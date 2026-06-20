"""Main Textual TUI for code review."""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from rich.markup import escape
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, ContentSwitcher, Footer, Header, Input, Label, Static

from .comment_store import Comment, CommentStore
from .diff_parser import DiffFile, DiffLine, get_git_diff, parse_diff

# ──────────────────────────────────────────────
#  Rendering helpers
# ──────────────────────────────────────────────

_STYLES = {
    "addition":    Style(color="bright_green",   bgcolor="#1a2d1a"),
    "deletion":    Style(color="bright_red",     bgcolor="#2d1a1a"),
    "hunk_header": Style(color="bright_cyan",    bgcolor="#0d1a2d"),
    "file_header": Style(color="bright_magenta", bgcolor="#1e0d2d"),
    "binary":      Style(color="yellow",         bgcolor="#2d2200"),
    "context":     Style(color="#6b7280"),
}
_SELECTED_BG = "#3a3500"


def make_line_text(line: DiffLine, selected: bool = False) -> Text:
    base = _STYLES.get(line.line_type, _STYLES["context"])
    if selected:
        base = Style(color=base.color, bgcolor=_SELECTED_BG, bold=True)

    if line.line_type in ("hunk_header", "file_header", "binary"):
        old_s = new_s = "    "
        sign = " "
    else:
        old_s = f"{line.old_lineno:4d}" if line.old_lineno is not None else "    "
        new_s = f"{line.new_lineno:4d}" if line.new_lineno is not None else "    "
        sign = {"addition": "+", "deletion": "-"}.get(line.line_type, " ")

    t = Text(no_wrap=True, overflow="ellipsis")
    t.append(f"{sign}{old_s} {new_s} ", style=base)
    t.append(line.content, style=base)
    return t


def make_comment_text(store: CommentStore, diff_file: DiffFile, current_line: Optional[DiffLine]) -> Text:
    t = Text()
    comments = store.get_comments(file=diff_file.new_path)

    if not comments:
        t.append(f"{diff_file.new_path}\n", style="bold")
        t.append("No comments yet.\n\n", style="dim")
        t.append("Press ", style="dim")
        t.append("c", style="bold yellow")
        t.append(" on a diff line to add one.", style="dim")
        return t

    # Identify which comments match the current cursor line
    on_line: set[str] = set()
    if current_line:
        for c in comments:
            match = (
                current_line.new_lineno is not None and c.new_lineno == current_line.new_lineno
            ) or (
                current_line.old_lineno is not None and c.old_lineno == current_line.old_lineno
            )
            if match:
                on_line.add(c.id)

    open_cnt = sum(1 for c in comments if c.status == "open")
    resolved_cnt = len(comments) - open_cnt

    t.append(f"{diff_file.new_path}\n", style="bold white")
    t.append(f"  {open_cnt} open", style="yellow")
    t.append(" · ", style="dim")
    t.append(f"{resolved_cnt} resolved\n\n", style="dim")

    for c in sorted(comments, key=lambda x: (x.new_lineno or 0, x.old_lineno or 0, x.timestamp)):
        highlighted = c.id in on_line
        _append_comment(t, c, highlighted)
        t.append("\n")

    return t


def _append_comment(t: Text, c: Comment, highlighted: bool) -> None:
    border_style = Style(color="yellow", bold=True) if highlighted else Style(color="#555555")
    status_icon = "✓" if c.status == "resolved" else "●"
    status_style = Style(color="green") if c.status == "resolved" else Style(color="white")
    author_style = Style(color="cyan") if c.author == "agent" else Style(color="yellow")
    dim = Style(dim=True)

    t.append("┌─", style=border_style)
    t.append(f" {c.line_ref} ", style=dim)
    t.append(c.author_label, style=author_style)
    t.append(" ", style=dim)
    t.append(c.timestamp[:16].replace("T", " "), style=dim)
    t.append(" ─", style=border_style)
    t.append(f" [{c.short_id}]\n", style=dim)

    content_style = Style(dim=True) if c.status == "resolved" else Style()
    for line in c.content.splitlines():
        t.append("│ ", style=border_style)
        t.append(line, style=content_style)
        t.append("\n")

    if c.line_content:
        t.append("│ ", style=border_style)
        t.append(f"» {c.line_content[:60]}", style=dim)
        t.append("\n")

    t.append("└", style=border_style)
    t.append(f" {status_icon} {c.status}\n", style=status_style)


# ──────────────────────────────────────────────
#  DiffViewer widget
# ──────────────────────────────────────────────

class DiffViewer(VerticalScroll):
    """Scrollable diff viewer with keyboard-driven line selection."""

    can_focus = True
    BINDINGS = [
        Binding("j,down", "move_down", "↓", show=False),
        Binding("k,up", "move_up", "↑", show=False),
        Binding("ctrl+d", "page_down", "PgDn", show=False),
        Binding("ctrl+u", "page_up", "PgUp", show=False),
        Binding("g", "go_top", "Top", show=False),
        Binding("G", "go_bottom", "Bottom", show=False),
        Binding("c", "add_comment", "Comment"),
        Binding("r", "resolve_comment", "Resolve"),
    ]

    cursor_idx: reactive[int] = reactive(-1, init=False)

    class LineChanged(Message):
        def __init__(self, idx: int, line: Optional[DiffLine], diff_file: DiffFile) -> None:
            super().__init__()
            self.idx = idx
            self.line = line
            self.diff_file = diff_file

    def __init__(self, diff_file: DiffFile, store: CommentStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.diff_file = diff_file
        self.store = store
        self._labels: List[Label] = []

    def compose(self) -> ComposeResult:
        if not self.diff_file.lines:
            yield Static("[dim]No diff content for this file.[/dim]")
            return
        for i, line in enumerate(self.diff_file.lines):
            lbl = Label(make_line_text(line), id=f"dl-{i}")
            self._labels.append(lbl)
            yield lbl

    def on_mount(self) -> None:
        self._known_ids: set[str] = {c.id for c in self.store.all_comments}
        self.set_interval(1.5, self._auto_refresh)
        if self.diff_file.lines:
            self.call_after_refresh(self._set_initial_cursor)

    def _set_initial_cursor(self) -> None:
        self.cursor_idx = 0

    async def _auto_refresh(self) -> None:
        """Reload comments from disk; notify on new arrivals."""
        self.store.load()
        current_ids = {c.id for c in self.store.all_comments}
        new_ids = current_ids - self._known_ids

        if new_ids:
            for c in self.store.all_comments:
                if c.id in new_ids:
                    if c.author == "agent":
                        badge = f"🤖 {c.agent_name or 'agent'}"
                        severity = "information"
                    else:
                        badge = "👤 human"
                        severity = "information"
                    preview = c.content[:50] + ("…" if len(c.content) > 50 else "")
                    self.app.notify(
                        f"{badge} · {c.file}:{c.line_ref}\n{preview}",
                        title="New comment",
                        severity=severity,
                        timeout=6,
                    )
            self._known_ids = current_ids

        panel = self.app.query_one(CommentsPanel)
        current = (
            self.diff_file.lines[self.cursor_idx]
            if 0 <= self.cursor_idx < len(self.diff_file.lines)
            else None
        )
        panel.update_comments(self.diff_file, current)

    def watch_cursor_idx(self, old: int, new: int) -> None:
        n = len(self.diff_file.lines)
        labels = self._labels

        if len(labels) != n:
            return  # Not yet composed

        if 0 <= old < n:
            labels[old].update(make_line_text(self.diff_file.lines[old], selected=False))
        if 0 <= new < n:
            labels[new].update(make_line_text(self.diff_file.lines[new], selected=True))
            labels[new].scroll_visible()

        line = self.diff_file.lines[new] if 0 <= new < n else None
        self.post_message(self.LineChanged(new, line, self.diff_file))

    # ── Actions ─────────────────────────────────

    def action_move_down(self) -> None:
        self.cursor_idx = min(self.cursor_idx + 1, len(self.diff_file.lines) - 1)

    def action_move_up(self) -> None:
        self.cursor_idx = max(self.cursor_idx - 1, 0)

    def action_page_down(self) -> None:
        self.cursor_idx = min(self.cursor_idx + 20, len(self.diff_file.lines) - 1)

    def action_page_up(self) -> None:
        self.cursor_idx = max(self.cursor_idx - 20, 0)

    def action_go_top(self) -> None:
        self.cursor_idx = 0

    def action_go_bottom(self) -> None:
        n = len(self.diff_file.lines)
        if n:
            self.cursor_idx = n - 1

    def action_add_comment(self) -> None:
        n = len(self.diff_file.lines)
        if 0 <= self.cursor_idx < n:
            line = self.diff_file.lines[self.cursor_idx]
            self.app.push_screen(
                AddCommentScreen(self.diff_file, line, self.store),
                callback=self._after_comment,
            )

    def action_resolve_comment(self) -> None:
        n = len(self.diff_file.lines)
        if not (0 <= self.cursor_idx < n):
            return
        line = self.diff_file.lines[self.cursor_idx]
        for c in self.store.get_comments(file=self.diff_file.new_path):
            if c.status == "open" and (
                (line.new_lineno is not None and c.new_lineno == line.new_lineno)
                or (line.old_lineno is not None and c.old_lineno == line.old_lineno)
            ):
                self.store.resolve(c.id)
                self.app.query_one(CommentsPanel).update_comments(self.diff_file, line)
                self.app.notify(f"Resolved comment [{c.short_id}]", severity="information")
                return
        self.app.notify("No open comment on this line.", severity="warning")

    def _after_comment(self, _: Any) -> None:
        n = len(self.diff_file.lines)
        current = self.diff_file.lines[self.cursor_idx] if 0 <= self.cursor_idx < n else None
        self.app.query_one(CommentsPanel).update_comments(self.diff_file, current)


# ──────────────────────────────────────────────
#  CommentsPanel widget
# ──────────────────────────────────────────────

class CommentsPanel(VerticalScroll):
    """Right panel: displays comments for the current diff file / line."""

    def __init__(self, store: CommentStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.store = store
        self._diff_file: Optional[DiffFile] = None
        self._current_line: Optional[DiffLine] = None

    def compose(self) -> ComposeResult:
        yield Static("", id="comments-text")

    def update_comments(self, diff_file: Optional[DiffFile], line: Optional[DiffLine]) -> None:
        self._diff_file = diff_file
        self._current_line = line
        display = self.query_one("#comments-text", Static)
        if diff_file is None:
            display.update(Text("Select a file to see comments.", style="dim"))
            return
        display.update(make_comment_text(self.store, diff_file, line))


# ──────────────────────────────────────────────
#  Add Comment modal
# ──────────────────────────────────────────────

class AddCommentScreen(ModalScreen[None]):
    """Modal for adding a review comment."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, diff_file: DiffFile, diff_line: DiffLine, store: CommentStore) -> None:
        super().__init__()
        self.diff_file = diff_file
        self.diff_line = diff_line
        self.store = store

    def compose(self) -> ComposeResult:
        line = self.diff_line
        if line.new_lineno is not None:
            loc = f"L{line.new_lineno}"
        elif line.old_lineno is not None:
            loc = f"-L{line.old_lineno}"
        else:
            loc = "header"

        with Vertical(id="add-comment-dialog"):
            yield Static(
                f"[bold]Add Comment[/bold]  [dim]{escape(self.diff_file.new_path)} {loc}[/dim]",
                id="dialog-title",
            )
            if line.content.strip():
                yield Static(
                    f"[dim on #1e2127]  {escape(line.content[:80])}[/dim on #1e2127]",
                    id="dialog-context",
                )
            yield Input(placeholder="Type your comment…", id="comment-input")
            with Horizontal(id="dialog-btns"):
                yield Button("Add Comment (Enter)", variant="primary", id="btn-add")
                yield Button("Cancel (Esc)", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#comment-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            self._submit()
        else:
            self.dismiss()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        text = self.query_one("#comment-input", Input).value.strip()
        if not text:
            self.app.notify("Comment cannot be empty.", severity="warning")
            return
        self.store.add_comment(
            file=self.diff_file.new_path,
            content=text,
            author="human",
            old_lineno=self.diff_line.old_lineno,
            new_lineno=self.diff_line.new_lineno,
            line_type=self.diff_line.line_type,
            line_content=self.diff_line.content,
        )
        self.app.notify("Comment added.", severity="information")
        self.dismiss()


# ──────────────────────────────────────────────
#  Help modal
# ──────────────────────────────────────────────

_HELP = """\
[bold]Navigation[/bold]
  [yellow]j / ↓[/yellow]       Move cursor down
  [yellow]k / ↑[/yellow]       Move cursor up
  [yellow]Ctrl+D[/yellow]      Page down (20 lines)
  [yellow]Ctrl+U[/yellow]      Page up (20 lines)
  [yellow]g[/yellow]           Jump to top
  [yellow]G[/yellow]           Jump to bottom
  [yellow][ / ←[/yellow]       Previous file
  [yellow]] / →[/yellow]       Next file

[bold]Comments[/bold]
  [yellow]c[/yellow]           Add comment on cursor line
  [yellow]r[/yellow]           Resolve open comment on cursor line

[bold]Agent CLI[/bold]  (from terminal, while TUI is open or not)
  [cyan]python -m revtui add-comment --file FILE --line LINE \\
          --message "MSG" --agent-name NAME[/cyan]

  [cyan]python -m revtui list-comments [--file FILE] [--json][/cyan]
  [cyan]python -m revtui resolve COMMENT_ID[/cyan]
  [cyan]python -m revtui status[/cyan]

[bold]Other[/bold]
  [yellow]?[/yellow]           Toggle this help
  [yellow]q[/yellow]           Quit
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("?", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("[bold reverse]  revtui — Code Review TUI  [/bold reverse]", id="help-title")
            yield Static(_HELP, id="help-body")
            yield Button("Close  [dim](Esc)[/dim]", id="btn-close")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss()


# ──────────────────────────────────────────────
#  File selector bar
# ──────────────────────────────────────────────

class FileSelectorBar(Static):
    """Top bar showing current file and navigation hints."""

    def __init__(self, diff_files: List[DiffFile], **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self.diff_files = diff_files

    def update_for(self, idx: int, comment_count: int) -> None:
        n = len(self.diff_files)
        if n == 0:
            self.update("[dim]No diff found[/dim]")
            return
        f = self.diff_files[idx]
        add = f"[green]+{f.additions}[/green]"
        rem = f"[red]-{f.deletions}[/red]"
        self.update(
            f"[dim][[/dim] [yellow]{idx+1}[/yellow][dim]/{n}[/dim] [dim]][/dim]  "
            f"[bold]{escape(f.display_path)}[/bold]  "
            f"{add} {rem}  "
            f"[dim]{comment_count} comment(s)   ← [ / → ][/dim]"
        )


# ──────────────────────────────────────────────
#  Main App
# ──────────────────────────────────────────────

class ReviewApp(App[None]):
    """Code review TUI — review agent-written diffs and leave comments."""

    CSS = """
    Screen {
        background: #1e2127;
    }
    Header {
        background: #21252b;
        color: #abb2bf;
    }
    Footer {
        background: #21252b;
        color: #6b7280;
    }
    #file-bar {
        background: #282c34;
        color: #abb2bf;
        height: 1;
        padding: 0 1;
        border-bottom: solid #3e4451;
    }
    #main-body {
        height: 1fr;
    }
    ContentSwitcher {
        width: 3fr;
        border-right: solid #3e4451;
    }
    DiffViewer {
        background: #1e2127;
        scrollbar-color: #3e4451;
        scrollbar-color-hover: #528bff;
    }
    Label {
        padding: 0 0;
    }
    #comments-panel {
        width: 1fr;
        background: #21252b;
        padding: 0 1;
        scrollbar-color: #3e4451;
    }
    #comments-text {
        width: 100%;
    }
    /* ── Add Comment modal ── */
    AddCommentScreen {
        align: center middle;
    }
    #add-comment-dialog {
        width: 70;
        height: auto;
        max-height: 20;
        background: #282c34;
        border: thick #528bff;
        padding: 1 2;
    }
    #dialog-title {
        margin-bottom: 1;
    }
    #dialog-context {
        margin-bottom: 1;
        color: #6b7280;
    }
    #comment-input {
        margin-bottom: 1;
    }
    #dialog-btns {
        height: auto;
        align: right middle;
    }
    #dialog-btns Button {
        margin-left: 1;
    }
    /* ── Help modal ── */
    HelpScreen {
        align: center middle;
    }
    #help-dialog {
        width: 72;
        height: auto;
        max-height: 35;
        background: #282c34;
        border: thick #528bff;
        padding: 1 2;
    }
    #help-title {
        margin-bottom: 1;
        text-align: center;
    }
    #help-body {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("left,bracketleft", "prev_file", "Prev file"),
        Binding("right,bracketright", "next_file", "Next file"),
        Binding("question_mark", "help", "Help"),
    ]

    file_idx: reactive[int] = reactive(0, init=False)

    def __init__(self, repo_path: str = ".") -> None:
        super().__init__()
        self.repo_path = repo_path
        self.store = CommentStore(Path(repo_path) / ".rev")
        diff_text, self.diff_desc = get_git_diff(repo_path)
        self.diff_files: List[DiffFile] = parse_diff(diff_text) if diff_text else []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield FileSelectorBar(self.diff_files, id="file-bar")
        with Horizontal(id="main-body"):
            if self.diff_files:
                with ContentSwitcher(id="diff-switcher", initial="file-0"):
                    for i, df in enumerate(self.diff_files):
                        yield DiffViewer(df, self.store, id=f"file-{i}")
            else:
                yield Static(
                    f"\n[bold yellow]No diff found.[/bold yellow]\n\n"
                    f"[dim]{self.diff_desc}[/dim]\n\n"
                    "[dim]Run revtui from a git repository that has uncommitted changes.[/dim]",
                    id="no-diff-msg",
                )
            yield CommentsPanel(self.store, id="comments-panel")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "revtui"
        self.sub_title = self.diff_desc
        if self.diff_files:
            self.file_idx = 0
            self._sync_file_bar()
            # Focus the first viewer
            self.call_after_refresh(lambda: self.query_one("#file-0", DiffViewer).focus())
        else:
            self.query_one(FileSelectorBar).update_for(0, 0)

    def watch_file_idx(self, _old: int, new: int) -> None:
        if not self.diff_files:
            return
        switcher = self.query_one("#diff-switcher", ContentSwitcher)
        switcher.current = f"file-{new}"
        self._sync_file_bar()
        panel = self.query_one(CommentsPanel)
        panel.update_comments(self.diff_files[new], None)
        # Focus the newly visible viewer
        self.call_after_refresh(lambda: self.query_one(f"#file-{new}", DiffViewer).focus())

    def _sync_file_bar(self) -> None:
        if not self.diff_files:
            return
        idx = self.file_idx
        df = self.diff_files[idx]
        cnt = len(self.store.get_comments(file=df.new_path))
        self.query_one(FileSelectorBar).update_for(idx, cnt)

    # ── File switching ───────────────────────────

    def action_prev_file(self) -> None:
        if self.diff_files:
            self.file_idx = max(0, self.file_idx - 1)

    def action_next_file(self) -> None:
        if self.diff_files:
            self.file_idx = min(len(self.diff_files) - 1, self.file_idx + 1)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    # ── Message handlers ────────────────────────

    def on_diff_viewer_line_changed(self, event: DiffViewer.LineChanged) -> None:
        panel = self.query_one(CommentsPanel)
        panel.update_comments(event.diff_file, event.line)
        self._sync_file_bar()
