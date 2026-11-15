"""遊んだリプレイを BL のリプレイアプリで開く（automap/bsor.py・app/replays.py・docs/アプリ仕様.md 26 節）。
作り物の .bsor（Open Replay Format を書く小さな道具＝下の bsor_bytes）と作り物の書き出し（Info.dat・難易度の .dat・song.egg）で確かめる:
読み方（頭・ノーツ・ボムの癖・壊れた文字列の長さ・満点と精度の目安）・譜面のフォルダの hash（bs_export.map_hash と同じ）・書き出しの控え
（hash ごと・音は中身ごとに 1 つ）・今の曲のリプレイの一覧（hash・曲名で選ぶ・譜面の出どころ）・開く（使い捨ての鍵・zip の中身）・
控えの無い版はリプレイの記録から組み立てる・サーバーの出入りの守り（/blr/ は合言葉なしで鍵を確かめる・ほかは合言葉が要る）。
他人の譜面・曲は使わない。"""
import hashlib
import http.client
import io
import json
import struct
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT))
from automap import bsor  # noqa: E402
from automap import config  # noqa: E402
import replays  # noqa: E402

SONG = 'テスト曲'


def _s(t, broken=False):
    b = t.encode('utf-8')
    return (b'\x00' if broken else b'') + struct.pack('<i', len(b)) + b


def bsor_bytes(song=SONG, h='AB' * 20, diff='Expert', score=1000, notes=(), walls=(), frames=3, broken=False, mods='', mapper='', end=None):
    """作り物の .bsor（BS-Open-Replay の形）。notes＝[(番号, 切った時刻, 出る時刻, 種類, before, after, 距離)]"""
    head = struct.pack('<iBB', bsor.MAGIC, 1, 0)
    strs = ['0.9.0', '1.40.8', '1794394711', '76561190000000000', 'プレイヤー', 'steam', 'Oculus', 'Quest3', 'Touch', h,
            song, mapper, diff]
    info = b''.join(_s(x, broken and i == 4) for i, x in enumerate(strs)) + struct.pack('<i', score)
    info += _s('Standard') + _s('DefaultEnvironment') + _s(mods) + struct.pack('<f?ffff', 17.0, False, 1.75, 0.0, 0.0, 1.0)
    fr = struct.pack('<Bi', 1, frames) + b''.join(struct.pack('<f', (end or 0) * (i + 1) / frames) + bytes(bsor.FRAME_SIZE - 4)
                                                  for i in range(frames))   # フレームの時刻（end＝最後のフレーム・無ければ 0）
    ns = struct.pack('<Bi', 2, len(notes))
    for nid, t, sp, kind, before, after, dist in notes:
        ns += struct.pack('<iffi', nid, t, sp, kind)
        if kind in (bsor.GOOD, bsor.BAD):
            ns += struct.pack('<????f3fiff3f3f4f', True, kind == bsor.GOOD, True, False, 3.0, 0, 0, 1, 1, 0.0, 0.0,
                              0, 1, 0, 0, 0, 1, dist, 0.0, before, after)
    ws = struct.pack('<Bi', 3, len(walls)) + b''.join(struct.pack('<ifff', *w) for w in walls)
    rest = struct.pack('<Bi', 4, 0) + struct.pack('<Bi', 5, 1) + struct.pack('<qf', 3, 12.5)
    return head + info + fr + ns + ws + rest


def nid(st, x, y, c, d):
    return st * 10000 + x * 1000 + y * 100 + c * 10 + d


NOTES = [(nid(3, 1, 0, 0, 1), 1.0, 1.0, bsor.GOOD, 1.0, 1.0, 0.0),     # 115 点
         (nid(3, 2, 0, 1, 1), 1.5, 1.5, bsor.GOOD, 1.0, 0.5, 0.15),    # 70+15+8
         (nid(3, 0, 2, 0, 0), 2.1, 2.0, bsor.BAD, 0.2, 0.0, 0.0),
         (nid(3, 3, 1, 1, 8), 2.5, 2.5, bsor.MISS, 0, 0, 0),
         (-1, 3.0, 3.0, bsor.GOOD, 0, 0, 0),                             # 古い形のボム（-1）
         (nid(6, 1, 1, 0, 1), 3.5, 3.5, bsor.GOOD, 1.0, 0.0, 0.0),     # チェーンの頭
         (nid(7, 1, 0, 0, 8), 3.6, 3.55, bsor.GOOD, 0, 0, 0)]          # チェーンの後ろ（組み立てでは使わない）


def test_parse_info_notes_and_quirks(tmp_path):
    f = tmp_path / 'r.bsor'
    f.write_bytes(bsor_bytes(notes=NOTES, walls=[(1, 0.1, 4.0, 4.0)], broken=True, mods='FS,NF'))
    info = bsor.read_info(f, head=64)   # 頭が 64 バイトを超えても読み足す
    assert (info['song_name'], info['difficulty'], info['hash'], info['modifiers'], info['mode']) == (SONG, 'Expert', 'AB' * 20, 'FS,NF', 'Standard')
    assert info['player_name'] == 'プレイヤー'   # 長さの前に 1 バイト余計な物があっても読み直す（公式の DecodeString と同じ）
    assert info['jump_distance'] == pytest.approx(17.0) and info['height'] == pytest.approx(1.75)
    r = bsor.read(f)
    assert r == bsor.parse(f.read_bytes())   # フレームを読み飛ばしても全部読んだ時と同じ
    assert r['frames'] == 3 and len(r['notes']) == 7 and len(r['walls']) == 1 and r['pauses'] == [(3, 12.5)]
    kinds = [n['type'] for n in r['notes']]
    assert kinds == [bsor.GOOD, bsor.GOOD, bsor.BAD, bsor.MISS, bsor.BOMB, bsor.GOOD, bsor.GOOD]   # -1 はボム
    assert r['notes'][4]['id'] == 3
    assert r['notes'][1]['cut']['after'] == pytest.approx(0.5)
    assert bsor.note_params(nid(3, 2, 1, 1, 7)) == (3, 2, 1, 1, 7)
    assert bsor.note_params(30000000 + 2 * 1000000 + 1 * 100000 + 15) == (3, 2, 1, 1, 5)   # 大きい譜面の形
    # 満点: 6 個（ボムを除く）＝115×1＋115×2＋115×2＋115×2＋85×2＋20×4
    assert bsor.max_score(r['notes']) == 115 + 115 * 2 * 3 + 85 * 2 + 20 * 4
    s = bsor.summary(r)
    assert (s['notes'], s['misses'], s['bad'], s['bombs'], s['walls']) == (6, 1, 1, 1, 1)
    assert s['acc'] == pytest.approx(1000 / bsor.max_score(r['notes']))


def test_not_a_replay(tmp_path):
    f = tmp_path / 'x.bsor'
    f.write_bytes(b'\x00' * 40)
    with pytest.raises(bsor.BsorError):
        bsor.read_info(f)


# ---- 作り物の書き出し ----

def make_level(folder, diffs=('Expert', 'Hard'), egg=b'OggS-egg', bpm=120.0, name=SONG, light=True):
    folder.mkdir(parents=True, exist_ok=True)
    info = {'_version': '2.1.0', '_songName': name, '_beatsPerMinute': bpm, '_songFilename': 'song.egg', '_coverImageFilename': 'cover.jpg',
            '_difficultyBeatmapSets': [{'_beatmapCharacteristicName': 'Standard', '_difficultyBeatmaps': [
                {'_difficulty': d, '_difficultyRank': replays.DIFF_RANK[d], '_beatmapFilename': f'{d}Standard.dat',
                 '_noteJumpMovementSpeed': 15.5, '_noteJumpStartBeatOffset': -0.25} for d in diffs]}]}
    (folder / 'Info.dat').write_text(json.dumps(info), encoding='utf-8')
    for d in diffs:
        dat = {'version': '3.2.0', 'colorNotes': [{'b': 2, 'x': 1, 'y': 0, 'c': 0, 'd': 1, 'a': 0}],
               'basicBeatmapEvents': [{'b': 0, 'et': 1, 'i': 3, 'f': 1}] if light else []}
        (folder / f'{d}Standard.dat').write_text(json.dumps(dat), encoding='utf-8')
    (folder / 'song.egg').write_bytes(egg)
    (folder / 'cover.jpg').write_bytes(b'\xff\xd8jpg')
    h = hashlib.sha1((folder / 'Info.dat').read_bytes())
    for d in diffs:
        h.update((folder / f'{d}Standard.dat').read_bytes())
    return h.hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    out, rdir = tmp_path / 'out', tmp_path / 'Replays'
    out.mkdir()
    rdir.mkdir()
    cfg = tmp_path / 'config.json'
    cfg.write_text(json.dumps({'bl_replays': str(rdir)}), encoding='utf-8')
    static = tmp_path / 'static'
    (static / 'blreplay').mkdir(parents=True)
    (static / 'blreplay' / 'index.html').write_text('<html></html>', encoding='utf-8')
    p = out / f'{SONG}.intent-s1.nlmf'
    p.write_text(json.dumps({'format': 'nlmf', 'version': 2, 'info': {'_songName': SONG}}), encoding='utf-8')

    def out_file(name):
        q = out / name
        assert q.parent == out
        return q
    ctx = SimpleNamespace(OUT=out, CONFIG=cfg, STATIC=static, CACHE=tmp_path / 'cache', out_file=out_file)
    monkeypatch.setattr(replays, '_TOK', {})
    monkeypatch.setattr(replays, '_SUM', {})
    monkeypatch.setattr(replays, '_SUM_DISK', {'path': None, 'dirty': False})
    monkeypatch.setattr(replays, '_LEVELS', {'key': None, 'items': []})
    levels = tmp_path / 'CustomLevels'
    levels.mkdir()
    monkeypatch.setattr(replays.bsexport, 'candidates', lambda cfg=None: [{'levels': str(levels)}])   # 本物の Beat Saber のフォルダを見ない
    return SimpleNamespace(ctx=ctx, out=out, rdir=rdir, p=p, tmp=tmp_path, mp=monkeypatch)


def record(env, folder, h):
    rp = env.out / '.export' / (env.p.name + '.json')
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({'dir': str(folder), 'folder': folder.name, 'hash': h}), encoding='utf-8')


def test_folder_hash_same_as_export(tmp_path):
    from automap import bs_export
    lv = tmp_path / 'lv'
    h = make_level(lv)
    files = {n.name: n.read_bytes() for n in lv.iterdir()}
    assert replays.folder_hash(lv) == h == bs_export.map_hash(files, json.loads(files['Info.dat']))


def test_keep_export_dedups_audio(env):
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h1 = make_level(lv)
    d = replays.keep_export(env.ctx, env.p, {'hash': h1, 'dir': str(lv)})
    assert sorted(x.name for x in d.iterdir()) == ['ExpertStandard.dat', 'HardStandard.dat', 'Info.dat', 'anp.json', 'cover.jpg']
    meta = json.loads((d / 'anp.json').read_text(encoding='utf-8'))
    assert meta['file'] == env.p.name and meta['egg'] == hashlib.sha1(b'OggS-egg').hexdigest()
    h2 = make_level(lv, diffs=('Expert',))   # 書き出し直し（音は同じ）
    replays.keep_export(env.ctx, env.p, {'hash': h2, 'dir': str(lv)})
    assert len(list((env.out / '.export' / 'eggs').iterdir())) == 1 and (env.out / '.export' / 'maps' / h2 / 'anp.json').is_file()
    assert replays.keep_export(env.ctx, env.p, {'hash': 'f' * 40, 'dir': str(lv)}) is None   # 書いた物と hash が違えば控えない


def unzip(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_list_open_and_serve(env):
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(h=h.upper(), notes=NOTES))                    # 今の書き出しで遊んだ
    (env.rdir / '1-b.bsor').write_bytes(bsor_bytes(h='CD' * 20, notes=NOTES, diff='ExpertPlus'))  # 前の版（控え無し）
    (env.rdir / '1-c.bsor').write_bytes(bsor_bytes(h='EF' * 20, song='ほかの曲'))
    (env.rdir / 'broken.bsor').write_bytes(b'junk')
    r = replays.list_replays(env.ctx, {'file': env.p.name})
    assert r['viewer'] and r['other'] == 1 and r['dirs'] == [str(env.rdir)]
    by = {x['id'].split('/')[1]: x for x in r['replays']}
    assert set(by) == {'1-a.bsor', '1-b.bsor'}
    assert by['1-a.bsor']['map'] == 'folder' and by['1-b.bsor']['map'] == 'rebuild'
    assert by['1-a.bsor']['misses'] == 1 and by['1-a.bsor']['acc'] == pytest.approx(1000 / (115 + 115 * 2 * 3 + 85 * 2 + 20 * 4))

    o = replays.open_replay(env.ctx, {'file': env.p.name, 'id': by['1-a.bsor']['id']})
    assert o['source'] == 'folder' and o['link'].endswith('/1-a.bsor') and o['mapLink'].endswith('/map.zip')
    bs, ct = replays.serve(o['link'])
    assert bs == (env.rdir / '1-a.bsor').read_bytes() and ct == 'application/octet-stream'
    z = unzip(replays.serve(o['mapLink'])[0])
    assert set(z) == {'Info.dat', 'ExpertStandard.dat', 'HardStandard.dat', 'song.egg', 'cover.jpg'}
    assert z['song.egg'] == b'OggS-egg'
    tok = o['link'].split('/')[2]
    assert replays.serve(f'/blr/{tok}/1-b.bsor') is None          # その鍵で渡すのは開いた 1 件だけ
    assert replays.serve('/blr/' + 'x' * 32 + '/map.zip') is None  # 知らない鍵
    assert replays.serve(f'/blr/{tok}/../config.json') is None

    # 書き出しを控えた後は控えから（書き出し先を書き換えても遊んだ時の譜面）
    replays.keep_export(env.ctx, env.p, {'hash': h, 'dir': str(lv)})
    make_level(lv, egg=b'OggS-new')
    o2 = replays.open_replay(env.ctx, {'file': env.p.name, 'id': by['1-a.bsor']['id']})
    assert o2['source'] == 'saved'
    assert unzip(replays.serve(o2['mapLink'])[0])['song.egg'] == b'OggS-egg'


def test_rebuild_from_replay(env):
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv, bpm=120.0)
    record(env, lv, h)
    (env.rdir / '1-b.bsor').write_bytes(bsor_bytes(h='CD' * 20, notes=NOTES, diff='Expert'))
    o = replays.open_replay(env.ctx, {'file': env.p.name, 'id': '0/1-b.bsor'})
    assert o['source'] == 'rebuild' and '組み立て' in o['note']
    z = unzip(replays.serve(o['mapLink'])[0])
    info = json.loads(z['Info.dat'])
    bms = info['_difficultyBeatmapSets']
    assert len(bms) == 1 and [bm['_difficulty'] for bm in bms[0]['_difficultyBeatmaps']] == ['Expert']
    bm = bms[0]['_difficultyBeatmaps'][0]
    assert bm['_beatmapFilename'] == 'ANPReplayExpertStandard.dat' and bm['_noteJumpMovementSpeed'] == 15.5   # NJS は今の書き出しの物
    assert 'HardStandard.dat' not in z and 'ExpertStandard.dat' not in z
    dat = json.loads(z['ANPReplayExpertStandard.dat'])
    # 出る時刻（秒）× BPM 120 ÷ 60 ＝拍。チェーンの後ろ（種類 7）は入れない・ボムはボムに
    assert [(n['b'], n['x'], n['y'], n['c'], n['d']) for n in dat['colorNotes']] == [
        (2.0, 1, 0, 0, 1), (3.0, 2, 0, 1, 1), (4.0, 0, 2, 0, 0), (5.0, 3, 1, 1, 8), (7.0, 1, 1, 0, 1)]
    assert dat['bombNotes'] == [{'b': 6.0, 'x': 0, 'y': 0}]
    assert dat['basicBeatmapEvents'] == [{'b': 0, 'et': 1, 'i': 3, 'f': 1}]   # ライトは今の書き出しの同じ難易度から
    assert z['song.egg'] == b'OggS-egg'


def test_no_map_and_bad_ids(env):
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(notes=NOTES))
    r = replays.list_replays(env.ctx, {'file': env.p.name})
    assert [x['map'] for x in r['replays']] == ['none']   # 曲名は同じでも、まだ書き出していない＝音が無い
    with pytest.raises(FileNotFoundError):
        replays.open_replay(env.ctx, {'file': env.p.name, 'id': '0/1-a.bsor'})
    for bad in ('0/../x.bsor', '1/1-a.bsor', '0/C:\\x.bsor', '0/1-a.txt', 'a/1-a.bsor', '0/\\\\host\\share\\a.bsor'):
        with pytest.raises((ValueError, FileNotFoundError)):
            replays.open_replay(env.ctx, {'file': env.p.name, 'id': bad})


def test_replay_dirs_from_levels(tmp_path):
    bsm = tmp_path / 'BSManager'
    lv = bsm / 'SharedContent' / 'SharedMaps' / 'CustomLevels'
    for v in ('1.39.1', '1.40.8'):
        (bsm / 'BSInstances' / v / 'UserData' / 'BeatLeader' / 'Replays').mkdir(parents=True)
    got = replays._replays_for(lv)
    assert [g.parts[-4] for g in got] == ['1.40.8', '1.39.1']   # 新しい版から
    game = tmp_path / 'Beat Saber'
    assert replays._replays_for(game / 'Beat Saber_Data' / 'CustomLevels') == [game / 'UserData' / 'BeatLeader' / 'Replays']


# ---- サーバーの出入りの守り（本物の HTTP） ----

@pytest.fixture
def srv(env, monkeypatch):
    import server
    monkeypatch.setattr(server, 'OUT', server.OUT)
    monkeypatch.setattr(server, 'CACHE', server.CACHE)
    monkeypatch.setattr(server, 'CONFIG', env.ctx.CONFIG)
    (env.tmp / 'cache').mkdir()
    s = server.make_server(0, env.out, env.tmp / 'cache')
    th = threading.Thread(target=s.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
    th.start()
    try:
        yield SimpleNamespace(port=s.server_address[1], token=server.TOKEN)
    finally:
        s.shutdown()
        s.server_close()


def _get(port, path, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    c.request('GET', path, headers=headers or {})
    r = c.getresponse()
    return r.status, r.read()


def test_server_guard(env, srv):
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(h=h, notes=NOTES))
    from urllib.parse import quote
    q = '/api/replays?file=' + quote(env.p.name)
    assert _get(srv.port, q)[0] == 403                                         # 一覧は合言葉が要る
    st, body = _get(srv.port, q, {'X-Automap-Key': srv.token})
    assert st == 200 and len(json.loads(body)['replays']) == 1
    o = replays.open_replay(env.ctx, {'file': env.p.name, 'id': '0/1-a.bsor'})
    st, body = _get(srv.port, quote(o['link']))                                # 鍵の場所は合言葉なしで
    assert st == 200 and body == (env.rdir / '1-a.bsor').read_bytes()
    assert _get(srv.port, o['mapLink'])[0] == 200
    assert _get(srv.port, '/blr/' + 'y' * 32 + '/map.zip')[0] == 404          # 知らない鍵
    assert _get(srv.port, o['mapLink'], {'Host': 'evil.example'})[0] == 403   # 名前の違うページからは出さない


def _req(port, path, headers=None, method='GET', body=None, host='127.0.0.1'):
    c = http.client.HTTPConnection(host, port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


def test_viewer_port(env, srv):
    """埋め込みのリプレイの窓（左下の欄・js/replaypane.js）: BL のリプレイアプリだけを別の番号（別のオリジン）で出す＝アプリの画面・合言葉に
    触れない。番号は合言葉の要る口で聞く・出すのは BL のリプレイアプリ・伝言の受け手・使い捨ての鍵の場所の GET だけ・index.html に伝言の
    受け手を足す（埋め込んでよいアプリの番号を書く）・埋め込めるのはアプリの画面からだけ（frame-ancestors）。名前は [::1]（別のサイト＝
    ブラウザが別の流れで描く）・同じ番号で 127.0.0.1 でも待つ（::1 で待てない PC は 127.0.0.1 だけ）"""
    import server
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(h=h, notes=NOTES))
    K = {'X-Automap-Key': srv.token}
    try:
        assert _req(srv.port, '/api/blrview')[0] == 403                          # 番号は合言葉が要る
        org = json.loads(_req(srv.port, '/api/blrview', K)[2])['origin']
        vp = int(org.rsplit(':', 1)[1])
        assert org in (f'http://[::1]:{vp}', f'http://127.0.0.1:{vp}') and vp != srv.port
        v6 = org.startswith('http://[::1]')
        if v6:   # [::1] の名前でも同じ物を出す・Host・Origin の [::1] を受ける
            st, hd, body = _req(vp, '/static/blreplay/index.html', {'Host': f'[::1]:{vp}'}, host='::1')
            assert st == 200 and b'blrembed/bridge.js' in body
            assert _req(vp, '/static/blrembed/bridge.js', {'Origin': org}, host='::1')[0] == 200
            assert _req(vp, '/api/songs', {**K, 'Host': f'[::1]:{vp}'}, host='::1')[0] == 403
        assert json.loads(_req(srv.port, '/api/blrview', K)[2])['origin'] == org   # サーバーを止めるまで同じ番号
        parents = f'http://127.0.0.1:{srv.port} http://localhost:{srv.port}'
        st, hd, body = _req(vp, '/static/blreplay/index.html')
        assert st == 200 and hd['content-security-policy'] == 'frame-ancestors ' + parents
        html = body.decode('utf-8')
        assert html.count('blrembed/bridge.js') == 1 and f'data-parent="{parents}"' in html
        assert html.index('blrembed/bridge.js') < html.rindex('</body>')
        assert b'blrembed' not in _req(srv.port, '/static/blreplay/index.html')[2]   # アプリの番号（別のタブ）では足さない
        assert _req(vp, '/static/blrembed/bridge.js')[0] == 200
        assert _req(vp, '/static/blreplay/build/' + next((server.STATIC / 'blreplay' / 'build').glob('*.js')).name)[0] == 200
        o = replays.open_replay(env.ctx, {'file': env.p.name, 'id': '0/1-a.bsor'})
        from urllib.parse import quote
        st, hd, body = _req(vp, quote(o['link']))
        assert st == 200 and body == (env.rdir / '1-a.bsor').read_bytes() and 'frame-ancestors' in hd['content-security-policy']
        assert _req(vp, o['mapLink'])[0] == 200
        # アプリの画面・受け口・音・書き換えはこの番号では出さない（合言葉があっても）
        for path in ('/', '/static/js/main.js', '/static/index.html', '/api/songs', '/api/blrview', '/audio/x/vocals.flac'):
            assert _req(vp, path, K)[0] == 403, path
        assert _req(vp, '/api/replays/open', {**K, 'X-Automap': '1', 'Content-Type': 'application/json'}, 'POST',
                    json.dumps({'file': env.p.name, 'id': '0/1-a.bsor'}).encode())[0] == 403
        assert _req(vp, o['mapLink'], {'Host': 'evil.example'})[0] == 403                     # 名前の違うページ
        assert _req(vp, o['mapLink'], {'Origin': f'http://127.0.0.1:{srv.port}'})[0] == 403  # ほかのオリジンのページ（アプリの画面も）から読まない
        assert _req(vp, o['mapLink'], {'Origin': org})[0] == 200                              # 埋め込んだ BL のリプレイアプリから
    finally:
        server.stop_viewers()


def test_song_name_needs_same_mapper(env):
    """曲名だけで合うリプレイは、作者名が空かこの曲を書き出した時の作者名の物だけ（同じ曲名の他人の譜面を混ぜない）"""
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    info = json.loads((lv / 'Info.dat').read_text(encoding='utf-8'))
    info['_levelAuthorName'] = 'Oz'
    (lv / 'Info.dat').write_text(json.dumps(info), encoding='utf-8')
    h = replays.folder_hash(lv)
    record(env, lv, h)
    (env.rdir / 'mine-old.bsor').write_bytes(bsor_bytes(h='CD' * 20, mapper=''))     # マッパー名を入れる前の書き出し
    (env.rdir / 'mine-oz.bsor').write_bytes(bsor_bytes(h='CE' * 20, mapper='oz'))    # 大文字小文字は見ない
    (env.rdir / 'theirs.bsor').write_bytes(bsor_bytes(h='CF' * 20, mapper='someone'))   # 同じ曲名の他人の譜面
    r = replays.list_replays(env.ctx, {'file': env.p.name})
    assert sorted(x['id'].split('/')[1] for x in r['replays']) == ['mine-old.bsor', 'mine-oz.bsor'] and r['other'] == 1
    # 設定のマッパー名（書き出しの窓で入れた名前）も自分の作者名に数える（NLM で書き出した版など）
    cfg = json.loads(env.ctx.CONFIG.read_text(encoding='utf-8'))
    env.ctx.CONFIG.write_text(json.dumps(dict(cfg, mapper_name='Someone')), encoding='utf-8')
    r = replays.list_replays(env.ctx, {'file': env.p.name})
    assert len(r['replays']) == 3 and r['other'] == 0


def test_all_history_and_open_without_song(env):
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    other = env.tmp / 'CustomLevels' / '1a2b (ほかの曲 - someone)'
    oh = make_level(other, name='ほかの曲', egg=b'OggS-other')
    info = json.loads((other / 'Info.dat').read_text(encoding='utf-8'))
    info['_levelAuthorName'] = 'someone'
    (other / 'Info.dat').write_text(json.dumps(info), encoding='utf-8')
    oh = replays.folder_hash(other)
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(h=h.upper(), notes=NOTES))                              # ANP の曲
    (env.rdir / '1-o.bsor').write_bytes(bsor_bytes(h=oh, song='ほかの曲', mapper='someone', notes=NOTES))   # 手元にある他人の譜面
    (env.rdir / '1-x.bsor').write_bytes(bsor_bytes(h='EF' * 20, song='無い曲', mapper='x'))                 # 手元に無い譜面
    r = replays.list_all(env.ctx, {})
    by = {x['id'].split('/')[1]: x for x in r['replays']}
    assert set(by) == {'1-a.bsor', '1-o.bsor', '1-x.bsor'}
    assert by['1-a.bsor']['anp'] == {'file': env.p.name, 'song': SONG} and by['1-a.bsor']['map'] == 'folder'
    assert by['1-o.bsor']['anp'] is None and by['1-o.bsor']['map'] == 'other' and by['1-o.bsor']['mapper'] == 'someone'
    assert by['1-a.bsor']['misses'] == 1
    # 一覧の数は作業の場所の cache に控える（サーバーを起動し直しても読み直さない）
    saved = json.loads((env.tmp / 'cache' / replays.SUM_FILE).read_text(encoding='utf-8'))
    assert saved['v'] == replays.SUM_VER and len(saved['items']) == 3

    o = replays.open_replay(env.ctx, {'id': by['1-a.bsor']['id']})   # 曲を指さない＝全部の履歴から
    assert o['source'] == 'folder' and o['mapLink']
    o = replays.open_replay(env.ctx, {'id': by['1-o.bsor']['id']})
    assert o['source'] == 'local' and unzip(replays.serve(o['mapLink'])[0])['song.egg'] == b'OggS-other'
    # 手元に無い譜面は BeatSaver から取る（テストはネットに出ない＝取る所を差し替える）
    asked = []
    env.mp.setattr(replays, 'beatsaver_zip', lambda h: asked.append(h) or b'PKzip')
    o = replays.open_replay(env.ctx, {'id': by['1-x.bsor']['id']})
    assert o['source'] == 'beatsaver' and asked == ['ef' * 20] and replays.serve(o['mapLink'])[0] == b'PKzip'
    assert replays.serve(o['link'])[0] == (env.rdir / '1-x.bsor').read_bytes()
    env.mp.setattr(replays, 'beatsaver_zip', lambda h: None)   # BeatSaver にも無い（消された・古い版・ネットが無い）
    with pytest.raises(FileNotFoundError):
        replays.open_replay(env.ctx, {'id': by['1-x.bsor']['id']})
    # 曲のフォルダの曲名と作者名の一覧も cache に控える（PC を起動した直後に Info.dat を読み直さない）
    lv_idx = json.loads((env.tmp / 'cache' / replays.LEVELS_FILE).read_text(encoding='utf-8'))
    assert lv_idx['items'][str(other)][1:] == ['ほかの曲', 'someone']


def test_beatsaver_zip_needs_hash():
    assert replays.beatsaver_zip('../x') is None and replays.beatsaver_zip('AB' * 20) is None   # 小文字の 40 字だけ（ネットに出ない）


JPG, PNG = b'\xff\xd8\xff\xe0', b'\x89PNG\r\n\x1a\n'


def test_cover(env):
    """全部の履歴のカバー画像（GET /api/replays/cover）: ANP の曲は書き出し先・ほかの譜面は手元の曲のフォルダ・無ければ BeatSaver。
    見つけた物は作業の場所の cache/.replay-covers/<hash> に控えて次からはそれを返す・見つからない hash はしばらく探し直さない"""
    env.mp.setattr(replays, '_COVER_MISS', {})
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    (lv / 'cover.jpg').write_bytes(JPG + b'anp')
    other = env.tmp / 'CustomLevels' / '1a2b (ほかの曲 - someone)'
    make_level(other, name='ほかの曲')
    info = json.loads((other / 'Info.dat').read_text(encoding='utf-8'))
    info.update(_levelAuthorName='someone', _coverImageFilename='c.png')
    (other / 'Info.dat').write_text(json.dumps(info), encoding='utf-8')
    (other / 'c.png').write_bytes(PNG + b'other')
    oh = replays.folder_hash(other)
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(h=h.upper()))
    (env.rdir / '1-o.bsor').write_bytes(bsor_bytes(h=oh, song='ほかの曲', mapper='someone'))
    (env.rdir / '1-x.bsor').write_bytes(bsor_bytes(h='EF' * 20, song='無い曲', mapper='x'))
    (env.rdir / '1-y.bsor').write_bytes(bsor_bytes(h='DD' * 20, song='消された曲', mapper='x'))
    asked = []
    env.mp.setattr(replays, '_beatsaver_cover', lambda hh: asked.append(hh) or (JPG + b'bs' if hh == 'ef' * 20 else None))
    root = env.tmp / 'cache' / replays.COVERS_DIR
    c = replays.cover(env.ctx, {'id': '0/1-a.bsor', 'file': env.p.name})
    assert c == root / (h + '.jpg') and c.read_bytes() == JPG + b'anp'
    c = replays.cover(env.ctx, {'id': '0/1-o.bsor'})
    assert c == root / (oh + '.png') and c.read_bytes() == PNG + b'other'
    c = replays.cover(env.ctx, {'id': '0/1-x.bsor'})
    assert c.read_bytes() == JPG + b'bs' and asked == ['ef' * 20]
    (lv / 'cover.jpg').write_bytes(JPG + b'changed')
    assert replays.cover(env.ctx, {'id': '0/1-a.bsor', 'file': env.p.name}).read_bytes() == JPG + b'anp'   # 控えを返す
    replays.cover(env.ctx, {'id': '0/1-x.bsor'})
    assert asked == ['ef' * 20]                                       # 控えがあれば BeatSaver に聞かない
    for _ in range(2):
        with pytest.raises(FileNotFoundError):
            replays.cover(env.ctx, {'id': '0/1-y.bsor'})
    assert asked == ['ef' * 20, 'dd' * 20]                            # 無かった hash はしばらく聞き直さない
    def gone(name):
        raise FileNotFoundError(name)
    env.mp.setattr(env.ctx, 'out_file', gone)                          # ANP の曲の結果のファイルが読めない → 次の探し先（手元の曲のフォルダ）へ
    (root / (oh + '.png')).unlink()
    assert replays.cover(env.ctx, {'id': '0/1-o.bsor', 'file': '消した曲.intent-s1.nlmf'}).read_bytes() == PNG + b'other'
    (lv / 'cover.jpg').write_bytes(b'<html>not an image')               # 画像でない物は使わない
    assert replays._folder_cover(lv) is None
    with pytest.raises(ValueError):
        replays.cover(env.ctx, {'id': '0/../x.bsor'})


def test_cover_same_hash_at_once(env):
    """同じ譜面を何回も遊んだ行（同じ hash）のカバーを同時に頼まれても、作るのは 1 回・どの頼みも同じ控えを返す・作った後は置き換えない
    （2026-11-15: 置き換えている最中に別の頼みが開くと Windows が Permission denied で断った）"""
    import time as T
    env.mp.setattr(replays, '_COVER_MISS', {})
    for i in range(8):
        (env.rdir / f'1-{i}.bsor').write_bytes(bsor_bytes(h='CC' * 20, song='何回も遊んだ曲', mapper='x'))
    made = []
    env.mp.setattr(replays, '_find_cover', lambda ctx, h, info, file=None: made.append(h) or T.sleep(0.2) or (JPG + b'once'))
    got, errs = [], []

    def ask(i):
        try:
            got.append(replays.cover(env.ctx, {'id': f'0/1-{i}.bsor'}))
        except Exception as e:   # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=ask, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs and len(made) == 1 and len(set(got)) == 1 and got[0].read_bytes() == JPG + b'once'
    assert not list(got[0].parent.glob('*.tmp'))


def test_cover_http(env, srv):
    """<img> の src で読む＝合言葉は ?k= でも受ける（server.KEY_QUERY）"""
    env.mp.setattr(replays, '_COVER_MISS', {})
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    (lv / 'cover.jpg').write_bytes(JPG + b'anp')
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(h=h))
    from urllib.parse import quote
    q = '/api/replays/cover?id=' + quote('0/1-a.bsor') + '&file=' + quote(env.p.name)
    assert _req(srv.port, q)[0] == 403
    st, hd, body = _req(srv.port, q + '&k=' + srv.token)
    assert st == 200 and body == JPG + b'anp' and hd['content-type'] == 'image/jpeg'


def test_stars(env):
    """一覧の★（POST /api/replays/stars）: 遊んだ時の譜面（ANP の曲は同じ hash の書き出し先・ほかは手元の曲のフォルダ）の遊んだ難易度を
    nlm-rating で測る（裏で・測っていない物は pending）・控えは作業の場所の cache に hash・遊び方・難易度・版ごと・遊んだ版が無い物は None"""
    import time as _t
    from automap import rating as R
    env.mp.setattr(replays, '_STARS', {'path': None, 'items': {}})
    env.mp.setattr(replays, '_STAR_MISS', {})
    env.mp.setattr(replays, '_STAR_PENDING', set())
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    other = env.tmp / 'CustomLevels' / '1a2b (ほかの曲 - someone)'
    make_level(other, name='ほかの曲', diffs=('Hard',))
    info = json.loads((other / 'Info.dat').read_text(encoding='utf-8'))
    info['_levelAuthorName'] = 'someone'
    (other / 'Info.dat').write_text(json.dumps(info), encoding='utf-8')
    oh = replays.folder_hash(other)
    (env.rdir / '1-a.bsor').write_bytes(bsor_bytes(h=h.upper(), diff='Expert'))
    (env.rdir / '1-o.bsor').write_bytes(bsor_bytes(h=oh, song='ほかの曲', mapper='someone', diff='Hard'))
    (env.rdir / '1-x.bsor').write_bytes(bsor_bytes(h='EF' * 20, song='無い曲', mapper='x'))
    exe = env.tmp / 'nlm-rating.exe'
    exe.write_bytes(b'')
    asked = []

    def run(e, req, timeout=300):
        t = req['targets'][0]
        asked.append((t['characteristic'], t['difficulty'], sorted(f['name'] for f in req['files'])))
        st = {'Expert': 6.234, 'Hard': 3.5}[t['difficulty']]
        return {'ok': True, 'results': [{'difficulty': t['difficulty'], 'ratings': {'none': {'stars': st}}}]}
    env.mp.setattr(R, 'rating_exe', lambda: str(exe))
    env.mp.setattr(R, 'exe_version', lambda e: '4.1.0')
    env.mp.setattr(R, 'run', run)
    items = [{'id': '0/1-a.bsor', 'file': env.p.name}, {'id': '0/1-o.bsor'}, {'id': '0/1-x.bsor'}, {'id': '0/../bad.bsor'}]
    r = replays.stars(env.ctx, {'items': items})
    assert set(r['pending']) == {'0/1-a.bsor', '0/1-o.bsor', '0/1-x.bsor'} and r['stars'] == {'0/../bad.bsor': None}
    end = _t.time() + 10
    while r['pending'] and _t.time() < end:
        _t.sleep(0.05)
        r = replays.stars(env.ctx, {'items': items})
    assert not r['pending']
    assert r['stars'] == {'0/1-a.bsor': 6.23, '0/1-o.bsor': 3.5, '0/1-x.bsor': None, '0/../bad.bsor': None}
    assert sorted(asked) == [('Standard', 'Expert', ['ExpertStandard.dat', 'Info.dat']), ('Standard', 'Hard', ['HardStandard.dat', 'Info.dat'])]
    saved = json.loads((env.tmp / 'cache' / replays.STARS_FILE).read_text(encoding='utf-8'))
    assert saved['items'] == {f'{h}|Standard|Expert|4.1.0': 6.23, f'{oh}|Standard|Hard|4.1.0': 3.5}   # 測れない物は控えに書かない
    replays.stars(env.ctx, {'items': items})
    assert len(asked) == 2                                                  # 控え・測れなかった物は測り直さない
    env.mp.setattr(replays, '_STARS', {'path': None, 'items': {}})
    assert replays.stars(env.ctx, {'items': items[:2]})['stars'] == {'0/1-a.bsor': 6.23, '0/1-o.bsor': 3.5}   # 起動し直しても控えから
    env.mp.setattr(R, 'exe_version', lambda e: '4.2.0')                     # nlm-rating の版が変わったら測り直す
    assert set(replays.stars(env.ctx, {'items': items[:2]})['pending']) == {'0/1-a.bsor', '0/1-o.bsor'}
    env.mp.setattr(R, 'rating_exe', lambda: None)
    assert replays.stars(env.ctx, {'items': items})['error'] == R.NO_EXE
    end = _t.time() + 10
    while replays._STAR_PENDING and _t.time() < end:
        _t.sleep(0.05)


def test_exit_and_end(env):
    """途中でやめたプレイ: BeatLeader はファイル名に -exit- を付ける（.bsor の中に印は無い）→ 一覧の exit。記録が終わった秒（最後の
    フレームの時刻）は end（左下の欄はそこで止める）。数の控えは版（SUM_VER）が違えば読み直す"""
    lv = env.tmp / 'CustomLevels' / 'anp-test'
    h = make_level(lv)
    record(env, lv, h)
    (env.rdir / f'76561190000000000-exit-{SONG}-Expert-Standard-{h}-1794394711.bsor').write_bytes(bsor_bytes(h=h, frames=40, end=4.25))
    (env.rdir / f'76561190000000000-fail-{SONG}-Expert-Standard-{h}-1794394712.bsor').write_bytes(bsor_bytes(h=h, frames=5, end=12.0))
    (env.rdir / f'76561190000000000-{SONG}-Expert-Standard-{h}-1794394713.bsor').write_bytes(bsor_bytes(h=h, frames=5, end=200.0))
    rows = {r['id'].split('-')[1]: r for r in replays.list_replays(env.ctx, {'file': env.p.name})['replays']}
    assert rows['exit']['exit'] is True and rows['exit']['end'] == 4.25
    assert rows['fail']['exit'] is False and rows['fail']['end'] == 12.0
    assert rows[SONG]['exit'] is False and rows[SONG]['end'] == 200.0
    f = next(env.rdir.glob('*-exit-*'))
    assert bsor.parse(f.read_bytes())['end'] == bsor.read(f)['end'] == 4.25   # 全部読む道と読み飛ばす道で同じ
    assert replays.name_flags('1-practice-fail-曲-Expert-Standard-AB-1.bsor') == {'practice', 'fail'}
    assert replays.name_flags('1-My exit-Expert-Standard-AB-1.bsor') == set()      # 曲名の中の exit は印ではない
    old = env.tmp / 'cache' / replays.SUM_FILE                                 # 前の版の控え（end が無い）は読み直す
    d = json.loads(old.read_text(encoding='utf-8'))
    for v in d['items'].values():
        v[2].pop('end', None)
    old.write_text(json.dumps(dict(d, v=1)), encoding='utf-8')
    env.mp.setattr(replays, '_SUM', {})
    env.mp.setattr(replays, '_SUM_DISK', {'path': None, 'dirty': False})
    rows = {r['id'].split('-')[1]: r for r in replays.list_replays(env.ctx, {'file': env.p.name})['replays']}
    assert rows['exit']['end'] == 4.25
