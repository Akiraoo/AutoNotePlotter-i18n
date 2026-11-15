"""曲ごとのライブラリの設定（docs/ライブラリ仕様.md 4 節）: 作業ファイルの library（型のデータベースの絞り込み）を compose の --library へ渡す・
絞り込みの中の曲と型の数を返す。server.py の connect() が routes(ctx) を呼んでつなぐ（compose の引数は ctx.COMPOSE_EXTRA）。

- 作業ファイル（<結果のファイル>.automap.json）の library＝automap/library_use の絞り込み（stars・years・diffs・freq・hard。出どころは
  BeatLeader のランク譜面に固定）。無い・前の形の設定は server.load_work が読み替える（library_use.migrate_work＝新しい曲の既定
  library_use.DEFAULT・出どころはランク譜面）。前の「今の型」（cache/themes.json）は除いた（2026-11-09・docs/除いた物.md）。
- データベースが無い・版が合わない PC: 受け口は available=false と理由を返す（画面に出す）。作り直しは compose が「型のデータベースが
  使えない（理由）」を出して止まる（library_use.export）。
- 受け口: GET /api/library（使えるか・既定・年の範囲・★の帯・量の目安の★の帯ごとの1秒のノーツの中央値）・POST /api/library/count
  （絞り込みの中の曲・型の数と★の帯ごとの曲の数）。
- 時期の自動（years＝'auto'・library_use.AUTO・2026-11-03 から新しい曲の既定）: 曲ごとに手本の時期を決める（library_use.resolve）。
  /api/library/count は file（結果のファイル）か song（曲の名前＝分けた音のフォルダ名）があれば、その曲の時期に置き換えて数え、
  auto_years（その曲の時期）と説明（label・short＝「時期は曲ごとに自動（この曲は …）」）を返す。曲が分からなければ年を絞らずに数える。
  compose へは自動のまま渡す（compose が同じ決まり＝曲の名前と種 1 で置き換える）。区間の点検・展開も auto_view で同じに数える。
- 量の目安（作業ファイルの amount・docs/アプリ仕様.md 8 節の 9）: {mode: 'band', stars: [下, 上]}＝その★の帯の人の譜面の1秒のノーツの
  中央値・{mode: 'nps', nps: 数}＝直接。無い・{mode: 'auto'}＝今のまま。compose に --nps-target（数）と --nps-from（説明）を渡す
  （amount_extra・別の案の作り直しにも効く）。ライブラリの★の帯とは別の設定（型と量は別・帯を変えても量は変えない）。
"""
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automap import library_use as LU  # noqa: E402

# 画面の★の帯（名前・[下, 上]・None＝全部）
BANDS = [(LU.stars_text(b)[1:], b) for b in LU.BAND_CHOICES[:5]] + [('全部', None)]
_CACHE, _LOCK = {}, threading.Lock()   # 絞り込み → 数（データベースのファイルの更新時刻が変われば捨てる）
C = None   # server モジュール（routes で受け取る。結果のファイルの場所・曲の名前）
SEED = 1   # 時期の自動の種（compose の --seed の既定。アプリの作り直しは --seed を渡さない）


def compose_extra(p, w):
    """作業ファイルの library を compose に --library（JSON の文字列）。無ければ新しい曲の既定（library_use.normalize）"""
    f = LU.normalize((w or {}).get('library'))
    return ['--library', json.dumps(f, ensure_ascii=False, separators=(',', ':'))]


def amount_extra(p, w):
    """作業ファイルに量の目安があれば compose に --nps-target（1秒のノーツの数）と --nps-from（報告に出す出どころ）。無ければ何も足さない＝今のまま"""
    t = LU.amount_target((w or {}).get('amount'))
    return ['--nps-target', f'{t[0]:g}', '--nps-from', t[1]] if t else []


def amount_bands():
    """量の目安の★の帯ごとの人の譜面の1秒のノーツの中央値 → [{name, stars, nps, diffs（参考の値は None）}]"""
    out = []
    for s in LU.NPS_BANDS:
        v, n = LU.band_nps(s)
        out.append({'name': f'〜{s[1]}' if s[0] <= 0 else f'{s[0]}〜{s[1]}', 'stars': list(s), 'nps': v, 'diffs': n})
    return out


def _stamp():
    try:
        p = LU.library_db.db_path()
        return str(p), p.stat().st_mtime
    except (LU.library_db.LibraryError, OSError):
        return None


def _memo(key, fn):
    st = _stamp()
    with _LOCK:
        if _CACHE.get('_stamp') != st:
            _CACHE.clear()
            _CACHE['_stamp'] = st
        if key in _CACHE:
            return _CACHE[key]
    v = fn()
    with _LOCK:
        _CACHE[key] = v
    return v


def _year_counts(f):
    """時期の自動の元: 絞り込み（年は除く）の年ごとの曲の数（覚えておく）。数えられなければ {}（＝年を絞らない）"""
    g = {k: v for k, v in (f or {}).items() if k not in ('years', 'auto_years', 'year_set', 'auto_v')}
    key = '_yc' + json.dumps(g, sort_keys=True, ensure_ascii=False)
    try:
        return _memo(key, lambda: LU.year_counts(g))
    except LU.ERRORS:
        return {}


def auto_view(f, song):
    """絞り込み（normalize 済み）と曲の名前 → (数える絞り込み, その曲の時期＝年の一覧 か None, 説明の絞り込み)。
    時期が自動で曲が分かれば library_use.resolve（compose と同じ決まり・種 SEED）で年を置き換える。曲が分からない・数えられない時は
    年を絞らない（library_use.concrete）。数える絞り込みには auto_years を入れない（データベースに渡す・覚える鍵）。
    説明の絞り込みは自動のまま＋auto_years（label が「時期は曲ごとに自動（この曲は …）」と書く）"""
    if not f or f.get('years') != LU.AUTO:
        return f, None, f
    got = None
    if song:
        r = LU.resolve(f, song, SEED, counts=_year_counts(f))
        got = r.get('auto_years')
        if got:
            return {k: v for k, v in r.items() if k != 'auto_years'}, list(got), dict(f, auto_years=list(got))
    return LU.concrete(f), None, f


def song_of_req(b):
    """受け口の本文 → 曲の名前（file＝結果のファイル・song＝曲の名前。無ければ None）"""
    if b.get('file') and C is not None:
        return C.song_of(C.out_file(b['file']))
    s = b.get('song')
    return str(s).strip() or None if s else None


def info(q=None):
    """GET /api/library: データベースが使えるか（使えない理由）・既定の設定・年の範囲・★の帯・頻度と難しさの区分"""
    ok, err, inf = LU.available()
    out = {'available': ok, 'error': err, 'default': LU.DEFAULT, 'legacy_default': LU.LEGACY_DEFAULT, 'auto': LU.AUTO, 'bands': [{'name': n, 'stars': b} for n, b in BANDS],
           'freq': list(LU.library_db.FREQ), 'hard': list(LU.library_db.HARD), 'nps_range': list(LU.NPS_RANGE)}
    out['amount_bands'] = _memo('_amount', amount_bands)
    if ok:
        out['built_at'] = inf.get('built_at')
        out['dist'] = bool((inf or {}).get('dist'))   # 配布用のライブラリ＝ランク譜面だけ（手元の譜面は入っていない・make_dist.py）
        try:
            out['years'] = _memo('_years', LU.years_range)
        except LU.ERRORS:
            out['years'] = None
    return out


def bands(q=None):
    """GET /api/library/bands: ★の帯の境目・直接選べる帯・既定の帯（画面の inspector.js が読み込みの時に読む・データベースは見ない）と★の物差し"""
    return {'steps': list(LU.BAND_STEPS), 'choices': [list(b) for b in LU.BAND_CHOICES], 'default': list(LU.DEFAULT['stars']), 'scale': LU.rating_scale.SCALE}


def count(b):
    """POST /api/library/count {library: 絞り込み（null＝新しい曲の既定）, file?: 結果のファイル, song?: 曲の名前}: 曲・片手の型・両手の組・
    1回だけの並び・テーマに使える型・選んだ譜面の割合、★の帯ごとの曲の数（★以外はそのまま）、年ごとの曲の数（year_counts＝★と年を
    外した数＝欄の一番上の年の横に出す・上から順に絞る・2026-11-15）。
    時期が自動なら file か song の曲の時期で数える（auto_years＝年の一覧・counted＝数えた絞り込み）。曲が分からなければ年を絞らない数"""
    f = LU.normalize(b.get('library'))
    ok, err, _ = LU.available()
    if not ok:
        return {'source': 'db', 'available': False, 'error': err, 'filters': f, 'label': LU.label(f), 'short': LU.label(f, True),
                'auto_years': None}
    cf, got, shown = auto_view(f, song_of_req(b) if f.get('years') == LU.AUTO else None)
    key = json.dumps([cf, got, f.get('years') == LU.AUTO], sort_keys=True, ensure_ascii=False)

    def calc():
        r = LU.counts(cf)
        r['bands'] = LU.band_songs(cf, [s for _, s in BANDS])
        r['year_counts'] = {str(y): n for y, n in _year_counts(LU.center_filters(f)).items()}
        r.update(available=True, filters=f, counted=cf, auto_years=got, label=LU.label(shown), short=LU.label(shown, True))
        if r['themes'] < LU.MIN_THEMES:
            r['warn'] = f'テーマに使える型が {r["themes"]} しか無い＝作り直しは止まる（{LU.MIN_THEMES} より少ないとテーマを選べない）。絞り込みをゆるめる'
        elif r['themes'] < 60:
            r['warn'] = f'テーマに使える型が {r["themes"]} と少ない＝曲どうし・曲の中が似やすい'
        return r
    try:
        return _memo(key, calc)
    except LU.ERRORS as e:
        return {'source': 'db', 'available': False, 'error': str(e), 'filters': f, 'label': LU.label(shown), 'short': LU.label(shown, True),
                'auto_years': got}


def _guard(fn):
    """受け答えの中の思わぬ失敗も 400（server は ValueError・FileNotFoundError・KeyError だけを 400 にする）"""
    def w(arg):
        try:
            return fn(arg)
        except (ValueError, FileNotFoundError, KeyError):
            raise
        except Exception as e:   # noqa: BLE001
            raise ValueError(f'{type(e).__name__}: {e}')
    return w


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})。compose の引数の口（ctx.COMPOSE_EXTRA）にも登録する"""
    global C
    C = ctx
    for fn in (compose_extra, amount_extra):   # amount_extra＝量の目安
        if fn not in ctx.COMPOSE_EXTRA:
            ctx.COMPOSE_EXTRA.append(fn)
    return {'/api/library': _guard(info), '/api/library/bands': _guard(bands)}, {'/api/library/count': _guard(count)}
