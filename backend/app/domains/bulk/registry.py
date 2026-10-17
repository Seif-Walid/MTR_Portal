"""The bulk-editor table registry: a data-driven description of every DB
table an admin can mass-edit in the portal grid.

One `TableSpec` per table declares its columns (type, editability, foreign-key
reference), the existing per-domain privilege that gates it, and how a deleted
row is handled. A single generic validate/apply engine in `service.py` drives
every table off this registry — there is no per-table screen or endpoint.

Row serialization lives in `exporters.py` (one exporter per curated table, or
a generic attribute reader), shared by the grid and the Excel export so both
always agree on shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from sqlalchemy import select

from app.domains.access.models import AccessLevel
from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventStatus,
    EventTeam,
)
from app.domains.inventory.models import (
    Condition,
    InventoryItem,
    Location,
    LocationKind,
    StockMovement,
)
from app.domains.finance.models import (
    BudgetLine,
    CashTransfer,
    Currency,
    DuesDiscount,
    DuesEnrollment,
    DuesPayment,
    DuesTier,
    EnrollmentStatus,
    FinanceOption,
    FinanceParty,
    FinanceSeason,
    FundingLine,
    FundingStatus,
    OptionList,
    Payable,
    PayableStatus,
    SeasonStatus,
    Spending,
)
from app.domains.events.models import EventParticipation
from app.domains.positions.models import Position
from app.domains.users.models import Department, MemberProfile, User

ColType = Literal["int", "number", "str", "bool", "date", "datetime"]


@dataclass(frozen=True)
class Ref:
    """A foreign-key target: which model a reference column points at, whether
    it is matched by id/name/slug, and how to label a choice in the grid's
    dropdown."""

    model: type
    value_attr: str  # "id" | "name" | "slug" — the value stored in the cell
    label: Callable[[object], str]
    # optional narrowing of the target rows, e.g. one finance pick-list out of
    # the shared options table: a SQLAlchemy where-clause factory
    where: Callable[[], object] | None = None
    order_by: Callable[[], object] | None = None

    def query(self):
        q = select(self.model)
        if self.where is not None:
            q = q.where(self.where())
        if self.order_by is not None:
            q = q.order_by(self.order_by())
        return q


# Reference targets, keyed by the name a Column.ref points to.
REFS: dict[str, Ref] = {
    "user": Ref(User, "id", lambda u: f"{u.full_name} <{u.email}>"),
    "access_level": Ref(AccessLevel, "name", lambda l: l.name),
    "event_kind": Ref(EventKind, "slug", lambda k: f"{k.slug} — {k.name}"),
    "position": Ref(Position, "id", lambda p: p.title),
    "event": Ref(Event, "id", lambda e: e.name),
    "event_category": Ref(EventCategory, "id", lambda c: c.name),
    "event_team": Ref(EventTeam, "id", lambda t: t.name),
    "location": Ref(Location, "id", lambda l: l.name),
    "item": Ref(InventoryItem, "id", lambda i: i.name),
    "member": Ref(
        MemberProfile, "id",
        lambda m: f"{m.mtr_id} — {m.display_name}" if m.mtr_id else m.display_name,
        order_by=lambda: MemberProfile.mtr_id,
    ),
    "fin_season": Ref(FinanceSeason, "id", lambda s: s.name, order_by=lambda: FinanceSeason.sort_order),
    "fin_party": Ref(FinanceParty, "id", lambda p: p.name, order_by=lambda: FinanceParty.name),
    "dues_tier": Ref(DuesTier, "id", lambda t: t.name, order_by=lambda: DuesTier.sort_order),
}


def _option_ref(list_key: str) -> Ref:
    return Ref(
        FinanceOption, "id", lambda o: o.value,
        where=lambda: FinanceOption.list_key == list_key,
        order_by=lambda: FinanceOption.sort_order,
    )


for _key in OptionList:
    REFS[f"opt_{_key.value}"] = _option_ref(_key.value)


@dataclass(frozen=True)
class Column:
    name: str  # must match the exporter header exactly
    type: ColType = "str"
    editable: bool = True  # False -> shown read-only (ids, derived, joins)
    required: bool = False
    ref: str | None = None  # key into REFS
    attr: str | None = None  # model attribute to write (defaults to `name`)
    choices: tuple[str, ...] | None = None  # fixed enum values
    label: str | None = None  # grid header; defaults to the prettified name
    # input rules, enforced by the grid as you type and again by the server
    min: float | None = None
    max: float | None = None
    max_length: int | None = None
    pattern: str | None = None  # full-match regex for text cells
    pattern_hint: str | None = None  # what a valid value looks like, e.g. "MTR-123"

    @property
    def model_attr(self) -> str:
        return self.attr or self.name

    @property
    def header(self) -> str:
        if self.label:
            return self.label
        if self.name == "id":
            return "ID"
        return self.name.removesuffix("_id").replace("_", " ").capitalize()


DeletePolicy = Literal["soft", "deactivate", "hard", "none"]


@dataclass
class TableSpec:
    key: str
    label: str
    model: type
    columns: list[Column]
    privilege: str  # existing per-domain edit privilege
    delete: DeletePolicy
    # read_only tables are the auto-registered "every other table" specs: shown
    # in the grid for inspection, but no editing / delete.
    read_only: bool = False
    # append_only tables (the movements ledger) accept new rows only: existing
    # rows are locked and deletes are refused.
    append_only: bool = False
    # optional per-table guard run before a hard/soft delete; returns a blocking
    # message or None. Populated in service.py to avoid import cycles.
    delete_guard: Callable[[object, int], str | None] | None = field(default=None, repr=False)
    # grouping in the table list (e.g. "Finance") and a one-line explanation
    group: str = "Core"
    description: str = ""
    # filter the rows shown/exported (e.g. one pick-list of finance_options)
    where: Callable[[], object] | None = field(default=None, repr=False)
    # fixed column values for inserted rows (e.g. list_key for a pick-list)
    insert_values: dict = field(default_factory=dict)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)

    def live_clause(self):
        """The where-clause hiding rows this table's delete policy has retired
        (soft-deleted / deactivated) — the same rows the exporters leave out, so
        a retired row can't be edited, counted or "missing from the file"."""
        if self.delete == "soft":
            return self.model.deleted_at.is_(None)
        if self.delete == "deactivate":
            return self.model.is_active.is_(True)
        return None

    def filters(self) -> list:
        out = [] if self.where is None else [self.where()]
        live = self.live_clause()
        return out if live is None else [*out, live]


def _enum(e) -> tuple[str, ...]:
    return tuple(v.value for v in e)


# shared input rules
_EMAIL = dict(pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+", pattern_hint="an email address like name@gmail.com")
_PHONE = dict(pattern=r"\+?\d[\d \-]{6,15}", pattern_hint="a phone number like 01012345678 or +966…")
_PHONES = dict(pattern=r"\+?\d[\d \-]{6,15}(\s*[,/]\s*\+?\d[\d \-]{6,15})*",
               pattern_hint="one or more phone numbers, separated by commas")
_MONEY = dict(min=0)


# --- the tables -------------------------------------------------------------
# Column order mirrors the matching exporter header exactly.
TABLES: dict[str, TableSpec] = {
    "people": TableSpec(
        group="People",
        key="people", label="People", model=User, privilege="users.manage", delete="deactivate",
        columns=[
            Column("id", "int", editable=False),
            Column("email", "str", required=True, **_EMAIL),
            Column("full_name", "str", required=True, max_length=150),
            Column("department", "str", choices=_enum(Department)),
            Column("access_level", ref="access_level", attr="access_level_id"),
            Column("manager_id", "int", ref="user"),
            Column("is_active", "bool"),
        ],
    ),
    "member_profiles": TableSpec(
        # The roster (the member database's Members sheet). Gated at
        # members.edit since it holds member PII (national_id, guardians).
        # A row may have no portal account (user_id blank) — those can be
        # deleted here; members with an account are retired by deactivating
        # the account on the People tab (the guard below refuses the delete).
        key="member_profiles", label="Members (roster)", model=MemberProfile,
        privilege="members.edit", delete="hard", group="Members",
        columns=[
            Column("id", "int", editable=False),
            Column("mtr_id", "str", label="MTR ID", pattern=r"MTR-\d{3,}", pattern_hint="MTR- followed by the number, e.g. MTR-123"),
            Column("full_name", "str", label="Name", max_length=150),
            Column("email", "str", label="Gmail", **_EMAIL),
            Column("user_id", "int", ref="user", label="Portal account"),
            Column("phone", "str", **_PHONE),
            Column("national_id", "str", label="National ID", pattern=r"\d{14}", pattern_hint="the 14-digit national ID"),
            Column("birthday", "date"),
            Column("location", "str", label="Governorate"),
            Column("university", "str"),
            Column("college", "str"),
            Column("major", "str"),
            Column("uni_id", "str", label="College ID"),
            Column("graduating_year", "int", label="Grad year", min=2000, max=2100),
            Column("guardian_phone", "str", label="Guardian's number", **_PHONES),
            Column("guardian_kinship", "str", label="Guardian's kinship"),
            Column("joined_at", "datetime", label="First registration"),
            Column("data_confidence", "str", label="Confidence"),
            Column("source_records", "int", label="Source records"),
            Column("review_note", "str", label="Review note"),
        ],
    ),
    "event_participations": TableSpec(
        # One row per (member x event) — the member database's Participations.
        key="event_participations", label="Participations", model=EventParticipation,
        privilege="members.edit", delete="hard", group="Members",
        columns=[
            Column("id", "int", editable=False),
            Column("event_id", "int", ref="event", required=True, label="Event"),
            Column("member_id", "int", ref="member", required=True, label="Member"),
            Column("role", "str", label="Role / field"),
            Column("team", "str"),
            Column("mentor", "str", label="Coach / mentor"),
            Column("rating", "str"),
            Column("registered_at", "datetime", label="Registered"),
        ],
    ),
    "positions": TableSpec(
        group="Organization",
        key="positions", label="Org Positions", model=Position, privilege="org.edit", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("title", "str", required=True),
            Column("parent_id", "int", ref="position"),
            Column("occupant_ids", "str", editable=False),  # join column — edit on the Org page
            Column("is_technical", "bool"),
            Column("access_level", ref="access_level", attr="access_level_id"),
        ],
    ),
    "event_kinds": TableSpec(
        group="Events",
        key="event_kinds", label="Event Kinds", model=EventKind, privilege="org.edit", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("slug", "str", required=True),
            Column("name", "str", required=True),
            Column("event_label", "str"),
            Column("category_label", "str"),
            Column("team_label", "str"),
            Column("member_label", "str"),
            Column("sort_order", "int"),
        ],
    ),
    "events": TableSpec(
        key="events", label="Events", model=Event, privilege="events.manage_any", delete="hard",
        group="Events",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            # The official long-form title the public Hall of Fame heads the
            # record with; blank when `name` is the only name.
            Column("full_name", "str"),
            Column("kind", ref="event_kind", attr="kind_id"),
            Column("description", "str"),
            Column("start_date", "date"),
            Column("end_date", "date"),
            Column("status", "str", choices=_enum(EventStatus)),
            Column("code", "str", label="Event ID"),
            Column("level", "str"),
            Column("organizer", "str"),
            Column("location", "str"),
            Column("tracks", "str", label="Categories / tracks"),
            Column("result", "str", label="Result / placement"),
            Column("registered_count", "int", label="# Registered", min=0),
            Column("participants_count", "int", label="# Participants", min=0),
            Column("teams_count", "int", label="# Teams", min=0),
            Column("mentors", "str", label="Mentors / coaches"),
            Column("captains", "str", label="Team captain(s)"),
            Column("contact", "str", label="MTR contact"),
            Column("budget_total", "number", label="Budget (recorded)"),
            Column("actual_spend", "number", label="Actual spend (recorded)"),
            Column("currency", "str"),
            Column("funding_source", "str", label="Funding source / sponsor"),
            Column("registration_form", "str", label="Registration form"),
            Column("roster_source", "str", label="Roster source"),
            Column("notes", "str"),
            Column("prep_date", "str", label="Prep date"),
            Column("competition_days", "str", label="Competition day(s)"),
        ],
    ),
    "event_categories": TableSpec(
        group="Events",
        key="event_categories", label="Event Categories", model=EventCategory,
        privilege="events.manage_any", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("event_id", "int", ref="event", required=True),
            Column("name", "str", required=True),
        ],
    ),
    "event_teams": TableSpec(
        group="Events",
        key="event_teams", label="Event Teams", model=EventTeam,
        privilege="events.manage_any", delete="soft",
        columns=[
            Column("id", "int", editable=False),
            Column("category_id", "int", ref="event_category", required=True),
            Column("name", "str", required=True),
            # Per-team placement published in the Hall of Fame, e.g. "🥇 1st Place".
            Column("award", "str"),
        ],
    ),
    # NB: no "event_team_members" grid — that flat roster is unused; event
    # membership is held as role/position occupants (see the Org Positions
    # table and the event card's member count), so surfacing an always-empty
    # roster here only confused it with real membership.
    "inventory_locations": TableSpec(
        group="Inventory",
        key="inventory_locations", label="Inventory Locations", model=Location,
        privilege="inventory.edit", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            Column("kind", "str", choices=_enum(LocationKind)),
            Column("notes", "str"),
        ],
    ),
    "inventory_items": TableSpec(
        group="Inventory",
        key="inventory_items", label="Inventory Items", model=InventoryItem,
        privilege="inventory.edit", delete="soft",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            Column("category", "str"),
            Column("asset_tag", "str"),
            Column("sku", "str"),
            Column("quantity", "int", required=True, min=0),
            Column("low_stock_threshold", "int", min=0),
            Column("unit", "str"),
            Column("location", "str"),  # free-text location note, not the FK
            Column("condition", "str", choices=_enum(Condition)),
            Column("notes", "str"),
            Column("team_lead_id", "int", ref="user"),
        ],
    ),
    "inventory_movements": TableSpec(
        group="Inventory",
        key="inventory_movements", label="Inventory Movements (ledger)", model=StockMovement,
        privilege="inventory.edit", delete="none", append_only=True,
        columns=[
            Column("id", "int", editable=False),
            Column("item_id", "int", ref="item", required=True),
            Column("quantity", "int", required=True),
            Column("from_location_id", "int", ref="location"),
            Column("from_holder_id", "int", ref="user"),
            Column("to_location_id", "int", ref="location"),
            Column("to_holder_id", "int", ref="user"),
            Column("actor_id", "int", ref="user"),
            Column("reason", "str"),
            Column("created_at", "datetime", editable=False),
        ],
    ),

    # --- finance books -----------------------------------------------------
    "finance_seasons": TableSpec(
        key="finance_seasons", label="Seasons", model=FinanceSeason,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Seasons of the books. The USD rate converts USD budget prices; the start date anchors dues maturity.",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            Column("status", "str", choices=_enum(SeasonStatus)),
            Column("start_date", "date", label="Start"),
            Column("end_date", "date", label="End"),
            Column("usd_rate", "number", label="USD → EGP", min=0),
            Column("notes", "str"),
            Column("sort_order", "int", label="Order"),
        ],
    ),
    "budget_lines": TableSpec(
        key="budget_lines", label="Budget", model=BudgetLine,
        privilege="finance.edit", delete="hard", group="Finance",
        description="What the season plans to buy. FMV = full worth; needed cost = what is still to buy after in-stock. Grey columns are computed.",
        columns=[
            Column("id", "int", editable=False),
            Column("season_id", "int", ref="fin_season", required=True, label="Season"),
            Column("event_id", "int", ref="event", label="Event"),
            Column("subsystem_id", "int", ref="opt_subsystem", label="Subsystem"),
            Column("item", "str", required=True),
            Column("currency", "str", choices=_enum(Currency)),
            Column("unit_price", "number", label="Unit price", min=0),
            Column("unit_price_egp", "number", editable=False, label="Unit EGP"),
            Column("required_qty", "number", label="Required", min=0),
            Column("spare_qty", "number", label="Spare", min=0),
            Column("total_qty", "number", editable=False, label="Total qty"),
            Column("in_stock_qty", "number", label="In stock", min=0),
            Column("needed_qty", "number", editable=False, label="Needed qty"),
            Column("fmv", "number", editable=False, label="FMV (EGP)"),
            Column("needed_cost", "number", editable=False, label="Needed cost (EGP)"),
            Column("category_id", "int", ref="opt_category", label="Category"),
            Column("link_note", "str", label="Link / note"),
        ],
    ),
    "spendings": TableSpec(
        key="spendings", label="Spendings", model=Spending,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Money actually spent. Net = count × unit cost.",
        columns=[
            Column("id", "int", editable=False),
            Column("season_id", "int", ref="fin_season", required=True, label="Season"),
            Column("event_id", "int", ref="event", label="Event"),
            Column("spent_on", "date", label="Date"),
            Column("item", "str", required=True),
            Column("category_id", "int", ref="opt_category", label="Category"),
            Column("subcategory_id", "int", ref="opt_subcategory", label="Sub-category"),
            Column("count", "number", min=0),
            Column("unit_cost", "number", label="Unit cost", min=0),
            Column("net", "number", editable=False, label="Net (EGP)"),
            Column("method_id", "int", ref="opt_payment_method", label="Method"),
            Column("paid_by_id", "int", ref="fin_party", label="Paid by"),
            Column("receipt", "str", label="Receipt / link"),
            Column("note", "str"),
        ],
    ),
    "dues_tiers": TableSpec(
        key="dues_tiers", label="Dues tiers", model=DuesTier,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Fee schedule per season: monthly fee × months, and/or a one-time fee.",
        columns=[
            Column("id", "int", editable=False),
            Column("season_id", "int", ref="fin_season", required=True, label="Season"),
            Column("name", "str", required=True),
            Column("monthly_fee", "number", label="Monthly fee", min=0),
            Column("months", "int", min=0, max=36),
            Column("one_time_fee", "number", label="One-time fee", min=0),
            Column("sort_order", "int", label="Order"),
        ],
    ),
    "dues_discounts": TableSpec(
        key="dues_discounts", label="Dues discounts", model=DuesDiscount,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Loyalty discount by years with the team (0.5 = 50% off).",
        columns=[
            Column("id", "int", editable=False),
            Column("season_id", "int", ref="fin_season", required=True, label="Season"),
            Column("min_years", "int", label="From year"),
            Column("discount", "number", min=0, max=1),
            Column("label", "str"),
        ],
    ),
    "dues_enrollments": TableSpec(
        key="dues_enrollments", label="Dues roster", model=DuesEnrollment,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Who owes dues this season and on which tier. Maturity is counted from the join date unless overridden.",
        columns=[
            Column("id", "int", editable=False),
            Column("season_id", "int", ref="fin_season", required=True, label="Season"),
            Column("member_id", "int", ref="member", required=True, label="Member"),
            Column("tier_id", "int", ref="dues_tier", required=True, label="Tier"),
            Column("status", "str", choices=_enum(EnrollmentStatus)),
            Column("maturity_override", "int", label="Maturity override (yrs)"),
            Column("note", "str"),
        ],
    ),
    "dues_payments": TableSpec(
        key="dues_payments", label="Dues collection", model=DuesPayment,
        privilege="finance.edit", delete="hard", group="Finance",
        description="One row per payment. Positive = payment, negative = refund.",
        columns=[
            Column("id", "int", editable=False),
            Column("season_id", "int", ref="fin_season", required=True, label="Season"),
            Column("paid_on", "date", required=True, label="Date"),
            Column("member_id", "int", ref="member", required=True, label="Member"),
            Column("amount", "number", required=True, label="Amount (EGP)"),
            Column("method_id", "int", ref="opt_payment_method", label="Method"),
            Column("received_by_id", "int", ref="fin_party", label="Received by"),
            Column("note", "str"),
        ],
    ),
    "funding_lines": TableSpec(
        key="funding_lines", label="Funding", model=FundingLine,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Money coming in besides dues (projected dues are added automatically on the dashboard).",
        columns=[
            Column("id", "int", editable=False),
            Column("season_id", "int", ref="fin_season", required=True, label="Season"),
            Column("source", "str", required=True),
            Column("type_id", "int", ref="opt_funding_type", label="Type"),
            Column("amount", "number", label="Amount (EGP)", min=0),
            Column("status", "str", choices=_enum(FundingStatus)),
            Column("note", "str"),
        ],
    ),
    "payables": TableSpec(
        key="payables", label="Payables", model=Payable,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Money the team owes.",
        columns=[
            Column("id", "int", editable=False),
            Column("owed_to_id", "int", ref="fin_party", label="Owed to"),
            Column("description", "str", required=True),
            Column("season_id", "int", ref="fin_season", label="Season"),
            Column("amount", "number", label="Amount (EGP)", min=0),
            Column("due_date", "date", label="Due"),
            Column("status", "str", choices=_enum(PayableStatus)),
            Column("note", "str"),
        ],
    ),
    "cash_transfers": TableSpec(
        key="cash_transfers", label="Cash transfers", model=CashTransfer,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Money moved between holders. Leave 'From' blank for an opening balance.",
        columns=[
            Column("id", "int", editable=False),
            Column("transferred_on", "date", label="Date"),
            Column("from_party_id", "int", ref="fin_party", label="From"),
            Column("from_method_id", "int", ref="opt_payment_method", label="From method"),
            Column("amount", "number", label="Amount (EGP)", min=0),
            Column("fees", "number", label="Fees (EGP)", min=0),
            Column("to_party_id", "int", ref="fin_party", label="To"),
            Column("to_method_id", "int", ref="opt_payment_method", label="To method"),
            Column("note", "str"),
        ],
    ),
    "finance_parties": TableSpec(
        key="finance_parties", label="People & entities", model=FinanceParty,
        privilege="finance.edit", delete="hard", group="Finance",
        description="Cash holders, suppliers, sponsors and organizers money moves to or from.",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            Column("type_id", "int", ref="opt_party_type", label="Type"),
            Column("phone", "str", **_PHONE),
            Column("payment_handle", "str", label="Payment handle / account"),
            Column("is_active", "bool", label="Active"),
            Column("notes", "str"),
            Column("user_id", "int", ref="user", label="Portal account"),
        ],
    ),
}



_OPTION_LABELS = {
    OptionList.PAYMENT_METHOD: "Payment methods",
    OptionList.CATEGORY: "Categories",
    OptionList.SUBCATEGORY: "Sub-categories",
    OptionList.SUBSYSTEM: "Subsystems",
    OptionList.FUNDING_TYPE: "Funding types",
    OptionList.PARTY_TYPE: "Entity / role types",
}

# One grid per finance pick-list, all backed by the shared finance_options table.
for _list, _label in _OPTION_LABELS.items():
    TABLES[f"options_{_list.value}"] = TableSpec(
        key=f"options_{_list.value}", label=f"List: {_label}", model=FinanceOption,
        privilege="finance.edit", delete="hard", group="Finance",
        description="A pick-list used across the books. Renaming a value renames it everywhere.",
        where=(lambda lk=_list.value: FinanceOption.list_key == lk),
        insert_values={"list_key": _list.value},
        columns=[
            Column("id", "int", editable=False),
            Column("value", "str", required=True),
            Column("sort_order", "int", label="Order"),
        ],
    )

# --- read-only auto-registration -------------------------------------------
# Everything above is a hand-tuned, editable grid. Admins also want to *see*
# every other table on the server (auth sessions, audit log, role templates,
# position occupants, …). We reflect each remaining mapped table into a
# read-only TableSpec so the same generic grid can display it. These are
# gated behind "users.manage" (top-admin only) since they include sensitive
# internal tables, and they carry no editing or delete.
_READONLY_PRIVILEGE = "users.manage"
_readonly_loaded = False


def _prettify(table_name: str) -> str:
    return table_name.replace("_", " ").title()


def ensure_all_tables_registered() -> None:
    """Idempotently add a read-only spec for every mapped table not already
    curated above. Imports all domain model modules first so SQLAlchemy knows
    about every table, then registers the leftovers. Cheap after the first run."""
    global _readonly_loaded
    if _readonly_loaded:
        return

    import importlib
    import pkgutil

    import app.domains as _domains

    for mod in pkgutil.walk_packages(_domains.__path__, "app.domains."):
        if mod.name.endswith(".models"):
            importlib.import_module(mod.name)

    from app.core.database import Base

    curated = {spec.model.__table__.name for spec in TABLES.values()}
    autos: list[TableSpec] = []
    seen: set[str] = set()
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = cls.__table__
        name = table.name
        if name in TABLES or name in curated or name in seen:
            continue
        seen.add(name)
        autos.append(
            TableSpec(
                key=name,
                label=_prettify(name),
                model=cls,
                columns=[Column(c.key, "str", editable=False) for c in table.columns],
                privilege=_READONLY_PRIVILEGE,
                delete="none",
                read_only=True,
                group="System (read-only)",
            )
        )
    for spec in sorted(autos, key=lambda s: s.label):
        TABLES[spec.key] = spec
    _readonly_loaded = True
