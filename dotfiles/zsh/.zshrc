# Shared zsh config for macOS laptop and Linux cloud devbox

# Symlink this file to ~/.zshrc
# Secrets and machine-specific setup go in ~/.zshrc.local (untracked, loaded last)
# REMEMBER: This file is in a PUBLIC repo: don't put secrets here

# ---- PATH -------------------------------------------------------------------
typeset -U path   # drop duplicate PATH entries
path=("$HOME/bin" "$HOME/.local/bin" $path)

# ---- History (macOS sets these in /etc/zshrc; Linux doesn't) -----------------
HISTFILE=~/.zsh_history
HISTSIZE=2000
SAVEHIST=1000

# ---- Keys (emacs keymap; Home/End/Delete from terminfo, as macOS does) --------
bindkey -e
[[ -n ${terminfo[khome]} ]] && bindkey "${terminfo[khome]}" beginning-of-line
[[ -n ${terminfo[kend]} ]]  && bindkey "${terminfo[kend]}"  end-of-line
[[ -n ${terminfo[kdch1]} ]] && bindkey "${terminfo[kdch1]}" delete-char

# ---- Locale: prompt icons need UTF-8 (fixes a C locale over SSH on Linux) ----
if [[ $OSTYPE == linux* && "$(locale charmap 2>/dev/null)" != UTF-8 ]]; then
  export LANG=C.UTF-8
fi

# ---- Tool version managers ----------------------------------------------------
# mise: CLI tools in ~/.config/mise/config.toml (neovim, ripgrep, fd, ...)
command -v mise >/dev/null && eval "$(mise activate zsh)"

# fnm: Node versions (macOS and Linux install locations)
for fnm_dir in "$HOME/Library/Application Support/fnm" "$HOME/.local/share/fnm"; do
  [[ -d $fnm_dir ]] && path=("$fnm_dir" $path)
done
unset fnm_dir
command -v fnm >/dev/null && eval "$(fnm env --use-on-cd --shell zsh)"

# ---- Shortcuts ----------------------------------------------------------------
alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias cc="claude"
alias reload="source ~/.zshrc"

# ---- Prompt -------------------------------------------------------------------
# Load version control information
autoload -Uz vcs_info
precmd() {

  vcs_info 

  # Check if we're in a worktree
  local git_dir=$(git rev-parse --git-dir 2>/dev/null)
  if [[ -n "$git_dir" ]]; then
    local commondir="$git_dir/commondir"
    if [[ -f "$commondir" ]]; then
      WORKTREE_OPEN="%F{magenta}[%f"
      WORKTREE_INDICATOR=" %F{magenta}[ worktree]%f"
    else
      WORKTREE_OPEN=""
      WORKTREE_INDICATOR=""
    fi
  else
    WORKTREE_OPEN=""
    WORKTREE_INDICATOR=""
  fi
}

# Format the vcs_info_msg_0_ variable  %F{215}%f
zstyle ':vcs_info:git:*' formats ' %F{215} %b%f'

setopt PROMPT_SUBST
PS1=$'%F{69}%n%f on %F{cyan}%~%f ${vcs_info_msg_0_}${WORKTREE_INDICATOR} 
\Uf0da '

# Cloud icon at the start of the prompt on the devbox (the bootstrap writes this marker)
[[ -e /var/lib/devbox/bootstrapped ]] && PS1=$'%F{117}\Uf0c2%f '"$PS1"

# ---- Machine-specific settings and secrets (untracked) -------------------------
[[ -r ~/.zshrc.local ]] && source ~/.zshrc.local
