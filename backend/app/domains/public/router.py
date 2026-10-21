"""Public, unauthenticated read API for the marketing website.

This is the ONLY surface the public website (mindtechrobotics.com) may call.
Everything it *returns* is deliberately anonymous and PII-free: it exposes a
member's public name and technical discipline and nothing else — never the
contact, national-ID, guardian, birthday or any other MemberProfile field, and
never a user id or email. Treat this router as published-to-the-world.

The one write is the join form: POST /applications takes an applicant's
answers in and answers only "received" — nothing stored is ever read back out
here (reviewers read applications through the authenticated /applications).

The Hall of Fame is the public projection of the portal's *archived competition*
events: the same records the internal Archive is built from, shaped exactly like
the website's existing `CompetitionRecord` so the site can consume it directly.
The record shape itself lives in app/domains/events/hall_of_fame.py, shared with
the Archive so the two views can never drift.
"""

from fastapi import APIRouter, Request, status

from app.core.database import DB
from app.domains.applications import service as applications
from app.domains.applications.schemas import ApplicationIn
from app.domains.events.hall_of_fame import archived_competitions, record_out, summary

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/hall-of-fame")
def hall_of_fame(db: DB) -> list[dict]:
    """Every archived competition, newest first, in the website's CompetitionRecord
    shape: {id, event, fullName, year, awards, groups[{label, sublabel, award,
    members[{name, role}]}]}. Unauthenticated and PII-free."""
    return [record_out(event) for event in db.scalars(archived_competitions()).all()]


@router.get("/hall-of-fame/summary")
def hall_of_fame_summary(db: DB) -> dict:
    """What the record adds up to: competitions entered, seasons, members
    fielded, and the medal tally — counted from the same archived competitions
    /hall-of-fame returns, so the headline numbers can never disagree with the
    records printed underneath them."""
    return summary(list(db.scalars(archived_competitions()).all()))


@router.post("/applications", status_code=status.HTTP_201_CREATED)
def apply(payload: ApplicationIn, request: Request, db: DB) -> dict:
    """The website's "Join the team" form. Unauthenticated; rate-limited per
    connection, with a honeypot field for bots. Sending again within a day
    updates the earlier application rather than adding another."""
    applications.submit(db, payload, applications.client_hash(request))
    return {"received": True}
