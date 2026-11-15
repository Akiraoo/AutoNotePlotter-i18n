"""リズムの型を使い回す（2026-11-08 利用者「くり返しの多い曲にしたい・1 と 2 を入れて」・docs/方針.md 6.30・6.31）。

人のランク譜面（★5〜8.5）は 4 拍のリズムの型を使い回す（同じリズムの 4 拍がほかにもある 83%・リズムの種類÷窓 34%）。作った譜面は打点を
歌・ドラムの細かい立ち上がりから拾うので、同じ音楽でも毎回少しずつ違うリズムになった（パピヨン 9%・103 の窓が 101 種類＝人の誰よりも少ない）。
自動で拾った打点（rhythm.choose_hits の後・途切れの前）を、4 拍の小節ごとに整える:

1. 同じ音楽の小節（伴奏と歌のくり返しの記号＝music.analyze の lab が同じ）は同じリズム: その組の小節の打点の数の中央値だけ、多くの小節で
   打っている位置から選ぶ（密度を変えない）。
2. 似たリズムは 1 つの型へ: 小節の数の多いリズムから順に型にし、違いが THETA 以下（打点の数の 1/4・4 打点なら 1 つ）のリズムはその型に寄せる。
3. 両手か・強さは型の位置ごとにそろえる（多数決・平均）＝難易度を展開して弱い打点から間引く時も、同じ型の小節は同じように間引かれる。

残した打点はそのまま（何の音か・高さ・山の音の印）。足した位置は近くの打点の候補（1/24 拍以内）から、無ければ同じ型のほかの小節の打点から写す。
4 拍でない小節（2 拍の小節など）・最初の小節の前は触らない。人の指示（意思入れ）は後で効くので、指示のある区間は指示が勝つ。
"""
from bisect import bisect_right
from collections import Counter, defaultdict

from . import rhythm

THETA = 0.45      # 型に寄せてよいリズムの違い（違う位置の数 ÷ 多い方の打点の数）
GRID = 12         # 位置の目盛り（1 拍を 12＝1/4 拍と 1/3 拍の両方）
EPS = 1e-6


def _dist(a, b):
    n = max(len(a), len(b))
    return len(a ^ b) / n if n else 0.0


def _sec_phr(secs, b):
    si = 0
    for i, s in enumerate(secs):
        if s.b0 - EPS <= b:
            si = i
    ps = secs[si].phrases or [(secs[si].b0, secs[si].b1)]
    pi = 0
    for k, (p0, p1) in enumerate(ps):
        if p0 - EPS <= b:
            pi = k
    return si, pi


def regularize(hits, mu, secs, ons, theta=THETA):
    """自動の打点 → (整えた打点, 報告 {bars, before, after, groups, moved, added, removed})"""
    bars = list(mu['bars'])
    if not bars or not hits:
        return hits, None
    edges = bars + [bars[-1] + 4]
    acc, mel = mu['lab']['acc'], mu['lab']['mel']
    per = defaultdict(list)
    outside = []
    for h in hits:
        i = bisect_right(bars, h.beat + EPS) - 1
        if i < 0 or abs(edges[i + 1] - edges[i] - 4) > EPS:
            outside.append(h)
        else:
            per[i].append(h)
    slot = lambda h, i: round((h.beat - bars[i]) * GRID)
    rh = {i: frozenset(slot(h, i) for h in hs) for i, hs in per.items()}
    before = len(set(rh.values()))
    # 1. 同じ音楽の小節は同じリズム（組の小節の半分以上で打っている位置）
    groups = defaultdict(list)
    for i in per:
        if acc[i] >= 0:
            groups[(acc[i], mel[i])].append(i)
    cur = dict(rh)
    n_groups = 0
    for idx in groups.values():
        if len(idx) < 2:
            continue
        cnt = Counter(s for i in idx for s in rh[i])
        # 組の小節の打点の数の中央値だけ、多くの小節で打っている位置から（同じなら拍の頭・半拍を先に）＝密度を変えない
        # （「半分以上の小節で打っている位置」だと打点が 8% 増えて★が +0.4・「半分より多く」だと 14% 減った）
        want = sorted(len(rh[i]) for i in idx)[len(idx) // 2]
        cons = frozenset(sorted(cnt, key=lambda s: (-cnt[s], 0 if s % GRID == 0 else 1 if s % (GRID // 2) == 0 else 2, s))[:want])
        if cons:
            n_groups += 1
            for i in idx:
                cur[i] = cons
    # 2. 似たリズムは 1 つの型へ（小節の数の多いリズムから型に）
    freq = Counter(cur.values())
    centers = []
    for r, _ in sorted(freq.items(), key=lambda kv: (-kv[1], len(kv[0]), sorted(kv[0]))):   # 同じ数なら打点の少ない方
        if not any(_dist(r, c) <= theta for c in centers):
            centers.append(r)
    moved = 0
    for i, r in cur.items():
        best = min(centers, key=lambda c: (_dist(r, c), -freq[c], len(c), sorted(c)))
        if best != r and _dist(r, best) <= theta:
            cur[i] = best
            moved += 1
    # 3. 型の位置ごとの両手・強さ（その型の小節の打点の多数決・平均）と、足す打点の元
    by_pat = defaultdict(list)
    for i, r in cur.items():
        by_pat[r].append(i)
    tmpl = {}
    for r, idx in by_pat.items():
        for s in r:
            src = [h for i in idx for h in per[i] if slot(h, i) == s]
            if src:
                tmpl[(r, s)] = (2 if 2 * sum(h.hands == 2 for h in src) > len(src) else 1, sum(h.s for h in src) / len(src), src[0])
    cand = sorted((o for k in ('vocal', 'kick', 'snare', 'hihat', 'other', 'bass') for o in ons.get(k, [])), key=lambda o: o.beat)
    cb = [o.beat for o in cand]

    def near(b):
        j = bisect_right(cb, b)
        best = None
        for o in cand[max(0, j - 3):j + 3]:
            if abs(o.beat - b) <= 1 / 24 + EPS and (best is None or o.s > best.s):
                best = o
        return best

    out, added, removed, added_on = list(outside), 0, 0, 0
    for i, hs in per.items():
        r = cur[i]
        have = {slot(h, i): h for h in hs}
        removed += sum(1 for s in have if s not in r)
        for s in sorted(r):
            t = tmpl.get((r, s))
            if s in have:
                h = have[s]
            else:
                b = bars[i] + s / GRID
                o = near(b)
                si, pi = _sec_phr(secs, b)
                ref = t[2] if t else None
                h = rhythm.Hit(b, 1, si, pi, o.kind if o else (ref.src if ref else 'groove'), o.s if o else (ref.s if ref else 0.4),
                               o.midi if o else (ref.midi if ref else 0.0))
                added += 1
                added_on += o is not None and o.s >= 0.2
            if t:
                h.hands, h.s = t[0], t[1]
            out.append(h)
    out.sort(key=lambda h: h.beat)
    # 両手同時は前後 1/2 拍に打点が無い所だけ（rhythm.choose_hits と同じ）
    for k, h in enumerate(out):
        if h.hands == 2 and ((k > 0 and h.beat - out[k - 1].beat < 0.5 - EPS) or (k + 1 < len(out) and out[k + 1].beat - h.beat < 0.5 - EPS)):
            h.hands = 1
    after = len(set(cur.values()))
    return out, {'bars': len(per), 'before': before, 'after': after, 'groups': n_groups, 'moved': moved, 'added': added, 'removed': removed,
                 'added_on': added_on}


def report_line(rep):
    if not rep:
        return ''
    return (f'- リズムの型（docs/方針.md 6.31）: 4 拍の小節 {rep["bars"]} のリズム {rep["before"]} 種類 → {rep["after"]} 種類'
            f'（同じ音楽の小節の組 {rep["groups"]}・似たリズムを型に寄せた小節 {rep["moved"]}・打点 足し {rep["added"]}'
            f'（うち音の立ち上がりのある所 {rep.get("added_on", 0)}）・抜き {rep["removed"]}）')
