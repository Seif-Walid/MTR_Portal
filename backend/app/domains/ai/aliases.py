"""Fill inventory_items.aliases with the other names people use for a part
("L298 motor driver" → "H-bridge, dual DC motor controller"), so semantic
search finds it by any of them. Small embedding models don't know electronics
jargon; one pass of a language model over the item names fixes that.

Runs the local Claude Code CLI (no tools, JSON out) on the developer's own
subscription — same local-only rule as the chat provider. Only items with no
aliases are touched, so names a person typed are never overwritten."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.inventory.models import InventoryItem

PROMPT = """You label robotics-lab inventory for search. For each part below, give 3-6 other names
or generic terms a student might search for it by (function, common nicknames, chip family, category
words) — e.g. "L298 motor driver module" -> "H-bridge, dual DC motor driver, motor controller board,
L298N". Do not repeat the part's own name. Reply with ONLY a JSON object mapping each id (as a string)
to one comma-separated string. Parts:
"""

BATCH = 60


def _parse(text: str) -> dict[str, str]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v).strip()[:500] for k, v in data.items() if isinstance(v, str)}


async def _ask(lines: list[str]) -> dict[str, str]:
    workdir = Path(tempfile.gettempdir()) / "portal-ai-workdir"
    workdir.mkdir(exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        settings.claude_cli_path, "-p", PROMPT + "\n".join(lines),
        "--output-format", "json", "--model", settings.ai_model_bulk,
        "--tools", "", "--strict-mcp-config", "--setting-sources", "",
        cwd=workdir, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_API_KEY")},
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=settings.ai_run_timeout_s)
    try:
        return _parse(json.loads(out.decode()).get("result", ""))
    except (json.JSONDecodeError, AttributeError):
        return {}


async def fill_missing(db: Session) -> dict:
    items = list(db.scalars(select(InventoryItem).where(
        InventoryItem.deleted_at.is_(None), InventoryItem.aliases == "")))
    filled = 0
    for start in range(0, len(items), BATCH):
        chunk = items[start:start + BATCH]
        lines = [f"{i.id}: {i.name}" + (f" [{i.category}]" if i.category else "") for i in chunk]
        answers = await _ask(lines)
        for item in chunk:
            alias = answers.get(str(item.id), "")
            if alias and not item.aliases:
                item.aliases = alias
                filled += 1
        db.commit()
    return {"items_without_aliases": len(items), "filled": filled}
