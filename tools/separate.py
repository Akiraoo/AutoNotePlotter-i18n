# SPDX-License-Identifier: MIT
# このファイルだけ MIT License（リポジトリのほかは GPLv3）。音を分ける部品（PyTorch の NVIDIA・Intel の部品）と組み合わせて動かすため
# （2026-11-03 利用者・THIRD_PARTY_NOTICES.md の 5 節）。このファイルは本体（GPLv3）のコードを読み込まない＝本体のコードを足さないこと。
#
# Copyright (c) 2026 Auto Note Plotter contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
# ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH
# THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""曲を「歌・ドラム・ベース・その他」の音に分ける（学習済みの音源分離 Demucs）。曲ごとに1回だけ動かし、結果を保存する。

重い部品（PyTorch・Demucs）は打ち込みの環境と分けて `.venv-sep` に入れてある:
  py -3.14 -m venv .venv-sep
  .venv-sep/Scripts/python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
  .venv-sep/Scripts/python.exe -m pip install numpy soundfile demucs

使い方: .venv-sep/Scripts/python.exe tools/separate.py <音源> [--model htdemucs_ft] [--out cache/<音源の名前>]
        まとめて: tools/separate.py --list <一覧>（1行に「音源<TAB>出力のフォルダ」・モデルの読み込みは1回・separate.json がある曲は飛ばす）
出力: <out>/vocals.flac・drums.flac・bass.flac・other.flac（元の音源と同じ長さ・44.1kHz（元が 48kHz 等でも）・ステレオ）と separate.json（使ったモデル等）。
分離そのものは学習済みのモデル（AI）だが、出てくるのは音だけ。どこに打つかは規則と計算で決める（docs/方針.md）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
# 終わりだけが壊れた音源（最後のフレームが切れたまま ID3v1 のタグが続く MP3 等）は読めた所まで使う（2026-11-11・automap/sfread.py と
# 同じ決まり＝このファイルは本体を読み込めないので自前で持つ）。見出しの長さの残りがこれ未満で読めなくなったら「終わりが壊れている」
TAIL_SEC = 3.0
STEP = 1152   # 読み直す単位（MP3 の 1 フレーム）


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('audio', nargs='?')
    p.add_argument('--list', help='1行に「音源<TAB>出力のフォルダ」の一覧（まとめて分ける）')
    p.add_argument('--model', default='htdemucs_ft', help='htdemucs_ft（4つのモデルの平均・既定）／htdemucs（速い）')
    p.add_argument('--shifts', type=int, default=2, help='少しずつずらして平均する回数（多いほど良く遅い）')
    p.add_argument('--out')
    a = p.parse_args(argv)
    print(f'分ける準備（部品とモデル {a.model} を読み込む）', flush=True)
    import torch
    from demucs.api import Separator
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    if a.list:
        jobs = [ln.split('\t') for ln in Path(a.list).read_text(encoding='utf-8').splitlines() if '\t' in ln]
        sep = Separator(model=a.model, device=dev, shifts=a.shifts, progress=False)
        for i, (src, out) in enumerate(jobs):
            if (Path(out) / 'separate.json').exists():
                continue
            try:
                info = one(sep, Path(src), Path(out), a, dev)
                print(f'{i + 1}/{len(jobs)} {out} {info["took"]}s', flush=True)
            except Exception as e:   # 読めない音源などは飛ばして続ける
                print(f'{i + 1}/{len(jobs)} {out} 失敗: {e}', flush=True)
        return
    src = Path(a.audio)
    out = Path(a.out) if a.out else ROOT / 'cache' / src.stem
    prog = Progress(a.shifts)   # Demucs の棒（progress=True）は計算の回ごとに 0→100% をくり返すので使わない
    sep = Separator(model=a.model, device=dev, shifts=a.shifts, progress=False, callback=prog)
    print(json.dumps(one(sep, src, out, a, dev, prog), ensure_ascii=False))


def _mmss(s):
    s = max(0, int(round(s)))
    return f'{s // 60}:{s % 60:02d}'


class Progress:
    """音を分ける計算の全体の進み具合を 1 行で（Demucs の Separator の callback・2026-11-11 利用者「何度も 100% になったり残りが何度も
    0 秒になるのがわかりにくい・全体の進み具合が見えればよい・個別の計算は括弧書きで、全体のうちの何個が終わったか」）。
    htdemucs_ft は 4 つのモデルの平均で、モデルごとに shifts 回ずらして曲の全体を計算する（4 × 2＝8 回・CPU の shifts 1 は 4 回）。
    Demucs の棒（tqdm）は 1 回ごとに 0→100% になり、そのたびに残りが 0 になっていた。
    → 「音を分ける 38%・残り約 0:35（8 回の計算のうち 3 回済み・4 回目 60%）」を \\r で同じ行に書き直す（取り込みの記録は行ごとに最後の
    物だけ残す＝app/importer.py の _collapse・画面は今の段の最後の行を出す＝importer.js の lastLine）。全体の割合＝(済んだ回＋今の回の
    進み)÷回の数（下がらない・100% は終わった時の 1 回だけ）・残り＝最初の区切りからの時間と全体の割合から。表示の失敗で分けるのを止めない"""

    def __init__(self, shifts, out=None, clock=time.monotonic, every=0.5):
        self.shifts = max(1, int(shifts or 0))
        self.out, self.clock, self.every = out, clock, every
        self.t0 = None       # 最初の区切りを始めた時刻（モデルの読み込みは入れない）
        self.runs = 1        # 計算の回の数（モデルの数 × ずらす回数）
        self.run = -1        # 今の回（0 から）
        self.prev = None     # 今の回で最後に始めた区切りの位置（フレーム）
        self.stride = 0      # 区切りの間（フレーム・回をまたいで使う）
        self.frac = 0.0      # 全体の割合（下げない）
        self.shown = None    # 最後に書いた時刻
        self.shown_run = -1  # 最後に書いた回
        self.width = 0

    def _write(self, s):
        o = self.out or sys.stdout
        o.write(s)
        o.flush()

    def __call__(self, d):
        try:
            self._step(d)
        except Exception:   # noqa: BLE001  （進み具合を出せなくても分けるのは続ける）
            pass

    def _step(self, d):
        now = self.clock()
        models = max(1, int(d.get('models') or 1))
        runs = models * self.shifts
        run = int(d.get('model_idx_in_bag') or 0) * self.shifts + int(d.get('shift_idx') or 0)
        length = max(1, int(d.get('audio_length') or 1))
        off = int(d.get('segment_offset') or 0)
        if self.t0 is None:
            self.t0, self.runs = now, runs
            how = [f'{models} つのモデル'] if models > 1 else []
            how += [f'それぞれ {self.shifts} 回ずらして'] if self.shifts > 1 else []
            self._write((f'曲の全体を {runs} 回計算して平均する（{"・".join(how)}）' if runs > 1 else '曲の全体を 1 回計算する') + '\n')
        if run != self.run:
            self.run, self.prev = run, None
        if d.get('state') == 'start':
            if self.prev is not None and off > self.prev:
                self.stride = off - self.prev
            self.prev = off
            f = off / length
        else:   # 区切りを終えた＝次の区切りの頭まで（ずらした分だけ曲より少し長いので 1 で止める）
            f = (off + self.stride) / length
        f = min(1.0, max(0.0, f))
        self.frac = max(self.frac, min(1.0, (run + f) / runs))
        if not (run != self.shown_run or f >= 1 or self.shown is None or now - self.shown >= self.every):
            return
        self.shown, self.shown_run = now, run
        el = now - self.t0
        if self.frac >= 0.02 and el >= 2:
            rem = el * (1 - self.frac) / self.frac
            left = '残りわずか' if rem < 5 else f'残り約 {_mmss(rem)}'
        else:
            left = '残りを測っている'
        text = f'音を分ける {min(99, int(self.frac * 100))}%・{left}'
        if runs > 1:
            text += (f'（{runs} 回の計算のうち {run + 1} 回済み）' if f >= 1
                     else f'（{runs} 回の計算のうち {run} 回済み・{run + 1} 回目 {int(f * 100)}%）')
        self.width = max(self.width, len(text))
        self._write('\r' + text.ljust(self.width))

    def done(self):
        """計算が済んだ（separate_tensor の後）: 100% の行で閉じる"""
        if self.t0 is None:
            return
        took = _mmss(self.clock() - self.t0)
        text = f'音を分ける 100%（{self.runs} 回の計算が済んだ・{took} かかった）' if self.runs > 1 else f'音を分ける 100%（{took} かかった）'
        self._write('\r' + text.ljust(self.width) + '\n')


def read_audio(src):
    """(音 (サンプル, チャンネル), 周波数, 終わりが壊れていたか)。sf.read で読めなかった時は 1 フレームずつ読み直し、読めなくなったのが
    終わり近くならそこまで（ffmpeg と同じ音・同じ位置で、切れた最後のフレームの分だけ短い）・途中が壊れた物は読めないエラーのまま"""
    try:
        wav, sr = sf.read(str(src), dtype='float32', always_2d=True)
        return wav, sr, False
    except sf.LibsndfileError:
        pass
    parts, n, cut = [], 0, False
    with sf.SoundFile(str(src)) as f:
        while True:
            try:
                b = f.read(STEP, dtype='float32', always_2d=True)
            except sf.LibsndfileError:
                if f.frames - n > TAIL_SEC * f.samplerate:
                    raise
                cut = True
                break
            if not len(b):
                break
            parts.append(b)
            n += len(b)
        wav = np.concatenate(parts) if parts else np.zeros((0, f.channels), np.float32)
        return wav, f.samplerate, cut


def one(sep, src, out, a, dev, prog=None):
    import torch
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    wav, sr, cut = read_audio(src)   # (サンプル, チャンネル)
    if cut:
        print(f'音源の終わりが壊れていて最後まで読めないので、読めた所（{len(wav) / sr:.2f} 秒）まで使う: {src.name}', flush=True)
    x = torch.from_numpy(np.ascontiguousarray(wav.T))
    _, stems = sep.separate_tensor(x, sr)
    if prog is not None:
        prog.done()
        print('分けた音を書いている（歌・ドラム・ベース・その他）', flush=True)
    for name, y in stems.items():   # 分けた音はモデルの標本化の周波数（44.1kHz）で書く（元が 48kHz 等でも、separate_tensor が変換する）
        y = y.cpu().numpy().T
        sf.write(str(out / f'{name}.flac'), np.clip(y, -1, 1), sep.samplerate, subtype='PCM_16')
    info = {'source': src.name, 'model': a.model, 'shifts': a.shifts, 'device': dev, 'sr': sep.samplerate, 'source_sr': sr,
            'seconds': round(len(wav) / sr, 3), 'took': round(time.time() - t0, 1), 'stems': sorted(stems)}
    (out / 'separate.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    return info


if __name__ == '__main__':
    main()
