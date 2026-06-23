# revtui TUI Improvement Plan

Source: 4-agent review (TUI Expert, UX Expert, Designer, Devil's Advocate).
Lens kept throughout: revtui is a **live human↔agent comment work-queue on a diff**,
not a GitHub-style discussion forum. Items that only serve forum/IDE parity were cut.

Decisions are final (user-selected). 13 items IN, organized into 4 phases.
File:line refs are from the review snapshot; re-verify before editing.

---

## Phase 1 — Correctness bugs (do first, blocks nothing)

Independent of each other → **parallelizable**.

### 1.1 Single shared poll timer  [S]
- **Problem:** every `DiffViewer` runs its own `set_interval(1.5, _auto_refresh)`
  (`app.py:240`). With N files = N timers, N `store.load()` disk reads / 1.5s, and
  the new-comment toast fires **once per viewer** → duplicate toasts. (`app.py:248-270`)
- **Change:** move the timer + `_known_ids` diff + toast to `ReviewApp` (App level).
  On new comments: load once, notify once, then tell the *current* viewer to
  `_refresh_inline_comments()` and refresh `FileTree` stats.
- **Done when:** one agent comment = one toast, regardless of file count.

### 1.2 Block comments on header / hunk lines  [S]
- **Problem:** `_find_line_idx` returns None for header/hunk lines (both linenos
  None) → comment stored but never rendered = silent data loss. Cursor starts at
  idx 0 which is always a `file_header`, so the first `c` hits it.
  (`app.py:274-281, 404, 441`; line types in `diff_parser.py`)
- **Change:** in `action_add_comment` / `AddCommentScreen`, reject `line_type` in
  {`file_header`, `hunk_header`, `binary`} with a `notify(... warning)`.
  (Optional later: anchor to next real line instead of rejecting — NOT in scope now.)
- **Done when:** pressing `c` on a header line warns instead of silently storing.

### 1.3 Fix blind resolve  [S]
- **Problem:** `action_resolve_comment` resolves the *first* matching open comment
  on a line; with >1 it silently picks an arbitrary one. (`app.py:360-372`)
- **Change:** if exactly one open comment → resolve it. If >1 → resolve the most
  recent deterministically (or show a tiny chooser; deterministic-newest is the
  S-path and acceptable). Notify which `short_id` was resolved.
- **Done when:** behavior on multi-comment lines is predictable + reported.

### 1.4 Help text command fix  [S]
- **Problem:** `_HELP` says `python -m revtui ...`; README/skill use bare `revtui`.
  (`app.py:469-473`)
- **Change:** replace `python -m revtui` → `revtui` in `_HELP`.

---

## Phase 2 — Visual / design fixes (after Phase 1; touch rendering)

Some overlap in `make_line_text` / `make_inline_comment_widget` → coordinate, but
mostly **parallelizable** by function.

### 2.1 Selection color + keep type-tint  [S]  (Designer P1, highest visual impact)
- **Problem:** selection replaces the whole style with olive `_SELECTED_BG #3a3500`
  (`app.py:36, 42`), dropping the green/red add/del tint on the focused line —
  a functional regression. Olive also collides with human-comment bg + badge yellow.
- **Change:** on selection keep `base.bgcolor` (the type tint), add `bold=True`
  and a left accent bar (e.g. `▎`) + a brighter/neutral cool selection cue.
  Drop olive. (`make_line_text`, `app.py:39-55`)
- **Done when:** a selected addition still reads green; cursor is unmistakable.

### 2.2 Align inline comment cards to the gutter  [S]
- **Problem:** card lines hardcode 6 spaces (`"      "`) but the real diff gutter is
  11 cols (`sign 1 + old 4 + space 1 + new 4 + space 1`). Cards float misaligned.
  (`app.py:73, 80, 85, 89` vs gutter built at `app.py:53`)
- **Change:** define `_GUTTER_W = 11` (single source), use it for card indent so
  cards hang under the line they annotate. Consider a tee glyph (`├─`/`╰─`) so the
  card visibly anchors to its line.
- **Done when:** card body aligns under the code content column.

### 2.3 Lift context / footer contrast  [S]
- **Problem:** context grey `#6b7280` on `#1e2127` ≈ 3.5:1 (under WCAG AA 4.5);
  it's the bulk of the diff. Footer uses the same dim grey. (`app.py:34, 519`)
- **Change:** bump `context` → `#8b93a3` (~4.5:1). Keep `#6b7280` only for truly
  secondary text (timestamps, short_id). Footer hint color → `#8b93a3`.

### 2.4 Unify human/agent + status glyphs  [S]
- **Problem:** three vocabularies for the human/agent distinction: sidebar uses
  `H:`/`A:` letters (`app.py:166-169`), toasts + `author_label` use `🤖`/`👤`
  (`app.py:257`, `comment_store.py:35-36`), card status uses `●`/`✓` with `●` open
  rendered plain white (`app.py:69-70`).
- **Change:** pick ONE icon set for human/agent across card header, sidebar, toasts.
  Status: open = amber glyph (warm = needs attention), resolved = green `✓`.
  Make `open` NOT white.
- **Done when:** the same symbols mean the same thing everywhere.

---

## Phase 3 — Comment-loop features (after Phase 1; some depend on it)

### 3.1 Delete own comment in TUI (delete-only, no edit)  [S]
- **Scope decision:** delete only. Edit-in-TUI was CUT (typo = delete + re-add `c`).
- **Already exists:** `CommentStore.delete()` (`comment_store.py:113`) — just surface it.
- **Change:** bind `d` in `DiffViewer`. On cursor line, find the user's own (`author
  == "human"`) open/any comment; confirm (small modal or `notify` + second-press),
  then `store.delete(c.id)`, refresh inline + tree stats.
- **Guard:** only allow deleting `author == "human"` comments (don't let the human
  delete the agent's comments by accident).
- **Done when:** `d` removes the human's comment on the line with confirmation.

### 3.2 Gutter comment markers  [S]
- **Problem:** a line with a comment looks identical to one without when scrolled
  past — no information scent. (`make_line_text`, `app.py:39-55`)
- **Change:** when rendering a diff line that has comment(s), draw a marker in/next
  to the gutter (e.g. `●`), colored by open (amber) vs resolved (green/dim).
  Reuse the glyph set from 2.4.
- **Done when:** you can scan a file visually for where the threads are.

### 3.3 Next / prev comment navigation  [M]
- **Problem:** on big diffs you `j`-spam through context to find the next thread.
- **Change:** bind `n` / `N` = jump cursor to next / prev line that has a comment
  (scroll into view). Add a next-**unresolved** variant (e.g. shift / `]`).
  Build an ordered index of commented line idxs from the store.
- **Depends on:** comment→line mapping already used by `_find_line_idx`.
- **Done when:** `n`/`N` move between threads; unresolved variant skips resolved.

---

## Phase 4 — Live-loop polish (after Phase 1; independent)

### 4.1 Pause auto-refresh while a modal is open  [S]
- **Problem:** the timer keeps polling + can remount inline widgets / fire toasts
  under `AddCommentScreen` while the user types. (`app.py:248`)
- **Change:** in the shared timer (1.1), early-return if `len(self.screen_stack) > 1`.
- **Depends on:** 1.1 (shared timer).

### 4.2 "● watching" indicator + toast short_id  [S]
- **Problem:** no signal the live loop is active; add-comment toast is generic
  ("Comment added", `app.py:446`) so it can't be correlated with agent references.
- **Change:** (a) header `sub_title` (or a status cell) shows `● watching` so the
  user knows auto-refresh is live; (b) include `c.short_id` in the add-comment toast.
- **Done when:** user sees the loop is live; add toast shows `[short_id]`.

---

## Explicitly CUT (do NOT build)

Rationale: GitHub-envy / generic-IDE reflex that doesn't serve the live work-queue,
or unmeasured optimization. Revisit only with a profiler or real user pain.

- **Threading / `parent_id` / replies** — agent consumes comments via `list-comments
  --json` and acts in the code; it does not reply in threads. Flat records are correct.
- **Line-API single-widget renderer rewrite** — unmeasured (assumed 2000-line file;
  real diffs are tens–low-hundreds of lines), and it fights the sibling-widget inline
  comment model (`mount(..., after=anchor)`, `app.py:305`). Demand a measurement first.
- **Edit-in-TUI** — kept delete only; edit duplicates CLI/delete+re-add.
- **Multi-line range select (`v`-then-`c`)** — renders to a single anchor anyway;
  large state cost, tiny value over "comment the key line + say 'this block'."
- **Theme system + light theme + `t` toggle** — terminal is already themed. (The real
  nugget — colors split across `_STYLES` + CSS — is an optional consolidation chore.)
- **Severity quick-pick picker for humans** — the skill makes tagging optional for
  humans by design; at most a placeholder hint, not a picker.
- **Lazy-mount viewers** — speculative once 1.1 lands; revisit only with a profiler.
- **Standalone all-comments TUI panel** — `revtui watch` + sidebar badges + inline
  display already cover cross-file awareness.
- **Responsive / auto-hiding sidebar** — the existing `s` toggle is the responsive
  story for a terminal.

---

## Suggested execution order

1. **Phase 1** (1.1 → then 1.2/1.3/1.4 in parallel). 1.1 unblocks 4.1.
2. **Phase 2** (2.1–2.4, parallel by function; 2.4 glyph set feeds 3.2).
3. **Phase 3** (3.1, 3.2, 3.3 — 3.2 reuses 2.4 glyphs).
4. **Phase 4** (4.1 needs 1.1; 4.2 independent).

## Resolved decisions (were open questions)
- **1.3:** deterministic — resolve the **most-recent** open comment on the line. No chooser modal. Notify the resolved `short_id`.
- **2.4 / 3.2:** keep emoji **`🤖` (agent) / `👤` (human)** everywhere (matches `comment_store.py:author_label`); unify sidebar `H:`/`A:` and toasts to this. Status glyphs: open = amber `●`, resolved = green `✓`.
- **3.1:** **double-press `d`** inline confirm (first `d` arms + `notify("press d again to delete")`, second `d` within the same cursor line deletes). No modal.
- **3.3:** `n` / `N` = next / prev **any** comment line; `]` / `[` = next / prev **unresolved** comment line.
