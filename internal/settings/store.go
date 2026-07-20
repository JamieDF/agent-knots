// Package settings provides a YAML-backed global settings store for agentjam.
//
// Settings live at ~/.agentjam/settings.yaml and are loaded at startup. The
// store is safe for concurrent use. Settings cascade: explicitly-set values
// override defaults; provider/model fall through to environment variables and
// then to the agent backend's own config.
package settings

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"gopkg.in/yaml.v3"
)

// Store holds global agentjam settings persisted to YAML.
type Store struct {
	path string
	mu   sync.RWMutex
	data Settings
}

// Settings is the top-level settings document.
type Settings struct {
	Agent     AgentSettings     `yaml:"agent"`
	UI        UISettings        `yaml:"ui"`
	Container ContainerSettings `yaml:"container"`
	Vault     VaultSettings     `yaml:"vault"`
}

// AgentSettings configures the agent backend.
type AgentSettings struct {
	// DefaultDriver is the driver kind used when not specified on the CLI.
	// Empty means "pi".
	DefaultDriver string `yaml:"default_driver,omitempty"`

	// Provider is the LLM provider (anthropic, openai, google, etc.).
	// Empty means fall through to env → agent's own config.
	Provider string `yaml:"provider,omitempty"`

	// Model is the model pattern or ID.
	// Empty means fall through to env → agent's own config.
	Model string `yaml:"model,omitempty"`

	// DefaultMode is the agent persona used when not specified on the CLI.
	// Empty means "agent".
	DefaultMode string `yaml:"default_mode,omitempty"`

	// CostCapPerSessionUSD is the maximum spend per session. 0 = no cap.
	CostCapPerSessionUSD float64 `yaml:"cost_cap_per_session_usd,omitempty"`

	// PauseOnIdle, when true, auto-pauses the agent after N seconds of idle.
	PauseOnIdle bool `yaml:"pause_on_idle,omitempty"`
}

// UISettings configures the cockpit UI.
type UISettings struct {
	// Theme is "dark" or "light".
	Theme string `yaml:"theme,omitempty"`

	// RefreshIntervalS is how often the agent list refreshes (seconds).
	RefreshIntervalS int `yaml:"refresh_interval_s,omitempty"`
}

// ContainerSettings configures the container runtime.
type ContainerSettings struct {
	// DefaultImage overrides the auto-detected container image.
	DefaultImage string `yaml:"default_image,omitempty"`

	// ResourceLimits sets per-container caps.
	ResourceLimits ContainerResourceLimits `yaml:"resource_limits,omitempty"`
}

// ContainerResourceLimits sets per-container resource caps.
type ContainerResourceLimits struct {
	CPUCores int `yaml:"cpu_cores,omitempty"` // 0 = no limit
	MemoryMB int `yaml:"memory_mb,omitempty"` // 0 = no limit
	DiskGB   int `yaml:"disk_gb,omitempty"`   // 0 = no limit
}

// VaultSettings configures the credential vault.
type VaultSettings struct {
	// UnlockedAtStartup, when true, attempts to unlock the vault on startup.
	UnlockedAtStartup bool `yaml:"unlocked_at_startup,omitempty"`
}

// Defaults returns a settings object with sensible defaults.
func Defaults() Settings {
	return Settings{
		Agent: AgentSettings{
			DefaultDriver: "pi",
			DefaultMode:   "agent",
		},
		UI: UISettings{
			Theme:            "dark",
			RefreshIntervalS: 2,
		},
		Container: ContainerSettings{
			ResourceLimits: ContainerResourceLimits{
				CPUCores: 2,
				MemoryMB: 4096,
				DiskGB:   10,
			},
		},
	}
}

// Load reads settings from path. If the file doesn't exist, returns defaults.
func Load(path string) (*Store, error) {
	s := &Store{
		path: path,
		data: Defaults(),
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return s, nil
		}
		return nil, fmt.Errorf("read settings: %w", err)
	}

	var loaded Settings
	if err := yaml.Unmarshal(data, &loaded); err != nil {
		return nil, fmt.Errorf("parse settings: %w", err)
	}

	// Merge: loaded values override defaults.
	s.data = mergeDefaults(loaded)
	return s, nil
}

// New creates an in-memory store from the given settings. Use this in tests.
func New(settings Settings) *Store {
	return &Store{
		data: mergeDefaults(settings),
	}
}

// Get returns the current settings.
func (s *Store) Get() Settings {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.data
}

// Set replaces a single dotted-path key and writes to disk immediately.
// Paths: "agent.default_driver", "agent.provider", "container.resource_limits.cpu_cores", etc.
func (s *Store) Set(keyPath, value string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if err := setByPath(&s.data, keyPath, value); err != nil {
		return err
	}
	return s.saveLocked()
}

// saveLocked writes current settings to disk. Caller must hold s.mu.
func (s *Store) saveLocked() error {
	if s.path == "" {
		return nil // in-memory only
	}
	if err := os.MkdirAll(filepath.Dir(s.path), 0o700); err != nil {
		return fmt.Errorf("create settings dir: %w", err)
	}
	data, err := yaml.Marshal(s.data)
	if err != nil {
		return fmt.Errorf("marshal settings: %w", err)
	}
	if err := os.WriteFile(s.path, data, 0o600); err != nil {
		return fmt.Errorf("write settings: %w", err)
	}
	return nil
}

// Path returns the file path, or empty for in-memory stores.
func (s *Store) Path() string { return s.path }

// mergeDefaults overlays user settings on top of defaults.
func mergeDefaults(user Settings) Settings {
	def := Defaults()

	if user.Agent.DefaultDriver != "" {
		def.Agent.DefaultDriver = user.Agent.DefaultDriver
	}
	if user.Agent.Provider != "" {
		def.Agent.Provider = user.Agent.Provider
	}
	if user.Agent.Model != "" {
		def.Agent.Model = user.Agent.Model
	}
	if user.Agent.DefaultMode != "" {
		def.Agent.DefaultMode = user.Agent.DefaultMode
	}
	if user.Agent.CostCapPerSessionUSD != 0 {
		def.Agent.CostCapPerSessionUSD = user.Agent.CostCapPerSessionUSD
	}
	if user.Agent.PauseOnIdle {
		def.Agent.PauseOnIdle = user.Agent.PauseOnIdle
	}
	if user.UI.Theme != "" {
		def.UI.Theme = user.UI.Theme
	}
	if user.UI.RefreshIntervalS != 0 {
		def.UI.RefreshIntervalS = user.UI.RefreshIntervalS
	}
	if user.Container.DefaultImage != "" {
		def.Container.DefaultImage = user.Container.DefaultImage
	}
	if user.Container.ResourceLimits.CPUCores != 0 {
		def.Container.ResourceLimits.CPUCores = user.Container.ResourceLimits.CPUCores
	}
	if user.Container.ResourceLimits.MemoryMB != 0 {
		def.Container.ResourceLimits.MemoryMB = user.Container.ResourceLimits.MemoryMB
	}
	if user.Container.ResourceLimits.DiskGB != 0 {
		def.Container.ResourceLimits.DiskGB = user.Container.ResourceLimits.DiskGB
	}
	if user.Vault.UnlockedAtStartup {
		def.Vault.UnlockedAtStartup = user.Vault.UnlockedAtStartup
	}
	return def
}
