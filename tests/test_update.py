"""アプリの更新（app/update.py・tools/dist/launcher.cs の --apply-update）。ネットには行かない: 手元の小さな HTTP サーバーが
update.json と zip を出す（AUTOMAP_UPDATE_URL で取る場所の頭を替える＝GitHub と同じ並び）。
照合の失敗・外へ出る名前・404・新しくない版・作業の途中・起動し直した後の片付け、と差し替え役の exe（翻訳して実際に動かす）。"""
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import types
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'tools' / 'dist'))
if str(ROOT / 'tools') not in sys.path:
    sys.path.append(str(ROOT / 'tools'))   # tools/sep_install.py（NG を読む側）
from automap import config  # noqa: E402

CUR, NEW = 'v0.2.0', 'v0.3.0'


# ---- 手元の配布元（GitHub のリリースの並び: releases/latest/download/update.json・releases/download/<tag>/<zip>）----
class Releases:
    def __init__(self):
        self.files = {}     # パス → bytes（無ければ 404）
        self.slow = set()   # 少しずつ送るパス（やめるの確かめ）
        self.hits = []
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                me.hits.append(self.path)
                data = me.files.get(self.path)
                if data is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    if self.path in me.slow:
                        for i in range(0, len(data), 64 * 1024):
                            self.wfile.write(data[i:i + 64 * 1024])
                            time.sleep(0.05)
                    else:
                        self.wfile.write(data)
                except (ConnectionError, OSError):
                    pass

        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.base = f'http://127.0.0.1:{self.srv.server_address[1]}/releases/'
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def publish(self, ver, zbytes, manifest=None, **over):
        import update
        name = update.ZIP_NAME.format(version=ver)
        m = manifest or {'name': 'AutoNotePlotter', 'format': 1, 'version': ver, 'tag': ver,
                         'zip': {'name': name, 'sha256': hashlib.sha256(zbytes).hexdigest(), 'size': len(zbytes)},
                         'notes': [{'version': 'v0.3.0', 'ja': ['三つ目']}, {'version': 'v0.2.1', 'ja': ['直した']},
                                   {'version': 'v0.2.0', 'ja': ['最初']}, {'version': 'v0.1.0', 'ja': ['前']}]}
        m.update(over)
        self.files['/releases/latest/download/update.json'] = json.dumps(m).encode('utf-8') if not isinstance(m, bytes) else m
        self.files[f'/releases/download/{ver}/{name}'] = zbytes
        return f'/releases/download/{ver}/{name}'


def package(ver, entries=None, info_ver=None, mod_ver=None, drop=()):
    """配布 zip の作り物（最上位 AutoNotePlotter/ の下に exe・build-info.json・automap/version.py・runtime・app）"""
    files = {'AutoNotePlotter.exe': b'exe', 'build-info.json': json.dumps({'name': 'AutoNotePlotter', 'version': info_ver or ver}).encode(),
             'automap/version.py': f"VERSION = '{mod_ver or ver}'\n".encode(), 'runtime/python.exe': b'py', 'app/server.py': b'#',
             'data/library-dist.sqlite': b'db'}
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        for k, v in files.items():
            if k.split('/')[0] not in drop:
                z.writestr('AutoNotePlotter/' + k, v)
        for k, v in (entries or {}).items():
            z.writestr(k, v)
    return b.getvalue()


@pytest.fixture
def R():
    r = Releases()
    yield r
    r.srv.shutdown()
    r.srv.server_close()


@pytest.fixture
def U(R, monkeypatch, tmp_path):
    import server
    import update
    app = tmp_path / 'AutoNotePlotter'
    app.mkdir()
    (app / 'AutoNotePlotter.exe').write_bytes(b'old')
    monkeypatch.setenv('AUTOMAP_UPDATE_URL', R.base)
    monkeypatch.delenv('AUTOMAP_UPDATE_NO_LAUNCH', raising=False)
    monkeypatch.setenv('AUTOMAP_NO_OPEN', '1')
    spawned = []
    monkeypatch.setattr(update, '_spawn', lambda args, cwd: spawned.append((args, cwd)))
    u = update.Updater(app, distributed=True, current=CUR)
    ctx = types.SimpleNamespace(CONFIG=tmp_path / 'config.json', JOBS=server.JOBS, start_job=server.start_job, cancel_job=server.cancel_job)
    return types.SimpleNamespace(u=u, app=app, ctx=ctx, spawned=spawned, update=update, R=R, tmp=tmp_path)


def _wait(job):
    t0 = time.time()
    while job['state'] == 'running' or job.get('finishing'):
        assert time.time() - t0 < 30
        time.sleep(0.05)
    return job


def test_version_and_url(monkeypatch):
    import update
    from automap import version
    assert update.vtuple(version.VERSION) and update.vtuple('v1.2.3') == (1, 2, 3)
    assert update.vtuple('v1.2') is None and update.vtuple('v1.2.3-beta') is None and update.vtuple('1.2.3') is None
    assert version.CHANGES[0][0] == version.VERSION   # 変更点の頭は今の版（build_embed.py も確かめる）
    monkeypatch.delenv('AUTOMAP_UPDATE_URL', raising=False)
    assert update.base_url() == update.RELEASES == f'https://github.com/{update.REPO}/releases/'
    monkeypatch.setenv('AUTOMAP_UPDATE_URL', 'http://127.0.0.1:9/r')
    assert update.base_url() == 'http://127.0.0.1:9/r/'
    for bad in ('https://example.com/releases/', 'http://192.168.0.2/x/', 'http://127.0.0.1:9/x?y=1', 'file:///C:/x/'):
        monkeypatch.setenv('AUTOMAP_UPDATE_URL', bad)
        with pytest.raises(update.UpdateError) as e:
            update.base_url()
        assert e.value.code == 'badUrl'


def test_check_newer_shows_notes_between(U):
    U.R.publish(NEW, package(NEW))
    j = U.u.check()
    assert j['ok'] and j['newer'] and j['latest'] == NEW and j['current'] == CUR and j['auto'] == 'ok'
    assert [n['version'] for n in j['notes']] == ['v0.3.0', 'v0.2.1']   # 今の版より新しい分だけ・新しい順
    assert j['size'] == len(package(NEW)) and U.R.hits == ['/releases/latest/download/update.json']


@pytest.mark.parametrize('ver', ['v0.2.0', 'v0.1.9'])
def test_not_newer(U, ver):
    U.R.publish(ver, package(ver))
    j = U.u.check()
    assert j['ok'] and not j['newer']
    with pytest.raises(U.update.UpdateError) as e:
        U.u.start_download(U.ctx)
    assert e.value.code == 'noUpdate' and not (U.app / '_update').exists()


def test_check_errors(U):
    UE = U.update.UpdateError
    with pytest.raises(UE) as e:   # リリースがまだ無い（404）
        U.u.check()
    assert e.value.code == 'notFound' and '配布元にまだ' in e.value.message()
    z = package(NEW)
    good = hashlib.sha256(z).hexdigest()
    zname = f'AutoNotePlotter-{NEW}-win-x64.zip'
    bads = [b'{', {'name': 'NonLinearMapper'}, {'version': 'v0.3'}, {'zip': {'name': zname, 'sha256': 'x' * 64, 'size': len(z)}},
            {'zip': {'name': 'AutoNotePlotter-v9.9.9-win-x64.zip', 'sha256': good, 'size': len(z)}},
            {'zip': {'name': zname, 'sha256': good, 'size': 2 << 30}}, {'zip': {'name': zname, 'sha256': good, 'size': '12'}},
            {'tag': '../../evil'}, {'tag': 'v0.3.0/x'}, {'tag': 'a?b'}]
    for over in bads:
        if isinstance(over, bytes):
            U.R.publish(NEW, z)
            U.R.files['/releases/latest/download/update.json'] = over
        else:
            U.R.publish(NEW, z, **over)
        with pytest.raises(UE) as e:
            U.u.check()
        assert e.value.code == 'badManifest', over
    U.R.publish(NEW, z, format=2)   # 新しすぎる形＝自動で更新しない（配布元のページを開く）
    j = U.u.check()
    assert j['newer'] and j['auto'] == 'manual'
    with pytest.raises(UE) as e:
        U.u.start_download(U.ctx)
    assert e.value.code == 'noUpdate'


def test_manifest_urgent_and_ng_are_lenient(U):
    """format 1 に足した urgent・ng は形が違っても止めない（知っている所だけ読む＝新しい版で書き方が増えても古い版が止まらない）"""
    up = U.update
    z = package(NEW)
    U.R.publish(NEW, z, urgent={'v0.2.1': ' 脆弱性を直した ', 'v9': 'x', 'v0.2.5': 3, 'v0.3.0': True},
                ng={'app': ['v0.2.0', 'bad', 7, 'v0.1.0'], 'parts': {'torch': ['2.11.0', '<<x', 5, ' <2.0 '], '../x': ['1'], 'numpy': 'x'},
                    'why': '試し', 'new_field': {'x': 1}})
    j = U.u.check()
    m = up.check_manifest(U.R.files['/releases/latest/download/update.json'])
    assert m['urgent'] == {'v0.2.1': '脆弱性を直した', 'v0.3.0': ''}
    assert m['ng'] == {'app': ['v0.1.0', 'v0.2.0'], 'parts': {'torch': ['2.11.0', '<2.0']}, 'why': '試し'}
    import sep_install   # 控えた NG をそのまま読む側（app/setup.py が渡す）も同じ決まりを読む
    assert sep_install._ng_rules(m['ng']) == {'torch': ['2.11.0', '<2.0']}
    assert j['newer'] and j['urgent'] and j['urgent_why'] == '脆弱性を直した' and j['self_ng'] and j['ng_why'] == '試し'
    for junk in ([1], 'x', None, 5, {'app': 'v0.2.0', 'parts': [1], 'why': 3}):
        U.R.publish(NEW, z, ng=junk)
        assert U.u.check()['ok'] and up.check_manifest(U.R.files['/releases/latest/download/update.json'])['ng'] == \
            {'app': [], 'parts': {}, 'why': ''}, junk
    assert up.clean_urgent('理由', NEW) == {NEW: '理由'} and up.clean_urgent(True, NEW) == {NEW: ''}
    assert up.clean_urgent([NEW], NEW) == {} and up.clean_urgent({NEW: None}, NEW) == {} and up.clean_urgent(None, NEW) == {}
    U.R.publish(NEW, z, format=2, ng={'app': [CUR]})   # 形の版が上がって自動で更新できない版でも、NG は読む
    j = U.u.check()
    assert j['auto'] == 'manual' and j['self_ng']


def test_check_urgent_self_ng_and_remember(U):
    """確かめるたびに NG・急ぎの印を設定に控え（受け口から＝cfg_path を渡した時だけ）、ネットにつながらない起動でも控えから知らせる"""
    cfgp = U.ctx.CONFIG
    U.R.publish(NEW, package(NEW), urgent={'v0.2.1': '脆弱性を直した'}, ng={'app': [CUR], 'parts': {'torch': ['2.11.0']}, 'why': '音がずれる'})
    j = U.u.check()   # 直に呼ぶ＝控えない
    assert j['urgent'] and j['urgent_why'] == '脆弱性を直した' and j['self_ng'] and j['ng_why'] == '音がずれる' and not j['ng_changed']
    assert not cfgp.exists()
    assert U.u.check(cfgp)['ng_changed']
    saved = config.load(cfgp)['update_ng']
    assert saved['parts'] == {'torch': ['2.11.0']} and saved['app'] == [CUR] and saved['latest'] == NEW and saved['urgent'] == {'v0.2.1': '脆弱性を直した'}
    assert not U.u.check(cfgp)['ng_changed']   # 同じ＝部品の NG は変わっていない
    U.R.files.clear()   # ネットにつながらない起動
    with pytest.raises(U.update.UpdateError):
        U.u.check(cfgp)
    st = U.u.status(config.load(cfgp))
    assert st['self_ng'] and st['urgent'] and st['urgent_why'] == '脆弱性を直した' and st['known_latest'] == NEW and st['ng_at']
    assert st['ng_why'] == '音がずれる'
    # 急ぎの版が今の版そのもの・より古い＝急ぎではない。NG が外れた＝控えも外れる（最新の update.json の差し替えで消せる）
    U.R.publish(NEW, package(NEW), urgent={CUR: '前の', 'v0.1.0': 'もっと前'})
    j = U.u.check(cfgp)
    assert not j['urgent'] and not j['self_ng'] and j['ng_changed'] and config.load(cfgp)['update_ng']['parts'] == {}
    st = U.u.status(config.load(cfgp))
    assert not st['self_ng'] and not st['urgent'] and st['known_latest'] == NEW
    # 更新した後（今の版が最新）＝控えの急ぎは効かない
    newer = U.update.Updater(U.app, distributed=True, current=NEW)
    U.R.publish(NEW, package(NEW), urgent={NEW: '急ぎ'}, ng={'app': [CUR]})
    assert not newer.check(cfgp)['urgent']
    st = newer.status(config.load(cfgp))
    assert not st['urgent'] and not st['self_ng'] and st['known_latest'] is None
    # 設定が読めない時は控えない（確かめの答えは返す）
    cfgp.write_text('{', encoding='utf-8')
    assert U.u.check(cfgp)['ok']


def test_network_error(U, monkeypatch):
    import socket
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()   # 誰も待っていない番号
    monkeypatch.setenv('AUTOMAP_UPDATE_URL', f'http://127.0.0.1:{port}/releases/')
    with pytest.raises(U.update.UpdateError) as e:
        U.u.check()
    assert e.value.code == 'network' and 'インターネット' in e.value.message()


def test_download_extract_apply(U, monkeypatch):
    zpath = U.R.publish(NEW, package(NEW))
    r = U.u.start_download(U.ctx)
    job = _wait(U.ctx.JOBS[r['id']])
    assert job['state'] == 'done' and job['kind'] == 'update' and job['progress']['stage'] == 'ready', job['log']
    assert zpath in U.R.hits   # zip は releases/download/<tag>/<名前>
    new = U.app / '_update' / 'new' / 'AutoNotePlotter'
    assert (new / 'AutoNotePlotter.exe').read_bytes() == b'exe' and U.u.ready == {'version': NEW, 'dir': str(new)}
    assert not list((U.app / '_update').glob('*.part')) and U.u.check()['ready']
    assert U.u.apply(U.ctx, pid=4321) == {'ok': True, 'version': NEW}
    (args, cwd), = U.spawned
    assert args == [str(new / 'AutoNotePlotter.exe'), '--apply-update', '--target', str(U.app), '--pid', '4321'] and cwd == str(new)
    monkeypatch.setenv('AUTOMAP_UPDATE_NO_LAUNCH', '1')   # 確かめ用: 起動し直さない
    U.u.apply(U.ctx, pid=4321)
    assert U.spawned[-1][0][-1] == '--no-launch'
    assert (U.app / 'AutoNotePlotter.exe').read_bytes() == b'old'   # 差し替えは exe の役（ここでは何も変えない）


@pytest.mark.parametrize('how', ['sha', 'short', 'long'])
def test_download_hash_mismatch(U, how):
    z = package(NEW)
    sha = hashlib.sha256(z).hexdigest()
    U.R.publish(NEW, z)
    m = json.loads(U.R.files['/releases/latest/download/update.json'])
    if how == 'sha':
        m['zip']['sha256'] = hashlib.sha256(b'other').hexdigest()
    elif how == 'short':   # 配布元の情報より大きいファイルが来た
        m['zip']['size'] = len(z) - 10
    else:   # 途中で切れた（小さい）
        U.R.files[f'/releases/download/{NEW}/{m["zip"]["name"]}'] = z[:-10]
        m['zip']['sha256'] = sha
    U.R.files['/releases/latest/download/update.json'] = json.dumps(m).encode()
    job = _wait(U.ctx.JOBS[U.u.start_download(U.ctx)['id']])
    assert job['state'] == 'error' and job['error'] == 'hash' and '一致しません' in job['message']
    assert not (U.app / '_update' / 'new').exists() and not list((U.app / '_update').glob('*.part')) and U.u.ready is None
    with pytest.raises(U.update.UpdateError) as e:
        U.u.apply(U.ctx)
    assert e.value.code == 'notReady' and not U.spawned


EVIL = ['../evil.txt', 'AutoNotePlotter/../../evil.txt', '/abs.txt', 'AutoNotePlotter\\..\\evil.txt', 'Other/x.txt', 'C:/evil.txt',
        'AutoNotePlotter/./x.txt', 'AutoNotePlotter//x.txt']


@pytest.mark.parametrize('name', EVIL)
def test_zip_slip_refused(U, name, tmp_path):
    z = package(NEW, entries={name: b'evil'})
    zp = tmp_path / 'r.zip'
    zp.write_bytes(z)
    dst = tmp_path / 'x' / 'new'
    with pytest.raises(U.update.UpdateError) as e:
        U.update.extract_release(zp, dst, NEW)
    assert e.value.code == 'badZip'
    assert not dst.exists() and not (tmp_path / 'evil.txt').exists() and not (tmp_path / 'x' / 'evil.txt').exists()


def test_zip_slip_via_download(U):
    U.R.publish(NEW, package(NEW, entries={'AutoNotePlotter/../../evil.txt': b'evil'}))
    job = _wait(U.ctx.JOBS[U.u.start_download(U.ctx)['id']])
    assert job['state'] == 'error' and job['error'] == 'badZip'
    assert not (U.app / '_update' / 'new').exists() and not (U.tmp / 'evil.txt').exists() and not (U.app / 'evil.txt').exists()


@pytest.mark.parametrize('kw', [{'info_ver': 'v0.2.9'}, {'mod_ver': 'v0.2.9'}, {'drop': ('runtime',)}, {'drop': ('build-info.json',)}])
def test_package_contents_checked(U, kw, tmp_path):
    """update.json の版と中身の版（build-info.json・automap/version.py）が違う・要る物が無い＝壊れている"""
    zp = tmp_path / 'r.zip'
    zp.write_bytes(package(NEW, **kw))
    with pytest.raises(U.update.UpdateError) as e:
        U.update.extract_release(zp, tmp_path / 'new', NEW)
    assert e.value.code == 'badZip' and not (tmp_path / 'new').exists()
    U.update.extract_release(_write(tmp_path / 'ok.zip', package(NEW)), tmp_path / 'new', NEW)
    assert U.update.package_version(tmp_path / 'new' / 'AutoNotePlotter') == NEW


def _write(p, b):
    p.write_bytes(b)
    return p


def test_apply_guards(U, monkeypatch):
    UE = U.update.UpdateError
    with pytest.raises(UE) as e:
        U.u.apply(U.ctx)
    assert e.value.code == 'notReady'
    U.R.publish(NEW, package(NEW))
    _wait(U.ctx.JOBS[U.u.start_download(U.ctx)['id']])
    other = {'id': 'x', 'kind': 'generate', 'state': 'running', 'file': 'a.nlmf'}
    U.ctx.JOBS['x-update-test'] = other   # 作り直しの途中は差し替えない
    try:
        with pytest.raises(UE) as e:
            U.u.apply(U.ctx)
        assert e.value.code == 'busy' and 'generate' in e.value.detail and not U.spawned
    finally:
        U.ctx.JOBS.pop('x-update-test')
    (U.app / '_update' / 'new' / 'AutoNotePlotter' / 'build-info.json').write_text('{"version": "v0.2.9"}', encoding='utf-8')
    with pytest.raises(UE) as e:   # 展開した後に中身が変わった
        U.u.apply(U.ctx)
    assert e.value.code == 'notReady' and U.u.ready is None
    dev = U.update.Updater(U.app, distributed=False, current=CUR)   # 開発の PC は更新しない
    assert dev.auto_mode() == 'dev' and dev.status({})['distributed'] is False
    for fn in (lambda: dev.start_download(U.ctx), lambda: dev.apply(U.ctx)):
        with pytest.raises(UE) as e:
            fn()
        assert e.value.code == 'dev'
    assert U.update.Updater(U.app, distributed=False).check()['auto'] == 'dev'


def test_cancel_download(U):
    big = package(NEW, entries={'AutoNotePlotter/data/big.bin': os.urandom(3 << 20)})
    path = U.R.publish(NEW, big)
    U.R.slow.add(path)
    job = U.ctx.JOBS[U.u.start_download(U.ctx)['id']]
    t0 = time.time()
    while job['progress'].get('done', 0) == 0:
        assert time.time() - t0 < 10
        time.sleep(0.02)
    U.ctx.cancel_job(job['id'])
    _wait(job)
    assert job['state'] == 'error' and job.get('cancelled') and job['error'] == 'cancelled'
    assert not (U.app / '_update' / 'new').exists() and not list((U.app / '_update').glob('*.part')) and U.u.ready is None


def test_no_space(U, monkeypatch):
    import shutil
    U.R.publish(NEW, package(NEW))
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: types.SimpleNamespace(free=100, total=1, used=1))
    with pytest.raises(U.update.UpdateError) as e:
        U.u.start_download(U.ctx)
    assert e.value.code == 'noSpace'


def test_startup_after_update(U, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(U.tmp / 'lad'))
    w = U.app / '_update'
    (w / 'new' / 'AutoNotePlotter').mkdir(parents=True)
    (w / 'applied.json').write_text(json.dumps({'from': CUR, 'to': NEW}), encoding='utf-8')
    (w / 'apply.log').write_text('差し替えを始める\nできた\n', encoding='utf-8')
    u = U.update.Updater(U.app, distributed=True, current=NEW)
    U.update.startup(u)
    assert u.just_updated == {'from': CUR, 'to': NEW} and u.status({})['justUpdated'] == u.just_updated
    t0 = time.time()
    while w.exists():
        assert time.time() - t0 < 10
        time.sleep(0.05)
    assert 'できた' in (U.tmp / 'lad' / 'AutoNotePlotter' / 'update.log').read_text(encoding='utf-8')
    u2 = U.update.Updater(U.app, distributed=True, current=NEW)
    U.update.startup(u2)   # 片付けた後＝ふつうの起動
    assert u2.just_updated is None


def test_routes(U, monkeypatch):
    monkeypatch.setattr(U.update, 'UPDATER', U.u)
    U.u.started = True
    get, post = U.update.routes(U.ctx)
    st = get['/api/update/status']({})
    assert st['current'] == CUR and st['auto_check'] and st['skip'] is None and st['distributed']
    r = get['/api/update/check']({})   # 失敗は例外ではなく {ok: false}（起動した時は画面が黙る）
    assert r == {'ok': False, 'error': 'notFound', 'message': r['message'], 'detail': 'HTTP 404'}
    st = post['/api/update/settings']({'auto_check': False})
    assert st['auto_check'] is False and config.load(U.ctx.CONFIG)['update_check'] is False
    with pytest.raises(ValueError):
        post['/api/update/settings']({'auto_check': 'no'})
    assert post['/api/update/skip']({'version': NEW})['skip'] == NEW
    with pytest.raises(ValueError):
        post['/api/update/skip']({'version': '../x'})
    assert post['/api/update/apply']({})['error'] == 'notReady'
    assert post['/api/update/open-releases']({})['opened'] == U.update.RELEASES + 'latest'   # 開く場所は固定（画面から受け取らない）
    U.R.publish(NEW, package(NEW), ng={'app': [], 'parts': {'numpy': ['2.5.4']}, 'why': '試し'})
    assert get['/api/update/check']({})['ng_changed']   # 受け口の確かめは NG を設定に控える（準備の確かめが読む）
    assert config.load(U.ctx.CONFIG)['update_ng']['parts'] == {'numpy': ['2.5.4']}
    r = post['/api/update/download']({'url': 'http://evil/', 'version': 'v9.9.9'})   # 画面からの値は使わない
    job = _wait(U.ctx.JOBS[r['id']])
    assert r['version'] == NEW and job['state'] == 'done' and get['/api/update/status']({})['ready'] == NEW


def test_version_flags_and_refresh_manifest(U, monkeypatch, tmp_path):
    """automap/version.py の URGENT・NG → update.json の urgent・ng（build_embed.flags）・出したリリースの update.json の書き換え
    （--refresh-manifest＝zip・版・変更点はそのまま）・NG の書き方の誤り・出す版や部品の一覧が NG なら止める"""
    import build_embed
    from automap import version
    assert isinstance(version.URGENT, dict) and set(version.NG) == {'app', 'parts', 'why'}
    assert build_embed.flags(version.VERSION) == (U.update.clean_urgent(version.URGENT, version.VERSION), U.update.clean_ng(version.NG))
    monkeypatch.setattr(version, 'URGENT', {'v0.2.1': '急ぎ'})
    monkeypatch.setattr(version, 'NG', {'app': ['v0.2.0'], 'parts': {'torch': ['2.11.0+cu126']}, 'why': '試し'})
    U.R.publish(CUR, package(CUR))
    src = tmp_path / 'update.json'
    src.write_bytes(U.R.files['/releases/latest/download/update.json'])
    dst, data = build_embed.refresh_manifest(src, tmp_path / 'new.json')
    m = U.update.check_manifest(dst.read_bytes())
    old = U.update.check_manifest(src.read_bytes())
    assert m['ng'] == {'app': ['v0.2.0'], 'parts': {'torch': ['2.11.0+cu126']}, 'why': '試し'} and m['urgent'] == {}   # 出した版より新しい印は書かない
    assert (m['version'], m['zip'], m['notes']) == (old['version'], old['zip'], old['notes'])
    with pytest.raises(SystemExit, match='NG の app'):
        build_embed.flags('v0.2.0')   # 出す版そのものが NG
    with pytest.raises(SystemExit, match='部品の一覧'):
        monkeypatch.setattr(version, 'NG', {'app': [], 'parts': {'torch': ['2.11.0+cu126']}, 'why': ''})
        build_embed.flags('v0.2.1')   # 出す版の音を分ける部品の一覧に NG の版がある
    for bad in ({'app': ['0.2.0'], 'parts': {}, 'why': ''}, {'app': [], 'parts': {'torch': '2.11.0'}, 'why': ''}, {'apps': []}):
        monkeypatch.setattr(version, 'NG', bad)
        with pytest.raises(SystemExit, match='NG'):
            build_embed.flags()
    monkeypatch.setattr(version, 'NG', {'app': [], 'parts': {}, 'why': ''})
    monkeypatch.setattr(version, 'URGENT', {'0.2.1': 'x'})
    with pytest.raises(SystemExit, match='URGENT'):
        build_embed.flags()


def test_launcher_constants_match():
    """差し替える物の一覧・置き場所の名前が app/update.py と launcher.cs で同じ（片方だけ直すと、更新で物が残る・消える）"""
    import re
    import update
    cs = (ROOT / 'tools' / 'dist' / 'launcher.cs').read_text(encoding='utf-8')
    items = re.search(r'ReplaceItems\s*=\s*\{(.*?)\};', cs, re.S).group(1)
    names = [update.EXE_NAME if x.strip() == 'Launcher.ExeName' else x.strip().strip('"') for x in items.split(',')]
    assert tuple(names) == update.REPLACE_ITEMS
    consts = dict(re.findall(r'const string (\w+) = "([^"]*)";', cs))
    assert consts['ExeName'] == update.EXE_NAME and consts['ZipTop'] == update.ZIP_TOP
    assert consts['UpdateDir'] == update.UPDATE_DIR and consts['PrevPrefix'] == update.PREV_PREFIX
    assert '"--apply-update"' in cs and '"--target"' in cs and '"--pid"' in cs


# ---- 差し替え役の exe（launcher.cs を翻訳して実際に動かす）----
CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
needs_csc = pytest.mark.skipif(sys.platform != 'win32' or not CSC.exists(), reason='.NET Framework 4 の csc.exe が要る')

MARKER_CS = r'''
using System; using System.IO;
static class M { static int Main(string[] a) {
  File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ran.txt"),
    string.Join("|", a) + "|nousersite=" + Environment.GetEnvironmentVariable("PYTHONNOUSERSITE"));
  return 0; } }
'''


@pytest.fixture(scope='module')
def exes(tmp_path_factory):
    if sys.platform != 'win32' or not CSC.exists():
        pytest.skip('.NET Framework 4 の csc.exe が要る')
    import build_embed
    d = tmp_path_factory.mktemp('exes')
    build_embed.compile_launcher(d / 'AutoNotePlotter.exe', quiet=True)
    (d / 'marker.cs').write_text(MARKER_CS, encoding='utf-8')
    subprocess.run([str(CSC), '/nologo', '/target:winexe', f'/out:{d / "marker.exe"}', str(d / 'marker.cs')], check=True, capture_output=True)
    return d


def _tree(root, files):
    for k, v in files.items():
        p = root / k
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(v, bytes):
            p.write_bytes(v)
        else:
            p.write_text(v, encoding='utf-8')


def _layout(exes, tmp_path):
    """アプリのフォルダ（古い版 v0.2.0）と、_update/new/AutoNotePlotter/ に展開した新しい版（v0.3.0）"""
    t = tmp_path / 'アプリ AutoNotePlotter'   # 日本語と空白の入った場所
    launcher, marker = (exes / 'AutoNotePlotter.exe').read_bytes(), (exes / 'marker.exe').read_bytes()
    _tree(t, {'AutoNotePlotter.exe': launcher, 'runtime/pythonw.exe': marker, 'runtime/old.txt': 'old', 'app/desktop.py': 'old',
              'automap/version.py': f"VERSION = '{CUR}'\n", 'build-info.json': json.dumps({'version': CUR}), 'LICENSE': 'old',
              'keep.txt': '利用者の物', '_previous_v0.1.0/app/x.py': 'older'})
    src = t / '_update' / 'new' / 'AutoNotePlotter'
    _tree(src, {'AutoNotePlotter.exe': launcher, 'runtime/pythonw.exe': marker, 'runtime/new.txt': 'new', 'app/desktop.py': 'new',
                'automap/version.py': f"VERSION = '{NEW}'\n", 'build-info.json': json.dumps({'version': NEW}), 'data/lib.sqlite': 'db',
                'THIRD_PARTY_NOTICES.md': 'n'})
    return t, src


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file() and '_update' not in p.parts}


@needs_csc
def test_launcher_apply_waits_and_replaces(exes, tmp_path):
    t, src = _layout(exes, tmp_path)
    holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1.5)'])   # 終わるのを待つ「古いアプリ」
    t0 = time.time()
    r = subprocess.run([str(src / 'AutoNotePlotter.exe'), '--apply-update', '--target', str(t), '--pid', str(holder.pid), '--quiet', '--no-launch'],
                       timeout=90)
    took = time.time() - t0
    holder.wait()
    assert r.returncode == 0 and took >= 1.0   # 古いアプリが終わるまで待った
    assert (t / 'runtime' / 'new.txt').exists() and not (t / 'runtime' / 'old.txt').exists()
    assert (t / 'app' / 'desktop.py').read_text(encoding='utf-8') == 'new' and (t / 'data' / 'lib.sqlite').exists()
    assert json.loads((t / 'build-info.json').read_text(encoding='utf-8'))['version'] == NEW
    assert (t / 'keep.txt').read_text(encoding='utf-8') == '利用者の物'   # 決めた物以外は触らない
    bk = t / '_previous_v0.2.0'   # 前の版は 1 世代だけ残す
    assert (bk / 'runtime' / 'old.txt').exists() and (bk / 'LICENSE').exists() and (bk / 'AutoNotePlotter.exe').exists()
    assert not (t / '_previous_v0.1.0').exists() and not (t / 'LICENSE').exists()   # 新しい版に無い物は退避したまま
    assert json.loads((t / '_update' / 'applied.json').read_text(encoding='utf-8')) == {'from': CUR, 'to': NEW}
    assert 'できた' in (t / '_update' / 'apply.log').read_text(encoding='utf-8')
    assert not (t / 'runtime' / 'ran.txt').exists()   # --no-launch＝起動し直さない


@needs_csc
def test_launcher_relaunches(exes, tmp_path):
    """差し替えた後、アプリのフォルダの AutoNotePlotter.exe（新しい版）→ runtime\\pythonw.exe app\\desktop.py の順に起動し直す"""
    t, src = _layout(exes, tmp_path)
    r = subprocess.run([str(src / 'AutoNotePlotter.exe'), '--apply-update', '--target', str(t), '--pid', '0', '--quiet'], timeout=90)
    assert r.returncode == 0
    ran = t / 'runtime' / 'ran.txt'
    t0 = time.time()
    while not ran.exists():
        assert time.time() - t0 < 20
        time.sleep(0.1)
    text = ran.read_text(encoding='utf-8')
    assert text.startswith(str(t / 'app' / 'desktop.py')) and text.endswith('nousersite=1')


@needs_csc
def test_launcher_refuses_other_places(exes, tmp_path):
    """自分が <target>\\_update\\new\\AutoNotePlotter にいない時は何もしない（ほかのフォルダを書き換えさせない）"""
    t, src = _layout(exes, tmp_path)
    before = _snapshot(t)
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'AutoNotePlotter.exe').write_bytes((exes / 'AutoNotePlotter.exe').read_bytes())
    for exe, target in ((other / 'AutoNotePlotter.exe', t), (src / 'AutoNotePlotter.exe', tmp_path / 'nothing'), (src / 'AutoNotePlotter.exe', other)):
        r = subprocess.run([str(exe), '--apply-update', '--target', str(target), '--pid', '0', '--quiet', '--no-launch'], timeout=60)
        assert r.returncode == 2
    (src / 'build-info.json').write_text('{"version": "0.3"}', encoding='utf-8')   # 新しい版の中身が読めない
    r = subprocess.run([str(src / 'AutoNotePlotter.exe'), '--apply-update', '--target', str(t), '--pid', '0', '--quiet', '--no-launch'], timeout=60)
    assert r.returncode == 2 and _snapshot(t) == before and not (t / '_update' / 'applied.json').exists()


@needs_csc
def test_launcher_rolls_back(exes, tmp_path):
    """置いている途中で失敗したら（新しい版の app\\ を掴まれていて移せない）、退避した古い版を戻して元のまま"""
    t, src = _layout(exes, tmp_path)
    before = _snapshot(t)
    with open(src / 'app' / 'desktop.py', 'rb'):   # 開いている間はフォルダを移せない
        r = subprocess.run([str(src / 'AutoNotePlotter.exe'), '--apply-update', '--target', str(t), '--pid', '0', '--quiet', '--no-launch'],
                           timeout=120)
    assert r.returncode == 1
    after = _snapshot(t)
    assert after == {k: v for k, v in before.items() if not k.startswith('_previous_v0.1.0/')}   # 古い版のまま（前の退避は消えてよい）
    assert not (t / '_previous_v0.2.0').exists() and not (t / '_update' / 'applied.json').exists()
    assert (src / 'runtime' / 'new.txt').exists()   # 途中まで置いた新しい版は展開した場所へ戻した
    assert '戻す' in (t / '_update' / 'apply.log').read_text(encoding='utf-8')
