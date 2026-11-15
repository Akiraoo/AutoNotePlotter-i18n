"""区間の点検（区間ごとの人の譜面との近さ・曲の中での似かた・崩れと警告）を画面に出す。数えるのは automap/section_check.py。
server.py の connect() が routes(ctx) を呼んでつなぐ。

- GET  /api/check?file=<結果のファイル>[&wait=秒]: 結果のファイルの譜面で数える（無ければ土台）。
- POST /api/check {file, notes?, library?, wait?}: 画面が見ている譜面（S.D.notes＝[秒, x, y, 色, 向き, 拍]・別の案や履歴の版も）で数える。
  notes が無ければ結果のファイルの基準の難易度の譜面（画面が派生の難易度を見ている時はこちら＝作り直す区間を選ぶ材料は基準）。
  library＝曲ごとのライブラリの設定（画面の S.W.library。省略は作業ファイルの library）。無ければ新しい曲の既定（ランク譜面）。
  時期が自動（years＝'auto'）なら、この曲の時期に置き換えて数える（app/library.auto_view＝compose と同じ library_use.resolve）。
- 区間は帯「区間」と同じ（曲のデータの marks）・同じ音楽は区間の名前と流れの表（blocks）の記号。
- ライブラリの並びの数は絞り込みごとに1回数えて覚えておく（数秒）。数え終わっていなければ library.state='building' で返す
  （画面は少し待って聞き直す）。データベースが無い・版が合わない時は 'unavailable'（1 の数字だけ出さない）。

決めの場所（珍しい型の「決め」・automap/kime.py＝型のデータベースの曲だけ）:
- GET /api/kime?file=<結果のファイル>[&cand=<番号> | &ver=<版>]: 作り直しの報告（<結果>.report.md・別の案は .cand の
  <曲>.cand<番号>.report.md・履歴の版は .history の <曲>.<版>.report.md）の「## 決め（珍しい型）」の表を読んで返す。
  結果のファイルがまだ無い曲は土台（server.base_of）の報告。答え: {file, state, kimes, notes}。state＝ok（節があった・
  kimes が空なら入れる所が無かった）・none（節が無い＝決めを入れない曲）・no_report（報告が無い）。kimes の1つ＝
  {b0, b1（最初と最後の振りの拍）, t（元の音源の秒）, sec（区間＋何回目）, place, place_beat, hand（0＝左・1＝右）,
  seq（その手の形 [[x, y, 向き]]）, seq_text, maps（曲の数）, freq, hard, placed, total, own, gone}。notes＝節の箇条書き（「- 」を外した物）。
  表の形は automap/__main__.py の _kime_lines・_kime_row（読むのは automap/kime.py の parse_report・parse_row＝作る側と同じ物。
  変えたら両方とテストを直す・tests/test_section_check.py で突き合わせる）。
- 区間だけ作り直した報告（別の案・この区間だけ作り直す・「ここから」）の表には、作り直した所の決めしか無い＝外の決めは前の版の
  報告（別の案→今の結果のファイル→履歴の前の版…・全部を作り直した報告まで）から拾い、見ている譜面にまだある物だけ足す
  （own＝False）。gone＝見ている譜面のその手の所が型どおりでない（NLM で直した等）。
"""
import hashlib
import json
import re
import time
from pathlib import Path

from automap import lazy
SC = lazy.Module('automap.section_check')   # numpy を読むので点検する時に読む（アプリの起動を速く・2026-11-09・automap/lazy.py）
# 報告の決めの表の読み方は作る側と同じ物（compose が前の版の決めを引き継ぐ時にも読む）
from automap.kime import parse_report as parse_kime, partial_of  # noqa: F401  （parse_kime・partial_of はテストも使う）

VER_RE = re.compile(r'^[0-9A-Za-z_-]{1,64}$')


def _filters(lib, song=None):
    """曲ごとのライブラリの設定 → (曲の選び方の絞り込み, 曲の設定か, 知らせ, 説明の絞り込み)。型の頻度・難しさは並びの数に関係しないので
    落とす（同じ曲の選び方は1回だけ数える）。時期が自動なら曲（song）の時期に置き換える（app/library.auto_view・曲が分からなければ
    年を絞らない）。説明の絞り込みは自動のまま＋その曲の時期（auto_years）。設定が無い・読めない時は新しい曲の既定（ランク譜面。前は
    手元の譜面で数えていた＝「今の型」と一緒に除いた）"""
    from automap import library_use
    note = ''
    try:
        f = library_use.normalize(lib)
    except Exception as e:   # noqa: BLE001  （設定が読めない＝新しい曲の既定で数える）
        note = f'ライブラリの設定が読めないので新しい曲の既定で数えた（{e}）'
        f, lib = library_use.normalize(None), None
    own = bool(lib)
    shown = f
    if f.get('years') == 'auto':
        import library as AL   # noqa: E402  （app/ の中・曲ごとの時期）
        f, _, shown = AL.auto_view(f, song)
    f = dict(f)
    for k in ('freq', 'hard', 'once', 'once_min', 'once_limit'):
        f.pop(k, None)
    f.setdefault('diffs', ['Expert', 'ExpertPlus'])
    shown = dict(shown or f)
    for k in ('freq', 'hard', 'once', 'once_min', 'once_limit'):
        shown.pop(k, None)
    shown.setdefault('diffs', ['Expert', 'ExpertPlus'])
    return f, own, note, shown


def _label(f, own):
    try:
        from automap import library_use
        s = library_use.label(f, short=True)
    except Exception:   # noqa: BLE001
        s = '・'.join(f.get('sources') or [])
    return s if own else s + '（曲の設定なし＝新しい曲の既定）'


def compute(ctx, file, notes=None, library=..., wait=6.0):
    t0 = time.time()
    p = ctx.out_file(file)
    d = _song(ctx, p)
    if notes is None:
        notes = ctx.chart(ctx.base_of(p))['notes']
    if library is ...:
        library = (ctx.load_work(p) or {}).get('library')
    f, own, note, shown = _filters(library, ctx.song_of(p))
    idx, state, err = SC.index_for(f, wait=float(wait))
    bpm, lead = float(d['bpm']), float(d['lead'])
    end = (float(d['dur']) + lead) * bpm / 60
    secs = SC.sections_of(d['marks'], end)
    blocks = [(b[5], b[6], b[3]) for b in d.get('blocks') or []]
    ns = [(n[5], n[3], n[1], n[2], n[4]) for n in notes if len(n) >= 6]
    res = SC.check(ns, secs, bpm, blocks, idx)
    sec = lambda b: round(b * 60 / bpm - lead, 3)
    for s in res:
        s['t0'], s['t1'] = sec(s['b0']), sec(s['b1'])
    lib = {'state': state, 'filters': f, 'label': _label(shown, own), 'own': own, 'note': note, 'error': err,
           'auto_years': shown.get('auto_years')}
    if idx is not None:
        lib.update(songs=idx.songs, built_at=idx.built_at, took=idx.took, ref=idx.ref, min_songs=SC.MIN_SONGS)
    return {'file': p.name, 'sections': res, 'library': lib, 'notes': len(ns),
            'marks': {'same_low': SC.SAME_LOW, 'prev_high': SC.PREV_HIGH, 'min_win': SC.MIN_WIN},
            'took': round(time.time() - t0, 3)}


def _song(ctx, p):
    """曲のデータ（区間・流れの表・テンポ）。画面が開いている曲は覚えてある物を使う（結果のファイルの更新時刻が変わっても
    区間と流れの表は同じ＝作り直しのたびに解析を読み直さない）。無ければ読む"""
    name = ctx.song_of(p)
    with ctx._DATA_LOCK:
        for d in ctx._DATA.values():
            if d.get('name') == name:
                return d
    return ctx.song_data(p)


# ---- 決めの場所（作り直しの報告の表） ----

def still_there(k, notes):
    """決め k が譜面（[秒, x, y, 色, 向き, 拍]）にまだあるか: その手の拍 b0〜b1 のノーツが型の数だけあり、型どおりの数が
    「置けた」以上（置けた数が無ければ全部）"""
    got = sorted((n[5], n[1], n[2], n[4]) for n in notes if n[3] == k['hand'] and k['b0'] - 1e-3 <= n[5] <= k['b1'] + 1e-3)
    seq = k['seq']
    if not seq or len(got) != len(seq):
        return False
    hit = sum(1 for (_, x, y, d), q in zip(got, seq) if [x, y, d] == list(q))
    return hit >= (k['placed'] if k['placed'] is not None else len(seq))


def merge_kimes(mds, notes=None):
    """報告の並び（見ている版の報告から古い順へ）→ (state, 決め, 箇条書き)。見ている版の報告が区間だけ（「ここから」の後ろだけ）
    作り直した物なら、外の決めは前の版の報告から拾う（全部を作り直した報告に着くまで）。拾った決めは譜面 notes にまだある物だけ
    （from＝どの報告から・見ている版の決めは譜面に無くても残し gone を付ける＝NLM で直した等）"""
    state, kimes, notes_ = parse_kime(mds[0])
    regions = [partial_of(mds[0])]
    out = [dict(k, own=True) for k in kimes]
    for md in mds[1:]:
        if regions[-1] is None:
            break
        st, ks, _ = parse_kime(md)
        for k in ks:
            if any(not (k['b1'] < a - 1e-6 or k['b0'] >= b - 1e-6) for a, b in regions):
                continue
            if notes is None or still_there(k, notes):
                out.append(dict(k, own=False))
                state = 'ok'
        regions.append(partial_of(md))
    if notes is not None:
        for k in out:
            k['gone'] = not still_there(k, notes)
    out.sort(key=lambda k: k['b0'])
    return state, out, notes_


def _read(path):
    try:
        return Path(path).read_text(encoding='utf-8')
    except OSError:
        return None


def chain_of(ctx, q):
    """問い合わせ（file・cand・ver）→ (報告の場所の並び＝見ている版から古い順, 見ている譜面のファイル)。別の案は今の結果のファイル→履歴、
    結果のファイルは履歴の中の同じ中身の版より前、履歴の版はそれより前の版をさかのぼる"""
    p = ctx.out_file(q['file'])
    song = ctx.song_of(p)
    out = Path(ctx.OUT)
    hd = out / '.history' / song
    try:
        items = json.loads((hd / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        items = []
    rep = lambda e: hd / f'{song}.{e["id"]}.report.md'
    if q.get('ver'):
        if not VER_RE.match(q['ver']):
            raise ValueError('版の名前が違う')
        i = next((k for k, e in enumerate(items) if e['id'] == q['ver']), None)
        if i is None:
            raise FileNotFoundError('その版は無い')
        return [rep(e) for e in reversed(items[:i + 1])], hd / f'{song}.{q["ver"]}.nlmf'
    chain, shown = [], None
    if q.get('cand'):
        n = int(q['cand'])
        chain.append(out / '.cand' / song / f'{song}.cand{n}.report.md')
        shown = out / '.cand' / song / f'{song}.cand{n}.nlmf'
    src = ctx.base_of(p)
    chain.append(src.with_name(src.name[:-len('.nlmf')] + '.report.md'))
    if src == p and items:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        i = next((k for k in range(len(items) - 1, -1, -1) if items[k].get('sha') == sha), len(items))
        chain += [rep(e) for e in reversed(items[:i])]
    return chain, shown or src


def kime_marks(ctx, q):
    chain, shown = chain_of(ctx, q)
    first = _read(chain[0])
    if first is None:
        return {'file': chain[0].name, 'state': 'no_report', 'kimes': [], 'notes': []}
    try:
        notes = ctx.chart(shown)['notes']
    except (OSError, ValueError, KeyError):
        notes = None
    mds = [first] + [m for m in (_read(c) for c in chain[1:]) if m is not None]
    state, kimes, bullets = merge_kimes(mds, notes)
    return {'file': chain[0].name, 'state': state, 'kimes': kimes, 'notes': bullets}


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})"""
    def get(q):
        return compute(ctx, q['file'], wait=q.get('wait', 6))

    def post(b):
        return compute(ctx, b['file'], notes=b.get('notes'), library=b['library'] if 'library' in b else ..., wait=b.get('wait', 6))

    return {'/api/check': get, '/api/kime': lambda q: kime_marks(ctx, q)}, {'/api/check': post}
