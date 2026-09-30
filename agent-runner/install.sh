#!/usr/bin/env bash

# Sets up agent-runner: creates ~/.agent-runner (repo list, logs, worktrees), links the
# script into ~/bin for interactive use, and installs the cron entry. Safe to re-run.
# Needs: cron (cronie), gh (logged in), claude (logged in), jq, flock.
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
HOME_DIR="$HOME/.agent-runner"
CONFIG="$HOME_DIR/repos"
MARK_BEGIN="# BEGIN agent-runner"
MARK_END="# END agent-runner"

log() { echo "==> $*"; }

# Script: Add a symlink so `agent-runner` works from any shell (cron calls the repo path directly)
# /bin/ is already in the PATH, so this symlink will allow the 'agent-runner' command to be
# run from anywhere, instead of just this repo.
#
# This block also handles the case where the symlink already exists but points to the wrong location,
# in which case it moves the existing symlink to a backup location and creates a new one.
dst="$HOME/bin/agent-runner"
mkdir -p "$HOME/bin" "$HOME_DIR"
if [[ ! -L $dst || "$(readlink "$dst")" != "$DIR/agent-runner" ]]; then
  if [[ -e $dst || -L $dst ]]; then
    backup="$HOME/.dotfiles-backup/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup"
    mv "$dst" "$backup/"
    log "moved existing $dst to $backup/"
  fi
  ln -s "$DIR/agent-runner" "$dst"
  log "linked $dst"
fi

# Repo list: machine-specific, never overwritten
# This block just copies the example file into the /repos/ subdirectory
# so the user can edit it to list their checkouts.
if [[ ! -f $CONFIG ]]; then
  cp "$DIR/repos.example" "$CONFIG"
  log "created $CONFIG: edit it to list your checkouts"
fi

# Cron entry: replace whatever is between the markers, keep the rest of the crontab
# this is necessary because the crontab is shared, so to make sure this script is idempotent
# we need to replace the existing entry with the new one, and without these markers, the
# install script wouldn't know what was safe to replace.
if ! command -v crontab >/dev/null; then
  log "crontab not found; install cron first (AL2023: sudo dnf install -y cronie && sudo systemctl enable --now crond), then re-run"
  exit 1
fi
block=$(
  echo "$MARK_BEGIN"
  sed -e "s|@HOME@|$HOME|g" -e "s|@DIR@|$DIR|g" "$DIR/crontab" | grep -v '^#'
  echo "$MARK_END"
)
{
  { crontab -l 2>/dev/null || true; } | sed "/^$MARK_BEGIN\$/,/^$MARK_END\$/d"
  echo "$block"
} | crontab -
# Copy for the dashboard: its service runs with NoNewPrivileges, which stops the
# setuid crontab binary from reading the spool, so `crontab -l` fails there
echo "$block" > "$HOME_DIR/crontab"
log "installed cron entry (crontab -l; copy in $HOME_DIR/crontab)"

# Headless browser for agents' visual checks (browser/check.mjs): Playwright in
# browser/node_modules, Chromium in ~/.cache/ms-playwright. Its system libraries come
# from ec2/bootstrap.sh (`npx playwright install-deps` is apt-only).
if command -v npm >/dev/null; then
  (cd "$DIR/browser" && npm ci --silent && npx playwright install chromium >/dev/null) \
    && log "installed Playwright Chromium for browser/check.mjs" \
    || log "warning: Playwright setup failed; agents can't take screenshots"
else
  log "warning: npm not on PATH; skipping the headless browser (browser/check.mjs)"
fi

# Checks that the required CLI tools are available on the PATH
for tool in gh claude jq flock; do
  command -v "$tool" >/dev/null || log "warning: $tool not on PATH"
done

# Checks that github and claude are logged in
gh auth status >/dev/null 2>&1 || log "warning: gh is not logged in (gh auth login)"
[[ "$(claude auth status 2>/dev/null | jq -r .loggedIn 2>/dev/null)" == "true" ]] \
  || log "warning: claude is not logged in (claude auth login)"

log "done. Try: agent-runner --dry-run"
