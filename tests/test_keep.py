"""NLM とのやり取りの決まり（作ったクリップの id＝中身の指紋・作り直しで NLM で直した所を残す）"""
import copy

from automap import nlmf
from automap import __main__ as cli

DK = 'expertplusstandard.dat'


def _proj():
    """拍 0〜32 を作ったクリップ 4 つ（8 拍ずつ・隙間なし）で覆った作業用のファイル（こちらで書いたまま）"""
    p = {'format': 'nlmf', 'version': 2, 'bpm': 120, 'tempoParts': [], 'current': 'ExpertPlusStandard.dat', 'notesLanes': 1,
         'lightLanes': 1, 'markers': [{'beat': 0, 'name': 'A'}, {'beat': 8, 'name': 'B'}, {'beat': 16, 'name': 'C'}, {'beat': 24, 'name': 'D'}],
         'laneStates': {'mute': [], 'solo': [], 'lock': []},
         'difficulties': {DK: {'name': 'ExpertPlusStandard.dat', 'v3': True, 'base': {}, 'notes': [], 'bombs': [], 'walls': [],
                               'arcs': [], 'chains': [], 'lightEvents': [[0, 1, 1, None, 0]],
                               'sections': [{'id': 'l1', 'beat': 0, 'track': 0, 'lk': 'l', 'len': 32, 'label': 'light', 'content': {}}]}}}
    notes = [{'beat': b + 0.0, 'x': 1 + (i % 2), 'y': 0, 'c': i % 2, 'd': 1 if (i // 2) % 2 == 0 else 0} for i, b in enumerate(range(1, 32))]
    nlmf.put_note_lane(p, {DK: cli._cover_clips(p, notes, 32)})
    return p


def _clip(p, beat):
    return next(s for s in nlmf.note_clips(p['difficulties'][DK]) if s['beat'] == beat)


def test_fingerprint_follows_content_only():
    """同じ中身なら同じ指紋（NLM が後ろの None を省いても・1 と 1.0 でも）。ノーツを1つ動かす・始まりを動かすと変わる。レーンの番号は入れない"""
    p = _proj()
    s = _clip(p, 8)
    assert s['id'] == nlmf.clip_id(DK, s) and s['id'].startswith('au') and len(s['id']) == 9
    t = copy.deepcopy(s)
    t['content']['notes'] = [[float(a[0]), *a[1:5]] for a in t['content']['notes']]   # 後ろの None を省き、拍を小数に
    t['track'] = 3
    assert nlmf.clip_id(DK, t) == s['id']
    t['content']['notes'][0][1] = (t['content']['notes'][0][1] + 1) % 4
    assert nlmf.clip_id(DK, t) != s['id']
    u = copy.deepcopy(s)
    u['beat'] += 1
    assert nlmf.clip_id(DK, u) != s['id'] and nlmf.clip_id('hardstandard.dat', s) != s['id']


def test_written_clips_cover_the_song():
    """作ったクリップは曲の頭から終わりまで隙間なく（ノーツの無い区間も空のクリップ）"""
    p = _proj()
    st = p['difficulties'][DK]
    st['sections'] = [s for s in st['sections'] if s.get('lk') == 'l']
    nlmf.put_note_lane(p, {DK: cli._cover_clips(p, [{'beat': 9, 'x': 1, 'y': 0, 'c': 0, 'd': 1}], 32)})
    cs = sorted(nlmf.note_clips(st), key=lambda s: s['beat'])
    assert [(s['beat'], s['len'], s['label']) for s in cs] == [(0, 8, '自動 A'), (8, 8, '自動 B'), (16, 8, '自動 C'), (24, 8, '自動 D')]
    assert [bool(s['content']) for s in cs] == [False, True, False, False]
    assert nlmf.coverage_holes(p, DK, 0, 32) == []


def _edit(p):
    """NLM で直した: B のノーツを1つ動かす・C の名前に「固定」・D を消す・別のレーンに利用者のクリップ"""
    st = p['difficulties'][DK]
    b = _clip(p, 8)
    b['content']['notes'][0][1] = (b['content']['notes'][0][1] + 1) % 4
    _clip(p, 16)['label'] += ' 固定'
    st['sections'] = [s for s in st['sections'] if s.get('beat') != 24 or s.get('lk') == 'l']
    p['notesLanes'] = 2
    st['sections'].append({'id': 'n5abcd', 'beat': 2, 'track': 1, 'lk': 'n', 'len': 4, 'label': 'Sheet', 'kind': 'sheet',
                           'content': {'notes': [[0, 0, 0, 0, 1, None]]}})
    return _nlm_flat(p)


def _nlm_flat(p):
    """NLM の保存と同じく、フラットの配列をクリップの中身から作り直す"""
    st = p['difficulties'][DK]
    for key in nlmf.FLAT_N:
        fi = len(nlmf._enc_fields(key))
        out = []
        for s in nlmf.note_clips(st):
            for t in (s.get('content') or {}).get(key) or []:
                if 0 <= t[0] < s['len']:
                    f = list(t) + [None] * max(0, fi + 1 - len(t))
                    f[0], f[fi] = nlmf._r(t[0] + s['beat']), s.get('track') or 0
                    out.append(f)
        st[key] = sorted(out, key=lambda t: t[0])
    return p


def test_classify_and_holes():
    p = _edit(_proj())
    got = {s['beat'] if s['track'] == 0 else ('user', s['beat']): st for s, st in nlmf.classify(p, DK)[0]}
    assert got == {0: 'app', 8: 'edited', 16: 'fixed', ('user', 2): 'user'}
    assert nlmf.classify(p, DK)[1:] == (True, 0)                  # 新しい形式・作ったクリップのレーン 0
    assert nlmf.coverage_holes(p, DK, 0, 32) == [(24, 32)]        # 消した所


def test_legacy_ids_are_kept_unless_written_as_is():
    """前の形式（id がでたらめ）: こちらで書いたまま（手元の指紋が一致）なら作り直す・分からなければ残す"""
    p = _proj()
    for k, s in enumerate(nlmf.note_clips(p['difficulties'][DK])):
        s['id'] = 'auxyz%04d' % k
    assert {st for _, st in nlmf.classify(p, DK)[0]} == {'legacy'} and nlmf.classify(p, DK)[1] is False
    assert {st for _, st in nlmf.classify(p, DK, as_written=True)[0]} == {'app'}


def test_regenerate_keeps_edits_and_leaves_deleted_empty():
    """作り直し: 作ったままのクリップだけ入れ替え、直した・固定・利用者のクリップはそのまま、消した所は空のまま（打点も作らない）"""
    p = _edit(_proj())
    before = {s['id']: copy.deepcopy(s) for s in nlmf.note_clips(p['difficulties'][DK])}
    plan = cli._keep_plan(p, DK, False, 32)
    assert [s['beat'] for s in plan['remove']] == [0]
    assert sorted(r for r in plan['blocked']) == [(2, 6), (8, 16), (16, 24), (24, 32)]
    new = [{'beat': b, 'x': 3, 'y': 1, 'c': 1, 'd': 0} for b in (1, 3, 7)]
    nlmf.remove_clips(p, DK, plan['remove'])
    nlmf.put_clips(p, DK, cli._cover_clips(p, new, 32, exclude=plan['exclude']), plan['lane'])
    after = {s['id']: s for s in nlmf.note_clips(p['difficulties'][DK])}
    for i, s in before.items():
        if s['beat'] != 0 or s['track'] == 1:
            assert after[i] == s                                      # 残したクリップはそのまま
    assert not any(s['track'] == 0 and s['beat'] < 32 and s['beat'] + s['len'] > 24 for s in after.values())   # 消した所は空のまま
    a0 = next(s for s in after.values() if s['track'] == 0 and s['beat'] == 0)
    assert a0['id'] == nlmf.clip_id(DK, a0) and len(a0['content']['notes']) == 3
    flat = sorted(tuple(a[:6]) for a in p['difficulties'][DK]['notes'])
    assert flat == sorted((nlmf._r(n['beat']), n['x'], n['y'], n['c'], n['d'], n['tr'])
                          for n in nlmf.clip_notes(p, DK, include_muted=True))   # フラットもクリップの中身と同じ


def test_copies_judge_themselves(tmp_path):
    """同じファイルを2つにコピーして別々に直しても、それぞれ自分の中身で判定できる（外の控えに頼らない）"""
    p = _proj()
    a, b = tmp_path / 'a.nlmf', tmp_path / 'b.nlmf'
    nlmf.save(p, a)
    nlmf.save(p, b)
    pa, pb = nlmf.load(a), nlmf.load(b)
    _clip(pa, 0)['content']['notes'][0][2] = 2   # a は頭のクリップを直した
    _clip(pb, 16)['content']['notes'].pop()      # b は C を直した
    nlmf.save(pa, a)
    nlmf.save(pb, b)
    sa = {s['beat']: st for s, st in nlmf.classify(nlmf.load(a), DK)[0]}
    sb = {s['beat']: st for s, st in nlmf.classify(nlmf.load(b), DK)[0]}
    assert sa == {0: 'edited', 8: 'app', 16: 'app', 24: 'app'}
    assert sb == {0: 'app', 8: 'app', 16: 'edited', 24: 'app'}


def test_kept_hits_merge_slider_tails():
    """残したノーツ → 流れに入れる打点（同じ色が 0.07 秒以内に続く物は1つ・両手は2色）"""
    from automap import rhythm
    tm = nlmf.TempoMap(120)
    secs = [rhythm.Section('A', 0, 32)]
    ns = [{'beat': 4, 'x': 1, 'y': 0, 'c': 0, 'd': 1}, {'beat': 4, 'x': 2, 'y': 0, 'c': 1, 'd': 1},
          {'beat': 5, 'x': 1, 'y': 0, 'c': 0, 'd': 0}, {'beat': 5.1, 'x': 1, 'y': 1, 'c': 0, 'd': 0}]
    hs = cli._kept_hits(ns, secs, tm)
    assert [(h.beat, h.hands, h.kept) for h in hs] == [(4, 2, True), (5, 1, True)]
    assert hs[0].fix == {0: (1, 0, 1), 1: (2, 0, 1)}


def test_only_range_keeps_outside_and_splits_at_the_edges():
    """選んだ区間だけ作り直す（--only）: 区間の外の作ったクリップは残し、またぐクリップは境目で分けて外側を同じ中身の新しいクリップに
    （id は中身の指紋＝作ったまま）。区間の外のノーツは1つも変わらず、区間の中だけ入れ替わる・隙間はできない"""
    p = _proj()
    st = p['difficulties'][DK]
    note = lambda n: (nlmf._r(n['beat']), n['x'], n['y'], n['c'], n['d'])
    before = sorted(note(n) for n in nlmf.clip_notes(p, DK, include_muted=True))
    plan = cli._keep_plan(p, DK, False, 32, only=(10, 20))
    assert sorted(s['beat'] for s, why in plan['kept'] if why == 'outside') == [0, 24]
    assert sorted(s['beat'] for s in plan['remove']) == [8, 16]
    assert sorted((c['beat'], c['len']) for c in plan['split']) == [(8, 2), (20, 4)]
    assert (0.0, 10) in plan['blocked'] and (20, 32) in plan['blocked']
    assert sorted(n['beat'] for n in plan['kept_notes']) == [b for b in range(1, 32) if not 10 <= b < 20]
    new = [{'beat': b + 0.5, 'x': 0, 'y': 2, 'c': 0, 'd': 0} for b in range(10, 20, 2)]
    nlmf.remove_clips(p, DK, plan['remove'])
    nlmf.put_clips(p, DK, cli._cover_clips(p, new, 32, exclude=plan['exclude']) + plan['split'], plan['lane'])
    after = sorted(note(n) for n in nlmf.clip_notes(p, DK, include_muted=True))
    assert [n for n in after if not 10 <= n[0] < 20] == [n for n in before if not 10 <= n[0] < 20]   # 外は1つも変わらない
    assert [n for n in after if 10 <= n[0] < 20] == sorted(note(n) for n in new)                    # 中だけ入れ替わる
    assert {why for _, why in nlmf.classify(p, DK)[0]} == {'app'}                                     # 分けた外側も作ったまま
    assert nlmf.coverage_holes(p, DK, 0, 32) == []
    labels = sorted((s['beat'], s['len'], s['label']) for s in nlmf.note_clips(st))
    assert (8, 2, '自動 B') in labels and (20, 4, '自動 C') in labels


def test_motif_breath_stays_inside_the_range():
    """選んだ区間だけ作り直す時、入りの前の打点を抜く・足すは区間の中だけ（外は今の譜面のまま）"""
    from automap import flow
    from test_intent import _motif_stream
    beats = [i * 0.5 for i in range(41)]
    hits, events = _motif_stream(beats, 4.0, 12.5)
    gen, _ = flow.generate(events, flow.Style(seed=1))
    cut, add = cli._motif_breath(hits, events, gen, {}, allow=(12.25, 20))   # 直前の 12.0 は区間の外＝抜かない
    assert 12.0 not in cut and all(12.25 <= b < 20 for b in cut + add)


def test_edited_clip_stays_edited_after_a_regeneration():
    """前の作り直しで残した「手で直した」クリップは、ファイル全体がこちらで書いたまま（手元の指紋が一致）でも、次の作り直しで
    入れ替えない（新しい形式では手元の指紋に頼らない）"""
    p = _edit(_proj())
    assert {st for s, st in nlmf.classify(p, DK, as_written=True)[0] if s['beat'] == 8} == {'edited'}
    assert {st for s, st in nlmf.classify(p, DK, as_written=True)[0] if s['beat'] == 0} == {'app'}
