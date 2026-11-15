"""手元の Beat Saber 譜面（CustomLevels）から、難易度ごとの「打ち方の数字」を集める（自動打ち込みの検討用・読むだけ）。

使い方: python -I tools/library_stats.py <CustomLevels のフォルダ> <結果の json>
v2/v3 の Standard だけ。v4・Noodle/Mapping Extensions・BPM 変化のある譜面は除く。
"""
import json, os, sys, math, statistics
from multiprocessing import Pool

RANKS = ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus']
EPS = 1e-3
DIRV = {0: (0, 1), 1: (0, -1), 2: (-1, 0), 3: (1, 0), 4: (-1, 1), 5: (1, 1), 6: (-1, -1), 7: (1, -1)}
UPISH, DOWNISH = {0, 4, 5}, {1, 6, 7}


def load(p):
    with open(p, 'rb') as f:
        b = f.read()
    return json.loads(b.decode('utf-8-sig'))


def find(folder, name):
    low = name.lower()
    for f in os.listdir(folder):
        if f.lower() == low:
            return os.path.join(folder, f)
    return None


def grid_class(t):
    fr = t - math.floor(t)
    for name, den in (('1', 1), ('1/2', 2), ('1/4', 4), ('1/3', 3), ('1/6', 6), ('1/8', 8), ('1/16', 16)):
        k = round(fr * den)
        if abs(fr - k / den) < 0.01:
            return name
    return 'other'


def gap_class(g):
    for name, v in (('>=2', None), ('1', 1), ('1/2', 0.5), ('1/3', 1 / 3), ('1/4', 0.25), ('1/6', 1 / 6), ('1/8', 0.125)):
        if v is None:
            if g >= 2 - 0.02:
                return name
            continue
        if abs(g - v) < 0.02:
            return name
    if g > 1:
        return '1<g<2'
    return 'other'


def parse_diff(d):
    """色ノーツ [(拍, 色, x, y, 向き)]・ボム数・アーク数・チェーン数・BPM変化の有無。"""
    if 'colorNotes' in d or 'version' in d:
        notes = [(n.get('b', 0), n.get('c', 0), n.get('x', 0), n.get('y', 0), n.get('d', 0)) for n in d.get('colorNotes', [])]
        bombs = len(d.get('bombNotes', []))
        arcs = len(d.get('sliders', []))
        chains = len(d.get('burstSliders', []))
        bpmch = len(d.get('bpmEvents', [])) > 1
        return notes, bombs, arcs, chains, bpmch
    notes, bombs = [], 0
    for n in d.get('_notes', []):
        ty = n.get('_type', 0)
        if ty == 3:
            bombs += 1
        elif ty in (0, 1):
            notes.append((n.get('_time', 0), ty, n.get('_lineIndex', 0), n.get('_lineLayer', 0), n.get('_cutDirection', 0)))
    cd = d.get('_customData') or {}
    bpmch = bool(d.get('_BPMChanges') or cd.get('_BPMChanges') or cd.get('_bpmChanges'))
    return notes, bombs, 0, 0, bpmch


def swings(hand_notes):
    """同じ手のノーツを 1/8 拍以内でまとめて1振りに（スライダー・スタック）。各振りの (拍, 頭のノーツ)。"""
    out = []
    for n in hand_notes:
        if out and n[0] - out[-1][2] <= 0.125 + EPS:
            out[-1] = (out[-1][0], out[-1][1], n[0])
            continue
        out.append((n[0], n, n[0]))
    return out


def analyze(notes, bpm):
    notes.sort(key=lambda n: (n[0], n[1]))
    if len(notes) < 20:
        return None
    sec = 60.0 / bpm
    span = (notes[-1][0] - notes[0][0]) * sec
    if span <= 1:
        return None
    if any(not (0 <= n[2] <= 3 and 0 <= n[3] <= 2 and 0 <= n[4] <= 8) for n in notes):
        return None
    r = {'nps': len(notes) / span, 'n': len(notes)}
    # 同時のノーツを1つの打点に
    events = []
    for n in notes:
        if events and abs(n[0] - events[-1][0]) < EPS:
            events[-1][1].add(n[1])
        else:
            events.append([n[0], {n[1]}])
    r['events'] = len(events)
    r['dbl'] = sum(1 for e in events if len(e[1]) == 2) / len(events)
    gc = {}
    for e in events:
        k = grid_class(e[0])
        gc[k] = gc.get(k, 0) + 1
    r['grid'] = {k: v / len(events) for k, v in gc.items()}
    gp = {}
    for a, b in zip(events, events[1:]):
        k = gap_class(b[0] - a[0])
        gp[k] = gp.get(k, 0) + 1
    tot = max(1, len(events) - 1)
    r['gap'] = {k: v / tot for k, v in gp.items()}
    # 片手の打点が続く時、手が入れ替わる割合
    singles = [next(iter(e[1])) for e in events if len(e[1]) == 1]
    if len(singles) > 1:
        r['alt'] = sum(1 for a, b in zip(singles, singles[1:]) if a != b) / (len(singles) - 1)
    dirs = {}
    for n in notes:
        k = 'down' if n[4] == 1 else 'up' if n[4] == 0 else 'side' if n[4] in (2, 3) else 'dot' if n[4] == 8 else 'diag'
        dirs[k] = dirs.get(k, 0) + 1
    r['dir'] = {k: v / len(notes) for k, v in dirs.items()}
    rows = [0, 0, 0]
    cols = [0, 0, 0, 0]
    for n in notes:
        rows[n[3]] += 1
        cols[n[2]] += 1
    r['row'] = [v / len(notes) for v in rows]
    r['col'] = [v / len(notes) for v in cols]
    # 振りの流れ（片手ずつ）
    resets = total = 0
    ang = {'180': 0, '135': 0, '<=90': 0}
    fast = []
    for c in (0, 1):
        sw = swings([n for n in notes if n[1] == c])
        for a, b in zip(sw, sw[1:]):
            fast.append((b[0] - a[2]) * sec)
            da, db = a[1][4], b[1][4]
            if da == 8 or db == 8:
                continue
            total += 1
            if (da in UPISH and db in UPISH) or (da in DOWNISH and db in DOWNISH):
                resets += 1
            va, vb = DIRV[da], DIRV[db]
            cosv = (va[0] * vb[0] + va[1] * vb[1]) / (math.hypot(*va) * math.hypot(*vb))
            deg = math.degrees(math.acos(max(-1, min(1, cosv))))
            if deg > 157.5:
                ang['180'] += 1
            elif deg > 112.5:
                ang['135'] += 1
            else:
                ang['<=90'] += 1
    if total:
        r['reset'] = resets / total
        r['ang'] = {k: v / total for k, v in ang.items()}
    if fast:
        fast.sort()
        r['swing_gap_p10'] = fast[len(fast) // 10]
        r['swing_gap_med'] = fast[len(fast) // 2]
    r['times'] = sorted({round(e[0], 3) for e in events})
    return r


def song(folder):
    try:
        ip = find(folder, 'Info.dat')
        if not ip:
            return None
        info = load(ip)
        if '_difficultyBeatmapSets' not in info:
            return None  # v4
        bpm = float(info.get('_beatsPerMinute') or 0)
        if bpm <= 0:
            return None
        out = {}
        for s in info['_difficultyBeatmapSets']:
            if s.get('_beatmapCharacteristicName') != 'Standard':
                continue
            for bm in s.get('_difficultyBeatmaps', []):
                rank = bm.get('_difficulty')
                if rank not in RANKS:
                    continue
                req = ((bm.get('_customData') or {}).get('_requirements')) or []
                if any('Noodle' in q or 'Mapping Extensions' in q for q in req):
                    continue
                dp = find(folder, bm.get('_beatmapFilename', ''))
                if not dp:
                    continue
                notes, bombs, arcs, chains, bpmch = parse_diff(load(dp))
                if bpmch:
                    continue
                r = analyze(notes, bpm)
                if not r:
                    continue
                mins = r['n'] / r['nps'] / 60
                r['bombs_pm'] = bombs / mins
                r['arcs_pm'] = arcs / mins
                r['chains_pm'] = chains / mins
                r['njs'] = bm.get('_noteJumpMovementSpeed')
                r['bpm'] = bpm
                out[rank] = r
        return out or None
    except Exception:
        return None


def main():
    root, dst = sys.argv[1], sys.argv[2]
    folders = [os.path.join(root, f) for f in os.listdir(root) if os.path.isdir(os.path.join(root, f))]
    with Pool(8) as p:
        res = [r for r in p.map(song, folders, chunksize=8) if r]
    # 難易度の組: 易しい方の打点が、1つ上の難易度にもある割合
    pairs = {}
    for s in res:
        have = [k for k in RANKS if k in s]
        for lo, hi in zip(have, have[1:]):
            a, b = set(s[lo]['times']), set(s[hi]['times'])
            if not a:
                continue
            key = f'{lo}->{hi}'
            pairs.setdefault(key, []).append((len(a & b) / len(a), len(a) / max(1, len(b))))
    summary = {'songs': len(res), 'ranks': {}, 'pairs': {}}
    for k in RANKS:
        rs = [s[k] for s in res if k in s]
        if not rs:
            continue

        def med(f):
            v = [f(r) for r in rs if f(r) is not None]
            if not v:
                return None
            v.sort()
            return [round(v[len(v) // 4], 3), round(statistics.median(v), 3), round(v[(len(v) * 3) // 4], 3)]

        def mean_dict(name):
            acc = {}
            for r in rs:
                for kk, vv in (r.get(name) or {}).items():
                    acc[kk] = acc.get(kk, 0) + vv
            return {kk: round(vv / len(rs), 3) for kk, vv in sorted(acc.items(), key=lambda x: -x[1])}

        summary['ranks'][k] = {
            'maps': len(rs),
            'nps_q1_med_q3': med(lambda r: r['nps']),
            'njs_q1_med_q3': med(lambda r: r['njs']),
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
    for key, v in pairs.items():
        inc = sorted(x[0] for x in v)
        ratio = sorted(x[1] for x in v)
        summary['pairs'][key] = {
            'songs': len(v),
            'subset_q1_med_q3': [round(inc[len(inc) // 4], 3), round(statistics.median(inc), 3), round(inc[(len(inc) * 3) // 4], 3)],
            'share_ge_90pct': round(sum(1 for x in inc if x >= 0.9) / len(inc), 3),
            'density_ratio_med': round(statistics.median(ratio), 3),
        }
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
