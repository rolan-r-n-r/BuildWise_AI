/**
 * blueprintReveal.ts — progressive sheet reveal + room focus, as pure DOM rules.
 * =============================================================================
 * The server emits the drawing in its real layer order inside inert groups:
 *
 *   envelope → site → rooms → ghost → walls → cores → openings →
 *   labels → dims → annotations, with the title block / validation gate in a
 *   final `sheet` group.
 *
 * This module owns two presentation-only behaviours over that output:
 *
 *   1. REVEAL — stages the existing groups into view, once per generation.
 *      The `sheet` group is deliberately NEVER animated: the title block, the
 *      validation gate rows and the FAIL stamp are visible from the first
 *      frame, so an animation can never imply that an uncertified plan passed.
 *   2. ROOM FOCUS — the selected room's fill brightens while every other room
 *      fill is muted. It only changes `fill-opacity`; walls, openings and
 *      dimensions stay exactly where the solver put them.
 *
 * No geometry is created here. The helpers mutate only presentation attributes
 * on an already-injected, server-authored sheet.
 */

import { MOTION } from '../../design/tokens';

/** The animated phases, in drawing order. `sheet` is excluded by design. */
export const BLUEPRINT_REVEAL_PHASES = [
  'envelope',
  'site',
  'rooms',
  'ghost',
  'walls',
  'cores',
  'openings',
  'labels',
  'dims',
  'annotations',
] as const;

export type BlueprintRevealPhase = (typeof BLUEPRINT_REVEAL_PHASES)[number];

/**
 * Delay per phase. Kept in the same order as the drawing so the sheet reads as
 * one pass — boundary, massing, structure, openings, then the annotation
 * layers. The whole sequence lands under 1 s.
 */
export const BLUEPRINT_PHASE_DELAY_MS: Record<BlueprintRevealPhase, number> = {
  envelope: 0,
  site: 50,
  rooms: 90,
  ghost: 130,
  walls: 190,
  cores: 260,
  openings: 330,
  labels: 430,
  dims: 520,
  annotations: 620,
};

/** One phase's fade duration: the existing panel token, not a new timing. */
export const BLUEPRINT_PHASE_DURATION_MS = MOTION.duration.panel;

/** Last phase delay + duration; the caller uses this only as a cleanup bound. */
export const BLUEPRINT_REVEAL_TOTAL_MS =
  BLUEPRINT_PHASE_DELAY_MS.annotations + BLUEPRINT_PHASE_DURATION_MS;

export type SheetRevealState = 'run' | 'done' | 'off';

/** True when the sheet carries at least one addressable phase group. */
export function sheetHasRevealPhases(svg: string | null | undefined): boolean {
  return typeof svg === 'string' && /data-bw-phase\s*=/.test(svg);
}

/** Write the reveal state onto the injected `<svg>`. */
export function setSheetRevealState(root: ParentNode | null, state: SheetRevealState): boolean {
  const svg = root?.querySelector?.('svg');
  if (!svg) return false;
  svg.setAttribute('data-bw-reveal', state);
  return true;
}

/** Read it back (missing attribute is reported as `null`, not a guess). */
export function readSheetRevealState(root: ParentNode | null): SheetRevealState | null {
  const svg = root?.querySelector?.('svg');
  const value = svg?.getAttribute('data-bw-reveal');
  return value === 'run' || value === 'done' || value === 'off' ? value : null;
}

/**
 * Focus one room fill in the injected sheet, or clear the focus.
 *
 * Exact id first, then the floor-suffixed/base id pair the legend already uses
 * (`living_F1` ↔ `living`), so a chip selects the right fill on either side of
 * the suffix convention. Returns the number of matched fills, which is what a
 * test (and a caller deciding whether a highlight is possible) wants to know.
 */
export function applyRoomFocus(root: ParentNode | null, roomId: string | null): number {
  const svg = root?.querySelector?.('svg');
  if (!svg) return 0;
  const fills = Array.from(svg.querySelectorAll<SVGElement>('.bw-room-fill[data-room-id]'));
  if (fills.length === 0) return 0;

  const wanted = roomId || '';
  const base = wanted.replace(/_F\d+$/, '');
  let matched = 0;
  for (const fill of fills) {
    const id = fill.getAttribute('data-room-id') || '';
    const fillBase = id.replace(/_F\d+$/, '');
    const selected =
      wanted !== '' && (id === wanted || (base !== '' && fillBase === base));
    fill.classList.toggle('bw-room-selected', selected);
    if (selected) matched += 1;
  }

  if (wanted) {
    svg.setAttribute('data-room-focus', 'on');
    svg.setAttribute('data-selected-room', wanted);
  } else {
    svg.removeAttribute('data-room-focus');
    svg.removeAttribute('data-selected-room');
  }
  return matched;
}

export interface StartedReveal {
  /** False when the sheet has no phases, motion is reduced, or it was used. */
  started: boolean;
  /** Idempotent: removes the listener/timer if the sheet is replaced. */
  cancel: () => void;
}

/**
 * Run the staged reveal on an injected sheet.
 *
 * The state attribute is the single switch: CSS only animates under
 * `data-bw-reveal="run"`, so an exported/printed SVG (which never receives the
 * attribute) is always the finished drawing. When the last phase finishes —
 * animationend, or a bounded fallback if the browser never fires it — the
 * attribute becomes `done`, which removes the animation objects rather than
 * leaving ten paused fade animations on a chart the user is panning.
 */
export function startSheetReveal(
  root: ParentNode | null,
  reducedMotion: boolean
): StartedReveal {
  const svg = root?.querySelector?.('svg');
  const noop = { started: false, cancel: () => {} };
  if (!svg) return noop;

  if (reducedMotion || svg.querySelectorAll('[data-bw-phase]').length === 0) {
    setSheetRevealState(root, 'off');
    return noop;
  }

  let finished = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const startedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();

  const finish = () => {
    if (finished) return;
    finished = true;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    svg.removeEventListener('animationend', onAnimationEnd);
    // Only finish the document this reveal was started on; a replacement sheet
    // has its own lifecycle and must not inherit this one's `done`.
    if (svg.isConnected) {
      const elapsed =
        (typeof performance !== 'undefined' ? performance.now() : Date.now()) - startedAt;
      svg.setAttribute('data-bw-reveal', 'done');
      // Diagnostic only (never exported): lets the browser test report the real
      // wall-clock sequence rather than the authored timing table.
      svg.setAttribute('data-bw-reveal-ms', String(Math.round(elapsed)));
    }
  };

  const onAnimationEnd = (event: Event) => {
    const target = event.target as Element | null;
    if (target?.getAttribute?.('data-bw-phase') === 'annotations') finish();
  };

  svg.setAttribute('data-bw-reveal', 'run');
  svg.setAttribute('data-bw-reveal-start', String(Math.round(startedAt)));
  svg.addEventListener('animationend', onAnimationEnd);
  timer = setTimeout(finish, BLUEPRINT_REVEAL_TOTAL_MS + 120);

  return {
    started: true,
    cancel: () => {
      finished = true;
      if (timer !== null) clearTimeout(timer);
      timer = null;
      svg.removeEventListener('animationend', onAnimationEnd);
    },
  };
}
