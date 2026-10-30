#!/usr/bin/env node
/**
 * measure_premium_map.cjs — evidence, not claims.
 * ===============================================
 * The premium map brief asks for measurements (initial load, map init,
 * style-switch duration, plot-selection transition, panel responsiveness,
 * long tasks). This script records them from a real headless Chrome against
 * the running dev server and writes one JSON file, so the audit report can
 * quote numbers that were actually observed on this machine.
 *
 * What it measures
 *   load      navigation timing + first contentful paint + time to a
 *             style-loaded MapLibre instance (the engine is lazy-mounted).
 *   styles    click -> raster overlay at full opacity, and click -> camera
 *             at rest, for Standard->Satellite and Satellite->Terrain.
 *   flash     screenshots of the map region at 80/180/350/700 ms into the
 *             terrain switch (a blank frame has near-zero luminance spread).
 *   plot      camera-settle time for a selected boundary (fit token 720 ms).
 *   panels    the actual animation durations of a sheet and a drawer, read
 *             from getAnimations() rather than from source.
 *   long tasks per phase via PerformanceObserver.
 *
 * Usage: node scripts/measure_premium_map.cjs
 * Output: ../docs_ignore/qa-audit/assets-premium/perf-premium.json
 *         ../docs_ignore/qa-audit/assets-premium/flash-terrain-*.png
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const URL = process.env.E2E_URL || 'http://localhost:5173/app';
const OUT_DIR = path.resolve(__dirname, '..', '..', 'docs_ignore', 'qa-audit', 'assets-premium');
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
    } catch {
      /* next */
    }
  }
  throw new Error('Chrome not found. Set CHROME_PATH.');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clickByLabel(page, label) {
  return page.evaluate((needle) => {
    const btn = Array.from(document.querySelectorAll('button')).find(
      (b) => (b.textContent || '').includes(needle) && !b.disabled,
    );
    if (!btn) return false;
    btn.click();
    return true;
  }, label);
}

async function waitForMap(page) {
  await page.waitForFunction(() => !!window.__maplibreMap && window.__maplibreMap.isStyleLoaded(), {
    timeout: 60000,
  });
}

async function openStylePicker(page) {
  await page.evaluate(() => {
    document
      .querySelector('button[aria-label="Map details (standard / satellite / terrain)"]')
      ?.click();
  });
  await page.waitForSelector('button[role="radio"][data-mode]', { timeout: 5000 });
}

async function chooseStyle(page, mode) {
  await openStylePicker(page);
  return page.evaluate((id) => {
    const btn = document.querySelector(`button[role="radio"][data-mode="${id}"]`);
    if (!btn) return false;
    btn.click();
    return true;
  }, mode);
}

/**
 * Wait for the crossfade to be ISSUED, and read its budget.
 *
 * MapLibre's `getPaintProperty` returns the TARGET value, so opacity flips to 1
 * the instant the fade is issued — it cannot tell us when the pixels finished
 * moving. What is observable is the transition the app sets on the layer
 * (`raster-opacity-transition`), which is the designed crossfade the reader
 * sees. The tile gate holds the fade until tiles are resident (or its 1.2 s
 * timeout), so this polls until the transition stops being the gate's 0 ms
 * placeholder and becomes the 420 ms fade.
 */
async function waitForFadeIssue(page, layerId, timeoutMs = 3000) {
  const started = Date.now();
  for (;;) {
    const info = await page.evaluate((id) => {
      const m = window.__maplibreMap;
      if (!m || !m.getLayer(id)) return null;
      return {
        visible: m.getLayoutProperty(id, 'visibility') !== 'none',
        opacity: m.getPaintProperty(id, 'raster-opacity'),
        transition: m.getPaintProperty(id, 'raster-opacity-transition') || null,
      };
    }, layerId);
    if (info?.transition && info.transition.duration >= 300) {
      return { issuedAfterMs: Date.now() - started, ...info };
    }
    if (Date.now() - started > timeoutMs) return { issuedAfterMs: null, ...info };
    await sleep(20);
  }
}

/** Wait for the mode attribute React commits, so timing starts at the effect. */
async function waitForStyleAttribute(page, mode, timeoutMs = 4000) {
  const started = Date.now();
  for (;;) {
    const ok = await page.evaluate(
      (m) => document.querySelector('[data-map-style]')?.getAttribute('data-map-style') === m,
      mode,
    );
    if (ok) return Date.now() - started;
    if (Date.now() - started > timeoutMs) return null;
    await sleep(10);
  }
}

/**
 * Camera settle: wait until the ease has STARTED, then until it rests. The
 * effect runs one commit after the click, so polling `isMoving()` immediately
 * reports 'at rest' before the camera has even been told to move.
 */
async function waitForCameraCycle(page, timeoutMs = 5000) {
  const started = Date.now();
  let seenMoving = false;
  while (Date.now() - started <= timeoutMs) {
    const moving = await page.evaluate(() => window.__maplibreMap?.isMoving() ?? false);
    if (moving) seenMoving = true;
    else if (seenMoving) return Date.now() - started;
    await sleep(16);
  }
  return null;
}

const readLongTasks = (page) => page.evaluate(() => (window.__premiumLong || []).slice());
const resetLongTasks = (page) =>
  page.evaluate(() => {
    window.__premiumLong = [];
  });

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const out = { generatedAt: new Date().toISOString(), url: URL, viewport: '1600x1000' };
  const browser = await puppeteer.launch({
    executablePath: resolveChrome(),
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1600,1000', '--use-gl=swiftshader'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });

  try {
    // ---------------------------------------------------------------- load
    await page.evaluateOnNewDocument(() => {
      window.__premiumLong = [];
      try {
        new PerformanceObserver((list) =>
          list.getEntries().forEach((e) => window.__premiumLong.push(Math.round(e.duration))),
        ).observe({ type: 'longtask', buffered: true });
      } catch {
        /* observer unsupported */
      }
    });
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const t0 = Date.now();
    await waitForMap(page);
    const mapReadyWall = Date.now() - t0;
    out.load = await page.evaluate(() => {
      const nav = performance.getEntriesByType('navigation')[0];
      const paints = performance.getEntriesByType('paint');
      const fcp = paints.find((p) => p.name === 'first-contentful-paint');
      return {
        domInteractiveMs: Math.round(nav?.domInteractive ?? 0),
        domContentLoadedMs: Math.round(nav?.domContentLoadedEventEnd ?? 0),
        loadEventMs: Math.round(nav?.loadEventEnd ?? 0),
        firstContentfulPaintMs: fcp ? Math.round(fcp.startTime) : null,
        mapStyleLoadedAtMs: Math.round(performance.now()),
        engineChunkRequests: performance
          .getEntriesByType('resource')
          .filter((r) => /MapCanvas-|maplibre/.test(r.name)).length,
      };
    });
    out.load.mapReadyAfterDomContentLoadedMs = mapReadyWall;
    out.longTasks = { load: await readLongTasks(page) };
    await sleep(1200);

    // The style picker is a popover: measure its entrance from the DOM.
    await openStylePicker(page);
    out.panels = {};
    out.panels.stylePopoverInMs = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="map-style-picker"]') ||
        document.querySelector('button[role="radio"][data-mode]')?.closest('div[class*="rounded"]');
      const anims = el ? el.getAnimations({ subtree: true }) : [];
      return anims.length ? Math.round(Math.max(...anims.map((a) => a.effect.getTiming().duration))) : null;
    });
    await page.keyboard.press('Escape').catch(() => {});

    // ------------------------------------------------------- style switches
    out.styleSwitch = {};
    await resetLongTasks(page);
    const cameraBefore = await page.evaluate(() => {
      const m = window.__maplibreMap;
      return { zoom: m.getZoom(), bearing: m.getBearing(), pitch: m.getPitch() };
    });
    let t = Date.now();
    await chooseStyle(page, 'satellite');
    const satEffectStart = await waitForStyleAttribute(page, 'satellite');
    const satRaster = await waitForFadeIssue(page, 'satellite-layer');
    const satCameraMs = await waitForCameraCycle(page);
    out.styleSwitch.standardToSatellite = {
      effectStartMs: satEffectStart,
      fadeIssuedAfterClickMs: satRaster?.issuedAfterMs ?? null,
      crossfade: satRaster?.transition ?? null,
      crossfadeEndMs:
        satRaster?.issuedAfterMs != null && satRaster?.transition
          ? satRaster.issuedAfterMs + satRaster.transition.duration + (satRaster.transition.delay || 0)
          : null,
      cameraSettleMs: satCameraMs,
    };
    await sleep(900);
    const cameraAfterSat = await page.evaluate(() => {
      const m = window.__maplibreMap;
      return { zoom: m.getZoom(), bearing: m.getBearing(), pitch: m.getPitch() };
    });
    out.styleSwitch.standardToSatellite.camera = { before: cameraBefore, after: cameraAfterSat };
    out.longTasks.satelliteSwitch = await readLongTasks(page);

    await resetLongTasks(page);
    t = Date.now();
    await chooseStyle(page, 'terrain');
    const terrEffectStart = await waitForStyleAttribute(page, 'terrain');
    const terrRaster = await waitForFadeIssue(page, 'terrain-layer');
    const terrCameraMs = await waitForCameraCycle(page);
    out.styleSwitch.satelliteToTerrain = {
      effectStartMs: terrEffectStart,
      fadeIssuedAfterClickMs: terrRaster?.issuedAfterMs ?? null,
      crossfade: terrRaster?.transition ?? null,
      crossfadeEndMs:
        terrRaster?.issuedAfterMs != null && terrRaster?.transition
          ? terrRaster.issuedAfterMs + terrRaster.transition.duration + (terrRaster.transition.delay || 0)
          : null,
      cameraSettleMs: terrCameraMs,
      totalMs: Date.now() - t,
    };
    await sleep(1200);
    out.longTasks.terrainSwitch = await readLongTasks(page);

    // -------------------------------------------- terrain flash (separate pass)
    // Screenshots of a WebGL surface cost hundreds of ms each, so this runs
    // AFTER the timing pass: switch back and re-enter terrain, sampling the map
    // band on the way. A blank frame has near-zero luminance spread.
    await chooseStyle(page, 'standard');
    await sleep(1200);
    const clip = { x: 360, y: 80, width: 900, height: 700 };
    t = Date.now();
    await chooseStyle(page, 'terrain');
    for (const at of [80, 180, 350, 700]) {
      while (Date.now() - t < at) await sleep(5);
      await page.screenshot({ path: path.join(OUT_DIR, `flash-terrain-${at}ms.png`), clip });
    }
    out.flashSamples = [80, 180, 350, 700].map((ms) => `flash-terrain-${ms}ms.png`);
    await sleep(1200);

    // ------------------------------------------------------------- panels
    await resetLongTasks(page);
    await page.mouse.click(700, 500);
    await page.keyboard.press('r');
    await page.waitForSelector('.animate-sheet-in', { timeout: 8000 });
    await sleep(40);
    out.panels.sheetInMs = await page.evaluate(() => {
      const el = document.querySelector('.animate-sheet-in');
      if (!el) return null;
      const d = getComputedStyle(el).animationDuration;
      return Math.round(parseFloat(d) * 1000);
    });
    await page.keyboard.press('Escape');
    await sleep(40);
    out.panels.sheetOutMs = await page.evaluate(() => {
      const el = document.querySelector('.animate-sheet-out');
      if (!el) return null;
      return Math.round(parseFloat(getComputedStyle(el).animationDuration) * 1000);
    });
    await page.waitForFunction(() => !document.querySelector('.animate-sheet-out'), { timeout: 3000 });
    out.longTasks.panel = await readLongTasks(page);

    // --------------------------------------------------------------- plot
    // A clean page: the theme/mode state above is not part of this measure.
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 });
    await waitForMap(page);
    await sleep(900);
    await resetLongTasks(page);
    const plotStart = await page.evaluate(() => {
      const m = window.__maplibreMap;
      return { zoom: m.getZoom(), bearing: m.getBearing() };
    });
    await clickByLabel(page, 'Select Location on Map to Begin');
    await page.waitForFunction(() => /Locate the site/.test(document.body.innerText || ''), { timeout: 15000 });
    await clickByLabel(page, 'Trace boundary');
    await page.waitForSelector('[data-testid="trace-toolbar-presets"]', { timeout: 15000 });
    await page.click('[data-testid="trace-toolbar-presets"]');
    await page.waitForSelector('[data-testid="preset-menu"]', { timeout: 8000 });
    await page.click('[data-testid="preset-item-rect"]');
    await sleep(900);
    await clickByLabel(page, 'Finish');
    await page.waitForFunction(() => /Confirm the frontage/.test(document.body.innerText || ''), { timeout: 30000 });
    await page.evaluate(() => {
      Array.from(document.querySelectorAll('button'))
        .find((b) => (b.textContent || '').trim() === 'Accept' && !b.disabled)
        ?.click();
    });
    await page.evaluate(() => document.querySelector('[data-testid="edge-row-0"]')?.click());
    await sleep(300);
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll('button')).some(
          (b) => (b.textContent || '').trim() === 'Review' && !b.disabled,
        ),
      { timeout: 15000 },
    );
    await clickByLabel(page, 'Review');
    await page.waitForFunction(() => /Review boundary/.test(document.body.innerText || ''), { timeout: 15000 });
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll('button')).some(
          (b) => (b.textContent || '').includes('Use this boundary') && !b.disabled,
        ),
      { timeout: 30000 },
    );
    t = Date.now();
    await clickByLabel(page, 'Use this boundary');
    await page.waitForSelector('[data-testid="site-preview-hud"]', { timeout: 15000 });
    const hudMs = Date.now() - t;
    const plotCameraMs = await waitForCameraCycle(page);
    await sleep(900);
    const plotEnd = await page.evaluate(() => {
      const m = window.__maplibreMap;
      return { zoom: m.getZoom(), bearing: m.getBearing() };
    });
    out.plot = {
      clickToPanelVisibleMs: hudMs,
      cameraSettleMs: plotCameraMs,
      zoomBefore: plotStart.zoom,
      zoomAfter: plotEnd.zoom,
      bearingBefore: plotStart.bearing,
      bearingAfter: plotEnd.bearing,
    };

    // Property panel close: camera restore duration.
    t = Date.now();
    await page.evaluate(() =>
      document.querySelector('button[aria-label="Dismiss site preview"]')?.click(),
    );
    const restoreCameraMs = await waitForCameraCycle(page);
    out.plot.dismissToCameraRestMs = restoreCameraMs;
    out.plot.dismissTotalMs = Date.now() - t;
    out.longTasks.plot = await readLongTasks(page);

    // -------------------------------------------------------- compact drawer
    await page.setViewport({ width: 390, height: 844 });
    await sleep(700);
    await clickByLabel(page, 'Controls');
    await page.waitForSelector('#controls-drawer', { timeout: 5000 });
    await sleep(40);
    out.panels.drawerInMs = await page.evaluate(() => {
      const el = document.querySelector('#controls-drawer');
      return el ? Math.round(parseFloat(getComputedStyle(el).animationDuration) * 1000) : null;
    });
    const drawerStart = Date.now();
    await page.evaluate(() =>
      document.querySelector('#controls-drawer button[aria-label="Close parameters panel"]')?.click(),
    );
    out.panels.drawerOutMs = await page.evaluate(() => {
      const el = document.querySelector('#controls-drawer');
      return el ? Math.round(parseFloat(getComputedStyle(el).animationDuration) * 1000) : null;
    });
    await page.waitForFunction(() => !document.querySelector('#controls-drawer'), { timeout: 3000 });
    out.panels.drawerUnmountMs = Date.now() - drawerStart;

    // ------------------------------------------------------ reduced motion
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await sleep(200);
    out.reducedMotion = await page.evaluate(() => {
      const btn = document.querySelector(
        'button[aria-label="Map details (standard / satellite / terrain)"]',
      );
      return {
        stylePickerTransition: btn ? getComputedStyle(btn).transitionDuration : null,
        cameraTransitionToken: getComputedStyle(document.documentElement)
          .getPropertyValue('--motion-duration-panel')
          .trim(),
      };
    });
    out.longTasks.all = await page.evaluate(() => (window.__premiumLong || []).slice());
  } catch (err) {
    out.error = String((err && err.stack) || err).slice(0, 2000);
  } finally {
    await browser.close();
    const file = path.join(OUT_DIR, 'perf-premium.json');
    fs.writeFileSync(file, JSON.stringify(out, null, 2));
    console.log(JSON.stringify(out, null, 2));
    console.log(`\nwrote ${file}`);
  }
})();
