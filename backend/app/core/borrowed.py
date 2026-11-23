"""In-process requests that run on a session someone else already holds.

The AI assistant performs portal actions by calling the portal's own HTTP
routes in-process, as the signed-in person, so every permission check and
side rule the pages go through applies unchanged. Those calls must share the
caller's database session (so a dry run can be rolled back, and a batch of
confirmed actions lands in one transaction), and must authenticate as that
person without a cookie.

A caller registers the session under a random one-time key and sends it in
the `x-ai-run` header; `BorrowMiddleware` turns the header into the context
variable that `get_db` and `get_current_user` consult. Keys live only for the
duration of the call and are never sent anywhere, so an outside request
cannot borrow a session.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.orm import Session

HEADER = "x-ai-run"


@dataclass
class Borrowed:
    session: Session
    user_id: int
    dry_run: bool


CURRENT: ContextVar[Borrowed | None] = ContextVar("borrowed_session", default=None)
_ACTIVE: dict[str, Borrowed] = {}


def current() -> Borrowed | None:
    return CURRENT.get()


def in_dry_run() -> bool:
    run = CURRENT.get()
    return run is not None and run.dry_run


@contextmanager
def lend(session: Session, user_id: int, dry_run: bool) -> Iterator[str]:
    """Register the session for one in-process call; routes' commits become
    flushes, so the caller alone decides whether the work is kept."""
    key = secrets.token_urlsafe(32)
    _ACTIVE[key] = Borrowed(session, user_id, dry_run)
    session.commit = session.flush  # type: ignore[method-assign]
    try:
        yield key
    finally:
        _ACTIVE.pop(key, None)
        del session.commit  # back to Session.commit


class BorrowMiddleware:
    """Pure ASGI, so the context variable is set in the request's own task
    and reaches the dependencies and the (thread-pooled) endpoint."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        run = None
        if scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name == HEADER.encode():
                    run = _ACTIVE.get(value.decode("latin-1"))
                    break
        if run is None:
            await self.app(scope, receive, send)
            return
        token = CURRENT.set(run)
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT.reset(token)
