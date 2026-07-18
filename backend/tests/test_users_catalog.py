"""GET /users/roles and /users/departments — the DB-backed catalogs the admin
user-management UI picks from, instead of a hardcoded frontend list."""


def test_roles_catalog_admin_only(login, org):
    r = login("admin").get("/api/users/roles")
    assert r.status_code == 200
    slugs = {role["slug"] for role in r.json()}
    assert {"admin", "ceo", "cto", "student"} <= slugs
    # names come from the Role table (however it was seeded), not a
    # frontend-side slug-to-label guess — the endpoint is a passthrough
    names = {role["slug"]: role["name"] for role in r.json()}
    assert names["software_lead"] == "Software Lead"

    assert login("student").get("/api/users/roles").status_code == 403


def test_departments_catalog_admin_only(login, org):
    r = login("admin").get("/api/users/departments")
    assert r.status_code == 200
    assert set(r.json()) == {"software", "mechanical", "electrical", "media", "finance"}

    assert login("student").get("/api/users/departments").status_code == 403
