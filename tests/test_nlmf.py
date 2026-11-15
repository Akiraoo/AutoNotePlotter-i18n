import json

from automap import nlmf


def _proj():
    sec = lambda sid, beat, tr, notes, lk='n': {'id': sid, 'beat': beat, 'track': tr, 'lk': lk, 'len': 8, 'label': sid,
                                                'col': 0, 'colHex': None, 'kind': 'sheet', 'content': {'notes': notes} if notes else {}}
    diff = lambda secs, flat: {'name': 'X.dat', 'v3': True, 'base': {}, 'notes': flat, 'bombs': [], 'walls': [], 'arcs': [],
                               'chains': [[4, 0, 1, 0, 1, 4.5, 1, 1, 3, 1, 1]], 'lightEvents': [[0, 1, 1, None, 0]], 'sections': secs}
    return {
        'format': 'nlmf', 'version': 2, 'bpm': 120, 'tempoParts': [], 'current': 'ExpertPlusStandard.dat', 'notesLanes': 2,
        'lightLanes': 1, 'markers': [], 'laneStates': {'mute': ['n1', 'l0'], 'solo': [], 'lock': ['n0'], 'editOnly': 1},
        'difficulties': {
            'expertplusstandard.dat': diff([sec('a', 0, 1, [[1, 1, 0, 0, 1, None], [-1, 2, 0, 1, 1, None], [9, 2, 0, 1, 1, None]]),
                                            sec('b', 8, 0, [[0, 2, 0, 1, 1, None]]), sec('l', 0, 0, None, lk='l')],
                                           [[1, 1, 0, 0, 1, 1], [8, 2, 0, 1, 1, 0]]),
            'hardstandard.dat': diff([sec('c', 0, 1, [[2, 1, 0, 0, 1, None]])], [[2, 1, 0, 0, 1, 1]]),
        },
    }


def test_clip_notes_reads_visible_content_only():
    p = _proj()
    got = nlmf.clip_notes(p, 'expertplusstandard.dat', include_muted=True)
    assert [(n['beat'], n['tr']) for n in got] == [(1, 1), (8, 0)]   # 負の拍・長さの外は隠れた分
    assert [n['beat'] for n in nlmf.clip_notes(p, 'expertplusstandard.dat')] == [8]   # n1 はミュート


CLIP = {'beat': 0, 'len': 8, 'label': '自動', 'colHex': '#e0a040',
        'notes': [{'beat': 0, 'x': 1, 'y': 0, 'c': 0, 'd': 1}, {'beat': 7.5, 'x': 2, 'y': 0, 'c': 1, 'd': 0},
                  {'beat': 8, 'x': 2, 'y': 0, 'c': 1, 'd': 1}]}


def test_put_note_lane_shifts_existing_lanes(tmp_path):
    p = _proj()
    assert nlmf.put_note_lane(p, {'expertplusstandard.dat': [CLIP]}) == 0   # 一番上（b）が使われている＝1本足す
    assert p['notesLanes'] == 3
    ep = p['difficulties']['expertplusstandard.dat']
    tracks = {s['id']: s['track'] for s in ep['sections']}
    assert tracks['a'] == 2 and tracks['b'] == 1 and tracks['l'] == 0   # ライトのクリップはずらさない
    assert p['difficulties']['hardstandard.dat']['sections'][0]['track'] == 2
    new = [s for s in ep['sections'] if s['label'] == '自動'][0]
    assert new['track'] == 0 and new['content']['notes'] == [[0, 1, 0, 0, 1, None], [7.5, 2, 0, 1, 0, None]]   # 8 拍は範囲の外
    assert sorted(a[5] for a in ep['notes']) == [0, 0, 1, 2]
    assert ep['chains'][0][10] == 1 + 1 and ep['lightEvents'][0][4] == 0   # チェーンの _tr（10項目の後ろ）はずらす・ライトはそのまま
    ls = p['laneStates']
    assert ls['mute'] == ['n2', 'l0'] and ls['lock'] == ['n1'] and ls['editOnly'] == 2   # 同じレーンに付いたままずらす
    out = tmp_path / 'o.nlmf'
    nlmf.save(p, out)
    assert json.loads(out.read_text(encoding='utf-8'))['notesLanes'] == 3


def test_clear_notes_then_reuse_empty_top_lane():
    p = _proj()
    assert nlmf.clear_notes(p, 'expertplusstandard.dat') == 2
    ep = p['difficulties']['expertplusstandard.dat']
    assert [s['id'] for s in ep['sections']] == ['l'] and ep['notes'] == [] and ep['chains'] == []
    assert ep['lightEvents'] == [[0, 1, 1, None, 0]]   # ライトは残す
    assert nlmf.put_note_lane(p, {'expertplusstandard.dat': [CLIP]}) == 0   # 一番上は全難易度で空＝足さずに使う
    assert p['notesLanes'] == 2 and p['difficulties']['hardstandard.dat']['sections'][0]['track'] == 1
    assert sorted(a[5] for a in ep['notes']) == [0, 0] and p['laneStates']['mute'] == ['n1', 'l0']


def test_tempo_parts():
    tm = nlmf.TempoMap(120, [{'beat': 4, 'bpm': 60}])
    assert tm.sec(4) == 2.0 and tm.sec(5) == 3.0


def test_result_file_edited_in_nlm_becomes_the_base(tmp_path):
    import argparse
    from automap import __main__ as cli
    src = tmp_path / 'song.nlmf'
    nlmf.save(_proj(), src)
    out = tmp_path / 'out' / 'song.result.nlmf'
    out.parent.mkdir()
    a = argparse.Namespace(input=str(src), out=str(out), fresh=False)
    proj, used, note = cli._open_project(a, out)
    assert used == src and note is None                       # 結果がまだ無い＝入力が土台
    cli._save(proj, out)
    used, note = cli._open_project(a, out)[1:]
    assert used == out and 'old/' not in note                 # 結果のファイルがあればそれが土台（こちらで書いたままなら控えは取らない）
    d = json.loads(out.read_text(encoding='utf-8'))           # NLM で無音追加を直して保存した
    d['graph'] = {'song': {'offset': -0.21}}
    out.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    proj, used, note = cli._open_project(a, out)
    assert used == out and proj['graph']['song']['offset'] == -0.21 and 'old/' in note
    assert len(list((out.parent / 'old').glob('song.result.*.nlmf'))) == 1   # 上書きの前の控え
    cli._save(proj, out)                                      # 作り直して保存しても、次も結果のファイルが土台（直した設定が残る）
    proj, used, _ = cli._open_project(a, out)
    assert used == out and proj['graph']['song']['offset'] == -0.21
    a.fresh = True
    assert cli._open_project(a, out)[1] == src                # --fresh は入力が土台


def test_items_before_and_put_back_keep_other_kinds():
    p = _proj()
    ep = p['difficulties']['expertplusstandard.dat']
    a = next(s for s in ep['sections'] if s['id'] == 'a')   # 拍 0 から 8 拍・track 1
    a['content']['bombs'] = [[2, 1, 1, None], [7, 0, 0, None]]
    a['content']['arcs'] = [[1, 0, 1, 0, 1, 1, 3, 2, 2, 0, 1, 0, None]]
    a['content']['notes'][0] = [1, 1, 0, 0, 1, None, {'a': 15}]   # 矢印の角度など標準外の項目
    keep = nlmf.items_before(p, 'expertplusstandard.dat', 5)
    assert keep['notes'] == [[1, 1, 0, 0, 1, None, {'a': 15}]]       # 拍 8 の b・負の拍・長さの外は入らない
    assert keep['bombs'] == [[2, 1, 1, None]] and keep['arcs'] == [[1, 0, 1, 0, 1, 1, 3, 2, 2, 0, 1, 0, None]]
    nlmf.clear_notes(p, 'expertplusstandard.dat')
    clip = {'beat': 0, 'len': 8, 'label': '自動', 'colHex': None, 'notes': [{'beat': 6, 'x': 2, 'y': 0, 'c': 1, 'd': 1}], 'extra': keep}
    nlmf.put_note_lane(p, {'expertplusstandard.dat': [clip]})
    new = [s for s in ep['sections'] if s['label'] == '自動'][0]
    assert new['content']['notes'] == [[1, 1, 0, 0, 1, None, {'a': 15}], [6, 2, 0, 1, 1, None]]
    assert new['content']['arcs'][0][6] == 3 and ep['arcs'][0][12] == 0 and ep['bombs'] == [[2, 1, 1, 0]]
    assert [n[:6] for n in ep['notes']] == [[1, 1, 0, 0, 1, 0], [6, 2, 0, 1, 1, 0]]
