#!/usr/bin/env node
/**
 * e2e_warning_surface.cjs — browser proof on the canonical 55-warning fixture.
 *
 * Mounts the real warning surface + advisor, then at 1280 and 390 checks:
 *   summary -> expand the full verbatim list -> open the engine-operations log
 *   with zero horizontal spill.
 * Then applies "Add a storey" through the REAL engine and asserts the new
 * certificate equals the card's dry-run (3 failures / 73 messages).
 *
 * Usage: node scripts/e2e_warning_surface.cjs
 * Env:   E2E_URL (default http://localhost:5174/app), CHROME_PATH
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://localhost:5174/app';
const OUT = path.resolve(ROOT, '..', 'docs_ignore', 'qa-audit', 'warning-surface');
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

// The canonical fixture's certificate-owned counts.  The truth summary must
// keep them separate: 3 failures are not the 27 listed deviations, and the
// 7 unresolved breaches are what the fail stamp rests on.
const hasTruthCounts = (text) =>
  /Certificate failures:\s*3\b/.test(text) &&
  /Listed deviations:\s*27\b/.test(text) &&
  /Unresolved breaches:\s*7\b/.test(text);

const read = () => ({
  summary: document.querySelector('[data-testid="warning-summary"]')?.textContent ?? '',
  summaryDetail: document.querySelector('[data-testid="warning-summary-detail"]')?.textContent ?? '',
  advisorCounts: document.querySelector('[data-testid="advisor-counts"]')?.textContent ?? '',
  reasons: document.querySelectorAll('[data-testid="advisor-reasons"] li').length,
  rows: document.querySelectorAll('[data-testid="warning-row"]').length,
  fullMessages: document.querySelectorAll('[data-testid="full-message"]').length,
  fullListOpen: Boolean(document.querySelector('[data-testid="full-message-list"]')),
  operationsOpen: Boolean(document.querySelector('[data-testid="operations-list"]')),
  docOverflow: document.documentElement.scrollWidth - window.innerWidth,
  proofOverflow:
    (document.querySelector('[data-testid="warning-surface-proof"]')?.scrollWidth ?? 0) -
    (document.querySelector('[data-testid="warning-surface-proof"]')?.clientWidth ?? 0),
});

async function click(page, selector) {
  await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (el) el.click();
  }, selector);
  await sleep(250);
}

async function main() {
  if (!CHROME) throw new Error('Chrome not found. Set CHROME_PATH.');
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(90000);
  try {
    await page.goto(URL, { waitUntil: 'networkidle2' });
    await page.evaluate(async () => {
      const harness = await import('/scripts/harness/warningSurfaceMount.tsx');
      await harness.mountWarningSurface();
    });
    await page.waitForSelector('[data-testid="warning-surface-proof"][data-phase="baseline"]');
    await page.waitForSelector('[data-testid="warning-summary"]');
    await page.waitForSelector('[data-testid="advisor-counts"]');

    await page.setViewport({ width: 1280, height: 1600, deviceScaleFactor: 1 });
    await sleep(1200);

    let state = await page.evaluate(read);
    check(hasTruthCounts(state.summary), '1280: summary carries the three truth-label counts', state.summary.slice(0, 120));
    check(hasTruthCounts(state.advisorCounts), '1280: advisor counts agree with the grouped truth labels', state.advisorCounts.slice(0, 120));
    check(/55 engine messages/.test(state.summaryDetail), '1280: detail keeps the 55-message total', state.summaryDetail.slice(0, 120));
    check(state.reasons === 3, '1280: three deterministic blocking reasons', String(state.reasons));
    check(state.docOverflow <= 0 && state.proofOverflow <= 0, '1280: no horizontal spill');

    await click(page, '[data-testid="full-list-toggle"]');
    state = await page.evaluate(read);
    check(state.fullListOpen, '1280: full verbatim list opens');
    check(state.fullMessages === 55, '1280: all 55 raw lines are present', String(state.fullMessages));
    check(state.docOverflow <= 0 && state.proofOverflow <= 0, '1280: full list does not spill');

    await click(page, '[data-testid="operations-toggle"]');
    state = await page.evaluate(read);
    check(state.operationsOpen, '1280: engine operations log opens');
    await page.screenshot({ path: path.join(OUT, 'fixture-1280.png') });

    await page.setViewport({ width: 390, height: 1400, deviceScaleFactor: 1 });
    await sleep(500);
    state = await page.evaluate(read);
    check(hasTruthCounts(state.summary), '390: summary keeps the three truth-label counts', state.summary.slice(0, 120));
    check(/55 engine messages/.test(state.summaryDetail), '390: detail keeps the 55-message total', state.summaryDetail.slice(0, 120));
    check(state.fullMessages === 55, '390: expanded full list keeps all 55 lines');
    check(state.docOverflow <= 0 && state.proofOverflow <= 0, '390: no horizontal spill');
    await page.screenshot({ path: path.join(OUT, 'fixture-390.png') });

    // Apply "Add a storey" through the real engine.  The card appears only
    // after its engine dry-runs have measured the alternative.
    await page.setViewport({ width: 1280, height: 1600, deviceScaleFactor: 1 });
    await page.waitForSelector(
      '[data-testid="remediation-card"][data-option="add_storey"]',
      { timeout: 120000 },
    );
    await page.waitForFunction(() => {
      const card = document.querySelector(
        '[data-testid="remediation-card"][data-option="add_storey"]',
      );
      return Boolean(card && card.getAttribute('data-failures'));
    }, { timeout: 120000 });
    await sleep(300);
    const before = await page.evaluate(() => {
      const cert = document.querySelector('[data-testid="proof-certificate"]');
      const card = document.querySelector('[data-testid="remediation-card"][data-option="add_storey"]');
      return {
        generation: cert?.getAttribute('data-generation'),
        verdict: cert?.getAttribute('data-verdict'),
        failures: card?.getAttribute('data-failures'),
        warnings: card?.getAttribute('data-warnings'),
      };
    });
    check(Boolean(before.failures), 'card publishes its dry-run failures', JSON.stringify(before));
    await click(page, '[data-testid="apply-add_storey"]');
    await page.waitForSelector('[data-testid="warning-surface-proof"][data-phase="applied"]', { timeout: 120000 });
    await sleep(1500);
    const after = await page.evaluate(() => {
      const cert = document.querySelector('[data-testid="proof-certificate"]');
      return {
        generation: cert?.getAttribute('data-generation'),
        verdict: cert?.getAttribute('data-verdict'),
        failures: cert?.getAttribute('data-failures'),
        warnings: cert?.getAttribute('data-warnings'),
        text: cert?.textContent ?? '',
      };
    });
    check(after.generation !== before.generation, 'apply produced a new generation', `${before.generation} -> ${after.generation}`);
    check(after.verdict === 'NOT-CERTIFIED-FAIL-STAMP', 'new certificate verdict is shown', after.verdict);
    check(after.failures === before.failures, 'post-apply failures equal the dry-run', `${before.failures} vs ${after.failures}`);
    check(after.warnings === before.warnings, 'post-apply messages equal the dry-run', `${before.warnings} vs ${after.warnings}`);
    await page.screenshot({ path: path.join(OUT, 'after-apply-1280.png') });
  } finally {
    await browser.close();
  }
  console.log(`\n${passes} passed, ${failures} failed`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
