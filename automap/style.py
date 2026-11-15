"""曲の個性: 曲全体の特徴（テンポ・歌のリズムの細かさと裏拍・歌の音の長さと跳び・ドラムの細かさと裏拍）から、テーマ（型）の狙いを傾ける。

人の譜面（手元の 143 曲・docs/方針.md 6.19）を曲どうしで比べると、曲の特徴と譜面の形の関係は弱い（相関は強くて ±0.25）＝譜面の個性は
ほぼ作者の好み。ここでは、その弱い関係の「向き」に沿って型の狙いを傾け、効きの強さは差がはっきり出るように大きめにする（＝好みの決めごと）。
狙いごとに主に効く特徴を分ける（1つの狙いに多くの特徴を混ぜて平均すると、ゆっくりめの曲がそろって同じ端に張り付き、同じテーマになった）:
- 外側の列・横の幅: テンポと歌の音の長さ（どちらも +0.22。歌やドラムの細かさ・裏拍（−0.24〜−0.26）も同じ向きだが、混ぜると曲の差が消える）
- 斜め: ドラムの裏拍（−0.18）
- 上の段: 歌の跳び（+0.18）と歌の音域（小節ごとに上下の幅と +0.07）
- 動き: 歌の跳び（+0.10）
横向きは候補の型の 3% にしか無いので狙わない。
特徴の位置は、手元の 143 曲の中の順位（DECILES・tools/library_music.py style で測り直せる）。
歌の音が半拍の目盛りに乗らない割合（off16）は、速い曲ほど歌を強い位置へ寄せる作り（rhythm.snap_vocals）に左右されるので使わない。
"""
import numpy as np

FEATS = ('bpm', 'offbeat', 'vlen', 'vden', 'vrange', 'vjump', 'dden', 'doff16')

# 手元の人の譜面 143 曲（tools/library_music.py の評価の高い組と手元の組・2026-10-25）の 0・10・…・100% の値
DECILES = {
    'bpm': [83.01, 117.2, 125.0, 130.0, 133.8, 150.0, 166.0, 172.4, 184.0, 200.0, 322.0],
    'offbeat': [0.223, 0.342, 0.387, 0.425, 0.477, 0.56, 0.608, 0.63, 0.64, 0.68, 0.772],
    'vlen': [0.161, 0.229, 0.257, 0.272, 0.282, 0.3, 0.321, 0.35, 0.373, 0.409, 0.561],
    'vden': [0.088, 0.956, 1.103, 1.169, 1.257, 1.39, 1.524, 1.626, 1.867, 2.083, 2.851],
    'vrange': [5.55, 9.727, 11.482, 12.219, 13.949, 14.78, 15.43, 16.357, 17.795, 20.947, 33.554],
    'vjump': [0.455, 1.244, 1.476, 1.844, 1.912, 1.965, 1.991, 2.039, 2.215, 2.739, 11.856],
    'dden': [0.859, 1.735, 1.957, 2.042, 2.133, 2.311, 2.446, 2.682, 2.882, 3.19, 5.299],
    'doff16': [0.0, 0.044, 0.073, 0.097, 0.127, 0.155, 0.184, 0.22, 0.285, 0.379, 0.939],
}

NAMES = {'bpm': 'テンポ', 'offbeat': '歌の裏拍', 'vlen': '歌の音の長さ', 'vden': '歌の細かさ', 'vrange': '歌の音域', 'vjump': '歌の跳び',
         'dden': 'ドラムの細かさ', 'doff16': 'ドラムの裏拍'}


def features(onsets, bpm):
    """打点の候補（onsets.json の onsets・拍）→ 曲全体の特徴。歌の音が少なければ歌の特徴は真ん中の値"""
    voc = [v for v in onsets['vocal'] if v['s'] >= 0.3]
    f = {'bpm': float(bpm)}
    if len(voc) >= 30:
        beats = np.array([v['beat'] for v in voc])
        m = np.array([v['midi'] for v in voc])
        span = max(1.0, beats.max() - beats.min())
        f.update(offbeat=float(np.mean(np.abs(beats - np.round(beats)) > 1e-3)), vlen=float(np.median([v['length'] for v in voc])),
                 vden=len(voc) / span, vrange=float(np.percentile(m, 90) - np.percentile(m, 10)), vjump=float(np.median(np.abs(np.diff(m)))))
    else:
        f.update({k: DECILES[k][5] for k in ('offbeat', 'vlen', 'vden', 'vrange', 'vjump')})
    dr = [o for k in ('kick', 'snare') for o in onsets[k] if o['s'] >= 0.3]
    if dr:
        b = np.array([o['beat'] for o in dr])
        f['dden'] = len(dr) / max(1.0, b.max() - b.min())
        f['doff16'] = float(np.mean(np.abs(b * 2 - np.round(b * 2)) > 1e-3))
    else:
        f.update(dden=DECILES['dden'][5], doff16=DECILES['doff16'][5])
    return f


def position(f):
    """特徴ごとの、手元の 143 曲の中の位置（0〜1）"""
    return {k: float(np.interp(f[k], DECILES[k], np.linspace(0, 1, 11))) for k in FEATS}


def tilt(f, gain=1.0):
    """曲の特徴 → 型の狙いの傾き {outer, diag, row, move}（−1〜1）。位置を −1〜1 にして、狙いごとの特徴を関係の向きで重みづけて平均し、gain 倍"""
    p = {k: 2 * v - 1 for k, v in position(f).items()}
    w = {
        'outer': {'bpm': 0.22, 'vlen': 0.22},
        'diag': {'doff16': -0.18},
        'row': {'vjump': 0.18, 'vrange': 0.07},
        'move': {'vjump': 0.10},
    }
    out = {}
    for k, ws in w.items():
        v = sum(c * p[f_] for f_, c in ws.items()) / sum(abs(c) for c in ws.values())
        out[k] = float(np.clip(v * gain, -1, 1))
    return out


# ランク譜面（BeatLeader のランク譜面 2,900 難易度・2026-11-03）の、1 秒の振りの数（sps＝両手の振りの数÷秒）ごとの中央値。振りのたびに、
# もう片方の手の直前の振り（1 秒以内）と組にして数えた。WIDE＝両手を同時に外へ（左手が列 0・右手が列 3）の組の割合。
# HCOL＝手から見た列 r（右手は r=x・左手は r=3−x）の割合 [反対の外, 反対の内, 自分の内, 自分の外]（足して 1 に割り直して使う）。
# 線でつないで使い、端の外は端の値（np.interp）。利用者の決め（2026-11-03）: 標準はランク譜面のふつう（★＝密度に合わせて）
SPS_TABLE = (1.91, 3.03, 3.99, 5.00, 5.97, 7.16, 8.81, 10.76)
WIDE_TABLE = (0.131, 0.149, 0.157, 0.158, 0.169, 0.183, 0.208, 0.249)
HCOL_TABLE = ((0.000, 0.083, 0.522, 0.378), (0.000, 0.151, 0.430, 0.403), (0.003, 0.183, 0.376, 0.415), (0.007, 0.212, 0.343, 0.421),
              (0.011, 0.211, 0.333, 0.431), (0.013, 0.195, 0.333, 0.438), (0.010, 0.181, 0.333, 0.461), (0.009, 0.151, 0.328, 0.499))
# 手から見たマス（rx×3＋y・rx は右手は x・左手は 3−x）の割合（譜面ごとの割合の平均・2026-11-03・docs/方針.md 6.22）。作った譜面は 31 と 20 の
# 2マスに振りの 62〜78% が集まり（ランク譜面は約 48%）、曲どうしの3振りの並びの重なりが 41〜43%（ランク譜面の同じ作者の違う曲 20%）だった
CELL_TABLE = ((0.004, 0.002, 0.000, 0.092, 0.004, 0.007, 0.426, 0.027, 0.066, 0.137, 0.212, 0.023),
              (0.005, 0.002, 0.000, 0.131, 0.005, 0.018, 0.325, 0.019, 0.089, 0.123, 0.234, 0.047),
              (0.008, 0.006, 0.001, 0.150, 0.008, 0.028, 0.260, 0.017, 0.104, 0.111, 0.240, 0.068),
              (0.010, 0.008, 0.001, 0.166, 0.010, 0.033, 0.223, 0.015, 0.111, 0.108, 0.239, 0.076),
              (0.013, 0.011, 0.002, 0.161, 0.009, 0.037, 0.212, 0.013, 0.114, 0.100, 0.235, 0.094),
              (0.012, 0.009, 0.001, 0.156, 0.007, 0.035, 0.216, 0.011, 0.115, 0.100, 0.234, 0.105),
              (0.011, 0.007, 0.001, 0.146, 0.005, 0.030, 0.209, 0.010, 0.116, 0.101, 0.225, 0.139),
              (0.010, 0.003, 0.000, 0.138, 0.002, 0.018, 0.225, 0.004, 0.102, 0.105, 0.198, 0.195))
SPS_DEFAULT = 4.0   # sps が分からない時の値
# 曲ごとの癖（2026-11-03・docs/方針.md 6.22）: 手から見たマスの割合の目標を、列ごとの段の割合だけ曲ごとに散らす（ディリクレ・平均×HABIT_K）。
# どの曲も同じ目標（ランク譜面の平均）に寄せると、曲どうしのマスの使い方の重なりが 90% まで上がった（ランク譜面は違う作者 77%・同じ作者 83%）。
# 列ごとの割合（hcol＝両手の広がり）は散らさない。種は曲の名前と compose の種（style.habit_seed）＝同じ曲は難易度を展開しても同じ癖
HABIT_K = 10.0
# 曲の個性（t['outer']・−1〜1）で外へ広げる効き＝自分の外の割合・両手を同時に外への割合に足す量の最大（利用者「傾きは残して効きを小さく・
# 標準の ±3% くらい」・2026-11-03。前は外側の列の目標に 0.15×t＝ハロ（+0.41）で外側の列が 53% まで上がり、両手を同時に外へが 35%＝ランク譜面の上から 2%）
TILT_SPREAD = 0.03
LIB_HCOL_CAP = 0.03   # 型のデータベースの書き出しの外側のずらし（lib_shift の outer）を自分の外に足す時の上限


def rank_spread(sps=None):
    """1 秒の振りの数 → ランク譜面のふつう (hcol, wide)。hcol＝手から見た列の割合 [反対の外, 反対の内, 自分の内, 自分の外]（足して 1）・
    wide＝両手を同時に外への割合。sps が None なら SPS_DEFAULT（4.0）の値"""
    s = SPS_DEFAULT if sps is None else float(sps)
    rows = [np.asarray(r, float) / sum(r) for r in HCOL_TABLE]
    hcol = np.array([np.interp(s, SPS_TABLE, [r[i] for r in rows]) for i in range(4)])
    hcol = hcol / hcol.sum()
    return tuple(float(v) for v in hcol), float(np.interp(s, SPS_TABLE, WIDE_TABLE))


def rank_cells(sps=None):
    """1 秒の振りの数 → ランク譜面のふつうの手から見たマスの割合（12 個・rx×3＋y・足して 1）"""
    s = SPS_DEFAULT if sps is None else float(sps)
    rows = [np.asarray(r, float) / sum(r) for r in CELL_TABLE]
    c = np.array([np.interp(s, SPS_TABLE, [r[i] for r in rows]) for i in range(12)])
    return tuple(float(v) for v in c / c.sum())


def habit_seed(song, seed=1):
    """曲の名前と種 → 曲ごとの癖の種（起動ごとに変わらない＝zlib.crc32）"""
    import zlib
    return (zlib.crc32(str(song or '').encode('utf-8')) ^ (int(seed) * 0x9E3779B1)) & 0xFFFFFFFF


def habit_cells(cell, seed, k=None):
    """手から見たマスの割合（12 個）→ 列ごとの段の割合を曲ごとに散らした物（列ごとの合計はそのまま）。seed が None なら散らさない"""
    if seed is None:
        return tuple(cell)
    k = HABIT_K if k is None else float(k)
    rng = np.random.default_rng(int(seed))
    out = list(cell)
    for r in range(4):
        p = np.asarray(cell[r * 3:r * 3 + 3], float)
        tot = float(p.sum())
        if tot <= 0 or k <= 0:
            continue
        q = rng.dirichlet(np.maximum(p / tot * k, 1e-3))
        for y in range(3):
            out[r * 3 + y] = tot * float(q[y])
    return tuple(out)


def want(base, t, sps=None):
    """性格の狙い（theme.WANT）を傾ける。外側の列の割合 outer・両手を同時に外への割合 wide の狙いも足す。動かし幅は候補の型の分布に合わせる
    （外側の列の割合は大半の型で 0〜0.5・段の平均は 0〜1・斜めは 0・0.5・1）。
    外側の列（outer）の中心はランク譜面のふつう（rank_spread の 反対の外＋自分の外＝型の shape の outer と同じ数え方・sps 4 で 0.43）で、
    曲の個性の傾きは ±TILT_SPREAD（前は 0.35±0.2）。横の幅（width）の傾きは前の 1/4（±0.25・小数のまま）。
    wide＝ランク譜面のふつう＋TILT_SPREAD×t['outer']（style.targets と同じ）。theme.fit は型の spread がこれより多い分を減点に足す"""
    w = dict(base)
    hcol, wide = rank_spread(sps)
    to = t.get('outer', 0.0)
    w['move'] = base['move'] + 0.5 * t['move']
    w['row'] = float(np.clip(base['row'] + 0.15 * t['row'], 0.0, 1.4))   # 作者の曲は歌の跳びがそろって小さく、強くすると全曲が下の段に寄った
    w['diag'] = float(np.clip(base['diag'] + 0.4 * t['diag'], 0.0, 1.0))
    w['width'] = float(np.clip(base['width'] + 0.25 * to, 0, 3))
    w['outer'] = float(np.clip(hcol[0] + hcol[3] + TILT_SPREAD * to, 0.0, 1.0))
    w['wide'] = float(np.clip(wide + TILT_SPREAD * to, 0.0, 1.0))
    w['w_diag'] = 2.0   # 斜めの合い方を重く（1.0 だと曲D と曲E の傾きが逆でも同じテーマになった）
    w['P'] = max(base['P'], 4)   # 2振りの型（↓20 ↑31 等）はどの曲にも出て、曲の中も単調にする＝簡単な所も4振り以上
    return w


# 目標の中心（下の 0.48・0.45・0.20・0.42）を決めた時の型の出どころ＝手元の譜面（cache/themes.json と同じ Expert／Expert+）の割合。
# 型のデータベースの手元の譜面（自分で書き出した物も入れる・★と年は全部）を library_db.diff_stats で測った（2026-10-26・1,523 難易度）
LIB_REF = {'outer': 0.46, 'diag': 0.366, 'top': 0.238, 'bottom': 0.494}


def lib_shift(lib):
    """型の出どころ → 目標の中心をずらす量 {outer, diag, top, bottom}。型のデータベースの書き出し（library_use.export が選んだ譜面の割合
    library.stats を足した物）の時だけ「選んだ譜面の割合 − LIB_REF」。library.stats の無い型（テストの作り物）は None＝ずらさない"""
    L = (lib or {}).get('library')
    st = L.get('stats') if isinstance(L, dict) else None
    if not st:
        return None
    return {k: float(np.clip(st[k] - LIB_REF[k], -0.15, 0.15)) for k in LIB_REF if st.get(k) is not None}


def targets(t, lib=None, sps=None, habit=None):
    """曲の個性の傾き → 流れの計算の目標の割合（flow.Style.targets の row・dir・col・hcol・wide）。テーマの選び方だけでは、候補の型の偏り
    （斜めの型は外側の列も使う物が多い等）で狙いと逆になることがあった（曲D: 斜めを増やしたいのに 31%）。弱い重みで全体の割合を曲ごとの狙いへ寄せる。
    斜め 45±25%・上の段 20±8%（人の譜面の Expert+ は上の段 22〜25%・作った譜面は 10〜15% だった）。
    列（2026-11-03）: hcol＝手から見た列の割合 [反対の外, 反対の内, 自分の内, 自分の外]・wide＝両手を同時に外へ（左手が列 0・右手が列 3）の割合。
    標準はランク譜面のふつう（rank_spread・sps＝1 秒の振りの数・None は 4.0）。曲の個性で外へ広げる傾きは小さく: 自分の外 ±TILT_SPREAD
    （その分を自分の内から引く）・wide ±TILT_SPREAD。col（手を区別しない 4 列）は hcol から作り直す（col[x]＝(hcol[x]＋hcol[3−x])/2・
    kime._style_cost が col[0]＋col[3] を外側の割合として読む）。前は col の外側 48±15%（手を区別しない）で、ハロで両手を同時に外へが 35% になった。
    lib が型のデータベースの書き出しなら、中心を選んだ譜面の割合の分だけずらす（docs/ライブラリ仕様.md 4 節「曲の個性の目標の割合も、
    選んだライブラリの譜面から取る」。中心の値は手元の譜面に合わせて決めた物なので、そのまま置き換えずに手元の譜面との差を足す）。
    外側のずらしは自分の外に ±LIB_HCOL_CAP まで（その分を自分の内から引く）"""
    from .flow import LIBRARY_EPLUS
    sh = lib_shift(lib) or {}
    to = t.get('outer', 0.0)
    g = float(np.clip(0.45 + sh.get('diag', 0) + 0.25 * t['diag'], 0.15, 0.75))
    top = float(np.clip(0.20 + sh.get('top', 0) + 0.08 * t['row'], 0.08, 0.32))
    hcol, wide = rank_spread(sps)
    hcol = list(hcol)
    d = TILT_SPREAD * to + float(np.clip(sh.get('outer', 0), -LIB_HCOL_CAP, LIB_HCOL_CAP))
    d = float(np.clip(d, -hcol[3], hcol[2]))   # 割合が負にならないように
    hcol[3] += d
    hcol[2] -= d
    tg = dict(LIBRARY_EPLUS)
    tg['hcol'] = tuple(hcol)
    tg['wide'] = float(np.clip(wide + TILT_SPREAD * to, 0.0, 1.0))
    tg['col'] = tuple((hcol[x] + hcol[3 - x]) / 2 for x in range(4))
    cell = list(rank_cells(sps))   # 手から見たマス: 列ごとの合計を（曲の個性で傾けた）hcol にそろえる
    for r in range(4):
        tot = sum(cell[r * 3:r * 3 + 3])
        for y in range(3):
            cell[r * 3 + y] = cell[r * 3 + y] * hcol[r] / tot if tot > 0 else hcol[r] / 3
    tg['cell'] = habit_cells(cell, habit)   # 曲ごとの癖（habit＝habit_seed の種・None なら散らさない）
    tg['dir'] = (1 - g - 0.02, g, 0.02)
    if sh:
        bottom = float(np.clip(0.42 + sh.get('bottom', 0), 0.3, 0.55))
        tg['row'] = (bottom, 1 - bottom - top, top)
    else:
        tg['row'] = (0.42, 0.58 - top, top)   # ずらさない時（library.stats の無い型）は前の cache/themes.json の時と全く同じ式
    return tg


# col（手を区別しない 4 列）は 0 にして、手ごとの列 hcol と両手を同時に外へ wide で見る（2026-11-03・docs/方針.md 6.21）。
# hcol・wide の重みは 4 曲で 1.5・2 ／ 3・4 ／ 4・8 を比べて決めた（テーマの型への寄せ 1.2／マスに負けないように強め）。
# cell（手から見たマスの割合・6.22）は 4・8・12 を比べて 12（曲どうしの3振りの並びの重なり 43%→34%・ほかは崩れない）
W_TARGET = {'row': 1.0, 'dir': 1.5, 'col': 0.0, 'center': 0.0, 'still': 0.0, 'alt': 0.0, 'hcol': 4.0, 'wide': 8.0, 'cell': 12.0}
W_CENTER = 4.0   # 真ん中の2列の中段の減点（試作4 は 2.0）。内側の列を狙う曲で visionBlock が出た
# その帯らしさの重み（★の帯を変えた型の束の時だけ・theme.fit の want['lift']）。2026-10-26 利用者「帯を変えた時は、その帯らしい型を優先する・
# 曲の個性との合い方は少し下がってよい」
W_LIFT = 1.5   # ★〜8 の曲の 1段難しく: 選ばれる 24 テーマのうち曲の設定と同じ物 12→7〜8・2段 5〜9→1〜4（0.5 だと 10・1.0 だと 8〜10）


def band_lib(lib):
    """型の出どころが★の帯を変えた書き出し（library_use.band_lift の印がある）なら、その印（無ければ None）"""
    L = (lib or {}).get('library') if isinstance(lib, dict) else None
    return L.get('band') if isinstance(L, dict) else None


def pick(blocks, onsets, bpm, themes, seed=1, k=3, lib=None, sps=None):
    # lib＝型の出どころの生の中身（__main__._library＝型のデータベースの書き出し）。選んだライブラリに合わせる時に使う
    # sps＝1 秒の振りの数（両手）。狙いの外側の列・両手を同時に外へ（want の outer・wide）をランク譜面のその密度の値に。None は 4.0
    """試作5 のテーマ選び: 曲の特徴 → 傾き → 性格ごとに k 個のテーマ（どれも曲の傾きで選ぶ・使われた曲の数の重みは弱く 0.15・
    先に選んだ物と似ている物は避ける）→ 記号に割り当て（form.palette_assign）。
    lib が★の帯を変えた書き出し（band_lib）なら、その帯らしさ（Theme.lift）も W_LIFT の重みで点に入れる（ほかは前と同じ選び方）。
    → (記号 → Theme, 記号 → Theme の並び（まとまりの中の切り替えの順）, {性格: [Theme…]}, 性格の順, 特徴, 傾き)"""
    from types import SimpleNamespace
    from . import form, theme
    chars = form.character(blocks)
    f = features(onsets, bpm)
    t = tilt(f)
    order = form.palette_order(blocks, chars)
    names = [f'{c}#{i}' for c in order for i in range(k)]
    wl = W_LIFT if band_lib(lib) else 0

    def want_of(sec):
        w = want(theme.WANT[sec.name.split('#')[0]], t, sps=sps)
        if wl:
            w['lift'] = wl
        return w
    got = theme.pick_themes(themes, [SimpleNamespace(name=n) for n in names], seed=seed, want_of=want_of, pop=0.15)
    pal = {c: [got[f'{c}#{i}'] for i in range(k)] for c in order}
    first, seq = form.palette_assign(blocks, chars, pal)
    return first, seq, pal, order, f, t


def describe(f, t):
    """報告用の一行（目立つ特徴と傾き）"""
    pos = position(f)
    top = sorted(FEATS, key=lambda k: -abs(pos[k] - 0.5))[:4]
    feats = '・'.join(f'{NAMES[k]} {pos[k]:.0%}' for k in top)
    tl = '・'.join(f'{ {"outer": "外側", "diag": "斜め", "row": "上の段", "move": "動き"}[k]} {v:+.2f}' for k, v in t.items())
    return f'目立つ特徴（手元の 143 曲の中の位置）: {feats} → 型の傾き: {tl}'
