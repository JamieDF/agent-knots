//go:build integration

package integration

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestSessionLifecycle_StartDetach(t *testing.T) {
	id := startMockSession(t)
	defer stopSession(t, id)

	// PID file should exist.
	pidPath := filepath.Join(ajHome, "sessions", id+".pid")
	if _, err := os.Stat(pidPath); err != nil {
		t.Fatalf("PID file missing: %v\nLog:\n%s", err, readSessionLog(id))
	}

	// Socket file should exist.
	sockPath := filepath.Join(ajHome, "sessions", id+".sock")
	if !waitForFile(sockPath, 5*time.Second) {
		t.Fatalf("socket file missing\nLog:\n%s", readSessionLog(id))
	}

	// PID file should contain a valid PID.
	data, err := os.ReadFile(pidPath)
	if err != nil {
		t.Fatal(err)
	}
	pidStr := strings.TrimSpace(string(data))
	if pidStr == "" {
		t.Error("PID file is empty")
	}
}

func TestSessionLifecycle_ListShowsRunning(t *testing.T) {
	id := startMockSession(t)
	defer stopSession(t, id)

	out, err := runAgentJam("session", "list")
	if err != nil {
		t.Fatalf("session list: %v\n%s", err, out)
	}

	if !strings.Contains(out, id) {
		t.Errorf("session %s not in list output:\n%s", id, out)
	}

	if !strings.Contains(strings.ToLower(out), "running") {
		t.Errorf("session not showing as running:\n%s", out)
	}
}

func TestSessionLifecycle_StopCleansUp(t *testing.T) {
	id := startMockSession(t)

	pidPath := filepath.Join(ajHome, "sessions", id+".pid")
	sockPath := filepath.Join(ajHome, "sessions", id+".sock")

	// Verify files exist before stop.
	if _, err := os.Stat(pidPath); err != nil {
		t.Fatalf("PID file missing before stop: %v", err)
	}

	stopSession(t, id)

	// Verify files are cleaned up.
	assertFileGone(t, pidPath, "PID file")
	assertFileGone(t, sockPath, "socket file")

	// Verify session shows stopped in list.
	out, _ := runAgentJam("session", "list")
	if strings.Contains(strings.ToLower(out), strings.ToLower(id)) &&
		strings.Contains(strings.ToLower(out), "running") {
		t.Errorf("session %s still showing as running after stop", id)
	}
}

func TestSessionLifecycle_StopIdempotent(t *testing.T) {
	id := startMockSession(t)
	defer stopSession(t, id)

	// First stop.
	stopSession(t, id)

	// Second stop should not error (or at least not hang).
	done := make(chan struct{})
	go func() {
		runAgentJam("session", "stop", id)
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("second stop hung for 10s")
	}
}
