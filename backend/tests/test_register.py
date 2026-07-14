"""Open registration: personal emails welcome; new accounts start with no
roles and no hierarchy position until the admin places them."""


def test_register_creates_account_and_logs_in(client, org):
    r = client.post(
        "/api/auth/register",
        json={"email": "New.Person@gmail.com", "full_name": "New Person", "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "new.person@gmail.com"  # normalized
    assert body["roles"] == []
    assert body["is_admin"] is False and body["is_staff"] is False and body["has_team"] is False

    # the register response set a session cookie
    me = client.get("/api/auth/me", cookies=dict(r.cookies))
    assert me.status_code == 200
    assert me.json()["email"] == "new.person@gmail.com"


def test_register_duplicate_email_rejected(client, org):
    payload = {"email": "dup@gmail.com", "full_name": "Dup", "password": "secret123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 409
    # also collides with pre-existing seeded users
    r = client.post(
        "/api/auth/register",
        json={"email": org["cto"].email, "full_name": "X", "password": "secret123"},
    )
    assert r.status_code == 409


def test_register_validation(client, org):
    r = client.post(
        "/api/auth/register",
        json={"email": "weak@gmail.com", "full_name": "W", "password": "short"},
    )
    assert r.status_code == 422  # password min length
    r = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "full_name": "W", "password": "secret123"},
    )
    assert r.status_code == 422


def test_registered_user_can_send_requests_but_not_tasks(client, org):
    r = client.post(
        "/api/auth/register",
        json={"email": "fresh@gmail.com", "full_name": "Fresh Joiner", "password": "secret123"},
    )
    cookies = dict(r.cookies)

    # no subtree -> cannot assign tasks to anyone
    t = client.post(
        "/api/tasks",
        json={"title": "x", "assignee_id": org["student"].id},
        cookies=cookies,
    )
    assert t.status_code == 403

    # but can request work from any staff member
    req = client.post(
        "/api/requests",
        json={"recipient_id": org["cto"].id, "title": "please help"},
        cookies=cookies,
    )
    assert req.status_code == 201
