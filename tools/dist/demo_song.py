"""確かめ・チュートリアル用のデモ曲（自分で合成した音＝他人の曲を使わない・公開してよい）と文字の無いカバー画像を作る
（tools/dist/checkset.py・docs/tutorial.md の画像の撮り直し・docs/アプリ仕様.md 23 節）。種が同じなら毎回同じ音になる。

BPM 120・4/4・1 小節 2 秒。構成: イントロ 4 小節 → Aメロ 8 → サビ 8 → Aメロ 8 → サビ 8 → アウトロ 4（計 40 小節＝80 秒）＋頭の無音 0.25 秒。
使い方: <.venv の python> tools/dist/demo_song.py <出す場所>  → <出す場所>/デモ曲.flac・Cover.png
"""
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

SR = 44100
BPM = 120.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
LEAD = 0.25
rng = None

SECTIONS = [('intro', 4), ('verse', 8), ('chorus', 8), ('verse', 8), ('chorus', 8), ('outro', 4)]
NBARS = sum(n for _, n in SECTIONS)
TOTAL = LEAD + NBARS * BAR + 2.0
N = int(TOTAL * SR)
L = R = None


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def t_of(bar, beat=0.0):
    return LEAD + bar * BAR + beat * BEAT


def add(sig, t0, gain=1.0, pan=0.0):
    i0 = int(round(t0 * SR))
    if i0 >= N:
        return
    sig = sig[:N - i0]
    gl, gr = gain * np.sqrt(0.5 * (1 - pan)), gain * np.sqrt(0.5 * (1 + pan))
    L[i0:i0 + len(sig)] += sig * gl
    R[i0:i0 + len(sig)] += sig * gr


def env_adsr(n, a=0.01, d=0.1, s=0.7, r=0.08):
    t = np.arange(n) / SR
    dur = n / SR
    e = np.where(t < a, t / a, np.where(t < a + d, 1 - (1 - s) * (t - a) / d, s))
    rel = np.clip((dur - t) / r, 0, 1)
    return e * rel


def bp(x, lo, hi, order=2):
    sos = butter(order, [lo, hi], btype='band', fs=SR, output='sos')
    return sosfilt(sos, x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, btype='high', fs=SR, output='sos'), x)


def lp(x, f, order=2):
    return sosfilt(butter(order, f, btype='low', fs=SR, output='sos'), x)


# ---- ドラム ----
def kick():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 9) + 0.3 * np.exp(-t * 200) * rng.standard_normal(n) * 0.3


def snare():
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    noise = bp(rng.standard_normal(n), 1200, 7000) * np.exp(-t * 18)
    tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 25)
    return 0.9 * noise + 0.5 * tone


def hat(open_=False):
    n = int((0.25 if open_ else 0.05) * SR)
    t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 7000, 4) * np.exp(-t * (12 if open_ else 80))


def crash():
    n = int(2.0 * SR)
    t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 4000, 2) * np.exp(-t * 2.2)


KICK = SNARE = HAT = OHAT = CRASH = None


# ---- 和音・ベース ----
def pad(midis, dur, bright=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.zeros(n)
    for m in midis:
        f = midi_hz(m)
        for det in (-0.004, 0.004):
            ff = f * (1 + det)
            for k in range(1, 9):
                if ff * k > 6000:
                    break
                s += np.sin(2 * np.pi * ff * k * t + rng.uniform(0, 6.28)) * (bright ** (k - 1)) / k
    s = lp(s, 2500 if bright < 0.8 else 4500)
    return s * env_adsr(n, a=0.08, d=0.3, s=0.8, r=0.25) / (len(midis) * 6)


def bass_note(m, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = midi_hz(m)
    s = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.15 * np.sin(2 * np.pi * 3 * f * t)
    return s * env_adsr(n, a=0.005, d=0.15, s=0.6, r=0.05)


# ---- 歌の代わり（声に近い音色・母音の響きの山・ビブラート） ----
VOWELS = {'a': [(800, 80, 1.0), (1150, 90, 0.5), (2900, 120, 0.25), (3900, 130, 0.1)],
          'o': [(450, 70, 1.0), (800, 80, 0.45), (2830, 100, 0.12), (3800, 120, 0.06)],
          'e': [(400, 60, 1.0), (1700, 80, 0.4), (2600, 100, 0.3), (3500, 120, 0.12)]}


def voice(m, dur, vowel='a', vib=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f0 = midi_hz(m)
    vdepth = 0.018 * vib * np.clip((t - 0.18) / 0.25, 0, 1)   # 伸ばすと遅れてビブラートがかかる
    f = f0 * (1 + vdepth * np.sin(2 * np.pi * 5.6 * t)) * (1 + 0.012 * np.exp(-t * 18) * -1)   # 頭は少し下から
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.zeros(n)
    forms = VOWELS[vowel]
    for k in range(1, 40):
        fk = f0 * k
        if fk > 7000:
            break
        g = sum(a / (1 + ((fk - fc) / bw) ** 2) for fc, bw, a in forms) + 0.02
        s += g * np.sin(k * ph) / np.sqrt(k)
    breath = hp(rng.standard_normal(n), 3000) * 0.015 * np.exp(-t * 10)
    return (s / 6 + breath) * env_adsr(n, a=0.03, d=0.12, s=0.85, r=0.09)


# 和音の並び（1 小節ずつ）
CH = {'Am': [57, 60, 64], 'F': [53, 57, 60], 'C': [55, 60, 64], 'G': [55, 59, 62], 'Em': [55, 59, 64], 'Dm': [57, 62, 65]}
ROOT = {'Am': 45, 'F': 41, 'C': 48, 'G': 43, 'Em': 40, 'Dm': 38}
VERSE_CH = ['Am', 'F', 'C', 'G']
CHORUS_CH = ['F', 'G', 'Em', 'Am']
INTRO_CH = ['Am', 'F', 'C', 'G']

# 旋律（拍, 長さ, 音・母音）: 2 小節（8 拍）ずつ
VERSE_MEL = [
    [(0, 1, 64), (1, .5, 67), (1.5, .5, 69), (2, 1, 72), (3, 1, 71), (4, 1.5, 69), (5.5, .5, 67), (6, 1.5, 65)],
    [(0, .5, 64), (.5, .5, 67), (1, 1, 72), (2, 1, 74), (3, 1, 72), (4, 1, 71), (5, 1, 67), (6, 1.5, 67)],
    [(0, 1, 64), (1, .5, 67), (1.5, .5, 69), (2, 1, 72), (3, 1, 74), (4, 1.5, 76), (5.5, .5, 74), (6, 1.5, 72)],
    [(0, .5, 71), (.5, .5, 72), (1, 1, 74), (2, 1, 72), (3, 1, 71), (4, 2, 69), (6, 1, 67), (7, .5, 68)],
]
CHORUS_MEL = [
    [(0, 1.5, 72), (1.5, .5, 74), (2, 1, 76), (3, 1, 77), (4, 1.5, 79), (5.5, .5, 77), (6, 1.5, 76)],
    [(0, 1, 76), (1, 1, 74), (2, 1, 72), (3, 1, 71), (4, 2, 72), (6, .5, 74), (6.5, 1, 76)],
    [(0, 1.5, 72), (1.5, .5, 74), (2, 1, 76), (3, 1, 77), (4, 1.5, 79), (5.5, .5, 81), (6, 1.5, 79)],
    [(0, 1, 77), (1, 1, 76), (2, 1, 74), (3, 1, 72), (4, 3, 69)],
]


def drums(bar, kind):
    t0 = t_of(bar)
    if kind == 'intro':
        for b in range(4):
            add(HAT, t0 + b * BEAT, 0.08, 0.2)
        if bar % 4 == 3:
            for x in (2, 2.5, 3, 3.25, 3.5, 3.75):
                add(SNARE, t0 + x * BEAT, 0.25 + 0.1 * (x - 2))
        return
    if kind == 'outro':
        if bar % 4 == 0:
            add(CRASH, t0, 0.35)
            add(KICK, t0, 0.9)
        for b in range(4):
            add(HAT, t0 + b * BEAT, 0.06, 0.2)
        return
    if kind == 'verse':
        for x in (0, 1.5, 2.5):
            add(KICK, t0 + x * BEAT, 0.9)
        for x in (1, 3):
            add(SNARE, t0 + x * BEAT, 0.55)
        for i in range(8):
            add(HAT, t0 + i * 0.5 * BEAT, 0.12 if i % 2 == 0 else 0.07, 0.25)
    else:   # サビ: 4 つ打ち・16 分のハイハット・頭にクラッシュ
        for x in range(4):
            add(KICK, t0 + x * BEAT, 1.0)
        for x in (1, 3):
            add(SNARE, t0 + x * BEAT, 0.7)
        for i in range(16):
            add(OHAT if i % 4 == 2 else HAT, t0 + i * 0.25 * BEAT, 0.12 if i % 2 == 0 else 0.06, 0.3)
        if bar % 8 == 0:
            add(CRASH, t0, 0.45, -0.3)
    if bar % 8 == 7:   # 区切りの前のフィル
        for x in (3, 3.25, 3.5, 3.75):
            add(SNARE, t0 + x * BEAT, 0.45)


# ---- カバー画像（文字無し・グラデーションと円） ----
def png(path, img):
    h, w, _ = img.shape
    raw = b''.join(b'\x00' + img[y].tobytes() for y in range(h))

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')
    Path(path).write_bytes(data)


def make(out, name='デモ曲'):
    """out にデモ曲（<name>.flac）と Cover.png を作る → (曲の場所, カバーの場所)。毎回同じ音（種 7）"""
    global rng, L, R, KICK, SNARE, HAT, OHAT, CRASH
    out = Path(out)
    rng = np.random.default_rng(7)
    L, R = np.zeros(N), np.zeros(N)
    KICK, SNARE, HAT, OHAT, CRASH = kick(), snare(), hat(), hat(True), crash()
    bar = 0
    for kind, nb in SECTIONS:
        for i in range(nb):
            b = bar + i
            chs = {'verse': VERSE_CH, 'chorus': CHORUS_CH}.get(kind, INTRO_CH)
            ch = chs[i % 4]
            bright = 0.85 if kind == 'chorus' else 0.6
            gain = {'intro': 0.9, 'outro': 0.8, 'verse': 0.7, 'chorus': 1.0}[kind]
            p = pad(CH[ch], BAR + 0.2, bright)
            add(p, t_of(b), gain * 0.9, -0.35)
            add(p, t_of(b) + 0.012, gain * 0.9, 0.35)
            if kind == 'chorus':   # サビは上に1オクターブの和音を足す
                add(pad([m + 12 for m in CH[ch]], BAR + 0.2, 0.7), t_of(b), 0.4, 0.0)
            drums(b, kind)
            if kind in ('verse', 'chorus'):
                r = ROOT[ch]
                if kind == 'verse':
                    for x, d in ((0, 1.4), (1.5, .4), (2, 1.4), (3.5, .4)):
                        add(bass_note(r, d * BEAT), t_of(b, x), 0.55)
                else:
                    for k in range(8):
                        add(bass_note(r + (12 if k % 2 else 0), 0.45 * BEAT), t_of(b, k * 0.5), 0.6)
            elif kind == 'outro' and i == 0:
                add(bass_note(ROOT[ch], 3.5 * BEAT), t_of(b), 0.5)
            if kind in ('verse', 'chorus') and i % 2 == 0:
                mel = (VERSE_MEL if kind == 'verse' else CHORUS_MEL)[(i // 2) % 4]
                for j, (x, d, m) in enumerate(mel):
                    vw = 'aoe'[(j + i) % 3]
                    v = voice(m, d * BEAT * 0.95, vw, vib=1.0 if d >= 1 else 0.3)
                    if kind == 'verse':
                        add(v, t_of(b, x), 0.55, 0.0)
                    else:   # サビは声を2つ重ねて左右に広げ、3度下のハモり
                        add(v, t_of(b, x), 0.45, -0.25)
                        add(voice(m + 0.08, d * BEAT * 0.95, vw, 1.0), t_of(b, x) + 0.015, 0.4, 0.25)
                        add(voice(m - 4 if m % 12 in (4, 11) else m - 3, d * BEAT * 0.95, vw, 0.8), t_of(b, x), 0.22, 0.0)
        bar += nb

    mix = np.stack([L, R], axis=1)
    fade = int(1.5 * SR)
    end = int((LEAD + NBARS * BAR + 1.8) * SR)
    mix = mix[:end]
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    mix = mix / np.max(np.abs(mix)) * 0.89
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'{name}.flac'
    with sf.SoundFile(str(path), 'w', SR, 2, 'PCM_16', format='FLAC') as f:
        f.title = name
        f.artist = 'Auto Note Plotter'
        f.write(mix)
    S = 512
    y, x = np.mgrid[0:S, 0:S] / (S - 1)
    top, bot = np.array([0.36, 0.18, 0.62]), np.array([0.05, 0.55, 0.75])
    img = (top[None, None] * (1 - y[..., None]) + bot[None, None] * y[..., None])
    for cx, cy, r, col in ((0.32, 0.38, 0.22, (0.95, 0.25, 0.35)), (0.66, 0.6, 0.2, (0.2, 0.5, 1.0))):
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        a = np.clip((r - d) / 0.01, 0, 1)[..., None] * 0.85
        img = img * (1 - a) + np.array(col)[None, None] * a
    img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    cover = out / 'Cover.png'
    png(cover, img)
    return path, cover


if __name__ == '__main__':
    song, cover = make(sys.argv[1] if len(sys.argv) > 1 else '.')
    print('wrote', song, cover)
