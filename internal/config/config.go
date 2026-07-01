// Package config defines global agentjam configuration and the home directory
// resolution logic.
//
// All agentjam data lives under a single root directory:
//   - ~/.agentjam/ by default
//   - overridden by AGENTJAM_HOME env var
//
// On first call, Home() will auto-migrate a legacy ~/.agentjam/ directory
// to ~/.agentjam/ (renaming on disk) with a one-time stderr notice. This
// only fires when ~/.agentjam/ exists and ~/.agentjam/ does not.
//
// Subdirectories:
//   - vault/         encrypted credential store
//   - tasks/         persistent task files (YAML)
//   - projects/      project workspaces (YAML)
//   - modes/         default mode markdown files
//   - logs/          runtime logs
package config

import (
	"fmt"
	"os"
	"path/filepath"
)

// Home returns the agentjam data root directory. Defaults to ~/.agentjam.
// Overridden by AGENTJAM_HOME.
//
// If neither AGENTJAM_HOME nor ~/.agentjam/ exists, but a legacy
// ~/.agentjam/ directory does, it is renamed to ~/.agentjam/ in place.
// Safe to call repeatedly: migration runs at most once per process.
func Home() string {
	if v := os.Getenv("AGENTJAM_HOME"); v != "" {
		return v
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ".agentjam"
	}
	newDir := filepath.Join(home, ".agentjam")
	if _, err := os.Stat(newDir); err == nil {
		return newDir
	}
	oldDir := filepath.Join(home, ".agentjam")
	if _, err := os.Stat(oldDir); err == nil {
		if err := os.Rename(oldDir, newDir); err == nil {
			fmt.Fprintf(os.Stderr,
				"agentjam: migrated %s → %s (one-time, from prior 'agentjam' install)\n",
				oldDir, newDir)
		} else {
			fmt.Fprintf(os.Stderr,
				"agentjam: could not migrate %s → %s (%v); using %s\n",
				oldDir, newDir, err, newDir)
		}
		return newDir
	}
	return newDir
}

// EnsureDirs creates the standard agentjam directory structure under Home()
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
