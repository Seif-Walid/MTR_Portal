"""Team time blocks: a team claiming a stretch of the calendar.

A block anchors to exactly one team — an *event* team (event_team_id) or an
*org* unit (position_id, the org-chart node whose subtree is the team). It then
occupies time in one of two shapes, chosen by `weekday_mask`:

- mask == 0  → a continuous span covering every day in [start_date, end_date]
  ("this team works the whole week").
- mask != 0  → only the selected weekdays inside [start_date, end_date]
  ("all the Mondays in the project"). Bit i (0..6) = Python weekday, Monday=0.

The calendar aggregator (app/domains/calendar) expands a block into concrete
CalendarItems; nothing else stores the per-day rows.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TimeBlock(Base):
    __tablename__ = "time_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)

    # exactly one of these is set (app-enforced); team_type says which
    team_type: Mapped[str] = mapped_column(String(10))  # "event" | "org"
    event_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    weekday_mask: Mapped[int] = mapped_column(Integer, default=0)  # 0 = whole span

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
