// Package session — init.go implements the session initialization flow.
//
// A session is a single running agent driver plus its bookkeeping. Init()
// walks six phases:
//
//  1. Resolve — figure out task, project, working dir, mode, vault state.
//  2. Decide — pick the runtime (local vs container, per --container flag).
//  3. Prepare — build the workspace: worktree, mounts, environment.
//  4. Start — actually run the driver (and container, if any).
//  5. Register — persist the session record and update task assignment.
//  6. Prompt — send the initial user message to the agent.
//
// If a phase fails, Init() returns the phase's error. The runtime's
// Cleanup method is invoked to roll back resources created in earlier
// phases (e.g. a partially-created worktree is removed if the driver fails
// to start).
package session

import (
	"context"
	"fmt"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/container"
	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/project"
	"github.com/JamieDF/agentjam/internal/task"
)

// VaultChecker is the subset of the vault interface Init() needs.
// Keeping it narrow lets callers pass nil when the session doesn't touch
// credentials, and lets tests use a stub.
type VaultChecker interface {
	IsUnlocked(ctx context.Context) (bool, error)
}

// Options is the input to Init. TaskID, ProjectID, Mode are all optional.
// ID is required unless GenerateID is true.
type Options struct {
	// ID is the session's unique identifier. If empty and GenerateID is
	// false, returns errs.ErrInvalid.
	ID string

	// GenerateID, when true and ID is empty, generates an ID from the
	// current timestamp + a random suffix.
	GenerateID bool

	// TaskID is the task to assign. Empty = no task (just chat).
	TaskID string

	// ProjectID is the project for this session. Required when Container
	// is true and TaskID is empty. Inferred from TaskID when only TaskID
	// is set.
	ProjectID string

	// Mode is the agent's persona. Empty = project default or "agent".
	Mode driver.Mode

	// Container requests a containerized session.
	Container bool

	// ContainerImage overrides the project's container.image. Empty = use
	// the auto-detected image.
	ContainerImage string

	// ContainerProfile, when non-nil and Content != nil, overrides the
	// default isolation profile. Only set by --privileged-debug.
	ContainerProfile *container.IsolationProfile

	// PrivilegedDebug opts out of isolation hardening for debugging. The
	// CLI requires an explicit confirmation prompt.
	PrivilegedDebug bool

	// Vault is the credential vault. May be nil for tasks that don't
	// require credentials.
	Vault VaultChecker

	// ProjectStore is the project persistence backend. May be nil.
	ProjectStore project.Store

	// TaskStore is the task persistence backend. May be nil.
	TaskStore task.Store

	// WorktreeBase is the directory under which per-session worktrees
	// are created. Default: $HARNESS_HOME/worktrees.
	WorktreeBase string

	// VaultSocketPath is the path to the vault daemon's unix socket (only
	// relevant for container sessions). Empty = no vault socket mount.
	VaultSocketPath string
}

// Init starts a new agent session. The returned *Session has its Driver
// field populated (callers can stream events from Driver.Events()).
//
// On error, the returned *Session may still contain useful diagnostic
// state (e.g. the resolved working dir). The runtime's Cleanup method has
// already been invoked to release any partial state.
//
// The *Manager argument is required; it owns persistence of the session
// record. Build it once at startup with session.New(dir) and reuse.
func Init(ctx context.Context, mgr *Manager, opts Options) (*Session, error) {
	if mgr == nil {
		return nil, errs.Wrap(errs.ErrInvalid, "session: manager is required")
	}
	if err := opts.validate(); err != nil {
		return nil, err
	}
	if opts.ID == "" && opts.GenerateID {
		opts.ID = newSessionID()
	}
	if opts.ID == "" {
		return nil, errs.Wrap(errs.ErrInvalid, "session ID is required (set Options.ID or Options.GenerateID)")
	}

	s := &Session{
		ID:        opts.ID,
		Mode:      opts.Mode,
		Status:    StatusStarting,
		StartedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}

	// Phase 1: Resolve task / project / mode / dir.
	resolved, err := phase1Resolve(ctx, opts)
	if err != nil {
		return nil, fmt.Errorf("phase 1 (resolve): %w", err)
	}
	s.Project = resolved.ProjectID
	s.Task = resolved.TaskID
	if resolved.Mode != "" {
		s.Mode = resolved.Mode
	}
	s.WorkingDir = resolved.WorkingDir

	// Phase 2: Decide runtime.
	rt, err := phase2DecideRuntime(opts, resolved)
	if err != nil {
		return nil, fmt.Errorf("phase 2 (decide runtime): %w", err)
	}
	s.Runtime = string(rt.Kind())

	// Phase 3: Prepare workspace (worktree, mounts, env).
	prep, err := phase3Prepare(ctx, rt, resolved, opts)
	if err != nil {
		rt.Cleanup(ctx)
		return s, fmt.Errorf("phase 3 (prepare): %w", err)
	}
	s.WorkingDir = prep.WorkingDir
	s.Env = prep.Env

	// Phase 4: Start driver (and container if container runtime).
	if err := phase4Start(ctx, rt, prep); err != nil {
		rt.Cleanup(ctx)
		return s, fmt.Errorf("phase 4 (start): %w", err)
	}
	s.Status = StatusRunning

	// Register + persist.
	if err := mgr.Register(s); err != nil {
		rt.Cleanup(ctx)
		return s, fmt.Errorf("phase 5 (register session): %w", err)
	}
	s.DriverID = rt.DriverID()

	// Side-effect: assign the task to this session (if there is one).
	if opts.TaskID != "" && opts.TaskStore != nil {
		_ = opts.TaskStore.Assign(task.ID(opts.TaskID), s.ID)
	}

	// Phase 6: Send initial prompt.
	if err := phase6Prompt(ctx, rt, resolved, opts); err != nil {
		rt.Cleanup(ctx)
		return s, fmt.Errorf("phase 6 (prompt): %w", err)
	}

	s.UpdatedAt = time.Now().UTC()
	_ = mgr.Update(s) // best-effort

	return s, nil
}

// Resolved is the output of phase 1.
type Resolved struct {
	TaskID      string
	ProjectID   string
	Project     *project.Project
	Mode        driver.Mode
	WorkingDir  string
	VaultReady  bool
	VaultMissed []string
}

func phase1Resolve(ctx context.Context, opts Options) (*Resolved, error) {
	r := &Resolved{TaskID: opts.TaskID, ProjectID: opts.ProjectID}

	// Project inference: explicit -> from task -> unset.
	if r.ProjectID == "" && r.TaskID != "" && opts.TaskStore != nil {
		t, err := opts.TaskStore.Get(task.ID(r.TaskID))
		if err != nil {
			return nil, fmt.Errorf("resolve task %q: %w", r.TaskID, err)
		}
		r.ProjectID = string(t.Project)
	}
	if r.ProjectID != "" && opts.ProjectStore != nil {
		p, err := opts.ProjectStore.Get(project.ID(r.ProjectID))
		if err != nil {
			return nil, fmt.Errorf("resolve project %q: %w", r.ProjectID, err)
		}
		r.Project = p
	}

	// Working dir.
	if r.Project != nil {
		r.WorkingDir = r.Project.WorkspaceRoot
	}

	// Mode resolution: explicit > project default > "agent".
	if opts.Mode != "" {
		r.Mode = opts.Mode
	} else if r.Project != nil && r.Project.Prompts.Mode != "" {
		r.Mode = driver.Mode(r.Project.Prompts.Mode)
	} else {
		r.Mode = driver.ModeAgent
	}

	// Vault readiness.
	if opts.Vault != nil {
		unlocked, _ := opts.Vault.IsUnlocked(ctx)
		r.VaultReady = unlocked
	}

	// Track missing credentials for clearer errors downstream.
	if r.TaskID != "" && opts.TaskStore != nil {
		if t, err := opts.TaskStore.Get(task.ID(r.TaskID)); err == nil {
			if !r.VaultReady && len(t.RequiredCredentials) > 0 {
				r.VaultMissed = append([]string(nil), t.RequiredCredentials...)
			}
		}
	}

	return r, nil
}

func phase2DecideRuntime(opts Options, r *Resolved) (Runtime, error) {
	if opts.Container {
		return NewContainerRuntime(opts, r), nil
	}
	return NewLocalRuntime(opts, r), nil
}

// Prepared is the output of phase 3.
type Prepared struct {
	WorkingDir string
	Mounts     []container.Mount
	Env        map[string]string
}

func phase3Prepare(ctx context.Context, rt Runtime, r *Resolved, opts Options) (*Prepared, error) {
	p := &Prepared{Env: map[string]string{}}

	wd, err := rt.PrepareWorkspace(ctx, r)
	if err != nil {
		return nil, err
	}
	p.WorkingDir = wd

	if rt.Kind() == RuntimeKindContainer {
		p.Mounts = []container.Mount{
			{Source: wd, Target: "/workspace", ReadOnly: false},
		}
		if opts.VaultSocketPath != "" {
			p.Mounts = append(p.Mounts, container.Mount{
				Source:   opts.VaultSocketPath,
				Target:   "/run/harness/vault.sock",
				ReadOnly: false,
			})
		}
	}

	p.Env["HARNESS_SESSION_ID"] = opts.ID
	p.Env["HARNESS_PROJECT_ID"] = opts.ProjectID
	if opts.TaskID != "" {
		p.Env["HARNESS_TASK_ID"] = opts.TaskID
	}
	return p, nil
}

func phase4Start(ctx context.Context, rt Runtime, p *Prepared) error {
	return rt.Start(ctx, p)
}

func phase6Prompt(ctx context.Context, rt Runtime, r *Resolved, opts Options) error {
	if opts.TaskID == "" || opts.TaskStore == nil {
		return nil
	}
	t, err := opts.TaskStore.Get(task.ID(opts.TaskID))
	if err != nil {
		return err
	}
	return rt.Send(ctx, driver.Message{Role: "user", Content: buildTaskPrompt(t)})
}

// buildTaskPrompt constructs the initial user message for a task-ful
// session. The agent reads this as the "kickoff" and works through the
// acceptance criteria.
func buildTaskPrompt(t *task.Task) string {
	prompt := fmt.Sprintf("You are working on task %q (project: %q, priority: %s).\n\n",
		t.Title, t.Project, t.Priority)
	if t.Description != "" {
		prompt += "## Description\n\n" + t.Description + "\n\n"
	}
	if len(t.AcceptanceCriteria) > 0 {
		prompt += "## Acceptance Criteria\n\n"
		for i, c := range t.AcceptanceCriteria {
			prompt += fmt.Sprintf("%d. %s\n", i+1, c)
		}
		prompt += "\n"
	}
	if len(t.OutOfScope) > 0 {
		prompt += "## Out of Scope\n\n"
		for _, c := range t.OutOfScope {
			prompt += "- " + c + "\n"
		}
		prompt += "\n"
	}
	prompt += "## Workflow\n\n"
	prompt += "1. Read the project structure first.\n"
	prompt += "2. Log progress to the task before and after every meaningful action.\n"
	prompt += "3. Verify each acceptance criterion (run tests, inspect outputs).\n"
	prompt += "4. If a blocker arises, log it as a progress entry with a clear question.\n"
	prompt += "5. When done, leave the working directory clean.\n"
	return prompt
}

func (o Options) validate() error {
	if o.Container && o.ProjectID == "" && o.TaskID == "" {
		return errs.Wrap(errs.ErrInvalid, "container sessions require --project or --task")
	}
	if o.PrivilegedDebug && o.ContainerProfile == nil {
		p := container.PrivilegedDebugProfile()
		o.ContainerProfile = &p
	}
	if o.PrivilegedDebug && !o.Container {
		// --privileged-debug without --container is a no-op (local mode
		// is already unprivileged for sensible defaults).
	}
	return nil
}

// newSessionID generates a fresh session identifier. Timestamp + a 4-char
// random suffix yields uniqueness for ~100k sessions/day without collision.
func newSessionID() string {
	now := time.Now().UTC()
	suffix := now.Format("150405.000000")
	// 4 random chars from a 36-char alphabet (~1.7M combos) sufficient
	// for per-second uniqueness in single-user context.
	const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
	s := make([]byte, 4)
	// Cheap pseudo-random from time nanoseconds. Not cryptographic; just
	// enough to disambiguate the timestamp.
	n := now.UnixNano()
	for i := range s {
		s[i] = alphabet[n%36]
		n /= 36
		if n == 0 {
			n = now.UnixNano() >> 32
		}
	}
	return fmt.Sprintf("S-%s-%s", suffix, string(s))
}
