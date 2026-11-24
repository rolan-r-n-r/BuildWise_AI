/**
 * landing/motion.ts — shared motion vocabulary for the landing page.
 * Apple-style curves only: cubic-bezier(0.32, 0.72, 0, 1) for timed
 * transitions, stiff/soft damped springs for interactive motion.
 * Every variant respects prefers-reduced-motion via `fadeOnly`.
 *
 * REVEAL BUDGET. A marketing page is read, not watched, and the old reveals
 * spent it: section content faded in over 900ms and the hero's headline mask
 * took 1050ms, so the first useful pixels of every section arrived a second
 * after it entered the viewport and scrolling faster than the animation meant
 * reading half-revealed copy. Everything now lands inside ~600ms, and the
 * hero's own entrance happens once, on load, before the reader can scroll.
 *
 * WHEN a reveal fires matters as much as how long it lasts, and that turned out
 * to be the real defect (see SETTLE_VIEWPORT): the reveals were firing at the
 * bottom edge of the screen, so they finished before the content was anywhere
 * near the reading position, and the page read as static with stray motion
 * happening behind the reader. Below-fold content now becomes visible ONCE, at
 * the reading line — which is also why none of it is scrubbed by the wheel:
 * text whose opacity tracks the scroll can be caught half-legible mid-scroll.
 * The scroll-linked half of this page's motion lives in scrollLink.ts (depth,
 * the product window, the map's analysis, the progress rail) and is
 * transform-only, on layers that were already composited.
 */
import type { Variants, Transition, TargetAndTransition } from 'framer-motion';

/**
 * A two-state reveal pair. Deliberately not typed as `Variants`: `Variant` also
 * allows a resolver FUNCTION, which is not assignable to the `initial` /
 * `whileInView` props, and these pairs are used as both — `variants={fadeRise}`
 * in the grids, `initial={fadeRise.hidden}` where a part reveals itself (see
 * SectionHeading). Typing the members as targets makes both work.
 */
export type RevealPair = { hidden: TargetAndTransition; show: TargetAndTransition };

/** Apple-style deceleration used for all timed (non-spring) motion. */
export const EASE_APPLE: [number, number, number, number] = [0.32, 0.72, 0, 1];

/**
 * Overshooting drop: the value runs PAST its target, comes back, and settles.
 * Used where something is dropped onto its resting place — the map pin — so it
 * can land with a bounce.
 *
 * A spring is a function of TIME, and the pin's drop no longer has a clock: it
 * is a band of scroll progress (scrollLink.useBand). A damped oscillation is
 * the same gesture written in the only variable the sequence has.
 *
 * Written out rather than passed as a cubic-bezier definition for a concrete
 * reason: `useTransform`'s `ease` option takes easing FUNCTIONS, and an array
 * there is read as one function per interpolation segment — a `[.34, 1.42,
 * .64, 1]` tuple would be called as `0.34(x)` at runtime. (Bezier tuples are
 * fine in a variant's `transition.ease`, which is a different code path, and
 * that is where EASE_APPLE is used.)
 *
 * Normalized so the curve lands EXACTLY on 1: the band ends at progress 1, and
 * a curve that was still 0.4% short there would leave the pin hanging above its
 * resting place for the rest of the page.
 */
const BOUNCE_DECAY = 5;
const BOUNCE_FREQUENCY = 2 * Math.PI * 1.15;
const rawBounce = (t: number): number => 1 - Math.exp(-BOUNCE_DECAY * t) * Math.cos(BOUNCE_FREQUENCY * t);
export const EASE_DROP = (t: number): number => rawBounce(t) / rawBounce(1);

/** Reveal duration for section content entering the viewport. */
export const REVEAL = 0.48;

/** Hero entrance: one beat slower than a section reveal, since it owns the fold. */
export const ENTRANCE = 0.68;

/** Interactive spring (buttons, toggles, chips): stiffness 260–320 / damping 26–30. */
export const SPRING_INTERACTIVE: Transition = {
  type: 'spring',
  stiffness: 300,
  damping: 28,
  mass: 1,
};

/** Softer spring for large surfaces (mockup rise, sheet menus). */
export const SPRING_SOFT: Transition = {
  type: 'spring',
  stiffness: 260,
  damping: 30,
  mass: 1,
};

/* The map pin's bouncy spring lived here. It is gone on purpose: the drop is a
   band of scroll progress now, and a spring needs a clock. See EASE_DROP. */

/**
 * Timed Apple-curve transition helper.
 *
 * A zero delay is OMITTED rather than written. This is not tidiness: a parent's
 * `staggerChildren` reaches a child as `{ delay: stagger, ...childTransition }`,
 * so a child whose own variant carries an explicit `delay: 0` overwrites the
 * staggered delay with zero — silently flattening every `staggerParent` on the
 * page into "all children at once". (Which is exactly what had happened here:
 * six capability cards and four dossier rows were each written as a staggered
 * group and were each revealing in a single frame.)
 */
export const timed = (duration: number, delay = 0): Transition =>
  delay > 0 ? { duration, delay, ease: EASE_APPLE } : { duration, ease: EASE_APPLE };

/**
 * Fade+rise, the reveal used for most section content. One shape everywhere on
 * purpose — a page that invents a different entrance per element reads as
 * noise, not as choreography — at 20px, roughly one line of copy: far enough to
 * register as arriving, close enough that the text is never legible while
 * displaced.
 */
export const fadeRise: RevealPair = {
  hidden: { opacity: 1, y: 12 },
  show: { opacity: 1, y: 0, transition: timed(REVEAL) },
};

/**
 * The same reveal, for SHORT elements: a hairline-divided row, a chip, a list
 * line. Settled from an already-visible default so no row is ever trapped
 * invisible during fast scrolls, printing, or full-page captures.
 */
export const fadeRiseTight: RevealPair = {
  hidden: { opacity: 1, y: 6 },
  show: { opacity: 1, y: 0, transition: timed(REVEAL * 0.8) },
};

/** Flat fade for reduced-motion swaps (no transform). */
export const fadeOnly: RevealPair = {
  hidden: { opacity: 1 },
  show: { opacity: 1, transition: timed(0.3) },
};

/** Parent that staggers children reveals. */
export const staggerParent = (stagger = 0.08, delayChildren = 0): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: stagger, delayChildren } },
});

/**
 * Masked curtain lift for display type: the line lives in an overflow-hidden
 * box and rises into it, so the type is uncovered rather than faded. This is
 * the hero's grammar (its headline has always arrived this way) applied one
 * step down the page — a heading that wipes up reads as set type; a heading
 * that fades reads as a div appearing.
 *
 * One beat longer than a body reveal: a 2.6rem line is a larger distance to
 * travel, and at the same duration it looks hurried rather than quick.
 *
 * 125% OF ITS OWN HEIGHT, not 100%, because the mask box carries padding for
 * descenders and that padding is INSIDE the clip (see SectionHeading). The type
 * must clear the padded strip as well as the line box, so the travel has to
 * exceed 100% plus the padding measured in line heights. At a 1.12 line-height
 * a 0.12em padding needs 0.107em more than 100%; 125% leaves real margin, and
 * the cost is only that the line starts a little further out of frame.
 */
export const maskLift: RevealPair = {
  hidden: { y: '0%' },
  show: { y: '0%', transition: timed(0.5) },
};

/**
 * A hairline drawing across the page from its left edge.
 *
 * Used on the section headings' eyebrow rule: at 1.5px the scale change is
 * invisible as motion, so what the reader perceives is the RULE arriving, which
 * is the page's strongest available signal that a section has started without
 * spending a colour or a shadow on it.
 */
export const ruleDraw: RevealPair = {
  hidden: { scaleX: 0 },
  show: { scaleX: 1, transition: timed(0.7) },
};

/**
 * Viewport for below-fold reveals: fire once, when the element's TOP edge
 * crosses 74% of the viewport height.
 *
 * This replaced `{ once: true, amount: 0.12 }`, which asked "is 12% of this
 * element's AREA on screen?" — a question whose answer depends on how tall the
 * element happens to be. For a full-height section that is true while the
 * section is still down at the bottom edge, so every reveal played to an empty
 * room: the reader's first sight of the content was content that had already
 * finished moving, with the motion happening off-screen behind them. Shortening
 * the observer's root by 26% puts the trigger at a fixed place on the screen
 * instead of a fraction of a box that changes size from section to section,
 * which is also what makes the timing predictable across the whole page.
 */
export const SETTLE_MARGIN = '0px 0px -8% 0px';

/** The same line, for elements that observe themselves with `useInView`. */
export const SETTLE_VIEWPORT = { once: true, margin: SETTLE_MARGIN } as const;

/** Reduced-motion variant swap helper: picks the flat fade when requested. */
export const reveal = (reducedMotion: boolean): Variants =>
  reducedMotion ? fadeOnly : fadeRise;
