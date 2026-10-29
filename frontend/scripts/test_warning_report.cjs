#!/usr/bin/env node
/**
 * test_warning_report.cjs — pins the warning information architecture.
 * =====================================================================
 * Canonical fixture: src/test-fixtures/plan_noncertified_55.json, captured live
 * from the engine by backend/scripts/capture_warning_fixture.py (the user's
 * original payload was not in the repo). It is a withheld-certificate plan with
 * 55 engine messages, 13 room-level relaxations across 10 rooms and a terrace
 * band on F2.
 *
 * Pins:
 *   1. Fixture shape (55 lines, FAIL stamp, terrace_band_F2 present).
 *   2. Truth-label contract: CERTIFICATE FAILURES = the certificate's own
 *      failure rows (3 here) and nothing else; LISTED DEVIATIONS = the listed,
 *      within-cap rows; UNRESOLVED BREACHES = the rows the FAIL stamp rests on;
 *      T4 engine operations stay out of every warning count.
 *   3. No line is lost: the full list is the payload, verbatim and in order.
 *   4. Summary == grouping parity: every count printed equals its group.
 *   5. Relaxations: one listed-deviation row per disclosure, the 200-char
 *      policy explained once and stripped from every row, chips distinct, and
 *      every structured record reachable behind its room row.
 *   6. The removed duplicate relaxation list stays removed (no second rendering
 *      of 13 rows on the card).
 *
 * Run: node scripts/test_warning_report.cjs
 */
const fs = require('fs');
const path = require('path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const ROOT = path.resolve(__dirname, '..');
const FIXTURE = path.join(ROOT, 'src', 'test-fixtures', 'plan_noncertified_55.json');

let failures = 0;
let passes = 0;
function check(cond, label, detail) {
  if (cond) {
    passes += 1;
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function attr(html, name) {
  const m = new RegExp(`${name}="([^"]*)"`).exec(html);
  return m ? m[1] : null;
}
function countTestId(html, id) {
  return (html.match(new RegExp(`data-testid="${id}"`, 'g')) || []).length;
}

async function main() {
  const fixture = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  const { createServer } = await import('vite');
  const server = await createServer({
    root: ROOT,
    logLevel: 'error',
    appType: 'custom',
    server: { middlewareMode: true },
  });

  try {
    const {
      buildWarningReport,
      warningSummary,
      classifyWarning,
      shortReason,
    } = await server.ssrLoadModule('/src/services/warningReport.ts');
    const { WarningReportView } = await server.ssrLoadModule(
      '/src/components/report/WarningReportView.tsx',
    );

    console.log('\n[1] Canonical fixture');
    check(fixture.warnings.length === 55, 'the fixture carries exactly 55 engine messages', String(fixture.warnings.length));
    check(
      fixture.plan_verdict === 'NOT-CERTIFIED-FAIL-STAMP',
      'the fixture is a FAIL-stamped plan',
      fixture.plan_verdict,
    );
    check(fixture.certificate && fixture.certificate.is_valid === false, 'the certificate is withheld');
    check(fixture.gate && fixture.gate.status === 'FAIL', 'the validation gate is FAIL');
    check(
      fixture.room_ids.includes('terrace_band_F2'),
      'the fixture includes terrace_band_F2',
    );
    check(fixture.relaxations.length > 0, 'the fixture carries room-level relaxations');

    console.log('\n[2] Truth-label contract');
    const report = buildWarningReport(fixture.warnings, fixture.relaxations, {
      certificateFailures: fixture.certificate.failures,
    });
    const t1Codes = new Set(report.failures.map((e) => e.code));
    const t2Codes = new Set(report.deviations.map((e) => e.code));
    const t3Codes = new Set(report.advisories.map((e) => e.code));
    const t4Codes = new Set(report.operations.map((e) => e.code));
    // GROUP A is the certificate's own rows, counted exactly.
    check(
      report.truth.counts.certificateFailures === fixture.certificate.failures.length,
      'CERTIFICATE FAILURES == len(certificate.failures)',
      `${report.truth.counts.certificateFailures} vs ${fixture.certificate.failures.length}`,
    );
    check(
      report.truth.certificateFailures.every((f) => fixture.certificate.failures.includes(f)),
      'every group-A row is a certificate failure row, verbatim',
    );
    check(t1Codes.has('PROP-HARD'), 'PROP-HARD is an unresolved breach (T1)');
    check(t1Codes.has('GATE-FAIL'), 'GATE-FAIL is an unresolved breach (T1)');
    check(
      report.truth.unresolvedBreaches.some((r) => /^ROOM-MIN/.test(r)),
      'an unlisted ROOM-MIN is an unresolved breach',
    );
    check(
      report.truth.listedDeviations.some((d) => d.ruleId === 'ROOM-MIN'),
      'a listed ROOM-MIN is a listed deviation, not a certificate failure',
    );
    check(
      report.truth.listedDeviations.every((d) => !report.truth.unresolvedBreaches.includes(d.page1Row)),
      'no row is listed and a breach at the same time',
    );
    check(t2Codes.has('PROP-IDEAL'), 'PROP-IDEAL is a listed deviation (T2)');
    check(t2Codes.has('PROP-ASPECT'), 'PROP-ASPECT is a listed deviation (T2)');
    check(
      !t1Codes.has('PROP-IDEAL') && !t1Codes.has('PROP-ASPECT'),
      'a listed relaxation never counts as a breach',
    );
    check(
      report.truth.listedDeviations.every((d) => !/no listed relaxation/i.test(d.page1Row ?? '')),
      'a row that says there is no listing is never read as a listing',
    );
    for (const code of ['SWING', 'WET-STACK', 'VENTILATION', 'TERRACE', 'FURNITURE']) {
      check(t4Codes.has(code), `${code} is a T4 engine operation`);
    }
    const stackLine = classifyWarning(
      'STACK-SOLVE: the governing floor F0 was solved once and stacked to F1, F2.',
    );
    check(stackLine.tier === 'T4', 'STACK-SOLVE is a T4 engine operation', stackLine.tier);
    check(stackLine.code === 'STACK-SOLVE', 'STACK-SOLVE keeps its own code', stackLine.code);
    const chainLine = classifyWarning('STRATEGY-CHAIN: S0 fail -> S1 fail; selected S1');
    check(chainLine.tier === 'T4', 'STRATEGY-CHAIN is a T4 engine operation', chainLine.tier);
    check(
      chainLine.code === 'STRATEGY-CHAIN',
      'STRATEGY-CHAIN keeps its own code',
      chainLine.code,
    );
    check(
      report.tiers.T1.messages + report.tiers.T3.messages === report.warningMessages,
      'the warning headline is T1 + T3 only (T2 deviations are their own group)',
    );
    check(
      report.tiers.T1.messages + report.tiers.T2.messages + report.tiers.T3.messages +
        report.tiers.T4.messages === report.totalMessages,
      'every raw line lands in exactly one tier',
    );
    check(
      report.truth.counts.certificateFailures + report.truth.counts.listedDeviations +
        report.truth.counts.unresolvedBreaches > 0,
      'the truth-label groups are populated',
    );
    for (const raw of fixture.warnings) {
      const { tier } = classifyWarning(raw);
      check(
        tier === 'T1' || tier === 'T3' || tier === 'T4',
        `classified ${raw.slice(0, 34)}…`,
        tier,
      );
      if (tier !== 'T4' && /^GATE-FAIL|^PROP-HARD/.test(raw)) {
        check(tier === 'T1', `critical line classified T1: ${raw.slice(0, 28)}…`, tier);
      }
    }

    console.log('\n[3] Full disclosure — no line lost');
    check(
      report.fullList.length === fixture.warnings.length,
      'fullList has one entry per raw message',
      `${report.fullList.length} vs ${fixture.warnings.length}`,
    );
    check(
      report.fullList.every((m, i) => m.raw === fixture.warnings[i]),
      'fullList preserves every raw line verbatim and in order',
    );
    check(
      report.entries.reduce((n, e) => n + e.occurrences, 0) === fixture.warnings.length,
      'grouping neither adds nor drops occurrences',
    );

    console.log('\n[4] Summary == grouping parity (rendered)');
    const html = renderToStaticMarkup(
      React.createElement(WarningReportView, {
        warnings: fixture.warnings,
        relaxations: fixture.relaxations,
        planVerdict: fixture.plan_verdict,
        certificateFailures: fixture.certificate.failures,
      }),
    );
    check(attr(html, 'data-critical') === 'true', 'the surface renders critical');
    check(attr(html, 'data-total-messages') === '55', 'surface reports 55 raw messages', attr(html, 'data-total-messages'));
    check(attr(html, 'data-t1-count') === String(report.tiers.T1.messages), 'T1 data count == report');
    check(attr(html, 'data-t2-count') === String(report.tiers.T2.messages), 'T2 data count == report');
    check(attr(html, 'data-t3-count') === String(report.tiers.T3.messages), 'T3 data count == report');
    check(attr(html, 'data-t4-count') === String(report.tiers.T4.messages), 'T4 data count == report');
    check(
      attr(html, 'data-certificate-failure-count') === String(report.truth.counts.certificateFailures),
      'certificate-failure data count == certificate.failures',
      attr(html, 'data-certificate-failure-count'),
    );
    check(
      attr(html, 'data-listed-deviation-count') === String(report.truth.counts.listedDeviations),
      'listed-deviation data count == the listed rows',
    );
    check(
      attr(html, 'data-unresolved-breach-count') === String(report.truth.counts.unresolvedBreaches),
      'unresolved-breach data count == the breach rows',
    );
    check(
      attr(html, 'data-relaxation-count') === String(report.relaxations.total),
      'relaxation data count == report',
    );
    check(
      attr(html, 'data-relaxation-rooms') === String(report.relaxations.rooms),
      'relaxation room count == report',
    );
    const summary = warningSummary(report);
    check(
      html.includes(summary.truthLine.replace(/&/g, '&amp;')),
      'the visible summary states the certificate counts separately',
    );
    check(
      html.includes(summary.totalLine.replace(/&/g, '&amp;')),
      'the visible detail line is the report detail line',
    );
    const unresolvedList = /data-testid="unresolved-breaches-list" data-count="(\d+)"/.exec(html);
    check(
      unresolvedList && Number(unresolvedList[1]) === report.truth.counts.unresolvedBreaches,
      'the unresolved-breaches list data-count is its own group count',
    );
    check(
      (html.match(/data-testid="unresolved-breach-row"|data-testid="warning-row" data-tier="T1"/g) || []).length ===
        report.tiers.T1.entries,
      'the breach list renders one row per grouped breach',
      `${(html.match(/data-tier="T1"/g) || []).length} vs ${report.tiers.T1.entries}`,
    );
    // GROUP A: the certificate's own rows, counted and rendered verbatim.
    check(
      html.includes(`CERTIFICATE FAILURES (${fixture.certificate.failures.length})`),
      'group A prints its heading with the certificate count',
    );
    check(
      (html.match(/data-testid="certificate-failure-row"/g) || []).length ===
        fixture.certificate.failures.length,
      'group A renders exactly the certificate failure rows',
    );
    const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    check(
      fixture.certificate.failures.every((f) => html.includes(esc(f))),
      'every certificate failure row prints verbatim',
    );
    // GROUP B: the listed deviations, counted as the rows displayed.
    check(
      html.includes(`LISTED DEVIATIONS (${report.truth.counts.listedDeviations})`),
      'group B prints its heading with the listed-row count',
    );
    check(
      (html.match(/data-testid="listed-deviation-row"/g) || []).length ===
        report.truth.counts.listedDeviations,
      'group B renders exactly the listed deviation rows',
    );
    check(
      html.includes(`UNRESOLVED BREACHES (${report.truth.counts.unresolvedBreaches})`),
      'group C prints its heading with the breach count',
    );
    check(
      html.includes(`${report.tiers.T3.messages} advisor`),
      'the advisories toggle prints the T3 total',
    );
    check(
      html.includes(`Engine operations log (${report.tiers.T4.messages})`),
      'the engine log prints the T4 total',
    );
    check(
      html.includes(`View all ${report.totalMessages} messages`),
      'the full-list toggle prints the raw total',
    );
    check(
      html.includes(`${report.relaxations.total} structured relaxation`) &&
        html.includes(`${report.relaxations.rooms} room`),
      'the listed-deviation header prints the structured total and room count',
    );
    check(
      !html.includes('Applied Relaxations'),
      'the removed duplicate relaxation list does not render',
    );

    console.log('\n[5] Relaxations — grouped, deduped policy');
    check(
      report.relaxations.groups.length === report.relaxations.rooms,
      'one group per room',
    );
    check(
      report.relaxations.groups.reduce((n, g) => n + g.items.length, 0) ===
        report.relaxations.total,
      'every relaxation belongs to exactly one room group',
    );
    check(
      report.relaxations.total === fixture.relaxations.length,
      'every structured relaxation is shown',
    );
    check(
      report.relaxations.policyFromEngine && report.relaxations.policy.length > 40,
      'the shared policy sentence was extracted from the payload',
      report.relaxations.policy.slice(0, 60),
    );
    check(
      /^[A-Z]/.test(report.relaxations.policy) && /[.!?]$/.test(report.relaxations.policy),
      'the policy reads as a standalone sentence',
      report.relaxations.policy,
    );
    check(
      report.relaxations.items.every((i) => !i.reason.includes(report.relaxations.policy)),
      'no row repeats the shared policy',
    );
    check(
      report.relaxations.items.every((i) => !/Listed as a relaxation on this room/i.test(i.reason)),
      'no row retains the removed boilerplate clause',
    );
    const chips = report.relaxations.items.map((i) => `${i.ruleId}|${i.chip}`);
    check(
      report.relaxations.items.every((i) => i.chip.length > 0 && i.chip.length <= 46),
      'every row carries a short distinct reason chip',
      chips.join(' / '),
    );
    check(
      report.relaxations.items.every((i) => shortReason(i.reason) === i.chip),
      'chips are derived deterministically from the row reason',
    );

    const expanded = renderToStaticMarkup(
      React.createElement(WarningReportView, {
        warnings: fixture.warnings,
        relaxations: fixture.relaxations,
        planVerdict: fixture.plan_verdict,
        certificateFailures: fixture.certificate.failures,
        expandAll: true,
      }),
    );
    check(
      countTestId(expanded, 'relaxation-records') === report.relaxations.rooms,
      'expanded: one structured-record block per room',
      `${countTestId(expanded, 'relaxation-records')} blocks`,
    );
    check(
      countTestId(expanded, 'relaxation-item') === report.relaxations.total,
      'expanded: every structured relaxation is reachable',
      `${countTestId(expanded, 'relaxation-item')} vs ${report.relaxations.total}`,
    );
    check(
      countTestId(expanded, 'certificate-failure-row') === fixture.certificate.failures.length,
      'expanded: the certificate failure rows are all printed',
    );
    // The verbatim list (full disclosure) keeps the raw engine text, and the
    // listed-deviation rows quote the page-1 disclosure verbatim too; only the
    // structured RECORDS themselves must be free of the repeated policy clause.
    const itemBlocks = expanded.match(/<li data-testid="relaxation-item"[\s\S]*?<\/li>/g) || [];
    check(
      itemBlocks.length === report.relaxations.total,
      'expanded: every structured record renders as its own row',
      `${itemBlocks.length} vs ${report.relaxations.total}`,
    );
    check(itemBlocks.length > 0, 'expanded: the structured-record region renders');
    check(
      itemBlocks.every((block) => !/Listed as a relaxation on this room/i.test(block)),
      'expanded: no structured record carries the boilerplate clause',
    );
    check(
      itemBlocks.every((block) => !/certificate still fails the dimension layer/i.test(block)),
      'expanded: the shared policy sentence is not repeated in a record',
    );
    check(
      countTestId(expanded, 'full-message') === fixture.warnings.length,
      'expanded: the full verbatim list renders every raw line',
    );
    check(
      countTestId(expanded, 'operations-list') === 1 &&
        (expanded.match(/data-tier="T4"/g) || []).length >= report.tiers.T4.entries,
      'expanded: the engine operations drawer renders its rows',
    );

    console.log('\n[6] Dedupe');
    const dup = buildWarningReport(
      [...fixture.warnings.slice(0, 3), fixture.warnings[0]],
      [],
    );
    check(dup.totalMessages === 4, 'duplicate raw lines are all counted');
    check(dup.totalDistinct === 3, 'identical raw lines group into one entry');
    check(
      dup.entries.find((e) => e.key === fixture.warnings[0].trim()).occurrences === 2,
      'the repeated line carries its occurrence count',
    );
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
