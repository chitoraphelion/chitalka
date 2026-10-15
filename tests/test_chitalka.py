import json
from pathlib import Path

from chitalka import cli
from chitalka.locate import by_words
from chitalka.store import Store, store_path, waiting

TEX = r"""\documentclass{article}
\begin{document}
\section{Введение}
Мы рассматриваем задачу выпуклой оптимизации.
\input{sections/app}
\end{document}
"""
APP = r"""\section{Приложение}
Здесь лежит вспомогательная лемма о спуске.
"""


def project(tmp_path: Path) -> Path:
    (tmp_path / "sections").mkdir()
    (tmp_path / "main.tex").write_text(TEX, encoding="utf-8")
    (tmp_path / "sections" / "app.tex").write_text(APP, encoding="utf-8")
    return tmp_path


def test_store_path_prefers_legacy(tmp_path):
    assert store_path(tmp_path) == tmp_path / "kommentarii" / "kommentarii.json"
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "kommentarii.json").write_text("[]")
    assert store_path(tmp_path) == tmp_path / "notes" / "kommentarii.json"


def test_locate_by_words_follows_input(tmp_path):
    root = project(tmp_path)
    hit = by_words(root, "вспомогательная лемма о спуске", "A Приложение")
    assert hit == {"file": "sections/app.tex", "line": 2}


def test_agent_commands(tmp_path, capsys):
    root = project(tmp_path)
    store = Store(store_path(root))
    store.path.parent.mkdir(parents=True)
    store.save([{"id": "abc", "status": "open", "page": 1, "quote": "задачу", "comment": "уточнить",
                 "category": "rewrite", "reply": "", "thread": []}])
    assert cli.main(["list", "--root", str(root)]) == 0
    assert "[abc]" in capsys.readouterr().out
    assert cli.main(["reply", "abc", "готово", "--done", "--root", str(root)]) == 0
    c = store.read()[0]
    assert c["status"] == "done" and c["thread"][-1]["who"] == "ai" and not waiting(c)
    assert cli.main(["init", "--root", str(root)]) == 0
    doc = (root / "kommentarii" / "HOW_TO_USE_CHITALKA.md").read_text(encoding="utf-8")
    assert "chitalka list" in doc and "kommentarii.json" in doc
    json.loads(store.path.read_text(encoding="utf-8"))


def test_engine_flag(tmp_path):
    from chitalka.build import engine_flag
    (tmp_path / "main.tex").write_text("% Компиляция: latexmk -xelatex main.tex\n\\documentclass{article}\n")
    assert engine_flag(tmp_path, None) == ["-xelatex"]
    assert engine_flag(tmp_path, "pdflatex") == ["-pdf"]
    (tmp_path / ".latexmkrc").write_text("$pdf_mode = 5;\n")
    assert engine_flag(tmp_path, None) == []


def test_open_rejects_outside(tmp_path):
    import pytest
    from chitalka.editor import open_in_editor
    project(tmp_path)
    with pytest.raises(ValueError):
        open_in_editor(tmp_path, "../x.tex", 1, "true")
    assert open_in_editor(tmp_path, "main.tex", 3, "true {file} {line}") == "editor"
