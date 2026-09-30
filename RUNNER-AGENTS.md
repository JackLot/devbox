# RUNNER-AGENTS.md

Learnings for unattended runner agents ([`agent-runner/`](agent-runner/)) working in this repo.
Read this before starting; add to it when you learn something a future run would otherwise rediscover.

## Environment limits

- You can't leave processes running after you exit: `nohup`, `setsid` and backgrounding are
  refused, and so is `curl`. You can start a server in the foreground briefly to check that it
  boots, but you can't keep it up or fetch its pages.

## Letting the reviewer check your change

- For changes to `ec2/dashboard/`, the reviewer wants to try the branch in a browser. End the
  summary with a single copy-paste command that runs the dashboard from your worktree on port
  9998, next to the real one on 9999, plus how to stop it:

  ```bash
  nohup python3 ~/.agent-runner/worktrees/devbox-<N>/ec2/dashboard/server.py --port 9998 > /tmp/devbox-dashboard-issue<N>.log 2>&1 < /dev/null & disown
  # open http://devbox:9998 ; stop with: pkill -f 'server.py --port 9998'
  ```

  Use your actual worktree path (your working directory); it stays in place until the issue
  is closed. Warn that the test dashboard's **Hibernate now** and Stop buttons are live.
