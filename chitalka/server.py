"""HTTP-сервер читалки: отдаёт страницу, PDF и API комментариев (только 127.0.0.1)."""
import json
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from .locate import locate
from .store import CATEGORIES, STATUSES, Store, new_comment, now

STATIC = resources.files("chitalka") / "static"
LOCAL_ORIGIN = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$")
EDITABLE = ("comment", "status", "category", "suggestion", "reply_seen")
TYPES = {".js": "text/javascript", ".html": "text/html; charset=utf-8", ".css": "text/css"}


@dataclass
class Config:
    root: Path
    pdf: Path | None          # явно заданный PDF; None — искать по умолчанию
    store: Store
    font: str
    title: str = ""

    def pdf_path(self):
        cands = [self.pdf] if self.pdf else [self.root / "main.pdf", self.root / "build" / "main.pdf"]
        for p in cands:
            if p and p.exists():
                return p
        return None


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
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                html = (STATIC / "index.html").read_text(encoding="utf-8")
                html = html.replace("/*CHITALKA_FONT*/", f"--font:{cfg.font};")
                return self.send(200, html, TYPES[".html"])
            if path.startswith("/vendor/"):
                f = STATIC / "vendor" / Path(path).name
                if f.is_file():
                    return self.send(200, f.read_bytes(), TYPES.get(Path(path).suffix, "application/octet-stream"))
                return self.send(404, {"error": "нет файла"})
            if path == "/book.pdf":
                p = cfg.pdf_path()
                if not p:
                    return self.send(404, {"error": "PDF не найден — соберите статью"})
                return self.send(200, p.read_bytes(), "application/pdf")
            if path == "/api/info":
                p = cfg.pdf_path()
                return self.send(200, {"root": str(cfg.root), "title": cfg.title,
                                       "store": str(cfg.store.path), "pdf": str(p) if p else None})
            if path == "/api/pdfinfo":
                p = cfg.pdf_path()
                return self.send(200, {"mtime": p.stat().st_mtime if p else 0, "name": p.name if p else None})
            if path == "/api/comments":
                return self.send(200, cfg.store.read())
            return self.send(404, {"error": "не найдено"})

        # ------------------------------------------------------------ POST
        def do_POST(self):
            path = self.path.split("?")[0]
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

            if path == "/api/comments":
                item = new_comment(data, locate(cfg.root, cfg.pdf_path(), data))
                with cfg.store.edit() as items:
                    items.append(item)
                return self.send(200, item)

            m = re.match(r"/api/comments/(\w+)(/thread)?$", path)
            if not m:
                return self.send(404, {"error": "не найдено"})
            with cfg.store.edit() as items:
                it = next((c for c in items if c["id"] == m.group(1)), None)
                if it is None:
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
            return self.send(200, it)

        def do_DELETE(self):
            if self.foreign(need_json=False):
                return self.send(403, {"error": "запрещено"})
            m = re.match(r"/api/comments/(\w+)$", self.path)
            if not m:
                return self.send(404, {"error": "не найдено"})
            with cfg.store.edit() as items:
                items[:] = [c for c in items if c["id"] != m.group(1)]
            return self.send(200, {"ok": True})

    return Handler


def serve(cfg: Config, port: int):
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg))
