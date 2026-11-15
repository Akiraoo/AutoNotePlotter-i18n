"""曲の中身（どこが同じ音楽のくり返しか・小節の頭）を分けた音から測る。規則と計算だけ（学習済みのモデルは使わない）。

曲に合わせた展開（テーマを「同じ音楽には同じ振り・少し変わった所は少し変えた振り」で結びつける）の下ごしらえ。
- 1拍ごとの特徴: 伴奏（ベース＋その他）の和音（12 の音名ごとの強さ＝クロマ）・歌の音名（拾った歌の音符から）・ドラムの型（キック・スネア・
  ハイハットの帯の立ち上がりの強さを 1/4 拍の4か所で）。
- 小節の頭: 和音が変わる拍とキックの強さで、拍ごとにたどる（NLM のマーカーは小節の頭に乗っていないことがある）。途中の短い小節も許す
  （曲E の Cメロ・曲C の転調の前に2拍の小節があり、曲全体で1つに固定した目盛りでは、後ろのサビが半小節ずれて前のサビと比べられなかった）。
- 小節どうしの似ている度合い（4拍を順にそろえて比べる）と、似ている小節に同じ記号を付けた「くり返しの記号」。
- 小節ごとの盛り上がりの手がかり（利用者が曲B を耳で聞いて挙げた物・`bar_intensity`）: ドラムの勢い（大きさ・シンバルの響き）と
  打ち方の変わり目・歌の広がり（エコー・コーラス）・その他の楽器の多さ・旋律楽器（トランペット等）。ベースは曲の盛り上がりと関係が無い（利用者）。
- 音が一回途切れる所（`breaks`・利用者: そこで一つ区切り。曲E のサビの途中の半拍の途切れ）。
- 調のずれ（曲の頭の調から半音いくつ上か。前にあった小節を半音ずらした形のくり返しをつないで測る）＝転調の所。曲B の最後のサビ（+1）・曲C の 1:40〜（+1）
  （どちらも利用者が耳で確かめた）。曲D の 2:13〜2:29 にも −1 が出る（未確認）。
"""
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.lib.stride_tricks import sliding_window_view

from . import audio

MUSIC_VER = 17
CN, CH = 4096, 1024   # クロマの STFT（22050Hz で 5.4Hz ごと＝低い音の半音も分かれる・46ms ごと）


def _chroma_frames(y, lo=50, hi=2000):
    """（コマ, 12）。コマ i の中心＝i×CH の標本"""
    pad = np.concatenate([np.zeros(CN // 2, np.float32), y, np.zeros(CN // 2, np.float32)])
    fr = sliding_window_view(pad, CN)[::CH]
    win = np.hanning(CN).astype(np.float32)
    f = np.fft.rfftfreq(CN, 1 / audio.SR)
    sel = (f >= lo) & (f < hi)
    pc = (np.round(69 + 12 * np.log2(f[sel] / 440.0)).astype(int)) % 12
    M = np.zeros((sel.sum(), 12), np.float32)
    M[np.arange(sel.sum()), pc] = 1
    out = []
    for i in range(0, len(fr), 2048):
        mag = np.abs(np.fft.rfft(fr[i:i + 2048] * win, axis=1))[:, sel]
        out.append((mag ** 2) @ M)
    return np.log(np.concatenate(out) + 1e-6)


def _per_beat(frames, fps, n_beats, t_of):
    """コマの特徴 → 1拍ごとの平均（拍 b ＝ t_of(b)〜t_of(b+1) 秒）"""
    out = np.zeros((n_beats, frames.shape[1]), np.float32)
    for b in range(n_beats):
        i0, i1 = int(max(0, t_of(b)) * fps), int(max(0, t_of(b + 1)) * fps)
        if i1 > i0 and i0 < len(frames):
            out[b] = frames[i0:i1].mean(axis=0)
    return out


def _norm_rows(F, floor, center=False):
    """行ごとに平均を引いて長さ1に（無音・ほぼ一定の拍は 0 のまま）。center＝先に曲全体の平均の形（調・いつも鳴っている音）を引く"""
    if center:
        F = F - F.mean(axis=0, keepdims=True)
    F = F - F.mean(axis=1, keepdims=True)
    n = np.linalg.norm(F, axis=1, keepdims=True)
    return np.where(n > floor, F / np.maximum(n, 1e-9), 0)


def beat_features(stem_dir, onsets, bpm, lead_ms, n_beats):
    """{acc: (拍, 12) 伴奏の和音, mel: (拍, 12) 歌の音名, drum: (拍, 12) ドラムの型（3種×1/4拍の4か所）, kick: (拍,) 拍の頭のキック}"""
    stem_dir = Path(stem_dir)
    t_of = lambda b: b * 60 / bpm - lead_ms / 1000
    y = audio.load_mono(stem_dir / 'bass.flac') + audio.load_mono(stem_dir / 'other.flac')
    acc = _per_beat(_chroma_frames(y), audio.SR / CH, n_beats, t_of)
    mel = np.zeros((n_beats, 12), np.float32)
    for v in onsets['vocal']:
        if v['s'] < 0.3:
            continue
        a, e = v['raw'], v['raw'] + v['length']
        for b in range(max(0, int(a)), min(n_beats, int(np.ceil(e)))):
            mel[b, int(round(v['midi'])) % 12] += max(0.0, min(e, b + 1) - max(a, b)) * v['s']
    # ドラムの型: 帯ごとの立ち上がりの強さ（拾った打点でなく連続の値＝打点の拾い漏れ・強さの揺れに左右されにくい）を 1/4 拍の4か所で
    mag = audio.stft_mag(audio.load_mono(stem_dir / 'drums.flac'))
    drum = np.zeros((n_beats, 12), np.float32)
    w = max(1, int(60 / bpm / 8 * audio.FPS))
    for j, (lo, hi) in enumerate(((30, 150), (180, 2500), (6000, 11000))):
        fl = audio.band_flux(mag, lo, hi)
        fl = np.clip(fl / (np.percentile(fl, 99) + 1e-9), 0, 1)
        for b in range(n_beats):
            for sub in range(4):
                i = int(t_of(b + sub / 4) * audio.FPS)
                if 0 <= i - w and i + w < len(fl):
                    drum[b, j * 4 + sub] = fl[i - w:i + w + 1].max()
    kick = drum[:, 0].copy()
    return {'acc': acc, 'mel': mel, 'drum': drum, 'kick': kick}


def bar_starts(F, short=3.0):
    """小節の頭の拍の番号の並び。和音の変わり目（前の拍との違い）とキックの強さ（曲の平均を引いた物）を小節の頭で足した合計が一番大きい並びを
    拍ごとにたどって選ぶ（ビタビ）。小節は4拍、短い小節（1〜3拍）は1つにつき short を引く＝何小節も続けて頭がずれて見える時だけ入れる
    （1.0 だと曲B に5か所出た・2〜3 で曲B・曲D は 0・曲C・曲E は1か所）"""
    A = _norm_rows(F['acc'], 1e-3, center=True)
    chg = np.r_[0, 1 - (A[1:] * A[:-1]).sum(axis=1)]
    d = chg + 0.5 * F['kick']
    e = d - d.mean()
    n = len(e)
    sc = np.zeros((n, 4))   # 状態＝小節の何拍目か（0＝頭）
    bp = np.zeros((n, 4), int)
    sc[0] = [e[0], 0, 0, 0]
    for b in range(1, n):
        cand = [(sc[b - 1, 3], 3)] + [(sc[b - 1, q] - short, q) for q in (0, 1, 2)]
        v, q = max(cand)
        sc[b, 0], bp[b, 0] = v + e[b], q
        for st in (1, 2, 3):
            sc[b, st], bp[b, st] = sc[b - 1, st - 1], st - 1
    st = int(np.argmax(sc[-1]))
    out = []
    for b in range(n - 1, -1, -1):
        if st == 0:
            out.append(b)
        st = bp[b, st]
    return [b for b in reversed(out) if b + 4 <= n]


def bar_ssm(Fk, starts, floor, center=False):
    """小節どうしの似ている度合い（頭から4拍を順にそろえた拍ごとの cos の平均）と、その小節に音があるか"""
    X = _norm_rows(Fk, floor, center)
    S = X @ X.T
    idx = np.asarray(starts)
    nb = len(idx)
    B = np.zeros((nb, nb), np.float32)
    for k in range(4):
        B += S[np.ix_(idx + k, idx + k)]
    has = np.array([(np.abs(X[i:i + 4]).sum(axis=1) > 0).sum() >= 2 for i in idx])
    return B / 4, has


def labels(B, has, thr):
    """似ている小節に同じ記号（0,1,2…・−1＝音が無い）。前から順に、前の小節のどれかと thr 以上似ていればその記号、無ければ新しい記号。
    2小節続けて似ている所（B[i,j] と B[i+1,j+1] の平均）を見る＝1小節だけたまたま似ている所を拾いにくくする"""
    n = len(B)
    B2 = B.copy()
    B2[:-1, :-1] = (B[:-1, :-1] + B[1:, 1:]) / 2
    lab = np.full(n, -1)
    nxt = 0
    for i in range(n):
        if not has[i]:
            continue
        cand = [(B2[i, j], j) for j in range(i) if has[j] and B2[i, j] >= thr]
        if cand:
            lab[i] = lab[max(cand)[1]]
        else:
            lab[i] = nxt
            nxt += 1
    return lab


THR = {'acc': 0.6, 'mel': 0.5, 'drum': 0.7}
FLOOR = {'acc': 1e-3, 'mel': 0.05, 'drum': 0.05}


# 転調として見るずれ（半音・全音の上げ下げ）。4度・5度・3度のずれでの一致は、同じ調の中の和音の並び（IV→V→iii→vi 等）でよく起きる
KMASK = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1], bool)


def _shift_ssm(Fk, idx, floor, center):
    """（ずらし k, 小節 i, 小節 j）: 小節 i の音名を k 半音下げた形と小節 j の似ている度合い"""
    X0 = _norm_rows(Fk, floor, center)
    out = []
    for k in range(12):
        S = _norm_rows(np.roll(Fk, -k, axis=1), floor, center) @ X0.T
        out.append(sum(S[np.ix_(idx + j, idx + j)] for j in range(4)) / 4)
    return np.array(out)


def bar_shift(F, starts, min_back=4, margin=0.12, match=0.5, run=6, w_mel=0.7):
    """小節ごとの調のずれ（曲の頭の調から半音いくつ上か・0〜11）。音名を半音ずつずらして 4 小節以上前の小節と比べ、一番よく合う小節 j と
    ずらし k を探す。よく合えば（match 以上）その小節の調＝j の調＋k（k≠0 はずらさずに比べた時より margin 以上よく合う時だけ）、合う所が無ければ
    前の小節と同じ調。つないでいくので、転調した後の2回目のくり返しも転調した調のまま。前後2小節で多い物にならし、run 小節より短い変化は消す
    （同じ調の中の別の和音の並び・歌のメロディを1音上で繰り返す所（ゼクエンツ）とたまたま合う。曲B で 3〜5 小節の物が出た。転調は 8 小節以上続く）。調の名前を当てるやり方（長調・短調の重みの表）は取り違えで揺れた。
    比べるのは、両方の小節に歌があれば 歌の音名 w_mel＋伴奏の和音 (1−w_mel)、無ければ伴奏だけ（曲C は歪んだギターの伴奏だけだと
    全音上（+2）に見え、歌の音名の分布は半音上（+1）でぴったり合った）"""
    idx = np.asarray(starts)
    nb = len(idx)
    Bk = _shift_ssm(F['acc'], idx, 1e-3, True)
    mel = F.get('mel')
    if mel is not None and np.abs(mel).sum() > 0:
        X = _norm_rows(mel, FLOOR['mel'])
        sing = np.array([(np.abs(X[i:i + 4]).sum(axis=1) > 0).sum() >= 2 for i in idx])
        both = sing[:, None] & sing[None, :]
        Bk = np.where(both[None], w_mel * _shift_ssm(mel, idx, FLOOR['mel'], False) + (1 - w_mel) * Bk, Bk)
    key = [0] * nb
    for i in range(nb):
        if i <= min_back:
            continue
        m = np.where(KMASK[:, None], Bk[:, i, :i - min_back], -np.inf)
        k, j = np.unravel_index(int(np.argmax(m)), m.shape)
        j0 = int(np.argmax(m[0]))
        if k and m[k, j] - m[0, j0] >= margin and m[k, j] >= match:
            key[i] = (key[j] + int(k)) % 12
        elif m[0, j0] >= match:
            key[i] = key[j0]
        else:
            key[i] = key[i - 1]
    sm = []
    for i in range(nb):
        w = key[max(0, i - 2):i + 3]
        sm.append(max(set(w), key=lambda k: (w.count(k), k == key[i])))
    out = list(sm)
    i = 0
    while i < nb:
        j = i
        while j < nb and sm[j] == sm[i]:
            j += 1
        if j - i < run:
            out[i:j] = [out[i - 1] if i else 0] * (j - i)
        i = j
    return out


def _z(x, mask=None):
    """中央値と四分位の幅でそろえる（mask の所だけで測る）"""
    x = np.asarray(x, float)
    ok = ~np.isnan(x) if mask is None else (~np.isnan(x) & mask)
    if ok.sum() < 4:
        return np.zeros_like(x)
    q1, med, q3 = np.percentile(x[ok], [25, 50, 75])
    return (x - med) / ((q3 - q1) / 1.35 + 1e-9)


DRUM_CHANGE = 2.0   # ドラムの変わり目のしきい値（四分位でそろえた値の差）。曲の中の上位 2 割で決めると、曲C の転調の所が 2.23 対 2.24 で落ちた


def bar_intensity(stem_dir, onsets, bpm, lead_ms, starts):
    """小節ごとの盛り上がりの手がかり（利用者が曲B を耳で聞いて挙げた物）。曲B の区間の平均で確かめた値:
    - drum: ドラムの勢い（ドラム全体の大きさとシンバルの響き＝5〜11kHz の大きさの z の平均）。サビはシンバルが Aメロ・Bメロより 3〜4dB 大きい。
      ドラムの打点の数では分からない（キックは Aメロ 7・サビ 4 回／小節＝サビは毎拍そろって踏む「ドンドンドン」）。
    - drum_change: ドラムの打ち方の変わり目の小節（前後2小節の大きさ・シンバル・スネアとタムの帯・毎拍のキック・裏のキックの差が
      目立って大きい所）。利用者: 打ち方が変わる所は歌い方も変わる＝歌の変わる直前の合図になる。曲C の転調の後の間奏はスネア・タムの帯が
      3dB 上がるだけで、大きさ・シンバル・キックでは出なかった。
    - width: 歌の広がり（左右の差の成分÷真ん中の成分・dB・歌のある小節だけ）。主旋律は真ん中、エコー・コーラスは左右に広がる。
      曲B: サビ −12dB・Aメロ −28・Bメロ −24・落ちサビ −28。
    - bands: その他の楽器の多さ（80Hz〜11kHz を 24 の帯に分け、一番強い帯から 25dB 以内の帯の数の平均）。サビ 21・Aメロ 17.6・落ちサビ 13。
    - lead: 旋律楽器らしさ（その他の音で、高さがはっきり1つに決まるコマの割合＝トランペット・ギターの旋律等）。曲B の間奏・アウトロ・
      サビの直前で出る。歌と同時に吹く所は伴奏に埋もれて拾えない。
    - sing: 歌のある割合（拾った歌の音符）。旋律楽器が「歌の代わり」か「歌に重ねる」かの区別に使う（利用者: 意味合いが違う）"""
    from . import audio
    stem_dir = Path(stem_dir)
    t_of = lambda b: b * 60 / bpm - lead_ms / 1000
    n = len(starts)
    # ドラム
    mag = audio.stft_mag(audio.load_mono(stem_dir / 'drums.flac'))
    f = np.fft.rfftfreq(audio.NFFT, 1 / audio.SR)
    tot = (mag ** 2).sum(axis=1)
    cym = (mag[:, (f >= 5000) & (f < 11000)] ** 2).sum(axis=1)
    snr = (mag[:, (f >= 180) & (f < 2500)] ** 2).sum(axis=1)
    kf = audio.band_flux(mag, 30, 150)
    w = max(1, int(60 / bpm / 8 * audio.FPS))
    peak = lambda c: kf[max(0, c - w):c + w + 1].max() if 0 <= c < len(kf) else 0.0
    dv = np.full((n, 5), np.nan)
    for i, b in enumerate(starts):
        i0, i1 = int(t_of(b) * audio.FPS), int(t_of(b + 4) * audio.FPS)
        if i0 < 0 or i1 > len(tot) or i1 <= i0:
            continue
        on = [peak(int(t_of(b + k) * audio.FPS)) for k in range(4)]
        off = [peak(int(t_of(b + k + 0.5) * audio.FPS)) for k in range(4)]
        dv[i] = [10 * np.log10(tot[i0:i1].mean() + 1e-12), 10 * np.log10(cym[i0:i1].mean() + 1e-12), min(on), np.mean(off),
                 10 * np.log10(snr[i0:i1].mean() + 1e-12)]
    quiet = ~(dv[:, 0] >= np.nanpercentile(dv[:, 0], 95) - 15)   # ドラムがほぼ鳴っていない小節（落ちサビ・終わり）
    # 物差しはドラムが鳴っている小節だけで取る（静かな小節を入れると、ふつうの区間どうしの差が潰れて サビの頭の変わり目が出なかった）
    Z = np.column_stack([_z(dv[:, k], ~quiet) for k in range(5)])
    drum = np.where(quiet, np.nan, (Z[:, 0] + Z[:, 1]) / 2)
    Z = np.nan_to_num(Z) * np.array([1, 1, 0.5, 0.5, 1])
    Z[quiet, :2] = -4
    Z[quiet, 4] = -4
    nov = np.zeros(n)
    for i in range(2, n - 1):
        nov[i] = np.linalg.norm(Z[i:i + 2].mean(axis=0) - Z[i - 2:i].mean(axis=0))
    change = []
    for i in sorted(range(2, n - 1), key=lambda i: -nov[i]):   # 強い順に、隣の小節に強い物が無ければ
        if nov[i] >= DRUM_CHANGE and all(abs(i - c) > 1 for c in change):
            change.append(i)
    change.sort()
    # 歌のある割合
    sing = np.zeros(n)
    on_b = np.zeros(int(max(starts) + 8))
    for v in onsets['vocal']:
        if v['s'] >= 0.3:
            on_b[max(0, int(v['raw'])):max(0, int(v['raw'] + v['length'])) + 1] = 1
    for i, b in enumerate(starts):
        sing[i] = on_b[b:b + 4].mean()
    # 歌の広がり
    y, sr = sf.read(str(stem_dir / 'vocals.flac'), dtype='float32', always_2d=True)
    width = np.full(n, np.nan)
    if y.shape[1] >= 2:
        mid, side = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2
        for i, b in enumerate(starts):
            a0, a1 = int(t_of(b) * sr), int(t_of(b + 4) * sr)
            if a0 < 0 or a1 > len(mid) or sing[i] < 0.5:
                continue
            m = float((mid[a0:a1] ** 2).mean())
            if m > 1e-7:
                width[i] = 10 * np.log10(float((side[a0:a1] ** 2).mean()) / m + 1e-12)
    # その他: 楽器の多さ・旋律楽器らしさ
    yo = audio.load_mono(stem_dir / 'other.flac')
    mag = audio.stft_mag(yo)
    edges = np.geomspace(80, 11000, 25)
    Bdb = 10 * np.log10(np.stack([(mag[:, (f >= edges[k]) & (f < edges[k + 1])] ** 2).sum(axis=1) for k in range(24)], 1) + 1e-12)
    act = (Bdb > Bdb.max(axis=1, keepdims=True) - 25).sum(axis=1)
    loud = Bdb.max(axis=1) > np.percentile(Bdb.max(axis=1), 95) - 40
    _, conf = audio.yin(yo, fmin=150, fmax=1200, hop=256)
    fps2 = audio.SR / 256
    bands, lead = np.full(n, np.nan), np.zeros(n)
    for i, b in enumerate(starts):
        j0, j1 = int(t_of(b) * audio.FPS), int(t_of(b + 4) * audio.FPS)
        if j0 >= 0 and j1 <= len(act) and loud[j0:j1].mean() > 0.5:
            bands[i] = act[j0:j1][loud[j0:j1]].mean()
        k0, k1 = int(t_of(b) * fps2), int(t_of(b + 4) * fps2)
        if k0 >= 0 and k1 <= len(conf):
            lead[i] = (conf[k0:k1] > 0.8).mean()
    r = lambda x, d=2: [None if np.isnan(v) else round(float(v), d) for v in x]
    return {'drum': r(drum), 'drum_change': change, 'drum_nov': r(nov), 'width': r(width, 1), 'bands': r(bands, 1), 'lead': r(lead), 'sing': r(sing)}


def breaks(stem_dir, bpm, lead_ms, n_beats, win=8):
    """音が一回途切れる所（利用者: そこで一つ区切りとしてよい）→ [{beat, len（拍）, kind}]。1/4 拍ごとの大きさを、前後 win 拍の中央値と比べる:
    kind 'all'＝ドラムとその他が両方 12dB 以上下がる（半拍以上・両方 25dB 以上なら 1/4 拍でも。長さは両方 8dB 以上下がっている所まで）・
    'drums'＝ドラムだけ 20dB 以上下がる（1拍以上）。途切れの前 win 拍で
    ドラム（'all' はその他も）がほぼずっと鳴っていて（もともと隙間の多い打ち方・音の少ないイントロを拾わない）、後ろでまた鳴る所だけ。
    曲E のサビの途中（頭から 15.9 秒・2回とも同じ所）で、ドラムとその他が半拍だけ消える。半拍の区切りで測ると、区切りが途切れを
    またいだ時にどちらも半分しか静かにならず漏れた → 1/4 拍で測る"""
    from . import audio
    stem_dir = Path(stem_dir)
    q = 15 / bpm
    t0 = -lead_ms / 1000   # 拍 0 の元の音源の秒
    nq, W = 4 * n_beats, 4 * win
    H = {}
    for k in ('drums', 'other'):
        y = audio.load_mono(stem_dir / f'{k}.flac').astype(np.float64)
        p = np.full(nq, 1e-12)
        for i in range(nq):
            a, b = int((t0 + i * q) * audio.SR), int((t0 + (i + 1) * q) * audio.SR)
            if a >= 0 and b <= len(y) and b > a:
                p[i] = (y[a:b] ** 2).mean() + 1e-12
        H[k] = 10 * np.log10(p)
    med = {k: np.array([np.median(H[k][max(0, i - W):i + W]) for i in range(nq)]) for k in H}
    dd, do = H['drums'] - med['drums'], H['other'] - med['other']
    on = {k: H[k] > med[k] - 12 for k in H}
    out = []
    i = 0
    while i < nq:
        kind = 'all' if dd[i] < -12 and do[i] < -12 else 'drums' if dd[i] < -20 else None
        if kind is None:
            i += 1
            continue
        j = i
        while j < nq and (dd[j] < -12 and do[j] < -12 if kind == 'all' else dd[j] < -20):
            j += 1
        L, before = j - i, slice(i - W, i)
        if kind == 'all':
            deep = L >= 2 or (dd[i] < -25 and do[i] < -25)   # 曲E の2回目のサビ: 両方 −12dB 未満は 1/4 拍だけ（前後は −9・−10dB）
            a, b = i, j
            while a > 0 and dd[a - 1] < -8 and do[a - 1] < -8:
                a -= 1
            while b < nq and dd[b] < -8 and do[b] < -8:
                b += 1
            i, L, end = a, b - a, b
        else:
            deep, end = L >= 4, j
        ok = deep and i >= W and j + 4 <= nq and L <= 32 and on['drums'][j:j + 8].any()
        ok = ok and on['drums'][before].mean() >= 0.85 and (kind == 'drums' or on['other'][before].mean() >= 0.85)
        if ok:
            out.append({'beat': i / 4, 'len': L / 4, 'kind': kind})
        i = max(end, i + 1)
    return out


def analyze(stem_dir, onsets, bpm, lead_ms, n_beats, force=False):
    """→ {bars: [小節の頭の拍], ssm: {acc, mel, drum}, lab: {acc, mel, drum}, shift: [調のずれ], inten: bar_intensity, breaks}。分けた音のフォルダの music.json に保存して使い回す"""
    stem_dir = Path(stem_dir)
    cp = stem_dir / 'music.json'
    key = {'ver': MUSIC_VER, 'bpm': bpm, 'lead_ms': lead_ms, 'n': n_beats}
    if cp.exists() and not force:
        d = json.loads(cp.read_text(encoding='utf-8'))
        if d.get('key') == key:
            return d
    # 途切れ（breaks）はほかに関係しないので同時に測る（numpy・soundfile は GIL を外して動く・答えは同じ・2026-11-11）
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        f_breaks = ex.submit(breaks, stem_dir, bpm, lead_ms, n_beats)
        out = _analyze(stem_dir, onsets, bpm, lead_ms, n_beats, key)
        out['breaks'] = f_breaks.result()
    cp.write_text(json.dumps(out), encoding='utf-8')
    return out


def _analyze(stem_dir, onsets, bpm, lead_ms, n_beats, key):
    F = beat_features(stem_dir, onsets, bpm, lead_ms, n_beats)
    starts = bar_starts(F)
    out = {'key': key, 'bars': starts, 'ssm': {}, 'lab': {}}
    out['shift'] = bar_shift(F, starts)
    # くり返しの記号は、転調した小節の音名を元の調へ戻してから付ける（転調した後のサビも前のサビと同じ記号に）
    per_beat = np.zeros(n_beats, int)
    for i, b in enumerate(starts):
        per_beat[b:starts[i + 1] if i + 1 < len(starts) else n_beats] = out['shift'][i]
    for k in ('acc', 'mel'):
        F[k] = np.array([np.roll(F[k][b], -per_beat[b]) for b in range(n_beats)])
    for k in ('acc', 'mel', 'drum'):
        B, has = bar_ssm(F[k], starts, FLOOR[k], center=k == 'acc')
        out['ssm'][k] = np.round(B, 3).tolist()
        out['lab'][k] = labels(B, has, THR[k]).tolist()
    out['inten'] = bar_intensity(stem_dir, onsets, bpm, lead_ms, starts)
    return out
