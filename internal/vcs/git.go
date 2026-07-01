// Package vcs provides git operations for per-session worktree management.
//
// When a session starts (especially in container mode), each repo in the
// project gets its own git worktree on a dedicated branch. This isolates
// the agent's changes from the main working copy. On session cleanup, the
// worktrees are removed and the branches deleted.
//
// Operations are implemented by shelling out to the `git` binary. This keeps
// the dependency surface small — every developer already has git installed.
package vcs

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Git wraps the git binary for worktree operations.
type Git struct {
	bin string // path to git binary (default: looked up from PATH)
}

// New creates a Git helper. If bin is empty, "git" is resolved from PATH
// on first use.
func New(bin string) *Git {
	return &Git{bin: bin}
}

// Worktree describes a worktree created by CreateWorktree.
type Worktree struct {
	// RepoDir is the path to the main repository (contains .git).
	RepoDir string

	// Branch is the branch name created for this worktree.
	Branch string

	// WorktreeDir is the path to the worktree working directory.
	WorktreeDir string

	// BaseBranch is the branch the worktree was created from.
	BaseBranch string
}

// IsGitRepo reports whether dir is inside a git repository (i.e. `git
// rev-parse --git-dir` succeeds when run from dir).
func (g *Git) IsGitRepo(dir string) bool {
	_, err := g.run(dir, "rev-parse", "--git-dir")
	return err == nil
}

// CurrentBranch returns the current branch name in dir, or an error if dir
// is not a git repo or is in detached HEAD state.
func (g *Git) CurrentBranch(dir string) (string, error) {
	out, err := g.run(dir, "rev-parse", "--abbrev-ref", "HEAD")
	if err != nil {
		return "", fmt.Errorf("current branch in %q: %w", dir, err)
	}
	name := strings.TrimSpace(out)
	if name == "HEAD" {
		return "", fmt.Errorf("repo %q is in detached HEAD state", dir)
	}
	return name, nil
}

// CreateWorktree creates a new worktree at spec.WorktreeDir on a new branch
// spec.Branch, starting from spec.BaseBranch (or the current HEAD if empty).
//
// The main repository must already exist at spec.RepoDir. The parent
// directory of spec.WorktreeDir must exist; WorktreeDir itself must not.
func (g *Git) CreateWorktree(spec WorktreeSpec) (*Worktree, error) {
	if spec.RepoDir == "" {
		return nil, fmt.Errorf("vcs: RepoDir is required")
	}
	if spec.Branch == "" {
		return nil, fmt.Errorf("vcs: Branch is required")
	}
	if spec.WorktreeDir == "" {
		return nil, fmt.Errorf("vcs: WorktreeDir is required")
	}

	// Resolve base branch: explicit > current HEAD.
	base := spec.BaseBranch
	if base == "" {
		var err error
		base, err = g.CurrentBranch(spec.RepoDir)
		if err != nil {
			return nil, err
		}
	}

	// Ensure parent dir exists.
	parent := filepath.Dir(spec.WorktreeDir)
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return nil, fmt.Errorf("vcs: create parent dir %q: %w", parent, err)
	}

	// git worktree add -b <branch> <worktree-dir> <base>
	if _, err := g.run(spec.RepoDir,
		"worktree", "add", "-b", spec.Branch, spec.WorktreeDir, base,
	); err != nil {
		return nil, fmt.Errorf("vcs: worktree add %q from %q: %w",
			spec.WorktreeDir, spec.RepoDir, err)
	}

	return &Worktree{
		RepoDir:     spec.RepoDir,
		Branch:      spec.Branch,
		WorktreeDir: spec.WorktreeDir,
		BaseBranch:  base,
	}, nil
}

// RemoveWorktree removes a worktree from its parent repository. Uses --force
// to handle cases where there are untracked files.
func (g *Git) RemoveWorktree(wt *Worktree) error {
	if wt == nil || wt.WorktreeDir == "" {
		return nil
	}
	// Run from the repo dir; git resolves the worktree path.
	_, err := g.run(wt.RepoDir,
		"worktree", "remove", "--force", wt.WorktreeDir,
	)
	if err != nil {
		// Fallback: if the worktree dir was already removed manually,
		// prune stale entries.
		_, _ = g.run(wt.RepoDir, "worktree", "prune")
	}
	return nil
}

// DeleteBranch removes a branch from the repository. Uses -D (force) since
// session branches are ephemeral and may contain unmerged work.
func (g *Git) DeleteBranch(repoDir, branch string) error {
	if branch == "" {
		return nil
	}
	_, err := g.run(repoDir, "branch", "-D", branch)
	if err != nil {
		return fmt.Errorf("vcs: delete branch %q in %q: %w", branch, repoDir, err)
	}
	return nil
}

// Cleanup removes the worktree and deletes its branch. Errors are collected
// but do not stop cleanup — we want to remove as much as possible.
func (g *Git) Cleanup(wt *Worktree) error {
	if wt == nil {
		return nil
	}
	var errs []error
	if err := g.RemoveWorktree(wt); err != nil {
		errs = append(errs, err)
	}
	if err := g.DeleteBranch(wt.RepoDir, wt.Branch); err != nil {
		errs = append(errs, err)
	}
	if len(errs) > 0 {
		return fmt.Errorf("vcs cleanup: %v", errs)
	}
	return nil
}

// WorktreeSpec describes a worktree to create.
type WorktreeSpec struct {
	RepoDir     string // path to the main repo (has .git)
	Branch      string // new branch name
	WorktreeDir string // where to create the worktree
	BaseBranch  string // branch to start from (default: current HEAD)
}

// bin returns the git binary path, resolving "git" from PATH on first call.
func (g *Git) binPath() string {
	if g.bin != "" {
		return g.bin
	}
	return "git"
}

// run executes a git command in dir and returns trimmed stdout.
func (g *Git) run(dir string, args ...string) (string, error) {
	cmd := exec.Command(g.binPath(), args...)
	if dir != "" {
		cmd.Dir = dir
	}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("%s: %s", err, strings.TrimSpace(string(out)))
	}
	return string(out), nil
}
