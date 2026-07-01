// Package integration provides end-to-end tests that exercise multiple
// packages together. These tests build the real agentjam binary and
// run it as a subprocess to validate the full session lifecycle.
//
// Tests are gated behind the "integration" build tag so they don't run
// during normal `go test ./...`. Run them with:
//
//	go test -tags integration -count=1 ./internal/integration/...
//
//go:build integration

package integration

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Globals set by TestMain.
var (
	binPath string // path to the built agentjam binary
	ajHome  string // isolated AGENTJAM_HOME for tests
)

func TestMain(m *testing.M) {
	// Build the binary.
	repoRoot, err := filepath.Abs("../..")
	if err != nil {
		fmt.Fprintf(os.Stderr, "FATAL: %v\n", err)
		os.Exit(1)
	}
	binPath = filepath.Join(os.TempDir(), "agentjam-integration-test")
	build := exec.Command("go", "build", "-o", binPath, "./cmd/agentjam")
	build.Dir = repoRoot
	build.Env = append(os.Environ(), "GOFLAGS=-mod=mod")
	if out, err := build.CombinedOutput(); err != nil {
		fmt.Fprintf(os.Stderr, "FATAL: build failed: %s (%v)\n", out, err)
		os.Exit(1)
	}

	// Set up isolated home.
	ajHome, err = os.MkdirTemp("", "agentjam-int-")
	if err != nil {
		fmt.Fprintf(os.Stderr, "FATAL: %v\n", err)
		os.Exit(1)
	}
	os.Setenv("AGENTJAM_HOME", ajHome)
	for _, d := range []string{"sessions", "tasks", "projects", "worktrees"} {
		os.MkdirAll(filepath.Join(ajHome, d), 0o755)
	}

	code := m.Run()

	// Cleanup.
	os.Remove(binPath)
	os.RemoveAll(ajHome)
	os.Exit(code)
}

// ─── Helpers ─────────────────────────────────────────────────────────

// runAgentJam executes the agentjam binary with the given args.
// Returns combined output and error.
func runAgentJam(args ...string) (string, error) {
	return runAgentJamCtx(context.Background(), args...)
}

func runAgentJamCtx(ctx context.Context, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, binPath, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	if err != nil {
		return stdout.String() + stderr.String(), err
	}
	return stdout.String(), nil
}

// startMockSession starts a detached mock session and returns its ID.
func startMockSession(t *testing.T) string {
	t.Helper()
	out, err := runAgentJam("session", "start", "--driver", "mock", "--detach")
	if err != nil {
		t.Fatalf("session start: %v\n%s", err, out)
	}
	id := extractSessionID(out)
	if id == "" {
		t.Fatalf("could not extract session ID from: %s", out)
	}

	// Wait for PID file.
	pidPath := filepath.Join(ajHome, "sessions", id+".pid")
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(pidPath); err == nil {
			return id
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatalf("PID file not created for session %s after 15s\nLog:\n%s",
		id, readSessionLog(id))
	return ""
}

// extractSessionID parses the session ID from the start command output.
func extractSessionID(out string) string {
	lines := strings.Split(out, "\n")
	for _, line := range lines {
		if strings.Contains(line, "Started session") {
			parts := strings.Fields(line)
			if len(parts) >= 3 {
				return parts[2]
			}
		}
	}
	// Fallback: look for "cli-" prefix.
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "cli-") {
			return line
		}
	}
	return ""
}

// readSessionLog reads the log file for a session.
func readSessionLog(id string) string {
	data, err := os.ReadFile(filepath.Join(ajHome, "sessions", id+".log"))
	if err != nil {
		return "(no log file)"
	}
	return string(data)
}

// stopSession stops a session and waits for cleanup.
func stopSession(t *testing.T, id string) {
	t.Helper()
	_, err := runAgentJam("session", "stop", id)
	if err != nil {
		t.Logf("stop session %s: %v", id, err)
	}
	// Wait for PID file removal.
	pidPath := filepath.Join(ajHome, "sessions", id+".pid")
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(pidPath); os.IsNotExist(err) {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Logf("warning: PID file for %s not removed after 10s", id)
}

// waitForFile waits up to timeout for a file to exist. Returns true if found.
func waitForFile(path string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(path); err == nil {
			return true
		}
		time.Sleep(100 * time.Millisecond)
	}
	return false
}

// assertFileGone fails the test if the file still exists.
func assertFileGone(t *testing.T, path, label string) {
	t.Helper()
	if _, err := os.Stat(path); err == nil {
		t.Errorf("%s still exists at %s", label, path)
	}
}
