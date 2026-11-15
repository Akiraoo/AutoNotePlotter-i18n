"""譜面の緩急（試し・compose --relief・docs/方針.md 6.26）: 曲の中に「息つぎ」のまとまりを作る。

息つぎ＝易しい型を、同じ動きのまま続けるまとまり（ノーツは消さない＝意思入れの「休み」とは別）。作った譜面は同じ速さの人の譜面より、
8 拍ごとの形の難しさの波が小さく（下から 13%）、同じ動きのくり返しも少ない（下から 16%・人は振りの約 17%）＝ずっと同じ調子で新しい動きを
読み続ける。1 小節ごとのテーマの切り替えを減らすだけでは増えなかった（手から見たマスの目標が 2〜3 マスの往復を崩す）ので、息つぎの中だけ
その目標を外し、テーマに強く沿わせる。

どこを息つぎにするか（人の譜面 142 曲のまとまり 4,768 を数えた・6.26）:
- 形の難しさ（曲の中の z）の重み: 歌なし −0.20・盛り上がり +0.18・密度 −0.17 ＝ 歌の無い所・盛り上がりの低い所・密度の高い所ほど易しい。
  ただし説明できるのは 4% だけ＝人の波の大半は音楽と結びついていない。どこにするかは決めごとで、データは向きだけ。
- 同じ音楽（くり返しの記号）は同じくらいの難しさ＝同じ記号は同じ役。易しいまとまりは曲の下 1/3 として 1 回平均 1.6 まとまり（3 つ以上は 16%）・
  間にはさまる数は中央値 1・90% 点 5。
打点は変えない（くり返しに合わせて消すのは密度の話で、別の設定）。人の指示（同じ振り・置き方・型の変わり方）がある打点は、そちらが勝つ。

どんな動きにするか（ランク譜面の Expert／Expert+ のくり返しの中の振り 41 万）: 型の長さは 2 振りが 79%・4 振りが 15%。くり返す回数は 2 回が 80%・3 回が 16%
（6 回以上は 1%）＝短い往復を 1〜2 小節やって少し変える。真横の振りを含む型は 3%。最初の試しは 1 つのまとまりを 1 つの往復で埋めたら、どの曲も ↓20 ↑31 が
4 小節以上続いて人より長すぎた → 息つぎの中でも小節の音楽の記号が変われば、もう 1 つの往復へ替える（同じ記号の小節は同じ往復）。型は自分の側の列だけ・
真横なし（反対側の列の型 ↓10 ↑12 は両手が交差して、型どおりに置けたのが 33〜48%）。
"""
import math
import random

from . import form, intent, style, theme

SHARE = 1 / 3      # 息つぎにする小節の割合の目安（人の譜面の「曲の下 1/3」に合わせる）
MAX_RUN = 3        # 続けて息つぎにするまとまりの数の上限
MAX_GAP = 5        # 息つぎの無いまとまりが続く数の上限（人の譜面の 90% 点）
W_NOVOCAL, W_TENSION, W_DENS = 0.20, 0.18, 0.17   # 易しさの点の重み（人の譜面の形の難しさの重みの符号を返した物）
MIN_HITS = 6       # これより打点の少ないまとまりは息つぎにしない（くり返しにならない）
THEME_K = 2.0      # 息つぎの打点のテーマに沿う重みの倍率（Event.relief）
W_EASE = 1.0       # 息つぎのテーマを選ぶ時の形の難しさの重み
N_THEMES = 4       # 1 曲の息つぎのテーマの数（記号ごとに 2 つずつ順に割り当てる＝同じ音楽は同じ型）
PICK_JITTER = 1.0  # 息つぎのテーマを選ぶ時の揺らぎ（曲ごと。小さいと、どの曲も同じ往復になった）
POP = 0.1          # 息つぎのテーマの使われた曲の数の重み（theme.fit の pop。0.3 だと 12 曲全部の主な往復が ↓20 ↑31 になった）
GID = 800000       # 息つぎのテーマの番号（まとまりごと＝まとまりの中は小節の頭でたどり直さない）
LOCK_KEYS = ('motif', 'keep', 'variety', 'variant', 'rare', 'band', 'kime') + intent.PLACE   # 息つぎにしない人の指示

_DIRV = {0: (0, 1), 1: (0, -1), 2: (-1, 0), 3: (1, 0), 4: (-1, 1), 5: (1, 1), 6: (-1, -1), 7: (1, -1)}


def _z(v):
    if not v:
        return []
    m = sum(v) / len(v)
    s = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
    return [(x - m) / s if s > 1e-9 else 0.0 for x in v]


def easy_scores(blocks, counts):
    """まとまりごとの易しさの点（大きいほど息つぎ向き）。counts＝まとまりごとの打点の数。打点の少ないまとまりは None"""
    ok = [i for i, n in enumerate(counts) if n >= MIN_HITS]
    zt = _z([blocks[i].tension for i in ok])
    zd = _z([counts[i] / max(blocks[i].b1 - blocks[i].b0, 1e-6) for i in ok])
    out = [None] * len(blocks)
    for k, i in enumerate(ok):
        out[i] = W_NOVOCAL * (not blocks[i].vocal) - W_TENSION * zt[k] + W_DENS * zd[k]
    return out


def choose(blocks, scores, locked=(), share=SHARE, max_run=MAX_RUN, max_gap=MAX_GAP):
    """息つぎにするまとまりの番号の集まり。同じ記号は同じ役（点の平均の高い記号から、小節の割合が share に届くまで）→ 続きすぎを切る →
    間が空きすぎる所へ足す。locked＝人の指示があって息つぎにしないまとまり"""
    usable = [i for i, s in enumerate(scores) if s is not None and i not in locked]
    if not usable:
        return set()
    by = {}
    for i in usable:
        by.setdefault(blocks[i].base, []).append(i)
    bars = lambda i: blocks[i].i1 - blocks[i].i0
    total = sum(bars(i) for i in usable)
    order = sorted(by, key=lambda k: (-sum(scores[i] for i in by[k]) / len(by[k]), by[k][0]))
    rest, got = set(), 0
    for k in order:
        n = sum(bars(i) for i in by[k])
        if got and got + n > share * total * 1.15:   # 大きすぎる記号は飛ばして次へ（1 つの記号で割合を超えない）
            continue
        rest.update(by[k])
        got += n
        if got >= share * total * 0.9:
            break
    # 続きすぎ: 点の高い順に残す
    run = []
    for i in list(range(len(blocks))) + [None]:
        if i is not None and i in rest:
            run.append(i)
            continue
        if len(run) > max_run:
            for j in sorted(run, key=lambda j: (scores[j], -j))[:len(run) - max_run]:
                rest.discard(j)
        run = []
    # 間が空きすぎ: 間の中の点の一番高いまとまりを足す（くり返して、どの間も max_gap 以下に）
    changed = True
    while changed:
        changed = False
        marks = [-1] + sorted(rest) + [len(blocks)]
        for p, q in zip(marks, marks[1:]):
            if q - p - 1 > max_gap:
                cand = [i for i in usable if p + 2 <= i <= q - 2]   # 前後の息つぎに続かない所から
                if not cand:
                    continue
                mid = (p + q) / 2
                rest.add(max(cand, key=lambda i: (scores[i] - 0.02 * abs(i - mid), -i)))
                changed = True
                break
    return rest


def _hard(seq):
    """型の形の難しさ（tools/library_build/build_db.hard_parts と同じ式・輪として数える）"""
    P = len(seq)
    pr = [(seq[k], seq[(k + 1) % P]) for k in range(P)]
    turn = []
    for a, b in pr:
        va, vb = _DIRV.get(a[2]), _DIRV.get(b[2])
        if va and vb:
            c = (va[0] * vb[0] + va[1] * vb[1]) / (math.hypot(*va) * math.hypot(*vb))
            turn.append((180 - math.degrees(math.acos(max(-1, min(1, c))))) / 45)
    move = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in pr) / P
    return (0.5 * move + (sum(turn) / len(turn) if turn else 0.0) + 0.5 * sum(s[2] in (4, 5, 6, 7) for s in seq) / P
            + sum(s[0] == 0 for s in seq) / P + 0.5 * sum(s[1] == 2 for s in seq) / P)


def ease_of(t):
    """テーマの形の難しさ（実際に渡す形＝軽くした後の a・b の平均）"""
    a, b = theme.transform(t, 'base')
    return (_hard(a) + _hard(b)) / 2


def usable(t):
    """息つぎに使える型か: 4 振りまで・自分の側の列だけ・真横と点なし・両方の手が 2 マス以上を使う（同じマスの上下は動きが無さすぎる）"""
    for c in (t.a, t.b):
        if len(c) > 4 or len({(x, y) for x, y, _ in c}) < 2 or any(x < 2 or d in (2, 3, 8) for x, _, d in c):
            return False
    return True


def candidates(lib, themes):
    """息つぎのテーマの候補＝テーマに使える型＋2 振りの片手の型（ふだんはどの曲にも出て単調にするので使わない・style.want。息つぎでは使う）のうち
    usable な物"""
    hm, _ = theme.thresholds(lib)
    out, seen = [], set()
    for t in themes:
        if t.key() not in seen and usable(t):
            seen.add(t.key())
            out.append(t)
    for h in lib.get('hands') or []:
        if len(h['cycle']) == 2 and h['maps'] >= hm:
            c = [tuple(s) for s in h['cycle']]
            t = theme.Theme(c, c, h['maps'], 'sym', h.get('lift'))
            if t.key() not in seen and usable(t):
                seen.add(t.key())
                out.append(t)
    return out


def pick(cands, tilt, sps, seed, k=N_THEMES):
    """息つぎのテーマを k 個（性格は「simple」・2 振りも可・易しいほど良い・先に選んだ物と似ている物は避ける）"""
    tl = tilt or {'outer': 0.0, 'move': 0.0, 'row': 0.0, 'diag': 0.0}
    want = style.want(theme.WANT['simple'], tl, sps=sps)
    want['P'] = 2
    rng = random.Random((int(seed) ^ 0x5F356495) & 0xFFFFFFFF)
    chosen = []
    for _ in range(min(k, len(cands))):
        best, bv = None, None
        for t in cands:
            v = theme.fit(t, want, POP) + W_EASE * ease_of(t) + rng.random() * PICK_JITTER
            for u in chosen:
                v += 100.0 if u.key() == t.key() else 0.8 * theme._similar(t, u)
            if bv is None or v < bv:
                best, bv = t, v
        chosen.append(best)
    return chosen


def block_at(blocks, beat):
    """拍が入っているまとまりの番号（無ければ None）"""
    for i, b in enumerate(blocks):
        if b.b0 - 1e-6 <= beat < b.b1 - 1e-6:
            return i
    return None


def _locked(blocks, it):
    """人の指示（同じ振り・そのまま残す・置き方・型の変わり方・案・珍しい型まで・★の帯・決め）の区間が半分を超えるまとまり（そちらが勝つので息つぎに
    しない）。打点の数ではなく区間の長さで見る＝どの難易度でも同じ（打点で数えると、間引きで半分をまたいで難易度ごとに息つぎの場所がずれた）"""
    spans = [(r['b0'], r['b1']) for r in (it or {}).get('ranges') or [] if any((r.get('set') or {}).get(k) for k in LOCK_KEYS)]
    out = set()
    for i, b in enumerate(blocks):
        cov, pos = 0.0, b.b0
        for x, y in sorted(spans):
            x, y = max(x, pos), min(y, b.b1)
            if y > x:
                cov += y - x
                pos = y
        if cov * 2 > b.b1 - b.b0:
            out.add(i)
    return out


def _manual(h):
    return bool(getattr(h, 'motif', None) or getattr(h, 'kept', False) or getattr(h, 'mods', None) or getattr(h, 'variety', None))


def plan(blocks, auto_hits, it, lib, themes, tilt, sps, seed, stars_tag=None):
    """息つぎの計画 → {'rest': まとまりの番号の集まり, 'scores': 点, 'themes': テーマ, 'of': {番号: テーマ}, 'spans': [(拍, 拍)]}。
    auto_hits＝自動で拾った打点（量の設定・意思入れ・派生の間引きの前＝どの難易度でも同じ役になる）・it＝意思入れの表（人の指示の区間）・
    stars_tag＝★を書いたまとまり"""
    counts = [sum(1 for h in auto_hits if b.b0 - 1e-6 <= h.beat < b.b1 - 1e-6) for b in blocks]
    scores = easy_scores(blocks, counts)
    locked = _locked(blocks, it) | set(stars_tag or ())
    rest = choose(blocks, scores, locked, SHARE)
    ts = pick(candidates(lib, themes), tilt, sps, seed)
    seen, of = {}, {}
    for i in sorted(rest):
        base = blocks[i].base
        if base not in seen:   # 同じ記号は同じ 2 つの往復（主・副）
            j = 2 * len(seen)
            seen[base] = (ts[j % len(ts)], ts[(j + 1) % len(ts)]) if ts else None
        of[i] = seen[base]
    return {'rest': rest, 'scores': scores, 'themes': ts, 'of': of, 'spans': [(blocks[i].b0, blocks[i].b1) for i in sorted(rest)]}


def apply_guides(bgd, blocks, pl, mu):
    """小節ごとのテーマ（form.mix_guides 等）の息つぎの小節を、息つぎのテーマに置き換えた物。まとまりの中は、小節の音楽の記号が変わるたびに
    主・副の往復を替える（同じ記号の小節は同じ往復・form.mix_guides と同じ決まり）。続く間はテーマの番号を変えない＝小節の頭でたどり直さない"""
    out = dict(bgd)
    for i in pl['rest']:
        b, pair = blocks[i], pl['of'].get(i)
        if pair is None:
            continue
        seen, nxt, j = {}, 0, 0
        for k in range(b.i0, b.i1):
            lab = mu['lab']['mel'][k] if b.vocal and mu['lab']['mel'][k] >= 0 else mu['lab']['acc'][k]
            if lab >= 0:
                if lab not in seen:
                    seen[lab] = nxt % 2
                    nxt += 1
                j = seen[lab]
            th = pair[j]
            tfn = 'calm' if b.tension < form.QUIET else 'swap' if b.group.endswith("'") and th.a != th.b else 'base'
            a, bb = theme.transform(th, tfn)
            out[k] = (GID + 1000 * i + j, {0: theme.mirror(bb), 1: a}, tfn)
    return out


def mark(hits, events, blocks, pl):
    """息つぎのまとまりの打点に印（Event.relief＝テーマに沿う重みの倍率）→ 印を付けた数。人の指示がある打点には付けない・歌の高さの狙いは外す"""
    n = 0
    for h, ev in zip(hits, events):
        if _manual(h):
            continue
        i = block_at(blocks, ev.beat)
        if i in pl['rest'] and pl['of'].get(i) is not None:
            ev.relief = THEME_K
            ev.py = None
            n += 1
    return n


def _rep_share(notes_by_hand, b0, b1):
    """まとまりの中で、同じ動き（その手の振りが 2 つ前と同じ）の割合（数えられなければ None）"""
    same, tot = 0, 0
    for sw in notes_by_hand:
        q = [s for s in sw if b0 - 1e-6 <= s[0] < b1 - 1e-6]
        for k in range(2, len(q)):
            tot += 1
            same += q[k][1:] == q[k - 2][1:]
    return same / tot if tot else None


def report(pl, blocks, gen, bpm, lead_ms, cyc_text):
    """報告の節（行の並び）: 息つぎのまとまりごとの時刻・記号・段階・歌・テーマ・実際に同じ動きを続けた割合"""
    sec = lambda x: x * 60 / bpm - lead_ms / 1000
    fm = lambda s: f'{int(max(0, s)) // 60}:{max(0, s) % 60:04.1f}'
    sw = [sorted((n['beat'], n['x'], n['y'], n['d']) for n in gen if n.get('c') == c) for c in (0, 1)]
    tot = sum(b.i1 - b.i0 for b in blocks) or 1
    got = sum(blocks[i].i1 - blocks[i].i0 for i in pl['rest'])
    lines = ['', f'## 緩急（息つぎ・試し）: {len(pl["rest"])} まとまり（小節の {got / tot:.0%}）', '',
             '| 時刻 | 拍 | 記号 | 段階 | 歌 | 易しさの点 | 型（右手の形） | 同じ動きを続けた割合 |', '|---|---|---|---|---|---|---|---|']
    for i in sorted(pl['rest']):
        b = blocks[i]
        pair = pl['of'].get(i)
        r = _rep_share(sw, b.b0, b.b1)
        lines.append(f'| {fm(sec(b.b0))} | {b.b0:g}〜{b.b1:g} | {b.group} | {b.level} | {"歌" if b.vocal else "—"} | {pl["scores"][i]:+.2f} | '
                     f'{" ／ ".join(cyc_text(t.a) for t in pair) if pair else "—"} | {"—" if r is None else f"{r:.0%}"} |')
    return lines
