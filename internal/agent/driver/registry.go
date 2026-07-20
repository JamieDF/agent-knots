// Package driver defines the AgentDriver interface and provides a registry
// for pluggable backend implementations.
//
// Each agent backend (Pi, OpenCode, mock) registers a factory function with
// the default registry. The orchestrator picks which backend to use via a
// kind string (e.g. "pi", "mock"). Adding a new backend is a new package +
// one registration line in cmd/agentjam/main.go.
package driver

import (
	"fmt"
	"sort"
	"strings"
	"sync"
)

// FactoryOptions is what every driver factory receives. It abstracts away
// provider/model/settings so individual drivers don't need to know about
// the settings system.
type FactoryOptions struct {
	// Workdir is the working directory the agent operates in.
	Workdir string

	// ModeFile is the path to the mode markdown file (system prompt).
	ModeFile string

	// ID is the driver instance identifier. If empty, the factory generates one.
	ID string

	// TaskID is the assigned task (may be empty).
	TaskID string

	// Provider is the LLM provider, or empty to use the driver's default.
	Provider string

	// Model is the model pattern or ID, or empty to use the driver's default.
	Model string

	// Container, when non-nil, requests a containerized driver.
	Container *ContainerOptions
}

// ContainerOptions configures a containerized driver.
type ContainerOptions struct {
	// Image is the container image to use.
	Image string

	// WorktreeDir is the host directory to mount as the workspace.
	WorktreeDir string

	// ExtensionsDir is the host directory to mount as the extensions volume.
	ExtensionsDir string

	// Env is extra environment variables to set in the container.
	Env map[string]string
}

// Factory builds a Driver from FactoryOptions.
type Factory func(opts FactoryOptions) (Driver, error)

// Registry holds named driver factories.
type Registry struct {
	mu        sync.RWMutex
	factories map[string]Factory
}

// Default is the global driver registry. Register backends here at init().
var Default = &Registry{factories: make(map[string]Factory)}

// Register adds a driver factory under the given kind name.
func (r *Registry) Register(kind string, f Factory) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.factories[kind] = f
}

// Build constructs a Driver of the given kind.
func (r *Registry) Build(kind string, opts FactoryOptions) (Driver, error) {
	r.mu.RLock()
	f, ok := r.factories[kind]
	r.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("unknown driver: %q (registered: %s)", kind, strings.Join(r.namesLocked(), ", "))
	}
	return f(opts)
}

// Names returns the list of registered driver kinds, sorted.
func (r *Registry) Names() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.namesLocked()
}

// namesLocked returns sorted names. Caller must hold r.mu.
func (r *Registry) namesLocked() []string {
	keys := make([]string, 0, len(r.factories))
	for k := range r.factories {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
