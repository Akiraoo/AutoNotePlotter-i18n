"""書き出しの「曲の音量を自動でそろえる」（app/bsexport.normalize・automap/loudness.py・2026-11-08）"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from automap import bs_export as B
from automap import diffs as D
from automap import loudness as L
from automap import new_project, nlmf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import bsexport  # noqa: E402

SR = 44100


def _quiet_song(tmp_path, db=-25.0, seconds=6.0):
    t = np.arange(int(SR * seconds)) / SR
    x = (10 ** (db / 20) * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    wav = tmp_path / 'quiet.wav'
    sf.write(wav, np.stack([x, x], axis=1), SR, subtype='FLOAT')
    proj = new_project.build(wav, {'grid': {'bpm': 120, 'leadMs': 0}}, title='静かな曲', artist='だれか', diff='ExpertPlus')
    dk = D.key('ExpertPlus')
    nlmf.put_note_lane(proj, {dk: [{'beat': 0, 'len': 8, 'label': '自動', 'colHex': None,
                                    'notes': [{'beat': b, 'x': b % 4, 'y': 0, 'c': b % 2, 'd': 1} for b in range(8)]}]})
    D.set_export(proj, 'ExpertPlus')
    B.apply_info(proj, {'folder': 'quiet-song', 'levelAuthorName': 'ANP'})
    p = tmp_path / 'quiet.nlmf'
    new_project.save(proj, p)
    return p


def test_normalize_raises_a_quiet_song_to_the_target(tmp_path):
    p = _quiet_song(tmp_path)
    db, m, why = bsexport.normalize(p, log=lambda s: None)
    assert abs(m['lufs'] - (-25)) <= 0.1 and abs(m['peak_db'] - (-25)) <= 0.05
    assert 15.8 <= db <= 16.0 and why == L.BY_TEXT['target']   # 0.1 dB で切り捨て（NLM と同じ）
    # 補正を曲のノードに書いて書き出すと、song.egg は目標の大きさになる（NLM と同じ焼き込み）
    proj = nlmf.load(p)
    B.song_node(proj)['gainDb'] = db
    nlmf.save(proj, p)
    dest = tmp_path / 'CustomLevels'
    dest.mkdir()
    r = B.write(p, dest)
    y, sr = sf.read(Path(r['dir']) / 'song.egg', dtype='float32', always_2d=True)
    got = L.measure([y[:, c] for c in range(y.shape[1])], sr)
    assert abs(got['lufs'] - L.AUTO_TARGET_LUFS) <= 0.3


def test_normalize_does_not_lower_a_loud_song_and_skips_a_missing_source(tmp_path):
    p = _quiet_song(tmp_path, db=-6.0)
    db, m, why = bsexport.normalize(p, log=lambda s: None)
    assert db == 0.0 and why == L.BY_TEXT['loud']
    proj = nlmf.load(p)
    B.song_node(proj)['nativePath'] = str(tmp_path / 'nothing.wav')
    nlmf.save(proj, p)
    logs = []
    assert bsexport.normalize(p, log=logs.append) is None and '見つからない' in logs[0]


def test_export_with_limiter_marks_and_rebuilds_the_egg(tmp_path):
    p = _quiet_song(tmp_path, db=-28.0)   # 正弦波: 平均 -28・ピーク -28 → 自動の補正 +19 で届く。リミッターは目標の手前から
    dest = tmp_path / 'CustomLevels'
    dest.mkdir()
    r = B.write(p, dest, limiter=(L.AUTO_TARGET_LUFS, L.AUTO_PEAK_DB))
    d = Path(r['dir'])
    import json
    mark = json.loads((d / '.nlm-egg.json').read_text(encoding='utf-8'))
    assert mark['limit'] == [L.AUTO_TARGET_LUFS, L.AUTO_PEAK_DB] and r['limiter'] and not r['limiter']['skipped']
    y, sr = sf.read(d / 'song.egg', dtype='float32', always_2d=True)
    got = L.measure([y[:, c] for c in range(y.shape[1])], sr)
    assert abs(got['lufs'] - L.AUTO_TARGET_LUFS) <= 0.4 and got['peak_db'] <= L.AUTO_PEAK_DB + 0.3   # OGG に変えた後
    assert B.write(p, dest, limiter=(L.AUTO_TARGET_LUFS, L.AUTO_PEAK_DB))['egg'] == 'kept'   # 同じ設定なら作り直さない
    r2 = B.write(p, dest)   # リミッターを外すと作り直す（印は NLM と同じ形に戻る）
    assert r2['egg'] == 'written' and 'limit' not in json.loads((d / '.nlm-egg.json').read_text(encoding='utf-8'))
