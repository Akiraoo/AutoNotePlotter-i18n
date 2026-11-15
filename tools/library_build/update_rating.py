"""BeatLeader の★の付け直し（PP の版の更新）に追従する（docs/ライブラリ仕様.md 6.11・2026-11-07 利用者）。

★の物差しの組（automap/rating_scale.py＝nlm-rating・型のデータベース・★から決めた数）をまとめて入れ替える。2 段に分ける＝入れ替える前に
比べの表を見て、★の帯の境目を変えるかなどを人が決める:

  python -I tools/library_build/update_rating.py prepare --exe <新しい nlm-rating.exe> [--skip-fetch]
      1. 今の一覧・★の近似を控える（置き場の bl.<前の版>-<日付>/・rating.nlm-rating-<前の版>/。捨てない）
      2. BeatLeader の一覧・新しいランク譜面・★の近似の測り直し（fetch.py all。exe は環境変数で渡す＝設定は変えない）
      3. データベースと配布用のライブラリを別の名前で作る（library.new.sqlite・library-dist.new.sqlite・元と同じ答えかも確かめる）
      4. 比べの表 <データベースのフォルダ>/update_rating_<版>.md（★の動き・帯の境目の案・型の数・NJS の式）
      動いているアプリには触らない。
  python -I tools/library_build/update_rating.py apply [--bands keep|proposed|0,5,6.5,8.5,10,12,99]
      データベース 2 つを置き換え・設定の nlm_rating_exe を新しい exe に・automap/rating_scale.json を書く（アプリを閉じてから）。
      --bands＝★の帯の境目（既定 keep＝今のまま・proposed＝比べの表の案）。動かすと前の境目の読み替え（moved）も書く＝前に決めた設定は
      作業ファイルを読む時に今の境目へ読み替わる（automap/rating_scale.migrate_work）。

この後は人の手で: テスト → コミット → リリースする時はアプリの版を上げる（automap/version.py の VERSION と CHANGES）。
"""
import argparse
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

from automap import config, library_db as DB, library_use as LU, njs, rating_scale as RS, theme  # noqa: E402

HERE = Path(__file__).resolve().parent
SINCE = '2015'   # 取るランク譜面の年の下限（6.9 で全部の年代に広げた）
EDGES = RS.BANDS[1:-1]   # 今の★の帯の境目（0 と 99 を除く）
EDGE_WARN = 0.3   # 帯の境目が同じ割合の所からこれだけ動いたら、表に見直しの印を出す
EDGE_STEP = 0.5   # 境目の案の刻み
QUANTS = (0.1, 0.25, 0.5, 0.75, 0.9)
NJS_EXAMPLES = (('ExpertPlus', 120, 5.0), ('Expert', 170, 7.0), ('Hard', 120, 3.5), ('Normal', 120, 2.5), ('Easy', 100, 1.5))


def paths():
    db = C.db_path(None)
    return {'db': db, 'dist': db.with_name('library-dist.sqlite'), 'new': db.with_name('library.new.sqlite'),
            'new_dist': db.with_name('library-dist.new.sqlite'), 'state': db.with_name('update_rating.json')}


def _info(db):
    con = sqlite3.connect(f'file:{Path(db).as_posix()}?mode=ro', uri=True)
    try:
        return DB.info_of(con)
    finally:
        con.close()


def _main_version(info):
    """データベースの★の近似を一番多く測った nlm-rating の版"""
    v = info.get('approx_versions') or {}
    return max(v, key=v.get) if v else None


def backup(root, info, log=print):
    """今の一覧・★の近似を控える（もう控えがあれば飛ばす）→ 控えた場所"""
    ver = _main_version(info) or 'unknown'
    day = str(info.get('bl_list_at') or '')[:10].replace('-', '') or 'unknown'
    out = []
    for src, name in ((root / 'bl', f'bl.{ver}-{day}'), (root / 'rating', f'rating.nlm-rating-{ver}')):
        dst = root / name
        if src.is_dir() and not dst.exists():
            log(f'控える: {src} → {dst}')
            shutil.copytree(src, dst)
            out.append(dst)
    return out


def _run(args, env=None):
    subprocess.run([sys.executable, '-I', *map(str, args)], check=True, env={**os.environ, **(env or {}), 'PYTHONIOENCODING': 'utf-8'})


# ---- 比べの表 ----

def ranked_diffs(db):
    """ランク譜面の難易度 → {(hash, 難易度): (★, 1秒のノーツ)}（BeatLeader の★だけ・近似は入れない）"""
    con = sqlite3.connect(f'file:{Path(db).as_posix()}?mode=ro', uri=True)
    try:
        return {(h, d): (s, n) for h, d, s, n in con.execute(
            "SELECT m.hash, d.difficulty, d.stars, d.nps FROM diffs d JOIN maps m ON m.id = d.map_id "
            "WHERE d.bl_ranked AND d.stars IS NOT NULL AND d.characteristic = 'Standard' AND m.hash IS NOT NULL")}
    finally:
        con.close()


def quantile(sorted_values, q):
    """並べた値の q の所（線でつなぐ）"""
    v = sorted_values
    if not v:
        return None
    x = q * (len(v) - 1)
    i = int(x)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (x - i)


def edge_shift(old, new, edges=EDGES):
    """前の★の境目と同じ割合の所が今の★でいくつか → [(境目, 前の割合, 今の★)]"""
    a, b = sorted(old), sorted(new)
    return [(e, sum(x < e for x in a) / len(a), quantile(b, sum(x < e for x in a) / len(a))) for e in edges] if a and b else []


def proposed_bands(old, new, edges=EDGES):
    """★の帯の境目の案: 前の境目と同じ割合の所を EDGE_STEP 刻みに丸める（下の境目より必ず上）→ BANDS の形（0・境目・99）。
    old・new＝ランク譜面の★の並び。比べられなければ今のまま"""
    out = [0]
    for e, _, v in edge_shift(old, new, edges):
        out.append(RS._num(max(round(v / EDGE_STEP) * EDGE_STEP, out[-1] + EDGE_STEP)))
    return out + [99] if len(out) > 1 else [0, *edges, 99]


def next_moved(old_bands, new_bands, moved):
    """前の境目 → 今の境目の表（前に動いた分も今の境目まで）。今の境目にある値は読み替えない＝何度通してもよい → rating_scale.json の moved"""
    step = {float(a): b for a, b in zip(old_bands, new_bands) if a != b}
    out = {float(k): step.get(float(v), v) for k, v in moved.items()}
    out.update(step)
    cur = {float(x) for x in new_bands}
    return {f'{k:g}': v for k, v in sorted(out.items()) if k not in cur}


def band_of(s, edges=EDGES):
    return sum(s >= e for e in edges)


def star_report(old, new):
    """ランク譜面の★の動き → 表の行（old・new＝ranked_diffs の答え）"""
    both = [k for k in new if k in old and old[k][0]]
    ratios = sorted(new[k][0] / old[k][0] for k in both)
    oldv, newv = sorted(v[0] for v in old.values()), sorted(v[0] for v in new.values())
    moved = sum(band_of(old[k][0]) != band_of(new[k][0]) for k in both)
    L = ['## ランク譜面の★の動き（BeatLeader の値・Standard）', '',
         f'- 難易度 {len(old)} → {len(new)}（増えた {len(set(new) - set(old))}・無くなった {len(set(old) - set(new))}）',
         f'- 同じ難易度 {len(both)} の 今÷前: 中央 {quantile(ratios, 0.5):.3f}・5% {quantile(ratios, 0.05):.3f}・95% {quantile(ratios, 0.95):.3f}' if both else '- 同じ難易度なし',
         f'- ★の帯（{"・".join(map(str, EDGES))}）をまたいだ難易度 {moved}（{moved / max(1, len(both)):.1%}）', '',
         '| 分位 | 前 | 今 |', '|---|---|---|']
    L += [f'| {int(q * 100)}% | ★{quantile(oldv, q):.2f} | ★{quantile(newv, q):.2f} |' for q in QUANTS]
    L += ['', '## ★の帯の境目（前の境目と同じ割合の所が、今の★でいくつか）', '', '| 境目 | 前にそれより下の割合 | 今の★ | ずれ |', '|---|---|---|---|']
    warn = False
    shift = edge_shift([x[0] for x in old.values()], [x[0] for x in new.values()])
    for e, f, v in shift:
        far = abs(v - e) >= EDGE_WARN
        warn |= far
        L.append(f'| ★{e} | {f:.1%} | ★{v:.2f} | {v - e:+.2f}{" ⚠" if far else ""} |')
    L += ['', f'⚠ が付いた境目（{EDGE_WARN} 以上）は、★の帯の意味が変わっている＝境目を動かすかを決める'
          f'（案 {proposed_bands([x[0] for x in old.values()], [x[0] for x in new.values()])}・apply --bands proposed）。'
          if warn else f'どの境目も {EDGE_WARN} より小さい＝境目はそのままでよい目安。', '']
    L += ['## 今の境目の★の帯ごとの難易度の数と 1 秒のノーツの中央値', '', '| 帯 | 数 前→今 | 1 秒のノーツ 前→今 |', '|---|---|---|']
    lows = (0,) + EDGES
    for i, lo in enumerate(lows):
        name = f'★{lo}〜{EDGES[i]}' if i < len(EDGES) else f'★{lo}〜'
        o = [v[1] for v in old.values() if band_of(v[0]) == i and v[1]]
        n = [v[1] for v in new.values() if band_of(v[0]) == i and v[1]]
        L.append(f'| {name} | {len(o)} → {len(n)} | {statistics.median(o) if o else 0:.2f} → {statistics.median(n) if n else 0:.2f} |')
    return L + ['']


def filter_report(old_db, new_db, proposed):
    """画面で選べる帯ごとの曲・テーマに使える型の数（前のデータベース／今のデータベースで同じ境目／今のデータベースで案の境目）→ 表の行"""
    def cnt(st, db):
        lib = DB.export_themes({'sources': ['ranked'], 'stars': st, 'diffs': ['Expert', 'ExpertPlus']}, db=db)
        return f'{lib.get("songs")}・{len(theme.load_themes(lib))}'
    L = ['## 帯ごとの曲・テーマに使える型の数（ランク・全部の年代・Expert／Expert+）', '', '| 今の帯 | 前 | 同じ境目のまま | 案の境目 |', '|---|---|---|---|']
    for a, b in zip(LU.band_choices(RS.BANDS), LU.band_choices(proposed)):
        L.append(f'| {LU.stars_text(a)} | {cnt(a, old_db)} | {cnt(a, new_db)} | {LU.stars_text(b)}：{cnt(b, new_db)} |')
    return L + ['']


def njs_report(coef):
    """NJS の式の前後 → 表の行（coef＝njs.fit の答え）"""
    L = ['## NJS の式（automap/njs.py）', '', f'- 今の係数の例: ★×{njs.COEF["stars"]["x"]} → ★×{coef["stars"]["x"]}・'
         f'切片 {njs.COEF["stars"]["base"]} → {coef["stars"]["base"]}・BPM×{njs.COEF["stars"]["bpm"]} → {coef["stars"]["bpm"]}',
         f'- 式の当たり（ずれの中央）: {coef["stars"].get("err")}（{coef["stars"].get("n")} 難易度）', '',
         '| 難易度 | BPM | ★ | NJS 前→今 |', '|---|---|---|---|']
    for d, bpm, s in NJS_EXAMPLES:
        c = coef['stars']
        v = c['base'] + c['x'] * s + c['bpm'] * bpm + c['diff'][d]
        L.append(f'| {d} | {bpm} | {s} | {njs.suggest(d, bpm, stars=s)[0]} → {min(njs.RANGE[1], max(njs.RANGE[0], round(v / njs.STEP) * njs.STEP))} |')
    return L + ['']


def nps_ref(db, bands):
    """★の帯の 1 秒のノーツの中央値（library_use.band_nps と同じ束）→ rating_scale.json の nps_ref。bands＝BANDS の形"""
    out = {}
    for lo, hi in zip(bands[:5], bands[1:6]):
        q = ((DB.diff_stats(dict(LU.NPS_FILTERS, stars=[lo, hi]), db=db) or {}).get('all') or {}).get('nps_q1_med_q3')
        out[f'{lo:g}-{hi:g}'] = round(float(q[1]), 1) if q and q[1] else RS.NPS_REF.get((lo, hi))
    return out


def report(old_db, new_db, ver, coef, proposed):
    a, b = _info(old_db), _info(new_db)
    head = [f'# ★の物差しの更新の比べ（nlm-rating {_main_version(a)} → {ver}）', '',
            f'- 物差し: {RS.of(_main_version(a))} → {RS.of(ver)}（今のアプリの設定は {RS.SCALE}）',
            f'- BeatLeader の一覧を取った時: {a.get("bl_list_at")} → {b.get("bl_list_at")}',
            f'- 譜面 {a.get("maps")} → {b.get("maps")}・難易度 {a.get("diffs")} → {b.get("diffs")}',
            f'- ★の近似を測った版: {a.get("approx_versions")} → {b.get("approx_versions")}',
            f'- ★の帯の境目: 今 {list(RS.BANDS)}・案 {proposed}',
            f'- ★の帯の 1 秒のノーツの参考の値: {RS.NPS_REF} → 同じ境目 {nps_ref(new_db, RS.BANDS)}・案 {nps_ref(new_db, proposed)}', '']
    return '\n'.join(head + star_report(ranked_diffs(old_db), ranked_diffs(new_db)) + filter_report(old_db, new_db, proposed) + njs_report(coef))


# ---- 手順 ----

def cmd_prepare(a):
    P = paths()
    exe = Path(a.exe)
    ver = RS.exe_version(exe)
    if not ver:
        raise SystemExit(f'nlm-rating の版が読めない: {exe}')
    root = C.raw_root(None)
    old = _info(P['db'])
    print(f'nlm-rating {_main_version(old)} → {ver}（物差し {RS.of(ver)}）')
    if not a.skip_fetch:
        backup(root, old)
        _run([HERE / 'fetch.py', 'all', '--skip-local', '--since', SINCE], env={'NLM_RATING_EXE': str(exe)})
    _run([HERE / 'build_db.py', '--db', P['new']])
    _run([HERE / 'make_dist.py', '--db', P['new'], '--out', P['new_dist']])
    bad = RS.problems(db=P['new'], scale=RS.of(ver))
    if bad:   # 測り直しが済んでいない（--skip-fetch の時など）
        raise SystemExit('\n'.join(bad))
    coef = njs.fit(P['new'])
    old_stars, new_stars = [[v[0] for v in ranked_diffs(db).values()] for db in (P['db'], P['new'])]
    proposed = proposed_bands(old_stars, new_stars)
    text = report(P['db'], P['new'], ver, coef, proposed)
    out = P['db'].with_name(f'update_rating_{ver}.md')
    out.write_text(text, encoding='utf-8')
    C.write_json(P['state'], {'exe': str(exe), 'version': ver, 'scale': RS.of(ver), 'bl_list_at': _info(P['new']).get('bl_list_at'), 'njs': coef,
                              'proposed': proposed}, indent=1)
    print(text)
    print(f'比べの表: {out}\n良ければアプリを閉じて apply（元のデータベース・設定はまだ変えていない）')


def bands_of(arg, proposed):
    """--bands の値 → BANDS の形（0 から 99 まで 7 つ・上がり続ける）"""
    if arg == 'keep':
        return list(RS.BANDS)
    if arg == 'proposed':
        return list(proposed)
    b = [RS._num(x) for x in arg.split(',')]
    if len(b) != len(RS.BANDS) or b[0] != 0 or b[-1] != 99 or any(x >= y for x, y in zip(b, b[1:])):
        raise SystemExit(f'--bands は 0 で始まり 99 で終わる上がり続ける {len(RS.BANDS)} つの数: {arg}')
    return b


def write_scale(state, data=None):
    """automap/rating_scale.json を書く（改行は LF・行が読めるように字下げ）"""
    p = Path(data or RS.DATA)
    d = {'scale': state['scale'], 'nlm_rating': state['version'], 'bl_list_at': state['bl_list_at'], 'bands': state['bands'], 'moved': state['moved'],
         'njs': state['njs'], 'nps_ref': state['nps_ref']}
    p.write_bytes((json.dumps(d, ensure_ascii=False, indent=1) + '\n').encode('utf-8'))


def cmd_apply(a):
    P = paths()
    state = C.read_json(P['state'])
    if not state:
        raise SystemExit(f'先に prepare（{P["state"]} が無い）')
    bands = bands_of(a.bands, state['proposed'])
    try:
        for src, dst in ((P['new'], P['db']), (P['new_dist'], P['dist'])):
            if src.exists():   # 途中で止まってやり直す時は、済んだ物を飛ばす
                os.replace(src, dst)
    except PermissionError:
        raise SystemExit('データベースを使っているプロセスがあって置き換えられない（アプリを閉じてから apply をやり直す）')
    config.update({'nlm_rating_exe': state['exe']})
    moved = next_moved(RS.BANDS, bands, {f'{k:g}': v for k, v in RS.MOVED.items()})
    write_scale(dict(state, bands=bands, moved=moved, nps_ref=nps_ref(P['db'], bands)))
    bad = RS.problems(exe=state['exe'], db=P['db'], scale=state['scale']) + RS.problems(db=P['dist'], scale=state['scale'])
    if bad:
        raise SystemExit('\n'.join(bad))
    P['state'].unlink()
    print(f'物差しを {state["scale"]}（nlm-rating {state["version"]}）にした。★の帯の境目 {bands}・前の境目の読み替え {moved}。automap/rating_scale.json を書いた。\n'
          'この後: アプリを起動し直す → テスト → コミット → リリースする時は automap/version.py の VERSION を上げて CHANGES に一言')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--exe', required=True, help='新しい nlm-rating.exe')
    p.add_argument('--skip-fetch', action='store_true', help='一覧の取り直しと測り直しが済んでいる時（控えも取らない）')
    q = sub.add_parser('apply')
    q.add_argument('--bands', default='keep', help='★の帯の境目: keep（今のまま）・proposed（比べの表の案）・0,5,6.5,8.5,10,12,99')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    {'prepare': cmd_prepare, 'apply': cmd_apply}[a.cmd](a)


if __name__ == '__main__':
    main()
