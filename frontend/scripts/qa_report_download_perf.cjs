#!/usr/bin/env node
/**
 * qa_report_download_perf.cjs — repeatable browser download timing probe.
 *
 * Sends one saved /api/report payload from the real Vite origin, reads the
 * response body into a Blob, clicks the download link, and waits for the file
 * to finish writing. Writes a JSON timing record plus the PDF it downloaded.
 *
 * Usage:
 *   node scripts/qa_report_download_perf.cjs <request.json> <out-dir> [base-url]
 *
 * The request file must contain the exact { analysis_data, site_vision,
 * floor_plan } body. The output directory is created if absent.
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);

function resolveChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error('Chrome not found. Set CHROME_PATH to the Chrome executable.');
}

async function main() {
  const requestPath = process.argv[2];
  const outDir = path.resolve(process.argv[3] || '');
  const origin = process.argv[4] || 'http://localhost:5173';
  if (!requestPath || !outDir) {
    throw new Error('usage: node scripts/qa_report_download_perf.cjs <request.json> <out-dir> [origin]');
  }
  const body = fs.readFileSync(path.resolve(requestPath), 'utf8');
  if (!process.argv[3]) throw new Error('out-dir is required');
  fs.mkdirSync(outDir, { recursive: true });
  const downloadName = `download_${Date.now()}.pdf`;
  const downloadPath = path.join(outDir, downloadName);

  const browser = await puppeteer.launch({
    executablePath: resolveChrome(),
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  try {
    const client = await page.createCDPSession();
    await client.send('Browser.setDownloadBehavior', {
      behavior: 'allow',
      downloadPath: outDir,
    });
    await page.goto(origin, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const result = await page.evaluate(async (requestBody, name) => {
      const started = performance.now();
      const response = await fetch('http://127.0.0.1:8000/api/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody,
      });
      const headersMs = performance.now() - started;
      const buffer = await response.arrayBuffer();
      const bodyMs = performance.now() - started;
      const blob = new Blob([buffer], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return {
        status: response.status,
        flagCache: response.headers.get('X-Buildwise-Report-Cache'),
        bytes: buffer.byteLength,
        headersMs: Math.round(headersMs * 10) / 10,
        bodyMs: Math.round(bodyMs * 10) / 10,
      };
    }, body, downloadName);

    let size = 0;
    let stable = 0;
    const started = Date.now();
    while (Date.now() - started < 30000) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      const current = fs.existsSync(downloadPath) ? fs.statSync(downloadPath).size : 0;
      if (current > 0 && current === size) {
        stable += 1;
        if (stable >= 3) break;
      } else {
        stable = 0;
        size = current;
      }
    }
    const record = {
      request: path.resolve(requestPath),
      origin,
      ...result,
      downloadedBytes: size,
      downloadFile: downloadPath,
      totalWallMs: Date.now() - started,
    };
    const timingPath = path.join(outDir, 'browser_timing.json');
    fs.writeFileSync(timingPath, `${JSON.stringify(record, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(record, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
