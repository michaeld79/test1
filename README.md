# revtui

A terminal UI for reviewing agent-written code. View the git diff, leave inline
comments, and let your coding agent read them back via CLI.

## What it does

- **Colored diff view** with file tree sidebar (toggle with `s`)
- **Inline comments** appear directly in the diff — yellow for human, cyan for agent
- **Agent CLI** — any coding agent can post and read comments without opening the TUI
- **Auto-refresh** — new agent comments appear in the TUI within 1.5 seconds
- **Watch mode** — stream incoming comments live in the terminal

## Install

```bash
# pipx (recommended)
pipx install git+https://github.com/michaeld79/revtui.git

# uv tool
uv tool install git+https://github.com/michaeld79/revtui.git

# Or locally from the repo
pip install .
```

Requires Python 3.10+ and a terminal with color support.

## Usage

### Open the TUI

```bash
revtui
# or from a different directory:
revtui --repo /path/to/repo
```

Shows the diff for the current repo (unstaged changes, then staged, then last commit).

### TUI keybindings

| Key | Action |
|-----|--------|
| `j` / `↓` | Move cursor down |
| `k` / `↑` | Move cursor up |
| `Ctrl+D` / `Ctrl+U` | Page down / up |
| `g` / `G` | Jump to top / bottom |
| `s` | Toggle file tree sidebar |
| `Tab` | Switch focus: tree ↔ diff |
| `c` | Add comment on cursor line |
| `r` | Resolve comment on cursor line |
| `?` | Help |
| `q` | Quit |

### Agent / CLI commands

```bash
# Print full agent instructions (start here)
revtui --skill

# List changed files
revtui files

# Post a comment
revtui add-comment \
  --file src/main.py \
  --line 42 \
  --message "[bug] This will panic on nil input." \
  --agent-name my-agent

# List comments (JSON for scripting)
revtui list-comments --file src/main.py --open-only --json

# Resolve a comment by ID prefix
revtui resolve bb3b92b6

# Review summary
revtui status

# Stream new comments live
revtui watch
```

### Integrating a coding agent

Run `revtui --skill` to print the full review workflow your agent should follow.
Add this to your agent's system prompt or `AGENTS.md`:

```markdown
Before reviewing code in this repo, run `revtui --skill` and follow the instructions.
```

Codex reads `AGENTS.md` automatically — this repo includes one.
Claude Code users can invoke the bundled skill with `/revtui-review`.

## How it works

Comments are stored in `.rev/comments.json` (gitignored). The TUI polls this
file every 1.5 seconds, so comments posted by a background agent appear without
restarting.

```
human opens TUI        agent runs in parallel
       │                       │
       │                       ├─ revtui files
       │                       ├─ git diff HEAD -- foo.py
       │                       ├─ revtui add-comment --file foo.py --line 7 \
       │                       │     --message "[bug] ..." --agent-name bot
       │                       │
       │◄──── toast notification (new comment from bot) ──────────────────┤
       │
       │  diff view now shows inline comment under line 7
```

## Project structure

```
revtui/
  app.py           Textual TUI — diff viewer, file tree, inline comments
  cli.py           Click CLI — add-comment, list, resolve, watch, --skill
  comment_store.py Comment persistence (.rev/comments.json)
  diff_parser.py   Git diff parser → structured DiffFile / DiffLine
AGENTS.md          Agent instructions (read by Codex automatically)
.claude/skills/
  revtui-review/
    SKILL.md       Claude Code skill — invoke with /revtui-review
```

## Development

```bash
git clone https://github.com/michaeld79/revtui.git
cd revtui
pip install -e .
revtui --repo .
```

## License

MIT
