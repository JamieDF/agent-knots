package driver

import (
	"testing"
	"time"
)

func TestEventTypes(t *testing.T) {
	cases := []struct {
		et   EventType
		want string
	}{
		{EventMessage, "message"},
		{EventThinking, "thinking"},
		{EventToolCall, "tool_call"},
		{EventToolResult, "tool_result"},
		{EventBlocker, "blocker"},
		{EventProgress, "progress"},
		{EventStateChange, "state_change"},
		{EventError, "error"},
	}
	for _, c := range cases {
		if string(c.et) != c.want {
			t.Errorf("EventType %q != %q", c.et, c.want)
		}
	}
}

func TestStatusValues(t *testing.T) {
	all := []Status{
		StatusIdle, StatusRunning, StatusBlocked,
		StatusPaused, StatusError, StatusStopped,
	}
	seen := make(map[Status]bool)
	for _, s := range all {
		if seen[s] {
			t.Errorf("duplicate status %q", s)
		}
		if s == "" {
			t.Error("empty status")
		}
		seen[s] = true
	}
}

func TestMessageZero(t *testing.T) {
	var m Message
	if m.Role != "" || m.Content != "" {
		t.Errorf("zero message should have zero values, got %+v", m)
	}
}

func TestStateZero(t *testing.T) {
	var s State
	if s.Status != "" {
		t.Errorf("zero state should have empty status, got %q", s.Status)
	}
	if s.Uptime != 0 {
		t.Errorf("zero state should have zero uptime, got %v", s.Uptime)
	}
	if s.TokensUsed != 0 {
		t.Errorf("zero state should have zero tokens, got %d", s.TokensUsed)
	}
}

func TestToolCallArgs(t *testing.T) {
	tc := ToolCall{
		ID:   "call_1",
		Name: "bash",
		Args: map[string]any{"command": "ls -la"},
	}
	if tc.ID != "call_1" {
		t.Errorf("ID = %q", tc.ID)
	}
	if tc.Name != "bash" {
		t.Errorf("Name = %q", tc.Name)
	}
	if cmd, _ := tc.Args["command"].(string); cmd != "ls -la" {
		t.Errorf("Args[command] = %v", tc.Args["command"])
	}
}

// ExampleEvent shows how to discriminate on event type in a consumer.
func ExampleEvent() {
	e := Event{Type: EventMessage, Message: "hello"}
	switch e.Type {
	case EventMessage:
		_ = e.Message
	case EventToolCall:
		_ = e.ToolCall
	case EventStateChange:
		_ = e.State
	}
	// Just demonstrating switch — no output.
	_ = time.Now()
}