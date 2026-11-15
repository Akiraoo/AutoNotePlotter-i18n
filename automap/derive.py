"""基準の譜面から上・下の難易度（派生）を作る（難易度の展開・docs/アプリ仕様.md 17 節）。
compose --derive-from（__main__._derive）と、アプリの展開の窓（既定の値＝default_plan）が使う。

- 下の難易度は人の譜面と同じく基準の打点を弱い物から間引く（易しい難易度の打点の 97〜98% が1つ上にもある・1段で量 72〜86%・
  docs/方針.md 4 章）。上は拾った候補から打点を足す（amount.py の足す順）。置き方は基準に寄せながら流れの計算をし直す。
- 派生ごとに決めるのは、量（基準の1秒のノーツに対する割合・既定は1段ごとに ±10%＝diffs.ratio・アプリは app/config.local.json の
  expand_step_pct で刻みを変えられる）と型の範囲（ライブラリの★の帯・既定は段の数だけずらす＝区間の★の帯 ±1 と同じ決まり・library_use.band_stars）。
"""
import bisect
import copy
import math

from . import amount, diffs, library_use, repeat, rhythm, stats

# 派生の型の範囲の既定を決める時の型の数（library_use.counts の themes＝テーマに使える型）
LOW_DIFF_ENOUGH = 30   # 易しい難易度（Hard 以下）の譜面だけでこれだけ型があれば、絞り込みの難易度に足す（少なければ Expert／Expert+ のまま）
PLAN_MIN = 40          # 既定の型の範囲でこれより少なければ、★の帯の上を1段ずつ戻す（型が足りずに止まったり単調になったりしないように）
LOW_DIFFS = ('Easy', 'Normal', 'Hard')


def _counts(f):
    try:
        return library_use.counts(f)['themes']
    except library_use.ERRORS:
        return None


def ratio_note(base, target, step_pct=None):
    """既定の量の決め方の説明（default_plan の note の頭）"""
    n = diffs.steps(base, target)
    s = diffs.STEP_PCT if step_pct is None else float(step_pct)
    return f'量 {diffs.ratio(base, target, s):g} 倍（1段 {s:g}%' + (f'・{abs(n)}段{"下" if n < 0 else "上"}' if n else '') + '）'


def default_plan(base, target, library, step_pct=None):
    """基準の難易度 base から派生の難易度 target を作る時の既定 → {'ratio': 量の割合, 'library': 型の範囲, 'note': 決め方,
    'lib_note': note のうち型の範囲の決め方（量の刻みを変えても同じ＝アプリが覚えて使い回す）}。
    library＝曲の作業ファイルの library（None＝新しい曲の既定 library_use.DEFAULT）。step_pct＝量の刻み（%・None＝diffs.STEP_PCT）。
    - ratio＝diffs.ratio（1段下ごとに −step_pct%・上は +step_pct%・足し算・diffs.RATIO_RANGE の端まで）。
    - library＝曲の絞り込みの★の帯を段の数だけずらした物（区間の★の帯と同じ）。
      Hard 以下は、その難易度（と Expert までの間の難易度）の譜面の型が LOW_DIFF_ENOUGH 以上あれば絞り込みの難易度に足す。
      型が PLAN_MIN より少なければ★の帯の上を戻す。データベースが使えない PC は曲の設定のまま（作り直しは止まる）。"""
    base, target = diffs.name_of(base), diffs.name_of(target)
    n = diffs.steps(base, target)
    r = diffs.ratio(base, target, step_pct)
    rn = ratio_note(base, target, step_pct)
    out = lambda lib, *ln: {'ratio': r, 'library': lib, 'note': '・'.join((rn,) + ln), 'lib_note': '・'.join(ln)}
    song = library_use.normalize(library)   # 無い＝新しい曲の既定
    ok, why, _ = library_use.available()
    if not ok:
        return out(song, f'型のデータベースが使えない（{why}）＝作り直しは止まる')
    if n == 0:
        return out(song, '基準と同じ難易度・型は曲の設定のまま')
    f = library_use.band_filters(song, max(-3, min(3, n)))
    src = '曲の設定' if library else '新しい曲の既定'
    note = [f'型は{src}の{library_use.stars_text(song.get("stars"))}を{abs(n)}段'
            f'{"やさしく" if n < 0 else "難しく"}＝{library_use.stars_text(f["stars"])}']
    low = [d for d in LOW_DIFFS if diffs.ORDER.index(d) >= diffs.ORDER.index(target)]
    if low and target in LOW_DIFFS:
        k = _counts(dict(f, diffs=low))
        if k is not None and k >= LOW_DIFF_ENOUGH:
            f['diffs'] = sorted(set(f.get('diffs') or library_use.DEFAULT['diffs']) | set(low), key=diffs.ORDER.index)
            note.append(f'{"／".join(diffs.TEXT[d] for d in low)} の譜面の型 {k} を足す')
        else:
            note.append(f'{"／".join(diffs.TEXT[d] for d in low)} の譜面の型が少ない（{k}）ので難易度は'
                        f'{"／".join(diffs.TEXT[d] for d in f.get("diffs") or library_use.DEFAULT["diffs"])}のまま')
    k = _counts(f)
    hi0 = song.get('stars') or [0, 99]
    while k is not None and k < PLAN_MIN and f['stars'][1] < hi0[1]:
        up = [x for x in library_use.BAND_STEPS if x > f['stars'][1]]
        if not up:
            break
        f['stars'] = [f['stars'][0], min(up[0], hi0[1])]
        k = _counts(f)
        note.append(f'型が少ないので★の上を {library_use.stars_text(f["stars"])} まで戻す')
    if k is None:
        return out(song, '型の数を数えられないので型は曲の設定のまま')
    note.append(f'テーマに使える型 {k}')
    return out(f, *note)


# ---- 派生の打点（compose --derive-from・__main__ の派生の道） ----
# 人の譜面の難易度ごとの数（docs/方針.md 4 章・手元の譜面 930 曲の中央値）。派生は基準の数にこの比を掛けた所を目安にする
HUMAN = {
    'nps': {'Easy': 2.2, 'Normal': 3.0, 'Hard': 3.9, 'Expert': 4.9, 'ExpertPlus': 6.3},
    'double': {'Easy': 0.06, 'Normal': 0.09, 'Hard': 0.11, 'Expert': 0.14, 'ExpertPlus': 0.20},      # 両手同時（打点あたり）
    'quarter': {'Easy': 0.01, 'Normal': 0.02, 'Hard': 0.06, 'Expert': 0.15, 'ExpertPlus': 0.22},     # 打点の間が 1/4 拍
    'fast': {'Easy': 0.47, 'Normal': 0.34, 'Hard': 0.28, 'Expert': 0.20, 'ExpertPlus': 0.18},       # 同じ手の振りの間（速い方から1割・秒）
}
ANCHOR_W = 0.5        # 基準と同じ拍の打点を基準の置き方に寄せる重み（前の譜面に寄せる・決めの外を留めるのと同じ仕組み）。こだまの Expert で
                      # 同じ置き方 0.2＝20%・0.5＝33%・1.0＝51%（片手が交互 90・83・74%・基準 93%）。型の範囲を変えた分はテーマが勝つ
SLIDER_SEC = 0.07     # 同じ色がこれより短く続く物は1つの振り（__main__._kept_hits・stats と同じ）
MIN_GAP = 0.15        # compose の同じ手の振りの最短の間（秒・flow.Style の min_gap）。下の難易度は人の速い方から1割の比で広げる
TOL = 0.015           # 目安の量との差がこの割合より小さければ合わせ終わり
DBL_FREE = 0.5        # 両手にする打点の前後に空ける拍（rhythm と同じ・決めた両手でない時）
DBL_SEC = 0.12        # 〃（秒）
DBL_EVEN_SPAN = 16.0  # 足す両手と前後の両手の間の片手の打点を偶数個にする（この拍より離れた両手とは比べない）


def human_rel(base, target, key):
    """人の譜面の数の比（target ÷ base・HUMAN）"""
    h = HUMAN[key]
    return h[diffs.name_of(target)] / h[diffs.name_of(base)]


def min_gap(base, target):
    """派生の流れの計算の同じ手の振りの最短の間（秒）。下の難易度は人の速い方から1割の間の比で広げ、上は今のまま"""
    return round(MIN_GAP * max(1.0, human_rel(base, target, 'fast')), 3)


def swings(notes, tempo, slider_sec=SLIDER_SEC):
    """ノーツ → {拍（4 桁に丸め）: {手: (x, y, d)}}（赤青だけ。同じ色が slider_sec 秒以内に続く物＝スライダーの後ろ・重なりは1つの振り）"""
    by, last = {}, {}
    for n in sorted(notes, key=lambda n: (n['beat'], n['c'])):
        if n['c'] not in (0, 1):
            continue
        t = tempo.sec(n['beat'])
        if n['c'] in last and t - last[n['c']] < slider_sec:
            continue
        last[n['c']] = t
        by.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    return dict(sorted(by.items()))


def strength_at(ons, kinds=('vocal', 'kick', 'snare', 'other')):
    """{拍（4 桁）: 一番強い打点の強さ}"""
    st = {}
    for k in kinds:
        for o in ons.get(k, []):
            b = round(o.beat, 4)
            st[b] = max(st.get(b, 0.0), o.s)
    return st


def accent_at(ons):
    """{拍（4 桁）: 歌・キック・スネアの強さの和}（両手にする所の強さ・intent のアレンジの形と同じ）"""
    st = {}
    for k in ('vocal', 'kick', 'snare'):
        for o in ons.get(k, []):
            b = round(o.beat, 4)
            st[b] = st.get(b, 0.0) + o.s
    return st


def motif_regions(auto, it):
    """同じ意思入れで選んだ自動の打点の同じ振りの印 → [(拍の始まり, 終わり, 印)]（区間は意思入れの表の区間・無ければ打点の最後まで）"""
    occ = {}
    for h in auto:
        m = getattr(h, 'motif', None)
        if m:
            k = (m.get('idx'), m.get('b0'))
            o = occ.setdefault(k, [m, h.beat])
            o[1] = max(o[1], h.beat)
    rs = (it or {}).get('ranges') or []
    out = []
    for (i, b0), (m, last) in occ.items():
        ok = isinstance(i, int) and 0 <= i < len(rs) and abs(float(rs[i]['b0']) - float(b0)) < 1e-6
        out.append((float(b0), float(rs[i]['b1']) if ok else last + 0.01, m))
    return sorted(out, key=lambda t: t[0])


REGION_KEYS = ('mods', 'min_gap', 'variety')            # 区間の指示の印（近くの自動の打点から写す）
POINT_KEYS = ('force_dbl', 'force_strong', 'reentry')   # その打点だけの印（同じ拍の自動の打点から写す）


def base_hits(at, auto, secs, ons, it=None):
    """基準の振り at（swings）→ 派生の元の打点（基準の打点そのもの・両手かは基準のまま）。同じ意思入れで選んだ自動の打点 auto の印を写す:
    同じ拍の物から区間・フレーズ・音の種類と強さ・山の音・途切れの戻り・強い打点・決めた両手、1拍以内の物から区間の指示の印
    （置き方・速さの上限・型の変わり方）、同じ振りの印は区間で（基準の打点が NLM で直されて自動の打点と違っても付く）"""
    from .amount import _sec_phr
    by = {round(h.beat, 4): h for h in auto}
    bs = sorted(by)
    st = strength_at(ons)
    # 自動の同じ振り（automap/repeat.py）の印は写さない: 基準の譜面にくり返しが入っていて、派生は基準の置き方に寄せる（写すと手本に合わせ
    # 直す力と基準に寄せる力がぶつかり、NLM の振りの警告と同じ決まりが出た）
    regs = [r for r in motif_regions(auto, it) if not r[2].get('auto')]
    out = []
    for b, f in at.items():
        h0 = by.get(b)
        if h0 is not None:
            h = rhythm.Hit(h0.beat, len(f), h0.sec_i, h0.phr_i, h0.src, h0.s, h0.midi, h0.accent)
            for k in POINT_KEYS:
                if hasattr(h0, k):
                    setattr(h, k, getattr(h0, k))
            src = h0
        else:
            si, pi = _sec_phr(secs, b)
            h = rhythm.Hit(b, len(f), si, pi, 'base', st.get(b, 0.3))
            j = bisect.bisect_left(bs, b)
            near = [by[x] for x in bs[max(0, j - 1):j + 1] if abs(x - b) <= 1.0 + 1e-6]
            src = min(near, key=lambda q: abs(q.beat - b)) if near else None
        if len(f) == 1 and getattr(h, 'force_dbl', False):
            h.force_dbl = False
        if src is not None:
            for k in REGION_KEYS:
                if hasattr(src, k):
                    setattr(h, k, getattr(src, k))
        for b0, b1, m in regs:
            if b0 - 1e-6 <= b < b1 - 1e-6:
                h.motif = dict(m)
                break
        out.append(h)
    return out


# ---- 同じ音楽の区間（自動の同じ振り・automap/repeat.py）を派生でもそろえる（2026-11-11 利用者「繰り返しの区間に対して、派生の場合も
# 基準のノーツ配置をベースにノーツを増やす事が出来ないだろうか」）。前は派生に印を写さず、上は組の区間に足さない・下は回ごとに別々に
# 間引く・置き方は回ごとに計算し直していた＝派生で手本と同じ置き方の回は 14〜65%（リズムも下では 65〜95%）・Rain の Expert+ は曲の 61% に
# 足せなかった。今は基準でそろっている回に印を付け、足す・間引くはどの回も同じ所（回の頭からの拍）・置き方は手本の回に写す（_fix_motifs）
REP_RHYTHM = 0.9   # 基準で手本の回と打点がこの割合以上同じ回だけそろえる（NLM で直した等で違う回は今まで通り自由に）
REP_PLACE = 0.8    # 〃 置き方（手・マス・向き。左右反転の回は手を入れ替えて反転）
MIRROR_D = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}   # 向きの左右反転（flow.MIRROR_D と同じ・flow は重いので読まない）


def _bar_end(bars, b0, n):
    """拍 b0 から n 小節後の拍（曲の小節の頭の並び bars・b0 が小節の頭でなければ 4 拍×n）"""
    i = bisect.bisect_left(bars, b0 - 1e-6)
    if i < len(bars) and abs(bars[i] - b0) < 1e-6 and i + n < len(bars):
        return float(bars[i + n])
    return b0 + 4.0 * n


def rep_groups(md, used, bars):
    """派生でそろえる組の元 → ([{'name', 'bars', 'occ': [(拍の始まり, 終わり)], 'kinds': ['model'|'same'|'mirror']}], 出どころ)。
    基準の報告（md）の「同じ音楽の区間」の行（repeat.parse_groups＝基準の打点はこの組で写した）・読めなければこの作り直しで同じ曲の流れから
    選び直した組（used＝repeat.apply が使った組・新しく作った基準と同じ）"""
    gs = repeat.parse_groups(md) if md else None
    if gs is not None:
        return [{'name': g['name'], 'bars': g['bars'], 'occ': [(o['b0'], _bar_end(bars, o['b0'], g['bars'])) for o in g['occ']],
                 'kinds': [o['kind'] for o in g['occ']]} for g in gs], '基準の報告'
    out = []
    for g in used or []:
        flip = g.get('flip', 0)
        out.append({'name': g['name'], 'bars': g['bars'], 'occ': [tuple(o) for o in g['occ']],
                    'kinds': ['model' if k == 0 else 'mirror' if k % 2 != flip else 'same' for k in range(len(g['occ']))]})
    return out, '曲の流れから選び直した組（基準の報告が読めない）'


def _span_of(at, a, b):
    return {round(x - a, 4): f for x, f in at.items() if a - 1e-6 <= x < b - 1e-6}


def occ_match(at, model, occ, kind):
    """振り at（swings の形）で、回 occ（拍の始まり, 終わり）が手本の回 model と同じ割合 → (打点（どちらかにある回の頭からの拍のうち
    両方にある割合）, 置き方（両方にある打点のノーツのうち手・マス・向きが同じ割合・kind＝'mirror' は手を入れ替えて左右反転）)"""
    m, o = _span_of(at, *model), _span_of(at, *occ)
    both = set(m) & set(o)
    n = ok = 0
    for x in both:
        for c, (cx, cy, d) in m[x].items():
            want = (1 - c, (3 - cx, cy, MIRROR_D.get(d, d))) if kind == 'mirror' else (c, (cx, cy, d))
            n += 1
            ok += o[x].get(want[0]) == want[1]
    return len(both) / max(1, len(set(m) | set(o))), ok / max(1, n)


def check_groups(groups, at):
    """基準の振り at で、回ごとに手本の回と同じか（打点・置き方）を確かめる → (そろえる組（手本と、同じだった回だけ）, 外した回
    [(組の名前, 回の拍, 打点の一致, 置き方の一致)])。手本に振りが無い組・同じ回が1つも無い組は使わない"""
    used, dropped = [], []
    for g in groups:
        (a0, b0), rest = g['occ'][0], list(zip(g['occ'][1:], g['kinds'][1:]))
        if not _span_of(at, a0, b0):
            continue
        keep = [((a0, b0), 'model')]
        for (a, b), kind in rest:
            rhy, pl = occ_match(at, (a0, b0), (a, b), kind)
            if rhy >= REP_RHYTHM - 1e-9 and pl >= REP_PLACE - 1e-9:
                keep.append(((a, b), kind))
            else:
                dropped.append((g['name'], a, rhy, pl))
        if len(keep) >= 2:
            used.append({'name': g['name'], 'bars': g['bars'], 'occ': [o for o, _ in keep], 'kinds': [k for _, k in keep]})
    return used, dropped


def group_mark(g, gi, k):
    """組 g（番号 gi）の k 回目の打点に付ける自動の同じ振りの印（repeat.apply と同じ形）"""
    return {'group': g['name'], 'key': g['name'], 'variant': 'a', 'mode': None, 'idx': repeat.IDX0 + gi, 'b0': g['occ'][k][0], 'occ': k,
            'mirror': g['kinds'][k] == 'mirror', 'auto': True}


def mark_groups(hits, groups):
    """そろえる組の回の打点に自動の同じ振りの印（ほかの同じ振りの印がある打点は触らない）"""
    for gi, g in enumerate(groups):
        for k, (a, b) in enumerate(g['occ']):
            m = group_mark(g, gi, k)
            for h in hits:
                if a - 1e-6 <= h.beat < b - 1e-6 and not getattr(h, 'motif', None):
                    h.motif = dict(m)
    return hits


def unify_groups(hits, groups, tempo, secs, avoid=()):
    """そろえる組の写す側の回の打点を手本の回と同じ所（回の頭からの拍）に: 手本に無い所の片手の打点は抜き、手本にあって無い所は足す
    （前後が詰まる・avoid の中なら足さない）。基準でも回どうしは 9 割以上同じ（check_groups）だが、基準の入りの前に足した打点などで少し
    違い、違う所では置き方を写せず回の中で振りの順が崩れた（BURN の Hard で NLM の振りの警告）→ (打点, 抜いた数, 足した数)"""
    hs = sorted(hits, key=lambda h: h.beat)
    in_avoid = lambda b: any(a - 1e-6 <= b < c - 1e-6 for a, c in avoid)
    drop, adds = set(), []
    for gi, g in enumerate(groups):
        (a0, e0) = g['occ'][0]
        model = {round(h.beat - a0, 4): h for h in hs if a0 - 1e-6 <= h.beat < e0 - 1e-6}
        for k, (a, b) in enumerate(g['occ'][1:], 1):
            mine = {round(h.beat - a, 4): h for h in hs if a - 1e-6 <= h.beat < b - 1e-6}
            for o, h in mine.items():
                if o not in model and h.hands == 1 and not getattr(h, 'kept', False):
                    drop.add(id(h))
                elif o in model and h.hands != model[o].hands:   # 両手・片手も手本に
                    h.hands = model[o].hands
                    h.force_dbl = getattr(model[o], 'force_dbl', False)
            for o, h0 in model.items():
                if o not in mine and a + o < b - 1e-6 and not in_avoid(a + o):
                    q = rhythm.Hit(a + o, h0.hands, *amount._sec_phr(secs, a + o), h0.src, h0.s, h0.midi, h0.accent)
                    q.motif = group_mark(g, gi, k)
                    adds.append(q)
    hs = [h for h in hs if id(h) not in drop]
    occ = sorted(h.beat for h in hs)
    need = {round(h.beat, 4): amount._need(h) for h in hs}
    free = _gaps_free(occ, need, tempo)
    n_add = 0
    for q in sorted(adds, key=lambda h: h.beat):
        if free(q.beat):
            hs.append(q)
            bisect.insort(occ, q.beat)
            need[round(q.beat, 4)] = amount._need(q)
            n_add += 1
    return sorted(hs, key=lambda h: h.beat), len(drop), n_add


def _in(h, a, b):
    return a - 1e-6 <= h.beat < b - 1e-6


def _flip_one(hs, before, cur, bef, members, sources, beat_of, tempo):
    """片手の打点の数の偶奇を1つ戻す（keep_parity の1か所分）。cur・bef＝{鍵: 打点}（今・足す／間引く前）・members(鍵)＝今の打点のうち
    その鍵の物（組はどの回も）・sources(鍵)＝前の打点のうちその鍵の物・beat_of(鍵)＝目盛りの強さを見る拍 → (打点, 直せたか)。
    弱い方から: 足した片手を1つ抜く → 片手を両手にした所を戻す → 間引いた片手を1つ戻す（前後が空いていれば）→ 両手を片手にした所を戻す"""
    added = [k for k, h in cur.items() if k not in bef and h.hands == 1]
    conv = [k for k, h in cur.items() if k in bef and h.hands == 2 and bef[k].hands == 1]
    gone = [k for k, h in bef.items() if k not in cur and h.hands == 1]
    undbl = [k for k, h in cur.items() if k in bef and h.hands == 1 and bef[k].hands == 2]
    if added:
        k = min(added, key=lambda k: (-amount._lvl(beat_of(k)), cur[k].s, -k))
        drop = {id(h) for h in members(k)}
        return [h for h in hs if id(h) not in drop], True
    if conv:
        for h in members(min(conv, key=lambda k: (cur[k].s, k))):
            h.hands, h.force_dbl = 1, False
        return hs, True
    if gone:
        free = _gaps_free(sorted(h.beat for h in hs), {round(h.beat, 4): amount._need(h) for h in hs}, tempo)
        for k in sorted(gone, key=lambda k: (amount._lvl(beat_of(k)), -bef[k].s, k)):
            src = sources(k)
            if src and all(free(h.beat) for h in src):
                return sorted(hs + [copy.copy(h) for h in src], key=lambda h: h.beat), True
    if undbl:
        for h in members(max(undbl, key=lambda k: (cur[k].s, -k))):
            h.hands = 2
        return hs, True
    return hs, False


def keep_parity(hits, before, groups, tempo):
    """そろえる組の回の中と、回と回の間の片手の打点の数の偶奇を、足す・間引く前（before）と同じに戻す → (打点, 直した所の数)。
    手はそれぞれ振りの向きを交互にするので、両手の向きのそろい方は片手の打点のたびに入れ替わる（_motif_breath）。写す側の回は手本の回の
    置き方に決めるので、手本の入りから写す側の入りまでの片手の数の偶奇が基準と変わると、写す側の入りでそろい方が合わず、振りの順が崩れた
    （回が切れ目なく続く所・Rain の拍 268 → 276 → 284 や 175 では入りの前を抜けない＝NLM の振りの警告）。組の回の中はどの回も同じ所を・
    回と回の間（組の印の無い打点）は1つずつ直す。最初の回より前・最後の回より後は直さない（決めた置き方が無い）"""
    hs = sorted(hits, key=lambda h: h.beat)
    n_fix = 0
    odd = lambda xs, a, b, ok=lambda h: True: sum(1 for h in xs if _in(h, a, b) and h.hands == 1 and ok(h)) % 2
    for g in groups:   # 組の回の中（手本の回で数え、どの回も同じ所を直す）
        a0, e0 = g['occ'][0]
        if odd(before, a0, e0) == odd(hs, a0, e0):
            continue
        cur = {round(h.beat - a0, 4): h for h in hs if _in(h, a0, e0)}
        bef = {round(h.beat - a0, 4): h for h in before if _in(h, a0, e0)}
        at = lambda xs, o: [h for h in xs for a, b in g['occ'] if _in(h, a, b) and abs(h.beat - a - o) < 1e-6]
        hs, ok = _flip_one(hs, before, cur, bef, lambda o: at(hs, o), lambda o: at(before, o), lambda o: a0 + o, tempo)
        n_fix += ok
    spans = sorted(o for g in groups for o in g['occ'])
    plain = lambda h: not getattr(h, 'motif', None)
    for (_, a), (b, _) in zip(spans, spans[1:]):   # 回と回の間（数えるのは全部の片手・直すのは印の無い打点＝利用者の同じ振りも間引くと偶奇が変わる）
        if b <= a + 1e-6 or odd(before, a, b) == odd(hs, a, b):
            continue
        cur = {round(h.beat, 4): h for h in hs if _in(h, a, b) and plain(h)}
        bef = {round(h.beat, 4): h for h in before if _in(h, a, b) and plain(h)}
        hs, ok = _flip_one(hs, before, cur, bef, lambda x: [cur[x]], lambda x: [bef[x]], lambda x: x, tempo)
        n_fix += ok
    return hs, n_fix


def _gaps_free(occ, need, tempo):
    """amount.scale の free と同じ決まり（足す拍 b の前後の打点との間）＝ fn(b) → 足してよいか"""
    def free(b):
        i = bisect.bisect_left(occ, b - 0.75)
        while i < len(occ) and occ[i] <= b + 0.75:
            x = occ[i]
            nd = need.get(round(x, 4), 0.0)
            if abs(x - b) < max(amount.GAP_BEAT, nd) - 1e-6:
                return False
            if tempo is not None and abs(tempo.sec(x) - tempo.sec(b)) < (amount.DBL_SEC if nd else amount.GAP_SEC) - 1e-9:
                return False
            i += 1
        return True
    return free


def _grow_groups(hits, k, groups, cands, bars, secs, tempo, avoid=()):
    """同じ音楽の区間の組に打点を足す: 手本の回の小節ごとに打点の数を k 倍へ（amount.scale と同じ数え方・打点の無い小節は空のまま）。
    足す所は候補（cands＝amount.pool の形）を回の頭からの拍でまとめ、回の半分以上に音の立ち上がりがある所から（段・音のある回の数・強さの
    順）。どの回にも同じ所に足す（リズムのくり返しを崩さない）・どこかの回で前後が詰まる所には足さない・avoid（途切れ・NLM で直した所）の
    中の回には足さない → (打点, {'add': 足した打点の数, 'short': 足りなかった数（手本の回の数え）})"""
    st = {'add': 0, 'short': 0}
    if not groups:
        return hits, st
    hs = sorted(hits, key=lambda h: h.beat)
    occ = [h.beat for h in hs]
    need = {round(h.beat, 4): amount._need(h) for h in hs}
    free = _gaps_free(occ, need, tempo)
    in_avoid = lambda b: any(a - 1e-6 <= b < c - 1e-6 for a, c in avoid)
    added = []
    for gi, g in enumerate(groups):
        spans = g['occ']
        a0, e0 = spans[0]
        pooled = {}
        for c in cands:
            for j, (a, b) in enumerate(spans):
                if a - 1e-6 <= c[2] < b - 1e-6:
                    pooled.setdefault(round(c[2] - a, 4), {})[j] = c
        edges = [a0] + [x for x in bars if a0 + 1e-6 < x < e0 - 1e-6] + [e0]
        sup = (len(spans) + 1) // 2
        carry = 0.0
        for x0, x1 in zip(edges, edges[1:]):
            n_b = sum(1 for h in hs if x0 - 1e-6 <= h.beat < x1 - 1e-6)
            if not n_b:
                continue
            want_f = n_b * k + carry
            want = int(math.floor(want_f + 0.5))
            carry = want_f - want
            if want <= n_b:
                continue
            offs = [(o, d) for o, d in pooled.items() if x0 - a0 - 1e-6 <= o < x1 - a0 - 1e-6 and len(d) >= sup]
            offs.sort(key=lambda od: (min(c[0] for c in od[1].values()), -len(od[1]), -max(c[3].s for c in od[1].values()), od[0]))
            n = 0
            for o, d in offs:
                if n_b + n >= want:
                    break
                tg = [(j, a + o) for j, (a, b) in enumerate(spans) if a + o < b - 1e-6]
                # どこかの回で足せない所（途切れ・NLM で直した所・前後が詰まる）には、どの回にも足さない（1 つの回だけ打点が違うと置き方を
                # 写せず、回の中で振りの順が崩れた＝Rain の Expert で途切れにかかる回だけ足さず、NLM の振りの警告）
                if not tg or any(in_avoid(b) or not free(b) for _, b in tg):
                    continue
                best = min(d.values(), key=lambda c: (c[0], c[1]))[3]
                for j, b in tg:
                    on = d[j][3] if j in d else best
                    si, pi = amount._sec_phr(secs, b)
                    h = rhythm.Hit(b, 1, si, pi, on.kind, on.s, getattr(on, 'midi', 0.0))
                    h.motif = group_mark(g, gi, j)
                    added.append(h)
                    bisect.insort(occ, b)
                    need[round(b, 4)] = 0.0
                    st['add'] += 1
                n += 1
            st['short'] += max(0, want - n_b - n)
    return sorted(hs + added, key=lambda h: h.beat), st


def _bars_of(bars, end):
    edges = list(bars) + [end]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1) if edges[i + 1] > edges[i] + 1e-6]


def _prot(h, heads, firsts):
    """間引かない打点: 小節の頭・区間の頭（区間の最初の打点）・途切れの戻り・キックで決めた所・同じ振りの区間の最初・残したノーツ"""
    return (getattr(h, 'kept', False) or getattr(h, 'reentry', False) or getattr(h, 'force_strong', False)
            or round(h.beat, 4) in heads or id(h) in firsts)


def _del_key(h, st, fast=(), nest=None):
    """間引く順（小さい方から）: 両手のすぐ隣（fast＝同じ手が最短の間より速く続く打点）→ 間の難易度に無い打点・下の難易度にもある打点は
    後（nest＝(上, 下) の拍の集まり・入れ子にする）→ 目盛りの弱い所（3連符など → 1/4 拍 → 半拍の裏 → 拍の頭）・強さの弱い物・後ろの物"""
    b = round(h.beat, 4)
    up, lo = nest or (None, None)
    return (id(h) not in fast, up is None or b in up, lo is not None and b in lo, -amount._lvl(h.beat), h.s + st.get(b, 0.0), -h.beat)


def _fast_ids(hits, tempo, gap):
    """両手の前後 gap 秒より近い片手の打点の id（両手で両方の手が振った直後・直前なので、どちらの手でも同じ手が速く続く）"""
    hs = sorted(hits, key=lambda h: h.beat)
    out = set()
    for i, h in enumerate(hs):
        if h.hands != 1:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(hs) and hs[j].hands == 2 and abs(tempo.sec(hs[j].beat) - tempo.sec(h.beat)) < gap - 1e-9:
                out.add(id(h))
    return out


def _thin_bars(hs, k, spans, heads, firsts, st, fast=(), nest=None):
    """小節ごとに打点の数を k 倍へ（両手と間引かない打点は残す・端数は次の小節へ送る）→ 消す打点の id の集まり。
    両手のすぐ隣（fast）は数によらず消す（下の難易度で同じ手が速く続かないように・ほかの小節の倍率は thin が合わせ直す）"""
    drop, carry, i = set(), 0.0, 0
    hs = sorted(hs, key=lambda h: h.beat)
    for a, b in spans:
        bh = []
        while i < len(hs) and hs[i].beat < b - 1e-6:
            if hs[i].beat >= a - 1e-6:
                bh.append(hs[i])
            i += 1
        if not bh:
            continue
        want_f = len(bh) * k + carry
        want = int(math.floor(want_f + 0.5))
        carry = want_f - want
        order = sorted((h for h in bh if h.hands == 1 and not _prot(h, heads, firsts)), key=lambda h: _del_key(h, st, fast, nest))
        n = max(0, len(bh) - want)
        for j, h in enumerate(order):
            if j < n or id(h) in fast:
                drop.add(id(h))
    return drop


def _units(hits):
    """同じ振りの打点をまとめる → (同じ振りでない打点, {まとまり: {区間の頭: [打点]}})"""
    free, mot = [], {}
    for h in hits:
        m = getattr(h, 'motif', None)
        if m and not getattr(h, 'kept', False):
            mot.setdefault(m.get('key'), {}).setdefault(m['b0'], []).append(h)
        else:
            free.append(h)
    return free, mot


def _off(h):
    return round(h.beat - h.motif['b0'], 4)


def _model(occs):
    """同じ振りのまとまりの手本にする回（打点の一番多い回・同じなら前の回）"""
    return min(occs.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _dbl_score(h, acc, heads, firsts):
    """両手のままにしたい強さ（小さい方から片手にする）"""
    return (acc.get(round(h.beat, 4), 0.0) + h.s + 0.5 * (amount._lvl(h.beat) == 0) + 1.0 * (round(h.beat, 4) in heads)
            + 2.0 * (id(h) in firsts or getattr(h, 'reentry', False)) + 1.0 * bool(getattr(h, 'force_dbl', False)))


def _thin_once(hits, k, dbl_share, spans, heads, st, acc, tempo, gap, nest=None):
    """1回の間引き（倍率 k・両手の割合の目安 dbl_share・gap＝派生の同じ手の最短の間）→ (打点, 消した数, 片手にした両手の数)"""
    fast = _fast_ids(hits, tempo, gap)
    free, mot = _units(hits)
    firsts, seen = set(), set()
    for h in sorted(free, key=lambda h: h.beat):
        if h.sec_i not in seen:
            seen.add(h.sec_i)
            firsts.add(id(h))
    drop = _thin_bars(free, k, spans, heads, firsts, st, fast, nest)
    for key, occs in mot.items():   # 同じ振り: 手本にする回で消す所を決め、どの回も同じ所（区間の頭からの拍）を消す
        _, mh = _model(occs)
        mf = {id(min(mh, key=lambda h: h.beat))}
        # 回の中は小節で分けず1つにまとめて数える（短い区間が小節の境目をまたぐと、小節ごとの端数で消す所が決まり、入れ子の順が効かなかった）
        whole = [(min(h.beat for h in mh) - 1e-3, max(h.beat for h in mh) + 1e-3)]
        md = _thin_bars(mh, k, whole, heads, mf, st, fast, nest)
        offs = {_off(h) for h in mh if id(h) in md}
        for hs in occs.values():
            first = min(hs, key=lambda h: h.beat)
            for h in hs:
                if _off(h) in offs and h is not first and not getattr(h, 'force_strong', False):
                    drop.add(id(h))
    out = [h for h in hits if id(h) not in drop]
    # 両手を片手に（人の譜面の両手の割合の比へ）: 弱い両手から。同じ振りの両手は、どの回も同じ所を
    own = [h for h in out if not getattr(h, 'kept', False)]
    n2, want2, conv = sum(h.hands == 2 for h in own), int(round(dbl_share * len(own))), 0
    if n2 > want2:
        free2, mot2 = _units(out)
        cand = [([h], _dbl_score(h, acc, heads, firsts)) for h in free2 if h.hands == 2 and not getattr(h, 'kept', False)]
        for occs in mot2.values():
            by_off = {}
            for hs in occs.values():
                for h in hs:
                    if h.hands == 2:
                        by_off.setdefault(_off(h), []).append(h)
            for hs in by_off.values():
                cand.append((hs, sum(_dbl_score(h, acc, heads, set()) for h in hs) / len(hs) + 0.5))
        for hs, _ in sorted(cand, key=lambda t: (t[1], t[0][0].beat)):
            if n2 <= want2:
                break
            for h in hs:
                h.hands, h.force_dbl = 1, False
            n2 -= len(hs)
            conv += len(hs)
    return out, len(hits) - len(out), conv


def _copy(hits):
    return [copy.copy(h) for h in hits]


def thin(hits, ratio, bars, end, tempo, ons, base, target, nest=None):
    """下の難易度: 基準の打点を弱い物から間引く（小節ごとに同じ倍率・小節の頭・区間の頭・途切れの戻りは残す・同じ振りはどの回も同じ所を）。
    両手は人の譜面の両手の割合の比（HUMAN の double）で片手にする。1秒のノーツが基準の ratio 倍になるまで倍率を動かす。
    nest＝(上, 下): 基準との間の難易度（上）・下の難易度（下）の打点の拍の集まり（どちらも無ければ None）＝上に無い打点から・下にある打点は
    後に間引く（人の譜面は易しい難易度の打点の 97〜98% が1つ上にもある・NLM の譜面チェックの timingDifference）
    → (打点, 報告の数 {target, before, after, k, del, conv, far, …})"""
    base_nps = amount.measure(hits, tempo)
    goal = base_nps * ratio
    nh = [h for h in hits if not getattr(h, 'kept', False)]
    dbl_share = sum(h.hands == 2 for h in nh) / max(1, len(nh)) * human_rel(base, target, 'double')
    spans = _bars_of(bars, end)
    heads = {round(a, 4) for a, _ in spans}
    st, acc = strength_at(ons), accent_at(ons)
    gap = min_gap(base, target)
    k, best, tried = ratio, None, []
    for _ in range(12):
        k = min(1.0, max(0.05, k))
        if any(abs(k - x) < 1e-6 for x in tried):
            break
        tried.append(k)
        out, nd, nc = _thin_once(_copy(hits), k, dbl_share, spans, heads, st, acc, tempo, gap, nest)
        v = amount.measure(out, tempo)
        if best is None or abs(v - goal) < abs(best[1] - goal) - 1e-12:
            best = (out, v, k, nd, nc)
        if abs(v - goal) <= TOL * goal or v <= 0:
            break
        k = k * goal / v
    out, v, k, nd, nc = best
    return out, {'target': goal, 'before': base_nps, 'after': v, 'k': k, 'del': nd, 'conv': nc, 'add': 0, 'short': 0, 'dbl': 0,
                 'dbl_share': dbl_share, 'far': abs(v - goal) > amount.FAR * goal}


def _dbl_ok(h, hs, idx, tempo):
    """片手の打点 h を両手にしてよいか: 前後 1/2 拍（と 0.12 秒）に打点が無い・前後の両手との間の片手の打点が偶数個（DBL_EVEN_SPAN 拍まで）"""
    i = idx[id(h)]
    for j in (i - 1, i + 1):
        if 0 <= j < len(hs):
            q = hs[j]
            if abs(q.beat - h.beat) < DBL_FREE - 1e-6 or abs(tempo.sec(q.beat) - tempo.sec(h.beat)) < DBL_SEC:
                return False
    for step in (-1, 1):
        n, j = 0, i + step
        while 0 <= j < len(hs) and abs(hs[j].beat - h.beat) <= DBL_EVEN_SPAN:
            if hs[j].hands == 2:
                if n % 2:
                    return False
                break
            n += 1
            j += step
    return True


def _dbl_units(own, acc, in_avoid):
    """片手を両手にする候補のまとまり → [(打点の並び, 強さ)]（強い順に使う）。ふつうの打点は1つずつ・自動の同じ振りの組（派生でそろえる組）は
    回の頭からの拍が同じ打点をどの回もまとめて（どの回にもある所だけ）。利用者の同じ振りの打点は両手にしない（今まで通り）"""
    sc = lambda h: acc.get(round(h.beat, 4), 0.0) + 0.3 * (amount._lvl(h.beat) == 0)
    ok = lambda h: h.hands == 1 and amount._lvl(h.beat) <= 1 and not in_avoid(h.beat)
    units = [([h], sc(h)) for h in own if ok(h) and not getattr(h, 'motif', None)]
    n_occ, by = {}, {}
    for h in own:
        m = getattr(h, 'motif', None)
        if m and m.get('auto'):
            n_occ.setdefault(m['key'], set()).add(m['b0'])
            if ok(h):
                by.setdefault((m['key'], round(h.beat - m['b0'], 4)), []).append(h)
    for (key, _), hs in by.items():
        if len({h.motif['b0'] for h in hs}) == len(n_occ[key]):
            units.append((sorted(hs, key=lambda h: h.beat), sum(sc(h) for h in hs) / len(hs)))
    return sorted(units, key=lambda u: (-u[1], u[0][0].beat))


def thicken(hits, ratio, bars, end, tempo, ons, secs, base, target, avoid=(), groups=()):
    """上の難易度: 基準の打点は全部残し、拾った候補から打点を足す（amount.pool の段の順＝半拍の歌・キック・スネア・楽器 → 半拍の
    ハイハット → 1/4 拍・小節ごとに同じ倍率＝amount.scale）。片手の強い打点を両手に（人の譜面の両手の割合の比へ）。avoid＝足さない
    範囲（途切れ・利用者の同じ振りの区間・残したクリップ）。groups＝派生でそろえる同じ音楽の区間の組（check_groups・印は mark_groups）:
    組の回にはどの回も同じ所に足し（_grow_groups）、両手もどの回も同じ所を → (打点, 報告の数)"""
    base_nps = amount.measure(hits, tempo)
    goal = base_nps * ratio
    nh = [h for h in hits if not getattr(h, 'kept', False)]
    dbl_share = min(0.35, sum(h.hands == 2 for h in nh) / max(1, len(nh)) * human_rel(base, target, 'double'))
    spans = [o for g in groups for o in g['occ']]
    in_g = lambda b: any(a - 1e-6 <= b < c - 1e-6 for a, c in spans)
    pool = amount.pool(ons, tempo, end, avoid)
    cands = [c for c in pool if not in_g(c[2])] if spans else pool   # 組の回の中は _grow_groups が（回ごとに別々に足さない）
    g_cands = [c for c in pool if in_g(c[2])]
    acc = accent_at(ons)
    in_avoid = lambda b: any(a - 1e-6 <= b < c - 1e-6 for a, c in avoid)
    k, best, tried = ratio, None, []
    for _ in range(12):
        k = min(amount.K_RANGE[1], max(1.0, k))
        if any(abs(k - x) < 1e-6 for x in tried):
            break
        tried.append(k)
        out, stg = _grow_groups(_copy(hits), k, groups, g_cands, bars, secs, tempo, avoid)
        out, sti = amount.scale(out, k, bars, end, cands, secs, tempo)
        sti = {'add': sti['add'] + stg['add'], 'short': sti['short'] + stg['short'], 'g_add': stg['add']}
        hs = sorted(out, key=lambda h: h.beat)
        idx = {id(h): i for i, h in enumerate(hs)}
        own = [h for h in hs if not getattr(h, 'kept', False)]
        n2, want2, nd = sum(h.hands == 2 for h in own), int(round(dbl_share * len(own))), 0
        if n2 < want2:
            for unit, _ in _dbl_units(own, acc, in_avoid):
                if n2 >= want2:
                    break
                done = []
                for h in unit:   # 1つずつ確かめて両手に（同じ組の回どうしが近いと、前の回を両手にしたことで後の回の偶奇が変わる）
                    if not _dbl_ok(h, hs, idx, tempo):
                        break
                    h.hands = 2
                    done.append(h)
                if len(done) < len(unit):
                    for h in done:
                        h.hands = 1
                    continue
                n2 += len(unit)
                nd += len(unit)
        v = amount.measure(hs, tempo)
        prev = best[1] if best else None
        if best is None or abs(v - goal) < abs(best[1] - goal) - 1e-12:
            best = (hs, v, k, sti, nd)
        if abs(v - goal) <= TOL * goal:
            break
        if prev is not None and abs(v - prev) < 1e-9 and v < goal:
            break   # 倍率を上げても増えない（拾える打点が足りない）
        nk = k * goal / v if v > 0 else k * 1.5
        if (nk > k and k >= amount.K_RANGE[1]) or (nk < k and k <= 1.0):
            break
        k = nk
    hs, v, k, sti, nd = best
    info = {'target': goal, 'before': base_nps, 'after': v, 'k': k, 'del': 0, 'conv': 0, 'add': sti['add'], 'short': sti['short'],
            'g_add': sti['g_add'], 'dbl': nd, 'dbl_share': dbl_share, 'far': abs(v - goal) > amount.FAR * goal}
    if info['far'] and v < goal:
        info['why'] = _short_why(hits, hs, tempo, pool, avoid)
    return hs, info


def _short_why(hits, out, tempo, pool, avoid):
    """足りなかった訳の数（報告の文の元）: 1/4 拍の升を全部埋めた時の1秒のノーツ・足さない範囲が曲に占める割合・拾った候補のうち使った数"""
    hs = [h for h in hits if tempo.sec(h.beat) >= amount.T_MIN]
    if len(hs) < 2:
        return {}
    b0, b1 = min(h.beat for h in hs), max(h.beat for h in hs)
    span = tempo.sec(b1) - tempo.sec(b0)
    cover = sum(max(0.0, min(c, b1) - max(a, b0)) for a, c in _merge_spans(avoid)) / max(1e-9, b1 - b0)
    got = {round(h.beat, 4) for h in out}
    return {'ceil': (b1 - b0) * 4 / span if span > 0 else 0.0, 'avoid': cover, 'pool': len(pool),
            'used': sum(1 for c in pool if round(c[2], 4) in got)}


def _merge_spans(spans):
    """重なる範囲をまとめる [(a, b)]"""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


# ---- 流れの計算 ----
W_RESET = 60.0   # 派生の流れの計算の「休みの後で振りの順を戻す」減点（基準に寄せる重みがあると、休みの後で振りの順を戻して基準の
                 # 向きに合わせ、NLM の振りの警告が出た・こだまの Expert で 1）。1回目の計算の手と振りの向きのまま狙いを基準のマスに
                 # し直してもう一度計算する案は、同じ置き方の割合がほぼ変わらず（48.5〜72%）時間だけ倍になったので捨てた
                 # 30 → 60（2026-11-10）: 流れの計算の先読みが振りの順のやり直しを見込むようにしたら、こだまの Expert で 1（右手の拍 336→339・
                 # 間引いてできた 1.5 秒の間）。基準の作り直し（__main__.W_RESET）も 60


# ---- 報告の数 ----

def measures(notes, tempo):
    """ノーツ → {events, nps, double（打点あたり）, quarter（打点の間が 1/4 拍の割合）, gap_min・gap_q10（同じ手の振りの間の
    一番短い・速い方から1割・秒）}"""
    at = swings(notes, tempo)
    bs = sorted(at)
    r = {'events': len(bs), 'nps': stats.summarize(notes, tempo).get('nps', 0.0)}
    r['double'] = sum(len(f) == 2 for f in at.values()) / max(1, len(bs))
    gaps = [b - a for a, b in zip(bs, bs[1:])]
    r['quarter'] = sum(abs(g - 0.25) < 0.01 for g in gaps) / max(1, len(gaps))
    hg = []
    for c in (0, 1):
        ts = [tempo.sec(b) for b in bs if c in at[b]]
        hg += [y - x for x, y in zip(ts, ts[1:])]
    hg.sort()
    r['gap_min'] = hg[0] if hg else None
    r['gap_q10'] = hg[len(hg) // 10] if hg else None
    return r


def nest_pick(proj, base, target, extra=()):
    """入れ子にする相手の名前 (上, 下): 上＝基準と派生の間の難易度でノーツのある物（extra＝同じ展開で一緒に作る派生も数える）のうち
    派生に一番近い物・下＝派生より下の難易度でノーツのある物のうち一番近い物（extra は数えない＝1つずつ作る順では後で作る）。
    2026-11-02: 上を「基準に一番近い物」で選んでいた（Expert+ から Normal を作ると Expert に入れ子・間の Hard には入れ子にならない）のを、
    説明どおり派生に一番近い物に直した（NLM の timingDifference は1つ上の難易度と比べる）"""
    i, j = diffs.ORDER.index(diffs.name_of(target)), diffs.ORDER.index(diffs.name_of(base))
    has = lambda d: (diffs.key(d) in proj['difficulties'] and diffs.notes_in(proj['difficulties'][diffs.key(d)]))
    lo_i, hi_i = sorted((i, j))
    mid = [d for d in diffs.ORDER[lo_i + 1:hi_i] if d in extra or has(d)]
    below = [d for d in diffs.ORDER[:i] if has(d)] if i < j else []
    up = (mid[0] if i < j else mid[-1]) if mid else None
    return up, (below[-1] if below else None)


def same_place(base_at, notes, tempo):
    """派生のノーツのうち基準と同じ拍・手・マス・向きの割合（same）・同じ拍・手・マスの割合（cell）と、派生の打点のうち基準にもある割合（common）"""
    d = swings(notes, tempo)
    n = sum(len(f) for f in d.values())
    same = sum(1 for b, f in d.items() for c, v in f.items() if base_at.get(b, {}).get(c) == v)
    cell = sum(1 for b, f in d.items() for c, v in f.items() if (base_at.get(b, {}).get(c) or (None, None))[:2] == v[:2])
    common = sum(1 for b in d if b in base_at)
    return {'same': same / max(1, n), 'cell': cell / max(1, n), 'common': common / max(1, len(d)), 'events': len(d),
            'base_events': len(base_at)}
