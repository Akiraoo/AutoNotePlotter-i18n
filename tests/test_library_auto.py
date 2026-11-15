"""型のライブラリの時期の「自動」（automap/library_use・2026-11-03・docs/方針.md 6.24）: 曲ごとに手本の時期を決める。
データベースは使わない（年ごとの曲の数を渡す・書き出しは library_db を差し替える）"""
import pytest

from automap import library_db
from automap import library_use as LU

COUNTS = {2018: 40, 2019: 30, 2020: 120, 2021: 160, 2022: 110, 2023: 60, 2024: 90, 2025: 50, 2026: 3}


def test_normalize_keeps_auto_and_default_is_auto():
    """自動は決め方の版（auto_v）ごと残す・前の範囲 [から, まで] は年の一覧（year_set）に・選んだ年は小さい順に重なり無しで"""
    old = LU.normalize({'sources': ['ranked'], 'years': 'auto'})
    assert old['years'] == 'auto' and 'auto_v' not in old                      # 前の決め方（印無し）はそのまま
    assert LU.normalize({'years': 'auto', 'auto_v': 2})['auto_v'] == 2
    assert LU.normalize({'years': [2023, 2021]}) == {'sources': ['ranked'], 'year_set': [2021, 2022, 2023], 'diffs': ['Expert', 'ExpertPlus']}
    assert LU.normalize({'year_set': [2024, '2019', 2024, 2021.0]})['year_set'] == [2019, 2021, 2024]
    assert 'year_set' not in LU.normalize({'year_set': []})                       # どれも選ばない＝全部の年
    for bad in (['x'], [True], [1999.5], 2021):
        with pytest.raises(ValueError):
            LU.normalize({'year_set': bad})
    assert LU.DEFAULT['years'] == LU.AUTO and LU.DEFAULT['auto_v'] == LU.AUTO_V and LU.normalize(LU.DEFAULT)['auto_v'] == 2
    assert 'auto_v' not in LU.DEFAULT_V1 and LU.DEFAULT_V1['years'] == LU.AUTO


def test_auto_years_window():
    """中心の年は曲の名前と種で決まる（同じなら同じ）・曲が AUTO_SONGS 以上になるまで曲の多い隣の年へ広げる・曲の少ない年（2026）は中心にしない"""
    f = {'sources': ['ranked'], 'years': 'auto'}
    got = {s: LU.auto_years(f, s, counts=COUNTS) for s in ('曲A', '曲B', '曲C', '曲D', '曲E', '曲F', '曲G', '曲H')}
    assert got['曲A'] == LU.auto_years(f, '曲A', counts=COUNTS)
    assert LU.auto_years(f, '曲A', seed=2, counts=COUNTS) is not None
    for ys in got.values():
        lo, hi = ys[0], ys[-1]
        assert 2018 <= lo <= hi <= 2026 and ys == list(range(lo, hi + 1))   # 前の決め方＝つながった年
        assert sum(COUNTS[y] for y in ys) >= LU.AUTO_SONGS
    assert len({tuple(v) for v in got.values()}) >= 3   # 曲ごとに散る
    assert LU.auto_years(f, '曲A', counts={}) is None
    assert LU.auto_years(f, '曲A', counts={2020: 5}) is None   # 中心にできる年が無い


def test_auto_years_v2_scatter():
    """新しい決め方（auto_v 2・2026-11-15 利用者「歯抜けの年を持たせたり…ランダム性を少し上げたい」）: 中心の年は前の決め方と同じ・
    ほかの年は曲ごとに決まった順で足す（離れた年も入る）・曲が AUTO_SONGS 以上・曲が AUTO_PICK_MIN より少ない年は足さない・
    曲どうしで年の組が散る（前の決め方より多くの組）・同じ曲と種なら同じ"""
    f2, f1 = {'years': 'auto', 'auto_v': 2}, {'years': 'auto'}
    c2 = dict(COUNTS)
    c2[2026] = LU.AUTO_PICK_MIN - 1   # 曲がとても少ない年
    songs = [f'曲{i}' for i in range(60)]
    v2 = {s: LU.auto_years(f2, s, counts=c2) for s in songs}
    v1 = {s: LU.auto_years(f1, s, counts=c2) for s in songs}
    for s, ys in v2.items():
        assert ys == sorted(set(ys)) and sum(c2[y] for y in ys) >= LU.AUTO_SONGS
        assert 2026 not in ys                                       # 曲がとても少ない年は足さない（中心にもならない）
        assert set(ys) & set(v1[s])                                 # 中心の年は前の決め方と同じ
        assert ys == LU.auto_years(f2, s, counts=c2)
    assert len({tuple(v) for v in v2.values()}) > len({tuple(v) for v in v1.values()})   # 前より散る
    assert any(v != list(range(v[0], v[-1] + 1)) for v in v2.values())                  # 歯抜けの組がある
    assert LU.auto_years(f2, '曲0', seed=2, counts=c2) is not None
    assert LU.auto_years(f2, '曲0', counts={}) is None


def test_resolve(monkeypatch):
    monkeypatch.setattr(LU, 'year_counts', lambda f, db=None: dict(COUNTS))
    r = LU.resolve({'sources': ['ranked'], 'years': 'auto', 'stars': [0, 8]}, '曲A')
    assert r['year_set'] == r['auto_years'] == LU.auto_years({}, '曲A', counts=COUNTS) and r['stars'] == [0, 8] and 'years' not in r
    r2 = LU.resolve({'sources': ['ranked'], 'years': 'auto', 'auto_v': 2, 'stars': [0, 8]}, '曲A')
    assert r2['year_set'] == r2['auto_years'] == LU.auto_years({'auto_v': 2}, '曲A', counts=COUNTS) and r2['auto_v'] == 2
    fixed = {'sources': ['ranked'], 'year_set': [2020, 2022]}
    assert LU.resolve(fixed, '曲A') == fixed and LU.resolve(None, '曲A') is None

    def boom(f, db=None):
        raise library_db.LibraryError('データベースが無い')
    monkeypatch.setattr(LU, 'year_counts', boom)
    assert 'years' not in LU.resolve({'years': 'auto'}, '曲A')   # 数えられない＝年を絞らない
    assert not {'years', 'auto_v', 'year_set'} & set(LU.resolve({'years': 'auto', 'auto_v': 2}, '曲A'))


def test_concrete_and_label():
    assert LU.concrete({'years': 'auto', 'auto_v': 2, 'stars': [0, 8]}) == {'stars': [0, 8]}
    assert LU.concrete({'year_set': [2021, 2023], 'auto_years': [2021, 2023], 'auto_v': 2}) == {'year_set': [2021, 2023]}
    assert '時期自動' in LU.label({'sources': ['ranked'], 'years': 'auto', 'stars': [0, 8]}, True)
    long = LU.label({'sources': ['ranked'], 'year_set': [2021, 2022, 2023], 'auto_years': [2021, 2022, 2023], 'stars': [0, 8]})
    assert '2021〜2023 年' in long and '前の決め方' in long
    new = LU.label({'sources': ['ranked'], 'year_set': [2019, 2021, 2022, 2025], 'auto_years': [2019, 2021, 2022, 2025], 'auto_v': 2})
    assert 'この曲は 2019・2021〜2022・2025 年' in new and '前の決め方' not in new
    assert LU.label({'sources': ['ranked'], 'year_set': [2019, 2021, 2022, 2023]}, True).endswith('2019・21〜23')
    assert '2019・2021〜2023 年' in LU.label({'sources': ['ranked'], 'year_set': [2019, 2021, 2022, 2023]})
    assert '2020〜2022 年' in LU.label({'sources': ['ranked'], 'years': [2020, 2022]})   # 前の形の範囲も読める
    assert LU.years_text([2024, 2019, 2020]) == '2019〜2020・2024' and LU.years_text([2019, 2020, 2024], True) == '2019〜20・24'
    assert '時期は曲ごとに自動' in LU.label({'sources': ['ranked'], 'years': 'auto', 'stars': [0, 8]})


def test_export_unresolved_auto_takes_all_years(monkeypatch):
    """resolve していない自動のまま来たら年を絞らない（データベースの読み口には年の文字が渡らない）・説明は自動のまま"""
    seen = {}

    def fake_export(f, out_path=None, db=None):
        seen['f'] = dict(f)
        return {'songs': 300, 'hands': [], 'pairs': [], 'library': {'filters': dict(f)}}
    monkeypatch.setattr(library_db, 'export_themes', fake_export)
    monkeypatch.setattr(library_db, 'diff_stats', lambda f, db=None: {})
    from automap import theme
    monkeypatch.setattr(theme, 'load_themes', lambda lib, *a, **k: [None] * 50)
    lib = LU.export({'sources': ['ranked'], 'years': 'auto', 'stars': [0, 8]})
    assert 'years' not in seen['f'] and lib['library']['filters']['years'] == LU.AUTO
    lib = LU.export({'sources': ['ranked'], 'year_set': [2021, 2023], 'auto_years': [2021, 2023], 'auto_v': 2})
    assert seen['f']['year_set'] == [2021, 2023] and not {'auto_years', 'auto_v'} & set(seen['f'])
    L = lib['library']['filters']
    assert L['auto_years'] == [2021, 2023] and L['years'] == LU.AUTO and L['auto_v'] == 2 and 'year_set' not in L


def test_select_ignores_text_years():
    """データベースの読み口は、年が [下, 上] でない（自動の文字のまま）なら年を絞らない＝落ちない"""
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(':memory:')) as con:   # 閉じる（with だけの sqlite3 は閉じない＝ResourceWarning）
        con.execute('CREATE TABLE diffs (id, map_id, difficulty, missing, mods, bpm_change, notes, err, bl_ranked, stars, star_approx, pos, stats, characteristic)')
        con.execute('CREATE TABLE maps (id, place, hash, ord, bpm, year, mappers, v4, err, on_beatsaver, own)')
        con.execute("INSERT INTO maps VALUES (1, 'bl', 'h', 0, 120, 2018, '[]', 0, NULL, 1, 0)")
        con.execute("INSERT INTO diffs VALUES (1, 1, 'ExpertPlus', 0, 0, 0, 500, NULL, 1, 5.0, 0, 0, '{}', 'Standard')")
        assert list(library_db._select(con, {'sources': ['ranked'], 'years': 'auto'})) == [1]
        assert list(library_db._select(con, {'sources': ['ranked'], 'years': [2020, 2026]})) == []
        assert list(library_db._select(con, {'sources': ['ranked'], 'year_set': [2016, 2018]})) == [1]   # 選んだ年の一覧（歯抜け）
        assert list(library_db._select(con, {'sources': ['ranked'], 'year_set': [2017, 2019]})) == []
        assert list(library_db._select(con, {'sources': ['ranked'], 'year_set': [2018], 'years': [2020, 2026]})) == [1]   # 一覧が先


def test_center_year_does_not_depend_on_stars(monkeypatch):
    """同じ曲は★の帯（難易度の展開の派生）が違っても中心の年が同じ（中心は★を外した曲の数から選ぶ・広げ方だけ★の帯の数）。
    前は★で絞った数から選び、こだまの Expert+（★〜8）が 2023〜26・Expert（★〜6）が 2018〜22 になった"""
    low = {2018: 30, 2019: 12, 2020: 40, 2021: 50, 2022: 30, 2023: 20, 2024: 12, 2025: 11}

    def fake(f, db=None):
        return dict(low) if f.get('stars') == [0, 4] else dict(COUNTS)
    monkeypatch.setattr(LU, 'year_counts', fake)
    base = {'sources': ['ranked'], 'years': 'auto'}
    for song in ('曲A', '曲B', '曲C', '曲D', '曲E'):
        hi_ = LU.resolve(dict(base, stars=[0, 8]), song)['auto_years']
        lo_ = LU.resolve(dict(base, stars=[0, 4]), song)['auto_years']
        c = LU.auto_years(base, song, counts=COUNTS, center_counts=COUNTS)
        assert hi_ == c
        assert set(hi_) & set(lo_)   # 同じ中心の年を含む
        h2 = LU.resolve(dict(base, auto_v=2, stars=[0, 8]), song)['auto_years']
        l2 = LU.resolve(dict(base, auto_v=2, stars=[0, 4]), song)['auto_years']
        assert set(h2) & set(l2)     # 新しい決め方も
