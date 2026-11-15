"""アプリの更新（配布物だけ・docs/アプリ仕様.md 21 節・2026-11-03 利用者「バージョンアップの仕組みも NLM 同等に用意したい」）。

NLM の app_update.py と同じ流れ・同じ約束で作った（違う所は下の「NLM と違う所」）:
  起動時（設定の update_check・既定は確かめる）か「更新」の窓の「更新を確認」で、GitHub Releases の最新リリースの update.json を読む
  → 新しい版があれば変更点を見せる → 「更新する」なら
  ① zip をダウンロードして update.json の SHA-256・大きさと照合 → アプリのフォルダの _update/new/ へ展開（download・作業は start_job）
  ② 展開した「新しい版の起動用 exe」（tools/dist/launcher.cs）を --apply-update 付きで起動し、今のアプリは終わる（apply → 画面が
     /api/shutdown を呼ぶ＝窓のアプリはサーバーが止まると窓を閉じる）
  ③ 新しい版の exe が、古いアプリ（--pid）の終了を待ってから REPLACE_ITEMS を差し替え、起動し直す（launcher.cs の Apply）
  ④ 起動し直したアプリが _update/ を片付け、「更新しました」を出す（startup）
  差し替えを新しい版の exe（C#・.NET Framework 4）で行うのは、動いている runtime\\pythonw.exe・python314.dll は自分自身を上書きできないため。

★版をまたぐ約束（変えると、もう配った版から更新できなくなる）:
  - update.json の場所: https://github.com/<REPO>/releases/latest/download/update.json（RELEASES＋UPDATE_PATH）と形（format=1 の項目:
    name・format・version・tag・zip{name, sha256, size}・notes[{version, ja[]}]）。zip の場所は releases/download/<tag>/<zip の名前>。
  - 版の形 v〇.〇.〇（automap/version.py）・zip の名前 AutoNotePlotter-<版>-win-x64.zip・zip の中の形（最上位 AutoNotePlotter/ の下に
    AutoNotePlotter.exe・build-info.json（"version"）・automap/version.py（VERSION）・runtime/・app/・automap/ …）。
  - 展開する場所 <アプリ>/_update/new/AutoNotePlotter/ と、差し替え役の引数
    `--apply-update --target <アプリのフォルダ> --pid <終わるのを待つプロセス>`（古い版が起動するのは「新しい版の」exe なので、
    新しい版の launcher.cs はこの引数を受け付け続けること）。
  - REPO（リポジトリの名前）: 配った後に変えると、古い版は前の名前の場所を見続ける（GitHub は名前を変えた時に転送するが、頼らない）。
  - format=1 に足した項目（2026-11-03・最初のリリース v1.0.0 から読む・無い・形が違う所は黙って捨てる＝古い版は知らない項目を読まない）:
    urgent＝急ぎの更新 {版: 理由（文）か true}（今の版から最新の版までの間に急ぎの版があれば強い知らせ＝「この版は飛ばす」を出さない）
    ng＝使ってはいけない版 {app: [アプリの版…], parts: {音を分ける部品の名前: [版の決まり…]}, why: 理由}（どの版のアプリも確かめのたびに
    読んで設定の update_ng に控える＝ネットにつながらない起動でも効く。app に今の版があれば強い知らせ・parts は app/setup.py が
    tools/sep_install.check に渡す＝入っていれば止める）。部品の版の決まりは '2.11.0'（その版の全部の種類）・'2.11.0+cu126'（その種類だけ）・
    '<2.11.0' 等（==・!=・<・<=・>・>=）。出どころは automap/version.py の URGENT・NG（tools/dist/build_embed.py が書く）。NG を足すのは
    新しいリリースか、最新のリリースの update.json の差し替え（build_embed.py --refresh-manifest・tools/dist/README.md）。
安全のための約束（NLM と同じ）:
  - 取る URL はここに固定（確かめ用に AUTOMAP_UPDATE_URL で手元の http://127.0.0.1 だけに替えられる＝画面からは替えられない）。
    画面（JS）からは URL・パス・版を受け取らない（受け取るのは「起動時に確かめるか」と飛ばす版の印だけ）。
  - zip は update.json の SHA-256・大きさと照合してから展開し、フォルダの外へ出る名前・最上位が違う名前を拒む。中身の版も確かめる。
  - 差し替えるのは REPLACE_ITEMS だけ（launcher.cs に同じ一覧）。利用者のデータ（作業フォルダ・設定・音を分ける部品）はアプリの
    フォルダの外にあり、触らない。
NLM と違う所:
  - 差し替え役は PyInstaller の exe ではなく起動用の小さな exe（launcher.cs）。差し替えの間は小さな窓（「更新しています」）を出す。
  - ダウンロード・展開は server.start_job の作業（kind='update'・進み具合は /api/job・やめるは /api/job/cancel）。
  - 「起動時に確認する」と飛ばす版は設定（automap/config.py の update_check・update_skip）に置く（窓のアプリは番号ごとに localStorage が
    分かれるため）。言葉は日本語だけ（失敗の文はここで作る）。
  - 作り直し・取り込み等の作業の途中は差し替えない（busy）。展開したフォルダの中身は、置き換える時に「移す」（同じドライブ＝すぐ終わる）。
  - 前の版は <アプリ>/_previous_<版>/ に 1 世代残す（NLM と同じ）。

受け口（server.connect が routes(ctx) をつなぐ）:
  GET  /api/update/status   → 今の版・配布物か・起動時に確かめるか・飛ばす版・更新した直後か・展開済みか・控えた NG（self_ng＝今の版が NG・
                              urgent＝控えた最新の版への更新が急ぎ・ng_at＝控えた時）
  GET  /api/update/check    → 最新の版（新しいか・変更点・大きさ・自動で更新できるか・urgent・self_ng・ng_why・ng_changed＝部品の NG が
                              変わった＝画面が準備の確かめをし直す）。確かめるたびに NG・急ぎの印を設定に控える。失敗は {ok: false, error, message}
  POST /api/update/download → ダウンロード・照合・展開の作業 {id}（/api/job?id= で進み具合 progress・やめる＝/api/job/cancel）
  POST /api/update/apply    → 新しい版の exe に差し替えを任せる（この後、画面が保存して /api/shutdown）
  POST /api/update/settings {auto_check: bool}  → 起動時に確かめるか
  POST /api/update/skip {version}               → 起動時にはその版（とそれより古い版）を知らせない（「この版は飛ばす」）
  POST /api/update/open-releases                → 配布元のページを既定のブラウザで開く（自動で更新できない時）
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automap import config  # noqa: E402
from automap import version as app_version  # noqa: E402

# GitHub のリポジトリ（2026-11-03 に利用者と決めた・変えると配った版が見つけられなくなる。まだリリースが無い間は 404＝起動時は黙る・「更新を確認」は
# 「配布元にまだ更新の情報がありません」）
REPO = 'Oz-Co-two/AutoNotePlotter'
RELEASES = f'https://github.com/{REPO}/releases/'
UPDATE_PATH = 'latest/download/update.json'
ZIP_PATH = 'download/{tag}/{name}'
URL_ENV = 'AUTOMAP_UPDATE_URL'       # 確かめ用: RELEASES の代わり（http://127.0.0.1:<番号>/… だけ）
NO_LAUNCH_ENV = 'AUTOMAP_UPDATE_NO_LAUNCH'   # 確かめ用: 差し替えた後に起動し直さない（=1）
NO_OPEN_ENV = 'AUTOMAP_NO_OPEN'      # 確かめ用: ブラウザを開かない（=1）
FORMAT = 1                           # update.json の形の版。上げたら古い版は自動で更新せず「配布元のページを開く」になる
NAME = 'AutoNotePlotter'
EXE_NAME = NAME + '.exe'
ZIP_TOP = NAME                       # 配布 zip の最上位フォルダ
ZIP_NAME = NAME + '-{version}-win-x64.zip'
# 差し替える物（これ以外には触らない・launcher.cs の ReplaceItems と同じ）。どちらかの側に無い物は飛ばす
REPLACE_ITEMS = (EXE_NAME, 'runtime', 'app', 'automap', 'tools', 'data', 'parts', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'build-info.json')
NEED_ITEMS = (EXE_NAME, 'runtime', 'app', 'automap', 'build-info.json')   # 展開した中身に無ければ壊れている
UPDATE_DIR = '_update'               # アプリの隣の作業フォルダ（ダウンロード・展開先。更新の後に消す）
PREV_PREFIX = '_previous_'           # 差し替える前の版の退避（_previous_v1.0.0/。1 世代だけ残す）
MAX_MANIFEST = 1 << 20
MAX_ZIP = 1 << 30
MAX_UNZIP = 4 << 30
_VER_RE = re.compile(r'v(\d{1,4})\.(\d{1,4})\.(\d{1,4})')
_TAG_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
_SHA_RE = re.compile(r'[0-9a-f]{64}')
_PKG_VER_RE = re.compile(r"""^VERSION\s*=\s*['"]([^'"]+)['"]""", re.M)
_PART_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
_SPEC_RE = re.compile(r'(==|!=|<=|>=|<|>)?\s*[0-9A-Za-z.+!_-]{1,64}')   # tools/sep_install.py の _NG_OP と同じ形
NG_KEY = 'update_ng'   # 設定に控える「最後に確かめた使ってはいけない版・急ぎの印・最新の版」（ネットにつながらない起動でも効かせる）
_lock = threading.Lock()

MESSAGES = {
    'network': 'インターネットにつながらないか、配布元（GitHub）に届きませんでした。ネットの接続を確かめてください。',
    'notFound': '配布元にまだ更新の情報がありません（リリースがまだ無いか、更新の情報が付いていません）。',
    'badManifest': '配布元の更新の情報（update.json）を読めませんでした。',
    'badUrl': '更新の確かめ先の設定（AUTOMAP_UPDATE_URL）が正しくありません（手元の http://127.0.0.1 だけ使えます）。',
    'tooLarge': 'ファイルが大きすぎます。',
    'noSpace': 'アプリのあるドライブの空き容量が足りません。',
    'hash': 'ダウンロードしたファイルが配布元の情報と一致しません（壊れているか、書き換えられた可能性）。更新をやめました。',
    'badZip': 'ダウンロードしたファイルの中身が正しくありません。更新をやめました。',
    'extract': 'ダウンロードしたファイルを展開できませんでした。',
    'notAuto': 'この環境では自動で更新できません。',
    'dev': '開発用の環境（配布物でない）では更新しません。',
    'readonly': 'アプリのフォルダに書き込めないため、自動では更新できません。',
    'noUpdate': '新しい版はありません。',
    'notReady': '更新の準備ができていません（もう一度「更新する」からやり直してください）。',
    'busy': '作り直し・曲の取り込みなどの作業の途中です。終わってから更新してください。',
    'running': 'もう更新をダウンロードしています。',
    'cancelled': 'ダウンロードをやめました。',
}


class UpdateError(Exception):
    """利用者に見せる失敗。code は画面の分け方（起動時は黙る等）、message は見せる文"""
    def __init__(self, code, detail=''):
        self.code, self.detail = code, str(detail)[:300]
        super().__init__(self.message())

    def message(self):
        m = MESSAGES.get(self.code, self.code)
        return m + (f'（{self.detail}）' if self.detail and self.code not in ('hash',) else '')

    def view(self):
        return {'ok': False, 'error': self.code, 'message': self.message(), 'detail': self.detail}


def vtuple(v):
    m = _VER_RE.fullmatch(str(v or ''))
    return tuple(int(x) for x in m.groups()) if m else None


def base_url():
    """取る場所の頭（GitHub のリリース。確かめの時だけ環境変数で手元のサーバーに）"""
    u = os.environ.get(URL_ENV)
    if not u:
        return RELEASES
    p = urllib.parse.urlsplit(u)
    if p.scheme != 'http' or p.hostname not in ('127.0.0.1', 'localhost') or p.query or p.fragment or p.username:
        raise UpdateError('badUrl')
    return u if u.endswith('/') else u + '/'


def _get(url, limit):
    req = urllib.request.Request(url, headers={'User-Agent': 'AutoNotePlotter'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise UpdateError('notFound' if e.code == 404 else 'network', f'HTTP {e.code}')
    except Exception as e:   # noqa: BLE001
        raise UpdateError('network', type(e).__name__)
    if len(data) > limit:
        raise UpdateError('tooLarge')
    return data


def _clean_notes(notes):
    """変更点（版ごとの短い文の並び）。画面に出す文字なので形と長さだけ整える（画面は textContent で入れる）"""
    out = []
    for n in (notes if isinstance(notes, list) else [])[:200]:
        if not isinstance(n, dict) or not vtuple(n.get('version')):
            continue
        xs = n.get('ja')
        out.append({'version': n['version'],
                    'ja': [str(x)[:300] for x in xs[:60] if isinstance(x, str)] if isinstance(xs, list) else []})
    return out


def clean_ng(x):
    """update.json の ng（使ってはいけない版）→ {'app': [版…], 'parts': {部品: [版の決まり…]}, 'why': 文}。形の違う所は黙って捨てる
    （どの版のアプリも読む＝新しい版で書き方が増えても、古い版は知っている所だけ読んで止まらない）"""
    out = {'app': [], 'parts': {}, 'why': ''}
    if not isinstance(x, dict):
        return out
    app = x.get('app')
    if isinstance(app, list):
        out['app'] = sorted({v for v in app[:500] if isinstance(v, str) and vtuple(v)}, key=vtuple)
    parts = x.get('parts')
    if isinstance(parts, dict):
        for name, vers in list(parts.items())[:200]:
            if isinstance(name, str) and _PART_RE.fullmatch(name) and isinstance(vers, list):
                vs = [v.strip() for v in vers[:100] if isinstance(v, str) and _SPEC_RE.fullmatch(v.strip())]
                if vs:
                    out['parts'][name] = vs
    if isinstance(x.get('why'), str):
        out['why'] = x['why'].strip()[:300]
    return out


def clean_urgent(x, latest):
    """update.json の urgent（急ぎの更新の印）→ {版: 理由}。書き方: {版: 理由の文か true}（版ごと）・文か true（最新の版 latest が急ぎ）"""
    if x is True or (isinstance(x, str) and x.strip()):
        x = {latest: x}
    out = {}
    if isinstance(x, dict):
        for v, why in list(x.items())[:200]:
            if isinstance(v, str) and vtuple(v) and (why is True or isinstance(why, str)):
                out[v] = why.strip()[:300] if isinstance(why, str) else ''
    return out


def urgent_for(urgent, cur, latest):
    """今の版 cur から latest へ上げる間（cur より新しく latest まで）に急ぎの版があれば、その理由（文・空のこともある）→ 無ければ None"""
    cv, lv = vtuple(cur), vtuple(latest)
    if not cv or not lv:
        return None
    hits = sorted(((vtuple(v), why) for v, why in urgent.items() if cv < vtuple(v) <= lv), reverse=True)
    if not hits:
        return None
    return ' / '.join(dict.fromkeys(w for _, w in hits if w))


def check_manifest(raw):
    """update.json を確かめて返す。format が違う（新しすぎる）時は manual=True（自動で更新しない）。urgent・ng は形が違っても止めない"""
    try:
        m = json.loads(raw)
        ver = str(m['version'])
        ok = m.get('name') == NAME and vtuple(ver) is not None and isinstance(m.get('format'), int)
    except Exception:   # noqa: BLE001
        ok = False
    if not ok:
        raise UpdateError('badManifest')
    res = {'version': ver, 'notes': _clean_notes(m.get('notes')), 'manual': m['format'] != FORMAT, 'zip': None, 'tag': ver,
           'urgent': clean_urgent(m.get('urgent'), ver), 'ng': clean_ng(m.get('ng'))}
    if not res['manual']:
        z = m.get('zip') or {}
        tag = m.get('tag', ver)
        try:
            zok = (isinstance(z, dict) and z.get('name') == ZIP_NAME.format(version=ver) and _SHA_RE.fullmatch(str(z.get('sha256')))
                   and isinstance(z.get('size'), int) and 0 < z['size'] <= MAX_ZIP and isinstance(tag, str) and _TAG_RE.fullmatch(tag))
        except Exception:   # noqa: BLE001
            zok = False
        if not zok:
            raise UpdateError('badManifest')
        res['zip'] = {'name': z['name'], 'sha256': z['sha256'], 'size': z['size']}
        res['tag'] = tag
    return res


def package_version(d):
    """展開した配布物（または今のアプリのフォルダ）の版。build-info.json と automap/version.py が同じ時だけ → 版か ''"""
    d = Path(d)
    try:
        info = json.loads((d / 'build-info.json').read_text(encoding='utf-8'))
        m = _PKG_VER_RE.search((d / 'automap' / 'version.py').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    v = info.get('version') if isinstance(info, dict) else None
    return v if vtuple(v) and m and m.group(1) == v else ''


def extract_release(zip_path, dst, ver):
    """照合済みの配布 zip を dst へ展開し、中身が ver の Auto Note Plotter であることを確かめる（テスト・build_embed.py からも呼ぶ）"""
    dst = Path(dst)
    tmp = Path(str(dst) + '.tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        try:
            zf = zipfile.ZipFile(zip_path)
        except (zipfile.BadZipFile, OSError) as e:
            raise UpdateError('badZip', type(e).__name__)
        with zf:
            total = 0
            for info in zf.infolist():
                name = info.filename
                parts = name.rstrip('/').split('/')
                # フォルダの外へ出る名前・絶対パス・ドライブ名・'\\' を含む名前・最上位のフォルダが違う名前は拒む（zip slip）
                if (not name or name.startswith('/') or '\\' in name or ':' in name
                        or any(p in ('..', '.', '') for p in parts) or parts[0] != ZIP_TOP):
                    raise UpdateError('badZip', name[:120])
                if (info.external_attr >> 16) & 0o170000 == 0o120000:   # 記号リンクは入れない
                    raise UpdateError('badZip', name[:120])
                total += info.file_size
                if total > MAX_UNZIP:
                    raise UpdateError('tooLarge')
            tmp.mkdir(parents=True)
            try:
                zf.extractall(tmp)
            except (zipfile.BadZipFile, OSError, EOFError) as e:
                raise UpdateError('extract', type(e).__name__)
        top = tmp / ZIP_TOP
        missing = [n for n in NEED_ITEMS if not (top / n).exists()]
        if missing:
            raise UpdateError('badZip', '足りない物: ' + '・'.join(missing))
        got = package_version(top)
        if got != ver:
            raise UpdateError('badZip', f'中身の版が {got or "読めない"}（{ver} のはず）')
        shutil.rmtree(dst, ignore_errors=True)
        os.replace(tmp, dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _spawn(args, cwd):
    """このアプリが終わっても動き続けるように起動する（DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP）。アプリが閉じると中を全部止める
    Windows のジョブの中で動いていれば、ジョブの外へ出す（出られない決まりのジョブなら、そのまま）"""
    if sys.platform != 'win32':
        subprocess.Popen(args, cwd=cwd, close_fds=True)
        return
    flags = 0x00000008 | 0x00000200
    try:
        subprocess.Popen(args, cwd=cwd, close_fds=True, creationflags=flags | 0x01000000)   # CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen(args, cwd=cwd, close_fds=True, creationflags=flags)


def _open_url(url):
    if os.environ.get(NO_OPEN_ENV) != '1':
        import webbrowser
        webbrowser.open(url)
    return {'ok': True, 'opened': url}


class Updater:
    """1 プロセスに 1 つ（routes が作る）。app_dir＝配布物のフォルダ（AutoNotePlotter.exe の隣）"""
    def __init__(self, app_dir=ROOT, distributed=None, current=None):
        self.app_dir = Path(app_dir)
        # 本物の配布物だけ（配布物のふり＝tools/dist/checkset.py dev はソースのまま＝差し替えるとリポジトリを書き換える）
        self.distributed = config.packaged() if distributed is None else bool(distributed)
        self._current = current
        self.ready = None          # 展開まで済んだ {'version', 'dir'}
        self.job = None            # ダウンロードの作業（server.start_job の job）
        self.applying = None       # 差し替えを任せた版
        self.just_updated = None   # 起動し直した直後なら {'from', 'to'}（startup が入れる）
        self.started = False

    @property
    def work(self):
        return self.app_dir / UPDATE_DIR

    def current(self):
        return self._current or app_version.VERSION

    def auto_mode(self):
        """'ok'＝自動で更新できる / 'dev'＝配布物でない（開発の PC）/ 'readonly'＝アプリのフォルダに書けない"""
        if not self.distributed:
            return 'dev'
        try:   # _update/ ではなくアプリの隣で試す（起動直後の startup が _update/ を消している最中でも見誤らない）
            p = self.app_dir / '.anp-write-test'
            p.write_text('1', encoding='ascii')
            p.unlink()
            return 'ok'
        except OSError:
            return 'readonly'

    def downloading(self):
        return bool(self.job and self.job.get('state') == 'running')

    def status(self, cfg=None):
        cfg = config.load() if cfg is None else cfg
        cur = self.current()
        saved = cfg.get(NG_KEY) if isinstance(cfg.get(NG_KEY), dict) else {}
        ng = clean_ng(saved)
        latest = saved.get('latest') if vtuple(saved.get('latest')) else None
        newer = bool(latest and vtuple(cur) and vtuple(latest) > vtuple(cur))
        urgent = urgent_for(clean_urgent(saved.get('urgent'), latest), cur, latest) if newer else None
        return {'ok': True, 'current': cur, 'distributed': self.distributed, 'auto_check': cfg.get('update_check', True) is not False,
                'skip': cfg.get('update_skip') if vtuple(cfg.get('update_skip')) else None, 'justUpdated': self.just_updated,
                'ready': self.ready['version'] if self.ready else None, 'job': self.job['id'] if self.downloading() else None,
                'releases': RELEASES + 'latest',
                # 前に確かめた時に控えた物（ネットにつながらない起動でも、今の版が NG・急ぎの新しい版を知っていれば強い知らせ）
                'self_ng': cur in ng['app'], 'ng_why': ng['why'], 'ng_at': str(saved.get('at') or '')[:19] or None,
                'known_latest': latest if newer else None, 'urgent': urgent is not None, 'urgent_why': urgent or ''}

    def check(self, cfg_path=None):
        """最新の版を確かめる。cfg_path を渡すと（受け口）、NG・急ぎの印を設定に控える（直に呼ぶテストは控えない）"""
        m = check_manifest(_get(base_url() + UPDATE_PATH, MAX_MANIFEST))
        cur = self.current()
        cv, lv = vtuple(cur), vtuple(m['version'])
        newer = bool(cv and lv > cv)
        notes = sorted([n for n in m['notes'] if cv and cv < vtuple(n['version']) <= lv], key=lambda n: vtuple(n['version']), reverse=True)
        urgent = urgent_for(m['urgent'], cur, m['version']) if newer else None
        changed = self.remember(m, cfg_path) if cfg_path is not None else False
        return {'ok': True, 'current': cur, 'latest': m['version'], 'newer': newer, 'notes': notes,
                'size': m['zip']['size'] if m['zip'] else 0, 'auto': 'manual' if m['manual'] else self.auto_mode(),
                'ready': bool(self.ready and self.ready['version'] == m['version']),
                'urgent': urgent is not None, 'urgent_why': urgent or '', 'self_ng': cur in m['ng']['app'], 'ng_why': m['ng']['why'],
                'ng_changed': changed}

    def remember(self, m, cfg_path):
        """確かめた update.json の NG・急ぎの印・最新の版を設定（NG_KEY）に控える（変わった時と日が変わった時だけ書く）
        → 音を分ける部品の NG が前の控えと変わったか（画面が準備の確かめをし直す）"""
        new = {'app': m['ng']['app'], 'parts': m['ng']['parts'], 'why': m['ng']['why'], 'urgent': m['urgent'], 'latest': m['version'],
               'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
        try:
            old = config.load(cfg_path).get(NG_KEY)
            old = old if isinstance(old, dict) else {}
            if any(old.get(k) != new[k] for k in ('app', 'parts', 'why', 'urgent', 'latest')) or str(old.get('at', ''))[:10] != new['at'][:10]:
                config.update({NG_KEY: new}, cfg_path)
        except (OSError, ValueError):   # 設定が読めない・書けない＝控えない（確かめの答えはそのまま返す）
            return False
        return clean_ng(old)['parts'] != new['parts']

    # ---- ① ダウンロード・照合・展開（server.start_job の作業。進み具合は job['progress']）----
    def start_download(self, ctx):
        with _lock:
            if self.downloading():
                raise UpdateError('running')
            mode = self.auto_mode()
            if mode != 'ok':
                raise UpdateError(mode if mode in ('dev', 'readonly') else 'notAuto')
            m = check_manifest(_get(base_url() + UPDATE_PATH, MAX_MANIFEST))   # 画面から版を受け取らず、もう一度ここで読む
            if m['manual'] or not (vtuple(m['version']) > (vtuple(self.current()) or (0, 0, 0))):
                raise UpdateError('noUpdate')
            try:
                free = shutil.disk_usage(self.app_dir).free
            except OSError:
                free = None
            need = m['zip']['size'] * 4   # zip＋展開した物（zip の 3 倍ほど）。前の版は移すだけなので増えない
            if free is not None and free < need:
                raise UpdateError('noSpace', f'{need / 1e6:.0f}MB ほど要る・空き {free / 1e6:.0f}MB')
            self.ready = None
            self.job = ctx.start_job(None, [(f'{m["version"]} をダウンロードして展開する', lambda job: self._download(job, m))], kind='update',
                                     after=self._after, version=m['version'], progress={'stage': 'download', 'done': 0, 'total': m['zip']['size']})
        return {'ok': True, 'id': self.job['id'], 'version': m['version']}

    def _download(self, job, m):
        z, ver = m['zip'], m['version']
        part = self.work / (z['name'] + '.part')
        try:
            shutil.rmtree(self.work / 'new', ignore_errors=True)
            self.work.mkdir(parents=True, exist_ok=True)
            url = base_url() + ZIP_PATH.format(tag=urllib.parse.quote(m['tag']), name=urllib.parse.quote(z['name']))
            req = urllib.request.Request(url, headers={'User-Agent': 'AutoNotePlotter'})
            h, done = hashlib.sha256(), 0
            try:
                with urllib.request.urlopen(req, timeout=60) as r, open(part, 'wb') as f:
                    while True:
                        if job.get('cancel'):
                            raise UpdateError('cancelled')
                        b = r.read(256 * 1024)
                        if not b:
                            break
                        done += len(b)
                        if done > z['size']:
                            raise UpdateError('hash')
                        h.update(b)
                        f.write(b)
                        job['progress'] = {'stage': 'download', 'done': done, 'total': z['size']}
            except UpdateError:
                raise
            except urllib.error.HTTPError as e:
                raise UpdateError('notFound' if e.code == 404 else 'network', f'HTTP {e.code}')
            except Exception as e:   # noqa: BLE001
                raise UpdateError('network', type(e).__name__)
            if done != z['size'] or h.hexdigest() != z['sha256']:
                raise UpdateError('hash')
            job['progress'] = {'stage': 'extract', 'done': done, 'total': z['size']}
            job['log'] += f'照合できた（{done / 1e6:.1f}MB・SHA-256 一致）。展開する\n'
            try:
                extract_release(part, self.work / 'new', ver)
            except UpdateError:
                raise
            except Exception as e:   # noqa: BLE001
                raise UpdateError('extract', f'{type(e).__name__}: {e}')
            self.ready = {'version': ver, 'dir': str(self.work / 'new' / ZIP_TOP)}
            job['progress'] = {'stage': 'ready', 'done': done, 'total': z['size']}
        except UpdateError as e:
            job['error'], job['message'] = e.code, e.message()
            raise
        finally:
            try:
                part.unlink()
            except OSError:
                pass

    def _after(self, job):
        if job['state'] != 'done' or not self.ready:
            self.ready = None
            shutil.rmtree(self.work / 'new', ignore_errors=True)
            if job.get('cancelled') and not job.get('error'):
                job['error'], job['message'] = 'cancelled', MESSAGES['cancelled']

    # ---- ② 新しい版の exe に差し替えを任せる（この後、画面が作業ファイルを保存して /api/shutdown を呼ぶ）----
    def apply(self, ctx, pid=None):
        mode = self.auto_mode()
        if mode != 'ok':
            raise UpdateError(mode if mode in ('dev', 'readonly') else 'notAuto')
        if not self.ready:
            raise UpdateError('notReady')
        others = sorted({j.get('kind') or '作業' for j in list(ctx.JOBS.values()) if j.get('state') == 'running' and j.get('kind') != 'update'})
        if others:
            raise UpdateError('busy', '・'.join(others))
        new_dir = Path(self.ready['dir'])
        # 展開した場所と中身の版をもう一度確かめる（ダウンロードから時間が経っている）
        if new_dir != self.work / 'new' / ZIP_TOP or package_version(new_dir) != self.ready['version'] or not (new_dir / EXE_NAME).is_file():
            self.ready = None
            raise UpdateError('notReady')
        args = [str(new_dir / EXE_NAME), '--apply-update', '--target', str(self.app_dir), '--pid', str(pid or os.getpid())]
        if os.environ.get(NO_LAUNCH_ENV) == '1':
            args.append('--no-launch')
        try:
            (self.work / 'applied.json').unlink()
        except OSError:
            pass
        _spawn(args, str(new_dir))
        self.applying = self.ready['version']
        return {'ok': True, 'version': self.ready['version']}


# ---- ④ 起動し直した後の片付け（routes が 1 度だけ呼ぶ）----
def startup(u):
    """更新した直後なら「更新しました」用に版を覚え、_update/ を消す（差し替え役の exe が終わるのを待って少し粘る）。
    差し替えの記録（_update/apply.log）は消す前に <LOCALAPPDATA>/AutoNotePlotter/update.log へ写す（うまくいかなかった時に見る）"""
    if u.started:
        return
    u.started = True
    work = u.work
    if not work.is_dir():
        return
    try:
        a = json.loads((work / 'applied.json').read_text(encoding='utf-8'))
        if vtuple(a.get('to')):
            u.just_updated = {'from': str(a.get('from', ''))[:40], 'to': a['to']}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        log = (work / 'apply.log').read_text(encoding='utf-8', errors='replace')
        d = config.app_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / 'update.log', 'a', encoding='utf-8') as f:
            f.write(log[-20000:] + '\n')
    except OSError:
        pass

    def clean():
        for _ in range(60):
            if u.job is not None:
                return   # このプロセスで更新を始めた＝消さない
            shutil.rmtree(work, ignore_errors=True)
            if not work.exists():
                return
            time.sleep(1)
    threading.Thread(target=clean, name='update-clean', daemon=True).start()


UPDATER = None


def updater():
    global UPDATER
    if UPDATER is None:
        UPDATER = Updater()
    return UPDATER


def routes(ctx):
    u = updater()
    startup(u)

    def wrap(fn):
        def run(arg):
            try:
                return fn(arg)
            except UpdateError as e:
                return e.view()
        return run

    def settings(b):
        on = b.get('auto_check')
        if not isinstance(on, bool):
            raise ValueError('auto_check は true か false')
        config.update({'update_check': on}, ctx.CONFIG)
        return u.status(config.load(ctx.CONFIG))

    def skip(b):
        v = b.get('version')
        if v is not None and not vtuple(v):
            raise ValueError('版の形が違います')
        config.update({'update_skip': v}, ctx.CONFIG)
        return u.status(config.load(ctx.CONFIG))

    get = {'/api/update/status': lambda q: u.status(config.load(ctx.CONFIG)),
           '/api/update/check': wrap(lambda q: u.check(ctx.CONFIG))}
    post = {'/api/update/download': wrap(lambda b: u.start_download(ctx)),
            '/api/update/apply': wrap(lambda b: u.apply(ctx)),
            '/api/update/settings': settings, '/api/update/skip': skip,
            '/api/update/open-releases': lambda b: _open_url(RELEASES + 'latest')}
    return get, post
