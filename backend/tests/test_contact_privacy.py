"""Regression tests for the 2026-11 member-list leak.

A penetration test pulled every member's name and email. Two ways in:
- any signed-in account (people.view is on Member/Student) could read every
  email from people pickers (/api/users/directory, /assignable, teams, ...)
  and the AI people search;
- an account an admin added but nobody had set up could be taken over by
  typing its email into Request entry with a password of one's choosing.
Plus sign-in had no brute-force limit, and the bootstrap admin's password
(`portal123`) is published in this public repository.
"""

import json

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.domains.access.models import AccessLevel
from app.domains.users.models import User
from tests.conftest import PASSWORD


def test_people_pickers_hide_other_peoples_emails(login, org):
    me = login("student")
    rows = me.get("/api/users/directory").json()
    assert len(rows) > 3
    for row in rows:
        if row["id"] == org["student"].id:
            assert row["email"] == org["student"].email  # your own, always
        else:
            assert row["email"] is None, row
    for path in ("/api/users/assignable", "/api/users/staff"):
        r = me.get(path)
        assert r.status_code == 200
        assert all(u["email"] is None for u in r.json() if u["id"] != org["student"].id)


def test_people_admins_still_see_emails(login, org):
    rows = login("admin").get("/api/users/directory").json()
    assert any(r["email"] == org["cto"].email for r in rows)


def test_own_profile_keeps_email(client, org):
    r = client.post("/api/auth/login", json={"email": org["student"].email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["email"] == org["student"].email
    assert client.get("/api/auth/me").json()["email"] == org["student"].email


def test_ai_people_lookup_hides_emails(client, login, org, db_session):
    from tests.test_ai import _call, _token

    level = db_session.query(AccessLevel).filter_by(name="Requester").one()
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | {"ai.use"}))
    db_session.commit()
    headers = _token(login, "student")
    matches = _call(client, headers, "find_person", name=org["cto"].full_name)["matches"]
    assert matches and all(m["email"] is None for m in matches if m["user_id"] != org["student"].id)


def test_login_is_throttled(client, org):
    email = org["cto"].email
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong-guess"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 429  # even the right password waits out the lockout


def test_production_never_uses_published_admin_password(db_session, monkeypatch):
    from app import seed

    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.delenv("SEED_ADMIN_PASSWORD", raising=False)
    levels = seed.seed_levels(db_session)
    # an existing bootstrap admin still on the dev password gets locked ...
    db_session.add(User(email="admin@org.local", full_name="Technical Admin",
                        hashed_password=hash_password(seed.DEV_PASSWORD)))
    db_session.flush()
    admin = seed.seed_admin(db_session, levels)
    assert not verify_password(seed.DEV_PASSWORD, admin.hashed_password)
    # ... and a fresh one is never created with it
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "boot@org.local")
    fresh = seed.seed_admin(db_session, levels)
    assert not verify_password(seed.DEV_PASSWORD, fresh.hashed_password)


# --- follow-up review findings ------------------------------------------------

def test_request_entry_answer_never_depends_on_membership(client, org):
    """No phone: same 422 whether or not the email is a member."""
    body = {"full_name": "a", "password": "aaaaaaaa"}
    known = client.post("/api/auth/request-entry", json={**body, "email": org["cto"].email})
    unknown = client.post("/api/auth/request-entry", json={**body, "email": "nobody-here@gmail.com"})
    assert known.status_code == unknown.status_code == 422


def test_stranger_cannot_rewrite_someone_elses_entry_request(client, db_session, org):
    from sqlalchemy import select

    from app.domains.applications.models import Application

    ask = {"email": "victim@gmail.com", "full_name": "Victim", "phone": "01011111111"}
    assert client.post("/api/auth/request-entry", json={**ask, "password": "victimpass1"}).status_code == 202
    r = client.post("/api/auth/request-entry",
                    json={**ask, "full_name": "Attacker", "password": "attacker12", "phone": "01099999999"})
    assert r.status_code == 202 and r.json() == {"status": "pending"}
    app = db_session.scalar(select(Application).where(Application.email == "victim@gmail.com"))
    db_session.refresh(app)
    assert app.full_name == "Victim" and app.phone == "01011111111"
    assert verify_password("victimpass1", app.password_hash)


def test_phone_match_never_hands_over_a_members_account(client, db_session, org, login, outbox):
    """An entry request carrying a member's phone links to them on accept,
    but sets no password: the setup link goes to the member's own inbox."""
    from sqlalchemy import select

    from app.domains.applications.models import Application
    from tests.conftest import make_member

    victim = make_member(db_session, "Victim Member", email="real.member@gmail.com", phone="01022223333")
    db_session.commit()
    assert client.post("/api/auth/request-entry", json={
        "email": "attacker@gmail.com", "full_name": "Attacker", "password": "attacker12", "phone": "01022223333",
    }).status_code == 202
    app = db_session.scalar(select(Application).where(Application.email == "attacker@gmail.com"))
    r = login("admin").post(f"/api/applications/{app.id}/add-to-roster")
    assert r.status_code == 200, r.text
    db_session.refresh(victim)
    assert not victim.claimed
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "real.member@gmail.com", "password": "attacker12"}).status_code == 401
    assert [m["to"] for m in outbox] == ["real.member@gmail.com"]


def test_org_tree_hides_emails_from_members(login, org):
    def emails(nodes):
        for n in nodes:
            yield n["id"], n["email"]
            yield from emails(n["children"])

    seen = dict(emails(login("team_lead").get("/api/team/tree").json()))
    assert len(seen) > 1
    assert all(e is None for uid, e in seen.items() if uid != org["team_lead"].id)
    assert seen[org["team_lead"].id] == org["team_lead"].email


def test_website_gets_public_api_only_and_never_with_cookies(client, org):
    site = {"Origin": "https://mindtechrobotics.com"}
    pub = client.get("/api/public/events", headers=site)
    assert pub.headers.get("access-control-allow-origin") == "https://mindtechrobotics.com"
    assert "access-control-allow-credentials" not in pub.headers
    pre = client.options("/api/users/directory", headers={**site, "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in pre.headers
    assert "access-control-allow-origin" not in client.get("/api/auth/me", headers=site).headers
    evil = client.get("/api/public/events", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
