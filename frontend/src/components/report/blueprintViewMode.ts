/**
 * blueprintViewMode.ts — sheet / plan / width framing over the real SVG.
 * =========================================================================
 * Three presentation modes, all implemented on the already-injected sheet:
 *
 *   sheet  — the complete drawing (the server's own viewBox).
 *   plan   — the union of the real plan-layer bounding boxes, padded; the
 *            title block, schedules and sheet furniture are outside it.
 *   width  — the complete drawing, scaled so its WIDTH fills the viewer and
 *            the top (plan) is aligned to the viewport. Vertical pan reaches
 *            the rest.
 *
 * Nothing is re-rendered, re-injected or re-solved. The helpers change only
 * `viewBox`, `width`/`height` (to make the cropped bbox the element's aspect
 * ratio) and two data attributes. The exported SVG is produced from the source
 * string, never from this DOM, so export/PDF keep the full sheet.
 */

export type BlueprintViewMode = 'sheet' | 'plan' | 'width';

export interface ViewBoxRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const BLUEPRINT_VIEW_MODES: ReadonlyArray<{
  id: BlueprintViewMode;
  label: string;
  short: string;
  hint: string;
}> = [
  { id: 'sheet', label: 'Full Sheet', short: 'Sheet', hint: 'The complete drawing' },
  { id: 'plan', label: 'Plan Focus', short: 'Plan', hint: 'The floor-plan region only' },
  { id: 'width', label: 'Fit Width', short: 'Width', hint: 'Drawing width fills the viewer' },
];

/** Plan-region layers, in drawing order. `sheet` (title block,
 *  validation gate, stamp) and `annotations` (compass, graphic scale) are
 *  excluded so the crop follows the building, not the paper furniture. */
export const PLAN_FOCUS_PHASES = [
  'envelope',
  'site',
  'rooms',
  'ghost',
  'walls',
  'cores',
  'openings',
  'labels',
  'dims',
] as const;

const BASE_VIEWBOX_ATTR = 'data-bw-base-viewbox';
const BASE_WIDTH_ATTR = 'data-bw-base-width';
const BASE_HEIGHT_ATTR = 'data-bw-base-height';
const VIEW_MODE_ATTR = 'data-bw-view';

export function parseViewBox(raw: string | null | undefined): ViewBoxRect | null {
  if (!raw) return null;
  const parts = raw.trim().split(/[\s,]+/).map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null;
  const [x, y, width, height] = parts;
  if (!(width > 0) || !(height > 0)) return null;
  return { x, y, width, height };
}

export function formatViewBox(rect: ViewBoxRect): string {
  const round = (n: number) => Math.round(n * 100) / 100;
  return `${round(rect.x)} ${round(rect.y)} ${round(rect.width)} ${round(rect.height)}`;
}

/** Union of real bounding boxes; null when nothing has extent. */
export function unionRects(rects: ViewBoxRect[]): ViewBoxRect | null {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const rect of rects) {
    if (!(rect.width > 0) || !(rect.height > 0)) continue;
    left = Math.min(left, rect.x);
    top = Math.min(top, rect.y);
    right = Math.max(right, rect.x + rect.width);
    bottom = Math.max(bottom, rect.y + rect.height);
  }
  if (!Number.isFinite(left) || right <= left || bottom <= top) return null;
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/**
 * Pad the real plan bounds and clamp them to the sheet.
 *
 * 4.5% of the larger dimension is enough to keep dimension chains and the
 * compass from touching the crop edge without pulling the schedules in. The
 * result can never exceed the base sheet: a crop outside the viewBox would
 * show empty margins.
 */
export function planFocusRect(base: ViewBoxRect, rects: ViewBoxRect[]): ViewBoxRect {
  const union = unionRects(rects);
  if (!union) return { ...base };
  const pad = Math.max(6, Math.max(union.width, union.height) * 0.045);
  let x = union.x - pad;
  let y = union.y - pad;
  let right = union.x + union.width + pad;
  let bottom = union.y + union.height + pad;

  x = Math.max(base.x, x);
  y = Math.max(base.y, y);
  right = Math.min(base.x + base.width, right);
  bottom = Math.min(base.y + base.height, bottom);

  if (right <= x || bottom <= y) return { ...base };
  return { x, y, width: right - x, height: bottom - y };
}

function getBBox(el: Element): ViewBoxRect | null {
  const graphics = el as SVGGraphicsElement;
  if (typeof graphics.getBBox !== 'function') return null;
  try {
    const box = graphics.getBBox();
    if (!(box.width > 0) || !(box.height > 0)) return null;
    return { x: box.x, y: box.y, width: box.width, height: box.height };
  } catch {
    return null;
  }
}

function setBaseAttributes(svg: SVGSVGElement, base: ViewBoxRect): void {
  if (!svg.hasAttribute(BASE_VIEWBOX_ATTR)) {
    svg.setAttribute(BASE_VIEWBOX_ATTR, formatViewBox(base));
  }
  const widthAttr = svg.getAttribute('width');
  const heightAttr = svg.getAttribute('height');
  if (!svg.hasAttribute(BASE_WIDTH_ATTR) && widthAttr) {
    svg.setAttribute(BASE_WIDTH_ATTR, widthAttr);
  }
  if (!svg.hasAttribute(BASE_HEIGHT_ATTR) && heightAttr) {
    svg.setAttribute(BASE_HEIGHT_ATTR, heightAttr);
  }
}

function restoreElementSize(svg: SVGSVGElement, base: ViewBoxRect): void {
  const width = svg.getAttribute(BASE_WIDTH_ATTR) || String(Math.round(base.width));
  const height = svg.getAttribute(BASE_HEIGHT_ATTR) || String(Math.round(base.height));
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
}

function setElementSize(svg: SVGSVGElement, rect: ViewBoxRect): void {
  const round = (n: number) => Math.round(n * 100) / 100;
  svg.setAttribute('width', String(round(rect.width)));
  svg.setAttribute('height', String(round(rect.height)));
}

export interface AppliedViewMode {
  ok: boolean;
  mode: BlueprintViewMode;
  viewBox: string | null;
  baseViewBox: string | null;
  planAvailable: boolean;
}

/**
 * Apply one framing mode to an injected sheet. Idempotent; safe to call on
 * every mode/floor change.
 *
 * `planAvailable` is false for sheets with no addressable plan layers (for
 * example a site-plan SVG authored in another generator); callers should
 * disable Plan Focus there instead of pretending it cropped.
 */
export function applyBlueprintViewMode(
  root: ParentNode | null,
  mode: BlueprintViewMode
): AppliedViewMode {
  const svg = root?.querySelector?.('svg') as SVGSVGElement | null;
  if (!svg) {
    return { ok: false, mode, viewBox: null, baseViewBox: null, planAvailable: false };
  }

  const rawBase =
    svg.getAttribute(BASE_VIEWBOX_ATTR) ||
    svg.getAttribute('viewBox') ||
    null;
  const base =
    parseViewBox(rawBase) ||
    ({
      x: 0,
      y: 0,
      width: svg.width?.baseVal?.value || 495,
      height: svg.height?.baseVal?.value || 1386,
    } satisfies ViewBoxRect);

  setBaseAttributes(svg, base);

  const boxes: ViewBoxRect[] = [];
  for (const phase of PLAN_FOCUS_PHASES) {
    const group = svg.querySelector(`[data-bw-phase="${phase}"]`);
    if (!group) continue;
    const box = getBBox(group);
    if (box) boxes.push(box);
  }
  const planAvailable = boxes.length > 0;
  const focused = mode === 'plan' && planAvailable ? planFocusRect(base, boxes) : base;

  svg.setAttribute('viewBox', formatViewBox(focused));
  svg.setAttribute(VIEW_MODE_ATTR, mode);
  if (mode === 'plan' && planAvailable) {
    setElementSize(svg, focused);
  } else {
    restoreElementSize(svg, base);
  }

  return {
    ok: true,
    mode,
    viewBox: formatViewBox(focused),
    baseViewBox: formatViewBox(base),
    planAvailable,
  };
}

/** Read the current mode back (used by probes/tests; null before first apply). */
export function readBlueprintViewMode(root: ParentNode | null): BlueprintViewMode | null {
  const value = (root?.querySelector?.('svg') as SVGSVGElement | null)?.getAttribute(VIEW_MODE_ATTR);
  return value === 'sheet' || value === 'plan' || value === 'width' ? value : null;
}
