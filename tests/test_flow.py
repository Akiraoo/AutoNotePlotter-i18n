import functools

import pytest

from automap import flow, nlmf


def _events(beats, doubles=(), bpm=120):
    tm = nlmf.TempoMap(bpm)
    return [flow.Event(b, tm.sec(b), 2 if b in doubles else 1) for b in beats]


def _swings_by_hand(notes):
    by = {0: [], 1: []}
    for n in sorted(notes, key=lambda n: n['beat']):
        by[n['c']].append(n)
    return by


def test_parity_alternates_and_stays_in_grid():
    beats = [i * 0.5 for i in range(64)]
    notes, _ = flow.generate(_events(beats, doubles={8.0, 16.0}), flow.Style(seed=3))
    assert len(notes) == 64 + 2
    for n in notes:
        assert 0 <= n['x'] <= 3 and 0 <= n['y'] <= 2 and 0 <= n['d'] <= 7
    for c, ns in _swings_by_hand(notes).items():
        pars = [flow.parity_of(c, n['d']) for n in ns]
        assert all(a != b for a, b in zip(pars, pars[1:])), f'手 {c} の振りの交互が崩れた'


def test_doubles_do_not_collide_or_cross():
    beats = [i for i in range(32)]
    notes, _ = flow.generate(_events(beats, doubles=set(beats)), flow.Style(seed=1))
    by_beat = {}
    for n in notes:
        by_beat.setdefault(n['beat'], {})[n['c']] = n
    for b, pair in by_beat.items():
        l, r = pair[0], pair[1]
        assert (l['x'], l['y']) != (r['x'], r['y'])
        assert l['x'] <= r['x']


def test_seed_is_deterministic_and_changes_result():
    ev = _events([i * 0.5 for i in range(48)])
    a, _ = flow.generate(ev, flow.Style(seed=5))
    b, _ = flow.generate(ev, flow.Style(seed=5))
    c, _ = flow.generate(ev, flow.Style(seed=6))
    assert a == b
    assert a != c


def test_noise_does_not_carry_over_from_earlier_hits():
    """揺らぎは候補ごとに（種・打点の拍・手・置き方）から決まる＝前の打点の数・候補の数によらない。
    前の打点だけが違う2つの並びで、決めた両手で状態をそろえた後ろは同じノーツになる（前は曲の頭からの1本の乱数の列で、
    前の候補の数が変わると後ろの揺らぎが全部ずれ、ここが 40 中 20〜38 違った）"""
    tm = nlmf.TempoMap(120)
    zero = {k: 0.0 for k in ('row', 'dir', 'center', 'still', 'alt', 'col')}

    def run(prefix, seed):
        evs = [flow.Event(b, tm.sec(b), 1) for b in prefix]
        for b, fx in ((24.0, {0: (1, 0, 1), 1: (2, 0, 1)}), (24.5, {0: (0, 1, 0), 1: (3, 1, 0)})):   # 振り下ろし→振り上げで両手の状態をそろえる
            e = flow.Event(b, tm.sec(b), 2)
            e.fix, e.fix_w = fx, 50.0
            evs.append(e)
        evs += [flow.Event(25 + i * 0.5, tm.sec(25 + i * 0.5), 1) for i in range(40)]
        notes, _ = flow.generate(evs, flow.Style(seed=seed, beam=32, w_target=zero))
        return [n for n in notes if n['beat'] >= 25]

    for seed in (1, 2):
        assert run([i * 0.5 for i in range(32)], seed) == run([i * 0.75 for i in range(25)], seed)
    assert run([i * 0.5 for i in range(32)], 1) != run([i * 0.5 for i in range(32)], 2)
    k1, k2 = flow._jitter_key(1, 25.0), flow._jitter_key(2, 25.0)
    v = [flow._jitter(k, 1, 0, 3, 0, 1) for k in (k1, k2)]
    assert all(0 <= x < 1 for x in v) and v[0] != v[1]


def test_targets_pull_rows_up():
    ev = _events([i * 0.5 for i in range(200)])
    low = flow.Style(seed=1)
    low.targets = dict(flow.LIBRARY_EPLUS, row=(0.9, 0.05, 0.05))
    high = flow.Style(seed=1)
    high.targets = dict(flow.LIBRARY_EPLUS, row=(0.3, 0.3, 0.4))
    top = lambda ns: sum(1 for n in ns if n['y'] == 2) / len(ns)
    assert top(flow.generate(ev, high)[0]) > top(flow.generate(ev, low)[0]) + 0.15


def test_fix_is_followed_and_looked_ahead():
    """決めたノーツ（Event.fix）: 両手とも振り上げから入る型を、両手が逆の向きにそろった流れの途中に置いても、
    先読みで前の振りを選び直して決めたとおりに置ける（振りの交互は崩さない）"""
    beats = [i * 0.5 for i in range(40)]
    evs = _events(beats, doubles={4.0})
    fix = {12.0: {0: (0, 1, 4)}, 12.5: {1: (3, 1, 0)}, 13.0: {0: (0, 1, 1)}, 13.5: {1: (3, 1, 1)}}
    for e in evs:
        e.fix = fix.get(e.beat)
    notes, _ = flow.generate(evs, flow.Style(seed=2))
    got = {n['beat']: (n['c'], n['x'], n['y'], n['d']) for n in notes if n['beat'] in fix}
    assert got == {b: (c, *v) for b, f in fix.items() for c, v in f.items()}
    for c, ns in _swings_by_hand(notes).items():
        pars = [flow.parity_of(c, n['d']) for n in ns]
        assert all(a != b for a, b in zip(pars, pars[1:]))


def _with_mods(mods, n=64, seed=4):
    beats = [i * 0.5 for i in range(n)]
    evs = _events(beats)
    for e in evs:
        e.mods = mods
    notes, _ = flow.generate(evs, flow.Style(seed=seed))
    return notes


def _move(notes):
    out = []
    for c, ns in _swings_by_hand(notes).items():
        out += [((a['x'] - b['x']) ** 2 + (a['y'] - b['y']) ** 2) ** 0.5 for a, b in zip(ns, ns[1:])]
    return sum(out) / len(out)


@functools.lru_cache(maxsize=None)
def _mods_notes(**mods):
    """_with_mods の控え（同じ指示の譜面を 1 つのテストの中・続くテストで作り直さない）。指示が無ければ mods＝None"""
    return _with_mods(mods or None)


def _mean(ns, f):
    return sum(1 for n in ns if f(n)) / len(ns)


# 置き方の指示ごと（並べて流せるように分けた）: 振りの交互を確かめる指示・狙った方向に変わるかの確かめ
_PLACE_MODS = {
    'width': ({'width': 1}, lambda m, base: _mean(m(width=-1), _OUTER) < _mean(base, _OUTER) < _mean(m(width=1), _OUTER)),
    'height': ({'height': 1}, lambda m, base: _mean(m(height=1), _TOP) > _mean(base, _TOP) >= _mean(m(height=-1), _TOP)),
    'diag': ({'diag': 1}, lambda m, base: _mean(m(diag=1), _DG) > _mean(base, _DG) > _mean(m(diag=-1), _DG)),
    'move': ({'move': 2}, lambda m, base: _move(m(move=2)) > _move(base) > _move(m(move=-1))),
    'turn': ({'turn': 1}, None),
    'bigmove': ({'bigmove': True}, None),
}
_OUTER = lambda n: n['x'] in (0, 3)   # noqa: E731
_TOP = lambda n: n['y'] == 2   # noqa: E731
_DG = lambda n: n['d'] in flow.DIAG   # noqa: E731


@pytest.mark.parametrize('kind', list(_PLACE_MODS))
def test_place_mods_move_the_shape(kind):
    """意思入れの置き方の指示（Event.mods）で、狙った方向に置き方が変わる（振りの交互は崩さない）"""
    mods, moved = _PLACE_MODS[kind]
    if moved:
        assert moved(_mods_notes, _mods_notes())
    for c, ns in _swings_by_hand(_mods_notes(**mods)).items():
        pars = [flow.parity_of(c, n['d']) for n in ns]
        assert all(a != b for a, b in zip(pars, pars[1:])), (mods, c)


def test_no_mods_is_unchanged():
    """mods が無い（None・空）時は、指示の無い時と同じノーツ"""
    assert _with_mods(None) == _with_mods({})


def _spread_events(mods=None):
    tm = nlmf.TempoMap(150)
    out = []
    for i in range(240):
        b = i * 0.5
        e = flow.Event(b, tm.sec(b), 2 if i % 16 == 0 else 1)
        e.mods = mods
        out.append(e)
    return out, tm


def _spread_style(wh, ww):
    st = flow.Style(seed=3, beam=32)
    st.targets = dict(flow.LIBRARY_EPLUS, hcol=(0.0, 0.18, 0.38, 0.44), wide=0.15)
    st.w_target = dict(st.w_target, hcol=wh, wide=ww)
    return st


def test_spread_targets_pull_hands_in():
    """両手の広がり（docs/方針.md 6.21）: 手から見た列（hcol）と両手を同時に外へ（wide）の重みを付けると、両手を同時に外へ
    （左手が列 0・右手が列 3 の組）が目標（15%）へ下がる（重み 0 だと Style の既定の列の減点で外に寄り 26%）"""
    from automap import stats
    ev, tm = _spread_events()
    plain = stats.note_spread(flow.generate(ev, _spread_style(0, 0))[0], tm.sec)
    pulled = stats.note_spread(flow.generate(ev, _spread_style(4, 8))[0], tm.sec)
    assert plain['wide'] > 0.22 and pulled['wide'] < 0.19 and pulled['wide'] < plain['wide'] - 0.06


def test_spread_targets_off_where_width_plus():
    """意思入れの「横の広がり +1」（mods の width > 0）の打点は、両手の広がりの割合を効かせない＝重み 0 と全く同じ答え"""
    ev, _ = _spread_events({'width': 1})
    ev2, _ = _spread_events({'width': 1})
    assert flow.generate(ev, _spread_style(4, 8))[0] == flow.generate(ev2, _spread_style(0, 0))[0]


def test_cell_target_spreads_cells():
    """手から見たマスの割合（docs/方針.md 6.22）: 重みを付けると、マスの割合が目標（targets の cell・無ければ flow.CELL0＝ランク譜面の
    ふつう）に近づく（目標からの離れ Σ|差| が縮む・作り物の並びでは反対の内の下の段が 3% → 12% など）"""
    from automap import stats
    ev, tm = _spread_events()
    st0, st1 = _spread_style(4, 8), _spread_style(4, 8)
    st1.w_target = dict(st1.w_target, cell=12.0)
    dist = lambda st: sum(abs(a - b) for a, b in zip(stats.summarize(flow.generate(ev, st)[0], tm)['cells'], flow.CELL0))
    assert dist(st1) < dist(st0) - 0.1


def test_cell_target_off_where_width_plus():
    """「横の広がり +1」の打点は手から見たマスの割合も効かせない＝重み 0 と全く同じ答え"""
    ev, _ = _spread_events({'width': 1})
    ev2, _ = _spread_events({'width': 1})
    st = _spread_style(4, 8)
    st.w_target = dict(st.w_target, cell=12.0)
    assert flow.generate(ev, st)[0] == flow.generate(ev2, _spread_style(0, 0))[0]


def test_fast_solo_goes_to_right_hand():
    """片手だけで速く続ける振りは右手に（w_left_fast・2026-11-03 利用者「難しい高速な配置は右手側に・右利きが基本」）: 片手・両手・片手が
    1/4 拍ずつの塊（BPM 80）で、両手の後の片手（＝両手の時の手がそのまま速く続ける）が左手になる回が減る。0 なら前と同じ"""
    tm = nlmf.TempoMap(80)
    ev, b = [], 0.0
    for _ in range(60):
        ev += [flow.Event(b, tm.sec(b), 1), flow.Event(b + 0.25, tm.sec(b + 0.25), 2), flow.Event(b + 0.5, tm.sec(b + 0.5), 1)]
        b += 2

    def left_after_double(w):
        st = flow.Style(seed=1, beam=32, w_same_hand=1.0)
        st.w_left_fast = w
        ns, _ = flow.generate(ev, st)
        hand = {n['beat']: n['c'] for n in ns if n['beat'] % 2 == 0.5}
        return sum(c == 0 for c in hand.values())
    assert left_after_double(0) >= 20 and left_after_double(1) <= 6


def test_hand_tech_goes_to_right_hand():
    """向きの曲がり・大きな移動も右手に（w_hand_tech＝角度・移動の減点を左手 1＋k・右手 1−k 倍・2026-11-03 利用者「それも右手側に」）:
    右手の曲がる振り（真逆から 45° 以上ずれる）が増え、左手は増えない"""
    import random
    tm = nlmf.TempoMap(150)
    rng = random.Random(3)
    b, ev = 0.0, []
    for _ in range(300):
        ev.append(flow.Event(b, tm.sec(b), 1))
        b += rng.choice([0.5, 0.5, 1.0, 0.25])

    def curves(k):
        st = flow.Style(seed=2, beam=32, w_same_hand=1.0)
        st.w_hand_tech = k
        ns, _ = flow.generate(ev, st)
        out = []
        for c in (0, 1):
            hs = [x for x in ns if x['c'] == c]
            out.append(sum((180 - flow.angle_between(a['d'], q['d'])) >= 45 for a, q in zip(hs, hs[1:]) if a['d'] != 8 and q['d'] != 8))
        return out
    (l0, r0), (l1, r1) = curves(0), curves(0.3)
    assert r1 > r0 + 10 and l1 <= l0 and r1 > l1 * 1.5
