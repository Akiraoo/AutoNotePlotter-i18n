"""型のライブラリ（build_db.py で作ったデータベース）から、配布用のライブラリを作る（docs/ライブラリ仕様.md 6.10・docs/アプリ仕様.md 21 節）。

使い方: python -I tools/library_build/make_dist.py [--db <library.sqlite>] [--out <library-dist.sqlite>] [--no-check]
新しいランク譜面を取り込んだら: fetch.py all --skip-local → build_db.py → make_dist.py（作るたびに元のデータベースと同じ答えになるかを確かめる）。

元の譜面は他人の作品なので、譜面に戻せる物は入れない（2026-11-03 利用者と決めた）:
- BeatLeader のランクの譜面だけ（手元にしか無い譜面・自分で書き出した譜面は入れない）。同じ版は1つ（library_db._select の決まり）。
- swings の表（全部の振りの拍・列・段・向き）は入れない。区間の点検（automap/section_check.py）に要る分だけ、片手の3・4振りの並びの番号を
  REF_BEATS 拍の切れ目ごとに順番を捨てて入れる（grams の表・拍は持たない）。
- 型がどこに出たか（occurrences の spans・once_occ の beats）は入れない。occurrences の first は難易度の中の順位に、gaps は並べ替えて入れる
  （どちらも答えは変わらない＝最初に出てきた順の比べと中央値にしか使わない）。
- 曲名・アーティスト・作者・譜面の hash／key・フォルダ・BeatSaver の評価は入れない（年・★・BPM・難易度ごとの数字は残す）。
  作者で絞る（mappers・exclude_mappers）は配布用では効かない。
- 型（2〜8 振りの短い動き）は 1 曲にしか出ない物も全部入れる（利用者）。
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from automap import library_db as DB  # noqa: E402
from automap import section_check as SC  # noqa: E402

DIST_VERSION = 1    # 配布用の中身の決まりの版（入れる物を変えたら上げる）
TABLES = """
CREATE TABLE info (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE maps (
  id INTEGER PRIMARY KEY, place TEXT, folder TEXT, ord INTEGER, hash TEXT, key TEXT,
  ranked INTEGER, on_beatsaver INTEGER, song TEXT, sub TEXT, artist TEXT, level_author TEXT, mappers TEXT,
  uploaded TEXT, year INTEGER, bpm REAL, duration REAL, upvotes INTEGER, downvotes INTEGER, score REAL, curated INTEGER,
  v4 INTEGER, err TEXT, own INTEGER);
CREATE TABLE diffs (
  id INTEGER PRIMARY KEY, map_id INTEGER, pos INTEGER, characteristic TEXT, difficulty TEXT, filename TEXT, missing INTEGER,
  mods INTEGER, version TEXT, bpm_change INTEGER, notes INTEGER, bombs INTEGER, arcs INTEGER, chains INTEGER, njs REAL, nps REAL,
  bl_ranked INTEGER, stars REAL, star_approx INTEGER, pass REAL, tech REAL, acc REAL, ranked_time INTEGER,
  err TEXT, xerr TEXT, stats TEXT);
CREATE TABLE grams (diff_id INTEGER, hand INTEGER, data BLOB, PRIMARY KEY (diff_id, hand));
CREATE TABLE patterns (
  id INTEGER PRIMARY KEY, kind TEXT, key TEXT, n INTEGER, cells INTEGER, move REAL, row REAL, diag REAL, width INTEGER,
  shape_a TEXT, shape_b TEXT, hard_shape REAL, hard_parts TEXT, UNIQUE (kind, key));
CREATE TABLE occurrences (
  pattern_id INTEGER, diff_id INTEGER, runs INTEGER, reps INTEGER, gaps TEXT, first INTEGER, spans TEXT);
CREATE TABLE once_occ (pattern_id INTEGER, diff_id INTEGER, n INTEGER, gap REAL, beats TEXT);
"""
INDEXES = """
CREATE INDEX occ_diff ON occurrences (diff_id);
CREATE INDEX occ_pat ON occurrences (pattern_id);
CREATE INDEX once_diff ON once_occ (diff_id);
CREATE INDEX diffs_map ON diffs (map_id);
"""
KEEP_INFO = ('schema_version', 'extract_version', 'built_at', 'once_len', 'bl_list_at', 'approx_versions')
# 作るたびに元と比べる絞り込み（sources は ranked だけ＝配布用に入っている物）
CHECK_FILTERS = [
    {'sources': ['ranked'], 'stars': [0, 8], 'years': [2020, 2026], 'diffs': ['Expert', 'ExpertPlus']},
    {'sources': ['ranked']},
    {'sources': ['ranked'], 'stars': [8, 12], 'freq': 'よくある', 'hard': 'ふつう'},
    {'sources': ['ranked'], 'stars': [0, 6], 'years': [2015, 2021], 'diffs': ['Hard', 'Expert'], 'approx': False, 'on_beatsaver': True},
]
CHECK_INDEX = CHECK_FILTERS[:2]


def _chunks(xs, n=900):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def pick_maps(src):
    """配布用に入れる譜面の id: BeatLeader のランクの難易度があり、ランクの絞り込み（sources=['ranked']）で選ばれ得る物（同じ版は並びの早い1つ）"""
    rows = src.execute('SELECT d.map_id, d.bl_ranked, m.hash, m.ord, m.v4, m.err, m.bpm, m.own FROM diffs d JOIN maps m ON m.id = d.map_id '
                       'WHERE d.characteristic = ?', ('Standard',)).fetchall()
    first = {}
    for r in sorted(rows, key=lambda r: r[3]):
        if r[2]:
            first.setdefault(r[2], r[0])
    return sorted({mid for mid, blr, h, _, v4, err, bpm, own in rows
                   if blr and h and first.get(h) == mid and not v4 and not err and bpm and bpm > 0 and not own})


def make(src_path, out_path, log=print):
    t0 = time.time()
    src = DB.open_db(src_path)
    tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if 'swings' not in tables:
        src.close()   # 開いたまま止めない（閉じ忘れの ResourceWarning・テストの test_dist_same_answers_without_maps）
        raise SystemExit('元のデータベースに swings の表が無い（配布用のライブラリからは作れない・build_db.py で作った物を渡す）')
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + '.tmp')
    if tmp.exists():
        tmp.unlink()
    dst = sqlite3.connect(tmp)
    dst.executescript(TABLES)
    maps = pick_maps(src)
    for ch in _chunks(maps):
        dst.executemany('INSERT INTO maps (id, place, ord, hash, ranked, on_beatsaver, mappers, year, bpm, v4, own) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        [(mid, 'ranked', ordv, f'm{mid}', ranked, onbs, '[]', year, bpm, 0, 0) for mid, ordv, ranked, onbs, year, bpm in src.execute(
                            f'SELECT id, ord, ranked, on_beatsaver, year, bpm FROM maps WHERE id IN ({",".join("?" * len(ch))})', ch)])
    # 難易度: 入れる譜面の Standard の全部（曲ごと除く決まり＝Expert／Expert+ の読めない所を見るため）。中身はランクの難易度だけ
    cols = ('id, map_id, pos, characteristic, difficulty, missing, mods, version, bpm_change, notes, bombs, arcs, chains, njs, nps, '
            'bl_ranked, stars, star_approx, pass, tech, acc, ranked_time, err, stats')
    ranked = []
    for ch in _chunks(maps):
        rows = src.execute(f'SELECT {cols} FROM diffs WHERE characteristic = ? AND map_id IN ({",".join("?" * len(ch))})', ['Standard', *ch]).fetchall()
        out = []
        for r in rows:
            r = list(r)
            r[22] = 'x' if r[22] else None          # 読めない所があるかだけ（中身の文は入れない）
            if not r[15]:
                r[23] = None                         # ランクでない難易度は数字も入れない（選ばれない）
            else:
                ranked.append(r[0])
            out.append(r)
        dst.executemany(f'INSERT INTO diffs ({cols}) VALUES ({",".join("?" * 24)})', out)
    ranked.sort()
    used = set()
    n_occ = n_once = 0
    for ch in _chunks(ranked):
        q = ",".join("?" * len(ch))
        occ = src.execute(f'SELECT pattern_id, diff_id, runs, reps, gaps, first FROM occurrences WHERE diff_id IN ({q}) '
                          f'ORDER BY diff_id, first, pattern_id', ch).fetchall()
        rank, last, rows = 0, (None, None), []
        for pid, did, runs, reps, gaps, fst in occ:
            if did != last[0]:
                rank = 0
            elif fst != last[1]:
                rank += 1
            last = (did, fst)
            rows.append((pid, did, runs, reps, json.dumps(sorted(json.loads(gaps)), separators=(',', ':')), rank, None))
            used.add(pid)
        dst.executemany('INSERT INTO occurrences VALUES (?,?,?,?,?,?,?)', rows)
        n_occ += len(rows)
        once = src.execute(f'SELECT pattern_id, diff_id, n, gap FROM once_occ WHERE diff_id IN ({q})', ch).fetchall()
        dst.executemany('INSERT INTO once_occ VALUES (?,?,?,?,NULL)', once)
        used.update(r[0] for r in once)
        n_once += len(once)
        g = []
        for did, hand, data in src.execute(f'SELECT diff_id, hand, data FROM swings WHERE diff_id IN ({q})', ch):
            sw = json.loads(zlib.decompress(data))
            g.append((did, hand, SC.pack_grams(SC.grams(*SC.hand_codes([(s[0], tuple(s[1:4])) for s in sw], hand)))))
        dst.executemany('INSERT INTO grams VALUES (?,?,?)', g)
    for ch in _chunks(sorted(used)):
        dst.executemany('INSERT INTO patterns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', src.execute(
            f'SELECT id, kind, key, n, cells, move, row, diag, width, shape_a, shape_b, hard_shape, hard_parts FROM patterns '
            f'WHERE id IN ({",".join("?" * len(ch))})', ch).fetchall())
    dst.executescript(INDEXES)
    sinfo = DB.info_of(src)
    src.close()
    info = {k: sinfo[k] for k in KEEP_INFO if k in sinfo}
    info.update(ref_beats=SC.REF_BEATS, maps=len(maps), diffs=len(ranked),
                patterns=dict(dst.execute('SELECT kind, COUNT(*) FROM patterns GROUP BY kind').fetchall()),
                dist={'version': DIST_VERSION, 'made_at': C.now(), 'occurrences': n_occ, 'once': n_once})
    dst.executemany('INSERT INTO info VALUES (?,?)', [(k, json.dumps(v, ensure_ascii=False)) for k, v in info.items()])
    dst.commit()
    dst.execute('ANALYZE')
    dst.execute('VACUUM')
    dst.close()
    try:
        os.replace(tmp, out_path)
    except PermissionError:
        raise SystemExit(f'前の配布用のライブラリを使っているプロセスがあって置き換えられない（アプリ等を閉じてから）。作った物は {tmp}')
    log(f'できた: 譜面 {len(maps)}・ランクの難易度 {len(ranked)}・型 {info["patterns"]}・{os.path.getsize(out_path) / 1e6:.0f}MB・'
        f'{time.time() - t0:.0f} 秒 → {out_path}')
    return info


def _plain(v):
    """比べるための形（numpy の配列 → list）"""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, 'tolist'):
        return v.tolist()
    return v


def check(src_path, out_path, filters=None, index_filters=None, log=print):
    """元と配布用で、書き出す型・打ち方の数字・区間の点検の数が同じか → 違った所の一覧（空なら同じ）"""
    bad = []
    for f in filters or CHECK_FILTERS:
        a, b = DB.export_themes(f, db=src_path), DB.export_themes(f, db=out_path)
        a.pop('library'), b.pop('library')
        if a != b:
            bad.append(f'型 {json.dumps(f, ensure_ascii=False)}: 曲 {a["songs"]}→{b["songs"]}・手 {len(a["hands"])}→{len(b["hands"])}・'
                       f'組 {len(a["pairs"])}→{len(b["pairs"])}・1回 {len(a.get("once") or [])}→{len(b.get("once") or [])}')
        if DB.diff_stats(f, db=src_path) != DB.diff_stats(f, db=out_path):
            bad.append(f'数字 {json.dumps(f, ensure_ascii=False)}')
        log(f'  型・数字 {json.dumps(f, ensure_ascii=False)}: 曲 {a["songs"]}・手 {len(a["hands"])}・組 {len(a["pairs"])}・'
            f'1回 {len(a.get("once") or [])}')
    for f in index_filters or CHECK_INDEX:
        x, y = SC.build_index(f, src_path), SC.build_index(f, out_path)
        same = (x.songs == y.songs and all(_plain(x.keys[n]) == _plain(y.keys[n]) and _plain(x.counts[n]) == _plain(y.counts[n]) for n in x.keys)
                and _plain(x.ref) == _plain(y.ref))
        if not same:
            bad.append(f'区間の点検 {json.dumps(f, ensure_ascii=False)}: 曲 {x.songs}→{y.songs}')
        log(f'  区間の点検 {json.dumps(f, ensure_ascii=False)}: 曲 {x.songs}・3振り {len(x.keys[3])}・4振り {len(x.keys[4])}・'
            f'数える時間 {x.took}→{y.took} 秒')
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', help='元のデータベース（省略は設定の library_db）')
    ap.add_argument('--out', help='配布用のライブラリ（省略は元と同じフォルダの library-dist.sqlite）')
    ap.add_argument('--no-check', action='store_true', help='元と同じ答えになるかを確かめない')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    src = C.db_path(a.db)
    out = Path(a.out) if a.out else src.parent / 'library-dist.sqlite'
    make(src, out)
    if not a.no_check:
        print('元と同じ答えになるかを確かめる:')
        bad = check(src, out)
        if bad:
            print('違った:\n' + '\n'.join('  ' + b for b in bad))
            raise SystemExit(1)
        print('全部同じ')


if __name__ == '__main__':
    main()
