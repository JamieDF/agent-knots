// Command agentjam is the entry point for the agentjam CLI.
//
// agentjam is a local-first orchestrator for AI coding agents. It manages
// projects, tasks, a credential vault, and runs agents (via Pi, OpenCode,
// or mock drivers) in interactive or autonomous modes.
//
// See the README for a quickstart or docs/architecture.md for design.
package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/agent/driver/mock"
	"github.com/JamieDF/agentjam/internal/agent/driver/opencode"
	pidriver "github.com/JamieDF/agentjam/internal/agent/driver/pi"
	"github.com/JamieDF/agentjam/internal/config"
)

func init() {
	// Register all known driver backends with the default registry.
	driver.Default.Register("mock", func(opts driver.FactoryOptions) (driver.Driver, error) {
		d := mock.New(mock.Options{
			ID:     opts.ID,
			TaskID: opts.TaskID,
		})
		return d, nil
	})

	driver.Default.Register("pi", func(opts driver.FactoryOptions) (driver.Driver, error) {
		if opts.Container != nil {
			return pidriver.NewContainer(pidriver.ContainerOptions{
				ID:            opts.ID,
				WorktreeDir:   opts.Container.WorktreeDir,
				ExtensionsDir: opts.Container.ExtensionsDir,
				Provider:      opts.Provider,
				Model:         opts.Model,
			})
		}
		return pidriver.New(pidriver.Options{
			ID:       opts.ID,
			Workdir:  opts.Workdir,
			ModeFile: opts.ModeFile,
			Provider: opts.Provider,
			Model:    opts.Model,
		})
	})

	driver.Default.Register("opencode", func(opts driver.FactoryOptions) (driver.Driver, error) {
		return opencode.New(opencode.Options{
			ID:        opts.ID,
			Directory: opts.Workdir,
			Title:     "agentjam-session-" + opts.ID,
		})
	})
}

var (
	// Version is set at build time via -ldflags.
	Version = "0.1.0"
	// Commit is set at build time via -ldflags.
	Commit = "dev"
)

func main() {
	if err := config.EnsureDirs(); err != nil {
		fmt.Fprintf(os.Stderr, "agentjam: failed to initialize directories: %v\n", err)
		os.Exit(1)
	}
	if err := rootCmd().Execute(); err != nil {
		os.Exit(1)
	}
}

func rootCmd() *cobra.Command {
	root := &cobra.Command{
		Use:   "agentjam",
		Short: "Local-first orchestrator for AI coding agents",
		Long: `agentjam is a platform for orchestrating multiple AI coding agents in parallel
across multi-repo projects. You stay in control: chat with one agent, watch
many others work autonomously, take over any of them, hand control back.

Free. Model-agnostic. Local-first.

Run 'agentjam <command> --help' for details on any subcommand.`,
		Version:      Version,
		SilenceUsage: true,
	}

	root.SetVersionTemplate("agentjam version {{.Version}} (commit {{.Commit}})\n")

	root.AddCommand(
		projectCmd(),
		taskCmd(),
		vaultCmd(),
		agentCmd(),
		sessionCmd(),
		cockpitCmd(),
		settingsCmd(),
		versionCmd(),
	)

	return root
}

func versionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print version information",
		RunE: func(cmd *cobra.Command, _ []string) error {
			fmt.Printf("agentjam %s (commit %s)\n", Version, Commit)
			return nil
		},
	}
}
