"""量の目安（docs/アプリ仕様.md 8 節の 9・2026-10-26 利用者と決めた）: 自動で選んだ打点（意思入れの前）の量を、曲ごとの設定
「量の目安」（1秒のノーツの数）に合わせる。compose の --nps-target（アプリは作業ファイルの amount → app/library.py が数にして渡す）。

- 目安が無い＝今のまま（ここを通らない＝答えを1つも変えない）。
- 量＝ノーツの数 ÷ 最初から最後のノーツまでの秒（stats.summarize・型のデータベースの diff_stats と同じ数え方）。両手は 2 ノーツ。
  曲の頭の 1.6 秒より前は数えない（compose がそこに打たない）。
- 小節ごとに打点の数を同じ倍率に近づける（量のラインと同じ形＝曲の中の緩急はそのまま。打点の無い小節は空のまま）。倍率は、
  測り直しながら目安に合うまで動かす（拾える打点が足りない小節があるので、ほかの小節で補う）。
- 増やす: まず拾う打点を増やす＝半拍の目盛りの弱めの打点（歌・キック・スネア・楽器の両方）→ 半拍のハイハット → 1/4 拍の目盛り
  （歌・ドラム・楽器）→ 1/4 拍のハイハット。同じ段なら強い順。打点の間は 1/4 拍（と 0.075 秒）より詰めない。両手の前後
  （1/2 拍・決めた両手は 1/4 拍で、どちらも 0.12 秒以上）と途切れの間には足さない＝両手と途切れは今のまま残る（両手は別の指示＝
  区間の「両手」）。速い曲（1/4 拍が 0.12 秒未満）では強いキックの 1/4 拍隣にも足さない（意思入れの「キックで決める」で両手になる）。
- 減らす: 弱い打点から（1/4 拍の裏 → 半拍の裏 → 拍の頭、同じなら弱い物から）。小節の頭・両手・途切れの戻り・区間の最初の打点は残す。
- 意思入れの量のライン（50〜150%）は合わせた後の打点に掛かる。区間の量 ±（と元にする音）で選び直した打点も、合わせた倍率
  （ratio＝合わせた後の打点の数 ÷ 前）を掛ける（intent.apply の scale・make_scale）＝どちらも目安に対する割合。同じ振りの区間には
  掛けない（形の打点の並びは手本とアレンジの量で決める）。
"""
import bisect
import math

T_MIN = 1.6          # これより前（秒）には打たない（compose の hotStart よけと同じ）
GAP_BEAT = 0.25      # 足す打点と前後の打点の間（拍）
GAP_SEC = 0.075      # 〃（秒・速い曲で 1/4 拍が詰まりすぎないように）
DBL_SEC = 0.12       # 両手の前後に足す打点との間（秒）。決めた両手は 1/4 拍まで詰めてよいが、速い曲では同じ手が 0.12 秒未満で続く
TIERS = (            # 足す打点の候補の段（前の段から使う）: (目盛り, 目盛りの細かい方だけか, {音: 強さの下限})
    (2, False, {'vocal': 0.2, 'kick': 0.25, 'snare': 0.25, 'other': 0.35}),
    (2, False, {'hihat': 0.4}),
    (4, True, {'vocal': 0.2, 'kick': 0.25, 'snare': 0.25, 'other': 0.35}),
    (4, True, {'hihat': 0.4}),
)
K_RANGE = (0.2, 4.0)  # 小節ごとの倍率の範囲
TOL = 0.015          # 目安との差がこの割合より小さければ合わせ終わり
FAR = 0.05           # 目安からこれより外れたら報告で知らせる


def _on(b, g):
    return abs(b * g - round(b * g)) < 1e-6


def _lvl(b):
    """目盛りの強さ: 0＝拍の頭・1＝半拍の裏・2＝1/4 拍・3＝ほか（3連符など）"""
    return 0 if _on(b, 1) else 1 if _on(b, 2) else 2 if _on(b, 4) else 3


def measure(hits, tempo, t_min=T_MIN):
    """打点の1秒のノーツの数（両手は 2・曲の頭の t_min 秒より前は数えない）"""
    hs = [h for h in hits if tempo.sec(h.beat) >= t_min]
    if len(hs) < 2:
        return 0.0
    b0, b1 = min(h.beat for h in hs), max(h.beat for h in hs)
    span = tempo.sec(b1) - tempo.sec(b0)
    return sum(h.hands for h in hs) / span if span > 0 else 0.0


def _need(h):
    """打点 h の前後に空けておく拍（両手は 1/2 拍・決めた両手は 1/4 拍）"""
    if h.hands == 2:
        return 0.25 if getattr(h, 'force_dbl', False) else 0.5
    return 0.0


def pool(ons, tempo=None, end=None, avoid=(), t_min=T_MIN):
    """足す打点の候補 → [(段, −強さ, 拍, Onset)]（拍の順。同じ拍は前の段・強い物だけ）。avoid＝足さない拍の範囲 [(b0, b1)]
    （途切れの間）。tempo があれば曲の頭の t_min 秒より前は除く"""
    best = {}
    strong = {round(o.beat * 4) / 4 for o in ons.get('kick', []) if o.s >= 0.7}   # 強いキック（意思入れの「キックで決める」で両手になりやすい）
    for tier, (g, fine, th) in enumerate(TIERS):
        for kind, smin in th.items():
            for o in ons.get(kind, []):
                if o.s < smin or not _on(o.beat, g) or (fine and _on(o.beat, 2)):
                    continue
                if fine and tempo is not None and tempo.sec(o.beat + 0.25) - tempo.sec(o.beat) < DBL_SEC and \
                        (round(o.beat * 4) / 4 + 0.25 in strong or round(o.beat * 4) / 4 - 0.25 in strong):
                    continue   # 速い曲: 強いキックの 1/4 拍隣には足さない（そこが両手になると同じ手が 0.12 秒未満で続く）
                if end is not None and o.beat >= end - 1e-6:
                    continue
                if any(a + 0.05 < o.beat < b - 0.05 for a, b in avoid):
                    continue
                if tempo is not None and tempo.sec(o.beat) < t_min:
                    continue
                key = round(o.beat, 4)
                c = (tier, -o.s, o.beat, o)
                if key not in best or c[:2] < best[key][:2]:
                    best[key] = c
    return sorted(best.values(), key=lambda c: c[2])


def _sec_phr(secs, b):
    """拍 b の区間の番号・区間の中のフレーズの番号"""
    si = len(secs) - 1
    for i, s in enumerate(secs):
        if s.b0 - 1e-6 <= b < s.b1 - 1e-6:
            si = i
            break
    si = max(0, si)
    ph = (getattr(secs[si], 'phrases', None) or []) if secs else []
    pi = next((k for k, (p0, p1) in enumerate(ph) if p0 - 1e-6 <= b < p1 - 1e-6), 0)
    return si, pi


def scale(hits, k, bars, end, cands, secs, tempo=None, lo=None, hi=None):
    """小節ごとに打点の数を k 倍に近づける（lo〜hi があればその中の打点だけ数え、その中だけ足す・減らす）。
    → (打点（拍の順）, {'add': 足した数, 'del': 減らした数, 'short': 足りなかった数})"""
    from .rhythm import Hit
    hits = sorted(hits, key=lambda h: h.beat)
    lo = -math.inf if lo is None else lo
    hi = math.inf if hi is None else hi
    edges = list(bars) + [end]
    occ = [h.beat for h in hits]                 # 埋まっている拍（足すたびに入れる）
    need = {round(h.beat, 4): _need(h) for h in hits}
    cb = [c[2] for c in cands]
    first = {}
    for h in hits:
        first.setdefault(h.sec_i, h)
    keep_first = {id(h) for h in first.values()}
    out_del, added = set(), []
    st = {'add': 0, 'del': 0, 'short': 0}
    carry = 0.0

    def free(b):
        i = bisect.bisect_left(occ, b - 0.75)
        while i < len(occ) and occ[i] <= b + 0.75:
            x = occ[i]
            d = abs(x - b)
            nd = need.get(round(x, 4), 0.0)
            if d < max(GAP_BEAT, nd) - 1e-6:
                return False
            if tempo is not None and abs(tempo.sec(x) - tempo.sec(b)) < (DBL_SEC if nd else GAP_SEC) - 1e-9:
                return False
            i += 1
        return True

    for i in range(len(edges) - 1):
        a, b = max(edges[i], lo), min(edges[i + 1], hi)
        if b <= a + 1e-6:
            continue
        bh = [h for h in hits if a - 1e-6 <= h.beat < b - 1e-6 and id(h) not in out_del]
        if not bh:
            continue   # 打点の無い小節（静かな所・途切れ・休み）は空のまま
        want_f = len(bh) * k + carry
        want = int(math.floor(want_f + 0.5))
        carry = want_f - want
        if want > len(bh):
            n = 0
            j0, j1 = bisect.bisect_left(cb, a - 1e-6), bisect.bisect_left(cb, b - 1e-6)
            for c in sorted(cands[j0:j1], key=lambda c: (c[0], c[1], c[2])) if j1 > j0 else []:
                if len(bh) + n >= want:
                    break
                o = c[3]
                if not free(o.beat):
                    continue
                si, pi = _sec_phr(secs, o.beat)
                h = Hit(o.beat, 1, si, pi, o.kind, o.s, getattr(o, 'midi', 0.0))
                added.append(h)
                bisect.insort(occ, o.beat)
                need[round(o.beat, 4)] = 0.0
                n += 1
            st['add'] += n
            st['short'] += max(0, want - len(bh) - n)
        elif want < len(bh):
            prot = lambda h: (h.hands == 2 or getattr(h, 'reentry', False) or getattr(h, 'force_strong', False)
                              or abs(h.beat - edges[i]) < 1e-6 or id(h) in keep_first)
            order = sorted((h for h in bh if not prot(h)), key=lambda h: (-_lvl(h.beat), h.s, -h.beat))
            for h in order[:len(bh) - want]:
                out_del.add(id(h))
                st['del'] += 1
    out = [h for h in hits if id(h) not in out_del] + added
    out.sort(key=lambda h: h.beat)
    return out, st


def fit(hits, ons, secs, bars, end, target, tempo, avoid=()):
    """打点の1秒のノーツの数を目安 target に合わせる → (打点, 報告用の数 {target, before, after, k, ratio, add, del, short,
    n0, n1, dbl0, dbl1, far})。target が無い・打点が無い時は打点をそのまま返す"""
    base = measure(hits, tempo)
    info = {'target': target, 'before': base, 'after': base, 'k': 1.0, 'ratio': 1.0, 'add': 0, 'del': 0, 'short': 0,
            'n0': len(hits), 'n1': len(hits), 'dbl0': sum(h.hands == 2 for h in hits), 'dbl1': sum(h.hands == 2 for h in hits),
            'far': False}
    if not target or base <= 0 or not len(bars):
        return hits, info
    cands = pool(ons, tempo, end, avoid)
    k, best, tried = target / base, None, {}
    for _ in range(14):
        k = min(K_RANGE[1], max(K_RANGE[0], k))
        kk = round(k, 6)
        if kk in tried:
            break
        out, st = scale(hits, k, bars, end, cands, secs, tempo)
        v = measure(out, tempo)
        tried[kk] = v
        if best is None or abs(v - target) < abs(best[1] - target) - 1e-12:
            best = (out, v, k, st)
        if abs(v - target) <= TOL * target or v <= 0:
            break
        nk = k * target / v
        if (nk > k and k >= K_RANGE[1]) or (nk < k and k <= K_RANGE[0]):
            break
        # 足りない（増やしても増えない）時は倍率を上げても変わらない＝前の回と同じ量なら終わり
        if len(tried) >= 2 and abs(v - list(tried.values())[-2]) < 1e-9:
            break
        k = nk
    out, v, k, st = best
    info.update(after=v, k=k, ratio=len(out) / max(1, len(hits)), add=st['add'], **{'del': st['del']}, short=st['short'],
                n1=len(out), dbl1=sum(h.hands == 2 for h in out), far=abs(v - target) > FAR * target)
    return out, info


def make_scale(ons, secs, bars, end, tempo, ratio, avoid=()):
    """意思入れの区間の量 ±・元にする音で選び直した打点にも、目安で合わせた倍率を掛ける関数 fn(打点, b0, b1) → 打点（intent.apply の scale）。
    倍率がほぼ 1 なら None（何もしない）"""
    if abs(ratio - 1.0) < 1e-3:
        return None
    cands = pool(ons, tempo, end, avoid)

    def fn(hits, b0, b1):
        return scale(hits, ratio, bars, end, cands, secs, tempo, lo=b0, hi=b1)[0]
    return fn


def report_line(info, src=None):
    """compose の報告の行（目安がある時だけ）"""
    t, v = info['target'], info['after']
    s = (f'- 量の目安: 1秒 {t:.2f} ノーツ' + (f'（{src}）' if src else '') +
         f'。自動の打点 {info["before"]:.2f} → {v:.2f}（打点 {info["n0"]} → {info["n1"]}・足し {info["add"]}・減らし {info["del"]}・'
         f'小節ごとの倍率 {info["k"]:.2f}・両手 {info["dbl0"]} → {info["dbl1"]}）。量のライン・区間の量 ±はこの量に対する割合')
    if info['far']:
        why = '拾える打点が足りない（1/4 拍の目盛りまで足した）' if v < t else '減らせない打点（小節の頭・両手・区間の最初）が多い'
        s += f'。**目安 {t:.2f} に対して {v:.2f}**（{why}）'
    return s
