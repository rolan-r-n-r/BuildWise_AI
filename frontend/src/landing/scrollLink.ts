/**
 * landing/scrollLink.ts — the landing's scroll-LINKED motion.
 *
 * WHY THIS FILE EXISTS. Every reveal on this page used to be one shape: a 20px
 * fade-up fired by `whileInView` at 12% visibility. That is a toggle, not a
 * transition. It ignores the reader twice over — it fires while the section is
 * still down at the bottom edge of the screen, so the content has finished
 * moving before it ever reaches the reading position — and nothing on the page
 * moved WITH the scroll. A page that is read by scrolling should have at least
 * one layer that IS the scroll; these hooks are that layer.
 *
 * THE DIVISION OF LABOUR, deliberately:
 *
 *  - TYPE AND CARDS are still revealed once, on arrival, by framer-motion
 *    variants (see motion.ts SETTLE_VIEWPORT). Text whose opacity is bound to
 *    the wheel can be caught half-legible mid-scroll, and a marketing page's
 *    job is to be read, so text entrances stay one-shot. What changed there is
 *    WHEN they fire (at the reading position, not at the screen edge) and what
 *    they look like (masked, staggered, on this page's own curve).
 *
 *  - STRUCTURE AND DEPTH are scrubbed: the ambient backdrop drifts, the product
 *    window rises, the map's analysis plays, the progress rail reports. These
 *    are transform-only bindings on layers that were already composited, so the
 *    motion rides on the scroll without costing a paint per frame.
 *
 * All of it collapses honestly under prefers-reduced-motion: a scrubbed value
 * reports its SETTLED end (1) rather than 0, so every consumer renders its
 * finished state and there is nothing left to animate.
 */
import { useEffect, useMemo } from 'react';
import type { RefObject } from 'react';
import {
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useTransform,
} from 'framer-motion';
import type { MotionValue, UseScrollOptions } from 'framer-motion';
import { ENTRY_BAND as ENTRY, SETPIECE_BAND as SETPIECE, bandOffset } from './interaction/scrub';

/**
 * THE ENTRY BAND — the contract every scrubbed section obeys.
 *
 * `'start 0.92'` → `'start 0.55'` reads: progress runs 0 → 1 as the element's
 * TOP edge travels from 92% of the viewport height (a sliver showing at the
 * bottom) up to 55% (the top third — the reading position). Two consequences
 * worth stating, because they are the whole point:
 *
 *  1. The motion FINISHES before the content is being read. Nothing settles
 *     under the reader's eye; it has already arrived.
 *  2. 37% of a viewport of scroll is the entire travel, so the effect is
 *     visible and brief instead of a long lazy drift.
 *
 * The band is expressed against the element's top edge only, so it does not
 * care how tall the element is — the same numbers work for the 700px product
 * window and the 90px map legend.
 */
/*
 * THE BANDS COME FROM THE PROMOTED PRIMITIVES.
 *
 * `interaction/scrub.ts` owns the entry and set-piece bands as NUMBERS, and this
 * module owns their spelling as framer offset strings — so the landing's existing
 * scroll links and the new scrubbed sections cannot drift apart by one decimal
 * place, which is exactly how a page ends up with two entry bands that almost
 * match. `interaction/scrub.ts` records the contract; this file is one of its
 * consumers.
 */
const ENTRY_OFFSET: NonNullable<UseScrollOptions['offset']> = bandOffset(ENTRY);

/**
 * A longer band, for the one element on the page that is a SET PIECE rather
 * than a layer: the map's analysis.
 *
 * The map has a second of choreography in it (boundary, vertices, pin, chips)
 * and the entry band above is only 37% of a viewport — about 0.6s at a normal
 * scroll. Stretching the map's own band to 60% of a viewport gives that
 * sequence somewhere to play, so the demo is legible whether the reader is
 * crawling or flinging, instead of being over before the pin has landed.
 *
 * It ENDS at 40%, not at the 55% the other bands end at: the map is the bottom
 * half of the product window, so a reader who has settled it on screen has its
 * top edge around 35–45% of the viewport, and a band that ended later would
 * leave them looking at an analysis that had not finished running.
 */
/**
 * The set-piece band as two edges of the viewport, so the numbers can be used twice:
 * once as a `useScroll` offset (above) and once by `useSetpieceProgress` (below), which
 * has to do the arithmetic itself. Expressed as a fraction of the viewport height:
 * progress runs 0 → 1 as the element's top edge travels from the bottom edge to 40%.
 */
export const SETPIECE_FROM = SETPIECE.from;
export const SETPIECE_TO = SETPIECE.to;

export const SETPIECE_BAND: NonNullable<UseScrollOptions['offset']> = bandOffset(SETPIECE);

/**
 * Progress (0→1) for a SET PIECE, measured from the element's own geometry and latched.
 *
 * WHY NOT `useScroll({ target })` HERE. framer measures the target through
 * `getBoundingClientRect`, and any frame in which the element has no layout — a hidden
 * tab, a frame before the page has laid out, a resize while the section is off-screen —
 * reports its top edge at 0. On a band that begins at the bottom of the viewport, top 0
 * is a progress of 1. Latched, that single bad sample marks the whole sequence FINISHED
 * before a reader has seen any of it: the build-up plays silently, off-screen, and the
 * page looks like it was never animated. That is not hypothetical: it is what the
 * scroll-scrubbed plan build-up did on its first build — a section that has since been
 * removed entirely, code and all (see `LandingPage`'s history) — and it was only visible
 * by reading the drawn geometry back out of the DOM at the top of the page, where the
 * plan reported itself already finished. The hook is kept because the hazard belongs to
 * the next set piece as much as to that one; nothing in `src/` consumes it today, and
 * `SETPIECE_BAND` above is kept for the same reason.
 *
 * So this measures the geometry itself, on scroll and on resize, and it:
 *   - ignores any frame in which the element has no height (no layout → no opinion),
 *   - clamps to [0, 1] so a lazy-loaded page growing above the section cannot over-report,
 *   - never lets the value fall, so the sequence only ever builds (see `useLatch` for why
 *     un-building reads as a bug), and
 *   - reports the settled end (1) under `prefers-reduced-motion`, so those readers see the
 *     finished plan and no motion at all.
 */
export function useSetpieceProgress(ref: RefObject<HTMLElement | null>): MotionValue<number> {
  const reduced = useReducedMotion();
  const progress = useMotionValue(reduced ? 1 : 0);

  useEffect(() => {
    if (reduced) {
      progress.set(1);
      return;
    }
    const el = ref.current;
    if (!el) return;

    const travel = (SETPIECE_FROM - SETPIECE_TO) || 1;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      const viewport = window.innerHeight || 1;
      if (rect.height <= 0) return;
      const next = Math.min(1, Math.max(0, (viewport * SETPIECE_FROM - rect.top) / (viewport * travel)));
      if (next > progress.get()) progress.set(next);
    };

    measure();
    window.addEventListener('scroll', measure, { passive: true });
    window.addEventListener('resize', measure);
    return () => {
      window.removeEventListener('scroll', measure);
      window.removeEventListener('resize', measure);
    };
  }, [ref, reduced, progress]);

  return progress;
}

/**
 * Progress (0→1) for one element's journey across the entry band.
 *
 * One `useScroll` per scrubbed element. framer-motion shares a single scroll
 * listener per container and measures each target once per frame (a couple of
 * rect reads), so a handful of these is cheap — but a handful is the budget:
 * scrubbing is for LAYERS, not for every paragraph.
 */
export function useEntryProgress(
  ref: RefObject<HTMLElement | null>,
  band: NonNullable<UseScrollOptions['offset']> = ENTRY_OFFSET,
): MotionValue<number> {
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: band });
  return useTransform(scrollYProgress, (v) => (reduced ? 1 : v));
}

/**
 * One step of a scroll-linked sequence: `progress` remapped through a sub-band
 * of itself — 0 before `from`, 1 after `to`, eased in between.
 *
 * This is how a scrubbed element is choreographed. Writing the whole sequence
 * against ONE progress value (the container's) means the parts cannot drift
 * apart: the boundary draws at 0.10–0.50 of the same travel the pin drops at
 * 0.62–0.82 of, so the order holds at every scroll speed instead of being
 * enforced by a set of independent timers that a fast reader outruns.
 */
export function useBand(
  progress: MotionValue<number>,
  from: number,
  to: number,
  output: [number, number],
  ease?: (value: number) => number,
): MotionValue<number> {
  return useTransform(progress, [from, to], output, ease ? { ease } : undefined);
}

/**
 * Page-wide scroll progress, for the layers that span the whole document.
 *
 * `position: fixed` layers are the one place on this page where a true
 * parallax is free: they are already composited, already painted, and already
 * outside the document flow, so moving them is a transform on an existing
 * layer. (`scrollY` is returned too — the rail fades in on the first scroll and
 * ambient drift is expressed in absolute travel, not in progress.)
 */
export function usePageScroll(): {
  scrollY: MotionValue<number>;
  progress: MotionValue<number>;
} {
  const { scrollY, scrollYProgress } = useScroll();
  return useMemo(() => ({ scrollY, progress: scrollYProgress }), [scrollY, scrollYProgress]);
}

/**
 * A whole-pixel vertical drift, scaled by how much of the scroll a layer takes.
 *
 * WHY WHOLE PIXELS: the ambient grid is 1px rules at 5% alpha. Translated by a
 * fractional amount, each rule is resampled across its own pixel and loses or
 * regains contrast every frame — the lines visibly shimmer, and a blueprint
 * that shimmers reads as a broken texture rather than as paper. Rounding the
 * offset keeps every rule on the pixel grid it was drawn for.
 *
 * SIGN. The page's content travels up at 100% of the scroll, so a background
 * layer has to travel up at a FRACTION of it to read as distant — which is a
 * negative factor here (translate the fixed layer up by `factor * scrollY`).
 * Positive would move the layer down the screen as the reader scrolls down,
 * against the content; that is the aggressive "sliding panels" direction and
 * is not what a page of paper does.
 *
 * `factor` is that fraction: 0 = pinned to the viewport (infinitely far),
 * -1 = moving with the content (the page's own plane). The layers here live
 * between the two, and it is the DIFFERENCE between their factors that the eye
 * reads as depth.
 */
export function useDrift(scrollY: MotionValue<number>, factor: number): MotionValue<number> {
  return useTransform(scrollY, (v) => Math.round(v * factor));
}

/**
 * A monotonic copy of a progress value: it follows the scroll forward and holds
 * whatever it has seen on the way back up.
 *
 * The map's analysis is physics, not a scrub bar. A plot boundary that
 * un-draws, vertices that unpick themselves and a pin that flies back out of
 * the ground tells a different story from the one that section is telling.
 * Latching keeps the part that makes scroll-linking feel good — the sequence
 * plays at the reader's own pace, under their finger, instead of on a 2.5s
 * timer they may never be present for — and drops the part that reads as a bug.
 */
export function useLatch(progress: MotionValue<number>): MotionValue<number> {
  const latched = useMotionValue(progress.get());
  useMotionValueEvent(progress, 'change', (v) => {
    if (v > latched.get()) latched.set(v);
  });
  return latched;
}

