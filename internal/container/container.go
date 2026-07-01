// Package container defines the ContainerRuntime interface — the abstraction
// over container engines (Podman, Docker, etc.) used to run agents in
// isolated environments.
//
// The interface is designed so all runtimes expose the same operations:
// build an image, run a container, stream logs, get stats, stop, remove.
// Implementations live under internal/container/ (e.g. podman, docker).
//
// Implementations must be safe for concurrent use.
package container

import (
	"context"
	"io"
	"time"
)

// ID is a unique container identifier.
type ID string

// ImageID identifies a built or pulled image.
type ImageID string

// ImageSpec describes how to build or pull an image.
type ImageSpec struct {
	// Name is a logical name for the image (e.g. "agentjam-node:latest").
	Name string

	// Dockerfile is the inline Dockerfile content. If empty, the runtime
	// expects the image to already exist locally or be pullable from a
	// registry.
	Dockerfile string

	// Context is the build context directory (for Dockerfile-based builds).
	Context string

	// From is the base image (e.g. "docker.io/library/node:20").
	From string

	// Tags are alternative tags for the image.
	Tags []string
}

// ContainerConfig controls how a container is run.
type ContainerConfig struct {
	// Image is the image to run.
	Image ImageID

	// Name is an optional human-readable name.
	Name string

	// Command is the command to run inside the container (overrides image
	// default).
	Command []string

	// Env are environment variables to set.
	Env map[string]string

	// Mounts are filesystem mounts (host:container).
	Mounts []Mount

	// Network is the network mode (e.g. "none", "bridge", "host").
	Network string

	// Workdir is the working directory inside the container.
	Workdir string

	// User is the user to run as (e.g. "1000:1000").
	User string

	// Privileged runs the container with --privileged. **MUST be false for
	// production workloads**; the isolation profile rejects it.
	Privileged bool

	// ReadOnlyRootfs makes the container's root filesystem read-only.
	ReadOnlyRootfs bool

	// Resource limits.
	Resources Resources

	// Labels are key-value tags applied to the container.
	Labels map[string]string

	// AutoRemove deletes the container when it exits.
	AutoRemove bool

	// Detached runs the container in the background.
	Detached bool
}

// Mount describes a filesystem mount.
type Mount struct {
	// Source is the host path.
	Source string

	// Target is the container path.
	Target string

	// ReadOnly makes the mount read-only.
	ReadOnly bool
}

// Resources configures cgroup resource limits.
type Resources struct {
	// CPUs is the number of CPUs (e.g. 2.0 for 2 cores).
	CPUs float64

	// MemoryBytes is the memory limit in bytes (e.g. 4 << 30 for 4 GiB).
	MemoryBytes int64

	// DiskBytes is the disk limit in bytes (e.g. 10 << 30 for 10 GiB).
	DiskBytes int64
}

// Container is a running (or stopped) container.
type Container struct {
	ID    ID
	Name  string
	Image ImageID
	State string
}

// Stats is a point-in-time resource usage snapshot.
type Stats struct {
	CPUPercent     float64
	MemoryUsed     int64
	MemoryLimit    int64
	NetworkRxBytes int64
	NetworkTxBytes int64
	Timestamp      time.Time
}

// Runtime is the interface for container engines.
//
// Implementations live under internal/container/.
type Runtime interface {
	// Name returns the runtime identifier (e.g. "podman", "docker").
	Name() string

	// Available reports whether the runtime is installed and usable.
	Available(ctx context.Context) (bool, error)

	// Version returns the runtime version (e.g. "4.5.0").
	Version(ctx context.Context) (string, error)

	// Build builds an image from spec.
	Build(ctx context.Context, spec ImageSpec) (ImageID, error)

	// Pull pulls an image from a registry.
	Pull(ctx context.Context, ref string) (ImageID, error)

	// Run starts a container and returns it. If Detached is true, returns
	// immediately; otherwise blocks until the container exits.
	Run(ctx context.Context, cfg ContainerConfig) (Container, error)

	// Stop stops a running container.
	Stop(ctx context.Context, id ID, timeout time.Duration) error

	// Remove deletes a container.
	Remove(ctx context.Context, id ID, force bool) error

	// Logs streams container logs. The returned reader is closed when the
	// caller is done.
	Logs(ctx context.Context, id ID, follow bool) (io.ReadCloser, error)

	// Stats returns a single stats snapshot.
	Stats(ctx context.Context, id ID) (Stats, error)

	// List returns containers matching the given filters.
	List(ctx context.Context, all bool) ([]Container, error)
}
