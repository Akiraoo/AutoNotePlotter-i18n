"""珍しい型を「決め」に（docs/ライブラリ仕様.md 1 節・4 節）。

型のデータベース（automap/library_db.export_themes）の 1回だけの並び（once＝くり返しの外の片手の 4 振り・右手の形）のうち、
頻度の区分が「珍しい」（無ければ「よくある」）物を、曲の「1回だけの場所」（途切れの前・区間の変わり目の直前・フレーズの終わり・
山の音・曲の終わり）に 1 つずつ入れる。くり返すテーマとは別に、その場所だけの振り。

- 入れ方: 1回目の流れの計算の結果（gen）を読み、場所の直前のその手の続く 4 つの振りを決めの所にする。手と振りの向き（振り下ろし・
  振り上げ）は 1回目の結果のまま＝最初の振りの向きが合う型だけを選ぶ（合わない型は使わない。向きは左右反転しても変わらない）。
  左手に使う時は左右反転。置き方は決めたノーツ（flow.Event.fix・重み KIME_W＝同じ振りの 4 より弱め）で流れの計算に渡し、
  __main__ が計算し直す。その時、決めの前後（ANCHOR_MARGIN 拍）の外の打点は 1回目の結果に弱く留める（anchor・重み ANCHOR_W）
  ＝留めないと、決めの所で手の割り振りの道が変わり、点数がほぼ同じ別の道のまま戻らず曲の 6〜8 割が変わった。
  その手の振りの間がそろっている所だけ（型は振りの間の中央値しか持たない）。
- 型の選び方: 打点の間（その手の振りの間の秒・拍）が近い・曲の個性の狙い（流れの計算の目標の割合 style.targets の斜め・
  上の段・外側の列）に近い・難しさ（まとまりの盛り上がりの段階に合う区分を先に・静かなまとまりでは「難しい」を使わない・
  ライブラリの絞り込みの上限は export_themes が先に効かせている）・もう片方の手（1回目の結果）とぶつからない・1曲の中で同じ型を使わない（残したノーツの中の型も数える）・
  腕の交差（右手の形で左端の列）と真ん中の段の中央2列（試作5 の w_center が決めより重い）は使わない・両手同時の打点ではその手の側の列だけ。
- 数は控えめに: 曲の SEC_PER 秒に 1 つまで・1 つの場所（区間の変わり目等）に 1 つ・1 つの区間に 1 つ・決めどうしは MIN_APART 拍あける。
- 入れない所: 同じ振り（意思入れ・手本も写しも）・NLM で直して残したノーツ（KEPT_MARGIN 拍の近くも）・選んだ区間の外（--only）・
  ほかの決めたノーツ。意思入れの置き方の指示（mods）がある所は、指示に逆らわない型だけ（狭く・低く・斜めを減らす…）・
  「案 k」の区間は場所の点を下げる（入りにくく）。
- 意思入れの区間の指示「決め」: 入れる（と「珍しい型まで」の区間）は choose の want＝[(拍の始まり, 終わり)]（その中の場所を先に・数の上限の外）・入れないは avoid（決めの 4 振りが重なる所には入れない）。
- 前の版から引き継ぐ（docs/アプリ仕様.md 12 節・compose --prev-intent＝前の譜面に寄せる時）: 前の版の決め（作り直しの報告の表を
  prev_kimes で読む）のうち、指示を変えていない所の物は carry で今の打点に移して同じ場所・同じ型のまま使い、choose の keep に渡す。
  新しく選ぶのは変わった所（choose の inside）だけ。選び直すと、1回目の計算がわずかに違うだけで別の場所・型になり前後が変わった。
- 報告の表の読み書き: 表の1行の形は __main__._kime_lines（parse_row・parse_report で読む。app/check.py もこれを使う）。区間だけ
  作り直した報告には、残したノーツの中の決め（作り直さなかった所＝前の版のまま）を節 CARRY_HEAD に同じ形で書く（次の作り直しが
  外の決めを知るため。app の決めの場所は前の版の報告をさかのぼって拾うので、この節は読まない）。
"""
import math
import random
import re
from dataclasses import dataclass

from . import flow

LEN = 4              # 1回だけの並びの長さ（library_db の once・型の決め方の版 1）
KIME_W = 2.5         # 決めたノーツの重み（同じ振りは flow.Style.w_fix＝4・残したノーツは 20）。テーマに沿う重み（マス 1.2〜2.0）より強く
SEC_PER = 30.0       # 曲の何秒に 1 つまで
MIN_APART = 12.0     # 決めどうしの間（拍）
NEAR = 2.0           # 区切りの何拍前までに、その手の最後の振りがあればよいか
SPAN = 8.0           # 4 振りの長さの上限（拍）
MAX_GAP = (2.0, 1.2)  # その手の振りの間の上限（拍・秒）。これより空くと流れの計算が振りの順を戻してよい（reset_gap）所に近い
MIN_GAP_SEC = 0.15   # その手の振りの間の下限（秒・compose の min_gap）
RATIO = 1.6          # 振りの間（秒）の型との比の許し
EVEN = 2.0           # その手の振りの間のそろい方（いちばん長い間 ≦ いちばん短い間の EVEN 倍）
ANCHOR_W = 0.2       # 決めの所の外を 1回目の結果に留める重み（anchor）
ANCHOR_MARGIN = 2.0  # 決めの前後の留めない所（拍）＝決めへの入り・出のつなぎを流れの計算が選び直せる
KEPT_MARGIN = 2.0    # 残したノーツから空ける拍
MOTIF_MARGIN = 1.0   # 同じ振りの打点から空ける拍
TIERS = ('珍しい', 'よくある')
HARD = ('やさしい', 'ふつう', '難しい')
SCORE = {'途切れの前': 3.0, '区間の変わり目': 2.0, '山の音': 1.5, '曲の終わり': 1.5, 'フレーズの終わり': 1.0}


@dataclass
class Place:
    beat: float            # 区切りの拍（inclusive＝False: この拍より前の振りで終える・True: この拍の振りで終える）
    kind: str
    score: float
    inclusive: bool = False
    level: int = None      # その場所のまとまりの盛り上がりの段階（無ければ None）


@dataclass
class Kime:
    hand: int              # 0＝左手・1＝右手
    idx: list              # events の番号（4 つ）
    beats: list            # その拍
    seq: list              # その手の形 [(x, y, d)]（左手は左右反転済み）
    item: dict             # once の型（seq は右手の形）
    place: Place
    sec_i: int
    placed: int = None     # 計算し直した結果で決めたとおりに置けた数
    cost: float = 0.0      # 型を選んだ時の点（小さいほど合う）
    carried: bool = False  # 前の版から引き継いだ（carry）


def mirror(seq):
    """右手の形 ↔ 左手の形（左右反転）"""
    return [(3 - x, y, flow.MIRROR_D[d]) for x, y, d in seq]


def hand_form(seq_r, hand):
    seq = [tuple(s) for s in seq_r]
    return seq if hand == flow.RIGHT else mirror(seq)


def places(hits, secs, blocks=None, mu=None, want=()):
    """曲の「1回だけの場所」→ [Place]。途切れの前（music.breaks）・区間の変わり目の直前（まとまりの記号か区間の名前が変わる所・次の
    まとまりで盛り上がる所は点を上げる）・フレーズの終わり（同じ記号の続き・区間の中のフレーズの区切り）・山の音（打点の accent）・曲の終わり"""
    out = []
    lv = (lambda i: blocks[i].level) if blocks else (lambda i: None)
    for br in (mu or {}).get('breaks') or []:
        si = next((i for i, s in enumerate(secs) if s.b0 - 1e-6 <= br['beat'] < s.b1 - 1e-6), None)
        out.append(Place(float(br['beat']), '途切れの前', SCORE['途切れの前'] - (0.5 if br.get('kind') != 'all' else 0.0),
                         level=lv(si) if si is not None else None))
    for i in range(len(secs) - 1):
        a, b = secs[i], secs[i + 1]
        if blocks:
            change = blocks[i].base != blocks[i + 1].base
            up = blocks[i + 1].level > blocks[i].level
        else:
            change, up = a.name != b.name, False
        kind = '区間の変わり目' if change else 'フレーズの終わり'
        out.append(Place(float(b.b0), kind, SCORE[kind] + (0.5 if (change and up) else 0.0), level=lv(i)))
    for i, s in enumerate(secs):   # 区間の中のフレーズの区切り（曲の流れの表ではフレーズはまとまり 1 つ＝ここには出ない）
        for p0, _ in (s.phrases or [])[1:]:
            out.append(Place(float(p0), 'フレーズの終わり', SCORE['フレーズの終わり'], level=lv(i)))
    for h in hits:
        if getattr(h, 'accent', False) and not getattr(h, 'kept', False):
            out.append(Place(float(h.beat), '山の音', SCORE['山の音'], inclusive=True, level=lv(h.sec_i) if h.sec_i < len(secs) else None))
    free = [h for h in hits if not getattr(h, 'kept', False)]
    if free:
        out.append(Place(float(free[-1].beat), '曲の終わり', SCORE['曲の終わり'], inclusive=True, level=lv(len(secs) - 1) if secs else None))
    n0 = len(out)
    bars = list((mu or {}).get('bars') or [])
    sec_lv = lambda b: lv(next((i for i, s in enumerate(secs) if s.b0 - 1e-6 <= b < s.b1 - 1e-6), len(secs) - 1)) if secs else None
    for b0, b1 in want or ():   # 意思入れの決め（入れる）・珍しい型まで: 区間の中の場所を先に。区間の終わりと、区間の中の小節の頭（の直前）にも
        for p in out[:n0]:   # 区間の頭の区切り（その直前の振りで終える＝区間の外）は上げない
            if (b0 - 1e-6 <= p.beat if p.inclusive else b0 + 1e-6 < p.beat) and p.beat <= b1 + 1e-6:
                p.score += 3.0
        out.append(Place(float(b1), '指示した区間', 3.0 + SCORE['区間の変わり目'], level=sec_lv(b1 - 1e-3)))
        inner = [b for b in bars if b0 + 2 - 1e-6 <= b < b1 - 1e-6] if bars else             [b0 + 4 * k for k in range(1, int((b1 - b0) // 4) + 1) if b0 + 4 * k < b1 - 1e-6]
        for b in inner:   # 区間の中の小節の頭（区間の終わりで型が合わない時の入れ所）
            out.append(Place(float(b), '指示した区間', 3.0 + SCORE['フレーズの終わり'], level=sec_lv(b - 1e-3)))
    return out


def _at(gen):
    at = {}
    for n in gen:
        at.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    return at


def _window(place, hand, events, swings_of, at):
    """その手の、場所の直前の続く 4 つの振り（events の番号）。無ければ None"""
    sw = swings_of[hand]
    if place.inclusive:
        k = next((j for j in range(len(sw) - 1, -1, -1) if events[sw[j]].beat <= place.beat + 1e-6), None)
        if k is None or abs(events[sw[k]].beat - place.beat) > 1e-6:
            return None
    else:
        k = next((j for j in range(len(sw) - 1, -1, -1) if events[sw[j]].beat < place.beat - 1e-6), None)
        if k is None or place.beat - events[sw[k]].beat > NEAR + 1e-6:
            return None
    if k < LEN + 1:   # その手の最初の振りから決めにしない（曲の頭の 4 振りが決めになった＝決めの前に流れが無い）
        return None
    idx = sw[k - LEN + 1:k + 1]
    bs = [events[i].beat for i in idx]
    ss = [events[i].sec for i in idx]
    if bs[-1] - bs[0] > SPAN + 1e-6:
        return None
    for j in range(LEN - 1):
        g, s = bs[j + 1] - bs[j], ss[j + 1] - ss[j]
        if g > MAX_GAP[0] + 1e-6 or s > MAX_GAP[1] + 1e-6 or s < MIN_GAP_SEC - 1e-6:
            return None
    gs = [b - a for a, b in zip(bs, bs[1:])]
    if max(gs) > EVEN * min(gs) + 1e-6:   # 振りの間がばらばら（型は振りの間の中央値しか持たない＝速い所で大きく動く型になった）
        return None
    ps = [flow.parity_of(hand, at[round(events[i].beat, 4)][hand][2]) for i in idx]
    if None in ps or any(ps[j] == ps[j + 1] for j in range(LEN - 1)):
        return None
    return idx, ps[0]


def _free(idx, hits, events, allow, kept_b, motif_b):
    """決めの所（番号の範囲の全部の打点）に、ほかの仕組みの打点が無いか"""
    i0, i1 = idx[0], idx[-1]
    b0, b1 = events[i0].beat, events[i1].beat
    if allow and not (allow[0] - 1e-9 <= b0 and b1 < allow[1] - 1e-9):
        return False
    for i in range(i0, i1 + 1):
        h, ev = hits[i], events[i]
        if getattr(h, 'kept', False) or getattr(h, 'motif', None) or (ev.fix and not getattr(ev, 'anchored', False))                 or getattr(h, 'src', '') in ('lead', 'kept'):   # 前の譜面に弱く寄せた打点（anchored）は決めにしてよい
            return False
    if any(b0 - KEPT_MARGIN - 1e-6 <= b <= b1 + KEPT_MARGIN + 1e-6 for b in kept_b):
        return False
    if any(b0 - MOTIF_MARGIN - 1e-6 <= b <= b1 + MOTIF_MARGIN + 1e-6 for b in motif_b):
        return False
    return True


def _mods_ok(seq_r, item, mods):
    """意思入れの置き方の指示（減らす向き）に逆らわない型か（右手の形で見る。左右反転しても外側・段・斜めは同じ）"""
    for m in mods:
        if (m.get('width') or 0) < 0 and any(x in (0, 3) for x, _, _ in seq_r):
            return False
        if (m.get('height') or 0) < 0 and any(y == 2 for _, y, _ in seq_r):
            return False
        if (m.get('diag') or 0) < 0 and any(d in flow.DIAG for _, _, d in seq_r):
            return False
        if (m.get('move') or 0) < 0 and (item.get('move') or 0) > 1.0:
            return False
        if (m.get('turn') or 0) < 0 and any(22 < 180 - flow.angle_between(a[2], b[2]) for a, b in zip(seq_r, seq_r[1:])):
            return False
    return True


def _style_cost(item, seq_r, targets):
    """曲の個性の狙いからの離れ。targets＝流れの計算の目標の割合（style.targets＝曲の個性の傾き＋選んだライブラリの譜面の割合の分の
    ずらし・flow.Style.targets の形）。無ければ傾き無しの中心（斜め 45%・上の段 20%・外側の列 48%）"""
    if targets:
        dt, tt, ot = targets['dir'][1], targets['row'][2], targets['col'][0] + targets['col'][3]
    else:
        dt, tt, ot = 0.45, 0.20, 0.48
    n = len(seq_r)
    top = sum(1 for _, y, _ in seq_r if y == 2) / n
    outer = sum(1 for x, _, _ in seq_r if x in (0, 3)) / n
    diag = sum(1 for _, _, d in seq_r if d in flow.DIAG) / n
    return abs(diag - dt) + abs(top - tt) + abs(outer - ot)


def _candidates(once):
    """once → 頻度の区分ごとの [(型, 右手の形)]（点ノーツ・腕の交差（右手の形で左端の列）・長さの違う物は除く）"""
    out = {t: [] for t in TIERS}
    for it in once or []:
        seq = [tuple(s) for s in it.get('seq') or []]
        if it.get('freq') not in out or len(seq) != LEN or any(d not in flow.DIR_ANGLE for _, _, d in seq):
            continue
        if any(x == 0 for x, _, _ in seq):
            continue
        if any(x in (1, 2) and y == 1 for x, y, _ in seq):   # 真ん中の段の中央2列（視界をふさぐ・流れの計算の w_center が決めより重い）
            continue
        out[it['freq']].append((it, seq))
    return out


def _clash(seq_h, hand, ss, others):
    """もう片方の手（1回目の結果）とのぶつかり: 0.35 秒以内に同じマス（hitboxInline・0.2 秒以上は軽く）・0.15 秒以内に振り抜けたマス
    （hitboxStair）・0.5 秒以内に腕の交差（流れの計算の w_inline・w_stair・w_cross_dyn と同じ決まり）。もう片方の手は決めないので
    流れの計算が動かせるが、テーマに沿う重みと競って決めの方がずれることがある"""
    c = 0.0
    for (x, y, _), t in zip(seq_h, ss):
        for t2, ox, oy, od in others:
            dt = t - t2
            if abs(dt) < 0.35 and (ox, oy) == (x, y):
                c += 1.0 if abs(dt) < 0.2 else 0.5
            if 0 < dt < 0.15 and od in flow.DIR_SPACE and (ox + flow.DIR_SPACE[od][0], oy + flow.DIR_SPACE[od][1]) == (x, y):
                c += 1.0
            if 0 <= dt < 0.5 and ((hand == flow.LEFT and x > ox) or (hand == flow.RIGHT and x < ox)):
                c += 0.5
    return c


def _hard_target(level):
    """まとまりの盛り上がりの段階 → 狙う難しさの区分の番号（静か 0〜1＝やさしい・2＝ふつう・3＝難しい。段階が無ければふつう）"""
    return 1 if level is None else 0 if level <= 1 else 1 if level == 2 else 2


def _pick(cands, used, p0, dbl_k, mods, level, our_sec, our_gap, targets, rng, hand=flow.RIGHT, ss=None, others=()):
    """その所に合う型 → (点, 型, 右手の形) か None。頻度の区分は珍しい → よくある の順（珍しいで合う物があればそれだけ）。
    level＝その場所のまとまりの盛り上がりの段階（0 なら「難しい」は使わない・段階に合う難しさを先に）"""
    ht = _hard_target(level)
    for tier in TIERS:
        best = None
        for it, seq in cands[tier]:
            key = tuple(seq)
            if key in used or flow.parity_of(flow.RIGHT, seq[0][2]) != p0:
                continue
            if any(seq[k][0] < 2 for k in dbl_k):   # 両手同時の打点ではその手の側の列だけ（もう片方の手が並べる所を残す）
                continue
            hc = (it.get('hard') or {}).get('class')
            if level is not None and level <= 0 and hc == HARD[2]:
                continue
            if mods and not _mods_ok(seq, it, mods):
                continue
            sec, gap = it.get('sec') or 0, it.get('gap') or 0
            if sec <= 0 or gap <= 0:
                continue
            r = math.log(our_sec / sec)
            if abs(r) > math.log(RATIO):
                continue
            c = 2.0 * abs(r) + 0.5 * abs(math.log(our_gap / gap)) + _style_cost(it, seq, targets)
            c += 0.3 * abs((HARD.index(hc) if hc in HARD else 1) - ht) - 0.05 * math.log(max(1, it.get('maps') or 1))
            if others and ss:
                c += _clash(hand_form(seq, hand), hand, ss, others)
            c += 0.15 * rng.random()
            if best is None or c < best[0]:
                best = (c, it, seq)
        if best:
            return best
    return None


def _kept_shapes(hits):
    """残したノーツ（選んだ区間の外・NLM で直した所）の中の、片手の続く 4 振りの形（右手の形）＝もう使った型として数える
    （--only で区間だけ作り直す時に、外にある決めと同じ型をもう一度使わない）"""
    by = {0: [], 1: []}
    for h in hits:
        if getattr(h, 'kept', False):
            for c, v in (getattr(h, 'fix', None) or {}).items():
                if c in by:
                    by[c].append(tuple(v))
    out = set()
    for c, seq in by.items():
        for j in range(len(seq) - LEN + 1):
            w = seq[j:j + LEN]
            out.add(tuple(w) if c == flow.RIGHT else tuple(mirror(w)))
    return out


def choose(lib, hits, events, gen, secs, blocks=None, mu=None, targets=None, seed=1, allow=None, vranges=(), want=(), limit=None, avoid=(),
           keep=(), inside=None):
    """決めを選ぶ → [Kime]（拍の順）。lib に once が無ければ（1回だけの並びの無い書き出し）空。hits と events は同じ並び（compose の打点と Event）。
    gen＝1回目の流れの計算の結果（手と振りの向きを読む）。allow＝(拍の始まり, 終わり)（選んだ区間だけ作り直す時）。
    vranges＝意思入れ・--variant の「案 k」の区間 [(b0, b1, k, …)]（b0 が None＝曲の全部）。want＝決めを入れる区間（意思入れの決め 1・珍しい型まで）。avoid＝決めを入れない区間（決め −1。want より勝つ）。
    keep＝もう決まった決め（carry＝前の版から引き継いだ物。答えにそのまま入り、数の上限・区間に1つ・間・同じ型を使わない、に数える）。
    inside＝新しく選んでよい所 [(拍の始まり, 終わり)]（決めの 4 振りが収まる所だけ。None＝どこでも・[]＝新しく選ばない）"""
    keep = sorted(keep or (), key=lambda k: k.beats[0])
    once = (lib or {}).get('once')
    if not once or not events or not gen or len(hits) != len(events):
        return list(keep)
    cands = _candidates(once)
    if not any(cands.values()) or (inside is not None and not inside):
        return list(keep)
    at = _at(gen)
    swings_of = {0: [], 1: []}
    for i, ev in enumerate(events):
        for c in at.get(round(ev.beat, 4), {}):
            swings_of[c].append(i)
    kept_b = [h.beat for h in hits if getattr(h, 'kept', False)]
    motif_b = [h.beat for h in hits if getattr(h, 'motif', None)]
    in_var = lambda b0, b1: any((v[0] is None) or (v[0] - 1e-6 <= b1 and b0 <= v[1] + 1e-6) for v in vranges or ())
    in_want = lambda b0, b1: next((j for j, (w0, w1) in enumerate(want or ()) if w0 - 1e-6 <= b0 and b1 <= w1 + 1e-6), None)   # 入れる区間の番号
    free_ev = [ev for h, ev in zip(hits, events) if not getattr(h, 'kept', False)]
    t0 = free_ev[0].sec if free_ev else 0.0
    dur = free_ev[-1].sec - t0 if len(free_ev) > 1 else 0.0
    if limit is None:
        limit = max(1, int(dur / SEC_PER))
    slot = lambda t: min(limit - 1, int((t - t0) / (dur / limit))) if dur > 0 else 0   # 曲を limit 個に分けた所ごとに 1 つ（前半に固まらない）
    sec_at = {round(ev.beat, 4): ev.sec for ev in events}
    other_notes = {c: sorted((sec_at.get(round(n['beat'], 4), 0.0), n['x'], n['y'], n['d']) for n in gen if n['c'] == c) for c in (0, 1)}
    rng = random.Random(seed)
    sec_of = lambda i: getattr(hits[i], 'sec_i', 0)
    cand = []
    for p in places(hits, secs, blocks, mu, want):
        for hand in (flow.LEFT, flow.RIGHT):
            w = _window(p, hand, events, swings_of, at)
            if not w:
                continue
            idx, p0 = w
            if not _free(idx, hits, events, allow, kept_b, motif_b):
                continue
            bs = [events[i].beat for i in idx]
            if any(a0 - 1e-6 <= bs[-1] and bs[0] < a1 - 1e-6 for a0, a1 in avoid or ()):
                continue
            if inside is not None and not any(a0 - 1e-6 <= bs[0] and bs[-1] <= a1 + 1e-6 for a0, a1 in inside):
                continue
            ss = [events[i].sec for i in idx]
            gaps = sorted(b - a for a, b in zip(bs, bs[1:]))
            secs_g = sorted(b - a for a, b in zip(ss, ss[1:]))
            mods = [getattr(hits[i], 'mods', None) for i in range(idx[0], idx[-1] + 1) if getattr(hits[i], 'mods', None)]
            dbl_k = [k for k, i in enumerate(idx) if events[i].hands == 2]
            score = p.score * (0.5 if in_var(bs[0], bs[-1]) else 1.0)
            others = [o for o in other_notes[1 - hand] if ss[0] - 0.5 <= o[0] <= ss[-1] + 0.5]
            cand.append((score, p, hand, idx, p0, gaps[len(gaps) // 2], secs_g[len(secs_g) // 2], mods, dbl_k, in_want(bs[0], bs[-1]),
                         ss, others))
    by_place = {}
    for c in cand:
        by_place.setdefault((c[1].beat, c[1].kind), []).append(c)
    order = sorted(by_place.values(), key=lambda cs: (-max(c[0] for c in cs), cs[0][1].beat))   # 点の高い場所から・同じ点は前から
    out, used, used_sec, used_slot, used_want = list(keep), _kept_shapes(hits), set(), set(), set()
    n_free = 0
    for k in keep:   # もう決まった決め: 同じ型・同じ区間・同じ所・入れる区間の数に数える
        used.add(tuple(hand_form(k.seq, k.hand)))
        used_sec.add(k.sec_i)
        w = in_want(k.beats[0], k.beats[-1])
        if w is None or w in used_want:
            n_free += 1
            used_slot.add(slot(events[k.idx[-1]].sec))
        else:
            used_want.add(w)
    for cs in order:   # 1 つの場所に 1 つ: 両方の手で合う型を探し、点の良い方
        best = None
        for score, p, hand, idx, p0, our_gap, our_sec, mods, dbl_k, wanted, ss, others in cs:
            si = sec_of(idx[-1])
            sl = slot(ss[-1])
            b0, b1 = events[idx[0]].beat, events[idx[-1]].beat
            if wanted in used_want:   # 入れる区間には 1 つ（2 つ目からはふつうの決めと同じ数の上限）
                wanted = None
            if wanted is None and (si in used_sec or sl in used_slot or n_free >= limit):
                continue
            if any(b0 - MIN_APART < k.beats[-1] and k.beats[0] < b1 + MIN_APART for k in out):
                continue
            if any(set(range(idx[0], idx[-1] + 1)) & set(range(k.idx[0], k.idx[-1] + 1)) for k in out):
                continue
            got = _pick(cands, used, p0, dbl_k, mods, p.level, our_sec, our_gap, targets, rng, hand, ss, others)
            if got and (best is None or got[0] < best[0][0]):
                best = (got, p, hand, idx, si, sl, wanted)
        if not best:
            continue
        (c, it, seq_r), p, hand, idx, si, sl, wanted = best
        used.add(tuple(seq_r))
        used_sec.add(si)
        if wanted is None:
            n_free += 1
            used_slot.add(sl)
        else:
            used_want.add(wanted)
        out.append(Kime(hand, list(idx), [events[i].beat for i in idx], hand_form(seq_r, hand), it, p, si, cost=round(c, 3)))
    out.sort(key=lambda k: k.beats[0])
    return out


def apply(kimes, events, weight=None):
    """決めを流れの計算へ（その手だけの決めたノーツ。両手同時の打点のもう片方の手は決めない）。重みは KIME_W"""
    weight = weight or KIME_W
    for k in kimes:
        for i, cell in zip(k.idx, k.seq):
            events[i].fix = {k.hand: tuple(cell)}
            events[i].fix_w = weight
            events[i].anchored = False


def release(kimes, events, margin=None):
    """前の譜面に弱く寄せた打点（compose の --prev-intent・Event.anchored）のうち、決めの所（前後 margin 拍を含む）の物を寄せない
    ＝決めへの入り・出のつなぎを流れの計算が選び直せる（前の譜面に同じ決めが無い所だけ呼ぶ）→ 外した数"""
    margin = ANCHOR_MARGIN if margin is None else margin
    spans = [(k.beats[0] - margin, k.beats[-1] + margin) for k in kimes]
    n = 0
    for ev in events:
        if getattr(ev, 'anchored', False) and any(a - 1e-6 <= ev.beat <= b + 1e-6 for a, b in spans):
            ev.fix, ev.fix_w, ev.anchored = None, None, False
            n += 1
    return n


def anchor(kimes, events, gen, hits=None, weight=None, margin=None):
    """決めを入れて計算し直す時、決めの所（前後 margin 拍を含む）の外の打点を 1回目の結果（gen）の置き方に弱く留める（決めたノーツ・
    重み ANCHOR_W）→ 留めた打点の数。留めないと、決めの所で手の割り振りの道が変わった後、点数がほぼ同じ別の道のまま戻らず、
    決めから遠い所まで譜面が変わった（意思入れの無い曲で曲の 6〜8 割）。ほかの決めたノーツ（同じ振り・残したノーツ）がある打点と、
    同じ振り・残したノーツの打点（hits）は触らない（同じ振りの手本どおりの数え方が Event.fix を見る）。前の譜面に寄せた打点
    （Event.anchored）もそのまま（前の譜面に寄せる方が先）"""
    weight = weight or ANCHOR_W
    margin = ANCHOR_MARGIN if margin is None else margin
    at = _at(gen)
    spans = [(k.beats[0] - margin, k.beats[-1] + margin) for k in kimes]
    n = 0
    for i, ev in enumerate(events):
        h = hits[i] if hits is not None and i < len(hits) else None
        if ev.fix or (h is not None and (getattr(h, 'motif', None) or getattr(h, 'kept', False))):
            continue
        if any(a - 1e-6 <= ev.beat <= b + 1e-6 for a, b in spans):
            continue
        f = at.get(round(ev.beat, 4))
        if f:
            ev.fix, ev.fix_w = dict(f), weight
            n += 1
    return n


def check(kimes, gen):
    """計算し直した結果で、決めたとおりに置けた数を kimes に書く → (置けた数, 狙った数)"""
    at = _at(gen)
    ok = tot = 0
    for k in kimes:
        k.placed = sum(1 for b, cell in zip(k.beats, k.seq) if at.get(round(b, 4), {}).get(k.hand) == tuple(cell))
        ok += k.placed
        tot += len(k.seq)
    return ok, tot


def carry(prev, lib, hits, events, gen, at, free, allow=None, avoid=()):
    """前の版の決め（prev_kimes の行）のうち、指示を変えていない所の物を今の打点に移す → ([Kime]（carried）, [(行, 理由)]（使わな
    かった物）)。at＝前の譜面の置き方 {拍: {手: (x, y, d)}}（compose の前の譜面に寄せる相手）・free＝指示が変わった所 [(b0, b1)]・
    gen＝1回目の流れの計算の結果。使う条件: 決めの 4 振りが変わった所にかからない・選んだ区間の中（allow）・入れない区間（avoid）に
    かからない・前の譜面のその手の振りが拍 b0〜b1 にちょうど 4 つで、置けた数以上が型どおり（NLM で直した等は使わない）・今の打点に
    同じ拍があり、間にほかの決めたノーツ（残したノーツ・同じ振り・前の譜面に寄せたもの以外）が無い・1回目の計算でもその手が同じ
    拍で振り、振りの向き（振り下ろし・振り上げ）が型と同じ"""
    by_seq = {tuple(tuple(s) for s in it.get('seq') or []): it for it in (lib or {}).get('once') or []}
    ev_at = {round(ev.beat, 4): i for i, ev in enumerate(events)}
    g_at = _at(gen)
    out, drop = [], []
    for r in prev or ():
        hand, b0, b1 = r['hand'], r['b0'], r['b1']
        seq = [tuple(s) for s in r['seq']]
        why, idx = None, None
        if any(x - 1e-6 < b1 and b0 < y - 1e-6 for x, y in free or ()):
            why = '指示が変わった所'
        elif allow and not (allow[0] - 1e-9 <= b0 and b1 < allow[1] - 1e-9):
            why = '選んだ区間の外'
        elif any(a0 - 1e-6 <= b1 and b0 < a1 - 1e-6 for a0, a1 in avoid or ()):
            why = '入れない区間'
        else:
            bs = sorted(b for b, f in at.items() if hand in f and b0 - 1e-3 <= b <= b1 + 1e-3)
            ok = sum(1 for b, c in zip(bs, seq) if tuple(at[b][hand]) == c)
            idx = [ev_at.get(round(b, 4)) for b in bs]
            gs = sorted(b for b, f in g_at.items() if hand in f and b0 - 1e-3 <= b <= b1 + 1e-3)
            if len(bs) != LEN or len(seq) != LEN or ok < (r['placed'] if r.get('placed') is not None else LEN):
                why = '前の譜面で型どおりでない'
            elif None in idx:
                why = '打点が無い'
            elif any(getattr(hits[i], 'kept', False) or getattr(hits[i], 'motif', None)
                     or (events[i].fix and not getattr(events[i], 'anchored', False)) for i in range(idx[0], idx[-1] + 1)):
                why = 'ほかの決めたノーツ'
            elif any(idx[0] <= o.idx[-1] and o.idx[0] <= idx[-1] for o in out):
                why = 'ほかの決めと重なる'
            elif len(gs) != LEN or any(abs(a - b) > 1e-3 for a, b in zip(gs, bs)) or any(
                    flow.parity_of(hand, g_at[b][hand][2]) != flow.parity_of(hand, c[2]) for b, c in zip(gs, seq)):
                why = '手か振りの向きが合わない'
        if why:
            drop.append((r, why))
            continue
        seq_r = hand_form(seq, hand)
        it = by_seq.get(tuple(seq_r)) or {'seq': [list(s) for s in seq_r], 'maps': r.get('maps'), 'freq': r.get('freq'),
                                          'hard': {'class': r.get('hard')}}
        pl = Place(r['place_beat'] if r.get('place_beat') is not None else b1, r.get('place') or '前の版', 0.0)
        out.append(Kime(hand, idx, [events[i].beat for i in idx], seq, it, pl, getattr(hits[idx[-1]], 'sec_i', 0), carried=True))
    return out, drop


def present(r, notes):
    """前の版の決め（prev_kimes の行）が譜面（{beat, x, y, c, d} の並び）にまだあるか: その手の拍 b0〜b1 のノーツが型の数だけあり、
    型どおりの数が置けた数以上（app/check.py の still_there と同じ決まり）"""
    got = sorted((n['beat'], n['x'], n['y'], n['d']) for n in notes if n['c'] == r['hand'] and r['b0'] - 1e-3 <= n['beat'] <= r['b1'] + 1e-3)
    seq = r['seq']
    if not seq or len(got) != len(seq):
        return False
    hit = sum(1 for (_, x, y, d), q in zip(got, seq) if [x, y, d] == list(q))
    return hit >= (r['placed'] if r.get('placed') is not None else len(seq))


# ---- 作り直しの報告の決めの表（書くのは __main__._kime_lines・_kime_row） ----

REPORT_HEAD = '## 決め（珍しい型）'
CARRY_HEAD = '## 決め（残したノーツの中・前の版のまま）'   # 区間だけ作り直した報告の、作り直さなかった所の決め
ARROW = {'↑': 0, '↓': 1, '←': 2, '→': 3, '↖': 4, '↗': 5, '↙': 6, '↘': 7, '・': 8}   # __main__.AR の逆
_NUM = r'-?\d+(?:\.\d+)?'


def parse_seq(text):
    """「↑12 ↘20 …」→ [[x, y, 向き]]（読めない粒は飛ばす）"""
    out = []
    for tok in text.split():
        m = re.fullmatch(r'(\S)(\d)(\d)', tok)
        if m and m.group(1) in ARROW:
            out.append([int(m.group(2)), int(m.group(3)), ARROW[m.group(1)]])
    return out


def parse_row(cells):
    """表の1行（8 つの欄）→ 決めの1つ（拍が読めなければ None）"""
    if len(cells) < 8:
        return None
    m = re.fullmatch(rf'({_NUM})〜({_NUM})', cells[0])
    if not m:
        return None
    r = {'b0': float(m.group(1)), 'b1': float(m.group(2)), 't': None, 'sec': cells[2], 'place': cells[3], 'place_beat': None,
         'hand': 1 if cells[4].startswith('右') else 0, 'seq': parse_seq(cells[5]), 'seq_text': cells[5],
         'maps': None, 'freq': '', 'hard': '', 'placed': None, 'total': None}
    try:
        r['t'] = float(cells[1])
    except ValueError:
        pass
    m = re.fullmatch(rf'(.*?)（拍 ({_NUM})）', cells[3])
    if m:
        r['place'], r['place_beat'] = m.group(1), float(m.group(2))
    m = re.fullmatch(r'(\d+|None)（(.*?)・(.*?)）', cells[6])
    if m:
        r['maps'] = int(m.group(1)) if m.group(1).isdigit() else None
        r['freq'], r['hard'] = m.group(2), m.group(3)
    m = re.fullmatch(r'(\d+|None) / (\d+)', cells[7])
    if m:
        r['placed'] = int(m.group(1)) if m.group(1).isdigit() else None
        r['total'] = int(m.group(2))
    return r


def parse_report(md, head=REPORT_HEAD):
    """報告（.report.md の中身）→ (state, 決めの一覧, 箇条書き)。state＝ok・none（節が無い）。head＝読む節の見出し"""
    lines = (md or '').splitlines()
    try:
        i = next(k for k, s in enumerate(lines) if s.strip() == head)
    except StopIteration:
        return 'none', [], []
    kimes, notes = [], []
    for s in lines[i + 1:]:
        s = s.strip()
        if s.startswith('## '):
            break
        if s.startswith('- '):
            notes.append(s[2:])
        elif s.startswith('|') and not s.startswith('|---'):
            r = parse_row([c.strip() for c in s.strip('|').split('|')])
            if r:
                kimes.append(r)
    return 'ok', kimes, notes


def partial_of(md):
    """報告が一部だけ作り直した物なら、作り直した拍の範囲（区間だけ＝(a, b)・「ここから」＝(拍, 無限)）。全部なら None"""
    m = re.search(rf'選んだ区間（拍 ({_NUM})〜({_NUM})）だけ作り直した', md or '')
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(rf'「ここから」（拍 ({_NUM})）より前は結果のファイルのまま', md or '')
    if m:
        return float(m.group(1)), float('inf')
    return None


def prev_kimes(md):
    """前の版の報告 → 前の版の譜面にある決め [parse_row の行]（表＝作り直した所の決め＋節 CARRY_HEAD＝残したノーツの中の決め）か
    None（分からない: 決めの節が無い・決めを切った（--no-kime）・区間だけ作り直した報告なのに CARRY_HEAD の節が無い＝前の形の
    報告で外の決めが載っていない）"""
    st, rows, notes = parse_report(md)
    if st != 'ok' or any(s.startswith('切った') for s in notes):
        return None
    st2, rows2, _ = parse_report(md, CARRY_HEAD)
    if st2 != 'ok' and partial_of(md) is not None:
        return None
    out, seen = [], set()
    for r in rows + rows2:
        key = (r['hand'], round(r['b0'], 3), round(r['b1'], 3))
        if key not in seen and len(r['seq']) == LEN:
            seen.add(key)
            out.append(r)
    return out
