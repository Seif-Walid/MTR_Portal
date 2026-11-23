/* Where to land after signing in. Only the OAuth consent page uses it: an
   outside AI agent sends the person there, and if they are signed out the
   login (password or Google) must bring them back to approve. */

const KEY = 'mtr_return_to';
const ALLOWED = '/oauth/consent';

export function rememberReturn(path: string): void {
  if (!path.startsWith(ALLOWED)) return;
  try { sessionStorage.setItem(KEY, path); } catch { /* storage blocked: they'll land on /tasks */ }
}

export function pendingReturn(): string | null {
  try {
    const path = sessionStorage.getItem(KEY);
    return path && path.startsWith(ALLOWED) ? path : null;
  } catch {
    return null;
  }
}

export function clearReturn(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}

export const afterLogin = (): string => pendingReturn() ?? '/tasks';
