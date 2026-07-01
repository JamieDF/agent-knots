//go:build integration

package integration

import (
	"encoding/json"
	"fmt"
	"net"
	"path/filepath"
	"testing"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

// dialSocket connects to a session's event socket and returns the connection.
func dialSocket(t *testing.T, id string) net.Conn {
	t.Helper()
	sockPath := filepath.Join(ajHome, "sessions", id+".sock")
	conn, err := net.Dial("unix", sockPath)
	if err != nil {
		t.Fatalf("dial socket for %s: %v", id, err)
	}
	return conn
}

// readEvents reads up to n events from a connection within timeout.
// Returns the events collected.
func readEvents(t *testing.T, conn net.Conn, n int, timeout time.Duration) []driver.Event {
	t.Helper()
	var events []driver.Event
	deadline := time.Now().Add(timeout)
	for len(events) < n && time.Now().Before(deadline) {
		conn.SetReadDeadline(time.Now().Add(timeout))
		dec := json.NewDecoder(conn)
		var msg struct {
			Type  string        `json:"type"`
			Event *driver.Event `json:"event"`
		}
		if err := dec.Decode(&msg); err != nil {
			break
		}
		if msg.Type == "event" && msg.Event != nil {
			events = append(events, *msg.Event)
		}
	}
	return events
}

func TestEventStreaming_EventsArrive(t *testing.T) {
	id := startMockSession(t)
	defer stopSession(t, id)

	// Give the mock driver time to emit some events.
	time.Sleep(3 * time.Second)

	conn := dialSocket(t, id)
	defer conn.Close()

	events := readEvents(t, conn, 3, 10*time.Second)
	if len(events) < 3 {
		t.Fatalf("expected at least 3 events, got %d", len(events))
	}

	// Verify event types are from the expected set.
	validTypes := map[driver.EventType]bool{
		driver.EventThinking:  true,
		driver.EventToolCall:  true,
		driver.EventToolResult: true,
		driver.EventMessage:   true,
		driver.EventProgress:  true,
	}
	for _, ev := range events {
		if !validTypes[ev.Type] {
			t.Errorf("unexpected event type: %s", ev.Type)
		}
		if ev.SessionID == "" {
			t.Error("event has empty SessionID")
		}
	}
}

func TestControlChannel_SetMode(t *testing.T) {
	id := startMockSession(t)
	defer stopSession(t, id)

	// Wait for events to start flowing (proves the session is ready).
	time.Sleep(2 * time.Second)

	// Connect to the socket.
	conn := dialSocket(t, id)
	defer conn.Close()

	// Send a control message: set-mode to "assistant".
	ctrl := map[string]string{
		"type":   "control",
		"action": "set-mode",
		"mode":   "assistant",
	}
	data, _ := json.Marshal(ctrl)
	data = append(data, '\n')
	if _, err := conn.Write(data); err != nil {
		t.Fatalf("write control message: %v", err)
	}

	// Read the response.
	dec := json.NewDecoder(conn)
	var resp struct {
		Type  string `json:"type"`
		OK    bool   `json:"ok"`
		Error string `json:"error,omitempty"`
	}
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	if err := dec.Decode(&resp); err != nil {
		t.Fatalf("read control response: %v", err)
	}

	if !resp.OK {
		t.Errorf("set-mode response not OK: %s", resp.Error)
	}
}

func TestControlChannel_Send(t *testing.T) {
	id := startMockSession(t)
	defer stopSession(t, id)

	time.Sleep(2 * time.Second)

	conn := dialSocket(t, id)
	defer conn.Close()

	// Send a control message: send.
	ctrl := map[string]string{
		"type":    "control",
		"action":  "send",
		"content": "hello from integration test",
		"role":    "user",
	}
	data, _ := json.Marshal(ctrl)
	data = append(data, '\n')
	if _, err := conn.Write(data); err != nil {
		t.Fatalf("write control message: %v", err)
	}

	// Read response.
	dec := json.NewDecoder(conn)
	var resp struct {
		Type  string `json:"type"`
		OK    bool   `json:"ok"`
		Error string `json:"error,omitempty"`
	}
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	if err := dec.Decode(&resp); err != nil {
		t.Fatalf("read control response: %v", err)
	}

	if !resp.OK {
		t.Errorf("send response not OK: %s", resp.Error)
	}
}

func TestControlChannel_AssumeRelinquishViaCLI(t *testing.T) {
	id := startMockSession(t)
	defer stopSession(t, id)

	time.Sleep(2 * time.Second)

	// Test assume via CLI.
	out, err := runAgentJam("session", "assume", id)
	if err != nil {
		t.Fatalf("assume: %v\n%s", err, out)
	}
	if !contains(out, "assistant") {
		t.Errorf("assume output should mention assistant mode:\n%s", out)
	}

	// Test send via CLI.
	out, err = runAgentJam("session", "send", id, "check the tests")
	if err != nil {
		t.Fatalf("send: %v\n%s", err, out)
	}

	// Test relinquish via CLI.
	out, err = runAgentJam("session", "relinquish", id)
	if err != nil {
		t.Fatalf("relinquish: %v\n%s", err, out)
	}
	if !contains(out, "agent") {
		t.Errorf("relinquish output should mention agent mode:\n%s", out)
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr ||
		(len(s) > 0 && len(substr) > 0 &&
			indexOfString(s, substr) >= 0))
}

func indexOfString(s, substr string) int {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return i
		}
	}
	return -1
}

func init() {
	// Suppress unused fmt import if not needed elsewhere.
	_ = fmt.Sprintf("")
}
