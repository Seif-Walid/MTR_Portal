import markSvg from '../assets/logo-mark.svg?raw';

/** The Mind-Tech Robotics mark as inline SVG with no background around it.
    Its own colours (black ink, white fill, grey shading, red ticks) are fixed
    so it looks the same in light and dark. Traced from the website's logo-mark. */
export function LogoImage({ size = 40, label = 'Mind-Tech Robotics' }: { size?: number; radius?: number; label?: string }) {
  return (
    <span
      className="mtr-logo"
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
      style={{ height: size, width: size * (541 / 620) }}
      dangerouslySetInnerHTML={{ __html: markSvg.replace('role="img" aria-label="Mind Tech Robotics"', 'aria-hidden="true"') }}
    />
  );
}

export function Wordmark({ color = 'currentColor', size = 15 }: { color?: string; size?: number }) {
  return (
    <div style={{ color, lineHeight: 1.15, userSelect: 'none' }}>
      <div style={{ fontWeight: 800, fontSize: size, letterSpacing: 0.5, whiteSpace: 'nowrap' }}>
        [ MIND·TECH ]
      </div>
      <div
        style={{
          fontSize: size * 0.56,
          fontWeight: 600,
          letterSpacing: size * 0.32,
          opacity: 0.85,
          whiteSpace: 'nowrap',
        }}
      >
        ROBOTICS
      </div>
    </div>
  );
}
