package container

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"testing"
)

// skipIfNoPodman skips the test if podman is not installed.
func skipIfNoPodman(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("podman"); err != nil {
		t.Skip("podman not installed")
	}
}

// startTestContainer starts a minimal container that sleeps long enough
// for tests to run. Returns the container ID and cleans up automatically.
func startTestContainer(t *testing.T) string {
	t.Helper()
	out, err := exec.Command("podman", "run", "-d", "--rm",
		"alpine:latest", "sleep", "120").CombinedOutput()
	if err != nil {
		t.Skipf("could not start test container: %s (%v)", out, err)
	}
	id := strings.TrimSpace(string(out))
	t.Cleanup(func() {
		_ = exec.Command("podman", "stop", "-t", "1", id).Run()
	})
	return id
}

func containerPID(t *testing.T, id string) int {
	t.Helper()
	out, err := exec.Command("podman", "inspect", "--format", "{{.State.Pid}}", id).Output()
	if err != nil {
		t.Fatalf("get container PID: %v", err)
	}
	var pid int
	if _, err := fmt.Sscanf(strings.TrimSpace(string(out)), "%d", &pid); err != nil {
		t.Fatalf("parse PID: %v", err)
	}
	return pid
}

func TestInstallEgressRules(t *testing.T) {
	skipIfNoPodman(t)

	id := startTestContainer(t)
	pid := containerPID(t, id)
	if pid <= 0 {
		t.Fatal("got invalid PID")
	}

	denyList := []string{
		"10.0.0.0/8",
		"192.168.0.0/16",
	}

	ctx := context.Background()
	if err := InstallEgressRules(ctx, pid, denyList); err != nil {
		t.Fatalf("InstallEgressRules: %v", err)
	}

	// Verify rules are present.
	rules, err := VerifyEgressRules(ctx, pid)
	if err != nil {
		t.Fatalf("VerifyEgressRules: %v", err)
	}

	ruleSet := make(map[string]bool)
	for _, r := range rules {
		ruleSet[r] = true
	}

	for _, cidr := range denyList {
		if !ruleSet[cidr] {
			t.Errorf("expected DROP rule for %s, not found in %v", cidr, rules)
		}
	}
}

func TestInstallEgressRules_EmptyList(t *testing.T) {
	ctx := context.Background()
	if err := InstallEgressRules(ctx, 99999, nil); err != nil {
		t.Fatalf("InstallEgressRules with empty list should succeed: %v", err)
	}
}

func TestInstallEgressRules_InvalidPID(t *testing.T) {
	ctx := context.Background()
	err := InstallEgressRules(ctx, 0, []string{"10.0.0.0/8"})
	if err == nil {
		t.Fatal("expected error for invalid PID")
	}
}

func TestVerifyEgressRules_NoRules(t *testing.T) {
	skipIfNoPodman(t)

	id := startTestContainer(t)
	pid := containerPID(t, id)

	ctx := context.Background()
	rules, err := VerifyEgressRules(ctx, pid)
	if err != nil {
		t.Fatalf("VerifyEgressRules on clean container: %v", err)
	}
	// A fresh container should have no custom DROP rules.
	for _, r := range rules {
		if strings.Contains(r, "DROP") {
			t.Errorf("unexpected DROP rule in fresh container: %s", r)
		}
	}
}
