"""An agent provider turns one user message into a stream of events:

  {"type": "session", "id": str}            provider-side session to resume next turn
  {"type": "text", "text": str}             a chunk of the reply
  {"type": "tool", "name": str, "input": dict}
  {"type": "tool_result", "name": str, "result": Any}
  {"type": "error", "message": str}
  {"type": "done"}

The provider reaches the portal only through the MCP tools, authenticated by
`token`, so it holds no database access of its own."""

from __future__ import annotations

from typing import AsyncIterator, Protocol


class AgentProvider(Protocol):
    def run(
        self, *, text: str, mode: str, token: str, session_id: str | None, system: str
    ) -> AsyncIterator[dict]: ...
