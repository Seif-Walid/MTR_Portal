"""Scripted provider for tests: replays canned events."""

from __future__ import annotations

from typing import AsyncIterator


class FakeProvider:
    def __init__(self, script: list[dict] | None = None) -> None:
        self.script = script or [{"type": "text", "text": "ok"}]
        self.calls: list[dict] = []

    async def run(self, *, text: str, mode: str, token: str, session_id: str | None,
                  system: str) -> AsyncIterator[dict]:
        self.calls.append({"text": text, "mode": mode, "token": token, "session_id": session_id})
        yield {"type": "session", "id": session_id or "fake-session"}
        for event in self.script:
            yield event
        yield {"type": "done"}
