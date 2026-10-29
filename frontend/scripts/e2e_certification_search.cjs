#!/usr/bin/env node
/**
 * e2e_certification_search.cjs — browser proof for the T2 certification-search case.
 *
 * Mounts the real warning surface + advisor over a live 12x18 m / 129.6 m² /
 * G+4 T2 solve at 1280 and 390, checks the strategy chip and grouped rows, then
 * applies the service-row alternative through the real API. The S2 single-unit
 * alternative is expected to be NOT-CERTIFIED-FAIL-STAMP while its V2 kitchen
 * has no qualifying exterior window; the proof asserts that honest verdict and
 * its disclosed daylight reason rather than promising a certificate.
 *
 * Usage: node scripts/e2e_certification_search.cjs
 * Env:   E2E_URL (default http://localhost:5173/app), CHROME_PATH
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://localhost:5173/app';
const OUT = path.resolve(ROOT, '..', 'docs_ignore', 'qa-audit', 'certification-search');
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

const read = () => {
  const root = document.querySelector('[data-testid="strategy-proof"]');
  const cert = document.querySelector('[data-testid="strategy-proof-certificate"]');
  const chain = document.querySelector('[data-testid="strategy-chain"]');
  return {
    phase: root?.getAttribute('data-phase') ?? '',
    selected: chain?.getAttribute('data-selected') ?? '',
    chainRows: Array.from(document.querySelectorAll('[data-testid="strategy-chain-row"]')).map((row) => ({
      id: row.getAttribute('data-strategy'),
      status: row.getAttribute('data-status'),
      text: row.textContent ?? '',
    })),
    summary: document.querySelector('[data-testid="warning-summary"]')?.textContent ?? '',
    truth: (() => {
      const banner = document.querySelector('[data-testid="plan-warnings-banner"]');
      return {
        cert: Number(banner?.getAttribute('data-certificate-failure-count') ?? -1),
        listed: Number(banner?.getAttribute('data-listed-deviation-count') ?? -1),
        breaches: Number(banner?.getAttribute('data-unresolved-breach-count') ?? -1),
      };
    })(),
    t1Rows: document.querySelectorAll('[data-testid="warning-row"]').length,
    advisorCounts: document.querySelector('[data-testid="advisor-counts"]')?.textContent ?? '',
    failureRows: Array.from(
      document.querySelectorAll('[data-testid="certificate-failure-row"]'),
    ).map((row) => row.textContent ?? ''),
    certificate: {
      generation: cert?.getAttribute('data-generation') ?? '',
      verdict: cert?.getAttribute('data-verdict') ?? '',
      failures: cert?.getAttribute('data-failures') ?? '',
      warnings: cert?.getAttribute('data-warnings') ?? '',
      geometry: cert?.getAttribute('data-geometry') ?? '',
    },
    serviceCard: (() => {
      const card = document.querySelector('[data-testid="remediation-card"][data-option="service_row"]');
      return card
        ? {
            current: card.getAttribute('data-current'),
            verdict: card.getAttribute('data-verdict'),
            failures: card.getAttribute('data-failures'),
            warnings: card.getAttribute('data-warnings'),
            plate: card.getAttribute('data-plate'),
          }
        : null;
    })(),
    singleUnitCard: (() => {
      const card = document.querySelector('[data-testid="remediation-card"][data-option="single_unit"]');
      const button = document.querySelector('[data-testid="apply-single_unit"]');
      return card
        ? {
            current: card.getAttribute('data-current'),
            verdict: card.getAttribute('data-verdict'),
            failures: card.getAttribute('data-failures'),
            warnings: card.getAttribute('data-warnings'),
            confirmPresent: Boolean(document.querySelector('[data-testid="confirm-single_unit"]')),
            buttonDisabled: Boolean(button && button.disabled),
          }
        : null;
    })(),
    docOverflow: document.documentElement.scrollWidth - window.innerWidth,
    proofOverflow:
      (root?.scrollWidth ?? 0) - (root?.clientWidth ?? 0),
  };
};

async function click(page, selector) {
  await page.evaluate((sel) => {
    document.querySelector(sel)?.click();
  }, selector);
  await sleep(300);
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
  page.setDefaultTimeout(120000);
  try {
    await page.goto(URL, { waitUntil: 'networkidle2' });
    await page.evaluate(async () => {
      const harness = await import('/scripts/harness/certificationSearchMount.tsx');
      await harness.mountCertificationSearch();
    });
    await page.waitForSelector('[data-testid="strategy-proof"][data-phase="baseline"]');
    await page.waitForSelector('[data-testid="strategy-chain"]');
    await page.waitForSelector('[data-testid="warning-summary"]');
    await page.waitForSelector('[data-testid="remediation-card"][data-option="single_unit"]', {
      timeout: 60000,
    });
    await page.setViewport({ width: 1280, height: 1800, deviceScaleFactor: 1 });
    await sleep(800);

    let state = await page.evaluate(read);
    check(state.selected === 'S1', '1280: chain names the selected strategy', state.selected);
    check(state.chainRows.length === 2, '1280: chain shows S0 fail -> S1 certified', String(state.chainRows.length));
    check(
      state.chainRows.find((r) => r.id === 'S1')?.status === 'certified' &&
        /0 failure/.test(state.chainRows.find((r) => r.id === 'S1')?.text ?? ''),
      '1280: S1 reports its measured 0 certificate failures',
      state.chainRows.find((r) => r.id === 'S1')?.text?.slice(0, 140),
    );
    check(/not certified|NOT-CERTIFIED|fail/i.test(state.summary), '1280: verdict is exposed on the summary', state.summary.slice(0, 120));
    // Truth line: certificate failures from the certificate, listed
    // deviations and unresolved breaches from their own groups. The certified
    // T2 plan must print 0 failures beside its listed deviations.
    check(
      state.summary.includes(`Certificate failures: ${state.truth.cert}`) &&
        state.summary.includes(`Listed deviations: ${state.truth.listed}`) &&
        state.summary.includes(`Unresolved breaches: ${state.truth.breaches}`),
      '1280: summary equals the grouped truth counts',
      `${JSON.stringify(state.truth)} — ${state.summary.slice(0, 140)}`,
    );
    check(
      state.truth.cert === 0 && state.truth.listed > 0,
      '1280: certified plan prints 0 certificate failures beside its listed deviations',
      JSON.stringify(state.truth),
    );
    check(state.docOverflow <= 0 && state.proofOverflow <= 0, '1280: zero horizontal spill');
    check(
      Boolean(state.serviceCard) && state.serviceCard.current === 'true',
      '1280: the already-selected service row is labelled current and disabled',
      JSON.stringify(state.serviceCard),
    );
    check(
      Boolean(state.singleUnitCard) &&
        state.singleUnitCard.current === 'false' &&
        state.singleUnitCard.confirmPresent &&
        state.singleUnitCard.buttonDisabled,
      '1280: S2 requires an explicit dwelling-count confirmation',
      JSON.stringify(state.singleUnitCard),
    );
    await page.screenshot({ path: path.join(OUT, 't2-chain-1280.png') });

    await page.setViewport({ width: 390, height: 1600, deviceScaleFactor: 1 });
    await sleep(500);
    state = await page.evaluate(read);
    check(state.chainRows.length === 2, '390: every chain step remains visible', String(state.chainRows.length));
    check(state.docOverflow <= 0 && state.proofOverflow <= 0, '390: zero horizontal spill');
    await page.screenshot({ path: path.join(OUT, 't2-chain-390.png') });

    await page.setViewport({ width: 1280, height: 1800, deviceScaleFactor: 1 });
    await sleep(300);
    const before = await page.evaluate(read);
    await click(page, '[data-testid="confirm-checkbox-single_unit"]');
    state = await page.evaluate(read);
    check(
      state.singleUnitCard && state.singleUnitCard.buttonDisabled === false,
      'confirm tick enables the S2 apply button',
      JSON.stringify(state.singleUnitCard),
    );
    await click(page, '[data-testid="apply-single_unit"]');
    await page.waitForSelector('[data-testid="strategy-proof"][data-phase="applied"]', {
      timeout: 120000,
    });
    await sleep(900);
    const after = await page.evaluate(read);
    check(
      after.certificate.generation !== before.certificate.generation,
      'confirmed S2 apply produced a new generation token',
      `${before.certificate.generation} -> ${after.certificate.generation}`,
    );
    check(
      after.certificate.generation.endsWith('-SINGLE_UNIT-U1'),
      'new token names the single-unit plate',
      after.certificate.generation,
    );
    check(
      after.certificate.geometry !== before.certificate.geometry,
      'new plan has visibly different geometry',
      `${before.certificate.geometry.length} -> ${after.certificate.geometry.length} chars`,
    );
    check(
      after.certificate.failures === before.singleUnitCard?.failures,
      'post-apply failures equal the card dry-run',
      `${before.singleUnitCard?.failures} vs ${after.certificate.failures}`,
    );
    check(
      after.certificate.warnings === before.singleUnitCard?.warnings,
      'post-apply messages equal the card dry-run',
      `${before.singleUnitCard?.warnings} vs ${after.certificate.warnings}`,
    );
    check(
      after.certificate.verdict === 'NOT-CERTIFIED-FAIL-STAMP',
      'confirmed S2 alternative is honestly fail-stamped',
      after.certificate.verdict,
    );
    check(
      after.failureRows.some((row) => /kitchen has no exterior window/i.test(row)),
      'S2 fail stamp discloses the kitchen daylight reason',
      after.failureRows.join(' | ').slice(0, 240),
    );
    check(
      /Certificate failures:\s*1\b/.test(after.summary) &&
        /Unresolved breaches:\s*1\b/.test(after.summary),
      'UI counts the S2 failure once and keeps it unresolved',
      after.summary.slice(0, 140),
    );
    await page.screenshot({ path: path.join(OUT, 't2-after-single-unit-1280.png') });
    await page.setViewport({ width: 390, height: 1600, deviceScaleFactor: 1 });
    await sleep(500);
    state = await page.evaluate(read);
    check(state.docOverflow <= 0 && state.proofOverflow <= 0, '390 fail-stamped result: zero horizontal spill');
    await page.screenshot({ path: path.join(OUT, 't2-after-single-unit-390.png') });

    console.log(`\n${passes} passed, ${failures} failed`);
    console.log(`captures: ${OUT}`);
  } finally {
    await browser.close();
  }
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
