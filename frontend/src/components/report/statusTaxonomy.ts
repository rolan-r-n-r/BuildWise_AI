import type { FactorScore } from '../../services/types';

/**
 * Provenance taxonomy shared by the report UI and the PDF dossier. Every
 * surface derives its badges and legend copy from THIS module — those are the
 * only two consumers, so they can never diverge.
 */
export type ProvenanceStatus = 'VERIFIED' | 'CALCULATED' | 'ASSUMED' | 'UNKNOWN';

/**
 * The certification definition, stated verbatim.
 *
 * Kept byte-identical to `backend/app/services/plan_verdict.py`
 * (`CERTIFIED_DEFINITION`); the parity pin in test_plan_verdict_parity reads
 * both files.  Every surface that shows a verdict shows this sentence too.
 */
export const CERTIFIED_DEFINITION = 'CERTIFIED = statutory/safety layers PASS + zero unlisted breaches + every quality deviation listed and inside its declared cap. NOT-CERTIFIED-FAIL-STAMP = statutory FAIL, unlisted breach, or beyond-cap deviation.';

/** Multiple meanings disambiguated per context — never one word, two meanings. */
export interface LegendRow {
  status: ProvenanceStatus;
  /** Meaning when tagging a measured factor. */
  factorMeaning: string;
  /** Meaning when tagging a code-compliance check result. */
  checkMeaning: string;
  /** Meaning when tagging an on-drawing annotation. */
  annotationMeaning: string;
  style: 'verified' | 'calculated' | 'assumed' | 'unknown';
}

export const STATUS_LEGEND: readonly LegendRow[] = [
  {
    status: 'VERIFIED',
    factorMeaning: 'Measured directly from live external telemetry',
    checkMeaning: 'Statutory check ran against real geometry and passed',
    annotationMeaning: 'Value surveyed or measured at the site',
    style: 'verified',
  },
  {
    status: 'CALCULATED',
    factorMeaning: 'Derived deterministically from verified inputs',
    checkMeaning: 'Checked against code thresholds with known inputs',
    annotationMeaning: 'Value computed by the layout engine',
    style: 'calculated',
  },
  {
    status: 'ASSUMED',
    factorMeaning: 'Synthetic fallback applied — see the degradation notice',
    checkMeaning: 'Checked against relaxed or fallback assumptions',
    annotationMeaning: 'Value suggested by the advisory engine, may not hold',
    style: 'assumed',
  },
  {
    status: 'UNKNOWN',
    factorMeaning: 'Unmeasured — neutral placeholder, never fabricated',
    checkMeaning: 'Could not be evaluated — inspect inputs before relying',
    annotationMeaning: 'Not determinable at generation time',
    style: 'unknown',
  },
] as const;

/**
 * Derives the provenance status for one factor. This is the single categorizer
 * used by the factor badges, the DATA HEALTH strip and the PDF narration.
 */
export function deriveFactorProvenance(factor: FactorScore): ProvenanceStatus {
  if (factor.status === 'unknown' || factor.raw_value === null || factor.raw_value === undefined) {
    return 'UNKNOWN';
  }
  const details = (factor.details ?? '').toLowerCase();
  if (
    details.includes('fallback') ||
    details.includes('synthetic') ||
    details.includes('modelled') ||
    details.includes('modeled') ||
    details.includes('proxy') ||
    details.includes('latitudinal')
  ) {
    return 'ASSUMED';
  }
  return 'VERIFIED';
}

/** Microcopy for the popover fallback note on an ASSUMED factor. */
export function assumedFootnote(details: string): string {
  const lower = (details ?? '').toLowerCase();
  if (lower.includes('proxy')) return 'Modelled proxy — not a measured survey.';
  if (lower.includes('latitudinal')) return 'Synthetic latitude-based climate baseline.';
  return 'Synthetic fallback — disclosed, never fabricated.';
}
