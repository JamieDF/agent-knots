// Package opencode implements driver.Driver via the OpenCode Go SDK.
//
// OpenCode (https://opencode.ai) is the v1 default agent backend. This
// driver embeds the OpenCode Go SDK (github.com/sst/opencode-sdk-go) so the
// orchestrator can talk to OpenCode without subprocess overhead.
//
// # Architecture
//
// The driver connects to a running OpenCode server. All LLM/tool interactions
// happen through that server's REST API. Events stream over
// EventService.ListStreaming.
//
// # Lifecycle
//
//  1. New(opts) — construct the driver.
//  2. Start(ctx) — establish server connection; create a session.
//  3. Send / Events / Snapshot — drive the session.
//  4. Stop(ctx) — close the session.
//
// # Mode Swap
//
// OpenCode supports "build" and "plan" agents. We map:
//
//   - driver.ModeAgent    -> "build"
//   - driver.ModeAssistant -> "build" (with system prompt overrides)
//   - driver.ModeReviewer  -> "plan"
//
// Custom system prompts are passed via SessionPromptParams.System.
package opencode

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	opencode "github.com/sst/opencode-sdk-go"
	"github.com/sst/opencode-sdk-go/option"

	"github.com/harness/harness/internal/agent/driver"
	"github.com/harness/harness/internal/errs"
)

// Driver is an OpenCode-backed agent driver.
type Driver struct {
	client *opencode.Client
	id     string

	mu     sync.RWMutex
	dir    string
	title  string
	sessID string
	mode   driver.Mode

	events chan driver.Event

	startedAt time.Time
	closed    atomic.Bool
}

// Options configure a new Driver.
type Options struct {
	// BaseURL is the OpenCode server URL. Empty = use OPENCODE_BASE_URL env
	// var or SDK default.
	BaseURL string

	// Directory is the working directory OpenCode operates in (typically a
	// git repo root).
	Directory string

	// Title is the session title (for OpenCode's session list UI).
	Title string

	// ID is the driver instance identifier. If empty, one is generated.
	ID string
}

// New constructs a Driver. Call Start to establish the session.
func New(opts Options) (*Driver, error) {
	if opts.Directory == "" {
		return nil, errs.Wrap(errs.ErrInvalid, "directory is required")
	}

	var sdkOpts []option.RequestOption
	if opts.BaseURL != "" {
		sdkOpts = append(sdkOpts, option.WithBaseURL(opts.BaseURL))
	}

	id := opts.ID
	if id == "" {
		id = fmt.Sprintf("oc-%d", time.Now().UnixNano())
	}

	return &Driver{
		client: opencode.NewClient(sdkOpts...),
		id:     id,
		dir:    opts.Directory,
		title:  opts.Title,
		mode:   driver.ModeAgent,
		events: make(chan driver.Event, 64),
	}, nil
}

// ID implements driver.Driver.
func (d *Driver) ID() string { return d.id }

// Start implements driver.Driver. Creates a new OpenCode session.
func (d *Driver) Start(ctx context.Context) error {
	if d.closed.Load() {
		return driver.ErrClosed
	}

	params := opencode.SessionNewParams{
		Directory: opencode.F(d.dir),
	}
	if d.title != "" {
		params.Title = opencode.F(d.title)
	}

	sess, err := d.client.Session.New(ctx, params)
	if err != nil {
		return errs.Wrap(err, "opencode: create session")
	}

	d.mu.Lock()
	d.sessID = sess.ID
	d.startedAt = time.Now()
	d.mu.Unlock()

	// Start background event forwarder.
	go d.forwardEvents(ctx)

	return nil
}

// Stop implements driver.Driver.
func (d *Driver) Stop(ctx context.Context) error {
	if d.closed.Swap(true) {
		return nil
	}

	d.mu.RLock()
	sessID := d.sessID
	d.mu.RUnlock()

	if sessID != "" {
		// Best-effort cleanup.
		_, _ = d.client.Session.Delete(ctx, sessID, opencode.SessionDeleteParams{})
	}

	close(d.events)
	return nil
}

// Send implements driver.Driver. Sends a user message to the agent.
func (d *Driver) Send(ctx context.Context, msg driver.Message) error {
	if d.closed.Load() {
		return driver.ErrClosed
	}
	if msg.Role != "user" {
		return errs.Wrap(errs.ErrInvalid, "only user messages can be sent; got %q", msg.Role)
	}

	d.mu.RLock()
	sessID := d.sessID
	d.mu.RUnlock()

	if sessID == "" {
		return errs.Wrap(errs.ErrUnavailable, "session not started")
	}

	parts := []opencode.SessionPromptParamsPartUnion{
		opencode.TextPartInputParam{
			Type: opencode.F(opencode.TextPartInputTypeText),
			Text: opencode.F(msg.Content),
		},
	}

	_, err := d.client.Session.Prompt(ctx, sessID, opencode.SessionPromptParams{
		Parts: opencode.F(parts),
	})
	if err != nil {
		return errs.Wrap(err, "opencode: send prompt")
	}
	return nil
}

// Events implements driver.Driver.
func (d *Driver) Events() <-chan driver.Event {
	return d.events
}

// Snapshot implements driver.Driver.
func (d *Driver) Snapshot(_ context.Context) (driver.State, error) {
	if d.closed.Load() {
		return driver.State{}, driver.ErrClosed
	}

	d.mu.RLock()
	sessID := d.sessID
	mode := d.mode
	started := d.startedAt
	d.mu.RUnlock()

	state := driver.State{
		Status:    driver.StatusRunning,
		Uptime:    time.Since(started),
	}
	if sessID != "" {
		state.CurrentTask = sessID
	}
	state.LastAction = fmt.Sprintf("mode=%s", mode)
	return state, nil
}

// SetMode implements driver.Driver. Updates the mode and prepares to apply
// it on the next prompt via the System field.
func (d *Driver) SetMode(_ context.Context, mode driver.Mode) error {
	d.mu.Lock()
	d.mode = mode
	d.mu.Unlock()
	return nil
}

// Pause implements driver.Driver.
func (d *Driver) Pause(ctx context.Context) error {
	if d.closed.Load() {
		return driver.ErrClosed
	}
	d.mu.RLock()
	sessID := d.sessID
	d.mu.RUnlock()
	if sessID == "" {
		return errs.Wrap(errs.ErrUnavailable, "session not started")
	}
	_, err := d.client.Session.Abort(ctx, sessID, opencode.SessionAbortParams{})
	if err != nil {
		return errs.Wrap(err, "opencode: pause (abort)")
	}
	return nil
}

// Resume implements driver.Driver. OpenCode resumes on next prompt.
func (d *Driver) Resume(_ context.Context) error { return nil }

// Abort implements driver.Driver.
func (d *Driver) Abort(ctx context.Context) error {
	return d.Stop(ctx)
}

// forwardEvents streams events from OpenCode and translates them into driver
// events. The OpenCode SDK's EventService.ListStreaming returns a stream.
func (d *Driver) forwardEvents(ctx context.Context) {
	stream := d.client.Event.ListStreaming(ctx, opencode.EventListParams{})
	defer stream.Close()

	for stream.Next() {
		ev := stream.Current()
		d.emit(translateEvent(d.id, ev))
	}
	if err := stream.Err(); err != nil && !errors.Is(err, context.Canceled) {
		d.emit(driver.Event{
			Type:      driver.EventError,
			SessionID: d.id,
			Timestamp: time.Now(),
			Error:     err.Error(),
		})
	}
}

// emit pushes an event to the channel. Returns false if the driver is closed.
func (d *Driver) emit(ev driver.Event) bool {
	if d.closed.Load() {
		return false
	}
	select {
	case d.events <- ev:
		return true
	default:
		return false
	}
}

// translateEvent converts an OpenCode event into a driver.Event.
//
// OpenCode events are JSON discriminated unions keyed by "type" — e.g.
// "session.idle", "message.updated", "permission.updated". We preserve
// the OpenCode type as our driver.EventType so consumers can match on the
// full string.
func translateEvent(sessionID string, raw opencode.EventListResponse) driver.Event {
	ev := driver.Event{
		SessionID: sessionID,
		Timestamp: time.Now(),
	}

	// Marshal and re-parse to extract the type discriminator.
	data, err := json.Marshal(raw)
	if err != nil {
		ev.Type = driver.EventError
		ev.Error = "marshal: " + err.Error()
		return ev
	}

	var probe struct {
		Type string          `json:"type"`
		Data json.RawMessage `json:"-"`
	}
	if err := json.Unmarshal(data, &probe); err != nil {
		ev.Type = driver.EventError
		ev.Error = "parse: " + err.Error()
		return ev
	}
	if probe.Type == "" {
		ev.Type = driver.EventError
		ev.Error = "event missing type"
		return ev
	}

	ev.Type = driver.EventType(probe.Type)
	ev.Data = data
	return ev
}

// Compile-time check.
var _ driver.Driver = (*Driver)(nil)