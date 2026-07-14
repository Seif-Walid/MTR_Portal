import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

import { brand } from './brand';

type Mode = 'light' | 'dark';

const ThemeModeContext = createContext<{ mode: Mode; toggle: () => void }>({
  mode: 'light',
  toggle: () => {},
});

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(() => {
    const saved = localStorage.getItem('mtr-theme');
    if (saved === 'light' || saved === 'dark') return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  useEffect(() => {
    localStorage.setItem('mtr-theme', mode);
    document.body.style.background = mode === 'dark' ? brand.black : brand.cream;
    document.body.style.colorScheme = mode;
  }, [mode]);

  return (
    <ThemeModeContext.Provider
      value={{ mode, toggle: () => setMode((m) => (m === 'dark' ? 'light' : 'dark')) }}
    >
      {children}
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode() {
  return useContext(ThemeModeContext);
}
