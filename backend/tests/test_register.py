"""Request entry: nobody makes an account for themselves. Asking files an
application for a reviewer; only an accepted request becomes an account (with
the password chosen when asking). A member an admin already added activates
their account instead and is signed in at once."""

from sqlalchemy import select

from app.domains.applications.models import Application
from app.domains.users.models import User


def _ask(client, email="new.person@gmail.com", password="secret123", **extra):
    return client.post("/api/auth/request-entry", json={
        "email": email, "full_name": "New Person", "password": password, "phone": "01012345678", **extra,
    })


def _let_in(client, db_session, org, email, password, outbox) -> dict:
    """Ask, get accepted by the admin, follow the emailed link to choose a
    password, sign in — the cookies of that session."""
    from tests.conftest import As, link_token

    assert _ask(client, email, password).status_code == 202
    app = db_session.scalar(select(Application).where(Application.email == email))
    admin = As(client, org["admin"].email)
    assert admin.post(f"/api/applications/{app.id}/add-to-roster").status_code == 200
    client.cookies.clear()
    # the password typed into the request doesn't work on its own ...
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 401
    # ... the link mailed to the address does
    mail = [m for m in outbox if m["to"] == email][-1]
    assert client.post("/api/auth/reset-password",
                       json={"token": link_token(mail), "new_password": password}).status_code == 204
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return dict(r.cookies)


def test_request_entry_creates_no_account(client, db_session, org):
    r = _ask(client, "New.Person@gmail.com", school="Cairo University", why="I build robots")
    assert r.status_code == 202, r.text
    assert r.json() == {"status": "pending"}
    assert "portal_session" not in r.cookies
    assert db_session.scalar(select(User).where(User.email == "new.person@gmail.com")) is None
    app = db_session.scalar(select(Application).where(Application.email == "new.person@gmail.com"))
    assert app.source == "portal" and app.status == "new" and app.school == "Cairo University"
    assert app.password_hash and app.password_hash != "secret123"

    # can't sign in yet — and is told why (only with the right password)
    r = client.post("/api/auth/login", json={"email": "new.person@gmail.com", "password": "secret123"})
    assert r.status_code == 403 and "waiting for review" in r.json()["detail"]
    r = client.post("/api/auth/login", json={"email": "new.person@gmail.com", "password": "wrongpass1"})
    assert r.status_code == 401


def test_request_shows_in_applications_and_asking_again_updates_it(client, db_session, login, org):
    assert _ask(client).status_code == 202
    assert _ask(client, year="Year 2").status_code == 202  # the asker, same password
    rows = [a for a in login("admin").get("/api/applications").json() if a["email"] == "new.person@gmail.com"]
    assert len(rows) == 1 and rows[0]["source"] == "portal" and rows[0]["year"] == "Year 2"
    assert "password_hash" not in rows[0]


def test_accepted_request_signs_in_through_emailed_link(client, db_session, org, outbox):
    cookies = _let_in(client, db_session, org, "joiner@gmail.com", "secret123", outbox)
    me = client.get("/api/auth/me", cookies=cookies).json()
    assert me["email"] == "joiner@gmail.com"
    assert me["profile"]["mtr_id"].startswith("MTR-")  # numbered on the way in
    app = db_session.scalar(select(Application).where(Application.email == "joiner@gmail.com"))
    db_session.refresh(app)
    assert app.status == "accepted" and app.password_hash is None


def test_declined_request_never_signs_in(client, db_session, login, org):
    assert _ask(client, "nope@gmail.com").status_code == 202
    app = db_session.scalar(select(Application).where(Application.email == "nope@gmail.com"))
    r = login("admin").patch(f"/api/applications/{app.id}", json={"status": "declined"})
    assert r.status_code == 200
    db_session.refresh(app)
    assert app.password_hash is None
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "nope@gmail.com", "password": "secret123"}).status_code == 401


def test_request_entry_for_existing_account_looks_like_any_other(client, org):
    """Same answer as a brand-new email, so the form can't list members."""
    known = _ask(client, org["cto"].email)
    unknown = _ask(client, "brand-new@gmail.com")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"status": "pending"}


def test_request_entry_validation(client, org):
    assert _ask(client, "weak@gmail.com", password="short").status_code == 422
    assert _ask(client, "not-an-email").status_code == 422
    assert _ask(client, "nophone@gmail.com", phone="12").status_code == 422


def test_register_endpoint_is_gone(client, org):
    r = client.post("/api/auth/register",
                    json={"email": "x@gmail.com", "full_name": "X", "password": "secret123"})
    assert r.status_code in (404, 405)


def test_change_password_flow(client, db_session, org, outbox):
    cookies = _let_in(client, db_session, org, "pw@gmail.com", "secret123", outbox)

    # wrong current password rejected
    bad = client.post(
        "/api/auth/change-password",
        json={"current_password": "nope", "new_password": "brandnew123"},
        cookies=cookies,
    )
    assert bad.status_code == 400

    # reusing the same password rejected
    same = client.post(
        "/api/auth/change-password",
        json={"current_password": "secret123", "new_password": "secret123"},
        cookies=cookies,
    )
    assert same.status_code == 400

    # too short rejected by schema
    short = client.post(
        "/api/auth/change-password",
        json={"current_password": "secret123", "new_password": "short"},
        cookies=cookies,
    )
    assert short.status_code == 422

    # happy path
    ok = client.post(
        "/api/auth/change-password",
        json={"current_password": "secret123", "new_password": "brandnew123"},
        cookies=cookies,
    )
    assert ok.status_code == 204

    # old password no longer works, new one does
    assert client.post("/api/auth/login", json={"email": "pw@gmail.com", "password": "secret123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "pw@gmail.com", "password": "brandnew123"}).status_code == 200


def test_change_password_requires_auth(client, org):
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "x", "new_password": "brandnew123"},
    )
    assert r.status_code == 401
