"""★の物差しの組（automap/rating_scale.py）と、それをまとめて入れ替える道具（tools/library_build/update_rating.py）"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from automap import config, njs, rating_scale as RS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools' / 'library_build'))
sys.path.insert(0, str(ROOT / 'tools' / 'dist'))


def _db(path, versions):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE info (k TEXT PRIMARY KEY, v TEXT)')
    con.execute('INSERT INTO info VALUES (?, ?)', ('approx_versions', json.dumps(versions)))
    con.commit()
    con.close()
    return path


def test_scale_name_is_upper_two_of_version():
    assert RS.of('4.1.0') == '4.1' and RS.of('4.1.3') == '4.1' and RS.of('0.2.0') == '0.2'
    assert RS.of(None) is None and RS.of('') is None and RS.of('4') is None


def test_problems_finds_each_part_out_of_step(tmp_path, monkeypatch):
    monkeypatch.setattr(RS, 'exe_version', lambda exe: '4.1.2')
    db = _db(tmp_path / 'a.sqlite', {'4.1.0': 400})
    assert RS.problems(exe='x.exe', db=db, scale='4.1') == []   # 版の 3 つ目（直しだけ）が違ってもよい
    assert len(RS.problems(exe='x.exe', db=db, scale='4.2')) == 2
    old = _db(tmp_path / 'b.sqlite', {'0.2.0': 400})
    assert '0.2' in RS.problems(db=old, scale='4.1')[0]
    mixed = _db(tmp_path / 'c.sqlite', {'4.1.0': 3, '0.2.0': 1})   # 測り直しが途中で混ざった
    assert len(RS.problems(db=mixed, scale='4.1')) == 1
    assert len(RS.problems(db=tmp_path / 'none.sqlite', scale='4.1')) == 1
    monkeypatch.setattr(RS, 'exe_version', lambda exe: None)
    assert len(RS.problems(exe='x.exe', scale='4.1')) == 1


def test_data_is_what_the_code_reads():
    """njs の式と★の帯の参考の値は rating_scale.json から＝道具が書き換えると一緒に変わる"""
    assert njs.COEF is RS.NJS_COEF and set(njs.COEF) >= {'stars', 'nps'}
    from automap import library_use as LU
    assert LU.NPS_REF is RS.NPS_REF
    assert [list(k) for k in sorted(RS.NPS_REF)] == [list(b) for b in LU.NPS_BANDS]


def test_write_scale_is_read_back(tmp_path):
    import update_rating as UR
    state = {'scale': '9.9', 'version': '9.9.1', 'bl_list_at': '2030-01-01', 'exe': 'x', 'njs': RS.NJS_COEF, 'nps_ref': {'0-4': 1.5, '4-6.5': 2.5},
             'bands': [0, 4, 6.5, 8, 10, 12, 99], 'moved': {'6': 6.5}, 'proposed': [0, 1, 2, 3, 4, 5, 99]}
    p = tmp_path / 'rating_scale.json'
    UR.write_scale(state, p)
    d = json.loads(p.read_text(encoding='utf-8'))
    assert d['scale'] == '9.9' and d['nlm_rating'] == '9.9.1' and d['nps_ref'] == {'0-4': 1.5, '4-6.5': 2.5} and d['bands'][2] == 6.5 and d['moved'] == {'6': 6.5}
    assert 'exe' not in d and 'proposed' not in d   # PC の場所を入れない
    assert b'\r' not in p.read_bytes()


def test_move_and_migrate_work(monkeypatch):
    """前の境目は今の境目へ・今の境目と境目でない値はそのまま・何度通しても同じ。ライブラリ・量の目安・展開の行・区間の指示のどれも"""
    monkeypatch.setattr(RS, 'MOVED', {4.0: 5, 6.0: 6.5, 8.0: 8.5})
    assert RS.move([0, 8]) == [0, 8.5] and RS.move([4, 8]) == [5, 8.5] and RS.move([6, 10]) == [6.5, 10] and RS.move([10, 99]) == [10, 99]
    assert RS.move([0, 8.5]) == [0, 8.5] and RS.move([5, 7.25]) == [5, 7.25]
    w = {'library': {'sources': ['ranked'], 'years': [2020, 2026], 'stars': [0, 8]}, 'amount': {'mode': 'band', 'stars': [6, 8]},
         'expand': {'targets': [{'diff': 'Hard', 'library': {'stars': [0, 4]}}]},
         'ranges': [{'b0': 4, 'b1': 8, 'set': {'band': [6, 10], 'qty': [4, 6]}}, {'b0': 8, 'b1': 12, 'set': {'band': 1}}], 'line': [{'b': 4, 'k': 6}]}
    m = RS.migrate_work(w)
    assert m['library']['stars'] == [0, 8.5] and m['amount']['stars'] == [6.5, 8.5] and m['expand']['targets'][0]['library']['stars'] == [0, 5]
    assert m['ranges'][0]['set'] == {'band': [6.5, 10], 'qty': [4, 6]} and m['ranges'][1]['set']['band'] == 1   # 段の数は読み替えない
    assert m['library']['years'] == [2020, 2026] and m['line'] == w['line']   # ★の帯でない数はそのまま
    assert w['library']['stars'] == [0, 8] and RS.migrate_work(m) == m   # 元は変えない・何度通しても同じ
    monkeypatch.setattr(RS, 'MOVED', {})
    assert RS.migrate_work(w) is w


def test_proposed_bands_keep_the_share():
    """前の境目と同じ割合の所を 0.5 刻みに。動かなければ今の境目のまま"""
    import update_rating as UR
    old = [i / 10 for i in range(1, 141)]
    assert UR.proposed_bands(old, old, (4, 6, 8, 10, 12)) == [0, 4, 6, 8, 10, 12, 99]
    assert UR.proposed_bands(old, [x + 1 for x in old], (4, 6, 8, 10, 12)) == [0, 5, 7, 9, 11, 13, 99]
    flat = UR.proposed_bands(old, [5.0] * 140, (4, 6, 8, 10, 12))   # 全部同じ★でも境目は上がり続ける
    assert flat == [0, 5, 5.5, 6, 6.5, 7, 99]
    assert UR.proposed_bands([], [], (4, 6)) == [0, 4, 6, 99]


def test_next_moved_chains_to_current_edges():
    """2 回動いても前の前の値から今の境目へ。今の境目にある値は読み替えない"""
    import update_rating as UR
    first = UR.next_moved([0, 4, 6, 8, 10, 12, 99], [0, 5, 6.5, 8.5, 10, 12, 99], {})
    assert first == {'4': 5, '6': 6.5, '8': 8.5}
    second = UR.next_moved([0, 5, 6.5, 8.5, 10, 12, 99], [0, 6, 7, 8.5, 10, 12, 99], first)
    assert second == {'4': 6, '5': 6, '6.5': 7, '8': 8.5}   # 6 は今の境目＝読み替えない
    assert UR.next_moved([0, 4, 6, 8, 10, 12, 99], [0, 4, 6, 8, 10, 12, 99], {}) == {}


def test_backup_keeps_the_old_list_and_ratings(tmp_path):
    """前の一覧・★の近似を版と日付の名前で控える。もう控えがあれば上書きしない（捨てない・取り直さない）"""
    import update_rating as UR
    for d in ('bl', 'rating'):
        (tmp_path / d).mkdir()
        (tmp_path / d / 'a.json').write_text('1', encoding='utf-8')
    info = {'approx_versions': {'4.1.0': 400, '4.0.0': 2}, 'bl_list_at': '2026-11-06T23:04:45+00:00'}
    got = UR.backup(tmp_path, info, log=lambda s: None)
    assert [p.name for p in got] == ['bl.4.1.0-20261106', 'rating.nlm-rating-4.1.0']
    assert (tmp_path / 'bl.4.1.0-20261106' / 'a.json').read_text(encoding='utf-8') == '1'
    (tmp_path / 'bl' / 'a.json').write_text('2', encoding='utf-8')
    assert UR.backup(tmp_path, info, log=lambda s: None) == []
    assert (tmp_path / 'bl.4.1.0-20261106' / 'a.json').read_text(encoding='utf-8') == '1'


def test_bands_arg():
    import update_rating as UR
    assert UR.bands_of('keep', [0, 1, 2, 3, 4, 5, 99]) == list(RS.BANDS)
    assert UR.bands_of('proposed', [0, 1, 2, 3, 4, 5, 99]) == [0, 1, 2, 3, 4, 5, 99]
    assert UR.bands_of('0,5,6.5,8.5,10,12,99', None) == [0, 5, 6.5, 8.5, 10, 12, 99]
    for bad in ('0,5,6', '1,5,6.5,8.5,10,12,99', '0,6.5,5,8.5,10,12,99', '0,5,6.5,8.5,10,12,50'):
        with pytest.raises(SystemExit):
            UR.bands_of(bad, None)


def test_edge_shift_and_star_report():
    import update_rating as UR
    old = {('h', str(i)): (i / 10, 3.0) for i in range(1, 141)}   # ★0.1〜14
    same = UR.edge_shift([v[0] for v in old.values()], [v[0] for v in old.values()])
    assert [e for e, _, _ in same] == list(UR.EDGES) and all(abs(v - e) < 0.11 for e, _, v in same)
    text = '\n'.join(UR.star_report(old, old))
    assert '案' not in text.split('## ★の帯の境目')[1].split('##')[0]   # 動いていなければ案を出さない
    assert 'またいだ難易度 0' in text and '⚠' not in text and '境目はそのまま' in text
    new = {k: (v[0] * 1.2, v[1]) for k, v in old.items()}   # 全部 2 割上がった
    text = '\n'.join(UR.star_report(old, new))
    assert '中央 1.200' in text and '⚠' in text


def test_new_and_lost_diffs_are_counted():
    import update_rating as UR
    old = {('a', 'Expert'): (5.0, 3.0), ('b', 'Expert'): (7.0, 4.0)}
    new = {('a', 'Expert'): (5.0, 3.0), ('c', 'Expert'): (9.0, 5.0)}
    assert '増えた 1・無くなった 1' in '\n'.join(UR.star_report(old, new))


def test_bundle_stops_on_mixed_set(tmp_path, monkeypatch):
    """★の物差しがそろっていない組の配布物は作らない"""
    import build_embed as BE
    lib = _db(tmp_path / 'library-dist.sqlite', {'0.0.1': 1})   # どの物差しとも違う
    rd = tmp_path / 'rating'
    rd.mkdir()
    (rd / 'nlm-rating.exe').write_bytes(b'')
    monkeypatch.setattr(RS, 'exe_version', lambda exe: RS.SCALE + '.0')
    out = tmp_path / 'out'
    out.mkdir()
    with pytest.raises(SystemExit, match='物差し'):
        BE.bundle_parts(out, lib, rd)
    assert not (out / 'data').exists()   # 入れる前に止まる
    good = _db(tmp_path / 'good.sqlite', {RS.SCALE + '.0': 1})
    assert len(BE.bundle_parts(out, good, rd)) == 2 and (out / 'data' / 'library-dist.sqlite').is_file() and (out / 'parts' / 'nlm-rating' / 'nlm-rating.exe').is_file()


def test_moved_keeps_old_settings_on_current_edges():
    """今の rating_scale.json の決まり: 7 つの境目が上がり続ける・moved の行き先は今の境目・moved の元は今の境目でない"""
    b = RS.BANDS
    assert len(b) == 7 and b[0] == 0 and b[-1] == 99 and all(x < y for x, y in zip(b, b[1:]))
    assert all(v in b and k not in b for k, v in RS.MOVED.items())


def test_load_work_and_settings_read_old_edges_as_current(tmp_path, monkeypatch):
    """前の物差しの境目で保存した作業ファイル・履歴は今の境目で読む＝境目が動いただけなら「設定を変えた」にしない（作り直しが前の譜面に寄せたまま）"""
    sys.path.insert(0, str(ROOT / 'app'))
    import server
    import versions
    monkeypatch.setattr(RS, 'MOVED', {8.0: 8.5})
    old = {'library': {'sources': ['ranked'], 'stars': [0, 8]}, 'ranges': [], 'line': []}
    p = tmp_path / 'a.nlmf'
    server.work_path(p).write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
    w = server.load_work(p)
    assert w['library']['stars'] == [0, 8.5]
    assert versions._settings(RS.migrate_work(old)) == versions._settings(w)
    assert versions._settings(old) != versions._settings(w)   # 読み替えないと「ライブラリを変えた」に見える


def test_screen_bands_come_from_the_scale():
    """画面の★の帯（/api/library/bands・ライブラリの窓）は rating_scale.json の境目から"""
    sys.path.insert(0, str(ROOT / 'app'))
    import library as AL
    from automap import library_use as LU
    r = AL.bands()
    assert r['steps'] == list(RS.BANDS) and r['default'] == LU.DEFAULT['stars'] == [0, RS.BANDS[3]] and r['scale'] == RS.SCALE
    assert r['choices'][0] == [0, RS.BANDS[2]] and r['choices'][-1] == [RS.BANDS[4], 99]
    assert [s for _, s in AL.BANDS[:5]] == r['choices'][:5] and AL.BANDS[-1] == ('全部', None)
    assert [list(x) for x in sorted(RS.NPS_REF)] == [list(x) for x in LU.NPS_BANDS]


def test_this_pc_set_is_in_step():
    """開発の PC の設定の exe・データベース・配布用のライブラリが今の物差し（1 つだけ替えた時にここで分かる）。無い PC では飛ぶ"""
    cfg = config.load()
    exe, db = cfg.get('nlm_rating_exe'), cfg.get('library_db')
    if not exe or not db or not Path(exe).is_file() or not Path(db).is_file():
        pytest.skip('開発の PC の設定が無い')
    dist = Path(db).with_name('library-dist.sqlite')
    assert RS.problems(exe=exe, db=db) == []
    assert not dist.is_file() or RS.problems(db=dist) == []
