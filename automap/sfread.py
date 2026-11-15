"""音源を soundfile で読む（終わりだけが壊れた音源も・2026-11-11）。

iTunes で作った MP3 などに、最後のフレームが途中で切れたまま後ろに ID3v1 のタグが続く物がある（取り込みで分ける段が落ちた）。
ブラウザ（NLM）と ffmpeg はそこまでを鳴らすが、libsndfile（1.2.2）は「Unspecified internal error」で全体の読み込みを諦める。
そこで読めなかった時は 1 フレームずつ読み直し、読めなくなったのが終わり近く（見出しの長さの残り TAIL_SEC 秒未満）なら
そこまでの音を使う（ffmpeg と同じ音・同じ位置で、切れた最後の 1 フレーム＝26ms の分だけ短い）。途中が壊れた物は今まで通りエラー。
tools/separate.py にも同じ決まりの物がある（MIT・本体を読み込めないので自前で持つ）。
"""
TAIL_SEC = 3.0   # 見出しの長さ（MP3 は見積もり＝0.6〜0.8 秒ずれた例がある）の残りがこれ未満なら「終わりが壊れている」
STEP = 1152      # 読み直す単位（MP3 の 1 フレーム）＝読めずに捨てる分が小さい


def _tail_safe(f, sf, dtype):
    """開いた音源を頭から STEP ずつ（読めなくなったのが終わり近くならそこで終わる・途中なら読めないエラーのまま）"""
    n = 0
    while True:
        try:
            b = f.read(STEP, dtype=dtype, always_2d=True)
        except sf.LibsndfileError:
            if f.frames - n > TAIL_SEC * f.samplerate:
                raise
            return
        if not len(b):
            return
        n += len(b)
        yield b


def read(path, dtype='float32'):
    """sf.read(path, dtype=dtype, always_2d=True) と同じ (音 (サンプル, チャンネル), 周波数)。終わりが壊れた音源は読めた所まで"""
    import soundfile as sf
    try:
        return sf.read(str(path), dtype=dtype, always_2d=True)
    except sf.LibsndfileError:
        pass
    import numpy as np
    with sf.SoundFile(str(path)) as f:
        parts = list(_tail_safe(f, sf, dtype))
        return (np.concatenate(parts) if parts else np.zeros((0, f.channels), dtype)), f.samplerate


def frames(path, block=1 << 16):
    """最後まで読んで数えた (サンプル数, 周波数)。終わりが壊れた音源は読めた所まで（その数までなら読める）"""
    import soundfile as sf
    try:
        with sf.SoundFile(str(path)) as f:
            n = 0
            while True:
                b = f.read(block, dtype='float32', always_2d=True)
                if not len(b):
                    return n, f.samplerate
                n += len(b)
    except sf.LibsndfileError:
        pass
    with sf.SoundFile(str(path)) as f:
        return sum(len(b) for b in _tail_safe(f, sf, 'float32')), f.samplerate
