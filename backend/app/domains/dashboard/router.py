from fastapi import APIRouter

from app.domains.auth.deps import DB, CurrentUser
from app.domains.dashboard import service
from app.domains.dashboard.schemas import Dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: DB, user: CurrentUser) -> Dashboard:
    """The Home triage roll-up: everything that needs the signed-in person
    right now (overdue / needs-review / waiting-on-you / due-today / this-week),
    gathered from tasks, work requests, and inventory returns."""
    return service.build(db, user)
