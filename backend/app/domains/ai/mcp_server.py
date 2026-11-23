"""Portal MCP server. A thin proxy: it lists the portal's AI tools and forwards
each call to POST /api/ai/tools/{name} with the user's AI token, so every
permission check stays in the backend. Two transports share the handlers:

- hosted (what people use): the portal serves it at /api/ai/mcp over
  streamable HTTP, see `mcp_http`; the token is the request's bearer and calls
  go to the portal in-process.
- stdio (the local claude_code provider):

    PORTAL_URL=http://127.0.0.1:8000 PORTAL_AI_TOKEN=mtrai_... \\
        python -m app.domains.ai.mcp_server

Get a token from the portal's Assistant page → "Connect your AI agent"."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

PORTAL_URL = os.environ.get("PORTAL_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("PORTAL_AI_TOKEN", "")

INSTRUCTIONS = (
    "Tools for the MindTech Robotics portal. Resolve names to ids with semantic_search / "
    "find_person before acting. Write tools only PROPOSE: the user confirms them on the "
    "portal's Assistant page, so never say a change is done until a confirmation note says so."
)


def _client(ctx) -> httpx.AsyncClient:
    request = getattr(ctx, "request", None)
    if request is not None:  # hosted: the caller's own bearer, served in-process
        from app.main import app

        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal", timeout=120,
                                 headers={"Authorization": request.headers.get("authorization", "")})
    return httpx.AsyncClient(base_url=PORTAL_URL, timeout=120,
                             headers={"Authorization": f"Bearer {TOKEN}"})


async def list_tools(ctx, params) -> types.ListToolsResult:
    async with _client(ctx) as client:
        resp = await client.get("/api/ai/tools")
        resp.raise_for_status()
        return types.ListToolsResult(tools=[
            types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
            for t in resp.json()
        ])


async def call_tool(ctx, params) -> types.CallToolResult:
    async with _client(ctx) as client:
        resp = await client.post(f"/api/ai/tools/{params.name}", json={"arguments": params.arguments or {}})
    try:
        body = resp.json()
    except ValueError:
        body = {"error": resp.text}
    is_error = resp.status_code >= 400 or (isinstance(body, dict) and "error" in body)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
        is_error=is_error,
    )


HOSTED_INSTRUCTIONS = (
    "Tools for the MindTech Robotics portal, acting as the person who connected you, with their "
    "permissions. Resolve names to ids with semantic_search / find_person before acting. Use "
    "find_actions to discover any page action, portal_read to run reads and portal_change for "
    "writes. Writes run immediately and are recorded in the portal's audit log, so check ids and "
    "amounts first and say what you changed."
)

server = Server("portal", instructions=INSTRUCTIONS, on_list_tools=list_tools, on_call_tool=call_tool)
# what /api/ai/mcp serves: same tools, for agents whose writes run at once
hosted_server = Server("portal", instructions=HOSTED_INSTRUCTIONS, on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
