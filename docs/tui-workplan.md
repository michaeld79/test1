# revtui TUI Improvement — Executable Workplan (waves)

Companion to `tui-improvement-plan.md`. Produced by the TeamLeader agent.
`$PY` = scratchpad validate-venv python (textual 8.2.7, click, gitpython).

## Waves & dependencies
- **Wave A:** 1.1 shared poll timer — run ALONE, merge first (B/C/D depend on it).
- **Wave B (parallel, after 1.1):** 1.2 block header comments · 1.3 newest-resolve · 1.4 help text · 4.1 pause refresh under modal.
- **Wave C (after Phase 1):** **C1** = 2.1 selection+tint · 2.2 gutter align · 2.3 contrast · 2.4 glyph constants · 3.2 gutter markers — ONE worktree (all touch make_line_text / make_inline_comment_widget / _file_label / _STYLES).
- **Wave D (after C1):** **D1** = 3.1 delete (double-d) · 3.3 next/prev nav — ONE worktree (same BINDINGS literal).

## Merge order
1.1 → (1.4,1.3,1.2,4.1 any order) → C1 → D1.

## Combine rules
- C1 combines 5 items (same rendering funcs). D1 combines 2 (same BINDINGS).
- Everything else separate.

## Validation baseline (every task)
- `$PY -m py_compile revtui/*.py`
- `$PY -c "import revtui.app, revtui.comment_store, revtui.diff_parser, revtui.cli"`
- Pilot tests via `async with app.run_test() as pilot:` where UI behavior is involved.

## Risks needing human spot-check
1. C1 visual alignment/color (real terminal/screenshot).
2. Gutter-marker vs card-alignment 11-col coupling.
3. Emoji double-width in 28-col sidebar.
4. Timer/notification timing under run_test (drive deterministically; fallback: call _poll_comments directly).
5. Double-press `d` felt safety.
6. Toast de-dup MUST be tested with >=2 diff files.

Full per-task specs: see the TeamLeader message in session history / the implementer prompts.
