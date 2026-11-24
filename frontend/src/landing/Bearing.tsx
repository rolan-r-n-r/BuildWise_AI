/**
 * Bearing.tsx — the page's rotating survey instrument.
 *
 * WHY. The landing is drawn in the language of a plot sheet: grid, dimension
 * chains, a compass rose, a scale bar. The one thing a sheet can do that a
 * scrolling page usually does not is REPORT the reader's travel — and the
 * instrument that does that natively is a bearing dial: its card turns under a
 * fixed needle, so one glance says "something is moving through a known scale"
 * without a single word of explanation. The backdrop rose has done this since
 * the page was rebuilt; this component is the same instrument at section scale,
 * where it can be read rather than felt, and where the empty right-hand column
 * of the hero and the standards header had nothing in it at all.
 *
 * WHAT MOVES, AND WHAT DOES NOT. Two things turn and one holds:
 *
 *  · the CARD (ticks, numerals, outer ring) turns with the scroll;
 *  · the inner dashed ring turns the other way, at a different rate — two rates
 *    on one dial is what makes it read as a mechanism instead of a spinning
 *    picture;
 *  · the NEEDLE is fixed, pointing at `bearing`. A compass whose needle turned
 *    with its card would be pointing at nothing.
 *
 * The live readout (optional) prints the card's own bearing as it turns. It is
 * written to a text node from a MotionValue event, not from React state: a
 * per-frame `setState` here would re-render the whole hero sixty times a second
 * for four digits. The element is tabular-nums and fixed-width so the digits
 * never reflow their neighbours while the number changes.
 *
 * COST. Three composited transforms on one small element — no canvas, no
 * layout, no paint. Like the backdrop's own instruments this is not gated on
 * prefers-reduced-motion: rotation that follows the reader's scroll is
 * position, not animation, it stops the instant they do, and the component's
 * callers hand it a progress value that already reports its settled end for
 * readers who ask for less motion (see `useEntryProgress`).
 *
 * COLOUR. Everything is `currentColor`, so a caller sets the tone with a text
 * class (`text-bw-accent` for the dials on the porcelain ground) and the SVG
 * carries no palette of its own. No hex literals: the token gate treats a new
 * file with a raw colour as a regression.
 */
import React, { useRef } from 'react';
import {
  motion,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useSpring,
  useTransform,
  type MotionValue,
} from 'framer-motion';
import { SPRING_POSE } from './interaction';

export interface BearingProps {
  /** The scroll value that drives the turn — a page progress or an entry progress. */
  progress: MotionValue<number>;
  /** Degrees the card turns across progress 0 → 1. Negative turns anticlockwise. */
  sweep?: number;
  /** Degrees the inner dashed ring turns across the same range (usually the opposite way). */
  counterSweep?: number;
  /** Degrees the FIXED needle points at: a real bearing, e.g. 42 for the sample plot. */
  bearing?: number;
  /** Small mono label under the dial. */
  caption?: string;
  /** Second, dimmer mono line — a datum or the codes the dial stands for. */
  footnote?: string;
  /** Print the card's current bearing beside the caption. */
  readout?: boolean;
  /**
   * How solid the DIAL is, 0 → 1. Applied to the drawing only, never to the
   * captions: a watermark-weight instrument is the point, but caption type that
   * inherits the same opacity loses its contrast (measured 2.88:1 at 0.8 in the
   * landing audit). Text keeps its own token colour.
   */
  dialOpacity?: number;
  /** Enable subtle local pointer interaction on the needle and outer ring. */
  interactive?: boolean;
  /** Sizing and tone; the SVG fills the box this element gets. */
  className?: string;
}

const TICKS = 72;
const NUMERALS = Array.from({ length: 12 }, (_, i) => i * 30);
const CARDINALS: Record<number, string> = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' };
const SECTORS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const;

const at = (angleDeg: number, radius: number) => {
  const a = (angleDeg * Math.PI) / 180;
  return { x: 100 + radius * Math.sin(a), y: 100 - radius * Math.cos(a) };
};

const pad = (v: number) => String(Math.round(((v % 360) + 360) % 360)).padStart(3, '0');
const sectorOf = (v: number) => {
  const norm = ((v % 360) + 360) % 360;
  return SECTORS[Math.round(norm / 45) % 8];
};

export const Bearing: React.FC<BearingProps> = ({
  progress,
  sweep = 64,
  counterSweep = -110,
  bearing = 42,
  caption,
  footnote,
  readout = false,
  dialOpacity = 1,
  interactive = true,
  className,
}) => {
  const reduced = useReducedMotion();
  const card = useTransform(progress, [0, 1], [0, sweep]);
  const counter = useTransform(progress, [0, 1], [0, counterSweep]);

  /* Local hover needle deflection (±10° damped spring). Uses zero window
     listeners and zero React state updates during pointer moves. */
  const rawDeflect = useMotionValue(0);
  const needleDeflect = useSpring(rawDeflect, SPRING_POSE);
  const dialRef = useRef<HTMLDivElement>(null);

  /* The readout's text node, written directly. One element, one text write per
     frame at most, and no value at all when `readout` is false. */
  const digits = useRef<HTMLSpanElement>(null);
  const sectorRef = useRef<HTMLSpanElement>(null);
  const updateReadout = () => {
    // Both `card` (dial ring) and `needleDeflect` (pointer hover) use clockwise
    // positive screen rotation, so both add to the printed bearing telemetry.
    const angle = bearing + card.get() + needleDeflect.get();
    if (digits.current) digits.current.textContent = pad(angle);
    if (sectorRef.current) sectorRef.current.textContent = sectorOf(angle);
  };
  useMotionValueEvent(card, 'change', updateReadout);
  useMotionValueEvent(needleDeflect, 'change', updateReadout);

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (reduced || !interactive || e.pointerType === 'touch') return;
    const el = dialRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = e.clientX - cx;
    const dy = e.clientY - cy;
    const pointerAngle = (Math.atan2(dx, -dy) * 180) / Math.PI;
    // Shortest signed angular difference from needle bearing, gently damped to ±10°
    let delta = ((pointerAngle - bearing + 540) % 360) - 180;
    delta = Math.max(-10, Math.min(10, delta * 0.14));
    rawDeflect.set(delta);
  };

  const onPointerLeave = () => {
    rawDeflect.set(0);
  };

  /* The needle is drawn once at `bearing` and deflected smoothly on hover. */
  const tip = at(bearing, 58);
  const tail = at(bearing, -16);
  const left = at(bearing - 90, 5.4);
  const right = at(bearing + 90, 5.4);

  return (
    <div className={className} aria-hidden>
      <div
        ref={dialRef}
        onPointerMove={onPointerMove}
        onPointerLeave={onPointerLeave}
        data-interactive={interactive && !reduced ? 'true' : undefined}
        className={`bw-bearing-dial group relative aspect-square rounded-full transition-opacity duration-200 ${
          interactive && !reduced ? 'cursor-crosshair' : ''
        }`}
        style={{ '--bw-dial-opacity': String(dialOpacity) } as React.CSSProperties}
      >
        {/* Subtle calibration halo ring visible on hover */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-[2%] rounded-full border border-current opacity-0 transition-opacity duration-200 group-hover:opacity-25"
        />

        {/* The card: ring, ticks, numerals. */}
        <motion.svg viewBox="0 0 200 200" className="absolute inset-0 h-full w-full" style={{ rotate: card }}>
          <g fill="none" stroke="currentColor" strokeLinecap="round">
            <circle cx="100" cy="100" r="96" strokeWidth="1.1" opacity="0.6" />
            <circle cx="100" cy="100" r="99" strokeWidth="0.5" opacity="0.22" />
            {Array.from({ length: TICKS }, (_, i) => {
              const angle = i * 5;
              const cardinal = angle % 90 === 0;
              const major = angle % 30 === 0;
              const mid = angle % 15 === 0;
              const inner = cardinal ? 78 : major ? 83 : mid ? 86 : 89;
              const outer = cardinal ? 98 : 96;
              const from = at(angle, inner);
              const to = at(angle, outer);
              return (
                <line
                  key={angle}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  strokeWidth={cardinal ? 1.8 : major ? 1.15 : mid ? 0.85 : 0.55}
                  opacity={cardinal ? 0.92 : major ? 0.68 : mid ? 0.5 : 0.35}
                />
              );
            })}
          </g>
          <g
            fill="currentColor"
            fontSize="8.5"
            fontWeight={600}
            textAnchor="middle"
            dominantBaseline="middle"
            fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          >
            {NUMERALS.map((angle) => {
              const p = at(angle, 70);
              const label = CARDINALS[angle] ?? pad(angle);
              return (
                <text key={angle} x={p.x} y={p.y} opacity={CARDINALS[angle] ? 0.92 : 0.48}>
                  {label}
                </text>
              );
            })}
          </g>
        </motion.svg>

        {/* The inner ring: same centre, opposite turn, at its own rate. */}
        <motion.svg viewBox="0 0 200 200" className="absolute inset-0 h-full w-full" style={{ rotate: counter }}>
          <g fill="none" stroke="currentColor" strokeLinecap="round">
            <circle cx="100" cy="100" r="50" strokeWidth="0.9" strokeDasharray="2.5 5" opacity="0.55" />
            <circle cx="100" cy="100" r="32" strokeWidth="0.55" opacity="0.24" />
            {[45, 135, 225, 315].map((angle) => {
              const from = at(angle, 50);
              const to = at(angle, 58);
              return <line key={angle} x1={from.x} y1={from.y} x2={to.x} y2={to.y} strokeWidth="0.9" opacity="0.5" />;
            })}
          </g>
        </motion.svg>

        {/* Static center reticle crosshair */}
        <svg viewBox="0 0 200 200" className="pointer-events-none absolute inset-0 h-full w-full">
          <g stroke="currentColor" strokeWidth="0.65" opacity="0.28">
            <line x1="100" y1="74" x2="100" y2="126" />
            <line x1="74" y1="100" x2="126" y2="100" />
          </g>
        </svg>

        {/* The needle — points at `bearing`, gently responds to pointer hover. */}
        <motion.svg
          viewBox="0 0 200 200"
          className="pointer-events-none absolute inset-0 h-full w-full"
          style={{ rotate: needleDeflect }}
        >
          <g fill="none" stroke="currentColor" strokeLinecap="round" opacity="0.68">
            <line x1={tail.x} y1={tail.y} x2={tip.x} y2={tip.y} strokeWidth="0.9" />
          </g>
          <polygon
            points={`${tip.x},${tip.y} ${left.x},${left.y} ${tail.x},${tail.y} ${right.x},${right.y}`}
            fill="currentColor"
            opacity="0.78"
          />
          <circle cx="100" cy="100" r="4.5" fill="currentColor" opacity="0.86" />
          <circle cx="100" cy="100" r="1.7" fill="var(--bw-white)" />
        </motion.svg>
      </div>

      {(caption || readout || footnote) && (
        <div className="mt-3 flex flex-col gap-1">
          {(caption || readout) && (
            <div className="flex items-baseline justify-between gap-3">
              {caption ? (
                <span
                  className="text-[10px] font-semibold uppercase text-bw-ink-2"
                  style={{ letterSpacing: '0.16em' }}
                >
                  {caption}
                </span>
              ) : (
                <span />
              )}
              {readout && (
                <span className="font-mono text-[11px] font-semibold tabular-nums text-bw-accent">
                  <span ref={digits}>{pad(bearing)}</span>
                  <span className="text-bw-ink-2">° </span>
                  <span ref={sectorRef} className="text-[10px] text-bw-ink-2">
                    {sectorOf(bearing)}
                  </span>
                </span>
              )}
            </div>
          )}
          {footnote && (
            <span className="font-mono text-[10px] uppercase text-bw-ink-2" style={{ letterSpacing: '0.12em' }}>
              {footnote}
            </span>
          )}
        </div>
      )}
    </div>
  );
};
