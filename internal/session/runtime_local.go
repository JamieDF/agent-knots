// Package session — runtime_local.go implements RuntimeKindLocal.
//
// The local runtime runs the agent directly on the host. No isolation; no
// container; the agent's filesystem ops touch the real workspaceRoot. Use
// this for fast iterations or when the user explicitly opts out of
// container mode. Recommended for trusted tasks and local sandbox
// directories.
package session

import (
	"context"
	"fmt"
	"os"
	"sync"

	"github.com/harness/harness/internal/agent/driver"
	"github.com/harness/harness/internal/agent/driver/opencode"
	"github.com/harness/harness/internal/errs"
)

// LocalRuntime is the host-mode implementation of Runtime.
//
// It starts the OpenCode driver pointed at the project's directory. The
// "workspace" is the project's WorkspaceRoot — no worktree, no copy.
// Cleanup is a no-op for the local runtime; resources are released by
// closing the driver.
type LocalRuntime struct {
	opts Options
	r    *Resolved

	driver driver.Driver
	mu     sync.Mutex
}

// NewLocalRuntime constructs a LocalRuntime.
func NewLocalRuntime(opts Options, r *Resolved) *LocalRuntime {
	return &LocalRuntime{opts: opts, r: r}
}

// Kind implements Runtime.
func (l *LocalRuntime) Kind() RuntimeKind { return RuntimeKindLocal }

// PrepareWorkspace for local mode just resolves the project's
// WorkspaceRoot and ensures it exists.
func (l *LocalRuntime) PrepareWorkspace(_ context.Context, r *Resolved) (string, error) {
	if r.Project == nil {
		// Interactive session with no project: nothing to prepare.
		return "", nil
	}
	wd := r.Project.WorkspaceRoot
	if wd == "" {
		return "", errs.Wrap(errs.ErrInvalid, "project %q has no workspace_root", r.Project.ID)
	}
	if err := os.MkdirAll(wd, 0o755); err != nil {
		return "", errs.Wrap(err, "create workspace %q", wd)
	}
	return wd, nil
}

// Start launches OpenCode pointing at the working dir.
func (l *LocalRuntime) Start(ctx context.Context, p *Prepared) error {
	l.mu.Lock()
	defer l.mu.Unlock()

	if l.driver != nil {
		return errs.Wrap(errs.ErrAlreadyExists, "runtime already started")
	}

	dir := p.WorkingDir
	if dir == "" {
		return errs.Wrap(errs.ErrInvalid, "local runtime: empty working dir")
	}

	d, err := opencode.New(opencode.Options{
		Directory: dir,
		Title:     fmt.Sprintf("harness-session-%s", l.opts.ID),
		ID:        "session-" + l.opts.ID,
		BaseURL:   opencodeBaseURLFromEnv(),
	})
	if err != nil {
		return err
	}
	if err := d.Start(ctx); err != nil {
		return errs.Wrap(err, "opencode start")
	}
	if err := d.SetMode(ctx, l.r.Mode); err != nil {
		_ = d.Stop(ctx)
		return errs.Wrap(err, "opencode set mode %q", l.r.Mode)
	}

	l.driver = d
	return nil
}

// Send forwards the message to the running driver.
func (l *LocalRuntime) Send(ctx context.Context, msg driver.Message) error {
	l.mu.Lock()
	d := l.driver
	l.mu.Unlock()
	if d == nil {
		return errs.Wrap(errs.ErrUnavailable, "local runtime: not started")
	}
	return d.Send(ctx, msg)
}

// DriverID returns the running driver's ID.
func (l *LocalRuntime) DriverID() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.driver == nil {
		return ""
	}
	return l.driver.ID()
}

// Cleanup stops the driver.
func (l *LocalRuntime) Cleanup(ctx context.Context) {
	l.mu.Lock()
	d := l.driver
	l.driver = nil
	l.mu.Unlock()
	if d != nil {
		_ = d.Stop(ctx)
	}
}

// opencodeBaseURLFromEnv returns OPENCODE_BASE_URL or "" for SDK default.
func opencodeBaseURLFromEnv() string {
	if v := os.Getenv("OPENCODE_BASE_URL"); v != "" {
		return v
	}
	return ""
}
