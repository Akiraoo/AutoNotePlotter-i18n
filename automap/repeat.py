"""同じ音楽の区間は譜面ごとくり返す（同じ振りの自動版・2026-11-08 利用者「くり返しの多い曲にしたい・1 と 2 を入れて」・docs/方針.md 6.30・6.31）。

人の譜面（Kings & Queens）は 2 回目のサビを 1 回目と同じリズムの並びにし、置き方を丸ごと左右反転していた。人のランク譜面（★5〜8.5）の
4 拍の窓は、中身まで同じ窓がほかにもある 12%・左右反転の窓 5%（中央値）。作った譜面はどちらも 0%（同じ振りは利用者が意思入れで付けた所だけ）。

曲の流れの表のくり返しの記号（music.analyze の lab）で、伴奏の記号が MIN_BARS 小節以上続けて同じ並びで、歌の記号も MEL_MATCH 以上同じ所を
探し（4 拍の小節だけ・利用者の意思入れの区間とは重ねない）、長い物から重ならないように選ぶ。1 回目を手本に、2 回目からは手本の打点の並びを
写し（意思入れの同じ振りと同じ印＝hit.motif・番号は IDX0 から）、置き方は手本の置き方を流れの計算で狙い直す（__main__._fix_motifs）。
左右反転（手を入れ替え・列を 3−x・向きを左右逆＝motif['mirror']）はグループごとに交互: 1・3… 番目のグループは 2・4 回目、2・4… 番目の
グループは 3 回目（2 回目は同じ置き方）。どの回も左右反転にすると、左右反転の 4 拍が 12〜46%（人の中央値 5%・四分位 0〜17%）になった。
"""
from . import rhythm

MIN_BARS = 2      # くり返しとみる長さ（小節）
MAX_BARS = 16
MEL_MATCH = 0.7   # 歌の記号が同じ小節の割合（歌の記号は伴奏より揺れる・歌の無い小節どうしは同じ）
IDX0 = 100000     # 自動の同じ振りの番号（意思入れの区間の番号と重ならない・__main__ の gid＝500000＋番号）
EPS = 1e-6


def find(mu, avoid=()):
    """→ [グループ {'name', 'bars': 長さ（小節）, 'occ': [(拍の始まり, 終わり)]（始まりの順）}]"""
    bars = list(mu['bars'])
    if not bars:
        return []
    edges = bars + [bars[-1] + 4]
    acc, mel = mu['lab']['acc'], mu['lab']['mel']
    n = len(bars)
    ok = [abs(edges[i + 1] - edges[i] - 4) < EPS and acc[i] >= 0
          and not any(edges[i] < y - EPS and edges[i + 1] > x + EPS for x, y in avoid) for i in range(n)]

    def best_sub(i, j, L):
        """伴奏が同じ長さ L の組の中で、歌の記号の合う割合が MEL_MATCH 以上の一番長い区間 → (ずれ, 長さ) か None"""
        for ln in range(L, MIN_BARS - 1, -1):
            for s in range(0, L - ln + 1):
                if sum(mel[i + s + k] == mel[j + s + k] for k in range(ln)) >= MEL_MATCH * ln:
                    return s, ln
        return None

    cands = []
    for i in range(n):
        for j in range(i + 1, n):
            if i > 0 and ok[i - 1] and ok[j - 1] and acc[i - 1] == acc[j - 1]:
                continue   # 左へ伸ばせる（もっと前から始まる組で数える）
            L = 0
            while i + L < j and j + L < n and L < MAX_BARS and ok[i + L] and ok[j + L] and acc[i + L] == acc[j + L]:
                L += 1
            if L >= MIN_BARS:
                sub = best_sub(i, j, L)
                if sub:
                    cands.append((sub[1], i + sub[0], j + sub[0]))
    cands.sort(key=lambda c: (-c[0], c[1], c[2]))
    used, groups = set(), []
    for L, i, j in cands:
        span = lambda s: set(range(s, s + L))
        if span(i) & used or span(j) & used:
            continue
        occ = [i, j]
        for c, i2, j2 in cands:   # 同じ並びのほかの回（手本 i と長さ L 以上で合う所）
            k = j2 if i2 == i else None
            if k is not None and c >= L and k not in occ and not (span(k) & used) and all(abs(k - o) >= L for o in occ):
                occ.append(k)
        occ.sort()
        for o in occ:
            used |= span(o)
        groups.append({'name': f'自動{len(groups) + 1}', 'bars': L, 'occ': [(edges[o], edges[o + L]) for o in occ]})
    groups.sort(key=lambda g: g['occ'][0][0])
    for k, g in enumerate(groups):
        g['name'] = f'自動{k + 1}'
    return groups


def carry(prev, touch, mu):
    """前の版の組（parse_line の形・g['flip'] つき）を引き継ぐ → (グループ（find と同じ形・flip つき）, 組から外した小節の範囲（どの回も）)。
    指示が変わった所（touch＝[(拍, 拍)]）にどれかの回がかかる小節は組から外し、残りを MIN_BARS 小節以上の続きに分ける（手本と写す側の対応・
    反転の回はそのまま）。外した小節の写す側は自由に作らず、前の譜面に弱く寄せる（2026-11-09 利用者「ミラー側へコピーする必要はない」）。
    新しい組は作らない（作ると、変えた所と関係ない離れた所が写す側になって変わる）。作業中（2026-11-09・棚上げの 2）"""
    edges = list(mu['bars']) + [mu['bars'][-1] + 4] if mu.get('bars') else []
    pos = {round(b, 4): i for i, b in enumerate(edges)}
    out, dropped = [], []
    for g in prev:
        L = g['bars']
        starts = [pos.get(round(b0, 4)) for b0, _ in g['occ']]
        if None in starts or any(i + L >= len(edges) for i in starts):
            continue
        bad = [any(edges[i + o] < y - EPS and edges[i + o + 1] > x + EPS for i in starts for x, y in touch) for o in range(L)]
        o = 0
        while o < L:
            if bad[o]:
                dropped.extend((edges[i + o], edges[i + o + 1]) for i in starts)
                o += 1
                continue
            e = o
            while e < L and not bad[e]:
                e += 1
            if e - o >= MIN_BARS:
                out.append({'name': '', 'bars': e - o, 'occ': [(edges[i + o], edges[i + e]) for i in starts], 'flip': g.get('flip', 0)})
            else:
                dropped.extend((edges[i + o], edges[i + e]) for i in starts)
            o = e
    out.sort(key=lambda g: g['occ'][0][0])
    for k, g in enumerate(out):
        g['name'] = f'自動{k + 1}'
    return out, sorted(dropped)


def gone(touch, avoid):
    """指示が変わった所（touch＝[(拍, 拍)]）のうち、今は利用者の区間（avoid）にかからない所＝指示が無くなった所"""
    return [(x, y) for x, y in touch if not any(x < b - EPS and y > a + EPS for a, b in avoid)]


def regrow(groups, fresh, touch, avoid, mu):
    """指示が無くなった小節で、分かれた組を元の形に戻す（2026-11-10 利用者「分かれた組だけ元の形に戻す」）→ (グループ, 戻した小節の範囲)。
    groups＝carry で引き継いだ組・fresh＝今の指示でまっさらに作った組（find(mu, avoid)）。fresh の組 f ごとに、同じ回の数・同じ並び方で
    f に含まれる引き継いだ組（分かれた残り・反転の向きが同じ）を 1 つにまとめ、間と前後を f の形まで埋める（埋めるのは、どの回もほかの組に
    かからない小節・埋める小節に指示が無くなった小節＝gone を含む時だけ。前後は側ごとに見る）。完全に消えた組（分けた残りが MIN_BARS
    未満）は戻さない＝離れた所に新しい組を作らない"""
    ok = gone(touch, avoid)
    if not ok or not groups or not fresh or not mu.get('bars'):
        return groups, []
    edges = list(mu['bars']) + [mu['bars'][-1] + 4]
    pos = {round(b, 4): i for i, b in enumerate(edges)}
    starts = lambda g: [pos.get(round(b0, 4)) for b0, _ in g['occ']]
    hit = lambda i: any(edges[i] < y - EPS and edges[i + 1] > x + EPS for x, y in ok)
    out, grown = [dict(g) for g in groups], []
    for f in fresh:
        sf = starts(f)
        if None in sf:
            continue
        mem = []   # f に同じ並び方で含まれる組（番号・f の中の小節の範囲）
        for k, g in enumerate(out):
            sg = starts(g)
            if None in sg or len(sg) != len(sf):
                continue
            d = sg[0] - sf[0]
            if 0 <= d and d + g['bars'] <= f['bars'] and all(x - y == d for x, y in zip(sg, sf)):
                mem.append((k, d, d + g['bars']))
        if not mem or len({out[k].get('flip', 0) for k, _, _ in mem}) > 1:
            continue
        ks = {k for k, _, _ in mem}
        taken = {i + o for k, h in enumerate(out) if k not in ks for i in starts(h) if i is not None for o in range(h['bars'])}
        free = lambda r: all(i + r not in taken for i in sf)
        gone_in = lambda r0, r1: any(hit(i + r) for i in sf for r in range(r0, r1))
        mem.sort(key=lambda m: m[1])
        lo, hi = mem[0][1], mem[-1][2]
        if any(not free(r) for r in range(lo, hi) if not any(a <= r < b for _, a, b in mem)):
            continue   # 間にほかの組がある
        gaps = [(b, c) for (_, _, b), (_, c, _) in zip(mem, mem[1:]) if c > b]
        if gaps and not any(gone_in(b, c) for b, c in gaps):
            continue
        l2 = lo
        while l2 > 0 and free(l2 - 1):
            l2 -= 1
        h2 = hi
        while h2 < f['bars'] and free(h2):
            h2 += 1
        lo2 = l2 if gone_in(l2, lo) else lo
        hi2 = h2 if gone_in(hi, h2) else hi
        if len(mem) == 1 and (lo2, hi2) == (lo, hi):
            continue
        add = [(b, c) for b, c in gaps] + [(lo2, lo), (hi, hi2)]
        grown += [(edges[i + r0], edges[i + r1]) for i in sf for r0, r1 in add if r1 > r0]
        g0 = out[mem[0][0]]
        merged = {'name': g0['name'], 'bars': hi2 - lo2, 'occ': [(edges[i + lo2], edges[i + hi2]) for i in sf], 'flip': g0.get('flip', 0)}
        out = [g for k, g in enumerate(out) if k not in ks] + [merged]
    out.sort(key=lambda g: g['occ'][0][0])
    for k, g in enumerate(out):
        g['name'] = f'自動{k + 1}'
    return out, sorted(grown)


def parse_line(md):
    """報告の「同じ音楽の区間」の行（report_line）→ [{'bars', 'occ', 'flip'}]（行が無ければ None・見つからなかったは []）"""
    import re
    line = next((x for x in md.splitlines() if x.startswith('- 同じ音楽の区間（')), None)
    if line is None:
        return None
    out = []
    for m in re.finditer(r'自動\d+ (\d+) 小節: ((?:拍 [-\d.]+（[^）]+）(?:→)?)+)', line):
        L = int(m.group(1))
        occ = re.findall(r'拍 ([-\d.]+)（([^）]+)）', m.group(2))
        if len(occ) < 2:
            continue
        b0s = [float(b) for b, _ in occ]
        out.append({'bars': L, 'occ': [(b, b + 4 * L) for b in b0s], 'flip': 0 if occ[1][1] == '左右反転' else 1})
    return out


KIND = {'手本': 'model', '同じ': 'same', '左右反転': 'mirror'}


def parse_groups(md):
    """報告の「同じ音楽の区間」の行（report_line）→ 画面に出す形 [{'name', 'bars', 'occ': [{'b0', 'b1', 'kind'}]}]（kind＝model・same・
    mirror）。行が無ければ None・見つからなかったは []（parse_line と同じ行を読む・帯に繰り返しを出す app/repeats.py が使う）"""
    import re
    line = next((x for x in md.splitlines() if x.startswith('- 同じ音楽の区間（')), None)
    if line is None:
        return None
    out = []
    for m in re.finditer(r'(自動\d+) (\d+) 小節: ((?:拍 [-\d.]+（[^）]+）(?:→)?)+)', line):
        L = int(m.group(2))
        occ = [{'b0': float(b), 'b1': float(b) + 4 * L, 'kind': KIND.get(k, 'same')}
               for b, k in re.findall(r'拍 ([-\d.]+)（([^）]+)）', m.group(3))]
        if len(occ) >= 2:
            out.append({'name': m.group(1), 'bars': L, 'occ': occ})
    return out


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


def apply(hits, groups, secs):
    """手本（1 回目）の打点の並びを 2 回目からへ写し、同じ振りの印を付ける → (打点, 使ったグループ)。手本に打点が無い・ほかの同じ振りと
    重なるグループは使わない"""
    hits = sorted(hits, key=lambda h: h.beat)
    inside = lambda h, r: r[0] - EPS <= h.beat < r[1] - EPS
    used = []
    for gi, g in enumerate(groups):
        if any(getattr(h, 'motif', None) and any(inside(h, r) for r in g['occ']) for h in hits):
            continue
        m0 = g['occ'][0]
        model = [h for h in hits if inside(h, m0)]
        if not model:
            continue
        idx = IDX0 + gi
        # 左右反転の回はグループごとに交互（反転ばかりだと左右反転の 4 拍が人の上位を超えた）。前の版から引き継いだ組（carry）はその向き
        flip = g['flip'] if 'flip' in g else len(used) % 2
        # 手本（occ 0）は反転しない。前は occ % 2 != flip で、flip=1 のグループの手本に反転の印が付き、手本が 1 回目の置き方の左右反転に
        # なって写した「同じ」の回が手本の左右反転になった（パピヨンの拍 199 → 312・The Cup of Life の「同じ」の回で中身まで同じが 5%）
        mk = lambda b0, occ: {'group': g['name'], 'key': g['name'], 'variant': 'a', 'mode': None, 'idx': idx, 'b0': b0, 'occ': occ,
                              'mirror': occ > 0 and occ % 2 != flip, 'auto': True}
        for h in model:
            h.motif = mk(m0[0], 0)
        for k, r in enumerate(g['occ'][1:], 1):
            new = []
            for h in model:
                b = r[0] + (h.beat - m0[0])
                if b >= r[1] - EPS:
                    continue
                si, pi = _sec_phr(secs, b)
                q = rhythm.Hit(b, h.hands, si, pi, h.src, h.s, h.midi, h.accent)
                for a in ('force_dbl', 'force_strong', 'min_gap'):
                    if hasattr(h, a):
                        setattr(q, a, getattr(h, a))
                q.motif = mk(r[0], k)
                new.append(q)
            hits = sorted([h for h in hits if not inside(h, r)] + new, key=lambda h: h.beat)
        g['flip'] = flip
        used.append(g)
    return hits, used


def report_line(groups):
    if groups is None:
        return ''
    if not groups:
        return '- 同じ音楽の区間（自動の同じ振り・docs/方針.md 6.31）: 見つからなかった（伴奏と歌のくり返しの記号が 2 小節以上同じ並びの所が無い）'
    parts = []
    word = {v: k for k, v in KIND.items()}
    for g in groups:
        kinds = g.get('kinds')   # 回ごとの種類（派生でそろえた組＝基準の組から外した回があると番号の偶奇で決まらない・derive.check_groups）
        occ = '→'.join(f'拍 {b0:g}' + (f'（{word[kinds[k]]}）' if kinds else '（手本）' if k == 0 else '（左右反転）' if k % 2 != g.get('flip', 0) else '（同じ）')
                       for k, (b0, _) in enumerate(g['occ']))
        parts.append(f'{g["name"]} {g["bars"]} 小節: {occ}')
    return '- 同じ音楽の区間（自動の同じ振り・docs/方針.md 6.31）: ' + ' ／ '.join(parts)
