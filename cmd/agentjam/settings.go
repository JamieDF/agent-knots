package main

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/settings"
)

func settingsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "settings",
		Short: "Manage global agentjam settings",
		Long: `Settings control the default agent backend, provider, model, UI theme,
container resource limits, and vault behavior.

Settings are stored in ~/.agentjam/settings.yaml (editable by hand with
'agentjam settings edit'). Use 'agentjam settings show' to see current
values, and 'agentjam settings set <key> <value>' to change one.`,
	}

	cmd.AddCommand(
		settingsShowCmd(),
		settingsSetCmd(),
		settingsUnsetCmd(),
		settingsEditCmd(),
	)

	return cmd
}

func settingsShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show",
		Short: "Show current settings",
		RunE: func(cmd *cobra.Command, _ []string) error {
			s, err := settings.Load(settingsPath())
			if err != nil {
				return err
			}
			cfg := s.Get()

			fmt.Fprintln(cmd.OutOrStdout(), "=== Agent ===")
			fmt.Fprintf(cmd.OutOrStdout(), "  default_driver:        %s\n", cfg.Agent.DefaultDriver)
			fmt.Fprintf(cmd.OutOrStdout(), "  provider:              %s\n", valOr(cfg.Agent.Provider, "(env / backend default)"))
			fmt.Fprintf(cmd.OutOrStdout(), "  model:                 %s\n", valOr(cfg.Agent.Model, "(env / backend default)"))
			fmt.Fprintf(cmd.OutOrStdout(), "  default_mode:          %s\n", cfg.Agent.DefaultMode)
			fmt.Fprintf(cmd.OutOrStdout(), "  cost_cap_per_session_usd: %.2f\n", cfg.Agent.CostCapPerSessionUSD)
			fmt.Fprintf(cmd.OutOrStdout(), "  pause_on_idle:         %v\n", cfg.Agent.PauseOnIdle)

			fmt.Fprintln(cmd.OutOrStdout(), "\n=== UI ===")
			fmt.Fprintf(cmd.OutOrStdout(), "  theme:                 %s\n", cfg.UI.Theme)
			fmt.Fprintf(cmd.OutOrStdout(), "  refresh_interval_s:    %d\n", cfg.UI.RefreshIntervalS)

			fmt.Fprintln(cmd.OutOrStdout(), "\n=== Container ===")
			fmt.Fprintf(cmd.OutOrStdout(), "  default_image:         %s\n", valOr(cfg.Container.DefaultImage, "(auto-detected)"))
			fmt.Fprintf(cmd.OutOrStdout(), "  cpu_cores:             %d\n", cfg.Container.ResourceLimits.CPUCores)
			fmt.Fprintf(cmd.OutOrStdout(), "  memory_mb:             %d\n", cfg.Container.ResourceLimits.MemoryMB)
			fmt.Fprintf(cmd.OutOrStdout(), "  disk_gb:               %d\n", cfg.Container.ResourceLimits.DiskGB)

			fmt.Fprintln(cmd.OutOrStdout(), "\n=== Vault ===")
			fmt.Fprintf(cmd.OutOrStdout(), "  unlocked_at_startup:   %v\n", cfg.Vault.UnlockedAtStartup)

			fmt.Fprintf(cmd.OutOrStdout(), "\nFile: %s\n", s.Path())
			return nil
		},
	}
}

func settingsSetCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "set <dot.path> <value>",
		Short: "Set a setting value",
		Long: `Set a single setting by its dotted path. Examples:

  agentjam settings set agent.default_driver pi
  agentjam settings set agent.provider anthropic
  agentjam settings set agent.model claude-sonnet-4-20250514
  agentjam settings set ui.theme light
  agentjam settings set container.resource_limits.cpu_cores 4`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			path := args[0]
			value := args[1]

			s, err := settings.Load(settingsPath())
			if err != nil {
				return err
			}

			if err := s.Set(path, value); err != nil {
				return fmt.Errorf("set %s: %w", path, err)
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Set %s = %s\n", path, value)
			return nil
		},
	}
}

func settingsUnsetCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "unset <dot.path>",
		Short: "Remove a setting (reverts to default)",
		Long: `Remove a setting so it reverts to its default value.

Example:
  agentjam settings unset agent.provider`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			path := args[0]

			s, err := settings.Load(settingsPath())
			if err != nil {
				return err
			}

			// Unset by writing the default value for the path.
			defaults := settings.Defaults()
			defaultVal := getDefaultByPath(defaults, path)
			if err := s.Set(path, fmt.Sprintf("%v", defaultVal)); err != nil {
				return fmt.Errorf("unset %s: %w", path, err)
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Reset %s to default\n", path)
			return nil
		},
	}
}

func settingsEditCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "edit",
		Short: "Open settings file in $EDITOR",
		Long: `Opens ~/.agentjam/settings.yaml in your default editor ($EDITOR).

If $EDITOR is not set, attempts to use vim, nano, or vi.`,
		RunE: func(_ *cobra.Command, _ []string) error {
			p := settingsPath()
			editor := os.Getenv("EDITOR")
			if editor == "" {
				for _, e := range []string{"vim", "nano", "vi"} {
					if _, err := exec.LookPath(e); err == nil {
						editor = e
						break
					}
				}
			}
			if editor == "" {
				return fmt.Errorf("no editor found: set $EDITOR or install vim/nano")
			}

			// Ensure the file exists so the editor doesn't complain.
			s, err := settings.Load(p)
			if err != nil {
				return err
			}
			// Force a save to create the file if it doesn't exist.
			_ = s.Set("ui.theme", s.Get().UI.Theme)

			cmd := exec.Command(editor, p)
			cmd.Stdin = os.Stdin
			cmd.Stdout = os.Stdout
			cmd.Stderr = os.Stderr
			return cmd.Run()
		},
	}
}

// settingsPath returns the path to the settings file.
func settingsPath() string {
	return fmt.Sprintf("%s/settings.yaml", config.Home())
}

// valOr returns val if non-empty, or fallback otherwise.
func valOr(val, fallback string) string {
	if val != "" {
		return val
	}
	return fallback
}

// getDefaultByPath extracts a default value from a Settings struct for the unset command.
func getDefaultByPath(s settings.Settings, path string) any {
	switch path {
	case "agent.default_driver":
		return s.Agent.DefaultDriver
	case "agent.provider":
		return s.Agent.Provider
	case "agent.model":
		return s.Agent.Model
	case "agent.default_mode":
		return s.Agent.DefaultMode
	case "agent.cost_cap_per_session_usd":
		return s.Agent.CostCapPerSessionUSD
	case "agent.pause_on_idle":
		return s.Agent.PauseOnIdle
	case "ui.theme":
		return s.UI.Theme
	case "ui.refresh_interval_s":
		return s.UI.RefreshIntervalS
	case "container.default_image":
		return s.Container.DefaultImage
	case "container.resource_limits.cpu_cores":
		return s.Container.ResourceLimits.CPUCores
	case "container.resource_limits.memory_mb":
		return s.Container.ResourceLimits.MemoryMB
	case "container.resource_limits.disk_gb":
		return s.Container.ResourceLimits.DiskGB
	case "vault.unlocked_at_startup":
		return s.Vault.UnlockedAtStartup
	default:
		return ""
	}
}
