// Package config defines global harness configuration and the home directory
// resolution logic.
//
// All harness data lives under a single root directory:
//   - ~/.harness/ by default
//   - overridden by HARNESS_HOME env var
//
// Subdirectories:
//   - vault/         encrypted credential store
//   - tasks/         persistent task files (YAML)
//   - projects/      project workspaces (YAML)
//   - modes/         default mode markdown files
//   - logs/          runtime logs
package config

import (
	"os"
	"path/filepath"
)

// Home returns the harness data root directory. Defaults to ~/.harness.
// Overridden by HARNESS_HOME.
func Home() string {
	if v := os.Getenv("HARNESS_HOME"); v != "" {
		return v
	}
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".harness")
	}
	return ".harness"
}

// EnsureDirs creates the standard harness directory structure under Home()
// if it doesn't exist.
func EnsureDirs() error {
	dirs := []string{
		filepath.Join(Home(), "vault"),
		filepath.Join(Home(), "tasks"),
		filepath.Join(Home(), "projects"),
		filepath.Join(Home(), "modes"),
		filepath.Join(Home(), "logs"),
		filepath.Join(Home(), "sessions"),
	}
	for _, d := range dirs {
		if err := os.MkdirAll(d, 0o700); err != nil {
			return err
		}
	}
	return nil
}

// VaultPath returns the path to the vault directory.
func VaultPath() string { return filepath.Join(Home(), "vault") }

// TasksPath returns the path to the tasks directory.
func TasksPath() string { return filepath.Join(Home(), "tasks") }

// ProjectsPath returns the path to the projects directory.
func ProjectsPath() string { return filepath.Join(Home(), "projects") }

// ModesPath returns the path to the modes directory.
func ModesPath() string { return filepath.Join(Home(), "modes") }

// LogsPath returns the path to the logs directory.
func LogsPath() string { return filepath.Join(Home(), "logs") }

// SessionsPath returns the path to the sessions directory.
func SessionsPath() string { return filepath.Join(Home(), "sessions") }