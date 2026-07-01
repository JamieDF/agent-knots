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

// Control opens a control connection to the session subprocess. Control
// connections can send commands (set-mode, send) to the running agent.
// The connection is full-duplex: the caller writes control messages and
// reads responses. Event streaming uses a separate connection (see Events).
func (s *Session) Control() (*Control, error) {
	conn, err := net.Dial("unix", s.SocketPath)
	if err != nil {
		return nil, fmt.Errorf("dial session socket: %w", err)
	}
	return &Control{conn: conn}, nil
}

// Control is a client-side handle for sending commands to a running
// session subprocess via the event socket.
type Control struct {
	conn net.Conn
}

// SetMode sends a mode-swap command (e.g. "assistant" to assume control,
// "agent" to relinquish). Returns nil on success.
func (c *Control) SetMode(mode string) error {
	return c.send(map[string]string{
		"type":   "control",
		"action": "set-mode",
		"mode":   mode,
	})
}

// Send delivers a message to the agent as if typed by the user.
func (c *Control) Send(content string) error {
	return c.send(map[string]string{
		"type":    "control",
		"action":  "send",
		"content": content,
		"role":    "user",
	})
}

// Close releases the control connection.
func (c *Control) Close() error {
	return c.conn.Close()
}

// send writes a control message and waits for the response.
func (c *Control) send(msg any) error {
	data, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal control message: %w", err)
	}
	data = append(data, '\n')
	if _, err := c.conn.Write(data); err != nil {
		return fmt.Errorf("write control message: %w", err)
	}
	// Read the response.
	dec := json.NewDecoder(c.conn)
	var resp struct {
		Type  string `json:"type"`
		OK    bool   `json:"ok"`
		Error string `json:"error,omitempty"`
	}
	if err := dec.Decode(&resp); err != nil {
		return fmt.Errorf("read control response: %w", err)
	}
	if !resp.OK {
		return fmt.Errorf("control error: %s", resp.Error)
	}
	return nil
}
