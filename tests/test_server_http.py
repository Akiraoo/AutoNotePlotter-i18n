"""手元のサーバーの受け口（app/server.py の H・do_GET／do_POST／do_PUT・_file）を本物の HTTP で確かめる: 出入りの守り（Host・Origin・
起動ごとの合言葉・2026-11-11）・書き換える要求（POST・PUT）は頭 X-Automap: 1 が無いと断る・受け取った名前は UNC 等をファイルに触る前に断る・/static/・/audio/ の外を指す道（..・%2e%2e・\\・絶対の場所）は出さない・分けた音は Range に答える
（206・Content-Range・正しいバイト・終わりの無い範囲・後ろからの範囲・範囲の外は 416）・無いファイルは 404。
サーバーは空いている番号（0）で写しの場所（tmp_path）に立て、テストの終わりに必ず止める。設定も写し（利用者の設定を読まない・書かない）"""
import http.client
import json
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import server  # noqa: E402

SONG = '曲'
AUDIO = bytes(range(256)) * 4   # 1024 バイト（どの位置も中身で分かる）


@pytest.fixture
def srv(tmp_path, monkeypatch):
    """写しの場所に立てたサーバー → (番号, 写しの場所)。分けた音 1 つ・分けた音の場所の外に .flac（出してはいけない物）"""
    monkeypatch.setattr(server, 'OUT', server.OUT)       # テストの後で元に戻す（make_server が書き換える）
    monkeypatch.setattr(server, 'CACHE', server.CACHE)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'config.json')   # 利用者の設定を読まない・書かない
    (tmp_path / 'out').mkdir()
    (tmp_path / 'cache' / SONG / 'sub').mkdir(parents=True)
    (tmp_path / 'cache' / SONG / 'vocals.flac').write_bytes(AUDIO)
    (tmp_path / 'cache' / SONG / 'sub' / 'deep.flac').write_bytes(b'deep')
    (tmp_path / 'cache' / SONG / 'notes.txt').write_text('x', encoding='utf-8')
    (tmp_path / 'cache' / 'top.flac').write_bytes(b'SECRET-TOP')          # 分けた音の場所の直下（曲のフォルダではない）
    (tmp_path / 'secret.flac').write_bytes(b'SECRET-PARENT')              # 分けた音の場所の 1 つ上
    (tmp_path / 'out' / 'secret.flac').write_bytes(b'SECRET-OUT')         # 隣の作業の場所
    s = server.make_server(0, tmp_path / 'out', tmp_path / 'cache')
    th = threading.Thread(target=s.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)   # 止める時に待たない
    th.start()
    try:
        yield s.server_address[1], tmp_path
    finally:
        s.shutdown()
        s.server_close()
        th.join(5)


def _req(port, method, path, headers=None, body=None, key=True, host=None):
    """→ (状態, 頭 {小文字: 値}, 本文)。道はそのまま送る（urllib のように .. を畳まない）。
    key＝合言葉の頭（True＝正しい合言葉・False＝付けない・文字＝その値）・host＝Host の頭（None＝127.0.0.1:番号）"""
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        c.putrequest(method, path, skip_accept_encoding=True, skip_host=host is not None)
        if host is not None:
            c.putheader('Host', host)
        data = json.dumps(body).encode('utf-8') if body is not None else b''
        if method in ('POST', 'PUT'):
            c.putheader('Content-Length', str(len(data)))
        if key:
            c.putheader(server.KEY_HEADER, server.TOKEN if key is True else key)
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        c.endheaders(data or None)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        c.close()


def _q(s):
    return quote(s, safe='/')


VOC = f'/audio/{_q(SONG)}/vocals.flac'


def test_writes_need_the_app_header(srv):
    """POST・PUT は頭 X-Automap: 1 が無いと 403（ほかのページから送れない）・何も書かない・止まらない。頭があれば受け付ける"""
    port, tmp = srv
    cfg = tmp / 'config.json'
    for method, path in (('POST', '/api/prefs'), ('POST', '/api/shutdown'), ('POST', '/api/generate'), ('PUT', '/api/work?file=x.nlmf'),
                         ('POST', '/api/import/settings'), ('POST', '/api/nothing')):
        for h in ({}, {'X-Automap': '0'}, {'X-Automap': 'yes'}):
            st, _, body = _req(port, method, path, h, {'automap-sndon': True})
            assert st == 403 and 'error' in json.loads(body), (method, path, h)
    assert not cfg.exists()                                                   # 断った要求は何も書かない
    st, _, body = _req(port, 'GET', '/api/songs')                             # 止める要求も断った＝まだ動いている
    assert st == 200 and json.loads(body) == []
    st, _, body = _req(port, 'POST', '/api/prefs', {'X-Automap': '1'}, {'automap-sndon': True})
    assert st == 200 and json.loads(cfg.read_text(encoding='utf-8'))['ui_prefs'] == {'automap-sndon': True}
    assert _req(port, 'POST', '/api/nothing', {'X-Automap': '1'}, {})[0] == 404
    assert _req(port, 'PUT', '/api/nothing', {'X-Automap': '1'}, {})[0] == 404
    assert _req(port, 'PUT', '/api/work', {'X-Automap': '1'}, {})[0] == 400  # 頭は通る（file が無い）
    assert _req(port, 'POST', '/api/njs', {'X-Automap': '1'}, {})[0] == 400  # つないだ受け持ちの口（POST_ROUTES）も頭の後・失敗は 400
    assert _req(port, 'POST', '/api/njs', {}, {})[0] == 403


BAD_STATIC = ['/static/../server.py', '/static/%2e%2e/server.py', '/static/%2E%2E/%2E%2E/automap/config.py',
              '/static/..%5cserver.py', '/static/%5c..%5c..%5capp%5cserver.py', '/static/js/../../server.py',
              '/static/C:%5cWindows%5cwin.ini', '/static/C:/Windows/win.ini', '/static//Windows/win.ini',
              '/static/%2fWindows%2fwin.ini', '/static/', '/static/js', '/static/js/none.js']


def test_static_and_its_outside(srv):
    """/ と /static/ の中のファイルは出す。外を指す道（..・%2e%2e・\\・絶対の場所）・フォルダ・無い物は 404"""
    port, _ = srv
    st, h, body = _req(port, 'GET', '/')
    assert st == 200 and h['content-type'].startswith('text/html') and body == (server.STATIC / 'index.html').read_bytes()
    st, h, body = _req(port, 'GET', '/static/js/main.js')
    assert st == 200 and h['content-type'].startswith('text/javascript') and body == (server.STATIC / 'js' / 'main.js').read_bytes()
    for path in BAD_STATIC:
        st, _, body = _req(port, 'GET', path)
        assert st == 404 and b'import' not in body and b'[fonts]' not in body.lower(), path
    assert _req(port, 'GET', '/api/nothing')[0] == 404
    assert _req(port, 'GET', '/nothing')[0] == 404
    st, h, body = _req(port, 'GET', '/api/library/bands')   # つないだ受け持ちの口（GET_ROUTES・_reply）
    assert st == 200 and h['content-type'].startswith('application/json') and 'steps' in json.loads(body)


BAD_AUDIO = [f'/audio/{_q(SONG)}/../../secret.flac', f'/audio/{_q(SONG)}/..%2f..%2fsecret.flac', f'/audio/{_q(SONG)}/..%5c..%5csecret.flac',
             '/audio/%2e%2e/secret.flac', '/audio/../secret.flac', '/audio/../out/secret.flac', '/audio/%2E%2E/out/secret.flac',
             f'/audio/{_q(SONG)}%5c..%5c..%5cout/secret.flac', '/audio/x%5c..%5c..%5cout/secret.flac', '/audio/x%5c..%5c..%5csecret.flac',
             '/audio//top.flac', '/audio/./top.flac', '/audio/%2e/top.flac',
             f'/audio/{_q(SONG)}/sub/deep.flac', f'/audio/{_q(SONG)}/notes.txt', f'/audio/{_q(SONG)}/none.flac', '/audio/none/vocals.flac']


def test_audio_stays_inside(srv):
    """分けた音の場所の曲のフォルダの直下の .flac だけ（1 つ上・隣の作業の場所・分けた音の場所の直下・下のフォルダ・ほかの種類・
    無い物・絶対の場所は出さない）"""
    port, tmp = srv
    bad = list(BAD_AUDIO)
    for d in (tmp, tmp / 'out', tmp / 'cache'):   # 絶対の場所を曲の名前に（/ と \ の両方の書き方）
        name = 'top.flac' if d.name == 'cache' else 'secret.flac'
        bad += [f'/audio/{_q(str(d).replace(chr(92), "/")).replace("/", "%2f")}/{name}', f'/audio/{_q(str(d)).replace("/", "%5c")}/{name}']
    for path in bad:
        st, _, body = _req(port, 'GET', path)
        assert st in (400, 404) and b'SECRET' not in body and body != b'deep', path
    assert _req(port, 'GET', '/audio/' + _q(SONG))[0] == 400   # 曲の名前だけ（音の名前が無い）


def test_audio_whole_and_head(srv):
    port, _ = srv
    st, h, body = _req(port, 'GET', VOC)
    assert st == 200 and body == AUDIO and h['content-length'] == str(len(AUDIO)) and h['accept-ranges'] == 'bytes'
    assert h['content-type'] == 'audio/flac' and 'content-range' not in h
    st, h, body = _req(port, 'HEAD', VOC)
    assert st == 200 and body == b'' and h['content-length'] == str(len(AUDIO))


RANGES = [('bytes=0-0', 0, 0), ('bytes=10-19', 10, 19), ('bytes=1000-', 1000, 1023), ('bytes=-24', 1000, 1023),
          ('bytes=1000-5000', 1000, 1023), ('bytes=-5000', 0, 1023), ('bytes=1023-1023', 1023, 1023), ('bytes=5-9,20-29', 5, 9)]


def test_audio_range(srv):
    """Range: 206・Content-Range・その範囲のバイト（終わりの無い範囲・後ろから・終わりが大きすぎる時は終わりまで・2 つ目からは無視）。
    範囲の外（始まりが大きさ以上・終わりより後）は 416・Content-Range に大きさ（前は長さが負の 206 を返した）・形の崩れた範囲は 400"""
    port, _ = srv
    for rng, a, b in RANGES:
        st, h, body = _req(port, 'GET', VOC, {'Range': rng})
        assert st == 206 and h['content-range'] == f'bytes {a}-{b}/{len(AUDIO)}', rng
        assert body == AUDIO[a:b + 1] and h['content-length'] == str(b - a + 1), rng
    st, h, body = _req(port, 'HEAD', VOC, {'Range': 'bytes=1000-'})
    assert st == 206 and h['content-range'] == f'bytes 1000-1023/{len(AUDIO)}' and body == b''
    for rng in ('bytes=1024-', 'bytes=5000-6000', 'bytes=20-10', 'bytes=-0'):
        st, h, body = _req(port, 'GET', VOC, {'Range': rng})
        assert st == 416 and h['content-range'] == f'bytes */{len(AUDIO)}' and body == b'', rng
    st, _, body = _req(port, 'GET', VOC, {'Range': 'bytes=abc-'})
    assert st == 400 and b'error' in body


# ---- 出入りの守り（2026-11-11・セキュリティのスキャンの F1・F7・F9・F12） ----

def test_host_must_be_this_pc(srv):
    """Host の頭がこの PC の名前（127.0.0.1・localhost・番号付きも）でなければ、合言葉があっても 403（DNS リバインディング）"""
    port, _ = srv
    for host in (f'127.0.0.1:{port}', '127.0.0.1', f'localhost:{port}', 'LOCALHOST'):
        assert _req(port, 'GET', '/api/songs', host=host)[0] == 200, host
    for host in ('evil.example', f'evil.example:{port}', '127.0.0.1.evil.example', '10.0.0.5', ''):
        assert _req(port, 'GET', '/api/songs', host=host)[0] == 403, host
        assert _req(port, 'GET', '/', host=host)[0] == 403, host
        assert _req(port, 'POST', '/api/shutdown', {'X-Automap': '1'}, {}, host=host)[0] == 403, host
    assert _req(port, 'GET', '/api/songs')[0] == 200   # 止まっていない


def test_origin_must_be_this_server(srv):
    """Origin の頭が付いていれば、このサーバー（名前と番号）の物だけ。null は通す（合言葉は別に要る）"""
    port, _ = srv
    for org in (f'http://127.0.0.1:{port}', f'http://localhost:{port}', 'null'):
        assert _req(port, 'POST', '/api/prefs', {'X-Automap': '1', 'Origin': org}, {})[0] == 200, org
    for org in ('https://evil.example', f'http://127.0.0.1:{port + 1}', f'https://127.0.0.1:{port}', 'http://127.0.0.1', 'garbage'):
        assert _req(port, 'POST', '/api/prefs', {'X-Automap': '1', 'Origin': org}, {})[0] == 403, org
        assert _req(port, 'GET', '/api/songs', {'Origin': org})[0] == 403, org


def test_key_required(srv):
    """画面の部品（/・/static/）の外は合言葉が要る: 無い・違う・Cookie や Authorization で渡した物は 403。?k= は音とカバー画像だけ"""
    port, _ = srv
    tok = server.TOKEN
    assert len(tok) >= 40
    gets = ['/api/songs', '/api/prefs', '/api/ping', '/api/library/bands', VOC, '/api/nothing', '/nothing']
    for bad in (False, 'x' * len(tok), tok[:-1], tok + 'x', '日本語'.encode('utf-8').decode('latin-1')):
        for path in gets:
            assert _req(port, 'GET', path, key=bad)[0] == 403, (path, bad)
        assert _req(port, 'HEAD', VOC, key=bad)[0] == 403, bad
        for method, path in (('POST', '/api/prefs'), ('POST', '/api/shutdown'), ('PUT', '/api/work?file=x.nlmf'), ('POST', '/api/nothing')):
            assert _req(port, method, path, {'X-Automap': '1'}, {}, key=bad)[0] == 403, (path, bad)
    for how in ({'Cookie': f'{server.KEY_HEADER}={tok}'}, {'Authorization': f'Bearer {tok}'}):
        assert _req(port, 'GET', '/api/songs', how, key=False)[0] == 403, how
    assert _req(port, 'GET', f'/api/songs?k={tok}', key=False)[0] == 403        # ?k= は音とカバー画像だけ
    assert _req(port, 'POST', f'/api/prefs?k={tok}', {'X-Automap': '1'}, {}, key=False)[0] == 403
    st, _, body = _req(port, 'GET', f'{VOC}?k={tok}', key=False)                # <audio> の src
    assert st == 200 and body == AUDIO
    assert _req(port, 'GET', f'/api/bsexport/cover?file=x.nlmf&k={tok}', key=False)[0] in (400, 404)   # <img> の src（守りは通る）
    assert _req(port, 'GET', f'{VOC}?k={tok[:-1]}x', key=False)[0] == 403
    assert _req(port, 'GET', '/api/ping')[0] == 200 and _req(port, 'GET', '/api/songs', {'x-automap-key': tok}, key=False)[0] == 200
    for path in ('/', '/static/js/main.js', '/static/js/key.js', '/static/app.css'):   # 画面の部品は合言葉なし（<script>・<link>）
        assert _req(port, 'GET', path, key=False)[0] == 200, path


def test_key_file(tmp_path, monkeypatch):
    """合言葉の置き場（app/stop.bat・窓のアプリの二重起動の確かめが読む）: 書く・同じ合言葉の時だけ消す"""
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    f = server.write_key(8799)
    assert f == tmp_path / 'AutoNotePlotter' / 'session' / '8799.key' and f.read_text(encoding='ascii') == server.TOKEN
    assert server.access_url(8799) == f'http://127.0.0.1:8799/#k={server.TOKEN}'
    f.write_text('other', encoding='ascii')   # ほかのサーバーが同じ番号で書き直した
    server.drop_key(8799)
    assert f.exists()
    server.write_key(8799)
    server.drop_key(8799)
    assert not f.exists()
    server.drop_key(8799)   # 無くても落ちない


UNC = ['\\\\attacker.invalid\\s\\x.nlmf', '//attacker.invalid/s/x.nlmf', '\\\\?\\UNC\\attacker.invalid\\s\\x.nlmf', 'C:\\x.nlmf',
       '..\\x.nlmf', '../x.nlmf', 'a/x.nlmf', 'x.nlmf:stream', '']


@pytest.fixture
def no_net_resolve(monkeypatch):
    """resolve に UNC・ドライブ名から始まる場所が渡ったら記録する（開きに行かない）＝名前はファイルに触る前に確かめているか"""
    seen, orig = [], Path.resolve

    def spy(self, *a, **k):
        s = str(self)
        if s.startswith(('\\\\', '//')) or '\\\\?\\' in s or 'attacker.invalid' in s:
            seen.append(s)
            return self
        return orig(self, *a, **k)
    monkeypatch.setattr(Path, 'resolve', spy)
    return seen


def test_names_checked_before_touching_files(srv, no_net_resolve):
    """受け取った名前（?file=・/static/・/audio/・指示の元・★の path）は、UNC・ドライブ名・.. を resolve より前に断る
    （前は resolve が \\\\host\\share を開きに行き、利用者の NTLM の認証を送った＝F3〜F6・F11）"""
    port, _ = srv
    for name in UNC:
        with pytest.raises(ValueError):
            server.out_file(name)
        assert _req(port, 'GET', '/api/work?file=' + _q(name))[0] == 400, name
        assert _req(port, 'GET', '/api/rating?path=' + _q(name))[0] in (400, 404), name
        assert _req(port, 'GET', '/api/workio/source?file=x.nlmf&src=' + _q(name))[0] == 400, name
    for path in ('/static/%5C%5Cattacker.invalid%5Cs%5Cx', '/static//attacker.invalid/s/x', '/static/%2F%2Fattacker.invalid%2Fs%2Fx',
                 '/audio/a/%5C%5Cattacker.invalid%5Cs%5Cx.flac', '/audio/%5C%5Cattacker.invalid%5Cs/x.flac',
                 '/audio/a/%2F%2Fattacker.invalid%2Fs%2Fx.flac'):
        assert _req(port, 'GET', path)[0] in (400, 404), path
    assert no_net_resolve == []
    assert server.plain('a.nlmf') and not server.plain('a\\b') and not server.plain('..') and not server.plain('C:x')
    assert server.rel_parts('.history/曲/曲.v1.nlmf') == ['.history', '曲', '曲.v1.nlmf'] and server.rel_parts('a//b') is None
