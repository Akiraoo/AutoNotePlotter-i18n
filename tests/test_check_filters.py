"""区間の点検（app/check.py）: 曲にライブラリの設定が無い時の曲の選び方＝新しい曲の既定（ランク譜面・前は手元の譜面＝「今の型」と一緒に除いた）"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))


def test_no_setting_filters():
    import check
    from automap import library_use
    f, own, note, shown = check._filters(None)   # 曲が分からない＝時期は自動のまま年を絞らない
    assert f == dict(library_use.concrete(library_use.DEFAULT)) and not own and not note
    assert '曲の設定なし＝新しい曲の既定' in check._label(shown, own)
    f2, own2, note2, _ = check._filters({'sources': ['local'], 'stars': [0, 8]})   # 前の形の設定もランク譜面で数える
    assert f2['sources'] == ['ranked'] and own2 and not note2
