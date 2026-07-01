package main

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/agent/driver/opencode"
	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/mode"
	"github.com/JamieDF/agentjam/internal/project"
	"github.com/JamieDF/agentjam/internal/project/filestore"
	"github.com/JamieDF/agentjam/internal/task"
	taskstore "github.com/JamieDF/agentjam/internal/task/filestore"
)

func agentCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "agent",
		Short: "Run AI coding agents",
		Long: `Spawn and manage AI coding agents. Agents are driven by OpenCode
(https://opencode.ai) via the Go SDK. They run with a chosen mode
(assistant, agent, reviewer, etc.) and operate on a project's directory.

Subcommands let you spawn a new agent on a task and list active agents.`,
	}

	cmd.AddCommand(
		agentSpawnCmd(),
		agentListCmd(),
	)

	return cmd
}

func agentSpawnCmd() *cobra.Command {
	var (
		taskID  string
		modeF   string
		dir     string
		baseURL string
	)

	cmd := &cobra.Command{
		Use:   "spawn",
		Short: "Spawn an agent to work a task",
		Long: `Spawn a new agent. The agent starts in the specified mode (default:
agent) and operates on the task's project directory.

Example:
  agentjam agent spawn --task T-2026-01-01-001 --mode agent`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx := cmd.Context()

			// Resolve directory: --dir flag, or task's project.
			if dir == "" && taskID != "" {
				ts, err := taskstore.New(config.TasksPath())
				if err != nil {
					return err
				}
				t, err := ts.Get(task.ID(taskID))
				if err != nil {
					return err
				}
				ps, err := filestore.New(config.ProjectsPath())
				if err != nil {
					return err
				}
				p, err := ps.Get(project.ID(t.Project))
				if err != nil {
					return err
				}
				dir = p.WorkspaceRoot
			}
			if dir == "" {
				return fmt.Errorf("--dir is required (or specify --task with a project that has a workspace)")
			}

			// Resolve mode. Warn if not found.
			if modeF == "" {
				modeF = "agent"
			}
			mloader, err := mode.NewLoader(config.ModesPath())
			if err == nil {
				if _, err := mloader.Load(modeF); err != nil {
					fmt.Fprintf(cmd.ErrOrStderr(),
						"warning: mode %q not found, using as-is\n", modeF)
				}
			}

			d, err := opencode.New(opencode.Options{
				Directory: dir,
				BaseURL:   baseURL,
			})
			if err != nil {
				return err
			}

			if err := d.Start(ctx); err != nil {
				return err
			}
			if err := d.SetMode(ctx, driver.Mode(modeF)); err != nil {
				return err
			}

			// If a task was given, send the task description as the first
			// message.
			if taskID != "" {
				ts, _ := taskstore.New(config.TasksPath())
				if t, err := ts.Get(task.ID(taskID)); err == nil {
					prompt := buildTaskPrompt(t)
					if err := d.Send(ctx, driver.Message{
						Role:    "user",
						Content: prompt,
					}); err != nil {
						return err
					}
				}
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Spawned agent %s\n", d.ID())
			fmt.Fprintln(cmd.OutOrStdout(), "Streaming events (Ctrl-C to stop):")

			// Stream events to stdout.
			for ev := range d.Events() {
				fmt.Printf("[%s] %s\n", ev.Type, ev.Message)
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&taskID, "task", "", "Task ID to assign the agent")
	cmd.Flags().StringVar(&modeF, "mode", "agent", "Mode (assistant, agent, reviewer, security, junior-dev, senior-dev)")
	cmd.Flags().StringVar(&dir, "dir", "", "Working directory (overrides task's project)")
	cmd.Flags().StringVar(&baseURL, "base-url", "", "OpenCode server URL (default: localhost)")

	return cmd
}

func agentListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List active agents",
		RunE: func(cmd *cobra.Command, _ []string) error {
			fmt.Fprintln(cmd.OutOrStdout(), "Active agent tracking: not yet implemented in v1.")
			fmt.Fprintln(cmd.OutOrStdout(), "Use `agentjam agent spawn` to start an agent in the foreground.")
			return nil
		},
	}
}
