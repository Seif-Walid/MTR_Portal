export interface Role {
  slug: string;
  name: string;
  is_staff: boolean;
}

export interface UserBrief {
  id: number;
  email: string;
  full_name: string;
  department: string | null;
  roles: Role[];
}

export interface Me extends UserBrief {
  manager_id: number | null;
  is_admin: boolean;
  is_staff: boolean;
  is_high_staff: boolean;
  has_team: boolean;
  google_linked: boolean;
}

export interface AdminUser extends UserBrief {
  manager_id: number | null;
  is_active: boolean;
  google_linked: boolean;
  created_at: string;
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
  created_at: string;
  updated_at: string;
  attachments: Attachment[];
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

export type Condition = 'new' | 'good' | 'fair' | 'poor' | 'damaged';

export type AllocationPurpose =
  | 'training'
  | 'competition'
  | 'research'
  | 'borrowed'
  | 'other';

export type CompetitionStatus = 'active' | 'archived';

export interface CompetitionBrief {
  id: number;
  name: string;
  status: CompetitionStatus;
}

export interface CompetitionMember {
  id: number; // membership row id
  user: UserBrief;
}

export interface CompetitionTeam {
  id: number;
  name: string;
  lead: UserBrief | null;
  members: CompetitionMember[];
  can_manage_members: boolean;
}

export interface CompetitionCategory {
  id: number;
  name: string;
  teams: CompetitionTeam[];
}

export interface Competition extends CompetitionBrief {
  description: string;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  pms: UserBrief[];
  category_count: number;
  team_count: number;
  member_count: number;
  allocation_count: number;
  can_manage: boolean;
}

export interface CompetitionDetail extends Competition {
  categories: CompetitionCategory[];
}

export interface Allocation {
  id: number;
  quantity: number;
  purpose: AllocationPurpose;
  label: string;
  competition: CompetitionBrief | null;
  display_label: string; // competition name if linked, else the free-text label
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

export interface OrgTreeNode {
  id: number;
  full_name: string;
  email: string;
  department: string | null;
  roles: Role[];
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
  occupant: UserBrief | null;
  children: PositionNode[];
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

export interface AppNotification {
  id: number;
  type: string;
  message: string;
  task_id: number | null;
  request_id: number | null;
  is_read: boolean;
  created_at: string;
}
