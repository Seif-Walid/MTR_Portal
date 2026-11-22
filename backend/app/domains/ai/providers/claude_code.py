"""Runs the local Claude Code CLI headless, on the developer's own logged-in
subscription. LOCAL USE ONLY: a subscription is for its owner, so this must
never serve other members from a deployed server (see guard in get_provider).

The CLI gets no built-in tools except web search in planner mode, no project
settings or hooks, and exactly one MCP server: the portal's, which calls
/api/ai/tools/* with a short-lived token for the signed-in user."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncIterator

from app.core.config import BASE_DIR, settings

SERVER = "portal"


def _mcp_config(token: str) -> str:
    return json.dumps({"mcpServers": {SERVER: {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.domains.ai.mcp_server"],
        "env": {
            "PORTAL_URL": settings.ai_portal_url,
            "PORTAL_AI_TOKEN": token,
            "PYTHONPATH": str(BASE_DIR),
        },
    }}})


def build_command(*, text: str, mode: str, token: str, session_id: str | None, system: str) -> list[str]:
    planner = mode == "planner"
    cmd = [
        settings.claude_cli_path, "-p", text,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--model", settings.ai_model_planner if planner else settings.ai_model_assistant,
        "--mcp-config", _mcp_config(token), "--strict-mcp-config",
        "--setting-sources", "",
        "--tools", "WebSearch,WebFetch" if planner else "",
        "--allowedTools", f"mcp__{SERVER}", *(["WebSearch", "WebFetch"] if planner else []),
        "--append-system-prompt", system,
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def _short(name: str) -> str:
    prefix = f"mcp__{SERVER}__"
    return name[len(prefix):] if name.startswith(prefix) else name


def parse_line(obj: dict, tool_names: dict[str, str]) -> list[dict]:
    """One stream-json record → zero or more provider events."""
    out: list[dict] = []
    kind = obj.get("type")
    if kind == "system" and obj.get("subtype") == "init" and obj.get("session_id"):
        out.append({"type": "session", "id": obj["session_id"]})
    elif kind == "stream_event":
        ev = obj.get("event") or {}
        delta = ev.get("delta") or {}
        if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            out.append({"type": "text", "text": delta.get("text", "")})
    elif kind == "assistant":
        for block in (obj.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                tool_names[block.get("id", "")] = _short(block.get("name", ""))
                out.append({"type": "tool", "name": _short(block.get("name", "")), "input": block.get("input") or {}})
    elif kind == "user":
        for block in (obj.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
                try:
                    result = json.loads(content) if isinstance(content, str) else content
                except json.JSONDecodeError:
                    result = content
                out.append({"type": "tool_result", "name": tool_names.get(block.get("tool_use_id", ""), ""),
                            "result": result})
    elif kind == "result":
        if obj.get("session_id"):
            out.append({"type": "session", "id": obj["session_id"]})
        if obj.get("is_error") or obj.get("subtype") not in (None, "success"):
            out.append({"type": "error", "message": str(obj.get("result") or obj.get("subtype"))})
    return out


class ClaudeCodeProvider:
    async def run(self, *, text: str, mode: str, token: str, session_id: str | None,
                  system: str) -> AsyncIterator[dict]:
        workdir = Path(tempfile.gettempdir()) / "portal-ai-workdir"
        workdir.mkdir(exist_ok=True)  # empty dir: no CLAUDE.md or project files
        cmd = build_command(text=text, mode=mode, token=token, session_id=session_id, system=system)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_API_KEY")}
        # Load the portal tools up front (no deferred tool search), so with
        # --tools "" the model sees exactly the portal tools and nothing else.
        env["ENABLE_TOOL_SEARCH"] = "false"
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=workdir, env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024,
            )
        except FileNotFoundError:
            yield {"type": "error", "message": f"Claude Code CLI not found at '{settings.claude_cli_path}'"}
            yield {"type": "done"}
            return
        tool_names: dict[str, str] = {}
        try:
            async with asyncio.timeout(settings.ai_run_timeout_s):
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for event in parse_line(obj, tool_names):
                        yield event
                await proc.wait()
        except TimeoutError:
            proc.kill()
            yield {"type": "error", "message": "The assistant took too long and was stopped"}
        if proc.returncode not in (0, None):
            err = (await proc.stderr.read()).decode(errors="replace")[-800:] if proc.stderr else ""
            yield {"type": "error", "message": f"Claude Code exited with {proc.returncode}: {err.strip()}"}
        yield {"type": "done"}
