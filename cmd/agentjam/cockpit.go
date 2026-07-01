package main

import (
	"context"
	"fmt"
	"os"
	"sync"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/spf13/cobra"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/config"
	cockpit "github.com/JamieDF/agentjam/internal/cockpit/tui"
	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/session/live"
)

func cockpitCmd() *cobra.Command {
	var (
		web bool
	)

	cmd := &cobra.Command{
		Use:   "cockpit",
		Short: "Launch the concurrent agent cockpit",
		Long: `Launch the cockpit — the canonical management surface for agentjam.

By default, launches the keyboard-driven TUI cockpit. Use --web to launch
the web GUI (when implemented).

The cockpit discovers running sessions (started with --detach) and displays
them in real time. Use 'agentjam session start --driver mock --detach' to
start a test session, then launch the cockpit.

Keybindings (TUI):
  ↑/↓ or j/k   navigate agents
  Enter or f   focus on selected agent
  Esc or b     zoom back to agent list
  p            pause selected agent
  r            resume selected agent
  a            assume control
  q            quit`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if web {
				fmt.Fprintln(cmd.OutOrStdout(),
					"Web GUI is planned but not yet implemented. Run without --web for the TUI cockpit.")
				return nil
			}

			registry := &liveRegistry{
				sessionsDir: config.SessionsPath(),
			}

			model := cockpit.NewModel(registry)
			program := tea.NewProgram(model, tea.WithAltScreen())

			// Handle Ctrl-C in the terminal.
			ctx, cancel := context.WithCancel(cmd.Context())
			defer cancel()
			go func() {
				<-ctx.Done()
				program.Quit()
			}()

			if _, err := program.Run(); err != nil {
				fmt.Fprintf(os.Stderr, "cockpit: %v\n", err)
				return err
			}
			return nil
		},
	}

	cmd.Flags().BoolVar(&web, "web", false, "Use web GUI (planned, not yet implemented)")
	return cmd
}

// liveRegistry implements cockpit.DriverRegistry by discovering running
// session subprocesses via the live package.
type liveRegistry struct {
	sessionsDir string
}

func (r *liveRegistry) List() []cockpit.Driver {
	sessions, err := live.List(r.sessionsDir)
	if err != nil {
		return nil
	}
	var drivers []cockpit.Driver
	for _, ls := range sessions {
		drivers = append(drivers, newLiveDriver(ls))
	}
	return drivers
}

func (r *liveRegistry) Get(id string) (cockpit.Driver, bool) {
	ls, err := live.Get(r.sessionsDir, id)
	if err != nil {
		return nil, false
	}
	return newLiveDriver(ls), true
}

// liveDriver adapts a live.Session to the cockpit.Driver interface.
// It connects to the session's event socket, tracks state from events,
// and forwards them to the TUI.
type liveDriver struct {
	sessionID   string
	liveSession *live.Session
	startedAt   time.Time

	mu    sync.Mutex
	state driver.State
	outCh chan driver.Event // nil until Events() is first called
}

func newLiveDriver(ls *live.Session) *liveDriver {
	return &liveDriver{
		sessionID:   ls.SessionID,
		liveSession: ls,
		startedAt:   time.Now(),
		state: driver.State{
			Status:     driver.StatusRunning,
			LastAction: "connecting...",
		},
	}
}

func (d *liveDriver) ID() string { return d.sessionID }

// Events opens a connection to the session's event socket and returns
// a channel that receives forwarded events. If the connection fails,
// returns a closed channel so the caller stops retrying this instance
// (a fresh liveDriver is created on the next registry.List() call).
func (d *liveDriver) Events() <-chan driver.Event {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.outCh != nil {
		return d.outCh // already connected (or failed)
	}

	events, err := d.liveSession.Events()
	if err != nil {
		// Connection failed — return a closed channel so watchEvents
		// gets ok=false and stops. A fresh driver from the next tick
		// will retry.
		ch := make(chan driver.Event)
		close(ch)
		d.outCh = ch
		return ch
	}

	d.outCh = make(chan driver.Event, 64)
	go func(outCh chan driver.Event) {
		defer close(outCh)
		for ev := range events {
			d.trackState(ev)
			select {
			case outCh <- ev:
			default:
				// drop if TUI isn't reading fast enough
			}
		}
		// Socket closed — session ended.
		d.mu.Lock()
		d.state.Status = driver.StatusStopped
		d.mu.Unlock()
	}(d.outCh)
	return d.outCh
}

// trackState updates the locally-cached state from an event.
func (d *liveDriver) trackState(ev driver.Event) {
	d.mu.Lock()
	defer d.mu.Unlock()
	// Estimate tokens: ~70 per event (average script step cost).
	// Real token counts require a bidirectional snapshot protocol.
	d.state.TokensUsed += 70
	d.state.CostUSD = float64(d.state.TokensUsed) * 0.00003
	d.state.Uptime = time.Since(d.startedAt)
	if ev.ToolCall != nil {
		d.state.LastAction = ev.ToolCall.Name
	} else if ev.Message != "" {
		action := ev.Message
		if len(action) > 40 {
			action = action[:37] + "..."
		}
		d.state.LastAction = action
	}
}

func (d *liveDriver) Snapshot(_ context.Context) (driver.State, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	// Update uptime on every snapshot so it stays current between events.
	d.state.Uptime = time.Since(d.startedAt)
	return d.state, nil
}

func (d *liveDriver) Send(_ context.Context, msg driver.Message) error {
	ctrl, err := d.liveSession.Control()
	if err != nil {
		return errs.Wrap(err, "connect to session for Send")
	}
	defer ctrl.Close()
	return ctrl.Send(msg.Content)
}

func (d *liveDriver) SetMode(_ context.Context, mode driver.Mode) error {
	ctrl, err := d.liveSession.Control()
	if err != nil {
		return errs.Wrap(err, "connect to session for SetMode")
	}
	defer ctrl.Close()
	return ctrl.SetMode(string(mode))
}

func (d *liveDriver) Pause(_ context.Context) error {
	return errs.Wrap(errs.ErrUnsupported, "liveDriver.Pause not implemented")
}

func (d *liveDriver) Resume(_ context.Context) error {
	return errs.Wrap(errs.ErrUnsupported, "liveDriver.Resume not implemented")
}

// Compile-time checks.
var _ cockpit.Driver = (*liveDriver)(nil)
var _ cockpit.DriverRegistry = (*liveRegistry)(nil)
