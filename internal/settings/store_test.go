package settings

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDefaults(t *testing.T) {
	s := Defaults()

	if s.Agent.DefaultDriver != "pi" {
		t.Errorf("expected DefaultDriver=pi, got %q", s.Agent.DefaultDriver)
	}
	if s.Agent.DefaultMode != "agent" {
		t.Errorf("expected DefaultMode=agent, got %q", s.Agent.DefaultMode)
	}
	if s.UI.Theme != "dark" {
		t.Errorf("expected Theme=dark, got %q", s.UI.Theme)
	}
	if s.Container.ResourceLimits.CPUCores != 2 {
		t.Errorf("expected cpu_cores=2, got %d", s.Container.ResourceLimits.CPUCores)
	}
}

func TestLoad_NonExistent(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "settings.yaml")

	s, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if s.Get().Agent.DefaultDriver != "pi" {
		t.Errorf("expected default driver=pi, got %q", s.Get().Agent.DefaultDriver)
	}
	if s.Path() != path {
		t.Errorf("expected path %q, got %q", path, s.Path())
	}
}

func TestLoad_RoundTrip(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "settings.yaml")

	// Save settings with overrides.
	s, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if err := s.Set("agent.default_driver", "mock"); err != nil {
		t.Fatalf("Set: %v", err)
	}
	if err := s.Set("agent.provider", "anthropic"); err != nil {
		t.Fatalf("Set: %v", err)
	}
	if err := s.Set("container.resource_limits.cpu_cores", "8"); err != nil {
		t.Fatalf("Set: %v", err)
	}

	// Reload and verify.
	s2, err := Load(path)
	if err != nil {
		t.Fatalf("Load again: %v", err)
	}
	got := s2.Get()

	if got.Agent.DefaultDriver != "mock" {
		t.Errorf("expected driver=mock, got %q", got.Agent.DefaultDriver)
	}
	if got.Agent.Provider != "anthropic" {
		t.Errorf("expected provider=anthropic, got %q", got.Agent.Provider)
	}
	if got.Container.ResourceLimits.CPUCores != 8 {
		t.Errorf("expected cpu_cores=8, got %d", got.Container.ResourceLimits.CPUCores)
	}
	// Unset values should still have defaults.
	if got.UI.Theme != "dark" {
		t.Errorf("expected theme=dark, got %q", got.UI.Theme)
	}
}

func TestSet_BadPath(t *testing.T) {
	s := New(Defaults())

	err := s.Set("nonexistent.field", "value")
	if err == nil {
		t.Fatal("expected error for bad path")
	}
}

func TestSet_Bool(t *testing.T) {
	s := New(Defaults())

	if err := s.Set("agent.pause_on_idle", "true"); err != nil {
		t.Fatalf("Set: %v", err)
	}
	if !s.Get().Agent.PauseOnIdle {
		t.Fatal("expected pause_on_idle=true")
	}
}

func TestSet_BadType(t *testing.T) {
	s := New(Defaults())

	err := s.Set("agent.default_driver", "123") // string field, still ok
	if err != nil {
		t.Fatalf("Set string: %v", err)
	}

	err = s.Set("container.resource_limits.cpu_cores", "not-a-number")
	if err == nil {
		t.Fatal("expected error for bad int")
	}
}

func TestLoad_MalformedYAML(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "settings.yaml")

	if err := os.WriteFile(path, []byte("[invalid"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	_, err := Load(path)
	if err == nil {
		t.Fatal("expected parse error")
	}
}

func TestNew_InMemory(t *testing.T) {
	s := New(Settings{
		Agent: AgentSettings{Provider: "openai"},
	})
	if s.Path() != "" {
		t.Errorf("expected empty path for in-memory store, got %q", s.Path())
	}
	if s.Get().Agent.Provider != "openai" {
		t.Errorf("expected provider=openai, got %q", s.Get().Agent.Provider)
	}
	// Should still have defaults for unset fields.
	if s.Get().Agent.DefaultDriver != "pi" {
		t.Errorf("expected default driver=pi, got %q", s.Get().Agent.DefaultDriver)
	}
}

func TestMergeDefaults(t *testing.T) {
	got := mergeDefaults(Settings{
		Agent: AgentSettings{
			Provider: "anthropic",
			Model:    "claude-sonnet-4-20250514",
		},
		UI: UISettings{
			Theme: "light",
		},
	})

	if got.Agent.DefaultDriver != "pi" {
		t.Errorf("expected default driver=pi, got %q", got.Agent.DefaultDriver)
	}
	if got.Agent.Provider != "anthropic" {
		t.Errorf("expected provider=anthropic, got %q", got.Agent.Provider)
	}
	if got.Agent.Model != "claude-sonnet-4-20250514" {
		t.Errorf("expected model=claude, got %q", got.Agent.Model)
	}
	if got.UI.Theme != "light" {
		t.Errorf("expected theme=light, got %q", got.UI.Theme)
	}
	if got.Container.ResourceLimits.MemoryMB != 4096 {
		t.Errorf("expected default memory_mb=4096, got %d", got.Container.ResourceLimits.MemoryMB)
	}
}
