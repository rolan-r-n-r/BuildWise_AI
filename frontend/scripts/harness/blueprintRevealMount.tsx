/**
 * Browser-only harness for scripts/e2e_blueprint_reveal.cjs.
 *
 * Solves a real plate through the running API and mounts the production
 * BlueprintViewer — no mocked SVG, no hand-drawn fixture. The wrapper carries
 * the server verdict so the browser test can assert the FAIL chip and the
 * reveal coexist on the same payload.
 *
 *   multi  T1 20x20, 2 storeys  -> CERTIFIED on the current engine
 *   fail   T1 20x20, 1 storey   -> NOT-CERTIFIED-FAIL-STAMP
 *
 * It is loaded through Vite only; the app never imports it.
 */
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { DesignProvider } from '../../src/design/primitives';
import { BlueprintViewer } from '../../src/components/BlueprintViewer';
import { generateFloorPlan } from '../../src/services/api';
import type { FloorPlanRequest, FloorPlanResponse } from '../../src/services/types';

declare global {
  interface Window {
    __blueprintRevealRoot?: Root;
  }
}

export type BlueprintRevealCase = 'multi' | 'fail' | 'dense' | 'large';

const CASES: Record<
  BlueprintRevealCase,
  { label: string; floors: number; seed: string; width: number; depth: number; typology?: string }
> = {
  multi: {
    label: 'T1 single family · 20 × 20 m · 2 storeys',
    floors: 2,
    seed: 'qa-blueprint-t1',
    width: 20,
    depth: 20,
  },
  fail: {
    label: 'T1 single family · 20 × 20 m · 1 storey',
    floors: 1,
    seed: 'stage7-T1_SINGLE_FAMILY-20x20-F1',
    width: 20,
    depth: 20,
  },
  dense: {
    label: 'T1 single family · 8 × 40 m · 3 storeys (dense plate)',
    floors: 3,
    seed: 'qa-blueprint-dense',
    width: 8,
    depth: 40,
  },
  large: {
    label: 'T3 large complex · 30 × 40 m · 1 storey (large plate)',
    floors: 1,
    seed: 'qa-perf-large-t3',
    width: 30,
    depth: 40,
    typology: 'T3_LARGE_COMPLEX',
  },
};

function Proof({ caseId }: { caseId: BlueprintRevealCase }) {
  const spec = CASES[caseId];
  const [plan, setPlan] = React.useState<FloorPlanResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const request = {
      plot_width_m: spec.width,
      plot_depth_m: spec.depth,
      floors: spec.floors,
      building_typology: spec.typology || 'residential_single',
      vastu_strictness: 'high',
      seed: spec.seed,
      ai_provider: 'mock',
      bypass_cache: true,
    } as FloorPlanRequest;
    generateFloorPlan(request as any)
      .then((response) => setPlan(response as FloorPlanResponse))
      .catch((err) => setError(err?.message || 'solve failed'));
  }, [spec.floors, spec.seed, spec.width, spec.depth]);

  if (error) {
    return <p data-testid="blueprint-proof-error">{error}</p>;
  }
  if (!plan) {
    return (
      <p data-testid="blueprint-proof-loading" data-case={caseId}>
        solving the {spec.floors}-storey plate…
      </p>
    );
  }

  const anyPlan = plan as any;
  return (
    <div
      data-testid="blueprint-proof"
      data-case={caseId}
      data-phase="ready"
      data-verdict={plan.plan_verdict || ''}
      data-generation={plan.generation_id || ''}
      data-floors={anyPlan.multi_storey?.floors?.length ?? 1}
      style={{ width: '100%', maxWidth: 940, margin: '0 auto', padding: 12, boxSizing: 'border-box' }}
    >
      <div
        data-testid="blueprint-proof-label"
        style={{ fontSize: 13, fontWeight: 700, margin: '0 0 8px' }}
      >
        {spec.label} — server verdict: {plan.plan_verdict || 'not reported'}
      </div>
      <DesignProvider>
        <BlueprintViewer
          svgString={plan.svg_blueprint}
          svgPaperString={plan.svg_blueprint_paper}
          placements={plan.placements}
          plotWidthM={spec.width}
          plotDepthM={spec.depth}
          multiStorey={plan.multi_storey}
          sitePlan={plan.site_plan || plan.multi_storey?.site_plan}
          generationTimestamp={anyPlan.generated_at}
          generationId={plan.generation_id}
          storeys={spec.floors}
          isStale={false}
          requestedTypology={spec.typology || 'residential_single'}
          planVerdict={plan.plan_verdict}
        />
      </DesignProvider>
    </div>
  );
}

export async function mountBlueprintReveal(caseId: BlueprintRevealCase = 'multi'): Promise<void> {
  let host = document.getElementById('blueprint-reveal-harness');
  if (!host) {
    host = document.createElement('div');
    host.id = 'blueprint-reveal-harness';
    document.body.innerHTML = '';
    document.body.style.margin = '0';
    document.body.style.background = 'var(--surface, #f5f5f7)';
    document.body.appendChild(host);
  }
  window.__blueprintRevealRoot?.unmount();
  window.__blueprintRevealRoot = createRoot(host);
  window.__blueprintRevealRoot.render(React.createElement(Proof, { caseId }));
}
