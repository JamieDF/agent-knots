package mode

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/JamieDF/agentjam/internal/errs"
)

func newTestLoader(t *testing.T) *Loader {
	t.Helper()
	dir := t.TempDir()
	l, err := NewLoader(dir)
	if err != nil {
		t.Fatal(err)
	}
	return l
}

func TestNewLoader(t *testing.T) {
	dir := t.TempDir()
	l, err := NewLoader(filepath.Join(dir, "subdir"))
	if err != nil {
		t.Fatal(err)
	}
	if l.Root() == "" {
		t.Error("Root() empty")
	}
}

func TestNewLoader_EmptyPath(t *testing.T) {
	_, err := NewLoader("")
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestLoad(t *testing.T) {
	l := newTestLoader(t)
	if err := l.Write(Mode{
		Name: "test",
		Body: "# Test Mode\n\nThis is a test mode.\n\nIt does things.\n",
	}); err != nil {
		t.Fatal(err)
	}
	m, err := l.Load("test")
	if err != nil {
		t.Fatal(err)
	}
	if m.Name != "test" {
		t.Errorf("Name = %q", m.Name)
	}
	if m.DisplayName != "Test Mode" {
		t.Errorf("DisplayName = %q", m.DisplayName)
	}
	if m.Description != "This is a test mode." {
		t.Errorf("Description = %q", m.Description)
	}
	if m.Body == "" {
		t.Error("Body empty")
	}
}

func TestLoad_NotFound(t *testing.T) {
	l := newTestLoader(t)
	_, err := l.Load("nonexistent")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestLoad_EmptyName(t *testing.T) {
	l := newTestLoader(t)
	_, err := l.Load("")
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestList(t *testing.T) {
	l := newTestLoader(t)
	for _, name := range []string{"zebra", "alpha", "middle"} {
		if err := l.Write(Mode{Name: name, Body: "# " + name}); err != nil {
			t.Fatal(err)
		}
	}
	// Dotfiles should be ignored.
	if err := l.Write(Mode{Name: ".hidden", Body: "hidden"}); err != nil {
		t.Fatal(err)
	}

	got, err := l.List()
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 {
		t.Fatalf("got %d modes, want 3", len(got))
	}
	if got[0].Name != "alpha" {
		t.Errorf("first = %q, want alpha (sorted)", got[0].Name)
	}
	if got[2].Name != "zebra" {
		t.Errorf("last = %q, want zebra (sorted)", got[2].Name)
	}
}

func TestReload(t *testing.T) {
	l := newTestLoader(t)
	if err := l.Write(Mode{Name: "x", Body: "v1"}); err != nil {
		t.Fatal(err)
	}
	_, _ = l.Load("x")

	// Simulate external edit (e.g., user edits the file by hand). Write
	// to disk directly, bypassing Write's cache update.
	if err := os.WriteFile(filepath.Join(l.Root(), "x.md"), []byte("v2"), 0o600); err != nil {
		t.Fatal(err)
	}

	// Without reload, cache returns v1.
	m, _ := l.Load("x")
	if m.Body != "v1" {
		t.Errorf("cached body = %q, want v1", m.Body)
	}

	l.Reload()
	m, _ = l.Load("x")
	if m.Body != "v2" {
		t.Errorf("after reload body = %q, want v2", m.Body)
	}
}

// (removed: helper no longer needed; tests use os.WriteFile directly.)

func TestSystemPrompt_WithExtras(t *testing.T) {
	l := newTestLoader(t)
	if err := l.Write(Mode{Name: "agent", Body: "You are an agent."}); err != nil {
		t.Fatal(err)
	}

	prompt, err := l.SystemPrompt("agent", "Use pnpm.", "Always run tests.")
	if err != nil {
		t.Fatal(err)
	}
	want := "You are an agent.\n\nUse pnpm.\n\nAlways run tests."
	if prompt != want {
		t.Errorf("prompt = %q, want %q", prompt, want)
	}
}

func TestSystemPrompt_EmptyExtras(t *testing.T) {
	l := newTestLoader(t)
	if err := l.Write(Mode{Name: "agent", Body: "You are an agent."}); err != nil {
		t.Fatal(err)
	}

	prompt, _ := l.SystemPrompt("agent", "", "  ")
	if prompt != "You are an agent." {
		t.Errorf("prompt = %q", prompt)
	}
}

func TestExists(t *testing.T) {
	l := newTestLoader(t)
	if l.Exists("agent") {
		t.Error("Exists returned true for nonexistent mode")
	}
	_ = l.Write(Mode{Name: "agent", Body: "x"})
	if !l.Exists("agent") {
		t.Error("Exists returned false after Write")
	}
}

func TestString(t *testing.T) {
	m := Mode{Name: "agent"}
	if m.String() != `Mode{Name="agent"}` {
		t.Errorf("String() = %q", m.String())
	}
	m.DisplayName = "Senior Engineer"
	if m.String() != `Mode{Name="agent", Display="Senior Engineer"}` {
		t.Errorf("String() = %q", m.String())
	}
}