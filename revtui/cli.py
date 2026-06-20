"""CLI entry point for revtui — both TUI launcher and agent comment tool."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from .comment_store import CommentStore
from .diff_parser import get_git_diff, parse_diff


def _store(repo: str) -> CommentStore:
    return CommentStore(Path(repo) / ".rev")


# ──────────────────────────────────────────────
#  Root command
# ──────────────────────────────────────────────

@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--repo", default=".", show_default=True, help="Path to git repository.")
@click.pass_context
def main(ctx: click.Context, repo: str) -> None:
    """Code review TUI for reviewing agent-written code.

    Run without a subcommand to launch the interactive TUI.
    Use subcommands for scripted / agent use.
    """
    ctx.ensure_object(dict)
    ctx.obj["repo"] = repo
    if ctx.invoked_subcommand is None:
        _launch_tui(repo)


def _launch_tui(repo: str) -> None:
    from .app import ReviewApp
    app = ReviewApp(repo_path=repo)
    app.run()


# ──────────────────────────────────────────────
#  comment group
# ──────────────────────────────────────────────

@main.group()
def comment() -> None:
    """Add, list, or resolve review comments."""


@comment.command("add")
@click.option("--file", "-f", "filepath", required=True, help="File path relative to repo root.")
@click.option("--line", "-l", "lineno", type=int, default=None, help="New-file line number.")
@click.option("--old-line", type=int, default=None, help="Old-file line number (deletions).")
@click.option("--message", "-m", required=True, help="Comment text.")
@click.option(
    "--agent-name",
    default=None,
    help="Agent identifier. If provided, comment is marked as authored by an agent.",
)
@click.pass_context
def comment_add(
    ctx: click.Context,
    filepath: str,
    lineno: Optional[int],
    old_line: Optional[int],
    message: str,
    agent_name: Optional[str],
) -> None:
    """Add a review comment.  Intended for agent use.

    \b
    Example (agent):
        python -m revtui comment add \\
            --file src/main.py --line 42 \\
            --message "This logic is incorrect" \\
            --agent-name claude
    """
    repo = ctx.obj["repo"]
    store = _store(repo)

    # Try to look up the diff line for context
    diff_text, _ = get_git_diff(repo)
    line_content = ""
    line_type = "context"
    if diff_text:
        files = parse_diff(diff_text)
        for df in files:
            if df.new_path == filepath or df.old_path == filepath:
                for dl in df.lines:
                    if lineno and dl.new_lineno == lineno:
                        line_content = dl.content
                        line_type = dl.line_type
                        break
                    if old_line and dl.old_lineno == old_line:
                        line_content = dl.content
                        line_type = dl.line_type
                        break

    author = "agent" if agent_name else "human"
    c = store.add_comment(
        file=filepath,
        content=message,
        author=author,
        agent_name=agent_name,
        new_lineno=lineno,
        old_lineno=old_line,
        line_type=line_type,
        line_content=line_content,
    )

    click.echo(f"Added comment [{c.short_id}]")
    click.echo(f"  file:    {c.file}")
    if c.new_lineno:
        click.echo(f"  line:    {c.new_lineno}")
    elif c.old_lineno:
        click.echo(f"  old line:{c.old_lineno}")
    click.echo(f"  author:  {c.author_label}")
    click.echo(f"  status:  {c.status}")
    click.echo(f"  message: {c.content[:80]}")


@comment.command("list")
@click.option("--file", "-f", "filepath", default=None, help="Filter by file path.")
@click.option("--open-only", is_flag=True, help="Show only open (unresolved) comments.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.pass_context
def comment_list(
    ctx: click.Context,
    filepath: Optional[str],
    open_only: bool,
    as_json: bool,
) -> None:
    """List review comments."""
    repo = ctx.obj["repo"]
    store = _store(repo)
    status = "open" if open_only else None
    comments = store.get_comments(file=filepath, status=status)

    if as_json:
        from dataclasses import asdict
        click.echo(json.dumps([asdict(c) for c in comments], indent=2))
        return

    if not comments:
        click.echo("No comments found.")
        return

    for c in comments:
        icon = "✓" if c.status == "resolved" else "●"
        click.echo(
            f"[{c.short_id}] {icon} {c.author_label}  "
            f"{c.file}:{c.line_ref}  —  {c.content[:60]}"
        )


@comment.command("resolve")
@click.argument("comment_id")
@click.pass_context
def comment_resolve(ctx: click.Context, comment_id: str) -> None:
    """Resolve a comment by ID (prefix match works)."""
    repo = ctx.obj["repo"]
    store = _store(repo)
    c = store.resolve(comment_id)
    if c:
        click.echo(f"Resolved [{c.short_id}]: {c.content[:60]}")
    else:
        click.echo(f"Comment not found: {comment_id}", err=True)
        sys.exit(1)


@comment.command("delete")
@click.argument("comment_id")
@click.pass_context
def comment_delete(ctx: click.Context, comment_id: str) -> None:
    """Delete a comment by ID (prefix match works)."""
    repo = ctx.obj["repo"]
    store = _store(repo)
    if store.delete(comment_id):
        click.echo(f"Deleted comment {comment_id}")
    else:
        click.echo(f"Comment not found: {comment_id}", err=True)
        sys.exit(1)


# ──────────────────────────────────────────────
#  Convenience commands
# ──────────────────────────────────────────────

@main.command("add-comment")
@click.option("--file", "-f", "filepath", required=True, help="File path.")
@click.option("--line", "-l", "lineno", type=int, default=None, help="New-file line number.")
@click.option("--old-line", type=int, default=None, help="Old-file line number.")
@click.option("--message", "-m", required=True, help="Comment text.")
@click.option("--agent-name", default=None, help="Agent identifier.")
@click.pass_context
def add_comment_shortcut(
    ctx: click.Context,
    filepath: str,
    lineno: Optional[int],
    old_line: Optional[int],
    message: str,
    agent_name: Optional[str],
) -> None:
    """Shortcut for 'comment add' — agent-friendly."""
    ctx.invoke(
        comment_add,
        filepath=filepath,
        lineno=lineno,
        old_line=old_line,
        message=message,
        agent_name=agent_name,
    )


@main.command("list-comments")
@click.option("--file", "-f", "filepath", default=None)
@click.option("--open-only", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def list_comments_shortcut(
    ctx: click.Context, filepath: Optional[str], open_only: bool, as_json: bool
) -> None:
    """Shortcut for 'comment list' — agent-friendly."""
    ctx.invoke(comment_list, filepath=filepath, open_only=open_only, as_json=as_json)


@main.command("resolve")
@click.argument("comment_id")
@click.pass_context
def resolve_shortcut(ctx: click.Context, comment_id: str) -> None:
    """Shortcut for 'comment resolve' — agent-friendly."""
    ctx.invoke(comment_resolve, comment_id=comment_id)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show a review summary: changed files and comment counts."""
    repo = ctx.obj["repo"]
    store = _store(repo)
    diff_text, desc = get_git_diff(repo)

    click.echo(f"Diff:  {desc}")
    click.echo()

    if not diff_text:
        click.echo("No changes found.")
        return

    files = parse_diff(diff_text)
    click.echo(f"Files changed: {len(files)}")
    for df in files:
        comments = store.get_comments(file=df.new_path)
        open_cnt = sum(1 for c in comments if c.status == "open")
        res_cnt = len(comments) - open_cnt
        flag = " ⚠" if open_cnt else ""
        click.echo(
            f"  {df.display_path:<50}  +{df.additions}/-{df.deletions}"
            f"  [{open_cnt} open, {res_cnt} resolved]{flag}"
        )

    click.echo()
    all_open = store.get_comments(status="open")
    all_resolved = store.get_comments(status="resolved")
    click.echo(f"Total comments: {len(store.all_comments)}  "
               f"({len(all_open)} open, {len(all_resolved)} resolved)")


@main.command("files")
@click.pass_context
def list_files(ctx: click.Context) -> None:
    """List files changed in the current diff."""
    repo = ctx.obj["repo"]
    diff_text, desc = get_git_diff(repo)
    if not diff_text:
        click.echo(f"No changes ({desc})")
        return
    files = parse_diff(diff_text)
    for df in files:
        click.echo(df.new_path)


# ──────────────────────────────────────────────
#  watch command
# ──────────────────────────────────────────────

@main.command()
@click.option("--interval", default=1.0, show_default=True, help="Poll interval in seconds.")
@click.option("--file", "-f", "filepath", default=None, help="Filter to a specific file.")
@click.pass_context
def watch(ctx: click.Context, interval: float, filepath: Optional[str]) -> None:
    """Watch for new comments in real-time.

    Displays a live-updating table.  New comments that arrive after the
    watch starts are highlighted in yellow.  Press Ctrl+C to exit.

    \b
    Example:
        python -m revtui watch
        python -m revtui watch --file src/main.py --interval 0.5
    """
    import time
    from rich.console import Console
    from rich.live import Live
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    repo = ctx.obj["repo"]
    store = _store(repo)

    # Snapshot of IDs that existed before we started watching
    store.load()
    pre_existing_ids: set[str] = {c.id for c in store.all_comments}
    seen_new_ids: set[str] = set()

    console = Console()

    def _build_table() -> Panel:
        store.load()
        comments = store.get_comments(file=filepath)
        comments = sorted(comments, key=lambda c: c.timestamp)

        table = Table(
            show_header=True,
            header_style="bold white",
            expand=True,
            show_edge=False,
            padding=(0, 1),
        )
        table.add_column("Time", style="dim", width=10, no_wrap=True)
        table.add_column("Author", width=20, no_wrap=True)
        table.add_column("File", width=28, no_wrap=True)
        table.add_column("Line", width=6, no_wrap=True)
        table.add_column("St", width=4, no_wrap=True)
        table.add_column("Message")

        new_count = 0
        for c in comments:
            is_new = c.id not in pre_existing_ids
            if is_new:
                new_count += 1
                seen_new_ids.add(c.id)

            time_s = c.timestamp[11:19]

            if c.author == "agent":
                author = Text(f"🤖 {c.agent_name or 'agent'}", style="cyan")
            else:
                author = Text("👤 human", style="yellow")

            status_t = Text(
                "✓" if c.status == "resolved" else "●",
                style="green" if c.status == "resolved" else "bright_white",
            )
            msg_text = Text(c.content[:70] + ("…" if len(c.content) > 70 else ""))

            if is_new:
                time_t = Text(f"★ {time_s}", style="bold yellow")
                row_style = "bold"
                msg_text.stylize("bold yellow")
            else:
                time_t = Text(time_s, style="dim")
                row_style = ""

            table.add_row(time_t, author, c.file, c.line_ref, status_t, msg_text, style=row_style)

        total = len(comments)
        open_cnt = sum(1 for c in comments if c.status == "open")
        subtitle = (
            f"[dim]{total} comment(s) · {open_cnt} open[/dim]"
            f"  [bold yellow]{new_count} new[/bold yellow]"
            if new_count
            else f"[dim]{total} comment(s) · {open_cnt} open[/dim]"
        )

        filter_label = f" · [dim]{filepath}[/dim]" if filepath else ""
        return Panel(
            table,
            title=f"[bold]revtui watch[/bold]{filter_label}  [dim](Ctrl+C to exit)[/dim]",
            subtitle=subtitle,
            border_style="blue",
        )

    with Live(_build_table(), console=console, refresh_per_second=4, screen=False) as live:
        try:
            while True:
                time.sleep(interval)
                live.update(_build_table())
        except KeyboardInterrupt:
            pass

    console.print()
    console.print(f"[dim]Watch stopped. {len(seen_new_ids)} new comment(s) received.[/dim]")
