"""Shared atomic YAML file read/write helpers.

Six different stores (task, project, vault, settings, tools, workflows)
each independently reimplemented "write to .tmp, then rename" and
"yaml.safe_load wrapped in try/except". Centralizing both here also makes the
chmod(0o600) permission hygiene apply uniformly; previously vault/
settings/tools chmod'd their files and task/project never did, for no
real reason (none of them contain anything more sensitive than the
others don't already).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def atomic_write_yaml(path: Path, data: Any, *, sort_keys: bool = False, mode: int | None = 0o600) -> None:
    """Write data as YAML to path, atomically (write to a .tmp sibling,
    then rename over the real path — a reader never sees a half-written
    file).

    mode, if given, chmods the .tmp file before the rename. There's a
    brief window between write and chmod where the .tmp file has
    default permissions — the same tradeoff every call site this
    replaces already made.
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=sort_keys))
    if mode is not None:
        tmp.chmod(mode)
    tmp.rename(path)


def safe_read_yaml(path: Path, default: Any = None) -> Any:
    """Read and parse a YAML file, returning `default` on any file-level
    error (missing file, permission error, malformed YAML).

    Does not validate the parsed shape — callers that need a specific
    dict shape (e.g. a required "id" key) or construct a dataclass from
    the result still handle those errors themselves, since what counts
    as "malformed" varies per store.
    """
    try:
        return yaml.safe_load(path.read_text())
    except (yaml.YAMLError, OSError):
        return default
