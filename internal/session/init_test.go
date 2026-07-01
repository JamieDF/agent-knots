package session

import (
	"context"
	"path/filepath"
	"strings"
	"testing"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/task"
	"github.com/JamieDF/agentjam/internal/task/filestore"
)

func TestNewSessionID_UniqueAndFormatted(t *testing.T) {
	seen := make(map[string]bool)
	for i := 0; i < 100; i++ {
		id := newSessionID()
		if !strings.HasPrefix(id, "S-") {
			t.Errorf("ID %q does not start with S-", id)
		}
		if seen[id] {
			t.Errorf("duplicate ID generated: %q", id)
		}
		seen[id] = true
	}
}

func TestInit_ValidatesManager(t *testing.T) {
	_, _, err := Init(context.Background(), nil, Options{
		ID: "S1",
	})
	if err == nil {
		t.Fatal("expected error for nil manager")
	}
}

func TestInit_ValidatesID(t *testing.T) {
	dir := t.TempDir()
	mgr, err := New(filepath.Join(dir, "sessions"))
	if err != nil {
		t.Fatal(err)
	}

	_, _, err = Init(context.Background(), mgr, Options{})
	if err == nil {
		t.Fatal("expected error for empty ID without GenerateID")
	}
}

func TestInit_GeneratesIDWhenRequested(t *testing.T) {
	dir := t.TempDir()
	mgr, err := New(filepath.Join(dir, "sessions"))
	if err != nil {
		t.Fatal(err)
	}

	// Even with no task, no project, no real driver behind, we should at
	// least get an error from one of the phases (probably driver start),
	// not from ID validation.
	_, _, err = Init(context.Background(), mgr, Options{
		GenerateID: true,
		Container:  false,
	})
	if err == nil {
		t.Fatal("expected error from later phase (no driver available)")
	}
}

func TestInit_RefusesContainerWithoutProjectOrTask(t *testing.T) {
	dir := t.TempDir()
	mgr, err := New(filepath.Join(dir, "sessions"))
	if err != nil {
		t.Fatal(err)
	}

	_, _, err = Init(context.Background(), mgr, Options{
		ID:        "S-test",
		Container: true,
	})
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "container") {
		t.Errorf("expected 'container' in error, got: %v", err)
	}
}

func TestBuildTaskPrompt_IncludesAcceptance(t *testing.T) {
	tk := &task.Task{
		Title:              "Add dark mode",
		Project:            "ui-app",
		Priority:           task.PriorityHigh,
		Description:        "Toggle in settings page",
		AcceptanceCriteria: []string{"Toggle visible", "Choice persists"},
		OutOfScope:         []string{"Color scheme"},
	}
	prompt := buildTaskPrompt(tk)

	for _, want := range []string{"Add dark mode", "ui-app", "high", "Toggle in settings page",
		"Toggle visible", "Choice persists", "Color scheme", "## Workflow"} {
		if !strings.Contains(prompt, want) {
			t.Errorf("prompt missing %q", want)
		}
	}
}

func TestPhase1Resolve_DefaultsModeToAgent(t *testing.T) {
	r, err := phase1Resolve(context.Background(), Options{
		TaskStore: &stubTaskStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	if r.Mode != driver.ModeAgent {
		t.Errorf("default mode = %v, want agent", r.Mode)
	}
}

func TestPhase1Resolve_ExplicitModeWins(t *testing.T) {
	r, err := phase1Resolve(context.Background(), Options{
		Mode:      driver.ModeReviewer,
		TaskStore: &stubTaskStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	if r.Mode != driver.ModeReviewer {
		t.Errorf("explicit mode lost: got %v", r.Mode)
	}
}

func TestPhase1Resolve_DetectsMissingCredentials(t *testing.T) {
	tk := &task.Task{
		ID:                  "T-test",
		Title:               "Deploy",
		RequiredCredentials: []string{"github/work", "aws/prod"},
	}
	r, err := phase1Resolve(context.Background(), Options{
		TaskID:    string(tk.ID),
		Vault:     &stubVault{unlocked: false},
		TaskStore: &stubTaskStore{byID: map[string]*task.Task{"T-test": tk}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !r.VaultMissedContains("github/work") || !r.VaultMissedContains("aws/prod") {
		t.Errorf("expected missing creds recorded, got %v", r.VaultMissed)
	}
}

func TestPhase1Resolve_NoMissingCredsIfVaultUnlocked(t *testing.T) {
	tk := &task.Task{
		ID:                  "T-test",
		Title:               "Deploy",
		RequiredCredentials: []string{"github/work"},
	}
	r, err := phase1Resolve(context.Background(), Options{
		TaskID:    string(tk.ID),
		Vault:     &stubVault{unlocked: true},
		TaskStore: &stubTaskStore{byID: map[string]*task.Task{"T-test": tk}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.VaultMissed) != 0 {
		t.Errorf("expected no missed creds when unlocked, got %v", r.VaultMissed)
	}
}

// stubTaskStore is a minimal task.Store for tests.
type stubTaskStore struct {
	byID map[string]*task.Task
}

func (s *stubTaskStore) Create(*task.Task) error { return nil }
func (s *stubTaskStore) Get(id task.ID) (*task.Task, error) {
	if s.byID == nil {
		return nil, errNotFoundStub(id)
	}
	if t, ok := s.byID[string(id)]; ok {
		return t, nil
	}
	return nil, errNotFoundStub(id)
}
func (s *stubTaskStore) List(task.ListOptions) ([]*task.Task, error)   { return nil, nil }
func (s *stubTaskStore) Update(*task.Task) error                       { return nil }
func (s *stubTaskStore) Delete(task.ID) error                          { return nil }
func (s *stubTaskStore) LogProgress(task.ID, task.ProgressEntry) error { return nil }
func (s *stubTaskStore) Assign(task.ID, string) error                  { return nil }
func (s *stubTaskStore) SetStatus(task.ID, task.Status) error          { return nil }
func (s *stubTaskStore) CheckAcceptance(task.ID, []bool) error         { return nil }
func (s *stubTaskStore) AddStep(task.ID, task.Step) error              { return nil }
func (s *stubTaskStore) UpdateStep(task.ID, task.Step) error           { return nil }

// stubVault satisfies VaultChecker.
type stubVault struct{ unlocked bool }

func (s *stubVault) IsUnlocked(_ context.Context) (bool, error) { return s.unlocked, nil }

// errNotFoundStub keeps the stub's returns tight.
type errNotFoundStub task.ID

func (e errNotFoundStub) Error() string { return "not found: " + string(e) }

// helper for credential list assertion.
func (r *Resolved) VaultMissedContains(s string) bool {
	for _, v := range r.VaultMissed {
		if v == s {
			return true
		}
	}
	return false
}

// Use the real filestore in one test as a smoke test (phase 1 only —
// the integration with a running OpenCode server requires a live server,
// which we can't assume in unit tests).
func TestInit_Phase1WithFilestoreTasks(t *testing.T) {
	dir := t.TempDir()
	ts, err := filestore.New(filepath.Join(dir, "tasks"))
	if err != nil {
		t.Fatal(err)
	}
	tk := &task.Task{
		ID:                 "T-smoke-001",
		Title:              "Smoke test task",
		Project:            "does-not-exist",
		Description:        "End-to-end smoke test",
		AcceptanceCriteria: []string{"Init returns without panic"},
		Status:             task.StatusOpen,
		CreatedBy:          "test",
	}
	if err := ts.Create(tk); err != nil {
		t.Fatal(err)
	}

	// Without a ProjectStore, phase 1 should NOT fail — it just leaves
	// the project unresolved. The error surfaces later, when the runtime
	// tries to prepare a workspace.
	r, err := phase1Resolve(context.Background(), Options{
		TaskID:    string(tk.ID),
		TaskStore: ts,
	})
	if err != nil {
		t.Fatalf("phase 1 unexpectedly failed: %v", err)
	}
	if r.ProjectID != "does-not-exist" {
		t.Errorf("ProjectID = %q, want %q", r.ProjectID, "does-not-exist")
	}
	if r.Project != nil {
		t.Errorf("Project should be nil without ProjectStore, got %v", r.Project)
	}
}

func TestValidateID_Valid(t *testing.T) {
	t.Parallel()
	valid := []string{
		"S-abc123",
		"session-001",
		"a",
		"2024-01-01_session",
	}
	for _, id := range valid {
		if err := validateID(id); err != nil {
			t.Errorf("validateID(%q) = %v; want nil", id, err)
		}
	}
}

func TestValidateID_RejectsPathTraversal(t *testing.T) {
	t.Parallel()
	invalid := []string{
		"../etc/passwd",
		"a/../b",
		"/etc/passwd",
		`C:\Windows`,
		"foo/bar",
		`foo\bar`,
		"..",
		".",
		"",
	}
	for _, id := range invalid {
		if err := validateID(id); err == nil {
			t.Errorf("validateID(%q) = nil; want error", id)
		}
	}
}
