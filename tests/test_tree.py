"""Дерево файлов (<Space>e): /api/tree только читает и не выходит за корень проекта."""
import json
import os
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from chitalka.documents import list_dir
from chitalka.server import Config, serve
from chitalka.store import Store, store_path


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "paper.md").write_text("# T\n", encoding="utf-8")
    (root / "main.tex").write_text("x", encoding="utf-8")
    (root / ".hidden").write_text("", encoding="utf-8")
    (root / "sub" / "nb.ipynb").write_text("{}", encoding="utf-8")
    run = root / "run.sh"
    run.write_text("#!/bin/sh\n", encoding="utf-8")
    run.chmod(0o755)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "away").symlink_to(outside)
    (root / "broken").symlink_to(tmp_path / "missing")
    return root


def test_list_dir_marks_documents_dirs_and_links(project):
    data = list_dir(project)
    by = {e["name"]: e for e in data["entries"]}
    assert data["dir"] == "" and data["root"] == str(project.resolve())
    assert by["sub"]["dir"] and not by["sub"]["doc"]
    assert by["paper.md"]["doc"] and not by["main.tex"]["doc"]
    assert by["run.sh"]["exec"] and not by["paper.md"]["exec"]
    assert by["away"]["link"] and by["away"]["dir"]
    assert by["broken"]["link"] and not by["broken"]["dir"]
    assert ".hidden" in by                                  # как netrw: скрытые видны, gh скрывает
    sub = list_dir(project, "sub")
    assert sub["dir"] == "sub" and {e["name"] for e in sub["entries"]} == {"deep", "nb.ipynb"}
    assert next(e for e in sub["entries"] if e["name"] == "nb.ipynb")["doc"]
    for bad in ("..", "../outside", "away", "sub/../.."):
        with pytest.raises(ValueError):
            list_dir(project, bad)
    with pytest.raises(FileNotFoundError):
        list_dir(project, "nope")


def test_tree_api_reads_only(project, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    before = sorted(str(p) for p in project.rglob("*"))
    server = serve(Config(project, project / "paper.md", Store(store_path(project)), "monospace"), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(dir_):
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/tree?" + urlencode({"dir": dir_})) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        status, data = get("")
        assert status == 200 and "paper.md" in {e["name"] for e in data["entries"]}
        assert get("sub")[0] == 200
        assert get("..")[0] == 403 and get("away")[0] == 403
        assert get("nope")[0] == 404
        with urlopen(f"http://127.0.0.1:{server.server_port}/tree.js") as r:
            assert b"ChitalkaTree" in r.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert sorted(str(p) for p in project.rglob("*")) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root игнорирует права")
def test_unreadable_folder_is_reported(project):
    (project / "sub").chmod(0)
    try:
        with pytest.raises(PermissionError):
            list_dir(project, "sub")
    finally:
        (project / "sub").chmod(0o755)
