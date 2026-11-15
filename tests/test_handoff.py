"""左右の受け渡し（automap/handoff.py・docs/方針.md 6.29）"""
from automap import flow, handoff
from automap.flow import LEFT, RIGHT


def _stream(n=48, step=0.5, spb=0.5):
    """一定の間合いの片手の打点（120 BPM の半拍＝0.25 秒）"""
    return [flow.Event(4 + k * step, (4 + k * step) * spb, 1) for k in range(n)]


def _runs(notes, b0, b1):
    return [n['c'] for n in sorted(notes, key=lambda n: n['beat']) if b0 - 1e-6 <= n['beat'] < b1 - 1e-6]


def test_plan_marks_two_by_two_runs_at_the_target_rate():
    ev = _stream(200)
    pl = handoff.plan(ev, seed=1, rate=3.5)
    assert pl['target'] == round(3.5 / 100 * 200) and pl['n'] >= pl['target']
    for b0, m, lead, mir in pl['chains']:
        i = next(j for j, e in enumerate(ev) if abs(e.beat - b0) < 1e-9)
        if mir:   # 反転: 1 打点多く押さえて手は決めない
            assert all(ev[j].hoflex == (b0, m) and ev[j].want is None for j in range(i, i + 2 * m + 1))
        else:     # 2 振りずつ手が交代する
            assert [ev[j].want for j in range(i, i + 2 * m)] == [lead if (k // 2) % 2 == 0 else 1 - lead for k in range(2 * m)]
    again = _stream(200)
    assert handoff.plan(again, seed=1, rate=3.5)['chains'] == pl['chains']   # 種と拍で決まる


def test_plan_skips_fixed_fast_and_double_events():
    ev = _stream(40, step=0.25, spb=0.5)   # 1/4 拍＝0.125 秒: 同じ手の 1→2 振り目には速すぎる
    assert handoff.plan(ev, rate=50)['chains'] == []
    ev = _stream(40)
    for e in ev:
        e.fix = {RIGHT: (2, 0, 1)}
    assert handoff.plan(ev, rate=50)['chains'] == []


def test_flow_follows_the_wanted_hands():
    ev = _stream(32)
    for j, h in zip(range(8, 16), [RIGHT, RIGHT, LEFT, LEFT, RIGHT, RIGHT, LEFT, LEFT]):
        ev[j].want, ev[j].ho = h, 0
    notes, _ = flow.generate(ev, flow.Style(seed=1, w_same_hand=1.0))
    assert _runs(notes, ev[8].beat, ev[16].beat) == [RIGHT, RIGHT, LEFT, LEFT, RIGHT, RIGHT, LEFT, LEFT]
    ok, tot, *_ = handoff.check(ev, notes)
    assert ok == tot == 8


def test_flex_mirror_wherever_it_starts():
    """反転の受け渡しは、始まりの前に両手の振りの向きがそろう道なら頭から、そろわない道なら 1 打点後ろから＝どこに置いても反転になる"""
    for start in (8, 9, 10, 11):
        ev = _stream(36)
        for j in range(start, start + 5):
            ev[j].hoflex, ev[j].ho = (ev[start].beat, 2), 0
        notes, _ = flow.generate(ev, flow.Style(seed=1, w_same_hand=1.0))
        *_, mok, mtot, miss = handoff.check(ev, notes)
        assert (mok, mtot, miss) == (1, 1, []), start


def test_carry_keeps_previous_same_hand_runs_and_mirrors():
    ev = _stream(12)
    prev = [(RIGHT, (2, 0, 1)), (RIGHT, (3, 1, 0)), (LEFT, (1, 0, 1)), (LEFT, (0, 1, 0))] * 3
    for e, (h, p) in zip(ev, prev):
        e.fix, e.fix_w, e.anchored = {h: p}, 0.2, True
    n = handoff.carry(ev)
    assert n == 12 and [e.want for e in ev] == [h for h, _ in prev]
    assert all(e.fix_w == handoff.CARRY_MIR_W for e in ev)   # 後ろが前の左右反転＝置き方も強めに寄せる
    ev2 = _stream(12)
    for e, (h, p) in zip(ev2, prev):
        e.fix, e.fix_w, e.anchored = {h: p}, 0.2, True
    pl = handoff.plan(ev2, rate=50)
    assert pl['chains'] == [] and pl['carried'] == 12   # 寄せる打点には新しく計画しない


def test_stats_counts_handoffs_and_mirrors():
    seq = [(RIGHT, 2, 0, 6), (RIGHT, 3, 1, 5), (LEFT, 1, 0, 7), (LEFT, 0, 1, 4),   # 右 ↙ ↗ → 左 ↘ ↖（左右反転）
           (RIGHT, 2, 0, 1), (LEFT, 1, 0, 1), (RIGHT, 2, 1, 0), (LEFT, 1, 1, 0)]   # 交互
    notes = [{'beat': 1 + k * 0.5, 'c': c, 'x': x, 'y': y, 'd': d} for k, (c, x, y, d) in enumerate(seq)]
    s = handoff.stats(notes)
    assert s['ho'] == 1 and s['mir'] == 1 and s['singles'] == 8
    assert abs(s['same'] - 2 / 7) < 1e-9
