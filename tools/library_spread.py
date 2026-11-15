"""両手の広がり（docs/方針.md 6.21）: ランク譜面（型のライブラリのデータベース）と作った譜面（.nlmf）を同じ決まりで数える。

物差しは automap/stats.py の spread（振り＝1/8 拍以内の続きは先頭だけ・組＝もう片方の手の直前の振り 1 秒以内）:
- wide＝両手を同時に外へ（組のうち左手が列 0・右手が列 3）の割合
- in3＝両手が3列に収まる（組の2つの列が 0〜2 か 1〜3 の中）割合
- hcol＝手から見た列（右手 r=x・左手 r=3−x）の割合 [反対の外, 反対の内, 自分の内, 自分の外]
- sps＝1秒の振りの数（両手合わせて）
- top2＝よく使う2マス（手から見たマス＝右手の形の rx×3＋y）の割合・aba＝同じ2振りの往復（その手の振りが2つ前と同じ）の割合
  （stats.cell_stats・docs/方針.md 6.22）。マスの割合（cells）は 1秒の振りの帯ごとの平均の表に。

使い方（データベースの場所は app/config.local.json の library_db・読むだけで開く）:
  .venv/Scripts/python.exe -I tools/library_spread.py [作った譜面.nlmf ...] [--md 表.md] [--json 譜面ごと.json] [--db library.sqlite]
"""
import argparse
import json
import sqlite3
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:   # python -I では台本のフォルダが sys.path に入らない
    sys.path.insert(0, str(REPO))

from automap import diffs, nlmf, stats  # noqa: E402

MIN_SWINGS = 20   # これより振りの少ない譜面は数えない
MIN_PAIRS = 10    # これより組の少ない譜面は数えない
DIFF_ORDER = ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus']
STAR_BANDS = [(0, 3), (3, 5), (5, 7), (7, 10), (10, 99)]
SPS_BANDS = [(0, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 99)]


def measure(sw_l, sw_r, sec_of):
    """振り（左・右）→ stats.spread の結果。振り・組が少なすぎれば None"""
    if len(sw_l) + len(sw_r) < MIN_SWINGS:
        return None
    r = stats.spread(sw_l, sw_r, sec_of)
    if r['pairs'] < MIN_PAIRS or 'sps' not in r:
        return None
    return r


def db_path(arg=None):
    if arg:
        return Path(arg)
    cfg = json.loads((REPO / 'app' / 'config.local.json').read_text(encoding='utf-8'))
    return Path(cfg['library_db'])


def ranked(db):
    """ランク譜面（難易度ごとにランク・Standard・テンポの変化なし）の譜面ごとの値"""
    con = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
    rows = con.execute('SELECT d.id, d.difficulty, d.stars, m.bpm, m.id FROM diffs d JOIN maps m ON m.id = d.map_id '
                       "WHERE d.bl_ranked AND d.characteristic = 'Standard' AND NOT d.bpm_change AND m.bpm > 0 "
                       'AND d.stars IS NOT NULL').fetchall()
    out = []
    for did, dn, st, bpm, mid in rows:
        sw = {h: [tuple(s) for s in json.loads(zlib.decompress(b))]
              for h, b in con.execute('SELECT hand, data FROM swings WHERE diff_id = ?', (did,))}
        if 0 not in sw or 1 not in sw:
            continue
        r = measure(sw[0], sw[1], lambda b, bpm=bpm: b * 60.0 / bpm)
        if r:
            r.update(diff=dn, stars=st, bpm=bpm, map=mid, diff_id=did)
            out.append(r)
    con.close()
    return out


def generated(path):
    """作った譜面（.nlmf）の難易度ごとの値（ミュートしたレーンは入れない）"""
    proj = nlmf.load(path)
    tempo = nlmf.tempo_of(proj)
    out = []
    for k in proj.get('difficulties') or {}:
        ns = nlmf.clip_notes(proj, k, include_muted=False)
        tup = [(n['beat'], n['c'], n['x'], n['y'], n['d']) for n in ns if n.get('c') in (0, 1)]
        r = measure(stats.beat_swings(tup, 0), stats.beat_swings(tup, 1), tempo.sec)
        if r:
            try:
                dn = diffs.name_of(k)
            except ValueError:
                dn = str(k)
            r.update(diff=dn, file=Path(path).name)
            out.append(r)
    return out


def _q(vals, q):
    v = sorted(vals)
    if not v:
        return float('nan')
    i = (len(v) - 1) * q
    lo = int(i)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def _cell(rows, key, pct=True):
    v = [r[key] for r in rows if key in r]
    if not v:
        return ''
    f = (lambda x: f'{x * 100:.0f}%') if pct else (lambda x: f'{x:.2f}')
    return f'{f(_q(v, 0.5))}（{f(_q(v, 0.25))}〜{f(_q(v, 0.75))}）'


def _hcol(rows):
    return '／'.join(f'{_q([r["hcol"][k] for r in rows if "hcol" in r], 0.5) * 100:.0f}%' for k in range(4))


HEAD = ('| 組 | 譜面 | 両手を同時に外へ（wide） | 両手が3列に収まる（in3） | 手ごとの列（反対の外／反対の内／自分の内／自分の外） '
        '| 1秒の振り | ★ | よく使う2マス（top2） | 同じ2振りの往復（aba） |')
SEP = '|---|---|---|---|---|---|---|---|---|'


def _line(name, rows):
    return (f'| {name} | {len(rows)} | {_cell(rows, "wide")} | {_cell(rows, "in3")} | {_hcol(rows)} | '
            f'{_cell(rows, "sps", False)} | {_q([r["stars"] for r in rows], 0.5):.2f} | {_cell(rows, "top2")} | {_cell(rows, "aba")} |')


CELL_HEAD = ('| 組 | 譜面 | ' + ' | '.join(f'{rx}{y}' for rx in range(4) for y in range(3)) + ' |')
CELL_SEP = '|---|---|' + '---|' * 12


def _cells_line(name, rows):
    """手から見たマス（rx・段）の割合の平均（譜面ごとの割合の平均）"""
    v = [r['cells'] for r in rows if 'cells' in r]
    if not v:
        return f'| {name} | 0 |' + ' |' * 12
    return f'| {name} | {len(v)} | ' + ' | '.join(f'{sum(c[k] for c in v) / len(v) * 100:.1f}%' for k in range(12)) + ' |'


def rank_from_top(ranked_rows, key, v, higher=True):
    """ランク譜面の中で、v 以上（higher=False なら v 以下）の譜面の割合＝上から何%"""
    vals = [r[key] for r in ranked_rows if key in r]
    if not vals:
        return float('nan')
    return sum(1 for x in vals if (x >= v - 1e-12 if higher else x <= v + 1e-12)) / len(vals)


def report(R, G):
    out = ['# 両手の広がり（ランク譜面と作った譜面・docs/方針.md 6.21）', '',
           '中央値（25%〜75%）。手ごとの列は中央値だけ。', '', '## 難易度ごと', '', HEAD, SEP, _line('ランク 全部', R)]
    for d in DIFF_ORDER:
        rs = [r for r in R if r['diff'] == d]
        if rs:
            out.append(_line(f'ランク {d}', rs))
    out += ['', '## ★の帯ごと', '', HEAD, SEP]
    for lo, hi in STAR_BANDS:
        rs = [r for r in R if lo <= r['stars'] < hi]
        if rs:
            out.append(_line(f'★{lo}〜{hi if hi < 99 else ""}', rs))
    out += ['', '## 1秒の振りの数の帯ごと', '', HEAD, SEP]
    for lo, hi in SPS_BANDS:
        rs = [r for r in R if lo <= r['sps'] < hi]
        if rs:
            out.append(_line(f'振り {lo}〜{hi if hi < 99 else ""}/秒', rs))
    out += ['', '## 手から見たマスの割合（1秒の振りの数の帯ごと・譜面ごとの割合の平均）', '',
            '見出しは rx と段（rx＝右手は列 x・左手は 3−x＝0 が反対の外・3 が自分の外。段 0 が下）。', '', CELL_HEAD, CELL_SEP,
            _cells_line('ランク 全部', R)]
    for lo, hi in SPS_BANDS:
        rs = [r for r in R if lo <= r['sps'] < hi]
        if rs:
            out.append(_cells_line(f'振り {lo}〜{hi if hi < 99 else ""}/秒', rs))
    if G:
        out += ['', '## 作った譜面', '',
                '| 譜面 | 難易度 | wide | in3 | 手ごとの列（反対の外／反対の内／自分の内／自分の外） | 1秒の振り '
                '| wide の上から（全部／同じ難易度） | in3 の下から（全部） | 自分の外の上から（全部） '
                '| top2 | aba | top2 の上から（全部／同じ帯） | aba の上から（全部／同じ帯） |',
                '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
        for g in G:
            same = [r for r in R if r['diff'] == g['diff']]
            out.append(f'| {g["file"]} | {g["diff"]} | {g["wide"] * 100:.0f}% | {g["in3"] * 100:.0f}% | '
                       + '／'.join(f'{v * 100:.0f}%' for v in g['hcol'])
                       + f' | {g["sps"]:.2f} | {rank_from_top(R, "wide", g["wide"]) * 100:.1f}%／'
                       f'{rank_from_top(same, "wide", g["wide"]) * 100:.1f}% | '
                       f'{rank_from_top(R, "in3", g["in3"], higher=False) * 100:.1f}% | '
                       f'{rank_from_top([dict(o=r["hcol"][3]) for r in R], "o", g["hcol"][3]) * 100:.1f}% | '
                       + _gen_cells(R, g) + ' |')
    return '\n'.join(out) + '\n'


def sps_band(v):
    """1秒の振りの数 → SPS_BANDS の帯（無ければ None）"""
    return next(((lo, hi) for lo, hi in SPS_BANDS if lo <= v < hi), None)


def _gen_cells(R, g):
    """作った譜面の top2・aba と、ランク譜面の中の位置（上から何%・全部／同じ 1秒の振りの帯）"""
    if 'top2' not in g or 'aba' not in g:
        return ' |  |  | '
    b = sps_band(g['sps'])
    same = [r for r in R if b and b[0] <= r['sps'] < b[1]]
    pos = lambda k: f'{rank_from_top(R, k, g[k]) * 100:.1f}%／{rank_from_top(same, k, g[k]) * 100:.1f}%'
    return f'{g["top2"] * 100:.0f}% | {g["aba"] * 100:.0f}% | {pos("top2")} | {pos("aba")}'


def main(argv=None):
    ap = argparse.ArgumentParser(description='両手の広がり（ランク譜面と作った譜面を同じ決まりで数える）')
    ap.add_argument('nlmf', nargs='*', help='並べる作った譜面（.nlmf）')
    ap.add_argument('--db', help='型のライブラリのデータベース（既定は app/config.local.json の library_db）')
    ap.add_argument('--md', help='表を書く場所（無ければ画面に出す）')
    ap.add_argument('--json', help='譜面ごとの値を書く場所')
    a = ap.parse_args(argv)
    R = ranked(db_path(a.db))
    G = [g for f in a.nlmf for g in sorted(generated(f), key=lambda g: DIFF_ORDER.index(g['diff']) if g['diff'] in DIFF_ORDER else 99)]
    md = report(R, G)
    if a.md:
        Path(a.md).write_text(md, encoding='utf-8')
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(md)
    if a.json:
        Path(a.json).write_text(json.dumps({'ranked': R, 'generated': G}, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
