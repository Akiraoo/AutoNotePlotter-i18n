from pathlib import Path

import pytest

from automap import diffs


def _proj():
    note_sec = {'id': 'a', 'beat': 0, 'track': 0, 'lk': 'n', 'len': 8, 'content': {'notes': [[1, 1, 0, 0, 1, None], [9, 1, 0, 0, 1, None]]}}
    ep = {'name': 'ExpertPlusStandard.dat', 'v3': True, 'notes': [[1, 1, 0, 0, 1, 0]], 'lightEvents': [[0, 1, 1, None, 0]], 'sections': [note_sec]}
    return {'current': 'ExpertPlusStandard.dat', 'njsCfg': {'expertplusstandard.dat': {'njs': 18, 'offset': 0}},
            'graph': {'out': {'diffs': {'ExpertPlus': 1}}},
            'infoGraph': {'nodes': {'s1': {'t': 'set', 'data': {'diffs': {'ExpertPlus': 1}}}, 'm1': {'t': 'meta', 'data': {}}}},
            'difficulties': {'hardstandard.dat': {'name': 'HardStandard.dat', 'v3': True, 'notes': [], 'lightEvents': [], 'sections': []},
                             'expertplusstandard.dat': ep}}


def test_names_and_steps():
    assert diffs.name_of('Expert+') == 'ExpertPlus' == diffs.name_of('expertplusstandard.dat') == diffs.name_of('ExpertPlusStandard.dat')
    assert diffs.name_of('hard') == 'Hard'
    with pytest.raises(ValueError):
        diffs.name_of('Insane')
    assert diffs.key('Expert') == 'expertstandard.dat' and diffs.dat('Expert') == 'ExpertStandard.dat'
    assert diffs.steps('ExpertPlus', 'Hard') == -2 and diffs.steps('Hard', 'Expert') == 1
    # 量の既定は1段ごとに ±10%（足し算・2026-11-02 利用者）・刻みを変えられる・範囲の端まで
    assert diffs.ratio('ExpertPlus', 'Expert') == 0.9 and diffs.ratio('ExpertPlus', 'Hard') == 0.8 and diffs.ratio('ExpertPlus', 'Easy') == 0.6
    assert diffs.ratio('Expert', 'ExpertPlus') == 1.1 and diffs.ratio('Easy', 'ExpertPlus') == 1.4 and diffs.ratio('Hard', 'Hard') == 1
    assert diffs.ratio('ExpertPlus', 'Hard', 15) == 0.7 and diffs.ratio('Hard', 'ExpertPlus', 12.5) == 1.25
    assert diffs.ratio('ExpertPlus', 'Easy', 30) == diffs.RATIO_RANGE[0] and diffs.ratio('Easy', 'ExpertPlus', 50) == diffs.RATIO_RANGE[1]


def test_listing_counts_visible_notes():
    got = diffs.listing(_proj())
    assert [(r['diff'], r['notes'], r['export']) for r in got] == [('Hard', 0, False), ('ExpertPlus', 1, True)]


def test_ensure_adds_empty_and_marks_export():
    p = _proj()
    k = diffs.ensure(p, 'Expert')
    assert k == 'expertstandard.dat' and p['difficulties'][k]['name'] == 'ExpertStandard.dat'
    assert p['difficulties'][k]['sections'] == [] and 'base' in p['difficulties'][k]
    assert p['graph']['out']['diffs'] == {'ExpertPlus': 1, 'Expert': 1}
    assert p['infoGraph']['nodes']['s1']['data']['diffs'] == {'ExpertPlus': 1, 'Expert': 1}
    before = p['difficulties']['expertplusstandard.dat']
    assert diffs.ensure(p, 'ExpertPlus') == 'expertplusstandard.dat' and p['difficulties']['expertplusstandard.dat'] is before


def test_move_renames_whole_difficulty():
    p = _proj()
    diffs.move(p, 'ExpertPlus', 'Expert')
    d = p['difficulties']
    assert 'expertplusstandard.dat' not in d and d['expertstandard.dat']['name'] == 'ExpertStandard.dat'
    assert d['expertstandard.dat']['lightEvents'] == [[0, 1, 1, None, 0]]   # ライトも一緒に
    assert p['njsCfg'] == {'expertstandard.dat': {'njs': 18, 'offset': 0}}
    assert p['graph']['out']['diffs'] == {'ExpertPlus': 0, 'Expert': 1}
    assert p['infoGraph']['nodes']['s1']['data']['diffs'] == {'ExpertPlus': 0, 'Expert': 1}
    assert p['current'] == 'ExpertStandard.dat'


def test_move_refuses_filled_target_unless_swap():
    p = _proj()
    p['difficulties']['hardstandard.dat']['sections'] = [{'id': 'h', 'beat': 0, 'track': 0, 'lk': 'n', 'len': 4, 'content': {'notes': [[0, 1, 0, 0, 1, None]]}}]
    with pytest.raises(ValueError):
        diffs.move(p, 'ExpertPlus', 'Hard')
    diffs.move(p, 'ExpertPlus', 'Hard', swap=True)
    d = p['difficulties']
    assert d['hardstandard.dat']['sections'][0]['id'] == 'a' and d['expertplusstandard.dat']['sections'][0]['id'] == 'h'
    assert d['expertplusstandard.dat']['name'] == 'ExpertPlusStandard.dat'
    assert p['graph']['out']['diffs'] == {'Hard': 1}   # 入れ替わって来た Hard の譜面は印をまだ誰も決めていない＝決めていないまま（NLM ではどちらも書き出さない）
    assert p['current'] == 'HardStandard.dat'
    with pytest.raises(KeyError):
        diffs.move(p, 'Easy', 'Normal')


def test_move_keeps_undecided_marks_undecided():
    """印をまだ誰も決めていない基準（元のプロジェクトの印は NLM の新しいプロジェクトと同じく空）を置き直しても「外す」と書かない
    （前は外すと書き、Joy to the love の Hard が書き出されなかった・2026-11-03）。決めてあれば今まで通り付け替える"""
    p = _proj()
    p['graph']['out']['diffs'] = {}
    p['infoGraph']['nodes']['s1']['data']['diffs'] = {}
    diffs.move(p, 'ExpertPlus', 'Hard')
    assert p['graph']['out']['diffs'] == {} and p['infoGraph']['nodes']['s1']['data']['diffs'] == {}
    assert diffs.mark_of(p, 'Hard') is None and diffs.mark_default(p, 'Hard')   # 決めていない＝作り直し・展開が付ける
    assert p['graph']['out']['diffs'] == {'Hard': 1} == p['infoGraph']['nodes']['s1']['data']['diffs']
    q = _proj()
    q['graph']['out']['diffs'] = {'ExpertPlus': 0}   # NLM で外してあった＝外したまま移す
    q['infoGraph']['nodes']['s1']['data']['diffs'] = {'ExpertPlus': 0}
    diffs.move(q, 'ExpertPlus', 'Hard')
    assert q['graph']['out']['diffs'] == {'ExpertPlus': 0, 'Hard': 0} and not diffs.mark_default(q, 'Hard')


def test_mark_default_only_when_undecided_and_filled():
    """基準の書き出す印: まだ誰も決めていなくてノーツがある時だけ付ける。NLM で外した（0）・空の難易度は触らない。set の節だけにある印も見る"""
    p = _proj()
    p['graph']['out']['diffs'] = {}
    p['infoGraph']['nodes']['s1']['data']['diffs'] = {}
    assert not diffs.mark_default(p, 'Hard') and diffs.mark_of(p, 'Hard') is None   # ノーツが無い
    assert diffs.mark_default(p, 'ExpertPlus') and diffs.mark_of(p, 'ExpertPlus') == 1
    assert not diffs.mark_default(p, 'ExpertPlus')   # もう決めてある
    q = _proj()
    q['graph']['out']['diffs'] = {}
    q['infoGraph']['nodes']['s1']['data']['diffs'] = {'ExpertPlus': 0}   # NLM は開く時に set の節から作り直す
    assert diffs.mark_of(q, 'ExpertPlus') == 0 and not diffs.mark_default(q, 'ExpertPlus')


def test_report_path():
    out = Path('out/BURN.intent-s1.nlmf')
    assert diffs.report_path(out) == Path('out/BURN.intent-s1.report.md') == out.with_suffix('.report.md')
    assert diffs.report_path(out, 'Expert') == Path('out/BURN.intent-s1.Expert.report.md')
