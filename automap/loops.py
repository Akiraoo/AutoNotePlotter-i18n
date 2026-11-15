"""短い往復（2026-11-08 利用者「くり返し感がまだ弱い」・docs/方針.md 6.30 の案 3・6.32）: 曲の一部に「往復の区間」を決め、流れの計算で
同じ手の 2 つ前の振りと同じ置き方に寄せる（flow.Event.loop・Style.w_loop）＝ A B A B … の往復。手はそれぞれ下・上を交互に振るので、2 つ前は
必ず同じ向きの振り（無理なく置ける）。

人のランク譜面（★5〜8.5）は短い往復のくり返しに入る振りが 17%（中央値）、利用者の手本 Kings & Queens は 36%（上位 7%）。リズムの型と同じ音楽の
区間のくり返し（6.31）を入れたパピヨンは 20%・息つぎ（relief）を足しても 26%（息つぎは易しい所だけ・同じ振りの区間には入らない）。
区間は小節の頭から 1〜2 小節。片手の打点が MIN_SWINGS 以上で、印を付けてよい打点（片手・決めたノーツ無し・受け渡し無し・同じ振りの写す側
無し・息つぎ無し）が 8 割以上の所から、種と拍で決まるくじで、片手の振りの SHARE に届くまで選ぶ。同じ振りの手本の区間にも付く（写した回にも出る）。
"""
from bisect import bisect_right

from .flow import _mix64, _jitter_key

SHARE = 0.32       # 往復の区間に入れる片手の打点の割合の目安
MIN_SWINGS = 6     # 区間の片手の打点の数の下限（両手で 3 振りずつ＝往復が 1 回半）
P_TWO = 0.5        # 2 小節の区間にする割合
EPS = 1e-6


def _u(seed, beat, salt):
    return (_mix64(_jitter_key(seed, beat) ^ (salt * 0x9E3779B97F4A7C15 & ((1 << 64) - 1))) >> 11) * (1.0 / (1 << 53))


def _ok(ev):
    return (ev.hands == 1 and not ev.fix and not ev.relief and ev.want is None and ev.hoflex is None
            and not getattr(ev, 'no_ho', False) and ev.loop is None)


def plan(events, bars, seed=1, share=SHARE, keep=None, touch=()):
    """→ {spans: [(拍の始まり, 終わり)], marked（印を付けた打点）, target, kept（引き継いだ区間の数）}。
    keep＝前の版の区間（parse_line・前の譜面に寄せる作り直し）: 指示が変わった所（touch）にかからない区間はそのまま使い（区間の中の
    印を付けてよい打点に印）、新しく選ぶのは touch の中の小節だけ（作業中・2026-11-09・棚上げの 2）。目安の数とくじは曲の全部で数えるので、
    そのままだと打点の数が変わると変えた所の外の区間まで選び直した（こだまの写しで 10 → 12）"""
    if not bars or not events:
        return {'spans': [], 'marked': 0, 'target': 0}
    edges = list(bars) + [bars[-1] + 4]
    singles = sum(1 for e in events if e.hands == 1 and not getattr(e, 'no_ho', False))
    target = round(share * singles)
    beats = [e.beat for e in events]
    hit = lambda a, b: any(a < y - EPS and b > x + EPS for x, y in touch)
    used, spans, marked = set(), [], 0
    kept = [s for s in (keep or []) if not hit(*s)]
    for b0, b1 in kept:
        lo, hi = bisect_right(beats, b0 - EPS), bisect_right(beats, b1 - EPS)
        for e in events[lo:hi]:
            if e.hands == 1 and not e.relief and e.hoflex is None and not getattr(e, 'no_ho', False) and e.loop is None \
                    and (not e.fix or getattr(e, 'anchored', False)):
                e.loop = b0
                marked += not e.echo
        i0 = bisect_right(edges, b0 + EPS) - 1
        i1 = bisect_right(edges, b1 - EPS)
        used.update(range(i0, i1))
        spans.append((b0, b1))
    cands = []
    for i in range(len(bars)):
        L = 2 if _u(seed, bars[i], 21) < P_TWO and i + 2 < len(edges) else 1
        b0, b1 = edges[i], edges[i + L]
        if keep is not None and not any(x - EPS <= b0 and b1 <= y + EPS for x, y in touch):
            continue
        lo, hi = bisect_right(beats, b0 - EPS), bisect_right(beats, b1 - EPS)
        evs = events[lo:hi]
        good = [e for e in evs if _ok(e)]
        if len(good) >= MIN_SWINGS and len(good) >= 0.8 * len(evs):
            cands.append((_u(seed, b0, 22), i, L, b0, b1))
    cands.sort(key=lambda c: -c[0])
    for _, i, L, b0, b1 in cands:
        if marked >= target:
            break
        if any(j in used for j in range(i - 1, i + L + 1)):   # 区間どうしの間を 1 小節あける（ずっと往復にしない）
            continue
        lo, hi = bisect_right(beats, b0 - EPS), bisect_right(beats, b1 - EPS)
        for e in events[lo:hi]:
            if _ok(e):
                e.loop = b0
                marked += not e.echo   # 続けて左右反転の後ろのセットは反転が勝つ（印は付けて、目安には数えない）
        used.update(range(i, i + L))
        spans.append((b0, b1))
    return {'spans': sorted(spans), 'marked': marked, 'target': target, 'kept': len(kept)}


def report_line(pl, loop_share=None):
    if not pl:
        return ''
    where = '・'.join(f'{a:g}〜{b:g}' for a, b in pl['spans'])
    return (f'- 短い往復（docs/方針.md 6.32）: 往復の区間 {len(pl["spans"])}（印を付けた片手の打点 {pl["marked"]}・目安 {pl["target"]}）'
            + (f'・できた譜面の短い往復に入る振り {loop_share:.0%}（人の★5〜8.5 の中央値 17%・Kings & Queens 36%）' if loop_share is not None else '')
            + (f'。区間: 拍 {where}' if where else ''))


def parse_line(md):
    """報告の「短い往復」の行（report_line）→ 区間 [(拍の始まり, 終わり)]（行が無い・区間を書いていない前の形なら None）"""
    line = next((x for x in md.splitlines() if x.startswith('- 短い往復（')), None)
    if line is None:
        return None
    if '。区間: 拍 ' not in line:
        return [] if '往復の区間 0（' in line else None
    return [tuple(float(v) for v in s.split('〜')) for s in line.split('。区間: 拍 ')[1].strip().split('・')]


def share(notes):
    """できた譜面の短い往復に入る振りの割合（手ごとに、振りの並びで A B A B＝2 つ前と同じ置き方が 2 回続く所・振りは 1/8 拍でまとめる）"""
    tot = ins = 0
    for c in (0, 1):
        sw, last = [], None
        for n in sorted((n for n in notes if n['c'] == c), key=lambda n: n['beat']):
            if last is not None and n['beat'] - last <= 0.125 + EPS:
                last = n['beat']
                continue
            sw.append((n['x'], n['y'], n['d']))
            last = n['beat']
        tot += len(sw)
        mark = set()
        for i in range(len(sw) - 3):
            if sw[i] == sw[i + 2] and sw[i + 1] == sw[i + 3] and sw[i] != sw[i + 1]:
                mark.update(range(i, i + 4))
        ins += len(mark)
    return ins / max(1, tot)
