"""Comment storage and management for code review."""
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


@dataclass
class Comment:
    id: str
    file: str
    old_lineno: Optional[int]
    new_lineno: Optional[int]
    line_type: str
    line_content: str
    content: str
    author: str  # 'human' | 'agent'
    agent_name: Optional[str]
    timestamp: str
    status: str  # 'open' | 'resolved'

    @property
    def line_ref(self) -> str:
        if self.new_lineno is not None:
            return f"L{self.new_lineno}"
        if self.old_lineno is not None:
            return f"-L{self.old_lineno}"
        return "?"

    @property
    def author_label(self) -> str:
        if self.author == "agent":
            return f"🤖 {self.agent_name or 'agent'}"
        return "👤 human"

    @property
    def short_id(self) -> str:
        return self.id[:8]


class CommentStore:
    def __init__(self, rev_dir: Optional[Path] = None):
        self.rev_dir = Path(rev_dir) if rev_dir else Path(".rev")
        self.rev_dir.mkdir(exist_ok=True)
        self._file = self.rev_dir / "comments.json"
        self._comments: List[Comment] = []
        self.load()

    def load(self) -> None:
        if not self._file.exists():
            self._comments = []
            return
        try:
            data = json.loads(self._file.read_text())
            self._comments = [Comment(**c) for c in data.get("comments", [])]
        except Exception:
            self._comments = []

    def save(self) -> None:
        data = {"comments": [asdict(c) for c in self._comments]}
        self._file.write_text(json.dumps(data, indent=2))

    def add_comment(
        self,
        file: str,
        content: str,
        author: str = "human",
        agent_name: Optional[str] = None,
        old_lineno: Optional[int] = None,
        new_lineno: Optional[int] = None,
        line_type: str = "context",
        line_content: str = "",
    ) -> Comment:
        comment = Comment(
            id=str(uuid.uuid4()),
            file=file,
            old_lineno=old_lineno,
            new_lineno=new_lineno,
            line_type=line_type,
            line_content=line_content,
            content=content,
            author=author,
            agent_name=agent_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="open",
        )
        self._comments.append(comment)
        self.save()
        return comment

    def get_comments(
        self,
        file: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Comment]:
        result = list(self._comments)
        if file is not None:
            result = [c for c in result if c.file == file]
        if status is not None:
            result = [c for c in result if c.status == status]
        return result

    def resolve(self, comment_id: str) -> Optional[Comment]:
        for c in self._comments:
            if c.id == comment_id or c.id.startswith(comment_id):
                c.status = "resolved"
                self.save()
                return c
        return None

    def delete(self, comment_id: str) -> bool:
        before = len(self._comments)
        self._comments = [c for c in self._comments if not c.id.startswith(comment_id)]
        changed = len(self._comments) < before
        if changed:
            self.save()
        return changed

    @property
    def all_comments(self) -> List[Comment]:
        return list(self._comments)
