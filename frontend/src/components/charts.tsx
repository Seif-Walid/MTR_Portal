import { Empty, Tooltip, theme } from 'antd';

import { hexA } from '../theme/circuitTokens';

// Small, dependency-free chart primitives for the dashboards. Every chart here
// is single-series, so one mark hue carries it (validated against the dark
// surface: OKLCH L inside the 0.48–0.67 band, ≥3:1 contrast); a second figure
// for the same item is drawn as a track of the same hue behind the bar, never
// as a second color. Labels and values always wear text tokens.
export const MARK = '#2b9ad9';
const TRACK = hexA(MARK, 0.18);

export const egp = (n: number) =>
  `${n < 0 ? '−' : ''}${Math.abs(n).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;

export const compact = (n: number) => {
  const a = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  if (a >= 1_000_000) return `${sign}${(a / 1_000_000).toFixed(a >= 10_000_000 ? 0 : 1)}M`;
  if (a >= 10_000) return `${sign}${(a / 1000).toFixed(0)}K`;
  if (a >= 1000) return `${sign}${(a / 1000).toFixed(1)}K`;
  return `${sign}${Math.round(a)}`;
};

export function StatTile({
  label,
  value,
  unit,
  sub,
  tone,
}: {
  label: string;
  value: string;
  /** small unit after the value, e.g. "EGP" */
  unit?: string;
  sub?: React.ReactNode;
  tone?: 'danger' | 'good';
}) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        background: token.colorBgContainer,
        padding: '16px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minWidth: 0,
      }}
    >
      <div className="u-label" style={{ color: token.colorTextTertiary }}>{label}</div>
      <div
        style={{
          fontSize: 26,
          fontWeight: 600,
          lineHeight: 1.1,
          color: tone === 'danger' ? token.colorError : token.colorText,
          letterSpacing: '-0.01em',
          whiteSpace: 'nowrap',
        }}
      >
        {value}
        {unit && <span style={{ fontSize: 12, fontWeight: 500, marginLeft: 5, color: token.colorTextTertiary }}>{unit}</span>}
      </div>
      {sub && <div style={{ fontSize: 12, color: token.colorTextTertiary }}>{sub}</div>}
    </div>
  );
}

/** A row of stat tiles separated by hairlines (the panel colour shows through the gap). */
export function StatRow({ children, min = 180 }: { children: React.ReactNode; min?: number }) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`,
        gap: 1,
        background: token.colorBorderSecondary,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadiusLG,
        overflow: 'hidden',
      }}
    >
      {children}
    </div>
  );
}

export interface BarItem {
  name: string;
  value: number;
  /** a second figure for the same item, drawn as a track behind the bar */
  track?: number;
}

/** Horizontal bars, one per item, labelled at the left with the value at the tip. */
export function BarList({
  items,
  format = egp,
  valueLabel,
  trackLabel,
  empty = 'Nothing yet',
}: {
  items: BarItem[];
  format?: (n: number) => string;
  valueLabel?: string;
  trackLabel?: string;
  empty?: string;
}) {
  const { token } = theme.useToken();
  const max = Math.max(0, ...items.map((i) => Math.max(i.value, i.track ?? 0)));
  if (!items.length || max === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={empty} />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {trackLabel && (
        <div style={{ display: 'flex', gap: 14, fontSize: 12, color: token.colorTextTertiary, marginBottom: 2 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: MARK }} />
            {valueLabel}
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: TRACK }} />
            {trackLabel}
          </span>
        </div>
      )}
      {items.map((it) => (
        <Tooltip
          key={it.name}
          placement="topLeft"
          title={
            <div>
              <div style={{ fontWeight: 600 }}>{it.name}</div>
              <div>{valueLabel ?? 'Value'}: {format(it.value)}</div>
              {it.track != null && <div>{trackLabel}: {format(it.track)}</div>}
            </div>
          }
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(90px, 34%) 1fr auto',
              alignItems: 'center',
              gap: 10,
              padding: '3px 0',
              cursor: 'default',
            }}
          >
            <span
              style={{
                fontSize: 13,
                color: token.colorTextSecondary,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {it.name}
            </span>
            <div style={{ position: 'relative', height: 14 }}>
              {it.track != null && it.track > 0 && (
                <div
                  style={{
                    position: 'absolute', inset: '0 auto 0 0',
                    width: `${(it.track / max) * 100}%`,
                    background: TRACK,
                    borderRadius: '0 4px 4px 0',
                  }}
                />
              )}
              <div
                style={{
                  position: 'absolute', inset: '0 auto 0 0',
                  width: `${Math.max((it.value / max) * 100, it.value > 0 ? 0.6 : 0)}%`,
                  background: MARK,
                  borderRadius: '0 4px 4px 0',
                }}
              />
            </div>
            <span
              className="u-mono"
              style={{ fontSize: 12, color: token.colorText, fontVariantNumeric: 'tabular-nums', minWidth: 52, textAlign: 'right' }}
            >
              {format(it.value)}
              {it.track != null && <span style={{ color: token.colorTextTertiary }}> / {compact(it.track)}</span>}
            </span>
          </div>
        </Tooltip>
      ))}
    </div>
  );
}

export interface ColumnItem {
  label: string;
  value: number;
  /** tooltip title; defaults to label */
  title?: string;
}

/** Vertical columns along a time or ordinal axis, with the peak labelled. */
export function Columns({
  items,
  format = egp,
  height = 150,
  every,
  empty = 'Nothing yet',
}: {
  items: ColumnItem[];
  format?: (n: number) => string;
  height?: number;
  /** label every Nth tick (auto when omitted) */
  every?: number;
  empty?: string;
}) {
  const { token } = theme.useToken();
  const max = Math.max(0, ...items.map((i) => i.value));
  if (!items.length || max === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={empty} />;
  const step = every ?? Math.max(1, Math.ceil(items.length / 12));
  const peak = items.reduce((best, it, i) => (it.value > items[best].value ? i : best), 0);
  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 2,
          height,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          paddingTop: 18,
        }}
      >
        {items.map((it, i) => (
          <Tooltip key={`${it.label}-${i}`} title={`${it.title ?? it.label}: ${format(it.value)}`}>
            <div
              style={{
                flex: 1,
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'flex-end',
                alignItems: 'center',
                position: 'relative',
                cursor: 'default',
              }}
            >
              {i === peak && (
                <span
                  className="u-mono"
                  style={{
                    position: 'absolute',
                    top: `calc(${100 - (it.value / max) * 100}% - 18px)`,
                    fontSize: 11,
                    color: token.colorTextSecondary,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {format(it.value)}
                </span>
              )}
              <div
                style={{
                  width: '100%',
                  maxWidth: 24,
                  height: `${(it.value / max) * 100}%`,
                  minHeight: it.value > 0 ? 2 : 0,
                  background: MARK,
                  borderRadius: '4px 4px 0 0',
                }}
              />
            </div>
          </Tooltip>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 2, marginTop: 6 }}>
        {items.map((it, i) => (
          <span
            key={`${it.label}-${i}`}
            className="u-mono"
            style={{
              flex: 1,
              fontSize: 10,
              textAlign: 'center',
              color: token.colorTextTertiary,
              whiteSpace: 'nowrap',
              overflow: 'visible',
              visibility: i % step === 0 ? 'visible' : 'hidden',
            }}
          >
            {it.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** A titled panel for one chart or table on a dashboard. */
export function Panel({
  title,
  extra,
  children,
  style,
}: {
  title: React.ReactNode;
  extra?: React.ReactNode;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  const { token } = theme.useToken();
  return (
    <section
      style={{
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadiusLG,
        background: token.colorBgContainer,
        padding: '14px 16px 16px',
        minWidth: 0,
        ...style,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: token.colorText }}>{title}</h3>
        {extra && <div style={{ fontSize: 12, color: token.colorTextTertiary }}>{extra}</div>}
      </div>
      {children}
    </section>
  );
}

/** Responsive grid of dashboard panels. */
export function PanelGrid({ children, min = 340 }: { children: React.ReactNode; min?: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(min(${min}px, 100%), 1fr))`, gap: 14 }}>
      {children}
    </div>
  );
}
