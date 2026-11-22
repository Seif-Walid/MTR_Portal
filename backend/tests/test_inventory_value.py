"""Inventory market value: pinned shop listings, manual estimates, summary.

The shop APIs are stubbed — tests must never hit makerselectronics.com or
store.fut-electronics.com."""

import pytest

from app.domains.inventory import pricing


@pytest.fixture()
def shops(monkeypatch):
    prices = {("makers", "111"): 215.0, ("future", "uno-r3"): 360.0}

    def fetch(source, ref):
        if (source, ref) not in prices:
            raise pricing.PricingError("listing no longer exists")
        return pricing.Listing(source=source, ref=ref, title=f"{source} {ref}",
                               unit_price=prices[(source, ref)], currency="EGP",
                               in_stock=True, url=f"https://shop/{ref}")

    monkeypatch.setattr(pricing, "fetch_listing", fetch)
    return prices


def _item(login, name="Arduino Nano", quantity=4):
    r = login("cto").post("/api/inventory", json={"name": name, "quantity": quantity})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_pin_listing_prices_server_side(login, org, shops):
    item_id = _item(login)
    # a client-sent unit_value is ignored for shop sources — the shop decides
    r = login("cto").put(f"/api/inventory/{item_id}/value",
                         json={"source": "makers", "ref": "111", "unit_value": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["unit_value"], d["total_value"], d["value_source"]) == (215.0, 860.0, "makers")
    assert d["value_url"] == "https://shop/111"


def test_unknown_listing_is_rejected(login, org, shops):
    item_id = _item(login)
    r = login("cto").put(f"/api/inventory/{item_id}/value", json={"source": "makers", "ref": "nope"})
    assert r.status_code == 502


def test_manual_value_needs_amount_and_is_uncited(login, org, shops):
    item_id = _item(login)
    url = f"/api/inventory/{item_id}/value"
    assert login("cto").put(url, json={"source": "manual"}).status_code == 400
    d = login("cto").put(url, json={"source": "manual", "unit_value": 50, "note": "old stock"}).json()
    assert (d["value_source"], d["unit_value"], d["value_url"], d["value_note"]) == ("manual", 50.0, None, "old stock")


def test_value_editing_needs_inventory_edit(login, org, shops):
    item_id = _item(login)
    r = login("student").put(f"/api/inventory/{item_id}/value", json={"source": "manual", "unit_value": 5})
    assert r.status_code == 403


def test_refresh_follows_shop_and_skips_manual(login, org, shops):
    a, b, c = _item(login, "A", 2), _item(login, "B", 1), _item(login, "C", 3)
    cto = login("cto")
    cto.put(f"/api/inventory/{a}/value", json={"source": "makers", "ref": "111"})
    cto.put(f"/api/inventory/{b}/value", json={"source": "future", "ref": "uno-r3"})
    cto.put(f"/api/inventory/{c}/value", json={"source": "manual", "unit_value": 10})

    shops[("makers", "111")] = 230.0
    del shops[("future", "uno-r3")]
    r = cto.post("/api/inventory/values/refresh").json()
    assert (r["checked"], r["changed"]) == (2, 1)
    assert [f["id"] for f in r["failed"]] == [b]

    items = {i["id"]: i for i in cto.get("/api/inventory").json()}
    assert items[a]["unit_value"] == 230.0
    # a failed refresh keeps the last price but flags it
    assert items[b]["unit_value"] == 360.0 and items[b]["value_error"]
    assert items[c]["unit_value"] == 10.0


def test_summary_counts_unpriced_without_guessing(login, org, shops):
    a, b = _item(login, "A", 2), _item(login, "B", 5)
    _item(login, "Unpriced", 7)
    cto = login("cto")
    cto.put(f"/api/inventory/{a}/value", json={"source": "makers", "ref": "111"})
    cto.put(f"/api/inventory/{b}/value", json={"source": "manual", "unit_value": 10})
    s = cto.get("/api/inventory/value-summary").json()
    assert s["total"] == 215.0 * 2 + 10 * 5
    assert s["by_source"]["makers"] == {"items": 1, "units": 2, "total": 430.0}
    assert s["by_source"]["manual"]["total"] == 50.0
    assert (s["unpriced_items"], s["unpriced_units"]) == (1, 7)


def test_clear_value(login, org, shops):
    item_id = _item(login)
    cto = login("cto")
    cto.put(f"/api/inventory/{item_id}/value", json={"source": "manual", "unit_value": 3})
    d = cto.delete(f"/api/inventory/{item_id}/value").json()
    assert d["unit_value"] is None and d["value_source"] is None


def test_similarity_and_query_fallbacks():
    assert pricing.similarity("Arduino Nano", "arduino nano") == 1.0
    assert pricing.similarity("Arduino Nano", "Uno R3") == 0.0
    # a short name inside a long title is not a perfect match
    assert pricing.similarity("Arduino Mega", "Prototyping Shield for Arduino Mega") < \
        pricing.similarity("Arduino Mega", "Arduino Mega 2560")
    assert pricing._queries("Battery 11.1V 3S 1800mAh 30C") == [
        "Battery 11.1V 3S 1800mAh 30C", "Battery 11.1V 3S 1800mAh", "Battery 11.1V 3S", "Battery 11.1V"]
