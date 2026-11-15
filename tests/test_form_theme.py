"""同じ振りの形の「案 k」・「珍しい型まで」・「★の帯」（docs/アプリ仕様.md 15 節）: 形の設定（intent.form_specs）・形の型の選び直し
（__main__._form_pick・_motif_form_theme）・前の譜面に寄せる時の変わった所・形の別の案（app/versions.py の form）"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from automap import intent, nlmf
from automap import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_versions import _proj, DK  # noqa: E402

BARS = [0, 4, 8, 12, 16, 20, 24, 28, 32, 36]


def _m(b0, mode='arrange', g='X', **st):
    return {'b0': b0, 'b1': b0 + 2, 'set': dict({'motif': {'group': g, 'mode': mode}}, **st)}


def _t(*ranges):
    return {'ranges': list(ranges), 'line': [], 'auto_rest': {'on': False, 'b': None}}


def test_motif_forms_follow_the_screen():
    """形の決まり（store.motifForms と同じ）: 始まりの順で、アレンジは 1回目・3回目…が A・2回目・4回目…が B。ほかは全部 A。休みは除く"""
    it = _t(_m(20), _m(4), _m(12), _m(28), _m(8, 'same', 'Y'), _m(16, 'same', 'Y'), dict(_m(30), set={'motif': {'group': 'X'}, 'rest': 1}))
    f = intent.motif_forms(it)
    assert [r['b0'] for r in f['X']['A']] == [4, 20] and [r['b0'] for r in f['X']['B']] == [12, 28]
    assert [r['b0'] for r in f['Y']['A']] == [8, 16] and f['Y']['B'] == []
    assert intent.motif_forms(None) == {}


def test_form_specs_merge_like_form_set():
    """形の設定: 各回の同じ振りの指示（motif 以外）と、形の区間の中に収まる区間の指示を合わせる。回ごとに違えば付いている回の物・
    同じ種類なら後の回・別に付けた区間が勝つ。A と B は別々。形からはみ出す区間は入らない"""
    it = _t(_m(4, rare=1), _m(12), _m(20, variant=2), _m(28, band=1))
    assert intent.form_specs(it) == {('X', 'A'): {'k': 2, 'rare': True, 'band': None}, ('X', 'B'): {'k': 0, 'rare': False, 'band': 1}}
    it = _t(_m(4, variant=2), _m(12), _m(20, variant=4))   # 回ごとに違う → 後の回
    assert intent.form_specs(it)[('X', 'A')]['k'] == 4
    it = _t(_m(4, variant=2), _m(12), _m(20), {'b0': 4.5, 'b1': 5.5, 'set': {'variant': 3}})   # 中に収まる区間が勝つ
    assert intent.form_specs(it)[('X', 'A')]['k'] == 3
    it = _t(_m(4), _m(12), {'b0': 0, 'b1': 32, 'set': {'rare': 1}})   # はみ出す区間は形に入らない
    assert intent.form_specs(it) == {}
    assert intent.form_specs(_t(_m(4, amount=1, speed=1), _m(12))) == {} and intent.form_specs(None) == {}


def test_theme_ranges_leave_motif_forms_out():
    """小節のテーマを選び直す区間に、同じ振りの区間とその中に収まる区間は入れない（形の型で効く）。またぐ区間・ほかの区間は今まで通り"""
    it = _t(_m(4, rare=1), {'b0': 12, 'b1': 13, 'set': {'variant': 2}}, _m(12), {'b0': 0, 'b1': 16, 'set': {'band': 1}},
            {'b0': 20, 'b1': 24, 'set': {'variant': 3}})
    assert intent.theme_ranges(it, band=True) == [(0, 16, 0, False, 1), (20, 24, 3, False, None)]
    assert intent.theme_ranges(it) == [(20, 24, 3, False)]


def test_form_mixed_lists_the_differing_occurrences():
    """回ごとに設定が違う形（今の利用者の曲の形: A は全部 amount・speed、B は一部だけ）"""
    full = {'amount': 1, 'speed': 1}
    it = _t(_m(4, **full), _m(8, **full), _m(12, **full), _m(16), _m(20, **full), _m(24))
    assert intent.form_mixed(it) == {('X', 'B'): [(16, ['amount', 'speed']), (24, ['amount', 'speed'])]}
    assert intent.form_mixed(_t(_m(4, **full), _m(8, **full))) == {}


class _Th(SimpleNamespace):
    def key(self):
        return self.name


def _pal_of():
    """種 s・珍しい型まで・★の帯ごとに別のテーマの並び（記号 S・T）"""
    calls = []

    def pal_of(s, rare=False, band=None):
        calls.append((s, rare, band))
        tag = f's{s}' + ('r' if rare else '') + (f'b{band}' if band is not None else '')
        return None, {'S': [_Th(name=f'{tag}-{i}') for i in range(6)], 'T': [_Th(name=f'{tag}T-{i}') for i in range(6)]}
    return pal_of, calls


def test_form_pick_uses_the_variant_rule():
    """形の型: 案 k は variant_spec の (ずらし n, 種 s) で pal_of(s, …) の記号の並びの n 番目（小節の「案 k」と同じ決まり）。珍しい型まで・
    ★の帯はその束から。指示が無ければ今まで通り chosen（同じ物）"""
    pal_of, calls = _pal_of()
    chosen = {'S': _Th(name='base')}
    rep = []
    assert cli._form_pick('X', 'A', 'S', chosen, {}, pal_of, rep) is chosen['S'] and not calls and not rep
    sp = {('X', 'A'): {'k': 2, 'rare': False, 'band': None}}
    assert cli._form_pick('X', 'A', 'S', chosen, sp, pal_of, rep).name == 's1-2'
    sp = {('X', 'A'): {'k': 7, 'rare': True, 'band': 1}}   # 案 7＝ずらし 2・種 2
    assert cli._form_pick('X', 'A', 'S', chosen, sp, pal_of, rep).name == 's2rb1-2' and calls[-1] == (2, True, 1)
    sp = {('X', 'A'): {'k': 0, 'rare': True, 'band': None}}
    assert cli._form_pick('X', 'A', 'S', chosen, sp, pal_of, rep).name == 's1r-0' and calls[-1] == (1, True, None)


def test_motif_form_theme_a_and_b():
    """A と B は別々の形: B に設定が無ければ A の型（呼ぶ側が左右を入れ替える＝今まで通り・A を変えると B も変わる）。B の設定は B だけ"""
    pal_of, _ = _pal_of()
    chosen = {'S': _Th(name='base'), 'T': _Th(name='baseT')}
    a, b = {'group': 'X', 'variant': 'a'}, {'group': 'X', 'variant': 'b'}
    cache, rep = {}, []
    sp = {('X', 'A'): {'k': 2, 'rare': False, 'band': None}}
    assert cli._motif_form_theme(a, 'S', chosen, sp, pal_of, cache, rep).name == 's1-2'
    assert cli._motif_form_theme(b, 'T', chosen, sp, pal_of, cache, rep).name == 's1-2'   # A に付けた → B も同じ型（左右入れ替えは呼ぶ側）
    assert rep[-1] == {'g': 'X', 'form': 'B', 'follow': True}
    cache, rep = {}, []
    sp = {('X', 'B'): {'k': 3, 'rare': False, 'band': None}}
    assert cli._motif_form_theme(a, 'S', chosen, sp, pal_of, cache, rep) is chosen['S']   # A は今まで通り
    assert cli._motif_form_theme(b, 'T', chosen, sp, pal_of, cache, rep).name == 's1T-3'   # B は B の最初の打点の区間の記号の並びから
    cache = {}
    assert cli._motif_form_theme(b, 'T', chosen, {}, pal_of, cache, []) is chosen['T'] is cache[('X', 'A')]   # 指示なし＝今まで通り
    lines = cli._form_theme_lines([{'g': 'X', 'form': 'A', 'sp': {'k': 2, 'rare': True, 'band': None}, 'th': _Th(name='n', a=[], b=[], maps=3, src='s'),
                                    'base': _Th(name='o', a=[], b=[], maps=9, src='s'), 'n': 2, 's': 1}, {'g': 'X', 'form': 'B', 'follow': True}], {}, None)
    assert lines[0].startswith('- 同じ振りの形のテーマ: X A は') and '案 2（ずらし 2・種 1）・珍しい型まで' in lines[0] and 'X B は A の型の左右入れ替え' in lines[0]


def test_changing_a_form_frees_the_whole_group():
    """形の設定を変えた（A の全部の回に珍しい型まで）→ 前の譜面に寄せる時の変わった所は、同じ振りのグループの全部の回（B も・小節の頭と終わりまで）"""
    prev = _t(_m(4), _m(12), _m(20), _m(28), {'b0': 32, 'b1': 36, 'set': {'amount': 1}})
    cur = json.loads(json.dumps(prev))
    for r in intent.motif_forms(cur)['X']['A']:
        r['set']['rare'] = True
    free, glob, why = intent.changed_ranges(prev, cur, BARS, 40)
    assert free == [(4, 8), (12, 16), (20, 24), (28, 32)] and not glob and any('同じ振り「X」' in w for w in why)


@pytest.fixture
def app(tmp_path, monkeypatch):
    import server
    import versions
    monkeypatch.setattr(server, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(server, 'CACHE', tmp_path / 'cache')
    (tmp_path / 'out').mkdir()
    versions.routes(server)
    p = tmp_path / 'out' / 'T.intent-s1.nlmf'
    cli._save(_proj(), p)
    full = {'amount': 1, 'speed': 1}
    server.save_work(p, _t(_m(4, **full), _m(8, **full), _m(12, **full), _m(16), {'b0': 12.5, 'b1': 13, 'set': {'variant': 5}},
                           {'b0': 20, 'b1': 28, 'set': {'amount': 2}}))
    return server, versions, p



def test_form_candidates_body(app, monkeypatch):
    """形の別の案（POST /api/cands/start の form）: 形の全部の回の同じ振りの指示に「案 v」（と rare・band）を付けた表を --intent に、今の表を
    前の表（opts.prev_table → compose_extra の --prev-intent）にして全部を作り直す（--only 無し）。only は形の1回目に読み替え。
    中に収まる区間の「案」は外す（そちらが勝つので）。choose の答えに form・variant・rare・band"""
    server, versions, p = app
    got = []
    (p.with_name('T.intent-s1.report.md')).write_text('# 前の報告\n', encoding='utf-8')

    def fake_generate(p_, only=None, out=None, extra=(), kind='generate', opts=None, **meta):
        w = dict(server.load_work(p_), opts=opts or {})
        got.append((only, list(extra), [x for fn in server.COMPOSE_EXTRA if fn is versions.compose_extra for x in fn(p_, w)]))
        return {'state': 'done', 'took': 0.1, 'report': '- 打点 4\n'}

    def fake_job(file, steps, kind='generate', **meta):
        job = {'id': 'j', 'log': '', 'state': 'running', **meta}
        for _, fn in steps:
            fn(job)
        return job
    monkeypatch.setattr(server, 'start_generate', fake_generate)
    monkeypatch.setattr(server, 'start_job', fake_job)
    job = versions.start_cands(p, None, start=2, rare=True, form={'group': 'X', 'form': 'A'})
    assert job['form']['spans'] == [[4.0, 6.0], [12.0, 14.0]] and job['form']['others'] == [[8.0, 10.0], [16.0, 18.0]]
    d = versions.cand_dir(p)
    prev = d / 'T.prev.intent.json'
    assert [g[0] for g in got] == [None, None, None]   # 全部を作り直す
    assert [g[1] for g in got] == [['--intent', str(versions._cand(p, n, '.intent.json'))] for n in (1, 2, 3)]
    assert all(g[2] == ['--prev-intent', str(prev)] for g in got)
    assert (d / 'T.prev.report.md').read_text(encoding='utf-8') == '# 前の報告\n'   # 決めを引き継ぐ報告
    assert json.loads(prev.read_text(encoding='utf-8')) == server.intent_table(server.load_work(p))
    t = json.loads(versions._cand(p, 1, '.intent.json').read_text(encoding='utf-8'))
    by = {(r['b0'], r['b1']): r['set'] for r in t['ranges']}
    assert by[(4, 6)] == {'motif': {'group': 'X', 'mode': 'arrange'}, 'amount': 1, 'speed': 1, 'variant': 2, 'rare': True}
    assert by[(12, 14)]['variant'] == 2 and by[(12, 14)]['rare'] is True and 'variant' not in by[(8, 10)] and 'variant' not in by[(16, 18)]
    assert (12.5, 13) not in by and by[(20, 28)] == {'amount': 2}   # 中に収まる区間の「案」は外す（ほかの項目が無ければ区間ごと）
    assert intent.form_specs(t) == {('X', 'A'): {'k': 2, 'rare': True, 'band': None}}
    m = versions.cands_view(p)
    assert m['form']['group'] == 'X' and m['only'] == [4.0, 6.0] and m['current']['spans'] == 2
    c1 = m['cands'][0]
    assert {'notes', 'same', 'outside_diff', 'others_diff', 'far_diff', 'reset', 'warn'} <= set(c1) and c1['outside_diff'] == c1['far_diff'] == 0
    r = versions.choose(p, 1)
    assert r['form']['group'] == 'X' and r['form']['form'] == 'A' and r['variant'] == 2 and r['rare'] is True and r['band'] is None
    e = versions.list_versions(p)['versions'][0]
    assert e['form']['group'] == 'X' and '「X」の A の形' in e['title']


def test_form_candidates_reject_unknown_forms(app):
    server, versions, p = app
    with pytest.raises(ValueError):
        versions.start_cands(p, None, form={'group': 'Z', 'form': 'A'})
    server.save_work(p, _t(_m(4, 'same')))
    with pytest.raises(ValueError):
        versions.start_cands(p, None, form={'group': 'X', 'form': 'B'})


def test_region_candidates_say_no_form(app, monkeypatch):
    """区間の別の案は今まで通り（--only・--variant）。答えの form は None"""
    server, versions, p = app
    got = []
    monkeypatch.setattr(server, 'start_generate', lambda p_, only=None, out=None, extra=(), kind='generate', **meta:
                        got.append((only, list(extra))) or {'state': 'done', 'took': 0.1, 'report': ''})

    def fake_job(file, steps, kind='generate', **meta):
        job = {'id': 'j', 'log': '', 'state': 'running', **meta}
        for _, fn in steps:
            fn(job)
        return job
    monkeypatch.setattr(server, 'start_job', fake_job)
    versions.start_cands(p, [8, 16])
    assert got == [([8.0, 16.0], ['--variant', 1]), ([8.0, 16.0], ['--variant', 2]), ([8.0, 16.0], ['--variant', 3])]
    assert versions.cands_view(p)['form'] is None and versions.choose(p, 1)['form'] is None


def test_syncing_a_form_is_not_a_change():
    """画面が形の全部の回に同じ設定を書いても（そろえる）、効き方が同じ（付いている回の物が形の全部に効く）なら変わった所にしない。
    効き方が変わる（値を変えた・無かった項目を足した）なら形のグループの全部が変わった所"""
    full = {'amount': 1, 'speed': 1}
    prev = _t(_m(4, **full), _m(8, **full), _m(12, **full), _m(16), _m(20, **full), _m(24))
    cur = _t(*[_m(b, **full) for b in (4, 8, 12, 16, 20, 24)])
    assert intent.changed_ranges(prev, cur, BARS, 40) == ([], False, [])
    cur = _t(*[_m(b, **full) for b in (4, 12, 20)], *[_m(b, amount=1, speed=-1) for b in (8, 16, 24)])
    free, _, _ = intent.changed_ranges(prev, cur, BARS, 40)
    assert free == [(4, 28)]
