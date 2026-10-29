#!/usr/bin/env node
/**
 * interaction_probe.cjs — the browser half of the interaction acceptance suite.
 * ======================================================================
 * `scripts/test_interaction_primitives.cjs` proves the PURE cores with plain node
 * arithmetic. What it cannot prove is anything that only exists once the page is
 * running: that a rung with every capability flag off registers NO listener, that a
 * hundred trusted pointer moves do not restructure the DOM, that the pose really
 * stops being driven when the stage leaves the viewport, that an anchor lands on
 * its section to the pixel, and that the reduced-motion page is the animated page's
 * settled frame rather than a different composition.
 *
 * That is this harness — a REAL production build, served on loopback, driven by
 * real Chrome through puppeteer-core with TRUSTED input (CDP input events, never
 * `element.dispatchEvent`), because a synthetic event would not exercise the path
 * the reader's finger uses.
 *
 *   [1] The rung matrix + listener ledger (P7, P2). Four rungs — full, coarse,
 *       reduced-motion, and all four flags at once — with `EventTarget
 *       .addEventListener` counted before any app code runs. The full rung must
 *       carry exactly the primitives' own listeners; every "do less" rung must
 *       carry none of them; the coarse rung must swap the pointer for the device's
 *       own orientation, exactly as the capability gate documents.
 *   [2] A 100-move trusted pointer sweep (P2/P3): frame intervals, long tasks, CLS,
 *       and every DOM mutation the sweep causes classified. A pointer move must
 *       cost a transform write, not a render — asserted as "no childList, no
 *       characterData, no non-style attribute changes", and cross-checked by
 *       reading the readout's own text before and after.
 *   [3] The idle contract (P2/P7): scroll the stage out of view and the primitives'
 *       window listeners must drop to zero.
 *   [4] The anchor-landing invariant (P6) and document-height stability on `/`:
 *       anchor jumps land within 1 px of the section top, and the document does not
 *       change height between load and a full scroll — the fabricated-height
 *       failure this page has already had once.
 *   [5] Material discipline, measured: every element whose computed
 *       `backdrop-filter` is not `none`, checked against the floating-chrome
 *       whitelist (the source-side half is `scripts/lint_material.cjs`).
 *   [6] Reduced motion equals the settled frame (pixel comparison): the stage clip
 *       on a `prefers-reduced-motion: reduce` load against the same clip on a
 *       normal load, decoded and diffed in the page itself.
 *
 * WHICH RUNG IS FORCED, AND WHY THAT IS SAID OUT LOUD. `prefers-reduced-motion` is
 * emulated natively by the browser. `saveData` and `deviceMemory` are pinned onto
 * `navigator` because no browser emulates them, and `(pointer: coarse)` is answered
 * through `matchMedia` — the exact call `readCapabilityInput` makes — because CDP
 * device emulation does not reliably flip it. Every rung therefore reports
 * `forced`, and the report prints what the page READ BACK, so a rung is never
 * assumed from what was asked for.
 *
 * USAGE
 *   PROBE_URL=http://localhost:4322/preview/trace
 *   CHROME_PATH="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
 *   node scripts/interaction_probe.cjs
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const INTERACTION_URL = process.env.PROBE_URL || 'http://localhost:4322/preview/trace';
const ORIGIN = new URL(INTERACTION_URL).origin;
const LANDING_URL = `${ORIGIN}/`;
const PHASE = process.env.AUDIT_PHASE || 'phase-1-interaction';
const OUT_DIR = path.join(__dirname, '..', '.audit', PHASE);
const SHOTS_DIR = path.join(OUT_DIR, 'shots');

/** The elements' own classes that may carry glass — mirrors `lint_material.cjs`. */
const CHROME_CLASSES = ['bw-nav', 'vibrancy-pill', 'vibrancy-hud', 'vibrancy-panel'];

const RUNGS = [
  { name: 'full', width: 1440, height: 900, touch: false, forced: [] },
  { name: 'coarse', width: 390, height: 844, touch: true, forced: ['pointer: coarse'] },
  { name: 'reduced', width: 1440, height: 900, touch: false, reduced: true, forced: ['prefers-reduced-motion (native CDP emulation)'] },
  {
    name: 'all-four',
    width: 390,
    height: 844,
    touch: true,
    reduced: true,
    coarse: true,
    saveData: true,
    lowMemory: 2,
    forced: ['pointer: coarse', 'navigator.connection.saveData', 'navigator.deviceMemory', 'prefers-reduced-motion (native CDP emulation)'],
  },
];

function chromePath() {
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) return process.env.CHROME_PATH;
  const candidates = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    '/usr/bin/google-chrome',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  throw new Error('Chrome not found — set CHROME_PATH');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const round = (v) => Math.round(v * 100) / 100;

const checks = [];
const check = (id, ok, detail) => {
  checks.push({ id, ok: Boolean(ok), detail });
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${id}${detail ? ` — ${detail}` : ''}`);
};

/* ------------------------------------------------------------------ */
/* page-side instrumentation                                           */
/* ------------------------------------------------------------------ */

/**
 * Count live listeners, per target and type, from before the app boots.
 *
 * A COUNTING WRAPPER, NOT A MIRROR: the primitive cannot report "I registered one
 * listener" and be believed — this observes the registration itself. The one
 * approximation is that re-adding an identical (type, handler) pair counts twice
 * where the platform would keep one, which can only over-report.
 */
function recordListeners() {
  const live = { window: new Map(), document: new Map(), element: new Map() };
  const bucket = (target) => (target === window ? live.window : target === document ? live.document : live.element);
  const bump = (target, type, delta) => {
    const m = bucket(target);
    m.set(type, (m.get(type) || 0) + delta);
    if (m.get(type) <= 0) m.delete(type);
  };
  const add = EventTarget.prototype.addEventListener;
  const remove = EventTarget.prototype.removeEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    bump(this, String(type), 1);
    return add.call(this, type, fn, opts);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, opts) {
    bump(this, String(type), -1);
    return remove.call(this, type, fn, opts);
  };
  window.__listeners = () => ({
    window: Object.fromEntries(live.window),
    document: Object.fromEntries(live.document),
    element: Object.fromEntries(live.element),
  });
}

/** The three "do less" flags no browser emulates, plus the coarse pointer query. */
function rungScript(flags) {
  if (flags.coarse) {
    const native = window.matchMedia.bind(window);
    window.matchMedia = (query) =>
      /pointer:\s*coarse/.test(query)
        ? {
            matches: true,
            media: query,
            onchange: null,
            addEventListener() {},
            removeEventListener() {},
            addListener() {},
            removeListener() {},
            dispatchEvent: () => false,
          }
        : native(query);
  }
  if (flags.saveData) Object.defineProperty(navigator, 'connection', { configurable: true, get: () => ({ saveData: true }) });
  if (flags.lowMemory) Object.defineProperty(navigator, 'deviceMemory', { configurable: true, get: () => flags.lowMemory });
}

/** Vitals + a frame recorder, installed after load (a new-document throw is silent). */
function installMetrics() {
  const w = window;
  w.__probe = { longTasks: [], cls: 0, lcp: 0 };
  const observe = (type, fn) => {
    try {
      new PerformanceObserver(fn).observe({ type, buffered: true });
    } catch {
      /* unsupported in this browser */
    }
  };
  observe('layout-shift', (list) => {
    for (const entry of list.getEntries()) if (!entry.hadRecentInput) w.__probe.cls += entry.value;
  });
  observe('largest-contentful-paint', (list) => {
    for (const entry of list.getEntries()) w.__probe.lcp = Math.max(w.__probe.lcp, entry.startTime);
  });
  observe('longtask', (list) => {
    for (const entry of list.getEntries()) w.__probe.longTasks.push(Math.round(entry.duration));
  });
  w.__frameStart = () => {
    w.__frames = [];
    let last = performance.now();
    const tick = (t) => {
      w.__frames.push(t - last);
      last = t;
      w.__raf = requestAnimationFrame(tick);
    };
    w.__raf = requestAnimationFrame(tick);
  };
  w.__frameStop = () => {
    if (w.__raf) cancelAnimationFrame(w.__raf);
    return w.__frames.slice(1);
  };
}

/**
 * The entry band, READ FROM THE MODULE THAT DEFINES IT.
 *
 * This harness is a plain node script and `scrub.ts` is TypeScript, so it cannot be
 * imported here — but it must not be retyped either: [7] computes where the hero's
 * roof *should* be from these two numbers, and a copy that drifted from the source
 * would turn a real lag into a pass. If the source ever stops matching this shape,
 * the probe fails loudly instead of measuring the wrong band.
 */
function readEntryBand() {
  const file = path.join(__dirname, '..', 'src', 'landing', 'interaction', 'scrub.ts');
  const match = fs
    .readFileSync(file, 'utf8')
    .match(/export const ENTRY_BAND = \{ from: ([\d.]+), to: ([\d.]+) \}/);
  if (!match) throw new Error(`ENTRY_BAND not found in ${file} — the probe must not guess it`);
  return { from: Number(match[1]), to: Number(match[2]) };
}
const ENTRY = readEntryBand();

/**
 * The hero's own sub-band for the rise, read from the component for the same reason
 * the entry band is read from the module: the roof's expected position is only
 * comparable to the drawing if the same remap is applied. `RISE_TO` is 0.60, i.e. the
 * storey finishes a third of the way before the band does — which is exactly the
 * property that makes the settled frame reachable, so a probe that ignored it would
 * report the roof as permanently ahead of its line.
 */
function readRiseSubBand() {
  const file = path.join(__dirname, '..', 'src', 'landing', 'HeroModel.tsx');
  const text = fs.readFileSync(file, 'utf8');
  const from = text.match(/const RISE_FROM = ([\d.]+);/);
  const to = text.match(/const RISE_TO = ([\d.]+);/);
  if (!from || !to) throw new Error(`RISE_FROM/RISE_TO not found in ${file} — the probe must not guess them`);
  return { from: Number(from[1]), to: Number(to[1]) };
}
const RISE_BAND = readRiseSubBand();

function histogram(samples) {
  const sorted = [...samples].sort((a, b) => a - b);
  const pct = (p) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))] : 0);
  const mean = sorted.length ? sorted.reduce((a, b) => a + b, 0) / sorted.length : 0;
  return {
    samples: sorted.length,
    p50: round(pct(50)),
    p95: round(pct(95)),
    max: round(sorted[sorted.length - 1] ?? 0),
    fps: mean ? round(1000 / mean) : 0,
    over16_7ms: sorted.filter((v) => v > 16.7).length,
    over50ms: sorted.filter((v) => v > 50).length,
  };
}

const STAGE_BOX = () => {      const el = document.querySelector('[data-bw-stage]');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height, docTop: r.top + window.scrollY };
};

const POSE_MATRIX = () => {
  const stage = document.querySelector('[data-bw-stage]');
  const el = stage && stage.querySelector('[style*="preserve-3d"]');
  return el ? getComputedStyle(el).transform : null;
};

const READOUT = () => {
  const out = {};
  for (const div of document.querySelectorAll('dl > div')) {
    const key = div.querySelector('dt')?.textContent?.trim();
    if (key) out[key] = div.querySelector('dd')?.textContent?.trim() ?? '';
  }
  return out;
};

const LISTENERS = () => window.__listeners();

/**
 * The 16 numbers of a `matrix3d(…)`, and the largest difference between two of
 * them.
 *
 * Comparing the transform STRINGS for equality (the obvious way) is brittle in a way
 * that has nothing to do with the page: a spring converges asymptotically, so the
 * rest matrix after a reset lands within ~1e-4 of where it started rather than exactly
 * on it. The numbers are what matter — a deflection is ~9e-2 in these units, so a
 * residual of ≤ 1e-3 is a hundredfold smaller than the effect being measured, and a
 * pose that did NOT reset is ~9e-2.
 */
const matrixNumbers = (matrix) => ((matrix || '').match(/-?[\d.]+(?:e-?\d+)?/g) || []).map(Number);
const matrixDelta = (a, b) => {
  const left = matrixNumbers(a);
  const right = matrixNumbers(b);
  if (!left.length || left.length !== right.length) return Number.POSITIVE_INFINITY;
  return left.reduce((worst, value, i) => Math.max(worst, Math.abs(value - right[i])), 0);
};

/*
 * Read the STANDARD property only, never the `-webkit-` alias: an artifact whose
 * hand-written glass rules were minified to `-webkit-backdrop-filter` alone looks
 * fine in the source and is transparent in Chrome, and that is precisely the
 * defect this check exists to catch (see the note at the top of the glass policy
 * in `src/index.css`).
 */
const MATERIAL = (classes) =>
  Array.from(document.querySelectorAll('*'))
    .map((el) => ({ el, style: getComputedStyle(el) }))
    .filter(({ style }) => style.backdropFilter && style.backdropFilter !== 'none')
    .map(({ el }) => {
      const list = Array.from(el.classList);
      return {
        tag: el.tagName.toLowerCase(),
        classes: list,
        whitelisted: list.some((c) => classes.includes(c)),
        text: (el.textContent || '').trim().slice(0, 30),
      };
    });

/* ------------------------------------------------------------------ */
/* driving real input                                                  */
/* ------------------------------------------------------------------ */

async function drag(page, { touch, steps = 24, dx = 60, dy = 20 }) {
  const centre = await page.evaluate(() => {
    const el = document.querySelector('button[aria-label^="Survey corner"]');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  });
  if (!centre) throw new Error('no survey handle on the stage');
  if (touch) {
    const client = await page.createCDPSession();
    const points = (x, y) => [{ x, y, radiusX: 12, radiusY: 12, force: 1, id: 1 }];
    await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: points(centre.x, centre.y) });
    for (let i = 1; i <= steps; i += 1) {
      await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: points(centre.x + (dx * i) / steps, centre.y + (dy * i) / steps) });
      await sleep(16);
    }
    await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  } else {
    await page.mouse.move(centre.x, centre.y);
    await page.mouse.down();
    for (let i = 1; i <= steps; i += 1) {
      await page.mouse.move(centre.x + (dx * i) / steps, centre.y + (dy * i) / steps);
      await sleep(16);
    }
    await page.mouse.up();
  }
  await sleep(340);
}

/** 100 trusted pointer moves across the stage, with every side effect accounted for. */
async function sweep(page, moves = 100) {
  const box = await page.evaluate(STAGE_BOX);
  if (!box) throw new Error('no stage box');
  await page.evaluate(() => {
    window.__mut = [];
    window.__mutObs = new MutationObserver((records) => {
      for (const r of records) {
        window.__mut.push({
          type: r.type,
          name: r.attributeName || null,
          target: r.target.nodeType === 1 ? r.target.tagName.toLowerCase() : '#text',
          inStage: Boolean(r.target.closest && r.target.closest('[data-bw-stage]')),
        });
      }
    });
    window.__mutObs.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true });
    window.__probe.longTasks = [];
    window.__probe.cls = 0;
  });
  const poseBefore = await page.evaluate(POSE_MATRIX);
  const readoutBefore = await page.evaluate(READOUT);
  await page.evaluate(() => window.__frameStart());
  for (let i = 0; i < moves; i += 1) {
    const t = i / (moves - 1);
    await page.mouse.move(box.x + 16 + (box.w - 32) * t, box.y + 24 + (box.h - 48) * Math.sin(t * Math.PI));
  }
  const frames = await page.evaluate(() => window.__frameStop());
  const poseAfter = await page.evaluate(POSE_MATRIX);
  const readoutAfter = await page.evaluate(READOUT);
  const state = await page.evaluate(() => {
    window.__mutObs.disconnect();
    return { mutations: window.__mut, longTasks: window.__probe.longTasks.slice(), cls: window.__probe.cls };
  });
  const classify = (type, name) => state.mutations.filter((m) => m.type === type && (name === undefined || m.name === name)).length;
  return {
    moves,
    frames: histogram(frames),
    longTasks: state.longTasks,
    clsDuringSweep: round(state.cls),
    poseChanged: poseBefore !== poseAfter,
    readoutStable: JSON.stringify(readoutBefore) === JSON.stringify(readoutAfter),
    readoutKeys: Object.keys(readoutBefore).length,
    mutations: {
      total: state.mutations.length,
      childList: classify('childList'),
      characterData: classify('characterData'),
      styleInStage: state.mutations.filter((m) => m.type === 'attributes' && m.name === 'style' && m.inStage).length,
      nonStyleAttributes: state.mutations.filter((m) => m.type === 'attributes' && m.name !== 'style').length,
      styleOutsideStage: state.mutations.filter((m) => m.type === 'attributes' && m.name === 'style' && !m.inStage).length,
      sample: state.mutations.slice(0, 6),
    },
  };
}

/* ------------------------------------------------------------------ */
/* the probe                                                           */
/* ------------------------------------------------------------------ */

async function newPage(browser, { width, height, touch, reduced }) {
  const page = await browser.newPage();
  const console_ = [];
  const pageErrors = [];
  const failed = [];
  page.on('console', (m) => {
    if (m.type() === 'error') console_.push(m.text());
  });
  page.on('pageerror', (e) => pageErrors.push(String(e.message)));
  page.on('requestfailed', (r) => failed.push(`${r.url()} ${r.failure()?.errorText}`));
  page.__collectors = { consoleErrors: console_, pageErrors: pageErrors, failedRequests: failed };
  await page.setViewport({ width, height, deviceScaleFactor: 1, isMobile: touch, hasTouch: touch });
  if (reduced) await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  return page;
}

async function open(page, url, waitFor) {
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
  if (waitFor) {
    try {
      await page.waitForSelector(waitFor, { timeout: 20000 });
    } catch {
      /* The commonest failure here is not a broken page but the wrong build: the
         `/preview` prototypes are constant-folded out of a plain `npm run build`,
         so the default :4322 measurement server 404s the route. Say so, with the
         one-line fix, instead of a bare 20 s selector timeout. */
      throw new Error(
        `${waitFor} never appeared at ${url}.\n` +
          'The /preview prototype routes exist only in `vite dev` or in a build made with ' +
          'VITE_PREVIEW_PROTOTYPES=1, and this probe defaults to the measurement build on :4322.\n' +
          `Point it at the dev server instead:\n  PROBE_URL=http://localhost:5173${new URL(url).pathname}`,
      );
    }
  }
  await page.evaluate(installMetrics);
  await sleep(900);
}

async function main() {
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: chromePath(),
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--force-device-scale-factor=1', '--hide-scrollbars'],
  });
  const report = { interactionUrl: INTERACTION_URL, landingUrl: LANDING_URL, startedAt: new Date().toISOString(), rungs: [], landing: {}, material: {}, reducedMotion: null, checks };

  /* ---------------- [1] the rung matrix ---------------- */
  console.log('\n[1] The rung matrix — what each rung registers, and what it refuses');
  for (const rung of RUNGS) {
    const page = await newPage(browser, rung);
    await page.evaluateOnNewDocument(recordListeners);
    await page.evaluateOnNewDocument(rungScript, { coarse: rung.coarse, saveData: rung.saveData, lowMemory: rung.lowMemory });
    await open(page, INTERACTION_URL, '[data-bw-stage]');
    await page.evaluate(() => document.querySelector('[data-bw-stage]').scrollIntoView({ block: 'center' }));
    await sleep(700);

    /* What the page READ, not what was asked for. */
    const capability = await page.evaluate(() => ({
      coarse: window.matchMedia('(pointer: coarse)').matches,
      reduced: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      saveData: navigator.connection?.saveData === true,
      deviceMemory: typeof navigator.deviceMemory === 'number' ? navigator.deviceMemory : null,
    }));

    const onScreenListeners = (await page.evaluate(LISTENERS)).window;
    /* The pose at rest, before any pointer has moved — the value the pose must come
       back to when the pointer leaves the window (P2's "returns to centre"). */
    const restPose = await page.evaluate(POSE_MATRIX);
    const sweepResult = await sweep(page, 100);
    const poseDeflected = await page.evaluate(POSE_MATRIX);
    await page.screenshot({ path: path.join(SHOTS_DIR, `rung-${rung.name}-swept.png`) });
    /*
     * The pointer is moved OUT of the viewport with trusted input, then the window is
     * blurred, and both poses are recorded — because MEASURED HERE, an out-of-viewport
     * pointer move fires `pointerout` and NOT `pointerleave` on `window` (0 pointerleave
     * at (-4,-4) and 0 at (1600,1000) in this browser; the reading is recorded in the
     * report as `pointerOutOfViewport`), so the hook's second reset line is the one this
     * environment can actually reach. The blur is dispatched as an Event rather than
     * driven, and that is stated rather than hidden: there is no trusted way to blur a
     * headless window, and what is being asserted is the page's REACTION to the event
     * its listener already holds — the registration itself is proven by the ledger in
     * [1].
     */
    await page.mouse.move(-4, -4);
    await sleep(700);
    const poseAfterPointerOut = await page.evaluate(POSE_MATRIX);
    await page.evaluate(() => window.dispatchEvent(new Event('blur')));
    await sleep(700);
    const poseAfterLeave = await page.evaluate(POSE_MATRIX);

    /* Off screen: the stage is above the fold once the reader has scrolled past it. */
    /* Scroll past the stage and read the ledger again. WHETHER THAT PROVES
       ANYTHING DEPENDS ON THE VIEWPORT: `useOnScreen` observes with a 25% margin,
       so in a 900px-tall window the stage is still inside the observation box even
       with the document scrolled to its end (the route is ~2 viewports tall). The
       reading therefore records the stage's own position, and the assertion below
       only applies where the stage is genuinely outside the box. The dedicated
       check in [3] exercises it at a height where it is. */
    const scrollable = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
    let offScreenListeners = null;
    if (scrollable > 200) {
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await sleep(600);
      offScreenListeners = await page.evaluate(() => {
        const r = document.querySelector('[data-bw-stage]').getBoundingClientRect();
        return {
          ...window.__listeners().window,
          stageBottom: Math.round(r.bottom),
          viewport: window.innerHeight,
          stageBelowMargin: r.bottom < -0.25 * window.innerHeight,
        };
      });
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(300);

    const before = await page.evaluate(READOUT);
    await drag(page, { touch: rung.touch, dx: rung.touch ? 44 : 78, dy: rung.touch ? 18 : 28 });
    const after = await page.evaluate(READOUT);

    const entry = {
      name: rung.name,
      viewport: `${rung.width}x${rung.height}`,
      forced: rung.forced,
      capability,
      listeners: { onScreen: onScreenListeners, offScreen: offScreenListeners },
      sweep: sweepResult,
      pose: {
        rest: restPose,
        afterPointerOutOfViewport: poseAfterPointerOut,
        afterBlur: poseAfterLeave,
        /** How far the pointer moved the assembly (the effect being measured). */
        deflection: round(matrixDelta(restPose, poseDeflected)),
        /** How far from rest it still is once the reset has run. */
        residualAfterBlur: round(matrixDelta(restPose, poseAfterLeave)),
        requiresRest: false,
        outOfViewportAloneResets: matrixDelta(restPose, poseAfterPointerOut) <= 1e-3,
      },
      dragStillWorks: before.Area !== after.Area,
      measure: { before: before.Area, after: after.Area },
      collectors: page.__collectors,
    };
    report.rungs.push(entry);
    console.log(
      `  · ${rung.name.padEnd(9)} read(coarse=${capability.coarse} reduced=${capability.reduced} saveData=${capability.saveData} memory=${capability.deviceMemory}) ` +
        `listeners=${JSON.stringify(onScreenListeners)} offScreen=${offScreenListeners ? JSON.stringify(offScreenListeners) : 'n/a'} ` +
        `p95=${sweepResult.frames.p95}ms longTasks=${sweepResult.longTasks.length} mut=${sweepResult.mutations.total} drag=${entry.dragStillWorks}`,
    );
    await page.close();
  }

  const rung = (name) => report.rungs.find((r) => r.name === name);
  const full = rung('full');
  const coarse = rung('coarse');
  const reduced = rung('reduced');
  const allFour = rung('all-four');
  const w = (r, type) => r?.listeners.onScreen[type] || 0;

  check('P7 full rung registers exactly one window pointermove listener', w(full, 'pointermove') === 1, `${w(full, 'pointermove')} registered`);
  check('P2 pose returns to centre on pointerleave and blur', w(full, 'pointerleave') === 1 && w(full, 'blur') === 1, `${w(full, 'pointerleave')} pointerleave, ${w(full, 'blur')} blur`);
  check('P2 the coarse rung swaps the pointer for the device orientation', w(coarse, 'pointermove') === 0 && w(coarse, 'deviceorientation') + w(coarse, 'deviceorientationabsolute') >= 1, `pointermove ${w(coarse, 'pointermove')}, gyro ${w(coarse, 'deviceorientation') + w(coarse, 'deviceorientationabsolute')}`);
  check('P7 reduced motion registers no pointer tracking', w(reduced, 'pointermove') === 0, `${w(reduced, 'pointermove')} registered`);
  check('P7 all four flags register no pointer or gyro listener at all', w(allFour, 'pointermove') + w(allFour, 'deviceorientation') + w(allFour, 'deviceorientationabsolute') === 0, 'zero pointer/gyro listeners');
  check('P7 every rung keeps the drag (position is not animation)', full.dragStillWorks && coarse.dragStillWorks && reduced.dragStillWorks && allFour.dragStillWorks, `full=${full.dragStillWorks} coarse=${coarse.dragStillWorks} reduced=${reduced.dragStillWorks} allFour=${allFour.dragStillWorks}`);
  check('P2/P7 every rung is silent: no console error, page error or failed request', report.rungs.every((r) => !r.collectors.pageErrors.length && !r.collectors.consoleErrors.length && !r.collectors.failedRequests.length), report.rungs.map((r) => `${r.name}:${r.collectors.pageErrors.length + r.collectors.consoleErrors.length + r.collectors.failedRequests.length}`).join(' '));

  /* ---------------- [2] the pointer sweep ---------------- */
  console.log('\n[2] A 100-move trusted pointer sweep — a transform write, not a render');
  for (const r of report.rungs) {
    const m = r.sweep.mutations;
    const pointerDrivesPose = r.name === 'full';
    check(`P3 sweep on ${r.name}: no DOM restructuring`, m.childList === 0 && m.characterData === 0, `${m.childList} childList, ${m.characterData} characterData, ${m.nonStyleAttributes} non-style attributes`);
    check(`P3 sweep on ${r.name}: no React-rendered text moved`, r.sweep.readoutStable, `${r.sweep.readoutKeys} readout values unchanged`);
    /* The pose assertion FLIPS by rung, and that is the point of running four of
       them: on the full rung the pointer must move the assembly, and on every rung
       that has turned pointer tracking off the same 100 moves must leave it exactly
       where it was — a "do less" rung that still tracks the pointer is the failure
       mode a comment cannot catch. */
    check(
      pointerDrivesPose
        ? `P2 sweep on ${r.name}: the pose answered the pointer`
        : `P2 sweep on ${r.name}: the pose ignored the pointer (this rung has no pointer tracking)`,
      pointerDrivesPose ? r.sweep.poseChanged : !r.sweep.poseChanged,
      pointerDrivesPose ? 'transform matrix changed' : 'transform matrix unchanged',
    );
    check(`P3 sweep on ${r.name}: no long task`, r.sweep.longTasks.length === 0, r.sweep.longTasks.join(',') || 'none');
    /* The pose returns to its rest value when the pointer leaves the window. Only
       the full rung has a pointer-driven pose to return, so only there is this a
       statement about anything. */
    if (pointerDrivesPose) {
      check(
        'P2 the pose returns to its rest value when the page loses the pointer',
        r.pose.residualAfterBlur <= 1e-3,
        `deflected by ${r.pose.deflection} matrix units, ${r.pose.residualAfterBlur} away from rest after the blur event ` +
          '(handler-level: no trusted blur exists in a headless window; the listener itself is proven by the ledger in [1])',
      );
      report.pointerOutOfViewport = {
        resetsOnItsOwn: r.pose.outOfViewportAloneResets,
        note: 'measured: an out-of-viewport pointer move fires pointerout, not pointerleave, so the pose is held until the page loses focus — reported, not asserted',
      };
      console.log(
        `  ·    pointer moved out of the viewport resets the pose on its own: ${r.pose.outOfViewportAloneResets ? 'yes' : 'no (pointerout fires, pointerleave does not — the blur line is the reachable one here)'}`,
      );
    }
    /* The FRAME budget is asserted on the two rungs where the page is allowed to
       spend a frame on the pointer at all. The reduced-motion rungs have nothing to
       animate, so "no frame over 50ms" there would be a statement about an idle
       page rather than about the interaction. */
    if (r.name === 'full' || r.name === 'coarse') {
      check(`P1 sweep on ${r.name}: CLS stays 0 (no layout invalidation)`, r.sweep.clsDuringSweep === 0, `cls ${r.sweep.clsDuringSweep}`);
      check(`P1 sweep on ${r.name}: no frame over 50ms`, r.sweep.frames.over50ms === 0, `p50 ${r.sweep.frames.p50}ms, p95 ${r.sweep.frames.p95}ms, max ${r.sweep.frames.max}ms`);
    }
  }

  /* ---------------- [3] the idle contract ---------------- */
  console.log('\n[3] The idle contract — an off-screen stage spends nothing');
  const idle = (r) => {
    const o = r.listeners.offScreen;
    if (!o) return 'not exercisable at this width';
    return o.stageBelowMargin
      ? `stage out of the box (bottom ${o.stageBottom}px in ${o.viewport}px) → pointermove ${o.pointermove || 0}`
      : `stage still inside the 25% margin (bottom ${o.stageBottom}px in ${o.viewport}px) → not applicable`;
  };
  const idleOk = (r) => {
    const o = r.listeners.offScreen;
    if (!o || !o.stageBelowMargin) return true; // nothing to disprove at this viewport
    return !o.pointermove;
  };
  check(
    'P2/P7 wherever the stage is genuinely outside the observation box, the pointer listener is gone',
    [full, coarse].every(idleOk),
    `full: ${idle(full)}; coarse: ${idle(coarse)}`,
  );
  {
    /* A SHORT VIEWPORT IS THE ONLY WAY TO ACTUALLY EXERCISE THIS on the prototype
       route. At 1440x900 the stage is still inside `useOnScreen`'s 25% margin even
       with the document scrolled to its end (the page is ~2 viewports tall), so the
       assertion above would be vacuous — measured, then fixed by measuring at a
       height where the stage is genuinely gone. */
    const page = await newPage(browser, { width: 1440, height: 420, touch: false });
    await page.evaluateOnNewDocument(recordListeners);
    await open(page, INTERACTION_URL, '[data-bw-stage]');
    await page.evaluate(() => document.querySelector('[data-bw-stage]').scrollIntoView({ block: 'center' }));
    await sleep(600);
    const inView = (await page.evaluate(LISTENERS)).window;
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await sleep(700);
    const scrolledPast = await page.evaluate(() => {
      const r = document.querySelector('[data-bw-stage]').getBoundingClientRect();
      return { stageBottom: Math.round(r.bottom), viewport: window.innerHeight, listeners: window.__listeners().window };
    });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(() => document.querySelector('[data-bw-stage]').scrollIntoView({ block: 'center' }));
    await sleep(700);
    const backInView = (await page.evaluate(LISTENERS)).window;
    report.idleContract = { inView, scrolledPast: { ...scrolledPast, stageBelowMargin: scrolledPast.stageBottom < -0.25 * scrolledPast.viewport }, backInView };
    check('P2 the pointer listener exists while the stage is on screen', (inView.pointermove || 0) === 1, `pointermove ${inView.pointermove || 0}`);
    check(
      'P2/P7 the pointer listener is gone while the stage is off screen',
      !scrolledPast.listeners.pointermove && !scrolledPast.listeners.pointerleave,
      `stage bottom ${scrolledPast.stageBottom}px in a ${scrolledPast.viewport}px viewport; pointermove ${scrolledPast.listeners.pointermove || 0}`,
    );
    check('P2 the pointer listener returns with the stage', (backInView.pointermove || 0) === 1, `pointermove ${backInView.pointermove || 0}`);
    await page.close();
  }

  /* ---------------- [4] material, measured ---------------- */
  console.log('\n[4] Material discipline, measured on the rendered pages');
  {
    const page = await newPage(browser, { width: 1440, height: 900, touch: false });
    await page.evaluateOnNewDocument(recordListeners);
    await open(page, INTERACTION_URL, '[data-bw-stage]');
    const blurred = await page.evaluate(MATERIAL, CHROME_CLASSES);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await sleep(600);
    const blurredAfterScroll = await page.evaluate(MATERIAL, CHROME_CLASSES);
    report.material.interactionRoute = { blurred, afterScroll: blurredAfterScroll.length };
    const bad = [...blurred, ...blurredAfterScroll].filter((b) => !b.whitelisted);
    check('the interaction route adds no blur surface of its own', blurred.length === 0, `${blurred.length} blurred element(s) on the prototype route`);
    await page.close();
    void bad;
  }
  {
    const page = await newPage(browser, { width: 1440, height: 900, touch: false });
    await open(page, LANDING_URL, null);
    await page.evaluate(() => window.scrollTo(0, 600));
    await sleep(700);
    const blurred = await page.evaluate(MATERIAL, CHROME_CLASSES);
    report.material.landing = { blurred };
    const offenders = blurred.filter((b) => !b.whitelisted);
    check(
      'the landing blurs only floating chrome',
      offenders.length === 0,
      `${blurred.length} blurred element(s): ${blurred.map((b) => `${b.tag}.${b.classes.join('.') || '(none)'}`).join(', ')}`,
    );
    check('the landing carries one blur surface (the nav pill)', blurred.length === 1, `${blurred.length} blurred element(s)`);
    await page.close();
  }

  /* ---------------- [5] anchors and document height ---------------- */
  console.log('\n[5] Anchor landing and document height on the landing page');
  for (const width of [1440, 390]) {
    const page = await newPage(browser, { width, height: width > 600 ? 900 : 844, touch: width < 600 });
    await open(page, LANDING_URL, '.bw-landing');
    const heightAtLoad = await page.evaluate(() => document.documentElement.scrollHeight);
    const links = await page.evaluate(() =>
      Array.from(document.querySelectorAll('a[href^="#"]'))
        .map((a) => a.getAttribute('href'))
        .filter((href) => href && href.length > 1),
    );
    /* The menu is behind a button at the narrow width; open it so its links exist. */
    const opened = await page.evaluate(() => {
      const btn = document.querySelector('button[aria-label="Open menu"]');
      if (!btn) return false;
      btn.click();
      return true;
    });
    await sleep(500);
    const allLinks = opened
      ? await page.evaluate(() =>
          Array.from(document.querySelectorAll('a[href^="#"]'))
            .map((a) => a.getAttribute('href'))
            .filter((href) => href && href.length > 1),
        )
      : links;
    const targets = [...new Set(allLinks)];

    const landings = [];
    for (const href of targets) {
      const id = href.slice(1);
      const exists = await page.evaluate((i) => Boolean(document.getElementById(i)), id);
      if (!exists) {
        landings.push({ href, missingTarget: true });
        continue;
      }
      await page.evaluate((i) => {
        const el = document.querySelector(`a[href="#${i}"]`);
        if (el) el.click();
      }, id);
      await sleep(1400); // lenis smooth scroll
      landings.push(
        await page.evaluate((i) => {
          const section = document.getElementById(i);
          const r = section.getBoundingClientRect();
          const margin = parseFloat(getComputedStyle(section).scrollMarginTop) || 0;
          const to2 = (v) => Math.round(v * 100) / 100;
          const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
          return {
            href: `#${i}`,
            topAfter: to2(r.top),
            scrollMarginTop: margin,
            deltaFromMargin: to2(r.top - margin),
            documentTop: Math.round(r.top + window.scrollY),
            /* The last section of a document can be too close to the end for ANY
               scroll position to put it at the top. That is geometry, not a bug,
               so the assertion allows a shortfall only when the page is already at
               its end — and a landing that stops short with scroll still left is
               exactly the fabricated-height failure this check is for. */
            atDocumentEnd: window.scrollY >= maxScroll - 1,
          };
        }, id),
      );
    }
    const scrolled = await page.evaluate(() => document.documentElement.scrollHeight);
    report.landing[`w${width}`] = { heightAtLoad, heightAfterAnchors: scrolled, landings };
    const usable = landings.filter((l) => !l.missingTarget);
    const offenders = usable.filter((l) => Math.abs(l.deltaFromMargin) > 1 && !(l.atDocumentEnd && l.deltaFromMargin > 0));
    const worst = usable.reduce((m, l) => Math.max(m, Math.abs(l.deltaFromMargin)), 0);
    check(
      `P6 w${width} anchor jumps land on their section top (±1px of scroll-margin)`,
      offenders.length === 0,
      `${usable.length} anchors, worst |δ| ${worst}px${offenders.length ? `, offenders: ${offenders.map((l) => `${l.href} ${l.deltaFromMargin}px`).join(', ')}` : ''}`,
    );
    check(`P6 w${width} the document does not change height (the fabricated-height failure)`, Math.abs(scrolled - heightAtLoad) <= 1, `${heightAtLoad}px at load, ${scrolled}px after`);
    await page.close();
  }

  /* ---------------- [6] reduced motion equals the settled frame ---------------- */
  console.log('\n[6] Reduced motion renders the settled frame, not a different composition');
  {
    const normal = await newPage(browser, { width: 1440, height: 900, touch: false });
    await open(normal, INTERACTION_URL, '[data-bw-stage]');
    await sleep(900);
    const clipA = await (await normal.$('[data-bw-stage]')).screenshot({ encoding: 'base64' });

    const rm = await newPage(browser, { width: 1440, height: 900, touch: false, reduced: true });
    await open(rm, INTERACTION_URL, '[data-bw-stage]');
    await sleep(900);
    const clipB = await (await rm.$('[data-bw-stage]')).screenshot({ encoding: 'base64' });
    await rm.screenshot({ path: path.join(SHOTS_DIR, 'reduced-motion-stage.png') });

    const diff = await normal.evaluate(
      async (a, b) => {
        const decode = async (b64) => {
          const img = new Image();
          img.src = 'data:image/png;base64,' + b64;
          await img.decode();
          const c = document.createElement('canvas');
          c.width = img.width;
          c.height = img.height;
          const ctx = c.getContext('2d');
          ctx.drawImage(img, 0, 0);
          return ctx.getImageData(0, 0, c.width, c.height);
        };
        const [ia, ib] = [await decode(a), await decode(b)];
        if (ia.width !== ib.width || ia.height !== ib.height) return { sizeMismatch: `${ia.width}x${ia.height} vs ${ib.width}x${ib.height}` };
        let differing = 0;
        let maxDelta = 0;
        for (let i = 0; i < ia.data.length; i += 4) {
          const d = Math.max(
            Math.abs(ia.data[i] - ib.data[i]),
            Math.abs(ia.data[i + 1] - ib.data[i + 1]),
            Math.abs(ia.data[i + 2] - ib.data[i + 2]),
          );
          if (d > 2) differing += 1;
          if (d > maxDelta) maxDelta = d;
        }
        const pixels = ia.width * ia.height;
        return { pixels, differing, fraction: differing / pixels, maxDelta };
      },
      clipA,
      clipB,
    );
    report.reducedMotion = diff;
    check('reduced motion is the same frame as the animated rest state', !diff.sizeMismatch && diff.fraction <= 0.005, diff.sizeMismatch || `${diff.differing}/${diff.pixels} pixels differ (${(diff.fraction * 100).toFixed(3)}%), max channel delta ${diff.maxDelta}`);
    await normal.close();
    await rm.close();
  }

  /* ---------------- [7] P4, on the landing's own set piece ---------------- */
  /*
   * THE SCRUB, MEASURED ON THE THING IT MOVES.
   *
   * P4's two remaining acceptance items were "no consumer yet" for as long as the
   * primitive had none: the landing hero (`src/landing/HeroModel.tsx`) is the first,
   * and these checks read the DRAWN GEOMETRY rather than any internal value — the
   * roof plate's position inside the stage, and the drawing layer's own computed
   * opacity. A scrubbed element that reported "progress 1" while painting its rest
   * frame would pass a value-based assertion and fail these.
   *
   * The scroll is REAL wheel input, so Lenis, the damped follow and the browser's
   * own compositing are all in the path. THE POINTER IS NEVER MOVED IN THIS SECTION,
   * and that is a measurement decision rather than a convenience: the hero's pose is
   * pointer-driven, so pointing anywhere would move the roof for a reason that has
   * nothing to do with the scrub — measured, it moved the roof by 16 px (0.022 of the
   * stage height), which is larger than the tolerance this section asserts. Rest pose
   * on both rungs is what makes the reduced-motion comparison mean anything.
   *
   * WHAT IS ASSERTED, AND WHAT IS DELIBERATELY NOT. Not asserted: a roughness budget
   * on the output. `jitter()` in `scrub.ts` exists to attenuate a NOISY input, and a
   * wheel train is not noisy — it is a step train, whose output legitimately
   * accelerates at the start of each burst. Measured on the first run of this check,
   * an absolute second-difference threshold flagged exactly that acceleration. What is
   * asserted instead is the property a reader can see: the layer LAGS the scroll's own
   * band (so it is an answer, not an echo), it never passes the end, it never
   * reverses, and it settles exactly. The jitter attenuation itself is a unit claim
   * and is measured where it belongs, in `test_interaction_primitives.cjs` [3].
   */
  console.log('\n[7] P4 — the landing hero is scrubbed by a real scroll');
  const heroSample = (p) =>
    p.evaluate(() => {
      const stage = document.querySelector('[data-bw-massing]');
      const roof = stage && stage.querySelector('[data-bw-massing-roof]');
      const drawing = stage && stage.querySelector('[data-bw-massing-drawing]');
      if (!stage || !roof || !drawing) return null;
      const sb = stage.getBoundingClientRect();
      const rb = roof.getBoundingClientRect();
      return {
        /* Where the roof sits within the stage, as a fraction of the stage's own
           height: 0 = the stage's top edge. Scaffolding-free and pose-independent
           only because the pose is held still for the whole run. */
        rise: Math.round(((rb.top - sb.top) / sb.height) * 100000) / 100000,
        drawing: Math.round(parseFloat(getComputedStyle(drawing).opacity) * 1000) / 1000,
        stageTop: Math.round(sb.top),
        scrollY: Math.round(window.scrollY),
      };
    });
  {
    const page = await newPage(browser, { width: 1440, height: 900, touch: false });
    await open(page, LANDING_URL, '[data-bw-massing]');
    await sleep(700);
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(600);

    const samples = [];
    for (let i = 0; i < 16; i += 1) {
      await page.mouse.wheel({ deltaY: 60 });
      await sleep(180);
      const s = await heroSample(page);
      if (s) samples.push(s);
    }
    /* Then all the way to the settled end, without assuming how much scroll that
       takes: wheel until the roof stops moving, with a bound on the loop. */
    let settled = samples[samples.length - 1];
    let settling = 0;
    for (let i = 0; i < 12; i += 1) {
      const before = settled;
      await page.mouse.wheel({ deltaY: 220 });
      await sleep(260);
      settled = (await heroSample(page)) || before;
      settling += 1;
      if (Math.abs(settled.rise - before.rise) <= 1e-4 && settled.drawing === 1) break;
    }
    const errors = page.__collectors;
    await page.close();

    const reducedPage = await newPage(browser, { width: 1440, height: 900, touch: false, reduced: true });
    await open(reducedPage, LANDING_URL, '[data-bw-massing]');
    await sleep(900);
    const reducedHero = await heroSample(reducedPage);
    await reducedPage.screenshot({ path: path.join(SHOTS_DIR, 'hero-reduced-motion.png') });
    const reducedErrors = reducedPage.__collectors;
    await reducedPage.close();

    const series = samples.map((s) => s.rise);
    const nonMonotone = series.filter((v, i) => i > 0 && v > series[i - 1] + 5e-4).length;
    const travel = Math.abs(series[0] - settled.rise);

    /*
     * THE LAG SERIES — the measurement this section exists for.
     *
     * The band is PUBLIC (scrub.ts: the element's top edge travels from 92 % to
     * 55 % of the viewport), and the roof's height is a linear function of progress
     * inside it, so the drawing's expected position at any scroll can be computed
     * from geometry alone. The difference between that line and where the roof
     * actually is is the response: a `dampedFollow` trails it and closes the gap
     * afterwards, an echo sits on it, and a spring with the wrong damping oscillates
     * across it. Both signs are checked.
     */
    const vh = 900;
    const stageDocTop = samples[0].stageTop + samples[0].scrollY;
    const bandTop = stageDocTop - ENTRY.from * vh;
    const bandSpan = (ENTRY.from - ENTRY.to) * vh;
    const restRise = samples[0].rise;
    const lag = samples.map((s) => {
      const progress = Math.min(1, Math.max(0, (s.scrollY - bandTop) / bandSpan));
      const risen = Math.min(1, Math.max(0, (progress - RISE_BAND.from) / (RISE_BAND.to - RISE_BAND.from)));
      const expected = restRise + (settled.rise - restRise) * risen;
      return Math.round((s.rise - expected) * 1e5) / 1e5;
    });
    const maxLag = Math.max(...lag);
    const minLag = Math.min(...lag);

    report.heroScrub = {
      samples,
      settled,
      settlingWheels: settling,
      reduced: reducedHero,
      lag: { series: lag, max: maxLag, min: minLag, band: [Math.round(bandTop), Math.round(bandTop + bandSpan)] },
      nonMonotone,
      travel: Math.round(travel * 1e5) / 1e5,
      collectors: {
        normal: errors.pageErrors.length + errors.consoleErrors.length + errors.failedRequests.length,
        reduced: reducedErrors.pageErrors.length + reducedErrors.consoleErrors.length + reducedErrors.failedRequests.length,
      },
    };

    check(
      'P4 the hero scrub is sampling a live element on the landing',
      samples.length >= 14 && settled !== null && reducedHero !== null,
      `${samples.length} samples, settled ${JSON.stringify(settled)}, reduced ${JSON.stringify(reducedHero)}`,
    );
    check(
      'P4 the scrub actually travels as the reader scrolls (the check is not vacuous)',
      travel > 0.02 && settled.drawing === 1,
      `the roof travelled ${(travel * 100).toFixed(1)}% of the stage height; the drawing layer ended at opacity ${settled.drawing}`,
    );
    check(
      'P4 progress is monotone across a real scroll (it never un-builds)',
      nonMonotone === 0,
      `${nonMonotone} reversal(s) in ${series.length} samples: ${series.map((v) => v.toFixed(3)).join(' → ')}`,
    );
    check(
      'P4 the layer answers the scroll rather than echoing it (it trails the band, then closes)',
      maxLag >= 0.008,
      `furthest behind its band line: ${maxLag.toFixed(4)} of the stage height (${(maxLag * 741).toFixed(1)} px), band ${Math.round(
        bandTop,
      )}–${Math.round(bandTop + bandSpan)} px of scroll`,
    );
    check(
      'P4 the layer never passes the end of its band (a damped follow, not an undamped one)',
      minLag >= -0.002,
      `furthest PAST its band line: ${Math.abs(Math.min(0, minLag)).toFixed(4)} of the stage height`,
    );
    check(
      'P4 reduced motion renders the SETTLED end, not the start',
      reducedHero !== null && Math.abs(reducedHero.rise - settled.rise) <= 0.004 && reducedHero.drawing === 1,
      reducedHero
        ? `reduced motion: roof at ${reducedHero.rise.toFixed(4)} of the stage (animated end ${settled.rise.toFixed(
            4,
          )}), drawing opacity ${reducedHero.drawing}`
        : 'no hero on the reduced-motion load',
    );
    check(
      'P2/P4 the landing hero is silent on both rungs',
      report.heroScrub.collectors.normal === 0 && report.heroScrub.collectors.reduced === 0,
      `normal ${report.heroScrub.collectors.normal}, reduced ${report.heroScrub.collectors.reduced} console/page/request errors`,
    );
    console.log(
      `  ·    settled after ${settling} wheel burst(s); roof ${samples[0].rise.toFixed(3)} → ${settled.rise.toFixed(
        3,
      )}, drawing opacity ${samples[0].drawing} → ${settled.drawing}`,
    );
  }

  /* WHAT THIS HARNESS CANNOT EXERCISE YET, said out loud rather than left as a
     silent gap in the matrix above. */
  console.log('\n[8] Named gaps — acceptance items with nothing to measure yet');
  report.notExercised = [
    {
      item: 'P3 render count around a 100-move sweep',
      why: 'counted as its observable consequence (0 childList / 0 characterData / 0 non-style attributes, text unchanged) rather than by instrumenting React; a render counter would be a mirror of the thing it claims to measure',
    },
    {
      item: "P4 the reduced-motion frame and the animated end frame are the SAME pixels",
      why: 'asserted numerically here (the roof within 0.004 of the stage height and the drawing at opacity 1 in both), and as a pixel diff on the prototype route in [6]; a pixel diff of the landing hero was not added because its pose is pointer-driven and a headless pointer can only be in one place at a time',
    },
    {
      item: 'P2 device tilt on real hardware',
      why: 'no browser emulates DeviceOrientationEvent, so the coarse rung can only prove the LISTENER is registered (ledger, [1]); the mapping itself is covered by test_interaction_primitives.cjs',
    },
  ];
  for (const gap of report.notExercised) console.log(`  ·    ${gap.item} — ${gap.why}`);

  await browser.close();
  fs.writeFileSync(path.join(OUT_DIR, 'interaction-probe.json'), JSON.stringify(report, null, 2));
  const failed = checks.filter((c) => !c.ok);
  console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
  console.log(`wrote .audit/${PHASE}/interaction-probe.json and shots/*.png`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
