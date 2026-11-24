import html as html_lib
import logging
import threading

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.mail import send_email
from app.domains.notifications.models import Notification, NotificationType

log = logging.getLogger(__name__)

# Emails queued on a session are only sent once that session commits, so a
# rolled-back request (or an AI dry run) never mails anyone.
_PENDING_KEY = "pending_emails"


def notify(
    db: Session,
    user_id: int,
    type_: NotificationType,
    message: str,
    task_id: int | None = None,
    request_id: int | None = None,
) -> Notification:
    """Queue an in-app notification. Caller owns the commit.

    A task assignment also emails the assignee, after the commit."""
    n = Notification(
        user_id=user_id, type=type_, message=message, task_id=task_id, request_id=request_id
    )
    db.add(n)
    if type_ == NotificationType.TASK_ASSIGNED and task_id is not None:
        _queue_task_assigned_email(db, user_id, task_id)
    return n


def _queue_task_assigned_email(db: Session, user_id: int, task_id: int) -> None:
    from app.domains.tasks.models import Task
    from app.domains.users.models import User

    person = db.get(User, user_id)
    task = db.get(Task, task_id)
    if person is None or task is None or not person.email or not person.is_active:
        return
    if task.assigner_id == person.id:
        return  # nobody needs an email about a task they gave themselves
    assigner = db.get(User, task.assigner_id)
    by = assigner.full_name if assigner else "Someone"
    link = f"{settings.frontend_url.rstrip('/')}/tasks?task={task.id}"
    details = []
    if task.due_date:
        details.append(f"Due: {task.due_date:%a %d %b %Y}")
    if task.priority:
        details.append(f"Priority: {str(getattr(task.priority, 'value', task.priority)).title()}")
    description = (task.description or "").strip()

    text = (
        f"Hi {person.full_name},\n\n"
        f"{by} assigned you a task on the MindTech Robotics portal:\n\n"
        f"  {task.title}\n"
        + "".join(f"  {d}\n" for d in details)
        + (f"\n{description}\n" if description else "")
        + f"\nOpen it here:\n{link}\n"
    )
    esc = html_lib.escape
    html = (
        f"<p>Hi {esc(person.full_name)},</p>"
        f"<p>{esc(by)} assigned you a task on the MindTech Robotics portal:</p>"
        f"<p><strong>{esc(task.title)}</strong>"
        + "".join(f"<br>{esc(d)}" for d in details)
        + "</p>"
        + (f"<p style=\"white-space:pre-wrap\">{esc(description)}</p>" if description else "")
        + f'<p><a href="{esc(link)}">Open the task</a></p>'
    )
    db.info.setdefault(_PENDING_KEY, []).append(
        (person.email, f"New task: {task.title}"[:200], text, html)
    )


def _deliver(batch: list[tuple[str, str, str, str]]) -> None:
    for to, subject, text, html in batch:
        send_email(to, subject, text, html)  # never raises; failures are logged


def _start_delivery(batch: list[tuple[str, str, str, str]]) -> None:
    """Send off the request thread so a slow SMTP relay (or a team-wide
    fan-out) doesn't hold up the response."""
    threading.Thread(target=_deliver, args=(batch,), daemon=True, name="task-mail").start()


@event.listens_for(Session, "after_commit")
def _send_pending_emails(session: Session) -> None:
    batch = session.info.pop(_PENDING_KEY, None)
    if batch:
        try:
            _start_delivery(batch)
        except Exception:
            log.exception("could not start task email delivery")


@event.listens_for(Session, "after_rollback")
def _drop_pending_emails(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
