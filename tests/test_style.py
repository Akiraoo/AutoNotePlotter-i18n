from pathlib import Path

import pytest

from automap import form, style, theme
from tests.test_form import _mu

ROOT = Path(__file__).resolve().parent.parent
MID = {k: v[5] for k, v in style.DECILES.items()}


def test_tilt_directions():
    """速い・歌の音が長い曲は外側へ、ドラムの裏拍が多い曲は斜めを減らす（人の譜面の関係の向き）"""
    fast = style.tilt(dict(MID, bpm=190, vlen=0.40))
    slow = style.tilt(dict(MID, bpm=100, vlen=0.20))
    assert fast['outer'] > 0.3 > -0.3 > slow['outer']
    assert style.tilt(dict(MID, doff16=0.5))['diag'] < -0.5 < 0.5 < style.tilt(dict(MID, doff16=0.03))['diag']
    assert abs(style.tilt(MID)['outer']) < 0.05


def test_want_stays_in_range():
    """狙いは候補の型がある範囲に収まる（外側の列の割合・段・斜め・横の幅）"""
    for t in ({'outer': 1, 'diag': 1, 'row': 1, 'move': 1}, {'outer': -1, 'diag': -1, 'row': -1, 'move': -1}):
        for base in theme.WANT.values():
            w = style.want(base, t)
            assert 0.0 <= w['outer'] <= 1.0 and 0.0 <= w['diag'] <= 1.0 and 0.0 <= w['row'] <= 1.4 and 0 <= w['width'] <= 3


def test_pick_palette():
    """テーマは性格ごとに k 個まで。まとまりの前半と後半は別のテーマ（型は型のデータベースの新しい曲の既定から・無い PC は飛ばす）"""
    from automap import library_use
    try:
        lib = library_use.export(library_use.concrete(library_use.DEFAULT))
    except library_use.Unavailable as e:
        pytest.skip(str(e))
    bl = form.build(_mu(), [], 64)
    ons = {'vocal': [], 'kick': [], 'snare': []}
    chosen, seq, pal, order, f, t = style.pick(bl, ons, 120, theme.load_themes(lib), k=3, lib=lib)
    assert set(pal) == set(order) and all(len(v) == 3 for v in pal.values())
    assert len({t_.key() for b in bl for t_ in seq[b.base]}) <= 3 * len(order)
    assert all(seq[b.base][0].key() == chosen[b.base].key() != seq[b.base][1].key() for b in bl)
