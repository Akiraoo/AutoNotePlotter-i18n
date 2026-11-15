"""難易度の展開（app/expand.py・docs/アプリ仕様.md 17 節）: 難易度の一覧・基準の置き直し（id の付け直し・入れ替え）・作業の段
（控え・派生を並べて作る・結果・やめる・失敗）・報告の要点・量の既定の刻みの設定。compose は小さな台本に置き換える（作る側の中身は
tests/ の別のファイル）"""
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from automap import diffs, nlmf, njs
from automap import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
EP, EX = diffs.key('ExpertPlus'), diffs.key('Expert')

# 派生を作る compose の代わり: --diff の難易度に、元の譜面の 1 つおきのノーツを作ったクリップで（基準のクリップのレーンに）入れて報告を書く。
# 元の譜面＝基準。ただし割合 < 1 の時は、基準との間の難易度でノーツのある物か --derive-with の物のうち派生に一番近い物＝作る側の入れ子
# （derive.nest_pick）と同じく、ほかの難易度の今の譜面を読む（--derive-with の物は同じ決まりで作った見込み）。
# --sleep 秒・--fail 終了コード・--corrupt（読めないファイルを書く）・--add-lane（一番上にレーンを足す）・--njs（この難易度の NJS）
FAKE = r'''
import json, sys, time
sys.path.insert(0, {root!r})
from automap import diffs, nlmf
from automap import __main__ as cli
a = sys.argv[1:]
arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d
if arg('--sleep'):
    time.sleep(float(arg('--sleep')))
if arg('--wait-file'):   # テストが合図のファイルを作るまで待つ（時間に頼らずに「ほかの派生がまだ作っている間」を作る）
    t = time.time()
    while not __import__('os').path.exists(arg('--wait-file')) and time.time() - t < 60:
        time.sleep(0.05)
if arg('--fail'):
    print('わざと失敗', flush=True); sys.exit(int(arg('--fail')))
if '--corrupt' in a:   # 書いている途中で止まった（読めないファイル）
    open(arg('--out'), 'w', encoding='utf-8').write('{{"format":"nlmf","vers'); sys.exit(1)
out, d, base, r = arg('--out'), diffs.name_of(arg('--diff')), diffs.name_of(arg('--derive-from')), float(arg('--ratio'))
p = nlmf.load(out)
w = {{diffs.name_of(x.split('=')[0]): float(x.split('=')[1]) for x in (arg('--derive-with') or '').split(',') if x}}
has = lambda m: diffs.key(m) in p['difficulties'] and nlmf.clip_notes(p, diffs.key(m))
def make(d, r):
    src = base
    if r < 1:
        bi, ti = diffs.ORDER.index(base), diffs.ORDER.index(d)
        lo, hi = sorted((bi, ti))
        mid = [m for m in diffs.ORDER[lo + 1:hi] if m in w or has(m)]
        if mid:
            src = mid[0] if ti < bi else mid[-1]
    got = make(src, w[src])[0] if src in w else nlmf.clip_notes(p, diffs.key(src))
    return [n for i, n in enumerate(got) if i % 2 == 0], src
ns, src = make(d, r)
k = diffs.ensure(p, d, export=False)   # 書き出す印は付けない（展開の側が付ける）
st = p['difficulties'][k]
st['sections'] = [s for s in st.get('sections') or [] if s.get('lk') == 'l']
for f in nlmf.FLAT_N:
    st[f] = []
if arg('--njs'):   # compose が決めた NJS（njsCfg のこの難易度のキー）。ほかの難易度の NJS を写しで変えても本物へは入らない
    p.setdefault('njsCfg', {{}})[k] = {{'njs': float(arg('--njs')), 'offset': 0}}
    p['njsCfg'][diffs.key(base)] = {{'njs': 99, 'offset': 0}}
if '--add-lane' in a:
    nlmf.put_note_lane(p, {{k: cli._cover_clips(p, ns, 32)}})
else:
    lane = next(s.get('track') or 0 for s in nlmf.note_clips(p['difficulties'][diffs.key(base)]))
    nlmf.put_clips(p, k, cli._cover_clips(p, ns, 32), lane)
cli._save(p, __import__('pathlib').Path(out))
diffs.report_path(out, d).write_text('# 派生\n\n- 打点 %d（両手同時 0）\n- 量の割合 %s\n\n## 派生（%s から）\n\n- 基準の 1秒 4.00 → 2.00\n- 元 %s\n\n'
    '| | この難易度の譜面 |\n|---|---|\n| ノーツ | %d |\n| 1秒のノーツ | 2.00 |\n| 振りの交互の崩れ | 0%% |\n'
    '| NLM の振りの警告と同じ決まり（回） | 0 |\n' % (len(ns), arg('--ratio'), base, src, len(ns)), encoding='utf-8')
print('作った', d, len(ns), 'から', src, flush=True)
'''


def _notes(n=31, shift=0):
    return [{'beat': b + 0.0, 'x': (1 + (i % 2) + shift) % 4, 'y': 0, 'c': i % 2, 'd': 1 if (i // 2) % 2 == 0 else 0}
            for i, b in enumerate(range(1, n + 1))]


def _proj():
    """Expert+ に作ったクリップ（拍 0〜32・隙間なし）・Expert に利用者のクリップ 1 つ・Hard は空（NLM の新しいプロジェクトの既定）"""
    empty = lambda name: {'name': name, 'v3': True, 'base': {}, 'notes': [], 'bombs': [], 'walls': [], 'arcs': [], 'chains': [],
                          'lightEvents': [], 'sections': []}
    p = {'format': 'nlmf', 'version': 2, 'bpm': 120, 'tempoParts': [], 'current': 'ExpertPlusStandard.dat', 'notesLanes': 1,
         'lightLanes': 1, 'markers': [{'beat': 0, 'name': 'A'}, {'beat': 16, 'name': 'B'}],
         'laneStates': {'mute': [], 'solo': [], 'lock': []}, 'njsCfg': {EP: {'njs': 18, 'offset': 0}},
         'graph': {'out': {'diffs': {'ExpertPlus': 1}}}, 'infoGraph': {'nodes': {'s1': {'t': 'set', 'data': {'diffs': {'ExpertPlus': 1}}}}},
         'difficulties': {'hardstandard.dat': empty('HardStandard.dat'), EP: empty('ExpertPlusStandard.dat')}}
    nlmf.put_note_lane(p, {EP: cli._cover_clips(p, _notes(), 32)})
    return p


def _user_expert(p):
    """Expert に利用者のクリップ（NLM の id・ノーツ 2 つ）を足す"""
    st = diffs.ensure(p, 'Expert')
    p['difficulties'][st]['sections'] = [{'id': 'n123', 'beat': 0, 'track': 0, 'lk': 'n', 'len': 8, 'label': '手',
                                          'content': {'notes': [[1, 1, 0, 0, 1], [3, 2, 0, 1, 1]]}}]


@pytest.fixture
def app(tmp_path, monkeypatch):
    """写しの場所で server・versions・expand をつなぐ → (server, expand, 結果のファイル, compose の頼みの控え)"""
    import server
    import versions
    import expand
    monkeypatch.setattr(server, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(server, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'config.local.json')   # 本物の設定（利用者の PC の場所）を読まない・書かない
    (tmp_path / 'out').mkdir()
    versions.routes(server)
    expand.routes(server)
    fake = tmp_path / 'fake_compose.py'
    fake.write_text(FAKE.format(root=str(ROOT)), encoding='utf-8')
    calls = []

    def compose_cmd(p, intent_file, only=None, out=None, extra=(), diff=None):
        calls.append({'diff': diff, 'extra': [str(x) for x in extra], 'intent': Path(intent_file), 'p': Path(p), 'out': Path(out or p),
                      't': time.time()})
        return [sys.executable, str(fake), '--out', str(out or p), '--diff', diffs.name_of(diff), *[str(x) for x in extra]]
    monkeypatch.setattr(server, 'compose_cmd', compose_cmd)
    # 基準の NJS（expand.base_njs → cli._set_njs）: ★は測らず決まった値・設定は本物を読まない
    from automap import njs, rating
    stars = []
    monkeypatch.setattr(rating, 'measure_proj', lambda proj, diff='ExpertPlus', *a, **k: (stars.append(diff), {'ok': True, 'stars': 5.0})[1])
    monkeypatch.setattr(njs, 'CONFIG', tmp_path / 'config.local.json')
    monkeypatch.delenv('AUTOMAP_NJS_OFFSET', raising=False)
    monkeypatch.setattr(server, 'STARS_ASKED', stars, raising=False)
    # ★の口（app/rating）: 作り終えた派生から先に測る（expand._prerate）。本物の nlm-rating の代わりに ★＝ノーツの数 / 10
    import rating as AR
    AR.routes(server)
    rated = []
    monkeypatch.setattr(server, 'RATED', rated, raising=False)

    def fake_run(exe, req, timeout=300):
        dat = json.loads(req['files'][1]['text'])
        dn = req['targets'][0]['difficulty']
        rated.append((dn, time.time()))
        n = len(dat['colorNotes'])
        return {'ok': True, 'version': 't', 'results': [{'difficulty': dn, 'notes': n, 'skipped': None,
                                                         'ratings': {'none': {'stars': n / 10, 'pass': 1, 'tech': 1, 'acc': 1, 'predictedAcc': 0.9}}}]}
    monkeypatch.setattr(rating, 'run', fake_run)
    monkeypatch.setattr(rating, 'rating_exe', lambda: 'fake.exe')
    monkeypatch.setattr(rating, 'exe_version', lambda exe: 't')
    p = tmp_path / 'out' / 'T.intent-s1.nlmf'
    proj = _proj()
    _user_expert(proj)
    cli._save(proj, p)
    server.save_work(p, {'ranges': [{'b0': 8, 'b1': 16, 'set': {'amount': 1}}], 'line': [], 'auto_rest': {'on': False, 'b': None}})
    return server, expand, p, calls


def _wait(server, jid, t=60):
    t0 = time.time()
    while time.time() - t0 < t:
        j = server.job_view(server.JOBS[jid])
        if j['state'] != 'running':
            return j
        time.sleep(0.05)
    raise AssertionError('作業が終わらない')


def _stars(server, jid, t=30):
    """作業の進み具合の派生ごとの★（測り終えるまで待つ・★は別の流れで測る）"""
    t0 = time.time()
    while True:
        par = server.JOBS[jid].get('par') or []
        if all(r.get('stars') is not None for r in par) or time.time() - t0 > t:
            return {r['diff']: r.get('stars') for r in par}
        time.sleep(0.05)


def _with(server, monkeypatch, fn):
    """compose のコマンドに引数を足す（fn(難易度) → 足す引数）"""
    orig = server.compose_cmd
    monkeypatch.setattr(server, 'compose_cmd', lambda *a, **k: [*orig(*a, **k), *fn(diffs.name_of(k.get('diff')))])


def _diff_json(p, d):
    return json.dumps(nlmf.load(p)['difficulties'].get(diffs.key(d)), sort_keys=True, ensure_ascii=False)


def test_info_lists_kinds(app):
    server, X, p, _ = app
    d = X.info(p)
    assert d['base'] == 'ExpertPlus' and d['exists'] and not d['busy']
    assert d['step_pct'] == 10 and d['step_default'] == 10   # 設定が無ければ既定の刻み
    rows = {r['diff']: r for r in d['diffs']}
    assert [r['diff'] for r in d['diffs']] == diffs.ORDER
    assert not rows['Easy']['exists'] and rows['Hard']['exists'] and rows['Hard']['kind'] == 'empty'
    assert rows['ExpertPlus']['base'] and rows['ExpertPlus']['kind'] == 'auto' and rows['ExpertPlus']['notes'] == 31
    assert rows['ExpertPlus']['clips']['app'] == 2 and rows['ExpertPlus']['njs'] == 18 and rows['ExpertPlus']['nps'] == pytest.approx(31 / 15, abs=1e-3)
    assert rows['Expert']['kind'] == 'user' and rows['Expert']['clips']['user'] == 1 and rows['Expert']['notes'] == 2


def test_check_needs_swap_when_occupied(app):
    server, X, p, _ = app
    r = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Expert', 'targets': [], 'dry': True})
    assert r['need_swap'] and not r['ok']
    with pytest.raises(ValueError):
        X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Expert', 'targets': []})
    r = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Expert', 'swap': True, 'targets': [{'diff': 'ExpertPlus', 'ratio': 1.28}], 'dry': True})
    assert r['ok'] and r['swap'] and r['steps'] == ['控え', '基準を Expert に置き直す', 'Expert+ を作る']
    # 空の Hard へは入れ替えずに置き直せる・作る物が無いのはだめ・基準は派生にできない・量の範囲
    assert X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Hard', 'targets': [], 'dry': True})['ok']
    for bad in ([], [{'diff': 'ExpertPlus', 'ratio': 1}], [{'diff': 'Hard', 'ratio': 5}], [{'diff': 'Hard', 'ratio': 0.7}, {'diff': 'Hard', 'ratio': 0.6}]):
        with pytest.raises(ValueError):
            X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': bad, 'dry': True})


def test_deps_predict_or_wait():
    """待ち合わせ: 間引く派生の入れ子の相手（基準との間で一緒に作る派生）は、割合 < 1 なら見込む（待たない＝全部同時）・足す派生なら待つ。
    PREDICT が偽なら全部待つ（前の作り＝1つずつ作った時と同じ答え）"""
    import expand
    t = lambda d, r: {'diff': d, 'ratio': r}
    f = lambda base, ts, pr=None: {d: (x['after'], x['with']) for d, x in expand.deps(base, ts, pr).items()}
    assert f('ExpertPlus', [t('Expert', 0.9), t('Hard', 0.8)]) == {'Expert': ([], {}), 'Hard': ([], {'Expert': 0.9})}
    assert f('ExpertPlus', [t('Expert', 0.9), t('Hard', 0.8), t('Normal', 0.7)])['Normal'] == ([], {'Expert': 0.9, 'Hard': 0.8})
    assert f('Expert', [t('ExpertPlus', 1.1), t('Hard', 0.9), t('Normal', 0.8)]) == {'ExpertPlus': ([], {}), 'Hard': ([], {}), 'Normal': ([], {'Hard': 0.9})}
    assert f('Hard', [t('Expert', 1.1), t('ExpertPlus', 1.2)]) == {'Expert': ([], {}), 'ExpertPlus': ([], {})}   # 足す派生は読まない
    assert f('ExpertPlus', [t('Expert', 1.0), t('Hard', 0.8)])['Hard'] == (['Expert'], {})   # 間引かない相手は見込めない＝待つ
    assert f('ExpertPlus', [t('Expert', 0.9), t('Hard', 0.8), t('Normal', 0.7)], False) == {
        'Expert': ([], {}), 'Hard': (['Expert'], {}), 'Normal': (['Expert', 'Hard'], {})}


def test_move_base_reids_app_clips(app):
    """置き直すと、作ったままのクリップは移した先の難易度のキーで id を付け直す（付け直さないと全部「手で直した」に見える）。
    入れ替えた先の利用者のクリップはそのまま。書き出す印・NJS・開いている難易度・派生の報告も一緒に移る"""
    server, X, p, _ = app
    diffs.report_path(p, 'Expert').write_text('# Expert の報告\n', encoding='utf-8')
    n = X.move_base(p, 'ExpertPlus', 'Expert', swap=True)
    assert n == 2
    proj = nlmf.load(p)
    sts = [st for _, st in nlmf.classify(proj, EX)[0]]
    assert sts == ['app', 'app']
    assert [st for _, st in nlmf.classify(proj, EP)[0]] == ['user']
    assert proj['current'] == 'ExpertStandard.dat' and proj['njsCfg'] == {EX: {'njs': 18, 'offset': 0}}
    assert diffs.export_marks(proj) == {'ExpertPlus': 1, 'Expert': 1}   # 入れ替え＝Expert の印（利用者の譜面に付けた）も Expert+ へ
    assert not cli._edited_since_written(p)   # 書いた時の指紋も
    assert diffs.report_path(p, 'ExpertPlus').read_text(encoding='utf-8') == '# Expert の報告\n' and not diffs.report_path(p, 'Expert').exists()
    # 戻すと元の id に戻る（指紋は中身と難易度のキーだけで決まる）
    X.move_base(p, 'Expert', 'ExpertPlus', swap=True)
    assert [st for _, st in nlmf.classify(nlmf.load(p), EP)[0]] == ['app', 'app']


def test_expand_job_makes_derived(app):
    server, X, p, calls = app
    before = {d: _diff_json(p, d) for d in ('ExpertPlus',)}
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus',
                 'targets': [{'diff': 'Hard', 'ratio': 0.61, 'library': {'stars': [0, 4], 'sources': ['ranked']}}, {'diff': 'Expert', 'ratio': 0.78}]})
    assert j['steps'] == ['控え', 'Expert・Hard を作る（並べて）']
    with pytest.raises(ValueError):   # 作っている間は断る
        X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.61}], 'dry': True})
    v = _wait(server, j['id'])
    assert v['state'] == 'done', v['log']
    cs = {c['diff']: c for c in calls}
    assert sorted(cs) == ['Expert', 'Hard'] and abs(cs['Expert']['t'] - cs['Hard']['t']) < 1.0   # 同時に始める
    # 写しの基準（Expert+）は NLM で決めた 18（auto の印が無い）＝派生の NJS はその値から（app/njsbase.py・最後に決めた方が勝つ）
    assert cs['Expert']['extra'][:4] == ['--derive-from', 'ExpertPlus', '--ratio', '0.78'] and cs['Expert']['extra'][6:8] == ['--njs-base', '18']
    # 行の型の範囲が無い派生は曲の設定（この曲は設定が無い＝新しい曲の既定・前は --library 無し＝今の型）
    # 設定の無い曲（前からある曲）は前の決め方の自動（DEFAULT_V1・2026-11-15＝今の曲の年の組を変えない）
    assert cs['Expert']['extra'][4] == '--library' and json.loads(cs['Expert']['extra'][5]) == X.LU.DEFAULT_V1
    assert cs['Hard']['extra'][:6] == ['--derive-from', 'ExpertPlus', '--ratio', '0.61', '--derive-with', 'Expert=0.78']   # 入れ子の相手は見込む
    assert cs['Hard']['extra'][6] == '--library' and json.loads(cs['Hard']['extra'][7])['stars'] == [0, 4]
    calls = [cs['Expert'], cs['Hard']]
    assert not calls[0]['intent'].exists()   # 意思入れの表の一時ファイルは消した
    # compose の入力と --out は派生ごとの作業用の写し（本物ではない）・終わったら写しは消した
    assert all(c['p'] == c['out'] and c['out'] != p and c['out'].name == p.name and '.expand' in c['out'].parts for c in calls)
    assert calls[0]['out'] != calls[1]['out'] and not (p.parent / '.expand').exists()
    assert [r['state'] for r in v['par']] == ['done', 'done'] and v['par'][1]['after'] == [] and v['par'][1]['with'] == ['Expert']
    res = {r['diff']: r for r in v['results']}
    assert res['Expert']['notes'] == 16 and res['Hard']['notes'] == 8   # Hard は作る Expert の見込みから（作る前の Expert は利用者の 2 ノーツ）
    a = nlmf.load(p)
    assert {n['beat'] for n in nlmf.clip_notes(a, diffs.key('Hard'))} <= {n['beat'] for n in nlmf.clip_notes(a, EX)}   # 入れ子
    assert '元 Expert' in res['Hard']['report'] and res['Hard']['nums']['warn'] == '0' and res['Hard']['derive'][0] == '基準の 1秒 4.00 → 2.00'
    assert res['Hard']['want'] == 0.61
    assert Path(v['backup']).exists() and '.展開前.' in Path(v['backup']).name and Path(v['backup']).parent.name == 'old'
    import versions
    top = versions.list_versions(p)['versions'][0]
    assert top['kind'] == 'expand' and top['current'] and 'Expert・Hard' in top['title']
    d = {r['diff']: r for r in X.info(p)['diffs']}
    assert d['Hard']['kind'] == 'auto' and d['Hard']['report'] and d['ExpertPlus']['notes'] == 31   # 基準は触らない
    assert {k: _diff_json(p, k) for k in before} == before
    assert d['Hard']['export'] and d['Expert']['export'] and 'Hard に書き出す印を付けた' in v['log']
    assert not cli._edited_since_written(p)   # 入れ替えて保存した時の指紋も


def test_parallel_runs_together_and_equals_sequential(app, monkeypatch, tmp_path):
    """上と下は同時に作る（並べる）。答えは同じ設定で1つずつ順に作った物と同じ（派生の中身・書き出す印）・基準とほかの難易度は1ビットも変わらない"""
    server, X, p, calls = app
    seq = tmp_path / 'seq' / p.name   # 1つずつ順に（前の作り方）: 同じ結果のファイルへ上の近い順 → 下の近い順
    seq.parent.mkdir()
    shutil.copy2(p, seq)
    _with(server, monkeypatch, lambda d: ['--sleep', '1.5'])
    ts = [{'diff': 'ExpertPlus', 'ratio': 1.2}, {'diff': 'Hard', 'ratio': 0.8}, {'diff': 'Normal', 'ratio': 0.7}]
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Expert', 'swap': True, 'targets': ts})
    v = _wait(server, j['id'])
    assert v['state'] == 'done', v['log']
    st = {c['diff']: c['t'] for c in calls}
    assert max(st.values()) - min(st.values()) < 1.0   # 3 つとも同時に始める（Normal の入れ子の相手 Hard は見込む）
    assert v['par'][2]['after'] == [] and v['par'][2]['with'] == ['Hard']
    # 3 つの作業の時間が重なる（どれかが終わる前に全部始まっている）。前は「全体で 4.4 秒未満」（1 つ 1.5 秒＋起動）と見ていたが、
    # テストを並べて流すと CPU が混んで子のプロセスの起動が延び、順に作っていなくても超えた
    assert max(r['started'] for r in v['par']) < min(r['started'] + r['took'] for r in v['par'])
    import subprocess
    X.move_base(seq, 'ExpertPlus', 'Expert', True)
    for t in sorted(ts, key=lambda t: (diffs.steps('Expert', t['diff']) < 0, abs(diffs.steps('Expert', t['diff'])))):
        w = X.deps('Expert', ts)[t['diff']]['with']
        cmd = server.compose_cmd(seq, Path('x'), out=seq, diff=t['diff'], extra=['--derive-from', 'Expert', '--ratio', f'{t["ratio"]:g}',
                                 *(['--derive-with', ','.join(f'{e}={r:g}' for e, r in w.items())] if w else [])])
        subprocess.run([str(c) for c in cmd if c != '--sleep' and c != '1.5'], check=True, capture_output=True)
        X.mark_export(seq, t['diff'])
    a, b = nlmf.load(p), nlmf.load(seq)
    for d in diffs.ORDER:
        assert json.dumps(a['difficulties'].get(diffs.key(d)), sort_keys=True) == json.dumps(b['difficulties'].get(diffs.key(d)), sort_keys=True), d
    assert diffs.export_marks(a) == diffs.export_marks(b) and a['notesLanes'] == b['notesLanes'] == 1


def test_cancel_stops_all(app, monkeypatch):
    """やめる: 動いている compose を全部止め、待っている派生は作らない"""
    server, X, p, _ = app
    _with(server, monkeypatch, lambda d: ['--sleep', '20'])
    before = p.read_bytes()
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Expert', 'swap': True,
                 'targets': [{'diff': 'ExpertPlus', 'ratio': 1.2}, {'diff': 'Hard', 'ratio': 0.8}, {'diff': 'Normal', 'ratio': 0.6}]})
    time.sleep(1.5)
    t0 = time.time()
    X.cancel({'id': j['id']})
    v = _wait(server, j['id'], 15)
    assert v['state'] == 'error' and 'やめた' in v['log'] and time.time() - t0 < 10
    assert not v.get('results') and v['made'] == [] and v['moved']
    assert {r['diff']: r['state'] for r in v['par']} == {'ExpertPlus': 'cancelled', 'Hard': 'cancelled', 'Normal': 'cancelled'}
    assert not (p.parent / '.expand').exists() and p.read_bytes() != before   # 置き直しは済んでいる（派生は入れない）


@pytest.mark.parametrize('predict', [True, False])
def test_failure_keeps_the_others(app, monkeypatch, predict):
    """1つが失敗しても、ほかはそのまま終わらせて入れる・写しは記録に残す。失敗した派生を待っていた派生は作らない（見込む時は待たない）"""
    server, X, p, _ = app
    monkeypatch.setattr(X, 'PREDICT', predict)
    _with(server, monkeypatch, lambda d: ['--fail', '3'] if d == 'Hard' else [])
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Expert', 'swap': True,
                 'targets': [{'diff': 'ExpertPlus', 'ratio': 1.2}, {'diff': 'Hard', 'ratio': 0.8}, {'diff': 'Normal', 'ratio': 0.6}]})
    v = _wait(server, j['id'])
    assert v['state'] == 'error' and '終了コード 3' in v['log'] and 'わざと失敗' in v['log'] and v['step'] == 2
    made = ['ExpertPlus', 'Normal'] if predict else ['ExpertPlus']
    assert {r['diff']: r['state'] for r in v['par']} == {'ExpertPlus': 'done', 'Hard': 'error', 'Normal': 'done' if predict else 'skipped'}
    assert [r['diff'] for r in v['results']] == made and v['made'] == made and not v.get('restored')
    assert len(nlmf.clip_notes(nlmf.load(p), EP)) == 16 and (p.parent / '.expand' / j['id']).exists()
    assert f'.expand/{j["id"]}/' in v['log']


def test_broken_copy_never_breaks_the_result(app, monkeypatch):
    """compose が書いている途中で止まっても壊れるのは写しだけ（本物の結果のファイルは読める・できた派生は入れる）"""
    server, X, p, _ = app
    _with(server, monkeypatch, lambda d: ['--corrupt'] if d == 'Hard' else [])
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Expert', 'swap': True, 'targets': [{'diff': 'ExpertPlus', 'ratio': 1.2}, {'diff': 'Hard', 'ratio': 0.6}]})
    v = _wait(server, j['id'])
    assert v['state'] == 'error' and v['moved'] and v['made'] == ['ExpertPlus'] and not v.get('restored')
    proj = nlmf.load(p)
    assert len(nlmf.clip_notes(proj, EX)) == 31 and len(nlmf.clip_notes(proj, EP)) == 16 and not nlmf.clip_notes(proj, diffs.key('Hard'))


def test_broken_file_is_restored(app):
    """結果のファイルが読めなくなっていたら（置き直しの保存の途中で止まった等）展開の前の控えに戻す"""
    server, X, p, _ = app
    before = p.read_bytes()
    job = {'log': ''}
    X.backup(p, job)
    p.write_text('{"format":"nlmf","vers', encoding='utf-8')
    assert X.restore_if_broken(p, job) and job['restored']
    assert p.read_bytes() == before and not cli._edited_since_written(p)


def test_njs_of_the_derived_is_swapped(app, monkeypatch):
    """入れ替えるのは派生の難易度の njsCfg の項目だけ（写しに無ければ本物のまま・ほかの難易度の NJS は本物のまま）"""
    server, X, p, _ = app
    _with(server, monkeypatch, lambda d: ['--njs', '10.5'] if d == 'Hard' else [])
    proj = nlmf.load(p)
    proj['njsCfg'][EX] = {'njs': 13, 'offset': 0.2}   # 利用者が NLM で決めた Expert の NJS（Expert の写しは NJS を書かない）
    cli._save(proj, p)
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Expert', 'ratio': 0.9}, {'diff': 'Hard', 'ratio': 0.8}]})
    v = _wait(server, j['id'])
    assert v['state'] == 'done', v['log']
    assert nlmf.load(p)['njsCfg'] == {EP: {'njs': 18, 'offset': 0}, EX: {'njs': 13, 'offset': 0.2}, diffs.key('Hard'): {'njs': 10.5, 'offset': 0}}
    a, b = {'difficulties': {diffs.key('Hard'): {}}}, {'difficulties': {diffs.key('Hard'): {'x': 1}}, 'njsCfg': {diffs.key('Hard'): 11}}
    X.put_diff(a, b, 'Hard')   # 本物に njsCfg が無くても足す
    assert a['njsCfg'] == {diffs.key('Hard'): 11} and a['difficulties'][diffs.key('Hard')] == {'x': 1}


def _set_base_njs(p, e):
    proj = nlmf.load(p)
    if e is None:
        proj['njsCfg'].pop(EP, None)
    else:
        proj['njsCfg'][EP] = e
    cli._save(proj, p)


@pytest.mark.usefixtures('pinned_scale')
def test_base_njs_written_when_missing(app):
    """基準の NJS が無い（NJS の仕組みより前に作った基準）→ 展開で作り直しと同じ式の値を書く（2026-11-03 ハロのハードが NLM の既定 10 のまま）。
    ★5・BPM 120・Expert+ ＝ 8.57＋2.69＋1.40＋3.61 → 16.5"""
    server, X, p, _ = app
    _set_base_njs(p, None)
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.8}]})['id'])
    assert v['state'] == 'done', v['log']
    e = nlmf.load(p)['njsCfg'][EP]
    assert (e['njs'], e['auto'], e['offset'], e['auto_offset']) == (16.5, 16.5, njs.offset_for('ExpertPlus', 16.5, 120), njs.offset_for('ExpertPlus', 16.5, 120))
    assert '基準（Expert+）の NJS: 16.5（★5.00・BPM 120・Expert+から式で）・JD 18.5m' in v['log']   # 見え始める距離もその NJS で狙いの値に and server.STARS_ASKED == ['ExpertPlus']
    assert not cli._edited_since_written(p)


@pytest.mark.usefixtures('pinned_scale')
def test_base_njs_rewritten_after_move(app):
    """アプリが書いた NJS（auto と同じ）は基準を置き直すと移した先の難易度の式で書き直す（Expert+ の 16.5 のまま Hard にしない）。
    派生を作らない置き直しだけでも"""
    server, X, p, _ = app
    _set_base_njs(p, {'njs': 16.5, 'offset': 0.25, 'auto': 16.5})
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Hard', 'targets': []})['id'])
    assert v['state'] == 'done', v['log']
    nj = nlmf.load(p)['njsCfg']
    assert nj[diffs.key('Hard')] == {'njs': 14.5, 'offset': 0.25, 'auto': 14.5} and EP not in nj   # オフセットは今のまま


def test_base_njs_keeps_the_nlm_value(app):
    """NLM で利用者が決めた基準の NJS（auto と違う・auto が無い）は書き換えない・★も測らない"""
    server, X, p, _ = app
    _set_base_njs(p, {'njs': 13, 'offset': 0, 'auto': 16.5})
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.8}]})['id'])
    assert v['state'] == 'done', v['log']
    e = nlmf.load(p)['njsCfg'][EP]
    assert (e['njs'], e['auto'], e['offset']) == (13, 16.5, njs.offset_for('ExpertPlus', 13, 120))   # NJS は NLM の値・オフセットはまだ誰も決めていない＝整える
    assert '基準（Expert+）の NJS: 13（NLM で決めた値のまま）・JD' in v['log']
    # 基準の NJS のためには★を測らない。派生の元（NLM で直した 13＋派生の式−基準の式）の基準の式だけ測る（今の速さ → 式の値の速さ）
    assert server.STARS_ASKED == ['ExpertPlus', 'ExpertPlus'] and 'NLM で直した基準の NJS 13 から' in v['log']


@pytest.mark.usefixtures('pinned_scale')
def test_base_njs_keeps_the_edited_mark(app):
    """NLM で直された後のファイルに基準の NJS を書いても「NLM で直された」の判定はそのまま（書いた時の指紋を残さない）"""
    server, X, p, _ = app
    proj = nlmf.load(p)
    proj['njsCfg'].pop(EP)
    nlmf.save(proj, p)   # NLM で保存した（指紋が合わない）
    assert cli._edited_since_written(p)
    assert X.base_njs(p, 'ExpertPlus') and nlmf.load(p)['njsCfg'][EP]['njs'] == 16.5
    assert cli._edited_since_written(p)
    assert not X.base_njs(p, 'ExpertPlus')   # 2 回目は同じ値＝書かない


def test_lane_change_is_refused(app, monkeypatch):
    """写しでレーンが足された派生は入れ替えない（ほかの難易度の番号がずれる）"""
    server, X, p, _ = app
    _with(server, monkeypatch, lambda d: ['--add-lane'] if d == 'Hard' else [])
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.6}]})
    v = _wait(server, j['id'])
    assert v['state'] == 'error' and 'レーンの数が違う' in v['log'] and v['made'] == []
    proj = nlmf.load(p)
    assert proj['notesLanes'] == 1 and not nlmf.clip_notes(proj, diffs.key('Hard'))


def test_stars_start_when_each_derived_is_made(app, monkeypatch, tmp_path):
    """★は作り終えた派生から測り始める（2026-11-09 利用者）: Hard が先にできたら、Expert がまだ作っている間に Hard の★が進み具合に出る。
    答えの控えは中身の指紋＝本物へ入れた後に聞くと測り直さずに同じ★（基準も先に測ってある）"""
    server, X, p, _ = app
    go = tmp_path / 'go'
    _with(server, monkeypatch, lambda d: ['--wait-file', str(go)] if d == 'Expert' else [])
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Expert', 'ratio': 0.9}, {'diff': 'Hard', 'ratio': 0.8}]})
    t0 = time.time()
    try:
        while True:   # Hard の★が出るまで（Expert は合図を待っている＝まだ作っている）
            par = {r['diff']: r for r in server.job_view(server.JOBS[j['id']]).get('par') or []}
            if isinstance((par.get('Hard') or {}).get('stars'), float):
                break
            assert time.time() - t0 < 60, par
            time.sleep(0.05)
        assert par['Expert']['state'] == 'running' and par['Hard']['state'] == 'done' and par['Hard']['stars'] == 0.8   # 見込んだ Expert の半分＝8 ノーツ
        assert ('Hard', ) == tuple(d for d, _ in server.RATED if d != 'ExpertPlus')   # Expert はまだ測っていない（基準は先に測る）
    finally:
        go.write_text('1', encoding='utf-8')
    v = _wait(server, j['id'])
    assert v['state'] == 'done', v['log']
    assert _stars(server, j['id']) == {'Expert': 1.6, 'Hard': 0.8}   # 作業は★を待たずに終わる（最後の派生の★は画面が聞いて待つ）
    n = len(server.RATED)
    assert sorted(d for d, _ in server.RATED) == ['Expert', 'ExpertPlus', 'Hard']
    import rating as AR
    for d, s in (('Expert', 1.6), ('Hard', 0.8), ('ExpertPlus', 3.1)):   # 本物のファイルを聞く＝控えからすぐ（測り直さない）
        a = AR.rate(p, wait=5, diff=d)
        assert a['state'] == 'done' and a['stars'] == s, (d, a)
    assert len(server.RATED) == n


def test_stars_of_a_refused_copy_are_not_the_result(app, monkeypatch):
    """入れなかった派生（レーンの数が違う）は写しの★を測っても、本物のファイルのその難易度の★にはならない（中身が違う＝別の指紋）"""
    server, X, p, _ = app
    _with(server, monkeypatch, lambda d: ['--add-lane'] if d == 'Hard' else [])
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.6}]})['id'])
    assert v['state'] == 'error' and v['made'] == [] and _stars(server, v['id']) == {'Hard': 0.1}   # 写しの Hard（間の Expert の 2 ノーツから 1）は測った
    import rating as AR
    a = AR.rate(p, wait=5, diff='Hard')   # 本物の Hard は空のまま
    assert a['state'] == 'done' and a['stars'] == 0 and a['notes'] == 0


def test_no_prerate_without_the_rating_route(app, monkeypatch):
    """★の口がつながっていない（別の口のまま）・PRERATE が偽なら先に測らない（前と同じ）"""
    server, X, p, _ = app
    monkeypatch.setattr(X, 'PRERATE', False)
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.6}]})['id'])
    assert v['state'] == 'done' and 'stars' not in v['par'][0] and server.RATED == []


def test_result_changed_during_expand_is_backed_up(app, monkeypatch):
    """展開の間に結果のファイルが変わっていたら（NLM で保存した）、入れ替える前に控え・派生の難易度だけ入れ替える（ほかの直しは残る）"""
    server, X, p, _ = app
    _with(server, monkeypatch, lambda d: ['--sleep', '1.2'])
    j = X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.6}]})
    time.sleep(0.6)
    proj = nlmf.load(p)
    proj['markers'].append({'beat': 24, 'name': 'C'})
    nlmf.save(proj, p)
    v = _wait(server, j['id'])
    assert v['state'] == 'done', v['log']
    assert '展開中に変わった' in v['log'] and list((p.parent / 'old').glob('*.展開中に変わった.*.nlmf'))
    proj = nlmf.load(p)
    assert proj['markers'][-1]['name'] == 'C' and len(nlmf.clip_notes(proj, diffs.key('Hard'))) == 1   # 間の Expert（利用者の 2 ノーツ）から


def test_summary_reads_report():
    from expand import summary
    md = ('# 意思入れ\n\n- 土台: a.nlmf\n- 打点 120（両手同時 3）\n\n## 派生（Expert+ から Hard）\n\n- 間引いた 40\n- **量** 0.61 倍\n\n'
          '## 打ち方の数字\n\n| | この難易度の譜面 |\n|---|---|\n| ノーツ | 120 |\n| 1秒のノーツ | 2.31 |\n| 両手同時 | 3% |\n'
          '| 振りの交互の崩れ | 0% |\n| 同じ手が0.12秒未満で続く（回） | 0 |\n| NLM の振りの警告と同じ決まり（回） | 1 |\n\n## 曲の個性\n\n- 何か\n')
    s = summary(md)
    assert s['head'] == ['土台: a.nlmf', '打点 120（両手同時 3）']
    assert s['derive'] == ['間引いた 40', '量 0.61 倍']
    assert s['nums'] == {'notes': '120', 'nps': '2.31', 'both': '3%', 'broken': '0%', 'fast': '0', 'warn': '1'}


def test_plans_memo_and_step(app, monkeypatch):
    """派生の既定: 型の範囲は覚えて使い回す（刻みを変えても数え直さない）・量は刻み（設定・頼みの step_pct）から"""
    server, X, p, _ = app
    from automap import derive
    n = []
    monkeypatch.setattr(derive, 'default_plan', lambda b, t, lib, step=None: (n.append(t), {
        'ratio': diffs.ratio(b, t, step), 'library': None, 'note': 'x', 'lib_note': '型 x'})[1])
    r = X.plans({'file': p.name, 'base': 'Expert', 'targets': ['ExpertPlus', 'Hard', 'Expert']})
    assert set(r['plans']) == {'ExpertPlus', 'Hard'} and r['plans']['Hard']['short'] == X.LU.label(None, True) and r['step_pct'] == 10
    assert r['plans']['Hard']['ratio'] == 0.9 and r['plans']['ExpertPlus']['ratio'] == 1.1 and r['plans']['Hard']['note'].endswith('・型 x')
    r = X.plans({'file': p.name, 'base': 'Expert', 'targets': ['ExpertPlus', 'Hard'], 'step_pct': 15})
    assert r['plans']['Hard']['ratio'] == 0.85 and r['plans']['ExpertPlus']['ratio'] == 1.15 and '1段 15%' in r['plans']['Hard']['note']
    assert sorted(n) == ['ExpertPlus', 'Hard']   # 2 回目・3 回目は覚えた物
    X.set_step({'step_pct': 20})
    assert X.plans({'file': p.name, 'base': 'ExpertPlus', 'targets': ['Easy']})['plans']['Easy']['ratio'] == pytest.approx(0.2)   # 端まで


def test_step_setting_keeps_other_items(app):
    """「既定にする」: 設定のほかの項目・字下げ・行の終わり（CRLF）はそのまま expand_step_pct だけ書く・範囲の外と読めない設定は断る"""
    server, X, p, _ = app
    cfg = server.CONFIG
    assert X.step_pct() == 10   # 設定のファイルが無い
    cfg.write_bytes('{\r\n "nlm_exe": "C:\\\\x\\\\NLM.exe",\r\n "library_own": [\r\n  "yama-*"\r\n ]\r\n}\r\n'.encode('utf-8'))
    assert X.set_step({'step_pct': '12.5'}) == {'ok': True, 'step_pct': 12.5}
    raw = cfg.read_bytes().decode('utf-8')
    assert json.loads(raw) == {'nlm_exe': 'C:\\x\\NLM.exe', 'library_own': ['yama-*'], 'expand_step_pct': 12.5}
    assert raw.count('\r\n') == raw.count('\n') and raw.startswith('{\r\n "nlm_exe"') and not list(cfg.parent.glob('*.tmp'))
    assert X.step_pct() == 12.5 and X.info(p)['step_pct'] == 12.5
    X.set_step({'step_pct': 10})
    assert json.loads(cfg.read_text(encoding='utf-8'))['expand_step_pct'] == 10
    for bad in (0, 60, 'x', None):
        with pytest.raises(ValueError):
            X.set_step({'step_pct': bad})
    cfg.write_text('{"nlm_exe": ', encoding='utf-8')   # 読めない設定は書き換えない（利用者の設定を壊さない）
    with pytest.raises(ValueError):
        X.set_step({'step_pct': 15})
    assert cfg.read_text(encoding='utf-8') == '{"nlm_exe": ' and X.step_pct() == 10


# ---- 3D で決めた基準の NJS（作業ファイルの njs.base・app/njsbase.py・2026-11-09） ----

def _decide(server, p, v):
    w = server.load_work(p)
    w['njs'] = {'base': v}
    server.save_work(p, w)


@pytest.mark.usefixtures('pinned_scale')
def test_base_njs_uses_the_decided_value(app):
    """3D で決めた基準の NJS があれば、展開の前の基準の NJS は式ではなくその値そのまま（★も測らない）・置き直した基準にも付いていく"""
    server, X, p, _ = app
    _decide(server, p, 17)
    _set_base_njs(p, None)
    assert X.base_njs(p, 'ExpertPlus') and {k: v for k, v in nlmf.load(p)['njsCfg'][EP].items() if 'offset' not in k} == {'njs': 17.0, 'auto': 17.0}
    assert server.STARS_ASKED == []
    _set_base_njs(p, {'njs': 18, 'offset': 0.5, 'auto': 17})   # ON の後で NLM で直した＝NLM の値が勝つ（オフセットも NLM で決めた）
    assert not X.base_njs(p, 'ExpertPlus') and nlmf.load(p)['njsCfg'][EP] == {'njs': 18, 'offset': 0.5, 'auto': 17}
    _set_base_njs(p, {'njs': 16.5, 'offset': 0.25, 'auto': 16.5})
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'Hard', 'targets': []})['id'])   # 置き直すだけ
    assert v['state'] == 'done', v['log']
    assert nlmf.load(p)['njsCfg'][diffs.key('Hard')] == {'njs': 17.0, 'offset': 0.25, 'auto': 17.0}


@pytest.mark.usefixtures('pinned_scale')
def test_derived_get_njs_from_the_decided_base(app):
    """派生の compose には 決めた値と基準の式の値（1 回だけ測る）を渡す（派生の NJS＝決めた値＋派生の式−基準の式は作る側）。
    基準の式＝★5・BPM 120・Expert+ → 16.5。決めていなければ渡さない（前と同じ）"""
    server, X, p, calls = app
    _set_base_njs(p, None)   # 写しの基準は NLM で決めた 18（auto の印が無い）＝消してアプリが書く
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.8}]})['id'])
    assert v['state'] == 'done', v['log']
    assert not any('--njs-base' in c['extra'] for c in calls)
    _decide(server, p, 17)
    calls.clear()
    server.STARS_ASKED.clear()
    v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus',
                               'targets': [{'diff': 'Hard', 'ratio': 0.8}, {'diff': 'Expert', 'ratio': 0.9}]})['id'])
    assert v['state'] == 'done', v['log']
    for c in calls:
        e = c['extra']
        assert e[e.index('--njs-base') + 1] == '17' and e[e.index('--njs-base-formula') + 1] == '16.5', e
    assert {k: v for k, v in nlmf.load(p)['njsCfg'][EP].items() if 'offset' not in k} == {'njs': 17.0, 'auto': 17.0}
    # 基準の式は今の速さ（17）で測ってから式の値（16.5）の速さで測り直す（njs.settle）
    assert server.STARS_ASKED == ['ExpertPlus', 'ExpertPlus'] and '3D で決めた基準の NJS 17 から（基準の式 16.5' in v['log']
    rows = {r['diff']: r for r in X.info(p)['diffs']}
    assert rows['ExpertPlus']['njs_decided'] == 17 and not rows['ExpertPlus']['njs_user'] and 'njs_decided' not in rows['Hard']


@pytest.mark.usefixtures('pinned_scale')
def test_derived_follow_the_nlm_value_of_the_base(app):
    """基準が NLM で直されていれば（写しの Expert+ は NLM で決めた 18）、3D の「譜面に使う」が OFF でも派生はその値から
    （compose に --njs-base 18・基準の式 16.5）。3D で決めた 17 があっても NLM の値が勝つ（最後に決めた方）。基準の NJS は触らない"""
    server, X, p, calls = app
    for decided in (None, 17):
        if decided is not None:
            _decide(server, p, decided)
        calls.clear()
        v = _wait(server, X.start({'file': p.name, 'from': 'ExpertPlus', 'base': 'ExpertPlus', 'targets': [{'diff': 'Hard', 'ratio': 0.8}]})['id'])
        assert v['state'] == 'done', v['log']
        e = calls[0]['extra']
        assert e[e.index('--njs-base') + 1] == '18' and e[e.index('--njs-base-formula') + 1] == '16.5', e
        assert nlmf.load(p)['njsCfg'][EP] == {'njs': 18, 'offset': 0} and 'NLM で直した基準の NJS 18 から' in v['log']
    d = X.info(p)
    assert (d['njs_base'], d['njs_base_used'], d['njs_base_from']) == (17, 18, 'nlm')
