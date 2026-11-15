"""手元の譜面フォルダの人の譜面が、曲の流れ（盛り上がり・くり返し・途切れ・転調）にどう合わせているかを数える（読むだけ）。

使い方（.venv の Python）:
  1. 曲を選ぶ: tools/library_music.py pick <CustomLevels>
     評価（BeatSaver の score・賛成の数）は cache/library_ratings.json（BeatSaver の /maps/ids で取った物）から。
     歌の入っていそうなジャンルのタグ・Standard の Expert か Expert+・1.5〜6分・BPM の変化と曲の時刻のずらしの無い曲から、
     「評価の高い組」（score 0.95 以上・賛成 50 以上）と、同じ数の「ほかの手元の組」（score 0.9 未満・種で決まる抜き出し）を選ぶ
     → cache/lib_set.json と、音を分ける一覧 cache/lib_sep.txt。
  2. 音を分ける: .venv-sep/Scripts/python.exe tools/separate.py --list cache/lib_sep.txt --shifts 1（cache/lib/<フォルダ名の頭>/）
評価の高い譜面ほど曲の流れに合わせて変えているかも見る（利用者の案: 評価の高い譜面と手元の譜面の両方で）。
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from eval_vocal import map_of  # noqa: E402
from library_stats import find, load, parse_diff  # noqa: E402

VOCAL_TAGS = {'j-pop', 'j-rock', 'anime', 'pop', 'k-pop', 'vocaloid', 'rock', 'vtuber', 'alternative', 'punk', 'metal', 'rb', 'soul',
              'hip-hop-rap', 'nightcore', 'folk-acoustic', 'jazz', 'funk-disco', 'indie'}
NOT_VOCAL = {'instrumental', 'classical-orchestral', 'video-game-soundtrack', 'drum-and-bass', 'dubstep', 'speedcore', 'hardcore'}


def usable(root, key, m):
    """使える曲なら map_of の結果（BPM・音源・難易度・ノーツの拍…）"""
    md = m.get('metadata') or {}
    diffs = {x[0] for x in m.get('diffs', []) if x[1] == 'Standard'}
    if not (VOCAL_TAGS & set(m['tags'])) or NOT_VOCAL & set(m['tags']):
        return None
    if not ({'Expert', 'ExpertPlus'} & diffs) or not 90 <= (md.get('duration') or 0) <= 360 or not m.get('folder'):
        return None
    folder = os.path.join(root, m['folder'])
    try:
        info = load(find(folder, 'Info.dat'))
        if '_difficultyBeatmapSets' not in info:   # v4 の Info は読まない
            return None
        r = map_of(folder, 'ExpertPlus')
    except Exception:
        return None
    if not r or not r['song'] or abs(r['offset']) > 1e-6:
        return None
    return r


def pick(a):
    rt = json.loads((ROOT / 'cache' / 'library_ratings.json').read_text(encoding='utf-8'))
    sc = lambda m: (m.get('stats') or {}).get('score', 0)
    up = lambda m: (m.get('stats') or {}).get('upvotes', 0)
    hi, lo = [], []
    for k, m in sorted(rt.items()):
        r = usable(a.root, k, m)
        if not r:
            continue
        row = {'key': k, 'folder': m['folder'], 'song': r['song'], 'bpm': r['bpm'], 'diff': r['diff'], 'name': r['name'], 'mapper': r['mapper'],
               'score': sc(m), 'upvotes': up(m), 'blRanked': bool(m.get('blRanked')), 'curated': bool(m.get('curated'))}
        if sc(m) >= 0.95 and up(m) >= 50:
            hi.append(dict(row, group='高評価'))
        elif sc(m) < 0.9:
            lo.append(dict(row, group='手元'))
    pool = len(lo)
    random.Random(a.seed).shuffle(lo)
    lo = sorted(lo[:len(hi)], key=lambda r: r['key'])
    rows = hi + lo
    (ROOT / 'cache' / 'lib_set.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    (ROOT / 'cache' / 'lib_sep.txt').write_text(''.join(f"{r['song']}\t{ROOT / 'cache' / 'lib' / r['key']}\n" for r in rows), encoding='utf-8')
    print(f'高評価 {len(hi)} 曲・手元 {len(lo)} 曲（手元の候補 {pool}）→ cache/lib_set.json・cache/lib_sep.txt')


# ---- 人の譜面と曲の流れ ----

MIRROR_D = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}


def chart_of(folder, diff):
    """その難易度の色ノーツ [(拍, 色, x, y, 向き)]（拍の順）"""
    info = load(find(folder, 'Info.dat'))
    for s in info['_difficultyBeatmapSets']:
        if s.get('_beatmapCharacteristicName') != 'Standard':
            continue
        for bm in s['_difficultyBeatmaps']:
            if bm['_difficulty'] == diff:
                notes = parse_diff(load(find(folder, bm['_beatmapFilename'])))[0]
                return sorted(n for n in notes if n[1] in (0, 1) and 0 <= n[2] <= 3 and 0 <= n[3] <= 2)
    return []


def bar_chart(notes, bars, end):
    """小節ごとの譜面の数字: dens（1拍あたりのノーツ）・dbl（両手同時の打点の割合）・move（同じ手の前のノーツからの動き・マス）・
    top（上の段の割合）・pat（ノーツの並び＝(1/4 拍の位置, 色, x, y, 向き) の集まり）"""
    import numpy as np
    edges = list(bars) + [end]
    prev = {}
    out = []
    k = 0
    for i in range(len(bars)):
        b0, b1 = edges[i], edges[i + 1]
        ns = []
        while k < len(notes) and notes[k][0] < b1 - 1e-6:
            if notes[k][0] >= b0 - 1e-6:
                ns.append(notes[k])
            else:
                prev[notes[k][1]] = notes[k]
            k += 1
        times = {}
        for n in ns:
            times.setdefault(round(n[0], 3), set()).add(n[1])
        mv = []
        for n in ns:
            p = prev.get(n[1])
            if p is not None and n[0] - p[0] > 0.126:   # スライダー・スタックは数えない
                mv.append(((n[2] - p[2]) ** 2 + (n[3] - p[3]) ** 2) ** 0.5)
            prev[n[1]] = n
        out.append({'dens': len(ns) / max(b1 - b0, 1e-6), 'dbl': (sum(1 for v in times.values() if len(v) == 2) / len(times)) if times else np.nan,
                    'move': float(np.mean(mv)) if mv else np.nan, 'top': (sum(1 for n in ns if n[3] == 2) / len(ns)) if ns else np.nan,
                    'pat': {(round((n[0] - b0) * 4), n[1], n[2], n[3], n[4]) for n in ns}})
    return out


def _sim(a, b, rhythm=False):
    """2つの小節の並びの一致（そのまま・左右反転の大きい方）。rhythm＝時刻と手だけ（置き場所・向きは見ない）。どちらかが空なら None"""
    if not a or not b:
        return None
    if rhythm:
        a, b = {(o, c) for o, c, *_ in a}, {(o, c) for o, c, *_ in b}
        mir = {(o, 1 - c) for o, c in b}
    else:
        mir = {(o, 1 - c, 3 - x, y, MIRROR_D.get(d, d)) for o, c, x, y, d in b}
    return max(len(a & b), len(a & mir)) / max(len(a), len(b))


def song_measure(row):
    """1曲分: 曲の流れ（music.analyze・拍 0＝音源の頭）と人の譜面を小節ごとに突き合わせた数字"""
    import numpy as np
    from scipy.stats import spearmanr
    from automap import music, rhythm
    stems = ROOT / 'cache' / 'lib' / row['key']
    if not (stems / 'separate.json').exists():
        return None
    try:
        bpm = float(row['bpm'])
        secs = json.loads((stems / 'separate.json').read_text(encoding='utf-8'))['seconds']
        n_beats = int(secs * bpm / 60)
        rhythm.analyze(stems, bpm, 0)
        ons = json.loads((stems / 'onsets.json').read_text(encoding='utf-8'))['onsets']
        mu = music.analyze(stems, ons, bpm, 0, n_beats)
        notes = chart_of(os.path.join(row['root'], row['folder']), row['diff'])
    except Exception as e:
        return {'key': row['key'], 'error': str(e)}
    bars, it = mu['bars'], mu['inten']
    ch = bar_chart(notes, bars, n_beats)
    f = lambda k: np.array([np.nan if v is None else v for v in it[k]], float)
    c = lambda k: np.array([x[k] for x in ch], float)
    res = {'key': row['key'], 'group': row['group'], 'name': row['name'], 'mapper': row['mapper'], 'bars': len(bars), 'corr': {}}
    played = c('dens') > 0
    # 盛り上がり: 曲の手がかりと譜面の数字の順位の相関（ノーツのある小節だけ）
    for mk in ('drum', 'width', 'bands'):
        for ck in ('dens', 'dbl', 'move', 'top'):
            x, y = f(mk), c(ck)
            ok = played & ~np.isnan(x) & ~np.isnan(y)
            if ok.sum() >= 12 and np.std(x[ok]) > 0 and np.std(y[ok]) > 0:
                res['corr'][f'{mk}~{ck}'] = float(spearmanr(x[ok], y[ok])[0])
    # 盛り上がりの上 1/3 と下 1/3 の小節の差（ドラムの勢い）
    x = f('drum')
    ok = played & ~np.isnan(x)
    if ok.sum() >= 12:
        lo_, hi_ = np.percentile(x[ok], [33, 67])
        for ck in ('dens', 'dbl', 'move', 'top'):
            y = c(ck)
            a_, b_ = y[ok & (x <= lo_)], y[ok & (x >= hi_)]
            a_, b_ = a_[~np.isnan(a_)], b_[~np.isnan(b_)]
            if len(a_) and len(b_):
                res.setdefault('drum_hilo', {})[ck] = [float(np.mean(a_)), float(np.mean(b_))]
    # くり返し: 同じ記号の一番近い前の小節と、違う記号の一番近い前の小節での、譜面の並びの一致
    for lk in ('mel', 'acc'):
        lab = mu['lab'][lk]
        same, diff, rs, rd = [], [], [], []
        for i in range(len(bars)):
            if lab[i] < 0 or not ch[i]['pat']:
                continue
            js = [j for j in range(i - 1, -1, -1) if lab[j] == lab[i] and ch[j]['pat']]
            jd = [j for j in range(i - 1, -1, -1) if lab[j] >= 0 and lab[j] != lab[i] and ch[j]['pat']]
            if js and jd:
                same.append(_sim(ch[i]['pat'], ch[js[0]]['pat']))
                diff.append(_sim(ch[i]['pat'], ch[jd[0]]['pat']))
                rs.append(_sim(ch[i]['pat'], ch[js[0]]['pat'], True))
                rd.append(_sim(ch[i]['pat'], ch[jd[0]]['pat'], True))
        mean = lambda v: float(np.mean(v)) if v else None
        res[f'rep_{lk}'] = [mean(same), mean(diff), len(same)]
        res[f'rep_{lk}_rhythm'] = [mean(rs), mean(rd), len(rs)]
    # 途切れ: 途切れの間にノーツが無いか（同じ長さの場所を曲じゅうから取った時と比べる）・途切れの直後の最初の打点が両手か
    beats = np.array([nn[0] for nn in notes])
    nb = []
    for br in mu['breaks']:
        b0, b1 = br['beat'] + 0.05, br['beat'] + br['len'] - 0.05
        inside = int(((beats > b0) & (beats < b1)).sum())
        rnd = [int(((beats > s + 0.05) & (beats < s + br['len'] - 0.05)).sum()) for s in np.arange(4, n_beats - 4, 0.25)]
        after = beats[beats >= br['beat'] + br['len'] - 0.05]
        first_dbl = None
        if len(after):
            t0 = after[0]
            first_dbl = len({nn[1] for nn in notes if abs(nn[0] - t0) < 1e-3}) == 2
        nb.append({'empty': inside == 0, 'rnd_empty': float(np.mean([v == 0 for v in rnd])), 'first_dbl': first_dbl, 'kind': br['kind']})
    res['breaks'] = nb
    tm = {}
    for k_ in ('dbl',):
        times = {}
        for nn in notes:
            times.setdefault(round(nn[0], 3), set()).add(nn[1])
        tm['dbl_all'] = sum(1 for v in times.values() if len(v) == 2) / max(1, len(times))
    res.update(tm)
    # ドラムの変わり目: 譜面の数字が前後2小節で変わる大きさ（変わり目の小節と、ほかの小節）
    D = np.column_stack([c('dens'), np.nan_to_num(c('top')), np.nan_to_num(c('dbl'))])
    sd = D.std(axis=0) + 1e-9
    nov = np.full(len(bars), np.nan)
    for i in range(2, len(bars) - 1):
        nov[i] = float(np.linalg.norm((D[i:i + 2].mean(axis=0) - D[i - 2:i].mean(axis=0)) / sd))
    chg = [i for i in it['drum_change'] if 2 <= i < len(bars) - 1]
    rest = [i for i in range(2, len(bars) - 1) if i not in chg and not np.isnan(nov[i])]
    res['drum_change'] = [float(np.nanmean(nov[chg])) if chg else None, float(np.nanmean(nov[rest])) if rest else None, len(chg)]
    # 転調: 転調した所から 8 小節と、その前の 8 小節
    sh = mu['shift']
    mods = [i for i in range(1, len(sh)) if sh[i] != sh[i - 1] and sh[i] != 0 and i >= 8]
    res['mod'] = []
    for i in mods:
        seg = lambda a_, b_, k_: float(np.nanmean(c(k_)[a_:b_])) if b_ > a_ else None
        res['mod'].append({k_: [seg(i - 8, i, k_), seg(i, i + 8, k_)] for k_ in ('dens', 'top', 'dbl', 'move')})
    return res


def measure(a):
    from multiprocessing import Pool
    rows = json.loads((ROOT / 'cache' / 'lib_set.json').read_text(encoding='utf-8'))
    for r in rows:
        r['root'] = a.root
    if a.limit:
        rows = rows[:a.limit]
    with Pool(a.jobs) as p:
        res = [r for r in p.imap_unordered(song_measure, rows) if r]
    (ROOT / 'cache' / 'lib_music.json').write_text(json.dumps(res, ensure_ascii=False, indent=0), encoding='utf-8')
    report(res)


def report(res):
    import numpy as np
    ok = [r for r in res if 'error' not in r]
    bad = [r for r in res if 'error' in r]
    print(f'数えた曲 {len(ok)}（失敗 {len(bad)}）')
    groups = ('高評価', '手元')
    med = lambda v: f'{np.median(v):+.2f}' if len(v) else '—'
    print('\n## 盛り上がりと譜面の数字の順位の相関（曲ごとの値の中央値）\n')
    print('| 曲の手がかり～譜面 | ' + ' | '.join(groups) + ' |\n|---|---|---|')
    keys = sorted({k for r in ok for k in r['corr']})
    for k in keys:
        print(f'| {k} | ' + ' | '.join(med([r['corr'][k] for r in ok if r['group'] == g and k in r['corr']]) for g in groups) + ' |')
    print('\n## ドラムの勢いの下 1/3 → 上 1/3 の小節（曲ごとの平均の中央値）\n')
    print('| 譜面 | ' + ' | '.join(groups) + ' |\n|---|---|---|')
    for ck in ('dens', 'dbl', 'move', 'top'):
        cells = []
        for g in groups:
            v = [r['drum_hilo'][ck] for r in ok if r['group'] == g and ck in r.get('drum_hilo', {})]
            cells.append(f'{np.median([x[0] for x in v]):.2f} → {np.median([x[1] for x in v]):.2f}' if v else '—')
        print(f'| {ck} | ' + ' | '.join(cells) + ' |')
    print('\n## くり返し: 譜面の並びの一致（同じ記号の前の小節 ／ 違う記号の前の小節。_rhythm＝時刻と手だけ）\n')
    print('| 記号 | ' + ' | '.join(groups) + ' |\n|---|---|---|')
    for lk in ('mel', 'acc', 'mel_rhythm', 'acc_rhythm'):
        cells = []
        for g in groups:
            v = [r[f'rep_{lk}'] for r in ok if r['group'] == g and r[f'rep_{lk}'][0] is not None and r[f'rep_{lk}'][1] is not None]
            cells.append(f'{np.median([x[0] for x in v]):.2f} ／ {np.median([x[1] for x in v]):.2f}（{len(v)}曲）' if v else '—')
        print(f'| {lk} | ' + ' | '.join(cells) + ' |')
    print('\n## 途切れ\n')
    print('| | ' + ' | '.join(groups) + ' |\n|---|---|---|')
    for lab, fn in (('途切れの数', lambda b: len(b)),
                    ('途切れの間にノーツが無い', lambda b: np.mean([x['empty'] for x in b]) if b else np.nan),
                    ('（同じ長さの場所を曲じゅうから）', lambda b: np.mean([x['rnd_empty'] for x in b]) if b else np.nan),
                    ('直後の最初の打点が両手', lambda b: np.mean([x['first_dbl'] for x in b if x['first_dbl'] is not None]) if b else np.nan)):
        cells = []
        for g in groups:
            bs = [x for r in ok if r['group'] == g for x in r['breaks']]
            v = fn(bs)
            cells.append(f'{v:.2f}' if isinstance(v, float) else str(v))
        print(f'| {lab} | ' + ' | '.join(cells) + ' |')
    print('| （両手の打点の割合・曲全体） | ' + ' | '.join(f"{np.mean([r['dbl_all'] for r in ok if r['group'] == g]):.2f}" for g in groups) + ' |')
    print('\n## ドラムの変わり目での譜面の変わり方（変わり目の小節 ／ ほかの小節・前後2小節の差）\n')
    for g in groups:
        v = [r['drum_change'] for r in ok if r['group'] == g and r['drum_change'][0] is not None and r['drum_change'][1] is not None]
        print(f'- {g}: {np.median([x[0] for x in v]):.2f} ／ {np.median([x[1] for x in v]):.2f}（{len(v)}曲・変わり目 {sum(x[2] for x in v)}）' if v else f'- {g}: —')
    print('\n## 転調の前 8 小節 → 後 8 小節\n')
    for g in groups:
        ms = [m for r in ok if r['group'] == g for m in r['mod']]
        if not ms:
            print(f'- {g}: 転調 0')
            continue
        cells = []
        for k_ in ('dens', 'top', 'dbl', 'move'):
            v = [m[k_] for m in ms if m[k_][0] is not None and m[k_][1] is not None and not np.isnan(m[k_][0]) and not np.isnan(m[k_][1])]
            cells.append(f'{k_} {np.median([x[0] for x in v]):.2f} → {np.median([x[1] for x in v]):.2f}' if v else f'{k_} —')
        print(f'- {g}（転調 {len(ms)}）: ' + '・'.join(cells))


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    q = sub.add_parser('pick')
    q.add_argument('root')
    q.add_argument('--seed', type=int, default=0)
    q = sub.add_parser('measure')
    q.add_argument('root')
    q.add_argument('--jobs', type=int, default=6)
    q.add_argument('--limit', type=int, default=0)
    a = p.parse_args(argv)
    {'pick': pick, 'measure': measure}[a.cmd](a)


if __name__ == '__main__':
    main()
