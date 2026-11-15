"""曲の音量の測定と、音量補正の「自動」の値（2026-11-08 利用者「書き出す時に音楽の音量を一定にする機能が NLM にあるので、ここでも使えるように。
音源の音が小さい曲があって聞きにくい」）。NLM の js/audio/loudness.js の写し（同じ式・同じ目標＝NLM の「自動調整」と同じ値になる）。

測るのは ITU-R BS.1770-4（EBU R128）の積分ラウドネス（LUFS＝耳の感じ方に合わせた平均の音量）と、トゥルーピーク（dBTP＝サンプルの間も含めた
一番大きい瞬間。4 倍に補間して近似）。自動の補正は、平均を -9 LUFS（手元のカスタム曲の相場）へ上げるが、一番大きい瞬間が -1 dB を超えない所で
止め、自動では下げない。値は曲のノード（graph.song.gainDb）に書き、書き出しが song.egg へ焼き込む（automap/bs_export.py・NLM と同じ）。
"""
import math

import numpy as np

AUTO_TARGET_LUFS = -9.0   # 自動の目標（平均の音量）
AUTO_PEAK_DB = -1.0       # 自動で上げる上限＝一番大きい瞬間がこれを超えない所で止める（音割れを避ける）
GAIN_MIN_DB, GAIN_MAX_DB = -20.0, 20.0
TP_H = 12                 # トゥルーピークの補間の前後のサンプル数


def k_weighting(rate):
    """K 特性フィルタ（前段の高域シェルフ＋後段のハイパス）の係数 → ((b, a), (b, a))（a は a0=1 を含む）"""
    f0, Q, G = 1681.974450955533, 0.7071752369554196, 3.999843853973347
    K = math.tan(math.pi * f0 / rate)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    shelf = ([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0],
             [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / rate)
    d = 1 + K / Q + K * K
    hp = ([1.0, -2.0, 1.0], [1.0, 2 * (K * K - 1) / d, (1 - K / Q + K * K) / d])
    return shelf, hp


def _tp_phases():
    """サンプルの間の 1/4・2/4・3/4 の位置の値を求める窓付き sinc（前後 12 サンプル・直流の利得 1）"""
    out = []
    for f in (0.25, 0.5, 0.75):
        t = f - np.arange(1 - TP_H, TP_H + 1)
        w = np.sin(np.pi * t) / (np.pi * t) * 0.5 * (1 + np.cos(np.pi * t / TP_H))
        out.append(w / w.sum())
    return out


_TP = _tp_phases()


def _db(v):
    return 20 * math.log10(v) if v > 0 else -math.inf


def _block_lufs(z):
    return -0.691 + 10 * np.log10(z)


def measure(chs, rate, ranges=None, peak=True):
    """音量を測る。chs＝チャンネルごとの 1 次元の配列（同じ長さ）、rate＝サンプリング周波数、ranges＝測る区間 [(開始秒, 終了秒)]（None＝全体・
    書き出す song.egg に入る所だけを測る時に使う）→ {lufs, peak_db, sample_peak_db}。無音・0.4 秒未満なら lufs は -inf。
    peak＝False ならトゥルーピークを測らない（peak_db はサンプルのピーク・リミッターのやり直しの間を速く）"""
    from scipy.signal import lfilter
    chs = [np.asarray(x, dtype=np.float64) for x in chs]
    n = len(chs[0]) if chs else 0
    R = [(0.0, n / rate)] if not ranges else ranges
    R = [(max(0, round(s * rate)), min(n, round(e * rate))) for s, e in R]
    R = [(s, e) for s, e in R if e > s]
    (sb, sa), (hb, ha) = k_weighting(rate)
    sub = round(rate * 0.1)   # 100ms。400ms のブロックを 100ms ずつずらして測る（重なり 75%）
    blocks, sp = [], 0.0
    for s, e in R:
        n_sub = (e - s) // sub
        sub_sum = np.zeros(n_sub)
        for x in chs:
            seg = x[s:e]
            if len(seg):
                sp = max(sp, float(np.abs(seg).max()))
            z = lfilter(hb, ha, lfilter(sb, sa, seg))
            if n_sub:
                sub_sum += (z[:n_sub * sub] ** 2).reshape(n_sub, sub).sum(axis=1)
        if n_sub >= 4:
            blocks.append(np.convolve(sub_sum, np.ones(4), mode='valid') / (4 * sub))
    lufs = -math.inf
    if blocks:
        z = np.concatenate(blocks)
        z = z[z > 0]
        z = z[_block_lufs(z) > -70] if len(z) else z   # 絶対ゲート
        if len(z):
            rel = float(_block_lufs(z.mean())) - 10   # 相対ゲート
            g = z[_block_lufs(z) > rel]
            if len(g):
                lufs = float(_block_lufs(g.mean()))
    return {'lufs': lufs, 'peak_db': _db(_true_peak(chs, R, sp) if peak else sp), 'sample_peak_db': _db(sp)}


def _true_peak(chs, R, sp):
    """サンプルの間も含めた最大の振幅。隣り合う 2 つのサンプルのどちらかがピークの半分以上の所だけ補間する（loudness.js と同じ）"""
    best, th = sp, sp * 0.5
    for x in chs:
        for s, e in R:
            seg = x[s:e]
            if len(seg) < 2:
                continue
            av = np.abs(seg)
            mask = (av[:-1] >= th) | (av[1:] >= th)
            if not mask.any():
                continue
            pad = np.concatenate([np.zeros(TP_H - 1), seg, np.zeros(TP_H)])
            for w in _TP:
                y = np.abs(np.correlate(pad, w, mode='valid'))[:len(seg) - 1]
                m = float(y[mask].max())
                if m > best:
                    best = m
    return best


def auto_gain(m, target=AUTO_TARGET_LUFS, ceil=AUTO_PEAK_DB):
    """「自動」の補正値（dB・0.1 刻みで切り捨て）→ {db, by}。by: target＝目標まで上げた・peak＝音が割れない所で止めた・max＝補正の上限・
    loud＝もう目標以上（上げない）・noRoom＝ピークに余裕が無い・silent＝測れない"""
    if not m or not math.isfinite(m.get('lufs', -math.inf)) or not math.isfinite(m.get('peak_db', -math.inf)):
        return {'db': 0.0, 'by': 'silent'}
    by_l, by_p = target - m['lufs'], ceil - m['peak_db']
    if by_l <= 0:
        return {'db': 0.0, 'by': 'loud'}
    lim = min(by_l, by_p, GAIN_MAX_DB)
    db = math.floor(lim * 10 + 1e-9) / 10
    if db <= 0:
        return {'db': 0.0, 'by': 'noRoom'}
    return {'db': db, 'by': 'target' if lim == by_l else 'peak' if lim == by_p else 'max'}


# ---- リミッター（2026-11-08 利用者「B もオプションで選べるように」・NLM には無い・こちらの書き出しの song.egg だけ） ----
# 自動の補正（上の auto_gain）はピークを抑えずに上げるので、一番大きい瞬間に余裕の無い静かな曲はほとんど上がらない（パピヨン -14.8 LUFS・
# ピーク -3.4 dB → +2.3 dB だけ）。リミッターは平均を目標まで上げ、上限を超える瞬間だけ先読みで少し抑える。

LIM_BLOCK = 32          # 下げる量を決める単位（サンプル）
LIM_ATTACK = 0.005      # 先読み（秒）: 超える所の手前から少しずつ下げる
LIM_RELEASE = 0.08      # 戻り（秒）
LIM_MARGIN = 0.3        # サンプルの上限を上限より下げておく（dB・サンプルの間の山の分）
LIM_MAX_PUSH = 8.0      # 一番大きい瞬間を上限からこれ以上は押し込まない（dB）＝上げる量は (上限−元のピーク)＋これまで。無いと、もとから大きく
                        # ピークが 0 dB を超える曲（Rewind -10.5 LUFS・+2.5 dB）で +20 dB 上げて 25 dB 抑え、音をつぶした
LIM_FROM = 2.0          # 目標よりこれ以上小さい曲だけに掛ける（LU）。もとから大きい曲（shadow dance -9.8・Rewind -10.5）は 9 dB 以上抑えても
LIM_GAIN_MIN = 1.0      # 平均が 0.3〜0.5 しか上がらなかった＝掛けても平均がこれだけ上がらなければ元のまま


def _limit_once(y, sr, gain_db, ceil_db):
    """y（サンプル, チャンネル）を gain_db 上げ、サンプルの絶対値が ceil_db を超える所だけ下げる → (出力, 一番大きく下げた dB)"""
    from numpy.lib.stride_tricks import sliding_window_view
    B = LIM_BLOCK
    n = len(y)
    nb = -(-n // B)
    env = np.abs(y).max(axis=1) * (10 ** (gain_db / 20))
    env = np.concatenate([env, np.zeros(nb * B - n)]).reshape(nb, B).max(axis=1)
    req = np.maximum(0.0, 20 * np.log10(np.maximum(env, 1e-12)) - ceil_db)   # ブロックごとに下げる量（dB）
    la = max(1, round(LIM_ATTACK * sr / B))
    r1 = sliding_window_view(np.concatenate([req, np.zeros(la)]), la + 1).max(axis=1)   # この先 la ブロックで一番下げる量
    c = np.cumsum(np.concatenate([np.full(la - 1, r1[0]), r1]))
    r2 = (c[la - 1:] - np.concatenate([[0.0], c[:-la]])) / la   # 手前 la ブロックの平均＝少しずつ下げる（超える所では必ず req 以上）
    r2 = np.maximum(r2, req)
    k = math.exp(-B / (sr * LIM_RELEASE))
    r3 = np.empty(nb)
    prev = 0.0
    for b, v in enumerate(r2.tolist()):   # 戻りは指数でゆっくり（下げる時はすぐ）
        d = prev * k
        prev = v if v > d else d
        r3[b] = prev
    rb = np.empty(nb + 1)   # ブロックの境目の値（両隣の大きい方）を線でつなぐ＝ブロックの中でも必ず要る量以上
    rb[0], rb[-1] = r3[0], r3[-1]
    rb[1:-1] = np.maximum(r3[:-1], r3[1:])
    red = np.interp(np.arange(n), np.arange(nb + 1) * B, rb)
    g = (10 ** ((gain_db - red) / 20)).astype(np.float32)
    return y * g[:, None], float(r3.max()) if nb else 0.0


def limit(y, sr, target=AUTO_TARGET_LUFS, ceil=AUTO_PEAK_DB, tries=8, tol=0.15):
    """リミッター: y（サンプル, チャンネル・float32）の平均を target LUFS まで上げ（上げるだけ・+20 dB まで）、一番大きい瞬間（トゥルーピーク）は
    ceil dB を超えないように抑える → (出力, {gain_db, reduced_db（一番大きく抑えた量）, lufs, peak_db, before, skipped, capped}）。
    目標より LIM_FROM 以上小さい曲だけ・平均が LIM_GAIN_MIN 以上上がらなければ元のまま（skipped）。
    抑えると平均も下がるので、上げる量は割線法で決める（平均だけを測ってやり直し・トゥルーピークは最後に測ってはみ出したら上限を下げる）"""
    y = np.asarray(y, dtype=np.float32)
    chs = lambda a: [a[:, c] for c in range(a.shape[1])]
    m0 = measure(chs(y), sr)
    info = {'before': m0, 'gain_db': 0.0, 'reduced_db': 0.0, 'lufs': m0['lufs'], 'peak_db': m0['peak_db'], 'skipped': True}
    if not math.isfinite(m0['lufs']) or m0['lufs'] >= target - LIM_FROM:
        return y, info
    cdb = ceil - LIM_MARGIN
    gmax = max(0.0, min(GAIN_MAX_DB, ceil - m0['peak_db'] + LIM_MAX_PUSH))
    out = y
    g = min(gmax, target - m0['lufs'])
    for _ in range(4):   # トゥルーピークがはみ出したらサンプルの上限を下げて合わせ直す（上げる量は前の続きから）
        g0, f0 = None, None
        for _ in range(tries):
            out, red = _limit_once(y, sr, g, cdb)
            f = measure(chs(out), sr, peak=False)['lufs'] - target
            if abs(f) <= tol or (f < 0 and g >= gmax - 1e-9):
                break
            slope = (f - f0) / (g - g0) if g0 is not None and abs(g - g0) > 1e-6 else 1.0
            slope = min(1.2, max(0.15, slope))   # 抑えるほど 1 dB 上げても平均は 1 dB より少なく上がる
            g0, f0, g = g, f, min(gmax, max(0.0, g - f / slope))
        m = measure(chs(out), sr)
        info.update(gain_db=round(g, 2), reduced_db=round(red, 2), lufs=m['lufs'], peak_db=m['peak_db'], capped=g >= gmax - 1e-9 and m['lufs'] < target - tol)
        over = m['peak_db'] - ceil
        if over <= 0.02:
            break
        cdb -= over * 1.5 + 0.05   # 高い音の多い曲ほどサンプルの間の山が大きい
    else:   # それでもはみ出す時は全体を下げて必ず収める
        out = out * np.float32(10 ** (-(over + 0.02) / 20))
        m = measure(chs(out), sr)
        info.update(lufs=m['lufs'], peak_db=m['peak_db'])
    if info['lufs'] - m0['lufs'] < LIM_GAIN_MIN:   # 抑えるばかりで上がらない＝元のまま
        return y, dict(info, gain_db=0.0, reduced_db=0.0, lufs=m0['lufs'], peak_db=m0['peak_db'], skipped=True)
    info['skipped'] = False
    return out, info


BY_TEXT = {'target': '目標の -9 LUFS まで上げた', 'peak': '音が割れない所で止めた', 'max': '補正の上限 +20 dB で止めた',
           'loud': 'もう十分大きいので上げない', 'noRoom': '一番大きい瞬間に余裕が無いので上げない', 'silent': '測れなかった'}


def measure_file(path, ranges=None):
    """音源のファイル（soundfile で読める物・終わりが壊れた MP3 は読めた所まで＝automap/sfread）を測る"""
    from . import sfread
    x, rate = sfread.read(path)
    return measure([x[:, c] for c in range(x.shape[1])], rate, ranges)
