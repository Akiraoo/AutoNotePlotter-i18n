"""区間の指示「★の帯」（この区間はライブラリの★の帯を変えて取り直す・docs/アプリ仕様.md 8 節の 9）"""
from types import SimpleNamespace

import pytest

from automap import form, intent, library_use, theme
from automap import __main__ as cli
from test_anchor import BARS, EMPTY, _t
from test_versions import _variant_setup, app  # noqa: F401  （app＝写しの場所で server と versions をつなぐ）

pytestmark = pytest.mark.usefixtures('pinned_scale')


def test_band_values_and_names():
    """set.band・--band の値: 段の数（+＝難しく・−3〜3）か [下, 上]。使えない値は None（既定の作り方）"""
    assert [intent.band_of(v) for v in (1, -1, 2, 5, -9, '+1', '-1', 1.0)] == [1, -1, 2, 3, -3, 1, -1, 1]
    assert intent.band_of([6, 10]) == [6, 10] and intent.band_of('6,10') == [6, 10] and intent.band_of('6〜10') == [6, 10]
    assert intent.band_of([10, 6]) == [6, 10] and intent.band_of([-2, 4]) == [0, 4] and intent.band_of([6.5, 9]) == [6.5, 9]
    assert all(intent.band_of(v) is None for v in (0, None, True, False, 1.5, 'x', [3], [5, 5], [None, 2], {}))
    assert intent.band_text(1) == '★1段難しく' and intent.band_text(-1) == '★1段やさしく'
    assert [intent.band_text(b) for b in ([6, 10], [0, 8], [10, 99], [0, 99])] == ['★6〜10', '★〜8', '★10〜', '★全部']
    assert library_use.stars_text([8, 12]) == '★8〜12' and library_use.stars_text(None) == '★全部'


def test_band_steps_shift_the_song_band():
    """1段＝帯の両端を段の境目（〜4・6・8・10・12・それより上）で1つずらす。下が開いた帯（★〜x）を難しくする時は上の2段の帯
    として数える（★〜8 → ★6〜10）。曲の設定が無い・★全部は既定（★〜8）から。端で止まる・幅は1段より狭くしない"""
    st = library_use.band_stars
    assert [st(v, [0, 8]) for v in (1, 2, 3, -1, -2, -3)] == [[6, 10], [8, 12], [10, 99], [0, 6], [0, 4], [0, 4]]
    assert st(1, [6, 10]) == [8, 12] and st(-1, [6, 10]) == [4, 8] and st(1, [8, 12]) == [10, 99]
    assert st(1, [10, 99]) == [12, 99] and st(-1, [10, 99]) == [8, 12] and st(1, [0, 6]) == [4, 8]
    assert st(1, None) == st(1, [0, 99]) == st(1, library_use.DEFAULT['stars']) == [6, 10]
    assert st([8, 12], [0, 8]) == [8, 12] and st(0, [0, 8]) is None


def test_band_filters_change_only_the_stars():
    """帯の書き出しの絞り込み: 曲の設定の★だけ変える（ほかはそのまま）。設定が無ければ新しい曲の既定の★を変えた物（時期が自動のまま
    ＝曲が分からない所は年を絞らない）。珍しい型までと一緒の時は頻度を上書きできる"""
    f = library_use.band_filters(None, 1)
    assert f == dict(library_use.concrete(library_use.DEFAULT), stars=[6, 10])   # 前は今の型の曲＝前の既定（2020 年以降）
    song = {'sources': ['ranked'], 'stars': [6, 10], 'freq': '定番', 'hard': 'ふつう'}
    assert library_use.band_filters(song, -1) == {'sources': ['ranked'], 'stars': [4, 8], 'freq': '定番', 'hard': 'ふつう'}
    assert library_use.band_filters(song, [8, 12], freq='珍しい')['freq'] == '珍しい'
    assert song['stars'] == [6, 10]   # 曲の設定は書き換えない


def test_export_band_reuses_the_same_band(monkeypatch):
    """同じ帯の書き出しは1回の作り直しの中で使い回す（データベースから書き出すのは帯ごとに1回）"""
    got = []
    monkeypatch.setattr(library_use, 'export', lambda f, themes=None: got.append(f) or {'f': f})
    cache = {}
    a = library_use.export_band(None, 1, cache)
    b = library_use.export_band(None, [6, 10], cache)   # 同じ帯（★〜8 の1段難しく＝★6〜10）
    c = library_use.export_band(None, -1, cache)
    assert a is b and a is not c and len(got) == 2


def test_theme_ranges_take_band_only_when_asked():
    """theme_ranges(it, band=True): ★の帯だけの区間も入れて 5 つ目に帯。既定の呼び方は前と同じ形（★の帯だけの区間は入らない）。休みは除く"""
    it = {'ranges': [{'b0': 0, 'b1': 8, 'set': {'band': 1}}, {'b0': 8, 'b1': 12, 'set': {'band': [8, 12], 'variant': 2, 'rare': 1}},
                     {'b0': 12, 'b1': 16, 'set': {'variant': 3}}, {'b0': 16, 'b1': 20, 'set': {'band': 1, 'rest': True}},
                     {'b0': 20, 'b1': 24, 'set': {'band': 0}}]}
    assert intent.theme_ranges(it) == [(8, 12, 2, True), (12, 16, 3, False)]
    assert intent.theme_ranges(it, band=True) == [(0, 8, 0, False, 1), (8, 12, 2, True, [8, 12]), (12, 16, 3, False, None)]
    assert 'band' in intent.THEME_KEYS   # 打点の指示ではない（同じ振りの形の手本に効かせ直さない）


def test_band_is_a_changed_range_for_the_previous_chart():
    """前の譜面に寄せる: ★の帯を足した・変えた・消した区間は「指示が変わった所」（小節の頭と終わりまで）"""
    free, glob, why = intent.changed_ranges(EMPTY, _t((9, 14, {'band': 1})), BARS, 32)
    assert free == [(8, 16)] and not glob and why
    free, _, _ = intent.changed_ranges(_t((8, 16, {'band': 1})), _t((8, 16, {'band': [8, 12]})), BARS, 32)
    assert free == [(8, 16)]
    free, _, _ = intent.changed_ranges(_t((8, 16, {'band': 1})), EMPTY, BARS, 32)
    assert free == [(8, 16)]
    t = _t((8, 16, {'band': -1}))
    assert intent.changed_ranges(t, _t((8, 16, {'band': -1})), BARS, 32) == ([], False, [])


def test_band_ranges_choose_bar_themes_from_the_band_bundle():
    """★の帯: 区間と重なる小節だけ、帯を変えた型の束で選んだ並び（pal_of(s, 珍しい型まで, 帯)）のテーマ。案 k と一緒ならその帯の並びの中で
    案 k のずらし方・珍しい型までと一緒ならその帯の束を広げた物。★の帯・案・珍しい型までは小節ごとに別々に勝ち負け"""
    T, blocks, mu, seq, bgd, _ = _variant_setup()
    H = [theme.Theme([(3, 0, 1), (3, 1, 0)], [(0, 0, 1), (0, 1, 0)], 2, 'pair'),
         theme.Theme([(2, 0, 7), (3, 2, 5)], [(1, 0, 6), (0, 2, 4)], 2, 'pair'),
         theme.Theme([(1, 0, 1), (2, 2, 0)], [(2, 0, 1), (1, 2, 0)], 2, 'pair')]
    calls = []

    def pal_of(s, rare=False, band=None):
        calls.append((s, rare, band))
        return ({'x': H}, {'A': H}) if band is not None else ({'x': T}, seq)
    hb = form.mix_guides(blocks, mu, {'A': H})
    it = {'ranges': [{'b0': 0, 'b1': 4, 'set': {'band': 1}}, {'b0': 8, 'b1': 12, 'set': {'band': [8, 12], 'variant': 1}}]}
    vr = cli._variant_ranges(it, 0, None)
    assert vr == [(0, 4, 0, '意思入れ', False, 1), (8, 12, 1, '意思入れ', False, [8, 12])]
    alt, rep = cli._apply_variants(bgd, blocks, mu, vr, pal_of)
    assert alt[0] == hb[0]                                  # ★の帯（案なし）＝帯の並びのまま
    assert alt[1] == bgd[1] and alt[3] == bgd[3]            # 重ならない小節はそのまま
    assert alt[2][1] == hb[(2 + 1) % 3][1]                  # ★の帯＋案 1＝帯の並びで 1 ずらす
    assert all(alt[i][0] == bgd[i][0] for i in bgd)
    assert {(c[0], c[1], str(c[2])) for c in calls} == {(1, False, '1'), (1, False, '[8, 12]')}
    assert [r[8] for r in rep] == [1, [8, 12]] and rep[0][6] == 1
    # 後から付けた --variant（案だけ）は★の帯を消さない・--band（別の案）は --only の区間
    calls.clear()
    vr2 = cli._variant_ranges(it, 2, (0, 4), cli_band=None)
    alt2, _ = cli._apply_variants(bgd, blocks, mu, vr2, pal_of)
    assert alt2[0][1] == hb[(0 + 2) % 3][1]
    assert cli._variant_ranges(None, 0, (4, 8), cli_band=-1) == [(4, 8, 0, '--band', False, -1)]
    assert cli._variant_ranges(None, 3, None, True, [6, 10]) == [(None, None, 3, '--variant --rare --band', True, [6, 10])]
    # 珍しい型まで＋★の帯 → pal_of(s, True, 帯)
    calls.clear()
    cli._apply_variants(bgd, blocks, mu, cli._variant_ranges({'ranges': [{'b0': 4, 'b1': 8, 'set': {'band': 1, 'rare': 1}}]}, 0, None), pal_of)
    assert calls == [(1, True, 1)]
    # ★の帯が無ければ前と同じ形・同じ呼び方
    assert cli._variant_ranges({'ranges': [{'b0': 0, 'b1': 4, 'set': {'rare': 1}}]}, 2, (4, 8)) == \
        [(0, 4, 0, '意思入れ', True), (4, 8, 2, '--variant')]


def test_band_report_lines(monkeypatch):
    """報告: 「- 区間の★の帯: 拍 a〜b は ★x〜y（…）」と節「★の帯を変えた区間」（使った型・★の中央値）。データベースが使えない時は効かない旨"""
    T, blocks, mu, seq, bgd, _ = _variant_setup()
    H = [theme.Theme([(3, 0, 1), (3, 1, 0)], [(0, 0, 1), (0, 1, 0)], 2, 'pair'),
         theme.Theme([(2, 0, 7), (3, 2, 5)], [(1, 0, 6), (0, 2, 4)], 2, 'pair')]
    lib = {'songs': 40, 'library': {'filters': {'stars': [6, 10]}}, 'hands': [],
           'pairs': [{'a': [list(s) for s in t.a], 'b': [list(s) for s in t.b], 'maps': 2, 'stars': 8.5} for t in H]}
    monkeypatch.setattr(library_use, 'export', lambda f: dict(lib, library={'filters': f}))
    monkeypatch.setattr(library_use, 'band_counts', lambda f: (0, {}))   # 比べる束はデータベースから数えない（その帯らしさは付かない）
    monkeypatch.setattr(theme, 'load_themes', lambda d, hand_min=None, pair_min=None, freq=None: list(H))
    a = SimpleNamespace(library=None)
    box = {'libs': {}, 'got': {}}
    g = cli._band_themes(a, {}, 1, False, box)
    assert g['stars'] == [6, 10] and not g['db_song'] and g['base'] == [0, 8] and len(g['themes']) == 2
    assert cli._band_themes(a, {}, 1, False, box) is g
    vr = cli._variant_ranges({'ranges': [{'b0': 0, 'b1': 8, 'set': {'band': 1}}]}, 0, None)
    pal_of = lambda s, rare=False, band=None: ({'x': H}, {'A': H}) if band is not None else ({'x': T}, seq)
    alt, rep = cli._apply_variants(bgd, blocks, mu, vr, pal_of)
    line = cli._band_line(vr, rep, box)[0]
    assert line.startswith('- 区間の★の帯: 拍 0〜8 は ★6〜10（★1段難しく・既定 ★〜8 から・曲 40・型 2・小節 2')
    box['pals'] = {'1': [{'x': H}]}
    rows = cli._band_lines(rep, alt, mu['bars'], T, box)
    assert rows[2].startswith('| 拍 0〜8 | ★1段難しく＝★6〜10 | 2 | ') and '★8.5' in rows[2] and rows[2].endswith('| 2 / 2 |')
    assert cli._band_line([], None, box) == []
    # データベースが使えない → None・効かない旨（library_use.Unavailable の字）

    def no_db(f):
        raise library_use.Unavailable('型のデータベースが使えない（ライブラリが無い）')
    monkeypatch.setattr(library_use, 'export', no_db)
    box2 = {'libs': {}, 'got': {}}
    assert cli._band_themes(a, {}, -1, False, box2) is None
    vr3 = cli._variant_ranges({'ranges': [{'b0': 0, 'b1': 8, 'set': {'band': -1}}]}, 0, None)
    _, rep3 = cli._apply_variants(bgd, blocks, mu, vr3, pal_of)
    out = cli._band_line(vr3, rep3, box2)
    assert len(out) == 1 and '効かない' in out[0] and 'ライブラリが無い' in out[0]


def test_compose_cli_takes_band(monkeypatch):
    """compose の --band（既定は無し）を受け取る"""
    got = []
    monkeypatch.setattr(cli, 'cmd_compose', lambda a: got.append(a))
    cli.main(['compose', 'x.nlmf', '--stems', 'y', '--form', '--style', '--only', '4,8', '--band', '+1'])
    cli.main(['compose', 'x.nlmf', '--stems', 'y', '--band=6,10'])
    cli.main(['compose', 'x.nlmf', '--stems', 'y'])
    assert cli._cli_band(got[0]) == 1 and cli._cli_band(got[1]) == [6, 10] and cli._cli_band(got[2]) is None


def test_candidates_pass_the_band(app, monkeypatch):
    """別の案「★の帯を変えて作る」: compose に --band=…（「-1」が引数の名前に見えないように 1 つで）も渡し、案と表に帯。
    これにすると返事に帯（画面が区間に「★の帯」も足す）。帯の無い案は前と同じ引数"""
    import json as js
    server, V, p = app
    got = []

    def fake_generate(p_, only=None, out=None, extra=(), kind='generate', **meta):
        got.append([str(x) for x in extra])
        return {'state': 'done', 'took': 0.1, 'report': '- 打点 4\n'}

    def fake_job(file, steps, kind='generate', **meta):
        job = {'id': 'j', 'log': '', 'state': 'running'}
        for _, fn in steps:
            fn(job)
        return job
    monkeypatch.setattr(server, 'start_generate', fake_generate)
    monkeypatch.setattr(server, 'start_job', fake_job)
    V.start_cands(p, [8, 16], n=2, band=-1)
    assert got == [['--variant', '1', '--band=-1'], ['--variant', '2', '--band=-1']]
    assert V._cand_meta(p)['band'] == -1 and all(c['band'] == -1 for c in V._cand_meta(p)['cands'])
    got.clear()
    V.start_cands(p, [8, 16], n=1, rare=True, band=[6, 10])
    assert got == [['--variant', '1', '--rare', '--band=6,10']]
    got.clear()
    V.start_cands(p, [8, 16], n=1, band='x')   # 使えない値は無し（前と同じ引数）
    assert got == [['--variant', '1']] and V._cand_meta(p)['band'] is None
    # これにする: 返事と履歴の版に帯
    V.drop_cands(p)
    from test_versions import _cands
    _cands(V, p)
    mp = V.cand_dir(p) / 'index.json'
    meta = js.loads(mp.read_text(encoding='utf-8'))
    meta['cands'][0]['band'] = [8, 12]
    mp.write_text(js.dumps(meta), encoding='utf-8')
    r = V.choose(p, 1)
    assert r['band'] == [8, 12] and '★8〜12' in r['version']['title'] and r['version']['cand']['band'] == [8, 12]


# ---- その帯らしさ（2026-10-26 利用者「帯を変えた時は、その帯らしい型を優先する」） ----
PA = [[2, 0, 1], [3, 1, 0]]         # どの帯にもよく出る型（の代わり）
PB = [[1, 0, 6], [3, 2, 5]]         # 帯を変えた先で特によく出る型（の代わり）
HC = [[1, 0, 1], [1, 2, 0], [2, 0, 1], [2, 2, 0]]   # 曲の設定の帯でよく出る片手の型（の代わり）


def _band_lib(stars=(6, 10)):
    return {'songs': 100, 'library': {'filters': dict(library_use.concrete(library_use.DEFAULT), stars=list(stars))},   # 設定の無い曲の帯の書き出し（新しい曲の既定の★を変えた物）
            'pairs': [{'a': PA, 'b': PA, 'maps': 20}, {'a': PB, 'b': PB, 'maps': 10}],
            'hands': [{'cycle': HC, 'maps': 4}]}


BASE_COUNTS = (200, {('pair', library_use._tup(PA), library_use._tup(PA)): 40, ('hand', library_use._tup(HC)): 30})


def test_lift_is_the_share_in_the_band_over_the_share_in_the_song_library():
    """その帯らしさ＝帯の中で型が出る曲の割合 ÷ 曲の設定のライブラリの中の割合（両方に LIFT_PRIOR 曲を足す）。
    同じ割合なら 1・帯にだけ出る型は 1 より大きい・曲の設定の帯で多い型は 1 より小さい"""
    lo = library_use.lift_of
    assert lo(20, 100, 40, 200, prior=0) == 1.0 and abs(lo(20, 100, 40, 200) - 1) < 0.1 and lo(40, 200, 40, 200) == 1.0
    assert lo(10, 100, 0, 200) > 3 and lo(4, 100, 30, 200) < 0.6
    assert lo(2, 100, 0, 200) < lo(10, 100, 0, 200)   # 少ない曲にしか出ない型は控えめ（足した曲の分）


def test_band_lift_marks_the_band_bundle(monkeypatch):
    """帯の書き出しの型ごとに lift を足し、library.band に印（比べた束の★・曲の数）。比べる束は頻度・難しさを外した曲の設定"""
    asked = []
    monkeypatch.setattr(library_use, 'band_counts', lambda f: asked.append(f) or BASE_COUNTS)
    lib = _band_lib()
    base = library_use.band_base({'sources': ['ranked'], 'stars': [0, 8], 'freq': '定番', 'hard': 'ふつう'})
    assert base == {'sources': ['ranked'], 'stars': [0, 8]} and library_use.band_base(None) == library_use.concrete(library_use.DEFAULT)
    library_use.band_lift(lib, base)
    pa, pb = lib['pairs']
    assert abs(pa['lift'] - 1) < 0.1 and pb['lift'] > 3 and lib['hands'][0]['lift'] < 0.6
    assert lib['library']['band'] == {'base': [0, 8], 'base_songs': 200, 'prior': library_use.LIFT_PRIOR}
    assert asked == [base]
    # 比べる束と同じ帯・数えられない時は何もしない
    d = library_use.band_base(None)   # 設定の無い曲＝新しい曲の既定（★〜8）と比べる
    for lib2, err in ((_band_lib((0, 8)), None), (_band_lib(), True)):
        if err:
            monkeypatch.setattr(library_use, 'band_counts', lambda f: (_ for _ in ()).throw(library_use.library_db.LibraryError('無い')))
        library_use.band_lift(lib2, d)
        assert 'band' not in lib2['library'] and all('lift' not in q for q in lib2['pairs'])


def test_export_band_counts_the_song_library_once(monkeypatch):
    """1回の作り直しの中で、比べる束（曲の設定）は帯がいくつあっても1回だけ数える"""
    asked = []
    monkeypatch.setattr(library_use, 'export', lambda f: dict(_band_lib(f['stars']), library={'filters': f}))
    monkeypatch.setattr(library_use, 'band_counts', lambda f: asked.append(f) or BASE_COUNTS)
    cache = {}
    a = library_use.export_band(None, 1, cache)
    b = library_use.export_band(None, -1, cache)
    assert len(asked) == 1 and a['library']['band']['base'] == [0, 8] and b['library']['band']
    assert a['pairs'][1]['lift'] > 1 and library_use.export_band(None, [6, 10], cache) is a


def test_themes_carry_lift_without_changing_what_is_the_same_theme():
    """theme.load_themes は lift を Theme に持たせる（無い型は None）。同じ型かどうかの比べには入れない"""
    ts = theme.load_themes(dict(_band_lib(), pairs=[dict(q, lift=v) for q, v in zip(_band_lib()['pairs'], (1.0, 3.2))]))
    assert [t.lift for t in ts] == [1.0, 3.2, None]
    assert ts[0] == theme.Theme(ts[0].a, ts[0].b, ts[0].maps, 'pair')


def test_fit_adds_lift_only_when_asked():
    """theme.fit: 狙いに lift（重み）がある時だけ、その帯らしさの点（log・±LIFT_CAP で止める）を引く。無ければ前と同じ値"""
    t0 = theme.Theme([tuple(s) for s in HC], [tuple(s) for s in HC], 10, 'sym')
    t1 = theme.Theme(t0.a, t0.b, 10, 'sym', 2.0)
    t9 = theme.Theme(t0.a, t0.b, 10, 'sym', 100.0)
    w = dict(theme.WANT['big'])
    assert theme.fit(t1, w, 0.15) == theme.fit(t0, w, 0.15)
    wl = dict(w, lift=1.0)
    assert abs(theme.fit(t1, wl, 0.15) - (theme.fit(t0, w, 0.15) - 0.6931)) < 1e-3
    assert abs(theme.fit(t9, wl, 0.15) - (theme.fit(t0, w, 0.15) - theme.LIFT_CAP)) < 1e-9
    assert theme.fit(t0, wl, 0.15) == theme.fit(t0, w, 0.15)


def _synthetic_themes(lift=None):
    """振り下ろしと振り上げが交互の4振りの型を並べた束（人の譜面ではない）。lift＝型の番号 → その帯らしさ"""
    out = []
    for i, (x0, x1, y1, d) in enumerate((x0, x1, y1, d) for x0 in range(4) for x1 in range(4) for y1 in (1, 2) for d in (1, 6)):
        a = [(x0, 0, d), (x1, y1, 0 if d == 1 else 5), (x1, 0, d), (x0, y1, 0 if d == 1 else 5)]
        out.append(theme.Theme(a, a, 3 + (i * 7) % 40, 'sym', lift(i) if lift else None))
    return out


def test_style_pick_prefers_band_like_themes_only_for_a_band_bundle():
    """style.pick: 型の出どころが★の帯を変えた書き出し（library.band の印）の時だけ、その帯らしい型を優先する。
    印が無い（曲全体のテーマ選び）なら、型に lift があっても前と同じ答え"""
    from test_form import _mu
    from automap import style
    bl = form.build(_mu(), [], 64)
    ons = {'vocal': [], 'kick': [], 'snare': []}
    keys = lambda r: [t.key() for ts in r[2].values() for t in ts]
    plain = style.pick(bl, ons, 120, _synthetic_themes(), k=3)
    lifted = _synthetic_themes(lambda i: 3.0 if i % 5 == 0 else 0.5)
    assert keys(style.pick(bl, ons, 120, lifted, k=3)) == keys(plain)
    assert keys(style.pick(bl, ons, 120, lifted, k=3, lib={'library': {'filters': {}}})) == keys(plain)
    band = {'library': {'filters': {'stars': [6, 10]}, 'band': {'base': [0, 8]}}}
    got = style.pick(bl, ons, 120, lifted, k=3, lib=band)
    lf = lambda r: sum(t.lift for ts in r[2].values() for t in ts) / sum(len(ts) for ts in r[2].values())
    plain_l = style.pick(bl, ons, 120, lifted, k=3)
    assert lf(got) > lf(plain_l) and lf(got) > 2.5
    assert style.band_lib(band) == {'base': [0, 8]} and style.band_lib(None) is None and style.band_lib({'songs': 3}) is None
