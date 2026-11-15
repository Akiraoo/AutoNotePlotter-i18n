"""作った譜面の★（BeatLeader の★の近似＝nlm-rating）を測る（docs/ライブラリ仕様.md 4 節）。

.nlmf の難易度（既定 ExpertPlus）を、NLM が書き出すのと同じ中身の Info.dat（v2）と難易度の .dat（v3）にして nlm-rating に渡す
（NLM の editor-app.js の buildDiffJsonFor・buildExportInfo・flatFromSections と同じ決まり）:
- 正はクリップの中身。見えている物（クリップの頭からの拍が 0 以上・長さ未満）だけを絶対拍にする。**ミュートのレーンも入れる**
  （NLM の書き出しはミュートを見ない）。ライトのクリップ（lk='l'）・空のクリップ（kind='null'）は入れない。
- チェーンの頭には、チェーンの情報から colorNote を合成する（NLM はチェーンの頭のノーツを持たない・向き 8 は 0 に）。
- テンポの変化（tempoParts）は bpmEvents に。NJS・オフセットは njsCfg（無ければ NLM の既定＝ExpertPlus 16・Expert 12）。
- 書き出しは Music の終わりで切るが、ここでは切らない（作った譜面は曲の中にしか打たない）。v2 の難易度も v3 の形で渡す。

nlm-rating（protocol 1）は 1 回ごとに起動し、標準入力の JSON → 標準出力の JSON（nlm-rating の README・tools/library_build/fetch.py と同じ）。
場所は環境変数 NLM_RATING_EXE か app/config.local.json の nlm_rating_exe（fetch.rating_exe と同じ）。
BeatLeader の★は 2026-10 に PPv4 へ変わった（Pass・Tech・Acc の計算と★の物差し・曲の長さとノーツの数の割り引き。
https://beatleader.wiki/en/ranking/update4）。2026-11 に PPv4.1（★の低い側が 1 ほど上がった）。nlm-rating の版の上 2 つが本家の版（4.1.0＝PPv4.1）。
今の組は automap/rating_scale.py（nlm-rating・型のデータベース・★から決めた数をそろえる）。

コマンド: python -m automap.rating <.nlmf> [--diff ExpertPlus] [--json]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import config, nlmf

ROOT = Path(__file__).resolve().parent.parent
CONFIG = config.path()
BUNDLED = config.app_root() / 'parts' / 'nlm-rating' / 'nlm-rating.exe'   # 配布物に同梱（MIT・tools/dist/build_embed.py・配布物のふりは同梱物の場所）
DIFF_RANK = {'Easy': 1, 'Normal': 3, 'Hard': 5, 'Expert': 7, 'ExpertPlus': 9}
DIFF_NJS = {'Easy': 10, 'Normal': 10, 'Hard': 10, 'Expert': 12, 'ExpertPlus': 16}   # NLM の _DIFF_NJS（njsCfg が無い時）
NO_EXE = '★を測る部品（nlm-rating）が見つからない（配布物の parts/nlm-rating・「準備と設定」で場所を選ぶ・設定の nlm_rating_exe か 環境変数 NLM_RATING_EXE）'


def rating_exe():
    p = os.environ.get('NLM_RATING_EXE')
    if not p:
        try:
            p = json.loads(CONFIG.read_text(encoding='utf-8')).get('nlm_rating_exe')
        except (OSError, ValueError):
            p = None
    if not p and BUNDLED.is_file():
        p = str(BUNDLED)
    return p if p and Path(p).is_file() else None


_VERSIONS = {}   # (場所, 更新時刻, 大きさ) → nlm-rating の版


def exe_version(exe):
    """nlm-rating の版（`--version`・取れなければ None）。BeatLeader の計算が変わると版が上がる（v0.2.0＝2026-10 の PPv4）
    ＝控えた★は同じ版の物だけを使う。exe を差し替えたら測り直すように、場所・更新時刻・大きさごとに覚える"""
    try:
        st = Path(exe).stat()
    except OSError:
        return None
    k = (str(exe), st.st_mtime_ns, st.st_size)
    if k not in _VERSIONS:
        try:
            r = subprocess.run([exe, '--version'], capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            _VERSIONS[k] = json.loads(r.stdout.decode('utf-8')).get('version')
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            _VERSIONS[k] = None
    return _VERSIONS[k]


# ---- .nlmf → 見えている物 ----

def _item(key, a):
    """クリップの中身の 1 つ（保存形式 version 2 のタプル・v1 のオブジェクト）→ (項目の辞書, 標準外の項目)"""
    fields = nlmf._enc_fields(key)
    if isinstance(a, dict):
        it = {k: a.get(k) for k in fields}
        raw = a.get('raw')
    elif isinstance(a, list):
        it = {k: (a[i] if i < len(a) else None) for i, k in enumerate(fields)}
        raw = a[len(fields) + 1] if len(a) > len(fields) + 1 else None
    else:
        return None, None
    return it, (raw if isinstance(raw, dict) else None)


def visible_items(proj, dkey):
    """その難易度のクリップの見えている物（NLM の flatFromSections と同じ）→ {種類: [{項目…, raw}]}（絶対拍・拍の順）"""
    st = proj['difficulties'][dkey]
    out = {k: [] for k in nlmf.N_KEYS}
    for s in st.get('sections') or []:
        if s.get('lk') == 'l' or s.get('kind') == 'null':
            continue
        off, L = float(s.get('beat') or 0), float(s.get('len') or 4)
        for key in nlmf.N_KEYS:
            fields = nlmf._enc_fields(key)
            for a in (s.get('content') or {}).get(key) or []:
                it, raw = _item(key, a)
                if it is None or it[fields[0]] is None or not (0 <= it[fields[0]] < L):
                    continue
                for i in nlmf.BEAT_IDX[key]:
                    if it[fields[i]] is not None:
                        it[fields[i]] = it[fields[i]] + off
                it['raw'] = raw
                out[key].append(it)
    for k, f in (('notes', 'beat'), ('bombs', 'beat'), ('walls', 'beat'), ('arcs', 'b'), ('chains', 'b')):
        out[k].sort(key=lambda o: o[f])
    return out


def _r3(raw):
    """標準外の項目のうち v3 の物（名前が _ で始まらない）"""
    return {k: v for k, v in (raw or {}).items() if not k.startswith('_')}


def diff_json(items, tempo_parts=()):
    """見えている物 → 難易度の .dat（v3・NLM の buildDiffJsonFor の v3 と同じ形）"""
    n0 = lambda v, d: d if v is None else v
    chain_heads = [{'a': 0, 'b': c['b'], 'x': c['x'], 'y': c['y'], 'c': c['c'], 'd': 0 if c['d'] == 8 else c['d']} for c in items['chains']]
    notes = [{**(_r3(n['raw']) or {'a': 0}), 'b': n['beat'], 'x': n['x'], 'y': n['y'], 'c': n['c'], 'd': n['d']} for n in items['notes']]
    sb = lambda o: o['b']
    return {
        'version': '3.2.0',
        'bpmEvents': [{'b': float(p['beat']), 'm': float(p['bpm'])} for p in tempo_parts or []],
        'rotationEvents': [],
        'colorNotes': sorted(notes + chain_heads, key=sb),
        'bombNotes': sorted(({**_r3(o['raw']), 'b': o['beat'], 'x': o['x'], 'y': o['y']} for o in items['bombs']), key=sb),
        'obstacles': sorted(({**_r3(o['raw']), 'b': o['beat'], 'x': o['x'], 'y': o['y'], 'd': o['dur'], 'w': o['w'], 'h': o['h']}
                             for o in items['walls']), key=sb),
        'sliders': sorted(({**_r3(a['raw']), 'b': a['b'], 'c': a['c'], 'x': a['x'], 'y': a['y'], 'd': a['d'], 'mu': n0(a['mu'], 1),
                            'tb': a['tb'], 'tx': a['tx'], 'ty': a['ty'], 'tc': n0(a['tc'], a['d']), 'tmu': n0(a['tmu'], 1), 'm': n0(a['m'], 0)}
                           for a in items['arcs']), key=sb),
        'burstSliders': sorted(({**_r3(c['raw']), 'b': c['b'], 'c': c['c'], 'x': c['x'], 'y': c['y'], 'd': c['d'], 'tb': c['tb'],
                                 'tx': c['tx'], 'ty': c['ty'], 'sc': n0(c['sc'], 4), 's': n0(c['s'], 1)} for c in items['chains']), key=sb),
        'waypoints': [], 'basicBeatmapEvents': [], 'colorBoostBeatmapEvents': [],
        'lightColorEventBoxGroups': [], 'lightRotationEventBoxGroups': [],
        'basicEventTypesWithKeywords': {'d': []}, 'useNormalEventsAsCompatibleEvents': True,   # NLM の EMPTY_V3 と同じ
    }


def diff_name(proj, dkey):
    """難易度のキー → Beat Saber の難易度の名前（'expertplusstandard.dat' → 'ExpertPlus'）"""
    name = (proj['difficulties'][dkey].get('name') or dkey)
    base = name[:-4] if name.lower().endswith('.dat') else name
    base = base[:-len('Standard')] if base.lower().endswith('standard') else base
    for d in DIFF_RANK:
        if d.lower() == base.lower():
            return d
    raise KeyError(f'Standard の難易度ではない: {name}')


def njs_of(proj, dkey, dn):
    c = (proj.get('njsCfg') or {}).get(dkey) or {}
    return (c['njs'] if c.get('njs') is not None else DIFF_NJS.get(dn, 16)), (c['offset'] if c.get('offset') is not None else 0)


def info_json(proj, dn, njs, offset):
    """Info.dat（v2・NLM の buildExportInfo と同じ形。曲の名前などは★に効かないので入れない）"""
    return {'_version': '2.1.0', '_songName': '', '_songSubName': '', '_songAuthorName': '', '_levelAuthorName': '',
            '_beatsPerMinute': float(proj.get('bpm') or 120), '_songTimeOffset': 0, '_shuffle': 0, '_shufflePeriod': 0,
            '_previewStartTime': 12, '_previewDuration': 10, '_songFilename': 'song.egg', '_coverImageFilename': '',
            '_environmentName': 'DefaultEnvironment', '_allDirectionsEnvironmentName': 'GlassDesertEnvironment',
            '_difficultyBeatmapSets': [{'_beatmapCharacteristicName': 'Standard', '_difficultyBeatmaps': [
                {'_difficulty': dn, '_difficultyRank': DIFF_RANK[dn], '_beatmapFilename': f'{dn}Standard.dat',
                 '_noteJumpMovementSpeed': njs, '_noteJumpStartBeatOffset': offset}]}]}


def request(proj, diff='ExpertPlus', modifiers=None):
    """.nlmf（読んだ中身）→ (nlm-rating への頼み, 中身の数など)"""
    dkey = nlmf.diff_key(proj, diff)
    dn = diff_name(proj, dkey)
    items = visible_items(proj, dkey)
    tp = proj.get('tempoParts') or []
    njs, offset = njs_of(proj, dkey, dn)
    dat = diff_json(items, tp)
    req = {'protocol': 1,
           'files': [{'name': 'Info.dat', 'text': json.dumps(info_json(proj, dn, njs, offset), ensure_ascii=False, separators=(',', ':'))},
                     {'name': f'{dn}Standard.dat', 'text': json.dumps(dat, ensure_ascii=False, separators=(',', ':'))}],
           'targets': [{'characteristic': 'Standard', 'difficulty': dn}]}
    if modifiers:
        req['modifiers'] = list(modifiers)
    tm = nlmf.tempo_of(proj)
    beats = [n['b'] for n in dat['colorNotes']]
    span = tm.sec(max(beats)) - tm.sec(min(beats)) if len(beats) > 1 else 0
    meta = {'diff': dn, 'notes': len(dat['colorNotes']), 'bombs': len(dat['bombNotes']), 'walls': len(dat['obstacles']),
            'arcs': len(dat['sliders']), 'chains': len(dat['burstSliders']), 'njs': njs, 'offset': offset,
            'bpm': float(proj.get('bpm') or 120), 'tempo_parts': len(tp),
            'nps': round(len(beats) / span, 2) if span > 0 else None}   # 1秒のノーツの数＝ノーツの数 ÷ 最初から最後のノーツまでの秒
    return req, meta


def req_key(req, version=None):
    """頼みの中身と nlm-rating の版の指紋（同じ中身・同じ版なら測り直さない）"""
    s = json.dumps(req, sort_keys=True, ensure_ascii=False) + (f'\n{version}' if version else '')
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def run(exe, req, timeout=300):
    """nlm-rating を 1 回動かす → 答え（失敗も {'ok': False, 'error'} で返す）"""
    try:
        r = subprocess.run([exe], input=json.dumps(req, ensure_ascii=False).encode('utf-8'), capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': f'nlm-rating が {timeout} 秒で終わらなかった'}
    except OSError as e:
        return {'ok': False, 'error': f'nlm-rating を起動できなかった: {e}'}
    try:
        return json.loads(r.stdout.decode('utf-8'))
    except ValueError:
        return {'ok': False, 'error': (r.stderr.decode('utf-8', 'replace') or 'no output')[-500:]}


def summarize(ans, meta):
    """nlm-rating の答え → 画面・報告に出す形（★・Pass・Tech・Acc・予測精度。測れなかった難易度は skipped）"""
    out = dict(meta, ok=bool(ans.get('ok')), version=ans.get('version'), elapsed_ms=ans.get('elapsedMs'))
    if not ans.get('ok'):
        out['error'] = ans.get('error') or '測れなかった'
        return out
    res = next((x for x in ans.get('results') or [] if x.get('difficulty') == meta['diff']), None)
    if res is None:
        out.update(ok=False, error='答えにその難易度が無い')
        return out
    out['skipped'] = res.get('skipped')
    rt = res.get('ratings') or {}
    none = rt.get('none') or {}
    for k_out, k_in in (('stars', 'stars'), ('pass', 'pass'), ('tech', 'tech'), ('acc', 'acc'), ('predicted_acc', 'predictedAcc')):
        v = none.get(k_in)
        out[k_out] = round(v, 3) if isinstance(v, (int, float)) else None
    mods = {m: round(v['stars'], 3) for m, v in rt.items() if m != 'none' and isinstance((v or {}).get('stars'), (int, float))}
    if mods:
        out['mods'] = mods
    return out


def measure_proj(proj, diff='ExpertPlus', exe=None, modifiers=None):
    exe = exe or rating_exe()
    req, meta = request(proj, diff, modifiers)
    if not exe:
        return dict(meta, ok=False, unavailable=True, error=NO_EXE)
    t0 = time.time()
    out = summarize(run(exe, req), meta)
    out['took'] = round(time.time() - t0, 2)
    return out


def measure(path, diff='ExpertPlus', exe=None, modifiers=None):
    """.nlmf の場所 → 測った★（summarize の形）"""
    return measure_proj(nlmf.load(path), diff, exe, modifiers)


def text(r):
    """1 行の説明（コマンド・報告用）"""
    if not r.get('ok'):
        return f'★ 測れなかった: {r.get("error")}'
    if r.get('skipped'):
        return f'★ 測れない（{r["skipped"]}・ノーツ {r["notes"]}）'
    f2 = lambda k: '—' if r.get(k) is None else f'{r[k]:.2f}'
    pa = f'・予測精度 {r["predicted_acc"] * 100:.1f}%' if r.get('predicted_acc') is not None else ''
    nps = f'・1秒 {r["nps"]:.1f}' if r.get('nps') else ''
    njs = f'・NJS {r["njs"]:g}' if r.get('njs') is not None else ''
    return f'★ {f2("stars")}（Pass {f2("pass")}・Tech {f2("tech")}・Acc {f2("acc")}{pa}・ノーツ {r.get("notes")}{nps}{njs}・{r.get("diff")}）'


# ---- .dat → .nlmf と同じ形（確かめ用: BeatLeader の★が分かっている譜面を同じ道で測る） ----

def _dat_items(d):
    """難易度の .dat（v2・v3）→ visible_items と同じ形（絶対拍）・テンポの変化"""
    items = {k: [] for k in nlmf.N_KEYS}
    if 'colorNotes' in d or str(d.get('version', '')).startswith('3'):
        chains = d.get('burstSliders') or []
        heads = {(c['b'], c.get('x', 0), c.get('y', 0), c.get('c', 0)) for c in chains}
        for n in d.get('colorNotes') or []:
            if (n.get('b', 0), n.get('x', 0), n.get('y', 0), n.get('c', 0)) in heads:
                continue   # チェーンの頭のノーツ（NLM は持たない・書き出しで合成する）
            items['notes'].append({'beat': n.get('b', 0), 'x': n.get('x', 0), 'y': n.get('y', 0), 'c': n.get('c', 0), 'd': n.get('d', 0),
                                   'raw': {'a': n['a']} if n.get('a') else None})
        for n in d.get('bombNotes') or []:
            items['bombs'].append({'beat': n.get('b', 0), 'x': n.get('x', 0), 'y': n.get('y', 0), 'raw': None})
        for o in d.get('obstacles') or []:
            items['walls'].append({'beat': o.get('b', 0), 'x': o.get('x', 0), 'y': o.get('y', 0), 'dur': o.get('d', 0), 'w': o.get('w', 1),
                                   'h': o.get('h', 5), 'raw': None})
        for a in d.get('sliders') or []:
            items['arcs'].append({k: a.get(k, 0 if k not in ('mu', 'tmu') else 1) for k in nlmf._enc_fields('arcs')} | {'raw': None})
        for c in chains:
            items['chains'].append({k: c.get(k, 0) for k in nlmf._enc_fields('chains')} | {'raw': None})
        tp = [{'beat': e.get('b', 0), 'bpm': e['m']} for e in d.get('bpmEvents') or [] if 'm' in e]
    elif '_notes' in d:
        for n in d.get('_notes') or []:
            t = n.get('_type')
            if t in (0, 1):
                items['notes'].append({'beat': n['_time'], 'x': n['_lineIndex'], 'y': n['_lineLayer'], 'c': t, 'd': n['_cutDirection'], 'raw': None})
            elif t == 3:
                items['bombs'].append({'beat': n['_time'], 'x': n['_lineIndex'], 'y': n['_lineLayer'], 'raw': None})
        for o in d.get('_obstacles') or []:   # _type 0＝立った高さ・1＝しゃがむ高さ（NLM の読み込みと同じ）
            crouch = o.get('_type') == 1
            items['walls'].append({'beat': o['_time'], 'x': o['_lineIndex'], 'y': 2 if crouch else 0, 'dur': o['_duration'],
                                   'w': o['_width'], 'h': 3 if crouch else 5, 'raw': None})
        # テンポの変化は _events の _type 100 だけ（Beat Saber・BeatLeader の読み込みと同じ。_customData の _BPMChanges は
        # エディタ用でゲームも BeatLeader も見ない＝入れると BeatLeader の★と合わなくなった）
        tp = [{'beat': e['_time'], 'bpm': e['_floatValue']} for e in d.get('_events') or [] if e.get('_type') == 100 and '_floatValue' in e]
    else:
        raise ValueError('v2・v3 の .dat だけを読める')
    return items, tp


def proj_from_dat(info, dat, diff='ExpertPlus'):
    """Info.dat と難易度の .dat（読んだ中身）→ 1 つのクリップに全部入れた .nlmf と同じ形（確かめ・テスト用）"""
    items, tp = _dat_items(dat)
    bm = next(b for s in info['_difficultyBeatmapSets'] if s.get('_beatmapCharacteristicName') == 'Standard'
              for b in s['_difficultyBeatmaps'] if b['_difficulty'] == diff)
    content = {}
    for key, arr in items.items():
        fields = nlmf._enc_fields(key)
        rows = []
        for it in arr:
            row = [it.get(f) for f in fields] + [None]
            if it.get('raw'):
                row.append(it['raw'])
            rows.append(row)
        if rows:
            content[key] = rows
    end = max([it[nlmf._enc_fields(k)[0]] for k, arr in items.items() for it in arr] or [0]) + 4
    dkey = f'{diff}Standard.dat'.lower()
    return {'format': 'nlmf', 'version': 2, 'bpm': info['_beatsPerMinute'], 'tempoParts': tp, 'current': f'{diff}Standard.dat',
            'njsCfg': {dkey: {'njs': bm.get('_noteJumpMovementSpeed'), 'offset': bm.get('_noteJumpStartBeatOffset', 0)}},
            'difficulties': {dkey: {'name': f'{diff}Standard.dat', 'v3': True,
                                    'sections': [{'id': 'all', 'beat': 0, 'len': end, 'track': 0, 'content': content}]}}}


def main(argv=None):
    ap = argparse.ArgumentParser(description='作った譜面の★（BeatLeader の★の近似・nlm-rating）を測る')
    ap.add_argument('nlmf', nargs='+')
    ap.add_argument('--diff', default='ExpertPlus')
    ap.add_argument('--mods', action='store_true', help='速度違い（SS・FS・SFS）の★も')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    exe = rating_exe()
    if not exe:
        print(NO_EXE, file=sys.stderr)
        return 2
    rc = 0
    for p in a.nlmf:
        r = measure(p, a.diff, exe, ['none', 'SS', 'FS', 'SFS'] if a.mods else None)
        rc |= 0 if r.get('ok') else 1
        print(json.dumps(r, ensure_ascii=False) if a.json else f'{Path(p).name}: {text(r)}（{r.get("took", 0):.1f} 秒）')
    return rc


if __name__ == '__main__':
    sys.exit(main())
