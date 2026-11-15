"""盛り上がりの繰り返し（フック）の候補を探す（docs/アプリ仕様.md 18 節・2026-11-02 利用者）。

歌のくり返しのうち、曲の中で何回も出る一番盛り上がる所（桃源郷の「アイロニー」・BURN の「バーン」のような所）を、同じ振りの
グループの候補として多めに拾う（間違っていてよい・人が画面で消す・範囲も直す）。初めの譜面づくりには入れない（画面で押した時だけ）。
材料は拍ごとの歌の音名と伴奏の和音（music.beat_features・画面の「似た所を探す」と同じ）・転調（mu['shift']）・曲の流れの表の
盛り上がりの段階（form.build）・歌の有無（bar_intensity の sing）・区間の名前（サビ）。

1. 短い種（2・4 拍）ごとに、近さが THR 以上の所を重ならないように拾う（3 回以上）。
2. 回どうしが似ている間（各回の拍の近さの中央値が EXT_THR 以上）は前後へ伸ばす（最大 MAX_LEN 拍・長さは偶数の拍）。
3. 伸ばした長さで、少し低い境目（WEAK_THR）まで仲間を足す（弱い回＝weak の印）。
4. 点＝近さ × 盛り上がり（段階とサビ）× 回の数 × 離れたまとまりの数 × 歌 × 長さ × 小節の中の位置のそろい。
5. 同じ所の組（小さい方の回の 6 割以上が重なる）は1つに（長い方の点が 85% 以上なら長い方）。

確かめ（利用者が付けた同じ振りと比べた・2026-11-02）: 桃源郷「アイロニー」6 回（8 拍）＝1 位の組が 6 回とも頭も長さも同じ（余分 1 回）。
BURN「バーン」11 回（2 拍）＝上位の組が 10 回を頭から 1 拍以内で（長さは 8 拍＝続きの節まで入る）。1 曲 0.2〜0.4 秒。
"""
import numpy as np

from . import music, rhythm

SHIFTS = (0, 1, 2, 10, 11)   # 比べる半音のずらし（転調した所・画面の「似た所を探す」と同じ）
W_MEL = 0.7                  # 歌の音名の重み（残りは伴奏の和音）
THR = 0.72                   # 種の回の境目
EXT_THR = 0.55               # 伸ばす時の拍の近さの境目（各回の中央値）
WEAK_THR = 0.62              # 足す弱い回の境目
MAX_LEN = 16
SEEDS = (2, 4)
MIN_OCC = 3
TOP = 8


def _feats(F):
    M = music._norm_rows(np.asarray(F['mel'], float), music.FLOOR['mel'])
    A = music._norm_rows(np.asarray(F['acc'], float), 1e-3, center=True)
    return M, A, np.linalg.norm(M, axis=1) > 0


def _pairs(M, A, v):
    """拍どうしの近さ {k: (歌, 伴奏)}（種の側を k 半音上げて比べる＝後ろの回が k 半音上に転調していれば k で合う）"""
    return {k: (np.roll(M, k, axis=1) @ M.T, np.roll(A, k, axis=1) @ A.T) for k in SHIFTS}


def _diag_sum(X, L):
    """X[s+i, t+i] の i＝0..L−1 の和 → [s, t]"""
    n = X.shape[0]
    c = np.zeros((n + 1, n + 1))
    c[1:, 1:] = X
    for i in range(1, n + 1):
        c[i, 1:] += c[i - 1, :-1]
    return (c[L:, L:] - c[:-L, :-L])[:n - L + 1, :n - L + 1]


def _seg_sim(pairs, v, kbeat, L):
    """区間（頭の拍・長さ L）どうしの近さ → (近さ[s, t], ずらし[s, t])。歌は両方にある拍だけ（片方だけは近さ 0）・
    転調の見込み（kbeat）と違うずらしは 0.1 引く"""
    n = len(v)
    both = (v[:, None] & v[None, :]).astype(float)
    cnt = _diag_sum(both, L)
    kexp = (kbeat[None, :n - L + 1] - kbeat[:n - L + 1, None]) % 12
    best = np.full(cnt.shape, -9.0)
    bk = np.zeros(cnt.shape, dtype=int)
    for k, (Sm, Sa) in pairs.items():
        sm, sa = _diag_sum(Sm * both, L), _diag_sum(Sa, L)
        val = W_MEL * np.where(cnt > 0, sm / np.maximum(cnt, 1), 0) * (cnt / L) + (1 - W_MEL) * sa / L - 0.1 * (kexp != k)
        up = val > best
        best[up], bk[up] = val[up], k
    return best, bk


def _per_beat(n, bars, blocks, markers, sing_bar):
    """拍ごとの盛り上がり（段階/3 とサビの半々）と歌の有無"""
    lvl = np.zeros(n)
    for b in blocks:
        lvl[int(b.b0):int(min(n, b.b1))] = b.level / 3
    chorus = np.zeros(n)
    secs = rhythm.sections_from_markers(markers or [], n)
    for s in secs:
        if 'サビ' in s.name:
            chorus[int(s.b0):int(min(n, s.b1))] = 1
    bars = np.asarray(bars)
    bi = np.clip(np.searchsorted(bars, np.arange(n), side='right') - 1, 0, max(0, len(sing_bar) - 1))
    sing = np.asarray(sing_bar, float)[bi] if len(sing_bar) else np.ones(n)
    return 0.5 * lvl + 0.5 * chorus, sing


def detect(F, mu, blocks, markers, top=TOP):
    """→ [{L, score, why, occ: [{b0, b1, s（種との近さ）, k（半音のずらし）, weak}]}]（点の良い順）"""
    M, A, v = _feats(F)
    n = len(v)
    if n < 16 or not v.any():
        return []
    bars = mu['bars']
    bar_of = np.clip(np.searchsorted(np.asarray(bars), np.arange(n), side='right') - 1, 0, len(bars) - 1)
    kbeat = np.array([(mu.get('shift') or [0] * len(bars))[i] for i in bar_of])
    hype, sing = _per_beat(n, bars, blocks, markers, (mu.get('inten') or {}).get('sing') or [])
    pairs = _pairs(M, A, v)
    one = (v[:, None] ^ v[None, :]).astype(float)
    P = {k: W_MEL * Sm * (v[:, None] & v[None, :]) - 0.3 * W_MEL * one + (1 - W_MEL) * Sa for k, (Sm, Sa) in pairs.items()}
    SS = {}

    def seg(L):
        if L not in SS:
            SS[L] = _seg_sim(pairs, v, kbeat, L)
        return SS[L]
    voiced = lambda t, L: v[t:t + L].sum() >= max(1, L * 0.6)
    groups = []
    for L in SEEDS:
        S, K = seg(L)
        for s in range(S.shape[0]):
            if not v[s] or not voiced(s, L):
                continue
            row = S[s]
            occ = [s]
            for t in np.argsort(-row):
                if row[t] < THR:
                    break
                t = int(t)
                if all(abs(t - o) >= L for o in occ) and voiced(t, L):
                    occ.append(t)
            if len(occ) < MIN_OCC:
                continue
            g = _grow(s, L, sorted(occ), {t: int(K[s, t]) for t in occ}, P, n, v, seg, hype, sing, bars)
            if g:
                groups.append(g)
    return _merge(groups, top)


def _grow(s, L, occ, ks, P, n, v, seg, hype, sing, bars):
    """種の組を前後へ伸ばし、弱い回を足して点を付ける → 組か None"""
    others = [t for t in occ if t != s]

    def med(i):
        return float(np.median([P[ks[t]][s + i, t + i] if 0 <= s + i < n and 0 <= t + i < n else -1.0 for t in others]))
    a, b = 0, L
    while b - a < MAX_LEN and med(b) >= EXT_THR:
        b += 1
    while b - a < MAX_LEN and min(occ) + a > 0 and med(a - 1) >= EXT_THR:
        a -= 1
    if (b - a) % 2:
        b += 1
    span = b - a
    sims = {t: float(np.mean([P[ks[t]][s + i, t + i] if s + i < n and t + i < n else -1.0 for i in range(a, b)])) for t in others}
    keep = [s]
    for t in sorted(others, key=lambda t: -sims[t]):
        if all(abs(t - o) >= span for o in keep):
            keep.append(t)
    if len(keep) < MIN_OCC:
        return None
    weak = []
    Ssp, Ksp = seg(span)
    if 0 <= s + a < Ssp.shape[0]:
        row = Ssp[s + a]
        for t in np.argsort(-row):
            if row[t] < WEAK_THR:
                break
            t0 = int(t) - a
            if any(abs(t0 - o) < span for o in keep + weak) or v[int(t):int(t) + span].sum() < span * 0.5:
                continue
            weak.append(t0)
            sims[t0], ks[t0] = float(row[t]), int(Ksp[s + a, t])
    keep.sort()
    ms = float(np.mean([sims[t] for t in keep if t != s]))
    hy = float(np.mean([hype[t + a:t + b].mean() for t in keep]))
    sg = float(np.mean([sing[t + a:t + b].mean() for t in keep]))
    clusters = 1 + sum(1 for x, y in zip(keep, keep[1:]) if y - x >= 24)
    k_n = len(keep)
    f_n = min(k_n, 8) / 8 * (1.0 if k_n <= 14 else 14 / k_n)
    bars_ = np.asarray(bars)
    ph = [int((t + a) - bars_[max(0, np.searchsorted(bars_, t + a, side='right') - 1)]) % 4 for t in keep]   # 小節の中の位置
    f_ph = max(ph.count(x) for x in set(ph)) / len(ph)
    score = ms * (0.2 + 0.8 * hy) * f_n * min(clusters, 3) / 3 * (0.5 + 0.5 * sg) * (1 + 0.15 * np.log2(span)) * (0.6 + 0.4 * f_ph)
    occ_out = [{'b0': t + a, 'b1': t + b, 's': round(sims.get(t, 1.0), 3), 'k': ks[t] - 12 if ks[t] > 6 else ks[t], 'weak': t in weak}
               for t in sorted(keep + weak)]
    return {'L': span, 'score': round(float(score), 4), 'occ': occ_out,
            'why': f'近さ {ms:.2f}・盛り上がり {hy:.2f}・歌 {sg:.2f}・離れたまとまり {clusters}・回 {k_n}＋弱い回 {len(weak)}'}


def _merge(groups, top):
    """同じ所の組を1つに（小さい方の組の回の 6 割以上が、短い方の長さの半分以上重なる）。長い方の点が 85% 以上なら長い方を残す"""
    groups.sort(key=lambda g: -g['score'])

    def same(x, y):
        small, big = (x, y) if len(x['occ']) <= len(y['occ']) else (y, x)
        hit = sum(any(min(p['b1'], q['b1']) - max(p['b0'], q['b0']) >= 0.5 * min(p['b1'] - p['b0'], q['b1'] - q['b0']) for q in big['occ'])
                  for p in small['occ'])
        return hit / len(small['occ']) >= 0.6
    kept = []
    for g in groups:
        j = next((j for j, k in enumerate(kept) if same(g, k)), None)
        if j is None:
            kept.append(g)
        elif g['L'] > kept[j]['L'] and g['score'] >= 0.85 * kept[j]['score']:
            kept[j] = dict(g, score=kept[j]['score'])
    kept.sort(key=lambda g: -g['score'])
    return kept[:top]
