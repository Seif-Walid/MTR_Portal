// How a person reads in any picker. Members and accounts are one record, so
// every dropdown of people uses this: MTR ID first when they have one, then
// the name, then the email (when the roster has one) to tell namesakes apart.
import type { UserBrief } from '../api/types';

export function personLabel(u: Pick<UserBrief, 'full_name' | 'email' | 'mtr_id'>): string {
  const name = u.mtr_id ? `${u.mtr_id} — ${u.full_name}` : u.full_name;
  return u.email ? `${name} (${u.email})` : name;
}

export function personOptions(users: Pick<UserBrief, 'id' | 'full_name' | 'email' | 'mtr_id'>[]) {
  return users.map((u) => ({ value: u.id, label: personLabel(u) }));
}
