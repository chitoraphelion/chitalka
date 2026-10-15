"""«Открыть в редакторе»: файл:строка → nvim.

По умолчанию — новая вкладка в том окне kitty, где запущена читалка
(kitty @ launch, нужен allow_remote_control yes); иначе — новое окно kitty.
Свой вариант: --editor или $CHITALKA_EDITOR, шаблон с {file} {line} {root},
например "kitty @ launch --type=tab nvim +{line} {file}".
"""
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def resolve(root: Path, file: str) -> Path:
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"нет файла {file} в проекте")
    return path


def raise_kitty():
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", 'tell application "kitty" to activate'],
                       capture_output=True, timeout=3)


def open_in_editor(root: Path, file: str, line: int, template: str | None = None) -> str:
    path = resolve(root, file)
    line = max(1, int(line))
    template = template or os.environ.get("CHITALKA_EDITOR")
    if template:
        cmd = [part.format(file=str(path), line=line, root=str(root)) for part in shlex.split(template)]
        subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "editor"
    kitty = shutil.which("kitty")
    if not kitty:
        raise RuntimeError("kitty не найден — задайте --editor 'команда {file} {line}'")
    nvim = ["nvim", f"+{line}", "+normal! zz", str(path)]
    if os.environ.get("KITTY_WINDOW_ID"):
        r = subprocess.run([kitty, "@", "launch", "--type=tab", "--cwd", str(root),
                            "--tab-title", f"{path.name}:{line}", *nvim],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            raise_kitty()
            return "kitty-tab"
    subprocess.Popen([kitty, "--single-instance", "--directory", str(root), *nvim],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    raise_kitty()
    return "kitty-window"
