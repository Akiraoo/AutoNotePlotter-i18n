"""曲の取り込みのカバー画像の貼り付け（app/importer.save_pasted・/api/import/paste・2026-11-03 利用者「クリップボードに上がっている画像を
そのまま取り込む」）: jpg・png だけ受け、一時的な場所に書いて画面に見せてよい画像（取り込みで選べる画像）に足す"""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))
import importer  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 32
JPG = b'\xff\xd8\xff\xe0' + b'\0' * 32


@pytest.fixture
def paste_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, 'PASTE_DIR', tmp_path / 'paste')
    return tmp_path / 'paste'


def test_png_and_jpg(paste_dir):
    p = importer.save_pasted('data:image/png;base64,' + base64.b64encode(PNG).decode())
    j = importer.save_pasted(base64.b64encode(JPG).decode())
    assert p.suffix == '.png' and j.suffix == '.jpg' and p.parent == paste_dir == j.parent
    assert p.read_bytes() == PNG and j.read_bytes() == JPG
    assert str(p) in importer._SEEN and str(j) in importer._SEEN   # 取り込みのカバー画像として選べる・画面に出せる
    assert p.name.startswith('貼り付け-')


@pytest.mark.parametrize('data', ['', 'data:image/png;base64,', 'これは画像ではない', base64.b64encode(b'GIF89a' + b'\0' * 10).decode()])
def test_rejects(paste_dir, data):
    with pytest.raises(ValueError):
        importer.save_pasted(data)


def test_too_big(paste_dir, monkeypatch):
    monkeypatch.setattr(importer, 'PASTE_MAX', 16)
    with pytest.raises(ValueError):
        importer.save_pasted(base64.b64encode(PNG).decode())
