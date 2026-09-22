# EC2 devbox

A Graviton EC2 instance that runs coding agents and dev servers while the laptop
is closed, is reachable only over Tailscale, and hibernates itself when idle so
you pay only for the hours it is doing something.

Start with [CHECKLIST.md](CHECKLIST.md) to launch and verify one.

## How it fits together

| Concern | How |
|---|---|
| Inbound exposure | Security group with **zero inbound rules**, plus an nftables input policy that only accepts `tailscale0` |
| Everyday access | `ssh devbox` over Tailscale as `dev` (key-only, no sudo, agent forwarding refused) |
| Dev servers | Bind to `0.0.0.0`, browse `http://devbox:<port>` from any tailnet device |
| Admin access | `devbox ssm`: SSM Session Manager shell (`ssm-user`, has sudo), IAM-authenticated, no port 22 needed |
| Idle cost | `devbox-idle.timer` checks every 5 min; after 30 idle min it calls `ec2:StopInstances --hibernate` on itself |
| Waking up | `ssh devbox` runs `laptop/devbox proxy`, which starts the instance if needed and waits for sshd |
| "Active" means | Claude Code heartbeat (managed hooks) in the last 5 min, an SSH session, or 5-min load above 25% of cores |
| Memory | zram (priority 100) then `/swapfile` (priority 10). `/swap` is owned by `ec2-hibinit-agent` for the hibernation image only |
| Updates | `devbox-update.timer`: daily `dnf --releasever=latest upgrade` (AL2023 repos are otherwise pinned to the AMI's release) |
| Secrets at boot | Tailscale auth key read from SSM Parameter Store (`/devbox/tailscale-authkey`), never in user-data |

## Files

| File | Purpose |
|---|---|
| [`bootstrap.sh`](bootstrap.sh) | Self-contained EC2 user-data for AL2023 arm64. Idempotent; re-run with `sudo bash` after edits |
| [`CHECKLIST.md`](CHECKLIST.md) | Account hardening, launch, verification, resizing, teardown |
| [`iam/instance-trust.json`](iam/instance-trust.json) | Lets EC2 assume the instance role |
| [`iam/instance-policy.json`](iam/instance-policy.json) | Instance role: hibernate itself, read `/devbox/*` parameters (plus managed `AmazonSSMManagedInstanceCore`) |
| [`iam/laptop-policy.json`](iam/laptop-policy.json) | Optional least-privilege policy for the laptop's AWS profile |
| [`laptop/devbox`](laptop/devbox) | `devbox up / down / stop / status / ssm / proxy` |
| [`laptop/ssh_config`](laptop/ssh_config) | `Host devbox` block with the wake-on-SSH ProxyCommand |

On the instance, the bootstrap installs:

| Path | What |
|---|---|
| `/usr/local/bin/devbox-idle-check` | Idle detector and self-hibernate |
| `/etc/devbox/idle.conf` | `IDLE_MINUTES`, `IDLE_HIBERNATE=on/off` (not overwritten on re-run) |
| `/etc/claude-code/managed-settings.d/50-devbox-heartbeat.json` | Hooks that touch `/var/lib/devbox-activity/claude` |
| `/etc/nftables/devbox.nft` + `devbox-firewall.service` | Host firewall in its own table |
| `/etc/ssh/sshd_config.d/01-devbox.conf` | sshd hardening |
| `/etc/systemd/zram-generator.conf`, `/swapfile` | Runtime memory overflow |
| `devbox-update.timer`, `devbox-idle.timer` | Daily updates, idle checks |
| `/var/log/devbox-bootstrap.log` | Bootstrap output |

## Decisions

- **Amazon Linux 2023, not Ubuntu.** AWS supports Graviton hibernation on AL2023 and Ubuntu 20.04/22.04 only; Ubuntu 24.04 is not on the list, and the supported Ubuntu releases also recommend disabling KASLR. AL2023 ships `ec2-hibinit-agent`, the AWS CLI and the SSM agent in the standard AMI.
- **Hibernate, never plain stop.** RAM is saved to the encrypted root volume, so agents, tmux and dev servers resume exactly where they were. This is what makes a dumb idle timer safe.
- **SSH user has no sudo.** Whatever an agent can do, it does as `dev`. Root-level changes go through SSM, which is authenticated by IAM and logged in CloudTrail.
- **Heartbeat hooks live in managed settings.** Every Claude Code session on the box gets them, and they can't be dropped from `~/.claude/settings.json` by accident or by an agent.
- **Instance role is nearly empty.** Any process on the box can use it, so it can only hibernate this instance and read `/devbox/*` parameters.

## Known limits

- A single tool call that runs longer than the idle window with low CPU (a slow download) can be hibernated mid-flight. It resumes on wake; raise `IDLE_MINUTES` if it bites.
- A forgotten browser tab does not keep the box awake (by design). Waking it for the browser alone: `devbox up`.
- EC2 user-data is capped at 16 KB. `bootstrap.sh` is about 14.5 KB, so keep comments concise; gzip it (cloud-init accepts gzipped user-data) if it outgrows that.
- The laptop helper assumes exactly one non-terminated instance tagged `Name=devbox`.
