import argparse
import json
from pathlib import Path

from .completion_support import candidates, paths
from .store import store_path

COMMANDS = ("list", "show", "reply", "done", "reopen", "init", "where", "sessions", "ps", "stop", "completion")


def parser():
    p = argparse.ArgumentParser(prog="chitalka")
    p.add_argument("pdf", nargs="?")
    p.add_argument("-p", "--port")
    p.add_argument("--root")
    p.add_argument("--font")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("-w", "--watch", action="store_true")
    p.add_argument("--engine", choices=["pdflatex", "xelatex", "lualatex"])
    p.add_argument("--editor")
    p.add_argument("-V", "--version", action="store_true")
    sub = p.add_subparsers()
    for name in COMMANDS:
        cmd = sub.add_parser(name)
        cmd.add_argument("--root")
        if name == "list":
            for flag in ("--all", "--done", "--json"):
                cmd.add_argument(flag, action="store_true")
        if name in ("show", "reply", "reopen", "done"):
            cmd.add_argument("id", nargs="+" if name == "done" else None)
        if name == "reply":
            cmd.add_argument("text")
            cmd.add_argument("--done", action="store_true")
        if name == "done":
            cmd.add_argument("-m", "--message")
        if name in ("sessions", "ps", "stop"):
            cmd.add_argument("--json", action="store_true")
        if name == "stop":
            cmd.add_argument("pid", nargs="?")
            cmd.add_argument("--all", action="store_true")
            cmd.add_argument("--force", action="store_true")
            cmd.add_argument("--timeout")
        if name == "completion":
            cmd.add_argument("shell", choices=["zsh", "bash"])
            cmd.add_argument("--install", action="store_true")
    return p


def complete(words):
    root = Path.cwd()
    if "--root" in words and words.index("--root") + 1 < len(words) - 1:
        root = Path(words[words.index("--root") + 1]).expanduser()
    def dynamic(chain, dest, prefix, _):
        if dest == "root":
            return paths(prefix, directories=True)
        if not chain and dest == "pdf":
            return list(COMMANDS) + [p for p in paths(prefix) if p.lower().endswith(("/", ".pdf", ".md", ".markdown", ".ipynb"))]
        if chain[:1] == ["stop"] and dest == "pid":
            try:
                from .sessions import list_sessions
                return [str(item["pid"]) for item in list_sessions()]
            except RuntimeError:
                return []
        if dest == "id":
            try:
                items = json.loads(store_path(root).read_text())
                return [item["id"] for item in items if isinstance(item, dict) and item.get("id")]
            except (OSError, ValueError, TypeError):
                return []
        return None
    return candidates(parser(), words, dynamic)


def command(argv):
    p = argparse.ArgumentParser(prog="chitalka completion")
    p.add_argument("shell", choices=["zsh", "bash"])
    p.add_argument("--install", action="store_true")
    args = p.parse_args(argv)
    from .completion_support import install, script
    print(install("chitalka", args.shell) if args.install else script("chitalka", args.shell),
          end="\n" if args.install else "")
    return 0
