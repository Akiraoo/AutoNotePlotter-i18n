"""曲の音量の測定（automap/loudness.py・NLM の js/audio/loudness.js の写し）。値は NLM の tests/unit_js/test_loudness.py と同じ"""
import math

import numpy as np

from automap import loudness as L


def _sine(rate, parts, f=1000, ph=0.0):
    out = []
    t0 = 0
    for sec, db in parts:
        n = int(round(sec * rate))
        t = (np.arange(n) + t0) / rate
        out.append(10 ** (db / 20) * np.sin(2 * np.pi * f * t + ph))
        t0 += n
    return np.concatenate(out)


def test_k_weighting_coefficients_at_48k():
    (sb, sa), (hb, ha) = L.k_weighting(48000)
    want = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [-1.69065929318241, 0.73248077421585], [-1.99004745483398, 0.99007225036621])
    assert all(abs(g - w) < 1e-6 for g, w in zip(sb, want[0]))
    assert all(abs(g - w) < 1e-6 for g, w in zip(sa[1:], want[1]))
    assert all(abs(g - w) < 1e-6 for g, w in zip(ha[1:], want[2])) and hb == [1.0, -2.0, 1.0]


def test_ebu_sine_levels():
    for rate in (48000, 44100):
        for db in (-23, -33):
            x = _sine(rate, [(20, db)])
            m = L.measure([x, x], rate)
            assert abs(m['lufs'] - db) <= 0.1 and abs(m['peak_db'] - db) <= 0.05, (rate, db, m)
    assert abs(L.measure([_sine(48000, [(20, -23)])], 48000)['lufs'] - (-26.01)) <= 0.1   # モノラルは 3 LU 小さい


def test_ebu_gating_silence_and_short():
    a = _sine(48000, [(10, -36), (60, -23), (10, -36)])
    b = _sine(48000, [(20, -26), (20.1, -20), (20, -26)])
    assert abs(L.measure([a, a], 48000)['lufs'] - (-23)) <= 0.1
    assert abs(L.measure([b, b], 48000)['lufs'] - (-23)) <= 0.1
    z = np.zeros(48000 * 5)
    m = L.measure([z, z], 48000)
    assert m['lufs'] == -math.inf and m['peak_db'] == -math.inf
    assert L.measure([np.zeros(1000)], 48000)['lufs'] == -math.inf


def test_ranges_measure_only_inside():
    x = _sine(48000, [(10, -40), (10, -20), (10, -30)])
    mid = L.measure([x, x], 48000, [(10, 20)])
    two = L.measure([x, x], 48000, [(0, 10), (20, 30)])
    assert abs(mid['lufs'] - (-20)) <= 0.1 and abs(mid['peak_db'] - (-20)) <= 0.05
    assert abs(two['peak_db'] - (-30)) <= 0.05 and two['lufs'] < -29


def test_true_peak_between_samples():
    x = _sine(48000, [(2, -6)], f=12000, ph=math.pi / 4)
    m = L.measure([x, x], 48000)
    assert abs(m['sample_peak_db'] - (-9.01)) <= 0.05 and abs(m['peak_db'] - (-6.0)) <= 0.2


def test_auto_gain_same_as_nlm():
    a = lambda lufs, pk: L.auto_gain({'lufs': lufs, 'peak_db': pk})
    assert a(-17.29, -8.51) == {'db': 7.5, 'by': 'peak'}
    assert a(-20, -15) == {'db': 11.0, 'by': 'target'}
    assert a(-7, 1.2) == {'db': 0.0, 'by': 'loud'} and a(-9, -3) == {'db': 0.0, 'by': 'loud'}
    assert a(-12, -0.95) == {'db': 0.0, 'by': 'noRoom'}
    assert a(-40, -30) == {'db': 20.0, 'by': 'max'}
    assert a(-math.inf, -math.inf) == {'db': 0.0, 'by': 'silent'}
    assert (L.AUTO_TARGET_LUFS, L.AUTO_PEAK_DB, L.GAIN_MIN_DB, L.GAIN_MAX_DB) == (-9, -1, -20, 20)


def _quiet_with_peaks(rate=44100, sec=20.0, seed=1):
    """平均が小さく（約 -20 LUFS）、ときどき大きな瞬間（-9 dB）がある音＝自動の補正では -12 LUFS ほどまでしか上がらない"""
    rng = np.random.default_rng(seed)
    n = int(rate * sec)
    x = rng.standard_normal(n) * 10 ** (-24 / 20)
    for i in range(0, n, rate // 2):
        x[i:i + 200] += 10 ** (-9 / 20) * np.sin(np.arange(200) * 0.3)
    return np.stack([x, x], axis=1).astype(np.float32)


def test_limiter_raises_to_the_target_under_the_ceiling():
    y = _quiet_with_peaks()
    m0 = L.measure([y[:, 0], y[:, 1]], 44100)
    assert m0['lufs'] + L.auto_gain(m0)['db'] < -11.5   # 自動の補正（NLM と同じ）では目標に届かない
    out, info = L.limit(y, 44100)
    assert not info['skipped'] and abs(info['lufs'] - L.AUTO_TARGET_LUFS) <= 0.2 and info['peak_db'] <= L.AUTO_PEAK_DB + 0.02
    m = L.measure([out[:, 0], out[:, 1]], 44100)
    assert abs(m['lufs'] - info['lufs']) < 1e-6 and out.shape == y.shape and out.dtype == np.float32


def test_limiter_leaves_loud_songs_alone():
    y = _quiet_with_peaks() * np.float32(10 ** (12 / 20))   # 約 -9.5 LUFS（もう十分大きい）
    out, info = L.limit(y, 44100)
    assert info['skipped'] and out is y or np.array_equal(out, y)
