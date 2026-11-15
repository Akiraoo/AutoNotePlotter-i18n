"""確かめのセット（docs/アプリ仕様.md 23 節・2026-11-03 利用者と相談）。開発はこのまま（作業フォルダはリポジトリの out/・cache/）にして、
配布物を使う人と同じ周り（埋め込み用の Python・配布用の型のライブラリ・音を分ける部品のパック・設定と作業フォルダの場所・更新）で確かめる。
主に Claude の自動の確かめ用（利用者も動かせる）。.venv の Python で動かす（デモ曲を作るのに numpy・scipy・soundfile、後片付けに psutil）。

  ① dev      配布物のふりでアプリを起動する（ソースのまま・環境変数 AUTOMAP_AS_DIST＝automap/config.as_dist）。開発の PC にしか無い物
             （app/config.local.json・.venv-sep・開発用の型のデータベース・リポジトリの out/）を見ず、同梱物（配布用の
             型のライブラリ・nlm-rating・埋め込み用の Python）は置き場の bundle/ から読む。アプリの更新はしない（差し替えるとリポジトリを書き換える）。
             既定は準備が済んだ形（作業フォルダ・CPU 版の部品＝parts/cpu を使い回す）・--first-run で初回の設定画面から。
  ② release  リリースの前の通しの確かめ（1 コマンド）: テスト（全部・曲の解析の答え合わせは控えを使わずに計算）→
             配布物を作る → 配布物の中の確かめ（check_dist.py）→ まっさらな設定で起動 →
             作業フォルダ（日本語と空白の入った場所）→ 音を分ける部品（CPU 版・インストールの途中でアプリを強制終了して続きから）→
             デモ曲（合成）の取り込み → 作り直し → ★ → 難易度の展開 → Beat Saber に書き出す（2 回・プレイリストは 1 行）→
             窓のアプリ（起動用の exe → WebView2）で左下の欄のリプレイ（書き出したデモ曲の合成リプレイ・同期・▶ で音・描く速さ）→
             C ドライブに写して起動 → 更新（次の版を手元の配布元から）。結果は run/report.md。
             互いに関係ない段は並べる（2026-11-15）: テストは配布物を作るのと同時・check_dist は入れた後に裏で（取り込みの後で待つ）・
             C ドライブは窓のアプリの段と同時（設定と LOCALAPPDATA は写し）・更新の確かめの次の版の zip は軽い圧縮。
  parts      音を分ける部品を parts/<種類>/ に入れる（控えから・無ければダウンロード。GPU 版は数 GB＝頼まれた時だけ）
  demo       デモ曲（tools/dist/demo_song.py）を <置き場>/demo/ に作る

置き場（PC ごと・大きい部品とダウンロードの控えを使い回す）: --dir か、開発の設定（app/config.local.json）の check_dir。
  downloads/      埋め込み用の Python（build_embed.py の控え）・sep/＝音を分ける部品と学習済みモデルの控え（指紋を確かめた物）
  venv-build/     配布物を作る Python（py -3.14 -m venv・無ければ作る）
  build/          作った配布物（AutoNotePlotter/・release/＝zip と update.json）
  bundle/         配布物のふりの同梱物（data/library-dist.sqlite・parts/nlm-rating/・runtime/）
  parts/<種類>/    入れた音を分ける部品（配布物のふりが使い回す）
  demo/           デモ曲と Cover.png
  dev/            配布物のふりの設定（config.json）・作業フォルダ（work/）・LOCALAPPDATA（lad/）・書き出し先（levels/・playlists/）
                  ＝起動のたびにまっさら（--keep で残す）
  run/            通しの確かめ＝起動のたびにまっさら（app/＝入れた配布物・作業 フォルダ/・levels/・playlists/・logs/・report.md。
                  通ったら app/・vB/ の写しは消す）
Beat Saber への書き出し先はどちらも置き場の中に決めておく（本物の Beat Saber のフォルダに書かない）。

使い方:
  .venv/Scripts/python.exe tools/dist/checkset.py dev [--first-run] [--parts cpu|cu128|cu126|none] [--port 8775] [--window] [--browser] [--keep]
  .venv/Scripts/python.exe tools/dist/checkset.py release [--skip-tests] [--skip-build] [--net] [--window] [--no-c] [--no-update] [--port 8776]
  .venv/Scripts/python.exe tools/dist/checkset.py parts [--variant cpu]
  .venv/Scripts/python.exe tools/dist/checkset.py demo
"""
import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(REPO / 'tools'), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import build_embed as BE  # noqa: E402  （配布物を作る台本の関数・頭は標準の部品だけ）
import sep_install as SI  # noqa: E402  （音を分ける部品の一覧・ダウンロード）
from check_dist import env_like_launcher  # noqa: E402

VENV = REPO / '.venv' / 'Scripts'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# 開発の PC の場所を指す環境変数（確かめのアプリには渡さない）
DEV_VARS = ('AUTOMAP_CONFIG', 'AUTOMAP_LIBRARY', 'AUTOMAP_AS_DIST', 'AUTOMAP_NJS_OFFSET', 'AUTOMAP_UPDATE_URL', 'AUTOMAP_UPDATE_NO_LAUNCH',
            'AUTOMAP_NO_OPEN', 'NLM_RATING_EXE', 'NLM_EXE', 'NLM_ROOT', 'BPA_BSOR', 'VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME',
            'PYTHONSTARTUP', 'PYTHONUSERBASE', 'PYTHONEXECUTABLE', 'PYTHONSAFEPATH')
SONG = 'デモ曲'
C_COPY = Path(tempfile.gettempdir()) / 'anp-checkset'   # 「C ドライブに写して起動」の写しの場所（一時フォルダ＝ふつうは C ドライブ・終わったら消す）
T0 = time.time()


class Fail(Exception):
    pass


def say(*a):
    print(f'[{time.time() - T0:6.0f}s]', *a, flush=True)


def need(cond, msg):
    if not cond:
        raise Fail(msg)


def mb(n):
    return f'{(n or 0) / 1e6:,.0f}MB'


def check_root(arg):
    """確かめの置き場: --dir か、開発の設定（app/config.local.json）の check_dir"""
    if arg:
        return Path(arg).resolve()
    from automap import config
    p = config.load(config.DEV).get('check_dir')
    if not p:
        raise SystemExit('確かめの置き場が決まっていない: --dir で渡すか、app/config.local.json に "check_dir" を書く（大きい部品の控えを置くので速いドライブに）')
    return Path(p)


def flow_cache(app):
    """配布物の中の流れの計算（Numba）のコンパイル済みの控え → {名前: (大きさ, 更新時刻)}"""
    return {f.name: (f.stat().st_size, f.stat().st_mtime_ns) for f in (Path(app) / 'automap' / '__pycache__').glob('flow_nb.*.nb[ic]')}


def clean_env(base=None):
    return {k: v for k, v in (base or os.environ).items() if k not in DEV_VARS}


def rmtree(p):
    """消す（読むだけの印の付いたファイル・使用中は少し待って何度か）"""
    p = Path(p)
    for i in range(5):
        if not p.exists():
            return
        try:
            shutil.rmtree(p, onexc=lambda f, x, e: (os.chmod(x, 0o666), f(x)))
        except OSError:
            time.sleep(1 + i)
    if p.exists():
        raise Fail(f'消せない（使っているプロセスが残っている？）: {p}')


def link_or_copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def port_free(port):
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


# ---------------------------------------------------------------- 同梱物（配布物のふり）・音を分ける部品の控え

def ensure_runtime(root, rt):
    """埋め込み用の Python（配布物と同じ版・指紋を確かめる）を rt に（音を分ける部品のパックの Python の元）"""
    mark = rt / '.anp-python'
    if (rt / 'python.exe').exists() and mark.exists() and mark.read_text(encoding='utf-8').strip() == BE.PY_VERSION:
        return rt
    emb = BE.fetch(BE.PY_URL.format(v=BE.PY_VERSION), root / 'downloads' / f'python-{BE.PY_VERSION}-embed-amd64.zip')
    want = BE.PY_SHA256.get(BE.PY_VERSION)
    if want and BE.sha256(emb) != want:
        emb.unlink()
        raise Fail(f'埋め込み用の Python の指紋が違う（消した・もう一度動かすと取り直す）: {emb}')
    rmtree(rt)
    with zipfile.ZipFile(emb) as z:
        z.extractall(rt)
    BE.copy_vc_runtime(rt, rt)   # パックの PyTorch が使う msvcp140・vcomp140（配布物と同じ）
    mark.write_text(BE.PY_VERSION, encoding='utf-8')
    return rt


def _newer(src, dst):
    return not dst.exists() or src.stat().st_size != dst.stat().st_size or src.stat().st_mtime > dst.stat().st_mtime + 1


def prepare_bundle(root, data=True):
    """配布物のふりの同梱物（bundle/）: 配布用の型のライブラリ・nlm-rating（開発の設定の場所から・変わった時だけ写す）・埋め込み用の Python"""
    b = root / 'bundle'
    if data:
        from automap import config
        cfg = config.load(config.DEV)
        lib = Path(cfg['library_db']).parent / 'library-dist.sqlite' if cfg.get('library_db') else None
        rd = Path(cfg['nlm_rating_exe']).parent if cfg.get('nlm_rating_exe') else None
        need(lib and lib.is_file(), f'配布用の型のライブラリが無い（{lib}）: tools/library_build/make_dist.py で作る')
        need(rd and (rd / 'nlm-rating.exe').is_file(), f'nlm-rating が無い（{rd}）: 開発の設定の nlm_rating_exe')
        if _newer(lib, b / 'data' / 'library-dist.sqlite') or _newer(rd / 'nlm-rating.exe', b / 'parts' / 'nlm-rating' / 'nlm-rating.exe'):
            say(f'同梱物を写す: {lib.name}（{mb(lib.stat().st_size)}）・nlm-rating（{rd.name}）')
            rmtree(b / 'parts' / 'nlm-rating')
            (b / 'data').mkdir(parents=True, exist_ok=True)
            BE.bundle_parts(b, lib, rd)
    ensure_runtime(root, b / 'runtime')
    return b


def sep_items(variant, cache):
    return ([(f, cache / f['file']) for f in [SI.FILES[f'torch-{variant}'], *SI._lib_files(), SI.FILES['pip']]]
            + [(w, cache / 'weights' / w['file']) for w in SI.WEIGHTS])


def fill_sep_cache(root, variant):
    """音を分ける部品（wheel）と学習済みモデルを控え（downloads/sep/）に。無い物だけ公式の置き場から取り、指紋を確かめる → 控えの場所"""
    cache = root / 'downloads' / 'sep'
    items = sep_items(variant, cache)
    todo = [(f, d) for f, d in items if not (d.exists() and d.stat().st_size == f['size'])]
    if todo:
        total = sum(f['size'] for f, _ in todo)
        say(f'音を分ける部品の控えをダウンロードする（{variant}・{len(todo)} 個・{mb(total)}）')
        shown = [0]

        def rep(stage, done=0, total=0, msg='', force=False, **kw):
            if stage == 'download' and total and (done - shown[0] > total / 10 or done >= total):
                shown[0] = done
                say(f'   {stage} {mb(done)}/{mb(total)} {msg}')
        base = 0
        for f, d in todo:
            SI._fetch_verified(f, d, cache / 'partial', rep, None, base, total)
            base += f['size']
    return cache


def seed_pack(pack, variant, cache):
    """パックの場所に控えを置く（ダウンロードの段は控えを使い、pip・重み・確かめはふだんどおり）。置く前に指紋を確かめる"""
    snap = SI._snapshot(pack)
    for f, src in sep_items(variant, cache):
        need(src.exists() and SI._sha256(src) == f['sha256'], f'控えが壊れている（消して取り直す）: {src}')
        dst = snap / f['file'] if src.parent.name == 'weights' else Path(pack) / 'downloads' / f['file']
        link_or_copy(src, dst)


def ensure_parts(root, variant, auto=True):
    """parts/<種類>/ に音を分ける部品（無ければ控えから入れる）→ 場所"""
    pack = root / 'parts' / variant
    c = SI.check(str(pack)) if pack.exists() else {'ok': False}
    if c.get('ok'):
        return pack
    if not auto:
        raise SystemExit(f'音を分ける部品（{variant}）がまだ無い: checkset.py parts --variant {variant} で入れる（数 GB のダウンロード）')
    rt = ensure_runtime(root, root / 'bundle' / 'runtime')
    cache = fill_sep_cache(root, variant)
    seed_pack(pack, variant, cache)
    say(f'音を分ける部品をインストールする（{variant}・{pack}）')
    last = [None]

    def prog(ev):
        if ev.get('stage') != last[0]:
            last[0] = ev.get('stage')
            say(f'   {ev.get("step")}/{ev.get("steps")} {ev.get("label")} {ev.get("msg") or ""}')
    inst = SI.install(str(pack), variant, runtime=str(rt), progress=prog)
    say(f'   入れた: PyTorch {inst.get("torch")}・{inst.get("seconds")} 秒・{mb(inst.get("size"))}')
    return pack


def ensure_demo(root):
    d = root / 'demo'
    song, cover = d / f'{SONG}.flac', d / 'Cover.png'
    if not (song.exists() and cover.exists()):
        import demo_song   # tools/dist/demo_song.py（numpy・scipy・soundfile）
        say('デモ曲を作る（合成・80 秒）')
        demo_song.make(d, SONG)
    return song, cover


# ---------------------------------------------------------------- アプリのサーバー

# 確かめのアプリの合言葉（app/server.py の出入りの守り・2026-11-11）: 起こすサーバーに環境変数 AUTOMAP_TOKEN で渡し、要求に頭で付ける
TOKEN = secrets.token_urlsafe(32)


def api(base, method, path, body=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else (b'{}' if method in ('POST', 'PUT') else None)
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'X-Automap': '1', 'X-Automap-Key': TOKEN, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8') or 'null')
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try:
            msg = json.loads(raw).get('error') or raw
        except (ValueError, AttributeError):
            msg = raw
        raise Fail(f'{method} {path.split("?")[0]} → {e.code}: {str(msg)[:400]}') from None


def q(s):
    return urllib.parse.quote(str(s))


class Server:
    """確かめのアプリ（app/server.py）を別のプロセスで。記録は logs/<名前>-<回>.log"""

    def __init__(self, name, py, app, env, port, logs):
        self.name, self.py, self.app, self.env, self.port, self.logs = name, Path(py), Path(app), env, port, Path(logs)
        self.base = f'http://127.0.0.1:{port}'
        self.proc, self.n, self.logf = None, 0, None

    def start(self, timeout=180):
        need(port_free(self.port), f'番号 {self.port} が使われている（前の確かめのアプリが残っている？ --port で替える）')
        self.n += 1
        self.logs.mkdir(parents=True, exist_ok=True)
        self.logf = self.logs / f'{self.name}-{self.n}.log'
        log = open(self.logf, 'wb')
        env = dict(self.env if self.env is not None else os.environ, AUTOMAP_TOKEN=TOKEN)   # 合言葉（api が付ける）
        self.proc = subprocess.Popen([str(self.py), str(self.app / 'app' / 'server.py'), '--no-browser', '--port', str(self.port)],
                                     cwd=str(self.app), env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        t = time.time()
        while time.time() - t < timeout:
            try:
                return self.get('/api/setup/status', timeout=3)
            except (OSError, Fail):
                if self.proc.poll() is not None:
                    raise Fail(f'アプリが起動しない（{self.logf}）: {self.tail()}') from None
                time.sleep(0.3)
        raise Fail(f'アプリが {timeout} 秒で起動しない（{self.logf}）')

    def tail(self, n=1200):
        try:
            return self.logf.read_text(encoding='utf-8', errors='replace')[-n:]
        except OSError:
            return ''

    def get(self, path, timeout=60):
        return api(self.base, 'GET', path, timeout=timeout)

    def post(self, path, body=None, timeout=60):
        return api(self.base, 'POST', path, body if body is not None else {}, timeout=timeout)

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.post('/api/shutdown', timeout=5)
        except (OSError, Fail):
            pass
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.kill()

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(30)

    def wait_job(self, jid, timeout=1200, until=None, what=''):
        """作業（/api/job）が終わるまで（until(job) が真になったらそこで）。段・進み具合が変わったら一言"""
        t, last = time.time(), None
        while True:
            j = self.get(f'/api/job?id={q(jid)}')
            pr = j.get('progress') or {}
            steps = j.get('steps') or []
            st = j.get('step')
            label = pr.get('label') or (steps[st] if isinstance(st, int) and st < len(steps) else '')
            if label and label != last:
                say(f'   {what}{label}')
                last = label
            if until and until(j):
                return j
            if j['state'] != 'running':
                if j['state'] != 'done':
                    (self.logs / f'job-{jid}.log').write_text(j.get('log') or '', encoding='utf-8')
                    raise Fail(f'{what}作業が {j["state"]} で終わった: {(j.get("error") or "")[:300]} … {(j.get("log") or "")[-600:]}')
                return j
            if time.time() - t > timeout:
                raise Fail(f'{what}作業が {timeout} 秒で終わらない')
            time.sleep(0.4)


class Releases:
    """手元の配布元（GitHub のリリースと同じ並び: releases/latest/download/update.json・releases/download/<tag>/<zip>）"""

    def __init__(self, port):
        self.files, self.hits = {}, []
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                me.hits.append(self.path)
                p = me.files.get(self.path)
                if not p:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(p.stat().st_size))
                self.end_headers()
                with open(p, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile, 1 << 20)
        need(port_free(port), f'番号 {port} が使われている（--port で替える）')
        self.srv = ThreadingHTTPServer(('127.0.0.1', port), H)
        self.url = f'http://127.0.0.1:{port}/releases/'
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def publish(self, rel):
        """rel（build_embed の release/＝zip と update.json）を最新のリリースとして出す"""
        up = Path(rel) / 'update.json'
        m = json.loads(up.read_text(encoding='utf-8'))
        self.files = {'/releases/latest/download/update.json': up,
                      f'/releases/download/{m["tag"]}/{m["zip"]["name"]}': Path(rel) / m['zip']['name']}
        return m

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


# ---------------------------------------------------------------- ① 配布物のふり

def cmd_dev(a):
    root = check_root(a.dir)
    b = prepare_bundle(root)
    song, _ = ensure_demo(root)
    d = root / 'dev'
    cfgp = d / 'config.json'
    if not a.keep or not cfgp.exists():
        rmtree(d)
        d.mkdir(parents=True)
        cfg = {'bs_levels': str(d / 'levels'), 'bs_playlists': str(d / 'playlists')}   # 本物の Beat Saber のフォルダに書かない
        for x in ('levels', 'playlists'):
            (d / x).mkdir()
        if not a.first_run:
            work = d / 'work'
            for x in ('out', 'cache'):
                (work / x).mkdir(parents=True)
            cfg['work_dir'] = str(work)
            if a.parts != 'none':
                pack = ensure_parts(root, a.parts, auto=a.parts == 'cpu')
                cfg.update(sep_dir=str(pack), sep_variant=a.parts)
                cfg['setup_done'] = True
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    env = clean_env()
    env.update(AUTOMAP_AS_DIST=str(b), AUTOMAP_CONFIG=str(cfgp), LOCALAPPDATA=str(d / 'lad'), PYTHONIOENCODING='utf-8')
    (d / 'lad').mkdir(exist_ok=True)
    if a.window:
        cmd = [str(VENV / 'python.exe'), str(REPO / 'app' / 'desktop.py'), '--port', str(a.port)]
    else:
        cmd = [str(VENV / 'python.exe'), str(REPO / 'app' / 'server.py'), '--port', str(a.port)] + ([] if a.browser else ['--no-browser'])
    need(port_free(a.port), f'番号 {a.port} が使われている（--port で替える）')
    say(f'配布物のふりで起動する: http://127.0.0.1:{a.port}/（止めるのは Ctrl+C か画面の「終わる」）')
    say(f'   同梱物 {b}・設定 {cfgp}（{"初回の設定画面から" if a.first_run else "準備が済んだ形"}）')
    say(f'   デモ曲 {song}')
    return subprocess.call(cmd, cwd=str(REPO), env=env)


def cmd_parts(a):
    root = check_root(a.dir)
    pack = ensure_parts(root, a.variant)
    c = SI.check(str(pack))
    say(f'音を分ける部品: {pack}（{c.get("variant")}・ok={c.get("ok")}）')


def cmd_demo(a):
    song, cover = ensure_demo(check_root(a.dir))
    say(f'デモ曲: {song}・カバー: {cover}')


# ---------------------------------------------------------------- ② リリースの前の通しの確かめ

class Run:
    def __init__(self, root, a):
        self.root, self.a = root, a
        self.run = root / 'run'
        self.logs = self.run / 'logs'
        self.rows = []
        self.notes = {}

    @contextlib.contextmanager
    def step(self, name):
        t = time.time()
        say(f'▶ {name}')
        info = {}
        try:
            yield info
        except BaseException as e:
            msg = str(e) if isinstance(e, Fail) else f'{type(e).__name__}: {e}'
            self.rows.append((name, False, time.time() - t, msg))
            say(f'✗ {name}: {msg}')
            raise
        self.rows.append((name, True, time.time() - t, info.get('note', '')))
        say(f'✓ {name}（{time.time() - t:.0f} 秒）{info.get("note", "")}')

    def skip(self, name, why):
        self.rows.append((name, None, 0, why))
        say(f'－ {name}: {why}')

    def report(self, ok):
        lines = [f'# リリースの前の通しの確かめ（{time.strftime("%Y-%m-%d %H:%M", time.localtime(T0))} に始めた）', '',
                 f'- 結果: **{"通った" if ok else "通らなかった"}**（{time.time() - T0:.0f} 秒）',
                 *[f'- {k}: {v}' for k, v in self.notes.items()], '',
                 '| 段 | 結果 | 秒 | 中身 |', '|---|---|---|---|']
        for name, good, sec, msg in self.rows:
            mark = 'OK' if good else '－' if good is None else '**NG**'
            lines.append(f'| {name} | {mark} | {sec:.0f} | {str(msg).replace("|", "／").replace(chr(10), " ")[:600]} |')
        p = self.run / 'report.md'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return p


class Later:
    """段を裏（別の流れ）で先に始め、終わりは後の R.step の中で wait で待つ（互いに関係ない段を並べる・2026-11-15）。wait は fn の戻り値
    （fn の中の Fail などはそのまま上げる）。took＝fn にかかった秒"""

    def __init__(self, fn):
        self.t0, self.out, self.err, self.took = time.time(), None, None, None
        self.th = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self.th.start()

    def _run(self, fn):
        try:
            self.out = fn()
        except BaseException as e:   # noqa: BLE001  （待つ側で上げる）
            self.err = e
        self.took = time.time() - self.t0

    def wait(self, timeout=3600):
        self.th.join(timeout)
        need(not self.th.is_alive(), f'裏の段が {timeout} 秒で終わらない')
        if self.err:
            raise self.err
        return self.out


def dist_env(cfgp, lad, rel_url):
    """起動用の exe（launcher.cs）と同じ環境＋確かめ用の設定（本物の設定・作業フォルダ・GitHub を使わない）"""
    e = clean_env(env_like_launcher())
    e.update(AUTOMAP_CONFIG=str(cfgp), LOCALAPPDATA=str(lad), PYTHONIOENCODING='utf-8', AUTOMAP_UPDATE_URL=rel_url,
             AUTOMAP_UPDATE_NO_LAUNCH='1', AUTOMAP_NO_OPEN='1')
    return e


def kill_leftovers(root):
    """前の確かめで残ったプロセス（置き場の run/・C ドライブの写しの中の exe＝配布物の Python・パックの Python）を止める。
    コマンドの文字列では見ない（この台本を呼んだシェルの文字列に置き場の場所が入っていると、それごと止めてしまった）・自分と親は除く"""
    import psutil
    me = {os.getpid(), *(x.pid for x in psutil.Process().parents())}
    dirs = [str(root / 'run').lower() + os.sep, str(C_COPY).lower() + os.sep]
    n = 0
    for p in psutil.process_iter(['exe']):
        try:
            exe = (p.info['exe'] or '').lower()
        except (psutil.Error, OSError):
            continue
        if p.pid not in me and any(exe.startswith(d) for d in dirs):
            with contextlib.suppress(psutil.Error):
                p.kill()
                n += 1
    if n:
        say(f'前の確かめで残ったプロセスを {n} 個止めた')
        time.sleep(1)


def procs_with(text, under):
    """コマンドの文字列に text を含み、exe が under（置き場の run/）の中にあるプロセス（インストールの道具・pip）"""
    import psutil
    out, d = [], str(under).lower() + os.sep
    for p in psutil.process_iter(['exe', 'cmdline']):
        with contextlib.suppress(psutil.Error, OSError):
            if (p.info['exe'] or '').lower().startswith(d) and any(text in (c or '') for c in p.info['cmdline'] or []):
                out.append(p.pid)
    return out


def ver_of(app):
    try:
        return json.loads((Path(app) / 'build-info.json').read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, KeyError):
        return None


def bump(v):
    a, b, c = (int(x) for x in v.lstrip('v').split('.'))
    return f'v{a}.{b}.{c + 1}'


# ---- 窓のアプリ（WebView2）で左下の欄のリプレイ（2026-11-15 利用者「足してくれ」＝配布版のリプレイの確かめを毎回自動で） ----
# 起動用の exe から窓のアプリを起こし、WebView2 に CDP でつなぐ（WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS の --remote-debugging-port。
# 127.0.0.1 の TCP の口で認証が無い＝この段の間だけ・終わったら窓ごと止める）。リプレイは書き出したデモ曲の譜面から合成する
# （全部 GOOD・30fps のフレーム・点は満点の 95%）。見る物: #rstest=real（アプリで動かす → リプレイが付いてくる・リプレイで動かす → アプリが
# 付いてくる・再生・停止）・リプレイの窓が別のプロセスの iframe で自動再生が許されている・本物のマウスで ▶ → リプレイの窓の WebAudio が
# running になり時刻が進む・もう一度 ▶ で止まる・描く速さ（記録だけ＝窓が隠れていると落ちる）。

class _WS:
    """標準ライブラリだけの WebSocket（CDP 用・送る枠はマスクする）"""

    def __init__(self, url):
        import base64
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f'GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                        f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            c = self.s.recv(4096)
            if not c:
                raise Fail('WebView2 の CDP につながらない')
            buf += c
        need(b' 101 ' in buf.split(b'\r\n')[0], f'WebView2 の CDP: {buf[:120]!r}')
        self.rest = buf.split(b'\r\n\r\n', 1)[1]
        self.n, self.events = 0, []

    def _read(self, k):
        while len(self.rest) < k:
            c = self.s.recv(65536)
            if not c:
                raise Fail('WebView2 の CDP が切れた')
            self.rest += c
        out, self.rest = self.rest[:k], self.rest[k:]
        return out

    def _send(self, data, op=1):
        import struct
        m, n = os.urandom(4), len(data)
        size = bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack('>H', n) if n < 65536 else bytes([0x80 | 127]) + struct.pack('>Q', n)
        self.s.sendall(bytes([0x80 | op]) + size + m + bytes(b ^ m[i % 4] for i, b in enumerate(data)))

    def recv(self):
        import struct
        msg = b''
        while True:
            b0, b1 = self._read(2)
            ln = b1 & 0x7f
            if ln == 126:
                ln = struct.unpack('>H', self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack('>Q', self._read(8))[0]
            data, op = self._read(ln), b0 & 0x0f
            if op in (0, 1, 2):
                msg += data
                if b0 & 0x80:
                    return json.loads(msg.decode('utf-8'))
            elif op == 9:
                self._send(data, 0xA)
            elif op == 8:
                raise Fail('WebView2 の CDP が閉じた')

    def call(self, method, **params):
        self.n += 1
        i = self.n
        self._send(json.dumps({'id': i, 'method': method, 'params': params}).encode())
        while True:
            r = self.recv()
            if r.get('id') == i:
                if 'error' in r:
                    raise Fail(f'CDP {method}: {r["error"]}')
                return r.get('result', {})
            self.events.append(r)

    def js(self, expr):
        r = self.call('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        if r.get('exceptionDetails'):
            raise Fail(f'画面の中でエラー: {(r["exceptionDetails"].get("exception") or {}).get("description") or r["exceptionDetails"].get("text")}')
        return r.get('result', {}).get('value')

    def close(self):
        with contextlib.suppress(OSError):
            self.s.close()


def fake_replay(level, out_dir, diff):
    """書き出した譜面のフォルダ → 合成したリプレイ（.bsor・BeatLeader のファイル名の形）の場所。全部 GOOD・30fps のフレーム（頭と両手は
    決まった位置）・点は満点の 95%"""
    import hashlib
    import struct
    from automap import bsor
    info = json.loads((level / 'Info.dat').read_text(encoding='utf-8-sig'))
    bms = [bm for st in info['_difficultyBeatmapSets'] for bm in st['_difficultyBeatmaps']]
    bm = next(b for b in bms if b['_difficulty'] == diff)
    h = hashlib.sha1((level / 'Info.dat').read_bytes() + b''.join((level / b['_beatmapFilename']).read_bytes() for b in bms)).hexdigest().upper()
    dat = json.loads((level / bm['_beatmapFilename']).read_text(encoding='utf-8-sig'))
    bpm = float(info['_beatsPerMinute'])
    notes = sorted(dat.get('colorNotes') or [], key=lambda n: n['b'])
    need(notes, f'書き出した譜面にノーツが無い: {bm["_beatmapFilename"]}')

    def text(t):
        b = t.encode('utf-8')
        return struct.pack('<i', len(b)) + b

    def build(score):
        strs = ['0.9.0', '1.40.8', '1794394711', '76561190000000000', 'Player', 'steam', 'Oculus', 'Quest3', 'Touch', h,
                info['_songName'], info.get('_levelAuthorName') or '', diff]
        inf = b''.join(text(x) for x in strs) + struct.pack('<i', score)
        inf += text('Standard') + text('DefaultEnvironment') + text('') + struct.pack('<f?ffff', 17.0, False, 1.75, 0.0, 0.0, 1.0)
        nf = int((notes[-1]['b'] * 60 / bpm + 3) * 30)
        pose = b''.join(struct.pack('<3f4f', *pos, 0, 0, 0, 1) for pos in ((0, 1.6, 0), (-0.3, 1.1, 0.3), (0.3, 1.1, 0.3)))
        fr = struct.pack('<Bi', 1, nf) + b''.join(struct.pack('<fi', i / 30, 30) + pose for i in range(nf))
        ns = struct.pack('<Bi', 2, len(notes))
        for n in notes:
            t = n['b'] * 60 / bpm
            ns += struct.pack('<iffi', 30000 + n['x'] * 1000 + n['y'] * 100 + n['c'] * 10 + n['d'], t, t, bsor.GOOD)
            ns += struct.pack('<????f3fiff3f3f4f', True, True, True, False, 3.0, 0, 0, 1, 1, 0.0, 0.0, 0, 1, 0, 0, 0, 1, 0.0, 0.0, 1.0, 1.0)
        return (struct.pack('<iBB', bsor.MAGIC, 1, 0) + inf + fr + ns
                + struct.pack('<Bi', 3, 0) + struct.pack('<Bi', 4, 0) + struct.pack('<Bi', 5, 0))
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f'76561190000000000-{info["_songName"]}-{diff}-Standard-{h}-1794394711.bsor'
    f.write_bytes(build(0))
    f.write_bytes(build(int(bsor.max_score(bsor.read(f)['notes']) * 0.95)))
    return f


def _wv_page(dbg, base, sec):
    """WebView2 の CDP の口からアプリの画面の的（無ければ None）"""
    t0 = time.time()
    while time.time() - t0 < sec:
        with contextlib.suppress(OSError, ValueError):
            ts = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{dbg}/json/list', timeout=5).read())
            pg = next((t for t in ts if t.get('type') == 'page' and t.get('url', '').startswith(base + '/')), None)
            if pg:
                return pg, ts
        time.sleep(0.5)
    return None, []


def lad_log(R):
    """窓のアプリの記録（desktop.log）の終わり"""
    for f in R.run.rglob('desktop.log'):
        with contextlib.suppress(OSError):
            return f.read_text(encoding='utf-8', errors='replace')[-600:]
    return '窓のアプリの記録なし'


def window_replay(R, app, env, cfgp, level, diff, port, dbg):
    """窓のアプリ（起動用の exe → WebView2）で左下の欄のリプレイを確かめる → 段の中身の一言"""
    import base64
    import psutil
    for x in (port, port + 20, dbg):   # アプリ・リプレイの窓（アプリの番号＋20）・CDP
        need(port_free(x), f'番号 {x} が使われている（--port で替える）')
    rp = fake_replay(level, R.run / 'replays', diff)
    cfg = json.loads(cfgp.read_text(encoding='utf-8'))
    cfg['bl_replays'] = str(rp.parent)
    cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    e = dict(env, AUTOMAP_TOKEN=TOKEN, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={dbg}')
    subprocess.Popen([str(app / BE.EXE), '--port', str(port)], cwd=str(app), env=e)
    base = f'http://127.0.0.1:{port}'
    ws = fr = None
    try:
        page, _ = _wv_page(dbg, base, 180)
        need(page, f'窓のアプリが 180 秒で開かない（{lad_log(R)}）')
        ws = _WS(page['webSocketDebuggerUrl'])
        ws.call('Runtime.enable')
        ws.js(f"location.href = {json.dumps(f'{base}/#rstest=real&song={q(SONG)}&k={TOKEN}')}; location.reload(); 1")
        ws.close()
        time.sleep(2)
        t0, title = time.time(), ''
        while time.time() - t0 < 180 and title != 'rstest real ok' and not title.startswith('rstest real ng'):
            with contextlib.suppress(Fail, OSError, ValueError):
                if ws is None or ws.s.fileno() < 0:
                    page, _ = _wv_page(dbg, base, 30)
                    ws = _WS(page['webSocketDebuggerUrl'])
                title = ws.js('document.title') or ''
            time.sleep(0.5)
        out = ws.js("(document.getElementById('rstestOut') || {}).textContent || ''")
        (R.logs / 'window-replay.txt').write_text(out, encoding='utf-8')
        need(title == 'rstest real ok', f'#rstest=real が通らない（{title or "終わらない"}）: {out[:400]}')
        m1 = re.search(r'アプリで ([\d.]+) 秒へ: リプレイ=([\d.]+) S\.t=([\d.]+)', out)
        need(m1 and abs(float(m1[2]) - float(m1[1])) < 0.1 and abs(float(m1[3]) - float(m1[1])) < 0.1, f'アプリで動かしてもリプレイが付いてこない: {out[:400]}')
        m2 = re.search(r'リプレイで 60 秒へ: S\.t=([\d.]+) リプレイ=([\d.]+)', out)
        need(m2 and abs(float(m2[1]) - 60) < 0.1 and abs(float(m2[2]) - 60) < 0.1, f'リプレイで動かしてもアプリが付いてこない: {out[:400]}')
        need('リプレイ再生中=true' in out and '止める: リプレイ再生中=false' in out, f'再生・停止がそろわない: {out[:400]}')
        # リプレイの窓（別のプロセスの iframe）と、本物のマウスの ▶
        _, ts = _wv_page(dbg, base, 10)
        ifr = next((t for t in ts if t.get('type') == 'iframe' and '/blr' in t.get('url', '')), None)
        need(ifr, 'リプレイの窓が別のプロセスの iframe になっていない（同じプロセスで描くと遅い）')
        fr = _WS(ifr['webSocketDebuggerUrl'])
        fr.call('Runtime.enable')
        fr.call('WebAudio.enable')
        org = fr.js('location.origin')
        need(fr.js("document.featurePolicy ? document.featurePolicy.allowsFeature('autoplay') : true"), f'リプレイの窓で自動再生が許されていない（{org}）')
        btn = ws.js("(() => { const r = document.getElementById('play').getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()")

        def clock():
            m = re.match(r'\s*(\d+):([\d.]+)', ws.js("document.getElementById('time').textContent") or '')
            return int(m[1]) * 60 + float(m[2]) if m else None

        def click():
            for typ in ('mousePressed', 'mouseReleased'):
                ws.call('Input.dispatchMouseEvent', type=typ, x=btn['x'], y=btn['y'], button='left', clickCount=1)

        def fps(w):
            return w.js("new Promise(r => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 2000) "
                        "requestAnimationFrame(f); else r(Math.round(n * 1000 / (performance.now() - t0))); }; requestAnimationFrame(f); })")
        c0 = clock()
        click()
        time.sleep(3)
        c1 = clock()
        f_rep, f_app = fps(fr), fps(ws)
        for _ in range(3):
            fr.js('1')
        states = [((ev.get('params') or {}).get('context') or {}).get('contextState') for ev in fr.events if ev.get('method', '').startswith('WebAudio.context')]
        need(c0 is not None and c1 is not None and c1 - c0 > 1.5, f'▶ を押しても時刻が進まない: {c0} → {c1}')
        need('running' in states[-2:], f'▶ を押してもリプレイの窓の音（WebAudio）が動いていない: {states}')
        click()
        time.sleep(1)
        c2 = clock()
        time.sleep(1.5)
        c3 = clock()
        need(c2 is not None and c3 is not None and abs(c3 - c2) < 0.05, f'もう一度 ▶ を押しても止まらない: {c2} → {c3}')
        (R.logs / 'window-replay.png').write_bytes(base64.b64decode(ws.call('Page.captureScreenshot', format='png')['data']))
        return (f'{org} の別のプロセス・アプリで {float(m1[1]):g} 秒へ → リプレイ {float(m1[2]):.3f}・リプレイで 60 秒へ → アプリ {float(m2[1]):.3f}・'
                f'本物のマウスの ▶ で {c0:.1f} → {c1:.1f} 秒（WebAudio {states[-1]}）・もう一度で止まる・描く速さ リプレイ {f_rep}fps／アプリ {f_app}fps'
                '（窓が隠れていると落ちる）・画面は logs/window-replay.png')
    finally:
        for w in (ws, fr):
            if w:
                w.close()
        with contextlib.suppress(OSError, Fail):
            api(base, 'POST', '/api/shutdown', {}, timeout=5)
        t0 = time.time()
        under = str(app).lower() + os.sep
        while time.time() - t0 < 20:   # 窓のアプリ（配布物の Python）が終わるまで・残れば止める
            left = []
            for p in psutil.process_iter(['exe']):
                with contextlib.suppress(psutil.Error, OSError):
                    if (p.info['exe'] or '').lower().startswith(under):
                        left.append(p)
            if not left:
                break
            if time.time() - t0 > 15:
                for p in left:
                    with contextlib.suppress(psutil.Error):
                        p.kill()
            time.sleep(0.5)


def cmd_release(a):
    import psutil  # noqa: F401  （後片付けに使う・無ければ先に止める）
    root = check_root(a.dir)
    R = Run(root, a)
    kill_leftovers(root)
    rmtree(R.run)
    R.logs.mkdir(parents=True)
    build = root / 'build' / BE.NAME
    rel_a = root / 'build' / 'release'
    app = R.run / 'app' / BE.NAME
    work = R.run / '作業 フォルダ'
    cfgp, lad = R.run / 'config.json', R.run / 'lad'
    levels, playlists = R.run / 'levels', R.run / 'playlists'
    srv = rels = None
    ok = False
    try:
        # 0. テスト（全部）。曲の解析の答え合わせ（NLM と同じ答え）は普段は控えで済ませるので、ここでは必ず計算する
        #    （tests/test_song_analysis.py の AUTOMAP_FULL_ANALYSIS・2026-11-09 利用者「リリース前に確認が出来ていれば良い」）
        def run_tests():
            env = dict(os.environ, PYTHONIOENCODING='utf-8', AUTOMAP_FULL_ANALYSIS='1')
            r = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=str(REPO), capture_output=True, env=env, timeout=1800)
            out = (r.stdout + r.stderr).decode('utf-8', 'replace')
            (R.logs / 'pytest.log').write_text(out, encoding='utf-8')
            tail = ([ln.strip(' =') for ln in out.splitlines() if ln.strip()] or [''])[-1]
            need(r.returncode == 0, f'通らなかった（{R.logs / "pytest.log"}）: {tail}')
            ana = [ln for ln in out.splitlines() if ln.startswith('曲の解析の答え合わせ')]
            need(len(ana) == 2 and all('計算して NLM と同じ' in ln for ln in ana),
                 f'曲の解析の答え合わせを計算していない: {ana or "飛ばした（NLM で作った元のプロジェクトと音源が無い）"}')
            return f'{tail}・' + '／'.join(ln.split('）: ', 1)[-1] for ln in ana)
        tests = None
        if a.skip_tests:
            R.skip('テスト（全部）', '--skip-tests')
        else:   # 配布物を作るのと同時に（互いに関係ない・待つのは作った後）
            say('▶ テスト（全部・曲の解析の答え合わせは控えを使わずに計算）を裏で始めた（配布物を作るのと同時に）')
            tests = Later(run_tests)

        # 1. 配布物を作る
        if a.skip_build:
            need((build / 'build-info.json').exists(), f'前に作った配布物が無い（{build}）: --skip-build を外す')
            R.skip('配布物を作る', f'前に作った物（{ver_of(build)}）')
        else:
            with R.step('配布物を作る（build_embed.py --compile --zip）') as s:
                vb = root / 'venv-build' / 'Scripts' / 'python.exe'
                if not vb.exists():
                    say('   ビルド用の Python を作る（py -3.14 -m venv）')
                    subprocess.run(['py', '-3.14', '-m', 'venv', str(root / 'venv-build')], check=True)
                with open(R.logs / 'build.log', 'wb') as lf:
                    r = subprocess.run([str(vb), str(HERE / 'build_embed.py'), '--work', str(root), '--compile', '--zip'], cwd=str(REPO),
                                       stdout=lf, stderr=subprocess.STDOUT, env=clean_env(dict(os.environ, PYTHONIOENCODING='utf-8')))
                text = (R.logs / 'build.log').read_text(encoding='utf-8', errors='replace')
                need(r.returncode == 0, f'作れなかった（{R.logs / "build.log"}）: {text[-800:]}')
                sz = re.search(r'大きさ: (.*)', text)
                s['note'] = f'{ver_of(build)}・{sz.group(1)[:120] if sz else ""}'
        if tests:
            with R.step('テスト（全部・曲の解析の答え合わせは控えを使わずに計算・配布物を作るのと同時に）') as s:
                s['note'] = tests.wait() + f'（裏で {tests.took:.0f} 秒）'
        info = json.loads((build / 'build-info.json').read_text(encoding='utf-8'))
        A = info['version']
        R.notes.update({'版': A, 'コード（git describe）': info.get('git'), '埋め込み用の Python': info.get('python'), '作った時刻': info.get('built')})

        # 2. 配布物の中の確かめ（check_dist.py・自分の番号と作業の場所で動く＝入れた後に裏で始め、取り込みの後で待つ）
        cd_name = '配布物の中の確かめ（check_dist.py' + (' --window' if a.window else '') + '・裏で）'

        def run_check_dist():
            cmd = [sys.executable, str(HERE / 'check_dist.py'), str(build), '--scratch', str(R.run / 'check_dist'), '--port', str(a.port + 3)]
            r = subprocess.run(cmd + (['--window'] if a.window else []), capture_output=True, timeout=900, env=clean_env())
            out = r.stdout.decode('utf-8', 'replace')
            (R.logs / 'check_dist.log').write_text(out + r.stderr.decode('utf-8', 'replace'), encoding='utf-8')
            steps = [json.loads(ln) for ln in out.splitlines() if ln.startswith('{"step"')]
            bad = [x['step'] for x in steps if not x['ok']]
            need(steps and not bad and r.returncode == 0, f'通らなかった段: {bad or "（記録が無い）"}（{R.logs / "check_dist.log"}）')
            return f'{len(steps)} 段'

        # 3. 入れる（展開した形の写し＝更新で書き換わる）
        with R.step('配布物を入れる（作業用の写し）') as s:
            shutil.copytree(build, app)
            nb0 = flow_cache(app)
            need(any(k.endswith('.nbi') for k in nb0), f'流れの計算（Numba）のコンパイル済みの控えが無い（{app / "automap" / "__pycache__"}）')
            s['note'] = f'{app}・流れの計算の控え {len(nb0)} 個'
        say(f'▶ {cd_name}を始めた')
        cd = Later(run_check_dist)   # 写し終わってから（check_dist が build/ に書いても写しは変わらない）

        rels = Releases(a.port + 1)
        if (rel_a / 'update.json').exists():
            rels.publish(rel_a)   # 今の版＝最新（起動した時の更新の確かめは「最新です」）
        env = dist_env(cfgp, lad, rels.url)
        cfgp.write_text(json.dumps({'bs_levels': str(levels), 'bs_playlists': str(playlists)}, ensure_ascii=False) + '\n', encoding='utf-8')
        for x in (levels, playlists, lad):
            x.mkdir(parents=True, exist_ok=True)
        srv = Server('app', app / 'runtime' / 'python.exe', app, env, a.port, R.logs)

        # 4. まっさらな設定で起動
        with R.step('まっさらな設定で起動') as s:
            st = srv.start()
            need(st['distributed'] and not st['as_dist'], f'配布物として動いていない: {st.get("distributed")}')
            need(st['need_setup'] and not st['work']['ok'], '作業フォルダを聞かない（まっさらなのに準備が済んでいる）')
            lib, rt = st['library'], st['rating']
            need(lib['ok'] and lib.get('dist') and Path(lib['path']).resolve() == (app / 'data' / 'library-dist.sqlite').resolve(),
                 f'型のライブラリが同梱の物でない: {lib}')
            need(rt['ok'] and rt.get('bundled'), f'★を測る部品が同梱の物でない: {rt}')
            need(not st['sep']['ok'] and st['sep'].get('kind') is None, f'音を分ける部品が入っていることになっている: {st["sep"]}')
            up = srv.get('/api/update/status')
            need(up['distributed'] and up['current'] == A, f'更新の状態: {up}')
            need(srv.get('/api/songs') == [], '曲の一覧が空でない')
            s['note'] = f'型のライブラリ {lib.get("maps")} 曲・nlm-rating {rt.get("version")}'

        # 5. 作業フォルダ
        with R.step('作業フォルダを決める（日本語と空白の入った場所）') as s:
            st = srv.post('/api/setup/settings', {'work_dir': str(work)})
            need(st['work']['ok'] and (work / 'out').is_dir() and (work / 'cache').is_dir(), f'作業フォルダ: {st["work"]}')
            s['note'] = f'空き {st["work"].get("free", 0) / 1e9:.0f}GB'

        # 6. 音を分ける部品（CPU 版）
        pack = work / 'parts' / 'separate'
        with R.step('音を分ける部品（CPU 版）: 見積もり → インストール → 途中でアプリを強制終了 → 続きから') as s:
            p = srv.get(f'/api/setup/plan?dir={q(pack)}&variant=cpu')
            need(not p.get('problems') and not p.get('ng_set'), f'見積もりで止まる: {p.get("problems")} {p.get("ng_set")}')
            pyrow = [it.get('source') for it in p.get('items') or [] if it.get('key') == 'python']
            note = f'ダウンロード {mb(p.get("download_bytes"))}・展開後 {mb(p.get("install_bytes"))}・Python の元 {pyrow}'
            if a.net:
                note += '・控えを使わない（--net）'
            else:
                seed_pack(pack, 'cpu', fill_sep_cache(root, 'cpu'))
            jid = srv.post('/api/setup/install', {'dir': str(pack), 'variant': 'cpu'})['id']
            j = srv.wait_job(jid, timeout=3600, what='インストール: ',
                             until=lambda j: (j.get('progress') or {}).get('stage') in ('pip', 'weights', 'verify'))
            if j['state'] == 'running':
                stage = (j.get('progress') or {}).get('stage')
                srv.kill()
                time.sleep(3)
                left = procs_with(str(pack), R.run)
                need(not left, f'アプリを強制終了してもインストールの道具が止まらない（{left}）')
                st = srv.start()
                need(not st['sep']['ok'] and st['sep'].get('pending'), f'開き直した時に「続きから」にならない: {st["sep"]}')
                note += f'・{stage} の段で強制終了 → 道具も止まった → 続きから'
                jid = srv.post('/api/setup/install', {'dir': str(pack), 'variant': 'cpu'})['id']
                srv.wait_job(jid, timeout=3600, what='続きから: ')
            else:
                note += '・（止める前に終わった）'
            st = srv.get('/api/setup/status')
            need(st['sep']['ok'] and st['sep'].get('kind') == 'pack' and st['sep'].get('variant') == 'cpu', f'インストールした後: {st["sep"]}')
            st = srv.post('/api/setup/done')
            need(st['ready'] and not st['need_setup'], f'準備が済まない: ready={st["ready"]}')
            s['note'] = note

        # 7. デモ曲の取り込み
        song, _ = ensure_demo(root)
        file = f'{SONG}.intent-s1.nlmf'
        with R.step('デモ曲の取り込み（音を分ける → 解析 → 最初の譜面）') as s:
            pr = srv.post('/api/import/probe', {'path': str(song)})
            lib = srv.get('/api/library')
            need(lib.get('available') and lib.get('dist'), f'型のライブラリが使えない: {lib.get("error")}')
            need(pr.get('title') == SONG and pr.get('covers'), f'音源の下見: 曲名 {pr.get("title")}・カバーの候補 {pr.get("covers")}')
            r = srv.post('/api/import/start', {'path': pr['path'], 'name': SONG, 'title': pr['title'], 'artist': pr.get('artist') or '',
                                                'cover': pr['covers'][0], 'library': lib['default']})
            srv.wait_job(r['id'], timeout=3600, what='取り込み: ')
            out = work / 'out'
            need((out / file).exists() and (out / f'{SONG}.intent-s1.report.md').exists(), f'結果のファイル・報告が無い: {sorted(x.name for x in out.iterdir())}')
            sep = json.loads((work / 'cache' / SONG / 'separate.json').read_text(encoding='utf-8'))
            ex = srv.get(f'/api/expand?file={q(file)}')
            base = ex['base']
            row = next(x for x in ex['diffs'] if x['diff'] == base)
            need(row.get('notes', 0) > 50, f'基準の難易度のノーツが少ない: {row}')
            rp = (out / f'{SONG}.intent-s1.report.md').read_text(encoding='utf-8')
            need('データベースが使えない' not in rp, '型のデータベースが使えなかった')
            s['note'] = f'{base} {row["notes"]} ノーツ・{row.get("nps")}/秒・分けた音 {json.dumps(sep, ensure_ascii=False)[:160]}'

        with R.step(cd_name) as s:
            s['note'] = cd.wait() + f'（裏で {cd.took:.0f} 秒）'

        # 8. 作り直し
        with R.step('作り直し（全部）') as s:
            before = srv.get(f'/api/versions?file={q(file)}')['versions']
            r = srv.post('/api/generate', {'file': file})
            srv.wait_job(r['id'], timeout=1800, what='作り直し: ')
            after = srv.get(f'/api/versions?file={q(file)}')
            need(after['current'] and len(after['versions']) >= len(before), f'履歴: {len(before)} → {len(after["versions"])}・今の版 {after["current"]}')
            # 最初の譜面（取り込み）とこの作り直しで、流れの計算（Numba）をコンパイルしなかった＝控えが増えも書き換わりもしない
            # （コンパイルすると 20 秒ほどかかり、控えを足す・書き換える・build_embed.py の warm_flow）
            nb1 = flow_cache(app)
            need(nb1 == nb0, f'流れの計算をコンパイルした（控えが変わった: {sorted(set(nb1.items()) ^ set(nb0.items()))[:6]}）')
            s['note'] = f'履歴 {len(before)} → {len(after["versions"])} 版・流れの計算はコンパイルしなかった（控え {len(nb1)} 個のまま）'

        # 9. ★
        with R.step('★（同梱の nlm-rating）') as s:
            r = srv.get(f'/api/rating?file={q(file)}&wait=120', timeout=180)
            need(r.get('ok') and isinstance(r.get('stars'), (int, float)), f'測れない: {r.get("error") or r}')
            s['note'] = f'★{r["stars"]}（{r.get("view_diff")}・nlm-rating {r.get("version")}）'

        # 10. 難易度の展開
        with R.step('難易度の展開（基準から下へ 2 つ）') as s:
            order = ex['order']
            downs = [d for d in reversed(order[:order.index(base)])][:2]
            pl = srv.post('/api/expand/plan', {'file': file, 'base': base, 'targets': downs})
            tg = [{'diff': d, 'ratio': pl['plans'][d]['ratio'], 'library': pl['plans'][d].get('library')} for d in downs]
            r = srv.post('/api/expand/start', {'file': file, 'from': base, 'base': base, 'targets': tg})
            j = srv.wait_job(r['id'], timeout=1800, what='展開: ')
            res = {x['diff']: x for x in j.get('results') or []}
            need(all(res.get(d, {}).get('notes') for d in downs), f'派生ができていない: {[(d, res.get(d, {}).get("notes"), res.get(d, {}).get("error")) for d in downs]}')
            s['note'] = '・'.join(f'{d} {res[d]["notes"]} ノーツ（割合 {res[d].get("got")}）' for d in downs)

        # 11. Beat Saber に書き出す
        with R.step('Beat Saber に書き出す（置き場の中・2 回＝プレイリストは 1 行）') as s:
            folder = 'ANP-check-demo'
            for n in (1, 2):
                p = srv.get(f'/api/bsexport/plan?file={q(file)}')
                plan = p['plan']
                ch = dict(plan['info'], levelAuthorName='ANP の確かめ')
                for k in ('bpm', 'environment', 'cover', 'cover_embedded'):
                    ch.pop(k, None)
                ds = [d['diff'] for d in plan['diffs'] if not d['empty']]
                r = srv.post('/api/bsexport/run', {'file': file, 'changes': ch, 'folder': folder, 'diffs': ds, 'playlist': {'title': 'Auto Note Plotter'},
                                                   'levels': str(levels), 'save_info': True})
                srv.wait_job(r['id'], timeout=600, what=f'書き出し {n}: ')
            dst = levels / folder
            infod = json.loads((dst / 'Info.dat').read_text(encoding='utf-8'))
            names = [bm['_beatmapFilename'] for st_ in infod['_difficultyBeatmapSets'] for bm in st_['_difficultyBeatmaps']]
            need(all((dst / x).exists() for x in names) and (dst / infod['_songFilename']).stat().st_size > 100_000, f'書き出した物が足りない: {sorted(x.name for x in dst.iterdir())}')
            need(infod.get('_levelAuthorName') == 'ANP の確かめ', f'マッパー名: {infod.get("_levelAuthorName")}')
            import hashlib
            h = hashlib.sha1((dst / 'Info.dat').read_bytes() + b''.join((dst / x).read_bytes() for x in names)).hexdigest().upper()
            bp = json.loads((playlists / 'AutoNotePlotter.bplist').read_text(encoding='utf-8'))
            need(len(bp['songs']) == 1 and bp['songs'][0]['hash'] == h, f'プレイリスト: 曲 {len(bp["songs"])}・hash が合う {bp["songs"][0]["hash"] == h if bp["songs"] else None}')
            s['note'] = f'{len(names)} 難易度・song.egg {mb((dst / infod["_songFilename"]).stat().st_size)}・プレイリスト 1 行'
        srv.stop()

        # 13. C ドライブ（窓のアプリの段と同時に・設定と LOCALAPPDATA は写し＝窓の段が設定を書いても読み違えない・作業フォルダは同じ物を読むだけ）
        cdrive = None
        if a.no_c:
            R.skip('C ドライブに写して起動', '--no-c')
        else:
            cfg_c, lad_c = R.run / 'config-c.json', R.run / 'lad-c'
            shutil.copy2(cfgp, cfg_c)
            lad_c.mkdir(exist_ok=True)
            env_c = dist_env(cfg_c, lad_c, rels.url)

            def run_cdrive():
                cdir = C_COPY / BE.NAME
                rmtree(cdir.parent)
                t = time.time()
                shutil.copytree(build, cdir)
                took = time.time() - t
                cs = Server('c-drive', cdir / 'runtime' / 'python.exe', cdir, env_c, a.port + 2, R.logs)
                try:
                    st = cs.start()
                    need(st['ready'] and not st['need_setup'], f'準備が揃っていない: {st["work"]} {st["sep"].get("missing")}')
                    need(Path(st['library']['path']).resolve().drive.upper() == cdir.drive.upper() and st['rating'].get('bundled'), f'同梱物: {st["library"]["path"]}')
                    need(any(x['song'] == SONG for x in cs.get('/api/songs')), '曲の一覧にデモ曲が無い')
                finally:
                    cs.stop()
                rmtree(cdir.parent)
                return f'{cdir.drive} に写すのに {took:.0f} 秒'
            say('▶ C ドライブに写して起動（作業フォルダはそのまま）を裏で始めた（窓のアプリの段と同時に）')
            cdrive = Later(run_cdrive)

        # 12. 窓のアプリ（WebView2）で左下の欄のリプレイ（書き出したデモ曲の合成リプレイ）
        if a.no_window_replay:
            R.skip('窓のアプリでリプレイ', '--no-window-replay')
        else:
            with R.step('窓のアプリ（起動用の exe → WebView2）で左下の欄のリプレイ（合成したリプレイ・同期・▶ で音・描く速さ）') as s:
                s['note'] = window_replay(R, app, env, cfgp, levels / folder, base, a.port + 5, a.port + 6)

        if cdrive:
            with R.step('C ドライブに写して起動（作業フォルダはそのまま・窓のアプリの段と同時に）') as s:
                s['note'] = cdrive.wait() + f'（裏で {cdrive.took:.0f} 秒）'

        # 14. 更新
        if a.no_update:
            R.skip('更新', '--no-update')
        else:
            B = bump(A)
            with R.step(f'更新（{A} → {B}・手元の配布元）') as s:
                vb = R.run / 'vB' / BE.NAME
                shutil.copytree(build, vb)
                BE.set_version(vb, B)
                bi = json.loads((vb / 'build-info.json').read_text(encoding='utf-8'))
                (vb / 'build-info.json').write_text(json.dumps(dict(bi, version=B), ensure_ascii=False, indent=1), encoding='utf-8')
                say('   次の版の zip と update.json を作る')
                BE.make_release(vb, B, R.run / 'vB' / 'release', level=1)   # 確かめ用の次の版＝速く作る（中身と確かめは本物と同じ）
                rels.publish(R.run / 'vB' / 'release')
                srv.start()
                c = srv.get('/api/update/check')
                need(c['newer'] and c['latest'] == B and c['auto'] == 'ok', f'新しい版が見つからない: {c}')
                r = srv.post('/api/update/download')
                srv.wait_job(r['id'], timeout=600, what='更新: ')
                need((app / '_update' / 'new' / BE.NAME / BE.EXE).is_file(), '展開した新しい版が無い')
                r = srv.post('/api/update/apply')
                need(r.get('ok'), f'差し替えを始められない: {r}')
                srv.stop()
                logf = app / '_update' / 'apply.log'
                t = time.time()
                while time.time() - t < 180:
                    txt = logf.read_text(encoding='utf-8', errors='replace') if logf.exists() else ''
                    if 'できた:' in txt or '失敗' in txt:
                        break
                    time.sleep(0.3)
                time.sleep(1.5)
                txt = logf.read_text(encoding='utf-8', errors='replace') if logf.exists() else ''
                (R.logs / 'apply.log').write_text(txt, encoding='utf-8')
                need('できた:' in txt, f'差し替えに失敗: {txt[-600:]}')
                need(ver_of(app) == B and ver_of(app / f'_previous_{A}') == A, f'差し替えた後の版: {ver_of(app)}・前の版 {ver_of(app / f"_previous_{A}")}')
                srv.start()
                u = srv.get('/api/update/status')
                need(u['current'] == B and u['justUpdated'] == {'from': A, 'to': B}, f'起動し直した版: {u}')
                t = time.time()
                while (app / '_update').exists() and time.time() - t < 60:
                    time.sleep(0.3)
                need(not (app / '_update').exists(), '_update が片付かない')
                st = srv.get('/api/setup/status')
                need(st['ready'] and any(x['song'] == SONG for x in srv.get('/api/songs')), '更新の後に準備・曲の一覧が変わった')
                srv.stop()
                s['note'] = f'配布元への要求 {len(rels.hits)}・前の版は _previous_{A}'
        ok = True
    except Fail as e:
        if not R.rows or R.rows[-1][1] is not False:   # 段の外（準備）で止まった
            R.rows.append(('（準備）', False, 0, str(e)))
    except Exception as e:   # noqa: BLE001  （思わぬ物も報告に残す）
        if not R.rows or R.rows[-1][1] is not False:
            R.rows.append(('（思わぬエラー）', False, 0, f'{type(e).__name__}: {e}'))
        import traceback
        traceback.print_exc()
    finally:
        for s_ in (srv,):
            if s_:
                s_.stop()
                s_.kill()
        if rels:
            rels.close()
    if ok:   # 大きい写しは消す（作業フォルダ・記録・報告は残す）
        for x in (R.run / 'app', R.run / 'vB', R.run / 'check_dist', R.run / 'lad-c'):
            with contextlib.suppress(Fail):
                rmtree(x)
    p = R.report(ok)
    say(('通った' if ok else '通らなかった') + f': {p}')
    return 0 if ok else 1


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='確かめのセット（docs/アプリ仕様.md 23 節）')
    ap.add_argument('--dir', help='確かめの置き場（既定＝app/config.local.json の check_dir）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dev', help='① 配布物のふりでアプリを起動する')
    d.add_argument('--first-run', action='store_true', help='まっさらな設定（初回の設定画面）から')
    d.add_argument('--parts', default='cpu', choices=[*SI.VARIANTS, 'none'], help='使い回す音を分ける部品（既定 cpu・無ければ入れる）')
    d.add_argument('--port', type=int, default=8775)
    d.add_argument('--window', action='store_true', help='窓のアプリ（app/desktop.py）で開く')
    d.add_argument('--browser', action='store_true', help='ブラウザで開く')
    d.add_argument('--keep', action='store_true', help='前の設定・作業フォルダを残す')
    r = sub.add_parser('release', help='② リリースの前の通しの確かめ')
    r.add_argument('--skip-tests', action='store_true', help='テスト（全部・曲の解析の答え合わせは必ず計算）を飛ばす')
    r.add_argument('--skip-build', action='store_true', help='前に作った配布物（build/）を使う')
    r.add_argument('--net', action='store_true', help='音を分ける部品を控えから置かずに本当にダウンロードする')
    r.add_argument('--window', action='store_true', help='窓のアプリも確かめる（check_dist.py --window・画面に窓が出る）')
    r.add_argument('--no-c', action='store_true', help='C ドライブに写して起動するのを飛ばす')
    r.add_argument('--no-update', action='store_true', help='更新を飛ばす')
    r.add_argument('--no-window-replay', action='store_true', help='窓のアプリ（WebView2）で左下の欄のリプレイを確かめるのを飛ばす（画面に窓が出る）')
    r.add_argument('--port', type=int, default=8776, help='使う番号の頭（+1 配布元・+2 C ドライブ・+3 check_dist・+5 窓のアプリ（+25 リプレイの窓）・+6 WebView2 の CDP）')
    p = sub.add_parser('parts', help='音を分ける部品を parts/<種類>/ に入れる')
    p.add_argument('--variant', default='cpu', choices=list(SI.VARIANTS))
    sub.add_parser('demo', help='デモ曲を作る')
    a = ap.parse_args(argv)
    try:
        return {'dev': cmd_dev, 'release': cmd_release, 'parts': cmd_parts, 'demo': cmd_demo}[a.cmd](a) or 0
    except Fail as e:
        say(f'止めた: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
