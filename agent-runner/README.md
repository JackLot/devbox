# agent-runner

A cron job on the devbox that turns GitHub issues labeled `agent` into pull requests. Every 15
minutes it picks up newly labeled issues, has Claude Code implement each one in its own git
worktree of your local checkout, and opens a PR that closes the issue. You review the PR, ask for
changes in a comment or code review, and the next run revises it.

## Set it up

**Prerequisites** (on the devbox, as `dev`):

- cron. Amazon Linux 2023 doesn't ship it:
  ```bash
  sudo dnf install -y cronie && sudo systemctl enable --now crond   # needs sudo: run it in devbox ssm
  ```
- `gh` and `claude`, both signed in (`gh auth status`, `claude auth status`). The GitHub token
  needs Issues read/write in addition to Contents and Pull requests (see
  [`ec2/CHECKLIST.md`](../ec2/CHECKLIST.md) section 10).
- `jq` and `flock`.
- A local checkout of each repo you want it to work on, with any untracked files it needs
  (`.env`, tokens) in place.

**Steps:**

1. Run the installer. It creates `~/.agent-runner/`, links the script to `~/bin/agent-runner`,
   and installs the cron entry. It's safe to re-run.
   ```bash
   ~/devbox/agent-runner/install.sh
   ```
   It ends with `==> done. Try: agent-runner --dry-run`. Any `warning:` line above that names a
   missing tool or a tool that isn't signed in; fix it before continuing.
2. List the checkouts to watch in `~/.agent-runner/repos`, one per line: the checkout path, then
   any untracked files to link into each worktree (globs expand relative to the checkout).
   ```bash
   nvim ~/.agent-runner/repos
   ```
   ```
   ~/myproject  .env .env.local
   ```
3. Create a label named `agent` in each watched repo. The runner creates the other labels on its
   first real run.
4. Check what it would pick up, without changing anything:
   ```bash
   agent-runner --dry-run
   ```
   For each queued issue you see a line like
   `[2026-10-15 09:00:00] [dry-run] would implement you/myproject#12: Add a logout button (branch agent/issue-12 from origin/main)`.
   With nothing queued you see `you/myproject: no issues or PRs labeled 'agent', no new code reviews`.

From then on, cron runs it every 15 minutes. Run `agent-runner` yourself to start a run now.

## Queue an issue and follow it

Add the `agent` label to an issue. The runner moves the issue through these labels:

| Label | Meaning | What you do |
|---|---|---|
| `agent` | Queued | Add it to queue the issue |
| `agent-wip` | A run is working on it | Wait |
| `agent-pr` | PR opened or updated, or a follow-up question answered in a comment | Review the PR. To ask for changes or questions, comment on the issue and re-add `agent`, or [give feedback on the PR](#give-feedback-on-the-pr) |
| `agent-needs-human` | Blocked; the agent's question is in an issue comment | Answer in a comment, then re-add `agent` |
| `agent-failed` | The run errored, made no commits, or couldn't push or open the PR. The issue comment says why and gives a `cd` command for the worktree | Fix the issue text or the runner, then re-add `agent` |

When you re-add `agent` to an issue whose `agent/issue-N` branch already exists, the run resumes
on that branch with the full comment thread and pushes to the open PR instead of opening a new
one. If your follow-up only needs an answer ("how do I run this?"), the agent replies in an issue
comment without committing, and the issue goes back to `agent-pr`.

**Before you label an issue, read it.** The issue text is a prompt to an agent that runs shell
commands next to your secrets; see [Security](#security).

## Give feedback on the PR

You don't have to go back to the issue to ask for changes. Either of these on an open
`agent/issue-N` PR queues a run for issue N, the same as re-adding `agent` to the issue:

- **Submit a code review**: comment or request changes, with or without inline comments. An
  approval only counts if it has a summary. Each review triggers one run; the runner records the
  reviews it has handed to a run in `~/.agent-runner/reviews-seen`. Replying to an inline thread
  outside a review submits a one-comment review, so that triggers a run too.
- **Add the `agent` label to the PR**, for comments you left in the PR's discussion thread. The
  runner removes the label when it picks the PR up.

The run happens in the issue's worktree on the same branch. The agent gets the issue thread plus
the PR's discussion, reviews and inline review threads, with the diff lines they're on. Resolved
and outdated threads are marked, and so are reviews it hasn't seen before. It pushes a revision to
the PR as usual. Status labels still go on the issue only, but a run you asked for on the PR also
posts its reply, question or failure as a PR comment.

Only reviews from people with write access to the repo (owner, member, collaborator) count, and
unsubmitted draft reviews are ignored. A PR on any other branch isn't picked up, labeled or not:
the branch name is what ties a PR to its issue and worktree.

## Read the PR the agent opens

PR descriptions and comments are written for skimming:

- **Above the fold:** a sentence or two on what the change does, then **Audit** (the steps to
  check it by hand), and rarely anything else you must know to review it properly.
- **Below a rule**, in stripped-down language: **Code changes**, **Agent-run verification** and
  **Agent decisions**.

The agent is told to decide rather than stop. When the issue is ambiguous about details (naming,
copy, layout, approach, edge cases), it picks what fits the existing code, finishes, and lists its
judgment calls under **Agent decisions**, so you can push back in review. It stops with
`needs_human` only as a last resort: the goal is too unclear for any implementation to be likely
right, it needs access or setup it doesn't have, or it faces an irreversible or high-risk choice
(data deletion, breaking public APIs, security, billing) the issue doesn't settle. It commits its
progress before stopping, and its question lands in an issue comment.

The agent reports its outcome as `--json-schema` structured output (`status`, `summary`,
`decisions`, `question`), so the script never parses free text. To change these rules, edit the
prompt in `agent-runner`: "Making decisions" sets how readily it stops, and the "Writing ..."
section sets the PR layout.

## RUNNER-AGENTS.md

Each watched repo can have a committed `RUNNER-AGENTS.md` at its root: what runner agents have
learned about working in that repo unattended, such as tool limits, commands that don't work, and
how you want to verify changes. Agents read it before starting. When a run teaches them something
a future run would otherwise rediscover, often from your feedback in issue comments, they add it
and commit it with their change, so you review it in the PR. See
[`../RUNNER-AGENTS.md`](../RUNNER-AGENTS.md) for this repo's.

## How a run works

1. For each checkout in `~/.agent-runner/repos`, list open issues labeled `agent`, plus the
   issues of open `agent/issue-N` PRs that are labeled `agent` or have a new code review.
2. Swap the label to `agent-wip`, so the next run doesn't pick the issue up again.
3. Reuse or create the issue's worktree, `~/.agent-runner/worktrees/<repo>-N`, on the
   `agent/issue-N` branch. It starts at `origin/agent/issue-N` if that exists, otherwise at
   `origin/<default branch>`. The main checkout, and any interactive session in it, stays
   untouched.
4. Symlink the untracked files listed for that repo (`.env`, tokens) from the main checkout into
   the worktree.
5. Run `claude -p` with the issue title, body and comments, plus the open PR's discussion and
   review comments if there is one. The agent can edit files, run project tooling and commit, but
   can't push (see `ALLOWED_TOOLS` in the script).
6. Push any commits, open or update the PR (`Closes #N`, the summary and decisions), and set the
   final label with a comment. If the push or PR step fails, the issue gets `agent-failed` with
   the error. The commits stay in the worktree, and the next run continues from them instead of
   resetting to origin.

A lock file keeps runs from overlapping.

Worktrees stay until their issue is closed (merging a PR with `Closes #N` closes it). Dependencies
installed in a worktree survive between runs, and you can run the branch from the worktree while
you review. Each run removes the worktrees and local branches of closed issues.

## Runtime directory

Everything machine-specific lives in one untracked directory, `~/.agent-runner/`. It stays out of
this public repo because it names private repos, and the logs can contain secrets the agent read.

```
~/.agent-runner/
  repos        # checkouts to watch + untracked files to link (from repos.example)
  cron.log     # one line per run
  crontab      # copy of the installed cron entry, read by the dashboard
  logs/        # full JSON output of each issue run
  reviews-seen # PR code reviews already handed to a run
  worktrees/   # <repo>-N checkouts of agent/issue-N, kept until the issue is closed
  lock
```

Set `AGENT_RUNNER_HOME` to use a different directory.

The devbox [dashboard](../ec2/README.md#dashboard) shows queued issues, the current run, recent
runs and the `cron.log` tail.

## Files

| Repo path | Installed as | Notes |
|---|---|---|
| `agent-runner` | `~/bin/agent-runner` (symlink) | The runner. Cron calls the repo path directly; the symlink is for running it by hand |
| `crontab` | User crontab, between `# BEGIN agent-runner` and `# END agent-runner` | Every 15 minutes. Sets `PATH`, since cron doesn't load `.zshrc`. `install.sh` fills in `$HOME` and this folder's path |
| `repos.example` | `~/.agent-runner/repos` (copied once, never overwritten) | Template for the list of checkouts to watch |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `install.sh` stops with `crontab not found` | Install cron (see [prerequisites](#set-it-up)), then re-run `install.sh` |
| `No config at ~/.agent-runner/repos` | Run `install.sh`, or copy `repos.example` there |
| A labeled issue is never picked up | Check `~/.agent-runner/cron.log`. If it's empty, check that `crond` is running (`systemctl status crond`) and `crontab -l` has the `agent-runner` block. If the issue has `agent-wip`, a run is still working on it or one died; to requeue it, remove `agent-wip` and add `agent` |
| `Another run is in progress, exiting.` | A run is still going; the next tick tries again |
| `agent-failed` mentioning `.github/workflows/` | The branch changes a workflow file, which GitHub only accepts from a token with the `workflow` scope. Add that scope to the runner's token, then re-add `agent` |
| A PR comment didn't trigger a run | Comments in the PR's discussion thread need the `agent` label on the PR. Reviews must come from someone with write access, and the PR's branch must be `agent/issue-N` |
| You want to see exactly what the agent did | Full JSON output is in `~/.agent-runner/logs/<repo>-<N>-<timestamp>.json`; the worktree is `~/.agent-runner/worktrees/<repo>-<N>` |

## Security

The issue text is a prompt to an agent that runs shell commands next to your secrets. Adding a
label needs triage or write access, so outsiders can't queue work. But read any issue text or
comment someone else wrote before you label it: a resumed run reads every comment on the issue,
and every comment and review on its PR. A code review only triggers a run when its author has
write access, but once a run starts it reads the whole PR thread, whoever wrote it.

## Why local cron, not Claude routines

Claude Code routines have built-in triggers (schedule, an HTTP `/fire` endpoint, GitHub events)
and can run on a [self-hosted runner](https://code.claude.com/docs/en/self-hosted-environments.md).
But each run does a fresh clone into the runner's own working directory and deletes it after, so
untracked secrets have to be injected per session (a wrapper script or environment variables).
Running [`claude -p`](https://code.claude.com/docs/en/headless.md) locally reuses the checkouts
that already have their secrets. Revisit routines if runs should be visible in claude.ai/code or
triggered by GitHub events instead of polling.

## To do

- [ ] **Loosen how a PR is tied to its issue.** Today the only link is the branch name: a PR is
  picked up only if its head branch is `agent/issue-N`, and N is read from that name
  (`pr_triggers` in `agent-runner`). A PR you opened yourself on any other branch is ignored
  even with the `agent` label and a linked issue (e.g. PR #25 on `runner-headless-browser` for
  issue #31). Refactor so the issue can also be resolved from GitHub's own links (the PR's
  `closingIssuesReferences`, i.e. "Closes #N" or the Development sidebar), and have the run
  use the PR's actual head branch for the worktree and push rather than assuming
  `agent/issue-N`. Decide what to do when a PR links no issue or several.
