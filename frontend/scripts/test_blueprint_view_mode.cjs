#!/usr/bin/env node
/**
 * test_blueprint_view_mode.cjs — pure framing pins (no browser).
 * ==============================================================
 * The browser suite proves the DOM viewBox/crop on a real solved sheet. These
 * pins cover the arithmetic that decides the crop, so a bad union or an
 * out-of-sheet clamp is caught without a solver or a browser:
 *
 *   [1] viewBox parsing rejects malformed / zero-area boxes;
 *   [2] unionRects ignores empty descendants and spans the real extents;
 *   [3] planFocusRect pads the plan but never leaves the authored sheet;
 *   [4] the mode table is exactly Full Sheet / Plan Focus / Fit Width.
 *
 * Run: node --experimental-strip-types scripts/test_blueprint_view_mode.cjs
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
  const {
    BLUEPRINT_VIEW_MODES,
    PLAN_FOCUS_PHASES,
    formatViewBox,
    parseViewBox,
    planFocusRect,
    unionRects,
  } = await vite.ssrLoadModule('/src/components/report/blueprintViewMode.ts');

  console.log('\n[1] viewBox parser');
  check(
    BLUEPRINT_VIEW_MODES.map((m) => m.label).join(' / ') ===
      'Full Sheet / Plan Focus / Fit Width',
    'three modes are named in the UI order',
    BLUEPRINT_VIEW_MODES.map((m) => m.label).join(' / ')
  );
  check(formatViewBox({ x: 0, y: 5.8, width: 452.65, height: 473.66 }) === '0 5.8 452.65 473.66', 'viewBox formatting is stable');
  const parsed = parseViewBox('0 5.8 452.65 473.66');
  check(parsed && parsed.y === 5.8 && parsed.width === 452.65, 'a valid viewBox parses');
  check(parseViewBox('0 0 0 100') === null, 'a zero-width viewBox is rejected');
  check(parseViewBox('0 0 100') === null, 'a short viewBox is rejected');
  check(parseViewBox('nope') === null, 'non-numeric input is rejected');

  console.log('\n[2] union');
  const union = unionRects([
    { x: 10, y: 20, width: 100, height: 50 },
    { x: 40, y: 5, width: 20, height: 20 },
    { x: 0, y: 0, width: 0, height: 30 },
  ]);
  check(
    union && union.x === 10 && union.y === 5 && union.width === 100 && union.height === 65,
    'union spans real boxes and ignores empty ones',
    JSON.stringify(union)
  );
  check(unionRects([]) === null, 'an empty plan has no union');

  console.log('\n[3] plan crop');
  const base = { x: 0, y: 0, width: 495, height: 1386 };
  const plan = planFocusRect(base, [{ x: 20, y: 100, width: 430, height: 460 }]);
  check(plan.width < base.width && plan.height < base.height, 'the plan crop is smaller than the sheet', JSON.stringify(plan));
  check(plan.x >= base.x && plan.y >= base.y, 'the crop starts inside the sheet', JSON.stringify(plan));
  check(
    plan.x + plan.width <= base.x + base.width + 1e-9 &&
      plan.y + plan.height <= base.y + base.height + 1e-9,
    'the crop never runs past the sheet edge',
    JSON.stringify(plan)
  );
  check(
    plan.x < 20 && plan.y < 100 && plan.x + plan.width > 450 && plan.y + plan.height > 560,
    'the crop includes a margin around the plan',
    JSON.stringify(plan)
  );
  const edge = planFocusRect(base, [{ x: -100, y: -100, width: 1000, height: 2000 }]);
  check(
    edge.x === 0 && edge.y === 0 && edge.width === 495 && edge.height === 1386,
    'an oversized plan clamps to the full sheet rather than showing empty margins',
    JSON.stringify(edge)
  );
  check(planFocusRect(base, []) .width === base.width, 'no plan layers falls back to the full sheet');
  check(PLAN_FOCUS_PHASES.includes('walls') && !PLAN_FOCUS_PHASES.includes('sheet'), 'the crop targets plan layers, never the verdict sheet group');

  await vite.close();
  console.log(`\n=== blueprint view mode pins: ${passes} passed, ${failures} failed ===`);
  process.exit(failures ? 1 : 0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
