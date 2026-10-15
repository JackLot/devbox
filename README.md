# devbox: a cloud dev machine for coding agents, plus shared dotfiles

This repo sets up a personal AWS EC2 instance that you reach only over Tailscale. Coding agents
and dev servers keep running on it while your laptop is closed, and it hibernates itself when
idle, so you pay only for the hours it does work. The repo also holds the shell and editor config
that the laptop and the devbox share, and a cron job that turns labeled GitHub issues into pull
requests.

| Path | What it gives you | Start with |
|---|---|---|
| [`ec2/`](ec2/) | The devbox: bootstrap script, IAM policies, SSH and Tailscale access, auto-hibernate, laptop helper, web dashboard | [`ec2/CHECKLIST.md`](ec2/CHECKLIST.md) |
| [`dotfiles/`](dotfiles/) | zsh, tmux and nvim config, identical on the laptop (macOS) and the devbox | [`dotfiles/README.md`](dotfiles/README.md) |
| [`agent-runner/`](agent-runner/) | A cron job on the devbox that has Claude Code implement GitHub issues labeled `agent` and open PRs | [`agent-runner/README.md`](agent-runner/README.md) |

## Set everything up

Do these in order; each step depends on the one before it.

1. **Launch the devbox.** Follow [`ec2/CHECKLIST.md`](ec2/CHECKLIST.md) from section 1. Most of it
   is one-time AWS account and Tailscale setup. When you finish, `ssh devbox`
   wakes the box and logs you in.
2. **Install the dotfiles on your laptop.** The devbox bootstrap already installs them on the
   box. See [`dotfiles/README.md`](dotfiles/README.md).
3. **Optional: start the agent runner** on the devbox. See
   [`agent-runner/README.md`](agent-runner/README.md).

## Where the checkout lives

The docs and scripts assume these paths:

| Machine | Checkout | Why |
|---|---|---|
| Laptop | `~/dev/devbox` | [`ec2/laptop/ssh_config`](ec2/laptop/ssh_config) calls `~/dev/devbox/ec2/laptop/devbox` |
| Devbox | `~/devbox` (user `dev`) | The bootstrap clones the repo there |

If you clone to a different path on the laptop, edit the `ProxyCommand` line in your
`~/.ssh/config` to match.

**This repo is public.** Keep secrets and machine-specific settings in the untracked files the
config loads; [`dotfiles/README.md`](dotfiles/README.md#keep-secrets-and-machine-specific-settings-out-of-the-repo)
lists them.
