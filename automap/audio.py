"""分けた音（tools/separate.py の cache/<曲>/vocals.flac 等）から打点の候補を拾う。規則と計算だけ（学習済みのモデルは使わない）。

- ドラム: 帯域ごとの音の立ち上がり（対数の振幅の増え方の和＝スペクトルフラックス）の山。低い帯＝キック・中＝スネア・高い帯＝ハイハット。
- 歌: 1音ずつの「歌の音符の表」（始まり・終わり・高さ・強さ）。音の高さは YIN（自己相関の一種）で測り、
  ①無声→有声になった所 ②子音などで音が立ち上がった所 ③高さが半音近く変わってそのまま続いた所、を音の区切りにする。
- 秒→拍は NLM と同じ（拍 b の時刻＝b×60/BPM 秒・元の音源の秒＝その時刻−無音追加）。テンポパートは今は扱わない。
"""
import os
from contextlib import contextmanager

import numpy as np
import soundfile as sf
from numpy.lib.stride_tricks import sliding_window_view

SR = 22050
HOP = 128            # 5.8ms
NFFT = 1024
FPS = SR / HOP


_KEPT = None   # kept() の中で読んだ音 {(場所, sr, 更新時刻, 大きさ): 音}


@contextmanager
def kept():
    """この中では読んだ分けた音を覚えて使い回す（写しを返す）。打点の候補（rhythm.analyze）と曲の中身（music.analyze）は同じ 4 つの
    音を 11 回読み直していた（桃源郷で読むだけで 5.9 秒・覚えると 4 回で 3.8 秒ほど短い・2026-11-11）。出た時に捨てる
    （サーバーのように長く動くプロセスに 80MB ほどを残さない）"""
    global _KEPT
    prev = _KEPT
    if _KEPT is None:
        _KEPT = {}
    try:
        yield
    finally:
        _KEPT = prev


def load_mono(path, sr=SR):
    memo = _KEPT
    if memo is None:
        return _load_mono(path, sr)
    st = os.stat(path)
    key = (os.path.abspath(path), sr, st.st_mtime_ns, st.st_size)
    y = memo.get(key)
    if y is None:
        y = memo[key] = _load_mono(path, sr)
    return y.copy()


def _load_mono(path, sr):
    y, r = sf.read(str(path), dtype='float32', always_2d=True)
    y = y.mean(axis=1)
    if r != sr:
        from math import gcd
        from scipy import signal
        g = gcd(int(r), int(sr))
        y = signal.resample_poly(y, sr // g, int(r) // g).astype(np.float32)
    return y


def stft_mag(y):
    """振幅のスペクトログラム（コマ, 周波数）。コマ i の中心＝i×HOP の標本（頭に NFFT/2 の無音を足す）"""
    pad = np.concatenate([np.zeros(NFFT // 2, np.float32), y, np.zeros(NFFT // 2, np.float32)])
    win = np.hanning(NFFT).astype(np.float32)
    out = []
    fr = sliding_window_view(pad, NFFT)[::HOP]
    for i in range(0, len(fr), 4096):
        out.append(np.abs(np.fft.rfft(fr[i:i + 4096] * win, axis=1)).astype(np.float32))
    return np.concatenate(out)


def band_flux(mag, lo, hi, lag=2):
    """lo〜hi Hz の帯の、対数の振幅の増え方の和（音の立ち上がりの強さ・コマごと）"""
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    m = np.log1p(100 * mag[:, (f >= lo) & (f < hi)])
    d = np.zeros(len(m), np.float32)
    d[lag:] = np.maximum(m[lag:] - m[:-lag], 0).sum(axis=1)
    return d


def pick_peaks(nov, *, gap=0.07, win=0.4, k=1.0, floor_pct=60, rel=0.1):
    """立ち上がりの強さの山（コマの番号, 強さ）。近くの平均＋k×ばらつき を越え、±gap 秒で一番大きく、全体の floor_pct 番目の値と、
    強い山（99 番目の値）の rel 倍より大きい物（一定の音の中のごく小さな揺れを拾わない）"""
    g = max(1, int(gap * FPS))
    w = max(3, int(win * FPS)) | 1
    ker = np.ones(w) / w
    mu = np.convolve(nov, ker, mode='same')
    sd = np.sqrt(np.maximum(np.convolve(nov ** 2, ker, mode='same') - mu ** 2, 0))
    floor = max(np.percentile(nov, floor_pct), rel * np.percentile(nov, 99))
    from scipy import signal   # 使う時まで読まない（作り直しは控えの打点 onsets.json・music.json を読み、多くはここを通らない＝読み込みの 0.7 秒を省く・2026-11-09）
    mx = signal.order_filter(nov, np.ones(2 * g + 1), 2 * g)
    idx = np.where((nov >= mx) & (nov > mu + k * sd) & (nov > floor))[0]
    return idx, nov[idx]


def drum_onsets(path):
    """ドラムの音から {kick, snare, hihat: [(秒, 強さ0〜1)]}"""
    mag = stft_mag(load_mono(path))
    out = {}
    for name, lo, hi, k in (('kick', 30, 150, 1.0), ('snare', 180, 2500, 1.2), ('hihat', 6000, 11000, 1.0)):
        nov = band_flux(mag, lo, hi)
        idx, s = pick_peaks(nov, k=k)
        s = s / (np.percentile(s, 95) + 1e-9)
        out[name] = [(float(i / FPS), float(min(1.0, v))) for i, v in zip(idx, s)]
    return out


def bass_onsets(path):
    """ベースの音から [(秒, 強さ0〜1)]（30〜400Hz の立ち上がりの山）。低い音は立ち上がりがなまり、目盛りより遅れて出る＝寄せる前に差し引く（rhythm.analyze）"""
    mag = stft_mag(load_mono(path))
    idx, s = pick_peaks(band_flux(mag, 30, 400), k=1.0)
    s = s / (np.percentile(s, 95) + 1e-9)
    return [(float(i / FPS), float(min(1.0, v))) for i, v in zip(idx, s)]


# ---- 歌 ----

def yin(y, fmin=80, fmax=1000, hop=256, W=512, thr=0.15):
    """YIN の高さ（Hz・0＝無声）と、有声らしさ（1−周期の崩れ）を hop ごとに。コマ i の中心＝i×hop の標本"""
    tmax = int(SR / fmin)
    tmin = int(SR / fmax)
    L = W + tmax   # W＝足し合わせる幅（一番長い周期より長く）
    pad = np.concatenate([np.zeros(L // 2, np.float32), y, np.zeros(L, np.float32)])
    fr = sliding_window_view(pad, L)[::hop]
    n = len(fr)
    f0 = np.zeros(n, np.float32)
    conf = np.zeros(n, np.float32)
    nfft = 1 << int(np.ceil(np.log2(L + W)))
    for a in range(0, n, 1024):
        x = fr[a:a + 1024].astype(np.float64)
        # d(τ) = Σ_{j<W} (x_j − x_{j+τ})² = e(0) + e(τ) − 2 r(τ)
        X = np.fft.rfft(x, nfft, axis=1)
        Wf = np.fft.rfft(x[:, :W], nfft, axis=1)
        r = np.fft.irfft(X * np.conj(Wf), nfft, axis=1)[:, :tmax + 1]
        cs = np.cumsum(np.concatenate([np.zeros((len(x), 1)), x ** 2], axis=1), axis=1)
        tau = np.arange(tmax + 1)
        e0 = cs[:, W] - cs[:, 0]
        et = cs[:, tau + W] - cs[:, tau]
        d = e0[:, None] + et - 2 * r
        d[:, 0] = 0
        cm = np.cumsum(d[:, 1:], axis=1) / np.arange(1, tmax + 1)
        dn = np.ones_like(d)
        dn[:, 1:] = d[:, 1:] / np.maximum(cm, 1e-12)
        seg = dn[:, tmin:]
        below = seg < thr
        first = np.where(below.any(axis=1), below.argmax(axis=1), seg.argmin(axis=1))
        # 谷の底まで進める
        rows = np.arange(len(seg))
        t = first.copy()
        for _ in range(8):
            nxt = np.minimum(t + 1, seg.shape[1] - 1)
            go = seg[rows, nxt] < seg[rows, t]
            if not go.any():
                break
            t = np.where(go, nxt, t)
        v = seg[rows, t]
        # 放物線で補間
        tl, tr = np.maximum(t - 1, 0), np.minimum(t + 1, seg.shape[1] - 1)
        a_, b_, c_ = seg[rows, tl], v, seg[rows, tr]
        den = a_ - 2 * b_ + c_
        sh = np.where(np.abs(den) > 1e-12, 0.5 * (a_ - c_) / np.where(np.abs(den) > 1e-12, den, 1), 0)
        period = t + tmin + np.clip(sh, -1, 1)
        f0[a:a + 1024] = SR / period
        conf[a:a + 1024] = 1 - np.clip(v, 0, 1)
    return f0, conf


def hz_to_midi(f):
    return 69 + 12 * np.log2(np.maximum(f, 1e-6) / 440.0)


def vocal_notes(path, *, voiced_conf=0.75, min_note=0.06, jump=0.8):
    """歌の音から [{t0, t1, midi, s}]（秒・MIDI の高さ・強さ0〜1）。"""
    y = load_mono(path)
    hop = 256
    fps = SR / hop
    f0, conf = yin(y, hop=hop)
    n = len(f0)
    # 音量（dB）。曲の中の歌の大きさに対して相対で見る
    fr = sliding_window_view(np.concatenate([np.zeros(512, np.float32), y, np.zeros(1024, np.float32)]), 1024)[::hop][:n]
    rms = np.sqrt((fr.astype(np.float64) ** 2).mean(axis=1))
    db = 20 * np.log10(rms + 1e-9)
    loud = np.percentile(db[db > -80], 90) if (db > -80).any() else -20
    voiced = (conf >= voiced_conf) & (db > loud - 30) & (f0 >= 80) & (f0 <= 1000)
    # 短い穴（30ms 未満）は埋め、短い有声（40ms 未満）は捨てる
    voiced = _close(voiced, int(0.03 * fps))
    voiced = _open(voiced, int(0.04 * fps))
    midi = np.where(voiced, hz_to_midi(f0), np.nan)
    sm = _nanmedian_filter(midi, 5)
    # 子音などの立ち上がり（歌の音の 150〜5000Hz のフラックス）を hop 256 のコマへ
    mag = stft_mag(y)
    nov = band_flux(mag, 150, 5000)
    pk, _ = pick_peaks(nov, gap=0.08, k=1.2)
    on_t = pk / FPS
    bounds = set()
    # ① 有声の始まり
    st = np.where(voiced & ~np.r_[False, voiced[:-1]])[0]
    bounds.update(st.tolist())
    # ② 立ち上がり（有声の中か、その直前 60ms 以内）
    for t in on_t:
        i = int(round(t * fps))
        j = min(n - 1, i + int(0.06 * fps))
        if 0 <= i < n and voiced[i:j + 1].any():
            k = i + int(np.argmax(voiced[i:j + 1])) if not voiced[i] else i
            bounds.add(k)
    # ③ 高さが jump 半音以上変わり、60ms 以上そのまま
    hold = int(0.06 * fps)
    i = 1
    while i < n - hold:
        if voiced[i] and voiced[i - 1] and not np.isnan(sm[i]) and not np.isnan(sm[i - 1]):
            before = np.nanmedian(sm[max(0, i - hold):i])
            after = np.nanmedian(sm[i:i + hold])
            if abs(after - before) >= jump and np.all(np.abs(sm[i:i + hold] - after) < 0.6):
                bounds.add(i)
                i += hold
                continue
        i += 1
    bounds = sorted(bounds)
    # 近すぎる区切りはまとめる（前を残す）
    merged = []
    for b in bounds:
        if merged and b - merged[-1] < int(min_note * fps):
            continue
        merged.append(b)
    notes = []
    for k, b in enumerate(merged):
        e = merged[k + 1] if k + 1 < len(merged) else n
        seg = voiced[b:e]
        if not seg.any():
            continue
        last = b + int(np.where(seg)[0][-1]) + 1   # 有声の終わり
        if (last - b) / fps < min_note:
            continue
        m = np.nanmedian(midi[b:last])
        s = float(np.max(db[b:last]))
        notes.append({'t0': float(b / fps), 't1': float(last / fps), 'midi': float(m), 'db': s,
                      'cont': bool(notes) and b / fps - notes[-1]['t1'] < 0.02, 'dip': _dip(db, b, fps)})
    if notes:
        top = np.percentile([x['db'] for x in notes], 95)
        for x in notes:
            x['s'] = float(np.clip(1 + (x.pop('db') - top) / 30, 0, 1))
    return notes


def _dip(db, i, fps):
    """区切り（コマ i）の所で大きさが沈む深さ（dB）: 前と後の 50〜200ms の大きさの中央値の小さい方 − 区切りの −50〜+15ms の最小。
    子音・息で歌い直した所は深く、伸ばしの中の高さの揺れ・ビブラート（±4dB ほど）・合唱の高さの取り違えで切れた所は浅い"""
    a, w, c = int(0.05 * fps), int(0.2 * fps), int(0.015 * fps)
    lo = float(db[max(0, i - a):i + c + 1].min())
    pre, post = db[max(0, i - w):max(0, i - a)], db[i + a // 2:i + w]
    if not len(pre) or not len(post):
        return 99.0
    return float(min(np.median(pre), np.median(post)) - lo)


def _close(b, w):
    if w <= 0:
        return b
    out = b.copy()
    idx = np.where(~b)[0]
    if not len(idx):
        return out
    runs = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
    for r in runs:
        if len(r) < w and r[0] > 0 and r[-1] < len(b) - 1:
            out[r] = True
    return out


def _open(b, w):
    return ~_close(~b, w)


def _nanmedian_filter(x, w):
    h = w // 2
    p = np.concatenate([np.full(h, np.nan), x, np.full(h, np.nan)])
    v = sliding_window_view(p, w)
    with np.errstate(all='ignore'):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return np.nanmedian(v, axis=1)


# ---- 拍 ----

def sec_to_beat(t, bpm, lead_ms):
    """元の音源の秒 → NLM の拍（テンポパート無し）"""
    return (t + lead_ms / 1000.0) * bpm / 60.0


def snap(beat, grids=(4, 3)):
    """一番近い 1/4 拍か 1/3 拍の目盛り。(目盛りの拍, 何分の拍か, ずれ（拍）)"""
    best = None
    for g in grids:
        q = round(beat * g) / g
        d = beat - q
        if best is None or abs(d) < abs(best[2]) - 1e-9:
            best = (q, g, d)
    return best
