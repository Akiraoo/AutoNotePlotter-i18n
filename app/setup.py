"""初回の設定画面（準備と設定）と、起動のたびの準備の確かめ（docs/アプリ仕様.md 21 節・2026-11-03 利用者）。

利用者と決めたこと: 音を分ける部品は初回の設定画面で入れる・起動のたびに揃っているかを確かめ、足りなければ入れ直しを続きから再開する
案内を出す（部品が無いと動かない）・入れる前に必要な容量と入れる場所を必ず予告する・何に使うかを必ず説明する（譜面の置き方は
BeatLeader のランク譜面の型で自動で決める＝音を分ける部品は曲を理解するための物）。画面は static/js/setup.js。

揃っているかを見る物（ready＝4つとも）:
- 作業の場所（設定の work_dir＝out/・cache/ の親）: 開発の PC（配布物でない）は決めていなくてもリポジトリの out/・cache/。
- 音を分ける部品: 設定の sep_dir（tools/sep_install.py で入れたパック・check で揃っているか）か、開発の PC の .venv-sep。
  入れている途中で止まった物は設定の sep_pending（{dir, variant}）＝画面は「続きから入れる」。
  版の 2 段（2026-11-03 利用者）: check に設定の update_ng（app/update.py が配布元の update.json から控えた「使ってはいけない版」）を渡す。
  入っている版が確かめた組と違っても、最低の版以上で NG でなければ揃っている扱い（sep.stage 'recommended'＝画面は「おすすめの状態では
  ありません」と上の列の小さな印）。最低の版より古い・NG・入っていない・壊れている時だけ止める（'required'）。確かめた組そのものに NG が
  あれば部品の入れ直しでは直らない（sep.app_update＝「アプリの更新が必要です」・インストールも断る）。
- 型のライブラリ: automap/library_db.db_path（配布物は data/library-dist.sqlite）。
- ★を測る部品（nlm-rating・MIT）: automap/rating.rating_exe（配布物は parts/nlm-rating に同梱）。NJS の決め方・難易度の展開の目安に使う
  （2026-11-03 利用者「レーティングの部品も必須」）。
無くてもアプリは動く物: NLM（手直し・ライティング。Beat Saber への書き出しは app/bsexport.py で NLM が無くてもできる）。

受け口（server.connect が routes(ctx) をつなぐ）:
  GET  /api/setup/status                 → status()（sep に版の段・変わる部品・差分のダウンロード量。ng＝控えた NG の理由と日）
  GET  /api/setup/plan?dir=&variant=     → sep_install.plan（必要な容量・入れる場所の空き・何を取ってくるか・GPU の見分け）＋ ng_set
  POST /api/setup/settings {work_dir?, nlm_exe?, nlm_rating_exe?}  → 設定に書く（空の文字＝外す）・作業の場所は作って書けるか確かめる
  POST /api/setup/install {dir, variant} → 音を分ける部品を入れる作業（kind='setup'・/api/job で進み具合 progress・やめる＝/api/job/cancel）。
                                           入っているパックの更新も同じ（違う部品だけ取り直す）。確かめた組が NG なら断る
  POST /api/setup/pick {kind: folder|exe, initial}  → この PC の窓で選ぶ
  POST /api/setup/done                   → 初回の設定画面を終えた（setup_done）
  GET  /api/setup/move-plan?dir=         → 作業フォルダの引っ越しの見積もり（app/relocate.py）
  POST /api/setup/move {new_dir}         → 作業フォルダを引っ越す作業（kind='move'・/api/job で進み具合）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from automap import config  # noqa: E402
from automap import library_db  # noqa: E402

DEV_SEP = ROOT / '.venv-sep' / 'Scripts' / 'python.exe'   # 開発の PC の音を分ける環境（tools/separate.py の頭）
INSTALL_LABEL = '音を分ける部品をインストールする'


def _sep_mod():
    try:
        import sep_install   # tools/sep_install.py（MIT・音を分ける部品を入れる道具）
        return sep_install
    except ImportError:
        return None


def _free(p):
    """その場所のドライブの空き（バイト）。まだ無いフォルダは、あるところまで上がって見る"""
    p = Path(p)
    for q in (p, *p.parents):
        if q.exists():
            try:
                return shutil.disk_usage(q).free
            except OSError:
                return None
    return None


def _writable(d):
    try:
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.anp-', dir=d)
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


def default_work():
    return Path.home() / 'Documents' / 'AutoNotePlotter'


def default_sep(work):
    return Path(work) / 'parts' / 'separate'


def work_state(cfg):
    w = config.work_dir(cfg)
    if w is None:
        if config.distributed():
            return {'ok': False, 'dir': None, 'why': '作業フォルダがまだ決まっていません'}
        return {'ok': True, 'dir': str(ROOT), 'dev': True, 'free': _free(ROOT)}
    if not w.is_absolute():
        return {'ok': False, 'dir': str(w), 'why': '作業フォルダはドライブ名から書いてください'}
    if not w.exists():
        return {'ok': False, 'dir': str(w), 'why': '作業フォルダが見つかりません（外付けのドライブなら、つないでからアプリを開き直してください）'}
    ok = _writable(w)
    return {'ok': ok, 'dir': str(w), 'free': _free(w), 'why': None if ok else '作業フォルダに書き込めません'}


NG_KEY = 'update_ng'   # app/update.py の NG_KEY（設定に控えた使ってはいけない版）


def ng_of(cfg):
    """設定に控えた使ってはいけない版（update.json の ng の形）か None"""
    ng = cfg.get(NG_KEY)
    return ng if isinstance(ng, dict) else None


def sep_state(cfg):
    """音を分ける部品 → {ok, kind（pack・dev・None）, dir, variant, missing（日本語の一言の並び）, resume（途中まで入れた所）, pending,
    stage（none・recommended・required）, changes・update_bytes・partial・rebuild・ng_set・app_update・ng_why（sep_install.check）}"""
    pend = cfg.get('sep_pending') or None
    d = cfg.get('sep_dir')
    m = _sep_mod()
    ng = ng_of(cfg)
    if d:
        if m is None:
            return {'ok': False, 'kind': 'pack', 'dir': d, 'missing': ['インストールの道具（tools/sep_install.py）が見つかりません'], 'pending': pend}
        try:
            c = m.check(d, ng=ng)
        except Exception as e:   # noqa: BLE001
            c = {'ok': False, 'missing': [f'確かめられませんでした（{e}）']}
        return dict(c, kind='pack', dir=d, variant=c.get('variant') or cfg.get('sep_variant'), pending=pend)
    if pend and m is not None:
        try:
            c = m.check(pend['dir'], ng=ng)
        except Exception as e:   # noqa: BLE001
            c = {'ok': False, 'missing': [f'確かめられませんでした（{e}）']}
        if c.get('ok'):   # 入れ終わったのに印を書く前に止まった
            return dict(c, kind='pack', dir=pend['dir'], variant=c.get('variant') or pend.get('variant'), pending=pend, finish=True)
        return dict(c, ok=False, kind=None, dir=pend['dir'], variant=pend.get('variant'), pending=pend,
                    missing=c.get('missing') or ['インストールが途中で止まっています'])
    if not config.distributed() and DEV_SEP.exists():
        return {'ok': True, 'kind': 'dev', 'dir': str(DEV_SEP.parent.parent), 'variant': 'dev', 'python': str(DEV_SEP), 'missing': [],
                'pending': None}
    return {'ok': False, 'kind': None, 'dir': None, 'variant': None, 'missing': ['まだインストールしていません'], 'pending': None,
            'resume': None}


def library_state():
    try:
        p = library_db.db_path()
        con = library_db.open_db(p)
    except library_db.LibraryError as e:
        return {'ok': False, 'why': str(e)}
    try:
        info = library_db.info_of(con)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        con.close()
    dist = 'swings' not in tables
    return {'ok': True, 'path': str(p), 'dist': dist, 'built_at': info.get('built_at'), 'maps': info.get('maps'),
            'made_at': (info.get('dist') or {}).get('made_at') if dist else None}


def nlm_state(cfg):
    nlm = os.environ.get('NLM_EXE') or cfg.get('nlm_exe')
    return {'path': nlm, 'ok': bool(nlm and Path(nlm).is_file())}


def rating_state():
    from automap import rating
    exe = rating.rating_exe()
    if not exe:
        return {'ok': False, 'path': None, 'why': '★を測る部品（nlm-rating）が見つかりません'}
    try:
        ver = rating.exe_version(exe)
    except Exception:   # noqa: BLE001
        ver = None
    return {'ok': True, 'path': exe, 'version': ver, 'bundled': Path(exe).resolve() == rating.BUNDLED.resolve()}


def status(ctx):
    cfg = config.load(ctx.CONFIG)
    work, sep, lib, rat = work_state(cfg), sep_state(cfg), library_state(), rating_state()
    nlm = nlm_state(cfg)
    ready = work['ok'] and sep['ok'] and lib['ok'] and rat['ok']
    dist = config.distributed()
    done = bool(cfg.get('setup_done')) or (not dist and ready)
    w = config.work_dir(cfg) or default_work()
    ng = ng_of(cfg)
    return {'ready': ready, 'setup_done': done, 'need_setup': not ready or not done, 'distributed': dist, 'as_dist': config.as_dist() is not None,
            'config': str(ctx.CONFIG), 'work': work, 'sep': sep, 'library': lib, 'nlm': nlm, 'rating': rat,
            'default_work': str(default_work()), 'default_sep': str(default_sep(w)), 'running': _running(ctx),
            'ng': {'why': str(ng.get('why') or '')[:300], 'at': str(ng.get('at') or '')[:19] or None} if ng else None}


def _running(ctx):
    for j in ctx.JOBS.values():
        if j.get('kind') == 'setup' and j['state'] == 'running':
            return j['id']
    return None


def sep_runner(ctx_or_cfg=None):
    """取り込みが音を分ける時の (python.exe, 環境変数（全部・None＝今のまま）, 種類)。揃っていなければ RuntimeError（「準備と設定」へ）。
    パックの環境変数は sep_install.run_env（HF_HOME・ネットに出ない設定・PYTHONPATH 等を除く）"""
    cfg = config.load(getattr(ctx_or_cfg, 'CONFIG', None)) if not isinstance(ctx_or_cfg, dict) else ctx_or_cfg
    st = sep_state(cfg)
    if not st['ok']:
        raise RuntimeError('音を分ける部品が揃っていません（' + '・'.join(st.get('missing') or []) + '）→ 上の「準備と設定」でインストールしてください（続きから再開できます）')
    if st['kind'] == 'dev':
        return DEV_SEP, None, 'dev'
    m = _sep_mod()
    return Path(m.python_exe(st['dir'])), dict(m.run_env(st['dir'], os.environ)), st.get('variant')


def _abs_dir(s, what):
    s = str(s or '').strip().strip('"').strip("'").strip()
    if not s:
        raise ValueError(f'{what}が空です')
    p = Path(os.path.expanduser(s))
    if not p.is_absolute():
        raise ValueError(f'{what}はドライブ名から書いてください（例 D:\\AutoNotePlotter）')
    if (ROOT / 'runtime').is_dir() and (p == ROOT or ROOT in p.parents):
        raise ValueError(f'{what}をアプリのフォルダの中にしないでください（アプリの更新で消えます・Program Files には書き込めません）')
    return p


def set_settings(ctx, b):
    ch = {}
    if 'work_dir' in b:
        w = _abs_dir(b['work_dir'], '作業フォルダ')
        if not _writable(w):
            raise ValueError(f'作業フォルダに書き込めません: {w}')
        for sub in ('out', 'cache'):
            (w / sub).mkdir(exist_ok=True)
        ch['work_dir'] = str(w)
    for key, what in (('nlm_exe', 'NLM'), ('nlm_rating_exe', 'nlm-rating')):
        if key in b:
            v = str(b[key] or '').strip().strip('"')
            if v.startswith(('\\\\', '//')):   # ネットワークの場所の exe は使わない（調べるだけで相手へつなぐ・起動もする＝F12）。ファイルに触る前に断る
                raise ValueError(f'{what} の exe はこの PC のドライブに置いてください（ネットワークの場所は使えません）: {v}')
            if v and not (Path(v).is_file() and v.lower().endswith('.exe')):
                raise ValueError(f'{what} の exe が見つかりません: {v}')
            ch[key] = v or None
    cfg = config.update(ch, ctx.CONFIG)
    if 'work_dir' in ch:   # 作業の場所を変えた＝曲の一覧・作り直しは新しい場所から（前の場所のファイルは消さない）
        ctx.OUT, ctx.CACHE = config.out_dir(cfg), config.cache_dir(cfg)
    return status(ctx)


def install_cmd(d, variant):
    """部品を入れるコマンド（tools/sep_install.py install・1行に1つの JSON で進み具合）"""
    cmd = [sys.executable, ROOT / 'tools' / 'sep_install.py', 'install', '--dir', d, '--variant', variant, '--json']
    rt = runtime_dir()
    if rt:   # 配布物＝パックの Python はアプリの埋め込み用の Python から作る
        cmd += ['--runtime', rt]
    return cmd


def runtime_dir():
    """配布物の埋め込み用の Python（パックの Python の元）か None。配布物のふりは同梱物の場所の runtime/（tools/dist/checkset.py が置く）"""
    rt = config.app_root() / 'runtime'
    return rt if rt.is_dir() else None


def start_install(ctx, b):
    m = _sep_mod()
    if m is None:
        raise ValueError('インストールの道具（tools/sep_install.py）が見つかりません')
    if _running(ctx):
        raise ValueError('もうインストールしています（進み具合は準備の窓で見られます）')
    d = _abs_dir(b.get('dir'), 'インストール先')
    variant = str(b.get('variant') or '')
    bad = m.set_ng(variant or None, ng_of(config.load(ctx.CONFIG))) if hasattr(m, 'set_ng') else []
    if bad:   # 確かめた組そのものが NG＝インストールしても同じ版が入る（直らない）
        raise ValueError('このアプリの版がインストールする部品に、使ってはいけない版があります（'
                         + '・'.join(f'{x["name"]} {x["version"]}' for x in bad) + '）。アプリを新しい版に更新してください')
    cmd = install_cmd(d, variant)
    config.update({'sep_pending': {'dir': str(d), 'variant': variant}}, ctx.CONFIG)

    def run(job):
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        # アプリ（このサーバー）が止まったら道具も止める（閉じると中を全部止める Windows のジョブ＝sep_install._popen と同じ物）。
        # 止めないと、インストール中にアプリを閉じた時に道具が裏でダウンロードを続け、次に開いて「続きから」を押すと「別のところから
        # インストールしている途中」と断られた（2026-11-03 の通しの確かめ）。止まった物は次に開いた時に続きから
        pr = m._popen([str(c) for c in cmd], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        job['proc'] = pr
        err, last = None, None
        try:
            for raw in iter(pr.stdout.readline, b''):
                line = raw.decode('utf-8', 'replace').rstrip()
                try:
                    ev = json.loads(line)
                except ValueError:
                    ev = None
                if not isinstance(ev, dict):
                    if line:
                        job['log'] += line + '\n'
                    continue
                if ev.get('error'):
                    err = ev['error']
                    job['log'] += f'失敗: {err}\n'
                    continue
                job['progress'] = ev
                key = (ev.get('stage'), ev.get('msg'))
                if key != last and (ev.get('label') or ev.get('msg')):
                    job['log'] += f'{ev.get("label") or ev.get("stage")}: {ev.get("msg") or ""}\n'
                    last = key
            pr.wait()
        finally:
            job.pop('proc', None)
        if job.get('cancel'):
            return
        if pr.returncode or err:
            raise RuntimeError(err or f'失敗した（終了コード {pr.returncode}）')

    def after(job):
        if job['state'] == 'done':
            config.update({'sep_dir': str(d), 'sep_variant': variant, 'sep_pending': None}, ctx.CONFIG)

    job = ctx.start_job(None, [(INSTALL_LABEL, run)], kind='setup', after=after, dir=str(d), variant=variant)
    return {'id': job['id']}


def routes(ctx):
    def plan(q):
        m = _sep_mod()
        if m is None:
            raise ValueError('インストールの道具（tools/sep_install.py）が見つかりません')
        d = _abs_dir(q.get('dir'), 'インストール先')
        rt = runtime_dir()
        p = m.plan(str(d), q.get('variant') or None, runtime=str(rt) if rt else None)
        if hasattr(m, 'set_ng'):   # インストールする組の中の使ってはいけない版（あれば画面はインストールを止めて、アプリの更新へ）
            p['ng_set'] = m.set_ng(p.get('variant'), ng_of(config.load(ctx.CONFIG)))
        return p

    def pick(b):
        import importer   # noqa: E402  （app/ の中・ファイルの窓）
        kind = b.get('kind')
        if kind not in ('folder', 'exe'):
            raise ValueError('選ぶ物の種類が違います')
        return {'path': importer.PICKER(kind, b.get('initial'))}

    def done(b):
        st = status(ctx)
        if not st['ready']:
            raise ValueError('まだ揃っていない物があります')
        config.update({'setup_done': True}, ctx.CONFIG)
        return status(ctx)

    import relocate   # noqa: E402  （app/ の中・作業フォルダの引っ越し）
    get = {'/api/setup/status': lambda q: status(ctx), '/api/setup/plan': plan,
           '/api/setup/move-plan': lambda q: relocate.plan(ctx, q.get('dir'))}
    post = {'/api/setup/settings': lambda b: set_settings(ctx, b), '/api/setup/install': lambda b: start_install(ctx, b),
            '/api/setup/pick': pick, '/api/setup/done': done, '/api/setup/move': lambda b: relocate.start(ctx, b)}
    return get, post
