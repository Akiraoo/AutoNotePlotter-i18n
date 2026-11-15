"""難易度の展開（docs/アプリ仕様.md 17 節）: 今の譜面（基準）をどの難易度に置くか・上と下をいくつ作るかを決め、基準から派生の難易度を作る。
server.py の connect() が routes(ctx) を呼んでつなぐ（ctx＝server モジュール）。画面は static/js/expand.js。

- 派生は「展開する」を押した時だけ作り直す（基準を作り直しても派生はそのまま）。派生ごとに compose を1つ
  （`ctx.compose_cmd(写し, 表, out=写し, diff=派生, extra=['--derive-from', 基準, '--ratio', 割合, '--library', JSON])`・COMPOSE_EXTRA は付けない）。
  基準の報告があれば `--base-report`（写しの隣には無い＝同じ音楽の区間の組を派生でもそろえる・automap/derive.py の rep_groups・2026-11-11）。
  派生の難易度にもう譜面があれば、作る側の決まりどおり作ったままのクリップだけ入れ替える（NLM で直した・固定・利用者のクリップは残る）。
- **派生は並べて作る**（2026-11-02 利用者「展開する難易度を並列で計算できるように。データが混ざらないように注意」）: 派生ごとに結果のファイルの
  作業用の写し（`<out>/.expand/<作業>/<難易度>/<結果のファイルの名前>`・こちらで書いたままなら指紋も＝compose が old/ に控えを取らない）を作り、
  compose の入力と --out をその写しにして同時に動かす。全部終わったら本物の結果のファイルを読み直し、派生の難易度の中身（difficulties の
  その難易度のキーの物）・書き出す印・njsCfg のその難易度のキーの物（compose が決めた NJS）だけを写しから入れ替えて保存（基準・ほかの
  難易度・ほかの項目は本物のまま・`put_diff`）。写しの
  notesLanes が本物と違えば入れ替えずに失敗に。派生の報告は写しの隣にできるので `diffs.report_path(本物, 難易度)` へ移す。写しは終わったら消す
  （失敗した時は残して記録に場所を書く）。
  入れ子: 間引く派生（割合 < 1）は入れ子の相手に「基準との間の難易度で派生に一番近い物」の譜面を読む（derive.nest_pick）。その相手を
  同じ展開で一緒に作るなら、できた譜面を待たずに、作る側がその派生と同じ決まりで間引いた打点で見込む（compose --derive-with・`deps`・
  PREDICT）＝全部の派生を同時に始められる（2026-11-02・前は相手ができるのを待っていて、Expert+ から下 2 つは順だった）。
  相手が足す派生（割合 ≥ 1・見込めない）の時だけ待つ。足す派生はほかの難易度を読まない＝すぐ始める。
- 作業（start_job・kind='expand'）の段: 控え（`<out>/old/<名前>.展開前.<時刻>.nlmf`＋履歴）→（基準の置き直し）→ 派生を作る（並べて）。
  派生を作る前に基準の NJS も作り直しと同じ決まりで書く（`base_njs`・NLM で決めた値は触らない。NJS の仕組みより前に作った基準は空で、
  NLM の既定 10 のまま遊ぶことになった＝2026-11-03 ハロのハード）。3D で決めた基準の NJS（作業ファイルの njs.base・app/njsbase.py）があれば
  基準はその値・派生は「決めた値＋（派生の式 − 基準の式）」（compose --njs-base・--njs-base-formula＝基準の式はここで 1 回だけ測る）。
  派生ごとの進み具合は job['par']（[{diff, state: waiting|running|done|error|cancelled|skipped, after, started, took, last, error,
  stars（作り終えた派生の★・None＝測っている・False＝測れない・無い＝測らない）}]）。
  ★は作り終えた派生から写しで測り始める（`_prerate`・2026-11-09）＝★の控えは中身の指紋なので、本物へ入れた後に画面が聞くとすぐ返る。
  やめる（/api/expand/cancel）と全部の compose を止める（作り終えた派生は入れ替える）。1つが失敗しても、ほかはそのまま終わらせ、できた物
  だけ入れ替える（失敗した派生を待っていた派生は作らない＝skipped）。派生ごとの結果（ノーツ・1秒のノーツ・基準に対する割合・崩れ・警告・
  報告の大事な行）を job['results'] に。
- 量の既定の刻み（1段ごとに ±何%・diffs.ratio）は app/config.local.json の expand_step_pct（無ければ diffs.STEP_PCT＝10）。窓の「既定にする」で
  書く（ほかの項目はそのまま・一時ファイルに書いてから置き換える）。
- 基準の置き直し: `diffs.move`（入れ替える時は swap）＋作ったままのクリップの id を移した先の難易度のキーで付け直す（id＝中身の指紋は
  難易度のキーを含む＝付け直さないと全部「手で直した」に見え、次の作り直しで入れ替わらない）。保存は `ctx.cli._save`（書いた時の指紋も）。
  作業ファイルの diff（基準）は画面が変えて保存してから始める（PUT /api/work は作業ファイルを丸ごと置き換える＝ここでは書かない）。
- 作業ファイルの expand（最後に展開した設定・画面が書く）: {at, from, base, up, down, step_pct, targets: [{diff, ratio, auto_ratio,
  mode: 'plan'|'band', library（絞り込み・null＝曲の設定）, over: {freq, hard}（行で選んだ型の頻度・置き方の難しさ・選んだ物だけ）}]}。
  前の mode 'themes'（今の型）は除いた（画面は既定の行として読む）。
  auto_ratio＝量を既定のまま（次に開いた時はその時の刻みの既定）。画面で「作り直す」を外した派生は送らない（今の譜面のまま・expand には
  前に作った時の設定を残す・2026-11-03）＝ここは送られた派生だけを作る。
- 型の範囲の時期が自動（years＝'auto'・library_use.AUTO）: 派生の既定は、年を絞らずに
  派生の★の帯を決めてから、その帯でのこの曲の時期で derive.default_plan に数えさせ、派生の型の範囲は時期を自動のまま compose へ渡す
  （compose が派生の★の帯で同じ決まりで置き換える・_plan_auto）。
  画面に出す短い説明・数は、その派生の絞り込みをこの曲で置き換えた物（compose と同じ）。

受け口:
  GET  /api/expand?file=          今の難易度の一覧（ノーツ・1秒・中身の種類）・基準・前に展開した設定・量の既定の刻み（step_pct）
  POST /api/expand/plan           {file, base, targets, step_pct}＝派生の既定（automap.derive.default_plan・型の範囲は覚えておく）
  POST /api/expand/step           {step_pct}＝量の既定の刻みを設定（app/config.local.json の expand_step_pct）に書く
  POST /api/expand/start          {file, from, base, swap, targets: [{diff, ratio, library}], dry}（dry＝確かめるだけ）
  POST /api/expand/cancel         {id}
  GET  /api/expand/jobs?file=     この曲の展開の作業（新しい順・画面を開き直した時に続きを見る）
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automap import diffs, nlmf, njs  # noqa: E402
from automap import library_use as LU  # noqa: E402

C = None                       # server モジュール（OUT 等は呼ばれた時に読む＝--out で変えられる）
KIND = 'expand'
RATIO_RANGE = diffs.RATIO_RANGE   # 量の割合（基準の1秒のノーツに対する）の受け付ける範囲
STEP_KEY = 'expand_step_pct'      # 量の既定の刻み（%）の設定の項目（app/config.local.json）
STEP_LIMITS = (1, 50)             # 刻みの受け付ける範囲（%）
WORK = '.expand'                  # 並べて作る派生の作業用の写しの場所（<out>/.expand/<作業>/）
PREDICT = True                    # 一緒に作る間の派生（割合 < 1）を待たずに見込んで入れ子にする（deps・compose --derive-with）。False＝できるのを待つ
PRERATE = True                    # 作り終えた派生から★を測り始める（_prerate・2026-11-09）。False＝前と同じ（画面が展開の後に測る）
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_PLANS, _PLAN_LOCK = {}, threading.Lock()   # (基準, 派生, 曲の絞り込み, データベースの印) → 既定（型の範囲・刻みに依らない所）
_PROCS = {}                       # 作業の id → {難易度: 動いている compose}（job に入れると /api/job で JSON にできない）
_LOG_LOCK = threading.Lock()      # 並べた compose の出力を job['log'] へ足す時
# 報告の数字の表で見る行（automap/__main__ の打ち方の数字）
NUM_KEYS = {'ノーツ': 'notes', '1秒のノーツ': 'nps', '両手同時': 'both', '振りの交互の崩れ': 'broken',
            'NLM の振りの警告と同じ決まり（回）': 'warn', '同じ手が0.12秒未満で続く（回）': 'fast'}


# ---- 今の難易度 ----

def _span_nps(proj, ns):
    """ノーツ（拍の順）→ 1秒のノーツ（最初から最後のノーツまでの秒で割る＝画面の library.js の measureNow と同じ）"""
    if len(ns) < 2:
        return None
    tm = nlmf.tempo_of(proj)
    t0, t1 = tm.sec(ns[0]['beat']), tm.sec(ns[-1]['beat'])
    return round(len(ns) / (t1 - t0), 3) if t1 > t0 else None


def diff_state(proj, d, as_written):
    """難易度 d の中身 → {notes, nps, clips: {app, edited, fixed, user, legacy}, lights, kind}。kind＝empty（ノーツもライトも無い）・
    auto（作ったクリップがある）・user（ノーツは利用者のクリップだけ）"""
    k = diffs.key(d)
    st = proj['difficulties'][k]
    ns = nlmf.clip_notes(proj, k, include_muted=True)
    cls, _, _ = nlmf.classify(proj, k, as_written)
    cnt = {s: 0 for s in ('app', 'edited', 'fixed', 'user', 'legacy')}
    for _, c in cls:
        cnt[c] = cnt.get(c, 0) + 1
    lights = bool(st.get('lightEvents')) or any(s.get('lk') == 'l' for s in st.get('sections') or [])
    auto = cnt['app'] + cnt['edited'] + cnt['fixed'] + cnt['legacy']
    kind = 'empty' if not ns else 'auto' if auto else 'user'
    return {'notes': len(ns), 'nps': _span_nps(proj, ns), 'clips': cnt, 'lights': lights, 'kind': kind}


def _last(w):
    e = (w or {}).get('expand')
    return e if isinstance(e, dict) else None


def info(p):
    """GET /api/expand: 結果のファイルの難易度の一覧（Easy〜Expert+ の順・無い難易度も）・基準・前に展開した設定"""
    w = C.load_work(p)
    base = C.base_diff(p, w)
    last = _last(w)
    out = {'file': p.name, 'exists': p.exists(), 'base': base, 'expand': last, 'busy': C.busy(p.name),
           'order': list(diffs.ORDER), 'text': dict(diffs.TEXT), 'njs': dict(diffs.NJS), 'step_pct': step_pct(), 'step_default': diffs.STEP_PCT,
           'step_limits': list(STEP_LIMITS),
           'library': w.get('library'), 'library_short': _short(LU.normalize(w.get('library')), C.song_of(p)),
           'ratio_range': list(RATIO_RANGE), 'diffs': []}
    if not p.exists():
        return out
    proj = nlmf.load(p)
    aw = not C.cli._edited_since_written(p)
    ex = diffs.export_marks(proj)
    made = {t.get('diff') for t in (last or {}).get('targets') or []}
    nj = proj.get('njsCfg') if isinstance(proj.get('njsCfg'), dict) else {}
    out['njs_base'] = njs.decided(w)   # 3D で決めた基準の NJS（無い＝式のまま）
    out['njs_base_used'], out['njs_base_from'] = njs.base_value(proj, diffs.key(base), out['njs_base'])   # 派生の元（NLM で直した値が勝つ）
    for d in diffs.ORDER:
        row = {'diff': d, 'text': diffs.TEXT[d], 'exists': diffs.key(d) in proj['difficulties'], 'export': bool(ex.get(d)),
               'base': d == base, 'report': diffs.report_path(p, d).exists(), 'derived': d in made and d != base}
        if row['exists']:
            row.update(diff_state(proj, d, aw))
            v = nj.get(diffs.key(d))
            row['njs'] = v.get('njs') if isinstance(v, dict) else v if isinstance(v, (int, float)) else diffs.NJS[d]
            row['njs_user'] = njs.user_value(v) is not None   # NLM で決めた値
            if d == base and out['njs_base'] is not None:
                row['njs_decided'] = out['njs_base']   # 3D で決めた基準の NJS（NLM で直されていれば row['njs'] は NLM の値）
        out['diffs'].append(row)
    return out


# ---- 量の既定の刻み（app/config.local.json の expand_step_pct） ----

def _step_value(v):
    """刻み（%）の値 → 数（1 桁に丸める・整数なら int）。数でない・範囲の外は ValueError"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'量の刻みが数でない: {v}')
    if not STEP_LIMITS[0] <= v <= STEP_LIMITS[1]:
        raise ValueError(f'量の刻みは {STEP_LIMITS[0]}〜{STEP_LIMITS[1]}%（{v:g}）')
    v = round(v, 1)
    return int(v) if v == int(v) else v


def step_pct():
    """派生の量の既定の刻み（1段ごとに ±何%）: 設定の expand_step_pct・無い・読めない・範囲の外なら diffs.STEP_PCT"""
    try:
        cfg = json.loads(Path(C.CONFIG).read_text(encoding='utf-8'))
        return _step_value(cfg[STEP_KEY])
    except (OSError, ValueError, KeyError, TypeError):
        return diffs.STEP_PCT


def set_step(b):
    """POST /api/expand/step {step_pct} → 設定（app/config.local.json）の expand_step_pct に書く。ほかの項目・字下げ・行の終わりはそのまま、
    一時ファイルに書いてから置き換える（書いている途中で止まっても設定を壊さない）。設定が読めない時は書かない"""
    from automap import config
    v = _step_value(b.get('step_pct'))
    config.update({STEP_KEY: v}, C.CONFIG)
    return {'ok': True, 'step_pct': v}


# ---- 派生の既定 ----

def _db_stamp():
    try:
        q = LU.library_db.db_path()
        return str(q), q.stat().st_mtime
    except Exception:   # noqa: BLE001  （データベースが無い PC）
        return None


def _short(f, song):
    """型の範囲の短い説明（時期が自動なら、この曲の時期も＝「時期自動（2021〜23）」）"""
    if f and f.get('years') == LU.AUTO:
        import library as AL   # noqa: E402  （app/ の中・曲ごとの時期）
        return LU.label(AL.auto_view(f, song)[2], True)
    return LU.label(f, True)


def _plan_auto(base, target, library, step, song):
    """時期が自動の曲の派生の既定: 派生の型の範囲は時期を自動のまま compose へ（compose が派生の絞り込み＝★の帯をずらした物で
    この曲の時期に置き換える。★の帯で年ごとの曲の数が変わる＝基準と違う時期になり得る）。ここも同じ決まりで:
    ① 年を絞らずに derive.default_plan で派生の★の帯を決める ② その絞り込みでのこの曲の時期（app/library.auto_view）
    ③ その時期でもう一度 derive.default_plan（低い難易度を足すか・★の上を戻すかをその時期の型の数で決める）。
    auto_years＝派生の絞り込みでのこの曲の時期（compose と同じ）。③ で★が変わって時期も変われば数え直して note に足す"""
    from automap import derive
    import library as AL   # noqa: E402

    def auto_of(r):
        lib = {k: v for k, v in r['library'].items() if k not in ('years', 'auto_years', 'year_set', 'auto_v')}
        lib['years'] = LU.AUTO
        if isinstance(library, dict) and library.get('auto_v'):   # 自動の決め方の版は基準の物のまま（新しい決め方・前の決め方）
            lib['auto_v'] = library['auto_v']
        lib = LU.normalize(lib)
        return (lib,) + AL.auto_view(lib, song)
    f0 = LU.concrete(LU.normalize(library))
    r0 = dict(derive.default_plan(base, target, f0, step))
    if not isinstance(r0.get('library'), dict):   # 型の範囲が無い（数えられない）
        return r0
    lib, tf, got, shown = auto_of(r0)
    if got:
        r1 = dict(derive.default_plan(base, target, dict(f0, year_set=list(got)), step))
        if isinstance(r1.get('library'), dict):
            r0 = r1
            lib, tf, got2, shown = auto_of(r0)
            if got2 != got:
                try:
                    k = LU.counts(tf)['themes']
                    r0['lib_note'] = '・'.join(filter(None, [r0.get('lib_note'), f'★を戻したので時期も変わる（テーマに使える型 {k}）']))
                except LU.ERRORS:
                    pass
            got = got2
    r0['library'], r0['auto_years'] = lib, got
    r0['lib_note'] = '・'.join(filter(None, [r0.get('lib_note'), f'時期はこの曲の自動（この★の帯で {LU.years_text(got)} 年）' if got else
                                             '時期は自動（年ごとの曲の数を数えられないので年は絞らない）']))
    r0['short'] = LU.label(shown, True)
    return r0


def default_plan(base, target, library, step=None, song=None):
    """派生の既定（automap.derive.default_plan＝{ratio, library, note, lib_note}）＋ short（型の範囲の短い説明）・step_pct。型の範囲は
    数えるのに 0.3〜1.4 秒かかるので覚えておく（量の刻みに依らない）。量と note の頭は刻み（step・None＝設定の刻み）から。
    song＝曲の名前（型の範囲の時期が自動の時に、この曲の時期で数える）"""
    from automap import derive
    step = step_pct() if step is None else step
    auto = isinstance(library, dict) and library.get('years') == LU.AUTO
    key = (base, target, json.dumps(library, sort_keys=True, ensure_ascii=False), _db_stamp(), song if auto else None)
    with _PLAN_LOCK:
        r0 = _PLANS.get(key)
    if r0 is None:
        r0 = _plan_auto(base, target, library, step, song) if auto else dict(derive.default_plan(base, target, library, step))
        if 'short' not in r0:
            r0['short'] = LU.label(r0.get('library'), True)
        with _PLAN_LOCK:
            if len(_PLANS) > 200:
                _PLANS.clear()
            _PLANS[key] = r0
    return dict(r0, ratio=diffs.ratio(base, target, step), step_pct=step,
                note='・'.join(filter(None, [derive.ratio_note(base, target, step), r0.get('lib_note')])))


def plans(b):
    """POST /api/expand/plan {file, base, targets: [難易度…], step_pct（無ければ設定の刻み）} → {plans: {難易度: 既定}, step_pct}"""
    p = C.out_file(b['file'])
    lib = C.load_work(p).get('library')
    base = diffs.name_of(b['base'])
    step = step_pct() if b.get('step_pct') is None else _step_value(b['step_pct'])
    out = {}
    for t in b.get('targets') or []:
        t = diffs.name_of(t)
        if t != base:
            out[t] = default_plan(base, t, lib, step, C.song_of(p))
    return {'base': base, 'plans': out, 'step_pct': step}


# ---- 報告 ----

def summary(md):
    """派生の報告（<結果>.<難易度>.report.md）→ {head: 頭の行, nums: {notes, nps, both, broken, warn, fast}, derive: 派生の節の行}"""
    head, nums, der, sec = [], {}, [], None
    for ln in (md or '').splitlines():
        if ln.startswith('## '):
            sec = ln[3:].strip()
            continue
        s = ln.strip()
        if s.startswith('|'):
            cells = [c.strip() for c in s.strip('|').split('|')]
            if len(cells) >= 2 and cells[0] in NUM_KEYS:
                nums[NUM_KEYS[cells[0]]] = cells[-1]   # 派生の報告は「基準 … | 派生 …」の 2 列＝後ろの列
            continue
        if not s.startswith('- '):
            continue
        t = s[2:].replace('**', '')
        if sec is None:
            head.append(t)
        elif re.search('派生|展開|難易度', sec):
            der.append(t)
    return {'head': head, 'nums': nums, 'derive': der}


def result_of(p, d, base, want):
    """作った派生の結果: ファイルから数えたノーツ・1秒のノーツ・基準に対する割合と、報告の要点"""
    r = {'diff': d, 'text': diffs.TEXT[d], 'want': want}
    try:
        proj = nlmf.load(p)
        aw = not C.cli._edited_since_written(p)
        s, sb = diff_state(proj, d, aw), diff_state(proj, base, aw)
        r.update(notes=s['notes'], nps=s['nps'], clips=s['clips'], base_nps=sb['nps'],
                 got=round(s['nps'] / sb['nps'], 3) if s['nps'] and sb['nps'] else None)
    except (OSError, ValueError, KeyError) as e:
        r['error'] = f'結果のファイルを読めなかった: {e}'
    rp = diffs.report_path(p, d)
    if rp.exists():
        md = rp.read_text(encoding='utf-8')
        r.update(summary(md))
        r['report'] = md
    else:
        r['no_report'] = True
    return r


# ---- 作業 ----

def _norm_target(t, base):
    d = diffs.name_of(t.get('diff'))
    if d == base:
        raise ValueError(f'{diffs.TEXT[d]} は基準（派生にできない）')
    try:
        ratio = float(t.get('ratio'))
    except (TypeError, ValueError):
        raise ValueError(f'{diffs.TEXT[d]} の量の割合が数でない: {t.get("ratio")}')
    if not RATIO_RANGE[0] <= ratio <= RATIO_RANGE[1]:
        raise ValueError(f'{diffs.TEXT[d]} の量の割合は {RATIO_RANGE[0]:g}〜{RATIO_RANGE[1]:g} 倍（{ratio:g}）')
    lib = t.get('library')
    lib = LU.normalize(lib) if isinstance(lib, dict) and lib else None
    return {'diff': d, 'ratio': round(ratio, 4), 'library': lib}


def check(b):
    """展開の頼み → (p, 前の基準, 新しい基準, swap, 派生の並び, 知らせ)。だめなら ValueError"""
    p = C.out_file(b['file'])
    if not p.exists():
        raise ValueError('結果のファイルがまだ無い（先に作り直して基準の譜面を作る）')
    if C.busy(p.name):
        raise ValueError('この曲は今作り直している（終わってから展開する）')
    src = diffs.name_of(b.get('from') or C.base_diff(p))
    dst = diffs.name_of(b.get('base') or src)
    proj = nlmf.load(p)
    if diffs.key(src) not in proj['difficulties']:
        raise ValueError(f'結果のファイルに基準の難易度 {diffs.TEXT[src]} が無い')
    aw = not C.cli._edited_since_written(p)
    if not diff_state(proj, src, aw)['notes']:
        raise ValueError(f'基準の難易度 {diffs.TEXT[src]} にノーツが無い（先に作り直す）')
    swap, notes = bool(b.get('swap')), []
    occupied = None
    if dst != src and diffs.key(dst) in proj['difficulties']:
        s = diff_state(proj, dst, aw)
        if s['notes'] or s['lights']:
            occupied = s
    if occupied and not swap:
        e = ValueError(f'{diffs.TEXT[dst]} にはもう譜面がある（ノーツ {occupied["notes"]}'
                       f'{"・ライト" if occupied["lights"] else ""}）。入れ替えるなら swap')
        e.need_swap = True
        raise e
    if dst != src:
        notes.append(f'基準を {diffs.TEXT[src]} から {diffs.TEXT[dst]} へ置き直す' +
                     (f'（今の {diffs.TEXT[dst]} の譜面は {diffs.TEXT[src]} へ入れ替える）' if occupied else ''))
    ts, seen = [], set()
    for t in b.get('targets') or []:
        t = _norm_target(t, dst)
        if t['diff'] in seen:
            raise ValueError(f'{diffs.TEXT[t["diff"]]} が2つある')
        seen.add(t['diff'])
        ts.append(t)
    if not ts and dst == src:
        raise ValueError('作る難易度が無い（上か下を1つ以上）')
    ts.sort(key=lambda t: (diffs.steps(dst, t['diff']) < 0, abs(diffs.steps(dst, t['diff']))))   # 上（近い順）→ 下（近い順）。どれも基準から作る
    return p, src, dst, swap and bool(occupied), ts, notes


def _stamp():
    return time.strftime('%Y%m%d-%H%M%S')


def backup(p, job):
    """展開の前の結果のファイルを <out>/old/<名前>.展開前.<時刻>.nlmf に（履歴にも・どの版とも違えば）"""
    old = p.parent / 'old'
    old.mkdir(parents=True, exist_ok=True)
    stem = p.name[:-len('.nlmf')]
    dst = old / f'{stem}.展開前.{_stamp()}.nlmf'
    job['backup_aw'] = not C.cli._edited_since_written(p)   # 控えはこちらで書いたままか（戻す時に指紋も戻す）
    shutil.copy2(p, dst)
    job['backup'] = str(dst)
    job['log'] += f'控え: {dst.parent.name}/{dst.name}\n'
    v = sys.modules.get('versions')
    if v is not None and getattr(v, 'C', None) is not None:
        try:
            v.guard(p, '難易度を展開する前', diff=job.get('src'))   # 置き直す前の基準（作業ファイルの diff はもう新しい基準）
        except Exception as e:   # noqa: BLE001  （履歴に控えられなくても展開は止めない）
            job['log'] += f'（履歴の控えに失敗した: {e}）\n'


def restore_if_broken(p, job):
    """止めた・失敗した後に結果のファイルが読めなければ（compose を書いている途中で止めた等・nlmf.save は一気に書かない）、展開の前の控えに
    戻す（置き直しも作った派生も無かったことに）→ 戻したか"""
    try:
        nlmf.load(p)
        return False
    except (OSError, ValueError):
        pass
    bk = job.get('backup')
    if not bk or not Path(bk).exists():
        job['log'] += '\n結果のファイルが壊れている（読めない）。控えも無い'
        return False
    shutil.copy2(bk, p)
    sp = C.cli._state_path(p)
    if job.get('backup_aw'):   # 控えがこちらで書いたままだったなら指紋も（作ったままのクリップの判定を変えない）
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({'sha256': C.cli._sha(p), 'savedAt': nlmf.load(p).get('savedAt')}), encoding='utf-8')
    else:
        sp.unlink(missing_ok=True)
    job.update(restored=True, moved=False, results=[])
    job['log'] += f'\n結果のファイルが壊れていた（書いている途中で止まった）＝展開の前の控え {Path(bk).name} に戻した'
    return True


def move_base(p, src, dst, swap, log=None):
    """基準の難易度 src を dst へ置き直す（diffs.move）。作ったままのクリップの id を移した先のキーで付け直し、派生の報告も一緒に移す。
    → 付け直したクリップの数"""
    proj = nlmf.load(p)
    aw = not C.cli._edited_since_written(p)
    keep = {}
    for d in (src, dst):
        k = diffs.key(d)
        if k in proj['difficulties']:
            cls, _, _ = nlmf.classify(proj, k, aw)
            keep[d] = [s for s, st in cls if st == 'app' and s.get('id') == nlmf.clip_id(k, s)]
    diffs.move(proj, src, dst, swap=swap)
    n = 0
    for was, now in ((src, dst), (dst, src)):
        if was == dst and not swap:
            continue
        nk = diffs.key(now)
        for s in keep.get(was, []):
            s['id'] = nlmf.clip_id(nk, s)
            n += 1
    C.cli._save(proj, p)
    # 派生の報告: 入れ替えた時は dst の報告（今は src にある中身の物）を src の名前へ。入れ替えない時に dst の報告が残っていたら（中身の無い難易度の古い報告）控えへ
    rd, rs = diffs.report_path(p, dst), diffs.report_path(p, src)
    if rd.exists():
        if swap:
            rd.replace(rs)
        else:
            (p.parent / 'old').mkdir(parents=True, exist_ok=True)
            rd.replace(p.parent / 'old' / f'{rd.name[:-len(".report.md")]}.展開前.{_stamp()}.report.md')
    if log is not None:
        log(f'基準を {diffs.TEXT[src]} → {diffs.TEXT[dst]}' + (f'（{diffs.TEXT[dst]} の譜面は {diffs.TEXT[src]} へ）' if swap else '') +
            f'・作ったままのクリップの id を付け直した {n}')
    return n


def base_njs(p, base, log=None):
    """基準の NJS を作り直し（compose）と同じ決まりで書く（`C.cli._set_njs` → njs.apply）→ 書き換えたら True。
    NJS を書く仕組み（2026-11-02）より前に作った基準は njsCfg にその難易度の項目が無く、展開した派生だけ式の NJS になって、基準は
    NLM の既定（Easy〜Hard 10）のままだった（ハロのハード・2026-11-03 利用者「基準にしたハードの NJS が元の 10 のままで凄く切りにくかった」）。
    置き直した基準の NJS がアプリの書いた値（auto と同じ）なら、移した先の難易度の式で書き直す（diffs.move は NJS ごと移す＝Expert+ の値の
    まま Hard になる）。NLM で利用者が決めた値（auto と違う）は触らない（★も測らない）。NLM で直された後のファイルなら書いた時の指紋は
    残さない（「NLM で直された」の判定をそのままに）"""
    proj = nlmf.load(p)
    k = diffs.key(base)
    if k not in proj['difficulties']:
        return False
    e = (proj.get('njsCfg') or {}).get(k)
    before = json.dumps(e, sort_keys=True)
    if isinstance(e, dict) and e.get('njs') is not None and e.get('auto') != e.get('njs'):
        # NLM で決めた NJS: そのまま。アプリが前に NJS を書いた難易度なら見え始める距離はその NJS で整える（njs.fix_all と同じ決まり）
        r = njs.fix_jd(proj, k) if e.get('auto') is not None else {'state': 'none'}
        if log:
            t = njs.jd_text(r)
            log(f'基準（{diffs.TEXT[base]}）の NJS: {e["njs"]:g}（NLM で決めた値のまま）' + (f'・{t}' if t else ''))
        if r['state'] != 'wrote':
            return False
        _save_njs(p, proj)
        return True
    # 3D で決めた基準の NJS（作業ファイルの njs.base・2026-11-09）があればその値そのまま（置き直した基準にも＝決めた値は基準に付いていく）
    line = C.cli._set_njs(proj, k, nlmf.tempo_of(proj), base=njs.decided(C.load_work(p)))
    if log and line:
        log(f'基準（{diffs.TEXT[base]}）の {line[2:]}')
    if json.dumps(proj['njsCfg'].get(k) if isinstance(proj.get('njsCfg'), dict) else None, sort_keys=True) == before:
        return False
    _save_njs(p, proj)
    return True


def _save_njs(p, proj):
    if C.cli._edited_since_written(p):   # NLM で直された後のファイル＝書いた時の指紋は残さない
        nlmf.save(proj, p)
    else:
        C.cli._save(proj, p)


def njs_from_base(p, base, log=None):
    """派生の NJS の元にする基準の NJS → (基準の NJS, 基準の式の値)。式のままなら (None, None)。基準の NJS は最後に決めた方
    （njs.base_value・2026-11-09 利用者）: 基準が NLM で直されていればその値（3D の「譜面に使う」が OFF でも）・無ければ 3D で決めた値
    （作業ファイルの njs.base）。派生の NJS＝基準の NJS＋（派生の式 − 基準の式）（njs.from_base）の、基準の式の値をここで 1 回だけ測る
    （今の基準の★・BPM・難易度・★は式の値の速さで測り直す＝njs.settle）。測れなければ基準の式は None（compose が自分で測る）"""
    proj = nlmf.load(p)
    k = diffs.key(base)
    if k not in proj['difficulties']:
        return None, None
    nb, src = njs.base_value(proj, k, njs.decided(C.load_work(p)))
    if nb is None:
        return None, None
    fb, how = C.cli._njs_formula(proj, k, nlmf.tempo_of(proj), settle=True)   # 式の値の速さの★で（決めた値の速さで測ると 0.5 ずれる）
    if log:
        log(f'派生の NJS は {njs.BASE_FROM[src]} {nb:g} から（基準の式 ' + (f'{fb:g}＝{how}' if fb is not None else f'は測れない: {how}') +
            '・派生ごとに 基準の NJS＋派生の式−基準の式）')
    return nb, fb


def base_mark(p, base, log=None):
    """基準の書き出す印がまだ誰も決めていなければ付ける（diffs.mark_default・作り直しと同じ決まり。NLM で外した印は触らない）→ 付けたか。
    印の決まりより前に作った基準（印が空の結果のファイル）を展開した時のため（Joy to the love の Hard・2026-11-03）。保存の仕方は base_njs と同じ"""
    proj = nlmf.load(p)
    if not diffs.mark_default(proj, base):
        return False
    if C.cli._edited_since_written(p):
        nlmf.save(proj, p)
    else:
        C.cli._save(proj, p)
    if log:
        log(f'基準（{diffs.TEXT[base]}）に書き出す印を付けた（まだ決めていなかった）')
    return True


def mark_export(p, d, log=None):
    """作った派生に書き出す印が無ければ付ける（展開した＝書き出したい。元からあった空の難易度＝NLM の新しいプロジェクトの Hard は
    compose が印を付けなかった・2026-11-02）。付けたら書いた時の指紋も残して保存"""
    proj = nlmf.load(p)
    if diffs.export_marks(proj).get(d) or diffs.key(d) not in proj['difficulties']:
        return False
    diffs.set_export(proj, d, True)
    C.cli._save(proj, p)
    if log:
        log(f'{diffs.TEXT[d]} に書き出す印を付けた')
    return True


def _say(job, text):
    with _LOG_LOCK:
        job['log'] += text.rstrip('\n') + '\n'


def _prerate(job, row, path, d):
    """★を先に測り始める（2026-11-09 利用者「計算の終わった難易度は先に★の計算を始めれば早く出る」）: 派生は作り終えた所で作業用の
    写しから（全部の派生ができて本物へ入れるのを待たない）・基準は派生を作り始める時に。★の控え（<out>/.rating/・app/rating）は
    頼みの中身（その難易度の見えるノーツ・NJS・テンポ）の指紋＝本物へ入れ替えた後に画面が /api/rating で聞くと、同じ中身なので測り直さずに
    すぐ返る（put_diff は難易度の中身と njsCfg のその項目を丸ごと写す・テンポは同じ）。入れなかった派生（やめた・失敗・レーンの数が違う）の
    答えは控えに残るだけ＝本物のファイルの★と食い違わない。row があれば進み具合の表に出す（row['stars']: None＝測っている・数・False＝測れない）"""
    R = sys.modules.get('rating')   # app/rating（server がつないだ口だけ・テストで別の口のまま本物の nlm-rating を動かさない）
    if not PRERATE or R is None or getattr(R, 'C', None) is not C or not hasattr(R, 'prefetch'):
        return

    def then(a):
        if row is not None:
            row['stars'] = a['stars'] if a.get('ok') and not a.get('skipped') and a.get('stars') is not None else False
    try:
        if row is not None:
            row['stars'] = None
        if not R.prefetch(path, d, then) and row is not None:   # nlm-rating が無い
            row.pop('stars', None)
    except Exception as e:   # noqa: BLE001  （★を測れなくても展開は止めない）
        if row is not None:
            row['stars'] = False
        _say(job, f'[{diffs.TEXT[d]}] ★を先に測れなかった: {e}')


# ---- 派生を並べて作る ----

def deps(base, ts, predict=None):
    """派生ごとの待ち合わせ {難易度: {'after': [先に作り終えていないといけない派生], 'with': {見込む派生: 割合}}}。ts＝check の並び
    （上の近い順 → 下の近い順＝前に1つずつ作っていた順）。間引く派生（割合 < 1）は入れ子の相手に「基準との間の難易度」と「下の難易度」の
    譜面を読む（derive.nest_pick）。下の難易度は1つずつなら後で作っていた＝作る前の物を読む（写しは展開を始めた時の物＝同じ）。
    間の難易度で一緒に作る派生は、predict（既定 PREDICT）なら待たずに作る側が同じ決まりで間引いた打点で見込む（compose --derive-with・
    全部を同時に始められる）。間引かない派生（割合 ≥ 1＝足す）は見込めないので待つ。predict が偽なら全部待つ（前の作り）。
    足す派生・同じ量の派生はほかの難易度を読まない"""
    predict = PREDICT if predict is None else predict
    bi = diffs.ORDER.index(base)
    out = {}
    for t in ts:
        ti = diffs.ORDER.index(t['diff'])
        lo, hi = sorted((bi, ti))
        mid = [e for e in ts if t['ratio'] < 1 - 1e-6 and lo < diffs.ORDER.index(e['diff']) < hi]
        out[t['diff']] = {'after': [e['diff'] for e in mid if not (predict and e['ratio'] < 1 - 1e-6)],
                          'with': {e['diff']: e['ratio'] for e in mid if predict and e['ratio'] < 1 - 1e-6}}
    return out


def work_dir(p, jid):
    return p.parent / WORK / jid


def put_diff(proj, src, d):
    """派生 d の中身（difficulties の d のキーの物）・書き出す印・NJS（njsCfg の d のキーの物＝compose が★・BPM・難易度から決めて書く）を、
    写し src から proj へ入れ替える（写しに無い物と、ほかの難易度・ほかの項目は proj のまま）"""
    k = diffs.key(d)
    if k not in src['difficulties']:
        raise ValueError(f'写しに {diffs.TEXT[d]} が無い')
    proj['difficulties'][k] = src['difficulties'][k]
    m = diffs.export_marks(src)
    if d in m:
        diffs.set_export(proj, d, bool(m[d]))
    nj = src.get('njsCfg')
    if isinstance(nj, dict) and k in nj:
        if not isinstance(proj.get('njsCfg'), dict):
            proj['njsCfg'] = {}
        proj['njsCfg'][k] = nj[k]


def make_copy(snap, written, dst, done=()):
    """作業用の写し dst（名前は結果のファイルと同じ＝compose が曲の名前を読む）: 展開を始めた時の結果のファイル snap に、先に作り終えた
    派生（done＝[(難易度, 写し)]）の中身と書き出す印を入れた物。written（こちらで書いたまま）なら書いた時の指紋も（compose が old/ に控えを
    取らない・前の形式の判定も同じ）"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if done:
        proj = nlmf.load(snap)
        for d, cp in done:
            put_diff(proj, nlmf.load(cp), d)
        nlmf.save(proj, dst)
    else:
        shutil.copy2(snap, dst)
    sp = C.cli._state_path(dst)
    if written:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({'sha256': C.cli._sha(dst)}), encoding='utf-8')
    else:
        sp.unlink(missing_ok=True)
    return dst


def _kill(pr):
    try:
        pr.kill()
    except OSError:
        pass


def _run_one(job, cmd, row, d):
    """compose を1つ動かし、出力を job['log'] へ（頭に難易度）・最後の行を row['last'] へ。やめると止める"""
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    pr = subprocess.Popen([str(c) for c in cmd], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, creationflags=NO_WINDOW)
    _PROCS.setdefault(job['id'], {})[d] = pr
    if job.get('cancel'):   # 始めた時にはもうやめていた
        _kill(pr)
    try:
        for line in iter(pr.stdout.readline, b''):
            s = line.decode('utf-8', 'replace').rstrip()
            if s.strip():
                row['last'] = s[-200:]
            _say(job, f'[{diffs.TEXT[d]}] {s}')
        pr.wait()
    finally:
        _PROCS.get(job['id'], {}).pop(d, None)
    if job.get('cancel'):
        raise RuntimeError('やめた')
    if pr.returncode:
        raise RuntimeError(f'失敗した（終了コード {pr.returncode}）')


def merge(p, snap_sha, made, log):
    """作り終えた派生（made＝[(難易度, 写し)]・1つずつ作った順）を本物の結果のファイルへ: 読み直して、派生の難易度の中身・書き出す印・
    NJS だけを写しから入れ替えて保存（put_diff）（書いた時の指紋も）・報告を移す → (入れた難易度, {入れられなかった難易度: 訳})。写しの notesLanes が本物と違う
    （レーンが足された）物は入れない。展開の間に本物が変わっていた（NLM で保存した等）時は、入れ替える前に old/ に控える"""
    proj = nlmf.load(p)
    if C.cli._sha(p) != snap_sha:
        old = p.parent / 'old'
        old.mkdir(parents=True, exist_ok=True)
        bk = old / f'{p.name[:-len(".nlmf")]}.展開中に変わった.{_stamp()}.nlmf'
        shutil.copy2(p, bk)
        log(f'展開の間に結果のファイルが変わっていた（NLM で保存した？）＝派生の難易度だけを入れ替える（入れ替える前の控え: old/{bk.name}）')
    ok, bad = [], {}
    for d, cp in made:
        try:
            src = nlmf.load(cp)
            if (src.get('notesLanes') or 1) != (proj.get('notesLanes') or 1):
                raise ValueError(f'レーンの数が違う（写し {src.get("notesLanes") or 1}・結果のファイル {proj.get("notesLanes") or 1}）＝入れ替えない')
            put_diff(proj, src, d)
            ok.append(d)
        except (OSError, ValueError, KeyError) as e:
            bad[d] = str(e)
    if ok:
        C.cli._save(proj, p)
    for d, cp in made:
        if d in ok and diffs.report_path(cp, d).exists():
            diffs.report_path(cp, d).replace(diffs.report_path(p, d))
    return ok, bad


def run_all(job, p, dst, ts, tf):
    """派生を並べて作る段: 写しを作って compose を同時に動かし（deps の順は守る）、全部終わったら作り終えた物を本物へ入れ替える。
    やめた・失敗した派生があれば最後に RuntimeError（作り終えた物は入れ替えた後）"""
    base_njs(p, dst, lambda s: _say(job, s))   # 基準の NJS も（写しを作る前＝派生の写しにも入る・本物へは派生の物だけ入れ替える）
    base_mark(p, dst, lambda s: _say(job, s))  # 基準の書き出す印も（まだ誰も決めていなければ）
    nb, fb = njs_from_base(p, dst, lambda s: _say(job, s))   # 3D で決めた基準の NJS（派生は決めた値＋式の差・2026-11-09）
    jd = work_dir(p, job['id'])
    if jd.exists():
        shutil.rmtree(jd)
    jd.mkdir(parents=True)
    snap = jd / p.name
    shutil.copy2(p, snap)
    written, snap_sha = not C.cli._edited_since_written(p), C.cli._sha(snap)
    _prerate(job, None, snap, dst)   # 基準の★も（NJS を書き直したら中身が変わる・たいていは測ってある）
    dep = deps(dst, ts)
    rows = job['par'] = [{'diff': t['diff'], 'text': diffs.TEXT[t['diff']], 'ratio': t['ratio'], 'after': [diffs.TEXT[e] for e in dep[t['diff']]['after']],
                          'with': [diffs.TEXT[e] for e in dep[t['diff']]['with']],
                          'state': 'waiting', 'started': None, 'took': None, 'last': '', 'error': None} for t in ts]
    done, failed, threads = {}, {}, []
    song_lib = LU.normalize(C.load_work(p).get('library'))   # 行の型の範囲が無い派生（既定を数えられなかった）は曲の設定
    _say(job, f'作業用の写し: {WORK}/{job["id"]}/（派生ごと）' +
         ''.join(f'・{diffs.TEXT[d]} は {"・".join(diffs.TEXT[e] for e in x["after"])} の後' for d, x in dep.items() if x['after']) +
         ''.join(f'・{diffs.TEXT[d]} は {"・".join(diffs.TEXT[e] for e in x["with"])} を見込んで入れ子に' for d, x in dep.items() if x['with']))

    def work(t, row):
        d = t['diff']
        try:
            cp = make_copy(snap, written, jd / d / p.name, [(e, done[e]) for e in dep[d]['after']])
            extra = ['--derive-from', dst, '--ratio', f'{t["ratio"]:g}']
            if diffs.report_path(p).exists():   # 基準の報告（写しの隣には無い）＝同じ音楽の区間の組を派生でもそろえる（2026-11-11）
                extra += ['--base-report', str(diffs.report_path(p))]
            if dep[d]['with']:   # 一緒に作る間の派生（入れ子の相手は作る側が見込む）
                extra += ['--derive-with', ','.join(f'{e}={r:g}' for e, r in dep[d]['with'].items())]
            lib = t['library'] or song_lib   # 行の型の範囲（無い＝数えられなかった＝曲の設定）
            extra += ['--library', json.dumps(lib, ensure_ascii=False, separators=(',', ':'))]
            if nb is not None:   # 派生の NJS＝基準の決めた値＋（派生の式 − 基準の式）（基準の式は 1 回だけ測って渡す）
                extra += ['--njs-base', f'{nb:g}'] + (['--njs-base-formula', f'{fb:g}'] if fb is not None else [])
            cmd = C.compose_cmd(cp, tf, out=cp, diff=d, extra=extra)
            _say(job, f'[{diffs.TEXT[d]}] $ compose --diff {d} --derive-from {dst} --ratio {t["ratio"]:g}' +
                 f' --library {_short(lib, C.song_of(p))}' + ('' if t['library'] else '（行の型の範囲が無いので曲の設定）'))
            _run_one(job, cmd, row, d)
            mark_export(cp, d, lambda s: _say(job, f'[{diffs.TEXT[d]}] {s}'))
            done[d] = cp
            row['state'] = 'done'
            _prerate(job, row, cp, d)   # ほかの派生を待たずに★を測り始める（写しから）
        except Exception as e:   # noqa: BLE001
            failed[d] = str(e)
            row['state'], row['error'] = ('cancelled' if job.get('cancel') else 'error'), str(e)
            _say(job, f'[{diffs.TEXT[d]}] {e}')
        finally:
            row['took'] = round(time.time() - row['started'], 1)

    while True:
        for t, row in zip(ts, rows):
            if row['state'] != 'waiting':
                continue
            d = t['diff']
            if job.get('cancel'):
                row['state'], row['error'] = 'cancelled', 'やめた'
                failed[d] = 'やめた'
                continue
            miss = [e for e in dep[d]['after'] if e in failed]
            if miss:
                row['state'] = 'skipped'
                row['error'] = f'{"・".join(diffs.TEXT[e] for e in miss)} を作れなかったので作らない（入れ子の相手）'
                failed[d] = row['error']
                continue
            if all(e in done for e in dep[d]['after']):
                row['state'], row['started'] = 'running', time.time()
                th = threading.Thread(target=work, args=(t, row), daemon=True)
                threads.append(th)
                th.start()
        if all(r['state'] not in ('waiting', 'running') for r in rows):
            break
        time.sleep(0.2)
    for th in threads:
        th.join()
    _PROCS.pop(job['id'], None)
    made = [(t['diff'], done[t['diff']]) for t in ts if t['diff'] in done]
    ok, bad = merge(p, snap_sha, made, lambda s: _say(job, s)) if made else ([], {})
    for d, why in bad.items():
        failed[d] = why
        row = next(r for r in rows if r['diff'] == d)
        row['state'], row['error'] = 'error', why
        _say(job, f'[{diffs.TEXT[d]}] {why}')
    for t in ts:
        if t['diff'] in ok:
            r = result_of(p, t['diff'], dst, t['ratio'])
            job.setdefault('results', []).append(r)
            if r.get('nps') is not None:
                _say(job, f'{diffs.TEXT[t["diff"]]}: ノーツ {r["notes"]}・1秒 {r["nps"]:.2f}' +
                     (f'（基準の {r["got"]:.2f} 倍・狙い {t["ratio"]:g}）' if r.get('got') else ''))
    job['made'] = ok
    if job.get('cancel'):
        _clean(jd)
        raise RuntimeError('やめた' + (f'（作り終えた {"・".join(diffs.TEXT[d] for d in ok)} は入れた）' if ok else ''))
    if failed:
        _say(job, f'作業用の写しは {WORK}/{job["id"]}/ に残した（失敗の記録）')
        raise RuntimeError('失敗した: ' + '・'.join(f'{diffs.TEXT[d]}（{w}）' for d, w in failed.items()) +
                           (f'。作れた {"・".join(diffs.TEXT[d] for d in ok)} は入れた' if ok else ''))
    _clean(jd)


def _clean(jd):
    """作業用の写しを消す（空なら <out>/.expand も）"""
    shutil.rmtree(jd, ignore_errors=True)
    try:
        jd.parent.rmdir()
    except OSError:
        pass


def start(b):
    """POST /api/expand/start → {id}（dry なら確かめた中身）"""
    try:
        p, src, dst, swap, ts, notes = check(b)
    except ValueError as e:
        if b.get('dry') and getattr(e, 'need_swap', False):
            return {'ok': False, 'need_swap': True, 'error': str(e)}
        raise
    hard = sorted((t['diff'] for t in ts), key=diffs.ORDER.index, reverse=True)   # 画面の並び（上＝難しい）
    labels = ['控え'] + ([f'基準を {diffs.TEXT[dst]} に置き直す'] if dst != src else []) + \
             ([f'{"・".join(diffs.TEXT[d] for d in hard)} を作る' + ('（並べて）' if len(ts) > 1 else '')] if ts else [])
    dep = deps(dst, ts)
    if b.get('dry'):
        return {'ok': True, 'need_swap': False, 'from': src, 'base': dst, 'swap': swap, 'targets': ts, 'steps': labels, 'notes': notes,
                'deps': dep}
    tf = C.write_intent(p)   # 基準と同じ意思入れの表（作業ファイルから・終わったら消す）

    def stoppable(fn):
        def w(job):
            if job.get('cancel'):
                raise RuntimeError('やめた')
            fn(job)
        return w

    def mv(job):
        move_base(p, src, dst, swap, lambda t: _say(job, t))
        job['moved'] = True
        if not ts:   # 派生を作るなら run_all の頭で
            base_njs(p, dst, lambda t: _say(job, t))
            base_mark(p, dst, lambda t: _say(job, t))

    steps = [('控え', stoppable(lambda job: backup(p, job)))]
    if dst != src:
        steps.append((labels[1], stoppable(mv)))
    if ts:
        steps.append((labels[-1], stoppable(lambda job: run_all(job, p, dst, ts, tf))))

    def after(job):
        tf.unlink(missing_ok=True)
        if job['state'] != 'done':
            restore_if_broken(p, job)
        made = [r['diff'] for r in job.get('results') or []]
        job['made'] = made
        if not made and not job.get('moved'):
            return
        v = sys.modules.get('versions')
        if v is not None and getattr(v, 'C', None) is not None:
            try:   # 展開した後の版を履歴に（戻せる）・古い別の案は消す（案を選ぶと結果のファイルが写され、派生が消えてしまう）
                what = '・'.join(diffs.TEXT[d] for d in made) or 'なし'
                v.snapshot(p, KIND, title=f'難易度を展開した（基準 {diffs.TEXT[dst]}・作った {what}）', head=False, dedupe=False,
                           diff=dst if job.get('moved') or job['state'] == 'done' else job.get('src'))
                v.drop_cands(p)
            except Exception as e:   # noqa: BLE001
                job['log'] += f'\n（履歴の控えに失敗した: {e}）'

    j = C.start_job(p.name, steps, kind=KIND, after=after, title='難易度を展開', song=C.song_of(p), base=dst, src=src, swap=swap,
                    targets=ts, notes=notes, deps=dep)
    return {'id': j['id'], 'steps': labels}


def cancel(b):
    """POST /api/expand/cancel {id}: 動いている compose を全部止める（作り終えた派生は入れ替える）"""
    j = C.JOBS.get(b.get('id'))
    if not j or j.get('kind') != KIND:
        raise KeyError('その展開の作業は無い')
    if j['state'] == 'running':
        j['cancel'] = True
        for pr in list((_PROCS.get(j['id']) or {}).values()):
            _kill(pr)
    return {'ok': True}


def jobs(q):
    p = C.out_file(q['file'])
    js = sorted((j for j in C.JOBS.values() if j.get('kind') == KIND and j.get('file') == p.name), key=lambda j: -j['started'])
    return [C.job_view(j) for j in js[:3]]


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
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})"""
    global C
    C = ctx
    return ({'/api/expand': _guard(lambda q: info(C.out_file(q['file']))), '/api/expand/jobs': _guard(jobs)},
            {'/api/expand/plan': _guard(plans), '/api/expand/step': _guard(set_step), '/api/expand/start': _guard(start),
             '/api/expand/cancel': _guard(cancel)})
