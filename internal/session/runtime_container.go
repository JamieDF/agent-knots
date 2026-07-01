// Package session — runtime_container.go implements RuntimeKindContainer.
//
// ContainerRuntime spins up a podman container with the hardened isolation
// profile (see ADR-004 and internal/container/isolation.go). Inside the
// container, OpenCode runs on its default port (4096); the driver on the
// host dials into it over the bridged network.
//
// # What's in the container
//
//   - The OpenCode server (the agent runtime)
//   - LLM API key — NOT included; the agent asks the host vault via the
//     mounted unix socket, never holds raw keys
//   - The session's worktree, mounted read-write at /workspace
//   - Nothing else from the host
//
// # How the host talks to OpenCode inside
//
// podman publishes the container's OpenCode port onto a random host port.
// We parse `podman port` after Run() to discover the forwarding.
package session

import (
	"bufio"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/agent/driver/opencode"
	"github.com/JamieDF/agentjam/internal/container"
	"github.com/JamieDF/agentjam/internal/container/podman"
	"github.com/JamieDF/agentjam/internal/errs"
)

// ContainerRuntime is the podman-backed containerized-runtime implementation.
type ContainerRuntime struct {
	opts Options
	r    *Resolved

	profile  container.IsolationProfile
	cRuntime container.Runtime // pluggable; defaults to podman

	worktreePath string       // host path to the worktree (source of mount)
	containerID  container.ID // set after Run
	portMapping  string       // e.g. "127.0.0.1:49152"
	driver       driver.Driver
	mu           sync.Mutex
}

// NewContainerRuntime constructs a ContainerRuntime. It defaults to the
// hardened profile; callers may override via opts.ContainerProfile.
func NewContainerRuntime(opts Options, r *Resolved) *ContainerRuntime {
	profile := container.DefaultIsolationProfile()
	if opts.ContainerProfile != nil {
		profile = *opts.ContainerProfile
	}
	if opts.PrivilegedDebug {
		profile = container.PrivilegedDebugProfile()
	}
	return &ContainerRuntime{
		opts:    opts,
		r:       r,
		profile: profile,
	}
}

// Kind implements Runtime.
func (c *ContainerRuntime) Kind() RuntimeKind { return RuntimeKindContainer }

// PrepareWorkspace creates the per-session worktree directory.
//
// v1 implementation is "create empty directory"; a future git-worktree
// integration will branch off the repo and create a real worktree. The
// goal here is to lock down the API — subsequent phases of agentjam can
// swap in the git implementation without changing Init().
func (c *ContainerRuntime) PrepareWorkspace(_ context.Context, r *Resolved) (string, error) {
	if r.Project == nil {
		return "", errs.Wrap(errs.ErrInvalid, "container runtime: project is required")
	}
	base := c.opts.WorktreeBase
	if base == "" {
		base = filepath.Join(os.Getenv("HOME"), ".agentjam", "worktrees")
	}
	wt := filepath.Join(base, string(r.Project.ID), c.opts.ID)
	if err := os.MkdirAll(wt, 0o755); err != nil {
		return "", errs.Wrap(err, "create worktree dir %q", wt)
	}
	c.worktreePath = wt
	return wt, nil
}

// Start runs the container, waits for OpenCode inside to be ready, and
// dials into it.
func (c *ContainerRuntime) Start(ctx context.Context, p *Prepared) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.driver != nil {
		return errs.Wrap(errs.ErrAlreadyExists, "container runtime already started")
	}

	// Pick the container runtime (podman) lazily. Future backends (docker,
	// firecracker) swap this for a different Runtime implementation.
	if c.cRuntime == nil {
		c.cRuntime = podman.NewWithProfile("", c.profile)
	}

	// Resolve host UID for substitution.
	hostUID, err := container.HostUID()
	if err != nil {
		return err
	}

	// Pick an image: explicit override > project setting > auto-detect.
	image := c.opts.ContainerImage
	if image == "" {
		image = pickImage(c.r)
	}

	// Build the hardened ContainerConfig.
	cfg := container.ContainerConfig{
		Image:    container.ImageID(image),
		Name:     "agentjam-" + c.opts.ID,
		Detached: true,
		Env: map[string]string{
			"AGENTJAM_SESSION_ID": c.opts.ID,
		},
		// OpenCode server listens on 4096 inside the container; we
		// ask podman to publish it on a random host port.
		Command: []string{"opencode", "serve", "--port", "4096"},
	}

	cfg, err = container.ApplyIsolation(c.profile, cfg, hostUID)
	if err != nil {
		return err
	}

	// Add the worktree mount at /workspace.
	cfg.Mounts = append([]container.Mount{
		{Source: c.worktreePath, Target: "/workspace", ReadOnly: false},
	}, cfg.Mounts...)

	// Mount the vault socket if a path was provided.
	if c.opts.VaultSocketPath != "" {
		cfg.Mounts = append(cfg.Mounts, container.Mount{
			Source: c.opts.VaultSocketPath,
			Target: "/run/agentjam/vault.sock",
		})
	}

	// Map the container's OpenCode port to a random host port. We'll
	// discover the actual port after Run via `podman port`.
	cfg.Labels["io.agentjam.exposed-port"] = "4096"

	// Start the container.
	cont, err := c.cRuntime.Run(ctx, cfg)
	if err != nil {
		return errs.Wrap(err, "podman run")
	}
	c.containerID = cont.ID

	// Wait briefly for the OpenCode server inside to be ready. We poll
	// `podman port` to find the host-side mapping, then probe the HTTP
	// healthcheck.
	mapping, err := c.discoverPortMapping(ctx)
	if err != nil {
		return errs.Wrap(err, "discover port mapping")
	}
	c.portMapping = mapping

	if err := c.waitForOpenCodeReady(ctx); err != nil {
		_ = c.cRuntime.Stop(ctx, c.containerID, 5*time.Second)
		c.containerID = ""
		return errs.Wrap(err, "wait for opencode in container")
	}

	// Dial into OpenCode via the driver.
	d, err := opencode.New(opencode.Options{
		BaseURL:   "http://" + mapping,
		Directory: "/workspace",
		Title:     "agentjam-session-" + c.opts.ID,
		ID:        "session-" + c.opts.ID,
	})
	if err != nil {
		_ = c.cRuntime.Stop(ctx, c.containerID, 5*time.Second)
		c.containerID = ""
		return err
	}
	if err := d.Start(ctx); err != nil {
		_ = d.Stop(ctx)
		return errs.Wrap(err, "opencode dial")
	}
	if err := d.SetMode(ctx, c.r.Mode); err != nil {
		_ = d.Stop(ctx)
		return errs.Wrap(err, "opencode set mode")
	}

	c.driver = d
	return nil
}

// Send delivers a message to OpenCode inside the container.
func (c *ContainerRuntime) Send(ctx context.Context, msg driver.Message) error {
	c.mu.Lock()
	d := c.driver
	c.mu.Unlock()
	if d == nil {
		return errs.Wrap(errs.ErrUnavailable, "container runtime: not started")
	}
	return d.Send(ctx, msg)
}

// DriverID returns the running driver's ID.
func (c *ContainerRuntime) DriverID() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.driver == nil {
		return ""
	}
	return c.driver.ID()
}

// Driver returns the underlying driver, or nil before Start.
func (c *ContainerRuntime) Driver() driver.Driver {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.driver
}

// Cleanup stops the container and driver, and removes the worktree dir.
func (c *ContainerRuntime) Cleanup(ctx context.Context) {
	c.mu.Lock()
	d := c.driver
	id := c.containerID
	wt := c.worktreePath
	c.driver = nil
	c.containerID = ""
	c.mu.Unlock()

	if d != nil {
		_ = d.Stop(ctx)
	}
	if c.cRuntime != nil && id != "" {
		_ = c.cRuntime.Remove(ctx, id, true)
	}
	if wt != "" {
		_ = os.RemoveAll(wt)
	}
}

// discoverPortMapping inspects `podman port` to find the host port
// forwarded to the container's 4096.
func (c *ContainerRuntime) discoverPortMapping(ctx context.Context) (string, error) {
	bin := ""
	if r, ok := c.cRuntime.(*podman.Runtime); ok {
		bin = r.Binary
	}
	if bin == "" {
		bin = "podman"
	}
	cmd := exec.CommandContext(ctx, bin, "port", string(c.containerID), "4096/tcp")
	out, err := cmd.Output()
	if err != nil {
		return "", errs.Wrap(err, "podman port: %s", err)
	}
	// Output looks like:
	//   0.0.0.0:49152
	//   127.0.0.1:49153
	// We pick the 127.0.0.1 mapping (host loopback).
	scanner := bufio.NewScanner(strings.NewReader(string(out)))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "127.0.0.1:") {
			return line, nil
		}
	}
	// Fall back to whatever the first mapping was.
	scanner = bufio.NewScanner(strings.NewReader(string(out)))
	if scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		// If it's "0.0.0.0:49152", rewrite to "127.0.0.1:49152".
		if strings.HasPrefix(line, "0.0.0.0:") {
			return "127.0.0.1:" + strings.TrimPrefix(line, "0.0.0.0:"), nil
		}
		return line, nil
	}
	return "", errs.Wrap(errs.ErrUnavailable, "podman port: no mapping found")
}

// waitForOpenCodeReady polls the OpenCode healthcheck endpoint (a HEAD on
// the root URL should respond with 200 once ready).
func (c *ContainerRuntime) waitForOpenCodeReady(ctx context.Context) error {
	url := "http://" + c.portMapping
	deadline := time.Now().Add(60 * time.Second)
	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
		// Use curl or net/http; curl is universally available.
		cmd := exec.CommandContext(ctx, "curl", "-sSf", "-o", "/dev/null",
			"--max-time", "2", url+"/")
		if err := cmd.Run(); err == nil {
			return nil
		}
	}
	return errs.Wrap(errs.ErrUnavailable, "opencode not ready after 60s (%s)", url)
}

// pickImage returns the image ID to use for the session. Order of
// resolution: explicit override > project setting > stack-detected.
//
// v1: a tiny stack detector. v2: read project.container.image setting.
func pickImage(r *Resolved) string {
	if r == nil || r.Project == nil {
		return "agentjam-agent-base:latest"
	}
	root := r.Project.WorkspaceRoot

	candidates := []struct {
		file  string
		image string
	}{
		{"package.json", "agentjam-agent-node:20"},
		{"pyproject.toml", "agentjam-agent-python:3.12"},
		{"go.mod", "agentjam-agent-go:1.23"},
		{"Cargo.toml", "agentjam-agent-rust:1.82"},
	}
	for _, c := range candidates {
		if _, err := os.Stat(filepath.Join(root, c.file)); err == nil {
			return c.image
		}
	}
	return "agentjam-agent-base:latest"
}

// Compile-time check.
var _ Runtime = (*ContainerRuntime)(nil)
