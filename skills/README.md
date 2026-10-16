# skills

Custom [Claude Code skills](https://code.claude.com/docs/en/skills.md), installed at user level
so every Claude Code session on the machine can use them: interactive sessions, their subagents,
and [agent-runner](../agent-runner/) runs.

```bash
~/devbox/skills/install.sh    # link each skill into ~/.claude/skills/, install its dependencies; safe to re-run
```

Each skill is a folder with a `SKILL.md`. `install.sh` symlinks it to `~/.claude/skills/<name>`,
so edits here take effect right away; commit them to keep them. If the folder has a
`package-lock.json`, `install.sh` runs `npm ci` in it (needs Node), and the package's
`postinstall` script fetches anything else it needs. `node_modules/` stays out of git.

| Skill | What it does |
|---|---|
| [`headless-browser`](headless-browser/SKILL.md) | Headless Chromium through a pinned Playwright: screenshots at any viewport with a report of console errors and failed requests (`scripts/shot.mjs`), and Playwright scripts for clicking through flows (`scripts/pw.mjs`). For machines with no display or browser tool, like the devbox |

## headless-browser

- `SKILL.md` uses absolute paths under `/home/dev/.claude/skills/headless-browser`, because
  agent-runner refuses Bash commands containing `$VAR`. On a machine whose user isn't `dev`,
  change those paths.
- The `postinstall` script downloads Chromium's headless shell into `~/.cache/ms-playwright`.
  Chromium's system libraries (`libnss3`, `libgbm`, ...) must already be installed; they are on
  the current devbox. If the browser won't launch, the error names the missing libraries:
  install them with `dnf` (Playwright's own `install-deps` only supports Debian and Ubuntu).
- To upgrade Playwright, change the version in `package.json` and re-run `install.sh`. The
  browser build has to match the Playwright version, which `postinstall` takes care of.
