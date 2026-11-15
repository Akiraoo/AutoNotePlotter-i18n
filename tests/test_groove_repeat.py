"""リズムの型（automap/groove.py）と同じ音楽の区間のくり返し（automap/repeat.py）・docs/方針.md 6.31"""
from automap import flow, groove, repeat, rhythm
from automap import __main__ as cli


def _secs(end):
    s = rhythm.Section('A', 0, end)
    s.phrases = [(0, end)]
    return [s]


def _mu(n, acc, mel, short=()):
    bars, b = [], 0.0
    for i in range(n):
        bars.append(b)
        b += 2 if i in short else 4
    return {'bars': bars, 'lab': {'acc': acc, 'mel': mel, 'drum': [0] * n}}


def _hits(bars, pats):
    """小節ごとの打点の位置（拍）→ 打点"""
    out = []
    for b0, pat in zip(bars, pats):
        for off in pat:
            out.append(rhythm.Hit(b0 + off, 1, 0, 0, 'vocal', 0.5 + off / 10))
    return out


def _bars_of(hits, bars):
    from bisect import bisect_right
    by = {}
    for h in hits:
        i = bisect_right(bars, h.beat + 1e-6) - 1
        by.setdefault(i, []).append(round(h.beat - bars[i], 3))
    return {i: tuple(sorted(v)) for i, v in by.items()}


def test_same_music_bars_get_the_same_rhythm_with_the_same_density():
    mu = _mu(4, [0, 0, 0, 1], [0, 0, 0, 1])
    pats = [(0, 1, 2, 3), (0, 1, 2.5, 3), (0, 1, 2, 3.5), (0, 0.75, 1.5, 3.25)]
    out, rep = groove.regularize(_hits(mu['bars'], pats), mu, _secs(16), {})
    got = _bars_of(out, mu['bars'])
    assert got[0] == got[1] == got[2] == (0, 1, 2, 3)   # 3 小節中 2 小節以上で打つ位置・数は中央値（4）
    assert rep['groups'] == 1
    s = {h.s for h in out if h.beat < 12 and abs(h.beat % 4 - 1) < 1e-6}
    assert len(s) == 1   # 型の位置の強さはそろえる（展開で同じように間引かれる）


def test_similar_rhythms_snap_to_a_common_type_and_odd_bars_are_kept():
    mu = _mu(5, [0, 1, 2, 3, 4], [0, 1, 2, 3, 4], short={4})
    pats = [(0, 1, 2, 3), (0, 1, 2, 3), (0, 1, 2), (0, 0.5, 1.75, 2.25, 3.25), (0, 1)]
    out, rep = groove.regularize(_hits(mu['bars'], pats), mu, _secs(18), {})
    got = _bars_of(out, mu['bars'])
    assert got[2] == (0, 1, 2, 3)            # 1 つ欠け（違い 1/4）＝型に寄せる（ずれた位置は「欠け＋余分」で 2 つと数える）
    assert got[3] == (0, 0.5, 1.75, 2.25, 3.25)   # 違いが大きい＝そのまま
    assert got[4] == (0, 1)                  # 2 拍の小節は触らない
    assert rep['moved'] == 1


def test_find_repeated_passages_and_avoid_user_ranges():
    acc = [0, 1, 2, 3, 9, 0, 1, 2, 3, 8, 0, 1]
    mel = [5, 6, 7, 8, -1, 5, 6, 9, 8, -1, 5, 6]   # 2 回目は歌の記号が 1 つ違う（3/4 が同じ）
    mu = _mu(12, acc, mel)
    gs = repeat.find(mu)
    assert gs[0]['bars'] == 4 and [o[0] for o in gs[0]['occ']] == [0, 20]
    assert all(o[0] != 40 for g in gs for o in g['occ'] if g['bars'] == 4)   # 3 回目は 2 小節しか無い
    assert not any(o[0] <= 24 < o[1] for g in repeat.find(mu, avoid=[(20, 28)]) for o in g['occ'])


def test_carry_splits_and_regrow_restores_only_split_groups():
    """前の版の組の引き継ぎ（棚上げの 2）: 指示が変わった小節にかかる組は分ける（carry）。指示が無くなった小節では、まっさらに作った組
    （find）の形まで分けた残りを 1 つに戻す（regrow・2026-11-10 利用者「分かれた組だけ元の形に戻す」）。指示が残っている所・反転の向きが
    違う残り・完全に消えた組は戻さない"""
    mu = {'bars': [4.0 * i for i in range(20)]}
    whole = {'name': '自動1', 'bars': 6, 'occ': [(8, 32), (48, 72)], 'flip': 1}
    split, dropped = repeat.carry([whole], [(16, 17)], mu)   # 拍 16〜20 の小節に休み
    assert [(g['bars'], g['occ'][0][0], g['occ'][1][0], g['flip']) for g in split] == [(2, 8, 48, 1), (3, 20, 60, 1)]
    assert dropped == [(16, 20), (56, 60)]
    fresh = [dict(whole, flip=0)]
    back, grown = repeat.regrow(split, fresh, [(16, 20)], [], mu)   # 休みを外した
    assert [(g['bars'], g['occ'], g['flip']) for g in back] == [(6, [(8, 32), (48, 72)], 1)] and grown == [(16, 20), (56, 60)]
    assert repeat.regrow(split, fresh, [(16, 20)], [(16, 17)], mu)[0] == split   # まだ指示がある（休みを量に変えた等）
    flipped = [split[0], dict(split[1], flip=0)]
    assert repeat.regrow(flipped, fresh, [(16, 20)], [], mu)[0] == flipped   # 反転の向きが違う残りはまとめない
    short, _ = repeat.carry([dict(whole, bars=2, occ=[(12, 20), (52, 60)])], [(16, 17)], mu)
    assert short == [] and repeat.regrow(short, fresh, [(16, 20)], [], mu)[0] == []   # 完全に消えた組は戻さない
    one, grown = repeat.regrow([split[0]], fresh, [(16, 20)], [], mu)   # 後ろの残りが無い時は、指示が無くなった小節を含む側だけ伸ばす
    assert [(g['bars'], g['occ']) for g in one] == [(6, [(8, 32), (48, 72)])]


def test_apply_copies_the_model_and_alternates_mirror_by_group():
    mu = _mu(12, [0, 1, 7, 2, 3, 0, 1, 7, 2, 3, 6, 6], [0, 1, 7, 2, 3, 0, 1, 7, 2, 3, 6, 6])
    groups = [{'name': '自動1', 'bars': 2, 'occ': [(0, 8), (20, 28)]}, {'name': '自動2', 'bars': 2, 'occ': [(12, 20), (32, 40)]}]
    hits = _hits(mu['bars'], [(0, 1, 2), (0, 2), (0,), (0, 1), (0, 3), (0,), (0,), (0,), (0, 2), (0,), (0,), (0,)])
    out, used = repeat.apply(hits, groups, _secs(48))
    m = {round(h.beat, 3): h.motif for h in out if getattr(h, 'motif', None)}
    assert sorted(b for b in m if 20 <= b < 28) == [20, 21, 22, 24, 26]   # 手本（拍 0〜8）の並びを写す
    assert m[0]['occ'] == 0 and m[20]['occ'] == 1 and m[20]['mirror'] and not m[32]['mirror']   # 1 つ目は反転・2 つ目は同じ
    assert m[20]['auto'] and m[20]['idx'] == repeat.IDX0


def test_fix_motifs_mirrors_the_model_placement():
    hits = [rhythm.Hit(0, 1, 0, 0, 'vocal', 1), rhythm.Hit(8, 1, 0, 0, 'vocal', 1)]
    hits[0].motif = {'key': 'g', 'occ': 0, 'b0': 0}
    hits[1].motif = {'key': 'g', 'occ': 1, 'b0': 8, 'mirror': True}
    events = [flow.Event(h.beat, h.beat / 2, 1) for h in hits]
    gen = [{'beat': 0, 'c': 1, 'x': 3, 'y': 0, 'd': 6}]   # 右 ↙ 3 列
    groups = cli._fix_motifs(hits, events, gen)
    assert groups == {'g': [0, 8]} and events[1].fix == {0: (0, 0, 7)}   # 左 ↘ 0 列


def test_loops_repeat_the_same_hands_placement_two_swings_back():
    from automap import loops
    ev = [flow.Event(4 + k * 0.5, (4 + k * 0.5) * 0.5, 1) for k in range(40)]
    pl = loops.plan(ev, [4.0 + 4 * i for i in range(5)], seed=1, share=0.5)
    assert pl['spans'] and pl['marked'] >= 8
    notes, _ = flow.generate(ev, flow.Style(seed=1, w_same_hand=1.0))
    b0, b1 = pl['spans'][0]
    for c in (0, 1):
        sw = [(n['x'], n['y'], n['d']) for n in sorted(notes, key=lambda n: n['beat']) if n['c'] == c and b0 <= n['beat'] < b1]
        assert len(sw) >= 4 and all(sw[i] == sw[i + 2] for i in range(len(sw) - 2))   # 区間の中は A B A B
    assert loops.share(notes) > 0.2


def test_the_model_of_every_group_is_never_mirrored():
    # 2 つ目のグループ（左右反転の回を 1 つずらす）でも手本は反転しない（前は手本に反転の印が付き、「同じ」の回が手本の左右反転になった）
    mu = _mu(16, [0, 1, 0, 1, 5, 6, 5, 6, 2, 3, 2, 3, 7, 8, 7, 8], [0] * 16)
    hits = _hits(mu['bars'], [(0, 1, 2, 3)] * 16)
    groups = repeat.find(mu, [])
    out, used = repeat.apply(hits, groups, _secs(64))
    assert len(used) >= 2
    for h in out:
        m = getattr(h, 'motif', None)
        if m and m['occ'] == 0:
            assert not m['mirror']
    flips = {g['flip'] for g in used}
    assert flips == {0, 1}
