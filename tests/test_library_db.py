"""型のライブラリ（tools/library_build/・automap/library_db.py）: 今の tools/library_themes.py と同じ型・同じ数が出ること（docs/ライブラリ仕様.md 7 節の 3）"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from automap import library_db as L

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools' / 'library_build'))
import build_db  # noqa: E402
import common as C  # noqa: E402
import fetch  # noqa: E402

MIRROR = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}
A = [(2, 0, 1), (2, 1, 0)]                          # 右手の形（x, y, 向き）
B = [(3, 0, 1), (3, 2, 0), (2, 0, 7), (2, 1, 4)]
CC = [(1, 0, 6), (3, 1, 5)]
FILL = [(1, 0, 1), (2, 2, 0), (3, 0, 7), (0, 1, 4), (2, 0, 6), (1, 2, 5), (3, 1, 1), (0, 0, 0)]


def _hand(cyc, c, reps, start, step=1.0):
    out = []
    for k in range(reps * len(cyc)):
        x, y, d = cyc[k % len(cyc)]
        if c == 0:
            x, d = 3 - x, MIRROR[d]
        out.append((start + k * step, c, x, y, d))
    return out


def _song(r, l, start=4.0, fill=True):
    """右手 r・左手 l の [(型, 回数)] を続けて置き、最後にくり返さない振りを足す"""
    notes, tr, tl = [], start, start + 0.5
    for cyc, n in r:
        notes += _hand(cyc, 1, n, tr)
        tr += n * len(cyc)
    for cyc, n in l:
        notes += _hand(cyc, 0, n, tl)
        tl += n * len(cyc)
    if fill:
        notes += _hand(FILL, 1, 1, tr + 2) + _hand(FILL[::-1], 0, 1, tr + 2.5)
    return notes


def _v2(notes):
    return {'_version': '2.0.0', '_notes': [{'_time': b, '_lineIndex': x, '_lineLayer': y, '_type': c, '_cutDirection': d}
                                            for b, c, x, y, d in notes], '_obstacles': [], '_events': []}


def _v3(notes, bpm_events=1):
    return {'version': '3.0.0', 'colorNotes': [{'b': b, 'x': x, 'y': y, 'c': c, 'd': d, 'a': 0} for b, c, x, y, d in notes],
            'bombNotes': [], 'obstacles': [], 'sliders': [], 'burstSliders': [],
            'bpmEvents': [{'b': i * 16, 'm': 120 + i} for i in range(bpm_events)]}


def _map(folder, diffs, bpm=120, name='Test', author='Maker', v4=False):
    """diffs: [(特性, 難易度の名前, 中身（dict か文字列）, 要るmod)]"""
    folder.mkdir(parents=True)
    if v4:
        (folder / 'Info.dat').write_text(json.dumps({'version': '4.0.0', 'difficultyBeatmaps': []}), encoding='utf-8')
        return
    sets = {}
    for i, (ch, rank, body, req) in enumerate(diffs):
        fn = f'{rank}{ch}{i}.dat'
        (folder / fn).write_text(body if isinstance(body, str) else json.dumps(body), encoding='utf-8')
        bm = {'_difficulty': rank, '_beatmapFilename': fn, '_noteJumpMovementSpeed': 16}
        if req:
            bm['_customData'] = {'_requirements': req}
        sets.setdefault(ch, []).append(bm)
    info = {'_version': '2.0.0', '_songName': name, '_levelAuthorName': author, '_beatsPerMinute': bpm,
            '_difficultyBeatmapSets': [{'_beatmapCharacteristicName': ch, '_difficultyBeatmaps': bms} for ch, bms in sets.items()]}
    (folder / 'Info.dat').write_text(json.dumps(info), encoding='utf-8')
    (folder / 'song.egg').write_bytes(b'')


def _library(tmp):
    """作り物の手元の譜面（library_themes.py の決まりを一通り通る）"""
    cl = tmp / 'CustomLevels'
    S = 'Standard'
    _map(cl / 'a1 (One - Alice)', [(S, 'ExpertPlus', _v2(_song([(A, 10), (B, 4)], [(CC, 10), (B, 4)])), None),
                                   (S, 'Expert', _v2(_song([(CC, 10)], [(A, 10)])), None),
                                   (S, 'Hard', _v2(_song([(A, 6)], [(A, 6)])), None)], author='Alice')
    shutil.copytree(cl / 'a1 (One - Alice)', cl / 'a1 (One - Alice) copy')          # 同じ譜面の複製は2曲と数える
    _map(cl / 'b2 (Two - Bob)', [(S, 'ExpertPlus', _v3(_song([(A, 10), (CC, 5)], [(CC, 10), (A, 5)])), None)], bpm=150, author='Bob')
    _map(cl / 'c3 (BPM - Carol)', [(S, 'ExpertPlus', _v3(_song([(A, 10)], [(CC, 10)]), bpm_events=2), None),    # BPM が変わる＝除く
                                   (S, 'Expert', _v2(_song([(B, 6)], [(B, 6)])), None)], author='Carol')
    _map(cl / 'd4 (Noodle - Dan)', [(S, 'ExpertPlus', _v2(_song([(A, 10)], [(CC, 10)])), ['Noodle Extensions']),
                                    (S, 'Hard', _v2(_song([(B, 6)], [(B, 6)])), None)])
    _map(cl / 'e5 (Broken - Eve)', [(S, 'Expert', _v2(_song([(A, 10)], [(CC, 10)])), None),
                                    (S, 'ExpertPlus', '{"_notes": [', None)])                        # 読めない＝曲ごと除く
    _map(cl / 'f6 (V4 - Fay)', [], v4=True)
    _map(cl / 'g7 (Short - Gus)', [(S, 'ExpertPlus', _v2(_song([(A, 3)], [(CC, 3)], fill=False)), None)])  # 50 未満
    _map(cl / 'h8 (One saber - Hal)', [('OneSaber', 'ExpertPlus', _v2(_song([(A, 10)], [(CC, 10)])), None)])
    ns = _song([(B, 6), (A, 8)], [(B, 6), (CC, 8)])
    ns = [(b, c, float(x), y, d) for b, c, x, y, d in ns[:30]] + [(ns[30][0], ns[30][1], ns[30][2], ns[30][3], 8)] + ns[31:]
    _map(cl / 'i9 (Float - Ivy)', [(S, 'ExpertPlus', _v2(ns), None)], bpm=97.5)
    _map(cl / 'auto-own', [(S, 'ExpertPlus', _v2(_song([(B, 9)], [(B, 9)])), None)], author='')     # 自分で書き出した物（OWN で除く）
    _map(cl / 'auto-keep', [(S, 'ExpertPlus', _v2(_song([(CC, 9)], [(CC, 9)])), None)], author='Me')  # 「!」で除かない
    (cl / 'not-a-folder.txt').write_text('x')
    return cl


OWN = ['auto-*', '!auto-keep']


def _themes_now(cl, out):
    """今の作り方（tools/library_themes.py）の結果"""
    subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'library_themes.py'), str(cl), str(out)], check=True,
                   capture_output=True)
    return json.loads(out.read_text(encoding='utf-8'))


HCORE = ('cycle', 'cells', 'move', 'row', 'diag', 'width', 'maps', 'runs', 'gap', 'sec')
PCORE = ('a', 'b', 'shape_a', 'shape_b', 'maps', 'runs', 'gap', 'sec')


def _core(d):
    return {'songs': d['songs'], 'ranks': d['ranks'], 'hands': [{k: h[k] for k in HCORE} for h in d['hands']],
            'pairs': [{k: p[k] for k in PCORE} for p in d['pairs']]}


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('lib')
    cl = _library(tmp)
    raw = tmp / 'raw'
    raw.mkdir()
    fetch.cmd_local(SimpleNamespace(local=str(cl)), raw)
    db = tmp / 'library.sqlite'
    build_db.build(raw, db, jobs=1, log=lambda *a: None, own_patterns=OWN, hints={})
    return SimpleNamespace(tmp=tmp, cl=cl, raw=raw, db=db)


def test_same_as_library_themes(lib):
    """手元の譜面だけ（Expert／Expert+）で書き出した型は、今の library_themes.py と同じ型・同じ数・同じ順"""
    now = _themes_now(lib.cl, lib.tmp / 'themes.json')
    out = L.export_themes({'sources': ['local'], 'include_own': True}, db=lib.db)
    assert now['songs'] == 7 and now['hands'] and now['pairs']   # a1・その複製・b2・c3（Expert）・i9・auto-own・auto-keep
    assert _core(out) == now


def test_out_file_reads_with_load_themes(lib):
    """書いたファイルは load_themes で読める（足した項目は無視される）・tools/library_themes.py の形と同じ型になる"""
    from automap import theme
    p = lib.tmp / 'export.json'
    out = L.export_themes({'sources': ['local'], 'include_own': True}, out_path=p, db=lib.db)
    assert json.loads(p.read_text(encoding='utf-8'))['hands'] == out['hands']
    now = _themes_now(lib.cl, lib.tmp / 'themes2.json')
    assert [t.key() for t in theme.load_themes(json.loads(p.read_text(encoding='utf-8')))] == [t.key() for t in theme.load_themes(now)]
    h = out['hands'][0]
    assert h['freq'] in L.FREQ and h['hard']['class'] in L.HARD and h['diffs'] >= h['maps']
    assert out['once'] and {'seq', 'maps', 'freq', 'hard'} <= set(out['once'][0])


def _ranked(lib):
    """作り物の BeatLeader・BeatSaver の情報（a1 は 2019 年・b2 は 2021 年のランク譜面）と、取ってきた譜面 k9"""
    raw = lib.raw / 'filters'
    if raw.exists():
        return raw
    shutil.copytree(lib.raw, raw)
    (raw / 'maps').mkdir()
    _map(raw / 'maps' / 'k9.00000000 (Raw - Kim)', [('Standard', 'ExpertPlus', _v2(_song([(B, 8)], [(B, 8)])), None)], author='Kim')
    ha = C.bs_hash(lib.cl / 'a1 (One - Alice)')[0]
    hb = C.bs_hash(lib.cl / 'b2 (Two - Bob)')[0]
    hk = C.bs_hash(raw / 'maps' / 'k9.00000000 (Raw - Kim)')[0]
    lbs = {ha: [('Expert', 3.0), ('ExpertPlus', 5.0)], hb: [('ExpertPlus', 7.0)], hk: [('ExpertPlus', 11.0)]}
    C.write_json(raw / 'bl' / '_ranked.json', {'hashes': {h: [['Standard', d, s, 0] for d, s in v] for h, v in lbs.items()}})
    for h, v in lbs.items():
        C.write_json(raw / 'bl' / f'{h}.json', {'hash': h, 'leaderboards': [
            {'difficulty': {'modeName': 'Standard', 'difficultyName': d, 'stars': s, 'passRating': s / 2, 'techRating': s / 3,
                            'accRating': s, 'rankedTime': 1}} for d, s in v]})
    C.write_json(raw / 'maps_index.json', {hk: {'folder': 'k9.00000000 (Raw - Kim)', 'key': 'k9'}})
    C.write_json(raw / 'meta' / '_hashes.json', {ha: {'key': 'a1'}, hb: {'key': 'b2'}, hk: {'key': 'k9'}})
    for k, up, who in (('a1', '2019-05-01T00:00:00Z', 'Alice'), ('b2', '2021-03-01T00:00:00Z', 'Bob'), ('k9', '2024-01-01T00:00:00Z', 'Kim')):
        C.write_json(raw / 'meta' / f'{k}.json', {'id': k, 'uploaded': up, 'uploader': {'name': who}, 'metadata': {'levelAuthorName': who}})
    build_db.build(raw, raw / 'library.sqlite', jobs=1, log=lambda *a: None, own_patterns=OWN, hints={})
    return raw


def test_filters(lib):
    """出どころ・★・年・作者で絞る（ランクは BeatLeader のランクの難易度だけ・同じ版は1つ・手元と両方なら手元の全部＋取った物）"""
    db = _ranked(lib) / 'library.sqlite'
    ex = lambda **f: L.export_themes(f, db=db)   # noqa: E731
    assert ex(sources=['local'])['songs'] == 6                   # 自分で書き出した auto-own は既定で除く
    assert ex(sources=['local'], include_own=True)['songs'] == 7
    assert ex(sources=['ranked'])['songs'] == 3                  # a1（複製は1つ）・b2・k9
    assert ex()['songs'] == 7                                    # 手元 6＋取った k9
    assert ex(sources=['ranked'], years=[2020, 2026])['songs'] == 2
    assert ex(sources=['ranked'], stars=[6, 12])['songs'] == 2
    assert ex(sources=['ranked'], stars=[4, 6], diffs=['Expert'])['songs'] == 0
    assert ex(sources=['ranked'], stars=[2, 4], diffs=['Expert'])['songs'] == 1
    assert ex(mappers=['bob'])['songs'] == 1
    assert ex(exclude_mappers=['alice', 'bob'])['songs'] == 4   # c3・i9・auto-keep・k9（BeatSaver の情報が無い手元の譜面は Info の作者で見る）
    assert ex(on_beatsaver=True)['songs'] == 4                   # a1 とその複製・b2・k9
    common = ex(freq='定番')
    assert all(h['freq'] == '定番' for h in common['hands'] + common['pairs'])
    easy = ex(hard='やさしい')
    assert all(h['hard']['class'] == 'やさしい' for h in easy['hands'])
    st = L.diff_stats({'sources': ['ranked']}, db=db)
    assert st['songs'] == 3 and st['all']['nps_q1_med_q3'] and set(st['ranks']) == {'Expert', 'ExpertPlus'}


def test_version_check(lib, tmp_path):
    """合わない版のデータベースは分かるように止める"""
    p = tmp_path / 'old.sqlite'
    shutil.copy(lib.db, p)
    con = sqlite3.connect(p)
    con.execute("UPDATE info SET v = '0' WHERE k = 'extract_version'")
    con.commit()
    con.close()
    with pytest.raises(L.LibraryError, match='版が合わない'):
        L.open_db(p)
    with pytest.raises(L.LibraryError, match='無い'):
        L.open_db(tmp_path / 'none.sqlite')


def test_dist_same_answers_without_maps(lib, tmp_path):
    """配布用のライブラリ（make_dist.py）: ランクの絞り込みの答えが元と同じ・譜面に戻せる物と名前・場所は入っていない"""
    import make_dist
    src = _ranked(lib) / 'library.sqlite'
    out = tmp_path / 'library-dist.sqlite'
    make_dist.make(src, out, log=lambda *a: None)
    fs = [{'sources': ['ranked']}, {'sources': ['ranked'], 'years': [2020, 2026]}, {'sources': ['ranked'], 'stars': [6, 12], 'freq': '珍しい'},
          {'sources': ['ranked'], 'diffs': ['Expert'], 'hard': 'ふつう'}]
    assert make_dist.check(src, out, fs, fs[:2], log=lambda *a: None) == []
    assert L.export_themes({'sources': ['ranked']}, db=out)['songs'] == 3      # a1（複製は1つ）・b2・k9
    assert L.export_themes({}, db=out)['songs'] == 3                          # 手元の譜面は入っていない
    assert L.export_themes({'sources': ['ranked'], 'mappers': ['bob']}, db=out)['songs'] == 0   # 作者で絞るのは効かない
    con = sqlite3.connect(out)
    q = lambda s: con.execute(s).fetchone()[0]   # noqa: E731
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert 'swings' not in tables and q('SELECT COUNT(*) FROM grams') > 0
    assert q("SELECT COUNT(*) FROM maps WHERE song IS NOT NULL OR sub IS NOT NULL OR artist IS NOT NULL OR level_author IS NOT NULL "
             "OR folder IS NOT NULL OR key IS NOT NULL OR uploaded IS NOT NULL OR mappers != '[]' OR place != 'ranked' OR hash NOT LIKE 'm%'") == 0
    assert q('SELECT COUNT(*) FROM occurrences WHERE spans IS NOT NULL') == 0 and q('SELECT COUNT(*) FROM once_occ WHERE beats IS NOT NULL') == 0
    assert q('SELECT COUNT(*) FROM diffs WHERE filename IS NOT NULL OR xerr IS NOT NULL') == 0
    info = L.info_of(con)
    con.close()
    assert not {'raw_root', 'local_root', 'own_patterns'} & set(info) and info['dist']['version'] == make_dist.DIST_VERSION
    blob = out.read_bytes()
    for s in ('Alice', 'Raw - Kim', 'One - Alice', str(lib.tmp)):
        assert s.encode('utf-8') not in blob
    with pytest.raises(SystemExit, match='swings'):
        make_dist.make(out, tmp_path / 'again.sqlite', log=lambda *a: None)    # 配布用からは作れない
    assert not {'own_maps', 'own_read', 'own_by'} & set(info)                 # 自分の書き出しの一覧（フォルダ名）も入れない


# ---- 自分（アプリ・NLM）で書き出した手元の譜面の見分け（2026-11-09） ----

def _mark(folder, ver='0.2.0', last=None):
    """Info.dat に ANP の印（bs_export.put_mark と同じ形）を入れる"""
    from automap import bs_export as BX
    p = folder / 'Info.dat'
    info = BX.put_mark(json.loads(p.read_text(encoding='utf-8')), ver)
    if last:
        info['_customData']['_editors']['_lastEditedBy'] = last
    p.write_text(json.dumps(info), encoding='utf-8')


def _own_env(tmp):
    """作り物の手元の譜面・作業の場所（out/）・プレイリストの場所。見分けごとに 1 つずつ当たる譜面と、当たらない人の譜面"""
    cl = tmp / 'CustomLevels'
    S = 'Standard'
    song = lambda: [(S, 'ExpertPlus', _v2(_song([(A, 10)], [(CC, 10)])), None)]   # noqa: E731
    for name, author in (('h1 (Human - Hana)', 'Hana'), ('Oz-Hand', 'Oz-Co2'), ('marked', 'Oz-Co2'), ('marked-chro', 'X'),
                         ('listed', 'Oz-Co2'), ('listed-hash', ''), ('worked', 'Oz-Co2'), ('exported', ''), ('auto-name', ''),
                         ('auto-keep', 'Oz-Co2')):
        _map(cl / name, song(), name=name, author=author)   # 曲名を変えて hash を別々に
    _mark(cl / 'marked')
    _mark(cl / 'marked-chro', last='ChroMapper')     # ほかのエディタで直した後も ANP の項目が残る
    _mark(cl / 'auto-keep')                          # 「!」の型は印があっても除かない
    out = tmp / 'out'
    (out / '.history' / 'x').mkdir(parents=True)
    (out / '.export').mkdir()
    (out / 'song.intent-s1.nlmf').write_text(json.dumps({'format': 'nlmf', 'version': 2, 'graph': {'out': {'folderName': 'Worked'}},
                                                        'infoGraph': {'outs': {'o1': {'folderName': 'worked'}}}}), encoding='utf-8')
    (out / '.history' / 'x' / 'old.nlmf').write_text('{"graph":{"out":{"folderName":"auto-keep"}}}', encoding='utf-8')
    (out / 'song.notes.txt').write_text('"folderName": "h1 (Human - Hana)"', encoding='utf-8')   # .nlmf でない物は見ない
    (out / '.export' / 'song.intent-s1.nlmf.json').write_text(json.dumps({'folder': 'exported', 'hash': 'zz'}), encoding='utf-8')
    pls = tmp / 'Playlists'
    pls.mkdir()
    hh = C.bs_hash(cl / 'listed-hash')[0]
    (pls / 'AutoNotePlotter.bplist').write_text(json.dumps({'playlistTitle': 'Auto Note Plotter', 'songs': [
        {'hash': 'AB' * 20, 'customData': {'anpFolder': 'listed'}},
        {'hash': hh.upper(), 'customData': {'anpFolder': 'renamed-later'}}]}), encoding='utf-8')
    (pls / 'other.bplist').write_text(json.dumps({'songs': [{'hash': C.bs_hash(cl / 'h1 (Human - Hana)')[0]}]}), encoding='utf-8')  # ANP の行でない
    (pls / 'broken.bplist').write_text('{', encoding='utf-8')
    return cl, out, pls


OWN2 = ['auto-*', '!auto-keep']
WANT_OWN = {'marked': ['mark'], 'marked-chro': ['mark'], 'listed': ['playlist'], 'listed-hash': ['playlist'], 'worked': ['work'],
            'exported': ['export'], 'auto-name': ['name']}


def test_own_hints_and_build(tmp_path):
    """Info.dat の印・プレイリストの ANP の行（フォルダ名と hash）・作業の場所の .nlmf の書き出すフォルダ名・書き出しの記録・名前の型の
    どれかで自分の物。「!」の型（利用者が手で打った譜面）は何が当たっても人の譜面。作者名（Oz-Co2）では決めない"""
    cl, out, pls = _own_env(tmp_path)
    hints = build_db.own_hints({}, out_dir=out, playlist_dirs=[pls, tmp_path / 'none'])
    assert hints['folders']['worked'] == ['work'] and hints['folders']['auto-keep'] == ['work'] and 'h1 (human - hana)' not in hints['folders']
    assert hints['folders']['exported'] == ['export'] and hints['folders']['listed'] == ['playlist']
    assert hints['hashes'][('AB' * 20).lower()] == ['playlist'] and hints['read']['work'] == str(out)
    raw = tmp_path / 'raw'
    raw.mkdir()
    fetch.cmd_local(SimpleNamespace(local=str(cl)), raw)
    db = raw / 'library.sqlite'
    info = build_db.build(raw, db, jobs=1, log=lambda *a: None, own_patterns=OWN2, hints=hints)
    con = sqlite3.connect(db)
    own = dict(con.execute('SELECT folder, own FROM maps').fetchall())
    con.close()
    assert {f for f, o in own.items() if o} == set(WANT_OWN)
    assert {f: rs for f, rs in info['own_maps']} == WANT_OWN and info['own'] == len(WANT_OWN)
    assert info['own_by'] == {'mark': 2, 'playlist': 2, 'work': 1, 'export': 1, 'name': 1}
    assert L.export_themes({'sources': ['local']}, db=db)['songs'] == 3                    # h1・Oz-Hand・auto-keep
    assert L.export_themes({'sources': ['local'], 'include_own': True}, db=db)['songs'] == 10
    # 作る前の一覧（今のデータベースとの違い）
    rows = {r['folder']: r for r in build_db.own_table(raw, db, own_patterns=OWN2, hints=hints)}
    assert {f: r['reasons'] for f, r in rows.items()} == WANT_OWN and all(r['was'] == 1 for r in rows.values())
    assert rows['marked']['author'] == 'Oz-Co2' and rows['marked']['song'] == 'marked'
    rows2 = build_db.own_table(raw, db, own_patterns=['auto-*', '!auto-keep', '!marked'], hints={})
    lines = []
    build_db.print_own(rows2, log=lines.append)
    assert '== 自分の物でなくなる: 5' in lines and '== 前から自分の物: 2' in lines   # 手がかりを空・marked を「!」に → marked-chro と auto-name だけ
    assert any(s.startswith('  marked | ') and '（どれも当たらない）' in s for s in lines)


def test_own_reasons_rules():
    m = lambda f, place='local', h=None: {'folder': f, 'place': place, 'hash': h}   # noqa: E731
    hints = {'folders': {'abc': ['work', 'export']}, 'hashes': {'ff': ['playlist']}}
    assert build_db.own_reasons(m('ABC'), None, [], hints) == ['work', 'export']             # フォルダ名は大文字・小文字を区別しない
    assert build_db.own_reasons(m('x', h='FF'), '0.2.0', ['x*'], hints) == ['mark', 'playlist', 'name']
    assert build_db.own_reasons(m('x', h='FF'), '0.2.0', ['x*', '!X'], hints) == []          # 「!」が勝つ
    assert build_db.own_reasons(m('abc', 'raw', 'ff'), None, ['a*'], hints) == []            # 取った譜面は手元の手がかりで決めない
    assert build_db.own_reasons(m('abc', 'raw'), '?', [], hints) == ['mark']                 # 印は取った譜面でも
    assert build_db.own_reasons(m('h'), None, [], {}) == []


@pytest.mark.parametrize('levels', [r'E:\BSManager\SharedContent\SharedMaps\CustomLevels', r'D:\Steam\steamapps\common\Beat Saber\Beat Saber_Data\CustomLevels',
                                    r'C:\maps\CustomLevels', r'C:\maps\levels', r'X:\a\sharedmaps\customlevels'])
def test_playlists_for_same_as_app(levels):
    sys.path.insert(0, str(ROOT / 'app'))
    import bsexport
    assert build_db.playlists_for(levels) == bsexport.playlists_for(levels)


# ---- 本物のデータ（手元の譜面とデータベースがある環境だけ） ----

def _real():
    try:
        p = L.db_path()
    except L.LibraryError:
        return None
    if not p.exists():
        return None
    try:
        con = L.open_db(p)
    except L.LibraryError:   # 版が合わない（build_db.py で作り直す）
        return None
    info = L.info_of(con)
    con.close()
    lr = info.get('local_root')
    if not lr or not Path(lr).is_dir():
        return None
    raw = Path(info['raw_root'])
    reg = {e['name'] for e in (C.read_json(raw / 'local' / 'index.json') or {}).get('folders', [])}
    return SimpleNamespace(db=p, local=Path(lr), reg=reg)


def _newest(root):
    t = os.path.getmtime(root)
    for f in os.listdir(root):
        p = os.path.join(root, f)
        if os.path.isdir(p):
            t = max([t, os.path.getmtime(p)] + [os.path.getmtime(os.path.join(p, g)) for g in os.listdir(p) if g.lower().endswith('.dat')])
    return t


@pytest.mark.skipif(_real() is None, reason='型のライブラリ（データベース）か手元の譜面が無い')
def test_real_local_same_as_library_themes(tmp_path):
    """本物の手元の譜面: データベースから書き出した型＝同じ CustomLevels から今の library_themes.py で作った型（全部・順も）"""
    r = _real()
    now = {f for f in os.listdir(r.local) if (r.local / f).is_dir()}
    if now != r.reg:
        pytest.skip(f'手元の譜面がデータベースを作った後に変わった（増えた {len(now - r.reg)}・消えた {len(r.reg - now)}）→ build_db.py で作り直す')
    out = L.export_themes({'sources': ['local'], 'once': False, 'include_own': True}, db=r.db)
    assert _core(out) == _themes_now(r.local, tmp_path / 'themes.json')
