#!/usr/bin/env node
/**
 * gate_browser.cjs — the default browser regression gate.
 * =====================================================
 * Runs the browser suites sequentially against the shared dev servers:
 *
 *   API  :8000   app  :5173
 *
 * The servers are EXTERNALLY MANAGED, exactly as before this runner existed:
 * CI starts them in `.github/workflows/ci.yml`; a local run starts them in
 * separate terminals. This runner deliberately does not start, restart or stop
 * them. It therefore cannot duplicate server startup, cannot kill a server the
 * user owns, and cannot leak a server it did not create. It does own every
 * suite process (and the browser that suite starts) and terminates that process
 * tree on timeout or interruption.
 *
 * Why this runner instead of a longer `&&` chain:
 *   - one preflight fails clearly when the shared servers are not ready;
 *   - every suite is named and timed, and its own pass/fail summary is kept;
 *   - a hung suite cannot block the gate forever;
 *   - the aggregate exit status is nonzero after any failure;
 *   - signal cleanup kills only the active test tree, not the app servers.
 *
 * `perf_blueprint_validation.cjs` is intentionally NOT here. It is a diagnostic
 * with machine-specific measurements, not a per-commit pass/fail gate.
 *
 * Usage:
 *   npm run gates:browser
 *   E2E_URL=http://127.0.0.1:5173/app E2E_API_URL=http://127.0.0.1:8000/api/health npm run gates:browser
 *
 * `reset contract` is the one suite whose default is not the bare /app URL: it
 * starts on a shared-site deep link. It therefore ignores E2E_URL unless
 * E2E_RESET_URL is set, which is how CI gives it the loopback deep link.
 */
const { spawn, spawnSync } = require('child_process');
const http = require('http');
const https = require('https');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const APP_URL = process.env.E2E_URL || 'http://127.0.0.1:5173/app';
const API_URL = process.env.E2E_API_URL || 'http://127.0.0.1:8000/api/health';
const RESET_URL = process.env.E2E_RESET_URL || '';

const SUITES = [
  { name: 'reset contract', script: 'e2e_reset_contract.cjs', timeoutMs: 360000, preserveDeepLink: true },
  { name: 'selection policy', script: 'e2e_selection_policy.cjs', timeoutMs: 300000 },
  { name: 'full funnel', script: 'e2e_full_funnel.cjs', timeoutMs: 600000 },
  { name: 'UI closure', script: 'e2e_ui_closure.cjs', timeoutMs: 360000 },
  { name: 'warning overflow', script: 'e2e_warning_overflow.cjs', timeoutMs: 180000 },
  { name: 'blueprint progressive reveal', script: 'e2e_blueprint_reveal.cjs', timeoutMs: 420000 },
  { name: 'blueprint view modes', script: 'e2e_blueprint_view_modes.cjs', timeoutMs: 420000 },
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function probe(url, timeoutMs = 5000) {
  return new Promise((resolve) => {
    let parsed;
    try {
      parsed = new URL(url);
    } catch {
      resolve({ ok: false, reason: 'invalid URL' });
      return;
    }
    const client = parsed.protocol === 'https:' ? https : http;
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };
    const req = client.get(parsed, { timeout: timeoutMs }, (res) => {
      res.resume();
      const ok = res.statusCode >= 200 && res.statusCode < 400;
      finish({ ok, reason: `HTTP ${res.statusCode}` });
    });
    req.on('timeout', () => {
      req.destroy();
      finish({ ok: false, reason: `no response within ${timeoutMs} ms` });
    });
    req.on('error', (error) => finish({ ok: false, reason: error.code || error.message }));
  });
}

async function preflight() {
  console.log('browser gate — shared servers are externally managed');
  console.log(`  app  ${APP_URL}`);
  console.log(`  api  ${API_URL}`);
  console.log('  this runner never starts or stops them\n');

  const [app, api] = await Promise.all([probe(APP_URL), probe(API_URL)]);
  const failures = [];
  if (!app.ok) failures.push(`app  ${APP_URL} — ${app.reason}`);
  if (!api.ok) failures.push(`api  ${API_URL} — ${api.reason}`);

  if (failures.length) {
    console.error('FAIL: the shared servers are not ready.');
    failures.forEach((line) => console.error(`  ${line}`));
    console.error(
      '\nStart the backend on :8000 and the frontend dev server on :5173, then rerun.' +
        '\nCI starts both in .github/workflows/ci.yml. This runner deliberately does not.'
    );
    return false;
  }
  console.log('  preflight PASS\n');
  return true;
}

function killTree(child) {
  if (!child || child.killed) return;
  if (process.platform === 'win32') {
    // /T includes the Puppeteer Chrome child; /F is required because a hung
    // suite may ignore the normal termination request.
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    return;
  }
  try {
    process.kill(-child.pid, 'SIGKILL');
  } catch {
    try {
      child.kill('SIGKILL');
    } catch {
      /* already gone */
    }
  }
}

/**
 * Extract the suite's own final count line without changing its output.
 * Existing suites use three summary shapes:
 *   `N passed, M failed`            (warning overflow, blueprints)
 *   `N/M checks passed`             (selection policy)
 *   `PASS — N checks` / `FAIL (M) — N checks` (reset contract)
 */
function extractCounts(text) {
  const patterns = [
    {
      re: /(\d+)\s+passed,\s+(\d+)\s+failed/g,
      parse: (m) => ({ passed: Number(m[1]), failed: Number(m[2]) }),
    },
    {
      re: /(\d+)\/(\d+)\s+checks passed/g,
      parse: (m) => {
        const passed = Number(m[1]);
        const total = Number(m[2]);
        return { passed, failed: Math.max(0, total - passed) };
      },
    },
    {
      re: /PASS\s+—\s+(\d+)\s+checks/g,
      parse: (m) => ({ passed: Number(m[1]), failed: 0 }),
    },
    {
      re: /FAIL\s+\((\d+)\)\s+—\s+(\d+)\s+checks/g,
      parse: (m) => {
        const failed = Number(m[1]);
        const total = Number(m[2]);
        return { passed: Math.max(0, total - failed), failed };
      },
    },
  ];
  let result = null;
  for (const { re, parse } of patterns) {
    let match;
    while ((match = re.exec(text))) result = parse(match);
  }
  return result;
}

function runSuite(suite, suiteIndex) {
  return new Promise((resolve) => {
    const scriptPath = path.join(__dirname, suite.script);
    console.log(`\n[${suiteIndex + 1}/${SUITES.length}] ${suite.name}`);
    console.log(`      node scripts/${suite.script}`);
    const started = Date.now();
    let active = null;
    let timedOut = false;
    let stdout = '';
    let stderr = '';

    const env = { ...process.env };
    if (suite.preserveDeepLink) {
      // Reset contract must not start on the bare /app URL: its fixture is the
      // shared-site deep link. Use E2E_RESET_URL when CI supplies the loopback
      // host, otherwise let the suite's own default apply.
      if (RESET_URL) env.E2E_URL = RESET_URL;
      else delete env.E2E_URL;
    }

    const child = spawn(process.execPath, [scriptPath], {
      cwd: ROOT,
      // Every other suite receives E2E_URL (CI points them at 127.0.0.1);
      // without it they fall back to their own localhost defaults.
      env,
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    active = child;
    activeChild = child;

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
      process.stdout.write(chunk);
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
      process.stderr.write(chunk);
    });

    const timer = setTimeout(() => {
      timedOut = true;
      console.error(
        `\n  TIMEOUT: ${suite.name} exceeded ${Math.round(suite.timeoutMs / 1000)} s; terminating its process tree.`
      );
      killTree(child);
    }, suite.timeoutMs);

    const finish = (code, signal) => {
      clearTimeout(timer);
      if (activeChild === child) activeChild = null;
      const seconds = ((Date.now() - started) / 1000).toFixed(1);
      const combined = `${stdout}\n${stderr}`;
      const counts = extractCounts(combined);
      const ok = !timedOut && code === 0;
      const countText = counts
        ? `${counts.passed} passed, ${counts.failed} failed`
        : timedOut
          ? 'timed out'
          : 'counts not parsed from suite summary';
      console.log(
        `\n  ${ok ? 'PASS' : 'FAIL'} ${suite.name} — ${countText} (${seconds}s)`
      );
      if (!ok && !timedOut && code !== 0) {
        console.error(`  ${suite.name} exited with code ${code}${signal ? ` (${signal})` : ''}`);
      }
      resolve({ ok, code, signal, timedOut, seconds, counts });
    };

    child.once('error', (error) => {
      clearTimeout(timer);
      if (activeChild === child) activeChild = null;
      console.error(`\n  FAIL ${suite.name}: could not start — ${error.message}`);
      resolve({ ok: false, code: null, signal: null, timedOut: false, seconds: '0.0', counts: null });
    });
    child.once('close', finish);
  });
}

let activeChild = null;
let interrupted = false;

function interrupt(signal) {
  if (interrupted) return;
  interrupted = true;
  console.error(`\n\nInterrupted by ${signal}; terminating the active test tree (servers stay up).`);
  killTree(activeChild);
  setTimeout(() => process.exit(signal === 'SIGINT' ? 130 : 143), 250);
}
process.once('SIGINT', () => interrupt('SIGINT'));
process.once('SIGTERM', () => interrupt('SIGTERM'));

(async () => {
  const startedAt = Date.now();
  if (!(await preflight())) {
    process.exit(2);
  }

  const results = [];
  for (let suiteIndex = 0; suiteIndex < SUITES.length; suiteIndex += 1) {
    const result = await runSuite(SUITES[suiteIndex], suiteIndex);
    results.push({ ...SUITES[suiteIndex], ...result });
    if (!result.ok || interrupted) break;
  }

  const passed = results.filter((r) => r.ok).length;
  const failed = results.filter((r) => !r.ok).length;
  const notRun = SUITES.length - results.length;
  const totalChecks = results.reduce(
    (sum, r) => ({
      passed: sum.passed + (r.counts ? r.counts.passed : 0),
      failed: sum.failed + (r.counts ? r.counts.failed : 0),
    }),
    { passed: 0, failed: 0 }
  );
  const elapsed = Math.round((Date.now() - startedAt) / 1000);
  const minutes = Math.floor(elapsed / 60);
  const seconds = String(elapsed % 60).padStart(2, '0');

  console.log('\n' + '='.repeat(72));
  console.log(
    `browser gate: ${passed}/${SUITES.length} suites passed, ${failed} failed, ${notRun} not run`
  );
  console.log(
    `check totals from parsed summaries: ${totalChecks.passed} passed, ${totalChecks.failed} failed`
  );
  console.log(`elapsed: ${minutes}m ${seconds}s`);
  if (failed || notRun) {
    const failedNames = results.filter((r) => !r.ok).map((r) => r.name);
    if (failedNames.length) console.log(`failed suite(s): ${failedNames.join(', ')}`);
    if (notRun) {
      console.log(`not run: ${SUITES.slice(results.length).map((s) => s.name).join(', ')}`);
    }
    console.log('RESULT: FAIL');
    process.exit(1);
  }
  console.log('RESULT: PASS — all browser suites passed');
  process.exit(0);
})().catch((error) => {
  console.error('fatal browser gate error:', error);
  process.exit(2);
});
