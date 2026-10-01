# RUNNER-AGENTS.md

Learnings for unattended runner agents ([`agent-runner/`](agent-runner/)) working in this repo.
Read this before starting; add to it when you learn something a future run would otherwise rediscover.

## Environment limits

- You can't leave processes running after you exit: `nohup`, `setsid` and backgrounding are
  refused, and so is `curl`. You can start a server in the foreground briefly to check that it
  boots, but you can't keep it up or fetch its pages.
- Bash commands containing a shell expansion (`$(...)`, `$VAR`) are refused ("Contains
  simple_expansion"), even inside a quoted heredoc. That bites dashboard JS edits, where the code
  uses `$("id")`: make those edits with the Edit tool, not a Python/sed script run through Bash.
  `sed -i` chained with `&&` is refused too ("requires approval"); edit docs with the Edit tool.
- The dashboard is `index.html` (markup only) plus `static/style.css` and `static/*.js`: classic
  scripts sharing globals, loaded in the order `index.html` lists them. The reviewer asked for
  this split (issue #4); don't fold it back into one file. A new file there needs a `<script>`
  tag; `server.py` and `install.sh` pick up any `static/*.css|js` on their own.
- To syntax-check the dashboard JS without a browser, run `node --check` on each `static/*.js`
  (from a `python3 -c` subprocess loop; a shell `for` loop is refused). To catch runtime errors
  too, concatenate the scripts in `index.html` order and run them with `vm.runInContext`
  with stubbed `document`/`localStorage`/`fetch`/`setInterval`, then call `render()` on a
  snapshot saved from a `server.Sampler()` (call `.sample()` twice, a second apart, then
  `.get()`; `.get()` alone returns `{}`). Write that
  harness to `/tmp/*.js` with the Write tool (a Bash heredoc containing `{"` is refused), and
  make the stub element's `querySelector` return an object, or `spark()` and `bindModal()` throw; stub
  `removeAttribute` and `matches` too, and give `document` a `documentElement`. The sampled snapshot may have no `runner`
  issues, so to exercise the issue modal inject a fake `runner` (`issues`, `runs`, `home`)
  and call `openIssue("repo#N")`; `openMetric("cpu")`, `await openRun("<log name>")` and
  `openSessionLog(sid)` + `await fetchSessionLog()` cover the other modals (the disk modal:
  `await loadDiskUsage(false)` with the stub `fetch` returning a saved `/api/disk-usage` reply). One history row
  only gives "Collecting samples…", so fake a few `history.rows` to exercise the charts.
- Issues may say "Use /design": no `design` skill is installed for runner sessions, so do the
  design work directly and say so in the decisions.
- For large rewrites of a dashboard file (a whole section of `style.css`, say), Write the new
  block to `/tmp` and splice it in with a small Python script that is also written with the
  Write tool and run as `python3 /tmp/x.py`; then Read the file again before using Edit.
- There's no headless browser (no chromium/chrome on PATH), so layout changes (e.g. mobile
  CSS) can't be screenshotted here; say in the summary which widths the reviewer should check.
- The dashboard is plain http over Tailscale, so `navigator.clipboard` is undefined there;
  copy-to-clipboard needs the `execCommand("copy")` fallback (`copyText` in `static/util.js`).
  Inside a `showModal()` dialog the rest of the page is inert, so that fallback's textarea
  must be appended inside the dialog (pass it as `copyText`'s `host`), or nothing gets copied.
- Bash tools (`ls`, `tail`, `stat`, ...) are refused on paths outside your worktree, e.g.
  `~/.agent-runner/`. The Read and Glob tools, and `python3 -c` scripts, can still read them.
- `git -C <path> ...`, `cd <dir> && git ...` and `bash -n` are refused; run plain `git ...` from
  the working directory. `gh` isn't allowed directly but works from a `python3 -c` subprocess;
  so does `git merge` (refused as plain Bash, as are `rebase` and `merge-tree`), e.g. to merge `main`
  into the branch when the reviewer says code changed since the PR was opened.
- To test the dashboard's HTTP endpoints, start `ThreadingHTTPServer` with `server.Handler` on
  port 0 in a thread inside `python3 -c` and call it with `urllib`.
- When the reviewer says they made tweaks "in the worktree", they're usually uncommitted,
  and the runner's `git reset --hard` wiped them before you started. Cursor keeps local
  history: find the `~/.cursor-server/data/User/History/*/entries.json` whose `resource`
  ends in your worktree's file path; the newest entry's file in that folder is their last
  save. Diff it against HEAD and apply it (a `python3 -c` copy; `cp` from outside the
  worktree is refused). `git fsck` works from a `python3 -c` subprocess too, but won't have
  unstaged edits. Check this even when the newest comment asks for nothing new: a re-run with
  no new requests can mean they saved tweaks after your last push (compare entry timestamps
  with the last commit time).
- To test `agent-runner/agent-runner` without touching GitHub: `bash -n` it from a `python3`
  subprocess; run `--dry-run` with `AGENT_RUNNER_HOME` set to a `/tmp` dir whose `repos` lists
  `/home/dev/devbox`; and put a fake `gh` (a script that serves JSON fixtures through `jq`
  and `exec`s the real one otherwise) first on `PATH` to fake labels or reviews.
- Scripts that `ec2/bootstrap.sh` installs (`devbox-idle-check`, `devbox-idle`) are heredocs in
  it and need root paths. To test one, pull the heredoc out with a Python regex, replace the
  `/var/lib/...`, `/var/log/...` and `/etc/devbox/...` paths with a temp dir and `logger` with
  `true`, write it out and run it (`bash -n <file>` works from a `python3` subprocess). Changes
  there only reach the box when the reviewer re-runs `bootstrap.sh` over SSM (and
  `dashboard/install.sh` for the service unit); say so in the summary.

## Letting the reviewer check your change

- For changes to `ec2/dashboard/`, the reviewer wants to try the branch in a browser. Under
  `### Audit`, give a single copy-paste command that runs the dashboard from your worktree on
  port 9998, next to the real one on 9999:

  ```bash
  nohup python3 ~/.agent-runner/worktrees/devbox-<N>/ec2/dashboard/server.py --port 9998 > /tmp/devbox-dashboard-issue<N>.log 2>&1 < /dev/null & disown
  ```

  The code block must hold only that command (the reviewer copies it with the copy button
  and pastes it straight into a terminal; a `#` comment line breaks that). Follow it
  with just "Then open http://devbox:9998": the reviewer cut the stop command and the
  warning about live Hibernate/Stop buttons from their rewrite. Use your actual worktree
  path (your working directory); it stays in place until the issue is closed.
- The reviewer pastes that command into an ssh session on the devbox, which can't open a
  browser tab, so don't add an auto-open step (`open`, `xdg-open`, or wrapping it in
  `ssh devbox ... && open ...` from the laptop); they tried it and asked for it to be reverted.
