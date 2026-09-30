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
- You can still exercise dashboard endpoints: in one foreground `python3 -c` script, import
  `server`, set `server.Handler.sampler` to a stub, run a `ThreadingHTTPServer` on port 0 in a
  daemon thread and hit it with `urllib`.
- `tmux capture-pane` and chained shell commands over `~/.claude` need approval you won't get;
  read `~/.claude/sessions/*.json` and transcripts with Read/Glob or a Python one-liner instead.
- `gh pr view` needs approval you won't get, so an earlier run's PR description is out of reach;
  work from `git log`/`git show` on the branch and the issue comments in your prompt.
- To syntax-check the dashboard JS without a browser, pull out the `<script>` body with Python
  and run `node --check` on it.

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
- The reviewer pastes that command into an ssh session on the devbox, which can't open a
  browser tab, so don't add an auto-open step (`open`, `xdg-open`, or wrapping it in
  `ssh devbox ... && open ...` from the laptop); they tried it and asked for it to be reverted.
