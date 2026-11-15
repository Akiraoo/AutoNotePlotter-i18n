"""曲どうしの似方（docs/方針.md 6.22）: 作った譜面（.nlmf）を2つ以上並べて、曲の組ごとの重なりと曲の中の変化を Markdown で出す。

物差し（数え方は automap/stats.py の hand_seqs・tri_counts・one_counts・overlap・variety・cell_stats）:
- 振り＝その手のノーツの 1/8 拍以内の続きは先頭だけ（stats.beat_swings）。左手は左右反転して右手の形 (rx, y, 向き) にそろえる。
- 3振りの並びの重なり＝その手の3つ続く振りの並びの多重集合の Σmin ÷ 少ない方の数（曲の組ごと・平均）。置き方の重なり＝1振りで同じ。
- 曲の中の変化＝100振りあたりの3振りの並びの種類・ばらつき（エントロピー bit）・上位10の並びの割合。
- よく使う2マスの割合（top2）・同じ2振りの往復（A B A＝その手の振りが2つ前と同じ）の割合（aba）。
- --ref: ランク譜面（型のライブラリのデータベース・Expert+・Standard・テンポの変化なし・振り 200 以上・1秒の振り 3.5〜6）の
  違う作者の組と同じ作者の違う曲の組（種 1 でそれぞれ 600 組まで）の中央値と 25〜75%。

難易度は --diff（無ければ結果のファイルの作業ファイル <…>.automap.json の diff・それも無ければ Expert+）。ミュートしたレーンは入れない。

使い方（データベースの場所は app/config.local.json の library_db・読むだけで開く）:
  .venv/Scripts/python.exe -I tools/song_similarity.py a.nlmf b.nlmf [...] [--diff Expert+] [--ref [--ref-sps 3.5 6]]
      [--db library.sqlite] [--md 表.md]
"""
import argparse
import itertools
import json
import random
import sqlite3
import sys
import zlib
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:   # python -I では台本のフォルダが sys.path に入らない
    sys.path.insert(0, str(REPO))

from automap import diffs, nlmf, stats  # noqa: E402

REF_SPS = (3.5, 6.0)   # ランク譜面の基準の 1秒の振りの帯
REF_MIN_SWINGS = 200   # これより振りの少ない譜面は基準に入れない
REF_PAIRS = 600        # 組の数の上限（違う作者・同じ作者の違う曲のそれぞれ）
REF_SEED = 1


def diff_of(path, diff=None):
    """数える難易度の名前（'ExpertPlus' 等）: 引数 → 作業ファイルの diff → Expert+"""
    if diff:
        return diffs.name_of(diff)
    p = Path(path)
    w = p.with_name(p.name[:-len('.nlmf')] + '.automap.json') if p.name.endswith('.nlmf') else None
    if w is not None and w.exists():
        try:
            return diffs.name_of(json.loads(w.read_text(encoding='utf-8')).get('diff') or diffs.DEFAULT)
        except (ValueError, json.JSONDecodeError):
            pass
    return diffs.DEFAULT


def song_swings(path, diff=None):
    """作った譜面 → (難易度の名前, 左手の振り, 右手の振り)（stats.beat_swings）"""
    proj = nlmf.load(path)
    d = diff_of(path, diff)
    k = next((k for k in proj.get('difficulties') or {} if k.lower() == diffs.key(d)), None)
    if k is None:
        raise SystemExit(f'{Path(path).name} に難易度 {diffs.TEXT[d]} が無い')
    ns = nlmf.clip_notes(proj, k, include_muted=False)
    return (d, *stats.note_swings(ns))


def label(path, used):
    """表の曲の名前（ファイル名の最初の「.」まで・重なれば名前のまま）"""
    n = Path(path).name
    s = n.split('.')[0] or n
    return n if s in used else s


def pairs_table(names, tri, one):
    """曲の組ごとの重なり → (表の行, 3振りの平均, 置き方の平均)"""
    rows, t3, t1 = [], [], []
    for a, b in itertools.combinations(range(len(names)), 2):
        x, y = stats.overlap(tri[a], tri[b]), stats.overlap(one[a], one[b])
        t3.append(x)
        t1.append(y)
        rows.append(f'| {names[a]} | {names[b]} | {x * 100:.0f}% | {y * 100:.0f}% |')
    return rows, sum(t3) / len(t3), sum(t1) / len(t1)


def _q(v):
    """中央値（25〜75%）の文字（試しの台本と同じ取り方: 並べた位置 n/2・n/4・3n/4）"""
    v = sorted(v)
    return f'{v[len(v) // 2] * 100:.0f}%（{v[len(v) // 4] * 100:.0f}〜{v[3 * len(v) // 4] * 100:.0f}%）'


def ref_data(db, sps_band=REF_SPS):
    """ランク譜面の基準の譜面 {diff_id: (3振りの並びの数, 置き方の数, 作者, 譜面の id)}（1秒の振りが sps_band の中の物）"""
    con = sqlite3.connect(f'file:{Path(db).as_posix()}?mode=ro', uri=True)
    rows = con.execute("SELECT d.id, m.level_author, m.id, m.bpm FROM diffs d JOIN maps m ON m.id = d.map_id WHERE d.bl_ranked AND "
                       "d.characteristic = 'Standard' AND d.difficulty = 'ExpertPlus' AND NOT d.bpm_change AND m.bpm > 0 "
                       'ORDER BY d.id').fetchall()
    data = {}
    for did, au, mid, bpm in rows:
        sw = {h: [tuple(s) for s in json.loads(zlib.decompress(b))]
              for h, b in con.execute('SELECT hand, data FROM swings WHERE diff_id = ?', (did,))}
        if 0 not in sw or 1 not in sw:
            continue
        allb = sorted(s[0] for c in (0, 1) for s in sw[c])
        if len(allb) < REF_MIN_SWINGS or allb[-1] <= allb[0]:
            continue
        sps = len(allb) / ((allb[-1] - allb[0]) * 60 / bpm)
        if not sps_band[0] <= sps <= sps_band[1]:
            continue
        seqs = stats.hand_seqs(sw[0], sw[1])
        data[did] = (stats.tri_counts(seqs), stats.one_counts(seqs), (au or '').lower().strip(), mid)
    con.close()
    return data


def ref_pairs(data, n=REF_PAIRS, seed=REF_SEED):
    """違う作者の組・同じ作者の違う曲の組（それぞれ n 組まで・種で決まる）"""
    rng = random.Random(seed)
    ids = list(data)
    by = defaultdict(list)
    for i in ids:
        by[data[i][2]].append(i)
    diff_pairs = []
    if len(by) > 1:
        tries = 0
        while len(diff_pairs) < n and tries < n * 100:
            tries += 1
            a, b = rng.sample(ids, 2)
            if data[a][2] != data[b][2]:
                diff_pairs.append((a, b))
    same_pairs = [(a, b) for au, l in by.items() if au for a, b in itertools.combinations(l, 2) if data[a][3] != data[b][3]]
    rng.shuffle(same_pairs)
    return diff_pairs, same_pairs[:n]


def ref_lines(db, sps_band=REF_SPS):
    data = ref_data(db, sps_band)
    dp, sp = ref_pairs(data)
    out = ['', f'## ランク譜面の基準（Expert+・1秒の振り {sps_band[0]}〜{sps_band[1]}・譜面 {len(data)}・種 {REF_SEED}）', '',
           '| 組 | 数 | 3振りの並びの重なり | 置き方の重なり |', '|---|---|---|---|']
    for name, ps in (('違う作者', dp), ('同じ作者の違う曲', sp)):
        if not ps:
            out.append(f'| {name} | 0 | | |')
            continue
        t3 = [stats.overlap(data[a][0], data[b][0]) for a, b in ps]
        t1 = [stats.overlap(data[a][1], data[b][1]) for a, b in ps]
        out.append(f'| {name} | {len(ps)} | {_q(t3)} | {_q(t1)} |')
    out.append('')
    out.append('中央値（25〜75%）。')
    return out


def report(files, diff=None, db=None, ref=False, ref_sps=REF_SPS):
    names, tri, one, rows = [], [], [], []
    for f in files:
        d, sw_l, sw_r = song_swings(f, diff)
        seqs = stats.hand_seqs(sw_l, sw_r)
        nm = label(f, names)
        names.append(nm)
        tri.append(stats.tri_counts(seqs))
        one.append(stats.one_counts(seqs))
        v = stats.variety(seqs)
        c = stats.cell_stats(sw_l, sw_r)
        sw = sum(len(s) for s in seqs)
        rows.append(f'| {nm} | {diffs.TEXT[d]} | {sw} | {v.get("kinds", 0):.1f} | {v.get("entropy", 0):.2f} | '
                    f'{v.get("top10", 0) * 100:.0f}% | {c.get("top2", 0) * 100:.0f}% | {c.get("aba", 0) * 100:.0f}% |')
    out = ['# 曲どうしの似方（docs/方針.md 6.22）', '']
    if len(files) > 1:
        pr, m3, m1 = pairs_table(names, tri, one)
        out += [f'- 3振りの並びの重なり 平均 **{m3 * 100:.0f}%**・置き方（1振り）の重なり 平均 **{m1 * 100:.0f}%**（曲の組 {len(pr)}）', '',
                '## 曲の組ごと', '', '| 曲 | 曲 | 3振りの並び | 置き方 |', '|---|---|---|---|'] + pr
    out += ['', '## 曲ごと（曲の中の変化・使うマスの偏り）', '',
            '| 曲 | 難易度 | 振り | 3振りの並びの種類（100振りあたり） | ばらつき（bit） | 上位10の割合 | よく使う2マス | 同じ2振りの往復（A B A） |',
            '|---|---|---|---|---|---|---|---|'] + rows
    if ref:
        out += ref_lines(db_path(db), ref_sps)
    return '\n'.join(out) + '\n'


def db_path(arg=None):
    if arg:
        return Path(arg)
    cfg = json.loads((REPO / 'app' / 'config.local.json').read_text(encoding='utf-8'))
    return Path(cfg['library_db'])


def main(argv=None):
    ap = argparse.ArgumentParser(description='曲どうしの似方（作った譜面の曲の組ごとの重なり・曲の中の変化）')
    ap.add_argument('nlmf', nargs='+', help='作った譜面（.nlmf）を2つ以上（1つなら曲ごとの表だけ）')
    ap.add_argument('--diff', help='数える難易度（無ければ作業ファイルの diff・それも無ければ Expert+）')
    ap.add_argument('--ref', action='store_true', help='ランク譜面の基準も出す（型のライブラリのデータベースを読む）')
    ap.add_argument('--ref-sps', nargs=2, type=float, default=list(REF_SPS), metavar=('下', '上'),
                    help=f'基準にするランク譜面の 1秒の振りの帯（既定 {REF_SPS[0]} {REF_SPS[1]}）')
    ap.add_argument('--db', help='型のライブラリのデータベース（既定は app/config.local.json の library_db）')
    ap.add_argument('--md', help='表を書く場所（無ければ画面に出す）')
    a = ap.parse_args(argv)
    md = report(a.nlmf, a.diff, a.db, a.ref, tuple(a.ref_sps))
    if a.md:
        Path(a.md).write_text(md, encoding='utf-8')
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(md)


if __name__ == '__main__':
    main()
