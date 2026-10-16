// Re-exports the skill's pinned Playwright so scripts anywhere on disk can import it by absolute path:
//   import { chromium } from '/home/dev/.claude/skills/headless-browser/scripts/pw.mjs';
export { chromium, devices, expect } from 'playwright/test';
