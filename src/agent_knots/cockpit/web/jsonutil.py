"""JSON-extraction helper for parsing LLM completions."""

import json
import re


def _extract_json_object(text: str) -> dict:
    """Parse a JSON object out of a completion's raw text, tolerating the
    markdown code fences, stray commentary, and <think>...</think>
    reasoning blocks models commonly add even when explicitly told not
    to (no response_format to enforce it — see routes/tasks.py's
    draft_task()). MiniMax M2.7 in particular is a reasoning model that
    inlines its <think> block directly into `message.content` for a
    plain, non-streaming completion (there's no separate reasoning
    field to skip) — and since reasoning text about a coding task
    routinely contains its own literal '{'/'}' characters, a naive
    "first { to last }" scan can grab braces from *inside* the
    reasoning instead of the real JSON object, producing something
    that isn't valid JSON at all."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    snippet = text[:200] + ("…" if len(text) > 200 else "")
    raise ValueError(f"No valid JSON object found in completion: {snippet!r}")
