"""配布物の試作（tools/dist/build_embed.py の出力）が、それだけで動くかを確かめる。本物の out/・cache/ は読み書きしない。

使い方: <どの Python でも> tools/dist/check_dist.py <配布物のフォルダ> --scratch <空の作業の場所> [--port 8767] [--window]
  1. 埋め込み用の Python の場所の決まり（sys.path・site-packages・ユーザーごとの site を切ったか）
  2. 部品の読み込み（numpy・scipy・soundfile・librosa・scikit-learn・numba の JIT・pywebview・pythonnet の .NET）
  3. 曲の解析（`-m automap.analyze_song`＝作り直しと同じく別のプロセス）を合成の音で
  4. サーバー（app/server.py --no-browser・--out・--cache は作業の場所の空のフォルダ）を起動 → 画面・曲の一覧・画面の JS → 止める
  5. --window: 起動用の exe から窓のアプリの確かめ（desktop.py --selftest・LOCALAPPDATA を作業の場所に替える）
足りない DLL（Visual C++ の再頒布可能パッケージ等）の見落としは、この PC では分からない（入っているので）→ imports も出す。
"""
import argparse
import json
import os
import secrets
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CLEAN = ('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'PYTHONEXECUTABLE', 'PYTHONSAFEPATH')


def env_like_launcher(extra=None):
    """起動用の exe（launcher.cs）と同じ環境"""
    e = {k: v for k, v in os.environ.items() if k not in CLEAN}
    e['PYTHONNOUSERSITE'] = '1'
    # この PC の開発の .venv が PATH にあると DLL を拾い得る → PATH から Python の場所を外す
    e['PATH'] = os.pathsep.join(p for p in e.get('PATH', '').split(os.pathsep) if 'python' not in p.lower() and '.venv' not in p.lower())
    e.update(extra or {})
    return e


def step(name, ok, **info):
    print(json.dumps({'step': name, 'ok': bool(ok), **info}, ensure_ascii=False)[:1500], flush=True)
    return ok


PROBE = r'''
import json, sys, time, os
r = {'exe': sys.executable, 'prefix': sys.prefix, 'path': sys.path, 'nousersite': not __import__('site').ENABLE_USER_SITE}
t = time.time()
import numpy, scipy, scipy.signal, soundfile, sklearn, numba, librosa
r['versions'] = {m.__name__: m.__version__ for m in (numpy, scipy, soundfile, sklearn, numba, librosa)}
@numba.njit(cache=False)
def f(n):
    s = 0
    for i in range(n): s += i
    return s
r['numba'] = f(10)
r['import_s'] = round(time.time() - t, 1)
import webview, clr_loader, pythonnet
pythonnet.load('netfx'); import clr; import System
r['dotnet'] = str(System.Environment.Version)
import sqlite3, ssl, ctypes
try:
    import tkinter; r['tkinter'] = True
except ImportError:
    r['tkinter'] = False
print(json.dumps(r, ensure_ascii=False))
'''


def pe_imports(path):
    """PE の読み込む DLL の名前（import の表だけ・遅延読み込みは見ない）"""
    b = Path(path).read_bytes()
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    nsec = struct.unpack_from('<H', b, pe + 6)[0]
    optsz = struct.unpack_from('<H', b, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from('<H', b, opt)[0]
    dd = opt + (112 if magic == 0x20b else 96)
    imp_rva = struct.unpack_from('<I', b, dd + 8)[0]
    secs = []
    for i in range(nsec):
        s = pe + 24 + optsz + 40 * i
        vsz, va, rsz, raw = struct.unpack_from('<IIII', b, s + 8)   # VirtualSize・VirtualAddress・SizeOfRawData・PointerToRawData
        secs.append((va, max(vsz, rsz), raw))

    def off(rva):
        for va, sz, raw in secs:
            if va <= rva < va + sz:
                return rva - va + raw
        return None
    out = []
    o = off(imp_rva) if imp_rva else None
    while o is not None:
        name_rva = struct.unpack_from('<I', b, o + 12)[0]
        if not name_rva:
            break
        no = off(name_rva)
        out.append(b[no:b.index(b'\0', no)].decode('ascii', 'replace'))
        o += 20
    return out


VC_RT = ('msvcp', 'vcruntime', 'vcomp', 'concrt', 'libomp')   # Visual C++ の実行の部品（まっさらな Windows には無いことがある）


def dll_report(dist):
    """配布物の .pyd・.dll が読む DLL のうち、まっさらな PC で見つからないかもしれない物:
    missing＝配布物のどこにも System32 にも無い・vc_rt＝Visual C++ の実行の部品で、読む物と同じフォルダ・runtime\\ に無い物
    （System32 にあるのはこの PC に再頒布可能パッケージが入っているから＝まっさらな PC には無いかもしれない）"""
    dist = Path(dist)
    sysdir = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32'
    rt = {p.name.lower() for p in (dist / 'runtime').iterdir()}
    every = {p.name.lower() for p in dist.rglob('*') if p.suffix.lower() in ('.dll', '.pyd')}
    missing, vc = {}, {}
    for p in dist.rglob('*'):
        if p.suffix.lower() not in ('.dll', '.pyd', '.exe'):
            continue
        try:
            names = pe_imports(p)
        except Exception:   # noqa: BLE001
            continue
        here = {q.name.lower() for q in p.parent.iterdir()}
        for d in names:
            dl = d.lower()
            if dl.startswith(('api-ms-win-', 'ext-ms-')):
                continue
            if dl.startswith(VC_RT):
                # 名前に指紋の付いた物（numpy.libs 等・delvewheel が入れて自分の場所を DLL の探し先に足す）は配布物のどこかにあればよい
                if dl not in here and dl not in rt and not ('-' in dl and dl in every):
                    vc.setdefault(d, []).append(str(p.relative_to(dist)))
            elif dl not in every and not (sysdir / d).exists():
                missing.setdefault(d, []).append(str(p.relative_to(dist)))

    def short(m):
        return {k: v[:4] + ([f'…ほか {len(v) - 4}'] if len(v) > 4 else []) for k, v in sorted(m.items())}
    return {'missing': short(missing), 'vc_rt': short(vc)}


def make_wav(path, seconds=40, sr=22050):
    """合成の曲（120 BPM のクリック＋和音）"""
    import math
    n = int(seconds * sr)
    frames = bytearray()
    for i in range(n):
        t = i / sr
        beat = (t * 2) % 1
        v = 0.3 * math.exp(-beat * 30) * math.sin(2 * math.pi * 1000 * t)
        v += 0.1 * (math.sin(2 * math.pi * 220 * t) + math.sin(2 * math.pi * 277 * t) + math.sin(2 * math.pi * 330 * t))
        s = int(max(-1, min(1, v)) * 32767)
        frames += struct.pack('<hh', s, s)
    import wave
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


TOKEN = secrets.token_urlsafe(32)   # 確かめのサーバーの合言葉（app/server.py の出入りの守り・環境変数 AUTOMAP_TOKEN で渡す）


def http(url, data=None, timeout=10):
    req = urllib.request.Request(url, data=data, headers=({'X-Automap': '1', 'Content-Type': 'application/json'} if data is not None else {}) | {'X-Automap-Key': TOKEN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers, r.read()


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('dist')
    ap.add_argument('--scratch', required=True)
    ap.add_argument('--port', type=int, default=8767)
    ap.add_argument('--window', action='store_true')
    a = ap.parse_args(argv)
    dist, sc = Path(a.dist).resolve(), Path(a.scratch).resolve()
    py = dist / 'runtime' / 'python.exe'
    out, cache = sc / 'out', sc / 'cache'
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    env = env_like_launcher()
    results = []

    # 1・2
    t0 = time.time()
    r = subprocess.run([str(py), '-c', PROBE], capture_output=True, env=env, cwd=str(sc), timeout=300)
    try:
        info = json.loads(r.stdout.decode('utf-8', 'replace').strip().splitlines()[-1])
    except Exception:   # noqa: BLE001
        info = {'stderr': r.stderr.decode('utf-8', 'replace')[-1500:]}
    results.append(step('部品の読み込み', r.returncode == 0 and info.get('numba') == 45, took=round(time.time() - t0, 1), **info))
    results.append(step('DLL（配布物にも System32 にも無い物）', True, missing=dll_report(dist)))

    # 3. 曲の解析
    wav = sc / 'synth.wav'
    if not wav.exists():
        make_wav(wav)
    t0 = time.time()
    ana = sc / 'analysis.json'
    r = subprocess.run([str(py), '-m', 'automap.analyze_song', str(wav), '--json', str(ana)], capture_output=True, env=dict(env, PYTHONIOENCODING='utf-8'),
                       cwd=str(dist), timeout=600)
    ok = r.returncode == 0 and ana.exists()
    tempo = None
    if ok:
        try:
            tempo = json.loads(ana.read_text(encoding='utf-8')).get('tempo')
        except ValueError:
            pass
    results.append(step('曲の解析（-m automap.analyze_song）', ok, took=round(time.time() - t0, 1), tempo=str(tempo)[:200],
                        log=r.stdout.decode('utf-8', 'replace')[-300:] + r.stderr.decode('utf-8', 'replace')[-800:]))

    # 4. サーバー
    t0 = time.time()
    pr = subprocess.Popen([str(py), str(dist / 'app' / 'server.py'), '--port', str(a.port), '--no-browser', '--out', str(out), '--cache', str(cache)],
                          cwd=str(dist), env=dict(env, PYTHONIOENCODING='utf-8', AUTOMAP_TOKEN=TOKEN), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{a.port}'
    try:
        up = False
        while time.time() - t0 < 60 and pr.poll() is None:
            try:
                http(base + '/api/songs', timeout=2)
                up = True
                break
            except Exception:   # noqa: BLE001
                time.sleep(0.3)
        results.append(step('サーバーの起動', up, took=round(time.time() - t0, 1)))
        if up:
            st, h, body = http(base + '/')
            results.append(step('画面（/）', st == 200 and b'<html' in body.lower(), server=h.get('Server'), bytes=len(body)))
            st, h, body = http(base + '/api/songs')
            results.append(step('曲の一覧（空）', st == 200, body=body.decode('utf-8', 'replace')[:200]))
            st, h, body = http(base + '/static/js/main.js')
            results.append(step('画面の JS', st == 200 and len(body) > 1000, ctype=h.get('Content-Type'), bytes=len(body)))
            st, h, body = http(base + '/api/shutdown', data=b'{}')
            results.append(step('止める（/api/shutdown）', st == 200))
        try:
            pr.wait(15)
        except subprocess.TimeoutExpired:
            pass
    finally:
        if pr.poll() is None:
            pr.kill()
        log = pr.stdout.read().decode('utf-8', 'replace') if pr.stdout else ''
    results.append(step('サーバーが止まった', pr.poll() is not None, log=log[-600:]))

    # 5. 窓のアプリ（起動用の exe から）
    if a.window:
        la = sc / 'localappdata'
        la.mkdir(exist_ok=True)
        res = sc / 'selftest.json'
        res.unlink(missing_ok=True)
        t0 = time.time()
        subprocess.Popen([str(dist / 'AutoNotePlotter.exe'), '--port', '8790', '--out', str(out), '--cache', str(cache), '--selftest', '--selftest-result', str(res)],
                         cwd=str(sc), env=dict(env, LOCALAPPDATA=str(la)))
        while time.time() - t0 < 240 and not res.exists():
            time.sleep(1)
        time.sleep(1)
        if res.exists():
            R = json.loads(res.read_text(encoding='utf-8'))
            steps = [(s['name'], s['ok']) for s in R.get('steps', [])]
            results.append(step('窓のアプリ（起動用の exe → desktop.py --selftest）', any(n == '読み込み' and o for n, o in steps), took=round(time.time() - t0, 1),
                                steps=steps, diag=R.get('diag'), errors=R.get('js_errors')))
        else:
            lg = la / 'automap-app' / 'desktop.log'
            results.append(step('窓のアプリ（起動用の exe → desktop.py --selftest）', False, log=lg.read_text(encoding='utf-8')[-1500:] if lg.exists() else '記録なし'))
    print('全体:', 'OK' if all(results) else 'NG')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
