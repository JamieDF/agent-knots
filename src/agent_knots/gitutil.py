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
from dataclasses import dataclass, field
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


def _parse_numstat(stdout: str) -> list[dict]:
    items = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, deleted, path = parts
            items.append({
                "path": path,
                "added": int(added) if added.isdigit() else 0,
                "deleted": int(deleted) if deleted.isdigit() else 0,
            })
    return items


def _git_untracked(repo: Path) -> list[str]:
    """Untracked, non-ignored files — exactly the set `git add -A` would
    pick up beyond tracked modifications."""
    result = _run_git(repo, ["ls-files", "--others", "--exclude-standard"])
    if result.returncode != 0:
        return []
    return [p for p in result.stdout.splitlines() if p.strip()]


def _git_diff_stat(repo: Path) -> list[dict]:
    """Per-file added/deleted line counts for uncommitted changes.

    Covers tracked modifications AND untracked (non-ignored) files.
    The untracked half matters more than it sounds: `git diff` ignores
    them entirely, but Review's approve runs `git add -A`, so leaving
    them out meant the most common thing an agent does — creating a new
    file — was invisible in review while still being committed by it.
    Reviewers could approve a change they were never shown. Filtering
    with --exclude-standard keeps this set exactly aligned with what
    `git add -A` would actually stage.
    """
    items = _parse_numstat(_run_git(repo, ["diff", "--numstat"]).stdout)
    for path in _git_untracked(repo):
        # --no-index against /dev/null gives the added-line count, and
        # reports "-" for binary the same way a tracked diff would.
        # It exits 1 whenever there *is* a difference, so returncode
        # can't be used as a failure signal here.
        stat = _parse_numstat(
            _run_git(repo, ["diff", "--no-index", "--numstat", "--", "/dev/null", path]).stdout,
        )
        items.append({
            "path": path,
            "added": stat[0]["added"] if stat else 0,
            "deleted": 0,
        })
    return items


def _git_diff_for_file(repo: Path, path: str) -> str:
    """Unified diff for one uncommitted file.

    Falls back to a --no-index diff against /dev/null for untracked
    files, which plain `git diff` renders as empty — the reviewer needs
    to see the contents of a file approve is about to commit.
    """
    diff = _run_git(repo, ["diff", "--", path]).stdout
    if diff.strip():
        return diff
    if path in _git_untracked(repo):
        return _run_git(repo, ["diff", "--no-index", "--", "/dev/null", path]).stdout
    return diff


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


# ── managed workspace clones ─────────────────────────────────────────────────

# A clone pulls a whole history over the network; _BRANCH_TIMEOUT is
# nowhere near enough. A push is network-bound too, but bounded by the
# size of one branch rather than the entire repo.
_CLONE_TIMEOUT = 600
_PUSH_TIMEOUT = 120

_REMOTE_URL_PREFIXES = ("https://", "http://", "ssh://", "git://", "git@")


def is_remote_url(source: str) -> bool:
    """True if `source` looks like something to clone over the network
    rather than a path on disk."""
    return source.strip().startswith(_REMOTE_URL_PREFIXES)


def repo_name_from_source(source: str, fallback: str) -> str:
    """Derive a directory name from a clone source.

    Both URL and local-path forms reduce to their last segment with any
    .git suffix removed: ".../owner/repo.git" and "/home/me/repo" both
    give "repo". Anything that doesn't reduce to a usable directory name
    (empty source, "/", a bare host) gives `fallback` — the caller
    passes the workspace slug, which is already unique.
    """
    text = source.strip().rstrip("/")
    if not text:
        return fallback
    # Works for both separators: an scp-style "git@host:owner/repo" ends
    # in a /-segment too, and a Windows-ish path can't reach here.
    segment = text.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if segment.endswith(".git"):
        segment = segment[:-4]
    segment = re.sub(r"[^A-Za-z0-9._-]+", "-", segment).strip("-.")
    return segment or fallback


def unique_clone_dir(root: Path, repo_name: str) -> Path:
    """Pick a not-yet-taken directory under `root` for a managed clone.

    Same -2/-3 suffix loop as the workspace-id slugifier, but deduping
    against directories on disk rather than project ids: the folder is
    named after the *repo*, and two different workspaces can
    legitimately want the same repo name (two forks, or the same repo
    attached twice).

    Lives here rather than in the web routes so the CLI can create a
    managed workspace too, without importing from the web layer.
    """
    candidate = root / repo_name
    n = 2
    while candidate.exists():
        candidate = root / f"{repo_name}-{n}"
        n += 1
    return candidate


def remote_url(repo: Path, name: str = "origin") -> str | None:
    """URL of a named remote, or None if it isn't configured."""
    result = _run_git(repo, ["remote", "get-url", name])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@dataclass
class CloneResult:
    path: str = ""
    failed_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_reason


def clone_into(source: str, dest: Path) -> CloneResult:
    """Clone `source` into `dest`, which must not already exist.

    Never raises — every failure returns a CloneResult carrying
    failed_reason, so the caller can surface git's own words rather than
    a stack trace.

    Cloning from a local path is the fast, offline case, but it leaves
    `origin` pointing at that local checkout, so a later push would push
    back into the user's own repo instead of upstream. When the source
    has an origin of its own we adopt it and demote the local path to a
    `local` remote; when it has none (a repo that only ever existed on
    this machine) origin stays pointing at the source, which is then the
    only correct answer.
    """
    try:
        if dest.exists() and any(dest.iterdir()):
            return CloneResult(failed_reason=f"{dest} already exists and is not empty")

        dest.parent.mkdir(parents=True, exist_ok=True)
        local_source = None if is_remote_url(source) else Path(source).expanduser()
        if local_source is not None:
            if not local_source.exists():
                return CloneResult(failed_reason=f"{local_source} does not exist")
            if not is_repo(local_source):
                return CloneResult(failed_reason=f"{local_source} is not a git repository")
            source = str(local_source)

        result = subprocess.run(
            ["git", "clone", source, str(dest)],
            capture_output=True, text=True, timeout=_CLONE_TIMEOUT,
        )
        if result.returncode != 0:
            return CloneResult(failed_reason=result.stderr.strip() or "git clone failed")

        if local_source is not None:
            upstream = remote_url(local_source)
            if upstream:
                _run_git(dest, ["remote", "set-url", "origin", upstream])
                _run_git(dest, ["remote", "add", "local", str(local_source)])

        return CloneResult(path=str(dest))
    except subprocess.TimeoutExpired:
        return CloneResult(failed_reason=f"git clone timed out after {_CLONE_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as e:
        return CloneResult(failed_reason=f"git unavailable: {e}")


async def clone_into_async(source: str, dest: Path) -> CloneResult:
    """clone_into off the event loop — see ensure_session_branch_async."""
    return await asyncio.to_thread(clone_into, source, dest)


def init_repo(path: Path) -> bool:
    """`git init` an existing directory. True on success.

    Only used for a managed workspace created empty, where git is
    optional — Review and the task workflow both work without it.
    """
    try:
        return _run_git(path, ["init"]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@dataclass
class PushResult:
    branch: str = ""
    remote: str = ""
    failed_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_reason


def push_branch(repo: Path, name: str, remote: str = "origin") -> PushResult:
    """Push `name` to `remote`, setting upstream. Never raises."""
    try:
        if not is_repo(repo):
            return PushResult(failed_reason="not a git repository")
        if not branch_exists(repo, name):
            return PushResult(failed_reason=f"branch {name!r} does not exist")
        if remote_url(repo, remote) is None:
            return PushResult(failed_reason=f"no {remote!r} remote configured")

        result = _run_git(
            repo, ["push", "--set-upstream", remote, name], timeout=_PUSH_TIMEOUT,
        )
        if result.returncode != 0:
            return PushResult(failed_reason=result.stderr.strip() or "git push failed")
        return PushResult(branch=name, remote=remote)
    except subprocess.TimeoutExpired:
        return PushResult(failed_reason=f"git push timed out after {_PUSH_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as e:
        return PushResult(failed_reason=f"git unavailable: {e}")


async def push_branch_async(repo: Path, name: str, remote: str = "origin") -> PushResult:
    """push_branch off the event loop."""
    return await asyncio.to_thread(push_branch, repo, name, remote)


@dataclass
class MergeResult:
    branch: str = ""
    into: str = ""
    commits: int = 0
    conflicts: list[str] = field(default_factory=list)
    failed_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_reason


def _conflicted_files(repo: Path) -> list[str]:
    result = _run_git(repo, ["diff", "--name-only", "--diff-filter=U"])
    return [p for p in result.stdout.splitlines() if p.strip()]


def merge_branch(repo: Path, branch: str, into: str) -> MergeResult:
    """Merge `branch` into `into`, leaving HEAD on `into`. Never raises.

    Every refusal happens *before* anything is modified, and the one
    that can't — a conflict, which git only discovers mid-merge — is
    unwound with `merge --abort`. A half-merged working tree is far
    worse than a failed action: it strands the repo in a state the user
    didn't ask for and has to resolve by hand, possibly while an agent
    is about to wake up in it.

    Note this moves HEAD, so callers must ensure no live session owns
    the working directory (SessionManager._repo_writers). That check
    can't live here — gitutil is deliberately below the session layer.
    """
    try:
        if not is_repo(repo):
            return MergeResult(failed_reason="not a git repository")
        if not branch_exists(repo, branch):
            return MergeResult(failed_reason=f"branch {branch!r} does not exist")
        if not branch_exists(repo, into):
            return MergeResult(failed_reason=f"branch {into!r} does not exist")
        if branch == into:
            return MergeResult(failed_reason="cannot merge a branch into itself")

        # Uncommitted work would be carried onto `into` by the checkout
        # below and swept into someone else's history.
        if is_dirty(repo):
            return MergeResult(
                failed_reason="working tree has uncommitted changes — commit or discard them first",
            )

        ahead = commits_ahead(repo, branch, into)
        if ahead == 0:
            return MergeResult(
                branch=branch, into=into,
                failed_reason=f"{branch!r} has nothing that {into!r} doesn't already have",
            )
        if ahead < 0:
            return MergeResult(failed_reason="could not compare the branches")

        original = current_branch(repo)
        if _run_git(repo, ["checkout", into], timeout=_BRANCH_TIMEOUT).returncode != 0:
            return MergeResult(failed_reason=f"could not check out {into!r}")

        result = _run_git(
            repo,
            ["merge", "--no-ff", "-m", f"Merge {branch} into {into}", branch],
            timeout=_BRANCH_TIMEOUT,
        )
        if result.returncode != 0:
            conflicts = _conflicted_files(repo)
            _run_git(repo, ["merge", "--abort"], timeout=_BRANCH_TIMEOUT)
            # Put HEAD back where it was, so a refused merge leaves the
            # repo exactly as it found it.
            if original and original != into:
                _run_git(repo, ["checkout", original], timeout=_BRANCH_TIMEOUT)
            reason = (
                f"merge conflicts in: {', '.join(conflicts)}" if conflicts
                else (result.stderr.strip() or "git merge failed")
            )
            return MergeResult(branch=branch, into=into, conflicts=conflicts, failed_reason=reason)

        return MergeResult(branch=branch, into=into, commits=ahead)
    except subprocess.TimeoutExpired:
        return MergeResult(failed_reason=f"git merge timed out after {_BRANCH_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as e:
        return MergeResult(failed_reason=f"git unavailable: {e}")


async def merge_branch_async(repo: Path, branch: str, into: str) -> MergeResult:
    """merge_branch off the event loop."""
    return await asyncio.to_thread(merge_branch, repo, branch, into)


def gh_available() -> bool:
    """Whether the GitHub CLI is installed and authenticated.

    Surfaced to the UI so the pull-request option can be disabled rather
    than offered and then failing at the one moment a user expects work
    to be published. `gh auth status` exits non-zero when unauthenticated,
    which is the distinction that matters — installed-but-logged-out is
    just as unusable as absent.
    """
    try:
        return subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=10,
        ).returncode == 0
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return False


@dataclass
class PullRequestResult:
    url: str = ""
    failed_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_reason


def open_pull_request(
    repo: Path, branch: str, base: str, title: str, body: str = "",
) -> PullRequestResult:
    """Open a PR for `branch` against `base` using the `gh` CLI.

    Shelling out rather than calling the GitHub API keeps agent-knots
    free of token storage, OAuth and outbound HTTP of its own, and
    inherits enterprise GitHub, SSO and token refresh from a tool that
    already solves them. Same call shape as _run_git: list-form args, no
    shell=True, returncode inspected rather than trusted.

    A missing or unauthenticated `gh` is reported as such — the one
    failure a user can actually act on, and one that a bare non-zero
    exit would bury.
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--head", branch, "--base", base,
                "--title", title or branch,
                "--body", body or "",
            ],
            cwd=str(repo), capture_output=True, text=True, timeout=_PUSH_TIMEOUT,
        )
    except FileNotFoundError:
        return PullRequestResult(
            failed_reason="the GitHub CLI (`gh`) isn't installed — install it, or "
                          "set this workspace to merge locally instead",
        )
    except subprocess.TimeoutExpired:
        return PullRequestResult(failed_reason=f"gh pr create timed out after {_PUSH_TIMEOUT}s")
    except OSError as e:
        return PullRequestResult(failed_reason=f"gh unavailable: {e}")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "auth login" in stderr or "not logged" in stderr.lower():
            return PullRequestResult(
                failed_reason="the GitHub CLI isn't authenticated — run `gh auth login`",
            )
        return PullRequestResult(failed_reason=stderr or "gh pr create failed")

    # gh prints the PR URL on stdout; take the last URL-looking line so a
    # leading notice doesn't get mistaken for it.
    lines = [ln.strip() for ln in reversed(result.stdout.splitlines())]
    url = next((ln for ln in lines if ln.startswith("http")), "")
    return PullRequestResult(url=url)


async def open_pull_request_async(
    repo: Path, branch: str, base: str, title: str, body: str = "",
) -> PullRequestResult:
    """open_pull_request off the event loop."""
    return await asyncio.to_thread(open_pull_request, repo, branch, base, title, body)


def ahead_of_remote(repo: Path, branch: str, remote: str = "origin") -> int:
    """How many commits `branch` has that `remote/branch` doesn't.

    A local merge leaves the base branch ahead only locally — nothing
    pushes it. Surfacing that is what stops "merged" being mistaken for
    "in the remote mainline". -1 when there's no remote-tracking ref to
    compare against, which is the normal case for a repo with no remote
    and is not an error.
    """
    if remote_url(repo, remote) is None:
        return -1
    ref = f"{remote}/{branch}"
    if _run_git(repo, ["rev-parse", "--verify", "--quiet", ref]).returncode != 0:
        return -1
    return commits_ahead(repo, branch, ref)


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
