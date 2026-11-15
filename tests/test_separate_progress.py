"""音を分ける計算の進み具合（tools/separate.py の Progress・2026-11-11 利用者「何度も 100% になったり残りが何度も 0 秒になるのが
わかりにくい・全体の進み具合が見えればよい・個別の計算は括弧書きで、全体のうちの何個が終わったか」）の約束。

- htdemucs_ft は 4 つのモデル × 2 回ずらし＝8 回の計算。Demucs の棒は回ごとに 0→100% をくり返した → 全体の割合を 1 行に。
- 全体の割合は下がらない・100% は終わった時の 1 行だけ・括弧の中は「8 回の計算のうち k 回済み・k+1 回目 n%」。
- 行は \\r で書き直す（取り込みの記録は行ごとに最後の物だけ＝app/importer.py の _collapse）。
Demucs の callback の形（model_idx_in_bag・shift_idx・segment_offset・state・audio_length・models）を作り物で流す（torch・Demucs は要らない）。
"""
import importlib.util
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import importer  # noqa: E402


def _separate():
    spec = importlib.util.spec_from_file_location('separate_under_test', ROOT / 'tools' / 'separate.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)   # torch・Demucs は main の中で読む＝ここでは要らない
    return m


def _run(models=4, shifts=2, length=10000, stride=300, every=0.0, sec=1.0):
    """Demucs の apply_model と同じ順（モデル → ずらし → 区切り）で callback を呼ぶ → (書いた物, Progress)。1 区切り sec 秒"""
    S = _separate()
    out, t = io.StringIO(), [100.0]
    p = S.Progress(shifts, out=out, clock=lambda: t[0], every=every)
    for mi in range(models):
        for si in range(max(1, shifts)):
            shifted = length + 7 * (si + 1)   # ずらした分だけ曲より少し長い（Demucs の shifted の長さ）
            for off in range(0, shifted, stride):
                d = {'model_idx_in_bag': mi, 'shift_idx': si, 'segment_offset': off, 'audio_length': length, 'models': models}
                p(dict(d, state='start'))
                t[0] += sec
                p(dict(d, state='end'))
    p.done()
    return out.getvalue(), p


def _lines(text):
    return [s.rstrip() for s in re.split(r'[\r\n]+', text) if s.strip()]


def test_whole_progress_goes_up_once():
    text, p = _run()
    ls = _lines(text)
    assert ls[0] == '曲の全体を 8 回計算して平均する（4 つのモデル・それぞれ 2 回ずらして）'
    prog = [l for l in ls[1:] if l.startswith('音を分ける ')]
    pct = [int(re.match(r'音を分ける (\d+)%', l).group(1)) for l in prog]
    assert pct == sorted(pct)                                  # 下がらない
    assert pct.count(100) == 1 and pct[-1] == 100              # 100% は終わった時の 1 回だけ
    assert prog[-1] == '音を分ける 100%（8 回の計算が済んだ・4:32 かかった）'   # 34 区切り × 8 回 × 1 秒
    assert not any('残り約 0:00' in l for l in prog)          # 残り 0 をくり返さない
    few = [i for i, l in enumerate(prog) if '残りわずか' in l]
    assert few and few[0] >= 0.95 * len(prog)                  # 「わずか」は終わり際だけ
    # 括弧の中: 何回済み・今の回の進み
    assert any(re.search(r'（8 回の計算のうち 3 回済み・4 回目 \d+%）$', l) for l in prog)
    assert any(l.endswith('（8 回の計算のうち 8 回済み）') for l in prog)
    assert p.frac == 1.0


def test_remaining_time_counts_down():
    text, _ = _run()
    rem = []
    for l in _lines(text):
        m = re.search(r'残り約 (\d+):(\d\d)', l)
        if m:
            rem.append(int(m.group(1)) * 60 + int(m.group(2)))
    assert len(rem) > 100 and rem[0] > rem[len(rem) // 2] > rem[-1]
    # 回の切れ目で 0 に戻らない（回の最後の区切りは曲の終わりの少しだけなので少し揺れる・その分は許す）
    assert max(b - a for a, b in zip(rem, rem[1:])) <= 0.15 * rem[0]
    assert min(rem[: len(rem) * 3 // 4]) > 30


def test_one_model_no_shift_has_no_parentheses():
    text, _ = _run(models=1, shifts=0)
    ls = _lines(text)
    assert ls[0] == '曲の全体を 1 回計算する'
    assert all('回の計算のうち' not in l for l in ls[1:-1])
    assert re.match(r'音を分ける 100%（0:\d\d かかった）$', ls[-1])


def test_cpu_shifts_one():
    text, _ = _run(models=4, shifts=1)
    ls = _lines(text)
    assert ls[0] == '曲の全体を 4 回計算して平均する（4 つのモデル）'
    assert any(re.search(r'（4 回の計算のうち 1 回済み・2 回目 \d+%）$', l) for l in ls)


def test_throttle_and_log_collapse():
    """間引いても回の切れ目は書く・取り込みの記録（_collapse）には最後の 1 行だけが残る"""
    text, _ = _run(every=10.0)
    log = importer._collapse('$ separate.py\n分ける準備（…）\n' + text)
    rows = log.split('\n')
    assert rows[2] == '曲の全体を 8 回計算して平均する（4 つのモデル・それぞれ 2 回ずらして）'
    assert rows[3].rstrip().startswith('音を分ける 100%') and rows[4] == ''
    # 途中（終わる前）の記録でも、最後の行が今の全体の割合
    mid = text[:text.index('（8 回の計算のうち 5 回済み')]
    last = importer._collapse(mid).split('\n')[-1]
    assert re.match(r'音を分ける \d+%', last)
    starts = [l for l in _lines(text) if 'のうち' in l and '回目 0%' in l]
    assert len(starts) >= 7   # 2〜8 回目の頭は間引いても書く


def test_bad_callback_does_not_stop():
    S = _separate()
    p = S.Progress(2, out=io.StringIO())
    p({'models': 'x'})   # 形が違っても例外を出さない（分けるのを止めない）
    p.done()
