"""Tiny shared formatting helpers used by more than one CLI submodule."""

from __future__ import annotations

import datetime


def format_ts(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")
