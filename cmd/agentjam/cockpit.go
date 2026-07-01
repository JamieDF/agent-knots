package main

import (
	"context"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	cockpit "github.com/JamieDF/agentjam/internal/cockpit/tui"
)

func cockpitCmd() *cobra.Command {
	var (
		web bool
	)

	cmd := &cobra.Command{
		Use:   "cockpit",
		Short: "Launch the concurrent agent cockpit",
		Long: `Launch the cockpit — the canonical management surface for harness.

By default, launches the keyboard-driven TUI cockpit. Use --web to launch
the web GUI (when implemented).

The cockpit is the place to:
  - See all running agents at a glance
  - Switch focus between agents
  - Take over / relinquish control
  - Manage tasks, vault, and project settings

Keybindings (TUI):
  ↑/↓ or j/k   navigate agents
  Enter or f   focus on selected agent
  Esc or b     zoom back to agent list
  p            pause selected agent
  r            resume selected agent
  a            assume control
  q            quit`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if web {
				fmt.Fprintln(cmd.OutOrStdout(),
					"Web GUI is planned but not yet implemented. Run without --web for the TUI cockpit.")
				return nil
			}

			// For v1, the cockpit launches with an empty agent registry.
			// Once the active-agent tracking is implemented, this will
			// be populated from the registry.
			registry := &emptyRegistry{}

			model := cockpit.NewModel(registry)
			program := tea.NewProgram(model, tea.WithAltScreen())

			// Handle Ctrl-C in the terminal.
			ctx, cancel := context.WithCancel(cmd.Context())
			defer cancel()
			go func() {
				<-ctx.Done()
				program.Quit()
			}()

			if _, err := program.Run(); err != nil {
				fmt.Fprintf(os.Stderr, "cockpit: %v\n", err)
				return err
			}
			return nil
		},
	}

	cmd.Flags().BoolVar(&web, "web", false, "Use web GUI (planned, not yet implemented)")
	return cmd
}

// emptyRegistry is a stub DriverRegistry that returns no agents. Used
// until the active-agent tracking is implemented.
type emptyRegistry struct{}

func (e *emptyRegistry) List() []driver.Driver { return nil }
func (e *emptyRegistry) Get(_ string) (driver.Driver, bool) {
	return nil, false
}
