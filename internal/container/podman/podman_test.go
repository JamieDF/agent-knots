package podman

import (
	"context"
	"os/exec"
	"strings"
	"testing"
)

func TestParsePercent(t *testing.T) {
	cases := []struct {
		in   string
		want float64
	}{
		{"0%", 0},
		{"12.34%", 12.34},
		{"100%", 100},
		{" 5.5% ", 5.5},
	}
	for _, c := range cases {
		got, err := parsePercent(c.in)
		if err != nil {
			t.Errorf("parsePercent(%q) error: %v", c.in, err)
		}
		if got != c.want {
			t.Errorf("parsePercent(%q) = %v, want %v", c.in, got, c.want)
		}
	}
}

func TestParseBytes(t *testing.T) {
	cases := []struct {
		in   string
		want int64
	}{
		{"0", 0},
		{"1024", 1024},
		{"1KB", 1024},
		{"1.5GB", 1610612736},
		{"2MB", 2 * 1024 * 1024},
		{"512B", 512},
	}
	for _, c := range cases {
		got, err := parseBytes(c.in)
		if err != nil {
			t.Errorf("parseBytes(%q) error: %v", c.in, err)
			continue
		}
		if got != c.want {
			t.Errorf("parseBytes(%q) = %d, want %d", c.in, got, c.want)
		}
	}
}

func TestRuntime_Name(t *testing.T) {
	r := New("")
	if r.Name() != "podman" {
		t.Errorf("Name() = %q, want podman", r.Name())
	}
}

func TestRuntime_CustomBinary(t *testing.T) {
	r := New("/custom/path/podman")
	if r.Binary != "/custom/path/podman" {
		t.Errorf("Binary = %q", r.Binary)
	}
}

func TestRuntime_Available(t *testing.T) {
	r := New("")
	ctx := context.Background()

	available, err := r.Available(ctx)
	if err != nil {
		t.Fatal(err)
	}

	// Verify: podman should be installed in this test environment, OR
	// not — either is fine, we just verify no error.
	if _, err := exec.LookPath(r.Binary); err == nil {
		if !available {
			t.Error("podman is installed but Available() returned false")
		}
	} else {
		if available {
			t.Error("podman is not installed but Available() returned true")
		}
	}
}

func TestRuntime_VersionRequiresBinary(t *testing.T) {
	r := New("")
	ctx := context.Background()
	if _, err := exec.LookPath(r.Binary); err != nil {
		_, err := r.Version(ctx)
		if err == nil {
			t.Error("expected error when podman is not installed")
		}
		if !strings.Contains(err.Error(), "podman") {
			t.Errorf("error %q does not mention podman", err)
		}
	}
}
