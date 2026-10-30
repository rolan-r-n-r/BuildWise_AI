/**
 * e2e_full_funnel.cjs — browser E2E for the full funnel.
 * ============================================================================
 * Walks the real UI end-to-end against local dev servers and fails on any
 * browser console error / page error:
 *
 *   capture (Update Pin) -> site feasibility -> Cost & Plan -> generate
 *   blueprint -> viewer assertions:
 *     - the viewer's GEN token equals the SERVER generation_id
 *       (no client-side random token anywhere);
 *     - the QA panel lists all 14 gate layers (L1..L14) and the
 *       overall status chip, never silently fewer rows;
 *     - the sheet-truth chips carry FRTG (frontage) + POLYHASH.
 *
 * Usage:
 *   node scripts/e2e_full_funnel.cjs
 * Env:
 *   E2E_URL        app URL (default http://localhost:5173)
 *   CHROME_PATH    Chrome executable (defaults to the known local install)
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const os = require('os');
const path = require('path');

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
    try { if (fs.existsSync(p)) return p; } catch (e) { /* ignore */ }
  }
  throw new Error('Chrome not found. Set CHROME_PATH to the Chrome executable.');
}

const results = [];
function check(ok, label, detail) {
  results.push({ ok, label, detail });
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Click the first button whose text contains `label` (real DOM click). */
async function clickByLabel(page, label) {
  return page.evaluate((needle) => {
    const btn = Array.from(document.querySelectorAll('button'))
      .find((b) => (b.textContent || '').includes(needle));
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  }, label);
}

/**
 * Trace a rectangle through the path the UI actually offers. The flat "Rect"
 * tool this script used to click was replaced by [Draw][Edit][Import][Presets],
 * so the look-up matched nothing and the run died waiting for the frontage
 * step. The preset seeds a CLOSED 4-vertex ring, which still has to be finished
 * before the wizard hands over to the frontage step.
 */
/*
 * Deterministic upstream fixtures for the capture-side surfaces the audit
 * listed as UNVERIFIED. These stub the PROVIDERS, not the app: the request/
 * response shapes are the ones the frontend actually consumes, so the wiring,
 * payload and rendering are real.
 */
const GEOCODE_FIXTURE = {
  results: [
    { display_name: 'E2E Locality, Bengaluru, Karnataka, India', lat: 12.9716, lon: 77.5946, source: 'nominatim' },
  ],
  provider: 'nominatim',
  cached: false,
  error: null,
};

const KML_FIXTURE = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>E2E KML plot</name>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
77.5946,12.9716,0 77.5950,12.9716,0 77.5950,12.9719,0 77.5946,12.9719,0 77.5946,12.9716,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>`;

const VISION_FIXTURE = {
  mode: 'index-only',
  scene_metadata: { id: 'S2B_E2E', datetime: '2026-10-01T05:20:00Z', cloud_cover_pct: 3.1, source: 'Sentinel-2' },
  green_cover_pct: 37.5,
  water_cover_pct: 1.2,
  built_up_pct: 18.4,
  tree_clusters: {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[77.5946, 12.9716], [77.59465, 12.9716], [77.59465, 12.97165], [77.5946, 12.97165], [77.5946, 12.9716]]] },
        properties: { cluster_id: 'T1', area_sqm: 120.5, mean_ndvi: 0.61, rank: 'preserve' },
      },
      {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[77.5948, 12.9717], [77.59485, 12.9717], [77.59485, 12.97175], [77.5948, 12.97175], [77.5948, 12.9717]]] },
        properties: { cluster_id: 'T2', area_sqm: 44.0, mean_ndvi: 0.42, rank: 'monitor' },
      },
    ],
  },
  water_bodies: { type: 'FeatureCollection', features: [] },
  preservation_plan: [
    { cluster_id: 'T1', area_sqm: 120.5, centroid: [77.59462, 12.97162], mean_ndvi: 0.61, overlap_footprint: false, rank: 'preserve', action: 'Retain and protect during construction' },
    { cluster_id: 'T2', area_sqm: 44.0, centroid: [77.59482, 12.97172], mean_ndvi: 0.42, overlap_footprint: false, rank: 'monitor', action: 'Monitor during works' },
  ],
  warnings: [],
  timing_ms: { total_ms: 812 },
};

async function traceRectPreset(page) {
  await page.click('[data-testid="trace-toolbar-presets"]');
  await page.waitForSelector('[data-testid="preset-menu"]', { timeout: 8000 });
  await page.click('[data-testid="preset-item-rect"]');
  await sleep(900);
  await clickByLabel(page, 'Finish');
}

async function main() {
  console.log('=== E2E: full funnel ===');
  const browser = await puppeteer.launch({
    executablePath: resolveChrome(),
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1600,1000'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });

  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
      console.log('[console error]', msg.text().slice(0, 200));
    }
  });
  page.on('pageerror', (err) => {
    pageErrors.push(String(err && err.message || err));
    console.log('[page error]', String(err && err.message || err).slice(0, 200));
  });
  const apiFailures = [];
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) {
      apiFailures.push(`${res.status()} ${res.url()}`);
      console.log('[api failure]', res.status(), res.url());
    }
  });

  // Every analysis body, so "one site" can be checked where it matters: the
  // request the app actually sends, the boundary inside it and the card the
  // reader is looking at.
  const analyzeBodies = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes('/api/analyze')) {
      try { analyzeBodies.push(JSON.parse(req.postData() || '{}')); } catch (e) { analyzeBodies.push(null); }
    }
  });

  let serverGenerationId = null;
  page.on('response', async (res) => {
    if (res.url().includes('/api/generate-floorplan') && res.request().method() === 'POST') {
      try {
        const body = await res.json();
        serverGenerationId = body && body.generation_id ? String(body.generation_id) : null;
      } catch (e) { /* non-JSON response surfaces via console/page errors */ }
    }
  });

  try {
    console.log(`- loading ${URL}`);
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await sleep(2000);
    check(true, 'app loaded');

    // 1. capture: the pre-boundary CTA opens the capture wizard (STEP ZERO).
    console.log('- capture: opening the capture wizard');
    const ctaLabel = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => b.textContent && /Run Site Feasibility Analysis|Select Location on Map to Begin/.test(b.textContent));
      if (!btn) return null;
      if (btn.disabled) return `disabled:${btn.textContent.trim()}`;
      btn.click();
      return btn.textContent.trim();
    });
    check(ctaLabel && !ctaLabel.startsWith('disabled:'), 'pre-boundary CTA is enabled (not a dead end)', ctaLabel || 'not found');
    await page.waitForFunction(
      () => /Locate the site/.test(document.body.innerText || ''),
      { timeout: 15000 },
    );
    check(true, 'capture wizard opened on LOCATE');

    // 2. trace a rectangle from the pin (quick path), then commit the boundary.
    console.log('- tracing a rectangular boundary');
    await clickByLabel(page, 'Trace boundary');
    await sleep(800);
    await traceRectPreset(page);
    await page.waitForFunction(
      () => /Confirm the frontage/.test(document.body.innerText || ''),
      { timeout: 40000 },
    );
    // Stray-geometry guard: on FRONTAGE the dashed live-edge must be empty even
    // as the pointer moves (it is a TRACE-only affordance).
    const frontageLine = await page.evaluate(() => {
      const m = window.__maplibreMap;
      if (!m) return { available: false };
      const canvas = m.getCanvas();
      const r = canvas.getBoundingClientRect();
      for (const [x, y] of [[500, 300], [700, 500], [420, 700]]) {
        canvas.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: r.left + x, clientY: r.top + y }));
      }
      return new Promise((resolve) => setTimeout(() => {
        const live = m.getSource('bw-capture-live').serialize().data;
        resolve({
          available: true,
          liveCoords: (live.geometry && live.geometry.coordinates || []).length,
          massing: m.getLayer('3d-buildings') ? m.getLayoutProperty('3d-buildings', 'visibility') : 'absent',
        });
      }, 400));
    });
    check(frontageLine.available && frontageLine.liveCoords === 0, 'no stray dashed live edge on the FRONTAGE step', JSON.stringify(frontageLine));
    check(frontageLine.massing === 'none', 'basemap 3D massing suppressed over the site (no square on the pin)', JSON.stringify(frontageLine));

    // Per-edge callouts: the sheet lists every edge with its length + bearing.
    const rows = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[data-testid^="edge-row-"]')).map((el) => el.textContent.trim())
    );
    const measured = rows.filter((t) => /\d+\.\d{2} m · [NSEW] \d{2}°\d{2}′ [NSEW]/.test(t));
    check(rows.length >= 3, `per-edge callout rows rendered (${rows.length})`, rows.join(' | '));
    check(measured.length === rows.length && rows.length > 0, 'every edge row reports length + bearing');

    // Precision pick: hover, then click THAT edge, and assert the same edge is taken.
    const pick = await page.evaluate(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const m = window.__maplibreMap;
      // Wait for the camera fit to settle before computing pixels.
      for (let i = 0; i < 40 && m.isMoving(); i++) await sleep(100);
      const canvas = m.getCanvas();
      const rect = canvas.getBoundingClientRect();
      const ring = m.getSource('bw-capture-boundary').serialize().data.geometry.coordinates[0];
      const midOf = (i) => [(ring[i][0] + ring[i + 1][0]) / 2, (ring[i][1] + ring[i + 1][1]) / 2];
      const at = (lngLat) => { const p = m.project(lngLat); return { clientX: rect.left + p.x, clientY: rect.top + p.y, p }; };
      const pickIndexOf = () => {
        const r = Array.from(document.querySelectorAll('[data-testid^="edge-row-"]'));
        return r.findIndex((el) => /PICKED/.test(el.textContent || ''));
      };
      const target = 1;
      const t = at(midOf(target));
      canvas.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: t.clientX, clientY: t.clientY }));
      await sleep(350);
      const hover = m.getSource('bw-capture-hover-edge').serialize().data;
      const readout = document.querySelector('[data-testid="frontage-hover-readout"]');
      const badge = document.querySelector('[data-testid="frontage-hover-badge"]');
      const hovered = {
        coords: (hover.geometry && hover.geometry.coordinates || []).length,
        readout: readout ? readout.textContent.trim() : null,
        badge: badge ? badge.textContent.trim() : null,
        zoom: Number(m.getZoom().toFixed(2)),
      };
      canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: t.clientX, clientY: t.clientY }));
      await sleep(350);
      const pickedIdx = pickIndexOf();

      // Table pick: clicking a row picks that exact edge too.
      const rowTwo = document.querySelector('[data-testid="edge-row-2"]');
      if (rowTwo) rowTwo.click();
      await sleep(300);
      const pickedViaRow = pickIndexOf();

      // Off-edge click on empty map: the pick must NOT silently move elsewhere.
      canvas.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: rect.left + 60, clientY: rect.top + rect.height - 60 }));
      await sleep(250);
      canvas.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: rect.left + 60, clientY: rect.top + rect.height - 60 }));
      await sleep(350);
      return {
        hovered,
        pickedIdx,
        pickedViaRow,
        afterMissIdx: pickIndexOf(),
        missHint: Boolean(document.querySelector('[data-testid="frontage-miss-hint"]')),
      };
    });
    check(pick.hovered.coords === 2, 'hovering an edge highlights exactly that edge', JSON.stringify(pick.hovered));
    check(Boolean(pick.hovered.readout), 'hover readout names the edge with its measurement', pick.hovered.readout || 'none');
    check(Boolean(pick.hovered.badge), 'pointer badge shows the hovered edge measurement', pick.hovered.badge || 'none');
    check(pick.hovered.zoom >= 19, 'camera frames the plot for precise picking', `zoom ${pick.hovered.zoom}`);
    check(pick.pickedIdx === 1, 'clicking the hovered edge picks THAT edge', `picked index ${pick.pickedIdx}`);
    check(pick.pickedViaRow === 2, 'clicking an edge row picks THAT edge', `row pick index ${pick.pickedViaRow}`);
    check(pick.afterMissIdx === pick.pickedViaRow, 'an off-edge click never re-picks a random edge', `after miss ${pick.afterMissIdx}`);
    check(pick.missHint, 'an off-edge click surfaces the pick hint instead of guessing');

    // If the suggestion still stands (no manual pick), accept it as ASSUMED -> VERIFIED.
    const alreadyConfirmed = await page.evaluate(() => /PICKED/.test(document.body.innerText));
    if (!alreadyConfirmed) {
      await page.waitForFunction(
        () => {
          const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Accept');
          return Boolean(btn) && !btn.disabled;
        },
        { timeout: 40000 },
      );
      const accepted = await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Accept');
        if (btn) { btn.click(); return true; }
        return false;
      });
      check(accepted, 'frontage suggestion accepted (ASSUMED -> VERIFIED)');
    }
    check(true, 'frontage confirmed (VERIFIED)');
    await page.waitForFunction(
      () => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Review');
        return Boolean(btn) && !btn.disabled;
      },
      { timeout: 15000 },
    );
    await clickByLabel(page, 'Review');
    await page.waitForFunction(
      () => /Review boundary/.test(document.body.innerText || ''),
      { timeout: 15000 },
    );
    // an edge indexes TWO vertices. The old label interpolated
    // (index % n) + 1, so edge 1 read P2–P2. Assert the pair is distinct and
    // wraps correctly for every ring size the capture can produce.
    const frontageLabel = await page.evaluate(() => {
      const m = (document.body.innerText || '').match(/Frontage: edge P(\d+)–P(\d+)/);
      return m ? { a: Number(m[1]), b: Number(m[2]) } : null;
    });
    check(
      Boolean(frontageLabel) && frontageLabel.a !== frontageLabel.b,
      'frontage label names two distinct vertices',
      JSON.stringify(frontageLabel),
    );
    await page.waitForFunction(
      () => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').includes('Use this boundary'));
        return Boolean(btn) && !btn.disabled;
      },
      { timeout: 15000 },
    );
    await clickByLabel(page, 'Use this boundary');
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('button'))
        .some((b) => (b.textContent || '').includes('Run Site Feasibility Analysis')),
      { timeout: 15000 },
    );
    check(true, 'boundary committed; CTA enabled for analysis');

    // Bbox-derived width/depth are differences of geodesic floats.
    // They must reach the inputs at centimetre precision, not as
    // 89.05499999999999.
    const numberValues = await page.evaluate(() =>
      Array.from(document.querySelectorAll('input[type="number"]'))
        .map((el) => el.value)
        .filter((v) => v !== ''),
    );
    check(
      numberValues.every((v) => /^-?\d+(\.\d{1,2})?$/.test(v)),
      'numeric inputs carry no float residue',
      numberValues.filter((v) => !/^-?\d+(\.\d{1,2})?$/.test(v)).join(', '),
    );

    // 3. site feasibility
    console.log('- running site feasibility analysis');
    // Satellite vision: upstream imagery is stubbed so the run is deterministic.
    // The analysis auto-runs a scan as soon as it starts, so the stub must be in
    // place BEFORE the analyze click — otherwise a cold model load (~70 s) leaves
    // the Ecology card in its skeleton past any reasonable wait.
    let visionRequest = null;
    const visionHandler = (req) => {
      if (req.url().includes('/api/site-vision') && req.method() === 'POST') {
        try { visionRequest = JSON.parse(req.postData() || '{}'); } catch (e) { visionRequest = {}; }
        req.respond({
          status: 200,
          contentType: 'application/json',
          headers: { 'access-control-allow-origin': '*' },
          body: JSON.stringify(VISION_FIXTURE),
        });
        return;
      }
      req.continue();
    };
    await page.setRequestInterception(true);
    page.on('request', visionHandler);
    await clickByLabel(page, 'Run Site Feasibility Analysis');
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll('button'))
        .some((b) => b.textContent && b.textContent.includes('Cost & Plan')),
      { timeout: 90000 },
    );
    await sleep(1500);
    check(true, 'site feasibility report opened (Cost & Plan reachable)');

    // at 390 the report section tray scrolls, and the fade is a
    // measurement: the right edge fades before scrolling, the left edge
    // after. A permanent fade (or none at all) fails this.
    //
    // Resize only — no isMobile emulation: that swaps the capture flow's
    // layout and resets the page state under the rest of the funnel. CSS
    // Breakpoints are width-driven, which is exactly what the 390 px pass measured.
    await page.setViewport({ width: 390, height: 844 });
    await sleep(900);
    // Park the tray at its start so the measurement is deterministic: the
    // funnel may already have scrolled it while navigating sections.
    await page.evaluate(() => {
      const tray = document.querySelector('[data-testid="section-nav"] .bw-section-nav-scroll');
      if (tray) tray.scrollLeft = 0;
    });
    await sleep(350);
    const navStart = await page.evaluate(() => {
      const tray = document.querySelector('[data-testid="section-nav"] .bw-section-nav-scroll');
      if (!tray) return null;
      return {
        overflow: tray.getAttribute('data-overflow'),
        fadeR: getComputedStyle(tray).getPropertyValue('--bw-nav-fade-r').trim(),
        fadeL: getComputedStyle(tray).getPropertyValue('--bw-nav-fade-l').trim(),
        scrollable: tray.scrollWidth > tray.clientWidth + 1,
      };
    });
    check(
      Boolean(navStart) && navStart.scrollable,
      'report section nav scrolls at 390px',
      JSON.stringify(navStart),
    );
    // The fade must agree with the measured edges, whichever side the funnel
    // left the tray on: no fade on a side with nothing behind it, 18px on a
    // side that is clipping pills.
    const fadesAgree =
      Boolean(navStart) &&
      navStart.overflow !== 'none' &&
      navStart.fadeR === (navStart.overflow === 'end' || navStart.overflow === 'both' ? '18px' : '0px') &&
      navStart.fadeL === (navStart.overflow === 'start' || navStart.overflow === 'both' ? '18px' : '0px');
    check(fadesAgree, 'each clipped edge carries the fade affordance', JSON.stringify(navStart));
    await page.evaluate(() => {
      const tray = document.querySelector('[data-testid="section-nav"] .bw-section-nav-scroll');
      if (tray) tray.scrollLeft = tray.scrollWidth;
    });
    await sleep(350);
    const navEnd = await page.evaluate(() => {
      const tray = document.querySelector('[data-testid="section-nav"] .bw-section-nav-scroll');
      if (!tray) return null;
      return {
        overflow: tray.getAttribute('data-overflow'),
        fadeR: getComputedStyle(tray).getPropertyValue('--bw-nav-fade-r').trim(),
        fadeL: getComputedStyle(tray).getPropertyValue('--bw-nav-fade-l').trim(),
      };
    });
    check(
      Boolean(navEnd) && (navEnd.overflow === 'start' || navEnd.overflow === 'none') && navEnd.fadeR === '0px',
      'the fade follows the scroll position instead of staying fixed',
      JSON.stringify(navEnd),
    );
    await page.setViewport({ width: 1600, height: 1000 });
    await sleep(700);


    // 3.2 One site. The plot owns the location, so the body the analysis ran on,
    // the boundary inside it and the coordinate card must be the same place —
    // otherwise the report would describe a different site than the plot drawn
    // on the map (the bug this guards against).
    const analyze = analyzeBodies.find((b) => b && b.boundary) || null;
    const coordCard = await page.evaluate(() => {
      const field = (id) => (document.getElementById(id) || {}).value || '';
      return { lat: field('lat-input'), lon: field('lon-input') };
    });
    check(Boolean(analyze), 'the analysis request body was captured');
    if (analyze) {
      const same = (a, b) => Math.abs(a - b) < 1e-9;
      check(
        same(analyze.latitude, analyze.boundary.origin_lat) && same(analyze.longitude, analyze.boundary.origin_lon),
        'the analysis asks about the plot it was handed (request coords == boundary origin)',
        `request ${analyze.latitude},${analyze.longitude} vs origin ${analyze.boundary.origin_lat},${analyze.boundary.origin_lon}`,
      );
      check(
        analyze.boundary.vertices.length >= 3,
        'the analysis carried the captured ring, not just a point',
        `${analyze.boundary.vertices.length} vertices`,
      );
      check(
        Math.abs(analyze.latitude - Number(coordCard.lat)) < 5e-5 &&
        Math.abs(analyze.longitude - Number(coordCard.lon)) < 5e-5,
        'the coordinate card shows the site that was analysed',
        `card ${coordCard.lat},${coordCard.lon} vs request ${analyze.latitude},${analyze.longitude}`,
      );
    }

    // 3.5 Gestalt guard: a captured plot renders as ONE plot with ONE
    // buildable envelope and ONE building outline, all ON the plot - and the
    // analysis-derived, pin-anchored estimate stands down so the marker never
    // drags a second boundary along with it. The server geometry engine used to
    // emit the buildable/footprint in a corner-based frame, displacing them off
    // the plot by half its size ("several other boundaries" beside the pin).
    await sleep(900);
    const gestalt = await page.evaluate(() => {
      const m = window.__maplibreMap;
      const coordsOf = (id) => {
        const s = m.getSource(id);
        if (!s) return null;
        const d = s.serialize().data;
        const f = d.features ? d.features[0] : d;
        const g = f && f.geometry;
        if (!g || !g.coordinates || !g.coordinates.length) return null;
        if (g.type === 'Point') return g.coordinates;
        if (g.type === 'LineString') return g.coordinates;
        return g.coordinates[0].length ? g.coordinates[0] : null;
      };
      const featuresOf = (id) => {
        const s = m.getSource(id);
        return s ? (s.serialize().data.features || []).length : -1;
      };
      return {
        plot: coordsOf('bw-preview-setback'),
        buildable: coordsOf('bw-preview-buildable'),
        previewFootprint: coordsOf('bw-preview-footprint'),
        appFootprintFeatures: featuresOf('footprint-source'),
        appEntranceFeatures: featuresOf('entrance-shaft-source'),
      };
    });
    const centroidOf = (ring) => {
      const s = ring.reduce((a, c) => [a[0] + c[0], a[1] + c[1]], [0, 0]);
      return [s[0] / ring.length, s[1] / ring.length];
    };
    const insideRing = (p, ring) => {
      if (!ring || ring.length < 3) return false;
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i];
        const [xj, yj] = ring[j];
        if (
          yi > p[1] !== yj > p[1] &&
          p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi
        ) {
          inside = !inside;
        }
      }
      return inside;
    };
    check(Boolean(gestalt.plot && gestalt.plot.length >= 4), 'the captured plot is drawn as its own ring');
    check(
      Boolean(gestalt.buildable && insideRing(centroidOf(gestalt.buildable), gestalt.plot)),
      'preview buildable envelope sits ON its plot (not offset beside it)',
      JSON.stringify(gestalt.buildable),
    );
    check(
      Boolean(gestalt.previewFootprint && insideRing(centroidOf(gestalt.previewFootprint), gestalt.plot)),
      'preview building footprint sits ON its plot (not offset beside it)',
      JSON.stringify(gestalt.previewFootprint),
    );
    check(
      gestalt.appFootprintFeatures === 0,
      'no pin-anchored estimate rectangle while a plot is captured',
      `features ${gestalt.appFootprintFeatures}`,
    );
    check(
      gestalt.appEntranceFeatures === 0,
      'no pin-anchored entrance arrow while a plot is captured',
      `features ${gestalt.appEntranceFeatures}`,
    );

    // 3. Cost & Plan tab hosts the generator card.
    await page.evaluate(() => {
      const tab = Array.from(document.querySelectorAll('button'))
        .find((b) => b.textContent && b.textContent.includes('Cost & Plan'));
      if (tab) tab.click();
    });
    await sleep(1500);

    // 4. generate the blueprint
    console.log('- generating blueprint');
    const genClicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => b.textContent && /Generate .*(Blueprint|Floor Plan)|Regenerate Blueprint/.test(b.textContent));
      if (btn) { btn.click(); return btn.textContent.trim(); }
      return null;
    });
    check(Boolean(genClicked), 'generate button found', genClicked || 'none');
    await page.waitForResponse(
      (res) => res.url().includes('/api/generate-floorplan') && res.request().method() === 'POST',
      { timeout: 60000 },
    );
    await sleep(4000);
    check(Boolean(serverGenerationId), 'server returned a generation_id', serverGenerationId || 'none');

    // The report sheet skips layout/paint for off-screen sections
    // (`content-visibility: auto`), and `innerText` of a skipped subtree is
    // empty. That is a paint optimisation, not behaviour: force it visible so
    // the assertions read the whole dossier no matter where the page is
    // scrolled after the plan expands.
    await page.evaluate(() => {
      if (document.getElementById('e2e-show-all-sections')) return;
      const style = document.createElement('style');
      style.id = 'e2e-show-all-sections';
      style.textContent =
        '.report-sheet-content [data-report-section]{content-visibility: visible !important;}';
      document.head.appendChild(style);
    });
    await sleep(300);

    // 5. viewer assertions
    const ui = await page.evaluate(() => {
      const text = document.body.innerText || '';
      const layerIds = Array.from({ length: 14 }, (_, i) => `L${i + 1}`);
      const missingLayers = layerIds.filter((lid) => !new RegExp(`\\b${lid}\\b`).test(text));
      return {
        hasGenToken: /GEN-/.test(text),
        genTokens: Array.from(new Set((text.match(/GEN-[A-Za-z0-9-]+/g) || []))),
        missingLayers,
        hasOverall: /OVERALL/.test(text),
        hasFrtg: /\bFRTG\b/.test(text),
        hasPolyHash: /\bPOLYHASH\b/.test(text),
        hasRandomishGen: /GEN-\d+\.\d+/.test(text),
      };
    });

    check(ui.hasGenToken, 'viewer shows a GEN token');
    check(
      Boolean(serverGenerationId) && ui.genTokens.includes(serverGenerationId),
      'viewer GEN token equals the server generation_id',
      `server=${serverGenerationId} ui=${ui.genTokens.join(',')}`,
    );
    check(!ui.hasRandomishGen, 'no float/random GEN token in the DOM');
    check(
      ui.missingLayers.length === 0,
      'QA panel lists all 14 gate layers (no silent rows)',
      ui.missingLayers.length ? `missing ${ui.missingLayers.join(',')}` : '',
    );
    check(ui.hasOverall, 'QA panel shows the overall status');
    check(ui.hasFrtg, 'sheet-truth frontage chip present (FRTG)');
    check(ui.hasPolyHash, 'sheet-truth polygon hash chip present (POLYHASH)');

    // 5b. Sheet fit guard: the sheet the viewer is showing must be displayed WHOLE
    // inside its box. A tall site plan (10.SP) used to be rendered at native size and
    // cut off at the bottom, so the plate appeared to be "out of the view".
    const sheetFit = await page.evaluate(() => {
      const sheets = Array.from(document.querySelectorAll('svg.bw-sheet-fit'))
        .filter((s) => s.getBoundingClientRect().width > 0 && s.getBoundingClientRect().height > 0);
      if (!sheets.length) return { found: false };
      const svg = sheets[0];
      const r = svg.getBoundingClientRect();
      let box = svg.parentElement;
      while (box && box !== document.body && box.getBoundingClientRect().height < 50) {
        box = box.parentElement;
      }
      const b = (box || document.body).getBoundingClientRect();
      const vb = (svg.getAttribute('viewBox') || '').trim().split(/\s+/).map(Number);
      return {
        found: true,
        sheet: [Math.round(r.width), Math.round(r.height)],
        box: [Math.round(b.width), Math.round(b.height)],
        fits: r.width <= b.width + 1 && r.height <= b.height + 1,
        sheetRatio: vb.length === 4 && vb[3] > 0 ? vb[2] / vb[3] : 0,
        renderedRatio: r.height > 0 ? r.width / r.height : 0,
      };
    });
    check(sheetFit.found, 'viewer renders a fitted sheet (bw-sheet-fit host present)');
    check(
      sheetFit.found && sheetFit.fits,
      'the whole sheet is on screen (no clipping in the viewer box)',
      sheetFit.found ? `sheet ${sheetFit.sheet.join('x')} in box ${sheetFit.box.join('x')}` : 'no sheet',
    );
    check(
      sheetFit.found && sheetFit.sheetRatio > 0 && Math.abs(sheetFit.renderedRatio - sheetFit.sheetRatio) < 0.02,
      'the fitted sheet keeps its drawing aspect ratio',
      sheetFit.found ? `sheet ${sheetFit.sheetRatio.toFixed(3)} vs rendered ${sheetFit.renderedRatio.toFixed(3)}` : 'no sheet',
    );

    // 5c. Scheme & land economics surfaces: the land-economics certificate panel and the scheme
    // picker are mounted from the response, and picking a profile asks the
    // server to re-solve (it is not a local relabel).
    const schemeSurfaces = await page.evaluate(() => ({
      landPanel: Boolean(document.querySelector('[data-testid="land-economics-panel"]')),
      landChecks: document.querySelectorAll('[data-testid="land-economics-checks"] li').length,
      landKpis: document.querySelectorAll('[data-testid="land-economics-kpis"] > div').length,
      picker: Boolean(document.querySelector('[data-testid="scheme-picker"]')),
      options: Array.from(document.querySelectorAll('[data-testid^="scheme-option-"]')).map((b) =>
        b.getAttribute('data-testid'),
      ),
    }));
    check(schemeSurfaces.landPanel, 'land economics panel rendered from the certificate');
    check(schemeSurfaces.landChecks > 0, 'land economics lists its certificate checks', `${schemeSurfaces.landChecks} checks`);
    check(schemeSurfaces.landKpis >= 4, 'land economics shows its KPI tiles', `${schemeSurfaces.landKpis} tiles`);
    check(schemeSurfaces.picker, 'scheme picker rendered');
    check(
      schemeSurfaces.options.length === 3,
      'scheme picker offers all three profiles',
      schemeSurfaces.options.join(', ') || 'none',
    );

    if (schemeSurfaces.options.length === 3) {
      const targetProfile = 'max_vastu';
      const pickPromise = page.waitForResponse(
        (res) => res.url().includes('/api/generate-floorplan') && res.request().method() === 'POST',
        { timeout: 60000 },
      );
      await page.click(`[data-testid="scheme-option-${targetProfile}"]`);
      const pickResponse = await pickPromise;
      const pickBody = pickResponse.request().postData() || '';
      let pickReq = {};
      try { pickReq = JSON.parse(pickBody); } catch (e) { /* leave empty */ }
      const pickJson = await pickResponse.json().catch(() => ({}));
      await sleep(2500);

      check(
        pickReq.selected_scheme_id === targetProfile,
        'picking a profile sends it as selected_scheme_id',
        pickReq.selected_scheme_id || 'missing',
      );
      check(
        pickReq.include_scheme_alternatives === true,
        'the re-solve keeps the portfolio attached',
      );
      const status = (pickJson.params_snapshot || {}).scheme_selection_status;
      check(
        status === 'applied',
        'the backend applied the selected profile',
        String(status),
      );
      const badge = await page.evaluate(() => {
        const el = document.querySelector('[data-testid="scheme-selection-status"]');
        return el ? (el.textContent || '').trim() : null;
      });
      check(Boolean(badge), 'picker states what the backend did', badge || 'no badge');
    }

    // 5d. SVG export (audit surface: UNVERIFIED). The viewer's download must be
    // a real file carrying the server generation id, not a silent no-op.
    console.log('- export SVG from the viewer');
    const downloadDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bw-svg-'));
    const cdp = await page.createCDPSession();
    await cdp.send('Browser.setDownloadBehavior', {
      behavior: 'allow',
      downloadPath: downloadDir,
      eventsEnabled: true,
    });
    // The dossier is a drawer and the export toolbar lives in the expanded
    // sheet modal, so both have to be open before the button exists.
    await page.evaluate(() => {
      const toggle = Array.from(document.querySelectorAll('button'))
        .find((b) => /^View (Results|Panel)$/.test((b.textContent || '').trim()));
      if (toggle) toggle.click();
    });
    await sleep(600);
    const modalOpened = await page.evaluate(() => {
      const btn = document.querySelector('button[aria-label="Open Fullscreen Blueprint"]');
      if (!btn) return false;
      btn.click();
      return true;
    });
    check(modalOpened, 'the blueprint modal can be opened from the card');
    await sleep(700);
    let exportState = 'missing';
    for (let i = 0; i < 40; i += 1) {
      exportState = await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll('button'))
          .find((b) => /Export SVG/.test(b.textContent || ''));
        if (!btn) return 'missing';
        if (btn.disabled) return 'disabled';
        btn.click();
        return 'clicked';
      });
      if (exportState !== 'missing') break;
      await sleep(250);
    }
    let svgPath = null;
    for (let i = 0; i < 40 && !svgPath; i += 1) {
      await sleep(250);
      const hit = fs.readdirSync(downloadDir).find((f) => f.toLowerCase().endsWith('.svg'));
      if (hit) svgPath = path.join(downloadDir, hit);
    }
    const svgBody = svgPath ? fs.readFileSync(svgPath, 'utf8') : '';
    check(exportState === 'clicked', 'Export SVG is enabled on a solved plan', exportState);
    check(
      Boolean(svgPath) && /GEN-/.test(path.basename(svgPath)),
      'Export SVG writes an .svg named with the generation id',
      svgPath ? path.basename(svgPath) : 'no file',
    );
    check(
      svgBody.length > 5000 && /<svg[\s>]/.test(svgBody.slice(0, 600)),
      'the exported file is a real drawing',
      `${svgBody.length} bytes`,
    );

    // 5e. Satellite vision (audit surface: UNVERIFIED). Upstream imagery is
    // stubbed (installed before the analysis, above) so what is exercised is the
    // real card, the real POST and the real rendering of the measured response.
    console.log('- satellite vision scan');
    const ecologyClicked = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => (b.textContent || '').trim() === 'Ecology');
      if (!btn) return false;
      btn.click();
      return true;
    });
    // The analysis auto-runs a scan, so the card may still be in its loading
    // skeleton when the tab opens (no button at all). The stubbed scan settles
    // immediately; wait for the skeleton to clear — the click asserts the
    // steady-state affordance, not a race.
    await page.waitForFunction(() => {
      const sec = document.querySelector('[data-report-section="vision"]');
      if (!sec) return false;
      return !sec.querySelector('[aria-label="Analyzing satellite canopy and ecological inference"]');
    }, { timeout: 20000 }).catch(() => { });
    await sleep(900);
    const scanOffered = await page.evaluate(() => {
      const sec = document.querySelector('[data-report-section="vision"]');
      if (!sec) return 'no-section';
      // The analysis auto-runs a scan, so by the time the tab opens the card
      // may be showing its retry affordance rather than the first-run CTA.
      const btn = Array.from(sec.querySelectorAll('button'))
        .find((b) => /Scan satellite canopy|Retry scan|Rescan satellite/.test(b.textContent || ''));
      if (!btn) return 'missing';
      if (btn.disabled) return 'disabled';
      btn.click();
      return 'clicked';
    });
    await page.waitForFunction(
      () => /Tree clusters detected/.test(document.body.innerText || '') && /\bT1\b/.test(document.body.innerText || ''),
      { timeout: 20000 },
    ).catch(() => { });
    const visionUi = await page.evaluate(() => {
      const sec = document.querySelector('[data-report-section="vision"]');
      const text = sec ? (sec.innerText || '') : '';
      return {
        canopy: /37\.5%/.test(text),
        clusters: /Tree clusters detected/.test(text),
        plan: /\bT1\b/.test(text) && /\bT2\b/.test(text),
      };
    });
    check(ecologyClicked, 'Ecology tab opens');
    check(scanOffered === 'clicked', 'the vision card offers a scan for a located site', scanOffered);
    check(
      Boolean(visionRequest) && typeof visionRequest.latitude === 'number' && typeof visionRequest.longitude === 'number',
      'the scan posts the located site coordinates',
      JSON.stringify(visionRequest || {}),
    );
    check(visionUi.canopy && visionUi.clusters, 'the card renders the measured canopy and cluster count', JSON.stringify(visionUi));
    check(visionUi.plan, 'the preservation plan lists the detected clusters', JSON.stringify(visionUi));
    page.off('request', visionHandler);
    await page.setRequestInterception(false);
    // Restore the tab the rest of the run expects.
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => (b.textContent || '').trim() === 'Cost & Plan');
      if (btn) btn.click();
    });
    await sleep(500);

    // 6. Moving the site after generation ASKS FIRST: with a plot captured, the
    // move is not applied until the user chooses, and whichever choice is made
    // must never leave geometry describing two different sites at once.
    const siteMove = await page.evaluate(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const m = window.__maplibreMap;
      const srcLen = (id) => {
        const s = m.getSource(id);
        if (!s) return -1;
        const d = s.serialize().data;
        if (d && d.features) return d.features.length;
        if (d && d.geometry) {
          return d.geometry.type === 'Polygon' ? (d.geometry.coordinates[0] || []).length : (d.geometry.coordinates || []).length;
        }
        return 0;
      };
      const previewAnchor = () => {
        const s = m.getSource('bw-preview-footprint');
        const d = s && s.serialize().data;
        const ring = d && d.geometry && d.geometry.coordinates && d.geometry.coordinates[0];
        return ring && ring.length ? [Number(ring[0][0].toFixed(5)), Number(ring[0][1].toFixed(5))] : null;
      };
      const inputs = () => Array.from(document.querySelectorAll('input[type="text"]'));
      const typeCoords = async (lat, lon) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        const latEl = inputs().find((i) => i.id === 'lat-input') || inputs()[0];
        const lonEl = inputs().find((i) => i.id === 'lon-input') || inputs()[1];
        if (!latEl || !lonEl) return null;
        setter.call(latEl, String(lat));
        latEl.dispatchEvent(new Event('input', { bubbles: true }));
        setter.call(lonEl, String(lon));
        lonEl.dispatchEvent(new Event('input', { bubbles: true }));
        await sleep(300);
        return { latEl, lonEl, previous: null };
      };
      const pressUpdatePin = async () => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').includes('Update Pin'));
        if (!btn) return false;
        btn.click();
        await sleep(600);
        return true;
      };
      const waitForDialog = async (maxMs = 6000) => {
        const t0 = Date.now();
        while (Date.now() - t0 < maxMs) {
          if (document.querySelector('[data-testid="site-move-dialog"]')) return true;
          await sleep(50);
        }
        return false;
      };
      const waitForDialogClosed = async (maxMs = 6000) => {
        const t0 = Date.now();
        while (Date.now() - t0 < maxMs) {
          if (!document.querySelector('[data-testid="site-move-dialog"]')) return true;
          await sleep(50);
        }
        return false;
      };
      const latEl = inputs().find((i) => i.id === 'lat-input') || inputs()[0];
      if (!latEl) return { ok: false, reason: 'coordinate inputs missing' };
      const originLat = latEl.value;
      const nextLat = (Number(originLat) + 0.002).toFixed(5);
      const nextLon = (Number(inputs().find((i) => i.id === 'lon-input').value) + 0.002).toFixed(5);

      const start = { preview: previewAnchor(), chip: /m²/.test(document.body.innerText), latInput: originLat };

      // (a) Asking: the dialog appears and NOTHING has moved yet.
      await typeCoords(nextLat, nextLon);
      await pressUpdatePin();
      await waitForDialog();
      const asked = {
        dialog: Boolean(document.querySelector('[data-testid="site-move-dialog"]')),
        options: Array.from(document.querySelectorAll('[data-testid="site-move-dialog"] button')).map((b) => b.textContent.trim()),
        preview: previewAnchor(),
        chip: /m²/.test(document.body.innerText),
        typedLat: (inputs().find((i) => i.id === 'lat-input') || {}).value,
      };

      // (b) Keep the current plot: nothing changes and the inputs resync.
      const cancelBtn = document.querySelector('[data-testid="site-move-cancel"]');
      if (cancelBtn) cancelBtn.click();
      await waitForDialogClosed();
      await sleep(600);
      const afterCancel = {
        dialog: Boolean(document.querySelector('[data-testid="site-move-dialog"]')),
        preview: previewAnchor(),
        latInput: (inputs().find((i) => i.id === 'lat-input') || {}).value,
      };

      // (c) Take the plot to the new site: the plot (and its preview) move.
      await typeCoords(nextLat, nextLon);
      await pressUpdatePin();
      await waitForDialog();
      const applyBtn = document.querySelector('[data-testid="site-move-apply"]');
      if (applyBtn) applyBtn.click();
      await waitForDialogClosed();
      await sleep(2500);
      const afterApply = {
        preview: previewAnchor(),
        footprint: srcLen('footprint-source'),
        entrance: srcLen('entrance-shaft-source'),
        captureRing: srcLen('bw-capture-boundary'),
        plotStillCaptured: /m²/.test(document.body.innerText),
        notice: Boolean(document.querySelector('[data-testid="site-moved-notice"]')),
      };

      // (d) Drop it and re-capture: the plot clears and the wizard opens.
      await typeCoords((Number(nextLat) + 0.002).toFixed(5), (Number(nextLon) + 0.002).toFixed(5));
      await pressUpdatePin();
      await waitForDialog();
      const recaptureBtn = document.querySelector('[data-testid="site-move-recapture"]');
      if (recaptureBtn) recaptureBtn.click();
      await waitForDialogClosed();
      await sleep(1400);
      const afterRecapture = {
        // "Plot cleared" is read from the wizard's own loaded ring, not from the
        // page text: the parameters card legitimately prints "185.8 m²" for the
        // plinth area, which made the old /m²/ probe report a lingering plot.
        ringVertices: srcLen('bw-capture-boundary'),
        wizardOpen: /Locate the site/.test(document.body.innerText),
        dialog: Boolean(document.querySelector('[data-testid="site-move-dialog"]')),
      };

      return { ok: true, start, asked, afterCancel, afterApply, afterRecapture };
    });

    check(siteMove.ok, 'site move driven through the sidebar', siteMove.reason || '');
    if (siteMove.ok) {
      check(siteMove.asked.dialog, 'moving the site with a captured plot asks first');
      check(
        siteMove.asked.options.length === 3,
        'the dialog offers take / re-capture / keep',
        siteMove.asked.options.join(' | ')
      );
      check(
        JSON.stringify(siteMove.asked.preview) === JSON.stringify(siteMove.start.preview) && siteMove.asked.chip,
        'nothing changes while the question is open',
        `${JSON.stringify(siteMove.start.preview)} -> ${JSON.stringify(siteMove.asked.preview)}`
      );
      check(
        !siteMove.afterCancel.dialog &&
        JSON.stringify(siteMove.afterCancel.preview) === JSON.stringify(siteMove.start.preview) &&
        siteMove.afterCancel.latInput === siteMove.start.latInput,
        'keep: plot, preview and coordinates all stay as they were',
        JSON.stringify(siteMove.afterCancel)
      );
      check(
        JSON.stringify(siteMove.afterApply.preview) !== JSON.stringify(siteMove.start.preview),
        'take: site preview re-rendered for the NEW location',
        `${JSON.stringify(siteMove.start.preview)} -> ${JSON.stringify(siteMove.afterApply.preview)}`
      );
      check(siteMove.afterApply.footprint === 0, 'take: no footprint left stuck to the moved pin', `features ${siteMove.afterApply.footprint}`);
      check(siteMove.afterApply.entrance === 0, 'take: no stale entrance overlay after the move');
      check(siteMove.afterApply.captureRing === 0, 'take: no leftover capture ring on the basemap');
      check(siteMove.afterApply.plotStillCaptured, 'take: the captured plot travelled with the pin');
      check(siteMove.afterApply.notice, 'take: the user is told to re-run the analysis');
      check(
        siteMove.afterRecapture.ringVertices === 0 && siteMove.afterRecapture.wizardOpen && !siteMove.afterRecapture.dialog,
        're-capture: plot cleared and the wizard opens at locate',
        JSON.stringify(siteMove.afterRecapture)
      );
    }

    // 7. Unlocated-trace guard (regression). Clearing the coordinates used to
    //    leave the app holding a committed plot while its own CTA still read
    //    "Select Location on Map to Begin", and pressing that CTA re-opened the
    //    wizard instead of advancing. A plot can no longer be traced without a
    //    pin, and committing one locates the site at the pin it was traced
    //    around (never at the wizard's fallback point).
    console.log('- unlocated-trace guard');
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await sleep(2000);
    const clearedPin = await page.evaluate(() => {
      const b = document.querySelector('button[title="Clear coordinates"]');
      if (!b) return false;
      b.click();
      return true;
    });
    check(clearedPin, 'coordinates cleared from the card');
    await sleep(700);
    const afterClear = await page.evaluate(() => {
      const cta = Array.from(document.querySelectorAll('button'))
        .find((b) => /Select Location on Map to Begin|Run Site Feasibility Analysis/.test(b.textContent || ''));
      return {
        cta: cta ? cta.textContent.trim() : null,
        chip: Boolean(document.querySelector('[data-testid="boundary-chip"]')),
      };
    });
    check(
      afterClear.cta === 'Select Location on Map to Begin' && !afterClear.chip,
      'cleared: no plot captured, CTA asks for a location',
      JSON.stringify(afterClear),
    );
    // A cleared site must leave nothing behind for a later capture to anchor to
    // (the stale coordinates used to be the hidden site the wizard traced at).
    const staleAfterClear = await page.evaluate(() => {
      const field = (id) => (document.getElementById(id) || {}).value || '';
      return { lat: field('lat-input'), lon: field('lon-input') };
    });
    check(
      staleAfterClear.lat === '' && staleAfterClear.lon === '',
      'cleared: no stale coordinates left in the card',
      JSON.stringify(staleAfterClear),
    );

    await clickByLabel(page, 'Select Location on Map to Begin');
    await page.waitForFunction(() => /Locate the site/.test(document.body.innerText || ''), { timeout: 15000 });
    const guard = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find((b) => /Trace boundary/.test(b.textContent || ''));
      return {
        needsPin: Boolean(document.querySelector('[data-testid="capture-needs-pin"]')),
        disabled: btn ? Boolean(btn.disabled) : null,
      };
    });
    check(
      guard.needsPin && guard.disabled === true,
      'no pin: the wizard asks for one and blocks tracing',
      JSON.stringify(guard),
    );

    await page.mouse.click(900, 420);
    await sleep(1000);
    const placed = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="capture-pin-coords"]');
      const btn = Array.from(document.querySelectorAll('button')).find((b) => /Trace boundary/.test(b.textContent || ''));
      return { pin: el ? el.textContent.trim() : null, disabled: btn ? Boolean(btn.disabled) : null };
    });
    check(
      Boolean(placed.pin) && placed.disabled === false,
      'pin placed on the map: tracing is offered again',
      JSON.stringify(placed),
    );

    await clickByLabel(page, 'Trace boundary');
    await sleep(800);
    await traceRectPreset(page);
    await page.waitForFunction(() => /Confirm the frontage/.test(document.body.innerText || ''), { timeout: 40000 });
    await page.waitForFunction(() => Boolean(document.querySelector('[data-testid="edge-row-2"]')), { timeout: 20000 });
    await page.evaluate(() => document.querySelector('[data-testid="edge-row-2"]').click());
    await page.waitForFunction(
      () => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Review');
        return Boolean(btn) && !btn.disabled;
      },
      { timeout: 15000 },
    );
    await clickByLabel(page, 'Review');
    await page.waitForFunction(() => /Review boundary/.test(document.body.innerText || ''), { timeout: 15000 });
    await page.waitForFunction(
      () => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').includes('Use this boundary'));
        return Boolean(btn) && !btn.disabled;
      },
      { timeout: 15000 },
    );
    await clickByLabel(page, 'Use this boundary');
    await sleep(1500);
    const committed = await page.evaluate((pin) => {
      const cta = Array.from(document.querySelectorAll('button'))
        .find((b) => /Select Location on Map to Begin|Run Site Feasibility Analysis/.test(b.textContent || ''));
      const field = (id) => (document.getElementById(id) || {}).value || '';
      const [pinLat, pinLon] = (pin || '').split(',').map((s) => s.trim());
      return {
        cta: cta ? cta.textContent.trim() : null,
        chip: /m²/.test(document.body.innerText),
        lat: field('lat-input'),
        lon: field('lon-input'),
        pinLat,
        pinLon,
      };
    }, placed.pin);
    check(committed.chip, 'the unlocated trace captured a plot', JSON.stringify(committed));
    check(
      committed.cta === 'Run Site Feasibility Analysis',
      'committing the plot advances the CTA to Run',
      committed.cta || 'CTA not found',
    );
    check(
      committed.lat === committed.pinLat && committed.lon === committed.pinLon,
      'the site becomes the pin the plot was traced around',
      `${committed.lat}, ${committed.lon} vs pinned ${committed.pinLat}, ${committed.pinLon}`,
    );

    // 8. zero browser errors
    check(consoleErrors.length === 0, 'zero console errors', consoleErrors.slice(0, 3).join(' | '));
    check(pageErrors.length === 0, 'zero page errors', pageErrors.slice(0, 3).join(' | '));

    // 9. Mobile intent path (mobile intent). On a phone-sized, touch-first viewport the map
    //    ENGINE is not fetched until the reader touches the map region — and the
    //    touch that brings it up is the ordinary pointerdown listener, not a
    //    test flag (there is none). The reserved box must be identical before and
    //    after the engine mounts, because clsTrusted is measured across it.
    console.log('- mobile intent path (412x823, touch)');
    const mobilePage = await browser.newPage();
    const mobileConsole = [];
    const mobilePageErrors = [];
    const mobileEngineRequests = [];
    mobilePage.on('console', (m) => {
      if (m.type() === 'error') mobileConsole.push(m.text().slice(0, 200));
    });
    mobilePage.on('pageerror', (e) => mobilePageErrors.push(String((e && e.message) || e)));
    mobilePage.on('request', (r) => {
      // Built chunk (production) or the dev server's ESM module for the same
      // source — the deferral is about the MODULE, not about its file name.
      if (/MapCanvas-[^/]*\.js$/.test(r.url()) || /\/src\/components\/MapCanvas\.tsx/.test(r.url())) {
        mobileEngineRequests.push(r.url());
      }
    });
    await mobilePage.setViewport({ width: 412, height: 823, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
    await mobilePage.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await mobilePage.waitForSelector('[data-testid="map-placeholder"]', { timeout: 15000 });
    await sleep(1200);
    const mobileBefore = await mobilePage.evaluate(() => {
      const section = document.getElementById('center-map-section');
      const r = section ? section.getBoundingClientRect() : null;
      return {
        placeholder: Boolean(document.querySelector('[data-testid="map-placeholder"]')),
        reserved: (document.querySelector('[data-testid="map-placeholder"]') || {}).dataset?.mapReserved || null,
        map: Boolean(window.__maplibreMap),
        box: r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null,
      };
    });
    check(
      mobileBefore.placeholder && !mobileBefore.map && mobileEngineRequests.length === 0,
      'mobile: first view is the placeholder, engine not requested',
      `map=${mobileBefore.map} engineRequests=${mobileEngineRequests.length} reserved=${mobileBefore.reserved}`,
    );

    // The REAL intent path: a trusted touch inside the map region. Nothing else.
    await mobilePage.touchscreen.tap(206, 430);
    await mobilePage.waitForFunction(() => Boolean(window.__maplibreMap), { timeout: 30000 });
    // The style and its sources arrive after the engine module mounts; a fixed
    // sleep here was a known race (a slow style made styleLoaded read
    // false). Wait on the map's own 'load' event — fired once the style and the
    // resources it needs are ready — with a hard bound, then assert it.
    const styleReady = await mobilePage.evaluate(
      () =>
        new Promise((resolve) => {
          const m = window.__maplibreMap;
          if (!m) return resolve(false);
          const done = (ok) => {
            clearTimeout(timer);
            resolve(ok);
          };
          if (m.loaded() && m.isStyleLoaded() && (m.getStyle().layers || []).length > 0) return done(true);
          const timer = setTimeout(() => done(false), 20000);
          m.once('load', () => done(true));
        }),
      { timeout: 25000 },
    );
    // `load` can fire just before a style re-settle (a resize or a source
    // reconciliation flips isStyleLoaded() false for a frame). Poll the map's
    // own settled predicate before reading the final state; the assertion below
    // is unchanged and still fails if the style never becomes ready.
    const styleSettled = await mobilePage
      .waitForFunction(
        () => {
          const m = window.__maplibreMap;
          return Boolean(m && m.isStyleLoaded() && (m.getStyle().layers || []).length > 0);
        },
        { timeout: 10000 }
      )
      .then(() => true)
      .catch(() => false);
    const mobileAfter = await mobilePage.evaluate(() => {
      const m = window.__maplibreMap;
      const section = document.getElementById('center-map-section');
      const r = section ? section.getBoundingClientRect() : null;
      return {
        canvas: Boolean(document.querySelector('.maplibregl-canvas')),
        styleLoaded: m.isStyleLoaded(),
        layers: (m.getStyle().layers || []).length,
        placeholder: Boolean(document.querySelector('[data-testid="map-placeholder"]')),
        box: r ? [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] : null,
      };
    });
    check(
      mobileEngineRequests.length > 0 && mobileAfter.canvas && !mobileAfter.placeholder,
      'mobile: a trusted tap loads the engine and swaps the placeholder out',
      `engineRequests=${mobileEngineRequests.length} canvas=${mobileAfter.canvas} placeholder=${mobileAfter.placeholder}`,
    );
    check(
      styleReady === true && styleSettled && mobileAfter.styleLoaded === true && mobileAfter.layers > 0,
      'mobile: the map that came up is a real style',
      `styleEvent=${styleReady} styleSettled=${styleSettled} styleLoaded=${mobileAfter.styleLoaded} layers=${mobileAfter.layers}`,
    );
    check(
      JSON.stringify(mobileBefore.box) === JSON.stringify(mobileAfter.box),
      'mobile: the reserved map box does not move through the mount',
      `${JSON.stringify(mobileBefore.box)} -> ${JSON.stringify(mobileAfter.box)}`,
    );
    check(
      mobileConsole.length === 0 && mobilePageErrors.length === 0,
      'mobile: zero console and page errors on the intent path',
      mobileConsole.concat(mobilePageErrors).slice(0, 3).join(' | '),
    );
    await mobilePage.close();

    // 10. Capture-side surfaces the audit listed as UNVERIFIED: address search,
    //     presets, undo/redo and KML import. A second tab keeps them isolated
    //     from the funnel state asserted above; the providers are stubbed, the
    //     app is not.
    console.log('- capture surfaces: search, presets, undo/redo, KML import');
    const aux = await browser.newPage();
    const auxConsole = [];
    const auxErrors = [];
    aux.on('console', (m) => {
      if (m.type() === 'error') auxConsole.push(m.text().slice(0, 200));
    });
    aux.on('pageerror', (e) => auxErrors.push(String((e && e.message) || e)));
    await aux.setViewport({ width: 1600, height: 1000 });
    await aux.setRequestInterception(true);
    aux.on('request', (req) => {
      if (req.url().includes('/api/geocode')) {
        req.respond({
          status: 200,
          contentType: 'application/json',
          headers: { 'access-control-allow-origin': '*' },
          body: JSON.stringify(GEOCODE_FIXTURE),
        });
        return;
      }
      req.continue();
    });
    await aux.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await sleep(2000);

    // Address search -> pin.
    const searchInput = 'input[aria-label="Search for a location"]';
    await aux.waitForSelector(searchInput, { timeout: 15000 });
    await aux.click(searchInput);
    await aux.type(searchInput, 'E2E Locality 4471', { delay: 25 });
    await aux.waitForSelector('#geocode-suggestion-0', { timeout: 15000 });
    await aux.click('#geocode-suggestion-0');
    await sleep(1500);
    const located = await aux.evaluate(() => ({
      lat: (document.getElementById('lat-input') || {}).value,
      lon: (document.getElementById('lon-input') || {}).value,
    }));
    check(
      Math.abs(Number(located.lat) - 12.9716) < 0.0002 && Math.abs(Number(located.lon) - 77.5946) < 0.0002,
      'address search fills the pin from the geocode result',
      JSON.stringify(located),
    );

    // Presets -> 4 vertices; undo -> 0; redo -> 4.
    await clickByLabel(aux, 'Select Location on Map to Begin');
    await aux.waitForFunction(() => /Locate the site/.test(document.body.innerText || ''), { timeout: 15000 });
    await clickByLabel(aux, 'Trace boundary');
    await sleep(700);
    const vertexCount = () => aux.evaluate(() => {
      const m = window.__maplibreMap;
      const s = m && m.getSource('bw-capture-vertices');
      const d = s && s.serialize().data;
      return d && d.features ? d.features.length : -1;
    });
    await aux.click('[data-testid="trace-toolbar-presets"]');
    await aux.waitForSelector('[data-testid="preset-menu"]', { timeout: 10000 });
    await aux.click('[data-testid="preset-item-rect"]');
    await sleep(500);
    const presetCount = await vertexCount();
    await aux.click('[data-testid="trace-toolbar-undo"]');
    await sleep(400);
    const undoCount = await vertexCount();
    await aux.click('[data-testid="trace-toolbar-redo"]');
    await sleep(400);
    const redoCount = await vertexCount();
    check(presetCount === 4, 'a preset applies a closed rectangle to the trace', `vertices=${presetCount}`);
    check(
      undoCount === 0 && redoCount === 4,
      'undo and redo walk the vertex history',
      `${presetCount} -> ${undoCount} -> ${redoCount}`,
    );

    // KML import -> frontage with 4 edges.
    await aux.evaluate(() => {
      const d = document.querySelector('[data-testid="import-disclosure"]');
      if (d) d.open = true;
    });
    await aux.waitForSelector('[data-testid="import-disclosure"] textarea', { timeout: 10000 });
    await aux.evaluate((kml) => {
      const ta = document.querySelector('[data-testid="import-disclosure"] textarea');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, kml);
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    }, KML_FIXTURE);
    await sleep(200);
    const importClicked = await aux.evaluate(() => {
      const d = document.querySelector('[data-testid="import-disclosure"]');
      const btn = d ? Array.from(d.querySelectorAll('button')).find((b) => /Import/.test(b.textContent || '')) : null;
      if (!btn) return false;
      btn.click();
      return true;
    });
    await aux
      .waitForFunction(() => /Confirm the frontage/.test(document.body.innerText || ''), { timeout: 20000 })
      .catch(() => { });
    const kml = await aux.evaluate(() => ({
      onFrontage: /Confirm the frontage/.test(document.body.innerText || ''),
      rows: document.querySelectorAll('[data-testid^="edge-row-"]').length,
      error: (document.querySelector('[data-testid="import-disclosure"]') || {}).innerText || '',
    }));
    check(importClicked, 'KML import control is present and enabled');
    check(kml.onFrontage && kml.rows === 4, 'KML import lands on the frontage step with 4 edges', `rows=${kml.rows}`);
    check(
      !/Unsupported boundary|No polygon geometry|Import failed/i.test(kml.error),
      'KML import reports no parse error',
      kml.error.slice(0, 120),
    );
    check(
      auxConsole.length === 0 && auxErrors.length === 0,
      'capture surfaces: zero console and page errors',
      auxConsole.concat(auxErrors).slice(0, 3).join(' | '),
    );
    await aux.close();

  } catch (err) {
    check(false, 'E2E aborted', String(err && err.message || err));
    try {
      const state = await page.evaluate(() => ({
        buttons: Array.from(document.querySelectorAll('button')).map((b) => (b.textContent || '').trim()).filter(Boolean).slice(0, 40),
        bodySnippet: (document.body.innerText || '').slice(0, 600),
      }));
      console.log('--- UI state at abort ---');
      console.log('buttons:', JSON.stringify(state.buttons));
      console.log('text:', state.bodySnippet.replace(/\n+/g, ' / '));
    } catch (e) { /* page may be gone */ }
    console.log('--- API failures so far:', JSON.stringify(apiFailures));
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n=== e2e full funnel: ${results.length - failed.length} passed, ${failed.length} failed ===`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error('fatal:', err);
  process.exit(2);
});
