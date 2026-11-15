"""同じ音楽の区間（自動の同じ振り）を帯「作った譜面」に出す受け口（app/repeats.py・GET /api/repeats）: 作り直しの報告の
「同じ音楽の区間」の行を読む・基準と派生の報告の場所・報告が無い（no_report）・行が無い（none）・「見つからなかった」（ok で空）・
別の案と履歴の版（決めの場所と同じ選び方）・automap.repeat（numpy を読む）は使う時に読む"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from automap import diffs, repeat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))

# 報告の行は作る側と同じ書き方（repeat.report_line）で作る。自動1＝手本→左右反転・自動2＝手本→同じ→左右反転
G_BASE = [{'name': '自動1', 'bars': 3, 'occ': [(3, 15), (19, 31)], 'flip': 0},
          {'name': '自動2', 'bars': 2, 'occ': [(31, 39), (79, 87), (120, 128)], 'flip': 1}]
G_DER = [{'name': '自動1', 'bars': 4, 'occ': [(7, 23), (55, 71)], 'flip': 1}]


def _md(groups, extra=()):
    return '\n'.join(['# 報告', '', '- 打点 10', *filter(None, [repeat.report_line(groups)]), *extra, '', '## 意思入れ', '', '| 1〜2 | x |'])


@pytest.fixture
def app(tmp_path, monkeypatch):
    """写しの場所で server と repeats をつなぐ → (server, repeats, 結果のファイル)。基準の難易度は Hard（作業ファイルの diff）"""
    import server
    import repeats
    monkeypatch.setattr(server, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(server, 'CACHE', tmp_path / 'cache')
    (tmp_path / 'out').mkdir()
    p = tmp_path / 'out' / 'S.intent-s1.nlmf'
    p.write_bytes(b'{}')   # 中身は読まない（結果のファイルがあるか・名前だけ）
    server.save_work(p, {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}, 'diff': 'Hard'})
    return server, repeats, p


def _get(app, **q):
    server, repeats, p = app
    g, post = repeats.routes(server)
    assert post == {}
    return g['/api/repeats'](dict(q, file=p.name))


def test_base_and_derived_reports(app):
    server, repeats, p = app
    diffs.report_path(p).write_text(_md(G_BASE), encoding='utf-8')
    diffs.report_path(p, 'Expert').write_text(_md(G_DER), encoding='utf-8')
    r = _get(app)
    assert (r['file'], r['state'], r['diff'], r['derived']) == ('S.intent-s1.report.md', 'ok', 'Hard', False)
    assert r['groups'] == [
        {'name': '自動1', 'bars': 3, 'occ': [{'b0': 3.0, 'b1': 15.0, 'kind': 'model'}, {'b0': 19.0, 'b1': 31.0, 'kind': 'mirror'}]},
        {'name': '自動2', 'bars': 2, 'occ': [{'b0': 31.0, 'b1': 39.0, 'kind': 'model'}, {'b0': 79.0, 'b1': 87.0, 'kind': 'same'},
                                            {'b0': 120.0, 'b1': 128.0, 'kind': 'mirror'}]}]
    assert json.loads(json.dumps(r, ensure_ascii=False)) == r   # そのまま JSON で返せる
    d = _get(app, diff='Expert')   # 派生を見ている＝<結果>.<難易度>.report.md
    assert (d['file'], d['state'], d['diff'], d['derived']) == ('S.intent-s1.Expert.report.md', 'ok', 'Expert', True)
    assert d['groups'] == [{'name': '自動1', 'bars': 4, 'occ': [{'b0': 7.0, 'b1': 23.0, 'kind': 'model'}, {'b0': 55.0, 'b1': 71.0, 'kind': 'same'}]}]
    assert _get(app, diff='Hard') == r and _get(app, diff='hardstandard.dat') == r   # 基準の名前なら基準の報告
    n = _get(app, diff='Expert+')   # 派生の報告がまだ無い（展開していない）
    assert (n['file'], n['state'], n['groups'], n['derived']) == ('S.intent-s1.ExpertPlus.report.md', 'no_report', [], True)
    with pytest.raises(ValueError):
        _get(app, diff='Hardest')


def test_none_found_nothing_and_no_report(app):
    server, repeats, p = app
    assert _get(app) == {'file': 'S.intent-s1.report.md', 'diff': 'Hard', 'derived': False, 'state': 'no_report', 'groups': []}
    diffs.report_path(p).write_text(_md(None), encoding='utf-8')   # --no-auto-repeat・行を書く前の版＝行が無い
    assert (_get(app)['state'], _get(app)['groups']) == ('none', [])
    diffs.report_path(p).write_text(_md([]), encoding='utf-8')     # 探したが見つからなかった
    assert (_get(app)['state'], _get(app)['groups']) == ('ok', [])


def test_base_kind_when_result_missing(app, tmp_path):
    """結果のファイルがまだ無い曲は土台（試作5）の報告"""
    server, repeats, p = app
    p.unlink()
    b = tmp_path / 'out' / 'S.style-s1.nlmf'
    b.write_bytes(b'{}')
    diffs.report_path(b).write_text(_md(G_BASE), encoding='utf-8')
    r = _get(app)
    assert (r['file'], r['state'], len(r['groups'])) == ('S.style-s1.report.md', 'ok', 2)


def test_candidate_and_history_version(app, tmp_path):
    """別の案・履歴の版はその版の報告（決めの場所と同じ選び方・基準の難易度だけ＝diff は見ない）"""
    server, repeats, p = app
    out = tmp_path / 'out'
    diffs.report_path(p).write_text(_md(G_BASE), encoding='utf-8')
    diffs.report_path(p, 'Expert').write_text(_md(G_DER), encoding='utf-8')
    cd = out / '.cand' / 'S'
    cd.mkdir(parents=True)
    (cd / 'S.cand2.report.md').write_text(_md(G_DER), encoding='utf-8')
    hd = out / '.history' / 'S'
    hd.mkdir(parents=True)
    (hd / 'index.json').write_text(json.dumps([{'id': '20261111-000000-aaaa', 'sha': 'x', 'diff': 'Normal'},
                                               {'id': '20261111-000100-bbbb', 'sha': 'y'}]), encoding='utf-8')
    (hd / 'S.20261111-000000-aaaa.report.md').write_text(_md(G_DER), encoding='utf-8')
    c = _get(app, cand='2', diff='Expert')
    assert (c['file'], c['state'], c['diff'], c['derived']) == ('S.cand2.report.md', 'ok', 'Hard', False)
    assert c['groups'][0]['bars'] == 4
    v = _get(app, ver='20261111-000000-aaaa')
    assert (v['file'], v['state'], v['diff'], v['derived']) == ('S.20261111-000000-aaaa.report.md', 'ok', 'Normal', False)   # 控えた時の基準
    assert _get(app, ver='20261111-000100-bbbb')['state'] == 'no_report'
    assert _get(app, cand='3')['state'] == 'no_report'
    with pytest.raises(FileNotFoundError):
        _get(app, ver='20261111-999999-zzzz')
    with pytest.raises(ValueError):
        _get(app, ver='../x')


def test_out_file_only(app):
    """out/ の .nlmf だけ（外へ出る名前は断る＝400）"""
    server, repeats, _ = app
    for f in ('../x.nlmf', 'S.intent-s1.report.md'):
        with pytest.raises(ValueError):
            repeats.repeat_marks(server, {'file': f})


def test_connected_and_lazy():
    """server の connect() でつながる。repeats を読んだだけでは automap.repeat（rhythm → numpy）を読まない・使った時に読む"""
    import server
    server.connect()
    assert '/api/repeats' in server.GET_ROUTES
    prog = r'''
import sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + '/app')
import repeats
before = ['automap.repeat' in sys.modules, 'numpy' in sys.modules]
from types import SimpleNamespace
from pathlib import Path
md = '- 同じ音楽の区間（自動の同じ振り・docs/方針.md 6.31）: 自動1 2 小節: 拍 3（手本）→拍 11（同じ）'
d = Path(sys.argv[2]); d.mkdir(parents=True, exist_ok=True); p = d / 'S.intent-s1.nlmf'; p.write_bytes(b'{}')
(d / 'S.intent-s1.report.md').write_text(md, encoding='utf-8')
ctx = SimpleNamespace(out_file=lambda f: d / f, base_of=lambda q: q, file_diff=lambda q: 'ExpertPlus')
r = repeats.repeat_marks(ctx, {'file': p.name})
print(before, 'automap.repeat' in sys.modules, r['state'], len(r['groups']))
'''
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = subprocess.run([sys.executable, '-c', prog, str(ROOT), str(Path(td) / 'out')], capture_output=True, text=True,
                             encoding='utf-8', check=True, env=dict(os.environ, PYTHONIOENCODING='utf-8')).stdout.strip()
    assert out == '[False, False] True ok 1'
