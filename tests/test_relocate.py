"""作業フォルダの引っ越し（app/relocate.py）: 中身を全部移す・ファイルの中の場所を書き換える・NLM で直された印を消さない・設定を切り替える・
別のドライブはコピーしてから元を消す・だめな引っ越し先は断る"""
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
from automap import config  # noqa: E402


def _work(tmp):
    """作り物の作業フォルダ: 結果のファイル 2 つ（アプリの書いたまま・NLM で直した）・分けた音・音を分ける部品"""
    import server   # noqa: F401  （cli の _state_path・_sha）
    from automap import __main__ as cli
    w = tmp / '作業'
    (w / 'out').mkdir(parents=True)
    (w / 'cache' / '曲' / 'source').mkdir(parents=True)
    (w / 'cache' / '曲' / 'source' / 'a.flac').write_bytes(b'x' * 1000)
    src = str(w / 'cache' / '曲' / 'source' / 'a.flac')
    for name in ('A.intent-s1.nlmf', 'B.intent-s1.nlmf'):
        p = w / 'out' / name
        p.write_text(json.dumps({'format': 'nlmf', 'graph': {'song': {'nativePath': src}}}, ensure_ascii=False), encoding='utf-8')
        if name.startswith('A'):   # アプリの書いたまま＝指紋を記録
            sp = cli._state_path(p)
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps({'sha256': cli._sha(p)}), encoding='utf-8')
    (w / 'parts' / 'separate').mkdir(parents=True)
    (w / 'parts' / 'separate' / 'state.json').write_text(json.dumps({'dir': str(w / 'parts' / 'separate')}), encoding='utf-8')
    (w / 'cache' / '曲' / 'big.bin').write_bytes(b'\0' * 50000)
    return w, cli


@pytest.fixture
def C(tmp_path):
    import server
    w, cli = _work(tmp_path)
    cfgp = tmp_path / 'config.json'
    config.update({'work_dir': str(w), 'sep_dir': str(w / 'parts' / 'separate'), 'keep': 1}, cfgp)
    ctx = types.SimpleNamespace(CONFIG=cfgp, JOBS={}, cli=cli, OUT=w / 'out', CACHE=w / 'cache')

    def start_job(file, steps, kind='', after=None, **meta):
        ctx.JOBS['x'] = job = dict(meta, id='x', kind=kind, state='running', log='')
        try:
            for _, fn in steps:
                fn(job)
            job['state'] = 'done'
        except Exception as e:   # noqa: BLE001
            job['state'], job['log'] = 'error', job['log'] + str(e)
        return job
    ctx.start_job = start_job
    import relocate
    return types.SimpleNamespace(ctx=ctx, w=w, cli=cli, R=relocate, tmp=tmp_path, cfgp=cfgp)


def _check_moved(C, new):
    cli = C.cli
    assert not C.w.exists()
    a, b = new / 'out' / 'A.intent-s1.nlmf', new / 'out' / 'B.intent-s1.nlmf'
    want = str(new / 'cache' / '曲' / 'source' / 'a.flac')
    for p in (a, b):
        assert json.loads(p.read_text(encoding='utf-8'))['graph']['song']['nativePath'] == want
    assert not cli._edited_since_written(a)          # アプリの書いたまま＝書き換えた後も書いたまま
    assert cli._edited_since_written(b)              # 記録が無い（NLM で直された扱い）＝そのまま
    assert json.loads((new / 'parts' / 'separate' / 'state.json').read_text(encoding='utf-8'))['dir'] == str(new / 'parts' / 'separate')
    cfg = config.load(C.cfgp)
    assert cfg['work_dir'] == str(new) and cfg['sep_dir'] == str(new / 'parts' / 'separate') and cfg['keep'] == 1
    assert C.ctx.OUT == new / 'out' and C.ctx.CACHE == new / 'cache'
    assert (new / 'cache' / '曲' / 'big.bin').stat().st_size == 50000


def test_move_same_drive(C):
    new = C.tmp / '新しい場所' / 'ANP'
    pl = C.R.plan(C.ctx, str(new))
    assert not pl['problems'] and pl['same_drive'] and pl['files'] >= 6
    job = C.R.start(C.ctx, {'new_dir': str(new)})
    assert C.ctx.JOBS[job['id']]['state'] == 'done', C.ctx.JOBS[job['id']]['log']
    _check_moved(C, new)


def test_move_other_drive_copies_then_deletes(C, monkeypatch):
    monkeypatch.setattr(C.R, '_same_drive', lambda a, b: False)
    new = C.tmp / 'other' / 'ANP'
    job = C.R.start(C.ctx, {'new_dir': str(new)})
    j = C.ctx.JOBS[job['id']]
    assert j['state'] == 'done' and 'コピーした' in j['log'] and '元の作業フォルダを消した' in j['log'], j['log']
    _check_moved(C, new)


def test_refuse_bad_targets(C):
    (C.tmp / 'full').mkdir()
    (C.tmp / 'full' / 'x.txt').write_text('x')
    for d, word in ((str(C.w / 'out' / 'sub'), '中'), (str(C.tmp / 'full'), '空ではありません'), ('relative', 'ドライブ名'), ('', 'ドライブ名')):
        pl = C.R.plan(C.ctx, d)
        assert any(word in x for x in pl['problems']), (d, pl['problems'])
        with pytest.raises(ValueError):
            C.R.start(C.ctx, {'new_dir': d})
    C.ctx.JOBS['busy'] = {'state': 'running', 'kind': 'generate'}
    assert any('作業中' in x for x in C.R.plan(C.ctx, str(C.tmp / 'n'))['problems'])
    del C.ctx.JOBS['busy']
    config.update({'work_dir': None}, C.cfgp)   # 開発の PC（作業フォルダを決めていない）は引っ越せない
    assert any('開発の PC' in x for x in C.R.plan(C.ctx, str(C.tmp / 'n'))['problems'])
