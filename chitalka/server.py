"""HTTP-сервер читалки: отдаёт PDF/Markdown, ресурсы и API комментариев (только 127.0.0.1)."""
import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .editor import open_in_editor
from .locate import locate
from . import notes as personal
from .store import CATEGORIES, STATUSES, Store, new_comment, now, write_doc, write_error
from .documents import DOCUMENT_SUFFIXES, IMAGE_TYPES, document_id, is_markdown, markdown_snapshot, markdown_source, safe_path

STATIC = resources.files("chitalka") / "static"
LOCAL_ORIGIN = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$")
EDITABLE = ("comment", "status", "category", "suggestion", "reply_seen")
TYPES = {".js": "text/javascript", ".html": "text/html; charset=utf-8", ".css": "text/css",
         ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf"}


@dataclass
class Config:
    root: Path
    pdf: Path | None          # явно заданный PDF/Markdown; None — искать по умолчанию
    store: Store
    font: str
    title: str = ""
    builder: Any = None       # build.Builder при --watch
    editor: str | None = None  # шаблон команды редактора

    def pdf_path(self):
        p = self.document_path()
        return p if p and not is_markdown(p) else None

    def document_path(self):
        cands = [self.pdf] if self.pdf else [self.root / "main.pdf", self.root / "build" / "main.pdf"]
        for p in cands:
            if p and p.exists():
                return p
        if self.pdf or (self.root / "main.tex").exists():
            return None
        for name in ("main.md", "README.md", "readme.md"):
            if (self.root / name).is_file():
                return self.root / name
        return None

    @property
    def kind(self):
        return "markdown" if is_markdown(self.pdf or self.document_path()) else "pdf"

    @property
    def document(self):
        return document_id(self.pdf or self.document_path(), self.root)


def make_handler(cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 — тихий сервер
            return

        def send(self, code: int, body: bytes | str | dict | list = b"",
                 ctype: str = "application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if ctype.startswith("image/"):
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox")
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return None
            return data if isinstance(data, dict) else None

        def foreign(self, need_json=True):
            """Запросы только со своей страницы: защита от чужих сайтов."""
            origin = self.headers.get("Origin")
            if origin and not LOCAL_ORIGIN.match(origin):
                return True
            return need_json and "application/json" not in (self.headers.get("Content-Type") or "")

        # ------------------------------------------------------------ GET
        def document_config(self):
            chosen = parse_qs(urlsplit(self.path).query).get("document", [None])[0]
            if chosen is None:
                return cfg
            try:
                path = safe_path(cfg.root, chosen)
            except ValueError:
                self.send(403, {"error": "Документ вне проекта"})
                return None
            if path.suffix.lower() not in DOCUMENT_SUFFIXES or not path.is_file():
                self.send(404, {"error": "Документ не найден"})
                return None
            return replace(cfg, pdf=path)

        def belongs(self, comment, current):
            if comment.get("document"):
                return comment["document"] == current.document
            return current.kind == "pdf"  # preserve legacy PDF annotations

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                html = (STATIC / "index.html").read_text(encoding="utf-8")
                html = html.replace("/*CHITALKA_FONT*/", f"--font:{cfg.font};")
                project = hashlib.sha256(str(cfg.root).encode()).hexdigest()[:12]
                html = html.replace("/*CHITALKA_PROJECT*/", project)
                return self.send(200, html, TYPES[".html"])
            if path in ("/markdown.js", "/markdown.css"):
                f = STATIC / path[1:]
                return self.send(200, f.read_bytes(), TYPES[Path(path).suffix])
            if path.startswith("/vendor/"):
                relative = Path(unquote(path).removeprefix("/vendor/"))
                if relative.is_absolute() or ".." in relative.parts:
                    return self.send(403, {"error": "Запрещённый путь"})
                f = STATIC / "vendor" / str(relative)
                if f.is_file():
                    return self.send(200, f.read_bytes(), TYPES.get(relative.suffix, "application/octet-stream"))
                return self.send(404, {"error": "нет файла"})
            if path.startswith("/assets/"):
                try:
                    f = safe_path(cfg.root, unquote(path).removeprefix("/assets/"))
                except ValueError:
                    return self.send(403, {"error": "Файл вне проекта"})
                if f.is_file() and f.suffix.lower() in IMAGE_TYPES:
                    return self.send(200, f.read_bytes(), IMAGE_TYPES[f.suffix.lower()])
                return self.send(404, {"error": "Изображение не найдено"})
            current = self.document_config()
            if current is None:
                return
            if path == "/book.pdf":
                p = current.pdf_path()
                if not p:
                    return self.send(404, {"error": "PDF не найден — соберите статью"})
                return self.send(200, p.read_bytes(), "application/pdf")
            if path == "/api/info":
                p = current.pdf_path()
                return self.send(200, {"root": str(cfg.root), "title": cfg.title, "watch": bool(cfg.builder),
                                       "store": str(cfg.store.path), "pdf": str(p) if p else None,
                                       "kind": current.kind, "document": current.document, "markdown": True,
                                       "notes": True})
            if path == "/api/markdown":
                p = current.document_path()
                if not p or not is_markdown(p):
                    return self.send(404, {"error": "Markdown не выбран"})
                try:
                    return self.send(200, markdown_snapshot(p, cfg.root))
                except (OSError, UnicodeError, ValueError) as e:
                    return self.send(400, {"error": f"Не удалось прочитать документ: {e}"})
            if path == "/api/pdfinfo":
                p = current.document_path()
                return self.send(200, {"mtime": p.stat().st_mtime_ns / 1_000_000_000 if p else 0,
                                       "name": p.name if p else None, "kind": current.kind,
                                       "build": cfg.builder.info() if cfg.builder and current.kind == "pdf" else None})
            if path == "/api/comments":
                return self.send(200, [c for c in cfg.store.read() if self.belongs(c, current)])
            if path == "/api/notes":
                doc = current.document_path()
                if not doc:
                    return self.send(404, {"error": "Документ не найден"})
                sidecar = personal.notes_path(doc)
                try:
                    items = personal.read(sidecar)
                except personal.NotesError as e:
                    return self.send(200, {"notes": [], "path": str(sidecar), "error": str(e)})
                return self.send(200, {"notes": items, "path": str(sidecar)})
            return self.send(404, {"error": "не найдено"})

        def notes_call(self, current, path, data=None, method="POST"):
            """Личные заметки: отдельный sidecar, не агентское хранилище."""
            doc = current.document_path()
            if not doc:
                return self.send(404, {"error": "Документ не найден"})
            sidecar, name = personal.notes_path(doc), Path(doc).name
            m = re.match(r"/api/notes(?:/(n\w+))?$", path)
            try:
                if method == "DELETE" and m and m.group(1):
                    personal.delete(sidecar, name, m.group(1))
                    return self.send(200, {"ok": True})
                if method == "POST" and m and m.group(1):
                    return self.send(200, personal.update(sidecar, name, m.group(1), data))
                if method == "POST" and m:
                    return self.send(200, personal.add(sidecar, name, data))
            except personal.NotesError as e:
                return self.send(e.status, {"error": str(e)})
            return self.send(404, {"error": "не найдено"})

        # ------------------------------------------------------------ POST
        def do_POST(self):
            path = urlsplit(self.path).path
            if self.foreign():
                return self.send(403, {"error": "запрещено"})
            data = self.body()
            if data is None:
                return self.send(400, {"error": "неверный JSON"})
            for key in ("quote", "comment", "suggestion", "chapter", "text", "category", "reply_seen"):
                if data.get(key) is not None and not isinstance(data[key], str):
                    return self.send(400, {"error": f"поле {key} должно быть строкой"})
            for key in ("page", "pageEnd"):
                if data.get(key) is not None and not isinstance(data[key], int):
                    return self.send(400, {"error": f"поле {key} должно быть числом"})
            if "status" in data and data["status"] not in STATUSES:
                return self.send(400, {"error": "неверный статус"})
            current = self.document_config()
            if current is None:
                return

            if path == "/api/open":                  # открыть файл:строку в редакторе
                try:
                    how = open_in_editor(cfg.root, str(data.get("file") or ""), int(data.get("line") or 1), cfg.editor)
                except (ValueError, RuntimeError, OSError) as e:
                    return self.send(400, {"error": str(e)})
                return self.send(200, {"ok": True, "how": how})

            if path == "/api/notes" or path.startswith("/api/notes/"):
                return self.notes_call(current, path, data)

            if path == "/api/comments":
                if current.kind == "markdown":
                    try:
                        snapshot = markdown_snapshot(current.document_path(), cfg.root)
                    except (OSError, UnicodeError, TypeError, ValueError):
                        return self.send(409, {"error": "Markdown недоступен. Дождитесь сохранения файла и обновите документ."})
                    if data.get("documentRevision") != snapshot["revision"]:
                        return self.send(409, {"error": "Markdown изменился. Обновите документ и выделите фрагмент снова; текст комментария можно сохранить в черновик."})
                    try:
                        source = markdown_source(current.document_path(), cfg.root, data, snapshot)
                    except ValueError as e:
                        return self.send(400, {"error": str(e)})
                else:
                    source = locate(cfg.root, current.pdf_path(), data)
                item = new_comment({**data, "document": current.document}, source)
                try:                                  # папка и памятка — только при первом замечании
                    with cfg.store.edit() as items:
                        items.append(item)
                except OSError as e:
                    return self.send(500, {"error": write_error(cfg.store.path.parent, e)})
                try:
                    write_doc(cfg.store.path)
                except OSError:
                    pass                              # замечание сохранено; памятка не обязательна
                return self.send(200, item)

            m = re.match(r"/api/comments/(\w+)(/thread)?$", path)
            if not m or not cfg.store.exists():
                return self.send(404, {"error": "не найдено" if not m else "нет комментария"})
            try:
                with cfg.store.edit() as items:
                    it = next((c for c in items if c["id"] == m.group(1)), None)
                    if it is None or not self.belongs(it, current):
                        return self.send(404, {"error": "нет комментария"})
                    if m.group(2):                       # автор дописал уточнение
                        text = (data.get("text") or "").strip()
                        if text:
                            it.setdefault("thread", []).append({"who": "author", "text": text, "at": now()})
                            it["status"] = "open"
                    else:
                        for key in EDITABLE:
                            if key in data:
                                it[key] = data[key]
                        if it.get("category") not in CATEGORIES:
                            it["category"] = "rewrite"
            except OSError as e:
                return self.send(500, {"error": write_error(cfg.store.path.parent, e)})
            return self.send(200, it)

        def do_DELETE(self):
            if self.foreign(need_json=False):
                return self.send(403, {"error": "запрещено"})
            current = self.document_config()
            if current is None:
                return
            path = urlsplit(self.path).path
            if path.startswith("/api/notes/"):
                return self.notes_call(current, path, method="DELETE")
            m = re.match(r"/api/comments/(\w+)$", path)
            if not m or not cfg.store.exists():
                return self.send(404, {"error": "не найдено"})
            try:
                with cfg.store.edit() as items:
                    items[:] = [c for c in items if c["id"] != m.group(1) or not self.belongs(c, current)]
            except OSError as e:
                return self.send(500, {"error": write_error(cfg.store.path.parent, e)})
            return self.send(200, {"ok": True})

    return Handler


def serve(cfg: Config, port: int):
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg))
