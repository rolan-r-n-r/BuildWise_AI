/**
 * planAdvisor.ts — the deterministic half of the advisor.
 * ======================================================
 * The summary of a failed plan must exist with no network and no model: grouped
 * counts from the warning report plus the top blocking reasons, in plain
 * language. The LLM may later word a paragraph beside it; it cannot change a
 * number, an option, or the verdict, and the deterministic block never waits for
 * it.
 */
import type {
  AdvisoryResponse,
  FloorPlanRequest,
  FloorPlanResponse,
  RemediationOption,
  RemediationResponse,
} from './types';
import { warningSummary, type WarningReport } from './warningReport';

/** Stable plan identity for caching: request + messages + verdict. */
export function hashPlan(
  plan: FloorPlanResponse | null | undefined,
  request?: Partial<FloorPlanRequest> | null,
): string {
  if (!plan) return 'no-plan';
  const relaxations = collectRelaxationKeys(plan);
  const blob = JSON.stringify({
    id: plan.generation_id ?? '',
    verdict: plan.plan_verdict ?? '',
    warnings: plan.warnings ?? [],
    relaxations,
    request: request ?? null,
  });
  // Two FNV-1a passes (different offset basis) -> 16 hex chars.
  const fnv = (seed: number) => {
    let h = seed;
    for (let i = 0; i < blob.length; i += 1) {
      h ^= blob.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h.toString(16).padStart(8, '0');
  };
  return `${fnv(0x811c9dc5)}${fnv(0x01000193)}`;
}

function collectRelaxationKeys(plan: FloorPlanResponse): string[] {
  const rooms: any[] = [];
  if (plan.multi_storey?.floors) {
    for (const floor of plan.multi_storey.floors) rooms.push(...(floor.rooms ?? []));
  } else {
    rooms.push(...(plan.placements ?? []));
  }
  return rooms.flatMap((room) =>
    (room.relaxations ?? []).map((rx: any) => `${room.room_id}:${rx.rule_id}`),
  );
}

/** Plain-language name for an engine code. Never carries a number. */
export function plainLanguage(code: string): string {
  switch (code) {
    case 'PROP-HARD':
    case 'PROP-PLATE-CAP':
    case 'PROPORTION-FAIL':
      return 'a room cannot meet its minimum proportion on this plate';
    case 'ROOM-MIN':
      return 'rooms are below their catalogue minimum';
    case 'ROOM-MAX':
      return 'a room is larger than its catalogue maximum';
    case 'PROGRAMME-SQUEEZE':
    case 'PROGRAMME-DEFICIT':
      return 'the requested programme does not fit the plate';
    case 'GATE-FAIL':
      return 'the validation gate failed a layer';
    case 'PLATE-SHORT':
      return 'the plate is smaller than the programme needs';
    case 'ROOM-OVERLAP':
      return 'two rooms overlap';
    case 'SELECTION-FALLBACK':
      return 'the requested scheme was replaced by a legal fallback';
    case 'PROP-ASPECT':
    case 'PROP-IDEAL':
      return 'a room sits outside its ideal proportion band';
    case 'PLATE-GROWTH':
      return 'the plate had to grow beyond the programme';
    case 'RULE-FP':
      return 'a rule-based placement constraint was relaxed';
    default:
      return code.toLowerCase().replace(/_/g, ' ');
  }
}

const SEVERITY_ORDER: Record<string, number> = {
  'PROP-HARD': 0,
  'PROP-PLATE-CAP': 1,
  'PROPORTION-FAIL': 2,
  'GATE-FAIL': 3,
  'PROGRAMME-SQUEEZE': 4,
  'PROGRAMME-DEFICIT': 5,
  'PLATE-SHORT': 6,
  'ROOM-OVERLAP': 7,
  'ROOM-MIN': 8,
  'ROOM-MAX': 9,
  'SELECTION-FALLBACK': 10,
};

/** The top three blocking reasons, deterministically ordered by severity. */
export function blockingReasons(report: WarningReport, limit = 3): string[] {
  const seen = new Set<string>();
  const ranked = [...report.failures]
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => {
      const sa = SEVERITY_ORDER[a.entry.code] ?? 99;
      const sb = SEVERITY_ORDER[b.entry.code] ?? 99;
      return sa === sb ? a.index - b.index : sa - sb;
    })
    // The same room can fail the same rule twice (two raw lines). List that
    // fact once and keep ranking until three DISTINCT room/rule pairs exist,
    // so the list keys are unique without understating the count in the header.
    .filter(({ entry }) => {
      const key = `${entry.roomId ?? ''}|${entry.code}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, limit);
  return ranked.map(({ entry }) => {
    const room = entry.roomId ? `${entry.roomId} — ` : '';
    return `${room}${plainLanguage(entry.code)} (${entry.code})`;
  });
}

export interface DeterministicSummary {
  verdictLine: string;
  countsLine: string;
  reasons: string[];
  relaxationsLine: string;
}

export function deterministicSummary(
  report: WarningReport,
  verdict: string | null | undefined,
): DeterministicSummary {
  const counts = warningSummary(report);
  const verdictLine =
    verdict === 'NOT-CERTIFIED-FAIL-STAMP'
      ? 'The certificate is withheld: this plan is drawn and exported with a FAIL stamp.'
      : verdict === 'ADVISORY'
      ? 'The plan is certified, with advisories listed below.'
      : 'The plan is certified.';
  return {
    verdictLine,
    // The certificate-owned counts (failures / listed deviations / breaches),
    // stated separately — never one merged warning total.
    countsLine: counts.truthLine,
    reasons: blockingReasons(report),
    relaxationsLine: counts.relaxations,
  };
}

export function effectLine(option: RemediationOption): string {
  const effect = option.effect;
  if (!effect) return 'Effect not measured — engine unavailable';
  // The card's failure count is the certificate's own rule count — the same
  // unit the CERTIFICATE FAILURES group prints, so the two never disagree.
  const failures = `${effect.failure_count} certificate rule${effect.failure_count === 1 ? '' : 's'} failed`;
  const messages = `${effect.warning_count} engine message${effect.warning_count === 1 ? '' : 's'}`;
  const plate = effect.plate_area_m2 != null ? ` · plate ${effect.plate_area_m2.toFixed(1)} m²` : '';
  const verdict =
    effect.verdict === 'NOT-CERTIFIED-FAIL-STAMP'
      ? ' · still not certified'
      : ` · ${effect.verdict.toLowerCase()}`;
  return `${failures} · ${messages}${plate}${verdict}`;
}

/* ------------------------------------------------------------------ */
/* Cache                                                              */
/* ------------------------------------------------------------------ */

const ADVISOR_CACHE_PREFIX = 'bw.advisor.v1.';
const REMEDIATION_CACHE_PREFIX = 'bw.remediation.v1.';
const CACHE_TTL_MS = 30 * 60 * 1000;

function readCache<T>(key: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { at: number; value: T };
    if (!parsed || typeof parsed.at !== 'number') return null;
    if (Date.now() - parsed.at > CACHE_TTL_MS) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    return parsed.value;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, value: T): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), value }));
  } catch {
    /* storage unavailable: the request simply runs again */
  }
}

export function readAdvisorCache(planHash: string): AdvisoryResponse | null {
  return readCache<AdvisoryResponse>(`${ADVISOR_CACHE_PREFIX}${planHash}`);
}

export function writeAdvisorCache(planHash: string, value: AdvisoryResponse): void {
  writeCache(`${ADVISOR_CACHE_PREFIX}${planHash}`, value);
}

export function readRemediationCache(planHash: string): RemediationResponse | null {
  return readCache<RemediationResponse>(`${REMEDIATION_CACHE_PREFIX}${planHash}`);
}

export function writeRemediationCache(planHash: string, value: RemediationResponse): void {
  writeCache(`${REMEDIATION_CACHE_PREFIX}${planHash}`, value);
}

export function advisorCacheKey(planHash: string): string {
  return `${ADVISOR_CACHE_PREFIX}${planHash}`;
}

/** The payload the advisor endpoint receives: facts only. */
export function buildAdvisoryRequest(
  planHash: string,
  planVerdict: string,
  report: WarningReport,
  options: RemediationOption[],
) {
  const counts = warningSummary(report);
  const reasons = blockingReasons(report);
  return {
    plan_hash: planHash,
    plan_verdict: planVerdict,
    summary_line: counts.truthLine,
    blocking_reasons: reasons,
    warning_counts: {
      total: report.totalMessages,
      certificate_failures: report.truth.counts.certificateFailures,
      unresolved_breaches: report.tiers.T1.messages,
      listed_deviations: report.truth.counts.listedDeviations,
      advisories: report.tiers.T3.messages,
      operations: report.tiers.T4.messages,
      relaxations: report.relaxations.total,
    },
    options: options.map((option) => ({
      id: option.id,
      title: option.title,
      effect_line: effectLine(option),
    })),
  };
}
