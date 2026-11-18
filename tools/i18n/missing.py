"""List Japanese UI strings that have no translation in tools/i18n/messages.json.

Scans the screen code (app/static/index.html, app/static/js/*.js) and the server messages (app/*.py and a few automap
modules whose messages reach the screen). JS template literals become "{0}…" templates, HTML inside strings is split into
its text pieces (the runtime translates DOM text nodes one by one). Comments, docstrings and test-only strings are not
filtered out completely, so read the list and translate what users see.

    python tools/i18n/missing.py            # print missing strings (file, text)
    python tools/i18n/missing.py --json x   # also write them as a messages.json-shaped list with empty translations
"""
import argparse
import ast
import glob
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JPS = re.compile(r'[぀-ヿ一-鿿]')
TAG = re.compile(r'<[a-zA-Z/!][^<>]*>')
BS = '\\'
PY = ['app/*.py', 'automap/library_use.py', 'automap/library_db.py', 'tools/sep_install.py']


def js_strings(s):
    out = []; i = 0; n = len(s); prev = ''
    while i < n:
        c = s[i]
        if s.startswith('//', i):
            j = s.find('\n', i); i = n if j < 0 else j; continue
        if s.startswith('/*', i):
            j = s.find('*/', i + 2); i = n if j < 0 else j + 2; continue
        if c in '"\'':
            j = i + 1; buf = ''
            while j < n and s[j] != c:
                if s[j] == BS: buf += s[j:j + 2]; j += 2; continue
                if s[j] == '\n': break
                buf += s[j]; j += 1
            out.append(('s', buf)); i = j + 1; prev = 'x'; continue
        if c == '`':
            j = i + 1; parts = ['']
            while j < n and s[j] != '`':
                if s[j] == BS: parts[-1] += s[j:j + 2]; j += 2; continue
                if s.startswith('${', j):
                    d = 1; k = j + 2; st = k
                    while k < n and d:
                        if s[k] == '{': d += 1
                        elif s[k] == '}': d -= 1
                        elif s[k] in '\'"`':
                            q = s[k]; k += 1
                            while k < n and s[k] != q:
                                if s[k] == BS: k += 1
                                k += 1
                        k += 1
                    out.extend(js_strings(s[st:k - 1]))
                    parts.append(None); parts.append(''); j = k; continue
                parts[-1] += s[j]; j += 1
            out.append(('t', parts)); i = j + 1; prev = 'x'; continue
        if c == '/' and prev in '(,=:[!&|?{};+-*%<>~^':   # regex literal
            j = i + 1; cls = False
            while j < n:
                if s[j] == BS: j += 2; continue
                if s[j] == '[': cls = True
                elif s[j] == ']': cls = False
                elif s[j] == '/' and not cls: break
                elif s[j] == '\n': break
                j += 1
            i = j + 1; prev = 'x'; continue
        if not c.isspace():
            prev = 'x' if (c.isalnum() or c in '_$)]') else c
        i += 1
    return out


def unesc(t):   # JS string escapes → the real text
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), t, flags=re.S)


def pieces(k):   # HTML inside a string → its text pieces and title/placeholder values
    if not TAG.search(k):
        yield k; return
    for m in TAG.finditer(k):
        for a in re.finditer(r'(?:title|placeholder|aria-label|alt)="([^"]*)"', m.group(0)):
            yield a.group(1)
    for seg in TAG.split(k):
        yield re.sub(r'\s+', ' ', seg).strip() if '\n' in seg else seg


def collect():
    found = []

    def add(k, src):
        for p in pieces(k):
            if JPS.search(p):
                found.append((src, p))

    def js_file(text, name):
        for kind, v in js_strings(text):
            if kind == 's':
                add(unesc(v), name)
            else:
                txt = ''; i = 0
                for p in v:
                    if p is None: txt += '{%d}' % i; i += 1
                    else: txt += unesc(p)
                add(txt, name)

    for f in sorted(glob.glob(str(ROOT / 'app/static/js/*.js'))):
        if os.path.basename(f) == 'i18n.js':
            continue
        js_file(Path(f).read_text(encoding='utf-8'), os.path.basename(f))
    h = re.sub(r'<!--.*?-->', '', (ROOT / 'app/static/index.html').read_text(encoding='utf-8'), flags=re.S)
    for m in re.finditer(r'<script>(.*?)</script>', h, flags=re.S):
        js_file(m.group(1), 'index.html')
    h = re.sub(r'<script>.*?</script>', '', h, flags=re.S)
    for m in re.finditer(r'(?:title|placeholder|aria-label)="([^"]*)"', h):
        add(m.group(1), 'index.html')
    for m in re.finditer(r'>([^<>]+)<', h):
        add(re.sub(r'\s+', ' ', m.group(1)).strip(), 'index.html')

    for g in PY:
        for f in sorted(glob.glob(str(ROOT / g))):
            tree = ast.parse(Path(f).read_text(encoding='utf-8'))
            skip = set()
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and n.body \
                        and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                    skip.add(id(n.body[0].value))   # docstring
                if isinstance(n, ast.JoinedStr):
                    skip.update(id(v) for v in n.values)
            name = 'py:' + os.path.basename(f)
            for n in ast.walk(tree):
                if isinstance(n, ast.JoinedStr):
                    k = ''; i = 0
                    for v in n.values:
                        if isinstance(v, ast.Constant): k += str(v.value)
                        else: k += '{%d}' % i; i += 1
                    add(k, name)
                elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:
                    add(n.value, name)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    a = ap.parse_args()
    have = {e['ja'] for e in json.loads((ROOT / 'tools/i18n/messages.json').read_text(encoding='utf-8'))}
    squash = {re.sub(r'\s+', '', k) for k in have}
    seen, miss = set(), []
    for src, k in collect():
        if k in seen or k in have or k.strip() in have or re.sub(r'\s+', '', k) in squash:
            continue
        seen.add(k); miss.append((src, k))
    for src, k in miss:
        print(f'{src}\t{json.dumps(k, ensure_ascii=False)}')
    print(f'-- {len(miss)} strings without a translation')
    if a.json:
        Path(a.json).write_text(json.dumps([{'ja': k, 'en': '', 'zh-Hans': '', 'src': s} for s, k in miss],
                                           ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
