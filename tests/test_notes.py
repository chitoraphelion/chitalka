"""Личные заметки (N) и «чистое» открытие: ничего не создаётся до первого сохранения."""
import json
import os
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from chitalka import cli
from chitalka.notes import NOTES_SUFFIX, notes_path
from chitalka.server import Config, serve
from chitalka.store import Store, store_path


def tree(root: Path) -> set:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


@pytest.fixture
def reader(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / "paper.md").write_text("# Title\n\nText with $x_i$.\n", encoding="utf-8")
    (root / "other.md").write_text("# Other\n\nMore text.\n", encoding="utf-8")
    cfg = Config(root, root / "paper.md", Store(store_path(root)), "monospace")
    server = serve(cfg, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, body=None, method=None):
        req = Request(f"http://127.0.0.1:{server.server_port}{path}",
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"}, method=method)
        try:
            response = urlopen(req)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            if "application/json" in response.headers["Content-Type"]:
                content = json.loads(content)
            return response.status, content
    yield request, cfg, root
    server.shutdown()
    server.server_close()
    thread.join()


def test_opening_and_reading_create_nothing(reader, capsys):
    request, _, root = reader
    before = tree(root)
    for path in ("/", "/api/info", "/api/markdown", "/api/comments", "/api/notes", "/api/pdfinfo"):
        assert request(path)[0] == 200
    assert cli.main(["list", "--root", str(root)]) == 0
    assert cli.main(["list", "--all", "--json", "--root", str(root)]) == 0
    assert cli.main(["where", "--root", str(root)]) == 0
    with pytest.raises(SystemExit):
        cli.main(["reply", "abc", "x", "--root", str(root)])
    with pytest.raises(SystemExit):
        cli.main(["done", "abc", "--root", str(root)])
    # правка и удаление несуществующего замечания тоже ничего не создают
    assert request("/api/comments/abc", {"comment": "x"})[0] == 404
    assert request("/api/comments/abc", method="DELETE")[0] == 404
    assert request("/api/notes/nabc", method="DELETE")[0] == 404
    assert tree(root) == before
    capsys.readouterr()


def test_note_creates_only_sidecar_and_stays_out_of_agent_channels(reader, capsys):
    request, cfg, root = reader
    status, note = request("/api/notes", {"text": "Личное: проверить позже", "quote": "Text with",
                                          "page": 1, "ctx": {"before": "x", "after": "y"}})
    assert status == 200 and note["id"].startswith("n")
    assert tree(root) == {"paper.md", "other.md", "paper.md" + NOTES_SUFFIX}
    data = json.loads((root / ("paper.md" + NOTES_SUFFIX)).read_text(encoding="utf-8"))
    assert data["format"] == "chitalka-personal-notes" and data["notes"][0]["text"] == "Личное: проверить позже"
    # агентские каналы о заметке не знают
    assert request("/api/comments")[1] == []
    assert not cfg.store.exists()
    assert cli.main(["list", "--all", "--json", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == [] and "Личное" not in out
    # правка и удаление
    status, edited = request(f"/api/notes/{note['id']}", {"text": "Новый текст"})
    assert status == 200 and edited["text"] == "Новый текст" and edited["updated"]
    assert request("/api/notes")[1]["notes"][0]["text"] == "Новый текст"
    assert request(f"/api/notes/{note['id']}", method="DELETE")[0] == 200
    assert request("/api/notes")[1]["notes"] == []
    assert request(f"/api/notes/{note['id']}", method="DELETE")[0] == 404


def test_first_agent_comment_creates_store_and_memo(reader):
    request, cfg, root = reader
    snapshot = request("/api/markdown")[1]
    status, _ = request("/api/comments", {"quote": "Text", "comment": "Исправить", "page": 1, "sourceLine": 3,
                                          "documentRevision": snapshot["revision"]})
    assert status == 200 and cfg.store.exists()
    memo = (root / "kommentarii" / "HOW_TO_USE_CHITALKA.md").read_text(encoding="utf-8")
    assert "notes.json" in memo and "не поручения" in memo
    assert not (root / ("paper.md" + NOTES_SUFFIX)).exists()


def test_notes_are_per_document_and_validated(reader):
    request, _, root = reader
    other = "?" + urlencode({"document": "other.md"})
    assert request("/api/notes" + other, {"text": "к другому"})[0] == 200
    assert request("/api/notes")[1]["notes"] == []
    assert (root / ("other.md" + NOTES_SUFFIX)).exists()
    for body in ({"text": "   "}, {"text": 5}, {"text": "x", "page": 0}, {"text": "x", "quote": "q" * 10_001}):
        assert request("/api/notes", body)[0] == 400
    assert request("/api/notes/nmissing", {"text": "x"})[0] == 404


def test_read_only_folder_reports_clear_error(reader):
    request, _, root = reader
    if os.geteuid() == 0:
        pytest.skip("root игнорирует права на запись")
    before = tree(root)
    root.chmod(0o555)
    try:
        assert request("/api/notes")[0] == 200            # читать можно
        status, body = request("/api/notes", {"text": "не потерять"})
        assert status == 500 and "только для чтения" in body["error"] and "Текст остался" in body["error"]
        snapshot = request("/api/markdown")[1]
        status, body = request("/api/comments", {"quote": "Text", "comment": "x", "page": 1, "sourceLine": 3,
                                                 "documentRevision": snapshot["revision"]})
        assert status == 500 and "только для чтения" in body["error"]
    finally:
        root.chmod(0o755)
    assert tree(root) == before                            # ни tmp-файлов, ни папок


def test_symlinked_or_broken_sidecar_is_not_touched(reader, tmp_path):
    request, _, root = reader
    sidecar = root / ("paper.md" + NOTES_SUFFIX)
    target = tmp_path / "elsewhere.json"
    target.write_text("[]")
    sidecar.symlink_to(target)
    status, body = request("/api/notes", {"text": "x"})
    assert status == 409 and "символическая ссылка" in body["error"]
    assert "символическая ссылка" in request("/api/notes")[1]["error"]
    assert target.read_text() == "[]"
    sidecar.unlink()
    sidecar.write_text("{broken", encoding="utf-8")
    assert "повреждён" in request("/api/notes")[1]["error"]
    assert request("/api/notes", {"text": "x"})[0] == 409
    assert sidecar.read_text(encoding="utf-8") == "{broken"


def test_concurrent_note_writes_are_not_lost(reader):
    request, _, root = reader
    threads = [threading.Thread(target=request, args=("/api/notes", {"text": f"note {i}"})) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    texts = {n["text"] for n in request("/api/notes")[1]["notes"]}
    assert texts == {f"note {i}" for i in range(16)}
    assert tree(root) == {"paper.md", "other.md", "paper.md" + NOTES_SUFFIX}


def test_notes_path_follows_real_document(tmp_path):
    real = tmp_path / "real" / "article.pdf"
    real.parent.mkdir()
    real.write_bytes(b"%PDF")
    link = tmp_path / "link.pdf"
    link.symlink_to(real)
    assert notes_path(link) == real.parent / "article.pdf.notes.json"


def test_arbitrary_pdf_uses_its_folder_as_root(tmp_path, monkeypatch, capsys):
    elsewhere, cwd = tmp_path / "Downloads", tmp_path / "work"
    elsewhere.mkdir(); cwd.mkdir()
    pdf = elsewhere / "article.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.chdir(cwd)
    seen = []
    monkeypatch.setattr(cli, "probe", lambda port: seen.append(port) or {
        "root": str(elsewhere), "document": "article.pdf", "markdown": True})
    assert cli.main([str(pdf), "--no-browser"]) == 0
    assert "уже работает" in capsys.readouterr().out
    assert tree(cwd) == set() and tree(elsewhere) == {"article.pdf"}
