"""使うマスの偏りと曲どうしの似方の物差し（automap/stats.py の cell_stats・overlap・variety・tools/song_similarity.py・
docs/方針.md 6.22）。データベースは使わない（作り物の振り・小さな SQLite を作って読む）。"""
import json
import sqlite3
import sys
import zlib
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from automap import stats  # noqa: E402


class _Tempo:
    def __init__(self, bpm):
        self.bpm = bpm

    def sec(self, b):
        return b * 60.0 / self.bpm


def _n(b, c, x, y=0, d=1):
    return {'beat': b, 'c': c, 'x': x, 'y': y, 'd': d}


def test_to_r_same_as_library_themes():
    """右手の形へのそろえ方は tools/library_themes.to_r と同じ（左手は列 3−x・向きも左右反転）"""
    import library_themes as LT
    for c in (0, 1):
        for x in range(4):
            for d in range(9):
                assert stats.to_r(c, x, 1, d) == LT.to_r(c, (x, 1, d))
    assert stats.to_r(0, 0, 0, 2) == (3, 0, 3)    # 左手の左の外・左向き → 右手の形の自分の外・右向き
    assert stats.to_r(1, 1, 2, 4) == (1, 2, 4)


def test_cells_top2_aba():
    """cells＝手から見たマス（rx×3＋y）の割合・top2＝上位2マス・aba＝その手の振りが2つ前と同じ（3振りの並びの数あたり）"""
    # 右手: 31 ↓・20 ↑・31 ↓・10 ↑（3振りの並び 2 つ・往復は 1 つ目だけ）
    sw_r = [(0.0, 3, 1, 1), (1.0, 2, 0, 0), (2.0, 3, 1, 1), (3.0, 1, 0, 0)]
    # 左手: 列 0・1 は右手の形で rx 3・2（左右反転）。0 中段 ↓・1 下段 ↑・0 中段 ↓（往復 1 つ）
    sw_l = [(0.5, 0, 1, 1), (1.5, 1, 0, 0), (2.5, 0, 1, 1)]
    r = stats.cell_stats(sw_l, sw_r)
    n = 7
    want = [0.0] * 12
    want[3 * 3 + 1] = 4 / n    # rx 3・段 1
    want[2 * 3 + 0] = 2 / n    # rx 2・段 0
    want[1 * 3 + 0] = 1 / n
    assert r['cells'] == pytest.approx(want)
    assert sum(r['cells']) == pytest.approx(1.0)
    assert r['top2'] == pytest.approx(6 / 7)
    assert r['aba'] == pytest.approx(2 / 3)   # 右 1/2・左 1/1


def test_aba_needs_same_direction_and_mirrors_left():
    """往復はマスと向きの両方が同じ時だけ。左手は左右反転しても同じ物は同じ（そろえても数は変わらない）"""
    sw_r = [(0.0, 3, 0, 1), (1.0, 3, 0, 0), (2.0, 3, 0, 7)]   # 3振り目の向きが違う＝往復でない
    assert stats.cell_stats([], sw_r)['aba'] == 0.0
    sw_l = [(0.0, 0, 0, 6), (1.0, 1, 0, 5), (2.0, 0, 0, 6)]   # 左手の斜め（反転して 7・4・7）
    assert stats.cell_stats(sw_l, [])['aba'] == 1.0
    assert stats.hand_seqs(sw_l, [])[0] == [(3, 0, 7), (2, 0, 4), (3, 0, 7)]


def test_cells_skip_outside_grid_and_short():
    """マスの外（列 4 等）はマスの割合に入れない・振りが2つ以下なら aba は入れない"""
    r = stats.cell_stats([], [(0.0, 4, 0, 1), (1.0, 3, 0, 0)])
    assert r['cells'][9] == 1.0 and 'aba' not in r
    assert stats.cell_stats([], []) == {}


def test_summarize_has_cells_and_table_rows():
    """summarize に cells・top2・aba が入り（振りは 1/8 拍でまとめる＝spread と同じ）、表の最後に2行足される"""
    t = _Tempo(120)
    notes = []
    for i in range(6):
        b = i * 2.0
        notes += [_n(b, 0, 0, 1, d=1), _n(b + 0.125, 0, 1, 1, d=1),   # 左の続き（1/8 拍）＝1つの振り（頭の列 0）
                  _n(b + 1.0, 1, 3 if i % 2 == 0 else 2, 0, d=0)]
    r = stats.summarize(notes, t)
    sp = stats.note_spread(notes, t.sec)
    for k in ('cells', 'top2', 'aba'):
        assert r[k] == sp[k]
    # 左 6 振り（rx 3・段 1・同じ向き＝往復 4/4）・右 6 振り（30 と 20 が交互＝往復 4/4）
    assert r['cells'][3 * 3 + 1] == pytest.approx(0.5)
    assert r['top2'] == pytest.approx(0.75)
    assert r['aba'] == pytest.approx(1.0)
    md = stats.table([('a', r)])
    rows = [ln.split('|')[1].strip() for ln in md.splitlines()[2:]]
    assert rows[:3] == ['ノーツ', '1秒のノーツ', '両手同時']
    assert rows[-3:] == ['手ごとの列（反対の内／自分の内／自分の外）', 'よく使う2マスの割合', '同じ2振りの往復（A B A）']
    assert '| よく使う2マスの割合 | 75% |' in md
    assert '| 同じ2振りの往復（A B A） | 100% |' in md


def test_overlap_tri_one_variety():
    """重なり＝多重集合の Σmin ÷ 少ない方の数・3振りの並びはその手の中だけ・変化＝100振りあたりの種類・エントロピー・上位10"""
    a, b = Counter({'p': 2, 'q': 1}), Counter({'p': 1, 'r': 5})
    assert stats.overlap(a, b) == pytest.approx(1 / 3)
    assert stats.overlap(a, a) == 1.0
    assert stats.overlap(a, Counter()) == 0.0
    A, B, C = (3, 0, 1), (2, 0, 0), (3, 1, 1)
    seqs = [[A, B, C, A], [B, A]]          # 左手の並び・右手の並び（手をまたいで並びを作らない）
    t = stats.tri_counts(seqs)
    assert t == Counter({(A, B, C): 1, (B, C, A): 1})
    assert stats.one_counts(seqs) == Counter({A: 3, B: 2, C: 1})
    v = stats.variety(seqs)
    assert v['kinds'] == pytest.approx(2 / (6 / 100))
    assert v['entropy'] == pytest.approx(1.0)
    assert v['top10'] == 1.0
    assert stats.variety([[A, B]]) == {}


def test_song_similarity_diff_and_pairs(tmp_path):
    """難易度: 引数 → 作業ファイルの diff → Expert+。曲の組の表と平均"""
    import song_similarity as SS
    f = tmp_path / 'x.intent-s1.nlmf'
    assert SS.diff_of(f) == 'ExpertPlus'
    (tmp_path / 'x.intent-s1.automap.json').write_text(json.dumps({'diff': 'Hard'}), encoding='utf-8')
    assert SS.diff_of(f) == 'Hard'
    assert SS.diff_of(f, 'Expert+') == 'ExpertPlus'
    assert SS.label(f, []) == 'x' and SS.label(f, ['x']) == 'x.intent-s1.nlmf'
    T = [Counter({'p': 2}), Counter({'p': 1, 'q': 1}), Counter({'q': 4})]
    rows, m3, m1 = SS.pairs_table(['a', 'b', 'c'], T, T)
    assert len(rows) == 3
    assert m3 == pytest.approx((1 / 2 + 0 + 1 / 2) / 3) and m1 == m3


def _swing_blob(sw):
    return zlib.compress(json.dumps(sw).encode())


def test_song_similarity_ref_from_small_db(tmp_path):
    """ランク譜面の基準: Expert+・振り 200 以上・1秒の振り 3.5〜6 だけを読み、違う作者・同じ作者の違う曲の組を作る"""
    import song_similarity as SS
    db = tmp_path / 'lib.sqlite'
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE maps (id TEXT, level_author TEXT, bpm REAL)')
    con.execute('CREATE TABLE diffs (id INTEGER, map_id TEXT, bl_ranked INTEGER, characteristic TEXT, difficulty TEXT, bpm_change INTEGER)')
    con.execute('CREATE TABLE swings (diff_id INTEGER, hand INTEGER, data BLOB)')

    def add(did, mid, au, gap, n=120, diff='ExpertPlus', x0=3):
        con.execute('INSERT INTO maps VALUES (?, ?, ?)', (mid, au, 60.0))
        con.execute('INSERT INTO diffs VALUES (?, ?, 1, ?, ?, 0)', (did, mid, 'Standard', diff))
        for h in (0, 1):
            sw = [[i * gap + h * gap / 2, x0 if h else 3 - x0, i % 2, i % 2] for i in range(n)]
            con.execute('INSERT INTO swings VALUES (?, ?, ?)', (did, h, _swing_blob(sw)))

    add(1, 'm1', 'Alice', 0.4)            # 両手 240 振り・1秒 5 振り＝入る
    add(2, 'm2', 'alice ', 0.4, x0=2)     # 同じ作者（小文字・空白をならす）の違う曲＝入る
    add(3, 'm3', 'Bob', 0.4)              # 違う作者＝入る
    add(4, 'm4', 'Bob', 0.1)              # 1秒 20 振り＝入らない
    add(5, 'm5', 'Carol', 0.4, n=50)      # 振りが少ない＝入らない
    add(6, 'm6', 'Dan', 0.4, diff='Expert')   # Expert＝入らない
    con.commit()
    con.close()
    data = SS.ref_data(db)
    assert sorted(data) == [1, 2, 3]
    assert data[1][2] == data[2][2] == 'alice'
    dp, sp = SS.ref_pairs(data, n=5)
    assert len(dp) == 5 and all(data[a][2] != data[b][2] for a, b in dp)
    assert sp == [(1, 2)]
    assert SS.ref_pairs(data, n=5) == (dp, sp)   # 種で決まる
    lines = SS.ref_lines(db)
    assert any(ln.startswith('| 同じ作者の違う曲 | 1 |') for ln in lines)
