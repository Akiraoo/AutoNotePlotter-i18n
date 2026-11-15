"""準備と設定（app/setup.py・automap/config.py）: 設定の置き場所・起動のたびの確かめ・作業の場所・音を分ける部品（入れる作業・続きから）"""
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
from automap import config  # noqa: E402


def test_config_path_and_update(monkeypatch, tmp_path):
    p = tmp_path / 'c.json'
    monkeypatch.setenv('AUTOMAP_CONFIG', str(p))
    assert config.path() == p and config.load() == {}
    p.write_bytes(b'{\r\n "nlm_exe": "x",\r\n "keep": [1]\r\n}\r\n')
    cfg = config.update({'work_dir': str(tmp_path / 'w'), 'nlm_exe': None})
    raw = p.read_bytes().decode('utf-8')
    assert cfg == {'keep': [1], 'work_dir': str(tmp_path / 'w')} and json.loads(raw) == cfg
    assert raw.count('\r\n') == raw.count('\n') and not list(tmp_path.glob('*.tmp'))   # 行の終わりはそのまま・一時ファイルは残さない
    assert config.out_dir() == tmp_path / 'w' / 'out' and config.cache_dir() == tmp_path / 'w' / 'cache'
    assert config.out_dir({}) == ROOT / 'out'   # 作業の場所が無い＝リポジトリの out/（開発の PC）
    p.write_text('{', encoding='utf-8')
    with pytest.raises(ValueError, match='読めない'):
        config.update({'a': 1})
    monkeypatch.delenv('AUTOMAP_CONFIG')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'lad'))
    monkeypatch.setattr(config, 'DEV', tmp_path / 'none.json')
    assert config.path() == tmp_path / 'lad' / 'AutoNotePlotter' / 'config.json'   # 配布物＝使う人ごとの場所


class FakeSep:
    """tools/sep_install.py の代わり（check・set_ng・plan・python_exe・run_env）"""
    def __init__(self):
        self.done = set()
        self.ngs = []      # check・set_ng に渡された NG（設定の update_ng）
        self.bad = []      # set_ng の答え（確かめた組の中の NG）

    def check(self, d, ng=None):
        self.ngs.append(ng)
        if d in self.done:
            return {'ok': True, 'missing': [], 'variant': 'cpu', 'python': str(Path(d) / 'python' / 'python.exe'), 'resume': None,
                    'stage': 'none'}
        return {'ok': False, 'missing': ['torch がまだ'], 'variant': None, 'resume': {'stage': 'torch', 'done': 5, 'total': 10},
                'stage': 'required'}

    def set_ng(self, variant=None, ng=None):
        self.ngs.append(ng)
        return list(self.bad)

    def plan(self, d, variant=None, runtime=None):
        return {'dir': d, 'variant': variant or 'cpu', 'items': []}

    def python_exe(self, d):
        return str(Path(d) / 'python' / 'python.exe')

    def _popen(self, cmd, **kw):   # 本物はアプリが止まったら一緒に止まる Windows のジョブに入れる
        import subprocess
        return subprocess.Popen(cmd, **kw)

    def run_env(self, d, base=None):
        return dict(base or {}, HF_HOME=str(Path(d) / 'hf'), HF_HUB_OFFLINE='1')


@pytest.fixture
def S(monkeypatch, tmp_path):
    import server
    import setup
    fake = FakeSep()
    monkeypatch.setattr(setup, '_sep_mod', lambda: fake)
    monkeypatch.setattr(setup, 'library_state', lambda: {'ok': True, 'path': 'x', 'dist': True})
    rat = {'ok': True, 'path': 'nlm-rating.exe', 'version': '0.2.0', 'bundled': True}
    monkeypatch.setattr(setup, 'rating_state', lambda: dict(rat))
    monkeypatch.setattr(setup, 'DEV_SEP', tmp_path / 'no-venv-sep' / 'python.exe')
    monkeypatch.setattr(config, 'distributed', lambda: True)
    monkeypatch.delenv('NLM_EXE', raising=False)
    ctx = types.SimpleNamespace(CONFIG=tmp_path / 'config.json', JOBS=server.JOBS, start_job=server.start_job,
                                OUT=tmp_path / 'out0', CACHE=tmp_path / 'cache0')
    return types.SimpleNamespace(setup=setup, fake=fake, ctx=ctx, tmp=tmp_path, server=server)


def test_status_first_run_and_settings(S):
    """配布物の初回: 作業の場所・音を分ける部品が無い＝設定画面を出す。作業の場所を決めると out/・cache/ を作り、作り直しもそこへ"""
    st = S.setup.status(S.ctx)
    assert st['need_setup'] and not st['ready'] and not st['work']['ok'] and not st['sep']['ok'] and st['library']['ok']
    assert st['default_sep'].endswith(str(Path('AutoNotePlotter') / 'parts' / 'separate'))
    w = S.tmp / 'ワーク'
    st = S.setup.set_settings(S.ctx, {'work_dir': str(w)})
    assert st['work']['ok'] and (w / 'out').is_dir() and (w / 'cache').is_dir()
    assert S.ctx.OUT == w / 'out' and S.ctx.CACHE == w / 'cache'
    assert st['default_sep'] == str(w / 'parts' / 'separate')
    for bad in ('', 'relative/dir'):
        with pytest.raises(ValueError):
            S.setup.set_settings(S.ctx, {'work_dir': bad})
    with pytest.raises(ValueError, match='NLM'):
        S.setup.set_settings(S.ctx, {'nlm_exe': str(S.tmp / 'no.exe')})
    exe = S.tmp / 'NLM.exe'
    exe.write_bytes(b'')
    assert S.setup.set_settings(S.ctx, {'nlm_exe': str(exe)})['nlm']['ok']
    assert S.setup.set_settings(S.ctx, {'nlm_exe': ''})['nlm']['path'] is None   # 空＝外す
    for key in ('nlm_exe', 'nlm_rating_exe'):   # ネットワークの場所の exe は、ファイルに触る前に断る（F12）
        for unc in ('\\\\attacker.invalid\\s\\x.exe', '//attacker.invalid/s/x.exe'):
            with pytest.raises(ValueError, match='この PC のドライブ'):
                S.setup.set_settings(S.ctx, {key: unc})


def test_sep_pending_resume_and_runner(S):
    """入れている途中で止まった＝続きから（pending）・揃えば sep_runner がパックの python と環境変数を返す"""
    S.setup.set_settings(S.ctx, {'work_dir': str(S.tmp / 'w')})
    with pytest.raises(RuntimeError, match='準備と設定'):
        S.setup.sep_runner(S.ctx)
    d = str(S.tmp / 'w' / 'parts' / 'separate')
    config.update({'sep_pending': {'dir': d, 'variant': 'cpu'}}, S.ctx.CONFIG)
    st = S.setup.status(S.ctx)['sep']
    assert not st['ok'] and st['pending']['dir'] == d and st['resume']['stage'] == 'torch'
    S.fake.done.add(d)
    config.update({'sep_dir': d, 'sep_variant': 'cpu', 'sep_pending': None}, S.ctx.CONFIG)
    st = S.setup.status(S.ctx)
    assert st['ready'] and st['need_setup']        # 揃ったが初回の設定画面はまだ終えていない
    py, env, variant = S.setup.sep_runner(S.ctx)
    assert py == Path(d) / 'python' / 'python.exe' and env['HF_HUB_OFFLINE'] == '1' and variant == 'cpu'
    assert S.setup.routes(S.ctx)[1]['/api/setup/done']({})['need_setup'] is False
    S.fake.done.clear()   # 次に開いた時に部品が消えていた＝また設定画面（入れ直しの案内）
    st = S.setup.status(S.ctx)
    assert st['need_setup'] and not st['sep']['ok'] and st['sep']['missing']
    S.fake.done.add(d)
    S.setup.rating_state = lambda: {'ok': False, 'path': None, 'why': '無い'}   # ★を測る部品も必須（2026-11-03 利用者）
    st = S.setup.status(S.ctx)
    assert not st['ready'] and st['need_setup'] and st['sep']['ok']


def test_ng_passed_to_check_and_install_refused(S):
    """設定に控えた使ってはいけない版（app/update.py の update_ng）を部品の確かめに渡す。確かめた組そのものが NG ならインストールを断る"""
    import update
    assert S.setup.NG_KEY == update.NG_KEY
    S.setup.set_settings(S.ctx, {'work_dir': str(S.tmp / 'w')})
    d = str(S.tmp / 'w' / 'parts' / 'separate')
    ng = {'app': [], 'parts': {'torch': ['2.11.0']}, 'why': '音がずれる', 'at': '2026-11-03T09:00:00'}
    config.update({'sep_dir': d, 'sep_variant': 'cpu', 'update_ng': ng}, S.ctx.CONFIG)
    st = S.setup.status(S.ctx)
    assert S.fake.ngs[-1] == ng and st['ng'] == {'why': '音がずれる', 'at': '2026-11-03T09:00:00'}
    plan = S.setup.routes(S.ctx)[0]['/api/setup/plan']({'dir': d, 'variant': 'cpu'})
    assert plan['ng_set'] == []
    S.fake.bad = [{'key': 'torch-cpu', 'name': 'torch', 'version': '2.11.0+cpu'}]
    assert S.setup.routes(S.ctx)[0]['/api/setup/plan']({'dir': d, 'variant': 'cpu'})['ng_set'] == S.fake.bad
    with pytest.raises(ValueError, match='アプリを新しい版に更新'):
        S.setup.start_install(S.ctx, {'dir': d, 'variant': 'cpu'})
    assert 'sep_pending' not in config.load(S.ctx.CONFIG)   # 断った時は何も書かない
    config.update({'update_ng': None}, S.ctx.CONFIG)
    assert S.setup.status(S.ctx)['ng'] is None and S.fake.ngs[-1] is None


def _real_pack(si, d, variant='cpu'):
    """本物の tools/sep_install.py が「揃っている」と見るパックの作り物（中身は空のファイル）"""
    site = si._site(d)
    (d / 'python').mkdir(parents=True)
    (d / 'python' / 'python.exe').write_bytes(b'')
    for f in [si.FILES[f'torch-{variant}'], *si._lib_files()]:
        name = 'torch' if f['name'] == 'torch' else si._norm(f['name'])
        di = site / f'{name}-{f["version"]}.dist-info'
        di.mkdir(parents=True)
        (di / 'RECORD').write_text(f'{di.name}/RECORD,,\n')
    for k in si.KEY_FILES:
        (site / k).parent.mkdir(parents=True, exist_ok=True)
        (site / k).write_bytes(b'x')
    snap = si._snapshot(d)
    snap.mkdir(parents=True)
    for w in si.WEIGHTS:
        (snap / w['file']).write_bytes(b'w' * w['size'])
    (snap.parent.parent / 'refs').mkdir()
    (snap.parent.parent / 'refs' / 'main').write_text(si.HF_REV)
    si._write_json(d / 'installed.json', {'format': si.PACK_FORMAT, 'lock': si.LOCK_ID, 'variant': variant, 'python': '3.14.10',
                                          'installed_at': '2026-11-03T00:00:00', 'verify': {'warnings': []}})


def test_status_with_real_check_and_ng(S, monkeypatch):
    """本物の sep_install.check で: 控えた NG が入っている部品に当たれば止める（確かめた組そのもの＝アプリの更新が要る）・
    違う版でも最低の版以上で NG でなければ揃っている扱い（おすすめ）"""
    import sep_install as si
    monkeypatch.setattr(S.setup, '_sep_mod', lambda: si)
    monkeypatch.setattr(si, 'WEIGHTS', [{'file': 'htdemucs_ft.yaml', 'url': 'http://x/y', 'size': 5, 'sha256': '0' * 64}])
    S.setup.set_settings(S.ctx, {'work_dir': str(S.tmp / 'w')})
    d = S.tmp / 'w' / 'parts' / 'separate'
    _real_pack(si, d)
    config.update({'sep_dir': str(d), 'sep_variant': 'cpu', 'setup_done': True}, S.ctx.CONFIG)
    st = S.setup.status(S.ctx)
    assert st['ready'] and not st['need_setup'] and st['sep']['stage'] == 'none'
    f = si.FILES['lib-einops']
    monkeypatch.setattr(si, 'FILES', dict(si.FILES, **{'lib-einops': dict(f, version='0.8.3', file=f['file'].replace('0.8.2', '0.8.3'))}))
    st = S.setup.status(S.ctx)
    assert st['ready'] and not st['need_setup'] and st['sep']['stage'] == 'recommended' and st['sep']['update_bytes'] > 0
    config.update({'update_ng': {'app': [], 'parts': {'numpy': ['2.5.4']}, 'why': '試し'}}, S.ctx.CONFIG)
    st = S.setup.status(S.ctx)
    assert not st['ready'] and st['need_setup'] and st['sep']['stage'] == 'required' and st['sep']['app_update']
    with pytest.raises(RuntimeError, match='アプリを更新'):   # 取り込みも止まる
        S.setup.sep_runner(S.ctx)
    with pytest.raises(ValueError, match='numpy 2.5.4'):
        S.setup.start_install(S.ctx, {'dir': str(d), 'variant': 'cpu'})


def test_dev_pc_uses_venv_sep(S, monkeypatch):
    """開発の PC（配布物でない・.venv-sep がある・設定が無い）は何も聞かずにそのまま"""
    monkeypatch.setattr(config, 'distributed', lambda: False)
    dev = S.tmp / 'venv-sep' / 'Scripts' / 'python.exe'
    dev.parent.mkdir(parents=True)
    dev.write_bytes(b'')
    monkeypatch.setattr(S.setup, 'DEV_SEP', dev)
    st = S.setup.status(S.ctx)
    assert st['ready'] and not st['need_setup'] and st['sep']['kind'] == 'dev' and st['work'].get('dev')
    assert S.setup.sep_runner(S.ctx) == (dev, None, 'dev')


FAKE_INSTALL = r'''
import json, sys, time
for i in range(3):
    print(json.dumps({'stage': 'torch', 'label': 'PyTorch を取る', 'done': i, 'total': 2, 'msg': f'{i}/2'}), flush=True)
    time.sleep(0.05)
if sys.argv[1] == 'fail':
    print(json.dumps({'error': 'ネットにつながらない'}), flush=True)
    sys.exit(1)
print(json.dumps({'stage': 'done'}), flush=True)
'''


def _wait(job):
    t0 = time.time()
    while job['state'] == 'running' or job.get('finishing'):
        assert time.time() - t0 < 30
        time.sleep(0.05)
    return job


def test_install_job(S, monkeypatch):
    """入れる作業: 進み具合（progress）を作業に出し、終われば設定に sep_dir・失敗なら続きから（sep_pending が残る）"""
    script = S.tmp / 'fake_install.py'
    script.write_text(FAKE_INSTALL, encoding='utf-8')
    S.setup.set_settings(S.ctx, {'work_dir': str(S.tmp / 'w')})
    d = S.tmp / 'w' / 'parts' / 'separate'
    monkeypatch.setattr(S.setup, 'install_cmd', lambda d, v: [sys.executable, script, 'fail'])
    job = _wait(S.ctx.JOBS[S.setup.start_install(S.ctx, {'dir': str(d), 'variant': 'cpu'})['id']])
    assert job['state'] == 'error' and 'ネットにつながらない' in job['log'] and job['progress']['stage'] == 'torch'
    cfg = config.load(S.ctx.CONFIG)
    assert cfg['sep_pending'] == {'dir': str(d), 'variant': 'cpu'} and 'sep_dir' not in cfg
    monkeypatch.setattr(S.setup, 'install_cmd', lambda d, v: [sys.executable, script, 'ok'])
    job = _wait(S.ctx.JOBS[S.setup.start_install(S.ctx, {'dir': str(d), 'variant': 'cpu'})['id']])
    assert job['state'] == 'done' and job['kind'] == 'setup' and 'PyTorch を取る: 2/2' in job['log']
    cfg = config.load(S.ctx.CONFIG)
    assert cfg['sep_dir'] == str(d) and cfg['sep_variant'] == 'cpu' and 'sep_pending' not in cfg
    with pytest.raises(ValueError, match='ドライブ名'):
        S.setup.start_install(S.ctx, {'dir': 'parts', 'variant': 'cpu'})
