"""両手の広がりの物差し（automap/stats.py の spread・docs/方針.md 6.21）。データベースは使わない（作り物のノーツ）。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from automap import stats  # noqa: E402


class _Tempo:
    """一定のテンポ（拍→秒）"""
    def __init__(self, bpm):
        self.bpm = bpm

    def sec(self, b):
        return b * 60.0 / self.bpm


def _n(b, c, x, y=0, d=1):
    return {'beat': b, 'c': c, 'x': x, 'y': y, 'd': d}


def test_beat_swings_same_as_library_themes():
    """振りのまとめ方は tools/library_themes.hand_swings と同じ（型のライブラリの swings の表と同じ決まり）"""
    import library_themes as LT
    tup = [(0.0, 0, 1, 0, 1), (0.125, 0, 1, 1, 1), (0.25, 0, 1, 2, 1), (1.0, 0, 0, 0, 0), (1.0, 0, 2, 0, 0),
           (1.2, 0, 3, 0, 1), (2.0, 1, 3, 0, 1), (2.1, 1, 2, 0, 1), (3.0, 1, 2, 0, 0)]
    for c in (0, 1):
        assert stats.beat_swings(tup, c) == [(b, *s) for b, s in LT.hand_swings(tup, c)]


def test_eighth_beat_chain_is_one_swing():
    """1/8 拍以内に続く物（続けば鎖のように伸びる）は1つの振りで先頭だけ・1/8 拍より空けば別の振り"""
    tup = [(0.0, 1, 3, 0, 1), (0.125, 1, 2, 0, 1), (0.25, 1, 1, 0, 1), (0.5, 1, 1, 0, 0)]
    assert stats.beat_swings(tup, 1) == [(0.0, 3, 0, 1), (0.5, 1, 0, 0)]


def test_wide_in3_hcol_by_definition():
    """組＝振りのたびにもう片方の手の直前の振り（1 秒以内）。wide＝左 0・右 3・in3＝4列全部にまたがらない・hcol＝手から見た列"""
    t = _Tempo(60)   # 1 拍＝1 秒
    sw_l = [(0.0, 0, 0, 1), (2.0, 1, 0, 1)]
    sw_r = [(0.5, 3, 0, 1), (2.5, 2, 0, 1)]
    r = stats.spread(sw_l, sw_r, t.sec)
    # 組: 0.5 の右(3)と 0.0 の左(0)＝(0, 3)・2.0 の左(1) と 0.5 の右は 1.5 秒＝組にしない・2.5 の右(2) と 2.0 の左(1)＝(1, 2)
    assert stats.spread_pairs(sw_l, sw_r, t.sec) == [(0, 3), (1, 2)]
    assert r['pairs'] == 2
    assert r['wide'] == pytest.approx(0.5)
    assert r['in3'] == pytest.approx(0.5)
    # 手から見た列: 左 x=0→r=3・左 x=1→r=2・右 x=3→r=3・右 x=2→r=2
    assert r['hcol'] == pytest.approx([0.0, 0.0, 0.5, 0.5])
    assert r['sps'] == pytest.approx(4 / 2.5)


def test_crossed_and_in3_windows():
    """左右が入れ替わった (3, 0) も4列全部にまたがる（in3 に入らない・wide でもない）。0〜2・1〜3 の中は in3"""
    t = _Tempo(60)
    sw_l = [(0.0, 3, 0, 1), (1.0, 0, 0, 1), (2.0, 1, 0, 1)]
    sw_r = [(0.5, 0, 0, 1), (1.5, 2, 0, 1), (2.5, 3, 0, 1)]
    pa = stats.spread_pairs(sw_l, sw_r, t.sec)
    assert pa == [(3, 0), (0, 0), (0, 2), (1, 2), (1, 3)]
    r = stats.spread(sw_l, sw_r, t.sec)
    assert r['wide'] == 0
    assert r['in3'] == pytest.approx(4 / 5)
    # 左 x=3・右 x=0 は反対の外（r=0）
    assert r['hcol'][0] == pytest.approx(2 / 6)


def test_far_pairs_not_counted():
    """1 秒より離れた組は数えない（1 秒ちょうどは数える）"""
    t = _Tempo(60)
    r = stats.spread([(0.0, 0, 0, 1)], [(1.5, 3, 0, 1)], t.sec)
    assert r['pairs'] == 0 and 'wide' not in r and 'in3' not in r
    r = stats.spread([(0.0, 0, 0, 1)], [(1.0, 3, 0, 1)], t.sec)
    assert r['pairs'] == 1 and r['wide'] == 1


def test_summarize_and_table_rows():
    """summarize に wide・in3・hcol・sps が入り（振りは 1/8 拍でまとめる）、表に行が足される。今の行と並びは変えない"""
    t = _Tempo(120)
    notes = []
    for i in range(8):
        b = i * 2.0
        notes += [_n(b, 0, 0, d=1), _n(b + 0.125, 0, 1, d=1),   # 左の続き（1/8 拍）＝1つの振り（頭の列 0）
                  _n(b + 1.0, 1, 3 if i % 2 == 0 else 2, d=1)]
    r = stats.summarize(notes, t)
    assert r['notes'] == 24
    sp = stats.note_spread(notes, t.sec)
    assert r['wide'] == sp['wide'] and r['in3'] == sp['in3'] and r['hcol'] == sp['hcol']
    # 振り: 左 8（列 0）・右 8（列 3 と 2 が交互）。組: 右の振りと直前の左（0.5 秒前）・左の振りと直前の右（0.5 秒前）
    assert r['hcol'] == pytest.approx([0.0, 0.0, 0.25, 0.75])
    assert 0 < r['wide'] < 1
    md = stats.table([('a', r)])
    rows = [ln.split('|')[1].strip() for ln in md.splitlines()[2:]]
    assert rows[:3] == ['ノーツ', '1秒のノーツ', '両手同時']
    assert rows[-6:-2] == ['1秒の振り（両手）', '両手を同時に外へ（左 0・右 3）', '両手が3列に収まる',
                           '手ごとの列（反対の内／自分の内／自分の外）']   # 後ろの2行は使うマスの偏り（6.22・test_stats_similarity）
    assert '| 両手を同時に外へ（左 0・右 3） | ' + f'{r["wide"] * 100:.0f}%' in md


def test_summarize_short_has_no_spread():
    """ノーツが1つ・片手だけの時は組が無い（キーを入れない）"""
    t = _Tempo(120)
    assert 'wide' not in stats.summarize([_n(0, 0, 0)], t)
    r = stats.summarize([_n(0, 1, 3), _n(1, 1, 2)], t)
    assert 'wide' not in r and r['hcol'] == pytest.approx([0, 0, 0.5, 0.5])


def test_tool_measure_and_rank():
    """tools/library_spread の measure は stats.spread を使い、少なすぎる譜面は数えない。上から何%"""
    import library_spread as LS
    t = _Tempo(60)
    sw_l = [(i * 1.0, 0, 0, 1) for i in range(12)]
    sw_r = [(i * 1.0 + 0.5, 3, 0, 1) for i in range(12)]
    r = LS.measure(sw_l, sw_r, t.sec)
    assert r == stats.spread(sw_l, sw_r, t.sec)
    assert LS.measure(sw_l[:5], sw_r[:5], t.sec) is None
    R = [{'wide': v} for v in (0.1, 0.2, 0.3, 0.4)]
    assert LS.rank_from_top(R, 'wide', 0.3) == pytest.approx(0.5)
    assert LS.rank_from_top(R, 'wide', 0.2, higher=False) == pytest.approx(0.5)
