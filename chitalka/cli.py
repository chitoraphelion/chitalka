"""chitalka — читалка PDF-статьи с комментариями для агента.

Запуск читалки (из корня проекта: main.tex в ., сборка в . или ./build):
    chitalka [PDF] [-p PORT] [--no-browser] [--root DIR] [--font FONT]

Команды для агентов (работают с тем же файлом комментариев):
    chitalka list [--all|--done] [--json]   открытые комментарии, ждущие ответа
    chitalka show ID                        один комментарий целиком (JSON)
    chitalka reply ID ТЕКСТ [--done]        ответить автору (и закрыть)
    chitalka done ID [ID ...] [-m ТЕКСТ]    закрыть
    chitalka reopen ID                      вернуть в работу
    chitalka init                           создать kommentarii/ и памятку агентам
    chitalka where                          пути: проект, PDF, файл комментариев
"""
import argparse
import json
import os
import re
import signal
import sys
import threading
import urllib.request
import webbrowser
from importlib import resources
from pathlib import Path

from . import __version__
from .build import Builder
from .server import Config, serve
from .store import DOC_NAME, Store, messages, now, store_path, waiting

DEFAULT_PORT = 8765
COMMANDS = {"list", "show", "reply", "done", "reopen", "init", "where"}
DOC_MARK = "<!-- chitalka-doc"


# ------------------------------------------------------------------ окружение
def kitty_font() -> str:
    conf = Path(os.environ.get("KITTY_CONFIG_DIRECTORY", Path.home() / ".config" / "kitty")) / "kitty.conf"
    try:
        for line in conf.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*font_family\s+(.+?)\s*$", line)
            if m and m.group(1) != "monospace":
                return m.group(1)
    except OSError:
        pass
    return ""


def font_stack(name: str) -> str:
    fams = [f'"{name}"', f'"{name} Mono"'] if name else []
    return ", ".join(fams + ["ui-monospace", '"SF Mono"', "Menlo", "monospace"])


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


def find_root(args) -> Path:
    return Path(args.root).expanduser().resolve() if args.root else Path.cwd()


# ------------------------------------------------------------------ читалка
def probe(port: int):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=1) as r:
            return json.loads(r.read())
    except Exception:
        return None


def cmd_open(argv):
    p = argparse.ArgumentParser(prog="chitalka", description="Читалка PDF-статьи с комментариями.",
                                epilog="Команды для агентов: chitalka list|show|reply|done|reopen|init|where --help")
    p.add_argument("pdf", nargs="?", help="PDF (по умолчанию ./main.pdf, затем ./build/main.pdf)")
    p.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--root", help="корень проекта с main.tex (по умолчанию текущая папка)")
    p.add_argument("--font", help="шрифт интерфейса (по умолчанию font_family из kitty.conf)")
    p.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    p.add_argument("-w", "--watch", action="store_true",
                   help="запустить latexmk -pvc -synctex=1 и подхватывать новые сборки автоматически")
    p.add_argument("--engine", choices=["pdflatex", "xelatex", "lualatex"],
                   help="движок для --watch (по умолчанию .latexmkrc или подсказка в main.tex)")
    p.add_argument("--editor", help="команда редактора с {file} {line} {root} "
                                    "(по умолчанию nvim во вкладке kitty; также $CHITALKA_EDITOR)")
    p.add_argument("-V", "--version", action="version", version=f"chitalka {__version__}")
    args = p.parse_args(argv)

    root = find_root(args)
    pdf = Path(args.pdf).expanduser().resolve() if args.pdf else None
    if pdf and not pdf.exists():
        p.error(f"нет файла {pdf}")
    store_file = store_path(root)
    doc = write_doc(store_file)
    cfg = Config(root=root, pdf=pdf, store=Store(store_file), font=font_stack(args.font or kitty_font()),
                 title=root.name, editor=args.editor)

    server = None
    for port in range(args.port, args.port + 20):
        info = probe(port)
        if info:
            if info.get("root") == str(root):
                url = f"http://127.0.0.1:{port}/"
                print(f"Читалка этого проекта уже работает: {url}")
                if not args.no_browser:
                    webbrowser.open(url)
                return 0
            continue
        try:
            server = serve(cfg, port)
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"Нет свободного порта в {args.port}–{args.port + 19}")

    url = f"http://127.0.0.1:{server.server_port}/"
    if args.watch:
        if not (root / "main.tex").exists():
            sys.exit(f"--watch: нет {root / 'main.tex'}")
        outdir = "build" if (pdf and pdf.parent == root / "build") or (not pdf and (root / "build").is_dir()
                                                                     and not (root / "main.pdf").exists()) else None
        cfg.builder = Builder(root, store_file.parent / "latexmk.log", args.engine, outdir).start()
        print(f"Сборка: {' '.join(cfg.builder.cmd)}\n  лог: {cfg.builder.log}", flush=True)
    found = cfg.pdf_path()
    print(f"Читалка: {url}\n  PDF: {found or 'ещё не собран (main.pdf или build/main.pdf)'}\n"
          f"  Комментарии: {store_file}\n  Памятка агентам: {doc}\nОстановить: Ctrl+C", flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    def stop_on_signal(signum, frame):                 # закрыли терминал или kill: тоже гасим latexmk
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop_on_signal)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nГотово.")
    finally:
        if cfg.builder:
            cfg.builder.stop()
    return 0


# ------------------------------------------------------------------ агентам
def short(text: str | None, n: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def fmt(c: dict) -> str:
    src = c.get("source") or {}
    where = f"{src['file']}:{src['line']}" + (f"-{src['lineEnd']}" if src.get("lineEnd") else "") \
        + f" ({src.get('how', 'words')})" if src.get("file") else "место в .tex не найдено"
    out = [f"[{c['id']}] {c.get('status', 'open')} · {c.get('category', 'rewrite')} · стр. {c.get('page')}"
           f" · {where}",
           f"  цитата: {short(c.get('quote'))}"]
    if c.get("comment"):
        out.append(f"  комментарий: {short(c['comment'], 2000)}")
    if c.get("suggestion"):
        out.append(f"  предложено: {short(c['suggestion'], 2000)}")
    for m in messages(c):
        out.append(f"  {'ИИ' if m.get('who') == 'ai' else 'автор'}: {short(m.get('text'), 2000)}")
    return "\n".join(out)


def agent_parser(cmd):
    p = argparse.ArgumentParser(prog=f"chitalka {cmd}")
    p.add_argument("--root", help="корень проекта (по умолчанию текущая папка)")
    return p


def cmd_agent(cmd, argv):
    p = agent_parser(cmd)
    if cmd == "list":
        g = p.add_mutually_exclusive_group()
        g.add_argument("--all", action="store_true", help="все комментарии")
        g.add_argument("--done", action="store_true", help="только закрытые")
        p.add_argument("--json", action="store_true", help="вывести JSON")
    elif cmd in ("show", "reopen"):
        p.add_argument("id")
    elif cmd == "reply":
        p.add_argument("id")
        p.add_argument("text", help="ответ; «-» — прочитать из stdin")
        p.add_argument("--done", action="store_true", help="и закрыть комментарий")
    elif cmd == "done":
        p.add_argument("ids", nargs="+")
        p.add_argument("-m", "--message", help="заодно ответить этим текстом")
    args = p.parse_args(argv)
    root = find_root(args)
    store_file = store_path(root)
    store = Store(store_file)

    if cmd == "where":
        cfg = Config(root=root, pdf=None, store=store, font="")
        print(f"проект: {root}\nPDF: {cfg.pdf_path()}\nкомментарии: {store_file}\nпамятка: {store_file.parent / DOC_NAME}")
        return 0
    if cmd == "init":
        store_file.parent.mkdir(parents=True, exist_ok=True)
        if not store_file.exists():
            store.save([])
        print(write_doc(store_file))
        return 0
    if cmd == "list":
        items = store.read()
        sel = items if args.all else [c for c in items if c.get("status") == "done"] if args.done \
            else [c for c in items if waiting(c)]
        sel.sort(key=lambda c: (c.get("page") or 0, c.get("created") or ""))
        if args.json:
            print(json.dumps(sel, ensure_ascii=False, indent=2))
        else:
            print("\n\n".join(fmt(c) for c in sel) if sel else "Нет комментариев, ждущих ответа.")
        return 0
    if cmd == "show":
        c = next((c for c in store.read() if c["id"] == args.id), None)
        if not c:
            sys.exit(f"нет комментария {args.id}")
        print(json.dumps(c, ensure_ascii=False, indent=2))
        return 0

    ids = args.ids if cmd == "done" else [args.id]
    text = getattr(args, "text", None) or getattr(args, "message", None)
    if text == "-":
        text = sys.stdin.read()
    with store.edit() as items:
        found = {c["id"]: c for c in items if c["id"] in ids}
        missing = [i for i in ids if i not in found]
        if missing:
            sys.exit(f"нет комментариев: {', '.join(missing)}")
        for c in found.values():
            if text and text.strip():
                c.setdefault("thread", []).append({"who": "ai", "text": text.strip(), "at": now()})
            if cmd == "done" or getattr(args, "done", False):
                c["status"] = "done"
            elif cmd == "reopen":
                c["status"] = "open"
    print(f"{cmd}: {', '.join(ids)}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return cmd_agent(argv[0], argv[1:])
    return cmd_open(argv)


if __name__ == "__main__":
    sys.exit(main())
