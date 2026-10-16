"""Document identity and Markdown source locations shared by CLI and HTTP API."""
import hashlib
import os
from pathlib import Path

MARKDOWN_SUFFIXES = {".md", ".markdown"}
DOCUMENT_SUFFIXES = MARKDOWN_SUFFIXES | {".pdf"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".avif": "image/avif", ".svg": "image/svg+xml", ".ico": "image/x-icon"}


def is_markdown(path):
    return bool(path and Path(path).suffix.lower() in MARKDOWN_SUFFIXES)


def document_id(path, root):
    if not path:
        return None
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)  # explicitly opened PDFs can live outside the source project


def safe_path(root, relative):
    path = (Path(root).resolve() / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Файл должен находиться внутри проекта")
    return path


def markdown_snapshot(path, root):
    with Path(path).open("rb") as file:
        data = file.read()
        stat = os.fstat(file.fileno())
    text = data.decode("utf-8-sig")
    return {"kind": "markdown", "document": document_id(path, root), "name": Path(path).name,
            "text": text, "revision": hashlib.sha256(data).hexdigest(),
            "mtime": stat.st_mtime_ns / 1_000_000_000, "lines": max(1, len(text.splitlines()))}


def markdown_source(path, root, data, snapshot=None):
    snapshot = snapshot or markdown_snapshot(path, root)
    start, end = data.get("sourceLine"), data.get("sourceLineEnd")
    if isinstance(start, bool) or not isinstance(start, int) or start < 1 or start > snapshot["lines"]:
        raise ValueError("Выделение не содержит корректной строки Markdown")
    if end is None:
        end = start
    if isinstance(end, bool) or not isinstance(end, int) or end < start or end > snapshot["lines"]:
        raise ValueError("Некорректный диапазон строк Markdown")
    result = {"file": document_id(path, root), "line": start, "how": "markdown"}
    if end > start:
        result["lineEnd"] = end
    return result
