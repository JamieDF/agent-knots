package session

import (
	"path/filepath"
	"testing"

	"github.com/harness/harness/internal/agent/driver"
	"github.com/harness/harness/internal/errs"
)

func newTestManager(t *testing.T) *Manager {
	t.Helper()
	dir := t.TempDir()
	m, err := New(filepath.Join(dir, "sessions"))
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func sampleSession() *Session {
	return &Session{
		ID:         "sess-001",
		DriverID:   "oc-1234567890",
		Mode:       driver.ModeAgent,
		Project:    "my-app",
		Task:       "T-001",
		Status:     StatusRunning,
		WorkingDir: "/home/user/work/my-app",
	}
}

func TestNew(t *testing.T) {
	dir := t.TempDir()
	m, err := New(filepath.Join(dir, "sessions"))
	if err != nil {
		t.Fatal(err)
	}
	if m == nil {
		t.Fatal("nil manager")
	}
}

func TestNew_EmptyPath(t *testing.T) {
	_, err := New("")
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestRegister(t *testing.T) {
	m := newTestManager(t)
	s := sampleSession()
	if err := m.Register(s); err != nil {
		t.Fatal(err)
	}
	if s.StartedAt.IsZero() {
		t.Error("StartedAt not set")
	}
}

func TestRegister_EmptyID(t *testing.T) {
	m := newTestManager(t)
	s := sampleSession()
	s.ID = ""
	err := m.Register(s)
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestRegister_Duplicate(t *testing.T) {
	m := newTestManager(t)
	s := sampleSession()
	_ = m.Register(s)
	err := m.Register(s)
	if !errs.Is(err, errs.ErrAlreadyExists) {
		t.Errorf("expected ErrAlreadyExists, got %v", err)
	}
}

func TestGet(t *testing.T) {
	m := newTestManager(t)
	s := sampleSession()
	_ = m.Register(s)

	got, err := m.Get(s.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Mode != driver.ModeAgent {
		t.Errorf("Mode = %q", got.Mode)
	}
}

func TestGet_NotFound(t *testing.T) {
	m := newTestManager(t)
	_, err := m.Get("nonexistent")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestUpdate(t *testing.T) {
	m := newTestManager(t)
	s := sampleSession()
	_ = m.Register(s)

	s.Status = StatusPaused
	if err := m.Update(s); err != nil {
		t.Fatal(err)
	}

	got, _ := m.Get(s.ID)
	if got.Status != StatusPaused {
		t.Errorf("Status = %q", got.Status)
	}
}

func TestUpdate_NotFound(t *testing.T) {
	m := newTestManager(t)
	s := sampleSession()
	err := m.Update(s)
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestList(t *testing.T) {
	m := newTestManager(t)

	s1 := sampleSession()
	s1.ID = "s1"
	s1.Status = StatusRunning
	_ = m.Register(s1)

	s2 := sampleSession()
	s2.ID = "s2"
	s2.Status = StatusPaused
	_ = m.Register(s2)

	s3 := sampleSession()
	s3.ID = "s3"
	s3.Status = StatusRunning
	_ = m.Register(s3)

	cases := []struct {
		name string
		opts ListOptions
		want int
	}{
		{"all", ListOptions{}, 3},
		{"running", ListOptions{Status: StatusRunning}, 2},
		{"paused", ListOptions{Status: StatusPaused}, 1},
		{"limit 1", ListOptions{Limit: 1}, 1},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := m.List(c.opts)
			if len(got) != c.want {
				t.Errorf("got %d, want %d", len(got), c.want)
			}
		})
	}
}

func TestActive(t *testing.T) {
	m := newTestManager(t)
	s1 := sampleSession()
	s1.ID = "s1"
	s1.Status = StatusRunning
	_ = m.Register(s1)

	s2 := sampleSession()
	s2.ID = "s2"
	s2.Status = StatusStopped
	_ = m.Register(s2)

	active := m.Active()
	if len(active) != 1 {
		t.Errorf("got %d active, want 1", len(active))
	}
	if active[0].ID != "s1" {
		t.Errorf("active[0].ID = %q", active[0].ID)
	}
}

func TestRemove(t *testing.T) {
	m := newTestManager(t)
	s := sampleSession()
	_ = m.Register(s)
	if err := m.Remove(s.ID); err != nil {
		t.Fatal(err)
	}
	_, err := m.Get(s.ID)
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound after remove, got %v", err)
	}
}

func TestRoundTrip(t *testing.T) {
	dir := t.TempDir()
	m1, _ := New(filepath.Join(dir, "sessions"))

	s := sampleSession()
	_ = m1.Register(s)

	m2, _ := New(filepath.Join(dir, "sessions"))
	got, err := m2.Get(s.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Mode != s.Mode {
		t.Errorf("round-trip Mode = %q", got.Mode)
	}
}

func TestStatusValues(t *testing.T) {
	all := []Status{StatusStarting, StatusRunning, StatusPaused, StatusBlocked, StatusStopped, StatusError}
	seen := make(map[Status]bool)
	for _, s := range all {
		if seen[s] {
			t.Errorf("duplicate status %q", s)
		}
		if s == "" {
			t.Error("empty status")
		}
		seen[s] = true
	}
}
