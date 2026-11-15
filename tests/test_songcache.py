"""曲のデータのディスクの控え（app/songcache.py・app/server.py の song_data・2026-11-09）と、重い部品を使う時まで読まない作り
（automap/lazy.py・automap/written.py）: 控えから返した物が作った物と 1 バイトも違わない・入力（結果のファイル・こちらで書いた印・
基準の難易度・分けた音のフォルダの使うファイル）や作り方の版が変わったら作り直す・壊れた控えは作り直す・曲ごとに 1 つ・曲のデータを
作る時に読むモジュールが作り方の版に全部入っている・控えから開く時は重い部品（numpy・scipy・automap.__main__）を読まない"""
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from automap import nlmf, written
from automap import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import server  # noqa: E402
import songcache  # noqa: E402

EP = 'expertplusstandard.dat'
NAME = '曲'
BPM, SECS, SR = 120.0, 24.0, 22050
J = lambda d: json.dumps(d, ensure_ascii=False, separators=(',', ':')).encode('utf-8')   # server._send と同じ形


def _stems(d):
    """分けた音の作り物（拍ごとのドラム・歌の高さの並び・ベース・伴奏）と separate.json"""
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(5)
    t = np.arange(int(SECS * SR)) / SR
    beat = 60 / BPM
    drums = np.zeros_like(t)
    for i in range(int(SECS / beat * 2)):
        a = int(i * beat / 2 * SR)
        n = int((0.05 if i % 2 == 0 else 0.02) * SR)
        drums[a:a + n] += rng.normal(scale=0.4 if i % 4 == 0 else 0.15, size=len(drums[a:a + n]))
    voc = np.zeros_like(t)
    for i in range(int(SECS / beat)):
        if i % 8 in (6, 7):
            continue
        a, b = int(i * beat * SR) + 200, int((i + 0.8) * beat * SR)
        f = 220 * 2 ** ([0, 2, 4, 5, 7, 5, 4, 2][i % 8] / 12)
        voc[a:b] = 0.3 * np.sin(2 * np.pi * f * t[a:b])
    bass = 0.3 * np.sin(2 * np.pi * 55 * t) * (np.floor(t / beat) % 2 == 0)
    other = 0.1 * (np.sin(2 * np.pi * 261.6 * t) + np.sin(2 * np.pi * 329.6 * t)) + 0.01 * rng.normal(size=len(t))
    for k, y in (('drums', drums), ('vocals', voc), ('bass', bass), ('other', other)):
        sf.write(d / f'{k}.flac', np.stack([y, y], axis=1).astype(np.float32), SR)
    (d / 'separate.json').write_text(json.dumps({'seconds': SECS}), encoding='utf-8')


def _proj(shift=0):
    """拍 0〜48 を作ったクリップで覆った Expert+ だけのファイル（tests/test_app_diffs.py と同じ形）"""
    p = {'format': 'nlmf', 'version': 2, 'bpm': BPM, 'tempoParts': [], 'current': 'ExpertPlusStandard.dat', 'notesLanes': 1,
         'lightLanes': 1, 'markers': [{'beat': 0, 'name': 'Aメロ'}, {'beat': 16, 'name': 'サビ'}, {'beat': 32, 'name': 'Bメロ'}],
         'laneStates': {'mute': [], 'solo': [], 'lock': []}, 'graph': {'out': {'diffs': {'ExpertPlus': 1}}},
         'difficulties': {EP: {'name': 'ExpertPlusStandard.dat', 'v3': True, 'base': {}, 'notes': [], 'bombs': [], 'walls': [],
                               'arcs': [], 'chains': [], 'lightEvents': [],
                               'sections': [{'id': 'l1', 'beat': 0, 'track': 0, 'lk': 'l', 'len': 48, 'label': 'light', 'content': {}}]}}}
    ns = [{'beat': b + 0.0, 'x': (1 + (i % 2) + shift) % 4, 'y': 0, 'c': i % 2, 'd': 1 if (i // 2) % 2 == 0 else 0}
          for i, b in enumerate(range(1, 48))]
    nlmf.put_note_lane(p, {EP: cli._cover_clips(p, ns, 48)})
    return p


@pytest.fixture(scope='module')
def song_dirs(tmp_path_factory):
    """作り物の曲（分けた音・結果のファイル・こちらで書いた印・作業ファイル）。一度作った分けた音を写して使う"""
    base = tmp_path_factory.mktemp('song')
    _stems(base / 'cache' / NAME)
    (base / 'out').mkdir()
    return base


@pytest.fixture
def song(song_dirs, tmp_path, monkeypatch):
    import shutil
    o, c = tmp_path / 'out', tmp_path / 'cache'
    o.mkdir()
    shutil.copytree(song_dirs / 'cache', c)
    monkeypatch.setattr(server, 'OUT', o)
    monkeypatch.setattr(server, 'CACHE', c)
    monkeypatch.setattr(server, '_DATA', {})
    p = o / f'{NAME}.intent-s1.nlmf'
    written._save(_proj(), p)
    return p


def _files(p):
    return sorted(q.name for q in (server.CACHE / NAME).glob('song_data.*'))


def test_same_bytes_from_disk(song, monkeypatch):
    """作った物と、ディスクの控えから読んだ物（起動し直した＝メモリに無い）は JSON にして 1 バイトも違わない。控えから読む時は作らない"""
    monkeypatch.setattr(server, 'SONGDATA_DISK', False)
    fresh = J(server.song_data(song))
    assert _files(song) == []
    server._DATA.clear()
    monkeypatch.setattr(server, 'SONGDATA_DISK', True)
    made = J(server.song_data(song))
    assert made == fresh and len(_files(song)) == 1
    server._DATA.clear()
    monkeypatch.setattr(server.songdata, 'song_data', lambda *a: pytest.fail('控えがあるのに作った'))
    monkeypatch.setattr(server, 'chart', lambda *a, **k: pytest.fail('控えがあるのに作った'))
    assert J(server.song_data(song)) == fresh
    d = json.loads(fresh)
    assert d['notes'] and d['clips'] and d['file'] == song.name and d['src']['vocals'] == f'/audio/{NAME}/vocals.flac'


@pytest.fixture
def fake(song, monkeypatch):
    """作る所の作り物（呼ばれた回数を数える・答えに入力の大きさを入れる）"""
    made = []

    def make(name, src, a):
        made.append(name)
        return {'name': name, 'size': src.stat().st_size, 'n': len(made)}
    monkeypatch.setattr(server.songdata, 'song_data', make)
    monkeypatch.setattr(server, 'chart', lambda src, diff=None: {'base': server.base_diff(server.OUT / f'{NAME}.intent-s1.nlmf')})
    return made


def _reopen(p):
    """起動し直して開く（メモリの覚えを捨てる）"""
    server._DATA.clear()
    return server.song_data(p)


def test_rebuilds_when_inputs_change(song, fake):
    """結果のファイルを作り直した・NLM で保存した（こちらで書いた印と合わない）・基準の難易度を置き直した・分けた音の控えが変わった
    → 作り直す。変わっていなければ起動し直しても控えから（作らない）"""
    p = song
    first = server.song_data(p)
    assert fake == [NAME] and _reopen(p) == first and fake == [NAME]
    written._save(_proj(shift=1), p)                 # 作り直した（結果のファイルとこちらで書いた印）
    assert _reopen(p)['n'] == 2
    proj = nlmf.load(p)
    proj['markers'].append({'beat': 40, 'name': 'アウトロ'})
    nlmf.save(proj, p)                               # NLM で保存した（印はそのまま）
    assert _reopen(p)['n'] == 3 and _reopen(p)['n'] == 3
    server.save_work(p, dict(server.load_work(p), diff='Hard'))   # 基準を置き直した（見る難易度の基準）
    d = _reopen(p)
    assert d['n'] == 4 and d['base'] == 'Hard'
    ons = server.CACHE / NAME / 'onsets.json'
    ons.write_text('{}', encoding='utf-8')           # 分けた音の打点の控えが変わった
    assert _reopen(p)['n'] == 5
    (server.CACHE / NAME / 'vocals.flac').touch()    # 分けた音を作り直した
    os.utime(server.CACHE / NAME / 'vocals.flac', ns=(1, 1))
    assert _reopen(p)['n'] == 6 and _reopen(p)['n'] == 6
    assert len(_files(p)) == 1                       # 曲ごとに 1 つ（前の鍵の控えは消す）


def test_code_version(song, fake, monkeypatch):
    """作り方の版が変わったら作り直す・起動した後にコードを直していたら控えを書かない（古いコードで作った物を新しい版の鍵で残さない）"""
    p = song
    server.song_data(p)
    monkeypatch.setattr(songcache, 'CODE', 'x' * 16)          # 曲のデータを作るコードを直して起動し直した
    assert _reopen(p)['n'] == 2 and _reopen(p)['n'] == 2 and len(_files(p)) == 1
    monkeypatch.setattr(songcache, '_CODE_STATS', [])         # サーバーが動いている間にコードを直した → 書かない
    monkeypatch.setattr(songcache, 'CODE', 'y' * 16)
    assert _reopen(p)['n'] == 3 and _reopen(p)['n'] == 4


def test_broken_file_is_rebuilt(song, fake):
    """壊れた控え（書きかけ・gzip でない）は無い物として作り直し、書き直す"""
    p = song
    server.song_data(p)
    (f,) = (server.CACHE / NAME).glob('song_data.*.json.gz')
    f.write_bytes(gzip.compress(b'{"n": 1, "broken'))
    assert _reopen(p)['n'] == 2 and json.loads(gzip.decompress(f.read_bytes()))['n'] == 2
    f.write_bytes(b'not gzip')
    assert _reopen(p)['n'] == 3 and _reopen(p)['n'] == 3


def test_lazy_modules_light_side():
    """サーバーの cli は使う時に読む: こちらで書いた印の関数は automap.written の物（__main__ と同じ物）・ほかは本物から・差し替えも本物に"""
    assert server.cli._save is written._save is cli._save and server.cli._edited_since_written is cli._edited_since_written
    assert server.cli._cover_clips is cli._cover_clips
    import versions
    assert versions.cli._state_path is written._state_path and versions.intent.changed_ranges


def test_code_files_cover_what_song_data_loads(song):
    """曲のデータを作る時に読むリポジトリの中のモジュールは、全部作り方の版（songcache.CODE_FILES）に入っている＝コードを直したら控えが外れる。
    控えから開く別のプロセスは、重い部品（numpy・scipy・作る処理）を読まない・同じ答え"""
    o, c = server.OUT, server.CACHE
    prog = r'''
import json, sys
sys.path.insert(0, sys.argv[1] + '/app')
import server, songcache
from pathlib import Path
server.OUT, server.CACHE = Path(sys.argv[2]), Path(sys.argv[3])
p = server.OUT / sys.argv[4]
body = json.dumps(server.song_data(p), ensure_ascii=False, separators=(',', ':'))
root = Path(sys.argv[1]).resolve()
mine = sorted({Path(m.__file__).resolve().relative_to(root).as_posix() for m in list(sys.modules.values())
               if getattr(m, '__file__', None) and root in Path(m.__file__).resolve().parents
               and '.venv' not in Path(m.__file__).resolve().parts})
heavy = [m for m in ('numpy', 'scipy', 'soundfile', 'automap.__main__', 'songdata', 'automap.music', 'automap.intent') if m in sys.modules]
print(json.dumps({'mine': mine, 'code': sorted(f.relative_to(root).as_posix() for f in songcache.CODE_FILES), 'heavy': heavy,
                  'body': body}, ensure_ascii=False))
'''
    run = lambda: json.loads(subprocess.run([sys.executable, '-c', prog, str(ROOT), str(o), str(c), song.name], capture_output=True,
                                            text=True, encoding='utf-8', check=True, env=dict(os.environ, PYTHONIOENCODING='utf-8')).stdout)
    a = run()   # 控えが無い → 作る
    assert 'automap/music.py' in a['mine'] and a['heavy']   # 本当に作った（重い部品を読んだ）
    missing = sorted(set(a['mine']) - set(a['code']) - {'automap/version.py'})   # version は VERSION の値だけを版に入れる
    assert not missing, f'曲のデータを作る時に読むのに作り方の版に入っていない: {missing}（songcache.ROOTS・読み方を直す）'
    assert {'app/server.py', 'app/songdata.py', 'automap/music.py', 'automap/written.py'} <= set(a['code'])
    assert 'automap/__main__.py' not in a['code'] and 'automap/flow.py' not in a['code']   # 作る処理を直しても控えは外れない
    b = run()   # 控えから
    assert b['heavy'] == [] and b['body'] == a['body']


def test_prepare_before_onsets(song):
    """取り込みの先回り（songdata.prepare・2026-11-11）: onsets.json がまだ無い間は待ち、書かれたら拍ごとの特徴まで作って控える。
    その後の曲のデータは控えを使い、控えを使わずに作った物と 1 バイトも違わない。onsets.json が来ないまま止めればやめる"""
    import threading
    import time as _time
    import songdata
    stems = server.CACHE / NAME
    songdata._MEMO.clear()
    stop = threading.Event()
    got = []
    th = threading.Thread(target=lambda: got.append(songdata.prepare(song, stems, stop)))
    th.start()
    _time.sleep(0.5)
    assert th.is_alive() and not got   # onsets.json がまだ無い＝待っている（大きさの線は先に作る）
    assert sum(k[0] == 'env' for k in songdata._MEMO) == 4
    from automap import music, rhythm   # compose が書くのと同じ物（打点の候補 → 曲の中身）
    rhythm.analyze(stems, BPM, 0)
    music.analyze(stems, json.loads((stems / 'onsets.json').read_text(encoding='utf-8'))['onsets'], BPM, 0, int(SECS * BPM / 60))
    th.join(10)
    assert got == [True] and any(k[0] == 'feat' for k in songdata._MEMO)
    calls = []
    orig = songdata.music.beat_features
    songdata.music.beat_features = lambda *a, **k: calls.append(1) or orig(*a, **k)
    try:
        warm = J(server.song_data(song))
        assert not calls   # 控えから（作り直さない）
        songdata._MEMO.clear()
        server._DATA.clear()
        (stems / [f for f in os.listdir(stems) if f.startswith('song_data.')][0]).unlink()
        assert J(server.song_data(song)) == warm and calls == [1]
    finally:
        songdata.music.beat_features = orig
    stop2 = threading.Event()
    stop2.set()
    (stems / 'onsets.json').unlink()
    assert songdata.prepare(song, stems, stop2) is False   # 止めた後に 1 度見て、無ければやめる
