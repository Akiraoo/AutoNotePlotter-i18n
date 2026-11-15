"""区間の点検（automap/section_check.py）: 作り物のノーツで、振りの並び・ライブラリの数・区間どうしの似かた・崩れと警告の数え方を確かめる"""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from automap import section_check as SC
from automap import stats

ROOT = Path(__file__).resolve().parent.parent
MIRROR = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}
P = [(2, 0, 1), (2, 1, 0)]                                   # 右手の形（x, y, 向き）・振り下ろしと振り上げが交互
Q = [(3, 0, 1), (3, 2, 0), (2, 0, 7), (2, 1, 4)]
R = [(1, 0, 6), (3, 1, 5), (0, 0, 1), (2, 2, 4), (1, 1, 7), (3, 0, 0)]   # P・Q と重ならない並び


def hand(cyc, c, n, start, step=1.0):
    """右手の形の型 cyc を手 c で n 振り（左手は左右反転）→ [(拍, 色, x, y, 向き)]"""
    out = []
    for k in range(n):
        x, y, d = cyc[k % len(cyc)]
        if c == 0:
            x, d = 3 - x, MIRROR[d]
        out.append((start + k * step, c, x, y, d))
    return out


def part(cyc_r, cyc_l, b0, beats):
    """右手と左手を 1 拍おきに交互（左は半拍ずらす）に並べた区間"""
    return hand(cyc_r, 1, beats, b0) + hand(cyc_l, 0, beats, b0 + 0.5)


def test_mirror_and_windows():
    # 左手の型を左右反転して置くと、右手と同じ並びの番号になる
    b1, k1 = SC.hand_codes([(i, s) for i, s in enumerate(Q * 2)], 1)
    left = [(i, (3 - x, y, MIRROR[d])) for i, (x, y, d) in enumerate(Q * 2)]
    b0, k0 = SC.hand_codes(left, 0)
    assert list(k0) == list(k1)
    w = SC.windows(k1, 4)
    assert len(w) == 5 and len(set(w.tolist())) == 4      # 4振りの輪のずらし 4 種類
    assert SC.seq_text(int(w[0]), 4) == '↓30 ↑32 ↘20 ↖21'
    # マスの外・向きの外・小数の座標は並びに入れない
    _, k = SC.hand_codes([(0, (2, 0, 1)), (1, (5, 0, 0)), (2, (2, 0, 1)), (3, (1.5, 1, 0)), (4, (2, 0, 9))], 1)
    assert list(k) == [SC.code(2, 0, 1), -1, SC.code(2, 0, 1), -1, -1]
    assert (SC.windows(k, 3) == -1).all()


def test_count_swings_counts_songs_once():
    """同じ曲の中で何度出ても、Expert と Expert+ の両方にあっても 1 曲"""
    sw = lambda cyc, c, n: [[b, x, y, d] for b, _, x, y, d in hand(cyc, c, n, 0)]
    rows = [(1, 10, 1, sw(P, 1, 20)), (1, 11, 0, sw(P, 0, 20)),      # 曲 1: P（右・左）
            (2, 20, 1, sw(P, 1, 8)), (2, 20, 0, sw(Q, 0, 8)),        # 曲 2: P（右）・Q（左）
            (3, 30, 1, sw(R, 1, 12))]                                # 曲 3: R
    keys, counts, songs, ref = SC.count_swings(rows)
    idx = SC.Index(keys, counts, songs, {})
    assert songs == 3
    k = lambda cyc, n: SC.windows(SC.hand_codes([(i, s) for i, s in enumerate(cyc * 3)], 1)[1], n)[:1]
    assert idx.lookup(k(P, 4), 4)[0] == 2
    assert idx.lookup(k(Q, 4), 4)[0] == 1
    assert idx.lookup(k(R, 3), 3)[0] == 1
    assert idx.lookup(np.array([-1, 5]), 3).tolist() == [0, 0]
    assert ref is not None and ref['maps'] == 3


def test_grams_pack_round_trip():
    """配布用のライブラリの形（grams）: 詰めて戻しても数える物は同じ・順番と拍は残らない・切れ目をまたぐ並びは数にだけ入る"""
    sw = lambda cyc, c, n, step: [[b, x, y, d] for b, _, x, y, d in hand(cyc, c, n, 0, step)]   # noqa: E731
    bad = [[70.0, 5, 0, 0]]   # マスの外＝使えない振り
    rows = [(1, 10, 1, sw(Q, 1, 40, 1.5)), (1, 10, 0, sw(R, 0, 30, 2.0) + bad), (2, 20, 1, sw(P, 1, 3, 1.0)), (3, 30, 0, [])]
    want = SC.count_swings(rows)
    packed = []
    for mid, did, h, s in rows:
        g = SC.grams(*SC.hand_codes([(x[0], tuple(x[1:4])) for x in s], h))
        back = SC.unpack_grams(SC.pack_grams(g))
        assert back['n'] == g['n'] == len(s)
        for n in SC.N_LIST:
            w, c, x = g[n]
            bw, bc, bx = back[n]
            assert sorted(zip(c.tolist(), w.tolist())) == list(zip(bc.tolist(), bw.tolist()))   # 切れ目・番号の順に並べ直した多重集合
            assert bx.tolist() == sorted(set(x.tolist()))
            assert (bw >= 0).all() and (bx >= 0).all()
        packed.append((mid, did, h, back))
    assert len(packed[0][3][4][2]) and len(packed[0][3][4][0])   # 拍 32 の切れ目をまたぐ並びと、中の並びの両方がある
    got = SC.count_grams(packed)
    assert got[2] == want[2] == 3 and got[3] == want[3]
    for n in SC.N_LIST:
        assert got[0][n].tolist() == want[0][n].tolist() and got[1][n].tolist() == want[1][n].tolist()


def _secs():
    return [{'name': 'Aメロ', 'tags': [], 'b0': 0, 'b1': 32}, {'name': 'サビ', 'tags': [], 'b0': 32, 'b1': 64},
            {'name': 'Bメロ', 'tags': [], 'b0': 64, 'b1': 96}, {'name': 'サビ', 'tags': [], 'b0': 96, 'b1': 128},
            {'name': 'Cメロ', 'tags': [], 'b0': 128, 'b1': 160}]


def test_similarity_marks():
    """同じ名前の区間（サビ）が全く違う＝≠・違う音楽なのに前の区間と同じ＝＝"""
    notes = (part(P, P, 0, 32) + part(Q, Q, 32, 32) + part(Q, Q, 64, 32) + part(R, R, 96, 32) + part(R, R, 128, 32))
    S = SC.check(notes, _secs(), 120)
    assert [s['name'] for s in S] == ['Aメロ', 'サビ', 'Bメロ', 'サビ', 'Cメロ']
    assert S[1]['same'] == [3] and S[1]['best_same']['sim'] == 0
    assert 'differ' in S[1]['flags'] and 'differ' in S[3]['flags']
    assert S[2]['prev_sim'] == 1.0 and 'mono' in S[2]['flags']          # Bメロ がサビ（違う音楽）と同じ
    assert S[4]['prev_sim'] == 1.0 and 'mono' in S[4]['flags']
    assert S[1]['prev_sim'] == 0 and 'mono' not in S[1]['flags']
    assert all(s['lib'] is None and 'near' not in s for s in S)        # ライブラリ無し＝1 の数字は出さない
    # 流れの表の記号が同じなら名前が違っても同じ音楽（Bメロ がサビと同じ記号）＝＝ にしない
    blocks = [(0, 32, 'A'), (32, 64, 'B'), (64, 96, 'B'), (96, 128, 'B'), (128, 160, 'C')]
    S2 = SC.check(notes, _secs(), 120, blocks)
    assert S2[2]['prev_same_music'] and 'mono' not in S2[2]['flags'] and 2 in S2[1]['same']
    # 同じサビを同じ並びにすると印は消える
    notes3 = part(P, P, 0, 32) + part(Q, Q, 32, 32) + part(R, R, 64, 32) + part(Q, Q, 96, 32) + part(P, P, 128, 32)
    S3 = SC.check(notes3, _secs(), 120)
    assert S3[1]['best_same']['sim'] == 1.0 and not S3[1]['flags'] and not S3[3]['flags']


def test_counts_match_stats_summarize():
    """区間ごとの崩れ・NLM の振りの警告と同じ決まりの和が、曲全体の stats.summarize と同じ（境目をまたぐ物は後ろの区間）"""
    notes = part(P, Q, 0, 40) + part(R, P, 40, 40) + part(Q, R, 80, 80)
    notes += [(30.25, 1, 1, 0, 1), (31.0, 1, 2, 0, 1), (64.0, 0, 1, 1, 8), (64.0, 1, 2, 1, 8), (90.5, 0, 0, 0, 0)]   # 崩れ・点・両手
    S = SC.check(notes, _secs(), 140)
    tempo = SimpleNamespace(sec=lambda b: b * 60 / 140)
    whole = stats.summarize([{'beat': b, 'c': c, 'x': x, 'y': y, 'd': d} for b, c, x, y, d in notes], tempo)
    assert sum(s['notes'] for s in S) == whole['notes'] == len(notes)
    assert sum(s['warn'] for s in S) == whole['nlm_swing'] > 0
    assert sum(s['reset'] for s in S) / sum(s['pairs'] for s in S) == pytest.approx(whole['reset'])
    assert sum(s['double'] for s in S) == 1 and S[2]['double'] == 1   # 拍 64 の両手は Bメロ（境目の頭は後ろの区間）
    assert S[0]['nps'] == pytest.approx(S[0]['notes'] / (32 * 60 / 140), abs=0.01)


def test_with_index():
    """人の譜面との近さ: ライブラリにある並びの割合・珍しい並び"""
    sw = lambda cyc, c, n: [[b, x, y, d] for b, _, x, y, d in hand(cyc, c, n, 0)]
    rows = [(m, m, 1, sw(P, 1, 20)) for m in range(3)] + [(9, 9, 1, sw(Q, 1, 4))]
    keys, counts, songs, ref = SC.count_swings(rows)
    idx = SC.Index(keys, counts, songs, {}, ref=ref)
    notes = part(P, P, 0, 32) + part(R, R, 32, 32)
    S = SC.check(notes, _secs()[:2], 120, index=idx)
    assert S[0]['lib']['hit4'] == 1.0 and S[0]['near'] == 1.0 and S[0]['lib']['med4'] == pytest.approx(3 / 4)
    assert S[1]['lib']['hit4'] == 0.0 and S[1]['near'] == 0.0 and len(S[1]['lib']['rare']) == 3
    assert all(r['songs'] == 0 for r in S[1]['lib']['rare'])


def test_sections_of_like_lane():
    """帯「区間」と同じ切り方（名前の無いマーカーは前の区間の書き込み）"""
    marks = [{'beat': 2, 'name': 'イントロ', 'tags': []}, {'beat': 10, 'name': '', 'tags': ['★']}, {'beat': 18, 'name': 'Aメロ', 'tags': []}]
    s = SC.sections_of(marks, 50)
    assert [(x['name'], x['b0'], x['b1'], x['tags']) for x in s] == [('イントロ', 2, 18, ['★']), ('Aメロ', 18, 50, [])]
    assert SC.base_name('サビ2') == SC.base_name('サビ ') == 'サビ'


# ---- 作り物の型のライブラリ（tests/test_library_db.py と同じ手元の譜面）で数える ----

@pytest.fixture(scope='module')
def db(tmp_path_factory):
    sys.path.insert(0, str(ROOT / 'tests'))
    sys.path.insert(0, str(ROOT / 'tools' / 'library_build'))
    import build_db  # noqa: E402
    import fetch  # noqa: E402
    import test_library_db as T  # noqa: E402  （作り物の手元の譜面）
    tmp = tmp_path_factory.mktemp('seclib')
    cl = T._library(tmp)
    raw = tmp / 'raw'
    raw.mkdir()
    fetch.cmd_local(SimpleNamespace(local=str(cl)), raw)
    p = tmp / 'library.sqlite'
    build_db.build(raw, p, jobs=1, log=lambda *a: None, own_patterns=T.OWN)
    return SimpleNamespace(path=p, T=T)


def test_build_index_from_db(db):
    from automap import library_db
    f = {'sources': ['local'], 'include_own': True}
    idx = SC.build_index(f, db.path)
    assert idx.songs == library_db.export_themes(f, db=db.path)['songs']
    A = db.T.A   # 右手の形の型 A（a1・a1 の複製・b2・i9 の Expert／Expert+ に出る）
    w = SC.windows(SC.hand_codes([(i, s) for i, s in enumerate(A * 3)], 1)[1], 4)[:1]
    assert idx.lookup(w, 4)[0] == 4
    got, state, err = SC.index_for(f, wait=30, db=db.path)
    assert state == 'ok' and got.songs == idx.songs
    got, state, err = SC.index_for(f, wait=30, db=db.path.with_name('none.sqlite'))
    assert got is None and state == 'unavailable' and err


# ---- 決めの場所（app/check.py: 作り直しの報告の「## 決め（珍しい型）」の表を読む） ----

def _app_check():
    sys.path.insert(0, str(ROOT / 'app'))
    import check  # noqa: E402  （app/ の中）
    return check


def _kime_md(kimes, only=None):
    """作り直しの報告と同じ書き方（automap/__main__.py の _kime_lines）の決めの節"""
    from automap import __main__ as cli
    secs = [SimpleNamespace(name='サビ', nth=0), SimpleNamespace(name='Aメロ', nth=1)]
    tempo = SimpleNamespace(sec=lambda b: b * 0.5)
    proj = {'graph': {'song': {'offset': 0.25}}}
    head = [f'- **選んだ区間（拍 {only[0]:g}〜{only[1]:g}）だけ作り直した**。外は結果のファイルの今の譜面のまま'] if only else []
    return '\n'.join(['# 報告', '', '- 打点 10', *head, '', '## 決め（珍しい型）', '',
                      *cli._kime_lines(kimes, secs, tempo, proj), '', '## 意思入れ', '', '| 1〜2 | x |'])


def _kime(b0, hand, seq, sec_i=0, placed=4, kind='途切れの前', maps=3):
    return SimpleNamespace(beats=[b0 + k * 0.75 for k in range(len(seq))], seq=seq, placed=placed, sec_i=sec_i, hand=hand,
                           item={'maps': maps, 'freq': '珍しい', 'hard': {'class': 'ふつう'}},
                           place=SimpleNamespace(kind=kind, beat=b0 + 3))


SEQ_R = [(3, 1, 5), (2, 0, 6), (3, 0, 0), (1, 0, 6)]
SEQ_L = [(1, 2, 0), (2, 0, 7), (0, 1, 4), (0, 0, 7)]


def _chart_notes(kimes):
    """決めのとおりに置いた譜面（[秒, x, y, 色, 向き, 拍]）＋ほかの手のノーツ"""
    out = []
    for k in kimes:
        out += [[b * 0.5, x, y, k.hand, d, b] for b, (x, y, d) in zip(k.beats, k.seq)]
        out += [[b * 0.5, 1, 0, 1 - k.hand, 1, b] for b in k.beats]
    return out


def test_parse_kime_matches_report_lines():
    C = _app_check()
    ks = [_kime(33, 0, SEQ_L), _kime(112.75, 1, SEQ_R, sec_i=1, placed=3, kind='区間の変わり目', maps=5)]
    state, got, notes = C.parse_kime(_kime_md(ks))
    assert state == 'ok' and len(got) == 2 and notes[0].startswith('決め 2・決めたとおりに置けたノーツ 7 / 8')
    a, b = got
    assert (a['b0'], a['b1'], a['hand'], a['sec'], a['place'], a['place_beat']) == (33, 35.25, 0, 'サビ1', '途切れの前', 36)
    assert a['seq'] == [list(s) for s in SEQ_L] and a['t'] == pytest.approx(33 * 0.5 + 0.25, abs=0.06)
    assert (b['hand'], b['sec'], b['place'], b['maps'], b['freq'], b['hard'], b['placed'], b['total']) == \
        (1, 'Aメロ2', '区間の変わり目', 5, '珍しい', 'ふつう', 3, 4)
    assert C.parse_kime('# 報告\n\n- 打点 10\n') == ('none', [], [])                  # 決めを入れない曲＝節が無い
    state, got, notes = C.parse_kime(_kime_md([]))                                       # 入れる所が無かった
    assert state == 'ok' and got == [] and notes and '入れる所が無かった' in notes[0]


def test_kime_merge_partial_reports():
    C = _app_check()
    k1, k2, k3 = _kime(33, 0, SEQ_L), _kime(112, 1, SEQ_R), _kime(200, 1, SEQ_R)
    full = _kime_md([k1, k2, k3])
    new = _kime(114, 0, SEQ_L)                                    # 区間 100〜132 だけ作り直した案の決め
    part = _kime_md([new], only=(100, 132))
    assert C.partial_of(part) == (100, 132) and C.partial_of(full) is None
    assert C.partial_of('- 「ここから」（拍 64）より前は結果のファイルのまま残した') == (64, float('inf'))
    notes = _chart_notes([k1, new, k3])
    state, got, _ = C.merge_kimes([part, full], notes)
    assert state == 'ok' and [(k['b0'], k['own']) for k in got] == [(33, False), (114, True), (200, False)]   # 区間の中の前の決め（112）は落とす
    assert not any(k['gone'] for k in got)
    notes2 = [n for n in notes if not (n[3] == 1 and n[5] >= 200)]                      # 外の決め（200）を NLM で消した
    assert [k['b0'] for k in C.merge_kimes([part, full], notes2)[1]] == [33, 114]
    notes3 = [n for n in notes if not (n[3] == 0 and n[5] >= 114 and n[5] < 120)]        # 見ている版の決めは、型どおりでなくても残して gone
    got3 = C.merge_kimes([part, full], notes3)[1]
    assert [(k['b0'], k['gone']) for k in got3] == [(33, False), (114, True), (200, False)]
    assert [k['b0'] for k in C.merge_kimes([full, part], notes)[1]] == [33, 112, 200]   # 全部を作り直した報告はさかのぼらない
