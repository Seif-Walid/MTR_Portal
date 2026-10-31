export interface UserBrief {
  id: number;
  email: string | null; // null for members the roster has no email for yet
  full_name: string;
  department: string | null;
  mtr_id?: string | null;
}

export interface MemberProfile {
  mtr_id: string | null;
  guardian_kinship?: string | null;
  joined_at?: string | null;
  data_confidence?: string | null;
  national_id: string | null;
  birthday: string | null; // ISO date
  university: string | null;
  college: string | null;
  major: string | null;
  graduating_year: number | null;
  phone: string | null;
  guardian_phone: string | null; // comma-separated; one or more numbers
  uni_id: string | null;
  location: string | null;
}

export interface LevelBrief {
  id: number;
  rank: number;
  name: string;
}

export interface Privilege {
  key: string;
  label: string;
}

export interface AccessLevel extends LevelBrief {
  privileges: string[];
  is_top: boolean;
}

export interface Me extends UserBrief {
  manager_id: number | null;
  level: LevelBrief | null; // strongest held level — a label; privileges add up
  levels: string[]; // every level held (seats + override)
  privileges: string[];
  has_team: boolean;
  google_linked: boolean;
  created_at: string;
  seats: string[];
  profile: MemberProfile;
}

export interface AdminUser extends UserBrief {
  manager_id: number | null;
  is_active: boolean;
  google_linked: boolean;
  created_at: string;
  access_level_id: number | null; // the personal override
  effective_level: string | null; // computed from seats + override
  levels: string[]; // every level held — their privileges add up
  effective_rank: number | null;
  seats: string[]; // org positions occupied — the org's reflection
  claimed: boolean; // has a password or a linked Google identity; false = waiting for its owner
  profile: MemberProfile; // the person's roster fields
}

export type TaskStatus =
  | 'todo'
  | 'in_progress'
  | 'submitted'
  | 'approved'
  | 'revision_requested';

export type Priority = 'low' | 'medium' | 'high' | 'urgent';

export interface Attachment {
  id: number;
  kind: 'file' | 'drive' | 'link';
  filename: string; // a link's label
  url: string | null; // links only
  content_type: string;
  size: number;
  uploaded_by_id: number;
  created_at: string;
}

export interface TaskComment {
  id: number;
  author: UserBrief;
  body: string;
  created_at: string;
}

export interface TaskHistoryEntry {
  actor: string;
  action: string;
  detail: string; // JSON string
  created_at: string;
}

export interface Task {
  id: number;
  title: string;
  description: string;
  assigner: UserBrief;
  assignee: UserBrief;
  due_date: string | null;
  priority: Priority;
  category: string | null;
  status: TaskStatus;
  origin_request_id: number | null;
  is_blocked: boolean;
  blocked_reason: string;
  batch_id: string | null;
  event_team_id: number | null;
  event_team_name: string | null;
  team_visible: boolean;
  course_material_id: number | null; // hands out a course task sheet
  course_id: number | null;
  created_at: string;
  updated_at: string;
  attachments: Attachment[];
  comments: TaskComment[];
}

/** A team every selected assignee is on — the candidate context for a task. */
export interface TeamOption {
  team_id: number;
  name: string;
  event_name: string;
  category_name: string;
  shared_with_me: boolean;
}

export type RequestStatus = 'pending' | 'accepted' | 'declined';

export interface WorkRequest {
  id: number;
  requester: UserBrief;
  recipient: UserBrief;
  title: string;
  description: string;
  priority: Priority;
  due_date: string | null;
  item: ItemBrief | null;
  quantity: number | null;
  status: RequestStatus;
  decline_reason: string | null;
  created_task_id: number | null;
  created_task_status: TaskStatus | null;
  created_at: string;
  resolved_at: string | null;
}

export interface TeamMember {
  user: UserBrief;
  manager_id: number | null;
  is_direct_report: boolean;
  task_counts: Partial<Record<TaskStatus, number>>;
  total_tasks: number;
}

export interface TeamBlock {
  kind: 'org' | 'event';
  team_id: number | null; // event-team id; null for the org block
  name: string;
  event_name: string | null;
  event_id: number | null;
  members: TeamMember[];
  position_id: number | null; // org unit this block schedules (org kind only)
  can_schedule: boolean; // viewer may create/edit this team's time blocks
  event_start: string | null; // event span (event kind only) — blocks stay inside it
  event_end: string | null;
}

export interface TimeBlock {
  id: number;
  team_type: 'event' | 'org';
  event_team_id: number | null;
  position_id: number | null;
  title: string;
  start_date: string; // ISO date
  end_date: string; // ISO date
  weekday_mask: number; // 0 = whole span; else bit i (Mon=0..Sun=6)
  start_time: string | null; // "HH:MM:SS"; both null = all-day
  end_time: string | null;
}

export interface ArchivedEvent {
  id: number;
  name: string;
  full_name?: string | null; // official long-form title, e.g. "MATE ROV Competition"
  kind_id?: number | null;
  kind_slug?: string | null;
  kind_name: string | null;
  kind_label: string | null;
  team_label?: string | null; // what this kind calls a team ("Group" for Training)
  member_label?: string | null;
  start_date: string | null;
  end_date: string | null;
  awards?: string[] | null; // event-wide placements shown in the public Hall of Fame
  can_manage?: boolean; // may reactivate
  can_edit?: boolean; // may edit the record (archive.edit)
}

/** What the whole archived record adds up to — the headline the public site
 * prints above its Hall of Fame, counted from the same events. */
export interface ArchiveSummary {
  competitions: number;
  seasons: number;
  members_fielded: number;
  gold: number;
  silver: number;
  bronze: number;
  special: number; // judged awards that name no placement
}

/** One event kind as a section of the archive, with its archived-event count. */
export interface ArchiveKind {
  id: number;
  slug: string;
  name: string;
  event_label: string;
  count: number;
}

/** Someone who held one of an archived event's role seats (PM, coach, lead …),
 * recorded when it was archived — or added by hand from the archive. */
export interface ArchivedStaff {
  id: number; // the record row id
  role: string;
  name: string;
  user_id?: number | null;
  team?: string | null; // only for a seat whose team has since been deleted
}

export interface ArchivedTask {
  outcome: 'accomplished' | 'incomplete';
  team_name: string;
  task: Task;
}

export interface ArchivedMember {
  id: number; // membership row id
  name: string;
  role?: string | null;
}

/** One team of an archived event, in the same shape the public website reads. */
export interface ArchivedGroup {
  id: number; // team row id
  label: string;
  sublabel?: string | null;
  award?: string | null;
  members: ArchivedMember[];
  staff: ArchivedStaff[]; // the team's role seats: coach, lead, …
}

export interface ArchivedEventDetail {
  event: ArchivedEvent;
  staff: ArchivedStaff[]; // event-wide seats, e.g. the PMs
  mentors?: string | null; // the event record's free-text staff fields
  captains?: string | null;
  groups: ArchivedGroup[]; // the whole roster — what the public site publishes
  teams: string[]; // the viewer's teams within this event
  tasks: ArchivedTask[];
}

export type Condition = 'new' | 'good' | 'fair' | 'poor' | 'damaged';

export type AllocationPurpose =
  | 'training'
  | 'event'
  | 'research'
  | 'borrowed'
  | 'other';

export type EventStatus = 'active' | 'archived';

export interface EventKind {
  id: number;
  slug: string;
  name: string; // the tab / kind name, e.g. "Training"
  event_label: string; // one instance, e.g. "Training Season"
  category_label: string;
  team_label: string; // e.g. "Group"
  member_label: string;
  sort_order: number;
}

export interface EventBrief {
  id: number;
  name: string;
  status: EventStatus;
}

export interface EventMember {
  id: number; // membership row id
  user: UserBrief;
  role?: string | null; // competition role shown in the public Hall of Fame
}

export interface EntityRole {
  template_id: number;
  title: string;
  position_id: number | null;
  occupants: UserBrief[];
}

export interface EventTeam {
  id: number;
  name: string;
  parent_team_id: number | null; // the team (same category) this sub-team sits in; null = top level
  award?: string | null; // per-team placement shown in the public Hall of Fame
  roles: EntityRole[];
  members: EventMember[];
  can_manage_members: boolean; // also: may add sub-teams
  can_edit: boolean; // may rename / remove / set the placement
}

export interface EventCategory {
  id: number;
  name: string;
  teams: EventTeam[];
}

export interface Event extends EventBrief {
  full_name?: string | null; // official long-form title, e.g. "MATE ROV Competition"
  description: string;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  awards?: string[] | null; // competition-wide placements shown in the public Hall of Fame
  applications_open?: boolean; // the website's join form recruits for it
  public_summary?: string | null; // the pitch the website prints with it
  kind: EventKind | null;
  roles: EntityRole[];
  category_count: number;
  team_count: number;
  member_count: number;
  allocation_count: number;
  can_manage: boolean;
  code?: string | null;
  record?: Record<string, string | number>;
  participation_count?: number;
}

export interface EventDetail extends Event {
  categories: EventCategory[];
}

export interface Allocation {
  id: number;
  quantity: number;
  purpose: AllocationPurpose;
  label: string;
  event: EventBrief | null;
  display_label: string; // event name if linked, else the free-text label
  holder: UserBrief | null;
  notes: string;
  created_at: string;
}

export interface Location {
  id: number;
  name: string;
  kind: string;
  notes: string;
}

export interface PlaceOnHand {
  location: Location | null;
  holder: UserBrief | null;
  quantity: number;
}

export interface Whereabouts {
  owned: number;
  tracked: number;
  low_stock: boolean;
  by_location: PlaceOnHand[];
  by_holder: PlaceOnHand[];
}

export interface StockMovement {
  id: number;
  quantity: number;
  from_location: Location | null;
  to_location: Location | null;
  from_holder: UserBrief | null;
  to_holder: UserBrief | null;
  reason: string;
  created_at: string;
}

export type InventoryRequestStatus = 'submitted' | 'approved' | 'rejected' | 'issued' | 'returned';

export interface ItemBrief {
  id: number;
  name: string;
  unit: string;
}

export interface InventoryRequest {
  id: number;
  item: ItemBrief;
  requester: UserBrief;
  quantity: number;
  reason: string;
  needed_by: string | null;
  return_by: string | null;
  status: InventoryRequestStatus;
  approver: UserBrief | null;
  decision_reason: string;
  issued_at: string | null;
  returned_at: string | null;
  created_at: string;
  is_overdue: boolean;
}

export interface InventoryItem {
  id: number;
  name: string;
  category: string | null;
  asset_tag: string | null;
  sku: string | null;
  quantity: number; // total owned
  low_stock_threshold: number;
  unit: string;
  location: string | null;
  condition: Condition;
  notes: string;
  team_lead: UserBrief | null;
  in_use: number;
  free: number;
  by_purpose: Partial<Record<AllocationPurpose, number>>;
  allocations: Allocation[];
  created_at: string;
  updated_at: string;
}

export interface ImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export interface FileImportPreview {
  sheets: string[] | null; // workbook tab names (xlsx); null for CSV
  sheet: string | null;
  headers: string[];
  rows: Record<string, string>[];
  total: number;
}

export interface OrgTreeNode {
  id: number;
  full_name: string;
  email: string;
  department: string | null;
  level: string | null; // effective access level name
  manager_id: number | null;
  is_active: boolean;
  can_manage: boolean;
  children: OrgTreeNode[];
}

export interface PositionNode {
  id: number;
  title: string;
  is_technical: boolean;
  on_website?: boolean; // listed on the public website's People page
  parent_id: number | null;
  access_level_id: number | null; // power this seat confers
  occupants: UserBrief[];
  role_template_id: number | null;
  children: PositionNode[];
}

export type RoleEvent = 'event_created' | 'team_created' | 'team_member_added';

export interface RoleTemplate {
  id: number;
  title_template: string;
  event: RoleEvent;
  sort_order: number;
  access_level_id: number | null; // power the produced seats confer
  event_kind_id: number | null; // which event kind fires it; null = all kinds
  parent_template_id: number | null;
}

export interface RoleRoot {
  root_position_id: number | null;
  has_templates: boolean;
}

export interface AuditEntry {
  id: number;
  actor: string;
  domain: string;
  action: string;
  entity_type: string;
  entity_id: number | null;
  detail: string; // JSON string
  created_at: string;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  domains: string[];
}

export interface AppNotification {
  id: number;
  type: string;
  message: string;
  task_id: number | null;
  request_id: number | null;
  is_read: boolean;
  created_at: string;
}

export interface DashboardItem {
  source: 'task' | 'request' | 'inventory' | 'event';
  id: number;
  title: string;
  detail: string | null;
  due: string | null; // ISO date
  overdue: boolean;
  blocked: boolean;
  status: string | null;
  priority: string | null;
  action: string;
}

export interface DashboardSection {
  key: string; // overdue | review | waiting | today | week
  label: string;
  tone: 'danger' | 'normal';
  count: number; // full bucket size (may exceed items.length)
  items: DashboardItem[];
}

export interface DashboardStat {
  key: string;
  label: string;
  count: number;
  tone: 'danger' | 'normal';
}

export interface Dashboard {
  as_of: string; // ISO date
  greeting_name: string;
  is_reviewer: boolean;
  all_clear: boolean;
  stats: DashboardStat[];
  sections: DashboardSection[];
}

export type CalendarSource = 'task' | 'event' | 'inventory' | 'request' | 'team';

export interface CalendarItem {
  source: CalendarSource;
  id: number;
  title: string;
  start: string; // ISO date
  end: string | null; // ISO date; set only for multi-day event spans
  kind: string | null;
  detail: string | null;
  overdue: boolean;
  start_time: string | null; // "HH:MM:SS"; both null = all-day
  end_time: string | null;
}

// --- finance books ----------------------------------------------------------
export interface FinanceSeasonBrief {
  id: number;
  name: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
  usd_rate: number;
}

export interface CashMatrix {
  methods: { id: number | null; name: string }[];
  rows: { party_id: number; name: string; cells: Record<string, number>; total: number }[];
  totals: Record<string, number>;
  total: number;
}

export interface FinanceDashboard {
  seasons: FinanceSeasonBrief[];
  season_id: number | null;
  kpis: {
    plan_needed: number;
    plan_fmv: number;
    spent: number;
    dues_collected: number;
    funding_secured: number;
    funding_expected: number;
    cash_on_hand: number;
    projected_dues: number;
    dues_coverage: number;
    gap: number;
    owed: number;
  };
  per_season: { season_id: number; season: string; fmv: number; needed: number; spent: number; left: number; status: string }[];
  by_subsystem: { name: string; fmv: number; needed: number }[];
  by_category: { name: string; needed: number; spent: number }[];
  by_event: { name: string; needed: number; spent: number }[];
  monthly: { month: string; collected: number; spent: number }[];
  funding: { source: string; type: string | null; amount: number; status: string; season_id: number }[];
  cash: CashMatrix;
}

export interface DuesRow {
  enrollment_id: number;
  member_id: number;
  name: string;
  mtr_id: string | null;
  tier: string;
  joined_at: string | null;
  maturity: number;
  maturity_overridden: boolean;
  discount: number;
  monthly_fee: number;
  status: string;
  months_due: number;
  monthly: Record<string, number>;
  paid: number;
  expected: number;
  balance: number;
  note: string | null;
}

export interface DuesLedger {
  season: FinanceSeasonBrief;
  months: string[];
  rows: DuesRow[];
  projection: {
    tier: string; discount: number; base: number; monthly_fee: number; months: number;
    one_time_fee: number; members: number; projected: number;
  }[];
  totals: {
    members: number; active: number; projected: number; collected: number; expected: number;
    balance: number; unenrolled_paid: number; by_month: Record<string, number>;
  };
}

export interface EventMoney {
  has_books: boolean;
  planned_fmv: number;
  planned_needed: number;
  spent: number;
  budget_lines: number;
}

// --- member roster ----------------------------------------------------------
export interface RosterMember {
  id: number;
  mtr_id: string | null;
  name: string;
  email: string | null;
  phone: string | null;
  university: string | null;
  college: string | null;
  major: string | null;
  graduating_year: number | null;
  location: string | null;
  joined_at: string | null;
  data_confidence: string | null;
  claimed: boolean; // account set up (password or Google linked)?
  is_active: boolean;
  events: string[];
}

export interface Participation {
  id: number;
  event_id: number;
  event_name: string;
  event_code: string | null;
  event_kind: string | null;
  event_start: string | null;
  role: string | null;
  team: string | null;
  mentor: string | null;
  rating: string | null;
  registered_at: string | null;
}

export interface RosterMemberDetail extends RosterMember {
  full_name: string | null;
  national_id: string | null;
  birthday: string | null;
  guardian_phone: string | null;
  guardian_kinship: string | null;
  uni_id: string | null;
  source_records: number | null;
  review_note: string | null;
  participations: Participation[];
}

export interface DuplicateHit {
  id: number;
  mtr_id: string | null;
  name: string;
  matched_on: string[];
}

export interface RosterStats {
  totals: {
    members: number; unnumbered: number; claimed: number; unclaimed: number; needs_review: number;
    participations: number; active_members: number; graduating_soon: number;
  };
  by_university: { name: string; count: number }[];
  by_major: { name: string; count: number }[];
  by_location: { name: string; count: number }[];
  by_graduating_year: { name: string; count: number }[];
  by_confidence: { name: string; count: number }[];
  joins_by_month: { month: string; count: number }[];
  activity: { events: number; members: number }[];
  events: {
    id: number; name: string; code: string | null; kind: string | null; start_date: string | null;
    status: string; participants: number; result: string | null;
  }[];
}

export interface EventParticipant {
  id: number;
  member_id: number;
  mtr_id: string | null;
  name: string;
  role: string | null;
  team: string | null;
  mentor: string | null;
  rating: string | null;
  registered_at: string | null;
}

export type MaterialKind = 'slides' | 'book' | 'tasks' | 'answers' | 'tools';

export interface Course {
  id: number;
  title: string;
  description: string | null;
  cover_label: string | null;
  accent: string;
  cover_url: string | null;
  cover_path: string | null;
  is_published: boolean;
  sort_order: number;
  counts: Record<MaterialKind, number>;
  total: number;
  completed: number;
  percent: number;
  updated_at: string;
}

export interface CourseMaterial {
  id: number;
  kind: MaterialKind;
  title: string;
  path: string | null; // managers only
  is_link: boolean;
  media_type: string | null; // files only
  preview_url: string | null; // PDF rendition of an office file, shown inline
  unit: number | null;
  unit_label: string | null;
  sort_order: number;
  is_released: boolean;
  url: string | null; // null = held back from this viewer
  completed: boolean; // task sheets: the viewer's Task for it is submitted
  task: { id: number; status: TaskStatus } | null; // the viewer's own Task for this sheet
  handout: { assigned: number; submitted: number } | null; // managers, task sheets
}

export interface CourseDetail extends Course {
  materials: CourseMaterial[];
  can_manage: boolean;
  file_count: number | null;
}

export type ApplicationStatus = 'new' | 'contacted' | 'accepted' | 'waitlisted' | 'declined';

export interface Application {
  id: number;
  full_name: string;
  email: string;
  phone: string;
  school: string;
  year: string;
  subteam: string | null;
  motivation: string;
  event_id: number | null; // the event they applied to join; null = the team in general
  event_name: string | null;
  status: ApplicationStatus;
  notes: string | null;
  member_id: number | null;
  member_mtr_id: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  roster_matches: { id: number; mtr_id: string | null; name: string; matched_on: string[] }[];
}
