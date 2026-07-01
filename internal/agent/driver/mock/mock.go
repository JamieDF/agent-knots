// Package mock provides a driver.Driver implementation that emits scripted
// fake events. It requires no external services (no OpenCode server, no LLM
// API) and is used for testing, development, and demos.
//
// The mock driver cycles through a realistic agent workflow: thinking,
// tool calls, tool results, messages, and progress updates. Each cycle
// increments the token count. Pause/Resume controls the event generator
// goroutine.
//
// # Usage
//
//	d := mock.New(mock.Options{ID: "mock-S001", TaskID: "T-001"})
//	d.Start(ctx)   // begins emitting events
//	events := d.Events()
//	// ... read from events channel ...
//	d.Stop(ctx)    // closes the events channel
package mock

import (
	"context"
	"fmt"
	"math/rand"
	"sync"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/errs"
)

// Options configures a mock driver.
type Options struct {
	// ID is the driver identifier returned by ID().
	ID string

	// TaskID is the task being worked on (shown in state snapshots).
	TaskID string

	// Mode is the initial agent mode.
	Mode driver.Mode

	// Interval between events. Default 1.5s. Use a smaller value for
	// tests (e.g. 50ms).
	Interval time.Duration

	// Seed for the random number generator. 0 = auto-seed from clock.
	// Set to a fixed value for deterministic test output.
	Seed int64
}

// Driver implements driver.Driver with scripted fake events.
//
// On Start, a goroutine begins cycling through the event script,
// emitting events on the channel returned by Events(). The goroutine
// respects Pause/Resume and stops when Stop or Abort is called.
type Driver struct {
	id       string
	taskID   string
	mode     driver.Mode
	interval time.Duration
	rng      *rand.Rand

	mu         sync.Mutex
	status     driver.Status
	tokens     int64
	cost       float64
	startedAt  time.Time
	lastAction string
	modeNow    driver.Mode

	events  chan driver.Event
	stopCh  chan struct{}
	stopped bool
	started bool
}

// New creates a mock driver. The driver is not running until Start is called.
func New(opts Options) *Driver {
	interval := opts.Interval
	if interval <= 0 {
		interval = 1500 * time.Millisecond
	}
	seed := opts.Seed
	if seed == 0 {
		seed = time.Now().UnixNano()
	}
	mode := opts.Mode
	if mode == "" {
		mode = driver.ModeAgent
	}
	return &Driver{
		id:       opts.ID,
		taskID:   opts.TaskID,
		mode:     mode,
		modeNow:  mode,
		interval: interval,
		rng:      rand.New(rand.NewSource(seed)),
		events:   make(chan driver.Event, 64),
		stopCh:   make(chan struct{}),
	}
}

// compile-time interface check.
var _ driver.Driver = (*Driver)(nil)

// Start launches the event-generation goroutine.
func (d *Driver) Start(_ context.Context) error {
	d.mu.Lock()
	if d.started {
		d.mu.Unlock()
		return errs.Wrap(errs.ErrAlreadyExists, "mock driver already started")
	}
	d.started = true
	d.status = driver.StatusRunning
	d.startedAt = time.Now().UTC()
	d.mu.Unlock()

	go d.eventLoop()
	return nil
}

// Stop stops the event goroutine and closes the events channel.
func (d *Driver) Stop(_ context.Context) error {
	d.mu.Lock()
	if d.stopped {
		d.mu.Unlock()
		return nil
	}
	d.stopped = true
	d.status = driver.StatusStopped
	d.mu.Unlock()

	close(d.stopCh)
	close(d.events)
	return nil
}

// Send injects a user message as an event into the stream. This lets
// the cockpit's "assume control" flow produce a visible effect.
func (d *Driver) Send(_ context.Context, msg driver.Message) error {
	d.mu.Lock()
	if d.stopped {
		d.mu.Unlock()
		return driver.ErrClosed
	}
	d.mu.Unlock()

	ev := driver.Event{
		Type:      driver.EventMessage,
		SessionID: d.id,
		Timestamp: time.Now().UTC(),
		Message:   fmt.Sprintf("[user] %s", msg.Content),
	}
	select {
	case d.events <- ev:
	default:
		// channel full; drop silently
	}
	return nil
}

// Events returns the channel of scripted events.
func (d *Driver) Events() <-chan driver.Event {
	return d.events
}

// Snapshot returns the current agent state.
func (d *Driver) Snapshot(_ context.Context) (driver.State, error) {
	d.mu.Lock()
	defer d.mu.Unlock()

	var uptime time.Duration
	if !d.startedAt.IsZero() {
		uptime = time.Since(d.startedAt)
	}
	return driver.State{
		Status:      d.status,
		CurrentTask: d.taskID,
		LastAction:  d.lastAction,
		TokensUsed:  d.tokens,
		CostUSD:     d.cost,
		Uptime:      uptime,
	}, nil
}

// SetMode changes the agent's behavioral mode.
func (d *Driver) SetMode(_ context.Context, mode driver.Mode) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.modeNow = mode
	return nil
}

// Pause halts event generation. The agent enters the paused state.
func (d *Driver) Pause(_ context.Context) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.status == driver.StatusStopped {
		return driver.ErrClosed
	}
	d.status = driver.StatusPaused
	return nil
}

// Resume continues event generation after a pause.
func (d *Driver) Resume(_ context.Context) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.status == driver.StatusStopped {
		return driver.ErrClosed
	}
	if d.status == driver.StatusPaused {
		d.status = driver.StatusRunning
	}
	return nil
}

// Abort is equivalent to Stop for the mock driver.
func (d *Driver) Abort(_ context.Context) error {
	return d.Stop(context.Background())
}

// ID returns the driver identifier.
func (d *Driver) ID() string {
	return d.id
}

// --- Event generation ---

// scriptStep defines one step in the repeating event cycle.
type scriptStep struct {
	eventType driver.EventType
	message   string
	toolName  string
	toolArgs  map[string]any
	tokens    int64
}

// script is the repeating event sequence. It simulates a realistic
// agent workflow: analyze → read → reason → edit → test → report.
var script = []scriptStep{
	{eventType: driver.EventThinking, message: "Analyzing the task structure and dependencies...", tokens: 120},
	{eventType: driver.EventToolCall, toolName: "read_file", toolArgs: map[string]any{"path": "src/main.go"}, tokens: 80},
	{eventType: driver.EventToolResult, message: "read_file: 245 lines", tokens: 45},
	{eventType: driver.EventMessage, message: "I can see the issue is in the authentication module. The token validation is missing an expiry check.", tokens: 95},
	{eventType: driver.EventThinking, message: "Designing the fix for the token expiry validation...", tokens: 110},
	{eventType: driver.EventToolCall, toolName: "edit_file", toolArgs: map[string]any{"path": "src/auth.go", "lines": "142-158"}, tokens: 70},
	{eventType: driver.EventToolResult, message: "edit_file: 17 lines changed", tokens: 40},
	{eventType: driver.EventProgress, message: "Implemented token expiry validation. Moving to tests.", tokens: 30},
	{eventType: driver.EventThinking, message: "Writing test cases for edge conditions...", tokens: 90},
	{eventType: driver.EventToolCall, toolName: "bash", toolArgs: map[string]any{"cmd": "go test ./auth/... -v"}, tokens: 60},
	{eventType: driver.EventToolResult, message: "PASS (3 tests, 0 failures)", tokens: 50},
	{eventType: driver.EventMessage, message: "All tests passing. The fix handles expired tokens, missing claims, and clock skew gracefully.", tokens: 85},
	{eventType: driver.EventProgress, message: "Step 2 of 3 complete. Reviewing changes before commit.", tokens: 25},
	{eventType: driver.EventToolCall, toolName: "bash", toolArgs: map[string]any{"cmd": "git diff --stat"}, tokens: 40},
	{eventType: driver.EventToolResult, message: "2 files changed, 24 insertions(+), 8 deletions(-)", tokens: 35},
	{eventType: driver.EventMessage, message: "Changes look clean. Ready for review.", tokens: 75},
}

// eventLoop is the main goroutine that emits scripted events.
func (d *Driver) eventLoop() {
	stepIdx := 0
	ticker := time.NewTicker(d.interval)
	defer ticker.Stop()

	for {
		select {
		case <-d.stopCh:
			return
		case <-ticker.C:
		}

		// Check if paused.
		d.mu.Lock()
		if d.status != driver.StatusRunning {
			d.mu.Unlock()
			continue
		}
		d.mu.Unlock()

		step := script[stepIdx%len(script)]
		stepIdx++

		d.emitStep(step)
	}
}

// emitStep sends a scripted step as an event and updates state.
func (d *Driver) emitStep(s scriptStep) {
	d.mu.Lock()
	d.tokens += s.tokens
	d.cost = float64(d.tokens) * 0.00003 // rough pricing
	action := ""
	if s.toolName != "" {
		action = s.toolName
	} else if s.message != "" {
		action = truncate(s.message, 40)
	}
	d.lastAction = action
	sid := d.id
	d.mu.Unlock()

	ev := driver.Event{
		Type:      s.eventType,
		SessionID: sid,
		Timestamp: time.Now().UTC(),
		Message:   s.message,
	}
	if s.toolName != "" {
		ev.ToolCall = &driver.ToolCall{
			ID:   fmt.Sprintf("call-%d", d.rng.Intn(100000)),
			Name: s.toolName,
			Args: s.toolArgs,
		}
	}

	select {
	case d.events <- ev:
	case <-d.stopCh:
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if n <= 3 {
		return s[:n]
	}
	return s[:n-3] + "..."
}
