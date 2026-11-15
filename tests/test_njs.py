import pytest

from automap import njs

pytestmark = pytest.mark.usefixtures('pinned_scale')


def test_suggest_from_stars_and_bpm():
    v, how = njs.suggest('ExpertPlus', 120, stars=4.92)
    assert v == 16.0 and '★4.92' in how   # 8.57 + 0.538×4.92 + 0.0117×120 + 3.61 = 16.23 → 0.5 きざみ
    assert njs.suggest('Hard', 120, stars=3.49)[0] == 14.0
    assert njs.suggest('Easy', 120, stars=2.0)[0] < njs.suggest('Normal', 120, stars=2.0)[0] < njs.suggest('Hard', 120, stars=2.0)[0]
    assert njs.suggest('Expert', 180, stars=5)[0] > njs.suggest('Expert', 120, stars=5)[0]   # 速い曲ほど速い
    assert njs.suggest('Expert+', 120, stars=4.92, offset=1)[0] == 17.0   # 好みのずらし
    assert njs.suggest('ExpertPlus', 120, stars=99)[0] == njs.RANGE[1]
    v, how = njs.suggest('Hard', 120, nps=3.0)   # ★が無い時は1秒のノーツ
    assert v is not None and '1秒のノーツ' in how
    assert njs.suggest('Hard', 120)[0] is None


def test_apply_keeps_user_value():
    p = {'njsCfg': {}}
    assert njs.apply(p, 'hardstandard.dat', 14.0) == ('wrote', 14.0)
    assert p['njsCfg']['hardstandard.dat'] == {'njs': 14.0, 'offset': 0, 'auto': 14.0}
    assert njs.apply(p, 'hardstandard.dat', 14.5) == ('same', 14.0)   # 0.5 以内は前のまま
    assert njs.apply(p, 'hardstandard.dat', 15.5)[0] == 'wrote' and p['njsCfg']['hardstandard.dat']['njs'] == 15.5
    p['njsCfg']['hardstandard.dat']['njs'] = 13   # NLM で利用者が直した（auto は残る）
    assert njs.apply(p, 'hardstandard.dat', 16.0) == ('kept', 13)
    p['njsCfg']['expertstandard.dat'] = {'njs': 17, 'offset': 0.5}   # NLM で決めた（auto の印が無い）
    assert njs.apply(p, 'expertstandard.dat', 15.0) == ('kept', 17)
    q = {}
    assert njs.apply(q, 'easystandard.dat', 12.0)[0] == 'wrote' and q['njsCfg']['easystandard.dat']['offset'] == 0
    r = {'njsCfg': {'easystandard.dat': {'offset': 0.25}}}   # NJS は無くオフセットだけ＝書く・オフセットは残す
    assert njs.apply(r, 'easystandard.dat', 12.0)[0] == 'wrote' and r['njsCfg']['easystandard.dat']['offset'] == 0.25


def test_setting_offset_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr(njs, 'CONFIG', tmp_path / 'none.json')
    monkeypatch.delenv('AUTOMAP_NJS_OFFSET', raising=False)
    assert njs.setting() == (True, 0.0)
    (tmp_path / 'c.json').write_text('{"njs_offset": -1, "njs_auto": false}', encoding='utf-8')
    monkeypatch.setattr(njs, 'CONFIG', tmp_path / 'c.json')
    assert njs.setting() == (False, -1.0)
    monkeypatch.setenv('AUTOMAP_NJS_OFFSET', '0.5')
    assert njs.setting() == (False, 0.5)


# ---- 見え始める距離（JD）とオフセット（2026-11-10・njs.fix_jd） ----

def test_game_halves_the_jump_at_the_threshold():
    """ゲームの決まり: 見え始める所は 4 拍前から数え、18m を超える間は半分に。BPM 101（ストロボ）は NJS 15.15 が 2 拍と 1 拍の境目＝
    オフセット 0 のままだと 15.1 で 35.9m・15.2 で 18.1m に跳ぶ（3D の見え方は正しかった）"""
    assert njs.half_beats(15.1, 101) == 2.0 and njs.half_beats(15.2, 101) == 1.0
    assert round(njs.jd_of(15.1, 0, 101)[0], 1) == 35.9 and round(njs.jd_of(15.2, 0, 101)[0], 1) == 18.1
    assert njs.jd_of(16, -9, 120)[1] == 0.25 * 0.5   # 半分の拍は 0.25 拍より短くしない


def test_offset_keeps_the_target_across_the_threshold():
    """狙いの JD になるオフセット: 境目の両側で同じ JD（0.001 拍に丸めた分だけ）。ストロボの Hard は 34.5m → 19.7m"""
    for n in (15.1, 15.2):
        o = njs.offset_for('Expert', n, 101)
        assert abs(njs.jd_of(n, o, 101)[0] - njs.JD_TARGET['Expert']) < 0.02 and o == round(o, 3)
    assert njs.offset_for('Expert', 15.1, 101) < -0.9 and njs.offset_for('Expert', 15.2, 101) > 0   # 下は縮める・上は伸ばす
    assert abs(njs.jd_of(14.5, njs.offset_for('Hard', 14.5, 101), 101)[0] - 19.7) < 0.02


def test_target_stays_inside_the_nlm_warnings():
    """狙いの JD は NLM の譜面チェックの警告が出ない範囲（18m 以上・ちょうどよい上限以下・反応 0.42 秒以上）に収める"""
    for d in ('Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus'):
        for n in (8, 10, 12, 14, 16, 18, 20, 22, 24):
            for bpm in (60, 101, 128, 175, 240, 320):
                jd, rt = njs.jd_of(n, njs.offset_for(d, n, bpm), bpm)
                assert jd >= 18 and rt >= 0.42 and jd <= njs.opt_hi(n), (d, n, bpm, jd, rt)
    assert njs.target_jd('Hard', 16) == njs.JD_TARGET['Hard']   # ふつうは表のまま
    assert njs.target_jd('ExpertPlus', 24) > njs.JD_TARGET['ExpertPlus']   # 速い NJS は反応時間を守って伸ばす


def test_fix_jd_marks_and_keeps_the_nlm_offset():
    """まだ誰も決めていない（印が無く 0）＝書く（auto_offset の印も）・アプリの値＝NJS が変わったら合わせ直す・NLM で決めた値＝触らない"""
    p = {'bpm': 101, 'njsCfg': {'hardstandard.dat': {'njs': 14.5, 'offset': 0, 'auto': 14.5}}}
    E = lambda: p['njsCfg']['hardstandard.dat']   # fix_jd は項目を新しい辞書に置き換える
    r = njs.fix_jd(p, 'hardstandard.dat')
    assert r['state'] == 'wrote' and E()['offset'] == E()['auto_offset'] == njs.offset_for('Hard', 14.5, 101) and abs(r['jd'] - 19.7) < 0.02
    assert njs.fix_jd(p, 'hardstandard.dat')['state'] == 'same'
    E()['njs'] = 16   # NLM で NJS を直した（オフセットはアプリの値のまま）＝その NJS で狙いの JD に
    assert njs.fix_jd(p, 'hardstandard.dat')['state'] == 'wrote' and E()['offset'] == njs.offset_for('Hard', 16, 101)
    E()['offset'] = -0.5   # NLM でオフセットを直した＝触らない
    r = njs.fix_jd(p, 'hardstandard.dat')
    assert r['state'] == 'kept' and E()['offset'] == -0.5 and 'NLM で決めたオフセット −0.500 拍のまま' in njs.jd_text(r)
    q = {'bpm': 101, 'njsCfg': {'hardstandard.dat': {'njs': 14.5, 'offset': 0.25}}}   # 印の無い 0 でない値＝NLM で決めた
    assert njs.fix_jd(q, 'hardstandard.dat')['state'] == 'kept' and q['njsCfg']['hardstandard.dat']['offset'] == 0.25
    assert njs.fix_jd({'njsCfg': {'hardstandard.dat': {'njs': 14.5}}}, 'hardstandard.dat')['state'] == 'none'   # BPM が無い
    assert njs.fix_jd({'bpm': 101, 'njsCfg': {'x.dat': {'njs': 14.5}}}, 'x.dat')['state'] == 'none'   # 知らない難易度


def test_put_and_apply_write_the_offset():
    """NJS を書くとその NJS で狙いの JD のオフセットも（BPM のある譜面）。NJS が NLM の値で書かない時も、オフセットは整える"""
    p = {'bpm': 101, 'njsCfg': {}}
    assert njs.apply(p, 'expertstandard.dat', 15.5) == ('wrote', 15.5)
    assert p['njsCfg']['expertstandard.dat']['offset'] == njs.offset_for('Expert', 15.5, 101)
    p['njsCfg']['hardstandard.dat'] = {'njs': 13, 'offset': 0, 'auto': 14.5}   # NJS は NLM で決めた
    assert njs.apply(p, 'hardstandard.dat', 14.5) == ('kept', 13) and p['njsCfg']['hardstandard.dat']['offset'] == njs.offset_for('Hard', 13, 101)
    q = njs.with_njs(p, 'expertstandard.dat', 15.0)   # ★をその速さで測る写しも書いた時と同じオフセット
    assert q['njsCfg']['expertstandard.dat']['offset'] == njs.offset_for('Expert', 15.0, 101)
    assert p['njsCfg']['expertstandard.dat']['njs'] == 15.5


def test_fix_all_only_touches_the_apps_difficulties():
    """曲を開いた時・基準を作り直した時: アプリが NJS を書いた難易度（auto の印）だけ。利用者が NLM で作った難易度は触らない"""
    p = {'bpm': 101, 'difficulties': {'easystandard.dat': {}, 'hardstandard.dat': {}, 'expertstandard.dat': {}, 'normalstandard.dat': {}},
         'njsCfg': {'easystandard.dat': {'njs': 12.0, 'offset': 0, 'auto': 12.0},
                    'hardstandard.dat': {'njs': 14.5, 'offset': 0, 'auto': 14.5},
                    'expertstandard.dat': {'njs': 15.5, 'offset': 0}}}   # Expert は NLM で作った（auto が無い）・Normal は項目が無い
    got = njs.fix_all(p, skip={'hardstandard.dat'})
    assert [k for k, _, _ in got] == ['easystandard.dat'] and round(got[0][1], 1) == 28.5 and abs(got[0][2]['jd'] - 20.7) < 0.02
    assert p['njsCfg']['expertstandard.dat'] == {'njs': 15.5, 'offset': 0} and p['njsCfg']['hardstandard.dat']['offset'] == 0
    assert njs.fix_all(p, skip={'hardstandard.dat'}) == []   # 2 回目は書かない
