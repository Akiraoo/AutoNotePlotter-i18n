"""テーマ（検討の層の ③④）: 曲の流れの表のまとまり・小節ごとに「動きの型」を割り当て、変え方を付けて狙いの位置にする。

テーマ＝左右の手それぞれの振りの型（BeatLeader のランク譜面でくり返し使われた型＝型のデータベースの書き出し・library_use.export）。
型は右手の形の (x, y, 向き) の並びで、振り下ろし側と振り上げ側が交互＝そのまま続けても振りの交互が崩れない。
左手は左右反転して使う。

選び方は style.pick（曲の個性で傾けた狙い・性格ごとに主・副のテーマ）・割り当ては form.guides・form.mix_guides。
変え方: そのまま（base）・左右の入れ替え（swap）・抑える（calm）。どれも軽くする（tf_ease）を通す。
ここで決めるのは「狙いの位置」まで。実際の置き方は flow.generate が、狙いからのずれと体の負担の減点の合計で決める
（速すぎて届かない・腕が交差する、などの時は狙いから外れる）。
区間の名前で決める試作1〜3 の展開（フレーズごとの変え方・盛り上げ）は除いた（docs/除いた物.md）。
"""
import math
from dataclasses import dataclass, field

MIRROR_D = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}
DOWNISH, UPISH = {1, 6, 7}, {0, 4, 5}


def mirror(cyc):
    return [(3 - x, y, MIRROR_D[d]) for x, y, d in cyc]


def is_fore(d):
    return d in DOWNISH or d == 2   # 右手の形: 左へ＝体の方＝振り下ろし側


# ---- 性格ごとの狙い（form.character の性格・style.want が傾ける） ----

# 移動・段・斜め・幅・振りの数
WANT = {
    'calm': {'move': 2.0, 'row': 0.6, 'diag': 0.25, 'width': 1, 'P': 4},
    'build': {'move': 2.5, 'row': 0.9, 'diag': 0.5, 'width': 1, 'P': 4},
    'big': {'move': 2.75, 'row': 1.1, 'diag': 0.6, 'width': 2, 'P': 4},
    'drive': {'move': 2.5, 'row': 1.0, 'diag': 0.5, 'width': 2, 'P': 4},
    'simple': {'move': 2.0, 'row': 0.5, 'diag': 0.0, 'width': 1, 'P': 2},
}


@dataclass
class Theme:
    a: list      # 右手の形の型（主にこの型を右手に）
    b: list      # もう片方（左手へは反転して使う）
    maps: int    # 何曲で使われたか
    src: str     # 'pair'（両手で一緒に使われた）／'sym'（片手の型を左右対称に）
    # その帯らしさ（★の帯を変えた型の束の時だけ・library_use.band_lift。それ以外は None）。同じ型かどうかの比べには入れない
    lift: float = field(default=None, compare=False)

    def key(self):
        return (tuple(map(tuple, self.a)), tuple(map(tuple, self.b)))


def shape(cyc):
    P = len(cyc)
    mv = [abs(cyc[k][0] - cyc[(k + 1) % P][0]) + abs(cyc[k][1] - cyc[(k + 1) % P][1]) for k in range(P)]
    return {'move': sum(mv) / P, 'row': sum(c[1] for c in cyc) / P, 'diag': sum(1 for c in cyc if c[2] in (4, 5, 6, 7)) / P,
            'width': max(c[0] for c in cyc) - min(c[0] for c in cyc), 'cells': len({(c[0], c[1]) for c in cyc}), 'P': P,
            'outer': sum(1 for c in cyc if c[0] in (0, 3)) / P, 'horiz': sum(1 for c in cyc if c[2] in (2, 3)) / P}


HAND_MIN, PAIR_MIN, BASE_SONGS = 8, 3, 899   # 手元の 899 曲（前の cache/themes.json）で決めた、テーマに使う型の最小の曲の数
RARE_MIN = (2, 2)   # 珍しい型まで広げる時（少ない曲にしか出ない型も）。型の書き出し（library_db・library_themes.py）は 2 曲以上の型だけ


def thresholds(d, freq=None):
    """テーマに使う型の最小の曲の数 (片手の型, 両手の組)。
    - 型のデータベースの書き出し（library の項目がある）は、曲の数に合わせて手元の 899 曲の時と同じ割合（8/899・3/899。片手 3・両手 2 より
      下げない）。★〜8 のランク譜面（512 曲）は 5・2＝使える型が 129 → 206。library の項目が無い型（テストの作り物）は 8・3。
    - 型の頻度の上限が「珍しい」（freq か、書き出しの絞り込みの freq）なら RARE_MIN（2・2）＝少ない曲にしか出ない型もテーマの候補に入れる
      （曲全体の設定「珍しいまで」・区間ごとに広げる時）"""
    lib = d.get('library')
    if freq is None and isinstance(lib, dict):
        freq = (lib.get('filters') or {}).get('freq')
    if freq == '珍しい':
        return RARE_MIN
    if not isinstance(lib, dict) or not d.get('songs'):
        return HAND_MIN, PAIR_MIN
    r = d['songs'] / BASE_SONGS
    return max(3, round(HAND_MIN * r)), max(2, round(PAIR_MIN * r))


def load_themes(src, hand_min=None, pair_min=None, freq=None):
    """型 → Theme の並び。src＝型のデータベースの書き出し（library_use.export・library_db.export_themes の dict。前の cache/themes.json の
    場所を読む道は除いた）。hand_min・pair_min＝テーマに使う型の最小の曲の数（片手の型・両手の組。区間ごとに広げた型の束を別に作る時に渡す）。
    渡さなければ thresholds(d, freq)"""
    d = src
    hm, pm = thresholds(d, freq)
    hand_min = hm if hand_min is None else hand_min
    pair_min = pm if pair_min is None else pair_min
    out = []
    for q in d['pairs']:
        if q['maps'] >= pair_min:
            out.append(Theme([tuple(s) for s in q['a']], [tuple(s) for s in q['b']], q['maps'], 'pair', q.get('lift')))
    for h in d['hands']:
        if len(h['cycle']) >= 4 and h['maps'] >= hand_min:
            c = [tuple(s) for s in h['cycle']]
            out.append(Theme(c, c, h['maps'], 'sym', h.get('lift')))
    seen, uniq = set(), []
    for t in out:
        if t.key() not in seen:
            seen.add(t.key())
            uniq.append(t)
    return uniq


LIFT_CAP = 1.0   # その帯らしさの点（log）の上限・下限（少ない曲にしか出ない型の比が大きく振れても効きすぎないように）


def lift_score(lift):
    """その帯らしさ（比）→ 点（log・±LIFT_CAP で止める）。比が無い（None・0 以下）は 0"""
    if not lift or lift <= 0:
        return 0.0
    return max(-LIFT_CAP, min(LIFT_CAP, math.log(lift)))


W_SPREAD = 1.5   # 型の spread（両手を同時に外へ）が狙い（want['wide']）より多い分の減点の重み（仮の値・2026-11-03）。少ない分はごほうびにしない
_SPREAD = {}


def wide_pairs(left, right):
    """両手が交互に振る（右・左・右…）と見て、振りごとにもう片方の手の直前の振りと組にした時の「左手が列 0・右手が列 3」の組の数
    (右から始めた時, 左から始めた時, 組の数)。left・right は実際の列の座標の型（guides の {0: mirror(l), 1: r}）。その手の i 回目と相手の
    i 回目が同じ向き（型はどちらも振り下ろし側から始まる）。右から: 右i・左i と 右i+1・左i／左から: 右i・左i と 右i・左i+1。
    長さの違う型は最小公倍数の長さで回す（組の数＝その長さの 2 倍）"""
    lw, rw = [x == 0 for x, _, _ in left], [x == 3 for x, _, _ in right]
    pl, pr = len(lw), len(rw)
    if not pl or not pr:
        return 0, 0, 0
    n = pl * pr // math.gcd(pl, pr)
    same = sum(rw[i % pr] and lw[i % pl] for i in range(n))
    r_first = same + sum(rw[(i + 1) % pr] and lw[i % pl] for i in range(n))
    l_first = same + sum(rw[i % pr] and lw[(i + 1) % pl] for i in range(n))
    return r_first, l_first, 2 * n


def spread(theme, ease=True):
    """型を両手で振った時に「両手を同時に外へ」（右手が列 3・左手が列 0）になる組の割合の見込み（0〜1）。
    型は a・b とも右手の形で持つ（tools/library_themes.py の to_r が左手を左右反転・sym は a＝b）。guides・form.bar_guides・mix_guides は
    右手に a、左手に mirror(b) を渡す → 左手が列 0 ＝ b の列 3。ease＝実際に渡す形（transform の 'base'＝tf_ease。2列目の上の段の振り上げを
    外の列へ移すので外が増える）で数える。両手は交互に振る（右・左・右…）と見て、振りごとにもう片方の手の直前の振りと組にし、右から
    始める・左から始めるの両方を平均する（wide_pairs）。
    左右対称の型の左手の始まりを、組が一番少なくなるようにずらす案（phase）も試したが、左手だけ外の列が多く残り（自分の外が左 53%・
    右 42%）、両手を同時に外への減り方も 0.5 ポイントほどだったので捨てた（2026-11-03・docs/方針.md 6.21）"""
    k = (theme.key(), ease)
    if k in _SPREAD:
        return _SPREAD[k]
    A, B = transform(theme, 'base') if ease else (list(theme.a), list(theme.b))
    r, l, n = wide_pairs(mirror(B), list(A))
    v = (r + l) / (2 * n) if n else 0.0
    _SPREAD[k] = v
    return v


def fit(theme, want, pop=0.35):
    """性格への合い方（小さいほど良い）。pop＝多くの曲で使われた型ほど良くする重み（大きいとどの曲も同じ型に寄る・6.18）。
    want に outer（外側の列の割合）・horiz（横向きの割合）があればそれも見る（曲の個性・style.want）。
    want に lift（重み）があれば、その帯らしさ（theme.lift・★の帯を変えた型の束の時だけ）の点をその重みで足す（大きいほど良くする）。
    want に wide（両手を同時に外への割合の狙い・style.want）があれば、型の spread が狙いより多い分を W_SPREAD の重みで減点に足す（少ない分は
    ごほうびにしない。2026-11-03・左右対称の型は右手が外へ出ると左手も同時に外へ出て、ハロで両手を同時に外へが 35%＝ランク譜面の上から 2%）"""
    sa, sb = shape(theme.a), shape(theme.b)
    c = 0.0
    for s in (sa, sb):
        c += abs(s['move'] - want['move']) * 1.0 + abs(s['row'] - want['row']) * 1.5 + abs(s['diag'] - want['diag']) * want.get('w_diag', 1.0)
        c += abs(min(s['width'], 3 if 'outer' in want else 2) - want['width']) * 0.4
        c += 0.0 if s['P'] >= want['P'] else 1.0
        c += 0.0 if s['cells'] >= 2 else 1.0
        if 'outer' in want:
            c += abs(s['outer'] - want['outer']) * 1.5
            # 真ん中の2列の中段（視界をふさぐ＝NLM の譜面チェックの visionBlock）を含む型は避ける（曲D で内側の列を狙ったら出た）
            c += 1.5 * sum(1 for x, y, _ in (theme.a if s is sa else theme.b) if y == 1 and x in (1, 2)) / s['P']
        if 'horiz' in want:
            c += abs(s['horiz'] - want['horiz']) * 1.0
    if want.get('lift') and theme.lift:   # ★の帯を変えた時だけ（ほかは前と同じ式）
        v = c / 2 - pop * math.log(theme.maps) - want['lift'] * lift_score(theme.lift)
    else:
        v = c / 2 - pop * math.log(theme.maps)
    if 'wide' in want:   # 狙いに wide がある時だけ（無ければ前と同じ値）
        v += W_SPREAD * max(0.0, spread(theme) - want['wide'])
        if 'outer' in want:   # 渡す形（tf_ease の後）の外側の列が狙いより多い分（上の outer の合い方は元の形で、重みも小さかった）
            v += W_OUTER * max(0.0, eased_outer(theme) - want['outer'])
    return v


W_OUTER = 6.0   # 渡す形の外側の列の割合が狙い（want['outer']）より多い分の減点の重み（2026-11-03・ハロで選ばれた型が 49%・狙い 44%。
                # 4 曲で 0・3・6・8 を比べて 6＝両手を同時に外へがランク譜面のふつうに一番そろった・docs/方針.md 6.21）
_EOUTER = {}


def eased_outer(theme):
    """実際に渡す形（transform の 'base'＝tf_ease の後）の外側の列（右手の形の列 0・3）の割合（a・b の平均）。tf_ease は 2 列目の上の段の
    振り上げを外の列の中段（↗31）へ移すので、元の形より外が多い"""
    k = theme.key()
    if k not in _EOUTER:
        A, B = transform(theme, 'base')
        _EOUTER[k] = (shape(A)['outer'] + shape(B)['outer']) / 2
    return _EOUTER[k]


PICK_JITTER = 0.3   # テーマを選ぶ時の揺らぎの大きさ（種で決まる・試作5 は曲ごとの種＝style.habit_seed）


def pick_themes(themes, sections, want_of, seed=1, pop=0.35):
    """区間の名前ごとにテーマを1つ（同じ名前は同じテーマ・違う名前には違うテーマ）→ {名前: Theme}。want_of＝区間 → 狙い（style.want）"""
    import random
    rng = random.Random(seed)
    chosen, used = {}, []
    for sec in sections:
        if sec.name in chosen:
            continue
        want = want_of(sec)
        scored = []
        for t in themes:
            c = fit(t, want, pop)
            for u in used:   # 使ったテーマと似ている物は避ける（違う区間は違う動き）
                if t.key() == u.key():
                    c += 100
                c += 0.8 * _similar(t, u)
            scored.append((c + rng.random() * PICK_JITTER, t))
        scored.sort(key=lambda x: x[0])
        chosen[sec.name] = scored[0][1]
        used.append(scored[0][1])
    return chosen


def _similar(t, u):
    """2つのテーマの近さ 0〜1（同じマス・向きの振りの割合）"""
    a = set(t.a) | set(t.b)
    b = set(u.a) | set(u.b)
    return len(a & b) / max(1, len(a | b))


# ---- 変え方 ----

def tf_diag(cyc):
    """上下の振りを斜めに（右手の形: 振り下ろしは内側へ・振り上げは外側へ＝手首の自然な向き）"""
    return [(x, y, 6 if d == 1 else 5 if d == 0 else d) for x, y, d in cyc]


def tf_calm(cyc):
    """抑える: 型の最初の振り下ろしと振り上げの2つだけにし、振り上げは中段まで（小さく・同じ所を往復する）。
    真ん中の2列の中段は視界をふさぐ（譜面チェックの visionBlock）ので、そこは下の段で往復する"""
    f = next((c for c in cyc if is_fore(c[2])), cyc[0])
    b = next((c for c in cyc if not is_fore(c[2])), cyc[1])
    return [f, (b[0], 0 if b[0] in (1, 2) else min(1, b[1]), b[2])]


def tf_ease(cyc):
    """軽くする: 振り上げで上の段へ行く所を1つおきに下げる（上の段へ上げるのは半分に）。2振りの型は4振りに延ばして2回に1回下げる。
    下げ方（右手の形）: 2列目は外の列の中段へ斜め上（↗31）・外の列は中段・内側の列は下の段（真ん中の2列の中段は視界をふさぐので使わない）。
    手元の譜面の Expert+ は振り上げの 49% が上の段・35% が中段・13% が下の段（作った譜面は上の段が 77%・サビは 100% で、腕が上がりっぱなしだった）"""
    ups = [k for k, c in enumerate(cyc) if not is_fore(c[2]) and c[1] == 2]
    if not ups:
        return list(cyc)
    if len(ups) == 1:
        cyc, ups = list(cyc) * 2, [ups[0], ups[0] + len(cyc)]
    out = list(cyc)
    for k in ups[1::2]:
        x, y, d = out[k]
        if x == 2:
            out[k] = (3, 1, 5)
        elif x in (0, 3):
            out[k] = (x, 1, d)
        else:
            out[k] = (x, 0, d)
    return out


def transform(theme, name):
    """変え方の名前（base・swap・calm）→ (右手の形の型 a, b)。どれも軽くする（tf_ease）"""
    a, b = _transform(theme, name)
    return tf_ease(a), tf_ease(b)


def _transform(theme, name):
    a, b = list(theme.a), list(theme.b)
    if name == 'swap':
        if a == b:
            return tf_diag(a), tf_diag(b)
        return b, a
    if name == 'calm':
        return tf_calm(a), tf_calm(b)
    return a, b
