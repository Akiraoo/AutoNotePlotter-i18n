"""続けて左右反転（2026-11-08 利用者「短いセットを決めて、すぐ次に左右反転して入れる。右へ出たら次は左、左へ出たら右と連続性を持って。
くり返す範囲の長さは曲の流れに合わせて可変に」・docs/方針.md 6.33）。

自動の同じ振り（6.31・repeat.py）は離れた所（2 回目のサビ等）でくり返すだけ、短い往復（6.32）は同じ手の中の A B A B だけで、セットを手を
入れ替えて続けて打つ形は無かった。

1. セットの長さ（`_chains`）: 小節の頭ごとに、2 拍・1・2・4 小節の短い方から「次のセットのリズムが 1 つ目のセットとほぼ同じ」が続く
   一番短い長さ＝リズムが半分ずつくり返す所は 2 拍、小節ごとにくり返す所は 1 小節、伴奏の 4 小節の回りでだけくり返す所は 4 小節。
   リズムは歌・ドラムの打点とリズムの型（6.31・同じ音楽の小節は同じリズム）から来るので曲の流れに沿う。点の多い長さを選ぶと 4 小節の
   セットばかりになり、続きが減った（パピヨンで 12 → 4）。
2. リズムをそろえる（`unify`・打点の段・意思入れの後・自動の同じ振りの前＝手本の区間の続きは写した回にも出る）: 続きのどのセットも型
   （打点の数が真ん中のセットの位置・両手か片手かは位置ごとの多数決・強さは平均）の写しにする（足す・抜く）。少し違うリズムのままだと、
   打点が 1 つ多い・両手と片手が違う所から手の振りの向きの位相がずれ、後ろの反転が置けなかった（パピヨンで反転の印の 4 割）。型の片手の
   打点が奇数だと、手を入れ替えた反転はどう割り振っても置けない（両手の振りの数の和が奇数）ので、両手にできる打点（前後 1/2 拍が空いて
   いる・一番強い）を両手に、無ければ一番弱い片手の打点を抜く。
   同じ音楽の区間（repeat.py）の手本の境目・写す側にかかる続きは作らない（手本の中に収まる続きは写した回にも出る）。境目をまたぐと、手本の
   置き方が反転の印と同じ振りの写しで食い違い、反転も写しも崩れた（パピヨンの拍 195〜203 の反転 1/5・拍 199 → 312 の写しが「同じ」の
   はずが左右反転に）。
3. 流れの計算の印（`plan`・流れの計算の直前）: 2 つ目からのセットの打点に Event.echo（セットの長さ）＝1 セット前の同じ拍の打点の、手を
   入れ替えた左右反転に寄せる（flow.Style.w_echo）＝右 → 左 → 右 …（最大 MAX_UNITS）。決めたノーツ・同じ振りの写す側・息つぎの打点がある
   所は使わない。リズムをそろえていない打点（派生など）は 1 で選び直す。
4. 前のセットを片手に（`plan`・2 拍と 1 小節のセット）: 1 つ目のセットの片手の打点を全部同じ手に（Event.erun）＝右で打ったら次のセットは
   左で反転（2026-11-08 利用者「どこがくり返しか分からない」）。どちらの手かは流れの計算が候補ごとに選ぶ（右と決め打ちすると、前の手の
   振りの向きしだいで後ろの反転を置けない所が残った＝パピヨンの拍 9 で 6/8・拍 269 で 5/8）。左右交互のセット（R L R L）を反転しても L R L R＝ふつうの
   交互打ちにしか見えず、パピヨンの 12 の続きのうち「右の次に左」に見えたのは片手寄りの 4 つだけだった。片手で続けて振れる間合い
   （handoff.G_MIN 以上）で、片手の打点が RUN_MAX 以下の時だけ。人の受け渡しも「2 振り → 反対の手で反転の 2 振り」が多い（6.28）。
5. 前の譜面に寄せる作り直し（compose の --prev-intent）: 寄せた打点（Event.anchored・重み 0.2）にも 3. 4. の印を付ける（`plan` の anchored_free）
   ＝反転の印と前の譜面への寄せの両方。前は寄せた打点を「決めたノーツ」とみて印を付けず、新しく作った譜面を指示を変えずに初めて作り直すと、
   反転で置いた所が弱い寄せだけになって変わった（作り物の曲で 58 ノーツ中 17・2 回目からは同じ＝反転の無いまま）。派生の基準に寄せる打点は今まで通り。
"""
from bisect import bisect_right

from . import rhythm
from .flow import MIRROR_D
from .handoff import G_MIN

MAX_UNITS = 4        # 1 つの続きのセットの数
MAX_SPAN = 32.0      # 1 つの続きの長さの上限（拍）＝4 小節のセットは 2 回まで
UNITS = (2.0, 4.0, 8.0, 16.0)   # セットの長さ（拍）＝2 拍・1・2・4 小節。短い方から
RHY_DIFF = 0.34      # 流れの計算の印だけ付ける時の、リズムがほぼ同じとみる違い（違う位置の数÷多い方の打点の数）
UNIFY_DIFF = 0.45    # リズムをそろえてよい違い（リズムの型 groove.THETA と同じ）
RUN_MAX = 4          # 前のセットを片手にする片手の打点の数の上限（長い片手の続きにしない）
GRID = 48
EPS = 1e-6


def _pos(b, b0):
    return round((b - b0) * GRID)


def _chains(items, mu, free, diff, odd_ok=False, span_ok=None):
    """items（beat・hands を持つ・拍の順）から続きのセットを選ぶ → [(拍の始まり, セットの長さ（拍）, セットの数)]。
    odd_ok=False なら、1 つ目のセットの片手の打点が奇数のセットは使わない。span_ok(拍の始まり, 終わり)＝続きにしてよい範囲"""
    span_ok = span_ok or (lambda a, b: True)
    bars = list(mu['bars'])
    if not bars or not items:
        return []
    edges = bars + [bars[-1] + 4]
    n = len(bars)
    beats = [x.beat for x in items]
    four = [abs(edges[i + 1] - edges[i] - 4) < EPS for i in range(n)]

    def seg(b0, b1):
        lo, hi = bisect_right(beats, b0 - EPS), bisect_right(beats, b1 - EPS)
        xs = items[lo:hi]
        return frozenset(_pos(x.beat, b0) for x in xs), xs

    def bars_of(b0, U):   # セットがかかる 4 拍の小節（小節の頭から・2 拍は小節の中の前か後ろ・途中に短い小節があれば None）
        i = bisect_right(edges, b0 + EPS) - 1
        if i < 0 or i >= n or (U >= 4 and abs(edges[i] - b0) > EPS) or b0 + min(U, 4) > edges[i + 1] + EPS:
            return None
        m = max(1, int(U // 4))
        return list(range(i, i + m)) if i + m <= n and all(four[i:i + m]) else None

    def chain(b0, U):
        bs = bars_of(b0, U)
        if bs is None:
            return None
        r0, x0 = seg(b0, b0 + U)
        if len(r0) < 2 or not all(free(x) for x in x0) or not span_ok(b0, b0 + U):
            return None
        if not odd_ok and sum(x.hands == 1 for x in x0) % 2:
            return None
        k, sc = 1, 0.0
        while k < MAX_UNITS and (k + 1) * U <= MAX_SPAN + EPS:
            s = b0 + k * U
            if bars_of(s, U) is None or not span_ok(b0, s + U):
                break
            rk, xk = seg(s, s + U)
            if len(r0 ^ rk) > diff * max(len(r0), len(rk)) or not all(free(x) for x in xk):
                break
            sc += len(r0 & rk) - 0.5 * len(r0 ^ rk)
            k += 1
        return k if k >= 2 and sc > 0 else None

    out, i = [], 0
    while i < n:
        best = next(((U, k) for U in UNITS for k in [chain(edges[i], U)] if k), None)   # 続きができる一番短い長さ
        if best is None:
            i += 1
            continue
        U, k = best
        out.append((edges[i], U, k))
        end = edges[i] + U * k
        while i < n and edges[i] < end - EPS:
            i += 1
    return out


def _room(xs, j):
    """xs[j] を両手同時にできる（前後 1/2 拍が空いている＝rhythm.choose_hits と同じ決まり）"""
    b = xs[j].beat
    return (j == 0 or b - xs[j - 1].beat >= 0.5 - EPS) and (j + 1 == len(xs) or xs[j + 1].beat - b >= 0.5 - EPS)


def _span_ok(regions):
    """同じ音楽の区間（repeat.find の occ の並び・先頭が手本）: 続きは 1 つの手本の中に収まるか、どの手本・写す側にもかからない"""
    def ok(a, b):
        if any(occ[0][0] - EPS <= a and b <= occ[0][1] + EPS for occ in regions):
            return True
        return not any(a < r1 - EPS and b > r0 + EPS for occ in regions for r0, r1 in occ)
    return ok


def unify(hits, mu, ons, avoid=(), regions=(), keep=None, touch=(), grow=()):
    """打点の段: 続きのセットを選び、2 つ目からのセットのリズムを 1 つ目の写しにする → (打点, 報告の元 {chains, added, removed, hands, doubled,
    thinned, regrown})。
    avoid＝人の指示の区間（リズムを変えない）。同じ振りの印のある打点・残したノーツも変えない。regions＝同じ音楽の区間の occ の並び（_span_ok）。
    keep＝前の版の続き [(拍の始まり, セットの長さ, セットの数)]（parse_table・前の譜面に寄せる作り直し）: 指示が変わった所（touch）にかからない
    続きはそのまま使い、新しく選ぶのは touch か外した続きの中だけ（棚上げの 2・2026-11-09〜10）。
    grow＝指示が無くなった所（repeat.gone）: まっさらに選んだ続きがそこにかかり、引き継いだ続きを同じセットの長さ・同じ区切りで含むなら、
    元の続きに戻す（2026-11-10 利用者「分かれた組だけ元の形に戻す」・regrown）"""
    if not hits or not mu or not mu.get('bars'):
        return hits, None
    hs = sorted(hits, key=lambda h: h.beat)
    inside = lambda b: any(r0 - EPS <= b < r1 - EPS for r0, r1 in avoid)
    free = lambda h: not getattr(h, 'motif', None) and not getattr(h, 'kept', False) and not inside(h.beat)
    rep = {'chains': [], 'added': 0, 'removed': 0, 'hands': 0, 'doubled': 0, 'thinned': 0, 'regrown': []}
    if keep is None:
        chains = _chains(hs, mu, free, UNIFY_DIFF, odd_ok=True, span_ok=_span_ok(regions))
    else:
        hit = lambda a, b: any(a < y - EPS and b > x + EPS for x, y in touch)
        kept = [c for c in keep if not hit(c[0], c[0] + c[1] * c[2]) and _span_ok(regions)(c[0], c[0] + c[1] * c[2])]
        base = _span_ok(regions)
        if grow:
            for fs, fU, fk in _chains(hs, mu, free, UNIFY_DIFF, odd_ok=True, span_ok=base):
                fe = fs + fU * fk
                if not any(fs < y - EPS and fe > x + EPS for x, y in grow):
                    continue
                inner = [c for c in kept if c[0] < fe - EPS and c[0] + c[1] * c[2] > fs + EPS]
                if inner and all(c[1] == fU and c[0] >= fs - EPS and c[0] + c[1] * c[2] <= fe + EPS
                                 and abs((c[0] - fs) / fU - round((c[0] - fs) / fU)) < EPS for c in inner):
                    kept = [c for c in kept if c not in inner] + [(fs, fU, fk)]
                    rep['regrown'].append((fs, fU, fk))
        room = [(s, s + U * k) for s, U, k in keep if (s, U, k) not in kept] + list(touch)
        ok2 = lambda a, b: (base(a, b) and any(x - EPS <= a and b <= y + EPS for x, y in room)
                            and not any(a < s + U * k - EPS and b > s + EPS for s, U, k in kept))
        chains = sorted(kept + _chains(hs, mu, free, UNIFY_DIFF, odd_ok=True, span_ok=ok2))
    cand = sorted((o for kd in ('vocal', 'kick', 'snare', 'hihat', 'other', 'bass') for o in (ons or {}).get(kd, [])), key=lambda o: o.beat)
    cb = [o.beat for o in cand]

    def near(b):   # 足す位置の近くの打点の候補（1/24 拍以内・groove と同じ）
        j = bisect_right(cb, b)
        best = None
        for o in cand[max(0, j - 3):j + 3]:
            if abs(o.beat - b) <= 1 / 24 + EPS and (best is None or o.s > best.s):
                best = o
        return best

    def unit(b0, U):
        return {_pos(h.beat, b0): h for h in hs if b0 - EPS <= h.beat < b0 + U - EPS}

    for s, U, k in chains:
        units = [unit(s + j * U, U) for j in range(k)]
        # 型の位置＝打点の数が真ん中（2 つなら少ない方・同じなら前）のセット（密度を変えない・groove の型と同じ考え）。両手か片手かはその位置に
        # 打点のあるセットの多数決（同じ数なら片手＝写しで両手が増えすぎない）・強さは平均
        t = sorted(range(k), key=lambda j: (len(units[j]), j))[(k - 1) // 2]
        tmpl = {}
        for p, h in units[t].items():
            src = [u[p] for u in units if p in u]
            tmpl[p] = (2 if 2 * sum(x.hands == 2 for x in src) > len(src) else 1, sum(x.s for x in src) / len(src), h)
        ps = sorted(tmpl)
        if sum(v[0] == 1 for v in tmpl.values()) % 2:   # 片手の打点が奇数: 両手にできる打点を両手に、無ければ一番弱い片手の打点を抜く
            before = max((h.beat for h in hs if h.beat < s - EPS), default=None)
            after = min((h.beat for h in hs if h.beat >= s + U * k - EPS), default=None)

            def roomy(i):   # セットの中の前後と、つなぎ目（前のセットの最後・次のセットの頭＝同じ型）が 1/2 拍以上
                gp = (ps[i] - ps[i - 1]) / GRID if i else (U - ps[-1] / GRID + ps[0] / GRID)
                gn = (ps[i + 1] - ps[i]) / GRID if i + 1 < len(ps) else (U - ps[-1] / GRID + ps[0] / GRID)
                ok = gp >= 0.5 - EPS and gn >= 0.5 - EPS
                if i == 0 and before is not None:
                    ok = ok and s + ps[0] / GRID - before >= 0.5 - EPS
                if i + 1 == len(ps) and after is not None:
                    ok = ok and after - (s + (k - 1) * U + ps[-1] / GRID) >= 0.5 - EPS
                return ok
            dbl = [i for i in range(len(ps)) if tmpl[ps[i]][0] == 1 and roomy(i)]
            if dbl:
                i = max(dbl, key=lambda i: (tmpl[ps[i]][1], -(ps[i] % (GRID // 2))))
                tmpl[ps[i]] = (2,) + tmpl[ps[i]][1:]
                rep['doubled'] += 1
            elif len(ps) >= 3:
                singles = [p for p in ps if tmpl[p][0] == 1]
                p = min(singles, key=lambda p: (tmpl[p][1], -(p % (GRID // 2)), -p))
                del tmpl[p]
                rep['thinned'] += 1
            else:
                continue
        drop = set()
        add = []
        for j in range(k):   # どのセットも型の写しに（足す・抜く・両手か片手か・強さ）
            b0 = s + j * U
            have = units[j]
            drop |= {id(h) for p, h in have.items() if p not in tmpl}
            rep['removed'] += sum(1 for p in have if p not in tmpl)
            for p, (hands, st, ref) in tmpl.items():
                h = have.get(p)
                if h is None:   # 足す: 何の音か・高さは近くの打点の候補から（無ければ型の打点から）
                    b = b0 + p / GRID
                    o = near(b)
                    add.append(rhythm.Hit(b, hands, ref.sec_i, ref.phr_i, o.kind if o else ref.src, st, o.midi if o else ref.midi))
                    rep['added'] += 1
                else:
                    if h.hands != hands:
                        h.hands = hands
                        rep['hands'] += 1
                    h.s = st
        hs = sorted([h for h in hs if id(h) not in drop] + add, key=lambda h: h.beat)
        rep['chains'].append((s, U, k))
    for j, h in enumerate(hs):   # 両手同時は前後 1/2 拍が空いている所だけ（つなぎ目で近くなった所）
        if h.hands == 2 and not _room(hs, j):
            h.hands = 1
    return hs, rep


def plan(events, mu, chains=None, min_gap=0.15, anchored_free=False):
    """流れの計算の直前: 続きのセットの 2 つ目からの打点に Event.echo を付ける → {chains, marked, lead: {前のセットを片手にした続きの拍の始まり}}。
    chains＝unify で選んだ続き（None なら events のリズムから選び直す）。1 セット前と今のセットの打点が全部自由な所の、1 セット前の同じ拍に
    同じ両手か片手の打点がある打点だけ。2 拍・1 小節のセットは、片手で続けて振れる間合いなら 1 つ目のセットの片手の打点を同じ手に（Event.erun）。
    anchored_free＝前の譜面に弱く寄せた打点（Event.anchored・compose の --prev-intent）も自由とみる（モジュールの説明の 5.）"""
    if not events or not mu or not mu.get('bars'):
        return {'chains': [], 'marked': 0, 'lead': {}}
    gmin = max(G_MIN, min_gap + 0.02)

    def free(e):
        return ((not e.fix or (anchored_free and getattr(e, 'anchored', False))) and not getattr(e, 'no_ho', False) and e.want is None
                and e.hoflex is None and e.loop is None and e.echo is None and e.erun is None and not e.relief)
    if chains is None:
        chains = _chains(events, mu, free, RHY_DIFF)
    beats = [e.beat for e in events]

    def seg(b0, b1):
        return events[bisect_right(beats, b0 - EPS):bisect_right(beats, b1 - EPS)]
    ok = {id(e) for e in events if free(e)}   # 印を付ける前に決める（付けた印で次のセットが自由でなくならないように）
    used, marked, lead = [], 0, {}
    for s, U, k in chains:
        units = [seg(s + j * U, s + (j + 1) * U) for j in range(k)]
        got = 0
        for j in range(1, k):
            if not units[j - 1] or not units[j] or not all(id(e) in ok for e in units[j - 1] + units[j]):
                continue
            prev = {_pos(e.beat, s + (j - 1) * U): e for e in units[j - 1]}
            for e in units[j]:
                r = prev.get(_pos(e.beat, s + j * U))
                if r is not None and r.hands == e.hands:
                    e.echo = U
                    got += 1
        if got:
            used.append((s, U, k))
            marked += got
            singles = [e for e in units[0] if e.hands == 1]
            # 両手同時が奇数のセットは片手にしない: 手ごとの振りの数が両方奇数になり、両手同時で向きがそろうので、後ろのセットの反転を置けない
            # （「両右右」→「両左左」が 9 割崩れた）
            if (U <= 4 and 2 <= len(singles) <= RUN_MAX and (len(units[0]) - len(singles)) % 2 == 0 and all(id(e) in ok for e in units[0])
                    and all(b.sec - a.sec >= gmin - EPS for a, b in zip(singles, singles[1:]))):
                for e in singles:
                    e.erun = s
                lead[s] = True
    return {'chains': used, 'marked': marked, 'lead': lead}


def check(events, notes):
    """反転の印を付けた打点のうち、できた譜面で 1 セット前の打点の手を入れ替えた左右反転になった数 → (なった, 印)"""
    at = {}
    for n in notes:
        at.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    ok = tot = 0
    for e in events:
        if not e.echo:
            continue
        tot += 1
        cur, ref = at.get(round(e.beat, 4), {}), at.get(round(e.beat - e.echo, 4), {})
        ok += bool(cur) and set(cur) == {1 - c for c in ref} and all(cur.get(1 - c) == (3 - x, y, MIRROR_D.get(d, d)) for c, (x, y, d) in ref.items())
    return ok, tot


def report_line(pl, events, notes, urep=None):
    if not pl:
        return ''
    ok, tot = check(events, notes)
    kinds = {}
    for _, U, k in pl['chains']:
        kinds[U] = kinds.get(U, 0) + 1
    txt = '・'.join(f'{"2 拍" if U == 2 else f"{int(U // 4)} 小節"}のセット {c}' for U, c in sorted(kinds.items()))
    uni = (f'・リズムをそろえた打点 足し {urep["added"]}・抜き {urep["removed"]}・両手か片手か {urep["hands"]}'
           f'（片手の打点を偶数に: 両手に {urep["doubled"]}・抜き {urep["thinned"]}）'
           if urep else '')
    one = f'・前のセットを片手に {len(pl.get("lead") or {})}' if pl['chains'] else ''
    return (f'- 続けて左右反転（docs/方針.md 6.33）: 続き {len(pl["chains"])}（{txt or "無し"}{one}）・反転にした打点 {tot} のうち'
            f'手を入れ替えた左右反転になった {ok}{uni}')


def parse_table(md):
    """報告の「続けて左右反転の場所」の表（table）→ [(拍の始まり, セットの長さ, セットの数)]（表が無ければ None）。表に出るのは印を付けた続きだけ"""
    import re
    if '## 続けて左右反転の場所' not in md:
        return [] if md.count('- 続けて左右反転（') else None
    out = []
    for m in re.finditer(r'^\| ([-\d.]+)〜([-\d.]+)(?:（[^）]*）)? \| (2 拍|(\d+) 小節)×(\d+)', md, re.M):
        U = 2.0 if m.group(3) == '2 拍' else 4.0 * int(m.group(4))
        out.append((float(m.group(1)), U, int(m.group(5))))
    return out


def table(pl, events, notes, tempo=None):
    """報告の表（続きの場所・セット・手の並び・反転になった数）の行。tempo（拍→秒）があれば時刻も"""
    if not pl or not pl['chains']:
        return []
    at = {}
    for n in notes:
        at.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    keys = sorted(at)
    hand = lambda m: '両' if len(m) == 2 else '左右'[next(iter(m))]
    mm = (lambda b: f'{int(tempo.sec(b) // 60)}:{tempo.sec(b) % 60:04.1f}') if tempo else None
    ev = {round(e.beat, 4): e for e in events if e.echo}
    rows = ['| 拍（時刻） | セット | 手の並び（｜＝セットの区切り） | 反転になった |', '|---|---|---|---|']
    for s, U, k in pl['chains']:
        seq = '｜'.join(''.join(hand(at[b]) for b in keys if s + j * U - EPS <= b < s + (j + 1) * U - EPS) for j in range(k))
        tot = okn = 0
        for b in keys:
            e = ev.get(b)
            if e and s - EPS <= b < s + U * k - EPS:
                tot += 1
                ref = at.get(round(b - e.echo, 4), {})
                okn += set(at[b]) == {1 - c for c in ref} and all(at[b].get(1 - c) == (3 - x, y, MIRROR_D.get(d, d)) for c, (x, y, d) in ref.items())
        name = '2 拍' if U == 2 else f'{int(U // 4)} 小節'
        side = '・前を片手に' if (pl.get('lead') or {}).get(s) else ''
        when = f'{s:g}〜{s + U * k:g}' + (f'（{mm(s)}〜{mm(s + U * k)}）' if mm else '')
        rows.append(f'| {when} | {name}×{k}{side} | {seq} | {okn}/{tot} |')
    return rows
