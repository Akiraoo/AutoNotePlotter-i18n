"""曲ごとのライブラリの設定（automap/library_use.py・automap/library_setting.py・app/library.py）: 設定の無い曲・前の形の設定の
読み替え（ランク譜面）・しきい値・曲の個性の目標・データベースが無い時は止める・compose に渡す引数"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from automap import library_db, library_use as LU, style, theme

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import library as app_library  # noqa: E402
import test_library_db as T  # noqa: E402
from test_library_db import lib  # noqa: E402,F401  （作り物の譜面のデータベース）

pytestmark = pytest.mark.usefixtures('pinned_scale')
R4 =[[1, 0, 1], [2, 2, 0], [1, 0, 6], [2, 2, 5]]   # 右手の形の4振り（振り下ろし・振り上げが交互）


def _themes(songs=899, maps=(2, 3, 5, 8), library=None):
    """作り物の型（型のデータベースの書き出し library_db.export_themes と同じ形）。maps ごとに片手の型と両手の組を1つずつ"""
    hands, pairs = [], []
    for i, m in enumerate(maps):
        cyc = [[x, y, d] for x, y, d in R4]
        cyc[0][0] = i % 4
        hands.append({'cycle': cyc, 'maps': m})
        pairs.append({'a': cyc, 'b': [[3 - x, y, d] for x, y, d in cyc], 'maps': m})
    d = {'songs': songs, 'ranks': ['Expert', 'ExpertPlus'], 'hands': hands, 'pairs': pairs}
    if library is not None:
        d['library'] = library
    return d


def _old_load(d):
    """前の load_themes（片手の型は 8 曲以上・両手の組は 3 曲以上）"""
    out = [(tuple(map(tuple, q['a'])), tuple(map(tuple, q['b']))) for q in d['pairs'] if q['maps'] >= 3]
    out += [(tuple(map(tuple, h['cycle'])),) * 2 for h in d['hands'] if len(h['cycle']) >= 4 and h['maps'] >= 8]
    seen, uniq = set(), []
    for k in out:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def test_threshold_without_library_item():
    """library の項目が無い型（作り物）は前と同じ 8・3＝同じ型の並び"""
    d = _themes()
    assert theme.thresholds(d) == (8, 3)
    assert [t.key() for t in theme.load_themes(d)] == _old_load(d)


def test_thresholds_follow_songs_and_freq():
    """データベースの書き出しは曲の数に合わせた同じ割合・「珍しい」は少ない曲の型まで・引数で広げられる"""
    lib = {'filters': {'sources': ['ranked']}}
    assert theme.thresholds(_themes(512, library=lib)) == (5, 2)
    assert theme.thresholds(_themes(899, library=lib)) == (8, 3)
    assert theme.thresholds(_themes(100, library=lib)) == (3, 2)
    rare = _themes(512, library={'filters': {'freq': '珍しい'}})
    assert theme.thresholds(rare) == theme.RARE_MIN
    assert len(theme.load_themes(rare)) > len(theme.load_themes(_themes(512, library=lib)))
    d = _themes()   # library の項目が無い型でも、区間ごとに広げる時は引数で
    assert theme.thresholds(d, freq='珍しい') == theme.RARE_MIN
    wide = theme.load_themes(d, hand_min=2, pair_min=2)
    assert {t.maps for t in wide} == {2, 3, 5, 8}
    assert {t.maps for t in theme.load_themes(d)} == {3, 5, 8}


def test_targets_same_without_library():
    """曲の個性の目標は、library.stats の無い型はライブラリでずらさない: 段・斜めは前と同じ式・同じ数。
    列（2026-11-03 から）はランク譜面のふつう（style.rank_spread）＋曲の個性の自分の外 ±0.03（その分を自分の内から）・wide ±0.03・
    col は hcol の左右の平均"""
    from automap.flow import LIBRARY_EPLUS
    for t in ({'outer': 0.3, 'diag': -0.5, 'row': 0.2, 'move': 0.1}, {'outer': -1, 'diag': 1, 'row': -1, 'move': 0}):
        g = float(np.clip(0.45 + 0.25 * t['diag'], 0.15, 0.75))
        top = float(np.clip(0.20 + 0.08 * t['row'], 0.08, 0.32))
        hcol, wide = style.rank_spread(None)
        hcol = (hcol[0], hcol[1], hcol[2] - 0.03 * t['outer'], hcol[3] + 0.03 * t['outer'])
        for lib in (None, _themes(), _themes(library={'filters': {}})):
            tg = style.targets(t, lib=lib)
            assert tg['dir'] == (1 - g - 0.02, g, 0.02) and tg['row'] == (0.42, 0.58 - top, top)
            assert {k: tg[k] for k in LIBRARY_EPLUS if k not in ('dir', 'row', 'col')} == {k: v for k, v in LIBRARY_EPLUS.items()
                                                                                          if k not in ('dir', 'row', 'col')}
            assert tg['hcol'] == pytest.approx(hcol) and tg['wide'] == pytest.approx(wide + 0.03 * t['outer'])
            assert tg['col'] == pytest.approx(tuple((hcol[x] + hcol[3 - x]) / 2 for x in range(4)))
            assert tg == style.targets(t)


def test_targets_follow_library_stats():
    """データベースの書き出しは、選んだ譜面の割合と手元の譜面（LIB_REF）の差だけ中心をずらす。外側は自分の外に ±0.03 まで
    （2026-11-03 から・その分を自分の内から引く＝外側の列 col[0]＋col[3] は +0.04 でなく +0.03）"""
    t = {'outer': 0.0, 'diag': 0.0, 'row': 0.0, 'move': 0.0}
    base = style.targets(t)
    st = {'outer': style.LIB_REF['outer'] + 0.04, 'diag': style.LIB_REF['diag'] + 0.03, 'top': style.LIB_REF['top'] + 0.05,
          'bottom': style.LIB_REF['bottom'] - 0.02}
    tg = style.targets(t, lib=_themes(library={'filters': {}, 'stats': st}))
    assert tg['col'][0] * 2 == pytest.approx(base['col'][0] * 2 + 0.03)
    assert tg['hcol'][3] == pytest.approx(base['hcol'][3] + 0.03) and tg['hcol'][2] == pytest.approx(base['hcol'][2] - 0.03)
    assert tg['wide'] == pytest.approx(base['wide'])
    st2 = dict(st, outer=style.LIB_REF['outer'] + 0.02)   # 上限より小さいずらしはそのまま
    assert style.targets(t, lib=_themes(library={'filters': {}, 'stats': st2}))['hcol'][3] == pytest.approx(base['hcol'][3] + 0.02)
    assert tg['dir'][1] == pytest.approx(base['dir'][1] + 0.03)
    assert tg['row'][2] == pytest.approx(base['row'][2] + 0.05)
    assert tg['row'][0] == pytest.approx(0.40)
    assert sum(tg['row']) == pytest.approx(1.0)


def test_normalize_and_label():
    assert LU.normalize(None) == LU.DEFAULT and LU.normalize({}) == LU.DEFAULT   # 設定の無い曲＝新しい曲の既定（前は今の型）
    assert LU.normalize(LU.DEFAULT) == LU.DEFAULT
    f = LU.normalize({'sources': ['local', 'ranked', 'x'], 'stars': [8, 4], 'freq': '珍しい', 'hard': '難しい', 'zzz': 1,
                      'include_own': True, 'on_beatsaver': True, 'approx': False})
    assert f['sources'] == ['ranked'] and f['stars'] == [4, 8] and f['freq'] == '珍しい' and 'hard' not in f   # 出どころはランク譜面に固定
    assert 'zzz' not in f and 'include_own' not in f and 'on_beatsaver' not in f and f['approx'] is False and f['diffs'] == ['Expert', 'ExpertPlus']
    assert LU.label(LU.DEFAULT, short=True) == 'ランク ★〜8 時期自動'   # 新しい曲の既定は時期が自動（2026-11-03）
    assert LU.label(None, short=True) == LU.label(LU.DEFAULT, short=True)
    assert 'ランク譜面' in LU.label(LU.DEFAULT) and '時期は曲ごとに自動' in LU.label(LU.DEFAULT)
    assert '2020〜2026 年' in LU.label(LU.LEGACY_DEFAULT)


def test_compose_extra():
    """compose にはいつも --library（作業ファイルに library が無ければ新しい曲の既定＝前の今の型は除いた）"""
    for w in ({'ranges': []}, {'library': None}, {'library': LU.DEFAULT}):
        a = app_library.compose_extra(None, w)
        assert a[0] == '--library' and LU.filters_of(a[1]) == LU.DEFAULT


def test_migrate_old_settings():
    """前の形の設定の読み替え（2026-11-09）: 設定の無い曲は新しい曲の既定・出どころに手元の譜面（両方・出どころ無しも）はランク譜面だけに
    （手元の譜面だけの印も外す）・ランク譜面だけの設定は同じ物（今の曲の答えを変えない）"""
    from automap import library_setting as LS
    assert LS.migrate_filters(None) == LU.DEFAULT_V1 and LS.migrate_filters(None) is not LU.DEFAULT_V1   # 前からある曲＝前の決め方の自動
    ranked = {'sources': ['ranked'], 'years': 'auto', 'stars': [0, 6.5], 'diffs': ['Expert', 'ExpertPlus'], 'freq': '珍しい'}
    assert LS.migrate_filters(ranked) is ranked
    old = {'sources': ['local'], 'stars': [4, 8], 'include_own': True, 'on_beatsaver': True, 'hard': 'ふつう'}
    assert LS.migrate_filters(old) == {'sources': ['ranked'], 'stars': [4, 8], 'hard': 'ふつう'}
    assert LS.migrate_filters({'stars': [0, 8]})['sources'] == ['ranked']   # 出どころ無し＝前は両方
    w = {'ranges': [1], 'library': ranked}
    assert LS.migrate_work(w) is w
    w2 = LS.migrate_work({'ranges': [], 'line': []})
    assert w2['library'] == LU.DEFAULT_V1 and w2['ranges'] == []
    assert LU.migrate_work is LS.migrate_work and LU.DEFAULT is LS.DEFAULT   # library_use からも同じ名前で


def test_stops_without_database(tmp_path, monkeypatch):
    """データベースが無い PC: 書き出しは Unavailable（「型のデータベースが使えない（理由）」・前は cache/themes.json に戻して作っていた）"""
    monkeypatch.setenv('AUTOMAP_LIBRARY', str(tmp_path / 'none.sqlite'))
    ok, err, _ = LU.available()
    assert not ok and '無い' in err
    with pytest.raises(LU.Unavailable, match='型のデータベースが使えない（'):
        LU.export(json.dumps(LU.DEFAULT))
    with pytest.raises(LU.Unavailable):
        LU.export_band(json.dumps(LU.DEFAULT), 1)
    r = app_library.count({'library': LU.DEFAULT})
    assert r['available'] is False


def test_with_small_database(lib, monkeypatch):
    """作り物の譜面のデータベース（tests/test_library_db.py と同じ物）: 数・★の帯ごとの曲の数・型が少なすぎれば止める"""
    db = T._ranked(lib) / 'library.sqlite'
    monkeypatch.setenv('AUTOMAP_LIBRARY', str(db))
    ok, _, info = LU.available()
    assert ok and info.get('schema_version') == library_db.SCHEMA_VERSION
    c = LU.counts({'sources': ['ranked']})
    assert c['songs'] == 3 and c['source'] == 'db' and c['stats']['diffs'] > 0
    assert LU.band_songs({'sources': ['ranked']}, [[0, 6], [6, 12], None]) == [1, 2, 3]
    with pytest.raises(LU.Unavailable, match='使える型'):   # 型が少なすぎる（MIN_THEMES 未満）＝止める
        LU.export({'sources': ['ranked']})
