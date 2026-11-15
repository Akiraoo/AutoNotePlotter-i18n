"""量の目安（automap/amount.py・compose --nps-target・作業ファイルの amount）: 目安との比の合わせ方・無い時は変えない・量のラインと区間の量 ±は
合わせた後の量に対する割合・帯の中央値の取り方・アプリの引数と全体の設定の比べ"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from automap import amount, intent, library_db, rhythm
from automap import library_use as LU
from automap import __main__ as cli
from automap.nlmf import TempoMap

pytestmark = pytest.mark.usefixtures('pinned_scale')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
T = TempoMap(120)   # 1拍＝0.5 秒
BARS = [float(b) for b in range(0, 64, 4)]
END = 64.0


def _ons(n=64):
    """候補: キックは毎拍の頭（強）・スネアは半拍の裏（弱め）・ハイハットは 1/4 拍の裏・歌は2拍ごとの 3/4"""
    O = rhythm.Onset
    return {'kick': [O(float(b), float(b), 'kick', 0.8) for b in range(n)],
            'snare': [O(b + 0.5, b + 0.5, 'snare', 0.45) for b in range(n)],
            'hihat': [O(b + q, b + q, 'hihat', 0.5) for b in range(n) for q in (0.25, 0.75)],
            'vocal': [O(b + 0.75, b + 0.75, 'vocal', 0.3, 60.0, 0.25) for b in range(0, n, 2)],
            'other': []}


def _secs(n=64):
    s = rhythm.Section('A', 0, n, vocal=False)
    s.phrases = [(0, n)]
    return [s]


def _hits():
    """自動の打点: 拍 4〜63 の毎拍（片手）・拍 8 と 24 は両手"""
    return [rhythm.Hit(float(b), 2 if b in (8, 24) else 1, 0, 0, 'kick', 0.8) for b in range(4, 64)]


def _gaps_ok(hs):
    bs = sorted(h.beat for h in hs)
    return all(b - a >= amount.GAP_BEAT - 1e-6 for a, b in zip(bs, bs[1:]))


def test_measure_counts_doubles_as_two():
    hs = _hits()
    assert abs(amount.measure(hs, T) - 62 / ((63 - 4) * 0.5)) < 1e-9


def test_fit_up_adds_half_beats_first_and_keeps_doubles():
    """1.5 倍: 目安に近づき、足すのはまず半拍の裏（スネア）。両手はそのまま残り、両手の前後 1/2 拍には足さない"""
    hs = _hits()
    base = amount.measure(hs, T)
    out, info = amount.fit(hs, _ons(), _secs(), BARS, END, base * 1.5, T)
    assert abs(info['after'] - base * 1.5) <= 0.03 * base * 1.5
    assert info['add'] > 0 and info['del'] == 0 and not info['far']
    added = [h for h in out if h not in hs]
    assert added and all(abs(h.beat * 2 - round(h.beat * 2)) < 1e-6 for h in added)   # 半拍の目盛り
    assert [h.beat for h in out if h.hands == 2] == [8.0, 24.0]
    assert not [h for h in added if any(abs(h.beat - d) < 0.5 - 1e-6 for d in (8, 24))]
    assert _gaps_ok(out)
    assert info['ratio'] > 1.3


def test_fit_down_removes_weak_and_keeps_heads():
    """0.6 倍: 弱い打点から減らし、小節の頭・両手・区間の最初は残る"""
    hs = _hits()
    for h in hs:   # 小節の中の打点を少し弱く（減らす順を見る）
        if h.beat % 4 == 3:
            h.s = 0.3
    base = amount.measure(hs, T)
    out, info = amount.fit(hs, _ons(), _secs(), BARS, END, base * 0.6, T)
    assert abs(info['after'] - base * 0.6) <= 0.06 * base * 0.6
    assert info['del'] > 0 and info['add'] == 0
    bs = {h.beat for h in out}
    assert all(b in bs for b in BARS if b >= 4) and {8.0, 24.0} <= bs and 4.0 in bs
    gone = [h for h in hs if h.beat not in bs]
    assert sum(h.beat % 4 == 3 for h in gone) >= len(gone) // 2   # 弱い物から


def test_no_target_changes_nothing():
    """目安が無い＝打点はそのまま（compose の _fit_amount も同じ物を返す）・今と同じ量の目安＝足し減らし無し"""
    hs = _hits()
    out, info = amount.fit(hs, _ons(), _secs(), BARS, END, None, T)
    assert out is hs and info['add'] == info['del'] == 0
    a = SimpleNamespace(nps_target=None, nps_from=None)
    out2, inf2, sc = cli._fit_amount(a, hs, _ons(), _secs(), BARS, END, T)
    assert out2 is hs and inf2 is None and sc is None
    out3, info3 = amount.fit(hs, _ons(), _secs(), BARS, END, amount.measure(hs, T), T)
    assert [(h.beat, h.hands) for h in out3] == [(h.beat, h.hands) for h in hs] and info3['add'] == info3['del'] == 0


def test_fit_far_target_reports_shortfall():
    """拾える打点が足りない時は届かないまま一番近い物にし、報告に「目安 x に対して y」"""
    hs = _hits()
    base = amount.measure(hs, T)
    out, info = amount.fit(hs, _ons(), _secs(), BARS, END, base * 8, T)
    assert info['far'] and info['after'] < base * 8 and info['short'] > 0
    assert _gaps_ok(out)
    line = amount.report_line(info, '直接')
    assert '目安' in line and 'に対して' in line


def test_line_is_relative_to_fitted_amount():
    """量のライン 0.5 は、目安で合わせた後の小節の打点の数の半分ほど（元の数の半分ではない）"""
    hs = _hits()
    base = amount.measure(hs, T)
    fit, _ = amount.fit(hs, _ons(), _secs(), BARS, END, base * 1.5, T)
    n_fit = len([h for h in fit if 32 <= h.beat < 48])
    it = {'ranges': [], 'line': [{'b': 0, 'k': 0.5}, {'b': 64, 'k': 0.5}], 'auto_rest': {'on': False, 'b': None}}
    out, _ = intent.apply(fit, _ons(), _secs(), it, BARS, int(END))
    n = len([h for h in out if 32 <= h.beat < 48])
    assert abs(n - n_fit * 0.5) <= 2 and n > 8 * 0.5


def test_range_amount_scaled_by_fit_ratio():
    """区間の量 ±（選び直し）にも、目安で合わせた倍率が掛かる（scale が無ければ今のまま）"""
    hs = _hits()
    it = {'ranges': [{'b0': 16, 'b1': 32, 'set': {'amount': -1}}], 'line': [], 'auto_rest': {'on': False, 'b': None}}
    plain, _ = intent.apply(list(hs), _ons(), _secs(), it, BARS, int(END))
    sc = amount.make_scale(_ons(), _secs(), BARS, END, T, 1.6)
    up, rep = intent.apply(list(hs), _ons(), _secs(), it, BARS, int(END), scale=sc)
    cnt = lambda xs: len([h for h in xs if 16 <= h.beat < 32])
    assert cnt(up) > cnt(plain)
    assert [h.beat for h in up if not 16 <= h.beat < 32] == [h.beat for h in plain if not 16 <= h.beat < 32]
    assert any('量の目安の倍率' in d for r in rep for d in r[3])
    assert amount.make_scale(_ons(), _secs(), BARS, END, T, 1.0) is None


def test_amount_of_and_band_nps_fallback(monkeypatch):
    """作業ファイルの amount の整え方と、データベースが使えない時の帯の中央値（参考の値・帯の真ん中で線でつなぐ）"""
    assert LU.amount_of(None) is None and LU.amount_of({'mode': 'auto'}) is None
    assert LU.amount_of({'mode': 'band', 'stars': [8, 6]}) == {'mode': 'band', 'stars': [6, 8]}
    assert LU.amount_of({'mode': 'nps', 'nps': 5.555}) == {'mode': 'nps', 'nps': 5.55}
    assert LU.amount_of({'mode': 'nps', 'nps': 40}) is None and LU.amount_of({'mode': 'nps', 'nps': True}) is None

    def boom(*a, **k):
        raise library_db.LibraryError('無い')
    monkeypatch.setattr(library_db, 'diff_stats', boom)
    assert LU.band_nps([6, 8]) == (LU.NPS_REF[(6, 8)], None)
    v, _ = LU.band_nps([0, 6])   # 帯の真ん中 3 → ★〜4（2）と 4〜6（5）の間
    assert LU.NPS_REF[(0, 4)] < v < LU.NPS_REF[(4, 6)]
    t = LU.amount_target({'mode': 'band', 'stars': [6, 8]})
    assert t[0] == LU.NPS_REF[(6, 8)] and '★6〜8' in t[1] and '参考' in t[1]
    assert LU.amount_target({'mode': 'nps', 'nps': 5.5}) == (5.5, '曲の設定で直接')


def test_app_amount_extra_and_settings(monkeypatch):
    """アプリ: 作業ファイルの amount → compose の --nps-target・--nps-from（無い・自動は何も足さない）。前の譜面に寄せる時の
    「全体の設定」の比べ（自動は無いのと同じ・変えたら違う）"""
    import library as applib
    import versions
    assert applib.amount_extra(None, {}) == [] and applib.amount_extra(None, {'amount': {'mode': 'auto'}}) == []
    ex = applib.amount_extra(None, {'amount': {'mode': 'nps', 'nps': 5.5}})
    assert ex[:2] == ['--nps-target', '5.5'] and ex[2] == '--nps-from'
    s0 = versions._settings({'ranges': [], 'line': []})
    assert versions._settings({'ranges': [], 'amount': {'mode': 'auto'}}) == s0
    assert versions._settings({'amount': {'mode': 'band', 'stars': [6, 8]}}) != s0
    assert versions._settings({'amount': {'mode': 'band', 'stars': [6, 8]}}) != versions._settings({'amount': {'mode': 'band', 'stars': [8, 10]}})
