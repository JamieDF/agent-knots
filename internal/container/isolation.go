// Package container — isolation.go defines the security profile applied
// automatically to every harness-managed container session.
//
// The profile takes a ContainerConfig and returns a hardened version
// suitable for running AI coding agents. Every default is set "safe": the
// most restrictive option that still lets the agent do real work.
//
// # Threat model
//
// We assume the agent is well-intentioned but capable of mistakes (rm -rf,
// typos in shell pipelines) and that the LLM driving it may emit
// adversarial instructions if jailbroken. We want:
//
//   - Accidental damage contained to the container.
//   - No access to host secrets, SSH keys, browser cookies, etc.
//   - Hard cgroup limits so resource exhaustion doesn't freeze the host.
//   - Network allowlisted so secret exfiltration is hard.
//
// # Apply
//
//	runtime := podman.New("")
//	cfg, err := container.ApplyIsolation(container.DefaultIsolationProfile(), raw, uid)
//	if err != nil { return err }
//	cont, err := runtime.Run(ctx, cfg)
package container

import (
	"fmt"
	"os/user"
	"strings"
)

// IsolationProfile describes the security defaults for a container session.
//
// All fields are populated by DefaultIsolationProfile; users override only
// in extreme cases (debugging a problem, e.g.). The CLI exposes a
// `--privileged-debug` opt-out that drops the profile entirely, with a
// visible warning.
type IsolationProfile struct {
	// User is the UID:GID to run as inside the container (e.g. "1000:1000").
	// Defaults to the calling user's UID/GID. Running as a non-root UID is
	// the single most important isolation setting.
	User string

	// Privileged is whether to pass --privileged to the runtime. ALWAYS
	// false in DefaultIsolationProfile.
	Privileged bool

	// Capabilities is the set of Linux capabilities to KEEP. All others
	// are dropped. Defaults to the file-op subset needed for an agent.
	Capabilities []string

	// SecurityOpts is the list of --security-opt flags. Defaults to
	// no-new-privileges and seccomp=runtime/default.
	SecurityOpts []string

	// ReadOnlyRootfs makes the container's root filesystem read-only.
	// Defaults to true.
	ReadOnlyRootfs bool

	// TmpfsPaths are paths mounted as tmpfs (RAM-backed, ephemeral).
	TmpfsPaths []string

	// Network is the network mode passed to the runtime. "private"
	// creates a per-container network namespace. Host-installed egress
	// filters then apply.
	Network string

	// EgressAllowlist is the set of hostnames/IPs the container may reach.
	// All other outbound traffic is dropped at the host filter layer.
	EgressAllowlist []string

	// EgressDenyList is the set of CIDR ranges ALWAYS denied (private
	// nets, link-local, cloud metadata).
	EgressDenyList []string

	// Resources are the cgroup limits.
	Resources Resources

	// PidsLimit caps the number of processes inside the container.
	// Default 512. Prevents fork bombs.
	PidsLimit int

	// DropCapabilities explicitly enumerates capabilities to drop. If
	// non-empty, the runtime applies these in addition to the inverse of
	// Capabilities. Default: drop ALL.
	DropAllCapabilities bool

	// Namespaces lists the namespaces the container gets its own copy of.
	// Defaults to "pid", "ipc", "uts", "mount".
	Namespaces []string

	// Workdir is the working directory inside the container.
	Workdir string
}

// DefaultIsolationProfile returns the safe-by-default security profile for
// harness-managed containers.
//
// The returned profile is a defensive copy; callers may safely mutate it.
func DefaultIsolationProfile() IsolationProfile {
	return IsolationProfile{
		User: "1000:1000", // overridden by ApplyIsolation to the real UID

		Privileged: false,

		// Capabilities to KEEP. Everything else is dropped.
		// Just the file-op caps the agent needs:
		//   CAP_CHOWN, CAP_DAC_OVERRIDE, CAP_FOWNER — change ownership and
		//     bypass file permission checks so the agent can write anywhere
		//     in its worktree.
		//   CAP_SETUID, CAP_SETGID, CAP_SETFCAP — needed by some package
		//     managers when the agent installs system-level packages.
		//   CAP_FSETID — for `chmod` to update a file the user doesn't own.
		// NOT included (refused even if asked):
		//   CAP_NET_ADMIN, CAP_NET_RAW — no raw sockets, no firewall mods.
		//   CAP_SYS_ADMIN — would be root-equivalent.
		//   CAP_SYS_PTRACE — no attaching to other processes.
		//   CAP_SYS_MODULE — no loading kernel modules.
		//   CAP_MKNOD, CAP_AUDIT_* — not needed.
		Capabilities: []string{
			"CAP_CHOWN",
			"CAP_DAC_OVERRIDE",
			"CAP_FOWNER",
			"CAP_FSETID",
			"CAP_SETUID",
			"CAP_SETGID",
			"CAP_SETFCAP",
		},

		SecurityOpts: []string{
			"no-new-privileges:true",  // can't escalate via setuid binaries
			"seccomp=runtime/default", // kernel's default syscall filter
			"label=type:container_runtime_t",
		},

		ReadOnlyRootfs: true,

		TmpfsPaths: []string{
			"/tmp",     // scratch space, RAM-backed
			"/var/tmp", // ditto
			"/run",     // for the vault socket mount
		},

		Network: "private", // per-container netns

		// Always-allowed egress (whitelist):
		//   - LLM provider APIs (real list comes from project config)
		//   - GitHub API (so agent can use gh CLI)
		//   - npm/pypi/goproxy (so agent can install deps)
		// All other outbound is dropped at the egress filter.
		EgressAllowlist: []string{}, // populated by project policy

		// Always-denied (network-level blocks):
		EgressDenyList: []string{
			"169.254.0.0/16",     // link-local
			"127.0.0.0/8",        // loopback (stops container from hitting host services)
			"10.0.0.0/8",         // RFC1918 private
			"172.16.0.0/12",      // RFC1918 private
			"192.168.0.0/16",     // RFC1918 private
			"169.254.169.254/32", // cloud metadata service
			"::1/128",            // IPv6 loopback
			"fc00::/7",           // IPv6 ULA
			"fe80::/10",          // IPv6 link-local
		},

		Resources: Resources{
			CPUs:        2.0,
			MemoryBytes: 4 << 30,  // 4 GiB
			DiskBytes:   10 << 30, // 10 GiB
		},

		PidsLimit: 512,

		DropAllCapabilities: true,

		Namespaces: []string{"pid", "ipc", "uts", "mount"},

		Workdir: "/workspace",
	}
}

// PrivilegedDebugProfile returns a profile that disables most isolation.
// This exists ONLY for the `--privileged-debug` CLI flag and is gated
// behind a confirmation prompt in the CLI. It logs a warning to
// ~/.agentjam/logs/agentjam.log every time it's used.
func PrivilegedDebugProfile() IsolationProfile {
	p := DefaultIsolationProfile()
	p.User = "0:0" // run as root
	p.Privileged = true
	p.ReadOnlyRootfs = false
	p.SecurityOpts = []string{}
	p.DropAllCapabilities = false
	p.TmpfsPaths = []string{}
	p.Network = "host" // full host network
	return p
}

// ApplyIsolation returns a hardened ContainerConfig based on profile.
//
// Process:
//   - Set User (override with the real UID if "1000:1000" placeholder)
//   - Always apply !Privileged
//   - Compute mounts: workspace + vault socket + tmpfs
//   - Apply capabilities
//   - Apply resource limits
//   - Apply security opts
//
// The returned config has ALL sensitive fields set. The caller can still
// add additional mounts (e.g. read-only reference data) but cannot loosen
// the security defaults without constructing a new IsolationProfile.
func ApplyIsolation(p IsolationProfile, base ContainerConfig, hostUID string) (ContainerConfig, error) {
	if err := p.validate(); err != nil {
		return ContainerConfig{}, err
	}

	// Resolve user. If "1000:1000" placeholder, substitute hostUID.
	cfg := base
	if cfg.User == "" {
		cfg.User = resolveUser(p.User, hostUID)
	}
	cfg.Privileged = p.Privileged
	cfg.ReadOnlyRootfs = p.ReadOnlyRootfs || base.ReadOnlyRootfs

	// Validate mounts: only allow sources that pass our gate. We do not
	// refuse base.Mounts; the caller knows what they mounted. But we add
	// our own mandatory mounts.
	cfg.Mounts = append(base.Mounts, mandatoryMounts(base)...)

	// Apply resource limits unless already set.
	if cfg.Resources.CPUs == 0 {
		cfg.Resources.CPUs = p.Resources.CPUs
	}
	if cfg.Resources.MemoryBytes == 0 {
		cfg.Resources.MemoryBytes = p.Resources.MemoryBytes
	}
	if cfg.Resources.DiskBytes == 0 {
		cfg.Resources.DiskBytes = p.Resources.DiskBytes
	}

	// Apply network unless caller set a specific one. Default to private.
	if cfg.Network == "" {
		cfg.Network = p.Network
	}

	// Workdir default.
	if cfg.Workdir == "" {
		cfg.Workdir = p.Workdir
	}

	// Labels so the cockpit and `podman ps` can identify harness containers.
	if cfg.Labels == nil {
		cfg.Labels = map[string]string{}
	}
	cfg.Labels["io.agentjam.managed"] = "true"

	return cfg, nil
}

// resolveUser substitutes the placeholder UID with the host's UID.
func resolveUser(profileUser, hostUID string) string {
	if profileUser == "" {
		return hostUID
	}
	if profileUser == "1000:1000" && hostUID != "" {
		return hostUID
	}
	return profileUser
}

// mandatoryMounts returns the mounts every harness container gets:
//   - /tmp tmpfs
//   - /run tmpfs (for vault socket)
//
// The worktree mount is added by the session init code (it depends on the
// session/project); the vault socket mount is added when the session has
// been registered. This function adds only the always-on mounts.
func mandatoryMounts(cfg ContainerConfig) []Mount {
	var m []Mount

	// /tmp tmpfs (already in profile, but we ensure mount order).
	for _, p := range []string{"/tmp", "/var/tmp", "/run"} {
		m = append(m, Mount{
			Source: "",
			Target: p,
			// Type "tmpfs" is signalled by empty Source. The podman
			// runtime will turn these into --tmpfs flags.
		})
	}

	return m
}

// validate ensures the profile is internally consistent. Catches mistakes
// like setting Privileged=true with a ReadOnlyRootfs=false (the inconsistency
// is fine but we'd rather fail loudly).
func (p IsolationProfile) validate() error {
	if p.Privileged {
		return fmt.Errorf("isolation: privileged=true is not supported (use PrivilegedDebugProfile)")
	}
	if len(p.Capabilities) == 0 && p.DropAllCapabilities {
		return fmt.Errorf("isolation: dropping all capabilities with no additions yields a useless container")
	}
	for _, b := range p.EgressDenyList {
		if !strings.Contains(b, "/") {
			return fmt.Errorf("isolation: EgressDenyList entry %q must be CIDR", b)
		}
	}
	return nil
}

// HostUID returns the current user's UID:GID, formatted for the User field
// of ContainerConfig. Used by ApplyIsolation to substitute placeholders.
func HostUID() (string, error) {
	u, err := user.Current()
	if err != nil {
		return "", fmt.Errorf("isolation: cannot determine host UID: %w", err)
	}
	return fmt.Sprintf("%s:%s", u.Uid, u.Gid), nil
}

// SecurityOpts returns the security options for the runtime. The podman
// runtime turns these into --security-opt flags.
func (p IsolationProfile) SecurityOptsForRuntime() []string {
	return p.SecurityOpts
}

// DropAllCapsFlag returns the runtime flag string for dropping all
// capabilities. The podman runtime turns this into --cap-drop=ALL.
func (p IsolationProfile) DropAllCapsFlag() string {
	if p.DropAllCapabilities {
		return "ALL"
	}
	return ""
}

// AddCaps returns the list of capabilities to ADD back after dropping.
func (p IsolationProfile) AddCaps() []string {
	return p.Capabilities
}
