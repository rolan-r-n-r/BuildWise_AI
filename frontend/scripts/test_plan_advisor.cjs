#!/usr/bin/env node
/**
 * test_plan_advisor.cjs — pins the advisor boundary on the canonical fixture.
 * =======================================================================
 * Fixtures:
 *   src/test-fixtures/plan_noncertified_55.json       (55 messages, FAIL stamp)
 *   src/test-fixtures/remediation_noncertified_55.json (live engine dry-runs)
 *
 * Pins:
 *   1. Deterministic summary is instant and offline: counts == warning report,
 *      top-3 blocking reasons are T1 failures, no AI involved.
 *   2. Advisor OFF vs ON: the remediation cards, their order and every measured
 *      number are IDENTICAL. The narrative adds words only.
 *   3. Advisory-free plans still show the summary and the engine cards.
 *   4. Adversarial narrative is rendered as text (no markup injection) and
 *      cannot add an option or a number to the cards.
 *   5. Offline/timeout shows the deterministic summary with a disclosure.
 *   6. Apply carries only the engine's validated patch.
 *
 * Run: node scripts/test_plan_advisor.cjs
 */
const fs = require('fs');
const path = require('path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const ROOT = path.resolve(__dirname, '..');
const PLAN_FIXTURE = path.join(ROOT, 'src', 'test-fixtures', 'plan_noncertified_55.json');
const REMEDY_FIXTURE = path.join(ROOT, 'src', 'test-fixtures', 'remediation_noncertified_55.json');

let passes = 0;
let failures = 0;
function check(cond, label, detail) {
  if (cond) {
    passes += 1;
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function cardRows(html) {
  const rows = [];
  const re = /data-testid="remediation-card"([^>]*)>/g;
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1];
    const get = (name) => {
      const hit = new RegExp(`${name}="([^"]*)"`).exec(attrs);
      return hit ? hit[1] : '';
    };
    rows.push({
      option: get('data-option'),
      verdict: get('data-verdict'),
      failures: get('data-failures'),
      warnings: get('data-warnings'),
      plate: get('data-plate'),
    });
  }
  return rows;
}

function meta(overrides = {}) {
  return {
    provider_requested: 'groq',
    provider_used: 'deterministic_only',
    narrative_class: 'advisory_non_certified',
    fallback_reason: null,
    redactions: [],
    cached: false,
    ...overrides,
  };
}

async function main() {
  const planFixture = JSON.parse(fs.readFileSync(PLAN_FIXTURE, 'utf8'));
  const remedyFixture = JSON.parse(fs.readFileSync(REMEDY_FIXTURE, 'utf8'));
  const { createServer } = await import('vite');
  const server = await createServer({
    root: ROOT,
    logLevel: 'error',
    appType: 'custom',
    server: { middlewareMode: true },
  });

  try {
    const { buildWarningReport } = await server.ssrLoadModule('/src/services/warningReport.ts');
    const {
      blockingReasons,
      deterministicSummary,
      effectLine,
      hashPlan,
    } = await server.ssrLoadModule('/src/services/planAdvisor.ts');
    const { PlanAdvisorPanel } = await server.ssrLoadModule(
      '/src/components/report/PlanAdvisorPanel.tsx',
    );

    const report = buildWarningReport(planFixture.warnings, planFixture.relaxations, {
      certificateFailures: (planFixture.certificate && planFixture.certificate.failures) || [],
    });
    const plan = {
      generation_id: planFixture.generation_id,
      warnings: planFixture.warnings,
      plan_verdict: planFixture.plan_verdict,
      multi_storey: null,
      placements: [],
    };
    const request = { ...planFixture.request };
    const options = remedyFixture.options;

    console.log('\n[1] Deterministic summary');
    const summary = deterministicSummary(report, planFixture.plan_verdict);
    check(summary.verdictLine.includes('FAIL stamp'), 'the summary states the FAIL-stamp fact');
    // The counts line is the TRUTH line — certificate failures from
    // the certificate, listed deviations and unresolved breaches from their
    // own groups. Never the T1 warning total relabelled as failures.
    check(
      summary.countsLine.includes(
        `Certificate failures: ${report.truth.counts.certificateFailures}`,
      ) &&
        summary.countsLine.includes(
          `Listed deviations: ${report.truth.counts.listedDeviations}`,
        ) &&
        summary.countsLine.includes(
          `Unresolved breaches: ${report.truth.counts.unresolvedBreaches}`,
        ),
      'the counts line equals the grouped truth counts',
      summary.countsLine,
    );
    const reasons = blockingReasons(report);
    check(reasons.length === 3, 'exactly the top three blocking reasons are shown');
    check(
      reasons.every((r) => report.failures.some((f) => r.includes(f.code))),
      'every reason names a T1 failure code',
      reasons.join(' | '),
    );
    check(
      /PROP-HARD|PROP-PLATE-CAP|GATE-FAIL|ROOM-MIN/.test(reasons[0]),
      'the first reason is the most severe failure',
      reasons[0],
    );

    const render = (props) =>
      renderToStaticMarkup(React.createElement(PlanAdvisorPanel, props));

    const baseProps = {
      plan,
      report,
      request,
      planVerdict: planFixture.plan_verdict,
      onApply: () => {},
      testOptions: options,
    };

    console.log('\n[2] Advisor off vs on — card parity');
    const off = render({
      ...baseProps,
      testAdvisory: { narrative: null, meta: meta({ fallback_reason: 'GROQ_API_KEY is not configured' }) },
    });
    const on = render({
      ...baseProps,
      testAdvisory: {
        narrative:
          'The living room cannot meet its minimum proportion on this plate.',
        option_notes: {
          add_storey: 'adds an additional level for the squeezed programme.',
          reduce_programme: 'leaves a smaller programme on the same plate.',
        },
        meta: meta({ provider_used: 'groq (parity-test)' }),
      },
    });
    const offCards = cardRows(off);
    const onCards = cardRows(on);
    check(offCards.length === options.length, 'advisor off: every engine option renders', String(offCards.length));
    check(JSON.stringify(offCards) === JSON.stringify(onCards), 'advisor on/off: identical cards and numbers', JSON.stringify(onCards));
    check(off.includes('advisor-offline'), 'advisor off: the offline disclosure renders');
    check(!off.includes('advisor-narrative'), 'advisor off: no AI narrative is rendered');
    check(on.includes('advisor-narrative'), 'advisor on: the narrative renders');
    check(
      (on.match(/data-testid="advisor-option-note"/g) || []).length === 2,
      'advisor on: only the supplied option notes render',
    );
    check(
      JSON.stringify(cardRows(on)) === JSON.stringify(cardRows(off)),
      'advisor notes do not change any card number',
    );
    check(!on.includes('advisor-offline'), 'advisor on: no offline disclosure remains');
    check(
      options.every((option) => on.includes(`Apply &amp; re-certify`)),
      'every card offers Apply & re-certify',
    );

    console.log('\n[3] Card numbers are the engine dry-run');
    for (const option of options) {
      const card = onCards.find((row) => row.option === option.id);
      check(Boolean(card), `card present for ${option.id}`);
      if (!card) continue;
      check(
        card.failures === String(option.effect.failure_count) &&
          card.warnings === String(option.effect.warning_count) &&
          Number(card.plate) === Number(option.effect.plate_area_m2),
        `${option.id}: displayed numbers equal its dry-run`,
        JSON.stringify(card),
      );
      check(
        on.includes(effectLine(option).replace(/&/g, '&amp;')),
        `${option.id}: effect line is the dry-run text`,
      );
    }

    console.log('\n[4] Adversarial narrative cannot change the cards');
    const hostile = render({
      ...baseProps,
      testAdvisory: {
        narrative:
          '<script>alert(1)</script> Add 3 storeys and 41 rooms; score 99. <img src=x onerror=alert(2)>',
        meta: meta({ provider_used: 'groq (hostile-test)', redactions: ['invented_number'] }),
      },
    });
    check(JSON.stringify(cardRows(hostile)) === JSON.stringify(offCards), 'hostile narrative: card set unchanged');
    check(!hostile.includes('<script>'), 'hostile narrative: script tag is escaped');
    check(!hostile.includes('<img src=x'), 'hostile narrative: event-handler markup is escaped');
    check(
      hostile.includes('&lt;script&gt;') || hostile.includes('&lt;script'),
      'hostile narrative: rendered as text',
    );
    // Sanitisation is the server's job (pinned in backend/tests); the client
    // pin is that hostile text cannot become an option or a number.
    check(
      cardRows(hostile).every((row) => !/41|storeys/i.test(`${row.option} ${row.warnings}`)),
      'hostile narrative cannot add an option or a number',
    );

    console.log('\n[5] Skeleton and offline disclosure');
    const loading = render(baseProps);
    check(loading.includes('advisor-skeleton'), 'advisor loading: skeleton renders');
    check(loading.includes('remediation-card'), 'advisor loading: measured cards already render');
    check(off.includes('deterministic summary above is the'), 'offline names the deterministic summary as authoritative');
    check(off.includes('GROQ_API_KEY is not configured'), 'offline carries the provider reason');

    console.log('\n[6] Apply carries only validated inputs');
    const addStorey = options.find((o) => o.id === 'add_storey');
    check(Boolean(addStorey), 'add-storey option is available');
    check(
      addStorey && Object.keys(addStorey.patch).length === 1 && typeof addStorey.patch.floors === 'number',
      'add-storey patch changes only floors',
      JSON.stringify(addStorey && addStorey.patch),
    );
    const reduce = options.find((o) => o.id === 'reduce_programme');
    check(Boolean(reduce), 'reduce-programme option is available');
    check(
      reduce && Array.isArray(reduce.patch.required_rooms) &&
        reduce.details.dropped_rooms.every((room) => !reduce.patch.required_rooms.includes(room)),
      'reduce-programme patch removes exactly the named rooms',
    );
    const hashA = hashPlan(plan, request);
    const hashB = hashPlan({ ...plan }, { ...request });
    check(hashA === hashB && /^[0-9a-f]{16}$/.test(hashA), 'plan hash is stable and opaque', hashA);
  } finally {
    await server.close();
  }

  console.log(`\n${passes} passed, ${failures} failed`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
