package driver

import (
	"errors"
	"testing"
)

func TestRegistry_RegisterAndBuild(t *testing.T) {
	r := &Registry{factories: make(map[string]Factory)}

	var built bool
	r.Register("test", func(opts FactoryOptions) (Driver, error) {
		built = true
		return nil, nil
	})

	d, err := r.Build("test", FactoryOptions{})
	if err != nil {
		t.Fatalf("Build: %v", err)
	}
	if d != nil {
		t.Error("expected nil driver")
	}
	if !built {
		t.Error("factory was not called")
	}
}

func TestRegistry_UnknownKind(t *testing.T) {
	r := &Registry{factories: make(map[string]Factory)}

	_, err := r.Build("nonexistent", FactoryOptions{})
	if err == nil {
		t.Fatal("expected error for unknown kind")
	}
}

func TestRegistry_Names(t *testing.T) {
	r := &Registry{factories: make(map[string]Factory)}

	dummy := func(opts FactoryOptions) (Driver, error) { return nil, nil }
	r.Register("pi", dummy)
	r.Register("mock", dummy)
	r.Register("opencode", dummy)

	names := r.Names()
	if len(names) != 3 {
		t.Fatalf("expected 3 names, got %d: %v", len(names), names)
	}
	// Names should be sorted.
	if names[0] != "mock" || names[1] != "opencode" || names[2] != "pi" {
		t.Errorf("expected sorted [mock opencode pi], got %v", names)
	}
}

func TestRegistry_FactoryError(t *testing.T) {
	r := &Registry{factories: make(map[string]Factory)}

	r.Register("bad", func(opts FactoryOptions) (Driver, error) {
		return nil, errors.New("factory failed")
	})

	_, err := r.Build("bad", FactoryOptions{})
	if err == nil {
		t.Fatal("expected error from factory")
	}
	if err.Error() != "factory failed" {
		t.Errorf("expected 'factory failed', got %q", err.Error())
	}
}

func TestDefaultRegistry(t *testing.T) {
	// Default registry starts empty — registering and building should work.
	dummy := func(opts FactoryOptions) (Driver, error) {
		return nil, nil
	}
	Default.Register("_test_default", dummy)

	_, err := Default.Build("_test_default", FactoryOptions{})
	if err != nil {
		t.Fatalf("Default.Build: %v", err)
	}
}

func TestFactoryOptions_Defaults(t *testing.T) {
	opts := FactoryOptions{
		Workdir: "/tmp/test",
		ID:      "session-1",
		TaskID:  "T-001",
	}

	if opts.Provider != "" {
		t.Error("expected empty Provider")
	}
	if opts.Container != nil {
		t.Error("expected nil Container")
	}
	if opts.Workdir != "/tmp/test" {
		t.Errorf("expected /tmp/test, got %q", opts.Workdir)
	}
}

// verifyRegistryIsEmpty checks the default registry after our test.
func TestDefaultRegistry_UnknownAfterCleanup(t *testing.T) {
	_, err := Default.Build("_nonexistent_", FactoryOptions{})
	if err == nil {
		t.Fatal("expected unknown driver error")
	}
}

// Compile-time check: FactoryOptions satisfies interface expectations.
var _ = FactoryOptions{
	Workdir:  "/tmp",
	ModeFile: "/tmp/mode.md",
	ID:       "id-1",
	TaskID:   "T-001",
	Provider: "anthropic",
	Model:    "sonnet-4",
	Container: &ContainerOptions{
		Image:       "agentjam-agent-node:20",
		WorktreeDir: "/tmp/wt",
	},
}
