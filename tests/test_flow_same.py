"""流れの計算（flow.generate）を速くする直しで、答えが1ビットも変わらないことの確かめ（2026-11-02）。

作り物の打点の並び（乱数の種で決まる・片手と両手・テーマの型・山の音・強い打点・歌の高さ・振りの速さの上限・長い休み・
決めたノーツとその重み・意思入れの置き方・前の振りの引き継ぎ・揺らぎ 0 の同点）を、速くする前のコードで計算した答え
（ノーツと減点の合計を float.hex で）を tests/data/flow_same.json に控えてあり、今のコードの答えがそれと全く同じかを見る。
2026-11-09 に今の作り直しの道（RICH: 手から見た列・両手の外・マスの目標・左右の倍率・受け渡し・続けて左右反転・短い往復・息つぎ・
前の譜面に寄せる弱い決め・残したノーツの重い決め）を足した。その控えは、絞り込みが外れた時の数え直しを速くする前（コミット 1161940）の
flow.py で作った。前からあるケースの控えは変えていない。2026-11-10 に先読みの直しで --write した後、流れの計算を Numba（automap/flow_nb.py）に
した（答えは同じ＝控えはそのまま）。
控えを作り直す（流れの計算の答えをわざと変えた時だけ）: .venv/Scripts/python.exe tests/test_flow_same.py --write
ケースを足した時（足した物だけ計算して控えの終わりに足す・前からある物は 1 バイトも変えない）: ... tests/test_flow_same.py --add [注]
"""
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from automap import flow  # noqa: E402

DATA = Path(__file__).resolve().parent / 'data' / 'flow_same.json'

# 作り物の並びの設定。style: plain＝Style の既定・compose＝作り直しの既定（割合の重み 0）・tilt＝試作5（割合を弱く）・flat＝揺らぎ 0（同点が多い）
CASES = [
    dict(name='plain', seed=11, n=160, style='plain', beam=24),
    dict(name='compose', seed=12, n=220, style='compose', beam=64, theme=True, accent=True, py=True),
    dict(name='tilt', seed=13, n=220, style='tilt', beam=64, theme=True, accent=True, strong=True, gap=True),
    dict(name='fix', seed=14, n=200, style='tilt', beam=48, theme=True, fix=True, strong=True),
    dict(name='mods', seed=15, n=200, style='compose', beam=32, mods=True, gap=True, py=True),
    dict(name='init', seed=16, n=150, style='tilt', beam=40, init=True, theme=True, fix=True, mods=True),
    dict(name='flat', seed=17, n=150, style='flat', beam=16, doubles=0.3),
    dict(name='narrow', seed=18, n=180, style='compose', beam=8, theme=True, fix=True, accent=True),
]


def make_style(p):
    kind = p['style']
    if kind == 'plain':
        st = flow.Style(seed=p['seed'])
    else:
        st = flow.Style(seed=p['seed'], noise=0.05, col_cost=(1.5, 0.3, 0.05, 0.0), w_same_hand=1.0, min_gap=0.15, w_center=2.0,
                        w_target={k: 0.0 for k in ('row', 'dir', 'center', 'still', 'alt', 'col')}, w_pitch=0.35 if p.get('py') else 0.0)
        if kind == 'tilt':
            st.targets = dict(flow.LIBRARY_EPLUS, row=(0.4, 0.3, 0.3), dir=(0.5, 0.42, 0.08), col=(0.26, 0.24, 0.24, 0.26))
            st.w_target = {'row': 1.0, 'dir': 1.5, 'col': 1.5, 'center': 0.3, 'still': 0.4, 'alt': 0.5}
            st.w_theme_cell, st.w_theme_dir, st.w_center = 2.0, 1.0, 4.0
        elif kind == 'flat':
            st.noise = 0.0
    st.beam = p['beam']
    return st


def make_case(p):
    """設定 → (打点の並び, Style, init)。同じ設定からは必ず同じ物"""
    rnd = random.Random(p['seed'])
    bpm = rnd.choice((120, 129, 150, 175))
    spb = 60.0 / bpm
    steps = (0.25, 0.5, 0.5, 0.5, 1.0, 1.0, 0.75, 1 / 3, 2.0)
    beat, evs, gid, cyc = 4.0, [], -1, None
    fix_from = rnd.randrange(p['n'] // 3, p['n'] // 2)
    mods_from = rnd.randrange(p['n'] // 4, p['n'] // 2)
    for i in range(p['n']):
        if p.get('theme') and i % 24 == 0:   # 区間ごとにテーマの型（無い区間もある）
            if rnd.random() < 0.75:
                gid += 1
                cyc = {h: [(rnd.randrange(4), rnd.randrange(3), rnd.randrange(8)) for _ in range(rnd.randint(2, 4))] for h in (0, 1)}
            else:
                cyc = None
        hands = 2 if rnd.random() < p.get('doubles', 0.15) else 1
        ev = flow.Event(round(beat, 6), beat * spb, hands, gid if cyc else -1, cyc)
        if p.get('accent') and rnd.random() < 0.12:
            ev.accent = True
        if p.get('strong') and rnd.random() < 0.3:
            ev.strong = 0.4 if hands == 2 else 0.2
        if p.get('py') and rnd.random() < 0.7:
            ev.py = rnd.choice((0.0, 0.5, 1.0, 1.5, 2.0))
        if p.get('gap') and rnd.random() < 0.15:
            ev.min_gap = rnd.choice((0.25, 0.4))
        if p.get('fix') and fix_from <= i < fix_from + 30:
            hs = (0, 1) if hands == 2 else (rnd.randrange(2),)
            ev.fix = {h: (rnd.randrange(4), rnd.randrange(3), rnd.choice((0, 1, 2, 3, 4, 5, 6, 7, 8))) for h in hs}
            if i % 3 == 0:
                ev.fix_w = 20.0
        if p.get('mods') and mods_from <= i < mods_from + 40:
            ks = rnd.sample(('move', 'width', 'height', 'diag', 'turn', 'bigmove'), 3)
            ev.mods = {k: rnd.choice((-1, 1, 2)) for k in ks}
        evs.append(ev)
        beat += rnd.choice(steps) if rnd.random() > 0.03 else rnd.choice((4.0, 6.0))   # まれに長い休み（振りの向きを戻してよい）
    init = None
    if p.get('init'):
        class _T:
            def sec(self, b):
                return b * spb
        notes = [{'beat': 0.0, 'x': 1, 'y': 0, 'c': 0, 'd': 1}, {'beat': 0.0, 'x': 2, 'y': 0, 'c': 1, 'd': 1},
                 {'beat': 1.0, 'x': 3, 'y': 2, 'c': 1, 'd': 0}, {'beat': 2.0, 'x': 0, 'y': 1, 'c': 0, 'd': 8}]
        init = flow.init_from(notes, _T())
    return evs, make_style(p), init


# 今の作り直しの道（2026-11-09）: 作り直し（compose の試作5）と同じ方針の数（__main__ の fst・style.W_TARGET・W_CENTER・LEFT_FAST_W・
# HAND_TECH_K の値を写した物＝そちらを変えてもこのテストは変わらない）と、打点の印。parts＝曲を作る区切りの種類（下の make_rich）・
# anchor＝前の譜面・基準に弱く寄せる重み（自由に作る所を除く）・derive＝展開の派生の振りの間と休みの後の減点・kept＝選んだ区間だけ
# 作り直す（外は残したノーツの重い決め）・flat＝揺らぎ 0（同点が多い）・init＝前の振りを引き継ぐ。
# どれも前の Python 版の候補の絞り込み（上位 PRUNE）が外れやすい並び（Numba 版は絞り込まない・2026-11-10）
RICH = [
    dict(name='rank', seed=21, n=300, beam=64, parts=('plain', 'echo', 'loop', 'want', 'flex', 'relief', 'mods')),
    dict(name='rank_anchor', seed=22, n=260, beam=48, parts=('plain', 'echo', 'loop', 'want', 'flex'), anchor=0.5, derive=True),
    dict(name='rank_kept', seed=23, n=260, beam=48, parts=('plain', 'echo', 'want', 'loop', 'mods'), kept=True, init=True),
    dict(name='rank_flat', seed=24, n=220, beam=24, parts=('plain', 'echo', 'loop', 'want', 'flex', 'relief'), flat=True),
    dict(name='rank_narrow', seed=25, n=220, beam=8, parts=('plain', 'echo', 'loop', 'flex', 'mods'), anchor=0.2),
]
ALL = CASES + RICH
RANK_TARGETS = dict(flow.LIBRARY_EPLUS, row=(0.43, 0.38, 0.19), dir=(0.59, 0.39, 0.02), col=(0.22, 0.28, 0.28, 0.22),
                    hcol=(0.004, 0.19, 0.386, 0.42), wide=0.16,
                    cell=(0.002, 0.002, 0.0, 0.15, 0.01, 0.03, 0.3, 0.001, 0.07, 0.12, 0.25, 0.065))


def rank_style(p):
    st = flow.Style(seed=p['seed'], noise=0.0 if p.get('flat') else 0.05, col_cost=(1.5, 0.3, 0.05, 0.0), w_same_hand=1.0, min_gap=0.15,
                    w_center=4.0, w_pitch=0.35, w_left_fast=1.0, w_hand_tech=0.3,
                    w_target={'row': 1.0, 'dir': 1.5, 'col': 0.0, 'center': 0.0, 'still': 0.0, 'alt': 0.0, 'hcol': 4.0, 'wide': 8.0, 'cell': 12.0})
    st.targets = dict(RANK_TARGETS)
    if p.get('derive'):   # 展開の下の難易度: 同じ手の振りの間を広げ、休みの後で振りの順を戻す減点を重く（derive.min_gap・W_RESET）
        st.min_gap, st.w_reset = 0.19, 30.0
    st.beam = p['beam']
    return st


def _rhythm(rnd, span, dbl, steps=(0.25, 0.5, 0.5, 0.5, 1.0, 1 / 3)):
    """span 拍の中の打点 [(頭からの拍, 片手 1・両手 2)]"""
    out, t = [], 0.0
    while t < span - 1e-6:
        out.append((t, 2 if rnd.random() < dbl else 1))
        t += rnd.choice(steps)
    return out


def _prev_chart(rnd, evs):
    """前の譜面の置き方（打点ごとの {手: (x, y, d)}）: 手ごとに振り下ろしと振り上げが交互・片手は多くは左右交互・点ノーツも少し"""
    par, last, out = [None, None], 1, []
    for e in evs:
        hs = (0, 1) if e.hands == 2 else ((last if rnd.random() < 0.2 else 1 - last),)
        f = {}
        for h in hs:
            q = par[h] = flow.F if par[h] in (None, flow.B) else flow.B
            d = 8 if rnd.random() < 0.05 else rnd.choice((1, 6, 7) if q == flow.F else (0, 4, 5))
            x = rnd.choice((0, 1) if h == 0 else (2, 3)) if e.hands == 2 else rnd.randrange(4)
            f[h] = (x, rnd.choice((0, 0, 1)) if q == flow.F else rnd.choice((1, 2, 2)), d)
        if e.hands == 1:
            last = hs[0]
        out.append(f)
    return out


def make_rich(p):
    """RICH の設定 → (打点の並び, Style, init)。区切りごとに種類（parts）を選んで打点と印を作る。同じ設定からは必ず同じ物"""
    rnd = random.Random(p['seed'])
    spb = 60.0 / rnd.choice((120, 129, 150, 175, 200))
    evs, gid, cyc, beat, ho = [], -1, None, 4.0, 0

    def add(b, hands, head=False):
        b = round(b, 6)
        e = flow.Event(b, b * spb, hands, gid if cyc else -1, cyc)
        e.py = rnd.choice((0.0, 0.5, 1.0, 1.5, 2.0)) if rnd.random() < 0.7 else None
        e.accent = rnd.random() < 0.08
        e.strong = 3.0 if head else 1.5 if e.accent else 0.4 if hands == 2 else 0.2 if abs(b % 4) < 1e-6 else 0.0
        if rnd.random() < 0.1:
            e.min_gap = rnd.choice((0.25, 0.4))
        evs.append(e)
        return e

    while len(evs) < p['n']:
        if gid < 0 or rnd.random() < 0.5:   # 小節・区間ごとのテーマの型（無い所もある）
            gid += 1
            cyc = ({h: [(rnd.randrange(4), rnd.randrange(3), rnd.randrange(8)) for _ in range(rnd.randint(2, 4))] for h in (0, 1)}
                   if rnd.random() < 0.9 else None)
        kind, b0 = rnd.choice(p['parts']), beat
        if kind == 'echo':   # 続けて左右反転: 同じリズムのセットを k 回・2 つ目からに echo・短いセットは前のセットの片手を 1 つの手に（erun）
            U, k = rnd.choice((2.0, 4.0, 4.0, 8.0)), rnd.randint(2, 4)
            pat = _rhythm(rnd, U, 0.2)
            sets = [[add(b0 + j * U + t, hd, head=(j == 0 and t == 0)) for t, hd in pat] for j in range(k)]
            for st_ in sets[1:]:
                for e in st_:
                    e.echo = U
            one = [e for e in sets[0] if e.hands == 1]
            if U <= 4 and 2 <= len(one) <= 4 and (len(sets[0]) - len(one)) % 2 == 0:
                for e in one:
                    e.erun = sets[0][0].beat
            beat = b0 + k * U
        elif kind == 'loop':   # 短い往復: 1〜2 小節の片手の打点に区間の始まりの拍
            L = rnd.choice((4.0, 8.0))
            for t, _ in _rhythm(rnd, L, 0.0, (0.5, 0.5, 1.0)):
                add(b0 + t, 1, head=t == 0).loop = round(b0, 6)
            beat = b0 + L
        elif kind == 'relief':   # 息つぎ
            for t, hd in _rhythm(rnd, 4.0, 0.1, (0.5, 1.0)):
                add(b0 + t, hd, head=t == 0).relief = 2.0
            beat = b0 + 4.0
        elif kind == 'want':   # 受け渡し（決め打ち）: 片手の打点 2 つずつ手を交代・前の譜面の手を残す重みの時も
            m, step, lead = rnd.randint(2, 3), rnd.choice((0.5, 0.75, 1.0)), rnd.randrange(2)
            w = 2.5 if rnd.random() < 0.3 else None
            for i in range(2 * m):
                e = add(b0 + i * step, 1, head=i == 0)
                e.want, e.want_w, e.ho = (lead if (i // 2) % 2 == 0 else 1 - lead), w, ho
            ho += 1
            beat = b0 + 2 * m * step
        elif kind == 'flex':   # 左右反転の受け渡し: 手と始まりは流れの計算が候補ごとに決める
            m, step = rnd.randint(2, 3), rnd.choice((0.5, 1.0))
            for i in range(2 * m + 1):
                e = add(b0 + i * step, 1, head=i == 0)
                e.hoflex, e.ho = (round(b0, 6), m), ho
            ho += 1
            beat = b0 + (2 * m + 1) * step
        else:   # ふつう・意思入れの置き方の指示の区間（横の広がり +1 も）
            L, mods = rnd.choice((4.0, 8.0)), None
            if kind == 'mods':
                mods = {k_: rnd.choice((-1, 1, 2)) for k_ in rnd.sample(('move', 'width', 'height', 'diag', 'turn', 'bigmove'), 3)}
            for t, hd in _rhythm(rnd, L, 0.15):
                add(b0 + t, hd, head=t == 0).mods = mods
            beat = b0 + L
        beat += rnd.choice((0.0, 0.0, 0.5, 1.0)) if rnd.random() > 0.05 else rnd.choice((4.0, 6.0))   # 間（まれに長い休み）
    if p.get('anchor') or p.get('kept'):
        prev = _prev_chart(rnd, evs)
        lo = rnd.randrange(len(evs) // 3, len(evs) // 2)
        if p.get('anchor'):   # 前の譜面に寄せる・派生を基準に寄せる: 自由に作る所（20 打点）の外を弱く・少しだけ強め
            for i, (e, f) in enumerate(zip(evs, prev)):
                if not lo <= i < lo + 20:
                    e.fix, e.fix_w = f, (3.0 if rnd.random() < 0.02 else p['anchor'])
        else:   # 選んだ区間だけ作り直す: 外は残したノーツ（印の無い打点・重い決め）・区間の際の 4 打点は弱く
            hi = lo + len(evs) // 4
            for i, (e, f) in enumerate(zip(evs, prev)):
                if i < lo - 4 or i >= hi + 4:
                    evs[i] = flow.Event(e.beat, e.sec, e.hands, fix=f, fix_w=20.0)
                elif not lo <= i < hi:
                    e.fix, e.fix_w = f, 0.2
    init = None
    if p.get('init'):
        class _T:
            def sec(self, b):
                return b * spb
        notes = [{'beat': 0.0, 'x': 1, 'y': 0, 'c': 0, 'd': 1}, {'beat': 0.0, 'x': 2, 'y': 0, 'c': 1, 'd': 1},
                 {'beat': 1.0, 'x': 3, 'y': 2, 'c': 1, 'd': 0}, {'beat': 2.0, 'x': 0, 'y': 1, 'c': 0, 'd': 8}]
        init = flow.init_from(notes, _T())
    return evs, rank_style(p), init


def make(p):
    return make_rich(p) if p.get('parts') else make_case(p)


def run(p, counts=None):
    """設定の答え（覚えた答えは使わない）。counts に STATS の増えた分"""
    flow.forget()
    s0 = dict(flow.STATS)
    notes, cost = flow.generate(*make(p))
    if counts is not None:
        counts.update({k: v - s0.get(k, 0) for k, v in flow.STATS.items()})
    return {'notes': [[n['beat'], n['c'], n['x'], n['y'], n['d']] for n in notes], 'cost': float(cost).hex()}


def _want():
    return json.loads(DATA.read_text(encoding='utf-8'))


def test_cases_match_saved():
    assert [c['name'] for c in _want()['cases']] == [p['name'] for p in ALL], '控えと設定の並びが違う（足したなら --add で控えに足す）'


@pytest.mark.parametrize('p', ALL, ids=[p['name'] for p in ALL])
def test_generate_same_as_before(p):
    w = {c['name']: c for c in _want()['cases']}.get(p['name'])
    assert w is not None, '控えが無い（--add で足す）'
    counts = {}
    got = run(p, counts)
    assert got['cost'] == w['cost'], f"{p['name']}: 減点の合計が変わった {float.fromhex(got['cost'])} ≠ {float.fromhex(w['cost'])}"
    assert got['notes'] == w['notes'], f"{p['name']}: ノーツが変わった"


def test_memo_returns_copy_of_same_answer():
    """直前と同じ入力は覚えた答え（計算した時と同じ）の写しを返す・入力が少しでも違えば計算し直す（flow._LAST・2026-11-09）"""
    p = dict(CASES[1], n=60)
    flow.forget()
    m0 = flow.STATS['memo']
    a = flow.generate(*make_case(p))
    b = flow.generate(*make_case(p))   # 作り直した同じ値の入力（別の物）
    assert flow.STATS['memo'] == m0 + 1 and a == b
    a[0][0]['x'] = 99                   # 呼ぶ側が書き換えても、覚えた物は変わらない
    c = flow.generate(*make_case(p))
    assert flow.STATS['memo'] == m0 + 2 and c == b and c[0] is not b[0]
    evs, st, init = make_case(p)
    evs[-1].strong += 1e-12             # 打点の項目が 1 つ違う → 計算し直す
    flow.generate(evs, st, init)
    st.w_fix += 1e-12                   # 方針が違う
    flow.generate(evs, st, init)
    assert flow.STATS['memo'] == m0 + 2
    flow.forget()
    assert flow.generate(*make_case(p)) == b and flow.STATS['memo'] == m0 + 2


if __name__ == '__main__':
    if '--write' in sys.argv:
        out = {'note': '流れの計算を速くする前（2026-11-02・コミット 0a38706 の automap/flow.py）の答え。tests/test_flow_same.py が作る',
               'cases': [dict(name=p['name'], **run(p)) for p in ALL]}
        DATA.parent.mkdir(exist_ok=True)
        DATA.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        print('書いた', DATA, [(c['name'], len(c['notes']), float.fromhex(c['cost'])) for c in out['cases']])
    elif '--add' in sys.argv:   # 足したケースだけ計算して終わりに足す（前からある物の文字は 1 バイトも変えない）
        text = DATA.read_text(encoding='utf-8')
        have = [c['name'] for c in json.loads(text)['cases']]
        assert have == [p['name'] for p in ALL[:len(have)]] and text.endswith(']}'), '控えの並びが設定の頭と違う'
        i = sys.argv.index('--add')
        note = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        add = []
        for p in ALL[len(have):]:
            counts = {}
            c = dict(name=p['name'], **({'note': note} if note else {}), **run(p, counts))
            add.append(c)
            print(p['name'], len(c['notes']), float.fromhex(c['cost']), counts)
        DATA.write_text(text[:-2] + ''.join(',' + json.dumps(c, ensure_ascii=False, separators=(',', ':')) for c in add) + ']}',
                        encoding='utf-8')
        print('足した', DATA, [c['name'] for c in add])
    else:
        sys.exit('控えを作り直すのは --write・足すのは --add を付けた時だけ')
