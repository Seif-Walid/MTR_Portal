"""Semantic search over portal records.

Each searchable type contributes (id, text, payload) rows, already filtered to
what the caller may see. Vectors live in ai_embeddings keyed by a hash of the
text, so the index heals itself: a search re-embeds only the rows whose text
changed (or are new) in one batch, and drops vectors for rows that are gone.
Scores blend cosine similarity with a plain word-overlap score so exact part
numbers still win."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import viewer
from app.domains.access import service as access
from app.domains.ai.embeddings import get_embedder
from app.domains.ai.models import AiEmbedding
from app.domains.events.models import Event, EventTeam
from app.domains.finance.models import BudgetLine
from app.domains.inventory.models import InventoryItem
from app.domains.inventory.service import can_view_inventory, visible_items_query
from app.domains.users.models import User


@dataclass
class Row:
    id: int
    text: str
    payload: dict


def _items(db: Session, user: User) -> Iterable[Row]:
    if not can_view_inventory(db, user):
        return []
    rows = []
    for item in db.scalars(visible_items_query(db, user)):
        text = " | ".join(
            p for p in (item.name, item.aliases, item.category, item.value_title, item.notes, item.sku) if p
        )
        rows.append(Row(item.id, text, {
            "name": item.name, "category": item.category, "quantity": item.quantity,
            "free": item.free, "in_use": item.in_use, "unit_value": item.unit_value,
            "currency": item.value_currency,
        }))
    return rows


def _events(db: Session, user: User) -> Iterable[Row]:
    if not access.has_privilege(db, user, "events.view"):
        return []
    rows = []
    for ev in db.scalars(select(Event)):
        text = " | ".join(p for p in (ev.name, ev.full_name, ev.description) if p)
        rows.append(Row(ev.id, text, {
            "name": ev.name, "full_name": ev.full_name, "status": str(ev.status),
            "start_date": str(ev.start_date) if ev.start_date else None,
        }))
    return rows


def _teams(db: Session, user: User) -> Iterable[Row]:
    if not access.has_privilege(db, user, "events.view"):
        return []
    rows = []
    for team in db.scalars(select(EventTeam).where(EventTeam.deleted_at.is_(None))):
        ev = team.category.event
        text = f"{team.name} | {team.category.name} | {ev.name}"
        rows.append(Row(team.id, text, {
            "name": team.name, "category": team.category.name,
            "event_id": ev.id, "event": ev.name,
        }))
    return rows


def _people(db: Session, user: User) -> Iterable[Row]:
    if not access.has_privilege(db, user, "people.view"):
        return []
    rows = []
    contacts = viewer.sees_contacts(access.privileges_for(db, user))
    for person in db.scalars(select(User).where(User.is_active)):
        text = " | ".join(p for p in (person.full_name, person.department, person.major) if p)
        rows.append(Row(person.id, text, {
            "name": person.full_name, "department": person.department,
            "email": person.email if contacts or person.id == user.id else None,
        }))
    return rows


def _budget_lines(db: Session, user: User) -> Iterable[Row]:
    if not access.has_privilege(db, user, "finance.view"):
        return []
    rows = []
    for line in db.scalars(select(BudgetLine)):
        rows.append(Row(line.id, f"{line.item} | {line.link_note or ''}", {
            "item": line.item, "event_id": line.event_id, "unit_price_egp": line.unit_price_egp,
            "total_qty": line.total_qty, "needed_cost": line.needed_cost,
        }))
    return rows


SOURCES: dict[str, Callable[[Session, User], Iterable[Row]]] = {
    "inventory": _items,
    "event": _events,
    "team": _teams,
    "person": _people,
    "budget_line": _budget_lines,
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def sync_index(db: Session, entity_type: str, rows: list[Row], *, prune: bool = False) -> dict[int, list[float]]:
    """Make sure every row has a current vector; return {id: vector}. Only
    changed or missing rows are embedded. With prune, vectors for ids not in
    rows are deleted (only safe when rows is the full, unfiltered set)."""
    embedder = get_embedder()
    stored = {
        e.entity_id: e
        for e in db.scalars(select(AiEmbedding).where(
            AiEmbedding.entity_type == entity_type, AiEmbedding.model == embedder.name))
    }
    stale = [r for r in rows if r.id not in stored or stored[r.id].text_hash != _hash(r.text)]
    if stale:
        vectors = embedder.embed([r.text for r in stale])
        for row, vec in zip(stale, vectors):
            rec = stored.get(row.id)
            if rec is None:
                rec = AiEmbedding(entity_type=entity_type, entity_id=row.id, model=embedder.name)
                db.add(rec)
                stored[row.id] = rec
            rec.text, rec.text_hash, rec.vector = row.text, _hash(row.text), json.dumps(vec)
    if prune:
        keep = {r.id for r in rows}
        gone = [i for i in stored if i not in keep]
        if gone:
            db.execute(delete(AiEmbedding).where(
                AiEmbedding.entity_type == entity_type, AiEmbedding.model == embedder.name,
                AiEmbedding.entity_id.in_(gone)))
    if stale or prune:
        db.commit()
    return {r.id: json.loads(stored[r.id].vector) for r in rows}


def search(db: Session, user: User, query: str, types: list[str] | None = None, limit: int = 10) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    embedder = get_embedder()
    embed_query = getattr(embedder, "embed_query", None)
    qvec = np.array(embed_query(query) if embed_query else embedder.embed([query])[0])
    qwords = _words(query)
    hits = []
    for entity_type in types or list(SOURCES):
        source = SOURCES.get(entity_type)
        if source is None:
            continue
        rows = list(source(db, user))
        if not rows:
            continue
        vectors = sync_index(db, entity_type, rows)
        matrix = np.array([vectors[r.id] for r in rows])
        cosine = matrix @ qvec
        for row, cos in zip(rows, cosine):
            words = _words(row.text)
            lexical = len(qwords & words) / len(qwords) if qwords else 0.0
            if query.lower() in row.text.lower():
                lexical = 1.0
            score = 0.7 * float(cos) + 0.3 * lexical
            hits.append({"type": entity_type, "id": row.id, "score": round(score, 4),
                         "semantic": round(float(cos), 4), "lexical": round(lexical, 4),
                         "text": row.text, **row.payload})
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def reindex(db: Session, user: User) -> dict[str, int]:
    """Rebuild every type the (admin) caller can see, pruning stale vectors."""
    counts = {}
    for entity_type, source in SOURCES.items():
        rows = list(source(db, user))
        sync_index(db, entity_type, rows, prune=True)
        counts[entity_type] = len(rows)
    return counts
