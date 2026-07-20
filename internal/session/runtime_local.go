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
	"path/filepath"
	"sync"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/mode"
	"github.com/JamieDF/agentjam/internal/vcs"
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

	driver    driver.Driver
	worktrees []*vcs.Worktree // created if opts.UseWorktree
	mu        sync.Mutex
}

// NewLocalRuntime constructs a LocalRuntime.
func NewLocalRuntime(opts Options, r *Resolved) *LocalRuntime {
	return &LocalRuntime{opts: opts, r: r}
}

// Kind implements Runtime.
func (l *LocalRuntime) Kind() RuntimeKind { return RuntimeKindLocal }

// PrepareWorkspace for local mode resolves the project's WorkspaceRoot.
//
// When opts.UseWorktree is true, a git worktree is created on a per-session
// branch, isolating the agent's changes from the main working copy. This is
// the local-mode equivalent of what container sessions always do.
//
// When UseWorktree is false (default), the agent works directly in the
// project's WorkspaceRoot.
func (l *LocalRuntime) PrepareWorkspace(_ context.Context, r *Resolved) (string, error) {
	if r.Project == nil {
		// Interactive session with no project: nothing to prepare.
		return "", nil
	}
	wd := r.Project.WorkspaceRoot
	if wd == "" {
		return "", errs.Wrap(errs.ErrInvalid, "project %q has no workspace_root", r.Project.ID)
	}

	if !l.opts.UseWorktree {
		// Direct mode: ensure the dir exists and return it.
		if err := os.MkdirAll(wd, 0o755); err != nil {
			return "", errs.Wrap(err, "create workspace %q", wd)
		}
		return wd, nil
	}

	// Worktree mode: create a git worktree for isolation.
	g := vcs.New("")
	if !g.IsGitRepo(wd) {
		// Not a git repo — fall back to direct mode.
		if err := os.MkdirAll(wd, 0o755); err != nil {
			return "", errs.Wrap(err, "create workspace %q", wd)
		}
		return wd, nil
	}

	base := l.opts.WorktreeBase
	if base == "" {
		base = filepath.Join(os.Getenv("HOME"), ".agentjam", "worktrees")
	}
	wtDir := filepath.Join(base, string(r.Project.ID), l.opts.ID)
	branch := "agent-" + l.opts.ID

	wt, err := g.CreateWorktree(vcs.WorktreeSpec{
		RepoDir:     wd,
		Branch:      branch,
		WorktreeDir: wtDir,
	})
	if err != nil {
		return "", errs.Wrap(err, "create worktree for %q", wd)
	}
	l.worktrees = append(l.worktrees, wt)
	return wtDir, nil
}

// Start launches the driver via the driver registry.
// The driver kind is selected by opts.DriverKind.
func (l *LocalRuntime) Start(ctx context.Context, p *Prepared) error {
	l.mu.Lock()
	defer l.mu.Unlock()

	if l.driver != nil {
		return errs.Wrap(errs.ErrAlreadyExists, "runtime already started")
	}

	dir := p.WorkingDir
	if dir == "" {
		// No project — use current directory. Valid for mock drivers
		// and interactive sessions that don't need a workspace.
		dir = "."
	}

	// Resolve mode file for drivers that need a system prompt (Pi, opencode).
	modeFile, err := resolveModeFile(l.r.Mode)
	if err != nil {
		return fmt.Errorf("resolve mode file: %w", err)
	}

	kind := l.opts.DriverKind
	if kind == "" {
		kind = "pi"
	}

	d, err := driver.Default.Build(kind, driver.FactoryOptions{
		ID:       "session-" + l.opts.ID,
		Workdir:  dir,
		ModeFile: modeFile,
		TaskID:   l.opts.TaskID,
	})
	if err != nil {
		return err
	}

	if err := d.Start(ctx); err != nil {
		return errs.Wrap(err, "driver start")
	}
	if err := d.SetMode(ctx, l.r.Mode); err != nil {
		_ = d.Stop(ctx)
		return errs.Wrap(err, "set mode %q", l.r.Mode)
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

// Driver returns the underlying driver, or nil before Start.
func (l *LocalRuntime) Driver() driver.Driver {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.driver
}

// Cleanup stops the driver and removes any worktrees created in worktree
// mode.
func (l *LocalRuntime) Cleanup(ctx context.Context) {
	l.mu.Lock()
	d := l.driver
	worktrees := l.worktrees
	l.driver = nil
	l.worktrees = nil
	l.mu.Unlock()

	if d != nil {
		_ = d.Stop(ctx)
	}

	// Remove git worktrees and branches if any were created.
	if len(worktrees) > 0 {
		g := vcs.New("")
		for _, wt := range worktrees {
			_ = g.Cleanup(wt)
		}
	}
}

// opencodeBaseURLFromEnv returns OPENCODE_BASE_URL or "" for SDK default.
func opencodeBaseURLFromEnv() string {
	return os.Getenv("OPENCODE_BASE_URL")
}

// resolveModeFile loads the mode markdown for the given mode name and
// returns its on-disk path. Drivers that need a system prompt file
// (Pi, opencode) pass this path as --system-prompt or equivalent.
func resolveModeFile(modeName driver.Mode) (string, error) {
	if modeName == "" {
		return "", nil
	}

	// Look for modes in the bundled modes/ directory relative to the cwd,
	// then fall back to ~/.agentjam/modes/.
	loaderDir := filepath.Join("modes")
	if _, err := os.Stat(loaderDir); err != nil {
		home, err := os.UserHomeDir()
		if err == nil {
			loaderDir = filepath.Join(home, ".agentjam", "modes")
		}
	}

	loader, err := mode.NewLoader(loaderDir)
	if err != nil {
		return "", fmt.Errorf("create mode loader: %w", err)
	}
	m, err := loader.Load(string(modeName))
	if err != nil {
		return "", fmt.Errorf("load mode %q: %w", modeName, err)
	}
	return m.Path, nil
}
