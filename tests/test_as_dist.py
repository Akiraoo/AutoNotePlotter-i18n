"""配布物のふり（環境変数 AUTOMAP_AS_DIST・tools/dist/checkset.py dev・docs/アプリ仕様.md 23 節）: ソースのまま動かしても、
開発の PC にしか無い物（app/config.local.json・.venv-sep・開発用の型のデータベース・リポジトリの out/）を見ず、
同梱物（data/・parts/・runtime/）はその場所から読む。アプリの更新はしない（差し替えるとリポジトリを書き換える）。"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = r'''
import json, sys
root = sys.argv[1]
sys.path[:0] = [root, root + '/app', root + '/tools']
from automap import config, library_db, rating
import setup, update
cfg = config.load()
print(json.dumps({
    'distributed': config.distributed(), 'packaged': config.packaged(), 'as_dist': str(config.as_dist()),
    'config': str(config.path()), 'out': str(config.out_dir(cfg)), 'cache': str(config.cache_dir(cfg)),
    'library': str(library_db.BUNDLED), 'rating': str(rating.BUNDLED), 'runtime': str(setup.runtime_dir()),
    'work': setup.work_state(cfg), 'sep_kind': setup.sep_state(cfg)['kind'], 'update': update.Updater().distributed,
}, ensure_ascii=False))
'''


def probe(env):
    r = subprocess.run([sys.executable, '-c', PROBE, str(ROOT)], capture_output=True, env=env, cwd=ROOT)
    assert r.returncode == 0, r.stderr.decode('utf-8', 'replace')
    return json.loads(r.stdout.decode('utf-8'))


def clean_env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ('AUTOMAP_CONFIG', 'AUTOMAP_LIBRARY', 'NLM_RATING_EXE', 'AUTOMAP_AS_DIST')}
    env.update(LOCALAPPDATA=str(tmp_path / 'lad'), PYTHONIOENCODING='utf-8', **extra)
    return env


def test_as_dist_hides_dev_things(tmp_path):
    b = tmp_path / '同梱物'
    r = probe(clean_env(tmp_path, AUTOMAP_AS_DIST=str(b)))
    assert r['distributed'] and not r['packaged'] and Path(r['as_dist']) == b
    assert Path(r['config']) == tmp_path / 'lad' / 'AutoNotePlotter' / 'config.json'   # app/config.local.json を読まない
    assert Path(r['out']) == b / 'out' and Path(r['cache']) == b / 'cache'           # 作業の場所が決まる前もリポジトリの out/ を見ない
    assert Path(r['library']) == b / 'data' / 'library-dist.sqlite'
    assert Path(r['rating']) == b / 'parts' / 'nlm-rating' / 'nlm-rating.exe'
    assert r['runtime'] == 'None'
    assert not r['work']['ok'] and r['work']['dir'] is None   # 配布物と同じく作業フォルダを聞く
    assert r['sep_kind'] is None                               # .venv-sep を使わない
    assert r['update'] is False                                # 更新はしない


def test_as_dist_runtime_and_config(tmp_path):
    b = tmp_path / 'b'
    (b / 'runtime').mkdir(parents=True)
    cfg = tmp_path / 'config.json'
    cfg.write_text(json.dumps({'work_dir': str(tmp_path / 'w')}), encoding='utf-8')
    (tmp_path / 'w').mkdir()
    r = probe(clean_env(tmp_path, AUTOMAP_AS_DIST=str(b), AUTOMAP_CONFIG=str(cfg)))
    assert Path(r['runtime']) == b / 'runtime'   # 部品のインストールは同梱物の埋め込み用の Python から
    assert Path(r['config']) == cfg and Path(r['out']) == tmp_path / 'w' / 'out'
    assert r['work']['ok']


def test_without_as_dist_is_dev(tmp_path):
    r = probe(clean_env(tmp_path))
    assert not r['distributed'] and r['as_dist'] == 'None'
    assert Path(r['library']) == ROOT / 'data' / 'library-dist.sqlite'
    assert Path(r['out']).parent == ROOT or r['work']['ok']   # 開発の PC: 設定の作業の場所か、リポジトリの out/
