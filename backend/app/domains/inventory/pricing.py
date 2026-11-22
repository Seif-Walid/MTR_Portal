"""Market value lookups against the two shops we buy from.

Only public, keyless store feeds are used — nothing is scraped or guessed:

  * Makers Electronics  — WooCommerce Store API  (makerselectronics.com)
  * Future Electronics Egypt — Shopify storefront JSON (store.fut-electronics.com)

Item names are free text, so a search can land on the wrong product. The flow
is therefore "suggest, then a person confirms": `search()` returns candidates,
the chosen listing is pinned on the item by its shop id/handle, and
`fetch_listing()` re-prices exactly that listing later. Precedence (Makers
first, then Future, otherwise a manual value) is applied by whoever confirms.
"""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass

import httpx

MAKERS = "makers"
FUTURE = "future"
MANUAL = "manual"
SOURCES = (MAKERS, FUTURE)

MAKERS_BASE = "https://makerselectronics.com"
FUTURE_BASE = "https://store.fut-electronics.com"
TIMEOUT = 15.0
HEADERS = {"User-Agent": "MTR-Portal inventory valuation", "Accept": "application/json"}


class PricingError(Exception):
    """The shop could not be reached, or the listing no longer exists."""


@dataclass
class Listing:
    source: str
    ref: str  # Makers product id / Future product handle
    title: str
    unit_price: float
    currency: str
    in_stock: bool
    url: str
    score: float = 0.0  # name similarity to the item, 0..1 (search only)

    def as_dict(self) -> dict:
        return asdict(self)


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True)


def _get_json(client: httpx.Client, url: str, params: dict | None = None):
    try:
        resp = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise PricingError(f"could not reach {url.split('/')[2]}: {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        raise PricingError("listing no longer exists")
    if resp.status_code >= 400:
        raise PricingError(f"{url.split('/')[2]} answered HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise PricingError(f"{url.split('/')[2]} did not return JSON") from exc


# --- Makers (WooCommerce Store API) ----------------------------------------
def _makers_listing(p: dict) -> Listing:
    prices = p["prices"]
    minor = int(prices.get("currency_minor_unit", 2))
    raw = prices.get("price") or "0"
    return Listing(
        source=MAKERS,
        ref=str(p["id"]),
        title=html.unescape(p.get("name", "")),
        unit_price=int(raw) / (10 ** minor),
        currency=prices.get("currency_code") or "EGP",
        in_stock=bool(p.get("is_in_stock")),
        url=p.get("permalink", ""),
    )


def _makers_search(client: httpx.Client, query: str, limit: int) -> list[Listing]:
    data = _get_json(client, f"{MAKERS_BASE}/wp-json/wc/store/v1/products",
                     {"search": query, "per_page": limit})
    return [_makers_listing(p) for p in data if p.get("prices", {}).get("price")]


def _makers_fetch(client: httpx.Client, ref: str) -> Listing:
    return _makers_listing(_get_json(client, f"{MAKERS_BASE}/wp-json/wc/store/v1/products/{ref}"))


# --- Future Electronics Egypt (Shopify) ------------------------------------
_future_currency: str | None = None


def _future_shop_currency(client: httpx.Client) -> str:
    """Shopify's product JSON carries no currency; the cart does."""
    global _future_currency
    if _future_currency is None:
        cart = _get_json(client, f"{FUTURE_BASE}/cart.js")
        if not cart.get("currency"):
            raise PricingError("Future Electronics did not report its currency")
        _future_currency = cart["currency"]
    return _future_currency


def _future_search(client: httpx.Client, query: str, limit: int) -> list[Listing]:
    data = _get_json(client, f"{FUTURE_BASE}/search/suggest.json", {
        "q": query, "resources[type]": "product", "resources[limit]": min(limit, 10),
    })
    currency = _future_shop_currency(client)
    out = []
    for p in data.get("resources", {}).get("results", {}).get("products", []):
        price = p.get("price_min") or p.get("price")
        if price in (None, ""):
            continue
        out.append(Listing(
            source=FUTURE, ref=p["handle"], title=html.unescape(p.get("title", "")),
            unit_price=float(price), currency=currency, in_stock=bool(p.get("available")),
            url=f"{FUTURE_BASE}/products/{p['handle']}",
        ))
    return out


def _future_fetch(client: httpx.Client, ref: str) -> Listing:
    product = _get_json(client, f"{FUTURE_BASE}/products/{ref}.json")["product"]
    variants = product.get("variants") or []
    if not variants:
        raise PricingError("listing has no price")
    return Listing(
        source=FUTURE, ref=ref, title=html.unescape(product.get("title", "")),
        unit_price=min(float(v["price"]) for v in variants),
        currency=_future_shop_currency(client),
        in_stock=any(v.get("available", True) for v in variants),
        url=f"{FUTURE_BASE}/products/{ref}",
    )


_SEARCH = {MAKERS: _makers_search, FUTURE: _future_search}
_FETCH = {MAKERS: _makers_fetch, FUTURE: _future_fetch}


# --- matching helpers ------------------------------------------------------
def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9.]+", text.lower())) - {"", "-", "."}


def similarity(a: str, b: str) -> float:
    """Word overlap between item name and listing title (Dice coefficient),
    so a short name is not a "perfect" match for every title containing it.
    A ranking hint for the person confirming, never a decision on its own."""
    ta, tb = _tokens(a), _tokens(b)
    return round(2 * len(ta & tb) / (len(ta) + len(tb)), 2) if ta and tb else 0.0


def _queries(name: str) -> list[str]:
    """The full name first, then shorter prefixes: shop search engines AND
    every word, so a long free-text name often matches nothing as-is."""
    words = name.split()
    out = [name]
    for n in range(min(len(words) - 1, 4), 1, -1):
        out.append(" ".join(words[:n]))
    return list(dict.fromkeys(q for q in out if q.strip()))


# --- public API ------------------------------------------------------------
def search(name: str, query: str | None = None, limit: int = 8) -> dict:
    """Candidates from both shops. With an explicit `query` only that query is
    tried; otherwise the item name and shorter fallbacks until one hits."""
    result: dict = {"query": {}, MAKERS: [], FUTURE: [], "errors": {}}
    queries = [query] if query else _queries(name)
    with _client() as client:
        for source in SOURCES:
            for q in queries:
                try:
                    hits = _SEARCH[source](client, q, limit)
                except PricingError as exc:
                    result["errors"][source] = str(exc)
                    break
                if hits:
                    for h in hits:
                        h.score = similarity(name, h.title)
                    hits.sort(key=lambda h: -h.score)
                    result["query"][source] = q
                    result[source] = [h.as_dict() for h in hits]
                    break
    return result


def fetch_listing(source: str, ref: str) -> Listing:
    if source not in _FETCH:
        raise PricingError(f"unknown source {source!r}")
    with _client() as client:
        return _FETCH[source](client, ref)
