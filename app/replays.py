"""遊んだリプレイ（BeatLeader の .bsor）を、BL のリプレイアプリ（app/static/blreplay/・tools/blreplay_fetch.py で写した物）で開く
（2026-11-12 利用者「自分のプレイのリプレイを見れるようにしたい。サーバに譜面がないから BL の WEB リプレイで見れなくてつらい」
「出来れば、BL のリプレイアプリを使いたい」「ローカルに持って来てうまいこと動かせないかな」）。docs/アプリ仕様.md 26 節。

BL のリプレイアプリは譜面を BeatSaver から取るので、アプリで作った（BeatSaver に無い）譜面を開けない。アプリのサーバーに置いた BL の
リプレイアプリへ、リプレイ（?link=）と遊んだ時の譜面の zip（?mapLink=・zip-loader が BeatSaver に問い合わせずに読む）を渡して開く。

- リプレイの置き場: 設定の bl_replays（場所 1 つか一覧）。無ければ Beat Saber の曲のフォルダの候補（bsexport.candidates）から
  BSManager＝<BSManager>/BSInstances/*/UserData/BeatLeader/Replays・ゲームのフォルダ＝<Beat Saber>/UserData/BeatLeader/Replays。
- 今の曲のリプレイ: 遊んだ譜面の hash が、この曲の書き出しの控え（下）・書き出しの記録（<out>/.export/<結果>.json）・今の書き出し先の
  フォルダの hash のどれかと同じ物と、曲名（.nlmf と書き出した Info.dat の _songName）が同じ物。
- 遊んだ時の譜面（zip の中身）を探す順:
  1. 書き出しの控え <out>/.export/maps/<hash>/（書き出すたびに bsexport の後始末が keep_export で控える＝Info.dat・難易度の .dat・
     カバー・anp.json。song.egg は中身の sha1 ごとに <out>/.export/eggs/<sha1>.egg＝同じ音は 1 つ）
  2. 今の書き出し先のフォルダ（hash が同じ＝遊んだ後にまだ書き出し直していない）
  3. 組み立て: どちらも無い（控えを始める前に遊んで、その後に書き出し直した）時は、リプレイの記録のノーツ（切った・見逃した全部の
     位置・色・向き・時刻）から譜面の .dat を作り、音とカバーとライトは今の書き出し（無ければこの曲の一番新しい控え）から借りる。
     壁・アーク・チェーンは入らない（当たったボムだけ入る）・NJS は今の書き出しの同じ難易度の値。
- 受け口: GET /api/replays?file= → 今の曲の一覧／GET /api/replays/all → 全部の履歴（2026-11-15 利用者「全体の履歴も表示出来るように」・
  どの曲のリプレイも・ANP の曲の物は anp＝{file, song}）／POST /api/replays/open {id, file?} → {link, mapLink, source, note}＝BL のリプレイ
  アプリへ渡す場所（file 無し＝全部の履歴から: ANP の曲か見分け、ほかの譜面は手元の曲のフォルダ（同じ hash）・無ければ押した時に
  BeatSaver から zip を取る＝beatsaver_zip・BL のリプレイアプリの BeatSaver から取る道は BL のサーバー経由から始まりここでは通らない）／POST /api/replays/dir {dir}＝置き場を決める（空で自動に戻す）。
- 今の曲の物か（_mine）: hash が同じか、曲名が同じで作者名が空（マッパー名を入れる前の書き出し）かその曲を書き出した時の作者名
  ＝同じ曲名の他人の譜面（BeatSaver の譜面）を混ぜない。一覧の数（ミス・精度）は作業の場所の cache/.replays-summary.json に控える。
  渡す場所 /blr/<鍵>/<リプレイのファイル名>・/blr/<鍵>/map.zip は、開くたびに作る使い捨ての鍵（その 1 件だけ・サーバーを止めると消える）
  で受ける＝起動ごとの合言葉は要らない（BL のリプレイアプリは合言葉を付けられない・アプリの合言葉を渡さない）。server.py の出入りの
  守りは /blr/ を合言葉なしで通し、ここ（serve）が鍵を確かめる。
"""
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from pathlib import Path

import bsexport   # noqa: E402  （app/ の中・Beat Saber のフォルダの候補・書き出しの記録）
from names import plain   # noqa: E402
from automap import bsor, config

DIFF_RANK = {'Easy': 1, 'Normal': 3, 'Hard': 5, 'Expert': 7, 'ExpertPlus': 9}
KEEP_TOKENS = 8                     # 覚えておく鍵（zip を 1 つずつ持つ・1 つ 5MB ほど）
_TOK, _LOCK = {}, threading.Lock()  # 鍵 → {name, bsor（場所）, zip（バイト列）, at}
_HEAD = {}                          # リプレイの場所 → (更新時刻, 大きさ, 頭)
_SUM = {}                           # リプレイの場所 → (更新時刻, 大きさ, 数)
_FHASH = {}                         # 譜面のフォルダ → (Info.dat と .dat の更新時刻, hash)
TOKEN_RE = re.compile(r'[A-Za-z0-9_-]{24,64}')
HASH_RE = re.compile(r'[0-9a-f]{40}')


# ---- 置き場 ----

def _replays_for(levels):
    """Beat Saber の曲のフォルダ（CustomLevels）→ そのゲームのリプレイの置き場の候補"""
    p = Path(levels)
    if p.name.lower() == 'customlevels' and p.parent.name.lower() == 'sharedmaps':   # BSManager の共有
        root = p.parent.parent.parent
        return sorted((root / 'BSInstances').glob('*/UserData/BeatLeader/Replays'), reverse=True)
    if p.name.lower() == 'customlevels' and p.parent.name.lower() == 'beat saber_data':
        return [p.parent.parent / 'UserData' / 'BeatLeader' / 'Replays']
    return []


def replay_dirs(cfg):
    want = cfg.get('bl_replays')
    if want:
        return [Path(x) for x in (want if isinstance(want, list) else [want]) if Path(x).is_dir()]
    out = []
    for c in bsexport.candidates(cfg):
        for d in _replays_for(c['levels']):
            if d.is_dir() and d not in out:
                out.append(d)
    return out


def set_dir(ctx, b):
    v = str(b.get('dir') or '').strip().strip('"')
    if v and not Path(v).is_dir():
        raise ValueError(f'そのフォルダは見つかりません: {v}')
    config.update({'bl_replays': v or None}, ctx.CONFIG)
    return {'ok': True, 'dirs': [str(d) for d in replay_dirs(config.load(ctx.CONFIG))]}


# ---- 譜面のフォルダ ----

def _info_of(folder):
    try:
        return json.loads((Path(folder) / 'Info.dat').read_bytes().decode('utf-8-sig'))
    except (OSError, ValueError):
        return None


def _beatmaps(info):
    """Info.dat（v2）の難易度のファイル名の並び（Info の順）。どれか 1 つでも 1 つのファイルの名前（names.plain）で .dat でなければ None＝
    その譜面は使わない（手元の譜面フォルダは第三者が作った物で、名前が UNC・絶対の場所・.. だとフォルダの外を開く＝UNC なら NTLM の
    認証を送る・2026-11-15 のスキャン F2）"""
    ns = [bm.get('_beatmapFilename') for s in info.get('_difficultyBeatmapSets') or [] for bm in s.get('_difficultyBeatmaps') or []]
    if not all(isinstance(n, str) and plain(n) and n.lower().endswith('.dat') for n in ns):
        return None
    return ns


def folder_hash(folder):
    """譜面のフォルダの BeatSaver の hash（Info.dat＋難易度の .dat を Info の順に・bs_export.map_hash と同じ）。読めなければ None"""
    folder = Path(folder)
    info = _info_of(folder)
    if not info:
        return None
    bms = _beatmaps(info)
    if bms is None:
        return None
    names = ['Info.dat'] + bms
    try:
        key = tuple((folder / n).stat().st_mtime_ns for n in names)
    except OSError:
        return None
    hit = _FHASH.get(str(folder))
    if hit and hit[0] == key:
        return hit[1]
    h = hashlib.sha1()
    for n in names:
        h.update((folder / n).read_bytes())
    _FHASH[str(folder)] = (key, h.hexdigest())
    return h.hexdigest()


def _maps_root(ctx):
    return Path(ctx.OUT) / '.export' / 'maps'


def _eggs_root(ctx):
    return Path(ctx.OUT) / '.export' / 'eggs'


def keep_export(ctx, p, r):
    """書き出した譜面を hash ごとに控える（bsexport の書き出しの後始末が呼ぶ）。控えてあれば何もしない"""
    h = str(r.get('hash') or '').lower()
    src = Path(r.get('dir') or '')
    info = _info_of(src)
    if not HASH_RE.fullmatch(h) or not info or _beatmaps(info) is None or folder_hash(src) != h:
        return None
    dst = _maps_root(ctx) / h
    if (dst / 'anp.json').is_file():
        return dst
    tmp = dst.with_name(h + '.tmp')
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    names = ['Info.dat'] + _beatmaps(info)
    cover = info.get('_coverImageFilename')
    if cover and plain(cover) and (src / cover).is_file():
        names.append(cover)
    for n in names:
        shutil.copy2(src / n, tmp / n)
    song = info.get('_songFilename') or ''
    egg = None
    if plain(song) and (src / song).is_file():
        data = (src / song).read_bytes()
        egg = hashlib.sha1(data).hexdigest()
        ef = _eggs_root(ctx) / (egg + '.egg')
        if not ef.is_file():
            ef.parent.mkdir(parents=True, exist_ok=True)
            ef.write_bytes(data)
    (tmp / 'anp.json').write_text(json.dumps({'file': Path(p).name, 'folder': src.name, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                              'egg': egg}, ensure_ascii=False), encoding='utf-8')
    if dst.exists():
        shutil.rmtree(dst)
    tmp.rename(dst)
    return dst


def _kept(ctx):
    """書き出しの控え → [(hash, 場所, anp.json の中身)]"""
    root = _maps_root(ctx)
    out = []
    if root.is_dir():
        for d in root.iterdir():
            if HASH_RE.fullmatch(d.name) and (d / 'anp.json').is_file():
                try:
                    out.append((d.name, d, json.loads((d / 'anp.json').read_text(encoding='utf-8'))))
                except (OSError, ValueError):
                    pass
    return out


def _song_maps(ctx, p):
    """この曲（結果のファイル）の譜面 → {hashes: {hash: ('saved'|'folder', 場所)}, names: 曲名, base: 組み立てに借りる場所}"""
    hashes, names, base = {}, set(), None
    try:
        from automap import nlmf
        nm = (nlmf.load(p).get('info') or {}).get('_songName')
        if nm:
            names.add(nm)
    except (OSError, ValueError):
        pass
    mappers = set()
    saved = sorted((x for x in _kept(ctx) if x[2].get('file') == p.name), key=lambda x: x[2].get('at') or '')
    for h, d, _ in saved:
        hashes[h] = ('saved', d)
        info = _info_of(d)
        if info:
            names.add(info.get('_songName') or '')
            mappers.add(info.get('_levelAuthorName') or '')
    if saved:
        base = saved[-1][1]
    rec = bsexport.last_export(ctx, p)
    if rec and rec.get('dir') and _info_of(rec['dir']):
        d = Path(rec['dir'])
        fh = folder_hash(d)
        if fh:
            hashes.setdefault(fh, ('folder', d))
        names.add(_info_of(d).get('_songName') or '')
        mappers.add(_info_of(d).get('_levelAuthorName') or '')
        base = d
    names.discard('')
    try:   # 書き出しの窓で入れたマッパー名（NLM で書き出した版も同じ名前のはず）
        mappers.add(config.load(ctx.CONFIG).get('mapper_name') or '')
    except (OSError, ValueError, AttributeError):
        pass
    mappers.discard('')
    return {'hashes': hashes, 'names': {n.strip().casefold() for n in names}, 'base': base,
            'mappers': {m.strip().casefold() for m in mappers}}


def _mine(info, sm):
    """リプレイがこの曲（結果のファイル）の物か: 遊んだ譜面の hash がこの曲の書き出しと同じか、曲名が同じで作者名が空（マッパー名を
    入れる前の書き出し）かこの曲を書き出した時の作者名・設定のマッパー名と同じ（同じ曲名の他人の譜面＝BeatSaver の譜面を混ぜない）"""
    if (info.get('hash') or '').lower() in sm['hashes']:
        return True
    m = (info.get('mapper') or '').strip().casefold()
    return (info.get('song_name') or '').strip().casefold() in sm['names'] and (not m or m in sm['mappers'])


def _songs_index(ctx):
    """作業の場所の ANP の曲（アプリの結果のファイル）→ [(結果のファイル, _song_maps)]"""
    kind = getattr(ctx, 'APP_KIND', 'intent-s1')
    return [(p, _song_maps(ctx, p)) for p in sorted(Path(ctx.OUT).glob(f'*.{kind}.nlmf'))]


# ---- リプレイ ----

def _head(f):
    st = f.stat()
    hit = _HEAD.get(str(f))
    if hit and hit[:2] == (st.st_mtime_ns, st.st_size):
        return hit[2]
    h = bsor.read_info(f)
    _HEAD[str(f)] = (st.st_mtime_ns, st.st_size, h)
    return h


def _summary(f, st=None):
    st = st or f.stat()
    hit = _SUM.get(str(f))
    if hit and hit[:2] == (st.st_mtime_ns, st.st_size):
        return hit[2]
    s = bsor.summary(bsor.read(f))
    _SUM[str(f)] = (st.st_mtime_ns, st.st_size, s)
    _SUM_DISK['dirty'] = True
    return s


# 一覧の数（ミス・精度…）の控え: 1 個読むのに 3〜4ms（ノーツを全部読む）＝全部の履歴（800 個）で 3 秒。サーバーを起動し直しても読み直さない
# ように、作業の場所の cache/ に置く（.replays-summary.json・リプレイの場所 → [更新時刻, 大きさ, 数]・消しても読み直すだけ）
SUM_FILE = '.replays-summary.json'
SUM_VER = 2   # 2＝記録が終わった秒（end）を足した（2026-11-15・前の控えは読み直す）
_SUM_DISK = {'path': None, 'dirty': False}
_SUM_LOCK = threading.Lock()


def _sum_open(ctx):
    cache = getattr(ctx, 'CACHE', None)
    path = str(Path(cache) / SUM_FILE) if cache else None
    if path == _SUM_DISK['path']:
        return
    _SUM_DISK.update(path=path, dirty=False)
    if not path:
        return
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        if d.get('v') == SUM_VER:
            for k, (mt, sz, s) in d['items'].items():
                _SUM.setdefault(k, (mt, sz, s))
    except (OSError, ValueError, TypeError, KeyError):
        pass


def _sum_save():
    path = _SUM_DISK['path']
    if not (path and _SUM_DISK['dirty']):
        return
    try:
        tmp = Path(path + '.tmp')
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({'v': SUM_VER, 'items': {k: list(v) for k, v in _SUM.items()}}, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)
        _SUM_DISK['dirty'] = False
    except OSError:
        pass


def _ts(info, f):
    try:
        return int(info.get('timestamp') or 0) or int(f.stat().st_mtime)
    except ValueError:
        return int(f.stat().st_mtime)


def _scan(ctx, keep):
    """リプレイの置き場の全部 → keep(頭) が真の物だけ [(id, ファイル, 頭, 数)]"""
    cfg = config.load(ctx.CONFIG)
    dirs = replay_dirs(cfg)
    out, other = [], 0
    with _SUM_LOCK:
        _sum_open(ctx)
        for i, d in enumerate(dirs):
            for f in d.glob('*.bsor'):
                try:
                    st = f.stat()
                    info = _head(f)
                except (OSError, bsor.BsorError):
                    continue
                if not keep(info):
                    other += 1
                    continue
                try:
                    s = _summary(f, st)
                except (OSError, bsor.BsorError):
                    s = {}
                out.append((f'{i}/{f.name}', f, info, s))
        _sum_save()
    return cfg, dirs, out, other


# BeatLeader のリプレイのファイル名: <プレイヤー>[-practice][-fail][-exit]-<曲名>-<難易度>-<遊び方>-<hash>-<時刻>.bsor
# ＝exit は途中でやめた（ポーズからメニューへ・やり直し）プレイ（.bsor の中には印が無い・2026-11-15 に LOVE PHANTOM の 4 秒でやめた物で確かめた）
FLAGS_RE = re.compile(r'^[^-]+((?:-(?:practice|fail|exit))*)-')


def name_flags(name):
    m = FLAGS_RE.match(name)
    return set(m.group(1).split('-')[1:]) if m else set()


def _row(rid, f, info, s, src):
    flags = name_flags(f.name)
    row = {'id': rid, 'at': _ts(info, f), 'diff': info.get('difficulty'), 'mode': info.get('mode'),
           'exit': 'exit' in flags, 'practice': 'practice' in flags,
           'score': info.get('score'), 'modifiers': info.get('modifiers') or '', 'fail': (info.get('fail_time') or 0) > 0,
           'player': info.get('player_name'), 'song': info.get('song_name'), 'mapper': info.get('mapper') or '',
           'hash': (info.get('hash') or '').lower(), 'map': src, 'speed': info.get('speed') or 1}
    row.update(s)
    return row


def _answer(ctx, cfg, dirs, rows, other):
    rows.sort(key=lambda r: -r['at'])
    return {'dirs': [str(d) for d in dirs], 'auto': not cfg.get('bl_replays'), 'replays': rows, 'other': other,
            'viewer': (Path(ctx.STATIC) / 'blreplay' / 'index.html').is_file()}


def list_replays(ctx, q):
    """今の曲のリプレイ（GET /api/replays?file=）"""
    p = ctx.out_file(q['file'])
    sm = _song_maps(ctx, p)
    cfg, dirs, got, other = _scan(ctx, lambda info: _mine(info, sm))
    rows = []
    for rid, f, info, s in got:
        src = _map_source(ctx, (info.get('hash') or '').lower(), sm)
        rows.append(_row(rid, f, info, s, src[0] if src else 'none'))
    return _answer(ctx, cfg, dirs, rows, other)


def list_all(ctx, q):
    """全部の履歴（GET /api/replays/all）: どの曲のリプレイも。ANP の曲（作業の場所の結果のファイル）の物は anp＝{file, song} と
    遊んだ時の譜面の出どころ（map）、ほかの譜面（BeatSaver の譜面）は map＝'other'（開く時に手元の曲のフォルダを探す・無ければ BeatSaver から）"""
    idx = _songs_index(ctx)
    cfg, dirs, got, _ = _scan(ctx, lambda info: True)
    rows = []
    for rid, f, info, s in got:
        hit = next(((p, sm) for p, sm in idx if (info.get('hash') or '').lower() in sm['hashes']), None) \
            or next(((p, sm) for p, sm in idx if _mine(info, sm)), None)
        if hit:
            src = _map_source(ctx, (info.get('hash') or '').lower(), hit[1])
            row = _row(rid, f, info, s, src[0] if src else 'none')
            row['anp'] = {'file': hit[0].name, 'song': hit[0].name.split('.')[0]}
        else:
            row = _row(rid, f, info, s, 'other')
            row['anp'] = None
        rows.append(row)
    return _answer(ctx, cfg, dirs, rows, 0)


# ---- ほかの譜面（ANP の曲でない）を手元の曲のフォルダから探す ----
# 曲のフォルダ（CustomLevels・1200 曲ほど）の Info.dat の曲名と作者名の一覧。PC を起動した直後は Info.dat を初めて読むので 10 秒ほど
# かかった＝作業の場所の cache/.replays-levels.json に控え（フォルダ → [Info.dat の更新時刻, 曲名, 作者名]）、次からは更新時刻を見るだけ
LEVELS_FILE = '.replays-levels.json'
_LEVELS = {'key': None, 'items': []}   # 曲のフォルダの置き場の更新時刻 → [(フォルダ, 曲名, 作者名)]


def _levels_index(cfg, cache=None):
    roots = []
    for c in bsexport.candidates(cfg):
        r = Path(c['levels'])
        if r.is_dir() and r not in roots:
            roots.append(r)
    key = tuple((str(r), r.stat().st_mtime_ns) for r in roots)
    if _LEVELS['key'] == key:
        return _LEVELS['items']
    disk, cf = {}, (Path(cache) / LEVELS_FILE) if cache else None
    if cf:
        try:
            d = json.loads(cf.read_text(encoding='utf-8'))
            disk = d['items'] if d.get('v') == 1 else {}
        except (OSError, ValueError, KeyError, TypeError):
            disk = {}
    items, new = [], {}
    for r in roots:
        for d in r.iterdir():
            try:
                mt = (d / 'Info.dat').stat().st_mtime_ns
            except OSError:
                continue
            hit = disk.get(str(d))
            if hit and hit[0] == mt:
                name, mapper = hit[1], hit[2]
            else:
                info = _info_of(d)
                if not info:
                    continue
                name, mapper = (info.get('_songName') or '').strip().casefold(), (info.get('_levelAuthorName') or '').strip().casefold()
            new[str(d)] = [mt, name, mapper]
            items.append((d, name, mapper))
    if cf and new != disk:
        try:
            cf.parent.mkdir(parents=True, exist_ok=True)
            tmp = cf.with_name(cf.name + '.tmp')
            tmp.write_text(json.dumps({'v': 1, 'items': new}, ensure_ascii=False), encoding='utf-8')
            tmp.replace(cf)
        except OSError:
            pass
    _LEVELS.update(key=key, items=items)
    return items


def local_level(cfg, info, cache=None):
    """リプレイの譜面と同じ hash の手元の曲のフォルダ（曲名と作者名で候補を絞ってから hash を確かめる）か None"""
    h = (info.get('hash') or '').lower()
    name, mapper = (info.get('song_name') or '').strip().casefold(), (info.get('mapper') or '').strip().casefold()
    idx = _levels_index(cfg, cache)
    cands = [d for d, n, m in idx if n == name and m == mapper] or [d for d, n, _ in idx if n == name]
    return next((d for d in cands if folder_hash(d) == h), None)


BEATSAVER_ZIPS = ('https://r2cdn.beatsaver.com/{}.zip', 'https://cdn.beatsaver.com/{}.zip')
ZIP_MAX = 200 * 1024 * 1024


def beatsaver_zip(h):
    """BeatSaver から遊んだ版の譜面の zip を取る（手元に無いほかの譜面・押した時だけ）→ バイト列か None（無い・古い版で消えた・ネットが無い）。
    BL のリプレイアプリにも BeatSaver から取る道があるが、BL のサーバー経由の問い合わせ（/cors/…）から始めるので、このアプリの中では
    通らずに「譜面が見つからない」で止まった（2026-11-15）＝こちらで取って mapLink で渡す。送るのは公開の譜面の hash だけ"""
    import ssl
    import urllib.request
    if not HASH_RE.fullmatch(h or ''):
        return None
    ctx = ssl.create_default_context()
    for u in BEATSAVER_ZIPS:
        try:
            req = urllib.request.Request(u.format(h), headers={'User-Agent': 'AutoNotePlotter'})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                b = r.read(ZIP_MAX + 1)
            if len(b) <= ZIP_MAX and b[:4] == b'PK\x03\x04':
                return b
        except (OSError, ValueError):
            continue
    return None


# ---- 一覧のカバー画像（全部の履歴・2026-11-15 利用者「一覧だとカバー画像が欲しくなる。キャッシュしつつ 1 ページ半分だけ画像を随時取得する」） ----
# GET /api/replays/cover?id=<リプレイ>[&file=<ANP の曲の結果のファイル>]: 遊んだ譜面（hash）のカバー。探す順: 書き出しの控え（遊んだ時の物）→
# ANP の曲の書き出し（file がある時だけ・同じ hash の書き出し先か今の書き出し）→ 手元の曲のフォルダ（同じ hash）→ BeatSaver（cdn・送るのは
# 公開の譜面の hash だけ）。見つけた物は作業の場所の cache/.replay-covers/<hash>.<拡張子> に控え、次からはそれを返す。見つからなかった hash は
# COVER_RETRY 秒は探し直さない。画面（js/replays.js）は見えている行と半ページ先の分だけを順に頼む。<img> の src で読むので合言葉は ?k=
# （server.KEY_QUERY）。
COVERS_DIR = '.replay-covers'
COVER_MAX = 8 * 1024 * 1024
COVER_RETRY = 600
BEATSAVER_COVERS = ('https://cdn.beatsaver.com/{}.jpg', 'https://eu.cdn.beatsaver.com/{}.jpg')   # r2cdn は zip だけ（.jpg は 404 だった）
_COVER_MISS = {}   # hash → 見つからなかった時刻


def _img_ext(b):
    if b[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if b[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP':
        return '.webp'
    if b[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif'
    return None


def _folder_cover(d):
    """譜面のフォルダ（Info.dat の _coverImageFilename・v4 は coverImageFilename）→ 画像のバイト列か None"""
    info = _info_of(d) if d else None
    if not info:
        return None
    name = info.get('_coverImageFilename') or info.get('coverImageFilename') or ''
    if not (isinstance(name, str) and plain(name)):
        return None
    f = Path(d) / name
    try:
        if not f.is_file() or f.stat().st_size > COVER_MAX:
            return None
        b = f.read_bytes()
    except OSError:
        return None
    return b if _img_ext(b) else None


def _beatsaver_cover(h):
    import ssl
    import urllib.request
    c = ssl.create_default_context()
    for u in BEATSAVER_COVERS:
        try:
            req = urllib.request.Request(u.format(h), headers={'User-Agent': 'AutoNotePlotter'})
            with urllib.request.urlopen(req, timeout=15, context=c) as r:
                b = r.read(COVER_MAX + 1)
            if len(b) <= COVER_MAX and _img_ext(b):
                return b
        except (OSError, ValueError):
            continue
    return None


def _find_cover(ctx, h, info, file=None):
    b = _folder_cover(_maps_root(ctx) / h)
    if b:
        return b
    if file:
        try:   # 結果のファイルが読めない（消した・名前が違う）時は次の探し先へ
            sm = _song_maps(ctx, ctx.out_file(file))
        except (OSError, ValueError, KeyError):
            sm = None
        if sm:
            hit = sm['hashes'].get(h)
            b = _folder_cover(hit[1] if hit else sm['base'])
            if b:
                return b
    b = _folder_cover(local_level(config.load(ctx.CONFIG), info, getattr(ctx, 'CACHE', None)))
    if b:
        return b
    return _beatsaver_cover(h)


_COVER_LOCKS, _COVER_GUARD = {}, threading.Lock()


def cover(ctx, q):
    """GET /api/replays/cover → 控えた画像の場所（Path）。同じ hash（同じ譜面を何回も遊んだ行）を同時に頼まれても作るのは 1 回・
    もうある控えは置き換えない（2026-11-15: 置き換えている最中に別の頼みがそのファイルを開くと、Windows が Permission denied で断った）"""
    info = _head(_replay_path(ctx, q.get('id')))
    h = (info.get('hash') or '').lower()
    if not HASH_RE.fullmatch(h):
        raise FileNotFoundError('カバーが無い')
    root = Path(ctx.CACHE) / COVERS_DIR

    def have():
        return next((root / (h + ext) for ext in ('.jpg', '.png', '.webp', '.gif') if (root / (h + ext)).is_file()), None)
    hit = have()
    if hit:
        return hit
    with _COVER_GUARD:
        lock = _COVER_LOCKS.setdefault(h, threading.Lock())
    with lock:   # 同じ hash は 1 つずつ（先の頼みが作り終えたら、後の頼みはその控えを返す）
        hit = have()
        if hit:
            return hit
        if time.time() - _COVER_MISS.get(h, 0) < COVER_RETRY:
            raise FileNotFoundError('カバーが無い')
        b = _find_cover(ctx, h, info, q.get('file') or None)
        if not b:
            _COVER_MISS[h] = time.time()
            raise FileNotFoundError('カバーが無い')
        root.mkdir(parents=True, exist_ok=True)
        out = root / (h + _img_ext(b))
        tmp = out.with_name(f'{out.name}.{secrets.token_hex(4)}.tmp')
        tmp.write_bytes(b)
        tmp.replace(out)   # まだ無いファイルへ（ある時は上で返す）
        return out


# ---- 一覧の★（2026-11-15 利用者「一覧に難易度も表示して」→ ★） ----
# POST /api/replays/stars {items: [{id, file?}]} → {stars: {id: ★|None}, pending: [id]}: 遊んだ時の譜面（書き出しの控え・ANP の曲の同じ hash の
# 書き出し先・手元の曲のフォルダ）の、遊んだ難易度と遊び方（Standard・OneSaber…）の★を nlm-rating（BeatLeader の★の近似・アプリの★と同じ物差し・
# 修飾なし）で測る。測っていない物は裏で測り始めて pending で返す（画面は少し待って聞き直す）。測った★は作業の場所の cache/.replay-stars.json
# に hash・遊び方・難易度・nlm-rating の版ごとに控える（版が変われば測り直す）。遊んだ時の譜面が手元に無い（記録から組み立てる版・BeatSaver に
# しか無い）・測れなかった物は None（STAR_RETRY 秒は測り直さない・控えには書かない）。型のライブラリの BeatLeader の★は、配布用のライブラリに
# 譜面の hash が無いので使わない。画面（js/replays.js）は見えている行と半ページ先の分だけをまとめて頼む。
STARS_FILE = '.replay-stars.json'
STAR_WORKERS = max(2, min(6, (os.cpu_count() or 4) // 4))   # 同時に動かす nlm-rating（1 つ 1〜2 秒・論理コアの 1/4・2〜6）
STAR_RETRY = 600
STAR_MAX_ITEMS = 80
_STARS = {'path': None, 'items': {}}
_STAR_MISS, _STAR_PENDING = {}, set()
_STAR_LOCK = threading.Lock()
_STAR_POOL = []


def _stars_open(ctx):
    p = Path(ctx.CACHE) / STARS_FILE
    if _STARS['path'] != p:
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
            items = d['items'] if d.get('v') == 1 and isinstance(d.get('items'), dict) else {}
        except (OSError, ValueError, KeyError, TypeError):
            items = {}
        _STARS.update(path=p, items=items)


def _stars_save():
    p = _STARS['path']
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f'{p.name}.{secrets.token_hex(4)}.tmp')
        tmp.write_text(json.dumps({'v': 1, 'items': _STARS['items']}, ensure_ascii=False), encoding='utf-8')
        tmp.replace(p)
    except OSError:
        pass


def _star_folder(ctx, info, file):
    """遊んだ時の譜面のフォルダか None（遊んだ版が手元に無い）"""
    h = (info.get('hash') or '').lower()
    d = _maps_root(ctx) / h
    if (d / 'anp.json').is_file():
        return d
    if file:
        try:
            sm = _song_maps(ctx, ctx.out_file(file))
        except (OSError, ValueError, KeyError):
            sm = None
        if sm and h in sm['hashes']:
            return sm['hashes'][h][1]
    return local_level(config.load(ctx.CONFIG), info, getattr(ctx, 'CACHE', None))


def _beatmap_file(info, char, diff):
    for s in info.get('_difficultyBeatmapSets') or []:   # v2
        if s.get('_beatmapCharacteristicName') == char:
            for bm in s.get('_difficultyBeatmaps') or []:
                if bm.get('_difficulty') == diff:
                    return bm.get('_beatmapFilename')
    for bm in info.get('difficultyBeatmaps') or []:      # v4
        if bm.get('characteristic') == char and bm.get('difficulty') == diff:
            return bm.get('beatmapDataFilename')
    return None


def _rate_folder(exe, folder, char, diff):
    """譜面のフォルダの 1 つの難易度 → ★（修飾なし）か None"""
    from automap import rating as R
    info = _info_of(folder)
    fn = _beatmap_file(info or {}, char, diff)
    if not (fn and plain(fn) and (Path(folder) / fn).is_file()):
        return None
    try:
        files = [{'name': 'Info.dat', 'text': (Path(folder) / 'Info.dat').read_bytes().decode('utf-8-sig')},
                 {'name': fn, 'text': (Path(folder) / fn).read_bytes().decode('utf-8-sig')}]
    except (OSError, UnicodeDecodeError):
        return None
    ans = R.run(exe, {'protocol': 1, 'files': files, 'targets': [{'characteristic': char, 'difficulty': diff}]}, timeout=120)
    res = next((x for x in ans.get('results') or [] if x.get('difficulty') == diff), None) if ans.get('ok') else None
    st = (((res or {}).get('ratings') or {}).get('none') or {}).get('stars')
    return round(st, 2) if isinstance(st, (int, float)) and not res.get('skipped') else None


def _star_job(ctx, key, info, file, exe):
    try:
        d = _star_folder(ctx, info, file)
        st = _rate_folder(exe, d, info.get('mode') or 'Standard', info.get('difficulty') or '') if d else None
    except Exception:   # 測れない譜面（壊れた .dat 等）で裏の流れを止めない
        st = None
    with _STAR_LOCK:
        if st is None:
            _STAR_MISS[key] = time.time()
        else:
            _STARS['items'][key] = st
            _stars_save()
        _STAR_PENDING.discard(key)


def stars(ctx, b):
    from automap import rating as R
    exe = R.rating_exe()
    if not exe:
        return {'stars': {}, 'pending': [], 'error': R.NO_EXE}
    ver = R.exe_version(exe) or '?'
    out, pending = {}, []
    if not _STAR_POOL:
        from concurrent.futures import ThreadPoolExecutor
        _STAR_POOL.append(ThreadPoolExecutor(STAR_WORKERS, thread_name_prefix='replay-stars'))
    for it in (b.get('items') or [])[:STAR_MAX_ITEMS]:
        rid = str((it or {}).get('id') or '')
        try:
            info = _head(_replay_path(ctx, rid))
        except (OSError, ValueError, bsor.BsorError):
            out[rid] = None
            continue
        key = '|'.join([(info.get('hash') or '').lower(), info.get('mode') or 'Standard', info.get('difficulty') or '', ver])
        with _STAR_LOCK:
            _stars_open(ctx)
            if key in _STARS['items']:
                out[rid] = _STARS['items'][key]
                continue
            if time.time() - _STAR_MISS.get(key, 0) < STAR_RETRY:
                out[rid] = None
                continue
            pending.append(rid)
            if key in _STAR_PENDING:
                continue
            _STAR_PENDING.add(key)
        _STAR_POOL[0].submit(_star_job, ctx, key, info, (it or {}).get('file') or None, exe)
    return {'stars': out, 'pending': pending}


def _map_source(ctx, h, sm):
    """遊んだ譜面の hash → ('saved'|'folder'|'rebuild', 場所) か None"""
    d = _maps_root(ctx) / h
    if HASH_RE.fullmatch(h) and (d / 'anp.json').is_file():
        return 'saved', d
    hit = sm['hashes'].get(h)
    if hit and hit[0] == 'folder':
        return hit
    if sm['base']:
        return 'rebuild', sm['base']
    return None


def _song_file(ctx, folder, info):
    """譜面の場所の音（書き出しの控えは eggs/ の物）→ バイト列か None"""
    folder = Path(folder)
    meta = folder / 'anp.json'
    if meta.is_file():
        try:
            egg = json.loads(meta.read_text(encoding='utf-8')).get('egg')
        except (OSError, ValueError):
            egg = None
        if egg and HASH_RE.fullmatch(egg) and (_eggs_root(ctx) / (egg + '.egg')).is_file():
            return (_eggs_root(ctx) / (egg + '.egg')).read_bytes()
    song = info.get('_songFilename') or ''
    if plain(song) and (folder / song).is_file():
        return (folder / song).read_bytes()
    return None


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


def _folder_files(ctx, folder):
    folder = Path(folder)
    info = _info_of(folder)
    bms = _beatmaps(info or {})
    if bms is None:
        raise FileNotFoundError(f'譜面の難易度のファイル名が使えない（1 つのファイルの名前・.dat でない）: {folder}')
    files = {'Info.dat': (folder / 'Info.dat').read_bytes()}
    for n in bms:
        files[n] = (folder / n).read_bytes()
    cover = info.get('_coverImageFilename')
    if cover and plain(cover) and (folder / cover).is_file():
        files[cover] = (folder / cover).read_bytes()
    song = _song_file(ctx, folder, info)
    if song is None:
        raise FileNotFoundError(f'譜面の音（{info.get("_songFilename")}）が見つかりません: {folder}')
    files[info['_songFilename']] = song
    return files, info


def rebuild(ctx, rep, folder):
    """リプレイの記録のノーツから、遊んだ難易度だけの譜面を組み立てる（音・カバー・ライト・NJS は folder の物）→ zip の中身"""
    files, info = _folder_files(ctx, folder)
    ri = rep['info']
    diff, mode = ri.get('difficulty') or 'ExpertPlus', ri.get('mode') or 'Standard'
    bpm = float(info.get('_beatsPerMinute') or 120)
    sets = info.get('_difficultyBeatmapSets') or []
    ent = next((bm for s in sets if s.get('_beatmapCharacteristicName') == mode for bm in s.get('_difficultyBeatmaps') or []
                if bm.get('_difficulty') == diff), None) or next(
        (bm for s in sets for bm in s.get('_difficultyBeatmaps') or [] if bm.get('_difficulty') == diff), None)
    lights = {}
    if ent and ent.get('_beatmapFilename') in files:   # ライトは今の書き出しの同じ難易度から借りる
        try:
            old = json.loads(files[ent['_beatmapFilename']].decode('utf-8-sig'))
            lights = {k: old[k] for k in ('basicBeatmapEvents', 'colorBoostBeatmapEvents', 'lightColorEventBoxGroups',
                                          'lightRotationEventBoxGroups', 'lightTranslationEventBoxGroups') if k in old}
        except ValueError:
            pass
    notes, bombs, seen = [], [], set()
    for n in sorted(rep['notes'], key=lambda n: n['spawn']):
        st, x, y, c, d = bsor.note_params(n['id'])
        b = round(n['spawn'] * bpm / 60, 4)
        key = (b, x, y, c if n['type'] != bsor.BOMB else -1)
        if key in seen:
            continue
        seen.add(key)
        if n['type'] == bsor.BOMB:
            bombs.append({'b': b, 'x': x, 'y': y})
        elif st not in bsor.CHAIN_LINKS:
            notes.append({'b': b, 'x': x, 'y': y, 'c': c, 'd': d, 'a': 0})
    dat = {'version': '3.2.0', 'bpmEvents': [], 'rotationEvents': [], 'colorNotes': notes, 'bombNotes': bombs, 'obstacles': [],
           'sliders': [], 'burstSliders': [], 'waypoints': [], 'basicBeatmapEvents': [], 'colorBoostBeatmapEvents': [],
           'lightColorEventBoxGroups': [], 'lightRotationEventBoxGroups': [], 'lightTranslationEventBoxGroups': [],
           'basicEventTypesWithKeywords': {}, 'useNormalEventsAsCompatibleEvents': True, **lights}
    fname = f'ANPReplay{diff}{mode}.dat'
    new_ent = dict(ent or {'_noteJumpMovementSpeed': 16, '_noteJumpStartBeatOffset': 0})
    new_ent.update({'_difficulty': diff, '_difficultyRank': DIFF_RANK.get(diff, 9), '_beatmapFilename': fname})
    for n in _beatmaps(info) or []:
        files.pop(n, None)
    info = dict(info, _difficultyBeatmapSets=[{'_beatmapCharacteristicName': mode, '_difficultyBeatmaps': [new_ent]}])
    files['Info.dat'] = json.dumps(info, ensure_ascii=False).encode('utf-8')
    files[fname] = json.dumps(dat, ensure_ascii=False).encode('utf-8')
    return files, len(notes)


def _replay_path(ctx, rid):
    i, _, name = str(rid or '').partition('/')
    dirs = replay_dirs(config.load(ctx.CONFIG))
    if not (i.isdigit() and int(i) < len(dirs) and plain(name) and name.lower().endswith('.bsor')):
        raise ValueError('リプレイが違います')
    f = dirs[int(i)] / name
    if not f.is_file():
        raise FileNotFoundError(f'リプレイが見つかりません: {name}')
    return f


def _anp_of(ctx, info):
    """リプレイが ANP の曲の物ならその (結果のファイル, _song_maps)・違えば None（hash が合う曲を先に）"""
    idx = _songs_index(ctx)
    h = (info.get('hash') or '').lower()
    return next(((p, sm) for p, sm in idx if h in sm['hashes']), None) or next(((p, sm) for p, sm in idx if _mine(info, sm)), None)


def open_replay(ctx, b):
    """POST /api/replays/open {id, file?}: file＝その曲（ANP の曲）として開く。無ければ全部の履歴から＝ANP の曲か見分け、ほかの譜面は
    手元の曲のフォルダ（同じ hash）・無ければ BeatSaver から取った zip（beatsaver_zip）"""
    f = _replay_path(ctx, b.get('id'))
    rep = bsor.read(f)
    info = rep['info']
    h = (info.get('hash') or '').lower()
    if b.get('file'):
        p = ctx.out_file(b['file'])
        hit = (p, _song_maps(ctx, p))
    else:
        hit = _anp_of(ctx, info)
    files = None
    if hit:
        src = _map_source(ctx, h, hit[1])
        if not src:
            raise FileNotFoundError('遊んだ時の譜面が見つかりません（この曲をまだ Beat Saber に書き出していない）')
        kind, where = src
        if kind == 'rebuild':
            files, n = rebuild(ctx, rep, where)
            note = (f'遊んだ時の譜面の控えが無い（控えを始める前に遊んで、その後に書き出し直した）ので、リプレイの記録のノーツ {n} 個から'
                    '組み立てました。壁・アーク・チェーンは出ません。音・ライト・NJS は今の書き出しの物です')
        else:
            files, _ = _folder_files(ctx, where)
            note = '遊んだ時の譜面（書き出しの控え）' if kind == 'saved' else '遊んだ時の譜面（Beat Saber の曲のフォルダ）'
    raw = None
    if not hit:
        d = local_level(config.load(ctx.CONFIG), info, getattr(ctx, 'CACHE', None))
        if d is not None:
            files, _ = _folder_files(ctx, d)
            kind, note = 'local', f'手元の譜面（Beat Saber の曲のフォルダ {d.name}・遊んだ時と同じ譜面）'
        else:
            raw = beatsaver_zip(h)
            if raw is None:
                raise FileNotFoundError('遊んだ時の譜面が手元にも BeatSaver にもありません（BeatSaver で消された・古い版・ネットに繋がっていない）')
            kind, note = 'beatsaver', '手元に遊んだ時の譜面が無いので、BeatSaver から取りました'
    tok = secrets.token_urlsafe(24)
    with _LOCK:
        _TOK[tok] = {'name': f.name, 'bsor': f, 'zip': raw if raw is not None else _zip(files), 'at': time.time()}
        for old in sorted(_TOK, key=lambda k: _TOK[k]['at'])[:-KEEP_TOKENS]:
            _TOK.pop(old, None)
    base = f'/blr/{tok}/'
    return {'link': base + f.name, 'mapLink': base + 'map.zip', 'source': kind, 'note': note}


def serve(path):
    """/blr/<鍵>/<リプレイのファイル名 | map.zip> → (バイト列, 種類) か None（鍵が違う・知らない名前）"""
    parts = path.split('/')
    if len(parts) != 4 or parts[1] != 'blr' or not TOKEN_RE.fullmatch(parts[2]):
        return None
    from urllib.parse import unquote
    name = unquote(parts[3])
    with _LOCK:
        t = _TOK.get(parts[2])
    if not t:
        return None
    if name == 'map.zip':
        return (t['zip'], 'application/zip') if t['zip'] is not None else None
    if name == t['name']:
        return t['bsor'].read_bytes(), 'application/octet-stream'
    return None


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})"""
    return ({'/api/replays': lambda q: list_replays(ctx, q), '/api/replays/all': lambda q: list_all(ctx, q),
             '/api/replays/cover': lambda q: cover(ctx, q)},
            {'/api/replays/open': lambda b: open_replay(ctx, b), '/api/replays/dir': lambda b: set_dir(ctx, b),
             '/api/replays/stars': lambda b: stars(ctx, b)})
