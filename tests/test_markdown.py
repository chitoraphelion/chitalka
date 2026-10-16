import json
import subprocess
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from chitalka.documents import markdown_snapshot, markdown_source, safe_path
from chitalka.server import Config, serve
from chitalka.store import Store


@pytest.fixture
def reader(tmp_path):
    (tmp_path / 'paper.md').write_text('# Title\n\nText with $x_i$.\n', encoding='utf-8')
    (tmp_path / 'other.md').write_text('# Other\n', encoding='utf-8')
    (tmp_path / 'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (tmp_path / 'paper.pdf').write_bytes(b'%PDF-fixture')
    store = Store(tmp_path / 'comments.json')
    cfg = Config(tmp_path, tmp_path / 'paper.md', store, 'monospace')
    server = serve(cfg, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, body=None, method=None):
        req = Request(f'http://127.0.0.1:{server.server_port}{path}',
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'}, method=method)
        try:
            response = urlopen(req)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            if 'application/json' in response.headers['Content-Type']:
                content = json.loads(content)
            return response.status, content, response.headers
    yield request, cfg
    server.shutdown()
    server.server_close()
    thread.join()


def test_markdown_source_and_containment(tmp_path):
    path = tmp_path / 'paper.md'
    path.write_text('\ufeff# Title\n\nText\n', encoding='utf-8')
    snap = markdown_snapshot(path, tmp_path)
    assert snap['text'].startswith('# Title') and snap['lines'] == 3
    assert markdown_source(path, tmp_path, {'sourceLine': 1, 'sourceLineEnd': 3}) == {
        'file': 'paper.md', 'line': 1, 'lineEnd': 3, 'how': 'markdown'}
    for data in ({'sourceLine': True}, {'sourceLine': 0}, {'sourceLine': 4},
                 {'sourceLine': 2, 'sourceLineEnd': 1}):
        with pytest.raises(ValueError):
            markdown_source(path, tmp_path, data)
    (tmp_path / 'escape').symlink_to(tmp_path.parent, target_is_directory=True)
    for value in ('../secret', 'escape/secret'):
        with pytest.raises(ValueError):
            safe_path(tmp_path, value)


def test_markdown_api_comments_and_pdf_regression(reader):
    request, cfg = reader
    assert request('/api/info')[1]['kind'] == 'markdown'
    snapshot = request('/api/markdown')[1]
    body = {'quote': 'Text', 'comment': 'Revise', 'page': 1, 'sourceLine': 3,
            'documentRevision': snapshot['revision'], 'document': 'forged.md'}
    status, comment, _ = request('/api/comments', body)
    assert status == 200 and comment['document'] == 'paper.md'
    assert comment['source'] == {'file': 'paper.md', 'line': 3, 'how': 'markdown'}
    other = '?' + urlencode({'document': 'other.md'})
    assert request('/api/comments' + other)[1] == []
    assert request(f"/api/comments/{comment['id']}" + other, {'comment': 'wrong'})[0] == 404
    request(f"/api/comments/{comment['id']}" + other, method='DELETE')
    assert len(cfg.store.read()) == 1
    cfg.pdf.write_text('# Changed\n\nNew paragraph\n')
    assert request('/api/comments', body)[0] == 409
    body['documentRevision'] = request('/api/markdown')[1]['revision']
    assert request('/api/comments', {**body, 'sourceLine': 99})[0] == 400
    cfg.pdf.unlink()
    assert request('/api/info')[1]['kind'] == 'markdown'
    assert request('/api/comments', body)[0] == 409
    pdf = '?' + urlencode({'document': 'paper.pdf'})
    assert request('/api/info' + pdf)[1]['kind'] == 'pdf'
    assert request('/book.pdf' + pdf)[1] == b'%PDF-fixture'
    assert request('/api/comments' + pdf)[1] == []
    with cfg.store.edit() as items:
        items.append({'id': 'legacy', 'page': 1})
    assert request('/api/comments' + pdf)[1][0]['id'] == 'legacy'
    assert request('/api/info?document=../outside.md')[0] == 403


def test_offline_assets_and_images(reader):
    request, _ = reader
    for path, ctype in [('/markdown.js', 'text/javascript'), ('/markdown.css', 'text/css'),
                        ('/vendor/markdown-it.min.js', 'text/javascript'),
                        ('/vendor/katex.min.js', 'text/javascript'),
                        ('/vendor/katex.min.css', 'text/css'),
                        ('/vendor/fonts/KaTeX_Main-Regular.woff2', 'font/woff2')]:
        status, data, headers = request(path)
        assert status == 200 and data
        assert headers['Content-Type'] == ctype
    status, _, headers = request('/assets/figure.svg')
    assert status == 200 and 'sandbox' in headers['Content-Security-Policy']
    assert request('/assets/paper.md')[0] == 404
    assert request('/assets/%2e%2e/secret.png')[0] == 403
    assert request('/vendor/%2e%2e/index.html')[0] == 403


def test_browser_renderer_unit():
    import shutil
    if not shutil.which('node'):
        pytest.skip('Node is only needed for renderer development tests')
    subprocess.run(['node', str(Path(__file__).with_name('markdown.cjs'))], check=True)


def test_cli_reuses_reader_for_another_markdown(tmp_path, monkeypatch, capsys):
    from chitalka import cli
    from chitalka.completion import complete
    document = tmp_path / 'notes.md'
    document.write_text('# Notes')
    monkeypatch.setattr(cli, 'probe', lambda port: {
        'root': str(tmp_path), 'document': 'main.pdf', 'markdown': True})
    assert cli.main([str(document), '--no-browser', '--watch']) == 0
    assert '?document=notes.md' in capsys.readouterr().out
    assert str(document) in complete([str(tmp_path / 'notes')])
    # open must not litter the project: the memo appears with the first saved comment
    assert not (tmp_path / 'kommentarii').exists()
    from chitalka.store import write_doc
    doc = write_doc(tmp_path / 'kommentarii' / 'kommentarii.json').read_text()
    assert '(markdown)' in doc and 'KaTeX' in doc and '.notes.json' in doc
