"""緩急（息つぎ・automap/relief.py）の約束: どこを息つぎにするか・どんな型か・流れの計算で型に沿うか"""
from dataclasses import dataclass, field

from automap import flow, form, nlmf, relief, theme


def _blk(i, base, vocal=True, level=1, tension=0.0, group=None):
    return form.Block(b0=i * 16.0, b1=(i + 1) * 16.0, i0=i * 4, i1=(i + 1) * 4, group=group or base, base=base, level=level, tension=tension, vocal=vocal)


# ---- どこを息つぎにするか ----

def test_easy_scores_follow_human_direction():
    blocks = [_blk(0, 'A', vocal=False), _blk(1, 'B'), _blk(2, 'C', tension=-1.0), _blk(3, 'D', tension=1.0), _blk(4, 'E'), _blk(5, 'F')]
    s = relief.easy_scores(blocks, [32, 32, 32, 32, 64, 16])
    assert s[0] > s[1], '歌の無いまとまりは易しい側'
    assert s[2] > s[3], '盛り上がりの低いまとまりは易しい側'
    assert s[4] > s[5], '密度の高いまとまりは易しい側'


def test_easy_scores_skip_few_hits():
    blocks = [_blk(0, 'A'), _blk(1, 'B')]
    assert relief.easy_scores(blocks, [relief.MIN_HITS - 1, 20])[0] is None


def _song(n=30):
    """記号が 2 回ずつ出る曲: A B C … A B C …"""
    bases = [chr(65 + i) for i in range(n // 2)]
    return [_blk(i, bases[i % len(bases)]) for i in range(n)]


def test_choose_same_music_same_role():
    blocks = _song()
    scores = [0.5 - 0.05 * (i % 15) for i in range(30)]
    rest = relief.choose(blocks, scores, max_run=99, max_gap=99)
    by = {}
    for i, b in enumerate(blocks):
        by.setdefault(b.base, set()).add(i in rest)
    assert all(len(v) == 1 for v in by.values()), '同じ記号は同じ役'


def test_choose_share_run_and_gap():
    blocks = _song()
    scores = [1.0 - 0.1 * (i % 15) for i in range(30)]
    rest = relief.choose(blocks, scores)
    assert 0.2 <= len(rest) / 30 <= 0.5
    run = gap = 0
    for i in range(30):
        run = run + 1 if i in rest else 0
        gap = 0 if i in rest else gap + 1
        assert run <= relief.MAX_RUN, '息つぎが続きすぎる'
        assert gap <= relief.MAX_GAP, '息つぎの間が空きすぎる'


def test_choose_never_picks_locked_or_unusable():
    blocks = _song(12)
    scores = [1.0] * 12
    scores[5] = None
    rest = relief.choose(blocks, scores, locked={0, 1, 2})
    assert rest
    assert not rest & {0, 1, 2, 5}


def test_choose_empty_when_nothing_usable():
    assert relief.choose(_song(4), [None] * 4) == set()


def test_locked_by_range_length_not_hits():
    blocks = [_blk(0, 'A'), _blk(1, 'B'), _blk(2, 'C'), _blk(3, 'D')]
    it = {'ranges': [{'b0': 0.0, 'b1': 12.0, 'set': {'motif': {'group': 'g'}}},   # A の 3/4
                     {'b0': 16.0, 'b1': 20.0, 'set': {'width': 1}},                # B の 1/4
                     {'b0': 32.0, 'b1': 48.0, 'set': {'amount': 1}},               # C は打点の量の指示だけ
                     {'b0': 48.0, 'b1': 52.0, 'set': {'variety': -1}}, {'b0': 50.0, 'b1': 58.0, 'set': {'rare': 1}}]}   # D の 5/8（重なりは 1 回）
    assert relief._locked(blocks, it) == {0, 3}, '人の指示の区間が半分を超えるまとまりだけ'
    assert relief._locked(blocks, None) == set()


# ---- どんな型か ----

def _t(a, b=None, maps=10):
    a = [tuple(s) for s in a]
    b = [tuple(s) for s in (b or a)]
    return theme.Theme(a, b, maps, 'sym' if a == b else 'pair')


def test_usable_only_own_side_no_side_swing_no_single_cell():
    assert relief.usable(_t([(2, 0, 1), (3, 1, 0)]))
    assert not relief.usable(_t([(1, 0, 1), (2, 1, 0)])), '反対側の列（両手が交差する）'
    assert not relief.usable(_t([(2, 0, 2), (3, 1, 3)])), '真横'
    assert not relief.usable(_t([(2, 0, 1), (2, 0, 0)])), '同じマスの上下'
    assert not relief.usable(_t([(2, 0, 1), (3, 1, 0)] * 3)), '6 振り以上'


def test_candidates_add_two_swing_hands():
    two = [[2, 0, 1], [3, 1, 0]]
    lib = {'hands': [{'cycle': two, 'maps': 50}, {'cycle': [[1, 0, 1], [2, 1, 0]], 'maps': 50}], 'pairs': [], 'songs': 100}
    assert theme.load_themes(lib) == [], 'ふだんのテーマには 2 振りの片手の型は入らない'
    got = relief.candidates(lib, [])
    assert [t.a for t in got] == [[(2, 0, 1), (3, 1, 0)]], '息つぎには使う（交差する型は除く）'


def test_pick_prefers_easy_and_differs():
    easy, easy2 = _t([(2, 0, 1), (3, 1, 0)]), _t([(3, 0, 1), (2, 0, 0)])
    hard = _t([(2, 0, 6), (3, 2, 5), (2, 2, 7), (3, 0, 4)])
    assert relief.ease_of(easy) < relief.ease_of(hard)
    got = relief.pick([hard, easy, easy2], None, 4.0, seed=1, k=2)
    assert hard not in got
    assert got[0].key() != got[1].key()


def test_apply_guides_loop_follows_bar_music():
    a, c = _t([(2, 0, 1), (3, 1, 0)]), _t([(3, 0, 1), (2, 0, 0)])
    blocks = [_blk(0, 'A'), _blk(1, 'B')]
    mu = {'lab': {'mel': [1, 2, 1, 2, -1, -1, -1, -1], 'acc': [5, 5, 5, 5, 6, 6, 6, 6]}}
    other = (7, {0: [], 1: []}, 'base')
    bgd = {i: other for i in range(8)}
    got = relief.apply_guides(bgd, blocks, {'rest': {0}, 'of': {0: (a, c)}}, mu)
    assert got[0][1][1] == theme.transform(a, 'base')[0]
    assert got[1][1][1] == theme.transform(c, 'base')[0], '小節の音楽が変われば替える'
    assert got[2][0] == got[0][0], '同じ音楽の小節は同じ往復'
    assert all(got[i] == other for i in range(4, 8)), '息つぎの外はそのまま'
    bgd2 = relief.apply_guides(bgd, blocks, {'rest': {1}, 'of': {1: (a, c)}}, mu)
    assert len({bgd2[i][0] for i in range(4, 8)}) == 1, '同じ音楽が続く間はテーマの番号を変えない＝小節の頭でたどり直さない'


def test_mark_skips_human_directions_and_clears_pitch():
    @dataclass
    class H:
        beat: float
        mods: dict = field(default=None)
    blocks = [_blk(0, 'A'), _blk(1, 'B')]
    hits = [H(1.0), H(2.0, {'width': 1}), H(20.0)]
    evs = [flow.Event(h.beat, h.beat, 1, py=1.0) for h in hits]
    n = relief.mark(hits, evs, blocks, {'rest': {0}, 'of': {0: (_t([(2, 0, 1), (3, 1, 0)]),) * 2}})
    assert n == 1
    assert evs[0].relief == relief.THEME_K and evs[0].py is None
    assert evs[1].relief == 0.0 and evs[1].py == 1.0, '人の指示がある打点はそのまま'
    assert evs[2].relief == 0.0 and evs[2].py == 1.0, '息つぎの外はそのまま'


# ---- 流れの計算 ----

def _loop_events(relief_k, beats=128):
    tm = nlmf.TempoMap(120)
    cyc = {1: [(2, 0, 1), (3, 1, 0)], 0: [(1, 0, 1), (0, 1, 0)]}
    return [flow.Event(i * 0.5, tm.sec(i * 0.5), 1, 7, cyc, relief=relief_k) for i in range(beats)]


def _style():
    from automap.flow import CELL0
    return flow.Style(seed=1, noise=0.05, w_target={'row': 0.0, 'dir': 0.0, 'center': 0.0, 'still': 0.0, 'alt': 0.0, 'col': 0.0, 'cell': 12.0},
                      targets=dict(flow.LIBRARY_EPLUS, cell=CELL0))


def _follow(notes):
    want = {(2, 0, 1), (3, 1, 0)}
    rh = [n for n in notes if n['c'] == 1]
    return sum((n['x'], n['y'], n['d']) in want for n in rh) / len(rh)


def test_relief_keeps_loop_against_cell_target():
    with_r, _ = flow.generate(_loop_events(relief.THEME_K), _style())
    without, _ = flow.generate(_loop_events(0.0), _style())
    assert _follow(with_r) >= 0.95, '息つぎは同じ往復を続ける'
    assert _follow(with_r) > _follow(without), 'マスの目標が往復を崩す分が消える'


def test_relief_zero_is_default():
    a, _ = flow.generate(_loop_events(0.0, 64), _style())
    tm = nlmf.TempoMap(120)
    cyc = {1: [(2, 0, 1), (3, 1, 0)], 0: [(1, 0, 1), (0, 1, 0)]}
    b, _ = flow.generate([flow.Event(i * 0.5, tm.sec(i * 0.5), 1, 7, cyc) for i in range(64)], _style())
    assert a == b
