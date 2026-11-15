"""譜面づくりのアプリ（docs/アプリ仕様.md）の手元のサーバー。ブラウザの画面（app/static/）と、曲のデータ・分けた音・作業ファイル・作り直しを受け持つ。

使い方: .venv/Scripts/python.exe app/server.py [--port 8765] [--no-browser]（app/start.bat）
  → http://127.0.0.1:8765/ がブラウザで開く。止めるのは app/stop.bat・画面の「終わる」・Ctrl+C。
  窓のアプリ（pywebview の窓・同じプロセスでこのサーバーを動かす）は app/desktop.py（app/譜面づくり.bat）。

- 曲: out/<曲名>.*.nlmf（結果のファイル）と cache/<曲名>/（分けた音）がそろっている物。アプリが作り直すファイルは out/<曲名>.intent-s1.nlmf。
  まだ無い曲は、試作5（style-s1）か v0.1（compose-s1）を土台にして最初の作り直しで作る。
- 作業ファイル: 結果のファイルの隣に同じ名前で `<…>.automap.json`（意思入れ・量のライン・自動の休み）。
- 難易度（docs/アプリ仕様.md 17 節）: 意思入れ・作り直し・別の案・履歴・区間の点検は曲の基準の難易度（作業ファイルの diff・既定 Expert+）。
  ほかの難易度（派生）は見るだけ（/api/chart?diff=・/api/rating?diff=・3D）。曲のデータの diffs＝ある難易度の一覧・base＝基準。
- 作り直し: `python -m automap compose <結果のファイル> --stems cache/<曲> --form --style --intent <作業ファイルから作った表> --out <結果のファイル>`
  を別のプロセスで動かす（1回 30〜60 秒）。NLM で直した所は compose が残す（CLAUDE.md の NLM とのやり取りの決まり）。
- 外から触られないように 127.0.0.1 だけで待ち、Host・Origin を確かめ、画面の部品の外は起動ごとの合言葉を求める（下の「出入りの守り」）。
  書き換える要求（POST・PUT）には前からの `X-Automap: 1` の頭も求める。
"""
import argparse
import errno
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlsplit

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / 'static'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from automap import config  # noqa: E402  （設定の置き場所・作業の場所）
OUT, CACHE = config.out_dir(), config.cache_dir()   # 作業の場所（設定の work_dir・無ければリポジトリの out/・cache/）
from automap import nlmf  # noqa: E402
from automap import rating_scale  # noqa: E402  （★の物差し・前の境目の読み替え）
from automap import diffs  # noqa: E402  （難易度の名前・基準と派生）
from automap import lazy, written  # noqa: E402,F401
# 重い部品（作る処理＝scipy 等・曲のデータを作る部品 app/songdata.py）は使う時に読む（起動を速く・2026-11-09・automap/lazy.py）。
# NLM で直したかの判定（cli._edited_since_written・_state_path・_sha・_save）は軽い automap/written.py から（重い側を読まない）
cli = lazy.Module('automap.__main__', light='automap.written')
songdata = lazy.Module('songdata')   # 曲のデータ（app/songdata.py・numpy・soundfile・曲の中身の解析を読む）
import songcache  # noqa: E402  （曲のデータのディスクの控え・app/songcache.py）
from names import plain, rel_parts  # noqa: E402,F401  （受け取った名前はファイルに触る前に確かめる・app/names.py）


STEMS = ('vocals', 'drums', 'bass', 'other')
APP_KIND = 'intent-s1'            # アプリが作り直す結果のファイル
BASE_KINDS = ('style-s1', 'compose-s1')   # まだ無い時の土台（この順に探す）
CONFIG = config.path()   # 設定（開発の PC は app/config.local.json・配布物は <LOCALAPPDATA>/AutoNotePlotter/config.json）

mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('audio/flac', '.flac')


# ---- 出入りの守り（2026-11-11・セキュリティのスキャン CLAUDE-SECURITY-20261111-045144 の F1・F7・F9・F12・NLM の serve.py と同じ考え） ----
# 127.0.0.1 だけで待っても、次の 3 つは届く: (1) DNS リバインディング（攻撃者の名前を 127.0.0.1 へ向け直したページ＝同じオリジンになり
# 頭を自由に付けられる）・(2) 同じ PC の別のアカウントのプログラム・(3) ほかのサイトのページの <img> 等の GET（頭を付けずに送れる）。
#  ① Host の頭がこの PC の名前（HOSTS）でなければ断る（1）
#  ② Origin の頭が付いていて、このサーバー（同じ名前と番号）でなければ断る（念のための二重化）
#  ③ 画面の部品（/・/static/）のほかは、起動ごとの合言葉（TOKEN）を頭 X-Automap-Key で求める（2・3）。画面へは URL の #k=… で渡し
#     （main・窓のアプリが付ける＝access_url）、static/js/key.js が同じサーバーへの fetch・XHR に付ける。<audio>・<img> は頭を付けられない
#     ので、音とカバー画像（KEY_QUERY）だけ ?k= でも受ける。Cookie では渡さない（127.0.0.1 の Cookie は番号を区別しない＝同じ PC の
#     ほかの番号のページへも送られる）。
#  ④ 書き換える要求（POST・PUT）は前からの頭 X-Automap: 1 も求める。
# 合言葉は、サーバーを別のプロセスで起こす確かめの道具が環境変数 AUTOMAP_TOKEN で決めてもよい（tools/dist/checkset.py 等）。
# app/stop.bat と窓のアプリの二重起動の確かめのため、main・窓のアプリは合言葉を使う人だけが読める場所（key_file）に書き、止める時に消す。
_ENV_TOKEN = os.environ.get('AUTOMAP_TOKEN') or ''   # 決めるなら secrets.token_urlsafe(32) の形（英数字と - _ で 32 字以上）
TOKEN = _ENV_TOKEN if re.fullmatch(r'[A-Za-z0-9_-]{32,}', _ENV_TOKEN) else secrets.token_urlsafe(32)
HOSTS = ('127.0.0.1', 'localhost')
KEY_HEADER = 'X-Automap-Key'
KEY_QUERY = ('/audio/', '/api/bsexport/cover', '/api/import/cover', '/api/replays/cover')   # ?k= でも受ける GET（<audio>・<img> の src）


def access_url(port, host='127.0.0.1'):
    """合言葉付きの、画面を開く URL"""
    return f'http://{host}:{port}/#k={TOKEN}'


def key_file(port):
    """合言葉を書く場所（使う人ごとの <LOCALAPPDATA>/AutoNotePlotter/session/<番号>.key・ほかのアカウントは読めない）"""
    return config.app_dir() / 'session' / f'{port}.key'


def write_key(port):
    f = key_file(port)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(TOKEN, encoding='ascii')
    return f


def drop_key(port):
    """止める時に消す（ほかのサーバーが同じ番号で書き直した物は消さない）"""
    f = key_file(port)
    try:
        if f.read_text(encoding='ascii').strip() == TOKEN:
            f.unlink()
    except OSError:
        pass


def _hostname(hostport):
    """'127.0.0.1:8765'・'[::1]:8765'・'localhost' → 名前の部分（小文字）"""
    hp = (hostport or '').strip().lower()
    if hp.startswith('['):
        return hp[1:hp.find(']')] if ']' in hp else hp[1:]
    return hp.rsplit(':', 1)[0] if hp.count(':') == 1 else hp


# ---- 曲と結果のファイル ----

def songs():
    """曲の一覧: 分けた音があり、アプリの結果のファイルか土台（試作5・v0.1）がある曲（元のプロジェクトだけの曲＝取り込みの途中・
    最初の譜面に失敗した曲は出さない＝開くと「土台が無い」になる）"""
    by = {}
    for p in sorted(OUT.glob('*.nlmf')):
        name = p.name.split('.')[0]
        if (CACHE / name / 'separate.json').exists():
            by.setdefault(name, []).append(p)
    out = []
    with _META_LOCK:
        _meta_open()
        for name, files in by.items():
            app = OUT / f'{name}.{APP_KIND}.nlmf'
            base = app if app.exists() else next((OUT / f'{name}.{k}.nlmf' for k in BASE_KINDS if (OUT / f'{name}.{k}.nlmf').exists()), None)
            if base is None:
                continue
            m = _song_meta(base)
            out.append({'song': name, 'app_file': app.name, 'app_exists': app.exists(), 'base_file': base.name,
                        'files': [{'file': f.name, 'mtime': f.stat().st_mtime} for f in files],
                        # 曲を選ぶ窓（js/songpick.js）: 曲名・アーティスト・カバーの有無は結果のファイル（無ければ土台）の曲の情報・
                        # mtime＝そのファイルの更新時刻・cover_v＝カバーの画像の URL に付ける印（ファイルが変われば変わる）・archived＝作業ファイルの印
                        'title': m['title'] or name, 'artist': m['artist'], 'cover': m['cover'], 'cover_v': m['k'][0] if m['k'] else 0,
                        'mtime': base.stat().st_mtime, 'archived': _archived(app)})
        _meta_close({f'{x["song"]}.{k}.nlmf' for x in out for k in (APP_KIND, *BASE_KINDS)}, {work_path(OUT / x['app_file']).name for x in out})
    return out


# ---- 曲を選ぶ窓の曲の情報（曲名・アーティスト・カバーの有無・アーカイブの印）の控え ----
# 1 回読んだら（ファイルの名前 → 更新時刻・大きさ）で覚え、変わった時だけ読み直す（1 曲 5〜10ms・曲が 100 曲になっても一覧を速く出す）。
# 控えは <OUT>/.songlist.json（作業の場所の中の隠しファイル＝作業の場所ごと・引っ越し（relocate.py）でも一緒に動く・消しても読み直すだけ）。
# 起動して最初の一覧（画面の起動のたびに読む）でも全部の曲を読み直さないように、ファイルにも置く
SONGLIST_FILE = '.songlist.json'
_META = {'out': None, 'nlmf': {}, 'work': {}, 'dirty': False}
_META_LOCK = threading.RLock()


def _stat_key(p):
    try:
        st = p.stat()
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


def _meta_open():
    """控えを今の作業の場所のファイルから読む（作業の場所が変わった時・初めて）"""
    if _META['out'] == str(OUT):
        return
    _META.update(out=str(OUT), nlmf={}, work={}, dirty=False)
    try:
        d = json.loads((OUT / SONGLIST_FILE).read_text(encoding='utf-8'))
        if d.get('v') == 1:
            _META['nlmf'], _META['work'] = dict(d.get('nlmf') or {}), dict(d.get('work') or {})
    except (OSError, ValueError, AttributeError):
        pass


def _meta_close(names, works):
    """無くなったファイルの控えを捨て、変わっていればファイルに書く（書けなくても一覧は出す）"""
    for tab, keep in ((_META['nlmf'], names), (_META['work'], works)):
        for k in [k for k in tab if k not in keep]:
            del tab[k]
            _META['dirty'] = True
    _meta_flush()


def _meta_flush():
    if not _META['dirty']:
        return
    try:
        f = OUT / SONGLIST_FILE
        tmp = f.with_name(f.name + '.tmp')
        tmp.write_text(json.dumps({'v': 1, 'nlmf': _META['nlmf'], 'work': _META['work']}, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, f)
        _META['dirty'] = False
    except OSError:
        pass


def read_song_info(p):
    """結果のファイル → {title, artist, cover}: 書き出しの曲の情報（NLM の INFO の図の、書き出しに繋がった曲の情報・カバーのノード＝
    書き出しの窓 app/bsexport.py と同じ automap/bs_export の読み方）。読めなければ .nlmf の info（_songName・_songAuthorName）"""
    proj = nlmf.load(p)
    info = proj.get('info') if isinstance(proj.get('info'), dict) else {}
    title, artist, cover = info.get('_songName') or '', info.get('_songAuthorName') or '', False
    try:
        from automap import bs_export as bs
        ig = bs.info_graph(proj)
        ib, _ = bs.info_base(proj, ig)
        title, artist = ib.get('_songName') or title, ib.get('_songAuthorName') or artist
        cover = bs.cover_source(proj, ig) is not None
    except Exception:   # noqa: BLE001  （古い形の INFO の図・書き出しの部品が無い版でも一覧は出す）
        pass
    return {'title': str(title).strip(), 'artist': str(artist).strip(), 'cover': bool(cover)}


def _song_meta(p):
    """結果のファイル（か土台）の曲の情報（控えから・変わっていれば読み直す）→ {title, artist, cover, k}"""
    k = _stat_key(p)
    got = _META['nlmf'].get(p.name)
    if got and got.get('k') == k:
        return got
    try:
        m = dict(read_song_info(p), k=k)
    except Exception:   # noqa: BLE001  （読めない .nlmf も一覧には出す＝開くと訳が出る）
        m = {'title': '', 'artist': '', 'cover': False, 'k': k}
    _META['nlmf'][p.name] = m
    _META['dirty'] = True
    return m


def _archived(app):
    """曲のアーカイブの印（作業ファイルの archived・曲を選ぶ窓が付ける）。作業ファイルが無ければ False"""
    wp = work_path(app)
    k = _stat_key(wp)
    if k is None:
        return False
    got = _META['work'].get(wp.name)
    if got and got.get('k') == k:
        return got['archived']
    try:
        a = json.loads(wp.read_text(encoding='utf-8')).get('archived') is True
    except (OSError, ValueError, AttributeError):
        a = False
    _META['work'][wp.name] = {'k': k, 'archived': a}
    _META['dirty'] = True
    return a


def out_file(name):
    """out/ の中のファイルだけ（外へ出る名前は断る・名前はファイルに触る前に確かめる＝plain）"""
    if not plain(name) or not str(name).endswith('.nlmf'):
        raise ValueError('out/ の .nlmf だけを扱える')
    p = (OUT / name).resolve()
    if p.parent != OUT.resolve() or p.suffix != '.nlmf':
        raise ValueError('out/ の .nlmf だけを扱える')
    return p


def song_of(p):
    return p.name.split('.')[0]


def base_of(p):
    """作り直しの入力: 結果のファイルがあればそれ、無ければ土台"""
    if p.exists():
        return p
    for k in BASE_KINDS:
        q = OUT / f'{song_of(p)}.{k}.nlmf'
        if q.exists():
            return q
    raise FileNotFoundError(f'{song_of(p)} の土台になる結果のファイルが無い')


_DATA, _DATA_LOCK = {}, threading.Lock()
# 覚えておく曲の数（2026-11-09 利用者「曲の切り替えが遅い」: 前は 1 曲分だけで、曲を変えるたびに作り直していた＝Brotherhood 4.8〜6.3 秒・
# ハロ 3.6 秒）。1 曲の中身は Python の物で 2.3〜3.9MB（JSON で 300〜490KB・2026-11-09 に BURN・ハロ・Brotherhood で測った）＝3 曲で 12MB ほど。
# 古く使った物から捨てる
DATA_KEEP = 3
SONGDATA_DISK = True   # 曲のデータをディスクにも控える（app/songcache.py・<cache>/<曲>/song_data.<鍵>.json.gz）
# 曲のデータが読む分けた音のフォルダの中のファイル（分けた音の長さ・打点と曲の中身の控え＝作る時に書き足すこともある・4 つの音）
DATA_STEM_FILES = ('separate.json', 'onsets.json', 'music.json') + tuple(f'{k}.flac' for k in STEMS)


def data_inputs(p, src):
    """曲のデータの答えを決める入力（覚えておく物とディスクの控えの鍵・作り方の版は songcache が足す）: 開くファイル・土台・基準の難易度と、
    読むファイルの更新時刻と大きさ（土台・聞き比べの帯のほかの版 form-s1・style-s1・intent-s1・こちらで書いた印・DATA_STEM_FILES）。
    曲のデータを作る所（songdata.song_data・chart）で読むファイルを足したら、ここにも足す"""
    name = song_of(p)
    files = [src, *(OUT / f'{name}.{k}.nlmf' for k in ('form-s1', 'style-s1', APP_KIND)), written._state_path(src),
             *(CACHE / name / f for f in DATA_STEM_FILES)]
    return {'file': p.name, 'src': src.name, 'diff': base_diff(p), 'files': [songcache.stat_key(f) for f in files]}


def song_data(p):
    """画面に出す曲のデータ（app/songdata.py の物＋音の場所・基準の難易度の作った譜面とクリップ・ある難易度の一覧 diffs・基準 base）。
    重いので入力（data_inputs: ファイルの更新時刻と大きさ・基準の難易度）と作り方の版の鍵で、DATA_KEEP 曲までメモリに覚え、ディスクにも
    控える（app/songcache.py＝起動し直しても初めての曲でなければ読むだけ・重い部品も読まない）。同じ曲の古い物（結果のファイルが変わる前・
    基準を置き直す前）は、新しい物を入れる時に捨てる＝古い控えは返さない"""
    src = base_of(p)
    name = song_of(p)
    inp = data_inputs(p, src)
    key = (str(src), songcache.key_of(inp))
    with _DATA_LOCK:
        if key in _DATA:
            _DATA[key] = _DATA.pop(key)   # 使った順（dict は入れた順＝一番後ろが新しい）
            return _DATA[key]
    d = songcache.load(CACHE / name, key[1]) if SONGDATA_DISK else None
    if d is None:
        d = songdata.song_data(name, src, CACHE / name)
        d['src'] = {k: f'/audio/{name}/{k}.flac' for k in STEMS}   # 音の場所（/audio/）
        d['file'], d['shown'] = p.name, src.name
        d.update(chart(src))
        after = data_inputs(p, src)   # 作った後の入力（打点・曲の中身の控えを書き足した後＝次に開く時の鍵）
        if after['files'][0] == inp['files'][0] and after['diff'] == inp['diff']:   # 作っている間に土台・基準が変わっていない
            key = (str(src), songcache.key_of(after))
            if SONGDATA_DISK and not songcache.changed():   # サーバーを起動した後にコードを直していない
                songcache.save(CACHE / name, key[1], d)
    with _DATA_LOCK:
        for k in [k for k in _DATA if song_of(Path(k[0])) == name]:   # 同じ曲の前の物（土台が試作5 から結果のファイルに変わった時も）
            del _DATA[k]
        _DATA[key] = d
        while len(_DATA) > DATA_KEEP:
            del _DATA[next(iter(_DATA))]
    return d


STATE_TEXT = {'app': '', 'fixed': '固定', 'edited': '手で直した', 'user': '利用者のクリップ', 'legacy': '前の形式（直したか分からない）'}


def file_diff(path):
    """ファイルの基準の難易度の名前（docs/アプリ仕様.md 17 節）: 履歴の版（<OUT>/.history/<曲>/<曲>.<版>.nlmf）は控えた時の基準
    （一覧の diff・無ければ控えた作業ファイルの diff・無ければ ExpertPlus）、ほかは曲の作業ファイルの diff（base_diff）"""
    path = Path(path)
    if path.parent.parent.name == '.history':
        vid = path.name[:-len('.nlmf')].split('.', 1)[-1]
        try:
            e = next((e for e in json.loads((path.parent / 'index.json').read_text(encoding='utf-8')) if e.get('id') == vid), {})
        except (OSError, ValueError):
            e = {}
        d = e.get('diff')
        if not d:
            try:
                d = json.loads(path.with_name(path.name[:-len('.nlmf')] + '.automap.json').read_text(encoding='utf-8')).get('diff')
            except (OSError, ValueError):
                d = None
        try:
            return diffs.name_of(d or diffs.DEFAULT)
        except ValueError:
            return diffs.DEFAULT
    return base_diff(OUT / f'{song_of(path)}.{APP_KIND}.nlmf')


def diff_key_in(proj, d, what='このファイル'):
    """難易度の名前 → .nlmf の difficulties のキー（無ければ分かる言葉で ValueError）。nlmf.diff_key は頭の一致で探すので
    'Expert' で 'expertplusstandard.dat' を拾い得る＝ここでは使わない"""
    d = diffs.name_of(d)
    k = diffs.key(d)
    if k not in (proj.get('difficulties') or {}):
        have = [diffs.TEXT.get(x['diff'], x['diff']) for x in diffs.listing(proj)]
        raise ValueError(f'{what}に {diffs.TEXT[d]} の譜面が無い（ある難易度: {"・".join(have) or "無し"}）')
    return k


def diff_listing(proj, base, as_written=False):
    """ある難易度の一覧（automap.diffs.listing の形＋text＝画面の名前・role＝base（基準）か derived（派生）・edited＝NLM で手で直した
    作ったクリップの数・kept＝作り直しで残すクリップ（手で直した・固定・利用者のクリップ・前の形式）の数）"""
    out = []
    for it in diffs.listing(proj):
        cls = nlmf.classify(proj, it['key'], as_written)[0] if it['notes'] else []
        out.append(dict(it, text=diffs.TEXT[it['diff']], role='base' if it['diff'] == base else 'derived',
                        edited=sum(1 for _, st in cls if st == 'edited'), kept=sum(1 for _, st in cls if st != 'app')))
    return out


def chart(src, diff=None):
    """結果のファイルの作った譜面: ノーツ（秒・拍）とクリップ（ノーツのレーン）。クリップごとの状態（NLM とのやり取りの決まり＝
    nlmf.classify: 作ったまま・手で直した・固定・利用者のクリップ・前の形式）と、作ったクリップのレーンの隙間（NLM で消した所）も。
    diff＝見る難易度（無ければファイルの基準の難易度＝file_diff）。答えに diff（名前）・key・base（基準）・diffs（ある難易度の一覧）"""
    proj = nlmf.load(src)
    bpm = float(proj['bpm'])
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    lead = -off if off < 0 else 0.0
    base = file_diff(src)
    d = diffs.name_of(diff) if diff else base
    dk = diff_key_in(proj, d, '譜面のファイル' if diff else '譜面のファイル（基準の難易度）')
    sec = lambda b: round(b * 60 / bpm - lead, 4)
    notes = [[sec(n['beat']), n['x'], n['y'], n['c'], n['d'], round(n['beat'], 4)] for n in nlmf.clip_notes(proj, dk)]
    as_written = src.exists() and not cli._edited_since_written(src)
    cls, new_fmt, lane = nlmf.classify(proj, dk, as_written)
    clips = []
    for s, st in cls:
        b0 = float(s.get('beat') or 0)
        b1 = b0 + float(s.get('len') or 0)
        n = len(((s.get('content') or {}).get('notes')) or [])
        clips.append({'id': s.get('id'), 'label': s.get('label') or '', 'track': s.get('track', 0), 'b0': b0, 'b1': b1,
                      't0': sec(b0), 't1': sec(b1), 'n': n, 'state': st, 'reason': STATE_TEXT.get(st, st),
                      'keep': st != 'app', 'main': (s.get('track') or 0) == lane})
    holes = []
    if lane is not None and new_fmt:
        try:   # 曲の終わり（作り直しと同じ＝分けた音の長さ＋無音追加を4拍にそろえる）
            secs_ = json.loads((CACHE / song_of(src) / 'separate.json').read_text(encoding='utf-8'))['seconds']
            end = math.ceil((secs_ + lead) * bpm / 60 / 4) * 4
        except (OSError, ValueError, KeyError):
            end = max((c['b1'] for c in clips if c['main']), default=0)
        holes = [[a, b, sec(a), sec(b)] for a, b in nlmf.coverage_holes(proj, dk, lane, end)]
    return {'notes': notes, 'clips': clips, 'holes': holes, 'lane': lane, 'notesLanes': proj.get('notesLanes') or 1,
            'diff': d, 'key': dk, 'base': base, 'diffs': diff_listing(proj, base, as_written)}


# ---- 作業ファイル ----

def work_path(p):
    return p.with_name(p.name[:-len('.nlmf')] + '.automap.json')


def default_work(p):
    """作業ファイルが無い時: 前に聞き比べのページで作った意思入れの表（out/<曲>.intent.json）があれば引き継ぐ"""
    w = {'version': 1, 'song': song_of(p), 'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}, 'history': []}
    old = OUT / f'{song_of(p)}.intent.json'
    if old.exists():
        d = json.loads(old.read_text(encoding='utf-8'))
        seen = set()
        for r in d.get('ranges') or []:   # 全く同じ区間・指示の重なり（ページで2回付けた）は1つに（intent.load と同じ）
            k = (r['b0'], r['b1'], json.dumps(r.get('set') or {}, sort_keys=True, ensure_ascii=False))
            if k not in seen:
                seen.add(k)
                w['ranges'].append({'b0': r['b0'], 'b1': r['b1'], 'set': r.get('set') or {}})
        # 前の量のラインは点の間を直線でつなぐ形 → なめらかにつなぐキーフレームとして引き継ぐ（10% きざみ）
        w['line'] = [{'b': p_['b'], 'k': round(round(p_['k'] * 10) / 10, 1), 'smooth': True} for p_ in d.get('line') or []]
        w['auto_rest'] = d.get('auto_rest') or w['auto_rest']
        w['from'] = old.name
    return w


def load_work(p):
    """作業ファイル → 辞書（前の★の物差しの帯は今の境目へ読み替える＝automap/rating_scale.py・型のライブラリの設定の無い曲・出どころに
    手元の譜面がある前の形の設定はランク譜面へ読み替える＝automap/library_setting.migrate_work。次に保存した時に書き換わる）"""
    from automap import library_setting
    wp = work_path(p)
    w = rating_scale.migrate_work(json.loads(wp.read_text(encoding='utf-8'))) if wp.exists() else default_work(p)
    return library_setting.migrate_work(w)


# 画面が持たない作業ファイルの項目: 画面の保存（PUT /api/work・store.js の workBody は持っている項目しか送らない）やほかの受け持ちの保存
# （ctx.save_work）では、送られてきた値を使わずファイルにある値のまま残す（前に library を workBody に通し忘れて、保存のたびに消えた・
# CLAUDE.md）。書くのは決まった受け口だけ（archived＝曲を選ぶ窓のアーカイブの印・set_archived）。履歴の比べ（versions.WORK_ONLY）でも
# 曲の全体の設定に数えない（数えると、アーカイブしただけで次の作り直しが前の譜面に寄せなくなる）
SERVER_ONLY = ('archived',)
_WORK_LOCK = threading.Lock()


def _write_work(p, w):
    work_path(p).write_text(json.dumps(w, ensure_ascii=False, indent=1), encoding='utf-8')


def save_work(p, w):
    w = dict(w, version=1, song=song_of(p), saved=time.strftime('%Y-%m-%dT%H:%M:%S'))
    with _WORK_LOCK:
        wp = work_path(p)
        try:
            old = json.loads(wp.read_text(encoding='utf-8')) if wp.exists() else {}
        except (OSError, ValueError):
            old = {}
        for k in SERVER_ONLY:
            w.pop(k, None)
            if isinstance(old, dict) and k in old:
                w[k] = old[k]
        _write_work(p, w)
    return w


def set_archived(b):
    """POST /api/songs/archive {song, on}: 曲をアーカイブする（on＝False で戻す）。作業ファイルに印（archived: true）を付けるだけで、
    ファイルは動かさない。作業ファイルが無い曲は作る（default_work と同じ中身＝画面で開いた時と同じ）。印のほかは書き換えず、
    作業ファイルの更新時刻もそのまま（窓のアプリは作業ファイルを一番後に保存した曲を最後に開いていた曲とみる＝desktop.last_song）"""
    name = str(b.get('song') or '')
    s = next((x for x in songs() if x['song'] == name), None)
    if s is None:
        raise ValueError(f'その曲は一覧に無い: {name}')
    p = out_file(s['app_file'])
    on_ = bool(b.get('on', True))
    with _WORK_LOCK:
        wp = work_path(p)
        st = wp.stat() if wp.exists() else None
        if st:
            w = json.loads(wp.read_text(encoding='utf-8'))
        else:
            w = dict(default_work(p), version=1, song=song_of(p), saved=time.strftime('%Y-%m-%dT%H:%M:%S'))
        if on_:
            w['archived'] = True
        else:
            w.pop('archived', None)
        _write_work(p, w)
        if st:
            os.utime(wp, ns=(st.st_atime_ns, st.st_mtime_ns))
    with _META_LOCK:   # 一覧の控えも今の値に（更新時刻を戻したので、大きさが前と同じだと控えが変わったと気付けない）
        _meta_open()
        _META['work'][wp.name] = {'k': _stat_key(wp), 'archived': on_}
        _META['dirty'] = True
        _meta_flush()
    return {'ok': True, 'song': name, 'archived': on_}


def intent_table(w):
    """作業ファイル → compose の --intent の表（automap/intent.py の形）。量のラインのキーフレームは、
    「その点から次の点まで同じ値」（段）か「前の点からなめらかに」を、点を直線でつなぐ形に直す（段は点の直前に前の値の点を足す）"""
    pts, prev = [{'b': 0.0, 'k': 1.0}], 1.0
    for kf in sorted(w.get('line') or [], key=lambda q: q['b']):
        if not kf.get('smooth') and kf['b'] - 0.01 > pts[-1]['b']:
            pts.append({'b': round(kf['b'] - 0.01, 3), 'k': prev})
        pts.append({'b': kf['b'], 'k': kf['k']})
        prev = kf['k']
    return {'ranges': [{'b0': r['b0'], 'b1': r['b1'], 'set': r.get('set') or {}} for r in w.get('ranges') or []],
            'line': pts if len(pts) > 1 else [], 'auto_rest': w.get('auto_rest') or {'on': False, 'b': None}}


# ---- 時間のかかる作業（別の流れ・作り直し・曲の取り込み・別の案） ----

JOBS = {}
# 作り直しの前後に呼ぶ物（履歴の控え＝app/versions.py）: fn(job, p)。結果のファイル（アプリが作り直すファイル）へ書く時だけ呼ぶ
BEFORE_GENERATE, AFTER_GENERATE = [], []
# compose に足す引数（曲ごとのライブラリの設定＝app/library.py）: fn(p, 作業ファイル) → [引数…]。別の案の作り直しにも効く
COMPOSE_EXTRA = []


class Cancelled(Exception):
    """作業をやめた（cancel_job）"""


def cancel_job(jid):
    """POST /api/job/cancel {id}: 動いている作業をやめる（2026-11-03 利用者「譜面造りの途中でキャンセル出来るようなボタン」）。
    印（job['cancel']）を付け、動いているプロセス（compose）を止め、job['_on_cancel'] の物（別の案の案ごとの作業等）も呼ぶ。
    作業は次の段に入らずに止まり、state は error・job['cancelled'] が True（log の最後に「やめた」）。作り直しは結果のファイル・報告を
    作り直しの前に戻す（start_generate）。展開・取り込みはそれぞれの受け口（/api/expand/cancel・/api/import/cancel）"""
    j = JOBS.get(jid)
    if not j or j['state'] != 'running':
        raise ValueError('やめる作業が無い（もう終わった）')
    j['cancel'] = True
    pr = j.get('proc')
    if pr is not None:
        try:
            pr.kill()
        except OSError:
            pass
    for fn in list(j.get('_on_cancel') or []):
        try:
            fn()
        except Exception as e:   # noqa: BLE001
            j['log'] += f'\n（やめる時の後始末に失敗した: {e}）'
    return {'ok': True, 'id': jid}


def start_job(file, steps, kind='generate', after=None, **meta):
    """steps＝[(説明, 中身)] を順に別の流れで動かす。中身はコマンドの並び（別のプロセス・出力は job['log'] へ）か、
    関数 fn(job)（このプロセスの中で）。1つでも失敗したらそこで止める。after(job) は成功・失敗によらず最後に呼ぶ。
    画面は /api/job?id= で state（running・done・error）・step（今の番号）・steps（説明の並び）・log を見る。
    やめる（cancel_job）と次の段に入らず、動いているコマンドを止める（state は error・cancelled が True）"""
    jid = uuid.uuid4().hex[:10]
    job = JOBS[jid] = dict(meta, id=jid, kind=kind, file=file, state='running', log='', started=time.time(),
                           steps=[s for s, _ in steps], step=0)
    if after:
        job['finishing'] = True   # 後始末（after＝履歴の控え等）が終わるまで画面には動いていると見せる（job_view）

    def run():
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        try:
            for i, (label, what) in enumerate(steps):
                if job.get('cancel'):
                    raise Cancelled()
                job['step'] = i
                job['log'] += f'== {label}\n'
                if callable(what):
                    what(job)
                    if job.get('cancel'):
                        raise Cancelled()
                    continue
                pr = subprocess.Popen([str(c) for c in what], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                job['proc'] = pr
                if job.get('cancel'):   # 始める前にやめていた（cancel_job がまだプロセスを知らなかった）
                    pr.kill()
                for line in iter(pr.stdout.readline, b''):
                    job['log'] += line.decode('utf-8', 'replace')
                pr.wait()
                job.pop('proc', None)
                if job.get('cancel'):
                    raise Cancelled()
                if pr.returncode:
                    raise RuntimeError(f'{label} に失敗した（終了コード {pr.returncode}）')
            job['state'] = 'done'
        except Exception as e:   # noqa: BLE001
            if job.get('cancel'):
                job['state'], job['cancelled'], job['log'] = 'error', True, job['log'] + '\nやめた'
            else:
                job['state'], job['log'] = 'error', job['log'] + f'\n{e}'
        finally:
            job['took'] = round(time.time() - job['started'], 1)
            if after:
                try:
                    after(job)
                except Exception as e:   # noqa: BLE001
                    job['log'] += f'\n（後始末に失敗した: {e}）'
                finally:
                    job.pop('finishing', None)

    threading.Thread(target=run, daemon=True).start()
    return job


def job_view(j):
    """画面へ返す作業の中身（コマンドの文字列・プロセスは返さない）。後始末の間は running（終わったと見て画面が履歴・未反映の
    意思入れを聞くと、まだ作った版が控えられていなかった）"""
    v = {k: x for k, x in j.items() if k not in ('cmd', 'proc', 'finishing') and not k.startswith('_')}
    if j.get('finishing'):
        v['state'] = 'running'
    return v


PREFS_LOCK = threading.Lock()


def save_prefs(b):
    """画面の覚え（3D の窓の設定・切る音・表示の大きさ・欄の幅…・store.js の lsSet）を設定の ui_prefs に足す。名前は automap- で始まる物・
    値は小さな物だけ。ブラウザの覚えはアドレスの番号ごとで、窓のアプリが別の番号で開くと消えたように見えたので、アプリの設定に持つ"""
    if not isinstance(b, dict):
        raise ValueError('画面の覚えは {名前: 値}')
    with PREFS_LOCK:
        cur = dict(config.load(CONFIG).get('ui_prefs') or {})
        for k, v in b.items():
            if isinstance(k, str) and k.startswith('automap-') and len(k) <= 80 and len(json.dumps(v, ensure_ascii=False)) <= 20000:
                cur[k] = v
        config.update({'ui_prefs': cur}, CONFIG)
    return {'ok': True}


def busy(file):
    return any(j['state'] == 'running' and j['file'] == file for j in JOBS.values())


def base_diff(p, w=None):
    """曲の基準の難易度（アプリが意思入れで作り直す難易度・作業ファイルの diff・既定 ExpertPlus・automap/diffs.py）"""
    w = load_work(p) if w is None else w
    try:
        return diffs.name_of(w.get('diff') or diffs.DEFAULT)
    except ValueError:
        return diffs.DEFAULT


def compose_cmd(p, intent_file, only=None, out=None, extra=(), diff=None):
    """作り直しのコマンド。out＝別のファイルへ書く（別の案）・extra＝足す引数（--seed 等）・diff＝作る難易度（無ければ基準の難易度）。
    --diff は 'ExpertStandard.dat' の形で渡す（compose の nlmf.diff_key は頭の一致で探すので、'Expert' だと Expert+ を拾い得る）"""
    cmd = [sys.executable, '-m', 'automap', 'compose', str(base_of(p)), '--stems', str(CACHE / song_of(p)), '--form', '--style',
           '--intent', str(intent_file), '--out', str(out or p), '--diff', diffs.dat(diff if diff else base_diff(p))]
    if only:
        o0, o1 = sorted(float(x) for x in only)
        cmd += ['--only', f'{o0:g},{o1:g}']
    return cmd + [str(x) for x in extra]


def write_intent(p):
    """作業ファイルから compose の --intent の表を一時ファイルに書く（使い終わったら消す）"""
    tf = Path(tempfile.gettempdir()) / f'automap-{uuid.uuid4().hex[:8]}.intent.json'
    tf.write_text(json.dumps(intent_table(load_work(p)), ensure_ascii=False), encoding='utf-8')
    return tf


def start_generate(p, only=None, out=None, extra=(), kind='generate', after=None, opts=None, **meta):
    """作り直しを始める。only＝[拍の始まり, 終わり]: 選んだ区間だけ作り直す（compose --only・結果のファイルがある時だけ）。
    out＝結果のファイルではなく別のファイルへ書く（別の案。その時は BEFORE/AFTER_GENERATE を呼ばない）。
    opts＝画面の作り直しの選び方（{anchor: False}＝前の譜面に寄せない）。COMPOSE_EXTRA には作業ファイルの opts として渡す"""
    if only and not p.exists():
        raise ValueError('選んだ区間だけ作り直すのは、結果のファイルがある時だけ（先に全部を作り直す）')
    diff_key_in(nlmf.load(base_of(p)), base_diff(p), '作り直しの土台（' + base_of(p).name + '）')   # 基準の難易度が無ければ始める前に断る
    tf = write_intent(p)
    w = dict(load_work(p), opts=opts or {})
    extra = [*extra, *(x for fn in COMPOSE_EXTRA for x in fn(p, w))]
    cmd = compose_cmd(p, tf, only, out, extra)
    dst = Path(out) if out else p
    hooks = not out
    rp = dst.with_name(dst.name[:-len('.nlmf')] + '.report.md')
    keep = {}   # やめた時に戻す控え（結果のファイル・報告・書いた時の指紋。compose は保存の途中で止まると壊れたファイルを残す）

    def before(job):
        for f in (dst, rp, cli._state_path(dst)):
            keep[f] = f.read_bytes() if f.exists() else None
        if hooks:
            for fn in BEFORE_GENERATE:
                fn(job, p)

    def restore(job):
        """やめた作り直し: 結果のファイル・報告・指紋を作り直しの前に戻す（作り直しの前に無かった物は消す）"""
        back = 0
        for f, data in keep.items():
            if data is None:
                if f.exists():
                    f.unlink()
                    back += 1
            elif not f.exists() or f.read_bytes() != data:
                f.write_bytes(data)
                back += 1
        job['log'] += '・結果のファイルは作り直しの前のまま' + (f'（戻した {back}）' if back else '') + '\n'

    def done(job):
        tf.unlink(missing_ok=True)
        if job.get('cancelled'):
            restore(job)
        if job['state'] == 'done' and rp.exists():
            job['report'] = rp.read_text(encoding='utf-8')
        if hooks:
            for fn in AFTER_GENERATE:
                try:
                    fn(job, p)
                except Exception as e:   # noqa: BLE001
                    job['log'] += f'\n（作り直しの後の処理に失敗した: {e}）'
        if after:
            after(job)

    return start_job(p.name, [('控え', before), ('作り直す', cmd)], kind=kind, after=done, cmd=cmd, only=only,
                     out=dst.name, **meta)


def open_in_nlm(p):
    cfg = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
    exe = os.environ.get('NLM_EXE') or cfg.get('nlm_exe')
    if not exe or not Path(exe).exists():
        raise FileNotFoundError('NLM の場所が分からない（「準備と設定」で NLM の場所を選ぶ・設定の nlm_exe か 環境変数 NLM_EXE）')
    subprocess.Popen([exe, str(p)], cwd=str(Path(exe).parent))


# ---- 受け答え ----

class H(BaseHTTPRequestHandler):
    server_version = 'automap/0.1'   # 窓のアプリの二重起動の見分け（desktop.py の Server の頭 automap/）に使う＝名前を変えない

    def log_message(self, fmt, *args):   # 静かに（エラーだけ出す）
        if args and str(args[1])[:1] in '45':
            sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, {'error': str(msg)})

    def _reply(self, r):
        """つなぐ口（GET_ROUTES・POST_ROUTES）の答え: dict・list＝JSON／Path＝ファイル（Range にも答える）／(bytes, Content-Type)"""
        if isinstance(r, Path):
            return self._file(r)
        if isinstance(r, tuple):
            return self._send(200, r[0], r[1])
        return self._send(200, r)

    def _q(self):
        u = urlparse(self.path)
        return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}

    def _file(self, path):
        """静的なファイル・分けた音（Range に答える＝音の途中へ飛べる）"""
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        if rng and rng.startswith('bytes='):
            a, _, b = rng[6:].split(',')[0].partition('-')
            if a:
                start, end = int(a), (int(b) if b else size - 1)
            else:
                start = max(0, size - int(b))
            end = min(end, size - 1)
            if start > end:   # 範囲の外（始まりが大きさ以上・終わりより後）は 416（前は長さが負の 206 を返した）
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        n = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(n))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-cache')
        if rng:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(path, 'rb') as f:
            f.seek(start)
            left = n
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass

    def do_HEAD(self):
        self.do_GET()

    def _deny_reason(self, path, q, write):
        """出入りの守り（TOKEN の説明）→ 断る訳か None"""
        if _hostname(self.headers.get('Host')) not in HOSTS:
            return 'この PC の名前（127.0.0.1・localhost）で開いたページからだけ'
        org = self.headers.get('Origin')
        if org and org != 'null':
            try:
                u = urlsplit(org)
                same = u.scheme == 'http' and (u.hostname or '') in HOSTS and u.port == self.server.server_address[1]
            except ValueError:
                same = False
            if not same:
                return 'ほかのページからは使えない'
        if write and self.headers.get('X-Automap') != '1':
            return 'このアプリの画面からだけ'
        if not write and (path == '/' or path.startswith('/static/')):   # 画面の部品（<script>・<link> は頭を付けられない）
            return None
        if not write and path.startswith(TOKEN_PREFIXES):   # 使い捨ての鍵で受ける口（鍵は受け持ちが確かめる・下の PREFIX_GET）
            return None
        given = self.headers.get(KEY_HEADER) or (q.get('k') if not write and path.startswith(KEY_QUERY) else None) or ''
        if not hmac.compare_digest(given.encode('utf-8', 'replace'), TOKEN.encode('ascii')):
            return ('合言葉が違う（サーバーを起動し直した後の古い画面か、ほかから開いた画面）。app/start.bat か窓のアプリから開き直してください')
        return None

    def _guard(self, path, q, write=False):
        why = self._deny_reason(path, q, write)
        if why:
            self._err(403, why)
            return False
        return True

    def do_GET(self):
        path, q = self._q()
        if not self._guard(path, q):
            return
        try:
            if path == '/':
                return self._file(STATIC / 'index.html')
            if path.startswith('/static/'):
                parts = rel_parts(unquote(path[len('/static/'):]))   # 確かめてから場所にする（app/names.py）
                f = STATIC.joinpath(*parts).resolve() if parts else None
                if f is None or STATIC.resolve() not in f.parents or not f.is_file():
                    return self._err(404, 'ない')
                return self._file(f)
            if path.startswith('/audio/'):
                song, stem = unquote(path[len('/audio/'):]).split('/', 1)
                # 曲の名前も音の名前も 1 つの名前だけ（..・\・ドライブ名・UNC・絶対の場所で分けた音の場所の外を指さない）。確かめてから場所にする
                if not (plain(song) and plain(stem)):
                    return self._err(404, 'ない')
                f = (CACHE / song / stem).resolve()
                if f.parent != (CACHE / song).resolve() or f.suffix != '.flac' or not f.is_file():
                    return self._err(404, 'ない')
                return self._file(f)
            if path == '/api/ping':   # 合言葉が合っているか（static/js/key.js が URL の #k= を確かめる）
                return self._send(200, {'ok': True})
            if path == '/api/blrview':   # 埋め込みのリプレイの窓を出す番号（別のオリジン・下の viewer_origin）
                return self._send(200, {'origin': viewer_origin(self.server.server_address[1])})
            if path == '/api/songs':
                return self._send(200, songs())
            if path == '/api/prefs':   # 画面の覚え（store.js の lsGet・設定の ui_prefs）
                return self._send(200, config.load(CONFIG).get('ui_prefs') or {})
            if path == '/api/song':
                return self._send(200, song_data(out_file(q['file'])))
            if path == '/api/chart':   # &diff＝見る難易度（無ければ基準の難易度）
                return self._send(200, chart(base_of(out_file(q['file'])), q.get('diff')))
            if path == '/api/nlmf':   # 3D（nlmf-map.js）用の .nlmf の中身（カバー画像は除く）
                proj = nlmf.load(base_of(out_file(q['file'])))
                proj.pop('coverData', None)
                return self._send(200, proj)
            if path == '/api/work':
                return self._send(200, load_work(out_file(q['file'])))
            if path == '/api/job':
                j = JOBS.get(q.get('id'))
                return self._send(200, job_view(j)) if j else self._err(404, 'その作業は無い')
            if path == '/api/jobs':   # 動いている作業（画面を開き直した時に続きを見る）
                return self._send(200, [job_view(j) for j in JOBS.values() if j['state'] == 'running'])
            if path in GET_ROUTES:
                return self._reply(GET_ROUTES[path](q))
            for pre, fn in PREFIX_GET.items():
                if path.startswith(pre):
                    r = fn(path)
                    return self._send(200, r[0], r[1]) if r else self._err(404, 'ない')
            return self._err(404, 'ない')
        except (ValueError, FileNotFoundError, KeyError) as e:
            return self._err(400, e)
        except SystemExit as e:
            return self._err(400, e)

    def do_PUT(self):
        path, q = self._q()
        if not self._guard(path, q, write=True):
            return
        try:
            if path == '/api/work':
                return self._send(200, save_work(out_file(q['file']), self._body()))
            return self._err(404, 'ない')
        except (ValueError, KeyError) as e:
            return self._err(400, e)

    def do_POST(self):
        path, q = self._q()
        if not self._guard(path, q, write=True):
            return
        try:
            b = self._body()
            if path == '/api/prefs':
                return self._send(200, save_prefs(b))
            if path == '/api/songs/archive':   # 曲を選ぶ窓のアーカイブ・戻す（作業ファイルの印）
                return self._send(200, set_archived(b))
            if path == '/api/generate':
                p = out_file(b['file'])
                if busy(p.name):
                    return self._err(409, 'この曲は今作り直している')
                j = start_generate(p, b.get('only'), opts=b.get('opts'))
                return self._send(200, {'id': j['id']})
            if path == '/api/job/cancel':
                return self._send(200, cancel_job(b['id']))
            if path == '/api/open-nlm':
                open_in_nlm(out_file(b['file']))
                return self._send(200, {'ok': True})
            if path == '/api/shutdown':   # 止める（app/stop.bat・画面の「終わる」）。答えてから別の流れで止める（受け答えの中で止めると固まる）
                self._send(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path in POST_ROUTES:
                return self._reply(POST_ROUTES[path](b))
            return self._err(404, 'ない')
        except (ValueError, FileNotFoundError, KeyError) as e:
            return self._err(400, e)


# ---- 埋め込みのリプレイの窓（2026-11-15 利用者「プレイ履歴をアプリ内で表示して、全部の再生位置を同期させて見たい」・docs/アプリ仕様.md 26 節） ----
# 左下の欄（付けた指示と切り替え）で BL のリプレイアプリを iframe に開き、再生位置を窓どうしの伝言（postMessage）でそろえる
# （static/js/replaypane.js・static/blrembed/bridge.js）。アプリと同じ番号（同じオリジン）の iframe はアプリの画面（DOM・合言葉）に触れる
# ＝別のタブで開く時に noopener にしているのと同じ守りが要る。そこで BL のリプレイアプリだけを別の番号（アプリの番号＋VIEWER_DELTA・
# 使われていれば OS に選ばせる）で出す＝別のオリジン＝アプリの画面にもアプリの受け口（合言葉）にも届かない。この番号で出すのは
# BL のリプレイアプリ（/static/blreplay/）・その中で動く伝言の受け手（/static/blrembed/）・使い捨ての鍵の場所（/blr/）の GET だけ。
# BL のリプレイアプリの index.html には、出す時に伝言の受け手の <script> を足す（写した物には手を入れない＝tools/blreplay_fetch.py）。
# 埋め込めるのはアプリの画面からだけ（Content-Security-Policy の frame-ancestors）。番号はサーバーを止めるまで同じ（最初に使う時に開く）。
# 名前は IPv6 の [::1]（同じ番号で 127.0.0.1 でも待つ・2026-11-15 利用者「リプレイの画面のフレームレートが低い・90fps は最低出るように」）:
# ブラウザ（Edge・WebView2）はサイト（名前＝127.0.0.1 と [::1] は別のサイト・番号は見ない）ごとに描く流れ（プロセス）を分ける。127.0.0.1 の
# 別の番号ではアプリの画面と同じ流れで描き、アプリの帯・3D を描く間リプレイが待たされた（見えない Edge で平均 75fps・遅いコマ 18〜25ms）。
# localhost の名前で分ける案は、Windows で localhost の ::1 につながらない分の待ち（つなぐたびに 0.3 秒ほど）が出るのでやめた。
# ::1 で待てない PC（IPv6 を切った等）は 127.0.0.1 のまま（同じ流れで描く＝前の形）。
VIEWER_DELTA = 20
VIEWER_PATHS = ('/static/blreplay/', '/static/blrembed/', '/blr/')
VIEWER_HOSTS = HOSTS + ('::1',)
_VIEWERS, _VLOCK = {}, threading.Lock()   # アプリの番号 → [リプレイの窓のサーバー（127.0.0.1・あれば ::1）]
_IN_USE = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}   # 番号が使われている（Windows の WSAEADDRINUSE・排他で断られた WSAEACCES も）


class ExclusiveServer(ThreadingHTTPServer):
    """同じ番号をほかと分け合わない（desktop.py の ExclusiveServer と同じ）。Windows は SO_REUSEADDR だと使われている番号でも待ててしまい、
    要求がどちらに届くか決まらない＝同じ PC の別のアカウントのプログラムが同じ番号で待ち、合言葉を運ぶ要求を受け取れた（2026-11-15 の
    スキャン F1・ブラウザで使う形の make_server の既定がこれでなかった）"""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _ViewerHTTP(ExclusiveServer):
    """リプレイの窓の番号（同じ番号をほかと分け合わない）"""


class _ViewerHTTP6(_ViewerHTTP):
    address_family = socket.AF_INET6


class ViewerH(H):
    """リプレイの窓の番号の受け答え（VIEWER_PATHS の GET だけ）。main_port＝埋め込んでよいアプリの番号（viewer_origin が型を作る）"""
    main_port = 0

    def _parents(self):
        return f'http://127.0.0.1:{self.main_port} http://localhost:{self.main_port}'

    def _deny_reason(self, path, q, write):
        """アプリの番号の守り（H._deny_reason）と同じ考え: Host がこの PC の名前（[::1] も）・Origin が付いていればこの番号のページ。
        出すのは VIEWER_PATHS の GET だけ（どれも合言葉なし＝BL のリプレイアプリは合言葉を付けられない・鍵の場所は replays.serve が確かめる）"""
        if write or not path.startswith(VIEWER_PATHS):
            return 'リプレイの窓の番号では BL のリプレイアプリだけ'
        if _hostname(self.headers.get('Host')) not in VIEWER_HOSTS:
            return 'この PC の名前（127.0.0.1・localhost・[::1]）で開いたページからだけ'
        org = self.headers.get('Origin')
        if org and org != 'null':
            try:
                u = urlsplit(org)
                same = u.scheme == 'http' and (u.hostname or '') in VIEWER_HOSTS and u.port == self.server.server_address[1]
            except ValueError:
                same = False
            if not same:
                return 'ほかのページからは使えない'
        return None

    def end_headers(self):
        self.send_header('Content-Security-Policy', 'frame-ancestors ' + self._parents())
        super().end_headers()

    def do_GET(self):
        path, q = self._q()
        if path != '/static/blreplay/index.html':
            return super().do_GET()
        if not self._guard(path, q):
            return
        f = STATIC / 'blreplay' / 'index.html'
        if not f.is_file():
            return self._err(404, 'ない')
        html = f.read_text(encoding='utf-8')
        tag = f'<script src="../blrembed/bridge.js" data-parent="{self._parents()}"></script>\n'
        html = html.replace('</body>', tag + '</body>', 1) if '</body>' in html else html + tag
        return self._send(200, html, 'text/html; charset=utf-8')


def viewer_origin(main_port):
    """アプリの番号 → 埋め込みのリプレイの窓のオリジン（無ければ待ち始める）"""
    with _VLOCK:
        srvs = _VIEWERS.get(main_port)
        if srvs is None:
            cls = type('ViewerH', (ViewerH,), {'main_port': main_port})
            srvs = []
            for p in (main_port + VIEWER_DELTA, 0):
                if p > 65535:
                    continue
                try:
                    v4 = _ViewerHTTP(('127.0.0.1', p), cls)
                except OSError:
                    continue
                srvs = [v4]
                try:
                    srvs.append(_ViewerHTTP6(('::1', v4.server_address[1]), cls))
                except OSError as e:
                    if p and e.errno in _IN_USE:   # 決めた番号の ::1 がほかに使われていた → OS に選ばせた番号で両方を試す
                        v4.server_close()
                        srvs = []
                        continue
                    # ::1 で待てない（IPv6 を切った等）→ 127.0.0.1 だけ（アプリの画面と同じ流れで描く）
                break
            if not srvs:
                raise OSError('リプレイの窓の番号を開けなかった')
            for srv in srvs:
                threading.Thread(target=srv.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True, name='blr-viewer').start()
            _VIEWERS[main_port] = srvs
        port = srvs[0].server_address[1]
        return f'http://[::1]:{port}' if len(srvs) > 1 else f'http://127.0.0.1:{port}'


def stop_viewers():
    """リプレイの窓のサーバーを止める（確かめ・止める時）"""
    with _VLOCK:
        for srvs in _VIEWERS.values():
            for srv in srvs:
                srv.shutdown()
                srv.server_close()
        _VIEWERS.clear()


# ---- ほかの受け持ちがつなぐ口 ----
# 曲の取り込み（app/importer.py）・別の案と履歴（app/versions.py）は、それぞれの routes(ctx) が {パス: fn} を返す
# （ctx＝このモジュール。OUT・CACHE 等は呼ばれた時に ctx から読む＝--out・--cache で変えられる）。GET の fn は問い合わせ（dict）、
# POST の fn は本文（dict）を受け取り、dict・list・Path・(bytes, Content-Type) を返す。ValueError・FileNotFoundError・KeyError は 400。
GET_ROUTES, POST_ROUTES = {}, {}
# 使い捨ての鍵で受ける GET（場所の頭 → fn(場所)→(バイト列, Content-Type) か None＝404）。起動ごとの合言葉を付けられないページ（BL の
# リプレイアプリ＝app/replays.py）へ渡す物だけ。出入りの守りは Host・Origin を確かめた後、合言葉を求めずに通す（TOKEN_PREFIXES）＝
# fn が場所の中の鍵を確かめる（鍵の無い・違う場所は None）
PREFIX_GET = {}
TOKEN_PREFIXES = ('/blr/',)


def connect():
    import importer   # noqa: E402  （app/ の中）
    import versions   # noqa: E402
    import library    # noqa: E402  （曲ごとのライブラリの設定）
    import rating     # noqa: E402  （作った譜面の★）
    import check      # noqa: E402  （区間の点検）
    import workio     # noqa: E402  （指示の読み込み・全部外す）
    import expand     # noqa: E402  （難易度の展開・docs/アプリ仕様.md 17 節）
    import setup      # noqa: E402  （準備と設定・起動のたびの確かめ・docs/アプリ仕様.md 21 節）
    import bsexport   # noqa: E402  （Beat Saber へ直接書き出す・プレイリスト・docs/アプリ仕様.md 22 節）
    import update     # noqa: E402  （アプリの更新・配布物だけ・docs/アプリ仕様.md 21 節）
    import njsbase    # noqa: E402  （3D で決めた基準の NJS・docs/アプリ仕様.md 20 節）
    import repeats    # noqa: E402  （同じ音楽の区間＝自動の同じ振りの組を帯「作った譜面」に）
    import replays    # noqa: E402  （遊んだリプレイを BL のリプレイアプリで開く・docs/アプリ仕様.md 26 節）
    me = sys.modules[__name__]
    for mod in (importer, versions, library, rating, check, workio, expand, setup, bsexport, update, njsbase, repeats, replays):
        g, p = mod.routes(me)
        GET_ROUTES.update(g)
        POST_ROUTES.update(p)
    PREFIX_GET['/blr/'] = replays.serve


def make_server(port=8765, out=None, cache=None, cls=None):
    """サーバーを作る（待ち受けるだけ・serve_forever は呼ぶ側）。main と app/desktop.py（窓のアプリ）が使う。
    out・cache＝結果のファイル・分けた音の場所（既定 out/・cache/）。cls＝サーバーの型（既定は同じ番号をほかと分け合わない ExclusiveServer）。
    番号が使われていれば OSError（make_server の前に OUT・CACHE は決まる）"""
    cls = cls or ExclusiveServer
    global OUT, CACHE
    cfg = config.load(CONFIG)
    OUT = Path(out).resolve() if out else config.out_dir(cfg)
    CACHE = Path(cache).resolve() if cache else config.cache_dir(cfg)
    connect()
    return cls(('127.0.0.1', port), H)


def main(argv=None):
    ap = argparse.ArgumentParser(description='譜面づくりのアプリ（手元のサーバー）')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--out', help='結果のファイルの場所（既定は設定の作業の場所の out/・無ければ out/。確かめは写しの場所で）')
    ap.add_argument('--cache', help='分けた音の場所（既定は設定の作業の場所の cache/・無ければ cache/）')
    a = ap.parse_args(argv)
    try:
        srv = make_server(a.port, a.out, a.cache)
    except OSError as e:   # 番号が使われている（もう動いているアプリか、ほかのプログラム）＝分け合わずに止める
        sys.exit(f'番号 {a.port} はほかのプログラムが使っています（{e}）。アプリがもう動いていれば、そのタブを使うか app/stop.bat で止めてから'
                 'もう一度起動してください（別の番号は --port で）')
    port = srv.server_address[1]
    url = access_url(port)   # 合言葉付き（出入りの守り）
    write_key(port)          # app/stop.bat・窓のアプリの二重起動の確かめが読む
    print(f'Auto Note Plotter: {url}（止めるのは Ctrl+C）', flush=True)
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        drop_key(port)
    print('止めた', flush=True)


if __name__ == '__main__':
    main()
