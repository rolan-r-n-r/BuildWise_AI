#!/usr/bin/env node
/**
 * test_boundary_pipeline.cjs — boundary pipeline tests.
 * ============================================================
 * 1. Projection round-trip < 0.05 m over 2 km (client == backend parity).
 * 2. Rectangle quick path + presets -> valid, CCW, correctly typed rings.
 * 3. GeoJSON import via the shared boundaryIO util (KML path is DOMParser-based
 *    and runs in the browser E2E; guarded here when DOMParser exists).
 * 4. Single-source payload funnel: golden payload, CW->CCW canonicalization,
 *    invalid boundaries rejected with statutory reasons, frontage index flows.
 * 5. Snap math: ORTHO / PARALLEL / FREE.
 * 6. Single-source parity: same geometry from any capture path -> same payload.
 *
 * Strategy: transpiles the four service modules with the project's own tsc
 * (explicit flags, no tsconfig) into a temp dir, then requires them.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let pass = 0;
let fail = 0;
function check(cond, label) {
  if (cond) { pass++; console.log('  ok   ' + label); }
  else { fail++; console.log('  FAIL ' + label); }
}

/* ---------- transpile services to CJS ---------- */
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bw-boundary-'));
execFileSync(
  process.execPath,
  [path.join(ROOT, 'node_modules', 'typescript', 'lib', 'tsc.js'),
    path.join(ROOT, 'src', 'services', 'projection.ts'),
    path.join(ROOT, 'src', 'services', 'boundaryIO.ts'),
    path.join(ROOT, 'src', 'services', 'siteBoundary.ts'),
    path.join(ROOT, 'src', 'services', 'captureGeometry.ts'),
    path.join(ROOT, 'src', 'services', 'siteIntelligence.ts'),
    path.join(ROOT, 'src', 'services', 'validationGateUI.ts'),
    path.join(ROOT, 'src', 'services', 'sheetTruth.ts'),
    '--outDir', outDir,
    '--module', 'commonjs',
    '--target', 'es2020',
    '--esModuleInterop',
    '--skipLibCheck',
  ],
  { stdio: 'pipe', cwd: outDir } // neutral cwd prevents tsconfig auto-discovery (TS5112)
);

const projection = require(path.join(outDir, 'projection.js'));
const boundaryIO = require(path.join(outDir, 'boundaryIO.js'));
const siteBoundary = require(path.join(outDir, 'siteBoundary.js'));
const captureGeometry = require(path.join(outDir, 'captureGeometry.js'));
const siteIntelligence = require(path.join(outDir, 'siteIntelligence.js'));

/* ---------- 1. Projection round-trip ---------- */
console.log('\n[1] Projection round-trip (backend parity)');
{
  const origin = { lat: 12.9716, lon: 77.5946 };
  const metersPerDegLat = (6378137.0 * Math.PI) / 180; // exact sphere constant the projection uses
  const metersPerDegLon = 111139.0 * Math.cos((origin.lat * Math.PI) / 180);

  for (const [label, dxE, dyN] of [['2 km East', 2000, 0], ['2 km North', 0, 2000], ['2 km NE', 1414, 1414]]) {
    const lat = origin.lat + dyN / metersPerDegLat;
    const lon = origin.lon + dxE / metersPerDegLon;
    const local = projection.projectToLocal(lat, lon, origin);
    const back = projection.unprojectToLngLat(local, origin);
    const errM = Math.hypot(
      (back.lat - lat) * metersPerDegLat,
      (back.lon - lon) * metersPerDegLon
    );
    check(errM < 0.05, `${label}: round-trip ${errM.toFixed(6)} m < 0.05 m`);
  }
  const north = projection.projectToLocal(origin.lat + 2000 / metersPerDegLat, origin.lon, origin);
  check(Math.abs(north.y - 2000) < 0.05, '2 km North -> y = 2000 m');
}

/* ---------- 2. Rectangle quick path + presets ---------- */
console.log('\n[2] Quick paths (rectangle + presets)');
{
  const vs = siteBoundary.rectangleVertices({ widthM: 12, depthM: 18, rotationDeg: 0 }, { x: 0, y: 0 });
  const m = siteBoundary.metricsFor(vs);
  check(vs.length === 4, 'rectangle quick path yields 4 vertices');
  check(m.valid, 'rectangle quick path valid');
  check(m.shapeType === 'rectangle', 'classified as rectangle');
  check(Math.abs(m.areaSqm - 216) < 0.02, `area 216 m2 (got ${m.areaSqm})`);

  const mr = siteBoundary.metricsFor(siteBoundary.rectangleVertices({ widthM: 12, depthM: 18, rotationDeg: 30 }, { x: 0, y: 0 }));
  check(mr.valid && mr.shapeType === 'rectangle' && Math.abs(mr.areaSqm - 216) < 0.02, 'rotation preserves shape + area');

  for (const id of ['rect', 'l_shape', 'trapezoid', 'pentagon']) {
    const pm = siteBoundary.metricsFor(siteBoundary.presetVertices(id, 20, { x: 0, y: 0 }));
    check(pm.valid, `preset ${id} valid (${pm.vertexCount}V, ${pm.areaSqm.toFixed(1)} m2)`);
  }
  const l = siteBoundary.metricsFor(siteBoundary.presetVertices('l_shape', 20, { x: 0, y: 0 }));
  check(l.shapeType === 'l_shape', 'L preset classified l_shape');
}

/* ---------- 3. GeoJSON import (KML guarded for browser APIs) ---------- */
console.log('\n[3] Boundary import (shared util)');
{
  const origin = { lat: 12.9716, lon: 77.5946 };
  const corners = [
    { x: -20, y: -15 }, { x: 20, y: -15 }, { x: 20, y: 15 }, { x: -20, y: 15 },
  ].map((v) => projection.unprojectToLngLat(v, origin));
  const ring = [...corners, corners[0]].map((c) => [c.lon, c.lat]);
  const parsed = boundaryIO.parseBoundaryText(JSON.stringify({ type: 'Polygon', coordinates: [ring] }), origin);
  const pm = siteBoundary.metricsFor(parsed.vertices);
  check(parsed.vertices.length === 4, 'GeoJSON polygon -> 4 vertices');
  check(pm.valid && Math.abs(pm.areaSqm - 1200) < 1.0, `imported area ~1200 m2 (got ${pm.areaSqm.toFixed(1)})`);

  if (typeof DOMParser === 'undefined') {
    console.log('  skip KML import (DOMParser is browser-only; covered by the browser E2E)');
  } else {
    const kml =
      '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>Survey Plot</name>' +
      '<Polygon><outerBoundaryIs><LinearRing><coordinates>' +
      ring.map((c) => `${c[0]},${c[1]},0`).join(' ') +
      '</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>';
    const pk = boundaryIO.parseBoundaryText(kml, origin);
    const km = siteBoundary.metricsFor(pk.vertices);
    check(pk.vertices.length === 4 && pk.name === 'Survey Plot', 'KML polygon parses with placemark name');
    check(km.valid && Math.abs(km.areaSqm - 1200) < 1.0, `KML area ~1200 m2 (got ${km.areaSqm.toFixed(1)})`);
  }
}

/* ---------- 4. Payload funnel ---------- */
console.log('\n[4] Single-source payload funnel');
{
  const vs = siteBoundary.rectangleVertices({ widthM: 12, depthM: 18, rotationDeg: 0 }, { x: 0, y: 0 });
  const origin = { lat: 12.9716, lon: 77.5946 };
  const payload = siteBoundary.buildPlotPolygonPayload({ vertices: vs, origin, source: 'rectangle' });
  check(payload.shape_type === 'rectangle' && payload.is_regular_rectangle === true, 'payload rectangle flags');
  check(payload.vertices.length === 4 && Math.abs(payload.area_sqm - 216) < 0.02, 'payload vertices + area');
  check(payload.origin_lat === origin.lat && payload.origin_lon === origin.lon, 'payload origin');
  check(Array.isArray(payload.bounding_box) && payload.bounding_box.length === 4, 'payload bounding box');

  const cw = siteBoundary.buildPlotPolygonPayload({ vertices: [...vs].reverse(), origin, source: 'rectangle' });
  check(JSON.stringify(cw.vertices) === JSON.stringify(payload.vertices), 'CW input canonicalizes to identical CCW payload');

  let rejected = '';
  try {
    siteBoundary.buildPlotPolygonPayload({
      vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 0, y: 3 }], // 6 m2 < 36
      origin,
      source: 'trace',
    });
  } catch (e) {
    rejected = String(e.message);
  }
  check(rejected.toLowerCase().includes('36') || rejected.toLowerCase().includes('minimum'), `tiny boundary rejected: ${rejected}`);

  const withFrontage = siteBoundary.buildPlotPolygonPayload({ vertices: vs, origin, source: 'trace', frontageEdgeIndex: 2 });
  check(withFrontage.frontage_edge_index === 2, 'frontage index carried through payload');
}

/* ---------- 5. Snap math ---------- */
console.log('\n[5] Snap modes');
{
  const anchor = { x: 0, y: 0 };
  const east = captureGeometry.snapPoint({ x: 10, y: 1.2 }, anchor, null, 'ORTHOGONAL');
  check(Math.abs(east.point.y) < 1e-9 && east.point.x > 0, 'ORTHO snaps to due East');

  const diag = captureGeometry.snapPoint({ x: 10, y: 8.5 }, anchor, 45, 'PARALLEL');
  check(Math.abs(diag.point.x - diag.point.y) < 1e-6, 'PARALLEL snaps onto last-edge bearing');

  const free = captureGeometry.snapPoint({ x: 10, y: 1.2 }, anchor, null, 'FREE');
  check(free.point.x === 10 && free.point.y === 1.2, 'FREE leaves cursor unchanged');
}

/* ---------- 6. Single-source parity ---------- */
console.log('\n[6] Single-source parity (trace vs preset)');
{
  const origin = { lat: 12.9716, lon: 77.5946 };
  const geom = siteBoundary.presetVertices('trapezoid', 20, { x: 0, y: 0 });
  const a = siteBoundary.buildPlotPolygonPayload({ vertices: geom, origin, source: 'preset' });
  const b = siteBoundary.buildPlotPolygonPayload({ vertices: geom, origin, source: 'trace' });
  check(
    JSON.stringify({ v: a.vertices, ar: a.area_sqm, s: a.shape_type }) ===
      JSON.stringify({ v: b.vertices, ar: b.area_sqm, s: b.shape_type }),
    'same geometry from any capture path -> byte-identical geometry payload'
  );
}

/* ---------- 7. Frontage suggestion (Overpass bearing -> edge) ---------- */
console.log('\n[7] Frontage suggestion math');
{
  const origin = { lat: 12.9716, lon: 77.5946 };
  // 12 x 18 CCW rectangle centered at origin: edge 0 = south (outward 180 deg).
  const vs = [
    { x: -6, y: -9 }, { x: 6, y: -9 }, { x: 6, y: 9 }, { x: -6, y: 9 },
  ];
  const south = siteIntelligence.suggestFrontageEdge(vs, 180);
  check(south !== null && south.edgeIndex === 0, `road due South suggests edge 0 (got ${south && south.edgeIndex})`);

  const north = siteIntelligence.suggestFrontageEdge(vs, 0);
  check(north !== null && north.edgeIndex === 2, `road due North suggests edge 2 (got ${north && north.edgeIndex})`);

  const east = siteIntelligence.suggestFrontageEdge(vs, 90);
  check(east !== null && east.edgeIndex === 1, `road due East suggests edge 1 (got ${east && east.edgeIndex})`);

  // CW input ring: winding handled internally. Index differs (reversed ring),
  // but the PHYSICAL edge must be the same southern edge.
  const cw = [...vs].reverse(); // [SE, NE, NW, SW] per input indexing
  const cwSouth = siteIntelligence.suggestFrontageEdge(cw, 180);
  const phys = cwSouth === null ? null : [cw[cwSouth.edgeIndex], cw[(cwSouth.edgeIndex + 1) % cw.length]];
  check(
    phys !== null &&
      ((phys[0].x === -6 && phys[0].y === -9 && phys[1].x === 6 && phys[1].y === -9) ||
        (phys[1].x === -6 && phys[1].y === -9 && phys[0].x === 6 && phys[0].y === -9)),
    'CW ring: same physical southern edge suggested'
  );

  check(siteIntelligence.suggestFrontageEdge(vs, null) === null, 'null bearing -> no suggestion (Amendment 1)');
  check(siteIntelligence.suggestFrontageEdge([{ x: 0, y: 0 }, { x: 1, y: 1 }], 90) === null, 'degenerate ring -> null');

  // L-shape: road bearing parallel to a long edge wins over the short edge.
  const lShape = siteBoundary.presetVertices('l_shape', 20, { x: 0, y: 0 });
  const southEdge = siteIntelligence.suggestFrontageEdge(lShape, 180);
  check(southEdge !== null, 'L-shape yields a suggestion');

  // Payload builder: boundary -> analyze/preview wire shape.
  const payload = siteIntelligence.boundaryToSummaryPayload({
    vertices: vs, origin, source: 'trace', frontageEdgeIndex: 1,
  });
  check(
    payload.vertices.length === 4 && typeof payload.vertices[0].x === 'number',
    'boundaryToSummaryPayload emits {x,y} vertex objects'
  );
  check(payload.frontage_edge_index === 1 && payload.source === 'trace', 'payload carries source + frontage');
  check(
    Math.abs(payload.area_sqm - 216) < 0.5 && payload.shape_type === 'rectangle',
    `payload metrics authoritative client-side (area ${payload.area_sqm}, ${payload.shape_type})`
  );

  const previewReq = siteIntelligence.buildPreviewPayload(
    { vertices: vs, origin, source: 'trace', frontageEdgeIndex: 1 }, 0.55
  );
  check(
    previewReq.boundary.frontage_edge_index === 1 && previewReq.ground_coverage_ratio === 0.55,
    'preview payload carries boundary + coverage'
  );

  // Taxonomy surface exported for HUD pills.
  check(
    Array.isArray(siteIntelligence.ANNOTATION_STATUSES) && siteIntelligence.ANNOTATION_STATUSES.length === 4,
    'annotation taxonomy has exactly 4 statuses'
  );
  check(
    siteIntelligence.ANNOTATION_BADGE.ASSUMED.className !== siteIntelligence.ANNOTATION_BADGE.CALCULATED.className,
    'ASSUMED never renders as CALCULATED (badge styling differs)'
  );

  /* ---------- Universal Validation Gate QA-panel logic ---------- */
  const validationGateUI = require(path.join(outDir, 'validationGateUI.js'));
  check(
    JSON.stringify(validationGateUI.GATE_LAYER_IDS) === JSON.stringify(Array.from({ length: 16 }, (_, i) => `L${i + 1}`)),
    'gate layer-id list is canonical L1..L16'
  );

  const sampleGate = {
    overall_status: 'WARN',
    layers: [
      { layer_id: 'L1', status: 'WARN', summary: 'aspect advisory', findings: ['aspect'] },
      { layer_id: 'L2', status: 'PASS', summary: 'swings ok' },
      { layer_id: 'L3', status: 'N/A', reason: 'No bathrooms in this generation' },
      { layer_id: 'L4', status: 'PASS', summary: 'furniture ok' },
      { layer_id: 'L5', status: 'FAIL', summary: 'naming fail' },
    ],
  };
  const grouped = validationGateUI.groupGateLayers(sampleGate);
  check(grouped.overall === 'WARN', 'grouping preserves overall status');
  check(grouped.warnChips.length === 1 && grouped.warnChips[0].layer_id === 'L1', 'WARN layer surfaces as chip');
  check(grouped.naRows.length === 1 && grouped.naRows[0].layer_id === 'L3', 'N/A row grouped for explicit-reason surfacing');
  check(grouped.failRows.length === 1 && grouped.failRows[0].layer_id === 'L5', 'FAIL row grouped');
  check(
    grouped.incompleteIds.length === 11 && grouped.incompleteIds[0] === 'L6' && grouped.incompleteIds.includes('L16'),
    'incomplete gate flagged (missing layer ids listed, never silently hidden)'
  );

  const naText = validationGateUI.qaRowText({ layer_id: 'L3', status: 'N/A', reason: 'No terrace zone' });
  check(naText.includes('N/A:') && naText.includes('No terrace zone'), 'N/A row text carries explicit reason');
  const passText = validationGateUI.qaRowText({ layer_id: 'L2', status: 'PASS', summary: 'swings ok' });
  check(passText === 'swings ok', 'PASS row text uses summary');

  const chipCls = validationGateUI.QA_CHIP_CLASSES;
  check(
    chipCls.PASS !== chipCls.FAIL && chipCls.WARN !== chipCls['N/A'] && Object.keys(chipCls).length === 4,
    'status chip classes distinct across all 4 statuses'
  );

  const overallFromAll = validationGateUI.groupGateLayers({
    layers: [{ layer_id: 'L1', status: 'FAIL', summary: 'x' }],
  });
  check(overallFromAll.overall === 'FAIL', 'missing overall_status derives from worst layer (FAIL)');

  /* ---------- Sheet truth (frontage + polygon hash) ---------- */
  const sheetTruth = require(path.join(outDir, 'sheetTruth.js'));
  const fixedHash = sheetTruth.polygonHashShort({ vertices: [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 8 }, { x: 0, y: 8 }] });
  check(fixedHash === '1674dc47', `polygon hash matches backend fixed vector (got ${fixedHash})`);
  const noisy = sheetTruth.polygonHashShort({ vertices: [{ x: 0.001, y: 0 }, { x: 9.999, y: 0 }, { x: 10.001, y: 8 }, { x: 0, y: 8.004 }] });
  check(noisy === fixedHash, 'polygon hash stable under 2-decimal float noise');
  check(sheetTruth.polygonHashShort(null) === '', 'empty polygon -> empty hash');
  check(
    sheetTruth.frontageChipText(1, 'trace') === 'FRTG 1 (trace)',
    'frontage chip carries edge + source'
  );
  check(
    sheetTruth.frontageChipText(null, null) === 'FRTG NA',
    'unconfirmed frontage renders NA (never fabricated)'
  );
  check(
    sheetTruth.polygonChipText({ vertices: [{ x: 0, y: 0 }] }).startsWith('POLYHASH '),
    'polygon chip renders POLYHASH prefix'
  );
  check(
    sheetTruth.polygonChipText(null) === 'POLYHASH NA',
    'polygon-less plan renders POLYHASH NA'
  );
}

/* ---------- 10. Frontage callouts + precision pick ---------- */
console.log('\n[10] Frontage callouts + precision pick');
{
  // 12 x 18 CCW rectangle at the origin: edges 12/18/12/18 with square bearings.
  const vs = [
    { x: -6, y: -9 }, { x: 6, y: -9 }, { x: 6, y: 9 }, { x: -6, y: 9 },
  ];
  const callouts = captureGeometry.edgeCallouts(vs);
  check(callouts.length === 4, `one callout per edge (got ${callouts.length})`);
  check(
    callouts.map((c) => Number(c.lengthM.toFixed(2))).join(',') === '12,18,12,18',
    `callout lengths 12/18/12/18 (got ${callouts.map((c) => c.lengthM.toFixed(2)).join(',')})`
  );
  check(
    callouts.map((c) => Math.round(c.bearingDeg)).join(',') === '90,0,270,180',
    `callout bearings follow the ring (got ${callouts.map((c) => Math.round(c.bearingDeg)).join(',')})`
  );
  check(
    callouts[0].label === 'P1-P2 · 12.00 m · E 00°00′ S',
    `callout label carries edge id + length + quadrant bearing (got "${callouts[0].label}")`
  );
  const mid = callouts[1].midpoint;
  check(Math.abs(mid.x - 6) < 1e-9 && Math.abs(mid.y) < 1e-9, 'callout anchors at the edge midpoint');

  // Precision pick: inside the band -> that edge; outside -> null (no silent grab).
  check(
    captureGeometry.nearestEdgeWithin(vs, { x: 6.5, y: 0 }, 2.0) === 1,
    'pointer 0.5 m from edge 1 picks edge 1'
  );
  check(
    captureGeometry.nearestEdgeWithin(vs, { x: 6.5, y: 0 }, 0.25) === null,
    'pointer outside the pick band -> null (click must not grab a random edge)'
  );
  // Centre of a 12 m-wide plot sits 6 m from the long edges: a 4 m band misses
  // (null), while a 7 m band legitimately reaches the nearest one.
  check(
    captureGeometry.nearestEdgeWithin(vs, { x: 0, y: 0 }, 4.0) === null,
    'dead centre with a 4 m band -> null'
  );
  check(
    captureGeometry.nearestEdgeWithin(vs, { x: 0, y: 0 }, 7.0) === 1,
    'dead centre with a 7 m band reaches the nearest edge'
  );
  check(
    captureGeometry.nearestEdgeWithin([{ x: 0, y: 0 }, { x: 1, y: 0 }], { x: 0.5, y: 0.1 }, 5) === null,
    'fewer than 3 vertices never hovers an edge'
  );
  check(captureGeometry.edgeCallouts([{ x: 0, y: 0 }]).length === 0, 'single vertex -> no callouts');
}

fs.rmSync(outDir, { recursive: true, force: true });
console.log(`\n=== boundary pipeline tests: ${pass} passed, ${fail} failed ===`);
process.exit(fail === 0 ? 0 : 1);
