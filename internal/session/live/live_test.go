package live

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

// helper: write a PID file + fake a running process by using the
// current test's own PID (always alive during the test).
func writeFakeSession(t *testing.T, dir, id string) {
	t.Helper()
	pidPath := filepath.Join(dir, id+".pid")
	pid := os.Getpid() // we're alive
	if err := os.WriteFile(pidPath, []byte(fmt.Sprintf("%d", pid)), 0o600); err != nil {
		t.Fatal(err)
	}
}

// helper: write a PID file for a dead process (PID 999999 is unlikely
// to exist).
func writeDeadSession(t *testing.T, dir, id string) {
	t.Helper()
	pidPath := filepath.Join(dir, id+".pid")
	if err := os.WriteFile(pidPath, []byte("999999"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestList_EmptyDir(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()

	sessions, err := List(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(sessions) != 0 {
		t.Fatalf("expected 0 sessions, got %d", len(sessions))
	}
}

func TestList_NonexistentDir(t *testing.T) {
	t.Parallel()
	dir := filepath.Join(t.TempDir(), "does-not-exist")

	sessions, err := List(dir)
	if err != nil {
		t.Fatalf("expected nil error for nonexistent dir, got %v", err)
	}
	if sessions != nil {
		t.Fatalf("expected nil sessions for nonexistent dir, got %v", sessions)
	}
}

func TestList_AliveSession(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	writeFakeSession(t, dir, "sess-alive-001")

	sessions, err := List(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(sessions) != 1 {
		t.Fatalf("expected 1 session, got %d", len(sessions))
	}
	if sessions[0].SessionID != "sess-alive-001" {
		t.Fatalf("expected ID sess-alive-001, got %s", sessions[0].SessionID)
	}
}

func TestList_DeadSessionCleanedUp(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	writeDeadSession(t, dir, "sess-dead-001")

	sessions, err := List(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(sessions) != 0 {
		t.Fatalf("expected 0 sessions (dead cleaned up), got %d", len(sessions))
	}

	// PID file should be cleaned up.
	pidPath := filepath.Join(dir, "sess-dead-001.pid")
	if _, err := os.Stat(pidPath); !os.IsNotExist(err) {
		t.Fatalf("expected PID file removed, got err=%v", err)
	}
}

func TestList_IgnoresNonPidFiles(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	writeFakeSession(t, dir, "sess-001")
	// Create non-PID files that should be ignored.
	_ = os.WriteFile(filepath.Join(dir, "sess-001.yaml"), []byte("status: running"), 0o600)
	_ = os.WriteFile(filepath.Join(dir, "readme.txt"), []byte("ignore me"), 0o600)

	sessions, err := List(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(sessions) != 1 {
		t.Fatalf("expected 1 session, got %d", len(sessions))
	}
}

func TestGet_AliveSession(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	writeFakeSession(t, dir, "sess-get-001")

	s, err := Get(dir, "sess-get-001")
	if err != nil {
		t.Fatal(err)
	}
	if s.SessionID != "sess-get-001" {
		t.Fatalf("expected ID sess-get-001, got %s", s.SessionID)
	}
	if !s.IsAlive() {
		t.Fatal("expected session to be alive")
	}
}

func TestGet_NotRunning(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()

	_, err := Get(dir, "nonexistent-001")
	if err == nil {
		t.Fatal("expected error for non-running session")
	}
}

func TestGet_DeadSession(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	writeDeadSession(t, dir, "sess-dead-002")

	_, err := Get(dir, "sess-dead-002")
	if err == nil {
		t.Fatal("expected error for dead session")
	}
}

func TestIsAlive_CurrentProcess(t *testing.T) {
	t.Parallel()
	s := &Session{PID: os.Getpid()}
	if !s.IsAlive() {
		t.Fatal("current process should be alive")
	}
}

func TestIsAlive_DeadPID(t *testing.T) {
	t.Parallel()
	s := &Session{PID: 999999}
	if s.IsAlive() {
		t.Fatal("PID 999999 should not be alive")
	}
}

func TestIsAlive_InvalidPID(t *testing.T) {
	t.Parallel()
	s := &Session{PID: -1}
	if s.IsAlive() {
		t.Fatal("invalid PID should not be alive")
	}
}

func TestCleanupStale_RemovesFiles(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	// Create PID and sock files.
	pidPath := filepath.Join(dir, "sess-001.pid")
	sockPath := filepath.Join(dir, "sess-001.sock")
	_ = os.WriteFile(pidPath, []byte("12345"), 0o600)
	_ = os.WriteFile(sockPath, []byte("fake"), 0o600)

	s := &Session{SessionID: "sess-001", sessionsDir: dir}
	s.cleanupStale()

	if _, err := os.Stat(pidPath); !os.IsNotExist(err) {
		t.Fatal("PID file should be removed")
	}
	if _, err := os.Stat(sockPath); !os.IsNotExist(err) {
		t.Fatal("sock file should be removed")
	}
}

func TestEvents_StreamFromSocket(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	sockPath := filepath.Join(dir, "sess-events-001.sock")

	// Start a fake event server.
	listener, err := net.Listen("unix", sockPath)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()

	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		enc := json.NewEncoder(conn)
		// Send a few events.
		for i := 0; i < 3; i++ {
			msg := struct {
				Type  string        `json:"type"`
				Event *driver.Event `json:"event"`
			}{
				Type: "event",
				Event: &driver.Event{
					Type:    driver.EventMessage,
					Message: fmt.Sprintf("event %d", i),
				},
			}
			_ = enc.Encode(&msg)
		}
		// Close conn to end the stream.
	}()

	// Small delay to ensure server is accepting.
	time.Sleep(10 * time.Millisecond)

	s := &Session{SessionID: "sess-events-001", SocketPath: sockPath}
	ch, err := s.Events()
	if err != nil {
		t.Fatal(err)
	}

	var got []string
	timeout := time.After(2 * time.Second)
	for len(got) < 3 {
		select {
		case ev, ok := <-ch:
			if !ok {
				break
			}
			got = append(got, ev.Message)
		case <-timeout:
			t.Fatalf("timed out, got %d events: %v", len(got), got)
		}
	}

	if len(got) != 3 {
		t.Fatalf("expected 3 events, got %d", len(got))
	}
}

func TestEvents_DialFails(t *testing.T) {
	t.Parallel()
	// Nonexistent socket — dial should fail.
	s := &Session{SocketPath: "/tmp/nonexistent-sock-12345"}
	_, err := s.Events()
	if err == nil {
		t.Fatal("expected dial error for nonexistent socket")
	}
}
