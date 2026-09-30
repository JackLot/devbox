#!/usr/bin/env node
// Headless-browser check for runner agents, which can't keep a dev server running in
// the background. One foreground command starts the server, waits for the page, takes a
// screenshot per viewport width, reports console errors and failed requests as JSON,
// and kills the server and the browser before it exits.
//
//   node check.mjs --cmd "npm run dev -- --port 5180" --url http://localhost:5180/
//
// Run with --help for all options. Installed by ../install.sh.

import { spawn } from "node:child_process";
import { mkdirSync, openSync, readFileSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { chromium } from "playwright";

const HELP = `Usage: node check.mjs --url URL [options]

  --url URL          page to load (required)
  --cmd "CMD"        start this server first (bash -c, own process group), wait for URL,
                     kill it on exit. Omit if something is already serving URL.
  --widths 375,1280  viewport widths, one screenshot each (default 375,1280)
  --height N         viewport height (default 900)
  --out DIR          screenshot directory (default /tmp/agent-browser/<time>)
  --wait-for SEL     wait for this CSS selector after load
  --script FILE      ES module run at each width after load, before the screenshot:
                       export default async (page, { url, width, shot }) => { ... }
                     page is a Playwright Page; await shot("name") saves <width>-name.png
  --allow-host H     let the page reach this local/private host[:port] too (repeatable);
                     other localhost ports, private IPs, tailnet names are blocked
  --timeout S        overall limit in seconds (default 120)

Prints a JSON report; open the PNGs with the Read tool to look at them.
Exit 0 when every width loaded (check the report for errors), 1 otherwise.`;

const { values: opt } = parseArgs({
  options: {
    url: { type: "string" },
    cmd: { type: "string" },
    widths: { type: "string", default: "375,1280" },
    height: { type: "string", default: "900" },
    out: { type: "string" },
    "wait-for": { type: "string" },
    script: { type: "string" },
    "allow-host": { type: "string", multiple: true, default: [] },
    timeout: { type: "string", default: "120" },
    help: { type: "boolean", short: "h" },
  },
});
if (opt.help || !opt.url) {
  console.log(HELP);
  process.exit(opt.help ? 0 : 1);
}

const target = new URL(opt.url);
const widths = opt.widths.split(",").map(Number).filter(Boolean);
const height = Number(opt.height);
const out = resolve(opt.out ?? `/tmp/agent-browser/${new Date().toISOString().replace(/[:.]/g, "-")}`);
mkdirSync(out, { recursive: true });

let server, browser;
async function cleanup() {
  await browser?.close().catch(() => {});
  if (server?.exitCode === null) {
    try { process.kill(-server.pid, "SIGTERM"); } catch {}
    await new Promise((r) => setTimeout(r, 1000));
    try { process.kill(-server.pid, "SIGKILL"); } catch {}
  }
}
function fail(message, extra = {}) {
  console.log(JSON.stringify({ ok: false, error: message, ...extra }, null, 2));
  return cleanup().then(() => process.exit(1));
}
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => fail(`got ${sig}`));
process.on("uncaughtException", (e) => fail(`crashed: ${e.stack ?? e}`));
// Last resort if we exit some other way: never leave the server running
process.on("exit", () => { if (server?.exitCode === null) try { process.kill(-server.pid, "SIGKILL"); } catch {} });
setTimeout(() => fail(`timed out after ${opt.timeout}s`), Number(opt.timeout) * 1000).unref();

// Local and private hosts: the devbox dashboard (:9999, with live Stop/Hibernate buttons)
// and anything else on the tailnet. Blocked unless it's the target or --allow-host;
// public hosts (CDNs, fonts) are left alone. This guards against mistakes, not attacks.
function isPrivateHost(host) {
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".ts.net")) return true;
  if (!host.includes(".") && !host.includes(":")) return true; // single-label, e.g. "devbox"
  if (host === "[::1]" || /^\[f[cd]/i.test(host)) return true;
  const m = host.match(/^(\d+)\.(\d+)\.\d+\.\d+$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 127 || a === 10 || a === 0 || (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
}
const allowed = new Set([target.host, ...opt["allow-host"]]);
const isBlocked = (u) => !allowed.has(u.host) && !allowed.has(u.hostname) && isPrivateHost(u.hostname);

let serverLog;
if (opt.cmd) {
  serverLog = `${out}/server.log`;
  const fd = openSync(serverLog, "a");
  server = spawn("bash", ["-c", opt.cmd], { detached: true, stdio: ["ignore", fd, fd] });
}
const logTail = () => serverLog ? readFileSync(serverLog, "utf8").split("\n").slice(-30).join("\n") : undefined;

function answers(url) {
  return new Promise((done) => {
    const req = (url.startsWith("https:") ? https : http).get(url, { timeout: 2000 }, (res) => {
      res.resume();
      done(true);
    });
    req.on("error", () => done(false));
    req.on("timeout", () => req.destroy());
  });
}

// Wait until the URL answers (any HTTP status), or the server exits
for (let up = false; !up;) {
  if (server && server.exitCode !== null) {
    await fail(`server exited with code ${server.exitCode} before ${opt.url} answered`, { serverLog: logTail() });
  }
  up = await answers(opt.url);
  if (!up) await new Promise((r) => setTimeout(r, 500));
}

const script = opt.script ? (await import(pathToFileURL(resolve(opt.script)).href)).default : null;
browser = await chromium.launch();
const report = { ok: true, url: opt.url, out, pages: [] };

for (const width of widths) {
  const page = await browser.newPage({ viewport: { width, height } });
  const r = { width, screenshots: [], console: [], pageErrors: [], failedRequests: [], badResponses: [], blocked: [] };
  report.pages.push(r);
  await page.route("**/*", (route) => {
    const u = new URL(route.request().url());
    if (/^https?:$/.test(u.protocol) && isBlocked(u)) {
      r.blocked.push(u.href);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  page.on("console", (m) => {
    if (m.text().includes("ERR_BLOCKED_BY_CLIENT")) return; // already listed in blocked
    if (m.type() === "error" || m.type() === "warning") r.console.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => r.pageErrors.push(String(e.stack ?? e)));
  page.on("requestfailed", (q) => {
    if (!q.failure()?.errorText.includes("ERR_BLOCKED_BY_CLIENT")) r.failedRequests.push(`${q.url()} ${q.failure()?.errorText}`);
  });
  page.on("response", (s) => { if (s.status() >= 400) r.badResponses.push(`${s.status()} ${s.url()}`); });
  const shot = async (name) => {
    const path = `${out}/${width}${name ? `-${name}` : ""}.png`;
    await page.screenshot({ path, fullPage: true });
    r.screenshots.push(path);
    return path;
  };
  try {
    const res = await page.goto(opt.url, { waitUntil: "load" });
    r.status = res?.status();
    await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
    if (opt["wait-for"]) await page.waitForSelector(opt["wait-for"], { timeout: 10000 });
    if (script) await script(page, { url: opt.url, width, shot });
    await shot("");
  } catch (e) {
    r.error = String(e.message ?? e);
    report.ok = false;
    await shot("error").catch(() => {});
  }
  await page.close();
}

if (serverLog) report.serverLog = serverLog;
console.log(JSON.stringify(report, null, 2));
await cleanup();
process.exit(report.ok ? 0 : 1);
