"""選んだ区間だけ作り直す時の流れの計算を区間の前後だけで行う（automap/window.py・compose --only・docs/アプリ仕様.md 9 節）:
- 窓の決め方（区間の前後 MARGIN 拍・後ろから前を見る印の相手まで前へ・残したノーツでない打点は全部入れる）
- 窓の外の答えは残したノーツそのもの（決めた置き方）・窓の頭は前の残したノーツの振りを引き継ぐ
- compose を通して: 区間の外は結果のファイルのまま・つなぎ目で振りの向きが続く（NLM の振りの警告と同じ決まりが全部で計算した時より
  増えない）・--only が無い時は窓を使わない（答えは前と同じ）
作り物の曲は tests/test_compose_regen.py と同じ物（同じ一時フォルダを使い回す）"""
import pytest

from automap import __main__ as cli
from automap import flow, nlmf, rhythm, stats, window
from test_compose_regen import EMPTY, EP, NAME, _notes, _run, _table, _work, song  # noqa: F401（song はフィクスチャ）


def _ev(b, kept=True, fix=None, **marks):
    """拍 b の片手の打点（左右を交互に・手ごとに振り下ろしと振り上げを交互）。kept なら残したノーツ（決めた置き方・重み KEPT_FIX_W）"""
    e = flow.Event(b, b * 0.5, 1)
    if kept:
        c, down = int(b) % 2, (int(b) // 2) % 2 == 0
        e.fix, e.fix_w = fix or {c: (1 + c, 0 if down else 2, 1 if down else 0)}, cli.KEPT_FIX_W
    for k, v in marks.items():
        setattr(e, k, v)
    return e


def _hit(ev, kept):
    h = rhythm.Hit(ev.beat, ev.hands, 0, 0, 'kept' if kept else 'drum', 1.0)
    if kept:
        h.kept, h.fix = True, ev.fix
    return h


def _song_events(region=(24, 40), marks=None):
    """拍 0〜63 に 1 拍ごとの打点。区間の外は残したノーツ（右左を交互に・振りも交互の置き方）"""
    marks = marks or {}
    evs = []
    for i in range(64):
        kept = not region[0] <= i < region[1]
        evs.append(_ev(float(i), kept, **marks.get(i, {})))
    return evs


def test_bounds_margin_and_back_references():
    evs = _song_events()
    kept = [bool(e.fix) for e in evs]
    i0, i1 = window.bounds(evs, kept, (24, 40), 8)
    assert (evs[i0].beat, evs[i1 - 1].beat) == (16, 47)
    # 後ろから前を見る印の相手が窓の前にあれば、そこまで前へ（続けて左右反転・短い往復・受け渡しの反転・前のセットを片手に）
    for marks, b in (({30: {'echo': 16.0}}, 14), ({26: {'loop': 10.0}}, 10), ({33: {'hoflex': (5.0, 2)}}, 5), ({25: {'erun': 3.0}}, 3)):
        evs = _song_events(marks=marks)
        i0, _ = window.bounds(evs, [bool(e.fix) for e in evs], (24, 40), 8)
        assert evs[i0].beat == b, marks
    # 残したノーツの印は窓を広げない（決めた置き方のまま）
    evs = _song_events(marks={12: {'echo': 8.0}})
    assert evs[window.bounds(evs, [bool(e.fix) for e in evs], (24, 40), 8)[0]].beat == 16
    # 残したノーツでない打点が区間の外にあれば（起こらないはずだが）窓に入れる
    evs = _song_events()
    kept = [bool(e.fix) for e in evs]
    kept[60] = False
    i0, i1 = window.bounds(evs, kept, (24, 40), 8)
    assert evs[i1 - 1].beat == 60


def test_generate_outside_is_the_kept_notes_and_only_the_window_is_computed(monkeypatch):
    evs = _song_events()
    hits = [_hit(e, bool(e.fix)) for e in evs]
    calls = []
    orig = flow.generate

    def spy(events, style=None, init=None):
        calls.append((len(events), init))
        return orig(events, style, init)
    monkeypatch.setattr(flow, 'generate', spy)
    tm = nlmf.TempoMap(120)
    st = flow.Style(beam=8, seed=1)
    gen, cost, span = window.generate(evs, hits, st, (24, 40), tm, margin=8)
    assert span == (16, 47) and calls[0][0] == 32
    # 窓の頭は前の残したノーツの最後の振りから（flow.init_from）
    assert calls[0][1] == flow.init_from([{'beat': e.beat, 'x': x, 'y': y, 'c': c, 'd': d}
                                          for e in evs[:16] for c, (x, y, d) in e.fix.items()], tm)
    at = {(n['beat'], n['c']): (n['x'], n['y'], n['d']) for n in gen}
    assert len(gen) == len(evs) and [n['beat'] for n in gen] == [e.beat for e in evs]
    for e in evs:
        if not 16 <= e.beat < 48:   # 窓の外は決めた置き方そのもの
            assert {c: at[(e.beat, c)] for c in e.fix} == e.fix
    # 区間の前後の残したノーツ（重い決めたノーツ）は窓の中でも決めた置き方に置かれ、区間の中は振りが交互に続く
    for e in evs[16:48]:
        if e.fix:
            assert {c: at.get((e.beat, c)) for c in e.fix} == e.fix
    for c in (0, 1):
        pars = [flow.parity_of(c, at[(b, c)][2]) for b in sorted(b for b, cc in at if cc == c)]
        assert all(a != b for a, b in zip(pars, pars[1:]))
    # 曲の頭の区間: 窓の頭は曲の頭＝渡した始まり（「ここから」の init）をそのまま使う
    calls.clear()
    window.generate(evs[24:], hits[24:], st, (24, 40), tm, init=(flow.NO_HAND, flow.NO_HAND, -1), margin=8)
    assert calls[0][1] == (flow.NO_HAND, flow.NO_HAND, -1)


# ---- compose を通して（作り物の曲・64 拍） ----

REGION = (24.0, 40.0)


@pytest.fixture
def first(song, tmp_path, monkeypatch):
    return _work(song / 'first' / f'{NAME}.intent-s1.nlmf', tmp_path, monkeypatch)


def _seam_warns(ns, o0, o1):
    """NLM の振りの警告と同じ決まり（stats の nlm_swing）のうち、区間の境目をまたぐ組の数"""
    n = 0
    for c in (0, 1):
        hs = [x for x in ns if x[3] == c and x[4] != 8]
        for a, b in zip(hs, hs[1:]):
            if b[0] - a[0] >= 0.2 and stats._dir_diff(a[4], b[4]) <= 45 and (o0 - 1e-6 <= a[0] < o1 - 1e-6) != (o0 - 1e-6 <= b[0] < o1 - 1e-6):
                n += 1
    return n


def _only(song, d, out, full, monkeypatch):
    calls = []
    orig = flow.generate

    def spy(events, style=None, init=None):
        calls.append(len(events))
        return orig(events, style, init)
    monkeypatch.setattr(flow, 'generate', spy)
    if full:
        monkeypatch.setenv('AUTOMAP_ONLY_FULL', '1')
    else:
        monkeypatch.delenv('AUTOMAP_ONLY_FULL', raising=False)
    t0 = _table(d, 'prev', EMPTY)
    rep = _run(song, out, out, t0, '--prev-intent', str(t0), '--only', f'{REGION[0]:g},{REGION[1]:g}')
    monkeypatch.setattr(flow, 'generate', orig)
    return _notes(out), rep, calls


def test_compose_only_window_keeps_outside_and_the_seams(song, first, tmp_path, monkeypatch):
    d, out = first
    before = _notes(out)
    o0, o1 = REGION
    outside = lambda ns: [n for n in ns if not o0 - 1e-6 <= n[0] < o1 - 1e-6]
    inside = lambda ns: [n for n in ns if o0 - 1e-6 <= n[0] < o1 - 1e-6]
    got, rep, calls = _only(song, d, out, False, monkeypatch)
    assert outside(got) == outside(before) and inside(got)                       # 外は 1 つも変わらない・区間の中は作った
    total = len({(n[0]) for n in before})
    assert calls and max(calls) < total                                           # 流れの計算は窓だけ（どの呼び出しも）
    assert '流れの計算は区間の前後（拍 ' in rep
    for c in (0, 1):   # つなぎ目で振りの向きが続く（境目をまたぐ同じ手の 2 つが同じ向きにならない）
        hs = [n for n in got if n[3] == c and n[4] != 8]
        for a, b in zip(hs, hs[1:]):
            if (a[0] < o0 <= b[0]) or (a[0] < o1 <= b[0]):
                assert flow.parity_of(c, a[4]) != flow.parity_of(c, b[4]), (c, a, b)
    # 全部で計算した時（AUTOMAP_ONLY_FULL=1・前の作り）と比べる: 外は同じ・つなぎ目の警告は増えない
    d2 = tmp_path / 'full'
    d2.mkdir()
    _, out2 = _work(song / 'first' / f'{NAME}.intent-s1.nlmf', d2, monkeypatch)
    ref, rep2, calls2 = _only(song, d2, out2, True, monkeypatch)
    assert outside(ref) == outside(before) and set(calls2) == {total}
    assert '流れの計算は区間の前後' not in rep2
    assert _seam_warns(got, o0, o1) <= _seam_warns(ref, o0, o1)


def test_compose_without_only_does_not_use_the_window(song, first, monkeypatch):
    """--only が無い作り直しは窓を使わない（流れの計算は曲の全部の打点で・前と同じ答え）"""
    d, out = first

    def boom(*a, **k):
        raise AssertionError('--only が無いのに窓を使った')
    monkeypatch.setattr(window, 'generate', boom)
    t0 = _table(d, 'prev', EMPTY)
    rep = _run(song, out, out, t0, '--prev-intent', str(t0))
    assert '前の譜面に寄せた' in rep
