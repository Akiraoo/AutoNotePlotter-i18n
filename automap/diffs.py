"""難易度の名前と並び・難易度を足す・移す・派生の報告の場所（難易度の展開・docs/アプリ仕様.md 17 節）。
作る側（compose --diff・--derive-from）とアプリ（app/server.py・app/expand.py）が同じ決まりを使う。

- 名前は Beat Saber の難易度の名前（'Easy'〜'ExpertPlus'）。.nlmf の difficulties のキーは '<名前>Standard.dat' の小文字・
  中の name は '<名前>Standard.dat'。
- NLM の書き出す難易度の印は graph.out.diffs と infoGraph の set の節の data.diffs（{名前: 1|0}・NLM の editor-app.js は set の節から
  graph.out.diffs を作り直す＝両方そろえる）。空・項目が無い＝書き出さない（NLM の新しいプロジェクトは空）。アプリがノーツを書いた基準は
  まだ誰も決めていなければ付ける（mark_default）・NLM で外した 0 は触らない。NJS は njsCfg（キーは difficulties と同じ小文字・無ければ NLM の既定 _DIFF_NJS）。
- 基準＝アプリが意思入れで作り直す難易度（作業ファイルの diff・既定 ExpertPlus）。派生＝基準から「難易度を展開」で作った上・下の難易度。
  派生の報告は <結果>.<名前>.report.md（基準の報告 <結果>.report.md は決めの引き継ぎ等が読むので上書きしない）。
"""
from pathlib import Path

ORDER = ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus']
TEXT = {'Easy': 'Easy', 'Normal': 'Normal', 'Hard': 'Hard', 'Expert': 'Expert', 'ExpertPlus': 'Expert+'}
NJS = {'Easy': 10, 'Normal': 10, 'Hard': 10, 'Expert': 12, 'ExpertPlus': 16}   # NLM の _DIFF_NJS（njsCfg が無い時）
# 派生の量の既定の刻み（基準の1秒のノーツに対する割合を1段下ごとに −STEP_PCT%・1段上ごとに +STEP_PCT%・足し算）。2026-11-02 利用者
# 「今の既定は難易度が飛びすぎていて期待している範囲じゃない。一旦デフォルトを 10% 刻みに」（前は手元の譜面 930 曲の中央値
# 6.3→4.9→3.9→3.0→2.2 の比＝1段 0.78 倍の掛け算・docs/方針.md 4 章）。アプリは app/config.local.json の expand_step_pct で変えられる
STEP_PCT = 10
RATIO_RANGE = (0.2, 2.5)   # 量の割合の受け付ける範囲（既定がはみ出す時は端に・アプリの展開の窓も同じ）
DEFAULT = 'ExpertPlus'


def name_of(s):
    """'ExpertPlus'・'Expert+'・'expertplusstandard.dat'・'ExpertPlusStandard.dat' → 'ExpertPlus'（知らない名前は ValueError）"""
    t = str(s or '').strip().lower().replace('+', 'plus')
    if t.endswith('.dat'):
        t = t[:-4]
    if t.endswith('standard'):
        t = t[:-len('standard')]
    for d in ORDER:
        if d.lower() == t:
            return d
    raise ValueError(f'難易度の名前が違う: {s}（{"・".join(ORDER)}）')


def dat(d):
    return f'{name_of(d)}Standard.dat'


def key(d):
    return dat(d).lower()


def steps(base, d):
    """基準から何段上か（下は負）"""
    return ORDER.index(name_of(d)) - ORDER.index(name_of(base))


def ratio(base, d, step_pct=None):
    """基準の1秒のノーツに対する既定の割合: 1段下ごとに −step_pct%・1段上ごとに +step_pct%（足し算・既定 STEP_PCT）。
    RATIO_RANGE からはみ出す時は端に"""
    s = STEP_PCT if step_pct is None else float(step_pct)
    return round(min(RATIO_RANGE[1], max(RATIO_RANGE[0], 1 + s / 100 * steps(base, d))), 4)


def notes_in(st):
    """難易度のクリップの中身のノーツの数（見えている物・ライトは数えない）"""
    n = 0
    for s in st.get('sections') or []:
        if s.get('lk') == 'l' or s.get('kind') == 'null':
            continue
        L = s.get('len') or 4
        n += sum(1 for a in (s.get('content') or {}).get('notes') or [] if isinstance(a, list) and a[0] is not None and 0 <= a[0] < L)
    return n


def listing(proj):
    """ある難易度 → [{diff, key, notes, export（書き出す印）}]（ORDER の順）"""
    ex = export_marks(proj)
    out = []
    for d in ORDER:
        st = (proj.get('difficulties') or {}).get(key(d))
        if st is not None:
            out.append({'diff': d, 'key': key(d), 'notes': notes_in(st), 'export': bool(ex.get(d))})
    return out


def _set_nodes(proj):
    return [v for v in ((proj.get('infoGraph') or {}).get('nodes') or {}).values() if v.get('t') == 'set']


def export_marks(proj):
    """書き出す難易度の印 {名前: 1|0}（graph.out.diffs）"""
    return dict((((proj.get('graph') or {}).get('out') or {}).get('diffs')) or {})


def set_export(proj, d, on=True):
    """書き出す難易度の印を付ける・外す（graph.out.diffs と infoGraph の set の節の両方）"""
    d = name_of(d)
    g = proj.setdefault('graph', {}).setdefault('out', {})
    g.setdefault('diffs', {})[d] = 1 if on else 0
    for v in _set_nodes(proj):
        v.setdefault('data', {}).setdefault('diffs', {})[d] = 1 if on else 0


def mark_of(proj, d):
    """書き出す印 1|0、まだ誰も決めていなければ None（graph.out.diffs・無ければ set の節。NLM は開く時に set の節から graph.out.diffs を作り直す）"""
    d = name_of(d)
    ex = export_marks(proj)
    if d in ex:
        return ex[d]
    for v in _set_nodes(proj):
        m = (v.get('data') or {}).get('diffs') or {}
        if d in m:
            return m[d]
    return None


def export_decided(proj, d):
    """書き出す印を誰かが決めたか（付ける・外すのどちらかがある）。無い＝まだ誰も決めていない"""
    return mark_of(proj, d) is not None


def _unset_export(proj, d):
    """書き出す印を「まだ誰も決めていない」に戻す（両方から消す）"""
    ((proj.get('graph') or {}).get('out') or {}).get('diffs', {}).pop(d, None)
    for v in _set_nodes(proj):
        ((v.get('data') or {}).get('diffs') or {}).pop(d, None)


def mark_default(proj, d):
    """アプリがノーツを書いた難易度（作り直した基準・展開で置き直した基準）の書き出す印: まだ誰も決めていなければ付ける → 付けたか。
    NLM で外した印（0）は触らない。ノーツの無い難易度には付けない（2026-11-03 利用者「NLM で開くとハードが書き出し対象になっていない」＝
    元のプロジェクトの印は NLM の新しいプロジェクトと同じく空（どれも書き出さない）で、基準の作り直しは印に触らず、展開は派生にだけ付けていた）"""
    d = name_of(d)
    st = (proj.get('difficulties') or {}).get(key(d))
    if st is None or not notes_in(st) or export_decided(proj, d):
        return False
    set_export(proj, d, True)
    return True


def _empty(d):
    from .new_project import _empty_diff   # NLM の EMPTY_V3・encDiff の形（元のプロジェクトを作る時と同じ）
    return _empty_diff(dat(d))


def ensure(proj, d, export=True):
    """難易度が無ければ空の難易度を足す（書き出す印も付ける）→ difficulties のキー。あれば何もしない（印は export の時だけ付ける）"""
    k = key(d)
    if k not in proj['difficulties']:
        proj['difficulties'][k] = _empty(d)
    if export:
        set_export(proj, d, True)
    return k


def move(proj, src, dst, swap=False):
    """難易度 src の中身（クリップ・ノーツ・ライト・難易度ごとの設定）を dst へ移す（名前を付け替える）。dst にノーツかライトがあれば
    ValueError（swap＝入れ替える）。書き出す印・NJS（njsCfg）・開いている難易度（current）も一緒に付け替える"""
    src, dst = name_of(src), name_of(dst)
    if src == dst:
        return
    ds = proj['difficulties']
    ks, kd = key(src), key(dst)
    if ks not in ds:
        raise KeyError(f'難易度が無い: {src}')
    old = ds.get(kd)
    if old is not None and not swap and (notes_in(old) or old.get('lightEvents') or any(s.get('lk') == 'l' for s in old.get('sections') or [])):
        raise ValueError(f'{TEXT[dst]} にはもう譜面がある（入れ替えるなら swap）')
    a = ds.pop(ks)
    a['name'] = dat(dst)
    if old is not None and swap:
        old['name'] = dat(src)
        ds[ks] = old
    ds[kd] = a
    nj = proj.get('njsCfg')
    if isinstance(nj, dict):
        cs, cd = nj.pop(ks, None), nj.pop(kd, None)
        if cs is not None:
            nj[kd] = cs
        if cd is not None and swap:
            nj[ks] = cd
    # 書き出す印も付け替える。まだ誰も決めていない印（None）は決めていないまま移す（前は「外す」と書いていた＝印の無い Expert+ の基準を
    # Hard へ置き直した Joy to the love で、Hard が書き出されなかった・2026-11-03。決めていなければ mark_default が付ける）
    es, ed = mark_of(proj, src), mark_of(proj, dst)

    def put(x, v):
        if v is None:
            _unset_export(proj, x)
        else:
            set_export(proj, x, bool(v))
    if swap:
        put(dst, es)
        put(src, ed)
    else:   # dst は空だった＝src の印（dst に付けてあれば付ける）・src は空になる＝決めてあれば外す
        put(dst, 1 if (es or ed) else (0 if 0 in (es, ed) else None))
        put(src, 0 if es is not None else None)
    cur = (proj.get('current') or '').lower()
    if cur == ks:
        proj['current'] = dat(dst)
    elif cur == kd and swap:
        proj['current'] = dat(src)


def report_path(out, d=None):
    """作り直しの報告の場所: 基準（d＝None）は <結果>.report.md・派生は <結果>.<名前>.report.md"""
    out = Path(out)
    stem = out.name[:-len('.nlmf')] if out.name.endswith('.nlmf') else out.stem
    return out.with_name(f'{stem}.report.md' if d is None else f'{stem}.{name_of(d)}.report.md')
