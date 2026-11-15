"""曲のデータ（/api/song＝server.song_data の答え）のディスクの控え（2026-11-09 利用者「曲を開くのが遅い」）。

曲を開くのは 1 曲 2.5〜5 秒（分けた音の FLAC 4 つの読み込み・music.beat_features・hooks.detect）で、アプリで一番重かった。答えを
曲ごとに `<cache>/<曲>/song_data.<鍵>.json.gz` に控え、鍵が合えば読むだけにする（重い部品も読まない＝起動して最初の曲が速い）。

- 鍵＝入力（server.data_inputs: 元にした .nlmf・聞き比べの帯に出すほかの版の .nlmf・こちらで書いた印（out/.state/）・分けた音のフォルダの
  使うファイルの更新時刻と大きさ・基準の難易度）＋作り方の版（CODE）。結果のファイルを作り直した・NLM で保存した・基準の難易度を
  置き直した・分けた音を作り直した、で鍵が変わる＝作り直す。
- 作り方の版＝曲のデータを作るコードのファイルの中身の指紋: ROOTS（app/server.py・app/songdata.py・このファイル）から、automap の
  読み込み（`from automap import …`・`from automap.x import …`・`import automap.x`・automap の中の `from . import …`・関数の中の物も）を
  たどったファイル全部（code_files）の中身の sha1＋アプリの版（automap/version.py の VERSION）・Python の版。曲のデータを作るコードを
  直すと控えが自然に外れる（手で上げる版の数は無い・作る処理 flow.py 等を直しても外れない）。曲のデータを作る時に
  読む automap・tools・app のモジュールが全部ここに入っていることは tests/test_songcache.py が確かめる（server の song_data・chart から
  automap.lazy の `cli` の重い側を使い始めたら、そこで落ちる＝たどれない読み方を足したら ROOTS か読み方を直す）。
- 版はこのモジュールを読んだ時（＝サーバーの起動）に測る＝このプロセスが読むコードの版。測った後にファイルが変わったら（サーバーが
  動いている間にコードを直した）、控えを書かない（古いコードで作った物を新しい版の鍵で残さない・changed）。
- 曲ごとに 1 つだけ残す（書いたら同じ曲のほかの控えを消す）。読めない・壊れている控えは無い物として作り直す（上書きする）。
- 中身は server._send と同じ形の JSON（separators=(',', ':')・ensure_ascii=False）を gzip（level 6）で（2026-11-09 に Brotherhood で測った:
  502KB → 126KB・書くのは 15ms＝作る数秒に比べて小さい・読むのは圧縮しない物と同じ 15〜20ms＝ほぼ JSON を読む時間・PC を起動した直後の
  読み込みが 1/4 に）。JSON の数は Python の repr で往復するので、控えから返した物を JSON にすると作った物と 1 バイトも
  違わない（tests/test_songcache.py）。
"""
import gzip
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ROOTS = (ROOT / 'app' / 'server.py', ROOT / 'app' / 'songdata.py', Path(__file__).resolve(),
         ROOT / 'app' / 'names.py')   # 名前の確かめ（server.py が読む・2026-11-11）
PKG = ROOT / 'automap'
PREFIX, SUFFIX = 'song_data.', '.json.gz'
FORMAT = 1   # 控えのファイルの形（変えたら上げる＝前の控えを読まない）

_IMPORT = re.compile(r'^[ \t]*(?:from[ \t]+(\.+[\w.]*|automap(?:\.[\w.]+)?)[ \t]+import[ \t]+(\([^)]*\)|[^\n#;]+)'
                     r'|import[ \t]+(automap\.[\w.]+))', re.M)


def _module_file(parts):
    """automap の中のモジュール（パッケージからの名前の並び）→ ファイル（無ければ None）"""
    p = PKG.joinpath(*parts)
    for f in (p.with_suffix('.py'), p / '__init__.py'):
        if f.is_file():
            return f
    return None


def _imports(f, text):
    """ファイルの中の automap の読み込み → 読むファイルの集まり"""
    out = set()
    in_pkg = PKG in f.parents
    for m in _IMPORT.finditer(text):
        mod, names, plain = m.group(1), m.group(2), m.group(3)
        if plain:
            base = plain.split('.')[1:]
            names = ''
        elif mod.startswith('.'):
            if not in_pkg:
                continue
            dots = len(mod) - len(mod.lstrip('.'))
            pkg = f.parent
            for _ in range(dots - 1):
                pkg = pkg.parent
            rest = [x for x in mod.lstrip('.').split('.') if x]
            base = list(pkg.relative_to(PKG).parts) + rest
        else:
            base = mod.split('.')[1:]
        found = _module_file(base) if base else None
        if found:
            out.add(found)
        for nm in (names or '').strip().strip('()').split(','):
            nm = nm.strip().split()[0] if nm.strip() else ''
            sub = _module_file(base + [nm]) if nm and nm.isidentifier() else None
            if sub:
                out.add(sub)
    return out


def code_files():
    """曲のデータを作るコードのファイル（ROOTS から automap の読み込みをたどった全部・並びは決まった順）"""
    seen, todo = set(), [Path(r) for r in ROOTS]
    while todo:
        f = todo.pop()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        todo.extend(_imports(f, f.read_text(encoding='utf-8', errors='replace')) - seen)
        todo.extend(q / '__init__.py' for q in f.parents if q == PKG or PKG in q.parents)   # パッケージの頭（読むと必ず動く）
    return sorted(seen, key=lambda p: p.relative_to(ROOT).as_posix())


def _stats(files):
    out = []
    for f in files:
        try:
            st = f.stat()
            out.append((f.relative_to(ROOT).as_posix(), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((f.relative_to(ROOT).as_posix(), None, None))
    return out


def _measure():
    """→ (版, ファイル, ファイルの更新時刻と大きさ)。版にはアプリの版（automap/version.py の VERSION）と Python の版も入れる（更新で部品
    （numpy 等）が変わる時も外す）。ROOTS のどれかが無い（.py を入れない配布物等＝コードの中身で版を測れない）時は版を None＝控えを使わない"""
    files = code_files()
    if not all(Path(r).is_file() for r in ROOTS):
        return None, files, _stats(files)
    from automap import version
    h = hashlib.sha1(f'format {FORMAT}\napp {version.VERSION}\npython {sys.version_info[0]}.{sys.version_info[1]}\n'.encode())
    for f in files:
        h.update(f.relative_to(ROOT).as_posix().encode('utf-8') + b'\0')
        h.update(f.read_bytes())
        h.update(b'\0')
    return h.hexdigest()[:16], files, _stats(files)


CODE, CODE_FILES, _CODE_STATS = _measure()   # このプロセスが読むコードの版（サーバーを起動した時）


def changed():
    """版を測った後にコードのファイルが変わったか（変わっていたら控えを書かない）"""
    return _stats(CODE_FILES) != _CODE_STATS


def stat_key(p):
    """入力のファイル → [名前, 更新時刻（ns）, 大きさ]（無ければ時刻と大きさは None）"""
    try:
        st = Path(p).stat()
        return [Path(p).name, st.st_mtime_ns, st.st_size]
    except OSError:
        return [Path(p).name, None, None]


def key_of(inputs):
    """入力（JSON にできる物）＋作り方の版 → 鍵（16 文字）"""
    s = json.dumps({'code': CODE, 'in': inputs}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def path_of(folder, key):
    return Path(folder) / f'{PREFIX}{key}{SUFFIX}'


def load(folder, key):
    """控え → 曲のデータ（dict）。無い・読めない・壊れている・版を測れない → None"""
    if CODE is None:
        return None
    p = path_of(folder, key)
    try:
        with gzip.open(p, 'rb') as f:
            d = json.loads(f.read().decode('utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, EOFError, ValueError, UnicodeDecodeError):   # 壊れた・書きかけ（gzip の終わりが無い等）＝作り直す
        return None
    return d if isinstance(d, dict) else None


_WRITE = threading.Lock()


def save(folder, key, d):
    """控えを書き（書きかけを読ませないように別の名前で書いてから置き換える）、同じ曲のほかの控えを消す。書けなくても曲は開く（False）"""
    folder = Path(folder)
    if CODE is None or not folder.is_dir():
        return False
    p = path_of(folder, key)
    body = json.dumps(d, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    tmp = p.with_name(f'{p.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    with _WRITE:
        try:
            tmp.write_bytes(gzip.compress(body, compresslevel=6, mtime=0))
            os.replace(tmp, p)
        except OSError:   # 書けない場所・ほかのプロセスが同じ控えを読んでいる（Windows は開いている物を置き換えられない）
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        now = time.time()
        for q in folder.glob(f'{PREFIX}*'):
            try:
                # 前の鍵の控え・書きかけのまま止まった物（ほかのプロセスが今書いている物は消さない）
                if (q.name.endswith(SUFFIX) and q.name != p.name) or (q.name.endswith('.tmp') and now - q.stat().st_mtime > 600):
                    q.unlink()
            except OSError:   # ほかのプロセスが読んでいる・もう消えた（次に書く時に消す）
                pass
    return True
