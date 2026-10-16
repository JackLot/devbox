#!/usr/bin/env bash

# Links each skill in this folder into ~/.claude/skills/ so every Claude Code session on the
# machine (interactive, subagents, agent-runner) can use it, and installs the npm dependencies
# of skills that have a package.json. Safe to re-run. Anything already in the way is moved to
# ~/.dotfiles-backup/.
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/.claude/skills"
BACKUP="$HOME/.dotfiles-backup/$(date +%Y%m%d-%H%M%S)"

log() { echo "==> $*"; }

mkdir -p "$DEST"
for skill in "$DIR"/*/; do
  skill=${skill%/}
  name=$(basename "$skill")
  [[ -f $skill/SKILL.md ]] || continue

  dst="$DEST/$name"
  if [[ ! -L $dst || "$(readlink "$dst")" != "$skill" ]]; then
    if [[ -e $dst || -L $dst ]]; then
      mkdir -p "$BACKUP"
      mv "$dst" "$BACKUP/"
      log "moved existing $dst to $BACKUP/"
    fi
    ln -s "$skill" "$dst"
    log "linked $dst"
  fi

  # A package's postinstall script fetches anything else it needs (e.g. a browser build)
  if [[ -f $skill/package-lock.json ]]; then
    log "installing dependencies for $name"
    npm ci --prefix "$skill" --no-audit --no-fund --loglevel=error
  fi
done

log "done"
