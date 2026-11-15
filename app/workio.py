"""付けた指示の読み込み（控えた作業ファイル・履歴の版・前の形式の意思入れの表から選んで足す）と、全部外す。
server.py の connect() が routes(ctx) を呼んでつなぐ（ctx＝server モジュール。OUT 等は呼ばれた時に ctx から読む＝--out で変えられる）。

読み込める物（GET /api/workio/sources?file=<結果のファイル>）:
- 控え: <OUT>/saved/**/<曲>.*.automap.json（作業ファイルの写し）と <OUT>/saved/**/<曲>.intent.json（前の形式の表）
- 作業ファイル: <OUT>/<曲>.*.automap.json（今の結果のファイルの作業ファイルは除く）
- 前の形式: <OUT>/<曲>.intent.json（聞き比べのページで作った表。server.default_work と同じ変換）
- 履歴: <OUT>/.history/<曲>/<曲>.<版>.automap.json（app/versions.py の版。同じ中身の版は新しい1つだけ）
中身（GET /api/workio/source?file=&src=<OUT からの場所>）は作業ファイルの形（ranges・line・auto_rest・library・amount）にして返す。
区間・量のラインの点は拍で持っているので、読み込む物の目盛り（BPM・無音追加・テンポパート）が今の曲と違う時だけ、秒で合わせ直す
（作業ファイルは隣の .nlmf、前の形式は表の bpm・lead_ms から。分からない時はそのまま）。
足す・置き換える・全部外すは画面（js/workio.js）が作業ファイルに入れる（作業ファイルの正は画面＝commit で Ctrl+Z で戻せる）。
OUT の外・決まった場所の外・別の曲のファイルは読まない。
"""
import hashlib
import json
import time
from pathlib import Path

from automap import nlmf
from names import rel_parts  # noqa: E402  （app/names.py）

C = None                 # server モジュール（routes で受け取る）
SAVED = 'saved'          # 控えの置き場（<OUT>/saved/ の下・何段でも）
KIND_ORDER = {'saved': 0, 'out': 1, 'legacy': 2, 'history': 3}
KIND_TEXT = {'saved': '控え', 'out': '作業ファイル', 'legacy': '前の形式の表', 'history': '履歴の版'}
EMPTY_REST = {'on': False, 'b': None}


def _song(p):
    return p.name.split('.')[0]


def _out():
    return Path(C.OUT).resolve()


def _rkey(r):
    """全く同じ区間・指示（store.rangeKey・server.default_work と同じ見分け方）"""
    return (float(r['b0']), float(r['b1']), json.dumps(r.get('set') or {}, sort_keys=True, ensure_ascii=False))


def _ranges(rs):
    """区間の並び → 拍の数・区間の向きが正しい物だけ・全く同じ物は1つに"""
    out, seen = [], set()
    for r in rs or []:
        try:
            b0, b1 = float(r['b0']), float(r['b1'])
        except (KeyError, TypeError, ValueError):
            continue
        if not b1 > b0:
            continue
        q = {'b0': b0, 'b1': b1, 'set': r.get('set') or {}}
        k = _rkey(q)
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out


def legacy_work(d):
    """前の形式の意思入れの表（聞き比べのページの <曲>.intent.json）→ 作業ファイルの形（server.default_work と同じ変換:
    量のラインは点の間を直線でつなぐ形 → なめらかにつなぐキーフレーム・10% きざみ）"""
    return {'ranges': _ranges(d.get('ranges')),
            'line': [{'b': p['b'], 'k': round(round(p['k'] * 10) / 10, 1), 'smooth': True} for p in d.get('line') or []],
            'auto_rest': d.get('auto_rest') or dict(EMPTY_REST)}


def app_work(d):
    """作業ファイル（.automap.json）→ 読み込みに使う項目だけ"""
    return {'ranges': _ranges(d.get('ranges')),
            'line': [{'b': k['b'], 'k': k['k'], 'smooth': bool(k.get('smooth'))} for k in d.get('line') or []],
            'auto_rest': d.get('auto_rest') or dict(EMPTY_REST),
            'library': d.get('library') or None,
            'amount': d.get('amount') if (d.get('amount') or {}).get('mode') not in (None, 'auto') else None}


# ---- 目盛り（BPM・無音追加・テンポパート） ----

def grid_of_proj(proj):
    """結果のファイルの目盛り（server.song_data と同じ: 無音追加＝graph.song.offset が負の時の −offset 秒）"""
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    return {'bpm': float(proj['bpm']), 'lead': -off if off < 0 else 0.0,
            'parts': [{'beat': float(q['beat']), 'bpm': float(q['bpm'])} for q in proj.get('tempoParts') or []]}


def grid_of_legacy(d):
    if d.get('bpm') is None or d.get('lead_ms') is None:
        return None
    return {'bpm': float(d['bpm']), 'lead': float(d['lead_ms']) / 1000, 'parts': []}


def same_grid(a, b):
    if not a or not b:
        return True   # 分からない時はそのまま使う
    if abs(a['bpm'] - b['bpm']) > 1e-6 or abs(a['lead'] - b['lead']) > 5e-4 or len(a['parts']) != len(b['parts']):
        return False
    return all(abs(x['beat'] - y['beat']) < 1e-6 and abs(x['bpm'] - y['bpm']) < 1e-6 for x, y in zip(a['parts'], b['parts']))


def beat_at(tm, t):
    """曲頭（拍 0）からの秒 → 拍（nlmf.TempoMap.sec の逆）"""
    bb, bpm, tt = 0.0, tm.bpm, 0.0
    for q in tm.parts:
        t_next = tt + (q['beat'] - bb) * 60 / bpm
        if t_next >= t:
            break
        tt, bb, bpm = t_next, q['beat'], q['bpm']
    return bb + (t - tt) * bpm / 60


def regrid_beat(b, src, cur):
    """読み込む物の拍 → 今の曲の拍（元の音源の同じ秒）。1/4 拍の近く（0.06 拍以内）なら 1/4 拍にそろえる"""
    t = nlmf.TempoMap(src['bpm'], src['parts']).sec(b) - src['lead']
    x = beat_at(nlmf.TempoMap(cur['bpm'], cur['parts']), t + cur['lead'])
    q = round(x * 4) / 4
    return q if abs(q - x) < 0.06 else round(x, 3)


def regrid(w, src, cur):
    """作業ファイルの形の拍を全部、今の曲の目盛りへ"""
    f = lambda b: regrid_beat(float(b), src, cur)
    w = dict(w)
    w['ranges'] = [dict(r, b0=f(r['b0']), b1=f(r['b1'])) for r in w['ranges']]
    w['line'] = [dict(k, b=f(k['b'])) for k in w['line']]
    ar = w.get('auto_rest') or {}
    if ar.get('b') is not None:
        w['auto_rest'] = dict(ar, b=f(ar['b']))
    return w


# ---- 読み込める物 ----

def _is_legacy(f, song):
    return f.name == f'{song}.intent.json'


def _allowed(f, p):
    """読んでよいファイルか（OUT の中・決まった場所・この曲・作業ファイルか前の形式の表）→ 種類（'saved'・'out'・'legacy'・'history'）か None"""
    out, song = _out(), _song(p)
    try:
        f = f.resolve()
        rel = f.relative_to(out)
    except (OSError, ValueError):
        return None
    if f.name.split('.')[0] != song or not f.is_file():
        return None
    auto = f.name.endswith('.automap.json')
    if not (auto or _is_legacy(f, song)):
        return None
    parts = rel.parts
    if parts[0] == SAVED and len(parts) >= 2:
        return 'saved'
    if len(parts) == 1:
        if auto and f == Path(C.work_path(p)).resolve():
            return None   # 今の作業ファイル
        return 'out' if auto else 'legacy'
    if auto and len(parts) == 3 and parts[0] == '.history' and parts[1] == song:
        return 'history'
    return None


def _read_json(f):
    return json.loads(Path(f).read_text(encoding='utf-8'))


def _work_of(f, song):
    d = _read_json(f)
    return d, (legacy_work(d) if _is_legacy(f, song) else app_work(d))


def _digest(w):
    body = {k: w.get(k) for k in ('ranges', 'line', 'auto_rest', 'library', 'amount')}
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def _hist_index(p):
    try:
        return {e['id']: e for e in _read_json(_out() / '.history' / _song(p) / 'index.json')}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _entry(f, kind, p, d, w):
    out, song = _out(), _song(p)
    rel = f.resolve().relative_to(out)
    st = f.stat()
    at = d.get('saved') or d.get('maker_at') or d.get('made') or time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(st.st_mtime))
    e = {'src': rel.as_posix(), 'kind': kind, 'kind_text': KIND_TEXT[kind], 'name': f.name,
         'where': '/'.join(rel.parts[:-1]) or '.', 'at': str(at).replace('T', ' ')[:19], 'ts': st.st_mtime,
         'n': len(w['ranges']), 'line': len(w['line']),
         'groups': sorted({(r['set'].get('motif') or {}).get('group') for r in w['ranges']
                           if (r['set'].get('motif') or {}).get('group') and not r['set'].get('rest')}),
         'auto_rest': bool((w.get('auto_rest') or {}).get('on')), 'library': bool(w.get('library')),
         'amount': bool(w.get('amount')), 'legacy': _is_legacy(f, song)}
    if kind == 'history':
        vid = f.name[len(song) + 1:-len('.automap.json')]
        h = _hist_index(p).get(vid) or {}
        e['title'] = h.get('title') or ''
        e['at'] = h.get('at') or e['at']
        e['ts'] = h.get('ts') or e['ts']
        e['vid'] = vid
    return e


def sources(p):
    """その曲の読み込める物の一覧（控え → 作業ファイル・前の形式 → 履歴。それぞれ新しい順。履歴は同じ中身の版を新しい1つに）"""
    out, song = _out(), _song(p)
    files = []
    if (out / SAVED).is_dir():
        files += [f for f in (out / SAVED).rglob('*.json') if f.name.split('.')[0] == song]
    files += [f for f in out.glob('*.json') if f.name.split('.')[0] == song]
    hd = out / '.history' / song
    if hd.is_dir():
        files += [f for f in hd.glob('*.automap.json')]
    got, hist = [], {}
    for f in files:
        kind = _allowed(f, p)
        if not kind:
            continue
        try:
            d, w = _work_of(f, song)
            e = _entry(f, kind, p, d, w)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if kind == 'history':
            hist.setdefault(_digest(w), []).append(e)
        else:
            got.append(e)
    for es in hist.values():   # 同じ中身の版は新しい1つだけ（数を same に）
        e = max(es, key=lambda x: x['ts'])
        e['same'] = len(es)
        got.append(e)
    got.sort(key=lambda e: (KIND_ORDER[e['kind']], -e['ts']))
    return {'song': song, 'file': p.name, 'sources': got, 'cur_work': Path(C.work_path(p)).name}


def _src_grid(f, song, d):
    if _is_legacy(f, song):
        return grid_of_legacy(d)
    if f.name.endswith('.automap.json'):
        nf = f.with_name(f.name[:-len('.automap.json')] + '.nlmf')
        if nf.exists():
            try:
                return grid_of_proj(nlmf.load(nf))
            except (OSError, ValueError, KeyError, TypeError):
                return None
    return None


def read_source(p, src):
    """読み込む物の中身（作業ファイルの形・目盛りが違えば今の曲の拍に合わせ直した物）"""
    song = _song(p)
    parts = rel_parts(src)   # 確かめてから場所にする（UNC・絶対の場所・.. は resolve の前に断る＝app/names.py）
    f = _out().joinpath(*parts) if parts else None
    kind = _allowed(f, p) if f is not None else None
    if not kind:
        raise ValueError('読み込めない場所（この曲の控え・作業ファイル・履歴・前の形式の表だけ）')
    d, w = _work_of(f, song)
    g_src = _src_grid(f, song, d)
    try:
        g_cur = grid_of_proj(nlmf.load(C.base_of(p)))
    except FileNotFoundError:
        g_cur = None
    moved = not same_grid(g_src, g_cur)
    if moved:
        w = regrid(w, g_src, g_cur)
    note = ''
    if moved:
        note = (f'目盛りが今の曲と違う（BPM {g_src["bpm"]:g}・無音追加 {g_src["lead"] * 1000:.0f}ms → BPM {g_cur["bpm"]:g}・'
                f'無音追加 {g_cur["lead"] * 1000:.0f}ms）ので、区間と量のラインの点を元の音源の同じ秒に合わせ直した（小節の頭からずれる所がある）')
    elif g_src is None:
        note = '読み込む物の目盛りが分からない（隣に .nlmf が無い）ので、拍のまま入れる'
    return dict(w, src=f.resolve().relative_to(_out()).as_posix(), kind=kind, kind_text=KIND_TEXT[kind], name=f.name,
                legacy=_is_legacy(f, song), grid_src=g_src, grid_cur=g_cur, regrid=moved, grid_note=note)


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})"""
    global C
    C = ctx
    f = lambda q: C.out_file(q['file'])
    get = {
        '/api/workio/sources': lambda q: sources(f(q)),
        '/api/workio/source': lambda q: read_source(f(q), q['src']),
    }
    return get, {}
