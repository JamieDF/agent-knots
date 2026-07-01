// Command agentjam — session.go implements `agentjam session`.
//
// Subcommands:
//   - start   — start a new agent session
//   - list    — list known sessions
//   - show    — show details of one session
//   - stop    — stop a running session
//   - logs    — stream events from a session
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/container"
	pstore "github.com/JamieDF/agentjam/internal/project/filestore"
	"github.com/JamieDF/agentjam/internal/session"
	"github.com/JamieDF/agentjam/internal/session/live"
	tstore "github.com/JamieDF/agentjam/internal/task/filestore"
)

func sessionCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "session",
		Short: "Manage agent sessions",
		Long: `An agent session is one running AI coding agent plus its bookkeeping.
Sessions are the runtime counterpart to tasks: a task is the work, a
session is the agent doing it. Use 'agentjam session start' to spawn one,
'list' to see what's running, 'stop' to shut it down.`,
	}

	cmd.AddCommand(
		sessionStartCmd(),
		sessionRunCmd(),
		sessionListCmd(),
		sessionShowCmd(),
		sessionStopCmd(),
		sessionLogsCmd(),
	)

	return cmd
}

func sessionStartCmd() *cobra.Command {
	var (
		taskID          string
		projectID       string
		mode            string
		containerFlag   bool
		image           string
		detach          bool
		privilegedDebug bool
		driverKind      string
		worktree        bool
	)

	cmd := &cobra.Command{
		Use:   "start",
		Short: "Start a new agent session",
		Long: `Start a new agent session. The agent runs either locally (default)
or in a hardened container (--container). When given a --task, the task's
project is auto-resolved; otherwise --project is required for container
sessions.

By default, the session is attached: events stream to stdout until the
agent exits. Pass --detach to return immediately; use 'agentjam session logs
<id>' to follow.

Use --driver=mock to run a scripted fake-event driver for testing and demos
without an LLM server. The mock driver emits realistic events (thinking,
tool calls, messages, progress) every ~1.5 seconds.

Use --worktree to create a git worktree on a per-session branch, isolating
the agent's changes from your main working copy. Container sessions always
use worktrees.

The agent in a container session runs with the hardened isolation profile
defined in ADR-004: non-root UID, capabilities dropped, read-only rootfs,
private network namespace, cgroup limits, deny-by-default egress. Use
--privileged-debug to opt out (for diagnosing container issues only).

Example:
  agentjam session start --task T-001 --mode agent
  agentjam session start --project my-app --container --detach
  agentjam session start --driver mock           # fake events, no LLM
  agentjam session start --task T-001 --worktree # isolated git worktree
  agentjam session start --task T-001 --privileged-debug`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx := cmd.Context()

			mgr, err := session.New(config.SessionsPath())
			if err != nil {
				return err
			}

			ts, err := tstore.New(config.TasksPath())
			if err != nil {
				return err
			}

			ps, err := pstore.New(config.ProjectsPath())
			if err != nil {
				return err
			}

			var profile *container.IsolationProfile
			if privilegedDebug {
				p := container.PrivilegedDebugProfile()
				profile = &p
				fmt.Fprintln(cmd.OutOrStdout(),
					"WARNING: privileged-debug profile — agent runs as root with no isolation.")
				fmt.Fprintln(cmd.OutOrStdout(),
					"  This is unsafe for untrusted code. Logging to ~/.agentjam/logs.")
			}

			opts := session.Options{
				ID:               generateSessionID(),
				TaskID:           taskID,
				ProjectID:        projectID,
				Mode:             driver.Mode(mode),
				Container:        containerFlag,
				ContainerImage:   image,
			ContainerProfile: profile,
			PrivilegedDebug:  privilegedDebug,
			DriverKind:       driverKind,
			UseWorktree:      worktree,
			TaskStore:        ts,
				ProjectStore:     ps,
				WorktreeBase:     filepath.Join(config.Home(), "worktrees"),
				VaultSocketPath:  "/run/agentjam/vault.sock",
			}

			if detach {
				return startDetached(ctx, opts)
			}

			s, rt, err := session.Init(ctx, mgr, opts)
			if err != nil {
				return fmt.Errorf("start session: %w", err)
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Started session %s\n", s.ID)
			fmt.Fprintf(cmd.OutOrStdout(), "  runtime:  %s\n", s.Runtime)
			fmt.Fprintf(cmd.OutOrStdout(), "  driver:   %s\n", s.DriverID)
			fmt.Fprintf(cmd.OutOrStdout(), "  project:  %s\n", s.Project)
			fmt.Fprintf(cmd.OutOrStdout(), "  task:     %s\n", s.Task)
			fmt.Fprintf(cmd.OutOrStdout(), "  mode:     %s\n", s.Mode)
			fmt.Fprintf(cmd.OutOrStdout(), "  dir:      %s\n", s.WorkingDir)

			// Stream events until the session ends or the user interrupts.
			return streamEvents(ctx, s, rt)
		},
	}

	cmd.Flags().StringVar(&taskID, "task", "", "Task ID to assign")
	cmd.Flags().StringVar(&projectID, "project", "", "Project ID (auto-resolved from --task)")
	cmd.Flags().StringVar(&mode, "mode", "", "Agent mode (assistant, agent, reviewer, security, etc.)")
	cmd.Flags().BoolVar(&containerFlag, "container", false, "Run in hardened container")
	cmd.Flags().StringVar(&image, "image", "", "Override container image")
	cmd.Flags().BoolVar(&detach, "detach", false, "Return immediately after starting")
	cmd.Flags().BoolVar(&privilegedDebug, "privileged-debug", false,
		"Opt out of isolation hardening (debug only)")
	cmd.Flags().StringVar(&driverKind, "driver", "opencode",
		"Driver implementation: opencode (default) or mock")
	cmd.Flags().BoolVar(&worktree, "worktree", false,
		"Create a git worktree on a per-session branch (local mode only; container always uses worktrees)")

	return cmd
}

func sessionListCmd() *cobra.Command {
	var projectF string
	cmd := &cobra.Command{
		Use:     "list",
		Short:   "List sessions",
		Aliases: []string{"ls"},
		RunE: func(cmd *cobra.Command, _ []string) error {
			sessionsDir := config.SessionsPath()
			mgr, err := session.New(sessionsDir)
			if err != nil {
				return err
			}
			sessions := mgr.List(session.ListOptions{Project: projectF})
			if len(sessions) == 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "No sessions.")
				return nil
			}

			// Build a set of live session IDs for status enrichment.
			liveSessions, _ := live.List(sessionsDir)
			liveIDs := make(map[string]bool, len(liveSessions))
			for _, ls := range liveSessions {
				liveIDs[ls.SessionID] = true
			}

			w := cmd.OutOrStdout()
			fmt.Fprintf(w, "%-30s %-14s %-10s %-10s %-30s %s\n",
				"ID", "STATUS", "RUNTIME", "DRIVER", "MODE", "PROJECT")
			for _, s := range sessions {
				status := string(s.Status)
				if liveIDs[s.ID] {
					status = "running*"
				}
				driverID := s.DriverID
				if len(driverID) > 10 {
					driverID = driverID[:10]
				}
				fmt.Fprintf(w, "%-30s %-14s %-10s %-10s %-30s %s\n",
					s.ID, status, s.Runtime, driverID, s.Mode, s.Project)
			}
			if len(liveIDs) > 0 {
				fmt.Fprintln(w, "\n* = live subprocess")
			}
			return nil
		},
	}
	cmd.Flags().StringVar(&projectF, "project", "", "Filter by project")
	return cmd
}

func sessionShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <id>",
		Short: "Show session details",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			mgr, err := session.New(config.SessionsPath())
			if err != nil {
				return err
			}
			s, err := mgr.Get(args[0])
			if err != nil {
				return err
			}
			w := cmd.OutOrStdout()
			fmt.Fprintf(w, "ID:         %s\n", s.ID)
			fmt.Fprintf(w, "Driver:     %s\n", s.DriverID)
			fmt.Fprintf(w, "Status:     %s\n", s.Status)
			fmt.Fprintf(w, "Runtime:    %s\n", s.Runtime)
			fmt.Fprintf(w, "Mode:       %s\n", s.Mode)
			fmt.Fprintf(w, "Project:    %s\n", s.Project)
			fmt.Fprintf(w, "Task:       %s\n", s.Task)
			fmt.Fprintf(w, "Started:    %s\n", s.StartedAt.Format(time.RFC3339))
			fmt.Fprintf(w, "Updated:    %s\n", s.UpdatedAt.Format(time.RFC3339))
			fmt.Fprintf(w, "WorkingDir: %s\n", s.WorkingDir)
			if len(s.Env) > 0 {
				fmt.Fprintln(w, "Env:")
				for k, v := range s.Env {
					fmt.Fprintf(w, "  %s=%s\n", k, v)
				}
			}
			return nil
		},
	}
}

func sessionStopCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "stop <id>",
		Short: "Stop a running session",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			sessionsDir := config.SessionsPath()

			// Try to stop the live subprocess.
			ls, err := live.Get(sessionsDir, args[0])
			if err == nil {
				fmt.Fprintf(cmd.OutOrStdout(), "Stopping session %s (pid %d)...\n", args[0], ls.PID)
				if err := ls.Stop(); err != nil {
					return fmt.Errorf("stop session: %w", err)
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Stopped %s.\n", args[0])
			} else {
				// Session not running as a subprocess — just update the record.
				mgr, err := session.New(sessionsDir)
				if err != nil {
					return err
				}
				s, err := mgr.Get(args[0])
				if err != nil {
					return err
				}
				s.Status = session.StatusStopped
				s.StoppedAt = time.Now().UTC()
				s.UpdatedAt = s.StoppedAt
				if err := mgr.Update(s); err != nil {
					return err
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Stopped %s.\n", s.ID)
			}
			return nil
		},
	}
}

func sessionLogsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs <id>",
		Short: "Stream session events",
		Long: `Stream events from a running session's driver. The session must have
been started with --detach. Events are line-delimited and pretty-printed
to stdout. Press Ctrl-C to stop following (the session keeps running).`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			sessionsDir := config.SessionsPath()
			ls, err := live.Get(sessionsDir, args[0])
			if err != nil {
				return err
			}

			events, err := ls.Events()
			if err != nil {
				return fmt.Errorf("connect to session: %w", err)
			}

			// Handle Ctrl-C: just stop reading, don't kill the session.
			sigCh := make(chan os.Signal, 1)
			signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
			defer signal.Stop(sigCh)

			fmt.Fprintf(cmd.OutOrStdout(), "Following session %s (Ctrl-C to stop)...\n\n", args[0])

			for {
				select {
				case ev, ok := <-events:
					if !ok {
						fmt.Fprintln(cmd.OutOrStdout(), "\n[session ended]")
						return nil
					}
					printEvent(cmd.OutOrStdout(), ev)
				case <-sigCh:
					fmt.Fprintln(cmd.OutOrStdout(), "\n[stopped following]")
					return nil
				}
			}
		},
	}
	return cmd
}

// streamEvents reads from the driver's Events channel and prints each
// event to stdout until the channel closes or the context is cancelled.
// Handles SIGINT/SIGTERM by stopping the driver gracefully.
func streamEvents(ctx context.Context, s *session.Session, rt session.Runtime) error {
	d := rt.Driver()
	if d == nil {
		return fmt.Errorf("no driver available for session %s", s.ID)
	}

	// Handle Ctrl-C / SIGTERM: stop the driver and cleanup.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	defer signal.Stop(sigCh)

	go func() {
		select {
		case <-sigCh:
			fmt.Fprintln(os.Stderr, "\nInterrupt received, stopping session...")
			d.Stop(ctx)
			rt.Cleanup(ctx)
		case <-ctx.Done():
		}
	}()

	events := d.Events()
	for ev := range events {
		printEvent(os.Stdout, ev)
	}

	// Channel closed — driver stopped. Final snapshot.
	state, err := d.Snapshot(ctx)
	if err == nil {
		fmt.Fprintf(os.Stderr, "\nSession ended. Tokens: %d  Cost: $%.4f  Uptime: %s\n",
			state.TokensUsed, state.CostUSD, state.Uptime.Round(time.Second))
	}
	rt.Cleanup(ctx)
	return nil
}

// printEvent renders a driver event as a single line to w.
func printEvent(w io.Writer, ev driver.Event) {
	ts := ev.Timestamp.Format("15:04:05")
	switch ev.Type {
	case driver.EventMessage:
		fmt.Fprintf(w, "%s  %s\n", ts, ev.Message)
	case driver.EventThinking:
		fmt.Fprintf(w, "%s  [thinking] %s\n", ts, ev.Message)
	case driver.EventToolCall:
		if ev.ToolCall != nil {
			fmt.Fprintf(w, "%s  [tool] %s %s\n", ts, ev.ToolCall.Name, formatArgs(ev.ToolCall.Args))
		} else {
			fmt.Fprintf(w, "%s  [tool] %s\n", ts, ev.Message)
		}
	case driver.EventToolResult:
		fmt.Fprintf(w, "%s  [result] %s\n", ts, ev.Message)
	case driver.EventProgress:
		fmt.Fprintf(w, "%s  [progress] %s\n", ts, ev.Message)
	case driver.EventError:
		fmt.Fprintf(w, "%s  [error] %s\n", ts, ev.Error)
	default:
		if ev.Message != "" {
			fmt.Fprintf(w, "%s  %s\n", ts, ev.Message)
		}
	}
}

// formatArgs renders tool call args compactly for display.
func formatArgs(args map[string]any) string {
	if len(args) == 0 {
		return ""
	}
	b, err := json.Marshal(args)
	if err != nil {
		return ""
	}
	return string(b)
}

// startDetached forks a background `agentjam session run <id>` subprocess
// and waits for it to signal readiness via the PID file.
func startDetached(_ context.Context, opts session.Options) error {
	self, err := os.Executable()
	if err != nil {
		return fmt.Errorf("find agentjam executable: %w", err)
	}

	sessionsDir := config.SessionsPath()
	logPath := filepath.Join(sessionsDir, opts.ID+".log")

	// Open the log file for the child's stdout/stderr.
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return fmt.Errorf("open session log: %w", err)
	}

	// Build the child command with the same options.
	args := []string{"session", "run", opts.ID,
		"--driver", opts.DriverKind,
		"--mode", string(opts.Mode),
	}
	if opts.TaskID != "" {
		args = append(args, "--task", opts.TaskID)
	}
	if opts.ProjectID != "" {
		args = append(args, "--project", opts.ProjectID)
	}
	if opts.Container {
		args = append(args, "--container")
	}
	if opts.ContainerImage != "" {
		args = append(args, "--image", opts.ContainerImage)
	}
	if opts.PrivilegedDebug {
		args = append(args, "--privileged-debug")
	}
	if opts.UseWorktree {
		args = append(args, "--worktree")
	}

	cmd := exec.Command(self, args...)
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true} // detach from terminal

	if err := cmd.Start(); err != nil {
		logFile.Close()
		return fmt.Errorf("start session subprocess: %w", err)
	}
	// Don't wait — the child runs independently.
	_ = cmd.Process.Release()
	logFile.Close()

	// Poll for the PID file (success) or child exit (failure).
	pidPath := filepath.Join(sessionsDir, opts.ID+".pid")
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(pidPath); err == nil {
			// PID file exists — session started successfully.
			break
		}
		// Check if child process died.
		if cmd.ProcessState != nil {
			// Process exited before writing PID — read error from log.
			errMsg := readLogTail(logPath, 5)
			return fmt.Errorf("session process exited prematurely:\n%s", errMsg)
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Verify the PID file actually appeared.
	if _, err := os.Stat(pidPath); err != nil {
		return fmt.Errorf("session did not start within 15 seconds; check %s", logPath)
	}

	// Load the persisted session record and print info.
	mgr, err := session.New(sessionsDir)
	if err != nil {
		return err
	}
	s, err := mgr.Get(opts.ID)
	if err != nil {
		return err
	}

	fmt.Printf("Started session %s (detached)\n", s.ID)
	fmt.Printf("  runtime:  %s\n", s.Runtime)
	fmt.Printf("  driver:   %s\n", s.DriverID)
	fmt.Printf("  project:  %s\n", s.Project)
	fmt.Printf("  task:     %s\n", s.Task)
	fmt.Printf("  mode:     %s\n", s.Mode)
	fmt.Printf("  dir:      %s\n", s.WorkingDir)
	fmt.Printf("  log:      %s\n", logPath)
	fmt.Println("Use 'agentjam session logs <id>' to follow events.")
	return nil
}

// readLogTail reads the last n lines of a file as a string.
func readLogTail(path string, n int) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return "(could not read log)"
	}
	lines := strings.Split(string(data), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	return strings.Join(lines, "\n")
}

// generateSessionID is a thin wrapper around session's id generator; kept
// here so the CLI can produce IDs without exporting the internals.
func generateSessionID() string {
	now := time.Now().UTC()
	suffix := now.Format("150405")
	const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
	s := make([]byte, 4)
	n := now.UnixNano()
	for i := range s {
		s[i] = alphabet[n%36]
		n /= 36
		if n == 0 {
			n = now.UnixNano() >> 32
		}
	}
	return "cli-" + suffix + "-" + string(s)
}
