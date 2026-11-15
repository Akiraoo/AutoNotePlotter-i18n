"""3D で決めた NJS を曲の基準の NJS にする（2026-11-09 利用者・docs/アプリ仕様.md 20 節）。server.py の connect() が routes(ctx) を呼んでつなぐ
（ctx＝server モジュール）。画面は static/js/preview.js（3D の窓の NJS の横の「譜面に使う」）。

利用者「Brotherhood（BPM 94.7・基準は Normal に置いた★5.2）を開いたら NJS 13（式の値）で遅すぎて見にくい。3D で 17 にしたらちょうどよかった。
ここを基準に上を作るので式の NJS では合わない」「3D の画面で指定した場合に、それが基準になって新しく設定されていることが分かるように」。

- 曲ごとに作業ファイル（<結果のファイル>.automap.json）の njs＝{base: 値}（無い＝OFF＝式のまま・automap/njs.decided）。全体の好みの
  njs_offset とは別。画面は store.js の setWork／workBody が通す（PUT /api/work は作業ファイルを丸ごと置き換える＝通さないと保存で消える）。
  曲の全体に効く設定ではない（ノーツは変えない＝変えても前の譜面に寄せる・versions.WORK_ONLY）・「意思入れも戻す」でも今のまま（KEEP_ON_RESTORE）。
- **基準の NJS は決めた値そのまま**（作り直して★が少し変わっても動かさない）。ON にした時すぐ結果のファイルの基準の難易度の njsCfg に書く
  （作り直しを待たない・{njs, offset, auto}＝auto の印も・NLM で直された値も上書き＝アプリで明示して決めた）。作り直し（compose --njs-base）
  もその値で書く。**最後に決めた方が勝つ**（2026-11-09 利用者「NLM でさらに調整がかかっている場合は、それを採用してほしい」）: ON の後で
  NLM で直された値（njs が auto と違う）は作り直しでは触らず、それが基準の NJS（派生の元も・njs.base_value）。作業ファイルの njs.base は
  3D で決めた値のまま（NLM の値に書き換えない＝元に戻すで NLM の値を消さない・どちらが後かは結果のファイルの auto の印で分かる）。
- OFF に戻すと式の値（今の基準の★・BPM・難易度・好みのずらし）に戻す。NLM で直された値は OFF でも触らない。
- **もう作ってある派生はそのまま**（切り替えでは書き直さない・利用者「もう作ってある派生は私の方で修正する」）。これから作る派生（展開・
  展開し直し）は 決めた値＋（派生の式 − 基準の式）（app/expand.py・njs.from_base）。
- 保存の仕方は expand.base_njs と同じ（NLM で直された後のファイルなら書いた時の指紋は残さない＝「NLM で直された」の判定をそのままに）。
  作り直し・展開の間（busy）は断る（compose が結果のファイルを書き直す）。★の控えは中身の指紋（NJS も入る）＝書いた後に画面が聞くと測り直す。

- **見え始める距離（JD）**（2026-11-10・automap/njs.py の fix_jd）: NJS を書く時（put）にその NJS で狙いの JD になるオフセットも書く。
  曲を開いた時は POST /api/njs/jd で、アプリが NJS を書いた難易度の全部のオフセットを整える（前の版で作った譜面はオフセット 0 のまま＝
  BPM の低い曲で JD が倍に跳んでいた・NLM で決めたオフセットは触らない）。3D は jd（狙いの表と範囲）で NJS を変えた時の JD を出す。

受け口:
  GET  /api/njs?file=[&wait=秒]    今の様子 {base, decided, njs, auto, user, default, set, busy, exists, formula: {state, value, how}, jd}
                                    （formula＝式の値。★は app/rating の控え・wait 秒まで待つ・running＝まだ測っている。jd＝JD_INFO）
  POST /api/njs {file, base?, mode?}  base（数・null＝OFF）があれば作業ファイルの njs に書いてから、作業ファイルの決めた値を結果のファイルへ
                                    （mode 'set'＝既定・NLM で直された値も上書き／'sync'＝アプリが書いた値の時だけ合わせる＝開いた時の食い違い）
  POST /api/njs/jd {file}           アプリが NJS を書いた難易度のオフセットを狙いの JD に → {wrote, line, jd}（作り直し・展開の間は何もしない）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automap import diffs, nlmf, njs  # noqa: E402

C = None   # server モジュール（OUT・out_file・load_work・save_work・base_diff・busy・cli は呼ばれた時に読む）
WAIT_OFF = 30   # OFF に戻す時に式の値の★を待つ秒（たいていは測ってある＝すぐ）
# 3D が NJS を変えた時の JD を出すための狙いの表と範囲（njs.target_jd と同じ決まりを preview.js の jdTarget が使う）
JD_INFO = {'target': njs.JD_TARGET, 'min': njs.JD_MIN, 'rt_min': njs.RT_MIN, 'margin': njs.JD_MARGIN}


def _rating():
    """app/rating（server がつないだ口だけ・★の控えを使い回す）か None"""
    R = sys.modules.get('rating')
    return R if R is not None and getattr(R, 'C', None) is C and hasattr(R, 'rate') else None


def _nps(proj, k):
    ns = nlmf.clip_notes(proj, k, include_muted=True)
    if len(ns) < 2:
        return None
    tm = nlmf.tempo_of(proj)
    span = tm.sec(ns[-1]['beat']) - tm.sec(ns[0]['beat'])
    return len(ns) / span if span > 0 else None


def _stars_at(proj, d, value):
    """基準 d の NJS だけを value にした中身の★（nlm-rating・頼みの中身の指紋で覚える＝同じ中身は測り直さない）。測れなければ None"""
    from automap import rating as AR
    exe = AR.rating_exe()
    if not exe:
        return None
    req, meta = AR.request(njs.with_njs(proj, diffs.key(d), value), d)
    sha = AR.req_key(req, AR.exe_version(exe))
    if sha not in _AT:
        r = AR.summarize(AR.run(exe, req), meta)
        _AT[sha] = r['stars'] if r.get('ok') and not r.get('skipped') and r.get('stars') is not None else None
    return _AT[sha]


_AT = {}   # 頼みの指紋 → ★（_stars_at・このプロセスの間）


def formula(p, proj, d, wait=0.0):
    """基準 d の式の NJS → {state: done|running|none, value, how, stars}。★は今の中身（今の NJS）を app/rating の控えで（wait 秒まで待つ）・
    式の値が今の NJS と違えば（3D で決めた値が入っている）その速さで測り直す（njs.settle＝決めた 17 の速さの★で式が 13 → 13.5 に
    ずれない・OFF に戻すと前の式の値に戻る）。nlm-rating が無い PC は 1 秒のノーツの式（compose と同じ）"""
    k = diffs.key(d)
    if not nlmf.clip_notes(proj, k, include_muted=True):
        return {'state': 'none', 'value': None, 'how': 'ノーツが無い'}
    off = njs.setting()[1]
    from automap import rating as AR
    cur = AR.njs_of(proj, k, d)[0]
    R = _rating()
    if R is not None:
        r = R.rate(p, wait, d)
        if r.get('state') == 'running':
            return {'state': 'running', 'value': None, 'how': '★を測っている'}
        now = r['stars'] if r.get('ok') and r.get('stars') is not None and not r.get('skipped') else None
    else:   # 口がつながっていない（テスト・別の使い方）＝作り直しと同じく測る
        r = AR.measure_proj(proj, d)
        now = r.get('stars') if r.get('ok') else None
    got = {}

    def at(v):
        got['stars'] = now if v == cur else _stars_at(proj, d, v)
        return got['stars']
    v, how = njs.settle(d, proj['bpm'], at, cur, nps=_nps(proj, k), offset=off)
    return {'state': 'done' if v is not None else 'none', 'value': v, 'how': how, 'stars': got.get('stars')}


def state(p, w=None, wait=None):
    """今の様子（GET /api/njs の答え）。wait が None なら式の値は聞かない"""
    w = C.load_work(p) if w is None else w
    base = C.base_diff(p, w)
    out = {'file': p.name, 'base': base, 'text': diffs.TEXT[base], 'decided': njs.decided(w), 'exists': p.exists(),
           'busy': C.busy(p.name), 'default': diffs.NJS[base], 'njs': None, 'auto': None, 'user': None, 'set': False, 'has_base': False,
           'jd': JD_INFO}
    if not p.exists():
        return out
    proj = nlmf.load(p)
    k = diffs.key(base)
    out['has_base'] = k in proj['difficulties']
    e = (proj.get('njsCfg') or {}).get(k) if isinstance(proj.get('njsCfg'), dict) else None
    if isinstance(e, dict) and e.get('njs') is not None:
        out.update(njs=e['njs'], auto=e.get('auto'), set=True, user=njs.user_value(e))
    else:
        out['njs'] = diffs.NJS[base]   # 項目が無い＝NLM の既定
    if wait is not None and out['has_base']:
        out['formula'] = formula(p, proj, base, wait)
    return out


def _save(p, proj):
    if C.cli._edited_since_written(p):
        nlmf.save(proj, p)   # NLM で直された後のファイル＝書いた時の指紋は残さない
    else:
        C.cli._save(proj, p)


def _value(v):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ValueError('NJS は数か null（OFF）')
    try:
        v = float(v)
    except ValueError:
        raise ValueError('NJS は数か null（OFF）') from None
    lo, hi = njs.BASE_LIMITS
    if not lo <= v <= hi:
        raise ValueError(f'NJS は {lo:g}〜{hi:g}')
    return round(v, 2)


def apply(p, mode='set'):
    """作業ファイルの決めた値を結果のファイルの基準の njsCfg へ → (書いたか, 説明)"""
    w = C.load_work(p)
    v = njs.decided(w)
    if not p.exists():
        return False, '結果のファイルがまだ無い（最初の作り直しで書く）'
    base = C.base_diff(p, w)
    proj = nlmf.load(p)
    k = diffs.key(base)
    if k not in proj['difficulties']:
        return False, f'結果のファイルに基準の {diffs.TEXT[base]} が無い'
    e = (proj.get('njsCfg') or {}).get(k) if isinstance(proj.get('njsCfg'), dict) else None
    user = njs.user_value(e)
    if v is not None:   # ON: 決めた値そのまま（'set' は NLM で直された値も上書き）
        if mode == 'sync' and user is not None:
            return False, f'NLM で {user:g} に直した値を基準に使っている（派生もこの値から）'
        if isinstance(e, dict) and e.get('njs') == v and e.get('auto') == v:
            return False, f'基準（{diffs.TEXT[base]}）の NJS はもう {v:g}'
        njs.put(proj, k, v)
        _save(p, proj)
        return True, f'基準（{diffs.TEXT[base]}）の NJS を 3D で決めた {v:g} に' + (f'（NLM で決めた {user:g} を上書き）' if user is not None else '') + _jd(proj, k)
    if mode == 'sync':
        return False, '決めた値は無い（式のまま）'
    if user is not None:   # OFF: NLM で決めた値は触らない
        return False, f'NLM で {user:g} に直した値を基準に使っている（式には戻さない・派生もこの値から）'
    f = formula(p, proj, base, WAIT_OFF)
    if f.get('value') is None:
        return False, f'式の値を決められなかった（{f.get("how")}）＝今の値のまま'
    if isinstance(e, dict) and e.get('njs') == f['value'] and e.get('auto') == f['value']:
        return False, f'基準（{diffs.TEXT[base]}）の NJS はもう式の {f["value"]:g}'
    njs.put(proj, k, f['value'])
    _save(p, proj)
    return True, f'基準（{diffs.TEXT[base]}）の NJS を式の {f["value"]:g} に戻した（{f["how"]}）' + _jd(proj, k)


def _jd(proj, k):
    t = njs.jd_text(njs.fix_jd(proj, k))   # put が書いた後＝same（言葉だけ）
    return f'・{t}' if t else ''


def fix_jd(b):
    """POST /api/njs/jd: アプリが NJS を書いた難易度のオフセットを狙いの JD に（njs.fix_all）→ {wrote, line, jd}"""
    p = C.out_file(b['file'])
    out = {'wrote': False, 'line': '', 'jd': JD_INFO}
    if C.busy(p.name) or not p.exists() or not njs.setting()[0]:   # 作り直し・展開の間は compose が書く／njs_auto: false は触らない
        return out
    proj = nlmf.load(p)
    got = njs.fix_all(proj)
    if got:
        _save(p, proj)
        out.update(wrote=True, line='見え始める距離（JD）を整えた: ' + '・'.join(
            f'{diffs.TEXT[diffs.name_of(k)]} {before:.1f}→{r["jd"]:.1f}m' for k, before, r in got))
    return out


def post(b):
    p = C.out_file(b['file'])
    if C.busy(p.name):
        raise ValueError('この曲は今作り直している・展開している（終わってから変える）')
    mode = b.get('mode') or 'set'
    if mode not in ('set', 'sync'):
        raise ValueError('mode は set か sync')
    if 'base' in b:   # 作業ファイルにも書く（画面は自分で保存してから base を付けずに呼ぶ＝自動の保存と取り合わない）
        v = _value(b['base'])
        w = C.load_work(p)
        if njs.decided(w) != v or (v is None and 'njs' in w):
            if v is None:
                w.pop('njs', None)
            else:
                w['njs'] = {'base': v}
            C.save_work(p, w)
    wrote, line = apply(p, mode)
    return dict(state(p, wait=0), wrote=wrote, line=line)


def get(q):
    p = C.out_file(q['file'])
    wait = q.get('wait')
    return state(p, wait=None if wait in (None, '', 'no') else max(0.0, min(float(wait), 30.0)))


def compose_extra(p, w):
    """作り直し（server の COMPOSE_EXTRA・別の案にも効く）: 3D で決めた基準の NJS があれば --njs-base（基準はその値そのまま）"""
    v = njs.decided(w)
    return ['--njs-base', f'{v:g}'] if v is not None else []


def _guard(fn):
    """思わぬ失敗も 400（server は ValueError・FileNotFoundError・KeyError だけを 400 にする）"""
    def w(arg):
        try:
            return fn(arg)
        except (ValueError, FileNotFoundError, KeyError):
            raise
        except Exception as e:   # noqa: BLE001
            raise ValueError(f'{type(e).__name__}: {e}')
    return w


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})。compose の引数の口（ctx.COMPOSE_EXTRA）にも登録する"""
    global C
    C = ctx
    if compose_extra not in ctx.COMPOSE_EXTRA:
        ctx.COMPOSE_EXTRA.append(compose_extra)
    return {'/api/njs': _guard(get)}, {'/api/njs': _guard(post), '/api/njs/jd': _guard(fix_jd)}
