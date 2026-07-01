package mock

import (
	"context"
	"testing"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

func TestMockDriver_EventsAndTokens(t *testing.T) {
	t.Parallel()

	d := New(Options{
		ID:       "mock-test-001",
		TaskID:   "T-001",
		Interval: 10 * time.Millisecond,
		Seed:     42,
	})
	defer d.Stop(context.Background())

	if err := d.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Collect at least 3 events with a timeout.
	collected := make([]driver.Event, 0, 3)
	timeout := time.After(2 * time.Second)
	for len(collected) < 3 {
		select {
		case ev, ok := <-d.Events():
			if !ok {
				t.Fatal("events channel closed prematurely")
			}
			collected = append(collected, ev)
		case <-timeout:
			t.Fatalf("timed out waiting for events, got %d", len(collected))
		}
	}

	if collected[0].SessionID != "mock-test-001" {
		t.Errorf("event SessionID = %q, want mock-test-001", collected[0].SessionID)
	}

	// After 3 events, tokens should be > 0.
	state, err := d.Snapshot(context.Background())
	if err != nil {
		t.Fatalf("Snapshot: %v", err)
	}
	if state.TokensUsed <= 0 {
		t.Errorf("TokensUsed = %d, want > 0 after 3 events", state.TokensUsed)
	}
	if state.Status != driver.StatusRunning {
		t.Errorf("Status = %q, want running", state.Status)
	}
	if state.CurrentTask != "T-001" {
		t.Errorf("CurrentTask = %q, want T-001", state.CurrentTask)
	}
}

func TestMockDriver_PauseResume(t *testing.T) {
	t.Parallel()

	d := New(Options{
		ID:       "mock-pause-001",
		Interval: 10 * time.Millisecond,
		Seed:     99,
	})
	defer d.Stop(context.Background())

	if err := d.Start(context.Background()); err != nil {
		t.Fatal(err)
	}

	// Wait for at least one event.
	select {
	case <-d.Events():
	case <-time.After(time.Second):
		t.Fatal("no event before pause")
	}

	// Pause: no events should arrive.
	if err := d.Pause(context.Background()); err != nil {
		t.Fatal(err)
	}
	select {
	case ev := <-d.Events():
		t.Fatalf("received event while paused: %+v", ev)
	case <-time.After(50 * time.Millisecond):
		// good — no events during pause
	}

	state, _ := d.Snapshot(context.Background())
	if state.Status != driver.StatusPaused {
		t.Errorf("Status = %q, want paused", state.Status)
	}

	// Resume: events should flow again.
	if err := d.Resume(context.Background()); err != nil {
		t.Fatal(err)
	}
	select {
	case <-d.Events():
		// good — events resumed
	case <-time.After(time.Second):
		t.Fatal("no event after resume")
	}

	state, _ = d.Snapshot(context.Background())
	if state.Status != driver.StatusRunning {
		t.Errorf("Status = %q, want running", state.Status)
	}
}

func TestMockDriver_StopClosesChannel(t *testing.T) {
	t.Parallel()

	d := New(Options{
		ID:       "mock-stop-001",
		Interval: 10 * time.Millisecond,
		Seed:     7,
	})

	if err := d.Start(context.Background()); err != nil {
		t.Fatal(err)
	}

	if err := d.Stop(context.Background()); err != nil {
		t.Fatal(err)
	}

	// Channel should be closed.
	ev, ok := <-d.Events()
	if ok {
		t.Fatalf("expected channel closed, got event: %+v", ev)
	}

	// Stop is idempotent.
	if err := d.Stop(context.Background()); err != nil {
		t.Errorf("second Stop: %v", err)
	}
}

func TestMockDriver_SendProducesEvent(t *testing.T) {
	t.Parallel()

	d := New(Options{
		ID:       "mock-send-001",
		Interval: 50 * time.Millisecond,
		Seed:     1,
	})
	defer d.Stop(context.Background())

	if err := d.Start(context.Background()); err != nil {
		t.Fatal(err)
	}

	if err := d.Send(context.Background(), driver.Message{
		Role:    "user",
		Content: "take over",
	}); err != nil {
		t.Fatal(err)
	}

	// The Send event should arrive quickly.
	found := false
	timeout := time.After(500 * time.Millisecond)
	for !found {
		select {
		case ev := <-d.Events():
			if ev.Type == driver.EventMessage && ev.Message == "[user] take over" {
				found = true
			}
		case <-timeout:
			t.Fatal("Send event not received within timeout")
		}
	}
}

func TestMockDriver_DoubleStart(t *testing.T) {
	t.Parallel()

	d := New(Options{ID: "mock-dbl-001", Interval: 10 * time.Millisecond})
	defer d.Stop(context.Background())

	if err := d.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := d.Start(context.Background()); err == nil {
		t.Fatal("expected error from double Start")
	}
}

func TestMockDriver_AbortIsStop(t *testing.T) {
	t.Parallel()

	d := New(Options{ID: "mock-abort-001", Interval: 10 * time.Millisecond})

	if err := d.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := d.Abort(context.Background()); err != nil {
		t.Fatal(err)
	}

	ev, ok := <-d.Events()
	if ok {
		t.Fatalf("expected channel closed after abort, got: %+v", ev)
	}
}
