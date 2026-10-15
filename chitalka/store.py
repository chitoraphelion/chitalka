"""Хранилище комментариев: один JSON-файл в проекте.

Файл пишут и сервер читалки, и консольные команды агентов, поэтому каждое
изменение идёт под файловой блокировкой и записывается атомарно.
"""
import fcntl
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

STORE_DIR = "kommentarii"
STORE_NAME = "kommentarii.json"
LEGACY = Path("notes") / "kommentarii.json"
DOC_NAME = "HOW_TO_USE_CHITALKA.md"

CATEGORIES = {"typo", "rewrite", "fact", "ask", "idea"}
STATUSES = {"open", "done"}


def store_path(root: Path) -> Path:
    """kommentarii/kommentarii.json, а в старых проектах — notes/kommentarii.json."""
    new = root / STORE_DIR / STORE_NAME
    old = root / LEGACY
    if not new.exists() and old.exists():
        return old
    return new


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_name("." + path.name + ".lock")

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self) -> list:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            broken = self.path.with_suffix(f".broken-{int(time.time())}.json")
            self.path.rename(broken)
            return []
        return [c for c in data if isinstance(c, dict) and c.get("id")] if isinstance(data, list) else []

    def save(self, items: list) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    @contextmanager
    def edit(self):
        """with store.edit() as items: ... — изменения сохранятся по выходу."""
        with self.locked():
            items = self.load()
            yield items
            self.save(items)

    def read(self) -> list:
        with self.locked():
            return self.load()


def new_comment(data: dict, source) -> dict:
    cat = data.get("category")
    return {
        "id": uuid.uuid4().hex[:10],
        "created": now(),
        "status": "open",
        "category": cat if cat in CATEGORIES else "rewrite",
        "page": data.get("page"),
        "pageEnd": data.get("pageEnd") or data.get("page"),
        "chapter": data.get("chapter", ""),
        "quote": data.get("quote", ""),
        "comment": data.get("comment", ""),
        "suggestion": data.get("suggestion", ""),
        "ctx": data.get("ctx") if isinstance(data.get("ctx"), dict) else None,
        "anchor": data.get("anchor") if isinstance(data.get("anchor"), dict) else None,
        "source": source,
        "reply": "",
        "thread": [],
    }


def messages(c: dict) -> list:
    out = [{"who": "ai", "text": c["reply"]}] if c.get("reply") else []
    return out + [m for m in c.get("thread") or [] if isinstance(m, dict)]


def waiting(c: dict) -> bool:
    """Открыт и последнее слово за автором: агенту нужно ответить."""
    if c.get("status") == "done":
        return False
    m = messages(c)
    return not m or m[-1].get("who") != "ai"
