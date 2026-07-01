// Package live provides discovery and IPC for session subprocesses.
//
// When a session is started with --detach, a child process (agentjam session
// run <id>) holds the driver alive and serves events on a unix socket.
// This package lets other CLI invocations discover those live sessions,
// connect to their event streams, and stop them.
//
// # File layout
//
// For each running session, the child writes:
//
//	~/.agentjam/sessions/<id>.yaml   — session record (by Manager)
//	~/.agentjam/sessions/<id>.pid    — child process PID
//	~/.agentjam/sessions/<id>.sock   — unix socket for event streaming
//	~/.agentjam/sessions/<id>.log    — child stdout/stderr
//
// The .pid and .sock files are removed by the child on clean exit.
// If the child crashes, stale files may remain; IsAlive() checks PID liveness.
package live

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

// Session represents a running session subprocess.
type Session struct {
	SessionID  string
	PID        int
	SocketPath string
	LogPath    string
	sessionsDir string
}

// List scans the sessions directory for live sessions: those with a valid
// PID file whose process is still alive. Stale PID files (process exited)
// are cleaned up.
func List(sessionsDir string) ([]*Session, error) {
	entries, err := os.ReadDir(sessionsDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("read sessions dir: %w", err)
	}

	var out []*Session
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".pid") {
			continue
		}
		id := strings.TrimSuffix(e.Name(), ".pid")
		ls, err := fromPIDFile(sessionsDir, id)
		if err != nil {
			continue
		}
		if !ls.IsAlive() {
			ls.cleanupStale()
			continue
		}
		out = append(out, ls)
	}
	return out, nil
}

// Get returns the live session for the given ID, or an error if it's not
// running.
func Get(sessionsDir, id string) (*Session, error) {
	pidPath := filepath.Join(sessionsDir, id+".pid")
	if _, err := os.Stat(pidPath); err != nil {
		return nil, fmt.Errorf("session %q is not running (no pid file)", id)
	}
	ls, err := fromPIDFile(sessionsDir, id)
	if err != nil {
		return nil, err
	}
	if !ls.IsAlive() {
		ls.cleanupStale()
		return nil, fmt.Errorf("session %q is not running (process exited)", id)
	}
	return ls, nil
}

// fromPIDFile reads the PID file and constructs a Session. Does not check
// liveness — caller should call IsAlive().
func fromPIDFile(sessionsDir, id string) (*Session, error) {
	pidPath := filepath.Join(sessionsDir, id+".pid")
	data, err := os.ReadFile(pidPath)
	if err != nil {
		return nil, err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return nil, fmt.Errorf("invalid pid file %q: %s", pidPath, data)
	}
	return &Session{
		SessionID:   id,
		PID:         pid,
		SocketPath:  filepath.Join(sessionsDir, id+".sock"),
		LogPath:     filepath.Join(sessionsDir, id+".log"),
		sessionsDir: sessionsDir,
	}, nil
}

// IsAlive checks whether the session's process is still running.
func (s *Session) IsAlive() bool {
	if s.PID <= 0 {
		return false
	}
	// Send signal 0 (existence check). On Unix, this returns nil if the
	// process exists, or an error if it doesn't.
	return syscall.Kill(s.PID, 0) == nil
}

// Events dials the session's event socket and returns a channel of events.
// The channel is closed when the socket disconnects (session stopped).
// The caller should also pass a context to allow cancellation.
func (s *Session) Events() (<-chan driver.Event, error) {
	conn, err := net.Dial("unix", s.SocketPath)
	if err != nil {
		return nil, fmt.Errorf("dial session socket: %w", err)
	}

	ch := make(chan driver.Event, 64)
	go func() {
		defer conn.Close()
		defer close(ch)
		dec := json.NewDecoder(conn)
		for {
			var msg struct {
				Type  string        `json:"type"`
				Event *driver.Event `json:"event"`
				State *driver.State `json:"state"`
			}
			if err := dec.Decode(&msg); err != nil {
				if err != io.EOF {
					// Non-EOF errors indicate protocol corruption or
					// a crash mid-write. Log to stderr for debugging.
					fmt.Fprintf(os.Stderr, "live: event stream error for %s: %v\n",
						s.SessionID, err)
				}
				return
			}
			if msg.Type == "event" && msg.Event != nil {
				ch <- *msg.Event
			}
		}
	}()
	return ch, nil
}

// Stop sends SIGTERM to the session's process and waits up to 10 seconds
// for it to exit. If it doesn't exit, sends SIGKILL.
func (s *Session) Stop() error {
	if !s.IsAlive() {
		s.cleanupStale()
		return nil
	}

	// Send SIGTERM for graceful shutdown.
	if err := syscall.Kill(s.PID, syscall.SIGTERM); err != nil {
		return fmt.Errorf("send SIGTERM to pid %d: %w", s.PID, err)
	}

	// Wait up to 10 seconds for exit.
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if !s.IsAlive() {
			s.cleanupStale()
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Force kill.
	_ = syscall.Kill(s.PID, syscall.SIGKILL)
	time.Sleep(200 * time.Millisecond)
	s.cleanupStale()
	return nil
}

// cleanupStale removes stale PID and socket files for this session.
func (s *Session) cleanupStale() {
	_ = os.Remove(filepath.Join(s.sessionsDir, s.SessionID+".pid"))
	_ = os.Remove(filepath.Join(s.sessionsDir, s.SessionID+".sock"))
}
