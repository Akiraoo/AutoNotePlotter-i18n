"""流れの計算の Numba 版（automap/flow_nb.py・2026-11-10）の決まり。答えが前と同じことは tests/test_flow_same.py（13 ケース）。"""
import math
import random
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from automap import flow, flow_nb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_power_matches_python():
    """角度の減点の間の倍率 4^(0.25−dt) が Python と最後の桁まで同じ（底は配列から渡す＝定数の 4 だと LLVM が exp2(2x) に書き換えて
    25 万回中 65 回ずれた）"""
    rnd = random.Random(1)
    dts = [rnd.uniform(0, 6) for _ in range(20000)] + [b * s - a * s for s in (0.5, 60 / 129, 60 / 175) for a in range(30) for b in range(a, a + 20)]
    four = np.array([4.0])[0]
    assert all(flow_nb._tf(dt, four) == (1.0 if dt <= 0.25 else 4 ** (0.25 - dt)) for dt in dts)


def test_jitter_matches_python():
    """揺らぎ（64 ビットの符号なしの整数の式）が flow._jitter と同じ"""
    rnd = random.Random(2)
    for _ in range(300):
        key = flow._jitter_key(rnd.randrange(1000), round(rnd.uniform(0, 500), 4))
        h, q, x, y, d = rnd.randrange(2), rnd.randrange(2), rnd.randrange(4), rnd.randrange(3), rnd.randrange(8)
        assert flow_nb._jitter(np.uint64(key), h, q, x, y, d) == flow._jitter(key, h, q, x, y, d)


def test_tables_match_python_geometry():
    """hypot・atan2 を使う物は Python で作った表（Numba の数学の関数は最後の桁が違うことがある）: 振りの入り口までの移動・手拍子形"""
    st = flow.Style()
    SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG = flow_nb._tables(st)
    h, q, px, py, pd = 1, 0, 2, 1, 5
    vx, vy = flow.DIR_VEC[pd]
    for i in range(SO_N[h, q]):
        x, y, d = SO_X[h, q, i], SO_Y[h, q, i], SO_D[h, q, i]
        ix, iy = x - flow.DIR_VEC[d][0] * st.travel_k, y - flow.DIR_VEC[d][1] * st.travel_k
        assert G_WH[h, q, px, py, pd, i] == st.w_travel * math.hypot(px + vx * st.travel_k - ix, py + vy * st.travel_k - iy)
    pf = flow_nb._pair_flags()
    assert bool(pf[1, 0, 3, 2, 0, 2, 3]) == flow.handclap(1, 0, 3, 2, 0, 2)


def test_empty_and_tiny():
    """打点が無い・1 つ・置ける候補の少ないビームでも動く"""
    assert flow_nb.search([], flow.Style(), None) == ([], 0.0)
    notes, cost = flow.generate([flow.Event(4.0, 2.0, 2)], flow.Style(beam=1))
    assert len(notes) == 2 and {n['c'] for n in notes} == {0, 1}


def test_compose_process_uses_generic_cpu():
    """作り直しのプロセス（python -m automap）は NUMBA_CPU_NAME=generic（配布物に入れたコンパイル済みの控えをどの PC でも読む）"""
    code = ("import os, runpy, sys; sys.argv = ['automap', '--help']\n"
            "try:\n    runpy.run_module('automap', run_name='__main__')\nexcept SystemExit:\n    pass\n"
            "print('CPU=' + os.environ.get('NUMBA_CPU_NAME', ''))")
    env = {k: v for k, v in __import__('os').environ.items() if k != 'NUMBA_CPU_NAME'}
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert 'CPU=generic' in out.stdout, out.stdout + out.stderr
