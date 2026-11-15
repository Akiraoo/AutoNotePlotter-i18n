"""リズム（検討の層の ①）: 分けた音の打点の候補から、どこに打つかを決める。

- 打点の候補（audio.py）を拍にして目盛りへ寄せる。ドラムのずれ（立ち上がりの山と目盛りの差の中央値）を測って差し引く
  ＝プロジェクトの無音追加が耳で合わせた値（ドラムの山より少し早い）でも、寄せる先の目盛りを間違えない。
- 歌のある区間は歌の音符に打つ。寄せ方は `snap_vocals`: 歌の始まりの遅れ（円の平均）を差し引き、1/4 拍の目盛りのうち
  「近さ＋弱い位置ほど減点（半拍・1/4 拍。速い曲 45ms・遅い曲 15ms・`vocal_prior_ms`）」が一番小さい所へ（迷ったら強い位置）。人の譜面 7 曲
  （BPM 120〜208）で、人のノーツと同じ拍に乗る割合が 61% → 77%（拾えた割合 88% → 90%）。1/4 拍に一番近い所へ寄せていた時は、
  速い曲（1/4 拍が 86ms）で歌が目盛りの間に散らばり、隣の目盛りへ外していた（曲C で利用者が「歌の所がずれる」）。
  前の音符と続いていて区切りの谷が浅い音符（伸ばしの中の高さの揺れ・ビブラート・合唱の高さの取り違えで切れた所）は位置があやふやなので
  半拍まで（1/4 拍の位置に置かない）、寄せた先でドラム・楽器が鳴っていなければ前の音符にまとめる（`merge_phantoms`・2026-11-08）。
  歌の無い区間（イントロ・間奏・アウトロ）はドラムとその他の楽器（ギター等）の強い打点に打つ。
- 区間（まとまり）とフレーズは曲の流れの表（form.sections・フレーズはまとまり1つ）。密度と両手は form.plan
  （0＝1/2 拍の目盛りの強い打点だけ・1＝全部・2＝全部＋強い所を両手同時に）。区間の名前とフレーズの順で決める試作1〜3 の決め方
  （息継ぎでフレーズを区切る・区間の名前で密度の段階）は除いた（docs/除いた物.md）。
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio

CACHE_VER = 6   # 5＝谷の浅い続きの歌の音符は半拍まで・楽器の鳴っていない物は前の音符にまとめる（2026-11-08）・6＝歌の打点に weak（谷の浅い続き）を残す（2026-11-15・vocal_pull が寄せ直す時に使う）


def vocal_prior_ms(bpm):
    """歌の打点を寄せる時、半拍・1/4 拍の弱い位置ほど足す減点（ms）。1/4 拍が 90ms 以下の速い曲は 45ms（人の譜面 7 曲で一番合う）、
    110ms 以上の曲は 15ms（1/4 拍の細かさを残す。曲B（1/4 拍 116ms）は 1/4 拍の並びが「特徴的で正解」と利用者）、その間はなめらかに"""
    q = 60 / bpm / 4
    t = min(1.0, max(0.0, (0.110 - q) / 0.020))
    return 15 + 30 * t


@dataclass
class Onset:
    beat: float          # 目盛りに寄せた拍
    raw: float           # 寄せる前の拍（ずれを差し引いた後）
    kind: str            # vocal / kick / snare / hihat / other / bass
    s: float             # 強さ 0〜1
    midi: float = 0.0    # 歌の高さ
    length: float = 0.0  # 歌の長さ（拍）
    weak: bool = False   # 歌: 前の音符と続いていて区切りの谷が浅い（位置があやふや＝1/4 拍の位置に置かない・snap_vocals の coarse）


def vocal_lag(raw, grids=(2, 4), min_coh=0.08):
    """歌の始まりの、目盛りに対する平均の遅れ（拍）。目盛りの間を一周とみた円の平均＝ずれが大きくても平均が取れる。
    1/2 拍と 1/4 拍のうち歌がよく集まる方の目盛りで測る（速い曲は 1/4 拍の目盛りの間に散らばり、16 分で歌う曲は拍の頭・裏と
    1/4 拍の位置に半々に分かれて 1/2 拍の目盛りでは集まらない＝曲D で 1/2 拍で測って意味の無い値が出た）。どちらにも集まらなければ 0"""
    raw = np.asarray(raw, float)
    if not len(raw):
        return 0.0
    best = (0.0, 0.0)
    for g in grids:
        c = np.mean(np.exp(2j * np.pi * ((raw * g) % 1.0)))
        if abs(c) > best[0]:
            best = (abs(c), float(np.angle(c) / (2 * np.pi) / g))
    return best[1] if best[0] >= min_coh else 0.0


WEAK_DIP_DB = 3.0   # 前の音符と続いていて、区切りの谷がこれより浅い歌の音符＝位置があやふや（audio._dip）


def snap_vocals(raw, bpm, prior_ms=None, coarse=None, drums=None, pull=0.0, reach=None):
    """歌の始まり（拍・遅れを差し引いた後）→ 1/4 拍の目盛り。近さ（拍）＋弱さ（拍の頭 0・半拍 1・1/4 拍 2）× 減点 が一番小さい所。
    coarse（真偽の配列）の音符は 1/4 拍の位置に置かない（半拍まで）＝前の音符と続いていて谷の浅い区切り（`WEAK_DIP_DB`）。
    人の譜面 6 曲で、こうした区切りは人のノーツと同じ拍が 64%・1/4 拍ずれた所にだけ人のノーツがある割合が 18%（はっきりした区切りは
    84%・5%）で、半拍までにすると 1/4 拍ずれが 4% に（遅め〜中くらいの曲で効き、速い曲はもともと半拍に寄るので変わらない・2026-11-08）。
    drums（キック・スネアの寄せる前の拍・小さい順）と pull（拍）があれば、その目盛りの DRUM_TOL_MS 以内でキック・スネアが鳴っている
    候補の点を pull だけ下げる＝迷った打点はドラムの鳴る目盛りへ（vocal_pull・2026-11-15）。reach（拍）があれば、下げるのは寄せる前の
    位置からそれより近い候補だけ（coarse の打点は 2 倍＝1/4 拍なら両隣の目盛り・半拍までの打点は両隣の半拍）＝強く寄せても目盛りを
    飛び越えては動かさない。pull 0 なら前と同じ答え"""
    x = np.asarray(raw, float)
    lam = (vocal_prior_ms(bpm) if prior_ms is None else prior_ms) / 1000 * bpm / 60
    no_q = np.zeros(len(x), bool) if coarse is None else np.asarray(coarse, bool)
    base = np.floor(x * 4) / 4
    best, bc = None, None
    for k in (-1, 0, 1, 2):
        c = base + k / 4
        lvl = np.where(np.abs(c - np.round(c)) < 1e-6, 0, np.where(np.abs(c * 2 - np.round(c * 2)) < 1e-6, 1, 2))
        cost = np.abs(x - c) + lam * lvl + np.where(no_q & (lvl == 2), 9.0, 0.0)
        if pull and drums is not None and len(drums):
            bonus = pull * _has_drum(drums, c, DRUM_TOL_MS / 1000 * bpm / 60)
            if reach is not None:
                bonus = bonus * (np.abs(x - c) < np.where(no_q, 2 * reach, reach))
            cost = cost - bonus
        if best is None:
            best, bc = c.copy(), cost
        else:
            m = cost < bc
            best[m], bc[m] = c[m], cost[m]
    return best


# ---- 歌を拍に寄せる（2026-11-15 利用者「曲の中でなんか確実に拍がずれてるなみたいな感じのタイミングが時々ある」・The Cup of Life の 0:14〜0:29） ----
# 歌の立ち上がりが拍の目盛りからばらつく所（掛け声・重ねた声・響きで立ち上がりがぼやける・歌い方がゆるい）では、1/4 拍の目盛りの真ん中
# あたりで迷った打点が前後へ 30〜60ms 外れ、ドラム（目盛りにぴったり）とも歌とも合わない所にノーツが立った。迷った打点だけを、キック・
# スネアが鳴っている目盛りへ寄せる（ノーツの数・細かさは変えない＝1/4 拍まで・利用者「細かい区切りで拍を作るのはできるだけ避けたい」）。
# 区間の指示「歌を拍に寄せる」（intent の vsnap）と、歌がばらつく区間の自動（loose_spans）で効かせる。
# 強さは手元の人の譜面 148 曲（うちランク譜面 88・tools/eval_vocal.py --pull）で決めた（docs/方針.md 6.34）。
DRUM_PULL = 0.35      # 自動: 迷った打点をドラムの鳴る目盛りへ寄せる強さ（1/4 拍の割合＝127 BPM で 41ms ぶんドラムの方を近いとみる）
INTENT_PULL = 1.0     # 指示の区間: 両隣の目盛りのどちらかでキック・スネアが鳴っていれば必ずそちらへ（1/4 拍ぶん・利用者「ドラム優先」）
INTENT_REACH = 0.25   # 指示の区間で寄せる先は寄せる前の位置から 1/4 拍より近い目盛り（両隣）だけ
DRUM_TOL_MS = 30      # 目盛りに「ドラムが鳴っている」とみる近さ
DRUM_MIN_S = 0.3      # 数えるキック・スネアの強さの下限
LOOSE_BEATS = 8       # ばらつきを測る窓（拍・半分ずつ重ねる）
LOOSE_MIN = 6         # 窓の中の歌の打点（強さ 0.3 以上）がこれより少なければ測らない
LOOSE_FRAC = 0.8      # 1/4 拍の目盛りまでの距離の中央値が、でたらめに散らばった時（1/16 拍）のこの割合以上なら「ばらつく」


def _has_drum(drums, c, tol):
    """目盛りの点（配列）ごとに、tol 以内にドラムが鳴っているか（1.0／0.0）"""
    i = np.clip(np.searchsorted(drums, c), 1, len(drums) - 1)
    d = np.minimum(np.abs(drums[i - 1] - c), np.abs(drums[i] - c))
    if len(drums) == 1:
        d = np.abs(drums[0] - c)
    return (d <= tol).astype(float)


def loose_spans(vocal, frac=LOOSE_FRAC, win=LOOSE_BEATS, min_n=LOOSE_MIN):
    """歌の打点（Onset）→ 歌の立ち上がりが目盛りからばらつく区間 [(拍の始まり, 終わり)]（win 拍の窓を半分ずつ重ねて測り、続いた窓はまとめる）"""
    raw = np.array(sorted(o.raw for o in vocal if o.s >= 0.3))
    if len(raw) < min_n:
        return []
    out = []
    a = np.floor(raw[0] / (win / 2)) * (win / 2)
    while a < raw[-1]:
        r = raw[(raw >= a) & (raw < a + win)]
        if len(r) >= min_n and np.median(np.abs(r - np.round(r * 4) / 4)) >= frac / 16:
            if out and a <= out[-1][1]:
                out[-1][1] = a + win
            else:
                out.append([float(a), float(a + win)])
        a += win / 2
    return [tuple(x) for x in out]


def _minus(spans, cuts):
    """区間 [(a, b)] から cuts の区間を除いた残り（小さい順・空は捨てる）"""
    out = []
    for a, b in spans:
        parts = [(a, b)]
        for x, y in cuts:
            parts = [q for p0, p1 in parts for q in ((p0, min(p1, x)), (max(p0, y), p1)) if q[1] - q[0] > 1e-6]
        out += parts
    return out


def vocal_pull(ons, bpm, regions=(), auto=True, frac=LOOSE_FRAC, skip=()):
    """打点の候補 → (歌の打点を寄せ直した写し, 報告 [(拍の始まり, 終わり, 'intent'|'auto', 動いた数, 歌の打点の数)])。
    regions＝区間の指示「歌を拍に寄せる」の区間（強く寄せる＝INTENT_PULL・両隣の目盛りまで）・auto＝歌がばらつく区間も（loose_spans・
    DRUM_PULL・指示の区間と skip＝区間の指示「寄せない」の区間は除く）。寄せ直すのは歌の打点だけ（区間の中の今の拍で選ぶ・寄せる前の拍
    から snap_vocals に drums と pull を渡して寄せ直す）。動いた打点が同じ拍に重なった歌の打点は 1 つに（強い方・長さは長い方）＝ノーツは
    増やさない。キック・スネアが無い曲・区間が無ければそのまま返す"""
    voc = list(ons.get('vocal') or [])
    drums = np.array(sorted(o.raw for k in ('kick', 'snare') for o in ons.get(k) or [] if o.s >= DRUM_MIN_S))
    inten = sorted((float(a), float(b)) for a, b in regions or ())
    spans = [(a, b, 'intent') for a, b in inten]
    if auto:
        spans += [(a, b, 'auto') for a, b in _minus(loose_spans(voc, frac), inten + [(float(x), float(y)) for x, y in skip or ()])]
    spans.sort()
    if not voc or not len(drums) or not spans:
        return ons, []
    raw, weak = np.array([o.raw for o in voc]), [o.weak for o in voc]
    nb = {}
    if any(k == 'auto' for *_, k in spans):
        nb['auto'] = snap_vocals(raw, bpm, coarse=weak, drums=drums, pull=DRUM_PULL / 4)
    if inten:
        nb['intent'] = snap_vocals(raw, bpm, coarse=weak, drums=drums, pull=INTENT_PULL / 4, reach=INTENT_REACH)
    rep = {sp: [0, 0] for sp in spans}
    new, moved = [], set()
    for i, o in enumerate(voc):
        sp = next((sp for sp in spans if sp[0] <= o.beat < sp[1]), None)
        if sp is not None:
            rep[sp][1] += 1
            b = float(nb[sp[2]][i])
            if abs(b - o.beat) > 1e-6:
                rep[sp][0] += 1
                o = Onset(b, o.raw, o.kind, o.s, o.midi, o.length, o.weak)
                moved.add(round(b * 48))
        new.append(o)
    out_v, at = [], {}
    for o in new:   # 動いた打点が同じ拍に重なったら 1 つに（前からの重なりはそのまま）
        k = round(o.beat * 48)
        if k in moved and k in at:
            p = out_v[at[k]]
            keep = o if o.s > p.s else p
            out_v[at[k]] = Onset(keep.beat, keep.raw, keep.kind, keep.s, keep.midi, max(p.length, o.length), keep.weak)
            continue
        at.setdefault(k, len(out_v))
        out_v.append(o)
    out = dict(ons)
    out['vocal'] = sorted(out_v, key=lambda o: o.beat)
    return out, [(a, b, kind, n[0], n[1]) for (a, b, kind), n in rep.items()]


def pull_text(rep):
    """vocal_pull の報告 → 報告の 1 行（「- 」の後ろ・寄せる区間が無ければ None）。指示の区間は 1 つずつ・自動は区間の数と合計"""
    if not rep:
        return None
    fb = lambda x: f'{x:g}'
    parts = [f'指示 拍 {fb(a)}〜{fb(b)} {m}/{n}' for a, b, k, m, n in rep if k == 'intent']
    au = [(m, n) for a, b, k, m, n in rep if k == 'auto' and n]
    if au:
        parts.append(f'自動（歌が目盛りからばらつく {len(au)} 区間） {sum(m for m, _ in au)}/{sum(n for _, n in au)}')
    return '歌を拍に寄せた（迷った歌の打点をキック・スネアの鳴る目盛りへ・動いた数/歌の打点）: ' + ('・'.join(parts) or '寄せる歌の打点なし')


def _bass(stem_dir, to_b, bias, bpm, lst=None):
    """ベースの打点（意思入れの「元にする音: ベース」だけで使う）→ ([Onset], 遅れの ms)。遅れは歌と同じく円の平均で測る（曲ごとに 7〜45ms・
    曲C で 22ms）。寄せ方も歌と同じ（迷ったら強い位置へ）。lst＝先に測った audio.bass_onsets（analyze が同時に測る）"""
    p = Path(stem_dir) / 'bass.flac'
    if not p.exists():
        return [], 0.0
    if lst is None:
        lst = audio.bass_onsets(p)
    raw = np.array([to_b(t) - bias for t, _ in lst])
    s = np.array([v for _, v in lst])
    lag = float(np.clip(vocal_lag(raw[s >= 0.3]) if len(raw) else 0.0, -0.05 * bpm / 60, 0.05 * bpm / 60))
    q = snap_vocals(raw - lag, bpm) if len(raw) else []
    return [Onset(float(a), float(r - lag), 'bass', float(v)) for a, r, v in zip(q, raw, s)], round(lag * 60 / bpm * 1000, 1)


def merge_phantoms(vocal, weak, backing, min_s=0.3):
    """谷の浅い続きの区切りの歌の音符（weak）のうち、寄せた拍（1/4 拍の升）でドラム・楽器（強さ min_s 以上）が何も鳴り始めていない
    物は、前の音符の続きにまとめる（打点にしない・前の音符の長さを延ばす＝フレーズの切れ目は変わらない）。伸ばした合唱の高さの揺れ・
    取り違えで細切れになった音符がこれで、The Cup of Life の頭で半端な拍にノーツが並んだ（2026-11-08 利用者「ずれている感じ」）。
    人の譜面 6 曲で、こうした音符は人のノーツと同じ拍が 35%（楽器が鳴っている物は 84%）"""
    cells = {round(o.beat * 4) / 4 for o in backing if o.s >= min_s}
    out = []
    for o, w in zip(vocal, weak):
        if w and out and round(o.beat * 4) / 4 not in cells:
            p = out[-1]
            p.length = max(p.length, o.raw + o.length - p.raw)
            continue
        out.append(o)
    return out


def _other_peaks(path):
    """その他の音（ギター等）の立ち上がりの山（コマの番号, 強さ＝95 番目の値で 1 にそろえた物）"""
    nov = audio.band_flux(audio.stft_mag(audio.load_mono(path)), 150, 5000)
    idx, s = audio.pick_peaks(nov, gap=0.08, k=1.2)
    return idx, s / (np.percentile(s, 95) + 1e-9)


def _bias(beats, grid):
    d = [b - round(b * grid) / grid for b in beats]
    d = [x for x in d if abs(x) < 0.25 / grid]
    return float(np.median(d)) if d else 0.0


def analyze(stem_dir, bpm, lead_ms, force=False):
    """分けた音のフォルダ（tools/separate.py の出力）→ {kind: [Onset]}。結果は stem_dir/onsets.json に保存して使い回す。"""
    stem_dir = Path(stem_dir)
    cp = stem_dir / 'onsets.json'
    key = {'ver': CACHE_VER, 'bpm': bpm, 'lead_ms': lead_ms}
    if cp.exists() and not force:
        d = json.loads(cp.read_text(encoding='utf-8'))
        if d.get('key') == key:
            out = {k: [Onset(**o) for o in v] for k, v in d['onsets'].items()}
            if 'bass' not in out:   # ベースは後から足した（ほかを測り直さずに足す）
                bias = d['info']['drum_bias_ms'] / 1000 * bpm / 60
                out['bass'], d['info']['bass_bias_ms'] = _bass(stem_dir, lambda t: audio.sec_to_beat(t, bpm, lead_ms), bias, bpm)
                d['onsets']['bass'] = [o.__dict__ for o in out['bass']]
                cp.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
            return out, d['info']
    to_b = lambda t: audio.sec_to_beat(t, bpm, lead_ms)
    # 分けた音ごとの重い所（読む・スペクトル・歌の高さ）は互いに関係しないので同時に（numpy・soundfile は GIL を外して動く・
    # 桃源郷で 5.9 → 3.3 秒・答えは同じ＝同じ関数を同じ入力で・2026-11-11）。拍への直し（ドラムのずれ）は後でそろえてから
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        f_vn = ex.submit(audio.vocal_notes, stem_dir / 'vocals.flac')
        f_other = ex.submit(_other_peaks, stem_dir / 'other.flac')
        f_bass = ex.submit(audio.bass_onsets, stem_dir / 'bass.flac') if (stem_dir / 'bass.flac').exists() else None
        dr = audio.drum_onsets(stem_dir / 'drums.flac')
        vn, (o_idx, o_s) = f_vn.result(), f_other.result()
        bass_lst = f_bass.result() if f_bass else None
    strong = [to_b(t) for k in ('kick', 'snare') for t, s in dr[k] if s > 0.4]
    bias = _bias(strong, 2)
    out = {}
    for k, lst in dr.items():
        ons = []
        for t, s in lst:
            r = to_b(t) - bias
            q, g, _ = audio.snap(r, (4, 3))
            ons.append(Onset(q, r, k, s))
        out[k] = ons
    r0 = np.array([to_b(x['t0']) - bias for x in vn])
    vb = vocal_lag([r for r, x in zip(r0, vn) if x['s'] >= 0.3])
    vb = float(np.clip(vb, -0.04 * bpm / 60, 0.04 * bpm / 60))   # ±40ms まで（歌の無い曲などで外れた値を使わない）
    weak = [bool(x.get('cont')) and x.get('dip', 99.0) < WEAK_DIP_DB for x in vn]
    snapped = snap_vocals(r0 - vb, bpm, coarse=weak) if len(r0) else []
    vocal = [Onset(float(q), float(r - vb), 'vocal', x['s'], x['midi'], (x['t1'] - x['t0']) * bpm / 60, w)
             for q, r, x, w in zip(snapped, r0, vn, weak)]
    out['other'] = []
    for i, v in zip(o_idx, o_s):
        r = to_b(i / audio.FPS) - bias
        q, g, _ = audio.snap(r, (4, 3))
        out['other'].append(Onset(q, r, 'other', float(min(1, v))))
    out['vocal'] = merge_phantoms(vocal, weak, [o for k in ('kick', 'snare', 'hihat', 'other') for o in out[k]])
    out['bass'], bass_ms = _bass(stem_dir, to_b, bias, bpm, lst=bass_lst)
    info = {'drum_bias_ms': round(bias * 60 / bpm * 1000, 1), 'vocal_bias_ms': round(vb * 60 / bpm * 1000, 1), 'bass_bias_ms': bass_ms}
    cp.write_text(json.dumps({'key': key, 'info': info, 'onsets': {k: [o.__dict__ for o in v] for k, v in out.items()}},
                             ensure_ascii=False), encoding='utf-8')
    return out, info


@dataclass
class Section:
    name: str
    b0: float
    b1: float
    vocal: bool = False
    nth: int = 0          # 同じ名前の何回目か（0 から）
    last: bool = False    # 同じ名前の最後か
    phrases: list = field(default_factory=list)   # [(拍の始まり, 終わり)]
    tags: list = field(default_factory=list)      # 人の書き込み [(拍, '★'/'静'/'ドラム'/'歌', 次のマーカーの拍)]


TAGS = ('★', '静', 'ドラム', '歌', 'ここから')   # マーカーの名前に入れる人の書き込み（区間は切らない）。ここから＝その拍から後ろだけ作り直す


def parse_marker(name):
    """マーカーの名前 → (区間の名前（書き込みだけなら ''）, [書き込み])。例: '★サビ' → ('サビ', ['★'])・'ドラム' → ('', ['ドラム'])。
    「※」で始まる名前は人のコメント（区間を切らない・報告に出す）→ ('', ['※…'])"""
    name, tags = str(name or '').strip(), []
    if name.startswith('※'):
        return '', [name]
    for t in TAGS:
        if t in name:
            tags.append(t)
            name = name.replace(t, '')
    return name.strip(), tags


def sections_from_markers(markers, end_beat):
    """マーカー → 区間。名前が書き込み（★・静・ドラム・歌）だけのマーカーは区間を切らず、入っている区間の tags に入れる
    （ドラム・歌は、そのマーカーから次のマーカーまで）。名前が無いマーカーは区間の頭として扱う"""
    ms = sorted((m for m in markers if isinstance(m.get('beat'), (int, float))), key=lambda m: m['beat'])
    heads = [(float(m['beat']), *parse_marker(m.get('name'))) for m in ms]
    secs = [(b, nm or f'区間{i + 1}') for i, (b, nm, tags) in enumerate(heads) if nm or not tags]
    out = []
    for i, (b, nm) in enumerate(secs):
        b1 = secs[i + 1][0] if i + 1 < len(secs) else end_beat
        if b1 > b:
            out.append(Section(nm, b, float(b1)))
    for i, (b, nm, tags) in enumerate(heads):
        until = heads[i + 1][0] if i + 1 < len(heads) else float(end_beat)
        for s in out:
            if s.b0 - 1e-6 <= b < s.b1 - 1e-6:
                s.tags += [(b, t, until) for t in tags]
    seen = {}
    for s in out:
        s.nth = seen.get(s.name, 0)
        seen[s.name] = s.nth + 1
    for s in out:
        s.last = s.nth == seen[s.name] - 1
    return out


def _in(o, s):
    return s.b0 - 1e-6 <= o.beat < s.b1 - 1e-6


def regen_from(markers):
    """「ここから」のマーカーの拍（一番前の物・無ければ None）。その拍より前は結果のファイルのまま残し、後ろだけ作り直す"""
    bs = [float(m['beat']) for m in markers or [] if isinstance(m.get('beat'), (int, float)) and 'ここから' in parse_marker(m.get('name'))[1]]
    return min(bs) if bs else None


def phrase_tag(sec, p0, p1):
    """フレーズの中に人の ★・静 があればそれ"""
    for b, t, _ in sec.tags:
        if t in ('★', '静') and p0 - 1e-6 <= b < p1 - 1e-6:
            return t
    return None


def drum_ranges(sec):
    """人が「ドラム」と書いた範囲（そこから次のマーカーまで、歌でなくドラムと楽器に打つ）"""
    return [(b, until) for b, t, until in sec.tags if t == 'ドラム']


@dataclass
class Hit:
    beat: float
    hands: int            # 1＝片手・2＝両手同時
    sec_i: int            # 区間の番号
    phr_i: int            # 区間の中のフレーズの番号
    src: str              # 何の打点か（vocal / kick …）
    s: float
    midi: float = 0.0
    accent: bool = False  # 山の音（人の ★ のフレーズの頭）


def choose_hits(onsets, sections, plan):
    """区間ごとに打点を選ぶ → [Hit]（拍の順・同じ拍は1つ）。sections＝form.sections（歌の有無・フレーズが決まっている）。
    plan＝{区間の番号: {'lvl': 密度の段階, 'sparse': 1拍に1つまで, 'big': フレーズの頭を両手に, 'dbl': 両手を足す所（0 無し・1 小節の頭・
    2 小節の頭と真ん中。キックかシンバルのある所）}}（曲の流れの表・form.plan）。人の ★・静 が優先"""
    vocals = sorted(onsets['vocal'], key=lambda o: o.beat)
    drums = sorted(onsets['kick'] + onsets['snare'], key=lambda o: o.beat)
    other = sorted(onsets['other'], key=lambda o: o.beat)
    crash = {round(o.beat * 4) / 4: o.s for o in onsets['hihat'] if o.s > 0.8}
    kick = {round(o.beat * 4) / 4: o.s for o in onsets['kick']}
    hits = []
    for si, sec in enumerate(sections):
        vs = [v for v in vocals if _in(v, sec)]
        for pk, (p0, p1) in enumerate(sec.phrases):
            lvl, sparse, big, dbl = plan[si]['lvl'], plan[si]['sparse'], plan[si]['big'], plan[si].get('dbl', 0)   # 曲の流れの表の段階
            tag = phrase_tag(sec, p0, p1)
            if tag:   # 人の書き込みが優先（★＝盛り上げ・静＝抑える）
                lvl, sparse = (2, False) if tag == '★' else (0, sparse)
            inp = lambda o: p0 - 1e-6 <= o.beat < p1 - 1e-6
            dr = drum_ranges(sec)
            in_drum = lambda o: any(a - 1e-6 <= o.beat < b - 1e-6 for a, b in dr)
            if sec.vocal:
                cand = [v for v in vs if inp(v) and v.s >= 0.3 and not in_drum(v)]
                if lvl == 0:
                    first = cand[0].beat if cand else None
                    cand = [v for v in cand if v.beat == first or (abs(v.beat * 2 - round(v.beat * 2)) < 1e-6 and v.s >= 0.5)]
                # 歌の間（2 拍以上）はドラムで埋める（1 拍の目盛りの強い打点）
                fill = []
                marks = [p0] + [v.beat for v in cand] + [p1]
                for a, b in zip(marks, marks[1:]):
                    if b - a >= 2:
                        fill += [d for d in drums if a + 0.99 <= d.beat <= b - 0.99 and d.s >= 0.5 and abs(d.beat - round(d.beat)) < 1e-6]
                cand = cand + fill + [o for o in drums + other if inp(o) and in_drum(o) and o.s >= (0.5 if o.kind != 'other' else 0.6)
                                      and abs(o.beat * 2 - round(o.beat * 2)) < 1e-6]
            else:
                grid = 1 if lvl == 0 else 2
                cand = [o for o in drums + other if inp(o) and o.s >= (0.5 if o.kind != 'other' else 0.6)
                        and abs(o.beat * grid - round(o.beat * grid)) < 1e-6]
            seen = {}
            for o in sorted(cand, key=lambda o: (o.beat, -o.s)):
                if o.beat not in seen:
                    seen[o.beat] = o
            ph = sorted(seen.values(), key=lambda o: o.beat)
            # 近すぎる打点を間引く（密度 0 は 1/2 拍・それ以外は 1/4 拍より近い物）
            mind = 1.0 if sparse else 0.5 if lvl == 0 else 0.25
            kept = []
            for o in ph:
                if kept and o.beat - kept[-1].beat < mind - 1e-6:
                    continue
                kept.append(o)
            for j, o in enumerate(kept):
                hands = 1
                q = round(o.beat * 4) / 4
                strong_down = abs(o.beat - round(o.beat)) < 1e-6 and (kick.get(q, 0) > 0.6 or crash.get(q, 0) > 0)
                near_kick = max(kick.get(q + dq, 0) for dq in (-0.25, 0, 0.25))
                bar_head = abs((o.beat - sec.b0) % 4) < 1e-6
                half_bar = abs((o.beat - sec.b0) % 4 - 2) < 1e-6
                hit_or_crash = near_kick > 0.5 or crash.get(q, 0) > 0
                if j == 0 and big and near_kick > 0.5:
                    hands = 2          # サビ（盛り上がりの段階 2 以上）のフレーズの頭
                elif lvl >= 2 and bar_head and (near_kick > 0.6 or crash.get(q, 0) > 0):
                    hands = 2          # 盛り上げの段階の小節の頭
                elif j == 0 and pk == 0 and strong_down:
                    hands = 2          # 区間の頭
                elif dbl and hit_or_crash and (bar_head or (dbl >= 2 and half_bar)):
                    hands = 2          # 盛り上がりの段階で両手を足す（曲の流れの表）
                acc = j == 0 and tag == '★'   # 人の ★ のフレーズの頭
                if acc and lvl >= 1:
                    hands = 2          # 山の音（空きがあれば両手同時。無ければ下で片手に戻す）
                hits.append(Hit(o.beat, hands, si, pk, o.kind, o.s, o.midi, acc))
    hits.sort(key=lambda h: h.beat)
    out = []
    for h in hits:
        if out and abs(out[-1].beat - h.beat) < 1e-6:
            continue
        out.append(h)
    # 両手同時は前後 1/2 拍に打点が無い所だけ（すぐ次の打点を、今振ったばかりの手で打つことになるため）
    for i, h in enumerate(out):
        if h.hands == 2 and ((i > 0 and h.beat - out[i - 1].beat < 0.5 - 1e-6) or (i + 1 < len(out) and out[i + 1].beat - h.beat < 0.5 - 1e-6)):
            h.hands = 1
    return out
