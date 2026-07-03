package pi

import (
	"context"
	"fmt"
	"os/exec"
	"path/filepath"

	"github.com/JamieDF/agentjam/internal/agent/driver"
)

// ContainerOptions configures a containerized Pi driver.
type ContainerOptions struct {
	// Image is the container image (e.g. "agentjam-agent-node:20").
	Image string

	// WorktreeDir is the host directory to mount as /workspace.
	WorktreeDir string

	// ExtensionsDir is the host directory to mount as /extensions (read-only).
	ExtensionsDir string

	// ID is the driver instance identifier.
	ID string

	// Provider is the LLM provider.
	Provider string

	// Model is the model pattern or ID.
	Model string
}

// NewContainer constructs a Pi driver that runs inside a podman container.
// Returns a standard *Driver that, when Start() is called, spawns a podman
// container with Pi installed and pipes JSONL over stdin/stdout.
func NewContainer(opts ContainerOptions) (*Driver, error) {
	if opts.Image == "" {
		opts.Image = "agentjam-agent-node:20"
	}
	if opts.WorktreeDir == "" {
		return nil, fmt.Errorf("pi container driver: WorktreeDir is required")
	}

	id := opts.ID
	if id == "" {
		id = fmt.Sprintf("pi-container-%d", 1)
	}

	d := &Driver{
		id:      id,
		workdir: "/workspace", // Inside the container.
		modeFile:  filepath.Join("/workspace", ".agentjam", "modes", "agent.md"),
		provider:  opts.Provider,
		model:     opts.Model,
		mode:      driver.ModeAgent,
		status:    driver.StatusIdle,
		events:    make(chan driver.Event, 64),
		pending:   make(map[int64]chan jsonResponse),
		exited:    make(chan struct{}),
		piPath:    "pi", // Inside the container, pi is on PATH.
	}

	// Override the command builder to use podman instead of direct exec.
	d.containerCmd = func(ctx context.Context) *exec.Cmd {
		args := []string{
			"run",
			"--rm",
			"--name", "agentjam-" + id,
			"--network", "private",
			"--userns", "keep-id",
			// Mount the worktree as the workspace.
			"-v", fmt.Sprintf("%s:/workspace:Z", opts.WorktreeDir),
		}

		// Mount the extension if available.
		if opts.ExtensionsDir != "" {
			args = append(args, "-v", fmt.Sprintf("%s:/extensions:ro,Z", opts.ExtensionsDir))
		}

		// Pass API keys from environment.
		for _, key := range []string{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "PI_API_KEY"} {
			if val, ok := ctx.Value(key).(string); ok && val != "" {
				args = append(args, "-e", key+"="+val)
			}
		}

		args = append(args, opts.Image)

		// Pi command inside the container.
		piArgs := []string{
			"pi", "--mode", "rpc",
			"--no-session",
		}
		if d.modeFile != "" {
			piArgs = append(piArgs, "--system-prompt", d.modeFile)
		}
		if d.provider != "" {
			piArgs = append(piArgs, "--provider", d.provider)
		}
		if d.model != "" {
			piArgs = append(piArgs, "--model", d.model)
		}
		// If extensions dir is mounted, load the extension.
		if opts.ExtensionsDir != "" {
			piArgs = append(piArgs, "--extension", "/extensions/dist/index.js")
		}

		args = append(args, piArgs...)
		return exec.CommandContext(ctx, "podman", args...)
	}

	return d, nil
}
