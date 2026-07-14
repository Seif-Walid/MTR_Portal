/** The actual Mind-Tech Robotics logo (frontend/public/logo.png). */
export function LogoImage({ size = 40, radius = 10 }: { size?: number; radius?: number }) {
  return (
    <img
      src="/logo.png"
      alt="Mind-Tech Robotics"
      style={{
        height: size,
        width: 'auto',
        borderRadius: radius,
        display: 'block',
      }}
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
