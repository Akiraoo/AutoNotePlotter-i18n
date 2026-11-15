"""作った譜面の★（nlm-rating の近似・docs/ライブラリ仕様.md 4 節）を測って画面に出す。
server.py の connect() が routes(ctx) を呼んでつなぐ。測り方は automap/rating.py（NLM の書き出しと同じ中身を nlm-rating へ）。

GET /api/rating?file=<結果のファイル>[&diff=難易度][&wait=秒] → 測った★
  - 結果のファイルがまだ無い曲は、画面に出ている土台（試作5・v0.1）を測る（server.base_of）。
  - 測る難易度は diff（file= の時だけ・派生の難易度を見ている時）か、ファイルの基準の難易度（server.file_diff＝曲の作業ファイルの diff・
    履歴の版は控えた時の基準）。ファイルに無ければ 400（分かる言葉で）。
  - 別の案・履歴の版: &cand=<番号>（<OUT>/.cand/<曲>/<曲>.cand<番号>.nlmf）・&ver=<版>（<OUT>/.history/<曲>/<曲>.<版>.nlmf）。
    または path=<OUT からの場所>（.history・.cand の中の .nlmf か OUT の直下の .nlmf だけ）。
  答え: state＝done（測れた・測れなかった＝ok）・running（まだ測っている＝もう一度聞く）・unavailable（nlm-rating が無い PC）。
  done の時は automap.rating.summarize の形（stars・pass・tech・acc・predicted_acc・notes・nps・njs…）＋ file・measured_at、
  file= の時は作業ファイルのライブラリの★の帯（library_stars＝[下, 上]・無ければ None）も。

覚え方: ファイルの（場所・更新時刻・大きさ・難易度）と nlm-rating の版 → 頼みの中身と版の指紋、指紋 → 測った答え（<OUT>/.rating/<指紋>.json）。
頼みの中身には難易度の名前（targets・info の難易度）が入る＝同じファイルの別の難易度は別の指紋。
中身が同じなら（NLM でライトだけ直して保存した等）測り直さない。nlm-rating の版が変われば測り直す（BeatLeader の計算が変わった
＝2026-10 の PPv4 で v0.1.0 → v0.2.0。版を見ないと、exe を替えても前の計算の★が出続けた）。同じ中身を同時に頼まれても 1 回だけ測る（別の流れで測り、
受け答えは wait 秒まで待つ）。測れなかった答えはこのプロセスの間だけ覚える（nlm-rating を入れ直せば次の起動で測り直す）。
先に測る（prefetch）: 難易度の展開は作り終えた派生の作業用の写しから測り始める（覚え方が中身の指紋なので、本物へ入れた後に聞くとすぐ返る）。
"""
import json
import re
import threading
import time
from pathlib import Path

from automap import diffs, nlmf
from automap import rating as R
from names import rel_parts  # noqa: E402  （app/names.py）

C = None                 # server モジュール（OUT・out_file・base_of・load_work・file_diff は呼ばれた時に読む）
DIFF = 'ExpertPlus'      # 難易度を渡さない時の既定（アプリからは、曲の基準の難易度か見ている難易度を渡す）
WAIT = 15                # 受け答えで待つ秒（それより長くかかれば running を返し、画面がもう一度聞く）
KEEP = 2000              # <OUT>/.rating/ に残す答えの数（古い物から消す）
_LOCK = threading.Lock()
_KEYS = {}               # (場所, 更新時刻, 大きさ) → 指紋
_RUN = {}                # 指紋 → threading.Event（測っている最中）
_FAIL = {}               # 指紋 → 測れなかった答え（このプロセスの間だけ）
VER_RE = re.compile(r'^[0-9A-Za-z_-]{1,64}$')


def _dir():
    return Path(C.OUT) / '.rating'


def _inside(p, root):
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def target(q):
    """問い合わせ → 測るファイル（OUT の外・.nlmf でない物は断る）"""
    out = Path(C.OUT).resolve()
    if q.get('path'):
        parts = rel_parts(q['path'])   # 確かめてから場所にする（UNC・絶対の場所・.. は resolve の前に断る＝app/names.py）
        if not parts:
            raise ValueError('OUT の直下か .history・.cand の中の .nlmf だけを測れる')
        p = out.joinpath(*parts).resolve()
        parts = p.relative_to(out).parts if _inside(p, out) else ()
        if p.suffix != '.nlmf' or not (len(parts) == 1 or (len(parts) == 3 and parts[0] in ('.history', '.cand'))):
            raise ValueError('OUT の直下か .history・.cand の中の .nlmf だけを測れる')
    else:
        p0 = C.out_file(q['file'])
        song = p0.name.split('.')[0]
        if q.get('ver'):
            if not VER_RE.match(q['ver']):
                raise ValueError('版の名前が違う')
            p = out / '.history' / song / f'{song}.{q["ver"]}.nlmf'
        elif q.get('cand'):
            p = out / '.cand' / song / f'{song}.cand{int(q["cand"])}.nlmf'
        else:
            p = C.base_of(p0)
    if not p.is_file():
        raise FileNotFoundError(f'{p.name} が無い')
    return p


def _read(sha):
    try:
        return json.loads((_dir() / f'{sha}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write(sha, r):
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f'{sha}.tmp'
    tmp.write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
    tmp.replace(d / f'{sha}.json')
    fs = sorted(d.glob('*.json'), key=lambda f: f.stat().st_mtime)
    for f in fs[:max(0, len(fs) - KEEP)]:
        f.unlink(missing_ok=True)


def _measure(sha, req, meta, exe, ev):
    try:
        t0 = time.time()
        r = R.summarize(R.run(exe, req), meta)
        r.update(took=round(time.time() - t0, 2), measured_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
        if r.get('ok'):
            _write(sha, r)
        else:
            _FAIL[sha] = r
    except Exception as e:   # noqa: BLE001
        _FAIL[sha] = dict(meta, ok=False, error=f'{type(e).__name__}: {e}')
    finally:
        with _LOCK:
            _RUN.pop(sha, None)
        ev.set()


def _start(path, diff, exe):
    """測り始める → (指紋, 測ってあった答えか None, 測っている印（threading.Event）か None)。ファイルはここで読み終える
    （測る流れは読んだ頼みの中身だけを使う＝この後でファイルが消えてもよい・展開の作業用の写し）"""
    ver = R.exe_version(exe)
    st = path.stat()
    diff = diffs.dat(diff)   # 'ExpertStandard.dat' の形（nlmf.diff_key は頭の一致で探す＝'Expert' だと Expert+ を拾い得る）
    k = (str(path.resolve()), st.st_mtime_ns, st.st_size, ver, diff)
    with _LOCK:
        sha = _KEYS.get(k)
    req = meta = None
    if sha is None:
        proj = nlmf.load(path)
        chk = getattr(C, 'diff_key_in', None)
        if chk:
            chk(proj, diff, path.name)   # 無い難易度は分かる言葉で断る（ValueError＝400）
        req, meta = R.request(proj, diff)
        sha = R.req_key(req, ver)
        with _LOCK:
            _KEYS[k] = sha
    done = _read(sha) or _FAIL.get(sha)
    if done:
        return sha, done, None
    with _LOCK:
        ev = _RUN.get(sha)
        if ev is None:
            if req is None:
                req, meta = R.request(nlmf.load(path), diff)
            ev = _RUN[sha] = threading.Event()
            threading.Thread(target=_measure, args=(sha, req, meta, exe, ev), daemon=True).start()
    return sha, None, ev


def _answer(sha):
    return dict(_read(sha) or _FAIL.get(sha) or {'ok': False, 'error': '答えが無い'}, state='done')


def rate(path, wait=WAIT, diff=DIFF):
    """ファイル → 答え（state 付き）。必要なら別の流れで測り、wait 秒まで待つ。diff＝難易度の名前（ExpertPlus・Expert…）"""
    exe = R.rating_exe()
    if not exe:
        return {'state': 'unavailable', 'ok': False, 'error': R.NO_EXE}
    sha, done, ev = _start(path, diff, exe)
    if done:
        return dict(done, state='done')
    if not ev.wait(max(0.0, min(float(wait), 120.0))):
        return {'state': 'running'}
    return _answer(sha)


def prefetch(path, diff=DIFF, then=None):
    """先に測り始める（難易度の展開で、作り終えた派生の作業用の写しから・app/expand.py・2026-11-09 利用者）→ 測れるか（nlm-rating が
    無ければ False）。頼みの中身はここで読み、答えの控えは中身の指紋（<OUT>/.rating/）＝本物の結果のファイルへ同じ中身を入れた後に
    /api/rating で聞くと、測り直さずにすぐ返る。then(答え＝rate の done の形) は測り終えた時に別の流れで（測ってあればすぐここで）呼ぶ"""
    exe = R.rating_exe()
    if not exe:
        return False
    sha, done, ev = _start(path, diff, exe)
    if then is not None:
        if ev is None:
            then(dict(done, state='done'))
        else:
            threading.Thread(target=lambda: (ev.wait(300), then(_answer(sha))), daemon=True).start()
    return True


def library_stars(p):
    """作業ファイルのライブラリの★の帯（[下, 上]）。設定が無い・帯が無ければ None"""
    try:
        lib = (C.load_work(p) or {}).get('library')
    except (OSError, ValueError):
        return None
    s = lib.get('stars') if isinstance(lib, dict) else None
    return [float(s[0]), float(s[1])] if isinstance(s, (list, tuple)) and len(s) == 2 and all(isinstance(x, (int, float)) for x in s) else None


def get_rating(q):
    p = target(q)
    own = not q.get('path') and not q.get('ver') and not q.get('cand')
    fd = getattr(C, 'file_diff', None)   # ファイルの基準の難易度（server.file_diff・無い口のテストでは既定）
    d = diffs.name_of(q['diff']) if (own and q.get('diff')) else (fd(p) if fd else DIFF)   # 派生を見ている時だけ diff（版・案は基準）
    r = rate(p, q.get('wait', WAIT), d)
    r['file'], r['view_diff'] = p.name, d
    if own:
        r['library_stars'] = library_stars(C.out_file(q['file']))
    return r


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})"""
    global C
    C = ctx
    return {'/api/rating': get_rating}, {}
