"""Личные заметки автора (клавиша N): sidecar `<документ>.notes.json` рядом с PDF/Markdown.

Это не поручения агенту: заметки не попадают в `chitalka list/show/reply`,
в API агентских комментариев, экспорт и памятку. Файл создаётся только
при первом сохранении. Блокировка — в XDG state, чтобы рядом с документом
не появлялось ничего, кроме самого sidecar; запись атомарная (tmp + rename).
"""
import errno
import fcntl
import hashlib
import json
import os
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

NOTES_SUFFIX = ".notes.json"
FORMAT = "chitalka-personal-notes"
LIMITS = {"text": 50_000, "quote": 10_000, "chapter": 500}


class NotesError(Exception):
    """Понятная пользователю ошибка чтения или сохранения заметок."""

    def __init__(self, message, status=500):
        super().__init__(message)
        self.status = status


def notes_path(document) -> Path:
    """`article.pdf` → `article.pdf.notes.json` рядом с настоящим файлом документа."""
    real = Path(document).resolve()
    return real.with_name(real.name + NOTES_SUFFIX)


def _lock_file(sidecar: Path) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "chitalka" / "locks"
    return base / (hashlib.sha256(str(sidecar).encode()).hexdigest()[:32] + ".lock")


def _refuse_link(sidecar: Path):
    try:
        info = os.lstat(sidecar)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise NotesError(f"{sidecar.name} — символическая ссылка; заметки через ссылки не читаются и не пишутся", 409)
    if not stat.S_ISREG(info.st_mode):
        raise NotesError(f"{sidecar.name} — не обычный файл", 409)


def read(sidecar: Path) -> list:
    """Список заметок; отсутствующий файл — пустой список, без побочных эффектов."""
    _refuse_link(sidecar)
    try:
        fd = os.open(sidecar, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise NotesError(f"Не удалось прочитать {sidecar.name}: {e.strerror}", 409) from e
    with os.fdopen(fd, "rb") as f:
        raw = f.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as e:
        raise NotesError(f"{sidecar.name} повреждён ({e}); исправьте или переименуйте файл — "
                         "читалка не перезапишет его", 409) from e
    notes = data.get("notes") if isinstance(data, dict) else data
    if not isinstance(notes, list):
        raise NotesError(f"{sidecar.name}: неизвестный формат, ожидается {{\"notes\": [...]}}", 409)
    return [n for n in notes if isinstance(n, dict) and isinstance(n.get("id"), str)]


def _write(sidecar: Path, notes: list, document_name: str):
    _refuse_link(sidecar)
    payload = {"format": FORMAT, "version": 1, "document": document_name,
               "about": "Личные заметки автора из chitalka (клавиша N). Не поручения агенту.",
               "notes": notes}
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        fd, tmp = tempfile.mkstemp(dir=sidecar.parent, prefix="." + sidecar.name + ".", suffix=".tmp")
    except OSError as e:
        raise NotesError(_write_hint(sidecar, e)) from e
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if sidecar.exists():
            os.chmod(tmp, stat.S_IMODE(os.stat(sidecar).st_mode))
        os.replace(tmp, sidecar)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise NotesError(_write_hint(sidecar, e)) from e


def _write_hint(sidecar: Path, e: OSError) -> str:
    if e.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        why = "папка только для чтения или нет прав на запись"
    elif e.errno == errno.ENOSPC:
        why = "нет места на диске"
    else:
        why = e.strerror or str(e)
    return f"Заметка не сохранена: {why} ({sidecar.parent}). Текст остался в редакторе."


@contextmanager
def _locked(sidecar: Path):
    lock = _lock_file(sidecar)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        f = open(lock, "w")
    except OSError as e:
        raise NotesError(f"Не удалось взять блокировку заметок ({lock}): {e.strerror}") from e
    with f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _clean(data: dict, partial=False) -> dict:
    out = {}
    for key, limit in LIMITS.items():
        if key in data and data[key] is not None:
            if not isinstance(data[key], str):
                raise NotesError(f"поле {key} должно быть строкой", 400)
            if len(data[key]) > limit:
                raise NotesError(f"поле {key} длиннее {limit} символов", 400)
            out[key] = data[key]
    for key in ("page", "pageEnd"):
        if key in data and data[key] is not None:
            if isinstance(data[key], bool) or not isinstance(data[key], int) or data[key] < 1:
                raise NotesError(f"поле {key} должно быть номером страницы", 400)
            out[key] = data[key]
    ctx = data.get("ctx")
    if isinstance(ctx, dict):
        out["ctx"] = {k: ctx[k][:200] for k in ("before", "after") if isinstance(ctx.get(k), str)}
    if not partial and not (out.get("text") or "").strip():
        raise NotesError("Пустую заметку сохранять не нужно", 400)
    return out


def add(sidecar: Path, document_name: str, data: dict) -> dict:
    fields = _clean(data)
    note = {"id": "n" + uuid.uuid4().hex[:10], "created": time.strftime("%Y-%m-%d %H:%M"),
            "quote": "", "page": None, "pageEnd": None, "chapter": "", "ctx": None, **fields}
    note["text"] = note["text"].strip()
    note["pageEnd"] = note.get("pageEnd") or note.get("page")
    with _locked(sidecar):
        notes = read(sidecar)
        notes.append(note)
        _write(sidecar, notes, document_name)
    return note


def update(sidecar: Path, document_name: str, note_id: str, data: dict) -> dict:
    fields = _clean({"text": data.get("text")})
    with _locked(sidecar):
        notes = read(sidecar)
        note = next((n for n in notes if n.get("id") == note_id), None)
        if note is None:
            raise NotesError("Заметка не найдена", 404)
        note["text"] = fields["text"].strip()
        note["updated"] = time.strftime("%Y-%m-%d %H:%M")
        _write(sidecar, notes, document_name)
    return note


def delete(sidecar: Path, document_name: str, note_id: str) -> None:
    if not os.path.lexists(sidecar):
        raise NotesError("Заметка не найдена", 404)
    with _locked(sidecar):
        notes = read(sidecar)
        kept = [n for n in notes if n.get("id") != note_id]
        if len(kept) == len(notes):
            raise NotesError("Заметка не найдена", 404)
        _write(sidecar, kept, document_name)
