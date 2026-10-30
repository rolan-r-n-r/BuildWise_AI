/**
 * svgSanitize.ts — blueprint SVG sanitizer + ghost-overlay invariant gate.
 * ========================================================================
 * Extracted from BlueprintViewer so the ghost overlay contract is a pure,
 * testable rule rather than an inline expression:
 *
 *   GHOST OVERLAY CONTRACT — the F0 anchor core is already drawn on every
 *   sheet, so the ghost (upper-floor core collapse) overlay is meaningless on
 *   the ground floor. It is injected ONLY when `safeFloorIndex > 0` AND the
 *   user toggled it on. Both directions hold: ON at F0 renders false, OFF at
 *   F1+ renders false.
 */

import { MOTION } from '../../design/tokens';
import {
  BLUEPRINT_PHASE_DELAY_MS,
  BLUEPRINT_PHASE_DURATION_MS,
  BLUEPRINT_REVEAL_PHASES,
} from './blueprintReveal';

/** The gate. True only when the toggle is on AND an upper floor is active. */
export function isGhostOverlayVisible(showGhostOverlay: boolean, safeFloorIndex: number): boolean {
  return Boolean(showGhostOverlay) && safeFloorIndex > 0;
}

/** The `!important` override pair. Hidden is the default and the safe state. */
const GHOST_CSS_VISIBLE = '.ghost-core-overlay { display: block !important; opacity: 1 !important; }';
const GHOST_CSS_HIDDEN =
  '.ghost-core-overlay { display: none !important; opacity: 0 !important; visibility: hidden !important; }';

/**
 * Flip the ghost overlay on a sheet that is ALREADY injected, in place.
 *
 * The sanitized document carries both facts the contract is about — the rule
 * inside its injected `<style>` and the `data-ghost-overlay` attribute on the
 * `<svg>` — so a toggle never needs to re-parse or re-insert the sheet. Rewriting
 * those two nodes is two DOM writes; the React re-render that a state change
 * causes passes the SAME html string to `dangerouslySetInnerHTML`, which React
 * skips, so the patch stands. The sanitizer contract is unchanged: a fresh sheet,
 * and the print copy, are still produced by `sanitizeBlueprintSvg`.
 *
 * Returns false when the sheet is not in the DOM (nothing to flip), which lets
 * the caller fall back to re-injecting.
 */
export function patchGhostOverlayDom(root: ParentNode | null, ghostVisible: boolean): boolean {
  if (!root) return false;
  const svg = root.querySelector('svg');
  if (!svg) return false;
  const style = root.querySelector('style');
  if (!style) return false;
  const current = style.textContent || '';
  const from = ghostVisible ? GHOST_CSS_HIDDEN : GHOST_CSS_VISIBLE;
  const to = ghostVisible ? GHOST_CSS_VISIBLE : GHOST_CSS_HIDDEN;
  // Verify BEFORE writing either node: a partial patch (attribute flipped, rule
  // unchanged) would leave the overlay desynced from its own provenance flag,
  // which is the one thing the ghost contract forbids.
  if (!current.includes(from)) return false;
  style.textContent = current.replace(from, to);
  svg.setAttribute('data-ghost-overlay', ghostVisible ? 'true' : 'false');
  return true;
}

/**
 * Last sanitize result per ghost state, keyed by the SOURCE SVG IDENTITY.
 *
 * This function is pure, but its callers could only remember one result, so
 * every press of the ghost toggle re-parsed and re-injected a multi-hundred-node
 * sheet — the largest long task measured on that surface (191 ms at 4× CPU
 * throttle, ~48 ms at 1×) for an output it had already computed. Two sheets can
 * alternate forever (ghost on / ghost off), so two entries is exactly the bound.
 *
 * Identity, not a content hash: any different sheet — a regeneration, another
 * floor, a theme swap — misses the cache outright and REPLACES the map, so a
 * stale sheet can never be served. The cache is module-level because the function
 * is shared by every viewer instance and the key is the input itself.
 */
const sanitizeMemo: { svg: string | null; byGhost: Map<boolean, string> } = {
  svg: null,
  byGhost: new Map(),
};

/**
 * Strips scripts and inline handlers from a server-authored blueprint sheet,
 * then injects the fit + ghost-overlay styling and the `data-ghost-overlay`
 * provenance flag that mirrors `ghostVisible`.
 */
export function sanitizeBlueprintSvg(
  activeSvg: string | null | undefined,
  ghostVisible: boolean
): string {
  if (activeSvg && activeSvg === sanitizeMemo.svg) {
    const hit = sanitizeMemo.byGhost.get(ghostVisible);
    if (hit !== undefined) return hit;
  } else if (sanitizeMemo.svg !== activeSvg) {
    sanitizeMemo.svg = activeSvg ?? null;
    sanitizeMemo.byGhost = new Map();
  }
  const result = sanitizeBlueprintSvgUncached(activeSvg, ghostVisible);
  if (activeSvg) sanitizeMemo.byGhost.set(ghostVisible, result);
  return result;
}

function sanitizeBlueprintSvgUncached(
  activeSvg: string | null | undefined,
  ghostVisible: boolean
): string {
  if (!activeSvg) return '';
  const cleaned = activeSvg
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/on\w+\s*=\s*["'][^"']*["']/gi, '');

  // Sheets are authored at a fixed pixel size (a portrait site plan runs ~2500px
  // tall); the preview box and the modal are both shorter than that, so the lower
  // half of a tall sheet used to be cut off even at the smallest zoom. Constrain
  // the sheet to its container instead: it scales down to fit and the ratio holds.
  //
  // The reveal rules are inert unless the viewer puts `data-bw-reveal="run"` on
  // the root (startSheetReveal owns that switch). The `sheet` group — title
  // block, spec legend, validation gate and status stamp — is explicitly
  // excluded: the authoritative verdict must never fade in with the drawing.
  // Delays come from blueprintReveal.ts so the JS bound and the CSS cannot drift.
  // The delay selector needs at least the specificity of the shorthand above:
  // `[data-bw-reveal] [data-bw-phase]:not(...)` is (0,3,0), so a two-attribute
  // delay rule lost and the shorthand's `animation-delay: 0s` won. Every phase
  // then faded at once. Repeating both attributes on the delay rule makes the
  // intended stagger win deterministically.
  const phaseDelayCss = BLUEPRINT_REVEAL_PHASES.map(
    (phase) =>
      `        [data-bw-reveal="run"] [data-bw-phase]:not([data-bw-phase="sheet"])[data-bw-phase="${phase}"] { animation-delay: ${BLUEPRINT_PHASE_DELAY_MS[phase]}ms; }`
  ).join('\n');
  const styleInjection = `
      <style>
        ${ghostVisible ? GHOST_CSS_VISIBLE : GHOST_CSS_HIDDEN}
        .bw-sheet-fit { max-width: 100%; max-height: 100%; width: auto; height: auto; }
        /* Fit Width: the viewport width becomes the sheet width and the top of
           the sheet (the plan) starts at the top of the viewer. The viewer pans
           vertically over the rest. data-bw-view is set by the viewer only;
           a static export carries no such attribute and stays a full sheet. */
        svg[data-bw-view="width"] {
          position: absolute;
          top: 0;
          left: 50%;
          width: 100%;
          height: auto;
          max-width: none;
          max-height: none;
          transform: translateX(-50%);
          transform-origin: top center;
        }
        .bw-room-fill { transition: fill-opacity ${MOTION.duration.popover}ms ${MOTION.ease.out}; }
        svg[data-room-focus="on"] .bw-room-fill { fill-opacity: 0.04 !important; }
        svg[data-room-focus="on"] .bw-room-fill.bw-room-selected { fill-opacity: 0.42 !important; }
        [data-bw-reveal="run"] [data-bw-phase]:not([data-bw-phase="sheet"]) {
          opacity: 0;
          animation: bwSheetPhaseIn ${BLUEPRINT_PHASE_DURATION_MS}ms ${MOTION.ease.spatial} both;
        }
${phaseDelayCss}
        @keyframes bwSheetPhaseIn { from { opacity: 0; } to { opacity: 1; } }
        @media (prefers-reduced-motion: reduce) {
          .bw-room-fill { transition: none; }
          [data-bw-reveal="run"] [data-bw-phase] { opacity: 1; animation: none; }
        }
      </style>
    `;

  if (cleaned.includes('<svg')) {
    return cleaned.replace(
      /<svg\b([^>]*)>/i,
      `<svg $1 class="bw-sheet-fit" data-ghost-overlay="${ghostVisible ? 'true' : 'false'}">${styleInjection}`
    );
  }
  return cleaned;
}
