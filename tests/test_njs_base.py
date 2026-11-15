"""3D で決めた NJS を曲の基準の NJS にする（2026-11-09 利用者・automap/njs.py・app/njsbase.py・compose の _set_njs）:
決めた値は基準にそのまま（作り直しても動かさない）・これから作る派生は 決めた値＋（派生の式 − 基準の式）・OFF で式に戻る・
作ってある派生は切り替えで変わらない・NLM で直された値は作り直しで触らない・画面の保存（作業ファイルの njs）で消えない・
曲の全体に効く設定に数えない（前の譜面に寄せるのを止めない）。展開の側（app/expand.py）は tests/test_expand.py"""
import json
import sys
from pathlib import Path

import pytest

from automap import diffs, nlmf, njs
from automap import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
NM, HD = diffs.key('Normal'), diffs.key('Hard')
STARS = {'Normal': 5.2, 'Hard': 5.8, 'ExpertPlus': 7.0}   # Brotherhood の数（基準 Normal ★5.2・BPM 94.7）

pytestmark = pytest.mark.usefixtures('pinned_scale')


def _nj(e):
    """njsCfg の項目の NJS の分だけ（オフセットは NJS で決まる＝見え始める距離のテストで別に確かめる）"""
    return {k: v for k, v in e.items() if k not in ('offset', 'auto_offset')}


def _notes(n=40):
    return [{'beat': b + 0.0, 'x': 1 + (i % 2), 'y': 0, 'c': i % 2, 'd': 1 if (i // 2) % 2 == 0 else 0} for i, b in enumerate(range(1, n + 1))]


def _proj(njs_cfg=None):
    """基準 Normal（作ったクリップ）・派生 Hard（作ったクリップ）・BPM 94.72"""
    empty = lambda name: {'name': name, 'v3': True, 'base': {}, 'notes': [], 'bombs': [], 'walls': [], 'arcs': [], 'chains': [],
                          'lightEvents': [], 'sections': []}
    p = {'format': 'nlmf', 'version': 2, 'bpm': 94.72, 'tempoParts': [], 'current': 'NormalStandard.dat', 'notesLanes': 1, 'lightLanes': 1,
         'markers': [{'beat': 0, 'name': 'A'}], 'laneStates': {'mute': [], 'solo': [], 'lock': []}, 'njsCfg': dict(njs_cfg or {}),
         'graph': {'out': {'diffs': {'Normal': 1, 'Hard': 1}}}, 'infoGraph': {'nodes': {'s1': {'t': 'set', 'data': {'diffs': {'Normal': 1, 'Hard': 1}}}}},
         'difficulties': {NM: empty('NormalStandard.dat'), HD: empty('HardStandard.dat')}}
    nlmf.put_note_lane(p, {NM: cli._cover_clips(p, _notes(), 44)})
    nlmf.put_clips(p, HD, cli._cover_clips(p, _notes(), 44), 0)
    return p


@pytest.fixture
def stars(monkeypatch, tmp_path):
    """作り直しの側の★（rating.measure_proj）: 難易度ごとに決まった★・測った難易度の控え。設定は本物を読まない"""
    from automap import rating
    asked = []
    monkeypatch.setattr(rating, 'measure_proj', lambda proj, diff='ExpertPlus', *a, **k: (asked.append(diff), {'ok': True, 'stars': STARS[diff]})[1])
    monkeypatch.setattr(njs, 'CONFIG', tmp_path / 'none.json')
    monkeypatch.delenv('AUTOMAP_NJS_OFFSET', raising=False)
    return asked


# ---- 決まり（automap/njs.py） ----

def test_from_base_keeps_the_formula_gaps():
    """利用者の例: 基準 Normal ★5.2 の式 13 → 決めた 17（＋4）なら Hard ★5.8（式 14.5）は 18.5・Expert+ ★7.0（式 16.5）は 20.5"""
    assert njs.from_base(17, 14.5, 13) == 18.5 and njs.from_base(17, 16.5, 13) == 20.5
    assert njs.from_base(17, 13, 13) == 17 and njs.from_base(17, 11.5, 13) == 15.5   # 下の派生も同じ間隔で
    assert njs.from_base(17.3, 14.5, 13) == 19.0   # 0.5 きざみ
    assert njs.from_base(23, 24, 13) == njs.RANGE[1] and njs.from_base(9, 8, 13) == njs.RANGE[0]   # RANGE の中


def test_settle_measures_at_the_formula_speed():
    """★は NJS で少し変わる: 3D で決めた 17 の速さで測った★だと式が 13.5 になるが、式の値（13.5）の速さで測り直すと 13（Brotherhood で起きた）。
    今の NJS が式の値なら測り直さない・★が測れなければ 1 秒のノーツの式"""
    asked = []

    def at(v):
        asked.append(v)
        return 4.5 + 0.05 * (v - 13)   # 速いほど★が少し高い
    assert njs.suggest('Normal', 94.72, stars=at(17))[0] == 13.5
    asked.clear()
    assert njs.settle('Normal', 94.72, at, 17)[0] == 13.0 and asked == [17, 13.5]
    asked.clear()
    assert njs.settle('Normal', 94.72, at, 13.0)[0] == 13.0 and asked == [13.0]
    assert njs.settle('Normal', 94.72, lambda v: None, 17, nps=3.0)[1].startswith('1秒のノーツ')
    p = {'njsCfg': {NM: {'njs': 17, 'offset': 0.25, 'auto': 17}}}
    q = njs.with_njs(p, NM, 13)
    assert q['njsCfg'][NM] == {'njs': 13.0, 'offset': 0.25, 'auto': 17} and p['njsCfg'][NM]['njs'] == 17   # 元は変えない


def test_decided_reads_the_work_file():
    assert njs.decided({'njs': {'base': 17}}) == 17.0 and njs.decided({'njs': {'base': 17.25}}) == 17.25
    for w in ({}, {'njs': None}, {'njs': {'base': None}}, {'njs': {'base': True}}, {'njs': {'base': '17'}}, {'njs': {'base': 40}},
              {'njs': 17}, None):
        assert njs.decided(w) is None, w


def test_put_overwrites_and_apply_force_skips_the_wobble_guard():
    p = {'njsCfg': {NM: {'njs': 18, 'offset': 0.25, 'auto': 13}}}   # NLM で直した値
    assert njs.user_value(p['njsCfg'][NM]) == 18
    njs.put(p, NM, 17)
    assert p['njsCfg'][NM] == {'njs': 17.0, 'offset': 0.25, 'auto': 17.0} and njs.user_value(p['njsCfg'][NM]) is None
    assert njs.apply(p, NM, 17.5) == ('same', 17.0)   # 式の値（★の揺れの守り・前のまま）
    assert njs.apply(p, NM, 17.5, force=True) == ('wrote', 17.5)
    assert njs.apply(p, NM, 17.5, force=True) == ('same', 17.5)
    p['njsCfg'][NM]['njs'] = 19   # NLM で直した＝force でも触らない
    assert njs.apply(p, NM, 16, force=True) == ('kept', 19)


# ---- 作り直し（compose の _set_njs） ----

def test_rebuild_writes_the_decided_value_as_is(stars):
    """基準は決めた値そのまま（★は測らない・★が変わっても動かさない）。ON の後で NLM で直された値は触らない。njs_auto: false でも書く"""
    p = _proj({NM: {'njs': 13.0, 'offset': 0, 'auto': 13.0}})
    line = cli._set_njs(p, NM, nlmf.tempo_of(p), base=17)
    assert _nj(p['njsCfg'][NM]) == {'njs': 17.0, 'auto': 17.0} and '3D で決めた' in line and stars == []
    assert p['njsCfg'][NM]['offset'] == p['njsCfg'][NM]['auto_offset'] == njs.offset_for('Normal', 17, 94.72) and 'JD 20.3m' in line
    STARS['Normal'] = 9.0   # 作り直して★が変わった
    try:
        cli._set_njs(p, NM, nlmf.tempo_of(p), base=17)
    finally:
        STARS['Normal'] = 5.2
    assert p['njsCfg'][NM]['njs'] == 17.0
    p['njsCfg'][NM]['njs'] = 18   # NLM で直した
    line = cli._set_njs(p, NM, nlmf.tempo_of(p), base=17)
    assert _nj(p['njsCfg'][NM]) == {'njs': 18, 'auto': 17.0} and 'NLM で直した値のまま' in line
    assert p['njsCfg'][NM]['offset'] == njs.offset_for('Normal', 18, 94.72)   # オフセットはアプリの物＝NLM で直した NJS で狙いの JD に
    q = _proj()
    njs.CONFIG.write_text('{"njs_auto": false}', encoding='utf-8')
    cli._set_njs(q, NM, nlmf.tempo_of(q), base=16.5)
    assert q['njsCfg'][NM]['njs'] == 16.5


def test_derived_from_the_decided_base(stars):
    """派生 Hard: 決めた値 17＋（Hard の式 − Normal の式）。固定の物差しで Normal ★5.2＝13.5・Hard ★5.8＝15 → 18.5。
    基準の式の値を渡されれば測らない（展開が 1 回だけ測る）。決めていなければ前と同じ式の値"""
    p = _proj()
    tm = nlmf.tempo_of(p)
    assert njs.suggest('Normal', 94.72, stars=5.2)[0] == 13.5 and njs.suggest('Hard', 94.72, stars=5.8)[0] == 15.0
    dv = {'base': 'Normal', 'bkey': NM}
    line = cli._set_njs(p, HD, tm, base=17, dv=dv)
    # 式の値は、その値の速さで測り直す（今の Hard・Normal は NLM の既定 10＝式と違う）
    assert _nj(p['njsCfg'][HD]) == {'njs': 18.5, 'auto': 18.5} and stars == ['Hard', 'Hard', 'Normal', 'Normal'] and '3D で決めた基準の NJS 17' in line
    stars.clear()
    cli._set_njs(p, HD, tm, base=17, base_formula=13.0, dv=dv)   # 0.5 以内（18.5 → 19）でも書く
    assert p['njsCfg'][HD]['njs'] == 19.0 and stars == ['Hard', 'Hard']
    q = _proj()
    cli._set_njs(q, HD, tm, dv=dv)   # 決めていない＝式（前と同じ）
    assert q['njsCfg'][HD]['njs'] == 15.0 and q['njsCfg'].get(NM) is None
    p['njsCfg'][HD]['njs'] = 14   # NLM で直した派生は触らない
    assert 'NLM で決めた値のまま' in cli._set_njs(p, HD, tm, base=17, base_formula=13.0, dv=dv) and p['njsCfg'][HD]['njs'] == 14


def test_base_value_last_decided_wins():
    """派生の元にする基準の NJS: NLM で直されていればその値（3D が OFF でも）・アプリが書いた値なら 3D で決めた値・どちらも無ければ式"""
    nlm = {'njsCfg': {NM: {'njs': 16, 'offset': 0, 'auto': 17}}}
    assert njs.base_value(nlm, NM, 17) == (16.0, 'nlm') and njs.base_value(nlm, NM, None) == (16.0, 'nlm')
    app = {'njsCfg': {NM: {'njs': 17, 'offset': 0, 'auto': 17}}}
    assert njs.base_value(app, NM, 17) == (17.0, '3d') and njs.base_value(app, NM, None) == (None, None)
    assert njs.base_value({'njsCfg': {NM: {'njs': 15, 'offset': 0}}}, NM, None) == (15.0, 'nlm')   # auto の印が無い＝NLM で決めた
    assert njs.base_value({}, NM, None) == (None, None)


def test_derived_from_the_nlm_value_of_the_base(stars):
    """3D で決めた後に NLM で基準を 16 に直した＝NLM の値が勝つ: 派生 Hard は 16＋（15 − 13.5）＝17.5。「譜面に使う」が OFF（base が無い）
    でも同じ。3D で決め直した（アプリが書いた値に戻った）後は 3D の値から"""
    tm = None
    dv = {'base': 'Normal', 'bkey': NM}
    for base in (17, None):
        p = _proj({NM: {'njs': 16, 'offset': 0, 'auto': 17}})
        tm = nlmf.tempo_of(p)
        line = cli._set_njs(p, HD, tm, base=base, dv=dv)
        assert p['njsCfg'][HD]['njs'] == 17.5 and 'NLM で直した基準の NJS 16' in line, (base, line)
        assert p['njsCfg'][NM] == {'njs': 16, 'offset': 0, 'auto': 17}   # 基準は触らない
    p = _proj({NM: {'njs': 17.0, 'offset': 0, 'auto': 17.0}})   # 3D で決め直した
    cli._set_njs(p, HD, tm, base=17, dv=dv)
    assert p['njsCfg'][HD]['njs'] == 18.5
    p = _proj({NM: {'njs': 13.5, 'offset': 0, 'auto': 13.5}})   # 基準が式のまま＝派生も式どおり（前と同じ）
    cli._set_njs(p, HD, tm, dv=dv)
    assert p['njsCfg'][HD]['njs'] == 15.0


# ---- アプリの受け口（app/njsbase.py） ----

@pytest.fixture
def app(tmp_path, monkeypatch, stars):
    """写しの場所で server・njsbase・rating（★は決まった値）をつなぐ → (server, njsbase, 結果のファイル)"""
    import server
    import njsbase
    import rating as AR
    from automap import rating
    monkeypatch.setattr(server, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(server, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'config.local.json')
    monkeypatch.setattr(server, 'COMPOSE_EXTRA', [])
    (tmp_path / 'out').mkdir()
    AR.routes(server)
    njsbase.routes(server)

    def fake_run(exe, req, timeout=300):
        dn = req['targets'][0]['difficulty']
        return {'ok': True, 'version': 't', 'results': [{'difficulty': dn, 'notes': 40, 'skipped': None,
                                                         'ratings': {'none': {'stars': STARS[dn], 'pass': 1, 'tech': 1, 'acc': 1, 'predictedAcc': 0.9}}}]}
    monkeypatch.setattr(rating, 'run', fake_run)
    monkeypatch.setattr(rating, 'rating_exe', lambda: 'fake.exe')
    monkeypatch.setattr(rating, 'exe_version', lambda exe: 't')
    p = tmp_path / 'out' / 'T.intent-s1.nlmf'
    cli._save(_proj({NM: {'njs': 13.5, 'offset': 0, 'auto': 13.5}, HD: {'njs': 15.0, 'offset': 0, 'auto': 15.0}}), p)
    server.save_work(p, {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}, 'diff': 'Normal'})
    return server, njsbase, p


def _cfg(p):
    return nlmf.load(p)['njsCfg']


def _cfgn(p):
    return {k: _nj(e) for k, e in _cfg(p).items()}


def test_on_writes_the_base_now(app):
    """ON（17）: すぐ結果のファイルの基準（Normal）に書く・作業ファイルの njs・派生（Hard）はそのまま・こちらで書いた印のまま"""
    server, N, p = app
    r = N.post({'file': p.name, 'base': 17})
    assert r['wrote'] and r['decided'] == 17 and r['njs'] == 17 and r['user'] is None and r['base'] == 'Normal'
    assert _cfgn(p) == {NM: {'njs': 17.0, 'auto': 17.0}, HD: {'njs': 15.0, 'auto': 15.0}} and _cfg(p)[HD]['offset'] == 0   # 派生は触らない
    assert server.load_work(p)['njs'] == {'base': 17.0} and not cli._edited_since_written(p)
    assert not N.post({'file': p.name, 'base': 17})['wrote']   # 同じ値は書かない
    r = N.post({'file': p.name, 'base': 17.5})   # 欄を変えた＝付いてくる
    assert r['njs'] == 17.5 and _cfg(p)[HD]['njs'] == 15.0
    s = N.get({'file': p.name, 'wait': '5'})
    assert s['formula'] == {'state': 'done', 'value': 13.5, 'how': '★5.20・BPM 94.72・Normal', 'stars': 5.2}
    for bad in (4, 31, 'x', True, [17]):
        with pytest.raises(ValueError):
            N.post({'file': p.name, 'base': bad})


def test_on_overwrites_an_nlm_value_but_sync_does_not(app):
    """NLM で直された基準の NJS: ON（明示して決めた）は上書きする。開いた時の合わせ（sync）は NLM の値を使う"""
    server, N, p = app
    proj = nlmf.load(p)
    proj['njsCfg'][NM] = {'njs': 18, 'offset': 0, 'auto': 13.5}
    cli._save(proj, p)
    server.save_work(p, dict(server.load_work(p), njs={'base': 17}))
    r = N.post({'file': p.name, 'mode': 'sync'})
    assert not r['wrote'] and r['user'] == 18 and 'NLM で 18 に直した値を基準に使っている' in r['line'] and _cfg(p)[NM]['njs'] == 18
    r = N.post({'file': p.name, 'base': 17})   # NLM で直した後に 3D で決め直した＝3D の値で上書き（明示した操作が後）
    assert r['wrote'] and r['user'] is None and _nj(_cfg(p)[NM]) == {'njs': 17.0, 'auto': 17.0} and '上書き' in r['line'] and 'JD 20.3m' in r['line']
    proj = nlmf.load(p)
    proj['njsCfg'][NM]['njs'] = 18   # また NLM で直した
    cli._save(proj, p)
    assert N.post({'file': p.name, 'mode': 'sync'})['user'] == 18 and server.load_work(p)['njs'] == {'base': 17.0}   # 開いただけ＝NLM の値・作業ファイルは 3D で決めた値のまま
    assert N.post({'file': p.name, 'mode': 'set'})['njs'] == 17   # 画面が決め直した（欄に同じ値を打った）＝3D の値で上書き


def test_off_goes_back_to_the_formula(app):
    """OFF: 式の値（★5.2・BPM 94.72・Normal＝13.5）に戻す・作業ファイルから njs を消す・派生はそのまま。
    ON の後で NLM で直された値は OFF でも触らない"""
    server, N, p = app
    N.post({'file': p.name, 'base': 17})
    r = N.post({'file': p.name, 'base': None})
    assert r['wrote'] and r['decided'] is None and r['njs'] == 13.5 and 'njs' not in server.load_work(p)
    assert _cfgn(p) == {NM: {'njs': 13.5, 'auto': 13.5}, HD: {'njs': 15.0, 'auto': 15.0}}
    N.post({'file': p.name, 'base': 17})
    proj = nlmf.load(p)
    proj['njsCfg'][NM]['njs'] = 16   # ON の後で NLM で直した
    nlmf.save(proj, p)
    assert N.get({'file': p.name})['user'] == 16
    r = N.post({'file': p.name, 'base': None})
    assert not r['wrote'] and _cfg(p)[NM]['njs'] == 16 and 'NLM で 16 に直した値を基準に使っている' in r['line']


def test_busy_and_missing_base(app, monkeypatch):
    server, N, p = app
    monkeypatch.setattr(server, 'busy', lambda f: True)
    with pytest.raises(ValueError):
        N.post({'file': p.name, 'base': 17})
    monkeypatch.setattr(server, 'busy', lambda f: False)
    server.save_work(p, dict(server.load_work(p), diff='Expert'))   # 基準の難易度が結果のファイルに無い
    r = N.post({'file': p.name, 'base': 17})
    assert not r['wrote'] and 'Expert が無い' in r['line'] and not r['has_base'] and server.load_work(p)['njs'] == {'base': 17.0}


def test_rebuild_gets_the_decided_value_and_screen_save_keeps_it(app):
    """作り直し（COMPOSE_EXTRA）に --njs-base・画面の保存（PUT /api/work＝store.js の workBody が njs を通す）で残る・
    曲の全体に効く設定に数えない（変えても前の譜面に寄せる）・「意思入れも戻す」でも今の物のまま"""
    server, N, p = app
    import versions
    assert N.compose_extra in server.COMPOSE_EXTRA and N.compose_extra(p, server.load_work(p)) == []
    N.post({'file': p.name, 'base': 17})
    assert N.compose_extra(p, server.load_work(p)) == ['--njs-base', '17']
    body = {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}, 'diff': 'Normal', 'njs': {'base': 17}}   # 画面の自動保存の形
    server.save_work(p, body)
    assert server.load_work(p)['njs'] == {'base': 17}
    assert versions._settings({'njs': {'base': 17}, 'diff': 'Normal'}) == {} and 'njs' in versions.KEEP_ON_RESTORE
    store = (ROOT / 'app' / 'static' / 'js' / 'store.js').read_text(encoding='utf-8')
    assert '...(W.njs ? {njs: W.njs} : {})' in store and 'S.W.njs = w.njs' in store   # workBody・setWork が通す（通さないと保存で消える）


def test_get_reports_the_state(app):
    server, N, p = app
    s = N.get({'file': p.name})
    assert (s['base'], s['decided'], s['njs'], s['auto'], s['user'], s['set'], s['has_base'], s['default']) == \
        ('Normal', None, 13.5, 13.5, None, True, True, 10) and 'formula' not in s
    proj = nlmf.load(p)
    proj['njsCfg'].pop(NM)
    cli._save(proj, p)
    s = N.get({'file': p.name, 'wait': '3'})
    assert s['njs'] == 10 and not s['set'] and s['formula']['value'] == 13.5   # 項目が無い＝NLM の既定
    assert json.loads(json.dumps(s)) == s


# ---- 見え始める距離（JD）（2026-11-10・njs.fix_jd） ----

def test_rebuild_fixes_the_other_difficulties(stars):
    """基準の作り直し: ほかの難易度（アプリが NJS を書いた物）のオフセットも整える（前の版の派生はオフセット 0）・報告の行に出す"""
    p = _proj({HD: {'njs': 15.0, 'offset': 0, 'auto': 15.0}})
    line = cli._set_njs(p, NM, nlmf.tempo_of(p), base=17)
    assert 'Hard' not in line
    more = cli._fix_jd_others(p, NM)
    assert more.startswith('- 見え始める距離（JD）をほかの難易度でも整えた: Hard ') and p['njsCfg'][HD]['offset'] == njs.offset_for('Hard', 15.0, 94.72)
    assert cli._fix_jd_others(p, NM) == ''


def test_open_fixes_the_offsets(app):
    """曲を開いた時（POST /api/njs/jd）: アプリが NJS を書いた難易度のオフセットを狙いの JD に・2 回目は書かない・作り直しの間は何もしない"""
    server, N, p = app
    r = N.fix_jd({'file': p.name})
    assert r['wrote'] and r['line'].startswith('見え始める距離（JD）を整えた: Normal ') and r['jd']['target'] == njs.JD_TARGET
    cfg = _cfg(p)
    assert cfg[NM]['offset'] == njs.offset_for('Normal', 13.5, 94.72) and cfg[HD]['offset'] == njs.offset_for('Hard', 15.0, 94.72)
    assert not cli._edited_since_written(p) and not N.fix_jd({'file': p.name})['wrote']
    assert N.get({'file': p.name})['jd'] == N.JD_INFO
    proj = nlmf.load(p)
    proj['njsCfg'][HD]['offset'] = 0   # 戻して作り直しの間にする
    cli._save(proj, p)
    import pytest as _pt
    with _pt.MonkeyPatch.context() as m:
        m.setattr(server, 'busy', lambda f: True)
        assert not N.fix_jd({'file': p.name})['wrote'] and _cfg(p)[HD]['offset'] == 0
