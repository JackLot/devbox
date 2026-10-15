# dotfiles

zsh, tmux and nvim config shared by the laptop (macOS) and the devbox (Amazon Linux 2023,
arm64), so both machines look and behave the same. `install.sh` symlinks these files into your
home directory, so editing `~/.zshrc` edits the file in the repo.

## Install

**Prerequisites:** git and curl, and this repo cloned (`~/dev/devbox` on the laptop, `~/devbox`
on the devbox). `install.sh` installs everything else, including nvim itself.

**On the devbox** you don't need to do anything: the bootstrap clones this repo to `~/devbox` and
runs `install.sh` as its last step. To pick up changes on an existing devbox:

```bash
cd ~/devbox && git pull && dotfiles/install.sh
```

**On the laptop:**

```bash
~/dev/devbox/dotfiles/install.sh
```

The script is safe to re-run. It:

1. Links each file in the table below into `$HOME`. Anything already at that path moves to
   `~/.dotfiles-backup/<timestamp>/`.
2. Installs [mise](https://mise.jdx.dev) if missing, then the tool versions pinned in
   `mise/global.toml`.
3. Installs tmux plugins through TPM and nvim plugins from `nvim/nvim-pack-lock.json`.

It ends with `==> done. Open a new shell (or: exec zsh)`.

### Check that it worked

Open a new shell (`exec zsh`), then:

- The prompt shows the git branch, with a worktree tag inside a git worktree.
- `tmux` shows the Catppuccin status bar.
- `nvim` opens with your plugins. Language servers finish installing on the first launch.

## What's shared

| Repo path | Linked to | What it sets |
|---|---|---|
| `zsh/.zshrc` | `~/.zshrc` | Prompt (git branch, worktree indicator, Nerd Font icons), aliases, history, fnm, mise |
| `tmux/.tmux.conf` | `~/.tmux.conf` | Prefix `C-Space`, `\|` and `-` splits, Catppuccin mocha theme via TPM, truecolor, OSC 52 clipboard |
| `nvim/` | `~/.config/nvim` | [kickstart.nvim](https://github.com/nvim-lua/kickstart.nvim) (MIT, see `nvim/LICENSE.md`) with local changes; `nvim-pack-lock.json` pins plugin versions |
| `mise/global.toml` | `~/.config/mise/config.toml` | Exact versions of neovim, ripgrep, fd, fzf and tree-sitter, which Amazon Linux 2023 doesn't package |

tree-sitter is installed on macOS only: its Linux arm64 builds need a newer glibc than Amazon
Linux 2023 has. On the devbox, nvim uses the parsers it already has and skips compiling new ones.

## Keep secrets and machine-specific settings out of the repo

**This repo is public.** Put anything secret or specific to one machine in these untracked files.
The shared config loads each one if it exists:

| File | On the laptop | On the devbox |
|---|---|---|
| `~/.zshrc.local` (mode 600) | API keys, `AWS_PROFILE`, nvm, pyenv, bun, Postgres | Not needed |
| `~/.tmux.local.conf` | Battery plugin and status segment | `prefix C-a` and `prefix2 C-Space`, written by the bootstrap, so `C-a` reaches the devbox's tmux when it runs inside the laptop's tmux over SSH |
| `~/.config/mise/conf.d/local.toml` | `ruby = "3"` | Not needed |

## Change things

- **Bump a tool version:** edit its pin in `mise/global.toml`, commit, then run `mise install` on
  each machine.
- **Update nvim plugins:** run `:lua vim.pack.update()` in nvim, review the changes, and commit
  the updated `nvim-pack-lock.json`. On the other machine, `git pull` and open nvim.
- **Fonts:** icons render in the laptop's terminal, which needs a Nerd Font. The devbox needs no
  fonts.

## Troubleshooting

| Symptom | Fix |
|---|---|
| A file you had before is gone | `install.sh` moved it to `~/.dotfiles-backup/<timestamp>/` |
| Prompt icons show as boxes | Set a Nerd Font in the laptop's terminal |
| Over SSH from Ghostty: no prompt colors, tmux says `missing or unsuitable terminal` | Add `shell-integration-features = ssh-env,ssh-terminfo` to Ghostty's config and reconnect ([`ec2/CHECKLIST.md`](../ec2/CHECKLIST.md) section 9) |
| A tool is missing after a version bump | `mise install` |
