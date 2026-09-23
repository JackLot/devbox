-- [[ Neogit ]]
-- A Magit-inspired git interface for Neovim.
--  https://github.com/NeogitOrg/neogit
--
-- Telescope is already installed by the main config, so Neogit uses it
-- automatically for its selection prompts. No other dependency is required.

vim.pack.add { 'https://github.com/NeogitOrg/neogit' }

local neogit = require 'neogit'
neogit.setup {}

-- Document the key chain for which-key, alongside the `<leader>h` git hunk group.
require('which-key').add { { '<leader>g', group = '[G]it' } }

vim.keymap.set('n', '<leader>gg', neogit.open, { desc = 'Neogit status' })
vim.keymap.set('n', '<leader>gc', function() neogit.open { 'commit' } end, { desc = 'Neogit [c]ommit popup' })
vim.keymap.set('n', '<leader>gp', function() neogit.open { 'pull' } end, { desc = 'Neogit [p]ull popup' })
vim.keymap.set('n', '<leader>gP', function() neogit.open { 'push' } end, { desc = 'Neogit [P]ush popup' })
vim.keymap.set('n', '<leader>gl', function() neogit.open { 'log' } end, { desc = 'Neogit [l]og popup' })

-- vim: ts=2 sts=2 sw=2 et
