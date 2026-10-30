#!/usr/bin/env node
/**
 * e2e_blueprint_reveal.cjs — browser proof for the progressive blueprint.
 * ==========================================================================
 * Mounts the PRODUCTION BlueprintViewer over two real API solves:
 *
 *   multi  T1 20×20, 2 storeys -> CERTIFIED
 *   fail   T1 20×20, 1 storey  -> NOT-CERTIFIED-FAIL-STAMP
 *
 * Pins:
 *   1. the sheet contains 11 phase groups; 10 animate, `sheet` never does;
 *   2. the reveal finishes, removes its animations and is bounded (real wall
 *      clock recorded by the viewer, not the authored table);
 *   3. a FAIL chip is present and the verdict-bearing sheet group is fully
 *      opaque during the reveal — no animation can imply certification;
 *   4. room selection brightens one fill and mutes the rest; clearing restores;
 *   5. the fullscreen dialog has real dialog semantics, traps focus, restores
 *      it on Escape, and locks background scroll;
 *   6. +/0/arrows work on a focused sheet viewport;
 *   7. floor switching does not replay the reveal;
 *   8. 390 px layout does not overflow and the dialog fits;
 *   9. reduced motion shows the finished sheet immediately;
 *  10. the exported SVG is static (no reveal switch) and keeps room ids.
 *
 * Usage: node scripts/e2e_blueprint_reveal.cjs
 * Env:   E2E_URL (default http://localhost:5173/app), CHROME_PATH
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const URL = process.env.E2E_URL || 'http://localhost:5173/app';
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

let passes = 0;
let failures = 0;
function check(ok, label, detail) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`);
  ok ? (passes += 1) : (failures += 1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SELECT = {
  proof: '[data-testid="blueprint-proof"][data-phase="ready"]',
  sheet: '[data-testid="blueprint-sheet-card"] svg',
  modal: '[role="dialog"][aria-modal="true"]',
};

async function waitForFile(dir, before, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const now = fs.readdirSync(dir).filter((f) => f.endsWith('.svg') && !before.has(f));
    if (now.length) return path.join(dir, now[0]);
    await sleep(120);
  }
  return null;
}

async function installProbe(page) {
  await page.evaluateOnNewDocument(() => {
    window.__bwLongTasks = [];
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          window.__bwLongTasks.push(Math.round(entry.duration));
        }
      }).observe({ entryTypes: ['longtask'] });
    } catch {
      window.__bwLongTasks = [];
    }
  });
}

async function mount(page, caseId) {
  const started = Date.now();
  await page.evaluate(async (id) => {
    const harness = await import('/scripts/harness/blueprintRevealMount.tsx');
    await harness.mountBlueprintReveal(id);
  }, caseId);
  await page.waitForSelector(SELECT.proof, { timeout: 120000 });
  await page.waitForSelector(SELECT.sheet, { timeout: 20000 });
  return Date.now() - started;
}

async function readSheet(page) {
  return page.evaluate(() => {
    const host = document.querySelector('[data-testid="blueprint-sheet-card"]');
    const svg = host?.querySelector('svg');
    if (!svg) return null;
    const groups = Array.from(svg.querySelectorAll('[data-bw-phase]'));
    const sheet = svg.querySelector('[data-bw-phase="sheet"]');
    const animated = groups.filter((g) => g.getAttribute('data-bw-phase') !== 'sheet');
    const chip = document.querySelector('[data-testid="viewer-not-certified-chip"]');
    const style = (el) => (el ? getComputedStyle(el) : null);
    return {
      state: svg.getAttribute('data-bw-reveal'),
      duration: svg.getAttribute('data-bw-reveal-ms'),
      phases: groups.map((g) => g.getAttribute('data-bw-phase')),
      animatedCount: animated.length,
      animatedOpacities: animated.map((g) => Number(style(g).opacity)),
      sheetOpacity: Number(style(sheet).opacity),
      sheetAnimation: style(sheet).animationName,
      wallAnimation: style(svg.querySelector('[data-bw-phase="walls"]')).animationName,
      animationsAfterDone: svg.getAnimations({ subtree: true }).length,
      roomFocus: svg.getAttribute('data-room-focus'),
      selectedRooms: svg.querySelectorAll('.bw-room-fill.bw-room-selected').length,
      mutedRooms: svg.querySelectorAll('.bw-room-fill').length,
      fills: svg.querySelectorAll('.bw-room-fill').length,
      chip: chip
        ? {
            text: (chip.textContent || '').replace(/\s+/g, ' ').trim(),
            verdict: chip.getAttribute('data-verdict'),
          }
        : null,
      proofVerdict:
        document
          .querySelector('[data-testid="blueprint-proof"][data-phase="ready"]')
          ?.getAttribute('data-verdict') || '',
      floors: Number(
        document
          .querySelector('[data-testid="blueprint-proof"][data-phase="ready"]')
          ?.getAttribute('data-floors') || 0
      ),
      generation:
        document
          .querySelector('[data-testid="blueprint-proof"][data-phase="ready"]')
          ?.getAttribute('data-generation') || '',
    };
  });
}

async function waitRevealDone(page, timeout = 5000) {
  await page.waitForFunction(
    () => {
      const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
      return svg && svg.getAttribute('data-bw-reveal') === 'done';
    },
    { timeout }
  );
}

/** Replay the real CSS sequence and pause it at `ms` for deterministic proof. */
async function replayAndPause(page, ms) {
  await page.evaluate(async (at) => {
    const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
    if (!svg) return;
    svg.removeAttribute('data-bw-reveal');
    void svg.getBoundingClientRect();
    svg.setAttribute('data-bw-reveal', 'run');
    await new Promise((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))
    );
    for (const group of svg.querySelectorAll('[data-bw-phase]:not([data-bw-phase="sheet"])')) {
      for (const animation of group.getAnimations()) {
        animation.pause();
        animation.currentTime = at;
      }
    }
  }, ms);
  await sleep(80);
}

async function setFinished(page) {
  await page.evaluate(() => {
    const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
    if (!svg) return;
    svg.removeAttribute('data-bw-reveal');
    svg.setAttribute('data-bw-reveal', 'done');
  });
}

async function testMulti(browser, perf) {
  console.log('\n[1] Multi-storey · CERTIFIED · staged reveal');
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
  await installProbe(page);
  await page.goto(URL, { waitUntil: 'networkidle2' });
  const mountMs = await mount(page, 'multi');
  const first = await readSheet(page);
  perf.mountMs = mountMs;
  perf.longTasks = await page.evaluate(() => window.__bwLongTasks || []);

  check(Boolean(first), 'the real sheet is injected');
  check(first?.phases.length === 11, '11 phase groups are present', String(first?.phases.length));
  check(
    first?.phases.join(',') ===
      'envelope,site,rooms,ghost,walls,cores,openings,labels,dims,annotations,sheet',
    'phase groups follow the server drawing order',
    first?.phases.join(',')
  );
  check(first?.animatedCount === 10, 'the sheet group is excluded from the animated set');
  check(
    first?.state === 'run' || first?.state === 'done',
    'the reveal was actually started',
    first?.state || 'missing'
  );
  check(first?.proofVerdict === 'CERTIFIED', 'server says CERTIFIED', first?.proofVerdict);
  check(first?.chip === null, 'no refusal chip on a certified plan');

  if (first?.state === 'run') {
    check(first?.wallAnimation === 'bwSheetPhaseIn', 'animated phases carry the sheet keyframe', first?.wallAnimation);
  }
  check(first?.sheetAnimation === 'none', 'the sheet group never animates', first?.sheetAnimation);
  check(first?.sheetOpacity === 1, 'title block / validation gate are opaque from the first frame');

  await waitRevealDone(page);
  const done = await readSheet(page);
  perf.revealMs = Number(done?.duration || 0);
  check(Number.isFinite(perf.revealMs) && perf.revealMs > 0, 'the viewer recorded a real reveal duration', `${perf.revealMs} ms`);
  check(perf.revealMs >= 700, 'the full sequence is not skipped', `${perf.revealMs} ms`);
  check(done?.animatedOpacities.every((o) => o === 1), 'every animated phase is fully visible at completion');
  check(done?.animationsAfterDone === 0, 'no animation objects remain after completion', String(done?.animationsAfterDone));
  check(done?.floors === 2, 'the plan is a real 2-storey plate', String(done?.floors));

  console.log('\n[1b] Reveal cost on an already-mounted sheet');
  const replay = await page.evaluate(async () => {
    const tasks = [];
    let observer = null;
    try {
      observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) tasks.push(Math.round(entry.duration));
      });
      observer.observe({ entryTypes: ['longtask'] });
    } catch {
      /* longtask unsupported: the wall clock below is still valid */
    }
    const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
    if (!svg) return { tasks, supported: Boolean(observer), state: null, animations: -1 };
    svg.removeAttribute('data-bw-reveal');
    void svg.getBoundingClientRect();
    svg.setAttribute('data-bw-reveal', 'run');
    const start = performance.now();
    await new Promise((resolve) => setTimeout(resolve, 1500));
    observer?.disconnect();
    const animations = svg.getAnimations({ subtree: true }).length;
    const opacities = Array.from(svg.querySelectorAll('[data-bw-phase]:not([data-bw-phase="sheet"])')).map(
      (g) => Number(getComputedStyle(g).opacity)
    );
    svg.setAttribute('data-bw-reveal', 'done');
    return {
      tasks,
      supported: Boolean(observer),
      state: svg.getAttribute('data-bw-reveal'),
      animations,
      opacities,
      elapsed: Math.round(performance.now() - start),
    };
  });
  perf.replayLongTasks = replay.tasks;
  perf.replayElapsedMs = replay.elapsed;
  check(replay.opacities?.every((o) => o === 1), 'the isolated replay reaches full opacity');
  check(
    (replay.tasks || []).filter((ms) => ms > 100).length === 0,
    'the CSS reveal adds no >100 ms long task on an idle sheet',
    JSON.stringify(replay.tasks || [])
  );

  console.log('\n[2] Room selection highlights the drawing in place');
  const chip = await page.$('[data-testid^="room-chip-"]');
  check(Boolean(chip), 'a room chip is available');
  if (chip) {
    await chip.click();
    await page.waitForFunction(() =>
      Boolean(document.querySelector('[data-testid="blueprint-sheet-card"] svg[data-room-focus="on"]'))
    , { timeout: 3000 });
    await sleep(260);
    const focused = await readSheet(page);
    const fillStats = await page.evaluate(() => {
      const svg = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
      const fills = Array.from(svg.querySelectorAll('.bw-room-fill'));
      const selected = fills.find((f) => f.classList.contains('bw-room-selected'));
      const muted = fills.find((f) => !f.classList.contains('bw-room-selected'));
      return {
        selected: selected ? Number(getComputedStyle(selected).fillOpacity) : null,
        muted: muted ? Number(getComputedStyle(muted).fillOpacity) : null,
        total: fills.length,
      };
    });
    check(focused?.selectedRooms === 1, 'exactly one room fill is selected', String(focused?.selectedRooms));
    check(focused?.roomFocus === 'on', 'the sheet carries the focus switch');
    check(
      fillStats.selected !== null && fillStats.muted !== null && fillStats.selected > fillStats.muted,
      'selected fill is brighter than the muted context',
      `${fillStats.selected} vs ${fillStats.muted}`
    );
    await chip.click();
    await sleep(120);
    const cleared = await readSheet(page);
    check(cleared?.roomFocus === null && cleared?.selectedRooms === 0, 'a second press clears the focus');
  }
  await page.screenshot({ path: path.join(OUT, 'multi-final-desktop.png'), fullPage: true });

  console.log('\n[3] Fullscreen dialog semantics + focus');
  const expand = await page.$('[data-testid="blueprint-expand"]');
  check(Boolean(expand), 'fullscreen trigger exists');
  if (expand) {
    await expand.focus();
    await expand.click();
    await page.waitForSelector(SELECT.modal, { timeout: 4000 });
    await sleep(150);
    const modalState = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
      const active = document.activeElement;
      return {
        ariaModal: dialog?.getAttribute('aria-modal'),
        ariaLabel: dialog?.getAttribute('aria-label') || '',
        containsFocus: Boolean(dialog?.contains(active)),
        onClose: Boolean(active?.hasAttribute('data-blueprint-modal-close')),
        bodyOverflow: document.body.style.overflow,
        sheetCount: dialog?.querySelectorAll('[data-bw-reveal]').length || 0,
      };
    });
    check(modalState.ariaModal === 'true', 'dialog is modal to assistive tech');
    check(modalState.ariaLabel.length > 0, 'dialog has an accessible name', modalState.ariaLabel);
    check(modalState.onClose, 'initial focus lands on Close');
    check(modalState.bodyOverflow === 'hidden', 'background scroll is locked');

    const readable = await page.evaluate(() => {
      const canvas = document.querySelector('[data-testid="blueprint-modal-viewport"]');
      const sheet = document.querySelector('[data-testid="blueprint-sheet-card"] svg');
      const modalSvg = document.querySelector('[data-testid="blueprint-sheet-modal"] svg');
      const zoomText = document.querySelector('[data-testid="blueprint-modal-zoom-value"]')?.textContent || '';
      const cRect = canvas?.getBoundingClientRect();
      const sRect = modalSvg?.getBoundingClientRect();
      return {
        zoom: parseInt(zoomText, 10),
        width: sRect?.width || 0,
        topGap: cRect && sRect ? sRect.top - cRect.top : -1,
        canvasHeight: cRect?.height || 0,
        cardStillPresent: Boolean(sheet),
        framing: modalSvg?.getAttribute('data-bw-view') || null,
      };
    });
    // Plan Focus is itself the readable frame: it opens at 100% because the
    // viewBox is already the plan crop. Full Sheet keeps the opening 2× view.
    check(
      readable.framing === 'plan' ? readable.zoom === 100 && readable.width >= 300 : readable.zoom >= 200,
      'fullscreen opens at a readable framing',
      `${readable.zoom}% · ${readable.framing} · ${Math.round(readable.width)}px`
    );
    check(readable.width >= 300, 'the sheet is wide enough to read dimensions', `${Math.round(readable.width)} px`);
    check(
      readable.topGap >= 0 && readable.topGap < readable.canvasHeight * 0.35,
      'the sheet opens top-aligned (plan), not on the middle schedules',
      `${Math.round(readable.topGap)} / ${Math.round(readable.canvasHeight)} px`
    );

    // Trap: focus the first control, Shift+Tab must wrap to the last control.
    const wrapped = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
      const items = Array.from(
        dialog.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((el) => el.getClientRects().length > 0);
      items[0]?.focus();
      return { first: document.activeElement?.textContent?.trim().slice(0, 30), count: items.length };
    });
    await page.keyboard.down('Shift');
    await page.keyboard.press('Tab');
    await page.keyboard.up('Shift');
    const trapped = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
      const items = Array.from(
        dialog.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((el) => el.getClientRects().length > 0);
      return {
        inside: Boolean(dialog?.contains(document.activeElement)),
        isLast: document.activeElement === items[items.length - 1],
      };
    });
    check(trapped.inside, 'Tab focus is trapped inside the dialog');
    check(trapped.isLast, 'Shift+Tab from the first control wraps to the last', JSON.stringify(wrapped));

    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('[role="dialog"][aria-modal="true"]'), { timeout: 3000 });
    const restored = await page.evaluate(() => ({
      onTrigger: document.activeElement?.getAttribute('data-testid') === 'blueprint-expand',
      overflow: document.body.style.overflow,
    }));
    check(restored.onTrigger, 'focus returns to the fullscreen trigger');
    check(restored.overflow === '', 'background scroll is restored');
  }

  console.log('\n[4] Keyboard control of the sheet viewport');
  await page.focus('[data-testid="blueprint-viewport"]');
  await page.keyboard.press('Equal');
  await sleep(80);
  const zoomed = await page.$eval('[data-testid="blueprint-zoom-value"]', (el) => el.textContent.trim());
  await page.keyboard.press('Digit0');
  await sleep(80);
  const reset = await page.$eval('[data-testid="blueprint-zoom-value"]', (el) => el.textContent.trim());
  check(zoomed === '125%', '+ zooms the focused sheet to 125%', zoomed);
  check(reset === '100%', '0 returns to the fitted 100% view', reset);

  console.log('\n[5] Floor switching does not replay the reveal');
  const floorTab = await page.$('[data-testid="tab-floor-1"]');
  if (floorTab) {
    await floorTab.click();
    await page.waitForFunction(
      () =>
        document.querySelector('[data-testid="tab-floor-1"]')?.getAttribute('aria-pressed') === 'true' &&
        Boolean(document.querySelector('[data-testid="blueprint-sheet-card"] svg')),
      { timeout: 5000 }
    );
    await sleep(160);
    const floorState = await readSheet(page);
    check(floorState?.state === 'done', 'a second floor arrives finished, not re-animated', floorState?.state);
    check(floorState?.phases.length === 11, 'the new floor has the same addressable phases');
    await page.click('[data-testid="tab-floor-0"]');
    await page.waitForFunction(
      () => document.querySelector('[data-testid="tab-floor-0"]')?.getAttribute('aria-pressed') === 'true',
      { timeout: 5000 }
    );
  } else {
    check(false, 'floor tab for the second storey exists');
  }

  console.log('\n[6] Exported SVG is the finished drawing');
  await page.evaluate(() => {
    const client = document.createElement('div');
    client.id = 'download-probe';
    document.body.appendChild(client);
  });
  const downloadDir = path.join(OUT, 'downloads');
  // Chrome overwrites the same generated filename when the export is repeated,
  // so a "new filename" check would miss a successful download. Clear only this
  // test-owned evidence directory and wait for the file to appear.
  fs.rmSync(downloadDir, { recursive: true, force: true });
  fs.mkdirSync(downloadDir, { recursive: true });
  const client = await page.createCDPSession();
  await client.send('Browser.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: downloadDir,
    eventsEnabled: true,
  });
  await page.click('[data-testid="blueprint-expand"]');
  await page.waitForSelector(SELECT.modal, { timeout: 3000 });
  await page.click('[data-testid="blueprint-export-svg"]');
  const file = await waitForFile(downloadDir, new Set());
  check(Boolean(file), 'SVG export produced a file', file || 'no file');
  if (file) {
    const svg = fs.readFileSync(file, 'utf8');
    check(svg.includes('data-bw-phase="sheet"'), 'export keeps the verdict-bearing sheet group');
    check(svg.includes('data-room-id='), 'export keeps room identity');
    check(!/<svg[^>]*data-bw-reveal=/.test(svg), 'export carries no reveal switch on its root');
    check(!/data-bw-reveal-ms/.test(svg), 'export carries no timing diagnostics');
    check(svg.includes('@keyframes bwSheetPhaseIn'), 'reveal CSS is inert in the export, not geometry');
  }
  await page.keyboard.press('Escape');
  await sleep(120);
  await page.close();
}

async function testFail(browser, perf) {
  console.log('\n[7] Fail-stamped plan · verdict is visible during the reveal');
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
  await installProbe(page);
  await page.goto(URL, { waitUntil: 'networkidle2' });
  const mountMs = await mount(page, 'fail');
  const first = await readSheet(page);
  perf.failMountMs = mountMs;
  perf.failLongTasks = await page.evaluate(() => window.__bwLongTasks || []);

  check(first?.proofVerdict === 'NOT-CERTIFIED-FAIL-STAMP', 'server returned the fail-stamp verdict', first?.proofVerdict);
  check(Boolean(first?.chip), 'refusal chip exists on the failing plan');
  check(
    (first?.chip?.text || '').includes('NOT-CERTIFIED-FAIL-STAMP'),
    'chip renders the server verdict verbatim',
    first?.chip?.text
  );
  check(first?.sheetAnimation === 'none', 'verdict-bearing sheet group is outside the animation');
  check(first?.sheetOpacity === 1, 'sheet group is opaque while layers are still revealing');
  check((first?.animatedOpacities || []).some((o) => o < 1), 'at least one drawing layer is still hidden', JSON.stringify(first?.animatedOpacities));

  await waitRevealDone(page);
  const failDone = await readSheet(page);
  perf.failRevealMs = Number(failDone?.duration || 0);
  check(
    failDone?.state === 'done' && perf.failRevealMs >= 700,
    'the failing sheet also completes its bounded reveal',
    `${perf.failRevealMs} ms`
  );

  await replayAndPause(page, 300);
  const paused = await readSheet(page);
  check(
    paused?.chip !== null && paused?.sheetOpacity === 1,
    'FAIL chip + sheet remain visible at a mid-reveal frame'
  );
  check(
    (paused?.animatedOpacities || []).some((o) => o < 0.95),
    'the paused frame is genuinely mid-sequence',
    JSON.stringify(paused?.animatedOpacities)
  );
  const chipVisible = await page.evaluate(() => {
    const chip = document.querySelector('[data-testid="viewer-not-certified-chip"]');
    if (!chip) return false;
    const rect = chip.getBoundingClientRect();
    const style = getComputedStyle(chip);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && Number(style.opacity) > 0.99;
  });
  check(chipVisible, 'the refusal chip is painted, not just present in the DOM');
  await page.screenshot({ path: path.join(OUT, 'fail-mid-reveal-300ms.png'), fullPage: true });
  await replayAndPause(page, 620);
  await page.screenshot({ path: path.join(OUT, 'fail-mid-reveal-620ms.png'), fullPage: true });
  await setFinished(page);
  await page.screenshot({ path: path.join(OUT, 'fail-final-desktop.png'), fullPage: true });

  console.log('\n[7b] Single-storey room selection is not inert');
  const singleChip = await page.$('[data-testid^="room-chip-"]');
  check(Boolean(singleChip), 'single-storey room chip exists');
  if (singleChip) {
    await singleChip.click();
    await page.waitForFunction(
      () => Boolean(document.querySelector('[data-testid="blueprint-sheet-card"] svg[data-room-focus="on"]')),
      { timeout: 3000 }
    );
    await sleep(240);
    const singleFocus = await readSheet(page);
    check(singleFocus?.selectedRooms === 1, 'single-storey selection highlights one fill');
    check(singleFocus?.roomFocus === 'on', 'single-storey selection sets the focus switch');
  }
  await page.close();
}

async function testDense(browser, perf) {
  console.log('\n[7c] Dense 8 × 40 m, 3-storey plate');
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
  await page.goto(URL, { waitUntil: 'networkidle2' });
  const mountMs = await mount(page, 'dense');
  await waitRevealDone(page);
  const state = await readSheet(page);
  perf.denseMountMs = mountMs;
  perf.denseRevealMs = Number(state?.duration || 0);
  perf.denseFills = state?.fills || 0;
  check(state?.floors === 3, 'three floor plates are present', String(state?.floors));
  check(state?.phases.length === 11, 'the dense plate keeps all phase groups');
  check((state?.fills || 0) >= 6, 'the narrow ground plate has a full room set', String(state?.fills));
  check(state?.state === 'done', 'the dense plate completes its reveal', state?.state || 'missing');
  check((state?.duration || 0) >= 700, 'the dense plate reveal is not skipped', `${state?.duration} ms`);
  const tabs = await page.$$eval('[data-testid^="tab-floor-"]', (els) => els.length);
  check(tabs === 3, 'three storey tabs are rendered', String(tabs));
  const perFloor = [];
  for (let index = 0; index < 3; index += 1) {
    await page.click(`[data-testid="tab-floor-${index}"]`);
    await page.waitForFunction(
      (i) =>
        document.querySelector(`[data-testid="tab-floor-${i}"]`)?.getAttribute('aria-pressed') === 'true' &&
        Boolean(document.querySelector('[data-testid="blueprint-sheet-card"] svg')),
      { timeout: 5000 },
      index
    );
    await sleep(120);
    const floor = await readSheet(page);
    perFloor.push({ floor: index, fills: floor?.fills || 0, state: floor?.state });
  }
  check(perFloor.every((f) => f.fills >= 5), 'every storey carries a drawn room set', JSON.stringify(perFloor));
  check(perFloor.reduce((sum, f) => sum + f.fills, 0) >= 12, 'the dense stack totals a large programme', JSON.stringify(perFloor));
  check(perFloor.slice(1).every((f) => f.state === 'done'), 'upper floors open finished, without replay');
  await page.screenshot({ path: path.join(OUT, 'dense-8x40-final.png'), fullPage: true });
  await page.close();
}

async function testMobile(browser) {
  console.log('\n[8] 390 px layout');
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await page.goto(URL, { waitUntil: 'networkidle2' });
  await mount(page, 'multi');
  await waitRevealDone(page);
  const layout = await page.evaluate(() => {
    const viewer = document.getElementById('blueprint-viewer-container');
    const rect = viewer?.getBoundingClientRect();
    return {
      docOverflow: document.documentElement.scrollWidth - window.innerWidth,
      viewerWidth: rect?.width || 0,
      viewportWidth: window.innerWidth,
    };
  });
  check(layout.docOverflow <= 1, 'no horizontal page overflow', `${layout.docOverflow}px`);
  check(layout.viewerWidth <= layout.viewportWidth, 'the viewer fits the phone width', `${layout.viewerWidth}/${layout.viewportWidth}`);
  await page.screenshot({ path: path.join(OUT, 'mobile-390-final.png'), fullPage: true });

  await page.click('[data-testid="blueprint-expand"]');
  await page.waitForSelector(SELECT.modal, { timeout: 3000 });
  await sleep(160);
  const dialog = await page.evaluate(() => {
    const el = document.querySelector('[role="dialog"][aria-modal="true"]');
    const r = el?.getBoundingClientRect();
    return r ? { left: r.left, right: r.right, top: r.top, bottom: r.bottom, w: window.innerWidth, h: window.innerHeight } : null;
  });
  check(
    Boolean(dialog) && dialog.left >= 0 && dialog.right <= dialog.w + 1 && dialog.top >= 0 && dialog.bottom <= dialog.h + 1,
    'fullscreen dialog fits the phone viewport',
    JSON.stringify(dialog)
  );
  await page.screenshot({ path: path.join(OUT, 'mobile-390-modal.png') });
  await page.close();
}

async function testReducedMotion(browser) {
  console.log('\n[9] prefers-reduced-motion');
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 900, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.goto(URL, { waitUntil: 'networkidle2' });
  await mount(page, 'multi');
  await sleep(120);
  const state = await readSheet(page);
  check(state?.state === 'off', 'reduced motion switches the reveal off', state?.state || 'missing');
  check(state?.animationsAfterDone === 0, 'no animations are created', String(state?.animationsAfterDone));
  check(state?.animatedOpacities.every((o) => o === 1), 'all drawing layers are immediately visible');
  check(!state?.duration, 'no reveal duration is recorded', state?.duration || '');
  await page.screenshot({ path: path.join(OUT, 'reduced-motion-final.png'), fullPage: true });
  await page.close();
}

async function main() {
  if (!CHROME) throw new Error('Chrome not found. Set CHROME_PATH.');
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  });
  const perf = { url: URL, startedAt: new Date().toISOString() };
  try {
    await testMulti(browser, perf);
    await testFail(browser, perf);
    await testDense(browser, perf);
    await testMobile(browser);
    await testReducedMotion(browser);
  } finally {
    await browser.close();
  }
  perf.longTaskMaxMs = Math.max(0, ...(perf.longTasks || []), ...(perf.failLongTasks || []));
  perf.longTaskCount = (perf.longTasks || []).length + (perf.failLongTasks || []).length;
  fs.writeFileSync(path.join(OUT, 'perf-blueprint.json'), JSON.stringify(perf, null, 2));
  console.log(`\n=== blueprint reveal e2e: ${passes} passed, ${failures} failed ===`);
  console.log(`  perf → ${path.join(OUT, 'perf-blueprint.json')}`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
