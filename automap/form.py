"""曲の流れの表: 分けた音から測った曲の中身（music.analyze）を、フレーズ〜区間の「まとまり」の並びにする。

まとまりごとに: くり返しの記号（同じ音楽＝同じ記号・少し変わった物＝ダッシュ付き）・盛り上がりの段階 0〜3・歌があるか・主役のパート・できごと。
NLM の区間の名前には頼らない（マーカーは区切りの候補の1つ・★ 静 ドラム 等の人の書き込みはそのまま効く）。
同じ形の表を、人が別の UI で打ち込む案（次点）でも出す＝ノーツを作る側は1つで済む（docs/方針.md 6.15）。

決め方の元（docs/方針.md 6.15・6.16）:
- 区切り: ドラムの打ち方の変わり目・音が一回途切れる所（利用者「そこで一つ区切り」）・歌の入り／抜け・転調・マーカーの区間の頭。
  ドラムの変わり目はサビ等の1小節前の溜めの小節に出ることが多い（利用者「歌が変わる直前の合図」）ので、次の小節に別の手がかりがあればそこへ移す
  （移さないと曲B の1回目のサビの頭が1小節ずれ、2回目のサビと同じ記号にならなかった）。まとまりは4小節を基本にそろえる（長さがそろわないと
  同じサビでも並びを比べられない）。
- 盛り上がり: ドラムの勢いと楽器の多さ（人の譜面 144 曲で密度・両手と相関があったのはこの2つ。歌の広がりは弱い）。
  転調した所から 8 小節は1段上げる（利用者「転調の瞬間にギアが上がるが、ずっとではない」）。
- くり返し: 歌のあるまとまりは歌の記号、無いまとまりは伴奏の記号の並びを、前のまとまりと小節ごとに比べる。
"""
from dataclasses import dataclass, field

import numpy as np

from . import rhythm

LEVELS = 4


@dataclass
class Block:
    b0: float             # 拍
    b1: float
    i0: int               # 小節の番号（music.analyze の bars）
    i1: int
    group: str = ''       # くり返しの記号（'A'・"A'"・'B' …）
    base: str = ''        # ダッシュを除いた記号（テーマはこれで選ぶ）
    nth: int = 0          # 同じ base の何回目か
    level: int = 1        # 盛り上がりの段階 0〜3
    tension: float = 0.0  # 盛り上がりの値（ドラムの勢いと楽器の多さの z の平均）
    vocal: bool = False
    lead: str = ''        # 'vocal'・'inst'（旋律楽器）・'drums'
    why: list = field(default_factory=list)       # 頭の区切りの理由
    breaks: list = field(default_factory=list)    # 中の途切れ [(拍, 長さ, 種類)]
    mod: bool = False     # 転調の後 8 小節に掛かる


def _rz(x):
    x = np.asarray(x, float)
    ok = ~np.isnan(x)
    if ok.sum() < 4:
        return np.zeros_like(x)
    q1, med, q3 = np.percentile(x[ok], [25, 50, 75])
    return (x - med) / ((q3 - q1) / 1.35 + 1e-9)


def bar_tension(mu):
    """小節ごとの盛り上がり（ドラムの勢いと楽器の多さの z の平均。ドラムがほぼ鳴っていない小節は −3）"""
    it = mu['inten']
    drum = np.array([np.nan if v is None else v for v in it['drum']], float)
    bands = _rz([np.nan if v is None else v for v in it['bands']])
    t = 0.5 * np.where(np.isnan(drum), -3.0, drum) + 0.5 * np.nan_to_num(bands, nan=-3.0)
    return t


def boundaries(mu, markers, n_beats):
    """小節の番号 → (区切りの強さ, [理由])。頭の小節（0）は必ず区切り"""
    bars = mu['bars']
    nb = len(bars)
    sc = {0: [9.0, ['曲の頭']]}

    def add(i, s, why):
        if 0 < i < nb:
            e = sc.setdefault(i, [0.0, []])
            e[0] += s
            e[1].append(why)
    for i in mu['inten']['drum_change']:
        add(i, 2.0, 'ドラムの変わり目')
    head = lambda b: int(np.argmin([abs(x - b) for x in bars]))
    for br in mu['breaks']:   # 途切れの後の最初の小節の頭
        end = br['beat'] + br['len']
        i = next((k for k, x in enumerate(bars) if x >= end - 1.0), None)
        if i is not None:
            add(i, 2.0, '途切れ')
    sing = np.array(mu['inten']['sing'], float)
    von = sing >= 0.5
    for i in range(1, nb - 1):
        if von[i] != von[i - 1] and von[i] == von[i + 1]:
            add(i, 1.5, '歌の入り' if von[i] else '歌の抜け')
    sh = mu['shift']
    for i in range(1, nb):
        if sh[i] != sh[i - 1]:
            add(i, 2.0, '転調')
    for m in markers or []:
        if not isinstance(m.get('beat'), (int, float)):
            continue
        nm, _ = rhythm.parse_marker(m.get('name'))
        if nm:
            i = head(float(m['beat']))
            if abs(bars[i] - float(m['beat'])) <= 1.0:
                add(i, 1.5, f'マーカー「{nm}」')
    # ドラムの変わり目だけの小節の次に別の手がかりがあれば、変わり目は次の小節の予告（溜め）とみなして移す
    for i in sorted(sc):
        if i in sc and sc[i][1] == ['ドラムの変わり目'] and i + 1 in sc and 'ドラムの変わり目' not in sc[i + 1][1]:
            sc[i + 1][0] += sc[i][0]
            sc[i + 1][1].insert(0, 'ドラムの変わり目（1小節前）')
            del sc[i]
    return sc


def build(mu, markers, n_beats, min_bars=2, max_bars=4, thr=1.5):
    """music.analyze の結果とマーカー → [Block]"""
    bars = mu['bars']
    nb = len(bars)
    sc = boundaries(mu, markers, n_beats)
    cut = sorted(i for i, (s, _) in sc.items() if s >= thr)
    # 近すぎる区切り（min_bars 未満）は弱い方を捨てる（同じなら後ろを捨てる＝溜めの小節は前のまとまりの終わり）
    changed = True
    while changed:
        changed = False
        for k in range(1, len(cut)):
            if cut[k] - cut[k - 1] < min_bars:
                drop = cut[k] if sc[cut[k]][0] <= sc[cut[k - 1]][0] or cut[k - 1] == 0 else cut[k - 1]
                cut.remove(drop)
                changed = True
                break
    edges = cut + [nb]
    spans = []
    for a, b in zip(edges, edges[1:]):
        if b - a <= max_bars:
            spans.append((a, b))
            continue
        k = a
        while k < b:   # 長いまとまりは頭から max_bars 小節ずつ（端が短ければ前にまとめる）
            e = min(b, k + max_bars)
            if b - e < min_bars:
                e = b
            spans.append((k, e))
            k = e
    end_beat = lambda i: bars[i] if i < nb else bars[-1] + 4
    out = [Block(float(bars[a]), float(end_beat(b)), a, b, why=sc.get(a, [0, []])[1] if a in cut else ['4小節ごと']) for a, b in spans]
    _fill(out, mu, n_beats)
    return out


def _seq(mu, blk, key):
    return mu['lab'][key][blk.i0:blk.i1]


def _match(a, b):
    """2つの記号の並びの一致（頭からそろえて・音の無い小節は数えない）"""
    n = min(len(a), len(b))
    pairs = [(x, y) for x, y in zip(a[:n], b[:n]) if x >= 0 and y >= 0]
    if not pairs or n < max(len(a), len(b)) * 0.5:
        return 0.0
    return sum(x == y for x, y in pairs) / max(len(a), len(b))


def _fill(blocks, mu, n_beats):
    it = mu['inten']
    t = bar_tension(mu)
    sing = np.array(it['sing'], float)
    lead = np.array([0.0 if v is None else v for v in it['lead']], float)
    for b in blocks:
        r = slice(b.i0, b.i1)
        b.tension = float(np.mean(t[r]))
        b.vocal = float(np.mean(sing[r])) >= 0.5
        b.lead = 'vocal' if b.vocal else 'inst' if float(np.mean(lead[r])) >= 0.1 else 'drums'
        b.breaks = [(x['beat'], x['len'], x['kind']) for x in mu['breaks'] if b.b0 - 1e-6 <= x['beat'] < b.b1 - 1e-6]
    # 盛り上がりの段階: 小節の値の 25・50・80% で区切る
    q = np.percentile(t, [25, 50, 80])
    for b in blocks:
        b.level = int(np.searchsorted(q, b.tension))
    # 転調した所から 8 小節は1段上げる
    sh = mu['shift']
    for i in range(1, len(sh)):
        if sh[i] != sh[i - 1] and sh[i] != 0:
            for b in blocks:
                if b.i0 < i + 8 and b.i1 > i:
                    b.mod = True
                    b.level = min(LEVELS - 1, b.level + 1)
    # くり返しの記号
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    count, nxt = {}, 0
    for k, b in enumerate(blocks):
        key = 'mel' if b.vocal else 'acc'
        best, bj = 0.0, None
        for j in range(k):
            p = blocks[j]
            if p.vocal != b.vocal:
                s = _match(_seq(mu, b, 'acc'), _seq(mu, p, 'acc')) * 0.8
            else:
                s = max(_match(_seq(mu, b, key), _seq(mu, p, key)), 0.8 * _match(_seq(mu, b, 'acc'), _seq(mu, p, 'acc')))
            if s > best + 1e-9:
                best, bj = s, j
        if bj is not None and best >= 0.5:
            b.base = blocks[bj].base
            b.group = b.base if best >= 0.75 else b.base + "'"
        else:
            b.base = letters[nxt % 26] + ('' if nxt < 26 else str(nxt // 26 + 1))
            b.group = b.base
            nxt += 1
        b.nth = count.get(b.base, 0)
        count[b.base] = b.nth + 1


def table(blocks, bpm, lead_ms):
    """曲の流れの表（Markdown）"""
    sec = lambda x: x * 60 / bpm - lead_ms / 1000
    fm = lambda s: f'{int(max(0, s)) // 60}:{max(0, s) % 60:04.1f}'
    rows = ['| 時刻 | 拍 | 小節 | 記号 | 段階 | 盛り上がり | 主役 | 区切りの理由 | できごと |', '|---|---|---|---|---|---|---|---|---|']
    for b in blocks:
        ev = [f'途切れ {fm(sec(x))}（{ln:g}拍{"" if k == "all" else "・ドラムだけ"}）' for x, ln, k in b.breaks]
        if b.mod:
            ev.append('転調の後')
        rows.append(f'| {fm(sec(b.b0))} | {b.b0:g}〜{b.b1:g} | {b.i1 - b.i0} | {b.group} | {b.level} | {b.tension:+.2f} | '
                    f'{ {"vocal": "歌", "inst": "旋律楽器", "drums": "ドラム・伴奏"}[b.lead]} | {"・".join(b.why)} | {"・".join(ev)} |')
    return '\n'.join(rows)


# ---- 譜面づくりへ（試作4 で作り、試作5 で使う） ----

QUIET = -2.5   # これより低い盛り上がり（ドラムがほぼ抜けた所＝落ちサビ・終わり）は、1拍に1つまでの小さな振り


def sections(blocks, markers, end_beat):
    """まとまり → rhythm.Section（名前＝ダッシュを除いた記号・フレーズはまとまり1つ）。人の書き込み（★・静・ドラム・歌・※・ここから）は
    入っているまとまりの tags へ（sections_from_markers と同じ形: そのマーカーから次のマーカーまで）"""
    ms = sorted((m for m in markers or [] if isinstance(m.get('beat'), (int, float))), key=lambda m: m['beat'])
    heads = [(float(m['beat']), *rhythm.parse_marker(m.get('name'))) for m in ms]
    out = []
    for b in blocks:
        s = rhythm.Section(b.base, b.b0, min(b.b1, end_beat), vocal=b.vocal, nth=b.nth)
        s.phrases = [(s.b0, s.b1)]
        out.append(s)
    for i, (beat, nm, tags) in enumerate(heads):
        until = heads[i + 1][0] if i + 1 < len(heads) else float(end_beat)
        for s in out:
            if s.b0 - 1e-6 <= beat < s.b1 - 1e-6:
                s.tags += [(beat, t, until) for t in tags]
    last = {}
    for k, s in enumerate(out):
        last[s.name] = k
    for k, s in enumerate(out):
        s.last = last[s.name] == k
    return out


def plan(blocks):
    """密度と両手（rhythm.choose_hits の plan）。人の譜面 144 曲: 盛り上がりは密度と両手で出す（6.16）。
    密度は試作3 と同じ決め方（歌・ドラムの打点をそのまま拾う）で、もう段階 0→3 で 4 割上がる（曲B 1.59→2.18／拍・人の譜面は 3 割）ので変えない。
    最初は段階 0 を「強い打点だけ」にしたら 1.0／拍まで減り、差が人の譜面よりずっと大きくなった。とても静かな所（ドラムが抜けた所）だけ 1拍に1つまで。
    両手を盛り上がりで足す: 段階 2＝小節の頭・3＝小節の頭と真ん中（キックかシンバルのある所）。段階 2 以上はフレーズの頭も両手"""
    return {si: {'lvl': 0 if b.tension < QUIET else 2 if b.level >= 3 else 1, 'sparse': b.tension < QUIET, 'big': b.level >= 2,
                 'dbl': {0: 0, 1: 0, 2: 1, 3: 2}[b.level]} for si, b in enumerate(blocks)}


def character(blocks):
    """記号 → テーマの性格（theme.WANT のキー）。その記号の一番高い段階と歌の有無で（区間の名前は見ない）"""
    top, voc = {}, {}
    for b in blocks:
        top[b.base] = max(top.get(b.base, 0), b.level)
        voc[b.base] = voc.get(b.base, False) or b.vocal
    out = {}
    for k in top:
        if voc[k]:
            out[k] = 'big' if top[k] >= 3 else 'build' if top[k] == 2 else 'calm'
        else:
            out[k] = 'drive' if top[k] >= 2 else 'simple'
    return out


def palette_order(blocks, chars):
    """曲に出てくる性格の順（テーマは性格ごとに主・副の2つ＝1曲のテーマを絞る・6.18）"""
    out = []
    for b in blocks:
        if chars[b.base] not in out:
            out.append(chars[b.base])
    return out


def palette_assign(blocks, chars, pal):
    """記号 → (まとまりの頭のテーマ, 記号 → テーマの並び)。pal＝{性格: [テーマ k 個]}。同じ性格の記号は出てきた順に i 番目から始めて
    k 個を順に回す（まとまりの中で切り替える時はこの順）。同じ記号は毎回同じ並び＝同じ音楽には同じ展開"""
    first, seq, seen = {}, {}, {}
    for b in blocks:
        if b.base in first:
            continue
        c = chars[b.base]
        i = seen.get(c, 0)
        seen[c] = i + 1
        ts = pal[c]
        seq[b.base] = [ts[(i + j) % len(ts)] for j in range(len(ts))]
        first[b.base] = seq[b.base][0]
    return first, seq


def mix_guides(blocks, mu, seq):
    """小節ごとのテーマ（試作5）: まとまりの中は1小節ごとに、記号のテーマの並び（palette_assign の seq）を順に回す。
    ただし同じまとまりの中で同じ音楽の小節がまた出たら、前のその小節と同じテーマ（1小節のリフのくり返し等）。同じ記号のまとまりは毎回同じ並び。
    小節の音楽の記号だけで選ぶ（前の --switch label・除いた）と、くり返しの多い音楽（サビのループ等）に割り当てた1〜2個のテーマばかりになり、
    曲どうしが似た（3振りの並びの重なり 32% → 38%）。→ {小節の番号: (テーマの番号, {0: 左手の型, 1: 右手の型}, 変え方)}"""
    from . import theme
    out = {}
    for b in blocks:
        ts = seq[b.base]
        seen, k = {}, 0
        for i in range(b.i0, b.i1):
            lab = mu['lab']['mel'][i] if b.vocal and mu['lab']['mel'][i] >= 0 else mu['lab']['acc'][i]
            if lab >= 0 and lab in seen:
                j = seen[lab]
            else:
                j = k % len(ts)
                k += 1
                if lab >= 0:
                    seen[lab] = j
            th = ts[j]
            tfn = 'calm' if b.tension < QUIET else 'swap' if b.group.endswith("'") and th.a != th.b else 'base'
            a, bb = theme.transform(th, tfn)
            out[i] = (300000 + i, {0: theme.mirror(bb), 1: a}, tfn)
    return out


def guides(secs, blocks, chosen):
    """まとまりごとの (テーマの番号, {0: 左手の型, 1: 右手の型}, 変え方)＝まとまりの頭のテーマ（chosen＝記号 → テーマ・style.pick）。
    打点のテーマは小節ごと（mix_guides）で、これは小節のテーマが無い打点の控えと報告の区間の表に使う。テーマの番号はまとまりごと。
    上の段まで上げる盛り上げは使わない（人の譜面は盛り上がりを上の段で出さない）。とても静かな所・人の「静」は抑える。変え方はそのまま、
    ダッシュ付きは左右の型が違う時だけ入れ替え（斜めにする変え方は使わない: 左右対称の型の「入れ替え」は斜めになり、2/3 のまとまりが
    斜めになって曲の差が消えた）。性格の無い試作4 の変え方・まとまりの中で何小節ごとに切り替える試作5 の比べ（--switch 数・--no-split）は
    除いた（docs/除いた物.md）"""
    from . import theme
    out = {}
    for si, (sec, b) in enumerate(zip(secs, blocks)):
        th = chosen[sec.name]
        tfn = 'swap' if b.group.endswith("'") and th.a != th.b else 'base'
        if b.tension < QUIET:
            tfn = 'calm'
        tag = rhythm.phrase_tag(sec, sec.b0, sec.b1)
        if tag == '静':
            tfn = 'calm'
        a, bb = theme.transform(th, tfn)
        out[(si, 0)] = (si, {0: theme.mirror(bb), 1: a}, tfn)
    return out


def apply_breaks(hits, mu, min_len=1.0):
    """途切れ（music.breaks）: 途切れの間の打点を除き（ドラムとその他が両方止まる所・ドラムだけなら min_len 拍以上）、戻りの最初の打点を
    両手にする（前後 1/2 拍が空いている時だけ）。人の譜面 144 曲: 途切れの間はノーツ無しが偶然の 4 倍・評価の高い譜面は戻りの 48% が両手（6.16）。
    戻りの打点には reentry=True を付ける（振り下ろしで打つ強い打点にする）"""
    out = list(hits)
    for br in mu['breaks']:
        b0, b1 = br['beat'], br['beat'] + br['len']
        if br['kind'] == 'all' or br['len'] >= min_len:
            out = [h for h in out if not (b0 + 0.05 < h.beat < b1 - 0.05)]
        nxt = next((k for k, h in enumerate(out) if h.beat >= b1 - 0.05), None)
        if nxt is None or out[nxt].beat > b1 + 2:
            continue
        h = out[nxt]
        h.reentry = True
        free = (nxt == 0 or h.beat - out[nxt - 1].beat >= 0.5 - 1e-6) and (nxt + 1 >= len(out) or out[nxt + 1].beat - h.beat >= 0.5 - 1e-6)
        if free:
            h.hands = 2
    return out


def pitch_rows(hits, blocks):
    """歌の打点（片手）ごとの、歌の高さから狙う段（0〜2）{拍: 段}。まとまりの中の歌の高さの順位をそのまま 0〜2 に（高い音ほど高い段）。
    人の譜面は歌が高いと少し高い段に置く（音ごと +0.04・小節ごと +0.08。弱いので flow の w_pitch は小さく）"""
    out = {}
    for b in blocks:
        hs = [h for h in hits if b.b0 - 1e-6 <= h.beat < b.b1 - 1e-6 and h.src == 'vocal' and h.hands == 1 and h.midi > 0]
        if len(hs) < 4:
            continue
        ms = sorted(h.midi for h in hs)
        for h in hs:
            rank = (sum(1 for m in ms if m < h.midi) + 0.5 * sum(1 for m in ms if m == h.midi)) / len(ms)
            out[round(h.beat, 4)] = 2.0 * rank
    return out
