// Package tui implements the terminal cockpit — the keyboard-driven,
// multi-agent management surface.
//
// The TUI uses the Bubble Tea framework (github.com/charmbracelet/bubbletea).
// It renders two main views:
//
//   - AgentListView: shows all active agents with status
//   - AgentFocusView: shows the full event stream for one agent
//
// Press Enter or `f` on an agent to focus. Press Esc or `b` to zoom back
// out to the agent list. Press `a` to assume control, `r` to relinquish,
// `p` to pause, `q` to quit.
//
// # Status
//
// This is a v1 scaffold. The view models, keybindings, and data flow are
// in place; the actual data sources (driver subscriptions, task store
// queries, vault interactions) are wired up via interfaces so the TUI
// can be tested and extended independently.
//
// To run: `agentjam cockpit` (the CLI command launches this).
package tui

import (
	"context"
	"fmt"
	"time"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

// Driver is the subset of driver.Driver that the TUI uses. Defined as
// an interface here so the TUI can be tested with mocks.
type Driver interface {
	ID() string
	Snapshot(ctx context.Context) (driver.State, error)
	Events() <-chan driver.Event
	Send(ctx context.Context, msg driver.Message) error
	Pause(ctx context.Context) error
	Resume(ctx context.Context) error
}

// DriverRegistry provides the TUI with the list of active agents.
type DriverRegistry interface {
	List() []Driver
	Get(id string) (Driver, bool)
}

// Model is the Bubble Tea model for the cockpit TUI.
type Model struct {
	registry DriverRegistry

	// View state.
	view           viewKind
	agents         []agentRow
	cursor         int
	focused        string // driver ID currently focused
	focusedDriver  Driver // cached for event watching (avoids re-dialing socket)
	events         []driver.Event
	eventsLimit    int

	// Dimensions.
	width  int
	height int

	// Quit flag.
	quitting bool
}

// viewKind distinguishes the two main views.
type viewKind int

const (
	viewAgentList viewKind = iota
	viewAgentFocus
)

// agentRow is a row in the agent list view.
type agentRow struct {
	driver Driver
	state  driver.State
}

// NewModel constructs a Model with the given registry.
func NewModel(registry DriverRegistry) Model {
	return Model{
		registry:    registry,
		view:        viewAgentList,
		eventsLimit: 500,
	}
}

// Init implements tea.Model. Returns the initial command.
func (m Model) Init() tea.Cmd {
	return tea.Batch(
		tickCmd(),
		fetchAgentsCmd(m.registry),
	)
}

// Update implements tea.Model. Handles key events and tick messages.
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case tea.KeyMsg:
		return m.handleKey(msg)

	case tickMsg:
		return m, tea.Batch(
			tickCmd(),
			fetchAgentsCmd(m.registry),
		)

	case agentsMsg:
		m.agents = msg.agents
		// Auto-focus first agent if nothing focused yet.
		if m.focused == "" && len(m.agents) > 0 {
			m.focused = m.agents[0].driver.ID()
			m.focusedDriver = m.agents[0].driver
		}
		// Start watching events for the focused agent (if any).
		if m.focusedDriver != nil {
			return m, watchEvents(m.focusedDriver)
		}
		return m, nil

	case eventMsg:
		// Collect events from the focused driver. No SessionID filter
		// needed — watchEvents is only called for the focused driver.
		m.events = append(m.events, msg.event)
		if len(m.events) > m.eventsLimit {
			m.events = m.events[len(m.events)-m.eventsLimit:]
		}
		// Re-issue watch to keep the event stream going.
		if m.focusedDriver != nil {
			return m, watchEvents(m.focusedDriver)
		}
		return m, nil

	case snapshotMsg:
		// Update state for the agent with matching ID.
		for i := range m.agents {
			if m.agents[i].driver.ID() == msg.id {
				m.agents[i].state = msg.state
			}
		}
		return m, nil
	}

	return m, nil
}

// handleKey processes key events.
func (m Model) handleKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	// Global keys.
	switch msg.String() {
	case "ctrl+c", "q":
		m.quitting = true
		return m, tea.Quit
	}

	switch m.view {
	case viewAgentList:
		return m.handleKeyList(msg)
	case viewAgentFocus:
		return m.handleKeyFocus(msg)
	}
	return m, nil
}

// handleKeyList processes keys in the agent list view.
func (m Model) handleKeyList(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "up", "k":
		if m.cursor > 0 {
			m.cursor--
		}
	case "down", "j":
		if m.cursor < len(m.agents)-1 {
			m.cursor++
		}
	case "enter", "f":
		// Focus the agent at the cursor.
		if m.cursor < len(m.agents) {
			m.focused = m.agents[m.cursor].driver.ID()
			m.focusedDriver = m.agents[m.cursor].driver
			m.view = viewAgentFocus
			m.events = nil
			// Start watching events for this agent.
			return m, watchEvents(m.focusedDriver)
		}
	case "p":
		// Pause the highlighted agent.
		if m.cursor < len(m.agents) {
			d := m.agents[m.cursor].driver
			return m, pauseCmd(d)
		}
	case "r":
		// Resume the highlighted agent.
		if m.cursor < len(m.agents) {
			d := m.agents[m.cursor].driver
			return m, resumeCmd(d)
		}
	}
	return m, nil
}

// handleKeyFocus processes keys in the focus view.
func (m Model) handleKeyFocus(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc", "b":
		m.view = viewAgentList
		m.events = nil
	case "p":
		if m.focusedDriver != nil {
			return m, pauseCmd(m.focusedDriver)
		}
	case "r":
		if m.focusedDriver != nil {
			return m, resumeCmd(m.focusedDriver)
		}
	case "a":
		// Assume control — placeholder for full implementation.
		// Full version: pause the agent, open a shell in its workspace.
		if m.focusedDriver != nil {
			return m, sendCmd(m.focusedDriver, driver.Message{
				Role:    "user",
				Content: "[assume control requested by user]",
			})
		}
	}
	return m, nil
}

// View implements tea.Model. Renders the current view.
func (m Model) View() string {
	if m.quitting {
		return ""
	}

	switch m.view {
	case viewAgentList:
		return m.viewList()
	case viewAgentFocus:
		return m.viewFocus()
	}
	return ""
}

// viewList renders the agent list.
func (m Model) viewList() string {
	var s string
	s += titleStyle.Render("agentjam cockpit — agents") + "\n\n"

	if len(m.agents) == 0 {
		s += dimStyle.Render("  No active agents.") + "\n"
		s += dimStyle.Render("  Run `agentjam agent spawn` to start one.") + "\n\n"
	} else {
		// Header.
		s += headerStyle.Render(fmt.Sprintf("  %-30s %-12s %-10s %s", "ID", "STATUS", "TOKENS", "TASK")) + "\n"

		// Rows.
		for i, a := range m.agents {
			row := fmt.Sprintf("  %-30s %-12s %-10d %s",
				truncate(a.driver.ID(), 30),
				a.state.Status,
				a.state.TokensUsed,
				truncate(a.state.CurrentTask, 30),
			)
			if i == m.cursor {
				s += selectedStyle.Render("▶ "+row[2:]) + "\n"
			} else {
				s += row + "\n"
			}
		}
		s += "\n"
	}

	s += dimStyle.Render("  ↑/↓: navigate  Enter/f: focus  p: pause  r: resume  q: quit") + "\n"
	return s
}

// viewFocus renders the focused agent's event stream.
func (m Model) viewFocus() string {
	var s string
	s += titleStyle.Render(fmt.Sprintf("agentjam cockpit — %s", truncate(m.focused, 30))) + "\n\n"

	if len(m.events) == 0 {
		s += dimStyle.Render("  No events yet.") + "\n\n"
	} else {
		// Show most recent N events that fit in the terminal.
		maxLines := m.height - 6
		if maxLines < 5 {
			maxLines = 5
		}
		start := 0
		if len(m.events) > maxLines {
			start = len(m.events) - maxLines
		}
		for _, e := range m.events[start:] {
			ts := e.Timestamp.Format("15:04:05")
			msg := e.Message
			if msg == "" && e.ToolCall != nil {
				msg = fmt.Sprintf("[tool] %s %v", e.ToolCall.Name, e.ToolCall.Args)
			}
			if msg == "" {
				msg = string(e.Type)
			}
			s += fmt.Sprintf("  %s  %s\n", dimStyle.Render(ts), truncate(msg, m.width-12))
		}
		s += "\n"
	}

	s += dimStyle.Render("  Esc/b: back  p: pause  r: resume  a: assume control  q: quit") + "\n"
	return s
}

// truncate shortens s to n chars with an ellipsis if needed.
func truncate(s string, n int) string {
	if n <= 0 {
		return ""
	}
	if len(s) <= n {
		return s
	}
	if n <= 3 {
		return s[:n]
	}
	return s[:n-3] + "..."
}

// --- Bubble Tea commands and messages ---

type tickMsg time.Time

// tickCmd fires every 2 seconds to refresh the view.
func tickCmd() tea.Cmd {
	return tea.Tick(2*time.Second, func(t time.Time) tea.Msg {
		return tickMsg(t)
	})
}

type agentsMsg struct {
	agents []agentRow
}

// fetchAgentsCmd queries the registry and emits an agentsMsg.
func fetchAgentsCmd(registry DriverRegistry) tea.Cmd {
	return func() tea.Msg {
		if registry == nil {
			return agentsMsg{}
		}
		drivers := registry.List()
		rows := make([]agentRow, 0, len(drivers))
		for _, d := range drivers {
			state, _ := d.Snapshot(context.Background())
			rows = append(rows, agentRow{driver: d, state: state})
		}
		return agentsMsg{agents: rows}
	}
}

type eventMsg struct {
	event driver.Event
}

// watchEvents returns a command that subscribes to driver events.
func watchEvents(d Driver) tea.Cmd {
	return func() tea.Msg {
		// Read one event off the channel and emit it.
		ev, ok := <-d.Events()
		if !ok {
			return nil
		}
		return eventMsg{event: ev}
	}
}

type snapshotMsg struct {
	id    string
	state driver.State
}

// snapshotCmd fetches a state snapshot for one driver.
func snapshotCmd(d Driver) tea.Cmd {
	return func() tea.Msg {
		state, err := d.Snapshot(context.Background())
		if err != nil {
			return nil
		}
		return snapshotMsg{id: d.ID(), state: state}
	}
}

func pauseCmd(d Driver) tea.Cmd {
	return func() tea.Msg {
		_ = d.Pause(context.Background())
		return nil
	}
}

func resumeCmd(d Driver) tea.Cmd {
	return func() tea.Msg {
		_ = d.Resume(context.Background())
		return nil
	}
}

func sendCmd(d Driver, msg driver.Message) tea.Cmd {
	return func() tea.Msg {
		_ = d.Send(context.Background(), msg)
		return nil
	}
}