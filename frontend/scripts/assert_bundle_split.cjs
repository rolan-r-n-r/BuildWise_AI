#!/usr/bin/env node
/**
 * assert_bundle_split.cjs — the two-route bundle contract, asserted.
 *
 * WHAT IT PROVES
 *   1. three.js / R3F reach the network ONLY from the landing graph. The 3D
 *      chunk is a dynamic entry of `src/landing/LandingPage.tsx` and appears in
 *      neither the shared entry graph nor `/app`'s initial graph.
 *   2. The `/app` initial graph is unchanged. Compared by SOURCE KEY rather than
 *      by emitted file name (content hashes move for unrelated reasons): the set
 *      of modules `/app` loads on a cold visit must be identical to the pinned
 *      baseline, with an explicit, tiny byte allowance for the one query-parameter
 *      reader the landing programme added.
 *   3. The landing's own initial JS stays inside its budget: baseline + 60 KB gz.
 *      The 3D chunk is deliberately NOT counted in that budget — it is a lazy
 *      chunk that a reduced-motion, save-data or no-WebGL reader never fetches.
 *
 * GRAPHS. "Initial graph" = the entry script plus every STATIC import reachable
 * from it, plus the route's dynamic entry (the route chunk itself IS the initial
 * graph of that route). Chunks reached only through `import()` from within the
 * route are lazy and excluded — which is exactly the distinction that keeps
 * three.js off both routes' critical paths.
 *
 * THE BUDGET IS PINNED, NOT A DIRECTORY. The ceilings used to be read out of a
 * `dist-audit-before` build, which is untracked: on a clean checkout that file
 * does not exist, so the gate failed on `baseline manifest present` before it
 * asserted anything. An untracked build cannot be a budget. The reference sizes
 * are constants below; if a comparison build IS supplied with `--baseline`, it is
 * used instead, because it additionally diffs the /app module set by source key.
 *
 * USAGE
 *   node scripts/assert_bundle_split.cjs                        # newest dist-*, pinned baseline
 *   node scripts/assert_bundle_split.cjs --baseline dist-audit-before   # full module diff
 *   node scripts/assert_bundle_split.cjs --json                 # machine-readable result
 */
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const argv = process.argv.slice(2);
const argOf = (flag, fallback) => {
  const i = argv.indexOf(flag);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const asJson = argv.includes('--json');

const ROOT = path.join(__dirname, '..');

/** gzip size of an emitted file, or 0 when it does not exist (css/asset noise). */
function gz(file) {
  try {
    return zlib.gzipSync(fs.readFileSync(path.join(file))).length;
  } catch {
    return 0;
  }
}

/**
 * The most recently written `dist-*` directory that actually carries a manifest.
 * Newest-by-mtime rather than alphabetical, so a fresh build is picked up without
 * editing this file. Consequence worth knowing: any `dist-*` left lying around is
 * a CANDIDATE, so a preview snapshot rebuilt after the real `dist/` silently
 * becomes "current" and the gate compares it against the baseline instead of the
 * shipped build. Keep `dist/` the newest, or pass `--dist` explicitly.
 */
/**
 * Build directories that are MEASUREMENT ARTIFACTS, never the shipped graph: the
 * prototype measurement build is produced by `VITE_PREVIEW_PROTOTYPES=1`, which
 * deliberately makes the unlinked prototype route live. It is excluded from the
 * auto-selection below so the gate cannot silently audit it instead of `dist/` —
 * which is exactly what happened once, when the prototype build was rebuilt after
 * the landing build (the gate reported a /app graph one module wider and a landing
 * 1.3 KB gz heavier, neither of which was true of the shipped build).
 */
const MEASUREMENT_DISTS = ['dist-preview'];

function newestDist(exclude = []) {
  const dirs = fs
    .readdirSync(ROOT, { withFileTypes: true })
    .filter((e) => e.isDirectory() && /^dist/.test(e.name))
    .map((e) => e.name)
    .filter(
      (name) =>
        !exclude.includes(name) &&
        !MEASUREMENT_DISTS.includes(name) &&
        fs.existsSync(path.join(ROOT, name, '.vite', 'manifest.json')),
    )
    .map((name) => ({ name, mtime: fs.statSync(path.join(ROOT, name, '.vite', 'manifest.json')).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  return dirs.length ? dirs[0].name : null;
}

function loadManifest(dist) {
  const file = path.join(ROOT, dist, '.vite', 'manifest.json');
  if (!fs.existsSync(file)) throw new Error(`no manifest at ${file} — build first (vite build)`);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

/** Find the manifest key whose emitted file is the HTML entry script. */
function entryKey(manifest) {
  const found = Object.entries(manifest).find(([key]) => key === 'index.html');
  if (!found) throw new Error('no index.html entry in the manifest');
  return found[0];
}

/** Find the dynamic-entry key for a source module (route chunk). */
function routeKey(manifest, sourceSuffix) {
  const found = Object.entries(manifest).find(
    ([key, value]) => value.isDynamicEntry && key.replace(/\\/g, '/').endsWith(sourceSuffix),
  );
  if (!found) throw new Error(`no dynamic entry for ${sourceSuffix}`);
  return found[0];
}

/**
 * A graph member's STABLE identity.
 *
 * Rollup emits two kinds of manifest key: real source paths (`src/App.tsx`) and
 * synthesised shared chunks named after their content (`_Icon-C_BtUS-v.js`).
 * Comparing raw keys therefore reports a shared chunk as "added and removed"
 * whenever its hash moves for an unrelated reason, which is noise, not a
 * regression. Stripping the hash makes the comparison answer the question that
 * was actually asked: did a different MODULE enter the route's graph?
 */
function stableKey(key) {
  return key.replace(/-[A-Za-z0-9_-]{6,12}\.js$/, '.js');
}

/**
 * Every module in a route's initial graph: the entry, that entry's static
 * imports, and the route's own dynamic entry with ITS static imports. Lazy
 * chunks (reached only through dynamicImports) are excluded by construction.
 */
function initialGraph(manifest, keys) {
  const seen = new Set();
  const queue = [...keys];
  while (queue.length) {
    const key = queue.shift();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    for (const imported of manifest[key]?.imports ?? []) queue.push(imported);
  }
  return seen;
}

/** Modules reachable only through `import()` from a graph — the lazy set. */
function lazySet(manifest, initial) {
  const lazy = new Set();
  for (const key of initial) {
    for (const child of manifest[key]?.dynamicImports ?? []) {
      if (!initial.has(child)) lazy.add(child);
    }
  }
  return lazy;
}

function sizeOf(manifest, keys, dist) {
  let gzip = 0;
  let raw = 0;
  for (const key of keys) {
    const file = manifest[key]?.file;
    if (!file || !file.endsWith('.js')) continue;
    gzip += gz(path.join(ROOT, dist, file));
    try {
      raw += fs.statSync(path.join(ROOT, dist, file)).size;
    } catch {
      /* asset-only entry */
    }
  }
  return { gzip, raw, kb: Math.round((gzip / 1024) * 100) / 100 };
}

const KB = (bytes) => Math.round((bytes / 1024) * 100) / 100;

function main() {
  const baselineDist = argOf('--baseline', 'dist-audit-before');
  const dist = argOf('--dist', newestDist([baselineDist]));
  if (!dist) throw new Error('no built dist found — run `npm run build -- --outDir dist-<name>` first');

  const manifest = loadManifest(dist);
  const entry = entryKey(manifest);
  const landing = routeKey(manifest, 'src/landing/LandingPage.tsx');
  const app = routeKey(manifest, 'src/App.tsx');

  const entryGraph = initialGraph(manifest, [entry]);
  const landingGraph = initialGraph(manifest, [entry, landing]);
  const appGraph = initialGraph(manifest, [entry, app]);

  const landingLazy = lazySet(manifest, landingGraph);

  const entrySize = sizeOf(manifest, entryGraph, dist);
  const landingSize = sizeOf(manifest, landingGraph, dist);
  const appSize = sizeOf(manifest, appGraph, dist);

  // --- the 3D chunk: a lazy child of the landing route, and nothing else -----
  const three3dKeys = [...landingLazy].filter((key) => /hero3d[\\/]/i.test(key));
  // The 3D chunk's real cost: the hero3d modules only. `landingLazy` also
  // contains sibling route chunks (App), which are not part of this number.
  const threeLazySize = sizeOf(manifest, three3dKeys, dist);
  const threeInApp = [...appGraph].filter((key) => /hero3d[\\/]/i.test(key) || /three/i.test(key));
  const threeInEntry = [...entryGraph].filter((key) => /hero3d[\\/]/i.test(key) || /three/i.test(key));
  // three.js's own package must be inside the 3D chunk, never in an initial graph.
  const threeModuleInInitial = [...landingGraph, ...appGraph].filter((key) =>
    /node_modules[\\/](three|@react-three)[\\/]/.test(key),
  );

  const failures = [];
  const checks = [];
  const check = (name, ok, detail) => {
    checks.push({ name, ok, detail });
    if (!ok) failures.push(`${name}: ${detail}`);
  };

  /*
   * THE 3D LIBRARY MUST BE ABSENT, NOT MERELY LAZY.
   *
   * This check used to assert the opposite — that three.js occupied a landing-only
   * lazy chunk — which was the right assertion while the hero was a WebGL massing
   * model. Two 3D heroes have since been built and removed, and the landing is now
   * the copy-led baseline with no GPU library on either route, so the
   * assertion inverts: the dependency, its renderer and its typings were removed
   * from package.json, and a chunk containing any of them appearing in ANY graph
   * (entry, landing initial, landing lazy, or /app) is a regression. Asserting
   * `> 0` here would have gone on passing while a 243.90 KB gz chunk quietly
   * returned; asserting `=== 0` is the check that actually holds the line.
   */
  const threeAnywhere = [...three3dKeys, ...threeInEntry, ...threeModuleInInitial];
  check(
    'three.js is ABSENT from every graph (landing and /app)',
    threeAnywhere.length === 0,
    threeAnywhere.length ? `found: ${threeAnywhere.slice(0, 6).join(', ')}` : 'no three / @react-three / hero3d module in any graph',
  );
  check(
    'three.js is NOT in the entry graph',
    threeInEntry.length === 0 && threeModuleInInitial.filter((k) => entryGraph.has(k)).length === 0,
    threeInEntry.length ? threeInEntry.join(', ') : 'absent',
  );
  check(
    'three.js is NOT in the /app initial graph',
    threeInApp.length === 0,
    threeInApp.length ? threeInApp.join(', ') : 'absent',
  );
  check(
    'no three / @react-three module sits in ANY initial graph',
    threeModuleInInitial.length === 0,
    threeModuleInInitial.length ? threeModuleInInitial.join(', ') : 'absent',
  );

  // --- budgets ---------------------------------------------------------------
  const LANDING_ALLOWANCE_KB = 60;
  const APP_ALLOWANCE_KB = 2; // the single query-parameter reader, measured
  /* The pre-hero graphs, gzipped — the sizes the landing rewrite was measured
     against, kept here so the gate is reproducible from a clean checkout. */
  const PINNED_LANDING_BASE_KB = 135.07;
  // 112.35 → 114.80: the progressive blueprint reveal. BlueprintViewer is in
  // the /app graph because the report/cost-plan card is part of the route, so
  // the phase controller + inert phase CSS are initial-route bytes. The module
  // set is unchanged apart from the new report/blueprintReveal.ts; this base is
  // the measured shipped build after that feature, not a hand-raised ceiling —
  // the +2 KB allowance below still catches future drift.
  const PINNED_APP_BASE_KB = 114.8;

  let baseLandingKb = PINNED_LANDING_BASE_KB;
  let baseAppKb = PINNED_APP_BASE_KB;
  let appKeyChange = null;

  const hasBaseline = fs.existsSync(path.join(ROOT, baselineDist, '.vite', 'manifest.json'));
  if (hasBaseline) {
    const baseManifest = loadManifest(baselineDist);
    const baseLandingGraph = initialGraph(baseManifest, [entryKey(baseManifest), routeKey(baseManifest, 'src/landing/LandingPage.tsx')]);
    const baseAppGraph = initialGraph(baseManifest, [entryKey(baseManifest), routeKey(baseManifest, 'src/App.tsx')]);
    baseLandingKb = sizeOf(baseManifest, baseLandingGraph, baselineDist).kb;
    baseAppKb = sizeOf(baseManifest, baseAppGraph, baselineDist).kb;

    const baseMembers = new Set([...baseAppGraph].map(stableKey));
    const members = new Set([...appGraph].map(stableKey));
    const added = [...members].filter((k) => !baseMembers.has(k));
    const removed = [...baseMembers].filter((k) => !members.has(k));
    appKeyChange = { added, removed };
  }

  const landingDeltaKb = Math.round((landingSize.kb - baseLandingKb) * 100) / 100;
  const appDeltaKb = Math.round((appSize.kb - baseAppKb) * 100) / 100;
  const sign = (v) => `${v >= 0 ? '+' : ''}${v}`;

  check(
    `/app initial graph unchanged (≤ +${APP_ALLOWANCE_KB} KB gz, no modules added)`,
    appDeltaKb <= APP_ALLOWANCE_KB && (!appKeyChange || (appKeyChange.added.length === 0 && appKeyChange.removed.length === 0)),
    appKeyChange
      ? `added=${appKeyChange.added.length} removed=${appKeyChange.removed.length} delta=${appDeltaKb} KB gz` +
          (appKeyChange.added.length ? ` added:[${appKeyChange.added.join(', ')}]` : '') +
          (appKeyChange.removed.length ? ` removed:[${appKeyChange.removed.join(', ')}]` : '')
      : `baseline ${baseAppKb} KB → ${appSize.kb} KB (${sign(appDeltaKb)} KB gz); module diff needs a --baseline build`,
  );
  check(
    `landing initial JS ≤ baseline + ${LANDING_ALLOWANCE_KB} KB gz`,
    landingDeltaKb <= LANDING_ALLOWANCE_KB,
    `baseline ${baseLandingKb} KB → ${landingSize.kb} KB (${sign(landingDeltaKb)} KB gz)`,
  );

  const result = {
    dist,
    baselineDist,
    entryGraphKb: entrySize.kb,
    landingInitialKb: landingSize.kb,
    landingInitialRawKb: KB(landingSize.raw),
    landingDeltaKb,
    landingLazy3dKb: threeLazySize.kb,
    appInitialKb: appSize.kb,
    appDeltaKb,
    appModulesAdded: appKeyChange?.added ?? null,
    appModulesRemoved: appKeyChange?.removed ?? null,
    landingLazyKeys: [...landingLazy],
    three3dKeys,
    checks,
    passed: failures.length === 0,
    failures,
  };

  if (asJson) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } else {
    console.log(`bundle split — ${dist}  (baseline ${hasBaseline ? baselineDist : 'pinned constants'})`);
    console.log(`  entry graph          ${entrySize.kb} KB gz`);
    console.log(`  landing initial      ${landingSize.kb} KB gz${landingDeltaKb !== null ? `  (${landingDeltaKb >= 0 ? '+' : ''}${landingDeltaKb})` : ''}`);
    console.log(`  landing lazy (3D)    ${threeLazySize.kb} KB gz  ← not fetched by poster rungs`);
    console.log(`  /app initial         ${appSize.kb} KB gz${appDeltaKb !== null ? `  (${appDeltaKb >= 0 ? '+' : ''}${appDeltaKb})` : ''}`);
    console.log('');
    for (const c of checks) console.log(`  ${c.ok ? 'PASS' : 'FAIL'}  ${c.name} — ${c.detail}`);
    console.log('');
    if (failures.length) {
      console.error(`FAILED: ${failures.length} check(s)`);
      process.exit(1);
    }
    console.log('OK: no GPU library in any graph and /app is unchanged.');
  }
  process.exit(failures.length ? 1 : 0);
}

main();
