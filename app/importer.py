"""新しい曲の取り込み（docs/アプリ仕様.md 8 節の6・10 節・17 節）: 音源を選ぶ → 音を分ける → 曲の解析 → 元のプロジェクト → 基本設定を待つ → 最初の譜面。
server.py の connect() が routes(ctx) を呼んでつなぐ（ctx＝server モジュール。OUT・CACHE は呼ばれた時に ctx から読む＝--out・--cache）。

- 音源を選ぶ: サーバーの PC の「ファイルを開く」窓（PICKER。ブラウザで使う時は tkinter を別のプロセスで出す＝サーバーの流れを止めない。
  窓のアプリ（app/desktop.py）では use_window_picker で pywebview の窓のファイルの窓に替える）か、場所を文字で入れる。選んだら曲名・アーティスト（タグ。無ければファイル名）・
  長さ・カバー画像の候補（同じフォルダの Cover.jpg 等）・同じ名前の曲が out/・cache/ にあるかを返す（/api/import/probe）。
- 取り込みの作業（ctx.start_job・kind='import'）: ① 音を分ける（「準備と設定」で入れた部品か .venv-sep の tools/separate.py・分けてあれば使い回す）② 曲の解析
  （automap/analyze_song.py を別のプロセスで → cache/<名前>/analysis.json。元の音源だけを読むので ① の頭で裏に始め、① と同時に動かす
  ＝② の段は終わりを待つだけ・_side_start・2026-11-11）③ 元のプロジェクト out/<名前>.nlmf を NLM を使わずに作る
  （automap/new_project.py・カバー画像も）④ 基本設定を待つ（画面の基本設定の窓で決めた型のライブラリ＝POST /api/import/settings が
  job['settings'] に入るまで。届いていればすぐ抜ける・やめるで止まる・抜けたら決め直せない＝job['settings_locked']）⑤ 最初の譜面
  （compose --form --style → out/<名前>.intent-s1.nlmf。基本設定の型のライブラリを作業ファイルの library に入れて --library で渡す＝
  put_library。作業ファイルがもうあっても基本設定が勝つ・None＝新しい曲の既定）。
  基本設定の段は plan(wait=True) の時だけ（画面からの取り込み）。無い時（コマンド・前のテスト）は、作業ファイルが無ければ
  library_use.DEFAULT 入りで作る（new_library）。既定の時期は「自動」（years＝'auto'・2026-11-03 から）＝曲ごとに手本の時期を決める
  （compose が曲の名前で置き換える・記録にはその曲の時期を書く＝app/library.auto_view）。
  元のプロジェクトがもうあれば ②③ は使い回す（「作り直す」の時は控えを out/old/ に取ってから作る）。結果のファイル（out/<名前>.*.nlmf）が
  もうある名前は取り込まない（取り込んである曲を上書きしない＝名前を変えてもらう）。取り込みは1度に1曲。
"""
import codecs
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automap import new_project as NP  # noqa: E402
from automap import library_use as LU  # noqa: E402

KIND = 'import'
# 音を分ける環境（PyTorch＋Demucs）は setup.sep_runner（「準備と設定」で入れたパック・開発の PC は .venv-sep）
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
WAIT_LABEL = '基本設定を待つ'   # 段の名前（画面の importer.js も同じ名前で見分ける）
WAIT_POLL = 0.25                # 基本設定が届いたか・やめるかを見る間（秒）
_SET_LOCK = threading.Lock()    # 基本設定を受ける受け口と、待つ段の抜け際を分ける（抜けた後に届いた設定は断る）


# ---- ファイルを選ぶ窓 ----
# tkinter の窓を別のプロセスで出す（サーバーの受け答えの流れでは Tk を動かせない・窓を閉じるまで待つのはその要求だけ）。
# exe（pywebview）にする時は PICKER を fn(kind, initial) → パスか None の別の物（window.create_file_dialog）に替える。
TK_PICK = r'''
import sys, tkinter as tk
from tkinter import filedialog
kind, init = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else '')
root = tk.Tk()
root.withdraw()
try:
    root.attributes('-topmost', True)
except Exception:
    pass
root.update()
if kind == 'folder':
    p = filedialog.askdirectory(parent=root, title='フォルダを選ぶ', initialdir=init or None, mustexist=False)
    root.destroy()
    sys.stdout.buffer.write((p or '').encode('utf-8'))
    raise SystemExit(0)
if kind == 'image':
    title, types = 'カバー画像を選ぶ', [('画像', '*.jpg *.jpeg *.png'), ('すべてのファイル', '*.*')]
elif kind == 'exe':
    title, types = 'プログラム（exe）を選ぶ', [('プログラム', '*.exe'), ('すべてのファイル', '*.*')]
else:
    title, types = '取り込む曲の音源を選ぶ', [('音源', '*.flac *.wav *.mp3 *.ogg *.m4a *.aac *.opus *.aiff *.aif *.wma'), ('すべてのファイル', '*.*')]
p = filedialog.askopenfilename(parent=root, title=title, filetypes=types, initialdir=init or None)
root.destroy()
sys.stdout.buffer.write((p or '').encode('utf-8'))
'''


def tk_pick(kind, initial=None, timeout=1800):
    r = subprocess.run([sys.executable, '-c', TK_PICK, kind, str(initial or '')], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    if r.returncode:
        raise ValueError('ファイルを選ぶ窓を出せなかった: ' + r.stderr.decode('utf-8', 'replace')[-300:])
    p = r.stdout.decode('utf-8', 'replace').strip()
    return str(Path(p)) if p else None


PICKER = tk_pick

# 窓のアプリ（pywebview）のファイルの窓の種類（'説明 (*.拡張子;…)' の形＝pywebview の決まり）
WINDOW_TYPES = {'audio': ('音源 (*.flac;*.wav;*.mp3;*.ogg;*.m4a;*.aac;*.opus;*.aiff;*.aif;*.wma)', 'すべてのファイル (*.*)'),
                'image': ('画像 (*.jpg;*.jpeg;*.png)', 'すべてのファイル (*.*)'),
                'exe': ('プログラム (*.exe)', 'すべてのファイル (*.*)')}


def use_window_picker(window):
    """窓のアプリ（app/desktop.py）: PICKER を pywebview の窓のファイルの窓（window.create_file_dialog）に替える＝アプリの窓の上に出る。
    ブラウザで使う時（app/server.py）は呼ばない＝tkinter のまま"""
    global PICKER
    import webview   # 窓のアプリの時だけ（pywebview が無い環境でもこのモジュールは読める）

    def pick(kind, initial=None):
        init = str(initial or '')
        if init and not Path(init).is_dir():
            init = str(Path(init).parent) if Path(init).parent.is_dir() else ''
        if kind == 'folder':
            r = window.create_file_dialog(webview.FileDialog.FOLDER, directory=init)
        else:
            r = window.create_file_dialog(webview.FileDialog.OPEN, directory=init, allow_multiple=False,
                                          file_types=WINDOW_TYPES[kind if kind in WINDOW_TYPES else 'audio'])
        if isinstance(r, (list, tuple)):
            r = r[0] if r else None
        return str(Path(r)) if r else None

    PICKER = pick
    return pick


_PICK_LOCK = threading.Lock()
_LAST_DIR = {}          # 種類ごとに最後に選んだフォルダ（次に窓を出す時の始まり）
_SEEN = set()           # 画面に見せてよい画像（probe の候補・窓で選んだ物・貼り付けた物）＝/api/import/cover が返すのはこれだけ
PASTE_DIR = Path(tempfile.gettempdir()) / 'automap-paste'   # 貼り付けたカバー画像の置き場（取り込みで結果のファイルの隣へ写す）
PASTE_MAX = 12 * 1024 * 1024   # 貼り付けた画像の大きさの上限（画面で正方形・1024px 以下の jpg にしてから送る）


def save_pasted(data):
    """貼り付けた画像（data: URL か base64・jpg か png）→ PASTE_DIR に書いた場所（画面に見せてよい画像に足す）。
    2026-11-03 利用者「クリップボードに上がっている画像をそのまま取り込む・いちいちファイルで保存するのはめんどくさい」"""
    import base64
    import binascii
    import uuid
    s = str(data or '')
    if s.startswith('data:'):
        s = s.split(',', 1)[1] if ',' in s else ''
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('画像を読めない（貼り付けの中身が画像でない）')
    if not raw or len(raw) > PASTE_MAX:
        raise ValueError('画像が空か大きすぎる')
    ext = '.jpg' if raw[:3] == b'\xff\xd8\xff' else '.png' if raw[:8] == b'\x89PNG\r\n\x1a\n' else None
    if not ext:
        raise ValueError('カバー画像は jpg・png')
    PASTE_DIR.mkdir(parents=True, exist_ok=True)
    dst = PASTE_DIR / f'貼り付け-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:4]}{ext}'
    dst.write_bytes(raw)
    _SEEN.add(str(dst))
    return dst


# ---- 名前・同じ名前の曲 ----

def clean_path(s):
    """入れた場所の文字（エクスプローラーの「パスのコピー」の引用符・前後の空白を落とす）→ Path"""
    s = str(s or '').strip().strip('"').strip("'").strip()
    if not s:
        raise ValueError('音源の場所が空')
    return Path(os.path.expanduser(s))


def conflicts(ctx, name):
    """同じ名前の物: results＝結果のファイル（もう取り込んである＝取り込まない）・project＝元のプロジェクト（使い回すか作り直す）・
    stems＝分けた音（使い回す）"""
    out, cache = Path(ctx.OUT), Path(ctx.CACHE)
    res = sorted(p.name for p in out.glob('*.nlmf') if p.name.split('.')[0].lower() == name.lower() and p.name.lower() != f'{name}.nlmf'.lower())
    proj = out / f'{name}.nlmf'
    pinfo = None
    if proj.exists():
        try:
            d = json.loads(proj.read_bytes().decode('utf-8-sig'))
            song = (d.get('graph') or {}).get('song') or {}
            pinfo = {'file': proj.name, 'bpm': d.get('bpm'), 'lead': round(-(song.get('offset') or 0) * 1000), 'song': song.get('name') or '',
                     'markers': len(d.get('markers') or [])}
        except (OSError, ValueError):
            pinfo = {'file': proj.name, 'bpm': None, 'lead': None, 'song': '', 'markers': 0, 'bad': True}
    sinfo = None
    sp = cache / name / 'separate.json'
    if sp.exists():
        try:
            d = json.loads(sp.read_text(encoding='utf-8'))
            sinfo = {'source': d.get('source') or '', 'seconds': d.get('seconds'), 'model': d.get('model') or ''}
        except (OSError, ValueError):
            sinfo = None
    return {'name': name, 'results': res, 'project': pinfo, 'stems': sinfo, 'blocked': bool(res)}


def running_import(ctx):
    return next((j for j in ctx.JOBS.values() if j.get('kind') == KIND and j['state'] == 'running'), None)


# ---- 作業の中身 ----

def _collapse(text):
    """進み具合の棒（\\r で同じ行を書き直す）は、行ごとに最後の物だけ残す"""
    out = []
    for ln in text.split('\n'):
        if '\r' in ln:
            segs = [s for s in ln.split('\r') if s.strip()]
            ln = segs[-1] if segs else ''
        out.append(ln)
    return '\n'.join(out)


def run_cmd(job, cmd, env=None, out=None):
    """コマンドを別のプロセスで動かし、出力を少しずつ job['log'] へ（行の途中の進み具合の棒も出す）。やめる（job['cancel']）と止める。
    env＝環境変数の全部（音を分ける部品＝setup.sep_runner・無ければ今のまま）。
    out＝記録とプロセスを置く所（裏で動かす段＝_side_start の side・無ければ job）。out['stop'] でも止める"""
    out = job if out is None else out
    env = dict(env if env is not None else os.environ, PYTHONIOENCODING='utf-8')
    out['log'] += '$ ' + ' '.join(Path(str(c)).name if i == 0 else str(c) for i, c in enumerate(cmd)) + '\n'
    pr = subprocess.Popen([str(c) for c in cmd], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, creationflags=NO_WINDOW)
    out['proc'] = pr
    if job.get('cancel') or out.get('stop'):   # 始める前にやめていた（止める側がまだプロセスを知らなかった）
        pr.kill()
    dec = codecs.getincrementaldecoder('utf-8')('replace')
    try:
        while True:
            chunk = pr.stdout.read1(4096)
            if not chunk:
                break
            out['log'] = _collapse(out['log'] + dec.decode(chunk))
        out['log'] = _collapse(out['log'] + dec.decode(b'', final=True))
        pr.wait()
    finally:
        out.pop('proc', None)
    if job.get('cancel') or out.get('stop'):
        raise RuntimeError('やめた')
    if pr.returncode:
        raise RuntimeError(f'失敗した（終了コード {pr.returncode}）')


def _say(job, text):
    job['log'] += text.rstrip('\n') + '\n'


# ---- 裏で動かす段（2026-11-11 利用者「音を分ける以外は緩い・並列で速く」） ----
# 曲の解析は元の音源だけを読む（分けた音を使わない）ので、音を分ける（GPU）と同時に別のプロセスで動かす（桃源郷で取り込みの全部が
# 142 → 91 秒・解析の答えは同じ）。裏の記録は side['log'] に貯め、その段に入った時に job['log'] へ写す（記録の並びは前と同じ）。
# 画面へは job['bg']（段の名前 → running・done・error・stopped）＝同時に動いている段にも印を付ける（importer.js の stepsHTML）。

def _side_start(job, label, fn):
    """fn(side) を裏の流れで始める → side（log・done＝終わった印・err・kill()）。やめる（job['_on_cancel']）で止まる"""
    side = {'log': '', 'done': threading.Event(), 'err': None, 'label': label}

    def kill():
        side['stop'] = True
        pr = side.get('proc')
        if pr is not None:
            try:
                pr.kill()
            except OSError:
                pass
    side['kill'] = kill
    job['_side'] = side
    job['bg'] = {label: 'running'}   # 丸ごと置き換える（画面へ返す途中に項目の数が変わらない）
    job.setdefault('_on_cancel', []).append(kill)

    def run():
        try:
            fn(side)
        except BaseException as e:   # noqa: BLE001  （待つ段が受け取って出す）
            side['err'] = e
        finally:
            job['bg'][label] = 'stopped' if side.get('stop') else 'error' if side['err'] else 'done'
            side['done'].set()
    threading.Thread(target=run, daemon=True).start()
    return side


class _Warm:
    """曲のデータ（/api/song）の重い所＝分けた音の大きさの線と拍ごとの特徴（songdata.prepare）を、最初の譜面の compose と同時に
    サーバーの中で作り（onsets.json は compose が書くのを待つ）、compose の後に曲のデータを作って覚える（server.song_data＝メモリと
    ディスクの控え）＝取り込みの後に曲を開く時の待ち 5 秒ほどが無くなる（2026-11-11）。作れなくても取り込みは止めない（開く時に作る）"""

    def __init__(self, ctx, proj, stems):
        self.ctx, self.stop, self.err = ctx, threading.Event(), None
        self.th = threading.Thread(target=self._run, args=(proj, stems), daemon=True)
        self.th.start()

    def _run(self, proj, stems):
        try:
            self.ctx.songdata.prepare(proj, stems, self.stop)
        except Exception as e:   # noqa: BLE001
            self.err = e

    def finish(self, job, res):
        t0 = time.time()
        self.th.join()
        try:
            self.ctx.song_data(res)
            _say(job, f'曲のデータを用意した（{time.time() - t0:.1f} 秒）')
        except Exception as e:   # noqa: BLE001
            _say(job, f'（曲のデータは開く時に作る: {type(e).__name__}: {e}）')


def _side_wait(job):
    """裏で動かした段の終わりを待ち、記録を job['log'] へ写す。失敗していればその失敗を出す。やめる（job['cancel']）と止めて待つ"""
    side = job['_side']
    while not side['done'].wait(0.2):
        if job.get('cancel'):
            side['kill']()
    job['log'] += side['log']
    if job.get('cancel'):
        raise RuntimeError('やめた')
    if side['err'] is not None:
        raise side['err']


def plan(ctx, audio, name, title, artist, bpm=None, lead=None, cover=None, remake=False, info=None, wait=False):
    """取り込みの段 [(説明, fn(job))]。分けた音・元のプロジェクトがあれば使い回す（remake＝元のプロジェクトを作り直す）。
    wait＝最初の譜面の前に「基本設定を待つ」の段を入れる（画面からの取り込み）"""
    out, cache = Path(ctx.OUT), Path(ctx.CACHE)
    stems, proj = cache / name, out / f'{name}.nlmf'
    res = out / f'{name}.{ctx.APP_KIND}.nlmf'
    ana = stems / 'analysis.json'
    info = info or NP.audio_info(audio)
    make_proj = remake or not proj.exists()
    src0 = audio
    # NLM が開いただけでは読めない場所（\\NAS\… 等）の音源は、最初の段で分けた音のフォルダの source/ へ写して、その写しを使う
    # （元のプロジェクトの音源の場所もその写し・new_project.local_audio・2026-11-03 利用者・案 A）
    copy = make_proj and not NP.nlm_readable(Path(audio).absolute())
    if copy:
        audio = stems / NP.SOURCE_DIR / Path(audio).name

    def to_local(job):
        NP.local_audio(src0, stems, log=lambda s: _say(job, s))

    def analyze_cmd():
        cmd = [sys.executable, '-m', 'automap.analyze_song', audio, '--json', ana]
        if bpm is not None:
            cmd += ['--bpm', bpm]
        if lead is not None:
            cmd += ['--lead-ms', lead]
        return cmd

    def separate(job):
        if make_proj and '_side' not in job:   # 曲の解析を裏で始める（元の音源だけを読む＝分けた音を待たない）
            stems.mkdir(parents=True, exist_ok=True)

            def side_analyze(side):
                _say(side, '（音を分けるのと同時に進めた）')
                run_cmd(job, analyze_cmd(), out=side)
            _side_start(job, '曲の解析', side_analyze)
        try:
            _separate(job)
        except BaseException:
            if job.get('_side'):   # 音を分けられなかった・やめた＝裏の解析も止める（取り込みは終わる）
                job['_side']['kill']()
            raise

    def _separate(job):
        if (stems / 'separate.json').exists():
            return _say(job, f'分けた音がもうある（使い回す）: {stems.name}')
        import setup   # noqa: E402  （app/ の中）
        sep_py, sep_env, variant = setup.sep_runner(ctx)
        src, tmp = Path(audio), None
        if not info.get('soundfile'):   # soundfile で読めない形式（m4a 等）は ffmpeg で FLAC にしてから分ける
            ff = shutil.which('ffmpeg')
            if not ff:
                raise RuntimeError(f'{src.suffix} は ffmpeg が無いと読めない（flac・wav・mp3・ogg にする）')
            tmp = Path(tempfile.mkdtemp(prefix='automap-import-'))
            src = tmp / (Path(audio).stem + '.flac')
            run_cmd(job, [ff, '-nostdin', '-y', '-v', 'error', '-i', audio, '-vn', '-c:a', 'flac', src])
        try:
            # CPU だけの PC は少し軽く（ずらして平均する回数 1＝4 分の曲で約 5 分・GPU は今のまま 2）
            run_cmd(job, [sep_py, ROOT / 'tools' / 'separate.py', src, '--out', stems] + (['--shifts', '1'] if variant == 'cpu' else []),
                    env=sep_env)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    def analyze(job):
        if not make_proj:
            return _say(job, f'元のプロジェクトがもうある（その解析を使い回す）: {proj.name}')
        if job.get('_side'):   # 音を分ける段で裏に始めた物を待つ
            return _side_wait(job)
        stems.mkdir(parents=True, exist_ok=True)
        run_cmd(job, analyze_cmd())

    def project(job):
        if not make_proj:
            return _say(job, f'元のプロジェクトを使い回す: {proj.name}')
        if proj.exists():   # 作り直す: 前の元のプロジェクトの控え（元の .nlmf は書き換えない約束＝消さずに残す）
            bk = out / 'old' / f'{name}.{time.strftime("%Y%m%d-%H%M%S")}.nlmf'
            bk.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(proj, bk)
            _say(job, f'前の元のプロジェクトの控え: old/{bk.name}')
        NP.make(audio, proj, ana, title=title, artist=artist, cover=cover, log=lambda s: _say(job, s))

    def compose(job):
        cmd = [sys.executable, '-m', 'automap', 'compose', proj, '--stems', stems, '--form', '--style', '--out', res]
        with _SET_LOCK:   # ここから先は基本設定を変えられない（待つ段が無い時も）
            job['settings_locked'] = True
            st = job.get('settings')
        lib = put_library(ctx, res, job, st.get('library')) if st is not None else new_library(ctx, res, job)
        if lib:   # 型のデータベースの絞り込み（app/library.py の compose_extra と同じ渡し方）
            cmd += ['--library', json.dumps(lib, ensure_ascii=False, separators=(',', ':'))]
        warm = _Warm(ctx, proj, stems)   # 曲のデータの重い所を、最初の譜面を作っている間に先に（取り込みの後に開くのを待たせない）
        try:
            run_cmd(job, cmd)
        finally:
            warm.stop.set()
        warm.finish(job, res)

    def put_cover(job):   # 元のプロジェクトを使い回した時は、カバー画像を結果のファイルに入れる（元は書き換えない）
        p = ctx.nlmf.load(res)
        dst = NP.set_cover(p, res, cover, stem=name)
        ctx.cli._save(p, res)   # 書いた時の指紋も残す（次の作り直しで「NLM で直した」と取り違えない）
        _say(job, f'カバー画像: {dst.name}')

    steps = ([('音源を手元に写す', to_local)] if copy else []) + [('音を分ける', separate), ('曲の解析', analyze), ('元のプロジェクトを作る', project)]
    if wait:
        steps.append((WAIT_LABEL, wait_for_settings))
    steps.append(('最初の譜面を作る', compose))
    if cover and not make_proj:
        steps.append(('カバー画像を入れる', put_cover))
    return [(label, _stoppable(fn)) for label, fn in steps]


def wait_for_settings(job, poll=None):
    """基本設定（job['settings']）が届くまで待つ。届いていればすぐ抜ける。やめる（job['cancel']）で止まる。
    待つ間は段が「基本設定を待つ」のまま（/api/job で画面に分かる）。サーバーが止まって届かないまま待つのは構わない（やめるで止まる）"""
    said = False
    while True:
        with _SET_LOCK:
            st = job.get('settings')
            if st is not None:
                job['settings_locked'] = True   # 抜けたら決め直せない（受け口が断る）
                break
        if job.get('cancel'):
            raise RuntimeError('やめた')
        if not said:
            _say(job, '基本設定（型のライブラリ）を待っている（取り込みの窓で「この設定で作る」）')
            said = True
        time.sleep(WAIT_POLL if poll is None else poll)
    _say(job, f'基本設定: 型のライブラリ {LU.label(st.get("library"))}')


def _lib_text(ctx, res, f):
    """記録に書く型のライブラリの説明（時期が自動なら、この曲の時期も＝compose が置き換える物と同じ）"""
    if f and f.get('years') == LU.AUTO:
        try:
            import library as AL   # noqa: E402  （app/ の中・曲ごとの時期）
            return LU.label(AL.auto_view(f, ctx.song_of(Path(res)))[2])
        except Exception:   # noqa: BLE001  （説明だけ＝数えられなくても止めない）
            pass
    return LU.label(f)


def settings_of(lib, song=None):
    """画面から来た基本設定 → job['settings']（library＝絞り込み（None＝新しい曲の既定）・説明・受けた時刻）。song＝取り込む曲の名前
    （時期が自動なら説明にその曲の時期を入れる。library は自動のまま＝compose が置き換える）"""
    f = LU.normalize(lib)
    shown = f
    if song and f.get('years') == LU.AUTO:
        try:
            import library as AL   # noqa: E402  （app/ の中・曲ごとの時期）
            shown = AL.auto_view(f, song)[2]
        except Exception:   # noqa: BLE001  （説明だけ）
            shown = f
    return {'library': f, 'label': LU.label(shown), 'short': LU.label(shown, True), 'at': round(time.time(), 1)}


def put_library(ctx, res, job, lib):
    """基本設定で決めた型のライブラリを作業ファイルの library に入れる（作業ファイルがもうあっても基本設定が勝つ。None＝新しい曲の既定）
    → 絞り込み。データベースが使えない PC でも決めた物を入れる（最初の譜面は compose が「型のデータベースが使えない（理由）」で止まる）"""
    f = LU.normalize(lib)
    wp = ctx.work_path(res)
    w = json.loads(wp.read_text(encoding='utf-8')) if wp.exists() else ctx.default_work(res)
    w['library'] = f
    ctx.save_work(res, w)
    ok, err, _ = LU.available()
    if not ok:
        _say(job, f'型のデータベースが使えない（{err}）＝最初の譜面は作れない（「準備と設定」で型のライブラリを確かめる）')
    _say(job, f'型のライブラリ: {_lib_text(ctx, res, f)}（基本設定で決めた物。後で画面の「ライブラリ」で変えられる）')
    return f


def new_library(ctx, res, job):
    """新しい曲の型のライブラリ（docs/ライブラリ仕様.md 4 節・2026-10-26 利用者「新しい曲からデータベース」）: 作業ファイルが無ければ
    automap/library_use.DEFAULT（ランク譜面・時期は曲ごとに自動・★〜8）入りで作る。作業ファイルがもうあれば、その library のまま
    （無ければ新しい曲の既定）→ 絞り込み。基本設定の段が無い取り込み（plan(wait=False)）で、基本設定も届いていない時だけ使う"""
    wp = ctx.work_path(res)
    if wp.exists():
        lib = LU.normalize(json.loads(wp.read_text(encoding='utf-8')).get('library'))
        _say(job, f'型のライブラリ: {LU.label(lib)}（作業ファイルの設定のまま）')
        return lib
    ok, err, _ = LU.available()
    if not ok:
        _say(job, f'型のデータベースが使えない（{err}）＝最初の譜面は作れない（「準備と設定」で型のライブラリを確かめる）')
    w = ctx.default_work(res)
    w['library'] = dict(LU.DEFAULT)
    ctx.save_work(res, w)
    _say(job, f'型のライブラリ: {_lib_text(ctx, res, w["library"])}（新しい曲の既定。画面の「ライブラリ」で変えられる）')
    return w['library']


def _stoppable(fn):
    """やめる（job['cancel']）と、次の段に入らずに止める"""
    def w(job):
        if job.get('cancel'):
            raise RuntimeError('やめた')
        fn(job)
    return w


# ---- 受け口 ----

def _num(v, lo, hi, what, digits=None):
    if v in (None, ''):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{what} は数で入れる（空なら自動）')
    if not lo <= x <= hi:
        raise ValueError(f'{what} は {lo:g}〜{hi:g}（空なら自動）')
    return round(x, digits) if digits else int(round(x))


def _guard(fn):
    """受け答えの中の思わぬ失敗も 400（server は ValueError・FileNotFoundError・KeyError だけを 400 にする）"""
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

    def pick(b):
        kind = 'image' if b.get('kind') == 'image' else 'audio'
        if not _PICK_LOCK.acquire(blocking=False):
            raise ValueError('ファイルを選ぶ窓がもう開いている（タスクバーを見る）')
        try:
            p = PICKER(kind, _LAST_DIR.get(kind) or _LAST_DIR.get('audio'))
        finally:
            _PICK_LOCK.release()
        if p:
            _LAST_DIR[kind] = str(Path(p).parent)
            if kind == 'image':
                if Path(p).suffix.lower() not in NP.IMAGE_EXTS:
                    raise ValueError('カバー画像は jpg・png')
                _SEEN.add(str(Path(p)))
        return {'path': p}

    def probe(b):
        p = clean_path(b.get('path'))
        if not p.is_file():
            raise FileNotFoundError(f'そのファイルは無い: {p}')
        if p.suffix.lower() not in NP.AUDIO_EXTS:
            raise ValueError(f'音源のファイルを選ぶ（{"・".join(e[1:] for e in NP.AUDIO_EXTS)}）')
        p = p.resolve()
        info = NP.audio_info(p)
        if not info['seconds']:
            raise ValueError('音源を読めない（形式が違うか壊れている。m4a 等は ffmpeg が要る）')
        if not info['soundfile'] and not shutil.which('ffmpeg'):
            raise ValueError(f'{p.suffix} は ffmpeg が無いと読めない（flac・wav・mp3・ogg にする）')
        _LAST_DIR['audio'] = str(p.parent)
        covers = NP.cover_candidates(p)
        _SEEN.update(covers)
        name = NP.safe_name(info['title'] or p.stem)
        return {'path': str(p), 'file': p.name, 'title': info['title'] or p.stem, 'artist': info['artist'], 'tagged': bool(info['title']),
                'seconds': info['seconds'], 'sr': info['sr'], 'channels': info['channels'], 'format': info['format'],
                'ffmpeg': not info['soundfile'], 'covers': covers, 'name': name, 'exists': conflicts(ctx, name)}

    def check(b):
        name = NP.safe_name(b.get('name'))
        return conflicts(ctx, name)

    def cover(q):
        p = str(Path(q.get('path') or ''))
        if p not in _SEEN or not Path(p).is_file():
            raise FileNotFoundError('その画像は出せない')
        return Path(p)

    def start(b):
        audio = clean_path(b.get('path')).resolve()
        if not audio.is_file():
            raise FileNotFoundError(f'そのファイルは無い: {audio}')
        name = NP.safe_name(b.get('name') or audio.stem)
        c = conflicts(ctx, name)
        if c['blocked']:
            raise ValueError(f'「{name}」はもう取り込んである（{"・".join(c["results"])}）。名前を変えるか、一覧から開く')
        if running_import(ctx):
            raise ValueError('ほかの曲を取り込んでいる（終わってから）')
        if ctx.busy(f'{name}.{ctx.APP_KIND}.nlmf'):
            raise ValueError('この曲は今作り直している')
        title = str(b.get('title') or '').strip()[:200] or audio.stem
        artist = str(b.get('artist') or '').strip()[:200]
        bpm = _num(b.get('bpm'), 30, 400, 'BPM', 2)
        lead = _num(b.get('lead'), 0, 10000, '無音追加（ms）')
        remake = bool(b.get('remake'))
        if c['project'] and not remake and (bpm is not None or lead is not None):
            raise ValueError('元のプロジェクトがもうある。BPM・無音追加を変えるなら「元のプロジェクトを作り直す」に')
        cov = b.get('cover') or None
        if cov:
            cov = str(Path(cov))
            if cov not in _SEEN or not Path(cov).is_file():
                raise ValueError('カバー画像は候補か「別の画像」で選んだ物')
        info = NP.audio_info(audio)
        steps = plan(ctx, audio, name, title, artist, bpm, lead, cov, remake, info, wait=True)
        meta = {'settings': settings_of(b['library'], name)} if 'library' in b else {}   # 始める時に基本設定を渡してもよい（待つ段をすぐ抜ける）
        res = Path(ctx.OUT) / f'{name}.{ctx.APP_KIND}.nlmf'

        def done(job):
            rp = res.with_name(res.name[:-len('.nlmf')] + '.report.md')
            if job['state'] == 'done' and rp.exists():
                job['report'] = rp.read_text(encoding='utf-8')

        j = ctx.start_job(res.name, steps, kind=KIND, after=done, song=name, title=title, audio=str(audio), **meta)
        return {'id': j['id'], 'song': name}

    def settings(b):
        """POST /api/import/settings {id, library（null＝新しい曲の既定）}: 基本設定を覚える。最初の譜面の段が始まるまでは何度でも決め直せる"""
        j = ctx.JOBS.get(b.get('id'))
        if not j or j.get('kind') != KIND:
            raise KeyError('その取り込みは無い（サーバーを起動し直した？）')
        if 'library' not in b:
            raise ValueError('library が要る（null＝新しい曲の既定）')
        st = settings_of(b.get('library'), j.get('song'))
        with _SET_LOCK:
            if j['state'] != 'running':
                raise ValueError('その取り込みはもう終わった')
            if j.get('settings_locked'):
                raise ValueError('もう最初の譜面を作り始めたので基本設定は変えられない（できた後で上の「ライブラリ」の窓で変えて作り直す）')
            j['settings'] = st
        return {'ok': True, 'settings': st}

    def cancel(b):
        j = ctx.JOBS.get(b.get('id'))
        if not j or j.get('kind') != KIND:
            raise KeyError('その取り込みは無い')
        if j['state'] == 'running':
            j['cancel'] = True
            pr = j.get('proc')
            if pr:
                pr.kill()
            for fn in list(j.get('_on_cancel') or []):   # 裏で動かしている段（曲の解析）も止める
                fn()
        return {'ok': True}

    return ({'/api/import/cover': _guard(cover)},
            {'/api/import/pick': _guard(pick), '/api/import/paste': _guard(lambda b: {'path': str(save_pasted(b.get('data')))}),
             '/api/import/probe': _guard(probe), '/api/import/check': _guard(check),
             '/api/import/start': _guard(start), '/api/import/settings': _guard(settings), '/api/import/cancel': _guard(cancel)})
