from automap import form, rhythm


def _mu(n=16, change=8):
    """4拍の小節 n 個。change の小節からドラムと楽器が上がり、歌の並びも変わる（前半・後半とも4小節のくり返し）"""
    lo = [-1.0] * change + [1.0] * (n - change)
    lab = [k % 4 for k in range(change)] + [4 + k % 4 for k in range(n - change)]
    return {'bars': [4 * i for i in range(n)], 'shift': [0] * n, 'breaks': [],
            'lab': {'mel': lab, 'acc': lab, 'drum': [0] * n},
            'inten': {'drum': lo, 'bands': [18 + 2 * v for v in lo], 'sing': [1.0] * n, 'lead': [0.0] * n, 'drum_change': [change]}}


def test_build_groups_and_levels():
    """ドラムの変わり目で区切り・4小節ずつ・同じ並びは同じ記号・後半の方が段階が高い"""
    bl = form.build(_mu(), [], 64)
    assert [(b.i0, b.i1) for b in bl] == [(0, 4), (4, 8), (8, 12), (12, 16)]
    assert [b.group for b in bl] == ['A', 'A', 'B', 'B']
    assert bl[0].level < bl[2].level


def test_drum_change_moves_to_next_cue():
    """ドラムの変わり目の次の小節にマーカーがあれば、区切りはマーカーの小節（溜めの小節は前のまとまりの終わり）"""
    mu = _mu(change=7)
    bl = form.build(mu, [{'beat': 32, 'name': 'サビ'}], 64)
    assert 8 in [b.i0 for b in bl] and 7 not in [b.i0 for b in bl]


def test_apply_breaks():
    """途切れ（拍 10 から 1 拍）の間の打点を除き、戻りの最初の打点を両手に"""
    hits = [rhythm.Hit(b / 2, 1, 0, 0, 'vocal', 1.0) for b in range(41)]
    mu = {'breaks': [{'beat': 10.0, 'len': 1.0, 'kind': 'all'}]}
    out = form.apply_breaks(hits, mu)
    beats = [h.beat for h in out]
    assert 10.5 not in beats and 10.0 in beats
    h = next(h for h in out if h.beat == 11.0)
    assert h.hands == 2 and h.reentry
