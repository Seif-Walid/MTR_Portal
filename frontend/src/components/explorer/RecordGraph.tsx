import { theme } from 'antd';
import { useEffect, useRef, useState } from 'react';

import { C, hexA } from '../../theme/circuitTokens';
import type { ExploreRecord, RecordRef, RelatedGroup } from './types';

const ROW = 42;
const NODE_H = 32;
const MAX_SIDE = 12;

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** One record at the centre; on the left what it points at, on the right what
 *  points at it (with how many). Click a node to go there. */
export default function RecordGraph({
  record,
  onOpenRecord,
  onOpenGroup,
}: {
  record: ExploreRecord;
  onOpenRecord: (ref: RecordRef) => void;
  onOpenGroup: (g: RelatedGroup) => void;
}) {
  const { token } = theme.useToken();
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const left = record.outgoing.slice(0, MAX_SIDE);
  const right = record.incoming.slice(0, MAX_SIDE);
  if (!left.length && !right.length) return null;

  const w = Math.max(width, 560);
  const nodeW = Math.min(230, (w - 220) / 2 - 30);
  const rows = Math.max(left.length, right.length, 1);
  const h = rows * ROW + 24;
  const cx = w / 2;
  const cy = h / 2;
  const centreW = Math.min(220, w * 0.26);
  const chars = Math.floor(nodeW / 7.2);

  const yFor = (i: number, n: number) => cy - ((n - 1) * ROW) / 2 + i * ROW;

  const edge = (x1: number, y1: number, x2: number, y2: number) => {
    const dx = (x2 - x1) / 2;
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  };

  const node = (key: string, x: number, y: number, title: string, sub: string, onClick: () => void, align: 'left' | 'right') => {
    const on = hover === key;
    return (
      <g
        key={key}
        transform={`translate(${x},${y - NODE_H / 2})`}
        style={{ cursor: 'pointer' }}
        onMouseEnter={() => setHover(key)}
        onMouseLeave={() => setHover(null)}
        onClick={onClick}
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && onClick()}
      >
        <rect width={nodeW} height={NODE_H} rx={7}
          fill={on ? hexA(C.accent, 0.14) : 'rgba(15,20,29,.92)'}
          stroke={on ? C.accent : hexA('#78aae6', 0.24)} />
        <text x={align === 'left' ? 10 : nodeW - 10} y={14} fontSize={10} textAnchor={align === 'left' ? 'start' : 'end'}
          fill={token.colorTextTertiary} style={{ fontFamily: C.mono }}>
          {clip(sub, chars + 4)}
        </text>
        <text x={align === 'left' ? 10 : nodeW - 10} y={26} fontSize={12} textAnchor={align === 'left' ? 'start' : 'end'}
          fill={token.colorText}>
          {clip(title, chars)}
        </text>
      </g>
    );
  };

  return (
    <div ref={wrap} style={{ width: '100%', overflowX: 'auto' }}>
      <svg width={w} height={h} role="img" aria-label={`What ${record.title} connects to`}>
        <text x={16} y={12} fontSize={10} fill={token.colorTextTertiary} style={{ fontFamily: C.mono }} letterSpacing="0.14em">
          POINTS TO
        </text>
        <text x={w - 16} y={12} fontSize={10} textAnchor="end" fill={token.colorTextTertiary} style={{ fontFamily: C.mono }} letterSpacing="0.14em">
          LINKED FROM
        </text>
        {left.map((r, i) => {
          const y = yFor(i, left.length);
          const key = `o-${r.table}-${r.id}-${i}`;
          return (
            <path key={`e${key}`} d={edge(16 + nodeW, y, cx - centreW / 2, cy)} fill="none"
              stroke={hover === key ? C.accent : hexA('#78aae6', 0.3)} strokeWidth={hover === key ? 1.6 : 1} />
          );
        })}
        {right.map((g, i) => {
          const y = yFor(i, right.length);
          const key = `i-${g.key}`;
          return (
            <path key={`e${key}`} d={edge(cx + centreW / 2, cy, w - 16 - nodeW, y)} fill="none"
              stroke={hover === key ? C.accent : hexA('#78aae6', 0.3)} strokeWidth={hover === key ? 1.6 : 1} />
          );
        })}
        <g transform={`translate(${cx - centreW / 2},${cy - 24})`}>
          <rect width={centreW} height={48} rx={9} fill={hexA(C.accent, 0.16)} stroke={C.accent} />
          <text x={centreW / 2} y={19} fontSize={10} textAnchor="middle" fill={C.accent} style={{ fontFamily: C.mono }} letterSpacing="0.12em">
            {record.entity.toUpperCase()}
          </text>
          <text x={centreW / 2} y={36} fontSize={13} fontWeight={600} textAnchor="middle" fill={token.colorText}>
            {clip(record.title, Math.floor(centreW / 7.5))}
          </text>
        </g>
        {left.map((r, i) =>
          node(`o-${r.table}-${r.id}-${i}`, 16, yFor(i, left.length), r.title,
            `${r.relation ?? r.entity}${r.via ? ` · via ${r.via.toLowerCase()}` : ''}`, () => onOpenRecord(r), 'left'),
        )}
        {right.map((g, i) =>
          node(`i-${g.key}`, w - 16 - nodeW, yFor(i, right.length), `${g.total.toLocaleString('en-US')} ${g.label.toLowerCase()}`,
            g.via ? `via ${g.via.toLowerCase()}` : `as ${g.relation.toLowerCase()}`, () => onOpenGroup(g), 'right'),
        )}
      </svg>
      {(record.outgoing.length > MAX_SIDE || record.incoming.length > MAX_SIDE) && (
        <div style={{ fontSize: 12, color: token.colorTextTertiary }}>More connections are listed below.</div>
      )}
    </div>
  );
}
