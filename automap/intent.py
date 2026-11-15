"""意思入れ（docs/意思入れ.md）: 利用者がページで作った意思入れの表（<曲>.intent.json）を、譜面づくり（compose --form --style --intent）に効かせる。

自動で選んだ打点（rhythm.choose_hits＋form.apply_breaks）を、区間の指示で直す。順番:
1. 区間の指示（表の順・後の物が優先）: 元にする音・量 → その区間の打点を選び直す／スネアに打つ・キックで決める・空きを埋める → 足す／両手 → 両手にする・やめる。
2. 全体の量のライン（区間に量・元にする音の指示が無い小節だけ）: 小節ごとに打点の数を倍率に近づける（足す時は強い音から・減らす時は弱い裏から）。
3. 休み: 区間の打点を消す。
4. 近すぎる打点（1/8 拍未満）を消し、両手は前後が空いている所だけ（キック・スネア・両手 +2 で決めた両手は 1/4 拍・ほかは 1/2 拍）。
振りの速さの上限は流れの計算に渡す（hit.min_gap）。同じ振りは、グループで一番前の区間（手本）の打点の並びをほかの区間に写し（区間の頭からの拍）、
置き方は流れの計算で手本に合わせる（hit.motif → __main__ が手本の置き方を Event.fix に）。アレンジは2回目・4回目…を打点を足した形にし、
その形どうしは同じ（hit.motif['key'] が別のまとまり）。
案 k（set.variant＝別の案で選んだ案の番号）: 打点は変えず、__main__ が区間と重なる小節のテーマを案 k と同じ決まり（variant_spec）で選ぶ
（variants で区間を渡す）。
同じ振りの形の「案 k」・「珍しい型まで」・「★の帯」（form_specs）: 形の設定＝その形の各回の同じ振りの区間の motif 以外の項目（と、形の区間の
中に収まる同じ振りでない区間の指示・form_set と同じ決まり）。__main__ がその形の型（テーマ）を小節のテーマと同じ決まりで選び直す。
形の区間の中のこれらの指示は小節のテーマには効かせない（theme_ranges に入れない）。
珍しい型まで（set.rare＝1）: 打点は変えず、__main__ が区間と重なる小節のテーマを、テーマに使う型のしきい値を「珍しい」まで下げた型の束
（theme.load_themes(…, freq='珍しい')・少ない曲にしか出ない型も）から選び直す（theme_ranges で区間を渡す。案 k と一緒なら広げた束の中で
案 k のずらし方）。決め（set.kime＝1 入れる・−1 入れない）: 珍しい型の「決め」（kime.py・型のデータベースの曲だけ）をその区間に入れる・
入れない（kime_ranges。珍しい型までの区間は、決めの指示が無ければ入れる側）。同じ振りの区間の中の決めは効かない。
★の帯（set.band＝−1 1段やさしく・+1 1段難しく・[下, 上] 帯を直接）: 打点は変えず、__main__ が区間と重なる小節のテーマを、★の帯だけ
変えた型のデータベースの書き出し（library_use.export_band）で選び直す（theme_ranges(…, band=True)。
珍しい型まで・案 k と一緒なら、その帯の束の中で広げる・ずらす）。同じ振りの区間の中は、上の形の設定として効く。
そのまま残す（set.keep）: 打点は変えず、__main__ がその区間の前の譜面（結果のファイルの作ったノーツ）を NLM の「固定」と同じに残す
（keep_ranges。結果のファイルが無い時は効かない）。
前の譜面に寄せる（docs/アプリ仕様.md 11 節）: 前の作り直しの表と今の表を比べ、指示が変わった所（changed_ranges）だけ自由に作り、
ほかは前の譜面に弱く寄せる（__main__ の --prev-intent）。
"""
import json
from bisect import bisect_right
from pathlib import Path

import numpy as np

from . import rhythm

NOT_YET = {}   # まだ効かない指示（読むが使わない＝報告に出す）。2026-10-26 に「そのまま残す」（keep）が効くようになって空
PLACE = ('move', 'width', 'height', 'diag', 'turn', 'bigmove')   # 置き方の指示 → 打点の mods → flow.Event.mods（流れの計算の重みを区間の中だけ変える）
# 量 → (目盛り＝1/n 拍, 打点の強さの下限)。打点の間は目盛りの幅より詰めない
AMOUNT = {-2: (1, 0.6), -1: (2, 0.5), 0: (2, 0.4), 1: (2, 0.25), 2: (4, 0.15)}
MIN_GAP = {-1: 0.20, 1: 0.12}   # 振りの速さの上限 → 同じ手の振りの最短の間（秒・今の既定は flow.Style.min_gap）
THEME_KEYS = ('motif', 'comment', 'variant', 'rare', 'kime', 'keep', 'band')   # 打点の指示ではない物（同じ振りの形の手本に効かせ直さない）
VARIANT_ROT = 5   # 案 k: 小節ごとのテーマを 1+(k-1)%VARIANT_ROT 個ずらす（性格ごとのテーマは 6 個）。VARIANT_ROT 個ごとに種も1つ進める


def variant_spec(k):
    """案 k（1 以上の整数）→ (テーマのずらし, 種)。種は曲の種（compose --seed・既定 1）から数えた番号（1＝曲の種のまま）。
    別の案を作る時（app/versions.py → compose --variant k）も、作り直しで区間の指示「案 k」を効かせる時もこの決まり"""
    k = int(k)
    if k < 1:
        raise ValueError('案の番号は 1 から')
    return 1 + (k - 1) % VARIANT_ROT, 1 + (k - 1) // VARIANT_ROT


def variant_of(st):
    """指示（set）の「案 k」→ k。無い・番号として使えない（0 以下・小数・文字）→ None"""
    v = (st or {}).get('variant')
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or v < 1:
        return None
    return int(v)


def rare_of(st):
    """指示（set）の「珍しい型まで」→ True／False（1・True 等の真の値）"""
    v = (st or {}).get('rare')
    return bool(v) and not (isinstance(v, (int, float)) and not isinstance(v, bool) and v <= 0)


def kime_of(st):
    """指示（set）の「決め」→ 1（この区間に入れる）・−1（入れない）・None（既定）"""
    v = (st or {}).get('kime')
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v == 0:
        return None
    return 1 if v > 0 else -1


def band_of(v):
    """★の帯の指示（set.band・compose --band の文字）→ 段の数（−3〜3 の 0 以外の整数・+＝難しく）か [下, 上]（★）。使えなければ None。
    文字は「+1」「-1」「6,10」。[下, 上] の下は 0 より下げない・上が下以下なら使えない"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str):
        t = v.strip().replace('〜', ',')
        try:
            v = [float(x) for x in t.split(',')] if ',' in t else float(t)
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        if v != int(v) or v == 0:
            return None
        return max(-3, min(3, int(v)))
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            lo, hi = sorted(float(x) for x in v)
        except (TypeError, ValueError):
            return None
        lo = max(0.0, lo)
        if hi <= lo:
            return None
        return [int(x) if x.is_integer() else x for x in (lo, hi)]
    return None


def band_text(v):
    """★の帯の指示 → 報告・画面の短い名前（「★1段難しく」「★6〜10」）"""
    b = band_of(v)
    if b is None:
        return '★の帯（値が使えない）'
    if isinstance(b, list):
        lo, hi = b
        return '★全部' if lo <= 0 and hi >= 99 else f'★〜{hi:g}' if lo <= 0 else f'★{lo:g}〜' if hi >= 99 else f'★{lo:g}〜{hi:g}'
    return f'★{abs(b)}段' + ('難しく' if b > 0 else 'やさしく')


def theme_ranges(it, band=False):
    """テーマを選び直す区間（「案 k」か「珍しい型まで」）→ [(拍の始まり, 終わり, k（無ければ 0）, 珍しい型まで)]
    （表の順＝重なる小節は後の物が勝つ。案と珍しい型までは小節ごとに別々に勝ち負けを決める。休みの区間は除く）。
    band＝True なら「★の帯」の区間も入れて、5 つ目に★の帯（band_of の値・無ければ None）。
    同じ振りの区間と、その中に収まる区間は除く（形の設定＝form_specs で形の型を選び直す。小節のテーマに効かせると、同じ小節の
    形の外の打点まで変わる）"""
    rs = (it or {}).get('ranges') or []
    occ = [(r['b0'], r['b1']) for r in rs if (r.get('set') or {}).get('motif') and not (r.get('set') or {}).get('rest')]
    out = []
    for r in rs:
        st = r.get('set') or {}
        k, rare = variant_of(st), rare_of(st)
        b = band_of(st.get('band')) if band else None
        if (k or rare or b is not None) and not st.get('rest'):
            if st.get('motif') or any(x - 1e-6 <= r['b0'] and r['b1'] <= y + 1e-6 for x, y in occ):
                continue
            out.append((r['b0'], r['b1'], k or 0, rare, b) if band else (r['b0'], r['b1'], k or 0, rare))
    return out


FORM_THEME = ('variant', 'rare', 'band')   # 同じ振りの形の型（テーマ）を選び直す指示


def form_set(it, g, rs, keep):
    """同じ振りのグループ g の形の区間 rs（表の区間の並び）に付いた指示 → {項目: 値}（keep(項目) が真の物だけ）。形の区間の中に収まる
    区間の指示を合わせる（形の区間からはみ出す区間＝曲全体の量の区間等は入れない・曲C で「量 +2」の区間が同じ振りの区間をまたいでいた）。
    同じ振りの区間とは別に付けた指示が、同じ振りの区間の指示より勝つ（曲C は同じ振りの区間に「量 +1」が付いていて、別に付けた調整が
    効かなかった）。同じ種類なら表の後の物が勝つ（作業ファイルは区間の始まりの順＝後の回が勝つ）"""
    best = {}
    for r in rs:
        for qi, q in enumerate(it['ranges']):
            qs = q.get('set') or {}
            if qs.get('rest') or q['b0'] < r['b0'] - 1e-6 or q['b1'] > r['b1'] + 1e-6:
                continue
            if qs.get('motif') and qs['motif'].get('group') != g:
                continue
            pr = (0 if qs.get('motif') else 1, qi)
            for k, v in qs.items():
                if keep(k) and (k not in best or pr > best[k][0]):
                    best[k] = (pr, v)
    return {k: v for k, (_, v) in best.items()}


def motif_forms(it):
    """同じ振りの形（画面の store.motifForms と同じ決まり）→ {グループ: {'mode', 'A': [区間…], 'B': [区間…]}}。グループの区間を始まりの
    順に並べ、アレンジ（mode 'arrange'・1回目の区間の物）は 1回目・3回目…が A（手本の形）・2回目・4回目…が B（アレンジの形）、
    ほかは全部 A。休みの区間は除く。区間は表の区間（dict）そのもの"""
    groups = {}
    for r in (it or {}).get('ranges') or []:
        st = r.get('set') or {}
        if st.get('motif') and not st.get('rest'):
            groups.setdefault(st['motif'].get('group'), []).append(r)
    out = {}
    for g, lst in groups.items():
        lst = sorted(lst, key=lambda r: r['b0'])
        mode = ((lst[0].get('set') or {}).get('motif') or {}).get('mode')
        arr = mode == 'arrange'
        out[g] = {'mode': mode, 'A': lst[0::2] if arr else lst, 'B': lst[1::2] if arr else []}
    return out


def form_specs(it):
    """同じ振りの形ごとの型の指示 → {(グループ, 'A'|'B'): {'k': 案 k（無ければ 0）, 'rare': 珍しい型まで, 'band': ★の帯（band_of の値か None）}}
    （指示のある形だけ）。形の設定＝その形の各回の同じ振りの区間の motif 以外の項目と、形の区間の中に収まる区間の指示（form_set の決まり:
    回ごとに違えば、付いている回の物が形の全部に効く・同じ振りの区間とは別に付けた指示が勝つ・同じ種類なら後の回が勝つ）。
    A と B は別々の形（B に指示が無ければ、作る側は A の型を左右入れ替えて使う＝今まで通り）"""
    out = {}
    if not it:
        return out
    for g, f in motif_forms(it).items():
        for name in ('A', 'B'):
            if not f[name]:
                continue
            s = form_set(it, g, f[name], lambda k: k in FORM_THEME)
            k, rare, b = variant_of(s), rare_of(s), band_of(s.get('band'))
            if k or rare or b is not None:
                out[(g, name)] = {'k': k or 0, 'rare': rare, 'band': b}
    return out


def form_mixed(it):
    """同じ振りの形の回ごとに設定（同じ振りの区間の motif 以外の項目）が違う形 → {(グループ, 'A'|'B'): [(回の拍の頭, その回に無い項目 [..])]}
    （報告用。作る側は form_set の決まりで、付いている回の物を形の全部に効かせる）"""
    out = {}
    for g, f in motif_forms(it).items():
        for name in ('A', 'B'):
            sets = [(r['b0'], {k: v for k, v in (r.get('set') or {}).items() if k != 'motif'}) for r in f[name]]
            allk = {k for _, s in sets for k in s}
            js = {json.dumps(s, sort_keys=True, ensure_ascii=False) for _, s in sets}
            if len(js) > 1:
                out[(g, name)] = [(b0, sorted(allk - set(s))) for b0, s in sets if set(s) != allk]
    return out


def kime_ranges(it):
    """決めの指示の区間 → (入れる区間 [(b0, b1)], 入れない区間 [(b0, b1)])。決め 1 と、決めの指示の無い「珍しい型まで」の区間は
    入れる側（少ない曲にしか出ない型を使いたい区間＝1回だけの珍しい並びも入れる）。休みの区間は除く"""
    want, avoid = [], []
    for r in (it or {}).get('ranges') or []:
        st = r.get('set') or {}
        if st.get('rest'):
            continue
        k = kime_of(st)
        if k is None and rare_of(st):
            k = 1
        if k == 1:
            want.append((r['b0'], r['b1']))
        elif k == -1:
            avoid.append((r['b0'], r['b1']))
    return want, avoid


def vsnap_ranges(it):
    """「歌を拍に寄せる」の区間 → (寄せる区間 [(b0, b1)], 寄せない区間 [(b0, b1)])。寄せる＝迷った歌の打点を、両隣の目盛りのどちらかで
    キック・スネアが鳴っていればそちらへ（rhythm.vocal_pull の INTENT_PULL）・寄せない＝自動（歌がばらつく区間）でも寄せない。休みの区間は除く"""
    on, off = [], []
    for r in (it or {}).get('ranges') or []:
        st = r.get('set') or {}
        if st.get('rest') or st.get('vsnap') is None:
            continue
        (on if st['vsnap'] else off).append((float(r['b0']), float(r['b1'])))
    return on, off


def keep_ranges(it):
    """「そのまま残す」の区間 → [(拍の始まり, 終わり)]（表の順・休みの区間も含む＝前の譜面のまま）"""
    return [(r['b0'], r['b1']) for r in (it or {}).get('ranges') or [] if (r.get('set') or {}).get('keep')]


DIFF_SKIP = ('comment',)   # 作り方を変えない指示（前の表との比べに入れない）。そのまま残すは比べる（消した区間は自由に作り直す＝消すと戻る）


def _rkey(r):
    """区間の指示の比べる形（作り方を変えない指示だけの区間は None）"""
    st = {k: v for k, v in (r.get('set') or {}).items() if k not in DIFF_SKIP}
    if not st:
        return None
    return round(float(r['b0']), 4), round(float(r['b1']), 4), json.dumps(st, sort_keys=True, ensure_ascii=False)


def merge_spans(spans):
    """拍の範囲 [(b0, b1)] の重なり・接する物をまとめる（始まりの順）"""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _form_norm(ranges):
    """比べる用の区間の並び: 同じ振りの区間の指示（motif 以外）を、その形の設定（form_set の決まりで形の回を合わせた物）に置き換える。
    画面が形の全部の回に同じ物を書いても（そろえる）、効き方が同じなら変わった所にしない（作る側は回ごとに違っても付いている回の物を
    形の全部に効かせる＝そろえる前と同じ答え）。元の区間は変えない"""
    rs = [dict(r) for r in ranges]
    t = {'ranges': rs}
    new = []
    for g, f in motif_forms(t).items():
        for name in ('A', 'B'):
            merged = form_set(t, g, f[name], lambda k: k != 'motif' and k not in DIFF_SKIP) if f[name] else {}
            new += [(r, dict(merged, motif=(r.get('set') or {}).get('motif'))) for r in f[name]]
    for r, st in new:
        r['set'] = st
    return rs


def changed_ranges(prev, cur, bars=(), end=None):
    """前の作り直しの意思入れの表 prev と今の表 cur（load・server.intent_table の形）→ (指示が変わった拍の範囲 [(b0, b1)]（重なりは
    まとめる）, 全体の設定が変わったか（自動の休み）, 説明 [文])。変わった所:
    - 足した・消した・変えた区間（指示の中身で比べる。コメントだけの区間は比べない）
    - 同じ振り: 変わった区間と重なるグループの区間は全部（写した先も・形ごとの指示はその形の全部に効く）
    - 量のライン: 小節の頭の倍率が違う小節（倍率は小節ごとに効く＝intent.apply）
    テーマは小節ごとに選ぶ（案 k・珍しい型まで・型の変わり方）ので、範囲は小節の頭と終わりまで広げる（bars があれば）"""
    from collections import Counter
    prev, cur = prev or {}, cur or {}
    pr, cr = prev.get('ranges') or [], cur.get('ranges') or []
    pk = Counter(k for k in map(_rkey, _form_norm(pr)) if k)
    ck = Counter(k for k in map(_rkey, _form_norm(cr)) if k)
    diff = (pk - ck) + (ck - pk)
    spans = [(a, b) for a, b, _ in diff.elements()]
    why = []
    n_add, n_del = sum((ck - pk).values()), sum((pk - ck).values())
    if n_add or n_del:
        why.append(f'区間の指示（足した・変えた {n_add}・消した・変える前 {n_del}）')
    ov = lambda x, y: x[0] < y[1] - 1e-6 and y[0] < x[1] - 1e-6
    groups = {}
    for r in pr + cr:
        st = r.get('set') or {}
        if st.get('motif') and not st.get('rest'):
            groups.setdefault(st['motif'].get('group'), set()).add((float(r['b0']), float(r['b1'])))
    hit = set()
    for _ in range(len(groups) + 1):   # 同じ振りの区間が別のグループと重なる時も、変わらなくなるまで広げる
        more = [(g, lst) for g, lst in groups.items() if g not in hit and any(ov(s, x) for s in spans for x in lst)]
        if not more:
            break
        for g, lst in more:
            hit.add(g)
            spans += sorted(lst)
    if hit:
        why.append('同じ振り「' + '」「'.join(sorted(str(g) for g in hit)) + '」の区間（写した先も）')
    bars = [float(b) for b in (bars or [])]
    pl, cl = prev.get('line') or [], cur.get('line') or []
    if bars:
        edges = bars + [float(end) if end is not None else bars[-1] + 4.0]
        nl = 0
        for i, a in enumerate(bars):
            if abs(_line_k(pl, a) - _line_k(cl, a)) > 1e-3:
                spans.append((a, edges[i + 1]))
                nl += 1
        if nl:
            why.append(f'量のライン（{nl} 小節）')
    elif json.dumps(pl, sort_keys=True) != json.dumps(cl, sort_keys=True):
        spans.append((0.0, float(end) if end is not None else 1e9))
        why.append('量のライン')
    ar = lambda t: (lambda a: (bool(a.get('on')), a.get('b') if a.get('on') else None))(t.get('auto_rest') or {})
    glob = ar(prev) != ar(cur)
    if glob:
        why.append('自動の休み')
    if bars and spans:   # 小節の頭と終わりまで広げる
        wide = []
        for a, b in spans:
            i0 = max(0, int(np.searchsorted(bars, a + 1e-6, 'right')) - 1)
            i1 = int(np.searchsorted(bars, b - 1e-6, 'left'))
            wide.append((min(a, bars[i0]), max(b, bars[i1] if i1 < len(bars) else b)))
        spans = wide
    return merge_spans(spans), glob, why


def load(path):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    ranges, seen = [], set()
    for r in d.get('ranges') or []:   # 全く同じ区間・指示の重なり（ページで2回付けた）は1つに
        k = (r['b0'], r['b1'], json.dumps(r.get('set') or {}, sort_keys=True, ensure_ascii=False))
        if k not in seen:
            seen.add(k)
            ranges.append(r)
    return {'ranges': ranges, 'line': sorted(d.get('line') or [], key=lambda p: p['b']),
            'auto_rest': d.get('auto_rest') or {'on': False, 'b': None}}


def _in(b, r):
    return r['b0'] - 1e-6 <= b < r['b1'] - 1e-6


def _on_grid(b, grid):
    return abs(b * grid - round(b * grid)) < 1e-6


def _sec_of(secs, b):
    for i, s in enumerate(secs):
        if s.b0 - 1e-6 <= b < s.b1 - 1e-6:
            return i
    return max(0, len(secs) - 1)


def _kinds(source, vocal):
    if source == 'vocal':
        return ['vocal']
    if source == 'drums':
        return ['kick', 'snare']
    if source == 'inst':
        return ['other']
    if source == 'bass':
        return ['bass']
    if source == 'vocal+drums':
        return ['vocal', 'kick', 'snare']
    return ['vocal'] if vocal else ['kick', 'snare', 'other']


def pick(ons, b0, b1, kinds, amount, taken=()):
    """b0〜b1 の打点を選ぶ: kinds の音の打点で、量の目盛りに乗り強さが下限以上の物を、強い順に、目盛りの幅より詰めずに。
    歌は 1/4 拍まで（量 −2・−1 は目盛りに従う）。→ [Onset]"""
    grid, smin = AMOUNT[max(-2, min(2, amount))]
    cand = []
    for k in kinds:
        g = max(grid, 4) if (k == 'vocal' and amount >= 0) else grid
        th = smin * (0.75 if k == 'vocal' else 1.0)
        cand += [o for o in ons.get(k, []) if b0 - 1e-6 <= o.beat < b1 - 1e-6 and o.s >= th and _on_grid(o.beat, g)]
    gap = 1.0 / grid if amount < 0 else 0.25 if amount >= 2 or 'vocal' in kinds else 0.5
    got, beats = [], list(taken)
    for o in sorted(cand, key=lambda o: -o.s):
        if all(abs(o.beat - q) >= gap - 1e-6 for q in beats):
            got.append(o)
            beats.append(o.beat)
    return sorted(got, key=lambda o: o.beat)


def _mk(o, secs, src=None):
    return rhythm.Hit(o.beat, 1, _sec_of(secs, o.beat), 0, src or o.kind, o.s, getattr(o, 'midi', 0.0))


def _line_k(line, b):
    if not line:
        return 1.0
    xs, ks = [p['b'] for p in line], [p['k'] for p in line]
    return float(np.interp(b, xs, ks))


def _apply_set(hits, r, st, idx, ons, secs, bars, vocal_at, scale=None):
    """区間 r に指示 st を効かせる（打点を選び直す・足す・両手・置き方・速さ・同じ振りの印）→ (打点, したこと)。
    scale＝量の目安で合わせた倍率を掛ける関数（amount.make_scale・選び直した打点に掛ける＝区間の量 ±は目安に対する割合）"""
    b0, b1 = r['b0'], r['b1']
    did = []
    repicked = False
    if 'source' in st or 'amount' in st:   # 区間の打点を選び直す
        kinds = _kinds(st.get('source'), vocal_at(b0))
        amt = int(st.get('amount', 0))
        got = pick(ons, b0, b1, kinds, amt)
        if 'vocal' in kinds and amt >= 1:   # 歌の間（1拍以上）をドラムで埋める
            bs = [b0] + [o.beat for o in got] + [b1]
            for a, b in zip(bs, bs[1:]):
                if b - a >= 1.0:
                    got += pick(ons, a + 0.5, b - 0.25, ['kick', 'snare'], amt, ())
        if 'source' in st and len(got) < (b1 - b0) / 4:   # 選んだ音の打点がほとんど無い（曲C の 0:57〜 の楽器: 0。利用者が聞いていたのはベース）→ 元の打点のまま
            did.append(f'元にする音（{"・".join(kinds)}）の打点が {len(got)} しか無いので元のまま')
        else:
            hits = [h for h in hits if not _in(h.beat, r)] + [_mk(o, secs) for o in got]
            did.append('選び直し（' + '・'.join(kinds) + f'・量 {amt:+d}）')
            repicked = True
    hits.sort(key=lambda h: h.beat)
    inr = lambda: [h for h in hits if _in(h.beat, r)]
    def add(os_, force=False, lab=''):
        nonlocal hits
        n = 0
        for o in os_:
            h = next((h for h in hits if abs(h.beat - o.beat) < 0.126), None)
            if h is None:
                h = _mk(o, secs)
                hits.append(h)
                n += 1
            if force:
                h.hands, h.force_dbl, h.force_strong = 2, True, True
        hits.sort(key=lambda h: h.beat)
        if lab:
            did.append(f'{lab} {n} 足し' + ('・両手' if force else ''))
    if st.get('snare'):
        sn = [o for o in ons.get('snare', []) if b0 - 1e-6 <= o.beat < b1 - 1e-6 and o.s >= (0.6 if st['snare'] == 1 else 0.3)]
        add(sn, False, 'スネア')
        if st['snare'] == 2:
            add([o for o in sn if o.s >= 0.7], True)
    if st.get('kick'):
        kk = [o for o in ons.get('kick', []) if b0 - 1e-6 <= o.beat < b1 - 1e-6 and o.s >= 0.5]
        if st['kick'] == 1:
            kk = [o for o in kk if o.s >= 0.7 and (any(abs(o.beat - x) < 1e-6 for x in bars) or _on_grid(o.beat, 1))]
        add(kk, True, 'キック')
    if st.get('fill'):
        bs = [b0] + [h.beat for h in inr()] + [b1]
        fill = []
        for a, b in zip(bs, bs[1:]):
            if b - a >= 1.0:
                fill += pick(ons, a + 0.5, b - 0.49, ['kick', 'snare', 'other'], 0)
        add(fill, False, '空き埋め')
    if 'hands' in st:
        hv = st['hands']
        for h in inr():
            if hv < 0:
                h.hands, h.force_dbl = 1, False
            elif hv == 1 and (any(abs(h.beat - x) < 1e-6 or abs(h.beat - x - 2) < 1e-6 for x in bars)):
                h.hands = 2
            elif hv >= 2 and h.s >= 0.7 and _on_grid(h.beat, 2):
                h.hands, h.force_dbl = 2, True
        did.append(f'両手 {hv:+d}')
    if scale and repicked and not st.get('motif'):   # 量の目安: 選び直した打点にも曲全体を目安に合わせた倍率を掛ける（両手を決めた後＝両手の前後を空ける）。
        # 同じ振りの区間は掛けない（形の打点の並びは手本とアレンジの量で決める。掛けると曲C で、アレンジの両手のすぐ前に 1/4 拍の打点が入り同じ手が 0.09 秒で続いた）
        n_s = len(inr())
        hits = scale(hits, b0, b1)
        did.append(f'量の目安の倍率（{n_s} → {len(inr())}）')
    pm = {k: st[k] for k in PLACE if k in st}
    if pm:
        for h in inr():
            h.mods = dict(getattr(h, 'mods', None) or {}, **pm)
        did.append('置き方: ' + '・'.join(f'{k} {v}' for k, v in pm.items()))
    if 'variety' in st:   # 型の変わり方: __main__._bar_theme がテーマの切り替えを変える（区間の頭も渡す）
        for h in inr():
            h.variety = {'v': st['variety'], 'b0': b0}
        did.append(f'型の変わり方 {st["variety"]:+d}')
    if 'speed' in st:
        for h in inr():
            h.min_gap = MIN_GAP.get(st['speed'])
        did.append(f'振りの速さの上限 {st["speed"]:+d}（同じ手 {MIN_GAP.get(st["speed"])} 秒）')
    if st.get('motif'):
        for h in inr():
            h.motif = dict(st['motif'], idx=idx, b0=b0)
        did.append(f'同じ振り「{st["motif"].get("group")}」')
    if 'variant' in st:   # 案 k: テーマは __main__ が小節ごとに選ぶ（打点は変えない）
        k = variant_of(st)
        if k:
            n, s = variant_spec(k)
            did.append(f'案 {k}（テーマのずらし {n}・種 {s}）')
        else:
            did.append(f'案の番号が使えない（{st["variant"]!r}）ので既定の作り方')
    if 'rare' in st:   # 珍しい型まで: テーマは __main__ が広げた型の束から小節ごとに選ぶ（打点は変えない）
        did.append('珍しい型まで（テーマを少ない曲にしか出ない型まで広げた束から）' if rare_of(st) else '珍しい型まで: 切')
    if 'band' in st:   # ★の帯: テーマは __main__ が★の帯を変えた型の束から小節ごとに選ぶ（打点は変えない）
        did.append(f'{band_text(st["band"])}（テーマをその★の帯の型から選び直す）' if band_of(st['band']) is not None
                   else f'★の帯の値が使えない（{st["band"]!r}）ので既定')
    if 'kime' in st:   # 決め: __main__ が kime.choose に渡す（打点は変えない）
        k = kime_of(st)
        did.append('決めを入れる' if k == 1 else '決めを入れない' if k == -1 else f'決めの値が使えない（{st["kime"]!r}）ので既定')
    if 'vsnap' in st:   # 歌を拍に寄せる: __main__ が打点の候補の段で寄せ直す（vsnap_ranges → rhythm.vocal_pull・数は報告の「歌を拍に寄せた」の行）
        did.append('歌を拍に寄せる（迷った歌の打点を、隣の目盛りでキック・スネアが鳴っていればそちらへ）' if st['vsnap']
                   else '歌を拍に寄せない（おまかせの寄せ方もしない）')
    if st.get('keep'):   # そのまま残す: __main__ が前の譜面のノーツを残す（打点は変えない）
        did.append('そのまま残す（前の譜面のノーツを NLM の「固定」と同じに残す）')
    nyet = [NOT_YET[k] for k in st if k in NOT_YET]
    if nyet:
        did.append('まだ効かない: ' + '・'.join(nyet))
    return hits, did


def apply(hits, ons, secs, it, bars, end_beat, scale=None, line=True):
    """意思入れの表を打点に効かせる → (打点, 報告の行)。ons＝rhythm.analyze の打点の候補・secs＝form.sections・bars＝小節の頭の拍。
    scale＝量の目安（amount.make_scale）: 区間の量 ±・元にする音で選び直した打点に、目安で合わせた倍率を掛ける（無い＝今のまま）。
    line=False＝全体の量のラインはここでは効かせない（compose は自動のくり返しの後に apply_line で効かせる）"""
    hits = sorted(hits, key=lambda h: h.beat)
    rep = []
    vocal_at = lambda b: secs[_sec_of(secs, b)].vocal
    for idx, r in enumerate(it['ranges']):
        st = r.get('set') or {}
        n0 = sum(_in(h.beat, r) for h in hits)
        if st.get('rest'):
            continue   # 休みは最後に
        hits, did = _apply_set(hits, r, st, idx, ons, secs, bars, vocal_at, scale)
        rep.append((r, n0, sum(_in(h.beat, r) for h in hits), did))
    # 同じ振り: 手本（グループで一番前の区間）の打点の並びを、ほかの区間へ写す。アレンジは1回目・3回目…が手本の形、
    # 2回目・4回目…がアレンジの形（手本の並び＋打点を足す＝利用者「アレンジの所は打ち込みを増やす」）で、アレンジの形は2回目の区間で作って写す
    groups = {}
    for i, r in enumerate(it['ranges']):
        m = (r.get('set') or {}).get('motif')
        if m and not (r.get('set') or {}).get('rest'):
            groups.setdefault(m.get('group'), []).append((r['b0'], i, r))
    mot = lambda r: (r.get('set') or {}).get('motif') or {}
    for g, lst in groups.items():
        lst.sort(key=lambda t: t[0])
        _, i0, r0 = lst[0]
        mode = mot(r0).get('mode')

        def fset(sub, g=g):
            # 形ごとの指示: その形の区間（の中に収まる区間）に付けた打点の指示を合わせる（決まりは form_set）
            return form_set(it, g, [r for _, _, r in sub], lambda k: k not in THEME_KEYS)
        # 手本の形: ほかの区間に付けた指示も手本の区間に効かせ直す（手本の区間に付けていない物だけ）
        own0 = {k: v for k, v in (r0.get('set') or {}).items() if k not in THEME_KEYS}
        more0 = {k: v for k, v in fset(lst[0::2] if mode == 'arrange' else lst).items() if own0.get(k) != v}
        if more0:
            hits, d0 = _apply_set(hits, r0, dict(own0, **more0), i0, ons, secs, bars, vocal_at, scale)
            j = next(j for j, e in enumerate(rep) if e[0] is r0)
            rep[j] = (r0, rep[j][1], sum(_in(h.beat, r0) for h in hits), rep[j][3] + ['この形のほかの区間の指示: ' + '・'.join(d0)])
        # アレンジの量（同じ振りの欄・グループで1つ。2回目・4回目…の区間の物が先）: −1＝手本より少なく・0＝同じ数・+1＝5割ほど多く（既定）・+2＝倍
        extra = next((mot(r).get('extra') for _, _, r in lst[1::2] + lst if mot(r).get('extra') is not None), 1)
        extra = max(-1, min(2, int(extra)))
        model = [h for h in hits if _in(h.beat, r0)]
        offs = [(h.beat - r0['b0'], h) for h in model]
        subs = [('a', g, lst[0::2]), ('b', f'{g}（アレンジ）', lst[1::2])] if mode == 'arrange' else [('a', g, lst)]
        for var, key, sub in subs:
            if not sub:
                continue
            pat = offs
            for occ, (_, i, r) in enumerate(sub):
                L = r['b1'] - r['b0']
                n0 = sum(_in(h.beat, r) for h in hits)
                new = []
                for off, h in pat:
                    if off < L - 1e-6:
                        q = rhythm.Hit(r['b0'] + off, h.hands, _sec_of(secs, r['b0'] + off), 0, h.src, h.s, h.midi)
                        for k in ('force_dbl', 'force_strong', 'min_gap', 'mods'):
                            if hasattr(h, k):
                                setattr(q, k, getattr(h, k))
                        new.append(q)
                did = []
                if var == 'b' and occ == 0 and extra <= 0:   # アレンジの量 0＝手本と同じ数（テーマだけ違う）・−1＝弱い打点を3分の1減らす
                    acc = lambda b: sum(o.s for k in ('vocal', 'kick', 'snare') for o in ons.get(k, []) if abs(o.beat - b) < 0.01)
                    drop = sorted(new[1:], key=lambda q: (acc(q.beat) + q.s, -q.beat))[:max(1, len(new) // 3)] if extra < 0 else []
                    new = [q for q in new if q not in drop]
                    pat = [(q.beat - r['b0'], q) for q in new]
                    did.append(f'アレンジの形（量 {extra:+d}）: 手本の並び' + (f'から打点 {len(drop)} 減らし' if drop else 'のまま'))
                elif var == 'b' and occ == 0:   # アレンジの形: ノーツを手本の半分ほど増やす（量 +2 は倍）
                    # まず手本の並びの間の強い音（量を1段上げた目盛り）。曲C の「バーン」は音が半拍ごとにしか無く足せなかった
                    # → 足りない分は、歌・キック・スネアが重なる強い打点を両手にする。両手どうしの間の片手の打点は偶数個だけ
                    # （手は振りの向きを交互にするので、奇数個だと片方の両手が「片手は上・片手は下」になる）
                    want = max(1, len(new) // 2) * extra
                    st0 = r0.get('set') or {}
                    amt = min(2, int(st0.get('amount', 0)) + 1)
                    kinds = list(dict.fromkeys(_kinds((r.get('set') or {}).get('source'), vocal_at(r['b0'])) + ['kick', 'snare']))
                    more = sorted(pick(ons, r['b0'], r['b1'], kinds, amt, [q.beat for q in new]), key=lambda o: -o.s)[:want]
                    mg = next((q.min_gap for q in new if hasattr(q, 'min_gap')), None)
                    for o in more:
                        q = _mk(o, secs)
                        if mg:
                            q.min_gap = mg
                        new.append(q)
                    new.sort(key=lambda q: q.beat)
                    acc = lambda b: sum(o.s for k in ('vocal', 'kick', 'snare') for o in ons.get(k, []) if abs(o.beat - b) < 0.01)
                    dbl = []
                    for q in sorted((q for q in new if q.hands == 1), key=lambda q: (-acc(q.beat), q.beat)):
                        if len(dbl) >= want - len(more):
                            break
                        ds = sorted([d.beat for d in dbl] + [d.beat for d in new if d.hands == 2] + [q.beat])
                        if all(sum(a < x.beat < b and x.hands == 1 and x not in dbl and x is not q for x in new) % 2 == 0
                               for a, b in zip(ds, ds[1:])):
                            dbl.append(q)
                    for q in dbl:
                        q.hands, q.force_dbl, q.force_strong = 2, True, True
                    dbl.sort(key=lambda q: q.beat)
                    pat = [(q.beat - r['b0'], q) for q in new]
                    did.append(f'アレンジの形（量 {extra:+d}）: 手本の並び' + (f'＋打点 {len(more)} 足し' if more else '')
                               + (f'＋両手 {len(dbl)}（拍 {"・".join(format(q.beat, "g") for q in dbl)}）' if dbl else ''))
                elif occ or var == 'b':
                    did.append(f'{"アレンジの形（拍 " + format(sub[0][2]["b0"], "g") + "〜）" if var == "b" else "手本（拍 " + format(r0["b0"], "g") + "〜）"}の打点の並びを写す')
                if var == 'b' and occ == 0:
                    fb = fset(sub)
                    fb2 = {k: v for k, v in fb.items() if k not in ('source', 'amount')}
                    if fb2:
                        hits = sorted([h for h in hits if not _in(h.beat, r)] + new, key=lambda h: h.beat)
                        hits, d1 = _apply_set(hits, r, fb2, i, ons, secs, bars, vocal_at)
                        new = [h for h in hits if _in(h.beat, r)]
                        pat = [(q.beat - r['b0'], q) for q in new]
                        did.append('この形の指示: ' + '・'.join(d1))
                    if any(k in fb for k in ('source', 'amount')):
                        did.append('（アレンジの形の量は「アレンジの量」で決める。量・元にする音は手本の形に付ける）')
                for q in new:
                    q.motif = {'group': g, 'key': key, 'variant': var, 'mode': mode, 'idx': i, 'b0': r['b0'], 'occ': occ}
                if occ == 0 and var == 'a':
                    continue
                hits = sorted([h for h in hits if not _in(h.beat, r)] + new, key=lambda h: h.beat)
                j = next(j for j, e in enumerate(rep) if e[0] is r)
                rep[j] = (r, rep[j][1], len(new), rep[j][3] + did)
        for h in model:   # 手本の区間の打点（写した物と別の物）にも印
            h.motif = {'group': g, 'key': g, 'variant': 'a', 'mode': mode, 'idx': lst[0][1], 'b0': r0['b0'], 'occ': 0}
    # 全体の量のライン（量・元にする音を指定した区間の小節は除く）
    fixed = [r for r in it['ranges'] if 'source' in (r.get('set') or {}) or 'amount' in (r.get('set') or {}) or (r.get('set') or {}).get('rest')]
    line_add = line_del = 0
    if it['line'] and line:
        edges = list(bars) + [end_beat]
        for i in range(len(bars)):
            a, b = edges[i], edges[i + 1]
            k = _line_k(it['line'], a)
            if abs(k - 1) < 0.08 or any(r['b0'] < b and r['b1'] > a for r in fixed):
                continue
            bh = [h for h in hits if a - 1e-6 <= h.beat < b - 1e-6]
            want = int(round(len(bh) * k))
            if want > len(bh):
                for grid in (2, 4):
                    for o in sorted((o for kd in ('kick', 'snare', 'other', 'hihat', 'vocal') for o in ons.get(kd, [])
                                     if a - 1e-6 <= o.beat < b - 1e-6 and o.s >= 0.2 and _on_grid(o.beat, grid)), key=lambda o: -o.s):
                        if len(bh) >= want:
                            break
                        if all(abs(o.beat - h.beat) >= 0.24 for h in bh):
                            h = _mk(o, secs)
                            hits.append(h)
                            bh.append(h)
                            line_add += 1
            elif want < len(bh):
                order = sorted((h for h in bh if abs(h.beat - a) > 1e-6), key=lambda h: (_on_grid(h.beat, 1), h.s))
                for h in order[:len(bh) - want]:
                    hits.remove(h)
                    line_del += 1
        hits.sort(key=lambda h: h.beat)
    # 休み
    for r in it['ranges']:
        if (r.get('set') or {}).get('rest'):
            n0 = sum(_in(h.beat, r) for h in hits)
            hits = [h for h in hits if not _in(h.beat, r)]
            rep.append((r, n0, 0, ['休み']))
    # 近すぎる打点・両手の間
    out = []
    for h in sorted(hits, key=lambda h: (h.beat, -h.s)):
        if out and h.beat - out[-1].beat < 0.124:
            continue
        out.append(h)
    for i, h in enumerate(out):
        if h.hands == 2:
            need = 0.25 if getattr(h, 'force_dbl', False) else 0.5
            if (i > 0 and h.beat - out[i - 1].beat < need - 1e-6) or (i + 1 < len(out) and out[i + 1].beat - h.beat < need - 1e-6):
                h.hands = 1
    if it['line'] and line:
        rep.append(({'b0': it['line'][0]['b'], 'b1': it['line'][-1]['b']}, None, None, [f'全体の量のライン（足し {line_add}・減らし {line_del}）']))
    ar = it['auto_rest'] or {}
    if ar.get('on') and len(bars):   # 自動の休み: 位置（無ければ曲の 7 割）に一番近い小節を1つ空ける。休み・同じ振りの区間とは重ねない
        want = ar['b'] if ar.get('b') is not None else end_beat * 0.7
        avoid = [(r['b0'], r['b1']) for r in it['ranges'] if (r.get('set') or {}).get('rest') or (r.get('set') or {}).get('motif')]
        edges = list(bars) + [end_beat]
        for i in sorted(range(len(bars)), key=lambda i: abs(bars[i] - want)):
            a, b = edges[i], edges[i + 1]
            if b - a < 1 or any(a < y and b > x for x, y in avoid):
                continue
            n0 = sum(a - 1e-6 <= h.beat < b - 1e-6 for h in out)
            out = [h for h in out if not (a - 1e-6 <= h.beat < b - 1e-6)]
            rep.append(({'b0': a, 'b1': b}, n0, 0, [f'自動の休み（拍 {a:g}〜{b:g}）']))
            it.setdefault('_rest', []).append((a, b))   # 後で効かせる量のライン（apply_line）がここに打点を足さないように
            break
    return out, rep


def motif_families(it, hits):
    """利用者の同じ振りの、同じ形（motif['key']）の区間の並び → [[(拍の始まり, 終わり)…]]（先頭が手本）。自動の同じ振りは入れない"""
    ends = {}
    for r in it['ranges']:
        if (r.get('set') or {}).get('motif') and not (r.get('set') or {}).get('rest'):
            ends[round(r['b0'], 4)] = r['b1']
    occ = {}
    for h in hits:
        m = getattr(h, 'motif', None)
        if m and not m.get('auto') and round(m['b0'], 4) in ends:
            occ.setdefault(m.get('key'), {})[round(m['b0'], 4)] = m.get('occ', 0)
    out = []
    for key, d in occ.items():
        ws = sorted(d, key=lambda b: (d[b], b))
        if len(ws) >= 2:
            out.append([(b, ends[b]) for b in ws])
    return out


def apply_line(hits, it, bars, end_beat, ons, secs, inner=(), outer=()):
    """全体の量のライン（compose は続けて左右反転・自動の同じ振りの後に呼ぶ）→ (打点, 報告の行 or None)。小節ごとに打点の数を倍率に近づける
    （足す時は強い音から・減らす時は弱い裏から・小節の頭は残す・量・元にする音・休みの区間は触らない＝前と同じ決まり）。
    2026-11-08 利用者「量のラインがあまり反映されていない」: 前は意思入れの中（自動のくり返しの前）で効かせていて、続けて左右反転のセットと
    自動の同じ振りがリズムを手本から写し直すので、減らした分が戻った（パピヨンの拍 360〜 の ×0.9 が 0.97）。
    くり返しの組（先頭が手本の窓の並び）: inner＝続けて左右反転のセット（先に）・outer＝自動の同じ振り・利用者の同じ振り。組の中でラインの値が
    同じ窓は、手本で決めた足し・抜き（内側の組の分も含む）を全部の窓の同じ位置に写す＝くり返しを崩さない。値が違う窓は、その窓だけで合わせる。"""
    if not it['line'] or not len(bars):
        return hits, None
    hits = sorted(hits, key=lambda h: h.beat)
    E = 1e-6
    bars = list(bars)
    edges = bars + [end_beat]
    fixed = [(r['b0'], r['b1']) for r in it['ranges']
             if 'source' in (r.get('set') or {}) or 'amount' in (r.get('set') or {}) or (r.get('set') or {}).get('rest')] + list(it.get('_rest') or [])
    blocked = lambda a, b: any(x < b - E and y > a + E for x, y in fixed)
    cand = sorted((o for kd in ('kick', 'snare', 'other', 'hihat', 'vocal') for o in ons.get(kd, []) if o.s >= 0.2), key=lambda o: o.beat)
    cb = [o.beat for o in cand]
    done, log = set(), []   # 量のラインで扱い終えた打点・足し抜きの記録（拍, 'add'|'drop', 足した打点の元）
    cnt = {'add': 0, 'drop': 0, 'copy': 0}
    acc = [0.0]   # 四捨五入の端数（打点の数）を次の小節・窓へ持ち越す（2 拍のセットは打点が 2〜3 で、×0.9 を掛けても 1 つも減らなかった）

    def bar_of(b):
        return max(0, min(len(bars) - 1, bisect_right(bars, b + E) - 1))

    def subwins(w0, w1):   # 窓と小節の重なり（小節の頭の拍・重なりの始まり・終わり）
        out, i = [], bar_of(w0)
        while i < len(bars) and edges[i] < w1 - E:
            a, b = max(edges[i], w0), min(edges[i + 1], w1)
            if b > a + E:
                out.append((edges[i], a, b))
            i += 1
        return out

    def klist(w0, w1):
        return [_line_k(it['line'], bh) for bh, _, _ in subwins(w0, w1)]

    def at(b0, b1, free_only=True):
        lo, hi = bisect_right([h.beat for h in hits], b0 - E), bisect_right([h.beat for h in hits], b1 - E)
        return [h for h in hits[lo:hi] if not (free_only and id(h) in done)]

    def plan(w0, w1, nrep=1):   # 窓の中の自由な打点で、小節ごとの足し・抜きを決める → [(拍, 'drop'|'add', 元)]。nrep＝同じ足し抜きを写す窓の数
        ch = []
        for bh, a, b in subwins(w0, w1):
            k = _line_k(it['line'], bh)
            if abs(k - 1) < 0.08 or blocked(a, b):
                continue
            cur = at(a, b)
            d = len(cur) * (k - 1) * nrep + acc[0]   # 足し抜きの数（写す回の分も）＋持ち越し
            step = int(round(d / nrep))
            acc[0] = d - step * nrep
            want = max(0, len(cur) + step)
            if want > len(cur):
                have = [h.beat for h in at(a, b, False)]
                for grid in (2, 4):
                    lo, hi = bisect_right(cb, a - E), bisect_right(cb, b - E)
                    for o in sorted((o for o in cand[lo:hi] if _on_grid(o.beat, grid)), key=lambda o: -o.s):
                        if len(cur) + sum(c[1] == 'add' for c in ch if a - E <= c[0] < b - E) >= want:
                            break
                        if all(abs(o.beat - x) >= 0.24 for x in have):
                            ch.append((o.beat, 'add', o))
                            have.append(o.beat)
            elif want < len(cur):
                order = sorted((h for h in cur if abs(h.beat - bh) > E), key=lambda h: (_on_grid(h.beat, 1), h.s))
                ch += [(h.beat, 'drop', h) for h in order[:len(cur) - want]]
        return ch

    def put(changes, c0=None, t0=None, win=None):   # 足し抜きを効かせる（c0・t0＝手本の窓の始まり t0 から写す先の窓の始まり c0 へずらす・win＝窓）
        nonlocal hits
        sh = 0.0 if c0 is None else c0 - t0
        for b, kind, src in changes:
            bb = round(b + sh, 6)
            if kind == 'drop':
                h = next((h for h in hits if abs(h.beat - bb) < 1e-4), None)
                if h is not None and not getattr(h, 'kept', False):
                    hits.remove(h)
                    cnt['drop'] += 1
                    cnt['copy'] += c0 is not None
                    log.append((bb, 'drop', src))
            else:
                if any(abs(h.beat - bb) < 0.24 for h in hits):
                    continue
                q = rhythm.Hit(bb, 1, _sec_of(secs, bb), 0, getattr(src, 'kind', None) or getattr(src, 'src', 'line'), src.s, getattr(src, 'midi', 0.0))
                mm = next((h.motif for h in at(*win, False) if getattr(h, 'motif', None)), None) if win else None
                if mm:   # 同じ振りの窓の中に足した打点にも、その回の印
                    q.motif = dict(mm)
                hits.append(q)
                hits.sort(key=lambda h: h.beat)
                done.add(id(q))
                cnt['add'] += 1
                cnt['copy'] += c0 is not None
                log.append((bb, 'add', q))

    def family(ws, nested):
        ws = [w for w in ws if w[1] > w[0] + E]
        if len(ws) < 2 or any(abs((w1 - w0) - (ws[0][1] - ws[0][0])) > E for w0, w1 in ws) or any(blocked(*w) for w in ws):
            return
        t0, t1 = ws[0]
        k0 = klist(t0, t1)
        same = [w for w in ws[1:] if len(klist(*w)) == len(k0) and all(abs(x - y) < 0.08 for x, y in zip(klist(*w), k0))]
        if not same:
            return
        mark = len(log)
        put(plan(t0, t1, 1 + len(same)), win=(t0, t1))
        ch = [c for c in log[mark:]] + ([c for c in log[:mark] if t0 - E <= c[0] < t1 - E] if nested else [])
        for w0, w1 in same:   # 手本の窓の足し抜き（内側の組の分も）を同じ位置に写す
            put([(b, kd, src) for b, kd, src in ch], w0, t0, (w0, w1))
        for w0, w1 in [ws[0]] + same:
            for h in at(w0, w1, False):
                done.add(id(h))

    for ws in inner:
        family(ws, False)
    for ws in outer:
        family(ws, True)
    put(plan(edges[0], end_beat))   # くり返しの組の外（と、ラインの値が違う回）は小節ごとに
    out = []   # 近すぎる打点・両手の間（apply と同じ決まり）
    for h in sorted(hits, key=lambda h: (h.beat, -h.s)):
        if out and h.beat - out[-1].beat < 0.124:
            continue
        out.append(h)
    for i, h in enumerate(out):
        if h.hands == 2:
            need = 0.25 if getattr(h, 'force_dbl', False) else 0.5
            if (i > 0 and h.beat - out[i - 1].beat < need - E) or (i + 1 < len(out) and out[i + 1].beat - h.beat < need - E):
                h.hands = 1
    row = ({'b0': it['line'][0]['b'], 'b1': it['line'][-1]['b']}, None, None,
           [f'全体の量のライン（自動のくり返しの後・足し {cnt["add"]}・減らし {cnt["drop"]}・うち、くり返しの回に同じ位置で写した {cnt["copy"]}）'])
    return out, row
