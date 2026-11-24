/**
 * landing/scroll.ts — Lenis smooth scrolling for the landing route.
 * A single instance is created when the landing mounts (and destroyed on
 * unmount). Disabled entirely under prefers-reduced-motion.
 *
 * TUNING NOTE. This used to run on a 1.1s duration curve, which is the wrong
 * control for the input it is smoothing: a duration-based tween has to finish
 * its whole animation before the next wheel event can retarget it, so on a
 * trackpad — where every event is small and continuous — the page lagged the
 * fingers by a fixed slice of a second no matter how small the gesture was.
 * `lerp` (a fixed fraction of the remaining distance per frame) instead tracks
 * the pointer's own speed: small gestures move a little, big ones glide, and
 * the value approaches the target without ever spending a fixed second doing
 * it. 0.12 is the usual "still smooths, no longer feels detached" setting.
 *
 * Anchor jumps keep an explicit duration (an eased 0.9s travel), because those
 * ARE a single discrete gesture where a tween is the right shape.
 */
import Lenis from 'lenis';

let lenis: Lenis | null = null;
let rafId = 0;

const prefersReduced = (): boolean =>
  typeof window !== 'undefined' &&
  Boolean(window.matchMedia) &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Initialize the Lenis loop. Returns a cleanup fn. No-op when reduced. */
export function initLenis(): () => void {
  if (lenis || prefersReduced() || typeof window === 'undefined') return () => {};

  lenis = new Lenis({
    lerp: 0.12,
    wheelMultiplier: 1,
    smoothWheel: true,
    // The anchor offset below is the source of truth for section landing; a
    // second offset here would double it.
    autoRaf: false,
  });

  const raf = (time: number) => {
    lenis?.raf(time);
    rafId = requestAnimationFrame(raf);
  };
  rafId = requestAnimationFrame(raf);

  return () => {
    cancelAnimationFrame(rafId);
    lenis?.destroy();
    lenis = null;
  };
}

/** Pause or resume page & Lenis scrolling (used by mobile navigation drawer). */
export function setScrollLocked(locked: boolean): void {
  if (typeof document === 'undefined') return;
  if (locked) {
    lenis?.stop();
    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
  } else {
    document.documentElement.style.overflow = '';
    document.body.style.overflow = '';
    lenis?.start();
  }
}

/**
 * Smoothly scroll to a section id (works with and without Lenis).
 *
 * The landing's clearance under the floating nav pill is owned by the CSS
 * `scroll-mt-24` on each section, NOT by an offset passed here. That is the one
 * place both paths agree on: `scrollIntoView` (the reduced-motion / no-Lenis
 * path) only understands scroll-margin, and Lenis honours it too — so passing
 * Lenis its own `offset: -80` as well stacked the two and landed every section
 * 176px down the viewport instead of 96px. One source of truth, two engines,
 * same landing position.
 */
export function scrollToId(id: string): void {
  const el = document.getElementById(id);
  if (!el) return;
  if (lenis) {
    lenis.scrollTo(el, { duration: 0.9 });
  } else {
    el.scrollIntoView({
      behavior: prefersReduced() ? 'auto' : 'smooth',
      block: 'start',
    });
  }
}
