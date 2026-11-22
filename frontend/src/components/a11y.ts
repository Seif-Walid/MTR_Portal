import type { HTMLAttributes, KeyboardEvent } from 'react';

/**
 * Props for an antd `Table` row that opens something on click.
 * Adds what a mouse-only `onClick` misses: the row joins the tab order and
 * opens on Enter / Space, and it gets the shared focus ring (`.mtr-row-open`).
 * Keys pressed inside a control in the row (a button, a link) are left alone.
 */
export function openableRow(open: () => void): HTMLAttributes<HTMLElement> {
  return {
    onClick: open,
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
      if (e.target !== e.currentTarget) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        open();
      }
    },
    tabIndex: 0,
    className: 'mtr-row-open',
    style: { cursor: 'pointer' },
  };
}

/**
 * Props that make a non-button element (a card, a pill, a list row) behave
 * like a button for keyboard and screen-reader users. Prefer a real
 * `<button>` where the markup allows it.
 */
export function asButton(activate: () => void, opts: { pressed?: boolean; label?: string } = {}): HTMLAttributes<HTMLElement> {
  return {
    role: 'button',
    tabIndex: 0,
    'aria-pressed': opts.pressed,
    'aria-label': opts.label,
    onClick: activate,
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
      if (e.target !== e.currentTarget) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activate();
      }
    },
  };
}
