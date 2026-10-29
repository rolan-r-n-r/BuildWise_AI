#!/usr/bin/env node
/**
 * e2e_certificate_truth.cjs — browser proof for certificate truth labels + plate sizing.
 *
 * Mounts the production WarningReportView + CertificatePanel over two live
 * 20 x 20 m solves at 1280 and 390:
 *
 *   t2  T2 apartment, 1 storey -> CERTIFIED, 0 certificate failures, 10
 *       listed relaxations. The certificate-failure group must be (0) and the
 *       listed-deviation group must carry the relaxations, NOT be counted as
 *       failures.
 *   t1  T1 single family, 1 storey -> NOT-CERTIFIED-FAIL-STAMP with 3
 *       certificate failures and 6 listed relaxations. The group counts must
 *       equal the payload's two different sources.
 *
 * It also pins the definition legend verbatim on both outcomes and captures
 * the screenshots the audit report links.
 *
 * Usage: node scripts/e2e_certificate_truth.cjs
 * Env:   E2E_URL (default http://localhost:5173/app), CHROME_PATH
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://localhost:5173/app';
const OUT = path.resolve(ROOT, '..', 'docs_ignore', 'qa-audit', 'certificate-truth');
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

const CERTIFIED_DEFINITION =
  'CERTIFIED = statutory/safety layers PASS + zero unlisted breaches + every quality deviation listed and inside its declared cap. NOT-CERTIFIED-FAIL-STAMP = statutory FAIL, unlisted breach, or beyond-cap deviation.';

let passes = 0;
let failures = 0;
function check(ok, label, detail) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
  ok ? (passes += 1) : (failures += 1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const read = () => {
  const root = document.querySelector('[data-testid="certificate-truth-proof"]');
  const chip = document.querySelector('[data-testid="plan-verdict"]');
  const certHeading = document.querySelector('[data-testid="certificate-failures-heading"]');
  const devHeading = document.querySelector('[data-testid="listed-deviations-group"] button');
  const def = document.querySelector('[data-testid="certified-definition"]');
  const summary = document.querySelector('[data-testid="warning-summary"]');
  const certList = document.querySelector('[data-testid="certificate-failures-list"]');
  return {
    phase: root?.getAttribute('data-phase') ?? '',
    verdict: root?.getAttribute('data-verdict') ?? '',
    rootFailures: Number(root?.getAttribute('data-cert-failures') ?? -1),
    rootListed: Number(root?.getAttribute('data-listed') ?? -1),
    chipVerdict: chip?.getAttribute('data-verdict') ?? '',
    chipText: (chip?.textContent ?? '').trim(),
    certHeading: (certHeading?.textContent ?? '').replace(/\s+/g, ' ').trim(),
    certRows: certList?.querySelectorAll('[data-testid="certificate-failure-row"]').length ?? -1,
    certListCount: Number(certList?.getAttribute('data-count') ?? -1),
    certEmpty: Boolean(document.querySelector('[data-testid="certificate-failures-empty"]')),
    devHeading: (devHeading?.textContent ?? '').replace(/\s+/g, ' ').trim(),
    summaryCert: Number(summary?.getAttribute('data-certificate-failures') ?? -1),
    summaryListed: Number(summary?.getAttribute('data-listed-deviations') ?? -1),
    definition: (def?.textContent ?? '').replace(/\s+/g, ' ').trim(),
    docOverflow: document.documentElement.scrollWidth - window.innerWidth,
    rootOverflow: (root?.scrollWidth ?? 0) - (root?.clientWidth ?? 0),
  };
};

function parseGroupCount(text, label) {
  const m = text.match(new RegExp(`${label}\\s*\\((\\d+)\\)`, 'i'));
  return m ? Number(m[1]) : -1;
}

async function mount(page, caseId) {
  await page.evaluate(async (id) => {
    const harness = await import('/scripts/harness/certificateTruthMount.tsx');
    await harness.mountCertificateTruth(id);
  }, caseId);
  await page.waitForFunction(
    (id) =>
      Boolean(
        document.querySelector(
          `[data-testid="certificate-truth-proof"][data-case="${id}"][data-phase="ready"]`,
        ),
      ),
    { timeout: 120000 },
    caseId,
  );
  await page.waitForSelector('[data-testid="certificate-panel"]', { timeout: 30000 });
  await page.waitForSelector('[data-testid="plan-verdict"]', { timeout: 30000 });
  await sleep(400);
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

    // ---------------------------------------------------------------- T2
    await page.setViewport({ width: 1280, height: 1800, deviceScaleFactor: 1 });
    await mount(page, 't2');
    let s = await page.evaluate(read);
    check(s.verdict === 'CERTIFIED', 'T2 1280: payload verdict is CERTIFIED', s.verdict);
    check(/VERIFIED & CERTIFIED/i.test(s.chipText), 'T2 1280: green verdict chip matches', s.chipText);
    check(
      s.rootFailures === 0 && s.certListCount === 0 && s.certRows === 0 && s.certEmpty,
      'T2 1280: CERTIFICATE FAILURES group is (0) with the empty row',
      `root=${s.rootFailures} list=${s.certListCount} rows=${s.certRows} empty=${s.certEmpty}`,
    );
    check(
      parseGroupCount(s.certHeading, 'CERTIFICATE FAILURES') === 0,
      'T2 1280: heading reads CERTIFICATE FAILURES (0)',
      s.certHeading,
    );
    check(
      s.rootListed > 0 && parseGroupCount(s.devHeading, 'LISTED DEVIATIONS') === s.rootListed,
      'T2 1280: LISTED DEVIATIONS heading equals the listed count, not the warning total',
      `${s.devHeading} / root=${s.rootListed}`,
    );
    check(
      s.summaryCert === 0 && s.summaryListed === s.rootListed,
      'T2 1280: summary carries the same two independent counts',
      `cert=${s.summaryCert} listed=${s.summaryListed}`,
    );
    check(
      s.definition === CERTIFIED_DEFINITION,
      'T2 1280: definition legend is printed verbatim',
      s.definition.slice(0, 80),
    );
    check(s.docOverflow <= 0 && s.rootOverflow <= 0, 'T2 1280: zero horizontal spill');
    await page.screenshot({ path: path.join(OUT, 't2-certified-1280.png'), fullPage: true });

    await page.setViewport({ width: 390, height: 1600, deviceScaleFactor: 1 });
    await sleep(500);
    s = await page.evaluate(read);
    check(/VERIFIED & CERTIFIED/i.test(s.chipText), 'T2 390: chip remains CERTIFIED', s.chipText);
    check(
      parseGroupCount(s.certHeading, 'CERTIFICATE FAILURES') === 0 && s.certRows === 0,
      'T2 390: failures group stays (0)',
      s.certHeading,
    );
    check(
      parseGroupCount(s.devHeading, 'LISTED DEVIATIONS') === s.rootListed && s.rootListed > 0,
      'T2 390: listed group keeps its own count',
      s.devHeading,
    );
    check(s.definition === CERTIFIED_DEFINITION, 'T2 390: legend remains verbatim');
    check(s.docOverflow <= 0 && s.rootOverflow <= 0, 'T2 390: zero horizontal spill');
    await page.screenshot({ path: path.join(OUT, 't2-certified-390.png'), fullPage: true });

    // ---------------------------------------------------------------- T1
    await page.setViewport({ width: 1280, height: 1800, deviceScaleFactor: 1 });
    await mount(page, 't1');
    s = await page.evaluate(read);
    check(
      s.verdict === 'NOT-CERTIFIED-FAIL-STAMP',
      'T1 1280: payload verdict is NOT-CERTIFIED-FAIL-STAMP',
      s.verdict,
    );
    check(/PLAN NOT CERTIFIED/i.test(s.chipText), 'T1 1280: red fail-stamp chip matches', s.chipText);
    // This fail-stamp carries ZERO certificate failures and 11 listed
    // deviations. That is the old contradiction inverted: the warning
    // total must never be printed as certificate failures.
    check(
      s.certListCount === s.rootFailures &&
        s.certRows === s.rootFailures &&
        (s.rootFailures > 0 || s.certEmpty),
      'T1 1280: failure rows equal the certificate source exactly (zero here)',
      `root=${s.rootFailures} list=${s.certListCount} rows=${s.certRows} empty=${s.certEmpty}`,
    );
    check(
      s.rootFailures === 0 && s.rootListed > 0,
      'T1 1280: listed deviations are NOT counted as certificate failures',
      `failures=${s.rootFailures} listed=${s.rootListed}`,
    );
    check(
      parseGroupCount(s.certHeading, 'CERTIFICATE FAILURES') === s.rootFailures,
      'T1 1280: heading equals the certificate failure count',
      s.certHeading,
    );
    check(
      s.rootListed > 0 && parseGroupCount(s.devHeading, 'LISTED DEVIATIONS') === s.rootListed,
      'T1 1280: listed deviations are a separate group with their own count',
      `${s.devHeading} / root=${s.rootListed}`,
    );
    check(
      s.summaryCert === s.rootFailures && s.summaryListed === s.rootListed,
      'T1 1280: summary derives failures and deviations independently',
      `cert=${s.summaryCert} listed=${s.summaryListed}`,
    );
    check(
      s.definition === CERTIFIED_DEFINITION,
      'T1 1280: the same definition legend prints on a fail-stamp',
      s.definition.slice(0, 80),
    );
    check(s.docOverflow <= 0 && s.rootOverflow <= 0, 'T1 1280: zero horizontal spill');
    await page.screenshot({ path: path.join(OUT, 't1-failstamp-1280.png'), fullPage: true });

    await page.setViewport({ width: 390, height: 1600, deviceScaleFactor: 1 });
    await sleep(500);
    s = await page.evaluate(read);
    check(/PLAN NOT CERTIFIED/i.test(s.chipText), 'T1 390: fail-stamp chip remains', s.chipText);
    check(
      parseGroupCount(s.certHeading, 'CERTIFICATE FAILURES') === s.rootFailures,
      'T1 390: failure count remains derived from the certificate',
      s.certHeading,
    );
    check(
      parseGroupCount(s.devHeading, 'LISTED DEVIATIONS') === s.rootListed,
      'T1 390: listed count remains separate',
      s.devHeading,
    );
    check(s.docOverflow <= 0 && s.rootOverflow <= 0, 'T1 390: zero horizontal spill');
    await page.screenshot({ path: path.join(OUT, 't1-failstamp-390.png'), fullPage: true });

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
