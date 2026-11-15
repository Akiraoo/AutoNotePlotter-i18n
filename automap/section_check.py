"""区間の点検（アプリのタイムラインの帯「区間の点検」・docs/アプリ仕様.md）: どの区間を作り直すかの目安に、区間ごとの数字を出す
（境目は決めない＝数字と色をそのまま出し、人が判断する・2026-10-26 利用者）。

1. 人の譜面との近さ: 区間の中の片手の振りの並び（3振り・4振り）が、型のライブラリ（データベースの swings の表＝難易度×手ごとの
   振りの並び・配布用のライブラリは grams の表＝並びの番号を 32 拍ごとに順番を捨てた物）の何曲に出るか。振りのまとめ方・右手の形へのそろえ方は tools/library_themes.py（hand_swings・to_r）と同じ。
   出てくる割合（2曲以上に出る並びの割合）と、どれくらいよくある並びか（並びごとの「出る曲の割合」の中央値）。
   ライブラリは曲ごとの設定（作業ファイルの library・library_use.normalize＝無ければ新しい曲の既定のランク譜面）の曲の選び方。
   数えた物は絞り込みごとに1回だけ数えて覚えておく（数秒）。
2. 曲の中での似かた: 区間どうしの3振りの並びの重なり（多重集合の重なり÷少ない方の数）。人の譜面は同じ音楽に同じ並びの振りをくり返す
   （docs/方針.md 6.16）ので、同じ音楽（区間の名前が同じか、流れの表の記号が同じ）なのに重なりが小さい区間と、違う音楽なのに前の区間と
   重なりが大きい（単調）区間に印。
3. 区間ごとの振りの交互の崩れ・NLM の振りの警告と同じ決まり（automap/stats.py の summarize と同じ数え方。区間の境目をまたぐ2つは
   後ろの振りの区間に数える＝区間の和が曲全体と同じ）・ノーツの数・1秒のノーツ・両手の割合。
"""
import json
import re
import statistics
import sys
import threading
import time
import zlib
from pathlib import Path

import numpy as np

from . import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import library_themes as LT  # noqa: E402  （型の決め方と同じ振りのまとめ方・右手の形）

ARROW = '↑↓←→↖↗↙↘・'
NC = 108                 # 1振りの番号の数（列 4 × 段 3 × 向き 9）
MIN_SONGS = 2            # 「人の譜面に出る」とみる曲の数（型のライブラリのテーマと同じ 2 曲以上）
# 印の目安（仮・境目はまだ決めない＝画面には数字をそのまま出す）
SAME_LOW = 0.25          # 同じ音楽なのに、同じ音楽の区間との重なりの一番大きい物がこれより小さい
PREV_HIGH = 0.6          # 違う音楽なのに、前の区間との重なりがこれより大きい
MUSIC_SAME = 0.6         # 流れの表の記号の重なりがこれ以上なら同じ音楽
MIN_WIN = 6              # 並びがこれより少ない区間（短い区間）は、近さの色・似かたを出さない（数が少なすぎる）


# ---- 振りの並び ----

def code(x, y, d):
    """1振り（右手の形）の番号 0〜107。マスの外・小数の座標・向きの外は None"""
    if x != int(x) or y != int(y) or not (0 <= x <= 3 and 0 <= y <= 2 and 0 <= d <= 8):
        return None
    return int(x) + 4 * int(y) + 12 * int(d)


def decode(k):
    return k % 4, (k // 4) % 3, k // 12


def seq_text(key, n):
    """並びの番号 → 「↓10 ↑21 ↙00」（右手の形・列と段）"""
    out = []
    for _ in range(n):
        x, y, d = decode(key % NC)
        out.append(f'{ARROW[d]}{x}{y}')
        key //= NC
    return ' '.join(reversed(out))


def hand_codes(sw, c):
    """手 c の振り [(拍, (x, y, d))] → (拍の配列, 番号の配列（右手の形・使えない振りは -1）)"""
    def one(s):
        try:
            v = code(*LT.to_r(c, s))
        except (KeyError, TypeError, ValueError):   # 向きが 0〜8 の外・数でない
            v = None
        return -1 if v is None else v
    b = np.array([s[0] for s in sw], float)
    k = np.array([one(s[1]) for s in sw], np.int64)
    return b, k


def windows(k, n):
    """番号の並び → n 振りの並びの番号（使えない振りを含む所は -1）"""
    if len(k) < n:
        return np.zeros(0, np.int64)
    w = np.zeros(len(k) - n + 1, np.int64)
    bad = np.zeros(len(w), bool)
    for j in range(n):
        part = k[j:j + len(w)]
        w = w * NC + part
        bad |= part < 0
    w[bad] = -1
    return w


# ---- ライブラリの並びの数（絞り込みごとに1回） ----

class Index:
    """並びの番号 → 何曲に出たか（3振り・4振り）。ref＝同じライブラリの人の譜面を REF_BEATS 拍ごとに切った時の数字の幅（自分の曲を除いて数える）"""

    def __init__(self, keys, counts, songs, filters, built_at=None, took=0.0, ref=None):
        self.keys, self.counts = keys, counts      # {3: 並べた番号, 4: …}・{3: 曲の数, …}
        self.songs, self.filters, self.built_at, self.took, self.ref = songs, filters, built_at, took, ref

    def lookup(self, w, n):
        """並びの番号の配列 → 出た曲の数の配列（-1 は 0）"""
        ks, cs = self.keys[n], self.counts[n]
        if not len(ks) or not len(w):
            return np.zeros(len(w), np.int64)
        i = np.clip(np.searchsorted(ks, w), 0, len(ks) - 1)
        return np.where((ks[i] == w) & (w >= 0), cs[i], 0)


REF_MAPS, REF_BEATS = 80, 32   # 人の譜面の幅: 曲の数（ライブラリから等間隔に選ぶ）・切る長さ（拍）


N_LIST = (3, 4)
_E = np.zeros(0, np.int64)


def grams(b, k, n_list=N_LIST):
    """片手の振り（拍の配列・番号の配列＝hand_codes）→ 数えるのに要る物だけ: {'n': 振りの数, n: (中の並びの番号, その REF_BEATS 拍の
    切れ目の番号, またぐ並びの番号)}。中＝並びの最初と最後の振りが同じ切れ目の中（人の譜面の幅に使う）・またぐ＝それ以外（曲ごとの数にだけ使う）。
    使えない並び（-1）は入れない。順番と拍を持たない＝譜面に戻せない（配布用のライブラリ・tools/library_build/make_dist.py はこれを持つ）"""
    g = {'n': len(b)}
    for n in n_list:
        w = windows(k, n)
        if not len(w):
            g[n] = (_E, _E, _E)
            continue
        c0 = np.floor_divide(b[:len(w)], REF_BEATS).astype(np.int64)
        c1 = np.floor_divide(b[n - 1:n - 1 + len(w)], REF_BEATS).astype(np.int64)
        ok = w >= 0
        inside = ok & (c0 == c1)
        g[n] = (w[inside], c0[inside], w[ok & ~inside])
    return g


def count_swings(rows, n_list=N_LIST):
    """[(曲の id, 難易度の id, 手, [[拍, x, y, 向き], …])]（曲の id の順） → (keys, counts, 曲の数, 人の譜面の幅)。曲ごとに重ねずに数える"""
    return count_grams([(mid, did, hand, grams(*hand_codes([(s[0], tuple(s[1:4])) for s in sw], hand), n_list))
                        for mid, did, hand, sw in rows], n_list)


def count_grams(rows, n_list=N_LIST):
    """[(曲の id, 難易度の id, 手, grams の答え)]（曲の id の順） → count_swings と同じ"""
    maps = []      # [(曲の id, {難易度の id: {手: grams}})]
    for mid, did, hand, g in rows:
        if not maps or maps[-1][0] != mid:
            maps.append((mid, {}))
        maps[-1][1].setdefault(did, {})[hand] = g
    per = {n: [] for n in n_list}
    own = []
    for mid, ds in maps:
        u_n = {}
        for n in n_list:
            parts = [a for hs in ds.values() for g in hs.values() for a in (g[n][0], g[n][2])]
            u_n[n] = np.unique(np.concatenate(parts)) if parts else _E
            per[n].append(u_n[n])
        own.append(u_n)
    keys, counts = {}, {}
    for n in n_list:
        allk = np.concatenate(per[n]) if per[n] else _E
        keys[n], counts[n] = np.unique(allk, return_counts=True)
    idx = Index(keys, counts, len(maps), None)
    return keys, counts, len(maps), reference(maps, own, idx)


def _q(v):
    v = sorted(x for x in v if x is not None)
    return [round(v[min(len(v) - 1, int(len(v) * p))], 4) for p in (0.1, 0.25, 0.5, 0.75, 0.9)] if v else None


def reference(maps, own, idx):
    """人の譜面の幅: 等間隔に選んだ REF_MAPS 曲（1曲 1 難易度＝振りの一番多い物）を REF_BEATS 拍ごとに切り、区間と同じ数字を出す
    （その曲が数に入っている分は引く＝自分の曲を除いたライブラリ）→ {hit4・med4・prev（隣との重なり）: [10・25・50・75・90%], …}"""
    if not maps:
        return None
    step = max(1, len(maps) // REF_MAPS)
    hit4, med4, prev = [], [], []
    for mi in range(0, len(maps), step):
        ds = maps[mi][1]
        hs = max(ds.values(), key=lambda h: sum(g['n'] for g in h.values()))
        acc = {}
        for hand, g in hs.items():
            for n in (3, 4):
                w, ch, _ = g[n]   # 切れ目の中の並びだけ（またぐ並び・使えない並びは入っていない）
                if not len(w):
                    continue
                cnt = idx.lookup(w, n) - np.isin(w, own[mi][n]).astype(np.int64)
                for j in range(len(w)):
                    a = acc.setdefault(int(ch[j]), {3: {}, 4: []})
                    if n == 4:
                        a[4].append(int(cnt[j]))
                    else:
                        a[3][int(w[j])] = a[3].get(int(w[j]), 0) + 1
        for c0, a in acc.items():
            if len(a[4]) < MIN_WIN:
                continue
            hit4.append(sum(1 for c in a[4] if c >= MIN_SONGS) / len(a[4]))
            med4.append(statistics.median(a[4]) / max(1, idx.songs - 1))
            p = acc.get(c0 - 1)
            if p and sum(p[3].values()) >= MIN_WIN and sum(a[3].values()) >= MIN_WIN:
                prev.append(overlap(a[3], p[3]))
    return {'hit4': _q(hit4), 'med4': _q(med4), 'prev': _q(prev), 'chunks': len(hit4), 'maps': len(range(0, len(maps), step)),
            'beats': REF_BEATS}


def pack_grams(g, n_list=N_LIST):
    """grams の答え → 配布用のライブラリの grams の表の data（並びは切れ目・番号の順に並べ直す＝元の順番は残らない）"""
    head, parts = [g['n']], []
    for n in n_list:
        w, c, x = g[n]
        o = np.lexsort((w, c))
        uc, cnt = np.unique(c[o], return_counts=True)
        xs = np.unique(x)
        head += [len(uc), len(o), len(xs)]
        parts += [uc.astype('<i4'), cnt.astype('<i4'), w[o].astype('<u4'), xs.astype('<u4')]
    return zlib.compress(np.array(head, '<i4').tobytes() + b''.join(p.tobytes() for p in parts), 9)


def unpack_grams(data, n_list=N_LIST):
    raw = zlib.decompress(data)
    head = np.frombuffer(raw, '<i4', 1 + 3 * len(n_list))
    pos, g = head.nbytes, {'n': int(head[0])}

    def take(dt, cnt):
        nonlocal pos
        a = np.frombuffer(raw, dt, cnt, pos)
        pos += a.nbytes
        return a.astype(np.int64)
    for i, n in enumerate(n_list):
        nu, nw, nx = (int(v) for v in head[1 + 3 * i:4 + 3 * i])
        uc, cnt, w, x = take('<i4', nu), take('<i4', nu), take('<u4', nw), take('<u4', nx)
        g[n] = (w, np.repeat(uc, cnt), x)
    return g


RANKED = {'sources': ['ranked']}   # 絞り込みが無い時（呼ぶ側はいつも曲の設定を渡す・前は手元の譜面 local）


def build_index(filters=None, db=None):
    """型のデータベースの swings の表（配布用のライブラリなら grams の表）から並びの数を数える（library_db の曲の選び方＝export_themes と
    同じ。開いたら閉じる）"""
    from . import library_db
    f = dict(filters or RANKED)
    t0 = time.time()
    con = library_db.open_db(db)
    try:
        sel = library_db._select(con, f)   # 読むだけ（書き出しと同じ決まりで難易度を選ぶ）
        info = library_db.info_of(con)
        built = info.get('built_at')
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        dist = 'swings' not in tables and 'grams' in tables
        if dist and info.get('ref_beats') != REF_BEATS:
            raise library_db.LibraryError(f'配布用のライブラリの切れ目の長さ（{info.get("ref_beats")} 拍）がこの版（{REF_BEATS} 拍）と違う'
                                          ' → tools/library_build/make_dist.py で作り直す')
        ids = sorted(sel, key=lambda d: (sel[d][0], d))
        rows = []
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            got = {(d, h): data for d, h, data in con.execute(
                f'SELECT diff_id, hand, data FROM {"grams" if dist else "swings"} WHERE diff_id IN ({",".join("?" * len(ch))})', ch)}
            for d in ch:
                for h in (0, 1):
                    if (d, h) in got:
                        rows.append((sel[d][0], d, h, unpack_grams(got[(d, h)]) if dist else json.loads(zlib.decompress(got[(d, h)]))))
    finally:
        if not hasattr(db, 'execute'):
            con.close()
    keys, counts, songs, ref = count_grams(rows) if dist else count_swings(rows)
    return Index(keys, counts, songs, f, built, round(time.time() - t0, 2), ref)


_IDX, _IDX_LOCK, _BUILDING = {}, threading.Lock(), {}


def filters_key(f):
    return json.dumps(f or RANKED, sort_keys=True, ensure_ascii=False)


def index_for(filters, wait=0.0, db=None):
    """絞り込みの Index（覚えておく）。まだなら別の流れで数え始め、wait 秒まで待つ → (Index か None, 状態, エラー)。
    状態: 'ok'・'building'（数えている）・'unavailable'（データベースが無い・版が合わない）"""
    k = (filters_key(filters), str(db or ''))   # db＝データベースの場所（テスト・省略は既定の場所）
    with _IDX_LOCK:
        if k in _IDX:
            v = _IDX[k]
            return (v, 'ok', '') if isinstance(v, Index) else (None, 'unavailable', v)
        th = _BUILDING.get(k)
        if th is None:
            def run():
                try:
                    r = build_index(json.loads(k[0]), db)
                except Exception as e:   # noqa: BLE001  （データベースが無い・版が合わない・読めない）
                    r = str(e)
                with _IDX_LOCK:
                    _IDX[k] = r
                    _BUILDING.pop(k, None)
            th = _BUILDING[k] = threading.Thread(target=run, daemon=True)
            th.start()
    th.join(wait)
    with _IDX_LOCK:
        if k in _IDX:
            v = _IDX[k]
            return (v, 'ok', '') if isinstance(v, Index) else (None, 'unavailable', v)
    return None, 'building', ''


# ---- 区間 ----

def sections_of(marks, end):
    """マーカー（[{beat, name, tags}]・名前の無い物は前の区間に書き込みを足すだけ＝帯「区間」と同じ）→ [{name, tags, b0, b1}]"""
    out = []
    for m in sorted(marks, key=lambda m: m['beat']):
        if m.get('name'):
            out.append({'name': m['name'], 'tags': list(m.get('tags') or []), 'b0': float(m['beat'])})
        elif out:
            out[-1]['tags'] += list(m.get('tags') or [])
    for i, s in enumerate(out):
        s['b1'] = out[i + 1]['b0'] if i + 1 < len(out) else max(float(end), s['b0'])
    return out


def base_name(n):
    """区間の名前の比べ方（後ろの数字・空白は除く＝「サビ2」と「サビ」は同じ）"""
    return re.sub(r'[\s0-9０-９]+$', '', str(n or '').strip())


def music_sig(s, blocks):
    """区間の中の流れの表の記号 → {記号: 拍の長さ}（blocks＝[(拍の始まり, 終わり, 記号)]）"""
    sig = {}
    for b0, b1, base in blocks or []:
        ov = min(b1, s['b1']) - max(b0, s['b0'])
        if ov > 1e-6:
            sig[base] = sig.get(base, 0) + ov
    return sig


def overlap(a, b):
    """多重集合（{物: 数}）の重なり＝Σ min ÷ 少ない方の数（0〜1・どちらかが空なら None）"""
    na, nb = sum(a.values()), sum(b.values())
    if not na or not nb:
        return None
    return sum(min(v, b.get(k, 0)) for k, v in a.items()) / min(na, nb)


# ---- 数える ----

def check(notes, sections, bpm, blocks=None, index=None):
    """notes＝[(拍, 色, x, y, 向き)]・sections＝sections_of の結果・blocks＝[(拍の始まり, 終わり, 記号)]・index＝Index（None なら 1 を出さない）
    → 区間ごとの数字の並び（区間の順）"""
    notes = sorted(((float(b), int(c), x, y, int(d)) for b, c, x, y, d in notes), key=lambda n: (n[0], n[1]))   # stats.summarize と同じ並べ方（同じ拍・同じ色は来た順）
    spb = 60.0 / float(bpm)
    S = [dict(i=i, name=s['name'], tags=s.get('tags') or [], b0=s['b0'], b1=s['b1']) for i, s in enumerate(sections)]
    edges = np.array([s['b0'] for s in S] + [S[-1]['b1'] if S else 0.0])

    def sec_at(b):
        i = int(np.searchsorted(edges, b + 1e-6, side='right')) - 1
        return i if 0 <= i < len(S) and b < S[i]['b1'] - 1e-6 else None

    for s in S:
        s.update(notes=0, events=0, double=0, pairs=0, reset=0, warn=0, fast=0)
    # 3: ノーツ・両手（同じ拍の2色）
    ev = []
    for b, c, x, y, d in notes:
        if ev and abs(b - ev[-1][0]) < 1e-4:
            ev[-1][1].add(c)
        else:
            ev.append([b, {c}])
        i = sec_at(b)
        if i is not None:
            S[i]['notes'] += 1
    for b, cs in ev:
        i = sec_at(b)
        if i is not None:
            S[i]['events'] += 1
            S[i]['double'] += len(cs) == 2
    # 3: 振りの交互の崩れ・NLM の振りの警告と同じ決まり（stats.summarize と同じ。2つ目の振り・ノーツの区間に数える）
    nd = [{'beat': b, 'c': c, 'x': x, 'y': y, 'd': d} for b, c, x, y, d in notes]
    for c in (0, 1):
        sw = stats._swings([n for n in nd if n['c'] == c], lambda b: b * spb)
        for a, bb in zip(sw, sw[1:]):
            i = sec_at(bb[1]['beat'])
            if i is None:
                continue
            if bb[0] - a[2] < 0.12:
                S[i]['fast'] += 1
            da, db = a[1]['d'], bb[1]['d']
            if da == 8 or db == 8:
                continue
            S[i]['pairs'] += 1
            if (da in stats.UPISH and db in stats.UPISH) or (da in stats.DOWNISH and db in stats.DOWNISH):
                S[i]['reset'] += 1
        hs = [n for n in nd if n['c'] == c and n['d'] != 8]
        for a, bb in zip(hs, hs[1:]):
            if bb['beat'] - a['beat'] >= 0.2 and stats._dir_diff(a['d'], bb['d']) <= 45:
                i = sec_at(bb['beat'])
                if i is not None:
                    S[i]['warn'] += 1
    for s in S:
        dur = (s['b1'] - s['b0']) * spb
        s['sec'] = round(dur, 2)
        s['nps'] = round(s['notes'] / dur, 2) if dur > 0 else 0
        s['double_rate'] = round(s['double'] / s['events'], 3) if s['events'] else None
        s['reset_rate'] = round(s['reset'] / s['pairs'], 3) if s['pairs'] else None
    # 1・2: 片手の振りの並び（右手の形・区間の中に収まる並びだけ）
    lt = [(b, c, x, y, d) for b, c, x, y, d in notes]
    win = {3: [{} for _ in S], 4: [{} for _ in S]}
    found = {3: [[] for _ in S], 4: [[] for _ in S]}
    for c in (0, 1):
        sw = LT.hand_swings(lt, c)
        if not sw:
            continue
        bs, ks = hand_codes(sw, c)
        for n in (3, 4):
            w = windows(ks, n)
            cnt = index.lookup(w, n) if index is not None else None
            for j in range(len(w)):
                if w[j] < 0:
                    continue
                i, i2 = sec_at(bs[j]), sec_at(bs[j + n - 1])
                if i is None or i != i2:
                    continue
                win[n][i][int(w[j])] = win[n][i].get(int(w[j]), 0) + 1
                if cnt is not None:
                    found[n][i].append((int(cnt[j]), float(bs[j]), int(w[j])))
    for s in S:
        i = s['i']
        s['n3'], s['n4'] = sum(win[3][i].values()), sum(win[4][i].values())
        s['kinds3'] = len(win[3][i])
        if index is None:
            s['lib'] = None
            continue
        L = {}
        for n in (3, 4):
            f = found[n][i]
            if not f:
                L[f'hit{n}'] = L[f'med{n}'] = None
                continue
            L[f'hit{n}'] = round(sum(1 for k, _, _ in f if k >= MIN_SONGS) / len(f), 3)
            L[f'med{n}'] = round(statistics.median(k for k, _, _ in f) / max(1, index.songs), 4)
        rare = sorted(found[4][i], key=lambda r: (r[0], r[1]))
        seen, L['rare'] = set(), []
        for k, b, w in rare:
            if k >= MIN_SONGS or w in seen or len(L['rare']) >= 3:
                continue
            seen.add(w)
            L['rare'].append({'b': round(b, 3), 'seq': seq_text(w, 4), 'songs': k})
        s['lib'] = L
        s['near'] = near_score(L) if s['n4'] >= MIN_WIN else None
    # 2: 曲の中での似かた
    bl = [(float(b0), float(b1), str(base)) for b0, b1, base in (blocks or [])]
    sigs = [music_sig(s, bl) for s in S]

    def sim(i, j):   # 3振りの並びの重なり（どちらかの並びが少なすぎれば None）
        if sum(win[3][i].values()) < MIN_WIN or sum(win[3][j].values()) < MIN_WIN:
            return None
        return overlap(win[3][i], win[3][j])
    for s in S:
        i = s['i']
        same, best = [], None
        for t in S:
            j = t['i']
            if j == i:
                continue
            ms = overlap(sigs[i], sigs[j])
            if base_name(s['name']) == base_name(t['name']) or (ms is not None and ms >= MUSIC_SAME):
                same.append(j)
                v = sim(i, j)
                if v is not None and (best is None or v > best['sim']):
                    best = {'i': j, 'sim': round(v, 3)}
        s['same'] = same
        s['best_same'] = best
        prev = S[i - 1] if i > 0 else None
        v = None if prev is None else sim(i, i - 1)
        s['prev_sim'] = None if v is None else round(v, 3)
        s['prev_same_music'] = prev is not None and (i - 1) in same
        flags = []
        if same and best is not None and best['sim'] < SAME_LOW:
            flags.append('differ')
        if prev is not None and not s['prev_same_music'] and s['prev_sim'] is not None and s['prev_sim'] >= PREV_HIGH:
            flags.append('mono')
        s['flags'] = flags
    return S


def near_score(L):
    """色の濃さに使う1つの数（0〜1）: 4振りの並びが人の譜面（2曲以上）に出る割合（無ければ3振り）"""
    v = L.get('hit4')
    return v if v is not None else L.get('hit3')
