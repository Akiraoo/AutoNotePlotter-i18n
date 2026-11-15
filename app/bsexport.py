"""Beat Saber へ直接書き出す（docs/アプリ仕様.md 22 節・2026-11-03 利用者「直通の経路も用意しよう・不足するマッパーとかの情報も入れられる
ように・プレイリストにまとめて入れたい」）。NLM の形式（.nlmf）を作るのは今まで通り（NLM で開くかは使う人が決める）。

書き出しの中身は automap/bs_export.py（NLM の書き出しの計算の写し）。ここは受け口・書き出し先（CustomLevels）とプレイリストの場所の
候補・前回の書き出しの記録（<out>/.export/<結果のファイル>.json）。プレイリストは automap/playlist.py。
画面で入れた曲の情報（マッパー名など）は .nlmf にも書く（NLM で開いても同じに見える・bs_export.apply_info）。結果のファイルが
アプリの書いたままの時だけ、書いた後の指紋（out/.state）を記録し直す（NLM で直された印を消さない）。

カバー画像（2026-11-09 利用者「カバー画像が見えるように・ここから変更できるように（取り込みの時と同じ）」）: 窓に今のカバーと候補を出し
（cover_view）、選ぶとすぐ結果のファイルに入れる（set_cover＝画像は取り込みと同じく結果のファイルの隣へ写す・new_project.set_cover の
決まり・.nlmf へは書き出しに繋がったカバーのノードと coverData＝bs_export.apply_info）。選べるのは取り込みの窓と同じく、サーバーが
見せてよいと覚えた画像だけ（importer._SEEN＝候補・ファイルの窓で選んだ物・貼り付けた物）。

受け口（server.connect が routes(ctx) をつなぐ）:
  GET  /api/bsexport/plan?file=        → 書き出しの窓の中身（covers＝カバーの様子と候補）
  GET  /api/bsexport/cover?file=       → 今のカバーの画像（書き出しに使う物＝実パスの画像か .nlmf に入っている画像）
  POST /api/bsexport/cover {file, path} → カバーを変える（結果のファイルに入れる）→ {ok, plan（窓の中身を読み直した物）}
  POST /api/bsexport/settings {levels_dir?, playlists_dir?, mapper_name?}
  POST /api/bsexport/run {file, changes, folder, diffs, playlist: {file} か {title}（新しく作る）か null, save_info}
"""
import hashlib
import json
import re
import os
import string
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from automap import config  # noqa: E402
from automap import nlmf  # noqa: E402
from automap import playlist as PL  # noqa: E402

KIND = 'bsexport'


def _bs():
    from automap import bs_export   # NLM の書き出しの写し（無い版でも画面は開ける）
    return bs_export


# ---- Beat Saber のフォルダ ----

def playlists_for(levels):
    """CustomLevels の場所 → プレイリストの場所（BSManager の共有＝SharedContent\\Playlists・ゲームのフォルダ＝<Beat Saber>\\Playlists）"""
    p = Path(levels)
    if p.name.lower() == 'customlevels' and p.parent.name.lower() == 'sharedmaps':
        return p.parent.parent / 'Playlists'
    if p.name.lower() == 'customlevels' and p.parent.name.lower() == 'beat saber_data':
        return p.parent.parent / 'Playlists'
    return p.parent / 'Playlists'


def _steam_libraries():
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            roots.append(Path(winreg.QueryValueEx(k, 'SteamPath')[0]))
    except OSError:
        pass
    roots.append(Path(r'C:\Program Files (x86)\Steam'))
    libs = []
    for r in roots:
        vdf = r / 'steamapps' / 'libraryfolders.vdf'
        try:
            text = vdf.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.strip().split('"')
            if len(parts) >= 4 and parts[1] == 'path':
                libs.append(Path(parts[3].replace('\\\\', '\\')))
        libs.append(r)
    return libs


def _oculus_libraries():
    libs = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Oculus VR, LLC\Oculus\Libraries') as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as s:
                        libs.append(Path(winreg.QueryValueEx(s, 'OriginalPath')[0]))
                except OSError:
                    pass
    except OSError:
        pass
    return libs


def candidates(cfg=None):
    """Beat Saber のフォルダの候補 → [{levels, playlists, kind}]（あるフォルダだけ・同じ物は1つ）"""
    cfg = config.load() if cfg is None else cfg
    found = []

    def add(levels, kind, playlists=None):
        levels = Path(levels)
        if levels.is_dir() and not any(Path(x['levels']) == levels for x in found):
            found.append({'levels': str(levels), 'playlists': str(playlists or playlists_for(levels)), 'kind': kind})

    if cfg.get('bs_levels'):
        add(cfg['bs_levels'], '設定', cfg.get('bs_playlists'))
    if cfg.get('custom_levels'):
        add(cfg['custom_levels'], '型のライブラリの設定')
    drives = [f'{c}:\\' for c in string.ascii_uppercase if os.path.exists(f'{c}:\\')]
    for base in [Path.home()] + [Path(d) for d in drives]:
        add(base / 'BSManager' / 'SharedContent' / 'SharedMaps' / 'CustomLevels', 'BSManager')
    for lib in _steam_libraries():
        add(lib / 'steamapps' / 'common' / 'Beat Saber' / 'Beat Saber_Data' / 'CustomLevels', 'Steam')
    for lib in _oculus_libraries():
        add(lib / 'Software' / 'hyperbolic-magnetism-beat-saber' / 'Beat Saber_Data' / 'CustomLevels', 'Oculus（Meta）')
    return found


def dest_state(cfg):
    """書き出し先の今の設定 → {levels, playlists, ok, why}"""
    lv, pl = cfg.get('bs_levels'), cfg.get('bs_playlists')
    if not lv:
        c = candidates(cfg)
        if c:
            lv, pl = c[0]['levels'], c[0]['playlists']
    if not lv:
        return {'levels': None, 'playlists': None, 'ok': False, 'why': 'Beat Saber の曲のフォルダ（CustomLevels）が見つかりません。場所を選んでください'}
    ok = Path(lv).is_dir()
    return {'levels': str(lv), 'playlists': str(pl or playlists_for(lv)), 'ok': ok,
            'why': None if ok else f'Beat Saber の曲のフォルダが見つかりません: {lv}'}


# ---- 前回の書き出しの記録 ----

def _rec_path(ctx, file):
    return Path(ctx.OUT) / '.export' / (Path(file).name + '.json')


def last_export(ctx, file):
    try:
        return json.loads(_rec_path(ctx, file).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


# ---- 書き出し ----

def plan(ctx, file):
    p = ctx.out_file(file)
    cfg = config.load(ctx.CONFIG)
    try:
        bs = _bs()
        pl_ = bs.plan(p)
        err = None
    except ImportError:
        pl_, err = None, '直接書き出す部品（automap/bs_export.py）がまだありません'
    except Exception as e:   # noqa: BLE001  （読めない .nlmf 等）
        pl_, err = None, str(e)
    dest = dest_state(cfg)
    if not cfg.get('bs_levels') and pl_ and pl_.get('dest') and Path(pl_['dest']).is_dir():   # NLM で決めた書き出し先
        dest = {'levels': str(pl_['dest']), 'playlists': str(playlists_for(pl_['dest'])), 'ok': True, 'why': None}
    last = last_export(ctx, file)
    if pl_ is not None and pl_['info'].get('songSubName') in ('意思入れ', '試作5', '試作4'):   # 前に作り直しが既定で入れていたサブタイトル（2026-11-09 利用者「消して」）は空で出す
        pl_['info']['songSubName'] = ''
    if pl_ is not None and not pl_['info'].get('levelAuthorName') and cfg.get('mapper_name'):
        pl_['info']['levelAuthorName'] = cfg['mapper_name']   # 前に入れたマッパー名（入れる欄の初めの値）
        pl_['mapper_from_settings'] = True
    gain = None
    try:
        gain = _bs().gain_db(_bs().song_node(nlmf.load(p)))
    except Exception:   # noqa: BLE001
        pass
    covers = None
    try:
        covers = cover_view(ctx, p)
    except Exception:   # noqa: BLE001  （カバーの様子は出せなくても書き出しの窓は開く）
        pass
    return {'file': Path(p).name, 'plan': pl_, 'error': err, 'dest': dest, 'candidates': candidates(cfg),
            'loudness': {'on': bool(cfg.get('bs_loudness')), 'limiter': bool(cfg.get('bs_limiter')), 'gain_db': gain},
            'playlists': PL.list_playlists(dest['playlists']) if dest['playlists'] else [],
            'playlist_last': cfg.get('bs_playlist_last'), 'mapper_name': cfg.get('mapper_name') or '', 'last': last,
            'default_playlist': {'file': PL.DEFAULT_FILE, 'title': PL.DEFAULT_TITLE}, 'covers': covers}


# ---- カバー画像（見せる・変える） ----

def _seen():
    """画面に見せてよい・カバーに選んでよい画像の集まり（取り込みの窓と同じ物＝app/importer._SEEN）"""
    import importer   # noqa: E402  （app/ の中）
    return importer._SEEN


def _current_cover(p):
    """結果のファイルの今のカバー（書き出しに使う物）→ bs_export.cover_source の答え（{'name','data','path',...}）か None"""
    bs = _bs()
    proj = nlmf.load(p)
    return bs.cover_source(proj, bs.info_graph(proj))


def _placed_covers(p):
    """結果のファイルの隣の、この曲のカバーの画像（<曲>.jpg・<曲>.cover2.png 等＝取り込み・この窓で入れた物）"""
    from automap import new_project as NP
    song = p.name.split('.')[0]
    pat = re.compile(re.escape(song) + r'(\.cover\d*)?\.(jpe?g|png)$', re.I)
    try:
        return sorted((q for q in p.parent.iterdir() if q.is_file() and pat.fullmatch(q.name) and q.suffix.lower() in NP.IMAGE_EXTS),
                      key=lambda q: -q.stat().st_mtime)
    except OSError:
        return []


def cover_view(ctx, p, limit=8):
    """窓に出すカバーの様子 → {now: 今のカバーのファイルの場所（.nlmf に入っているだけの時は ''・無ければ None）, name, size: [幅, 高さ] か None,
    cands: ほかに選べる画像（結果のファイルの隣の前のカバー・音源のフォルダの Cover.jpg 等。今のカバーと同じ中身の物は除く）}。
    出す画像は画面に見せてよい画像に足す（/api/import/cover で出せる・POST /api/bsexport/cover で選べる）"""
    from automap import new_project as NP
    p = Path(p)
    bs = _bs()
    proj = nlmf.load(p)
    cur = bs.cover_source(proj, bs.info_graph(proj))
    seen = _seen()
    digests = {hashlib.sha1(cur['data']).hexdigest()} if cur else set()
    now = None
    if cur:
        now = str(Path(cur['path'])) if cur['path'] else ''
        if now:
            seen.add(now)
    cands = []
    audio = bs.audio_path(proj)
    pool = [str(q) for q in _placed_covers(p)] + (NP.cover_candidates(audio) if audio and Path(audio).is_file() else [])
    for c in pool:
        c = str(Path(c))
        if len(cands) >= limit or c == now or c in cands:
            continue
        try:
            d = hashlib.sha1(Path(c).read_bytes()).hexdigest()
        except OSError:
            continue
        if d in digests:
            continue
        digests.add(d)
        cands.append(c)
        seen.add(c)
    wh = bs.image_size(cur['data']) if cur else None
    return {'now': now, 'name': (Path(cur['path']).name if cur and cur['path'] else (cur['name'] if cur else '')),
            'size': list(wh) if wh else None, 'cands': cands}


def cover_image(ctx, q):
    """今のカバーの画像 → (バイト, Content-Type)"""
    cur = _current_cover(ctx.out_file(q['file']))
    if not cur:
        raise FileNotFoundError('カバー画像が無い')
    d = cur['data']
    ctype = 'image/png' if d[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg' if d[:3] == b'\xff\xd8\xff' else 'application/octet-stream'
    return d, ctype


def set_cover(ctx, b):
    """カバーを変える: 選んだ画像を取り込みと同じ決まりで結果のファイルの隣へ写し（<曲>.jpg・中身が違う同じ名前の物があれば <曲>.cover.jpg …＝
    上書きしない・new_project.set_cover）、結果のファイルの書き出しに繋がったカバーのノード（名前と実パス）・coverData・曲の流れの画面の
    カバーのノードに入れる（bs_export.apply_info＝NLM で選んだのと同じ形・NLM で開いても同じカバー）。元のプロジェクトは書き換えない"""
    from automap import new_project as NP
    p = ctx.out_file(b['file'])
    if not p.exists():
        raise FileNotFoundError(f'結果のファイルが無い: {p.name}')
    if ctx.busy(p.name):
        raise ValueError('この曲は今作り直しているか書き出している（終わってから変える）')
    src = str(Path(str(b.get('path') or '').strip().strip('"')))
    if not b.get('path') or src not in _seen() or not Path(src).is_file():
        raise ValueError('カバー画像は候補か「別の画像…」・貼り付けで選んだ物')
    if Path(src).suffix.lower() not in NP.IMAGE_EXTS:
        raise ValueError('カバー画像は jpg・png')
    # 置き場所の決まりは取り込みと同じ（new_project.set_cover が写す。その関数が中身に入れる所は使わない＝下の apply_info が
    # 書き出しに繋がったノードへ入れる）
    dst = NP.set_cover({}, p, src, stem=p.name.split('.')[0])
    _edit(ctx, p, lambda proj: _bs().apply_info(proj, {'cover': str(dst)}))
    _seen().add(str(Path(dst)))
    return {'ok': True, 'cover': str(dst), 'plan': plan(ctx, p.name)}


def set_settings(ctx, b):
    ch = {}
    if 'levels_dir' in b:
        v = str(b['levels_dir'] or '').strip().strip('"')
        if v and not Path(v).is_dir():
            raise ValueError(f'そのフォルダは見つかりません: {v}')
        ch['bs_levels'] = v or None
        if v and 'playlists_dir' not in b:
            ch['bs_playlists'] = str(playlists_for(v))
    if 'playlists_dir' in b:
        v = str(b['playlists_dir'] or '').strip().strip('"')
        if v and not Path(v).is_dir():   # 曲のフォルダと同じく、あるフォルダだけ（前は何も確かめずに設定へ書いた・F10）
            raise ValueError(f'そのフォルダは見つかりません: {v}')
        ch['bs_playlists'] = v or None
    if 'mapper_name' in b:
        ch['mapper_name'] = str(b['mapper_name'] or '').strip()[:100] or None
    config.update(ch, ctx.CONFIG)
    return {'ok': True, 'dest': dest_state(config.load(ctx.CONFIG))}


def _save_info(ctx, p, changes):
    """画面で入れた曲の情報を .nlmf に書く。アプリの書いたままだった時だけ、書いた後の指紋を記録し直す"""
    _edit(ctx, p, lambda proj: _bs().apply_info(proj, changes))


def _edit(ctx, p, fn):
    """.nlmf を読んで fn(proj) で直して書く。アプリの書いたままだった時だけ、書いた後の指紋を記録し直す（NLM で直した扱いにしない）。
    書く前の中身が履歴の版なら、書いた後の中身も同じ版とみなす（versions.adopt＝次の作り直しの前に「アプリの外で作り直した版」を控えない）"""
    as_written = p.exists() and not ctx.cli._edited_since_written(p)
    before = ctx.cli._sha(p) if p.exists() else None
    proj = nlmf.load(p)
    fn(proj)
    nlmf.save(proj, p)
    if as_written:
        sp = ctx.cli._state_path(p)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({'sha256': ctx.cli._sha(p), 'savedAt': proj.get('savedAt')}), encoding='utf-8')
    try:
        import versions
        versions.adopt(p, before)
    except Exception:   # noqa: BLE001  （履歴の印を直せなくても書き出しは続ける＝前と同じく次の作り直しで控えるだけ）
        pass


def normalize(p, log=print):
    """曲の音量をそろえる（automap/loudness.py＝NLM の「自動調整」と同じ）: 書き出す song.egg に入る所の元の音源を測り、自動の補正の値を
    返す → (補正 dB, 測った値, 理由) か None（音源が無い・測れない形式）。.nlmf は書き換えない（start の段が書く）"""
    from automap import loudness
    bs = _bs()
    proj = nlmf.load(p)
    src = bs.audio_path(proj)
    if not src or not Path(src).is_file():
        log('音量: 音源が見つからないので、そろえない（今の補正のまま）')
        return None
    try:
        n, sr = bs.audio_frames(src)
        pieces = bs.music_pieces(proj, nlmf.tempo_of(proj), n / sr)
        m = loudness.measure_file(src, [(a, b) for a, b, _ in pieces] or None)
    except Exception as e:   # noqa: BLE001  （soundfile で読めない形式など）
        log(f'音量: この音源は測れないので、そろえない（今の補正のまま・{e}）')
        return None
    a = loudness.auto_gain(m)
    return a['db'], m, loudness.BY_TEXT.get(a['by'], a['by'])


def _bplist_name(name):
    """プレイリストのファイル名として書いてよいか: 1 つの名前だけで .bplist（窓の一覧＝PL.list_playlists・新しく作る＝PL.safe_file の形）。
    前は最後の 1 段に切るだけで、どんな拡張子でも書いた＝スタートアップのフォルダに .bat を書かれた（セキュリティのスキャンの F10）"""
    s = str(name or '')
    bad = any(c in '/\\:*?"<>|' or ord(c) < 32 for c in s)   # Windows で使えない字・区切り・ドライブ名（PL.safe_file と同じ字）
    return not bad and s.lower().endswith('.bplist') and len(s) > len('.bplist') and s.strip(' .') == s


def start(ctx, b):
    p = ctx.out_file(b['file'])
    if not p.exists():
        raise FileNotFoundError(f'結果のファイルが無い: {p.name}')
    if ctx.busy(p.name):
        raise ValueError('この曲は今作り直している（終わってから書き出す）')
    cfg = config.load(ctx.CONFIG)
    dest = dest_state(cfg)
    if b.get('levels'):   # 窓で選んだ曲のフォルダ（.nlmf に NLM で決めた書き出し先・候補・選んだ物）
        lv = Path(str(b['levels']).strip().strip('"'))
        if not lv.is_dir():
            raise ValueError(f'Beat Saber の曲のフォルダが見つかりません: {lv}')
        dest = {'levels': str(lv), 'playlists': str(Path(cfg['bs_playlists']) if cfg.get('bs_playlists') and str(lv) == cfg.get('bs_levels')
                                                     else playlists_for(lv)), 'ok': True, 'why': None}
    if not dest['ok']:
        raise ValueError(dest['why'])
    changes = {k: v for k, v in (b.get('changes') or {}).items() if v is not None}
    folder = _bs().sanitize_folder(b.get('folder'))   # NLM と同じ決まり（英数字と一部の記号だけ）
    if not folder or folder in ('.', '..'):
        raise ValueError('書き出すフォルダ名が空です（英数字と - _ . ( ) [ ] & \' ! + , が使えます）')
    diffs = b.get('diffs') or None
    pl_req = b.get('playlist')
    if pl_req and pl_req.get('file') and not _bplist_name(pl_req['file']):
        raise ValueError(f'プレイリストのファイル名が違います（.bplist だけ）: {pl_req["file"]}')
    loud, lim = b.get('loudness'), b.get('limiter')
    if loud is not None or lim is not None:   # 次の曲でも同じ（2026-11-08）
        config.update({k: bool(v) for k, v in (('bs_loudness', loud), ('bs_limiter', lim)) if v is not None}, ctx.CONFIG)
    from automap import loudness as LD
    limiter = (LD.AUTO_TARGET_LUFS, LD.AUTO_PEAK_DB) if (loud and lim) else None
    bs = _bs()
    res = {}

    def set_loudness(job):
        say = lambda s: job.__setitem__('log', job['log'] + s + '\n')
        r = normalize(p, say)
        if r is None:
            return
        db, m, why = r
        old = bs.gain_db(bs.song_node(nlmf.load(p)))

        def put(proj):
            sn = bs.song_node(proj)
            if sn is None:
                return
            if db:
                sn['gainDb'] = db
            else:
                sn.pop('gainDb', None)
        if db != old:
            _edit(ctx, p, put)
        say(f'音量: 平均 {m["lufs"]:.1f} LUFS・一番大きい瞬間 {m["peak_db"]:.1f} dB → 補正 {db:+.1f} dB（{why}'
            + (f'・前は {old:+.1f} dB' if db != old else '') + '）。.nlmf の音量補正にも書いた（NLM の「自動調整」と同じ値）')

    def save_info(job):
        if b.get('save_info', True) and (changes or folder):
            _save_info(ctx, p, dict(changes, folder=folder))
            job['log'] += '曲の情報を .nlmf にも書いた（NLM で開いても同じ）\n'
        if changes.get('levelAuthorName'):
            config.update({'mapper_name': changes['levelAuthorName']}, ctx.CONFIG)   # 次の曲の初めの値

    def write(job):
        r = bs.write(p, dest['levels'], folder=folder, changes=changes, diffs=diffs,
                     log=lambda s: job.__setitem__('log', job['log'] + str(s).rstrip('\n') + '\n'), cancel=lambda: job.get('cancel'),
                     limiter=limiter)
        res.update(r)
        li = r.get('limiter')
        if li:   # リミッターの結果（song.egg を作り直した時だけ）
            b0 = li['before']
            job['log'] += (f'リミッター: 掛けなかった（平均 {b0["lufs"]:.1f} LUFS＝もう十分大きいか、抑えても上がらない）\n' if li.get('skipped') else
                           f'リミッター: 平均 {b0["lufs"]:.1f} → {li["lufs"]:.1f} LUFS・一番大きい瞬間 {b0["peak_db"]:.1f} → {li["peak_db"]:.1f} dB'
                           f'（上げた {li["gain_db"]:+.1f} dB・一番大きく抑えた所 {li["reduced_db"]:.1f} dB'
                           + ('・抑える量の上限で止めた' if li.get('capped') else '') + '）。この書き出しの song.egg だけ（NLM で書き出す時は入らない）\n')
        job['result'] = {'dir': r['dir'], 'hash': r['hash'], 'files': [Path(f).name for f in r['files']], 'warnings': r.get('warnings') or []}

    def add_playlist(job):
        if not pl_req:
            return
        pdir = Path(dest['playlists'])
        if pl_req.get('file'):
            path = pdir / pl_req['file']   # start で確かめた名前（_bplist_name）
        else:   # 新しく作る（既定の題名なら既定のファイル名＝窓の一覧の「Auto Note Plotter」と同じファイル）
            title = (pl_req.get('title') or PL.DEFAULT_TITLE).strip()
            path = pdir / (PL.DEFAULT_FILE if title == PL.DEFAULT_TITLE else PL.safe_file(title))
        cover = None
        try:
            cover = bs.plan(p)['info'].get('cover')
        except Exception:   # noqa: BLE001
            pass
        ent = PL.entry(res['hash'], res.get('song_name'), res.get('level_author'),
                       [(d['characteristic'], d['name']) for d in res.get('difficulties') or []], folder)
        r = PL.add_song(path, ent, title=pl_req.get('title') or PL.DEFAULT_TITLE, author=res.get('level_author') or PL.DEFAULT_TITLE,
                        image=PL.image_b64(cover))
        job['playlist'] = r
        job['log'] += f'プレイリスト「{r["title"]}」に{"入れ直した" if r["replaced"] else "入れた"}（{r["songs"]} 曲）\n'
        config.update({'bs_playlist_last': path.name}, ctx.CONFIG)

    def after(job):
        if job['state'] == 'done':
            rp = _rec_path(ctx, p)
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'dir': res.get('dir'), 'folder': folder, 'hash': res.get('hash'),
                                      'playlist': job.get('playlist')}, ensure_ascii=False), encoding='utf-8')
            try:   # 書き出した譜面を hash ごとに控える＝後で書き出し直しても、前の版で遊んだリプレイを遊んだ時の譜面で見られる（app/replays.py）
                import replays
                replays.keep_export(ctx, p, res)
            except Exception as e:   # noqa: BLE001  （控えられなくても書き出しは済んでいる）
                job['log'] += f'リプレイ用の譜面の控えを作れなかった: {e}\n'

    steps = ([('曲の情報を書く', save_info)] + ([('音量をそろえる', set_loudness)] if loud else []) + [('Beat Saber に書き出す', write)]
             + ([('プレイリストに入れる', add_playlist)] if pl_req else []))
    job = ctx.start_job(p.name, steps, kind=KIND, after=after, dest=dest['levels'], folder=folder)
    return {'id': job['id']}


def routes(ctx):
    get = {'/api/bsexport/plan': lambda q: plan(ctx, q['file']),
           '/api/bsexport/cover': lambda q: cover_image(ctx, q)}
    post = {'/api/bsexport/settings': lambda b: set_settings(ctx, b), '/api/bsexport/run': lambda b: start(ctx, b),
            '/api/bsexport/cover': lambda b: set_cover(ctx, b)}
    return get, post
