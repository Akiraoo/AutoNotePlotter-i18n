"""Beat Saber に書き出す窓のカバー画像（app/bsexport.cover_view・set_cover・cover_image・2026-11-09 利用者「カバー画像が見えるように・
ここから変えられるように（取り込みの時と同じ）」）: 今のカバーと候補を見せ、選んだ画像は取り込みと同じ決まりで結果のファイルの隣へ写して
（上書きしない）、書き出しに繋がったカバーのノードと coverData に入れる。選べるのは見せてよいと覚えた画像（importer._SEEN）だけ"""
import base64
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from automap import __main__ as cli
from automap import bs_export as B
from automap import new_project, nlmf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import bsexport  # noqa: E402
import importer  # noqa: E402


def _png(w, h, seed=0):
    raw = b''.join(b'\x00' + bytes([(x * 7 + y + seed) % 256 for x in range(w)] * 3) for y in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


@pytest.fixture
def song(tmp_path, monkeypatch):
    """カバーの無い結果のファイル（書いたままの指紋つき）と、音源のフォルダの Cover.png"""
    music = tmp_path / 'music'
    music.mkdir()
    wav = music / 'song.wav'
    sf.write(wav, np.zeros((22050, 2), np.float32), 22050)
    (music / 'Cover.png').write_bytes(_png(300, 300, 1))
    proj = new_project.build(wav, {'grid': {'bpm': 120, 'leadMs': 0}}, title='テスト曲', artist='だれか', diff='ExpertPlus')
    out = tmp_path / 'out'
    out.mkdir()
    p = out / 'テスト曲.intent-s1.nlmf'
    cli._save(proj, p)
    busy = set()
    ctx = SimpleNamespace(OUT=out, CONFIG=tmp_path / 'config.json', out_file=lambda f: out / Path(f).name, busy=lambda f: f in busy, cli=cli,
                          busy_set=busy)
    monkeypatch.setattr(importer, '_SEEN', set())
    monkeypatch.setattr(importer, 'PASTE_DIR', tmp_path / 'paste')
    monkeypatch.setattr(bsexport, 'candidates', lambda cfg=None: [])   # この PC の Beat Saber のフォルダを探さない
    return ctx, p, music


def _node(p):
    proj = nlmf.load(p)
    cid = B.connected(B.info_graph(proj), 'cover')
    return proj, cid, proj['infoGraph']['nodes'][cid]['data']


def test_view_and_set(song):
    ctx, p, music = song
    cv = bsexport.cover_view(ctx, p)
    assert cv['now'] is None and cv['cands'] == [str(music / 'Cover.png')] and str(music / 'Cover.png') in importer._SEEN
    assert bsexport.plan(ctx, p.name)['covers'] == cv
    with pytest.raises(FileNotFoundError):
        bsexport.cover_image(ctx, {'file': p.name})
    r = bsexport.set_cover(ctx, {'file': p.name, 'path': str(music / 'Cover.png')})
    dst = p.parent / 'テスト曲.png'   # 取り込みと同じ置き場所（結果のファイルの隣・<曲>.<拡張子>）
    assert r['ok'] and Path(r['cover']) == dst and dst.read_bytes() == (music / 'Cover.png').read_bytes()
    proj, cid, d = _node(p)
    assert d['name'] == 'テスト曲.png' and d['nativePath'] == str(dst.resolve())
    assert base64.b64decode(proj['coverData'][cid].split(',')[1]) == dst.read_bytes()   # NLM が開いた時に使う同梱の画像
    assert [x['name'] for x in proj['graph']['extra'] if x.get('kind') == 'cover'] == ['テスト曲.png']
    assert B.plan_proj(proj)['info']['cover'] == str(dst.resolve())   # 書き出しに使う
    assert not cli._edited_since_written(p)   # アプリが書いたままの印は残す（NLM で直した扱いにしない）
    assert r['plan']['covers']['now'] == str(dst.resolve()) and r['plan']['covers']['size'] == [300, 300]
    assert r['plan']['covers']['cands'] == []   # 音源のフォルダの Cover.png は今のカバーと同じ中身＝出さない
    data, ctype = bsexport.cover_image(ctx, {'file': p.name})
    assert data == dst.read_bytes() and ctype == 'image/png'


def test_change_again_keeps_old_and_can_go_back(song):
    ctx, p, music = song
    bsexport.cover_view(ctx, p)   # 窓を開いた（候補を見せた）
    bsexport.set_cover(ctx, {'file': p.name, 'path': str(music / 'Cover.png')})
    first = p.parent / 'テスト曲.png'
    pasted = importer.save_pasted(base64.b64encode(_png(320, 320, 9)).decode())   # 貼り付け（取り込みの窓と同じ受け口）
    r = bsexport.set_cover(ctx, {'file': p.name, 'path': str(pasted)})
    second = p.parent / 'テスト曲.cover.png'   # 同じ名前で中身の違う物は上書きしない
    assert Path(r['cover']) == second and second.read_bytes() == pasted.read_bytes() and first.read_bytes() == (music / 'Cover.png').read_bytes()
    cv = r['plan']['covers']
    assert cv['now'] == str(second.resolve()) and cv['size'] == [320, 320] and cv['cands'] == [str(first)]   # 前のカバーへ戻せる
    r = bsexport.set_cover(ctx, {'file': p.name, 'path': cv['cands'][0]})
    assert Path(r['cover']) == first and _node(p)[2]['nativePath'] == str(first.resolve())
    assert sorted(q.name for q in p.parent.glob('テスト曲*.png')) == ['テスト曲.cover.png', 'テスト曲.png']   # 戻しても写しは増えない


def test_embedded_only(song):
    ctx, p, music = song
    bsexport.cover_view(ctx, p)   # 窓を開いた（候補を見せた）
    bsexport.set_cover(ctx, {'file': p.name, 'path': str(music / 'Cover.png')})
    (p.parent / 'テスト曲.png').unlink()   # 画像のファイルが無くても .nlmf に入っている画像を見せる（書き出しも同じ）
    cv = bsexport.cover_view(ctx, p)
    assert cv['now'] == '' and cv['name'] == 'テスト曲.png' and cv['size'] == [300, 300]
    assert bsexport.cover_image(ctx, {'file': p.name})[0] == (music / 'Cover.png').read_bytes()


def test_rejects(song):
    ctx, p, music = song
    other = music / 'other.png'
    other.write_bytes(_png(256, 256, 3))
    with pytest.raises(ValueError, match='候補'):   # 見せてよいと覚えていない画像
        bsexport.set_cover(ctx, {'file': p.name, 'path': str(other)})
    txt = music / 'a.txt'
    txt.write_text('x')
    importer._SEEN.add(str(txt))
    with pytest.raises(ValueError, match='jpg・png'):
        bsexport.set_cover(ctx, {'file': p.name, 'path': str(txt)})
    importer._SEEN.add(str(other))
    ctx.busy_set.add(p.name)
    with pytest.raises(ValueError, match='作り直して'):   # 作り直し・書き出しの最中は変えない
        bsexport.set_cover(ctx, {'file': p.name, 'path': str(other)})
    ctx.busy_set.clear()
    with pytest.raises(ValueError):
        bsexport.set_cover(ctx, {'file': p.name, 'path': ''})
    assert _node(p)[2].get('name', '') == '' and not list(p.parent.glob('*.png'))   # 何も変えていない


def test_playlist_name_and_dir(song, tmp_path):
    """プレイリストに書けるのは 1 つの名前の .bplist だけ・プレイリストの場所はあるフォルダだけ
    （前はどんな拡張子でも書けた＝スタートアップのフォルダに .bat を書かれた・F10）"""
    ctx, p, _ = song
    for ok in ('AutoNotePlotter.bplist', 'My List.BPLIST', '曲たち.bplist'):
        assert bsexport._bplist_name(ok), ok
    for bad in ('a.bat', 'a.bplist.bat', '.bplist', '..\\a.bplist', '../a.bplist', 'C:a.bplist', 'a.bplist ', 'a.bplist.', ' a.bplist',
                'a\x01.bplist', '', None):
        assert not bsexport._bplist_name(bad), bad
    with pytest.raises(ValueError, match='.bplist だけ'):   # 書き出しを始める前に断る（何も書かない）
        bsexport.start(ctx, {'file': p.name, 'folder': 'x', 'levels': str(tmp_path), 'playlist': {'file': 'anp.bat', 'title': 'x'}})
    with pytest.raises(ValueError, match='見つかりません'):
        bsexport.set_settings(ctx, {'playlists_dir': str(tmp_path / 'none')})
    assert bsexport.set_settings(ctx, {'playlists_dir': str(tmp_path)})['ok']
