#!/usr/bin/env node
/**
 * lint_material.cjs — the material discipline gate.
 * ==========================================================
 * The dossier states the rule as a rule, not a preference:
 *
 *   floating chrome (nav pill, chips, tooltips, window bar) → translucent +
 *     backdrop-filter
 *   everything else (cards, stage planes, sheets, panels)    → opaque or
 *     token-tinted fill, token hairline
 *   and: "the landing gains NO new backdrop-filter surface anywhere in
 *   Phases 1–2. Blur count stays where the audit found it."
 *
 * WHY THIS IS A LINT AND NOT A NOTE IN A DOC. A blur is the one material that is
 * cheap to add and expensive to keep: every translucent surface is a live
 * backdrop sample, on an animated layer it is a per-frame paint, and no unit test
 * sees it, because it is a CSS value rather than a behaviour. So the ledger below
 * is checked in two directions — every blur in the tree must be CLASSIFIED, and
 * the classified set must equal the pinned baseline exactly. Adding a surface
 * fails; deleting one also fails until the baseline is regenerated (`--update`),
 * which is deliberate: the pin has to be a decision someone made.
 *
 * A baseline can never authorise a non-chrome surface. The classification rule
 * runs on the CURRENT tree, not on the baseline, so a name-shaped evasion (calling
 * a card `.vibrancy-pill`) still fails on the selector it actually is.
 *
 * Usage:
 *   node scripts/lint_material.cjs            # gate (exit 1 on any change)
 *   node scripts/lint_material.cjs --update   # regenerate the pinned ledger
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const BASELINE_PATH = path.join(__dirname, 'material-baseline.json');

/**
 * What MAY carry a blur, and why. Matched against a normalised CSS selector
 * (one selector per comma-separated part) or against a component source line.
 *
 * `landing-chrome` is the dossier's floating chrome: surfaces that float ABOVE the
 * page and whose whole job is to let the page show through. `app-glass` is the
 * pre-existing glass inside `/app` (map HUD, overlays, the report sheet): it is not
 * reachable from the landing route, it is pinned so this phase cannot grow it, and
 * it is deliberately a different class from the landing's chrome, because "the app
 * already has glass" must not become a licence for the landing to add some.
 */
const FLOATING_CHROME = [
  { re: /^\.bw-nav$/, kind: 'landing-chrome', why: 'the floating nav pill — it sits over the hero as the page scrolls' },
  { re: /^\.vibrancy-pill$/, kind: 'app-glass', why: 'map HUD pills, which float over the basemap' },
  { re: /^\.vibrancy-hud$/, kind: 'app-glass', why: 'the map HUD itself' },
  { re: /^\.vibrancy-panel$/, kind: 'app-glass', why: 'the capture drawer panel over the map' },
  { re: /maplibregl-popup-content$/, kind: 'app-glass', why: 'the map popup, which must read over arbitrary basemap pixels' },
];

const APP_SOURCE_GLASS = [
  { re: /^src\/components\/BlueprintViewer\.tsx$/, kind: 'app-glass', why: 'the blueprint modal scrim' },
  { re: /^src\/components\/map\/CaptureSheet\.tsx$/, kind: 'app-glass', why: 'capture HUD pills' },
  { re: /^src\/components\/MethodologyModal\.tsx$/, kind: 'app-glass', why: 'methodology modal scrim' },
  { re: /^src\/components\/SiteMoveDialog\.tsx$/, kind: 'app-glass', why: 'site-move dialog scrim' },
  { re: /^src\/components\/ReportSheet\.tsx$/, kind: 'app-glass', why: 'the report sheet surface' },
  { re: /^src\/design\/primitives\.tsx$/, kind: 'app-glass', why: 'the shared scrim primitive (`animate-scrim`)' },
];

/** The same surfaces as literal selector text, for reading a built stylesheet. */
const CHROME_SELECTOR_TEXT = ['.bw-nav', '.vibrancy-pill', '.vibrancy-hud', '.vibrancy-panel', 'maplibregl-popup-content'];

/**
 * The landing's own blur surfaces, pinned as a LITERAL as well as through the
 * ledger, so the headline claim of the material rule ("the landing gains no new
 * surface") is checkable without reading the baseline JSON. One: `.bw-nav`.
 */
const PINNED_LANDING_SURFACES = 1;

const walk = (dir, out = []) => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (/\.(tsx?|jsx?)$/.test(entry.name)) out.push(full);
  }
  return out;
};

const rel = (p) => path.relative(ROOT, p).split(path.sep).join('/');

/** Every CSS rule that blurs what is behind it, deduped per selector. */
function scanCss() {
  const raw = fs.readFileSync(path.join(ROOT, 'src', 'index.css'), 'utf8');
  const css = raw.replace(/\/\*[\s\S]*?\*\//g, '');
  const bySelector = new Map();
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = match[1].split(';').pop().trim().replace(/\s+/g, ' ');
    const body = match[2];
    for (const decl of body.matchAll(/(backdrop-filter|-webkit-backdrop-filter|filter)\s*:\s*([^;}]+)/g)) {
      if (!/blur\(/i.test(decl[2])) continue;
      const key = selector;
      const prev = bySelector.get(key) || { file: 'src/index.css', selector, occurrences: 0, declarations: new Set() };
      prev.occurrences += 1;
      prev.declarations.add(`${decl[1]}: ${decl[2].trim()}`);
      bySelector.set(key, prev);
    }
  }
  return [...bySelector.values()].map((e) => ({
    where: `${e.file} :: ${e.selector}`,
    file: e.file,
    selector: e.selector,
    occurrences: e.occurrences,
    declaration: [...e.declarations].join(' | '),
  }));
}

/**
 * Every component line that asks for a blur, through Tailwind or an inline style.
 *
 * COMMENTS ARE STRIPPED, and not cosmetically: this repository documents its own
 * removed glass by name (SectionNav.tsx records the frosted band it used to carry),
 * so a naive scan reports a comment as a live surface. `//` is only a comment when
 * it is not part of `https://`, which is why the lookbehind excludes a colon.
 */
function scanSources() {
  const out = [];
  for (const file of walk(path.join(ROOT, 'src'))) {
    const source = fs
      .readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ' '))
      .split(/\r?\n/)
      .map((line) => line.split(/(?<![\w:])\/\//)[0]);
    source.forEach((line, i) => {
      const hit = /backdrop-blur|backdropFilter|WebkitBackdropFilter/.test(line);
      if (!hit) return;
      out.push({
        where: `${rel(file)}:${i + 1}`,
        file: rel(file),
        line: i + 1,
        text: line.trim().slice(0, 120),
      });
    });
  }
  return out;
}

/** Classify an entry: chrome, app glass, or nothing (a failure). */
function classify(entry) {
  if (entry.selector) {
    for (const part of entry.selector.split(',').map((s) => s.trim())) {
      for (const rule of FLOATING_CHROME) if (rule.re.test(part)) return rule;
    }
    return null;
  }
  for (const rule of APP_SOURCE_GLASS) if (rule.re.test(entry.file)) return rule;
  return null;
}

const entries = [...scanCss(), ...scanSources()].sort((a, b) => a.where.localeCompare(b.where));
const classified = entries.map((e) => ({ ...e, classification: classify(e) }));

let failures = 0;
const fail = (label) => {
  failures += 1;
  console.log(`  FAIL ${label}`);
};

console.log('\n[1] Every blur in the tree is classified as chrome');
for (const entry of classified) {
  const rule = entry.classification;
  if (rule) {
    console.log(`  ok   ${entry.where.padEnd(52)} ${rule.kind.padEnd(14)} ${rule.why}`);
  } else {
    fail(`${entry.where} declares a blur but is not floating chrome — a card, plane, sheet or panel stays opaque`);
  }
}

console.log('\n[2] The landing adds no blur surface');
const landing = classified.filter((e) => e.classification?.kind === 'landing-chrome');
if (landing.length === PINNED_LANDING_SURFACES) {
  console.log(`  ok   ${landing.length} landing blur surface (${landing.map((e) => e.where).join(', ')})`);
} else {
  fail(`the landing carries ${landing.length} blur surfaces, pinned at ${PINNED_LANDING_SURFACES}`);
}
const landingSources = classified.filter(
  (e) => e.classification?.kind === 'landing-chrome' && !(e.selector && /^\.bw-/.test(e.selector)),
);
for (const e of landingSources) fail(`a landing surface is blurred through something other than a bw- class: ${e.where}`);

console.log('\n[3] The ledger equals the pinned baseline');
const ledger = classified.map((e) => e.where);
if (process.argv.includes('--update')) {
  fs.writeFileSync(BASELINE_PATH, `${JSON.stringify({ note: 'Pinned blur/translucency ledger. Regenerate with: node scripts/lint_material.cjs --update', surfaces: ledger }, null, 2)}\n`);
  console.log(`  wrote scripts/${path.basename(BASELINE_PATH)} with ${ledger.length} surfaces`);
} else if (!fs.existsSync(BASELINE_PATH)) {
  fail('no baseline pinned yet — run: node scripts/lint_material.cjs --update');
} else {
  const baseline = JSON.parse(fs.readFileSync(BASELINE_PATH, 'utf8')).surfaces;
  const added = ledger.filter((w) => !baseline.includes(w));
  const removed = baseline.filter((w) => !ledger.includes(w));
  if (!added.length && !removed.length) console.log(`  ok   ${ledger.length} surfaces, unchanged from the baseline`);
  for (const w of added) fail(`new blur surface: ${w}`);
  for (const w of removed) fail(`blur surface gone, baseline not regenerated: ${w}`);
}

console.log('\n[4] The BUILT stylesheet keeps the standard property');
/*
 * THE DEFECT THIS SECTION EXISTS FOR, measured rather than reasoned about: the
 * minifier collapses the `-webkit-backdrop-filter` / `backdrop-filter` pair to ONE
 * declaration and keeps the LAST one written. With the standard property written
 * first — the natural way to write it — the shipped stylesheet contained only
 * `-webkit-backdrop-filter`, which Chrome and Firefox do not support, so every
 * hand-written glass rule on the landing and in the app was transparent in the
 * artifact while reading as correct in the source. Writing the prefix first and the
 * standard property last is what keeps both.
 *
 * This is checked against a real build when one is present, and skipped (never
 * silently passed) when there is none.
 */
/* Only the CANONICAL build output, by name. Scanning every `dist-*` directory
   would report on artifacts built before this check existed, which is noise rather
   than a gate. `dist-preview` is the measurement build and is covered by the
   browser probe, which reads computed styles on the rendered page. */
const assetsDir = path.join(ROOT, 'dist', 'assets');
const builds = fs.existsSync(assetsDir)
  ? fs
      .readdirSync(assetsDir)
      .filter((f) => f.endsWith('.css'))
      .map((f) => path.join(assetsDir, f))
  : [];
if (!builds.length) {
  console.log('  ·    no build in dist/ — run `npm run build` to check the artifact');
} else {
  let broken = 0;
  let kept = 0;
  for (const file of builds) {
    const css = fs.readFileSync(file, 'utf8');
    for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = rule[1].replace(/^[;}]+/, '').trim();
      const body = rule[2];
      if (!/-webkit-backdrop-filter\s*:/i.test(body)) continue;
      const isChrome = CHROME_SELECTOR_TEXT.some((s) => selector.includes(s));
      if (!isChrome) continue;
      /* The standard declaration must survive WHATEVER IT SAYS — a blur, or the
         `none` opt-out (a rule that switches glass off has to switch it off in the
         standard property too, or Chrome keeps blurring under
         `prefers-reduced-transparency`). `-webkit-backdrop-filter:` must not be
         mistaken for it, hence the leading character class. */
      if (/[^-]backdrop-filter\s*:/i.test(body)) kept += 1;
      else {
        broken += 1;
        fail(`${rel(file)} :: ${selector} ships only -webkit-backdrop-filter — glass Chrome and Firefox will not paint`);
      }
    }
  }
  if (!broken && kept) console.log(`  ok   ${kept} blurred chrome rule(s) in dist/ carry the standard property`);
  if (!broken && !kept) fail('dist/ contains no blurred chrome rule at all — the glass policy is not reaching the artifact');
}

console.log(`\n${classified.length} blur surfaces, ${failures} failure(s)`);
process.exit(failures === 0 ? 0 : 1);
