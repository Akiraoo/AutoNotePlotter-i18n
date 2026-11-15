"""譜面の「打ち方の数字」（人の譜面と作った譜面の比べ・手元の譜面の統計と同じ数え方）。"""
import math
from collections import Counter

UPISH, DOWNISH = {0, 4, 5}, {1, 6, 7}
DIRV = {0: (0, 1), 1: (0, -1), 2: (-1, 0), 3: (1, 0), 4: (-1, 1), 5: (1, 1), 6: (-1, -1), 7: (1, -1)}


def _swings(hand_notes, sec_of, slider_sec=0.07):
    """同じ手のノーツを、slider_sec 以内の続き（スライダー・スタック）をまとめて振りに。[(秒, 頭のノーツ)]"""
    out = []
    for n in hand_notes:
        s = sec_of(n['beat'])
        if out and s - out[-1][2] <= slider_sec:
            out[-1] = (out[-1][0], out[-1][1], s)
            continue
        out.append((s, n, s))
    return out


def summarize(notes, tempo):
    notes = sorted(notes, key=lambda n: (n['beat'], n['c']))
    r = {'notes': len(notes)}
    if len(notes) < 2:
        return r
    sec_of = tempo.sec
    span = sec_of(notes[-1]['beat']) - sec_of(notes[0]['beat'])
    r['nps'] = len(notes) / span if span > 0 else 0
    events = []
    for n in notes:
        if events and abs(n['beat'] - events[-1][0]) < 1e-4:
            events[-1][1].add(n['c'])
        else:
            events.append([n['beat'], {n['c']}])
    r['double'] = sum(1 for e in events if len(e[1]) == 2) / len(events)
    singles = [next(iter(e[1])) for e in events if len(e[1]) == 1]
    if len(singles) > 1:
        r['alternate'] = sum(1 for a, b in zip(singles, singles[1:]) if a != b) / (len(singles) - 1)
    dirs = {'up': 0, 'down': 0, 'diag': 0, 'side': 0, 'dot': 0}
    for n in notes:
        d = n['d']
        dirs['down' if d == 1 else 'up' if d == 0 else 'side' if d in (2, 3) else 'dot' if d == 8 else 'diag'] += 1
    r['dir'] = {k: v / len(notes) for k, v in dirs.items()}
    r['row'] = [sum(1 for n in notes if n['y'] == y) / len(notes) for y in range(3)]
    r['col'] = [sum(1 for n in notes if n['x'] == x) / len(notes) for x in range(4)]
    r['center'] = sum(1 for n in notes if n['x'] in (1, 2) and n['y'] == 1) / len(notes)
    resets = total = fast = 0
    ang = {'180': 0, '135': 0, '<=90': 0}
    moves = []
    for c in (0, 1):
        sw = _swings([n for n in notes if n['c'] == c], sec_of)
        for a, b in zip(sw, sw[1:]):
            if b[0] - a[2] < 0.12:
                fast += 1
            da, db = a[1]['d'], b[1]['d']
            moves.append(math.hypot(a[1]['x'] - b[1]['x'], a[1]['y'] - b[1]['y']))
            if da == 8 or db == 8:
                continue
            total += 1
            if (da in UPISH and db in UPISH) or (da in DOWNISH and db in DOWNISH):
                resets += 1
            va, vb = DIRV[da], DIRV[db]
            cosv = (va[0] * vb[0] + va[1] * vb[1]) / (math.hypot(*va) * math.hypot(*vb))
            deg = math.degrees(math.acos(max(-1, min(1, cosv))))
            ang['180' if deg > 157.5 else '135' if deg > 112.5 else '<=90'] += 1
    if total:
        r['reset'] = resets / total
        r['angle'] = {k: v / total for k, v in ang.items()}
    if moves:
        r['move'] = sum(moves) / len(moves)
        r['still'] = sum(1 for m in moves if m < 1e-9) / len(moves)
    r['too_fast'] = fast
    # 片手の打点が同じ手で3つ続く（間が 1 拍以内）回数・打点あたり（手元の譜面の Expert+ の中央値 2.9%）
    run, k = 0, 0
    for a, b in zip(events, events[1:]):
        if len(a[1]) == 1 and a[1] == b[1] and b[0] - a[0] <= 1 + 1e-4:
            k += 1
            run += k == 2
        else:
            k = 0
    r['run3'] = run / len(events)
    # NLM の振りの続きの警告と同じ決まり（editor-app.js の swingConflicts）: 同じ手で 0.2 拍以上空いて続く2つのノーツの向きの差が 45° 以下
    warn = 0
    for c in (0, 1):
        hs = [n for n in notes if n['c'] == c and n['d'] != 8]
        for a, b in zip(hs, hs[1:]):
            if b['beat'] - a['beat'] >= 0.2 and _dir_diff(a['d'], b['d']) <= 45:
                warn += 1
    r['nlm_swing'] = warn
    # 両手の広がり（6.21）: 振りは 1/8 拍でまとめる（上の _swings の秒のまとめ方とは別・ランク譜面の数え方にそろえる）
    sp = note_spread(notes, sec_of)
    for k in ('wide', 'in3', 'hcol', 'sps', 'cells', 'top2', 'aba'):   # cells・top2・aba は使うマスの偏り（6.22）
        if k in sp:
            r[k] = sp[k]
    return r


# ---- 両手の広がり（docs/方針.md 6.21・tools/library_spread.py と同じ数え方） ----
SWING_GAP = 0.125   # 同じ手が 1/8 拍以内に続く物は1つの振り（tools/library_themes.hand_swings と同じ決まり）
SWING_EPS = 1e-3
PAIR_SEC = 1.0      # 組にするもう片方の手の直前の振りは 1 秒以内まで


def beat_swings(notes, c):
    """その手の振り [(拍, x, y, d)]。notes＝(拍, c, x, y, d) の並び。1/8 拍以内に続く物はまとめて先頭だけ
    （tools/library_themes.hand_swings と同じ決まり・型のライブラリのデータベースの swings の表もこれ）。"""
    out, last = [], None
    for b, cc, x, y, d in sorted(n for n in notes if n[1] == c):
        if last is not None and b - last <= SWING_GAP + SWING_EPS:
            last = b
            continue
        out.append((b, x, y, d))
        last = b
    return out


def spread_pairs(sw_l, sw_r, sec_of, pair_sec=PAIR_SEC):
    """組 [(左手の列, 右手の列)]: 振りのたびに、もう片方の手の直前の振り（pair_sec 秒以内）と組にする。
    sw_*＝[(拍, x, ...)]（左手 c=0・右手 c=1）・sec_of(拍)→秒。同じ時刻は左手を先に数える。"""
    ev = sorted([(sec_of(s[0]), 0, s[1]) for s in sw_l] + [(sec_of(s[0]), 1, s[1]) for s in sw_r])
    last, out = [None, None], []
    for t, h, x in ev:
        last[h] = (t, x)
        o = last[1 - h]
        if o is not None and t - o[0] <= pair_sec:
            out.append((x, o[1]) if h == 0 else (o[1], x))
    return out


def spread(sw_l, sw_r, sec_of):
    """両手の広がり: {'wide', 'in3', 'hcol', 'sps', 'pairs', 'swings'}（組が無ければ wide・in3 は入れない）と
    使うマスの偏り（cell_stats の 'cells'・'top2'・'aba'・6.22）。
    wide＝組のうち左手が列 0・右手が列 3（両手を同時に外へ）の割合。in3＝組の2つの列が 0〜2 か 1〜3 に収まる割合。
    hcol＝振りごとの手から見た列（右手 r=x・左手 r=3−x）の割合 [反対の外, 反対の内, 自分の内, 自分の外]。
    sps＝1秒の振りの数（両手合わせて・最初から最後の振りまで）。"""
    r = {'swings': len(sw_l) + len(sw_r)}
    pa = spread_pairs(sw_l, sw_r, sec_of)
    r['pairs'] = len(pa)
    if pa:
        r['wide'] = sum(1 for a, b in pa if a == 0 and b == 3) / len(pa)
        r['in3'] = sum(1 for a, b in pa if not (min(a, b) == 0 and max(a, b) == 3)) / len(pa)
    rs = [3 - s[1] for s in sw_l] + [s[1] for s in sw_r]
    rs = [v for v in rs if v in (0, 1, 2, 3)]
    if rs:
        r['hcol'] = [sum(1 for v in rs if v == k) / len(rs) for k in range(4)]
    ts = [sec_of(s[0]) for s in sw_l] + [sec_of(s[0]) for s in sw_r]
    if len(ts) > 1 and max(ts) > min(ts):
        r['sps'] = len(ts) / (max(ts) - min(ts))
    r.update(cell_stats(sw_l, sw_r))
    return r


def note_swings(notes):
    """ノーツ（{'beat','c','x','y','d'}）→ 振り（左, 右）＝beat_swings"""
    tup = [(n['beat'], n['c'], n['x'], n['y'], n['d']) for n in notes if n.get('c') in (0, 1)]
    return beat_swings(tup, 0), beat_swings(tup, 1)


def note_spread(notes, sec_of):
    """ノーツ（{'beat','c','x','y','d'}）→ spread の結果（振りは beat_swings）"""
    return spread(*note_swings(notes), sec_of)


# ---- 使うマスの偏り・曲どうしの似方（docs/方針.md 6.22・tools/song_similarity.py・tools/library_spread.py） ----
MIRROR_D = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}   # 向きの左右反転（tools/library_themes.MIRROR_D と同じ）


def to_r(c, x, y, d):
    """振り (x, y, 向き) を右手の形へ（左手 c=0 は左右反転＝列 3−x・向きも左右反転。tools/library_themes.to_r と同じ）"""
    return (x, y, d) if c == 1 else (3 - x, y, MIRROR_D.get(d, d))


def hand_seqs(sw_l, sw_r):
    """振り（左・右＝[(拍, x, y, d, …)]）→ 手ごとの右手の形の並び [[(rx, y, d)]（左）, [(rx, y, d)]（右）]"""
    return [[to_r(0, *s[1:4]) for s in sw_l], [to_r(1, *s[1:4]) for s in sw_r]]


def cell_stats(sw_l, sw_r):
    """使うマスの偏り: {'cells', 'top2', 'aba'}（数えられない物は入れない）。
    cells＝手から見たマス（番号 rx×3＋y・rx は右手 x・左手 3−x）の振りの割合 12 個。top2＝よく使う2マスの割合（cells の上位2つの和）。
    aba＝同じ2振りの往復（その手の振りが2つ前と同じ (rx, y, 向き)）の割合（両手の3振りの並びの数あたり）。"""
    r = {}
    seqs = hand_seqs(sw_l, sw_r)
    cnt, n = [0] * 12, 0
    for s in seqs:
        for x, y, _ in s:
            if x in (0, 1, 2, 3) and y in (0, 1, 2):
                cnt[int(x) * 3 + int(y)] += 1
                n += 1
    if n:
        r['cells'] = [v / n for v in cnt]
        r['top2'] = sum(sorted(r['cells'])[-2:])
    tri = sum(max(0, len(s) - 2) for s in seqs)
    if tri:
        r['aba'] = sum(1 for s in seqs for i in range(len(s) - 2) if s[i] == s[i + 2]) / tri
    return r


def tri_counts(seqs):
    """手ごとの右手の形の並び → 3振りの並びの数（多重集合・collections.Counter）"""
    return Counter(tuple(s[i:i + 3]) for s in seqs for i in range(len(s) - 2))


def one_counts(seqs):
    """手ごとの右手の形の並び → 置き方（1振り＝(rx, y, 向き)）の数"""
    return Counter(x for s in seqs for x in s)


def overlap(a, b):
    """2曲の重なり: 多重集合の Σmin ÷ 少ない方の数（どちらかが空なら 0）"""
    na, nb = sum(a.values()), sum(b.values())
    if not na or not nb:
        return 0.0
    return sum(min(v, b.get(k, 0)) for k, v in a.items()) / min(na, nb)


def variety(seqs):
    """曲の中の変化: {'kinds'＝100振りあたりの3振りの並びの種類, 'entropy'＝ばらつき（bit）, 'top10'＝上位10の並びの割合}"""
    t = tri_counts(seqs)
    n = sum(t.values())
    sw = sum(len(s) for s in seqs)
    if not n or not sw:
        return {}
    return {'kinds': len(t) / (sw / 100), 'entropy': -sum(v / n * math.log2(v / n) for v in t.values()),
            'top10': sum(v for _, v in t.most_common(10)) / n}


_ANG = {0: 90, 1: 270, 2: 180, 3: 0, 4: 135, 5: 45, 6: 225, 7: 315}


def _dir_diff(a, b):
    x = abs(_ANG[a] - _ANG[b]) % 360
    return min(x, 360 - x)


def table(rows):
    """[(見出し, summarize の結果)] → Markdown の表。"""
    def pct(v):
        return '' if v is None else f'{v * 100:.0f}%'

    def get(r, *path):
        for p in path:
            if r is None:
                return None
            r = r.get(p) if isinstance(r, dict) else (r[p] if isinstance(r, list) and p < len(r) else None)
        return r

    items = [
        ('ノーツ', lambda r: str(r.get('notes', ''))),
        ('1秒のノーツ', lambda r: f"{r['nps']:.2f}" if 'nps' in r else ''),
        ('両手同時', lambda r: pct(r.get('double'))),
        ('片手が交互', lambda r: pct(r.get('alternate'))),
        ('上下の向き', lambda r: pct((get(r, 'dir', 'up') or 0) + (get(r, 'dir', 'down') or 0)) if 'dir' in r else ''),
        ('斜め', lambda r: pct(get(r, 'dir', 'diag'))),
        ('横', lambda r: pct(get(r, 'dir', 'side'))),
        ('点', lambda r: pct(get(r, 'dir', 'dot'))),
        ('下段／中段／上段', lambda r: '／'.join(pct(v) for v in r['row']) if 'row' in r else ''),
        ('列 0〜3', lambda r: '／'.join(pct(v) for v in r['col']) if 'col' in r else ''),
        ('真ん中の段の中央2列', lambda r: pct(r.get('center'))),
        ('前の振りと真逆', lambda r: pct(get(r, 'angle', '180'))),
        ('45°曲がる', lambda r: pct(get(r, 'angle', '135'))),
        ('90°以上曲がる', lambda r: pct(get(r, 'angle', '<=90'))),
        ('振りの交互の崩れ', lambda r: pct(r.get('reset'))),
        ('同じ手の移動（マス・平均）', lambda r: f"{r['move']:.2f}" if 'move' in r else ''),
        ('同じ手が同じマスに続く', lambda r: pct(r.get('still'))),
        ('同じ手が0.12秒未満で続く（回）', lambda r: str(r.get('too_fast', ''))),
        ('NLM の振りの警告と同じ決まり（回）', lambda r: str(r.get('nlm_swing', ''))),
        ('同じ手が3つ続く（打点あたり）', lambda r: pct(r.get('run3'))),
        ('1秒の振り（両手）', lambda r: f"{r['sps']:.2f}" if 'sps' in r else ''),
        ('両手を同時に外へ（左 0・右 3）', lambda r: pct(r.get('wide'))),
        ('両手が3列に収まる', lambda r: pct(r.get('in3'))),
        ('手ごとの列（反対の内／自分の内／自分の外）', lambda r: '／'.join(pct(v) for v in r['hcol'][1:]) if 'hcol' in r else ''),
        ('よく使う2マスの割合', lambda r: pct(r.get('top2'))),
        ('同じ2振りの往復（A B A）', lambda r: pct(r.get('aba'))),
    ]
    head = '| | ' + ' | '.join(h for h, _ in rows) + ' |'
    sep = '|---|' + '---|' * len(rows)
    lines = [head, sep]
    for name, f in items:
        lines.append(f'| {name} | ' + ' | '.join(f(r) for _, r in rows) + ' |')
    return '\n'.join(lines)
