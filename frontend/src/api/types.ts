export interface UserBrief {
  id: number;
  email: string;
  full_name: string;
  department: string | null;
}

export interface MemberProfile {
  mtr_id: string | null;
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
  level: LevelBrief | null;
  privileges: string[];
  has_team: boolean;
  google_linked: boolean;
  created_at: string;
  seats: string[];
  profile: MemberProfile | null;
}

export interface AdminUser extends UserBrief {
  manager_id: number | null;
  is_active: boolean;
  google_linked: boolean;
  created_at: string;
  access_level_id: number | null; // the personal override
  effective_level: string | null; // computed from seats + override
  effective_rank: number | null;
  seats: string[]; // org positions occupied — the org's reflection
  profile: MemberProfile | null; // imported roster record (directory fields), if any
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
  filename: string;
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
}

export interface ArchivedEvent {
  id: number;
  name: string;
  kind_name: string | null;
  kind_label: string | null;
  start_date: string | null;
  end_date: string | null;
  can_manage?: boolean;
}

export interface ArchivedTask {
  outcome: 'accomplished' | 'incomplete';
  team_name: string;
  task: Task;
}

export interface ArchivedEventDetail {
  event: ArchivedEvent;
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
  award?: string | null; // per-team placement shown in the public Hall of Fame
  roles: EntityRole[];
  members: EventMember[];
  can_manage_members: boolean;
}

export interface EventCategory {
  id: number;
  name: string;
  teams: EventTeam[];
}

export interface Event extends EventBrief {
  description: string;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  awards?: string[] | null; // competition-wide placements shown in the public Hall of Fame
  kind: EventKind | null;
  roles: EntityRole[];
  category_count: number;
  team_count: number;
  member_count: number;
  allocation_count: number;
  can_manage: boolean;
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

export interface SheetsStatus {
  configured: boolean; // has a default push target (drives Sync)
  credentials: boolean; // has a service-account key (drives Import)
  can_sync: boolean;
}

export interface ImportPreview {
  spreadsheet_id: string;
  worksheet: string | null;
  headers: string[];
  rows: Record<string, string>[];
  total: number;
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

export interface SheetExportStatus {
  tab: string;
  row_count: number;
  is_dirty: boolean;
  last_synced_at: string | null;
  last_error: string;
}

export interface RebuildReport {
  ok: boolean;
  tab_counts: Record<string, number>;
  errors: string[];
  would_delete: Record<string, number>;
  committed: boolean;
  snapshot_path: string | null;
  batch_id: number | null;
}

export interface RebuildBatch {
  id: number;
  status: 'dry_run' | 'succeeded' | 'failed';
  tab_counts: string; // JSON
  errors: string; // JSON
  snapshot_path: string;
  started_at: string;
  finished_at: string | null;
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
}
