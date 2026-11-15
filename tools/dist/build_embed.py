"""配布物（Windows・Python の入っていない PC でそのまま動く zip）の試作を作る（docs/アプリ仕様.md 21 節・2026-11-03）。

作り方: python.org の「埋め込み用の Python」（embeddable zip・10MB ほど）＋部品（tools/dist/requirements-dist.txt を pip --target で）＋
  このリポジトリの app/・automap/・tools/ をそのまま＋起動用の小さな exe（tools/dist/launcher.cs を Windows の .NET Framework 4 の
  csc.exe で翻訳・アイコンは app/desktop.py がコードで描く物）。
  PyInstaller で固めない理由は tools/dist/README.md（作り直し・曲の解析を `sys.executable -m automap …` の別のプロセスで動かしている＝
  本物の python.exe が要る・音を分けるパックも同じ Python を使い回せる）。

使い方（ビルド用の環境は .venv と分ける。Python の版は埋め込み用と同じ 3.14 に）:
  py -3.14 -m venv <作業>/venv-build
  <作業>/venv-build/Scripts/python.exe tools/dist/build_embed.py --work <作業> [--compile] [--zip]
出力: <作業>/build/AutoNotePlotter/（そのまま動くフォルダ）・--zip で <作業>/build/release/ に GitHub のリリースに添付する 2 つ
  （AutoNotePlotter-<版>-win-x64.zip と update.json＝アプリの更新が読む・app/update.py）。
  ダウンロードした埋め込み用の Python は <作業>/downloads/ に置いて使い回す。
版: automap/version.py の VERSION（build-info.json・zip の名前・update.json）。変更点は同じファイルの CHANGES（頭の版が VERSION と違うと止まる）。
  --version v〇.〇.〇 は確かめ用（配布物の中の automap/version.py の VERSION の行だけ書き換える＝更新の確かめに 2 つの版を作る）。
  急ぎの印・使ってはいけない版は同じファイルの URGENT・NG（update.json の urgent・ng）。出す版が NG に当たる・この版の音を分ける部品の
  一覧に NG の版がある時は止まる。出したリリースの update.json の urgent・ng だけ書き換えるのは
  `build_embed.py --refresh-manifest <update.json> [--out <書く場所>]`（作り直さない・tools/dist/README.md の「リリースした後に問題が分かった時」）。

中身:
  AutoNotePlotter/
    AutoNotePlotter.exe        起動用（runtime\\pythonw.exe app\\desktop.py・ほかの Python の環境変数を消す）
    runtime/               埋め込み用の Python（._pth に本体の場所を足す）＋ Lib/site-packages/
    app/ automap/ tools/   このリポジトリの写し（__pycache__・config.local.json は入れない）。automap/__pycache__ には流れの計算（Numba）の
                           コンパイル済みの控え（flow_nb.*.nbi・.nbc・NUMBA_CPU_NAME=generic で作る・warm_flow）
    data/library-dist.sqlite  配布用の型のライブラリ（tools/library_build/make_dist.py・automap/library_db.BUNDLED）
    parts/nlm-rating/      ★を測る部品（nlm-rating・MIT・automap/rating.BUNDLED・LICENSE と THIRD_PARTY_NOTICES も一緒）
    LICENSE  THIRD_PARTY_NOTICES.md  build-info.json（version＝automap/version.py の VERSION・git＝git describe）
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NAME = 'AutoNotePlotter'      # Auto Note Plotter（ANP・2026-11-03 に決めた・docs/アプリ仕様.md 21 節）
EXE = NAME + '.exe'
PY_URL = 'https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip'
# 埋め込み用の Python の指紋（初めて取った時に出る値を python.org の公開の値と確かめてから入れる）
PY_VERSION = '3.14.10'   # 配布物に入れる Python（2026-10-25・3.14.8〜3.14.10 は SSL・zipfile・tarfile・urllib の脆弱性を直した版）。
# 版を上げる時: python.org の最新の 3.14.x を確かめ、そのページの Windows embeddable package (64-bit) の SHA-256 を下に足す（ダウンロードして同じか確かめてから）
PY_SHA256 = {'3.14.10': '90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'}   # python.org の公開の値（2026-11-03 に確かめた）
CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
SRC_DIRS = ('app', 'automap', 'tools')
SKIP = {'__pycache__', '.pytest_cache', 'config.local.json'}
SKIP_REL = {'tools/dist'}     # ビルドの台本は配布物に要らない
TOP_FILES = ('LICENSE', 'THIRD_PARTY_NOTICES.md')   # 部品ごとのライセンスは runtime\Lib\site-packages\*.dist-info に残る


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def fetch(url, dst):
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    log(f'取る: {url}')
    tmp = dst.with_suffix(dst.suffix + '.part')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'AutoNotePlotter-build'}), timeout=60) as r, \
            open(tmp, 'wb') as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dst)
    return dst


def run(cmd, **kw):
    log('$ ' + ' '.join(str(c) for c in cmd)[:300])
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def du(p):
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob('*') if f.is_file())


def mb(n):
    return f'{n / 1e6:.1f} MB'


def copy_src(dst):
    """app/・automap/・tools/ を写す（__pycache__・環境ごとの設定・ビルドの台本は除く）"""
    n = 0
    for top in SRC_DIRS:
        for f in sorted((REPO / top).rglob('*')):
            rel = f.relative_to(REPO)
            parts = set(rel.parts)
            if parts & SKIP or any(rel.as_posix() == s or rel.as_posix().startswith(s + '/') for s in SKIP_REL) or not f.is_file():
                continue
            if f.suffix in ('.pyc', '.pyo'):
                continue
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out)
            n += 1
    for name in TOP_FILES:
        if (REPO / name).exists():
            shutil.copy2(REPO / name, dst / name)
    return n


VC_RT = ('msvcp', 'vcruntime', 'vcomp', 'concrt')
ALWAYS_VC = ('msvcp140.dll', 'vcomp140.dll')


def bundle_parts(out, library=None, rating=None):
    """配布用の型のライブラリ（data/）と★を測る部品（parts/nlm-rating/）を入れる。場所は引数か、開発の PC の設定
    （library_db の隣の library-dist.sqlite・nlm_rating_exe のフォルダ）→ 入れた物の説明"""
    sys.path.insert(0, str(REPO))
    from automap import config, rating_scale   # noqa: E402
    cfg = config.load()
    lib = Path(library) if library else (Path(cfg['library_db']).parent / 'library-dist.sqlite' if cfg.get('library_db') else None)
    if not lib or not lib.is_file():
        raise SystemExit(f'配布用の型のライブラリが無い（{lib}）: tools/library_build/make_dist.py で作るか --library で渡す')
    rd = Path(rating) if rating else (Path(cfg['nlm_rating_exe']).parent if cfg.get('nlm_rating_exe') else None)
    if not rd or not (rd / 'nlm-rating.exe').is_file():
        raise SystemExit(f'nlm-rating のフォルダが無い（{rd}）: --rating で nlm-rating.exe のあるフォルダを渡す')
    bad = rating_scale.problems(exe=rd / 'nlm-rating.exe', db=lib)   # ★の物差しがそろっていない組は配らない（automap/rating_scale.py）
    if bad:
        raise SystemExit('★の物差しがそろっていない（tools/library_build/update_rating.py でそろえる）:\n  ' + '\n  '.join(bad))
    (out / 'data').mkdir(exist_ok=True)
    shutil.copy2(lib, out / 'data' / 'library-dist.sqlite')
    shutil.copytree(rd, out / 'parts' / 'nlm-rating', dirs_exist_ok=True)
    return [f'型のライブラリ {mb(lib.stat().st_size)}（{lib.name}）', f'nlm-rating {mb(du(rd))}（{rd.name}）']


def copy_vc_runtime(out, rt):
    """配布物の .pyd・.dll が読む Visual C++ の部品のうち、読む物の隣にも runtime\\ にも無い物を System32 から写す → 写した名前"""
    sys.path.insert(0, str(HERE))
    from check_dist import pe_imports   # noqa: E402
    sysdir = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32'
    want = set()
    for p in out.rglob('*'):
        if p.suffix.lower() not in ('.pyd', '.dll'):
            continue
        try:
            names = pe_imports(p)
        except Exception:   # noqa: BLE001
            continue
        for d in names:
            dl = d.lower()
            if dl.startswith(VC_RT) and '-' not in dl and not (p.parent / dl).exists() and not (rt / dl).exists():
                want.add(dl)
    done = []
    # 音を分けるパック（tools/sep_install.py）の PyTorch もここの msvcp140・vcomp140 を写して使う＝本体の部品が読まなくても必ず入れる
    want |= {d for d in ALWAYS_VC if not (rt / d).exists()}
    for dl in sorted(want):
        src = sysdir / dl
        if not src.exists():
            raise SystemExit(f'{dl} がこの PC の System32 に無い（Visual C++ の再頒布可能パッケージ x64 を入れてからビルドする）')
        shutil.copy2(src, rt / dl)
        done.append(dl)
    return done


def make_icon(path):
    sys.path.insert(0, str(REPO / 'app'))
    import desktop   # noqa: E402  （頭は標準の部品だけ＝読み込むだけなら害が無い）
    path.write_bytes(desktop._ico_bytes())
    return path


def compile_launcher(dst, ico=None, quiet=False):
    """launcher.cs を exe に（テスト tests/test_update.py も使う）"""
    if not CSC.exists():
        raise SystemExit(f'csc.exe が無い（.NET Framework 4）: {CSC}')
    cmd = [CSC, '/nologo', '/codepage:65001', '/target:winexe', '/optimize+', '/platform:anycpu', f'/out:{dst}',
           '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', HERE / 'launcher.cs']
    if ico:
        cmd.insert(-1, f'/win32icon:{ico}')
    if quiet:
        subprocess.run([str(c) for c in cmd], check=True, capture_output=True)
    else:
        run(cmd)
    return dst


def build_launcher(out, work):
    compile_launcher(out / EXE, make_icon(work / 'automap.ico'))


# ---- 版と更新の情報（app/update.py が読む形・版をまたぐ約束は app/update.py の頭）----
VER_LINE = re.compile(r"""^VERSION\s*=\s*['"]([^'"]*)['"]""", re.M)


def warm_flow(rt, out):
    """流れの計算のコンパイル済みの控えを配布物の中に作る → 控えのファイルの数（.nbi・.nbc）"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'NUMBA_'))}
    env.update(NUMBA_CPU_NAME='generic', PYTHONIOENCODING='utf-8')
    run([rt / 'python.exe', '-c', 'import automap.flow_nb as f; f.warm()'], cwd=str(out), env=env)
    got = sorted((out / 'automap' / '__pycache__').glob('flow_nb.*.nb[ic]'))
    if not any(g.suffix == '.nbi' for g in got):
        raise SystemExit('流れの計算のコンパイル済みの控えができていない（automap/__pycache__/flow_nb.*.nbi）')
    return len(got)


def app_version():
    sys.path.insert(0, str(REPO))
    from automap import version   # noqa: E402
    return version


def set_version(out, ver):
    """確かめ用（--version）: 配布物の中の automap/version.py の VERSION の行だけ書き換える"""
    p = out / 'automap' / 'version.py'
    text = p.read_text(encoding='utf-8')
    if not VER_LINE.search(text):
        raise SystemExit('automap/version.py に VERSION の行が無い')
    p.write_text(VER_LINE.sub(f"VERSION = '{ver}'", text, count=1), encoding='utf-8')


def release_notes(ver):
    """update.json の notes（新しい順・automap/version.py の CHANGES）。確かめ用の版が CHANGES に無ければ一言を足す"""
    notes = [{'version': v, 'ja': list(items)} for v, items in app_version().CHANGES]
    if not any(n['version'] == ver for n in notes):
        notes.insert(0, {'version': ver, 'ja': ['（確かめ用の版）']})
    return notes


def flags(ver=None):
    """automap/version.py の URGENT・NG → update.json の urgent・ng（app/update.py が読む形）。書き方の誤りで読み飛ばされる所があれば止める。
    ver（新しく出す版）を渡すと、その版が NG のアプリの版に入っていないか・その版の音を分ける部品の一覧に NG の版が無いかも確かめる"""
    sys.path.insert(0, str(REPO / 'app'))
    sys.path.insert(0, str(REPO / 'tools'))
    import update   # noqa: E402
    V = app_version()
    raw_ng = getattr(V, 'NG', None) or {}
    raw_urgent = getattr(V, 'URGENT', None) or {}
    ng = update.clean_ng(raw_ng)
    urgent = update.clean_urgent(raw_urgent, ver or V.VERSION)
    lost = []
    if not isinstance(raw_ng, dict) or set(raw_ng) - {'app', 'parts', 'why'}:
        lost.append('NG の項目は app・parts・why だけ')
    elif len(ng['app']) != len(set(raw_ng.get('app') or [])) or ng['parts'] != {k: [str(x).strip() for x in v] for k, v in (raw_ng.get('parts') or {}).items()}:
        lost.append(f'NG の書き方が違う所がある（読める形: {ng}）')
    if not isinstance(raw_urgent, dict) or len(urgent) != len(raw_urgent):
        lost.append(f'URGENT の書き方が違う所がある（{{版: 理由}}・読める形: {urgent}）')
    if lost:
        raise SystemExit('automap/version.py: ' + '・'.join(lost))
    if ver:
        if ver in ng['app']:
            raise SystemExit(f'出す版 {ver} が NG の app に入っている（直してから出す）')
        import sep_install   # noqa: E402  （tools/sep_install.py・この版の音を分ける部品の一覧）
        bad = sep_install.set_ng(None, ng)
        if bad:
            raise SystemExit('この版の音を分ける部品の一覧（tools/sep_install.py）に NG の版がある: '
                             + '・'.join(f'{b["name"]} {b["version"]}' for b in bad) + '（一覧の版を直してから出す）')
    return urgent, ng


def make_release(out, ver, rel, level=9):
    """GitHub のリリースに添付する 2 つ（zip と update.json）を rel に作り、アプリと同じ確かめ（照合・展開・版）に通す。level＝zip の圧縮の
    強さ（本物のリリースは 9・checkset.py の更新の確かめの「次の版」は 1＝作るのが速い・中身と確かめは同じ）"""
    sys.path.insert(0, str(REPO / 'app'))
    import update   # noqa: E402  （app/update.py）
    urgent, ng = flags(ver)
    rel.mkdir(parents=True, exist_ok=True)
    for p in [*rel.glob(f'{NAME}-*-win-x64.zip'), rel / 'update.json']:   # 前の分だけ消す
        p.unlink(missing_ok=True)
    zp = rel / update.ZIP_NAME.format(version=ver)
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED, compresslevel=level) as z:
        for f in sorted(out.rglob('*')):
            if f.is_file():
                z.write(f, f'{update.ZIP_TOP}/' + f.relative_to(out).as_posix())
    manifest = {'name': update.NAME, 'format': update.FORMAT, 'version': ver, 'tag': ver,
                'zip': {'name': zp.name, 'sha256': sha256(zp), 'size': zp.stat().st_size}, 'notes': release_notes(ver),
                'urgent': urgent, 'ng': ng}
    up = rel / 'update.json'
    up.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    m = update.check_manifest(up.read_bytes())
    assert not m['manual'] and m['zip']['size'] == zp.stat().st_size and m['version'] == ver
    assert m['ng'] == ng and m['urgent'] == urgent
    with tempfile.TemporaryDirectory(dir=rel) as td:
        update.extract_release(zp, Path(td) / 'new', ver)
    return zp, up, manifest


def refresh_manifest(src, dst=None):
    """出したリリースの update.json の urgent・ng だけを、今の automap/version.py の URGENT・NG に書き換える（zip・版・変更点はそのまま）
    → 書いた場所。最新のリリースの update.json をこれに差し替えると、どの版のアプリも次の確かめで新しい NG を読む（作り直し・
    zip の上げ直しは要らない）"""
    sys.path.insert(0, str(REPO / 'app'))
    import update   # noqa: E402
    src = Path(src)
    raw = src.read_bytes()
    m = update.check_manifest(raw)   # 形を確かめる（読めない物は直さない）
    urgent, ng = flags()
    data = json.loads(raw)
    data['urgent'] = {v: why for v, why in urgent.items() if update.vtuple(v) <= update.vtuple(m['version'])}
    data['ng'] = ng
    dst = Path(dst) if dst else src
    text = json.dumps(data, ensure_ascii=False, indent=1) + '\n'
    m2 = update.check_manifest(text.encode('utf-8'))
    assert m2['version'] == m['version'] and m2['zip'] == m['zip'] and m2['ng'] == ng
    dst.write_text(text, encoding='utf-8')
    return dst, data


def git_version():
    try:
        return subprocess.run(['git', 'describe', '--tags', '--always', '--dirty'], cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def main(argv=None):
    ap = argparse.ArgumentParser(description='配布物の試作（埋め込み用の Python ＋部品＋起動用の exe）')
    ap.add_argument('--work', help='作業の場所（downloads/・build/ を作る）')
    ap.add_argument('--refresh-manifest', metavar='UPDATE_JSON',
                    help='作らずに、出したリリースの update.json の urgent・ng だけを automap/version.py の URGENT・NG に書き換える'
                         '（最新のリリースの update.json を差し替えて NG を足す時）')
    ap.add_argument('--out', help='--refresh-manifest: 書く場所（既定＝読んだファイルに上書き）')
    ap.add_argument('--unpinned', action='store_true', help='公開の指紋を確かめていない版の Python でも作る（試しに作る時だけ）')
    ap.add_argument('--py', default=PY_VERSION, help=f'埋め込み用の Python の版（既定 {PY_VERSION}・ビルド用の Python と 3.14 までそろえる）')
    ap.add_argument('--compile', action='store_true', help='.pyc を作って入れる（checked-hash＝zip の時刻のずれで作り直さない）')
    ap.add_argument('--zip', action='store_true', help='配る zip も作る')
    ap.add_argument('--library', help='配布用の型のライブラリ（既定＝設定の library_db の隣の library-dist.sqlite）')
    ap.add_argument('--rating', help='nlm-rating のフォルダ（既定＝設定の nlm_rating_exe のフォルダ）')
    ap.add_argument('--version', help='確かめ用: 配布物の版を v〇.〇.〇 に（既定＝automap/version.py の VERSION）')
    a = ap.parse_args(argv)
    if a.refresh_manifest:
        dst, data = refresh_manifest(a.refresh_manifest, a.out)
        log(f'update.json を書き換えた: {dst}（版 {data["version"]}・NG のアプリの版 {len(data["ng"]["app"])}・NG の部品 {len(data["ng"]["parts"])}・'
            f'急ぎの印 {len(data["urgent"])}）')
        if dst.name != 'update.json':
            log('注意: 添付する名前は update.json（GitHub はファイルの名前をそのまま使う＝名前を update.json にしてから差し替える）')
        log(f'最新のリリースに差し替える: gh release upload {data["tag"]} "{dst}" --clobber（GitHub への公開は利用者が決める）')
        return
    if not a.work:
        ap.error('--work が要る（--refresh-manifest の時だけ要らない）')
    V = app_version()
    app_ver = a.version or V.VERSION
    if not re.fullmatch(r'v\d{1,4}\.\d{1,4}\.\d{1,4}', app_ver):
        raise SystemExit(f'版の形が違う（v〇.〇.〇）: {app_ver}')
    if not a.version and (not V.CHANGES or V.CHANGES[0][0] != V.VERSION):
        raise SystemExit(f'automap/version.py の CHANGES の頭の版が VERSION（{V.VERSION}）と違う（変更点を書いてから作る）')
    if tuple(int(x) for x in a.py.split('.')[:2]) != sys.version_info[:2]:
        raise SystemExit(f'ビルド用の Python（{sys.version_info[0]}.{sys.version_info[1]}）と埋め込み用（{a.py}）の版をそろえる（pip が選ぶ部品が変わる）')
    work = Path(a.work).resolve()
    out = work / 'build' / NAME
    t0 = time.time()

    # 1. 埋め込み用の Python
    emb = fetch(PY_URL.format(v=a.py), work / 'downloads' / f'python-{a.py}-embed-amd64.zip')
    digest = sha256(emb)
    want = PY_SHA256.get(a.py)
    if not want and not a.unpinned:
        raise SystemExit(f'埋め込み用の Python {a.py} の公開の指紋が PY_SHA256 に無い（python.org の値を確かめて足す・試しに作るだけなら --unpinned）')
    if want and want != digest:
        raise SystemExit(f'埋め込み用の Python の指紋が違う: {digest}')
    log(f'埋め込み用の Python {a.py}: {mb(emb.stat().st_size)} sha256={digest}{"（確かめた）" if want else "（未確認＝PY_SHA256 に入れる）"}')
    if out.exists():
        shutil.rmtree(out)
    rt = out / 'runtime'
    rt.mkdir(parents=True)
    with zipfile.ZipFile(emb) as z:
        z.extractall(rt)
    # ._pth で場所を決める（2026-11-03 に3通りを比べた）: ._pth を外すと、Windows はレジストリの PythonPath（その PC に入っている
    # 同じ版の Python の Lib・DLLs）を sys.path に混ぜた（この PC で tkinter が「ある」ことになった）。._pth があると隔離の決まり
    # （PYTHONPATH・レジストリ・ユーザーごとの site を見ない・safe_path＝スクリプトの場所も今の場所も足さない）になるので、
    # 本体の場所（..＝automap・..\app＝server.py をスクリプトで動かす時・..\tools＝区間の点検が読む library_themes 等）を書き足す。
    # PYTHONIOENCODING は ._pth があっても効く（作り直しの記録を utf-8 で受け取れる）
    for p in rt.glob('python*._pth'):
        p.unlink()
    ver = ''.join(a.py.split('.')[:2])
    (rt / f'python{ver}._pth').write_text('\n'.join([f'python{ver}.zip', '.', r'Lib\site-packages', '..', r'..\app', r'..\tools',
                                                    'import site', '']), encoding='utf-8')
    site = rt / 'Lib' / 'site-packages'
    site.mkdir(parents=True)

    # 2. 部品（ビルド用の Python の pip で、埋め込み用の site-packages へ）
    # proxy_tools（pywebview が使う・純 Python）は wheel が無く元のソースしか無い＝それだけ元のソースから
    run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location', '--only-binary=:all:',
         '--no-binary=proxy_tools', '--no-compile', '--target', site, '-r', HERE / 'requirements-dist.txt'])
    for d in ('bin', 'Scripts'):   # --target が作るコマンドの exe（ビルドの場所を指しているので使えない）
        shutil.rmtree(site / d, ignore_errors=True)

    # 2b. Visual C++ の実行の部品（MSVCP140・VCOMP140 等）: 埋め込み用の Python には vcruntime140(_1) しか入っていない。numba・
    # scikit-learn・soxr 等が読むので、まっさらな Windows（再頒布可能パッケージが無い）では読み込みに失敗する → ビルドの PC の
    # System32 から runtime\ へ写す（拡張モジュールは python.exe の場所も探す。NLM の PyInstaller の配布物も同じ物を同梱している。
    # Visual Studio の再頒布の決まりでアプリと一緒に置いてよい物）
    vc = copy_vc_runtime(out, rt)
    log('Visual C++ の部品を写した: ' + ('・'.join(vc) if vc else 'なし'))

    # 3. 本体の写し
    n = copy_src(out)
    if a.version and a.version != V.VERSION:
        set_version(out, app_ver)
    log(f'本体のファイル: {n}（版 {app_ver}）')
    # 3b. 同梱する部品（配布用の型のライブラリ・★を測る部品）
    log('同梱: ' + '・'.join(bundle_parts(out, a.library, a.rating)))

    # 4. 起動用の exe
    build_launcher(out, work)

    # 5. 流れの計算（Numba・automap/flow_nb.py）のコンパイル済みの控え（必ず）: 配布物の Python で NUMBA_CPU_NAME=generic にして一度動かし、
    # automap/__pycache__ に作る＝どの PC でも最初の作り直しでコンパイルしない（コンパイルは 20 秒ほど）。作り直しのプロセス（python -m automap）も
    # generic で動く（automap/__main__.py の頭）。控えの古さは元のファイルの中身の sha256 で見る（numba 0.68＝zip の時刻のずれは関係ない）。
    # 配布物の場所に書けない時（Program Files 等）、numba はユーザーごとの場所で作り直す（最初の作り直しが 20 秒ほど遅くなるだけ）
    nb = warm_flow(rt, out)
    log(f'流れの計算のコンパイル済みの控え: {nb} 個')

    # 5b. .pyc（任意）
    if a.compile:
        run([rt / 'python.exe', '-m', 'compileall', '-q', '-j', '0', '--invalidation-mode', 'checked-hash',
             site, out / 'app', out / 'automap', out / 'tools'])

    info = {'name': NAME, 'version': app_ver, 'git': git_version(), 'python': a.py, 'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'compiled': a.compile, 'flow_cache': nb}
    (out / 'build-info.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.path.insert(0, str(REPO / 'app'))
    import update   # noqa: E402  （app/update.py・build-info.json と automap/version.py の版がそろっているか＝更新の確かめと同じ読み方）
    if update.package_version(out) != app_ver:
        raise SystemExit(f'配布物の版が読めない・そろっていない（build-info.json と automap/version.py）: {update.package_version(out)!r}')

    # 大きさ
    sizes = {'全体': du(out), 'runtime（Python 本体）': du(rt) - du(site), 'site-packages': du(site),
             'app・automap・tools': sum(du(out / d) for d in SRC_DIRS), 'data（型のライブラリ）': du(out / 'data'),
             'parts（nlm-rating）': du(out / 'parts')}
    big = sorted(((du(p), p.name) for p in site.iterdir()), reverse=True)[:12]
    log('大きさ: ' + '・'.join(f'{k} {mb(v)}' for k, v in sizes.items()))
    log('site-packages の大きい物: ' + '・'.join(f'{n} {mb(s)}' for s, n in big))
    if a.zip:
        zp, up, manifest = make_release(out, app_ver, work / 'build' / 'release')
        log(f'zip: {zp}（{mb(zp.stat().st_size)}・sha256={manifest["zip"]["sha256"]}）')
        log(f'update.json: {up}（変更点 {len(manifest["notes"])} 版分・アプリと同じ確かめに通した）')
        log(f'公開する時は zip と update.json の 2 つを、タグ {app_ver} のリリース（最新）に添付する（GitHub への公開は利用者が決める）')
        sizes['zip'] = zp.stat().st_size
    (work / 'build' / 'sizes.json').write_text(json.dumps({k: round(v / 1e6, 1) for k, v in sizes.items()}, ensure_ascii=False, indent=1),
                                               encoding='utf-8')
    log(f'できた: {out}（{time.time() - t0:.0f} 秒）')


if __name__ == '__main__':
    main()
