"""前の譜面に寄せる（作り直しで指示を変えていない所を前の結果に弱く寄せる）・指示「そのまま残す」（docs/アプリ仕様.md 8 節の 9・11 節）"""
import json

from automap import flow, intent, nlmf, rhythm
from automap import __main__ as cli
from test_keep import DK, _proj
from test_versions import app  # noqa: F401  （写しの場所で server と versions をつなぐ）

EMPTY = {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}}
BARS = [0, 4, 8, 12, 16, 20, 24, 28]


def _t(*ranges, line=(), auto_rest=None):
    return {'ranges': [{'b0': a, 'b1': b, 'set': st} for a, b, st in ranges], 'line': list(line),
            'auto_rest': auto_rest or {'on': False, 'b': None}}


def test_same_table_changes_nothing():
    t = _t((8, 16, {'amount': 1}), (20, 24, {'motif': {'group': 'A'}}))
    assert intent.changed_ranges(t, json.loads(json.dumps(t)), BARS, 32) == ([], False, [])


def test_added_changed_and_removed_ranges_are_free_to_the_bar():
    """足した・変えた・消した区間が自由（小節の頭と終わりまで広げる）。指示の並び順は比べない・コメントだけの区間は比べない"""
    prev = _t((8, 16, {'amount': 1, 'hands': 1}), (24, 26, {'diag': 1}))
    cur = _t((8, 16, {'hands': 1, 'amount': 1}), (5, 6, {'width': -1}), (28, 30, {'comment': 'メモ'}))
    free, glob, why = intent.changed_ranges(prev, cur, BARS, 32)
    assert free == [(4, 8), (24, 28)] and not glob and why


def test_keep_counts_as_a_change():
    """「そのまま残す」を消した区間は自由に作り直す（消すと戻る）"""
    free, _, _ = intent.changed_ranges(_t((8, 12, {'keep': True})), EMPTY, BARS, 32)
    assert free == [(8, 12)]


def test_motif_group_spreads_to_all_its_ranges():
    """同じ振り: 変わった区間と重なるグループの区間は全部（写した先も）"""
    m = {'motif': {'group': 'A'}}
    prev = _t((0, 4, m), (16, 20, m))
    cur = _t((0, 4, m), (16, 20, m), (1, 2, {'diag': -1}))
    free, _, why = intent.changed_ranges(prev, cur, BARS, 32)
    assert free == [(0, 4), (16, 20)] and any('同じ振り' in w for w in why)


def test_line_change_frees_only_the_bars_whose_ratio_changed():
    prev = _t(line=[{'b': 0, 'k': 1.0}, {'b': 32, 'k': 1.0}])
    cur = _t(line=[{'b': 0, 'k': 1.0}, {'b': 15.99, 'k': 1.0}, {'b': 16, 'k': 1.3}, {'b': 32, 'k': 1.3}])
    free, glob, _ = intent.changed_ranges(prev, cur, BARS, 32)
    assert free == [(16, 32)] and not glob


def test_auto_rest_is_a_whole_song_setting():
    _, glob, _ = intent.changed_ranges(EMPTY, _t(auto_rest={'on': True, 'b': None}), BARS, 32)
    assert glob
    _, glob, _ = intent.changed_ranges(_t(auto_rest={'on': False, 'b': 8}), _t(auto_rest={'on': False, 'b': None}), BARS, 32)
    assert not glob   # 切ってある自動の休みの位置は比べない


def test_keep_ranges_and_report():
    it = _t((8, 12, {'keep': True}), (10, 16, {'keep': True, 'diag': 1}), (0, 4, {'amount': 1}))
    assert intent.keep_ranges(it) == [(8, 12), (10, 16)]
    assert 'keep' not in intent.NOT_YET


def test_keep_plan_keeps_the_previous_notes_in_the_range():
    """そのまま残す: 区間の中の作ったクリップの中身を残し（またぐ物は境目で分ける）、打点を作らない・新しいクリップを置かない。
    区間の外は作り直す。残したノーツは決めたノーツとして流れへ（kept_notes）・前の譜面に寄せる相手（prev_notes）は区間の外だけ"""
    p = _proj()
    note = lambda n: (nlmf._r(n['beat']), n['x'], n['y'], n['c'], n['d'])
    before = sorted(note(n) for n in nlmf.clip_notes(p, DK, include_muted=True))
    plan = cli._keep_plan(p, DK, False, 32, keep=[(10, 20)])
    assert sorted(s['beat'] for s in plan['remove']) == [0, 8, 16, 24]
    assert sorted((c['beat'], c['len']) for c in plan['split']) == [(10, 6), (16, 4)]
    assert (10, 20) in plan['blocked'] and (10, 20) in plan['exclude']
    assert sorted(n['beat'] for n in plan['kept_notes']) == list(range(10, 20)) and plan['keep_notes'] == 10
    assert sorted(n['beat'] for n in plan['prev_notes']) == [b for b in range(1, 32) if not 10 <= b < 20]
    new = [{'beat': b + 0.5, 'x': 0, 'y': 2, 'c': 0, 'd': 0} for b in (2, 22, 30)]
    nlmf.remove_clips(p, DK, plan['remove'])
    nlmf.put_clips(p, DK, cli._cover_clips(p, new, 32, exclude=plan['exclude']) + plan['split'], plan['lane'])
    after = sorted(note(n) for n in nlmf.clip_notes(p, DK, include_muted=True))
    assert [n for n in after if 10 <= n[0] < 20] == [n for n in before if 10 <= n[0] < 20]   # 区間の中は前の譜面のまま
    assert [n for n in after if not 10 <= n[0] < 20] == sorted(note(n) for n in new)
    assert {why for _, why in nlmf.classify(p, DK)[0]} == {'app'} and nlmf.coverage_holes(p, DK, 0, 32) == []
    # 消すと戻る: 次の作り直しでは分けたクリップも作ったまま＝作り直す
    plan2 = cli._keep_plan(p, DK, False, 32)
    assert not plan2['split'] and len(plan2['kept']) == 0


def test_keep_plan_with_only_and_keep():
    """選んだ区間だけ作り直す時も、区間の中の「そのまま残す」は残す（区間の外と重ねて1つの残す範囲に）"""
    plan = cli._keep_plan(_proj(), DK, False, 32, only=(8, 24), keep=[(12, 14)])
    assert sorted(s['beat'] for s, why in plan['kept'] if why == 'outside') == [0, 24]
    assert sorted((c['beat'], c['len']) for c in plan['split']) == [(12, 2)]
    assert sorted(n['beat'] for n in plan['prev_notes']) == [b for b in range(8, 24) if not 12 <= b < 14]


def _stream(n=24):
    hits, events = [], []
    for i in range(n):
        b = 1.0 + i
        hits.append(rhythm.Hit(b, 1, 0, 0, 'kick', 0.5))
        events.append(flow.Event(b, b * 0.5, 1))
    return hits, events


def test_prev_anchor_skips_free_spans_and_other_fixes():
    """前の結果の置き方に弱く寄せる: 自由に作る所（前後 margin 拍）・ほかの決めたノーツ・残したノーツは寄せない。同じ振りの打点は寄せる
    （1回目の計算を前の譜面に近づける・_fix_motifs が同じ振りの重みで決め直す）"""
    hits, events = _stream()
    at = {round(h.beat, 4): {i % 2: (1 + i % 2, 0, 1)} for i, h in enumerate(hits)}
    events[0].fix, events[0].fix_w = {0: (0, 0, 1)}, 4.0
    hits[1].motif = {'group': 'A'}
    hits[2].kept = True
    n = cli._prev_anchor(hits, events, at, [(10, 12)], 0.2, 2.0)
    anchored = [ev.beat for ev in events if getattr(ev, 'anchored', False)]
    assert n == len(anchored) and anchored == [2] + [b for b in range(4, 25) if not 8 <= b < 14]
    assert events[5].fix_w == 0.2 and events[0].fix_w == 4.0


def test_anchor_keeps_the_previous_placement():
    """寄せた打点の外で何も変えなければ、前の結果と同じ置き方に戻る（揺らぎ・ビームの違いがあっても）。自由な所だけ別の置き方になれる"""
    hits, events = _stream(32)
    prev, _ = flow.generate(events, flow.Style(seed=1))
    at = {}
    for nt in prev:
        at.setdefault(round(nt['beat'], 4), {})[nt['c']] = (nt['x'], nt['y'], nt['d'])
    hits2, events2 = _stream(32)
    cli._prev_anchor(hits2, events2, at, [(14, 16)], 0.2, 2.0)
    got, _ = flow.generate(events2, flow.Style(seed=3))   # 種を変えても（揺らぎが違っても）
    key = lambda ns: {(round(x['beat'], 4), x['c'], x['x'], x['y'], x['d']) for x in ns}
    same = {k for k in key(got) & key(prev)}
    outside = {k for k in key(prev) if not 12 <= k[0] < 18}
    assert len(same & outside) >= 0.9 * len(outside)


def test_compose_extra_passes_the_previous_table(app):  # noqa: F811
    """アプリの作り直し: 今の結果のファイルを作った版の作業ファイルを --prev-intent に。履歴が無い・全体の設定を変えた・画面で「寄せない」は
    --no-anchor（理由つき）。NLM で直した結果のファイルは、作ったままのクリップが重なる版を前の版とみる"""
    server, versions, p = app
    w = server.load_work(p)
    ex = versions.compose_extra(p, w)
    assert ex[0] == '--no-anchor' and '履歴' in ex[1]
    versions.snapshot(p, 'generate', work=json.dumps(w, ensure_ascii=False), report='', as_written=True, dedupe=False)
    ex = versions.compose_extra(p, dict(w, ranges=w['ranges'] + [{'b0': 20, 'b1': 24, 'set': {'diag': 1}}]))
    assert ex[0] == '--prev-intent'
    assert json.loads(open(ex[1], encoding='utf-8').read()) == server.intent_table(w)
    assert versions.compose_extra(p, dict(w, opts={'anchor': False}))[0] == '--no-anchor'
    ex = versions.compose_extra(p, dict(w, library={'sources': ['ranked']}))
    assert ex[0] == '--no-anchor' and 'ライブラリ' in ex[1]
    ex = versions.compose_extra(p, dict(w, auto_rest={'on': True, 'b': None}))
    assert ex[0] == '--no-anchor' and '自動の休み' in ex[1]
    proj = nlmf.load(p)   # NLM で1つのクリップを直して保存した
    s = next(s for s in nlmf.note_clips(proj['difficulties'][DK]) if s['beat'] == 8)
    s['content']['notes'][0][1] = (s['content']['notes'][0][1] + 1) % 4
    nlmf.save(proj, p)
    assert versions.compose_extra(p, w)[0] == '--prev-intent'
    assert versions.prev_version(p)[0]['kind'] == 'generate'


def test_prev_sync_matches_hits_and_fixes_parity():
    """寄せる所の打点を前の譜面にそろえる（前の譜面で抜いた打点を抜き・足した打点を足す）。自由な所の振りの数が前と奇数だけ違えば、
    自由な所の終わりの近くの弱い片手の打点を1つ抜く（前か後ろに寄せる打点が無い所は合わせない）"""
    hits, _ = _stream(24)                                   # 拍 1〜24
    at = {float(b): {b % 2: (1, 0, 1)} for b in range(1, 25) if b != 5}   # 前の譜面は拍 5 を抜いていた
    at[20.5] = {0: (1, 0, 1)}                               # 前の譜面は拍 20.5 を足していた
    hits = [h for h in hits if h.beat not in (11.0,)]       # 自由な所（10〜12・前後 2 拍）で打点が1つ減った＝奇数
    anc = {'at': at, 'free': [(10, 12)]}
    out = cli._prev_sync(hits, anc, {}, 2.0)
    bs = [h.beat for h in out]
    assert 5.0 not in bs and 20.5 in bs and anc['sync_cut'] == [5.0] and anc['sync_add'] == [20.5]
    assert len(anc['fix']) == 1 and anc['fix'][0][0] == '抜いた' and 8 <= anc['fix'][0][1] < 14
    n_new = sum(h.hands for h in out if 8 <= h.beat < 14)
    n_old = sum(len(f) for b, f in at.items() if 8 <= b < 14)
    assert (n_new - n_old) % 2 == 0
    anc2 = {'at': at, 'free': [(20, 26)]}                   # 後ろに寄せる打点が無い（曲の終わり）＝合わせない
    cli._prev_sync([h for h in _stream(24)[0] if h.beat != 22.0], anc2, {}, 2.0)
    assert anc2['fix'] == []
