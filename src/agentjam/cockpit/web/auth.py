"""Token-based authentication for the web cockpit.

Matches the Go implementation: a 64-char hex token stored in
~/.agentjam/cockpit.token with 0600 permissions. Auth is via
?token= query param (sets a cookie on first access) or the
agentjam-session HttpOnly cookie.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from fastapi import Cookie, HTTPException, Request
from fastapi.responses import RedirectResponse


TOKEN_LENGTH = 64  # hex characters (32 raw bytes)
COOKIE_NAME = "agentjam-session"


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


# ── FastAPI dependency ───────────────────────────────────────────────────────


class Auth:
    """Authentication dependency for FastAPI routes.

    Usage:
        auth = Auth(token_path)
        app.include_router(router, dependencies=[Depends(auth.require)])
    """

    def __init__(self, token_path: Path) -> None:
        self.token = load_or_create_token(token_path)

    async def require(self, request: Request) -> None:
        """Raise 401 if the request is not authenticated.

        Checks the cookie first, then falls back to ?token= query param.
        GET /login and POST /login are always allowed.
        HTMX requests get 401 instead of a redirect.
        """
        path = request.url.path
        if path in ("/login", "/login/"):
            return

        # Check cookie.
        cookie_token = request.cookies.get(COOKIE_NAME, "")
        if cookie_token and verify_token(cookie_token, self.token):
            return

        # Check query param.
        query_token = request.query_params.get("token", "")
        if query_token and verify_token(query_token, self.token):
            return

        # Check Authorization header (Bearer token).
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            bearer_token = auth_header[7:]
            if verify_token(bearer_token, self.token):
                return

        raise HTTPException(status_code=401, detail="Unauthorized")

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

    @property
    def cockpit_url(self, host: str = "127.0.0.1", port: int = 0) -> str:
        """Return the one-click cockpit URL with embedded token."""
        addr = f"127.0.0.1:{port}" if port else host
        return f"http://{addr}/?token={self.token}"
