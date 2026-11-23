import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

import { api, ApiError } from '../api/client';
import type { Me } from '../api/types';

/** Does the signed-in user's effective level include this privilege? */
export function can(me: Me | null, key: string): boolean {
  return !!me && me.privileges.includes(key);
}

export interface EntryRequest {
  email: string;
  full_name: string;
  password: string;
  phone: string;
  school?: string;
  year?: string;
  why?: string;
}

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** "Request entry": an admin-added member is activated and signed in
   * ('signed-in'); anyone else files a request for review ('pending'). */
  requestEntry: (fields: EntryRequest) => Promise<'signed-in' | 'pending'>;
  logout: () => Promise<void>;
  applyMe: (me: Me) => void;
}

const AuthContext = createContext<AuthState>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Me>('/api/auth/me')
      .then(setMe)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    setMe(await api.post<Me>('/api/auth/login', { email, password }));
  };

  const requestEntry = async (fields: EntryRequest) => {
    const r = await api.post<Me | { status: 'pending' }>('/api/auth/request-entry', fields);
    if ('status' in r && r.status === 'pending') return 'pending';
    setMe(r as Me);
    return 'signed-in';
  };

  const logout = async () => {
    await api.post('/api/auth/logout');
    setMe(null);
  };

  return (
    <AuthContext.Provider value={{ me, loading, login, requestEntry, logout, applyMe: setMe }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
