// Command agentjam — session_run.go implements the hidden `agentjam session run`
// subcommand. This is the background process that holds the driver alive
// when a session is started with --detach.
//
// The parent (`agentjam session start --detach`) forks this command with
// the same flags it received. This command:
//
//  1. Calls session.Init() to create the session and start the driver.
//  2. Writes a PID file so other CLI invocations can discover it.
//  3. Opens a unix socket and serves events to connected clients.
//  4. Waits for SIGTERM/SIGINT, then cleans up and exits.
package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/container"
	pstore "github.com/JamieDF/agentjam/internal/project/filestore"
	"github.com/JamieDF/agentjam/internal/session"
	tstore "github.com/JamieDF/agentjam/internal/task/filestore"
)

func sessionRunCmd() *cobra.Command {
	var (
		taskID          string
		projectID       string
		mode            string
		containerFlag   bool
		image           string
		privilegedDebug bool
		driverKind      string
	)

	cmd := &cobra.Command{
		Use:    "run <id>",
		Short:  "Run a session in the background (internal)",
		Hidden: true,
		Args:   cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			sessionID := args[0]
			ctx := cmd.Context()

			sessionsDir := config.SessionsPath()

			// Write the log file early so the parent can read errors.
			logPath := filepath.Join(sessionsDir, sessionID+".log")
			logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
			if err != nil {
				return fmt.Errorf("open log file: %w", err)
			}
			defer logFile.Close()

			mgr, err := session.New(sessionsDir)
			if err != nil {
				fmt.Fprintf(logFile, "ERROR: create session manager: %v\n", err)
				return err
			}

			ts, err := tstore.New(config.TasksPath())
			if err != nil {
				fmt.Fprintf(logFile, "ERROR: create task store: %v\n", err)
				return err
			}

			ps, err := pstore.New(config.ProjectsPath())
			if err != nil {
				fmt.Fprintf(logFile, "ERROR: create project store: %v\n", err)
				return err
			}

			var profile *container.IsolationProfile
			if privilegedDebug {
				p := container.PrivilegedDebugProfile()
				profile = &p
			}

			opts := session.Options{
				ID:               sessionID,
				TaskID:           taskID,
				ProjectID:        projectID,
				Mode:             driver.Mode(mode),
				Container:        containerFlag,
				ContainerImage:   image,
				ContainerProfile: profile,
				PrivilegedDebug:  privilegedDebug,
				DriverKind:        driverKind,
				TaskStore:        ts,
				ProjectStore:     ps,
				WorktreeBase:     filepath.Join(config.Home(), "worktrees"),
				VaultSocketPath:  "/run/agentjam/vault.sock",
			}

			s, rt, err := session.Init(ctx, mgr, opts)
			if err != nil {
				fmt.Fprintf(logFile, "ERROR: init session: %v\n", err)
				return fmt.Errorf("init session: %w", err)
			}

			fmt.Fprintf(logFile, "Session %s started (driver=%s)\n", s.ID, s.DriverID)

			// Write PID file — this is the "ready" signal for the parent.
			pidPath := filepath.Join(sessionsDir, sessionID+".pid")
			if err := os.WriteFile(pidPath, []byte(fmt.Sprintf("%d", os.Getpid())), 0o600); err != nil {
				rt.Cleanup(ctx)
				return fmt.Errorf("write pid file: %w", err)
			}

			// Open event socket.
			sockPath := filepath.Join(sessionsDir, sessionID+".sock")
			listener, err := net.Listen("unix", sockPath)
			if err != nil {
				rt.Cleanup(ctx)
				os.Remove(pidPath)
				return fmt.Errorf("listen on event socket: %w", err)
			}
			_ = os.Chmod(sockPath, 0o600)

			// Set up signal handling.
			sigCh := make(chan os.Signal, 1)
			signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

			// Run the event server in a goroutine so the main goroutine
			// can receive signals.
			es := newEventServer(listener, rt.Driver())
			go es.run()

			// Wait for a signal or the event server to finish (driver stopped).
			select {
			case sig := <-sigCh:
				fmt.Fprintf(logFile, "Received signal %v, shutting down...\n", sig)
			case <-es.done():
				fmt.Fprintf(logFile, "Event stream ended, shutting down...\n")
			}

			signal.Stop(sigCh)
			listener.Close()
			rt.Cleanup(ctx)

			// Update session record to stopped.
			s.Status = session.StatusStopped
			s.StoppedAt = time.Now().UTC()
			s.UpdatedAt = s.StoppedAt
			_ = mgr.Update(s)

			// Clean up IPC files.
			os.Remove(pidPath)
			os.Remove(sockPath)

			fmt.Fprintf(logFile, "Session %s stopped cleanly.\n", sessionID)
			return nil
		},
	}

	cmd.Flags().StringVar(&taskID, "task", "", "Task ID")
	cmd.Flags().StringVar(&projectID, "project", "", "Project ID")
	cmd.Flags().StringVar(&mode, "mode", "", "Agent mode")
	cmd.Flags().BoolVar(&containerFlag, "container", false, "Run in container")
	cmd.Flags().StringVar(&image, "image", "", "Container image override")
	cmd.Flags().BoolVar(&privilegedDebug, "privileged-debug", false, "Debug mode")
	cmd.Flags().StringVar(&driverKind, "driver", "opencode", "Driver kind")

	return cmd
}

// eventServer fans out driver events to connected socket clients.
type eventServer struct {
	listener net.Listener
	d        driver.Driver
	clients  map[net.Conn]bool
	mu       sync.Mutex
	doneCh   chan struct{}
}

func newEventServer(listener net.Listener, d driver.Driver) *eventServer {
	return &eventServer{
		listener: listener,
		d:        d,
		clients:  make(map[net.Conn]bool),
		doneCh:   make(chan struct{}),
	}
}

func (es *eventServer) done() <-chan struct{} { return es.doneCh }

// run accepts connections and forwards driver events to all clients.
// Returns when the driver's event channel closes.
func (es *eventServer) run() {
	// Accept loop.
	go func() {
		for {
			conn, err := es.listener.Accept()
			if err != nil {
				return
			}
			es.mu.Lock()
			es.clients[conn] = true
			es.mu.Unlock()
		}
	}()

	// Event forwarding loop.
	events := es.d.Events()
	for ev := range events {
		es.broadcast(ev)
	}

	// Event channel closed — driver stopped.
	close(es.doneCh)
	es.closeAllClients()
}

// broadcast sends an event to all connected clients. Drops clients that
// have disconnected.
func (es *eventServer) broadcast(ev driver.Event) {
	msg := struct {
		Type  string        `json:"type"`
		Event *driver.Event `json:"event"`
	}{
		Type:  "event",
		Event: &ev,
	}
	data, err := json.Marshal(msg)
	if err != nil {
		return
	}
	data = append(data, '\n')

	es.mu.Lock()
	defer es.mu.Unlock()
	for conn := range es.clients {
		if _, err := conn.Write(data); err != nil {
			conn.Close()
			delete(es.clients, conn)
		}
	}
}

func (es *eventServer) closeAllClients() {
	es.mu.Lock()
	defer es.mu.Unlock()
	for conn := range es.clients {
		conn.Close()
		delete(es.clients, conn)
	}
}
