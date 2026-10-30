#!/usr/bin/env node
/**
 * perf_blueprint_validation.cjs — measured blueprint mount, reveal and framing.
 * ============================================================================
 * Runs the production BlueprintViewer over real API solves in headless Chrome.
 * It records the machine and renderer it actually ran on, then measures:
 *
 *   - component mount, API solve, sheet injection and reveal as separate spans;
 *   - rAF deltas and dropped frames during the CSS reveal;
 *   - long tasks;
 *   - framing/zoom/room/fullscreen interaction latency;
 *   - JS heap before/after use.
 *
 * No FPS number is inferred from a video or from the authored CSS duration.
 * If the GPU is software-rendered, the report says so.
 *
 * Usage: node scripts/perf_blueprint_validation.cjs
 * Env:   E2E_URL (default http://127.0.0.1:5173/app), CHROME_PATH
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://127.0.0.1:5173/app';
const OUT = path.resolve(ROOT, '..', 'docs_ignore', 'qa-audit', 'assets-blueprint');
const CHROME = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean).find((p) => {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function installProbe(page) {
  await page.evaluateOnNewDocument(() => {
    const perf = {
      t0: 0,
      marks: {},
      frames: [],
      frameState: 'idle',
      frameStart: 0,
      frameEnd: 0,
      longTasks: [],
    };
    window.__bwPerf = perf;

    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.startTime >= (perf.t0 || 0)) {
            perf.longTasks.push({
              durationMs: Math.round(entry.duration),
              startMs: Math.round(entry.startTime - perf.t0),
            });
          }
        }
      }).observe({ entryTypes: ['longtask'] });
    } catch {
      /* no longtask support */
    }

    const mark = (name) => {
      if (perf.marks[name] === undefined) perf.marks[name] = performance.now();
    };
    const rootSvg = () => document.querySelector('[data-testid="blueprint-sheet-card"] svg');

    const startFrames = () => {
      if (perf.frameState === 'run' || perf.frameState === 'done') return;
      perf.frameState = 'run';
      perf.frameStart = performance.now();
      let prev = perf.frameStart;
      const tick = (now) => {
        perf.frames.push(now - prev);
        prev = now;
        const svg = rootSvg();
        const done = !svg || svg.getAttribute('data-bw-reveal') === 'done';
        if (done || now - perf.frameStart > 3000) {
          perf.frameState = 'done';
          perf.frameEnd = now;
          return;
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };

    const inspect = () => {
      if (!perf.t0) return;
      if (document.querySelector('[data-testid="blueprint-proof-loading"]')) mark('viewerLoading');
      if (document.querySelector('[data-testid="blueprint-proof"][data-phase="ready"]')) mark('apiReady');
      const svg = rootSvg();
      if (svg) {
        if (svg.getAttribute('data-bw-view')) mark('sheetInjected');
        const reveal = svg.getAttribute('data-bw-reveal');
        if (reveal === 'run') startFrames();
        if (reveal === 'done') mark('revealDone');
      }
      if (document.querySelector('[role="dialog"][aria-modal="true"] [data-testid="blueprint-sheet-modal"] svg')) {
        mark('modalSheet');
      }
    };

    const observer = new MutationObserver(inspect);
    observer.observe(document, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['data-bw-view', 'data-bw-reveal', 'aria-busy', 'data-phase'],
    });
    perf.observerReady = true;
    document.addEventListener('DOMContentLoaded', inspect, { once: true });
  });
}

function pct(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return Number(sorted[idx].toFixed(2));
}

function frameStats(frames) {
  if (!frames.length) return { count: 0, p50: null, p95: null, max: null, over20: 0, over50: 0, dropped: 0, fps: null };
  const over20 = frames.filter((dt) => dt > 20).length;
  const over50 = frames.filter((dt) => dt > 50).length;
  const duration = frames.reduce((a, b) => a + b, 0);
  return {
    count: frames.length,
    p50: pct(frames, 50),
    p95: pct(frames, 95),
    max: Number(Math.max(...frames).toFixed(2)),
    over20,
    over50,
    // A frame is dropped when its interval exceeds one 60 Hz slot plus 50%.
    dropped: frames.filter((dt) => dt > 25).length,
    fps: duration > 0 ? Number(((frames.length / duration) * 1000).toFixed(1)) : null,
  };
}

async function readTimeline(page) {
  return page.evaluate(() => {
    const perf = window.__bwPerf;
    const resource = performance
      .getEntriesByType('resource')
      .find((entry) => entry.name.includes('/api/generate-floorplan'));
    return {
      marks: { ...perf.marks },
      t0: perf.t0,
      frames: perf.frames.slice(),
      frameState: perf.frameState,
      frameStart: perf.frameStart,
      frameEnd: perf.frameEnd,
      longTasks: perf.longTasks.slice(),
      apiDurationMs: resource ? Number(resource.duration.toFixed(1)) : null,
      transferSize: resource ? resource.transferSize : null,
      revealAttrMs: Number(
        document.querySelector('[data-testid="blueprint-sheet-card"] svg')?.getAttribute('data-bw-reveal-ms') || 0
      ),
      viewBox: document.querySelector('[data-testid="blueprint-sheet-card"] svg')?.getAttribute('viewBox') || null,
      mode: document.querySelector('[data-testid="blueprint-sheet-card"] svg')?.getAttribute('data-bw-view') || null,
      fills: document.querySelectorAll('[data-testid="blueprint-sheet-card"] .bw-room-fill').length,
      floors: document.querySelectorAll('[data-testid^="tab-floor-"]').length,
    };
  });
}

async function measure(page, caseId) {
  await page.evaluate(async (id) => {
    window.__bwPerf.t0 = performance.now();
    const harness = await import('/scripts/harness/blueprintRevealMount.tsx');
    await harness.mountBlueprintReveal(id);
  }, caseId);
  await page.waitForSelector('[data-testid="blueprint-proof"][data-phase="ready"]', { timeout: 180000 });
  await page.waitForSelector('[data-testid="blueprint-sheet-card"] svg[data-bw-view]', { timeout: 30000 });
  try {
    await page.waitForFunction(
      () => {
        const perf = window.__bwPerf;
        const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
        const reveal = svg?.getAttribute('data-bw-reveal');
        return (
          perf.marks.revealDone !== undefined ||
          reveal === 'done' ||
          reveal === 'off' ||
          (svg && perf.frameState === 'done')
        );
      },
      { timeout: 20000 }
    );
  } catch (error) {
    console.error('timeline at timeout:', JSON.stringify(await readTimeline(page), null, 2));
    throw error;
  }
  await sleep(150);
  return readTimeline(page);
}

async function timeUntil(page, action, predicate, timeout = 3000) {
  return page.evaluate(
    ({ actionSource, predicateSource, timeout }) => {
      return new Promise((resolve) => {
        const started = performance.now();
        let done = false;
        const finish = (ok) => {
          if (done) return;
          done = true;
          requestAnimationFrame(() => {
            resolve({ ms: Number((performance.now() - started).toFixed(1)), ok });
          });
        };
        const check = new Function(`return (${predicateSource})`);
        const observer = new MutationObserver(() => {
          if (check()) {
            observer.disconnect();
            finish(true);
          }
        });
        observer.observe(document.documentElement, {
          subtree: true,
          childList: true,
          characterData: true,
          attributes: true,
          attributeFilter: ['data-bw-view', 'data-room-focus', 'aria-pressed', 'data-testid'],
        });
        try {
          new Function(actionSource)();
        } catch {
          observer.disconnect();
          resolve({ ms: -1, ok: false });
          return;
        }
        setTimeout(() => {
          observer.disconnect();
          finish(check());
        }, timeout);
      });
    },
    { actionSource: action, predicateSource: predicate, timeout }
  );
}

async function interactions(page) {
  const out = {};
  const modes = await timeUntil(
    page,
    "document.querySelector('[data-testid=\"view-mode-sheet\"]')?.click()",
    "document.querySelector('[data-testid=\"blueprint-sheet-card\"] svg')?.getAttribute('data-bw-view') === 'sheet'"
  );
  await sleep(80);
  out.modeSheetMs = modes;
  const back = await timeUntil(
    page,
    "document.querySelector('[data-testid=\"view-mode-plan\"]')?.click()",
    "document.querySelector('[data-testid=\"blueprint-sheet-card\"] svg')?.getAttribute('data-bw-view') === 'plan'"
  );
  await sleep(80);
  out.modePlanMs = back;

  const modeSamples = [];
  for (const id of ['sheet', 'width', 'plan']) {
    const t = await timeUntil(
      page,
      `document.querySelector('[data-testid="view-mode-${id}"]')?.click()`,
      `document.querySelector('[data-testid="blueprint-sheet-card"] svg')?.getAttribute('data-bw-view') === '${id}'`
    );
    modeSamples.push(t.ms);
    await sleep(60);
  }
  out.modeSamplesMs = modeSamples;
  out.modeMedianMs = pct(modeSamples, 50);

  const zoom = await timeUntil(
    page,
    "document.querySelector('[aria-label=\"Zoom In\"]')?.click()",
    "document.querySelector('[data-testid=\"blueprint-zoom-value\"]')?.textContent.trim() === '125%'"
  );
  out.zoomInMs = zoom;
  await page.evaluate(() => document.querySelector('[aria-label="Reset view to full sheet"]')?.click());
  await sleep(100);

  const chip = await page.$('[data-testid^="room-chip-"]');
  if (chip) {
    out.roomSelectMs = await timeUntil(
      page,
      "document.querySelector('[data-testid^=\"room-chip-\"]')?.click()",
      "document.querySelector('[data-testid=\"blueprint-sheet-card\"] svg')?.getAttribute('data-room-focus') === 'on'"
    );
    await page.evaluate(() => document.querySelector('[data-testid^="room-chip-"]')?.click());
    await sleep(80);
  }

  const expand = await page.$('[data-testid="blueprint-expand"]');
  if (expand) {
    out.fullscreenMs = await timeUntil(
      page,
      "document.querySelector('[data-testid=\"blueprint-expand\"]')?.click()",
      "Boolean(document.querySelector('[data-testid=\"blueprint-sheet-modal\"] svg[data-bw-view]'))",
      5000
    );
    await sleep(150);
    await page.keyboard.press('Escape');
    await sleep(120);
  }
  return out;
}

async function memory(page) {
  const cdp = await page.target().createCDPSession();
  await cdp.send('Performance.enable');
  try {
    await cdp.send('HeapProfiler.collectGarbage');
  } catch {
    /* best effort */
  }
  const metrics = await cdp.send('Performance.getMetrics');
  const map = Object.fromEntries(metrics.metrics.map((m) => [m.name, m.value]));
  return {
    jsHeapUsedMB: Number((map.JSHeapUsedSize / (1024 * 1024)).toFixed(2)),
    jsHeapTotalMB: Number((map.JSHeapTotalSize / (1024 * 1024)).toFixed(2)),
    nodes: map.Nodes ?? null,
    documents: map.Documents ?? null,
    jsEventListeners: map.JSEventListeners ?? null,
  };
}

async function main() {
  if (!CHROME) throw new Error('Chrome not found. Set CHROME_PATH.');
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--force-device-scale-factor=1',
      '--enable-precise-memory-info',
      '--js-flags=--expose-gc',
    ],
  });
  const version = await browser.version();
  const results = {
    startedAt: new Date().toISOString(),
    url: URL,
    browser: version,
    os: `${os.type()} ${os.release()} ${os.arch()}`,
    cpu: os.cpus().map((c) => c.model).filter((m, i, a) => a.indexOf(m) === i),
    logicalCores: os.cpus().length,
    totalMemoryGB: Number((os.totalmem() / 1024 ** 3).toFixed(1)),
    cases: {},
  };
  try {
    const meta = await browser.newPage();
    await meta.setViewport({ width: 1400, height: 950, deviceScaleFactor: 1 });
    await meta.goto(URL, { waitUntil: 'networkidle2' });
    results.renderer = await meta.evaluate(() => {
      const info = { userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency };
      info.deviceMemoryGB = navigator.deviceMemory ?? null;
      info.pixelRatio = window.devicePixelRatio;
      info.screen = `${screen.width}x${screen.height}`;
      try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        const ext = gl?.getExtension('WEBGL_debug_renderer_info');
        info.webglVendor = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null;
        info.webglRenderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
        info.webgl = Boolean(gl);
      } catch (error) {
        info.webgl = false;
      }
      return info;
    });
    await meta.close();

    for (const caseId of ['multi', 'dense', 'large']) {
      const page = await browser.newPage();
      await page.setViewport({ width: 1400, height: 950, deviceScaleFactor: 1 });
      await installProbe(page);
      await page.goto(URL, { waitUntil: 'networkidle2' });
      const before = await memory(page);
      const timeline = await measure(page, caseId);
      const after = await memory(page);
      const interaction = await interactions(page);
      const marks = timeline.marks;
      const t0 = timeline.t0;
      const spans = {
        componentMountMs: marks.viewerLoading !== undefined ? Number((marks.viewerLoading - t0).toFixed(1)) : null,
        apiSolveMs: timeline.apiDurationMs,
        apiReadyMs: marks.apiReady !== undefined ? Number((marks.apiReady - t0).toFixed(1)) : null,
        sheetInjectMs:
          marks.apiReady !== undefined && marks.sheetInjected !== undefined
            ? Number((marks.sheetInjected - marks.apiReady).toFixed(1))
            : null,
        revealWallClockMs:
          marks.sheetInjected !== undefined && marks.revealDone !== undefined
            ? Number((marks.revealDone - marks.sheetInjected).toFixed(1))
            : null,
        totalToFinishedSheetMs:
          marks.revealDone !== undefined ? Number((marks.revealDone - t0).toFixed(1)) : null,
      };
      const frames = frameStats(timeline.frames);
      const revealStart = timeline.frameStart ? timeline.frameStart - t0 : Infinity;
      const revealLongTasks = timeline.longTasks.filter((t) => t.startMs >= revealStart - 2);
      const mountLongTasks = timeline.longTasks.filter((t) => t.startMs < revealStart - 2);
      const longTasksMs = timeline.longTasks.map((t) => t.durationMs);
      results.cases[caseId] = {
        spans,
        frames,
        authoredRevealMs: timeline.revealAttrMs || null,
        longTasksMs,
        longTaskCount: longTasksMs.length,
        longTaskMaxMs: longTasksMs.length ? Math.max(...longTasksMs) : 0,
        longTasksDuringRevealMs: revealLongTasks.map((t) => t.durationMs),
        longTasksDuringMountMs: mountLongTasks.map((t) => t.durationMs),
        interaction,
        memoryBeforeMB: before,
        memoryAfterMB: after,
        floors: timeline.floors,
        fills: timeline.fills,
        finalMode: timeline.mode,
        finalViewBox: timeline.viewBox,
      };
      await page.screenshot({ path: path.join(OUT, `perf-${caseId}-finished.png`), fullPage: true });
      console.log(
        `[${caseId}] mount ${spans.componentMountMs} ms · api ${spans.apiSolveMs} ms · inject ${spans.sheetInjectMs} ms · ` +
          `reveal ${spans.revealWallClockMs} ms · frames ${frames.count} p50 ${frames.p50} p95 ${frames.p95} max ${frames.max} ` +
          `dropped ${frames.dropped} · heap ${before.jsHeapUsedMB}→${after.jsHeapUsedMB} MB`
      );
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(OUT, 'perf-blueprint-validation.json'), JSON.stringify(results, null, 2));
  console.log(`\nwrote ${path.join(OUT, 'perf-blueprint-validation.json')}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
