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

	mu       sync.Mutex
	state    driver.State
	outCh    chan driver.Event
	startOnce sync.Once
}

func newLiveDriver(ls *live.Session) *liveDriver {
	return &liveDriver{
		sessionID:   ls.SessionID,
		liveSession: ls,
		state: driver.State{
			Status:      driver.StatusRunning,
			CurrentTask: "",
			LastAction:  "connecting...",
		},
	}
}

func (d *liveDriver) ID() string { return d.sessionID }

// Events opens a connection to the session's event socket (once) and
// returns a channel that receives forwarded events. The adapter tracks
// state from the same stream.
func (d *liveDriver) Events() <-chan driver.Event {
	d.startOnce.Do(func() {
		events, err := d.liveSession.Events()
		if err != nil {
			d.outCh = make(chan driver.Event) // empty, never written
			return
		}
		d.outCh = make(chan driver.Event, 64)
		go func() {
			defer close(d.outCh)
			for ev := range events {
				d.trackState(ev)
				select {
				case d.outCh <- ev:
				default:
					// drop if TUI isn't reading fast enough
				}
			}
			// Socket closed — session ended.
			d.mu.Lock()
			d.state.Status = driver.StatusStopped
			d.mu.Unlock()
		}()
	})
	return d.outCh
}

// trackState updates the locally-cached state from an event.
func (d *liveDriver) trackState(ev driver.Event) {
	d.mu.Lock()
	defer d.mu.Unlock()
	// Estimate tokens: ~70 per event (average script step cost).
	d.state.TokensUsed += 70
	d.state.CostUSD = float64(d.state.TokensUsed) * 0.00003
	d.state.Uptime = time.Since(time.Now().Add(-d.state.Uptime))
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
	return d.state, nil
}

func (d *liveDriver) Send(_ context.Context, _ driver.Message) error {
	// Not yet implemented: requires bidirectional command protocol.
	return nil
}

func (d *liveDriver) Pause(_ context.Context) error {
	// Not yet implemented: requires bidirectional command protocol.
	return nil
}

func (d *liveDriver) Resume(_ context.Context) error {
	// Not yet implemented: requires bidirectional command protocol.
	return nil
}

// Compile-time check.
var _ cockpit.Driver = (*liveDriver)(nil)
var _ cockpit.DriverRegistry = (*liveRegistry)(nil)
