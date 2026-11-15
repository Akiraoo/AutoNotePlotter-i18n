"""指示の読み込み（app/workio.py）: 読み込める物の一覧・前の形式の変換（server.default_work と同じ）・目盛りの合わせ直し・場所の確かめ"""
import json
import sys
from pathlib import Path

import pytest

from automap import nlmf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))


def _proj(bpm=120, offset=-0.2, parts=()):
    return {'format': 'nlmf', 'version': 2, 'bpm': bpm, 'tempoParts': list(parts), 'graph': {'song': {'offset': offset}},
            'current': 'ExpertPlusStandard.dat', 'difficulties': {}}


def _wj(path, d):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')


R1 = {'b0': 8, 'b1': 16, 'set': {'amount': 1}}
M1 = {'b0': 16, 'b1': 20, 'set': {'motif': {'group': 'g', 'mode': 'same'}}}
M2 = {'b0': 24, 'b1': 28, 'set': {'motif': {'group': 'g', 'mode': 'same'}}}
WORK = {'version': 1, 'song': 'T', 'ranges': [R1, R1, M1, M2], 'line': [{'b': 4, 'k': 1.2, 'smooth': False}],
        'auto_rest': {'on': True, 'b': 40}, 'saved': '2026-10-26T10:00:00'}
LEGACY = {'version': 1, 'song': 'T', 'bpm': 120, 'lead_ms': 200, 'ranges': [dict(R1, t0=3.8, t1=7.8), dict(R1, t0=3.8, t1=7.8), M1],
          'line': [{'b': 4, 'k': 1.23}, {'b': 12, 'k': 0.87}], 'auto_rest': {'on': False, 'b': None}}


@pytest.fixture
def app(tmp_path, monkeypatch):
    """写しの場所（tmp_path/out）で server と workio をつなぐ → (server, workio, 結果のファイル, out)"""
    import server
    import workio
    out = tmp_path / 'out'
    monkeypatch.setattr(server, 'OUT', out)
    monkeypatch.setattr(server, 'CACHE', tmp_path / 'cache')
    out.mkdir()
    workio.routes(server)
    p = out / 'T.intent-s1.nlmf'
    nlmf.save(_proj(), p)
    server.save_work(p, {'ranges': [R1], 'line': [], 'auto_rest': {'on': False, 'b': None}})   # 今の作業ファイル（一覧に出さない）
    return server, workio, p, out


def test_sources_kinds(app):
    server, workio, p, out = app
    _wj(out / 'saved' / 'a' / 'T.intent-s1.automap.json', WORK)
    _wj(out / 'saved' / 'a' / 'b' / 'T.intent.json', LEGACY)
    _wj(out / 'T.intent.json', LEGACY)
    _wj(out / 'T.style-s1.automap.json', WORK)
    _wj(out / 'saved' / 'a' / 'U.intent-s1.automap.json', WORK)      # 別の曲
    _wj(out / 'saved' / 'a' / 'T.style-s1.report.json', WORK)         # 作業ファイルでも前の形式でもない
    _wj(out / 'other' / 'T.intent-s1.automap.json', WORK)             # 決まった場所の外
    hd = out / '.history' / 'T'
    for vid, ts in (('20261026-100000-aaaa', 1.0), ('20261026-110000-bbbb', 2.0), ('20261026-120000-cccc', 3.0)):
        _wj(hd / f'T.{vid}.automap.json', WORK if vid != '20261026-120000-cccc' else {'ranges': [R1]})
    _wj(hd / 'T.20261026-100000-aaaa.intent.json', {'ranges': [R1]})   # compose に渡した表（前の形式ではない）
    _wj(hd / 'index.json', [{'id': '20261026-100000-aaaa', 'at': '2026-10-26 10:00:00', 'ts': 1.0, 'title': '作り直した（全部）'},
                            {'id': '20261026-110000-bbbb', 'at': '2026-10-26 11:00:00', 'ts': 2.0, 'title': '作り直した（全部）'},
                            {'id': '20261026-120000-cccc', 'at': '2026-10-26 12:00:00', 'ts': 3.0, 'title': '選んだ区間だけ'}])
    d = workio.sources(p)
    got = [(e['kind'], e['src']) for e in d['sources']]
    assert ('saved', 'saved/a/T.intent-s1.automap.json') in got
    assert ('saved', 'saved/a/b/T.intent.json') in got
    assert ('legacy', 'T.intent.json') in got
    assert ('out', 'T.style-s1.automap.json') in got
    assert not any('U.' in s or 'other/' in s or 'report' in s or s.endswith('.intent-s1.automap.json') and '/' not in s for _, s in got)
    hist = [e for e in d['sources'] if e['kind'] == 'history']
    assert len(hist) == 2   # 同じ中身の 2 版は新しい 1 つに
    assert {e['vid'] for e in hist} == {'20261026-110000-bbbb', '20261026-120000-cccc'}
    assert next(e for e in hist if e['vid'] == '20261026-110000-bbbb')['same'] == 2
    assert [e['kind'] for e in d['sources']] == sorted((e['kind'] for e in d['sources']), key=workio.KIND_ORDER.get)
    sv = next(e for e in d['sources'] if e['src'] == 'saved/a/T.intent-s1.automap.json')
    assert sv['n'] == 3 and sv['line'] == 1 and sv['groups'] == ['g'] and sv['auto_rest'] and sv['at'] == '2026-10-26 10:00:00'


def test_read_source_app(app):
    server, workio, p, out = app
    f = out / 'saved' / 'a' / 'T.intent-s1.automap.json'
    _wj(f, dict(WORK, library={'sources': ['ranked']}, amount={'mode': 'auto'}))
    nlmf.save(_proj(), f.with_name('T.intent-s1.nlmf'))   # 同じ目盛り
    d = workio.read_source(p, 'saved/a/T.intent-s1.automap.json')
    assert [(r['b0'], r['b1']) for r in d['ranges']] == [(8, 16), (16, 20), (24, 28)]   # 全く同じ指示は 1 つに
    assert d['line'] == [{'b': 4, 'k': 1.2, 'smooth': False}] and d['auto_rest'] == {'on': True, 'b': 40}
    assert d['library'] == {'sources': ['ranked']} and d['amount'] is None   # 量の目安の自動＝無いのと同じ
    assert not d['regrid'] and d['grid_note'] == ''


def test_legacy_same_as_default_work(app):
    """前の形式の表の変換は、作業ファイルが無い時の引き継ぎ（server.default_work）と同じ"""
    server, workio, p, out = app
    _wj(out / 'T.intent.json', LEGACY)
    server.work_path(p).unlink()
    dw = server.default_work(p)
    d = workio.read_source(p, 'T.intent.json')
    assert d['legacy'] and not d['regrid']
    assert [{'b0': r['b0'], 'b1': r['b1'], 'set': r['set']} for r in d['ranges']] == dw['ranges']
    assert d['line'] == dw['line'] and d['auto_rest'] == dw['auto_rest']


def test_regrid(app):
    """目盛りが違う時だけ、元の音源の同じ秒へ合わせ直す（1/4 拍の近くはそろえる）"""
    server, workio, p, out = app
    f = out / 'saved' / 'T.intent-s1.automap.json'
    _wj(f, {'ranges': [{'b0': 8, 'b1': 16, 'set': {'hands': 1}}], 'line': [{'b': 8, 'k': 1.1, 'smooth': True}], 'auto_rest': {'on': True, 'b': 16}})
    nlmf.save(_proj(bpm=120, offset=-0.7), f.with_name('T.intent-s1.nlmf'))   # 無音追加が 0.5 秒多い＝1 拍後ろ
    d = workio.read_source(p, 'saved/T.intent-s1.automap.json')
    assert d['regrid'] and '合わせ直した' in d['grid_note']
    assert (d['ranges'][0]['b0'], d['ranges'][0]['b1']) == (7.0, 15.0)
    assert d['line'][0]['b'] == 7.0 and d['auto_rest']['b'] == 15.0
    # テンポパートのある曲: 拍 → 秒 → 拍 で戻る
    g = {'bpm': 120.0, 'lead': 0.1, 'parts': [{'beat': 16.0, 'bpm': 150.0}]}
    for b in (3.0, 16.0, 21.5, 40.25):
        assert workio.regrid_beat(b, g, g) == b
    cur = {'bpm': 120.0, 'lead': 0.1, 'parts': []}
    assert workio.regrid_beat(20.5, g, cur) == pytest.approx(16 + 4.5 * 120 / 150, abs=1e-3)   # 19.6（1/4 拍から離れている）
    assert workio.regrid_beat(20.0, g, cur) == 19.25   # 19.2 は 1/4 拍の近く＝そろえる
    assert workio.same_grid(None, cur) and not workio.same_grid(g, cur)


def test_no_grid_keeps_beats(app):
    server, workio, p, out = app
    _wj(out / 'saved' / 'T.x.automap.json', {'ranges': [R1]})   # 隣に .nlmf が無い
    d = workio.read_source(p, 'saved/T.x.automap.json')
    assert not d['regrid'] and d['grid_note'] and d['ranges'][0]['b0'] == 8


def test_read_source_refuses_outside(app, tmp_path):
    server, workio, p, out = app
    _wj(tmp_path / 'T.intent-s1.automap.json', WORK)
    _wj(out / 'other' / 'T.intent-s1.automap.json', WORK)
    _wj(out / 'saved' / 'U.intent-s1.automap.json', WORK)
    _wj(out / 'saved' / 'T.notes.json', WORK)
    _wj(out / '.history' / 'U' / 'T.v.automap.json', WORK)
    for src in ('../T.intent-s1.automap.json', str(tmp_path / 'T.intent-s1.automap.json'), 'other/T.intent-s1.automap.json',
                'saved/U.intent-s1.automap.json', 'saved/T.notes.json', '.history/U/T.v.automap.json',
                'T.intent-s1.automap.json',   # 今の作業ファイル
                'saved/none.automap.json', 'saved/../../T.intent-s1.automap.json'):
        with pytest.raises(ValueError):
            workio.read_source(p, src)


def test_routes(app):
    server, workio, p, out = app
    g, post = workio.routes(server)
    assert set(g) == {'/api/workio/sources', '/api/workio/source'} and post == {}
    _wj(out / 'T.intent.json', LEGACY)
    assert g['/api/workio/sources']({'file': p.name})['sources'][0]['src'] == 'T.intent.json'
    assert g['/api/workio/source']({'file': p.name, 'src': 'T.intent.json'})['legacy']
    with pytest.raises(ValueError):
        g['/api/workio/sources']({'file': '../x.nlmf'})
