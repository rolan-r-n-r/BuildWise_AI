/**
 * warningReport.ts — THE warning information architecture (pure).
 * =================================================================
 * A FAIL-stamped plan used to print one undifferentiated list: ~55 raw solver
 * lines (door swings, circulation repairs, vent risers) beside the certificate
 * failures they buried, followed by one 200-char relaxation rationale per row.
 * The reader could not see what failed, what was accepted, or what the engine
 * merely did.
 *
 * Four tiers, one owner (this module) so the counts on screen can never drift
 * from the lines the full list prints:
 *   T1  certificate failures  — always visible, always counted
 *   T2  accepted relaxations  — structured, grouped one row per room
 *   T3  advisories            — collapsed with a count (waste/rotation, RULE-FP,
 *                               PLATE-GROWTH, ideal-band and provenance notes)
 *   T4  engine operations     — collapsed drawer, EXCLUDED from warning counts
 *                               (swing resolutions, wet-stack moves, acoustic
 *                               buffers, vent risers, furniture rebalancing,
 *                               terrace removals, land absorption)
 *
 * Disclosure is never weakened: every tier is one click from its full list and
 * the raw messages remain verbatim. PDF page-1 is a separate backend surface
 * and is not changed here.
 */
import type { FloorPlanResponse } from './types';
import { isCriticalPlanWarning, page1PlanWarnings } from './planWarnings';

export type WarningTier = 'T1' | 'T2' | 'T3' | 'T4';

/* ------------------------------------------------------------------ */
/* TRUTH LABELS — the ONE grouping, mirrored from plan_verdict.py      */
/* ------------------------------------------------------------------ */

/**
 * The certificate is the only source of certificate-failure rows, listed
 * deviations get their own group and count, and the rows a FAIL stamp rests on
 * are their own group.  The heading templates below are byte-identical to
 * backend/app/services/plan_verdict.py (pinned by
 * backend/tests/test_plan_verdict_parity.py) so the screen, the print view and
 * the PDF can never print a group to a different count.
 */
export const CERTIFICATE_FAILURES_HEADING = 'CERTIFICATE FAILURES ({count})';
export const LISTED_DEVIATIONS_HEADING = 'LISTED DEVIATIONS ({count})';
export const UNRESOLVED_BREACHES_HEADING = 'UNRESOLVED BREACHES ({count})';
export const TRUTH_SUMMARY_TEMPLATE =
  'Certificate failures: {failures} · Listed deviations: {deviations} · Unresolved breaches: {breaches}';

export interface TruthLabelInput {
  /** Certificate failure rows, verbatim (`mathematical_certificate.failures`). */
  certificateFailures?: readonly (string | null | undefined)[] | null;
  /** Rooms carrying at least one structured relaxation. */
  listedRooms?: readonly string[] | null;
}

export interface ListedDeviationRow {
  roomId: string;
  ruleId: string;
  /** Verbatim page-1 row when one exists, else the structured rationale. */
  reason: string;
  page1Row: string | null;
  source: 'page1' | 'structured';
}

export interface TruthLabels {
  certificateFailures: string[];
  listedDeviations: ListedDeviationRow[];
  unresolvedBreaches: string[];
  headings: {
    certificateFailures: string;
    listedDeviations: string;
    unresolvedBreaches: string;
  };
  counts: {
    certificateFailures: number;
    listedDeviations: number;
    unresolvedBreaches: number;
  };
  /** The one summary line: the counts, stated separately. */
  summary: string;
  structuredRelaxations: number;
  listedDeviationRooms: number;
}

const BEYOND_CAP_RE = /beyond\b.*\bcap|unlisted breach/i;
// "... and no listed relaxation" is the opposite of a listing; the naive
// substring match used to read it as a listed, within-cap deviation.
const NOT_LISTED_RE = /\bno listed relaxation\b|\bunlisted\b/i;
const LISTED_ROW_RE =
  /(declared relaxation|certificate-listed relaxation|listed relaxation|accepted at|inside the .* band|within the .* cap|declared ceiling|^PROP-IDEAL|^PLINTH:)/i;  const ROOM_MAX_RE =
    /is\s+([\d.]+)\s*m²,\s*above its\s+([\d.]+)\s*m²\s*catalogue maximum/i;
const SQUEEZE_ROOMS_RE = /below their minimum:\s*(.+?)\)/i;
const TRUTH_ROOM_ID_RE = /\b([A-Za-z0-9_]+_F\d+)\b/;

/** Rooms a page-1 row names (room ids, or the squeeze room list). */
export function rowNamedRooms(row: string): string[] {
  const text = String(row ?? '');
  const names = text.match(TRUTH_ROOM_ID_RE) ? [TRUTH_ROOM_ID_RE.exec(text)![1]] : [];
  const squeeze = SQUEEZE_ROOMS_RE.exec(text);
  if (squeeze) {
    for (const part of squeeze[1].split(',')) {
      const name = part.trim();
      if (name) names.push(name);
    }
  }
  return names;
}

/**
 * True when a page-1 row is a listed, within-cap deviation — the mirror of
 * `plan_verdict._row_is_listed`.  The row text alone cannot tell a listed
 * shortfall from an unlisted one, so the room's structured relaxation is read
 * for the ROOM-MIN / PROGRAMME-SQUEEZE forms.
 */
export function isListedPlanRow(row: string, listedRooms: ReadonlySet<string>): boolean {
  const text = String(row ?? '').trim();
  if (!text || BEYOND_CAP_RE.test(text) || NOT_LISTED_RE.test(text)) return false;
  if (/^PROGRAMME-SQUEEZE/i.test(text)) {
    const match = SQUEEZE_ROOMS_RE.exec(text);
    if (!match) return false;
    const named = match[1].split(',').map((part) => part.trim()).filter(Boolean);
    return named.length > 0 && named.every((room) => listedRooms.has(room));
  }
  if (/^ROOM-MAX/i.test(text)) {
    const match = ROOM_MAX_RE.exec(text);
    if (!match) return false;
    const measured = Number(match[1]);
    const ceiling = Number(match[2]);
    return ceiling > 0 && measured / ceiling <= 1.4 + 1e-9;
  }
  if (/^ROOM-MIN/i.test(text)) {
    const rooms = rowNamedRooms(text);
    return rooms.length > 0 && rooms.every((room) => listedRooms.has(room));
  }
  return LISTED_ROW_RE.test(text);
}

/** The certificate failure rows a plan payload carries (never a warning). */
export function truthInputForPlan(
  plan:
    | { mathematical_certificate?: { failures?: readonly (string | null)[] | null } | null }
    | null
    | undefined,
): TruthLabelInput {
  return { certificateFailures: plan?.mathematical_certificate?.failures ?? [] };
}

/**
 * The ONE truth-label grouping for a set of warnings + structured relaxations.
 * Mirrors `plan_verdict.plan_truth_labels` so both surfaces agree on what is a
 * certificate failure, what is a listed deviation and what is a breach.
 */
export function truthLabels(
  warnings: readonly (string | null | undefined)[] | null | undefined,
  relaxations: readonly RelaxationInput[] | null | undefined = [],
  input: TruthLabelInput = {},
): TruthLabels {
  const raw = (warnings ?? [])
    .map((w) => normalizeWs(String(w ?? '')))
    .filter(Boolean);
  const relInputs = (relaxations ?? []).filter((r) => r && r.room);
  const listedRooms = new Set<string>(
    (input.listedRooms ?? relInputs.map((r) => r.room)).map((room) => String(room)),
  );
  const certificateFailures = (input.certificateFailures ?? [])
    .map((f) => String(f ?? '').trim())
    .filter(Boolean);

  const page1 = page1PlanWarnings(raw);
  const page1Set = new Set(page1);
  const listedDeviations: ListedDeviationRow[] = [];
  const unresolvedBreaches: string[] = [];
  for (const row of page1) {
    if (isCriticalPlanWarning(row) && !isListedPlanRow(row, listedRooms)) {
      unresolvedBreaches.push(row);
      continue;
    }
    if (isListedPlanRow(row, listedRooms)) {
      const rooms = rowNamedRooms(row);
      listedDeviations.push({
        roomId: rooms[0] ?? '',
        ruleId: String(row.split(':', 1)[0] ?? '').trim(),
        reason: row,
        page1Row: row,
        source: 'page1',
      });
    }
    // Neither a breach nor a listed deviation: an advisory row.  It stays in
    // the advisory tier and the full list, never in a failure count.
  }
  for (const item of relInputs) {
    if (listedDeviations.some((d) => d.page1Row && d.roomId === item.room)) continue;
    listedDeviations.push({
      roomId: item.room,
      ruleId: item.rule_id,
      reason: normalizeWs(item.rationale),
      page1Row: null,
      source: 'structured',
    });
  }
  for (const row of raw) {
    if (page1Set.has(row)) continue;
    if (isCriticalPlanWarning(row) && !isListedPlanRow(row, listedRooms)) {
      // A failure-grade engine-log row that never reached page 1 stays visible
      // as a breach, not hidden behind an advisory count.
      if (!unresolvedBreaches.includes(row)) unresolvedBreaches.push(row);
    }
  }

  const counts = {
    certificateFailures: certificateFailures.length,
    listedDeviations: listedDeviations.length,
    unresolvedBreaches: unresolvedBreaches.length,
  };
  return {
    certificateFailures,
    listedDeviations,
    unresolvedBreaches,
    headings: {
      certificateFailures: CERTIFICATE_FAILURES_HEADING.replace('{count}', String(counts.certificateFailures)),
      listedDeviations: LISTED_DEVIATIONS_HEADING.replace('{count}', String(counts.listedDeviations)),
      unresolvedBreaches: UNRESOLVED_BREACHES_HEADING.replace('{count}', String(counts.unresolvedBreaches)),
    },
    counts,
    summary: TRUTH_SUMMARY_TEMPLATE
      .replace('{failures}', String(counts.certificateFailures))
      .replace('{deviations}', String(counts.listedDeviations))
      .replace('{breaches}', String(counts.unresolvedBreaches)),
    structuredRelaxations: relInputs.length,
    listedDeviationRooms: new Set(relInputs.map((r) => r.room)).size,
  };
}

export interface WarningEntry {
  /** Stable key: whitespace-normalized message text. */
  key: string;
  /** Verbatim first occurrence. */
  raw: string;
  /** Message with the shared relaxation-policy tail removed. */
  display: string;
  tier: WarningTier;
  code: string;
  roomId: string | null;
  floorIndex: number | null;
  /** How many identical raw lines this entry represents (>= 1). */
  occurrences: number;
  /** Raw positions, for the full list / provenance. */
  indices: number[];
}

export interface RawWarning {
  index: number;
  raw: string;
  tier: WarningTier;
  code: string;
}

export interface RelaxationItem {
  roomId: string;
  floorIndex: number | null;
  ruleId: string;
  /** Full rationale, verbatim. */
  rationale: string;
  /** Rationale with the shared policy tail stripped. */
  reason: string;
  /** Short, distinct chip label (never the boilerplate). */
  chip: string;
  measure: string | null;
  factor: number | null;
}

export interface RelaxationGroup {
  roomId: string;
  floorIndex: number | null;
  items: RelaxationItem[];
  rules: string[];
}

export interface TierCount {
  /** Raw message lines in this tier (sum of `occurrences`). */
  messages: number;
  /** Distinct grouped rows in this tier. */
  entries: number;
}

export interface WarningReport {
  totalMessages: number;
  totalDistinct: number;
  /** T1 + T3 raw lines. T4 is excluded from the warning headline by contract. */
  warningMessages: number;
  tiers: { T1: TierCount; T2: TierCount; T3: TierCount; T4: TierCount };
  /** T1 = unresolved breaches (the rows a FAIL stamp rests on). */
  failures: WarningEntry[];
  /** T2 = listed, within-cap deviations — never counted as failures. */
  deviations: WarningEntry[];
  advisories: WarningEntry[];
  operations: WarningEntry[];
  entries: WarningEntry[];
  /** The certificate-owned grouping every surface prints. */
  truth: TruthLabels;
  fullList: RawWarning[];
  relaxations: {
    items: RelaxationItem[];
    groups: RelaxationGroup[];
    total: number;
    rooms: number;
    policy: string;
    /** True when the policy sentence above was extracted from the payload. */
    policyFromEngine: boolean;
  };
}

/* ==================================================================== */
/* Classification                                                        */
/* ==================================================================== */

/** Engine operations: work the solver did, not a defect the reader must act on. */
const T4_PATTERNS: RegExp[] = [
  /^Swing resolution:/i,
  /^CIRC-REPAIR:/i,
  /^WET-STACK-ALIGN\b/i,
  /^Acoustic Buffer Enforced:/i,
  /^VENTILATION:/i,
  /^Furniture\b.*rebalanc/i,
  /^Furniture catalog\b/i,
  /^Terrace\b.*removed/i,
  /^Room '[^']+' (?:fully inside|trimmed)\b.*terrace/i,
  /^LAND-02\b/i,
  /^LAND-07\b/i,
  // Representative-floor solve: the solver's own choice of one governing
  // plate, not a defect.  Disclosed in the operation drawer, never counted as
  // a warning or hidden from the full list.
  /^STACK-SOLVE\b/i,
  /^STRATEGY-CHAIN\b/i,
];

/**
 * Certificate failures. ROOM-MIN/MAX includes the "declared relaxation" form:
 * the certificate still fails the dimension layer in that case, so it belongs
 * with the failures, never with the advisories.
 */
const T1_PATTERNS: RegExp[] = [
  /^PROP-HARD\b/i,
  /^PROP-PLATE-CAP\b/i,
  /^PROPORTION-FAIL\b/i,
  /^GATE-FAIL\b/i,
  /^PROGRAMME-SQUEEZE\b/i,
  /^PROGRAMME-DEFICIT\b/i,
  /^ROOM-MIN\b/i,
  /^ROOM-MAX\b/i,
  /^ROOM-OVERLAP\b/i,
  /^PLATE-SHORT\b/i,
  /^LAND-01\b/i,
  /^PROGRAM INTENT VIOLATION\b/i,
  /^SELECTION-FALLBACK\b/i,
];

const CODE_PATTERNS: Array<[RegExp, string]> = [
  [/^PROP-HARD\b/i, 'PROP-HARD'],
  [/^PROP-PLATE-CAP\b/i, 'PROP-PLATE-CAP'],
  [/^PROP-ASPECT\b/i, 'PROP-ASPECT'],
  [/^PROP-IDEAL\b/i, 'PROP-IDEAL'],
  [/^PROPORTION-FAIL\b/i, 'PROPORTION-FAIL'],
  [/^GATE-FAIL\b/i, 'GATE-FAIL'],
  [/^PROGRAMME-SQUEEZE\b/i, 'PROGRAMME-SQUEEZE'],
  [/^PROGRAMME-DEFICIT\b/i, 'PROGRAMME-DEFICIT'],
  [/^PROGRAM INTENT VIOLATION\b/i, 'PROGRAM INTENT'],
  [/^ROOM-MIN\b/i, 'ROOM-MIN'],
  [/^ROOM-MAX\b/i, 'ROOM-MAX'],
  [/^ROOM-OVERLAP\b/i, 'ROOM-OVERLAP'],
  [/^PLATE-SHORT\b/i, 'PLATE-SHORT'],
  [/^PLATE-GROWTH\b/i, 'PLATE-GROWTH'],
  [/^SELECTION-FALLBACK\b/i, 'SELECTION-FALLBACK'],
  [/^RULE-FP-\d+/i, 'RULE-FP'],
  [/^ZONING WARNING\b/i, 'ZONING'],
  [/^METRICS\b/i, 'METRICS'],
  [/^Waste warning\b/i, 'WASTE'],
  [/^Swing resolution:/i, 'SWING'],
  [/^CIRC-REPAIR:/i, 'CIRC-REPAIR'],
  [/^WET-STACK-ALIGN\b/i, 'WET-STACK'],
  [/^Acoustic Buffer Enforced:/i, 'ACOUSTIC'],
  [/^VENTILATION:/i, 'VENTILATION'],
  [/^Furniture\b.*rebalanc/i, 'FURNITURE'],
];

export function classifyWarning(message: string): { tier: WarningTier; code: string } {
  const text = String(message ?? '').trim();
  let tier: WarningTier = 'T3';
  if (T4_PATTERNS.some((re) => re.test(text))) tier = 'T4';
  else if (T1_PATTERNS.some((re) => re.test(text))) tier = 'T1';

  let code = 'OTHER';
  if (tier === 'T4') {
    if (/^Swing resolution:/i.test(text)) code = 'SWING';
    else if (/^CIRC-REPAIR:/i.test(text)) code = 'CIRC-REPAIR';
    else if (/^WET-STACK-ALIGN\b/i.test(text)) code = 'WET-STACK';
    else if (/^Acoustic Buffer Enforced:/i.test(text)) code = 'ACOUSTIC';
    else if (/^VENTILATION:/i.test(text)) code = 'VENTILATION';
    else if (/^Furniture\b/i.test(text)) code = 'FURNITURE';
    else if (/^LAND-0\d\b/i.test(text)) code = (text.match(/^LAND-0\d\b/i) || ['LAND'])[0].toUpperCase();
    else if (/^STACK-SOLVE\b/i.test(text)) code = 'STACK-SOLVE';
    else if (/^STRATEGY-CHAIN\b/i.test(text)) code = 'STRATEGY-CHAIN';
    else if (/terrace/i.test(text)) code = 'TERRACE';
  } else {
    for (const [re, c] of CODE_PATTERNS) {
      if (c && re.test(text)) {
        code = c;
        break;
      }
    }
    if (code === 'OTHER') {
      const m = /^([A-Z][A-Z0-9-]{2,})(?:\s|:)/.exec(text);
      if (m) code = m[1];
    }
  }
  return { tier, code };
}

const ROOM_ID_RE = /\b([a-z][a-z0-9_]*_F\d+)\b/;
const QUOTED_RE = /'([^']+)'/;

export function roomOf(message: string): { roomId: string | null; floorIndex: number | null } {
  const text = String(message ?? '');
  const m = ROOM_ID_RE.exec(text);
  if (m) {
    const fm = /_F(\d+)$/.exec(m[1]);
    return { roomId: m[1], floorIndex: fm ? Number(fm[1]) : null };
  }
  const q = QUOTED_RE.exec(text);
  return { roomId: q ? q[1] : null, floorIndex: null };
}

/* ==================================================================== */
/* Shared-boilerplate extraction                                         */
/* ==================================================================== */

function normalizeWs(text: string): string {
  return String(text ?? '').replace(/\s+/g, ' ').trim();
}

/** Longest common suffix of two strings, on word boundaries. */
function commonSuffix(a: string, b: string): string {
  const max = Math.min(a.length, b.length);
  let i = 0;
  while (i < max && a[a.length - 1 - i] === b[b.length - 1 - i]) i += 1;
  let suffix = a.slice(a.length - i);
  // Do not split a word: trim back to the first space.
  const space = suffix.indexOf(' ');
  if (space > 0) suffix = suffix.slice(space + 1);
  return suffix;
}

/**
 * The relaxation policy used to be repeated at the end of every rationale
 * (~200 chars per row). Extract the shared tail ONCE and strip it from rows.
 */
export function extractSharedPolicy(messages: readonly string[]): {
  policy: string;
  stripped: (text: string) => string;
} {
  const texts = messages.map(normalizeWs).filter((t) => t.length > 0);
  const counts = new Map<string, number>();
  for (const text of texts) {
    const sentences = text.split(/(?<=\.)\s+/);
    if (sentences.length < 2) continue;
    const tail = sentences.slice(1).join(' ');
    if (tail.length < 60) continue;
    counts.set(tail, (counts.get(tail) ?? 0) + 1);
  }
  // A suffix shared by >= 2 messages is boilerplate. Prefer the most common,
  // then the longest (more of the row explained once).
  let best: string | null = null;
  let bestCount = 1;
  for (const [tail, n] of counts) {
    if (n >= 2 && (n > bestCount || (n === bestCount && (!best || tail.length > best.length)))) {
      best = tail;
      bestCount = n;
    }
  }
  // Cross-check with a true common suffix across the repeated group, which
  // catches tails that differ in their middle but share the final sentence.
  const anchor = best;
  const repeated = anchor ? texts.filter((t) => t.endsWith(anchor)) : [];
  if (repeated.length >= 2) {
    const suffix = repeated.reduce((acc, t) => commonSuffix(acc, t));
    if (suffix.length >= 60) best = suffix;
  }
  if (!best) {
    return {
      policy: '',
      stripped: (text: string) => normalizeWs(text),
    };
  }
  // Rows differ in their closing punctuation (some wrap the tail in a
  // parenthesis), so the strip key ignores trailing brackets and full stops.
  const key = best.replace(/[\s)\].,;]+$/, '');
  const trimTail = (text: string) => text.replace(/[\s)\].,;]+$/, '');
  return {
    policy: tidyPolicy(key),
    stripped: (text: string) => {
      const t = normalizeWs(text);
      const trimmed = trimTail(t);
      if (!key || !trimmed.endsWith(key)) return t;
      return cleanDanglingClause(t.slice(0, trimmed.length - key.length));
    },
  };
}

/**
 * The shared suffix can begin mid-sentence ("on this room and reported by the
 * ROOM-MIN warning; ..."): a policy note has to read as a statement, so keep
 * its final clause and capitalise it.
 */
function tidyPolicy(raw: string): string {
  let text = String(raw ?? '').trim();
  if (/^[a-z(]/.test(text)) {
    const clauses = text.split(/(?<=[.;])\s+/);
    text = clauses[clauses.length - 1] ?? text;
  }
  text = text.replace(/\)\s*$/, '').trim();
  text = text.replace(/^[a-z]/, (c) => c.toUpperCase());
  if (!/[.!?]$/.test(text)) text += '.';
  return text;
}

/**
 * Removing the shared tail can leave the opening words of the removed clause
 * behind ("... catalogue minimum. Listed as a relaxation"). They are engine
 * boilerplate, not a room-specific reason, so they are dropped with the tail.
 */
function cleanDanglingClause(head: string): string {
  let text = head.replace(/[\s;,.]+$/, '');
  text = text.replace(
    /[\s.,;:(]*(?:listed|disclosed|reported|accepted)(?:\s+(?:as|on)\s+(?:a|an|this)\s+[\w-]+)?[\s.,;:()]*$/i,
    '',
  );
  return text.replace(/[\s;,.]+$/, '').trim();
}

const FALLBACK_POLICY =
  'Bounded relaxations are exceptions the solver applies only when the plate cannot satisfy a catalogue minimum. Each is listed on the certificate, is counted here, and still fails the affected layer — it is never a claim of compliance.';

/* ==================================================================== */
/* Relaxations                                                           */
/* ==================================================================== */

export interface RelaxationInput {
  room: string;
  rule_id: string;
  rationale: string;
  measure?: string | null;
  factor?: number | string | null;
}

/** Extract every room-level relaxation exactly the way the card counts them. */
export function collectRelaxations(plan: FloorPlanResponse | null | undefined): RelaxationInput[] {
  const out: RelaxationInput[] = [];
  if (!plan) return out;
  const push = (room: any) => {
    if (!Array.isArray(room?.relaxations)) return;
    for (const rx of room.relaxations) {
      if (!rx) continue;
      out.push({
        room: String(room.room_id ?? room.room_name ?? 'room'),
        rule_id: String(rx.rule_id ?? 'RELAXATION'),
        rationale: String(rx.rationale ?? ''),
        measure: rx.measure ?? null,
        factor: rx.factor ?? rx.relaxation_factor ?? null,
      });
    }
  };
  const ms: any = (plan as any).multi_storey;
  if (ms?.floors) {
    for (const fl of ms.floors) {
      for (const r of fl.rooms ?? []) push(r);
    }
  } else if ((plan as any).placements) {
    for (const r of (plan as any).placements) push(r);
  }
  return out;
}

function measureOf(reason: string): string | null {
  const m = /^(gross area|gross short side|clear width \(wall-deducted\)|clear width|aspect(?: ratio)?)\b/i.exec(reason);
  return m ? m[1].toLowerCase() : null;
}

function factorOf(reason: string): number | null {
  const m = /at ([0-9]+\.[0-9]+)x\b/i.exec(reason) || /\b([0-9]+\.[0-9]+)x\b/i.exec(reason);
  return m ? Number(m[1]) : null;
}

/** A short, distinct chip label — never the repeated policy sentence. */
export function shortReason(reason: string): string {
  const text = normalizeWs(reason);
  const measure = measureOf(text);
  const short = /short by ([0-9.]+)/i.exec(text);
  if (short) return `${measure ?? 'declared'} short by ${short[1]}`;
  const accepted = /accepted at ([0-9.]+)x/i.exec(text);
  if (accepted) return `${measure ?? 'relaxation'} accepted at ${accepted[1]}x`;
  const band = /aspect ([0-9:.]+)[^;]*?([0-9]:[0-9.]+)/i.exec(text);
  if (band) return `aspect ${band[1]} vs ${band[2]}`;
  if (measure) return measure;
  const first = text.split(/[;.]/)[0].trim();
  return first.length > 46 ? `${first.slice(0, 43).trimEnd()}…` : first || 'declared relaxation';
}

function floorOfRoom(roomId: string): number | null {
  const m = /_F(\d+)$/.exec(roomId);
  return m ? Number(m[1]) : null;
}

/* ==================================================================== */
/* The report                                                           */
/* ==================================================================== */

export function buildWarningReport(
  warnings: readonly (string | null | undefined)[] | null | undefined,
  relaxations: readonly RelaxationInput[] | null | undefined = [],
  truthInput: TruthLabelInput = {},
): WarningReport {
  const rawMessages = (warnings ?? []).map((w) => String(w ?? '').trim()).filter(Boolean);
  const relInputs = (relaxations ?? []).filter((r) => r && r.room);

  const shared = extractSharedPolicy([
    ...rawMessages,
    ...relInputs.map((r) => r.rationale),
  ]);

  // The certificate's grouping overrides the message-text heuristic: a listed
  // ROOM-MIN row is a deviation (T2), the rows a FAIL stamp rests on are
  // breaches (T1), and neither is inferred from a warning total.
  const truth = truthLabels(rawMessages, relInputs, truthInput);
  const tierOverride = new Map<string, WarningTier>();
  for (const row of truth.unresolvedBreaches) tierOverride.set(normalizeWs(row), 'T1');
  for (const d of truth.listedDeviations) {
    if (d.page1Row) tierOverride.set(normalizeWs(d.page1Row), 'T2');
  }

  const byKey = new Map<string, WarningEntry>();
  const fullList: RawWarning[] = [];
  rawMessages.forEach((raw, index) => {
    const key = normalizeWs(raw);
    const classified = classifyWarning(raw);
    const tier = tierOverride.get(key) ?? classified.tier;
    const code = classified.code;
    const { roomId, floorIndex } = roomOf(raw);
    fullList.push({ index, raw, tier, code });
    const existing = byKey.get(key);
    if (existing) {
      existing.occurrences += 1;
      existing.indices.push(index);
      return;
    }
    byKey.set(key, {
      key,
      raw,
      display: shared.stripped(raw),
      tier,
      code,
      roomId,
      floorIndex,
      occurrences: 1,
      indices: [index],
    });
  });

  const entries = Array.from(byKey.values());
  const bucket = (tier: WarningTier) => {
    const rows = entries.filter((e) => e.tier === tier);
    return {
      rows,
      count: {
        messages: rows.reduce((n, e) => n + e.occurrences, 0),
        entries: rows.length,
      },
    };
  };
  const t1 = bucket('T1');
  const t2 = bucket('T2');
  const t3 = bucket('T3');
  const t4 = bucket('T4');

  const items: RelaxationItem[] = relInputs.map((r) => {
    const reason = shared.stripped(r.rationale);
    return {
      roomId: r.room,
      floorIndex: floorOfRoom(r.room),
      ruleId: r.rule_id,
      rationale: normalizeWs(r.rationale),
      reason,
      chip: shortReason(reason),
      measure: r.measure ?? measureOf(reason),
      factor: r.factor != null && r.factor !== '' ? Number(r.factor) : factorOf(reason),
    };
  });

  const groupMap = new Map<string, RelaxationGroup>();
  for (const item of items) {
    let group = groupMap.get(item.roomId);
    if (!group) {
      group = { roomId: item.roomId, floorIndex: item.floorIndex, items: [], rules: [] };
      groupMap.set(item.roomId, group);
    }
    group.items.push(item);
    if (!group.rules.includes(item.ruleId)) group.rules.push(item.ruleId);
  }
  const groups = Array.from(groupMap.values());

  return {
    totalMessages: rawMessages.length,
    totalDistinct: entries.length,
    warningMessages: t1.count.messages + t3.count.messages,
    tiers: { T1: t1.count, T2: t2.count, T3: t3.count, T4: t4.count },
    failures: t1.rows,
    deviations: t2.rows,
    advisories: t3.rows,
    operations: t4.rows,
    entries,
    fullList,
    truth,
    relaxations: {
      items,
      groups,
      total: items.length,
      rooms: groups.length,
      policy: shared.policy || FALLBACK_POLICY,
      policyFromEngine: Boolean(shared.policy),
    },
  };
}

/**
 * The ONE summary a surface may print. Every number is read from the report,
 * so a summary can never disagree with the list it summarises.
 */
export function warningSummary(report: WarningReport): {
  totalLine: string;
  /** The certificate-owned counts, stated separately. */
  truthLine: string;
  certificateFailures: string;
  failures: string;
  relaxations: string;
  advisories: string;
  operations: string;
} {
  const n = (v: number, one: string, many: string) => `${v} ${v === 1 ? one : many}`;
  return {
    totalLine: `${n(report.totalMessages, 'engine message', 'engine messages')} · ${n(
      report.truth.counts.certificateFailures,
      'certificate failure',
      'certificate failures',
    )} · ${n(report.truth.counts.listedDeviations, 'listed deviation', 'listed deviations')} · ${n(
      report.truth.counts.unresolvedBreaches,
      'unresolved breach',
      'unresolved breaches',
    )} · ${n(report.tiers.T3.messages, 'advisory', 'advisories')} · ${n(
      report.tiers.T4.messages,
      'engine operation',
      'engine operations',
    )} excluded from warnings`,
    truthLine: report.truth.summary,
    certificateFailures: n(
      report.truth.counts.certificateFailures,
      'certificate failure',
      'certificate failures',
    ),
    failures: n(report.truth.counts.unresolvedBreaches, 'unresolved breach', 'unresolved breaches'),
    relaxations: `${n(report.relaxations.total, 'relaxation', 'relaxations')} accepted · ${n(
      report.relaxations.rooms,
      'room',
      'rooms',
    )}`,
    advisories: n(report.tiers.T3.messages, 'advisory', 'advisories'),
    operations: n(report.tiers.T4.messages, 'engine operation', 'engine operations'),
  };
}
