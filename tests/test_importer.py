"""曲の取り込みの基本設定（app/importer.py・docs/アプリ仕様.md 17 節）: 「基本設定を待つ」の段・POST /api/import/settings・
決めた型のライブラリを作業ファイルの library に入れて compose の --library へ"""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import importer  # noqa: E402
from automap import library_use as LU  # noqa: E402

LIB = {'sources': ['ranked'], 'years': [2022, 2026], 'stars': [6, 10], 'diffs': ['ExpertPlus']}


@pytest.fixture
def app(tmp_path, monkeypatch):
    """写しの場所（tmp_path/out・cache）で server と importer をつなぐ。分けた音と元のプロジェクトは「もうある」（段は使い回すだけ）、
    compose は動かさずにコマンドを控える → (server, 受け口, 控えたコマンドの並び)"""
    import server
    out, cache = tmp_path / 'out', tmp_path / 'cache'
    out.mkdir()
    (cache / '曲').mkdir(parents=True)
    (cache / '曲' / 'separate.json').write_text('{}', encoding='utf-8')
    (out / '曲.nlmf').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(server, 'OUT', out)
    monkeypatch.setattr(server, 'CACHE', cache)
    monkeypatch.setattr(server, 'JOBS', {})
    monkeypatch.setattr(importer, 'WAIT_POLL', 0.02)
    cmds = []
    monkeypatch.setattr(importer, 'run_cmd', lambda job, cmd: cmds.append([str(c) for c in cmd]))
    _, post = importer.routes(server)
    return server, post, cmds


def _start(server, settings='none', wait=True):
    """取り込みの段（plan）を server.start_job で動かす。settings＝始める時に渡す基本設定（'none'＝渡さない・None＝新しい曲の既定）"""
    steps = importer.plan(server, Path('x.wav'), '曲', '曲', '', info={'soundfile': True}, wait=wait)   # 段はどれも使い回す＝音源は読まない
    meta = {} if settings == 'none' else {'settings': importer.settings_of(settings)}
    return server.start_job('曲.intent-s1.nlmf', steps, kind=importer.KIND, song='曲', **meta)


def _until(fn, sec=5):
    t0 = time.time()
    while time.time() - t0 < sec:
        if fn():
            return True
        time.sleep(0.01)
    return False


def _lib_arg(cmd):
    return json.loads(cmd[cmd.index('--library') + 1]) if '--library' in cmd else None


def test_plan_steps():
    """画面からの取り込みは最初の譜面の前に「基本設定を待つ」。無い時（コマンド・前の形）は前の4段のまま"""
    ctx = type('C', (), {'OUT': Path('o'), 'CACHE': Path('c'), 'APP_KIND': 'intent-s1'})
    labels = [s for s, _ in importer.plan(ctx, 'x.wav', '曲', '曲', '', info={'soundfile': True}, wait=True)]
    assert labels == ['音を分ける', '曲の解析', '元のプロジェクトを作る', importer.WAIT_LABEL, '最初の譜面を作る']
    assert importer.WAIT_LABEL == '基本設定を待つ'   # 画面（importer.js の WAIT）も同じ名前で見分ける
    assert len(importer.plan(ctx, 'x.wav', '曲', '曲', '', info={'soundfile': True})) == 4


def test_waits_until_settings(app):
    """設定がまだなら待つ段で止まる（/api/job の段が「基本設定を待つ」）→ 届いたら最初の譜面へ。決めた物が作業ファイルと --library に"""
    server, post, cmds = app
    j = _start(server)
    assert _until(lambda: j['step'] == 3 and '待っている' in j['log'])
    time.sleep(0.15)
    assert j['state'] == 'running' and j['step'] == 3 and not cmds and not j.get('settings_locked')
    assert server.job_view(j)['steps'][j['step']] == importer.WAIT_LABEL
    r = post['/api/import/settings']({'id': j['id'], 'library': LIB})
    assert r['ok'] and r['settings']['library'] == LU.normalize(LIB) and r['settings']['short'] == LU.label(LIB, True)
    assert _until(lambda: j['state'] != 'running')
    assert j['state'] == 'done', j['log']
    assert j['settings_locked'] and len(cmds) == 1 and _lib_arg(cmds[0]) == LU.normalize(LIB)
    w = json.loads((server.OUT / '曲.intent-s1.automap.json').read_text(encoding='utf-8'))
    assert w['library'] == LU.normalize(LIB)
    assert '基本設定: 型のライブラリ' in j['log'] and '基本設定で決めた物' in j['log']


def test_settings_before_wait(app):
    """設定が先に届いていれば待つ段はすぐ抜ける。決め直した最後の物が作業ファイルの library に入る（ほかの中身は残す）。
    null は新しい曲の既定（前の「今の型」＝library を入れない、は除いた）"""
    server, post, cmds = app
    res = server.OUT / '曲.intent-s1.nlmf'
    server.save_work(res, dict(server.default_work(res), library=LU.DEFAULT, ranges=[{'b0': 0, 'b1': 4, 'set': {'amount': 1}}]))
    lib2 = {'sources': ['ranked'], 'years': [2018, 2020], 'stars': [0, 6], 'diffs': ['Expert']}
    j = _start(server)
    post['/api/import/settings']({'id': j['id'], 'library': LIB})
    post['/api/import/settings']({'id': j['id'], 'library': lib2})   # 決め直し（最後の物が効く）
    assert _until(lambda: j['state'] != 'running')
    assert j['state'] == 'done', j['log']
    assert _lib_arg(cmds[0]) == LU.normalize(lib2)
    w = json.loads((server.OUT / '曲.intent-s1.automap.json').read_text(encoding='utf-8'))
    assert w['library'] == LU.normalize(lib2) and w['ranges'] == [{'b0': 0, 'b1': 4, 'set': {'amount': 1}}]
    assert importer.settings_of(None)['library'] == LU.DEFAULT


def test_existing_work_loses_to_settings(app):
    """作業ファイルがもうあっても（前に途中まで取り込んだ等）、基本設定で決めた物が勝つ"""
    server, post, cmds = app
    res = server.OUT / '曲.intent-s1.nlmf'
    server.save_work(res, dict(server.default_work(res), library=LU.DEFAULT))
    j = _start(server, settings=LIB)   # 始める時に渡した設定（待つ段をすぐ抜ける）
    assert _until(lambda: j['state'] != 'running') and j['state'] == 'done', j['log']
    assert _lib_arg(cmds[0]) == LU.normalize(LIB)
    assert json.loads((server.OUT / '曲.intent-s1.automap.json').read_text(encoding='utf-8'))['library'] == LU.normalize(LIB)


def test_cancel_while_waiting(app):
    """待っている間に「やめる」で止まる（最初の譜面を作らない・作業ファイルも作らない）"""
    server, post, cmds = app
    j = _start(server)
    assert _until(lambda: j['step'] == 3)
    post['/api/import/cancel']({'id': j['id']})
    assert _until(lambda: j['state'] != 'running')
    assert j['state'] == 'error' and j['cancel'] and 'やめた' in j['log'] and not cmds
    assert not (server.OUT / '曲.intent-s1.automap.json').exists()


def test_settings_refused(app, monkeypatch):
    """受け口: 無い取り込み・library の無い本文・最初の譜面を作り始めた後・終わった後は断る"""
    server, post, cmds = app
    s = post['/api/import/settings']
    with pytest.raises(KeyError):
        s({'id': 'nai', 'library': None})
    gate = threading.Event()
    hold = []

    def slow(job, cmd):   # 最初の譜面を作っている間（ここで止めて、その間に設定を送る）
        hold.append(cmd)
        gate.wait(5)
    monkeypatch.setattr(importer, 'run_cmd', slow)
    j = _start(server, settings=LIB)
    with pytest.raises(ValueError, match='library'):
        s({'id': j['id']})
    assert _until(lambda: hold)
    with pytest.raises(ValueError, match='作り始めた'):
        s({'id': j['id'], 'library': None})
    gate.set()
    assert _until(lambda: j['state'] != 'running') and j['state'] == 'done'
    with pytest.raises(ValueError, match='終わった'):
        s({'id': j['id'], 'library': None})
    assert _lib_arg(hold[0]) == LU.normalize(LIB)   # 断った設定は効かない


def test_no_wait_keeps_old_default(app):
    """基本設定の段が無い取り込み（前の形）は、作業ファイルが無ければ新しい曲の既定（データベースが使えない PC でも＝最初の譜面は止まる）"""
    server, post, cmds = app
    j = _start(server, wait=False)
    assert _until(lambda: j['state'] != 'running') and j['state'] == 'done', j['log']
    assert _lib_arg(cmds[0]) == LU.normalize(LU.DEFAULT)


# ---- 曲の解析を音を分けるのと同時に（2026-11-11・_side_start） ----

@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """分けた音も元のプロジェクトも無い取り込み（音を分ける・曲の解析を動かす）。コマンドは偽物 → (server, 受け口, 偽物の操作)。
    偽物の音を分けるは gate['sep'] が開くまで、曲の解析は gate['ana'] が開くまで待つ（止められたら「やめた」）"""
    import types
    import server
    out, cache = tmp_path / 'out', tmp_path / 'cache'
    out.mkdir()
    cache.mkdir()
    monkeypatch.setattr(server, 'OUT', out)
    monkeypatch.setattr(server, 'CACHE', cache)
    monkeypatch.setattr(server, 'JOBS', {})
    monkeypatch.setitem(sys.modules, 'setup', types.SimpleNamespace(sep_runner=lambda ctx: ('sep-python', None, 'cu128')))
    monkeypatch.setattr(importer.NP, 'make', lambda audio, proj, ana, **k: Path(proj).write_text('{}', encoding='utf-8'))
    F = {'gate': {'sep': threading.Event(), 'ana': threading.Event()}, 'started': {}, 'fail': set(), 'cmds': []}

    def fake(job, cmd, env=None, out=None):
        out = job if out is None else out
        cmd = [str(c) for c in cmd]
        kind = 'sep' if any(c.endswith('separate.py') for c in cmd) else 'ana' if 'automap.analyze_song' in cmd else 'other'
        F['cmds'].append(kind)
        out['log'] += f'$ {kind}\n'
        F['started'][kind] = time.time()
        if kind in F['gate']:
            while not F['gate'][kind].wait(0.01):
                if job.get('cancel') or out.get('stop'):
                    F['started'][kind + '-stopped'] = True
                    raise RuntimeError('やめた')
        if kind in F['fail']:
            out['log'] += f'{kind} がだめだった\n'
            raise RuntimeError('失敗した（終了コード 1）')
        out['log'] += f'{kind} 済み\n'
        if kind == 'sep':
            (cache / '曲' / 'separate.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(importer, 'run_cmd', fake)
    _, post = importer.routes(server)
    return server, post, F


def _start_fresh(server):
    steps = importer.plan(server, Path('x.wav'), '曲', '曲', '', info={'soundfile': True}, wait=True)
    return server.start_job('曲.intent-s1.nlmf', steps, kind=importer.KIND, song='曲', settings=importer.settings_of(LIB))


def test_analysis_runs_while_separating(fresh):
    """曲の解析は音を分ける段の間に裏で始まり（音を分ける段のうちに終わってよい）、記録は「曲の解析」の段に前と同じ並びで入る。
    画面には裏の段の様子（bg）が出る"""
    server, post, F = fresh
    j = _start_fresh(server)
    assert _until(lambda: 'ana' in F['started'] and 'sep' in F['started'])
    assert j['step'] == 0 and server.job_view(j)['bg'] == {'曲の解析': 'running'}   # 音を分ける段のまま、解析も動いている
    F['gate']['ana'].set()
    assert _until(lambda: j['bg']['曲の解析'] == 'done')
    assert j['step'] == 0 and 'ana 済み' not in j['log']   # 裏の記録は、まだ段の記録に入れない（今の段の最後の行＝音を分ける進み具合）
    F['gate']['sep'].set()
    assert _until(lambda: j['state'] != 'running') and j['state'] == 'done', j['log']
    log = j['log']
    assert log.index('== 音を分ける') < log.index('sep 済み') < log.index('== 曲の解析') < log.index('同時に進めた') < log.index('ana 済み') \
        < log.index('== 元のプロジェクトを作る')
    assert F['cmds'] == ['sep', 'ana', 'other'] or F['cmds'] == ['ana', 'sep', 'other']   # 解析は 1 回だけ（待つ段で動かし直さない）
    json.dumps(server.job_view(j))   # 裏の物（プロセス・印）は画面へ返さない


def test_analysis_failure_shows_at_its_step(fresh):
    """裏の解析が失敗しても音を分けるのは最後まで（分けた音は残る＝やり直しで使い回す）。失敗は「曲の解析」の段で出る"""
    server, post, F = fresh
    F['fail'].add('ana')
    F['gate']['ana'].set()
    j = _start_fresh(server)
    assert _until(lambda: j.get('bg', {}).get('曲の解析') == 'error')
    assert j['state'] == 'running' and j['step'] == 0
    F['gate']['sep'].set()
    assert _until(lambda: j['state'] != 'running')
    assert j['state'] == 'error' and j['steps'][j['step']] == '曲の解析' and 'ana がだめだった' in j['log']
    assert (server.CACHE / '曲' / 'separate.json').exists() and 'other' not in F['cmds']


def test_separation_failure_stops_analysis(fresh):
    """音を分けるのに失敗したら、裏の解析も止める（取り込みは音を分ける段で終わる）"""
    server, post, F = fresh
    F['fail'].add('sep')
    j = _start_fresh(server)
    assert _until(lambda: 'ana' in F['started'])
    F['gate']['sep'].set()
    assert _until(lambda: j['state'] != 'running')
    assert j['state'] == 'error' and j['step'] == 0 and 'sep がだめだった' in j['log']
    assert _until(lambda: F['started'].get('ana-stopped')) and _until(lambda: j['bg']['曲の解析'] == 'stopped')


def test_cancel_stops_both(fresh):
    """やめると、音を分けるのも裏の解析も止まる"""
    server, post, F = fresh
    j = _start_fresh(server)
    assert _until(lambda: 'ana' in F['started'] and 'sep' in F['started'])
    post['/api/import/cancel']({'id': j['id']})
    assert _until(lambda: j['state'] != 'running')
    assert j['state'] == 'error' and j['cancel'] and 'やめた' in j['log']
    assert _until(lambda: F['started'].get('sep-stopped') and F['started'].get('ana-stopped'))
    assert 'other' not in F['cmds'] and not (server.OUT / '曲.nlmf').exists()
