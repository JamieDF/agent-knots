"""Sandbox-aware tools that run inside the workspace directory.

When an agent session has a workspace, shell and editor tools are
confined to that directory. Commands run via subprocess with cwd set,
and file paths are resolved relative to the workspace root.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from strands.tools import tool as _tool_dec


def _resolve(root: str, path: str) -> str:
    """Resolve a path relative to the workspace root. Refuse traversal."""
    resolved = (Path(root) / path).resolve()
    if not str(resolved).startswith(str(Path(root).resolve())):
        raise ValueError(f"Path {path!r} is outside the workspace")
    return str(resolved)


def make_sandboxed_shell(workspace: str):
    """Create a shell tool confined to the workspace directory."""

    @_tool_dec(description="Run a shell command inside the workspace. Working directory is the workspace root.")
    def shell_tool(command: str) -> dict:
        """Run a shell command confined to the workspace.

        The command runs with cwd set to the workspace directory.
        """
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=60, cwd=workspace,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out (60s)"}
        except Exception as e:
            return {"error": str(e)}

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
