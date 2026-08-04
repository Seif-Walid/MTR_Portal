import { createContext, useContext, useEffect, type ReactNode } from 'react';

type Mode = 'dark';

// The CIRCUIT world is authored dark-only. The provider stays so existing
// consumers keep working; body background + palette come from circuit.css and
// the AntD dark theme.
const ThemeModeContext = createContext<{ mode: Mode; toggle: () => void }>({
  mode: 'dark',
  toggle: () => {},
});

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    localStorage.setItem('mtr-theme', 'dark');
    document.body.style.colorScheme = 'dark';
  }, []);

  return (
    <ThemeModeContext.Provider value={{ mode: 'dark', toggle: () => {} }}>
      {children}
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode() {
  return useContext(ThemeModeContext);
}
