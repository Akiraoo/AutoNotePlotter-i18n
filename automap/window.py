"""選んだ区間だけ作り直す時（compose --only）の流れの計算を、区間の前後だけで行う（docs/アプリ仕様.md 9 節・2026-11-09）。

区間の外は結果のファイルの今の譜面のまま＝残したノーツで、流れの計算には決めたノーツ（__main__._kept_hits・重み KEPT_FIX_W）として
入るだけ。それでも曲の全部の打点で計算し、1 回の作り直しで何度も呼ぶ（同じ振りの入りの合わせ直し・決めの留め直し）ので、区間だけの
作り直しに 10〜26 秒かかった（利用者「一部だけの作り替えが遅いのは気になっていた」）。

窓＝区間の前後 MARGIN 拍の打点（後ろから前を見る印＝続けて左右反転の 1 セット前・短い往復の始まり・受け渡しの反転の始まり・前のセットを
片手に の始まりの相手が窓の前にあれば、そこまで広げる。残したノーツでない打点は全部窓に入れる）:
- 窓の頭の前の残したノーツの最後の振りから始める（flow.init_from）。窓の中の区間の前の残したノーツは決めたノーツのまま入れる
  ＝直近の割合（指数移動平均）と振りの向きの位相が温まった状態で区間に入る。
- 窓の中の区間の後ろの残したノーツも決めたノーツのまま入れる＝つなぎ目（振りの向き・NLM の振りの警告）が計算の中で見える。
- 窓の外の答えは残したノーツそのもの（決めた置き方）。曲の全部の答えの形は全部で計算した時と同じ（同じ振り・決め・報告が読む）。
区間の中の答えは全部で計算した時と同じとは限らない（別の案の 1 つになる・利用者が了承）。--only が無い時は使わない（答えは 1 ビットも
変わらない）。比べ・測り用に、環境変数 AUTOMAP_ONLY_FULL=1 なら全部で計算する（前の作り）。"""
import os
from bisect import bisect_left

from . import flow

# 区間の前後に入れる残したノーツの拍（4 小節）。4 曲 × 5 区間で 0・4・8・16 を比べ、つなぎ目の NLM の振りの警告が全部で計算した時より
# 増えなかったのは 16 だけ（8 は BURN の同じ振りの区間で 1・4 は 2・0 は 6）。時間は 8 と 0.2〜0.7 秒しか違わない
MARGIN = 16.0
EPS = 1e-6


def full_wanted():
    """全部で計算する逃げ道（比べ・測り用・AUTOMAP_ONLY_FULL=1）"""
    return os.environ.get('AUTOMAP_ONLY_FULL', '') not in ('', '0')


def _refs(ev):
    """この打点が流れの計算の中で後ろから前を見る相手の拍（窓に入っていないと印が効かない）"""
    out = []
    if ev.echo:
        out.append(ev.beat - ev.echo)   # 続けて左右反転: 1 セット前の同じ拍
    if ev.loop is not None:
        out.append(ev.loop)             # 短い往復: 往復の区間の始まりから同じ手の 2 つ前
    if ev.hoflex is not None:
        out.append(ev.hoflex[0])        # 左右反転の受け渡し: 始まりの拍から数える
    if ev.erun is not None:
        out.append(ev.erun)             # 前のセットを片手に: 同じ印の 1・2 番目の打点
    return out


def bounds(events, kept, only, margin=MARGIN):
    """窓の打点の番号 [i0, i1)。kept＝打点ごとの「残したノーツか」"""
    lo, hi = only[0] - margin, only[1] + margin
    for ev, k in zip(events, kept):
        if k:
            continue
        lo = min(lo, ev.beat, *_refs(ev))
        hi = max(hi, ev.beat + EPS * 10)
    beats = [e.beat for e in events]
    return bisect_left(beats, lo - EPS), bisect_left(beats, hi - EPS)


def _fixed_notes(evs):
    return [{'beat': ev.beat, 'x': x, 'y': y, 'c': c, 'd': d} for ev in evs for c, (x, y, d) in sorted(ev.fix.items())]


def generate(events, hits, style, only, tempo, init=None, pre=(), margin=MARGIN):
    """区間の前後だけで流れの計算 → (曲の全部のノーツ [{beat, x, y, c, d}], 減点の合計（窓の中）, 窓の拍 (始まり, 終わり))。
    hits＝events と同じ並びの打点（残したノーツは kept）。init＝曲の頭から計算する時の始まり（「ここから」の flow.init_from）・
    pre＝「ここから」より前の残したノーツ（窓の頭の振りを引き継ぐ元に足す）。窓の外の打点が残したノーツでない（決めた置き方が無い）
    時は全部で計算する"""
    kept = [bool(getattr(h, 'kept', False)) for h in hits]
    i0, i1 = bounds(events, kept, only, margin)
    outside = events[:i0] + events[i1:]
    if any(not ev.fix for ev in outside):   # 起こらないはず（残したノーツでない打点は窓に入れる）
        gen, cost = flow.generate(events, style, init=init)
        return gen, cost, (events[0].beat if events else only[0], events[-1].beat if events else only[1])
    if i0 > 0:
        init = flow.init_from(list(pre) + _fixed_notes(events[:i0]), tempo)
    got, cost = flow.generate(events[i0:i1], style, init=init)
    out = _fixed_notes(events[:i0]) + got + _fixed_notes(events[i1:])
    out.sort(key=lambda n: (n['beat'], n['c']))
    span = (events[i0].beat, events[i1 - 1].beat) if i1 > i0 else tuple(only)
    return out, cost, span
