package vcs

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

// skipIfNoGit skips the test if git is not installed.
func skipIfNoGit(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not installed")
	}
}

// initBareRepo creates a git repo at dir with an initial commit on "main".
// The repo is configured with a test identity.
func initBareRepo(t *testing.T, dir string) {
	t.Helper()
	for _, args := range [][]string{
		{"init", "-b", "main", dir},
		{"-C", dir, "config", "user.email", "[email protected]"},
		{"-C", dir, "config", "user.name", "Test"},
	} {
		cmd := exec.Command("git", args...)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %s (%v)", args, out, err)
		}
	}
	// Create initial commit.
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("# test\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"-C", dir, "add", "."},
		{"-C", dir, "commit", "-m", "initial"},
	} {
		cmd := exec.Command("git", args...)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %s (%v)", args, out, err)
		}
	}
}

func TestGit_IsGitRepo(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	if !g.IsGitRepo(repoDir) {
		t.Fatal("expected IsGitRepo to return true for git repo")
	}

	// Non-repo directory.
	emptyDir := t.TempDir()
	if g.IsGitRepo(emptyDir) {
		t.Fatal("expected IsGitRepo to return false for non-repo dir")
	}
}

func TestGit_IsGitRepo_NonexistentDir(t *testing.T) {
	skipIfNoGit(t)
	g := New("")
	if g.IsGitRepo("/nonexistent/path/12345") {
		t.Fatal("expected false for nonexistent dir")
	}
}

func TestGit_CurrentBranch(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	branch, err := g.CurrentBranch(repoDir)
	if err != nil {
		t.Fatal(err)
	}
	if branch != "main" {
		t.Fatalf("expected branch 'main', got %q", branch)
	}
}

func TestGit_CreateWorktree(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	wtDir := filepath.Join(t.TempDir(), "worktree")

	wt, err := g.CreateWorktree(WorktreeSpec{
		RepoDir:     repoDir,
		Branch:      "agent-S-001/myrepo",
		WorktreeDir: wtDir,
	})
	if err != nil {
		t.Fatal(err)
	}

	// Worktree dir should exist with the file.
	if _, err := os.Stat(filepath.Join(wtDir, "README.md")); err != nil {
		t.Fatalf("worktree dir missing files: %v", err)
	}

	// Branch should exist in the main repo.
	if _, err := g.run(repoDir, "rev-parse", "--verify", "agent-S-001/myrepo"); err != nil {
		t.Fatalf("branch not found: %v", err)
	}

	if wt.Branch != "agent-S-001/myrepo" {
		t.Fatalf("expected branch agent-S-001/myrepo, got %q", wt.Branch)
	}
	if wt.BaseBranch != "main" {
		t.Fatalf("expected base branch main, got %q", wt.BaseBranch)
	}
}

func TestGit_CreateWorktree_ExplicitBase(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	// Create a feature branch.
	g := New("")
	if _, err := g.run(repoDir, "branch", "feature/v2"); err != nil {
		t.Fatal(err)
	}

	wtDir := filepath.Join(t.TempDir(), "worktree")
	wt, err := g.CreateWorktree(WorktreeSpec{
		RepoDir:     repoDir,
		Branch:      "agent-S-002/myrepo",
		WorktreeDir: wtDir,
		BaseBranch:  "feature/v2",
	})
	if err != nil {
		t.Fatal(err)
	}
	if wt.BaseBranch != "feature/v2" {
		t.Fatalf("expected base branch feature/v2, got %q", wt.BaseBranch)
	}
}

func TestGit_RemoveWorktree(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	wtDir := filepath.Join(t.TempDir(), "worktree")
	wt, err := g.CreateWorktree(WorktreeSpec{
		RepoDir:     repoDir,
		Branch:      "agent-S-003/myrepo",
		WorktreeDir: wtDir,
	})
	if err != nil {
		t.Fatal(err)
	}

	if err := g.RemoveWorktree(wt); err != nil {
		t.Fatal(err)
	}

	// Worktree dir should be gone.
	if _, err := os.Stat(wtDir); !os.IsNotExist(err) {
		t.Fatal("worktree dir should be removed")
	}
}

func TestGit_DeleteBranch(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	wtDir := filepath.Join(t.TempDir(), "worktree")
	wt, err := g.CreateWorktree(WorktreeSpec{
		RepoDir:     repoDir,
		Branch:      "agent-S-004/myrepo",
		WorktreeDir: wtDir,
	})
	if err != nil {
		t.Fatal(err)
	}

	// Remove worktree first (can't delete a checked-out branch).
	if err := g.RemoveWorktree(wt); err != nil {
		t.Fatal(err)
	}

	if err := g.DeleteBranch(repoDir, "agent-S-004/myrepo"); err != nil {
		t.Fatalf("DeleteBranch: %v", err)
	}

	// Branch should no longer exist.
	if _, err := g.run(repoDir, "rev-parse", "--verify", "agent-S-004/myrepo"); err == nil {
		t.Fatal("expected branch to be deleted")
	}
}

func TestGit_Cleanup(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	wtDir := filepath.Join(t.TempDir(), "worktree")
	wt, err := g.CreateWorktree(WorktreeSpec{
		RepoDir:     repoDir,
		Branch:      "agent-S-005/myrepo",
		WorktreeDir: wtDir,
	})
	if err != nil {
		t.Fatal(err)
	}

	if err := g.Cleanup(wt); err != nil {
		t.Fatalf("Cleanup: %v", err)
	}

	// Both worktree dir and branch should be gone.
	if _, err := os.Stat(wtDir); !os.IsNotExist(err) {
		t.Fatal("worktree dir should be removed after cleanup")
	}
	if _, err := g.run(repoDir, "rev-parse", "--verify", "agent-S-005/myrepo"); err == nil {
		t.Fatal("branch should be deleted after cleanup")
	}
}

func TestGit_Cleanup_NilSafe(t *testing.T) {
	skipIfNoGit(t)
	g := New("")
	if err := g.Cleanup(nil); err != nil {
		t.Fatalf("Cleanup(nil) should not error, got: %v", err)
	}
}

func TestGit_RemoveWorktree_AlreadyRemoved(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	wtDir := filepath.Join(t.TempDir(), "worktree")
	wt, err := g.CreateWorktree(WorktreeSpec{
		RepoDir:     repoDir,
		Branch:      "agent-S-006/myrepo",
		WorktreeDir: wtDir,
	})
	if err != nil {
		t.Fatal(err)
	}

	// Manually remove the dir first.
	os.RemoveAll(wtDir)

	// Should not panic or error.
	if err := g.RemoveWorktree(wt); err != nil {
		t.Fatalf("RemoveWorktree on already-removed dir should not error: %v", err)
	}
}

func TestGit_CreateWorktree_DirExists(t *testing.T) {
	skipIfNoGit(t)
	t.Parallel()

	repoDir := t.TempDir()
	initBareRepo(t, repoDir)

	g := New("")
	// Pre-create the worktree dir with a file inside — git refuses
	// worktree creation in non-empty directories.
	wtDir := filepath.Join(t.TempDir(), "worktree")
	if err := os.MkdirAll(wtDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(wtDir, "blocker.txt"), []byte("nope"), 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := g.CreateWorktree(WorktreeSpec{
		RepoDir:     repoDir,
		Branch:      "agent-S-007/myrepo",
		WorktreeDir: wtDir,
	})
	if err == nil {
		t.Fatal("expected error when worktree dir is non-empty")
	}
}
