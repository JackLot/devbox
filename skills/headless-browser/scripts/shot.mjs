#!/usr/bin/env node
// Load a URL in headless Chromium, save screenshot(s), and report what went wrong on the page.
// Prints one JSON object to stdout. Exits 1 if the page could not be loaded at all.
import { chromium, devices } from 'playwright';
import { parseArgs } from 'node:util';
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const HELP = `Usage: shot.mjs <url> [options]

  --out <path>             PNG path (default: $TMPDIR/headless-browser/<timestamp>.png).
                           With several viewports, each file gets a -<WxH> suffix.
  --viewport <WxH[,WxH]>   One or more viewports, e.g. 1280x800,390x844 (default 1280x800)
  --device <name>          Playwright device preset instead of --viewport, e.g. "iPhone 15"
  --full-page              Capture the whole scrollable page, not just the viewport
  --selector <css>         Screenshot only this element
  --wait-for <css>         Wait for this selector to be visible before capturing
  --wait <ms>              Extra delay before capturing (animations, transitions)
  --color-scheme <mode>    light | dark
  --storage-state <path>   Load cookies/localStorage saved by a previous login script
  --timeout <ms>           Navigation/wait timeout (default 30000)
`;

const { values: o, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    out: { type: 'string' },
    viewport: { type: 'string', default: '1280x800' },
    device: { type: 'string' },
    'full-page': { type: 'boolean', default: false },
    selector: { type: 'string' },
    'wait-for': { type: 'string' },
    wait: { type: 'string' },
    'color-scheme': { type: 'string' },
    'storage-state': { type: 'string' },
    timeout: { type: 'string', default: '30000' },
    help: { type: 'boolean', short: 'h' },
  },
});

const url = positionals[0];
if (o.help || !url) {
  process.stderr.write(HELP);
  process.exit(o.help ? 0 : 2);
}

const timeout = Number(o.timeout);
const out = path.resolve(o.out ?? path.join(tmpdir(), 'headless-browser', `${Date.now()}.png`));
mkdirSync(path.dirname(out), { recursive: true });

let targets;
if (o.device) {
  if (!devices[o.device]) {
    process.stderr.write(`Unknown device "${o.device}". Examples: "iPhone 15", "Pixel 7", "iPad Pro 11".\n`);
    process.exit(2);
  }
  targets = [{ label: o.device.replace(/\W+/g, '-'), context: devices[o.device] }];
} else {
  targets = o.viewport.split(',').map((v) => {
    const [width, height] = v.trim().toLowerCase().split('x').map(Number);
    if (!width || !height) {
      process.stderr.write(`Bad viewport "${v}", expected WxH like 1280x800.\n`);
      process.exit(2);
    }
    return { label: `${width}x${height}`, context: { viewport: { width, height } } };
  });
}

const browser = await chromium.launch();
const report = { url, screenshots: [], console: [], pageErrors: [], failedRequests: [], httpErrors: [] };
let failed = false;

try {
  for (const [i, t] of targets.entries()) {
    const context = await browser.newContext({
      ...t.context,
      ...(o['color-scheme'] && { colorScheme: o['color-scheme'] }),
      ...(o['storage-state'] && { storageState: o['storage-state'] }),
    });
    const page = await context.newPage();
    page.setDefaultTimeout(timeout);

    // Diagnostics are identical across viewports, so only collect them once.
    if (i === 0) {
      page.on('console', (m) => {
        if (m.type() === 'error' || m.type() === 'warning') report.console.push({ type: m.type(), text: m.text() });
      });
      page.on('pageerror', (e) => report.pageErrors.push(e.message));
      page.on('requestfailed', (r) => report.failedRequests.push({ url: r.url(), error: r.failure()?.errorText }));
      page.on('response', (r) => {
        if (r.status() >= 400) report.httpErrors.push({ url: r.url(), status: r.status() });
      });
    }

    const res = await page.goto(url, { waitUntil: 'load', timeout });
    // Dev servers often hold connections open (HMR), so networkidle is best-effort only.
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
    if (o['wait-for']) await page.locator(o['wait-for']).first().waitFor({ state: 'visible', timeout });
    if (o.wait) await page.waitForTimeout(Number(o.wait));

    if (i === 0) {
      report.status = res?.status() ?? null;
      report.finalUrl = page.url();
      report.title = await page.title();
    }

    const file = targets.length > 1 ? out.replace(/\.png$/i, '') + `-${t.label}.png` : out;
    const target = o.selector ? page.locator(o.selector).first() : page;
    await target.screenshot({ path: file, ...(!o.selector && { fullPage: o['full-page'] }) });
    report.screenshots.push({ viewport: t.label, path: file });
    await context.close();
  }
} catch (e) {
  failed = true;
  report.error = e.message.split('\n')[0];
} finally {
  await browser.close();
}

console.log(JSON.stringify(report, null, 2));
process.exit(failed ? 1 : 0);
