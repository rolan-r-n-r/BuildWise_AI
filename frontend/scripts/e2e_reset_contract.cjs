#!/usr/bin/env node
/**
 * e2e_reset_contract.cjs — browser pin for THE reset contract.
 * =============================================================
 * Walks the real funnel (trace -> analyze -> generate -> dirty the plan ->
 * reset) and fails unless reset is a TRUE reset:
 *
 *   BEFORE  the session has a boundary chip, an analysis report, a generated
 *           plan and a fired stale-plan guard.
 *   DIALOG  Reset is destructive: a confirmation opens and nothing is cleared
 *           until the user confirms.
 *   AFTER   pristine first-run state — no boundary in state, the map or the
 *           request; report/generator unmounted; default parameters; the
 *           report's stored data gone; the transient deep-link URL scrubbed;
 *           the map camera back at the default view; no stale guard.
 *   RELOAD  stays pristine (the URL cannot restore the reset site).
 *
 * Preferences (units here) must survive — reset clears data, not preferences.
 *
 * Usage: node scripts/e2e_reset_contract.cjs
 * Env:   E2E_URL   app URL (default starts on a shared-site deep link)
 *        CHROME_PATH
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');

const URL =
  process.env.E2E_URL ||
  'http://localhost:5173/app?lat=13.0500&lon=77.6200';
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

const results = [];
function check(ok, label, detail) {
  results.push({ ok, label, detail });
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clickByLabel(page, label) {
  return page.evaluate((needle) => {
    const btn = Array.from(document.querySelectorAll('button')).find(
      (b) => (b.textContent || '').includes(needle) && !b.disabled
    );
    if (!btn) return false;
    btn.click();
    return true;
  }, label);
}

/** Set a React-controlled range input and fire the event React listens to. */
async function setRange(page, selector, value) {
  return page.evaluate(
    (sel, v) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(el, String(v));
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    },
    selector,
    value
  );
}

const SNAPSHOT = () => ({
  boundaryChip: Boolean(document.querySelector('[data-testid="boundary-chip"]')),
  report: Boolean(document.querySelector('[role="dialog"][aria-label], .report-sheet-surface')),
  generator: Boolean(document.querySelector('[data-testid="floorplan-generator-card"]')),
  stale: Boolean(
    document.querySelector('[data-testid="stale-plan-chip"]') ||
      /Parameters changed/.test(document.body.innerText || '')
  ),
  area: document.querySelector('#area-input')?.value ?? null,
  coverage: document.querySelector('#coverage-input')?.value ?? null,
  storeys: document.querySelector('[data-testid="storeys-caption"]')?.textContent ?? null,
  brief: document.querySelector('#client-requirements-input')?.value ?? null,
  hash: window.location.hash,
  search: window.location.search,
  pathname: window.location.pathname,
  scrollKeys: Object.keys(sessionStorage).filter((k) => k.startsWith('bw.report.scroll.')),
  sectionsKey: localStorage.getItem('bw.report.sections.v1'),
  units: localStorage.getItem('buildwise.units'),
});

async function main() {
  console.log('=== E2E: reset contract ===');
  const browser = await puppeteer.launch({
    executablePath: resolveChrome(),
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1600,1000'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String((err && err.message) || err)));

  try {
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 });
    await page.waitForSelector('button[aria-label="Reset the site analysis"]', { timeout: 20000 });
    // A unit preference is seeded before the reset: it must SURVIVE (it is a
    // preference, not session data).
    await page.evaluate(() => localStorage.setItem('buildwise.units', 'imperial'));

    // Capture the FIRST-RUN camera (zoom / pitch / bearing). Reset must return
    // to exactly this view (the standard map auto-tilts at street zoom).
    const firstRunCamera = await page.evaluate(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      for (let i = 0; i < 40 && !window.__maplibreMap; i += 1) await sleep(100);
      const m = window.__maplibreMap;
      if (!m) return null;
      for (let i = 0; i < 40 && m.isMoving(); i += 1) await sleep(50);
      return {
        zoom: Number(m.getZoom().toFixed(1)),
        pitch: Math.round(m.getPitch()),
        bearing: Math.round(m.getBearing()),
      };
    });

    console.log('- capture: trace a preset rectangle from the linked pin');
    await clickByLabel(page, 'Select Location on Map to Begin');
    await page.waitForFunction(() => /Locate the site/.test(document.body.innerText), {
      timeout: 20000,
    });
    await clickByLabel(page, 'Trace boundary');
    await sleep(700);
    await page.click('[data-testid="trace-toolbar-presets"]');
    await page.waitForSelector('[data-testid="preset-menu"]', { timeout: 10000 });
    await page.click('[data-testid="preset-item-rect"]');
    await sleep(1200);
    // The preset seeds an OPEN ring in edit mode: close it, then pick a frontage
    // edge from the per-edge table (deterministic; no road-suggestion wait).
    const finished = await clickByLabel(page, 'Finish');
    check(finished, 'preset ring closed (Finish)');
    await page.waitForFunction(() => /Confirm the frontage/.test(document.body.innerText), {
      timeout: 30000,
    });
    await page.waitForSelector('[data-testid="edge-row-1"]', { timeout: 30000 });
    await page.click('[data-testid="edge-row-1"]');
    await page.waitForFunction(
      () => {
        const btn = Array.from(document.querySelectorAll('button')).find(
          (x) => (x.textContent || '').trim() === 'Review'
        );
        return Boolean(btn) && !btn.disabled;
      },
      { timeout: 30000 }
    );
    const reviewed = await clickByLabel(page, 'Review');
    check(reviewed, 'frontage picked and review reached');
    await page.waitForFunction(() => /Review boundary/.test(document.body.innerText), {
      timeout: 20000,
    });
    await clickByLabel(page, 'Use this boundary');
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll('button')).some(
          (b) => (b.textContent || '').includes('Run Site Feasibility Analysis') && !b.disabled
        ),
      { timeout: 20000 }
    );
    check(
      await page.evaluate(() => Boolean(document.querySelector('[data-testid="boundary-chip"]'))),
      'boundary committed (chip present before reset)'
    );

    console.log('- analyze + generate');
    await clickByLabel(page, 'Run Site Feasibility Analysis');
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll('button')).some((b) =>
          (b.textContent || '').includes('Cost & Plan')
        ),
      { timeout: 120000 }
    );
    await sleep(1200);
    await clickByLabel(page, 'Cost & Plan');
    await page.waitForSelector('[data-testid="floorplan-generator-card"]', { timeout: 20000 });
    const generated = await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll('button')).find((x) =>
        /Generate .*(Blueprint|Floor Plan)|Regenerate Blueprint/.test(x.textContent || '')
      );
      if (!b || b.disabled) return false;
      b.click();
      return true;
    });
    check(generated, 'generate button clicked');
    await page.waitForSelector('[data-testid="plan-verdict"]', { timeout: 180000 });
    check(true, 'plan generated (verdict rendered)');

    // Dirty the plan so the stale guard fires BEFORE reset: the guard must be
    // gone after it, not merely hidden behind an unmounted report.
    await setRange(page, '#coverage-input', 0.7);
    await page
      .waitForSelector('[data-testid="stale-plan-chip"]', { timeout: 10000 })
      .then(() => check(true, 'stale-plan guard fired before reset'))
      .catch(() =>
        check(
          false,
          'stale-plan guard fired before reset',
          'chip not found after a coverage change'
        )
      );

    const before = await page.evaluate(SNAPSHOT);
    check(before.boundaryChip, 'BEFORE: boundary chip present');
    check(before.report, 'BEFORE: report surface mounted');
    check(before.generator, 'BEFORE: generator mounted');
    check(before.stale, 'BEFORE: stale guard visible');
    check(before.hash === '#report', 'BEFORE: #report hash present', before.hash);
    check(/[?&]lat=/.test(before.search), 'BEFORE: deep-link lat present', before.search);

    // Close the report sheet so the header (and its Reset button) is reachable.
    await page.click('button[aria-label="Close report sheet"]');
    await sleep(400);

    console.log('- reset: destructive confirmation');
    await page.click('button[aria-label="Reset the site analysis"]');
    await page.waitForSelector('[data-testid="reset-confirm-dialog"]', { timeout: 10000 });
    const mid = await page.evaluate(SNAPSHOT);
    check(mid.boundaryChip, 'DIALOG: nothing is cleared before confirmation');
    await page.click('[data-testid="reset-confirm"]');
    await sleep(700);

    const after = await page.evaluate(SNAPSHOT);
    check(!after.boundaryChip, 'AFTER: boundary chip gone (no boundary in state)');
    check(!after.report, 'AFTER: report surface unmounted');
    check(!after.generator, 'AFTER: generator unmounted (its state is gone)');
    check(!after.stale, 'AFTER: stale guard cleared (and does not fire post-reset)');
    check(after.area === '2000', 'AFTER: plinth area at the 2,000 sq ft default', after.area);
    check(after.coverage === '0.6', 'AFTER: coverage at the 60% default', after.coverage);
    check(
      /Single level/.test(after.storeys || ''),
      'AFTER: storeys at the G default',
      after.storeys
    );
    check(!after.brief, 'AFTER: client requirements cleared', after.brief || '(empty)');
    check(after.hash === '', 'AFTER: #report hash removed', after.hash || '(none)');
    check(
      !/[?&]lat=/.test(after.search) && !/[?&]lon=/.test(after.search),
      'AFTER: deep-link coordinates removed from the URL',
      after.search || '(none)'
    );
    check(
      after.scrollKeys.length === 0,
      'AFTER: report scroll offsets removed from sessionStorage',
      after.scrollKeys.join(',')
    );
    check(after.sectionsKey === null, 'AFTER: report section map removed from localStorage');
    check(after.units === 'imperial', 'AFTER: units preference survives (data, not prefs)');
    const toast = await page.evaluate(() => /pristine first-run state/.test(document.body.innerText));
    check(toast, 'AFTER: confirmation toast names the pristine state');

    // No analysis request body can still describe the old plot when a new
    // analysis runs: the boundary is gone from state, not just from the DOM.
    const requestBoundary = await page.evaluate(() => ({
      run: Boolean(
        Array.from(document.querySelectorAll('button')).find((b) =>
          (b.textContent || '').includes('Run Site Feasibility Analysis')
        )
      ),
      select: Boolean(
        Array.from(document.querySelectorAll('button')).find((b) =>
          (b.textContent || '').includes('Select Location on Map to Begin')
        )
      ),
    }));
    check(
      !requestBoundary.run && requestBoundary.select,
      'AFTER: analysis is gated again (no plot to analyze; CTA asks for a site)',
      JSON.stringify(requestBoundary)
    );

    const mapView = await page.evaluate(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      for (let i = 0; i < 40 && !window.__maplibreMap; i += 1) await sleep(100);
      const m = window.__maplibreMap;
      if (!m) return null;
      for (let i = 0; i < 40 && m.isMoving(); i += 1) await sleep(50);
      const c = m.getCenter();
      return {
        lat: Number(c.lat.toFixed(4)),
        lon: Number(c.lng.toFixed(4)),
        zoom: Number(m.getZoom().toFixed(1)),
        pitch: Math.round(m.getPitch()),
        bearing: Math.round(m.getBearing()),
      };
    });
    check(
      mapView &&
        Math.abs(mapView.lat - 12.9716) < 0.01 &&
        Math.abs(mapView.lon - 77.5946) < 0.01,
      'AFTER: map pin returns to the default site',
      JSON.stringify(mapView)
    );
    check(
      mapView &&
        firstRunCamera &&
        mapView.zoom === firstRunCamera.zoom &&
        mapView.pitch === firstRunCamera.pitch &&
        mapView.bearing === firstRunCamera.bearing,
      'AFTER: camera matches the first-run view (zoom / pitch / bearing)',
      `after=${JSON.stringify(mapView)} firstRun=${JSON.stringify(firstRunCamera)}`
    );

    console.log('- reload: the session must stay pristine');
    await page.reload({ waitUntil: 'networkidle2', timeout: 60000 });
    await page.waitForSelector('button[aria-label="Reset the site analysis"]', { timeout: 20000 });
    await sleep(800);
    const reload = await page.evaluate(SNAPSHOT);
    check(!reload.boundaryChip, 'RELOAD: no boundary chip');
    check(!reload.report, 'RELOAD: report stays unmounted');
    check(!reload.stale, 'RELOAD: no stale guard');
    check(reload.area === '2000' && reload.coverage === '0.6', 'RELOAD: default parameters');
    check(
      !/[?&]lat=/.test(reload.search) && reload.search === '',
      'RELOAD: URL did not restore the reset site',
      reload.search || '(none)'
    );
    const reloadMap = await page.evaluate(() => {
      const m = window.__maplibreMap;
      if (!m) return null;
      const c = m.getCenter();
      return { lat: Number(c.lat.toFixed(4)), lon: Number(c.lng.toFixed(4)) };
    });
    check(
      reloadMap &&
        Math.abs(reloadMap.lat - 12.9716) < 0.01 &&
        Math.abs(reloadMap.lon - 77.5946) < 0.01,
      'RELOAD: default site view',
      JSON.stringify(reloadMap)
    );
    check(
      await page.evaluate(() => localStorage.getItem('buildwise.units') === 'imperial'),
      'RELOAD: preference survives the reload'
    );

    console.log('- keyboard: R opens the same destructive confirmation');
    await page.keyboard.press('r');
    await page.waitForSelector('[data-testid="reset-confirm-dialog"]', { timeout: 10000 });
    const dialogZ = await page.evaluate(() => {
      const panel = document.querySelector('[data-testid="reset-confirm-dialog"]')?.closest('[role="dialog"]');
      const stack = panel?.parentElement;
      return stack ? Number(getComputedStyle(stack).zIndex) : null;
    });
    check(true, 'R shortcut opens the reset confirmation');
    check(
      dialogZ === 2100,
      'confirmation stacks above the report sheet (z 2100)',
      String(dialogZ)
    );
    await page.click('[data-testid="reset-cancel"]');
    await sleep(300);
    check(
      await page.evaluate(
        () => !document.querySelector('[data-testid="reset-confirm-dialog"]')
      ),
      'cancelling leaves the pristine session untouched'
    );
  } catch (err) {
    check(false, 'unexpected failure', String((err && err.message) || err));
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  if (consoleErrors.length) {
    console.log('\nCONSOLE ERRORS:');
    consoleErrors.slice(0, 8).forEach((e) => console.log(' -', e.slice(0, 300)));
  }
  console.log(
    `\n${failed.length === 0 ? 'PASS' : `FAIL (${failed.length})`} — ${
      results.length
    } checks`
  );
  process.exit(failed.length === 0 && consoleErrors.length === 0 ? 0 : 1);
}

main();
