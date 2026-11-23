"""Free-tier model chain: runs the assistant on hosted models that speak the
OpenAI chat-completions API (Gemini, Groq, OpenRouter, ...), and moves on to
the next model in the chain whenever one is rate-limited, out of quota or
down — mid-turn if need be, since the history is plain OpenAI messages.

Unlike the Claude Code provider this one runs the tool loop itself. It still
reaches the portal only over HTTP with the user's AI token (the same
/api/ai/tools/* routes the MCP server uses), so every permission check stays
in the backend.

Chain, from settings.ai_chain: "provider:model,provider:model,...". A link
whose provider has no API key is skipped. Cooldowns are kept in-process."""

from __future__ import annotations

import copy
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncIterator
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

ENDPOINTS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
}

# Gemini 3+ wants each model-made function call echoed back with its thought
# signature. Calls another model made have none; this documented placeholder
# tells Gemini to skip the check for them.
DUMMY_SIGNATURE = "skip_thought_signature_validator"
PACIFIC = ZoneInfo("America/Los_Angeles")  # Gemini daily quotas reset at midnight PT
RESULT_CHARS = 12_000  # a tool result longer than this is cut before the model sees it
HISTORY_TURNS = 12  # earlier messages replayed from the conversation


@dataclass(frozen=True)
class Link:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


class LinkFailed(Exception):
    def __init__(self, link: Link, message: str, cooldown_s: float) -> None:
        super().__init__(message)
        self.link, self.cooldown_s = link, cooldown_s


def parse_chain(spec: str) -> list[Link]:
    links = []
    for part in spec.split(","):
        provider, sep, model = part.strip().partition(":")
        if sep and provider in ENDPOINTS and model:
            links.append(Link(provider, model))
        elif part.strip():
            log.warning("AI chain: ignoring malformed link %r", part)
    return links


def api_key(provider: str) -> str:
    return getattr(settings, f"{provider}_api_key", "") or ""


def configured_links() -> list[Link]:
    return [link for link in parse_chain(settings.ai_chain) if api_key(link.provider)]


# ------------------------------------------------------------- cooldowns
_cooldown_until: dict[Link, float] = {}


def available(link: Link, now: float | None = None) -> bool:
    return _cooldown_until.get(link, 0) <= (now or time.time())


def cool_down(link: Link, seconds: float) -> None:
    _cooldown_until[link] = time.time() + seconds
    log.warning("AI chain: %s cooling down for %.0fs", link.label, seconds)


def reset_cooldowns() -> None:
    _cooldown_until.clear()


def chain_status() -> list[dict]:
    now = time.time()
    return [{"link": link.label, "ready": available(link, now),
             "retry_in_s": max(0, round(_cooldown_until.get(link, 0) - now))}
            for link in configured_links()]


def _seconds_to_pacific_midnight() -> float:
    now = datetime.now(PACIFIC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    return (tomorrow - now).total_seconds()


def cooldown_for(link: Link, status: int, headers: httpx.Headers, body: str) -> float:
    """How long to leave a link alone after it failed with `status`."""
    if status == 429:
        retry = headers.get("retry-after")
        if retry and retry.replace(".", "", 1).isdigit():
            return max(float(retry), 1)
        if "PerDay" in body or "per day" in body.lower() or "daily" in body.lower():
            # out of the day's quota: Gemini resets at midnight Pacific; others
            # say so in retry-after, and a day is the safe upper bound
            return _seconds_to_pacific_midnight() if link.provider == "gemini" else 3600
        return 60
    if status in (401, 403):
        return 3600  # bad or revoked key: no point hammering it
    if status >= 500:
        return 30
    return 0  # 400 etc.: this request doesn't suit this model; try the next, keep the link


# ----------------------------------------------------------- tool schemas
def _deref(schema: dict, defs: dict, depth: int = 0) -> dict:
    """Inline $refs and reduce pydantic's schema to the subset every provider
    accepts (Gemini is the strictest): no $defs, no titles, no
    additionalProperties, `anyOf [X, null]` → X."""
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if depth > 3:  # recursive models (document blocks): stop here
            return {"type": "object", "description": defs.get(name, {}).get("description", "")}
        return _deref(defs.get(name, {}), defs, depth + 1)
    out: dict = {}
    for key, value in schema.items():
        if key in ("$defs", "title", "additionalProperties", "default"):
            continue
        if key == "anyOf":
            options = [o for o in value if o.get("type") != "null"]
            if len(options) == 1:
                out.update(_deref(options[0], defs, depth))
                continue
            out["anyOf"] = [_deref(o, defs, depth) for o in options]
        elif key == "properties":
            out["properties"] = {k: _deref(v, defs, depth) for k, v in value.items()}
        elif key == "items":
            out["items"] = _deref(value, defs, depth)
        else:
            out[key] = value
    return out


def tool_specs(catalog: list[dict]) -> list[dict]:
    specs = []
    for tool in catalog:
        schema = tool["input_schema"]
        params = _deref(schema, schema.get("$defs", {}))
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        specs.append({"type": "function", "function": {
            "name": tool["name"], "description": tool["description"], "parameters": params}})
    return specs


# -------------------------------------------------------------- messages
def history_messages(rows: list[dict]) -> list[dict]:
    """Earlier turns of the conversation as plain chat messages. Tool calls
    are kept as one-line notes, not replayed, so any model can read them."""
    out: list[dict] = []
    for row in rows[-HISTORY_TURNS:]:
        text = row.get("text") or ""
        if row["role"] == "assistant":
            calls = "; ".join(f"{t.get('name')}({json.dumps(t.get('input'), ensure_ascii=False)[:200]})"
                              for t in row.get("tools") or [])
            if calls:
                text = (text + "\n\n" if text else "") + f"[tools used: {calls}]"
            role = "assistant"
        elif row["role"] == "note":
            role, text = "user", f"[Portal note] {text}"
        else:
            role = "user"
        if not text:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + text
        else:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)  # chat APIs want the conversation to open with the user
    return out


def for_provider(messages: list[dict], provider: str) -> list[dict]:
    """Strip each message to the standard OpenAI fields the target accepts.
    Gemini also keeps (or, for calls another model made, fakes) its thought
    signatures."""
    out = []
    for msg in messages:
        keep = ("role", "content", "tool_calls", "tool_call_id") + (("extra_content",) if provider == "gemini" else ())
        m = {k: v for k, v in msg.items() if k in keep}
        if m.get("tool_calls"):
            calls = []
            for call in m["tool_calls"]:
                c = {k: v for k, v in call.items() if k in ("id", "type", "function")}
                if provider == "gemini":
                    extra = copy.deepcopy(call.get("extra_content") or {})
                    extra.setdefault("google", {}).setdefault("thought_signature", DUMMY_SIGNATURE)
                    c["extra_content"] = extra
                calls.append(c)
            m["tool_calls"] = calls
            if m.get("content") is None:
                m["content"] = ""
        out.append(m)
    return out


def _cut(text: str) -> str:
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + f"\n…[cut: {len(text) - RESULT_CHARS} more characters]"


# -------------------------------------------------------------- provider
class ChainProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None,
                 portal_transport: httpx.AsyncBaseTransport | None = None) -> None:
        # transports are for tests: one fakes the model APIs, one is the app
        self.transport, self.portal_transport = transport, portal_transport

    def _portal(self, token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=settings.ai_portal_url, transport=self.portal_transport,
                                 timeout=120, headers={"Authorization": f"Bearer {token}"})

    async def _complete(self, client: httpx.AsyncClient, link: Link, messages: list[dict],
                        tools: list[dict]) -> dict:
        try:
            resp = await client.post(
                f"{ENDPOINTS[link.provider]}/chat/completions",
                headers={"Authorization": f"Bearer {api_key(link.provider)}"},
                json={"model": link.model, "messages": for_provider(messages, link.provider),
                      "tools": tools, "tool_choice": "auto"},
            )
        except httpx.HTTPError as exc:  # timeout, connection refused, ...
            raise LinkFailed(link, f"{type(exc).__name__}: {exc}", 30) from exc
        if resp.status_code >= 400:
            raise LinkFailed(link, f"HTTP {resp.status_code}: {resp.text[:300]}",
                             cooldown_for(link, resp.status_code, resp.headers, resp.text))
        try:
            message = resp.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LinkFailed(link, f"unreadable reply: {resp.text[:300]}", 30) from exc
        return message

    async def _next_message(self, client: httpx.AsyncClient, messages: list[dict],
                            tools: list[dict]) -> tuple[Link, dict]:
        """One model step on the first link that answers."""
        links = configured_links()
        if not links:
            raise RuntimeError("No model is configured: set AI_CHAIN and at least one provider API key")
        errors = []
        for link in links:
            if not available(link):
                continue
            try:
                return link, await self._complete(client, link, messages, tools)
            except LinkFailed as failed:
                log.warning("AI chain: %s failed: %s", link.label, failed)
                errors.append(f"{link.label}: {failed}")
                if failed.cooldown_s:
                    cool_down(link, failed.cooldown_s)
        waits = [s["retry_in_s"] for s in chain_status() if not s["ready"]]
        hint = f" Try again in about {max(1, min(waits) // 60)} min." if waits else ""
        raise RuntimeError("Every model in the chain is busy or out of quota." + hint
                           + (" Last errors: " + " | ".join(errors[-3:]) if errors else ""))

    async def run(self, *, text: str, mode: str, token: str, session_id: str | None,
                  system: str) -> AsyncIterator[dict]:
        try:
            async for event in self._run(text=text, mode=mode, token=token, system=system):
                yield event
        except RuntimeError as exc:
            yield {"type": "error", "message": str(exc)}
        except httpx.HTTPError as exc:  # the portal's own tool routes failed
            log.exception("AI chain: portal call failed")
            yield {"type": "error", "message": f"Could not reach the portal's tools: {exc}"}
        yield {"type": "done"}

    async def _run(self, *, text: str, mode: str, token: str, system: str) -> AsyncIterator[dict]:
        async with self._portal(token) as portal:
            catalog = (await portal.get("/api/ai/tools")).raise_for_status().json()
            history = (await portal.get("/api/ai/history")).raise_for_status().json()
            if mode == "planner":
                system += ("\n\nWeb search is not available with this model. Plan from the portal's own "
                           "data and what you know, and mark dates, fees and prices as estimates to check.")
            messages = [{"role": "system", "content": system}, *history_messages(history),
                        {"role": "user", "content": text}]
            tools = tool_specs(catalog)
            used: list[str] = []
            async with httpx.AsyncClient(transport=self.transport, timeout=settings.ai_run_timeout_s) as client:
                for _ in range(settings.ai_max_tool_rounds):
                    link, message = await self._next_message(client, messages, tools)
                    if link.label not in used:
                        used.append(link.label)
                        yield {"type": "model", "model": link.label}
                    messages.append(message)
                    content = message.get("content")
                    if isinstance(content, list):  # some providers send content parts
                        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                    if content:
                        yield {"type": "text", "text": content}
                    calls = message.get("tool_calls") or []
                    if not calls:
                        return
                    for call in calls:
                        fn = call.get("function") or {}
                        name = fn.get("name", "")
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = None
                        yield {"type": "tool", "name": name, "input": args or {}}
                        if not isinstance(args, dict):
                            result = {"error": "Arguments were not valid JSON; send a JSON object"}
                        else:
                            resp = await portal.post(f"/api/ai/tools/{name}", json={"arguments": args})
                            try:
                                result = resp.json()
                            except ValueError:
                                result = {"error": resp.text[:500]}
                        yield {"type": "tool_result", "name": name, "result": result}
                        messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                         "content": _cut(json.dumps(result, ensure_ascii=False, default=str))})
                yield {"type": "error", "message": "Stopped after too many tool calls in one turn"}
