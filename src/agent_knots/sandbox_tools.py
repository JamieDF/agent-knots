"""Sandbox-aware tools that run inside the workspace directory.

When an agent session has a workspace, shell and editor tools default
their cwd to that directory and run under basic resource limits.

IMPORTANT: this is *not* a security boundary. Commands run via a real
shell (`shell=True`), so `cd /`, absolute paths, `curl`, `rm -rf /`, env
tricks, etc. are not blocked — only the starting directory and resource
usage are bounded. Genuine containment (filesystem/network isolation
against an adversarial agent) needs the container runtime tracked in
docs/decisions/004-container-isolation.md and the roadmap; it isn't
built yet. Path confinement for the editor tool (below) is real, since
that's plain path resolution rather than an arbitrary shell command.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable

from strands.tools import tool as _tool_dec

try:
    import resource
    HAS_RESOURCE = True
except ImportError:  # Windows
    HAS_RESOURCE = False


def _resolve(root: str, path: str) -> str:
    """Resolve a path relative to the workspace root. Refuse traversal."""
    resolved = (Path(root) / path).resolve()
    if not str(resolved).startswith(str(Path(root).resolve())):
        raise ValueError(f"Path {path!r} is outside the workspace")
    return str(resolved)


def _resource_preexec(timeout: int):
    """Build a preexec_fn that puts the child in its own process group and
    applies a best-effort CPU cap. Runs in the child after fork.

    This used to also cap RLIMIT_AS (virtual address space) as a memory
    guard, but that limits reserved address space, not actual physical
    memory used — and modern runtimes reserve huge virtual ranges
    upfront regardless of real usage (V8/Node reserves a multi-GB
    "sandbox" region for its pointer-compression tables at startup).
    Any RLIMIT_AS cap small enough to matter (e.g. 512MB) makes Node
    crash immediately with "Fatal process out of memory:
    SegmentedTable::InitializeTable" before running a single line of JS
    — so every npm/vite/webpack command an agent tries fails outright.
    RLIMIT_AS just isn't the right lever for this; real RSS containment
    needs cgroups, which is a bigger, separate piece of work (see the
    container-isolation decision doc referenced in the module docstring).
    """

    def _preexec() -> None:
        if hasattr(os, "setsid"):
            os.setsid()
        if HAS_RESOURCE:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
            except (ValueError, OSError):
                pass

    return _preexec


def run_confined(
    command: str, cwd: str | None, timeout: int = 60,
    max_output: int | None = None, env: dict[str, str] | None = None,
) -> dict:
    """Run a shell command with basic resource limits and full process-tree
    cleanup on timeout. See module docstring — this bounds resource usage
    and guarantees no orphaned children, but does not confine what paths
    the command can touch.

    Args:
        max_output: If set, stdout/stderr are each truncated to this many
            characters (with a note appended) before returning — protects
            against a runaway command flooding the agent's context with
            output, not a hard OS-level cap on what the process can write.
        env: Extra environment variables (e.g. injected vault
            credentials) merged on top of the current process's own
            environment — never a bare replacement, since that would
            drop PATH and break every command. Any value in here is
            scrubbed out of stdout/stderr before they're returned (see
            scrub_secrets), so an `env` or an accidental `echo $VAR`
            can't leak a credential into the agent's context.
    """
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd or None, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, **env} if env else None,
            preexec_fn=_resource_preexec(timeout) if hasattr(os, "setsid") else None,
        )
    except Exception as e:
        return {"error": scrub_secrets(str(e), env)}

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return {
            "stdout": _truncate(scrub_secrets(stdout, env), max_output),
            "stderr": _truncate(scrub_secrets(stderr, env), max_output),
            "exit_code": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        return {
            "error": f"Command timed out ({timeout}s)",
            "stdout": _truncate(scrub_secrets(stdout, env), max_output),
            "stderr": _truncate(scrub_secrets(stderr, env), max_output),
        }
    except Exception as e:
        _kill_process_tree(proc)
        return {"error": scrub_secrets(str(e), env)}


def scrub_secrets(text: str, env: dict[str, str] | None) -> str:
    """Replace any occurrence of an injected credential's value in text
    with a placeholder naming the env var it came from — applied to
    tool output before it's truncated (truncating first could split a
    secret across the cut, defeating the match) and before it reaches
    the agent's context / session history / SSE stream.

    Values under 8 characters are skipped: a short secret risks matching
    harmless substrings of ordinary output (a line number, a file size,
    part of an unrelated hash), which would scrub innocuous text and
    make the output actively misleading rather than protective.

    This only covers what comes back through this tool call — it can't
    stop an agent writing a credential to a file via the editor tool and
    reading it back some other way. That gap is accepted, not fixed
    here.
    """
    if not env or not text:
        return text
    for name, value in env.items():
        if len(value) >= 8 and value in text:
            text = text.replace(value, f"[redacted:{name}]")
    return text


def _truncate(text: str, limit: int | None) -> str:
    if not limit or len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more characters]"


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill the whole process group the command spawned, not just the shell."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
            return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_background(
    command: str, cwd: str | None, session_id: str = "",
    env: dict[str, str] | None = None,
) -> dict:
    """Start a command detached from the tool call, for anything meant to
    outlive a single turn — dev servers, watchers, long builds.

    Unlike run_confined(), this never waits for the process and is never
    subject to the timeout-kill: it returns as soon as the process has
    been spawned. Without this, an agent's only way to keep something
    running past the tool call is to hand-roll `nohup cmd &` itself,
    which is exactly the kind of thing agents got stuck fumbling with
    (wrong redirect, forgot disown, still got reaped) before this
    existed — so it's a first-class option instead of a shell trick the
    agent has to reinvent every time.

    stdout/stderr are redirected to a log file (path returned) rather
    than captured in memory, since there's no point in the call where
    we'd ever read them back — the process is still running when this
    returns. Unlike run_confined, that log file is NOT scrubbed of
    injected credential values — there's no output here to scrub at
    return time. A dev server that logs a credential it was started
    with will have it sitting in that file; reading the file back
    through the shell tool later scrubs it at that point, same as any
    other command output.

    Args:
        env: Extra environment variables merged on top of the current
            process's own environment, same convention as run_confined.
    """
    log_path = os.path.join(
        tempfile.gettempdir(), f"agent-knots-bg-{session_id or 'session'}-{uuid.uuid4().hex[:8]}.log"
    )
    try:
        with open(log_path, "wb") as log_file:
            proc = subprocess.Popen(
                command, shell=True, cwd=cwd or None,
                stdout=log_file, stderr=subprocess.STDOUT,
                env={**os.environ, **env} if env else None,
                preexec_fn=(lambda: os.setsid()) if hasattr(os, "setsid") else None,
            )
    except Exception as e:
        return {"error": scrub_secrets(str(e), env)}

    return {
        "pid": proc.pid,
        "log_file": log_path,
        "status": (
            f"Started in the background (pid {proc.pid}) — it keeps running after "
            f"this tool call returns and is not killed by any timeout. Check its "
            f"output with a normal command (e.g. `tail -n 50 {log_path}`), check "
            f"whether it's still alive with `kill -0 {proc.pid}`, and stop it with "
            f"`kill {proc.pid}` when you're done with it."
        ),
    }


def kill_background_process(pid: int) -> None:
    """Best-effort kill of a background process group by PID, for session
    teardown — mirrors _kill_process_tree but works from a bare pid
    instead of a live Popen handle, since background processes outlive
    the tool call that started them.

    Also reaps the pid afterward: run_background() never calls
    Popen.wait() (the whole point is not waiting on it), so a killed
    background process would otherwise sit around as a zombie until this
    process exits.
    """
    try:
        if hasattr(os, "killpg"):
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass


def make_sandboxed_shell(
    workspace: str, max_output: int = 1 << 20,
    session_id: str = "", background_pids: list[int] | None = None,
    env_provider: Callable[[], dict[str, str]] | None = None,
):
    """Create a shell tool that defaults cwd to the workspace directory.

    background_pids, if given, gets appended to whenever the agent starts
    a background=true command — lets the caller (SessionManager) track
    and clean these up when the session ends, since they'd otherwise
    outlive it indefinitely.

    env_provider, if given, is called fresh on every invocation rather
    than resolved once and captured — so a vault unlocked after the
    session started still takes effect on the next command, and no
    credential plaintext sits captured in this closure for the whole
    session's lifetime.
    """

    @_tool_dec(description=(
        "Run a shell command with cwd defaulted to the workspace root. Not a "
        "security sandbox — see module docs. Commands are killed if they "
        "haven't finished within the timeout — pass background=true for "
        "anything meant to keep running past this tool call (dev servers, "
        "watchers, long builds); it starts detached, is never killed by the "
        "timeout, and returns immediately with its pid and a log file path."
    ))
    def shell_tool(command: str, background: bool = False) -> dict:
        """Run a shell command with cwd defaulted to the workspace root.

        Args:
            command: The shell command to run.
            background: If true, start it detached and return immediately
                instead of waiting for it to finish — use this for dev
                servers or anything else meant to outlive this tool call.
        """
        env = env_provider() if env_provider else None
        if background:
            result = run_background(command, cwd=workspace, session_id=session_id, env=env)
            if background_pids is not None and "pid" in result:
                background_pids.append(result["pid"])
            return result
        return run_confined(command, cwd=workspace, max_output=max_output, env=env)

    return shell_tool


def make_sandboxed_editor(workspace: str, max_file_size: int = 10 << 20):
    """Create an editor tool confined to the workspace directory."""

    @_tool_dec(description="Read or write files inside the workspace. Paths are relative to workspace root.")
    def editor_tool(path: str, content: str = "", action: str = "read") -> dict:
        """Read or write a file in the workspace.

        Args:
            path: File path (relative to workspace root).
            content: Content to write (for 'write' action).
            action: 'read', 'write', or 'list'.

        Returns:
            File contents, status, or directory listing.
        """
        try:
            resolved = _resolve(workspace, path)
        except ValueError as e:
            return {"error": str(e)}

        if action == "read":
            try:
                return {"content": Path(resolved).read_text()}
            except FileNotFoundError:
                return {"error": f"File not found: {path}"}
            except Exception as e:
                return {"error": str(e)}

        if action == "write":
            size = len(content.encode("utf-8"))
            if size > max_file_size:
                return {
                    "error": f"Content is {size} bytes, exceeds max_file_size "
                              f"({max_file_size} bytes)."
                }
            try:
                Path(resolved).parent.mkdir(parents=True, exist_ok=True)
                Path(resolved).write_text(content)
                return {"status": "ok", "path": path}
            except Exception as e:
                return {"error": str(e)}

        # Default: list directory.
        try:
            p = Path(resolved)
            if not p.exists():
                return {"error": f"Not found: {path}"}
            if p.is_dir():
                items = []
                for f in sorted(p.iterdir()):
                    items.append({"name": f.name, "is_dir": f.is_dir()})
                return {"files": items}
            return {"file": p.name, "size": p.stat().st_size}
        except Exception as e:
            return {"error": str(e)}

    return editor_tool
