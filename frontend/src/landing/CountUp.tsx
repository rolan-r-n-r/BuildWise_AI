/**
 * CountUp.tsx — Restraint-first tabular number count-up on scroll arrival.
 * Respects prefers-reduced-motion and skips animation for counters already
 * visible above the initial fold so digits never flash backward on hydration.
 */
import React, { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'framer-motion';

export interface CountUpProps {
  /** Target numeric value. */
  value: number;
  /** Formatter applied to the current interpolated value. */
  format?: (n: number) => string;
  /** Duration in milliseconds (default 620ms). */
  durationMs?: number;
  /** Starting fraction of target (e.g. 0.6 feels calmer than jumping from 0). */
  startFraction?: number;
  className?: string;
}

export const CountUp: React.FC<CountUpProps> = ({
  value,
  format = (n) => String(Math.round(n)),
  durationMs = 620,
  startFraction = 0.6,
  className = '',
}) => {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const [display, setDisplay] = useState<number>(value);
  const hasAnimated = useRef(false);
  const prevValue = useRef(value);

  useEffect(() => {
    let syncRaf = 0;
    let animRaf = 0;

    if (prevValue.current !== value) {
      prevValue.current = value;
      hasAnimated.current = false;
      syncRaf = requestAnimationFrame(() => setDisplay(value));
    }

    if (reduced || typeof IntersectionObserver === 'undefined') {
      return () => {
        if (syncRaf) cancelAnimationFrame(syncRaf);
      };
    }

    const el = ref.current;
    if (!el || hasAnimated.current) {
      return () => {
        if (syncRaf) cancelAnimationFrame(syncRaf);
      };
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting || hasAnimated.current) continue;
          hasAnimated.current = true;
          io.disconnect();

          // Do not jump a visible initial-fold number backward from `value` to `startFraction`.
          if (window.scrollY < 16 && entry.boundingClientRect.top < window.innerHeight * 0.9) {
            return;
          }

          const from = value * startFraction;
          const start = performance.now();
          const tick = (now: number) => {
            const t = Math.min(1, (now - start) / durationMs);
            const eased = 1 - Math.pow(1 - t, 3);
            setDisplay(from + (value - from) * eased);
            if (t < 1) {
              animRaf = requestAnimationFrame(tick);
            } else {
              setDisplay(value);
            }
          };
          animRaf = requestAnimationFrame(tick);
        }
      },
      { threshold: 0.2 },
    );

    io.observe(el);
    return () => {
      io.disconnect();
      if (syncRaf) cancelAnimationFrame(syncRaf);
      if (animRaf) cancelAnimationFrame(animRaf);
    };
  }, [value, durationMs, startFraction, reduced]);

  return (
    <span ref={ref} className={`ui-font-tabular ${className}`}>
      {format(reduced ? value : display)}
    </span>
  );
};
