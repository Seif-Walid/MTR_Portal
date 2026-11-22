import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { flushSync } from 'react-dom';

import type { Mode } from './tokens';

/* Light and dark are full themes (DESIGN_RULES §14). The user's choice is
   persisted; until they choose, the OS setting wins and is followed live. */

type Pref = Mode | 'system';
const KEY = 'mtr-theme';

const readPref = (): Pref => {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
  } catch {
    return 'system';
  }
};
const systemMode = (): Mode =>
  window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';

const resolve = (p: Pref): Mode => (p === 'system' ? systemMode() : p);

// paint the attribute before React renders so the first frame is already themed
document.documentElement.dataset.theme = resolve(readPref());

type Ctx = {
  mode: Mode;
  pref: Pref;
  setPref: (p: Pref, origin?: { x: number; y: number }) => void;
  toggle: (origin?: { x: number; y: number }) => void;
};
const ThemeModeContext = createContext<Ctx>({
  mode: 'light',
  pref: 'system',
  setPref: () => {},
  toggle: () => {},
});

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<Pref>(readPref);
  const [mode, setMode] = useState<Mode>(() => resolve(readPref()));

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
  }, [mode]);

  useEffect(() => {
    if (pref !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const on = () => setMode(systemMode());
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, [pref]);

  const setPref = useCallback((p: Pref, origin?: { x: number; y: number }) => {
    const next = resolve(p);
    try { localStorage.setItem(KEY, p); } catch { /* storage off */ }
    const apply = () => {
      flushSync(() => { setPrefState(p); setMode(next); });
      document.documentElement.dataset.theme = next;
    };
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // The switch answers the click: the new theme grows out of the button as a
    // circle (View Transitions API). Falls back to an instant swap.
    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
    if (!doc.startViewTransition || reduce || next === mode) { apply(); return; }
    const x = origin?.x ?? window.innerWidth - 40;
    const y = origin?.y ?? 30;
    const r = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    doc.startViewTransition(apply).ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
        { duration: 420, easing: 'cubic-bezier(0.33, 1, 0.68, 1)', pseudoElement: '::view-transition-new(root)' },
      );
    }).catch(() => {});
  }, [mode]);

  const toggle = useCallback(
    (origin?: { x: number; y: number }) => setPref(mode === 'dark' ? 'light' : 'dark', origin),
    [mode, setPref],
  );

  return (
    <ThemeModeContext.Provider value={{ mode, pref, setPref, toggle }}>
      {children}
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode() {
  return useContext(ThemeModeContext);
}
