package main

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"

	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/project"
	"github.com/JamieDF/agentjam/internal/project/filestore"
)

func projectCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "project",
		Short: "Manage project workspaces",
		Long: `Projects are multi-repo workspaces. A project bundles N git repos into one
logical unit, with project-level settings (build commands, conventions, vault
scope) and a task namespace.

Subcommands let you create, list, switch, edit, and delete projects.`,
	}

	cmd.AddCommand(
		projectListCmd(),
		projectCreateCmd(),
		projectSwitchCmd(),
		projectShowCmd(),
		projectDeleteCmd(),
		projectActiveCmd(),
	)

	return cmd
}

func openProjectStore() (*filestore.Store, error) {
	return filestore.New(config.ProjectsPath())
}

func projectListCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "list",
		Short:   "List all projects",
		Aliases: []string{"ls"},
		RunE: func(cmd *cobra.Command, _ []string) error {
			s, err := openProjectStore()
			if err != nil {
				return err
			}

			projects, err := s.List(project.ListOptions{})
			if err != nil {
				return err
			}

			active, _ := s.Active()

			if len(projects) == 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "No projects. Run `harness project create` to make one.")
				return nil
			}

			fmt.Fprintf(cmd.OutOrStdout(), "%-20s %-30s %-10s %s\n", "ID", "NAME", "ACTIVE", "REPOS")
			for _, p := range projects {
				marker := ""
				if p.ID == active {
					marker = "●"
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%-20s %-30s %-10s %d\n",
					p.ID, truncate(p.Name, 30), marker, len(p.Repos))
			}
			return nil
		},
	}
}

func projectCreateCmd() *cobra.Command {
	var (
		name   string
		repo   string
		branch string
		role   string
		root   string
	)

	cmd := &cobra.Command{
		Use:   "create <id>",
		Short: "Create a new project",
		Long: `Create a new project workspace.

Example:
  harness project create my-app \
    --name "My Cool App" \
    --repo [email protected]:org/app.git \
    --branch main \
    --role frontend`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id := args[0]
			if name == "" {
				name = id
			}

			p := &project.Project{
				ID:            project.ID(id),
				Name:          name,
				WorkspaceRoot: root,
				Repos: []project.Repo{
					{
						Path:   ".",
						Remote: repo,
						Branch: branch,
						Role:   role,
					},
				},
				Models: project.Models{
					Default: "claude-sonnet-4",
					Agent:   "claude-sonnet-4",
					Cheap:   "gpt-4o-mini",
				},
			}

			s, err := openProjectStore()
			if err != nil {
				return err
			}
			if err := s.Create(p); err != nil {
				return err
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Created project %q.\n", id)
			return nil
		},
	}

	cmd.Flags().StringVar(&name, "name", "", "Project display name")
	cmd.Flags().StringVar(&repo, "repo", "", "Git remote URL")
	cmd.Flags().StringVar(&branch, "branch", "main", "Default branch")
	cmd.Flags().StringVar(&role, "role", "", "Repo role label (frontend, backend, etc.)")
	cmd.Flags().StringVar(&root, "root", "", "Workspace root directory")

	return cmd
}

func projectSwitchCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "switch <id>",
		Short:   "Switch the active project",
		Aliases: []string{"use"},
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := openProjectStore()
			if err != nil {
				return err
			}
			id := project.ID(args[0])
			if err := s.SetActive(id); err != nil {
				return err
			}
			if err := s.Touch(id); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Switched to project %q.\n", id)
			return nil
		},
	}
}

func projectShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "show <id>",
		Short:   "Show project details",
		Aliases: []string{"get"},
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := openProjectStore()
			if err != nil {
				return err
			}
			p, err := s.Get(project.ID(args[0]))
			if err != nil {
				return err
			}

			data, err := yaml.Marshal(p)
			if err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), string(data))
			return nil
		},
	}
}

func projectDeleteCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "delete <id>",
		Short:   "Delete a project",
		Aliases: []string{"rm"},
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := openProjectStore()
			if err != nil {
				return err
			}
			id := project.ID(args[0])
			if err := s.Delete(id); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Deleted project %q.\n", id)
			return nil
		},
	}
}

func projectActiveCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "active",
		Short: "Show the active project",
		RunE: func(cmd *cobra.Command, _ []string) error {
			s, err := openProjectStore()
			if err != nil {
				return err
			}
			id, err := s.Active()
			if err != nil {
				return err
			}
			if id == "" {
				fmt.Fprintln(cmd.OutOrStdout(), "(no active project)")
				return nil
			}
			fmt.Fprintln(cmd.OutOrStdout(), id)
			return nil
		},
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if n <= 3 {
		return s[:n]
	}
	return s[:n-3] + "..."
}

// ProjectFilePath returns the canonical path for a project's YAML file.
// Used by the `edit` subcommand.
func projectFilePath(id string) string {
	return filepath.Join(config.ProjectsPath(), id+".yaml")
}

// Make sure os is used so the import isn't flagged.
var _ = os.Getenv
var _ = filepath.Join
