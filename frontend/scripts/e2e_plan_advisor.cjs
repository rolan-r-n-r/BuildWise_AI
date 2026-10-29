#!/usr/bin/env node
/**
 * e2e_plan_advisor.cjs — advisor OFF vs ON, measured in the real browser.
 * ======================================================================
 * Mounts the actual PlanAdvisorPanel in the running app (Vite dev server), with
 * the canonical 55-warning fixture and the engine's captured remediation
 * options:
 *
 *   OFF  the component is given the offline advisory response (no network).
 *   ON   the component calls the live advisory endpoint (Groq) itself.
 *
 * Both states must render the SAME cards, order and measured numbers. The
 * screenshot pair and the parity table are written to
 * docs_ignore/qa-audit/plan-advisor/.
 *
 * Usage: node scripts/e2e_plan_advisor.cjs
 * Env:   E2E_URL (default http://localhost:5173/app), CHROME_PATH
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://localhost:5173/app';
const OUT_DIR = path.resolve(ROOT, '..', 'docs_ignore', 'qa-audit', 'plan-advisor');
const PLAN_FIXTURE = path.join(ROOT, 'src', 'test-fixtures', 'plan_noncertified_55.json');

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);

function resolveChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch {
      /* ignore */
    }
  }
  throw new Error('Chrome not found. Set CHROME_PATH to the Chrome executable.');
}

let passes = 0;
let failures = 0;
function check(ok, label, detail) {
  if (ok) {
    passes += 1;
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

async function mount(page, mode) {
  await page.evaluate(async (mode) => {
    const harness = await import('/scripts/harness/advisorMount.tsx');
    await harness.mountAdvisorHarness({ mode });
  }, mode);
}

const readState = () =>
  document.querySelector('[data-testid="plan-advisor"]')
    ? (() => {
        const section = document.querySelector('[data-testid="plan-advisor"]');
        const cards = Array.from(document.querySelectorAll('[data-testid="remediation-card"]')).map((card) => ({
          option: card.getAttribute('data-option'),
          verdict: card.getAttribute('data-verdict'),
          failures: card.getAttribute('data-failures'),
          warnings: card.getAttribute('data-warnings'),
          plate: card.getAttribute('data-plate'),
        }));
        return {
          state: section.getAttribute('data-advisor-state'),
          optionsState: section.getAttribute('data-options-state'),
          cards,
          hasNarrative: Boolean(document.querySelector('[data-testid="advisor-narrative"]')),
          hasOffline: Boolean(document.querySelector('[data-testid="advisor-offline"]')),
          notes: document.querySelectorAll('[data-testid="advisor-option-note"]').length,
          overflow: section.scrollWidth - section.clientWidth,
          documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
        };
      })()
    : null;

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: resolveChrome(),
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(60000);
  try {
    await page.goto(URL, { waitUntil: 'networkidle2' });
    await page.waitForSelector('body');

    const results = {};
    for (const mode of ['off', 'on']) {
      await page.setViewport({ width: 1440, height: 1400, deviceScaleFactor: 1 });
      await mount(page, mode);
      await page.waitForSelector('[data-testid="plan-advisor"]');
      if (mode === 'on') {
        await page
          .waitForFunction(
            () =>
              document.querySelector('[data-testid="advisor-narrative"]') ||
              document.querySelector('[data-testid="advisor-offline"]'),
            { timeout: 30000 },
          )
          .catch(() => {});
      }
      await new Promise((r) => setTimeout(r, 300));
      const state = await page.evaluate(readState);
      results[mode] = state;

      check(state !== null, `${mode}: the advisor panel mounts`);
      check(state && state.optionsState === 'ready', `${mode}: dry-run options are ready`, state && state.optionsState);
      check(state && state.cards.length === 3, `${mode}: three measured options render`, state && String(state.cards.length));
      check(state && state.overflow <= 0 && state.documentOverflow <= 0, `${mode}: no horizontal overflow`);

      if (mode === 'off') {
        check(state && state.hasOffline && !state.hasNarrative, 'off: disclosure instead of narrative');
      } else {
        check(state && (state.hasNarrative || state.hasOffline), 'on: advisory resolves (narrative or disclosed fallback)');
      }

      await page.screenshot({ path: path.join(OUT_DIR, `advisor-${mode}-1440.png`) });

      await page.setViewport({ width: 390, height: 1200, deviceScaleFactor: 1 });
      await new Promise((r) => setTimeout(r, 250));
      const narrow = await page.evaluate(readState);
      check(narrow && narrow.overflow <= 0 && narrow.documentOverflow <= 0, `${mode}: 390px has no horizontal overflow`);
      await page.screenshot({ path: path.join(OUT_DIR, `advisor-${mode}-390.png`) });
    }

    const off = results.off;
    const on = results.on;
    check(
      JSON.stringify(off.cards) === JSON.stringify(on.cards),
      'advisor ON/OFF: identical options, order and measured numbers',
      JSON.stringify(on.cards),
    );
    check(typeof on.notes === 'number' && on.notes > 0, 'advisor ON: option wording renders beside cards', String(on.notes));

    const parity = [
      'option | off failures/messages/plate/verdict | on failures/messages/plate/verdict',
      ...off.cards.map((card, index) => {
        const other = on.cards[index] || {};
        return `${card.option} | ${card.failures}/${card.warnings}/${card.plate}/${card.verdict} | ${other.failures}/${other.warnings}/${other.plate}/${other.verdict}`;
      }),
    ].join('\n');
    fs.writeFileSync(path.join(OUT_DIR, 'advisor-parity.txt'), `${parity}\n`, 'utf8');
    console.log(`\n${parity}\n\ncaptures: ${OUT_DIR}`);
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
