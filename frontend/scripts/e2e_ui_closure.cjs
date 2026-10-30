#!/usr/bin/env node
/**
 * e2e_ui_closure.cjs — browser pass for UI state that needs a real browser.
 * =============================================================================
 * These surfaces need real geometry, media queries and a live engine, so they
 * are exercised here rather than in a DOM shim. One 2-storey T1 plan drives:
 *
 *   [1] Exactly ONE live tab set at 390 and 1280; every role=tab has a
 *       non-zero box and can take focus (no phantom 0x0 duplicates).
 *   [2] Multi-storey + ghost core — floor tabs switch plates, the ghost toggle
 *       is disabled on F0, and the injected sheet mirrors the state on
 *       `data-ghost-overlay` in both directions.
 *   [3] Generation timeout — a held request aborts at the bounded timeout,
 *       surfaces the disclosed error, re-enables the button and keeps the
 *       previous plan on screen (dev-only timeout seam).
 *   [4] Reduced motion — under `prefers-reduced-motion: reduce` every sampled
 *       transition collapses to 0.01 ms and pulse animations are off.
 *   [5] Contrast spot — every sampled report ink equals a themed AA token
 *       (ratios themselves are gated by `npm run check:contrast`).
 *   [6] A real WebGL context loss/restore raises no page error.
 *
 * Usage (backend :8000, frontend :5173):
 *   node scripts/e2e_ui_closure.cjs
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const URL = process.env.E2E_URL || 'http://localhost:5173/app';
const SHOTS = path.resolve(__dirname, '../../docs_ignore/ui-closure');
fs.mkdirSync(SHOTS, { recursive: true });
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
    try { if (fs.existsSync(p)) return p; } catch (e) { /* ignore */ }
  }
  throw new Error('Chrome not found. Set CHROME_PATH.');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(ok, label, detail) {
  results.push({ ok, label, detail });
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
}

async function clickByLabel(page, needle) {
  return page.evaluate((label) => {
    const btn = Array.from(document.querySelectorAll('button'))
      .find((b) => (b.textContent || '').includes(label));
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, needle);
}

async function clickTab(page, label) {
  return page.evaluate((needle) => {
    const btn = Array.from(document.querySelectorAll('[role="tab"]'))
      .find((b) => (b.textContent || '').includes(needle));
    if (!btn) return false;
    btn.click();
    return true;
  }, label);
}

/**
 * The report sheet is a nested scroller and the viewer sits far below the
 * document top. Puppeteer's page.click() auto-scroll only the top-level page,
 * so a real floor-tab/ghost-toggle click could land off-screen while the test
 * silently clicked nothing. Scroll the control into view in its own container
 * first, then click it for real. No assertion is relaxed.
 */
async function scrollAndClick(page, selector) {
  const ready = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    return true;
  }, selector);
  if (!ready) throw new Error(`control not found: ${selector}`);
  await sleep(250);
  await page.click(selector);
}

async function main() {
  console.log('=== E2E: UI closure ===');
  const browser = await puppeteer.launch({
    executablePath: resolveChrome(),
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1600,1000', '--use-gl=swiftshader'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });

  const pageErrors = [];
  page.on('pageerror', (err) => {
    pageErrors.push(String(err && err.message || err));
    console.log('[page error]', String(err && err.message || err).slice(0, 200));
  });
  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });

  try {
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await sleep(1500);

    const liveProvider = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="provider-state-label"]');
      return el ? { state: el.getAttribute('data-provider-state'), label: el.textContent.trim() } : null;
    });
    check(
      liveProvider && liveProvider.state === 'live' && liveProvider.label === 'Live',
      'a configured hosted key renders the narrative badge Live',
      JSON.stringify(liveProvider),
    );

    // ---------------------------------------------------------------- capture
    console.log('- capture a rectangular plot');
    const cta = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => /Run Site Feasibility Analysis|Select Location on Map to Begin/.test(b.textContent || ''));
      if (!btn || btn.disabled) return false;
      btn.click();
      return true;
    });
    check(cta, 'capture wizard opened from the pre-boundary CTA');
    await page.waitForFunction(() => /Locate the site/.test(document.body.innerText || ''), { timeout: 15000 });
    await clickByLabel(page, 'Trace boundary');
    await sleep(800);
    await page.click('[data-testid="trace-toolbar-presets"]');
    await page.waitForSelector('[data-testid="preset-menu"]', { timeout: 8000 });
    await page.click('[data-testid="preset-item-rect"]');
    await sleep(900);
    await clickByLabel(page, 'Finish');
    await page.waitForFunction(() => /Confirm the frontage/.test(document.body.innerText || ''), { timeout: 40000 });

    // Overpass may be unavailable: the sheet then offers no amber suggestion and
    // says so. In that documented fallback the frontage is confirmed manually by
    // picking an edge row — never by assuming a bearing.
    const accepted = await page.evaluate(() => {
      const accept = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Accept');
      if (accept && !accept.disabled) { accept.click(); return 'suggestion accepted'; }
      const row = document.querySelector('[data-testid="edge-row-1"]');
      if (row) { row.click(); return 'edge picked manually'; }
      return null;
    });
    check(Boolean(accepted), 'frontage confirmed (suggestion or documented manual pick)', accepted || 'no control');
    await page.waitForFunction(() => {
      const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Review');
      return Boolean(btn) && !btn.disabled;
    }, { timeout: 25000 });
    await clickByLabel(page, 'Review');
    await page.waitForFunction(() => /Review boundary/.test(document.body.innerText || ''), { timeout: 15000 });
    await page.waitForFunction(() => {
      const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').includes('Use this boundary'));
      return Boolean(btn) && !btn.disabled;
    }, { timeout: 15000 });
    await clickByLabel(page, 'Use this boundary');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('button'))
      .some((b) => (b.textContent || '').includes('Run Site Feasibility Analysis')), { timeout: 15000 });
    check(true, 'captured plot committed');

    // ------------------------------------------------------- 2-storey analysis
    console.log('- set 2 storeys and run the analysis');
    await page.click('#floors-select');
    await page.waitForSelector('[role="option"]', { timeout: 8000 });
    const storeyPicked = await page.evaluate(() => {
      const opt = Array.from(document.querySelectorAll('[role="option"]'))
        .find((o) => /2 Levels/.test(o.textContent || ''));
      if (!opt || opt.disabled) return false;
      opt.click();
      return true;
    });
    check(storeyPicked, 'storeys control accepts G + 1 (2 Levels)');
    await sleep(400);
    const storeyCaption = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="storeys-caption"]');
      return el ? el.textContent.trim() : null;
    });
    check(Boolean(storeyCaption) && /2 levels/i.test(storeyCaption), 'caption confirms two levels', storeyCaption || 'none');

    const analyzeDone = page.waitForResponse(
      (res) => res.url().includes('/api/analyze') && res.request().method() === 'POST' && res.status() === 200,
      { timeout: 120000 },
    );
    await clickByLabel(page, 'Run Site Feasibility Analysis');
    await analyzeDone;
    await page.waitForFunction(() => Array.from(document.querySelectorAll('button'))
      .some((b) => (b.textContent || '').includes('Open Full Report')), { timeout: 90000 });
    check(true, 'analysis completed and the report CTA is available');

    // ------------------------------------------------------- report + generate
    console.log('- open the report and generate the 2-storey plan');
    await clickByLabel(page, 'Open Full Report');
    await page.waitForSelector('[role="dialog"][aria-label="Site Feasibility Report"]', { timeout: 15000 });
    check(true, 'report sheet opened');
    check(await clickTab(page, 'Cost & Plan'), 'Cost & Plan tab reached from the sheet tab bar');
    await sleep(1200);

    const generated = page.waitForResponse(
      (res) => res.url().includes('/api/generate-floorplan') && res.request().method() === 'POST' && res.status() === 200,
      { timeout: 120000 },
    );
    const genClicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => /Generate .*(Blueprint|Floor Plan)|Regenerate Blueprint/.test(b.textContent || ''));
      if (!btn || btn.disabled) return null;
      btn.click();
      return btn.textContent.trim();
    });
    check(Boolean(genClicked), 'generate action found', genClicked || 'none');
    await generated;
    await page.waitForSelector('[data-testid="tab-floor-1"]', { timeout: 30000 });
    check(true, 'multi-storey plan rendered with a G+1 floor tab');

    // ------------------------------------------------- [2] ghost core overlay
    console.log('- multi-storey switching + ghost core');
    const storey = await page.evaluate(() => {
      const viewer = document.querySelector('#blueprint-viewer-container');
      const chip = viewer
        ? [...viewer.querySelectorAll('span')].some((el) => /2F CAD/.test(el.textContent || ''))
        : false;
      return {
        chip,
        tabs: document.querySelectorAll('[data-testid^="tab-floor-"]').length,
        ghostDisabledOnGround: (() => {
          const b = document.querySelector('[data-testid="ghost-overlay-toggle"]');
          return b ? b.disabled : null;
        })(),
      };
    });
    check(storey.chip, 'viewer header states 2F CAD');
    check(storey.tabs === 2, 'both storey plates are listed', `${storey.tabs} tabs`);
    check(storey.ghostDisabledOnGround === true, 'ghost toggle is disabled on the ground floor');

    await scrollAndClick(page, '[data-testid="tab-floor-1"]');
    await sleep(900);
    const upper = await page.evaluate(() => {
      const toggle = document.querySelector('[data-testid="ghost-overlay-toggle"]');
      const svg = document.querySelector('#blueprint-viewer-container svg.bw-sheet-fit');
      return {
        toggleDisabled: toggle ? toggle.disabled : null,
        pressed: toggle ? toggle.getAttribute('aria-pressed') : null,
        ghost: svg ? svg.getAttribute('data-ghost-overlay') : null,
        heading: (document.querySelector('#blueprint-viewer-container h3') || {}).textContent || '',
      };
    });
    check(upper.toggleDisabled === false, 'ghost toggle is enabled on the upper floor');
    check(upper.ghost === 'true' && upper.pressed === 'true', 'upper floor starts with the F0 core ghost ON', JSON.stringify(upper));
    check(/G\+1|First|Level 1/i.test(upper.heading), 'floor switch changed the plate heading', upper.heading.trim());

    await scrollAndClick(page, '[data-testid="ghost-overlay-toggle"]');
    await sleep(500);
    const ghostOff = await page.evaluate(() => {
      const svg = document.querySelector('#blueprint-viewer-container svg.bw-sheet-fit');
      const toggle = document.querySelector('[data-testid="ghost-overlay-toggle"]');
      return { ghost: svg ? svg.getAttribute('data-ghost-overlay') : null, pressed: toggle ? toggle.getAttribute('aria-pressed') : null };
    });
    check(ghostOff.ghost === 'false' && ghostOff.pressed === 'false', 'ghost toggle OFF flips the injected sheet in place', JSON.stringify(ghostOff));

    await scrollAndClick(page, '[data-testid="ghost-overlay-toggle"]');
    await sleep(400);
    const ghostOn = await page.evaluate(() => {
      const svg = document.querySelector('#blueprint-viewer-container svg.bw-sheet-fit');
      return svg ? svg.getAttribute('data-ghost-overlay') : null;
    });
    check(ghostOn === 'true', 'ghost toggle ON restores the overlay');

    await page.screenshot({ path: path.join(SHOTS, 'ghost-core-upper-floor.png') });

    // -------------------------------------------------------------- [1] tabs
    console.log('- one live tab set at 390 and 1280');
    for (const width of [390, 1280]) {
      await page.setViewport({ width, height: width === 390 ? 844 : 900 });
      await sleep(600);
      const tabs = await page.evaluate(() => {
        const sheet = document.querySelector('[role="dialog"][aria-label="Site Feasibility Report"]');
        if (!sheet) return { sheet: false };
        const all = [...sheet.querySelectorAll('[role="tab"]')];
        let focusable = 0;
        for (const t of all) {
          try { t.focus(); if (document.activeElement === t) focusable += 1; } catch (e) { /* not focusable */ }
        }
        return {
          sheet: true,
          lists: sheet.querySelectorAll('[role="tablist"]').length,
          tabs: all.length,
          zeroBox: all.filter((t) => {
            const r = t.getBoundingClientRect();
            return r.width === 0 || r.height === 0;
          }).length,
          focusable,
        };
      });
      check(tabs.sheet, `${width}px: report sheet present`);
      check(tabs.lists === 1, `${width}px: exactly one tab list`, `${tabs.lists} lists`);
      check(tabs.tabs === 4, `${width}px: one tab per section`, `${tabs.tabs} tabs`);
      check(tabs.zeroBox === 0, `${width}px: no 0x0 tab remains`, `${tabs.zeroBox} zero-size`);
      check(tabs.focusable === 4, `${width}px: every visible tab takes focus`, `${tabs.focusable}/4`);
    }
    await page.screenshot({ path: path.join(SHOTS, 'single-tab-set-1280.png') });

    // --------------------------------------------------- [3] generation timeout
    console.log('- generation timeout path');
    await page.setViewport({ width: 1280, height: 900 });
    await sleep(400);
    let held = null;
    const holdGenerate = (req) => {
      if (req.url().includes('/api/generate-floorplan') && req.method() === 'POST') {
        held = req;
        return;
      }
      req.continue().catch(() => {});
    };
    await page.setRequestInterception(true);
    page.on('request', holdGenerate);
    await page.evaluate(() => { window.__bwGenerationTimeoutMs = 1200; });

    const timeoutButton = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => /Regenerate Blueprint|Generate .*(Blueprint|Floor Plan)/.test(b.textContent || ''));
      if (!btn || btn.disabled) return null;
      btn.click();
      return btn.textContent.trim();
    });
    check(Boolean(timeoutButton), 'a generation request was started for the timeout test', timeoutButton || 'none');
    let timeoutText = '';
    try {
      await page.waitForFunction(() => {
        const el = document.querySelector('[data-testid="floorplan-generate-error"]');
        return el && /timed out/i.test(el.textContent || '');
      }, { timeout: 20000 });
      timeoutText = await page.evaluate(() => {
        const el = document.querySelector('[data-testid="floorplan-generate-error"]');
        return el ? el.textContent.trim() : '';
      });
    } catch (e) { /* reported below */ }
    check(/timed out/i.test(timeoutText), 'a held request fails with the disclosed timeout message', timeoutText.slice(0, 140));
    const afterTimeout = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => /Regenerate Blueprint|Generate .*(Blueprint|Floor Plan)/.test(b.textContent || ''));
      return {
        buttonEnabled: Boolean(btn && !btn.disabled),
        planStillThere: Boolean(document.querySelector('#blueprint-viewer-container')),
      };
    });
    check(afterTimeout.buttonEnabled, 'the generate button is re-enabled after a timeout');
    check(afterTimeout.planStillThere, 'the previous plan stays on screen (nothing half-drawn)');
    await page.screenshot({ path: path.join(SHOTS, 'generation-timeout.png') });

    try { held && (await held.abort()); } catch (e) { /* already aborted */ }
    page.off('request', holdGenerate);
    await page.setRequestInterception(false);
    await page.evaluate(() => { delete window.__bwGenerationTimeoutMs; });

    // -------------------------------------------- [4] reduced motion (2 widths)
    console.log('- reduced motion at 390 and 1280');
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    for (const width of [390, 1280]) {
      await page.setViewport({ width, height: width === 390 ? 844 : 900 });
      await sleep(500);
      const motion = await page.evaluate(() => {
        const close = document.querySelector('.report-sheet-close-btn') || document.querySelector('[role="dialog"] button');
        const pulse = document.querySelector('.animate-pulse');
        const closeCs = close ? getComputedStyle(close) : null;
        const pulseCs = pulse ? getComputedStyle(pulse) : null;
        return {
          transition: closeCs ? closeCs.transitionDuration : null,
          animation: pulseCs ? pulseCs.animationName : 'no-pulse-element',
        };
      });
      const durations = String(motion.transition || '').split(',').map((d) => parseFloat(d));
      check(
        durations.length > 0 && durations.every((d) => d <= 0.001),
        `${width}px: transitions collapse under reduced motion`,
        motion.transition,
      );
      check(
        motion.animation === 'none' || motion.animation === 'no-pulse-element',
        `${width}px: pulse animations are disabled`,
        motion.animation,
      );
    }
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]);

    // ---------------------------------------------------- [5] contrast spot
    console.log('- contrast spot: report ink uses themed tokens');
    for (const width of [390, 1280]) {
      await page.setViewport({ width, height: width === 390 ? 844 : 900 });
      await sleep(400);
      for (const theme of ['light', 'dark']) {
        for (let i = 0; i < 3; i++) {
          const current = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
          if (current === theme) break;
          await page.evaluate(() => {
            const btn = document.querySelector('[aria-label="Toggle light / dark theme"]');
            if (btn) btn.click();
          });
          try {
            await page.waitForFunction(
              (expected) => document.documentElement.getAttribute('data-theme') === expected,
              { timeout: 3000 },
              theme,
            );
            break;
          } catch {
            /* retry toggle click */
          }
        }
        await page.waitForFunction(() => {
          const sheet = document.querySelector('[role="dialog"][aria-label="Site Feasibility Report"]');
          if (!sheet) return false;
          const probe = document.createElement('span');
          document.body.appendChild(probe);
          probe.style.color = 'var(--text-1)';
          const expected = getComputedStyle(probe).color;
          probe.remove();
          const h1 = sheet.querySelector('h1');
          if (h1 && getComputedStyle(h1).color !== expected) return false;
          const anims = typeof sheet.getAnimations === 'function' ? sheet.getAnimations({ subtree: true }) : [];
          return anims.filter((a) => typeof CSSTransition !== 'undefined' && a instanceof CSSTransition).every((a) => a.playState === 'finished' || a.playState === 'idle');
        }, { timeout: 5000 }).catch(() => {});
        await sleep(600);
        const spot = await page.evaluate(() => {
          const probe = document.createElement('span');
          document.body.appendChild(probe);
          const resolve = (token) => {
            probe.style.color = `var(${token})`;
            return getComputedStyle(probe).color;
          };
          const text1 = resolve('--text-1');
          const text2 = resolve('--text-2');
          const text3 = resolve('--text-3');
          const palette = [
            text1, text2, text3,
            resolve('--accent-ink'),
            resolve('--semantic-amber-ink'),
            resolve('--semantic-red-ink'),
            resolve('--semantic-green-ink'),
            resolve('--segmented-active-label'),
            'rgb(255, 255, 255)',
          ];
          probe.remove();

          const sheet = document.querySelector('[role="dialog"][aria-label="Site Feasibility Report"]');
          const samples = sheet
            ? [...sheet.querySelectorAll('h1,h2,h3,p,button,span')]
                .filter((el) => (el.textContent || '').trim().length > 8 && el.getBoundingClientRect().width > 0)
                .slice(0, 40)
                .map((el) => getComputedStyle(el).color)
            : [];
          const allowed = new Set(palette);
          const offToken = [...new Set(samples.filter((c) => !allowed.has(c)))];
          return {
            tokens: { text1, text2, text3 },
            sampled: samples.length,
            offToken,
            sheetBg: getComputedStyle(document.documentElement).getPropertyValue('--sheet-bg').trim(),
          };
        });
        check(spot.sampled > 0, `${width}px ${theme}: report ink sampled`, `${spot.sampled} nodes`);
        check(
          spot.offToken.length === 0,
          `${width}px ${theme}: every sampled report ink comes from the themed ink palette`,
          spot.offToken.slice(0, 3).join(' | '),
        );
      }
    }

    // ---------------------------------------------- [6] engine badge states
    console.log('- deterministic and offline badge states in the real app');
    const badgePage = await browser.newPage();
    await badgePage.setViewport({ width: 1280, height: 900 });
    await badgePage.setRequestInterception(true);
    badgePage.on('request', (req) => {
      if (req.url().includes('/api/status')) {
        req.respond({
          status: 200,
          contentType: 'application/json',
          // The app fetches the API cross-origin; a synthetic CDP response must
          // carry the CORS header itself or fetch() rejects and the badge would
          // (correctly) read Offline for the wrong reason.
          headers: { 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({ status: 'online', groq: false, gemini: false }),
        }).catch(() => {});
        return;
      }
      req.continue().catch(() => {});
    });
    await badgePage.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await sleep(1200);
    const deterministicBadge = await badgePage.evaluate(() => {
      const b = document.querySelector('[data-testid="engine-state"]');
      return b ? { state: b.getAttribute('data-engine-state'), label: b.textContent.trim() } : null;
    });
    check(
      deterministicBadge && deterministicBadge.state === 'deterministic' && /Deterministic/.test(deterministicBadge.label),
      'a successful status probe with no key renders Deterministic',
      JSON.stringify(deterministicBadge),
    );

    // The panel's own badge: select the built-in
    // deterministic author and read the label the reader actually sees.
    const selectMounted = await badgePage.evaluate(() => Boolean(document.querySelector('#ai-provider-select')));
    if (!selectMounted) {
      await badgePage.evaluate(() => {
        const header = [...document.querySelectorAll('button')]
          .find((b) => /Report Narrative Engine/.test(b.textContent || ''));
        if (header) header.click();
      });
      await sleep(500);
    }
    await badgePage.click('#ai-provider-select');
    await badgePage.waitForSelector('[role="option"]', { timeout: 8000 });
    const pickedMock = await badgePage.evaluate(() => {
      const opt = [...document.querySelectorAll('[role="option"]')]
        .find((o) => /Built-in deterministic engine/.test(o.textContent || ''));
      if (!opt) return false;
      opt.click();
      return true;
    });
    check(pickedMock, 'the built-in narrative author can be selected');
    await sleep(500);
    const deterministicPanel = await badgePage.evaluate(() => {
      const el = document.querySelector('[data-testid="provider-state-label"]');
      return el ? { state: el.getAttribute('data-provider-state'), label: el.textContent.trim() } : null;
    });
    check(
      deterministicPanel && deterministicPanel.state === 'deterministic' && deterministicPanel.label === 'Deterministic',
      'the narrative panel badge reads Deterministic for the built-in engine',
      JSON.stringify(deterministicPanel),
    );

    await badgePage.setRequestInterception(false);
    await badgePage.close();

    const offlinePage = await browser.newPage();
    await offlinePage.setViewport({ width: 1280, height: 900 });
    await offlinePage.setRequestInterception(true);
    offlinePage.on('request', (req) => {
      if (req.url().includes('/api/status')) {
        req.abort('failed').catch(() => {});
        return;
      }
      req.continue().catch(() => {});
    });
    await offlinePage.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(1500);
    const offlineBadge = await offlinePage.evaluate(() => {
      const b = document.querySelector('[data-testid="engine-state"]');
      const label = document.querySelector('[data-testid="provider-state-label"]');
      return {
        header: b ? { state: b.getAttribute('data-engine-state'), label: b.textContent.trim() } : null,
        panel: label ? { state: label.getAttribute('data-provider-state'), label: label.textContent.trim() } : null,
      };
    });
    check(
      offlineBadge.header && offlineBadge.header.state === 'offline' && /Offline/.test(offlineBadge.header.label),
      'an unreachable status probe renders the header Offline',
      JSON.stringify(offlineBadge.header),
    );
    check(
      offlineBadge.panel && offlineBadge.panel.state === 'offline' && offlineBadge.panel.label === 'Offline',
      'the narrative panel badge reads Offline when the backend is unreachable',
      JSON.stringify(offlineBadge.panel),
    );
    await offlinePage.setRequestInterception(false);
    await offlinePage.close();

    // --------------------------------------------------- [7] context loss
    console.log('- WebGL context loss/restore');
    await page.setViewport({ width: 1280, height: 900 });
    await sleep(400);
    const webgl = await page.evaluate(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const map = window.__maplibreMap;
      if (!map) return { available: false, reason: 'no map handle' };
      const canvas = map.getCanvas();
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      const ext = gl && gl.getExtension('WEBGL_lose_context');
      if (!ext) return { available: false, reason: 'WEBGL_lose_context unavailable' };
      window.__qaClosureErrors = [];
      const onError = (e) => window.__qaClosureErrors.push(String(e.message || e));
      window.addEventListener('error', onError);
      ext.loseContext();
      await sleep(700);
      ext.restoreContext();
      await sleep(1600);
      window.removeEventListener('error', onError);
      return {
        available: true,
        errors: window.__qaClosureErrors,
        restored: !canvas.isConnected ? 'canvas detached' : 'canvas in DOM',
      };
    });
    if (!webgl.available) {
      check(false, 'WebGL context loss could be exercised', webgl.reason);
    } else {
      check(
        webgl.errors.every((e) => !/preventDefault/i.test(e)),
        'context loss raises no preventDefault type error',
        webgl.errors.slice(0, 2).join(' | '),
      );
      check(webgl.restored === 'canvas in DOM', 'the map canvas survives a context loss/restore cycle');
    }

    // ------------------------------------------------------------ error tally
    const relevantPageErrors = pageErrors.filter((e) => !/ResizeObserver loop/i.test(e));
    check(relevantPageErrors.length === 0, 'no uncaught page errors during the closure pass', relevantPageErrors.slice(0, 3).join(' | '));
    check(consoleErrors.length === 0, 'no console errors during the closure pass', consoleErrors.slice(0, 3).join(' | '));
  } catch (err) {
    check(false, 'closure pass aborted', String(err && err.message || err));
    try {
      const state = await page.evaluate(() => ({
        text: (document.body.innerText || '').slice(0, 800),
        buttons: Array.from(document.querySelectorAll('button')).map((b) => (b.textContent || '').trim()).filter(Boolean).slice(0, 30),
      }));
      console.log('--- UI at abort ---');
      console.log(JSON.stringify(state, null, 1));
    } catch (e) { /* page may be gone */ }
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n=== UI closure: ${results.length - failed.length} passed, ${failed.length} failed ===`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error('fatal:', err);
  process.exit(2);
});
