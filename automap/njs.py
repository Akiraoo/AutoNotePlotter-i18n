"""譜面の NJS（ノーツが飛んでくる速さ）を★・BPM・難易度から決める（docs/アプリ仕様.md 20 節・2026-11-02 利用者）。

前は NJS を書かず NLM の既定（Easy〜Hard 10・Expert 12・Expert+ 16）のままで、展開した易しい難易度が遅すぎた。ランク譜面では NJS は
難易度の名前より★と BPM でほぼ決まる（型のライブラリ 3766 難易度: 同じ Expert でも★4〜6 で 16・★8 以上で 20・BPM 180 以上は 2〜4 速い）。
そこで最小二乗の式 NJS＝切片＋★×a＋BPM×b＋難易度の足し分（ずれの中央 1.0）で決める。★が測れない PC（nlm-rating が無い）は
1秒のノーツの数の式で代わりに。0.5 きざみ・好みで全体をずらす（app/config.local.json の njs_offset か 環境変数 AUTOMAP_NJS_OFFSET）。

書くのは njsCfg（NLM の難易度ごとの NJS・オフセット。キーは difficulties と同じ小文字）の項目に {njs, offset, auto}。auto＝アプリが書いた
NJS の印。NLM は項目のほかの値を残したまま njs を直して保存する（editor-app.js の setNjsCur・読み込みは structuredClone）ので、
njs が auto と違えば利用者が NLM で決めた値＝上書きしない。項目が無い・auto と同じ時だけ書き直す（前に書いた値と 0.5 以内なら前のまま＝
★の小さな揺れで作り直すたびに変わらない）。offset は今の値のまま（無ければ 0）。
njs_auto: false（config）で書かない。係数は★の物差しの一部（automap/rating_scale.py）で、★が変わったら fit(データベース) で作り直す。

**3D で決めた基準の NJS**（2026-11-09 利用者「Brotherhood の Normal を NJS 13 で開いたら遅すぎて見にくい。3D で 17 にしたらちょうどよかった。
ここを基準に上を作るので式の NJS では合わない」）: 3D の窓の NJS の横の「譜面に使う」を ON にすると、その値が曲の基準の NJS になる。
曲ごとに作業ファイルの njs＝{base: 値}（無い＝OFF＝式のまま・`decided`）。基準には決めた値をそのまま（★が少し変わっても動かさない・`put`）、
これから作る派生は「決めた値＋（式での派生の値 − 式での基準の値）」（`from_base`＝式の上下の間隔を保つ・0.5 きざみ・RANGE の中）。
もう作ってある派生は切り替えでは書き直さない。auto の印の決まりは同じ（ON の後で NLM で直された値は作り直しでも触らない）。

**見え始める距離（JD）とオフセット**（2026-11-10 利用者「ストロボで NJS 15.1 はゆっくりなのに 15.2 にした瞬間すごく速くなる」「できるだけ自動で
最適な値が入ってほしい」・docs/アプリ仕様.md 20 節）: Beat Saber はノーツが見え始める所を 4 拍前から数え、その距離が 18m を超える間は半分に
する（2 拍・1 拍…）。BPM の低い曲では NJS の小さな違いでこの境目をまたぎ、オフセット 0 のままだと JD が倍・半分に跳ぶ（BPM 101 のストロボは
NJS 15.15 が境目＝15.1 で 35.9m・15.2 で 18.1m）。ランク譜面の作者は 85% がオフセットを入れて打ち消していて（境目のすぐ下は −0.7 拍・すぐ上は
+0.15 拍ほど＝どちらも JD 21m 台）、JD はほぼ難易度で決まる（同じ難易度の中では NJS・★・BPM ではほとんど変わらない）。年ごとに短くなって
いる（2020 年 24.2m → 2025 年 18.6m）ので、2023 年以降のランク譜面の難易度ごとの中央値（JD_TARGET・tools/library_build/jd_table.py で測り直せる）
を狙い、NLM の譜面チェックの警告が出ない範囲（18m 以上・NJS ごとのちょうどよい上限以下・反応 0.42 秒以上）に収める（target_jd）。
NJS を書いた時（apply・put）にその NJS で狙いの JD になるオフセットも書く（fix_jd・NLM の欄と同じ 0.001 拍きざみ）。auto_offset＝アプリが
書いたオフセットの印: offset が auto_offset と違えば NLM で利用者が決めた値＝上書きしない。印が無く offset が 0（か無い）＝まだ誰も決めて
いない＝書く。印が無く 0 でない＝NLM で決めた値＝触らない。NJS を NLM で直しても、オフセットがアプリの値なら次に整える時にその NJS で狙いの
JD に合わせ直す。
"""
import json
import os
from pathlib import Path

from . import config, diffs, rating_scale

ROOT = Path(__file__).resolve().parent.parent
CONFIG = config.path()
ORDER = diffs.ORDER
# fit() の答え（★の物差しと一緒に tools/library_build/update_rating.py が automap/rating_scale.json に書く）
COEF = rating_scale.NJS_COEF
STEP = 0.5
RANGE = (8.0, 24.0)
BASE_LIMITS = (5.0, 30.0)   # 3D で決める基準の NJS の受け付ける範囲（3D の窓の NJS の欄と同じ）

# 見え始める距離（JD・m）の狙い＝2023 年以降の BeatLeader のランク譜面（1,038 難易度・491 曲）の難易度ごとの中央値（2026-11-10 に測った・
# tools/library_build/jd_table.py）。参考: 2022 年以降 22.2・21.3・20.5・19.6・18.9／2024 年以降 20.2・20.0・19.3・19.0・18.2
JD_TARGET = {'Easy': 20.7, 'Normal': 20.3, 'Hard': 19.7, 'Expert': 19.1, 'ExpertPlus': 18.5}
JD_SINCE = 2023
# NLM の譜面チェック（mapcheck.js・Kival の MapCheck と同じ）の警告: JD 18m 未満・36m 超・NJS ごとのちょうどよい上限（opt_hi）超・反応 0.42 秒未満。
# 0.001 拍に丸めた後もまたがないよう少し内側に
JD_MIN, RT_MIN, JD_MARGIN = 18.0, 0.42, 0.05
OFF_STEP = 0.001   # NLM のオフセットの欄（editor-app.js の offField・0.001 拍）


def half_beats(njs, bpm):
    """Beat Saber の既定の半分の飛来の拍（4 拍から始めて、距離が 18m を超える間は半分に）。3D（preview-v4 の computeJump）と同じ式。
    NLM の画面の JD の表示（mapcheck.js）は 1 拍より小さくしない（BPM が NJS×3.3 より遅い時だけ違う＝ほぼ無い）"""
    spb = 60.0 / float(bpm)
    h = 4.0
    for _ in range(64):
        if float(njs) * spb * h <= 17.999:
            break
        h /= 2
    return h


def jd_of(njs, offset, bpm):
    """→ (JD m, 反応時間 秒)。ゲームと同じ: 半分の拍＝既定＋オフセット（0.25 拍より短くしない）"""
    spb = 60.0 / float(bpm)
    hb = max(half_beats(njs, bpm) + float(offset or 0), 0.25)
    return 2 * float(njs) * spb * hb, spb * hb


def opt_hi(njs):
    """NLM の譜面チェックの「JD のちょうどよい上限」（mapcheck.js の calcJdOptimal()[1]）"""
    return 18 * (1 / 1.07) ** float(njs) + 18


def target_jd(diff, njs):
    """難易度と NJS → 狙いの JD（m）。難易度ごとの中央値を NLM の警告が出ない範囲に収める（下限は 18m と反応 0.42 秒・上限はちょうどよい上限。
    ぶつかる時（NJS 26 くらいから）は反応時間を守る）"""
    v = JD_TARGET[diffs.name_of(diff)]
    lo = max(JD_MIN + JD_MARGIN, 2 * float(njs) * (RT_MIN + JD_MARGIN / 10))
    hi = opt_hi(njs) - JD_MARGIN
    return round(max(lo, min(v, hi)), 3)


def offset_for(diff, njs, bpm):
    """その NJS・BPM で狙いの JD になるオフセット（拍・0.001 きざみ）"""
    spb = 60.0 / float(bpm)
    hb = max(target_jd(diff, njs) / (2 * float(njs) * spb), 0.25)
    return round(round((hb - half_beats(njs, bpm)) / OFF_STEP) * OFF_STEP, 3) + 0.0   # −0.0 を 0.0 に


def user_offset(e):
    """njsCfg の項目 → 利用者が NLM で決めたオフセット（数）か None（アプリが書いた・まだ誰も決めていない）"""
    if not isinstance(e, dict) or e.get('offset') is None:
        return None
    o = float(e['offset'])
    if e.get('auto_offset') is not None:
        return None if o == float(e['auto_offset']) else o
    return None if o == 0 else o


def fix_jd(proj, dkey):
    """難易度 dkey の今の NJS で狙いの JD になるオフセットを書く → {state: wrote|same|kept|none, offset, jd, rt, target}。
    kept＝NLM で決めたオフセット（触らない・jd は今の値）。none＝NJS の項目か BPM が無い（書かない）"""
    cfg = proj.get('njsCfg') if isinstance(proj.get('njsCfg'), dict) else None
    e = cfg.get(dkey) if cfg else None
    bpm = proj.get('bpm')
    if not isinstance(e, dict) or e.get('njs') is None or not bpm or float(bpm) <= 0:
        return {'state': 'none'}
    try:
        diffs.name_of(dkey)
    except ValueError:   # 知らない難易度（Standard 以外の特性など）は触らない
        return {'state': 'none'}
    n = float(e['njs'])
    tgt = target_jd(dkey, n)
    u = user_offset(e)
    if u is not None:
        jd, rt = jd_of(n, u, bpm)
        return {'state': 'kept', 'offset': u, 'jd': jd, 'rt': rt, 'target': tgt}
    o = offset_for(dkey, n, bpm)
    st = 'same' if e.get('auto_offset') is not None and float(e.get('offset') or 0) == o else 'wrote'
    if st == 'wrote':
        cfg[dkey] = dict(e, offset=o, auto_offset=o)
    jd, rt = jd_of(n, o, bpm)
    return {'state': st, 'offset': o, 'jd': jd, 'rt': rt, 'target': tgt}


def fix_all(proj, skip=()):
    """アプリが NJS を書いた難易度（auto の印がある）の全部のオフセットを整える → [(難易度のキー, 前の JD, fix_jd の答え)]（書いた物だけ）。
    NLM で決めたオフセット・アプリが NJS を書いていない難易度（利用者が NLM で作った等）は触らない。skip＝もう整えた難易度"""
    cfg = proj.get('njsCfg') if isinstance(proj.get('njsCfg'), dict) else {}
    out = []
    for k in list(proj.get('difficulties') or {}):
        e = cfg.get(k)
        if k in skip or not isinstance(e, dict) or e.get('auto') is None or e.get('njs') is None or not proj.get('bpm'):
            continue
        before = jd_of(e['njs'], e.get('offset') or 0, proj['bpm'])[0]
        r = fix_jd(proj, k)
        if r['state'] == 'wrote':
            out.append((k, before, r))
    return out


def jd_text(r):
    """fix_jd の答え → 報告の言葉（例「JD 19.1m・反応 0.57 秒（オフセット −0.623 拍）」）。none は ''"""
    if r.get('state') in (None, 'none'):
        return ''
    o = r['offset']
    os_ = f'{"−" if o < 0 else "+" if o > 0 else "±"}{abs(o):.3f}'
    base = f'JD {r["jd"]:.1f}m・反応 {r["rt"]:.2f} 秒'
    if r['state'] == 'kept':
        return f'{base}（NLM で決めたオフセット {os_} 拍のまま・狙いは {r["target"]:.1f}m）'
    return f'{base}（オフセット {os_} 拍）'


def setting():
    """(書くか, 全体のずらし)。config.local.json の njs_auto（既定 true）・njs_offset（既定 0）。環境変数 AUTOMAP_NJS_OFFSET が先"""
    try:
        cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cfg = {}
    off = os.environ.get('AUTOMAP_NJS_OFFSET', cfg.get('njs_offset', 0))
    try:
        off = float(off or 0)
    except (TypeError, ValueError):
        off = 0.0
    return cfg.get('njs_auto', True) is not False, off


def suggest(diff, bpm, stars=None, nps=None, offset=0.0):
    """→ (NJS, 決め方の説明)。★があれば★の式、無ければ 1秒のノーツの式、どちらも無ければ (None, 理由)"""
    d = diffs.name_of(diff)
    if stars is not None:
        c, x, what = COEF['stars'], float(stars), f'★{float(stars):.2f}'
    elif nps is not None and COEF.get('nps'):
        c, x, what = COEF['nps'], float(nps), f'1秒のノーツ {float(nps):.2f}'
    else:
        return None, '★も1秒のノーツも無い'
    v = c['base'] + c['x'] * x + c['bpm'] * float(bpm) + c['diff'][d] + offset
    v = min(RANGE[1], max(RANGE[0], round(v / STEP) * STEP))
    return v, f'{what}・BPM {float(bpm):g}・{diffs.TEXT[d]}' + (f'・好み {offset:+g}' if offset else '')


def settle(diff, bpm, stars_at, cur, nps=None, offset=0.0):
    """式の値を、その値の速さで測った★で決める → (NJS, 説明)。★は NJS で少し変わる（Acc・NJS 17 で +0.1〜0.3）ので、3D で決めた値（17）が
    入っている基準の式の値を今の速さで測った★で決めると 13 が 13.5 にずれた（Brotherhood の Normal・OFF に戻すと前の 13 に戻らない・派生も
    0.5 ずれる）。stars_at(NJS)＝その速さで測った★（None＝測れない）・cur＝今の NJS。今の速さで測り、式の値が今と違えばその値で 1 回だけ
    測り直す（★が測れなければ 1 秒のノーツの式＝速さに依らない）"""
    s = stars_at(cur)
    if s is None:
        return suggest(diff, bpm, nps=nps, offset=offset)
    v, how = suggest(diff, bpm, stars=s, offset=offset)
    if v is not None and abs(v - float(cur)) > 1e-9:
        s2 = stars_at(v)
        if s2 is not None:
            v, how = suggest(diff, bpm, stars=s2, offset=offset)
    return v, how


def with_njs(proj, dkey, value):
    """難易度 dkey の NJS だけを value にした浅い写し（★をその速さで測る時・元の proj は変えない）。オフセットも書いた時と同じに
    （その NJS で狙いの JD・NLM で決めたオフセットは今のまま＝fix_jd）"""
    cfg = dict(proj.get('njsCfg') or {}) if isinstance(proj.get('njsCfg'), dict) else {}
    e = cfg.get(dkey) if isinstance(cfg.get(dkey), dict) else {}
    cfg[dkey] = dict(e, njs=float(value), offset=e.get('offset', 0) or 0)
    out = dict(proj, njsCfg=cfg)
    fix_jd(out, dkey)
    return out


def user_value(e):
    """njsCfg の項目 → 利用者が NLM で決めた NJS（auto と違う・auto の印が無い）か None（アプリが書いた値・項目が無い）"""
    return e['njs'] if isinstance(e, dict) and e.get('njs') is not None and e.get('auto') != e.get('njs') else None


def apply(proj, dkey, value, force=False):
    """njsCfg に書く → ('wrote'|'same'|'kept', 今の値)。kept＝利用者が NLM で決めた値（auto と違う）＝上書きしない。
    force＝前に書いた値と 0.5 以内でも書く（3D で決めた基準の値から決めた派生・★の揺れの守りは要らない）"""
    cfg = proj.get('njsCfg')
    if not isinstance(cfg, dict):
        cfg = proj['njsCfg'] = {}
    e = cfg.get(dkey)
    if user_value(e) is not None:
        out = 'kept', e.get('njs')
    elif isinstance(e, dict) and e.get('auto') is not None and e.get('njs') is not None and float(e['njs']) == float(value):
        out = 'same', e['njs']
    elif not force and isinstance(e, dict) and e.get('auto') is not None and abs(float(e['auto']) - value) <= STEP + 1e-9:   # ★の小さな揺れで行ったり来たりしない
        out = 'same', e['auto']
    else:
        put(proj, dkey, value)
        return 'wrote', value
    fix_jd(proj, dkey)   # NJS はそのままでも、見え始める距離はその NJS で整える（NLM で決めたオフセットは触らない）
    return out


def put(proj, dkey, value):
    """njsCfg に必ず書く（{njs, offset, auto}・auto＝value＝アプリが書いた印）。NLM で直した値も上書きする＝
    3D で決めた基準の値（利用者がアプリで明示して決めた）と、OFF に戻して式の値に戻す時だけ使う。オフセットはその NJS で狙いの JD に
    （fix_jd・NLM で決めたオフセットは今のまま・BPM が無ければ今のまま）"""
    cfg = proj.get('njsCfg')
    if not isinstance(cfg, dict):
        cfg = proj['njsCfg'] = {}
    old = cfg.get(dkey) if isinstance(cfg.get(dkey), dict) else {}
    value = float(value)
    cfg[dkey] = dict(old, njs=value, offset=old.get('offset', 0) or 0, auto=value)
    fix_jd(proj, dkey)


def decided(w):
    """作業ファイル → 3D で決めた基準の NJS（数）か None（無い・形が違う＝OFF＝式のまま）"""
    e = (w or {}).get('njs') if isinstance(w, dict) else None
    v = e.get('base') if isinstance(e, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return round(v, 2) if BASE_LIMITS[0] <= v <= BASE_LIMITS[1] else None


BASE_FROM = {'nlm': 'NLM で直した基準の NJS', '3d': '3D で決めた基準の NJS'}


def base_value(proj, bkey, decided=None):
    """派生の NJS の元にする基準の NJS → (値, 'nlm'|'3d') か (None, None)（＝派生は式のまま）。**最後に決めた方が勝つ**（2026-11-09 利用者
    「NLM でさらに調整がかかっている場合は、それを採用してほしい。こちらでの調整は簡易的な位置づけで、詳細な仕上げを NLM でやる」）:
    基準が NLM で直されていれば（njs が auto と違う）その値（3D の「譜面に使う」が OFF でも）・アプリが書いた値なら 3D で決めた値（decided）。
    3D で決め直すと結果のファイルを上書きして auto の印も付く＝アプリが書いた値に戻る"""
    cfg = proj.get('njsCfg') if isinstance(proj.get('njsCfg'), dict) else {}
    u = user_value(cfg.get(bkey))
    if u is not None:
        return float(u), 'nlm'
    if decided is not None:
        return float(decided), '3d'
    return None, None


def from_base(base_value, derived_formula, base_formula):
    """3D で決めた基準の値から派生の NJS: 決めた値＋（式での派生の値 − 式での基準の値）＝式の上下の間隔を保ってずらす（0.5 きざみ・RANGE の中）。
    例: 基準 Normal ★5.2 の式 13 → 決めた 17（+4）なら、Hard ★5.8 の式 14.5 → 18.5"""
    v = float(base_value) + float(derived_formula) - float(base_formula)
    return min(RANGE[1], max(RANGE[0], round(v / STEP) * STEP))


def fit(db_path):
    """型のライブラリ（SQLite）のランク譜面から係数を作る → {'stars': {...}, 'nps': {...}, 'n': 数, 'err': ずれの中央}"""
    import sqlite3
    import numpy as np
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    rows = con.execute('SELECT d.difficulty, d.njs, m.bpm, COALESCE(d.stars, d.star_approx), d.nps FROM diffs d JOIN maps m ON m.id = d.map_id '
                       'WHERE d.njs IS NOT NULL AND d.bl_ranked AND m.bpm > 0').fetchall()
    out = {}
    for name, col in (('stars', 3), ('nps', 4)):
        rs = [r for r in rows if r[col] is not None and r[0] in ORDER]
        X = np.array([[1.0, r[col], r[2]] + [1.0 if r[0] == d else 0.0 for d in ORDER[1:]] for r in rs])
        y = np.array([r[1] for r in rs], float)
        c, *_ = np.linalg.lstsq(X, y, rcond=None)
        out[name] = {'base': round(float(c[0]), 2), 'x': round(float(c[1]), 3 if name == 'stars' else 3), 'bpm': round(float(c[2]), 4),
                     'diff': dict({'Easy': 0.0}, **{d: round(float(v), 2) for d, v in zip(ORDER[1:], c[3:])}),
                     'n': len(rs), 'err': round(float(np.median(abs(y - X @ c))), 2)}
    return out


if __name__ == '__main__':
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else json.loads(CONFIG.read_text(encoding='utf-8'))['library_db']
    print(json.dumps(fit(db), ensure_ascii=False, indent=1))
