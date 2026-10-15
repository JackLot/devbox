# EC2 devbox

A Graviton (arm64) EC2 instance for running coding agents and dev servers while your laptop is
closed. You reach it only over Tailscale, and it hibernates itself after 60 idle minutes, so you
pay only for the hours it does work. Hibernation saves RAM to disk: when the box wakes, agents,
tmux sessions and dev servers carry on where they stopped.

To launch and verify one, work through [CHECKLIST.md](CHECKLIST.md).

## Everyday use

After setup, these commands cover most of what you do. Run them on the laptop unless the table
says otherwise.

| To | Run |
|---|---|
| Connect (wakes the box if it's hibernated) | `ssh devbox` |
| Open a dev server from the laptop or phone | Bind the server to `0.0.0.0` and browse `http://devbox:<port>` from any device on your tailnet |
| Start or resume the box without connecting | `devbox up` |
| Hibernate now | `devbox down` |
| Stop fully, discarding RAM (needed to change instance type) | `devbox stop` |
| Check state and instance type | `devbox status` |
| Open an admin shell with sudo | `devbox ssm` |
| Keep the box awake until you say otherwise | `devbox-idle pause` on the devbox; `devbox-idle resume` to undo, `devbox-idle status` to check |

When your AWS SSO session has expired, `ssh devbox` and `devbox` open a browser sign-in and then
carry on. Waking from hibernation takes up to a few minutes; the helper prints
`still waiting (30s)` every 30 seconds until sshd answers.

## Edit from Cursor (Remote-SSH)

Cursor edits files on the box directly over Remote-SSH, so there is no local copy to keep in
sync. The editor UI runs on the laptop; files, terminal, language servers and git all run on the
devbox.

1. Add the `Host devbox` block from [`laptop/ssh_config`](laptop/ssh_config) to `~/.ssh/config`.
   Remote-SSH uses the system `ssh`, so connecting wakes the box.
2. In Cursor settings, set `remote.SSH.connectTimeout` to `300`. The default 15 seconds is too
   short: the helper waits up to 300 seconds for sshd after a wake, and an expired SSO session
   adds a browser sign-in first.
3. Command Palette > **Remote-SSH: Connect to Host** > `devbox`. The first connection installs
   Cursor's server into `~/.cursor-server` (linux-arm64).
4. **File > Open Folder** > a path under `/home/dev`.

An open Cursor window holds an SSH connection, which counts as activity, so the box won't
hibernate while one is open. Close the remote window or quit Cursor when you're done. If the
laptop sleeps instead, sshd drops the dead connection within about 3 minutes.

## Dashboard

An optional web page at `http://devbox:9999` that shows what the box is doing. Install it from an
admin shell (`devbox ssm`):

```bash
sudo bash /home/dev/devbox/ec2/dashboard/install.sh --user dev
```

Expected output ends with `==> devbox-dashboard running as dev: http://<hostname>:9999`. The
service runs a root-owned copy of the files, never the checkout, so re-run the command after you
pull dashboard changes. `--port` and `--bind` change where it listens; `--uninstall` removes it.
It works on any Linux machine with python3.

What it shows:

- **Agent sessions**: one row per Claude Code session with its title, state (working, needs
  input, idle), current tool call or last reply, directory and branch. Click a row to follow its
  transcript live.
- **CPU, memory and disk** tiles. Click the disk tile for the largest directories, worktrees and
  files under the home directory (one `du` pass when the modal opens, cached for a minute).
- **Listening ports** and a collapsible list of **top processes**, each with a Stop button.
- **Auto-hibernate** pill in the header. Click it for the countdown, the idle log tail, **Pause
  auto-hibernate** and **Hibernate now**.
- **Issues** for the [agent runner](../agent-runner/), shown when `~/.agent-runner` exists: the
  current run, open issues with an `agent*` label (state, PR, last run; refreshed from GitHub once
  a minute), recent runs with their full summary and log, the `cron.log` tail and a countdown to
  the next cron tick. Click an issue for its labels, worktree, branch and links. While issues are
  queued, the card offers an `agent-runner` command to copy and run; the dashboard can't start a
  run itself, since it has read-only access to your home directory.

Who can see and do what:

- Anyone on your tailnet can see process command lines and Claude prompts and replies.
- Stop buttons send SIGTERM to any `dev` process, Claude sessions included (resume those with
  `claude --resume`). **Hibernate now** hibernates the box through the instance role and logs
  `dashboard request, hibernating` to the idle log.
- Stop, hibernate, full session transcripts and run logs only answer requests from the
  dashboard's own page: a custom header, same origin, and a known Host. Add extra hostnames with
  the `DASHBOARD_HOSTS` environment variable.

## How it works

| Concern | How |
|---|---|
| Inbound exposure | Security group with **zero inbound rules**, plus an nftables input policy that only accepts `tailscale0` |
| Everyday access | `ssh devbox` over Tailscale as `dev`: key-only, no sudo, agent forwarding refused |
| Admin access | `devbox ssm` opens an SSM Session Manager shell as `ssm-user`, who has sudo. IAM authenticates it; no port 22 needed |
| Waking up | `ssh devbox` runs `laptop/devbox proxy`, which signs in to SSO if needed, starts the instance and waits for sshd |
| Idle detection | `devbox-idle.timer` checks every 5 minutes. After 60 idle minutes the box calls `ec2:StopInstances --hibernate` on itself |
| What counts as active | A Claude Code heartbeat in the last 5 minutes (from managed hooks), an open SSH session, or a 5-minute load average above 25% of the cores |
| Pausing auto-hibernate | `devbox-idle pause` (or the dashboard button) creates the flag file `/var/lib/devbox-activity/paused`. The pause lasts until you resume, across hibernation and reboots. **Hibernate now** and `devbox down` still work while paused |
| Memory | zram (priority 100), then `/pagefile` (priority 10). `/swap` belongs to `ec2-hibinit-agent` and holds only the hibernation image; no other swap file may have `/swap` in its path, because the agent matches that substring |
| Updates | `devbox-update.timer` runs `dnf --releasever=latest upgrade` daily. Amazon Linux 2023 repos otherwise stay pinned to the AMI's release |
| Secrets at boot | The bootstrap reads the Tailscale auth key from SSM Parameter Store (`/devbox/tailscale-authkey`), never from user-data |

## Files

| File | Purpose |
|---|---|
| [`CHECKLIST.md`](CHECKLIST.md) | Account hardening, launch, verification, resizing, teardown |
| [`bootstrap.sh`](bootstrap.sh) | Self-contained EC2 user-data for Amazon Linux 2023 arm64. Idempotent: re-run it with `sudo bash` after edits |
| [`iam/instance-trust.json`](iam/instance-trust.json) | Lets EC2 assume the instance role |
| [`iam/instance-policy.json`](iam/instance-policy.json) | Instance role: hibernate itself and read `/devbox/*` parameters (plus the managed `AmazonSSMManagedInstanceCore` policy) |
| [`iam/laptop-policy.json`](iam/laptop-policy.json) | `DevboxOperator` permission set, the laptop's everyday access: start, stop and describe the devbox, open SSM sessions |
| [`iam/admin-no-launch-policy.json`](iam/admin-no-launch-policy.json) | Deny added to `AdministratorAccess` after launch, so nobody can launch new instances until you deliberately lift it |
| [`laptop/devbox`](laptop/devbox) | Laptop helper: `devbox up`, `down`, `stop`, `status`, `ssm`, `proxy` |
| [`laptop/ssh_config`](laptop/ssh_config) | `Host devbox` block with the wake-on-connect `ProxyCommand` |
| [`dashboard/`](dashboard/) | `server.py` (Python standard library, reads `/proc`), `index.html` and its CSS and JS in `static/`; `install.sh` sets it up as a service |

The bootstrap installs these on the instance:

| Path | What |
|---|---|
| `/usr/local/bin/devbox-idle-check` | Idle detector; hibernates the box |
| `/usr/local/bin/devbox-idle` | `pause`, `resume`, `status` for auto-hibernate (runs as `dev`) |
| `/etc/devbox/idle.conf` | `IDLE_MINUTES` and `IDLE_HIBERNATE=on/off`. A bootstrap re-run doesn't overwrite it |
| `/var/log/devbox-idle.log` | Idle checker decisions and dashboard hibernations, mode 664, group `dev`. Also in `journalctl -t devbox-idle`, which `dev` can't read |
| `/etc/claude-code/managed-settings.d/50-devbox-heartbeat.json` | Claude Code hooks that touch `/var/lib/devbox-activity/claude` |
| `/etc/nftables/devbox.nft`, `devbox-firewall.service` | Host firewall, in its own table |
| `/etc/ssh/sshd_config.d/01-devbox.conf` | sshd hardening |
| `/etc/systemd/zram-generator.conf`, `/pagefile` | Memory overflow at runtime |
| `devbox-update.timer`, `devbox-idle.timer` | Daily updates, idle checks |
| `/var/log/devbox-bootstrap.log` | Bootstrap output |

## Design decisions

- **Amazon Linux 2023, not Ubuntu.** AWS supports hibernation on Graviton for Amazon Linux 2023
  and Ubuntu 20.04/22.04 only. Ubuntu 24.04 isn't on the list, and the supported Ubuntu releases
  also recommend disabling KASLR. Amazon Linux 2023 ships `ec2-hibinit-agent`, the AWS CLI and the
  SSM agent in the standard AMI.
- **arm64 (Graviton).** About 10-20% cheaper than x86 at the same size, and the same architecture
  as Apple Silicon. Browser testing works through Playwright's Chromium, tested with the libraries
  the bootstrap installs. Google Chrome and Puppeteer's default Chrome download have no Linux arm64
  build.
- **Hibernate, never plain stop.** RAM is saved to the encrypted root volume, so agents, tmux and
  dev servers resume where they were. That's what makes a simple idle timer safe.
- **The SSH user has no sudo.** Whatever an agent can do, it does as `dev`. Root-level changes go
  through SSM, which IAM authenticates and CloudTrail logs.
- **Heartbeat hooks live in managed settings.** Every Claude Code session on the box gets them,
  and neither you nor an agent can drop them from `~/.claude/settings.json` by accident.
- **The instance role is nearly empty.** Any process on the box can use it, so it can only
  hibernate this instance and read `/devbox/*` parameters.

## Known limits

- A single tool call that runs longer than the idle window with low CPU, such as a slow download,
  can be hibernated mid-flight. It resumes on wake; raise `IDLE_MINUTES` in
  `/etc/devbox/idle.conf` if this bites.
- A browser tab left open on a dev server doesn't keep the box awake, by design. To wake the box
  for the browser alone, run `devbox up`.
- EC2 user-data is capped at 16 KB (16,384 bytes), and `bootstrap.sh` is now over it (about
  17.5 KB). Launch with a gzipped copy, which cloud-init accepts; [CHECKLIST.md section
  7](CHECKLIST.md#7-launch) shows how. Keep its comments short.
- The laptop helper expects exactly one non-terminated instance tagged `Name=devbox`.

## Troubleshooting

See the symptom table in [CHECKLIST.md section 14](CHECKLIST.md#14-troubleshooting). If you're
locked out of SSH, `devbox ssm` still works: it needs no inbound port and no Tailscale.
