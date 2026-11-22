/* ==========================================================================
   MTR design tokens — "Workbench".
   Follows the portable design system (erp-onboarding/portable-design-system):
   brand layer → system scales → role tokens resolved per brightness.

   This file is the ONE source of truth. `installTokens()` writes every role
   token as a CSS custom property under :root[data-theme=light|dark], and
   `antdTheme(mode)` builds the Ant Design config from the same values, so
   CSS, inline styles and antd components can never drift apart.

   Identity: steel neutrals, MTR blue→cyan as the brand voice (primary
   fills, hero bands, selection, focus), and red as the single "needs
   attention" signal (live, unread, overdue, error).
   ========================================================================== */

export type Mode = 'light' | 'dark';

/* ── Brand (edit per brand) ─────────────────────────────────────────────── */
export const FONT_SANS =
  "'Archivo Variable', 'Archivo', 'Noto Sans Arabic Variable', system-ui, sans-serif";
// Display = the same family, stretched wide: echoes the logo's stamped lettering.
export const FONT_DISPLAY = FONT_SANS;
export const FONT_MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";

/* ── Role tokens per brightness ─────────────────────────────────────────── */
type Roles = Record<string, string>;

const LIGHT: Roles = {
  background: '#f1f2f4',
  surface: '#ffffff',
  'surface-alt': '#e9ebee',
  'surface-raised': '#ffffff',
  border: '#d9dce1',
  'border-light': '#e7e9ec',
  outline: '#858b95',

  'text-primary': '#121418',
  'text-secondary': '#454a53',
  'text-tertiary': '#5f656f',
  'text-disabled': '#a2a7af',

  primary: '#1f63e0',
  'on-primary': '#ffffff',
  'brand-fg': '#1d58c9',
  'primary-surface': '#e8effd',
  'brand-accent': '#12a3d6',
  'hero-1': '#0b2a72',
  'hero-2': '#1f5fd8',
  'hero-3': '#14a0d4',

  signal: '#d7263d',
  'signal-text': '#b3182d',
  'signal-surface': '#fdecee',

  success: '#1b8a52', 'success-text': '#13683d', 'success-surface': '#e6f4ec',
  warning: '#c27a00', 'warning-text': '#8a5300', 'warning-surface': '#fcf1dc',
  error: '#d7263d', 'error-text': '#b3182d', 'error-surface': '#fdecee',
  info: '#2f62d6', 'info-text': '#244fb4', 'info-surface': '#eaf0fc',

  // categorical hues (calendar sources, kinds, chart series) — >= 3:1 on surface
  'cat-blue': '#2f6fdf',
  'cat-violet': '#6b53cc',
  'cat-teal': '#0d8577',
  'cat-amber': '#b36f00',
  'cat-steel': '#68727f',

  scrim: 'rgb(18 20 24 / 0.38)',
  glass: 'rgb(255 255 255 / 0.82)',
  'shadow-color': 'rgb(18 20 24 / 0.06)',
  'shadow-strong': 'rgb(18 20 24 / 0.14)',
};

// Dark = the original Circuit night: blue-black void, blue-tinted panels and
// hairlines, ice-white text, MTR cyan as the brand voice.
const DARK: Roles = {
  background: '#06080c',
  surface: '#0c1118',
  'surface-alt': '#121925',
  'surface-raised': '#111823',
  border: '#1c2635',
  'border-light': '#141c28',
  outline: '#5b6b80',

  'text-primary': '#eaf2ff',
  'text-secondary': '#b4c3d6',
  'text-tertiary': '#8798ae',
  'text-disabled': '#4d5b6d',

  primary: '#2f86f6',
  'on-primary': '#ffffff',
  'brand-fg': '#5cc6ff',
  'primary-surface': '#0e2136',
  'brand-accent': '#5cc6ff',
  'hero-1': '#081d4f',
  'hero-2': '#1a4fc0',
  'hero-3': '#1696c9',

  signal: '#ff5a6e',
  'signal-text': '#ff8d9b',
  'signal-surface': '#361219',

  success: '#3fd49a', 'success-text': '#7fe3bb', 'success-surface': '#0b2a20',
  warning: '#ffb26b', 'warning-text': '#ffc996', 'warning-surface': '#33220f',
  error: '#ff5a6e', 'error-text': '#ff8d9b', 'error-surface': '#361219',
  info: '#5cc6ff', 'info-text': '#94dbff', 'info-surface': '#0d2235',

  'cat-blue': '#5cc6ff',
  'cat-violet': '#8b9dff',
  'cat-teal': '#4fd6c4',
  'cat-amber': '#ffb26b',
  'cat-steel': '#aab6c6',

  scrim: 'rgb(2 4 8 / 0.62)',
  glass: 'rgb(12 17 24 / 0.8)',
  'shadow-color': 'rgb(0 0 0 / 0.35)',
  'shadow-strong': 'rgb(0 0 0 / 0.6)',
};

export const ROLES: Record<Mode, Roles> = { light: LIGHT, dark: DARK };

/* ── System scales (shared by every brand) ──────────────────────────────── */
const SYSTEM = `
  --font-sans: ${FONT_SANS};
  --font-display: ${FONT_DISPLAY};
  --font-mono: ${FONT_MONO};
  --wdth-display: 118;

  --space-xxs: 2px; --space-xs: 4px; --space-sm: 8px; --space-md: 12px;
  --space-lg: 16px; --space-xl: 20px; --space-xxl: 24px; --space-xxxl: 32px;
  --space-huge: 40px; --space-massive: 48px; --space-jumbo: 64px;

  --radius-sm: 4px; --radius-md: 8px; --radius-lg: 12px;
  --radius-xl: 16px; --radius-xxl: 20px; --radius-full: 999px;

  --duration-instant: 100ms; --duration-fast: 150ms; --duration-normal: 250ms;
  --duration-page: 300ms; --duration-slow: 400ms;
  --ease-out: cubic-bezier(0.33, 1, 0.68, 1);
  --ease-in: cubic-bezier(0.32, 0, 0.67, 0);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --press-scale: 0.97;

  --z-content: 0; --z-sticky: 10; --z-nav: 20; --z-dropdown: 30;
  --z-panel: 40; --z-dialog: 50; --z-toast: 60; --z-island: 70; --z-tooltip: 90;
`;

const DERIVED = `
  --focus-ring: var(--brand-fg);
  --hover-tint: color-mix(in srgb, var(--brand-fg) 5%, transparent);
  --press-tint: color-mix(in srgb, var(--brand-fg) 9%, transparent);
  --hover-border: color-mix(in srgb, var(--brand-fg) 22%, var(--border));
  --selected-tint: var(--primary-surface);
  --gradient-primary: linear-gradient(135deg, var(--primary), var(--brand-accent));
  --gradient-hero: linear-gradient(105deg, var(--hero-1), var(--hero-2) 55%, var(--hero-3));
  --glow-brand: 0 14px 40px -12px color-mix(in srgb, var(--primary) 55%, transparent);
  --money-negative: var(--error-text);
  --shadow-sm: 0 1px 2px var(--shadow-color);
  --shadow-md: 0 2px 8px var(--shadow-color), 0 1px 2px var(--shadow-color);
  --shadow-lg: 0 8px 24px var(--shadow-color), 0 2px 6px var(--shadow-color);
  --shadow-xl: 0 16px 40px var(--shadow-strong);
  --shadow-floating: 0 20px 48px var(--shadow-strong);
`;

const block = (r: Roles) => Object.entries(r).map(([k, v]) => `  --${k}: ${v};`).join('\n');

export function tokensCss(): string {
  return `:root{${SYSTEM}}
:root[data-theme="light"]{color-scheme:light;\n${block(LIGHT)}\n${DERIVED}}
:root[data-theme="dark"]{color-scheme:dark;\n${block(DARK)}\n${DERIVED}}`;
}

let installed = false;
export function installTokens() {
  if (installed) return;
  installed = true;
  const el = document.createElement('style');
  el.id = 'mtr-tokens';
  el.textContent = tokensCss();
  document.head.prepend(el);
}

/** `var(--role)` shorthand for inline styles. */
export const v = (role: string) => `var(--${role})`;
/** Role colour at an alpha, theme-aware. */
export const mix = (color: string, a: number) =>
  `color-mix(in srgb, ${color} ${Math.round(a * 1000) / 10}%, transparent)`;
