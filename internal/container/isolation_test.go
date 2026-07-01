package container

import (
	"strings"
	"testing"
)

func TestDefaultIsolationProfile_DefaultsAreSafe(t *testing.T) {
	p := DefaultIsolationProfile()

	// Most important: NOT privileged.
	if p.Privileged {
		t.Error("default profile must not be privileged")
	}

	// Must run as non-root (placeholder is "1000:1000", but the principle
	// holds: never run as root by default).
	if p.User == "" || p.User == "0:0" {
		t.Errorf("default profile must run as non-root, got User=%q", p.User)
	}

	// Must drop ALL caps.
	if !p.DropAllCapabilities {
		t.Error("default profile must drop all capabilities")
	}

	// Must re-add only the safe file-ops ones.
	wantCaps := map[string]bool{
		"CAP_CHOWN":        true,
		"CAP_DAC_OVERRIDE": true,
		"CAP_FOWNER":       true,
		"CAP_FSETID":       true,
		"CAP_SETUID":       true,
		"CAP_SETGID":       true,
		"CAP_SETFCAP":      true,
	}
	gotCaps := make(map[string]bool)
	for _, c := range p.Capabilities {
		gotCaps[c] = true
	}
	for want := range wantCaps {
		if !gotCaps[want] {
			t.Errorf("default profile missing required cap %s", want)
		}
	}

	// Must not grant dangerous caps.
	forbiddenCaps := []string{
		"CAP_NET_ADMIN",
		"CAP_NET_RAW",
		"CAP_SYS_ADMIN",
		"CAP_SYS_PTRACE",
		"CAP_SYS_MODULE",
		"CAP_SYS_RAWIO",
		"CAP_AUDIT_CONTROL",
	}
	for _, bad := range forbiddenCaps {
		if gotCaps[bad] {
			t.Errorf("default profile grants dangerous cap %s", bad)
		}
	}

	// Must enable no-new-privileges + seccomp.
	hasNoNewPriv := false
	hasSeccomp := false
	for _, opt := range p.SecurityOpts {
		if strings.Contains(opt, "no-new-privileges:true") {
			hasNoNewPriv = true
		}
		if strings.Contains(opt, "seccomp=") {
			hasSeccomp = true
		}
	}
	if !hasNoNewPriv {
		t.Error("default profile must enable no-new-privileges")
	}
	if !hasSeccomp {
		t.Error("default profile must enable seccomp")
	}

	// Must read-only rootfs.
	if !p.ReadOnlyRootfs {
		t.Error("default profile must have ReadOnlyRootfs=true")
	}

	// Must have private network (NOT host).
	if p.Network == "host" {
		t.Error("default profile must not use host network")
	}

	// Must deny cloud metadata.
	deniesMetadata := false
	for _, c := range p.EgressDenyList {
		if strings.Contains(c, "169.254.169.254") {
			deniesMetadata = true
			break
		}
	}
	if !deniesMetadata {
		t.Error("default profile must deny cloud metadata endpoint")
	}

	// Must have sensible resource limits.
	if p.Resources.CPUs <= 0 {
		t.Error("default profile must have CPU limit")
	}
	if p.Resources.MemoryBytes <= 0 {
		t.Error("default profile must have Memory limit")
	}
	if p.PidsLimit <= 0 {
		t.Error("default profile must have PidsLimit")
	}
}

func TestPrivilegedDebugProfile_OptInToInsecure(t *testing.T) {
	p := PrivilegedDebugProfile()

	// Should be privileged.
	if !p.Privileged {
		t.Error("PrivilegedDebugProfile must be privileged")
	}

	// Should run as root.
	if p.User != "0:0" {
		t.Errorf("PrivilegedDebugProfile must run as root, got %q", p.User)
	}

	// Should NOT drop all caps.
	if p.DropAllCapabilities {
		t.Error("PrivilegedDebugProfile must not drop capabilities")
	}

	// Should have host network.
	if p.Network != "host" {
		t.Errorf("PrivilegedDebugProfile must use host network, got %q", p.Network)
	}

	// Should NOT be read-only.
	if p.ReadOnlyRootfs {
		t.Error("PrivilegedDebugProfile must not be read-only")
	}
}

func TestApplyIsolation_SubstitutesHostUID(t *testing.T) {
	p := DefaultIsolationProfile()
	base := ContainerConfig{
		Image: ImageID("agentjam-agent-node:20"),
	}

	cfg, err := ApplyIsolation(p, base, "1234:5678")
	if err != nil {
		t.Fatal(err)
	}

	if cfg.User != "1234:5678" {
		t.Errorf("User = %q, want 1234:5678", cfg.User)
	}
}

func TestApplyIsolation_KeepsExplicitUser(t *testing.T) {
	p := DefaultIsolationProfile()
	base := ContainerConfig{
		Image: ImageID("agentjam-agent-node:20"),
		User:  "555:555", // already set
	}

	cfg, err := ApplyIsolation(p, base, "1234:5678")
	if err != nil {
		t.Fatal(err)
	}

	// Explicit user should not be overwritten by the substitute.
	if cfg.User != "555:555" {
		t.Errorf("User = %q, want 555:555 (explicit)", cfg.User)
	}
}

func TestApplyIsolation_AddsManagedLabel(t *testing.T) {
	p := DefaultIsolationProfile()
	base := ContainerConfig{
		Image: ImageID("agentjam-agent-node:20"),
	}
	cfg, err := ApplyIsolation(p, base, "1000:1000")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Labels["io.agentjam.managed"] != "true" {
		t.Error("missing io.agentjam.managed label")
	}
}

func TestApplyIsolation_AppliesResourceDefaults(t *testing.T) {
	p := DefaultIsolationProfile()
	base := ContainerConfig{
		Image: ImageID("agentjam-agent-node:20"),
		// No Resources set.
	}
	cfg, err := ApplyIsolation(p, base, "1000:1000")
	if err != nil {
		t.Fatal(err)
	}

	if cfg.Resources.CPUs != p.Resources.CPUs {
		t.Errorf("CPUs = %v, want %v", cfg.Resources.CPUs, p.Resources.CPUs)
	}
	if cfg.Resources.MemoryBytes != p.Resources.MemoryBytes {
		t.Errorf("MemoryBytes = %d, want %d", cfg.Resources.MemoryBytes, p.Resources.MemoryBytes)
	}
}

func TestApplyIsolation_RespectsProvidedResources(t *testing.T) {
	p := DefaultIsolationProfile()
	base := ContainerConfig{
		Image: ImageID("agentjam-agent-node:20"),
		Resources: Resources{
			CPUs:        8.0,
			MemoryBytes: 16 << 30,
		},
	}
	cfg, err := ApplyIsolation(p, base, "1000:1000")
	if err != nil {
		t.Fatal(err)
	}

	if cfg.Resources.CPUs != 8.0 {
		t.Errorf("CPUs = %v, want 8.0 (explicit)", cfg.Resources.CPUs)
	}
	if cfg.Resources.MemoryBytes != 16<<30 {
		t.Errorf("MemoryBytes = %d, want 16<<30 (explicit)", cfg.Resources.MemoryBytes)
	}
}

func TestApplyIsolation_DefaultsNetworkIsolated(t *testing.T) {
	p := DefaultIsolationProfile()
	base := ContainerConfig{
		Image: ImageID("agentjam-agent-node:20"),
		// Network empty.
	}
	cfg, err := ApplyIsolation(p, base, "1000:1000")
	if err != nil {
		t.Fatal(err)
	}
	// Network must not be "host" — rootless podman's default is already
	// isolated (slirp4netns/pasta). Egress filtering is applied separately.
	if cfg.Network == "host" {
		t.Error("default profile must not use host network")
	}
}

func TestApplyIsolation_RefusesPrivileged(t *testing.T) {
	p := DefaultIsolationProfile()
	p.Privileged = true // try to enable

	_, err := ApplyIsolation(p, ContainerConfig{Image: ImageID("x")}, "1000:1000")
	if err == nil {
		t.Error("expected error for Privileged=true")
	}
}

func TestApplyValidation_RefusesEmptyCapsWhenDroppingAll(t *testing.T) {
	p := DefaultIsolationProfile()
	p.Capabilities = nil
	p.DropAllCapabilities = true

	err := p.validate()
	if err == nil {
		t.Error("expected validation error for empty caps + drop-all")
	}
}

func TestApplyValidation_RefusesBadCIDR(t *testing.T) {
	p := DefaultIsolationProfile()
	p.EgressDenyList = []string{"not-a-cidr"}

	err := p.validate()
	if err == nil {
		t.Error("expected validation error for bad CIDR")
	}
}

func TestIsolationProfile_TmpfsMountsListed(t *testing.T) {
	p := DefaultIsolationProfile()
	expectedTmpfs := []string{"/tmp", "/var/tmp", "/run"}
	for _, want := range expectedTmpfs {
		found := false
		for _, p := range p.TmpfsPaths {
			if p == want {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("missing tmpfs path %s", want)
		}
	}
}

func TestIsolationProfile_NamespacesPrivate(t *testing.T) {
	p := DefaultIsolationProfile()
	hasPID, hasIPC, hasUTS := false, false, false
	for _, ns := range p.Namespaces {
		switch ns {
		case "pid":
			hasPID = true
		case "ipc":
			hasIPC = true
		case "uts":
			hasUTS = true
		}
	}
	if !hasPID || !hasIPC || !hasUTS {
		t.Errorf("default profile must privatize pid/ipc/uts, got %v", p.Namespaces)
	}
}
