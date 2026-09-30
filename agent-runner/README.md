# agent-runner

A cron job on the devbox that turns GitHub issues labeled `agent` into pull requests.
Every 15 minutes it finds newly labeled issues, has Claude Code implement each one in a
git worktree of the local checkout, and opens a PR that closes the issue.

```bash
~/devbox/agent-runner/install.sh    # link script, seed config, install cron entry; safe to re-run
nvim ~/.agent-runner/repos          # list the checkouts to watch
agent-runner --dry-run              # shows what it would pick up
```

Needs cron (AL2023 doesn't ship it: `sudo dnf install -y cronie && sudo systemctl enable --now crond`),
plus `gh` and `claude`, both logged in.

## Labels

| Label | Meaning | What you do |
|---|---|---|
| `agent` | Queue this issue (create it yourself; the rest are created on the first run) | Add it |
| `agent-wip` | A run is working on it | Wait |
| `agent-pr` | PR opened or updated | Review; for changes, comment on the issue and re-add `agent` |
| `agent-needs-human` | Blocked; the agent's question is in an issue comment | Answer in a comment, re-add `agent` |
| `agent-failed` | Run errored or made no commits; see the issue comment | Fix the issue text or the runner, re-add `agent` |

Re-adding `agent` to an issue whose `agent/issue-N` branch already exists resumes on that branch
with the full comment thread, and pushes to the open PR instead of opening a new one.

## When the agent stops to ask

The prompt tells the agent to bias hard toward deciding: when the issue is ambiguous about
details (naming, copy, layout, approach, edge cases) it picks what fits the existing code,
finishes, and lists its judgment calls under **Decisions made** in the PR so they get reviewed
there. It returns `needs_human` only as a last resort: the goal is too unclear for any
implementation to be likely right, it needs access or setup it doesn't have, or it faces an
irreversible or high-risk choice (data deletion, breaking public APIs, security, billing) the
issue doesn't settle. It commits progress before stopping, and the question lands in an issue comment.

The agent reports its outcome through `--json-schema` structured output (`status`, `summary`,
`decisions`, `question`), so the script doesn't parse free text. To tune how readily it blocks,
edit the "Making decisions" section of the prompt in `agent-runner`.

## How a run works

1. For each checkout in `~/.agent-runner/repos`, list open issues labeled `agent`.
2. Swap the label to `agent-wip` so the next run doesn't pick it up again.
3. `git worktree add` the `agent/issue-N` branch, from `origin/agent/issue-N` if it exists,
   otherwise from `origin/<default branch>`, so the main checkout (and any interactive
   session in it) is untouched.
4. Symlink the untracked files listed for that repo (`.env`, tokens, ...) from the main
   checkout into the worktree.
5. `claude -p` with the issue title, body and comments. It can edit files, run project
   tooling and commit, but can't push (see `ALLOWED_TOOLS` in the script).
6. The script pushes any commits, then opens or updates the PR (`Closes #N`, the summary and
   decisions), and sets the final label with a comment.

A lock file means runs never overlap.

## Runtime directory

Everything machine-specific lives in one untracked directory, `~/.agent-runner/`, kept out of
this public repo because it names private repos and the logs can contain secrets the agent read:

```
~/.agent-runner/
  repos        # checkouts to watch + untracked files to link (from repos.example)
  cron.log     # one line per run
  logs/        # full JSON output of each issue run
  worktrees/   # agent/issue-N checkouts while a run is active
  lock
```

Set `AGENT_RUNNER_HOME` to use a different directory.

## Files

| Repo path | Installed as | Notes |
|---|---|---|
| `agent-runner` | `~/bin/agent-runner` (symlink) | The runner. Cron calls the repo path directly; the symlink is for running it by hand |
| `crontab` | user crontab, between `# BEGIN/END agent-runner` | Every 15 min; sets PATH since cron doesn't load `.zshrc`. `install.sh` fills in `$HOME` and this folder's path |
| `repos.example` | `~/.agent-runner/repos` (copy, never overwritten) | Template for the list of checkouts to watch |

## Security

The issue text is a prompt to an agent that runs shell commands next to your secrets. Adding a
label needs triage/write access, so outsiders can't queue work, but read issues and comments
someone else wrote before labeling (a resumed run reads every comment on the issue).

## Why local cron, not Claude routines

Claude Code routines have built-in triggers (schedule, an HTTP `/fire` endpoint, GitHub
events) and can run on a [self-hosted runner](https://code.claude.com/docs/en/self-hosted-environments.md).
But each run does a fresh clone into the runner's own working directory and deletes it after,
so untracked secrets have to be injected per session (wrapper script or environment variables).
Running [`claude -p`](https://code.claude.com/docs/en/headless.md) locally reuses the checkouts
that already have their secrets. Revisit routines if runs should be visible in claude.ai/code or
triggered by GitHub events instead of polling.
