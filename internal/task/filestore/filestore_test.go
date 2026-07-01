package filestore

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/task"
)

func newTestStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	s, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func sampleTask() *task.Task {
	return &task.Task{
		ID:       "T-2026-01-01-001",
		Project:  "test-project",
		Title:    "Add dark mode",
		Status:   task.StatusOpen,
		Priority: task.PriorityMedium,
		Tags:     []string{"ui", "frontend"},
		AcceptanceCriteria: []string{
			"Toggle visible in settings",
			"Choice persists across sessions",
		},
		OutOfScope: []string{"System preference detection"},
	}
}

func TestNew(t *testing.T) {
	dir := t.TempDir()
	_, err := New(filepath.Join(dir, "subdir"))
	if err != nil {
		t.Fatal(err)
	}
}

func TestNew_EmptyPath(t *testing.T) {
	_, err := New("")
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestCreate(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}
	if tt.CreatedAt.IsZero() {
		t.Error("CreatedAt not set")
	}
}

func TestCreate_Validation(t *testing.T) {
	s := newTestStore(t)

	cases := []struct {
		name string
		mut  func(*task.Task)
	}{
		{"empty id", func(t *task.Task) { t.ID = "" }},
		{"empty title", func(t *task.Task) { t.Title = "" }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			tt := sampleTask()
			c.mut(tt)
			err := s.Create(tt)
			if !errs.Is(err, errs.ErrInvalid) {
				t.Errorf("expected ErrInvalid, got %v", err)
			}
		})
	}
}

func TestCreate_Duplicate(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}
	tt2 := sampleTask()
	err := s.Create(tt2)
	if !errs.Is(err, errs.ErrAlreadyExists) {
		t.Errorf("expected ErrAlreadyExists, got %v", err)
	}
}

func TestGet(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}
	got, err := s.Get(tt.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Title != tt.Title {
		t.Errorf("Title = %q", got.Title)
	}
	if len(got.AcceptanceCriteria) != 2 {
		t.Errorf("AcceptanceCriteria len = %d", len(got.AcceptanceCriteria))
	}
}

func TestGet_NotFound(t *testing.T) {
	s := newTestStore(t)
	_, err := s.Get("T-nonexistent")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestList(t *testing.T) {
	s := newTestStore(t)

	// Create 3 tasks in different states.
	t1 := sampleTask()
	t1.ID = "T-001"
	t1.Status = task.StatusOpen
	if err := s.Create(t1); err != nil {
		t.Fatal(err)
	}

	t2 := sampleTask()
	t2.ID = "T-002"
	t2.Status = task.StatusInProgress
	if err := s.Create(t2); err != nil {
		t.Fatal(err)
	}

	t3 := sampleTask()
	t3.ID = "T-003"
	t3.Status = task.StatusDone
	t3.Project = "other"
	if err := s.Create(t3); err != nil {
		t.Fatal(err)
	}

	cases := []struct {
		name string
		opts task.ListOptions
		want int
	}{
		{"all", task.ListOptions{}, 3},
		{"project test-project", task.ListOptions{Project: "test-project"}, 2},
		{"project other", task.ListOptions{Project: "other"}, 1},
		{"status open", task.ListOptions{Status: task.StatusOpen}, 1},
		{"status done", task.ListOptions{Status: task.StatusDone}, 1},
		{"limit 2", task.ListOptions{Limit: 2}, 2},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := s.List(c.opts)
			if err != nil {
				t.Fatal(err)
			}
			if len(got) != c.want {
				t.Errorf("got %d, want %d", len(got), c.want)
			}
		})
	}
}

func TestUpdate(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}

	tt.Title = "Updated title"
	tt.Priority = task.PriorityHigh
	if err := s.Update(tt); err != nil {
		t.Fatal(err)
	}

	got, _ := s.Get(tt.ID)
	if got.Title != "Updated title" {
		t.Errorf("Title = %q", got.Title)
	}
	if got.Priority != task.PriorityHigh {
		t.Errorf("Priority = %q", got.Priority)
	}
	if !got.UpdatedAt.After(got.CreatedAt) && !got.UpdatedAt.Equal(got.CreatedAt) {
		t.Errorf("UpdatedAt should be >= CreatedAt: updated=%v created=%v", got.UpdatedAt, got.CreatedAt)
	}
}

func TestDelete(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}
	if err := s.Delete(tt.ID); err != nil {
		t.Fatal(err)
	}
	_, err := s.Get(tt.ID)
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound after delete, got %v", err)
	}
}

func TestLogProgress(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}

	entry := task.ProgressEntry{
		Entry:  "Created toggle component",
		Status: task.StatusInProgress,
		ActionsTaken: []string{
			"read_file: src/pages/Settings.tsx",
			"write_file: src/components/DarkModeToggle.tsx",
		},
		NextStep: "Wire to store",
		Caller:   "agent:auth-fix",
	}
	if err := s.LogProgress(tt.ID, entry); err != nil {
		t.Fatal(err)
	}

	got, _ := s.Get(tt.ID)
	if len(got.Progress) != 1 {
		t.Fatalf("Progress len = %d", len(got.Progress))
	}
	if got.Progress[0].Entry != entry.Entry {
		t.Errorf("Entry = %q", got.Progress[0].Entry)
	}
	if got.Status != task.StatusInProgress {
		t.Errorf("Status = %q (should auto-update from progress entry)", got.Status)
	}
	if got.Progress[0].Timestamp.IsZero() {
		t.Error("Timestamp not set")
	}
}

func TestLogProgress_EmptyEntry(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}
	err := s.LogProgress(tt.ID, task.ProgressEntry{})
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestLogProgress_Blocker(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}

	entry := task.ProgressEntry{
		Entry:  "Need user decision",
		Status: task.StatusBlocked,
		Blocker: &task.Blocker{
			Description: "Color contrast fails WCAG AA",
			Question:    "Which palette?",
			Options:     []string{"Option A", "Option B"},
			Awaiting:    "user",
		},
	}
	if err := s.LogProgress(tt.ID, entry); err != nil {
		t.Fatal(err)
	}

	got, _ := s.Get(tt.ID)
	if got.Status != task.StatusBlocked {
		t.Errorf("Status = %q", got.Status)
	}
	if got.Progress[0].Blocker == nil {
		t.Fatal("Blocker not persisted")
	}
	if got.Progress[0].Blocker.Question != "Which palette?" {
		t.Errorf("Blocker.Question = %q", got.Progress[0].Blocker.Question)
	}
}

func TestAssign(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}

	if err := s.Assign(tt.ID, "agent:auth-fix"); err != nil {
		t.Fatal(err)
	}
	got, _ := s.Get(tt.ID)
	if got.AssignedTo != "agent:auth-fix" {
		t.Errorf("AssignedTo = %q", got.AssignedTo)
	}

	if err := s.Assign(tt.ID, ""); err != nil {
		t.Fatal(err)
	}
	got, _ = s.Get(tt.ID)
	if got.AssignedTo != "" {
		t.Errorf("AssignedTo should be empty, got %q", got.AssignedTo)
	}
}

func TestSetStatus(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}

	if err := s.SetStatus(tt.ID, task.StatusInProgress); err != nil {
		t.Fatal(err)
	}
	got, _ := s.Get(tt.ID)
	if got.Status != task.StatusInProgress {
		t.Errorf("Status = %q", got.Status)
	}
}

func TestSetStatus_InvalidStatus(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}
	err := s.SetStatus(tt.ID, "garbage")
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestSetStatus_FromTerminal(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}
	if err := s.SetStatus(tt.ID, task.StatusDone); err != nil {
		t.Fatal(err)
	}
	err := s.SetStatus(tt.ID, task.StatusInProgress)
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid for terminal->active, got %v", err)
	}
}

func TestCheckAcceptance(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}

	// Wrong length.
	err := s.CheckAcceptance(tt.ID, []bool{true})
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid for wrong length, got %v", err)
	}

	// All satisfied.
	if err := s.CheckAcceptance(tt.ID, []bool{true, true}); err != nil {
		t.Errorf("expected nil, got %v", err)
	}

	// One not satisfied.
	err = s.CheckAcceptance(tt.ID, []bool{true, false})
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid for unsatisfied, got %v", err)
	}
}

func TestSteps(t *testing.T) {
	s := newTestStore(t)
	tt := sampleTask()
	if err := s.Create(tt); err != nil {
		t.Fatal(err)
	}

	step := task.Step{ID: ".1", Title: "Create component", Status: task.StatusOpen}
	if err := s.AddStep(tt.ID, step); err != nil {
		t.Fatal(err)
	}
	got, _ := s.Get(tt.ID)
	if len(got.Steps) != 1 {
		t.Fatalf("Steps len = %d", len(got.Steps))
	}
	if got.Steps[0].ID != ".1" {
		t.Errorf("Step ID = %q", got.Steps[0].ID)
	}

	// Auto-assign ID.
	if err := s.AddStep(tt.ID, task.Step{Title: "Wire to store"}); err != nil {
		t.Fatal(err)
	}
	got, _ = s.Get(tt.ID)
	if got.Steps[1].ID != ".2" {
		t.Errorf("auto-assigned ID = %q", got.Steps[1].ID)
	}

	// Update.
	step.Status = task.StatusDone
	if err := s.UpdateStep(tt.ID, step); err != nil {
		t.Fatal(err)
	}
	got, _ = s.Get(tt.ID)
	if got.Steps[0].Status != task.StatusDone {
		t.Errorf("Step 0 status = %q", got.Steps[0].Status)
	}
}

func TestStatusHelpers(t *testing.T) {
	if !task.StatusDone.IsTerminal() {
		t.Error("Done should be terminal")
	}
	if !task.StatusAbandoned.IsTerminal() {
		t.Error("Abandoned should be terminal")
	}
	if task.StatusOpen.IsTerminal() {
		t.Error("Open should not be terminal")
	}

	if !task.StatusInProgress.IsActive() {
		t.Error("InProgress should be active")
	}
	if !task.StatusPlanned.IsActive() {
		t.Error("Planned should be active")
	}
	if task.StatusOpen.IsActive() {
		t.Error("Open should not be active")
	}

	if !task.StatusOpen.Valid() {
		t.Error("Open should be valid")
	}
	if task.Status("garbage").Valid() {
		t.Error("garbage should not be valid")
	}
}

func TestRoundTrip(t *testing.T) {
	dir := t.TempDir()
	s1, _ := New(dir)

	tt := sampleTask()
	if err := s1.Create(tt); err != nil {
		t.Fatal(err)
	}

	// Reopen and read.
	s2, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	got, err := s2.Get(tt.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Title != tt.Title {
		t.Errorf("round-trip Title = %q", got.Title)
	}
}

func TestListOptions_Tags(t *testing.T) {
	s := newTestStore(t)
	for _, tags := range [][]string{{"a", "b"}, {"b"}, {"a"}} {
		tt := sampleTask()
		tt.ID = task.ID("T-" + strings.Join(tags, "-"))
		tt.Tags = tags
		if err := s.Create(tt); err != nil {
			t.Fatal(err)
		}
	}
	got, err := s.List(task.ListOptions{Tags: []string{"a", "b"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 {
		t.Errorf("expected 1, got %d", len(got))
	}
}

// Suppress unused warnings.
var _ = context.Background
var _ = time.Second