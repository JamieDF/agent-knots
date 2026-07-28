"""Git helpers shared by the review/filesystem-browse routers and the
session manager's per-session branch handling.

Lives at the package root rather than under cockpit/web/ because
session/manager.py needs it too, and importing from the web layer into
the session layer would invert the dependency direction.
"""

import asyncio
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Branch operations (checkout in particular) can take appreciably longer
# than the read-only queries _run_git's default covers — a checkout that
# rewrites a large working tree blows straight through 10s.
_BRANCH_TIMEOUT = 30


def _run_git(repo: Path, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a git command scoped to a workspace repo the user configured
    themselves (Project.repository) — never an arbitrary path, never
    shell=True (no injection risk from list-form subprocess args).

    Deliberately no check=True: callers inspect returncode/stderr and
    decide for themselves, since most git "failures" here (not a repo,
    branch already exists) are expected conditions rather than errors.
    """
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout,
    )


def _git_diff_stat(repo: Path) -> list[dict]:
    """Per-file added/deleted line counts for uncommitted changes."""
    result = _run_git(repo, ["diff", "--numstat"])
    items = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, deleted, path = parts
            items.append({
                "path": path,
                "added": int(added) if added.isdigit() else 0,
                "deleted": int(deleted) if deleted.isdigit() else 0,
            })
    return items


def _git_diff_for_file(repo: Path, path: str) -> str:
    return _run_git(repo, ["diff", "--", path]).stdout


def _github_url_from_remote(remote_url: str) -> str | None:
    """Best-effort parse of a git remote URL into a browsable
    https://github.com/owner/repo link, covering the SSH, ssh://, and
    HTTPS forms `git remote get-url origin` can return."""
    url = remote_url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    for pattern in (r"^git@github\.com:(.+)$", r"^ssh://git@github\.com/(.+)$", r"^https?://github\.com/(.+)$"):
        m = re.match(pattern, url)
        if m:
            return f"https://github.com/{m.group(1)}"
    return None


# ── per-session branches ─────────────────────────────────────────────────────


def is_repo(repo: Path) -> bool:
    """True if repo is inside a git working tree."""
    try:
        return _run_git(repo, ["rev-parse", "--git-dir"]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def current_branch(repo: Path) -> str | None:
    """Name of the checked-out branch, or None if detached/unavailable.

    Detached HEAD reports the literal string "HEAD", which is not a
    branch name — callers need to tell those apart, hence None.
    """
    result = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return None if name in ("", "HEAD") else name


def is_dirty(repo: Path) -> bool:
    """True if the working tree has uncommitted changes."""
    result = _run_git(repo, ["status", "--porcelain"])
    return result.returncode == 0 and bool(result.stdout.strip())


def branch_exists(repo: Path, name: str) -> bool:
    return _run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"]).returncode == 0


def commits_ahead(repo: Path, name: str, base: str) -> int:
    """How many commits `name` has that `base` does not. -1 if unknown.

    -1 rather than 0 on failure matters: callers use "is this zero?" to
    decide a branch is safe to delete, and an unanswerable question must
    never read as "yes, safe".
    """
    result = _run_git(repo, ["rev-list", "--count", f"{base}..{name}"])
    if result.returncode != 0:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def _slugify(text: str, max_len: int = 40) -> str:
    """Lowercase, punctuation-free, hyphen-separated. Falls back to
    'task' for a blank/symbols-only title rather than an empty slug."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "task"


def session_branch_name(task_id: str | None, task_title: str, session_id: str) -> str:
    """Branch name for a session — task-scoped, not session-scoped.

    Deliberately keyed on the *task*, not the session: sessions aren't
    persisted anywhere, so resuming a task later means starting a brand
    new session, and it must land back on the same branch (same
    uncommitted changes, same history) rather than a fresh one off base
    that orphans whatever the previous session left behind.

    Derived from the task's title (readable — "knots/fix-login-bug-a1b2c3"
    beats an opaque id) plus a short hash of the task id for uniqueness,
    since titles aren't unique (two tasks can share one, or both be
    blank) but ids always are.
    """
    if not task_id:
        return f"knots/session-{session_id}"
    short_id = hashlib.sha1(task_id.encode()).hexdigest()[:6]
    return f"knots/{_slugify(task_title)}-{short_id}"


@dataclass
class BranchResult:
    """Outcome of ensure_session_branch. skipped_reason set = no branch."""
    name: str | None = None
    created: bool = False
    base: str = ""
    skipped_reason: str | None = None


def ensure_session_branch(repo: Path, name: str, base: str) -> BranchResult:
    """Check out `name`, creating it from `base` if it doesn't exist.

    Never raises — every failure path returns a BranchResult carrying a
    skipped_reason instead, because a git problem must not stop an agent
    session from starting.

    A dirty working tree is deliberately NOT a skip condition: `git
    checkout -b` carries uncommitted changes onto the new branch, which
    is git's own behaviour and loses nothing. Only if git itself refuses
    (the checkout would clobber something) do we skip.
    """
    try:
        if not is_repo(repo):
            return BranchResult(skipped_reason="not a git repository")

        if branch_exists(repo, name):
            result = _run_git(repo, ["checkout", name], timeout=_BRANCH_TIMEOUT)
            if result.returncode != 0:
                return BranchResult(skipped_reason=f"checkout failed: {result.stderr.strip()}")
            return BranchResult(name=name, created=False, base=base)

        result = _run_git(repo, ["checkout", "-b", name, base], timeout=_BRANCH_TIMEOUT)
        if result.returncode != 0:
            return BranchResult(skipped_reason=f"branch create failed: {result.stderr.strip()}")
        return BranchResult(name=name, created=True, base=base)
    except (OSError, subprocess.SubprocessError) as e:
        return BranchResult(skipped_reason=f"git unavailable: {e}")


async def ensure_session_branch_async(repo: Path, name: str, base: str) -> BranchResult:
    """ensure_session_branch off the event loop.

    _run_git is synchronous, so calling it directly from async session
    startup would stall every other request for the full timeout.
    """
    return await asyncio.to_thread(ensure_session_branch, repo, name, base)


def delete_branch_if_empty(repo: Path, name: str, base: str) -> bool:
    """Delete `name` if it has no commits beyond `base` AND a clean
    working tree. True if deleted.

    The dirty-tree check matters: commits currently only happen via the
    Review screen's Approve action, so a session that's done real,
    uncommitted work still has zero commits ahead of base. Without also
    checking is_dirty, this would call the branch "empty", delete it,
    and checkout base — which carries the uncommitted changes along
    with it (git's own checkout semantics), landing an unreviewed
    agent's work on base's working tree instead of keeping it isolated.

    Never raises. Uses `branch -d` (safe delete) rather than -D, and
    bails without deleting if the base can't be checked out first —
    leaving HEAD somewhere unexpected would be worse than an extra
    branch lying around.
    """
    try:
        if commits_ahead(repo, name, base) != 0:
            return False
        if is_dirty(repo):
            return False
        if _run_git(repo, ["checkout", base], timeout=_BRANCH_TIMEOUT).returncode != 0:
            return False
        return _run_git(repo, ["branch", "-d", name], timeout=_BRANCH_TIMEOUT).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


async def delete_branch_if_empty_async(repo: Path, name: str, base: str) -> bool:
    return await asyncio.to_thread(delete_branch_if_empty, repo, name, base)


def delete_branch_force(repo: Path, name: str, base: str) -> bool:
    """Delete `name` unconditionally — regardless of commits or a dirty
    tree. True if deleted.

    Unlike delete_branch_if_empty, this is an explicit "yes, really get
    rid of it" action (wastebin cleanup only) — never called
    automatically. Still never raises, and still checks out base first
    for the same reason: leaving HEAD somewhere unexpected is worse
    than a branch that didn't get deleted.
    """
    try:
        if _run_git(repo, ["checkout", base], timeout=_BRANCH_TIMEOUT).returncode != 0:
            return False
        return _run_git(repo, ["branch", "-D", name], timeout=_BRANCH_TIMEOUT).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


async def delete_branch_force_async(repo: Path, name: str, base: str) -> bool:
    return await asyncio.to_thread(delete_branch_force, repo, name, base)
