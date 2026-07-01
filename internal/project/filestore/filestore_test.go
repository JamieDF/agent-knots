package filestore

import (
	"path/filepath"
	"testing"

	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/project"
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

func sampleProject() *project.Project {
	return &project.Project{
		ID:           "my-app",
		Name:         "My Cool App",
		Description:  "A test project",
		WorkspaceRoot: "/tmp/my-app",
		Repos: []project.Repo{
			{Path: "web", Remote: "[email protected]:org/web.git", Branch: "main", Role: "frontend"},
			{Path: "api", Remote: "[email protected]:org/api.git", Branch: "main", Role: "backend"},
		},
		Commands: project.Commands{
			Test:    "pnpm test",
			Lint:    "pnpm lint",
			Build:   "pnpm build",
			Install: "pnpm install",
		},
		IgnoredPaths: []string{"node_modules", "dist"},
		Conventions:  "TypeScript, Next.js, pnpm",
		VaultScope: project.VaultScope{
			AllowedCredentials: []string{"vault://github/work"},
		},
	}
}

func TestNew(t *testing.T) {
	dir := t.TempDir()
	if _, err := New(filepath.Join(dir, "subdir")); err != nil {
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
	p := sampleProject()
	if err := s.Create(p); err != nil {
		t.Fatal(err)
	}
	if p.CreatedAt.IsZero() {
		t.Error("CreatedAt not set")
	}
	if p.Models.Default == "" {
		t.Error("Models.Default not set")
	}
}

func TestCreate_Validation(t *testing.T) {
	s := newTestStore(t)
	cases := []struct {
		name string
		mut  func(*project.Project)
	}{
		{"empty id", func(p *project.Project) { p.ID = "" }},
		{"empty name", func(p *project.Project) { p.Name = "" }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := sampleProject()
			c.mut(p)
			err := s.Create(p)
			if !errs.Is(err, errs.ErrInvalid) {
				t.Errorf("expected ErrInvalid, got %v", err)
			}
		})
	}
}

func TestCreate_Duplicate(t *testing.T) {
	s := newTestStore(t)
	p := sampleProject()
	if err := s.Create(p); err != nil {
		t.Fatal(err)
	}
	err := s.Create(p)
	if !errs.Is(err, errs.ErrAlreadyExists) {
		t.Errorf("expected ErrAlreadyExists, got %v", err)
	}
}

func TestGet(t *testing.T) {
	s := newTestStore(t)
	p := sampleProject()
	if err := s.Create(p); err != nil {
		t.Fatal(err)
	}
	got, err := s.Get(p.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Name != p.Name {
		t.Errorf("Name = %q", got.Name)
	}
	if len(got.Repos) != 2 {
		t.Errorf("Repos len = %d", len(got.Repos))
	}
	if got.Commands.Test != "pnpm test" {
		t.Errorf("Commands.Test = %q", got.Commands.Test)
	}
}

func TestGet_NotFound(t *testing.T) {
	s := newTestStore(t)
	_, err := s.Get("nonexistent")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestList(t *testing.T) {
	s := newTestStore(t)
	p1 := sampleProject()
	p1.ID = "p1"
	if err := s.Create(p1); err != nil {
		t.Fatal(err)
	}
	p2 := sampleProject()
	p2.ID = "p2"
	if err := s.Create(p2); err != nil {
		t.Fatal(err)
	}
	got, err := s.List(project.ListOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Errorf("got %d projects, want 2", len(got))
	}
}

func TestUpdate(t *testing.T) {
	s := newTestStore(t)
	p := sampleProject()
	if err := s.Create(p); err != nil {
		t.Fatal(err)
	}
	p.Description = "Updated"
	p.Commands.Test = "jest"
	if err := s.Update(p); err != nil {
		t.Fatal(err)
	}
	got, _ := s.Get(p.ID)
	if got.Description != "Updated" {
		t.Errorf("Description = %q", got.Description)
	}
	if got.Commands.Test != "jest" {
		t.Errorf("Commands.Test = %q", got.Commands.Test)
	}
}

func TestDelete(t *testing.T) {
	s := newTestStore(t)
	p := sampleProject()
	if err := s.Create(p); err != nil {
		t.Fatal(err)
	}
	if err := s.Delete(p.ID); err != nil {
		t.Fatal(err)
	}
	_, err := s.Get(p.ID)
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound after delete, got %v", err)
	}
}

func TestActive(t *testing.T) {
	s := newTestStore(t)
	p := sampleProject()
	if err := s.Create(p); err != nil {
		t.Fatal(err)
	}

	// No active initially.
	active, _ := s.Active()
	if active != "" {
		t.Errorf("initial Active = %q", active)
	}

	// Set active.
	if err := s.SetActive(p.ID); err != nil {
		t.Fatal(err)
	}
	active, _ = s.Active()
	if active != p.ID {
		t.Errorf("Active = %q", active)
	}

	// Clear by deleting.
	if err := s.Delete(p.ID); err != nil {
		t.Fatal(err)
	}
	active, _ = s.Active()
	if active != "" {
		t.Errorf("Active after delete = %q", active)
	}
}

func TestSetActive_NotFound(t *testing.T) {
	s := newTestStore(t)
	err := s.SetActive("nonexistent")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestTouch(t *testing.T) {
	s := newTestStore(t)
	p := sampleProject()
	if err := s.Create(p); err != nil {
		t.Fatal(err)
	}
	if err := s.Touch(p.ID); err != nil {
		t.Fatal(err)
	}
	got, _ := s.Get(p.ID)
	if got.LastOpenedAt.IsZero() {
		t.Error("LastOpenedAt not set after Touch")
	}
}

func TestRoundTrip(t *testing.T) {
	dir := t.TempDir()
	s1, _ := New(dir)

	p := sampleProject()
	if err := s1.Create(p); err != nil {
		t.Fatal(err)
	}
	if err := s1.SetActive(p.ID); err != nil {
		t.Fatal(err)
	}

	s2, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	got, err := s2.Get(p.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Name != p.Name {
		t.Errorf("round-trip Name = %q", got.Name)
	}
	active, _ := s2.Active()
	if active != p.ID {
		t.Errorf("round-trip Active = %q", active)
	}
}