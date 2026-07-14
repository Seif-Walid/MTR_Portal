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
  has_team: boolean;
}

export interface AdminUser extends UserBrief {
  manager_id: number | null;
  is_active: boolean;
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

export interface AppNotification {
  id: number;
  type: string;
  message: string;
  task_id: number | null;
  request_id: number | null;
  is_read: boolean;
  created_at: string;
}
