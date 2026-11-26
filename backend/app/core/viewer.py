"""Who is looking at this response, for field-level redaction.

People's email addresses are contact details: everyone who can open a people
picker (people.view) needs a person's name, but only those who administer
people (members.view / users.manage) need where to reach them. Schemas that
carry someone else's email (UserBrief and its children) consult `may_see_email`
when they serialize, so every list, picker, task and team that embeds a person
is redacted the same way without each route having to remember to.

The decision is made once per request, by `get_current_user`, and stored in a
holder this middleware puts on the request's context. It fails closed: with no
signed-in viewer recorded (a background job, a forgotten code path) nobody's
email is shown.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

CONTACT_PRIVILEGES = frozenset({"members.view", "users.manage"})


@dataclass
class Viewer:
    user_id: int | None = None
    sees_contacts: bool = False


_HOLDER: ContextVar[Viewer | None] = ContextVar("response_viewer", default=None)


def record(user_id: int, privileges: set[str]) -> None:
    """Called by get_current_user once it knows who is asking."""
    holder = _HOLDER.get()
    if holder is None:
        holder = Viewer()
        _HOLDER.set(holder)
    holder.user_id = user_id
    holder.sees_contacts = bool(CONTACT_PRIVILEGES & privileges)


def may_see_email(owner_id: int | None) -> bool:
    holder = _HOLDER.get()
    if holder is None or holder.user_id is None:
        return False
    return holder.sees_contacts or (owner_id is not None and owner_id == holder.user_id)


def sees_contacts(privileges: set[str]) -> bool:
    """For code that has the viewer's privileges in hand (the AI tools)."""
    return bool(CONTACT_PRIVILEGES & privileges)


class ViewerMiddleware:
    """Pure ASGI: gives each request a fresh, mutable holder in its own task,
    so get_current_user (run in a worker thread on a copy of the context) can
    fill it in and the response serializer (another copy) can read it."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _HOLDER.set(Viewer())
        try:
            await self.app(scope, receive, send)
        finally:
            _HOLDER.reset(token)
