// Package pi implements driver.Driver via Pi's RPC mode subprocess.
//
// Pi (https://pi.dev) is an AI coding agent. This driver spawns Pi as a
// subprocess in RPC mode (`pi --mode rpc`) and communicates via
// bidirectional JSONL over stdin/stdout.
//
// Architecture:
//
//	Driver.Start(ctx)             → spawn pi --mode rpc subprocess
//	Driver.Send(ctx, msg)         → write {"type":"prompt",...} to stdin
//	Driver.SetMode(ctx, mode)     → set_thinking_level + /agentjam-switch
//	Driver.Pause(ctx)             → write {"type":"abort"} to stdin
//	Driver.Stop(ctx)              → cancel context, close stdin, wait
//	Driver.Events()               → channel fed by stdout reader goroutine
//	Driver.Snapshot(ctx)          → sends get_state/get_session_stats, awaits response
//
// The stdout reader goroutine parses JSONL events from Pi, translates them
// into driver.Event, and dispatches command responses to pending channels
// for synchronous Snapshot calls.
package pi

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/errs"
)

// Driver implements driver.Driver by wrapping a Pi RPC subprocess.
type Driver struct {
	id      string
	workdir string

	// Pi subprocess details.
	piPath   string
	modeFile string
	provider string
	model    string

	// State.
	mu        sync.Mutex
	mode      driver.Mode
	status    driver.Status
	tokens    int64
	cost      float64
	lastAct   string
	startedAt time.Time

	// Subprocess handles.
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	cancel context.CancelFunc
	exited chan struct{}

	// containerCmd, when non-nil, is used instead of the default
	// exec.Command("pi", ...). Podman wrappers set this to build a
	// podman run command.
	containerCmd func(ctx context.Context) *exec.Cmd

	// Event channel (fed by readLoop).
	events chan driver.Event

	// Response routing: command ID → response channel.
	pendingMu sync.Mutex
	pending   map[int64]chan jsonResponse

	nextID atomic.Int64
	closed atomic.Bool
}

// Options configures a new Pi driver.
type Options struct {
	// ID is the driver instance identifier. If empty, one is generated.
	ID string

	// Workdir is the working directory Pi operates in.
	Workdir string

	// ModeFile is the path to the mode markdown (system prompt).
	ModeFile string

	// PiPath is the path to the pi binary. Empty = "pi" on PATH.
	PiPath string

	// Provider is the LLM provider. Empty = Pi's own default.
	Provider string

	// Model is the model pattern or ID. Empty = Pi's own default.
	Model string
}

// New constructs a Driver. Call Start to launch the subprocess.
func New(opts Options) (*Driver, error) {
	if opts.Workdir == "" {
		return nil, fmt.Errorf("pi driver: workdir is required")
	}

	id := opts.ID
	if id == "" {
		id = fmt.Sprintf("pi-%d", time.Now().UnixNano())
	}

	piPath := opts.PiPath
	if piPath == "" {
		piPath = "pi"
	}

	return &Driver{
		id:       id,
		workdir:  opts.Workdir,
		piPath:   piPath,
		modeFile: opts.ModeFile,
		provider: opts.Provider,
		model:    opts.Model,
		mode:     driver.ModeAgent,
		status:   driver.StatusIdle,
		events:   make(chan driver.Event, 64),
		pending:  make(map[int64]chan jsonResponse),
		exited:   make(chan struct{}),
	}, nil
}

// ID implements driver.Driver.
func (d *Driver) ID() string { return d.id }

// Start implements driver.Driver. Spawns the Pi subprocess and starts
// the reader goroutine.
func (d *Driver) Start(ctx context.Context) error {
	if d.closed.Load() {
		return driver.ErrClosed
	}

	args := []string{
		"--mode", "rpc",
		"--no-session",
	}
	if d.modeFile != "" {
		args = append(args, "--system-prompt", d.modeFile)
	}
	if d.provider != "" {
		args = append(args, "--provider", d.provider)
	}
	if d.model != "" {
		args = append(args, "--model", d.model)
	}

	ctx, d.cancel = context.WithCancel(ctx)

	if d.containerCmd != nil {
		d.cmd = d.containerCmd(ctx)
	} else {
		d.cmd = exec.CommandContext(ctx, d.piPath, args...)
	}
	d.cmd.Dir = d.workdir

	var err error
	d.stdin, err = d.cmd.StdinPipe()
	if err != nil {
		d.cancel()
		return fmt.Errorf("pi driver: stdin pipe: %w", err)
	}

	stdout, err := d.cmd.StdoutPipe()
	if err != nil {
		d.cancel()
		return fmt.Errorf("pi driver: stdout pipe: %w", err)
	}

	// Capture stderr for debugging.
	d.cmd.Stderr = &piStderrLogger{id: d.id}

	if err := d.cmd.Start(); err != nil {
		d.cancel()
		return fmt.Errorf("pi driver: start process: %w", err)
	}

	d.mu.Lock()
	d.startedAt = time.Now()
	d.status = driver.StatusRunning
	d.mu.Unlock()

	// Start the stdout reader goroutine.
	go d.readLoop(ctx, stdout)

	// Monitor for subprocess exit.
	go func() {
		_ = d.cmd.Wait()
		d.mu.Lock()
		d.status = driver.StatusStopped
		d.mu.Unlock()
		close(d.exited)
	}()

	// Emit agent_start.
	d.pushEvent(driver.Event{
		Type:      driver.EventStateChange,
		SessionID: d.id,
		Timestamp: time.Now(),
		Message:   "agent started (pi --mode rpc)",
	})

	return nil
}

// Stop implements driver.Driver. Cancels the context, closes stdin,
// and waits for the subprocess to exit.
func (d *Driver) Stop(ctx context.Context) error {
	if d.closed.Swap(true) {
		return nil
	}

	if d.cancel != nil {
		d.cancel()
	}

	if d.stdin != nil {
		_ = d.stdin.Close()
	}

	// Wait for exit with timeout from ctx.
	select {
	case <-d.exited:
	case <-ctx.Done():
		// Force kill if it hasn't exited.
		if d.cmd != nil && d.cmd.Process != nil {
			_ = d.cmd.Process.Kill()
		}
	}

	close(d.events)
	return nil
}

// Send implements driver.Driver. Writes a prompt command to Pi's stdin.
func (d *Driver) Send(_ context.Context, msg driver.Message) error {
	if d.closed.Load() {
		return driver.ErrClosed
	}
	if msg.Role != "user" {
		return errs.Wrap(errs.ErrInvalid, "only user messages can be sent; got %q", msg.Role)
	}

	id := d.nextID.Add(1)
	cmd := piCommand{
		ID:      &id,
		Type:    "prompt",
		Message: msg.Content,
	}
	return d.writeCmd(cmd)
}

// Events implements driver.Driver.
func (d *Driver) Events() <-chan driver.Event { return d.events }

// SetMode implements driver.Driver. Sends a thinking-level change and
// invokes the agentjam-switch extension command for persona swap.
func (d *Driver) SetMode(ctx context.Context, mode driver.Mode) error {
	if d.closed.Load() {
		return driver.ErrClosed
	}

	d.mu.Lock()
	prevMode := d.mode
	d.mode = mode
	d.mu.Unlock()

	// 1. Change thinking level.
	level := modeToThinkingLevel(mode)
	_ = d.writeCmd(piCommand{
		Type:  "set_thinking_level",
		Level: level,
	})

	// 2. Invoke the extension for persona swap.
	// Send as a prompt message — Pi dispatches slash commands to extensions.
	// The extension command is /agentjam-switch.
	msg := fmt.Sprintf("/agentjam-switch %s", mode)
	_ = d.writeCmd(piCommand{
		Type:    "prompt",
		Message: msg,
	})

	// 3. Emit a state_change event.
	d.pushEvent(driver.Event{
		Type:      driver.EventStateChange,
		SessionID: d.id,
		Timestamp: time.Now(),
		Message:   fmt.Sprintf("mode changed: %s → %s", prevMode, mode),
	})

	return nil
}

// Pause implements driver.Driver. Sends an abort command to stop the
// current agent turn.
func (d *Driver) Pause(ctx context.Context) error {
	if d.closed.Load() {
		return driver.ErrClosed
	}
	return d.writeCmd(piCommand{Type: "abort"})
}

// Resume implements driver.Driver. Pi resumes on next prompt; no-op here.
func (d *Driver) Resume(_ context.Context) error { return nil }

// Abort implements driver.Driver. Stops the driver and discards the session.
func (d *Driver) Abort(ctx context.Context) error {
	return d.Stop(ctx)
}

// Snapshot implements driver.Driver. Sends get_state and get_session_stats
// commands synchronously and returns the merged state.
func (d *Driver) Snapshot(ctx context.Context) (driver.State, error) {
	if d.closed.Load() {
		return driver.State{}, driver.ErrClosed
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	// Try to get state + stats from Pi. If Pi isn't ready (no session
	// yet, etc.), return our locally-tracked state.
	stateResult := d.syncCommand(ctx, piCommand{Type: "get_state"})
	if stateResult != nil {
		if data, ok := stateResult["data"].(map[string]any); ok {
			if streaming, ok := data["isStreaming"].(bool); ok && streaming {
				d.status = driver.StatusRunning
			} else if d.status != driver.StatusRunning {
				d.status = driver.StatusIdle
			}
			if name, ok := data["sessionName"].(string); ok && name != "" {
				d.lastAct = name
			}
		}
	}

	statsResult := d.syncCommand(ctx, piCommand{Type: "get_session_stats"})
	if statsResult != nil {
		if data, ok := statsResult["data"].(map[string]any); ok {
			if tokens, ok := data["tokens"].(map[string]any); ok {
				if total, ok := tokens["total"].(float64); ok {
					d.tokens = int64(total)
				}
			}
			if cost, ok := data["cost"].(float64); ok {
				d.cost = cost
			}
		}
	}

	return driver.State{
		Status:     d.status,
		CurrentTask: d.lastAct,
		LastAction: d.lastAct,
		TokensUsed: d.tokens,
		CostUSD:    d.cost,
		Uptime:     time.Since(d.startedAt),
	}, nil
}

// --- Internal methods ---

// writeCmd marshals a command as JSON and writes it to Pi's stdin as a
// JSONL line. Returns immediately; does not wait for a response.
func (d *Driver) writeCmd(cmd piCommand) error {
	data, err := json.Marshal(cmd)
	if err != nil {
		return fmt.Errorf("marshal pi command: %w", err)
	}
	data = append(data, '\n')

	if d.stdin == nil {
		return fmt.Errorf("pi driver: stdin not open")
	}
	_, err = d.stdin.Write(data)
	return err
}

// syncCommand sends a command and waits for the response. Returns the
// response JSON, or nil on timeout/error.
func (d *Driver) syncCommand(ctx context.Context, cmd piCommand) map[string]any {
	id := d.nextID.Add(1)
	cmd.ID = &id

	ch := make(chan jsonResponse, 1)
	d.pendingMu.Lock()
	d.pending[id] = ch
	d.pendingMu.Unlock()

	defer func() {
		d.pendingMu.Lock()
		delete(d.pending, id)
		d.pendingMu.Unlock()
	}()

	if err := d.writeCmd(cmd); err != nil {
		return nil
	}

	select {
	case resp := <-ch:
		if !resp.Success {
			return nil
		}
		return resp.Data
	case <-ctx.Done():
		return nil
	case <-d.exited:
		return nil
	}
}

// pushEvent sends an event to the events channel. Non-blocking — drops
// if the channel is full (TUI/web not reading fast enough).
func (d *Driver) pushEvent(ev driver.Event) {
	select {
	case d.events <- ev:
	default:
	}
}

// readLoop reads JSONL lines from Pi's stdout and dispatches them to
// either the events channel (for events) or the pending map (for responses).
func (d *Driver) readLoop(ctx context.Context, stdout io.ReadCloser) {
	defer stdout.Close()

	scanner := bufio.NewScanner(stdout)
	// Use a larger buffer for large JSON lines.
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)

	// Override split function to split on LF only (Pi's framing).
	scanner.Split(bufio.ScanLines)

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}
		d.processLine(line)
	}
	if err := scanner.Err(); err != nil && err != io.EOF {
		d.pushEvent(driver.Event{
			Type:      driver.EventError,
			SessionID: d.id,
			Timestamp: time.Now(),
			Error:     fmt.Sprintf("pi stdout read error: %v", err),
		})
	}
}

// processLine handles one JSONL line from Pi's stdout.
func (d *Driver) processLine(line string) {
	var msg jsonMessage
	if err := json.Unmarshal([]byte(line), &msg); err != nil {
		return // skip malformed lines
	}

	switch {
	case msg.Type == "response":
		d.handleResponse(&msg)
	default:
		d.handleEvent(&msg)
	}
}

// handleResponse dispatches a command response to the pending channel.
func (d *Driver) handleResponse(msg *jsonMessage) {
	if msg.ID == nil {
		return
	}
	d.pendingMu.Lock()
	ch, ok := d.pending[*msg.ID]
	d.pendingMu.Unlock()
	if !ok {
		return
	}
	select {
	case ch <- jsonResponse{
		ID:      *msg.ID,
		Success: msg.Success,
		Data:   msg.Data,
	}:
	default:
	}
}

// handleEvent translates a Pi JSON event into a driver.Event and pushes it.
func (d *Driver) handleEvent(msg *jsonMessage) {
	ev := d.translateEvent(msg)
	if ev.Type == "" {
		return // skip unhandled events
	}
	d.pushEvent(ev)
}

// translateEvent converts a Pi JSON event into a driver.Event.
func (d *Driver) translateEvent(msg *jsonMessage) driver.Event {
	ev := driver.Event{
		SessionID: d.id,
		Timestamp: time.Now(),
	}

	switch msg.Type {
	case "agent_start":
		ev.Type = driver.EventStateChange
		ev.Message = "agent started"

	case "agent_end":
		ev.Type = driver.EventStateChange
		ev.Message = "agent ended"

	case "message_start":
		// Skip — use message_update and message_end instead.

	case "message_update":
		ev = d.translateMessageUpdate(msg)

	case "message_end":
		// Flush pending accumulated text.
		if msg.Message != nil {
			ev.Type = driver.EventMessage
			content := extractAssistantContent(msg.Message)
			if content != "" {
				ev.Message = content
			}
		}

	case "tool_execution_start":
		ev.Type = driver.EventToolCall
		tc := &driver.ToolCall{
			ID:   stringField(msg, "toolCallId"),
			Name: stringField(msg, "toolName"),
		}
		if args, ok := msg.Data["args"].(map[string]any); ok {
			tc.Args = args
		}
		ev.ToolCall = tc

	case "tool_execution_end":
		ev.Type = driver.EventToolResult

	case "compaction_start":
		ev.Type = driver.EventProgress
		ev.Message = fmt.Sprintf("compacting context (reason: %s)", stringField(msg, "reason"))

	case "compaction_end":
		ev.Type = driver.EventProgress
		result := msg.Data["result"]
		if r, ok := result.(map[string]any); ok {
			before, _ := r["tokensBefore"].(float64)
			after, _ := r["estimatedTokensAfter"].(float64)
			ev.Message = fmt.Sprintf("context compacted: ~%.0f → ~%.0f tokens", before, after)
		} else {
			ev.Message = "context compacted"
		}

	case "auto_retry_start":
		ev.Type = driver.EventError
		ev.Error = fmt.Sprintf("retrying after error (attempt %d/%d): %s",
			intField(msg, "attempt"), intField(msg, "maxAttempts"), stringField(msg, "errorMessage"))

	case "auto_retry_end":
		if success, _ := msg.Data["success"].(bool); !success {
			ev.Type = driver.EventError
			ev.Error = fmt.Sprintf("retry failed: %s", stringField(msg, "finalError"))
		} else {
			ev.Type = driver.EventProgress
			ev.Message = "retry succeeded"
		}

	case "queue_update":
		// Progress event — show pending steering/follow-up messages.
		steering := msg.Data["steering"]
		followUp := msg.Data["followUp"]
		if steering != nil || followUp != nil {
			ev.Type = driver.EventProgress
			ev.Message = fmt.Sprintf("queue: %d steering, %d follow-up", lenSlice(steering), lenSlice(followUp))
		}

	case "extension_error":
		ev.Type = driver.EventError
		ev.Error = fmt.Sprintf("extension error: %s", stringField(msg, "error"))

	default:
		// Unknown event — skip it.
	}

	return ev
}

// translateMessageUpdate handles the streaming message_update event.
func (d *Driver) translateMessageUpdate(msg *jsonMessage) driver.Event {
	ev := driver.Event{
		SessionID: d.id,
		Timestamp: time.Now(),
	}

	delta, ok := msg.Data["assistantMessageEvent"].(map[string]any)
	if !ok {
		return ev
	}

	deltaType, _ := delta["type"].(string)

	switch deltaType {
	case "text_delta":
		ev.Type = driver.EventMessage
		if text, ok := delta["delta"].(string); ok {
			ev.Message = text
		}

	case "thinking_delta":
		ev.Type = driver.EventThinking
		if text, ok := delta["delta"].(string); ok {
			ev.Message = text
		}

	case "toolcall_start":
		ev.Type = driver.EventToolCall
		ev.ToolCall = &driver.ToolCall{
			Name: stringFieldRaw(delta, "name"),
		}

	case "toolcall_end":
		ev.Type = driver.EventToolCall
		tc := &driver.ToolCall{
			ID: stringFieldRaw(delta, "id"),
		}
		if name, _ := delta["name"].(string); name != "" {
			tc.Name = name
		}
		// Parse arguments from the full toolCall object.
		if tc, ok := delta["toolCall"].(map[string]any); ok {
			if args, ok := tc["arguments"].(map[string]any); ok {
				ev.ToolCall = &driver.ToolCall{
					ID:   stringFieldRaw(tc, "id"),
					Name: stringFieldRaw(tc, "name"),
					Args: args,
				}
			}
		}
		if ev.ToolCall == nil {
			ev.ToolCall = tc
		}

	case "done":
		// Message fully generated.
		ev.Type = driver.EventProgress
		reason, _ := delta["reason"].(string)
		ev.Message = fmt.Sprintf("message complete (reason: %s)", reason)

	case "error":
		ev.Type = driver.EventError
		if errMsg, _ := delta["reason"].(string); errMsg != "" {
			ev.Error = errMsg
		} else {
			ev.Error = "unknown streaming error"
		}
	}

	return ev
}

// --- JSON types for Pi's RPC protocol ---

type piCommand struct {
	ID      *int64 `json:"id,omitempty"`
	Type    string `json:"type"`
	Message string `json:"message,omitempty"`
	Level   string `json:"level,omitempty"`
}

type jsonMessage struct {
	ID      *int64         `json:"id,omitempty"`
	Type    string         `json:"type"`
	Success bool           `json:"success"`
	Command string         `json:"command,omitempty"`
	Error   string         `json:"error,omitempty"`
	Data    map[string]any `json:"data,omitempty"`
	Message map[string]any `json:"message,omitempty"`
}

type jsonResponse struct {
	ID      int64
	Success bool
	Data    map[string]any
}

// --- Helpers ---

// modeToThinkingLevel maps our Mode to Pi's thinking level.
func modeToThinkingLevel(mode driver.Mode) string {
	switch mode {
	case driver.ModeAgent:
		return "high"
	case driver.ModeAssistant:
		return "low"
	case driver.ModeReviewer:
		return "medium"
	case driver.ModeSecurity:
		return "high"
	default:
		return "medium"
	}
}

// extractAssistantContent extracts text content from a Pi AssistantMessage.
func extractAssistantContent(m map[string]any) string {
	content, ok := m["content"]
	if !ok {
		return ""
	}
	// content can be string or array of blocks.
	switch c := content.(type) {
	case string:
		return c
	case []any:
		var parts []string
		for _, block := range c {
			if b, ok := block.(map[string]any); ok {
				if t, ok := b["text"].(string); ok {
					parts = append(parts, t)
				}
			}
		}
		return strings.Join(parts, "\n")
	}
	return ""
}

// stringField extracts a string field from a jsonMessage.
func stringField(msg *jsonMessage, key string) string {
	if msg == nil || msg.Data == nil {
		return ""
	}
	v, _ := msg.Data[key].(string)
	return v
}

// intField extracts an int field from a jsonMessage (as float64 from JSON).
func intField(msg *jsonMessage, key string) int {
	if msg == nil || msg.Data == nil {
		return 0
	}
	v, _ := msg.Data[key].(float64)
	return int(v)
}

// stringFieldRaw extracts a string field from a raw map.
func stringFieldRaw(m map[string]any, key string) string {
	if m == nil {
		return ""
	}
	s, _ := m[key].(string)
	return s
}

// lenSlice returns the length of the underlying slice, or 0.
func lenSlice(v any) int {
	if v == nil {
		return 0
	}
	if arr, ok := v.([]any); ok {
		return len(arr)
	}
	return 0
}

// piStderrLogger writes Pi's stderr output for debugging. Non-fatal.
type piStderrLogger struct {
	id string
}

func (l *piStderrLogger) Write(p []byte) (int, error) {
	fmt.Printf("[pi:%s stderr] %s", l.id, string(p))
	return len(p), nil
}

// Compile-time check.
var _ driver.Driver = (*Driver)(nil)
