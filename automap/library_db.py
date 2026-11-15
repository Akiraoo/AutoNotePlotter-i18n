"""型のライブラリ（探すためのデータベース・SQLite）を読む口（docs/ライブラリ仕様.md 7 節）。作るのは tools/library_build/build_db.py。

アプリと作る側はここだけを使う:
- open_db(path=None): 開く（場所は引数・環境変数 AUTOMAP_LIBRARY・設定（automap/config.py）の library_db か library_root/library.sqlite・
  配布物の data/library-dist.sqlite の順）
- export_themes(filters, out_path=None): 絞り込みの中で数え直した型を tools/library_themes.py が書く形（前の cache/themes.json）と同じ形で返す（足す物は項目を足すだけ）
- diff_stats(filters): 絞り込んだ難易度の打ち方の数字（tools/library_stats.py の analyze と同じ数え方）

filters（辞書・全部省略可）: sources（'ranked'＝BeatLeader のランクの難易度・'local'＝手元の譜面。省略は両方）・stars [下, 上]（★。
近似を含む・approx=False で BeatLeader の★だけ）・years [から, まで]（BeatSaver のアップロード年）・mappers／exclude_mappers・
diffs（既定 ['Expert', 'ExpertPlus']）・freq（使う頻度の上限: '定番'／'よくある'／'珍しい'）・hard（使う難しさの上限: 'やさしい'／'ふつう'／'難しい'）・
on_beatsaver（True＝BeatSaver に無い手元の譜面を全部除く）・include_own（True＝自分で書き出した手元の譜面も入れる。既定は除く。
どれが自分の物か（maps.own）は作る時に決める＝tools/library_build/build_db.own_reasons: Info.dat の ANP の印・プレイリストの ANP の行・
作業の場所の .nlmf の書き出すフォルダ名・書き出しの記録・設定の library_own（フォルダ名の型）。library_own の「!」で始まる型に合う物は除かない）・
once（False＝1回だけの並びを出さない）・
once_min（1回だけの並びを出す最小の曲の数・既定 2）・once_limit（頻度の区分ごとに出す数の上限・既定 1000）。
"""
import json
import os
import sqlite3
import statistics
from pathlib import Path

from . import config

SCHEMA_VERSION = 2    # 表の形の版（2: maps.own＝自分で書き出した手元の譜面の印）
EXTRACT_VERSION = 1   # 型の決め方の版（tools/library_themes.py の関数・1回だけの並びの決め方）
ROOT = Path(__file__).resolve().parent.parent
CONFIG = config.path()
BUNDLED = config.app_root() / 'data' / 'library-dist.sqlite'   # 配布物に入れた配布用のライブラリ（tools/library_build/make_dist.py・配布物のふりは同梱物の場所）
FREQ = ('定番', 'よくある', '珍しい')
HARD = ('やさしい', 'ふつう', '難しい')
DEFAULT_DIFFS = ('Expert', 'ExpertPlus')


class LibraryError(Exception):
    pass


def db_path(path=None):
    p = path or os.environ.get('AUTOMAP_LIBRARY')
    if not p:
        try:
            cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cfg = {}
        p = cfg.get('library_db') or (Path(cfg['library_root']) / 'library.sqlite' if cfg.get('library_root') else None)
    if not p and BUNDLED.exists():
        p = BUNDLED
    if not p:
        raise LibraryError('型のライブラリが無い（配布物の data/library-dist.sqlite・設定の library_db か library_root・環境変数 AUTOMAP_LIBRARY）')
    p = Path(p)
    return p / 'library.sqlite' if p.is_dir() else p


def open_db(path=None):
    """データベースを読むだけで開く。版が合わなければ LibraryError（作り直す: tools/library_build/build_db.py）"""
    if isinstance(path, sqlite3.Connection):
        return path
    p = db_path(path)
    if not p.exists():
        raise LibraryError(f'ライブラリが無い: {p}（tools/library_build/build_db.py で作る）')
    con = sqlite3.connect(f'file:{p.as_posix()}?mode=ro', uri=True)
    info = info_of(con)
    if info.get('schema_version') != SCHEMA_VERSION or info.get('extract_version') != EXTRACT_VERSION:
        con.close()
        raise LibraryError(f'ライブラリの版が合わない（表 {info.get("schema_version")}・型の決め方 {info.get("extract_version")}。'
                           f'この版は表 {SCHEMA_VERSION}・型の決め方 {EXTRACT_VERSION}）→ tools/library_build/build_db.py で作り直す')
    return con


def info_of(con):
    try:
        return {k: json.loads(v) for k, v in con.execute('SELECT k, v FROM info')}
    except sqlite3.DatabaseError:
        return {}


def _names(js):
    return {n.lower() for n in json.loads(js or '[]') if n}


def _select(con, f, themes=True):
    """絞り込みに入る難易度 → {難易度の id: (曲の id, 1拍の秒, ★, 年, 並び)}。
    themes＝library_themes.py と同じ決まり（ノーツ 50 以上・Expert／Expert+ で読めない所がある曲は曲ごと除く）"""
    ranks = set(f.get('diffs') or DEFAULT_DIFFS)
    srcs = set(f.get('sources') or ('ranked', 'local'))
    stars, years = f.get('stars'), f.get('years')
    if not isinstance(years, (list, tuple)):   # 時期の「自動」（library_use.AUTO）が曲の時期に置き換えられずに来た＝年は絞らない
        years = None
    yset = f.get('year_set')   # 選んだ年の一覧（歯抜けあり・2026-11-15・library_use.normalize）。years（範囲）より先に見る
    yset = {int(y) for y in yset} if isinstance(yset, (list, tuple)) and yset else None
    want = {m.lower() for m in f.get('mappers') or []}
    drop = {m.lower() for m in f.get('exclude_mappers') or []}
    rows = con.execute(
        'SELECT d.id, d.map_id, d.difficulty, d.missing, d.mods, d.bpm_change, d.notes, d.err, d.bl_ranked, d.stars, d.star_approx, d.pos, '
        'd.stats IS NOT NULL, m.place, m.hash, m.ord, m.bpm, m.year, m.mappers, m.v4, m.err, m.on_beatsaver, m.own '
        'FROM diffs d JOIN maps m ON m.id = d.map_id WHERE d.characteristic = ?', ('Standard',)).fetchall()
    bad = {r[1] for r in rows if r[2] in ranks and r[7]} if themes else set()
    local_hashes = {r[14] for r in rows if r[13] == 'local' and r[14]}
    ranked_copy = {}   # ランクの版ごとに1つ（同じ版が手元にも取った物にもある時は並びの早い物＝手元）
    for r in sorted(rows, key=lambda r: r[15]):
        if r[14]:
            ranked_copy.setdefault(r[14], r[1])
    out = {}
    for (did, mid, rank, missing, mods, bpmch, notes, err, blr, st, approx, pos, has_stats,
         place, h, ordv, bpm, year, mappers, v4, merr, onbs, own) in rows:
        if rank not in ranks or missing or mods or bpmch or v4 or merr or mid in bad or not bpm or bpm <= 0:
            continue
        if own and not f.get('include_own'):
            continue
        if themes and (err or (notes or 0) < 50):
            continue
        if not themes and not has_stats:
            continue
        take = 'local' in srcs and place == 'local'
        if not take and 'ranked' in srcs and blr:
            take = ranked_copy.get(h) == mid and not ('local' in srcs and h in local_hashes)
        if not take:
            continue
        if f.get('on_beatsaver') and not onbs:
            continue
        if stars and (st is None or not (stars[0] <= st <= stars[1]) or (approx and f.get('approx') is False)):
            continue
        if yset is not None:
            if year is None or int(year) not in yset:
                continue
        elif years and (year is None or not (years[0] <= year <= years[1])):
            continue
        if want or drop:
            ns = _names(mappers)
            if want and not any(w == n or w in n for n in ns for w in want):
                continue
            if drop and any(w == n or w in n for n in ns for w in drop):
                continue
        out[did] = (mid, 60 / bpm, st, year, (ordv, pos))
    return out


def _sel_table(con, sel):
    con.execute('CREATE TEMP TABLE IF NOT EXISTS sel (diff_id INTEGER PRIMARY KEY, map_id INTEGER, spb REAL, stars REAL)')
    con.execute('DELETE FROM sel')
    con.executemany('INSERT INTO sel VALUES (?,?,?,?)', ((d, v[0], v[1], v[2]) for d, v in sel.items()))


def _freq(maps, songs):
    if maps >= max(5, 0.05 * songs):
        return FREQ[0]
    if maps >= max(3, 0.01 * songs):
        return FREQ[1]
    return FREQ[2]


def _classify_hard(items, star_mid):
    """置き方の難しさの点＝形（build_db.hard_parts）＋振りの速さ（同じ手の振りの間 0.3 秒より短いほど）＋★の中央値×0.2。
    区分は絞り込みの中の三分位"""
    for it in items:
        sec = it['sec']
        speed = max(0.0, (0.30 - sec) / 0.10)
        st = it['stars'] if it['stars'] is not None else star_mid
        it['hard'] = {'score': round(it['_hs'] + speed + 0.2 * (st or 0), 3), 'shape': it['_hs'], 'speed': round(speed, 3),
                      'stars': st, 'parts': it['_hp']}
    sc = sorted(it['hard']['score'] for it in items)
    if sc:
        t1, t2 = sc[len(sc) // 3], sc[(2 * len(sc)) // 3]
        for it in items:
            s = it['hard']['score']
            it['hard']['class'] = HARD[0] if s < t1 else HARD[1] if s < t2 else HARD[2]


def export_themes(filters=None, out_path=None, db=None):
    """絞り込みの中で数え直した型（tools/library_themes.py が書く形＋足した項目）。out_path があれば同じ形で書く"""
    f = dict(filters or {})
    con = open_db(db)
    sel = _select(con, f)
    _sel_table(con, sel)
    songs = len({v[0] for v in sel.values()})
    acc = {}
    for pid, kind, did, runs, gaps, first in con.execute(
            "SELECT o.pattern_id, p.kind, o.diff_id, o.runs, o.gaps, o.first FROM occurrences o JOIN sel s ON s.diff_id = o.diff_id "
            "JOIN patterns p ON p.id = o.pattern_id WHERE p.kind IN ('hand', 'pair')"):
        mid, spb, st, year, (ordv, pos) = sel[did]
        a = acc.get(pid)
        if a is None:
            a = acc[pid] = {'maps': set(), 'runs': 0, 'gap': [], 'sec': [], 'first': (ordv, pos, first), 'stars': [], 'years': [],
                            'diffs': 0}
        g = json.loads(gaps)
        a['maps'].add(mid)
        a['runs'] += runs
        a['gap'] += g
        a['sec'] += [x * spb for x in g]
        a['first'] = min(a['first'], (ordv, pos, first))
        a['diffs'] += 1
        if st is not None:
            a['stars'].append(st)
        if year is not None:
            a['years'].append(year)
    keep = [pid for pid, a in acc.items() if len(a['maps']) >= 2]
    pats = {}
    for i in range(0, len(keep), 900):
        ch = keep[i:i + 900]
        for row in con.execute(f'SELECT id, kind, key, cells, move, row, diag, width, shape_a, shape_b, hard_shape, hard_parts '
                               f'FROM patterns WHERE id IN ({",".join("?" * len(ch))})', ch):
            pats[row[0]] = row
    all_stars = sorted(v[2] for v in sel.values() if v[2] is not None)
    star_mid = statistics.median(all_stars) if all_stars else None

    def pack(pid, extra):
        a, p = acc[pid], pats[pid]
        r = {**extra, 'maps': len(a['maps']), 'runs': a['runs'], 'gap': round(statistics.median(a['gap']), 3),
             'sec': round(statistics.median(a['sec']), 3)}
        r.update(stars=round(statistics.median(a['stars']), 2) if a['stars'] else None,
                 years=[min(a['years']), max(a['years'])] if a['years'] else None, diffs=a['diffs'],
                 freq=_freq(len(a['maps']), songs), _hs=p[10], _hp=json.loads(p[11]), _first=a['first'])
        return r

    hands, pairs = [], []
    for pid in keep:
        p = pats[pid]
        if p[1] == 'hand':
            hands.append(pack(pid, {'cycle': json.loads(p[2]), 'cells': p[3], 'move': p[4], 'row': p[5], 'diag': p[6], 'width': p[7]}))
        else:
            a, b = p[2].split('|')
            pairs.append(pack(pid, {'a': json.loads(a), 'b': json.loads(b), 'shape_a': json.loads(p[8]), 'shape_b': json.loads(p[9])}))
    out = {'songs': songs, 'ranks': list(f.get('diffs') or DEFAULT_DIFFS)}
    for name, items in (('hands', hands), ('pairs', pairs)):
        _classify_hard(items, star_mid)
        items.sort(key=lambda r: (-r['maps'], r['_first']))   # 同じ数は最初に出てきた順（library_themes.py と同じ）
        items[:] = [_limit(it, f) for it in items if _ok(it, f)]
        out[name] = items
    if f.get('once', True):
        out['once'] = _once(con, f, songs, star_mid)
    info = info_of(con)
    out['library'] = {'built_at': info.get('built_at'), 'schema_version': info.get('schema_version'),
                      'extract_version': info.get('extract_version'), 'filters': f}
    if db is None or not isinstance(db, sqlite3.Connection):
        con.close()
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as fp:
            json.dump(out, fp, ensure_ascii=False, indent=0)
    return out


def _ok(it, f):
    if f.get('freq') and FREQ.index(it['freq']) > FREQ.index(f['freq']):
        return False
    if f.get('hard') and HARD.index(it['hard']['class']) > HARD.index(f['hard']):
        return False
    return True


def _limit(it, f):
    for k in ('_hs', '_hp', '_first'):
        it.pop(k, None)
    return it


def _once(con, f, songs, star_mid):
    """1回だけの並び（くり返しの外の片手の4振り・右手の形）: 絞り込みの中で何曲に出たか。頻度の区分ごとに曲の数の多い順に once_limit まで。
    gap・sec・stars は難易度ごとの値の平均（中央値ではない・速さのため）"""
    mn, lim = f.get('once_min', 2), f.get('once_limit', 1000)
    rows = con.execute(
        'SELECT o.pattern_id, COUNT(DISTINCT s.map_id) AS m, SUM(o.n), AVG(o.gap), AVG(o.gap * s.spb), AVG(s.stars) '
        'FROM once_occ o JOIN sel s ON s.diff_id = o.diff_id GROUP BY o.pattern_id HAVING m >= ? ORDER BY m DESC, o.pattern_id',
        (mn,)).fetchall()
    per, keep = {}, []
    for r in rows:
        c = _freq(r[1], songs)
        if lim and per.get(c, 0) >= lim:
            continue
        per[c] = per.get(c, 0) + 1
        keep.append(r)
    pats = {}
    ids = [r[0] for r in keep]
    for i in range(0, len(ids), 900):
        ch = ids[i:i + 900]
        for row in con.execute(f'SELECT id, key, cells, move, row, diag, width, hard_shape, hard_parts FROM patterns '
                               f'WHERE id IN ({",".join("?" * len(ch))})', ch):
            pats[row[0]] = row
    items = []
    for pid, m, n, gap, sec, st in keep:
        p = pats[pid]
        items.append({'seq': json.loads(p[1]), 'cells': p[2], 'move': p[3], 'row': p[4], 'diag': p[5], 'width': p[6],
                      'maps': m, 'count': n, 'gap': round(gap, 3), 'sec': round(sec, 3), 'stars': round(st, 2) if st is not None else None,
                      'freq': _freq(m, songs), '_hs': p[7], '_hp': json.loads(p[8])})
    _classify_hard(items, star_mid)
    return [_limit(it, f) for it in items if _ok(it, f)]


def _summary(rs):
    """library_stats.py の main の難易度ごとのまとめと同じ数え方"""
    def med(fn):
        v = sorted(x for x in (fn(r) for r in rs) if x is not None)
        if not v:
            return None
        return [round(v[len(v) // 4], 3), round(statistics.median(v), 3), round(v[(len(v) * 3) // 4], 3)]

    def mean_dict(name):
        acc = {}
        for r in rs:
            for kk, vv in (r.get(name) or {}).items():
                acc[kk] = acc.get(kk, 0) + vv
        return {kk: round(vv / len(rs), 3) for kk, vv in sorted(acc.items(), key=lambda x: -x[1])}

    return {
        'maps': len(rs),
        'nps_q1_med_q3': med(lambda r: r['nps']),
        'njs_q1_med_q3': med(lambda r: r.get('njs')),
        'double_rate': med(lambda r: r['dbl']),
        'alt_rate': med(lambda r: r.get('alt')),
        'reset_rate': med(lambda r: r.get('reset')),
        'swing_gap_p10_sec': med(lambda r: r.get('swing_gap_p10')),
        'swing_gap_med_sec': med(lambda r: r.get('swing_gap_med')),
        'grid_mean': mean_dict('grid'),
        'gap_mean': mean_dict('gap'),
        'dir_mean': mean_dict('dir'),
        'angle_mean': mean_dict('ang'),
        'row_mean': [round(sum(r['row'][i] for r in rs) / len(rs), 3) for i in range(3)],
        'col_mean': [round(sum(r['col'][i] for r in rs) / len(rs), 3) for i in range(4)],
        'bombs_pm': med(lambda r: r['bombs_pm']),
        'arcs_pm': med(lambda r: r['arcs_pm']),
        'chains_pm': med(lambda r: r['chains_pm']),
    }


def diff_stats(filters=None, db=None):
    """絞り込んだ難易度の打ち方の数字（段・列・向き・1秒のノーツの数・振りの速さの分布…）。難易度の名前ごと（ranks）と全部（all）"""
    f = dict(filters or {})
    con = open_db(db)
    sel = _select(con, f, themes=False)
    _sel_table(con, sel)
    by = {}
    for did, rank, stats in con.execute('SELECT d.id, d.difficulty, d.stats FROM diffs d JOIN sel s ON s.diff_id = d.id'):
        by.setdefault(rank, []).append(json.loads(stats))
    if db is None or not isinstance(db, sqlite3.Connection):
        con.close()
    allr = [r for v in by.values() for r in v]
    return {'diffs': len(allr), 'songs': len({v[0] for v in sel.values()}),
            'ranks': {k: _summary(v) for k, v in by.items()}, 'all': _summary(allr) if allr else None}
