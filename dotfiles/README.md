# dotfiles

zsh, tmux and nvim config shared by the laptop (macOS) and the devbox (AL2023 arm64),
so both look and behave the same. Files here are symlinked into `$HOME`: editing
`~/.zshrc` edits the repo.

```bash
~/dev/devbox/dotfiles/install.sh     # link, install tools and plugins; safe to re-run
```

The devbox runs it automatically as the last bootstrap step (cloning this repo, which
must be pushed first). On an existing devbox: `cd ~/devbox && git pull && dotfiles/install.sh`.

## What's shared

| Repo path | Linked to | Notes |
|---|---|---|
| `zsh/.zshrc` | `~/.zshrc` | Prompt (git branch + worktree indicator, Nerd Font icons), aliases, history, fnm, mise |
| `tmux/.tmux.conf` | `~/.tmux.conf` | Prefix `C-Space`, `\|`/`-` splits, Catppuccin mocha via TPM, truecolor, OSC 52 clipboard |
| `nvim/` | `~/.config/nvim` | kickstart.nvim (MIT, see `nvim/LICENSE.md`) with local changes; `nvim-pack-lock.json` pins plugins |
| `mise/global.toml` | `~/.config/mise/config.toml` | Exact version pins: neovim, ripgrep, fd, fzf, tree-sitter (Amazon's linux distro, AL2023, packages none of these). Since versions are pinned, update this mise file and reinstall, see comments in the config |

`install.sh` moves anything already in the way to `~/.dotfiles-backup/<timestamp>/`.

## Machine-specific and secret: never in this repo

**This repo is public.** Anything secret or machine-specific goes in untracked files that the
shared config loads if present:

| File | Laptop | Devbox |
|---|---|---|
| `~/.zshrc.local` (mode 600) | API keys, AWS_PROFILE, nvm, pyenv, bun, Postgres | not needed |
| `~/.tmux.local.conf` | battery plugin + status segment | `prefix C-a` (the bootstrap writes it), so nested tmux over SSH doesn't clash with the laptop's `C-Space` |
| `~/.config/mise/conf.d/local.toml` | `ruby = "3"` | not needed |

## Changing things

- **Tool versions:** bump the pin in `mise/global.toml`, then `mise install` on each machine.
- **nvim plugins:** `:lua vim.pack.update()`, review, commit the updated `nvim-pack-lock.json`, then `git pull` + open nvim on the other machine.
- **Terminal font:** icons render on the laptop's terminal (Nerd Font); the devbox needs no fonts.
