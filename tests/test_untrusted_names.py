"""2026-11-15 のセキュリティのスキャン（F1〜F3）の直しの約束: ブラウザで使う形の待ち受けも番号を分け合わない・手元の譜面フォルダの
難易度のファイル名を確かめてから開く・BL のリプレイアプリを写し直す道具は外から来た名前を確かめてから書く"""
import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT))
import replays  # noqa: E402
import server  # noqa: E402

BS = chr(92)


def test_make_server_is_exclusive(tmp_path):
    """F1: 既定の型は番号を分け合わない＝先に SO_REUSEADDR で待つソケットがあれば重ねて待たない（main はその時に止める）"""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 0))
    s.listen()
    port = s.getsockname()[1]
    try:
        with pytest.raises(OSError):
            server.make_server(port, tmp_path / 'out', tmp_path / 'cache').server_close()
    finally:
        s.close()
    srv = server.make_server(0, tmp_path / 'out', tmp_path / 'cache')
    try:
        assert isinstance(srv, server.ExclusiveServer) and not srv.allow_reuse_address
    finally:
        srv.server_close()


def _level(folder, names):
    folder.mkdir(parents=True)
    info = {'_songName': 'x', '_songFilename': 'song.egg', '_difficultyBeatmapSets': [{'_beatmapCharacteristicName': 'Standard', '_difficultyBeatmaps': [
        {'_difficulty': 'Expert', '_beatmapFilename': n} for n in names]}]}
    (folder / 'Info.dat').write_text(json.dumps(info), encoding='utf-8')
    (folder / 'song.egg').write_bytes(b'OggS')
    for n in names:
        if replays.plain(n):
            (folder / n).write_text('{}', encoding='utf-8')
    return info


@pytest.mark.parametrize('bad', [BS * 2 + 'host' + BS + 'share' + BS + 'x.dat', '../outside.dat', 'C:' + BS + 'x.dat', 'sub/x.dat', 'Expert.txt', None])
def test_beatmap_names_checked(tmp_path, bad):
    """F2: 難易度のファイル名が 1 つの名前の .dat でない譜面は使わない（UNC・..・絶対の場所を開かない）"""
    lv = tmp_path / 'lv'
    info = _level(lv, ['ExpertStandard.dat', bad])
    assert replays._beatmaps(info) is None
    assert replays.folder_hash(lv) is None
    with pytest.raises(FileNotFoundError):
        replays._folder_files(None, lv)
    ok = tmp_path / 'ok'
    info = _level(ok, ['ExpertStandard.dat', 'HardStandard.DAT'])
    assert replays._beatmaps(info) == ['ExpertStandard.dat', 'HardStandard.DAT'] and replays.folder_hash(ok)


def test_blreplay_fetch_refuses_outside_names(tmp_path, monkeypatch):
    """F3: 取ってきた中身から読んだ名前は、写しのフォルダの外へ出る形・使えない文字なら何も書かずに止める"""
    import blreplay_fetch as B
    dest = tmp_path / 'blreplay'
    monkeypatch.setattr(B, 'DEST', dest)
    info = {'commit': 'c', 'from_github': []}
    for bad in ('build/../../../server.py', 'webfonts/..' + BS + 'x', 'C:/x', '.hidden', 'a//b'):
        with pytest.raises(SystemExit):
            B.write({'index.html': b'<html>', bad: b'x'}, info)
        assert not dest.exists() and not (tmp_path / 'blreplay.new').exists() and not (tmp_path / 'server.py').exists()
    B.write({'index.html': b'<html>', 'assets/flags/not set.png': b'png', 'build/b.1.js': b'js'}, info)
    assert (dest / 'assets' / 'flags' / 'not set.png').read_bytes() == b'png'
    man = json.loads((dest / 'MANIFEST.json').read_text(encoding='utf-8'))
    assert set(man['files']) == {'index.html', 'assets/flags/not set.png', 'build/b.1.js'}
    # 今の写しの名前は全部通る（写し直しても止まらない）
    cur = json.loads((ROOT / 'app' / 'static' / 'blreplay' / 'MANIFEST.json').read_text(encoding='utf-8'))
    assert all(B.safe_rel(p) for p in cur['files'])
    assert B.page_files('<script src="build/b.1.js?v=2"></script>') == ['build/b.1.js']
