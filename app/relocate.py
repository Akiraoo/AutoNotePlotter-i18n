"""作業フォルダの引っ越し（docs/アプリ仕様.md 21 節・2026-11-03 利用者「作業フォルダを後から動かす事ができるような仕組みとメニュー」）。

作業フォルダ（設定の work_dir＝out/・cache/・parts/（音を分ける部品）ほか）の中身を全部、新しいフォルダへ移す。
- 同じドライブ: 名前を変えるだけ（すぐ終わる・途中で失敗したら戻す）。別のドライブ: 全部コピーして数と大きさを確かめ、設定を切り替えてから
  元を消す（途中で止まっても元が残る）。
- ファイルの中の場所（.nlmf の音源・カバーの nativePath 等・.json）が古い作業フォルダを指していたら新しい場所に書き換える。.nlmf がアプリの
  書いたままだった時だけ、書き換えた後の指紋（out/.state）を記録し直す（NLM で直された印を消さない）。
- 設定の work_dir と、古い作業フォルダの中を指す sep_dir・sep_pending も書き換える。作業中（作り直し・取り込み・インストール・書き出し等）は動かさない。
アプリの本体（配布物のフォルダ）は、中の場所が全部相対なのでフォルダごと移してよい（このモジュールは使わない）。
"""
import json
import os
import shutil
import time
from pathlib import Path

from automap import config

TEXT_EXT = {'.nlmf', '.json'}


def _du(p):
    n = c = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
                c += 1
            except OSError:
                pass
    return n, c


def _free(p):
    for q in (Path(p), *Path(p).parents):
        if q.exists():
            try:
                return shutil.disk_usage(q).free
            except OSError:
                return None
    return None


def _same_drive(a, b):
    return os.path.splitdrive(str(Path(a).resolve()))[0].lower() == os.path.splitdrive(str(Path(b).resolve()))[0].lower()


def _inside(a, b):
    """a が b の中（同じも含む）か"""
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or b in a.parents


def running(ctx):
    return [j for j in ctx.JOBS.values() if j.get('state') == 'running']


def plan(ctx, new_dir):
    """引っ越しの見積もり → {old, new, bytes, files, free, same_drive, problems, warnings}"""
    cfg = config.load(ctx.CONFIG)
    old = config.work_dir(cfg)
    problems, warnings = [], []
    if old is None:
        problems.append('開発の PC（リポジトリの out・cache を使っている）では作業フォルダを引っ越せません')
        return {'old': None, 'new': str(new_dir or ''), 'bytes': 0, 'files': 0, 'free': None, 'same_drive': False,
                'problems': problems, 'warnings': warnings}
    s = str(new_dir or '').strip().strip('"')
    new = Path(os.path.expanduser(s)) if s else None
    size, count = _du(old) if old.exists() else (0, 0)
    if not new or not new.is_absolute():
        problems.append('引っ越し先はドライブ名から書いてください（例 D:\\AutoNotePlotter）')
    elif _inside(new, old) or _inside(old, new):
        problems.append('引っ越し先を今の作業フォルダの中（または外側）にはできません')
    elif new.exists() and any(new.iterdir()):
        problems.append('引っ越し先のフォルダが空ではありません（空のフォルダか、まだ無い名前を選んでください）')
    elif (config.ROOT / 'runtime').is_dir() and _inside(new, config.ROOT):
        problems.append('引っ越し先をアプリのフォルダの中にはできません（アプリの更新で消えます）')
    if not old.exists():
        problems.append(f'今の作業フォルダが見つかりません: {old}')
    same = bool(new) and new.is_absolute() and _same_drive(old, new)
    free = _free(new) if new and new.is_absolute() else None
    if new and not same and free is not None and free < size + 200e6:
        problems.append(f'引っ越し先のドライブの空き容量が足りません（要る量 約 {size / 1e9:.1f}GB・空き {free / 1e9:.1f}GB）')
    busy = running(ctx)
    if busy:
        problems.append('作業中の物があります（作り直し・取り込み・インストール・書き出しが終わってから）')
    warnings.append('NLM でこのアプリの曲を開いている時は、先に NLM を閉じてください（NLM が古い場所に保存してしまうため）')
    return {'old': str(old), 'new': str(new) if new else '', 'bytes': size, 'files': count, 'free': free, 'same_drive': same,
            'problems': problems, 'warnings': warnings}


def _variants(p):
    """場所の書き方（JSON の中の \\ を重ねた形・日本語を \\uXXXX にした形・/ の形・そのまま）。重なりは除かない（古い場所と新しい場所で
    対にするため。別々に除くと対がずれた）"""
    s = str(Path(p))
    out = []
    for x in (s, s.replace('\\', '/')):
        out += [json.dumps(x, ensure_ascii=False)[1:-1], json.dumps(x)[1:-1], x]
    return out


def rewrite_paths(root, old, new, cli=None, log=print):
    """root の中の .nlmf・.json に書かれた古い作業フォルダの場所を新しい場所に書き換える → 書き換えたファイルの数"""
    pairs = list(dict(zip(_variants(old), _variants(new))).items())   # 同じ書き方は 1 組に（対にしてから除く）
    n = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            if p.suffix.lower() not in TEXT_EXT:
                continue
            try:
                raw = p.read_bytes()
                text = raw.decode('utf-8-sig')
            except (OSError, UnicodeDecodeError):
                continue
            new_text = text
            for a, b in pairs:
                new_text = new_text.replace(a, b)
            if new_text == text:
                continue
            as_written = None
            if p.suffix.lower() == '.nlmf' and cli is not None:
                st = cli._state_path(p)
                try:
                    rec = json.loads(st.read_text(encoding='utf-8'))
                    as_written = rec.get('sha256') == cli._sha(p)
                except (OSError, ValueError):
                    as_written = False
            tmp = p.with_name(p.name + '.tmp')
            tmp.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + new_text.encode('utf-8'))
            os.replace(tmp, p)
            if as_written:
                st = cli._state_path(p)
                rec = json.loads(st.read_text(encoding='utf-8'))
                rec['sha256'] = cli._sha(p)
                st.write_text(json.dumps(rec), encoding='utf-8')
            n += 1
    log(f'ファイルの中の場所を書き換えた: {n} 個')
    return n


def _copy_tree(src, dst, job, total):
    done = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            if job.get('cancel'):
                raise RuntimeError('止めました（引っ越し先のコピーは途中まで・元の作業フォルダはそのまま）')
            s, d = Path(root) / f, dst / rel / f
            shutil.copy2(s, d)
            done += d.stat().st_size
            job['progress'] = {'stage': 'copy', 'label': 'コピーしています', 'done': done, 'total': total}


def start(ctx, b):
    pl = plan(ctx, b.get('new_dir'))
    if pl['problems']:
        raise ValueError('・'.join(pl['problems']))
    old, new = Path(pl['old']), Path(pl['new'])

    def move(job):
        new.mkdir(parents=True, exist_ok=True)
        children = sorted(old.iterdir())
        if pl['same_drive']:
            moved = []
            try:
                for c in children:
                    os.rename(c, new / c.name)
                    moved.append(c)
                    job['progress'] = {'stage': 'move', 'label': '移しています', 'done': len(moved), 'total': len(children)}
            except OSError as e:
                for c in reversed(moved):   # 戻す
                    try:
                        os.rename(new / c.name, c)
                    except OSError:
                        pass
                raise RuntimeError(f'移せませんでした（{e}）。開いているファイルがあれば閉じてから（NLM・エクスプローラー等）。元の場所に戻しました')
        else:
            _copy_tree(old, new, job, pl['bytes'])
            size, count = _du(new)
            if count != pl['files'] or size != pl['bytes']:
                raise RuntimeError(f'コピーした数・大きさが合いません（{count}/{pl["files"]} 個）。元の作業フォルダはそのままです')
        job['log'] += f'{"移した" if pl["same_drive"] else "コピーした"}: {pl["files"]} 個・{pl["bytes"] / 1e9:.2f}GB\n'

    def fix(job):
        rewrite_paths(new, old, new, cli=getattr(ctx, 'cli', None), log=lambda s: job.__setitem__('log', job['log'] + s + '\n'))
        cfg = config.load(ctx.CONFIG)
        ch = {'work_dir': str(new)}
        for k in ('sep_dir',):
            v = cfg.get(k)
            if v and _inside(v, old):
                ch[k] = str(new / Path(v).resolve().relative_to(old.resolve()))
        pend = cfg.get('sep_pending')
        if pend and pend.get('dir') and _inside(pend['dir'], old):
            ch['sep_pending'] = dict(pend, dir=str(new / Path(pend['dir']).resolve().relative_to(old.resolve())))
        cfg = config.update(ch, ctx.CONFIG)
        ctx.OUT, ctx.CACHE = config.out_dir(cfg), config.cache_dir(cfg)
        job['log'] += f'設定を新しい作業フォルダにした: {new}\n'

    def clean(job):
        if pl['same_drive']:
            try:
                old.rmdir()   # 空になった元のフォルダ
            except OSError:
                pass
            return
        job['progress'] = {'stage': 'clean', 'label': '元の作業フォルダを消しています', 'done': 0, 'total': 0}
        shutil.rmtree(old, ignore_errors=True)
        if old.exists():
            job['log'] += f'元の作業フォルダを消しきれませんでした（開いているファイルがある等）。あとで手で消してください: {old}\n'
        else:
            job['log'] += '元の作業フォルダを消した\n'

    job = ctx.start_job(None, [('移す', move), ('ファイルの中の場所と設定を書き換える', fix), ('片付ける', clean)], kind='move',
                        old=str(old), new=str(new), started_at=time.time())
    return {'id': job['id']}
