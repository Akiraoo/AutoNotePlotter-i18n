"""難易度の展開（compose --derive-from・automap/derive.py・docs/アプリ仕様.md 17 節）の約束:
既定の量と型の範囲・下は基準の打点の部分集合（小節の頭・区間の頭・途切れの戻りは残す・同じ振りはどの回も同じ所を）・上は基準の打点を
全部残して足す・基準とほかの難易度は1つも変えない・2回続けて作ると同じ・派生の難易度で NLM で直したクリップは残る"""
import copy
import json
import re
import shutil
from pathlib import Path

import pytest

from automap import __main__ as cli
from automap import amount, derive, diffs, library_use, nlmf, rhythm, stats

pytestmark = pytest.mark.usefixtures('pinned_scale')
ROOT = Path(__file__).resolve().parent.parent
TEMPO = nlmf.TempoMap(120)   # 1拍 0.5 秒


def _hit(b, hands=1, s=0.5, sec_i=0):
    return rhythm.Hit(float(b), hands, sec_i, 0, 'kick', s)


def _stream(n_bars=16):
    """半拍ごとの打点・拍の頭の 1/4 拍後にも打点・4拍ごとに両手（区間は8小節ごと）"""
    hs = []
    for b in range(n_bars * 4):
        for off in (0.0, 0.25, 0.5):
            if off == 0.25 and b % 2:
                continue
            hs.append(_hit(b + off, 2 if (off == 0 and b % 4 == 2) else 1, 0.9 if off == 0 else 0.3, b // 32))
    return [h for h in hs if TEMPO.sec(h.beat) >= amount.T_MIN]


BARS = [float(b) for b in range(0, 64, 4)]


# ---- 既定の量と型の範囲（default_plan） ----

def test_default_plan_without_database(monkeypatch):
    monkeypatch.setattr(library_use, 'available', lambda path=None: (False, 'データベースが無い', {}))
    p = derive.default_plan('ExpertPlus', 'Expert', None)
    assert p['ratio'] == 0.9 and p['library'] == library_use.DEFAULT and 'データベース' in p['note'] and p['note'].startswith('量 0.9 倍（1段 10%・1段下）')
    assert 'データベース' in p['lib_note'] and '量' not in p['lib_note']
    assert derive.default_plan('Expert+', 'hardstandard.dat', None)['ratio'] == 0.8
    assert derive.default_plan('Expert', 'ExpertPlus', None)['ratio'] == 1.1
    p = derive.default_plan('ExpertPlus', 'Hard', None, 15)   # 刻みを変える（アプリの設定 expand_step_pct）
    assert p['ratio'] == 0.7 and p['note'].startswith('量 0.7 倍（1段 15%・2段下）')


def test_default_plan_shifts_the_band_and_adds_low_difficulties(monkeypatch):
    monkeypatch.setattr(library_use, 'available', lambda path=None: (True, '', {}))
    monkeypatch.setattr(derive, '_counts', lambda f: 100)
    p = derive.default_plan('ExpertPlus', 'Expert', None)   # 設定の無い曲＝新しい曲の既定（★〜8）を1段やさしく
    assert p['library']['stars'] == [0, 6] and p['library']['diffs'] == ['Expert', 'ExpertPlus']
    p = derive.default_plan('ExpertPlus', 'Hard', None)     # Hard の譜面の型が十分なら絞り込みの難易度に足す
    assert p['library']['stars'] == [0, 4] and p['library']['diffs'] == ['Hard', 'Expert', 'ExpertPlus']
    p = derive.default_plan('Expert', 'ExpertPlus', {'sources': ['ranked'], 'stars': [0, 8], 'diffs': ['Expert', 'ExpertPlus']})
    assert p['library']['stars'] == [6, 10]
    # Hard の型が少なければ Expert／Expert+ のまま・全部で少なければ★の上を曲の設定の方へ戻す
    monkeypatch.setattr(derive, '_counts', lambda f: 5 if f['diffs'] == ['Hard'] else (10 if f['stars'][1] < 6 else 60))
    p = derive.default_plan('ExpertPlus', 'Hard', {'sources': ['ranked'], 'stars': [0, 6], 'diffs': ['Expert', 'ExpertPlus']})
    assert p['library']['diffs'] == ['Expert', 'ExpertPlus'] and p['library']['stars'] == [0, 6]
    assert '戻す' in p['note']


# ---- 下の難易度（thin） ----

def test_thin_is_a_subset_with_the_ratio_and_keeps_heads():
    hs = _stream()
    for h in hs:
        if h.beat == 21.5:
            h.reentry = True   # 途切れの戻り
    out, info = derive.thin(hs, 0.6, BARS, 64, TEMPO, {}, 'ExpertPlus', 'Hard')
    base = {round(h.beat, 4) for h in hs}
    got = {round(h.beat, 4) for h in out}
    assert got <= base
    assert amount.measure(out, TEMPO) / amount.measure(hs, TEMPO) == pytest.approx(0.6, abs=0.03)
    assert all(b in got for b in BARS if b in base)                  # 小節の頭
    assert 21.5 in got                                               # 途切れの戻り
    assert min(h.beat for h in out if h.sec_i == 1) == min(h.beat for h in hs if h.sec_i == 1)   # 区間の頭
    q = lambda xs: sum(abs(h.beat % 1 - 0.25) < 1e-6 for h in xs)
    assert q(out) < q(hs) * 0.5                                      # 1/4 拍の打点から先に間引く
    d0 = sum(h.hands == 2 for h in hs) / len(hs)
    d1 = sum(h.hands == 2 for h in out) / len(out)
    assert d1 == pytest.approx(d0 * derive.human_rel('ExpertPlus', 'Hard', 'double'), abs=0.02)
    assert all(h.hands in (1, 2) for h in hs)                        # 元の打点は変えない（写しで間引く）
    assert info['del'] > 0 and info['conv'] > 0


def test_thin_removes_singles_right_next_to_doubles():
    hs = [_hit(b) for b in range(4, 40)] + [_hit(10.25), _hit(20.75)]
    for h in hs:
        if h.beat in (10, 21):
            h.hands = 2
    out, _ = derive.thin(hs, 0.95, BARS, 64, TEMPO, {}, 'ExpertPlus', 'Hard')   # 0.125 秒＜Hard の最短の間
    got = {h.beat for h in out}
    assert 10.25 not in got and 20.75 not in got


def test_thin_cuts_the_same_offsets_in_every_occurrence_of_a_motif():
    hs = _stream()
    for b0, occ in ((8.0, 0), (24.0, 1), (40.0, 2)):
        for h in hs:
            if b0 <= h.beat < b0 + 6:
                h.motif = {'group': 'g', 'key': 'g', 'variant': 'a', 'mode': 'same', 'idx': occ, 'b0': b0, 'occ': occ}
    out, _ = derive.thin(hs, 0.6, BARS, 64, TEMPO, {}, 'ExpertPlus', 'Hard')
    offs = [sorted(round(h.beat - b0, 4) for h in out if b0 <= h.beat < b0 + 6) for b0 in (8.0, 24.0, 40.0)]
    assert offs[0] == offs[1] == offs[2] and 0.0 in offs[0]
    assert len(offs[0]) < sum(1 for h in hs if 8 <= h.beat < 14)


def test_thin_nests_inside_the_difficulty_in_between():
    hs = _stream()
    up = {round(h.beat, 4) for h in hs if h.beat % 1 != 0.5}   # 間の難易度は半拍の裏が無い
    out, _ = derive.thin(hs, 0.7, BARS, 64, TEMPO, {}, 'ExpertPlus', 'Hard', (up, None))
    plain, _ = derive.thin(hs, 0.7, BARS, 64, TEMPO, {}, 'ExpertPlus', 'Hard')
    base = {round(h.beat, 4) for h in hs}
    got = {round(h.beat, 4) for h in out}
    fast = {b + 0.25 for b in range(2, 64, 4)}   # 両手のすぐ後（入れ子によらず消す）
    assert (base - got) & up <= fast                 # 間の難易度にある打点は消さない（両手のすぐ隣だけ）
    q = lambda xs: sum(abs(h.beat % 1 - 0.25) < 1e-6 for h in xs)
    assert q(out) > q(plain)                         # 入れ子が無ければ 1/4 拍から消す


# ---- 上の難易度（thicken） ----

def test_thicken_keeps_every_base_hit_and_adds_from_the_pool():
    hs = [_hit(b, 2 if b % 8 == 4 else 1) for b in range(4, 64)]
    ons = {'kick': [rhythm.Onset(b + 0.5, b + 0.5, 'kick', 0.6) for b in range(4, 64)],
           'snare': [rhythm.Onset(b + 0.25, b + 0.25, 'snare', 0.5) for b in range(4, 64, 2)]}
    secs = [rhythm.Section('サビ', 0.0, 64.0)]
    secs[0].phrases = [(0.0, 64.0)]
    out, info = derive.thicken(hs, 1.3, BARS, 64, TEMPO, ons, secs, 'Expert', 'ExpertPlus')
    got = sorted(round(h.beat, 4) for h in out)
    assert {round(h.beat, 4) for h in hs} <= set(got)
    assert amount.measure(out, TEMPO) / amount.measure(hs, TEMPO) == pytest.approx(1.3, abs=0.04)
    assert min(b - a for a, b in zip(got, got[1:])) >= 0.25 - 1e-6
    assert sum(h.hands == 2 for h in out) > sum(h.hands == 2 for h in hs) and info['add'] > 0


def test_thicken_reports_when_the_pool_runs_out():
    hs = [_hit(b) for b in range(4, 64)]
    secs = [rhythm.Section('サビ', 0.0, 64.0)]
    secs[0].phrases = [(0.0, 64.0)]
    out, info = derive.thicken(hs, 1.5, BARS, 64, TEMPO, {}, secs, 'Expert', 'ExpertPlus')
    assert len(out) == len(hs) and info['far'] and info['after'] < info['target']


def test_base_hits_take_marks_from_the_auto_hits():
    at = {4.0: {0: (1, 0, 1)}, 5.0: {0: (1, 0, 1), 1: (2, 0, 1)}, 5.75: {1: (2, 0, 1)}}
    a4, a5 = _hit(4.0), _hit(5.0)
    a4.reentry = True
    a5.mods = {'width': 1}
    m = {'group': 'g', 'key': 'g', 'variant': 'a', 'mode': 'same', 'idx': 0, 'b0': 4.0, 'occ': 0}
    a4.motif = a5.motif = m
    it = {'ranges': [{'b0': 4.0, 'b1': 8.0, 'set': {'motif': {'group': 'g'}}}]}
    secs = [rhythm.Section('サビ', 0.0, 64.0)]
    secs[0].phrases = [(0.0, 64.0)]
    out = derive.base_hits(at, [a4, a5], secs, {}, it)
    assert [h.hands for h in out] == [1, 2, 1]
    assert out[0].reentry and out[1].mods == {'width': 1} and out[2].mods == {'width': 1}   # 区間の指示は1拍以内の自動の打点から
    assert all(h.motif['b0'] == 4.0 for h in out)   # 同じ振りの印は区間で（5.75 は自動の打点に無いが区間の中）


# ---- 同じ音楽の区間（自動の同じ振り）を派生でもそろえる（2026-11-11） ----

def _secs():
    s = [rhythm.Section('サビ', 0.0, 64.0)]
    s[0].phrases = [(0.0, 64.0)]
    return s


def _grp(*occ, kinds=None):
    kinds = kinds or ['model'] + ['same'] * (len(occ) - 1)
    return {'name': '自動1', 'bars': 2, 'occ': [(float(a), float(a) + 8) for a in occ], 'kinds': kinds}


def test_check_groups_takes_only_the_occurrences_that_match_in_the_base():
    """基準で手本と打点・置き方が同じ回だけそろえる（左右反転の回は手を入れ替えて反転して比べる）"""
    at = {}
    for b0, mir, bad in ((8, False, False), (24, True, False), (40, False, True)):
        for i, o in enumerate((0, 1, 2, 3, 4, 5)):
            c, x, d = (i % 2, 1 + i % 2, 1 if i % 4 < 2 else 0)
            if mir:
                c, x, d = 1 - c, 3 - x, derive.MIRROR_D[d]
            if bad and i >= 3:
                x = (x + 2) % 4   # 後半の置き方が違う回
            at[float(b0 + o)] = {c: (x, 0, d)}
    used, dropped = derive.check_groups([_grp(8, 24, 40, kinds=['model', 'mirror', 'same'])], at)
    assert [g['occ'] for g in used] == [[(8.0, 16.0), (24.0, 32.0)]] and used[0]['kinds'] == ['model', 'mirror']
    assert dropped and dropped[0][:2] == ('自動1', 40.0) and dropped[0][2] == 1.0 and dropped[0][3] == 0.5


def test_thicken_adds_the_same_offsets_in_every_occurrence_of_a_group():
    """組の回にはどの回も同じ所（回の頭からの拍）に足し、回ごとに別々には足さない。音の立ち上がりが片方の回にしか無い所にも両方に足す"""
    hs = [_hit(b) for b in range(4, 64)]
    g = _grp(8, 40)
    derive.mark_groups(hs, [g])
    ons = {'kick': [rhythm.Onset(b + 0.5, b + 0.5, 'kick', 0.6) for b in range(4, 64) if not 40 <= b < 48 or b % 2]}
    out, info = derive.thicken(hs, 1.4, BARS, 64, TEMPO, ons, _secs(), 'Expert', 'ExpertPlus', groups=[g])
    offs = [sorted(round(h.beat - a, 4) for h in out if a <= h.beat < a + 8) for a in (8.0, 40.0)]
    assert offs[0] == offs[1] and len(offs[0]) > 8 and info['g_add'] > 0
    assert all(h.motif['b0'] == (8.0 if h.beat < 16 else 40.0) for h in out if (8 <= h.beat < 16 or 40 <= h.beat < 48))
    assert {round(h.beat, 4) for h in hs} <= {round(h.beat, 4) for h in out}


def test_unify_groups_makes_the_copies_follow_the_model():
    hs = [_hit(b) for b in range(4, 64)] + [_hit(41.5)]   # 写す側だけに余分な打点
    hs = [h for h in hs if h.beat != 44]                   # 写す側に手本の打点が無い所
    g = _grp(8, 40)
    derive.mark_groups(hs, [g])
    out, n_del, n_add = derive.unify_groups(hs, [g], TEMPO, _secs())
    offs = [sorted(round(h.beat - a, 4) for h in out if a <= h.beat < a + 8) for a in (8.0, 40.0)]
    assert offs[0] == offs[1] and (n_del, n_add) == (1, 1)


def test_keep_parity_restores_the_odd_even_of_singles_in_groups_and_between():
    """組の回の中・回と回の間の片手の打点の数の偶奇を足す前と同じに（どの回も同じ所を直す）"""
    before = [_hit(b) for b in range(4, 64)]
    g = _grp(8, 40)
    derive.mark_groups(before, [g])
    out = [copy.copy(h) for h in before]
    extra = [_hit(9.5), _hit(41.5), _hit(20.5), _hit(30.5), _hit(28.5)]
    derive.mark_groups(extra, [g])
    fixed, n = derive.keep_parity(out + extra, before, [g], TEMPO)
    odd = lambda xs, a, b: sum(1 for h in xs if a <= h.beat < b and h.hands == 1) % 2
    for a, b in ((8, 16), (40, 48), (16, 40)):
        assert odd(fixed, a, b) == odd(before, a, b)
    offs = [sorted(round(h.beat - a, 4) for h in fixed if a <= h.beat < a + 8) for a in (8.0, 40.0)]
    assert offs[0] == offs[1] and n == 2


def test_rep_groups_reads_the_base_report_and_falls_back_to_the_found_groups():
    md = '- 同じ音楽の区間（自動の同じ振り・docs/方針.md 6.31）: 自動1 2 小節: 拍 8（手本）→拍 24（左右反転）→拍 40（同じ）'
    gs, src = derive.rep_groups(md, None, BARS)
    assert src == '基準の報告' and gs[0]['occ'] == [(8.0, 16.0), (24.0, 32.0), (40.0, 48.0)] and gs[0]['kinds'] == ['model', 'mirror', 'same']
    gs, src = derive.rep_groups(None, [{'name': '自動1', 'bars': 2, 'occ': [(8.0, 16.0), (24.0, 32.0)], 'flip': 0}], BARS)
    assert '選び直した' in src and gs[0]['kinds'] == ['model', 'mirror']
    from automap import repeat
    line = repeat.report_line([dict(gs[0], kinds=['model', 'same'])])   # 回ごとの種類をそのまま書く（派生でそろえた組）
    assert [o['kind'] for o in repeat.parse_groups(line)[0]['occ']] == ['model', 'same']


def test_thin_cuts_the_same_offsets_in_every_occurrence_of_an_auto_group():
    hs = _stream()
    g = _grp(8, 40)
    derive.mark_groups(hs, [g])
    out, _ = derive.thin(hs, 0.6, BARS, 64, TEMPO, {}, 'ExpertPlus', 'Hard')
    offs = [sorted(round(h.beat - a, 4) for h in out if a <= h.beat < a + 8) for a in (8.0, 40.0)]
    assert offs[0] == offs[1] and len(offs[0]) < sum(1 for h in hs if 8 <= h.beat < 16)


# ---- 難易度の名前・コマンド ----

def test_diff_key_does_not_pick_expertplus_for_expert():
    p = {'difficulties': {'expertplusstandard.dat': {}, 'expertstandard.dat': {}}}
    assert nlmf.diff_key(p, 'Expert') == 'expertstandard.dat'
    assert nlmf.diff_key(p, 'ExpertPlus') == 'expertplusstandard.dat'
    with pytest.raises(KeyError):
        nlmf.diff_key({'difficulties': {'expertplusstandard.dat': {}}}, 'Expert')


def test_cli_takes_derive_and_refuses_mixed_options(monkeypatch):
    got = []
    monkeypatch.setattr(cli, 'cmd_compose', lambda a: got.append(a))
    cli.main(['compose', 'x.nlmf', '--stems', 'y', '--form', '--diff', 'Hard', '--derive-from', 'ExpertPlus', '--ratio', '0.6'])
    a = got[-1]
    assert (a.derive_from, a.diff, a.ratio, a.anchor_w) == ('ExpertPlus', 'Hard', 0.6, None)
    assert cli._derive_check(a)[2] == 0.6
    a.ratio = None
    assert cli._derive_check(a) == ('ExpertPlus', 'Hard', pytest.approx(0.8))   # 既定＝1段ごとに −10%
    for extra in (['--only', '4,8'], ['--prev-intent', 'p.json'], ['--variant', '2'], ['--rare'], ['--band', '+1']):
        cli.main(['compose', 'x.nlmf', '--stems', 'y', '--diff', 'Hard', '--derive-from', 'ExpertPlus', *extra])
        with pytest.raises(SystemExit):
            cli._derive_check(got[-1])
    cli.main(['compose', 'x.nlmf', '--stems', 'y', '--diff', 'ExpertPlus', '--derive-from', 'Expert+'])
    with pytest.raises(SystemExit):
        cli._derive_check(got[-1])


def _proj_with_base():
    from automap.new_project import _empty_diff
    p = {'format': 'nlmf', 'version': 2, 'bpm': 120, 'notesLanes': 2, 'difficulties': {'expertplusstandard.dat': _empty_diff('ExpertPlusStandard.dat')}}
    nlmf.put_clips(p, 'expertplusstandard.dat', [{'beat': 0, 'len': 8, 'label': '自動 A', 'notes': [
        {'beat': 4, 'x': 1, 'y': 0, 'c': 0, 'd': 1}]}], 1)
    return p


def test_derived_clips_go_to_the_lane_of_the_base_clips():
    p = _proj_with_base()
    diffs.ensure(p, 'Expert')
    plan = cli._keep_plan(p, 'expertstandard.dat', False, 8.0)
    assert plan['lane'] is None
    assert cli._derive_lane(p, 'expertplusstandard.dat', plan) == 1   # 基準の作ったクリップと同じ（レーンを足さない）


# ---- 作り直し（手元の曲がある時だけ・写しで） ----

SONG = 'こだま'


def _compose(out, it, target, base='ExpertPlus', extra=()):
    cli.main(['compose', str(out), '--stems', str(ROOT / 'cache' / SONG), '--form', '--style', '--intent', str(it), '--out', str(out),
              '--diff', target, '--derive-from', base, '--beam', '12', *extra])


@pytest.fixture
def song(tmp_path):
    src = ROOT / 'out' / f'{SONG}.intent-s1.nlmf'
    if not src.exists() or not (ROOT / 'cache' / SONG / 'onsets.json').exists() or not library_use.available()[0]:
        pytest.skip('手元の曲（out/こだま.intent-s1.nlmf・cache/こだま）か型のデータベースが無い')
    out = tmp_path / src.name
    shutil.copy2(src, out)
    it = tmp_path / 'intent.json'
    it.write_text(json.dumps({'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}}), encoding='utf-8')
    return out, it


def test_base_compose_marks_export_when_undecided(song, capsys):
    """基準の作り直しは、書き出す印をまだ誰も決めていなければ付ける（元のプロジェクトの印は空＝NLM で開くと基準が書き出されなかった・
    2026-11-03）。ほかの難易度の印は触らない"""
    out, it = song
    p = nlmf.load(out)
    for m in [((p.get('graph') or {}).get('out') or {}).get('diffs')] + [n.get('data', {}).get('diffs') for n in (p.get('infoGraph') or {}).get('nodes', {}).values() if n.get('t') == 'set']:
        if isinstance(m, dict):
            m.clear()
    nlmf.save(p, out)
    cli.main(['compose', str(out), '--stems', str(ROOT / 'cache' / SONG), '--form', '--style', '--intent', str(it), '--out', str(out), '--beam', '12'])
    q = nlmf.load(out)
    assert diffs.export_marks(q) == {'ExpertPlus': 1} and diffs.mark_of(q, 'Hard') is None
    assert '書き出す印: Expert+ に付けた' in capsys.readouterr().out


def test_derive_end_to_end(song, capsys):
    out, it = song
    before = nlmf.load(out)
    keep = {k: json.dumps(v, sort_keys=True) for k, v in before['difficulties'].items() if k != 'expertstandard.dat'}
    _compose(out, it, 'Expert')
    p1 = nlmf.load(out)
    assert {k: json.dumps(v, sort_keys=True) for k, v in p1['difficulties'].items() if k in keep} == keep   # 基準・ほかは1つも変えない
    assert p1.get('notesLanes') == before.get('notesLanes')                                                 # レーンを足さない
    assert diffs.export_marks(p1).get('Expert') == 1
    rp = diffs.report_path(out, 'Expert')
    assert rp.exists() and not diffs.report_path(out).exists()   # 基準の報告は書かない
    report = rp.read_text(encoding='utf-8')
    assert '## 派生（基準の譜面から）' in report
    tempo = nlmf.tempo_of(p1)
    bn = nlmf.clip_notes(p1, 'expertplusstandard.dat', include_muted=True)
    dn = nlmf.clip_notes(p1, 'expertstandard.dat', include_muted=True)
    # 下は基準の打点から。例外は同じ振りの入りで振りの向きをそろえるために足した打点（_motif_breath・報告の「入りの前に打点を足した」）だけ
    # （派生で自動の同じ振りの手本の入りも合わせる＝model_heads・2026-11-11。こだまは 11-11 の作り直しから拍 31＝自動2 の入りの前）
    m = re.search(r'^- 入りの前に打点を足した: 拍 (.+)$', report, re.M)
    breath = {round(float(b), 4) for b in m.group(1).split('・')} if m else set()
    extra = {round(b, 4) for b in set(derive.swings(dn, tempo)) - set(derive.swings(bn, tempo))}
    assert extra <= breath and len(breath) <= 3, (extra, breath)
    sm = stats.summarize(dn, tempo)
    assert sm['nlm_swing'] == 0 and sm['reset'] == 0
    assert sm['nps'] / stats.summarize(bn, tempo)['nps'] == pytest.approx(0.9, abs=0.03)   # 既定＝1段 −10%
    # 2回続けて作ると同じ
    d1 = json.dumps(p1['difficulties']['expertstandard.dat'], sort_keys=True)
    _compose(out, it, 'Expert')
    p2 = nlmf.load(out)
    assert json.dumps(p2['difficulties']['expertstandard.dat'], sort_keys=True) == d1
    # 派生の難易度で NLM で直したクリップは残る（中身を少し変える・id はそのまま）
    st = p2['difficulties']['expertstandard.dat']
    cl = next(s for s in st['sections'] if (s.get('content') or {}).get('notes'))
    cl['content']['notes'][0][1] = (cl['content']['notes'][0][1] + 1) % 4
    body = json.dumps(cl, sort_keys=True)
    nlmf.save(p2, out)
    _compose(out, it, 'Expert')
    p3 = nlmf.load(out)
    assert [json.dumps(s, sort_keys=True) for s in p3['difficulties']['expertstandard.dat']['sections'] if s.get('id') == cl['id']] == [body]
    assert {k: json.dumps(v, sort_keys=True) for k, v in p3['difficulties'].items() if k in keep} == keep
    assert '手で直した' in rp.read_text(encoding='utf-8')


def test_nest_pick_takes_the_nearest_to_the_derived():
    """入れ子の相手は基準との間で派生に一番近い難易度（前は基準に一番近い物を選んでいた）・一緒に作る派生も数える・下は今ある物だけ"""
    has = lambda *ds: {'difficulties': {diffs.key(d): {'sections': [{'beat': 0, 'len': 4, 'content': {'notes': [[1, 1, 0, 0, 1]]}}]} for d in ds}}
    p = has('ExpertPlus', 'Expert', 'Hard', 'Easy')
    assert derive.nest_pick(p, 'ExpertPlus', 'Normal') == ('Hard', 'Easy')
    assert derive.nest_pick(p, 'ExpertPlus', 'Hard') == ('Expert', 'Easy')
    assert derive.nest_pick(has('ExpertPlus'), 'ExpertPlus', 'Normal', {'Expert': 0.9, 'Hard': 0.8}) == ('Hard', None)
    assert derive.nest_pick(has('Normal', 'Hard'), 'Normal', 'ExpertPlus', {'Expert': 0.9}) == ('Expert', None)   # 上でも派生に近い物
    assert derive.nest_pick(has('ExpertPlus', 'Normal'), 'ExpertPlus', 'Hard', {'Normal': 0.7}) == (None, 'Normal')   # 下は一緒に作っても数えない


def test_derive_with_predicts_the_one_in_between(song):
    """並べて作る（--derive-with）: Hard を先に、間の Expert を見込んで作り、後で Expert を作っても Hard の打点はほぼ Expert の中（入れ子）"""
    out, it = song
    _compose(out, it, 'Hard', extra=['--ratio', '0.8', '--derive-with', 'Expert=0.9'])
    _compose(out, it, 'Expert', extra=['--ratio', '0.9'])
    p = nlmf.load(out)
    tm = nlmf.tempo_of(p)
    h = derive.swings(nlmf.clip_notes(p, 'hardstandard.dat', include_muted=True), tm)
    e = derive.swings(nlmf.clip_notes(p, 'expertstandard.dat', include_muted=True), tm)
    assert sum(b in e for b in h) / len(h) >= 0.97
    assert '見込んだ' in diffs.report_path(out, 'Hard').read_text(encoding='utf-8')
