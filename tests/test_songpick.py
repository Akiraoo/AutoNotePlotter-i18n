"""曲を選ぶ窓（app/static/js/songpick.js）のサーバーの側（app/server.py・2026-11-09）: 曲の一覧の曲名・アーティスト・カバーの有無の
読み方と控え（<OUT>/.songlist.json）・アーカイブの印（作業ファイルの archived・画面の保存で消えない）・曲のデータの控えを 3 曲まで"""
import json
import os
import sys
from pathlib import Path

import pytest

from automap import nlmf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import server  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + (256).to_bytes(4, 'big') * 2 + b'\x08\x02\x00\x00\x00' + b'\x00' * 8


def _proj(title='', artist='', cover=None):
    """曲の情報（書き出しに繋がった曲の情報のノード・カバーのノード）だけの .nlmf"""
    nodes = {'m1': {'t': 'meta', 'x': 0, 'y': 0, 'data': {'name': title, 'sub': '', 'artist': artist, 'author': ''}}}
    edges = [{'s': 'm1', 'o': 'o1'}]
    if cover:
        nodes['c1'] = {'t': 'cover', 'x': 0, 'y': 200, 'data': {'name': Path(cover).name, 'nativePath': str(cover)}}
        edges.append({'s': 'c1', 'o': 'o1'})
    return {'format': 'nlmf', 'version': 2, 'bpm': 120, 'tempoParts': [], 'notesLanes': 1, 'lightLanes': 1, 'markers': [],
            'info': {'_songName': title, '_songAuthorName': artist},
            'infoGraph': {'nodes': nodes, 'outs': {'o1': {'x': 600, 'y': 100, 'folderName': '', 'outDirName': '', 'outDirPath': ''}},
                          'activeOut': 'o1', 'edges': edges, 'prevMig': 1},
            'difficulties': {}}


@pytest.fixture
def out(tmp_path, monkeypatch):
    """写しの場所: 曲 A（結果のファイル・作業ファイル・カバー）・曲 B（土台の試作5 だけ・作業ファイルも無い）"""
    o, c = tmp_path / 'out', tmp_path / 'cache'
    o.mkdir()
    monkeypatch.setattr(server, 'OUT', o)
    monkeypatch.setattr(server, 'CACHE', c)
    for name in ('A', 'B'):
        (c / name).mkdir(parents=True)
        (c / name / 'separate.json').write_text('{"seconds": 10}', encoding='utf-8')
    (o / 'A.jpg').write_bytes(PNG)
    nlmf.save(_proj('Song A', 'Artist A', o / 'A.jpg'), o / 'A.intent-s1.nlmf')
    server.save_work(o / 'A.intent-s1.nlmf', {'ranges': [{'b0': 0, 'b1': 4, 'set': {'amount': 1}}], 'line': [], 'auto_rest': {'on': False, 'b': None}})
    nlmf.save(_proj('', ''), o / 'B.style-s1.nlmf')
    return o


def _by(name):
    return next(s for s in server.songs() if s['song'] == name)


def test_songs_title_artist_cover(out):
    a, b = _by('A'), _by('B')
    assert (a['title'], a['artist'], a['cover'], a['archived'], a['app_exists']) == ('Song A', 'Artist A', True, False, True)
    assert (b['title'], b['artist'], b['cover'], b['archived'], b['app_exists']) == ('B', '', False, False, False)   # 曲名が無ければ曲の名前
    assert a['mtime'] == pytest.approx((out / 'A.intent-s1.nlmf').stat().st_mtime) and a['cover_v']
    assert b['mtime'] == pytest.approx((out / 'B.style-s1.nlmf').stat().st_mtime)
    saved = json.loads((out / server.SONGLIST_FILE).read_text(encoding='utf-8'))
    assert set(saved['nlmf']) == {'A.intent-s1.nlmf', 'B.style-s1.nlmf'} and saved['nlmf']['A.intent-s1.nlmf']['artist'] == 'Artist A'


def test_song_info_read_only_when_file_changes(out, monkeypatch):
    """1 回読んだら（更新時刻・大きさ）で控え、変わった時だけ読み直す。控えのファイルは起動し直しても使う"""
    server.songs()
    calls = []
    orig = server.read_song_info
    monkeypatch.setattr(server, 'read_song_info', lambda p: calls.append(p.name) or orig(p))
    server.songs()
    assert calls == []
    server._META['out'] = None   # 起動し直した（控えはファイルから読む）
    server.songs()
    assert calls == []
    nlmf.save(_proj('Song A2', 'Someone', out / 'A.jpg'), out / 'A.intent-s1.nlmf')   # NLM・書き出しの窓で曲の情報を直した
    assert (_by('A')['title'], _by('A')['artist']) == ('Song A2', 'Someone') and calls == ['A.intent-s1.nlmf']


def test_archive_survives_screen_save(out):
    """アーカイブの印は画面の保存（PUT /api/work＝store.js の workBody は印を持たない）・ほかの受け持ちの保存で消えず、送られた値でも変わらない"""
    p = out / 'A.intent-s1.nlmf'
    assert server.set_archived({'song': 'A', 'on': True}) == {'ok': True, 'song': 'A', 'archived': True}
    assert _by('A')['archived'] is True
    server.save_work(p, {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}})   # 画面の自動保存（印が無い）
    assert json.loads(server.work_path(p).read_text(encoding='utf-8'))['archived'] is True and _by('A')['archived'] is True
    server.save_work(p, dict(server.load_work(p), archived=False))   # 印を変えるのは決まった受け口だけ
    assert _by('A')['archived'] is True
    server.set_archived({'song': 'A', 'on': False})
    assert _by('A')['archived'] is False and 'archived' not in server.load_work(p)
    server.save_work(p, dict(server.load_work(p), archived=True))
    assert _by('A')['archived'] is False


def test_archive_keeps_work_mtime_and_content(out):
    """印を付けるだけ: ほかの項目と作業ファイルの更新時刻はそのまま（窓のアプリは作業ファイルを一番後に保存した曲を最後の曲とみる）"""
    p = out / 'A.intent-s1.nlmf'
    wp = server.work_path(p)
    os.utime(wp, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    before = json.loads(wp.read_text(encoding='utf-8'))
    server.set_archived({'song': 'A', 'on': True})
    assert wp.stat().st_mtime_ns == 1_700_000_000_000_000_000
    assert json.loads(wp.read_text(encoding='utf-8')) == dict(before, archived=True)
    server.set_archived({'song': 'A', 'on': False})   # 大きさ・更新時刻が前と同じに戻っても、控えが古い印を返さない
    assert wp.stat().st_mtime_ns == 1_700_000_000_000_000_000 and _by('A')['archived'] is False
    server._META['out'] = None
    assert _by('A')['archived'] is False


def test_archive_song_without_work_file(out):
    """作業ファイルが無い曲（まだ開いていない・土台だけ）もアーカイブできる（作業ファイルを作る＝開いた時と同じ中身）"""
    assert not server.work_path(out / 'B.intent-s1.nlmf').exists()
    server.set_archived({'song': 'B', 'on': True})
    w = json.loads(server.work_path(out / 'B.intent-s1.nlmf').read_text(encoding='utf-8'))
    assert w['archived'] is True and w['ranges'] == [] and w['song'] == 'B'
    assert _by('B')['archived'] is True
    with pytest.raises(ValueError):
        server.set_archived({'song': '../A', 'on': True})


def test_archive_is_not_a_song_setting(out):
    """アーカイブの印は曲の全体の設定に数えない（数えると、アーカイブしただけで次の作り直しが前の譜面に寄せなくなる・pending に出る）"""
    import versions
    w = server.load_work(out / 'A.intent-s1.nlmf')
    assert versions._settings(dict(w, archived=True)) == versions._settings(w)


def test_song_data_keeps_three_songs(out, monkeypatch):
    """曲のデータは 3 曲まで覚える（古く使った物から捨てる）。結果のファイルが変わったら作り直し、同じ曲の古い物は捨てる"""
    made = []
    monkeypatch.setattr(server, '_DATA', {})
    monkeypatch.setattr(server, 'SONGDATA_DISK', False)   # メモリの覚えだけを見る（ディスクの控えは tests/test_songcache.py）
    monkeypatch.setattr(server.songdata, 'song_data', lambda name, src, a: made.append(name) or {'name': name, 'size': src.stat().st_size})
    monkeypatch.setattr(server, 'chart', lambda src, diff=None: {})
    monkeypatch.setattr(server, 'base_diff', lambda p, w=None: 'ExpertPlus')
    for n in 'CDE':
        nlmf.save(_proj(n, ''), out / f'{n}.intent-s1.nlmf')
    get = lambda n: server.song_data(out / f'{n}.intent-s1.nlmf')
    for n in 'ACD':
        get(n)
    get('A')                       # 使った＝新しい側へ
    get('E')                       # 4 曲目 → 一番古く使った C を捨てる
    assert made == ['A', 'C', 'D', 'E'] and len(server._DATA) == 3
    get('A'); get('D')
    assert made == ['A', 'C', 'D', 'E']
    get('C')
    assert made[-1] == 'C' and len(server._DATA) == 3
    nlmf.save(_proj('A', 'x' * 50), out / 'A.intent-s1.nlmf')   # 作り直した（結果のファイルが変わった）
    d = get('A')
    assert made[-1] == 'A' and d['size'] == (out / 'A.intent-s1.nlmf').stat().st_size
    assert sum(1 for v in server._DATA.values() if v['name'] == 'A') == 1   # 古い物は残さない
