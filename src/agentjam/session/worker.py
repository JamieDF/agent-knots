"""Subprocess worker for isolated agent sessions.

This module runs as a child process, spawned by SubprocessRuntime.
It reads a JSON config from stdin, creates a Strands Agent, and
streams events back over stdout as JSONL. Control messages (send,
set-mode, stop) are read from stdin.

Protocol (JSONL, one JSON object per line):

Input (stdin):
  {"type": "config", "model": "...", "api_key": "...", "base_url": "...",
   "workspace_dir": "...", "system_prompt": "...", "task_description": "..."}
  {"type": "send", "message": "..."}
  {"type": "set-mode", "mode": "assistant"}
  {"type": "stop"}

Output (stdout):
  {"type": "event", "event_type": "message", "message": "..."}
  {"type": "event", "event_type": "tool_call", "tool_name": "...", "args": {...}}
  {"type": "event", "event_type": "state_change", "message": "Agent started."}
  {"type": "done"}

All communication happens on the main thread — stdin/stdout are
line-buffered and the agent runs in an asyncio event loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from strands import Agent
from strands.models.openai import OpenAIModel


async def run_worker() -> None:
    """Read config from stdin, run agent, stream events to stdout."""
    import contextlib, io
    # Save real stdout for JSONL output, suppress Strands' noise to stderr.
    real_stdout = sys.stdout
    sys.stdout = io.StringIO()

    global _real_stdout
    _real_stdout = real_stdout

    # Read config.
    config = await _read_config()
    if config is None:
        return

    workspace_dir = config.get("workspace_dir", "")
    if workspace_dir:
        os.chdir(workspace_dir)

    # Build model.
    client_args: dict[str, Any] = {}
    if config.get("api_key"):
        client_args["api_key"] = config["api_key"]
    if config.get("base_url"):
        client_args["base_url"] = config["base_url"]

    model = OpenAIModel(
        model_id=config.get("model", "minimax-m2.7"),
        client_args=client_args or None,
    )

    # Build tools.
    from agentjam.tools.defaults import DEFAULT_TOOLS, auto_approve_tools
    from agentjam.tools.registry import ToolRegistry
    auto_approve_tools()
    registry = ToolRegistry()
    all_tools = registry.list_enabled()

    # Swap sandboxed tools if workspace is set.
    if workspace_dir:
        from agentjam.sandbox_tools import make_sandboxed_shell, make_sandboxed_editor
        sb_shell = make_sandboxed_shell(workspace_dir)
        sb_editor = make_sandboxed_editor(workspace_dir)
        all_tools = [
            sb_shell if getattr(t, '__name__', '') == 'shell'
            else sb_editor if getattr(t, '__name__', '') == 'editor'
            else t
            for t in all_tools
        ]

    agent = Agent(
        model=model,
        tools=all_tools,
        system_prompt=config.get("system_prompt", ""),
        sandbox=None,
    )

    prompt = config.get("task_description", "")
    if not prompt:
        _emit({"type": "done"})
        return

    # Start streaming. Control messages are handled by _read_controls
    # which runs concurrently and can interrupt the stream.
    try:
        control_task = asyncio.create_task(_read_controls(agent))
        await _stream_agent(agent, prompt)
    finally:
        if not control_task.done():
            control_task.cancel()

    _emit({"type": "done"})


async def _stream_agent(agent: Agent, prompt: str) -> None:
    """Stream agent events to stdout."""
    _emit({"type": "event", "event_type": "state_change", "message": "Agent started."})

    try:
        async for chunk in agent.stream_async(prompt):
            event = _chunk_to_event(chunk)
            if event:
                _emit({"type": "event", **event})
    except asyncio.CancelledError:
        _emit({"type": "event", "event_type": "state_change", "message": "Agent cancelled."})
    except Exception as exc:
        _emit({"type": "event", "event_type": "error", "error": str(exc)})
    else:
        _emit({"type": "event", "event_type": "state_change", "message": "Agent finished."})


async def _read_controls(agent: Agent) -> None:
    """Read control messages from stdin. Runs until cancelled."""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:  # EOF — parent closed stdin
            await asyncio.sleep(0.5)  # Wait, don't exit immediately.
            continue
        try:
            msg = json.loads(line.strip())
        except json.JSONDecodeError:
            continue

        msg_type = msg.get("type", "")
        if msg_type == "send":
            prompt = msg.get("message", "")
            if prompt:
                async for chunk in agent.stream_async(prompt):
                    event = _chunk_to_event(chunk)
                    if event:
                        _emit({"type": "event", **event})
                _emit({"type": "event", "event_type": "state_change", "message": "Agent finished."})
        elif msg_type == "stop":
            break


async def _read_config() -> dict | None:
    """Read the config JSON from stdin."""
    loop = asyncio.get_event_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    if not line:
        return None
    try:
        msg = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    if msg.get("type") != "config":
        return None
    return msg


# Real stdout (saved before redirect).
_real_stdout = sys.stdout


def _emit(data: dict) -> None:
    """Write a JSON line to the real stdout."""
    global _real_stdout
    out = _real_stdout if _real_stdout else sys.__stdout__
    out.write(json.dumps(data) + "\n")
    out.flush()


def _chunk_to_event(chunk: Any) -> dict | None:
    """Translate a Strands chunk to a simplified event dict."""
    if not isinstance(chunk, dict):
        return None

    if any(k in chunk for k in ('init_event_loop', 'start', 'start_event_loop', 'force_stop')):
        return None

    if 'data' in chunk and 'delta' in chunk:
        text = chunk['delta'].get('text', '')
        if text:
            return {"event_type": "message", "message": text}

    if 'message' in chunk:
        msg = chunk['message']
        content = msg.get('content', '')
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and 'toolResult' in c:
                    tr = c['toolResult']
                    result_text = ''
                    if isinstance(tr.get('content', []), list):
                        result_text = ' '.join(ct.get('text', '') for ct in tr['content'] if isinstance(ct, dict))
                    return {"event_type": "tool_result", "message": result_text}
            text = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
        else:
            text = str(content)
        if text:
            return {"event_type": "message", "message": text}

    if 'result' in chunk:
        return None  # handled by the stream loop

    if chunk.get('type') == 'tool_use_stream':
        current = chunk.get('current_tool_use', {})
        return {
            "event_type": "tool_call",
            "tool_name": current.get('name', ''),
            "args": _parse_input(current.get('input', '{}')),
        }

    return None


def _parse_input(raw: str) -> dict:
    try:
        return json.loads(raw) if raw and raw != '{}' else {}
    except (json.JSONDecodeError, TypeError):
        return {}


if __name__ == "__main__":
    asyncio.run(run_worker())
