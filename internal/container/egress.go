// Package container — egress.go implements network egress filtering for
// agentjam-managed containers.
//
// After a container starts, deny-list CIDR ranges are blocked at the
// iptables OUTPUT chain inside the container's network namespace. This
// prevents the agent from reaching private networks, cloud metadata
// services, and other sensitive addresses.
//
// Rootless podman note: we use `podman unshare nsenter -t <PID> -n iptables`
// to enter the container's network namespace from the host. This works on
// rootless podman 4.x+ with user namespace remapping.
package container

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
)

// InstallEgressRules installs iptables DROP rules in the container's
// network namespace for each CIDR in denyList. The containerPID is the
// host-side PID of the container's init process (from podman inspect).
//
// Rules are installed in the OUTPUT chain so they affect traffic
// originating from inside the container. If a rule fails to install,
// the error is collected but does not stop the remaining rules.
//
// Returns nil if all rules were installed, or an error listing the
// failures.
func InstallEgressRules(ctx context.Context, containerPID int, denyList []string) error {
	if containerPID <= 0 {
		return fmt.Errorf("egress: invalid container PID %d", containerPID)
	}
	if len(denyList) == 0 {
		return nil
	}

	var errs []string
	for _, cidr := range denyList {
		cidr = strings.TrimSpace(cidr)
		if cidr == "" {
			continue
		}
		if err := installDropRule(ctx, containerPID, cidr); err != nil {
			errs = append(errs, fmt.Sprintf("%s: %v", cidr, err))
		}
	}

	if len(errs) > 0 {
		return fmt.Errorf("egress: failed to install %d/%d rules: %s",
			len(errs), len(denyList), strings.Join(errs, "; "))
	}
	return nil
}

// installDropRule runs a single iptables command in the container's
// network namespace to DROP outbound traffic to the given CIDR.
func installDropRule(ctx context.Context, pid int, cidr string) error {
	// Build: podman unshare nsenter -t <PID> -n iptables -A OUTPUT -d <CIDR> -j DROP
	args := []string{
		"unshare",
		"nsenter", "-t", fmt.Sprintf("%d", pid), "-n",
		"iptables", "-A", "OUTPUT", "-d", cidr, "-j", "DROP",
	}
	cmd := exec.CommandContext(ctx, "podman", args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("iptables -A OUTPUT -d %s: %s (%w)", cidr,
			strings.TrimSpace(string(out)), err)
	}
	return nil
}

// VerifyEgressRules checks whether iptables rules are present in the
// container's network namespace. Returns the list of deny-list CIDRs
// that have active DROP rules.
func VerifyEgressRules(ctx context.Context, containerPID int) ([]string, error) {
	if containerPID <= 0 {
		return nil, fmt.Errorf("egress: invalid container PID %d", containerPID)
	}

	args := []string{
		"unshare",
		"nsenter", "-t", fmt.Sprintf("%d", containerPID), "-n",
		"iptables", "-S", "OUTPUT",
	}
	cmd := exec.CommandContext(ctx, "podman", args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("iptables -S OUTPUT: %s (%w)",
			strings.TrimSpace(string(out)), err)
	}

	var rules []string
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		// Lines look like: -A OUTPUT -d 169.254.0.0/16 -j DROP
		if strings.Contains(line, "-j DROP") && strings.Contains(line, "-d ") {
			parts := strings.Fields(line)
			for i, p := range parts {
				if p == "-d" && i+1 < len(parts) {
					rules = append(rules, parts[i+1])
				}
			}
		}
	}
	return rules, nil
}
