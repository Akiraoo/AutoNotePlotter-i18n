"""新しい曲の元のプロジェクトを NLM を使わずに作る（automap/new_project.py）と、アプリの曲の取り込み（app/importer.py）"""
import json
import re
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from automap import new_project as NP
from automap import nlmf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'app'))
import nlm_project  # noqa: E402
import importer  # noqa: E402

# NLM の保存の項目の並び（buildProjectText）
NLM_KEYS = ['format', 'version', 'savedAt', 'bpm', 'tempoParts', 'current', 'musicBeat', 'musicSegs', 'songDeleted', 'noteRed', 'noteBlue',
            'laserRed', 'laserBlue', 'markers', 'notesLanes', 'lightLanes', 'info', 'infoGraph', 'njsCfg', 'coverData', 'chainCurveGlobal',
            'chromaPalette', 'laneStates', 'view', 'analysis', 'graph', 'difficulties']


def _analysis(bpm=128.0, lead=215):
    secs = [{'start': 2.0, 'end': 34.0, 'label': 'S1', 'count': 2, 'chorus': False, 'name': 'Aメロ'},
            {'start': 34.0, 'end': 66.0, 'label': 'S2', 'count': 1, 'chorus': True, 'name': 'サビ'},
            {'start': 66.0, 'end': 70.0, 'label': 'S3', 'count': 1, 'chorus': False, 'name': '間奏'},
            {'start': 70.0, 'end': 98.0, 'label': 'S4', 'count': 2, 'chorus': False, 'name': '間奏'},
            {'start': 98.0, 'end': 130.0, 'label': 'S5', 'count': 1, 'chorus': False, 'name': ''}]
    return {'v': 1, 'tempo': {'bpm': bpm, 'lead_ms': float(lead)}, 'structure': {'sub': 4, 'sections': secs, 'segments': [], 'chorus': ['B']},
            'names': {}, 'grid': {'bpm': bpm, 'leadMs': lead, 'tp': [], 'mb': 0, 'ms': None, 'song': 'x.flac'}}


def _wav(path, sec=1.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros((int(44100 * sec), 2), dtype='float32'), 44100)
    return path


def test_safe_name():
    """ファイル名に使う名前: Windows で使えない文字と「.」は _（アプリはファイル名の最初の「.」より前を曲の名前とみる）・終わりの点は落とす"""
    assert NP.safe_name('a/b:c*d?') == 'a_b_c_d_'
    assert NP.safe_name('Oz.') == 'Oz' and NP.safe_name('Mr. Blue') == 'Mr_ Blue'
    assert NP.safe_name('  ') == 'song' and NP.safe_name('CON') == 'CON_' and NP.safe_name('曲 名') == '曲 名'


def test_markers_same_rule_as_nlm_project():
    """マーカーは NLM で作る時（tools/nlm_project.markers_from_analysis）と同じ決まり（同じ名前が続く区間は1つ・名前が無ければ記号）"""
    an = _analysis()
    assert NP.markers_from_analysis(an) == nlm_project.markers_from_analysis(an)
    assert [m['name'] for m in NP.markers_from_analysis(an)] == ['Aメロ', 'サビ', '間奏', 'S5']


def test_build_like_nlm_new_project(tmp_path):
    """NLM が新しいプロジェクトで保存するのと同じ形: 項目の並び・既定の Hard と作る難易度（空）・BPM・無音追加（offset＝−秒）・
    曲名とアーティスト（3か所）・音源の場所・追加ノードの id とつながり・数は JS の書き方"""
    au = _wav(tmp_path / '01 song.wav')
    p = NP.build(au, _analysis(128.0, 215), title='曲', artist='誰か')
    assert list(p) == NLM_KEYS
    assert p['bpm'] == 128 and isinstance(p['bpm'], int) and p['info']['_beatsPerMinute'] == 128
    assert p['graph']['song'] == {'nx': 310, 'ny': 360, 'name': '01 song.wav', 'offset': -0.215, 'nativePath': str(au.resolve())}
    assert list(p['difficulties']) == ['hardstandard.dat', 'expertplusstandard.dat'] and p['current'] == 'ExpertPlusStandard.dat'
    assert all(not d['sections'] and not d['notes'] for d in p['difficulties'].values())
    assert p['info']['_songName'] == p['infoGraph']['nodes']['m1']['data']['name'] == p['graph']['extra'][0]['data']['_songName'] == '曲'
    assert p['info']['_songAuthorName'] == p['infoGraph']['nodes']['m1']['data']['artist'] == '誰か'
    x1, x2 = (x['id'] for x in p['graph']['extra'])
    assert re.fullmatch(r'x1[0-9a-z]{4}', x1) and re.fullmatch(r'x2[0-9a-z]{4}', x2)
    assert [e['fromId'] for e in p['graph']['edges'] if e['sig'] in ('info', 'cover')] == [x1, x2]
    assert p['markers'][0] == {'beat': 2, 'name': 'Aメロ'} and p['analysis']['grid']['leadMs'] == 215
    q = NP.build(au, _analysis(129.5, 0), title='t', artist='', diff='Hard')
    assert q['bpm'] == 129.5 and q['graph']['song']['offset'] == 0 and list(q['difficulties']) == ['hardstandard.dat']
    assert NP.js_numbers({'a': [1.0, -0.0, 0.25]}) == {'a': [1, 0, 0.25]}


def test_save_and_cover(tmp_path):
    """保存は NLM と同じ書き方（BOM なし・詰めた JSON・savedAt はミリ秒）で nlmf.load で読める。カバー画像は set_export と同じ形で、
    プロジェクトの隣へ写す（同じ名前で中身が違う物は上書きしない）"""
    au = _wav(tmp_path / 'a.wav')
    img = tmp_path / 'src' / 'Cover.JPG'
    img.parent.mkdir()
    img.write_bytes(b'\xff\xd8\xff\xe0 jpeg')
    out = tmp_path / 'out' / '曲.nlmf'
    out.parent.mkdir()
    p = NP.make(au, out, _analysis(), title='曲', artist='', cover=img, log=lambda s: None)
    raw = out.read_bytes()
    assert raw.startswith(b'{"format":"nlmf","version":2,"savedAt":"') and b'\n' not in raw
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', nlmf.load(out)['savedAt'])
    assert (tmp_path / 'out' / '曲.jpg').read_bytes() == img.read_bytes()
    c1 = p['infoGraph']['nodes']['c1']['data']
    assert c1 == {'name': '曲.jpg', 'nativePath': str((tmp_path / 'out' / '曲.jpg').resolve())}
    assert next(x for x in p['graph']['extra'] if x['kind'] == 'cover')['name'] == '曲.jpg'
    assert list(p['coverData']) == ['c1'] and p['coverData']['c1'].startswith('data:application/octet-stream;base64,')
    # 試聴の区間は最初のサビの頭（拍 34・BPM 128＝15.94 秒）から 10 秒（set_export の auto と同じ）。サビが無ければ NLM の既定の 12 秒。
    # 入れるのは元の音源の秒＝拍の時刻から無音追加を引いた秒（NLM の試聴ノードと同じ・書き出す時に NLM が無音追加を足す）
    want = round(34 * 60 / 128 - NP.lead_sec(p), 2)
    assert NP.lead_sec(p) > 0 and want < 15.94
    assert p['info']['_previewStartTime'] == want and p['infoGraph']['nodes']['p1']['data'] == {'start': want, 'dur': 10}
    q = NP.build(au, _analysis())
    q['markers'] = [m for m in q['markers'] if m['name'] != 'サビ']
    assert NP.set_preview(q) == 12 and q['infoGraph']['nodes']['p1']['data']['start'] == 12
    other = tmp_path / 'src' / 'folder.jpg'
    other.write_bytes(b'\xff\xd8 other')
    assert NP.set_cover(p, out, other).name == '曲.cover.jpg' and (tmp_path / 'out' / '曲.jpg').read_bytes() == img.read_bytes()
    assert NP.set_cover(p, out, img).name == '曲.jpg'
    assert NP.cover_candidates(au) == [] and NP.cover_candidates(img)[0].endswith('Cover.JPG')


def test_make_with_analysis_on_synthetic_audio(tmp_path):
    """合成の音（120 BPM の打ち込み・8 小節ごとに和音が変わる）で、曲の解析から元のプロジェクトまで通る"""
    sr, bpm, sec = 44100, 120.0, 40.0
    t = np.arange(int(sr * sec)) / sr
    y = np.zeros_like(t)
    for k in range(int(sec * bpm / 60)):
        i = int(k * 60 / bpm * sr)
        n = min(len(y) - i, 2000)
        y[i:i + n] += np.exp(-np.arange(n) / 300) * (1.0 if k % 2 == 0 else 0.5) * np.sin(2 * np.pi * 120 * np.arange(n) / sr)
    roots = [220.0, 174.6, 261.6, 196.0]
    for b in range(int(sec / 16) + 1):
        a, e = int(b * 16 * sr), min(len(y), int((b + 1) * 16 * sr))
        f = roots[b % 4]
        y[a:e] += 0.15 * sum(np.sin(2 * np.pi * f * m * t[a:e]) for m in (1, 1.25, 1.5))
    au = tmp_path / 'synth.wav'
    sf.write(str(au), (y / np.abs(y).max() * 0.8).astype('float32'), sr)
    out = tmp_path / 'synth.nlmf'
    p = NP.make(au, out, title='合成', artist='', log=lambda s: None)
    q = nlmf.load(out)
    assert abs(q['bpm'] - 120) < 1 and q['analysis']['grid']['bpm'] == q['bpm'] and q['analysis']['structure']['sections']
    assert q['markers'] == NP.markers_from_analysis(q['analysis']) and p['graph']['song']['name'] == 'synth.wav'


def _nlm_pairs(n):
    ys = ROOT / 'cache' / 'yama_set.json'
    if not ys.exists():
        return []
    out = []
    for s in json.loads(ys.read_text(encoding='utf-8')):
        pj = ROOT / 'out' / 'yama' / f'{s["name"]}.nlmf'
        if pj.exists() and Path(s['src']).exists():
            out.append((pj, s['src']))
        if len(out) >= n:
            break
    return out


def test_same_as_projects_made_with_nlm():
    """NLM で作った元のプロジェクト（tools/nlm_project.py make）と、同じ解析の結果から作った物が全く同じ（保存の時刻と追加ノードの
    id のでたらめの4文字は除く）。曲と NLM で作った元のプロジェクトがある環境だけ。解析そのものが同じ答えになるのは test_song_analysis"""
    pairs = _nlm_pairs(8)
    if not pairs:
        pytest.skip('NLM で作った元のプロジェクトと音源が無い')
    for pj, src in pairs:
        nl = nlmf.load(pj)
        assert NP.compare(NP.build(src, nl['analysis']), nl) == [], pj.name


# ---- 音源の場所（NLM が開いただけで読める場所・2026-11-03 案 A） ----

def test_nlm_readable_same_rule_as_nlm():
    """NLM の native_paths._path_kind が 'local' の物だけ（ドライブ名から始まる絶対パス）。UNC・デバイスパス・相対は読めない"""
    for p in ('C:\\a.mp3', 'z:/music/a.mp3', 'D:\\音楽\\曲.flac'):
        assert NP.nlm_readable(p), p
    for p in ('\\\\NAS01\\home\\music\\a.mp3', '//nas/share/a.mp3', '\\\\?\\C:\\a.mp3', '\\\\.\\UNC\\nas\\s\\a.mp3', 'a.mp3', 'C:a.mp3', '\\a.mp3'):
        assert not NP.nlm_readable(p), p


def test_local_audio_copies_and_reuses(tmp_path, monkeypatch):
    """NLM が読めない場所の音源は stems/source/<同じ名前> へ写す（書きかけは残さない）・2回目は使い回す。読める場所ならそのまま"""
    au = _wav(tmp_path / 'nas' / '06.曲.wav')
    stems = tmp_path / 'cache' / '曲'
    assert NP.local_audio(au, stems) == au and not (stems / 'source').exists()   # 手元（ドライブ名から）＝写さない
    monkeypatch.setattr(NP, 'nlm_readable', lambda p: False)
    log = []
    got = NP.local_audio(au, stems, log=log.append)
    assert got == stems / 'source' / '06.曲.wav' and got.read_bytes() == au.read_bytes() and '写した' in log[-1]
    assert [p.name for p in (stems / 'source').iterdir()] == ['06.曲.wav']   # .part は残らない
    assert NP.local_audio(au, stems, log=log.append) == got and '写しを使う' in log[-1]


def test_import_copies_unreadable_audio_first(tmp_path, monkeypatch):
    """取り込み: NLM が読めない場所の音源は最初の段で写し、元のプロジェクトの音源の場所はその写し（NLM が開いただけで読む）"""
    ctx = _ctx(tmp_path)
    au = _wav(tmp_path / 'nas' / '06.曲.wav')
    monkeypatch.setattr(NP, 'nlm_readable', lambda p: False)
    steps = importer.plan(ctx, au, '曲', '曲', '', info={'soundfile': True})
    assert [s for s, _ in steps][:2] == ['音源を手元に写す', '音を分ける']
    (ctx.CACHE / '曲').mkdir()
    (ctx.CACHE / '曲' / 'separate.json').write_text('{}', encoding='utf-8')
    (ctx.CACHE / '曲' / 'analysis.json').write_text(json.dumps(_analysis()), encoding='utf-8')
    job = {'log': ''}
    steps[0][1](job)
    copy = ctx.CACHE / '曲' / 'source' / '06.曲.wav'
    assert copy.is_file() and '写した' in job['log']
    dict(steps)['元のプロジェクトを作る'](job)
    song = nlmf.load(ctx.OUT / '曲.nlmf')['graph']['song']
    assert song['nativePath'] == str(copy.resolve()) and song['name'] == '06.曲.wav'
    monkeypatch.setattr(NP, 'nlm_readable', lambda p: True)   # 読める場所なら段は増えない（今まで通り）
    assert [s for s, _ in importer.plan(ctx, au, '曲2', '曲2', '', info={'soundfile': True})][0] == '音を分ける'


# ---- アプリの曲の取り込み（app/importer.py） ----

def _ctx(tmp_path):
    out, cache = tmp_path / 'out', tmp_path / 'cache'
    out.mkdir()
    cache.mkdir()
    return types.SimpleNamespace(OUT=out, CACHE=cache, APP_KIND='intent-s1', JOBS={}, busy=lambda f: False)


def test_import_conflicts(tmp_path):
    """同じ名前の物: 結果のファイルがあれば取り込まない・元のプロジェクトと分けた音は中身を知らせて使い回す"""
    ctx = _ctx(tmp_path)
    assert importer.conflicts(ctx, '曲') == {'name': '曲', 'results': [], 'project': None, 'stems': None, 'blocked': False}
    NP.save(NP.build(_wav(tmp_path / 'x.wav'), _analysis(), title='曲', artist=''), ctx.OUT / '曲.nlmf')
    (ctx.CACHE / '曲').mkdir()
    (ctx.CACHE / '曲' / 'separate.json').write_text(json.dumps({'source': 'x.wav', 'seconds': 1.0, 'model': 'm'}), encoding='utf-8')
    c = importer.conflicts(ctx, '曲')
    assert c['project'] == {'file': '曲.nlmf', 'bpm': 128, 'lead': 215, 'song': 'x.wav', 'markers': 4} and c['stems']['source'] == 'x.wav'
    assert not c['blocked'] and not importer.conflicts(ctx, '曲2')['project']
    (ctx.OUT / '曲.intent-s1.nlmf').write_text('{}', encoding='utf-8')
    c = importer.conflicts(ctx, '曲')
    assert c['blocked'] and c['results'] == ['曲.intent-s1.nlmf']


def test_import_plan_reuses(tmp_path):
    """取り込みの段: 分けた音・元のプロジェクトがあれば使い回す（コマンドを動かさない）。カバー画像は使い回した時だけ別の段で結果のファイルへ。
    やめると次の段に入らない"""
    ctx = _ctx(tmp_path)
    au = _wav(tmp_path / 'x.wav')
    labels = [s for s, _ in importer.plan(ctx, au, '曲', '曲', '', info={'soundfile': True})]
    assert labels == ['音を分ける', '曲の解析', '元のプロジェクトを作る', '最初の譜面を作る']
    NP.save(NP.build(au, _analysis(), title='曲', artist=''), ctx.OUT / '曲.nlmf')
    (ctx.CACHE / '曲').mkdir()
    (ctx.CACHE / '曲' / 'separate.json').write_text('{}', encoding='utf-8')
    steps = importer.plan(ctx, au, '曲', '曲', '', cover=str(tmp_path / 'c.jpg'), info={'soundfile': True})
    assert [s for s, _ in steps][-1] == 'カバー画像を入れる'
    job = {'log': ''}
    for _, fn in steps[:3]:
        fn(job)
    assert job['log'].count('使い回') == 3
    job['cancel'] = True
    with pytest.raises(RuntimeError, match='やめた'):
        steps[3][1](job)


def test_progress_bar_collapse():
    """進み具合の棒（\\r で同じ行を書き直す）は最後の物だけ残す"""
    assert importer._collapse('a\n 10%|#\r 50%|##\r\nb') == 'a\n 50%|##\nb'
    assert importer._collapse('x\r') == 'x'
