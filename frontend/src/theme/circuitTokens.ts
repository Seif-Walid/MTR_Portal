// Role-token shorthands for inline styles. Every value is a CSS custom property
// (theme/tokens.ts), so the same code renders correctly in light and dark.
export const C = {
  bgVoid: 'var(--background)',
  bgPanel: 'var(--surface)',
  bgInset: 'var(--surface-alt)',
  text: 'var(--text-primary)',
  textBody: 'var(--text-secondary)',
  textMuted: 'var(--text-tertiary)',
  // faint is the lowest tier allowed for readable text: ≈4.8:1 on void, panel and elevated surfaces
  textFaint: 'var(--text-tertiary)',
  // below this only for disabled controls and decorative icons (≥3:1 for icons)
  iconFaint: 'var(--text-tertiary)',
  textDisabled: 'var(--text-disabled)',
  accent: 'var(--brand-fg)',
  accentGrad: 'var(--primary)',
  hairline: 'var(--border)',
  hairlineRow: 'var(--border-light)',
  violet: 'var(--cat-violet)',
  teal: 'var(--cat-teal)',
  steel: 'var(--cat-steel)',
  amber: 'var(--cat-amber)',
  danger: 'var(--error)',
  mono: 'var(--font-mono)',
  display: 'var(--font-display)',
} as const;

// colour at an alpha. Hex → rgba; anything else (var(), named) → color-mix,
// so theme variables tint correctly in both brightnesses.
export const hexA = (h: string, a: number): string => {
  if (!/^#[0-9a-f]{6}$/i.test(h)) return `color-mix(in srgb, ${h} ${Math.round(a * 1000) / 10}%, transparent)`;
  const n = parseInt(h.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

export type CalSource = 'tasks' | 'events' | 'inventory' | 'requests' | 'teams';
export const SOURCE_COLOR: Record<CalSource, string> = {
  tasks: 'var(--cat-blue)', events: C.violet, inventory: C.steel, requests: C.teal, teams: C.amber,
};
export const SOURCE_LABEL: Record<CalSource, string> = {
  tasks: 'Tasks', events: 'Events', inventory: 'Inventory', requests: 'Requests', teams: 'Teams',
};
