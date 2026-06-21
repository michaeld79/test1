"""Main Textual TUI for code review."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.markup import escape
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button, ContentSwitcher, Footer, Header, Input, Label, Static, Tree,
)

from .comment_store import Comment, CommentStore
from .diff_parser import DiffFile, DiffLine, get_git_diff, parse_diff

# ──────────────────────────────────────────────
#  Diff line rendering
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


# ──────────────────────────────────────────────
#  Comment panel rendering
# ──────────────────────────────────────────────

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
        _append_comment(t, c, c.id in on_line)
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
#  FileTree sidebar
# ──────────────────────────────────────────────

class FileTree(Tree):
    """Left sidebar: tree of changed files with diff stats and comment counts."""

    can_focus = True

    class FileSelected(Message):
        def __init__(self, file_idx: int) -> None:
            super().__init__()
            self.file_idx = file_idx

    def __init__(self, diff_files: List[DiffFile], store: CommentStore, **kwargs: Any) -> None:
        super().__init__("Changed Files", **kwargs)
        self.diff_files = diff_files
        self.store = store
        self._file_nodes: Dict[int, Any] = {}  # file_idx → TreeNode
        # Guard counter: suppress NodeHighlighted events caused by select_idx()
        self._move_guard = 0
        self.root.expand()

    def on_mount(self) -> None:
        self._rebuild()
        if self._file_nodes:
            self.call_after_refresh(lambda: self.move_cursor(self._file_nodes[0]))

    # ── Building the tree ───────────────────────

    def _rebuild(self) -> None:
        self.root.remove_children()
        self._file_nodes = {}

        groups: Dict[str, List[tuple]] = defaultdict(list)
        for i, df in enumerate(self.diff_files):
            p = Path(df.new_path)
            parent = str(p.parent) if len(p.parts) > 1 else ""
            groups[parent].append((i, df))

        for parent in sorted(groups.keys()):
            if parent:
                dir_node = self.root.add(
                    Text(f"{parent}/", style="bold #888888"),
                    expand=True,
                )
            else:
                dir_node = self.root

            for idx, df in groups[parent]:
                node = dir_node.add_leaf(self._file_label(idx, df), data=idx)
                self._file_nodes[idx] = node

    def _file_label(self, idx: int, df: DiffFile) -> Text:
        """Rich label: filename  +adds  -dels  H:n  A:n"""
        comments = self.store.get_comments(file=df.new_path)
        human_open  = sum(1 for c in comments if c.author == "human"  and c.status == "open")
        agent_open  = sum(1 for c in comments if c.author == "agent"  and c.status == "open")

        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(Path(df.new_path).name, style="white")

        if df.additions or df.deletions:
            t.append("  ")
        if df.additions:
            t.append(f"+{df.additions}", style="green")
        if df.deletions:
            t.append(" " if df.additions else "")
            t.append(f"-{df.deletions}", style="red")

        if human_open:
            t.append(f"  H:{human_open}", style="bold yellow")
        if agent_open:
            t.append(f"  A:{agent_open}", style="bold cyan")

        return t

    # ── Public API ──────────────────────────────

    def refresh_stats(self) -> None:
        """Refresh line counts and comment badges without rebuilding the tree."""
        for idx, node in self._file_nodes.items():
            node.label = self._file_label(idx, self.diff_files[idx])

    def select_idx(self, idx: int) -> None:
        """Move tree cursor to the node for file index `idx` (no FileSelected event)."""
        node = self._file_nodes.get(idx)
        if node:
            self._move_guard += 1
            self.move_cursor(node)

    # ── Event handlers ──────────────────────────

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Fires on every cursor movement — use to switch files as you arrow through."""
        if self._move_guard > 0:
            self._move_guard -= 1
            return
        if event.node.data is not None:
            self.post_message(self.FileSelected(event.node.data))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter key — also fires FileSelected and transfers focus to diff view."""
        if event.node.data is not None:
            self.post_message(self.FileSelected(event.node.data))


# ──────────────────────────────────────────────
#  DiffViewer widget
# ──────────────────────────────────────────────

class DiffViewer(VerticalScroll):
    """Scrollable, cursor-driven diff view."""

    can_focus = True
    BINDINGS = [
        Binding("j,down", "move_down", "↓", show=False),
        Binding("k,up",   "move_up",   "↑", show=False),
        Binding("ctrl+d", "page_down", "PgDn", show=False),
        Binding("ctrl+u", "page_up",   "PgUp", show=False),
        Binding("g", "go_top",    "Top",    show=False),
        Binding("G", "go_bottom", "Bottom", show=False),
        Binding("c", "add_comment",     "Comment"),
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
        self._known_ids: set[str] = set()

    def compose(self) -> ComposeResult:
        if not self.diff_file.lines:
            yield Static("[dim]No diff content for this file.[/dim]")
            return
        for i, line in enumerate(self.diff_file.lines):
            lbl = Label(make_line_text(line), id=f"dl-{i}")
            self._labels.append(lbl)
            yield lbl

    def on_mount(self) -> None:
        self._known_ids = {c.id for c in self.store.all_comments}
        self.set_interval(1.5, self._auto_refresh)
        if self.diff_file.lines:
            self.call_after_refresh(self._set_initial_cursor)

    def _set_initial_cursor(self) -> None:
        self.cursor_idx = 0

    async def _auto_refresh(self) -> None:
        """Reload comments; notify on new arrivals; refresh tree stats."""
        self.store.load()
        current_ids = {c.id for c in self.store.all_comments}
        new_ids = current_ids - self._known_ids

        if new_ids:
            for c in self.store.all_comments:
                if c.id in new_ids:
                    badge = f"🤖 {c.agent_name or 'agent'}" if c.author == "agent" else "👤 human"
                    preview = c.content[:50] + ("…" if len(c.content) > 50 else "")
                    self.app.notify(
                        f"{badge} · {c.file}:{c.line_ref}\n{preview}",
                        title="New comment",
                        severity="information",
                        timeout=6,
                    )
            self._known_ids = current_ids
            # Refresh sidebar badges
            try:
                self.app.query_one(FileTree).refresh_stats()
            except Exception:
                pass

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
            return

        if 0 <= old < n:
            labels[old].update(make_line_text(self.diff_file.lines[old], selected=False))
        if 0 <= new < n:
            labels[new].update(make_line_text(self.diff_file.lines[new], selected=True))
            labels[new].scroll_visible()

        line = self.diff_file.lines[new] if 0 <= new < n else None
        self.post_message(self.LineChanged(new, line, self.diff_file))

    # ── Navigation actions ───────────────────────

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

    # ── Comment actions ──────────────────────────

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
                try:
                    self.app.query_one(FileTree).refresh_stats()
                except Exception:
                    pass
                self.app.notify(f"Resolved [{c.short_id}]", severity="information")
                return
        self.app.notify("No open comment on this line.", severity="warning")

    def _after_comment(self, _: Any) -> None:
        n = len(self.diff_file.lines)
        current = self.diff_file.lines[self.cursor_idx] if 0 <= self.cursor_idx < n else None
        self.app.query_one(CommentsPanel).update_comments(self.diff_file, current)
        try:
            self.app.query_one(FileTree).refresh_stats()
        except Exception:
            pass


# ──────────────────────────────────────────────
#  CommentsPanel
# ──────────────────────────────────────────────

class CommentsPanel(VerticalScroll):
    """Right panel: comments for the current diff file / cursor line."""

    def __init__(self, store: CommentStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.store = store

    def compose(self) -> ComposeResult:
        yield Static("", id="comments-text")

    def update_comments(self, diff_file: Optional[DiffFile], line: Optional[DiffLine]) -> None:
        display = self.query_one("#comments-text", Static)
        if diff_file is None:
            display.update(Text("Select a file to see comments.", style="dim"))
            return
        display.update(make_comment_text(self.store, diff_file, line))


# ──────────────────────────────────────────────
#  Add Comment modal
# ──────────────────────────────────────────────

class AddCommentScreen(ModalScreen[None]):
    """Modal for writing a review comment."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, diff_file: DiffFile, diff_line: DiffLine, store: CommentStore) -> None:
        super().__init__()
        self.diff_file = diff_file
        self.diff_line = diff_line
        self.store = store

    def compose(self) -> ComposeResult:
        line = self.diff_line
        loc = (
            f"L{line.new_lineno}" if line.new_lineno is not None
            else f"-L{line.old_lineno}" if line.old_lineno is not None
            else "header"
        )
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
  [yellow]j / ↓[/yellow]       Move diff cursor down
  [yellow]k / ↑[/yellow]       Move diff cursor up
  [yellow]Ctrl+D / Ctrl+U[/yellow]  Page down / up
  [yellow]g / G[/yellow]       Jump to top / bottom
  [yellow]Tab[/yellow]         Switch focus: tree ↔ diff ↔ comments
  [yellow]↑ / ↓ (tree)[/yellow]  Browse files — diff preview follows cursor
  [yellow]Enter (tree)[/yellow]    Select file and focus diff

[bold]Comments[/bold]
  [yellow]c[/yellow]           Add comment on cursor line
  [yellow]r[/yellow]           Resolve open comment on cursor line

[bold]Agent CLI[/bold]
  [cyan]python -m revtui add-comment --file FILE --line LINE \\
          --message "MSG" --agent-name NAME[/cyan]
  [cyan]python -m revtui watch[/cyan]          Live comment feed
  [cyan]python -m revtui list-comments[/cyan]  All comments (JSON: --json)
  [cyan]python -m revtui status[/cyan]         Summary

[bold]Other[/bold]
  [yellow]?[/yellow]           Toggle this help
  [yellow]q[/yellow]           Quit
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q",      "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(
                "[bold reverse]  revtui — Code Review TUI  [/bold reverse]",
                id="help-title",
            )
            yield Static(_HELP, id="help-body")
            yield Button("Close  [dim](Esc)[/dim]", id="btn-close")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss()


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
    #main-body {
        height: 1fr;
    }

    /* ── File tree sidebar ── */
    FileTree {
        width: 28;
        background: #1a1d24;
        border-right: solid #3e4451;
        scrollbar-color: #3e4451;
        padding: 0;
    }
    FileTree > .tree--guides {
        color: #3e4451;
    }
    FileTree > .tree--guides-selected {
        color: #528bff;
    }
    FileTree > .tree--cursor {
        background: #2c313a;
    }
    FileTree:focus > .tree--cursor {
        background: #2c313a;
    }

    /* ── Diff viewer ── */
    ContentSwitcher {
        width: 1fr;
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

    /* ── Comments panel ── */
    #comments-panel {
        width: 30;
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
        max-height: 38;
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
        Binding("q",             "quit",      "Quit"),
        Binding("question_mark", "help",      "Help"),
        Binding("tab",           "focus_next","Focus next", show=False),
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
        with Horizontal(id="main-body"):
            yield FileTree(self.diff_files, self.store, id="file-tree")
            if self.diff_files:
                with ContentSwitcher(id="diff-switcher", initial="file-0"):
                    for i, df in enumerate(self.diff_files):
                        yield DiffViewer(df, self.store, id=f"file-{i}")
            else:
                yield Static(
                    f"\n[bold yellow]No diff found.[/bold yellow]\n\n"
                    f"[dim]{self.diff_desc}[/dim]\n\n"
                    "[dim]Run revtui from a git repository with uncommitted changes.[/dim]",
                    id="no-diff-msg",
                )
            yield CommentsPanel(self.store, id="comments-panel")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "revtui"
        self.sub_title = self.diff_desc
        if self.diff_files:
            self.file_idx = 0
            # Focus the tree first so the user can immediately browse files
            self.call_after_refresh(lambda: self.query_one(FileTree).focus())

    def watch_file_idx(self, _old: int, new: int) -> None:
        if not self.diff_files:
            return
        # Switch the diff pane
        self.query_one("#diff-switcher", ContentSwitcher).current = f"file-{new}"
        # Update the right comment panel
        self.query_one(CommentsPanel).update_comments(self.diff_files[new], None)
        # Sync tree cursor without triggering FileSelected again
        self.query_one(FileTree).select_idx(new)
        # Focus the diff viewer
        self.call_after_refresh(lambda: self.query_one(f"#file-{new}", DiffViewer).focus())

    # ── Message handlers ─────────────────────────

    def on_file_tree_file_selected(self, event: FileTree.FileSelected) -> None:
        self.file_idx = event.file_idx

    def on_diff_viewer_line_changed(self, event: DiffViewer.LineChanged) -> None:
        self.query_one(CommentsPanel).update_comments(event.diff_file, event.line)

    # ── Actions ──────────────────────────────────

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
