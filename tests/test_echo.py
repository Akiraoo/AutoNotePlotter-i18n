"""続けて左右反転（automap/echo.py・docs/方針.md 6.33）"""
from automap import echo, flow, rhythm


def _mu(n):
    return {'bars': [4.0 * i for i in range(n)], 'lab': {'acc': list(range(n)), 'mel': list(range(n)), 'drum': [0] * n}}


def _hits(pats, s=0.5):
    """小節ごとの打点の位置（拍）→ 打点"""
    return [rhythm.Hit(4.0 * i + off, 1, 0, 0, 'vocal', s) for i, pat in enumerate(pats) for off in pat]


def _free(_):
    return True


def test_the_shortest_repeating_set_is_chosen():
    # 2 拍ごとに同じリズム → 2 拍のセット（4 つ続けて 2 小節）
    hs = _hits([(0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5)] * 4)
    assert echo._chains(hs, _mu(4), _free, echo.UNIFY_DIFF)[0] == (0.0, 2.0, 4)
    # 小節の前と後ろでリズムが違い、小節ごとに同じ → 1 小節のセット
    hs = _hits([(0, 1, 1.5, 3)] * 4)
    assert echo._chains(hs, _mu(4), _free, echo.UNIFY_DIFF)[0] == (0.0, 4.0, 4)
    # 小節ごとにリズムが違い、2 小節ごとに同じ → 2 小節のセット
    hs = _hits([(0, 1, 1.5, 3), (0, 2, 2.5, 3)] * 2)
    assert echo._chains(hs, _mu(4), _free, echo.UNIFY_DIFF)[0] == (0.0, 8.0, 2)


def test_odd_singles_sets_are_not_used_without_odd_ok():
    hs = _hits([(0, 1, 2)] * 4)   # 1 小節の片手の打点が 3＝手を入れ替えた反転はどう割り振っても置けない → 2 小節（6）のセット
    assert echo._chains(hs, _mu(4), _free, echo.UNIFY_DIFF) == [(0.0, 8.0, 2)]
    assert echo._chains(hs, _mu(4), _free, echo.UNIFY_DIFF, odd_ok=True) == [(0.0, 4.0, 4)]


def test_unify_copies_the_rhythm_of_the_set_and_keeps_density():
    # 2 小節目に 1 つ多い打点（2.5）・3 小節目は 1 つ少ない → どのセットも打点の数が真ん中のセットの写し
    hs = _hits([(0, 1, 1.5, 3), (0, 1, 1.5, 2.5, 3), (0, 1.5, 3), (0, 1, 1.5, 3)])
    out, rep = echo.unify(hs, _mu(4), {})
    assert rep['chains'] == [(0.0, 4.0, 4)]
    by = {}
    for h in out:
        by.setdefault(int(h.beat // 4), []).append(round(h.beat % 4, 3))
    assert all(tuple(v) == (0, 1, 1.5, 3) for v in by.values())
    assert rep['added'] == 1 and rep['removed'] == 1


def test_unify_makes_odd_sets_even_by_doubling_a_roomy_hit():
    hs = _hits([(0, 1, 2)] * 4)
    out, rep = echo.unify(hs, _mu(4), {})
    assert rep['doubled'] == 1 and rep['chains'] == [(0.0, 4.0, 4)]
    for i in range(4):   # どのセットも同じ所が両手（片手の打点が偶数）
        bar = [h for h in out if 4 * i <= h.beat < 4 * i + 4]
        assert sum(h.hands == 1 for h in bar) % 2 == 0
        assert [h.hands for h in bar] == [h.hands for h in out if 0 <= h.beat < 4]


def test_unify_leaves_user_ranges_and_motif_hits():
    hs = _hits([(0, 1, 1.5, 3), (0, 1, 1.5, 2.5, 3)] * 2)
    out, rep = echo.unify(hs, _mu(4), {}, avoid=[(0.0, 16.0)])
    assert rep['chains'] == [] and [h.beat for h in out] == [h.beat for h in hs]
    for h in hs:
        h.motif = {'group': 'g'}
    out, rep = echo.unify(hs, _mu(4), {})
    assert rep['chains'] == []


def test_flow_places_the_next_set_as_the_hand_swapped_mirror():
    hs = _hits([(0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5)] * 2 + [(0, 1, 1.5, 3)] * 4)
    mu = _mu(6)
    hs, rep = echo.unify(hs, mu, {})
    ev = [flow.Event(h.beat, h.beat * 0.5, h.hands) for h in hs]
    pl = echo.plan(ev, mu, rep['chains'])
    assert pl['marked'] >= 20 and {U for _, U, _ in pl['chains']} == {2.0, 4.0}
    notes, _ = flow.generate(ev, flow.Style(seed=1, w_same_hand=1.0))
    ok, tot = echo.check(ev, notes)
    assert tot == pl['marked'] and ok >= 0.9 * tot


def test_plan_without_chains_marks_only_same_beats_with_the_same_hands():
    hs = _hits([(0, 0.75, 1.5, 3, 3.5), (0, 0.75, 1.5, 2.5, 3, 3.5)])
    ev = [flow.Event(h.beat, h.beat * 0.5, h.hands) for h in hs]
    ev[0].hands = 2   # 1 つ目のセットの頭は両手・2 つ目は片手 → そこには付けない・1 つ目に無い拍（6.5）も付けない
    pl = echo.plan(ev, _mu(2))
    assert pl['chains'] == [(0.0, 4.0, 2)]
    assert sorted(e.beat for e in ev if e.echo) == [4.75, 5.5, 7.0, 7.5]


def test_chains_stay_inside_a_repeat_model_or_outside_all_repeat_ranges():
    # 同じ音楽の区間: 手本 拍 0〜16・写す側 拍 32〜48
    ok = echo._span_ok([[(0.0, 16.0), (32.0, 48.0)]])
    assert ok(0, 8) and ok(8, 16) and ok(16, 32)
    assert not ok(8, 24) and not ok(30, 34) and not ok(32, 40)   # 手本の境目をまたぐ・写す側にかかる
    hs = _hits([(0, 1, 1.5, 3)] * 12)
    _, rep = echo.unify(hs, _mu(12), {}, regions=[[(0.0, 8.0), (32.0, 40.0)]])
    for s, U, k in rep['chains']:
        assert (s + U * k <= 8 + 1e-6) or (s >= 8 - 1e-6 and s + U * k <= 32 + 1e-6) or s >= 40 - 1e-6


def test_short_sets_lead_with_one_hand_and_the_next_set_mirrors_with_the_other():
    hs = _hits([(0, 1, 2, 3)] * 4)   # 2 拍のセット（片手の打点 2・1 拍おき）
    mu = _mu(4)
    hs, rep = echo.unify(hs, mu, {})
    ev = [flow.Event(h.beat, h.beat * 0.5, h.hands) for h in hs]
    pl = echo.plan(ev, mu, rep['chains'])
    assert pl['lead'] and all(e.erun is not None for e in ev if e.beat < 2) and not any(e.erun for e in ev if e.echo)
    notes, _ = flow.generate(ev, flow.Style(seed=1, w_same_hand=1.0))
    ok, tot = echo.check(ev, notes)
    assert ok >= 0.9 * tot
    hand = {n['beat']: n['c'] for n in notes}
    for s in (0, 4, 8, 12):   # 2 拍ずつ 右右｜左左（か 左左｜右右）
        assert hand[s] == hand[s + 1] and hand[s + 2] == hand[s + 3] and hand[s] != hand[s + 2]
    # 片手で続けて振れない速さ（間合いが handoff.G_MIN 未満）は片手にしない
    ev = [flow.Event(h.beat, h.beat * 0.1, h.hands) for h in hs]
    assert not echo.plan(ev, mu, rep['chains'])['lead']
