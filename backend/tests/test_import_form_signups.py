"""Google Form sign-ups -> roster: existing members matched by email/phone and
left alone, new ones get the next MTR ID + a Google-linked Member account,
name-only look-alikes flagged for review, and re-runs add nothing."""

from datetime import datetime

import openpyxl

from app.domains.users.models import User
from tests.conftest import make_member
from scripts import import_form_signups as imp

HEADERS = ["Timestamp", "Email Address", "Name", "Whatsapp phone no.", "Track"]


def _responses(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    ws.append([datetime(2026, 10, 12, 18, 0), "Known@t.local", "Known Again", "01200000001", "Software"])
    ws.append([datetime(2026, 10, 12, 18, 5), "newphone@gmail.com", "Phone Match", "+20 1200000002", "Mechanical"])
    ws.append([datetime(2026, 10, 12, 18, 10), "fresh@gmail.com", "  Fresh   Person ", 1200000003.0, "Electrical"])
    ws.append([datetime(2026, 10, 13, 9, 0), "fresh@gmail.com", "Fresh Person", "0120 000 0004", "Electrical"])
    ws.append([datetime(2026, 10, 13, 10, 0), "twin@gmail.com", "Roster Name", "01200000009", "Software"])
    path = tmp_path / "responses.xlsx"
    wb.save(path)
    return str(path)


def test_form_signups_add_only_new_members(db_session, tmp_path):
    db = db_session
    make_member(db, "Known", mtr_id="MTR-010", email="known@t.local", phone="01200000001")
    make_member(db, "Phone Owner", mtr_id="MTR-011", phone="01200000002")
    make_member(db, "Roster Name", mtr_id="MTR-012", email="other@t.local")
    db.commit()

    path = _responses(tmp_path)
    imp.run(db, path, "GT S4")
    db.commit()

    by_mtr = {p.mtr_id: p for p in db.query(User) if p.mtr_id}
    assert set(by_mtr) == {"MTR-010", "MTR-011", "MTR-012", "MTR-013", "MTR-014"}
    assert by_mtr["MTR-010"].full_name == "Known"  # existing member untouched
    assert by_mtr["MTR-011"].email == "newphone@gmail.com"  # blank filled from the form

    fresh = by_mtr["MTR-013"]  # the duplicate answer collapsed, latest wins
    assert (fresh.full_name, fresh.phone, fresh.data_confidence) == ("Fresh Person", "01200000004", "single")
    account = db.query(User).filter_by(email="fresh@gmail.com").one()
    assert fresh.id == account.id and account.google_linked_at is not None

    twin = by_mtr["MTR-014"]
    assert twin.data_confidence == "review" and "MTR-012" in twin.review_note

    imp.run(db, path, "GT S4")
    db.commit()
    assert db.query(User).filter(User.mtr_id.is_not(None)).count() == 5
