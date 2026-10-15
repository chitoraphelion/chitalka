"""chitalka --watch: latexmk -pvc в фоне и состояние сборки для читалки."""
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

ERR_LINE = re.compile(r"^(?P<file>[^\s:][^:]*\.(?:tex|sty|cls|bib)):(?P<line>\d+): (?P<msg>.+)$")
RUN_START = re.compile(r"^(Latexmk: applying rule|Run number \d+ of rule|Rule '[^']+': )")
FAILED = re.compile(r"^(Latexmk: Errors, so I did not complete|Collected error summary|Latexmk: Failure)")
WATCHING = re.compile(r"^=== Watching for updated files")


def engine_flag(root: Path, engine: str | None) -> list:
    """-xelatex/-lualatex/-pdf: из --engine, иначе по подсказке в начале main.tex."""
    if engine:
        return [f"-{engine}" if engine != "pdflatex" else "-pdf"]
    if (root / ".latexmkrc").exists() or (root / "latexmkrc").exists():
        return []                                    # проект сам знает, чем собираться
    try:
        head = "\n".join((root / "main.tex").read_text(encoding="utf-8", errors="replace").splitlines()[:15]).lower()
    except OSError:
        return ["-pdf"]
    if "xelatex" in head or "\\usepackage{fontspec}" in head:
        return ["-xelatex"]
    if "lualatex" in head:
        return ["-lualatex"]
    return ["-pdf"]


class Builder:
    def __init__(self, root: Path, log: Path, engine: str | None = None, outdir: str | None = None):
        self.root, self.log = root, log
        self.cmd = ["latexmk", "-pvc", "-view=none", "-synctex=1", "-interaction=nonstopmode",
                    "-file-line-error", *engine_flag(root, engine),
                    *([f"-outdir={outdir}"] if outdir else []), "main.tex"]
        self.state, self.errors, self.changed = "starting", [], time.time()
        self.tail = deque(maxlen=60)
        self._failed, self.proc = False, None

    def start(self):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(self.cmd, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, errors="replace", start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()
        return self

    def _set(self, state):
        if state != self.state:
            self.state, self.changed = state, time.time()

    def _read(self):
        assert self.proc and self.proc.stdout
        with open(self.log, "w", encoding="utf-8") as log:
            for line in self.proc.stdout:
                log.write(line)
                log.flush()
                line = line.rstrip("\n")
                self.tail.append(line)
                if RUN_START.match(line):
                    if self.state != "building":
                        self.errors, self._failed = [], False
                    self._set("building")
                m = ERR_LINE.match(line)
                if m and len(self.errors) < 20:
                    err = {"file": os.path.normpath(m["file"]), "line": int(m["line"]), "msg": m["msg"].strip()}
                    if err not in self.errors:
                        self.errors.append(err)
                if FAILED.match(line):
                    self._failed = True
                if WATCHING.match(line):
                    self._set("error" if self._failed else "ok")
        self._set("stopped")

    def info(self) -> dict:
        return {"state": self.state, "errors": self.errors, "since": self.changed,
                "tail": list(self.tail)[-12:] if self.state == "error" else [], "log": str(self.log)}

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
