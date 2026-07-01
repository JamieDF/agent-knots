// Package driver defines the AgentDriver interface — the abstraction every
// agent backend (OpenCode today, custom drivers tomorrow) implements so the
// orchestrator can talk to any agent uniformly.
//
// The driver is the only piece of harness that knows how to talk to an actual
// LLM agent. Everything else (cockpit, task system, vault) talks to drivers
// through this interface.
//
// # Lifecycle
//
//  1. The orchestrator constructs a Driver via a factory function.
//  2. Start(ctx) launches the agent process / connection.
//  3. The orchestrator calls Send / Events / State / Pause / etc. as needed.
//  4. Stop(ctx) shuts the agent down cleanly.
//
// # Context
//
// Every method that does I/O takes a context.Context. Drivers must respect
// cancellation and surface ctx.Err() to callers via errs.Wrap or errs.ErrCanceled.
//
// # Thread safety
//
// Drivers must be safe for concurrent use. The orchestrator may call Send
// while another goroutine reads from Events().
package driver

import (
	"context"
	"errors"
	"time"
)

// Message is a single message exchanged with the agent. Roles follow the
// OpenAI / Anthropic convention so drivers can map directly.
type Message struct {
	// Role is one of "user", "assistant", "system", "tool".
	Role string

	// Content is the message body. For tool messages, contains the tool result.
	Content string

	// Name is set on "tool" messages to identify which tool produced the
	// result.
	Name string

	// ToolCallID is set on "tool" messages to correlate with the originating
	// assistant tool call.
	ToolCallID string

	// Timestamp is when the message was produced. Drivers should set this to
	// time.Now() if not provided.
	Timestamp time.Time
}

// Event is a structured event from the agent. Drivers emit Events on the
// channel returned by Events(). See EventType for the available types.
type Event struct {
	// Type identifies the event. See EventType constants.
	Type EventType

	// SessionID identifies which agent session produced the event.
	SessionID string

	// Timestamp is when the event was emitted.
	Timestamp time.Time

	// Message is set for message, thinking, blocker, and progress events.
	Message string

	// ToolCall is set for tool_call and tool_result events.
	ToolCall *ToolCall

	// State is set for state_change events.
	State *State

	// Error is set for error events.
	Error string

	// Data carries event-type-specific structured data. JSON-encoded for
	// forward-compatibility with unknown event types.
	Data []byte
}

// EventType is a string enum of driver event types. New types may be added
// in minor versions; consumers should default-handle unknown types.
type EventType string

const (
	// EventMessage is the agent emitting a chat message (text response).
	EventMessage EventType = "message"

	// EventThinking is the agent's reasoning, before tool calls or final
	// answer.
	EventThinking EventType = "thinking"

	// EventToolCall is the agent invoking a tool.
	EventToolCall EventType = "tool_call"

	// EventToolResult is the result of a tool invocation.
	EventToolResult EventType = "tool_result"

	// EventBlocker is the agent requesting user input (a question, an
	// approval gate, etc.).
	EventBlocker EventType = "blocker"

	// EventProgress is a structured progress log entry (task progress).
	EventProgress EventType = "progress"

	// EventStateChange is the agent transitioning between states
	// (e.g. running -> blocked -> running).
	EventStateChange EventType = "state_change"

	// EventError is a non-fatal error from the agent (e.g. tool failed but
	// agent continued).
	EventError EventType = "error"
)

// ToolCall describes a tool invocation by the agent.
type ToolCall struct {
	// ID is a unique identifier for this call, used to correlate with results.
	ID string

	// Name is the tool name (e.g. "bash", "read", "edit", "vault_use").
	Name string

	// Args is the tool arguments as a JSON object.
	Args map[string]any
}

// ToolResult is the outcome of a tool invocation. Returned via EventToolResult
// events.
type ToolResult struct {
	ToolCallID string
	Stdout     string
	Stderr     string
	ExitCode   int
	Error      string
}

// State is a snapshot of the agent's current state.
type State struct {
	// Status is the agent lifecycle state.
	Status Status

	// CurrentTask is the ID of the task the agent is currently working on, or
	// empty if none.
	CurrentTask string

	// LastAction is a short human-readable description of what the agent is
	// doing right now (e.g. "edit_file src/auth.py").
	LastAction string

	// TokensUsed is the cumulative token count for this session.
	TokensUsed int64

	// CostUSD is the cumulative spend for this session, if the provider
	// reports pricing.
	CostUSD float64

	// Uptime is the duration since the agent started.
	Uptime time.Duration
}

// Status is the agent's lifecycle state.
type Status string

const (
	// StatusIdle means the agent is alive but not actively doing anything.
	StatusIdle Status = "idle"

	// StatusRunning means the agent is processing or executing tools.
	StatusRunning Status = "running"

	// StatusBlocked means the agent is waiting for user input.
	StatusBlocked Status = "blocked"

	// StatusPaused means the agent was paused by the user via Pause().
	StatusPaused Status = "paused"

	// StatusError means the agent hit a fatal error.
	StatusError Status = "error"

	// StatusStopped means the agent has been stopped and cannot be resumed.
	StatusStopped Status = "stopped"
)

// Mode identifies the agent's behavioral persona. Modes are system prompts;
// see internal/mode for the loader.
type Mode string

const (
	// ModeAssistant is interactive, waits for user input.
	ModeAssistant Mode = "assistant"

	// ModeAgent is autonomous, spec-driven, works to completion.
	ModeAgent Mode = "agent"

	// ModeReviewer is read-only, finds issues.
	ModeReviewer Mode = "reviewer"

	// ModeSecurity audits for vulnerabilities.
	ModeSecurity Mode = "security"
)

// Driver is the interface every agent backend implements.
//
// Implementations live under internal/drivers/. The orchestrator only ever
// holds a Driver; it does not know which backend it is.
//
// All methods must be safe for concurrent use. Event delivery is via a channel
// returned by Events(); the driver closes that channel when Stop() succeeds
// or when the underlying agent process exits.
type Driver interface {
	// Start launches the agent. It must return only after the agent is
	// ready to receive messages (or after reporting a startup error).
	Start(ctx context.Context) error

	// Stop shuts the agent down. After Stop returns, the Events channel will
	// be closed.
	Stop(ctx context.Context) error

	// Send delivers a message to the agent. It returns nil once the message
	// is queued; delivery is observed via Events.
	Send(ctx context.Context, msg Message) error

	// Events returns a channel of structured events from the agent. The
	// channel is closed when the driver stops or the underlying agent
	// exits.
	Events() <-chan Event

	// Snapshot returns the agent's current state.
	Snapshot(ctx context.Context) (State, error)

	// SetMode swaps the agent's behavioral persona. This is a system-prompt
	// change; the driver should preserve ongoing context.
	SetMode(ctx context.Context, mode Mode) error

	// Pause halts autonomous action but keeps the session open. The agent
	// may still respond to Send (e.g. answering questions) but should not
	// invoke tools unilaterally.
	Pause(ctx context.Context) error

	// Resume continues a paused agent.
	Resume(ctx context.Context) error

	// Abort stops the agent and discards the session. After Abort, the
	// driver is unusable.
	Abort(ctx context.Context) error

	// ID returns a stable identifier for this driver instance (used in
	// logs and events).
	ID() string
}

// ErrClosed is returned by Send / Snapshot / etc. after Stop has been
// called. Drivers must return this rather than panic on use-after-close.
var ErrClosed = errors.New("driver: closed")

// IsClosed reports whether err indicates the driver is closed.
func IsClosed(err error) bool {
	return errors.Is(err, ErrClosed)
}