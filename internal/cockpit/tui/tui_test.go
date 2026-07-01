package tui

import (
	"context"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

// mockDriver is a stub Driver for testing.
type mockDriver struct {
	id       string
	state    driver.State
	eventsCh chan driver.Event
}

func (m *mockDriver) ID() string { return m.id }

func (m *mockDriver) Snapshot(_ context.Context) (driver.State, error) {
	return m.state, nil
}

func (m *mockDriver) Events() <-chan driver.Event {
	return m.eventsCh
}

func (m *mockDriver) Send(_ context.Context, msg driver.Message) error {
	return nil
}

func (m *mockDriver) Pause(_ context.Context) error {
	m.state.Status = driver.StatusPaused
	return nil
}

func (m *mockDriver) Resume(_ context.Context) error {
	m.state.Status = driver.StatusRunning
	return nil
}

// mockRegistry is a stub DriverRegistry for testing.
type mockRegistry struct {
	drivers []Driver
}

func (m *mockRegistry) List() []Driver {
	return m.drivers
}

func (m *mockRegistry) Get(id string) (Driver, bool) {
	for _, d := range m.drivers {
		if d.ID() == id {
			return d, true
		}
	}
	return nil, false
}

func TestNewModel(t *testing.T) {
	m := NewModel(&mockRegistry{})
	if m.view != viewAgentList {
		t.Errorf("default view = %v, want viewAgentList", m.view)
	}
	if m.eventsLimit != 500 {
		t.Errorf("eventsLimit = %d", m.eventsLimit)
	}
}

func TestModel_Init(t *testing.T) {
	m := NewModel(&mockRegistry{})
	cmd := m.Init()
	if cmd == nil {
		t.Error("Init returned nil cmd")
	}
}

func TestHandleKey_Quit(t *testing.T) {
	m := NewModel(&mockRegistry{})

	updated, _ := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'q'}})
	model := updated.(Model)
	if !model.quitting {
		t.Error("expected quitting after q")
	}
}

func TestHandleKey_Navigation(t *testing.T) {
	d1 := &mockDriver{
		id:       "agent-1",
		eventsCh: make(chan driver.Event),
		state:    driver.State{Status: driver.StatusRunning},
	}
	d2 := &mockDriver{
		id:       "agent-2",
		eventsCh: make(chan driver.Event),
		state:    driver.State{Status: driver.StatusBlocked},
	}
	registry := &mockRegistry{drivers: []Driver{d1, d2}}

	m := NewModel(registry)
	// Simulate fetching agents.
	updated, _ := m.Update(agentsMsg{agents: []agentRow{
		{driver: d1, state: d1.state},
		{driver: d2, state: d2.state},
	}})
	model := updated.(Model)

	if model.cursor != 0 {
		t.Errorf("initial cursor = %d", model.cursor)
	}

	// Press down.
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'j'}})
	model = updated.(Model)
	if model.cursor != 1 {
		t.Errorf("after j cursor = %d, want 1", model.cursor)
	}

	// Press down at bottom.
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'j'}})
	model = updated.(Model)
	if model.cursor != 1 {
		t.Errorf("cursor at bottom should stay 1, got %d", model.cursor)
	}

	// Press up.
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'k'}})
	model = updated.(Model)
	if model.cursor != 0 {
		t.Errorf("after k cursor = %d, want 0", model.cursor)
	}
}

func TestHandleKey_Focus(t *testing.T) {
	d1 := &mockDriver{
		id:       "agent-1",
		eventsCh: make(chan driver.Event),
		state:    driver.State{Status: driver.StatusRunning},
	}
	registry := &mockRegistry{drivers: []Driver{d1}}

	m := NewModel(registry)
	updated, _ := m.Update(agentsMsg{agents: []agentRow{{driver: d1, state: d1.state}}})
	model := updated.(Model)

	// Press enter to focus.
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})
	model = updated.(Model)
	if model.view != viewAgentFocus {
		t.Errorf("view after enter = %v, want viewAgentFocus", model.view)
	}
	if model.focused != "agent-1" {
		t.Errorf("focused = %q", model.focused)
	}

	// Press esc to zoom back.
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyEsc})
	model = updated.(Model)
	if model.view != viewAgentList {
		t.Errorf("view after esc = %v", model.view)
	}
}

func TestHandleKey_PauseResume(t *testing.T) {
	d1 := &mockDriver{
		id:       "agent-1",
		eventsCh: make(chan driver.Event),
		state:    driver.State{Status: driver.StatusRunning},
	}
	registry := &mockRegistry{drivers: []Driver{d1}}

	m := NewModel(registry)
	updated, _ := m.Update(agentsMsg{agents: []agentRow{{driver: d1, state: d1.state}}})
	model := updated.(Model)

	// Press p to pause.
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'p'}})
	if d1.state.Status != driver.StatusPaused {
		t.Errorf("expected paused, got %s", d1.state.Status)
	}

	// Press r to resume.
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'r'}})
	if d1.state.Status != driver.StatusRunning {
		t.Errorf("expected running, got %s", d1.state.Status)
	}
}

func TestHandleEvent(t *testing.T) {
	d1 := &mockDriver{
		id:       "agent-1",
		eventsCh: make(chan driver.Event),
		state:    driver.State{Status: driver.StatusRunning},
	}
	m := NewModel(&mockRegistry{drivers: []Driver{d1}})
	m.focused = "agent-1"

	ev := driver.Event{
		Type:      driver.EventMessage,
		SessionID: "agent-1",
		Message:   "hello",
		Timestamp: time.Now(),
	}
	updated, _ := m.Update(eventMsg{event: ev})
	model := updated.(Model)
	if len(model.events) != 1 {
		t.Fatalf("events len = %d, want 1", len(model.events))
	}
	if model.events[0].Message != "hello" {
		t.Errorf("Message = %q", model.events[0].Message)
	}
}

func TestHandleEvent_FilterByFocus(t *testing.T) {
	d1 := &mockDriver{id: "agent-1", eventsCh: make(chan driver.Event)}
	d2 := &mockDriver{id: "agent-2", eventsCh: make(chan driver.Event)}
	m := NewModel(&mockRegistry{drivers: []Driver{d1, d2}})
	m.focused = "agent-1"

	// Event from focused agent.
	updated, _ := m.Update(eventMsg{event: driver.Event{SessionID: "agent-1", Type: driver.EventMessage, Message: "yes"}})
	model := updated.(Model)
	if len(model.events) != 1 {
		t.Errorf("focused event: len = %d", len(model.events))
	}

	// Event from non-focused agent.
	updated, _ = model.Update(eventMsg{event: driver.Event{SessionID: "agent-2", Type: driver.EventMessage, Message: "no"}})
	model = updated.(Model)
	if len(model.events) != 1 {
		t.Errorf("non-focused event: len = %d, want 1 (unchanged)", len(model.events))
	}
}

func TestEventsLimit(t *testing.T) {
	m := NewModel(&mockRegistry{})
	m.focused = "test"
	m.eventsLimit = 3

	// Push 5 events.
	for i := 0; i < 5; i++ {
		updated, _ := m.Update(eventMsg{event: driver.Event{
			SessionID: "test",
			Type:      driver.EventMessage,
			Message:   "x",
		}})
		m = updated.(Model)
	}
	if len(m.events) != 3 {
		t.Errorf("events len = %d, want 3 (limited)", len(m.events))
	}
}

func TestTruncate(t *testing.T) {
	cases := []struct {
		in  string
		n   int
		out string
	}{
		{"hello", 10, "hello"},
		{"hello world", 5, "he..."},
		{"hi", 5, "hi"},
		{"", 5, ""},
		{"abc", 2, "ab"},
		{"abc", 0, ""},
	}
	for _, c := range cases {
		got := truncate(c.in, c.n)
		if got != c.out {
			t.Errorf("truncate(%q, %d) = %q, want %q", c.in, c.n, got, c.out)
		}
	}
}

func TestView_Renders(t *testing.T) {
	d1 := &mockDriver{
		id:       "agent-1",
		eventsCh: make(chan driver.Event),
		state:    driver.State{Status: driver.StatusRunning, TokensUsed: 1234},
	}
	m := NewModel(&mockRegistry{drivers: []Driver{d1}})
	m.width = 100
	m.height = 30
	updated, _ := m.Update(agentsMsg{agents: []agentRow{{driver: d1, state: d1.state}}})
	model := updated.(Model)

	view := model.View()
	if view == "" {
		t.Error("empty view")
	}
	if !contains(view, "agent-1") {
		t.Errorf("view does not contain 'agent-1': %s", view)
	}
}

// contains is a tiny helper for substring checks in test strings.
func contains(s, substr string) bool {
	for i := 0; i+len(substr) <= len(s); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}