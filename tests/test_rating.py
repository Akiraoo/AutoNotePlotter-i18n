"""作った譜面の★（automap/rating.py・app/rating.py）: .nlmf → nlm-rating に渡す Info.dat・.dat の形（NLM の書き出しと同じ決まり）・
.dat から作った形との往復・答えのまとめ方・受け口の覚え方（同じ中身は測り直さない・同時に頼まれても 1 回）・場所の確かめ。
本物の nlm-rating で測るのは、nlm-rating がある PC だけ（無ければ飛ばす）。譜面はここで作る合成の物だけを使う。"""
import importlib.util
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from automap import nlmf
from automap import rating as R

ROOT = Path(__file__).resolve().parent.parent
DK = 'expertplusstandard.dat'


def _proj(notes=None, njs=None, tempo=()):
    """拍 0〜8（レーン 0）と 8〜16（レーン 1・ミュート）の 2 つのクリップ。見えない所（負の拍・長さ以上）・ライト・空のクリップも置く"""
    a = {'notes': notes if notes is not None else [[0, 1, 0, 0, 1, None], [7.5, 2, 0, 1, 1, None, {'a': 15, '_x': 1}],
                                                     [-1, 0, 0, 0, 1, None], [8, 0, 0, 0, 1, None]],
         'bombs': [[2, 1, 1, None]], 'walls': [[3, 0, 0, 2, 1, 5, None]],
         'chains': [[4, 0, 1, 2, 8, 4.5, 2, 0, 5, 0.8, None]]}   # b c x y d tb tx ty sc s
    secs = [{'id': 'au1', 'beat': 0, 'len': 8, 'track': 0, 'content': a},
            {'id': 'au2', 'beat': 8, 'len': 8, 'track': 1, 'content': {'notes': [[1, 3, 2, 1, 0, None]]}},
            {'id': 'l1', 'beat': 0, 'len': 16, 'track': 0, 'lk': 'l', 'content': {'notes': [[1, 0, 0, 0, 1, None]]}},
            {'id': 'nul', 'beat': 0, 'len': 16, 'track': 2, 'kind': 'null', 'content': {'notes': [[1, 0, 0, 0, 1, None]]}}]
    p = {'format': 'nlmf', 'version': 2, 'bpm': 120, 'tempoParts': list(tempo), 'current': 'ExpertPlusStandard.dat',
         'laneStates': {'mute': ['n1']}, 'njsCfg': {},
         'difficulties': {DK: {'name': 'ExpertPlusStandard.dat', 'v3': True, 'sections': secs}}}
    if njs:
        p['njsCfg'][DK] = njs
    return p


def _files(req):
    return {f['name']: json.loads(f['text']) for f in req['files']}


def test_request_shape():
    req, meta = R.request(_proj(njs={'njs': 18, 'offset': -0.5}, tempo=[{'beat': 16, 'bpm': 240}]))
    f = _files(req)
    assert set(f) == {'Info.dat', 'ExpertPlusStandard.dat'} and req['targets'] == [{'characteristic': 'Standard', 'difficulty': 'ExpertPlus'}]
    bm = f['Info.dat']['_difficultyBeatmapSets'][0]['_difficultyBeatmaps'][0]
    assert f['Info.dat']['_beatsPerMinute'] == 120 and bm['_noteJumpMovementSpeed'] == 18 and bm['_noteJumpStartBeatOffset'] == -0.5
    d = f['ExpertPlusStandard.dat']
    # 見えている物だけ・絶対拍・ミュートのレーンも入る・チェーンの頭は合成（向き 8 → 0）・ライトと空のクリップは入らない
    assert [(n['b'], n['x'], n['y'], n['c'], n['d']) for n in d['colorNotes']] == [(0, 1, 0, 0, 1), (4, 1, 2, 0, 0), (7.5, 2, 0, 1, 1), (9, 3, 2, 1, 0)]
    assert d['colorNotes'][2]['a'] == 15 and '_x' not in d['colorNotes'][2] and d['colorNotes'][0]['a'] == 0
    assert d['bombNotes'] == [{'b': 2, 'x': 1, 'y': 1}]
    assert d['obstacles'] == [{'b': 3, 'x': 0, 'y': 0, 'd': 2, 'w': 1, 'h': 5}]
    assert d['burstSliders'] == [{'b': 4, 'c': 0, 'x': 1, 'y': 2, 'd': 8, 'tb': 4.5, 'tx': 2, 'ty': 0, 'sc': 5, 's': 0.8}]
    assert d['bpmEvents'] == [{'b': 16.0, 'm': 240.0}] and d['version'] == '3.2.0'
    assert meta['notes'] == 4 and meta['bombs'] == 1 and meta['walls'] == 1 and meta['chains'] == 1 and meta['diff'] == 'ExpertPlus'
    assert meta['nps'] == round(4 / 4.5, 2)   # 拍 0〜9＝4.5 秒に 4 ノーツ


def test_default_njs_and_key():
    req, meta = R.request(_proj())
    bm = _files(req)['Info.dat']['_difficultyBeatmapSets'][0]['_difficultyBeatmaps'][0]
    assert bm['_noteJumpMovementSpeed'] == 16 and bm['_noteJumpStartBeatOffset'] == 0   # NLM の既定（ExpertPlus）
    assert R.req_key(req) == R.req_key(R.request(_proj())[0])
    assert R.req_key(req) != R.req_key(R.request(_proj(notes=[[0, 2, 0, 0, 1, None]]))[0])


def test_from_dat_v2_roundtrip():
    """v2 の .dat → .nlmf と同じ形 → .dat（v3）。テンポの変化は _events の 100 だけ（_customData の _BPMChanges は見ない）"""
    info = {'_beatsPerMinute': 150, '_difficultyBeatmapSets': [{'_beatmapCharacteristicName': 'Standard', '_difficultyBeatmaps': [
        {'_difficulty': 'Expert', '_beatmapFilename': 'E.dat', '_noteJumpMovementSpeed': 17, '_noteJumpStartBeatOffset': 0.25}]}]}
    dat = {'_version': '2.2.0', '_notes': [{'_time': 1, '_lineIndex': 1, '_lineLayer': 0, '_type': 0, '_cutDirection': 1},
                                           {'_time': 2, '_lineIndex': 2, '_lineLayer': 1, '_type': 3, '_cutDirection': 0},
                                           {'_time': 3, '_lineIndex': 3, '_lineLayer': 2, '_type': 1, '_cutDirection': 4}],
           '_obstacles': [{'_time': 4, '_lineIndex': 0, '_type': 1, '_duration': 2, '_width': 4}],
           '_events': [{'_time': 8, '_type': 100, '_value': 0, '_floatValue': 180}],
           '_customData': {'_BPMChanges': [{'_time': 0, '_BPM': 999}]}}
    req, meta = R.request(R.proj_from_dat(info, dat, 'Expert'), 'Expert')
    f = _files(req)
    d = f['ExpertStandard.dat']
    assert [(n['b'], n['x'], n['y'], n['c'], n['d']) for n in d['colorNotes']] == [(1, 1, 0, 0, 1), (3, 3, 2, 1, 4)]
    assert d['bombNotes'] == [{'b': 2, 'x': 2, 'y': 1}]
    assert d['obstacles'] == [{'b': 4, 'x': 0, 'y': 2, 'd': 2, 'w': 4, 'h': 3}]
    assert d['bpmEvents'] == [{'b': 8.0, 'm': 180.0}]
    bm = f['Info.dat']['_difficultyBeatmapSets'][0]['_difficultyBeatmaps'][0]
    assert f['Info.dat']['_beatsPerMinute'] == 150 and bm['_noteJumpMovementSpeed'] == 17 and bm['_noteJumpStartBeatOffset'] == 0.25


def test_from_dat_v3_chain_head_once():
    """v3 の .dat のチェーンの頭のノーツは、NLM と同じく持たずに書き出しで合成する＝1 つだけ"""
    info = {'_beatsPerMinute': 120, '_difficultyBeatmapSets': [{'_beatmapCharacteristicName': 'Standard', '_difficultyBeatmaps': [
        {'_difficulty': 'ExpertPlus', '_beatmapFilename': 'X.dat', '_noteJumpMovementSpeed': 16}]}]}
    dat = {'version': '3.2.0', 'bpmEvents': [{'b': 0, 'm': 120}],
           'colorNotes': [{'b': 1, 'x': 1, 'y': 0, 'c': 0, 'd': 1, 'a': 0}, {'b': 2, 'x': 2, 'y': 2, 'c': 1, 'd': 0, 'a': 0}],
           'burstSliders': [{'b': 2, 'x': 2, 'y': 2, 'c': 1, 'd': 0, 'tb': 2.25, 'tx': 2, 'ty': 0, 'sc': 4, 's': 1}],
           'sliders': [{'b': 1, 'c': 0, 'x': 1, 'y': 0, 'd': 1, 'mu': 1, 'tb': 3, 'tx': 1, 'ty': 2, 'tc': 0, 'tmu': 1, 'm': 0}]}
    d = _files(R.request(R.proj_from_dat(info, dat))[0])['ExpertPlusStandard.dat']
    assert [(n['b'], n['c']) for n in d['colorNotes']] == [(1, 0), (2, 1)]
    assert len(d['burstSliders']) == 1 and d['sliders'][0]['tb'] == 3 and d['bpmEvents'] == [{'b': 0.0, 'm': 120.0}]


def test_summarize():
    meta = {'diff': 'ExpertPlus', 'notes': 100}
    ok = {'ok': True, 'version': '0.1.0', 'elapsedMs': 500, 'results': [{'characteristic': 'Standard', 'difficulty': 'ExpertPlus', 'notes': 100,
          'skipped': None, 'ratings': {'none': {'stars': 5.1234, 'pass': 3.1, 'tech': 2.2, 'acc': 7.7, 'predictedAcc': 0.98},
                                       'SS': {'stars': 4.0}}}]}
    r = R.summarize(ok, meta)
    assert r['ok'] and r['stars'] == 5.123 and r['pass'] == 3.1 and r['predicted_acc'] == 0.98 and r['mods'] == {'SS': 4.0}
    sk = R.summarize({'ok': True, 'results': [{'difficulty': 'ExpertPlus', 'skipped': 'tooFewNotes', 'ratings': {'none': {'stars': None}}}]}, meta)
    assert sk['ok'] and sk['skipped'] == 'tooFewNotes' and sk['stars'] is None
    bad = R.summarize({'ok': False, 'error': 'x'}, meta)
    assert not bad['ok'] and bad['error'] == 'x'
    assert R.text(r).startswith('★ 5.12')


def test_no_exe(monkeypatch, tmp_path):
    monkeypatch.setenv('NLM_RATING_EXE', str(tmp_path / 'none.exe'))
    assert R.rating_exe() is None
    r = R.measure_proj(_proj())
    assert not r['ok'] and r['unavailable']


def _synthetic(n):
    """左右交互・振り下ろしと振り上げが交互の合成の譜面（1 拍に 1 ノーツ）"""
    notes = [[float(i), 1 + (i % 2), 0, i % 2, 1 if (i // 2) % 2 == 0 else 0, None] for i in range(n)]
    p = _proj(notes=notes)
    p['difficulties'][DK]['sections'] = [{'id': 'a', 'beat': 0, 'len': n + 4, 'track': 0, 'content': {'notes': notes}}]
    return p


@pytest.mark.skipif(R.rating_exe() is None, reason='nlm-rating が無い')
def test_measure_real():
    r = R.measure_proj(_synthetic(120))
    assert r['ok'] and r['notes'] == 120 and 0 < r['stars'] < 6 and r['pass'] is not None and r['tech'] is not None
    few = R.measure_proj(_synthetic(10))
    assert few['ok'] and few['skipped'] == 'tooFewNotes'


# ---- 受け口（app/rating.py）----

@pytest.fixture
def app(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('app_rating_t', ROOT / 'app' / 'rating.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    out = tmp_path / 'out'
    out.mkdir()

    def out_file(name):
        p = (out / name).resolve()
        if p.parent != out.resolve() or p.suffix != '.nlmf':
            raise ValueError('out/ の .nlmf だけ')
        return p
    work = {}
    ctx = SimpleNamespace(OUT=out, out_file=out_file, base_of=lambda p: p, load_work=lambda p: work)
    m.routes(ctx)
    calls = []

    def fake_run(exe, req, timeout=300):
        calls.append(req)
        time.sleep(0.2)
        n = len(json.loads(req['files'][1]['text'])['colorNotes'])
        return {'ok': True, 'version': 't', 'results': [{'difficulty': 'ExpertPlus', 'notes': n, 'skipped': None,
                                                         'ratings': {'none': {'stars': n / 10, 'pass': 1, 'tech': 1, 'acc': 1, 'predictedAcc': 0.9}}}]}
    monkeypatch.setattr(R, 'run', fake_run)
    monkeypatch.setattr(R, 'rating_exe', lambda: 'fake.exe')
    p = out / 'T.intent-s1.nlmf'
    nlmf.save(_synthetic(30), p)
    return m, out, p, calls, work


def test_route_cache(app):
    m, out, p, calls, work = app
    get = m.routes(m.C)[0]['/api/rating']
    r = get({'file': p.name})
    assert r['state'] == 'done' and r['stars'] == 3.0 and r['file'] == p.name and r['library_stars'] is None and len(calls) == 1
    assert len(list((out / '.rating').glob('*.json'))) == 1
    get({'file': p.name})
    os.utime(p, (time.time() + 5, time.time() + 5))   # 更新時刻だけ変わった（中身は同じ）→ 測り直さない
    assert get({'file': p.name})['stars'] == 3.0 and len(calls) == 1
    nlmf.save(_synthetic(40), p)                      # 中身が変わった → 測り直す
    assert get({'file': p.name})['stars'] == 4.0 and len(calls) == 2
    work['library'] = {'sources': ['ranked'], 'stars': [0, 8]}
    assert get({'file': p.name})['library_stars'] == [0.0, 8.0] and len(calls) == 2


def test_route_remeasure_on_new_exe_version(app, monkeypatch):
    """nlm-rating の版が変わった（BeatLeader の計算が変わった）→ 同じ中身でも測り直す・前の版に戻せば前の答え"""
    m, out, p, calls, _ = app
    ver = ['0.1.0']
    monkeypatch.setattr(R, 'exe_version', lambda exe: ver[0])
    assert m.rate(p, wait=5)['stars'] == 3.0 and len(calls) == 1
    assert m.rate(p, wait=5)['state'] == 'done' and len(calls) == 1
    ver[0] = '0.2.0'
    assert m.rate(p, wait=5)['state'] == 'done' and len(calls) == 2
    assert len(list((out / '.rating').glob('*.json'))) == 2
    ver[0] = '0.1.0'
    assert m.rate(p, wait=5)['state'] == 'done' and len(calls) == 2


def test_exe_version(tmp_path):
    assert R.exe_version(str(tmp_path / 'none.exe')) is None
    exe = R.rating_exe()
    if exe:
        v = R.exe_version(exe)
        assert isinstance(v, str) and v.count('.') == 2


def test_route_once_when_parallel(app):
    m, out, p, calls, _ = app
    res = []
    ts = [threading.Thread(target=lambda: res.append(m.rate(p, wait=5))) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1 and all(r['state'] == 'done' and r['stars'] == 3.0 for r in res)


def test_route_running_then_done(app):
    m, out, p, calls, _ = app
    assert m.rate(p, wait=0)['state'] == 'running'
    assert m.rate(p, wait=5)['state'] == 'done' and len(calls) == 1


def test_route_places(app):
    m, out, p, calls, _ = app
    get = m.routes(m.C)[0]['/api/rating']
    h = out / '.history' / 'T'
    h.mkdir(parents=True)
    nlmf.save(_synthetic(50), h / 'T.v1.nlmf')
    c = out / '.cand' / 'T'
    c.mkdir(parents=True)
    nlmf.save(_synthetic(60), c / 'T.cand2.nlmf')
    assert get({'file': p.name, 'ver': 'v1'})['stars'] == 5.0
    assert get({'file': p.name, 'cand': '2'})['stars'] == 6.0
    assert get({'path': '.history/T/T.v1.nlmf'})['stars'] == 5.0
    (out.parent / 'x.nlmf').write_text('{}', encoding='utf-8')
    for q in ({'path': '../x.nlmf'}, {'path': '.history/../../x.nlmf'}, {'path': '.rating/a.json'}, {'path': str(out.parent / 'x.nlmf')},
              {'file': p.name, 'ver': '../a'}, {'file': '../x.nlmf'}):
        with pytest.raises(ValueError):
            get(q)
    with pytest.raises(FileNotFoundError):
        get({'file': p.name, 'cand': '9'})


def test_route_unavailable(app, monkeypatch):
    m, out, p, calls, _ = app
    monkeypatch.setattr(R, 'rating_exe', lambda: None)
    r = m.routes(m.C)[0]['/api/rating']({'file': p.name})
    assert r['state'] == 'unavailable' and 'nlm-rating' in r['error'] and not calls
