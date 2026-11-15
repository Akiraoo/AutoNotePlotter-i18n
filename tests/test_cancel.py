"""作業の「やめる」（app/server.cancel_job・2026-11-03 利用者「譜面造りの途中でキャンセル出来るようなボタン」）: 作り直しは compose を止めて
結果のファイル・報告・書いた時の指紋を作り直しの前に戻す（保存の途中で止めても壊れない）・履歴に残さない。別の案は案ごとの作り直しを
全部止め、作りかけの案を残さない。compose は小さな台本に置き換える"""
import sys
import time
from pathlib import Path

import pytest

from automap import nlmf
from automap import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_versions import _proj  # noqa: E402

# compose の代わり: --out に書きかけの（読めない）中身と報告を書いてから眠る（止められるのを待つ）。--quick なら普通に書いて終わる
FAKE = r'''
import sys, time
a = sys.argv[1:]
arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d
out = arg('--out')
print('始めた', flush=True)
if '--quick' in a:
    sys.exit(0)
open(out, 'w', encoding='utf-8').write('{"format":"nlmf","vers')
open(out[:-len('.nlmf')] + '.report.md', 'w', encoding='utf-8').write('# 書きかけ')
print('書きかけ', flush=True)
time.sleep(60)
'''


@pytest.fixture
def app(tmp_path, monkeypatch):
    import server
    import versions
    monkeypatch.setattr(server, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(server, 'CACHE', tmp_path / 'cache')
    (tmp_path / 'out').mkdir()
    versions.routes(server)
    fake = tmp_path / 'fake_compose.py'
    fake.write_text(FAKE, encoding='utf-8')
    monkeypatch.setattr(server, 'compose_cmd', lambda p, tf, only=None, out=None, extra=(), diff=None:
                        [sys.executable, str(fake), '--out', str(out or p), *[str(x) for x in extra]])
    monkeypatch.setattr(server, 'COMPOSE_EXTRA', [])
    p = tmp_path / 'out' / 'T.intent-s1.nlmf'
    cli._save(_proj(), p)
    p.with_name('T.intent-s1.report.md').write_text('# 前の報告\n', encoding='utf-8')
    server.save_work(p, {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}})
    return server, versions, p


def _wait(server, j, t=30, until=None):
    t0 = time.time()
    while time.time() - t0 < t:
        if until is not None and until(j):
            return j
        if until is None and server.job_view(j)['state'] != 'running':
            return j
        time.sleep(0.05)
    raise AssertionError('待ちきれない')


def test_cancel_generate_restores_result(app):
    """書きかけで止めても、結果のファイル・報告・指紋は作り直しの前のまま・履歴に作った版を残さない・もう一度やめるのは断る"""
    server, V, p = app
    before, rep = p.read_bytes(), p.with_name('T.intent-s1.report.md').read_text(encoding='utf-8')
    st = cli._state_path(p).read_bytes()
    j = server.start_generate(p)
    _wait(server, j, until=lambda j: '書きかけ' in j['log'])
    assert p.read_bytes() != before   # 書きかけ（読めない）
    assert server.cancel_job(j['id'])['ok']
    _wait(server, j)
    v = server.job_view(j)
    assert v['state'] == 'error' and v['cancelled'] and 'やめた' in v['log'] and '作り直しの前のまま' in v['log']
    assert p.read_bytes() == before and nlmf.load(p)['bpm'] == 120
    assert p.with_name('T.intent-s1.report.md').read_text(encoding='utf-8') == rep and cli._state_path(p).read_bytes() == st
    assert not cli._edited_since_written(p)
    assert all(e['kind'] != 'generate' for e in V.list_versions(p)['versions'])   # 作った版は控えない
    assert not server.busy(p.name)
    with pytest.raises(ValueError):
        server.cancel_job(j['id'])
    with pytest.raises(ValueError):
        server.cancel_job('nothing')


def test_cancel_between_steps(app, tmp_path):
    """やめると次の段に入らない（関数の段の中でやめても次のコマンドは動かさない）"""
    server, _, p = app
    mark = tmp_path / 'ran.txt'
    box = {}

    def first(job):
        server.cancel_job(job['id'])   # 段の中でやめる
        box['in'] = True
    j = server.start_job(p.name, [('一つ目', first), ('二つ目', [sys.executable, '-c', f'open(r"{mark}", "w").write("x")'])])
    _wait(server, j)
    assert box['in'] and j['cancelled'] and not mark.exists() and j['step'] == 0


def test_generate_without_cancel_is_unchanged(app):
    """やめなければ前と同じ（compose が終われば done・控えは戻さない）"""
    server, _, p = app
    j = server.start_generate(p, extra=['--quick'])
    _wait(server, j)
    assert j['state'] == 'done' and not j.get('cancelled')


def test_cancel_cands_stops_all(app):
    """別の案: 親をやめると案ごとの作り直しも全部止まる・作りかけの案は残さない・結果のファイルは今のまま"""
    server, V, p = app
    before = p.read_bytes()
    j = V.start_cands(p, [8, 16], n=2)
    _wait(server, j, until=lambda j: len([s for s in server.JOBS.values() if s.get('kind') == 'cand' and '書きかけ' in s['log']]) >= 2)
    subs = [s for s in server.JOBS.values() if s.get('kind') == 'cand' and s['state'] == 'running']
    assert len(subs) == 2
    server.cancel_job(j['id'])
    _wait(server, j)
    assert j['cancelled'] and j['state'] == 'error'
    assert all(s['state'] == 'error' and s.get('cancelled') for s in subs)
    assert not V.cand_dir(p).exists() and p.read_bytes() == before
