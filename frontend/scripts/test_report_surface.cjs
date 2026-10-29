#!/usr/bin/env node
/**
 * test_report_surface.cjs — component pins for the report surfaces.
 * ==============================================================================
 * Repo dialect: plain-node assertions (no test framework).  The components are
 * TSX, so Vite's SSR module loader transforms them in-process; React renders to
 * static markup and the assertions read the REAL DOM strings (not a regex over
 * source), except for the print-page wiring pin at the end.
 *
 * Pins:
 *   1. CertificatePanel L16 table renders a beyond-cap room and a LISTED
 *      relaxation, with band %, rule and factor.
 *   2. The FAIL stamp appears only on a FAIL/conflict banner; a WARN advisory
 *      never receives it.
 *   3. PlanVerdictChip shows NOT CERTIFIED only for a withheld certificate or a
 *      FAIL gate; a WARN gate shows nothing.
 *   4. The Print Report page-1 banner reads the merged plan list, not
 *      analysisData alone.
 *   5. planWarnings.ts is the one page-1 filter for card, sheet, print and PDF.
 */
const fs = require('fs');
const path = require('path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const ROOT = path.resolve(__dirname, '..');
let failures = 0;
let passes = 0;

function check(cond, label, detail) {
  if (cond) {
    passes++;
    console.log(`  ok   ${label}`);
  } else {
    failures++;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function layerRows(l16Status, l16Details) {
  return Array.from({ length: 16 }, (_, i) => ({
    layer_id: `L${i + 1}`,
    title: i + 1 === 16 ? 'Proportion & Surplus' : `Layer ${i + 1}`,
    status: i + 1 === 16 ? l16Status : 'PASS',
    summary: i + 1 === 16 ? 'proportion evidence' : 'ok',
    ...(i + 1 === 16 && l16Details ? { details: l16Details } : {}),
  }));
}

const L16_ROOMS = [
  {
    room_id: 'living_F0', floor: 0, measured_aspect: 2.5, band: 1.8, band_pct: 139,
    inside_band: false, relaxation_rule: null, relaxation_factor: null,
    area_sqm: 22.0, area_ceiling_sqm: 45.0, ceiling_overage_sqm: 0,
  },
  {
    room_id: 'kitchen_F0', floor: 0, measured_aspect: 2.28, band: 1.8, band_pct: 127,
    inside_band: false, relaxation_rule: 'PROP-ASPECT', relaxation_factor: 1.28,
    area_sqm: 9.4, area_ceiling_sqm: 20.0, ceiling_overage_sqm: 0,
  },
  {
    room_id: 'master_bed_F0', floor: 0, measured_aspect: 1.26, band: 1.8, band_pct: 70,
    inside_band: true, relaxation_rule: null, relaxation_factor: null,
    area_sqm: 19.8, area_ceiling_sqm: 25.0, ceiling_overage_sqm: 0,
  },
];

const L16_DETAILS = {
  rooms: L16_ROOMS,
  relaxations: [{ room: 'kitchen_F0', floor: 0, rule_id: 'PROP-ASPECT', measured: 2.28, band: 1.8 }],
  beyond_cap: ['F0 living_F0: 1:2.50 against a 1:1.80 band (1.39x, cap 1.40x) and no listed relaxation'],
  justified_beyond_cap: [],
  ceiling_overages: [],
  relaxation_cap: 1.4,
  surplus: {
    outdoor_sqm: 0, anonymous_outdoor_sqm: 0, dead_corner_sqm: 0,
    residual_slivers: 0, absorbed_slivers: 0, sliver_labels: ['rear yard'],
    void_ratio_pct: 9.3,
  },
};

function qaFixture(status) {
  return {
    validation_gate: {
      overall_status: status,
      layers: layerRows(status === 'FAIL' ? 'FAIL' : 'WARN', status === 'FAIL'
        ? L16_DETAILS
        : { ...L16_DETAILS, rooms: L16_ROOMS.map((r) => ({ ...r, inside_band: true })), beyond_cap: [] }),
    },
  };
}

async function main() {
  const { createServer } = await import('vite');
  const server = await createServer({
    root: ROOT,
    logLevel: 'error',
    appType: 'custom',
    server: { middlewareMode: true },
  });

  try {
    const { CertificatePanel } = await server.ssrLoadModule('/src/components/report/CertificatePanel.tsx');
    const { WarningsBanner } = await server.ssrLoadModule('/src/components/report/WarningsBanner.tsx');
    const { PlanVerdictChip } = await server.ssrLoadModule('/src/components/report/PlanVerdictChip.tsx');
    const {
      page1PlanWarnings,
      isCriticalPlanWarning,
      bannerWarnings,
    } = await server.ssrLoadModule('/src/services/planWarnings.ts');

    console.log('\n[1] CertificatePanel L16 table');
    const failHtml = renderToStaticMarkup(
      React.createElement(CertificatePanel, { qa: qaFixture('FAIL'), variant: 'sheet', relaxationsCount: 1 }),
    );
    check(failHtml.includes('data-testid="certificate-panel"'), 'panel renders');
    check(failHtml.includes('data-testid="proportion-rooms"'), 'L16 room table renders on FAIL');
    check(failHtml.includes('living_F0') && failHtml.includes('kitchen_F0'), 'both over-band rooms render');
    check(failHtml.includes('1:2.50') && failHtml.includes('1:1.80'), 'measured aspect and band render');
    check(failHtml.includes('139%'), 'band percentage renders');
    check(failHtml.includes('outside'), 'a beyond-cap room without a relaxation is marked outside');
    check(
      failHtml.includes('PROP-ASPECT @ 1.28x'),
      'the listed relaxation renders with its rule and factor',
    );
    check(failHtml.includes('master_bed_F0') && failHtml.includes('inside'),
      'the ALL-room table also prints the inside-band room');
    check(
      /bg-\[var\(--semantic-red\)\]\/10[^"]*"[^>]*>\s*FAIL/.test(failHtml) || />\s*FAIL\s*</.test(failHtml),
      'overall FAIL chip renders',
    );

    console.log('\n[2] WARN never receives the FAIL treatment');
    const warnHtml = renderToStaticMarkup(
      React.createElement(CertificatePanel, { qa: qaFixture('WARN'), variant: 'sheet' }),
    );
    check(warnHtml.includes('data-testid="proportion-rooms"'), 'the ALL-room table still renders on WARN');
    check(warnHtml.includes('3/3 rooms inside band'), 'the L16 summary discloses the census');
    check(/>\s*WARN\s*</.test(warnHtml), 'WARN chip renders');
    check(!warnHtml.includes('>FAIL<'), 'a WARN gate never renders a FAIL chip');

    const bannerFail = renderToStaticMarkup(
      React.createElement(WarningsBanner, {
        data: {
          warnings: [
            "ROOM-OVERLAP: rooms 'bath_1' and 'bed_2' overlap by 5.02 m² on floor 0.",
            'PROGRAMME-DEFICIT: the programme needs 122.7 m²; the plate provides 85.7 m².',
          ],
        },
      }),
    );
    check(/data-critical="true"/.test(bannerFail), 'ROOM-OVERLAP / PROGRAMME-DEFICIT set the banner critical');
    check(bannerFail.includes('FAIL stamp'), 'critical banner renders the FAIL stamp');
    check(bannerFail.includes('overlap by 5.02'), 'the named conflict line renders verbatim');

    const bannerWarn = renderToStaticMarkup(
      React.createElement(WarningsBanner, {
        data: { warnings: ['PROP-ASPECT: living aspect 1:1.83 above the band; listed relaxation.'] },
      }),
    );
    check(/data-critical="false"/.test(bannerWarn), 'a listed PROP-ASPECT advisory is not critical');
    check(!bannerWarn.includes('FAIL stamp'), 'WARN/advisory banner never shows the FAIL stamp');

    const bannerSplit = renderToStaticMarkup(
      React.createElement(WarningsBanner, {
        data: {
          warnings: [
            'PROP-IDEAL: bath_1 aspect 1:1.80 is outside the 1:1.50 ideal band.',
            'ROOM-MAX: dining_0_1 is 19.2 m², above its 14.0 m² catalogue maximum.',
            'Road network telemetry unavailable. Approach-side alignment bonus omitted.',
            'Guidance rate is effective 2024 and may be stale relative to the current market.',
          ],
        },
      }),
    );
    check(/data-plan-warning-count="2"/.test(bannerSplit), 'banner counts only the two plan lines');
    check(
      /data-degradation-count="2"/.test(bannerSplit),
      'banner counts the two degradation lines separately',
    );
    check(
      bannerSplit.includes('Plan warnings') && bannerSplit.includes('Data degradation notice'),
      'banner labels plan disclosures and provenance caveats separately',
    );
    check(
      bannerSplit.includes('banner-degradation-notice'),
      'degradation lines render in their own labelled block',
    );
    check(
      !bannerSplit.includes('Proportion / programme non-compliance'),
      'banner never labels provenance caveats as proportion non-compliance',
    );

    console.log('\n[3] PlanVerdictChip');
    const chipFail = renderToStaticMarkup(
      React.createElement(PlanVerdictChip, { isValid: false, gateStatus: 'FAIL' }),
    );
    check(chipFail.includes('data-testid="viewer-not-certified-chip"'), 'FAIL gate renders the chip');
    check(chipFail.includes('NOT CERTIFIED'), 'chip carries NOT CERTIFIED');

    const chipWarn = renderToStaticMarkup(
      React.createElement(PlanVerdictChip, { isValid: true, gateStatus: 'WARN' }),
    );
    check(chipWarn === '', 'WARN + valid certificate renders no chip');
    const chipPass = renderToStaticMarkup(
      React.createElement(PlanVerdictChip, { isValid: true, gateStatus: 'PASS' }),
    );
    check(chipPass === '', 'PASS renders no chip');

    console.log('\n[4] Plan warning filter (card / sheet / print / PDF mirror)');
    const planWarnings = [
      'PROP-HARD: kitchen below minimum.',
      'PROP-IDEAL: living outside its ideal band.',
      'PROGRAMME-SQUEEZE: one room below minimum.',
      'ROOM-MIN: kitchen 8.3 m² below 9.0 m².',
      'ROOM-MIN living: clear width below catalogue (declared relaxation).',
      "ROOM-OVERLAP: rooms 'a' and 'b' overlap by 1.00 m².",
      'SELECTION-FALLBACK: selection replaced by the legal programme.',
      'GATE-FAIL L1: aspect exceeds the band.',
      'PLATE-SHORT: plate is 59.5 m² against 78.2 m².',
      'GEN-FAIL: not a page-1 row.',
      'Degradation Level 1 applied: not a page-1 row.',
    ];
    const page1 = page1PlanWarnings(planWarnings);
    check(page1.length === 9, `nine page-1 rows survive the filter (got ${page1.length})`, page1.join(' | '));
    check(!page1.some((w) => w.startsWith('GEN-FAIL')), 'GEN-FAIL is not a page-1 plan row');
    check(!page1.some((w) => w.startsWith('Degradation')), 'analysis-only degradation is not a plan row');
    check(isCriticalPlanWarning(page1[0]) && isCriticalPlanWarning(page1[4]), 'critical filter catches ROOM-* rows');
    check(!isCriticalPlanWarning('PROP-ASPECT: listed relaxation'), 'listed aspect relaxation is not critical');
    const merged = bannerWarnings(
      { warnings: ['Telemetry unavailable.'] },
      { warnings: planWarnings },
    );
    check(merged.length === 10 && merged[1] === planWarnings[0], 'banner merges analysis + plan list in order');

    console.log('\n[4b] One plan verdict across card / certificate / viewer');
    const verdictFail = 'NOT-CERTIFIED-FAIL-STAMP';
    const certFail = renderToStaticMarkup(
      React.createElement(CertificatePanel, {
        qa: qaFixture('WARN'),
        variant: 'sheet',
        planVerdict: verdictFail,
      }),
    );
    check(
      /data-testid="certificate-plan-verdict"/.test(certFail) && certFail.includes(verdictFail),
      'the certificate panel renders the server verdict verbatim',
    );
    const certCertified = renderToStaticMarkup(
      React.createElement(CertificatePanel, {
        qa: qaFixture('PASS'),
        variant: 'sheet',
        planVerdict: 'CERTIFIED',
      }),
    );
    check(certCertified.includes('CERTIFIED'), 'a certified plan renders CERTIFIED');
    const certNoVerdict = renderToStaticMarkup(
      React.createElement(CertificatePanel, { qa: qaFixture('WARN'), variant: 'sheet' }),
    );
    check(!certNoVerdict.includes('certificate-plan-verdict'), 'no verdict prop => no verdict claimed');

    const viewerChip = renderToStaticMarkup(
      React.createElement(PlanVerdictChip, { verdict: verdictFail }),
    );
    check(viewerChip.includes(verdictFail), 'the viewer chip renders the same token');
    const viewerChipCertified = renderToStaticMarkup(
      React.createElement(PlanVerdictChip, { verdict: 'CERTIFIED' }),
    );
    check(viewerChipCertified === '', 'a CERTIFIED plan renders no not-certified chip');

    const cardSrc = fs.readFileSync(
      path.join(ROOT, 'src', 'components', 'FloorPlanGeneratorCard.tsx'),
      'utf8',
    );
    // The verdict chip moved into the tiered warning report that the card
    // mounts; the card still owns the decision and passes the server verdict.
    const reportSrc = fs.readFileSync(
      path.join(ROOT, 'src', 'components', 'report', 'WarningReportView.tsx'),
      'utf8',
    );
    check(/data-testid="plan-verdict"/.test(reportSrc), 'the plan card renders a plan-verdict token');
    check(
      /<WarningReportView[\s\S]*?planVerdict=\{planVerdict\}/.test(cardSrc),
      'the card mounts the warning report with the server verdict',
    );
    check(/planVerdict/.test(cardSrc), 'the card consumes the server verdict');
    check(
      /planVerdict=\{planVerdict\}/.test(cardSrc),
      'the card passes the same verdict to the certificate panel',
    );

    console.log('\n[5] Print page-1 wiring');
    const sheet = fs.readFileSync(path.join(ROOT, 'src', 'components', 'ReportSheet.tsx'), 'utf8');
    check(!/WarningsBanner\s+data=\{analysisData\}/.test(sheet), 'no WarningsBanner still reads analysisData alone');
    const printBlock = sheet.slice(sheet.indexOf('report-print-all'));
    check(
      /WarningsBanner\s+data=\{bannerData\}/.test(printBlock),
      'the print block renders the merged bannerData',
    );
    check(
      /bannerWarnings\(analysisData, floorPlanData\)/.test(sheet),
      'bannerData is built by the shared planWarnings helper',
    );

    console.log('\n[6] Engine state badge');
    const { AppHeader } = await server.ssrLoadModule('/src/components/AppHeader.tsx');
    const headerProps = {
      onOpenMethodology: () => {},
      onReset: () => {},
      theme: 'light',
    };
    const header = (over) =>
      renderToStaticMarkup(
        React.createElement(AppHeader, {
          ...headerProps,
          backendConnected: true,
          activeAiProvider: 'groq',
          serverStatus: { groq: true, gemini: false },
          ...over,
        }),
      );

    const live = header();
    check(live.includes('data-engine-state="live"'), 'a configured hosted key renders the live state');
    check(live.includes('Live · Groq'), 'the live label names the probed provider');
    check(
      /reachability is not/i.test(live),
      'the live title discloses that reachability is not probed',
    );

    const noKey = header({ serverStatus: { groq: false, gemini: false } });
    check(
      noKey.includes('data-engine-state="deterministic"'),
      'a hosted provider without a key renders the deterministic state',
    );
    check(!noKey.includes('Offline'), 'a working deterministic engine is never labelled offline');
    check(noKey.includes('Deterministic'), 'the deterministic label is explicit');

    const mock = header({ activeAiProvider: 'mock' });
    check(mock.includes('data-engine-state="deterministic"'), 'the built-in provider renders deterministic');

    const offline = header({ backendConnected: false, serverStatus: null });
    check(offline.includes('data-engine-state="offline"'), 'an unreachable backend renders offline');
    check(offline.includes('>Offline<') || offline.includes('Offline</span>'), 'the offline label is explicit');

    const gemini = header({ activeAiProvider: 'gemini', serverStatus: { groq: false, gemini: true } });
    check(gemini.includes('data-engine-state="live"') && gemini.includes('Live · Gemini'),
      'each hosted provider is probed independently');

    const ollama = header({ activeAiProvider: 'ollama' });
    check(
      ollama.includes('data-engine-state="unverified"'),
      'an unprobed local provider is never claimed live or deterministic',
    );

    for (const [name, html] of [['live', live], ['no-key', noKey], ['mock', mock], ['offline', offline], ['ollama', ollama]]) {
      check(!/Engine Offline \(Local Mock\)/.test(html), `${name}: retired misleading offline-mock copy is gone`);
    }

    console.log('\n[7] Key-removal fallback disclosure');
    const { RecommendationPanel } = await server.ssrLoadModule('/src/components/RecommendationPanel.tsx');
    const narrative = (providerUsed) =>
      renderToStaticMarkup(
        React.createElement(RecommendationPanel, {
          summary: 'The site is workable with the stated brief.',
          recommendations: ['Confirm the frontage before setting out.'],
          aiMetadata: {
            provider_requested: 'groq',
            provider_used: providerUsed,
            parameter_reflection: 'The plot carries a workable programme.',
            fallback_reason: providerUsed.includes('mock')
              ? 'GROQ_API_KEY is not configured in environment'
              : undefined,
          },
        }),
      );

    const fallbackNarrative = narrative('mock_fallback');
    check(
      fallbackNarrative.includes('Deterministic engine narrative'),
      'a key-removal fallback is labelled as the deterministic engine',
    );
    check(
      !/AI narrative/i.test(fallbackNarrative),
      'a fallback is never labelled an AI narrative',
    );
    check(
      !/AI-generated/i.test(fallbackNarrative),
      'a fallback is never claimed AI-generated',
    );

    const liveNarrative = narrative('groq (gpt-oss-120b)');
    check(
      liveNarrative.includes('AI narrative — advisory, non-certified'),
      'a real hosted answer carries the advisory, non-certified label',
    );

    console.log('\n[8] Narrative-engine badge vocabulary');
    const { PROVIDER_STATE_LABEL, effectiveProviderState } = await server.ssrLoadModule(
      '/src/services/providerBadge.ts',
    );
    check(PROVIDER_STATE_LABEL.live === 'Live', 'the hosted-key state reads Live');
    check(PROVIDER_STATE_LABEL.deterministic === 'Deterministic', 'the built-in state reads Deterministic');
    check(PROVIDER_STATE_LABEL.offline === 'Offline', 'the unreachable state reads Offline');
    check(
      effectiveProviderState('deterministic', false) === 'offline',
      'an unreachable backend overrides the selected author with Offline',
    );
    check(
      effectiveProviderState('deterministic', true) === 'deterministic',
      'a reachable built-in engine stays Deterministic (never Live)',
    );

    console.log('\n[9] One live report tab bar');
    const sheetSrc = fs.readFileSync(path.join(ROOT, 'src', 'components', 'ReportSheet.tsx'), 'utf8');
    check(
      /useMediaQuery\('\(min-width: 1024px\)'\)/.test(sheetSrc),
      'the sheet chooses its tab bar from the viewport query',
    );
    check(
      /desktopTabs && \(/.test(sheetSrc) && /!desktopTabs && \(/.test(sheetSrc),
      'each tab bar is mounted only on its side of the breakpoint',
    );
    check(
      !/report-sheet-tabs-nav hidden lg:flex/.test(sheetSrc) &&
        !/report-sheet-tabs-nav lg:hidden/.test(sheetSrc),
      'no CSS-hidden duplicate tab bar remains',
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
