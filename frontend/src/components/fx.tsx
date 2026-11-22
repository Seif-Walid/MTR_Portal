/* Interactive surface effects, after JDevelops' desktop shell:
   a cursor-pushed field of floating cubes for hero bands, a 3D tilt card,
   a count-up number and an orbital action button. Everything honours
   prefers-reduced-motion (static frame, no tilt, no count-up). */
import {
  animate,
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
} from 'motion/react';
import { useEffect, useRef, useState } from 'react';

/* ── Cube field ──────────────────────────────────────────────────────────
   Wire-frame cubes drift through the band and get shoved away from the
   cursor with a spring back home; nearby cubes are joined by faint traces.
   Draws in white so it sits on any of the gradient bands. */
type Cube = {
  hx: number; hy: number; // home position, 0..1
  s: number; // size px
  rot: number; spin: number;
  phase: number; drift: number;
  px: number; py: number; vx: number; vy: number; // push offset + velocity
};

function makeCubes(n: number): Cube[] {
  // deterministic layout so the band looks the same every visit
  let seed = 7;
  const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  return Array.from({ length: n }, (_, i) => ({
    hx: 0.08 + ((i + rnd() * 0.6) / n) * 0.9,
    hy: 0.15 + rnd() * 0.7,
    s: 14 + rnd() * 26,
    rot: rnd() * Math.PI,
    spin: (rnd() - 0.5) * 0.25,
    phase: rnd() * Math.PI * 2,
    drift: 6 + rnd() * 10,
    px: 0, py: 0, vx: 0, vy: 0,
  }));
}

function drawCube(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, rot: number, alpha: number) {
  // isometric wire cube: front square + back square offset + joining edges
  const d = s * 0.42;
  const c = Math.cos(rot), sn = Math.sin(rot);
  const pt = (px: number, py: number) => [x + px * c - py * sn, y + px * sn + py * c] as const;
  const h = s / 2;
  const f = [pt(-h, -h), pt(h, -h), pt(h, h), pt(-h, h)];
  const b = [pt(-h + d, -h - d), pt(h + d, -h - d), pt(h + d, h - d), pt(-h + d, h - d)];
  ctx.strokeStyle = `rgba(255,255,255,${alpha})`;
  ctx.fillStyle = `rgba(255,255,255,${alpha * 0.12})`;
  ctx.beginPath();
  f.forEach(([a, bb], i) => (i ? ctx.lineTo(a, bb) : ctx.moveTo(a, bb)));
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  b.forEach(([a, bb], i) => (i ? ctx.lineTo(a, bb) : ctx.moveTo(a, bb)));
  ctx.closePath();
  ctx.stroke();
  ctx.beginPath();
  for (let i = 0; i < 4; i++) {
    ctx.moveTo(f[i][0], f[i][1]);
    ctx.lineTo(b[i][0], b[i][1]);
  }
  ctx.stroke();
}

export function CubeField({ count = 9 }: { count?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const cubes = makeCubes(count);
    let w = 0, h = 0, raf = 0, visible = true, last = performance.now();
    const mouse = { x: -9999, y: -9999 };

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = r.width; h = r.height;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const frame = (t: number) => {
      const dt = Math.min((t - last) / 1000, 0.05);
      last = t;
      ctx.clearRect(0, 0, w, h);
      ctx.lineWidth = 1;
      const pos: [number, number][] = [];
      for (const cb of cubes) {
        if (!reduce) {
          // cursor push: inverse-distance force inside a 150px radius
          const bx = cb.hx * w + Math.sin(t / 2400 + cb.phase) * cb.drift;
          const by = cb.hy * h + Math.cos(t / 3100 + cb.phase) * cb.drift;
          const dx = bx + cb.px - mouse.x, dy = by + cb.py - mouse.y;
          const dist = Math.hypot(dx, dy);
          if (dist < 150 && dist > 0.1) {
            const f = (1 - dist / 150) * 2200;
            cb.vx += (dx / dist) * f * dt;
            cb.vy += (dy / dist) * f * dt;
          }
          // spring home + damping
          cb.vx += -cb.px * 9 * dt; cb.vy += -cb.py * 9 * dt;
          cb.vx *= 1 - 4.2 * dt; cb.vy *= 1 - 4.2 * dt;
          cb.px += cb.vx * dt; cb.py += cb.vy * dt;
          cb.rot += (cb.spin + Math.hypot(cb.vx, cb.vy) * 0.002) * dt;
          pos.push([bx + cb.px, by + cb.py]);
        } else {
          pos.push([cb.hx * w, cb.hy * h]);
        }
      }
      // traces between neighbours
      for (let i = 0; i < pos.length; i++) {
        for (let j = i + 1; j < pos.length; j++) {
          const d = Math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]);
          if (d < 190) {
            ctx.strokeStyle = `rgba(255,255,255,${(1 - d / 190) * 0.16})`;
            ctx.beginPath();
            ctx.moveTo(pos[i][0], pos[i][1]);
            ctx.lineTo(pos[j][0], pos[j][1]);
            ctx.stroke();
          }
        }
      }
      cubes.forEach((cb, i) => {
        const near = Math.hypot(pos[i][0] - mouse.x, pos[i][1] - mouse.y) < 150;
        drawCube(ctx, pos[i][0], pos[i][1], cb.s, cb.rot, near ? 0.55 : 0.28);
      });
      if (!reduce && visible) raf = requestAnimationFrame(frame);
    };

    const host = canvas.parentElement!;
    const onMove = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
    };
    const onLeave = () => { mouse.x = -9999; mouse.y = -9999; };
    host.addEventListener('pointermove', onMove);
    host.addEventListener('pointerleave', onLeave);

    const ro = new ResizeObserver(() => { resize(); if (reduce) frame(performance.now()); });
    ro.observe(canvas);
    // stop drawing when scrolled away or the tab is hidden
    const io = new IntersectionObserver(([en]) => {
      const was = visible;
      visible = en.isIntersecting && !document.hidden;
      if (visible && !was && !reduce) { last = performance.now(); raf = requestAnimationFrame(frame); }
    });
    io.observe(canvas);
    const onVis = () => {
      const was = visible;
      visible = !document.hidden;
      if (visible && !was && !reduce) { last = performance.now(); raf = requestAnimationFrame(frame); }
    };
    document.addEventListener('visibilitychange', onVis);

    resize();
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect(); io.disconnect();
      host.removeEventListener('pointermove', onMove);
      host.removeEventListener('pointerleave', onLeave);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [count, reduce]);

  return <canvas ref={ref} className="fx-cubes" aria-hidden />;
}

/* ── Spotlight ───────────────────────────────────────────────────────────
   Soft light that follows the cursor across a surface. Returns props to
   spread on the host and a style for the glow layer. */
export function useSpotlight() {
  const x = useMotionValue(-400);
  const y = useMotionValue(-400);
  const bg = useMotionTemplate`radial-gradient(420px circle at ${x}px ${y}px, rgba(255,255,255,0.16), transparent 60%)`;
  const onPointerMove = (e: React.PointerEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    x.set(e.clientX - r.left);
    y.set(e.clientY - r.top);
  };
  const onPointerLeave = () => { x.set(-400); y.set(-400); };
  return { hostProps: { onPointerMove, onPointerLeave }, glow: bg };
}

/* ── Tilt ────────────────────────────────────────────────────────────────
   Leans a card toward the cursor (max `deg`) with a glare spot. */
export function useTilt(deg = 7) {
  const reduce = useReducedMotion();
  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const sx = useSpring(px, { stiffness: 260, damping: 22 });
  const sy = useSpring(py, { stiffness: 260, damping: 22 });
  const rotateY = useTransform(sx, [0, 1], [-deg, deg]);
  const rotateX = useTransform(sy, [0, 1], [deg, -deg]);
  const gx = useTransform(sx, (n) => `${n * 100}%`);
  const gy = useTransform(sy, (n) => `${n * 100}%`);
  const glare = useMotionTemplate`radial-gradient(160px circle at ${gx} ${gy}, rgba(255,255,255,0.28), transparent 70%)`;
  const onPointerMove = (e: React.PointerEvent<HTMLElement>) => {
    if (reduce) return;
    const r = e.currentTarget.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width);
    py.set((e.clientY - r.top) / r.height);
  };
  const onPointerLeave = () => { px.set(0.5); py.set(0.5); };
  return {
    style: reduce ? {} : { rotateX, rotateY, transformPerspective: 700 },
    handlers: { onPointerMove, onPointerLeave },
    glare,
  };
}

/* ── Count-up ────────────────────────────────────────────────────────── */
export function CountUp({ value, duration = 0.9 }: { value: number; duration?: number }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? value : 0);
  const from = useRef(reduce ? value : 0);
  useEffect(() => {
    if (reduce) { setShown(value); return; }
    const c = animate(from.current, value, {
      duration,
      ease: [0.33, 1, 0.68, 1],
      onUpdate: (n) => setShown(Math.round(n)),
    });
    from.current = value;
    return () => c.stop();
  }, [value, duration, reduce]);
  return <>{shown}</>;
}

/* ── Orbital button ──────────────────────────────────────────────────────
   The hero's one primary action: a white tile inside a slowly orbiting
   ring and a breathing halo. */
export function OrbitButton({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <div className="fx-orbit">
      <motion.button
        type="button"
        className="fx-orbit__btn"
        onClick={onClick}
        aria-label={label}
        whileHover={{ scale: 1.06 }}
        whileTap={{ scale: 0.92 }}
        transition={{ type: 'spring', stiffness: 500, damping: 26 }}
      >
        <span className="fx-orbit__halo" aria-hidden />
        <span className="fx-orbit__ring" aria-hidden />
        <span className="fx-orbit__tile">{icon}</span>
      </motion.button>
      <span className="fx-orbit__label" aria-hidden>{label}</span>
    </div>
  );
}
