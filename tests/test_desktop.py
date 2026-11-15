"""窓のアプリ（app/desktop.py）: pywebview が無くても読める・アイコン・番号の選び方・サーバーを作る関数（server.make_server）・
取り込みのファイルの窓の差し替え（importer.use_window_picker）。窓そのものは `app/desktop.py --selftest` で確かめる"""
import json
import socket
import struct
import sys
import threading
import types
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))

import desktop  # noqa: E402


def test_reads_without_webview():
    """pywebview は main の中で読む（入っていない環境でもこのモジュールとテストは動く）"""
    src = (ROOT / 'app' / 'desktop.py').read_text(encoding='utf-8')
    assert '\nimport webview' not in src and '\nfrom webview' not in src


def test_server_after_window():
    """サーバー（重い部品）は窓（起動の表示）を出した後に裏で読む＝main では読まない（2026-11-09・起動の表示）"""
    src = (ROOT / 'app' / 'desktop.py').read_text(encoding='utf-8')
    main = src[src.index('\ndef main('):]
    assert 'import server' not in main and 'html=splash_html(' in src


def test_splash_html():
    """起動の表示: 経過の秒の起点が入る・段と失敗を書く口がある・外の物を読まない"""
    h = desktop.splash_html(1.25)
    assert 'Date.now() - 1250' in h and '@OFFSET@' not in h
    assert 'window.__stage' in h and 'window.__fail' in h
    assert 'http' not in h and ' src=' not in h and '@import' not in h


def test_data_dir_env(tmp_path, monkeypatch):
    """確かめの時は覚え・WebView2・記録の置き場を替えられる（利用者の物を触らない）"""
    monkeypatch.setenv(desktop.DIR_ENV, str(tmp_path / 'dd'))
    assert desktop.data_dir() == tmp_path / 'dd' and (tmp_path / 'dd').is_dir()


def test_last_song(tmp_path):
    """先に曲のデータを作る曲＝作業ファイルを一番後に保存した曲（無ければ一覧の頭・曲が無ければ None）"""
    import os
    out = tmp_path / 'out'
    out.mkdir()
    songs = [{'app_file': f'{n}.intent-s1.nlmf'} for n in ('A', 'B', 'C')]
    S = types.SimpleNamespace(OUT=out, songs=lambda: songs, work_path=lambda p: p.with_name(p.name[:-len('.nlmf')] + '.automap.json'))
    assert desktop.last_song(S) == 'A.intent-s1.nlmf'
    for i, n in enumerate(('C', 'B')):
        w = out / f'{n}.intent-s1.automap.json'
        w.write_text('{}', encoding='utf-8')
        os.utime(w, (1000 + i, 1000 + i))
    assert desktop.last_song(S) == 'B.intent-s1.nlmf'
    songs.clear()
    assert desktop.last_song(S) is None


def test_single_flight():
    """同じ曲の曲のデータを2つの流れが頼んだら、後の方は先の方が終わるのを待つ（二重に作らない）"""
    import time
    spans, lock, n = [], threading.Lock(), {'a': 0}

    def slow(p):
        t0 = time.perf_counter()
        with lock:
            first = p == 'a' and n['a'] == 0
            n['a'] += p == 'a'
        time.sleep(0.3 if first else 0.01)
        with lock:
            spans.append((p, t0, time.perf_counter()))
        return p.upper()
    f = desktop.single_flight(slow)
    out = []
    ts = [threading.Thread(target=lambda: out.append(f('a'))) for _ in range(2)]
    ts[0].start()
    time.sleep(0.05)
    ts[1].start()
    assert f('b') == 'B'   # 違う引数は待たない
    for t in ts:
        t.join(5)
    assert out == ['A', 'A']
    a = sorted((s for s in spans if s[0] == 'a'), key=lambda s: s[1])
    assert len(a) == 2 and a[1][1] >= a[0][2]   # 後の方は先の方が終わってから
    b = next(s for s in spans if s[0] == 'b')
    assert b[2] < a[0][2]   # 'b' は 'a' の途中で終わった


def test_icon():
    b = desktop._ico_bytes((16, 32))
    reserved, kind, n = struct.unpack('<HHH', b[:6])
    assert (reserved, kind, n) == (0, 1, 2)
    w, h, _, _, planes, bits, size, off = struct.unpack('<BBBBHHII', b[6:22])
    assert (w, h, planes, bits) == (16, 16, 1, 32) and off == 6 + 16 * 2 and len(b) >= off + size
    assert struct.unpack('<i', b[off + 8:off + 12])[0] == 32   # BMP の高さは2倍（色＋形）
    rgba = desktop._icon_rgba(16)
    assert len(rgba) == 16 * 16 * 4
    assert rgba[3] == 0                                   # 角は透明
    mid = (8 * 16 + 8) * 4
    assert rgba[mid + 3] == 255                           # 真ん中は塗られている


def test_free_port_skips_used():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        s.listen()
        used = s.getsockname()[1]
        p = desktop.free_port(used)
        assert p != used
        with socket.socket() as t:   # 返した番号は空いている
            t.bind(('127.0.0.1', p))


@pytest.mark.skipif(not hasattr(socket, 'SO_EXCLUSIVEADDRUSE'), reason='Windows だけ（SO_REUSEADDR で同じ番号に2つ待ててしまう）')
def test_exclusive_server():
    a = desktop.ExclusiveServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
    try:
        with pytest.raises(OSError):
            ThreadingHTTPServer(('127.0.0.1', a.server_address[1]), BaseHTTPRequestHandler)
    finally:
        a.server_close()


def test_make_server(tmp_path, monkeypatch):
    """main と窓のアプリが使うサーバーを作る関数: 場所を変え、つなぐ口をつなぎ、渡した型で待つ。要求に答える"""
    import server
    monkeypatch.setattr(server, 'OUT', server.OUT)       # テストの後で元に戻す
    monkeypatch.setattr(server, 'CACHE', server.CACHE)
    srv = server.make_server(0, tmp_path / 'out', tmp_path / 'cache', cls=desktop.ExclusiveServer)
    try:
        assert isinstance(srv, desktop.ExclusiveServer)
        assert server.OUT == (tmp_path / 'out').resolve() and server.CACHE == (tmp_path / 'cache').resolve()
        assert '/api/import/pick' in server.POST_ROUTES
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        port = srv.server_address[1]
        req = urllib.request.Request(f'http://127.0.0.1:{port}/api/songs', headers={server.KEY_HEADER: server.TOKEN})   # 合言葉（出入りの守り）
        with urllib.request.urlopen(req, timeout=10) as r:
            assert json.loads(r.read().decode('utf-8')) == []
        assert desktop.automap_running(port)   # 二重起動の確かめ（合言葉の要らない / を見る）
        srv.shutdown()
        th.join(5)
        assert not th.is_alive()
    finally:
        srv.server_close()


def test_window_picker(monkeypatch):
    import importer
    monkeypatch.setitem(sys.modules, 'webview', types.SimpleNamespace(FileDialog=types.SimpleNamespace(OPEN=10, FOLDER=20)))
    monkeypatch.setattr(importer, 'PICKER', importer.PICKER)   # テストの後で tkinter の物に戻す
    calls, answer = [], [('C:/music/a.flac',)]

    class Win:
        def create_file_dialog(self, kind, directory='', allow_multiple=False, file_types=()):
            calls.append({'kind': kind, 'dir': directory, 'multi': allow_multiple, 'types': file_types})
            return answer[0]

    pick = importer.use_window_picker(Win())
    assert importer.PICKER is pick
    assert pick('audio', str(ROOT)) == str(Path('C:/music/a.flac'))
    assert calls[-1]['kind'] == 10 and calls[-1]['dir'] == str(ROOT) and not calls[-1]['multi']
    assert '*.flac' in calls[-1]['types'][0]
    answer[0] = None   # やめた
    assert pick('image', str(ROOT / 'no-such-dir')) is None
    assert calls[-1]['dir'] == str(ROOT) and '*.png' in calls[-1]['types'][0]   # 無い場所は1つ上から（exe・フォルダの今の場所）
    assert pick('exe', str(ROOT / 'a' / 'b.exe')) is None and calls[-1]['dir'] == '' and '*.exe' in calls[-1]['types'][0]
    answer[0] = 'D:/AutoNotePlotter'
    assert pick('folder', str(ROOT)) == str(Path('D:/AutoNotePlotter')) and calls[-1]['kind'] == 20


def test_window_types_valid():
    """ファイルの窓の種類は pywebview の決まり（'説明 (*.拡張子;…)'）に合う"""
    util = pytest.importorskip('webview.util')
    import importer
    for types_ in importer.WINDOW_TYPES.values():
        for t in types_:
            util.parse_file_type(t)


def test_automap_running():
    """二重に開く時の確かめ: その番号で動いているのがこのアプリ（Server の頭が automap/）かどうか"""
    class Me(BaseHTTPRequestHandler):
        server_version = 'automap/0.1'

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'[]')

        def log_message(self, *a):
            pass

    class Other(Me):
        server_version = 'other/1.0'

    for handler, want in ((Me, True), (Other, False)):
        srv = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            assert desktop.automap_running(srv.server_address[1]) is want
        finally:
            srv.shutdown()
            srv.server_close()
    assert desktop.automap_running(desktop.free_port(47000)) is False


class _Win:
    """作り物の窓: evaluate_js の答えを順に返す（尽きたら最後の物）・load_url を数える"""
    def __init__(self, answers):
        self.events = types.SimpleNamespace(loaded=threading.Event())
        self.events.loaded.set()
        self.answers, self.loads = list(answers), []

    def evaluate_js(self, code):
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return a

    def load_url(self, url):
        self.loads.append(url)


def _watcher(win, monkeypatch):
    d = desktop.Desktop.__new__(desktop.Desktop)
    d.win, d.closing, d.stopped, d.url, d.times = win, False, threading.Event(), 'http://127.0.0.1:8765/#k=x', {}
    logs = []
    monkeypatch.setattr(desktop, 'log', logs.append)
    monkeypatch.setattr(desktop.time, 'sleep', lambda s: None)
    return d, logs


def test_watch_open_logs_boot_stages(monkeypatch):
    """画面の起動の段を記録に出し、済んだら「最初の曲を開いた」。確かめの途中のエラー（読み込み直している間など）で見張りを止めない
    （2026-11-15 利用者「起動させたのだけど、画面が真っ暗なまま」＝前は 1 回のエラーで見張りが終わり、何も残らなかった）"""
    win = _Win([RuntimeError('読み込み直している'), ['', '3D の準備', '', 100], ['', '曲の一覧', '', 50],
                ['桃源郷 を読み込んでいる…', '最初の曲を開く', '', 10], ['桃源郷 を開いた', 'done', '', 0]])
    d, logs = _watcher(win, monkeypatch)
    d._watch_open()
    assert '最初の曲を開いた' in d.times and win.loads == []
    assert [x for x in logs if x.startswith('画面の起動の段')] == ['画面の起動の段: 3D の準備', '画面の起動の段: 曲の一覧', '画面の起動の段: 最初の曲を開く']


def test_watch_open_reloads_once_when_stuck(monkeypatch):
    """同じ段で BOOT_STUCK 秒止まったままなら 1 回だけ読み込み直す（2 回目からはしない）・部品を読めなかった訳も記録に"""
    stuck = ['', '3D の準備', '', desktop.BOOT_STUCK * 1000 + 1]
    win = _Win([['', '', '画面の部品を読めなかった', 0], stuck, stuck, stuck, ['桃源郷 を開いた', 'done', '', 0]])
    d, logs = _watcher(win, monkeypatch)
    d._watch_open()
    assert win.loads == [d.url]
    assert any('「3D の準備」で' in x for x in logs) and any('画面の部品を読めなかった: 画面の部品を読めなかった' in x for x in logs)
    assert '最初の曲を開いた' in d.times
