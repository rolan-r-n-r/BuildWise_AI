#!/usr/bin/env node
/**
 * test_plot_camera.cjs — the selected-plot camera contract, without a browser.
 * ===========================================================================
 * Pins the parts of the map-selection move that are easy to regress and hard to
 * see in a review:
 *   [1] a boundary's lon/lat envelope is derived from its local origin,
 *   [2] panel-aware padding never lets the fit centre the plot under a panel,
 *   [3] the fit preserves bearing/pitch and sets a bounded zoom,
 *   [4] reduced motion collapses both the fit and the restore to duration 0,
 *   [5] the restore is a true inverse of the camera snapshot.
 *
 * Run with:
 *   node --experimental-strip-types scripts/test_plot_camera.cjs
 */
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

function check(results, ok, label, detail) {
  results.push({ ok, label, detail });
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
}

function squareBoundary(origin = { lat: 12.9716, lon: 77.5946 }, half = 20) {
  return {
    origin,
    source: 'preset',
    frontageEdgeIndex: 0,
    vertices: [
      { x: -half, y: -half },
      { x: half, y: -half },
      { x: half, y: half },
      { x: -half, y: half },
    ],
  };
}

function fakeMap() {
  const calls = {};
  return {
    calls,
    getCenter: () => ({ lng: 77.5946, lat: 12.9716 }),
    getZoom: () => 15.25,
    getBearing: () => -22.5,
    getPitch: () => 31,
    fitBounds(bounds, options) {
      calls.fitBounds = { bounds, options };
    },
    easeTo(options) {
      calls.easeTo = options;
    },
  };
}

(async () => {
  const results = [];
  // Vite's SSR loader resolves the app's extensionless TypeScript imports; Node's
  // strip-types runner does not, and adding a test-only import suffix to app
  // source would leak the test harness into production code.
  const { createServer } = await import('vite');
  const vite = await createServer({
    configFile: false,
    root: ROOT,
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true },
  });
  const mod = await vite.ssrLoadModule('/src/services/plotCamera.ts');
  const {
    boundaryLngLatBox,
    boxToBounds,
    plotFocusPadding,
    focusCameraOnPlot,
    readCamera,
    restoreCamera,
  } = mod;

  console.log('\n[1] Boundary envelope');
  const box = boundaryLngLatBox(squareBoundary());
  check(results, Boolean(box), 'a valid square produces a box');
  check(
    results,
    box.west < 77.5946 && box.east > 77.5946 && box.south < 12.9716 && box.north > 12.9716,
    'the box contains the boundary origin',
    JSON.stringify(box),
  );
  check(
    results,
    Math.abs(box.north - box.south) > 0.0002 && Math.abs(box.east - box.west) > 0.0002,
    'the box has real extent (a 40 m square is not degenerate)',
  );
  check(results, boundaryLngLatBox(null) === null, 'no boundary produces no box');
  check(
    results,
    boundaryLngLatBox({ ...squareBoundary(), vertices: [{ x: 0, y: 0 }, { x: 1, y: 1 }] }) === null,
    'a ring with fewer than 3 vertices is refused',
  );
  const bounds = boxToBounds(box);
  check(
    results,
    bounds[0][0] === box.west && bounds[0][1] === box.south && bounds[1][0] === box.east && bounds[1][1] === box.north,
    'bounds are [[west, south], [east, north]]',
  );

  console.log('\n[2] Panel-aware padding');
  const phone = plotFocusPadding(390, 844);
  check(results, phone.left === 20 && phone.right === 20, 'phone uses symmetric 20 px insets', JSON.stringify(phone));
  check(results, phone.top > 0 && phone.bottom > phone.top, 'phone reserves more bottom room for the chip/HUD band');
  const desktop = plotFocusPadding(1440, 900, { leftPanel: true, rightPanel: true });
  check(
    results,
    desktop.left === 364 && desktop.right === 384,
    '1440 with both panels open reserves their real widths',
    JSON.stringify(desktop),
  );
  const laptop = plotFocusPadding(1024, 800, { leftPanel: true, rightPanel: true });
  check(
    results,
    laptop.left <= 1024 * 0.28 + 0.01 && laptop.right <= 1024 * 0.29 + 0.01,
    '1024 caps panel padding at 28–29% so a usable map remains',
    JSON.stringify(laptop),
  );
  check(
    results,
    1024 - laptop.left - laptop.right >= 420,
    'at 1024 the usable map width stays at least 420 px',
    `${Math.round(1024 - laptop.left - laptop.right)} px`,
  );
  const closed = plotFocusPadding(1440, 900, { leftPanel: false, rightPanel: false });
  check(results, closed.left === 24 && closed.right === 24, 'closed panels collapse to 24 px insets');

  console.log('\n[3] Fit keeps orientation and bounds zoom');
  const map = fakeMap();
  const fit = focusCameraOnPlot(map, squareBoundary(), {
    width: 1440,
    height: 900,
    leftPanel: true,
    rightPanel: true,
  });
  check(results, fit === true && Boolean(map.calls.fitBounds), 'a valid plot issues fitBounds');
  const opts = map.calls.fitBounds && map.calls.fitBounds.options;
  check(results, opts.maxZoom === 18.4, 'fit is capped at 18.4 (a small plot cannot fill the screen)');
  check(
    results,
    !('bearing' in opts) && !('pitch' in opts),
    'fit does not spin or pitch the reader’s map',
  );
  check(results, opts.duration === 720, 'default fit duration is the spatial token (720 ms)', String(opts.duration));
  check(results, map.calls.fitBounds.bounds[0][0] < map.calls.fitBounds.bounds[1][0], 'fit bounds are ordered west→east');

  console.log('\n[4] Reduced motion');
  const originalWindow = global.window;
  global.window = {
    matchMedia: () => ({ matches: true }),
  };
  const reducedMap = fakeMap();
  focusCameraOnPlot(reducedMap, squareBoundary(), { width: 390, height: 844 });
  check(
    results,
    reducedMap.calls.fitBounds.options.duration === 0,
    'fit duration collapses to 0 under prefers-reduced-motion',
  );
  const snapshot = readCamera(fakeMap());
  restoreCamera(reducedMap, snapshot);
  check(results, reducedMap.calls.easeTo.duration === 0, 'restore duration collapses to 0 too');
  global.window = originalWindow;

  console.log('\n[5] Snapshot / restore');
  const source = fakeMap();
  const snap = readCamera(source);
  check(
    results,
    snap.zoom === 15.25 && snap.bearing === -22.5 && snap.pitch === 31 && snap.center.lng === 77.5946,
    'snapshot reads centre, zoom, bearing and pitch',
    JSON.stringify(snap),
  );
  const target = fakeMap();
  restoreCamera(target, snap);
  check(
    results,
    target.calls.easeTo.center[0] === snap.center.lng &&
      target.calls.easeTo.center[1] === snap.center.lat &&
      target.calls.easeTo.zoom === snap.zoom &&
      target.calls.easeTo.bearing === snap.bearing &&
      target.calls.easeTo.pitch === snap.pitch,
    'restore is the inverse of the snapshot',
  );
  check(results, target.calls.easeTo.duration === 520, 'restore uses its own spatial duration (520 ms)');

  await vite.close();
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n=== plot camera tests: ${results.length - failed} passed, ${failed} failed ===`);
  process.exit(failed ? 1 : 0);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
