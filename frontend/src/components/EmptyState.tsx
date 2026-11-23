import { motion } from 'motion/react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import './empty.css';

/* ==========================================================================
   Empty state: the one way the portal says "nothing here".
   A big animated mascot (the logo's robot head, line-drawn), one short
   phrase under it, and one button at the bottom that sends people somewhere
   more useful. `compact` is for drawers, modals and small panels.
   ========================================================================== */

export type EmptyAction = { label: string; to?: string; onClick?: () => void; icon?: ReactNode };

const EASE = [0.33, 1, 0.68, 1] as const;

function Mascot({ size }: { size: number }) {
  return (
    <div className="es-art" style={{ width: size, height: size }} aria-hidden>
      <span className="es-art__halo" />
      <motion.svg
        viewBox="0 0 160 160" width={size} height={size} fill="none"
        className="es-art__bot"
        animate={{ y: [0, -7, 0] }}
        transition={{ duration: 4.2, repeat: Infinity, ease: 'easeInOut' }}
      >
        <defs>
          <linearGradient id="es-shell" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--es-shell-a)" />
            <stop offset="1" stopColor="var(--es-shell-b)" />
          </linearGradient>
          <linearGradient id="es-scan" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--brand-accent)" stopOpacity="0" />
            <stop offset="0.5" stopColor="var(--brand-accent)" stopOpacity="0.55" />
            <stop offset="1" stopColor="var(--brand-accent)" stopOpacity="0" />
          </linearGradient>
          <clipPath id="es-face"><rect x="38" y="52" width="84" height="66" rx="18" /></clipPath>
        </defs>

        {/* antennas */}
        <path d="M64 52 L56 30" stroke="var(--es-line)" strokeWidth="3" strokeLinecap="round" />
        <path d="M96 52 L104 30" stroke="var(--es-line)" strokeWidth="3" strokeLinecap="round" />
        <circle cx="56" cy="28" r="5" fill="url(#es-shell)" stroke="var(--es-line)" strokeWidth="2.5" />
        <motion.circle
          cx="104" cy="28" r="5" fill="var(--signal)"
          animate={{ opacity: [1, 0.25, 1] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* ear bolts */}
        <rect x="27" y="74" width="12" height="22" rx="5" fill="url(#es-shell)" stroke="var(--es-line)" strokeWidth="2.5" />
        <rect x="121" y="74" width="12" height="22" rx="5" fill="url(#es-shell)" stroke="var(--es-line)" strokeWidth="2.5" />

        {/* head */}
        <rect x="38" y="52" width="84" height="66" rx="18" fill="url(#es-shell)" stroke="var(--es-line)" strokeWidth="3" />

        {/* scan line sweeping the face */}
        <g clipPath="url(#es-face)">
          <motion.rect
            x="38" width="84" height="22" fill="url(#es-scan)"
            initial={{ y: 40 }}
            animate={{ y: [40, 112, 40] }}
            transition={{ duration: 3.4, repeat: Infinity, ease: 'easeInOut' }}
          />
        </g>

        {/* eyes: look around, blink now and then */}
        <motion.g
          animate={{ x: [0, -6, -6, 6, 6, 0] }}
          transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut', times: [0, 0.15, 0.4, 0.55, 0.8, 1] }}
        >
          {[64, 96].map((cx) => (
            <g key={cx}>
              <circle cx={cx} cy="82" r="11" fill="var(--es-eye-bg)" stroke="var(--es-line)" strokeWidth="2.5" />
              <motion.ellipse
                cx={cx} cy="82" rx="5" ry="5" fill="var(--brand-accent)"
                style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
                animate={{ scaleY: [1, 1, 0.12, 1, 1] }}
                transition={{ duration: 4.8, repeat: Infinity, times: [0, 0.46, 0.5, 0.54, 1] }}
              />
            </g>
          ))}
        </motion.g>

        {/* mouth grille */}
        {[66, 74, 82, 90].map((x) => (
          <rect key={x} x={x} y="102" width="4" height="7" rx="1.5" fill="var(--es-line)" opacity="0.55" />
        ))}
      </motion.svg>
      <motion.span
        className="es-art__shadow"
        animate={{ scaleX: [1, 0.82, 1], opacity: [0.5, 0.3, 0.5] }}
        transition={{ duration: 4.2, repeat: Infinity, ease: 'easeInOut' }}
      />
    </div>
  );
}

export default function EmptyState({
  phrase,
  action,
  compact = false,
}: {
  phrase: ReactNode;
  action?: EmptyAction | null;
  compact?: boolean;
}) {
  const navigate = useNavigate();
  const go = action ? (action.onClick ?? (() => action.to && navigate(action.to))) : undefined;
  return (
    <motion.div
      className={`es${compact ? ' es--compact' : ''}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: EASE }}
      role="status"
    >
      <Mascot size={compact ? 96 : 168} />
      <p className="es__phrase">{phrase}</p>
      {action && (
        <button type="button" className="es__btn" onClick={go}>
          {action.icon}
          <span>{action.label}</span>
          <svg viewBox="0 0 20 20" width={14} height={14} fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden>
            <path d="M4 10h11M11 6l4 4-4 4" />
          </svg>
        </button>
      )}
    </motion.div>
  );
}

/* ── Route-aware default ────────────────────────────────────────────────
   What antd shows for any empty table / list that didn't set its own:
   a phrase for the page and a button to the most related other page. */
const ROUTE_DEFAULTS: [string, string, EmptyAction][] = [
  ['/tasks', 'No tasks to show.', { label: 'Open the calendar', to: '/calendar' }],
  ['/requests', 'No requests yet.', { label: 'Browse inventory', to: '/inventory' }],
  ['/inventory', 'No components here.', { label: 'See requests', to: '/requests' }],
  ['/events', 'Nothing here yet.', { label: 'Open the calendar', to: '/calendar' }],
  ['/archive', 'Nothing archived yet.', { label: 'See current events', to: '/events' }],
  ['/team', 'No teammates here yet.', { label: 'See the organization', to: '/organization' }],
  ['/organization', 'No one here yet.', { label: 'See members', to: '/members' }],
  ['/members', 'No members match.', { label: 'Review applications', to: '/applications' }],
  ['/applications', 'No applications waiting.', { label: 'See members', to: '/members' }],
  ['/finance', 'No money records yet.', { label: 'Open the dashboard', to: '/explore' }],
  ['/explore', 'Nothing recorded here yet.', { label: 'Open data tables', to: '/admin/data' }],
  ['/courses', 'Nothing on this shelf yet.', { label: 'Open my tasks', to: '/tasks' }],
  ['/admin/audit', 'No changes logged yet.', { label: 'Back to Home', to: '/home' }],
  ['/admin', 'Nothing here yet.', { label: 'Back to Home', to: '/home' }],
];

export function RouteEmpty({ compact }: { compact?: boolean }) {
  const { pathname } = useLocation();
  const hit = ROUTE_DEFAULTS.find(([p]) => pathname === p || pathname.startsWith(`${p}/`));
  const [phrase, action] = hit ? [hit[1], hit[2]] : ['Nothing here yet.', { label: 'Back to Home', to: '/home' }];
  return <EmptyState phrase={phrase} action={action.to === pathname ? { label: 'Back to Home', to: '/home' } : action} compact={compact} />;
}
