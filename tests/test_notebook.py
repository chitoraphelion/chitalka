"""Jupyter-ноутбук (.ipynb): статичный показ ячеек и сохранённых выводов, место для агента."""
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from chitalka import cli
from chitalka.documents import is_markdown, is_notebook
from chitalka.notebook import convert, source_for
from chitalka.server import Config, serve
from chitalka.store import Store, store_path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "notebook.ipynb"


def cell_at(spans, md_text, needle):
    line = next(i for i, l in enumerate(md_text.split("\n"), 1) if needle in l)
    return line, source_for(spans, line, line)


def test_example_notebook_converts_to_static_markdown():
    raw = EXAMPLE.read_text(encoding="utf-8")
    text, spans = convert(raw)
    assert text.startswith("# Градиентный спуск в ноутбуке")
    assert "$$\nf(x_k) - f^\\star" in text                       # формулы markdown-ячеек как есть
    assert "```python nb-in 1\nimport numpy as np" in text
    assert "```text nb-out\n0 [0. 0.]" in text                  # stdout
    assert "```text nb-err\nRuntimeWarning" in text             # stderr
    assert "```text nb-out\n45\n```" in text                    # execute_result
    assert "![вывод](data:image/png;base64,iVBOR" in text       # картинка из вывода
    assert "![вывод](data:image/svg+xml;base64," in text        # svg — тоже base64
    assert "```html nb-html\n<div>" in text and "   a  b" not in text   # HTML важнее text/plain
    assert "ZeroDivisionError: division by zero" in text and "\x1b" not in text
    assert "![logo](data:image/png;base64," in text             # attachment:
    assert "```text nb-raw\nraw-ячейка" in text
    assert "```python nb-in\n# не исполнялась" in text           # без execution_count
    assert [s["cell"] for s in spans] == list(range(1, 12))
    lines = raw.split("\n")
    for span in spans:                                           # строка в .ipynb — начало source
        assert lines[span["file_line"] - 1].strip().startswith('"')


def test_selection_maps_to_cell_and_ipynb_line():
    raw = EXAMPLE.read_text(encoding="utf-8")
    text, spans = convert(raw)
    file_lines = raw.split("\n")
    _, src = cell_at(spans, text, "for k in range(3):")
    assert src["cell"] == 2 and "for k in range(3)" in file_lines[src["line"] - 1]
    _, out = cell_at(spans, text, "RuntimeWarning")              # вывод → последняя строка кода ячейки
    assert out["cell"] == 2 and "print(k, x)" in file_lines[out["line"] - 1]
    _, md = cell_at(spans, text, "## Графики")
    assert md["cell"] == 4 and "## Графики" in file_lines[md["line"] - 1]
    a, _ = cell_at(spans, text, "Шаг $x_{k+1}")
    b, _ = cell_at(spans, text, "sum(range(10))")
    both = source_for(spans, a, b)
    assert both["cell"] == 1 and both["cellEnd"] == 3 and both["lineEnd"] > both["line"]
    # пустые строки между ячейками относятся к предыдущей ячейке
    assert source_for(spans, spans[0]["end"] + 1, spans[0]["end"] + 1)["cell"] == 1


def test_html_widgets_and_service_outputs():
    def one(*outputs):
        return convert(json.dumps({"cells": [{"cell_type": "code", "source": "x", "outputs": list(outputs)}]}))[0]
    styler = '<style type="text/css">#T_1_row0_col0 {background-color: #3787c0}</style><table id="T_1"><tr><td id="T_1_row0_col0">1</td></tr></table>'
    assert "```html nb-html\n<style" in one({"output_type": "display_data", "data": {"text/html": styler}})
    sk = '<div class="sk-text-repr-fallback"><pre>LinearRegression()</pre></div><style>…</style>'
    text = one({"output_type": "execute_result", "data": {"text/html": sk, "text/plain": "LinearRegression()"}})
    assert "nb-html" not in text and "```text nb-out\nLinearRegression()" in text   # схема sklearn → repr
    widget = {"output_type": "display_data", "data": {"application/vnd.jupyter.widget-view+json": {"model_id": "m"},
                                                      "text/plain": "  0%|          | 0/42"}}
    assert "```text nb-widget\n0%|" in one(widget)
    assert "не показывается" not in one({"output_type": "display_data", "data": {"application/vnd.colab-display-data+json": {}}})
    assert "<!-- chitalka:cell -->" in one()                       # граница ячейки для незакрытого HTML


def test_nbformat3_and_errors():
    nb3 = {"nbformat": 3, "metadata": {}, "worksheets": [{"cells": [
        {"cell_type": "code", "language": "python", "input": ["print(1)"], "prompt_number": 7,
         "outputs": [{"output_type": "pyout", "text": ["1"]},
                     {"output_type": "pyerr", "ename": "E", "evalue": "v", "traceback": []}]}]}]}
    text, spans = convert(json.dumps(nb3))
    assert "```python nb-in 7\nprint(1)\n```" in text and "```text nb-out\n1\n```" in text
    assert "```text nb-err\nE: v\n```" in text and len(spans) == 1
    for bad in ("not json", "[]", '{"cells": 5}'):
        with pytest.raises(ValueError):
            convert(bad)
    # длинный вывод обрезается, обратные кавычки в выводе не ломают блок
    long = {"cells": [{"cell_type": "code", "source": "x", "outputs": [
        {"output_type": "stream", "name": "stdout", "text": "```\n" + "x\n" * 6000}]}]}
    text, _ = convert(json.dumps(long))
    assert "````text nb-out" in text and "вывод обрезан" in text
    assert is_notebook("a/b.IPYNB") and is_markdown("b.ipynb") and not is_notebook("b.md")


@pytest.fixture
def reader(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / "nb.ipynb").write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "broken.ipynb").write_text("{oops", encoding="utf-8")
    cfg = Config(root, root / "nb.ipynb", Store(store_path(root)), "monospace")
    server = serve(cfg, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, body=None):
        req = Request(f"http://127.0.0.1:{server.server_port}{path}",
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"})
        try:
            response = urlopen(req)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())
    yield request, cfg, root
    server.shutdown()
    server.server_close()
    thread.join()


def test_server_serves_notebook_and_comments_point_to_cells(reader, capsys):
    request, cfg, root = reader
    status, snap = request("/api/markdown")
    assert status == 200 and snap["notebook"] is True and snap["document"] == "nb.ipynb"
    assert "nb-in 1" in snap["text"]
    line = next(i for i, l in enumerate(snap["text"].split("\n"), 1) if "for k in range(3):" in l)
    status, comment = request("/api/comments", {"quote": "for k in range(3):", "comment": "Шаг поменять",
                                                "page": 1, "sourceLine": line,
                                                "documentRevision": snap["revision"]})
    assert status == 200
    src = comment["source"]
    assert src["how"] == "notebook" and src["file"] == "nb.ipynb" and src["cell"] == 2
    assert "for k in range(3)" in (root / "nb.ipynb").read_text(encoding="utf-8").split("\n")[src["line"] - 1]
    assert cli.main(["list", "--root", str(root)]) == 0
    assert f"nb.ipynb:{src['line']} (notebook), ячейка 2" in capsys.readouterr().out
    status, body = request("/api/markdown?document=broken.ipynb")
    assert status == 400 and "Не удалось прочитать" in body["error"]
