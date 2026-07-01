// Package session provides session tracking and lifecycle management.
//
// A Session represents one running agent driver — its ID, mode, project,
// task, start time, and accumulated state. Sessions are persisted to disk
// so the cockpit can show all known agents even after a restart, and so
// sessions can be resumed.
//
// Sessions are lightweight records; the actual agent state lives in the
// driver. The session manager is the registry.
package session

import (
	"errors"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/harness/harness/internal/agent/driver"
	"github.com/harness/harness/internal/errs"
)

// Status is the session's lifecycle state.
type Status string

const (
	StatusStarting Status = "starting"
	StatusRunning  Status = "running"
	StatusPaused   Status = "paused"
	StatusBlocked  Status = "blocked"
	StatusStopped  Status = "stopped"
	StatusError    Status = "error"
)

// Session represents one running agent.
type Session struct {
	// ID is the session's unique identifier.
	ID string `yaml:"id"`

	// DriverID is the underlying driver's identifier.
	DriverID string `yaml:"driver_id"`

	// Mode is the agent's behavioral mode.
	Mode driver.Mode `yaml:"mode"`

	// Project is the owning project ID (empty if not project-scoped).
	Project string `yaml:"project,omitempty"`

	// Task is the assigned task ID (empty if no task).
	Task string `yaml:"task,omitempty"`

	// Status is the session's lifecycle state.
	Status Status `yaml:"status"`

	// Runtime is "local" or "container". Empty defaults to "local".
	Runtime string `yaml:"runtime,omitempty"`

	// Env is the per-session environment applied to the agent process.
	Env map[string]string `yaml:"env,omitempty"`

	// StartedAt is when the session was created.
	StartedAt time.Time `yaml:"started_at"`

	// UpdatedAt is the last modification.
	UpdatedAt time.Time `yaml:"updated_at"`

	// StoppedAt is when the session ended (zero if still running).
	StoppedAt time.Time `yaml:"stopped_at,omitempty"`

	// TokensUsed is the cumulative token count.
	TokensUsed int64 `yaml:"tokens_used"`

	// CostUSD is the cumulative spend, if reported.
	CostUSD float64 `yaml:"cost_usd,omitempty"`

	// WorkingDir is the directory the agent operates on.
	WorkingDir string `yaml:"working_dir,omitempty"`
}

// Manager tracks active and historical sessions.
type Manager struct {
	dir string

	mu       sync.RWMutex
	sessions map[string]*Session
}

// New constructs a Manager rooted at the given directory. The directory is
// created if absent.
func New(dir string) (*Manager, error) {
	if dir == "" {
		return nil, errs.Wrap(errs.ErrInvalid, "session manager dir is required")
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, errs.Wrap(err, "create session dir %q", dir)
	}

	m := &Manager{
		dir:      dir,
		sessions: make(map[string]*Session),
	}
	if err := m.load(); err != nil {
		return nil, err
	}
	return m, nil
}

// load reads all session files from disk.
func (m *Manager) load() error {
	entries, err := os.ReadDir(m.dir)
	if err != nil {
		return errs.Wrap(err, "read session dir")
	}
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".yaml" {
			continue
		}
		data, err := os.ReadFile(filepath.Join(m.dir, e.Name()))
		if err != nil {
			continue // skip errors silently
		}
		var s Session
		if err := yaml.Unmarshal(data, &s); err != nil {
			continue
		}
		m.sessions[s.ID] = &s
	}
	return nil
}

// Register creates a new session record. Returns an error if a session
// with the same ID already exists.
func (m *Manager) Register(s *Session) error {
	if s == nil {
		return errs.Wrap(errs.ErrInvalid, "session is nil")
	}
	if s.ID == "" {
		return errs.Wrap(errs.ErrInvalid, "session ID is required")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.sessions[s.ID]; exists {
		return errs.Wrap(errs.ErrAlreadyExists, "session %q", s.ID)
	}

	if s.StartedAt.IsZero() {
		s.StartedAt = time.Now().UTC()
	}
	s.UpdatedAt = s.StartedAt
	if s.Status == "" {
		s.Status = StatusStarting
	}

	return m.writeLocked(s)
}

// Update replaces a session record.
func (m *Manager) Update(s *Session) error {
	if s == nil {
		return errs.Wrap(errs.ErrInvalid, "session is nil")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.sessions[s.ID]; !exists {
		return errs.Wrap(errs.ErrNotFound, "session %q", s.ID)
	}
	s.UpdatedAt = time.Now().UTC()
	return m.writeLocked(s)
}

// Get returns a session by ID.
func (m *Manager) Get(id string) (*Session, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	s, ok := m.sessions[id]
	if !ok {
		return nil, errs.Wrap(errs.ErrNotFound, "session %q", id)
	}
	// Return a copy so callers can't mutate the map's value.
	copy := *s
	return &copy, nil
}

// List returns all sessions, optionally filtered.
func (m *Manager) List(opts ListOptions) []*Session {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var out []*Session
	for _, s := range m.sessions {
		if opts.Status != "" && s.Status != opts.Status {
			continue
		}
		if opts.Project != "" && s.Project != opts.Project {
			continue
		}
		copy := *s
		out = append(out, &copy)
	}

	sort.Slice(out, func(i, j int) bool {
		return out[i].StartedAt.After(out[j].StartedAt)
	})

	if opts.Limit > 0 && len(out) > opts.Limit {
		out = out[:opts.Limit]
	}
	return out
}

// Active returns all currently-running sessions.
func (m *Manager) Active() []*Session {
	return m.List(ListOptions{
		Status: StatusRunning,
	})
}

// Remove deletes a session record. Does not stop the underlying driver.
func (m *Manager) Remove(id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.sessions[id]; !exists {
		return errs.Wrap(errs.ErrNotFound, "session %q", id)
	}

	path := m.pathFor(id)
	delete(m.sessions, id)
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return errs.Wrap(err, "remove session file")
	}
	return nil
}

// writeLocked writes s to disk atomically. Must be called with the lock held.
func (m *Manager) writeLocked(s *Session) error {
	m.sessions[s.ID] = s
	data, err := yaml.Marshal(s)
	if err != nil {
		return errs.Wrap(err, "marshal session")
	}
	path := m.pathFor(s.ID)
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return errs.Wrap(err, "write session tmp")
	}
	return os.Rename(tmp, path)
}

func (m *Manager) pathFor(id string) string {
	return filepath.Join(m.dir, id+".yaml")
}

// ListOptions filters session queries.
type ListOptions struct {
	// Status filters to a specific status. Empty = all.
	Status Status

	// Project filters to a specific project. Empty = all.
	Project string

	// Limit caps the number of results. Zero = no limit.
	Limit int
}

// Compile-time check.
var _ = New // ensure symbol used
