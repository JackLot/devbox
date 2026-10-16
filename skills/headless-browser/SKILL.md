---
name: headless-browser
description: Spin up a headless Chromium on this machine to look at a web page — take screenshots at desktop/mobile sizes, catch console errors and failed requests, or script clicks, typing and multi-step flows with Playwright. Use whenever you need to visually check UI work or drive a page in a browser and have no browser tool. Assumes you already know how to start the app; this skill only covers the browser.
---

# Headless browser

This machine has no display and no browser tool, but it has headless Chromium and a pinned Playwright install in this skill's folder. Use them directly from Bash. Every command below starts its own browser and closes it when done, so any number of agents can use it at the same time without interfering.

Always write the full absolute paths shown below. Don't put them in a shell variable: some sandboxes refuse commands containing `$VAR`.

Start the app yourself first. Run the dev server with the Bash tool's `run_in_background` option (not `&` or `nohup`, which may be refused), then wait until it answers: `node -e "fetch('http://localhost:3000').then(r=>console.log(r.status))"` (`curl` may not be allowed). This skill does not know how any repo is served. Stop the server when you're done.

## 1. Screenshot and health check: `shot.mjs`

```bash
node /home/dev/.claude/skills/headless-browser/scripts/shot.mjs http://localhost:3000/some/page --out <scratchpad>/home.png
```

It prints JSON: HTTP `status`, `finalUrl` (catch unexpected redirects), `title`, screenshot paths, and every console error/warning, uncaught page error, failed request and 4xx/5xx response. Exit code 1 means the page didn't load at all (`error` explains why).

Then **look at the PNG with the Read tool**. The JSON says whether the page broke; only the image says whether it looks right.

Useful options (run with `--help` for all):

| Option | Use it to |
|---|---|
| `--viewport 1280x800,390x844` | check desktop and mobile in one run (one file per size) |
| `--device "iPhone 15"` | use a real device preset (touch, pixel ratio, user agent) |
| `--full-page` | capture the whole scrollable page |
| `--selector ".modal"` | capture just one element, sharper than a full-page shot |
| `--wait-for "[data-loaded]"` | wait for client-rendered content before capturing |
| `--wait 500` | let animations or transitions finish |
| `--color-scheme dark` | check dark mode |
| `--storage-state <file>` | start signed in (see section 3) |

## 2. Interactions and flows: write a Playwright script

When you need to click, type, hover, or step through a flow, write a short script in your scratchpad and import Playwright from this skill by absolute path (this needs no `npm install` in the repo):

```js
// <scratchpad>/flow.mjs
import { chromium } from '/home/dev/.claude/skills/headless-browser/scripts/pw.mjs';

const out = process.argv[2]; // directory for screenshots
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));

  await page.goto('http://localhost:3000/');
  await page.getByRole('button', { name: 'Start' }).click();
  await page.screenshot({ path: `${out}/01-after-start.png` });

  await page.getByLabel('Email').fill('test@example.com');
  await page.keyboard.press('Enter');
  await page.getByText('Welcome').waitFor();
  await page.screenshot({ path: `${out}/02-welcome.png` });

  console.log(JSON.stringify({ errors }, null, 2));
} finally {
  await browser.close();
}
```

```bash
node <scratchpad>/flow.mjs <scratchpad>
```

Guidelines:
- Find elements by role, label or text (`getByRole`, `getByLabel`, `getByText`) before CSS selectors. They match what a user sees and survive markup changes.
- Wait on something meaningful (`locator.waitFor()`, `page.waitForURL()`), not fixed sleeps.
- Take a numbered screenshot after each step that matters, then Read them in order.
- To understand an unfamiliar page without a screenshot, print its structure as text: `console.log(await page.locator('body').ariaSnapshot())`. It's cheap, and good for finding the right locator.
- Always close the browser in `finally` so failed runs don't leave Chromium processes behind.
- `expect` from Playwright Test is also exported from `pw.mjs` if you want assertions: `await expect(page.getByRole('heading')).toHaveText('Done')`.

## 3. Staying signed in across runs

Each run starts with an empty browser. If the app needs a login, sign in once and save the session, then reuse it:

```js
await page.context().storageState({ path: '<scratchpad>/auth.json' });
```

Then pass `--storage-state <scratchpad>/auth.json` to `shot.mjs`, or `browser.newContext({ storageState: '<scratchpad>/auth.json' })` in your own scripts. Keep this file in your scratchpad, never in the repo.

## Tips

- Very tall full-page screenshots get scaled down when you view them, so small text becomes unreadable. Prefer viewport or `--selector` shots, and use `--full-page` only for overall layout.
- Before reporting UI work done, check at least one mobile width (`390x844`) as well as desktop.
- `localhost` and `127.0.0.1` both work. The browser runs on this machine, so it reaches anything the dev server binds to.

## Troubleshooting

- **`Executable doesn't exist at .../ms-playwright/...`**: the browser download is missing. Run `npm --prefix /home/dev/.claude/skills/headless-browser exec -- playwright install --only-shell chromium`.
- **`net::ERR_CONNECTION_REFUSED`**: the dev server isn't up yet, or it's on a different port. Check the server's output.
- **Timeouts on `networkidle`** in your own scripts: dev servers keep connections open for hot reload. Wait for an element instead.
- **Fonts look wrong or show as boxes**: the page probably loads web fonts from a server that's unreachable here. Check `failedRequests` in the `shot.mjs` output.
