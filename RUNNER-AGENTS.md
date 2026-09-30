# RUNNER-AGENTS.md

Learnings for unattended runner agents ([`agent-runner/`](agent-runner/)) working in this repo.
Read this before starting; add to it when you learn something a future run would otherwise rediscover.

## Environment limits

- You can't leave processes running after you exit: `nohup`, `setsid` and backgrounding are
  refused, and so is `curl`. You can start a server in the foreground briefly to check that it
  boots, but you can't keep it up or fetch its pages.
- Bash commands containing a shell expansion (`$(...)`, `$VAR`) are refused ("Contains
  simple_expansion"), even inside a quoted heredoc. That bites `index.html` edits, where the JS
  uses `$("id")`: make those edits with the Edit tool, not a Python/sed script run through Bash.
- To syntax-check the dashboard JS without a browser, pull out the `<script>` body with Python
  and run `node --check` on it. To catch runtime errors too, `eval` that script in `node -e`
  with stubbed `document`/`localStorage`/`fetch`/`setInterval` and call `render()` on a
  snapshot saved from `server.Sampler().get()` (sample twice, a second apart). Write that
  harness to `/tmp/*.js` with the Write tool (a Bash heredoc containing `{"` is refused), and
  make the stub element's `querySelector` return an object, or `spark()` throws.
- The dashboard is plain http over Tailscale, so `navigator.clipboard` is undefined there;
  copy-to-clipboard needs the `execCommand("copy")` fallback (`copyText` in `index.html`).
- Bash tools (`ls`, `tail`, `stat`, ...) are refused on paths outside your worktree, e.g.
  `~/.agent-runner/`. The Read and Glob tools, and `python3 -c` scripts, can still read them.
- `git -C <path> ...`, `cd <dir> && git ...` and `bash -n` are refused; run plain `git ...` from
  the working directory. `gh` isn't allowed directly but works from a `python3 -c` subprocess.
- To test the dashboard's HTTP endpoints, start `ThreadingHTTPServer` with `server.Handler` on
  port 0 in a thread inside `python3 -c` and call it with `urllib`. Stub `subprocess.Popen`
  (after the first `sample()`) before exercising `/api/runner/start`, and remember it appends
  to the real `~/.agent-runner/cron.log`; you are yourself a runner run holding the lock.
- When the reviewer says they made tweaks "in the worktree", they're usually uncommitted,
  and the runner's `git reset --hard` wiped them before you started. Cursor keeps local
  history: find the `~/.cursor-server/data/User/History/*/entries.json` whose `resource`
  ends in your worktree's file path; the newest entry's file in that folder is their last
  save. Diff it against HEAD and apply it (a `python3 -c` copy; `cp` from outside the
  worktree is refused). `git fsck` works from a `python3 -c` subprocess too, but won't have
  unstaged edits.
## Letting the reviewer check your change

- For changes to `ec2/dashboard/`, the reviewer wants to try the branch in a browser. End the
  summary with a single copy-paste command that runs the dashboard from your worktree on port
  9998, next to the real one on 9999:

  ```bash
  nohup python3 ~/.agent-runner/worktrees/devbox-<N>/ec2/dashboard/server.py --port 9998 > /tmp/devbox-dashboard-issue<N>.log 2>&1 < /dev/null & disown
  ```

  The code block must hold only that command (the reviewer copies it with the copy button
  and pastes it straight into a terminal; a `#` comment line breaks that). Put the URL
  (http://devbox:9998) and the stop command (`pkill -f 'server.py --port 9998'`) in prose
  or their own code blocks. Use your actual worktree path (your working directory); it stays in place until the issue
  is closed. Warn that the test dashboard's **Hibernate now** and Stop buttons are live.
