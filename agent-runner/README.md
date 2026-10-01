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
| `agent-pr` | PR opened or updated, or a follow-up question answered in a comment | Review; for changes or questions, comment on the issue and re-add `agent`, or [give feedback on the PR](#feedback-on-the-pr) |
| `agent-needs-human` | Blocked; the agent's question is in an issue comment | Answer in a comment, re-add `agent` |
| `agent-failed` | Run errored, made no commits, or couldn't push or open the PR; the issue comment says why and gives a `cd` command for the worktree | Fix the issue text or the runner, re-add `agent` |

Re-adding `agent` to an issue whose `agent/issue-N` branch already exists resumes on that branch
with the full comment thread, and pushes to the open PR instead of opening a new one. If the
follow-up only needs an answer (say, "how do I run this?"), the agent replies in an issue comment
without committing and the issue goes back to `agent-pr`.

## Feedback on the PR

You don't have to go back to the issue to ask for changes. Either of these on an open
`agent/issue-N` PR queues a run for issue N, the same as re-adding `agent` to the issue:

- **Submit a code review** (comment or request changes, with or without inline comments; an
  approval only counts if it has a summary). Each review triggers one run; the ones already
  handed to a run are recorded in `~/.agent-runner/reviews-seen`. Replying to an inline thread
  outside a review submits a one-comment review, so that triggers a run too.
- **Add the `agent` label to the PR**, for comments left in the PR's discussion thread. The
  runner removes the label when it picks the PR up.

The run happens in the issue's worktree on the same branch, and the agent gets the issue thread
plus the PR's discussion, reviews and inline review threads (with the diff lines they're on;
resolved and outdated threads are marked, reviews it hasn't been given before are marked new).
It pushes a revision to the PR as usual. Status labels still go on the issue only, but a run
you asked for on the PR also posts its reply, question or failure as a PR comment.

Reviews count only from people with write access to the repo (owner, member, collaborator),
and draft reviews you haven't submitted are ignored. A PR on any other branch isn't picked up,
labeled or not: the branch name is what ties a PR to its issue and worktree.

## RUNNER-AGENTS.md

Each watched repo can have a committed `RUNNER-AGENTS.md` at its root: what runner agents have
learned about working in that repo unattended (tool limits, commands that don't work, how you
want to verify changes). Agents read it before starting, and when a run teaches them something
a future run would otherwise rediscover, often from your feedback in issue comments, they add
it and commit it with their change, so it gets reviewed in the PR. See
[`../RUNNER-AGENTS.md`](../RUNNER-AGENTS.md) for this repo's.

## When the agent stops to ask

The prompt tells the agent to bias hard toward deciding: when the issue is ambiguous about
details (naming, copy, layout, approach, edge cases) it picks what fits the existing code,
finishes, and lists its judgment calls under **Agent decisions** in the PR so they get reviewed
there. It returns `needs_human` only as a last resort: the goal is too unclear for any
implementation to be likely right, it needs access or setup it doesn't have, or it faces an
irreversible or high-risk choice (data deletion, breaking public APIs, security, billing) the
issue doesn't settle. It commits progress before stopping, and the question lands in an issue comment.

The agent reports its outcome through `--json-schema` structured output (`status`, `summary`,
`decisions`, `question`), so the script doesn't parse free text. To tune how readily it blocks,
edit the "Making decisions" section of the prompt in `agent-runner`.

PR descriptions and comments are written for skimming. Above the fold: a sentence or two on
what the change does, then **Audit**, the steps to check it by hand, and (rarely) anything
else the reviewer must know to review it properly. Below a rule, in
stripped-down language: **Code changes**, **Agent-run verification** and **Agent decisions**.
The layout and wording rules are the "Writing ..." section of the prompt.

## How a run works

1. For each checkout in `~/.agent-runner/repos`, list open issues labeled `agent`, plus the
   issues of open `agent/issue-N` PRs that are labeled `agent` or have a new code review.
2. Swap the label to `agent-wip` so the next run doesn't pick it up again.
3. Reuse or create the issue's worktree, `~/.agent-runner/worktrees/<repo>-N`, on the
   `agent/issue-N` branch at `origin/agent/issue-N` if it exists, otherwise at
   `origin/<default branch>`. The main checkout (and any interactive session in it) is untouched.
4. Symlink the untracked files listed for that repo (`.env`, tokens, ...) from the main
   checkout into the worktree.
5. `claude -p` with the issue title, body and comments, and the open PR's discussion and
   review comments if there is one. It can edit files, run project
   tooling and commit, but can't push (see `ALLOWED_TOOLS` in the script).
6. The script pushes any commits, then opens or updates the PR (`Closes #N`, the summary and
   decisions), and sets the final label with a comment. If the push or the PR step fails
   (for example, the token lacks the `workflow` scope and the branch touches
   `.github/workflows/`), the issue gets `agent-failed` with the error. The commits stay in
   the worktree, and the next run continues from them instead of resetting to origin.

A lock file means runs never overlap.

Worktrees are kept until their issue is closed (merging a PR with `Closes #N` does that), so
dependencies installed in them survive between runs, and you can run the branch from the
worktree while reviewing. Each run removes the worktrees and local branches of closed issues.

## Runtime directory

Everything machine-specific lives in one untracked directory, `~/.agent-runner/`, kept out of
this public repo because it names private repos and the logs can contain secrets the agent read:

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

## Files

| Repo path | Installed as | Notes |
|---|---|---|
| `agent-runner` | `~/bin/agent-runner` (symlink) | The runner. Cron calls the repo path directly; the symlink is for running it by hand |
| `crontab` | user crontab, between `# BEGIN/END agent-runner` | Every 15 min; sets PATH since cron doesn't load `.zshrc`. `install.sh` fills in `$HOME` and this folder's path |
| `repos.example` | `~/.agent-runner/repos` (copy, never overwritten) | Template for the list of checkouts to watch |

## Security

The issue text is a prompt to an agent that runs shell commands next to your secrets. Adding a
label needs triage/write access, so outsiders can't queue work, but read issues and comments
someone else wrote before labeling (a resumed run reads every comment on the issue, and every
comment and review on its PR). A code review only triggers a run when its author has write
access, but once a run starts it reads the whole PR thread, whoever wrote it.

## Why local cron, not Claude routines

Claude Code routines have built-in triggers (schedule, an HTTP `/fire` endpoint, GitHub
events) and can run on a [self-hosted runner](https://code.claude.com/docs/en/self-hosted-environments.md).
But each run does a fresh clone into the runner's own working directory and deletes it after,
so untracked secrets have to be injected per session (wrapper script or environment variables).
Running [`claude -p`](https://code.claude.com/docs/en/headless.md) locally reuses the checkouts
that already have their secrets. Revisit routines if runs should be visible in claude.ai/code or
triggered by GitHub events instead of polling.
