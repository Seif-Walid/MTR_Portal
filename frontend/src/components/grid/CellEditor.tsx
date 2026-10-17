import { CalendarOutlined } from '@ant-design/icons';
import { theme } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { ColumnMeta, Option, displayText, isNumeric, isPick } from './sheet';

// The floating in-cell editor, shared by the grid and the single-record form.
// It never parses anything itself: it hands back either raw typed text (parsed
// by the caller, like a pasted value) or a picked option's value.

export type Move = 'down' | 'up' | 'right' | 'left' | null;
export type Commit = { kind: 'text'; text: string } | { kind: 'value'; value: string };

export interface EditorRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Props {
  col: ColumnMeta;
  opts: Option[];
  value: string;
  /** a key typed to start editing replaces the cell's content */
  seed: string | null;
  rect: EditorRect;
  /** scrolled out of view: keep the editor (and what's typed) but don't show it */
  hidden?: boolean;
  onCommit: (c: Commit, move: Move) => void;
  onCancel: () => void;
}

export default function CellEditor(props: Props) {
  const { token } = theme.useToken();
  const { rect } = props;
  const box: React.CSSProperties = {
    position: 'fixed',
    left: rect.left,
    top: rect.top,
    minWidth: Math.max(rect.width, isPick(props.col) ? 260 : rect.width),
    minHeight: rect.height,
    zIndex: 1100,
    background: token.colorBgElevated,
    boxShadow: `0 0 0 2px ${token.colorPrimary}, ${token.boxShadowSecondary}`,
    borderRadius: 2,
    fontSize: 13,
    color: token.colorText,
    visibility: props.hidden ? 'hidden' : undefined,
  };
  return createPortal(
    <div style={box} onMouseDown={(e) => e.stopPropagation()}>
      {isPick(props.col) ? <PickEditor {...props} /> : <TextEditor {...props} />}
    </div>,
    document.body,
  );
}

const inputStyle = (h: number, align: 'left' | 'right'): React.CSSProperties => ({
  all: 'unset',
  boxSizing: 'border-box',
  display: 'block',
  width: '100%',
  minHeight: h,
  padding: '5px 8px',
  lineHeight: '20px',
  textAlign: align,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  fontVariantNumeric: 'tabular-nums',
  resize: 'none',
  overflow: 'hidden',
});

function moveFor(e: React.KeyboardEvent): Move | undefined {
  if (e.key === 'Enter' && !e.altKey && !e.ctrlKey && !e.metaKey) return e.shiftKey ? 'up' : 'down';
  if (e.key === 'Tab') return e.shiftKey ? 'left' : 'right';
  return undefined;
}

function TextEditor({ col, value, seed, rect, onCommit, onCancel }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const dateRef = useRef<HTMLInputElement>(null);
  const initial = seed ?? (isNumeric(col) ? value : col.type === 'datetime' ? value.replace('T', ' ').slice(0, 16) : value);
  const [text, setText] = useState(initial);
  const done = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    const end = el.value.length;
    el.setSelectionRange(end, end);
  }, []);
  // grow with the content (multi-line notes)
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.max(rect.height, el.scrollHeight)}px`;
  }, [text, rect.height]);

  const finish = (move: Move) => {
    if (done.current) return;
    done.current = true;
    onCommit({ kind: 'text', text }, move);
  };

  return (
    <div style={{ display: 'flex', alignItems: 'flex-start' }}>
      <textarea
        ref={ref}
        rows={1}
        value={text}
        spellCheck={col.type === 'str'}
        inputMode={isNumeric(col) ? 'decimal' : undefined}
        placeholder={col.type === 'date' ? 'YYYY-MM-DD, 3/10/2026, 3 Oct…' : undefined}
        style={inputStyle(rect.height, isNumeric(col) ? 'right' : 'left')}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => finish(null)}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === 'Escape') {
            e.preventDefault();
            done.current = true;
            onCancel();
            return;
          }
          if (e.key === 'Enter' && e.altKey) {
            // Alt+Enter = new line inside the cell, like Sheets
            e.preventDefault();
            const el = e.currentTarget;
            const s = el.selectionStart;
            setText((t) => `${t.slice(0, s)}\n${t.slice(el.selectionEnd)}`);
            requestAnimationFrame(() => el.setSelectionRange(s + 1, s + 1));
            return;
          }
          const m = moveFor(e);
          if (m !== undefined) {
            e.preventDefault();
            finish(m);
          }
        }}
      />
      {col.type === 'date' && (
        <>
          <button
            type="button"
            tabIndex={-1}
            title="Pick from a calendar"
            onMouseDown={(e) => {
              e.preventDefault();
              const el = dateRef.current;
              if (!el) return;
              el.value = /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : '';
              try {
                el.showPicker();
              } catch {
                el.focus();
              }
            }}
            style={{ all: 'unset', cursor: 'pointer', padding: '5px 8px', opacity: 0.7 }}
          >
            <CalendarOutlined />
          </button>
          <input
            ref={dateRef}
            type="date"
            tabIndex={-1}
            style={{ position: 'absolute', opacity: 0, pointerEvents: 'none', width: 1, height: 1, right: 0, bottom: 0 }}
            onChange={(e) => {
              if (!e.target.value) return;
              done.current = true;
              onCommit({ kind: 'value', value: e.target.value }, null);
            }}
          />
        </>
      )}
    </div>
  );
}

function PickEditor({ col, opts, value, seed, rect, onCommit, onCancel }: Props) {
  const { token } = theme.useToken();
  const ref = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState(seed ?? '');
  const done = useRef(false);

  const items = useMemo(() => {
    const low = q.trim().toLowerCase();
    const base = opts.map((o) => ({ value: String(o.value), label: o.label }));
    const filtered = low
      ? base
          .filter((o) => o.label.toLowerCase().includes(low))
          .sort((a, b) => Number(!a.label.toLowerCase().startsWith(low)) - Number(!b.label.toLowerCase().startsWith(low)))
      : base;
    return !col.required && !low && value !== '' ? [{ value: '', label: '(empty)' }, ...filtered] : filtered;
  }, [opts, q, col.required, value]);

  const [hi, setHi] = useState(0);
  useEffect(() => {
    const cur = q ? 0 : items.findIndex((o) => o.value === value);
    setHi(Math.max(0, cur));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${hi}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [hi]);

  const pick = (v: string, move: Move) => {
    if (done.current) return;
    done.current = true;
    onCommit({ kind: 'value', value: v }, move);
  };

  return (
    <div>
      <input
        ref={ref}
        value={q}
        placeholder={displayText(col, value, opts) || 'Type to search…'}
        style={inputStyle(rect.height, 'left')}
        onChange={(e) => setQ(e.target.value)}
        onBlur={() => {
          if (done.current) return;
          done.current = true;
          if (q.trim()) onCommit({ kind: 'text', text: q }, null);
          else onCancel();
        }}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === 'Escape') {
            e.preventDefault();
            done.current = true;
            onCancel();
          } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHi((h) => Math.min(items.length - 1, h + 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHi((h) => Math.max(0, h - 1));
          } else {
            const m = moveFor(e);
            if (m === undefined) return;
            e.preventDefault();
            if (items[hi]) pick(items[hi].value, m);
            else if (q.trim()) {
              done.current = true;
              onCommit({ kind: 'text', text: q }, m);
            } else {
              done.current = true;
              onCancel();
            }
          }
        }}
      />
      <div
        ref={listRef}
        onMouseDown={(e) => e.preventDefault()}
        style={{ maxHeight: 260, overflowY: 'auto', borderTop: `1px solid ${token.colorSplit}`, padding: 4 }}
      >
        {items.length === 0 && <div style={{ padding: '6px 8px', color: token.colorTextTertiary }}>No match</div>}
        {items.map((o, i) => (
          <div
            key={`${o.value}-${i}`}
            data-i={i}
            onMouseEnter={() => setHi(i)}
            onClick={() => pick(o.value, null)}
            style={{
              padding: '5px 8px',
              borderRadius: 4,
              cursor: 'pointer',
              background: i === hi ? token.controlItemBgActive : undefined,
              fontWeight: o.value === value ? 600 : undefined,
              color: o.value === '' ? token.colorTextTertiary : undefined,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {o.label}
          </div>
        ))}
      </div>
    </div>
  );
}
