// Package podman implements container.Runtime via the podman CLI.
//
// Podman is the v1 default runtime — rootless by default, daemonless,
// OCI-compatible. The CLI is invoked via os/exec; this package wraps the
// relevant subcommands in a Runtime interface.
//
// # Why CLI and not the podman Go bindings?
//
// The official podman Go bindings (github.com/containers/podman/v5) require a
// running libpod service, which complicates rootless setup. The CLI works
// everywhere podman is installed and is the supported path for rootless
// containers on most Linux distributions.
//
// # Concurrency
//
// Each method spawns a short-lived process and is safe for concurrent use.
package podman

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os/exec"
	"strings"
	"time"

	"github.com/JamieDF/agentjam/internal/container"
	"github.com/JamieDF/agentjam/internal/errs"
)

// Runtime is a podman-backed container.Runtime.
//
// Runtime holds the configured IsolationProfile so every Run() applies the
// hardened defaults (capabilities, security-opt, tmpfs, etc.) without
// callers having to thread the profile through every call.
type Runtime struct {
	// Binary is the path to the podman binary. Defaults to "podman".
	Binary string

	// Profile is the IsolationProfile applied to every Run(). Defaults to
	// container.DefaultIsolationProfile(). Use container.PrivilegedDebugProfile()
	// to opt out — CLI requires --privileged-debug to do this.
	Profile container.IsolationProfile
}

// New constructs a podman Runtime with the default isolation profile.
// If binary is empty, defaults to "podman".
func New(binary string) *Runtime {
	if binary == "" {
		binary = "podman"
	}
	return &Runtime{
		Binary:  binary,
		Profile: container.DefaultIsolationProfile(),
	}
}

// NewWithProfile constructs a podman Runtime with an explicit isolation
// profile. Use this when you need to opt out of the defaults (debugging).
// The CLI gates this behind --privileged-debug.
func NewWithProfile(binary string, profile container.IsolationProfile) *Runtime {
	if binary == "" {
		binary = "podman"
	}
	return &Runtime{
		Binary:  binary,
		Profile: profile,
	}
}

// Name implements container.Runtime.
func (r *Runtime) Name() string { return "podman" }

// Available implements container.Runtime.
func (r *Runtime) Available(ctx context.Context) (bool, error) {
	cmd := exec.CommandContext(ctx, r.Binary, "--version")
	if err := cmd.Run(); err != nil {
		return false, nil // not installed is not an error
	}
	return true, nil
}

// Version implements container.Runtime.
func (r *Runtime) Version(ctx context.Context) (string, error) {
	out, err := r.run(ctx, "version", "--format", "{{.Version}}")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
}

// Build implements container.Runtime.
func (r *Runtime) Build(ctx context.Context, spec container.ImageSpec) (container.ImageID, error) {
	if spec.Dockerfile == "" {
		return "", errs.Wrap(errs.ErrInvalid, "Dockerfile is required for Build")
	}
	// Write Dockerfile to a temp file.
	// (Implementation left as future work — for now, assume spec.Dockerfile
	// is a path to a Dockerfile, or the image already exists locally.)
	args := []string{"build", "-t", spec.Name}
	for _, tag := range spec.Tags {
		args = append(args, "-t", spec.Name+":"+tag)
	}
	if spec.Context != "" {
		args = append(args, spec.Context)
	}
	if _, err := r.run(ctx, args...); err != nil {
		return "", err
	}
	return container.ImageID(spec.Name), nil
}

// Pull implements container.Runtime.
func (r *Runtime) Pull(ctx context.Context, ref string) (container.ImageID, error) {
	if _, err := r.run(ctx, "pull", ref); err != nil {
		return "", err
	}
	return container.ImageID(ref), nil
}

// Run implements container.Runtime.
//
// ContainerConfig is expected to have been hardened by
// container.ApplyIsolation. We translate its settings into the right
// podman CLI flags:
//   - --privileged (must be false; isolation.ApplyIsolation rejects true)
//   - --security-opt for each profile.SecurityOpt
//   - --cap-drop=ALL when profile.DropAllCapabilities is set, then
//     --cap-add=<cap> for each kept capability
//   - --read-only when ReadOnlyRootfs is set
//   - --tmpfs for each tmpfs path
//   - --network, --cpus, -m, --pids-limit
//   - --userns=keep-id when User is set (matches host UID inside)
func (r *Runtime) Run(ctx context.Context, cfg container.ContainerConfig) (container.Container, error) {
	args := []string{"run"}
	if cfg.Detached {
		args = append(args, "-d")
	} else {
		args = append(args, "-it")
	}
	if cfg.AutoRemove {
		args = append(args, "--rm")
	}
	if cfg.Name != "" {
		args = append(args, "--name", cfg.Name)
	}
	if cfg.Network != "" {
		args = append(args, "--network", cfg.Network)
	}
	if cfg.Workdir != "" {
		args = append(args, "-w", cfg.Workdir)
	}
	if cfg.User != "" {
		args = append(args, "-u", cfg.User)
		// Keep the same UID inside the container so files written
		// appear with the host user's ownership (no root-owned files
		// polluting the worktree).
		args = append(args, "--userns", "keep-id")
	}

	// Security options: no-new-privileges, seccomp, apparmor label.
	for _, opt := range r.Profile.SecurityOpts {
		args = append(args, "--security-opt", opt)
	}

	// Capabilities: drop ALL then add back the keep-set.
	if r.Profile.DropAllCapabilities {
		args = append(args, "--cap-drop", "ALL")
		for _, cap := range r.Profile.Capabilities {
			args = append(args, "--cap-add", cap)
		}
	}

	// Read-only rootfs.
	if cfg.ReadOnlyRootfs || r.Profile.ReadOnlyRootfs {
		args = append(args, "--read-only")
	}

	// Tmpfs paths (ephemeral scratch space).
	for _, p := range r.Profile.TmpfsPaths {
		args = append(args, "--tmpfs", p)
	}

	// Pids limit.
	if r.Profile.PidsLimit > 0 {
		args = append(args, "--pids-limit", fmt.Sprintf("%d", r.Profile.PidsLimit))
	}

	// Resource limits.
	if cfg.Resources.CPUs > 0 {
		args = append(args, "--cpus", fmt.Sprintf("%g", cfg.Resources.CPUs))
	}
	if cfg.Resources.MemoryBytes > 0 {
		args = append(args, "-m", fmt.Sprintf("%db", cfg.Resources.MemoryBytes))
	}
	if cfg.Resources.DiskBytes > 0 {
		// --storage-opt size=N requires overlay on XFS (with quota
		// support). On btrfs/ext4 this will error. We skip the flag
		// and rely on container-level disk limits or the runtime's
		// default quota. Callers who know their storage driver
		// supports it can set DiskBytes explicitly.
		// Disabled by default — see IsolationProfile.Resources.
		args = append(args, "--storage-opt", fmt.Sprintf("size=%d", cfg.Resources.DiskBytes))
	}

	// Env, mounts, labels as before.
	for k, v := range cfg.Env {
		args = append(args, "-e", k+"="+v)
	}
	for _, m := range cfg.Mounts {
		if m.Source == "" {
			// Empty source signals tmpfs (already added above); skip.
			continue
		}
		ro := ""
		if m.ReadOnly {
			ro = ":ro"
		}
		args = append(args, "-v", m.Source+":"+m.Target+ro)
	}
	for k, v := range cfg.Labels {
		args = append(args, "--label", k+"="+v)
	}
	args = append(args, string(cfg.Image))
	args = append(args, cfg.Command...)

	out, err := r.run(ctx, args...)
	if err != nil {
		return container.Container{}, err
	}
	id := strings.TrimSpace(out)
	if cfg.Detached {
		// Out is the container ID.
		return container.Container{ID: container.ID(id), Image: cfg.Image, State: "running"}, nil
	}
	// Foreground run: container has exited. Return with exit state.
	return container.Container{ID: container.ID(id), Image: cfg.Image, State: "exited"}, nil
}

// Stop implements container.Runtime.
func (r *Runtime) Stop(ctx context.Context, id container.ID, timeout time.Duration) error {
	secs := int(timeout.Seconds())
	if secs < 1 {
		secs = 10
	}
	_, err := r.run(ctx, "stop", "-t", fmt.Sprintf("%d", secs), string(id))
	return err
}

// ContainerPID returns the host-side PID of the container's init process.
// Used for nsenter-based operations (e.g. egress rule installation).
func (r *Runtime) ContainerPID(ctx context.Context, id container.ID) (int, error) {
	out, err := r.run(ctx, "inspect", "--format", "{{.State.Pid}}", string(id))
	if err != nil {
		return 0, err
	}
	var pid int
	if _, err := fmt.Sscanf(strings.TrimSpace(out), "%d", &pid); err != nil {
		return 0, fmt.Errorf("parse container PID: %w", err)
	}
	return pid, nil
}

// Remove implements container.Runtime.
func (r *Runtime) Remove(ctx context.Context, id container.ID, force bool) error {
	args := []string{"rm"}
	if force {
		args = append(args, "-f")
	}
	args = append(args, string(id))
	_, err := r.run(ctx, args...)
	return err
}

// Logs implements container.Runtime.
func (r *Runtime) Logs(ctx context.Context, id container.ID, follow bool) (io.ReadCloser, error) {
	args := []string{"logs"}
	if follow {
		args = append(args, "-f")
	}
	args = append(args, string(id))

	cmd := exec.CommandContext(ctx, r.Binary, args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, errs.Wrap(err, "create log pipe")
	}
	if err := cmd.Start(); err != nil {
		return nil, errs.Wrap(err, "start logs")
	}
	return stdout, nil
}

// Stats implements container.Runtime.
func (r *Runtime) Stats(ctx context.Context, id container.ID) (container.Stats, error) {
	// podman stats --format json --no-stream
	args := []string{"stats", "--no-stream", "--format", "json", string(id)}
	out, err := r.run(ctx, args...)
	if err != nil {
		return container.Stats{}, err
	}

	var raw []struct {
		CPUPercent string `json:"cpu_percent"`
		MemUsage   string `json:"mem_usage"`
		MemLimit   string `json:"mem_limit"`
		NetRxBytes string `json:"net_rx"`
		NetTxBytes string `json:"net_tx"`
	}
	if err := json.Unmarshal([]byte(out), &raw); err != nil {
		return container.Stats{}, errs.Wrap(err, "parse stats")
	}
	if len(raw) == 0 {
		return container.Stats{}, nil
	}
	row := raw[0]

	stats := container.Stats{
		Timestamp: time.Now(),
	}
	if v, err := parsePercent(row.CPUPercent); err == nil {
		stats.CPUPercent = v
	}
	if v, err := parseBytes(row.MemUsage); err == nil {
		stats.MemoryUsed = v
	}
	if v, err := parseBytes(row.MemLimit); err == nil {
		stats.MemoryLimit = v
	}
	if v, err := parseBytes(row.NetRxBytes); err == nil {
		stats.NetworkRxBytes = v
	}
	if v, err := parseBytes(row.NetTxBytes); err == nil {
		stats.NetworkTxBytes = v
	}
	return stats, nil
}

// List implements container.Runtime.
func (r *Runtime) List(ctx context.Context, all bool) ([]container.Container, error) {
	args := []string{"ps", "--format", "json"}
	if all {
		args = append(args, "-a")
	}
	out, err := r.run(ctx, args...)
	if err != nil {
		return nil, err
	}

	var raw []struct {
		ID    string   `json:"Id"`
		Names []string `json:"Names"`
		Image string   `json:"Image"`
		State string   `json:"State"`
	}
	if err := json.Unmarshal([]byte(out), &raw); err != nil {
		return nil, errs.Wrap(err, "parse ps output")
	}
	containers := make([]container.Container, len(raw))
	for i, r := range raw {
		name := ""
		if len(r.Names) > 0 {
			name = r.Names[0]
		}
		containers[i] = container.Container{
			ID:    container.ID(r.ID),
			Name:  name,
			Image: container.ImageID(r.Image),
			State: r.State,
		}
	}
	return containers, nil
}

// run executes the podman CLI with args and returns combined stdout.
func (r *Runtime) run(ctx context.Context, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, r.Binary, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		return "", errs.Wrap(err, "podman %s: %s", strings.Join(args, " "), stderr.String())
	}
	return stdout.String(), nil
}

// parsePercent parses a percentage string like "12.34%" to 12.34.
func parsePercent(s string) (float64, error) {
	s = strings.TrimSuffix(strings.TrimSpace(s), "%")
	var v float64
	_, err := fmt.Sscanf(s, "%f", &v)
	return v, err
}

// parseBytes parses a size string like "1.5GB" to bytes.
func parseBytes(s string) (int64, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, nil
	}

	// Try to split into number and unit suffix.
	var (
		numStr, unit string
	)
	for i, c := range s {
		if (c >= '0' && c <= '9') || c == '.' {
			continue
		}
		numStr = s[:i]
		unit = s[i:]
		break
	}
	if numStr == "" {
		numStr = s
	}

	var val float64
	if _, err := fmt.Sscanf(numStr, "%f", &val); err != nil {
		return 0, errs.Wrap(err, "parse bytes %q", s)
	}

	unit = strings.ToUpper(strings.TrimSpace(unit))
	var mult int64
	switch unit {
	case "", "B":
		mult = 1
	case "K", "KB":
		mult = 1024
	case "M", "MB":
		mult = 1024 * 1024
	case "G", "GB":
		mult = 1024 * 1024 * 1024
	case "T", "TB":
		mult = 1024 * 1024 * 1024 * 1024
	default:
		return 0, errs.Wrap(errs.ErrInvalid, "unknown unit %q", unit)
	}
	return int64(val * float64(mult)), nil
}

// Compile-time check.
var _ container.Runtime = (*Runtime)(nil)
