"""曲ごとのライブラリの設定の形（新しい曲の既定と、前の形の設定の読み替え・2026-11-09）。

軽い部品（標準の部品と rating_scale だけを読む）: サーバーは曲を開くたびに作業ファイルを読み（server.load_work）、ここで読み替える。
書き出し・数える所（automap/library_use.py）は作る処理の部品（style・theme・intent）を読むので、サーバーの頭や曲のデータの控えの
作り方の版（app/songcache.py）に入れないよう分けた。library_use からも同じ名前で使える（library_use.DEFAULT 等）。

型は BeatLeader のランク譜面の型のデータベースだけから作る（前の「今の型」＝手元の譜面から作った cache/themes.json と、出どころの
手元の譜面の選びは除いた・docs/除いた物.md）。設定の無い曲・出どころに手元の譜面がある前の形の設定はランク譜面へ読み替える。
"""
import json

from . import rating_scale

_B = rating_scale.BANDS   # ★の段の境目（★の物差しの一部）
# 新しい曲の既定（2026-10-26 利用者・時期は 2026-11-03 から自動）: BeatLeader のランク譜面・時期は曲ごとに自動・★〜B[3]・Expert／Expert+
# 時期の自動の決め方の版（auto_v・2026-11-15 利用者「チェックボックス式にして歯抜けの年を持たせたり…曲ごとに初回自動選択されるけども、
# それ自体のランダム性を少し上げたい」）: 2＝中心の年から、曲ごとに決まった順で離れた年も足す（歯抜けあり・library_use.auto_years）。
# 印の無い自動（years＝'auto' だけ）は前の決め方＝つながった年（2026-11-15 より前に作った曲・利用者「今の曲は今の年の組のまま」）。
AUTO = 'auto'
AUTO_V = 2
DEFAULT = {'sources': ['ranked'], 'years': AUTO, 'auto_v': AUTO_V, 'stars': [0, _B[3]], 'diffs': ['Expert', 'ExpertPlus']}
# 設定の無い曲（前は今の型）の読み替え先＝前の決め方の自動（2026-11-15 より前からある曲の年を変えない）
DEFAULT_V1 = {k: v for k, v in DEFAULT.items() if k != 'auto_v'}
# 前の既定（2020 年以降）。取り込みの窓がブラウザに覚えた前の既定を新しい既定に読み替えるのに使う（app/library.info の legacy_default）
LEGACY_DEFAULT = {'sources': ['ranked'], 'years': [2020, 2026], 'stars': [0, _B[3]], 'diffs': ['Expert', 'ExpertPlus']}


def migrate_filters(f):
    """前の形のライブラリの設定 → 今の形: 無い・空（設定の無い曲＝前は今の型）は新しい曲の既定（の前の決め方の自動＝DEFAULT_V1 の写し）・出どころに手元の譜面
    （local）がある・出どころが無い（両方）は、出どころだけランク譜面に（手元の譜面だけの印 include_own・on_beatsaver も外す）。
    ランク譜面だけの設定はそのまま返す（同じ物＝今の曲の答えを変えない）"""
    if not f or not isinstance(f, dict):
        return json.loads(json.dumps(DEFAULT_V1))
    if list(f.get('sources') or []) == ['ranked']:
        return f
    g = {k: v for k, v in f.items() if k not in ('include_own', 'on_beatsaver')}
    g['sources'] = ['ranked']
    return g


def migrate_work(w):
    """作業ファイル（の写し）の library を migrate_filters で読み替えた物（server.load_work・versions._ver_work・次に保存した時に
    書き換わる）。読み替える物が無ければ同じ物"""
    if not isinstance(w, dict):
        return w
    lib = w.get('library')
    new = migrate_filters(lib)
    return w if new is lib else dict(w, library=new)
