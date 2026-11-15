"""プレイリスト（automap/playlist.py）: 作る・足す・書き出し直したら置き換える・知らない項目は残す"""
import json

from automap import playlist as PL


def test_new_add_replace_keep_unknown(tmp_path):
    p = tmp_path / PL.DEFAULT_FILE
    e1 = PL.entry('abc123', '曲A', 'me', [('Standard', 'ExpertPlus'), ('Standard', 'Hard')], 'anp-songA')
    r = PL.add_song(p, e1, title='Auto Note Plotter', author='me', image='iVBORw0K')
    assert r == {'file': PL.DEFAULT_FILE, 'title': 'Auto Note Plotter', 'songs': 1, 'replaced': False}
    d = json.loads(p.read_text(encoding='utf-8'))
    s = d['songs'][0]
    assert d['image'] == 'iVBORw0K' and s['hash'] == 'ABC123' and s['levelid'] == 'custom_level_ABC123'
    assert s['difficulties'] == [{'characteristic': 'Standard', 'name': 'expertPlus'}, {'characteristic': 'Standard', 'name': 'hard'}]
    PL.add_song(p, PL.entry('def456', '曲B', 'me', [('Standard', 'Expert')], 'anp-songB'))
    # 曲A を書き出し直した（hash が変わる）＝前の行を置き換える・並びはそのまま
    r = PL.add_song(p, PL.entry('999fff', '曲A', 'me', [('Standard', 'ExpertPlus')], 'anp-songA'))
    assert r['replaced'] and r['songs'] == 2
    assert [x['hash'] for x in json.loads(p.read_text(encoding='utf-8'))['songs']] == ['999FFF', 'DEF456']


def test_add_to_existing_playlist_keeps_fields(tmp_path):
    """BeatLeader 等が作ったプレイリスト（BOM 付き・customData・知らない項目）に足しても、元の項目は消さない"""
    p = tmp_path / 'bl.bplist'
    src = {'playlistTitle': 'PracticeSong1', 'playlistAuthor': 'BeatLeader', 'image': 'xyz', 'customData': {'syncURL': 'https://x', 'id': '1'},
           'songs': [{'hash': 'f1ce', 'songName': 'X', 'difficulties': [{'name': 'hard', 'characteristic': 'Standard'}], 'extra': 1}]}
    p.write_bytes(b'\xef\xbb\xbf' + json.dumps(src).encode('utf-8'))
    PL.add_song(p, PL.entry('a1', '曲', 'me', [('Standard', 'Expert')], 'anp-x'))
    d = json.loads(p.read_text(encoding='utf-8'))
    assert d['customData'] == src['customData'] and d['image'] == 'xyz' and d['songs'][0] == src['songs'][0] and len(d['songs']) == 2
    ls = PL.list_playlists(tmp_path)
    assert ls == [{'file': 'bl.bplist', 'title': 'PracticeSong1', 'author': 'BeatLeader', 'songs': 2, 'anp': 1}]
    (tmp_path / 'broken.bplist').write_text('{', encoding='utf-8')
    assert [x['file'] for x in PL.list_playlists(tmp_path)] == ['bl.bplist']   # 読めない物は飛ばす
    assert PL.list_playlists(tmp_path / 'none') == []


def test_safe_file():
    assert PL.safe_file('My: List?') == 'My_ List_.bplist'
    assert PL.safe_file('  ') == 'playlist.bplist'
