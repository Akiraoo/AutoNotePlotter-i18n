"""見え始める距離（JD）の狙いの表（automap/njs.py の JD_TARGET）を型のデータベースのランク譜面から測り直す（読むだけ・2026-11-10）。

データベース（diffs）は NJS を持つがオフセット（_noteJumpStartBeatOffset）を持たないので、譜面のフォルダ（maps の place・folder＝手元の
CustomLevels か生データの maps/）の Info.dat から読む。JD はゲームと同じ式（njs.jd_of）。難易度ごとの中央値を年の区切りごとに出す。

  .venv/Scripts/python.exe -I tools/library_build/jd_table.py [--since 2023] [--db …]

場所は設定（library_db・library_root・custom_levels）から。出した表を njs.JD_TARGET に写す時は JD_SINCE とコメントの日付も直す。
"""
import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT))
import library_stats as LS  # noqa: E402
from automap import config as AC  # noqa: E402
from automap import diffs, njs  # noqa: E402


def rows(db, raw_root, local_root):
    """ランク譜面（BeatLeader でランクの難易度・Standard）→ [{diff, njs, offset, bpm, year, jd, rt}]"""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    rs = con.execute(
        "SELECT m.place, m.folder, d.pos, d.difficulty, d.njs, m.bpm, m.year FROM diffs d JOIN maps m ON m.id = d.map_id "
        "WHERE d.bl_ranked AND d.characteristic = 'Standard' AND m.bpm > 0 AND d.njs IS NOT NULL").fetchall()
    infos, out = {}, []
    for place, folder, pos, diff, n, bpm, year in rs:
        path = (Path(local_root) / folder) if place == 'local' else (Path(raw_root) / 'maps' / folder)
        if path not in infos:
            ip = LS.find(str(path), 'Info.dat')
            infos[path] = LS.load(ip) if ip else None
        info, k, bm = infos[path], -1, None
        for s in (info or {}).get('_difficultyBeatmapSets', []):   # pos＝全部の特性を通した並び（build_db.parse_map と同じ）
            for b in s.get('_difficultyBeatmaps', []):
                k += 1
                if k == pos:
                    bm = b
        if bm is None or diff not in diffs.ORDER:
            continue
        off = float(bm.get('_noteJumpStartBeatOffset') or 0)
        jd, rt = njs.jd_of(n, off, bpm)
        out.append({'diff': diff, 'njs': float(n), 'offset': off, 'bpm': float(bpm), 'year': year, 'jd': jd, 'rt': rt})
    return out


def table(rs, since):
    """難易度 → (JD の中央値 0.1 m・数)"""
    out = {}
    for d in diffs.ORDER:
        v = [r['jd'] for r in rs if r['diff'] == d and (r['year'] or 0) >= since]
        if v:
            out[d] = (round(statistics.median(v), 1), len(v))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--since', type=int, default=njs.JD_SINCE)
    ap.add_argument('--db')
    a = ap.parse_args()
    cfg = json.loads(AC.path().read_text(encoding='utf-8'))
    rs = rows(a.db or cfg['library_db'], cfg['library_root'], cfg['custom_levels'])
    print(f'ランク譜面 {len(rs)} 難易度・オフセットを入れている {sum(r["offset"] != 0 for r in rs) / max(1, len(rs)):.0%}')
    for since in sorted({a.since, 2020, 2022, 2024}):
        t = table(rs, since)
        print(f'{since} 年以降: ' + '・'.join(f'{diffs.TEXT[d]} {v}m（{n}）' for d, (v, n) in t.items()))
    t = table(rs, a.since)
    print(f'\nJD_TARGET（{a.since} 年以降）= ' + json.dumps({d: v for d, (v, _) in t.items()}))
    now = {d: njs.JD_TARGET.get(d) for d in t}
    print('今の njs.JD_TARGET と ' + ('同じ' if all(now[d] == t[d][0] for d in t) and a.since == njs.JD_SINCE else f'違う（今 {now}・{njs.JD_SINCE} 年以降）'))


if __name__ == '__main__':
    main()
