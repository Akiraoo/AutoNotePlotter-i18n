import numpy as np

from automap import music


def test_labels_repeat():
    """同じ4小節が2回 → 同じ記号が同じ順に付く"""
    rng = np.random.default_rng(0)
    base = rng.normal(size=(16, 12))
    B, has = music.bar_ssm(np.concatenate([base, base]), [0, 4, 8, 12, 16, 20, 24, 28], 1e-3)
    lab = music.labels(B, has, 0.6)
    assert list(lab[:4]) == [0, 1, 2, 3]
    assert list(lab[4:]) == [0, 1, 2, 3]


def test_labels_silent_bar():
    """音の無い小節は −1"""
    rng = np.random.default_rng(1)
    F = rng.normal(size=(16, 12))
    F[4:8] = 0
    B, has = music.bar_ssm(F, [0, 4, 8, 12], 1e-3)
    assert music.labels(B, has, 0.6)[1] == -1


def test_bar_shift_half_step_up():
    """8小節の和音の並びを2回、3回目は半音上げ → 3回目だけ +1"""
    rng = np.random.default_rng(2)
    base = rng.normal(size=(32, 12))
    acc = np.concatenate([base, base, np.roll(base, 1, axis=1)])
    sh = music.bar_shift({'acc': acc}, list(range(0, 96, 4)))
    assert sh[:16] == [0] * 16
    assert sh[16:] == [1] * 8


def _bars(heads, n, seed=3):
    """heads の拍で和音が変わり、キックが鳴る1拍ごとの特徴"""
    rng = np.random.default_rng(seed)
    acc = np.zeros((n, 12))
    kick = np.zeros(n)
    chord = rng.normal(size=12)
    for b in range(n):
        if b in heads:
            chord = rng.normal(size=12)
            kick[b] = 1
        acc[b] = chord
    return {'acc': acc, 'kick': kick}


def test_bar_starts():
    """和音が拍 2 から4拍ごとに変わり、キックもそこ → 小節の頭は 2, 6, 10 …"""
    heads = set(range(2, 64, 4))
    assert music.bar_starts(_bars(heads, 64)) == sorted(h for h in heads if h + 4 <= 64)


def test_bar_starts_short_bar():
    """途中に2拍の小節（拍 34〜36）→ その後ろは頭が2拍ずれる。1小節だけの外れでは目盛りを変えない"""
    heads = set(range(2, 35, 4)) | set(range(36, 96, 4))
    assert music.bar_starts(_bars(heads, 96)) == sorted(h for h in heads if h + 4 <= 96)
    one = (set(range(2, 96, 4)) - {50}) | {52}   # 1か所だけ和音の変わり目が2拍遅れる
    st = music.bar_starts(_bars(one, 96))
    assert all((b - 2) % 4 == 0 for b in st)


def test_breaks(tmp_path):
    """ドラム（1/4 拍ごとの短い音）とその他（ずっと鳴る音）: 拍 40〜40.5 で両方止まる → 'all'・拍 20〜22 でドラムだけ止まる → 'drums'"""
    import soundfile as sf
    sr, bpm, n = 22050, 120.0, 64
    t = np.arange(int(n * 60 / bpm * sr)) / sr
    rng = np.random.default_rng(4)
    drums = np.zeros_like(t)
    q = int(15 / bpm * sr)
    for i in range(0, len(t) - q, q):
        drums[i:i + int(0.03 * sr)] = rng.normal(scale=0.3, size=int(0.03 * sr))
    other = 0.2 * np.sin(2 * np.pi * 440 * t)
    beat = lambda b: int(b * 60 / bpm * sr)
    drums[beat(20):beat(22)] = 0
    drums[beat(40):beat(40.5)] = 0
    other[beat(40):beat(40.5)] = 0
    sf.write(tmp_path / 'drums.flac', drums.astype(np.float32), sr)
    sf.write(tmp_path / 'other.flac', other.astype(np.float32), sr)
    out = music.breaks(tmp_path, bpm, 0, n)
    assert {'beat': 20.0, 'len': 2.0, 'kind': 'drums'} in out
    assert {'beat': 40.0, 'len': 0.5, 'kind': 'all'} in out
    assert len(out) == 2
