"""tools/sep_install.py（音を分ける部品を入れる道具・MIT）の約束。ネットに行かない（取るのは 127.0.0.1 の小さなサーバーから）・数秒"""
import ast
import hashlib
import http.server
import importlib.util
import json
import os
import re
import sys
import threading
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'sep_install.py'
_spec = importlib.util.spec_from_file_location('sep_install', TOOL)
si = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(si)


# ---------------------------------------------------------------- ライセンス・読み込む物・一覧

def test_mit_header_and_stdlib_only():
    src = TOOL.read_text(encoding='utf-8')
    assert src.startswith('# SPDX-License-Identifier: MIT\n')
    head = (ROOT / 'tools' / 'separate.py').read_text(encoding='utf-8').split('"""', 1)[0]
    assert src.split('"""', 1)[0] == head          # tools/separate.py と同じ MIT の頭
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            mods.add(n.module.split('.')[0])
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)   # 本体（automap・app）も外の部品も読まない


def _pins():
    pins = {}
    for ln in (ROOT / 'requirements-sep.txt').read_text(encoding='utf-8').splitlines():
        m = re.match(r'([A-Za-z0-9_.\-]+)==([^\s#]+)', ln)
        if m:
            pins[si._norm(m[1])] = m[2]
    return pins


def test_lock_matches_requirements_sep():
    pins = _pins()
    assert pins['torch'] == f'{si.TORCH}+cu128'
    assert pins['demucs'] == si.DEMUCS
    for name, ver in si.LIBS:
        assert pins[si._norm(name)] == ver, name
    leftover = set(pins) - {si._norm(n) for n, _ in si.LIBS} - {'torch', 'torchaudio'}
    assert not leftover          # requirements-sep.txt の部品は全部入れる（torchaudio は要らない）


def test_lock_entries():
    hosts = {'download.pytorch.org', 'files.pythonhosted.org', 'huggingface.co'}
    for v in si.VARIANTS:
        f = si.FILES[f'torch-{v}']
        assert f['version'] == f'{si.TORCH}+{v}' and f['file'].endswith('-cp314-cp314-win_amd64.whl')
    for name, ver in si.LIBS + [si.PIP]:
        assert any(f['name'] == name and f['version'] == ver for f in si.FILES.values()), name
    for f in list(si.FILES.values()) + si.WEIGHTS:
        assert re.fullmatch(r'[0-9a-f]{64}', f['sha256']) and f['size'] > 0
        assert f['url'].startswith('https://') and f['url'].split('/')[2] in hosts
        assert '/' not in f['file']
    assert si.WEIGHTS[0]['file'] == f'{si.MODEL}.yaml' and len(si.WEIGHTS) == 5
    assert all(si.HF_REV in w['url'] for w in si.WEIGHTS)
    assert all(si.SIZES[k] > 0 for k in si.SIZES)


def test_tag_rank():
    assert si._tag_rank('numpy-2.5.4-cp314-cp314-win_amd64.whl') == 0
    assert si._tag_rank('numpy-2.5.4-cp314-cp314t-win_amd64.whl') is None       # 自由スレッド版は入らない
    assert si._tag_rank('safetensors-0.8.0-cp310-abi3-win_amd64.whl') == 1
    assert si._tag_rank('soundfile-0.14.0-py2.py3-none-win_amd64.whl') == 2
    assert si._tag_rank('demucs-4.1.0-py3-none-any.whl') == 3
    assert si._tag_rank('x-1.0-cp313-cp313-win_amd64.whl') is None
    assert si._tag_rank('x-1.0-cp314-cp314-manylinux_2_17_x86_64.whl') is None


# ---------------------------------------------------------------- GPU

def _info(cuda=(13, 0), cc=(8, 9), mem=12 << 30, driver='610.88', name='GeForce RTX 4070 SUPER'):
    return {'driver': driver, 'cuda': cuda, 'gpus': [{'name': name, 'cc': cc, 'mem': mem}]}


@pytest.mark.parametrize('info,want', [
    (None, 'cpu'),
    ({'driver': None, 'cuda': None, 'gpus': []}, 'cpu'),
    (_info(), 'cu128'),
    (_info(cuda=(12, 8)), 'cu128'),
    (_info(cuda=(12, 6)), 'cu126'),                         # ドライバーが CUDA 12.8 に足りない
    (_info(cuda=(12, 2)), 'cpu'),                           # 古いドライバー
    (_info(cc=(6, 1), name='GTX 1080'), 'cu126'),           # Pascal は cu128 の torch が対応していない
    (_info(cc=(3, 5), name='GTX 780'), 'cpu'),
    (_info(cc=(12, 0), cuda=(12, 6), name='RTX 5080'), 'cpu'),   # Blackwell は cu126 が対応していない＝ドライバーを新しくする
    (_info(mem=2 << 30, name='GTX 1050'), 'cpu'),           # メモリが少ない
    (_info(cuda=None, driver='572.16'), 'cu128'),           # CUDA の版が分からなければドライバーの版から
    (_info(cuda=None, driver='561.09'), 'cu126'),
    (_info(cuda=None, driver=None), 'cpu'),
])
def test_choose(info, want):
    v, why = si._choose(info)
    assert v == want and why


def test_detect_gpu_without_nvidia(monkeypatch):
    monkeypatch.setattr(si, '_nvml', lambda: None)
    monkeypatch.setattr(si, '_smi', lambda: None)
    g = si.detect_gpu()
    assert g['nvidia'] is False and g['variant'] == 'cpu' and 'NVIDIA' in g['why'] and g['how'] is None


def test_detect_gpu_uses_smi_when_no_nvml(monkeypatch):
    monkeypatch.setattr(si, '_nvml', lambda: None)
    monkeypatch.setattr(si, '_smi', lambda: _info())
    g = si.detect_gpu()
    assert g == g | {'nvidia': True, 'variant': 'cu128', 'cuda': '13.0', 'cc': '8.9', 'how': 'nvidia-smi'}


# ---------------------------------------------------------------- plan

@pytest.fixture
def gpu(monkeypatch):
    monkeypatch.setattr(si, 'detect_gpu', lambda: {'nvidia': False, 'name': None, 'driver': None, 'cuda': None, 'cc': None,
                                                   'mem': None, 'variant': 'cpu', 'why': 'テスト', 'how': None})


def test_plan_offline(tmp_path, gpu):
    p = si.plan(tmp_path / 'sep', online=False)
    assert p['variant'] == 'cpu' and p['estimated'] and not p['online']
    keys = [i['key'] for i in p['items']]
    assert keys == ['python', 'torch', 'libs', 'pip', 'weights']
    assert all(i['what'] and i['name'] and i['source'] for i in p['items'])
    assert p['download_bytes'] == sum(i['download'] for i in p['items']) == (
        si.FILES['torch-cpu']['size'] + sum(f['size'] for f in si._lib_files()) + si.FILES['pip']['size'] + sum(w['size'] for w in si.WEIGHTS))
    assert p['install_bytes'] == si.SIZES['python'] + si.SIZES['libs'] + si.SIZES['torch-cpu'] + sum(w['size'] for w in si.WEIGHTS)
    assert p['peak_bytes'] > p['install_bytes'] and p['need_bytes'] >= p['peak_bytes']
    assert p['enough'] == (p['free_bytes'] >= p['need_bytes'])
    assert p['state']['ok'] is False
    json.dumps(p, ensure_ascii=False)      # そのまま画面へ渡せる
    g = si.plan(tmp_path / 'sep', 'cu128', online=False)
    assert g['download_bytes'] > 2.5e9 and g['install_bytes'] > 4e9 and 'GPU' in g['items'][1]['name']


def test_plan_not_enough_space(tmp_path, gpu, monkeypatch):
    monkeypatch.setattr(si, '_free_bytes', lambda d: 100 * 1000 * 1000)
    p = si.plan(tmp_path, online=False)
    assert not p['enough'] and any('空き容量が足りない' in x for x in p['problems'])


def test_plan_path_too_long(tmp_path, gpu, monkeypatch):
    monkeypatch.setattr(si, '_long_paths', lambda: False)
    assert si._path_problem(Path('C:/ANP/sep')) is None
    p = si.plan(tmp_path / ('x' * 150), online=False)
    assert any('長すぎる' in x for x in p['problems'])
    monkeypatch.setattr(si, '_long_paths', lambda: True)
    assert si._path_problem(tmp_path / ('x' * 150)) is None


def test_plan_online_sizes(tmp_path, gpu, monkeypatch):
    sizes = {f['url']: f['size'] for f in si.FILES.values()} | {w['url']: w['size'] for w in si.WEIGHTS}
    odd = si.FILES['lib-numpy']['url']
    monkeypatch.setattr(si, '_head', lambda url, timeout: sizes[url] + (1 if url == odd else 0))
    p = si.plan(tmp_path, online=True)
    assert p['online'] and not p['estimated']
    assert any('numpy' in w for w in p['warnings'])

    def down(url, timeout):
        raise si.urllib.error.URLError('つながらない')
    monkeypatch.setattr(si, '_head', down)
    p = si.plan(tmp_path, online=True)
    assert not p['online'] and p['estimated']


# ---------------------------------------------------------------- check（作り物のパック）

SMALL_W = [{'file': 'htdemucs_ft.yaml', 'url': 'http://x/y', 'size': 5, 'sha256': '0' * 64},
           {'file': 'a.safetensors', 'url': 'http://x/a', 'size': 7, 'sha256': '0' * 64}]


def _fake_pkg(site, f, tops=None):
    name = re.sub(r'[-_.]+', '_', f['name']).lower() if f['name'] != 'torch' else 'torch'
    di = site / f'{name}-{f["version"]}.dist-info'
    di.mkdir(parents=True, exist_ok=True)
    (di / 'METADATA').write_text(f'Name: {f["name"]}\n')
    rec = [f'{di.name}/METADATA,,']
    for t in tops or [name]:
        (site / t).mkdir(parents=True, exist_ok=True)
        (site / t / '__init__.py').write_text('')
        rec.append(f'{t}/__init__.py,,')
    (di / 'RECORD').write_text('\n'.join(rec) + '\n')


def _fake_pack(d, variant='cpu', installed=True):
    (d / 'python').mkdir(parents=True, exist_ok=True)
    (d / 'python' / 'python.exe').write_bytes(b'')
    site = si._site(d)
    for f in [si.FILES[f'torch-{variant}'], *si._lib_files()]:
        _fake_pkg(site, f)
    for k in si.KEY_FILES + ['torch/lib/torch_cuda.dll']:
        (site / k).parent.mkdir(parents=True, exist_ok=True)
        (site / k).write_bytes(b'x')
    snap = si._snapshot(d)
    snap.mkdir(parents=True)
    for w in si.WEIGHTS:
        (snap / w['file']).write_bytes(b'w' * w['size'])
    (snap.parent.parent / 'refs').mkdir()
    (snap.parent.parent / 'refs' / 'main').write_text(si.HF_REV)
    if installed:
        si._write_json(d / 'installed.json', {'format': si.PACK_FORMAT, 'lock': si.LOCK_ID, 'variant': variant, 'python': '3.14.10',
                                              'model': si.MODEL, 'hf_revision': si.HF_REV,
                                              'installed_at': '2026-11-03T00:00:00', 'verify': {'warnings': []}})


def test_check_empty(tmp_path):
    for d in (tmp_path / 'nothing', tmp_path):
        r = si.check(d)
        assert r['ok'] is False and r['missing'] and r['resume'] is None and r['python'] is None


def test_check_fake_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    _fake_pack(tmp_path)
    r = si.check(tmp_path)
    assert r['ok'], r['missing']
    assert r['variant'] == 'cpu' and r['python'].endswith('python.exe') and r['installed_at']
    assert r['stage'] == 'none' and r['changes'] == [] and r['update_bytes'] == 0 and r['partial'] and not r['app_update']

    (si._site(tmp_path) / 'torch' / 'lib' / 'torch_cpu.dll').unlink()          # ウイルス対策ソフトが消した等
    r = si.check(tmp_path)
    assert not r['ok'] and any('torch_cpu.dll' in m for m in r['missing'])
    assert [(c['name'], c['why'], c['required']) for c in r['changes']] == [('torch', 'broken', True)]
    assert not any('部品が足りない' in m for m in r['missing'])                   # 同じ物を 2 回知らせない


def test_check_detects_kind_format_python_model(tmp_path, monkeypatch):
    """パックの作り・Python の版・学習済みモデルの版の違いは今と同じく必須（部品の版は部品ごとに見る＝一覧の頭 lock だけ違っても止めない）"""
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    _fake_pack(tmp_path, 'cpu')
    inst = si._read_json(tmp_path / 'installed.json')
    si._write_json(tmp_path / 'installed.json', inst | {'variant': 'cu128'})      # cu128 の印なのに torch は +cpu
    r = si.check(tmp_path)
    assert not r['ok'] and r['stage'] == 'required' and any('PyTorch（GPU 版・CPU 版の種類が違う）' in m for m in r['missing'])
    assert [c['why'] for c in r['changes']] == ['kind'] and r['partial']
    si._write_json(tmp_path / 'installed.json', inst | {'lock': 'old'})          # 前のアプリの版で入れた（部品は今の一覧と同じ）
    assert si.check(tmp_path)['stage'] == 'none'
    for over, word in (({'format': si.PACK_FORMAT + 1}, '作り'), ({'python': '3.13.5'}, 'Python の版')):
        si._write_json(tmp_path / 'installed.json', inst | over)
        r = si.check(tmp_path)
        assert not r['ok'] and r['rebuild'] and not r['partial'] and any(word in m for m in r['missing']), over
    si._write_json(tmp_path / 'installed.json', inst | {'hf_revision': 'abcdef0123'})
    r = si.check(tmp_path)
    assert not r['ok'] and r['partial'] and any('学習済みモデルの版' in m for m in r['missing'])
    assert [(c['key'], c['why'], c['have']) for c in r['changes']] == [('weights', 'model', 'abcdef0')]
    si._write_json(tmp_path / 'installed.json', inst)
    (si._snapshot(tmp_path) / 'a.safetensors').write_bytes(b'short')
    r = si.check(tmp_path)
    assert not r['ok'] and any('学習済みモデル' in m for m in r['missing'])
    assert [(c['key'], c['why'], c['size']) for c in r['changes']] == [('weights', 'missing', 7)] and r['update_bytes'] == 7


# ---------------------------------------------------------------- 版の 2 段（おすすめ・必須）と NG（使ってはいけない版）

def test_version_keys():
    k = si._vkey
    assert k('2.11.0+cu128') == k('2.11.0') == k('2.11') and k('2.10.0') < k('2.11.0') < k('2.11.1')
    assert k('1.0.dev1') < k('1.0a1') < k('1.0b2') < k('1.0rc1') < k('1.0') < k('1.0.post1') < k('1.1')
    assert k('2026.7.0') > k('2025.12.1') and k('3.20') > k('3.9') and k('0.16.0') < k('0.16.1')
    assert k('abc') is None and si._ver_lt('abc', '1.0') and si._local('2.11.0+CU128') == 'cu128' and si._local('2.11.0') == ''


def test_ng_rules_and_match():
    rules = si._ng_rules({'parts': {'torch': ['2.11.0'], 'Hf-Xet': ['<1.7.0', '1.8.0+x'], 'bad': 'notalist', 'numpy': [3, '', 'a b']},
                          'why': 'w'})
    assert set(rules) == {'torch', 'hf_xet'}                       # 形の違う物は黙って飛ばす（古い版が新しい形を読んでも止まらない）
    assert si._ng_match('torch', '2.11.0+cu128', rules) and si._ng_match('torch', '2.11', rules)
    assert not si._ng_match('torch', '2.11.1+cpu', rules) and not si._ng_match('torch', None, rules)
    assert si._ng_match('hf_xet', '1.6.9', rules) and not si._ng_match('hf-xet', '1.7.0', rules)
    assert si._ng_match('hf-xet', '1.8.0+x', rules) and not si._ng_match('hf-xet', '1.8.0', rules)   # 種類つきはその種類だけ
    assert si._ng_rules(None) == {} and si._ng_rules({'app': ['v0.2.0'], 'why': 'x'}) == {} and si._ng_rules('x') == {}
    assert si._ng_rules({'torch': ['2.11.0']}) == {'torch': ['2.11.0']}   # parts そのものも読む


def test_min_versions_hold_for_verified_set():
    pinned = {si._norm(f['name']): f['version'] for _, f in si._verified()}
    for n, lo in si.MIN_VERSIONS.items():
        assert si._norm(n) in pinned, n                                     # 一覧に無い名前を書かない
        assert si._vkey(lo) and not si._ver_lt(pinned[si._norm(n)], lo), (n, pinned[si._norm(n)], lo)   # 確かめた組は最低の版を満たす


def _bump(monkeypatch, key, version):
    """アプリの新しい版で、確かめた組のある部品の版を変えた（FILES の写しを差し替える）"""
    f = si.FILES[key]
    new = dict(si.FILES)
    new[key] = dict(f, version=version, file=f['file'].replace(f['version'], version, 1))
    monkeypatch.setattr(si, 'FILES', new)
    return new[key]


def test_check_recommended_update(tmp_path, monkeypatch):
    """入っている版が確かめた組と違っても、最低の版以上で NG でなければ止めない（おすすめの更新・差分のダウンロード量）"""
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    _fake_pack(tmp_path)
    f = _bump(monkeypatch, 'lib-einops', '0.8.3')            # 最低の版の無い部品
    t = _bump(monkeypatch, 'torch-cpu', '2.12.0+cpu')        # torch は最低の版 2.11.0 以上＝今の 2.11.0 のままでも使える
    r = si.check(tmp_path)
    assert r['ok'] and r['stage'] == 'recommended' and not r['missing'] and r['partial'] and not r['app_update']
    by = {c['name']: c for c in r['changes']}
    assert set(by) == {'einops', 'torch'} and all(c['why'] == 'diff' and not c['required'] and c['fixable'] for c in by.values())
    assert (by['torch']['have'], by['torch']['want'], by['torch']['min'], by['torch']['label']) == ('2.11.0+cpu', '2.12.0+cpu', '2.11.0', 'PyTorch')
    assert r['update_bytes'] == f['size'] + t['size'] + si.FILES['pip']['size']
    _bump(monkeypatch, 'torch-cpu', '2.11.0+cpu')
    _bump(monkeypatch, 'lib-einops', '0.8.1')                 # 確かめた組の方が古い（下げた）＝これも「違う版」
    assert [(c['name'], c['why']) for c in si.check(tmp_path)['changes']] == [('einops', 'diff')]


def test_check_required_older_and_ng(tmp_path, monkeypatch):
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    _fake_pack(tmp_path)
    monkeypatch.setitem(si.MIN_VERSIONS, 'torch', '2.12.0')   # 新しいアプリの版は torch 2.12 以上が要る
    _bump(monkeypatch, 'torch-cpu', '2.12.0+cpu')
    r = si.check(tmp_path)
    assert not r['ok'] and r['stage'] == 'required' and r['partial'] and not r['app_update']
    assert [(c['name'], c['why'], c['required'], c['fixable']) for c in r['changes']] == [('torch', 'older', True, True)]
    assert any('古すぎる' in m and '2.12.0 以上' in m for m in r['missing'])
    monkeypatch.setitem(si.MIN_VERSIONS, 'torch', '2.11.0')
    _bump(monkeypatch, 'lib-filelock', '4.2.8')
    ng = {'parts': {'filelock': ['4.2.7']}, 'why': 'ファイルを壊す不具合'}
    r = si.check(tmp_path, ng)
    assert not r['ok'] and r['stage'] == 'required' and r['ng_why'] == 'ファイルを壊す不具合'
    by = {c['name']: (c['why'], c['required'], c['fixable']) for c in r['changes']}
    assert by == {'torch': ('diff', False, True), 'filelock': ('ng', True, True)}
    assert any('使ってはいけない版' in m and 'filelock 4.2.7' in m and 'ファイルを壊す不具合' in m for m in r['missing'])
    assert si.check(tmp_path)['stage'] == 'recommended'       # NG を知らなければ（控えが無い）おすすめのまま


def test_check_ng_in_verified_set_needs_app_update(tmp_path, monkeypatch):
    """確かめた組そのものに NG の版がある＝部品をインストールし直しても直らない（アプリの更新が要る）"""
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    _fake_pack(tmp_path)
    ng = {'parts': {'torch': ['2.11.0']}}
    r = si.check(tmp_path, ng)
    assert not r['ok'] and r['app_update'] and r['ng_set'] == [{'key': 'torch-cpu', 'name': 'torch', 'version': '2.11.0+cpu'}]
    assert [(c['why'], c['fixable']) for c in r['changes']] == [('ng', False)] and any('アプリを更新' in m for m in r['missing'])
    assert si.set_ng('cpu', ng) == r['ng_set'] and len(si.set_ng(None, ng)) == len(si.VARIANTS) and si.set_ng('cpu', None) == []
    assert si.set_ng('cpu', {'parts': {'pip': ['26.2.1']}})[0]['key'] == 'pip'   # 入れる道具（pip）が NG でもアプリの更新
    # 確かめた版は NG・入っている版は使える（NG でない・最低の版以上）＝入れ替えない（入れ替えると NG を入れる）
    _bump(monkeypatch, 'torch-cpu', '2.12.0+cpu')
    r = si.check(tmp_path, {'parts': {'torch': ['2.12.0']}})
    assert r['ok'] and r['stage'] == 'none' and r['ng_set'] and not r['app_update'] and not r['changes']


def test_check_resume_info(tmp_path, monkeypatch):
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    dl = tmp_path / 'downloads'
    dl.mkdir()
    (dl / (si.FILES['torch-cpu']['file'] + '.part')).write_bytes(b'x' * 1000)
    si._write_json(tmp_path / 'state.json', {'variant': 'cpu', 'lock': si.LOCK_ID, 'started_at': 'a', 'updated_at': 'b',
                                             'stages': {'python': {'done': True}}})
    r = si.check(tmp_path)
    assert not r['ok'] and any('途中' in m for m in r['missing'])
    assert r['resume']['stage'] == 'download' and r['resume']['downloaded_bytes'] == 1000
    assert r['resume']['done_stages'] == ['python'] and r['resume']['label']


def test_check_is_fast(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    _fake_pack(tmp_path)
    t = time.perf_counter()
    for _ in range(20):
        si.check(tmp_path)
    assert (time.perf_counter() - t) / 20 < 0.2


# ---------------------------------------------------------------- 部品の状態・消す

def test_pkg_state_and_remove(tmp_path):
    site = tmp_path / 'site'
    f = si.FILES['torch-cpu']
    assert si._pkg_state(site, f) == 'missing'
    _fake_pkg(site, f, tops=['torch', 'torchgen'])
    assert si._pkg_state(site, f, deep=True) == 'ok'
    (site / 'torchgen' / '__init__.py').unlink()
    assert si._pkg_state(site, f) == 'ok' and si._pkg_state(site, f, deep=True) == 'broken'
    (site / f'torch-{f["version"]}.dist-info' / 'RECORD').unlink()                 # pip が途中で止まった
    assert si._pkg_state(site, f) == 'broken'
    assert si._pkg_state(site, si.FILES['torch-cu128']) == 'version'
    whl = tmp_path / 'w.whl'
    with zipfile.ZipFile(whl, 'w') as z:
        z.writestr('functorch/__init__.py', '')
        z.writestr('torch-2.11.0+cpu.dist-info/RECORD', '')
    (site / 'functorch').mkdir()
    (site / 'numpy').mkdir()
    si._remove_pkg(site, f, whl)
    # RECORD が無い時は、これから入れる wheel の一番上の名前（functorch）と dist-info を消す。ほかの部品（numpy）は残す
    assert sorted(p.name for p in site.iterdir()) == ['numpy', 'torch', 'torchgen']
    # pip が torch/ を書いている途中で止まった（dist-info はまだ無い）→ wheel の一番上の名前で消す
    (site / 'functorch' / 'x.py').parent.mkdir()
    (site / 'functorch' / 'x.py').write_text('')
    assert si._pkg_state(site, f) == 'missing'
    si._remove_pkg(site, f, whl)
    assert not (site / 'functorch').exists() and (site / 'numpy').exists()


def test_copy_runtime(tmp_path):
    rt = tmp_path / 'runtime'
    (rt / 'Lib' / 'site-packages' / 'numpy').mkdir(parents=True)
    (rt / 'Scripts').mkdir()
    (rt / '__pycache__').mkdir()
    for n in ('python.exe', 'pythonw.exe', 'python314.dll', 'python314.zip', 'msvcp140.dll'):
        (rt / n).write_bytes(b'x')
    (rt / 'python314._pth').write_text('python314.zip\n.\nLib\\site-packages\n..\n..\\app\nimport site\n')
    dst = tmp_path / 'pack' / 'python'
    assert si._copy_runtime(rt, dst) == '314'
    assert (dst / 'python.exe').exists() and (dst / 'msvcp140.dll').exists()
    assert not (dst / 'Scripts').exists() and not (dst / '__pycache__').exists()
    assert (dst / 'Lib' / 'site-packages').is_dir() and not any((dst / 'Lib' / 'site-packages').iterdir())
    assert (dst / 'python314._pth').read_text().split() == ['python314.zip', '.', 'Lib\\site-packages', 'import', 'site']
    with pytest.raises(si.SepInstallError):
        si._copy_runtime(tmp_path / 'pack', tmp_path / 'other')      # python3XX.zip の無い物は埋め込み用の Python ではない


def test_run_env(tmp_path):
    e = si.run_env(tmp_path)
    assert e['HF_HUB_OFFLINE'] == '1' and Path(e['HF_HOME']) == (tmp_path / 'hf').resolve()
    full = si.run_env(tmp_path, {'PATH': 'p', 'PYTHONPATH': 'x', 'PYTHONHOME': 'y', 'PIP_CERT': 'z'})
    assert full['PATH'] == 'p' and 'PYTHONPATH' not in full and 'PYTHONHOME' not in full and 'PIP_CERT' not in full
    assert full['HF_HUB_OFFLINE'] == '1'
    assert si.python_exe(tmp_path) == tmp_path / 'python' / 'python.exe'
    (tmp_path / 'python' / 'Scripts').mkdir(parents=True)
    (tmp_path / 'python' / 'Scripts' / 'python.exe').write_bytes(b'')     # 開発の PC の venv
    assert si.python_exe(tmp_path) == tmp_path / 'python' / 'Scripts' / 'python.exe'


def test_lock_file(tmp_path):
    (tmp_path / 'install.lock').write_text(str(os.getppid()))             # 生きている別のプロセス
    with pytest.raises(si.SepInstallError, match='途中'):
        with si._Lock(tmp_path):
            pass
    (tmp_path / 'install.lock').write_text('99999999')                     # 止まったプロセスの残り
    with si._Lock(tmp_path):
        assert (tmp_path / 'install.lock').read_text() == str(os.getpid())
    assert not (tmp_path / 'install.lock').exists()


# ---------------------------------------------------------------- 取る（127.0.0.1 の小さなサーバー）

class _Server:
    def __init__(self, data, honor_range=True):
        self.data, self.ranges = data, []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                rng = self.headers.get('Range')
                outer.ranges.append(rng)
                start = int(re.match(r'bytes=(\d+)-', rng)[1]) if rng and honor_range else 0
                body = outer.data[start:]
                self.send_response(206 if start else 200)
                if start:
                    self.send_header('Content-Range', f'bytes {start}-{len(outer.data) - 1}/{len(outer.data)}')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass

            def log_message(self, *a):
                pass
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}/f.whl'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def no_proxy(monkeypatch):
    monkeypatch.setenv('NO_PROXY', '*')
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        monkeypatch.delenv(k, raising=False)


def _entry(url, data, sha=None):
    return {'file': 'f.whl', 'url': url, 'size': len(data), 'sha256': sha or hashlib.sha256(data).hexdigest()}


@pytest.mark.parametrize('honor', [True, False])
def test_download_resume(tmp_path, no_proxy, honor):
    data = os.urandom(3 * (1 << 20) + 123)
    srv = _Server(data, honor_range=honor)
    try:
        f = _entry(srv.url, data)
        dl = tmp_path / 'downloads'
        seen = []

        def rep(stage, done=0, total=0, msg='', force=False):
            seen.append((stage, done))
        with pytest.raises(si.Cancelled):          # 1 MB 取った所で止める
            si._fetch_verified(f, dl / 'f.whl', dl, rep, lambda: any(d >= (1 << 20) for _, d in seen), 0, f['size'])
        part = dl / 'f.whl.part'
        assert part.exists() and 0 < part.stat().st_size < len(data) and not (dl / 'f.whl').exists()
        si._fetch_verified(f, dl / 'f.whl', dl, rep, None, 0, f['size'])
        assert (dl / 'f.whl').read_bytes() == data and not part.exists()
        assert srv.ranges[0] is None and srv.ranges[-1] and srv.ranges[-1].startswith('bytes=')    # 続きから頼んだ
        n = len(srv.ranges)
        si._fetch_verified(f, dl / 'f.whl', dl, rep, None, 0, f['size'])                          # もうある → 取らない
        assert len(srv.ranges) == n
    finally:
        srv.close()


def test_download_bad_hash(tmp_path, no_proxy):
    data = b'abc' * 1000
    srv = _Server(data)
    try:
        f = _entry(srv.url, data, sha='0' * 64)
        dl = tmp_path / 'downloads'
        with pytest.raises(si.SepInstallError, match='壊れている'):
            si._fetch_verified(f, dl / 'f.whl', dl, lambda *a, **k: None, None, 0, f['size'])
        assert len(srv.ranges) == 2                                       # 1 回だけ頭から取り直した
        assert not list(dl.iterdir())                                     # 合わない物は残さない
    finally:
        srv.close()


def test_net_errors_are_japanese():
    e = si.urllib.error.URLError(ConnectionRefusedError('refused'))
    assert 'ネットにつながらない' in si._net_error(e, 'https://download.pytorch.org/x')
    e = si.urllib.error.URLError(si.ssl.SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]'))
    assert '証明書' in si._net_error(e, 'https://pypi.org/x')
    e = si.urllib.error.HTTPError('https://x/y', 404, 'nf', {}, None)
    assert '無い' in si._net_error(e, 'https://x/y')


# ---------------------------------------------------------------- 段の流れ（重い所は作り物に替える）

@pytest.fixture
def fake_stages(monkeypatch, gpu):
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    calls = {'python': 0, 'fetch': [], 'pip': []}

    def prep(d, runtime, rep):
        calls['python'] += 1
        (d / 'python').mkdir(exist_ok=True)
        (d / 'python' / 'python.exe').write_bytes(b'')
        return '3.14.7'

    def fetch(f, dst, dl, rep, cancel, base, total, stage='download'):
        calls['fetch'].append(f['file'])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if stage == 'weights':
            dst.write_bytes(b'w' * f['size'])
        else:
            with zipfile.ZipFile(dst, 'w') as z:
                z.writestr(f'{f["name"]}-{f["version"]}.dist-info/RECORD', '')

    def pip(d, files, rep, cancel, total, base, log):
        calls['pip'].append([f['name'] for f in files])
        site = si._site(d)
        for f in files:
            _fake_pkg(site, f)
        for k in si.KEY_FILES + ['torch/lib/torch_cuda.dll']:
            (site / k).parent.mkdir(parents=True, exist_ok=True)
            (site / k).write_bytes(b'x')
    monkeypatch.setattr(si, '_prepare_python', prep)
    monkeypatch.setattr(si, '_fetch_verified', fetch)
    monkeypatch.setattr(si, '_run_pip', pip)
    monkeypatch.setattr(si, 'verify', lambda d, log=None: {'ok': True, 'cuda': False, 'warnings': []})
    return calls


def test_install_stages_resume(tmp_path, fake_stages):
    calls = fake_stages
    stages = []
    with pytest.raises(si.Cancelled):          # pip の前で止める
        si.install(tmp_path, 'cpu', progress=lambda p: stages.append(p['stage']), cancel=lambda: 'pip' in stages or
                   len(calls['fetch']) >= len(si._lib_files()) + 2)
    r = si.check(tmp_path)
    assert not r['ok'] and r['resume']['stage'] == 'pip' and r['resume']['done_stages'] == ['python', 'download', 'hash']
    assert not (tmp_path / 'install.lock').exists()
    got = []
    inst = si.install(tmp_path, 'cpu', progress=got.append)
    assert calls['python'] == 1                                         # 済んだ段は飛ばす
    assert [len(x) for x in calls['pip']] == [len(si._lib_files()), 1]  # 小物と torch の 2 回
    assert inst['variant'] == 'cpu' and inst['lock'] == si.LOCK_ID and inst['verify']['ok']
    assert si.check(tmp_path)['ok'] and not (tmp_path / 'downloads').exists()
    assert {'stage', 'label', 'done', 'total', 'msg'} <= set(got[-1]) and got[-1]['stage'] == 'done'
    again = si.install(tmp_path, 'cpu')                                 # 入っている時は何もしない
    assert again['already'] and len(calls['pip']) == 2

    # 部品が 1 つ壊れた → その部品だけ取り直して入れ直す
    rec = next(si._site(tmp_path).glob('demucs-*.dist-info')) / 'RECORD'
    rec.unlink()
    si.install(tmp_path, 'cpu')
    assert calls['pip'][-1] == ['demucs']


def test_recommended_update_replaces_only_changed(tmp_path, fake_stages, monkeypatch):
    """アプリの版が上がって一覧の頭（LOCK_ID）も変わった → おすすめの更新は違う部品だけ取り直す（パック専用の Python を作り直さない
    ＝site-packages ごと消して全部を取り直さない）"""
    calls = fake_stages
    si.install(tmp_path, 'cpu')
    monkeypatch.setattr(si, 'LOCK_ID', si.LOCK_ID + '-next')
    f = _bump(monkeypatch, 'lib-einops', '0.8.3')
    assert si.check(tmp_path)['stage'] == 'recommended'
    n = len(calls['fetch'])
    inst = si.install(tmp_path, 'cpu')
    assert calls['python'] == 1
    assert [x for x in calls['fetch'][n:] if x.endswith('.whl')] == [f['file'], si.FILES['pip']['file']]
    assert calls['pip'][-1] == ['einops'] and inst['lock'] == si.LOCK_ID and not inst.get('already')
    r = si.check(tmp_path)
    assert r['stage'] == 'none' and r['resume'] is None


def test_lower_versions_in_new_verified_set(tmp_path, fake_stages, monkeypatch):
    """リリースした後に問題が分かり、動作確認済みの組の版を下げた（アプリの新しい版の一覧が古い版を指し、問題の版は NG・最低の版も下げる）
    → 起動のたびの確かめで「使ってはいけない版」と分かって止め、インストールすると下げた部品だけを取り直して入れ替える（上げるのも
    下げるのも同じ道）。NG を知らない（ネットにつながらず控えも無い）時は「おすすめ」のまま"""
    calls = fake_stages
    si.install(tmp_path, 'cpu')
    assert si.check(tmp_path)['ok']
    new = dict(si.FILES)
    new['lib-filelock'] = dict(si.FILES['lib-filelock'], version='3.32.3', file='filelock-3.32.3-py3-none-any.whl')
    new['torch-cpu'] = dict(si.FILES['torch-cpu'], version='2.10.0+cpu', file='torch-2.10.0+cpu-cp314-cp314-win_amd64.whl')
    monkeypatch.setattr(si, 'FILES', new)
    monkeypatch.setattr(si, 'MIN_VERSIONS', dict(si.MIN_VERSIONS, torch='2.10.0', filelock='3.32.3'))
    ng = {'parts': {'filelock': ['4.2.7'], 'torch': ['2.11.0']}, 'why': '試し'}
    r = si.check(tmp_path, ng)
    assert not r['ok'] and r['stage'] == 'required' and not r['app_update']
    assert any('filelock' in m and '使ってはいけない版' in m for m in r['missing'])
    assert sorted((c['name'], c['why']) for c in r['changes']) == [('filelock', 'ng'), ('torch', 'ng')]
    assert si.check(tmp_path)['stage'] == 'recommended'
    n = len(calls['fetch'])
    si.install(tmp_path, 'cpu')
    got = sorted(x for x in calls['fetch'][n:] if x.endswith('.whl') and not x.startswith('pip-'))
    assert got == sorted([new['lib-filelock']['file'], new['torch-cpu']['file']])   # 下げた 2 つだけ
    assert calls['pip'][-2:] == [['filelock'], ['torch']]
    r = si.check(tmp_path, ng)
    assert r['ok'] and r['stage'] == 'none'
    site = si._site(tmp_path)
    assert [p.name for p in site.glob('filelock-*.dist-info')] == ['filelock-3.32.3.dist-info']
    assert [p.name for p in site.glob('torch-*.dist-info')] == ['torch-2.10.0+cpu.dist-info']


def test_switch_variant_keeps_working_pack(tmp_path, fake_stages):
    calls = fake_stages
    si.install(tmp_path, 'cpu')
    n = len(calls['fetch'])
    with pytest.raises(si.Cancelled):          # GPU 版へ入れ替える途中（取った後・入れる前）で止める
        si.install(tmp_path, 'cu128', cancel=lambda: len(calls['fetch']) > n)
    r = si.check(tmp_path)
    assert r['ok'] and r['variant'] == 'cpu'                            # 今の CPU 版はそのまま使える
    assert r['resume']['variant'] == 'cu128' and r['resume']['stage'] == 'pip'
    inst = si.install(tmp_path, 'cu128')
    assert inst['variant'] == 'cu128' and calls['python'] == 1          # パック専用の Python は作り直さない
    assert calls['pip'][-1] == ['torch']                                # 小物は入れ直さない
    r = si.check(tmp_path)
    assert r['ok'] and r['variant'] == 'cu128' and r['resume'] is None
    assert [p.name for p in si._site(tmp_path).glob('torch-*.dist-info')] == ['torch-2.11.0+cu128.dist-info']


# ---------------------------------------------------------------- コマンド

def test_cli_json(tmp_path, gpu, capsys):
    assert si.main(['check', '--dir', str(tmp_path), '--json']) == 1
    o = json.loads(capsys.readouterr().out)
    assert o['ok'] is False
    assert si.main(['plan', '--dir', str(tmp_path), '--offline', '--json']) == 0
    o = json.loads(capsys.readouterr().out)
    assert o['variant'] == 'cpu' and o['items']


def test_cli_check_with_ng(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(si, 'WEIGHTS', SMALL_W)
    _fake_pack(tmp_path)
    assert si.main(['check', '--dir', str(tmp_path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['stage'] == 'none'
    ngf = tmp_path / 'ng.json'
    ngf.write_text(json.dumps({'parts': {'numpy': ['2.5.4']}, 'why': '試し'}), encoding='utf-8')
    assert si.main(['check', '--dir', str(tmp_path), '--ng', str(ngf)]) == 1
    out = capsys.readouterr().out
    assert '使ってはいけない版' in out and '必須: numpy 2.5.4 → 2.5.4' in out


def test_cli_install_error_json(tmp_path, gpu, capsys, monkeypatch):
    monkeypatch.setattr(si, '_free_bytes', lambda d: 0)
    assert si.main(['install', '--dir', str(tmp_path), '--json']) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert '空き容量が足りない' in lines[-1]['error'] and lines[-1]['cancelled'] is False
