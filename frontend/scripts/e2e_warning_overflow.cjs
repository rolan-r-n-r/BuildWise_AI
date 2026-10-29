#!/usr/bin/env node
/**
 * e2e_warning_overflow.cjs — containment pin + before/after captures.
 * ==================================================================
 * Renders the warning surface on the canonical 55-warning fixture and measures
 * real layout in Chrome at 390 / 768 / 1024 / 1280 / 1440:
 *
 *   AFTER   WarningReportView (tiered, wrapped): zero horizontal spill inside
 *           the section, inside every row container, and in the document.
 *   BEFORE  the removed rendering (one raw line per message + one flex row per
 *           relaxation with the 200-char rationale as a shrink-0 chip) is
 *           reconstructed from the same fixture. It is measured, not asserted:
 *           the capture documents the defect and is labelled as reconstructed.
 *
 * Screenshots (4 widths each) are written to
 * docs_ignore/qa-audit/warning-overflow/{before,after}-<width>.png.
 *
 * Usage: node scripts/e2e_warning_overflow.cjs
 * Env:   E2E_URL (default http://localhost:5173/app), CHROME_PATH
 */
const fs = require('fs');
const path = require('path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://localhost:5173/app';
const WIDTHS = [390, 768, 1024, 1280, 1440];
const CAPTURE_WIDTHS = [390, 768, 1024, 1440];
const OUT_DIR = path.resolve(ROOT, '..', 'docs_ignore', 'qa-audit', 'warning-overflow');
const FIXTURE = path.join(ROOT, 'src', 'test-fixtures', 'plan_noncertified_55.json');

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);

function resolveChrome() {
  for (const p of CHROME_CANDIDATES) {
    try {
      if (fs.existsSync(p)) return p;
    } catch (e) {
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

const escapeHtml = (s) =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

/** The rendering this stage replaced, rebuilt from the same fixture. */
function legacyMarkup(fixture) {
  const warnings = fixture.warnings
    .map(
      (w) => `
      <li class="flex items-start gap-2 text-[12px] leading-snug text-[var(--text-2)]">
        <span class="mt-1.5 w-1 h-1 rounded-full shrink-0 bg-[var(--semantic-red)]"></span>
        <span>${escapeHtml(w)}</span>
      </li>`,
    )
    .join('');
  const relaxations = fixture.relaxations
    .map(
      (r) => `
      <div class="p-1.5 rounded-[6px] bg-amber-500/10 text-[11px] flex items-center justify-between gap-2">
        <span class="font-medium text-amber-900 dark:text-amber-200 truncate">
          ${escapeHtml(r.room)}: <code class="font-mono text-[10px] font-semibold">${escapeHtml(r.rule_id)}</code>
        </span>
        <span class="text-[10px] font-mono px-1.5 rounded bg-amber-500/20 text-amber-800 dark:text-amber-200 shrink-0">
          ${escapeHtml(r.rationale)}
        </span>
      </div>`,
    )
    .join('');
  return `
  <section data-testid="legacy-warning-wall" class="mt-2.5 rounded-[12px] border border-rose-500/30 bg-rose-500/10 p-3 space-y-2">
    <div class="flex items-center gap-2 flex-wrap">
      <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-600 text-white">FAIL stamp</span>
      <span class="text-[13px] font-semibold text-[var(--text-1)]">Proportion / programme non-compliance (${fixture.warnings.length})</span>
    </div>
    <ul class="space-y-1.5 pl-6">${warnings}</ul>
    <div class="space-y-1">
      <div class="flex items-center justify-between text-[11px] font-semibold text-amber-800 dark:text-amber-300">
        <span>Applied Relaxations (${fixture.relaxations.length})</span>
        <span class="font-normal text-[10px] text-[var(--text-3)]">Bounded Deg-1 Pragmatic Adjustments</span>
      </div>
      ${relaxations}
    </div>
  </section>`;
}

function measure() {
  const harness = document.getElementById('harness');
  const section = harness ? harness.firstElementChild : null;
  const rowSelector = [
    '[data-testid="warning-row"]',
    '[data-testid="relaxation-room"]',
    '[data-testid="relaxation-item"]',
    '[data-testid="full-message"]',
    '[data-testid="operations-list"] li',
  ].join(',');
  const rows = Array.from(document.querySelectorAll(rowSelector));
  const spill = rows
    .filter((el) => el.scrollWidth > el.clientWidth + 1)
    .map((el) => ({
      testid: el.getAttribute('data-testid'),
      over: el.scrollWidth - el.clientWidth,
      text: (el.textContent || '').replace(/\s+/g, ' ').slice(0, 70),
    }));
  // Anything whose painted right edge escapes the section is spill even when
  // its own scrollWidth looks fine (unbroken flex children can paint outside).
  const bounds = section ? section.getBoundingClientRect() : null;
  const escaped = bounds
    ? Array.from(section.querySelectorAll('*'))
        .filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.right > bounds.right + 1;
        })
        .slice(0, 5)
        .map((el) => ({
          tag: el.tagName,
          cls: String(el.className).slice(0, 48),
          over: Math.round(el.getBoundingClientRect().right - bounds.right),
        }))
    : [];
  return {
    sectionOverflow: section ? section.scrollWidth - section.clientWidth : null,
    documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
    rowCount: rows.length,
    rowSpill: spill,
    escaped,
  };
}

async function main() {
  const fixture = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  if (fixture.warnings.length !== 55) {
    throw new Error(`canonical fixture changed: ${fixture.warnings.length} warnings`);
  }
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const { createServer } = await import('vite');
  const server = await createServer({
    root: ROOT,
    logLevel: 'error',
    appType: 'custom',
    server: { middlewareMode: true },
  });

  let browser;
  try {
    const { WarningReportView } = await server.ssrLoadModule(
      '/src/components/report/WarningReportView.tsx',
    );
    const props = {
      warnings: fixture.warnings,
      relaxations: fixture.relaxations,
      planVerdict: fixture.plan_verdict,
    };
    // Containment is measured on the widest state (every drawer open); the
    // screenshots show the default state a user actually lands on.
    const afterMarkup = renderToStaticMarkup(
      React.createElement(WarningReportView, { ...props, expandAll: true }),
    );
    const afterDefaultMarkup = renderToStaticMarkup(
      React.createElement(WarningReportView, props),
    );
    const beforeMarkup = legacyMarkup(fixture);

    browser = await puppeteer.launch({
      executablePath: resolveChrome(),
      headless: 'new',
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    });
    const page = await browser.newPage();
    page.setDefaultTimeout(60000);
    await page.goto(URL, { waitUntil: 'networkidle2' });
    await page.waitForSelector('body');

    const results = {};
    for (const [mode, markup] of [
      ['before', beforeMarkup],
      ['after', afterMarkup],
    ]) {
      results[mode] = {};
      for (const width of WIDTHS) {
        await page.setViewport({ width, height: 1600, deviceScaleFactor: 1 });
        await page.evaluate((html) => {
          document.body.innerHTML = `<div id="harness" style="width:100%;padding:8px;box-sizing:border-box">${html}</div>`;
          window.scrollTo(0, 0);
        }, markup);
        await new Promise((r) => setTimeout(r, 200));
        const m = await page.evaluate(measure);
        results[mode][width] = m;

        if (CAPTURE_WIDTHS.includes(width)) {
          if (mode === 'after') {
            await page.evaluate((html) => {
              document.body.innerHTML = `<div id="harness" style="width:100%;padding:8px;box-sizing:border-box">${html}</div>`;
              window.scrollTo(0, 0);
            }, afterDefaultMarkup);
            await new Promise((r) => setTimeout(r, 150));
          }
          const file = path.join(OUT_DIR, `${mode}-${width}.png`);
          await page.screenshot({ path: file });
        }

        if (mode === 'after') {
          check(
            m.sectionOverflow !== null && m.sectionOverflow <= 0,
            `${width}px: the warning section has no horizontal overflow`,
            String(m.sectionOverflow),
          );
          check(
            m.documentOverflow <= 0,
            `${width}px: the page does not scroll horizontally`,
            String(m.documentOverflow),
          );
          check(
            m.rowSpill.length === 0,
            `${width}px: every row container wraps inside its card (${m.rowCount} rows)`,
            m.rowSpill.map((s) => `${s.testid} +${s.over}px "${s.text}"`).join(' | '),
          );
          check(
            m.escaped.length === 0,
            `${width}px: no element paints past the section edge`,
            m.escaped.map((e) => `${e.tag}.${e.cls} +${e.over}px`).join(' | '),
          );
        }
      }
    }

    console.log('\n[before] reconstructed legacy rendering (not asserted):');
    for (const width of WIDTHS) {
      const m = results.before[width];
      console.log(
        `  ${width}px  section +${m.sectionOverflow}px  rows spilling ${m.rowSpill.length}/${m.rowCount}  widest +${
          m.rowSpill.reduce((n, s) => Math.max(n, s.over), 0)
        }px  document +${m.documentOverflow}px`,
      );
    }
    console.log('\n[after] tiered surface:');
    for (const width of WIDTHS) {
      const m = results.after[width];
      console.log(
        `  ${width}px  section +${m.sectionOverflow}px  rows spilling ${m.rowSpill.length}/${m.rowCount}  document +${m.documentOverflow}px`,
      );
    }
    console.log(`\nscreenshots: ${OUT_DIR}`);
  } finally {
    if (browser) await browser.close();
    await server.close();
  }

  console.log(`\n${passes} passed, ${failures} failed`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
