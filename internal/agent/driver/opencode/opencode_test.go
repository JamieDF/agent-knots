package opencode

import (
	"context"
	"testing"

	opencode "github.com/sst/opencode-sdk-go"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/errs"
)

func TestNew(t *testing.T) {
	d, err := New(Options{Directory: "/tmp"})
	if err != nil {
		t.Fatal(err)
	}
	if d == nil {
		t.Fatal("nil driver")
	}
	if d.ID() == "" {
		t.Error("empty ID")
	}
}

func TestNew_RequiresDirectory(t *testing.T) {
	_, err := New(Options{})
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestNew_CustomID(t *testing.T) {
	d, _ := New(Options{Directory: "/tmp", ID: "test-id"})
	if d.ID() != "test-id" {
		t.Errorf("ID = %q", d.ID())
	}
}

func TestEventsChannel(t *testing.T) {
	d, _ := New(Options{Directory: "/tmp"})
	ch := d.Events()
	if ch == nil {
		t.Fatal("nil channel")
	}
}

func TestSend_NotStarted(t *testing.T) {
	d, _ := New(Options{Directory: "/tmp"})
	err := d.Send(context.Background(), driver.Message{Role: "user", Content: "hi"})
	if !errs.Is(err, errs.ErrUnavailable) {
		t.Errorf("expected ErrUnavailable, got %v", err)
	}
}

func TestSend_NotUserRole(t *testing.T) {
	d, _ := New(Options{Directory: "/tmp"})
	ctx := context.Background()
	// Bypass Start by manually setting sessID (test-only).
	d.mu.Lock()
	d.sessID = "fake"
	d.mu.Unlock()

	err := d.Send(ctx, driver.Message{Role: "assistant", Content: "hi"})
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestSetMode(t *testing.T) {
	d, _ := New(Options{Directory: "/tmp"})
	if err := d.SetMode(context.Background(), driver.ModeAgent); err != nil {
		t.Fatal(err)
	}
	if d.mode != driver.ModeAgent {
		t.Errorf("mode = %q", d.mode)
	}
}

func TestSnapshot_AfterClose(t *testing.T) {
	d, _ := New(Options{Directory: "/tmp"})
	_ = d.Stop(context.Background())
	_, err := d.Snapshot(context.Background())
	if !driver.IsClosed(err) {
		t.Errorf("expected ErrClosed, got %v", err)
	}
}

func TestSend_AfterClose(t *testing.T) {
	d, _ := New(Options{Directory: "/tmp"})
	d.mu.Lock()
	d.sessID = "fake"
	d.mu.Unlock()
	_ = d.Stop(context.Background())
	err := d.Send(context.Background(), driver.Message{Role: "user", Content: "hi"})
	if !driver.IsClosed(err) {
		t.Errorf("expected ErrClosed, got %v", err)
	}
}

func TestTranslateEvent(t *testing.T) {
	// Real event translation requires server-generated payloads which we
	// can't easily mock. We verify SessionID propagation only.
	ev := translateEvent("test", opencode.EventListResponse{})
	if ev.SessionID != "test" {
		t.Errorf("SessionID = %q", ev.SessionID)
	}
}