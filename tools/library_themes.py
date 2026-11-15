"""手元の譜面（CustomLevels）から「テーマ」＝くり返されている動きの型を集める（自動打ち込みのテーマの素材・読むだけ）。

使い方: python -I tools/library_themes.py <CustomLevels のフォルダ> <結果の json> [--ranks Expert,ExpertPlus]

- 片手の振り（スタック・スライダーは1振り）の並びで、同じ P 振り（P=2,4,6,8）が2回以上続けてくり返されている所を「型」とする。
  型は振り下ろし側と振り上げ側が交互になっている物だけ（そのまま使っても振りの交互が崩れない）。点ノーツを含む物は除く。
- 型は右手の形にそろえる（左手は左右反転）。回転は「振り下ろし側から始まる」中で辞書順が一番小さい物を代表にする。
- 左右の手の型が同じ時間にくり返されている所を「両手のテーマ」として数える（何曲で使われたか）。
- 型には、使われた時の振りの間（同じ手・拍と秒の中央値）と、型の大きさ（マスの数・移動・段・斜め）を付ける。
v2/v3 の Standard だけ。v4・Noodle/Mapping Extensions・BPM 変化のある譜面は除く（library_stats.py と同じ）。
"""
import json
import os
import statistics
import sys
from collections import defaultdict
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from library_stats import load, find, parse_diff  # noqa: E402

MIRROR_D = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}
EPS = 1e-3


def parity(c, d):
    """振り下ろし側 0・振り上げ側 1・点 None（automap.flow.parity_of と同じ）"""
    if d in (1, 6, 7):
        return 0
    if d in (0, 4, 5):
        return 1
    if d == 2:
        return 0 if c == 1 else 1
    if d == 3:
        return 0 if c == 0 else 1
    return None


def to_r(c, s):
    """左手の振り (x, y, d) を右手の形へ（左右反転）"""
    x, y, d = s
    return (x, y, d) if c == 1 else (3 - x, y, MIRROR_D[d])


def canon(cyc):
    """型の代表の回転（振り下ろし側から始まる中で一番小さい物）。右手の形の (x, y, d) の並び"""
    P = len(cyc)
    rots = [tuple(cyc[i:] + cyc[:i]) for i in range(P) if parity(1, cyc[i][2]) == 0]
    return min(rots) if rots else None


def hand_swings(notes, c):
    """その手の振り [(拍, (x, y, d))]（1/8 拍以内に続く物はまとめて先頭だけ）"""
    out, last = [], None
    for b, cc, x, y, d in sorted(n for n in notes if n[1] == c):
        if last is not None and b - last <= 0.125 + EPS:
            last = b
            continue
        out.append((b, (x, y, d)))
        last = b
    return out


def runs(sw, c):
    """くり返しの区間 [(型, 始まりの拍, 終わりの拍, 回数, 振りの間（拍）の中央値)]"""
    seq = [s for _, s in sw]
    out, i, n = [], 0, len(seq)
    while i < n:
        found = None
        for P in (2, 4, 6, 8):
            if i + 2 * P > n:
                break
            cyc = seq[i:i + P]
            if any(s[2] == 8 for s in cyc):
                break
            if seq[i + P:i + 2 * P] != cyc:
                continue
            ps = [parity(c, s[2]) for s in cyc]
            if any(ps[k] == ps[(k + 1) % P] for k in range(P)):
                continue
            found = P
            break
        if not found:
            i += 1
            continue
        P = found
        j = i + 2 * P
        while j + P <= n and seq[j:j + P] == seq[i:i + P]:
            j += P
        reps = (j - i) // P
        gaps = [sw[k + 1][0] - sw[k][0] for k in range(i, j - 1)]
        out.append((tuple(to_r(c, s) for s in seq[i:i + P]), sw[i][0], sw[j - 1][0], reps, statistics.median(gaps) if gaps else 0))
        i = j
    return out


def song(folder):
    try:
        ip = find(folder, 'Info.dat')
        if not ip:
            return None
        info = load(ip)
        if '_difficultyBeatmapSets' not in info:
            return None
        bpm = float(info.get('_beatsPerMinute') or 0)
        if bpm <= 0:
            return None
        res = []
        for s in info['_difficultyBeatmapSets']:
            if s.get('_beatmapCharacteristicName') != 'Standard':
                continue
            for bm in s.get('_difficultyBeatmaps', []):
                rank = bm.get('_difficulty')
                if rank not in RANKS_USED:
                    continue
                req = ((bm.get('_customData') or {}).get('_requirements')) or []
                if any('Noodle' in q or 'Mapping Extensions' in q for q in req):
                    continue
                dp = find(folder, bm.get('_beatmapFilename', ''))
                if not dp:
                    continue
                notes, _, _, _, bpmch = parse_diff(load(dp))
                if bpmch or len(notes) < 50:
                    continue
                rl = runs(hand_swings(notes, 0), 0)
                rr = runs(hand_swings(notes, 1), 1)
                hands = []
                for cyc, b0, b1, reps, g in rl + rr:
                    k = canon(list(cyc))
                    if k:
                        hands.append((k, b0, b1, reps, g))
                pairs = []
                for cl, l0, l1, _, gl in rl:
                    for cr, r0, r1, _, gr in rr:
                        ov = min(l1, r1) - max(l0, r0)
                        if ov > 0.5 * min(l1 - l0, r1 - r0) and ov >= 2:
                            kl, kr = canon(list(cl)), canon(list(cr))
                            if kl and kr:
                                pairs.append((kl, kr, max(l0, r0), min(l1, r1), (gl + gr) / 2))
                res.append({'rank': rank, 'bpm': bpm, 'hands': hands, 'pairs': pairs})
        return (os.path.basename(folder), res) if res else None
    except Exception:
        return None


RANKS_USED = ('Expert', 'ExpertPlus')


def shape(cyc):
    """型の大きさ: マスの数・1振りの平均の移動（マス）・平均の段・斜めの割合・列の幅"""
    P = len(cyc)
    mv = [abs(cyc[k][0] - cyc[(k + 1) % P][0]) + abs(cyc[k][1] - cyc[(k + 1) % P][1]) for k in range(P)]
    return {'cells': len({(s[0], s[1]) for s in cyc}), 'move': round(sum(mv) / P, 3),
            'row': round(sum(s[1] for s in cyc) / P, 3), 'diag': round(sum(1 for s in cyc if s[2] in (4, 5, 6, 7)) / P, 3),
            'width': max(s[0] for s in cyc) - min(s[0] for s in cyc)}


def _set_ranks(r):
    global RANKS_USED
    RANKS_USED = r


def main():
    root, dst = sys.argv[1], sys.argv[2]
    if '--ranks' in sys.argv:
        _set_ranks(tuple(sys.argv[sys.argv.index('--ranks') + 1].split(',')))
    folders = [os.path.join(root, f) for f in os.listdir(root) if os.path.isdir(os.path.join(root, f))]
    with Pool(8, initializer=_set_ranks, initargs=(RANKS_USED,)) as p:
        res = [r for r in p.map(song, folders, chunksize=8) if r]
    hand = defaultdict(lambda: {'maps': set(), 'runs': 0, 'reps': 0, 'gap': [], 'sec': []})
    pair = defaultdict(lambda: {'maps': set(), 'runs': 0, 'gap': [], 'sec': []})
    for name, diffs in res:
        for dd in diffs:
            spb = 60 / dd['bpm']
            for k, b0, b1, reps, g in dd['hands']:
                h = hand[k]
                h['maps'].add(name)
                h['runs'] += 1
                h['reps'] += reps
                h['gap'].append(g)
                h['sec'].append(g * spb)
            for kl, kr, b0, b1, g in dd['pairs']:
                # 左右を入れ替えた物（鏡写し）は同じテーマ
                key = min((kl, kr), (kr, kl))
                q = pair[key]
                q['maps'].add(name)
                q['runs'] += 1
                q['gap'].append(g)
                q['sec'].append(g * spb)

    def pack(k, v, extra):
        return {**extra, 'maps': len(v['maps']), 'runs': v['runs'], 'gap': round(statistics.median(v['gap']), 3),
                'sec': round(statistics.median(v['sec']), 3)}

    hands = sorted((pack(k, v, {'cycle': [list(s) for s in k], **shape(k)}) for k, v in hand.items() if len(v['maps']) >= 2),
                   key=lambda r: -r['maps'])
    pairs = sorted((pack(k, v, {'a': [list(s) for s in k[0]], 'b': [list(s) for s in k[1]], 'shape_a': shape(k[0]), 'shape_b': shape(k[1])})
                    for k, v in pair.items() if len(v['maps']) >= 2), key=lambda r: -r['maps'])
    out = {'songs': len(res), 'ranks': list(RANKS_USED), 'hands': hands, 'pairs': pairs}
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f'曲 {len(res)}・型 {len(hands)}・両手のテーマ {len(pairs)}')


if __name__ == '__main__':
    main()
