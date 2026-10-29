/**
 * Browser-only harness for scripts/e2e_certificate_truth.cjs.
 *
 * Solves two 20 x 20 m typology-default plans through the real API and mounts
 * the production warning report (verdict chip + CERTIFICATE FAILURES group +
 * LISTED DEVIATIONS group) beside the real CertificatePanel (definition
 * legend). It is loaded through Vite only; the app never imports it.
 *
 *   t2  T2_FAMILY_APARTMENT 20x20, 1 storey  -> CERTIFIED, 0 cert failures
 *   t1  T1_SINGLE_FAMILY   20x20, 1 storey  -> NOT-CERTIFIED-FAIL-STAMP
 *
 * The point of the proof is not that either case is nice: it is that the two
 * counts are derived from different sources (certificate rows vs listed
 * relaxations) and the definition is printed verbatim on both outcomes.
 */
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CertificatePanel } from '../../src/components/report/CertificatePanel';
import { WarningReportView } from '../../src/components/report/WarningReportView';
import { buildWarningReport } from '../../src/services/warningReport';
import { generateFloorPlan } from '../../src/services/api';
import type { FloorPlanRequest, FloorPlanResponse } from '../../src/services/types';

declare global {
  interface Window {
    __certificateTruthRoot?: Root;
  }
}

export type CertificateTruthCase = 't2' | 't1';

const CASES: Record<
  CertificateTruthCase,
  { typology: string; label: string; seed: string }
> = {
  t2: {
    typology: 'residential_multi',
    label: 'T2 apartment · 20 × 20 m · 1 storey',
    seed: 'stage7-truth-t2',
  },
  t1: {
    typology: 'residential_single',
    label: 'T1 single family · 20 × 20 m · 1 storey',
    // This exact seed yields the T1 20x20 fail-stamp WITH certificate rows
    // (the truth-label grouping must be proven on both zero and non-zero).
    seed: 'stage7-T1_SINGLE_FAMILY-20x20-F1',
  },
};

function collectRelaxations(plan: any): Array<Record<string, any>> {
  const rooms = plan.multi_storey?.floors
    ? plan.multi_storey.floors.flatMap((floor: any) => floor.rooms ?? [])
    : plan.placements ?? [];
  return rooms.flatMap((room: any) =>
    (room.relaxations ?? []).map((rx: any) => ({
      room: room.room_id,
      rule_id: rx.rule_id,
      rationale: rx.rationale ?? rx.reason ?? '',
      measure: rx.measure ?? null,
      factor: rx.factor ?? null,
    })),
  );
}

function Proof({ caseId }: { caseId: CertificateTruthCase }) {
  const spec = CASES[caseId];
  const [plan, setPlan] = React.useState<FloorPlanResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const request: FloorPlanRequest = {
      plot_width_m: 20,
      plot_depth_m: 20,
      building_typology: spec.typology,
      floors: 1,
      ground_coverage_ratio: 0.6,
      vastu_strictness: 'high',
      seed: spec.seed,
      ai_provider: 'mock',
      bypass_cache: true,
    } as FloorPlanRequest;
    generateFloorPlan(request as any)
      .then((response) => setPlan(response as FloorPlanResponse))
      .catch((err) => setError(err?.message || 'solve failed'));
  }, [spec.seed, spec.typology]);

  if (error) {
    return <p data-testid="certificate-truth-error">{error}</p>;
  }
  if (!plan) {
    return <p data-testid="certificate-truth-loading">solving the 20 × 20 m plate…</p>;
  }

  const anyPlan = plan as any;
  const cert = anyPlan.mathematical_certificate ?? {};
  const failures: string[] = (cert.failures ?? []).map((f: any) =>
    typeof f === 'string' ? f : JSON.stringify(f),
  );
  const relaxations = collectRelaxations(plan);
  const report = buildWarningReport(plan.warnings ?? [], relaxations, {
    certificateFailures: failures,
  });
  const verdict = plan.plan_verdict ?? '';

  return (
    <div
      data-testid="certificate-truth-proof"
      data-case={caseId}
      data-phase="ready"
      data-verdict={verdict}
      data-cert-failures={failures.length}
      data-listed={report.truth.counts.listedDeviations}
      data-relaxations={relaxations.length}
      data-warnings={(plan.warnings ?? []).length}
      style={{ width: '100%', maxWidth: 1180, margin: '0 auto', padding: 12, boxSizing: 'border-box' }}
    >
      <h1
        data-testid="certificate-truth-case-label"
        style={{ fontSize: 14, fontWeight: 700, margin: '0 0 8px' }}
      >
        {spec.label}
      </h1>
      <WarningReportView
        warnings={plan.warnings ?? []}
        relaxations={relaxations}
        planVerdict={verdict}
        certificateFailures={failures}
        prebuiltReport={report}
        expandAll
      />
      <div style={{ marginTop: 10 }}>
        <CertificatePanel
          qa={plan.qa}
          planVerdict={verdict}
          relaxationsCount={relaxations.length}
        />
      </div>
    </div>
  );
}

export async function mountCertificateTruth(caseId: CertificateTruthCase = 't2'): Promise<void> {
  let host = document.getElementById('certificate-truth-harness');
  if (!host) {
    host = document.createElement('div');
    host.id = 'certificate-truth-harness';
    document.body.innerHTML = '';
    document.body.style.background = 'var(--surface, #f7f7f5)';
    document.body.appendChild(host);
  }
  window.__certificateTruthRoot?.unmount();
  window.__certificateTruthRoot = createRoot(host);
  window.__certificateTruthRoot.render(React.createElement(Proof, { caseId }));
}
