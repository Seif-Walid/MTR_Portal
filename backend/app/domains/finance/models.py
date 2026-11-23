"""The team's books: what the season plans to spend (budget), what it actually
spent, the member dues it expects and collects, the funding it secured, what it
owes, and where its cash physically sits.

Everything a value is *derived* from (needed quantity, FMV, net cost, dues
maturity and fee, cash balances) is computed in `service.py` from the stored
facts — never stored — so the books can't drift out of step with themselves.

The pick-lists (payment methods, categories, sub-categories, subsystems, funding
types, party types) are data: one `FinanceOption` table the treasurer edits in
the portal. Only states the math depends on (a funding line being Secured, a
payable being Paid, a dues enrolment being Withdrawn, a price's currency) are
fixed in code."""

from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Money and quantities: exact NUMERIC in the database, floats in Python.
Money = Numeric(14, 2, asdecimal=False)
Qty = Numeric(12, 3, asdecimal=False)


class OptionList(StrEnum):
    PAYMENT_METHOD = "payment_method"
    CATEGORY = "category"
    SUBCATEGORY = "subcategory"
    SUBSYSTEM = "subsystem"
    FUNDING_TYPE = "funding_type"
    PARTY_TYPE = "party_type"


class SeasonStatus(StrEnum):
    PLANNING = "planning"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Currency(StrEnum):
    EGP = "EGP"
    USD = "USD"


class FundingStatus(StrEnum):
    EXPECTED = "expected"
    SECURED = "secured"


class PayableStatus(StrEnum):
    OWED = "owed"
    PAID = "paid"


class EnrollmentStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class FinanceOption(Base):
    """One value of one admin-editable pick-list (see OptionList)."""

    __tablename__ = "finance_options"
    __table_args__ = (UniqueConstraint("list_key", "value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_key: Mapped[str] = mapped_column(String(30), index=True)
    value: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class FinanceSeason(Base):
    """A season of the books, e.g. "Season 2026/2027 (S4)", plus team-wide
    buckets like "General (team)". Carries the season's USD→EGP rate (budget
    prices entered in USD convert at it) and its start date (dues maturity is
    counted up to it)."""

    __tablename__ = "finance_seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=SeasonStatus.ACTIVE)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    usd_rate: Mapped[float] = mapped_column(Money, default=50)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class FinanceParty(Base):
    """An outside contact money moves to or from: suppliers, sponsors,
    organizers. Cash holders are portal accounts (see `holder_id` on the money
    rows); parties that used to stand for a holder keep `user_id` so old rows
    still resolve, and are shown as "legacy holder" when they have none."""

    __tablename__ = "finance_parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    type_id: Mapped[int | None] = mapped_column(
        ForeignKey("finance_options.id", ondelete="SET NULL"), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    type = relationship(FinanceOption, lazy="joined")


class BudgetLine(Base):
    """One planned purchase. FMV is the full worth of what the season needs;
    the needed cost is only what still has to be bought after what's in stock."""

    __tablename__ = "budget_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("finance_seasons.id"), index=True)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True, nullable=True
    )
    subsystem_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    item: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default=Currency.EGP)
    unit_price: Mapped[float] = mapped_column(Money, default=0)
    required_qty: Mapped[float] = mapped_column(Qty, default=0)
    spare_qty: Mapped[float] = mapped_column(Qty, default=0)
    in_stock_qty: Mapped[float] = mapped_column(Qty, default=0)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    link_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    season = relationship(FinanceSeason, lazy="joined")

    @property
    def unit_price_egp(self) -> float:
        rate = self.season.usd_rate if self.season is not None else 1
        return (self.unit_price or 0) * (rate if self.currency == Currency.USD else 1)

    @property
    def total_qty(self) -> float:
        return (self.required_qty or 0) + (self.spare_qty or 0)

    @property
    def needed_qty(self) -> float:
        return max(self.total_qty - (self.in_stock_qty or 0), 0)

    @property
    def fmv(self) -> float:
        return self.total_qty * self.unit_price_egp

    @property
    def needed_cost(self) -> float:
        return self.needed_qty * self.unit_price_egp


class Spending(Base):
    """Money actually spent. Net = count × unit cost (EGP)."""

    __tablename__ = "spendings"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("finance_seasons.id"), index=True)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True, nullable=True
    )
    event_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    spent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    item: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    subcategory_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    count: Mapped[float] = mapped_column(Qty, default=1)
    unit_cost: Mapped[float] = mapped_column(Money, default=0)
    method_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    # legacy: the party that paid, from the spreadsheet era — read-only now
    paid_by_id: Mapped[int | None] = mapped_column(ForeignKey("finance_parties.id"), nullable=True)
    # the account that paid it — always whoever logged it
    holder_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # optional supplier paid
    payee_party_id: Mapped[int | None] = mapped_column(
        ForeignKey("finance_parties.id", ondelete="SET NULL"), index=True, nullable=True
    )
    receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def net(self) -> float:
        return (self.count or 0) * (self.unit_cost or 0)


class DuesTier(Base):
    """A dues tier for one season: e.g. Active (600/mo × 7), Member (200/mo × 7),
    Mini-robots (one-time fee)."""

    __tablename__ = "dues_tiers"
    __table_args__ = (UniqueConstraint("season_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("finance_seasons.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    monthly_fee: Mapped[float] = mapped_column(Money, default=0)
    months: Mapped[int] = mapped_column(Integer, default=0)
    one_time_fee: Mapped[float] = mapped_column(Money, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DuesDiscount(Base):
    """Loyalty discount by maturity: members with at least `min_years` with the
    team get `discount` (a fraction, 0.5 = 50% off) on their monthly fee."""

    __tablename__ = "dues_discounts"
    __table_args__ = (UniqueConstraint("season_id", "min_years"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("finance_seasons.id", ondelete="CASCADE"), index=True)
    min_years: Mapped[int] = mapped_column(Integer, default=0)
    discount: Mapped[float] = mapped_column(Numeric(5, 4, asdecimal=False), default=0)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)


class DuesEnrollment(Base):
    """An *exception* to the derived dues roster. Who owes dues comes from the
    season's event teams (each event carries its `dues_tier_id`); a row here
    adds someone who isn't on a team, overrides their tier (`tier_id`, NULL =
    keep the derived one) or maturity, or marks them withdrawn (owes nothing
    more)."""

    __tablename__ = "dues_enrollments"
    __table_args__ = (UniqueConstraint("season_id", "member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("finance_seasons.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tier_id: Mapped[int | None] = mapped_column(ForeignKey("dues_tiers.id"), nullable=True)
    event_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default=EnrollmentStatus.ACTIVE)
    maturity_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    member = relationship("User", foreign_keys=[member_id], lazy="joined")
    tier = relationship(DuesTier, lazy="joined")


class DuesPayment(Base):
    """One dues payment (positive) or refund (negative)."""

    __tablename__ = "dues_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("finance_seasons.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Money)
    method_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    # legacy: the party that received it, from the spreadsheet era
    received_by_id: Mapped[int | None] = mapped_column(ForeignKey("finance_parties.id"), nullable=True)
    # the account that took the money — always whoever logged it
    holder_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    member = relationship("User", foreign_keys=[member_id], lazy="joined")
    holder = relationship("User", foreign_keys=[holder_id], lazy="joined")


class FundingLine(Base):
    """Money coming in besides dues: grants, sponsors, in-kind, carry-overs.
    A line is a plan until it is *received* (`received_on` + `holder_id`): then
    the money sits with that holder and counts in the cash balances."""

    __tablename__ = "funding_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("finance_seasons.id"), index=True)
    source: Mapped[str] = mapped_column(String(255))
    type_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Money, default=0)
    status: Mapped[str] = mapped_column(String(20), default=FundingStatus.EXPECTED)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    party_id: Mapped[int | None] = mapped_column(
        ForeignKey("finance_parties.id", ondelete="SET NULL"), index=True, nullable=True
    )
    received_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    method_id: Mapped[int | None] = mapped_column(
        ForeignKey("finance_options.id", ondelete="SET NULL"), index=True, nullable=True
    )
    holder_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )


class Payable(Base):
    """Money the team owes a supplier or organizer."""

    __tablename__ = "payables"

    id: Mapped[int] = mapped_column(primary_key=True)
    owed_to_id: Mapped[int | None] = mapped_column(ForeignKey("finance_parties.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(255))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("finance_seasons.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Money, default=0)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=PayableStatus.OWED)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CashTransfer(Base):
    """Money handed from one holder to another (`from_user_id` → `to_user_id`).
    A transfer with no sender is an opening balance. The `*_party_id` columns
    are the spreadsheet era's holders, kept read-only for old rows."""

    __tablename__ = "cash_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    transferred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    from_party_id: Mapped[int | None] = mapped_column(ForeignKey("finance_parties.id"), nullable=True)
    from_method_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Money, default=0)
    fees: Mapped[float] = mapped_column(Money, default=0)
    to_party_id: Mapped[int | None] = mapped_column(ForeignKey("finance_parties.id"), nullable=True)
    to_method_id: Mapped[int | None] = mapped_column(ForeignKey("finance_options.id"), nullable=True)
    from_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
