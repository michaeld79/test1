"""Parse git diff output into structured data."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import subprocess
import re


@dataclass
class DiffLine:
    line_type: str  # 'addition' | 'deletion' | 'context' | 'hunk_header' | 'file_header' | 'binary'
    content: str
    old_lineno: Optional[int] = None
    new_lineno: Optional[int] = None


@dataclass
class DiffFile:
    old_path: str
    new_path: str
    is_new: bool = False
    is_deleted: bool = False
    is_renamed: bool = False
    lines: List[DiffLine] = field(default_factory=list)

    @property
    def display_path(self) -> str:
        if self.is_new:
            return f"{self.new_path} [new]"
        if self.is_deleted:
            return f"{self.old_path} [deleted]"
        if self.is_renamed:
            return f"{self.old_path} → {self.new_path}"
        return self.new_path

    @property
    def additions(self) -> int:
        return sum(1 for l in self.lines if l.line_type == "addition")

    @property
    def deletions(self) -> int:
        return sum(1 for l in self.lines if l.line_type == "deletion")


def parse_diff(diff_text: str) -> List[DiffFile]:
    files: List[DiffFile] = []
    current: Optional[DiffFile] = None
    old_lineno = 0
    new_lineno = 0
    in_content = False

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            in_content = False
            if current is not None:
                files.append(current)
            m = re.match(r"diff --git a/(.*) b/(.*)", raw)
            if m:
                current = DiffFile(old_path=m.group(1), new_path=m.group(2))
            else:
                current = DiffFile(old_path="unknown", new_path="unknown")
            current.lines.append(DiffLine("file_header", raw))
            continue

        if current is None:
            continue

        if not in_content:
            if raw.startswith("new file mode"):
                current.is_new = True
                current.lines.append(DiffLine("file_header", raw))
            elif raw.startswith("deleted file mode"):
                current.is_deleted = True
                current.lines.append(DiffLine("file_header", raw))
            elif raw.startswith("rename from") or raw.startswith("rename to"):
                current.is_renamed = True
                current.lines.append(DiffLine("file_header", raw))
            elif raw.startswith(
                ("index ", "old mode", "new mode", "similarity index", "copy from", "copy to")
            ):
                current.lines.append(DiffLine("file_header", raw))
            elif raw.startswith("--- "):
                current.lines.append(DiffLine("file_header", raw))
            elif raw.startswith("+++ "):
                current.lines.append(DiffLine("file_header", raw))
                in_content = True
            elif raw.startswith("Binary files"):
                current.lines.append(DiffLine("binary", raw))
            continue

        if raw.startswith("@@ "):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", raw)
            if m:
                old_lineno = int(m.group(1))
                new_lineno = int(m.group(2))
            current.lines.append(DiffLine("hunk_header", raw))
        elif raw.startswith("+"):
            current.lines.append(DiffLine("addition", raw[1:], None, new_lineno))
            new_lineno += 1
        elif raw.startswith("-"):
            current.lines.append(DiffLine("deletion", raw[1:], old_lineno, None))
            old_lineno += 1
        elif raw.startswith("\\ "):
            pass  # "No newline at end of file"
        else:
            content = raw[1:] if raw.startswith(" ") else raw
            current.lines.append(DiffLine("context", content, old_lineno, new_lineno))
            old_lineno += 1
            new_lineno += 1

    if current is not None and current.lines:
        files.append(current)

    return files


def get_git_diff(repo_path: str = ".") -> Tuple[str, str]:
    """Return (diff_text, description). Tries HEAD, staged, then HEAD~1..HEAD."""

    def run(*args: str) -> str:
        try:
            r = subprocess.run(
                ["git", "diff"] + list(args),
                capture_output=True,
                text=True,
                cwd=repo_path,
            )
            return r.stdout
        except Exception:
            return ""

    text = run("HEAD")
    if text.strip():
        return text, "Changes vs HEAD"

    text = run("--staged")
    if text.strip():
        return text, "Staged changes"

    text = run("HEAD~1", "HEAD")
    if text.strip():
        return text, "Last commit"

    return "", "No changes found"
