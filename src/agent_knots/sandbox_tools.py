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
from pathlib import Path

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


def _resource_preexec(timeout: int, max_memory_mb: int):
    """Build a preexec_fn that puts the child in its own process group and
    applies best-effort CPU/memory caps. Runs in the child after fork."""

    def _preexec() -> None:
        if hasattr(os, "setsid"):
            os.setsid()
        if HAS_RESOURCE:
            try:
                mem_bytes = max_memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, OSError):
                pass
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
            except (ValueError, OSError):
                pass

    return _preexec


def run_confined(command: str, cwd: str | None, timeout: int = 60, max_memory_mb: int = 512) -> dict:
    """Run a shell command with basic resource limits and full process-tree
    cleanup on timeout. See module docstring — this bounds resource usage
    and guarantees no orphaned children, but does not confine what paths
    the command can touch.
    """
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd or None, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            preexec_fn=_resource_preexec(timeout, max_memory_mb) if hasattr(os, "setsid") else None,
        )
    except Exception as e:
        return {"error": str(e)}

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return {"stdout": stdout, "stderr": stderr, "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        return {"error": f"Command timed out ({timeout}s)", "stdout": stdout, "stderr": stderr}
    except Exception as e:
        _kill_process_tree(proc)
        return {"error": str(e)}


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


def make_sandboxed_shell(workspace: str):
    """Create a shell tool that defaults cwd to the workspace directory."""

    @_tool_dec(description="Run a shell command with cwd defaulted to the workspace root. Not a security sandbox — see module docs.")
    def shell_tool(command: str) -> dict:
        """Run a shell command with cwd defaulted to the workspace root."""
        return run_confined(command, cwd=workspace)

    return shell_tool


def make_sandboxed_editor(workspace: str):
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
