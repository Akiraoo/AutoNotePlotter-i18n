"""★の物差し（BeatLeader の PP の版）の組（docs/ライブラリ仕様.md 6.11・2026-11-07 利用者）。

アプリの★は次の 3 つが同じ物差しでそろって初めて意味を持つ。1 つだけ新しいと「ライブラリ ★〜8」の★と作った譜面の★が別の物になる:
  1. nlm-rating（作った譜面の★を測る・配布物の parts/nlm-rating/）
  2. 型のデータベース（ランク譜面の★・★の近似＝★の帯で絞る・配布物の data/library-dist.sqlite）
  3. ★から決めた数（NJS の式の係数・★の帯の境目・帯の 1 秒のノーツの参考の値＝rating_scale.json）

どれも `tools/library_build/update_rating.py` がまとめて入れ替える。rating_scale.json はその道具が書く（手で直さない）。リリースはアプリの版と
一緒に上げる＝配布物にどれも入っていて、更新で丸ごと差し替わる。配布物を作る時に `problems` が違いを見つけたら止まる（tools/dist/build_embed.py）。

★の帯の境目は、前の物差しと同じ割合の譜面が入る所へ 0.5 刻みで動かす（道具が案を出し、人が決める）。境目が動いても、前に決めた設定は
`moved`（前の境目 → 今の境目）で読み替える＝作業ファイル・履歴を読む時に `migrate_work`（server.load_work・versions）。

物差しの名前は nlm-rating の版の上 2 つ（4.1.0 → 4.1＝本家の PPv4.1。nlm-rating は 4.1.0 から版の上 2 つを本家に合わせている）。
配布物を作る Python でも読むので標準ライブラリだけ。
"""
import json
import sqlite3
import subprocess
from pathlib import Path

DATA = Path(__file__).with_name('rating_scale.json')
_D = json.loads(DATA.read_text(encoding='utf-8'))


def _num(x):
    """'6.5' → 6.5・'5' → 5（作業ファイルの★の帯と同じ書き方）"""
    v = float(x)
    return int(v) if v.is_integer() else v


SCALE = _D['scale']              # 今の物差し（例 '4.1'）
NLM_RATING = _D['nlm_rating']    # 作った時の nlm-rating の版
BL_LIST_AT = _D['bl_list_at']    # 作った時に BeatLeader の一覧を取った時刻
BANDS = tuple(_D['bands'])       # ★の段の境目（7 つ＝0・5 つの境目・99。automap/library_use.py の BAND_STEPS）
MOVED = {float(k): v for k, v in _D['moved'].items()}   # 前の物差しの境目 → 今の境目（今の境目は入れない）
NJS_COEF = _D['njs']             # automap/njs.py の式の係数（njs.fit の答え）
NPS_REF = {tuple(_num(x) for x in k.split('-')): v for k, v in _D['nps_ref'].items()}   # ★の帯 → 人の譜面の 1 秒のノーツの中央値（automap/library_use.py）


def move(st):
    """★の帯 [下, 上] の前の境目を今の境目へ（今の境目・境目でない値はそのまま＝何度通してもよい）"""
    return [MOVED.get(float(x), x) for x in st]


def _is_band(v):
    return isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)


def migrate_work(o):
    """作業ファイル（の一部）の中の★の帯（項目 stars・band の [下, 上]＝ライブラリの設定・量の目安・展開の行・区間の指示）を今の境目へ読み替えた写し"""
    if not MOVED:
        return o
    if isinstance(o, dict):
        return {k: move(v) if k in ('stars', 'band') and _is_band(v) else migrate_work(v) for k, v in o.items()}
    if isinstance(o, list):
        return [migrate_work(v) for v in o]
    return o


def of(version):
    """nlm-rating の版 → 物差しの名前（'4.1.0' → '4.1'）。版が無ければ None"""
    parts = str(version).split('.') if version else []
    return '.'.join(parts[:2]) if len(parts) >= 2 else None


def exe_version(exe):
    """nlm-rating の版（`--version`）。取れなければ None"""
    try:
        r = subprocess.run([str(exe), '--version'], capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return json.loads(r.stdout.decode('utf-8')).get('version')
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return None


def db_scales(db):
    """型のデータベースの★の近似を測った nlm-rating の物差し → {物差し}（info の approx_versions）。読めなければ空"""
    try:
        con = sqlite3.connect(f'file:{Path(db).as_posix()}?mode=ro', uri=True)
        try:
            row = con.execute("SELECT v FROM info WHERE k = 'approx_versions'").fetchone()
        finally:
            con.close()
        return {of(v) for v in json.loads(row[0])} if row else set()
    except (sqlite3.DatabaseError, ValueError, AttributeError):
        return set()


def problems(exe=None, db=None, scale=None):
    """渡した nlm-rating・型のデータベースが物差し（既定＝SCALE）と違う所の説明 → 一覧（空ならそろっている）"""
    scale = scale or SCALE
    out = []
    if exe is not None:
        v = exe_version(exe)
        if of(v) != scale:
            out.append(f'nlm-rating の版が {v}（物差し {scale} の版ではない）: {exe}')
    if db is not None:
        s = db_scales(db)
        if s != {scale}:
            out.append(f'型のデータベースの★の物差しが {sorted(map(str, s)) or "不明"}（{scale} ではない）: {db}')
    return out
