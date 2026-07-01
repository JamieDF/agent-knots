//go:build integration

package integration

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// initTempGitRepo creates a git repo at dir with an initial commit on main.
func initTempGitRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	for _, args := range [][]string{
		{"init", "-q", "-b", "main", dir},
		{"-C", dir, "config", "user.email", "[email protected]"},
		{"-C", dir, "config", "user.name", "Integration Test"},
	} {
		if out, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Skipf("git %v: %s (%v) — skipping", args, out, err)
		}
	}
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("# test\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"-C", dir, "add", "."},
		{"-C", dir, "commit", "-q", "-m", "initial"},
	} {
		if out, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %s (%v)", args, out, err)
		}
	}
	return dir
}

// gitBranchExists checks if a branch matching pattern exists in the repo.
func gitBranchExists(t *testing.T, repoDir, pattern string) bool {
	t.Helper()
	out, err := exec.Command("git", "-C", repoDir, "branch", "--list", pattern).Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) != ""
}

func TestWorktree_CreateAndCleanup(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not installed")
	}

	repoDir := initTempGitRepo(t)

	// Create a project pointing to the repo.
	out, err := runAgentJam("project", "create", "wt-test",
		"--name", "Worktree Test",
		"--root", repoDir)
	if err != nil {
		t.Fatalf("project create: %v\n%s", err, out)
	}

	// Start a session with --worktree.
	out, err = runAgentJam("session", "start",
		"--driver", "mock",
		"--project", "wt-test",
		"--worktree",
		"--detach")
	if err != nil {
		t.Fatalf("session start: %v\n%s", err, out)
	}
	id := extractSessionID(out)
	if id == "" {
		t.Fatalf("could not extract session ID from: %s", out)
	}

	// Wait for PID file.
	pidPath := filepath.Join(ajHome, "sessions", id+".pid")
	if !waitForFile(pidPath, 15*time.Second) {
		t.Fatalf("PID file not created\nLog:\n%s", readSessionLog(id))
	}
	defer stopSession(t, id)

	// Give the session time to create the worktree.
	time.Sleep(2 * time.Second)

	// Verify worktree branch was created.
	if !gitBranchExists(t, repoDir, "agent-"+id+"*") {
		// The local runtime uses just "agent-<id>" as branch name.
		if !gitBranchExists(t, repoDir, "agent-*") {
			t.Errorf("no worktree branch found in %s\nLog:\n%s",
				repoDir, readSessionLog(id))
		}
	}

	// Stop the session.
	stopSession(t, id)

	// Give cleanup time to run.
	time.Sleep(2 * time.Second)

	// Verify worktree branch was deleted.
	if gitBranchExists(t, repoDir, "agent-*") {
		out, _ := exec.Command("git", "-C", repoDir, "branch", "--list", "agent-*").Output()
		t.Errorf("worktree branch still exists after stop: %s", strings.TrimSpace(string(out)))
	}
}

func TestWorktree_WorktreeDirCreated(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not installed")
	}

	repoDir := initTempGitRepo(t)

	out, err := runAgentJam("project", "create", "wt-dir-test",
		"--name", "Worktree Dir Test",
		"--root", repoDir)
	if err != nil {
		t.Fatalf("project create: %v\n%s", err, out)
	}

	out, err = runAgentJam("session", "start",
		"--driver", "mock",
		"--project", "wt-dir-test",
		"--worktree",
		"--detach")
	if err != nil {
		t.Fatalf("session start: %v\n%s", err, out)
	}
	id := extractSessionID(out)
	defer stopSession(t, id)

	waitForFile(filepath.Join(ajHome, "sessions", id+".pid"), 15*time.Second)
	time.Sleep(2 * time.Second)

	// The worktree should be under the worktrees directory.
	wtBase := filepath.Join(ajHome, "worktrees", "wt-dir-test")
	entries, err := os.ReadDir(wtBase)
	if err != nil {
		t.Fatalf("worktree base dir missing: %v", err)
	}
	if len(entries) == 0 {
		t.Error("worktree base dir is empty — no worktree created")
	}

	// Stop and verify worktree dir is cleaned.
	stopSession(t, id)
	time.Sleep(2 * time.Second)

	// The worktree dir itself may or may not be removed by git, but the
	// branch should be gone.
	if gitBranchExists(t, repoDir, "agent-*") {
		t.Error("worktree branch still exists after stop")
	}
}
