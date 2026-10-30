#!/usr/bin/env node
/**
 * e2e_premium_map.cjs — spatial UX contract in a real browser.
 * ===========================================================
 * The map is the app's primary surface, and the properties that make it feel
 * premium are observable only in a running MapLibre instance:
 *
 *   [1] Standard -> Satellite preserves the camera, replaces no style instance
 *       and leaves satellite visible / terrain covered.
 *   [2] Satellite -> Terrain preserves the camera, shows relief, and removes
 *       the building massing that used to turn relief into a skyline.
 *   [3] A theme swap while Terrain is active keeps the topo raster on screen
 *       (the regression that left a dark, blank map).
 *   [4] Reduced motion: a style switch moves no camera and CSS transitions
 *       collapse; the fit/restore path is exercised by `test_plot_camera.cjs`.
 *   [5] Selecting a plot frames it, and dismissing the preview restores the
 *       pre-capture camera instead of leaving the wizard's zoom behind.
 *   [6] Compact drawer enters and exits (the exit is a kept-mounted presence).
 *
 * Usage (frontend :5173, backend :8000):
 *   node scripts/e2e_premium_map.cjs
 * Env: E2E_URL (default http://localhost:5173/app), CHROME_PATH
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');

const URL = process.env.E2E_URL || 'http://localhost:5173/app';
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
const results = [];
function check(ok, label, detail) {
  results.push({ ok, label, detail });
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
}

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
  await page.waitForFunction(
    () => !!window.__maplibreMap && window.__maplibreMap.isStyleLoaded(),
    { timeout: 60000 },
  );
}

async function readCamera(page) {
  return page.evaluate(() => {
    const m = window.__maplibreMap;
    return {
      center: { lng: m.getCenter().lng, lat: m.getCenter().lat },
      zoom: m.getZoom(),
      bearing: m.getBearing(),
      pitch: m.getPitch(),
    };
  });
}

function sameCamera(a, b, tolerance = 1e-5) {
  return (
    Math.abs(a.center.lng - b.center.lng) < tolerance &&
    Math.abs(a.center.lat - b.center.lat) < tolerance &&
    Math.abs(a.zoom - b.zoom) < tolerance &&
    Math.abs(a.bearing - b.bearing) < tolerance
  );
}

async function openStylePicker(page) {
  await page.evaluate(() => {
    const btn = document.querySelector('button[aria-label="Map details (standard / satellite / terrain)"]');
    if (btn) btn.click();
  });
  await page.waitForSelector('button[role="radio"][data-mode]', { timeout: 5000 });
}

async function chooseStyle(page, mode) {
  await openStylePicker(page);
  const clicked = await page.evaluate((id) => {
    const btn = document.querySelector(`button[role="radio"][data-mode="${id}"]`);
    if (!btn) return false;
    btn.click();
    return true;
  }, mode);
  return clicked;
}

(async () => {
  console.log('=== E2E: premium spatial UX ===');
  const browser = await puppeteer.launch({
    executablePath: resolveChrome(),
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1600,1000', '--use-gl=swiftshader'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => pageErrors.push(String((err && err.message) || err)));

  try {
    console.log(`- loading ${URL}`);
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 });
    await waitForMap(page);
    await sleep(1200);
    await page.evaluate(() => {
      window.__premiumLong = [];
      try {
        new PerformanceObserver((list) =>
          list.getEntries().forEach((e) => window.__premiumLong.push(Math.round(e.duration))),
        ).observe({ type: 'longtask', buffered: false });
      } catch {
        /* observer unsupported */
      }
      window.__mapIdentity = window.__maplibreMap;
    });
    check(true, 'app + map loaded at 1600x1000');

    console.log('\n[1] Standard -> Satellite');
    const beforeSat = await readCamera(page);
    await page.evaluate(() => { window.__premiumLong.length = 0; });
    check(await chooseStyle(page, 'satellite'), 'satellite chosen through the style picker');
    await sleep(1500);
    const sat = await page.evaluate(() => {
      const m = window.__maplibreMap;
      return {
        sameInstance: m === window.__mapIdentity,
        satelliteVisible: m.getLayoutProperty('satellite-layer', 'visibility'),
        satelliteOpacity: m.getPaintProperty('satellite-layer', 'raster-opacity'),
        terrainOpacity: m.getPaintProperty('terrain-layer', 'raster-opacity'),
        massing: m.getLayer('3d-buildings') ? m.getLayoutProperty('3d-buildings', 'visibility') : 'absent',
        roadOpacity: (() => {
          const road = m.getStyle().layers.find((l) => l.type === 'line' && /^(road_|bridge_|highway_)/.test(l.id));
          return road ? m.getPaintProperty(road.id, 'line-opacity') : null;
        })(),
        long: window.__premiumLong.slice(),
      };
    });
    const afterSat = await readCamera(page);
    check(sat.sameInstance, 'style switch keeps the same MapLibre instance (no reconstruction)');
    check(sameCamera(beforeSat, afterSat), 'centre, zoom and bearing are preserved', JSON.stringify({ beforeSat, afterSat }));
    check(sat.satelliteVisible === 'visible' && sat.satelliteOpacity === 1, 'satellite imagery is the visible basemap', JSON.stringify({ v: sat.satelliteVisible, o: sat.satelliteOpacity }));
    check(sat.terrainOpacity === 0, 'terrain imagery is fully covered in satellite mode');
    check(sat.massing === 'none', 'building massing is removed over imagery');
    check(Math.abs(sat.roadOpacity - 0.34) < 0.001, 'satellite roads are held at context weight (0.34)', String(sat.roadOpacity));
    check(sat.long.every((d) => d <= 320), 'satellite switch has no long task over 320 ms', sat.long.join(', ') || 'none');
    await openStylePicker(page);
    const satChecked = await page.evaluate(
      () => document.querySelector('button[role="radio"][data-mode="satellite"]')?.getAttribute('aria-checked'),
    );
    check(satChecked === 'true', 'style picker marks satellite as the selected radio', String(satChecked));
    await page.evaluate(() => document.querySelector('button[aria-label="Map details (standard / satellite / terrain)"]')?.click());

    console.log('\n[2] Satellite -> Terrain');
    const beforeTerr = await readCamera(page);
    await page.evaluate(() => { window.__premiumLong.length = 0; });
    check(await chooseStyle(page, 'terrain'), 'terrain chosen through the style picker');
    // The topo raster is cross-faded first (tile gate <=1.2 s + 420/80 ms fade)
    // and DEM displacement is enabled once that fade lands, so that a visible
    // basemap never gets replaced by a blank canvas. Wait for the deferred
    // enable instead of assuming it happened at click time.
    await sleep(700);
    await page
      .waitForFunction(() => !!window.__maplibreMap?.getTerrain(), { timeout: 5000 })
      .catch(() => {});
    const terr = await page.evaluate(() => {
      const m = window.__maplibreMap;
      return {
        sameInstance: m === window.__mapIdentity,
        terrainOpacity: m.getPaintProperty('terrain-layer', 'raster-opacity'),
        satelliteOpacity: m.getPaintProperty('satellite-layer', 'raster-opacity'),
        massing: m.getLayer('3d-buildings') ? m.getLayoutProperty('3d-buildings', 'visibility') : 'absent',
        hillshade: m.getPaintProperty('hillshade-layer', 'hillshade-exaggeration'),
        saturation: m.getPaintProperty('terrain-layer', 'raster-saturation'),
        hasTerrain: Boolean(m.getTerrain()),
        long: window.__premiumLong.slice(),
      };
    });
    const afterTerr = await readCamera(page);
    check(terr.sameInstance, 'terrain switch keeps the same MapLibre instance');
    check(sameCamera(beforeTerr, afterTerr), 'centre, zoom and bearing are preserved into terrain', JSON.stringify({ beforeTerr, afterTerr }));
    check(terr.terrainOpacity === 1, 'topographic raster is visible', String(terr.terrainOpacity));
    check(terr.satelliteOpacity === 0, 'satellite is fully covered in terrain mode');
    check(terr.massing === 'none', 'building massing is removed over relief');
    check(terr.hasTerrain === true, 'DEM displacement is active');
    check(Math.abs(terr.hillshade - 0.32) < 0.001, 'hillshade exaggeration is restrained (0.32)', String(terr.hillshade));
    check(Math.abs(terr.saturation + 0.18) < 0.001, 'topo raster is gently desaturated (-0.18)', String(terr.saturation));
    check(terr.long.every((d) => d <= 320), 'terrain switch has no long task over 320 ms', terr.long.join(', ') || 'none');
    await openStylePicker(page);
    const terrChecked = await page.evaluate(
      () => document.querySelector('button[role="radio"][data-mode="terrain"]')?.getAttribute('aria-checked'),
    );
    check(terrChecked === 'true', 'style picker marks terrain as selected', String(terrChecked));
    await page.evaluate(() => document.querySelector('button[aria-label="Map details (standard / satellite / terrain)"]')?.click());

    console.log('\n[3] Theme swap while terrain is active');
    await page.evaluate(() => {
      document.querySelector('button[aria-label="Toggle light / dark theme"]')?.click();
    });
    await sleep(2400);
    const dark = await page.evaluate(() => {
      const m = window.__maplibreMap;
      return {
        theme: document.documentElement.dataset.theme,
        visible: m.getLayoutProperty('terrain-layer', 'visibility'),
        opacity: m.getPaintProperty('terrain-layer', 'raster-opacity'),
        brightnessMax: m.getPaintProperty('terrain-layer', 'raster-brightness-max'),
        massing: m.getLayer('3d-buildings') ? m.getLayoutProperty('3d-buildings', 'visibility') : 'absent',
      };
    });
    check(dark.theme === 'dark', 'dark theme applied');
    check(
      dark.visible === 'visible' && dark.opacity === 1,
      'terrain raster survives the theme style reload (no blank dark map)',
      JSON.stringify(dark),
    );
    check(Math.abs(dark.brightnessMax - 0.66) < 0.001, 'dark terrain ceiling is lowered for dark chrome', String(dark.brightnessMax));
    check(dark.massing === 'none', 'massing stays off after the style reload');

    console.log('\n[4] Reduced motion');
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    const beforeReduced = await readCamera(page);
    await chooseStyle(page, 'standard');
    await sleep(700);
    const reduced = await page.evaluate(() => {
      const m = window.__maplibreMap;
      const btn = document.querySelector('button[aria-label="Map details (standard / satellite / terrain)"]');
      return {
        moving: m.isMoving(),
        transition: btn ? getComputedStyle(btn).transitionDuration : null,
        style: document.querySelector('[data-map-style]')?.getAttribute('data-map-style'),
      };
    });
    const afterReduced = await readCamera(page);
    check(reduced.style === 'standard', 'style switch still works under reduced motion');
    check(sameCamera(beforeReduced, afterReduced), 'reduced motion does not move the camera', JSON.stringify({ beforeReduced, afterReduced }));
    check(reduced.moving === false, 'no camera ease is left running');
    const transitionSeconds = parseFloat(String(reduced.transition || '1').replace('ms', '')) || 0;
    check(
      String(reduced.transition || '').endsWith('ms')
        ? transitionSeconds <= 0.01
        : transitionSeconds <= 0.0001,
      'CSS transitions collapse under prefers-reduced-motion',
      String(reduced.transition),
    );
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]);

    console.log('\n[5] Plot selection frames, dismissal restores');
    // A clean page avoids the theme/mode state accumulated above.
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 60000 });
    await waitForMap(page);
    await sleep(900);
    const beforeCapture = await readCamera(page);
    const opened = await clickByLabel(page, 'Select Location on Map to Begin');
    check(opened, 'capture wizard opens from the first-run CTA');
    await page.waitForFunction(() => /Locate the site/.test(document.body.innerText || ''), { timeout: 15000 });
    await clickByLabel(page, 'Trace boundary');
    await page.waitForSelector('[data-testid="trace-toolbar-presets"]', { timeout: 15000 });
    await page.click('[data-testid="trace-toolbar-presets"]');
    await page.waitForSelector('[data-testid="preset-menu"]', { timeout: 8000 });
    await page.click('[data-testid="preset-item-rect"]');
    await sleep(900);
    await clickByLabel(page, 'Finish');
    await page.waitForFunction(() => /Confirm the frontage/.test(document.body.innerText || ''), { timeout: 30000 });
    // Accept the suggested frontage when it is offered (ASSUMED -> VERIFIED),
    // then review and commit. This is the same path the full-funnel E2E uses.
    await page.evaluate(() => {
      const accept = Array.from(document.querySelectorAll('button')).find(
        (b) => (b.textContent || '').trim() === 'Accept' && !b.disabled,
      );
      accept?.click();
    });
    // No road suggestion (offline/first-run) leaves the picker manual; choose
    // the first listed edge so the wizard always has a frontage to review.
    await page.evaluate(() => {
      const row = document.querySelector('[data-testid="edge-row-0"]');
      if (row) row.click();
    });
    await sleep(300);
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('button')).some(
        (b) => (b.textContent || '').trim() === 'Review' && !b.disabled,
      ),
      { timeout: 15000 },
    );
    await clickByLabel(page, 'Review');
    await page.waitForFunction(() => /Review boundary/.test(document.body.innerText || ''), { timeout: 15000 });
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('button')).some((b) => (b.textContent || '').includes('Use this boundary') && !b.disabled),
      { timeout: 30000 },
    );
    await clickByLabel(page, 'Use this boundary');
    await page.waitForSelector('[data-testid="site-preview-hud"]', { timeout: 15000 });
    await sleep(1300);
    const selected = await readCamera(page);
    check(
      selected.zoom > beforeCapture.zoom + 0.3,
      'selected plot is framed by a camera move',
      `zoom ${beforeCapture.zoom.toFixed(2)} -> ${selected.zoom.toFixed(2)}`,
    );
    check(
      Math.abs(selected.bearing - beforeCapture.bearing) < 0.01,
      'selection keeps the reader bearing',
      `${beforeCapture.bearing.toFixed(2)} -> ${selected.bearing.toFixed(2)}`,
    );
    const dismissed = await page.evaluate(() => {
      const btn = document.querySelector('button[aria-label="Dismiss site preview"]');
      if (!btn) return false;
      btn.click();
      return true;
    });
    check(dismissed, 'site preview panel exposes a dismiss control');
    await sleep(1000);
    const restored = await readCamera(page);
    check(
      sameCamera(beforeCapture, restored, 5e-4),
      'dismissing the property panel restores the pre-capture camera',
      JSON.stringify({ beforeCapture, restored }),
    );

    console.log('\n[6] Compact drawer entrance/exit');
    await page.setViewport({ width: 390, height: 844 });
    await sleep(900);
    const drawerOpened = await clickByLabel(page, 'Controls');
    await page.waitForSelector('#controls-drawer', { timeout: 5000 });
    await sleep(80);
    const drawerIn = await page.evaluate(() => {
      const el = document.querySelector('#controls-drawer');
      return {
        side: el?.getAttribute('data-side'),
        animation: el ? getComputedStyle(el).animationName : null,
        exiting: el?.getAttribute('data-exiting'),
      };
    });
    check(drawerOpened && drawerIn.side === 'bottom', 'compact controls drawer opens as a bottom sheet', JSON.stringify(drawerIn));
    check(/bwDrawerInBottom/.test(drawerIn.animation || ''), 'drawer enters with its edge transition', String(drawerIn.animation));
    await page.evaluate(() => {
      document.querySelector('#controls-drawer button[aria-label="Close parameters panel"]')?.click();
    });
    await sleep(60);
    const drawerOut = await page.evaluate(() => {
      const el = document.querySelector('#controls-drawer');
      return el ? { exiting: el.getAttribute('data-exiting'), animation: getComputedStyle(el).animationName } : null;
    });
    check(drawerOut && drawerOut.exiting === 'true', 'drawer stays mounted for its exit animation', JSON.stringify(drawerOut));
    check(/bwDrawerOutBottom/.test(drawerOut?.animation || ''), 'drawer leaves with the matching edge transition', String(drawerOut?.animation));
    await sleep(400);
    const drawerGone = await page.evaluate(() => !document.querySelector('#controls-drawer'));
    check(drawerGone, 'drawer unmounts after the exit completes');

    check(consoleErrors.length === 0, 'no console errors', consoleErrors.slice(0, 2).join(' | '));
    check(pageErrors.length === 0, 'no page errors', pageErrors.slice(0, 2).join(' | '));
  } catch (err) {
    check(false, 'run completed without an exception', String((err && err.stack) || err).slice(0, 1000));
  } finally {
    const failed = results.filter((r) => !r.ok).length;
    console.log(`\n=== premium map UX: ${results.length - failed} passed, ${failed} failed ===`);
    await browser.close();
    process.exit(failed ? 1 : 0);
  }
})();
