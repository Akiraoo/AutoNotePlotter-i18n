"""Beat Saber へ直接書き出す部品（automap/bs_export.py＝NLM の exportMap の写し）の約束。

- 作り物の全部入りの譜面（tests/data/bs_export/rich.nlmf・rich2.nlmf: ボム・壁・アーク・チェーン・ライト・色のブースト・v2・テンポの変化・
  Music の切り貼り・標準外の項目・隠れた所・開いていない難易度・繋いでいない INFO のノード 等）を、見えない NLM（コミット 8b378d09）で
  書き出させた物（rich-nlm/・rich2-nlm/・tools/nlm_export_check.py --headless で作った・音源は読まない）とバイトまで同じ。
  NLM の版が上がったら作り直して比べる。
- JS と同じ数・文字の書き方・Math.round。書き出す印・足りない物・写していない物（BsExportError）・画面で入れた情報の書き込み。
- song.egg（無音追加・切り貼り・音量）のサンプルの位置（ffmpeg の adelay・atrim と同じ数）・.nlm-egg.json の印・やめる。
ネット・NLM・ffmpeg は使わない。譜面と音はここで作る作り物だけ。
"""
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from automap import bs_export as B
from automap import diffs as D
from automap import new_project, nlmf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'tests' / 'data' / 'bs_export'
sys.path.insert(0, str(ROOT / 'tools' / 'library_build'))


# ---- JS と同じ書き方 ----

@pytest.mark.parametrize('x,s', [
    (1.0, '1'), (0, '0'), (-0.0, '0'), (0.1, '0.1'), (3.3000000000000003, '3.3000000000000003'), (16.333333333333332, '16.333333333333332'),
    (1e21, '1e+21'), (1.5e21, '1.5e+21'), (1e20, '100000000000000000000'), (123456789012345680000.0, '123456789012345680000'),
    (1e-6, '0.000001'), (1.5e-6, '0.0000015'), (1e-7, '1e-7'), (2.5e-7, '2.5e-7'), (5e-324, '5e-324'), (-12.188, '-12.188'),
    (1770075664791.0369, '1770075664791.0369'), (978254796000.0, '978254796000'), (float('nan'), 'null'), (float('inf'), 'null'),
    (True, 'true'), (2 ** 40, '1099511627776'),
])
def test_js_num(x, s):
    assert B.js_num(x) == s


def test_js_dumps():
    v = {'b': [1.0, {'c': B.UNDEF, 'd': None}], '10': 1, 'a': '"\\\n　', '2': [], 'e': {}}
    assert B.js_dumps(v) == '{"2":[],"10":1,"b":[1,{"d":null}],"a":"\\"\\\\\\n　","e":{}}'   # 番号の形の名前が先（JS の物の順）
    assert B.js_dumps([B.UNDEF]) == '[null]'
    assert B.js_dumps({'a': [1, {'b': []}], 'c': {}}, 2) == '{\n  "a": [\n    1,\n    {\n      "b": []\n    }\n  ],\n  "c": {}\n}'
    plain = {'x': [1, 2.5, 'あ', None, True], 'y': {'z': -3}}
    assert B.js_dumps(plain, 2) == json.dumps(plain, ensure_ascii=False, indent=2)


@pytest.mark.parametrize('x,r', [(0.5, 1), (1.5, 2), (2.5, 3), (-0.5, 0), (-2.5, -2), (0.49999999999999994, 0), (12187.999999999998, 12188)])
def test_js_round(x, r):
    assert B.js_round(x) == r


# ---- NLM の書き出しとバイトまで同じ（作り物の全部入り） ----

def _expected(d):
    return {p.name: p.read_bytes().replace(b'\r\n', b'\n') for p in (DATA / d).iterdir()}   # 取り出す時に CRLF にされても比べられる


@pytest.mark.parametrize('name', ['rich', 'rich2'])
def test_same_as_nlm(name, tmp_path):
    proj = nlmf.load(DATA / f'{name}.nlmf')
    b = B.build(proj, 'all', audio=False, mark=False)   # NLM と同じ＝中身のある難易度を全部・音源は読まない・ANP の印なし
    exp = _expected(f'{name}-nlm')
    assert sorted(b['files']) == sorted(exp)
    for fn, data in b['files'].items():
        assert data == exp[fn], fn
    from common import bs_hash   # tools/library_build/common.py（BeatSaver の版の hash）
    for fn, data in exp.items():
        (tmp_path / fn).write_bytes(data)
    assert B.map_hash(b['files'], b['info']) == bs_hash(str(tmp_path))[0]


def test_anp_mark(tmp_path):
    """ANP の印（Info.dat の _customData._editors・写しと違う所）: 既定で入る・印の分だけが NLM の書き出しと違う・見分け"""
    proj = nlmf.load(DATA / 'rich.nlmf')
    exp = _expected('rich-nlm')
    b = B.build(proj, 'all', audio=False)
    info = json.loads(b['files']['Info.dat'])
    ver = B.anp_version()
    assert info['_customData'] == {'_editors': {'_lastEditedBy': B.ANP_EDITOR, B.ANP_EDITOR: {'version': ver}}}
    assert not ver.startswith('v') and B.anp_mark(info) == ver
    nlm = json.loads(exp['Info.dat'])
    assert B.anp_mark(nlm) is None and list(info)[:-1] == list(nlm) and {k: v for k, v in info.items() if k != '_customData'} == nlm
    assert all(b['files'][k] == exp[k] for k in exp if k != 'Info.dat')   # 難易度の .dat は同じ
    assert json.loads(B.build(proj, 'all', audio=False, mark='0.1.9')['files']['Info.dat'])['_customData']['_editors'][B.ANP_EDITOR] == {'version': '0.1.9'}
    # ほかのエディタの印は残す・ほかのエディタで直した後も ANP の項目が残っていれば印あり・v4 の形
    i2 = B.put_mark({'_customData': {'_contributors': [], '_editors': {'_lastEditedBy': 'ChroMapper', 'ChroMapper': {'version': '0.14'}}}}, '1.0.0')
    assert i2['_customData']['_contributors'] == [] and i2['_customData']['_editors']['ChroMapper'] == {'version': '0.14'}
    i2['_customData']['_editors']['_lastEditedBy'] = 'ChroMapper'
    assert B.anp_mark(i2) == '1.0.0'
    assert B.anp_mark({'version': '4.0.1', 'customData': {'editors': {'lastEditedBy': 'ChroMapper', B.ANP_EDITOR: {'version': '0.3.0'}}}}) == '0.3.0'
    assert B.anp_mark({'customData': {'editors': {'lastEditedBy': B.ANP_EDITOR}}}) == '?'
    for other in ({'_customData': {'_editors': {'_lastEditedBy': 'beatsage', 'beatsage': {'version': '2.0.0'}}}}, {'_customData': None},
                  {'_customData': {'_editors': 'x'}}, {}, None, []):
        assert B.anp_mark(other) is None


def test_export_check_ignores_mark(tmp_path):
    """tools/nlm_export_check.py: NLM の書き出しとは印なしで比べる（違いにしない）・ANP で書き出した物とは同じ版の印を入れて比べる"""
    sys.path.insert(0, str(ROOT / 'tools'))
    import nlm_export_check as XC
    nlm = tmp_path / 'nlm'
    nlm.mkdir()
    for fn, data in _expected('rich-nlm').items():
        (nlm / fn).write_bytes(data)
    logs = []
    assert XC.check(DATA / 'rich.nlmf', nlm, audio=False, say=logs.append) == 0, logs
    anp = tmp_path / 'anp'
    anp.mkdir()
    for fn, data in B.build(nlmf.load(DATA / 'rich.nlmf'), 'all', audio=False, mark='0.1.0')['files'].items():   # 前の版の ANP で書き出した物
        (anp / fn).write_bytes(data)
    logs = []
    assert XC.check(DATA / 'rich.nlmf', anp, audio=False, say=logs.append) == 0, logs
    assert any('ANP の印（版 0.1.0）' in s for s in logs) and XC.their_mark(nlm) is None


def test_rich_details():
    proj = nlmf.load(DATA / 'rich.nlmf')
    b = B.build(proj, 'all', audio=False)
    ep = json.loads(b['files']['ExpertPlusStandard.dat'])
    assert ep['colorNotes'][0]['b'] == 3.3000000000000003        # 開いていた難易度はクリップから（3.2＋0.1）
    assert json.loads(b['files']['HardStandard.dat'])['colorNotes'][0]['b'] == 3.3   # 開いていない難易度は保存されたフラット
    assert max(n['b'] for n in ep['colorNotes']) < 94.5 == round(b['ctx'].cut_b, 6)   # Music の終わりより後ろは書かない
    assert 'd' not in ep['colorNotes'][1]                         # 無い項目は書かない（JS の undefined）
    assert ep['burstSliders'][0] == {'customData': {'c': 3}, 'b': 8, 'c': 0, 'x': 1, 'y': 0, 'd': 8, 'tb': 8.5, 'tx': 1, 'ty': 1, 'sc': 5,
                                     's': 0.8}                    # エディタ専用の cpm・td は書かない
    assert {'a': 0, 'b': 8, 'x': 1, 'y': 0, 'c': 0, 'd': 0} in ep['colorNotes']   # チェーンの頭のノーツ（向き 8 は 0）
    info = json.loads(b['files']['Info.dat'])
    assert info['_songName'] == '作り物 "引用"\\ テスト'           # 最後に繋いだ曲情報のノード
    assert info['_previewStartTime'] == 7.5                       # 試聴のノード（元の音源の秒）＋無音追加
    assert B.build(proj, None, audio=False)['chosen'] == ['ExpertPlus']   # 既定は書き出す印の難易度だけ


def test_plan_contract():
    pl = B.plan(DATA / 'rich.nlmf')
    assert set(pl['info']) >= {'songName', 'songSubName', 'songAuthorName', 'levelAuthorName', 'bpm', 'previewStart', 'previewDuration',
                               'environment', 'cover'}
    assert pl['folder'] == 'rich-test' and pl['dest'] is None
    assert [r['diff'] for r in pl['diffs']] == ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus']
    assert [r['export'] for r in pl['diffs']] == [False, False, False, False, True]
    assert pl['info']['previewStart'] == 7.25 and pl['info']['environment'] == 'BigMirrorEnvironment'
    assert 'audio' in pl['missing'] and 'audio' in pl['blocking'] and 'cover' in pl['missing']
    assert any('印の無い難易度にもノーツ' in w for w in pl['warnings'])
    assert pl['unsupported'] == []


# ---- 作り物の曲で書き出す ----

def _png(w, h):
    raw = b''.join(b'\x00' + bytes([(x * 7 + y) % 256 for x in range(w)] * 3) for y in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


SR = 22050


def _noise(n, ch, seed=0):
    """作り物の音（雑音＋0.5 秒ごとの大きな印＝相互相関の山が鋭い）"""
    x = (np.random.default_rng(seed).standard_normal((n, ch)) * 0.05).astype(np.float32)
    for i in range(0, n, SR // 2):
        x[i:i + 300] *= 8
    return x


def _song(tmp_path, lead_ms=250, seconds=3.0):
    """作り物の曲（WAV）と、その元のプロジェクト（Expert+ に 8 ノーツ・書き出す印・フォルダ名）"""
    x = _noise(int(SR * seconds), 2)
    wav = tmp_path / 'song.wav'
    sf.write(wav, x, SR)
    proj = new_project.build(wav, {'grid': {'bpm': 120, 'leadMs': lead_ms}}, title='テスト曲', artist='だれか', diff='ExpertPlus')
    dk = D.key('ExpertPlus')
    nlmf.put_note_lane(proj, {dk: [{'beat': 0, 'len': 8, 'label': '自動', 'colHex': None,
                                    'notes': [{'beat': b, 'x': b % 4, 'y': 0, 'c': b % 2, 'd': 1} for b in range(8)]}]})
    D.set_export(proj, 'ExpertPlus')
    B.apply_info(proj, {'folder': 'test-song', 'levelAuthorName': 'ANP'})
    p = tmp_path / 'song.nlmf'
    new_project.save(proj, p)
    return p, wav, x


def _lag(want, path):
    """書いた song.egg が、期待する音（同じ長さ）より何サンプル遅れているか・相関・長さ"""
    y, sr = sf.read(path, dtype='float32', always_2d=True)
    a, b = want.mean(axis=1), y.mean(axis=1)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    cc = np.fft.irfft(np.conj(np.fft.rfft(a, n)) * np.fft.rfft(b, n), n)
    lags = np.r_[0:200, -199:0]
    v = np.r_[cc[:200], cc[n - 199:]]
    i = int(np.argmax(v))
    return int(lags[i]), float(v[i] / np.sqrt((a * a).sum() * (b * b).sum())), len(y), sr


def test_write_folder(tmp_path):
    p, wav, x = _song(tmp_path)
    before = p.read_bytes()
    dest = tmp_path / 'CustomLevels'
    dest.mkdir()
    logs = []
    r = B.write(p, dest, log=logs.append)
    d = dest / 'test-song'
    assert Path(r['dir']) == d and r['egg'] == 'written' and r['difficulties'] == [{'characteristic': 'Standard', 'name': 'ExpertPlus'}]
    assert {'song.egg', 'Info.dat', 'ExpertPlusStandard.dat'} <= {q.name for q in d.iterdir()} and (d / '.nlm-egg.json').is_file()
    assert p.read_bytes() == before                                 # .nlmf は書き換えない
    from common import bs_hash
    assert r['hash'] == bs_hash(str(d))[0]
    info = json.loads((d / 'Info.dat').read_text(encoding='utf-8'))
    assert (info['_songName'], info['_songAuthorName'], info['_levelAuthorName']) == ('テスト曲', 'だれか', 'ANP')
    assert B.anp_mark(info) == B.anp_version()                      # 書き出した譜面に ANP の印（型のライブラリが自分の物と見分ける）
    # 試聴の既定 12 秒は 3 秒の曲の外 → 最初に鳴る所の頭（無音追加 0.25 秒）＝NLM の eggOutSecOf と同じ
    assert info['_previewStartTime'] == 0.25 and info['_coverImageFilename'] == ''
    assert [b['_noteJumpMovementSpeed'] for b in info['_difficultyBeatmapSets'][0]['_difficultyBeatmaps']] == [16]
    lead = B.delay_samples(250, SR)
    assert lead == 5512                                             # ffmpeg の adelay と同じ切り捨て（5512.5 → 5512）
    lg, r, n, sr = _lag(np.concatenate([np.zeros((lead, 2), np.float32), x]), d / 'song.egg')
    assert (lg, sr, n) == (0, SR, lead + len(x)) and r > 0.8
    mark = json.loads((d / '.nlm-egg.json').read_text(encoding='utf-8'))
    assert list(mark) == ['name', 'size', 'mtime', 'leadInMs', 'segs', 'gainDb'] and mark['leadInMs'] == 250 and mark['segs'] is None
    # 2 回目: 音源・無音追加が同じなら song.egg を作り直さない。強制なら作り直す
    t0 = (d / 'song.egg').stat().st_mtime_ns
    assert B.write(p, dest)['egg'] == 'kept' and (d / 'song.egg').stat().st_mtime_ns == t0
    assert B.write(p, dest, force_egg=True)['egg'] == 'written'
    # 画面で入れた情報（.nlmf は書き換えない）・フォルダの指定
    r2 = B.write(p, dest, folder='other name!', changes={'levelAuthorName': '別の人', 'songSubName': 'サブ'})
    info2 = json.loads((dest / 'other name!' / 'Info.dat').read_text(encoding='utf-8'))
    assert info2['_levelAuthorName'] == '別の人' and info2['_songSubName'] == 'サブ' and r2['level_author'] == '別の人'
    assert p.read_bytes() == before
    assert not list(dest.rglob('*.part'))


def test_cover_and_fit(tmp_path):
    p, wav, x = _song(tmp_path)
    proj = nlmf.load(p)
    img = tmp_path / 'c.png'
    img.write_bytes(_png(256, 256))
    B.apply_info(proj, {'cover': str(img)})
    ig = proj['infoGraph']
    cid = B.connected(B.info_graph(proj), 'cover')
    assert ig['nodes'][cid]['data']['nativePath'] == str(img.resolve()) and proj['coverData'][cid].startswith('data:application/octet-stream;base64,')
    b = B.build(proj, audio=False)
    assert b['cover'] == ('cover.png', img.read_bytes()) and json.loads(b['files']['Info.dat'])['_coverImageFilename'] == 'cover.png'
    img.unlink()   # 画像のファイルが無くても、プロジェクトに入っている画像で書く（NLM と同じ）
    assert B.build(proj, audio=False)['cover'][1] == _png(256, 256)
    # 補正（data.fit）が要る画像は写していない＝書かない
    bad = tmp_path / 'wide.png'
    bad.write_bytes(_png(300, 200))
    B.apply_info(proj, {'cover': str(bad)})
    assert not B.plan_proj(proj)['unsupported'] and any('基準' in w for w in B.plan_proj(proj)['warnings'])
    ig['nodes'][cid]['data']['fit'] = {'mode': 'crop', 'bg': '#000000'}
    with pytest.raises(B.BsExportError, match='NLM で書き出して'):
        B.build(proj, audio=False)
    assert B.plan_proj(proj)['unsupported']
    good = tmp_path / 'sq.png'
    good.write_bytes(_png(256, 256))
    B.apply_info(proj, {'cover': str(good)})
    ig['nodes'][cid]['data']['fit'] = {'mode': 'crop'}
    assert B.build(proj, audio=False)['cover'][1] == good.read_bytes()   # 補正の設定があっても直す所が無ければそのまま（NLM と同じ）


def test_apply_info(tmp_path):
    p, wav, x = _song(tmp_path)
    proj = nlmf.load(p)
    done = B.apply_info(proj, {'songName': '新しい名前', 'songAuthorName': 'A', 'previewStart': 31.456, 'previewDuration': 0.2,
                               'environment': 'DefaultEnvironment', 'folder': '曲 Song-1 (仮)!', 'bpm': 120})
    assert 'bpm' not in done
    ig = proj['infoGraph']
    meta = ig['nodes'][B.connected(B.info_graph(proj), 'meta')]['data']
    prev = ig['nodes'][B.connected(B.info_graph(proj), 'prev')]['data']
    assert meta['name'] == '新しい名前' and proj['info']['_songName'] == '新しい名前'
    assert (prev['start'], prev['dur']) == (31.46, 0.5) and proj['info']['_previewStartTime'] == 31.46
    assert proj['graph']['out']['folderName'] == 'Song-1 (仮)!'.replace('仮', '') == ig['outs'][ig['activeOut']]['folderName']
    B.apply_info(proj, {'environment': 'BigMirrorEnvironment', 'diffs': {'ExpertPlus': False}})
    pl = B.plan_proj(proj)
    assert pl['info']['environment'] == 'BigMirrorEnvironment' and pl['info']['songName'] == '新しい名前'
    assert 'diffs' in pl['missing'] and D.mark_of(proj, 'ExpertPlus') == 0
    with pytest.raises(ValueError):
        B.apply_info(proj, {'bpm': 130})
    with pytest.raises(ValueError):
        B.apply_info(proj, {'mapper': 'x'})


def test_unsupported_and_missing(tmp_path):
    p, wav, x = _song(tmp_path)
    proj = nlmf.load(p)
    dk = D.key('ExpertPlus')
    st = proj['difficulties'][dk]
    st['notes'].append([40, 0, 0, 0, 1, 0])   # クリップの外の物（NLM は開く時に新しいクリップへ入れる＝写していない）
    with pytest.raises(B.BsExportError, match='クリップの外'):
        B.build(proj, audio=False)
    st['notes'].pop()
    # 開いていない難易度で、保存されたノーツとクリップが合わない（NLM の答えが開き方で変わる）
    proj['current'] = 'HardStandard.dat'
    st['notes'][0][1] = 3
    with pytest.raises(B.BsExportError, match='合わない'):
        B.build(proj, audio=False)
    proj2 = json.loads(json.dumps(proj))
    proj2['difficulties'][D.key('Hard')] = json.loads(json.dumps(st))
    proj2['difficulties'][D.key('Hard')]['name'] = 'HardStandard.dat'
    proj2['current'] = 'ExpertPlusStandard.dat'
    assert B.build(proj2, ['ExpertPlus'], audio=False)['chosen'] == ['ExpertPlus']   # 書かない難易度の問題では止めない
    st['notes'][0][1] = 0
    # 足りない物
    q = tmp_path / 'q.nlmf'
    proj['graph']['out']['folderName'] = ''
    proj['infoGraph']['outs'][proj['infoGraph']['activeOut']]['folderName'] = ''
    nlmf.save(proj, q)
    with pytest.raises(B.BsExportError, match='フォルダ名'):
        B.write(q, tmp_path)
    assert 'folder' in B.plan(q)['blocking']
    wav.unlink()
    pl = B.plan(p)
    assert 'audio' in pl['missing']
    with pytest.raises(B.BsExportError, match='音源のファイルが見つからない'):
        B.write(p, tmp_path)


def test_ffmpeg_missing(tmp_path, monkeypatch):
    p, wav, x = _song(tmp_path)
    proj = nlmf.load(p)
    fake = tmp_path / 'song.m4a'
    fake.write_bytes(b'\x00\x00\x00\x20ftypM4A ' + b'\x00' * 64)
    proj['graph']['song']['nativePath'] = str(fake)
    q = tmp_path / 'm4a.nlmf'
    nlmf.save(proj, q)
    monkeypatch.setattr(B.shutil, 'which', lambda name: None)
    pl = B.plan(q)
    assert 'ffmpeg' in pl['blocking']
    with pytest.raises(B.BsExportError, match='ffmpeg'):
        B.write(q, tmp_path)


def test_cancel(tmp_path):
    p, wav, x = _song(tmp_path, seconds=8)
    dest = tmp_path / 'out'
    dest.mkdir()
    with pytest.raises(B.BsExportCancelled):
        B.write(p, dest, cancel=lambda: True)
    assert not (dest / 'test-song' / 'Info.dat').exists() and not list(dest.rglob('*.part'))
    calls = []

    def later():
        calls.append(1)
        return len(calls) > 2   # song.egg を作っている途中でやめる
    with pytest.raises(B.BsExportCancelled):
        B.write(p, dest, cancel=later)
    d = dest / 'test-song'
    assert not (d / 'song.egg').exists() and not (d / 'Info.dat').exists() and not list(dest.rglob('*.part'))


def test_egg_segments(tmp_path):
    """Music の切り貼り・正の offset・Music の開始位置・音量（ffmpeg と同じサンプルの位置。ffmpeg との比べは tools/nlm_export_check.py）"""
    x = _noise(SR * 10, 1, seed=3)
    src = tmp_path / 's.wav'
    sf.write(src, x, SR)
    proj = {'bpm': 120, 'tempoParts': [{'beat': 8, 'bpm': 60}], 'musicBeat': 0, 'graph': {'song': {'offset': -0.1, 'gainDb': -6}},
            'musicSegs': [{'beat': 0, 'off': 1.05, 'dur': 2.5}, {'beat': 10, 'off': 5.0, 'dur': 1.5}]}
    t = B.Tempo(proj)
    egg = B.egg_plan(proj, t, 10.0)
    assert egg['lead_in_ms'] == 0 and egg['segs'] == [[0.95, 3.45, 0.0], [4.9, 6.4, 6.0]]   # 拍 10＝4 秒＋2 拍×1 秒
    out = tmp_path / 'e.ogg'
    total, sr = B.write_egg_sf(src, out, egg)
    a0, a1 = B.trim_sample(0.95, SR), B.trim_sample(3.45, SR)
    b0, b1 = B.trim_sample(4.9, SR), B.trim_sample(6.4, SR)
    o2 = B.delay_samples(6000, SR)
    assert total == max(a1 - a0, o2 + b1 - b0)
    want = np.zeros((total, 1), np.float32)
    want[:a1 - a0] += x[a0:a1]
    want[o2:o2 + b1 - b0] += x[b0:b1]
    lg, r, ln, _ = _lag(want, out)
    assert (lg, ln) == (0, total) and r > 0.8
    y, _ = sf.read(out, dtype='float32', always_2d=True)
    k = float(np.sqrt((y ** 2).mean() / (want ** 2).mean()))
    assert abs(k - 10 ** (-6 / 20)) < 0.05   # 音量 −6 dB（平均の大きさの比）
    # 分けていない・Music の開始位置が 4 拍＝2 秒＋無音追加 0.1 秒 → 先頭の無音 2100 ms
    p2 = {'bpm': 120, 'musicBeat': 4, 'graph': {'song': {'offset': -0.1}}}
    e2 = B.egg_plan(p2, B.Tempo(p2), 10.0)
    assert (e2['lead_in_ms'], e2['segs']) == (2100, None)
    # 正の offset（元の音源の頭を切る）は切り貼りとして書く
    p3 = {'bpm': 120, 'graph': {'song': {'offset': 0.3}}}
    assert B.egg_plan(p3, B.Tempo(p3), 10.0)['segs'] == [[0.3, 10.0, 0.0]]
    assert B.egg_out_sec(egg['pieces'], 2.0, 0) == pytest.approx(1.05) and B.egg_out_sec([], 12, 250) == 12.25


def test_egg_mark(tmp_path):
    f = tmp_path / 'a.flac'
    f.write_bytes(b'x' * 10)
    egg = {'lead_in_ms': 188, 'segs': None, 'gain_db': 0}
    m = B.egg_mark(f, egg)
    assert m['name'] == 'a.flac' and m['size'] == 10 and B.egg_same(json.loads(B.js_dumps(m)), m)
    assert not B.egg_same({**m, 'leadInMs': 200}, m) and not B.egg_same(None, m)
    assert B.egg_same({k: v for k, v in m.items() if k not in ('leadInMs',)}, {**m, 'leadInMs': 0})   # 無い＝0（NLM と同じ比べ方）


def test_sanitize_and_misc():
    assert B.sanitize_folder(' 曲A-b_c.(d)[e]&\'!+,/\\:  ') == "A-b_c.(d)[e]&'!+,"
    assert B.image_size(_png(300, 200)) == (300, 200)
    assert B.cover_needs_fix(256, 256, 'a.jpg') is False and B.cover_needs_fix(256, 256, 'a.webp') is True
    assert B.cover_out_name('Cover.JPG') == 'cover.jpg' and B.cover_out_name('cover') == 'cover.png'
    assert B.delay_samples(188, 44100) == 8290 and B.delay_samples(340, 44100) == 14994   # 本物の NLM の song.egg と同じ数
    assert B.trim_sample(0.29, 44100) == 12789 and B.trim_sample(1.0000005, 44100) == 44100


@pytest.mark.skipif('MP3' not in sf.available_formats(), reason='この soundfile は MP3 を書けない')
def test_mp3_frames(tmp_path):
    """MP3 の見出しの長さは見積もり＝最後まで読んで数える（Joy to the love で 26031 サンプル長く見えた）"""
    x = (np.random.default_rng(0).standard_normal((44100 * 2, 2)) * 0.1).astype(np.float32)
    p = tmp_path / 'a.mp3'
    sf.write(p, x, 44100, format='MP3')
    n, sr = B.audio_frames(p)
    with sf.SoundFile(p) as f:
        real = sum(len(b) for b in f.blocks(blocksize=65536))
    assert (n, sr) == (real, 44100)
