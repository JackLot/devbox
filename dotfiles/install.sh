#!/usr/bin/env bash

# Links the dotfiles into $HOME and installs what they need (macOS or Linux).
# Safe to re-run. Anything already in the way is moved to ~/.dotfiles-backup/.
set -euo pipefail

# Start by backing up existing dotfiles
DOT=$(cd "$(dirname "$0")" && pwd)
BACKUP="$HOME/.dotfiles-backup/$(date +%Y%m%d-%H%M%S)"

log() { echo "==> $*"; }

# link <path in dotfiles> <path in $HOME>
link() {
  local src="$DOT/$1" dst=$2
  if [[ -L $dst && "$(readlink "$dst")" == "$src" ]]; then
    return 0
  fi
  if [[ -e $dst || -L $dst ]]; then
    mkdir -p "$BACKUP"
    mv "$dst" "$BACKUP/"
    log "moved existing $dst to $BACKUP/"
  fi
  mkdir -p "$(dirname "$dst")"
  ln -s "$src" "$dst"
  log "linked $dst"
}

link zsh/.zshrc          "$HOME/.zshrc"
link tmux/.tmux.conf     "$HOME/.tmux.conf"
link nvim                "$HOME/.config/nvim"
link mise/config.toml    "$HOME/.config/mise/config.toml"

# mise and the tools in mise/config.toml (neovim, ripgrep, fd, fzf, tree-sitter)
if [[ ! -x $HOME/.local/bin/mise ]] && ! command -v mise >/dev/null; then
  log "installing mise"
  curl -fsSL https://mise.run | sh
fi
mise_bin=$(command -v mise || echo "$HOME/.local/bin/mise")
log "installing mise tools"
"$mise_bin" install --yes
eval "$("$mise_bin" activate bash --shims)"

# tmux plugins (TPM installs them without a running tmux server)
if [[ ! -d $HOME/.tmux/plugins/tpm ]]; then
  log "installing tpm"
  git clone --depth 1 https://github.com/tmux-plugins/tpm "$HOME/.tmux/plugins/tpm"
fi
log "installing tmux plugins"
"$HOME/.tmux/plugins/tpm/bin/install_plugins" >/dev/null

# nvim plugins: vim.pack installs everything in the lockfile at startup.
# Language servers (Mason) and treesitter parsers finish on the first real launch.
log "installing nvim plugins"
nvim --headless +qa

log "done. Open a new shell (or: exec zsh)"
