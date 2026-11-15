from automap import intent, rhythm


def _ons(n=32):
    """4拍の小節 n/4 個分の打点の候補: キックは毎拍の頭（強）・スネアは裏拍（中）・歌は半拍ごと（弱め）・楽器は2つだけ"""
    O = rhythm.Onset
    return {'kick': [O(float(b), float(b), 'kick', 0.8) for b in range(n)],
            'snare': [O(b + 0.5, b + 0.5, 'snare', 0.65) for b in range(n)],
            'vocal': [O(b / 2, b / 2, 'vocal', 0.5, 60.0, 0.5) for b in range(2 * n)],
            'other': [O(1.0, 1.0, 'other', 0.9), O(9.0, 9.0, 'other', 0.9)]}


def _secs(n=32):
    return [rhythm.Section('A', 0, n, vocal=True)]


def _hits(n=32):
    """自動で選んだ打点: 1拍ごとの片手"""
    return [rhythm.Hit(float(b), 1, 0, 0, 'kick', 0.8) for b in range(n)]


def _it(ranges, line=None):
    return {'ranges': ranges, 'line': line or [], 'auto_rest': {'on': False, 'b': None}}


def _apply(it, hits=None):
    return intent.apply(hits or _hits(), _ons(), _secs(), it, [0, 4, 8, 12, 16, 20, 24, 28], 32)


def test_rest_removes_hits():
    """休みの区間の打点は全部消え、ほかは残る"""
    out, rep = _apply(_it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'rest': 1}}]))
    assert not [h for h in out if 8 <= h.beat < 16]
    assert len(out) == 32 - 8
    assert rep[-1][3] == ['休み']


def test_amount_up_adds_hits():
    """量 +2 は、その区間の打点が元（1拍ごと）より増え、区間の外は変わらない"""
    out, _ = _apply(_it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'amount': 2}}]))
    assert len([h for h in out if 8 <= h.beat < 16]) > 8
    assert [h.beat for h in out if h.beat < 8] == list(range(8))


def test_kick_makes_doubles():
    """キックで決める（2）: その区間のキックの所が両手になり、強い打点として流れの計算に渡る"""
    out, _ = _apply(_it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'kick': 2}}]))
    dbl = [h for h in out if h.hands == 2]
    assert dbl and all(8 <= h.beat < 16 and getattr(h, 'force_strong', False) for h in dbl)
    # 両手のすぐ前後（1/4 拍未満）に打点が無い
    beats = [h.beat for h in out]
    for h in dbl:
        assert all(abs(b - h.beat) >= 0.25 - 1e-6 for b in beats if b != h.beat)


def test_line_scales_per_bar():
    """全体の量のライン: 倍率 0.5 の所は小節ごとに打点が半分ほどになり、小節の頭は残る"""
    out, _ = _apply(_it([], line=[{'b': 0, 'k': 0.5}, {'b': 32, 'k': 0.5}]))
    for a in range(0, 32, 4):
        bh = [h.beat for h in out if a <= h.beat < a + 4]
        assert len(bh) == 2 and a in bh


def test_source_fallback_keeps_original():
    """元にする音に打点がほとんど無い（楽器が 2 つだけ）時は、元の打点のまま"""
    out, rep = _apply(_it([{'id': 1, 'b0': 0, 'b1': 16, 'set': {'source': 'inst'}}]))
    assert [h.beat for h in out if h.beat < 16] == list(range(16))
    assert '元のまま' in rep[0][3][0]


def test_speed_and_motif_pass_to_flow():
    """振りの速さの上限と同じ振りは、打点に印を付けて流れの計算へ渡す（打点の数は変えない）"""
    out, _ = _apply(_it([{'id': 1, 'b0': 4, 'b1': 8, 'set': {'speed': 1, 'motif': {'group': 'X', 'mode': 'same'}}}]))
    inr = [h for h in out if 4 <= h.beat < 8]
    assert len(inr) == 4
    assert all(h.min_gap == intent.MIN_GAP[1] and h.motif['group'] == 'X' and h.motif['idx'] == 0 for h in inr)
    assert not any(hasattr(h, 'motif') for h in out if not 4 <= h.beat < 8)


def test_place_mods_and_not_yet():
    """置き方の指示は打点に印（mods）を付けて流れの計算へ渡し、報告の「置き方:」に出す。そのまま残すは打点を変えず報告に出す
    （前の譜面を残すのは compose＝_keep_plan）"""
    out, rep = _apply(_it([{'id': 1, 'b0': 0, 'b1': 8, 'set': {'height': 1, 'diag': -1, 'keep': True}}]))
    assert len(out) == 32
    assert all(h.mods == {'height': 1, 'diag': -1} for h in out if h.beat < 8)
    assert not any(getattr(h, 'mods', None) for h in out if h.beat >= 8)
    assert any(d.startswith('置き方:') and 'height 1' in d and 'diag -1' in d for d in rep[0][3])
    assert any(d.startswith('そのまま残す') for d in rep[0][3]) and not any('まだ効かない' in d for d in rep[0][3])


def test_source_bass():
    """元にする音: ベース → その区間はベースの打点（拍の頭と裏の強い所）だけになる"""
    O = rhythm.Onset
    ons = dict(_ons(), bass=[O(b, b, 'bass', 0.9) for b in (8.0, 9.5, 11.5, 12.0, 13.5)] + [O(10.25, 10.25, 'bass', 0.9)])
    out, rep = intent.apply(_hits(), ons, _secs(), _it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'source': 'bass'}}]),
                            [0, 4, 8, 12, 16, 20, 24, 28], 32)
    assert [h.beat for h in out if 8 <= h.beat < 16] == [8.0, 9.5, 11.5, 12.0, 13.5]
    assert all(h.src == 'bass' for h in out if 8 <= h.beat < 16)


def test_load_drops_exact_duplicates(tmp_path):
    """ページで同じ区間に同じ指示を2回付けた物は1つに"""
    import json
    r = {'b0': 4, 'b1': 6, 'set': {'amount': 1, 'motif': {'group': 'X', 'mode': 'same'}}}
    p = tmp_path / 'a.intent.json'
    p.write_text(json.dumps({'ranges': [r, dict(r), {'b0': 8, 'b1': 10, 'set': {'amount': 1}}]}), encoding='utf-8')
    assert [(x['b0'], x['b1']) for x in intent.load(p)['ranges']] == [(4, 6), (8, 10)]


def _motif_ons():
    O = rhythm.Onset
    return dict(_ons(), vocal=[O(b, b, 'vocal', 0.9) for b in (4.0, 4.5, 5.0, 5.5, 12.0, 13.5, 20.0)])


def _mk_motif(b0, mode):
    return {'b0': b0, 'b1': b0 + 2, 'set': {'amount': 1, 'motif': {'group': 'X', 'mode': mode}}}


def test_motif_copies_rhythm_of_the_first():
    """同じ振り（そのまま）: 一番前の区間（手本）の打点の並びを、ほかの区間へ区間の頭からの拍で写す（ほかの区間の歌の拾い方に関わらず）"""
    it = _it([_mk_motif(20, 'same'), _mk_motif(4, 'same'), _mk_motif(12, 'same')])
    out, rep = intent.apply(_hits(), _motif_ons(), _secs(), it, [0, 4, 8, 12, 16, 20, 24, 28], 32)
    for k, b0 in enumerate((4, 12, 20)):
        inr = [h for h in out if b0 <= h.beat < b0 + 2]
        assert [h.beat - b0 for h in inr] == [0.0, 0.5, 1.0, 1.5]
        assert all(h.motif['occ'] == k and h.motif['b0'] == b0 and h.motif['key'] == 'X' and h.hands == 1 for h in inr)


def test_motif_arrange_adds_notes():
    """同じ振り（アレンジ）: 2回目・4回目…は手本の並びのノーツを増やした形（間に強い音が無ければ強い打点を両手に。両手どうしの間の
    片手は偶数個＝片手は上・片手は下の両手にならない）。1回目・3回目…は手本のまま"""
    it = _it([_mk_motif(4, 'arrange'), _mk_motif(12, 'arrange'), _mk_motif(20, 'arrange')])
    out, rep = intent.apply(_hits(), _motif_ons(), _secs(), it, [0, 4, 8, 12, 16, 20, 24, 28], 32)
    got = lambda b0: [(h.beat - b0, h.hands) for h in out if b0 <= h.beat < b0 + 2]
    assert got(4) == got(20) == [(0.0, 1), (0.5, 1), (1.0, 1), (1.5, 1)]
    assert got(12) == [(0.0, 2), (0.5, 1), (1.0, 1), (1.5, 2)]
    assert {h.motif['key'] for h in out if 12 <= h.beat < 14} == {'X（アレンジ）'}


def _motif_stream(beats, model_b0, head_b0):
    """片手の打点の並び（半拍ごと）に、手本の区間と、写した区間（各 4 打点）の印を付ける → (hits, events)"""
    from automap import flow, nlmf
    tm = nlmf.TempoMap(120)
    hits, events = [], []
    for b in beats:
        h = rhythm.Hit(b, 1, 0, 0, 'vocal', 0.8)
        for k, b0 in enumerate((model_b0, head_b0)):
            if b0 <= b < b0 + 2:
                h.motif = {'group': 'X', 'key': 'X', 'mode': 'same', 'idx': k, 'b0': b0, 'occ': k}
        hits.append(h)
        events.append(flow.Event(b, tm.sec(b), 1))
    return hits, events


def test_motif_breath_cuts_or_adds_before_the_head():
    """写した区間の入りで、両手の振りの向きのそろい方が手本と逆（間の片手の打点が奇数個）なら、直前（1拍以内）の打点を抜く。
    空きが 1.5 拍以上なら、入りの1拍前に足す"""
    from automap import flow
    from automap.__main__ import _motif_breath
    beats = [i * 0.5 for i in range(41)]   # 4〜6 が手本、12.5〜14.5 が写した所＝間の片手が 13 個（奇数）
    hits, events = _motif_stream(beats, 4.0, 12.5)
    gen, _ = flow.generate(events, flow.Style(seed=1))
    cut, add = _motif_breath(hits, events, gen, {})
    assert (cut, add) == ([12.0], []) and len(hits) == len(events) == 40
    beats = [b for b in beats if b not in (11.5, 12.0)]   # 入りの前が 1.5 拍空いている（間の片手は 11 個）
    hits, events = _motif_stream(beats, 4.0, 12.5)
    gen, _ = flow.generate(events, flow.Style(seed=1))
    cut, add = _motif_breath(hits, events, gen, {})
    assert (cut, add) == ([], [11.5]) and [h.beat for h in hits if 11 <= h.beat < 12.5] == [11.0, 11.5]


def test_auto_rest_empties_one_bar():
    """自動の休み: 位置に一番近い小節を1つ空ける（休み・同じ振りの区間は避ける）。入っていなければ何もしない"""
    bars = [0, 4, 8, 12, 16, 20, 24, 28]
    it = _it([])
    it['auto_rest'] = {'on': True, 'b': 13}
    out, rep = intent.apply(_hits(), _ons(), _secs(), it, bars, 32)
    assert not [h for h in out if 12 <= h.beat < 16] and len(out) == 28
    assert '自動の休み（拍 12〜16）' in rep[-1][3]
    it = _it([{'id': 1, 'b0': 12, 'b1': 16, 'set': {'rest': True}}])
    it['auto_rest'] = {'on': True, 'b': 13}
    out, rep = intent.apply(_hits(), _ons(), _secs(), it, bars, 32)
    assert not [h for h in out if 8 <= h.beat < 16] or not [h for h in out if 12 <= h.beat < 20]
    it = _it([])
    it['auto_rest'] = {'on': False, 'b': 13}
    out, _ = intent.apply(_hits(), _ons(), _secs(), it, bars, 32)
    assert len(out) == 32


def test_variety_bar_theme():
    """型の変わり方: −1 は区間の最初の小節のテーマのまま・+1 は小節の後ろ半分を別のテーマに"""
    from automap.__main__ import _bar_theme
    bgd = {0: (100, 'a', 'base'), 1: (101, 'b', 'base'), 2: (102, 'c', 'base')}
    bars = [0, 4, 8]
    assert _bar_theme(bgd, bars, 9)[0] == 102
    assert _bar_theme(bgd, bars, 9, {'v': -1, 'b0': 0})[0] == 100
    assert _bar_theme(bgd, bars, 5, {'v': 1, 'b0': 0})[0] == 101
    assert _bar_theme(bgd, bars, 6, {'v': 1, 'b0': 0})[0] == 102
    assert _bar_theme(bgd, bars, 10, {'v': 1, 'b0': 0})[0] == 101


def test_motif_arrange_extra():
    """アレンジの量（同じ振りの欄）: 0＝手本と同じ並び・−1＝手本より少ない・+2＝+1 より多い"""
    O = rhythm.Onset
    ons = dict(_motif_ons(), snare=_ons()['snare'] + [O(b, b, 'snare', 0.7) for b in (12.25, 12.75, 13.25)])

    def run(extra):
        it = _it([_mk_motif(b, 'arrange') for b in (4, 12, 20)])
        for r in it['ranges']:
            r['set']['motif']['extra'] = extra
        out, rep = intent.apply(_hits(), ons, _secs(), it, [0, 4, 8, 12, 16, 20, 24, 28], 32)
        return [(h.beat - 12, h.hands) for h in out if 12 <= h.beat < 14]
    assert run(0) == [(0.0, 1), (0.5, 1), (1.0, 1), (1.5, 1)]
    assert len(run(-1)) < 4
    n = lambda xs: sum(hd for _, hd in xs)
    assert n(run(2)) > n(run(1)) > n(run(0))


def test_motif_form_directives():
    """形ごとの指示: アレンジの形のどれかの区間に付けた「両手 −1」はアレンジの形の全部に、手本の形のどれかに別に付けた「量」は
    手本の区間にも効く（同じ振りの区間に付いた量より、別に付けた量が勝つ）"""
    it = _it([_mk_motif(b, 'arrange') for b in (4, 12, 20, 28)])
    it['ranges'] += [{'b0': 28, 'b1': 30, 'set': {'hands': -1}}, {'b0': 20, 'b1': 22, 'set': {'amount': -2}}]
    out, rep = intent.apply(_hits(), _motif_ons(), _secs(), it, [0, 4, 8, 12, 16, 20, 24, 28], 32)
    got = lambda b0: [(h.beat - b0, h.hands) for h in out if b0 <= h.beat < b0 + 2]
    assert all(hd == 1 for _, hd in got(12) + got(28))
    assert [o for o, _ in got(4)] == [o for o, _ in got(20)] == [0.0, 1.0]


def test_variant_spec():
    """案 k → (テーマのずらし, 種): 5 個ずらすごとに種が1つ進む（案を作る時も作り直しの時もこの決まり）"""
    import pytest
    assert [intent.variant_spec(k) for k in (1, 2, 5, 6, 7, 10, 11)] == [(1, 1), (2, 1), (5, 1), (1, 2), (2, 2), (5, 2), (1, 3)]
    with pytest.raises(ValueError):
        intent.variant_spec(0)


def test_variant_is_a_known_directive():
    """「案 k」は知っている指示: 打点は変えず、報告に案の作り方を出す（「まだ効かない」に出さない）。使えない番号はその知らせ"""
    out, rep = _apply(_it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'variant': 7}}]))
    assert [h.beat for h in out] == list(range(32)) and not any(hasattr(h, 'variety') or getattr(h, 'mods', None) for h in out)
    assert rep[0][3] == ['案 7（テーマのずらし 2・種 2）']
    _, rep = _apply(_it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'variant': 0, 'hands': 1}}]))
    assert any('案の番号が使えない' in d for d in rep[0][3]) and not any('まだ効かない' in d for d in rep[0][3])


def test_variants_in_table_order():
    """意思入れの表の「案」の区間を表の順に（後の物が勝つ）。休みの区間・使えない番号は除く"""
    it = _it([{'b0': 0, 'b1': 8, 'set': {'variant': 2}}, {'b0': 4, 'b1': 12, 'set': {'variant': 6, 'amount': 1}},
              {'b0': 12, 'b1': 16, 'set': {'variant': 3, 'rest': True}}, {'b0': 16, 'b1': 20, 'set': {'variant': 0}},
              {'b0': 20, 'b1': 24, 'set': {'variant': 1.5}}, {'b0': 24, 'b1': 28, 'set': {'variant': True}},
              {'b0': 28, 'b1': 32, 'set': {'variant': 3.0}}])
    assert intent.theme_ranges(it) == [(0, 8, 2, False), (4, 12, 6, False), (28, 32, 3, False)]
    assert intent.theme_ranges(None) == []


def test_variant_inside_a_motif_is_not_copied_to_the_model():
    """同じ振りの形の区間の中の「案」は、形の指示として手本の区間に効かせ直さない（テーマは手本から取るので案は効かない）"""
    it = _it([_mk_motif(4, 'same'), _mk_motif(12, 'same'), {'b0': 12, 'b1': 14, 'set': {'variant': 2}}])
    _, rep = intent.apply(_hits(), _motif_ons(), _secs(), it, [0, 4, 8, 12, 16, 20, 24, 28], 32)
    assert not any('案' in d for d in rep[0][3])
    assert rep[2][3] == ['案 2（テーマのずらし 2・種 1）']


def test_rare_and_kime_are_known_directives():
    """「珍しい型まで」・「決め」は知っている指示: 打点は変えず、報告に出す（「まだ効かない」に出さない）"""
    out, rep = _apply(_it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'rare': 1, 'kime': -1}}]))
    assert [h.beat for h in out] == list(range(32)) and not any(getattr(h, 'mods', None) for h in out)
    assert rep[0][3] == ['珍しい型まで（テーマを少ない曲にしか出ない型まで広げた束から）', '決めを入れない']
    _, rep = _apply(_it([{'id': 1, 'b0': 8, 'b1': 16, 'set': {'kime': 1, 'rare': 0}}]))
    assert rep[0][3] == ['珍しい型まで: 切', '決めを入れる'] and not any('まだ効かない' in d for d in rep[0][3])


def test_theme_and_kime_ranges():
    """テーマを選び直す区間（案・珍しい型まで）と決めの区間: 表の順・休みは除く。珍しい型までは決めの指示が無ければ入れる側"""
    it = _it([{'b0': 0, 'b1': 8, 'set': {'rare': 1}}, {'b0': 8, 'b1': 12, 'set': {'variant': 2, 'rare': 1, 'kime': -1}},
              {'b0': 12, 'b1': 16, 'set': {'variant': 3}}, {'b0': 16, 'b1': 20, 'set': {'rare': 1, 'rest': True}},
              {'b0': 20, 'b1': 24, 'set': {'kime': 1}}, {'b0': 24, 'b1': 28, 'set': {'kime': 0, 'rare': False}}])
    assert intent.theme_ranges(it) == [(0, 8, 0, True), (8, 12, 2, True), (12, 16, 3, False)]
    assert intent.kime_ranges(it) == ([(0, 8), (20, 24)], [(8, 12)])
    assert intent.theme_ranges(None) == [] and intent.kime_ranges(None) == ([], [])


def test_rare_inside_a_motif_is_not_copied_to_the_model():
    """同じ振りの形の区間の中の「珍しい型まで」・「決め」も、形の指示として手本の区間に効かせ直さない（案と同じ）"""
    it = _it([_mk_motif(4, 'same'), _mk_motif(12, 'same'), {'b0': 12, 'b1': 14, 'set': {'rare': 1, 'kime': 1}}])
    _, rep = intent.apply(_hits(), _motif_ons(), _secs(), it, [0, 4, 8, 12, 16, 20, 24, 28], 32)
    assert not any('珍しい' in d or '決め' in d for d in rep[0][3])


BARS = [0, 4, 8, 12, 16, 20, 24, 28]


def _line(hits, line, inner=(), outer=()):
    return intent.apply_line(hits, _it([], line=line), BARS, 32, _ons(), _secs(), inner=inner, outer=outer)


def test_line_after_repeats_thins_every_occurrence_at_the_same_places():
    # 拍 0〜8 が手本・拍 16〜24 が写した回（同じリズム）・どちらも 0.5 → 同じ位置を抜く（くり返しを崩さない）
    hits = [rhythm.Hit(b + 0.5 * k, 1, 0, 0, 'kick', 0.3 + 0.1 * k) for b in range(32) for k in range(2)]
    out, row = _line(hits, [{'b': 0, 'k': 0.5}, {'b': 32, 'k': 0.5}], outer=[[(0.0, 8.0), (16.0, 24.0)]])
    rel = lambda b0: sorted(round(h.beat - b0, 3) for h in out if b0 <= h.beat < b0 + 8)
    assert rel(0) == rel(16) and len(rel(0)) == 8
    assert '同じ位置で写した' in row[3][0]


def test_line_after_repeats_treats_occurrences_with_other_values_separately():
    # 手本は 1.0・写した回だけ 0.5 → 手本は変えず、写した回だけ減らす（人の指示が勝つ）
    hits = [rhythm.Hit(b + 0.5 * k, 1, 0, 0, 'kick', 0.3 + 0.1 * k) for b in range(32) for k in range(2)]
    line = [{'b': 0, 'k': 1.0}, {'b': 15.99, 'k': 1.0}, {'b': 16, 'k': 0.5}, {'b': 32, 'k': 0.5}]
    out, _ = _line(hits, line, outer=[[(0.0, 8.0), (16.0, 24.0)]])
    assert sum(0 <= h.beat < 8 for h in out) == 16 and sum(16 <= h.beat < 24 for h in out) == 8


def test_line_carries_rounding_over_short_sets():
    # 2 拍のセット（打点 3）が続く所に 0.9: 1 セットずつ四捨五入すると 1 つも減らない → 端数を持ち越して全体で 1 割ほど減らす
    hits = [rhythm.Hit(b + off, 1, 0, 0, 'kick', 0.5) for b in range(0, 32, 2) for off in (0, 0.5, 1.0)]
    inner = [[(float(s + 2 * j), float(s + 2 * j + 2)) for j in range(4)] for s in range(0, 32, 8)]
    out, _ = _line(hits, [{'b': 0, 'k': 0.9}, {'b': 32, 'k': 0.9}], inner=inner)
    assert 40 <= len(out) <= 45   # 48 × 0.9 ≈ 43
    for s in range(0, 32, 8):   # セットの組の中は同じリズムのまま
        rel = [sorted(round(h.beat - (s + 2 * j), 3) for h in out if s + 2 * j <= h.beat < s + 2 * j + 2) for j in range(4)]
        assert all(r == rel[0] for r in rel)


def test_apply_without_line_leaves_the_line_for_later():
    out, rep = intent.apply(_hits(), _ons(), _secs(), _it([], line=[{'b': 0, 'k': 0.5}, {'b': 32, 'k': 0.5}]), BARS, 32, line=False)
    assert len(out) == 32 and not any('量のライン' in ' '.join(r[3]) for r in rep)


# ---- 量のラインで増やす側（apply_line の put・motif_families。compose は自動のくり返しの後に呼ぶ・docs/方針.md 6.33） ----

UP = [{'b': 0, 'k': 1.5}, {'b': 32, 'k': 1.5}]


def _ons_by(strong):
    """毎拍の頭のキック（0.8）・裏拍のスネア（strong の拍だけ 0.9・ほかは 0.3）。足す打点は強い裏拍から選ばれる"""
    O = rhythm.Onset
    return {'kick': [O(float(b), float(b), 'kick', 0.8) for b in range(32)],
            'snare': [O(b + 0.5, b + 0.5, 'snare', 0.9 if b + 0.5 in strong else 0.3) for b in range(32)]}


def test_line_up_adds_auto_hits_from_strong_onsets():
    """倍率 1.5: 小節ごとに打点が 4 → 6（強い音から・元の打点は全部残る・小節の頭も残る）。報告の行に足した数"""
    hits = _hits()
    out, row = intent.apply_line(hits, _it([], line=UP), BARS, 32, _ons(), _secs())
    assert {h.beat for h in hits} <= {h.beat for h in out}
    for a in range(0, 32, 4):
        bh = sorted(h.beat for h in out if a <= h.beat < a + 4)
        assert len(bh) == 6 and a in bh
        assert [b - a for b in bh if b % 1] == [0.5, 1.5]   # 裏拍のスネア（同じ強さなら前から）
    assert all(h.hands == 1 and h.src == 'snare' for h in out if h.beat % 1)
    assert '足し 16・減らし 0' in row[3][0]
    # 量・元にする音・休みの区間は触らない（人の指示が勝つ）
    it = _it([{'b0': 8, 'b1': 16, 'set': {'amount': 1}}, {'b0': 20, 'b1': 24, 'set': {'rest': 1}}], line=UP)
    out, _ = intent.apply_line(_hits(), it, BARS, 32, _ons(), _secs())
    assert sum(8 <= h.beat < 16 for h in out) == 8 and sum(20 <= h.beat < 24 for h in out) == 4
    assert sum(0 <= h.beat < 4 for h in out) == 6


def test_line_up_adds_at_the_same_places_in_every_repeat():
    """くり返しの組（自動の同じ振り＝outer）: 手本の窓で決めた足しを、写した回にも同じ位置で足す（写した回の強い音の位置に
    関わらず）。組の外は小節ごとに自分の強い音から"""
    strong = {0.5, 2.5, 4.5, 6.5, 17.5, 19.5, 21.5, 23.5}   # 手本（0〜8）と写した回（16〜24）で強い裏拍がずれている
    rel = lambda out, b0: sorted(round(h.beat - b0, 3) for h in out if b0 <= h.beat < b0 + 8)
    out, row = intent.apply_line(_hits(), _it([], line=UP), BARS, 32, _ons_by(strong), _secs(), outer=[[(0.0, 8.0), (16.0, 24.0)]])
    assert rel(out, 0) == rel(out, 16) == [0, 0.5, 1, 2, 2.5, 3, 4, 4.5, 5, 6, 6.5, 7]
    assert 'うち、くり返しの回に同じ位置で写した 4' in row[3][0]
    alone, _ = intent.apply_line(_hits(), _it([], line=UP), BARS, 32, _ons_by(strong), _secs())   # 組が無ければ回ごとに自分の強い音
    assert rel(alone, 16) == [0, 1, 1.5, 2, 3, 3.5, 4, 5, 5.5, 6, 7, 7.5] != rel(alone, 0)


def test_line_up_copies_nested_echo_sets_into_the_repeat():
    """続けて左右反転のセット（inner・2 拍）の中で決めた足しをセットの全部に同じ位置で・その手本の窓を含む自動の同じ振り（outer）の
    写した回にも同じ位置で（内側の組の分も写す）。足した打点にはその回の同じ振りの印"""
    strong = {1.5, 3.5, 5.5, 7.5, 16.5, 18.5}
    hits = _hits()
    for h in hits:
        if 0 <= h.beat < 8 or 16 <= h.beat < 24:
            h.motif = {'key': 'R', 'b0': 0.0 if h.beat < 8 else 16.0, 'occ': int(h.beat >= 16), 'auto': True}
    inner = [[(float(s), float(s + 2)) for s in range(0, 8, 2)]]
    out, _ = intent.apply_line(hits, _it([], line=UP), BARS, 32, _ons_by(strong), _secs(), inner=inner, outer=[[(0.0, 8.0), (16.0, 24.0)]])
    sets = [sorted(round(h.beat - s, 3) for h in out if s <= h.beat < s + 2) for s in (0, 2, 4, 6, 16, 18, 20, 22)]
    assert all(r == [0, 1, 1.5] for r in sets)   # 1 拍目の裏（手本のセットの強い音）を、どのセットにも・写した回にも
    added = [h for h in out if h.beat % 1 and (h.beat < 8 or 16 <= h.beat < 24)]
    assert len(added) == 8 and all(h.motif['occ'] == int(h.beat >= 16) for h in added)


def test_motif_families_and_line_up_on_the_users_motif():
    """利用者の同じ振り（意思入れ）: 同じ形の回の並び（手本が先頭・休みの区間と自動の同じ振りと 1 回だけの形は入れない）。
    compose と同じつなぎ方（intent.apply → motif_families → apply_line）で、量のラインの足しが全部の回の同じ位置に入る"""
    mot = lambda b0, g='X', **kw: {'b0': b0, 'b1': b0 + 4, 'set': {'motif': {'group': g, 'mode': 'same'}, **kw}}
    it = _it([mot(16), mot(4), mot(24, rest=1), mot(8, 'Y')], line=UP)
    hits, _ = intent.apply(_hits(), _ons(), _secs(), it, BARS, 32, line=False)
    auto = rhythm.Hit(28.0, 1, 0, 0, 'kick', 0.8)
    auto.motif = {'key': 'Z', 'b0': 28.0, 'occ': 1, 'auto': True}
    fam = intent.motif_families(it, hits + [auto])
    assert fam == [[(4, 8), (16, 20)]]
    out, row = intent.apply_line(hits, it, BARS, 32, _ons(), _secs(), outer=fam)
    rel = lambda b0: sorted(round(h.beat - b0, 3) for h in out if b0 <= h.beat < b0 + 4)
    assert rel(4) == rel(16) and len(rel(4)) > 4
    assert all(h.motif['occ'] == (0 if h.beat < 8 else 1) for h in out if (4 <= h.beat < 8 or 16 <= h.beat < 20) and h.beat % 1)
    assert 'くり返しの回に同じ位置で写した' in row[3][0]
