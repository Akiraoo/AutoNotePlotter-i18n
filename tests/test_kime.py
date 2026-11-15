"""珍しい型を「決め」に（automap/kime.py）: 作り物の打点と 1回だけの並び（once）で、場所の選び方・手と振りの向きの合わせ方・
左右反転・入れない所・once が無い時は何もしない、を確かめる"""
from automap import flow, form, kime, nlmf, rhythm


def _item(seq, maps=5, freq='珍しい', hard='やさしい', gap=1.0, sec=0.5):
    return {'seq': [list(s) for s in seq], 'maps': maps, 'freq': freq, 'hard': {'class': hard}, 'gap': gap, 'sec': sec,
            'move': 1.0, 'diag': sum(1 for s in seq if s[2] in flow.DIAG) / len(seq)}


# 右手の形。F＝振り下ろしから・B＝振り上げから
F1 = [(3, 0, 1), (3, 2, 0), (2, 0, 1), (3, 1, 0)]
B1 = [(3, 2, 0), (2, 0, 1), (3, 1, 0), (3, 0, 1)]
F2 = [(2, 0, 7), (3, 1, 4), (3, 0, 1), (2, 2, 5)]
B2 = [(3, 1, 5), (3, 0, 6), (2, 2, 0), (3, 0, 7)]
LIB = {'once': [_item(s) for s in (F1, B1, F2, B2)]}


def _style():
    """compose（試作4）と同じ重み（目標の割合は使わない）"""
    return flow.Style(seed=1, beam=64, noise=0.05, col_cost=(1.5, 0.3, 0.05, 0.0), w_same_hand=1.0, min_gap=0.15, w_center=2.0,
                      w_target={k: 0.0 for k in ('row', 'dir', 'center', 'still', 'alt', 'col')})


def _song(n=64, split=18.0, names=('A', 'B'), gen=None, r_phase=flow.F):
    """片手の打点が 1/2 拍ごと・区間は split 拍で変わる。gen＝'flow'（流れの計算）か None（作り物: 左右交互・
    左手は振り下ろしから・右手は r_phase から、どちらの手も振りの向きは交互）"""
    tm = nlmf.TempoMap(120)
    beats = [2 + i * 0.5 for i in range(n)]
    hits = [rhythm.Hit(b, 1, 0 if b < split else 1, 0, 'vocal', 0.5) for b in beats]
    events = [flow.Event(b, tm.sec(b), 1) for b in beats]
    secs = [rhythm.Section(names[0], 0, split), rhythm.Section(names[1], split, beats[-1] + 2)]
    if gen == 'flow':
        g, _ = flow.generate(events, _style())
    else:
        g = []
        for i, b in enumerate(beats):
            c, k = (flow.LEFT, i // 2) if i % 2 == 0 else (flow.RIGHT, i // 2)
            q = (flow.F if k % 2 == 0 else flow.B) if c == flow.LEFT else (r_phase if k % 2 == 0 else 1 - r_phase)
            g.append({'beat': b, 'x': 1 if c == flow.LEFT else 2, 'y': 0, 'c': c, 'd': 1 if q == flow.F else 0})
    return hits, events, secs, g


def _hand_swings(gen, hand):
    return [n for n in sorted(gen, key=lambda n: n['beat']) if n['c'] == hand]


def test_no_once_does_nothing():
    hits, events, secs, gen = _song()
    assert kime.choose({}, hits, events, gen, secs) == []
    assert kime.choose({'once': []}, hits, events, gen, secs) == []
    assert kime.choose({'hands': [], 'pairs': []}, hits, events, gen, secs) == []   # cache/themes.json の形


def test_mirror_keeps_parity():
    for d in range(8):
        for c in (flow.LEFT, flow.RIGHT):
            assert flow.parity_of(c, d) == flow.parity_of(1 - c, flow.MIRROR_D[d])
    assert kime.hand_form(F1, flow.LEFT) == [(0, 0, 1), (0, 2, 0), (1, 0, 1), (0, 1, 0)]
    assert kime.hand_form(F2, flow.LEFT) == [(1, 0, 6), (0, 1, 5), (0, 0, 1), (1, 2, 4)]
    assert kime.hand_form(F1, flow.RIGHT) == F1


def test_places_from_breaks_blocks_and_phrases():
    secs = [rhythm.Section('A', 0, 16), rhythm.Section('A', 16, 32), rhythm.Section('B', 32, 48)]
    secs[0].phrases = [(0, 8), (8, 16)]
    blocks = [form.Block(0, 16, 0, 4, base='A', level=1), form.Block(16, 32, 4, 8, base='A', level=1),
              form.Block(32, 48, 8, 12, base='B', level=3)]
    mu = {'breaks': [{'beat': 24.0, 'len': 1.0, 'kind': 'all'}, {'beat': 40.0, 'len': 2.0, 'kind': 'drums'}]}
    hits = [rhythm.Hit(b, 1, 0, 0, 'vocal', 0.5) for b in (1, 2, 3)]
    hits[1].accent = True
    ps = {(p.beat, p.kind): p for p in kime.places(hits, secs, blocks, mu)}
    assert ps[(24.0, '途切れの前')].score == 3.0 and ps[(40.0, '途切れの前')].score == 2.5
    assert ps[(16.0, 'フレーズの終わり')].score == 1.0                 # 同じ記号の続き
    assert ps[(32.0, '区間の変わり目')].score == 2.5                   # 記号が変わって盛り上がる
    assert ps[(8.0, 'フレーズの終わり')].level == 1
    assert ps[(2.0, '山の音')].inclusive and ps[(3.0, '曲の終わり')].inclusive


def test_kime_before_boundary_matches_hand_and_parity():
    hits, events, secs, gen = _song(gen='flow')
    ks = kime.choose(LIB, hits, events, gen, secs)
    assert len(ks) == 1                                    # 16 秒の曲＝1 つまで
    k = ks[0]
    assert k.place.kind == '区間の変わり目' and k.place.beat == 18.0
    sw = _hand_swings(gen, k.hand)
    bs = [n['beat'] for n in sw]
    i = bs.index(k.beats[0])
    assert bs[i:i + 4] == k.beats                         # その手の続く 4 つの振り
    assert 18.0 - k.beats[-1] <= kime.NEAR and k.beats[-1] < 18.0
    assert flow.parity_of(k.hand, k.seq[0][2]) == flow.parity_of(k.hand, sw[i]['d'])   # 振りの向きが今の流れと合う
    assert k.seq == kime.hand_form([tuple(s) for s in k.item['seq']], k.hand)
    assert all(flow.parity_of(k.hand, a[2]) != flow.parity_of(k.hand, b[2]) for a, b in zip(k.seq, k.seq[1:]))


def test_flow_follows_the_kime():
    hits, events, secs, gen = _song(gen='flow')
    ks = kime.choose(LIB, hits, events, gen, secs)
    kime.apply(ks, events)
    assert all(events[i].fix == {k.hand: tuple(c)} and events[i].fix_w == kime.KIME_W for k in ks for i, c in zip(k.idx, k.seq))
    gen2, _ = flow.generate(events, _style())
    assert kime.check(ks, gen2) == (4, 4) and ks[0].placed == 4
    for c in (0, 1):   # 振りの交互は崩れない
        ps = [flow.parity_of(c, n['d']) for n in _hand_swings(gen2, c)]
        assert all(a != b for a, b in zip(ps, ps[1:]))


def test_anchor_keeps_the_rest_unchanged():
    """決めの所の外は 1回目の結果に弱く留める＝計算し直しても、違いは決めの前後だけ"""
    hits, events, secs, gen = _song(n=160, gen='flow')
    ks = kime.choose(LIB, hits, events, gen, secs)
    assert ks
    hits[0].motif = {'group': 'g', 'key': 'g', 'occ': 0, 'b0': 2.0}
    kime.apply(ks, events)
    n = kime.anchor(ks, events, gen, hits)
    spans = [(k.beats[0] - kime.ANCHOR_MARGIN, k.beats[-1] + kime.ANCHOR_MARGIN) for k in ks]
    inside = lambda b: any(a - 1e-6 <= b <= e + 1e-6 for a, e in spans)
    assert events[0].fix is None                                   # 同じ振りの打点は留めない
    assert n == sum(1 for e in events[1:] if not inside(e.beat))
    assert all(e.fix_w == kime.ANCHOR_W for e in events[1:] if not inside(e.beat))
    gen2, _ = flow.generate(events, _style())
    assert kime.check(ks, gen2)[0] == 4 * len(ks)
    key = lambda g: {(n['beat'], n['c'], n['x'], n['y'], n['d']) for n in g if not inside(n['beat']) and n['beat'] > 2.0}
    assert key(gen2) == key(gen)


def test_kept_shapes_count_as_used():
    """選んだ区間だけ作り直す時: 外（残したノーツ）にある型は、もう使った型として数える"""
    hits, events, secs, gen = _song(r_phase=flow.B)
    assert kime.choose({'once': [_item(F1)]}, hits, events, gen, secs)
    right = [i for i, h in enumerate(hits) if 28 <= h.beat < 32 and i % 2 == 1]
    for i, cell in zip(right, F1):
        hits[i].kept, hits[i].fix = True, {flow.RIGHT: cell}
    assert kime.choose({'once': [_item(F1)]}, hits, events, gen, secs) == []


def test_hand_and_parity_choose_the_shape():
    """左手は振り下ろしから・右手は振り上げから入る所: 振り下ろしから入る型だけなら左手に左右反転して使い、
    振り上げから入る型だけなら右手にそのまま使う（合わない型は使わない）"""
    hits, events, secs, gen = _song(r_phase=flow.B)
    lw = [n for n in _hand_swings(gen, flow.LEFT) if n['beat'] < 18][-4:]
    rw = [n for n in _hand_swings(gen, flow.RIGHT) if n['beat'] < 18][-4:]
    assert flow.parity_of(flow.LEFT, lw[0]['d']) == flow.F and flow.parity_of(flow.RIGHT, rw[0]['d']) == flow.B
    ks = kime.choose({'once': [_item(F1)]}, hits, events, gen, secs)
    assert len(ks) == 1 and ks[0].hand == flow.LEFT and ks[0].place.beat == 18.0
    assert ks[0].beats == [n['beat'] for n in lw] and ks[0].seq == kime.mirror(F1)
    ks = kime.choose({'once': [_item(B1)]}, hits, events, gen, secs)
    assert len(ks) == 1 and ks[0].hand == flow.RIGHT and ks[0].seq == B1
    assert ks[0].beats == [n['beat'] for n in rw]


def test_rare_first_then_common_and_speed():
    hits, events, secs, gen = _song(r_phase=flow.B)
    lib = {'once': [_item(F1, freq='よくある', maps=40), _item(F2, freq='珍しい')]}
    ks = kime.choose(lib, hits, events, gen, secs)
    assert ks and ks[0].item['freq'] == '珍しい'
    ks = kime.choose({'once': [_item(F1, freq='よくある')]}, hits, events, gen, secs)
    assert ks and ks[0].item['freq'] == 'よくある'                   # 珍しいが無ければよくある
    assert kime.choose({'once': [_item(F1, freq='定番')]}, hits, events, gen, secs) == []
    assert kime.choose({'once': [_item(F1, sec=0.2, gap=0.4)]}, hits, events, gen, secs) == []   # 打点の間が合わない


def test_not_near_motif_kept_or_outside_only():
    hits, events, secs, gen = _song()
    for h in hits:   # 区間の変わり目の前は同じ振り
        if 12 <= h.beat < 18:
            h.motif = {'group': 'g', 'key': 'g', 'occ': 1, 'b0': 12.0}
    ks = kime.choose(LIB, hits, events, gen, secs)
    assert ks and all(k.place.kind != '区間の変わり目' for k in ks)
    assert all(not (k.beats[0] - kime.MOTIF_MARGIN <= b <= k.beats[-1] + kime.MOTIF_MARGIN) for k in ks for b in range(12, 18))

    hits, events, secs, gen = _song()
    for h, e in zip(hits, events):   # 残したノーツ（NLM で直した所）
        if 16 <= h.beat < 18:
            h.kept = True
            e.fix, e.fix_w = {0: (0, 0, 1)}, 20.0
    ks = kime.choose(LIB, hits, events, gen, secs)
    assert all(k.beats[-1] < 16 - kime.KEPT_MARGIN or k.beats[0] > 18 + kime.KEPT_MARGIN for k in ks)

    hits, events, secs, gen = _song()
    assert kime.choose(LIB, hits, events, gen, secs, allow=(0.0, 10.0)) == []
    ks = kime.choose(LIB, hits, events, gen, secs, allow=(26.0, 40.0))
    assert ks and all(26 <= b < 40 for k in ks for b in k.beats)


def test_variant_range_weakens_and_mods_filter():
    hits, events, secs, gen = _song()
    ks = kime.choose(LIB, hits, events, gen, secs, vranges=[(10.0, 18.0, 2, '意思入れ')])
    assert ks and ks[0].place.kind == '曲の終わり'          # 案 k の区間の場所は点が半分＝曲の終わりが先
    hits, events, secs, gen = _song()
    for h in hits:
        h.mods = {'height': -1}
    assert kime.choose(LIB, hits, events, gen, secs) == []    # 型が全部上の段を使う＝上の段を減らす指示に逆らう
    low = [(3, 0, 1), (3, 1, 0), (2, 0, 1), (3, 1, 4)]
    ks = kime.choose({'once': LIB['once'] + [_item(low)]}, hits, events, gen, secs)
    assert ks and all(k.seq == kime.hand_form(low, k.hand) for k in ks)


def test_center_and_cross_shapes_are_not_used():
    hits, events, secs, gen = _song(r_phase=flow.B)
    center = [(3, 0, 1), (2, 1, 0), (3, 0, 1), (3, 2, 0)]
    cross = [(0, 0, 1), (3, 2, 0), (2, 0, 1), (3, 1, 0)]
    assert kime.choose({'once': [_item(center), _item(cross)]}, hits, events, gen, secs) == []


def test_one_pattern_once_and_spread():
    """長い曲: 同じ型は 1 回だけ・30 秒に 1 つまで・決めどうしは離す"""
    tm = nlmf.TempoMap(120)
    beats = [2 + i * 0.5 for i in range(480)]   # 2 分
    hits = [rhythm.Hit(b, 1, int((b - 2) // 32), 0, 'vocal', 0.5) for b in beats]
    events = [flow.Event(b, tm.sec(b), 1) for b in beats]
    secs = [rhythm.Section('AB'[k % 2], 2 + 32 * k, 2 + 32 * (k + 1)) for k in range(8)]
    gen, _ = flow.generate(events, _style())
    ks = kime.choose(LIB, hits, events, gen, secs)
    assert 1 <= len(ks) <= 4
    keys = [tuple(map(tuple, k.item['seq'])) for k in ks]
    assert len(set(keys)) == len(keys)
    for a, b in zip(ks, ks[1:]):
        assert b.beats[0] - a.beats[-1] >= kime.MIN_APART


def test_want_and_avoid_ranges():
    """決めの区間の指示: 入れる区間には（数の上限の外で）1 つ・区間の頭の区切り（その前の振りで終える）は上げない。入れない区間には入れない"""
    hits, events, secs, gen = _song(n=160, gen='flow')
    ks0 = kime.choose(LIB, hits, events, gen, secs)
    ps = {(p.beat, p.kind): p for p in kime.places(hits, secs, want=[(18.0, 40.0)])}
    assert ps[(18.0, '区間の変わり目')].score == kime.SCORE['区間の変わり目']   # 区間の頭の区切りは区間の外（直前の振り）
    assert (40.0, '指示した区間') in ps and (22.0, '指示した区間') in ps
    ks = kime.choose(LIB, hits, events, gen, secs, want=[(50.0, 70.0)])
    got = [k for k in ks if 50.0 <= k.beats[0] and k.beats[-1] <= 70.0]
    assert len(got) == 1 and len(ks) == len(ks0) + 1      # 入れる区間に 1 つ（ほかはそのまま）
    ks = kime.choose(LIB, hits, events, gen, secs, avoid=[(10.0, 20.0)])
    assert ks0 and all(k.beats[-1] < 10.0 or k.beats[0] >= 20.0 for k in ks)
    assert not any(10.0 <= k.beats[-1] and k.beats[0] < 20.0 for k in ks)
    both = kime.choose(LIB, hits, events, gen, secs, want=[(50.0, 70.0)], avoid=[(50.0, 70.0)])   # 入れないが勝つ
    assert not any(50.0 <= k.beats[-1] and k.beats[0] < 70.0 for k in both)


# ---- 前の版から引き継ぐ（compose --prev-intent＝前の譜面に寄せる時・docs/アプリ仕様.md 12 節） ----

def _report(ks, only=None, carry_rows=None):
    """作り直しの報告と同じ書き方の決めの節（__main__._kime_lines・区間だけ作り直した時は CARRY_HEAD の節も）"""
    from types import SimpleNamespace
    from automap import __main__ as cli
    secs = [SimpleNamespace(name='AB'[i % 2], nth=i // 2) for i in range(5)]
    head = [f'- **選んだ区間（拍 {only[0]:g}〜{only[1]:g}）だけ作り直した**。外は結果のファイルの今の譜面のまま'] if only else []
    md = ['# 報告', '', *head, '', kime.REPORT_HEAD, '',
          *cli._kime_lines(ks, secs, SimpleNamespace(sec=lambda b: b * 0.5), {'graph': {'song': {'offset': 0.0}}})]
    if carry_rows is not None:
        md += ['', kime.CARRY_HEAD, '', f'- {len(carry_rows)}', '', *(cli._kime_head() + [cli._kime_row(r) for r in carry_rows] if carry_rows else [])]
    return '\n'.join(md + ['', '## 意思入れ', '', '| 1〜2 | x |'])


def _quick():
    st = _style()
    st.beam = 24   # 速く（テストの時間）
    return st


def _long(run=True):
    """65 秒の曲（決めが 2 つ入る）→ hits, events, secs, 1回目の計算（run＝False なら None）"""
    tm = nlmf.TempoMap(120)
    beats = [2 + i * 0.5 for i in range(260)]
    hits = [rhythm.Hit(b, 1, int((b - 2) // 32), 0, 'vocal', 0.5) for b in beats]
    events = [flow.Event(b, tm.sec(b), 1) for b in beats]
    secs = [rhythm.Section('AB'[k % 2], 2 + 32 * k, 2 + 32 * (k + 1)) for k in range(5)]
    return hits, events, secs, flow.generate(events, _quick())[0] if run else None


_PREV = []


def _prev_version():
    """前の版: 1回目の計算から決めを選び、計算し直した譜面とその報告（1回だけ作って使い回す）"""
    if not _PREV:
        hits, events, secs, gen = _long()
        ks = kime.choose(LIB, hits, events, gen, secs)
        kime.apply(ks, events)
        kime.anchor(ks, events, gen, hits)
        gen2, _ = flow.generate(events, _quick())
        kime.check(ks, gen2)
        _PREV.append((ks, gen2, _report(ks)))
    return _PREV[0]


def _remake(prev_gen):
    """作り直し: 打点を前の譜面に弱く寄せて（compose の _prev_anchor）1回目の計算 → hits, events, secs, 1回目の計算, 前の譜面の置き方"""
    hits, events, secs, _ = _long(run=False)
    at = kime._at(prev_gen)
    for ev in events:
        ev.fix, ev.fix_w, ev.anchored = dict(at[round(ev.beat, 4)]), kime.ANCHOR_W, True
    gen1, _ = flow.generate(events, _quick())
    return hits, events, secs, gen1, at


def test_report_table_roundtrip_and_prev_kimes():
    from automap import __main__ as cli
    ks, _, md = _prev_version()
    assert len(ks) >= 2
    rows = kime.prev_kimes(md)
    assert [(r['hand'], r['b0'], r['b1'], [tuple(s) for s in r['seq']], r['placed']) for r in rows] == \
        [(k.hand, k.beats[0], k.beats[-1], [tuple(c) for c in k.seq], k.placed) for k in ks]
    for r in rows:                                                   # 表の1行は書いて読むと同じ
        assert kime.parse_row([c.strip() for c in cli._kime_row(r).strip('|').split('|')]) == r
    assert kime.prev_kimes('# 報告\n\n- 打点 10\n') is None                       # 決めの節が無い＝分からない
    assert kime.prev_kimes('\n'.join([kime.REPORT_HEAD, '', '- 切った（--no-kime）'])) is None
    part = _report(ks[:1], only=(0, 40))
    assert kime.prev_kimes(part) is None                                          # 区間だけ作り直した前の形の報告＝外が分からない
    got = kime.prev_kimes(_report(ks[:1], only=(0, 40), carry_rows=rows[1:]))     # 外の決めは CARRY_HEAD の節から
    assert [(r['b0'], r['hand']) for r in got] == [(r['b0'], r['hand']) for r in rows]
    assert kime.prev_kimes(_report(ks[:1], only=(0, 40), carry_rows=[])) == rows[:1]   # 外に決めが無い（節はある）
    assert kime.parse_report(_report(ks[:1], only=(0, 40), carry_rows=rows[1:]))[1] == rows[:1]   # app の読み方は表だけ（重ならない）


def test_carry_keeps_unchanged_kimes_and_answer():
    """指示を変えずに作り直す: 前の版の決めを同じ場所・同じ型で使い、計算し直した譜面は前の版と同じ"""
    ks, prev_gen, md = _prev_version()
    hits, events, secs, gen1, at = _remake(prev_gen)
    carried, drop = kime.carry(kime.prev_kimes(md), LIB, hits, events, gen1, at, free=[])
    assert not drop and [(k.hand, k.beats, k.seq) for k in carried] == [(k.hand, k.beats, [tuple(c) for c in k.seq]) for k in ks]
    assert all(k.carried and k.item in LIB['once'] for k in carried)
    got = kime.choose(LIB, hits, events, gen1, secs, keep=carried, inside=[])     # 新しく選ばない
    assert got == carried
    kime.apply(got, events)
    kime.anchor(got, events, gen1, hits)
    gen2, _ = flow.generate(events, _quick())
    key = lambda g: {(n['beat'], n['c'], n['x'], n['y'], n['d']) for n in g}
    assert kime.check(got, gen2)[0] == sum(k.placed for k in ks) and key(gen2) == key(prev_gen)


def test_carry_changed_range_reselects_only_there():
    """指示が変わった所の決めは選び直す（そこだけ）・ほかは前の版のまま・NLM で直された決めは使わない"""
    ks, prev_gen, md = _prev_version()
    prev = kime.prev_kimes(md)
    hits, events, secs, gen1, at = _remake(prev_gen)
    k0 = ks[0]
    free = [(k0.beats[0] - 2, k0.beats[-1] + 2)]
    for ev in events:   # 変わった所（と前後）は寄せない（compose の _prev_anchor と同じ）
        if free[0][0] - kime.ANCHOR_MARGIN <= ev.beat < free[0][1] + kime.ANCHOR_MARGIN:
            ev.fix, ev.fix_w, ev.anchored = None, None, False
    carried, drop = kime.carry(prev, LIB, hits, events, gen1, at, free=free)
    assert [why for _, why in drop] == ['指示が変わった所'] and len(carried) == len(ks) - 1
    inside = [(free[0][0] - kime.ANCHOR_MARGIN, free[0][1] + kime.ANCHOR_MARGIN)]
    got = kime.choose(LIB, hits, events, gen1, secs, keep=carried, inside=inside)
    new = [k for k in got if not k.carried]
    assert all(k in got for k in carried) and len(new) <= 1
    assert all(inside[0][0] <= k.beats[0] and k.beats[-1] <= inside[0][1] for k in new)
    used = {tuple(kime.hand_form(k.seq, k.hand)) for k in carried}
    assert all(tuple(kime.hand_form(k.seq, k.hand)) not in used for k in new)   # 引き継いだ型はもう使わない
    at2 = {b: dict(f) for b, f in at.items()}                       # 前の譜面の 2 つ目の決めを NLM で直した
    k1 = ks[1]
    x, y, d = at2[round(k1.beats[1], 4)][k1.hand]
    at2[round(k1.beats[1], 4)][k1.hand] = ((x + 1) % 4, y, d)
    _, drop2 = kime.carry(prev, LIB, hits, events, gen1, at2, free=free)
    assert ('前の譜面で型どおりでない' in [why for r, why in drop2 if r['b0'] == k1.beats[0]])
    _, drop3 = kime.carry(prev, LIB, hits, events, gen1, at, free=[], avoid=[(k1.beats[0], k1.beats[0] + 1)])
    assert [(r['b0'], why) for r, why in drop3] == [(k1.beats[0], '入れない区間')]


def test_kept_kimes_listed_for_partial_reports():
    """区間だけ作り直した報告に書く「残したノーツの中の決め」: 作り直さなかった所にあって、譜面にまだある物"""
    from automap import __main__ as cli
    ks, prev_gen, md = _prev_version()
    prev = kime.prev_kimes(md)
    k0, k1 = ks[0], ks[1]
    spans = [(-1e9, k1.beats[0] - 1)]                                 # k0 は残したノーツの中・k1 は作り直した所
    assert [r['b0'] for r in cli._kept_kimes(prev, [], spans, prev_gen)] == [k0.beats[0]]
    assert cli._kept_kimes(prev, [k0], spans, prev_gen) == []         # 今の決めと同じ物は除く
    gone = [n for n in prev_gen if not (n['c'] == k0.hand and n['beat'] == k0.beats[0])]
    assert cli._kept_kimes(prev, [], spans, gone) == []               # 譜面から消えた（NLM で直した）
