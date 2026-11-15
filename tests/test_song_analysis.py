"""NLM から写した曲の解析（automap/song_analysis/・包みは automap/analyze_song.py）"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from automap import analyze_song as A

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import sync_nlm_analysis as S  # noqa: E402


def test_copy_is_untouched():
    """写した物は SOURCE.md に記録した指紋のまま（手を加えない＝NLM が直した時に写し直すだけで済む）"""
    rec = S.recorded()
    assert set(rec) == set(S.FILES)
    for f in S.FILES:
        assert hashlib.sha256((S.DST / f).read_bytes()).hexdigest() == rec[f], f


def test_at_grid_like_nlm():
    """目盛り（NLM の anaAtGrid）: 拍 k/4 の元の音源の秒＝拍の時刻−無音追加・音源の外は None・1ms に丸める・曲の長さ＋無音追加まで"""
    at = A.at_grid(120, 500, 10.0)   # 1拍 0.5 秒・無音追加 0.5 秒
    assert at[:5] == [None, None, None, None, 0.0]
    assert at[5] == 0.125 and at[8] == 0.5
    assert len(at) == int((10.0 + 0.5) / 0.5 * 4) + 1 and at[-1] is None and at[-2] == 9.875
    assert A.at_grid(129, 210, 5.0)[3] == round(3 / 4 * 60 / 129 - 0.21, 3)


def test_clean_like_nlm_page():
    """NLM の画面が保存の前に整える形（知らない項目を落とす・名前の長さ・区間の並び）・atSec"""
    t = A.clean_tempo({'bpm': 120.0, 'lead_ms': 30.5, 'family': 120.0, 'version': 1, 'drift': [(0, 120.1)], 'steps': [], 'alt': None})
    assert t == {'bpm': 120.0, 'lead_ms': 30.5, 'family': 120.0, 'low_offbeat': False, 'slope_sig': False, 'steps': [], 'drift': [[0, 120.1]], 'alt': None}
    st = A.clean_structure({'sub': 4, 'sections': [{'start': 8, 'end': 16, 'label': 'S2', 'count': 1, 'chorus': True, 'name': 'サビ', 'nameKey': 'chorus'},
                                                   {'start': 0, 'end': 8, 'label': 'S1', 'name': 'イントロ'}], 'segments': [], 'chorus': ['B']})
    assert [s['label'] for s in st['sections']] == ['S1', 'S2'] and 'nameKey' not in st['sections'][1] and st['sections'][0]['count'] == 1
    at = [None, None, 0.0, 0.1, None]
    assert A.at_sec(at, 4, 0, 1) == 0.0 and A.at_sec(at, 4, 1, -1) == 0.1


def _one_pair():
    """比べる 1 曲＝使える中で一番短い曲（構成の解析は曲の長さに比例する・3 分の曲で 25 秒・2 分半で 18 秒。長さは頭を読むだけ＝全部で 0.1 秒）"""
    ys = ROOT / 'cache' / 'yama_set.json'
    if not ys.exists():
        return None
    pairs = []
    for s in json.loads(ys.read_text(encoding='utf-8')):
        pj = ROOT / 'out' / 'yama' / f'{s["name"]}.nlmf'
        if pj.exists() and Path(s['src']).exists():
            pairs.append((A.audio_duration(s['src']), s['name'], pj, s['src']))
    return min(pairs)[2:] if pairs else None


# ---- 答え合わせの控え（2026-11-09 利用者「リリース前に確認が出来ていれば、普段は必要な所だけ流せば良い」）----
# 答えを変え得る物が全部前回と同じで、前回計算して通っていれば計算しない（決まった計算＝入力が同じなら答えも同じ）。どれか違えば・
# 7 日たったら・環境変数 AUTOMAP_FULL_ANALYSIS=1 なら計算する。tools/dist/checkset.py release はその環境変数を立ててテストを流す。
# 控えは .pytest_cache の automap/nlm_same/<tempo|structure>（git の管理外）。結果は pytest の出力の終わりに 1 行ずつ（tests/conftest.py）。
FULL_ENV = 'AUTOMAP_FULL_ANALYSIS'
MEMO_DAYS = 7
MEMO_KEEP = 4    # 鍵をいくつ覚えるか（1 本と並べた時でスレッドの数が違う＝別の鍵）
MEMO_CODE = ('automap/song_analysis/*.py', 'automap/analyze_song.py', 'tools/sync_nlm_analysis.py', 'tests/test_song_analysis.py')
MEMO_ENV = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')


def memo_key(part, pair):
    """答えを変え得る物の指紋: 写したコード・包み・比べる関数・このファイル／Python とすべての部品の版／音源の中身・.nlmf の
    analysis（読むのは比べる時と同じ nlmf.load）／CPU・OS・計算のスレッドの数（スレッドの数で eigh のビットが変わる）"""
    import platform
    from importlib import metadata

    from automap.nlmf import load
    h = hashlib.sha256()

    def add(*xs):
        for x in xs:
            h.update(x if isinstance(x, bytes) else str(x).encode('utf-8'))
            h.update(b'\0')

    add('part', part)
    for pat in MEMO_CODE:
        for p in sorted(ROOT.glob(pat)):
            add(p.relative_to(ROOT).as_posix(), p.read_bytes())
    add(sys.version, platform.platform(), platform.machine(), platform.processor())
    add(*sorted(f'{d.name}=={d.version}' for d in metadata.distributions()))
    add(*(f'{k}={os.environ.get(k, "")}' for k in MEMO_ENV))
    pj, audio = pair
    add(Path(pj).name, Path(audio).name, hashlib.sha256(Path(audio).read_bytes()).hexdigest())
    add(json.dumps(load(pj).get('analysis'), sort_keys=True, ensure_ascii=False))
    return h.hexdigest()


def memo_hit(cache, part, key, now=None):
    """前回この鍵で計算して通った時刻（期限の中なら）・無ければ None"""
    if cache is None or os.environ.get(FULL_ENV, '') not in ('', '0'):
        return None
    rec = ((cache.get(f'automap/nlm_same/{part}', None) or {}).get('runs') or {}).get(key)
    at = (rec or {}).get('at')
    now = time.time() if now is None else now
    return rec if at and 0 <= now - at < MEMO_DAYS * 86400 else None


def memo_store(cache, part, key, sec, now=None):
    if cache is None:
        return
    runs = dict((cache.get(f'automap/nlm_same/{part}', None) or {}).get('runs') or {})
    runs[key] = {'at': time.time() if now is None else now, 'sec': round(sec, 1)}
    runs = dict(sorted(runs.items(), key=lambda kv: -kv[1]['at'])[:MEMO_KEEP])
    cache.set(f'automap/nlm_same/{part}', {'runs': runs})


PART_JA = {'tempo': 'テンポ', 'structure': '構成'}


@pytest.mark.parametrize('part', ['tempo', 'structure'])
def test_same_answer_as_nlm(part, request, record_property):
    """写した物で解析し直すと、NLM が .nlmf に入れた結果（テンポ・区間・細かい区切り・サビの候補）と全く同じになる（1曲・
    テンポ 10 秒・構成 20 秒ほど。構成は .nlmf の BPM で解く＝テンポと別々に比べられるので、2 つに分けて並べて流す）。
    曲と NLM で作った元のプロジェクトがある環境だけ（out/・cache/ は git の管理外）。たくさんの曲は tools/sync_nlm_analysis.py check。
    答えを変え得る物が前回と同じなら控えで済ませる（上の決まり）"""
    pair = _one_pair()
    if not pair:
        pytest.skip('NLM で作った元のプロジェクトと音源が無い')
    cache = getattr(request.config, 'cache', None)
    key = memo_key(part, pair)
    rec = memo_hit(cache, part, key)
    name = f'曲の解析の答え合わせ（{PART_JA[part]}・{Path(pair[0]).stem}）'
    if rec:
        day = time.strftime('%Y-%m-%d %H:%M', time.localtime(rec['at']))
        record_property('automap_memo', f'{name}: 控えと同じ＝計算していない（{day} に計算して NLM と同じだった・'
                                        f'{rec.get("sec", "?")} 秒）。必ず計算するのは {FULL_ENV}=1')
        record_property('automap_memo_hit', True)
        return
    t = time.time()
    r = S.compare(*pair, parts=(part,))
    assert 'skip' not in r, r
    keys = ('tempo',) if part == 'tempo' else ('sections', 'segments', 'chorus')
    assert all(r[k] for k in keys), r
    sec = time.time() - t
    memo_store(cache, part, key, sec)
    record_property('automap_memo', f'{name}: 計算して NLM と同じ（{sec:.1f} 秒）')


def test_memo_rules(tmp_path, monkeypatch):
    """答え合わせの控えの決まり: 同じ鍵・期限の中だけ当たる・必ず計算の環境変数で当たらない・鍵は 4 つまで覚える・
    鍵は答えを変え得る物（ここでは部分・音源の中身・.nlmf の analysis・スレッドの数）で変わる"""
    monkeypatch.delenv(FULL_ENV, raising=False)   # リリース前の確かめ（必ず計算）の中でも決まりを確かめる
    class Cache(dict):
        def get(self, k, d):
            return super().get(k, d)

        def set(self, k, v):
            self[k] = json.loads(json.dumps(v))

    c, now = Cache(), 1_000_000.0
    memo_store(c, 'structure', 'k1', 20.0, now=now)
    assert memo_hit(c, 'structure', 'k1', now=now + 60)['sec'] == 20.0
    assert memo_hit(c, 'structure', 'k2', now=now + 60) is None and memo_hit(c, 'tempo', 'k1', now=now + 60) is None
    assert memo_hit(c, 'structure', 'k1', now=now + MEMO_DAYS * 86400 + 1) is None   # 期限切れ
    assert memo_hit(None, 'structure', 'k1') is None
    monkeypatch.setenv(FULL_ENV, '1')
    assert memo_hit(c, 'structure', 'k1', now=now + 60) is None
    monkeypatch.setenv(FULL_ENV, '0')
    assert memo_hit(c, 'structure', 'k1', now=now + 60)
    for i in range(2, 7):
        memo_store(c, 'structure', f'k{i}', 1.0, now=now + i)
    assert set(c['automap/nlm_same/structure']['runs']) == {'k3', 'k4', 'k5', 'k6'}

    audio, pj = tmp_path / 'a.flac', tmp_path / 'p.nlmf'
    audio.write_bytes(b'abc')
    import automap.nlmf as N
    monkeypatch.setattr(N, 'load', lambda p: {'analysis': {'v': 1}})
    k0 = memo_key('structure', (pj, audio))
    assert memo_key('structure', (pj, audio)) == k0 and memo_key('tempo', (pj, audio)) != k0
    audio.write_bytes(b'abd')
    assert memo_key('structure', (pj, audio)) != k0
    audio.write_bytes(b'abc')
    assert memo_key('structure', (pj, audio)) == k0
    monkeypatch.setattr(N, 'load', lambda p: {'analysis': {'v': 2}})
    assert memo_key('structure', (pj, audio)) != k0
    monkeypatch.setattr(N, 'load', lambda p: {'analysis': {'v': 1}})
    monkeypatch.setenv('OPENBLAS_NUM_THREADS', '7')
    assert memo_key('structure', (pj, audio)) != k0
