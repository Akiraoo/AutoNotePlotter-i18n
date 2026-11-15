"""結果のファイルを土台にした作り直しを compose を通して確かめる（作り物の曲・32 秒・分けた音とテーマの型も作り物）:
- 前の譜面に寄せる（--prev-intent・__main__._prev_plan・_prev_sync・_prev_parity・docs/アプリ仕様.md 11 節）: 指示を変えていない所は前の
  譜面のまま・変えた区間だけ変わる・自由に作る所（前後 kime.ANCHOR_MARGIN 拍）の振りの数の偶奇は前の譜面に合わせる。
  今の作りで満たさない所（続けて左右反転・自動の同じ振りと一緒の時）は strict の xfail で残す（直ったら xfail を外す）。
- 「ここから」のマーカー（cmd_compose の rhythm.regen_from・nlmf.items_before・flow.init_from）: その拍より前は結果のファイルのまま
  （作ったクリップの中のボム・アーク・標準外の項目も）・後ろだけ作り直す・残した所の最後の振りを引き継ぐ・--fresh の時は使わない。
利用者の out/・cache/・設定は読まない（--stems・--out は写しの場所・型は作り物＝library_use.export を差し替える・NJS は設定の写しで切る＝
nlm-rating を動かさない）"""
import json
import shutil
import time
import types

import numpy as np
import pytest
import soundfile as sf

from automap import __main__ as cli
from automap import flow, kime, library_use, nlmf, njs, rating, written
from test_library_use import _themes

EP = 'expertplusstandard.dat'
NAME = '曲'
BPM, SECS, SR = 120.0, 32.0, 22050
END = SECS * BPM / 60   # 64 拍＝16 小節
EMPTY = {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}}
PLAIN = ('--no-auto-repeat', '--no-echo')   # 前の譜面に寄せる仕組みだけを見る時（自動の同じ振り・続けて左右反転を切る）
MARKERS = [{'beat': 0, 'name': 'Aメロ'}, {'beat': 16, 'name': 'Bメロ'}, {'beat': 32, 'name': 'サビ'}, {'beat': 48, 'name': 'Cメロ'}]


def _stems(d):
    """分けた音の作り物（半拍ごとのドラム・2 小節でくり返す歌の高さ・ベース・伴奏）と separate.json"""
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(5)
    t = np.arange(int(SECS * SR)) / SR
    beat = 60 / BPM
    drums = np.zeros_like(t)
    for i in range(int(SECS / beat * 2)):
        a = int(i * beat / 2 * SR)
        n = int((0.05 if i % 2 == 0 else 0.02) * SR)
        drums[a:a + n] += rng.normal(scale=0.4 if i % 4 == 0 else 0.15, size=len(drums[a:a + n]))
    voc = np.zeros_like(t)
    mel = [0, 2, 4, 5, 7, 5, 4, 2, 0, 4, 7, 9, 7, 4, 2, 0]
    for i in range(int(SECS / beat)):
        if i % 8 in (6, 7):
            continue
        a, b = int(i * beat * SR) + 200, int((i + 0.8) * beat * SR)
        voc[a:b] = 0.3 * np.sin(2 * np.pi * 220 * 2 ** (mel[i % 16] / 12) * t[a:b])
    bass = 0.3 * np.sin(2 * np.pi * 55 * t) * (np.floor(t / beat) % 2 == 0)
    other = 0.1 * (np.sin(2 * np.pi * 261.6 * t) + np.sin(2 * np.pi * 329.6 * t)) + 0.01 * rng.normal(size=len(t))
    for k, y in (('drums', drums), ('vocals', voc), ('bass', bass), ('other', other)):
        sf.write(d / f'{k}.flac', np.stack([y, y], axis=1).astype(np.float32), SR)
    (d / 'separate.json').write_text(json.dumps({'seconds': SECS}), encoding='utf-8')


def _proj():
    """元のプロジェクト（Expert+ だけ・ノーツ無し・区間 4 つ）"""
    return {'format': 'nlmf', 'version': 2, 'bpm': BPM, 'tempoParts': [], 'current': 'ExpertPlusStandard.dat', 'notesLanes': 1,
            'lightLanes': 1, 'markers': [dict(m) for m in MARKERS], 'laneStates': {'mute': [], 'solo': [], 'lock': []},
            'graph': {'out': {'diffs': {'ExpertPlus': 1}}},
            'difficulties': {EP: {'name': 'ExpertPlusStandard.dat', 'v3': True, 'base': {}, 'notes': [], 'bombs': [], 'walls': [],
                                  'arcs': [], 'chains': [], 'lightEvents': [],
                                  'sections': [{'id': 'l1', 'beat': 0, 'track': 0, 'lk': 'l', 'len': END, 'label': 'light', 'content': {}}]}}}


# 型の出どころ: 時期を決めた絞り込み（自動でない＝データベースで年を数えない）。書き出しは作り物の型（library_use.export を差し替える）
LIB = json.dumps({'sources': ['ranked'], 'stars': [0, 8], 'diffs': ['Expert', 'ExpertPlus']})


def _no_rating(mp, d):
    """NJS は書かない（njs_auto: false）＝★を測る部品（nlm-rating）を動かさない・利用者の設定を読まない。型は作り物
    （_themes と同じ・曲の数 899＝テーマに使うしきい値は 8・3・選んだ譜面の割合 stats も 1回だけの並び once も無い＝前の --themes と同じ答え）"""
    cfg = d / 'config.json'
    cfg.write_text(json.dumps({'njs_auto': False}), encoding='utf-8')
    mp.setattr(njs, 'CONFIG', cfg)
    mp.setattr(rating, 'CONFIG', cfg)
    mp.delenv('NLM_RATING_EXE', raising=False)
    mp.setattr(library_use, 'export', lambda spec: _themes(library={'filters': library_use.filters_of(spec)}))


def _make(d):
    """作り物の曲（分けた音・テーマの型・元のプロジェクト）と土台の結果のファイル（曲の解析の控えもここで作る）:
    first＝元のプロジェクトから意思入れなしで 1 回作った物・settled＝それを同じ表で 1 回作り直した物（前の譜面に寄せる作り直しの 2 回目
    からと同じ）・plain＝自動の同じ振りと続けて左右反転を切って同じように 2 回作った物"""
    _stems(d / 'cache' / NAME)
    src, it = d / f'{NAME}.nlmf', d / 'empty.intent.json'
    nlmf.save(_proj(), src)
    it.write_text(json.dumps(EMPTY), encoding='utf-8')
    first, settled, plain = (d / k / f'{NAME}.intent-s1.nlmf' for k in ('first', 'settled', 'plain'))
    with pytest.MonkeyPatch.context() as mp:
        _no_rating(mp, d)
        _run(d, src, first, it)
        settled.parent.mkdir()
        _copy(first, settled)
        _run(d, settled, settled, it, '--prev-intent', str(it))
        _run(d, src, plain, it, *PLAIN)
        _run(d, plain, plain, it, '--prev-intent', str(it), *PLAIN)


@pytest.fixture(scope='session')
def song(tmp_path_factory, worker_id):
    """_make の場所。並べて流す時は働き手みんなで 1 つを使う（最初の 1 人が作り、ほかは出来上がりを待つ＝曲の解析と土台の作り直しを
    働き手ごとにくり返さない・作った後は読むだけ）。場所はこの回の一時フォルダの中（ほかの回と混ざらない）"""
    base = tmp_path_factory.getbasetemp()
    root = (base if worker_id == 'master' else base.parent) / 'compose_regen_song'
    lock, done = root.parent / (root.name + '.lock'), root / 'done'
    t0 = time.monotonic()
    while not done.exists():
        try:
            lock.mkdir()
        except FileExistsError:   # ほかの働き手が作っている
            if time.monotonic() - t0 > 300:
                pytest.fail(f'作り物の曲ができない（{lock} が残っている）')
            time.sleep(0.05)
            continue
        try:
            if not done.exists():
                shutil.rmtree(root, ignore_errors=True)   # 途中で落ちた物は作り直す
                root.mkdir()
                _make(root)
                done.touch()
        finally:
            lock.rmdir()
    return root


def _run(d, src, out, it, *extra):
    cli.main(['compose', str(src), '--stems', str(d / 'cache' / NAME), '--library', LIB, '--form', '--style',
              '--intent', str(it), '--out', str(out), '--beam', '12', *extra])
    return out.with_suffix('.report.md').read_text(encoding='utf-8')


def _copy(src, out):
    """結果のファイルとこちらで書いた印（.state/）と報告を写す（写した先でも「こちらで書いたまま」・アプリと同じに結果のファイルの隣に
    報告がある＝前の版のくり返しの組を報告から引き継げる。前は報告を写さず、引き継ぎが効かないまま曲の全部で組み直していた）"""
    shutil.copy2(src, out)
    if src.with_suffix('.report.md').exists():
        shutil.copy2(src.with_suffix('.report.md'), out.with_suffix('.report.md'))
    (out.parent / '.state').mkdir(exist_ok=True)
    shutil.copy2(src.parent / '.state' / (src.name + '.json'), out.parent / '.state' / (out.name + '.json'))
    assert not written._edited_since_written(out)


def _work(src, tmp_path, monkeypatch):
    _no_rating(monkeypatch, tmp_path)
    out = tmp_path / f'{NAME}.intent-s1.nlmf'
    _copy(src, out)
    return tmp_path, out


@pytest.fixture
def work(song, tmp_path, monkeypatch):
    """1 回作った結果のファイルの写し → (作業の場所, 結果のファイル)"""
    return _work(song / 'first' / f'{NAME}.intent-s1.nlmf', tmp_path, monkeypatch)


@pytest.fixture
def settled(song, tmp_path, monkeypatch):
    """同じ表で 1 回作り直した結果のファイルの写し → (作業の場所, 結果のファイル)"""
    return _work(song / 'settled' / f'{NAME}.intent-s1.nlmf', tmp_path, monkeypatch)


@pytest.fixture
def plain(song, tmp_path, monkeypatch):
    """自動の同じ振りと続けて左右反転を切って作った結果のファイル（同じ表で 1 回作り直した物）の写し"""
    return _work(song / 'plain' / f'{NAME}.intent-s1.nlmf', tmp_path, monkeypatch)


def _table(d, name, t):
    p = d / f'{name}.intent.json'
    p.write_text(json.dumps(t, ensure_ascii=False), encoding='utf-8')
    return p


def _notes(p):
    return sorted((nlmf._r(n['beat']), n['x'], n['y'], n['c'], n['d']) for n in nlmf.clip_notes(nlmf.load(p), EP, include_muted=True))


# ---- 前の譜面に寄せる（--prev-intent） ----

def test_same_table_keeps_the_previous_chart(song, settled):
    """指示を変えずに作り直すと、前の譜面と 1 つも違わない（自由に作る所は無し）"""
    d, out = settled
    before = _notes(out)
    t0 = _table(d, 'prev', EMPTY)
    rep = _run(song, out, out, t0, '--prev-intent', str(t0))
    assert _notes(out) == before and len(before) > 30
    assert '前の譜面に寄せた' in rep and '自由に作った所: 無し' in rep


def test_same_table_keeps_the_first_chart(song, work):
    """新しく作った譜面（続けて左右反転・自動の同じ振り・短い往復あり）を、指示を変えずに初めて作り直しても前の譜面のまま。
    前は 58 ノーツ中 17 が変わった（2 回目からは同じ）: 反転の印（echo.plan）と短い往復（loops.plan）が前の譜面に寄せた打点を決めたノーツとみて
    印を付けず、同じ振りの手本（_fix_motifs）を写す側も前の譜面に寄せた 1 回目の計算から取った。くり返しの数も 1 回目と同じ"""
    d, out = work
    before = _notes(out)
    rep0 = (song / 'first' / out.with_suffix('.report.md').name).read_text(encoding='utf-8')
    t0 = _table(d, 'prev', EMPTY)
    rep = _run(song, out, out, t0, '--prev-intent', str(t0))
    assert _notes(out) == before
    line = lambda r, k: next(x for x in r.splitlines() if x.startswith(f'- {k}')).split('。できた譜面')[0]
    for k in ('同じ音楽の区間', '続けて左右反転', '短い往復'):
        assert line(rep, k) == line(rep0, k)
    assert '往復の区間 0' not in rep and '左右反転になった 0' not in rep


def _swings(notes, a, b):
    """拍 a 以上 b 未満の振りの数（同じ拍・同じ手の重なりは 1 つ・_prev_plan と同じ数え方の片手 1・両手 2）"""
    return len({(n[0], n[3]) for n in notes if a - 1e-6 <= n[0] < b - 1e-6 and n[3] in (0, 1)})


def _odd_rest(song, before):
    """休みにすると消える振りの数が奇数の区間（小節の中の 1〜3 拍・曲の頭と終わりの 2 小節は除く）→ (始まり, 終わり, 小節の頭, 次の小節の頭)"""
    bars = json.loads((song / 'cache' / NAME / 'music.json').read_text(encoding='utf-8'))['bars']
    return next((bars[i] + o, bars[i] + o + L, bars[i], bars[i + 1]) for i in range(2, len(bars) - 3) for L in (1, 2, 3)
                for o in range(0, 4 - L + 1) if _swings(before, bars[i] + o, bars[i] + o + L) % 2 == 1)


def _same_outside(before, after, x, y):
    """自由に作る所（拍 x〜y と前後 kime.ANCHOR_MARGIN 拍）の外で、前の譜面と同じ置き方のノーツの割合"""
    m = kime.ANCHOR_MARGIN
    out = lambda ns: {n for n in ns if not x - m - 1e-6 <= n[0] < y + m - 1e-6}
    return len(out(before) & out(after)) / max(1, len(out(before)))


def _rest_and_back(song, d, out, *flags):
    before = _notes(out)
    a, b, x, y = _odd_rest(song, before)
    t0 = _table(d, 'prev', EMPTY)
    t1 = _table(d, 'now', dict(EMPTY, ranges=[{'b0': a, 'b1': b, 'set': {'rest': 1}}]))
    rep1 = _run(song, out, out, t1, '--prev-intent', str(t0), *flags)
    after = _notes(out)
    rep2 = _run(song, out, out, t0, '--prev-intent', str(t1), *flags)
    return before, after, _notes(out), (a, b, x, y), rep1, rep2


def test_changed_range_only_changes_there_and_keeps_the_swing_parity(song, plain):
    """休みの区間を 1 つ足して作り直す（前の表と比べて変わったのはその区間だけ）: 休みの区間は空・自由に作る所（区間を含む小節と前後
    kime.ANCHOR_MARGIN 拍）の外は前の譜面のまま（弱く寄せる＝9 割以上・test_anchor と同じ目安）。休みで消える振りの数が奇数の区間を選ぶ
    ＝そのままだと振りの向きの位相がずれる → 自由に作る所の振りの数の偶奇を前の譜面に合わせる（_prev_parity）。前の表に戻すと、
    その小節だけ作り直して打点が戻る。寄せる仕組みだけを見るため、自動の同じ振り・続けて左右反転は切る（一緒の時は下の xfail）"""
    d, out = plain
    before, after, again, (a, b, x, y), rep1, rep2 = _rest_and_back(song, d, out, *PLAIN)
    m = kime.ANCHOR_MARGIN
    assert not [n for n in after if a <= n[0] < b] and [n for n in again if a <= n[0] < b]
    assert _same_outside(before, after, x, y) >= 0.9 and _same_outside(after, again, x, y) >= 0.9
    for ns in (after, again):
        assert _swings(ns, x - m, y + m) % 2 == _swings(before, x - m, y + m) % 2
    assert f'自由に作った所: 拍 {x:g}〜{y:g}' in rep1 and '振りの数の偶奇を合わせた' in rep1
    assert f'自由に作った所: 拍 {x:g}〜{y:g}' in rep2


def _free_of(rep):
    """報告の「自由に作った所: 拍 a〜b・c〜d（前後 …」→ [(a, b), (c, d)]"""
    import re
    m = re.search(r'自由に作った所: 拍 ([^（]+)（前後', rep)
    return [tuple(float(v) for v in s.split('〜')) for s in m.group(1).split('・')] if m else []


def _same_outside_spans(before, after, spans):
    """自由に作る所（spans と前後 kime.ANCHOR_MARGIN 拍）の外で、前の譜面と同じ置き方のノーツの割合"""
    m = kime.ANCHOR_MARGIN
    out = lambda ns: {n for n in ns if not any(x - m - 1e-6 <= n[0] < y + m - 1e-6 for x, y in spans)}
    return len(out(before) & out(after)) / max(1, len(out(before)))


def test_changed_range_only_changes_there_with_repeats(song, settled):
    """既定の作り（自動の同じ振り・続けて左右反転あり）でも、変えた区間の外は前の譜面のまま（9 割以上）。くり返しの組は前の版から
    引き継ぎ（曲の全部で組み直さない）、変えた所にかかる小節だけ組から外す。組から外した小節の写す側は自由に作らない（利用者「ミラー側へ
    コピーする必要はない」＝報告の「自由に作った所」は変えた区間だけ）。その後に指示を変えずに作り直しても変わらない（前は休みの回に
    変わった手本に写す側が次の回で追いつき、こだまの写しで拍 200〜400 の半分が遅れて変わった）。
    直したのは 2026-11-10（棚上げの 2・docs/アプリ仕様.md 24 節）: 流れの計算の先読みが振りの順のやり直しを見込む（flow._fix_look）・
    寄せる所は片手・両手も前の譜面に合わせる（_prev_sync）・つなぎ目のゆとりにある同じ振りの打点は寄せる（_prev_anchor）"""
    d, out = settled
    before, rep0 = _notes(out), out.with_suffix('.report.md').read_text(encoding='utf-8')
    a, b, x, y = _odd_rest(song, before)
    t0 = _table(d, 'prev', EMPTY)
    t1 = _table(d, 'now', dict(EMPTY, ranges=[{'b0': a, 'b1': b, 'set': {'rest': 1}}]))
    rep1 = _run(song, out, out, t1, '--prev-intent', str(t0))
    after = _notes(out)
    assert not [n for n in after if a <= n[0] < b]
    assert _free_of(rep1) == [(x, y)]
    assert _same_outside(before, after, x, y) >= 0.9
    assert '前の版のくり返しの組を引き継いだ' in rep1
    _run(song, out, out, t1, '--prev-intent', str(t1))   # 指示を変えずにもう一度
    assert _notes(out) == after
    # 休みを外す: 分かれた組は元の形に戻る（2026-11-10 利用者「分かれた組だけ元の形に戻す」・repeat.regrow・echo.unify の grow）
    groups = lambda r: next(x for x in r.splitlines() if x.startswith('- 同じ音楽の区間（'))
    rep3 = _run(song, out, out, t0, '--prev-intent', str(t1))
    back = _notes(out)
    assert groups(rep3) == groups(rep0)
    assert '指示が無くなった所で組を元の形に戻した' in rep3
    assert _same_outside(before, back, -1, -1) >= 0.9
    _run(song, out, out, t0, '--prev-intent', str(t0))
    assert _notes(out) == back


def test_prev_plan_does_not_anchor(tmp_path):
    """前の譜面に寄せない時（理由を報告に出す）: --no-anchor・--prev-intent が無い・結果のファイルが無い／--fresh・曲の全部の案・
    全体の設定（自動の休み）を変えた・前の譜面に作ったノーツが無い"""
    pi = tmp_path / 'prev.intent.json'
    pi.write_text(json.dumps(EMPTY), encoding='utf-8')
    A = lambda **kw: types.SimpleNamespace(**{'no_anchor': None, 'prev_intent': str(pi), 'fresh': False, 'variant': 0, 'rare': False,
                                              'band': None, **kw})
    plan = {'prev_notes': [{'beat': 8.0, 'x': 1, 'y': 0, 'c': 0, 'd': 1}, {'beat': 8.0, 'x': 2, 'y': 0, 'c': 1, 'd': 1},
                           {'beat': 8.01, 'x': 1, 'y': 1, 'c': 0, 'd': 1}, {'beat': 9.0, 'x': 0, 'y': 0, 'c': 3, 'd': 0}]}
    mu, tm = {'bars': [0, 4, 8, 12]}, nlmf.TempoMap(BPM)
    go = lambda a, plan=plan, it=None, only=None: cli._prev_plan(a, plan, it, mu, 16, only, tm)
    assert go(A(no_anchor='画面で寄せない')) == {'why': '画面で寄せない'}
    assert go(A(prev_intent=None)) == {}
    assert go(A(), plan=None)['why'].startswith('結果のファイルが無い')
    assert go(A(fresh=True), plan=None)['why'].startswith('--fresh')
    assert go(A(variant=2))['why'].startswith('曲の全部の案') and go(A(rare=True))['why'].startswith('曲の全部の案')
    assert go(A(), it=dict(EMPTY, auto_rest={'on': True, 'b': None}))['why'] == '全体の設定（自動の休み）を変えた'
    assert go(A(), plan={'prev_notes': [{'beat': 9.0, 'x': 0, 'y': 0, 'c': 3, 'd': 0}]})['why'] == '前の譜面に作り直すノーツが無い'
    got = go(A())   # 寄せる: 拍ごとの手の置き方（同じ色が 0.07 秒以内に続く物は 1 つ・ボム等は入れない）
    assert got['at'] == {8.0: {0: (1, 0, 1), 1: (2, 0, 1)}} and got['free'] == [] and got['n'] == 0
    got = go(A(variant=2), only=(4.0, 8.0))   # 選んだ区間の別の案: その区間は自由に
    assert got['free'] == [(4.0, 8.0)] and '別の案の区間' in got['what']


# ---- 「ここから」のマーカー ----

CUT = 20.0
SENT = (0, 0, 8)   # 作り直す所に置いておく目印のノーツ（点・左下）＝作り直したら残らない


def _prepared(out, last_d):
    """結果のファイルを「ここから」（拍 20）の前後で目印の入った作ったクリップ（id＝中身の指紋＝作ったまま）に置き換え、マーカーを足す。
    拍 0〜8 は丸ごと前（ボムつき）・拍 8〜16 は丸ごと前で NLM で手で直した物（アーク・標準外の項目つきのノーツ・中身が指紋と合わない）・
    拍 16〜32 は「ここから」をまたぐ（前の部分にもボム・アーク・標準外の項目）・拍 32〜64 は後ろ。前の最後の振りは左右とも向き last_d
    → (プロジェクト, 丸ごと前の作ったまま・手で直したクリップの id)"""
    p = nlmf.load(out)
    cls, _, lane = nlmf.classify(p, EP)
    assert lane is not None and {st for _, st in cls} == {'app'}
    nlmf.remove_clips(p, EP, [s for s, _ in cls])
    N = lambda b, x, y, c, d: {'beat': b, 'x': x, 'y': y, 'c': c, 'd': d}
    alt = lambda b0, b1: [N(b0 + 0.5 * i, 1 + i % 2, 0, i % 2, 1 if (i // 2) % 2 == 0 else 0) for i in range(int((b1 - b0) * 2))]
    head = alt(4, 16)
    # 拍 16〜19.5: 左手 16・17・18・19、右手 16.5・17.5・18.5・19.5 が振りの交互で、最後（19・19.5）が向き last_d。右手の 17.5 は標準外の項目つき
    d_at = lambda k: last_d if (3 - k) % 2 == 0 else 1 - last_d
    cross = [N(16 + k, 1, 0, 0, d_at(k)) for k in range(4)] + [N(16.5 + k, 2, 0, 1, d_at(k)) for k in (0, 2, 3)]
    after = lambda b0, b1: [N(b + 0.75, *SENT[:2], int(b) % 2, SENT[2]) for b in range(b0, b1)]
    raw = lambda b, c, d: [b, 2, 0, c, d, None, {'a': 15}]
    clips = [{'beat': 0, 'len': 8, 'label': '自動 Aメロ', 'notes': head, 'extra': {'bombs': [[6.25, 1, 1, None]]}},
             {'beat': 8, 'len': 8, 'label': '自動 Aメロ', 'notes': head,
              'extra': {'arcs': [[8, 1, 0, 0, 1, 1, 10, 2, 1, 0, 0, 0, None]], 'notes': [raw(12.25, 1, 1)]}},
             {'beat': 16, 'len': 16, 'label': '自動 Bメロ', 'notes': cross + after(20, 32),
              'extra': {'bombs': [[18.25, 2, 1, None], [24.25, 2, 1, None]], 'arcs': [[17, 1, 0, 1, 1, 1, 18.5, 2, 1, 0, 0, 0, None]],
                        'notes': [raw(17.5, 1, d_at(1))]}},
             {'beat': 32, 'len': 16, 'label': '自動 サビ', 'notes': after(32, 48)},
             {'beat': 48, 'len': 16, 'label': '自動 Cメロ', 'notes': after(48, 64)}]
    nlmf.put_clips(p, EP, clips, lane)
    secs = {s['beat']: s for s in nlmf.note_clips(p['difficulties'][EP])}
    secs[8]['content']['notes'][0][1] = 3   # NLM で手で直した（id の指紋と中身が合わない）
    p['markers'].append({'beat': CUT, 'name': 'ここから'})
    written._save(p, out)
    assert [st for _, st in sorted(nlmf.classify(p, EP)[0], key=lambda x: x[0]['beat'])] == ['app', 'edited', 'app', 'app', 'app']
    return p, (secs[0]['id'], secs[8]['id'])


def _first_after(notes, c):
    return min((n for n in notes if n[0] >= CUT and n[3] == c), key=lambda n: n[0])


@pytest.mark.parametrize('last_d,want', [(1, flow.B), (0, flow.F)])
def test_regen_from_marker_keeps_before_and_continues_the_swing(song, work, last_d, want):
    """「ここから」より前は結果のファイルのまま（ノーツ・ボム・アーク・標準外の項目。丸ごと前の作ったクリップはそのまま・またぐクリップは
    前の部分を新しいクリップへ移す）・後ろは作り直す（目印が残らない）・前の最後の振り（左右とも振り下ろし／振り上げ）の続きから"""
    d, out = work
    before, head = _prepared(out, last_d)
    rep = _run(song, out, out, _table(d, 'prev', EMPTY))
    p = nlmf.load(out)
    assert nlmf.items_before(p, EP, CUT) == nlmf.items_before(before, EP, CUT)
    assert len(nlmf.items_before(p, EP, CUT)['bombs']) == 2 and len(nlmf.items_before(p, EP, CUT)['arcs']) == 2
    keep = {s['id']: s for s in nlmf.note_clips(p['difficulties'][EP])}
    old = {s['id']: s for s in nlmf.note_clips(before['difficulties'][EP])}
    assert all(keep.get(i) == old[i] for i in head)   # 丸ごと前のクリップ（作ったまま・手で直した物）はそのまま残した
    after = _notes(out)
    new = [n for n in after if n[0] >= CUT]
    assert len(new) > 30 and not [n for n in new if (n[1], n[2], n[4]) == SENT and n[0] % 1 == 0.75]
    assert not [b for b in nlmf.items_before(nlmf.load(out), EP, 99)['bombs'] if b[0] >= CUT]   # 後ろのボムは作り直しで消えた
    assert {st for _, st in nlmf.classify(p, EP)[0]} == {'app', 'edited'} and nlmf.coverage_holes(p, EP, nlmf.classify(p, EP)[2], END) == []
    for c in (0, 1):   # 残した所の最後の振り（拍 19・19.5）の続きから＝左右とも逆の向きで始める（flow.init_from）
        assert flow.parity_of(c, _first_after(after, c)[4]) == want
    assert f'「ここから」（拍 {CUT:g}）より前は結果のファイルのまま残した' in rep


def test_regen_from_marker_is_ignored_with_fresh(song, work):
    """--fresh（入力を土台にする）の時は「ここから」を使わない: 前の目印・ボム・アーク・標準外の項目も残らず、全部を作り直す"""
    d, out = work
    _, head = _prepared(out, 1)
    rep = _run(song, out, out, _table(d, 'prev', EMPTY), '--fresh')
    p = nlmf.load(out)
    assert not set(head) & {s['id'] for s in nlmf.note_clips(p['difficulties'][EP])}   # 手で直したクリップも残らない（入力を土台に）
    keep = nlmf.items_before(p, EP, CUT)
    assert not keep['bombs'] and not keep['arcs'] and not [t for t in keep['notes'] if len(t) > 6]
    notes = _notes(out)
    assert [n for n in notes if n[0] < CUT] and not [n for n in notes if (n[1], n[2], n[4]) == SENT and n[0] % 1 == 0.75]
    assert 'ここから' not in rep and {m['name'] for m in p['markers']} >= {'ここから'}   # マーカーは消さない
