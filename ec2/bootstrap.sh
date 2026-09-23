#!/bin/bash
# devbox bootstrap for Amazon Linux 2023 (arm64).
# Runs as EC2 user-data on first boot; safe to re-run: sudo bash bootstrap.sh
# Log: /var/log/devbox-bootstrap.log
set -euo pipefail
exec > >(tee -a /var/log/devbox-bootstrap.log) 2>&1



# ---- SETTINGS ---------------------------------------------------------------
DEV_USER=dev                                   # SSH login + agent user, no sudo
INSTANCE_NAME_TAG=devbox                       # must match iam/*.json and laptop/devbox
TAILSCALE_HOSTNAME=devbox
TAILSCALE_AUTHKEY_PARAM=/devbox/tailscale-authkey
RUNTIME_SWAP_MB=2048                           # disk swap behind zram; ~RAM size
DEFAULT_IDLE_MINUTES=30                        # override in /etc/devbox/idle.conf



# ---- HELPER FUNCTIONS ---------------------------------------------------------------
log()  { echo "==> [$(date -u +%H:%M:%S)] $*"; }
warn() { echo "!!! WARNING: $*"; }

# Instance metadata (IMDSv2): session token + `md <path>` lookup.
imds_token=$(curl -sf -X PUT http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 300')
md() {
  curl -sf -H "X-aws-ec2-metadata-token: $imds_token" \
    "http://169.254.169.254/latest/meta-data/$1"
}



# ---- PREFLIGHT CHECKS ---------------------------------------------------------------
# OS, AWS CLI, SSM agent, hibernation, Name tag.

log "Preflight"

# shellcheck source=/dev/null
. /etc/os-release
[[ "$ID" == amzn && "$VERSION_ID" == 2023 ]] || { echo "Amazon Linux 2023 required"; exit 1; }
command -v aws >/dev/null || { echo "aws CLI missing (use the standard AL2023 AMI, not minimal)"; exit 1; }
systemctl is-enabled --quiet amazon-ssm-agent || warn "amazon-ssm-agent is not enabled"
[[ "$(md hibernation/configured || true)" == true ]] \
  || warn "hibernation is NOT configured for this instance; auto-hibernate will fail. Relaunch with --hibernation-options Configured=true"
[[ "$(md tags/instance/Name || true)" == "$INSTANCE_NAME_TAG" ]] \
  || warn "instance Name tag is not '$INSTANCE_NAME_TAG' (or instance metadata tags are disabled); auto-hibernate IAM and laptop 'devbox' CLI lookup will fail. Tag Name=$INSTANCE_NAME_TAG and set InstanceMetadataTags=enabled"
REGION=$(md placement/region)



# ---- PACKAGES AND DAILY AUTOMATIC UPDATES ----------------------------------------
# AL2023 pins repos to the AMI's release; --releasever=latest gets current updates.

log "Updating packages"
dnf -y --releasever=latest upgrade
# GitHub CLI from GitHub's own repo (also kept current by the daily update)
curl -fsSL https://cli.github.com/packages/rpm/gh-cli.repo -o /etc/yum.repos.d/gh-cli.repo
dnf -y install git gh tmux unzip nftables zram-generator smart-restart
# Libraries Playwright's Chromium needs (`npx playwright install-deps` is apt-only)
dnf -y install atk at-spi2-atk at-spi2-core cups-libs libxcb libxkbcommon libX11 \
  libXext libXcomposite libXdamage libXfixes libXrandr alsa-lib mesa-libgbm cairo pango

cat > /etc/systemd/system/devbox-update.service <<'EOF'
[Unit]
Description=Apply latest Amazon Linux 2023 updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/dnf -y --releasever=latest upgrade
EOF

cat > /etc/systemd/system/devbox-update.timer <<'EOF'
[Unit]
Description=Daily package updates

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF



# ---- DEV USER ---------------------------------------------------------------
# Unprivileged login + agent user; its SSH key comes from the EC2 key pair.

log "Creating user $DEV_USER"

# For zsh: install it, then change /bin/bash to /bin/zsh here.
id "$DEV_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEV_USER"
dev_home=$(getent passwd "$DEV_USER" | cut -d: -f6)

# 700: only the user can enter ~/.ssh
install -d -m 700 -o "$DEV_USER" -g "$DEV_USER" "$dev_home/.ssh"

if pubkey=$(md public-keys/0/openssh-key); then
  auth_keys="$dev_home/.ssh/authorized_keys"
  touch "$auth_keys"
  grep -qxF "$pubkey" "$auth_keys" || echo "$pubkey" >> "$auth_keys"   # add once
  chown "$DEV_USER:" "$auth_keys"
  chmod 600 "$auth_keys"   # 600: only the user can read/write
else
  warn "no EC2 key pair on this instance; add a key to $dev_home/.ssh/authorized_keys manually"
fi



# ---- SSHD -------------------------------------------------------------------
# Only $DEV_USER may SSH in, key-only (no passwords). Admin access is through SSM (ssm-user).

log "Hardening sshd"
cat > /etc/ssh/sshd_config.d/01-devbox.conf <<EOF
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
PermitRootLogin no
AllowUsers $DEV_USER
AllowAgentForwarding no
X11Forwarding no
ClientAliveInterval 60
ClientAliveCountMax 3
EOF

# Validate, reload, then confirm the drop-in actually took effect.
# Output is captured before matching: under pipefail, `cmd | grep -q` fails
# at random when grep exits early and cmd dies of SIGPIPE.
sshd -t
systemctl reload sshd
sshd_effective=$(sshd -T)
grep -qx "allowusers $DEV_USER" <<<"$sshd_effective" || { echo "sshd drop-in not applied"; exit 1; }
grep -qx "passwordauthentication no" <<<"$sshd_effective" || { echo "sshd password auth still on"; exit 1; }



# ---- HOST FIREWALL ----------------------------------------------------------
# Backup for the no-inbound security group: only Tailscale traffic and replies
# to outbound connections reach local services. Own table, so Tailscale's rules
# are never touched.

log "Configuring host firewall"
install -d /etc/nftables

# Inbound default is drop; each rule below is an exception.
cat > /etc/nftables/devbox.nft <<'EOF'
table inet devbox
delete table inet devbox
table inet devbox {
  chain input {
    type filter hook input priority 0; policy drop;
    iif lo accept
    ct state established,related accept
    ct state invalid drop
    iifname "tailscale0" accept
    meta l4proto { icmp, ipv6-icmp } accept
    udp dport { 68, 546 } accept   # DHCP client replies
    udp dport 41641 accept         # Tailscale direct connections
  }
}
EOF

# Loads the ruleset at boot
cat > /etc/systemd/system/devbox-firewall.service <<'EOF'
[Unit]
Description=devbox host firewall
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/nftables/devbox.nft
ExecStop=/usr/sbin/nft delete table inet devbox

[Install]
WantedBy=multi-user.target
EOF



# ---- MEMORY: ZRAM + RUNTIME SWAPFILE ---------------------------------------
# /swap belongs to ec2-hibinit-agent (hibernation image only, swapped off at
# runtime). Runtime swap is zram first, then /swapfile on disk.
log "Configuring zram and runtime swap"

# Config for systemd's zram generator (not a service); applied at boot
cat > /etc/systemd/zram-generator.conf <<'EOF'
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
swap-priority = 100
EOF



swap_bytes=$((RUNTIME_SWAP_MB * 1024 * 1024))
if [[ -f /swapfile && "$(stat -c %s /swapfile)" -ne "$swap_bytes" ]]; then
  swapoff /swapfile 2>/dev/null || true
  rm -f /swapfile
fi
if [[ ! -f /swapfile ]]; then
  # dd rather than fallocate: XFS swapfiles must not contain unwritten extents
  dd if=/dev/zero of=/swapfile bs=1M count="$RUNTIME_SWAP_MB" status=none
  chmod 600 /swapfile
  mkswap /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap defaults,pri=10 0 0' >> /etc/fstab
grep -qx /swapfile <<<"$(swapon --show=NAME --noheadings)" || swapon -p 10 /swapfile



# ---- TAILSCALE --------------------------------------------------------------
# Private network for SSH and dev servers, so the box needs no public inbound ports.

log "Installing Tailscale"

curl -fsSL https://pkgs.tailscale.com/stable/amazon-linux/2023/tailscale.repo \
  -o /etc/yum.repos.d/tailscale.repo
dnf -y install tailscale
systemctl enable --now tailscaled

if tailscale status >/dev/null 2>&1; then
  log "Tailscale already connected"

# Otherwise join with the single-use auth key from SSM Parameter Store
elif authkey=$(aws ssm get-parameter --region "$REGION" --name "$TAILSCALE_AUTHKEY_PARAM" \
    --with-decryption --query Parameter.Value --output text 2>/dev/null); then
  # Key goes through a temp file so it never shows in the process list.
  # If this fails, join manually over SSM.
  log "Joining tailnet as $TAILSCALE_HOSTNAME"
  keyfile=$(mktemp /run/devbox-tskey.XXXXXX)
  printf '%s' "$authkey" > "$keyfile"
  unset authkey
  tailscale up --auth-key="file:$keyfile" --hostname="$TAILSCALE_HOSTNAME"
  rm -f "$keyfile"
else
  warn "could not read $TAILSCALE_AUTHKEY_PARAM; join manually over SSM: sudo tailscale up --hostname=$TAILSCALE_HOSTNAME"
fi



# ---- IDLE AUTO-HIBERNATE ----------------------------------------------------
# Hibernates the box after IDLE_MINUTES (default 30) without activity.

log "Installing idle auto-hibernate"

install -d -m 755 /etc/devbox /var/lib/devbox-idle
install -d -m 755 -o "$DEV_USER" -g "$DEV_USER" /var/lib/devbox-activity

# Written once; your later edits survive re-runs
[[ -f /etc/devbox/idle.conf ]] || cat > /etc/devbox/idle.conf <<EOF
# Minutes of continuous idleness before the box hibernates.
IDLE_MINUTES=$DEFAULT_IDLE_MINUTES

# Set to off to pause auto-hibernation (e.g. while debugging).
IDLE_HIBERNATE=on
EOF

cat > /usr/local/bin/devbox-idle-check <<'EOF'
#!/usr/bin/env bash

# Hibernates this instance after a sustained idle period.
# Run every 5 minutes by devbox-idle.timer. Decisions: journalctl -t devbox-idle
set -euo pipefail

IDLE_MINUTES=30
IDLE_HIBERNATE=on
if [[ -r /etc/devbox/idle.conf ]]; then
  # shellcheck source=/dev/null
  . /etc/devbox/idle.conf
fi

CHECK_INTERVAL_MIN=5                  # must match devbox-idle.timer
HEARTBEAT_DIR=/var/lib/devbox-activity
STATE_FILE=/var/lib/devbox-idle/count # consecutive idle checks
LOAD_BUSY=$(awk -v n="$(nproc)" 'BEGIN { print n * 0.25 }')
idle_checks=$(( (IDLE_MINUTES + CHECK_INTERVAL_MIN - 1) / CHECK_INTERVAL_MIN ))

# Prints the reason and returns 0 if anything counts as activity.
is_active() {
  # Claude Code hooks touch HEARTBEAT_DIR; +1 min absorbs timer jitter
  # (captured, not piped to grep -q: that races with SIGPIPE under pipefail)
  if [[ -n "$(find "$HEARTBEAT_DIR" -type f -mmin "-$((CHECK_INTERVAL_MIN + 1))" -print -quit)" ]]; then
    echo "agent heartbeat"; return 0
  fi

  # Open SSH session. sshd drops dead ones in ~3 min, but a session left open
  # on an awake laptop keeps the box up; consider a local idle auto-kill.
  if [[ -n "$(ss -Htn state established '( sport = :22 )')" ]]; then
    echo "ssh session"; return 0
  fi

  # Tailscale SSH session
  if pgrep -f 'tailscaled be-child ssh' >/dev/null; then
    echo "tailscale ssh session"; return 0
  fi

  # Load: builds, tests, installs running without an agent
  if awk -v t="$LOAD_BUSY" '{ exit !($2 > t) }' /proc/loadavg; then
    echo "load $(cut -d' ' -f2 /proc/loadavg) > $LOAD_BUSY"; return 0
  fi

  return 1
}

# Paused via idle.conf
if [[ "$IDLE_HIBERNATE" != on ]]; then
  echo 0 > "$STATE_FILE"
  logger -t devbox-idle "auto-hibernate disabled in /etc/devbox/idle.conf"
  exit 0
fi

count=$(cat "$STATE_FILE" 2>/dev/null || echo 0)

if reason=$(is_active); then
  echo 0 > "$STATE_FILE"
  logger -t devbox-idle "active ($reason)"
  exit 0
fi

count=$((count + 1))
logger -t devbox-idle "idle check $count/$idle_checks"

if (( count < idle_checks )); then
  echo "$count" > "$STATE_FILE"
  exit 0
fi

# Reset first: after resume every heartbeat looks stale, and the box must get
# a full idle window before it can hibernate again.
echo 0 > "$STATE_FILE"
sync

# IMDSv2 lookup of this instance's id and region
token=$(curl -sf -X PUT http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
md() { curl -sf -H "X-aws-ec2-metadata-token: $token" \
  "http://169.254.169.254/latest/meta-data/$1"; }

logger -t devbox-idle "idle for $IDLE_MINUTES min, hibernating"

aws ec2 stop-instances --hibernate \
  --region "$(md placement/region)" \
  --instance-ids "$(md instance-id)" >/dev/null
EOF

chmod 755 /usr/local/bin/devbox-idle-check

# Runs the checker every 5 min
cat > /etc/systemd/system/devbox-idle.service <<'EOF'
[Unit]
Description=Hibernate devbox when idle

[Service]
Type=oneshot
ExecStart=/usr/local/bin/devbox-idle-check
EOF

cat > /etc/systemd/system/devbox-idle.timer <<'EOF'
[Unit]
Description=Check devbox idleness every 5 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF

# Heartbeat hooks as managed settings: they apply to every Claude Code session
# on the box and can't be removed from the agent user's own settings.
install -d -m 755 /etc/claude-code/managed-settings.d
beat='touch /var/lib/devbox-activity/claude 2>/dev/null || true'
cat > /etc/claude-code/managed-settings.d/50-devbox-heartbeat.json <<EOF
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "$beat" }] }],
    "PreToolUse":       [{ "matcher": "*", "hooks": [{ "type": "command", "command": "$beat" }] }],
    "PostToolUse":      [{ "matcher": "*", "hooks": [{ "type": "command", "command": "$beat" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "$beat" }] }],
    "SubagentStop":     [{ "hooks": [{ "type": "command", "command": "$beat" }] }]
  }
}
EOF

# 644 (world-readable) is required: dev must read it, and Claude Code refuses to
# start when managed settings are unreadable. Only root can write it.
chmod 644 /etc/claude-code/managed-settings.d/50-devbox-heartbeat.json



# ---- DEV TOOLING (AS THE DEV USER) -----------------------------------------
# Installs fnm, Node LTS and Claude Code for the dev user (tmux comes from dnf above).

log "Installing fnm, Node LTS and Claude Code for $DEV_USER"
bashrc="$dev_home/.bashrc"
if ! grep -q '>>> devbox >>>' "$bashrc"; then
  cat >> "$bashrc" <<'EOF'

# >>> devbox >>>
export PATH="$HOME/.local/bin:$PATH"
FNM_PATH="$HOME/.local/share/fnm"
if [ -d "$FNM_PATH" ]; then
  export PATH="$FNM_PATH:$PATH"
  eval "$(fnm env --use-on-cd --shell bash)"
fi
# <<< devbox <<<
EOF
  chown "$DEV_USER:" "$bashrc"
fi

# shellcheck disable=SC2016  # expands in the dev user's shell, not here
runuser -l "$DEV_USER" -c '
  set -euo pipefail

  if [ ! -x "$HOME/.local/share/fnm/fnm" ]; then
    curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
  fi
  export PATH="$HOME/.local/share/fnm:$PATH"
  eval "$(fnm env --shell bash)"
  fnm install --lts
  fnm default lts-latest
  if [ ! -x "$HOME/.local/bin/claude" ]; then
    curl -fsSL https://claude.ai/install.sh | bash
  fi
'



# ---- ENABLE SERVICES --------------------------------------------------------
log "Enabling services"

systemctl daemon-reload
systemctl enable --now devbox-firewall.service
nft list table inet devbox >/dev/null
systemctl start systemd-zram-setup@zram0.service
systemctl enable --now devbox-update.timer devbox-idle.timer

# Bootstrap timestamp, for debugging
install -d /var/lib/devbox
date -u +%FT%TZ > /var/lib/devbox/bootstrapped
log "Bootstrap complete"
swapon --show
tailscale status --self 2>/dev/null | head -1 || true
