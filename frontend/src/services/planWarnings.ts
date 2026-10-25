import type { FloorPlanResponse } from './types';

/**
 * PAGE-1 PLAN WARNINGS — one list for print, the sheet and the PDF.
 *
 * The proportion and programme evidence belongs on page 1. The in-app Print
 * Report used to read the analysis warnings only, while the
 * PDF read the plan object, so the two banners could disagree.  This module is
 * the single filter both surfaces use; the backend mirror lives in
 * `report_service.page1_plan_warnings`.
 */
export const PAGE1_PLAN_WARNING_PATTERN =
  /^(PROP-|PROGRAMME-|PLINTH:|ROOM-MIN|ROOM-MAX|ROOM-OVERLAP|SELECTION-FALLBACK|GATE-FAIL|PLATE-SHORT)/;

/**
 * Warnings loud enough to switch the banner to the red FAIL treatment.  A
 * listed proportion relaxation (`PROP-ASPECT`) is disclosed but not a FAIL by
 * itself; the squeezed-room and conflict lines are.
 */
export const CRITICAL_PLAN_WARNING_PATTERN =
  /^(GATE-FAIL|PROGRAMME-DEFICIT|PROGRAMME-SQUEEZE|PLATE-SHORT|PROP-HARD|PROP-PLATE-CAP|PROPORTION-FAIL|ROOM-MIN|ROOM-MAX|ROOM-OVERLAP|SELECTION-FALLBACK)\b/;

export function page1PlanWarnings(
  warnings?: readonly (string | null | undefined)[] | null,
): string[] {
  return (warnings ?? [])
    .map((w) => String(w ?? '').trim())
    .filter((w) => w.length > 0 && PAGE1_PLAN_WARNING_PATTERN.test(w));
}

export function isCriticalPlanWarning(w: string): boolean {
  return CRITICAL_PLAN_WARNING_PATTERN.test(String(w ?? ''));
}

/**
 * Split a plan's solver log into the page-1 disclosures and resolver noise.
 *
 * The card banner used to print its total line count under a "Proportion /
 * programme non-compliance" headline, so 15 lines of which 6 were plan
 * disclosures read as 15 failures.  Both surfaces list the same
 * facts; only the count changes to match the label.
 */
export function splitPlanWarnings(
  warnings?: readonly (string | null | undefined)[] | null,
): { planWarnings: string[]; resolverNotes: string[] } {
  const planWarnings = page1PlanWarnings(warnings);
  const seen = new Set(planWarnings);
  const resolverNotes = (warnings ?? [])
    .map((w) => String(w ?? '').trim())
    .filter((w) => w.length > 0 && !seen.has(w));
  return { planWarnings, resolverNotes };
}

/** Headline text for the card banner, so the label and the count agree. */
export function planWarningsHeadline(planCount: number, resolverCount: number): string {
  if (planCount > 0) return `Plan warnings (${planCount})`;
  if (resolverCount > 0) return `Resolver notes (${resolverCount})`;
  return 'Plan warnings (0)';
}

/**
 * The badge above the mathematical certificate follows the PLAN verdict, not
 * the gate alone. A certified geometry with named programme
 * deficits must not read "CERTIFIED" anywhere on the card.
 */
export function planVerdictBadge(
  verdict?: string | null,
): { text: string; tone: 'red' | 'amber' | 'green' } {
  if (verdict === 'NOT-CERTIFIED-FAIL-STAMP') return { text: 'PLAN NOT CERTIFIED', tone: 'red' };
  if (verdict === 'ADVISORY') return { text: 'CERTIFIED · ADVISORIES', tone: 'amber' };
  return { text: 'VERIFIED & CERTIFIED', tone: 'green' };
}

/** The banner payload: analysis warnings first, then the same plan list the PDF prints. */
export function bannerWarnings<T extends { warnings?: string[] } | null | undefined>(
  analysis: T,
  plan: FloorPlanResponse | null | undefined,
): string[] {
  const base = (analysis?.warnings ?? []).map((w) => String(w));
  const merged = [...base];
  for (const w of page1PlanWarnings(plan?.warnings)) {
    if (!merged.includes(w)) merged.push(w);
  }
  return merged;
}
