"""Everything a person can do on the portal's pages, as assistant tools.

Rather than one hand-written tool per feature, the assistant reaches the
portal's own HTTP routes (the ones the pages call), in-process and as the
signed-in person:

- `find_actions` searches the route catalogue (built from the OpenAPI spec)
  and returns what each matching route expects;
- `portal_read` runs a GET route straight away;
- `portal_change` PROPOSES a POST / PUT / PATCH / DELETE: it is dry-run
  through the real route (every permission check and validation the page
  meets), rolled back, and stored as a pending action the person confirms.

New features get tools for free. Routes that log in, upload files, talk to
Google, or run the assistant itself are left out.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core import borrowed
from app.domains.users.models import User

RESULT_CAP = 15_000  # characters of a GET result handed back to the model

BLOCKED_PREFIXES = ("/api/ai", "/api/public", "/api/drive", "/api/health")
AUTH_ALLOWED = {("GET", "/api/auth/me"), ("PUT", "/api/auth/me/profile")}
BLOCKED = {
    ("POST", "/api/inventory/values/refresh"),  # scrapes shops for every item; minutes long
    ("GET", "/api/inventory/{item_id}/price-candidates"),  # live shop lookups: use price_lookup
    ("POST", "/api/tasks/{task_id}/drive-uploads"),
    ("POST", "/api/tasks/{task_id}/drive-uploads/complete"),
}
FILE_PATHS = re.compile(r"(export\.xlsx|/attachments/|/files/)")
REF = re.compile(r"\{\{#(\d+)((?:\.[A-Za-z0-9_]+)*)\}\}")


# ------------------------------------------------------------- catalogue
def _strip(schema: Any, components: dict, depth: int = 0) -> Any:
    """Inline $refs and drop noise so a route's body reads compactly."""
    if isinstance(schema, list):
        return [_strip(s, components, depth) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if depth > 4:
            return {"type": "object"}
        return _strip(components.get(name, {}), components, depth + 1)
    out = {}
    for key, value in schema.items():
        if key in ("title", "additionalProperties"):
            continue
        if key == "anyOf":
            options = [o for o in value if o.get("type") != "null"]
            if len(options) == 1:
                out.update(_strip(options[0], components, depth))
                out["nullable"] = True
                continue
        out[key] = _strip(value, components, depth)
    return out


def _allowed(method: str, path: str, op: dict) -> bool:
    if path.startswith("/api/auth"):
        return (method, path) in AUTH_ALLOWED
    if path.startswith(BLOCKED_PREFIXES) or (method, path) in BLOCKED:
        return False
    if method == "GET" and FILE_PATHS.search(path):
        return False
    content = (op.get("requestBody") or {}).get("content", {})
    return not content or "application/json" in content


@lru_cache(maxsize=1)
def operations() -> tuple[dict, ...]:
    from app.main import app

    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    ops = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            method = method.upper()
            if not _allowed(method, path, op):
                continue
            params = [{"name": p["name"], "in": p["in"], "required": p.get("required", False),
                       "schema": _strip(p.get("schema", {}), components)}
                      for p in op.get("parameters", []) if p["in"] in ("path", "query")]
            body = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
            doc = (op.get("description") or "").strip()
            ops.append({
                "method": method, "path": path, "summary": op.get("summary", ""),
                "area": (op.get("tags") or [path.split("/")[2]])[0] if len(path.split("/")) > 2 else "",
                "doc": doc[:600], "params": params,
                "body": _strip(body, components) if body else None,
                "regex": re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$"),
            })
    return tuple(ops)


def _match(method: str, path: str) -> dict | None:
    for op in operations():
        if op["method"] == method and op["regex"].match(path):
            return op
    return None


VERBS = {
    "POST": "create add new make record register post submit apply accept approve",
    "PATCH": "edit update change set rename move mark modify",
    "PUT": "set replace update",
    "DELETE": "delete remove drop cancel",
    "GET": "list show get view read see find",
}


def _words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower().replace("_", " ").replace("-", " "))
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}


def _fields(schema: Any) -> str:
    """Field names and descriptions of a body, so 'paid' finds the dues route."""
    if isinstance(schema, list):
        return " ".join(_fields(s) for s in schema)
    if not isinstance(schema, dict):
        return ""
    words = [schema.get("description", "")]
    for name, sub in (schema.get("properties") or {}).items():
        words += [name, _fields(sub)]
    words.append(_fields(schema.get("items")))
    return " ".join(w for w in words if w)


def search(query: str, limit: int = 8) -> list[dict]:
    want = _words(query)
    scored = []
    for op in operations():
        title = _words(" ".join([op["path"], op["summary"], op["area"]]))
        doc = _words(op["doc"])
        fields = _words(_fields(op["body"]))
        verbs = _words(VERBS[op["method"]])
        score = 4 * len(want & title) + 2 * len(want & doc - title) + len(want & fields - title - doc) \
            + len(want & verbs)
        if score:
            scored.append((score, op))
    scored.sort(key=lambda s: -s[0])
    return [op for _, op in scored[:limit]]


def describe(op: dict, full: bool) -> dict:
    out = {"method": op["method"], "path": op["path"], "summary": op["summary"], "area": op["area"]}
    if full:
        if op["doc"]:
            out["doc"] = op["doc"]
        if op["params"]:
            out["params"] = op["params"]
        if op["body"]:
            out["body"] = op["body"]
    return out


# ----------------------------------------------------------------- calls
def _resolve(value: Any, refs: dict[int, Any]) -> Any:
    """`{{#12.id}}` → field `id` of what pending action #12 returned."""
    if isinstance(value, dict):
        return {k: _resolve(v, refs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, refs) for v in value]
    if not isinstance(value, str) or "{{#" not in value:
        return value

    def lookup(m: re.Match) -> Any:
        action_id, path = int(m.group(1)), [p for p in m.group(2).split(".") if p]
        if action_id not in refs:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Action #{action_id} must be confirmed in the same batch")
        got = refs[action_id]
        for part in path:
            if isinstance(got, dict) and part in got:
                got = got[part]
            elif isinstance(got, list) and part.isdigit() and int(part) < len(got):
                got = got[int(part)]
            else:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Action #{action_id}'s result has no {'.'.join(path)}")
        return got

    whole = REF.fullmatch(value)
    if whole:  # keep the type (an id stays an int)
        return lookup(whole)
    return REF.sub(lambda m: str(lookup(m)), value)


def call(db: Session, user: User, method: str, path: str, query: dict | None, body: Any,
         dry_run: bool) -> tuple[int, Any]:
    """Run one portal route in-process as `user` on `db`. Nothing is committed."""
    from fastapi.testclient import TestClient

    from app.main import app

    parts = urlsplit(path)
    if parts.scheme or parts.netloc or parts.query:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give a bare /api/... path; put filters in `query`")
    if _match(method, parts.path) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{method} {parts.path} is not an action the assistant can use; look it up with find_actions")
    with borrowed.lend(db, user.id, dry_run) as key:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.request(method, parts.path, params=query or None,
                           json=body if method != "GET" or body else None,
                           headers={borrowed.HEADER: key})
    try:
        data = r.json()
    except ValueError:
        data = {"content_type": r.headers.get("content-type"), "bytes": len(r.content)}
    return r.status_code, data


def _fail(code: int, data: Any) -> HTTPException:
    detail = data.get("detail", data) if isinstance(data, dict) else data
    return HTTPException(code, detail)


# ----------------------------------------------------------------- tools
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindActionsIn(_In):
    query: str = Field(default="", description=(
        "What the user wants to do or see, in a few plain words, e.g. 'record dues payment', "
        "'edit task status', 'delete inventory item'. Leave empty to list every action briefly."))


class ReadIn(_In):
    path: str = Field(description="A GET path from find_actions with the ids filled in, e.g. /api/finance/dues")
    query: dict[str, Any] | None = Field(default=None, description="Query parameters, if the route takes any")


class ChangeIn(_In):
    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(description=(
        "Path from find_actions with ids filled in, e.g. /api/tasks/12/status. "
        "An id that an earlier pending action will create is written {{#<action id>.<field>}}, e.g. /api/events/{{#31.id}}/categories"))
    body: dict[str, Any] | None = Field(default=None, description=(
        "JSON body matching the route's `body` schema from find_actions. {{#<action id>.<field>}} works here too"))
    query: dict[str, Any] | None = None
    summary: str = Field(min_length=3, max_length=400, description=(
        "One plain sentence the user reads before confirming, with names not ids, "
        "e.g. 'Record 500 EGP dues paid by Omar Hassan for MRC 2026'"))


def find_actions(db: Session, user: User, inp: FindActionsIn) -> dict:
    if not inp.query.strip():
        return {"actions": [f"{o['method']} {o['path']} — {o['summary']}" for o in operations()],
                "note": "Call find_actions again with words from the one you need to get its inputs."}
    hits = search(inp.query)
    if not hits:
        return {"actions": [f"{o['method']} {o['path']} — {o['summary']}" for o in operations()],
                "note": "Nothing matched those words, so here is every action. Pick one and call find_actions with its words to get its inputs."}
    return {"actions": [describe(op, full=i < 5) for i, op in enumerate(hits)],
            "note": "GET → portal_read. Anything else → portal_change."}


def portal_read(db: Session, user: User, inp: ReadIn) -> Any:
    try:
        code, data = call(db, user, "GET", inp.path, inp.query, None, dry_run=True)
    finally:
        db.rollback()
    if code >= 400:
        raise _fail(code, data)
    text = json.dumps(data, default=str)
    if len(text) > RESULT_CAP:
        return {"truncated": True, "first_part": text[:RESULT_CAP],
                "note": "Too long; narrow it with query parameters or use query_data."}
    return data


def portal_change(db: Session, user: User, inp: ChangeIn, refs: dict[int, Any]) -> Any:
    """Runs on the session the propose/confirm flow passes in; it decides
    whether to keep the result."""
    path = _resolve(inp.path, refs)
    body = _resolve(inp.body, refs)
    query = _resolve(inp.query, refs)
    code, data = call(db, user, inp.method, path, query, body, dry_run=getattr(db, "info", {}).get("ai_dry_run", True))
    if code >= 400:
        raise _fail(code, data)
    return data if isinstance(data, dict) else {"result": data}


def summarize_change(db: Session, inp: ChangeIn) -> str:
    body = json.dumps(inp.body, ensure_ascii=False) if inp.body else ""
    if len(body) > 500:
        body = body[:500] + "…"
    return f"{inp.summary}\n\n`{inp.method} {inp.path}`" + (f" `{body}`" if body else "")
