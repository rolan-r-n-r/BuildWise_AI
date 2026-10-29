/**
 * Browser-only harness for scripts/e2e_plan_advisor.cjs.
 *
 * Loaded through the Vite dev server (`import('/scripts/harness/advisorMount.tsx')`)
 * so the component runs with its real imports, effects, API calls and CSS. It is
 * never imported by the app and is not part of the production bundle.
 */
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PlanAdvisorPanel } from '../../src/components/report/PlanAdvisorPanel';
import { buildWarningReport } from '../../src/services/warningReport';
import type { AdvisoryResponse, RemediationOption } from '../../src/services/types';

declare global {
  interface Window {
    __advisorRoot?: Root;
  }
}

interface HarnessOptions {
  mode: 'off' | 'on';
}

export async function mountAdvisorHarness({ mode }: HarnessOptions): Promise<void> {
  const fixture = await (await fetch('/src/test-fixtures/plan_noncertified_55.json')).json();
  const remedy = await (await fetch('/src/test-fixtures/remediation_noncertified_55.json')).json();
  const report = buildWarningReport(fixture.warnings, fixture.relaxations, {
    certificateFailures: fixture.certificate?.failures ?? [],
  });
  const plan = {
    generation_id: fixture.generation_id,
    warnings: fixture.warnings,
    plan_verdict: fixture.plan_verdict,
    placements: [],
    multi_storey: {
      total_storeys: fixture.request.floors,
      floors: [
        {
          floor_index: 0,
          rooms: fixture.room_ids.map((room_id: string) => ({ room_id })),
        },
      ],
    },
  };

  let host = document.getElementById('advisor-harness');
  if (!host) {
    host = document.createElement('div');
    host.id = 'advisor-harness';
    document.body.innerHTML = '';
    document.body.appendChild(host);
  }
  host.style.cssText = 'width:100%;max-width:1100px;margin:0 auto;padding:12px;box-sizing:border-box';

  const offline: AdvisoryResponse = {
    narrative: null,
    option_notes: {},
    meta: {
      provider_requested: 'groq',
      provider_used: 'deterministic_only',
      narrative_class: 'advisory_non_certified',
      fallback_reason: 'Advisor disabled for the offline capture',
      redactions: [],
      cached: false,
    },
  };

  window.__advisorRoot?.unmount();
  window.__advisorRoot = createRoot(host);
  window.__advisorRoot.render(
    React.createElement(PlanAdvisorPanel, {
      plan: plan as any,
      report,
      request: fixture.request,
      planVerdict: fixture.plan_verdict,
      onApply: () => {},
      testOptions: remedy.options as RemediationOption[],
      ...(mode === 'off' ? { testAdvisory: offline } : {}),
    }),
  );
}
