#!/usr/bin/env node
/**
 * landing_audit.cjs — Live-browser audit of the BuildWise marketing
 * landing page (route "/"), driven through real Chrome via Puppeteer.
 *
 * WHAT IT PRODUCES (all under frontend/.audit/landing/):
 *   landing-audit.json   machine-readable evidence (one record per viewport)
 *   shots/*.png          per-viewport screenshots + fold + a11y/motion passes
 *
 * WHAT IT MEASURES, per viewport (1440 / 1280 / 1024 / 834 / 390):
 *   - console errors, page exceptions, failed network requests
 *   - horizontal overflow: document level AND per-element (+ off-canvas boxes)
 *   - tap-target sizes against BOTH 44x44 (WCAG 2.5.5 AAA / this programme's
 *     bar) and 24x24 (WCAG 2.5.8 AA)
 *   - Core Web Vitals via the real `web-vitals` library (IIFE build), including
 *     an INP sample driven by genuine input events
 *   - axe-core (WCAG 2.0 A/AA, 2.1 A/AA, 2.2 AA + best-practice) violations
 *   - document structure: landmarks, heading order, meta/OG/JSON-LD presence
 * Plus: a dark-theme parity pass, a prefers-reduced-motion pass, and WebGL
 * capability probes for future 3D work.
 *
 * Tooling: `axe-core` and `web-vitals` are devDependencies, so a clean
 * `npm install` is enough to run this audit. Neither reaches the app's graph.
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.LANDING_URL || 'http://localhost:4173/';
const OUT_DIR = path.join(__dirname, '..', '.audit', 'landing');
const SHOTS_DIR = path.join(OUT_DIR, 'shots');
/*
 * axe-core and web-vitals are devDependencies. They used to be read out of an
 * untracked `.audit-tools` install, which meant this audit could not run on a
 * clean checkout — a gate whose tooling is not in the lockfile is not a gate.
 * The old location remains as a fallback for a machine that still has it.
 */
const TOOLS = [path.join(__dirname, '..', 'node_modules'), path.join(__dirname, '..', '.audit-tools', 'node_modules')].find(
  (dir) => fs.existsSync(path.join(dir, 'axe-core', 'axe.min.js')),
);
if (!TOOLS) throw new Error('axe-core is not installed — run `npm install` in frontend/');
const AXE_PATH = path.join(TOOLS, 'axe-core', 'axe.min.js');
const WEBVITALS_PATH = path.join(TOOLS, 'web-vitals', 'dist', 'web-vitals.iife.js');

const VIEWPORTS = [
  { name: '1440', width: 1440, height: 900, mobile: false },
  { name: '1280', width: 1280, height: 800, mobile: false },
  { name: '1024', width: 1024, height: 768, mobile: false },
  { name: '834', width: 834, height: 1112, mobile: true },
  { name: '390', width: 390, height: 844, mobile: true },
];

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

function getChromePath() {
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) return process.env.CHROME_PATH;
  const candidates = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    process.env.LOCALAPPDATA && process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean);
  for (const p of candidates) if (fs.existsSync(p)) return p;
  throw new Error('Chrome executable not found. Set CHROME_PATH.');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function runAxe(page) {
  await page.addScriptTag({ path: AXE_PATH });
  return await page.evaluate(async (tags) => {
    const res = await window.axe.run(document, { runOnly: { type: 'tag', values: tags }, resultTypes: ['violations'] });
    return {
      violations: res.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        helpUrl: v.helpUrl,
        nodes: v.nodes.slice(0, 6).map((n) => ({
          target: n.target.join(' '),
          summary: (n.failureSummary || '').replace(/\s+/g, ' ').slice(0, 200),
        })),
        nodeCount: v.nodes.length,
      })),
      violationCount: res.violations.length,
      nodeCount: res.violations.reduce((a, v) => a + v.nodes.length, 0),
    };
  }, AXE_TAGS);
}

/** Injected into the page: collect every shape of layout defect. */
function scanLayout() {
  const winW = window.innerWidth;

  // Is this element's box clipped away by an overflow-hidden/clip ancestor?
  // (Decorative layers legitimately extend past the viewport and are clipped.)
  function clippedByAncestor(el) {
    let node = el.parentElement;
    while (node && node !== document.body) {
      const s = getComputedStyle(node);
      const ox = s.overflowX;
      const oy = s.overflowY;
      if (ox === 'hidden' || ox === 'clip' || oy === 'hidden' || oy === 'clip') {
        const r = node.getBoundingClientRect();
        const er = el.getBoundingClientRect();
        // Ancestor already covers/extends beyond this element on the axis.
        if (er.right <= r.right + 1 && er.left >= r.left - 1) return true;
      }
      node = node.parentElement;
    }
    return false;
  }

  const skip = (el) => {
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'head', 'meta', 'link', 'noscript', 'title', 'html', 'body'].includes(tag)) return true;
    if (el.closest('svg') || tag === 'svg') return true; // svg geometry is its own coordinate space
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return true;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return true;
    if (s.textOverflow === 'ellipsis' || el.classList.contains('truncate')) return true;
    if (s.webkitLineClamp && s.webkitLineClamp !== 'none') return true;
    return false;
  };

  function sel(el) {
    let s = el.tagName.toLowerCase();
    if (el.id) return `#${el.id}`;
    if (typeof el.className === 'string' && el.className.trim()) {
      const c = el.className.split(/\s+/).filter((x) => x && x.length < 40 && !/[[\]():/%]/.test(x));
      if (c.length) s += '.' + c.slice(0, 3).join('.');
    }
    return s;
  }

  const elementOverflow = [];
  const offCanvas = [];

  for (const el of document.querySelectorAll('*')) {
    if (skip(el)) continue;
    const s = getComputedStyle(el);

    const scrollableX = s.overflowX === 'auto' || s.overflowX === 'scroll';
    if (!scrollableX && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1) {
      elementOverflow.push({
        selector: sel(el),
        detail: `scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}`,
        diff: el.scrollWidth - el.clientWidth,
        text: (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60),
      });
    }

    const r = el.getBoundingClientRect();
    if (r.right > winW + 1 || r.left < -1) {
      if (clippedByAncestor(el)) continue;
      // A sticky/fixed element parked at a negative offset on purpose is rare;
      // report it and let the report decide.
      offCanvas.push({
        selector: sel(el),
        detail: r.right > winW + 1 ? `right ${Math.round(r.right)} > viewport ${winW}` : `left ${Math.round(r.left)} < 0`,
        diff: r.right > winW + 1 ? Math.round(r.right - winW) : Math.round(-r.left),
        position: s.position,
        text: (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40),
      });
    }
  }

  elementOverflow.sort((a, b) => b.diff - a.diff);
  offCanvas.sort((a, b) => b.diff - a.diff);

  // ---- Tap targets -------------------------------------------------------
  const interactive = [];
  const selector = 'a[href], button, [role="button"], [role="link"], [role="switch"], [role="tab"], input:not([type="hidden"]), select, textarea, summary';
  for (const el of document.querySelectorAll(selector)) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0' || s.pointerEvents === 'none') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    // WCAG exempts links rendered inside a sentence of text.
    const inlineInProse = el.tagName === 'A' && s.display === 'inline' && (el.parentElement?.innerText || '').trim().length > 60;
    if (inlineInProse) continue;
    interactive.push({
      selector: sel(el),
      label: (el.getAttribute('aria-label') || el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 48),
      w: Math.round(r.width * 10) / 10,
      h: Math.round(r.height * 10) / 10,
      tag: el.tagName.toLowerCase(),
    });
  }
  const under44 = interactive.filter((t) => t.w < 44 || t.h < 44);
  const under24 = interactive.filter((t) => t.w < 24 || t.h < 24);

  return {
    docOverflow: {
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: winW,
      diff: document.documentElement.scrollWidth - winW,
      bodyScrollWidth: document.body.scrollWidth,
      canScrollX: document.documentElement.scrollWidth > winW,
    },
    pageHeight: document.documentElement.scrollHeight,
    elementOverflow: elementOverflow.slice(0, 25),
    elementOverflowCount: elementOverflow.length,
    offCanvas: offCanvas.slice(0, 25),
    offCanvasCount: offCanvas.length,
    tapTargets: {
      total: interactive.length,
      under44Count: under44.length,
      under24Count: under24.length,
      under44: under44.slice(0, 30),
      under24: under24.slice(0, 30),
    },
  };
}

/** Injected into the page: DOM/a11y/SEO structure census. */
function scanStructure() {
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map((h) => ({
    level: Number(h.tagName[1]),
    text: (h.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 90),
  }));
  const imgs = Array.from(document.images).map((i) => ({
    src: i.currentSrc || i.src,
    alt: i.getAttribute('alt'),
    hasAltAttr: i.hasAttribute('alt'),
    width: i.naturalWidth,
    height: i.naturalHeight,
  }));
  const landmarks = {
    main: document.querySelectorAll('main').length,
    nav: document.querySelectorAll('nav').length,
    header: document.querySelectorAll('header').length,
    footer: document.querySelectorAll('footer').length,
    section: document.querySelectorAll('section').length,
  };
  const buttons = Array.from(document.querySelectorAll('button, a[href]')).map((b) =>
    (b.getAttribute('aria-label') || b.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60)
  );
  return {
    title: document.title,
    lang: document.documentElement.lang,
    metaDescription: document.querySelector('meta[name="description"]')?.getAttribute('content') || null,
    canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href') || null,
    og: Array.from(document.querySelectorAll('meta[property^="og:"]')).map((m) => m.getAttribute('property')),
    twitter: Array.from(document.querySelectorAll('meta[name^="twitter:"]')).map((m) => m.getAttribute('name')),
    jsonLd: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map((s) => (s.textContent || '').slice(0, 120)),
    headings,
    headingOrderValid: (() => {
      let prev = 0;
      for (const h of headings) {
        if (prev && h.level > prev + 1) return false;
        prev = h.level;
      }
      return true;
    })(),
    h1Count: headings.filter((h) => h.level === 1).length,
    images: imgs,
    imagesMissingAlt: imgs.filter((i) => !i.hasAltAttr).length,
    landmarks,
    interactiveCount: buttons.length,
    canvases: document.querySelectorAll('canvas').length,
    canvasesWithLabel: Array.from(document.querySelectorAll('canvas')).map((c) => ({
      ariaLabel: c.getAttribute('aria-label'),
      role: c.getAttribute('role'),
      hidden: c.getAttribute('aria-hidden'),
    })),
    webgl: (() => {
      try {
        const c = document.createElement('canvas');
        const gl2 = c.getContext('webgl2');
        const gl1 = gl2 ? null : c.getContext('webgl') || c.getContext('experimental-webgl');
        const ctx = gl2 || gl1;
        if (!ctx) return { webgl2: false, webgl1: false };
        const dbg = ctx.getExtension('WEBGL_debug_renderer_info');
        return {
          webgl2: Boolean(gl2),
          webgl1: Boolean(gl1),
          vendor: dbg ? ctx.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : ctx.getParameter(ctx.VENDOR),
          renderer: dbg ? ctx.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : ctx.getParameter(ctx.RENDERER),
          maxTextureSize: ctx.getParameter(ctx.MAX_TEXTURE_SIZE),
        };
      } catch (e) {
        return { error: String(e) };
      }
    })(),
    navInfo: {
      deviceMemory: navigator.deviceMemory ?? null,
      hardwareConcurrency: navigator.hardwareConcurrency ?? null,
      dpr: window.devicePixelRatio,
      connection: navigator.connection?.effectiveType ?? null,
      saveData: navigator.connection?.saveData ?? null,
    },
    /** Above-the-fold copy, for the 5-second test. */
    foldText: (() => {
      const out = [];
      const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = walk.nextNode())) {
        const el = n.parentElement;
        if (!el) continue;
        const r = el.getBoundingClientRect();
        if (r.bottom < 0 || r.top > window.innerHeight || r.width === 0) continue;
        const s = getComputedStyle(el);
        if (s.visibility === 'hidden' || s.opacity === '0') continue;
        const t = (n.textContent || '').trim();
        if (t) out.push(t);
      }
      return out.slice(0, 60);
    })(),
    sectionIds: Array.from(document.querySelectorAll('main > section, main > div > section, section')).map(
      (s) => s.id || s.getAttribute('aria-label') || '(unnamed)'
    ),
  };
}

async function attachCollectors(page) {
  const c = { consoleErrors: [], consoleWarnings: [], pageErrors: [], failedRequests: [] };
  page.on('console', (msg) => {
    const t = msg.text();
    if (msg.type() === 'error') c.consoleErrors.push(t.slice(0, 300));
    else if (msg.type() === 'warning') c.consoleWarnings.push(t.slice(0, 300));
  });
  page.on('pageerror', (err) => c.pageErrors.push(String(err).slice(0, 300)));
  page.on('requestfailed', (req) => {
    const url = req.url();
    c.failedRequests.push({ url: url.slice(0, 160), error: req.failure()?.errorText || 'unknown' });
  });
  return c;
}

const VITALS_BOOTSTRAP = () => {
  window.__bwVitals = { lcp: null, cls: null, fcp: null, ttfb: null, inp: null, raw: [] };
  const v = window.webVitals;
  if (!v) return false;
  const put = (name) => (m) => {
    window.__bwVitals[name] = { value: Math.round(m.value * 1000) / 1000, rating: m.rating, id: m.id };
    window.__bwVitals.raw.push({ name, value: m.value, rating: m.rating });
  };
  v.onLCP(put('lcp'), { reportAllChanges: true });
  v.onCLS(put('cls'), { reportAllChanges: true });
  v.onFCP(put('fcp'));
  v.onTTFB(put('ttfb'));
  v.onINP(put('inp'), { reportAllChanges: true });
  return true;
};

(async () => {
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  const chromePath = getChromePath();
  const out = {
    meta: {
      url: BASE_URL,
      chromePath,
      startedAt: new Date().toISOString(),
      viewports: VIEWPORTS.map((v) => v.name),
      tools: {
        axe: require(path.join(TOOLS, 'axe-core', 'package.json')).version,
        webVitals: require(path.join(TOOLS, 'web-vitals', 'package.json')).version,
      },
    },
    viewports: [],
    darkThemePass: null,
    reducedMotionPass: null,
    screenshots: [],
  };

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  });

  const shoot = async (page, name, fullPage) => {
    const file = path.join(SHOTS_DIR, `${name}.png`);
    await page.screenshot({ path: file, fullPage });
    out.screenshots.push({ name, file: path.relative(OUT_DIR, file).replace(/\\/g, '/'), fullPage: Boolean(fullPage) });
    return file;
  };

  for (const vp of VIEWPORTS) {
    const page = await browser.newPage();
    const collectors = await attachCollectors(page);
    await page.setViewport({
      width: vp.width,
      height: vp.height,
      deviceScaleFactor: 1,
      isMobile: vp.mobile,
      hasTouch: vp.mobile,
    });
    await page.goto(BASE_URL, { waitUntil: 'networkidle0', timeout: 60000 });
    await page.waitForSelector('.bw-landing', { timeout: 20000 });
    await page.waitForSelector('h1', { timeout: 20000 });
    await sleep(1400); // let entrances settle before measuring CLS

    // ---- layout / structure -------------------------------------------------
    const layout = await page.evaluate(scanLayout);
    const structure = await page.evaluate(scanStructure);

    // ---- Core Web Vitals via web-vitals ------------------------------------
    await page.addScriptTag({ path: WEBVITALS_PATH });
    const vitalsArmed = await page.evaluate(VITALS_BOOTSTRAP);

    // genuine input to produce an INP sample: scroll, then click real controls
    await page.mouse.wheel({ deltaY: 600 });
    await sleep(400);
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(300);
    // One nav anchor, selected by SHAPE rather than by destination: this list used to
    // name `#platform` (the anchor the platform-preview section owns), and when that
    // section was removed the entry silently stopped matching anything — `page.$`
    // returns null and the loop skips it — so the INP sample quietly lost one of its
    // three real clicks without the run failing. Naming a section here at all is the
    // same trap, so it asks for a nav link to a fragment and takes whatever the page
    // has. The secondary hero CTA is matched the same way, by the text it renders.
    const clickTargets = [
      'button[aria-label="Open menu"]',
      // A section link, not the brand's `#top`: same shape rule, one exclusion.
      'nav a[href^="#"]:not([href="#top"])',
    ];
    for (const sel of clickTargets) {
      const el = await page.$(sel);
      if (el) {
        try {
          await el.click();
        } catch {
          /* off-screen at this breakpoint */
        }
        await sleep(250);
      }
    }
    // a CTA hover+focus pass, without navigating away from the landing route. This
    // looked for /Explore the platform/i, which no CTA has ever said — the hero's
    // secondary control reads "See the platform" and is an anchor, not a button, so
    // the pass focused nothing. It now matches the control's own text across both
    // element types.
    await page.evaluate(() => {
      const controls = Array.from(document.querySelectorAll('a, button'));
      const secondary = controls.find((el) => /See the platform/i.test(el.textContent || ''));
      secondary?.focus();
    });
    await sleep(300);
    const vitals = await page.evaluate(() => window.__bwVitals);

    // ---- axe ---------------------------------------------------------------
    const axe = await runAxe(page);
    // ---- screenshots -------------------------------------------------------
    await shoot(page, `v${vp.name}-fold`, false);
    await shoot(page, `v${vp.name}-full`, true);

    out.viewports.push({
      name: vp.name,
      width: vp.width,
      height: vp.height,
      isMobile: vp.mobile,
      collectors,
      layout,
      structure,
      vitals,
      vitalsArmed,
      axe,
      pageHeight: layout.pageHeight,
    });
    console.log(
      `[${vp.name}] errors=${collectors.consoleErrors.length} pageErrors=${collectors.pageErrors.length} ` +
      `docOverflow=${layout.docOverflow.diff}px elOverflow=${layout.elementOverflowCount} offCanvas=${layout.offCanvasCount} ` +
      `tap<44=${layout.tapTargets.under44Count}/${layout.tapTargets.total} cls=${vitals.cls?.value ?? 'n/a'} lcp=${vitals.lcp?.value ?? 'n/a'}ms ` +
      `axe=${axe.violationCount}v/${axe.nodeCount}n`
    );
    await page.close();
  }

  // ---- OS-dark-preference & dark theme pass --------------------------------
  // The landing supports full light & dark mode. When the OS prefers dark or
  // the theme toggle is clicked, the landing seamlessly adopts the architectural
  // blueprint obsidian palette (--bw-porcelain-1: #090d16, --bw-ink: #f8fafc).
  {
    const page = await browser.newPage();
    const collectors = await attachCollectors(page);
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
    await page.goto(BASE_URL, { waitUntil: 'networkidle0', timeout: 60000 });
    await page.waitForSelector('.bw-landing');
    await sleep(1200);
    const paints = await page.evaluate(() => {
      const probe = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const s = getComputedStyle(el);
        return { bg: s.backgroundColor, color: s.color, border: s.borderTopColor };
      };
      return {
        body: { bg: getComputedStyle(document.body).backgroundColor, color: getComputedStyle(document.body).color },
        landing: probe('.bw-landing'),
        nav: probe('.bw-nav'),
        featureCard: probe('.bw-surface'),
        ink: getComputedStyle(document.documentElement).getPropertyValue('--bw-ink').trim(),
        porcelain: getComputedStyle(document.documentElement).getPropertyValue('--bw-porcelain-1').trim(),
        hasThemeAttr: document.documentElement.getAttribute('data-theme'),
      };
    });
    const axe = await runAxe(page);
    await shoot(page, 'v1440-dark-theme', false);
    out.darkThemePass = { collectors, paints, axe };
    console.log(`[dark-preference] bodyBg=${paints.body.bg} bw-ink=${paints.ink} (landing dark mode active, axe violations=${axe.violationCount})`);
    await page.close();
  }

  // ---- prefers-reduced-motion pass ----------------------------------------
  {
    const page = await browser.newPage();
    const collectors = await attachCollectors(page);
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.goto(BASE_URL, { waitUntil: 'networkidle0', timeout: 60000 });
    await page.waitForSelector('.bw-landing');
    await sleep(1600);

    // Scroll to the bottom so every below-fold section is revealed, then check
    // that pinned/animated layers are frozen and content is visible.
    const total = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y <= total; y += 500) {
      await page.evaluate((yy) => window.scrollTo(0, yy), y);
      await sleep(120);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(400);

    // The two ambient loops this pass used to inspect (`.bw-mist-drift`,
    // `.bw-needle-wobble`) were CSS for a hero that has been removed, and the rules
    // and their keyframes went with it — so the queries were reading classes that can
    // no longer exist, and reported `null` for both on every run. What is left here
    // is the part that can still be true or false: nothing pinned, mid-reveal, or
    // half-faded is sitting on screen once the reader is back at the top.
    const rm = await page.evaluate(() => {
      const reveals = Array.from(document.querySelectorAll('.bw-surface, [data-reveal]'));
      const hidden = Array.from(document.querySelectorAll('h2, h3, .bw-surface')).filter(
        (el) => Number(getComputedStyle(el).opacity) < 0.9 && el.getBoundingClientRect().top < window.innerHeight
      ).length;
      return {
        lenisActive: document.documentElement.classList.contains('lenis'),
        scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
        revealSampleSize: reveals.length,
        visibleButFadedCount: hidden,
      };
    });
    await shoot(page, 'v1440-reduced-motion', false);
    out.reducedMotionPass = { collectors, ...rm };
    console.log(`[reduced-motion] lenis=${rm.lenisActive} revealSampleSize=${rm.revealSampleSize} fadedNearViewport=${rm.visibleButFadedCount}`);
    await page.close();
  }

  // ---- gate ----------------------------------------------------------------
  // This file used to write evidence and exit 0 whatever it found, so a
  // console error, an axe violation or 6/10 undersized tap targets could ship
  // under a green "audit". The hard failures are now exit status.
  const failures = [];
  for (const v of out.viewports) {
    const where = `${v.name}px`;
    if (v.collectors.consoleErrors.length) failures.push(`${where}: ${v.collectors.consoleErrors.length} console error(s)`);
    if (v.collectors.pageErrors.length) failures.push(`${where}: ${v.collectors.pageErrors.length} page error(s)`);
    if (v.axe.violationCount) failures.push(`${where}: ${v.axe.violationCount} axe violation(s) / ${v.axe.nodeCount} node(s)`);
    if (v.layout.tapTargets.under44Count) failures.push(`${where}: ${v.layout.tapTargets.under44Count}/${v.layout.tapTargets.total} tap target(s) under 44px`);
    if (v.layout.docOverflow.diff > 1) failures.push(`${where}: document overflows by ${v.layout.docOverflow.diff}px`);
  }
  if (out.darkThemePass.collectors.pageErrors.length || out.darkThemePass.collectors.consoleErrors.length) {
    failures.push('dark pass: console/page errors');
  }
  const rgb = (s) => (s.match(/\d+/g) || []).slice(0, 3).map(Number);
  const [dr, dg, db] = rgb(out.darkThemePass.paints.body.bg);
  const groundLum = (0.2126 * dr + 0.7152 * dg + 0.0722 * db) / 255;
  const [ir, ig, ib] = rgb(out.darkThemePass.paints.landing.color);
  const inkLum = (0.2126 * ir + 0.7152 * ig + 0.0722 * ib) / 255;
  if (!(groundLum < 0.25 && inkLum > 0.7)) {
    failures.push(`dark-preference pass: landing dark contrast unexpected (ground ${out.darkThemePass.paints.body.bg}, ink ${out.darkThemePass.paints.landing.color})`);
  }
  if (out.darkThemePass.axe && out.darkThemePass.axe.violationCount) {
    failures.push(`dark-preference pass: ${out.darkThemePass.axe.violationCount} axe violation(s) in dark mode`);
  }

  fs.writeFileSync(path.join(OUT_DIR, 'landing-audit.json'), JSON.stringify(out, null, 2));
  console.log(`\nWrote ${path.relative(process.cwd(), path.join(OUT_DIR, 'landing-audit.json'))} and ${out.screenshots.length} screenshots.`);
  if (failures.length) {
    console.log(`GATE FAIL — ${failures.length} finding(s):`);
    for (const f of failures) console.log(`  - ${f}`);
    process.exitCode = 1;
  } else {
    console.log('GATE PASS — no console/page errors, no axe violations, no tap target under 44px, no document overflow, landing supports full light & dark themes.');
  }
  await browser.close();
})().catch(async (e) => {
  console.error('AUDIT FAILED:', e);
  process.exit(1);
});
