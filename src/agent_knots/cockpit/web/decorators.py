"""Shared route decorators for the cockpit web API."""

import functools

from fastapi import HTTPException


def raises_as(status_code: int):
    """Route decorator: convert a ValueError raised inside the handler
    into an HTTPException with the given status code, so routes don't
    each hand-roll the same `try: ... except ValueError as e: raise
    HTTPException(status_code=N, detail=str(e))` (~17 near-identical
    copies of it before this existed — found in the code review).

    Stack directly under the FastAPI route decorator:

        @app.patch("/api/things/{key}")
        @raises_as(404)
        async def update_thing(key: str, body: UpdateRequest):
            return store.update(key, ...)  # raises ValueError if missing

    functools.wraps sets __wrapped__, which inspect.signature() (what
    FastAPI actually uses to resolve path/query/body parameters) follows
    by default — so FastAPI still sees the original handler's real
    signature through the wrapper, not a bare (*args, **kwargs). Verified
    directly against a real FastAPI app before applying this broadly.
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ValueError as e:
                raise HTTPException(status_code=status_code, detail=str(e))
        return wrapper

    return decorator
