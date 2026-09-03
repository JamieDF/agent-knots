"""Optional live e2e — skipped unless explicitly enabled.

Requires a running cockpit and AGENT_KNOTS_API_KEY. Not part of the default
pytest suite (``uv run pytest``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "e2e_playground_agent.py"


@pytest.mark.skipif(not os.environ.get("AGENT_KNOTS_E2E"), reason="set AGENT_KNOTS_E2E=1")
@pytest.mark.skipif(not os.environ.get("AGENT_KNOTS_API_KEY"), reason="needs AGENT_KNOTS_API_KEY")
def test_playground_agent_e2e():
    """Run scripts/e2e_playground_agent.py against a live cockpit on :8090."""
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    env = os.environ.copy()
    env.setdefault("E2E_BASE_URL", "http://127.0.0.1:8090")
    subprocess.run(
        [sys.executable, str(SCRIPT), "--timeout", env.get("E2E_PLAYGROUND_TIMEOUT", "360")],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
