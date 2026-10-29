#!/usr/bin/env node
/**
 * test_reset_reducer.cjs — THE reset contract, pinned without a browser.
 * ======================================================================
 * Reset used to be a hand-written list of set*() calls that drifted from the
 * first-run initialisers: the boundary survived, the parameters differed from
 * first run and the deep-link URL restored the old site on reload. Reset now
 * goes through one pure reducer seeded by the same object as first render.
 *
 * This test pins that contract:
 *   [1] pristine state == first-run state (same request, default site, no data)
 *   [2] reset from a dirty session drops every datum, including ones added
 *       after the reset list was written (client brief / extracted constraints)
 *   [3] reset is a rebuild, not a patch: no stale key survives
 *   [4] purity: the input state is never mutated; unknown actions are no-ops
 *   [5] storage scrubber drops report data and keeps preferences
 *   [6] URL scrubber removes lat/lon/start/#report and keeps unrelated params
 *
 * Repo dialect: plain-node assertions (no test framework). Run with
 *   node --experimental-strip-types scripts/test_reset_reducer.cjs
 */
const path = require('path');
const { pathToFileURL } = require('url');

const ROOT = path.resolve(__dirname, '..');

function makeStorage() {
  const map = new Map();
  return {
    map,
    get length() {
      return map.size;
    },
    key(i) {
      return Array.from(map.keys())[i] ?? null;
    },
    getItem(k) {
      return map.has(k) ? map.get(k) : null;
    },
    setItem(k, v) {
      map.set(k, String(v));
    },
    removeItem(k) {
      map.delete(k);
    },
  };
}

function makeWindow() {
  const state = {
    pathname: '/app',
    search: '?lat=12.9&lon=77.6&start=capture&utm=keep',
    hash: '#report',
    href: '',
  };
  state.href = `http://localhost:5173${state.pathname}${state.search}${state.hash}`;
  const sync = () => {
    state.href = `http://localhost:5173${state.pathname}${state.search}${state.hash}`;
  };
  return {
    state,
    localStorage: makeStorage(),
    sessionStorage: makeStorage(),
    location: state,
    history: {
      replaceState(_data, _title, url) {
        const parsed = new URL(url, 'http://localhost:5173');
        state.pathname = parsed.pathname;
        state.search = parsed.search;
        state.hash = parsed.hash;
        sync();
      },
    },
  };
}

(async () => {
  let failures = 0;
  const check = (cond, label, detail) => {
    console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
    if (!cond) failures++;
  };

  const mod = await import(
    pathToFileURL(path.join(ROOT, 'src', 'services', 'sessionReset.ts')).href
  );
  const {
    DEFAULT_SITE,
    PRISTINE_REQUEST,
    REPORT_SECTIONS_KEY,
    REPORT_SCROLL_PREFIX,
    createInitialSessionData,
    pristineSessionData,
    sessionDataReducer,
    clearSessionDataStorage,
    stripTransientUrl,
  } = mod;

  console.log('\n[1] Pristine state IS first-run state');
  const firstRun = createInitialSessionData();
  const pristine = pristineSessionData();
  check(
    JSON.stringify(firstRun) === JSON.stringify(pristine),
    'createInitialSessionData() and pristineSessionData() are the same state',
  );
  check(
    JSON.stringify(firstRun.request) === JSON.stringify(PRISTINE_REQUEST),
    'first-run request is PRISTINE_REQUEST (single source)',
    JSON.stringify(firstRun.request),
  );
  check(
    firstRun.request.ground_coverage_ratio === 0.6 &&
      firstRun.request.floors === 1 &&
      firstRun.request.built_up_area_sqft === 2000,
    'first-run parameters are coverage 0.6 / G / 2,000 sq ft',
  );
  check(
    firstRun.request.client_requirements === undefined &&
      firstRun.request.extracted_constraints === undefined,
    'first run carries no client brief or extracted constraints',
  );
  check(
    firstRun.site.latitude === DEFAULT_SITE.latitude &&
      firstRun.site.longitude === DEFAULT_SITE.longitude,
    'first run sits on the default site',
  );
  check(
    firstRun.boundary === null &&
      firstRun.analysisData === null &&
      firstRun.siteVisionData === null &&
      firstRun.floorPlanData === null &&
      firstRun.overrideLandRate === null &&
      firstRun.overridePlotArea === null &&
      firstRun.testWarnings === null &&
      firstRun.pendingSiteMove === null,
    'first run has no plot, analysis, vision, plan, overrides or test warnings',
  );

  console.log('\n[2] Reset drops every datum (a dirty session)');
  const boundary = {
    vertices: [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 12 },
      { x: 0, y: 12 },
    ],
    origin: { lat: 19.076, lon: 72.8777 },
    frontageEdgeIndex: 1,
    source: 'trace',
  };
  const dirty = {
    ...firstRun,
    site: { latitude: 19.076, longitude: 72.8777 },
    boundary,
    request: {
      ...firstRun.request,
      built_up_area_sqft: 8000,
      floors: 3,
      building_typology: 'commercial_mixed',
      client_requirements: 'three bedrooms, a pooja room and a shop',
      extracted_constraints: { rooms: ['bed_1', 'bed_2', 'bed_3'] },
      ground_coverage_ratio: 0.75,
    },
    analysisData: { request_id: 'abc', warnings: ['PROP-HARD x'], overall_suitability_score: 7.1 },
    siteVisionData: { mode: 'segformer', green_cover_pct: 12 },
    floorPlanData: { generation_id: 'GEN-1', warnings: ['ROOM-MIN bed_2'] },
    overrideLandRate: 9000,
    overridePlotArea: 2400,
    testWarnings: ['GATE-FAIL L7'],
    pendingSiteMove: { lat: 20.0, lon: 78.0 },
    sessionEpoch: 4,
  };
  const frozen = JSON.stringify(dirty);
  const reset = sessionDataReducer(dirty, { type: 'reset', provider: 'groq' });

  check(JSON.stringify(dirty) === frozen, 'the input state is not mutated (purity)');
  check(
    JSON.stringify(reset) ===
      JSON.stringify({ ...pristine, sessionEpoch: dirty.sessionEpoch + 1 }),
    'reset output is exactly the pristine state + an incremented epoch',
  );
  check(reset.boundary === null, 'boundary is cleared');
  check(
    reset.site.latitude === DEFAULT_SITE.latitude && reset.site.longitude === DEFAULT_SITE.longitude,
    'site pin returns to the default view',
  );
  check(
    reset.request.floors === 1 &&
      reset.request.ground_coverage_ratio === 0.6 &&
      reset.request.built_up_area_sqft === 2000,
    'parameters return to generator defaults',
  );
  check(
    reset.request.client_requirements === undefined &&
      reset.request.extracted_constraints === undefined,
    'client brief and extracted constraints are dropped (never patch-listed)',
  );
  check(
    reset.analysisData === null &&
      reset.siteVisionData === null &&
      reset.floorPlanData === null,
    'analysis, vision and generated plan are dropped',
  );
  check(
    reset.overrideLandRate === null &&
      reset.overridePlotArea === null &&
      reset.testWarnings === null &&
      reset.pendingSiteMove === null,
    'overrides, test-warning seam and a held pin move are dropped',
  );
  check(
    reset.sessionEpoch === dirty.sessionEpoch + 1,
    'session epoch advances (data surfaces remount, not prop-update)',
  );

  console.log('\n[3] Reset is a rebuild (no stale keys), idempotent modulo epoch');
  const keySet = (s) => Object.keys(s).sort().join(',');
  check(keySet(reset) === keySet(firstRun), 'reset has exactly the first-run key set');
  const twice = sessionDataReducer(reset, { type: 'reset', provider: 'groq' });
  check(
    JSON.stringify({ ...twice, sessionEpoch: 0 }) ===
      JSON.stringify({ ...reset, sessionEpoch: 0 }),
    'a second reset changes nothing but the epoch',
  );

  console.log('\n[4] Reducer edges');
  check(
    sessionDataReducer(reset, { type: 'not-an-action' }) === reset,
    'unknown actions are no-ops (same object)',
  );
  const deepLinked = createInitialSessionData({ latitude: 1.25, longitude: 103.8 });
  check(
    deepLinked.site.latitude === 1.25 && deepLinked.boundary === null,
    'a shared-site link seeds only the pin, never a plot',
  );
  check(
    sessionDataReducer(firstRun, { type: 'reset', provider: 'gemini' }).request.ai_provider ===
      'gemini',
    'reset respects the provider the engine advertises',
  );
  const cleared = sessionDataReducer(dirty, { type: 'clearSite' });
  check(
    cleared.site === null && cleared.boundary === null && cleared.floorPlanData === null,
    'clearSite removes the site and every site result',
  );

  console.log('\n[5] Storage scrubber: data out, preferences kept');
  const win = makeWindow();
  globalThis.window = win;
  win.localStorage.setItem(REPORT_SECTIONS_KEY, '{"overview":false}');
  win.localStorage.setItem('buildwise.units', 'imperial');
  win.localStorage.setItem('bw.coach.capture', 'dismissed');
  win.sessionStorage.setItem(`${REPORT_SCROLL_PREFIX}overview`, '640');
  win.sessionStorage.setItem(`${REPORT_SCROLL_PREFIX}cost_plan`, '1200');
  win.sessionStorage.setItem('bw.played.report.stagger.overview', '1');
  win.sessionStorage.setItem('bw.assisted.continue', '1');
  clearSessionDataStorage();
  check(win.localStorage.getItem(REPORT_SECTIONS_KEY) === null, 'report section map is dropped');
  check(
    win.sessionStorage.getItem(`${REPORT_SCROLL_PREFIX}overview`) === null &&
      win.sessionStorage.getItem(`${REPORT_SCROLL_PREFIX}cost_plan`) === null,
    'remembered report scroll offsets are dropped',
  );
  check(win.localStorage.getItem('buildwise.units') === 'imperial', 'units preference survives');
  check(win.localStorage.getItem('bw.coach.capture') === 'dismissed', 'coach marks survive');
  check(
    win.sessionStorage.getItem('bw.assisted.continue') === '1',
    'ASSISTED notice preference survives',
  );
  check(
    win.sessionStorage.getItem('bw.played.report.stagger.overview') === '1',
    'animation bookkeeping survives (not site/plan data)',
  );

  console.log('\n[6] URL scrubber: reload cannot restore the reset session');
  stripTransientUrl();
  const url = win.state;
  check(
    !/[?&]lat=/.test(url.search) && !/[?&]lon=/.test(url.search),
    'lat/lon deep link is removed',
  );
  check(!/[?&]start=/.test(url.search), 'start=capture is removed');
  check(url.hash === '', '#report is removed');
  check(url.search === '?utm=keep', 'unrelated query parameters are preserved');
  check(
    url.pathname + url.search + url.hash === '/app?utm=keep',
    'replaceState (not push) leaves the address bar pristine',
    url.pathname + url.search + url.hash,
  );

  console.log(`\n${failures === 0 ? 'PASS' : `FAIL (${failures})`} — reset reducer contract`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
