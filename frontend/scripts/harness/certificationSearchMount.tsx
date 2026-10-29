/**
 * Browser-only harness for scripts/e2e_certification_search.cjs.
 *
 * Solves the reported T2 12x18 / 129.6 m² / G+4 case through the real API,
 * mounts the production warning surface and advisor panel, and applies the
 * service-row alternative through the same validated request patch. It is
 * loaded through Vite only; the app never imports it.
 */
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PlanAdvisorPanel } from '../../src/components/report/PlanAdvisorPanel';
import { WarningReportView } from '../../src/components/report/WarningReportView';
import { buildWarningReport } from '../../src/services/warningReport';
import { generateFloorPlan } from '../../src/services/api';
import type { FloorPlanRequest, FloorPlanResponse, RemediationOption } from '../../src/services/types';

declare global {
  interface Window {
    __certificationSearchRoot?: Root;
  }
}

const REQUEST: FloorPlanRequest = {
  plot_width_m: 12,
  plot_depth_m: 18,
  building_typology: 'residential_multi',
  floors: 4,
  ground_coverage_ratio: 0.6,
  vastu_strictness: 'high',
  seed: 'stage4-browser',
  ai_provider: 'mock',
  bypass_cache: true,
} as FloorPlanRequest;

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

function Proof() {
  const [plan, setPlan] = React.useState<FloorPlanResponse | null>(null);
  const [phase, setPhase] = React.useState<'baseline' | 'applied'>('baseline');
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    generateFloorPlan(REQUEST as any)
      .then((response) => setPlan(response as FloorPlanResponse))
      .catch((err) => setError(err?.message || 'solve failed'));
  }, []);

  if (error) return <p data-testid="strategy-proof-error">{error}</p>;
  if (!plan) return <p data-testid="strategy-proof-loading">solving the T2 plate…</p>;

  const relaxations = collectRelaxations(plan);
  const report = buildWarningReport(plan.warnings ?? [], relaxations, {
    certificateFailures: (plan as any).mathematical_certificate?.failures ?? [],
  });
  const cert = (plan as any).mathematical_certificate ?? {};
  const failures = (cert.failures ?? []).length;
  // Geometry-only signature: ids and rectangles, never verdicts or warnings.
  // The browser proof uses it to show that applying S2 drew a different plate.
  const geometry = JSON.stringify(
    (plan.multi_storey?.floors ?? []).flatMap((floor: any) =>
      (floor.rooms ?? []).map((room: any) => [
        room.room_id,
        Math.round(room.x * 100) / 100,
        Math.round(room.y * 100) / 100,
        Math.round(room.width_m * 100) / 100,
        Math.round(room.depth_m * 100) / 100,
      ]),
    ),
  );

  const onApply = async (option: RemediationOption) => {
    if (!option.patch) return;
    setError(null);
    try {
      const response = await generateFloorPlan({ ...(REQUEST as any), ...option.patch });
      setPlan(response as FloorPlanResponse);
      setPhase('applied');
    } catch (err: any) {
      setError(err?.message || 'apply failed');
    }
  };

  return (
    <div
      data-testid="strategy-proof"
      data-phase={phase}
      data-selected={(plan.multi_storey as any)?.strategy_selected ?? ''}
      data-verdict={plan.plan_verdict ?? ''}
      style={{ width: '100%', maxWidth: 1100, margin: '0 auto', padding: 12, boxSizing: 'border-box' }}
    >
      <div
        data-testid="strategy-proof-certificate"
        data-generation={plan.generation_id ?? ''}
        data-verdict={plan.plan_verdict ?? ''}
        data-failures={failures}
        data-warnings={(plan.warnings ?? []).length}
        data-geometry={geometry}
        style={{ fontSize: 11, opacity: 0.001, height: 1, overflow: 'hidden' }}
      >
        {plan.plan_verdict} · {failures} failures · {(plan.warnings ?? []).length} messages
      </div>
      <WarningReportView
        warnings={plan.warnings ?? []}
        relaxations={relaxations}
        planVerdict={plan.plan_verdict}
        certificateFailures={(plan as any).mathematical_certificate?.failures ?? []}
        prebuiltReport={report}
      />
      <PlanAdvisorPanel
        plan={plan}
        report={report}
        request={REQUEST}
        planVerdict={plan.plan_verdict ?? ''}
        onApply={onApply}
      />
    </div>
  );
}

export async function mountCertificationSearch(): Promise<void> {
  let host = document.getElementById('certification-search-harness');
  if (!host) {
    host = document.createElement('div');
    host.id = 'certification-search-harness';
    document.body.innerHTML = '';
    document.body.style.background = 'var(--surface, #f7f7f5)';
    document.body.appendChild(host);
  }
  window.__certificationSearchRoot?.unmount();
  window.__certificationSearchRoot = createRoot(host);
  window.__certificationSearchRoot.render(React.createElement(Proof));
}
