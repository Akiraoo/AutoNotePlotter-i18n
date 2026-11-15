"""別の案と履歴（app/versions.py）: 作り直しの前後の控え・戻す・古い版を消す・案を選ぶ・区間を固定・案のテーマのずらし（compose --variant）"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from automap import form, nlmf, theme
from automap import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
DK = 'expertplusstandard.dat'


def _proj(shift=0):
    """拍 0〜32 を作ったクリップ 4 つ（マーカーごと・隙間なし）で覆った作業用のファイル。shift＝ノーツの列をずらす（別の版を作る）"""
    p = {'format': 'nlmf', 'version': 2, 'bpm': 120, 'tempoParts': [], 'current': 'ExpertPlusStandard.dat', 'notesLanes': 1,
         'lightLanes': 1, 'markers': [{'beat': 0, 'name': 'A'}, {'beat': 8, 'name': 'B'}, {'beat': 16, 'name': 'C'}, {'beat': 24, 'name': 'D'}],
         'laneStates': {'mute': [], 'solo': [], 'lock': []},
         'difficulties': {DK: {'name': 'ExpertPlusStandard.dat', 'v3': True, 'base': {}, 'notes': [], 'bombs': [], 'walls': [],
                               'arcs': [], 'chains': [], 'lightEvents': [],
                               'sections': [{'id': 'l1', 'beat': 0, 'track': 0, 'lk': 'l', 'len': 32, 'label': 'light', 'content': {}}]}}}
    notes = [{'beat': b + 0.0, 'x': (1 + (i % 2) + shift) % 4, 'y': 0, 'c': i % 2, 'd': 1 if (i // 2) % 2 == 0 else 0}
             for i, b in enumerate(range(1, 32))]
    nlmf.put_note_lane(p, {DK: cli._cover_clips(p, notes, 32)})
    return p


@pytest.fixture
def app(tmp_path, monkeypatch):
    """写しの場所（tmp_path/out）で server と versions をつなぐ → (server, versions, 結果のファイル)"""
    import server
    import versions
    monkeypatch.setattr(server, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(server, 'CACHE', tmp_path / 'cache')
    (tmp_path / 'out').mkdir()
    versions.routes(server)
    p = tmp_path / 'out' / 'T.intent-s1.nlmf'
    cli._save(_proj(), p)   # こちらで書いたまま（out/.state/ の指紋あり）
    server.save_work(p, {'ranges': [{'b0': 8, 'b1': 16, 'set': {'amount': 1}}], 'line': [], 'auto_rest': {'on': False, 'b': None}})
    return server, versions, p


def _job(jid, state='running', **kw):
    return dict(kw, id=jid, log='', state=state, file='T.intent-s1.nlmf')


def _states(p):
    proj = nlmf.load(p)
    return [(s.get('beat'), st) for s, st in nlmf.classify(proj, DK)[0]]


def test_hooks_once(app):
    server, versions, _ = app
    versions.routes(server)
    assert server.BEFORE_GENERATE.count(versions.before_generate) == 1 and server.AFTER_GENERATE.count(versions.after_generate) == 1


def test_history_around_generate(app):
    """作り直しの前に今の版（初め）を控え、後に作った版を控える。NLM で直して保存した版は、次の作り直しの前に「NLM で直した版」として控える"""
    server, V, p = app
    V.before_generate(_job('j1'), p)
    cli._save(_proj(shift=1), p)   # compose が書いた（指紋も）
    V.after_generate(_job('j1', 'done', report='- 打点 31（両手同時 0）・種 1・計算 1.0 秒・減点の合計 2.0\n'), p)
    d = V.list_versions(p)
    assert [v['kind'] for v in d['versions']] == ['generate', 'first']
    assert d['versions'][0]['current'] and d['current'] == d['versions'][0]['id'] and d['known']
    assert d['versions'][0]['head'] == ['打点 31（両手同時 0）・種 1'] and d['versions'][0]['as_written']
    assert d['versions'][0]['work'] and d['versions'][1]['notes'] == 31
    # 失敗した作り直しは控えない
    V.before_generate(_job('j2'), p)
    V.after_generate(_job('j2', 'error'), p)
    assert len(V.list_versions(p)['versions']) == 2
    # NLM で直して保存した（指紋は直さない）→ 次の作り直しの前に控える
    nlmf.save(_proj(shift=2), p)
    assert not V.list_versions(p)['known']
    V.before_generate(_job('j3'), p)
    top = V.list_versions(p)['versions'][0]
    assert top['kind'] == 'nlm' and not top['as_written'] and top['head'] == [] and top['current']


def test_export_info_is_same_version(app):
    """Beat Saber への書き出しが .nlmf に曲の情報・音量を書いても、次の作り直しの前に「アプリの外で作り直した版」を控えない（書く前の版と
    同じ版とみなす＝versions.adopt・2026-11-15）。書き出しの後に NLM で直して保存した時は、今までどおり控える"""
    server, V, p = app
    import bsexport
    ctx = SimpleNamespace(cli=cli)
    V.before_generate(_job('j1'), p)
    cli._save(_proj(shift=1), p)
    V.after_generate(_job('j1', 'done', report='- 打点 31' + chr(10)), p)
    gen = V.list_versions(p)['versions'][0]
    for n in range(3):   # 書き出す（曲の情報・音量）→ 作り直す前、を 3 回
        bsexport._edit(ctx, p, lambda proj, n=n: proj.setdefault('graph', {}).setdefault('song', {}).update(title=f'曲 {n}', gainDb=n))
        d = V.list_versions(p)
        assert d['current'] == gen['id'] and d['known']
        V.before_generate(_job(f'jx{n}'), p)
        assert [v['kind'] for v in V.list_versions(p)['versions']] == ['generate', 'first']
    assert not cli._edited_since_written(p)
    # 書き出しの後に NLM で直して保存 → 控える（NLM で直した版）
    proj = nlmf.load(p)
    proj['bpm'] = 121
    nlmf.save(proj, p)
    V.before_generate(_job('j9'), p)
    assert V.list_versions(p)['versions'][0]['kind'] == 'nlm'
    # NLM で直した（どの版とも違う）後の書き出しは、同じ版とみなさない（adopt は何もしない）→ 書き出した中身は次の作り直しの前に控える
    proj['bpm'] = 122
    nlmf.save(proj, p)
    bsexport._edit(ctx, p, lambda proj: proj.setdefault('graph', {}).setdefault('song', {}).update(title='後'))
    assert not V.list_versions(p)['known']


def test_restore(app):
    """戻す: 今の版を控えてから写す。こちらで書いたままの版は指紋を書き直し（作ったクリップは作ったまま）、NLM で直した版は指紋を消す"""
    server, V, p = app
    first = V.guard(p, '試し')
    cli._save(_proj(shift=1), p)
    gen = V.snapshot(p, 'generate')
    nlmf.save(_proj(shift=2), p)          # NLM で直した（どの版とも違う）
    work0 = server.work_path(p).read_text(encoding='utf-8')
    server.save_work(p, {'ranges': [], 'line': [], 'auto_rest': {'on': True, 'b': None}})
    r = V.restore(p, first['id'], work=True)
    vs = V.list_versions(p)['versions']
    assert vs[0]['kind'] == 'nlm' and not vs[0]['current']        # 戻す前の版を控えた
    assert r['work']['ranges'][0]['b0'] == 8                       # 意思入れも戻した
    assert json.loads(server.work_path(p).read_text(encoding='utf-8'))['ranges'] == json.loads(work0)['ranges']
    assert V._sha(p) == first['sha'] and not cli._edited_since_written(p)
    assert all(st == 'app' for _, st in _states(p))               # 次の作り直しでも作ったまま
    assert V.list_versions(p)['current'] == first['id']
    # NLM で直した版に戻す → 指紋を消す（次の作り直しで out/old/ に控え・分からない物として扱う）
    V.restore(p, vs[0]['id'])
    assert cli._edited_since_written(p) and not cli._state_path(p).exists()
    with pytest.raises(FileNotFoundError):
        V.restore(p, '20000101-000000-abcd')
    with pytest.raises(ValueError):
        V.restore(p, '../x')
    assert gen['id'] in {v['id'] for v in V.list_versions(p)['versions']}


def test_prune_keeps_marked_and_current(app, monkeypatch):
    server, V, p = app
    monkeypatch.setattr(V, 'HIST_MAX', 3)
    ids = []
    for k in range(6):
        cli._save(_proj(shift=k % 4), p)   # 保存の時刻が入るので、同じノーツでも別の中身
        ids.append(V.snapshot(p, 'generate', dedupe=False)['id'])
        if k == 0:
            V.set_keep(p, ids[0], True)
    vs = V.list_versions(p)['versions']
    have = [v['id'] for v in vs]
    assert ids[0] in have and ids[-1] in have                       # 残す印・今の版
    assert sum(1 for v in vs if not v['keep']) == 3
    assert not V._ver(p, ids[1]).exists()                           # 古い版のファイルも消した
    with pytest.raises(ValueError):
        V.delete_version(p, ids[-1])                                # 今の版は消せない
    V.delete_version(p, ids[0])
    assert ids[0] not in [v['id'] for v in V.list_versions(p)['versions']]


def _cands(V, p, only=(8, 16)):
    """案を1つ置く（compose --only の代わり: 区間の中のクリップだけノーツを動かした写し）"""
    d = V.cand_dir(p)
    d.mkdir(parents=True)
    pj = nlmf.load(p)
    for s in nlmf.note_clips(pj['difficulties'][DK]):
        if only[0] <= s['beat'] < only[1]:
            for t in s['content']['notes']:
                t[1] = 3 - t[1]
            s['id'] = nlmf.clip_id(DK, s)
    cli._save(pj, V._cand(p, 1))
    V._cand(p, 1, '.report.md').write_text(f'- 土台: {V._cand(p, 1).name}。NLM で直された結果の控え: old/T.cand1.x.nlmf\n- 打点 4\n',
                                          encoding='utf-8')
    meta = {'file': p.name, 'only': list(only), 'base_sha': V._sha(p), 'start': 1, 'done': True,
            'cands': [{'n': 1, 'v': 1, 'variant': 1, 'seed': 1, 'state': 'done'}]}
    (d / 'index.json').write_text(json.dumps(meta), encoding='utf-8')


def test_choose_candidate(app):
    """これにする: 今の版を控えてから案を写し、報告も写す（案のファイルの名前は結果のファイルの名前に）。区間を固定すると区間の
    クリップの名前に「固定」（id はそのまま）。外は今のまま"""
    server, V, p = app
    before = nlmf.clip_notes(nlmf.load(p), DK)
    _cands(V, p)
    s = V.region_summary(V._cand(p, 1), 8, 16, before)
    assert s['outside_diff'] == 0 and s['same'] < s['notes'] == 8
    assert V.cands_view(p)['cands'][0]['n'] == 1
    r = V.choose(p, 1, fix=True)
    assert r['fixed'] == 1 and not V.cand_dir(p).exists()
    st = dict(_states(p))
    assert st[8] == 'fixed' and st[0] == st[16] == st[24] == 'app'
    after = nlmf.clip_notes(nlmf.load(p), DK)
    assert [n for n in after if not 8 <= n['beat'] < 16] == [n for n in before if not 8 <= n['beat'] < 16]
    rep = V._report_path(p).read_text(encoding='utf-8')
    assert 'T.cand1' not in rep and p.name in rep
    vs = V.list_versions(p)['versions']
    assert vs[0]['kind'] == 'cand' and vs[0]['current'] and vs[0]['fixed'] == 1 and vs[1]['kind'] == 'first'
    assert not cli._edited_since_written(p)


def test_stale_candidates(app):
    """結果のファイルが変わったら案は使えない（消す）"""
    server, V, p = app
    _cands(V, p)
    cli._save(_proj(shift=1), p)
    with pytest.raises(ValueError):
        V.choose(p, 1)
    assert not V.cand_dir(p).exists()
    _cands(V, p)
    cli._save(_proj(shift=2), p)
    assert V.cands_view(p) == {'cands': None, 'stale': True} and not V.cand_dir(p).exists()


def test_variant_rotates_themes_in_range():
    """compose --variant: 区間と重なる小節だけ、テーマの並びの中で n 個ずらす（外の小節はそのまま）"""
    T = [theme.Theme([(1, 0, 1), (1, 1, 0)], [(2, 0, 1), (2, 1, 0)], 5, 'pair'),
         theme.Theme([(0, 0, 1), (0, 2, 0)], [(3, 0, 1), (3, 2, 0)], 4, 'pair'),
         theme.Theme([(1, 0, 6), (2, 2, 5)], [(2, 0, 7), (1, 2, 4)], 3, 'pair')]
    blocks = [SimpleNamespace(base='A', i0=0, i1=4, vocal=False, tension=0.0, group='A')]
    mu = {'bars': [0, 4, 8, 12], 'lab': {'mel': [-1] * 4, 'acc': [0, 1, 2, 3]}}
    seq = {'A': T}
    bgd = form.mix_guides(blocks, mu, seq)
    alt = cli._variant_guides(bgd, blocks, mu, seq, 1, only=(4, 8))
    assert alt[0] == bgd[0] and alt[2] == bgd[2] and alt[3] == bgd[3]
    assert alt[1][1] == bgd[2][1] and alt[1][0] == bgd[1][0]       # 小節 1 は次のテーマ（番号は小節のまま）
    whole = cli._variant_guides(bgd, blocks, mu, seq, 1)
    assert [whole[i][1] for i in range(3)] == [bgd[i + 1][1] for i in range(3)]
    assert cli._variant_guides(bgd, blocks, mu, seq, 3) == bgd   # 並びの数だけずらすと同じ


def _variant_setup():
    T = [theme.Theme([(1, 0, 1), (1, 1, 0)], [(2, 0, 1), (2, 1, 0)], 5, 'pair'),
         theme.Theme([(0, 0, 1), (0, 2, 0)], [(3, 0, 1), (3, 2, 0)], 4, 'pair'),
         theme.Theme([(1, 0, 6), (2, 2, 5)], [(2, 0, 7), (1, 2, 4)], 3, 'pair')]
    blocks = [SimpleNamespace(base='A', i0=0, i1=4, vocal=False, tension=0.0, group='A')]
    mu = {'bars': [0, 4, 8, 12], 'lab': {'mel': [-1] * 4, 'acc': [0, 1, 2, 3]}}
    seq = {'A': T}
    T2 = list(reversed(T))   # 種 2 で選び直したテーマの並び（の代わり）
    pal_of = lambda s: ({'x': T}, seq) if s == 1 else ({'x': T2}, {'A': T2})
    return T, blocks, mu, seq, form.mix_guides(blocks, mu, seq), pal_of


def test_variant_directives_choose_bar_themes():
    """区間の「案 k」: 区間と重なる小節だけ、案 k の (ずらし, 種) のテーマ。重なる小節は後の区間が勝ち、compose の --variant は
    意思入れの表の「案」より後（同じ区間でまた別の案を作れる）。種が 1 でない案は、その種のテーマの並びからずらす（曲全体の種は変えない）"""
    T, blocks, mu, seq, bgd, pal_of = _variant_setup()
    it = {'ranges': [{'b0': 4, 'b1': 12, 'set': {'variant': 1}}, {'b0': 0, 'b1': 4, 'set': {'variant': 6}}]}
    vr = cli._variant_ranges(it, 2, (4, 8))
    assert vr == [(4, 12, 1, '意思入れ'), (0, 4, 6, '意思入れ'), (4, 8, 2, '--variant')]
    alt, rep = cli._apply_variants(bgd, blocks, mu, vr, pal_of)
    cyc = lambda i: alt[i][1]
    assert cyc(0) == bgd[1][1]                        # 案 6＝種 2 の並び（逆順）で 1 ずらす → T2[1]＝T[1]
    assert cyc(1) == bgd[0][1]                        # --variant 2 が意思入れの案 1 に勝つ → T[(1+2)%3]
    assert cyc(2) == bgd[0][1]                        # 意思入れの案 1 → T[(2+1)%3]
    assert alt[3] == bgd[3]                           # 区間の外はそのまま
    assert all(alt[i][0] == bgd[i][0] for i in bgd)   # テーマの番号は小節のまま（小節の頭で型をたどり直す）
    assert [r[:6] for r in rep] == [(4, 12, 1, 1, 1, '意思入れ'), (0, 4, 6, 1, 2, '意思入れ'), (4, 8, 2, 2, 1, '--variant')]
    line = cli._variant_line(vr, rep)
    assert line.startswith('- 別の案: 拍 4〜12 は案 1（ずらし 1・種 1）') and '拍 4〜8 は案 2（ずらし 2・種 1・--variant）' in line
    # 案の無い時は何も変えない・--variant だけで区間が無ければ曲の全部
    assert cli._variant_ranges(None, 0, None) == [] and cli._variant_line([], None) == ''
    whole, rep = cli._apply_variants(bgd, blocks, mu, cli._variant_ranges(None, 1, None), pal_of)
    assert [whole[i][1] for i in range(3)] == [bgd[i + 1][1] for i in range(3)] and rep[0][0] is None
    assert '曲の全部は案 1' in cli._variant_line(cli._variant_ranges(None, 1, None), rep)
    assert cli._variant_line(vr, None) == ''


def test_candidates_pass_only_the_variant(app, monkeypatch):
    """別の案を作る: 案 v（4・5・6…）の compose には --variant v だけを渡す（種は渡さない＝曲全体の種はいつも同じ）。表の数字は variant_spec"""
    server, V, p = app
    got = []

    def fake_generate(p_, only=None, out=None, extra=(), kind='generate', **meta):
        got.append(list(extra))
        return {'state': 'done', 'took': 0.1, 'report': '- 打点 4\n'}

    def fake_job(file, steps, kind='generate', **meta):
        job = {'id': 'j', 'log': '', 'state': 'running'}
        for _, fn in steps:
            fn(job)
        return job
    monkeypatch.setattr(server, 'start_generate', fake_generate)
    monkeypatch.setattr(server, 'start_job', fake_job)
    V.start_cands(p, [8, 16], start=4)
    assert got == [['--variant', 4], ['--variant', 5], ['--variant', 6]]
    cs = V._cand_meta(p)['cands']
    assert [(c['n'], c['v'], c['variant'], c['seed']) for c in cs] == [(1, 4, 4, 1), (2, 5, 5, 1), (3, 6, 1, 2)]


def test_choose_keeps_the_work_with_the_variant(app):
    """これにする: 画面が送った「案 k」を足した後の作業ファイルを、選んだ版の控えに（作業ファイルそのものは画面が保存する）。返事に案の番号"""
    server, V, p = app
    _cands(V, p)
    work0 = server.work_path(p).read_text(encoding='utf-8')
    w = {'ranges': [{'b0': 8, 'b1': 16, 'set': {'amount': 1, 'variant': 1}}], 'line': [], 'auto_rest': {'on': False, 'b': None}}
    r = V.choose(p, 1, work=w)
    assert r['variant'] == 1
    vs = V.list_versions(p)['versions']
    saved = json.loads(V._ver(p, vs[0]['id'], '.automap.json').read_text(encoding='utf-8'))
    assert saved['ranges'] == w['ranges'] and vs[0]['cand'] == {'v': 1, 'variant': 1, 'seed': 1}
    assert server.work_path(p).read_text(encoding='utf-8') == work0   # 作業ファイルはここでは書かない


def test_rare_ranges_choose_bar_themes_from_the_wider_bundle():
    """「珍しい型まで」: 区間と重なる小節だけ、広げた型の束で選んだ並び（pal_of(s, True)）のテーマ。案 k と一緒なら広げた並びの中で案 k の
    ずらし方。案と珍しい型までは小節ごとに別々に勝ち負け（後から付けた案だけの区間でも、珍しい型までは残る）。無ければ前と同じ"""
    T, blocks, mu, seq, bgd, _ = _variant_setup()
    R = [theme.Theme([(3, 0, 1), (3, 1, 0)], [(0, 0, 1), (0, 1, 0)], 2, 'pair'),
         theme.Theme([(2, 0, 7), (3, 2, 5)], [(1, 0, 6), (0, 2, 4)], 2, 'pair'),
         theme.Theme([(1, 0, 1), (2, 2, 0)], [(2, 0, 1), (1, 2, 0)], 2, 'pair')]
    calls = []

    def pal_of(s, rare=False):
        calls.append((s, rare))
        return ({'x': R}, {'A': R}) if rare else ({'x': T}, seq)
    rb = form.mix_guides(blocks, mu, {'A': R})
    it = {'ranges': [{'b0': 0, 'b1': 8, 'set': {'rare': 1}}, {'b0': 8, 'b1': 12, 'set': {'rare': 1, 'variant': 1}}]}
    vr = cli._variant_ranges(it, 2, (4, 8))
    assert vr == [(0, 8, 0, '意思入れ', True), (8, 12, 1, '意思入れ', True), (4, 8, 2, '--variant')]
    alt, rep = cli._apply_variants(bgd, blocks, mu, vr, pal_of)
    assert alt[0] == rb[0]                                   # 珍しい型まで（案なし）＝広げた並びのまま
    assert alt[1][1] == rb[(1 + 2) % 3][1]                   # 後の --variant 2 は案だけ＝珍しい型までは残り、広げた並びで 2 ずらす
    assert alt[2][1] == rb[(2 + 1) % 3][1]                   # 珍しい型まで＋案 1
    assert alt[3] == bgd[3] and all(alt[i][0] == bgd[i][0] for i in bgd)
    assert {c for c in calls} == {(1, True)}
    assert [r[7] for r in rep] == [True, True, False] and rep[0][2:7] == (0, 0, 1, '意思入れ', 2)
    assert cli._variant_line(vr, rep) == '- 別の案: 拍 8〜12 は案 1（ずらし 1・種 1・珍しい型まで）・拍 4〜8 は案 2（ずらし 2・種 1・--variant）'
    box = {'themes': R * 4, 'min': (2, 2)}
    line = cli._rare_line(vr, rep, 5, box)
    assert line.startswith('- 珍しい型まで: 拍 0〜8（小節 2）・拍 8〜12（小節 1・案 1）') and '型 12・曲の束は 5' in line
    assert cli._rare_line([], None, 5, box) == ''
    box['pals'] = [{'x': R}]
    rows = cli._rare_lines(rep, alt, mu['bars'], T, box)
    assert rows[2].startswith('| 拍 0〜8 | 2 | ') and rows[2].endswith('| 1 / 1 |')   # 小節 0 と 1 は同じ型（R[0]）
    # --rare（別の案「珍しい型まで広げて作る」）: --only の区間・--variant と一緒
    assert cli._variant_ranges(None, 0, (4, 8), True) == [(4, 8, 0, '--rare', True)]
    assert cli._variant_ranges(None, 3, None, True) == [(None, None, 3, '--variant --rare', True)]
    # 案だけの時は前と同じ形（5 つ目の項目なし）・珍しい型までの区間が無ければ広げた束は作らない
    calls.clear()
    alt2, _ = cli._apply_variants(bgd, blocks, mu, cli._variant_ranges(None, 1, (4, 8)), pal_of)
    assert calls == [(1, False)] and alt2[1][1] == bgd[2][1]


def test_compose_cli_takes_rare(monkeypatch):
    """compose の --rare（既定は無し）を受け取る"""
    got = []
    monkeypatch.setattr(cli, 'cmd_compose', lambda a: got.append(a))
    cli.main(['compose', 'x.nlmf', '--stems', 'y', '--form', '--style', '--only', '4,8', '--variant', '2', '--rare'])
    cli.main(['compose', 'x.nlmf', '--stems', 'y'])
    assert got[0].rare and got[0].variant == 2 and got[0].only == '4,8' and not got[1].rare


def test_candidates_can_widen_to_rare(app, monkeypatch):
    """別の案を「珍しい型まで広げて」作る: compose に --variant v と --rare。これにすると返事に rare（画面が「珍しい型まで」も足す）"""
    server, V, p = app
    got = []

    def fake_generate(p_, only=None, out=None, extra=(), kind='generate', **meta):
        got.append(list(extra))
        return {'state': 'done', 'took': 0.1, 'report': '- 打点 4\n'}

    def fake_job(file, steps, kind='generate', **meta):
        job = {'id': 'j', 'log': '', 'state': 'running', **meta}
        for _, fn in steps:
            fn(job)
        return job
    monkeypatch.setattr(server, 'start_generate', fake_generate)
    monkeypatch.setattr(server, 'start_job', fake_job)
    job = V.start_cands(p, [8, 16], start=1, rare=True)
    assert got == [['--variant', 1, '--rare'], ['--variant', 2, '--rare'], ['--variant', 3, '--rare']] and job['rare']
    m = V._cand_meta(p)
    assert m['rare'] and all(c['rare'] for c in m['cands'])
    shutil_copy = __import__('shutil').copy2
    shutil_copy(p, V._cand(p, 1))   # 案のファイル（中身は今のまま）
    r = V.choose(p, 1)
    assert r['rare'] and r['variant'] == 1
    e = V.list_versions(p)['versions'][0]
    assert e['cand'] == {'v': 1, 'variant': 1, 'seed': 1, 'rare': True} and '珍しい型まで' in e['title']


def _gen(server, V, p, jid, shift, only=None):
    """作り直しの代わり（前後の控えだけ）: 結果のファイルの中身を shift で変える"""
    V.before_generate(_job(jid, only=only), p)
    cli._save(_proj(shift=shift), p)
    V.after_generate(_job(jid, 'done', only=only), p)


def test_pending_compares_with_the_work_that_made_the_chart(app):
    """未反映の意思入れ: 今の結果のファイルを作った時の作業ファイルと、次の作り直しと同じ決まりで比べる"""
    server, V, p = app
    assert V.pending(p)['state'] == 'unknown'   # 履歴が無い＝分からない
    _gen(server, V, p, 'j1', 1)
    assert V.pending(p)['state'] == 'none'
    w = server.load_work(p)
    w['ranges'] += [{'b0': 24, 'b1': 32, 'set': {'hands': 1}}, {'b0': 0, 'b1': 8, 'set': {'amount': -1}},
                    {'b0': 16, 'b1': 20, 'set': {'comment': '※コメントだけ'}}]   # コメントだけの区間は作り方を変えない
    server.save_work(p, w)
    d = V.pending(p)
    assert d['state'] == 'some' and d['spans'] == [[0, 8], [24, 32]] and d['settings'] == [] and d['items'] == ['区間の指示（足した 2）']
    w['ranges'][0]['set'] = {'amount': 2}   # 同じ場所で中身を変えた
    w['line'] = [{'b': 8, 'k': 1.2, 'smooth': False}]
    w['auto_rest'] = {'on': True, 'b': 4}
    server.save_work(p, w)
    d = V.pending(p)
    assert d['items'] == ['区間の指示（足した 2・変えた 1）', '量のライン'] and d['settings'] == ['自動の休み']
    w['ranges'][0]['set'] = {'amount': 1}
    w['line'], w['auto_rest'] = [], {'on': False, 'b': None}
    w['ranges'] = [r for r in w['ranges'] if r['b0'] in (8, 16)]   # 消したら元どおり（コメントは残してよい）
    server.save_work(p, w)
    assert V.pending(p)['state'] == 'none'
    assert server.load_work(p) and V.pending(p.with_name('無い.intent-s1.nlmf'))['state'] == 'nofile'


def test_only_generate_keeps_outside_directives_pending(app):
    """区間だけ作り直した版には、作り直した区間の中の指示だけを効いた物として控える＝外で変えた指示は未反映のまま・次の全部の作り直しで
    「変わった所」に入る（前は今の作業ファイルをそのまま控え、外の指示が前の譜面に寄せられて効かないままだった）"""
    server, V, p = app
    _gen(server, V, p, 'j1', 1)
    w = server.load_work(p)
    w['ranges'] += [{'b0': 24, 'b1': 32, 'set': {'hands': 1}}, {'b0': 0, 'b1': 8, 'set': {'amount': -1}}]
    server.save_work(p, w)
    _gen(server, V, p, 'j2', 2, only=[24, 32])
    d = V.pending(p)
    assert d['state'] == 'some' and d['spans'] == [[0, 8]]
    saved = json.loads(V._ver(p, V.list_versions(p)['versions'][0]['id'], '.automap.json').read_text(encoding='utf-8'))
    assert [(r['b0'], r['set']) for r in saved['ranges']] == [(8, {'amount': 1}), (24, {'hands': 1})]
    _gen(server, V, p, 'j3', 3)   # 全部を作り直すと全部効く
    assert V.pending(p)['state'] == 'none'


def test_choose_region_candidate_keeps_outside_directives_pending(app):
    """区間の別の案を選んだ版も、区間の外の指示は前の版の物を控える（案は区間だけ作り直した物）"""
    server, V, p = app
    _gen(server, V, p, 'j1', 1)
    w = server.load_work(p)
    w['ranges'] += [{'b0': 0, 'b1': 8, 'set': {'amount': -1}}]
    server.save_work(p, w)
    _cands(V, p)
    sent = {'ranges': w['ranges'][:1] + [{'b0': 8, 'b1': 16, 'set': {'variant': 1}}] + w['ranges'][1:], 'line': [],
            'auto_rest': {'on': False, 'b': None}}
    V.choose(p, 1, work=sent)
    server.save_work(p, sent)   # 画面が同じ物を保存する
    d = V.pending(p)
    assert d['state'] == 'some' and d['spans'] == [[0, 8]]


def test_job_view_is_running_until_hooks_are_done():
    """作り直しの後始末（履歴の控え）が終わるまで画面には running と見せる（終わったと見た画面が未反映の意思入れを聞くと、まだ控えが無かった）"""
    import server
    v = server.job_view({'id': 'x', 'state': 'done', 'finishing': True, 'proc': 1, 'cmd': []})
    assert v['state'] == 'running' and 'finishing' not in v and 'proc' not in v and 'cmd' not in v
    assert server.job_view({'id': 'x', 'state': 'done'})['state'] == 'done'
