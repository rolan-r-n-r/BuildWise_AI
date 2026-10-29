/**
 * Browser-only harness for scripts/e2e_warning_surface.cjs.
 *
 * Mounts the REAL warning surface and advisor panel over the canonical
 * 55-warning fixture, then applies "Add a storey" through the real engine and
 * renders the regenerated certificate. Loaded by the Vite dev server only; it
 * is never imported by the app.
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
    __warningSurfaceRoot?: Root;
  }
}

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
  const [fixture, setFixture] = React.useState<any>(null);
  const [plan, setPlan] = React.useState<any>(null);
  const [phase, setPhase] = React.useState<'baseline' | 'applied'>('baseline');
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    (async () => {
      const data = await (await fetch('/src/test-fixtures/plan_noncertified_55.json')).json();
      setFixture(data);
      setPlan({
        generation_id: data.generation_id,
        warnings: data.warnings,
        plan_verdict: data.plan_verdict,
        placements: [],
        multi_storey: {
          total_storeys: data.request.floors,
          floors: [
            {
              floor_index: 0,
              rooms: data.room_ids.map((room_id: string) => ({ room_id })),
            },
          ],
        },
        mathematical_certificate: data.certificate,
      });
    })();
  }, []);

  if (!fixture || !plan) return <div data-testid="proof-loading">loading fixture</div>;

  const relaxations = phase === 'baseline' ? fixture.relaxations : collectRelaxations(plan);
  const report = buildWarningReport(
    plan.warnings ?? [],
    relaxations,
    { certificateFailures: plan.mathematical_certificate?.failures ?? [] },
  );
  const cert = plan.mathematical_certificate ?? {};
  const failures = (cert.failures ?? []).length;

  const onApply = async (option: RemediationOption) => {
    if (!option.patch) return;
    setError(null);
    try {
      const req = { ...(fixture.request as FloorPlanRequest), ...option.patch } as FloorPlanRequest;
      const response = await generateFloorPlan(req);
      setPlan(response as FloorPlanResponse);
      setPhase('applied');
    } catch (err: any) {
      setError(err?.message || 'apply failed');
    }
  };

  return (
    <div
      data-testid="warning-surface-proof"
      data-phase={phase}
      style={{ width: '100%', maxWidth: 1100, margin: '0 auto', padding: 12, boxSizing: 'border-box' }}
    >
      {error && (
        <p data-testid="proof-error" style={{ color: 'crimson', fontSize: 12 }}>
          {error}
        </p>
      )}
      <div
        data-testid="proof-certificate"
        data-verdict={plan.plan_verdict ?? ''}
        data-failures={failures}
        data-warnings={(plan.warnings ?? []).length}
        data-generation={plan.generation_id ?? ''}
        data-phase={phase}
        style={{ fontSize: 11, opacity: 0.001, height: 1, overflow: 'hidden' }}
      >
        {plan.plan_verdict} · {failures} failures · {(plan.warnings ?? []).length} messages
      </div>
      <WarningReportView
        warnings={plan.warnings ?? []}
        relaxations={relaxations}
        planVerdict={plan.plan_verdict}
        certificateFailures={plan.mathematical_certificate?.failures ?? []}
        prebuiltReport={report}
      />
      <PlanAdvisorPanel
        plan={plan}
        report={report}
        request={fixture.request}
        planVerdict={plan.plan_verdict ?? ''}
        onApply={onApply}
      />
    </div>
  );
}

export async function mountWarningSurface(): Promise<void> {
  let host = document.getElementById('warning-surface-harness');
  if (!host) {
    host = document.createElement('div');
    host.id = 'warning-surface-harness';
    document.body.innerHTML = '';
    document.body.style.background = 'var(--surface, #f7f7f5)';
    document.body.appendChild(host);
  }
  window.__warningSurfaceRoot?.unmount();
  window.__warningSurfaceRoot = createRoot(host);
  window.__warningSurfaceRoot.render(React.createElement(Proof));
}
