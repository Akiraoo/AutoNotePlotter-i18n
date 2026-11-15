"""流れの計算（flow.generate のビームサーチ）の Numba 版（2026-11-10・利用者「やるなら全部」・docs/アプリ仕様.md 19 節）。

答えは前の Python 版と 1 ビットも同じ（tests/test_flow_same.py・tests/test_flow_nb.py）。そのための決まり:
- 足し算・掛け算は Python 版と同じ値を同じ順に（浮動小数点の丸めが変わらない）。fastmath は使わない（足し算の順を入れ替えない）。
- hypot・atan2 を使う物（振りの入り口までの移動・手拍子形・置き方の指示の移動）は Python で表にして渡す（Numba の数学の関数は
  Python と最後の桁が違うことがある）。べき乗（間の長さで角度の減点を軽くする 4^(0.25−dt)）は底を配列から読む＝定数の底だと LLVM が
  exp2 に書き換えて最後の桁が違った（25 万回中 65 回）。
- 候補は絞らずに全部数える（前の Python 版の上位 PRUNE の絞り込みと数え直しは、全部を数えた時と同じ答えになるように作ってある）。
  同じ状態のキーの候補は点数の小さい方・同点は先に数えた方。並べ替えは同点なら先にキーを入れた順（Python の辞書と安定な並べ替えと同じ）。
- 揺らぎ（flow._jitter）は 64 ビットの符号なしの整数で同じ式。

減点の決まりを足す・変える時はここを直し、答えをわざと変えたなら tests/test_flow_same.py を --write する。前の Python 版（ビームサーチの
本体・先読み・割合の更新）は除いた（2026-11-10・二重に直さないため。答えが同じことは 13 ケース・40 通りの作り物の並び・11 曲の作り直しで確かめた）。
流れの計算の全体の考え方・方針の数は automap/flow.py（Style・Event の説明）。
配布物にはコンパイル済みの控え（__pycache__ の .nbi・.nbc）を入れる。CPU の種類によらず使えるように、作り直しのプロセス
（python -m automap）は NUMBA_CPU_NAME=generic で動かす（automap/__main__.py の頭・docs/アプリ仕様.md 23 節）。
"""
import math

import numpy as np
from numba import njit

from . import flow as F

# ---- 手の状態（int の 9 項目＋秒）: 振り・x・y・向き・打点の番号・同じマスの続き・テーマの番号・型の何番目まで・前の振り上げが上の段か
HQ, HX, HY, HD, HEI, HRUN, HGID, HNK, HTOP = range(9)
NH = 9
KEY = 2 * NH + 1   # 候補のキー: 左手の 9 項目・右手の 9 項目・手（両手は −1）

# ---- 直近の割合（ema）の並び: 段 3・向きの種類 3・真ん中・同じマス・交互・列 4・手から見た列（左 4・右 4）・両手を同時に外へ・手から見たマス（左 12・右 12）
E_ROW, E_DIR, E_CEN, E_STILL, E_ALT, E_COL, E_HC, E_WIDE, E_KC = 0, 3, 6, 7, 8, 9, 13, 21, 22
NE = 46

# ---- 打点の数（float）
(F_SEC, F_BEAT, F_STRONG, F_PY, F_MG, F_FIXW, F_REL, F_WANTW, F_LP, F_BTF, F_BTB,
 F_MW, F_MH, F_MDG, F_MMV, F_MTN) = range(16)
NF = 16
# ---- 打点の数（int）
(I_HANDS, I_GID, I_ACC, I_FIXANY, I_FH0, I_FH1, I_FX0, I_FY0, I_FD0, I_FX1, I_FY1, I_FD1, I_MODS, I_BIG, I_SPREAD,
 I_WANT, I_FPOS, I_FXM, I_EBACK, I_ER0, I_ER1, I_HFSAME, I_CYL0, I_CYL1) = range(24)
NI = 24

# ---- 方針の数（float）
_SKEYS = ('noise', 'w_repeat', 'w_same_hand', 'w_fast', 'reset_gap', 'w_reset', 'w_first_up', 'w_accent', 'w_top_again',
          'w_inline', 'w_stair', 'w_shrado', 'w_handclap', 'w_stack_col', 'w_mirror', 'w_mixed', 'w_cross_dyn', 'w_theme_cell',
          'w_theme_dir', 'w_theme_skip', 'w_fix', 'w_pitch', 'w_left_fast', 'left_fast_s', 'w_hand_tech', 'w_ho_mirror', 'w_ho_lead',
          'w_echo', 'w_echo_want', 'w_echo_phase', 'w_loop', 'w_erun', 'w_ho_want')
(S_NOISE, S_REPEAT, S_SAMEH, S_FAST, S_RGAP, S_RESET, S_FIRSTUP, S_ACCENT, S_TOPAGAIN, S_INLINE, S_STAIR, S_SHRADO, S_CLAP,
 S_STACK, S_MIRROR, S_MIXED, S_CROSS, S_TCELL, S_TDIR, S_TSKIP, S_FIX, S_PITCH, S_LFW, S_LFS, S_HTK, S_HOM, S_HOLEAD,
 S_ECHO, S_ECHOWANT, S_ECHOPH, S_LOOP, S_ERUN, S_HOWANT) = range(len(_SKEYS))
_N0 = len(_SKEYS)
# 割合の重みと目標・置き方の指示の重み・定数（べき乗の底は配列から読む）
(S_WR, S_WD, S_WC, S_WE, S_WS, S_WH, S_WW, S_WK, S_WALT, S_TE, S_TS, S_TW, S_TALT, S_USEH, S_USEW, S_USEK,
 S_MODW, S_MODH, S_MODD, S_MODM, S_MODT, S_FOUR, S_ANOTE, S_AMOVE, S_AALT, S_APAIR, S_PAIRS) = range(_N0, _N0 + 27)
S_TR, S_TD, S_TC, S_TH, S_TK = _N0 + 27, _N0 + 30, _N0 + 33, _N0 + 37, _N0 + 41
NS = _N0 + 53

_ANG = np.array(F._ANG, dtype=np.int64)                       # 8×8
_MIR = np.array([F.MIRROR_D[d] for d in range(9)], dtype=np.int64)
_DSX = np.array([F.DIR_SPACE[d][0] for d in range(8)], dtype=np.int64)
_DSY = np.array([F.DIR_SPACE[d][1] for d in range(8)], dtype=np.int64)
_DCL = np.array([F.dir_class(d) for d in range(9)], dtype=np.int64)
_HYP = np.array([[math.hypot(dx, dy) for dy in range(-2, 3)] for dx in range(-3, 4)])   # 置き方の指示の移動（x の差 +3・y の差 +2）
_RXA = np.array(F._RX, dtype=np.int64)

_U = np.uint64
_C1, _C2, _C3 = _U(0x9E3779B97F4A7C15), _U(0xBF58476D1CE4E5B9), _U(0x94D049BB133111EB)
_S30, _S27, _S31, _S11 = _U(30), _U(27), _U(31), _U(11)
_TWO_M53 = 1.0 / (1 << 53)
_FNV = _U(0x100000001B3)
_FNV0 = _U(0xCBF29CE484222325)

_TABLES = {}   # 方針の数ごとの表（候補・振りの入り口までの移動の表）


# ---------------------------------------------------------------- 小さな部品

@njit(cache=True)
def _parity(c, d):
    if d == 1 or d == 6 or d == 7:
        return 0
    if d == 0 or d == 4 or d == 5:
        return 1
    if d == 2:
        return 0 if c == 1 else 1
    if d == 3:
        return 0 if c == 0 else 1
    return -1


@njit(cache=True)
def _mix64(z):
    z = z + _C1
    z = (z ^ (z >> _S30)) * _C2
    z = (z ^ (z >> _S27)) * _C3
    return z ^ (z >> _S31)


@njit(cache=True)
def _jitter(key, h, q, x, y, d):
    small = _U(h | (q << 1) | (x << 2) | (y << 4) | (d << 6))
    return float(_mix64(key ^ small) >> _S11) * _TWO_M53


@njit(cache=True)
def _tf(dt, four):
    """角度の減点の間の倍率（間が 0.25 秒より空くと BeatLeader と同じ割合で軽くなる）。底 four（4.0）は呼ぶ側が配列から渡す: 定数の 4 だと
    LLVM が 4^x を exp2(2x) に書き換え、Python（C ランタイムの pow）と最後の桁が違った（tests/test_flow_nb.py）"""
    return 1.0 if dt <= 0.25 else four ** (0.25 - dt)


@njit(cache=True)
def _same_hand_k(gap):
    """同じ手が続く減点の倍率（間が短いほど重い。手元の譜面では 1/2 拍以内で 18%・1拍前後で 3割ほど同じ手が続く）"""
    return 1.0 if gap < 0.6 else 0.5 if gap < 1.2 else 0.15


@njit(cache=True)
def _mods_cost(ef, x, y, d, par, px, py, pd, S):
    """意思入れの置き方の指示（区間の中の打点だけ・Event.mods）の減点（負＝ごほうび）。大きさは w_center・col_cost・w_diag と同じくらい
    （指示した区間ではっきり変わるが、振りの交互・手拍子形などの減点には勝たない）。mods の無い打点には何も足さない"""
    c = 0.0
    v = ef[F_MW]   # 横の広がり: −1＝内側の 2 列に寄せる・+1＝外側の列まで
    if v != 0.0:
        c += S[S_MODW] * (1.0 if (x == 0 or x == 3) else 0.0) * (1.0 if v < 0 else -0.7)
    v = ef[F_MH]   # 上の段を減らす・増やす
    if v != 0.0:
        c += S[S_MODH] * (1.0 if y == 2 else 0.0) * (1.0 if v < 0 else -0.8)
    v = ef[F_MDG]   # 斜めの振りを減らす・増やす
    if v != 0.0:
        c += S[S_MODD] * (1.0 if (d == 4 or d == 5 or d == 6 or d == 7) else 0.0) * (1.0 if v < 0 else -0.8)
    if par >= 0:
        v = ef[F_MMV]   # 1 振りごとの腕の移動を小さく・大きく（+2 はもっと）
        if v != 0.0:
            dist = _HYP[x - px + 3, y - py + 2]
            c += S[S_MODM] * dist * (1.0 if v < 0 else -0.6 * v)
        v = ef[F_MTN]   # −1＝真上・真下の素直な往復（45° 曲げを減点）・+1＝45° 曲げる振りを増やす
        if v != 0.0:
            dev = 180 - _ANG[pd, d]
            if 22 < dev <= 67:
                c += S[S_MODT] * (1.0 if v < 0 else -0.8)
    return c


# ---------------------------------------------------------------- 先読み

@njit(cache=True)
def _look_tables(EF, EI, S, has_gap):
    """決めたノーツ（Event.fix）の先読み: ビームを絞る時に、この先の決めたノーツで振りの向き（振り下ろし・振り上げ）や手が合わなくなる
    見込みの減点を足す（並べ替えだけ・点数には入れない）。決めた所に着いてから減点が出ても、その前で手の割り振りを変えた候補は
    もうビームから落ちている（曲C の同じ振りで、片方の手の向きが逆のまま横向きに逃げた）。
    後ろから1回たどって、状態（左手の最後の振りの向き・右手・最後の片手の手・その手の片手の打点の続いた数）ごとに「ここから先で決めた
    ノーツに合わせる一番安い減点」を出しておく（片手の打点はどちらの手でも打てて、同じ手が続くと ws・決めたノーツと向きが逆なら 2w・
    手が違えば 3w）。最初は先の打点の手の割り振りを全部並べていたが、両手の多い所で数が増えすぎて切り詰め、合う割り振りを落として
    逆効果になった。
    振りの順のやり直し（その手の前の振りから reset_gap 秒以上なら同じ振りを続けてよい・減点 w_reset）も見込む。手が空いた長さは
    「最後の片手の打点が同じ手で続いた数」から分かる（その間もう片方の手は振っていない）。前はやり直しを見込まず、片方の手だけ振りの順が
    ずれた状態は二度と直せないとみていた（2026-11-10）。前の譜面が先でやり直していると（こだまの右手の拍 246→249.5・その間は左手の片手の
    打点が 4 つ）、そこから後ろに合わせるために、手前の休み（拍 138→141）で片方の手の振りの順をやり直し、その間の拍 146〜246（同じ振りの
    手本を含む）を全部逆の向きにした（点数も 3 割高かった）。手が空いたかを数えずに「前の gap 秒が全部片手ならやり直せる」とみる甘い見込みは、
    11 曲で NLM の振りの警告が 11 → 24 に増えた。
    → (T[j, pl, pr, cur, r], R[j], W[j], low[j])。pl・pr: 0＝F・1＝B・2＝まだ振っていない。cur: 0＝両手・1＝左・2＝右。
    W[j]＝打点 j の前 gap 秒の中の打点の数（もう片方の手が r 打点前から振っていない時、r ≥ W[j] なら空いた長さが gap 以上）・R[j]＝続いた数の上限"""
    n = EF.shape[0]
    gap, wr, w, ws = S[S_RGAP], S[S_RESET], S[S_FIX], S[S_SAMEH]
    W = np.zeros(n + 1, dtype=np.int64)
    if has_gap:
        lo = 0
        for j in range(n):
            t0 = EF[j, F_SEC] - gap + 1e-9
            while lo < j and EF[lo, F_SEC] <= t0:
                lo += 1
            W[j] = j - lo
    R = np.ones(n + 1, dtype=np.int64)
    if has_gap:
        for j in range(n + 1):
            R[j] = max(1, W[j])
    rmax = 1
    for j in range(n + 1):
        rmax = max(rmax, R[j])
    T = np.zeros((n + 1, 3, 3, 3, rmax + 1))
    low = np.zeros(n + 1)
    qs = np.zeros(2, dtype=np.int64)
    cs = np.zeros(2)
    ql = np.zeros(2, dtype=np.int64)
    cl = np.zeros(2)
    qr = np.zeros(2, dtype=np.int64)
    cr = np.zeros(2)
    for j in range(n - 1, -1, -1):
        Rn = R[j + 1]
        near = has_gap and W[j] == 0
        fixany = EI[j, I_FIXANY] == 1
        wfix = EF[j, F_FIXW]
        hands = EI[j, I_HANDS]
        tg = np.full(2, -1, dtype=np.int64)
        has = np.zeros(2, dtype=np.int64)
        if fixany:
            for h in range(2):
                if EI[j, I_FH0 + h] == 1:
                    has[h] = 1
                    tg[h] = _parity(h, EI[j, I_FD0 + 3 * h])
        best_all = 1e300
        for cur in range(3):   # 0＝−1・1＝左・2＝右
            rlo, rhi = (0, 0) if cur == 0 else (1, R[j])
            for r in range(rlo, rhi + 1):
                idle_l = has_gap and (near or (cur == 2 and r >= W[j]))
                idle_r = has_gap and (near or (cur == 1 and r >= W[j]))
                for pl in range(3):
                    for pr in range(3):
                        if hands == 2:
                            nl = _swing(pl, tg[0], idle_l, 2 * wfix, wr, ql, cl)
                            nr = _swing(pr, tg[1], idle_r, 2 * wfix, wr, qr, cr)
                            best = 1e300
                            for a in range(nl):
                                for b in range(nr):
                                    v = cl[a] + cr[b] + T[j + 1, ql[a], qr[b], 0, 0]
                                    if v < best:
                                        best = v
                        else:
                            best = 1e300
                            for h in range(2):
                                c0 = (ws if h + 1 == cur else 0.0) + (3 * wfix if (fixany and has[h] == 0) else 0.0)
                                r2 = (r + 1 if h + 1 == cur else 1)
                                if r2 > Rn:
                                    r2 = Rn
                                if h == 0:
                                    k = _swing(pl, tg[0], idle_l, 2 * wfix, wr, qs, cs)
                                else:
                                    k = _swing(pr, tg[1], idle_r, 2 * wfix, wr, qs, cs)
                                for a in range(k):
                                    if h == 0:
                                        v = c0 + cs[a] + T[j + 1, qs[a], pr, 1, r2]
                                    else:
                                        v = c0 + cs[a] + T[j + 1, pl, qs[a], 2, r2]
                                    if v < best:
                                        best = v
                        T[j, pl, pr, cur, r] = best
                        if best < best_all:
                            best_all = best
        low[j] = best_all
    return T, R, W, low


@njit(cache=True)
def _swing(p, tgt, idle, wf2, wr, qo, co):
    """手（最後の振り p・2＝まだ）がこの打点で振る時の (次の向き, 減点) を qo・co に → 数"""
    if p == 2:
        if tgt >= 0:
            qo[0], co[0] = tgt, 0.0
            return 1
        qo[0], co[0], qo[1], co[1] = 0, 0.0, 1, 0.0
        return 2
    q = 1 - p
    qo[0] = q
    co[0] = wf2 if (tgt >= 0 and q != tgt) else 0.0
    if idle:
        qo[1] = p
        co[1] = wr + (wf2 if (tgt >= 0 and p != tgt) else 0.0)
        return 2
    return 1


# ---------------------------------------------------------------- 候補の減点（手の状態からの全部の候補・減点の小さい順に並べるのは呼ぶ側）

@njit(cache=True)
def _costs(h, hs, hsec, ei, ef, eir, cyr, S, SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG, ETS, ETN, JT,
           wtc, wtd, oc, oq, oi, onk, osame):
    par, px, py, pd = hs[HQ], hs[HX], hs[HY], hs[HD]
    prun, pgid, pk, ptop = hs[HRUN], hs[HGID], hs[HNK], hs[HTOP]
    sec = ef[F_SEC]
    gid = eir[I_GID]
    dt = sec - hsec
    cyl = eir[I_CYL0 + h]
    k0 = pk if pgid == gid else 0
    nq = 0
    qv0, qv1 = 0, 0
    qc0, qc1 = 0.0, 0.0
    if par < 0:
        qv0, qc0, qv1, qc1, nq = 0, 0.0, 1, S[S_FIRSTUP], 2
    else:
        qv0, qc0, nq = 1 - par, 0.0, 1
        if dt >= S[S_RGAP]:
            qv1, qc1, nq = par, S[S_RESET], 2
    fast = 0.0
    mg = ef[F_MG]
    if par >= 0 and dt < mg:
        fast = S[S_FAST] * (mg - dt) / mg * 10
    tf = _tf(dt, S[S_FOUR])
    spd = min(3.0, max(0.3, 0.35 / max(dt, 1e-3)))
    if eir[I_HFSAME] == 1:
        hf = 1.0
    else:
        hf = 1.0 + S[S_HTK] if h == 0 else 1.0 - S[S_HTK]
    shr = dt <= 0.25
    rep = S[S_REPEAT] * max(0, prun)
    mods = eir[I_MODS] == 1
    bmf = 0.6 if eir[I_BIG] == 1 else 1.0
    wtop, wskip, wshr = S[S_TOPAGAIN], S[S_TSKIP], S[S_SHRADO]
    cnt = 0
    for qi in range(nq):
        q = qv0 if qi == 0 else qv1
        qc = qc0 if qi == 0 else qc1
        has_tt, skip, nk, jm = False, False, 0, 0
        if cyl > 0:
            j = k0 if _parity(h, cyr[h, k0 % cyl, 2]) == q else k0 + 1
            jm = j % cyl
            has_tt = True
            skip = j != k0 and pgid == gid
            nk = j + 1
        topq = q == 1 and ptop == 1
        tx, ty, td = cyr[h, jm, 0], cyr[h, jm, 1], cyr[h, jm, 2]
        for i in range(SO_N[h, q]):
            x, y, d = SO_X[h, q, i], SO_Y[h, q, i], SO_D[h, q, i]
            c = SO_C0[h, q, i] + qc + fast
            same = -1
            if par < 0:
                for t in range(ETN[h, q, i]):
                    c += ETS[h, q, i, t]
                if mods:
                    c += _mods_cost(ef, x, y, d, par, px, py, pd, S)
                if topq and y == 2:
                    c += wtop
                if has_tt:
                    c += wtc * (abs(x - tx) + abs(y - ty)) + wtd * _ANG[d, td] / 45
                    if skip:
                        c += wskip
                c += JT[h, q, i]
            else:
                w = G_W[h, q, px, py, pd, i]
                wh = G_WH[h, q, px, py, pd, i]
                same = G_SAME[h, q, px, py, pd, i]
                shg = G_SHG[h, q, px, py, pd, i] == 1
                if not mods and not topq:
                    if hf == 1.0:
                        if not math.isnan(w):
                            c += tf * w
                        c += wh * spd * bmf
                    else:
                        if not math.isnan(w):
                            c += tf * w * hf
                        c += wh * spd * bmf * hf
                    if shg and shr:
                        c += wshr
                    if same == 1:
                        c += rep
                    for t in range(ETN[h, q, i]):
                        c += ETS[h, q, i, t]
                    if has_tt:
                        c += wtc * (abs(x - tx) + abs(y - ty)) + wtd * _ANG[d, td] / 45
                        if skip:
                            c += wskip
                    c += JT[h, q, i]
                else:
                    if not math.isnan(w):
                        c += tf * w if hf == 1.0 else tf * w * hf
                    c += wh * spd * bmf if hf == 1.0 else wh * spd * bmf * hf
                    if shg and shr:
                        c += wshr
                    if same == 1:
                        c += rep
                    for t in range(ETN[h, q, i]):
                        c += ETS[h, q, i, t]
                    if mods:
                        c += _mods_cost(ef, x, y, d, par, px, py, pd, S)
                    if topq and y == 2:
                        c += wtop
                    if has_tt:
                        c += wtc * (abs(x - tx) + abs(y - ty)) + wtd * _ANG[d, td] / 45
                        if skip:
                            c += wskip
                    c += JT[h, q, i]
            oc[cnt], oq[cnt], oi[cnt], onk[cnt], osame[cnt] = c, q, i, nk, same
            cnt += 1
    return cnt


# ---------------------------------------------------------------- 候補の表（キー → 番号・Python の辞書と同じ順）

@njit(cache=True)
def _find(kb, ck, ht_stamp, ht_idx, stamp, mask):
    """キー kb の番号（無ければ −1）と、入れるならその枠 → (番号, 枠)"""
    hsh = _FNV0
    for t in range(KEY):
        hsh = (hsh ^ _U(kb[t] + 2)) * _FNV
    s = np.int64(_mix64(hsh) & _U(mask))
    while ht_stamp[s] == stamp:
        ci = ht_idx[s]
        same = True
        for t in range(KEY):
            if ck[ci, t] != kb[t]:
                same = False
                break
        if same:
            return ci, s
        s = (s + 1) & mask
    return -1, s


# ---------------------------------------------------------------- 道をさかのぼる（段 s＝打点 s に入る時のビーム・段 ei が今のビーム）

@njit(cache=True)
def _anc(hp, ei, bi, k):
    """k 打点前の打点の後の状態 → (段, 番号)（段 ei の番号 bi が今の候補）。道が尽きたら (−1, −1)"""
    step, idx = ei, bi
    for _ in range(1, k):
        p = hp[step, idx]
        if p < 0:
            return -1, -1
        step -= 1
        idx = p
    return step, idx


@njit(cache=True)
def _loop_target(hp, hnp, hpl, EF, ei, bi, h, lp):
    step, idx, k, seen = ei, bi, 1, 0
    while k <= 24:
        b = EF[ei - k, F_BEAT] if ei - k >= 0 else -1e9
        if b < lp - 1e-6:
            return -1, 0, 0
        for t in range(hnp[step, idx]):
            if hpl[step, idx, t, 0] == h:
                seen += 1
                if seen == 2:
                    return hpl[step, idx, t, 1], hpl[step, idx, t, 2], hpl[step, idx, t, 3]
        p = hp[step, idx]
        if p < 0:
            return -1, 0, 0
        step -= 1
        idx = p
        k += 1
    return -1, 0, 0


# ---------------------------------------------------------------- 直近の割合（目標の割合の追い方は flow.py の A_NOTE の説明）

@njit(cache=True)
def _next_ema(e, x, y, d, same, S):
    k = 1 - S[S_ANOTE]
    a = S[S_ANOTE]
    o0, o1, o2 = e[E_ROW], e[E_ROW + 1], e[E_ROW + 2]
    e[E_ROW], e[E_ROW + 1], e[E_ROW + 2] = o0 * k, o1 * k, o2 * k
    e[E_ROW + y] = (o0 if y == 0 else o1 if y == 1 else o2) * k + a
    dc = _DCL[d]
    o0, o1, o2 = e[E_DIR], e[E_DIR + 1], e[E_DIR + 2]
    e[E_DIR], e[E_DIR + 1], e[E_DIR + 2] = o0 * k, o1 * k, o2 * k
    e[E_DIR + dc] = (o0 if dc == 0 else o1 if dc == 1 else o2) * k + a
    ox = e[E_COL + x]
    for i in range(4):
        e[E_COL + i] = e[E_COL + i] * k
    e[E_COL + x] = ox * k + a
    cen = (x == 1 or x == 2) and y == 1
    e[E_CEN] = e[E_CEN] * k + (a if cen else 0.0)
    if same >= 0:
        e[E_STILL] = e[E_STILL] * (1 - S[S_AMOVE]) + (S[S_AMOVE] if same == 1 else 0.0)


@njit(cache=True)
def _hw_ema(e, h, x, y, S):
    """手から見た列・手から見たマスの直近の割合（手ごとに別々に数える）。手から見た列を両手まとめて1つで追うと、後から外へ出る手（多くは
    右手）だけが「両手を同時に外へ」の減点で内に引っ込み、左手は外のまま（自分の外が左 53%・右 42%）になった＝手ごとに目標へ寄せる"""
    k = 1 - S[S_ANOTE]
    a = S[S_ANOTE]
    r = x if h == 1 else 3 - x
    b = E_HC + 4 * h
    o = e[b + r]
    for i in range(4):
        e[b + i] = e[b + i] * k
    e[b + r] = o * k + a
    j = r * 3 + y
    b = E_KC + 12 * h
    o = e[b + j]
    for i in range(12):
        e[b + i] = e[b + i] * k
    e[b + j] = o * k + a


# ---------------------------------------------------------------- 本体

@njit(cache=True)
def _search(EF, EI, CY, JK, S, SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG, PF,
            ema0, ihs, isec, ilast, LT, LR, has_look, beam):
    n = EF.shape[0]
    B = beam
    hp = np.full((n + 1, B), -1, dtype=np.int64)
    hnp = np.zeros((n + 1, B), dtype=np.int64)
    hpl = np.zeros((n + 1, B, 2, 4), dtype=np.int64)
    hq = np.zeros((n + 1, B, 2), dtype=np.int64)
    # 今のビームと次のビーム（入れ替えて使う）
    b_tot = np.zeros(B)
    b_hs = np.zeros((B, 2, NH), dtype=np.int64)
    b_sec = np.zeros((B, 2))
    b_last = np.zeros(B, dtype=np.int64)
    b_ema = np.zeros((B, NE))
    n_tot = np.zeros(B)
    n_hs = np.zeros((B, 2, NH), dtype=np.int64)
    n_sec = np.zeros((B, 2))
    n_last = np.zeros(B, dtype=np.int64)
    n_ema = np.zeros((B, NE))
    nb = 1
    b_hs[0] = ihs
    b_sec[0] = isec
    b_last[0] = ilast
    b_ema[0] = ema0
    # 候補
    M = max(B * 2 * 96, B * 144) + 8
    c_tot = np.zeros(M)
    c_hs = np.zeros((M, 2, NH), dtype=np.int64)
    c_sec = np.zeros((M, 2))
    c_h = np.zeros(M, dtype=np.int64)
    c_par = np.zeros(M, dtype=np.int64)
    c_np = np.zeros(M, dtype=np.int64)
    c_pl = np.zeros((M, 2, 4), dtype=np.int64)
    c_same = np.zeros((M, 2), dtype=np.int64)
    c_wide = np.zeros(M, dtype=np.int64)
    ck = np.zeros((M, KEY), dtype=np.int64)
    skey = np.zeros(M)
    cap = 1
    while cap < 2 * M:
        cap *= 2
    mask = cap - 1
    ht_stamp = np.zeros(cap, dtype=np.int64)
    ht_idx = np.zeros(cap, dtype=np.int64)
    kb = np.zeros(KEY, dtype=np.int64)
    # 候補の減点の置き場（2 つの振り × 48）
    oc = np.zeros(2 * 48)
    oq = np.zeros(2 * 48, dtype=np.int64)
    oi = np.zeros(2 * 48, dtype=np.int64)
    onk = np.zeros(2 * 48, dtype=np.int64)
    osame = np.zeros(2 * 48, dtype=np.int64)
    oc2 = np.zeros(2 * 48)
    oq2 = np.zeros(2 * 48, dtype=np.int64)
    oi2 = np.zeros(2 * 48, dtype=np.int64)
    onk2 = np.zeros(2 * 48, dtype=np.int64)
    osame2 = np.zeros(2 * 48, dtype=np.int64)
    ETS = np.zeros((2, 2, 48, 5))
    ETN = np.zeros((2, 2, 48), dtype=np.int64)
    JT = np.zeros((2, 2, 48))
    RC = np.zeros(3)
    DC = np.zeros(3)
    CC = np.zeros(4)
    HC = np.zeros((2, 4))
    PT = np.zeros((2, 12))
    ers = np.zeros(12)
    use_h, use_w, use_k = S[S_USEH] != 0.0, S[S_USEW] != 0.0, S[S_USEK] != 0.0
    use_hw = use_h or use_w or use_k
    lfw, lfs = S[S_LFW], S[S_LFS]
    for ei in range(n):
        ef = EF[ei]
        eir = EI[ei]
        cyr = CY[ei]
        sec = ef[F_SEC]
        gid = eir[I_GID]
        # 今のビームを道の控えに（段 ei）
        for bi in range(nb):
            hq[ei, bi, 0] = b_hs[bi, 0, HQ]
            hq[ei, bi, 1] = b_hs[bi, 1, HQ]
        mods = eir[I_MODS] == 1
        bm = eir[I_BIG] == 1
        wcross = S[S_CROSS] * (0.4 if bm else 1.0)
        spread = eir[I_SPREAD] == 1
        rl = ef[F_REL]
        eh = use_h and not spread and rl == 0.0
        ew = use_w and not spread
        ek = use_k and not spread and rl == 0.0
        if rl != 0.0:
            wtc, wtd = S[S_TCELL] * rl, S[S_TDIR] * rl
        else:
            wtc, wtd = S[S_TCELL], S[S_TDIR]
        # 打点だけで決まる候補ごとの減点の並び（拍・山の音・強い打点・歌の高さ・決めたノーツ・足す順）と揺らぎ
        jkey = JK[ei]
        for h in range(2):
            for q in range(2):
                bt = ef[F_BTF] if q == 0 else ef[F_BTB]
                for i in range(SO_N[h, q]):
                    x, y, d = SO_X[h, q, i], SO_Y[h, q, i], SO_D[h, q, i]
                    t = 0
                    if not math.isnan(bt):
                        ETS[h, q, i, t] = bt
                        t += 1
                    if eir[I_ACC] == 1:
                        ETS[h, q, i, t] = -(S[S_ACCENT] * ((1.0 if y == 2 else 0.0) + 0.5 * (1.0 if (x == 0 or x == 3) else 0.0)))
                        t += 1
                    if q == 1 and ef[F_STRONG] != 0.0:
                        ETS[h, q, i, t] = ef[F_STRONG]
                        t += 1
                    if not math.isnan(ef[F_PY]):
                        ETS[h, q, i, t] = S[S_PITCH] * abs(y - ef[F_PY])
                        t += 1
                    if eir[I_FIXANY] == 1:
                        wf = ef[F_FIXW]
                        if eir[I_FH0 + h] == 1:
                            fx, fy, fd = eir[I_FX0 + 3 * h], eir[I_FY0 + 3 * h], eir[I_FD0 + 3 * h]
                            if 0 <= fd <= 7:
                                ETS[h, q, i, t] = wf * (abs(x - fx) + abs(y - fy) + _ANG[d, fd] / 45)
                            else:
                                ETS[h, q, i, t] = wf * (abs(x - fx) + abs(y - fy))
                        else:
                            ETS[h, q, i, t] = wf * 3
                        t += 1
                    ETN[h, q, i] = t
                    JT[h, q, i] = _jitter(jkey, h, q, x, y, d) * S[S_NOISE]
        stamp = ei + 1
        m = 0
        want = eir[I_WANT]
        wantw = ef[F_WANTW]
        fpos = eir[I_FPOS]
        fxm = eir[I_FXM]
        eback = eir[I_EBACK]
        lp = ef[F_LP]
        has_lp = not math.isnan(lp)
        er0, er1 = eir[I_ER0], eir[I_ER1]
        for bi in range(nb):
            cost = b_tot[bi]
            last = b_last[bi]
            e = b_ema[bi]
            # 割合の減点の表（段・向きの種類・列・真ん中・同じマス・手から見た列・両手を同時に外へ・手から見たマス）。手から見た列・マスの
            # 減点は段・列の割合の表に前もって混ぜる（候補ごとの足し算を増やさない）
            ec = S[S_WE] * (e[E_CEN] - S[S_TE])
            es = S[S_WS] * (e[E_STILL] - S[S_TS])
            for i in range(3):
                RC[i] = S[S_WR] * (e[E_ROW + i] - S[S_TR + i])
            for i in range(3):
                DC[i] = S[S_WD] * (e[E_DIR + i] - S[S_TD + i])
            for i in range(4):
                CC[i] = S[S_WC] * (e[E_COL + i] - S[S_TC + i])
            EC, mEC, ES, mES = ec, -ec, es, -es
            if eh:
                for hh in range(2):
                    for i in range(4):
                        HC[hh, i] = S[S_WH] * (e[E_HC + 4 * hh + i] - S[S_TH + i])
            has_wd = ew
            WD = S[S_WW] * (e[E_WIDE] - S[S_TW]) if ew else 0.0
            has_pt = eh or ek
            if has_pt:
                for hh in range(2):
                    for x in range(4):
                        cxs = CC[x] + HC[hh, _RXA[hh, x]] if eh else CC[x] + 0.0
                        for y in range(3):
                            if ek:
                                jj = _RXA[hh, x] * 3 + y
                                PT[hh, x * 3 + y] = RC[y] + cxs + S[S_WK] * (e[E_KC + 12 * hh + jj] - S[S_TK + jj])
                            else:
                                PT[hh, x * 3 + y] = RC[y] + cxs + 0.0
            if eir[I_HANDS] == 1:
                # ---- 片手の打点（全部の候補・ビームの1件・手ごと）
                frole, fw, fmt_ok, fmt0, fmt1, fmt2, fmc_ok, fmc0, fmc1 = 0, -1, False, 0, 0, 0, False, 0, 0
                if fpos >= 0:
                    # 左右反転の受け渡し（Event.hoflex）: この候補の道での役（0＝受け渡しの外・1＝先の手の 1 振り目（手は決めない）・2＝続き）・
                    # 使いたい手・反転の狙い。始まりの打点の前に両手の直前の振りの向き（下・上）がそろっていれば始まりから、そろっていなければ
                    # 1 打点後ろから受け渡しにする（交互の並びでは 1 打点進むと必ずそろう＝後の手が先の手の反転を置ける）。人もそろう所は打点の
                    # 半分ほどで、反転はそろう所に置いている。場所を決め打ちすると 4〜6 割の所で位相が逆になり、反転を置けなかった。
                    # 先の手は 1 振り目で選ばれた手・後の手はその反対・後の手の振りは 2 打点前（相手の手の同じ順番の振り）の左右反転に寄せる。
                    # 段の 2 振り目は、次の段の 1 振り目（この段の 1 振り目の左右反転）のマスをあける
                    s0s, s0i = _anc(hp, ei, bi, fpos + 1)
                    if s0s >= 0:
                        lq, rq = hq[s0s, s0i, 0], hq[s0s, s0i, 1]
                        role = fpos - (0 if (lq >= 0 and lq == rq) else 1)
                        if 0 <= role < 2 * fxm:
                            if role == 0:
                                frole = 1   # 'lead'
                            else:
                                ls, li = _anc(hp, ei, bi, role)
                                if ls >= 0 and hnp[ls, li] == 1:
                                    lead = hpl[ls, li, 0, 0]
                                    hand = lead if (role // 2) % 2 == 0 else 1 - lead
                                    if role >= 2:
                                        ps, pi = _anc(hp, ei, bi, 2)
                                        if ps >= 0 and hnp[ps, pi] == 1 and hpl[ps, pi, 0, 0] == 1 - hand:
                                            fmt_ok = True
                                            fmt0, fmt1, fmt2 = 3 - hpl[ps, pi, 0, 1], hpl[ps, pi, 0, 2], _MIR[hpl[ps, pi, 0, 3]]
                                    if role % 2 == 1 and role + 1 < 2 * fxm:
                                        fmc_ok = True
                                        fmc0, fmc1 = 3 - hpl[ei, bi, 0, 1], hpl[ei, bi, 0, 2]
                                    frole, fw = 2, hand   # 'run'
                run_h = -1
                if er0 >= 0 and ei != er0:
                    # 前のセットを片手に（Event.erun）: この候補の道で使う手。1 番目の打点の前に両手の直前の振りの向きがそろっていれば 1 番目の手、
                    # そろっていなければ 1 番目は向きをそろえる打点にして 2 番目の手（後ろのセットの手は前のセットの手の反対＝向きがそろって
                    # いないと、どちらの手で始めても反転を置けない＝受け渡しと同じ）
                    s0s, s0i = _anc(hp, ei, bi, ei - er0 + 1)
                    if s0s >= 0:
                        lq, rq = hq[s0s, s0i, 0], hq[s0s, s0i, 1]
                        sync = lq < 0 or rq < 0 or lq == rq
                        f = er0 if sync else er1
                        if f >= 0 and ei != f:
                            rs, ri = _anc(hp, ei, bi, ei - f)
                            if rs >= 0 and hnp[rs, ri] == 1:
                                run_h = hpl[rs, ri, 0, 0]
                ec_hand, ect0, ect1, ect2 = -1, 0, 0, 0
                if eback > 0:   # 続けて左右反転: 1 セット前の同じ拍の打点（片手）の反対の手で、その左右反転に
                    es_, ei_ = _anc(hp, ei, bi, eback)
                    if es_ >= 0 and hnp[es_, ei_] == 1:
                        ec_hand = 1 - hpl[es_, ei_, 0, 0]
                        ect0, ect1, ect2 = 3 - hpl[es_, ei_, 0, 1], hpl[es_, ei_, 0, 2], _MIR[hpl[es_, ei_, 0, 3]]
                for h in range(2):
                    o = 1 - h
                    hs = b_hs[bi, h]
                    hsec = b_sec[bi, h]
                    osec = b_sec[bi, o]
                    altc = 0.0
                    mt_ok, mt0, mt1, mt2 = False, 0, 0, 0
                    mc_ok, mc0, mc1 = False, 0, 0
                    lt_ok, lt0, lt1, lt2 = False, 0, 0, 0
                    if has_lp:   # 短い往復: 同じ手の 2 つ前の置き方（手の向きは交互なので 2 つ前は必ず同じ向きの振り）
                        lt0, lt1, lt2 = _loop_target(hp, hnp, hpl, EF, ei, bi, h, lp)
                        lt_ok = lt0 >= 0
                    if ec_hand >= 0:   # 続けて左右反転（同じ手の続き・速い続きの減点は掛けない＝反転の形のまま）
                        if h == ec_hand:
                            if hs[HQ] >= 0 and _parity(h, ect2) == hs[HQ]:
                                altc = S[S_ECHOPH]   # 振りの向きの位相が逆＝反転を置けない
                            else:
                                mt_ok, mt0, mt1, mt2 = True, ect0, ect1, ect2
                        else:
                            altc = S[S_ECHOWANT] + (S[S_SAMEH] * _same_hand_k(sec - hsec) if last == h else 0.0)
                    elif want >= 0:   # 受け渡し: 使いたい手（同じ手の続き・速い続きの減点は掛けない）
                        altc = 0.0 if h == want else wantw
                    elif run_h >= 0:   # 前のセットを片手に: 最初の打点と同じ手（同じ手の続き・速い続きの減点は掛けない）
                        altc = 0.0 if h == run_h else S[S_ERUN]
                    elif frole == 2:   # 左右反転の受け渡しの続き: 反転の狙い（2 段目から）・次の段のマスをあける（段の 2 振り目）
                        if h == fw:
                            altc = 0.0
                            mc_ok, mc0, mc1 = fmc_ok, fmc0, fmc1
                            if fmt_ok and not (hs[HQ] >= 0 and _parity(h, fmt2) == hs[HQ]):
                                mt_ok, mt0, mt1, mt2 = True, fmt0, fmt1, fmt2
                        else:   # 違う手: 使いたい手の減点＋ふだんの同じ手の続きの減点（無いと同じ手が 3 回続いて崩れた）
                            altc = S[S_HOWANT]
                            if last >= 0 and last == h:
                                altc += S[S_SAMEH] * _same_hand_k(sec - hsec)
                    else:
                        if last >= 0:
                            ea = S[S_WALT] * (e[E_ALT] - S[S_TALT])
                            altc = (ea if h != last else -ea) + (S[S_SAMEH] * _same_hand_k(sec - hsec) if last == h else 0.0)
                        if lfw != 0.0 and h == 0 and hs[HQ] >= 0 and sec - hsec < lfs and (b_hs[bi, o, HQ] < 0 or osec <= hsec + 1e-6):
                            altc += lfw * (lfs - (sec - hsec)) / lfs   # 片手だけの速い続きは右手に（w_left_fast）
                        if frole == 1 and h == 0:
                            altc += S[S_HOLEAD]   # 反転の受け渡しは右から始める方を少し好む
                    ox, oy, od = b_hs[bi, o, HX], b_hs[bi, o, HY], b_hs[bi, o, HD]
                    has_o = ox >= 0
                    sx, sy = -100, -100
                    if has_o and 0 < sec - osec < 0.15 and 0 <= od <= 7:   # もう片方の手が直前に振り抜けたマス（hitboxStair）
                        sx, sy = ox + _DSX[od], oy + _DSY[od]
                    inl_ok = has_o and sec - osec < 0.35   # もう片方の手が直前に置いたマス（hitboxInline）
                    inl = S[S_INLINE] * (1.0 if sec - osec < 0.2 else 0.3) if inl_ok else 0.0
                    crs = has_o and sec - osec < 0.5   # もう片方の手の最近の位置をまたぐ
                    # 両手を同時に外へ: もう片方の手が PAIR_S 秒以内に自分の外（左手は列 0・右手は列 3）にいて、この手も自分の外に置く
                    pair = has_o and sec - osec <= S[S_PAIRS]   # 組がある（割合を数える）
                    wx = -100
                    if pair and ox == (0 if h == 1 else 3):
                        wx = 3 if h == 1 else 0
                    wmt = S[S_ECHO] if ec_hand >= 0 else S[S_HOM]
                    simple = not mt_ok and not mc_ok and not lt_ok
                    cnt = _costs(h, hs, hsec, ei, ef, eir, cyr, S, SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG,
                                 ETS, ETN, JT, wtc, wtd, oc, oq, oi, onk, osame)
                    order = np.argsort(oc[:cnt], kind='mergesort')
                    prun, ptop = hs[HRUN], hs[HTOP]
                    for oo in range(cnt):
                        u = order[oo]
                        c, q, i, same = oc[u], oq[u], oi[u], osame[u]
                        x, y, d = SO_X[h, q, i], SO_Y[h, q, i], SO_D[h, q, i]
                        cen = (x == 1 or x == 2) and y == 1
                        if not has_pt:
                            v = RC[y] + DC[_DCL[d]] + CC[x] + (EC if cen else mEC)
                        else:
                            v = PT[h, x * 3 + y] + DC[_DCL[d]] + (EC if cen else mEC)
                        if same >= 0:
                            v = v + (ES if same == 1 else mES)
                        tot = cost + c + altc + v
                        if x == sx and y == sy:
                            tot += S[S_STAIR]
                        if inl_ok and x == ox and y == oy:
                            tot += inl
                        if crs and ((x > ox) if h == 0 else (x < ox)):
                            tot += wcross
                        if has_wd and x == wx:
                            tot += WD
                        if not simple:
                            if mt_ok:   # 受け渡し・続けて左右反転: 相手の置き方の左右反転からのずれ
                                tot += wmt * (abs(x - mt0) + abs(y - mt1) + _ANG[d, mt2] / 45)
                            elif mc_ok and x == mc0 and y == mc1:   # 受け渡しの反転: 次の段の反転のマスをふさぐ
                                tot += S[S_HOM]
                            if lt_ok:   # 短い往復: 2 つ前の振りからのずれ
                                tot += S[S_LOOP] * (abs(x - lt0) + abs(y - lt1) + _ANG[d, lt2] / 45)
                        nrun = prun + 1 if same == 1 else 0
                        ntop = (1 if y == 2 else 0) if q == 1 else ptop
                        # キー（手の状態の秒の外の項目）: 同じキーは点数の小さい方・同点は先に数えた方
                        bL = 0 if h == 0 else NH
                        bO = NH if h == 0 else 0
                        kb[bL + HQ], kb[bL + HX], kb[bL + HY], kb[bL + HD] = q, x, y, d
                        kb[bL + HEI], kb[bL + HRUN], kb[bL + HGID], kb[bL + HNK], kb[bL + HTOP] = ei, nrun, gid, onk[u], ntop
                        for t in range(NH):
                            kb[bO + t] = b_hs[bi, o, t]
                        kb[2 * NH] = h
                        ci, slot = _find(kb, ck, ht_stamp, ht_idx, stamp, mask)
                        if ci < 0:
                            ci = m
                            m += 1
                            ht_stamp[slot] = stamp
                            ht_idx[slot] = ci
                            for t in range(KEY):
                                ck[ci, t] = kb[t]
                        elif not (c_tot[ci] > tot):
                            continue
                        c_tot[ci] = tot
                        for t in range(NH):
                            c_hs[ci, h, t] = kb[bL + t]
                            c_hs[ci, o, t] = b_hs[bi, o, t]
                        c_sec[ci, h] = sec
                        c_sec[ci, o] = osec
                        c_h[ci] = h
                        c_par[ci] = bi
                        c_np[ci] = 1
                        c_pl[ci, 0, 0], c_pl[ci, 0, 1], c_pl[ci, 0, 2], c_pl[ci, 0, 3] = h, x, y, d
                        c_same[ci, 0] = same
                        c_wide[ci] = (1 if x == wx else 0) if pair else -1
            else:
                # ---- 両手同時: 左右それぞれ減点の小さい 12 の組
                etl_ok = False
                etl0, etl1, etl2, etr0, etr1, etr2 = 0, 0, 0, 0, 0, 0
                if eback > 0:   # 続けて左右反転（両手）: 左手は 1 セット前の右手の反転・右手は左手の反転に
                    es_, ei_ = _anc(hp, ei, bi, eback)
                    if es_ >= 0 and hnp[es_, ei_] == 2:
                        a0, a1 = hpl[es_, ei_, 0, 0], hpl[es_, ei_, 1, 0]
                        if a0 != a1:
                            li = 0 if a0 == 0 else 1
                            ri = 1 - li
                            etl_ok = True
                            etl0, etl1, etl2 = 3 - hpl[es_, ei_, ri, 1], hpl[es_, ei_, ri, 2], _MIR[hpl[es_, ei_, ri, 3]]
                            etr0, etr1, etr2 = 3 - hpl[es_, ei_, li, 1], hpl[es_, ei_, li, 2], _MIR[hpl[es_, ei_, li, 3]]
                cntr = _costs(1, b_hs[bi, 1], b_sec[bi, 1], ei, ef, eir, cyr, S, SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG,
                              ETS, ETN, JT, wtc, wtd, oc2, oq2, oi2, onk2, osame2)
                ordr = np.argsort(oc2[:cntr], kind='mergesort')
                nr = min(12, cntr)
                for k2 in range(nr):
                    u = ordr[k2]
                    x, y, d = SO_X[1, oq2[u], oi2[u]], SO_Y[1, oq2[u], oi2[u]], SO_D[1, oq2[u], oi2[u]]
                    cen = (x == 1 or x == 2) and y == 1
                    if not has_pt:
                        v = RC[y] + DC[_DCL[d]] + CC[x] + (EC if cen else mEC)
                    else:
                        v = PT[1, x * 3 + y] + DC[_DCL[d]] + (EC if cen else mEC)
                    ers[k2] = v if osame2[u] < 0 else v + (ES if osame2[u] == 1 else mES)
                cntl = _costs(0, b_hs[bi, 0], b_sec[bi, 0], ei, ef, eir, cyr, S, SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG,
                              ETS, ETN, JT, wtc, wtd, oc, oq, oi, onk, osame)
                ordl = np.argsort(oc[:cntl], kind='mergesort')
                nl = min(12, cntl)
                lh, rh = b_hs[bi, 0], b_hs[bi, 1]
                for k1 in range(nl):
                    u1 = ordl[k1]
                    cl, ql_, il = oc[u1], oq[u1], oi[u1]
                    xl, yl, dl = SO_X[0, ql_, il], SO_Y[0, ql_, il], SO_D[0, ql_, il]
                    cenl = (xl == 1 or xl == 2) and yl == 1
                    if not has_pt:
                        el = RC[yl] + DC[_DCL[dl]] + CC[xl] + (EC if cenl else mEC)
                    else:
                        el = PT[0, xl * 3 + yl] + DC[_DCL[dl]] + (EC if cenl else mEC)
                    sl = osame[u1]
                    if sl >= 0:
                        el = el + (ES if sl == 1 else mES)
                    a = cost + cl
                    nrunl = lh[HRUN] + 1 if sl == 1 else 0
                    ntopl = (1 if yl == 2 else 0) if ql_ == 1 else lh[HTOP]
                    for k2 in range(nr):
                        u2 = ordr[k2]
                        cr, qr_, ir = oc2[u2], oq2[u2], oi2[u2]
                        xr, yr, dr = SO_X[1, qr_, ir], SO_Y[1, qr_, ir], SO_D[1, qr_, ir]
                        if xl > xr or (xl == xr and yl == yr):
                            continue
                        tot = a + cr + el + ers[k2]
                        if PF[xl, yl, dl, xr, yr, dr, 0]:
                            tot += S[S_STACK]
                        if PF[xl, yl, dl, xr, yr, dr, 1]:
                            tot += S[S_MIRROR]
                        if PF[xl, yl, dl, xr, yr, dr, 2]:
                            tot += S[S_MIXED]
                        if PF[xl, yl, dl, xr, yr, dr, 3]:
                            tot += S[S_CLAP]
                        if PF[xl, yl, dl, xr, yr, dr, 4]:
                            tot += S[S_CLAP]
                        if etl_ok:
                            tot += S[S_ECHO] * (abs(xl - etl0) + abs(yl - etl1) + _ANG[dl, etl2] / 45
                                                + abs(xr - etr0) + abs(yr - etr1) + _ANG[dr, etr2] / 45)
                        wide = xl == 0 and xr == 3
                        if has_wd and wide:
                            tot += WD
                        sr = osame2[u2]
                        nrunr = rh[HRUN] + 1 if sr == 1 else 0
                        ntopr = (1 if yr == 2 else 0) if qr_ == 1 else rh[HTOP]
                        kb[HQ], kb[HX], kb[HY], kb[HD], kb[HEI], kb[HRUN], kb[HGID], kb[HNK], kb[HTOP] = \
                            ql_, xl, yl, dl, ei, nrunl, gid, onk[u1], ntopl
                        kb[NH + HQ], kb[NH + HX], kb[NH + HY], kb[NH + HD], kb[NH + HEI], kb[NH + HRUN], kb[NH + HGID], kb[NH + HNK], kb[NH + HTOP] = \
                            qr_, xr, yr, dr, ei, nrunr, gid, onk2[u2], ntopr
                        kb[2 * NH] = -1
                        ci, slot = _find(kb, ck, ht_stamp, ht_idx, stamp, mask)
                        if ci < 0:
                            ci = m
                            m += 1
                            ht_stamp[slot] = stamp
                            ht_idx[slot] = ci
                            for t in range(KEY):
                                ck[ci, t] = kb[t]
                        elif not (c_tot[ci] > tot):
                            continue
                        c_tot[ci] = tot
                        for t in range(NH):
                            c_hs[ci, 0, t] = kb[t]
                            c_hs[ci, 1, t] = kb[NH + t]
                        c_sec[ci, 0] = sec
                        c_sec[ci, 1] = sec
                        c_h[ci] = -1
                        c_par[ci] = bi
                        c_np[ci] = 2
                        c_pl[ci, 0, 0], c_pl[ci, 0, 1], c_pl[ci, 0, 2], c_pl[ci, 0, 3] = 0, xl, yl, dl
                        c_pl[ci, 1, 0], c_pl[ci, 1, 1], c_pl[ci, 1, 2], c_pl[ci, 1, 3] = 1, xr, yr, dr
                        c_same[ci, 0] = sl
                        c_same[ci, 1] = sr
                        c_wide[ci] = 1 if wide else 0
        if m == 0:
            return hp, hnp, hpl, -1, 0.0, ei
        # 並べ替え（先読みを足した値・同点は先にキーを入れた順）
        for ci in range(m):
            if has_look:
                lqv = c_hs[ci, 0, HQ]
                rqv = c_hs[ci, 1, HQ]
                li_ = 2 if lqv < 0 else lqv
                ri_ = 2 if rqv < 0 else rqv
                hh = c_h[ci]
                j = ei + 1
                if hh == -1:
                    skey[ci] = c_tot[ci] + LT[j, li_, ri_, 0, 0]
                else:
                    oe = c_hs[ci, 1, HEI] if hh == 0 else c_hs[ci, 0, HEI]
                    r = ei - oe if oe >= 0 else LR[j]
                    r = max(1, min(r, LR[j]))
                    skey[ci] = c_tot[ci] + LT[j, li_, ri_, hh + 1, r]
            else:
                skey[ci] = c_tot[ci]
        top = np.argsort(skey[:m], kind='mergesort')
        nn = min(B, m)
        for k in range(nn):   # 残った物だけ直近の割合を更新する（息つぎの置き場所は数えない＝後ろのまとまりをずらさない）
            ci = top[k]
            par = c_par[ci]
            n_tot[k] = c_tot[ci]
            n_hs[k] = c_hs[ci]
            n_sec[k] = c_sec[ci]
            hh = c_h[ci]
            n_last[k] = hh
            e = n_ema[k]
            e[:] = b_ema[par]
            if hh >= 0:
                last = b_last[par]
                if last >= 0:
                    e[E_ALT] = e[E_ALT] * (1 - S[S_AALT]) + (S[S_AALT] if hh != last else 0.0)
                _next_ema(e, c_pl[ci, 0, 1], c_pl[ci, 0, 2], c_pl[ci, 0, 3], c_same[ci, 0], S)
                if use_hw:
                    if rl == 0.0:
                        _hw_ema(e, hh, c_pl[ci, 0, 1], c_pl[ci, 0, 2], S)
                    if c_wide[ci] >= 0:
                        e[E_WIDE] = e[E_WIDE] * (1 - S[S_APAIR]) + (S[S_APAIR] if c_wide[ci] == 1 else 0.0)
            else:
                _next_ema(e, c_pl[ci, 0, 1], c_pl[ci, 0, 2], c_pl[ci, 0, 3], c_same[ci, 0], S)
                _next_ema(e, c_pl[ci, 1, 1], c_pl[ci, 1, 2], c_pl[ci, 1, 3], c_same[ci, 1], S)
                if use_hw:
                    if rl == 0.0:
                        _hw_ema(e, 0, c_pl[ci, 0, 1], c_pl[ci, 0, 2], S)
                        _hw_ema(e, 1, c_pl[ci, 1, 1], c_pl[ci, 1, 2], S)
                    e[E_WIDE] = e[E_WIDE] * (1 - S[S_APAIR]) + (S[S_APAIR] if c_wide[ci] == 1 else 0.0)
            hp[ei + 1, k] = par
            hnp[ei + 1, k] = c_np[ci]
            hpl[ei + 1, k] = c_pl[ci]
        b_tot, n_tot = n_tot, b_tot
        b_hs, n_hs = n_hs, b_hs
        b_sec, n_sec = n_sec, b_sec
        b_last, n_last = n_last, b_last
        b_ema, n_ema = n_ema, b_ema
        nb = nn
    return hp, hnp, hpl, nb, b_tot[0], -1


# ---------------------------------------------------------------- Python の側（打点・方針を配列に詰める）

def _tables(st):
    """方針の数で決まる表（候補の並び・振りの入り口までの移動・両手の組の形）。同じ方針なら使い回す"""
    key = (st.w_neutral, st.w_diag, st.w_side, st.w_center, tuple(st.col_cost), tuple(sorted((k, tuple(v)) for k, v in st.row_cost.items())),
           st.travel_k, st.w_a45, st.w_a90, st.w_travel)
    t = _TABLES.get(key)
    if t is not None:
        return t
    static = st.static_options()
    tk = st.travel_k
    SO_C0 = np.zeros((2, 2, 48))
    SO_X = np.zeros((2, 2, 48), dtype=np.int64)
    SO_Y = np.zeros((2, 2, 48), dtype=np.int64)
    SO_D = np.zeros((2, 2, 48), dtype=np.int64)
    SO_N = np.zeros((2, 2), dtype=np.int64)
    for (h, q), lst in static.items():
        SO_N[h, q] = len(lst)
        for i, (c0, x, y, d) in enumerate(lst):
            SO_C0[h, q, i], SO_X[h, q, i], SO_Y[h, q, i], SO_D[h, q, i] = c0, x, y, d
    G_W = np.full((2, 2, 4, 3, 8, 48), np.nan)
    G_WH = np.zeros((2, 2, 4, 3, 8, 48))
    G_SAME = np.zeros((2, 2, 4, 3, 8, 48), dtype=np.int64)
    G_SHG = np.zeros((2, 2, 4, 3, 8, 48), dtype=np.int64)
    w45, w90, w90x3, wtr = st.w_a45, st.w_a90, st.w_a90 * 3, st.w_travel
    for (h, q), lst in static.items():
        ins = [(x - F.DIR_VEC[d][0] * tk, y - F.DIR_VEC[d][1] * tk) for _, x, y, d in lst]
        sd = 7 if h == F.LEFT else 6
        for px in range(4):
            for py in range(3):
                for pd in range(8):
                    vx, vy = F.DIR_VEC[pd]
                    ex, ey = px + vx * tk, py + vy * tk
                    ang = F._ANG[pd]
                    for i, ((_, x, y, d), (ix, iy)) in enumerate(zip(lst, ins)):
                        dev = 180 - ang[d]
                        w = (w90 if dev < 112 else w90x3) if dev > 67 else w45 if dev > 22 else None
                        if w is not None:
                            G_W[h, q, px, py, pd, i] = w
                        G_WH[h, q, px, py, pd, i] = wtr * math.hypot(ex - ix, ey - iy)
                        G_SAME[h, q, px, py, pd, i] = 1 if (x == px and y == py) else 0
                        G_SHG[h, q, px, py, pd, i] = 1 if (d == 0 and pd == sd and max(abs(x - px), abs(y - py)) >= 1) else 0
    t = _TABLES[key] = (SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG)
    return t


_PF = None


def _pair_flags():
    """両手同時の組の形（足す順: 同じ列・鏡写し・振りの向きの食い違い・手拍子形・振りの通り道）"""
    global _PF
    if _PF is None:
        pf = np.zeros((4, 3, 8, 4, 3, 8, 5), dtype=np.bool_)
        for xl in range(4):
            for yl in range(3):
                for dl in range(8):
                    for xr in range(4):
                        for yr in range(3):
                            for dr in range(8):
                                pf[xl, yl, dl, xr, yr, dr] = (xl == xr, xl == 3 - xr and yl == yr and dl == F.MIRROR_D[dr],
                                                              F.parity_of(F.LEFT, dl) != F.parity_of(F.RIGHT, dr),
                                                              F.handclap(xl, yl, dl, xr, yr, dr), F.hitbox_path(xl, yl, dl, xr, yr, dr))
        _PF = pf
    return _PF


def _hand(hs):
    """flow の手の状態（タプル）→ (int の 9 項目, 秒)"""
    q, x, y, d, sec, ei, run, gid, nk, top = hs
    f = lambda v: -1 if v is None else int(v)
    return [f(q), f(x), f(y), f(d), int(ei), int(run), int(gid), int(nk), 1 if top else 0], float(sec)


def _style_array(st):
    S = np.zeros(NS)
    for i, k in enumerate(_SKEYS):
        S[i] = getattr(st, k)
    W, T = st.w_target, st.targets
    S[S_WR], S[S_WD], S[S_WC], S[S_WE], S[S_WS] = W['row'], W['dir'], W['col'], W['center'], W['still']
    S[S_WH], S[S_WW], S[S_WK], S[S_WALT] = W.get('hcol', 0.0), W.get('wide', 0.0), W.get('cell', 0.0), W['alt']
    S[S_TE], S[S_TS], S[S_TW], S[S_TALT] = T['center'], T['still'], float(T.get('wide', F.WIDE0)), T['alt']
    S[S_USEH], S[S_USEW], S[S_USEK] = bool(S[S_WH]), bool(S[S_WW]), bool(S[S_WK])
    S[S_MODW], S[S_MODH], S[S_MODD], S[S_MODM], S[S_MODT] = (F.MOD_W[k] for k in ('width', 'height', 'diag', 'move', 'turn'))
    S[S_FOUR], S[S_ANOTE], S[S_AMOVE], S[S_AALT], S[S_APAIR], S[S_PAIRS] = 4.0, F.A_NOTE, F.A_MOVE, F.A_ALT, F.A_PAIR, F.PAIR_S
    S[S_TR:S_TR + 3] = T['row']
    S[S_TD:S_TD + 3] = T['dir']
    S[S_TC:S_TC + 4] = T['col']
    S[S_TH:S_TH + 4] = tuple(T.get('hcol') or F.HCOL0)
    S[S_TK:S_TK + 12] = tuple(T.get('cell') or F.CELL0)
    return S


def _events(events, st):
    n = len(events)
    EF = np.zeros((n, NF))
    EI = np.zeros((n, NI), dtype=np.int64)
    maxp = max([1] + [len(e.cyc[h]) for e in events if e.cyc for h in (0, 1)])
    CY = np.zeros((n, 2, maxp, 3), dtype=np.int64)
    JK = np.zeros(n, dtype=np.uint64)
    bidx = {round(e.beat, 4): i for i, e in enumerate(events)}
    efirst = {}
    for i, e in enumerate(events):
        if e.erun is not None:
            efirst.setdefault(e.erun, []).append(i)
    for ei, ev in enumerate(events):
        ef, eir = EF[ei], EI[ei]
        frac = ev.beat - math.floor(ev.beat)
        on_beat = frac < 1e-3 or frac > 1 - 1e-3
        half = abs(frac - 0.5) < 1e-3
        ef[F_SEC], ef[F_BEAT] = ev.sec, ev.beat
        ef[F_STRONG] = ev.strong or 0.0
        ef[F_PY] = np.nan if ev.py is None else ev.py
        ef[F_MG] = ev.min_gap or st.min_gap
        ef[F_FIXW] = ev.fix_w or st.w_fix
        ef[F_REL] = ev.relief or 0.0
        ef[F_BTF] = st.w_beat * 0.5 if half else np.nan
        ef[F_BTB] = st.w_beat if on_beat else np.nan
        mods = ev.mods or {}
        for fi, k in ((F_MW, 'width'), (F_MH, 'height'), (F_MDG, 'diag'), (F_MMV, 'move'), (F_MTN, 'turn')):
            ef[fi] = mods.get(k) or 0
        eir[I_MODS] = 1 if mods else 0
        eir[I_BIG] = 1 if mods.get('bigmove') else 0
        eir[I_SPREAD] = 1 if (mods.get('width') or 0) > 0 else 0
        eir[I_HANDS], eir[I_GID], eir[I_ACC] = ev.hands, ev.gid, 1 if ev.accent else 0
        if ev.fix:
            eir[I_FIXANY] = 1
            for h in (0, 1):
                if h in ev.fix:
                    eir[I_FH0 + h] = 1
                    eir[I_FX0 + 3 * h], eir[I_FY0 + 3 * h], eir[I_FD0 + 3 * h] = ev.fix[h]
        want = ev.want
        eir[I_WANT] = -1 if want is None else want
        ef[F_WANTW] = (ev.want_w if ev.want_w is not None else st.w_want) if want is not None else 0.0
        fx = ev.hoflex
        eir[I_FPOS] = (ei - bidx[round(fx[0], 4)]) if (fx is not None and round(fx[0], 4) in bidx) else -1
        eir[I_FXM] = fx[1] if fx is not None else 0
        eback = (ei - bidx[round(ev.beat - ev.echo, 4)]) if (ev.echo and round(ev.beat - ev.echo, 4) in bidx) else 0
        eback = eback if eback > 0 else 0
        eir[I_EBACK] = eback
        ef[F_LP] = ev.loop if (ev.loop is not None and not eback) else np.nan
        if ev.erun is not None:
            er = efirst[ev.erun][:2]
            eir[I_ER0], eir[I_ER1] = er[0], (er[1] if len(er) > 1 else -1)
        else:
            eir[I_ER0], eir[I_ER1] = -1, -1
        eir[I_HFSAME] = 1 if (ev.echo or ev.erun is not None) else 0
        if ev.cyc:
            for h in (0, 1):
                cy = ev.cyc[h]
                eir[I_CYL0 + h] = len(cy)
                for k, (x, y, d) in enumerate(cy):
                    CY[ei, h, k] = (x, y, d)
        JK[ei] = F._jitter_key(st.seed, ev.beat)
    return EF, EI, CY, JK


def search(events, st, init):
    """打点の並び → (ノーツ [{beat, x, y, c, d}], 減点の合計)（flow.generate の本体）"""
    n = len(events)
    l0, r0, last0 = init or (F.NO_HAND, F.NO_HAND, -1)
    if n == 0:
        return [], 0.0
    EF, EI, CY, JK = _events(events, st)
    S = _style_array(st)
    SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG = _tables(st)
    lh, ls = _hand(l0)
    rh, rs = _hand(r0)
    ihs = np.array([lh, rh], dtype=np.int64)
    isec = np.array([ls, rs])
    e0 = F._ema0(st.targets)
    ema0 = np.array(list(e0[0]) + list(e0[1]) + [e0[2], e0[3], e0[4]] + list(e0[5]) + list(e0[6][0]) + list(e0[6][1]) + [e0[7]]
                    + list(e0[8][0]) + list(e0[8][1]))
    has_look = any(e.fix for e in events)
    if has_look:
        LT, LR, _, _ = _look_tables(EF, EI, S, True)
    else:
        LT, LR = np.zeros((1, 3, 3, 3, 2)), np.ones(1, dtype=np.int64)
    hp, hnp, hpl, nb, cost, bad = _search(EF, EI, CY, JK, S, SO_C0, SO_X, SO_Y, SO_D, SO_N, G_W, G_WH, G_SAME, G_SHG, _pair_flags(),
                                          ema0, ihs, isec, int(last0), LT, LR, has_look, int(st.beam))
    if bad >= 0:
        raise RuntimeError(f'打点 {bad}（拍 {events[bad].beat}）で置ける候補が無い')
    out, idx = [], 0
    for step in range(n, 0, -1):
        ev = events[step - 1]
        for t in range(hnp[step, idx]):
            h, x, y, d = (int(v) for v in hpl[step, idx, t])
            out.append({'beat': ev.beat, 'x': x, 'y': y, 'c': h, 'd': d})
        idx = int(hp[step, idx])
    out.sort(key=lambda n_: (n_['beat'], n_['c']))
    return out, float(cost)


def warm():
    """コンパイル済みの控え（automap/__pycache__ の flow_nb の .nbi・.nbc）を作る: 本体と先読みの表を一度動かす（配布物を作る時・
    tools/dist/build_embed.py が配布物の Python で NUMBA_CPU_NAME=generic にして呼ぶ）。片手・両手・決めたノーツのある打点で、
    作り直しと同じ型の引数（呼ぶ型が違うと別にコンパイルする）"""
    evs = [F.Event(4.0 + i * 0.5, 2.0 + i * 0.25, 2 if i % 5 == 0 else 1) for i in range(12)]
    evs[3].fix = {0: (1, 0, 1)}
    search(evs, F.Style(beam=4), None)
    search(evs[:4] + [F.Event(9.0, 4.5, 1)], F.Style(beam=2), None)
    evs[3].fix = None
    return search(evs, F.Style(beam=4), None)
