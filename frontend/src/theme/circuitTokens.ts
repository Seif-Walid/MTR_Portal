// CIRCUIT design tokens — import where you build custom styling in TS/TSX.
export const C = {
  bgVoid: '#06080c',
  bgPanel: 'rgba(15,20,29,.55)',
  bgInset: 'rgba(8,11,17,.6)',
  text: '#eaf2ff',
  textBody: 'rgba(224,236,252,.72)',
  textMuted: 'rgba(224,236,252,.55)',
  textFaint: 'rgba(224,236,252,.4)',
  accent: '#5cc6ff',
  accentGrad: 'linear-gradient(180deg,#7cd2ff,#4eb4f5)',
  hairline: 'rgba(120,170,230,.12)',
  hairlineRow: 'rgba(120,170,230,.07)',
  violet: '#8b9dff',
  teal: '#4fd6c4',
  steel: '#aab6c6',
  amber: '#ffb26b',
  danger: '#ff5a6e',
  mono: "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace",
  display: "'Space Grotesk Variable', 'Space Grotesk', sans-serif",
} as const;

// hex (#rrggbb) → rgba string. Used for translucent bar fills/borders.
export const hexA = (h: string, a: number): string => {
  const n = parseInt(h.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

export type CalSource = 'tasks' | 'events' | 'inventory' | 'requests' | 'teams';
export const SOURCE_COLOR: Record<CalSource, string> = {
  tasks: C.accent, events: C.violet, inventory: C.steel, requests: C.teal, teams: C.amber,
};
export const SOURCE_LABEL: Record<CalSource, string> = {
  tasks: 'Tasks', events: 'Events', inventory: 'Inventory', requests: 'Requests', teams: 'Teams',
};
