"""分けた音 → 打点 → テーマ → 置き方の部品の約束（試作1 から）。"""
import numpy as np
import soundfile as sf

from automap import audio, flow, form, nlmf, rhythm, theme

THEME_R = [(2, 0, 1), (2, 2, 0), (2, 0, 1), (3, 1, 5)]   # ↓20 ↑22 ↓20 ↗31（右手の形）


def _guided(beats, cyc_r=THEME_R, doubles=(), bpm=120):
    tm = nlmf.TempoMap(bpm)
    cyc = {0: theme.mirror(cyc_r), 1: list(cyc_r)}
    return [flow.Event(b, tm.sec(b), 2 if b in doubles else 1, 0, cyc) for b in beats]


def _style(**kw):
    return flow.Style(seed=1, noise=0.0, w_same_hand=1.0, w_target={k: 0.0 for k in ('row', 'dir', 'center', 'still', 'alt', 'col')}, **kw)


def test_theme_is_followed_when_there_is_time():
    notes, _ = flow.generate(_guided([float(i) for i in range(32)]), _style())
    for c in (0, 1):
        want = THEME_R if c == 1 else theme.mirror(THEME_R)
        got = [(n['x'], n['y'], n['d']) for n in sorted(notes, key=lambda n: n['beat']) if n['c'] == c]
        assert got == [tuple(want[k % 4]) for k in range(len(got))], f'手 {c} が型どおりでない'


def test_guided_keeps_parity_and_no_handclap():
    beats = [i * 0.25 for i in range(96)]
    notes, _ = flow.generate(_guided(beats, doubles={b for b in beats if b % 4 == 0}), _style())
    for c in (0, 1):
        ns = sorted((n for n in notes if n['c'] == c), key=lambda n: n['beat'])
        pars = [flow.parity_of(c, n['d']) for n in ns]
        assert all(a != b for a, b in zip(pars, pars[1:]))
    by = {}
    for n in notes:
        by.setdefault(n['beat'], {})[n['c']] = n
    for pair in by.values():
        if len(pair) == 2:
            l, r = pair[0], pair[1]
            assert not flow.handclap(l['x'], l['y'], l['d'], r['x'], r['y'], r['d'])
            assert not flow.hitbox_path(l['x'], l['y'], l['d'], r['x'], r['y'], r['d'])


def test_transforms_keep_parity_alternation():
    for name in ('base', 'swap', 'calm'):
        for cyc in theme.transform(theme.Theme(THEME_R, THEME_R, 1, 'sym'), name):
            pars = [flow.parity_of(1, d) for _, _, d in cyc]
            assert all(pars[k] != pars[(k + 1) % len(pars)] for k in range(len(pars))), name
            assert all(0 <= x <= 3 and 0 <= y <= 2 for x, y, _ in cyc)


def _one_block(level, vocal=True, markers=()):
    """まとまり 1 つ（拍 0〜8・盛り上がりの段階 level）の曲の流れの表 → (form.sections, form.plan)"""
    blocks = [form.Block(0.0, 8.0, 0, 2, group='A', base='A', level=level, vocal=vocal)]
    return form.sections(blocks, list(markers), 8.0), form.plan(blocks)


def test_double_needs_room_around_it():
    secs, plan = _one_block(3)   # 一番盛り上がる段階＝小節の頭と真ん中・フレーズの頭を両手に足そうとする
    ons = {'vocal': [rhythm.Onset(b, b, 'vocal', 0.9, 60, 0.2) for b in (0, 0.25, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7)],
           'kick': [rhythm.Onset(b, b, 'kick', 0.9) for b in range(8)], 'snare': [], 'hihat': [], 'other': []}
    hits = rhythm.choose_hits(ons, secs, plan)
    assert any(h.hands == 2 for h in hits)
    for i, h in enumerate(hits):
        if h.hands == 2:
            assert (i == 0 or h.beat - hits[i - 1].beat >= 0.5) and (i + 1 == len(hits) or hits[i + 1].beat - h.beat >= 0.5)


def test_vocal_notes_from_synthetic_tones(tmp_path):
    sr = 44100
    t = np.arange(int(sr * 0.5)) / sr
    tone = lambda f: 0.4 * np.sin(2 * np.pi * f * t) * np.minimum(1, np.minimum(t, 0.5 - t) / 0.01)
    y = np.concatenate([np.zeros(sr // 2), tone(220.0), np.zeros(sr // 4), tone(261.63), np.zeros(sr // 2)])
    p = tmp_path / 'v.flac'
    sf.write(str(p), np.stack([y, y], axis=1), sr)
    notes = audio.vocal_notes(p)
    assert len(notes) == 2
    assert abs(notes[0]['midi'] - 57) < 0.5 and abs(notes[1]['midi'] - 60) < 0.5
    assert abs(notes[0]['t0'] - 0.5) < 0.05 and abs(notes[1]['t0'] - 1.25) < 0.05


def test_sec_to_beat_matches_nlm():
    # 無音追加 240ms・BPM 129: 拍 b の時刻＝b×60/129 秒、元の音源の秒＝その時刻−0.24
    b = 10.0
    assert abs(audio.sec_to_beat(b * 60 / 129 - 0.24, 129, 240) - b) < 1e-9
    assert audio.snap(2.26) == (2.25, 4, 2.26 - 2.25) or audio.snap(2.26)[0] == 2.25
    assert audio.snap(2.33)[:2] == (2 + 1 / 3, 3)


def test_calm_does_not_block_vision():
    for cyc in ([(2, 0, 1), (2, 2, 0)], [(1, 0, 6), (3, 2, 5)], list(THEME_R)):
        for x, y, d in theme.tf_calm(cyc):
            assert not (x in (1, 2) and y == 1)


def test_no_hitbox_stair():
    notes, _ = flow.generate(_guided([i * 0.25 for i in range(96)], bpm=120), _style())
    last = {}
    for n in sorted(notes, key=lambda n: (n['beat'], n['c'])):
        o = last.get(1 - n['c'])
        if o and 0 < (n['beat'] - o['beat']) * 0.5 < 0.15:
            dx, dy = flow.DIR_SPACE[o['d']]
            assert (n['x'], n['y']) != (o['x'] + dx, o['y'] + dy), n
        last[n['c']] = n


def test_marker_tags_do_not_split_sections():
    ms = [{'beat': 0, 'name': 'Aメロ'}, {'beat': 15.5, 'name': '★サビ'}, {'beat': 20, 'name': '★'}, {'beat': 28, 'name': 'ドラム'},
          {'beat': 32, 'name': 'アウトロ'}, {'beat': 36, 'name': '※ここ振りにくい'}]
    secs = rhythm.sections_from_markers(ms, 40)
    assert secs[2].tags == [(36.0, '※ここ振りにくい', 40.0)]
    assert [(s.name, s.b0, s.b1) for s in secs] == [('Aメロ', 0, 15.5), ('サビ', 15.5, 32), ('アウトロ', 32, 40)]
    assert secs[1].tags == [(15.5, '★', 20.0), (20.0, '★', 28.0), (28.0, 'ドラム', 32.0)]
    assert rhythm.phrase_tag(secs[1], 18, 24) == '★' and rhythm.phrase_tag(secs[1], 24, 32) is None
    assert rhythm.drum_ranges(secs[1]) == [(28.0, 32.0)]


def test_drum_range_uses_drums_not_vocals():
    secs, plan = _one_block(2, markers=[{'beat': 4, 'name': 'ドラム'}])   # 拍 4 から「ドラム」
    assert secs[0].tags == [(4.0, 'ドラム', 8.0)]
    ons = {'vocal': [rhythm.Onset(b * 0.5, b * 0.5, 'vocal', 0.9, 60, 0.2) for b in range(16)],
           'kick': [rhythm.Onset(float(b), float(b), 'kick', 0.9) for b in range(8)], 'snare': [], 'hihat': [], 'other': []}
    hits = rhythm.choose_hits(ons, secs, plan)
    assert {h.src for h in hits if h.beat < 4} == {'vocal'} and {h.src for h in hits if h.beat >= 4} == {'kick'}


def test_hitbox_path_geometry():
    assert flow.hitbox_path(2, 0, 7, 3, 1, 5)        # 左↘(2,0)・右↗(3,1): 右の振り上げが左下から入る所に左のノーツ（曲B の拍121.75）
    assert not flow.hitbox_path(1, 0, 1, 2, 0, 1)    # 左↓(1,0)・右↓(2,0): ふつうの両手同時
    assert not flow.hitbox_path(0, 0, 1, 3, 0, 1)    # 離れている


def test_ease_lowers_every_other_top_upswing():
    cyc = [(1, 0, 6), (2, 2, 0), (3, 1, 7), (2, 2, 0)]   # ↙10 ↑22 ↘31 ↑22（曲B のサビのテーマ）
    e = theme.tf_ease(cyc)
    assert e[1] == (2, 2, 0) and e[3] == (3, 1, 5)       # 2つ目の振り上げは外の列の中段へ斜め上
    e2 = theme.tf_ease([(2, 0, 1), (2, 2, 0)])          # 2振りの型は4振りに延ばして2回に1回下げる
    assert e2 == [(2, 0, 1), (2, 2, 0), (2, 0, 1), (3, 1, 5)]


def test_hands_do_not_follow_into_the_same_cell():
    """左右の手が同じマスに続けて来ない（NLM の hitboxInline・2D で後ろに急に現れて見える形）"""
    notes, _ = flow.generate(_guided([i * 0.25 for i in range(96)], bpm=175), _style())
    tm = nlmf.TempoMap(175)
    last = {}
    for n in sorted(notes, key=lambda n: (n['beat'], n['c'])):
        o = last.get(1 - n['c'])
        if o and 0 < tm.sec(n['beat']) - tm.sec(o['beat']) < 0.2:
            assert (n['x'], n['y']) != (o['x'], o['y']), n
        last[n['c']] = n


def test_regen_from_marker_and_init():
    assert rhythm.regen_from([{'beat': 40, 'name': 'サビ'}, {'beat': 64.5, 'name': 'ここから'}, {'beat': 80, 'name': 'ここから★'}]) == 64.5
    assert rhythm.regen_from([{'beat': 0, 'name': 'Aメロ'}]) is None
    secs = rhythm.sections_from_markers([{'beat': 0, 'name': 'Aメロ'}, {'beat': 8, 'name': 'ここから'}], 16)
    assert [(s.name, s.b0, s.b1) for s in secs] == [('Aメロ', 0, 16)]     # 区間は切らない
    tm = nlmf.TempoMap(120)
    kept = [{'beat': 0, 'x': 1, 'y': 0, 'c': 0, 'd': 1}, {'beat': 0.5, 'x': 2, 'y': 0, 'c': 1, 'd': 1}]   # 左右とも振り下ろしで終わる
    init = flow.init_from(kept, tm)
    assert init[0][0] == flow.F and init[1][0] == flow.F and init[2] == 1
    notes, _ = flow.generate(_guided([1.0, 1.5, 2.0, 2.5]), _style(), init=init)
    for c in (0, 1):
        first = min((n for n in notes if n['c'] == c), key=lambda n: n['beat'])
        assert flow.parity_of(c, first['d']) == flow.B          # 続きは振り上げから（交互を引き継ぐ）


def test_vocal_snap_prefers_strong_beats_in_fast_songs():
    # BPM 175（1/4 拍 86ms）: 1/4 拍の位置から 25ms ずれた歌は、強い位置（半拍）へ。BPM 129（1/4 拍 116ms）では 1/4 拍のまま
    q = 0.25
    off = lambda bpm, ms: ms / 1000 * bpm / 60
    assert rhythm.snap_vocals([1 + q + off(175, 25)], 175)[0] == 1.5
    assert rhythm.snap_vocals([1 + q + off(129, 25)], 129)[0] == 1.25
    assert rhythm.snap_vocals([1 + q + off(175, 5)], 175)[0] in (1.0, 1.5)   # 速い曲は 1/4 拍の位置に 2 段分の減点＝強い位置へ（人の譜面で一番合った）
    assert rhythm.snap_vocals([1 + q + off(129, 5)], 129)[0] == 1.25          # 遅めの曲は 1/4 拍の細かさを残す
    assert rhythm.vocal_prior_ms(175) == 45 and rhythm.vocal_prior_ms(129) == 15


def test_weak_vocal_boundary_snaps_to_half_beats():
    # 谷の浅い続きの区切りは 1/4 拍の位置に置かない（半拍まで）。ほかは今まで通り
    raw = [1.27, 1.27, 1.70, 1.70]
    q = rhythm.snap_vocals(raw, 129, coarse=[False, True, False, True])
    assert list(q) == [1.25, 1.5, 1.75, 1.5]
    assert list(rhythm.snap_vocals(raw, 129)) == list(rhythm.snap_vocals(raw, 129, coarse=[False] * 4))


def test_merge_phantoms_folds_unbacked_weak_vocals_into_previous():
    O = rhythm.Onset
    v = [O(1.0, 1.0, 'vocal', 0.9, 60, 0.5), O(1.5, 1.52, 'vocal', 0.9, 60, 0.4), O(2.0, 2.0, 'vocal', 0.9, 60, 0.3),
         O(2.5, 2.47, 'vocal', 0.9, 60, 0.3)]
    backing = [O(2.0, 2.0, 'snare', 0.8), O(2.5, 2.5, 'other', 0.1)]   # 2.5 の楽器は弱い＝鳴っていないのと同じ
    out = rhythm.merge_phantoms(v, [False, True, True, True], backing)
    assert [o.beat for o in out] == [1.0, 2.0]          # 1.5（楽器なし）と 2.5（弱い楽器だけ）は前にまとめる・2.0 はスネアがあるので残す
    assert abs(out[0].length - (1.52 + 0.4 - 1.0)) < 1e-9 and abs(out[1].length - (2.47 + 0.3 - 2.0)) < 1e-9
    assert [o.beat for o in rhythm.merge_phantoms(v, [True, False, False, False], [])] == [1.0, 1.5, 2.0, 2.5]   # 頭は残す


def test_vocal_dip_separates_rearticulation_from_sustain():
    fps = 100
    flat = np.full(100, -15.0)
    flat[48:53] += np.array([1, -1, -2, -1, 1])          # 伸ばしの中の小さな揺れ
    gap = np.full(100, -15.0)
    gap[45:51] = -30                                      # 子音で沈んで歌い直し
    assert audio._dip(flat, 50, fps) < rhythm.WEAK_DIP_DB <= audio._dip(gap, 50, fps)


def test_vocal_lag_is_circular_mean():
    import numpy as np
    raw = np.array([k * 0.5 + 0.05 for k in range(40)] + [k * 0.5 + 0.03 for k in range(40)])   # 目盛りから 0.03〜0.05 拍遅れ
    assert abs(rhythm.vocal_lag(raw) - 0.04) < 1e-3


def test_vocal_lag_uses_the_grid_where_vocals_gather():
    import numpy as np
    # 16 分で歌う: 拍の頭・裏と 1/4 拍の位置に半々（1/2 拍の目盛りでは集まらない）。遅れは 0.03 拍
    raw = np.array([k * 0.25 + 0.03 for k in range(80)])
    assert abs(rhythm.vocal_lag(raw) - 0.03) < 1e-3
    rng = np.random.default_rng(0)
    assert rhythm.vocal_lag(rng.uniform(0, 100, 400)) == 0.0     # どこにも集まらなければ差し引かない


def test_regen_no_longer_writes_the_old_subtitle():
    # アプリの作り直しは曲のサブタイトルを書かない。前の既定の「意思入れ」は空に・利用者が入れたサブタイトルはそのまま
    from automap import __main__ as cli
    mk = lambda s: {'info': {'_songSubName': s}, 'infoGraph': {'nodes': {'m': {'t': 'meta', 'data': {'sub': s}}}}}
    p = mk('意思入れ')
    cli._clear_old_subtitle(p)
    assert p['info']['_songSubName'] == '' and p['infoGraph']['nodes']['m']['data']['sub'] == ''
    p = mk('Remix')
    cli._clear_old_subtitle(p)
    assert p['info']['_songSubName'] == 'Remix' and p['infoGraph']['nodes']['m']['data']['sub'] == 'Remix'
