"""生データ（取ってきた譜面・手元の譜面・BeatSaver と BeatLeader の情報）から、探すためのデータベース（SQLite）を作る
（docs/ライブラリ仕様.md 3 節・7 節）。軸や型の決め方を変えたら作り直す（版は automap/library_db.py の SCHEMA_VERSION・EXTRACT_VERSION）。

使い方: python -I tools/library_build/build_db.py [--root <生データの置き場>] [--db <library.sqlite>] [--local <CustomLevels>] [--jobs 8]
       python -I tools/library_build/build_db.py --list-own   # 作らずに、自分で書き出した手元の譜面の一覧（今のデータベースとの違い）
- 手元の譜面は先に登録し直す（fetch.py local と同じ・中身が変わったフォルダだけ hash を計算し直す。ネットには行かない）。
- 型の決め方は tools/library_themes.py の関数（hand_swings・runs・canon・shape）、振りの読み方は tools/library_stats.py の
  load・find・parse_diff・analyze をそのまま使う（書き直さない＝tools/library_themes.py と同じ数え方）。
- 作り終わってから置き換える（作っている間も前のデータベースは読める）。
- 自分（アプリ・NLM）で書き出した手元の譜面（maps.own・型のライブラリは既定で除く）の見分け（2026-11-09・own_reasons）:
  mark＝Info.dat の ANP の印（automap/bs_export.put_mark）・playlist＝プレイリストの ANP の行（customData.anpFolder・hash）・
  work＝作業の場所（out/）の .nlmf の書き出すフォルダ名・export＝アプリの書き出しの記録（out/.export/）・name＝設定の library_own の型。
  library_own の「!」で始まる型に合う手元の譜面（利用者が手で打った譜面）は、どれが当たっても除かない。
"""
import argparse
import fnmatch
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import time
import zlib
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import library_stats as LS  # noqa: E402
import library_themes as LT  # noqa: E402
from automap import bs_export as BX  # noqa: E402  （Info.dat の ANP の印＝anp_mark）
from automap import config as AC  # noqa: E402
from automap import library_db as DB  # noqa: E402
from automap import playlist as PL  # noqa: E402

ONCE_LEN = 4        # 1回だけの並びの長さ（片手の振りの数）
RAW_ORD = 10 ** 7   # 取った譜面の並びは手元の後ろ
OWN_KINDS = ('mark', 'playlist', 'work', 'export', 'name')   # 自分で書き出した譜面の見分け（own_reasons の並び）
FOLDER_NAME = re.compile(rb'"folderName"\s*:\s*"((?:[^"\\]|\\.)*)"')   # .nlmf の書き出すフォルダ名（graph.out・infoGraph の outs）

SCHEMA = """
CREATE TABLE info (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE maps (
  id INTEGER PRIMARY KEY, place TEXT, folder TEXT, ord INTEGER, hash TEXT, key TEXT,
  ranked INTEGER, on_beatsaver INTEGER, song TEXT, sub TEXT, artist TEXT, level_author TEXT, mappers TEXT,
  uploaded TEXT, year INTEGER, bpm REAL, duration REAL, upvotes INTEGER, downvotes INTEGER, score REAL, curated INTEGER,
  v4 INTEGER, err TEXT, own INTEGER);
CREATE TABLE diffs (
  id INTEGER PRIMARY KEY, map_id INTEGER, pos INTEGER, characteristic TEXT, difficulty TEXT, filename TEXT, missing INTEGER,
  mods INTEGER, version TEXT, bpm_change INTEGER, notes INTEGER, bombs INTEGER, arcs INTEGER, chains INTEGER, njs REAL, nps REAL,
  bl_ranked INTEGER, stars REAL, star_approx INTEGER, pass REAL, tech REAL, acc REAL, ranked_time INTEGER,
  err TEXT, xerr TEXT, stats TEXT);
CREATE TABLE swings (diff_id INTEGER, hand INTEGER, data BLOB, PRIMARY KEY (diff_id, hand));
CREATE TABLE patterns (
  id INTEGER PRIMARY KEY, kind TEXT, key TEXT, n INTEGER, cells INTEGER, move REAL, row REAL, diag REAL, width INTEGER,
  shape_a TEXT, shape_b TEXT, hard_shape REAL, hard_parts TEXT, UNIQUE (kind, key));
CREATE TABLE occurrences (
  pattern_id INTEGER, diff_id INTEGER, runs INTEGER, reps INTEGER, gaps TEXT, first INTEGER, spans TEXT);
CREATE TABLE once_occ (pattern_id INTEGER, diff_id INTEGER, n INTEGER, gap REAL, beats TEXT);
"""
INDEXES = """
CREATE INDEX occ_diff ON occurrences (diff_id);
CREATE INDEX occ_pat ON occurrences (pattern_id);
CREATE INDEX once_diff ON once_occ (diff_id);
CREATE INDEX diffs_map ON diffs (map_id);
"""


def _num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _key(seq):
    return json.dumps([[_num(v) for v in s] for s in seq], separators=(',', ':'))


def once_windows(sw, c, rs):
    """1回だけの並び: くり返し（runs）の外で、点ノーツを含まず振り下ろし・振り上げが交互の ONCE_LEN 振り（右手の形に）"""
    beats = [b for b, _ in sw]
    cov = [False] * len(sw)
    for _, b0, b1, _, _ in rs:
        for k, b in enumerate(beats):
            if b0 <= b <= b1:
                cov[k] = True
    out = []
    for k in range(len(sw) - ONCE_LEN + 1):
        if any(cov[k:k + ONCE_LEN]):
            continue
        win = [s for _, s in sw[k:k + ONCE_LEN]]
        ps = [LT.parity(c, s[2]) for s in win]
        if None in ps or any(ps[i] == ps[i + 1] for i in range(ONCE_LEN - 1)):
            continue
        g = statistics.median(beats[k + i + 1] - beats[k + i] for i in range(ONCE_LEN - 1))
        out.append((tuple(LT.to_r(c, s) for s in win), beats[k], g))
    return out


def _agg(items):
    """[(鍵, 始まり, 終わり, 回数, 振りの間)] → {鍵: [回, 回数の計, [間], 最初の番号, [[始まり, 終わり]]]}（並びの順を保つ）"""
    out = {}
    for i, (k, b0, b1, reps, g) in enumerate(items):
        e = out.get(k)
        if e is None:
            e = out[k] = [0, 0, [], i, []]
        e[0] += 1
        e[1] += reps
        e[2].append(g)
        e[4].append([round(b0, 4), round(b1, 4)])
    return out


def parse_map(folder):
    """1つの譜面のフォルダ → 曲の情報と、Standard の難易度ごとの振り・型・打ち方の数字。
    失敗の扱いは library_themes.song と同じ（Expert／Expert+ で失敗すると曲ごと落ちる＝err。落ちない所の失敗は xerr）"""
    r = {'err': None, 'v4': 0, 'bpm': None, 'info': {}, 'diffs': [], 'anp': None}
    try:
        ip = LS.find(folder, 'Info.dat')
        if not ip:
            r['err'] = 'Info.dat が無い'
            return r
        info = LS.load(ip)
        r['anp'] = BX.anp_mark(info)   # ANP で書き出した印（v2・v4 の形）＝自分の物
        if '_difficultyBeatmapSets' not in info:
            r['v4'] = 1
            return r
        r['info'] = {k: info.get('_' + k) for k in ('songName', 'songSubName', 'songAuthorName', 'levelAuthorName')}
        bpm = float(info.get('_beatsPerMinute') or 0)
        r['bpm'] = bpm
        if bpm <= 0:
            r['err'] = 'BPM が無い'
            return r
        pos = -1
        for s in info['_difficultyBeatmapSets']:
            ch = s.get('_beatmapCharacteristicName')
            for bm in s.get('_difficultyBeatmaps', []):
                pos += 1
                if ch != 'Standard':
                    continue
                if not isinstance(bm, dict):
                    raise TypeError('難易度の項目が辞書でない')
                r['diffs'].append(parse_diff(folder, bm, pos, bpm))
    except Exception as e:
        r['err'] = f'{type(e).__name__}: {e}'
    return r


def parse_diff(folder, bm, pos, bpm):
    d = {'pos': pos, 'rank': None, 'file': None, 'missing': 0, 'mods': 0, 'err': None, 'xerr': None}
    try:
        d['rank'] = bm.get('_difficulty')
        d['njs'] = bm.get('_noteJumpMovementSpeed')
        req = ((bm.get('_customData') or {}).get('_requirements')) or []
        if any('Noodle' in q or 'Mapping Extensions' in q for q in req):
            d['mods'] = 1
            return d
        d['file'] = bm.get('_beatmapFilename', '')
        dp = LS.find(folder, d['file'])
        if not dp:
            d['missing'] = 1
            return d
        raw = LS.load(dp)
        notes, bombs, arcs, chains, bpmch = LS.parse_diff(raw)
    except Exception as e:
        d['err'] = f'{type(e).__name__}: {e}'
        return d
    d.update(version='3' if ('colorNotes' in raw or 'version' in raw) else '2', bpmch=int(bool(bpmch)), notes=len(notes),
             bombs=bombs, arcs=arcs, chains=chains)
    themes = not bpmch and len(notes) >= 50   # library_themes が型を数える難易度
    try:
        sl, sr = LT.hand_swings(notes, 0), LT.hand_swings(notes, 1)
        rl, rr = LT.runs(sl, 0), LT.runs(sr, 1)
        hands = []
        for cyc, b0, b1, reps, g in rl + rr:
            k = LT.canon(list(cyc))
            if k:
                hands.append((k, b0, b1, reps, g))
        pairs = []
        for cl, l0, l1, _, gl in rl:
            for cr, r0, r1, _, gr in rr:
                ov = min(l1, r1) - max(l0, r0)
                if ov > 0.5 * min(l1 - l0, r1 - r0) and ov >= 2:
                    kl, kr = LT.canon(list(cl)), LT.canon(list(cr))
                    if kl and kr:
                        pairs.append((kl, kr, max(l0, r0), min(l1, r1), (gl + gr) / 2))
        once = once_windows(sl, 0, rl) + once_windows(sr, 1, rr)
        d['swings'] = [[[b, *s] for b, s in sw] for sw in (sl, sr)]
        d['hands'] = {_key(k): (v, k) for k, v in _agg(hands).items()}
        d['pairs'] = {_key(k[0]) + '|' + _key(k[1]): (v, k) for k, v in
                      _agg([(min((kl, kr), (kr, kl)), b0, b1, 1, g) for kl, kr, b0, b1, g in pairs]).items()}
        d['once'] = {_key(k): (v, k) for k, v in _agg([(k, b, b, 1, g) for k, b, g in once]).items()}
    except Exception as e:
        d['err' if themes else 'xerr'] = f'{type(e).__name__}: {e}'
        d.pop('hands', None)
    if not bpmch:   # 打ち方の数字（library_stats.song と同じ）
        try:
            st = LS.analyze(list(notes), bpm)
            if st:
                mins = st['n'] / st['nps'] / 60
                st.update(bombs_pm=bombs / mins, arcs_pm=arcs / mins, chains_pm=chains / mins, njs=d.get('njs'), bpm=bpm)
                st.pop('times', None)
                d['stats'] = st
        except Exception:
            pass
    return d


def hard_parts(seq, cyclic):
    """型の形の難しさ（右手の形の振りの並び）: 移動・向きの変わり方（真逆＝0・135°＝1・90°＝2）・斜め・腕の交差（左端の列）・上の段"""
    P = len(seq)
    pr = [(seq[k], seq[(k + 1) % P]) for k in range(P if cyclic else P - 1)]
    turn = []
    for a, b in pr:
        va, vb = LS.DIRV.get(a[2]), LS.DIRV.get(b[2])
        if va and vb:
            cosv = (va[0] * vb[0] + va[1] * vb[1]) / (math.hypot(*va) * math.hypot(*vb))
            turn.append((180 - math.degrees(math.acos(max(-1, min(1, cosv))))) / 45)
    p = {'move': sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in pr) / len(pr),
         'turn': sum(turn) / len(turn) if turn else 0.0,
         'diag': sum(1 for s in seq if s[2] in (4, 5, 6, 7)) / P,
         'cross': sum(1 for s in seq if s[0] == 0) / P,
         'high': sum(1 for s in seq if s[1] == 2) / P}
    p = {k: round(v, 3) for k, v in p.items()}
    return p, round(0.5 * p['move'] + p['turn'] + 0.5 * p['diag'] + p['cross'] + 0.5 * p['high'], 3)


def gather(root, local):
    """作る元の譜面のフォルダ: 手元（登録の並び）→ 取った物（名前の順）"""
    out = []
    li = C.read_json(root / 'local' / 'index.json') or {'folders': []}
    if local:
        for e in li['folders']:
            out.append({'place': 'local', 'folder': e['name'], 'path': str(Path(li['root']) / e['name']), 'ord': e['order'],
                        'hash': e.get('hash'), 'key': e.get('key')})
    idx = C.read_json(root / 'maps_index.json') or {}
    for i, (h, e) in enumerate(sorted(idx.items(), key=lambda x: x[1]['folder'])):
        out.append({'place': 'raw', 'folder': e['folder'], 'path': str(root / 'maps' / e['folder']), 'ord': RAW_ORD + i,
                    'hash': h, 'key': e.get('key')})
    return out


def _work(m):
    return parse_map(m['path'])


def is_kept(name, patterns):
    """「!」で始まる型に合うフォルダ名か（利用者が手で打った譜面＝どの見分けが当たっても自分の物にしない）"""
    n = name.lower()
    return any(fnmatch.fnmatchcase(n, p[1:].lower()) for p in patterns if p.startswith('!'))


def is_own(name, patterns):
    """自分で書き出した手元の譜面か（フォルダ名の型の一覧。「!」で始まる型に合う物は除かない）"""
    n = name.lower()
    return not is_kept(name, patterns) and any(fnmatch.fnmatchcase(n, p.lower()) for p in patterns if not p.startswith('!'))


def playlists_for(levels):
    """CustomLevels の場所 → プレイリストの場所（app/bsexport.playlists_for と同じ決まり＝tests/test_library_db.py で確かめる）"""
    p = Path(levels)
    if p.name.lower() == 'customlevels' and p.parent.name.lower() in ('sharedmaps', 'beat saber_data'):
        return p.parent.parent / 'Playlists'
    return p.parent / 'Playlists'


def own_hints(cfg=None, out_dir=None, playlist_dirs=None):
    """自分（アプリ・NLM）で書き出した手元の譜面の手がかりのうち、Info.dat の印と名前の型のほか →
    {'folders': {小文字のフォルダ名: [見分け]}, 'hashes': {小文字の hash: [見分け]}, 'read': {'work': 作業の場所, 'playlists': [プレイリストの場所]}}
    - playlist: プレイリスト（.bplist）の ANP の行（customData.anpFolder＝automap/playlist.py が書く）のフォルダ名と hash
    - work: 作業の場所（out/ の下の全部の .nlmf＝履歴・控え・見本も）の書き出すフォルダ名（graph.out.folderName・infoGraph の outs
      ＝NLM で書き出しても同じ名前＝印の無い前の書き出し・NLM から直に書き出した物も拾う）
    - export: アプリの書き出しの記録（out/.export/*.json の folder）
    場所は設定から（作業の場所＝automap/config.out_dir・プレイリスト＝bs_playlists と、bs_levels・custom_levels の隣）"""
    cfg = C.config() if cfg is None else cfg
    out = Path(out_dir) if out_dir is not None else AC.out_dir(cfg)
    if playlist_dirs is None:
        playlist_dirs = [cfg.get('bs_playlists')] + [playlists_for(cfg[k]) for k in ('bs_levels', 'custom_levels') if cfg.get(k)]
    pdirs = list(dict.fromkeys(str(Path(p)) for p in playlist_dirs if p))
    folders, hashes = {}, {}

    def add(d, k, why):
        if k and k.strip():
            d.setdefault(k.strip().lower(), set()).add(why)
    if out.is_dir():
        for p in out.rglob('*.nlmf'):
            try:
                data = p.read_bytes()
            except OSError:
                continue
            for m in FOLDER_NAME.finditer(data):
                try:
                    add(folders, json.loads(b'"' + m.group(1) + b'"'), 'work')
                except ValueError:
                    pass
        for p in (out / '.export').glob('*.json'):
            rec = C.read_json(p) or {}
            if isinstance(rec, dict) and isinstance(rec.get('folder'), str):
                add(folders, rec['folder'], 'export')
    for d in pdirs:
        if not Path(d).is_dir():
            continue
        for p in Path(d).glob('*.bplist'):
            try:
                pl = PL.load(p)
            except (OSError, ValueError):
                continue
            for s in pl.get('songs') or []:
                f = (s.get('customData') or {}).get('anpFolder') if isinstance(s, dict) and isinstance(s.get('customData'), dict) else None
                if isinstance(f, str) and f.strip():
                    add(folders, f, 'playlist')
                    add(hashes, str(s.get('hash') or ''), 'playlist')
    srt = lambda s: sorted(s, key=OWN_KINDS.index)   # noqa: E731
    return {'folders': {k: srt(v) for k, v in folders.items()}, 'hashes': {k: srt(v) for k, v in hashes.items()},
            'read': {'work': str(out), 'playlists': pdirs}}


def own_reasons(m, mark, patterns, hints):
    """自分で書き出した譜面か → 当たった見分けの並び（OWN_KINDS の順・空＝人の譜面）。m＝gather の行・mark＝Info.dat の ANP の印・
    hints＝own_hints。印のほかの見分けは手元の譜面だけ。「!」で始まる型に合う手元の譜面は何が当たっても除かない"""
    local = m['place'] == 'local'
    if local and is_kept(m['folder'], patterns):
        return []
    out = {'mark'} if mark else set()
    if local:
        out.update((hints or {}).get('folders', {}).get(m['folder'].lower(), ()))
        out.update((hints or {}).get('hashes', {}).get((m.get('hash') or '').lower(), ()))
        if is_own(m['folder'], patterns):
            out.add('name')
    return sorted(out, key=OWN_KINDS.index)


def _info_brief(folder):
    """Info.dat → (曲名, アーティスト, 作者, ANP の印)（v2・v4。読めなければ空）"""
    try:
        info = LS.load(LS.find(folder, 'Info.dat'))
    except Exception:   # noqa: BLE001
        return '', '', '', None
    if not isinstance(info, dict):
        return '', '', '', None
    if '_difficultyBeatmapSets' in info or '_songName' in info:
        return info.get('_songName') or '', info.get('_songAuthorName') or '', info.get('_levelAuthorName') or '', BX.anp_mark(info)
    song = info.get('song') if isinstance(info.get('song'), dict) else {}
    who = []
    for d in info.get('difficultyBeatmaps') or []:
        who += ((d.get('beatmapAuthors') or {}).get('mappers') or []) if isinstance(d, dict) else []
    return song.get('title') or '', song.get('author') or '', ', '.join(dict.fromkeys(map(str, who))), BX.anp_mark(info)


def own_table(root, db=None, own_patterns=None, hints=None):
    """手元の譜面のうち自分で書き出した物の一覧（作る前の確かめ・Info.dat だけ読む）→
    [{'folder', 'reasons', 'song', 'artist', 'author', 'was'（今のデータベースの own・載っていなければ None）}]（自分の物か、今は自分の物の行だけ）"""
    own_patterns = C.config().get('library_own', []) if own_patterns is None else own_patterns
    hints = own_hints() if hints is None else hints
    was = {}
    if db and Path(db).is_file():
        con = sqlite3.connect(f'file:{Path(db).as_posix()}?mode=ro', uri=True)
        try:
            was = {f: o for f, o in con.execute("SELECT folder, own FROM maps WHERE place = 'local'")}
        finally:
            con.close()
    rows = []
    for m in gather(root, True):
        if m['place'] != 'local':
            continue
        song, artist, author, mark = _info_brief(m['path'])
        rs = own_reasons(m, mark, own_patterns, hints)
        if rs or was.get(m['folder']):
            rows.append({'folder': m['folder'], 'reasons': rs, 'song': song, 'artist': artist, 'author': author, 'was': was.get(m['folder'])})
    return rows


def build(root, db, jobs=8, local=True, log=print, own_patterns=None, hints=None):
    """own_patterns＝自分で書き出した手元の譜面のフォルダ名の型（省略は app/config.local.json の library_own）・
    hints＝自分で書き出した譜面の手がかり（own_hints の答え・省略は設定の場所から集める）"""
    t0 = time.time()
    own_patterns = C.config().get('library_own', []) if own_patterns is None else own_patterns
    hints = own_hints() if hints is None else hints
    maps = gather(root, local)
    log(f'譜面 {len(maps)}（手元 {sum(m["place"] == "local" for m in maps)}・取った物 {sum(m["place"] == "raw" for m in maps)}）を読む')
    ranked = (C.read_json(root / 'bl' / '_ranked.json') or {}).get('hashes', {})
    hashes = C.read_json(root / 'meta' / '_hashes.json') or {}
    tmp = Path(str(db) + '.building')
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    pid = {}

    def pattern(kind, key, k):
        i = pid.get((kind, key))
        if i is not None:
            return i
        if kind == 'pair':
            sa, sb = LT.shape(k[0]), LT.shape(k[1])
            ha, hb = hard_parts(k[0], True), hard_parts(k[1], True)
            row = (len(k[0]) + len(k[1]), None, None, None, None, None, json.dumps(sa), json.dumps(sb), round((ha[1] + hb[1]) / 2, 3),
                   json.dumps({'a': ha[0], 'b': hb[0]}))
        else:
            s = LT.shape(k)
            if kind == 'once':   # 輪ではなく並び（最後から最初へ戻る移動は数えない）
                s['move'] = round(sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(k, k[1:])) / (len(k) - 1), 3)
            hp, hs = hard_parts(k, kind == 'hand')
            row = (len(k), s['cells'], s['move'], s['row'], s['diag'], s['width'], None, None, hs, json.dumps(hp))
        cur = con.execute('INSERT INTO patterns (kind, key, n, cells, move, row, diag, width, shape_a, shape_b, hard_shape, hard_parts) '
                          'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (kind, key, *row))
        pid[(kind, key)] = cur.lastrowid
        return cur.lastrowid

    n_diff = n_err = n_v4 = n_own = 0
    own_by, own_maps = Counter(), []   # 自分で書き出した譜面の見分けごとの数・[フォルダ名, [見分け]]
    approx_ver = Counter()   # ★の近似を測った nlm-rating の版（BeatLeader の★と同じ計算か＝v0.2.0 から PPv4）
    pool = Pool(jobs) if jobs > 1 else None   # 1 ならこのプロセスだけで（テスト）
    try:
        for i, (m, r) in enumerate(zip(maps, pool.imap(_work, maps, chunksize=4) if pool else map(_work, maps))):
            meta = None
            k = (hashes.get(m['hash']) or {}).get('key') if m['hash'] else None
            if k:
                meta = C.read_json(root / 'meta' / f'{k}.json')
            bl = C.read_json(root / 'bl' / f'{m["hash"]}.json') if m['hash'] in ranked else None
            rating = C.read_json(root / 'rating' / f'{m["hash"]}.json') if m['hash'] else None
            md = (meta or {}).get('metadata') or {}
            inf = r['info']
            names = []
            if meta:
                names = [meta.get('uploader', {}).get('name')] + [c.get('name') for c in meta.get('collaborators') or []]
            la = md.get('levelAuthorName') or inf.get('levelAuthorName')
            names = [n for n in dict.fromkeys(names + [la]) if n]
            up = (meta or {}).get('uploaded')
            st = (meta or {}).get('stats') or {}
            reasons = own_reasons(m, r.get('anp'), own_patterns, hints)
            if reasons:
                n_own += 1
                own_by.update(reasons)
                own_maps.append([m['folder'], reasons])
            cur = con.execute(
                'INSERT INTO maps (place, folder, ord, hash, key, ranked, on_beatsaver, song, sub, artist, level_author, mappers, uploaded, '
                'year, bpm, duration, upvotes, downvotes, score, curated, v4, err, own) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (m['place'], m['folder'], m['ord'], m['hash'], (meta or {}).get('id', m['key'] or '').lower() or None,
                 int(m['hash'] in ranked), int(meta is not None), md.get('songName') or inf.get('songName'),
                 md.get('songSubName') or inf.get('songSubName'), md.get('songAuthorName') or inf.get('songAuthorName'), la,
                 json.dumps(names, ensure_ascii=False), up, int(up[:4]) if up else None, r['bpm'], md.get('duration'),
                 st.get('upvotes'), st.get('downvotes'), st.get('score'), int(bool((meta or {}).get('curatedAt'))), r['v4'], r['err'],
                 int(bool(reasons))))
            map_id = cur.lastrowid
            n_err += bool(r['err'])
            n_v4 += r['v4']
            bld = {}
            for x in (bl or {}).get('leaderboards', []):
                df = x['difficulty']
                bld[(df['modeName'], df['difficultyName'])] = df
            rat = {}
            for x in (rating or {}).get('results') or []:
                nr = ((x.get('ratings') or {}).get('none')) or {}
                if nr.get('stars') is not None:
                    rat[(x['characteristic'], x['difficulty'])] = nr
            used = False
            for d in r['diffs']:
                b = bld.get(('Standard', d['rank']))
                # Noodle・Mapping Extensions の難易度は★の近似も使わない（fetch.py rate が測らない難易度。前に測った値が残っていても
                # 計算の版が古く、マスの外のノーツで★がでたらめ＝★ 1618 等）
                a = rat.get(('Standard', d['rank'])) if not b and not d['mods'] else None
                used |= a is not None
                src = b or a or {}
                stats = d.get('stats')
                cur = con.execute(
                    'INSERT INTO diffs (map_id, pos, characteristic, difficulty, filename, missing, mods, version, bpm_change, notes, bombs, '
                    'arcs, chains, njs, nps, bl_ranked, stars, star_approx, pass, tech, acc, ranked_time, err, xerr, stats) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (map_id, d['pos'], 'Standard', d['rank'], d['file'], d['missing'], d['mods'], d.get('version'), d.get('bpmch'),
                     d.get('notes'), d.get('bombs'), d.get('arcs'), d.get('chains'), d.get('njs'), (stats or {}).get('nps'),
                     int(b is not None), src.get('stars'), int(a is not None) if src else None,
                     src.get('passRating', src.get('pass')), src.get('techRating', src.get('tech')), src.get('accRating', src.get('acc')),
                     (b or {}).get('rankedTime'), d['err'], d['xerr'], json.dumps(stats) if stats else None))
                diff_id = cur.lastrowid
                n_diff += 1
                for h, sw in enumerate(d.get('swings') or []):
                    con.execute('INSERT INTO swings VALUES (?,?,?)', (diff_id, h, zlib.compress(json.dumps(sw, separators=(',', ':')).encode())))
                rows = []
                for kind, name in (('hand', 'hands'), ('pair', 'pairs')):
                    for key, (v, kk) in (d.get(name) or {}).items():
                        rows.append((pattern(kind, key, kk), diff_id, v[0], v[1], json.dumps(v[2]), v[3], json.dumps(v[4])))
                con.executemany('INSERT INTO occurrences VALUES (?,?,?,?,?,?,?)', rows)
                con.executemany('INSERT INTO once_occ VALUES (?,?,?,?,?)',
                                [(pattern('once', key, kk), diff_id, v[0], statistics.median(v[2]), json.dumps([s[0] for s in v[4]]))
                                 for key, (v, kk) in (d.get('once') or {}).items()])
            if used:
                approx_ver[rating.get('exe_version') or rating.get('version') or '?'] += 1
            if (i + 1) % 200 == 0:
                log(f'  {i + 1}/{len(maps)}（{time.time() - t0:.0f} 秒）')
    finally:
        if pool:
            pool.close()
            pool.join()
    con.executescript(INDEXES)
    info = {'schema_version': DB.SCHEMA_VERSION, 'extract_version': DB.EXTRACT_VERSION, 'built_at': C.now(), 'once_len': ONCE_LEN,
            'raw_root': str(root), 'local_root': (C.read_json(root / 'local' / 'index.json') or {}).get('root') if local else None,
            'maps': len(maps), 'diffs': n_diff, 'map_errors': n_err, 'v4': n_v4, 'own': n_own, 'own_patterns': own_patterns,
            'own_by': {k: own_by[k] for k in OWN_KINDS if own_by[k]}, 'own_maps': own_maps, 'own_read': hints.get('read'),
            'bl_list_at': (C.read_json(root / 'bl' / '_ranked.json') or {}).get('fetched_at'), 'approx_versions': dict(approx_ver),
            'patterns': dict(con.execute('SELECT kind, COUNT(*) FROM patterns GROUP BY kind').fetchall())}
    con.executemany('INSERT INTO info VALUES (?,?)', [(k, json.dumps(v, ensure_ascii=False)) for k, v in info.items()])
    con.commit()
    con.execute('ANALYZE')
    con.close()
    try:
        os.replace(tmp, db)
    except PermissionError:
        raise SystemExit(f'前のデータベースを使っているプロセスがあって置き換えられない（アプリ等を閉じてから作り直す）。作った物は {tmp}')
    log(f'できた: 譜面 {len(maps)}・難易度 {n_diff}・読めない譜面 {n_err}・v4 {n_v4}・自分で書き出した物 {n_own}'
        f'（{"・".join(f"{k} {v}" for k, v in info["own_by"].items())}）・型 {info["patterns"]}・'
        f'{os.path.getsize(db) / 1e6:.0f}MB・{time.time() - t0:.0f} 秒 → {db}')
    return info


OWN_TEXT = {'mark': 'Info.dat の印', 'playlist': 'プレイリスト', 'work': '作業の場所の .nlmf', 'export': '書き出しの記録',
            'name': 'library_own の型'}


def print_own(rows, log=print):
    """own_table の一覧を、今のデータベースからの違いごとに出す"""
    groups = (('新しく自分の物になる', lambda r: r['reasons'] and not r['was']),
              ('自分の物でなくなる', lambda r: not r['reasons'] and r['was']),
              ('前から自分の物', lambda r: r['reasons'] and r['was']))
    for title, f in groups:
        sel = [r for r in rows if f(r)]
        log(f'== {title}: {len(sel)}')
        for r in sel:
            log(f'  {r["folder"]} | {r["song"]} | {r["artist"]} | 作者 {r["author"] or "（空）"} | '
                f'{"・".join(OWN_TEXT[k] for k in r["reasons"]) or "（どれも当たらない）"}'
                + ('' if r['was'] is not None else '（今のデータベースに無い）'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root')
    ap.add_argument('--db')
    ap.add_argument('--local')
    ap.add_argument('--no-local', action='store_true', help='手元の譜面を入れない')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--list-own', action='store_true', help='作らずに、自分で書き出した手元の譜面の一覧を出す（今のデータベースとの違い）')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    root = C.raw_root(a.root)
    if not a.no_local:
        import fetch
        fetch.cmd_local(a, root)
    if a.list_own:
        hints = own_hints()
        print(f'手がかりを読んだ場所: 作業の場所 {hints["read"]["work"]}・プレイリスト {hints["read"]["playlists"]}')
        print_own(own_table(root, C.db_path(a.db), hints=hints))
        return
    build(root, C.db_path(a.db), jobs=a.jobs, local=not a.no_local)


if __name__ == '__main__':
    main()
