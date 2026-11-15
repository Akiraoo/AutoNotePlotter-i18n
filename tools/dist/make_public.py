"""公開版（GitHub に出す物）のコミットを、手元の public ブランチに作る（blnext・NLM と同じ分け方・2026-11-15）。NAS の master は全部の
開発の履歴、public ブランチは公開した版ごとに 1 コミットの積み重ね（GitHub の master には public を push する＝開発の履歴・コミットの文は出ない）。

  .venv/Scripts/python.exe tools/dist/make_public.py           「<版> 公開」のコミットとタグ <版> を public に作る
  .venv/Scripts/python.exe tools/dist/make_public.py --check   作らずに、外す物と個人の情報の検査だけ

- 中身は master のコミットの中身から EXCLUDE を外した物。作業中のフォルダ・ブランチ・index には触らない（別の index で組み立てる）。
- 個人の情報の検査: 公開版の中に、この PC のユーザーのフォルダ・NAS の場所（remote origin のホストと利用者名）・git のメールアドレス・
  リポジトリを置いているフォルダ・開発の設定（app/config.local.json）に書いてある場所があれば止まる。調べる値はこの PC から読む（ここには書かない）。
- 版は automap/version.py の VERSION。public の先頭が同じ版の「公開」のコミットなら、作り直す（まだ push していない時だけ使うこと。
  push した後に同じ版を作り直すと、GitHub と食い違う）。
- push はしない（GitHub への公開は利用者の指示を得てから）。最後に送るコマンドを出す。
- 作者・コミッタは GitHub の noreply のアドレス（NLM・blnext の公開版と同じ）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.platform == 'win32':
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding='utf-8')
        except Exception:   # noqa: BLE001
            pass

ROOT = Path(__file__).resolve().parents[2]
EXCLUDE = ('CLAUDE.local.md',)   # git の管理外のはずだが、間違えて足しても公開版には入れない
BRANCH = 'public'
SOURCE = 'master'
AUTHOR = ('Oz-Co-two', '332386196+Oz-Co-two@users.noreply.github.com')


class PublicError(Exception):
    pass


def git(repo, *args, env=None, input=None):
    p = subprocess.run(['git', '-C', str(repo), '-c', 'core.quotepath=false', *args], capture_output=True, text=True, encoding='utf-8',
                       env={**os.environ, **(env or {})}, input=input)
    if p.returncode != 0:
        raise PublicError('git %s: %s' % (' '.join(args[:3]), (p.stderr or p.stdout).strip()))
    return p.stdout.strip()


def ref(repo, name):
    """ref のコミット（無ければ None）"""
    p = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', '--quiet', name + '^{commit}'], capture_output=True, text=True, encoding='utf-8')
    return p.stdout.strip() or None


def build_tree(repo, source=SOURCE, exclude=EXCLUDE):
    """source の中身から exclude を外した tree"""
    with tempfile.TemporaryDirectory() as td:
        env = {'GIT_INDEX_FILE': str(Path(td) / 'index')}
        git(repo, 'read-tree', source, env=env)
        git(repo, 'rm', '-r', '--cached', '--quiet', '--ignore-unmatch', '--', *exclude, env=env)
        return git(repo, 'write-tree', env=env)


def _forms(path):
    """場所の書き方の違い（\\・/・JSON の \\\\）"""
    s = str(path)
    return {s, s.replace('\\', '/'), s.replace('\\', '\\\\'), s.replace('/', '\\')}


def secrets(repo):
    """公開版に入っていてはいけない、この PC・作者に固有の文字の並び（名前, 値）"""
    out = []
    name = Path.home().name   # C:\Users\<名前>
    out += [('この PC のユーザーのフォルダ', 'Users' + sep + name) for sep in ('\\', '/', '\\\\')]
    origin = subprocess.run(['git', '-C', str(repo), 'remote', 'get-url', 'origin'], capture_output=True, text=True).stdout.strip()
    m = re.match(r'(?:\w+://)?(?:([^@/]+)@)?([^/:]+)', origin)
    if m and origin:
        if m.group(1):
            out.append(('NAS の利用者名', m.group(1)))
        out.append(('NAS の場所', m.group(2)))
    for scope in ([], ['--global']):
        email = subprocess.run(['git', '-C', str(repo), 'config', *scope, 'user.email'], capture_output=True, text=True).stdout.strip()
        if email and not email.endswith('noreply.github.com') and not email.endswith('@local'):
            out.append(('git のメールアドレス', email))
    out += [('リポジトリを置いているフォルダ', f) for f in _forms(Path(repo).resolve().parent)]
    try:   # 開発の設定に書いた場所（型のライブラリ・Beat Saber のフォルダ・NLM・確かめの置き場など）とその親
        cfg = json.loads((Path(repo) / 'app' / 'config.local.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cfg = {}
    for k, v in cfg.items():
        if isinstance(v, str) and re.match(r'^[A-Za-z]:[\\/]|^\\\\', v):
            p = Path(v)
            for q in (p, p.parent):
                if len(q.parts) >= 2:   # ドライブの一番上（I:\ だけ）は調べない
                    out += [(f'開発の設定の場所（{k}）', f) for f in _forms(q)]
    seen, uniq = set(), []
    for k, v in out:
        if v and len(v) >= 4 and v.lower() not in seen:
            seen.add(v.lower())
            uniq.append((k, v))
    return uniq


def check_tree(repo, tree, exclude=EXCLUDE, extra=()):
    """公開版の tree の検査。問題の一覧（無ければ []）"""
    bad = []
    names = git(repo, 'ls-tree', '-r', '--name-only', tree).splitlines()
    for n in names:
        if any(n == e or n.startswith(e + '/') for e in exclude):
            bad.append('外すはずの物が入っている: ' + n)
    for label, value in [*secrets(repo), *extra]:
        p = subprocess.run(['git', '-C', str(repo), '-c', 'core.quotepath=false', 'grep', '-I', '-l', '-i', '-F', '-e', value, tree],
                           capture_output=True, text=True, encoding='utf-8')
        for line in p.stdout.splitlines():
            bad.append('%sが入っている: %s' % (label, line.split(':', 1)[-1]))
    return bad


def make(repo, version, check_only=False, extra=()):
    """public に「<版> 公開」のコミットとタグを作る → (コミット, 作ったか)"""
    if not ref(repo, SOURCE):
        raise PublicError(f'{SOURCE} がありません')
    tree = build_tree(repo)
    bad = check_tree(repo, tree, extra=extra)
    if bad:
        raise PublicError('公開版に入れてはいけない物があります:\n  ' + '\n  '.join(bad))
    if check_only:
        return None, False
    msg = f'{version} 公開'
    old = ref(repo, BRANCH)
    parent = old
    if old and git(repo, 'log', '-1', '--format=%s', old) == msg:   # まだ push していない同じ版を作り直す
        parent = ref(repo, old + '^')
    if parent and git(repo, 'rev-parse', parent + '^{tree}') == tree:
        raise PublicError(f'公開版の中身が前の公開（{BRANCH}）と同じです。版を上げてから作ってください')
    env = {'GIT_AUTHOR_NAME': AUTHOR[0], 'GIT_AUTHOR_EMAIL': AUTHOR[1], 'GIT_COMMITTER_NAME': AUTHOR[0], 'GIT_COMMITTER_EMAIL': AUTHOR[1]}
    new = git(repo, 'commit-tree', tree, *(['-p', parent] if parent else []), '-F', '-', env=env, input=msg + '\n')
    git(repo, 'update-ref', 'refs/heads/' + BRANCH, new, *([old] if old else []))
    if ref(repo, 'refs/tags/' + version):
        git(repo, 'tag', '-d', version)
    git(repo, 'tag', '-a', version, new, '-m', version, env=env)
    return new, True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='作らずに検査だけ')
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from automap import version
    ver = version.VERSION
    if not re.fullmatch(r'v\d+\.\d+\.\d+', ver or ''):
        print(f'VERSION（{ver!r}）が読めません', file=sys.stderr)
        return 1
    try:
        new, made = make(ROOT, ver, check_only=a.check)
    except PublicError as e:
        print('止めました: ' + str(e), file=sys.stderr)
        return 1
    if not made:
        print(f'検査は通りました（{SOURCE} から {", ".join(EXCLUDE)} を外した中身に、この PC・作者に固有の物はありません・調べた値 {len(secrets(ROOT))} 個）')
        return 0
    print(f'{BRANCH} に「{ver} 公開」（{new[:7]}）とタグ {ver} を作りました（{", ".join(EXCLUDE)} は外した）。')
    print('GitHub に出す時（利用者の指示を得てから）:')
    print(f'  git push github {BRANCH}:master && git push github {ver}')
    print(f'  git push origin {BRANCH} {ver}   （NAS にも残す）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
