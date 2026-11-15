"""曲ごとのライブラリの設定（作業ファイルの library）→ 型のデータベースの書き出し（docs/ライブラリ仕様.md 4 節・6.7）。
compose の --library・アプリ（app/library.py）・取り込み（app/importer.py）が使う。
型は BeatLeader のランク譜面の型のデータベースだけから作る（2026-11-09 利用者「古い所からは作らず、リリース用の BeatLeader のメインの
データベースからだけの作成に絞り込んでよい」）。前の「今の型」（手元の譜面から作った cache/themes.json・設定の無い曲）と、出どころの
手元の譜面の選びは除いた（docs/除いた物.md）。

- 作業ファイルの library＝library_db.export_themes の絞り込み（stars・years・diffs・freq・hard。無い項目は絞らない）。出どころは
  ランク譜面に固定（sources=['ranked']・normalize）。設定の無い曲・前の形の設定（出どころに手元の譜面 local がある）は migrate_filters
  （automap/library_setting.py）で
  ランク譜面へ読み替える（設定の無い曲は新しい曲の既定 DEFAULT・ほかは出どころだけ ranked に。ランク譜面だけの設定はそのまま）。
- データベースが使えない PC・版が合わない・絞り込みの中で使える型が少なすぎる時は止める（export が Unavailable＝「型のデータベースが
  使えない（理由）」。compose はその字を出して止まる＝アプリの作り直し・取り込み・展開の記録に出る）。
- 書き出しには、選んだ譜面の打ち方の割合（diff_stats の斜め・外側の列・上の段…）を library.stats として足す（style.targets が使う）。
- **時期の自動**（years＝'auto'・2026-11-03 利用者「自動をデフォルトにして、気になる人は個別に調整」・docs/方針.md 6.23・6.24）: 人の譜面は
  時期（年）で型の選ばれ方が作者と同じくらい変わる（違う作者でも同じ年なら3振りの並びの重なり 23%・3年以上離れると 10%）。曲ごとに
  手本の時期を自動で決める＝曲どうしのテーマが散る。中心の年は曲の名前と種で（style.habit_seed と同じ種）、そこから曲が AUTO_SONGS
  以上になるまで曲の多い隣の年へ広げる（auto_years）。使う所（compose・アプリ）は resolve で曲の時期に置き換えてから書き出す。
- **年は選んだ年の一覧**（year_set・2026-11-15 利用者「チェックボックス式にしてどの年とどの年を選べる…歯抜けの年を持たせたり」）: 前の
  範囲 [から, まで]（years）は normalize で年の一覧に読み替える（データベースの読み口は両方を受ける）。時期の自動の決め方は版（auto_v）で分ける:
  2＝中心の年から、曲ごとに決まった順で離れた年も足す（歯抜けあり＝曲どうしの年の組が散る）・印無し＝前の決め方（つながった年＝2026-11-15
  より前に作った曲は今の年の組のまま・利用者）。resolve の後は year_set＝その曲の年・auto_years＝同じ（表示用）。
"""
import json
import sqlite3
from pathlib import Path

from . import library_db, rating_scale
# 新しい曲の既定（AUTO・DEFAULT）・前の既定（LEGACY_DEFAULT）・前の形の設定の読み替え（migrate_filters・migrate_work）は軽い部品に
# 分けた（サーバーが曲を開くたびに読む・automap/library_setting.py）。ここからも同じ名前で使える
from .library_setting import AUTO, AUTO_V, DEFAULT, DEFAULT_V1, LEGACY_DEFAULT, migrate_filters, migrate_work  # noqa: F401

# ★の段の境目（★の物差しの一部＝automap/rating_scale.py）。★〜B[1]・B[1]〜B[2]・… 1段やさしく／難しく＝帯の両端をこの境目で1つずらす
_B = BAND_STEPS = rating_scale.BANDS
AUTO_SONGS = 170          # 自動の時期の窓に入れる曲の数の目安（既定の★の帯・Expert／Expert+ で、どの窓もテーマに使える型が 83 以上になる大きさ。
                          # 1年だけだと 2023 年 34・2024 年 27 と少ない・2026-11-07 のデータベース＝★〜8.5 で窓の型 85〜173）
AUTO_MIN_YEAR_SONGS = 10  # 中心の年にできる年の曲の数の下限
AUTO_PICK_MIN = 3         # 新しい決め方（auto_v 2）で足す年の曲の数の下限（★で絞った数・2026 年の 3 曲だけの年などは足しても型が増えない）
NPS_FILTERS = {'sources': ['ranked'], 'years': [2020, 2026], 'diffs': ['Expert', 'ExpertPlus']}   # ★の帯の量の目安（band_nps）を数える束（前の DEFAULT のまま）


def concrete(f):
    """絞り込みの時期が自動のまま（曲が分からない所）なら年を絞らない物に（resolve の後の物はそのまま）"""
    f = dict(f or {})
    if f.get('years') == AUTO:
        f.pop('years')
    f.pop('auto_years', None)
    f.pop('auto_v', None)
    return f
MIN_THEMES = 8   # 絞り込みの中で使える型（theme.load_themes）がこれより少なければ止める（テーマを選べない・Unavailable）
SRC_TEXT = {('ranked',): 'ランク譜面', ('local',): '手元の譜面', ('local', 'ranked'): 'ランク譜面と手元の譜面'}
DIFF_TEXT = {'Expert': 'Expert', 'ExpertPlus': 'Expert+'}
ERRORS = (library_db.LibraryError, sqlite3.Error, OSError, ValueError, KeyError)


class Unavailable(Exception):
    """型のデータベースが使えない（無い・版が合わない・絞り込みの中で使える型が少なすぎる）。字は「型のデータベースが使えない（理由）」
    （compose は字を出して止まる・アプリの記録と画面に出る）"""


def filters_of(spec):
    """--library の中身（JSON の文字列か、JSON のファイルの場所）→ 絞り込み（library_db.export_themes の filters）"""
    if isinstance(spec, dict):
        return dict(spec)
    s = str(spec).strip()
    return json.loads(s if s.startswith('{') else Path(s).read_text(encoding='utf-8'))


def _pair(v, k):
    if not (isinstance(v, (list, tuple)) and len(v) == 2):
        raise ValueError(f'{k} は [下, 上]')
    lo, hi = (float(x) for x in v)
    return (hi, lo) if lo > hi else (lo, hi)


def year_list(v):
    """選んだ年（一覧）を整える → 小さい順・重なり無しの年（整数）。年でない物は ValueError"""
    if not isinstance(v, (list, tuple)):
        raise ValueError('year_set は年の一覧')
    out = set()
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float, str)) or not str(x).strip().split('.')[0].isdigit():
            raise ValueError(f'年でない: {x!r}')
        y = int(float(x))
        if not 2000 <= y <= 2100:
            raise ValueError(f'年でない: {x!r}')
        out.add(y)
    return sorted(out)


def years_text(ys, short=False):
    """年の一覧 → 説明の字（続いた年はまとめる）: [2019, 2021, 2022, 2023] → 「2019・2021〜2023」（short＝「2019・21〜23」）"""
    ys = sorted(set(int(y) for y in ys or ()))
    runs, out = [], []
    for y in ys:
        if runs and y == runs[-1][1] + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    for i, (a, b) in enumerate(runs):
        sa = str(a)[2:] if short and i else str(a)
        out.append(sa if a == b else f'{sa}〜{str(b)[2:] if short else b}')
    return '・'.join(out)


def normalize(f):
    """画面・作業ファイルから来た絞り込みを整える（知らない項目・空の項目は落とす。全部の頻度と難しさは「絞らない」）。出どころは
    ランク譜面に固定（sources=['ranked']・手元の譜面の選びは除いた）。None・空なら新しい曲の既定（DEFAULT）"""
    if not f:
        f = DEFAULT
    if not isinstance(f, dict):
        raise ValueError('ライブラリの設定は辞書')
    out = {'sources': ['ranked']}
    if f.get('years') == AUTO:   # 時期の自動（auto_v＝決め方の版・印の無い物は前の決め方のまま）
        out['years'] = AUTO
        if f.get('auto_v') == AUTO_V:
            out['auto_v'] = AUTO_V
    elif f.get('year_set'):      # 選んだ年の一覧（歯抜けあり）
        out['year_set'] = year_list(f['year_set'])
    elif f.get('years'):         # 前の形の範囲 [から, まで] → 年の一覧
        lo, hi = _pair(f['years'], 'years')
        out['year_set'] = list(range(int(lo), int(hi) + 1))
    if f.get('stars'):
        lo, hi = _pair(f['stars'], 'stars')
        out['stars'] = [int(x) if x.is_integer() else x for x in (lo, hi)]
    d = [x for x in f.get('diffs') or [] if x in ('Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus')]
    out['diffs'] = d or list(library_db.DEFAULT_DIFFS)
    if f.get('freq') in library_db.FREQ:   # 無い＝既定（曲の数に合わせたしきい値）・「珍しい」＝少ない曲にしか出ない型も（theme.thresholds）
        out['freq'] = f['freq']
    if f.get('hard') in library_db.HARD[:-1]:   # 「難しいまで」＝全部
        out['hard'] = f['hard']
    for k in ('mappers', 'exclude_mappers'):
        if f.get(k):
            out[k] = [str(x) for x in f[k]]
    if 'approx' in f and f['approx'] is not None:
        out['approx'] = bool(f['approx'])
    return out


def label(f, short=False):
    """絞り込み → 日本語の説明（short＝ボタン用の短い物「ランク ★〜8」）。None・空は新しい曲の既定"""
    if not f:
        f = DEFAULT
    src = tuple(sorted(f.get('sources') or ('local', 'ranked')))
    st = f.get('stars')
    star = '★全部' if not st else f'★〜{st[1]:g}' if st[0] <= 0 else f'★{st[0]:g}〜' if st[1] >= 99 else f'★{st[0]:g}〜{st[1]:g}'
    yr = f.get('years')
    got = f.get('auto_years')   # resolve が決めた曲の時期（表示だけ・年の一覧）
    auto = yr == AUTO or bool(got)
    ys = got if got else f.get('year_set') or (list(range(int(yr[0]), int(yr[1]) + 1)) if isinstance(yr, (list, tuple)) and len(yr) == 2 else None)
    old = auto and f.get('auto_v') != AUTO_V   # 前の決め方の自動（つながった年）
    if short:
        parts = [{'ranked': 'ランク', 'local': '手元'}[src[0]] if len(src) == 1 else 'ランク＋手元', star]
        if auto:
            parts.append('時期自動' + (f'（{years_text(ys, True)}）' if ys else ''))
        elif ys:
            parts.append(years_text(ys, True))
        if f.get('freq'):
            parts.append(f'{f["freq"]}まで')
        if f.get('hard'):
            parts.append(f'{f["hard"]}まで')
        return ' '.join(parts)
    parts = [SRC_TEXT.get(src, '・'.join(src)), star + ('（BeatLeader の★だけ）' if f.get('approx') is False else '')]
    parts.append(('時期は曲ごとに自動' + (('（前の決め方＝つながった年' + (f'・この曲は {years_text(ys)} 年）' if ys else '）')) if old else
                                         f'（この曲は {years_text(ys)} 年）' if ys else '')) if auto else
                 f'{years_text(ys)} 年' if ys else '年は全部')
    parts.append('／'.join(DIFF_TEXT.get(d, d) for d in f.get('diffs') or library_db.DEFAULT_DIFFS))
    parts.append('型の頻度は珍しいまで（少ない曲にしか出ない型も）' if f.get('freq') == '珍しい' else
                 f'型の頻度は{f["freq"]}まで' if f.get('freq') else '型の頻度は既定（曲の数に合わせる）')
    parts.append(f'置き方の難しさは{f["hard"]}まで' if f.get('hard') else '置き方の難しさは全部')
    if f.get('mappers'):
        parts.append('作者 ' + '・'.join(f['mappers']))
    if f.get('exclude_mappers'):
        parts.append('除く作者 ' + '・'.join(f['exclude_mappers']))
    return '・'.join(parts)


def available(path=None):
    """データベースが使えるか → (使える, 使えない理由, info)。開いたらすぐ閉じる（開いたままだと build_db.py が置き換えられない）"""
    try:
        con = library_db.open_db(path)
    except ERRORS as e:
        return False, str(e), {}
    try:
        return True, '', library_db.info_of(con)
    finally:
        con.close()


def brief(st):
    """diff_stats の全部のまとめ → 曲の個性の目標に使う割合（下の段・上の段・外側の列・斜め（点を除いた向きの中）・1秒のノーツの中央値）"""
    a = (st or {}).get('all')
    if not a:
        return None
    d = a.get('dir_mean') or {}
    v, g, s = d.get('up', 0) + d.get('down', 0), d.get('diag', 0), d.get('side', 0)
    tot = (v + g + s) or 1
    col, row = a.get('col_mean') or [0.25] * 4, a.get('row_mean') or [1 / 3] * 3
    nps = a.get('nps_q1_med_q3')
    return {'diffs': st.get('diffs'), 'songs': st.get('songs'), 'bottom': round(row[0], 4), 'top': round(row[2], 4),
            'outer': round(col[0] + col[3], 4), 'diag': round(g / tot, 4), 'side': round(s / tot, 4),
            'nps': nps[1] if nps else None}


# ---- 量の目安（作業ファイルの amount → compose --nps-target・automap/amount.py・docs/アプリ仕様.md 8 節の 9） ----
# 型のデータベースが使えない PC の参考＝データベースがある時と同じ決め方（NPS_FILTERS の中央値）。★の物差しの一部（automap/rating_scale.py）
NPS_REF = rating_scale.NPS_REF
NPS_BANDS = tuple([a, b] for a, b in zip(_B[:5], _B[1:6]))   # 画面で選べる★の帯
NPS_RANGE = (1.0, 16.0)   # 直接入れる1秒のノーツの数の範囲


def amount_of(a):
    """作業ファイルの amount → {'mode': 'band', 'stars': [下, 上]}・{'mode': 'nps', 'nps': 数}・None（自動＝今のまま・使えない値）"""
    if not isinstance(a, dict):
        return None
    if a.get('mode') == 'band':
        s = a.get('stars')
        if isinstance(s, (list, tuple)) and len(s) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in s):
            lo, hi = sorted(float(x) for x in s)
            if hi > lo:
                return {'mode': 'band', 'stars': [int(x) if x.is_integer() else x for x in (lo, hi)]}
        return None
    if a.get('mode') == 'nps':
        v = a.get('nps')
        if isinstance(v, (int, float)) and not isinstance(v, bool) and NPS_RANGE[0] <= v <= NPS_RANGE[1]:
            return {'mode': 'nps', 'nps': round(float(v), 2)}
    return None


def band_nps(stars):
    """★の帯 [下, 上] → (人の譜面の1秒のノーツの中央値, 譜面の数（参考の値は None）)。型のデータベースの diff_stats（出どころ・年・難易度は
    DEFAULT＝ランク譜面・2020 年以降・Expert／Expert+。曲のライブラリの設定とは別＝型と量は別）。使えない PC・帯に譜面が無い時は
    NPS_REF（同じ帯が無ければ帯の真ん中で参考の値を線でつなぐ）"""
    lo, hi = float(stars[0]), float(stars[1])
    try:
        st = library_db.diff_stats(dict(NPS_FILTERS, stars=[lo, hi]))
        q = ((st or {}).get('all') or {}).get('nps_q1_med_q3')
        if q and q[1]:
            return round(float(q[1]), 2), st.get('diffs')
    except ERRORS:
        pass
    ref = NPS_REF.get((lo, hi))
    if ref is None:
        import numpy as np
        xs = sorted(NPS_REF)
        ref = float(np.interp((lo + min(hi, 14)) / 2, [(a + b) / 2 for a, b in xs], [NPS_REF[k] for k in xs]))
    return round(ref, 2), None


def amount_target(a):
    """作業ファイルの amount → (目安の1秒のノーツの数, 報告に出す出どころの説明) か None（自動＝今のまま）"""
    a = amount_of(a)
    if not a:
        return None
    if a['mode'] == 'nps':
        return a['nps'], '曲の設定で直接'
    v, n = band_nps(a['stars'])
    lo, hi = a['stars']
    band = f'★〜{hi:g}' if lo <= 0 else f'★{lo:g}〜{hi:g}'
    return v, (f'{band} の人の譜面 {n} 難易度の中央値' if n else f'{band} の人の譜面の中央値（参考の値・型のデータベースが使えない）')


_YC = {}   # year_counts の覚え（絞り込みとデータベースの更新時刻ごと）


def year_counts(f, db=None):
    """絞り込み（年は除く）に入る曲の数を年ごとに → {年: 曲の数}（データベースを作り直すまで覚える）"""
    g = {k: v for k, v in dict(f).items() if k not in ('years', 'auto_years', 'year_set', 'auto_v')}
    try:
        stamp = Path(library_db.db_path(db)).stat().st_mtime if not isinstance(db, sqlite3.Connection) else None
    except (OSError, TypeError, ValueError, library_db.LibraryError):
        stamp = None
    key = (json.dumps(g, sort_keys=True, ensure_ascii=False), str(db), stamp)
    if stamp is not None and key in _YC:
        return dict(_YC[key])
    con = library_db.open_db(db)
    try:
        sel = library_db._select(con, g)
    finally:
        con.close()
    out = {}
    for mid, _, _, year, _ in sel.values():
        if year is not None:
            out.setdefault(int(year), set()).add(mid)
    res = {y: len(v) for y, v in sorted(out.items())}
    if stamp is not None:
        _YC[key] = res
    return dict(res)


def auto_years(f, song, seed=1, counts=None, center_counts=None):
    """時期が自動の絞り込み → この曲の手本の年の一覧（小さい順・曲の数が無ければ None）。
    中心の年は曲の名前と種で（style.habit_seed）、center_counts（★を外した年ごとの曲の数・無ければ counts）で曲が AUTO_MIN_YEAR_SONGS 以上の
    年から同じ重みで選ぶ＝★の帯（難易度の展開の派生）が違っても同じ曲は同じ中心の年（前は★で絞った数から選び、こだまの Expert+ が
    2023〜26・Expert が 2018〜22 になった）。そこから counts（★で絞った数）で曲が AUTO_SONGS 以上になるまで年を足す:
    - auto_v 2（新しい決め方・2026-11-15）: ほかの年を曲ごとに決まった順（★を外した年も含めて曲の種で混ぜた順＝★の帯が違っても同じ順）で
      足す。離れた年も入る＝歯抜けあり。年は曲の多さによらず同じ重み（曲の数で重みを付けると、曲の多い 2021 年ばかりが 2 つ目に入った）。
      ★で絞った曲が AUTO_PICK_MIN より少ない年は足さない。試しの計算で、利用者の 14 曲の年の組が 6 → 13 通り・作り物の 200 曲で 92 通り
    - 印無し（前の決め方）: 隣の年へ左右交互に広げる＝つながった年（最初は曲の少ない側から。曲の多い側へ広げる決まりでは、53 曲中 51 曲の
      時期に一番大きい 2021 年が入って散らなかった）"""
    from . import style
    counts = counts if counts is not None else year_counts(f)
    cc = center_counts if center_counts is not None else counts
    ys = [y for y, n in sorted(cc.items()) if n >= AUTO_MIN_YEAR_SONGS]
    if not ys or not counts:
        return None
    h = style.habit_seed(song, seed)
    c = ys[h % len(ys)]
    if f.get('auto_v') == AUTO_V:
        import random
        rest = sorted(y for y in set(cc) | set(counts) if y != c)
        random.Random(f'{h}:years').shuffle(rest)
        picked, tot = [c], counts.get(c, 0)
        for y in rest:
            if tot >= AUTO_SONGS:
                break
            if counts.get(y, 0) >= AUTO_PICK_MIN:
                picked.append(y)
                tot += counts[y]
        return sorted(picked)
    lo = hi = c
    first, last = min(min(counts), c), max(max(counts), c)
    tot = counts.get(c, 0)
    side = None
    while tot < AUTO_SONGS and (lo > first or hi < last):
        can_l, can_r = lo > first, hi < last
        if side is None:   # 最初は曲の少ない隣から
            side = 'l' if can_l and (not can_r or counts.get(lo - 1, 0) < counts.get(hi + 1, 0)) else 'r'
        else:
            side = 'r' if side == 'l' else 'l'
        if side == 'l' and not can_l:
            side = 'r'
        if side == 'r' and not can_r:
            side = 'l'
        if side == 'l':
            lo -= 1
            tot += counts.get(lo, 0)
        else:
            hi += 1
            tot += counts.get(hi, 0)
    return list(range(lo, hi + 1))


def center_filters(f):
    """中心の年を選ぶ時の絞り込み＝★を外した物（同じ曲は★の帯が違っても同じ中心の年）"""
    return {k: v for k, v in dict(f).items() if k not in ('stars', 'years', 'auto_years', 'year_set', 'auto_v')}


def resolve(spec, song, seed=1, counts=None, center_counts=None):
    """絞り込み → 時期が自動なら、この曲の時期（auto_years）に置き換えた絞り込み（表示用に auto_years も入れる。書き出しは無視する）。
    自動でなければそのまま。曲の数が数えられない（データベースが使えない）時は年を絞らない。center_counts が無ければ★を外して数える"""
    if not spec:
        return spec
    f = filters_of(spec)
    if f.get('years') != AUTO:
        return f
    try:
        if center_counts is None:
            center_counts = year_counts(center_filters(f))
        got = auto_years(f, song, seed, counts, center_counts)
    except ERRORS:
        got = None
    if got:   # auto_v は残す（説明が前の決め方かを書く・データベースへは concrete が外す）
        return dict({k: v for k, v in f.items() if k != 'years'}, year_set=list(got), auto_years=list(got))
    return {k: v for k, v in f.items() if k not in ('years', 'auto_v')}


def export(spec):
    """絞り込み → 型（library_db.export_themes の形＋library.stats）。使えない（データベースが無い・版が合わない・使える型が MIN_THEMES より
    少ない）時は Unavailable（止める・前は cache/themes.json に戻して作っていた）。時期が自動のまま来たら（resolve していない）年は絞らない"""
    from . import theme
    f0 = filters_of(spec)
    f = concrete(f0)
    auto = f0.get('years') == AUTO or bool(f0.get('auto_years'))
    try:
        lib = library_db.export_themes(f)
        n = len(theme.load_themes(lib))
        if n < MIN_THEMES:
            raise ValueError(f'絞り込み（{label(f, True)}）の中で使える型が {n} しか無い・曲 {lib.get("songs")}＝絞り込みをゆるめる')
        lib['library']['stats'] = brief(library_db.diff_stats(f))
    except ERRORS as e:
        raise Unavailable(f'型のデータベースが使えない（{e}）') from e
    if auto:   # 報告・画面の説明は「時期は自動（この曲は …）」
        lib['library']['filters'] = dict({k: v for k, v in (lib['library'].get('filters') or f).items() if k != 'year_set'}, years=AUTO,
                                         **({'auto_years': list(f0['auto_years'])} if f0.get('auto_years') else {}),
                                         **({'auto_v': f0['auto_v']} if f0.get('auto_v') else {}))
    return lib


def describe(lib):
    """報告に出す「型の出どころ」の文（compose の報告。後ろに「・型 N」が付く）"""
    from . import theme
    L = lib.get('library') or {}
    hm, pm = theme.thresholds(lib)
    s = (f'型のデータベース（{label(L.get("filters"))}）の曲 {lib.get("songs")}・片手の型 {len(lib.get("hands") or [])}・'
         f'両手の組 {len(lib.get("pairs") or [])}・1回だけの並び {len(lib.get("once") or [])}'
         f'（テーマに使うのは片手の型 {hm} 曲以上・両手の組 {pm} 曲以上）')
    st = L.get('stats')
    if st:
        s += (f'。選んだ譜面の割合: 斜め {st["diag"]:.0%}・外側の列 {st["outer"]:.0%}・上の段 {st["top"]:.0%}'
              + (f'・1秒のノーツ {st["nps"]:g}' if st.get('nps') else '') + '（曲の個性の目標をこの分ずらす）')
    if L.get('built_at'):
        s += f'。データベースを作った日 {str(L["built_at"])[:10]}'
    return s


def counts(f):
    """アプリの窓に出す数: 曲・片手の型・両手の組・1回だけの並び・テーマに使える型（theme.load_themes）・選んだ譜面の割合。
    f が空なら新しい曲の既定（年は絞らない）"""
    from . import theme
    f = f or concrete(DEFAULT)
    lib = library_db.export_themes(f)
    hm, pm = theme.thresholds(lib)
    return {'source': 'db', 'songs': lib.get('songs'), 'hands': len(lib['hands']), 'pairs': len(lib['pairs']),
            'once': len(lib.get('once') or []), 'themes': len(theme.load_themes(lib)), 'min': [hm, pm],
            'stats': brief(library_db.diff_stats(f)), 'built_at': (lib.get('library') or {}).get('built_at')}


def band_songs(f, bands):
    """★の帯ごとの曲の数（★以外の絞り込みはそのまま・library_db.export_themes と同じ曲の選び方）→ [曲の数…]。
    bands＝[[下, 上] か None（全部）…]"""
    g = {k: v for k, v in (f or {}).items() if k != 'stars'}
    con = library_db.open_db()
    try:
        sel = library_db._select(con, g)   # 読むだけ（書き出しと同じ決まりで難易度を選ぶ）
    finally:
        con.close()
    out = []
    for b in bands:
        out.append(len({v[0] for v in sel.values() if b is None or (v[2] is not None and b[0] <= v[2] <= b[1])}))
    return out


def years_range():
    """データベースのアップロード年の範囲 [最初, 最後]（無ければ None）"""
    con = library_db.open_db()
    try:
        r = con.execute('SELECT MIN(year), MAX(year) FROM maps WHERE year IS NOT NULL').fetchone()
    finally:
        con.close()
    return [r[0], r[1]] if r and r[0] else None


# ---- 区間の★の帯（意思入れの区間の指示 set.band・compose --band・docs/アプリ仕様.md 8 節の 9） ----
def band_choices(b):
    """★の段の境目 → 画面で直接選べる帯（ライブラリの窓の帯＋一番上）"""
    return ([0, b[2]], [0, b[3]], [b[1], b[3]], [b[2], b[4]], [b[3], b[5]], [b[4], b[6]])


BAND_CHOICES = band_choices(_B)   # 画面（inspector.js）は /api/library/bands から読む


def stars_text(st):
    """★の帯 [下, 上] → 「★〜8」「★6〜10」「★10〜」（None は「★全部」）"""
    if not st or (st[0] <= 0 and st[1] >= 99):
        return '★全部'
    lo, hi = st
    return f'★〜{hi:g}' if lo <= 0 else f'★{lo:g}〜' if hi >= 99 else f'★{lo:g}〜{hi:g}'


def _step(x):
    """★の値 → 一番近い段の境目の番号（BAND_STEPS）"""
    return min(range(len(BAND_STEPS)), key=lambda i: (abs(BAND_STEPS[i] - x), i))


def band_stars(v, base=None):
    """★の帯の指示（intent.band_of で整えた値）→ [下, 上]。[下, 上] はそのまま。段の数（+＝難しく）なら、base（曲の設定の★の帯・
    無い・★全部は新しい曲の既定 DEFAULT の★）の両端を段の境目（BAND_STEPS）でその数だけずらす（下は ★0・上は ★99 で止まる。
    幅は1段より狭くしない）。下が開いた帯（★〜x）を難しくする時は、上の2段の帯として数える（★〜8.5 を ★5〜10 にすると ★6.5〜8.5 の
    曲が両方に入ったままで、選ばれるテーマの半分が曲の設定と同じだった。★6.5〜10 なら 4 割）。
    例: ★〜8.5 の1段難しく＝★6.5〜10・2段＝★8.5〜12・1段やさしく＝★〜6.5・★6.5〜10 の1段難しく＝★8.5〜12・★8.5〜12 の1段難しく＝★10〜"""
    from .intent import band_of
    v = band_of(v)
    if v is None:
        return None
    if isinstance(v, list):
        return v
    lo, hi = base if base and not (base[0] <= 0 and base[1] >= 99) else DEFAULT['stars']
    i, j = _step(lo), _step(hi)
    j = max(j, i + 1)
    if v > 0 and i == 0:
        i = max(0, j - 2)
    n = len(BAND_STEPS) - 1
    i2 = min(max(0, i + v), n - 1)
    j2 = min(max(i2 + 1, j + v), n)
    return [BAND_STEPS[i2], BAND_STEPS[j2]]


def band_filters(song, v, freq=None):
    """曲の設定（--library の中身・作業ファイルの library。無い＝新しい曲の既定 DEFAULT）と★の帯の指示 → 帯の書き出しの絞り込み（★だけ変える）。
    時期が自動のまま来たら（曲が分からない）年は絞らない（compose は先に resolve する）。
    freq＝型の頻度を上書き（「珍しい型まで」と一緒で、曲の設定が頻度を絞っている時の「珍しい」）"""
    f = concrete(filters_of(song) if song else DEFAULT)
    f['stars'] = band_stars(v, f.get('stars'))
    if freq:
        f['freq'] = freq
    return f


def export_band(song, v, cache=None, freq=None):
    """★の帯を変えた書き出し（export と同じ形・使えなければ Unavailable＝呼ぶ側はその帯を効かせない）。
    cache（辞書）があれば同じ絞り込みは使い回す（1回の作り直しの中で同じ帯は1回だけ書き出す）。
    型ごとに「その帯らしさ」（band_lift）を足す＝帯を変えた時は、その帯らしい型を優先する（style.pick）"""
    f = band_filters(song, v, freq)
    key = json.dumps(f, sort_keys=True, ensure_ascii=False)
    if cache is not None and key in cache:
        return cache[key]
    lib = export(f)
    band_lift(lib, band_base(song), cache)
    if cache is not None:
        cache[key] = lib
    return lib


# ---- その帯らしさ（2026-10-26 利用者「帯を変えた時は、その帯らしい型を優先する」・docs/アプリ仕様.md 12 節） ----
# よくある型（上下の往復等）はどの帯にもあって曲の個性に一番合うので、帯を変えても選ばれ続けた（★〜8 の曲で 1段難しくしても、選ばれる
# 24 テーマのうち 9〜10 が曲の設定と同じ）。型ごとに「帯の中で型が出る曲の割合 ÷ 曲の設定のライブラリ（比べる束）の中の割合」を持たせ、
# テーマ選びでその log を足す（style.W_LIFT・theme.lift_score）。どの帯でも同じくらい出る型は 1 前後（点は 0）・帯を変えた先で特に
# よく出る型は 1 より大きい・曲の設定の帯でよく出る型は 1 より小さい。
LIFT_PRIOR = 5   # 割合を数える時に両方へ足す曲の数（2〜3 曲にしか出ない型の比が大きく振れすぎないように。2 だと帯にだけ 2 曲出る型も
                 # 1.55 倍になり、選ばれる型の曲の数の中央値が 5〜6 だった。5 で 7〜8＝その帯で「よく使われている」型が残る）


def band_base(song):
    """比べる束の絞り込み＝曲の設定のライブラリ（無い＝新しい曲の既定 DEFAULT＝帯をずらす元と同じ）。頻度・難しさは外す（数えるだけ）"""
    f = concrete(filters_of(song) if song else DEFAULT)
    return {k: v for k, v in f.items() if k not in ('freq', 'hard')}


def band_counts(f):
    """絞り込みの中で型が出る曲の数 → (曲の数, {('pair', a, b) か ('hand', cycle): 曲の数})。2 曲以上に出る型だけ（書き出しと同じ）"""
    lib = library_db.export_themes(dict(f, once=False))
    m = {}
    for q in lib.get('pairs') or []:
        m[('pair', _tup(q['a']), _tup(q['b']))] = q['maps']
    for h in lib.get('hands') or []:
        m[('hand', _tup(h['cycle']))] = h['maps']
    return lib.get('songs') or 0, m


def _tup(cyc):
    return tuple(tuple(s) for s in cyc)


def lift_of(m_band, s_band, m_base, s_base, prior=None):
    """その帯らしさ＝(帯の中で型が出る曲の割合) ÷ (比べる束の中の割合)。両方に prior 曲（無ければ LIFT_PRIOR）を足して数える"""
    c = LIFT_PRIOR if prior is None else prior
    return ((m_band + c) / (s_band + c)) / ((m_base + c) / (s_base + c))


def band_lift(lib, base, cache=None):
    """帯の書き出し lib（export の結果）の型ごとに lift（その帯らしさ・lift_of）を足し、lib['library']['band'] に比べた束の印を付ける
    （style.pick はこの印がある時だけ、その帯らしさを点に入れる）。帯が比べる束と同じ・数えられない時は何もしない（今までと同じ選び方）。
    cache があれば比べる束の数は使い回す"""
    L = lib.get('library') if isinstance(lib, dict) else None
    if not isinstance(L, dict) or not (lib.get('pairs') or lib.get('hands')):
        return lib
    bf = {k: v for k, v in (L.get('filters') or {}).items() if k not in ('freq', 'hard')}
    if bf == base or not lib.get('songs'):
        return lib
    key = 'base:' + json.dumps(base, sort_keys=True, ensure_ascii=False)
    try:
        got = cache[key] if cache is not None and key in cache else band_counts(base)
    except ERRORS:
        return lib
    if cache is not None:
        cache[key] = got
    sb, mb = got
    if not sb:
        return lib
    s = lib['songs']
    for q in lib.get('pairs') or []:
        q['lift'] = round(lift_of(q['maps'], s, mb.get(('pair', _tup(q['a']), _tup(q['b'])), 0), sb), 4)
    for h in lib.get('hands') or []:
        h['lift'] = round(lift_of(h['maps'], s, mb.get(('hand', _tup(h['cycle'])), 0), sb), 4)
    L['band'] = {'base': base.get('stars'), 'base_songs': sb, 'prior': LIFT_PRIOR}
    return lib
