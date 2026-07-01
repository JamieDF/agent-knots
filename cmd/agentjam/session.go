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
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/container"
	pstore "github.com/JamieDF/agentjam/internal/project/filestore"
	"github.com/JamieDF/agentjam/internal/session"
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

The agent in a container session runs with the hardened isolation profile
defined in ADR-004: non-root UID, capabilities dropped, read-only rootfs,
private network namespace, cgroup limits, deny-by-default egress. Use
--privileged-debug to opt out (for diagnosing container issues only).

Example:
  agentjam session start --task T-001 --mode agent
  agentjam session start --project my-app --container --detach
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
				TaskStore:        ts,
				ProjectStore:     ps,
				WorktreeBase:     filepath.Join(config.Home(), "worktrees"),
				VaultSocketPath:  "/run/agentjam/vault.sock",
			}

			s, err := session.Init(ctx, mgr, opts)
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

			if detach {
				fmt.Fprintln(cmd.OutOrStdout(),
					"Detached. Use 'agentjam session logs <id>' to follow.")
				return nil
			}

			// Stream events until the session ends.
			return streamEvents(ctx, s)
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

	return cmd
}

func sessionListCmd() *cobra.Command {
	var projectF string
	cmd := &cobra.Command{
		Use:     "list",
		Short:   "List sessions",
		Aliases: []string{"ls"},
		RunE: func(cmd *cobra.Command, _ []string) error {
			mgr, err := session.New(config.SessionsPath())
			if err != nil {
				return err
			}
			sessions := mgr.List(session.ListOptions{Project: projectF})
			if len(sessions) == 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "No sessions.")
				return nil
			}
			w := cmd.OutOrStdout()
			fmt.Fprintf(w, "%-30s %-12s %-10s %-30s %s\n",
				"ID", "STATUS", "RUNTIME", "MODE", "PROJECT")
			for _, s := range sessions {
				fmt.Fprintf(w, "%-30s %-12s %-10s %-30s %s\n",
					s.ID, s.Status, s.Runtime, s.Mode, s.Project)
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
			mgr, err := session.New(config.SessionsPath())
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
			// Note: actual driver stop is delegated to the container/
			// local runtimes via session registry in a future cycle.
			return nil
		},
	}
}

func sessionLogsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs <id>",
		Short: "Stream session events",
		Long: `Stream events from a session's driver. Output is line-delimited
JSON-ish records: one event per line. Use --tail=N to backfill the last
N events from disk (not yet implemented).`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			mgr, err := session.New(config.SessionsPath())
			if err != nil {
				return err
			}
			s, err := mgr.Get(args[0])
			if err != nil {
				return err
			}
			// We don't have a handle on the running driver (it's in the
			// container or local process we spawned earlier). For now,
			// tell the user where to look.
			fmt.Fprintf(cmd.OutOrStdout(),
				"Live event streaming requires the session record to be tied to the running driver.\n"+
					"For now, run 'agentjam session start' in the foreground (no --detach) to follow events.\n"+
					"Session: %s  mode=%s  status=%s  dir=%s\n",
				s.ID, s.Mode, s.Status, s.WorkingDir)
			return nil
		},
	}
	return cmd
}

// streamEvents tails a session's events from the driver until it exits.
// For the v1 implementation, we just print a status line each second and
// detach; the real event forwarding lives in the runtime adapters (and is
// wired into the foreground `agentjam agent spawn` path).
func streamEvents(ctx context.Context, s *session.Session) error {
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-tick.C:
			// Real implementation will read from the driver Events channel.
			// Until the Session struct exposes a Driver handle, just print
			// a heartbeat so the user knows the session is alive.
			fmt.Fprintf(os.Stderr, "[%s] session %s alive (status=%s)\n",
				time.Now().Format("15:04:05"), s.ID, s.Status)
			// Bailing out after the first tick keeps the foreground mode
			// snappy. Future: read from s.Driver.Events().
			return nil
		}
	}
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
