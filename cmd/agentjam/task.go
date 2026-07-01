package main

import (
	"fmt"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/task"
	"github.com/JamieDF/agentjam/internal/task/filestore"
)

func taskCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "task",
		Short: "Manage tasks",
		Long: `Tasks are persistent work records. They survive context compaction,
session restarts, and mode swaps. Each task has structured progress logs
that any agent (or human) can read to pick up exactly where the previous
one left off.`,
	}

	cmd.AddCommand(
		taskListCmd(),
		taskNewCmd(),
		taskShowCmd(),
		taskStatusCmd(),
		taskAssignCmd(),
		taskLogCmd(),
	)

	return cmd
}

func openTaskStore() (*filestore.Store, error) {
	return filestore.New(config.TasksPath())
}

func taskListCmd() *cobra.Command {
	var (
		status   string
		projectF string
		tag      string
	)

	cmd := &cobra.Command{
		Use:     "list",
		Short:   "List tasks",
		Aliases: []string{"ls"},
		RunE: func(cmd *cobra.Command, _ []string) error {
			s, err := openTaskStore()
			if err != nil {
				return err
			}

			opts := task.ListOptions{
				Project: projectF,
				Status:  task.Status(status),
			}
			if tag != "" {
				opts.Tags = strings.Split(tag, ",")
			}

			tasks, err := s.List(opts)
			if err != nil {
				return err
			}

			if len(tasks) == 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "No tasks.")
				return nil
			}

			fmt.Fprintf(cmd.OutOrStdout(), "%-32s %-12s %-10s %-30s\n",
				"ID", "STATUS", "PRIORITY", "TITLE")
			for _, t := range tasks {
				fmt.Fprintf(cmd.OutOrStdout(), "%-32s %-12s %-10s %s\n",
					t.ID, t.Status, t.Priority, truncate(t.Title, 40))
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&status, "status", "", "Filter by status")
	cmd.Flags().StringVar(&projectF, "project", "", "Filter by project")
	cmd.Flags().StringVar(&tag, "tag", "", "Filter by tag (comma-separated)")
	return cmd
}

func taskNewCmd() *cobra.Command {
	var (
		title      string
		priority   string
		projectF   string
		desc       string
		acceptance []string
		outOfScope []string
		tags       []string
	)

	cmd := &cobra.Command{
		Use:   "new",
		Short: "Create a new task",
		Long: `Create a new task with title, acceptance criteria, and optional metadata.

Example:
  harness task new \
    --title "Add dark mode toggle" \
    --project my-app \
    --priority medium \
    --acceptance "Toggle visible in settings" \
    --acceptance "Choice persists across sessions"`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if title == "" {
				return errs.Wrap(errs.ErrInvalid, "--title is required")
			}

			s, err := openTaskStore()
			if err != nil {
				return err
			}

			t := &task.Task{
				ID:                 task.NewID(projectF),
				Project:            projectF,
				Title:              title,
				Description:        desc,
				Priority:           task.Priority(priority),
				AcceptanceCriteria: acceptance,
				OutOfScope:         outOfScope,
				Tags:               tags,
				CreatedBy:          "user",
				Status:             task.StatusOpen,
			}
			if t.Priority == "" {
				t.Priority = task.PriorityMedium
			}

			if err := s.Create(t); err != nil {
				return err
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Created task %q.\n", t.ID)
			return nil
		},
	}

	cmd.Flags().StringVar(&title, "title", "", "Task title (required)")
	cmd.Flags().StringVar(&priority, "priority", "medium", "Priority (low/medium/high/urgent)")
	cmd.Flags().StringVar(&projectF, "project", "", "Owning project")
	cmd.Flags().StringVar(&desc, "description", "", "Long description")
	cmd.Flags().StringSliceVar(&acceptance, "acceptance", nil, "Acceptance criterion (repeatable)")
	cmd.Flags().StringSliceVar(&outOfScope, "out-of-scope", nil, "Out-of-scope item (repeatable)")
	cmd.Flags().StringSliceVar(&tags, "tag", nil, "Tag (repeatable)")

	_ = cmd.MarkFlagRequired("title")
	return cmd
}

func taskShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "show <id>",
		Short:   "Show task details",
		Aliases: []string{"get"},
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := openTaskStore()
			if err != nil {
				return err
			}
			t, err := s.Get(task.ID(args[0]))
			if err != nil {
				return err
			}
			return renderTask(cmd, t)
		},
	}
}

func taskStatusCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "status <id> <new-status>",
		Short: "Set task status",
		Long: `Transition a task to a new status. Valid statuses:
  draft, open, planned, in_progress, blocked, review, done, abandoned`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := openTaskStore()
			if err != nil {
				return err
			}
			id := task.ID(args[0])
			newStatus := task.Status(args[1])
			if err := s.SetStatus(id, newStatus); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Set %q to %s.\n", id, newStatus)
			return nil
		},
	}
}

func taskAssignCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "assign <id> <agent-id>",
		Short: "Assign a task to an agent (pass empty agent to unassign)",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := openTaskStore()
			if err != nil {
				return err
			}
			id := task.ID(args[0])
			agent := ""
			if len(args) > 1 {
				agent = args[1]
			}
			if err := s.Assign(id, agent); err != nil {
				return err
			}
			if agent == "" {
				fmt.Fprintf(cmd.OutOrStdout(), "Unassigned %q.\n", id)
			} else {
				fmt.Fprintf(cmd.OutOrStdout(), "Assigned %q to %q.\n", id, agent)
			}
			return nil
		},
	}
}

func taskLogCmd() *cobra.Command {
	var (
		entryFlag string
		statusF   string
		next      string
	)

	cmd := &cobra.Command{
		Use:   "log <id>",
		Short: "Append a progress entry to a task",
		Long: `Log a progress entry to a task. Use this after every meaningful action
the agent takes — the progress log is the recovery point if context is lost.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if entryFlag == "" {
				return errs.Wrap(errs.ErrInvalid, "--entry is required")
			}
			s, err := openTaskStore()
			if err != nil {
				return err
			}
			e := task.ProgressEntry{
				Entry:    entryFlag,
				Status:   task.Status(statusF),
				NextStep: next,
				Caller:   "user",
			}
			if err := s.LogProgress(task.ID(args[0]), e); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Logged entry to %q.\n", args[0])
			return nil
		},
	}

	cmd.Flags().StringVar(&entryFlag, "entry", "", "Progress entry text (required)")
	cmd.Flags().StringVar(&statusF, "status", "", "Optional new status")
	cmd.Flags().StringVar(&next, "next", "", "Next step description")

	_ = cmd.MarkFlagRequired("entry")
	return cmd
}

func renderTask(cmd *cobra.Command, t *task.Task) error {
	w := cmd.OutOrStdout()
	fmt.Fprintf(w, "ID:          %s\n", t.ID)
	fmt.Fprintf(w, "Project:     %s\n", t.Project)
	fmt.Fprintf(w, "Title:       %s\n", t.Title)
	fmt.Fprintf(w, "Status:      %s\n", t.Status)
	fmt.Fprintf(w, "Priority:    %s\n", t.Priority)
	fmt.Fprintf(w, "Assigned:    %s\n", t.AssignedTo)
	fmt.Fprintf(w, "Created:     %s\n", t.CreatedAt.Format("2006-01-02 15:04"))
	fmt.Fprintf(w, "Updated:     %s\n", t.UpdatedAt.Format("2006-01-02 15:04"))

	if len(t.Tags) > 0 {
		fmt.Fprintf(w, "Tags:        %s\n", strings.Join(t.Tags, ", "))
	}
	if t.Description != "" {
		fmt.Fprintf(w, "\nDescription:\n%s\n", t.Description)
	}
	if len(t.AcceptanceCriteria) > 0 {
		fmt.Fprintln(w, "\nAcceptance Criteria:")
		for i, c := range t.AcceptanceCriteria {
			fmt.Fprintf(w, "  %d. %s\n", i+1, c)
		}
	}
	if len(t.OutOfScope) > 0 {
		fmt.Fprintln(w, "\nOut of Scope:")
		for _, c := range t.OutOfScope {
			fmt.Fprintf(w, "  - %s\n", c)
		}
	}
	if len(t.Steps) > 0 {
		fmt.Fprintln(w, "\nSteps:")
		for _, s := range t.Steps {
			marker := "[ ]"
			if s.Status == task.StatusDone {
				marker = "[x]"
			} else if s.Status == task.StatusInProgress {
				marker = "[~]"
			}
			fmt.Fprintf(w, "  %s %s %s\n", marker, s.ID, s.Title)
		}
	}

	if len(t.Progress) > 0 {
		fmt.Fprintln(w, "\nProgress Log:")
		// Most recent first.
		entries := make([]task.ProgressEntry, len(t.Progress))
		copy(entries, t.Progress)
		sort.Slice(entries, func(i, j int) bool {
			return entries[i].Timestamp.After(entries[j].Timestamp)
		})
		for _, e := range entries {
			fmt.Fprintf(w, "  %s [%s] %s\n",
				e.Timestamp.Format("2006-01-02 15:04"), e.Status, e.Entry)
		}
	}
	return nil
}
