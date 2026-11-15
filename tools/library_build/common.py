"""型のライブラリの道具の共通の部品: 設定・置き場・記録・BeatSaver の版の hash・間を空けて取る HTTP。

置き場（生データ）の場所は PC ごとの設定（app/config.local.json の library_root・git の管理外）か --root で渡す。
手元の譜面（CustomLevels）の場所は custom_levels か --local。データベースの場所は automap.library_db.db_path と同じ決め方。
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / 'tools'
for p in (str(REPO), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from automap import config as _config  # noqa: E402
from automap import library_db, rating_scale  # noqa: E402

CONFIG = _config.path()
UA = 'nlm-automap-library/1 (personal research; slow crawl)'
BL_API = 'https://api.beatleader.com'
BS_API = 'https://api.beatsaver.com'


def config():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def raw_root(arg=None):
    """生データの置き場（--root・環境変数 AUTOMAP_LIBRARY_RAW・設定の library_root の順）"""
    p = arg or os.environ.get('AUTOMAP_LIBRARY_RAW') or config().get('library_root')
    if not p:
        raise SystemExit('生データの置き場が分からない（--root か app/config.local.json の library_root に入れる）')
    return Path(p)


def local_root(arg=None):
    p = arg or os.environ.get('AUTOMAP_CUSTOM_LEVELS') or config().get('custom_levels')
    return Path(p) if p else None


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_json(p, default=None):
    try:
        with open(p, 'rb') as f:
            return json.loads(f.read().decode('utf-8-sig'))
    except FileNotFoundError:
        return default


def write_json(p, obj, indent=None):
    """書き途中で止まっても壊れないように、隣に書いてから置き換える"""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.part')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, p)


def log(root, op, **rec):
    """fetch.log.jsonl に1行（いつ何を取りに行ったか・続きから再開する時の手がかり）"""
    with open(Path(root) / 'fetch.log.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'t': now(), 'op': op, **rec}, ensure_ascii=False) + '\n')


def find(folder, name):
    low = name.lower()
    for f in os.listdir(folder):
        if f.lower() == low:
            return os.path.join(folder, f)
    return None


def bs_hash(folder):
    """BeatSaver の版の hash（Info.dat の中身＋難易度の .dat を Info の順に続けた sha1）。v4 の Info は (None, 'v4')"""
    ip = find(folder, 'Info.dat')
    if not ip:
        return None, 'no-info'
    with open(ip, 'rb') as f:
        b = f.read()
    h = hashlib.sha1(b)
    try:
        info = json.loads(b.decode('utf-8-sig'))
    except ValueError:
        return None, 'bad-info'
    if '_difficultyBeatmapSets' not in info:
        return None, 'v4'
    for s in info['_difficultyBeatmapSets']:
        for bm in s.get('_difficultyBeatmaps', []):
            p = find(folder, bm.get('_beatmapFilename', ''))
            if p:
                with open(p, 'rb') as f:
                    h.update(f.read())
    return h.hexdigest(), 'ok'


def safe_name(s, n=60):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(s or '')).strip().rstrip('. ')
    return s[:n].rstrip('. ') or '_'


class NotFound(Exception):
    pass


class Http:
    """間を空けて取る（同じ相手には gap 秒あける）。429・5xx・つながらない時は間を延ばしてやり直す。404 は NotFound"""

    def __init__(self, gap=1.0, tries=5, waits=(5, 15, 45, 120, 300)):
        self.gap, self.tries, self.waits = gap, tries, waits
        self.last = {}
        self.fails = 0   # 続けて失敗した数（多ければ呼ぶ側で止める）

    def _wait(self, url):
        host = url.split('/')[2]
        dt = time.monotonic() - self.last.get(host, -1e9)
        if dt < self.gap:
            time.sleep(self.gap - dt)
        self.last[host] = time.monotonic()

    def _open(self, url, timeout):
        err = None
        for k in range(self.tries):
            self._wait(url)
            try:
                r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=timeout)
                self.fails = 0
                return r
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    self.fails = 0
                    raise NotFound(url)
                if e.code != 429 and e.code < 500:
                    raise
                err = e
                ra = e.headers.get('Retry-After') if e.headers else None
                w = max(self.waits[min(k, len(self.waits) - 1)], int(ra) if ra and ra.isdigit() else 0)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                err = e
                w = self.waits[min(k, len(self.waits) - 1)]
            print(f'  …{url.split("/")[2]} が答えない（{err}）。{w} 秒待ってやり直す', flush=True)
            time.sleep(w)
        self.fails += 1
        raise err

    def json(self, url, timeout=60):
        with self._open(url, timeout) as r:
            return json.loads(r.read().decode('utf-8'))

    def download(self, url, dst, timeout=300, limit=1 << 30):
        with self._open(url, timeout) as r, open(dst, 'wb') as f:
            n = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                n += len(b)
                if n > limit:
                    raise ValueError(f'大きすぎる（{n} バイト）: {url}')
                f.write(b)
        return n


def db_path(arg=None):
    return library_db.db_path(arg)
