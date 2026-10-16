"""Discover all readers, including readers started before the registry existed."""
import argparse
import json
from pathlib import Path

from .processes import discover, process_table, terminate


def list_sessions(root=None, table=None):
    table = process_table() if table is None else table
    items = discover("chitalka", table)
    if root:
        items = [s for s in items if s["root"] == str(Path(root).expanduser().resolve())]
    # A tracked latexmk is a child of the reader, not another reader session.
    children = {pid for s in items for pid in s["children"]}
    return [s for s in items if s["pid"] not in children]


def stop_sessions(pid=None, root=None, all_sessions=False, force=False, timeout=8):
    if pid is not None and pid <= 1:
        raise ValueError("PID должен быть больше 1")
    if all_sessions and (pid or root):
        raise ValueError("--all нельзя совмещать с PID или --root")
    table = process_table()
    sessions = list_sessions(table=table)
    if all_sessions:
        selected = sessions
    elif pid:
        selected = [s for s in sessions if s["pid"] == int(pid)]
    else:
        selected = [s for s in sessions if s["root"] == str(Path(root or Path.cwd()).expanduser().resolve())]
    if pid and not selected:
        raise ValueError(f"Запущенная сессия chitalka не найдена: {pid}")
    result = terminate([s["pid"] for s in selected], table, timeout=timeout, force=force)
    result["sessions"] = [s["pid"] for s in selected]
    return result


def command(cmd, argv):
    parser = argparse.ArgumentParser(prog=f"chitalka {cmd}")
    parser.add_argument("--root")
    parser.add_argument("--json", action="store_true")
    if cmd == "stop":
        parser.add_argument("pid", nargs="?", type=int)
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--force", action="store_true", help="SIGKILL оставшихся после SIGTERM")
        parser.add_argument("--timeout", type=float, default=8)
    else:
        parser.add_argument("--ids", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if cmd == "stop":
        result = stop_sessions(args.pid, args.root, args.all, args.force, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
              f"Остановлены PID: {result['stopped'] or '-'}; остались: {result['remaining'] or '-'}")
        return 1 if result["remaining"] or result["errors"] else 0
    items = list_sessions(args.root)
    if args.ids:
        print("\n".join(str(item["pid"]) for item in items))
    elif args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for item in items:
            print(f"PID {item['pid']}  {item['kind']}  {item['root'] or '(проект неизвестен)'}  "
                  f"{item.get('details', {}).get('url', '')}  "
                  f"дочерние: {','.join(map(str, item['children'])) or '-'}")
        if not items:
            print("Нет запущенных сессий chitalka.")
    return 0
