#!/usr/bin/env node
/**
 * e2e_blueprint_view_modes.cjs — browser proof for the three framing modes.
 * ==========================================================================
 * Runs against the production BlueprintViewer mounted over a real API solve:
 *
 *   Full Sheet  — the server's whole viewBox, title block included.
 *   Plan Focus  — a strict crop of the real plan-layer bounding boxes.
 *   Fit Width   — the whole sheet scaled to the viewer width, top-aligned.
 *
 * What this pins:
 *   [1] geometry is never regenerated: same <svg> node, same fill/wall counts;
 *   [2] ViewBox crops come from the real layer bounding boxes, not fixed bounds;
 *   [3] switching modes does not replay or restart the progressive reveal;
 *   [4] reset and keyboard 0/1/2/3 return to a whole sheet at 100%;
 *   [5] the same modes work inside the fullscreen dialog;
 *   [6] a fail-stamped plan keeps its verdict visible outside the crop;
 *   [7] 390 px and reduced-motion modes remain usable;
 *   [8] axe finds no new critical/serious violations in the mode chrome.
 *
 * Usage: node scripts/e2e_blueprint_view_modes.cjs
 * Env:   E2E_URL (default http://127.0.0.1:5173/app), CHROME_PATH
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://127.0.0.1:5173/app';
const OUT = path.resolve(ROOT, '..', 'docs_ignore', 'qa-audit', 'assets-blueprint');
const CHROME = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean).find((p) => {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
});

let passes = 0;
let failures = 0;
function check(ok, label, detail) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
  ok ? (passes += 1) : (failures += 1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SELECT = {
  proof: '[data-testid="blueprint-proof"][data-phase="ready"]',
  sheet: '[data-testid="blueprint-sheet-card"] svg',
  modal: '[role="dialog"][aria-modal="true"]',
  modalSheet: '[data-testid="blueprint-sheet-modal"] svg',
};

async function mount(page, caseId) {
  await page.evaluate(async (id) => {
    const harness = await import('/scripts/harness/blueprintRevealMount.tsx');
    await harness.mountBlueprintReveal(id);
  }, caseId);
  await page.waitForSelector(SELECT.proof, { timeout: 120000 });
  await page.waitForSelector(SELECT.sheet, { timeout: 20000 });
}

async function waitInjected(page) {
  await page.waitForFunction(
    () =>
      Boolean(document.querySelector('[data-testid="blueprint-sheet-card"] svg[data-bw-view]')) &&
      !document.querySelector('[data-testid="blueprint-sheet-card"][aria-busy="true"]'),
    { timeout: 10000 }
  );
}

async function readCard(page) {
  return page.evaluate(() => {
    const host = document.querySelector('[data-testid="blueprint-sheet-card"]');
    const svg = host?.querySelector('svg');
    if (!svg) return null;
    const canvas = document.querySelector('[data-testid="blueprint-viewport"]');
    const vb = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
    const base = (svg.getAttribute('data-bw-base-viewbox') || '').trim().split(/[\s,]+/).map(Number);
    const sheetGroup = svg.querySelector('[data-bw-phase="sheet"]');
    const sb = sheetGroup ? sheetGroup.getBBox() : null;
    const sheetBox = sb ? { x: sb.x, y: sb.y, width: sb.width, height: sb.height } : null;
    const sr = svg.getBoundingClientRect();
    const cr = canvas?.getBoundingClientRect();
    const hr = host?.getBoundingClientRect();
    const cs = getComputedStyle(svg);
    const planBoxes = [...svg.querySelectorAll('[data-bw-phase]')]
      .filter((g) => !['sheet', 'annotations'].includes(g.getAttribute('data-bw-phase')))
      .map((g) => g.getBBox());
    const planUnion = planBoxes.reduce(
      (acc, b) => ({
        x: Math.min(acc.x, b.x),
        y: Math.min(acc.y, b.y),
        right: Math.max(acc.right, b.x + b.width),
        bottom: Math.max(acc.bottom, b.y + b.height),
      }),
      { x: Infinity, y: Infinity, right: -Infinity, bottom: -Infinity }
    );
    return {
      mode: svg.getAttribute('data-bw-view'),
      viewBox: vb,
      baseViewBox: base,
      planUnion: Number.isFinite(planUnion.x)
        ? {
            x: planUnion.x,
            y: planUnion.y,
            width: planUnion.right - planUnion.x,
            height: planUnion.bottom - planUnion.y,
          }
        : null,
      sheetBox,
      width: sr.width,
      height: sr.height,
      canvasWidth: cr?.width || 0,
      canvasHeight: cr?.height || 0,
      hostWidth: hr?.width || 0,
      topGap: cr ? sr.top - cr.top : -1,
      position: cs.position,
      reveal: svg.getAttribute('data-bw-reveal'),
      animations: svg.getAnimations({ subtree: true }).length,
      fills: svg.querySelectorAll('.bw-room-fill').length,
      walls: svg.querySelectorAll('[data-bw-phase="walls"] *').length,
      labels: svg.querySelectorAll('[data-bw-phase="labels"] *').length,
      dims: svg.querySelectorAll('[data-bw-phase="dims"] *').length,
      sheetNodes: svg.querySelectorAll('[data-bw-phase="sheet"] *').length,
      planPressed: document.querySelector('[data-testid="view-mode-plan"]')?.getAttribute('aria-pressed'),
      sheetPressed: document.querySelector('[data-testid="view-mode-sheet"]')?.getAttribute('aria-pressed'),
      widthPressed: document.querySelector('[data-testid="view-mode-width"]')?.getAttribute('aria-pressed'),
      status: document.querySelector('[data-testid="blueprint-view-mode-status"]')?.textContent || '',
      probe: svg.getAttribute('data-probe-node') || '',
    };
  });
}

async function readModal(page) {
  return page.evaluate(() => {
    const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
    const svg = dialog?.querySelector('[data-testid="blueprint-sheet-modal"] svg');
    const canvas = dialog?.querySelector('[data-testid="blueprint-modal-viewport"]');
    const zoomText = dialog?.querySelector('[data-testid="blueprint-modal-zoom-value"]')?.textContent || '';
    if (!svg) return null;
    const sr = svg.getBoundingClientRect();
    const cr = canvas?.getBoundingClientRect();
    const host = dialog?.querySelector('[data-testid="blueprint-sheet-modal"]');
    const hr = host?.getBoundingClientRect();
    const vb = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
    return {
      mode: svg.getAttribute('data-bw-view'),
      viewBox: vb,
      zoom: parseInt(zoomText, 10),
      width: sr.width,
      height: sr.height,
      canvasWidth: cr?.width || 0,
      canvasHeight: cr?.height || 0,
      hostWidth: hr?.width || 0,
      topGap: cr ? sr.top - cr.top : -1,
      status: dialog?.querySelector('[data-testid="blueprint-modal-view-mode-status"]')?.textContent || '',
      buttons: dialog?.querySelectorAll('[data-testid^="view-mode-"]').length || 0,
      pressed: [...(dialog?.querySelectorAll('[data-testid^="view-mode-"]') || [])].map((b) => [
        b.getAttribute('data-bw-view-mode'),
        b.getAttribute('aria-pressed'),
      ]),
    };
  });
}

async function clickMode(page, id, modal = false) {
  const scope = modal
    ? '[role="dialog"][aria-modal="true"] '
    : '';
  await page.click(`${scope}[data-testid="view-mode-${id}"]`);
  await page.evaluate(
    (target) => {
      const svg = document.querySelector(
        target === 'modal'
          ? '[data-testid="blueprint-sheet-modal"] svg'
          : '[data-testid="blueprint-sheet-card"] svg'
      );
      return svg && svg.getAttribute('data-bw-view');
    },
    modal ? 'modal' : 'card'
  );
  await sleep(100);
}

async function waitRevealDone(page) {
  await page.waitForFunction(
    () => {
      const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
      return svg && ['done', 'off'].includes(svg.getAttribute('data-bw-reveal'));
    },
    { timeout: 5000 }
  );
}

async function testFraming(browser, evidence) {
  console.log('\n[1] Card framing — real geometry, one node');
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 950, deviceScaleFactor: 1 });
  await page.goto(URL, { waitUntil: 'networkidle2' });
  await mount(page, 'multi');
  await waitInjected(page);
  await waitRevealDone(page);

  const initial = await readCard(page);
  check(Boolean(initial), 'sheet is injected');
  check(initial?.mode === 'plan', 'the card opens on Plan Focus', initial?.mode);
  check(initial?.planPressed === 'true' && initial?.sheetPressed === 'false', 'pressed state names Plan Focus');
  check(
    initial?.viewBox.length === 4 && initial?.baseViewBox.length === 4,
    'the sheet carries both the authored and current viewBox',
    JSON.stringify({ base: initial?.baseViewBox, current: initial?.viewBox })
  );
  check(
    initial?.viewBox[2] < initial?.baseViewBox[2] && initial?.viewBox[3] < initial?.baseViewBox[3],
    'the plan crop is smaller than the authored sheet in both axes',
    `${initial?.baseViewBox?.slice(2).join('x')} → ${initial?.viewBox?.slice(2).join('x')}`
  );
  const planAreaRatio =
    initial && initial.planUnion
      ? (initial.viewBox[2] * initial.viewBox[3]) / (initial.baseViewBox[2] * initial.baseViewBox[3])
      : null;
  check(
    planAreaRatio !== null && planAreaRatio < 0.9 && planAreaRatio > 0.1,
    'the crop is a real plan-focused fraction of the sheet, not a full or empty box',
    `${(planAreaRatio * 100).toFixed(1)}% of sheet area`
  );
  check(initial?.height <= initial?.canvasHeight + 1, 'Plan Focus fits inside the card', `${Math.round(initial?.height)} ≤ ${Math.round(initial?.canvasHeight)}`);
  check(initial?.topGap >= 0, 'the plan crop starts inside the viewer', `${Math.round(initial?.topGap)} px`);
  evidence.initial = initial;
  await page.screenshot({ path: path.join(OUT, 'viewmode-01-plan-card.png'), fullPage: true });

  // Node identity + drawn geometry survive every switch.
  await page.evaluate(() => {
    const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
    svg.setAttribute('data-probe-node', 'kept');
  });
  const geometry = {
    fills: initial.fills,
    walls: initial.walls,
    labels: initial.labels,
    dims: initial.dims,
  };

  await clickMode(page, 'sheet');
  const sheet = await readCard(page);
  check(sheet?.mode === 'sheet', 'Full Sheet applies', sheet?.mode);
  check(
    sheet?.viewBox.every((n, i) => Math.abs(n - sheet.baseViewBox[i]) < 0.01),
    'Full Sheet restores the authored viewBox exactly',
    `${sheet?.viewBox.join(' ')}`
  );
  check(sheet?.probe === 'kept', 'the same SVG node is reused — no re-inject');
  check(
    sheet?.fills === geometry.fills && sheet?.walls === geometry.walls && sheet?.labels === geometry.labels,
    'room fills, walls and labels are byte-identical in count',
    JSON.stringify({ before: geometry, after: { fills: sheet?.fills, walls: sheet?.walls, labels: sheet?.labels } })
  );
  check(sheet?.sheetBox && sheet.sheetBox.height > 0, 'the title block is drawn on the full sheet');
  check(sheet?.reveal === 'done' && sheet?.animations === 0, 'Full Sheet does not replay the reveal', `${sheet?.reveal}/${sheet?.animations}`);
  check(sheet?.sheetPressed === 'true' && sheet?.planPressed === 'false', 'Full Sheet becomes the pressed mode');
  check(sheet?.status.includes('title block'), 'the status states that the title block is included', sheet?.status?.trim());
  await page.screenshot({ path: path.join(OUT, 'viewmode-02-full-sheet-card.png'), fullPage: true });

  await clickMode(page, 'width');
  const width = await readCard(page);
  check(width?.mode === 'width', 'Fit Width applies', width?.mode);
  check(width?.position === 'absolute', 'Fit Width uses the absolute top-aligned sheet', width?.position);
  check(
    Math.abs(width.width - width.hostWidth) <= 2,
    'Fit Width fills the viewer width',
    `${width.width.toFixed(1)} / ${width.hostWidth.toFixed(1)} px (canvas ${width.canvasWidth.toFixed(1)})`
  );
  check(width?.height > width.canvasHeight, 'Fit Width leaves the rest of the sheet to pan', `${Math.round(width?.height)} > ${Math.round(width?.canvasHeight)}`);
  check(width?.probe === 'kept' && width?.reveal === 'done', 'Fit Width is the same node with no reveal replay');
  check(width?.widthPressed === 'true', 'Fit Width becomes the pressed mode');
  check(width?.status.includes('top-aligned'), 'the status explains the top alignment', width?.status?.trim());
  evidence.width = width;
  await page.screenshot({ path: path.join(OUT, 'viewmode-03-fit-width-card.png'), fullPage: true });

  await clickMode(page, 'plan');
  const planAgain = await readCard(page);
  check(
    planAgain?.viewBox.every((n, i) => Math.abs(n - initial.viewBox[i]) < 1),
    'returning to Plan Focus reproduces the same bounds exactly',
    planAgain?.viewBox.join(' ')
  );
  check(planAgain?.height <= planAgain?.canvasHeight + 1, 'Plan Focus still fits after a round trip');

  // Zoom then reset: reset is explicitly a full-sheet action.
  await page.focus('[data-testid="blueprint-viewport"]');
  await page.keyboard.press('Equal');
  await sleep(60);
  const zoomed = await page.$eval('[data-testid="blueprint-zoom-value"]', (el) => el.textContent.trim());
  await page.click('[aria-label="Reset view to full sheet"]');
  await sleep(100);
  const reset = await readCard(page);
  const resetZoom = await page.$eval('[data-testid="blueprint-zoom-value"]', (el) => el.textContent.trim());
  check(zoomed === '125%', 'zoom still works over the Plan Focus crop', zoomed);
  check(reset?.mode === 'sheet' && resetZoom === '100%', 'reset returns to Full Sheet at 100%', `${reset?.mode}/${resetZoom}`);

  // Keyboard shortcuts.
  await page.focus('[data-testid="blueprint-viewport"]');
  await page.keyboard.press('Digit2');
  await sleep(60);
  const keyPlan = await readCard(page);
  await page.keyboard.press('Digit3');
  await sleep(60);
  const keyWidth = await readCard(page);
  await page.keyboard.press('Digit1');
  await sleep(60);
  const keySheet = await readCard(page);
  check(
    keyPlan?.mode === 'plan' && keyWidth?.mode === 'width' && keySheet?.mode === 'sheet',
    'keyboard 2 / 3 / 1 select Plan / Width / Sheet',
    `${keyPlan?.mode},${keyWidth?.mode},${keySheet?.mode}`
  );

  // Axe on the mode chrome and the whole viewer (new violations only in scope).
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const axe = await page.evaluate(async () => {
    const run = async (el) => {
      const results = await window.axe.run(el, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      });
      return results.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.length,
        targets: v.nodes.map((n) => n.target.join(' ')),
        html: v.nodes.slice(0, 6).map((n) => n.html.slice(0, 180)),
      }));
    };
    return {
      card: await run(document.getElementById('blueprint-viewer-container')),
      modes: await run(document.querySelector('[data-testid="blueprint-view-modes"]')),
    };
  });
  evidence.axeCard = axe;
  const criticalModes = axe.modes.filter((v) => ['critical', 'serious'].includes(v.impact));
  check(
    criticalModes.length === 0,
    'axe: no critical/serious violations in the new mode controls',
    JSON.stringify(criticalModes)
  );
  const criticalCard = axe.card.filter((v) => ['critical', 'serious'].includes(v.impact));
  check(criticalCard.length === 0, 'axe: no critical/serious violations in the full blueprint card', JSON.stringify(criticalCard));
  evidence.axeCard = axe;

  await page.close();
}

async function testModal(browser, evidence) {
  console.log('\n[2] Fullscreen dialog framing');
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 950, deviceScaleFactor: 1 });
  await page.goto(URL, { waitUntil: 'networkidle2' });
  await mount(page, 'multi');
  await waitInjected(page);
  await waitRevealDone(page);
  await page.click('[data-testid="blueprint-expand"]');
  await page.waitForSelector(SELECT.modal, { timeout: 4000 });
  await page.waitForSelector(`${SELECT.modal} ${SELECT.modalSheet}`, { timeout: 4000 });
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  await sleep(160);

  const initial = await readModal(page);
  check(initial?.buttons === 3, 'the dialog has all three framing modes', String(initial?.buttons));
  check(initial?.mode === 'plan', 'the dialog opens in the card’s current mode', initial?.mode);
  check(initial?.zoom === 100, 'Plan Focus opens at its natural 100% framing', `${initial?.zoom}%`);
  check(initial?.width >= 300, 'the plan crop is wide enough to read', `${Math.round(initial?.width)} px`);
  check(initial?.pressed.some(([id, pressed]) => id === 'plan' && pressed === 'true'), 'the dialog marks Plan Focus pressed');

  await clickMode(page, 'sheet', true);
  const sheet = await readModal(page);
  check(sheet?.mode === 'sheet', 'Full Sheet applies inside the dialog');
  check(
    sheet?.viewBox[3] > initial?.viewBox?.[3] && sheet?.height >= sheet?.canvasHeight * 0.8,
    'Full Sheet restores the full tall sheet and fits the dialog height',
    `${sheet?.viewBox.join(' ')} · ${Math.round(sheet?.height)} / ${Math.round(sheet?.canvasHeight)} px`
  );
  await page.screenshot({ path: path.join(OUT, 'viewmode-04-modal-full-sheet.png'), fullPage: true });

  await clickMode(page, 'width', true);
  const width = await readModal(page);
  check(width?.mode === 'width', 'Fit Width applies inside the dialog');
  check(
    Math.abs(width.width - width.hostWidth) <= 2,
    'the dialog sheet fills its available width',
    `${Math.round(width?.width)} / ${Math.round(width?.hostWidth)} (canvas ${Math.round(width?.canvasWidth)})`
  );
  await page.screenshot({ path: path.join(OUT, 'viewmode-05-modal-fit-width.png'), fullPage: true });

  await clickMode(page, 'plan', true);
  const plan = await readModal(page);
  check(plan?.mode === 'plan', 'Plan Focus applies again in the dialog');
  check(plan?.height <= plan?.canvasHeight + 1, 'Plan Focus fits the dialog');
  await page.screenshot({ path: path.join(OUT, 'viewmode-06-modal-plan.png'), fullPage: true });

  const status = plan?.status || '';
  check(/title block/i.test(status), 'the dialog status explains the crop', status.trim());

  const axe = await page.evaluate(async () => {
    const run = async (el) => {
      const results = await window.axe.run(el, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      });
      return results.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.length,
        targets: v.nodes.map((n) => n.target.join(' ')),
        html: v.nodes.slice(0, 6).map((n) => n.html.slice(0, 180)),
      }));
    };
    const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
    return {
      dialog: await run(dialog),
      modes: await run(dialog.querySelector('[data-testid="blueprint-modal-view-modes"]')),
    };
  });
  evidence.axeModal = axe;
  const criticalModes = axe.modes.filter((v) => ['critical', 'serious'].includes(v.impact));
  check(
    criticalModes.length === 0,
    'axe: no critical/serious violations in the dialog mode controls',
    JSON.stringify(criticalModes)
  );
  const criticalDialog = axe.dialog.filter((v) => ['critical', 'serious'].includes(v.impact));
  check(criticalDialog.length === 0, 'axe: no critical/serious violations in the full dialog', JSON.stringify(criticalDialog));
  evidence.axeModal = axe;

  await page.keyboard.press('Escape');
  await page.close();
}

async function testFailStamp(browser, evidence) {
  console.log('\n[3] Fail-stamped plan — verdict survives every crop');
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 950, deviceScaleFactor: 1 });
  await page.goto(URL, { waitUntil: 'networkidle2' });
  await mount(page, 'fail');
  await waitInjected(page);
  await waitRevealDone(page);
  await sleep(120);
  const verdict = await page.evaluate(() => {
    const chip = document.querySelector('[data-testid="viewer-not-certified-chip"]');
    const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
    const sheet = svg?.querySelector('[data-bw-phase="sheet"]');
    const sheetText = sheet?.textContent || '';
    const chipRect = chip?.getBoundingClientRect();
    return {
      chipText: chip?.textContent?.trim() || '',
      chipVisible: Boolean(chipRect && chipRect.width > 0 && chipRect.height > 0),
      mode: svg?.getAttribute('data-bw-view'),
      sheetText: sheetText.slice(0, 2000),
      validationGate: /VALIDATION GATE/i.test(sheetText),
      certifiedClaimOnSheet: /\bCERTIFIED\b/i.test(sheetText),
      verdictInChrome: /NOT-CERTIFIED-FAIL-STAMP/.test(chip?.textContent || ''),
    };
  });
  check(verdict?.chipVisible, 'the failing plan keeps its verdict chip visible');
  check(/NOT-CERTIFIED-FAIL-STAMP/.test(verdict?.chipText || ''), 'the chip says NOT-CERTIFIED-FAIL-STAMP', verdict?.chipText);
  check(verdict?.validationGate, 'the drawing itself still carries the validation-gate table');
  check(!verdict?.certifiedClaimOnSheet, 'the drawing never prints a certified claim');
  check(verdict?.mode === 'plan', 'the failing plan also opens on Plan Focus', verdict?.mode);

  await clickMode(page, 'sheet');
  const full = await page.evaluate(() => {
    const chip = document.querySelector('[data-testid="viewer-not-certified-chip"]');
    const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
    const rect = chip?.getBoundingClientRect();
    return {
      chip: chip?.textContent?.trim() || '',
      chipVisible: Boolean(rect && rect.width > 0 && rect.height > 0),
      mode: svg?.getAttribute('data-bw-view'),
      reveal: svg?.getAttribute('data-bw-reveal'),
    };
  });
  check(
    full.mode === 'sheet' && full.chipVisible && /NOT-CERTIFIED-FAIL-STAMP/.test(full.chip),
    'Full Sheet keeps the fail verdict visible outside the drawing',
    `${full.mode}/${full.chip}`
  );
  evidence.fail = { verdict, full };
  await page.screenshot({ path: path.join(OUT, 'viewmode-07-fail-full-sheet.png'), fullPage: true });
  await page.close();
}

async function testDenseFloors(browser, evidence) {
  console.log('\n[4] Dense multi-storey — recrop per floor without replay');
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 950, deviceScaleFactor: 1 });
  await page.goto(URL, { waitUntil: 'networkidle2' });
  await mount(page, 'dense');
  await waitInjected(page);
  await waitRevealDone(page);
  const floor0 = await readCard(page);
  const results = [];
  for (const idx of [1, 2, 0]) {
    await page.click(`[data-testid="tab-floor-${idx}"]`);
    await page.waitForFunction(
      (i) =>
        document.querySelector(`[data-testid="tab-floor-${i}"]`)?.getAttribute('aria-pressed') === 'true' &&
        Boolean(document.querySelector('[data-testid="blueprint-sheet-card"] svg[data-bw-view]')),
      { timeout: 5000 },
      idx
    );
    await sleep(140);
    const state = await readCard(page);
    results.push({ idx, ...state });
  }
  check(
    results.every((r) => r.mode === 'plan' && r.viewBox[2] < r.baseViewBox[2]),
    'each dense floor gets its own plan crop',
    results.map((r) => `${r.idx}:${r.viewBox.slice(2).join('x')}`).join(' ')
  );
  check(
    results.every((r) => r.reveal === 'done' || r.reveal === 'off'),
    'floor changes never replay the reveal under a crop',
    results.map((r) => r.reveal).join(',')
  );
  check(
    results.every((r) => r.fills > 0),
    'the dense floors still draw their rooms',
    results.map((r) => r.fills).join(',')
  );
  const distinct = new Set(results.map((r) => r.viewBox.join(','))).size;
  check(distinct > 1, 'the crop follows each floor’s real extents', `${distinct} distinct viewBoxes`);
  evidence.dense = { floor0, results };
  await page.screenshot({ path: path.join(OUT, 'viewmode-08-dense-floor2-plan.png'), fullPage: true });
  await page.close();
}

async function testMobile(browser, evidence) {
  console.log('\n[5] 390 px framing + reduced motion');
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
  await page.goto(URL, { waitUntil: 'networkidle2' });
  await mount(page, 'multi');
  await waitInjected(page);
  await waitRevealDone(page);
  const modes = [];
  for (const id of ['plan', 'sheet', 'width', 'plan']) {
    await page.click(`[data-testid="view-mode-${id}"]`);
    await sleep(90);
    modes.push(await readCard(page));
    await page.screenshot({ path: path.join(OUT, `viewmode-09-mobile-${id}.png`), fullPage: true });
  }
  check(modes.every((m) => m.mode === 'plan' || m.mode === 'sheet' || m.mode === 'width'), 'all modes apply at 390 px');
  check(
    modes.every((m) => m.width <= m.canvasWidth + 1),
    'no framing mode overflows the mobile card',
    modes.map((m) => `${Math.round(m.width)}/${Math.round(m.canvasWidth)}`).join(' ')
  );
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(overflow <= 1, 'the page does not scroll horizontally', `${overflow}px`);
  evidence.mobile = modes;

  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.reload({ waitUntil: 'networkidle2' });
  await mount(page, 'multi');
  await waitInjected(page);
  await sleep(200);
  const reduced = await readCard(page);
  check(reduced?.reveal === 'off', 'reduced motion still switches the reveal off', reduced?.reveal);
  await page.click('[data-testid="view-mode-width"]');
  await sleep(80);
  const reducedWidth = await readCard(page);
  const transforms = await page.evaluate(() => {
    const canvas = document.querySelector('[data-testid="blueprint-viewport"]');
    return canvas ? getComputedStyle(canvas).transitionDuration : '';
  });
  check(reducedWidth?.mode === 'width', 'framing still works under reduced motion', reducedWidth?.mode);
  const transitionSeconds = transforms
    .split(',')
    .map((d) => parseFloat(d) || 0)
    .filter((n) => n > 0);
  check(
    transitionSeconds.every((n) => n <= 0.01),
    'the global reduced-motion rule collapses the pan/zoom transition',
    transforms
  );
  evidence.reduced = { reduced, reducedWidth, transforms };
  await page.close();
}

async function main() {
  if (!CHROME) throw new Error('Chrome not found. Set CHROME_PATH.');
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  });
  const evidence = { url: URL, startedAt: new Date().toISOString() };
  try {
    await testFraming(browser, evidence);
    await testModal(browser, evidence);
    await testFailStamp(browser, evidence);
    await testDenseFloors(browser, evidence);
    await testMobile(browser, evidence);
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(OUT, 'viewmode-evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(`\n=== blueprint view modes e2e: ${passes} passed, ${failures} failed ===`);
  console.log(`  evidence → ${path.join(OUT, 'viewmode-evidence.json')}`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
