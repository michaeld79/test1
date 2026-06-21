---
description: Review agent-written code using the revtui CLI. Reads the current git diff, posts inline comments keyed to specific lines, and resolves comments after fixes. Use when asked to review, audit, or leave comments on uncommitted changes.
---

# revtui code review skill

You are reviewing code changes using `revtui`, a CLI tool that stores structured
comments in `.rev/comments.json` and displays them inline in the diff TUI.

Follow the steps below in order. Do not skip steps — line-number accuracy depends
on reading the actual diff output rather than guessing.

---

## Step 1 — Discover what changed

```bash
revtui files
```

Returns one file path per line. Work through every file unless the user asked
you to focus on a specific one.

---

## Step 2 — Read the diff for each file

```bash
git diff HEAD -- <file>
```

Read this carefully. Each hunk header (`@@ -OLD +NEW @@`) tells you where the
changed block starts. Count lines from that header to find the correct
**new-file line number** (`+` lines have new-file numbers; `-` lines have
old-file numbers).

> **Line-number rule**
> - Use `--line` (new-file number) for added lines (`+`) and context lines.
> - Use `--old-line` (old-file number) for deleted lines (`-`).
> - For a comment that spans a region, anchor it to the first relevant line.

---

## Step 3 — Read existing comments before adding new ones

```bash
revtui list-comments --file <file> --json
```

Avoid duplicating comments that are already present. If an existing open comment
covers the same issue, skip it. If an existing comment was already resolved, do
not reopen it.

---

## Step 4 — Post your comments

```bash
revtui add-comment \
  --file <relative/path/to/file> \
  --line <new-file-lineno> \
  --message "<your comment>" \
  --agent-name "<your-name>"
```

Use `--old-line` instead of `--line` when commenting on a deleted line.

**Comment writing guidelines:**
- Be specific: name the exact construct (variable, function, pattern) you mean.
- Explain the *why*: what breaks, what the risk is, or what the better approach is.
- One issue per comment. Do not bundle multiple concerns.
- Keep it under ~3 sentences. The human reviewer will see it inline next to the code.
- Do not praise code that is merely adequate. Only compliment non-obvious good choices.

**Severity conventions (put at the start of the message):**

| Prefix | When to use |
|--------|-------------|
| `[bug]` | Incorrect behaviour, wrong output, crash risk |
| `[security]` | Auth bypass, injection, secret exposure, etc. |
| `[perf]` | Measurable performance problem |
| `[style]` | Naming, formatting, readability |
| `[question]` | Genuine uncertainty — ask before assuming it's wrong |
| *(none)* | General suggestion or improvement |

---

## Step 5 — Resolve comments after a fix is applied

If you are reviewing a second pass after the human has made changes, check
which comments are now addressed:

```bash
revtui list-comments --open-only --json
```

For each comment that the new code has resolved:

```bash
revtui resolve <comment-id>
```

`<comment-id>` can be the first 8 characters of the full UUID shown in
`list-comments` output.

---

## Step 6 — Report a summary

After posting all comments, output a short summary to the user:

```
Reviewed <N> file(s).  Posted <M> comment(s).  Resolved <K>.

High-priority items:
- <file>:<line> — <one-line summary>
- ...
```

If there is nothing to comment on, say so explicitly: "No issues found."

---

## Full CLI reference

```
revtui files
    List files changed in the current diff (one per line).

revtui status
    Summary: changed files, open and resolved comment counts.

revtui add-comment \
    --file FILE        Relative path from repo root (required)
    --line INT         New-file line number (additions / context)
    --old-line INT     Old-file line number (deletions) — use instead of --line
    --message TEXT     Comment body (required)
    --agent-name TEXT  Your agent identifier (e.g. "gpt-reviewer", "claude-reviewer")

revtui list-comments \
    --file FILE        Filter to one file
    --open-only        Only open (unresolved) comments
    --json             Machine-readable JSON output

revtui resolve COMMENT_ID
    Mark a comment resolved by its full UUID or 8-char prefix.

revtui watch \
    --file FILE        Filter to one file
    --interval FLOAT   Poll interval in seconds (default 1.0)
    Stream new comments as they arrive; Ctrl-C to stop.
```

---

## Example session

```bash
# 1. What changed?
revtui files
# → sample_agent_code.py

# 2. Read the diff
git diff HEAD -- sample_agent_code.py

# 3. Any existing comments?
revtui list-comments --file sample_agent_code.py --json

# 4. Post findings
revtui add-comment \
  --file sample_agent_code.py \
  --line 7 \
  --message "[bug] VIP discount is 0.5 (50%). Confirm this is intentional — most tiers cap at 20-30%." \
  --agent-name "claude-reviewer"

revtui add-comment \
  --file sample_agent_code.py \
  --line 12 \
  --message "rounding here prevents floating-point drift in downstream totals — good practice." \
  --agent-name "claude-reviewer"

# 5. Summary
revtui status
```
