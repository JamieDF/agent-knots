"""Token-based authentication for the web cockpit.

Matches the Go implementation: a 64-char hex token stored in
~/.agent-knots/cockpit.token with 0600 permissions. Auth is via
?token= query param (sets a cookie on first access), the
agent-knots-session HttpOnly cookie, or an Authorization: Bearer header.

The actual auth check lives in server.py's auth_middleware, not here —
this module holds the token lifecycle (generate/load/verify) and the
shared helpers the middleware and /login route both use, so there's one
source of truth for "is this token valid" instead of two.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi.responses import RedirectResponse


TOKEN_LENGTH = 64  # hex characters (32 raw bytes)
COOKIE_NAME = "agent-knots-session"


def generate_token() -> str:
    """Generate a new random 64-char hex token."""
    return secrets.token_hex(32)


def load_or_create_token(token_path: Path) -> str:
    """Load an existing token file or create a new one.

    The file is created with 0600 permissions so only the owner can read it.
    """
    token_path = Path(token_path)

    if token_path.exists():
        return token_path.read_text().strip()

    token = generate_token()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token)
    os.chmod(token_path, 0o600)
    return token


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def verify_token(provided: str, stored: str) -> bool:
    """Verify a provided token against the stored value."""
    if not provided or not stored:
        return False
    return _constant_time_compare(provided, stored)


# ── token holder ─────────────────────────────────────────────────────────────


class Auth:
    """Holds the cockpit's auth token and the helpers built around it.

    Usage:
        auth = Auth(token_path)
        # in auth_middleware: verify_token(candidate, auth.token)
        # in /login: auth.set_cookie_redirect(return_url)
    """

    def __init__(self, token_path: Path) -> None:
        self.token = load_or_create_token(token_path)

    def set_cookie_redirect(self, return_url: str = "/") -> RedirectResponse:
        """Return a redirect response that sets the auth cookie.

        Called after successful login or first-time ?token= access.
        """
        response = RedirectResponse(url=return_url, status_code=303)
        response.set_cookie(
            key=COOKIE_NAME,
            value=self.token,
            httponly=True,
            samesite="strict",
            max_age=7 * 24 * 3600,  # 7 days
            secure=False,  # localhost-only, no TLS needed
        )
        return response

    def cockpit_url(self, host: str = "127.0.0.1", port: int = 0) -> str:
        """Return the one-click cockpit URL with embedded token."""
        addr = f"127.0.0.1:{port}" if port else host
        return f"http://{addr}/?token={self.token}"
