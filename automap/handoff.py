"""左右の受け渡し（2026-11-08 利用者「人の譜面は右手主導の形の後に左手で左右反転した形が出る・A と B 両方入った受け渡しを入れよう」・
docs/方針.md 6.28・6.29）: 片手の打点が同じ間合いで続く所を、手が 2 振りずつ交代する形（右 2 → 左 2 → …）にする。

人のランク譜面（★5〜8.5 の Expert／Expert+）: 同じ手が続けて振る割合はアプリの約 2 倍（21% と 12%）で、リズムは同じ＝手の割り振りの違い。
同じ手の続きの約 2/3 は受け渡しの一部。受け渡しは片手の打点 100 あたり 3〜4（中央値 3.1・平均 4.4）・2 振り→2 振りが 68%・54% は次の受け渡しに
連なる・拍の頭から 62%・先の手の 1→2 振り目の間合いは中央値 0.23 秒（10〜90% が 0.15〜0.46 秒）。受け渡しの 19% は後ろが前の完全な左右反転
（偶然 6%）で、反転は右から始める方が多い（65%）。後ろを簡単にする傾向は 2〜3 振りの単位では無い（入れない）。

作り: `plan` が打点の並び（flow.Event）から、片手の打点が 2 つずつ同じ間合いで並ぶ所を選び、手を決める（Event.want）。反転にする所は
手を決めず、1 打点多く押さえて（Event.hoflex＝(始まりの拍, 段の数)）、流れの計算が候補ごとに始まりと先の手を決める（両手の振りの向きが
そろう所から始め、後の手の振りを 2 打点前の左右反転に寄せる・flow.generate の flex）。人の譜面も、そろう所は打点の半分ほどで、反転は
そろう所に置いている。始まりを決め打ちすると 4〜6 割の所で振りの位相が逆になり反転を置けなかった（手が合った所でも反転は 1 曲 0〜2）。
選び方は種と拍から決まる値（flow._jitter_key）で決める＝同じ打点なら作り直しても同じ所。
前の譜面に寄せる打点（Event.anchored・派生の基準に寄せる打点も）には新しく計画せず、前の譜面で同じ手が続いていた所の手を残す（`carry`）＝
指示を変えずに作り直した所の受け渡しが、同じ手の続きの減点で崩れない。
"""
from .flow import LEFT, RIGHT, MIRROR_D, _mix64, _jitter_key

RATE = 3.5            # 片手の打点 100 あたりの受け渡し（人の中央値 3.1・平均 4.4 の間）
G_MIN, G_MAX = 0.17, 0.6   # 同じ手の 1→2 振り目の間合い（秒）。下は流れの計算の最短の間（0.15）より少し上
P_CHAIN = 0.5         # もう 1 段連ねる（人は 54% が次の受け渡しに連なる）
MAX_RUNS = 4          # 1 つのつなぎの段の数（2 振りずつ）
P_MIRROR = 0.5        # 後ろを前の左右反転にする（人の受け渡しの 19%。反転は間合いの条件がきつく置ける所が少ないので多め）
P_RIGHT = 0.55        # 右から始める（反転は流れの計算が選ぶ・右を少し好む＝flow.Style.w_ho_lead）
CARRY_W = 2.5         # 前の譜面の同じ手の続きを残す重み（Event.want_w）
CARRY_MIR_W = 3.0     # 前の譜面の左右反転の受け渡しの置き方に寄せる重み（Event.fix_w・flow.Style.w_ho_mirror と同じ。寄せる重み 0.2 のままだと
                      # 指示を変えずに作り直して反転が 5→1・6→1 に崩れた）
EPS = 1e-3


def _u(seed, beat, salt):
    """種と拍から決まる 0〜1"""
    return (_mix64(_jitter_key(seed, beat) ^ (salt * 0x9E3779B97F4A7C15 & ((1 << 64) - 1))) >> 11) * (1.0 / (1 << 53))


def _eligible(ev):
    """計画してよい打点: 片手・決めたノーツ（同じ振り・残したノーツ・決め・前の譜面に寄せる）・息つぎ・振りの速さの上限の指示が無い"""
    return ev.hands == 1 and not ev.fix and not ev.relief and not ev.min_gap and ev.want is None and not getattr(ev, 'no_ho', False) and not ev.echo and ev.erun is None


def _weight(beat, bars):
    """始まりの重み（人は拍の頭から 62%・半拍 16%）。小節の頭はもう少し上げる"""
    on = abs(beat - round(beat)) < EPS
    if on and bars is not None and any(abs(beat - b) < EPS for b in bars):
        return 2.5
    return 2.0 if on else 1.0 if abs(beat * 2 - round(beat * 2)) < EPS else 0.6


def _runs_from(events, i, gmin):
    """打点 i から 2 振りずつの段が何段続けられるか（0 か 2〜MAX_RUNS）。どの段も 1→2 振り目の間合い（拍）が同じで、秒は gmin〜G_MAX。
    段と段の間は段の中の間合いの 0.5〜2 倍"""
    n = len(events)
    if i + 3 >= n:
        return 0
    d = events[i + 1].beat - events[i].beat
    k = 0
    while k < MAX_RUNS and i + 2 * k + 1 < n:
        a, b = events[i + 2 * k], events[i + 2 * k + 1]
        if not (_eligible(a) and _eligible(b)) or abs((b.beat - a.beat) - d) > EPS or not gmin - EPS <= b.sec - a.sec <= G_MAX + EPS:
            break
        if k and not 0.5 * d - EPS <= a.beat - events[i + 2 * k - 1].beat <= 2 * d + EPS:
            break
        k += 1
    return k if k >= 2 else 0


def carry(events):
    """前の譜面に寄せる打点（Event.anchored・fix が片手）で、前の譜面で同じ手が続いていた所（間 1.2 秒未満）は、その手を使いたい手にする
    → 残した数。寄せる重み（0.2）は同じ手の続きの減点（1.0）より弱く、受け渡しを作った譜面を寄せて作り直すと崩れた"""
    n, prev = 0, None
    for ev in events:
        one = ev.hands == 1 and ev.fix and getattr(ev, 'anchored', False) and len(ev.fix) == 1
        h = next(iter(ev.fix)) if one else None
        if one and prev is not None and prev[0] == h and ev.sec - prev[1].sec < 1.2:
            for e in (prev[1], ev):
                if e.want is None:
                    e.want, e.want_w = h, CARRY_W
                    n += 1
        prev = (h, ev) if one else None
    # 前の譜面の左右反転の受け渡し（先の手 2・後の手 2 で後ろが左右反転）は置き方も強めに寄せる
    seq = [ev for ev in events if ev.hands == 1 and ev.fix and getattr(ev, 'anchored', False) and len(ev.fix) == 1]
    for j in range(len(seq) - 3):
        a1, a2, b1, b2 = seq[j:j + 4]
        (ha, pa1), (_, pa2), (hb, pb1), (_, pb2) = (next(iter(e.fix.items())) for e in (a1, a2, b1, b2))
        if not (next(iter(a2.fix)) == ha and next(iter(b2.fix)) == hb and ha != hb):
            continue
        mir = lambda p: (3 - p[0], p[1], MIRROR_D.get(p[2], p[2]))
        if tuple(pb1) == mir(pa1) and tuple(pb2) == mir(pa2):
            for e in (a1, a2, b1, b2):
                e.fix_w = max(e.fix_w or 0.0, CARRY_MIR_W)
    return n


def _periodic(events, i, n, gmin):
    """打点 i から n 個が計画してよい打点で、間合いが 1 つおきに同じ（拍・長短長短も可）・どれも gmin〜G_MAX 秒か。反転は始まりを流れの
    計算が 1 打点ずらすので、どちらから始めても 2 振りずつのリズムが同じになる並びだけ"""
    if i + n > len(events) or not all(_eligible(events[j]) for j in range(i, i + n)):
        return False
    g = [events[j + 1].beat - events[j].beat for j in range(i, i + n - 1)]
    s = [events[j + 1].sec - events[j].sec for j in range(i, i + n - 1)]
    return all(gmin - EPS <= x <= G_MAX + EPS for x in s) and all(abs(g[j] - g[j + 2]) <= EPS for j in range(len(g) - 2))


def plan(events, seed=1, bars=None, min_gap=0.15, rate=RATE):
    """受け渡しを計画して打点に印を付ける（Event.want・hoflex・ho）→ {target, cand, chains: [(拍, 段, 先の手（反転は None）, 反転)],
    n（受け渡しの数）, carried}。前の譜面に寄せる打点の手を残してから（carry）、残りの打点に新しく選ぶ"""
    carried = carry(events)
    gmin = max(G_MIN, min_gap + 0.02)
    # 目安は同じ振りの写す側（no_ho）を除いて数える（写す側には手本の受け渡しがそのまま写るので、全体で目安くらいになる）
    singles = sum(1 for e in events if e.hands == 1 and not getattr(e, 'no_ho', False))
    target = round(rate / 100 * singles)
    cands = []
    for i, ev in enumerate(events):
        k = _runs_from(events, i, gmin)
        if k:
            w = _weight(ev.beat, bars)
            cands.append((_u(seed, ev.beat, 1) ** (1 / w), i, k))   # 重み付きのくじ（大きい順に選ぶ）
    cands.sort(key=lambda c: -c[0])
    used, chains, n = set(), [], 0
    for _, i, k in cands:
        if n >= target:
            break
        if any(j in used for j in range(i - 1, i + 5)):   # 前後に 1 打点あける（別のつなぎとくっつけない）
            continue
        b0 = events[i].beat
        m = 2
        while m < k and _u(seed, b0, 10 + m) < P_CHAIN and not any(j in used for j in range(i + 2 * m, i + 2 * m + 3)):
            m += 1
        mir = _u(seed, b0, 2) < P_MIRROR and _periodic(events, i, 2 * m + 1, gmin) and (i + 2 * m + 1) not in used
        cid = len(chains)
        if mir:   # 反転: 1 打点多く押さえて、手と始まりは流れの計算に任せる
            for j in range(i, i + 2 * m + 1):
                events[j].hoflex, events[j].ho = (b0, m), cid
                used.add(j)
            chains.append((b0, m, None, True))
        else:
            lead = RIGHT if _u(seed, b0, 3) < P_RIGHT else LEFT
            for r in range(m):
                hand = lead if r % 2 == 0 else 1 - lead
                for j in (i + 2 * r, i + 2 * r + 1):
                    events[j].want, events[j].ho = hand, cid
                    used.add(j)
            chains.append((b0, m, lead, False))
        n += m - 1
    return {'target': target, 'cand': len(cands), 'chains': chains, 'n': n, 'carried': carried}


# ---- できた譜面の数え方（docs/方針.md 6.28 の物差しと同じ・振りは 1/8 拍でまとめる・両手同時は 0.07 拍以内） ----

def _swings(notes):
    out = []
    for c in (LEFT, RIGHT):
        last = None
        for n in sorted((n for n in notes if n['c'] == c), key=lambda n: n['beat']):
            if last is not None and n['beat'] - last <= 0.125 + 1e-6:
                last = n['beat']
                continue
            out.append((n['beat'], c, n['x'], n['y'], n['d']))
            last = n['beat']
    out.sort()
    seq = []
    for i, e in enumerate(out):
        both = (i > 0 and e[0] - out[i - 1][0] <= 0.07 and out[i - 1][1] != e[1]) or \
               (i + 1 < len(out) and out[i + 1][0] - e[0] <= 0.07 and out[i + 1][1] != e[1])
        seq.append(e + (both,))
    return seq


def stats(notes):
    """{same: 同じ手で続ける割合（両手同時を挟まない片手の打点の続き）, ho: 受け渡し, mir: 後ろが前の完全な左右反転の受け渡し（前が
    1 マスの上下だけの物は除く）, singles: 片手の振り}"""
    seq = _swings(notes)
    same = tot = 0
    for a, b in zip(seq, seq[1:]):
        if a[5] or b[5]:
            continue
        tot += 1
        same += a[1] == b[1]
    runs, cur, h = [], [], None
    for b, hand, x, y, d, both in seq:
        if both:
            if cur:
                runs.append((h, cur))
            runs.append(None)
            cur, h = [], None
            continue
        if hand != h and cur:
            runs.append((h, cur))
            cur = []
        h = hand
        cur.append((x, y, d))
    if cur:
        runs.append((h, cur))
    ho = mir = 0
    for A, B in zip(runs, runs[1:]):
        if not A or not B or len(A[1]) < 2 or len(B[1]) < 2:
            continue
        ho += 1
        trivial = len({(x, y) for x, y, _ in A[1]}) == 1 and all(d in (0, 1, 8) for *_, d in A[1])
        k = min(len(A[1]), len(B[1]))
        if not trivial and all(s2 == (3 - s1[0], s1[1], MIRROR_D[s1[2]]) for s1, s2 in zip(A[1][:k], B[1][:k])):
            mir += 1
    singles = sum(1 for e in seq if not e[5])
    return {'same': same / max(1, tot), 'ho': ho, 'mir': mir, 'singles': singles}


def _mirror_ok(seq):
    """片手のノーツの並び（先の手 2・後の手 2 …）が、手が 2 振りずつ交代し、後の段が前の段の左右反転か（1 つ目の受け渡しだけでも）"""
    if len(seq) < 4 or any(len(v) != 1 for v in seq[:4]):
        return False
    a1, a2, b1, b2 = (v[0] for v in seq[:4])
    if not (a1['c'] == a2['c'] and b1['c'] == b2['c'] and a1['c'] != b1['c']):
        return False
    return all((y['x'], y['y'], y['d']) == (3 - x['x'], x['y'], MIRROR_D.get(x['d'], x['d'])) for x, y in ((a1, b1), (a2, b2)))


def check(events, notes):
    """計画が、できた譜面でどれだけ守れたか → (手が合った打点, 手を決めた打点, 反転になった段, 反転にした段, ならなかった段の始まりの拍)。反転は始まりを流れの計算が
    決めるので、押さえた打点の頭からか 1 打点後ろからのどちらかで、手が 2 振りずつ交代して後ろが左右反転なら合ったとする"""
    at = {}
    for n in notes:
        at.setdefault(round(n['beat'], 4), []).append(n)
    ok = tot = 0
    flex = {}
    for ev in events:
        ns = at.get(round(ev.beat, 4)) or []
        if ev.hoflex is not None:
            flex.setdefault(ev.hoflex, []).append(ns)
        elif ev.ho is not None and ev.want is not None:
            tot += 1
            ok += len(ns) == 1 and ns[0]['c'] == ev.want
    miss = sorted(k[0] for k, seqs in flex.items() if not (_mirror_ok(seqs) or _mirror_ok(seqs[1:])))
    return ok, tot, len(flex) - len(miss), len(flex), miss


def report_line(pl, events, notes):
    """報告の行（計画が無ければ空）"""
    if not pl:
        return ''
    ok, tot, mok, mtot, miss = check(events, notes)
    s = stats(notes)
    return (f'- 左右の受け渡し（docs/方針.md 6.29）: 計画 {pl["n"]}（目安 {pl["target"]}・置ける所 {pl["cand"]}・つなぎ {len(pl["chains"])}'
            + (f'・前の譜面の同じ手の続きを残した打点 {pl["carried"]}' if pl['carried'] else '') + f'）・手が計画どおり {ok}/{tot}・反転にした所 {mok}/{mtot} が反転'
            + (f'（ならなかった所: 拍 {"・".join(f"{b:g}" for b in miss[:8])}）' if miss else '') + '。'
            f'できた譜面: 同じ手で続ける {s["same"]:.1%}・受け渡し {s["ho"]}（片手の振り 100 あたり {s["ho"] / max(1, s["singles"]) * 100:.1f}）・'
            f'左右反転 {s["mir"]}（人の★5〜8.5: 21%・3〜4・受け渡しの 19%）')
