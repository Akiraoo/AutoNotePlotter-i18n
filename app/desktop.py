"""譜面づくりのアプリを自分用の窓で開く（docs/アプリ仕様.md 8 節の7・9 節「exe はまず自分用」・2026-10-26）。

使い方: ダブルクリックで app/譜面づくり.bat（＝.venv/Scripts/pythonw.exe app/desktop.py。黒い窓は一瞬だけ）か、
  `.venv/Scripts/python.exe app/desktop.py --shortcut [フォルダ]` で作るショートカット（既定はデスクトップ・黒い窓は出ない）。
  引数: [--port 8765] [--out 場所] [--cache 場所] [--debug]（--debug＝開発者ツール・右クリックの「検証」）
  [--data-dir 場所]（確かめ用: 窓の覚え・WebView2 の作業の場所・記録の置き場を替える＝環境変数 AUTOMAP_DESKTOP_DIR と同じ）。
  要る物: .venv に pywebview（`.venv/Scripts/python.exe -m pip install pywebview`）と WebView2（Windows 11 は入っている）。

- サーバー（app/server.py の make_server）を同じプロセスの中で動かし、pywebview の窓（WebView2＝Edge）でアプリの画面を開く。
  ブラウザで使うやり方（app/start.bat）はそのまま。
- 起動の表示（2026-11-09 利用者「起動がすごく時間がかかる時とサクッと起動する時がある・スプラッシュを」）: サーバーの部品（numpy・scipy・
  曲の解析）を読む前に窓を出し、起動の表示（SPLASH_HTML＝今の段・経過の秒・遅い時の訳）を見せる。部品の読み込み → サーバー → 画面の
  読み込み（load_url）は裏の流れ（_boot）。失敗したら窓に「起動できませんでした」と訳・記録の場所を出す（×ですぐ閉じる）。
  遅い時の訳: 初めての起動・PC を起動し直した直後・更新の後は、部品のファイル（.pyd・DLL が 120 ほど）が読み込みの控えに無く、ウイルス対策
  ソフトも検査するので、部品の読み込みが 1 秒 → 10〜30 秒になる。段ごとの秒は記録（desktop.log）の「起動の段」に出す。
  2026-11-09 から、サーバーは重い部品（numpy・scipy・作る処理）を使う時まで読まない（automap/lazy.py・起動で読むのは .pyd・DLL 20 足らず
  （18MB・Python 本体を含む）・モジュール 160 ほど＝前は 130（122MB）・950）。曲のデータはディスクの控え（app/songcache.py）から読むので、重い部品を読むのは控えの無い曲を開いた時・
  作り直しの前の比べ等だけ。
- 最後に開いていた曲（作業ファイルを一番後に保存した曲）の曲のデータ（/api/song・控えがあれば 0.05 秒・無ければ 3〜5 秒）は、サーバーが
  待ち始めたらすぐ裏で作る（画面の読み込みと重ねる・_prewarm）。同じ曲を画面も同時に頼んだら、先に作っている物を待つ（song_data を二重に作らない）。
- 番号は 8765。使われていたら（ブラウザで使うサーバー・もう1つの窓）空いている番号に。画面の覚え（localStorage＝最後の曲・表示の
  大きさ・欄の幅）は番号ごとなので、別の番号の時は覚えも別。覚え・WebView2 の作業の場所・記録・アイコンは <LOCALAPPDATA>/automap-app/。
- 窓を閉じる（×）: 作り直し・取り込みの途中なら確かめる → 画面の作業ファイルを保存（store.saveWork を呼び、サーバーに届いたことを
  確かめる＝beforeunload 頼みにしない。届かなければ確かめる）→ サーバーを止める → 窓を閉じる。
  画面の「終わる」・app/stop.bat（/api/shutdown）でサーバーが止まった時も窓を閉じる。
- 曲の取り込みの「選ぶ…」は窓のファイルの窓（importer.use_window_picker）。
- pythonw（黒い窓なし）で動く時は print の出し先が無いので、記録は <LOCALAPPDATA>/automap-app/desktop.log へ。作り直し・取り込みの
  別のプロセスは同じ場所の python.exe で動かす（server・importer は CREATE_NO_WINDOW で起動するので黒い窓は出ない）。
- 確かめ用: --selftest（開く → 曲が開く・3D・音・キー・ファイルの窓 → ×と同じ閉じ方で閉じる、を自動で。結果は --selftest-result の
  JSON）・--selftest-generate（作り直しも。本物の out/ では断る＝--out に写しの場所）・--selftest-quit（×ではなく画面の「終わる」で閉じる）。
  NLM_EXE に害の無い物（例: pythonw.exe）を入れておくと「NLM で開く」の口も確かめる（本物の NLM は起動しない）。
"""
import argparse
import base64
import ctypes
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
TITLE = 'Auto Note Plotter'
SHORTCUT_NAME = 'Auto Note Plotter'
KIND_TEXT = {'generate': '作り直し', 'import': '曲の取り込み', 'cand': '別の案づくり', 'cands': '別の案づくり', 'setup': '音を分ける部品のインストール',
             'move': '作業フォルダの引っ越し', 'bsexport': 'Beat Saber への書き出し', 'update': 'アプリの更新のダウンロード'}
ORIG_EXE = sys.executable
DIR_ENV = 'AUTOMAP_DESKTOP_DIR'   # 確かめ用: 覚え・WebView2 の作業の場所・記録の置き場を替える（--data-dir）
LOG_FILE = None   # 記録のファイル（pythonw の時・quiet_streams）。python.exe の時は None（記録は黒い窓に出る）


def _proc_started():
    """このプロセスが始まった時刻（ダブルクリックからの秒を記録に出す）。取れなければ今"""
    try:
        k = ctypes.WinDLL('kernel32')   # 自分の関数の型を決める（ctypes.windll の共有の物を変えない）
        k.GetCurrentProcess.restype = ctypes.c_void_p
        t = [ctypes.c_ulonglong() for _ in range(4)]
        if k.GetProcessTimes(ctypes.c_void_p(k.GetCurrentProcess()), *(ctypes.byref(x) for x in t)):
            return t[0].value / 1e7 - 11644473600   # FILETIME（1601 年からの 100ns）→ UNIX の秒
    except Exception:   # noqa: BLE001
        pass
    return time.time()


T_PROC = _proc_started()


def since():
    """プロセスが始まってからの秒"""
    return time.time() - T_PROC


def data_dir():
    """覚え・WebView2 の作業の場所・記録・アイコンの置き場（この PC のユーザーごと・確かめは AUTOMAP_DESKTOP_DIR）"""
    if os.environ.get(DIR_ENV):
        d = Path(os.environ[DIR_ENV])
    else:
        base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        d = Path(base) / 'automap-app'
    d.mkdir(parents=True, exist_ok=True)
    return d


def log(msg):
    try:
        print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)
    except Exception:   # noqa: BLE001
        pass


def quiet_streams():
    """pythonw では sys.stdout・sys.stderr が無い（print は消え、sys.stderr.write は落ちる）→ 記録のファイルへ"""
    global LOG_FILE
    if sys.stdout is not None and sys.stderr is not None:
        return
    p = data_dir() / 'desktop.log'
    try:
        if p.exists() and p.stat().st_size > (1 << 20):
            p.replace(p.with_name('desktop.old.log'))
        f = open(p, 'a', encoding='utf-8', buffering=1)
        LOG_FILE = p
    except OSError:
        f = open(os.devnull, 'w', encoding='utf-8')
    f.write(f'\n==== {time.strftime("%Y-%m-%d %H:%M:%S")} 起動（プロセスが始まってから {since():.1f} 秒）\n')
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f


def console_python():
    """pythonw で動いている時、別のプロセス（compose・解析）は同じ場所の python.exe で（出力をパイプで受け取る。
    server・importer は CREATE_NO_WINDOW で起動するので黒い窓は出ない）"""
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').exists():
        sys.executable = str(exe.with_name('python.exe'))


def pythonw():
    """ショートカット・bat が起動する pythonw（repo の .venv の物。無ければ今の Python の隣）"""
    for p in (ROOT / '.venv' / 'Scripts' / 'pythonw.exe', Path(ORIG_EXE).with_name('pythonw.exe')):
        if p.exists():
            return p
    return Path(ORIG_EXE)


# ---- 番号 ----

class ExclusiveServer(ThreadingHTTPServer):
    """同じ番号をほかと分け合わない（Windows は SO_REUSEADDR だと使われている番号でも待ててしまい、要求がどちらに届くか分からない）"""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def in_use(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', port)) == 0


def free_port(want):
    """want が空いていればそこ・使われていれば次の番号（19 先まで）・それも無ければ OS に選ばせる"""
    for p in [want, *range(want + 1, want + 20)]:
        if in_use(p):
            continue
        try:
            with socket.socket() as s:
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                s.bind(('127.0.0.1', p))
            return p
        except OSError:
            continue
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


# ---- アイコン（コードで描く＝絵のファイルを repo に置かない） ----

ICON_VER = 1


def _icon_rgba(n):
    """n×n の RGBA（上の行から）: 暗い角丸の地に、赤（↓）と青（↑）のノーツ"""
    ss = 4
    out = bytearray()

    def rrect(x, y, x0, y0, x1, y1, r):
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx, cy = min(max(x, x0 + r), x1 - r), min(max(y, y0 + r), y1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def tri(x, y, ax, ay, bx, by, cx, cy):
        d1 = (x - bx) * (ay - by) - (ax - bx) * (y - by)
        d2 = (x - cx) * (by - cy) - (bx - cx) * (y - cy)
        d3 = (x - ax) * (cy - ay) - (cx - ax) * (y - ay)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))

    bg, red, blue, white = (32, 34, 46), (226, 54, 60), (44, 124, 232), (255, 255, 255)
    for py in range(n):
        for px in range(n):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    x, y = (px + (sx + .5) / ss) / n, (py + (sy + .5) / ss) / n
                    col = None
                    if rrect(x, y, 0.02, 0.02, 0.98, 0.98, 0.2):
                        col = bg
                        if rrect(x, y, 0.10, 0.36, 0.48, 0.74, 0.07):      # 赤のノーツ（左下）
                            col = white if tri(x, y, 0.17, 0.45, 0.41, 0.45, 0.29, 0.60) else red
                        elif rrect(x, y, 0.52, 0.18, 0.90, 0.56, 0.07):    # 青のノーツ（右上）
                            col = white if tri(x, y, 0.59, 0.47, 0.83, 0.47, 0.71, 0.32) else blue
                    if col:
                        acc[0] += col[0]
                        acc[1] += col[1]
                        acc[2] += col[2]
                        acc[3] += 255
            k = ss * ss
            a = acc[3] / k
            if a:
                out += bytes((round(acc[0] / (acc[3] / 255)), round(acc[1] / (acc[3] / 255)), round(acc[2] / (acc[3] / 255)), round(a)))
            else:
                out += b'\0\0\0\0'
    return bytes(out)


def _ico_bytes(sizes=(16, 24, 32, 48, 64, 128)):
    """ICO（32bit の BMP の並び。.NET の Icon でも読める形）"""
    images = []
    for n in sizes:
        rgba = _icon_rgba(n)
        rows = [rgba[y * n * 4:(y + 1) * n * 4] for y in range(n)]
        xor = b''.join(bytes(b for i in range(0, len(r), 4) for b in (r[i + 2], r[i + 1], r[i], r[i + 3])) for r in reversed(rows))
        mask = b'\0' * (((n + 31) // 32) * 4 * n)
        head = struct.pack('<IiiHHIIiiII', 40, n, n * 2, 1, 32, 0, len(xor) + len(mask), 0, 0, 0, 0)
        images.append((n, head + xor + mask))
    off = 6 + 16 * len(images)
    out = struct.pack('<HHH', 0, 1, len(images))
    for n, data in images:
        out += struct.pack('<BBBBHHII', n % 256, n % 256, 0, 0, 1, 32, len(data), off)
        off += len(data)
    return out + b''.join(d for _, d in images)


def icon_path():
    p = data_dir() / f'automap-{ICON_VER}.ico'
    if not p.exists():
        try:
            p.write_bytes(_ico_bytes())
        except OSError:
            return None
    return p


# ---- ショートカット ----

def make_shortcut(folder=None):
    """ダブルクリックで窓のアプリを開くショートカット（pythonw で desktop.py・黒い窓なし）を作る。既定はデスクトップ"""
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    ico = icon_path()
    ps = '\n'.join([
        '$ErrorActionPreference = "Stop"',
        '[Console]::OutputEncoding = [Text.Encoding]::UTF8',
        f'$d = {q(folder)}' if folder else '$d = [Environment]::GetFolderPath("Desktop")',
        f'$p = Join-Path $d {q(SHORTCUT_NAME + ".lnk")}',
        '$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p)',
        f'$s.TargetPath = {q(pythonw())}',
        f'$s.Arguments = {q(chr(34) + str(APP_DIR / "desktop.py") + chr(34))}',
        f'$s.WorkingDirectory = {q(ROOT)}',
        f'$s.Description = {q("Auto Note Plotter（Beat Saber の譜面を自動で作る）を窓で開く")}',
        (f'$s.IconLocation = {q(str(ico) + ",0")}' if ico else ''),
        '$s.Save()',
        'Write-Output $p',
    ])
    enc = base64.b64encode(ps.encode('utf-16-le')).decode('ascii')
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', enc], capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    text = (r.stdout or b'').decode('utf-8', 'replace').strip()
    if r.returncode:
        raise SystemExit('ショートカットを作れなかった: ' + (r.stderr or b'').decode('cp932', 'replace')[-400:])
    return text


def alert(msg):
    """窓を出す前の失敗を知らせる（pythonw では print が見えない）"""
    log(msg)
    try:
        ctypes.windll.user32.MessageBoxW(None, str(msg), TITLE, 0x10)
    except Exception:   # noqa: BLE001
        pass


def close_dialog(t, timeout=10.0):
    """確かめ用: このプロセスの見えているダイアログ（クラス #32770＝ファイルの窓・MessageBox）を探し、見つけたら閉じる（WM_CLOSE）。
    t＝ダイアログを出している流れ（終わったら探すのをやめる）→ [(hwnd, 題)]"""
    u = ctypes.windll.user32
    found, pid = [], os.getpid()
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(h, _):
        p = ctypes.c_ulong()
        u.GetWindowThreadProcessId(ctypes.c_void_p(h), ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(ctypes.c_void_p(h)):
            buf = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(ctypes.c_void_p(h), buf, 64)
            if buf.value == '#32770':
                tb = ctypes.create_unicode_buffer(200)
                u.GetWindowTextW(ctypes.c_void_p(h), tb, 200)
                found.append((h, tb.value))
        return True
    cb = EnumProc(each)
    t0 = time.time()
    while time.time() - t0 < timeout and not found and t.is_alive():
        time.sleep(0.3)
        u.EnumWindows(cb, 0)
    if found:
        time.sleep(0.5)
        u.PostMessageW(ctypes.c_void_p(found[0][0]), 0x0010, 0, 0)
    return found


def automap_running(port):
    """その番号でこのアプリ（app/server.py か窓のアプリ）が動いているか（画面の入口 / は合言葉なしで答える＝server.py の出入りの守り）"""
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1.5) as r:
            return (r.headers.get('Server') or '').startswith('automap/')
    except Exception:   # noqa: BLE001
        return False


# ---- 窓のアプリ ----

# 画面の起動の様子（_watch_open）: [状態欄の字, 起動の段（index.html の起動の見張り window.anpBoot）, 部品を読めなかった訳, その段になってからの ms]
BOOT_JS = ("(function () { var b = window.anpBoot || {}; return [(document.getElementById('status') || {}).textContent || '', "
           "b.stage || '', b.why || '', b.at ? Date.now() - b.at : 0]; })()")
BOOT_STUCK = 60   # 画面の起動が同じ段のままこの秒数たったら 1 回読み込み直す（初めての曲のデータは 10〜30 秒かかることがある）

SAVE_JS = r"""(function () {
  window.__automapSave = 'wait';
  try { document.querySelectorAll('audio').forEach(function (a) { a.pause(); }); } catch (e) {}
  import('/static/js/store.js').then(function (m) {
    var need = !!(m.S && m.S.file && !m.S.readonly);
    return m.saveWork().then(function () { window.__automapSave = need ? 'saved' : 'nothing'; });
  }).catch(function (e) { window.__automapSave = 'error: ' + e; });
  return 1;
})()"""

# 起動の表示（サーバーの準備ができるまで窓に出す・外の物を読まない）。__stage(段)・__fail(見出し, 説明, 詳しく, 記録) は _painter が呼ぶ。
# 経過の秒はプロセスが始まってから（@OFFSET@＝窓を作った時の秒）。8 秒を過ぎたら遅い時の訳を出す
SPLASH_HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>Auto Note Plotter</title>
<style>
:root { color-scheme: dark; }
html, body { margin: 0; height: 100%; background: #0e0e0e; color: #e8e8ea;
  font-family: "Yu Gothic UI", "Meiryo UI", "Segoe UI", sans-serif; }
.wrap { box-sizing: border-box; height: 100%; padding: 24px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 16px; text-align: center; }
.logo { display: flex; gap: 14px; align-items: flex-end; height: 70px; }
.n { position: relative; width: 44px; height: 44px; border-radius: 9px; animation: bob 1.4s ease-in-out infinite; }
.n.r { background: #e2363c; }
.n.b { background: #2c7ce8; margin-bottom: 22px; animation-delay: .7s; }
.n::after { content: ""; position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  border-left: 11px solid transparent; border-right: 11px solid transparent; }
.n.r::after { border-top: 13px solid #fff; }
.n.b::after { border-bottom: 13px solid #fff; }
@keyframes bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: .04em; }
#stage { min-height: 1.4em; font-size: 15px; color: #c9c9cf; }
.bar { width: 260px; height: 3px; overflow: hidden; border-radius: 2px; background: #26262b; }
.bar i { display: block; width: 40%; height: 100%; background: linear-gradient(90deg, #e2363c, #2c7ce8); animation: run 1.3s linear infinite; }
@keyframes run { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
#sec { font-size: 12px; color: #8a8a92; }
#hint { max-width: 560px; font-size: 12.5px; line-height: 1.7; color: #8a8a92; visibility: hidden; }
#err { display: none; box-sizing: border-box; max-width: 760px; width: 100%; padding: 16px 18px; text-align: left; font-size: 13.5px;
  line-height: 1.7; background: #1c1416; border: 1px solid #5a2a2e; border-radius: 8px; }
#err h2 { margin: 0 0 6px; font-size: 16px; color: #ff8a8f; }
#err pre { margin: 8px 0; max-height: 40vh; overflow: auto; white-space: pre-wrap; word-break: break-all; font-size: 12.5px; color: #e0c8ca;
  font-family: Consolas, "BIZ UDGothic", monospace; }
#errLog { color: #b9b9c0; white-space: pre-line; word-break: break-all; }
body.fail .bar, body.fail #sec, body.fail #hint, body.fail #stage { display: none; }
body.fail .n { animation: none; opacity: .45; }
body.fail #err { display: block; }
</style></head>
<body><div class="wrap">
  <div class="logo" aria-hidden="true"><div class="n r"></div><div class="n b"></div></div>
  <h1>Auto Note Plotter</h1>
  <div id="stage">起動しています…</div>
  <div class="bar"><i></i></div>
  <div id="sec"></div>
  <div id="hint">初めての起動・パソコンを起動し直した直後・アプリを更新した後は、部品の読み込み（ウイルス対策ソフトの検査を含む）に
    30 秒ほどかかることがあります。そのままお待ちください。</div>
  <div id="err"><h2 id="errHead"></h2><div id="errMsg"></div><pre id="errDetail"></pre><div id="errLog"></div></div>
</div>
<script>
var T0 = Date.now() - @OFFSET@;
function tick() {
  var s = Math.max(0, Math.floor((Date.now() - T0) / 1000));
  document.getElementById('sec').textContent = s + ' 秒';
  if (s >= 8) document.getElementById('hint').style.visibility = 'visible';
}
setInterval(tick, 250); tick();
window.__stage = function (t) { document.getElementById('stage').textContent = t; return 1; };
window.__fail = function (head, msg, detail, logText) {
  document.body.className = 'fail';
  document.getElementById('errHead').textContent = head;
  document.getElementById('errMsg').textContent = msg;
  document.getElementById('errDetail').textContent = detail;
  document.getElementById('errLog').textContent = logText;
  return 1;
};
</script></body></html>"""


def splash_html(offset=0.0):
    """起動の表示の HTML（offset＝窓を作った時の、プロセスが始まってからの秒＝経過の秒をダブルクリックから数える）"""
    return SPLASH_HTML.replace('@OFFSET@', str(max(0, int(offset * 1000))))


def last_song(S):
    """最後に開いていた曲の結果のファイルの名前（作業ファイルを一番後に保存した曲・窓を閉じる時と「終わる」で画面が保存する）。
    作業ファイルが無ければ一覧の頭（画面が覚えていない時に開く曲）。曲が無ければ None"""
    songs = S.songs()
    best = None
    for s in songs:
        try:
            t = S.work_path(S.OUT / s['app_file']).stat().st_mtime
        except OSError:
            continue
        if best is None or t > best[0]:
            best = (t, s['app_file'])
    return best[1] if best else (songs[0]['app_file'] if songs else None)


def single_flight(fn):
    """同じ引数の呼び出しが先に動いていたら、それが終わるのを待ってから呼ぶ（song_data は覚えた物を返す＝二重に作らない）"""
    lock, running = threading.Lock(), {}

    def call(p):
        key = str(p)
        with lock:
            ev = running.get(key)
            mine = ev is None
            if mine:
                ev = running[key] = threading.Event()
        if not mine:
            ev.wait(300)
            return fn(p)
        try:
            return fn(p)
        finally:
            with lock:
                running.pop(key, None)
            ev.set()
    call.__wrapped__ = fn
    return call


class Desktop:
    """窓のアプリ。run() が窓（起動の表示）を出し、_boot（裏の流れ）がサーバーの部品を読んでサーバーを始め、アプリの画面へ移る"""

    def __init__(self, webview, port, out=None, cache=None, debug=False):
        self.wv = webview
        self.S = self.srv = None    # server モジュールとサーバー（_boot が作る）
        self.port, self.out, self.cache, self.debug = port, out, cache, debug
        self.url = f'http://127.0.0.1:{port}/'
        self.allow_close = False    # ×をそのまま通す（保存してサーバーを止めた後・サーバーが先に止まった時・起動に失敗した時）
        self.closing = False        # 閉じる手順の途中
        self.stopped = threading.Event()
        self.serving = False        # serve_forever の流れを始めた（止める時に shutdown を呼んでよい）
        self.saved_at = 0.0         # 作業ファイルを最後に保存した時刻（サーバーに届いた物）
        self.selftest = None
        self.selftest_quit = False   # 確かめを画面の「終わる」で閉じる
        self.result = {}
        # 起動の表示（_painter が窓に書く）
        self.app_page = False       # アプリの画面を読み込み始めた（それまでは起動の表示＝保存する物が無い）
        self.boot_cancel = False    # 起動の途中で窓を閉じた
        self.boot_error = None      # 起動に失敗した（窓に出した訳）
        self.stage = '起動しています…'
        self.fail = None            # (見出し, 説明, 詳しく, 記録)
        self.painted = None         # 最後に窓に書いた物
        self.splash_lock = threading.Lock()
        self.times = {}             # 起動の段の秒（プロセスが始まってから）

    @property
    def base_url(self):
        """合言葉を除いた URL（記録・確かめの結果に書く）"""
        return self.url.split('#', 1)[0]

    def mark(self, name):
        self.times[name] = round(since(), 2)
        log(f'起動の段: {name}（+{self.times[name]:.1f} 秒）')

    def attach(self, server, srv):
        """サーバーを窓につなぐ: 作業ファイルの保存が届いたかを見る口・曲のデータを二重に作らない口・合言葉（server.py の出入りの守り）"""
        self.S, self.srv = server, srv
        self.port = srv.server_address[1]
        self.url = server.access_url(self.port)   # 合言葉（#k=）付き＝画面の js/key.js が読む。記録には書かない（base_url）
        try:
            server.write_key(self.port)   # app/stop.bat・ほかの窓の二重起動の確かめが読む（止める時に _serve が消す）
        except OSError as e:
            log(f'合言葉を書けなかった: {e}')
        orig = server.save_work

        def save_work(p, w):   # 届いたことを確かめるため（server の PUT /api/work と、ほかの受け持ちの ctx.save_work）
            r = orig(p, w)
            self.saved_at = time.time()
            return r
        server.save_work = save_work
        server.song_data = single_flight(server.song_data)   # 先に作っている（_prewarm）曲を画面も頼んだら待つ

    # -- 窓の大きさ（前に閉じた時の大きさ・無ければ作業領域の 9 割） --
    def _size(self):
        w, h = 1600, 960
        try:
            class RECT(ctypes.Structure):
                _fields_ = [('l', ctypes.c_long), ('t', ctypes.c_long), ('r', ctypes.c_long), ('b', ctypes.c_long)]
            rc = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rc), 0):   # SPI_GETWORKAREA（DPI を知らない間＝論理の大きさ）
                w, h = min(1760, int((rc.r - rc.l) * 0.92)), min(1100, int((rc.b - rc.t) * 0.92))
        except Exception:   # noqa: BLE001
            pass
        try:
            d = json.loads((data_dir() / 'window.json').read_text(encoding='utf-8'))
            w, h = max(1000, min(int(d['w']), 4000)), max(650, min(int(d['h']), 3000))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return w, h

    def _remember_size(self):
        if self.selftest:   # 確かめの窓の大きさは覚えない
            return
        try:
            w, h = int(self.win.width), int(self.win.height)
            if w >= 600 and h >= 400:
                (data_dir() / 'window.json').write_text(json.dumps({'w': w, 'h': h}), encoding='utf-8')
        except Exception:   # noqa: BLE001
            pass

    def run(self, selftest=None):
        self.selftest = selftest
        w, h = self._size()
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('nlm-automap.app')   # タスクバーにこの窓のアイコンを出す
        except Exception:   # noqa: BLE001
            pass
        ico = icon_path()
        # 先に起動の表示の窓を出す（サーバーの部品を読むのは窓が出てから＝裏の _boot）。題名も「起動しています」に
        self.win = self.wv.create_window(TITLE + '（起動しています…）', html=splash_html(since()), width=w, height=h, min_size=(1000, 650),
                                         background_color='#0e0e0e', text_select=True)
        self.win.events.closing += self._on_closing
        self.mark('窓を作る')
        threading.Thread(target=self._boot, name='automap-boot', daemon=True).start()
        self.wv.start(None, private_mode=False, storage_path=str(data_dir() / 'webview'),
                      icon=str(ico) if ico else None, debug=self.debug)
        # 窓が閉じた（×・「終わる」・stop.bat・起動の途中）
        self.boot_cancel = True
        if self.serving and not self.stopped.is_set():
            self.srv.shutdown()
        if self.srv is not None:
            self.srv.server_close()
        log('止めた')

    # ---- 起動（裏の流れ・pywebview の start が窓を出した後に呼ぶ） ----
    def _boot(self):
        threading.Thread(target=lambda: self.win.events.shown.wait(120) and self.mark('窓が出た'), daemon=True).start()
        threading.Thread(target=self._painter, name='automap-splash', daemon=True).start()
        try:
            self._set_stage('プログラムを読み込んでいます…')
            t = time.time()
            import server     # app/server.py（重い部品は使う時に読む＝ここは 0.1〜0.3 秒・DLL・.pyd は 20 足らず）
            import importer   # server.connect() が読むのと同じモジュール（app/importer.py）
            log(f'サーバーの部品を読み込んだ（{time.time() - t:.1f} 秒）')
            self.mark('部品を読み込んだ')
            if self.boot_cancel:
                return
            self._set_stage('サーバーを始めています…')
            srv = self._make_server(server)
            if self.boot_cancel:
                srv.server_close()
                return
            self.attach(server, srv)
            importer.use_window_picker(self.win)
            self.serving = True
            threading.Thread(target=self._serve, name='automap-server', daemon=True).start()
            threading.Thread(target=self._prewarm, name='automap-prewarm', daemon=True).start()
            self.mark('サーバーが待ち始めた')
            self._set_stage('画面を読み込んでいます…')
            # 起動の表示が読み込まれてから切り替える（先に切り替えると、起動の表示の「読み込んだ」の合図をアプリの画面の物と取り違える）
            shown = self.win.events.loaded.wait(30)
            with self.splash_lock:
                self.result['splash'] = {'shown': bool(shown), 'painted': self.painted}
                self.app_page = True
            if self.boot_cancel:
                return
            log(f'窓を開く: {self.base_url}')
            self.win.load_url(self.url)
            self.win.set_title(TITLE)
            self.mark('画面を読み込み始めた')
            threading.Thread(target=self._watch_open, name='automap-watch', daemon=True).start()
        except Exception as e:   # noqa: BLE001
            log(traceback.format_exc())
            if not self.boot_cancel:   # 起動の途中で窓を閉じた時は知らせない
                self._boot_failed(e)
            return
        if self.selftest:
            self._selftest()

    def _make_server(self, server):
        """サーバーを作る（server.make_server）。窓を出している間に番号が使われたら、空いている番号で待ち直す"""
        try:
            return server.make_server(self.port, self.out, self.cache, cls=ExclusiveServer)
        except OSError as e:
            if getattr(e, 'winerror', None) not in (10048, 10013):   # WSAEADDRINUSE・WSAEACCES（ほかが使っている）
                raise
            port = free_port(self.port + 1)
            log(f'{self.port} が使われたので {port} で待つ')
            self.port, self.url = port, f'http://127.0.0.1:{port}/'
            return ExclusiveServer(('127.0.0.1', port), server.H)   # make_server の最後と同じ（つなぐ口はもうつないだ）

    def _set_stage(self, text):
        self.stage = text

    def _painter(self):
        """起動の表示に今の段・失敗を書く（窓が読み込まれてから・アプリの画面へ移るまで）"""
        while True:
            with self.splash_lock:
                if self.app_page:
                    return
                cur = self.fail or self.stage
                if cur != self.painted and self.win.events.loaded.is_set():
                    js = (f'window.__fail({", ".join(json.dumps(x, ensure_ascii=False) for x in cur)})' if self.fail
                          else f'window.__stage({json.dumps(cur, ensure_ascii=False)})')
                    try:
                        self.win.evaluate_js(js)
                        if self.painted is None:
                            self.mark('起動の表示が出た')
                        self.painted = cur
                    except Exception:   # noqa: BLE001
                        log(traceback.format_exc())
                        self.painted = cur   # 書けない物を何度も試さない
                if self.fail and self.painted == self.fail:
                    return
            time.sleep(0.1)

    def _boot_failed(self, e):
        """起動に失敗した: 窓に訳と記録の場所を出す（×ですぐ閉じる）。窓が読み込まれない（WebView2 が動かない）時は MessageBox"""
        self.boot_error = f'{type(e).__name__}: {e}'
        self.allow_close = True
        where = (f'記録: {LOG_FILE}' if LOG_FILE else '記録: この黒い窓の出力') + \
            '\n窓を閉じて、もう一度起動してください。続く時は、この画面か記録を見せてください。'
        msg = 'サーバーを始められませんでした。' if self.S is None or self.srv is None else '画面へ移れませんでした。'
        detail = ''.join(traceback.format_exception(e)[-6:])   # 最後の行が失敗の訳
        with self.splash_lock:
            self.fail = ('起動できませんでした', msg, detail.strip(), where)
        try:
            self.win.set_title(TITLE + '（起動できませんでした）')
        except Exception:   # noqa: BLE001
            pass
        t0 = time.time()
        while time.time() - t0 < 5 and self.painted != self.fail:
            time.sleep(0.1)
        if self.painted != self.fail and not self.selftest:
            alert(f'起動できませんでした: {self.boot_error}\n{where}')
        if self.selftest:   # 確かめは窓を残さない（失敗は結果の JSON に）
            time.sleep(1.5)
            self.win.destroy()

    def _prewarm(self):
        """最後に開いていた曲の曲のデータを先に作る（画面の読み込みと重ねる・答えは画面が頼んだ時と同じ物）"""
        try:
            name = last_song(self.S)
            if not name:
                return
            t = time.time()
            self.S.song_data(self.S.out_file(name))
            log(f'曲のデータを先に作った: {name}（{time.time() - t:.1f} 秒）')
            self.mark('曲のデータを先に作った')
        except Exception as e:   # noqa: BLE001  （画面が頼んだ時にもう一度作る・失敗はそこで画面に出る）
            log(f'曲のデータを先に作れなかった（画面が開く時に作る）: {type(e).__name__}: {e}')

    def _watch_open(self):
        """画面が読み込まれた・最初の曲を開いた時刻を記録に（起動の遅さを後から見るため）。画面の起動の段（index.html の起動の見張り
        window.anpBoot）も記録に出し、同じ段で BOOT_STUCK 秒止まったままなら 1 回読み込み直す（2026-11-15 利用者「起動させたのだけど、
        画面が真っ暗なまま。前にも 1 回あった」＝11-10 と 11-15 の 2 回。部品を読めなかった時は画面が自分で読み込み直す）"""
        try:
            if not self.win.events.loaded.wait(120):
                return
            self.mark('画面を読み込んだ')
        except Exception:   # noqa: BLE001  （記録のためだけ）
            return
        t0, last, why_seen, reloaded = time.time(), None, '', False
        while time.time() - t0 < 300 and not self.closing and not self.stopped.is_set():
            try:
                r = self.win.evaluate_js(BOOT_JS)
            except Exception:   # noqa: BLE001  （読み込み直している間など・続けて見る）
                r = None
            v = list(r) if isinstance(r, (list, tuple)) else []
            v += ['', '', '', 0][len(v):]
            st, stage, why, age = str(v[0] or ''), str(v[1] or ''), str(v[2] or ''), v[3]
            age = age if isinstance(age, (int, float)) else 0
            if stage != last:
                last = stage
                if stage and stage != 'done':
                    log(f'画面の起動の段: {stage}')
            if why and why != why_seen:
                why_seen = why
                log(f'画面の部品を読めなかった: {why}（画面が自分で読み込み直す）')
            if 'を開いた' in st or 'できなかった' in st or '曲が無い' in st or stage == 'done':
                self.mark('最初の曲を開いた' if 'を開いた' in st else f'最初の曲を開けなかった（{st[:60]}）')
                log('起動の段（プロセスが始まってからの秒）: ' + '・'.join(f'{k} {v:.1f}' for k, v in self.times.items()))
                return
            if stage and not reloaded and (age or 0) > BOOT_STUCK * 1000:
                reloaded = True
                log(f'画面の起動が「{stage}」で {BOOT_STUCK} 秒止まったので、画面を読み込み直す')
                try:
                    self.win.load_url(self.url)
                except Exception as e:   # noqa: BLE001
                    log(f'読み込み直せなかった: {e}')
            time.sleep(0.25)
        if not self.closing and not self.stopped.is_set():
            log(f'最初の曲を開いた知らせが {time.time() - t0:.0f} 秒来なかった（画面の起動の段: {last or "始まっていない"}）')

    def _serve(self):
        try:
            self.srv.serve_forever()
        except Exception:   # noqa: BLE001
            log(traceback.format_exc())
        finally:
            self.stopped.set()
            self.S.drop_key(self.port)
            if not self.closing:   # 画面の「終わる」・app/stop.bat でサーバーが先に止まった（画面はもう保存した）→ 窓も閉じる
                log('サーバーが止まったので窓を閉じる')
                self.allow_close = True
                try:
                    self.win.destroy()
                except Exception:   # noqa: BLE001
                    pass

    # -- ×で閉じる: ここ（窓の流れ）では待たない。別の流れで保存してから閉じ直す --
    def _on_closing(self):
        if self.allow_close:
            return True
        if not self.app_page:   # 起動の途中（まだ起動の表示＝保存する物が無い）→ そのまま閉じる（run が後を片付ける）
            self.boot_cancel = True
            return True
        if not self.closing:
            self.closing = True
            threading.Thread(target=self._close_flow, name='automap-close', daemon=True).start()
        return False

    def _close_flow(self):
        try:
            running = [j for j in list(self.S.JOBS.values()) if j.get('state') == 'running']
            if running:
                what = '・'.join(sorted({KIND_TEXT.get(j.get('kind'), '作業') for j in running}))
                if not self.ask(f'{what}の途中です。終わると途中の作業を止めます。\n終わりますか？'):
                    self.closing = False
                    return
            ok, why = self.save_page()
            log(f'作業ファイルの保存: {"できた" if ok else "できなかった"}（{why}）')
            self.result['close_save'] = {'ok': ok, 'why': why}
            if not ok and not self.ask(f'作業ファイルを保存できませんでした（{why}）。\nそれでも終わりますか？'):
                self.closing = False
                return
            for j in running:
                j['cancel'] = True
                pr = j.get('proc')
                if pr:
                    try:
                        pr.kill()
                    except OSError:
                        pass
            self._remember_size()
        except Exception:   # noqa: BLE001  （思わぬ失敗でも閉じる＝窓が閉じられなくなるよりよい。作業ファイルは変えるたびに自動で保存している）
            log(traceback.format_exc())
        self.allow_close = True
        try:
            self.srv.shutdown()
        except Exception:   # noqa: BLE001
            pass
        self.win.destroy()

    def save_page(self, timeout=10.0):
        """画面の作業ファイルを保存させ、サーバーに届いたかを確かめる → (できたか, 説明)"""
        if not self.win.events.loaded.is_set():
            return True, '画面がまだ読み込まれていない'
        t0 = time.time()
        try:
            self.win.evaluate_js(SAVE_JS)
            while time.time() - t0 < timeout:
                st = self.win.evaluate_js('window.__automapSave')
                if st == 'nothing':
                    return True, '保存する物が無い（曲を開いていない）'
                if st == 'saved':
                    return (True, 'サーバーに届いた') if self.saved_at >= t0 else (False, 'サーバーに届かなかった')
                if isinstance(st, str) and st.startswith('error'):
                    return False, st
                time.sleep(0.1)
            return False, f'{timeout:g} 秒で終わらなかった'
        except Exception as e:   # noqa: BLE001
            return False, f'{type(e).__name__}: {e}'

    def on_gui(self, fn):
        """窓の流れ（GUI のスレッド）で fn() を動かして答えを返す"""
        from System import Func, Type   # pythonnet（pywebview の WinForms が読み込み済み）
        box = {}

        def run():
            try:
                box['r'] = fn()
            except Exception as e:   # noqa: BLE001
                box['e'] = e
        self.win.native.Invoke(Func[Type](run))
        if 'e' in box:
            raise box['e']
        return box.get('r')

    def ask(self, msg):
        """「OK・キャンセル」の確かめ（アプリの窓の上に出す）。確かめ用（--selftest）の時は聞かずに OK"""
        return True if self.selftest else self.ask_box(msg)

    def ask_box(self, msg):
        try:
            import System.Windows.Forms as WF
            return self.on_gui(lambda: WF.MessageBox.Show(self.win.native, msg, TITLE, WF.MessageBoxButtons.OKCancel,
                                                          WF.MessageBoxIcon.Question) == WF.DialogResult.OK)
        except Exception:   # noqa: BLE001
            log(traceback.format_exc())
            return bool(self.win.create_confirmation_dialog(TITLE, msg))

    # ---- 確かめ用 ----
    def js_wait(self, code, timeout=20.0):
        """code＝値か Promise を返す JS の式。答え（JSON にできる物）を待って返す"""
        key = '__dt' + uuid.uuid4().hex[:8]
        self.win.evaluate_js(f'window.{key} = null; Promise.resolve().then(() => ({code})).then(v => {{ window.{key} = {{v: v === undefined ? null : v}}; }}, '
                             f'e => {{ window.{key} = {{e: String(e && e.stack || e)}}; }}); 1')
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = self.win.evaluate_js(f'window.{key}')
            if r:
                if 'e' in r:
                    raise RuntimeError(r['e'])
                return r['v']
            time.sleep(0.1)
        raise TimeoutError(code[:60])

    def _selftest(self):
        R = self.result
        R.update(url=self.base_url, steps=[])

        def step(name, ok, **info):
            R['steps'].append(dict(name=name, ok=bool(ok), **info))
            log(f'確かめ: {name} {"OK" if ok else "NG"} {json.dumps(info, ensure_ascii=False)[:300]}')

        try:
            step('読み込み', self.win.events.loaded.wait(40))
            self.win.evaluate_js("window.__errs = []; addEventListener('error', e => __errs.push(String(e.message || e))); "
                                 "addEventListener('unhandledrejection', e => __errs.push('rejection: ' + String(e.reason && e.reason.message || e.reason))); 1")
            t0, st = time.time(), ''
            while time.time() - t0 < 120:
                st = self.win.evaluate_js("document.getElementById('status').textContent") or ''
                if 'を開いた' in st or 'できなかった' in st or '曲が無い' in st:
                    break
                time.sleep(0.3)
            if 'を開いた' not in st:   # 開けない時の手がかり
                R['diag'] = self.js_wait("""({href: location.href, ready: document.readyState, vis: document.visibilityState, focus: document.hasFocus(),
                  songs: document.getElementById('song').options.length, pv: document.getElementById('pv').innerHTML.length,
                  errs: window.__errs})""")
                log(f'手がかり: {R["diag"]}')
            info = self.js_wait("""import('/static/js/store.js').then(async st => { const pl = await import('/static/js/player.js');
              const $ = id => document.getElementById(id), cv = document.querySelector('#pvView canvas');
              return {song: st.S.song, file: st.S.file, notes: st.S.D ? st.S.D.notes.length : null, status: $('status').textContent,
                      bad: $('status').classList.contains('bad'), pvKind: $('pvKind') ? $('pvKind').textContent : null, canvas: !!cv,
                      gl: cv ? !!(cv.getContext('webgl2') || cv.getContext('webgl')) : false, audio: pl.P.au.map(a => a.readyState),
                      size: [innerWidth, innerHeight]}; })""")
            step('曲を開く', 'を開いた' in (info.get('status') or '') and not info.get('bad'), song=info.get('song'), notes=info.get('notes'),
                 status=info.get('status'), took=round(time.time() - t0, 1), size=info.get('size'))
            step('3D（WebGL）', info.get('canvas') and info.get('gl') and info.get('pvKind') == '', pvKind=info.get('pvKind'))
            t1 = time.time()
            while time.time() - t1 < 15 and not all(x >= 1 for x in info.get('audio') or [0]):
                time.sleep(0.5)
                info['audio'] = self.js_wait("import('/static/js/player.js').then(pl => pl.P.au.map(a => a.readyState))")
            step('音（4つの <audio>）', len(info.get('audio') or []) == 4 and all(x >= 1 for x in info['audio']), readyState=info['audio'])
            # 音が鳴るか: 消音で4つとも 1 秒鳴らして再生位置が進むか（スクリプトからの再生は「人の操作」ではないので、消音でないと
            # 自動再生の決まりで止められることがある。人がボタン・キーで始めれば音が出る）
            snd = self.js_wait("""import('/static/js/player.js').then(async pl => {
              const m0 = pl.P.au.map(a => a.muted); pl.P.au.forEach(a => { a.muted = true; a.currentTime = 30; });
              const r = await Promise.all(pl.P.au.map(a => a.play().then(() => 'ok', e => String(e.name || e))));
              await new Promise(z => setTimeout(z, 1200)); const t = pl.P.au.map(a => +a.currentTime.toFixed(2));
              pl.P.au.forEach((a, i) => { a.pause(); a.muted = m0[i]; a.currentTime = 0; }); return {play: r, t: t}; })""")
            step('音が鳴る（消音で4つとも）', all(x == 'ok' for x in snd['play']) and all(t > 30.3 for t in snd['t']), **snd)
            # キー: Space で再生・もう一度で止める（画面のキーの受け口が動くか。消音でない再生が自動再生の決まりで止められたかも記録）
            play = self.js_wait("""import('/static/js/player.js').then(async pl => {
              const key = o => document.body.dispatchEvent(new KeyboardEvent('keydown', Object.assign({bubbles: true}, o)));
              key({key: ' ', code: 'Space'}); await new Promise(r => setTimeout(r, 1500));
              const a = pl.P.au[0], r = {playing: pl.P.playing, t: +a.currentTime.toFixed(2), paused: a.paused};
              key({key: ' ', code: 'Space'}); await new Promise(r => setTimeout(r, 300)); r.after = pl.P.playing; pl.seek(0); return r; })""")
            step('キー Space（再生・止める）', play.get('playing') and not play.get('after'), **play)
            und = self.js_wait("""import('/static/js/store.js').then(st => { const n0 = st.S.W ? st.S.W.ranges.length : null;
              document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', code: 'KeyZ', ctrlKey: true, bubbles: true}));
              return {ranges: n0}; })""")
            step('キー Ctrl+Z（落ちない）', True, **und)
            ok, info = self._test_picker()
            step('ファイルの窓（取り込みの「選ぶ…」）', ok, **info)
            ok, info = self._test_ask()
            step('確かめの窓（×で閉じる時）', ok, **info)
            lib = self.js_wait("""(async () => { document.getElementById('libBtn').click(); await new Promise(r => setTimeout(r, 1500));
              const d = document.getElementById('libDlg'), shown = !!d && d.style.display === 'flex';
              if (d) document.getElementById('libClose').click(); return {shown: shown, count: d ? document.getElementById('libCount').textContent.slice(0, 80) : null}; })()""")
            step('ライブラリの窓', lib.get('shown'), **lib)
            if os.environ.get('NLM_EXE'):   # 確かめの時だけ（本物の NLM を起動しない＝NLM_EXE に害の無い物を入れて呼ぶ）
                nlm = self.js_wait("import('/static/js/store.js').then(st => st.api('POST', '/api/open-nlm', {file: st.S.file}))")
                step('NLM で開く（起動の口）', (nlm or {}).get('ok'), answer=nlm, exe=Path(os.environ['NLM_EXE']).name)
            if self.selftest == 'generate':
                g0 = time.time()
                self.win.evaluate_js("document.getElementById('gen').click(); 1")
                gs = ''
                while time.time() - g0 < 300:
                    time.sleep(1)
                    gs = self.win.evaluate_js("document.getElementById('genState').textContent") or ''
                    if '作り直した' in gs or '失敗' in gs or '作り直せなかった' in gs or ('作り直して' not in gs and time.time() - g0 > 5 and not gs):
                        break
                n = self.js_wait("import('/static/js/store.js').then(st => st.S.D.notes.length)")
                step('作り直し', '作り直した' in gs, genState=gs, notes=n, took=round(time.time() - g0, 1))
            R['js_errors'] = self.win.evaluate_js('window.__errs') or []
            step('画面のエラー無し', not R['js_errors'], errors=R['js_errors'][:10])
        except Exception as e:   # noqa: BLE001
            step('例外', False, error=f'{type(e).__name__}: {e}', tb=traceback.format_exc()[-1500:])
        R['close_at'] = time.time()
        if self.selftest_quit:   # 画面の「終わる」（確かめの窓は OK にする）→ 画面が保存 → /api/shutdown → サーバーが止まって窓も閉じる
            try:
                self.win.evaluate_js("window.confirm = () => true; document.getElementById('quit').click(); 1")
                return
            except Exception:   # noqa: BLE001
                log(traceback.format_exc())
        # 利用者が×を押したのと同じ閉じ方（WM_CLOSE）→ _on_closing → 保存 → サーバーを止める → 閉じる
        try:
            hwnd = int(self.win.native.Handle.ToInt64())
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        except Exception:   # noqa: BLE001
            log(traceback.format_exc())
            self.win.destroy()

    def _test_ask(self):
        """×の時の確かめの窓（MessageBox を窓の流れで出す）を出し、閉じる（WM_CLOSE＝キャンセル）→ (出て・キャンセルになったか, 情報)"""
        box = {}

        def run():
            try:
                box['r'] = self.ask_box('確かめ用の窓です（すぐ閉じます）。')
            except Exception as e:   # noqa: BLE001
                box['e'] = f'{type(e).__name__}: {e}'
        t = threading.Thread(target=run, daemon=True)
        t.start()
        found = close_dialog(t)
        t.join(10)
        return bool(found) and box.get('r') is False, {'dialog': found[0][1] if found else None, 'answer': box.get('r'), 'error': box.get('e')}

    def _test_picker(self):
        """画面の「＋ 曲を取り込む」→「選ぶ…」でファイルの窓を出し（サーバーの受け答えの流れから PICKER が呼ばれる＝本物と同じ）、
        出たのを見つけたら閉じる（WM_CLOSE）→ (出せて・閉じたら画面が元に戻ったか, 情報)"""
        box = {}

        def run():
            try:
                box['r'] = self.js_wait("""(async () => { document.getElementById('importBtn').click(); await new Promise(r => setTimeout(r, 300));
                  const shown = document.getElementById('impDlg').style.display === 'flex';
                  document.getElementById('impBrowse').click(); await new Promise(r => setTimeout(r, 200));
                  for (let i = 0; i < 150 && document.getElementById('impBrowse').disabled; i++) await new Promise(r => setTimeout(r, 100));
                  const m = document.getElementById('impPickMsg'), r = {imp_dialog: shown, msg: m.textContent, bad: m.classList.contains('bad')};
                  document.getElementById('impClose').click(); return r; })()""", timeout=30)
            except Exception as e:   # noqa: BLE001
                box['e'] = f'{type(e).__name__}: {e}'
        t = threading.Thread(target=run, daemon=True)
        t.start()
        found = close_dialog(t)
        t.join(30)
        r = box.get('r') or {}
        ok = bool(found) and 'e' not in box and not t.is_alive() and r.get('imp_dialog') and not r.get('bad') and not r.get('msg')
        return ok, {'dialog': found[0][1] if found else None, 'page': r, 'error': box.get('e')}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if '--data-dir' in argv[:-1]:   # 記録の置き場も替えるので、記録を開く（quiet_streams）より前に
        os.environ[DIR_ENV] = str(Path(argv[argv.index('--data-dir') + 1]).resolve())
    quiet_streams()
    ap = argparse.ArgumentParser(description='譜面づくりのアプリを窓で開く（pywebview）')
    ap.add_argument('--port', type=int, default=8765, help='待つ番号（使われていたら空いている番号に）')
    ap.add_argument('--out', help='結果のファイルの場所（既定 out/。確かめは写しの場所で）')
    ap.add_argument('--cache', help='分けた音の場所（既定 cache/）')
    ap.add_argument('--debug', action='store_true', help='開発者ツールを使えるようにする')
    ap.add_argument('--data-dir', help='確かめ用: 窓の覚え・WebView2 の作業の場所・記録の置き場（既定 <LOCALAPPDATA>/automap-app）')
    ap.add_argument('--shortcut', nargs='?', const='', metavar='フォルダ', help='ショートカットを作って終わる（既定はデスクトップ）')
    ap.add_argument('--selftest', action='store_true', help='確かめ用: 開いて調べ、×と同じ閉じ方で閉じる')
    ap.add_argument('--selftest-generate', action='store_true', help='確かめ用: 作り直しも（--out に写しの場所が要る）')
    ap.add_argument('--selftest-quit', action='store_true', help='確かめ用: ×ではなく画面の「終わる」で閉じる')
    ap.add_argument('--selftest-result', help='確かめの結果の JSON の場所')
    a = ap.parse_args(argv)
    if a.shortcut is not None:
        print(make_shortcut(a.shortcut or None))
        return 0
    console_python()
    sys.path.insert(0, str(APP_DIR))
    try:
        import webview
    except ImportError:
        alert('pywebview が入っていません。\n.venv/Scripts/python.exe -m pip install pywebview で入れてください（ブラウザで使うなら app/start.bat）。')
        return 1
    # サーバー（app/server.py・重い部品）はここでは読まない＝窓（起動の表示）を出してから Desktop._boot が読む
    selftest_any = a.selftest or a.selftest_generate or a.selftest_quit
    if a.selftest_generate and (not a.out or Path(a.out).resolve() == (ROOT / 'out').resolve()):
        alert('確かめの作り直しは --out に写しの場所を渡す（本物の out/ を書き換えない）')
        return 2
    if not selftest_any and automap_running(a.port):
        # 同じ作業ファイルを2つの画面で直すと、後から保存した方が勝つ（片方の直しが消える）
        r = ctypes.windll.user32.MessageBoxW(None, f'アプリはもう動いています（ブラウザか別の窓・http://127.0.0.1:{a.port}/）。\n'
                                             '同じ曲を2つの画面で直すと、後から保存した方が勝ちます。\nもう1つ開きますか？', TITLE, 0x21)
        if r != 1:   # IDOK 以外
            return 0
    port = free_port(a.port)
    if port != a.port:
        log(f'{a.port} は使われているので {port} で開く')
    app = Desktop(webview, port, a.out, a.cache, debug=a.debug)
    selftest = 'generate' if a.selftest_generate else ('basic' if a.selftest or a.selftest_quit else None)
    app.selftest_quit = a.selftest_quit
    t0 = time.time()
    try:
        app.run(selftest)
    except Exception as e:   # noqa: BLE001
        alert(f'窓を開けませんでした: {type(e).__name__}: {e}')
        log(traceback.format_exc())
        return 1
    if selftest:
        R = app.result
        R['took'] = round(time.time() - t0, 1)
        R['startup'] = app.times
        R['port_free_after'] = not in_use(app.port)
        sp = R.get('splash') or {}
        head = [{'name': '起動の表示（サーバーの準備の前に窓）', 'ok': bool(sp.get('shown')) and not app.boot_error, **sp,
                 'error': app.boot_error}]
        R['steps'] = head + R.get('steps', []) + [{'name': '閉じたらサーバーが止まる（番号が空く）', 'ok': R['port_free_after']}]
        if a.selftest_quit:
            R['steps'].append({'name': '「終わる」で画面が作業ファイルを保存', 'ok': app.saved_at >= R.get('close_at', t0)})
        else:
            cs = R.get('close_save') or {}
            R['steps'].append({'name': '×で閉じる時に作業ファイルを保存', 'ok': bool(cs.get('ok')), **cs})
        R['ok'] = all(s['ok'] for s in R['steps'])
        text = json.dumps(R, ensure_ascii=False, indent=1)
        if a.selftest_result:
            Path(a.selftest_result).write_text(text, encoding='utf-8')
        print(text)
        return 0 if R['ok'] else 3
    return 1 if app.boot_error else 0


if __name__ == '__main__':
    sys.exit(main())
