"""The generic, admin-configurable role-chain engine: template CRUD and
ordering, the single ask-once root, event-triggered seating (competition/
team/member), multi-occupancy, seat-level authority (a seat whose access
level carries competitions.manage_seated makes its occupants that entity's
managers), retitle/removal cascades, and the manager_id/real-seat exclusion
guarantee — all without any role name ever being hardcoded in the app."""

from tests.conftest import ensure_position, seat_role


def _tree_by_title(login):
    def walk(nodes):
        out = {}
        for n in nodes:
            out[n["title"]] = n
            out.update(walk(n["children"]))
        return out
    return walk(login("admin").get("/api/org/tree").json())


def _level_id(login, name: str) -> int:
    levels = login("admin").get("/api/access/levels").json()
    return next(lvl["id"] for lvl in levels if lvl["name"] == name)


def _template(login, *, title, event, level=None, who="admin"):
    body = {"title_template": title, "event": event}
    if level is not None:
        body["access_level_id"] = _level_id(login, level)
    r = login(who).post("/api/org/roles/templates", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _comp(login, root=None, who="cto", name="Cup"):
    body = {"name": name}
    if root is not None:
        body["role_root_position_id"] = root
    r = login(who).post("/api/competitions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _team(login, cat_id, root=None, who="cto", name="Alpha"):
    body = {"name": name}
    if root is not None:
        body["role_root_position_id"] = root
    r = login(who).post(f"/api/competitions/categories/{cat_id}/teams", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_template_crud_auto_orders_and_renumbers(login, org):
    a = _template(login, title="{competition} PM", event="competition_created")
    b = _template(login, title="{team} Lead", event="team_created")
    c = _template(login, title="{member}", event="team_member_added")
    assert [t["sort_order"] for t in [a, b, c]] == [1, 2, 3]

    templates = login("admin").get("/api/org/roles/templates").json()
    assert [t["id"] for t in templates] == [a["id"], b["id"], c["id"]]

    assert login("admin").delete(f"/api/org/roles/templates/{b['id']}").status_code == 204
    remaining = login("admin").get("/api/org/roles/templates").json()
    assert [t["sort_order"] for t in remaining] == [1, 2]  # renumbered, no gap

    # only org.edit levels may configure roles
    assert login("cto").post(
        "/api/org/roles/templates",
        json={"title_template": "x", "event": "competition_created"},
    ).status_code == 403


def test_first_role_position_requires_a_parent_then_remembers_it(login, org):
    _template(login, title="{competition} PM", event="competition_created")
    r = login("cto").post("/api/competitions", json={"name": "No Root Yet"})
    assert r.status_code == 400

    root = ensure_position(login("admin"))
    comp_a = _comp(login, root=root, name="Cup A")
    root_info = login("admin").get("/api/org/roles/root").json()
    assert root_info["root_position_id"] == root
    assert root_info["has_templates"] is True

    # a second competition doesn't need to ask again
    comp_b = _comp(login, name="Cup B")
    tree = _tree_by_title(login)
    assert tree["Cup A PM"]["parent_id"] == root
    assert tree["Cup B PM"]["parent_id"] == root
    assert comp_a["roles"][0]["title"] == "Cup A PM"


def test_seats_start_vacant_and_seat_level_confers_scoped_management(login, org):
    _template(login, title="{competition} PM", event="competition_created", level="Lead")
    comp = _comp(login, root=ensure_position(login("admin")))
    pos_id = comp["roles"][0]["position_id"]

    # nothing auto-seats the creator: the seat starts vacant and the creator
    # has no authority over what they just made
    assert comp["roles"][0]["occupants"] == []
    assert login("cto").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is False

    # appoint the creator + a plain staff member — the seat holds both, and
    # the SEAT's level (Lead, which carries competitions.manage_seated) makes
    # both of them managers, regardless of their own personal levels
    seat_role(login("admin"), comp, [org["cto"].id, org["sw_emp"].id])
    r = login("admin").get(f"/api/org/tree")
    assert login("cto").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is True
    assert login("sw_emp").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is True
    # someone not seated still can't manage it
    assert login("student").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is False

    # a seated manager can appoint others (entity-manager path, not org.edit)
    r = login("cto").put(
        f"/api/org/roles/positions/{pos_id}/occupants",
        json={"user_ids": [org["cto"].id]},
    )
    assert r.status_code == 200, r.text
    assert [u["id"] for u in r.json()["occupants"]] == [org["cto"].id]
    assert login("sw_emp").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is False


def test_pm_seat_never_sets_manager_id_or_evicts_a_real_seat(login, org):
    admin = login("admin")
    ceo_seat = admin.post("/api/org/positions", json={
        "title": "CEO Seat", "occupant_ids": [org["ceo"].id],
    }).json()
    admin.post("/api/org/positions", json={
        "title": "CTO Seat", "parent_id": ceo_seat["id"], "occupant_ids": [org["cto"].id],
    })
    assert login("cto").get("/api/auth/me").json()["manager_id"] == org["ceo"].id

    _template(login, title="{competition} PM", event="competition_created")
    comp = _comp(login, root=ceo_seat["id"])
    seat_role(admin, comp, [org["cto"].id])

    tree = _tree_by_title(login)
    assert tree["CTO Seat"]["occupants"][0]["id"] == org["cto"].id  # not evicted by becoming a PM
    assert tree["Cup PM"]["occupants"][0]["id"] == org["cto"].id
    me = login("cto").get("/api/auth/me").json()
    assert me["manager_id"] == org["ceo"].id  # unaffected by the PM seat


def test_manager_id_picks_earliest_occupant_of_a_multi_occupant_parent(login, org):
    admin = login("admin")
    top = admin.post("/api/org/positions", json={
        "title": "Co-Leadership", "occupant_ids": [org["ceo"].id, org["cfo"].id],
    }).json()
    admin.post("/api/org/positions", json={
        "title": "Report", "parent_id": top["id"], "occupant_ids": [org["cto"].id],
    })
    assert login("cto").get("/api/auth/me").json()["manager_id"] == org["ceo"].id  # earliest-added


def test_four_level_chain_seats_correctly(login, org):
    """pm (competition) -> coach (team) -> team_lead (team) -> member (membership)."""
    _template(login, title="{competition} PM", event="competition_created", level="Lead")
    _template(login, title="{team} Coach", event="team_created")
    _template(login, title="{team} Lead", event="team_created", level="Lead")
    _template(login, title="{member}", event="team_member_added")

    root = ensure_position(login("admin"))
    comp = _comp(login, root=root, name="Cup")
    seat_role(login("admin"), comp, [org["cto"].id])
    cat = login("cto").post(f"/api/competitions/{comp['id']}/categories", json={"name": "Senior"}).json()
    team = _team(login, cat["id"], name="Alpha")
    login("cto").post(f"/api/competitions/teams/{team['id']}/members", json={"user_id": org["student"].id})

    tree = _tree_by_title(login)
    stud = org["student"].full_name
    assert tree["Cup PM"]["parent_id"] == root
    assert tree["Alpha Coach"]["parent_id"] == tree["Cup PM"]["id"]
    assert tree["Alpha Lead"]["parent_id"] == tree["Alpha Coach"]["id"]
    assert tree[stud]["parent_id"] == tree["Alpha Lead"]["id"]
    assert tree[stud]["occupants"][0]["id"] == org["student"].id  # auto-occupied, no manual pick


def test_team_lead_role_grants_member_management(login, org):
    _template(login, title="{competition} PM", event="competition_created", level="Lead")
    _template(login, title="{team} Lead", event="team_created", level="Lead")
    root = ensure_position(login("admin"))
    comp = _comp(login, root=root)
    seat_role(login("admin"), comp, [org["cto"].id])
    cat = login("cto").post(f"/api/competitions/{comp['id']}/categories", json={"name": "Senior"}).json()
    team = _team(login, cat["id"])
    lead_pos = team["roles"][0]["position_id"]
    login("cto").put(f"/api/org/roles/positions/{lead_pos}/occupants", json={"user_ids": [org["student"].id]})

    detail = login("student").get(f"/api/competitions/{comp['id']}").json()
    assert detail["can_manage"] is False
    assert detail["categories"][0]["teams"][0]["can_manage_members"] is True


def test_retitle_cascades_through_the_whole_chain(login, org):
    _template(login, title="{competition} PM", event="competition_created", level="Lead")
    _template(login, title="{team} Lead", event="team_created")
    _template(login, title="{member}", event="team_member_added")
    root = ensure_position(login("admin"))
    comp = _comp(login, root=root, name="Old Comp")
    seat_role(login("admin"), comp, [org["cto"].id])
    cat = login("cto").post(f"/api/competitions/{comp['id']}/categories", json={"name": "Senior"}).json()
    team = _team(login, cat["id"], name="Old Team")
    login("cto").post(f"/api/competitions/teams/{team['id']}/members", json={"user_id": org["student"].id})

    login("cto").patch(f"/api/competitions/{comp['id']}", json={"name": "New Comp"})
    login("cto").patch(f"/api/competitions/teams/{team['id']}", json={"name": "New Team"})

    tree = _tree_by_title(login)
    assert "New Comp PM" in tree and "Old Comp PM" not in tree
    assert "New Team Lead" in tree and "Old Team Lead" not in tree


def test_archive_removes_the_whole_subtree_and_reactivate_rebuilds_it(login, org):
    _template(login, title="{competition} PM", event="competition_created", level="Lead")
    _template(login, title="{team} Lead", event="team_created")
    _template(login, title="{member}", event="team_member_added")
    root = ensure_position(login("admin"))
    comp = _comp(login, root=root, name="Doomed")
    seat_role(login("admin"), comp, [org["cto"].id])
    cat = login("cto").post(f"/api/competitions/{comp['id']}/categories", json={"name": "Senior"}).json()
    team = _team(login, cat["id"], name="Squad")
    login("cto").post(f"/api/competitions/teams/{team['id']}/members", json={"user_id": org["student"].id})

    stud = org["student"].full_name
    login("cto").patch(f"/api/competitions/{comp['id']}", json={"status": "archived"})
    tree = _tree_by_title(login)
    # gone from the org chart entirely — it only shows active work
    assert "Doomed PM" not in tree and "Squad Lead" not in tree and stud not in tree

    # reactivating rebuilds the structure: seats come back vacant (occupancy
    # isn't remembered), except member seats — the membership itself says who
    # sits there
    login("admin").patch(f"/api/competitions/{comp['id']}", json={"status": "active"})
    tree = _tree_by_title(login)
    assert tree["Doomed PM"]["parent_id"] == root
    assert tree["Doomed PM"]["occupants"] == []
    assert tree["Squad Lead"]["parent_id"] == tree["Doomed PM"]["id"]
    assert tree[stud]["parent_id"] == tree["Squad Lead"]["id"]
    assert [u["id"] for u in tree[stud]["occupants"]] == [org["student"].id]
    # cto's PM seat was not restored, so their authority is gone until
    # someone re-appoints them — only manage_any levels can act meanwhile
    assert login("cto").delete(f"/api/competitions/{comp['id']}").status_code == 403

    assert login("admin").delete(f"/api/competitions/{comp['id']}").status_code == 204
    tree = _tree_by_title(login)
    assert "Doomed PM" not in tree and "Squad Lead" not in tree and stud not in tree


def test_team_soft_and_permanent_delete_both_remove_positions(login, org):
    """Soft delete keeps the team row queryable as history, but its role
    positions leave the org chart either way — the chart only shows active
    work."""
    _template(login, title="{competition} PM", event="competition_created", level="Lead")
    _template(login, title="{team} Lead", event="team_created")
    _template(login, title="{member}", event="team_member_added")
    root = ensure_position(login("admin"))
    comp = _comp(login, root=root)
    seat_role(login("admin"), comp, [org["cto"].id])
    cat = login("cto").post(f"/api/competitions/{comp['id']}/categories", json={"name": "Senior"}).json()

    stud, comp_member = org["student"].full_name, org["comp_member"].full_name
    team_a = _team(login, cat["id"], name="Soft")
    login("cto").post(f"/api/competitions/teams/{team_a['id']}/members", json={"user_id": org["student"].id})
    assert login("cto").delete(f"/api/competitions/teams/{team_a['id']}").status_code == 204
    tree = _tree_by_title(login)
    assert "Soft Lead" not in tree and stud not in tree

    team_b = _team(login, cat["id"], name="Gone")
    login("cto").post(f"/api/competitions/teams/{team_b['id']}/members", json={"user_id": org["comp_member"].id})
    assert login("admin").delete(f"/api/competitions/teams/{team_b['id']}?permanent=true").status_code == 204
    tree = _tree_by_title(login)
    assert "Gone Lead" not in tree and comp_member not in tree


def test_reordering_a_template_live_reparents_existing_positions(login, org):
    coach = _template(login, title="{team} Coach", event="team_created")
    lead = _template(login, title="{team} Lead", event="team_created")
    root = ensure_position(login("admin"))
    comp = _comp(login, who="admin")
    cat = login("admin").post(f"/api/competitions/{comp['id']}/categories", json={"name": "Senior"}).json()
    _team(login, cat["id"], root=root, who="admin", name="Reorder")

    tree = _tree_by_title(login)
    assert tree["Reorder Lead"]["parent_id"] == tree["Reorder Coach"]["id"]

    # swap: Lead now comes first, Coach chains under it
    r = login("admin").patch(f"/api/org/roles/templates/{lead['id']}", json={"sort_order": 1})
    assert r.status_code == 200, r.text

    tree = _tree_by_title(login)
    assert tree["Reorder Lead"]["parent_id"] == root
    assert tree["Reorder Coach"]["parent_id"] == tree["Reorder Lead"]["id"]


def test_template_level_edit_propagates_to_existing_positions(login, org):
    """Changing a role's access level updates the seats it already produced —
    occupants gain/lose the scoped authority instantly."""
    tpl = _template(login, title="{competition} PM", event="competition_created")
    comp = _comp(login, root=ensure_position(login("admin")))
    seat_role(login("admin"), comp, [org["cto"].id])
    # seat has no level: occupancy confers nothing
    assert login("cto").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is False

    r = login("admin").patch(
        f"/api/org/roles/templates/{tpl['id']}",
        json={"access_level_id": _level_id(login, "Lead")},
    )
    assert r.status_code == 200, r.text
    assert login("cto").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is True

    r = login("admin").patch(f"/api/org/roles/templates/{tpl['id']}", json={"clear_access_level": True})
    assert r.status_code == 200, r.text
    assert login("cto").get(f"/api/competitions/{comp['id']}").json()["can_manage"] is False


def test_parent_template_id_previews_the_chain_before_anything_real_exists(login, org):
    """The org tree shows automatic roles nested where they'd chain even
    before any competition/team exists — parent_template_id (purely
    structural, no positions needed yet) is what makes that possible."""
    pm = _template(login, title="{competition} PM", event="competition_created")
    coach = _template(login, title="{team} Coach", event="team_created")
    lead = _template(login, title="{team} Lead", event="team_created")
    deputy = _template(login, title="{competition} Deputy PM", event="competition_created")

    templates = {t["id"]: t for t in login("admin").get("/api/org/roles/templates").json()}
    assert templates[pm["id"]]["parent_template_id"] is None  # nothing eligible before it — root
    assert templates[coach["id"]]["parent_template_id"] == pm["id"]
    assert templates[lead["id"]]["parent_template_id"] == coach["id"]
    # added last but same event as pm, and coach (in between) isn't eligible
    # for a competition-level role — still resolves to pm, not coach
    assert templates[deputy["id"]]["parent_template_id"] == pm["id"]


def test_insert_after_nests_new_role_under_the_clicked_parent(login, org):
    """Adding a role from an existing role's "+" in the tree sends
    insert_after_id: the new template slots in right after that one instead
    of appending at the end — appending would make it resolve under the last
    same-event sibling (Deputy here) rather than the node actually clicked."""
    pm = _template(login, title="{competition} PM", event="competition_created")
    deputy = _template(login, title="{competition} Deputy", event="competition_created")

    r = login("admin").post("/api/org/roles/templates", json={
        "title_template": "{team} Coach", "event": "team_created",
        "insert_after_id": pm["id"],
    })
    assert r.status_code == 201, r.text
    coach = r.json()
    assert coach["parent_template_id"] == pm["id"]

    templates = {t["id"]: t for t in login("admin").get("/api/org/roles/templates").json()}
    assert [templates[i]["sort_order"] for i in (pm["id"], coach["id"], deputy["id"])] == [1, 2, 3]
    # deputy still chains under pm — coach (team-level) can't parent a
    # competition-level role, so the insertion doesn't steal deputy away
    assert templates[deputy["id"]]["parent_template_id"] == pm["id"]


def test_template_added_after_entity_exists_blocks_dependents_instead_of_orphaning_to_root(login, org):
    """A template only ever seats itself when its own event fires (see
    apply_event) — adding one late never backfills it onto entities created
    before it existed. If a later-chained template's event then fires for
    one of those old entities, its prerequisite link is missing, so it must
    be skipped entirely rather than falling back to root (which would
    silently orphan it ahead of a role that's supposed to come first)."""
    old_comp = _comp(login, who="cto", name="Preexisting")  # created before any templates exist
    _template(login, title="{competition} PM", event="competition_created", level="Lead")
    _template(login, title="{team} Coach", event="team_created")

    # cto has no role seat on this old competition (PM never applied to it) —
    # only manage_any levels can manage it until someone configures things
    old_cat = login("admin").post(f"/api/competitions/{old_comp['id']}/categories", json={"name": "Senior"}).json()
    old_team = _team(login, old_cat["id"], who="admin", name="Alpha")  # no root passed — must never be needed

    tree = _tree_by_title(login)
    assert "Preexisting PM" not in tree  # never backfilled onto the pre-existing competition
    assert "Alpha Coach" not in tree  # blocked: its PM prerequisite doesn't exist for this competition
    assert old_team["roles"][0]["position_id"] is None
    assert old_team["roles"][0]["occupants"] == []

    # a *new* competition, created after both templates exist, chains normally
    root = ensure_position(login("admin"))
    new_comp = _comp(login, root=root, who="cto", name="Fresh")
    seat_role(login("admin"), new_comp, [org["cto"].id])
    new_cat = login("cto").post(f"/api/competitions/{new_comp['id']}/categories", json={"name": "Senior"}).json()
    _team(login, new_cat["id"], name="Beta")

    tree = _tree_by_title(login)
    assert tree["Fresh PM"]["parent_id"] == root
    assert tree["Beta Coach"]["parent_id"] == tree["Fresh PM"]["id"]


def test_deleting_a_template_splices_out_its_positions(login, org):
    pm = _template(login, title="{competition} PM", event="competition_created", level="Lead")
    coach = _template(login, title="{team} Coach", event="team_created")
    lead = _template(login, title="{team} Lead", event="team_created")
    root = ensure_position(login("admin"))
    comp = _comp(login, root=root, name="Splice")
    seat_role(login("admin"), comp, [org["cto"].id])
    cat = login("cto").post(f"/api/competitions/{comp['id']}/categories", json={"name": "Senior"}).json()
    _team(login, cat["id"], name="Team")

    tree = _tree_by_title(login)
    assert tree["Team Coach"]["parent_id"] == tree["Splice PM"]["id"]
    assert tree["Team Lead"]["parent_id"] == tree["Team Coach"]["id"]

    assert login("admin").delete(f"/api/org/roles/templates/{coach['id']}").status_code == 204
    tree = _tree_by_title(login)
    assert "Team Coach" not in tree
    assert tree["Team Lead"]["parent_id"] == tree["Splice PM"]["id"]  # spliced up to the PM seat
