"""終わりだけが壊れた音源（最後のフレームが切れたまま ID3v1 のタグが続く MP3・2026-11-11 の取り込みで分ける段が落ちた）を読む約束。

- libsndfile はその形で「Unspecified internal error」を出して全体を読まない → 読めた所まで使う（automap/sfread・tools/separate.py の写し）。
  頭からの音は壊れていない物と 1 サンプルも違わない。途中が壊れた物（残りが TAIL_SEC 秒より長い）は今まで通りエラー。
- 使う所: 分ける段（tools/separate.py）・ffmpeg が無い PC の曲の解析（analyze_song.load＝librosa.load と同じ手順）・Beat Saber への
  書き出し（bs_export.audio_frames・song.egg）・音量の測り方（loudness.measure_file）。
音は作り物だけ（MP3 は soundfile の LAME で書く）。
"""
import importlib.util
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from automap import bs_export as B
from automap import loudness, sfread

ROOT = Path(__file__).resolve().parent.parent
SR = 44100
pytestmark = pytest.mark.skipif('MP3' not in sf.available_formats(), reason='この soundfile は MP3 を書けない')


def _separate():
    spec = importlib.util.spec_from_file_location('separate_under_test', ROOT / 'tools' / 'separate.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)   # torch・Demucs は main の中で読む＝ここでは要らない
    return m


@pytest.fixture(scope='module')
def mp3s(tmp_path_factory):
    """(壊れていない MP3, 終わりが壊れた MP3, 壊れていない物を読んだ音)。最後のフレームを途中で切って ID3v1 のタグ（128 バイト）を
    付ける＝libsndfile が読めなくなる形（どこで切ると読めなくなるかは LAME の版で変わり得るので探す）"""
    d = tmp_path_factory.mktemp('sfread')
    t = np.arange(SR * 8) / SR
    x = (np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 660 * t)], 1) * 0.3).astype(np.float32)
    ok = d / 'ok.mp3'
    sf.write(ok, x, SR, format='MP3')
    clean, _ = sf.read(ok, dtype='float32', always_2d=True)
    b = ok.read_bytes()
    bad = d / 'bad.mp3'
    for cut in range(150, 420, 10):
        bad.write_bytes(b[:-cut] + b'TAG' + b'\0' * 125)
        try:
            sf.read(bad, dtype='float32', always_2d=True)
        except sf.LibsndfileError:
            return ok, bad, clean
    pytest.skip('この libsndfile では終わりが切れた MP3 でも読めた（直すことが無い）')


def test_read_until_broken_tail(mp3s):
    ok, bad, clean = mp3s
    y, sr = sfread.read(bad)
    assert sr == SR and y.dtype == np.float32 and y.shape[1] == 2
    assert len(clean) - 3 * 1152 < len(y) < len(clean)        # 切れた最後のフレームの辺りだけ短い
    assert np.array_equal(y, clean[:len(y)])                   # 頭からの音は 1 サンプルも違わない
    assert sfread.frames(bad) == (len(y), SR)
    y2, sr2 = sfread.read(ok)                                  # 壊れていない物は sf.read のまま
    assert sr2 == SR and np.array_equal(y2, clean) and sfread.frames(ok) == (len(clean), SR)


def test_separate_same_rule(mp3s):
    ok, bad, clean = mp3s
    sep = _separate()
    y, sr, cut = sep.read_audio(bad)
    assert cut and sr == SR and np.array_equal(y, sfread.read(bad)[0])
    y2, _, cut2 = sep.read_audio(ok)
    assert not cut2 and np.array_equal(y2, clean)
    assert (sep.TAIL_SEC, sep.STEP) == (sfread.TAIL_SEC, sfread.STEP)


class _Broken:
    """10 秒と言いながら 1 秒で読めなくなる音源（途中が壊れた物の代わり）"""
    frames, samplerate, channels = SR * 10, SR, 2

    def __init__(self, *a, **k):
        self.n = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, k, dtype='float32', always_2d=True):
        if self.n >= SR:
            raise sf.LibsndfileError(29)
        self.n += k
        return np.zeros((k, 2), np.float32)


def test_broken_in_middle_still_fails(monkeypatch):
    def fail(*a, **k):
        raise sf.LibsndfileError(29)
    monkeypatch.setattr(sf, 'read', fail)
    monkeypatch.setattr(sf, 'SoundFile', _Broken)
    with pytest.raises(sf.LibsndfileError):
        sfread.read('x.mp3')
    with pytest.raises(sf.LibsndfileError):
        sfread.frames('x.mp3')
    with pytest.raises(sf.LibsndfileError):
        _separate().read_audio(Path('x.mp3'))
    monkeypatch.setattr(_Broken, 'frames', SR + 2 * SR)       # 残りが TAIL_SEC 未満なら終わりが壊れているだけ
    y, sr = sfread.read('x.mp3')
    assert sr == SR and SR <= len(y) < SR + sfread.STEP


def test_bs_export_and_loudness(mp3s, tmp_path):
    _, bad, _ = mp3s
    n = len(sfread.read(bad)[0])
    assert B.audio_frames(bad) == (n, SR)
    out = tmp_path / 'song.egg'
    total, sr = B.write_egg_sf(bad, out, {'lead_in_ms': 100, 'segs': None, 'gain_db': 0})
    assert sr == SR and total == B.delay_samples(100, SR) + n and sf.info(str(out)).frames == total
    m = loudness.measure_file(bad)
    assert np.isfinite(m['lufs'])


def test_analysis_without_ffmpeg(mp3s, monkeypatch):
    """ffmpeg が無い PC の曲の解析: 壊れていない物は librosa.load と同じ答え（手順が同じ）・終わりが壊れた物も読める"""
    import librosa
    from automap import analyze_song as A
    ok, bad, _ = mp3s
    want, _ = librosa.load(str(ok), sr=A.SR, mono=True)
    assert np.array_equal(A._tail_load(ok), want)
    monkeypatch.setattr(shutil, 'which', lambda *a, **k: None)
    y = A.load(bad)
    assert y.ndim == 1 and len(want) - A.SR * 0.1 < len(y) < len(want)
    assert A._tail_load(ROOT / 'tests' / 'no-such-file.mp3') is None
