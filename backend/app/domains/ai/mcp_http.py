"""The hosted MCP endpoint: /api/ai/mcp over streamable HTTP.

Any MCP client (Claude Code, Codex, Antigravity, claude.ai, ChatGPT...) is
given just this URL: the 401 below sends it through the portal's OAuth sign-in
(`oauth.py`), and the token it ends up with lasts until the person disconnects
it, so nothing is installed and nothing has to be pasted again. Stateless with JSON responses: every request stands
alone, which keeps it simple behind nginx and across backend workers.

Each request's bearer is checked first (GET /api/ai/token, in-process), so a
revoked or expired token gets a plain 401 instead of a broken MCP session.
The tool handlers themselves are the shared ones in `mcp_server`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.domains.ai.mcp_server import hosted_server

PATH = "/api/ai/mcp"


class HostedMCP:
    def __init__(self) -> None:
        self.manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        # a manager runs only once, so every app start (and test client) gets a new one
        self.manager = StreamableHTTPSessionManager(app=hosted_server, stateless=True, json_response=True)
        async with self.manager.run():
            yield
        self.manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        from app.main import app

        authorization = Headers(scope=scope).get("authorization", "")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal") as client:
            check = await client.get("/api/ai/token", headers={"Authorization": authorization})
        if check.status_code != 200:
            detail = check.json().get("detail", "Invalid AI token") if check.content else "Invalid AI token"
            code = check.status_code if check.status_code in (401, 403) else 401
            from app.domains.ai.oauth import resource_metadata_url

            challenge = f'Bearer realm="portal", resource_metadata="{resource_metadata_url()}"'
            await JSONResponse({"error": detail}, status_code=code,
                               headers={"WWW-Authenticate": challenge})(scope, receive, send)
            return
        if self.manager is None:
            await JSONResponse({"error": "MCP endpoint is starting"}, status_code=503)(scope, receive, send)
            return
        await self.manager.handle_request(scope, receive, send)


hosted = HostedMCP()
