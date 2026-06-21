# Agent instructions — revtui code review

This repository uses **revtui** to manage inline code-review comments on git diffs.
When you are asked to review code, audit changes, or leave comments, use the
`revtui` CLI described below. Comments are stored in `.rev/comments.json` and
displayed inline in the diff viewer by the human reviewer.

---

## Review workflow

Work through these steps in order every time you do a review.

### 1. Discover changed files

```bash
revtui files
```

Returns one relative file path per line. Review all of them unless the task
specifies a subset.

### 2. Read the diff

```bash
git diff HEAD -- <file>
```

Study the hunk headers (`@@ -OLD,n +NEW,n @@`). They tell you the starting
line numbers. Count forward from each header to find the exact line you want
to comment on.

**Line-number rule:**
- `+` lines (additions) and context lines → use `--line <new-file-lineno>`
- `-` lines (deletions) → use `--old-line <old-file-lineno>`

### 3. Check existing comments first

```bash
revtui list-comments --file <file> --open-only --json
```

Do not duplicate an open comment. Do not reopen a resolved one.

### 4. Post comments

```bash
revtui add-comment \
  --file <relative/path> \
  --line <new-file-lineno> \
  --message "<comment>" \
  --agent-name "<your-identifier>"
```

**Comment guidelines:**
- Start with a severity tag: `[bug]`, `[security]`, `[perf]`, `[style]`, or `[question]`.
  Omit the tag for general suggestions.
- One issue per comment. Do not bundle multiple concerns.
- Be specific: name the exact variable, function, or pattern.
- Explain *why* it matters, not just *what* it is.
- Keep it to 1–3 sentences.

### 5. Resolve addressed comments (second-pass reviews)

```bash
# List what's still open
revtui list-comments --open-only --json

# Resolve each comment the new code has fixed
revtui resolve <comment-id>   # first 8 chars of the UUID is enough
```

### 6. Output a summary

After finishing, print a short report:

```
Reviewed <N> file(s). Posted <M> comment(s). Resolved <K>.

High-priority items:
- <file>:<line> — <one-line summary>
```

Say "No issues found." explicitly if there is nothing to flag.

---

## CLI quick-reference

| Command | Purpose |
|---------|----------|
| `revtui files` | List changed files |
| `revtui status` | Overview: files + comment counts |
| `revtui add-comment --file F --line N --message M --agent-name A` | Post a comment on a new-file line |
| `revtui add-comment --file F --old-line N --message M --agent-name A` | Post a comment on a deleted line |
| `revtui list-comments [--file F] [--open-only] [--json]` | Read comments |
| `revtui resolve <id>` | Mark a comment resolved |
| `revtui watch [--file F]` | Stream new comments live |

---

## Severity tag reference

| Tag | Use for |
|-----|----------|
| `[bug]` | Wrong output, crash risk, incorrect logic |
| `[security]` | Auth bypass, injection, exposed secrets |
| `[perf]` | Measurable or obvious performance problem |
| `[style]` | Naming, formatting, readability |
| `[question]` | Genuine uncertainty — ask before assuming it's wrong |
| *(none)* | General suggestion or improvement |

---

## Example

```bash
# Step 1 — what changed?
revtui files

# Step 2 — read one file's diff
git diff HEAD -- sample_agent_code.py

# Step 3 — existing comments?
revtui list-comments --file sample_agent_code.py --open-only --json

# Step 4 — post findings
revtui add-comment \
  --file sample_agent_code.py \
  --line 7 \
  --message "[bug] VIP discount is 0.5 (50%). Most tiers cap at 20–30%; confirm this is intentional." \
  --agent-name "codex-reviewer"

# Step 5 — nothing to resolve on a first pass

# Step 6 — summary
revtui status
```
