import { theme } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';

import { C, hexA } from '../../theme/circuitTokens';
import type { ExploreSchema } from './types';

const NODE_H = 34;
const GAP = 10;
const HEAD = 30;
const MIN_COL = 170;
// Work items and the audit trail are admin bookkeeping — browsable from the
// side list, but they'd only add lines to every account on the map.
const MAP_GROUPS_EXCLUDED = new Set(['Work', 'System']);

/** Every kind of record the viewer can see, laid out by area, with a line for
 *  each way one kind points at another. Hover a box to light up its relations;
 *  click it to browse that kind. */
export default function SchemaMap({
  schema,
  onOpen,
}: {
  schema: ExploreSchema;
  onOpen: (table: string) => void;
}) {
  const { token } = theme.useToken();
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const groups = useMemo(() => schema.groups.filter((g) => !MAP_GROUPS_EXCLUDED.has(g)), [schema]);

  const layout = useMemo(() => {
    const colW = Math.max(MIN_COL, (width - 40) / groups.length);
    const nodeW = colW - 34;
    const pos: Record<string, { x: number; y: number; w: number; col: number }> = {};
    let maxRows = 0;
    groups.forEach((g, ci) => {
      const items = schema.entities.filter((e) => e.group === g);
      maxRows = Math.max(maxRows, items.length);
      items.forEach((e, ri) => {
        pos[e.table] = { x: ci * colW + 17, y: HEAD + ri * (NODE_H + GAP), w: nodeW, col: ci };
      });
    });
    return { colW, pos, height: HEAD + maxRows * (NODE_H + GAP) + 10, width: groups.length * colW + 40 };
  }, [schema, width, groups]);

  // one line per (source, target) pair — several FKs between the same pair fold into one
  const edges = useMemo(() => {
    const seen = new Map<string, { source: string; target: string; labels: string[] }>();
    for (const l of schema.links) {
      const k = `${l.source}>${l.target}`;
      const e = seen.get(k) ?? { source: l.source, target: l.target, labels: [] };
      e.labels.push(l.label);
      seen.set(k, e);
    }
    return Array.from(seen.values()).filter((e) => layout.pos[e.source] && layout.pos[e.target]);
  }, [schema, layout]);

  const neighbours = useMemo(() => {
    if (!hover) return null;
    const s = new Set([hover]);
    for (const e of edges) {
      if (e.source === hover) s.add(e.target);
      if (e.target === hover) s.add(e.source);
    }
    return s;
  }, [hover, edges]);

  const path = (a: string, b: string) => {
    const p = layout.pos[a];
    const q = layout.pos[b];
    const ay = p.y + NODE_H / 2;
    const by = q.y + NODE_H / 2;
    if (p.col === q.col) {
      // same column: loop out to the right
      const x = p.x + p.w;
      const bend = 26 + Math.abs(by - ay) * 0.15;
      return `M ${x} ${ay} C ${x + bend} ${ay}, ${x + bend} ${by}, ${x} ${by}`;
    }
    const leftToRight = p.col < q.col;
    const x1 = leftToRight ? p.x + p.w : p.x;
    const x2 = leftToRight ? q.x : q.x + q.w;
    const dx = Math.max(40, Math.abs(x2 - x1) / 2);
    return `M ${x1} ${ay} C ${x1 + (leftToRight ? dx : -dx)} ${ay}, ${x2 + (leftToRight ? -dx : dx)} ${by}, ${x2} ${by}`;
  };

  return (
    <div ref={wrap} style={{ width: '100%', overflowX: 'auto' }}>
      <svg width={layout.width} height={layout.height} role="img" aria-label="How the portal's records relate">
        {groups.map((g, ci) => (
          <text key={g} x={ci * layout.colW + 17} y={16} fontSize={10} letterSpacing="0.14em"
            fill={token.colorTextTertiary} style={{ fontFamily: C.mono, textTransform: 'uppercase' }}>
            {g.toUpperCase()}
          </text>
        ))}
        {edges.map((e) => {
          const on = neighbours ? neighbours.has(e.source) && neighbours.has(e.target) && (e.source === hover || e.target === hover) : false;
          return (
            <path
              key={`${e.source}>${e.target}`}
              d={path(e.source, e.target)}
              fill="none"
              stroke={on ? C.accent : hexA('#78aae6', neighbours ? 0.06 : 0.22)}
              strokeWidth={on ? 1.6 : 1}
            >
              <title>{`${e.source} → ${e.target}: ${e.labels.join(', ')}`}</title>
            </path>
          );
        })}
        {schema.entities.map((e) => {
          const p = layout.pos[e.table];
          if (!p) return null;
          const dim = neighbours && !neighbours.has(e.table);
          const active = hover === e.table;
          return (
            <g
              key={e.table}
              transform={`translate(${p.x},${p.y})`}
              style={{ cursor: 'pointer', opacity: dim ? 0.35 : 1, transition: 'opacity .15s' }}
              onMouseEnter={() => setHover(e.table)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onOpen(e.table)}
              tabIndex={0}
              onKeyDown={(ev) => ev.key === 'Enter' && onOpen(e.table)}
            >
              <rect
                width={p.w}
                height={NODE_H}
                rx={7}
                fill={active ? hexA(C.accent, 0.14) : 'rgba(15,20,29,.92)'}
                stroke={active ? C.accent : hexA('#78aae6', 0.22)}
              />
              <text x={10} y={21} fontSize={12.5} fill={token.colorText}>
                {e.label.length > 22 ? `${e.label.slice(0, 21)}…` : e.label}
              </text>
              <text x={p.w - 9} y={21} fontSize={11} textAnchor="end" fill={token.colorTextTertiary}
                style={{ fontFamily: C.mono, fontVariantNumeric: 'tabular-nums' }}>
                {e.count.toLocaleString('en-US')}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
