"""Jupyter-ноутбук (.ipynb) как статичный документ: ничего не исполняется.

Ноутбук переводится в Markdown, и дальше работает обычный конвейер читалки
(листы A4, KaTeX, поиск, замечания и заметки). Markdown-ячейки — как есть,
код — блоком с подписью `In [n]`, сохранённые выводы — текстом, ошибками
(без ANSI-цветов) и картинками. Для замечаний агенту строится карта:
строка Markdown → номер ячейки и строка в самом .ipynb (для nvim).
"""
import base64
import json
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
IMAGE_MIME = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml")
MAX_OUTPUT_LINES = 5000


def _text(value) -> str:
    if isinstance(value, list):
        return "".join(str(v) for v in value)
    return "" if value is None else str(value)


def _fence(body: str, info: str) -> list:
    ticks = "`" * max(3, max((len(m) for m in re.findall(r"`+", body)), default=0) + 1)
    lines = body.rstrip("\n").split("\n") if body.strip("\n") else [""]
    if len(lines) > MAX_OUTPUT_LINES:
        lines = lines[:MAX_OUTPUT_LINES] + [f"… вывод обрезан: ещё {len(lines) - MAX_OUTPUT_LINES} строк"]
    return [ticks + info, *lines, ticks]


def _image(mime: str, data) -> str:
    raw = _text(data)
    if mime == "image/svg+xml":
        raw = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    else:
        raw = re.sub(r"\s+", "", raw)
    return f"![вывод]({'data:' + mime + ';base64,' + raw})"


def _output(out: dict) -> list:
    kind = out.get("output_type")
    if kind == "stream":
        name = out.get("name", "stdout")
        return _fence(ANSI.sub("", _text(out.get("text"))), "text nb-err" if name == "stderr" else "text nb-out")
    if kind in ("error", "pyerr"):
        trace = "\n".join(ANSI.sub("", _text(t)) for t in out.get("traceback") or [])
        head = f"{out.get('ename', 'Error')}: {out.get('evalue', '')}"
        return _fence(trace or head, "text nb-err")
    data = out.get("data") or {}
    if kind == "pyout" or (not data and out.get("text")):          # nbformat 3
        data = {"text/plain": out.get("text"), **{f"image/{k}": out[k] for k in ("png", "jpeg") if k in out}}
    for mime in IMAGE_MIME:
        if mime in data:
            return [_image(mime, data[mime])]
    if "text/markdown" in data:
        return _text(data["text/markdown"]).split("\n")
    if "text/latex" in data:
        tex = _text(data["text/latex"]).strip()
        return [tex] if tex.startswith("$") or tex.startswith("\\[") else ["$$", tex, "$$"]
    if "text/plain" in data:
        return _fence(ANSI.sub("", _text(data["text/plain"])), "text nb-out")
    if data:
        return [f"*Вывод типа {', '.join(sorted(data))} не показывается*"]
    return []


def _cell_lines(raw: str) -> list:
    """Строка в .ipynb, где начинается source каждой ячейки (для nvim); 1, если не найдено."""
    lines, starts, pending, starts_hint = raw.split("\n"), [], False, 1
    for no, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith('"cell_type"'):
            if pending:
                starts.append(starts_hint)
            pending, starts_hint = True, no
        elif pending and (s.startswith('"source"') or s.startswith('"input"')):
            # "source": [  → строки на следующих строках файла; "source": "…" → на этой же
            starts.append(no + 1 if s.rstrip().endswith("[") else no)
            pending = False
    if pending:
        starts.append(starts_hint)
    return starts


def convert(raw: str):
    """(markdown, cells), где cells — [{"cell": n, "start": md_line, "end": md_line, "file_line": l}]."""
    try:
        nb = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"не JSON-ноутбук: {e}") from e
    if not isinstance(nb, dict):
        raise ValueError("не JSON-ноутбук")
    cells = nb.get("cells")
    if cells is None and isinstance(nb.get("worksheets"), list) and nb["worksheets"]:
        cells = nb["worksheets"][0].get("cells")             # nbformat 3
    if not isinstance(cells, list):
        raise ValueError("в ноутбуке нет списка cells")
    lang = ((nb.get("metadata") or {}).get("language_info") or {}).get("name") \
        or ((nb.get("metadata") or {}).get("kernelspec") or {}).get("language") or "python"
    file_lines = _cell_lines(raw)
    out, spans = [], []
    for i, cell in enumerate(c for c in cells if isinstance(c, dict)):
        kind = cell.get("cell_type")
        source = _text(cell.get("source", cell.get("input")))
        start = len(out) + 1
        body_start = start
        if kind == "markdown":
            for name, att in (cell.get("attachments") or {}).items():
                for mime in IMAGE_MIME:
                    if mime in att:
                        source = source.replace(f"attachment:{name}", f"data:{mime};base64,{re.sub(chr(92) + 's+', '', _text(att[mime]))}")
            out += source.split("\n")
        elif kind == "code":
            n = cell.get("execution_count", cell.get("prompt_number"))
            info = f"{lang} nb-in {n if isinstance(n, int) else ' '}".rstrip()
            fence = _fence(source, info)
            body_start = start + 1
            out += fence
            for o in cell.get("outputs") or []:
                if isinstance(o, dict):
                    block = _output(o)
                    if block:
                        out += [""] + block
        else:                                                    # raw и прочие
            out += _fence(source, "text nb-raw")
            body_start = start + 1
        spans.append({"cell": i + 1, "start": start, "end": len(out), "body": body_start,
                      "lines": max(1, len(source.split("\n"))),
                      "file_line": file_lines[i] if i < len(file_lines) else 1})
        out += ["", ""]
    return "\n".join(out), spans


def source_for(spans: list, start: int, end: int):
    """Строки Markdown выделения → {cell, cellEnd?, line, lineEnd?} в .ipynb."""
    def find(line):                              # пустые строки между ячейками → предыдущая ячейка
        return next((s for s in reversed(spans) if s["start"] <= line), None)
    a, b = find(start), find(end)
    if not a:
        raise ValueError("Выделение вне ячеек ноутбука")

    def file_line(span, line):                   # вывод ячейки → последняя строка её исходника
        return span["file_line"] + min(max(0, line - span["body"]), span["lines"] - 1)
    result = {"cell": a["cell"], "line": file_line(a, start)}
    last = file_line(b, end)
    if b["cell"] != a["cell"]:
        result["cellEnd"] = b["cell"]
    if last > result["line"]:
        result["lineEnd"] = last
    return result
