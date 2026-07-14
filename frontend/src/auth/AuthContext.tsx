import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

import { api, ApiError } from '../api/client';
import type { Me } from '../api/types';

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, fullName: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
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

  const register = async (email: string, fullName: string, password: string) => {
    setMe(await api.post<Me>('/api/auth/register', { email, full_name: fullName, password }));
  };

  const logout = async () => {
    await api.post('/api/auth/logout');
    setMe(null);
  };

  return (
    <AuthContext.Provider value={{ me, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
