#!/usr/bin/env node
/**
 * test_blueprint_reveal.cjs — pins for the progressive sheet reveal (no browser).
 * =============================================================================
 * The DOM mechanics (animation state, room-fill classes, focus trap) are proven
 * in scripts/e2e_blueprint_reveal.cjs. This file pins the parts a browser test
 * should not be the only guard for:
 *
 *   [1] phase order and timing match the drawing, and the sequence is bounded;
 *   [2] the sheet group is explicitly excluded from the animated selector, so
 *       the title block / validation gate / FAIL stamp never fade in;
 *   [3] the sanitizer output stays static (no reveal switch on the root), so an
 *       exported or printed SVG is the finished drawing;
 *   [4] room ids survive sanitization for in-place selection;
 *   [5] reduced motion collapses the reveal in CSS.
 *
 * Run: node --experimental-strip-types scripts/test_blueprint_reveal.cjs
 */
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let failures = 0;
let passes = 0;

function check(ok, label, detail) {
  if (ok) {
    passes += 1;
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

(async () => {
  const { createServer } = await import('vite');
  const vite = await createServer({
    configFile: false,
    root: ROOT,
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true },
  });

  const reveal = await vite.ssrLoadModule('/src/components/report/blueprintReveal.ts');
  const sanitize = await vite.ssrLoadModule('/src/components/report/svgSanitize.ts');

  const {
    BLUEPRINT_REVEAL_PHASES,
    BLUEPRINT_PHASE_DELAY_MS,
    BLUEPRINT_PHASE_DURATION_MS,
    BLUEPRINT_REVEAL_TOTAL_MS,
    sheetHasRevealPhases,
  } = reveal;

  console.log('\n[1] Phase contract');
  check(
    BLUEPRINT_REVEAL_PHASES.join(',') ===
      'envelope,site,rooms,ghost,walls,cores,openings,labels,dims,annotations',
    'phases follow the drawing order and exclude sheet',
    BLUEPRINT_REVEAL_PHASES.join(',')
  );
  const delays = BLUEPRINT_REVEAL_PHASES.map((phase) => BLUEPRINT_PHASE_DELAY_MS[phase]);
  check(
    delays.every((value, index) => index === 0 || value > delays[index - 1]),
    'delays increase strictly (no two layers land together)',
    delays.join(',')
  );
  check(
    BLUEPRINT_REVEAL_TOTAL_MS === delays[delays.length - 1] + BLUEPRINT_PHASE_DURATION_MS,
    'total is the last delay plus one phase duration'
  );
  check(BLUEPRINT_REVEAL_TOTAL_MS <= 1000, 'the full reveal lands under 1 s', `${BLUEPRINT_REVEAL_TOTAL_MS} ms`);
  check(sheetHasRevealPhases('<svg><g data-bw-phase="walls"></g></svg>'), 'phase-bearing SVG is detected');
  check(!sheetHasRevealPhases('<svg><g></g></svg>'), 'an SVG without phases is not revealed');
  check(!sheetHasRevealPhases(null), 'null is not revealed');

  console.log('\n[2] Sanitized sheet / export is static');
  const source = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">',
    '<g data-bw-phase="envelope"><rect x="0" y="0" width="10" height="10"/></g>',
    '<g data-bw-phase="rooms"><rect class="bw-room-fill" data-room-id="living_F0" fill-opacity="0.15"/></g>',
    '<g data-bw-phase="sheet"><text>VALIDATION GATE</text><text>FAIL</text></g>',
    '</svg>',
  ].join('');
  const out = sanitize.sanitizeBlueprintSvg(source, false);
  check(out.includes('bw-room-fill'), 'room fill class survives sanitization');
  check(out.includes('data-room-id="living_F0"'), 'room id survives sanitization');
  check(out.includes('data-bw-phase="sheet"'), 'the verdict-bearing sheet group survives');
  check(!/<svg[^>]*data-bw-reveal=/.test(out), 'sanitizer writes no reveal switch (export/print are final)');
  check(
    out.includes('[data-bw-reveal="run"] [data-bw-phase]:not([data-bw-phase="sheet"])'),
    'the animated selector excludes the sheet group'
  );
  check(out.includes('@keyframes bwSheetPhaseIn'), 'the reveal keyframes are present but inert');
  check(out.includes('prefers-reduced-motion: reduce'), 'reduced motion has an explicit collapse rule');
  check(
    BLUEPRINT_REVEAL_PHASES.every((phase) =>
      out.includes(
        `[data-bw-phase]:not([data-bw-phase="sheet"])[data-bw-phase="${phase}"] { animation-delay: ${BLUEPRINT_PHASE_DELAY_MS[phase]}ms; }`
      )
    ),
    'every CSS delay is generated from the single TS timing source'
  );
  check(
    out.includes('[data-room-focus="on"] .bw-room-fill.bw-room-selected'),
    'selected-room fill rule is present'
  );
  check(!out.includes('data-bw-reveal="run"><'), 'no attribute is placed on the root by the sanitizer');

  console.log('\n[3] Static source with no phases');
  const plain = sanitize.sanitizeBlueprintSvg('<svg><rect width="2" height="2"/></svg>', false);
  check(plain.includes('bw-sheet-fit'), 'fit styling still applies');
  check(plain.includes('@media (prefers-reduced-motion: reduce)'), 'reduced-motion rule is harmless on a plain sheet');

  await vite.close();
  console.log(`\n=== blueprint reveal pins: ${passes} passed, ${failures} failed ===`);
  process.exit(failures ? 1 : 0);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
