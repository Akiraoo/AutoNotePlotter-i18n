"""両手を同時に外へ（wide）・手ごとの列（hcol）の目標（style.targets・style.want）と、型の広がりの見込み（theme.spread・theme.fit）"""
import pytest

from automap import style, theme

T0 = {'outer': 0.0, 'diag': 0.0, 'row': 0.0, 'move': 0.0}


def _row(i):
    r = style.HCOL_TABLE[i]
    return [v / sum(r) for v in r]


def test_rank_spread_follows_the_table():
    """表の点はその値・間は線でつなぐ・端の外は端の値・sps が無ければ 4.0。hcol は足して 1"""
    hcol, wide = style.rank_spread(style.SPS_TABLE[2])
    assert wide == pytest.approx(style.WIDE_TABLE[2]) and hcol == pytest.approx(_row(2))
    mid = (style.SPS_TABLE[3] + style.SPS_TABLE[4]) / 2
    hcol, wide = style.rank_spread(mid)
    assert wide == pytest.approx((style.WIDE_TABLE[3] + style.WIDE_TABLE[4]) / 2)
    assert hcol == pytest.approx([(a + b) / 2 for a, b in zip(_row(3), _row(4))], abs=1e-9)
    assert style.rank_spread(0.5)[1] == pytest.approx(style.WIDE_TABLE[0]) and style.rank_spread(0.5)[0] == pytest.approx(_row(0))
    assert style.rank_spread(30)[1] == pytest.approx(style.WIDE_TABLE[-1]) and style.rank_spread(30)[0] == pytest.approx(_row(-1))
    assert style.rank_spread(None) == style.rank_spread(4.0)
    for s in (1, 2.5, 4.2, 6.6, 9, 12):
        assert sum(style.rank_spread(s)[0]) == pytest.approx(1.0)


def test_targets_hcol_wide_and_col():
    """標準はランク譜面のふつう。曲の個性は自分の外と wide を ±0.03（その分を自分の内から引く）。col は hcol の左右の平均。ほかのキーは傾きで変わらない"""
    base = style.targets(T0, sps=5.0)
    hcol, wide = style.rank_spread(5.0)
    assert base['hcol'] == pytest.approx(hcol) and base['wide'] == pytest.approx(wide)
    up = style.targets(dict(T0, outer=1.0), sps=5.0)
    dn = style.targets(dict(T0, outer=-1.0), sps=5.0)
    assert up['hcol'][3] == pytest.approx(hcol[3] + 0.03) and up['hcol'][2] == pytest.approx(hcol[2] - 0.03)
    assert dn['hcol'][3] == pytest.approx(hcol[3] - 0.03) and dn['hcol'][2] == pytest.approx(hcol[2] + 0.03)
    assert up['hcol'][:2] == pytest.approx(hcol[:2]) and up['wide'] == pytest.approx(wide + 0.03) and dn['wide'] == pytest.approx(wide - 0.03)
    for tg in (base, up, dn, style.targets(dict(T0, outer=0.41), sps=4.2), style.targets(T0)):
        assert sum(tg['hcol']) == pytest.approx(1.0) and min(tg['hcol']) >= 0
        assert tg['col'] == pytest.approx(tuple((tg['hcol'][x] + tg['hcol'][3 - x]) / 2 for x in range(4)))
        assert sum(tg['col']) == pytest.approx(1.0)
    for k in ('row', 'dir', 'center', 'still', 'alt'):
        assert up[k] == base[k] == dn[k]
    assert style.targets(T0) == style.targets(T0, sps=4.0)


def test_targets_library_shift_is_capped_on_own_outer():
    """型のデータベースの外側のずらしは自分の外に足す（±0.03 で切る・その分を自分の内から引く）"""
    base = style.targets(T0, sps=4.0)
    for d, got in ((0.01, 0.01), (0.10, 0.03), (-0.10, -0.03)):
        lib = {'library': {'filters': {}, 'stats': {'outer': style.LIB_REF['outer'] + d, 'diag': style.LIB_REF['diag'],
                                                     'top': style.LIB_REF['top'], 'bottom': style.LIB_REF['bottom']}}}
        tg = style.targets(T0, lib=lib, sps=4.0)
        assert tg['hcol'][3] == pytest.approx(base['hcol'][3] + got) and tg['hcol'][2] == pytest.approx(base['hcol'][2] - got)
        assert tg['wide'] == pytest.approx(base['wide'])


def test_want_outer_wide_and_small_tilt():
    """狙いの外側の列はランク譜面のふつう（反対の外＋自分の外）を中心に ±0.03・横の幅の傾きは ±0.25・wide は targets と同じ"""
    hcol, wide = style.rank_spread(6.0)
    for to in (-1.0, 0.0, 0.41, 1.0):
        t = dict(T0, outer=to)
        for base in theme.WANT.values():
            w = style.want(base, t, sps=6.0)
            assert w['outer'] == pytest.approx(hcol[0] + hcol[3] + 0.03 * to)
            assert w['width'] == pytest.approx(min(3.0, max(0.0, base['width'] + 0.25 * to)))
            assert w['wide'] == pytest.approx(style.targets(t, sps=6.0)['wide'])
    assert style.want(theme.WANT['big'], T0) == style.want(theme.WANT['big'], T0, sps=4.0)


def _sym(cyc):
    return theme.Theme(list(cyc), list(cyc), 10, 'sym')


OUT = [(3, 0, 1), (3, 2, 0), (3, 0, 1), (3, 2, 0)]      # 右手の形で外の列だけ（左手は反転して列 0）
IN = [(1, 0, 1), (2, 1, 0), (1, 0, 1), (2, 1, 0)]       # 内側だけ
HALF = [(1, 0, 6), (3, 1, 5), (3, 0, 1), (2, 2, 0)]     # ↙10 ↗31 ↓30 ↑22（ハロの big の主のテーマ）
SPR = [(3, 0, 1), (3, 2, 0), (3, 0, 1), (2, 1, 0)]      # 右手が 4 回のうち 3 回外


def test_spread_counts_both_hands_outer():
    """sym で右手が外の型は高い・内の型は低い。左手は b を反転して使う＝b の列 3 が左手の列 0。pair は左右の型を別々に見る"""
    assert theme.spread(_sym(OUT)) == pytest.approx(1.0)
    assert theme.spread(_sym(IN)) == 0.0
    # ↙10 ↗31 ↓30 ↑22（ハロの主なテーマ）: 左手は列 2・0・0・1 を同じ番目から＝右から 3/8・左から 3/8
    assert [x for x, _, _ in theme.mirror(HALF)] == [2, 0, 0, 1]
    assert theme.wide_pairs(theme.mirror(HALF), HALF) == (3, 3, 8)
    assert theme.spread(_sym(HALF), ease=False) == pytest.approx(6 / 16)
    # 実際に渡す形（tf_ease が ↑22 の 2 回に 1 回を ↗31 へ）は外が増える
    assert theme.spread(_sym(HALF)) > theme.spread(_sym(HALF), ease=False)
    assert theme.spread(_sym(SPR)) == pytest.approx(10 / 16)
    # 右手だけ外・左手は内（pair）は 0。左右の型の長さが違っても回る（pair はずらさない）
    assert theme.spread(theme.Theme(OUT, IN, 5, 'pair')) == 0.0
    assert theme.spread(theme.Theme(OUT, [(3, 0, 1), (2, 1, 0)], 5, 'pair')) == pytest.approx(0.5)
    # 左右を反転した型（右手が列 0・左手が列 3）は「両手を同時に外へ」ではない
    assert theme.spread(_sym(theme.mirror(OUT))) == 0.0


def test_fit_penalizes_spread_over_wide_only():
    """狙いに wide がある時だけ、spread が狙いより多い分を W_SPREAD の重みで減点に足す（少ない分はごほうびにしない・無ければ前と同じ値）"""
    w0 = style.want(theme.WANT['big'], T0)
    plain = {k: v for k, v in w0.items() if k != 'wide'}
    for th in (_sym(OUT), _sym(IN), _sym(HALF), _sym(SPR)):
        extra = theme.W_SPREAD * max(0.0, theme.spread(th) - w0['wide']) + theme.W_OUTER * max(0.0, theme.eased_outer(th) - w0['outer'])
        assert theme.fit(th, w0, 0.15) == pytest.approx(theme.fit(th, plain, 0.15) + extra)
    assert theme.fit(_sym(IN), w0, 0.15) == theme.fit(_sym(IN), plain, 0.15)


def test_fit_puts_spreading_theme_behind():
    """形の数（段・動き・斜め・外側の列・幅）が同じ 2 つの型（右手が列 3 の型と、それを左右反転した型）は wide が無ければ同じ点。
    wide があれば、両手を同時に外へ広がる型が後ろになる"""
    a, b = _sym(SPR), _sym(theme.mirror(SPR))
    w0 = style.want(theme.WANT['big'], T0)
    plain = {k: v for k, v in w0.items() if k != 'wide'}
    assert theme.fit(a, plain, 0.15) == pytest.approx(theme.fit(b, plain, 0.15))
    assert theme.fit(a, w0, 0.15) > theme.fit(b, w0, 0.15) + 0.3
    sec = type('S', (), {'name': 'サビ'})()
    got = theme.pick_themes([a, b], [sec], want_of=lambda s: w0, pop=0.15)
    assert got['サビ'].key() == b.key()


def test_rank_cells_and_habit():
    """手から見たマスの目標（6.22）: ランク譜面の表を線でつなぐ（足して 1）・曲ごとの癖は列ごとの合計を変えずに段の割合だけ散らす・
    種が同じなら同じ・曲が違えば違う・None なら散らさない。targets の cell の列ごとの合計は hcol と同じ"""
    c = style.rank_cells(4.5)
    assert len(c) == 12 and abs(sum(c) - 1) < 1e-9
    assert style.rank_cells(None) == style.rank_cells(style.SPS_DEFAULT)
    s1, s2 = style.habit_seed('曲A'), style.habit_seed('曲B')
    assert s1 == style.habit_seed('曲A') and s1 != s2 and style.habit_seed('曲A', 2) != s1
    h1, h2 = style.habit_cells(c, s1), style.habit_cells(c, s2)
    assert h1 == style.habit_cells(c, s1) and h1 != h2 and style.habit_cells(c, None) == tuple(c)
    for h in (h1, h2):
        for r in range(4):
            assert sum(h[r * 3:r * 3 + 3]) == pytest.approx(sum(c[r * 3:r * 3 + 3]))
    tg = style.targets(T0, sps=4.2, habit=s1)
    for r in range(4):
        assert sum(tg['cell'][r * 3:r * 3 + 3]) == pytest.approx(tg['hcol'][r])
