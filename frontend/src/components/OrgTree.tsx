import { Fragment } from 'react';
import { Typography } from 'antd';
import { C } from '../theme/circuitTokens';

/* OrgTree — flattens the position tree into indented rows (CIRCUIT style).
   Drop into OrganizationPage in place of the AntD <Tree> render, or keep
   AntD Tree and only borrow the row markup. Actions (add/edit/delete,
   drag re-parent) stay wired to your existing handlers — pass them in. */

export interface OrgNode {
  id: number;
  title: string;
  occupants: string[];        // full names; empty = vacant
  isTechnical?: boolean;
  isAutomatic?: boolean;      // role template seat
  levelName?: string | null;  // access level, if any
  children: OrgNode[];
}

interface Row { node: OrgNode; depth: number; }

function flatten(nodes: OrgNode[], depth = 0, acc: Row[] = []): Row[] {
  for (const n of nodes) {
    acc.push({ node: n, depth });
    if (n.children?.length) flatten(n.children, depth + 1, acc);
  }
  return acc;
}

const miniTag = (text: string, color: string) => (
  <span style={{
    fontFamily: C.mono, fontSize: 9, letterSpacing: '.1em', textTransform: 'uppercase',
    color, border: `1px solid ${color}55`, background: `${color}14`, padding: '2px 8px', borderRadius: 5,
  }}>{text}</span>
);

export default function OrgTree({ roots, renderActions }: {
  roots: OrgNode[];
  renderActions?: (node: OrgNode) => React.ReactNode;
}) {
  const rows = flatten(roots);
  return (
    <div className="circuit-panel">
      {rows.map(({ node, depth }) => (
        <div key={node.id} style={{
          display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap',
          padding: '12px 18px', paddingLeft: 18 + depth * 26,
          borderBottom: `1px solid ${C.hairlineRow}`,
        }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: C.accent, boxShadow: `0 0 8px ${C.accent}`, flexShrink: 0 }} />
          <span style={{ fontFamily: C.display, fontWeight: 600, fontSize: 14, color: C.text }}>{node.title}</span>
          {node.occupants.length === 0 ? (
            <span style={{ fontFamily: C.mono, fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'rgba(224,236,252,.42)', border: '1px dashed rgba(120,170,230,.25)', padding: '2px 8px', borderRadius: 5 }}>vacant</span>
          ) : (
            <Typography.Text style={{ fontSize: 12.5, color: C.textMuted }}>{node.occupants.join(', ')}</Typography.Text>
          )}
          {node.isTechnical && miniTag('technical', C.accent)}
          {node.isAutomatic && miniTag('automatic', C.violet)}
          {node.levelName && miniTag(node.levelName, C.amber)}
          {renderActions && <Fragment>{renderActions(node)}</Fragment>}
        </div>
      ))}
    </div>
  );
}
