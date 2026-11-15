"""アプリの基準の難易度と派生の難易度（docs/アプリ仕様.md 17 節・app/server.py・app/versions.py）: 見る難易度の譜面・作り直しの --diff・
履歴から戻す／別の案を選ぶ時に派生を消さない・基準を置き直した後の古い版・前の譜面に寄せる時の前の版"""
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from automap import diffs, nlmf
from automap import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
EP, EX, HD = 'expertplusstandard.dat', 'expertstandard.dat', 'hardstandard.dat'


def _proj(shift=0):
    """拍 0〜32 を作ったクリップ 4 つで覆った Expert+ だけのファイル（tests/test_versions.py と同じ形）。shift＝ノーツの列をずらす"""
    p = {'format': 'nlmf', 'version': 2, 'bpm': 120, 'tempoParts': [], 'current': 'ExpertPlusStandard.dat', 'notesLanes': 1,
         'lightLanes': 1, 'markers': [{'beat': 0, 'name': 'A'}, {'beat': 8, 'name': 'B'}, {'beat': 16, 'name': 'C'}, {'beat': 24, 'name': 'D'}],
         'laneStates': {'mute': [], 'solo': [], 'lock': []}, 'graph': {'out': {'diffs': {'ExpertPlus': 1}}},
         'difficulties': {EP: {'name': 'ExpertPlusStandard.dat', 'v3': True, 'base': {}, 'notes': [], 'bombs': [], 'walls': [],
                               'arcs': [], 'chains': [], 'lightEvents': [],
                               'sections': [{'id': 'l1', 'beat': 0, 'track': 0, 'lk': 'l', 'len': 32, 'label': 'light', 'content': {}}]}}}
    nlmf.put_note_lane(p, {EP: cli._cover_clips(p, _notes(shift), 32)})
    return p


def _notes(shift=0, every=1):
    return [{'beat': b + 0.0, 'x': (1 + (i % 2) + shift) % 4, 'y': 0, 'c': i % 2, 'd': 1 if (i // 2) % 2 == 0 else 0}
            for i, b in enumerate(range(1, 32)) if i % every == 0]


def _add_derived(proj, d, src=EP, every=2):
    """派生の作り物: src の譜面から間引いたクリップを d に（作ったクリップ＝id は d のキーの指紋）"""
    k = diffs.ensure(proj, d)
    nlmf.clear_notes(proj, k)
    lane = nlmf.classify(proj, src)[2] or 0
    ns = [n for i, n in enumerate(_notes_of(proj, src)) if i % every == 0]
    nlmf.put_clips(proj, k, cli._cover_clips(proj, ns, 32), lane)
    return k


def _notes_of(proj, k):
    return [{'beat': n['beat'], 'x': n['x'], 'y': n['y'], 'c': n['c'], 'd': n['d']} for n in nlmf.clip_notes(proj, k)]


def _sig(proj, k):
    return [(n['beat'], n['x'], n['y'], n['c'], n['d']) for n in nlmf.clip_notes(proj, k)] if k in proj['difficulties'] else None


def _move(proj, src, dst):
    """基準を置き直す（app/expand.py と同じ: diffs.move ＋作ったままのクリップの id を移した先のキーで付け直す）"""
    ks, kd = diffs.key(src), diffs.key(dst)
    ids = {s['id'] for s in nlmf.note_clips(proj['difficulties'][ks]) if nlmf.is_app_clip(s) and s['id'] == nlmf.clip_id(ks, s)}
    diffs.move(proj, src, dst)
    for s in nlmf.note_clips(proj['difficulties'][kd]):
        if s['id'] in ids:
            s['id'] = nlmf.clip_id(kd, s)


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
    cli._save(_proj(), p)
    server.save_work(p, {'ranges': [{'b0': 8, 'b1': 16, 'set': {'amount': 1}}], 'line': [], 'auto_rest': {'on': False, 'b': None}})
    return server, versions, p


def _job(jid, state='running', **kw):
    return dict(kw, id=jid, log='', state=state, file='T.intent-s1.nlmf')


def _generate(V, p, proj, jid):
    """作り直したことにする（前後の控え・compose が書いた＝指紋も）"""
    V.before_generate(_job(jid), p)
    cli._save(proj, p)
    V.after_generate(_job(jid, 'done', report='- 打点 31（両手同時 0）・種 1\n'), p)


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_chart_reads_the_base_and_other_difficulties(app):
    server, _, p = app
    proj = nlmf.load(p)
    _add_derived(proj, 'Expert')
    sec = nlmf.note_clips(proj['difficulties'][EX])[0]
    sec['content']['notes'][0][1] = (sec['content']['notes'][0][1] + 1) % 4   # NLM で手で直した
    cli._save(proj, p)
    c = server.chart(p)
    assert (c['diff'], c['key'], c['base']) == ('ExpertPlus', EP, 'ExpertPlus') and len(c['notes']) == 31
    assert [(x['diff'], x['role'], x['notes'], x['edited']) for x in c['diffs']] == [('Expert', 'derived', 16, 1), ('ExpertPlus', 'base', 31, 0)]
    e = server.chart(p, 'Expert')
    assert (e['diff'], e['key'], e['base']) == ('Expert', EX, 'ExpertPlus') and len(e['notes']) == 16
    assert sorted({x['state'] for x in e['clips']}) == ['app', 'edited']
    with pytest.raises(ValueError, match='Hard の譜面が無い'):
        server.chart(p, 'Hard')


def test_compose_gets_the_full_difficulty_name(app):
    """compose の --diff は 'ExpertStandard.dat' の形（nlmf.diff_key は頭の一致で探す＝'Expert' だと Expert+ を拾い得る）"""
    server, _, p = app
    cmd = server.compose_cmd(p, 'x.json')
    assert cmd[cmd.index('--diff') + 1] == 'ExpertPlusStandard.dat'
    assert server.compose_cmd(p, 'x.json', diff='Hard')[-1] == 'HardStandard.dat'
    w = server.load_work(p)
    server.save_work(p, dict(w, diff='Expert'))
    cmd = server.compose_cmd(p, 'x.json')
    assert cmd[cmd.index('--diff') + 1] == 'ExpertStandard.dat'
    with pytest.raises(ValueError, match='Expert の譜面が無い'):   # 基準の難易度が無いファイルは作り直しを始める前に断る
        server.start_generate(p)


def test_restore_puts_back_only_the_base(app):
    """履歴から戻すのは基準の難易度だけ。派生（手で直したクリップも）・基準のライト・書き出す印は今のまま＝合わせた物を「戻した版」として控える"""
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    v1 = V.list_versions(p)['versions'][0]
    _generate(V, p, _proj(shift=2), 'j2')
    proj = nlmf.load(p)
    _add_derived(proj, 'Expert')
    proj['difficulties'][EP]['sections'][0]['label'] = 'light（NLM で直した）'   # 基準の難易度のライト
    cli._save(proj, p)
    before = nlmf.load(p)
    r = V.restore(p, v1['id'])
    after = nlmf.load(p)
    assert r['merged'] and _sig(after, EP) == _sig(nlmf.load(V._ver(p, v1['id'])), EP)
    assert after['difficulties'][EX] == before['difficulties'][EX] and diffs.export_marks(after) == diffs.export_marks(before)
    assert [s for s in after['difficulties'][EP]['sections'] if s.get('lk') == 'l'][0]['label'] == 'light（NLM で直した）'
    assert {st for _, st in nlmf.classify(after, EP)[0]} == {'app'} and not cli._edited_since_written(p)
    top = V.list_versions(p)['versions'][0]
    assert top['kind'] == 'restore' and top['current'] and top['reliable'] and top['diff'] == 'ExpertPlus' and top['work']
    assert V.prev_version(p)[0]['id'] == top['id']   # 前の譜面に寄せる時の前の版＝戻した版（作った時の作業ファイル）


def test_restore_without_other_difficulties_copies_the_version(app):
    """派生の無い今の曲は今まで通り: 版のファイルをそのまま写す（指紋が合う＝一覧の「今の版」・新しい版は増えない）"""
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    v1 = V.list_versions(p)['versions'][0]
    _generate(V, p, _proj(shift=2), 'j2')
    n = len(V.list_versions(p)['versions'])
    r = V.restore(p, v1['id'])
    assert not r['merged'] and r['restored'] is None and _sha(p) == v1['sha']
    d = V.list_versions(p)
    assert len(d['versions']) == n and d['current'] == v1['id'] and not cli._edited_since_written(p)


def test_restore_an_old_version_into_the_moved_base(app):
    """基準を Expert+ から Expert に置き直した後に、置き直す前の版（基準 Expert+）に戻す → 今の基準（Expert）に入る・作ったクリップのまま"""
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    v1 = V.list_versions(p)['versions'][0]
    assert v1['diff'] == 'ExpertPlus'
    _generate(V, p, _proj(shift=2), 'j2')
    proj = nlmf.load(p)
    _move(proj, 'ExpertPlus', 'Expert')
    _add_derived(proj, 'Hard', src=EX)
    cli._save(proj, p)
    server.save_work(p, dict(server.load_work(p), diff='Expert', expand={'base': 'Expert'}))
    assert server.file_diff(V._ver(p, v1['id'])) == 'ExpertPlus' and server.file_diff(p) == 'Expert'
    hard = _sig(proj, HD)
    r = V.restore(p, v1['id'], work=True)
    after = nlmf.load(p)
    assert r['merged'] and EP not in after['difficulties']
    assert _sig(after, EX) == _sig(nlmf.load(V._ver(p, v1['id'])), EP) and _sig(after, HD) == hard
    assert {st for _, st in nlmf.classify(after, EX)[0]} == {'app'}   # id を付け直した＝次の作り直しで入れ替わる
    w = server.load_work(p)
    assert w['diff'] == 'Expert' and w['expand'] == {'base': 'Expert'}   # 意思入れも戻す: 基準と展開の設定は今のまま
    assert server.chart(p)['diff'] == 'Expert' and len(server.chart(p, 'Hard')['notes']) == len(hard)


def test_prev_version_after_moving_the_base(app):
    """基準を置き直した（クリップの id はキーごと変わる）後も、前の譜面に寄せる時の前の版が分かる・diff と expand は曲の全体の設定に入れない"""
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    v1 = V.list_versions(p)['versions'][0]
    proj = nlmf.load(p)
    _move(proj, 'ExpertPlus', 'Expert')
    cli._save(proj, p)
    server.save_work(p, dict(server.load_work(p), diff='Expert', expand={'base': 'Expert', 'up': 1}))
    e, why = V.prev_version(p)
    assert e and e['id'] == v1['id'], why
    assert V.compose_extra(p, server.load_work(p))[0] == '--prev-intent'
    assert V.pending(p)['state'] == 'none'


def test_choose_keeps_other_difficulties(app):
    """別の案を選ぶ: 案は今の結果のファイルから作る＝基準の難易度だけ違う → 派生は今のまま（案のファイルをそのまま写す）"""
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    proj = nlmf.load(p)
    _add_derived(proj, 'Expert')
    cli._save(proj, p)
    der = copy.deepcopy(proj['difficulties'][EX])
    meta = {'file': p.name, 'only': [8, 16], 'base_sha': _sha(p), 'start': 1, 'cands': [{'n': 1, 'v': 1, 'variant': 1, 'seed': 1, 'state': 'done'}],
            'done': True, 'rare': False, 'band': None, 'form': None}
    V.cand_dir(p).mkdir(parents=True)
    (V.cand_dir(p) / 'index.json').write_text(json.dumps(meta), encoding='utf-8')
    cp = V._cand(p, 1)
    shutil.copy2(p, cp)
    c = nlmf.load(cp)   # 案: 区間（拍 8〜16）の基準のクリップだけ置き方を変えた物（作り直した＝id も中身の指紋）
    s = next(s for s in nlmf.note_clips(c['difficulties'][EP]) if s['beat'] == 8)
    for a in s['content']['notes']:
        a[1] = 3 - a[1]
    s['id'] = nlmf.clip_id(EP, s)
    cli._save(c, cp)
    want, want_sha = _sig(nlmf.load(cp), EP), _sha(cp)
    V.choose(p, 1)   # （選んだ後は案を消す）
    after = nlmf.load(p)
    assert after['difficulties'][EX] == der
    assert _sig(after, EP) == want != _sig(proj, EP) and _sha(p) == want_sha


def test_file_diff_reads_the_version_entry(app):
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    v1 = V.list_versions(p)['versions'][0]
    assert v1['diff'] == 'ExpertPlus' and server.file_diff(V._ver(p, v1['id'])) == 'ExpertPlus'
    items = json.loads((V.hist_dir(p) / 'index.json').read_text(encoding='utf-8'))
    items[0]['diff'] = 'Expert'   # （一覧の diff が先）
    (V.hist_dir(p) / 'index.json').write_text(json.dumps(items), encoding='utf-8')
    assert server.file_diff(V._ver(p, items[0]['id'])) == 'Expert'
    with pytest.raises(ValueError, match='Expert の譜面が無い'):
        server.chart(V._ver(p, items[0]['id']))


def test_restore_aligns_lanes(app):
    """版の後に NLM で一番上にレーンを足した（今のノーツの番号が 1 つずれた）ファイルに戻す → 版の基準のクリップも 1 つずらして入れる"""
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    v1 = V.list_versions(p)['versions'][0]
    proj = _proj(shift=2)
    _add_derived(proj, 'Expert')
    V._align_lanes(proj, 2)   # NLM で一番上にレーンを足した
    cli._save(proj, p)
    assert {s['track'] for s in nlmf.note_clips(proj['difficulties'][EP])} == {1}
    r = V.restore(p, v1['id'])
    after = nlmf.load(p)
    assert r['merged'] and after['notesLanes'] == 2
    assert {s['track'] for s in nlmf.note_clips(after['difficulties'][EP])} == {1} == {s['track'] for s in nlmf.note_clips(after['difficulties'][EX])}
    assert _sig(after, EP) == _sig(nlmf.load(V._ver(p, v1['id'])), EP)
    assert {st for _, st in nlmf.classify(after, EP)[0]} == {'app'} and nlmf.classify(after, EP)[2] == 1


def test_snapshot_before_moving_the_base(app):
    """基準を置き直す直前（画面が先に作業ファイルの diff を新しい基準にした・ファイルはまだ前の基準）の控え: 版の基準は前の基準のまま。
    app/expand.py は guard(…, diff=前の基準)・置き直した後の snapshot(…, diff=新しい基準) で渡せる"""
    server, V, p = app
    _generate(V, p, _proj(shift=1), 'j1')
    cli._save(_proj(shift=2), p)   # （どの版とも違う）
    server.save_work(p, dict(server.load_work(p), diff='Expert'))
    e = V.guard(p, '難易度を展開する前')
    assert e['diff'] == 'ExpertPlus' and e['notes'] == 31 and server.file_diff(V._ver(p, e['id'])) == 'ExpertPlus'
    proj = nlmf.load(p)
    _move(proj, 'ExpertPlus', 'Expert')
    cli._save(proj, p)
    e2 = V.snapshot(p, 'expand', '難易度を展開した', head=False, dedupe=False, diff='Expert')
    assert e2['diff'] == 'Expert' and e2['notes'] == 31 and len(server.chart(V._ver(p, e['id']))['notes']) == 31
