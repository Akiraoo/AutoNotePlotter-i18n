from types import SimpleNamespace

import numpy as np

from automap import hooks

N = 320
AT = [40, 56, 140, 156, 260, 276]   # くり返し（8 拍）を置く所。後ろの 2 回は半音上に転調


def _song(seed=3):
    rng = np.random.default_rng(seed)
    mel = rng.random((N, 12)) ** 4   # 歌（拍ごとの音名）: でたらめ
    acc = rng.random((N, 12))
    pm, pa = rng.random((8, 12)) ** 4, rng.random((8, 12))
    pm[:, 0] += 2.0   # くり返しの節（はっきりした音名）
    for t in AT:
        k = 1 if t >= 260 else 0
        mel[t:t + 8] = np.roll(pm, k, axis=1) + 0.02 * rng.random((8, 12))
        acc[t:t + 8] = np.roll(pa, k, axis=1) + 0.02 * rng.random((8, 12))
    bars = list(range(0, N, 4))
    shift = [1 if b >= 256 else 0 for b in bars]
    mu = {'bars': bars, 'shift': shift, 'inten': {'sing': [1.0] * len(bars)}}
    blocks = [SimpleNamespace(b0=b0, b1=b0 + 32, level=3 if b0 in (32, 128, 256) else 0) for b0 in range(0, N, 32)]
    markers = [{'beat': 0, 'name': 'Aメロ'}, {'beat': 36, 'name': 'サビ'}, {'beat': 72, 'name': 'Bメロ'}, {'beat': 136, 'name': 'サビ'},
               {'beat': 172, 'name': 'Bメロ'}, {'beat': 256, 'name': 'サビ'}, {'beat': 292, 'name': 'アウトロ'}]
    return {'mel': mel, 'acc': acc}, mu, blocks, markers


def test_finds_repeated_phrase_with_key_change():
    F, mu, blocks, markers = _song()
    gs = hooks.detect(F, mu, blocks, markers)
    assert gs, '候補が無い'
    g = gs[0]
    starts = [o['b0'] for o in g['occ']]
    assert all(any(abs(s - t) <= 1 for s in starts) for t in AT), starts   # 転調した後ろの 2 回も
    assert 6 <= g['L'] <= 10 and g['L'] % 2 == 0
    late = [o for o in g['occ'] if o['b0'] >= 250]
    assert late and all(o['k'] == 1 for o in late)   # 半音上で合った
    assert all(o['b1'] - o['b0'] == g['L'] for o in g['occ'])
    occ = sorted(starts)
    assert all(b - a >= g['L'] for a, b in zip(occ, occ[1:]))   # 回どうしは重ならない


def test_deterministic_and_plain_numbers():
    import json
    F, mu, blocks, markers = _song()
    a, b = hooks.detect(F, mu, blocks, markers), hooks.detect(F, mu, blocks, markers)
    assert json.dumps(a) == json.dumps(b)   # 同じ材料なら同じ答え・JSON に出せる（numpy の型を出さない）


def test_no_vocal_no_candidates():
    F, mu, blocks, markers = _song()
    F['mel'][:] = 0
    assert hooks.detect(F, mu, blocks, markers) == []
