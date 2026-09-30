#!/bin/bash
# Installs the dashboard as a systemd service on any Linux box with python3.
#   sudo bash install.sh [--user dev] [--port 9999] [--bind 0.0.0.0]
#   sudo bash install.sh --uninstall
# Files are copied to a root-owned dir, so the service never runs code from
# the user's writable checkout. Re-run after pulling changes.
set -euo pipefail

SERVICE=devbox-dashboard
LIB=/usr/local/lib/devbox-dashboard
UNIT=/etc/systemd/system/$SERVICE.service
RUN_USER=${SUDO_USER:-}
PORT=9999
BIND=0.0.0.0
UNINSTALL=0

while (( $# )); do
  case $1 in
    --user) RUN_USER=$2; shift 2 ;;
    --port) PORT=$2; shift 2 ;;
    --bind) BIND=$2; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

(( EUID == 0 )) || { echo "run with sudo" >&2; exit 1; }

if (( UNINSTALL )); then
  systemctl disable --now "$SERVICE" 2>/dev/null || true
  rm -f "$UNIT"
  rm -rf "$LIB"
  systemctl daemon-reload
  echo "==> $SERVICE removed"
  exit 0
fi

# Running as the login user lets the ports table map that user's listening
# sockets (dev servers) to processes; root would see all, but a web server
# reachable over the network shouldn't run as root.
[[ -n $RUN_USER && $RUN_USER != root ]] || { echo "pass --user <login user> (not root)" >&2; exit 1; }
id "$RUN_USER" >/dev/null
PYTHON=/usr/bin/python3
[[ -x $PYTHON ]] || { echo "$PYTHON missing" >&2; exit 1; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
install -d -m 755 "$LIB"
install -m 644 "$here/server.py" "$here/index.html" "$LIB/"

cat > "$UNIT" <<EOF
[Unit]
Description=devbox dashboard (http://$BIND:$PORT)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$RUN_USER
Environment=DASHBOARD_BIND=$BIND DASHBOARD_PORT=$PORT
ExecStart=$PYTHON $LIB/server.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
sleep 1
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 20 --no-pager; exit 1; }

# The devbox firewall only admits tailscale0; elsewhere 0.0.0.0 may be public.
if [[ $BIND == 0.0.0.0 ]] && ! nft list table inet devbox >/dev/null 2>&1; then
  echo "!!! WARNING: listening on all interfaces and no devbox firewall found."
  echo "    Unless a firewall/security group blocks port $PORT, re-run with --bind 127.0.0.1"
  echo "    and browse through an SSH tunnel: ssh -L $PORT:localhost:$PORT <host>"
fi
echo "==> $SERVICE running as $RUN_USER: http://$(hostname -s):$PORT"
