"""歌の打点の寄せ方を、人が歌に合わせて打った譜面で確かめる（手元の譜面フォルダの曲・読むだけ）。

使い方: NLM 不要。.venv の Python で:
  .venv/Scripts/python.exe tools/eval_vocal.py <CustomLevels> <曲のフォルダ名の頭 …> [--diff ExpertPlus]
曲ごとに song.egg を分け（cache/lib/<フォルダ名の頭>/・.venv-sep で・1回だけ）、歌の始まりを拾い、ドラムで目盛りを合わせ、
寄せ方ごとに「作った歌の打点が人のノーツと同じ拍にある割合」（一致）と「1/4 拍か 1/3 拍ずれた所にだけ人のノーツがある割合」（ずれ）を数える。
人は歌の全部の音節は打たないので一致は 100% にならない。寄せ方どうしの比べに使う。
--seg: 歌の音符の区切りの扱い（前の音符と続いていて谷の浅い区切りを半拍までにする・寄せた先で楽器が鳴っていない物を前の音符に
まとめる＝rhythm.snap_vocals の coarse・merge_phantoms）を比べる（分けた音のある曲だけ・歌の多い曲に限らず手元の 149 曲で確かめた）。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from automap import rhythm  # noqa: E402
from library_stats import load, find, parse_diff  # noqa: E402


def map_of(folder, want):
    info = load(find(folder, 'Info.dat'))
    bpm = float(info['_beatsPerMinute'])
    song = find(folder, info.get('_songFilename') or 'song.egg')
    for s in info['_difficultyBeatmapSets']:
        if s.get('_beatmapCharacteristicName') != 'Standard':
            continue
        bms = {b['_difficulty']: b for b in s['_difficultyBeatmaps']}
        for d in (want, 'ExpertPlus', 'Expert'):
            if d in bms:
                notes, _, _, _, bpmch = parse_diff(load(find(folder, bms[d]['_beatmapFilename'])))
                if bpmch:
                    return None
                beats = sorted({round(n[0], 3) for n in notes if n[1] in (0, 1)})
                return {'bpm': bpm, 'song': song, 'diff': d, 'beats': np.array(beats), 'name': f"{info.get('_songAuthorName')} - {info.get('_songName')}",
                        'mapper': info.get('_levelAuthorName'), 'offset': float(info.get('_songTimeOffset') or 0)}
    return None


def strategies():
    """寄せ方の名前 → 関数(歌の始まりの拍（ドラムで合わせた目盛り）の配列, 遅れ（拍）) → 寄せた拍"""
    def nearest(r, grid):
        return np.round(r * grid) / grid

    def prior(lam, grids=(4,)):
        def f(r, lat):
            x = r - lat
            best = None
            for g in grids:
                base = np.floor(x * g) / g
                for k in (-1, 0, 1, 2):
                    c = base + k / g
                    lvl = np.where(np.abs(c - np.round(c)) < 1e-6, 0, np.where(np.abs(c * 2 - np.round(c * 2)) < 1e-6, 1, 2))
                    cost = np.abs(x - c) + lam * lvl
                    if best is None:
                        best, bc = c.copy(), cost
                    else:
                        m = cost < bc
                        best[m], bc[m] = c[m], cost[m]
            return best
        return f
    ms = lambda v: (lambda r, lat, small, bpm: prior(v / 1000 * bpm / 60)(r, lat))   # 優先の強さを ms で（速い曲ほど拍では強く）
    return {
        '今（1/4・小さな補正）': lambda r, lat, small, bpm: nearest(r - small, 4),
        '優先 45ms': ms(45), '優先 55ms': ms(55), '優先 70ms': ms(70),
        '速さで変える・遅れは1/2拍で': lambda r, lat, small, bpm: rhythm.snap_vocals(r - circ_lat(r, 2), bpm),
        '速さで変える・遅れは集まる方で（rhythm の今）': lambda r, lat, small, bpm: rhythm.snap_vocals(r - rhythm.vocal_lag(r), bpm),
        '優先 45ms・遅れは1/2拍で': lambda r, lat, small, bpm: prior(0.045 * bpm / 60)(r, circ_lat(r, 2)),
        '優先 55ms・遅れは1/2拍で': lambda r, lat, small, bpm: prior(0.055 * bpm / 60)(r, circ_lat(r, 2)),
        '遅れを差し引く（1/4）': lambda r, lat, small, bpm: nearest(r - lat, 4),
        '1/2 拍だけ': lambda r, lat, small, bpm: nearest(r - lat, 2),
    }


def circ_lat(r, grid=4):
    """歌の始まりの、目盛りに対する平均の遅れ（拍）。円の平均（目盛りの間を一周とみる）＝大きくずれていても平均が取れる"""
    ph = 2 * np.pi * ((r * grid) % 1.0)
    return float(np.angle(np.mean(np.exp(1j * ph))) / (2 * np.pi) / grid)


SEG = ('全部 1/4 拍まで（2026-11-07 まで）', '谷の浅い続きは半拍まで', '＋楽器の鳴っていない物をまとめる（rhythm の今）')


def seg_rows(stems, m):
    """歌の音符の区切りの扱いごとの (一致, 1/4 拍ずれ, 作った数, 拾えた, 分母)。分母＝歌の音符（強さ 0.3 以上）の鳴っている間に
    ある人のノーツ（扱いで変わらない）。寄せる前の位置・遅れは rhythm.analyze と同じ"""
    from automap import audio
    bpm = m['bpm']
    ons, info = rhythm.analyze(stems, bpm, 0)
    bias = info['drum_bias_ms'] / 1000 * bpm / 60
    vn = audio.vocal_notes(stems / 'vocals.flac')
    r0 = np.array([audio.sec_to_beat(x['t0'], bpm, 0) - bias for x in vn])
    vb = float(np.clip(rhythm.vocal_lag([r for r, x in zip(r0, vn) if x['s'] >= 0.3]), -0.04 * bpm / 60, 0.04 * bpm / 60))
    weak = [x['cont'] and x['dip'] < rhythm.WEAK_DIP_DB for x in vn]
    strong = np.array([x['s'] >= 0.3 for x in vn])
    H = set(np.round(m['beats'], 3))
    spans = [(r - 0.13, r + (x['t1'] - x['t0']) * bpm / 60) for r, x in zip(r0, vn) if x['s'] >= 0.3]
    den = [h for h in sorted(H) if any(a <= h <= b for a, b in spans)]
    q_all = rhythm.snap_vocals(r0 - vb, bpm)
    q_half = rhythm.snap_vocals(r0 - vb, bpm, coarse=weak)
    vo = [rhythm.Onset(float(q), float(r - vb), 'vocal', x['s'], x['midi'], (x['t1'] - x['t0']) * bpm / 60) for q, r, x in zip(q_half, r0, vn)]
    merged = rhythm.merge_phantoms(vo, weak, [o for k in ('kick', 'snare', 'hihat', 'other') for o in ons[k]])
    out = []
    for q in (q_all[strong], q_half[strong], np.array([o.beat for o in merged if o.s >= 0.3])):
        qs = set(np.round(q, 3))
        ex = sum(1 for b in qs if b in H)
        off = sum(1 for b in qs if b not in H and any(round(b + d, 3) in H for d in (-0.25, 0.25)))
        out.append((ex, off, len(qs), sum(1 for h in den if round(h, 3) in qs), len(den)))
    return out


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('root')
    p.add_argument('ids', nargs='+')
    p.add_argument('--diff', default='ExpertPlus')
    p.add_argument('--seg', action='store_true', help='寄せ方ではなく、歌の音符の区切りの扱い（谷の浅い続き・楽器の鳴っていない物）を比べる')
    p.add_argument('--pull', action='store_true', help='歌を拍に寄せる（迷った歌の打点をキック・スネアの鳴る目盛りへ・rhythm.vocal_pull）を比べる')
    p.add_argument('--jobs', type=int, default=8, help='--pull: 並べる数')
    a = p.parse_args(argv)
    if a.seg:
        return main_seg(a)
    if a.pull:
        return main_pull(a)
    sep_py = ROOT / '.venv-sep' / 'Scripts' / 'python.exe'
    names = list(strategies())
    tot = {k: [0, 0, 0, 0, 0] for k in names}   # 一致・ずれ・作った数・拾えた人のノーツ・歌の近くの人のノーツ
    print('| 曲（譜面の作者・BPM） | 歌の遅れ | ' + ' | '.join(names) + ' |')
    print('|---|---|' + '---|' * len(names))
    for pre in a.ids:
        pre = pre.strip()
        folder = next((os.path.join(a.root, f) for f in os.listdir(a.root) if f.startswith(pre)), None)
        m = map_of(folder, a.diff) if folder else None
        if not m or not m['song'] or abs(m['offset']) > 1e-6:
            print(f'| {pre}: 使えない（無い・BPM の変化・曲の時刻のずらし） |')
            continue
        stems = ROOT / 'cache' / 'lib' / pre
        if not (stems / 'separate.json').exists():
            subprocess.run([str(sep_py), str(ROOT / 'tools' / 'separate.py'), m['song'], '--out', str(stems)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ons, info = rhythm.analyze(stems, m['bpm'], 0)
        vb = info['vocal_bias_ms'] / 1000 * m['bpm'] / 60
        vs = [v for v in ons['vocal'] if v.s >= 0.3]
        r = np.array([v.raw for v in vs]) + vb          # ドラムで合わせた目盛りに対する歌の始まり（拍）
        lat = circ_lat(r)
        H = set(np.round(m['beats'], 3))
        # 歌の始まりの近く（1/8 拍以内）にある人のノーツ＝人が歌に合わせて置いた物（拾えた割合の分母）
        hv = [h for h in m['beats'] if np.min(np.abs(r - lat - h)) < 0.125]
        row = []
        for k, f in strategies().items():
            b = np.unique(np.round(f(r, lat, vb, m['bpm']), 3))
            ex = sum(1 for x in b if round(x, 3) in H)
            near = sum(1 for x in b if round(x, 3) not in H and any(round(x + d, 3) in H for d in (-0.25, 0.25, -1 / 3, 1 / 3)))
            bs = set(np.round(b, 3))
            rec = sum(1 for h in hv if round(h, 3) in bs)
            tot[k][0] += ex
            tot[k][1] += near
            tot[k][2] += len(b)
            tot[k][3] += rec
            tot[k][4] += len(hv)
            row.append(f'{ex / len(b):.0%}／{rec / max(1, len(hv)):.0%}')
        print(f"| {m['name'][:28]}（{m['mapper'][:12]}・{m['bpm']:g}） | {lat * 60 / m['bpm'] * 1000:+.0f}ms | " + ' | '.join(row) + ' |')
    print('| 全体 | | ' + ' | '.join(f'{v[0] / max(1, v[2]):.0%}／{v[3] / max(1, v[4]):.0%}' for v in tot.values()) + ' |')
    f1 = lambda v: 2 * (v[0] / max(1, v[2])) * (v[3] / max(1, v[4])) / max(1e-9, v[0] / max(1, v[2]) + v[3] / max(1, v[4]))
    print('| 合わせた点 | | ' + ' | '.join(f'{f1(v):.2f}' for v in tot.values()) + ' |')
    print('（各欄＝一致（作った打点のうち人も置いた割合）／拾えた割合（歌の近くの人のノーツのうち同じ拍に置けた割合）。合わせた点は両方の調和平均）')


def main_seg(a):
    """--seg: 区切りの扱いごとの表（2026-11-08・手元の 149 曲で 一致 56.8→60.6→63.2%・1/4 拍ずれ 13.6→8.4→8.6%・拾えた 62.2→61.7→59.9%）。
    分けた音が無い曲は飛ばす（--seg では分けない）"""
    tot = [np.zeros(5) for _ in SEG]
    print('| 曲（譜面の作者・BPM） | ' + ' | '.join(SEG) + ' |')
    print('|---|' + '---|' * len(SEG))
    for pre in a.ids:
        pre = pre.strip()
        folder = next((os.path.join(a.root, f) for f in os.listdir(a.root) if f.startswith(pre)), None)
        m = map_of(folder, a.diff) if folder else None
        stems = ROOT / 'cache' / 'lib' / pre
        if not m or not m['song'] or abs(m['offset']) > 1e-6 or not (stems / 'vocals.flac').exists():
            continue
        rows = seg_rows(stems, m)
        if rows[0][4] < 30:   # 歌の近くに人のノーツがほとんど無い（歌の無い曲）
            continue
        for t, r in zip(tot, rows):
            t += r
        print(f"| {m['name'][:28]}（{m['mapper'][:12]}・{m['bpm']:g}） | "
              + ' | '.join(f'{r[0] / max(1, r[2]):.0%}／{r[1] / max(1, r[2]):.0%}／{r[3] / max(1, r[4]):.0%}' for r in rows) + ' |')
    print('| 全体 | ' + ' | '.join(f'{v[0] / max(1, v[2]):.1%}／{v[1] / max(1, v[2]):.1%}／{v[3] / max(1, v[4]):.1%}（{int(v[2])}）' for v in tot) + ' |')
    print('（各欄＝一致／1/4 拍ずれた所にだけ人のノーツ／拾えた割合（歌の鳴っている間の人のノーツのうち同じ拍に置けた割合）・全体の括弧は打点の数）')


PULL = (('今（寄せない）', None, None), ('自動（既定・しきい値 0.8・強さ 0.35）', 0.8, 0.35), ('自動 しきい値 0.9', 0.9, 0.35),
        ('自動 しきい値 1.0', 1.0, 0.35), ('自動 強さ 0.5', 0.8, 0.5), ('曲の全部を指示の区間に（強さ 1.0＝隣にドラムなら必ず）', None, 1.0),
        ('曲の全部を指示の区間に（強さ 0.5）', None, 0.5), ('曲の全部を指示の区間に（強さ 0.35）', None, 0.35))
# 名前・ばらつきのしきい値（LOOSE_FRAC・None＝曲の全部を指示の区間に＝INTENT_REACH の両隣まで）・寄せる強さ（DRUM_PULL か INTENT_PULL）
# 2026-11-15 に手元の 148 曲で: 自動（既定）は一致 62.9→63.9%・1/4 拍ずれ 8.5→7.6%・拾えた 63.6→63.6%（ランク譜面で歌に沿って打つ 67 曲は
# 76.2→77.7%・9.0→7.8%・73.6→73.5%）。両隣に絞らないと自動は少し良い（絞ると 63.6%）＝自動は絞らない・指示の強い寄せ方だけ絞る


def pull_rows(job):
    """--pull の 1 曲: 寄せ方ごとの (一致, 1/4 拍ずれ, 作った数, 拾えた, 分母, 動いた数, 動いた歌の元の位置に人, 寄せた位置に人, 元の位置にだけ人, 寄せた位置にだけ人)
    と、人が歌に沿って打っているか（目盛りから 15ms 以内の歌の打点のうち人のノーツが同じ拍にある割合）"""
    root, pre, diff = job
    folder = next((os.path.join(root, f) for f in os.listdir(root) if f.startswith(pre)), None)
    m = map_of(folder, diff) if folder else None
    stems = ROOT / 'cache' / 'lib' / pre
    if not m or not m['song'] or abs(m['offset']) > 1e-6 or not (stems / 'vocals.flac').exists():
        return None
    bpm = m['bpm']
    ons, _ = rhythm.analyze(stems, bpm, 0)
    H = set(np.round(m['beats'], 3))
    has = lambda b: round(b, 3) in H
    v0 = [o for o in ons['vocal'] if o.s >= 0.3]
    spans = [(o.raw - 0.13, o.raw + o.length) for o in v0]
    den = [h for h in sorted(H) if any(a <= h <= b for a, b in spans)]
    clean = [o for o in v0 if abs(o.raw - round(o.raw * 4) / 4) * 60 / bpm * 1000 < 15]
    follow = sum(has(o.beat) for o in clean) / max(1, len(clean))
    old = {round(o.raw, 5): o.beat for o in ons['vocal']}
    out = []
    for _, frac, pull in PULL:
        if pull is None:
            vs = ons['vocal']
        else:
            keep = rhythm.DRUM_PULL, rhythm.INTENT_PULL
            rhythm.DRUM_PULL = rhythm.INTENT_PULL = pull
            try:
                if frac is None:
                    got, _ = rhythm.vocal_pull(ons, bpm, [(-1e9, 1e9)], auto=False)
                else:
                    got, _ = rhythm.vocal_pull(ons, bpm, [], auto=True, frac=frac)
            finally:
                rhythm.DRUM_PULL, rhythm.INTENT_PULL = keep
            vs = got['vocal']
        vs = [o for o in vs if o.s >= 0.3]
        qs = set(round(o.beat, 3) for o in vs)
        ex = sum(1 for b in qs if b in H)
        off = sum(1 for b in qs if b not in H and any(round(b + d, 3) in H for d in (-0.25, 0.25)))
        mv = [(old[round(o.raw, 5)], o.beat) for o in vs if round(o.raw, 5) in old and abs(old[round(o.raw, 5)] - o.beat) > 1e-6]
        out.append((ex, off, len(qs), sum(1 for h in den if round(h, 3) in qs), len(den), len(mv),
                    sum(has(a) for a, _ in mv), sum(has(b) for _, b in mv),
                    sum(has(a) and not has(b) for a, b in mv), sum(has(b) and not has(a) for a, b in mv)))
    return {'pre': pre, 'rows': out, 'follow': follow, 'name': m['name'], 'mapper': m['mapper'], 'bpm': bpm}


def _ranked_prefixes():
    """型のデータベース（設定の library_db）で BeatLeader のランク譜面の手元のフォルダの名前の頭（読めなければ空）"""
    try:
        import sqlite3
        from automap import config
        db = sqlite3.connect(config.load().get('library_db'))
        return {os.path.basename(f or '').split(' ')[0] for f, r in db.execute("select folder, ranked from maps where place = 'local'") if r}
    except Exception:   # noqa: BLE001
        return set()


def main_pull(a):
    """--pull: 歌を拍に寄せる寄せ方ごとの表（全部・ランク譜面だけ・人が歌に沿って打っている曲だけ）。分けた音が無い曲は飛ばす。
    一致・1/4 拍ずれ・拾えたは --seg と同じ。動いた歌は「元の位置にだけ人 → 寄せた位置にだけ人」（どちらにもある・どちらにも無いは数えない）"""
    from concurrent.futures import ProcessPoolExecutor
    ranked = _ranked_prefixes()
    with ProcessPoolExecutor(a.jobs) as ex:
        res = [r for r in ex.map(pull_rows, [(a.root, p.strip(), a.diff) for p in a.ids]) if r and r['rows'][0][4] >= 30]
    groups = (('全部', res), ('ランク譜面', [r for r in res if r['pre'] in ranked]),
              ('人が歌に沿って打つ曲（目盛りに近い歌の 60% 以上に人のノーツ）', [r for r in res if r['follow'] >= 0.6]),
              ('ランク譜面で歌に沿って打つ曲', [r for r in res if r['pre'] in ranked and r['follow'] >= 0.6]))
    for gname, rs in groups:
        print(f'\n### {gname}（{len(rs)} 曲）\n')
        print('| 寄せ方 | 一致 | 1/4 拍ずれ | 拾えた | 動いた歌 | 動いた歌: 元の位置にだけ人 → 寄せた位置にだけ人 |')
        print('|---|---|---|---|---|---|')
        for i, (name, *_) in enumerate(PULL):
            v = np.sum([r['rows'][i] for r in rs], axis=0) if rs else np.zeros(10)
            print(f'| {name} | {v[0] / max(1, v[2]):.1%} | {v[1] / max(1, v[2]):.1%} | {v[3] / max(1, v[4]):.1%} | {int(v[5])}（{v[5] / max(1, v[2]):.1%}） | '
                  f'{v[8] / max(1, v[5]):.1%} → {v[9] / max(1, v[5]):.1%} |')
    print('\n（一致＝作った歌の打点のうち人のノーツも同じ拍にある割合・1/4 拍ずれ＝隣の 1/4 拍にだけ人のノーツ・拾えた＝歌の鳴っている間の人のノーツのうち'
          '同じ拍に置けた割合。自動＝歌がばらつく区間（rhythm.loose_spans）だけ）')


if __name__ == '__main__':
    main()
