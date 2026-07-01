// Package session — runtime.go defines the per-session runtime abstraction.
//
// Runtime is the contract each backend (LocalRuntime, ContainerRuntime)
// implements so phase 2-4 of session Init() can be backend-agnostic.
//
// The runtime owns four responsibilities:
//
//   - PrepareWorkspace — set up the directory the agent will work in
//     (worktree creation for container sessions, dir creation for local).
//   - Start — launch the driver (and container, if any) and dial into it.
//   - Send — deliver messages to the agent.
//   - Cleanup — release any resources (worktree, container) on error.
//
// Implementations live in this package (local.go and container.go).
package session

import (
	"context"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

// RuntimeKind identifies which backend a Runtime is.
type RuntimeKind string

const (
	// RuntimeKindLocal is the local-host runtime. No isolation.
	RuntimeKindLocal RuntimeKind = "local"

	// RuntimeKindContainer is the containerized runtime with hardened
	// defaults (see ADR-004 and internal/container/isolation.go).
	RuntimeKindContainer RuntimeKind = "container"
)

// Runtime is the per-session backend abstraction.
type Runtime interface {
	// Kind returns the runtime kind ("local" or "container").
	Kind() RuntimeKind

	// PrepareWorkspace sets up the directory the agent will work on.
	// Returns the absolute path.
	PrepareWorkspace(ctx context.Context, r *Resolved) (string, error)

	// Start launches the driver (and any backend container). On success,
	// subsequent Send/Events calls are routed to the running driver.
	Start(ctx context.Context, p *Prepared) error

	// Send delivers msg to the running agent.
	Send(ctx context.Context, msg driver.Message) error

	// DriverID returns the running driver's identifier (set after Start).
	// Returns empty string before Start.
	DriverID() string

	// Cleanup releases any resources held by the runtime. Called when an
	// earlier phase fails so we don't leak worktrees or containers.
	Cleanup(ctx context.Context)
}
