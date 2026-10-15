"""Где в исходниках .tex лежит выделенный в PDF фрагмент.

1. SyncTeX: если рядом с PDF есть main.synctex.gz (latexmk -synctex=1),
   координаты выделения переводятся в точные файл и строку.
2. Иначе — поиск цитаты по словам в main.tex и подключённых \\input-файлах.
"""
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

WORD = re.compile(r"[0-9a-zа-яё]+", re.I)
SECTION = re.compile(r"\\section\*?\{(.*)\}")
INPUT = re.compile(r"\\(?:input|include|subfile)\{([^}]+)\}")


def norm(text: str) -> str:
    # NFKC превращает математические 𝑃, 𝐻 в обычные буквы
    return unicodedata.normalize("NFKC", text).lower().replace("ё", "е")


def norm_words(text: str) -> list:
    return WORD.findall(norm(text))


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


# ------------------------------------------------------------------ SyncTeX
def synctex_file(pdf: Path):
    for cand in (pdf.with_suffix(".synctex.gz"), pdf.with_suffix(".synctex"),
                 pdf.parent / "build" / (pdf.stem + ".synctex.gz")):
        if cand.exists() and cand.stat().st_mtime >= pdf.stat().st_mtime - 5:
            return cand
    return None


def synctex(pdf: Path, root: Path, page: int, x: float, y: float):
    """Координаты в пунктах от левого верхнего угла страницы → {file, line}."""
    if not (shutil.which("synctex") and synctex_file(pdf)):
        return None
    try:
        out = subprocess.run(
            ["synctex", "edit", "-o", f"{page}:{x:.2f}:{y:.2f}:{pdf}"],
            capture_output=True, text=True, timeout=5, cwd=pdf.parent).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m_file = re.search(r"^Input:(.+)$", out, re.M)
    m_line = re.search(r"^Line:(\d+)$", out, re.M)
    if not (m_file and m_line) or int(m_line.group(1)) <= 0:
        return None
    path = Path(m_file.group(1).strip())
    if not path.is_absolute():
        path = pdf.parent / path
    return {"file": rel(path, root), "line": int(m_line.group(1))}


# ------------------------------------------------------------ поиск по словам
def tex_files(root: Path) -> list:
    main = root / "main.tex"
    if not main.exists():
        return []
    files, seen = [], set()

    def walk(f: Path):
        if f in seen or not f.exists():
            return
        seen.add(f)
        files.append(f)
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = re.sub(r"(?<!\\)%.*", "", line)
            for m in INPUT.finditer(line):
                name = m.group(1)
                walk(root / (name if name.endswith(".tex") else name + ".tex"))

    walk(main)
    return files


def tex_index(root: Path) -> list:
    """[(файл, раздел, [(слово, строка), ...])], файлы режутся по \\section."""
    out = []
    for f in tex_files(root):
        title, words = "", []
        for no, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = re.sub(r"(?<!\\)%.*", "", line)
            m = SECTION.search(line)
            if m:
                if words:
                    out.append((f, title, words))
                title, words = norm(re.sub(r"\\[a-zA-Z]+\*?|[{}$]", " ", m.group(1))).strip(), []
            line = re.sub(r"\\[a-zA-Z]+\*?", " ", line)
            words += [(w, no) for w in norm_words(line)]
        if words:
            out.append((f, title, words))
    return out


def by_words(root: Path, quote: str, chapter: str = ""):
    q = norm_words(re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", quote))
    if not q:
        return None
    index = tex_index(root)
    ch = norm(re.sub(r"^\s*[\dIVXA-Z]+\s+", "", chapter or ""))
    index.sort(key=lambda t: 0 if ch and t[1] and (t[1] in ch or ch in t[1]) else 1)
    for k in range(min(6, len(q)), 1 if len(q) > 1 else 0, -1):
        for start in range(len(q) - k + 1):
            window = q[start:start + k]
            for f, _, words in index:
                ws = [w for w, _ in words]
                for i in range(len(ws) - k + 1):
                    if ws[i:i + k] == window:
                        return {"file": rel(f, root), "line": words[i][1]}
    return None


def locate(root: Path, pdf, data: dict):
    """{file, line[, lineEnd], how} или None."""
    anchor, end = data.get("anchor"), data.get("anchorEnd")
    if pdf and isinstance(anchor, dict):
        try:
            hit = synctex(pdf, root, int(anchor["page"]), float(anchor["x"]), float(anchor["y"]))
        except (KeyError, TypeError, ValueError):
            hit = None
        if hit:
            if isinstance(end, dict):
                try:
                    e = synctex(pdf, root, int(end["page"]), float(end["x"]), float(end["y"]))
                except (KeyError, TypeError, ValueError):
                    e = None
                if e and e["file"] == hit["file"] and e["line"] > hit["line"]:
                    hit["lineEnd"] = e["line"]
            return {**hit, "how": "synctex"}
    hit = by_words(root, data.get("quote", ""), data.get("chapter", ""))
    return {**hit, "how": "words"} if hit else None
