"""Хранилище комментариев: один JSON-файл в проекте.

Файл пишут и сервер читалки, и консольные команды агентов, поэтому каждое
изменение идёт под файловой блокировкой и записывается атомарно. Чтение
блокировки не берёт и ничего не создаёт: открытие документа и `chitalka list`
не оставляют в проекте ни папки, ни lock-файла. Папка, файл и памятка агентам
появляются при первом сохранённом замечании (или по явному `chitalka init`).
"""
import fcntl
import json
import time
import uuid
from contextlib import contextmanager
from importlib import resources
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

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self, rename_broken: bool = True) -> list:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if not rename_broken:                     # читатель без блокировки не трогает файл
                return []
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
        """Без блокировки и без создания файлов: запись атомарна (tmp + replace)."""
        return self.load(rename_broken=False)


DOC_MARK = "<!-- chitalka-doc"


def write_doc(store_file: Path) -> Path:
    """Памятка агентам рядом с файлом комментариев; свою старую версию обновляет."""
    doc = store_file.parent / DOC_NAME
    text = (resources.files("chitalka") / "agent_doc.md").read_text(encoding="utf-8")
    text = text.replace("{STORE}", store_file.name)
    if doc.exists() and not doc.read_text(encoding="utf-8").startswith(DOC_MARK):
        return doc                                   # файл переписан человеком — не трогаем
    if not doc.exists() or doc.read_text(encoding="utf-8") != text:
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(text, encoding="utf-8")
    return doc


def write_error(path: Path, e: OSError) -> str:
    """Сообщение об ошибке записи, понятное в интерфейсе."""
    import errno
    if e.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        why = "папка только для чтения или нет прав на запись"
    elif e.errno == errno.ENOSPC:
        why = "нет места на диске"
    else:
        why = e.strerror or str(e)
    return f"Не сохранено: {why} ({path}). Текст остался в редакторе."


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
        "document": data.get("document"),
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
