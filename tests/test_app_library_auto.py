"""型のライブラリの時期の「自動」をアプリの側で数える（app/library.py・app/check.py・app/expand.py・app/importer.py・2026-11-03）:
窓の数はその曲の時期で数える（曲が分からなければ年を絞らない）・取り込みの既定は自動・点検と展開も自動を受け付ける。
データベースは使わない（年ごとの曲の数・数える関数は差し替える）"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from automap import library_use as LU

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import library as AL  # noqa: E402
import check as CH  # noqa: E402
import expand as XP  # noqa: E402
import importer as IM  # noqa: E402

COUNTS = {2018: 40, 2019: 30, 2020: 120, 2021: 160, 2022: 110, 2023: 60, 2024: 90, 2025: 50, 2026: 3}
AUTO_F = {'sources': ['ranked'], 'years': 'auto', 'stars': [0, 8], 'diffs': ['Expert', 'ExpertPlus']}


@pytest.fixture
def fake_db(monkeypatch):
    """データベースの代わり: 年ごとの曲の数は COUNTS・数は渡された絞り込みを覚えて返す"""
    seen = []
    monkeypatch.setattr(LU, 'available', lambda path=None: (True, None, {}))
    monkeypatch.setattr(LU, 'year_counts', lambda f, db=None: dict(COUNTS))

    def counts(f, themes=None):
        seen.append(dict(f))
        return {'source': 'db', 'songs': 300, 'hands': 10, 'pairs': 5, 'once': 0, 'themes': 120, 'min': [8, 3]}
    monkeypatch.setattr(LU, 'counts', counts)
    monkeypatch.setattr(LU, 'band_songs', lambda f, bands: [1] * len(bands))
    AL._CACHE.clear()
    yield seen
    AL._CACHE.clear()


def _years(song):
    return LU.auto_years(AUTO_F, song, AL.SEED, counts=COUNTS)


def test_default_is_auto():
    assert LU.DEFAULT['years'] == LU.AUTO
    r = AL.info()
    assert r['default']['years'] == 'auto' and r['default']['auto_v'] == 2 and r['legacy_default']['years'] == [2020, 2026] and r['auto'] == 'auto'


def test_count_uses_the_song_period(fake_db, monkeypatch):
    """窓の数: 時期が自動なら、その曲の時期（compose と同じ resolve・種 1）で数える。答えに曲の時期と説明"""
    r = AL.count({'library': AUTO_F, 'song': '桃源郷'})
    want = _years('桃源郷')
    assert want and r['auto_years'] == want and r['counted']['year_set'] == want and 'auto_years' not in r['counted']
    assert fake_db[-1]['year_set'] == want   # データベースに渡したのはその曲の時期
    assert r['filters']['years'] == 'auto'   # 決める物は自動のまま
    assert r['short'].endswith(f'時期自動（{LU.years_text(want, True)}）')
    assert f'この曲は {LU.years_text(want)} 年' in r['label']
    assert r['year_counts'] == {str(y): n for y, n in COUNTS.items()}   # 年の横に出す数（★を外した数）
    # 結果のファイルから曲の名前（server.song_of）
    monkeypatch.setattr(AL, 'C', SimpleNamespace(out_file=lambda f: Path(f), song_of=lambda p: p.name.split('.')[0]))
    r2 = AL.count({'library': AUTO_F, 'file': '桃源郷.intent-s1.nlmf'})
    assert r2['auto_years'] == want


def test_count_without_song_takes_all_years(fake_db):
    """曲が分からない受け口: 自動のまま＝年を絞らない数"""
    r = AL.count({'library': AUTO_F})
    assert r['auto_years'] is None and 'years' not in r['counted'] and 'years' not in fake_db[-1]
    assert '時期自動' in r['short'] and '（' not in r['short'].split('時期自動')[1]


def test_count_fixed_years_unchanged(fake_db):
    """年を選んだ設定はそのまま数える（曲を渡しても）"""
    f = dict(AUTO_F, years=[2021, 2023])   # 前の形の範囲＝年の一覧に読み替える
    r = AL.count({'library': f, 'song': '桃源郷'})
    assert r['counted']['year_set'] == [2021, 2022, 2023] and r['auto_years'] is None and '時期自動' not in r['short']
    r = AL.count({'library': {k: v for k, v in AUTO_F.items() if k != 'years'} | {'year_set': [2019, 2024]}, 'song': '桃源郷'})
    assert r['counted']['year_set'] == [2019, 2024] and r['short'].endswith('2019・24')


def test_auto_view_when_counts_fail(monkeypatch):
    """年ごとの曲の数を数えられない（データベースが無い等）＝年を絞らない"""
    def boom(f, db=None):
        raise LU.library_db.LibraryError('無い')
    monkeypatch.setattr(LU, 'year_counts', boom)
    AL._CACHE.clear()
    cf, got, shown = AL.auto_view(dict(AUTO_F), '桃源郷')
    assert got is None and 'years' not in cf and shown['years'] == 'auto'
    AL._CACHE.clear()


def test_check_resolves_auto(fake_db):
    """区間の点検: 自動ならこの曲の時期の曲で並びを数える・説明は自動のまま＋時期"""
    f, own, note, shown = CH._filters(dict(AUTO_F, freq='珍しい'), '桃源郷')
    want = _years('桃源郷')
    assert own and f['year_set'] == want and 'freq' not in f and 'auto_years' not in f
    assert shown['years'] == 'auto' and shown['auto_years'] == want
    assert '時期自動' in CH._label(shown, own)
    f2, _, _, _ = CH._filters(dict(AUTO_F), None)   # 曲が分からない＝年を絞らない
    assert 'years' not in f2
    f3, own3, _, shown3 = CH._filters(None, '桃源郷')   # 曲の設定なし＝新しい曲の既定（ランク譜面・時期はこの曲の自動）
    assert not own3 and f3['sources'] == ['ranked'] and shown3['years'] == 'auto' and '時期自動' in CH._label(shown3, own3)


def test_expand_plan_keeps_auto(fake_db, monkeypatch):
    """展開の既定: 年を絞らずに派生の★の帯を決め、その帯でのこの曲の時期でもう一度 derive に数えさせる。派生の型の範囲は時期を
    自動のまま（compose が派生の絞り込みで置き換える）。説明はその曲の時期（compose と同じ）"""
    from automap import derive
    got = []
    by_stars = {6: {2018: 40, 2019: 5, 2020: 100, 2021: 90, 2022: 70, 2023: 30}}   # ★〜6 は年ごとの曲の数が違う＝時期も変わり得る
    monkeypatch.setattr(LU, 'year_counts', lambda f, db=None: dict(by_stars.get((f.get('stars') or [0, 8])[1], COUNTS)))
    AL._CACHE.clear()

    def fake_plan(b, t, lib, step=None):
        got.append(dict(lib))
        return {'ratio': 0.9, 'library': dict(lib, stars=[0, 6]), 'note': '量・型', 'lib_note': '型は★〜6'}
    monkeypatch.setattr(derive, 'default_plan', fake_plan)
    XP._PLANS.clear()
    r = XP.default_plan('ExpertPlus', 'Expert', dict(AUTO_F), step=10, song='桃源郷')
    t_years = LU.auto_years(dict(AUTO_F, stars=[0, 6]), '桃源郷', AL.SEED, counts=by_stars[6], center_counts=COUNTS)   # 中心は★を外した数
    assert 'years' not in got[0] and got[1]['year_set'] == t_years   # 1 回目は年を絞らず・2 回目は派生の帯でのこの曲の時期
    assert r['library']['years'] == 'auto' and r['library']['stars'] == [0, 6] and 'auto_years' not in r['library']
    assert r['auto_years'] == t_years and r['short'].endswith(f'時期自動（{LU.years_text(t_years, True)}）')
    assert f'この★の帯で {LU.years_text(t_years)} 年' in r['note']
    assert 'auto_v' not in r['library']   # 前の決め方の自動は派生も前の決め方
    XP._PLANS.clear()
    r3 = XP.default_plan('ExpertPlus', 'Expert', dict(AUTO_F, auto_v=2), step=10, song='桃源郷')
    assert r3['library']['auto_v'] == 2 and r3['auto_years'] == LU.auto_years(dict(AUTO_F, auto_v=2, stars=[0, 6]), '桃源郷', AL.SEED,
                                                                              counts=by_stars[6], center_counts=COUNTS)
    # 自動でない曲は前のまま（曲の名前は効かない）
    XP._PLANS.clear()
    r2 = XP.default_plan('ExpertPlus', 'Expert', dict(AUTO_F, years=[2020, 2026]), step=10, song='桃源郷')
    assert r2['library']['years'] == [2020, 2026] and 'auto_years' not in r2
    XP._PLANS.clear()


def test_expand_target_accepts_auto():
    """展開の頼みの派生の型の範囲は自動のまま通す（compose へ --library で渡す）"""
    t = XP._norm_target({'diff': 'Hard', 'ratio': 0.8, 'library': dict(AUTO_F)}, 'ExpertPlus')
    assert t['library']['years'] == 'auto'


def test_import_settings_label_has_the_song_period(fake_db):
    """取り込みの基本設定: 自動のまま覚え、説明には取り込む曲の時期"""
    st = IM.settings_of(LU.DEFAULT, '桃源郷')
    want = LU.auto_years(LU.DEFAULT, '桃源郷', AL.SEED, counts=COUNTS)   # 新しい曲の既定＝新しい決め方
    assert st['library']['years'] == 'auto' and st['library']['auto_v'] == 2 and f'この曲は {LU.years_text(want)} 年' in st['label']
    assert IM.settings_of(LU.DEFAULT)['library']['years'] == 'auto'   # 曲が分からなくても自動のまま
