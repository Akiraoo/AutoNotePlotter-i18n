"""Build the UI translation dictionaries (app/static/i18n/<lang>.json) from tools/i18n/messages.json.

messages.json is the source of truth: a list of {"ja": original Japanese, "en": English, "zh-Hans": Simplified Chinese, "src": file}.
Traditional Chinese (zh-Hant, Taiwan phrasing) is generated from zh-Hans with OpenCC (s2twp), so only en and zh-Hans are
written by hand. Entries may carry an explicit "zh-Hant" to override the conversion.

    python tools/i18n/build.py            # writes app/static/i18n/{en,zh-Hans,zh-Hant}.json
    python tools/i18n/build.py --check    # fails if the written files are out of date

OpenCC is only needed for building (pip install opencc-python-reimplemented or opencc); the app reads the JSON files.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'tools' / 'i18n' / 'messages.json'
OUT = ROOT / 'app' / 'static' / 'i18n'
LANGS = ('en', 'zh-Hans', 'zh-Hant')
PH = re.compile(r'\{\d+\}')


def converter():
    try:
        import opencc
    except ImportError:
        sys.exit('OpenCC is needed to build zh-Hant: pip install opencc-python-reimplemented')
    try:
        c = opencc.OpenCC('s2twp')
    except Exception:
        c = opencc.OpenCC('s2twp.json')
    return c.convert


def build():
    msgs = json.loads(SRC.read_text(encoding='utf-8'))
    s2t = converter()
    out = {lang: {} for lang in LANGS}
    problems = []
    for e in msgs:
        ja = e['ja']
        vals = {'en': e.get('en'), 'zh-Hans': e.get('zh-Hans')}
        vals['zh-Hant'] = e.get('zh-Hant') or (s2t(vals['zh-Hans']) if vals['zh-Hans'] is not None else None)
        for lang in LANGS:
            v = vals[lang]
            if v is None:
                continue
            if sorted(PH.findall(v)) != sorted(PH.findall(ja)):
                problems.append(f'{lang}: placeholders differ: {ja!r} -> {v!r}')
            out[lang][ja] = v
            dec = html.unescape(ja)   # the same text as it appears in the DOM (&lt; → <)
            if dec != ja:
                out[lang].setdefault(dec, html.unescape(v))
    return out, problems


def dump(lang, m):
    return json.dumps({'lang': lang, 'm': m}, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    out, problems = build()
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        sys.exit(1)
    OUT.mkdir(parents=True, exist_ok=True)
    stale = []
    for lang in LANGS:
        f = OUT / f'{lang}.json'
        text = dump(lang, out[lang])
        if a.check:
            if not f.is_file() or f.read_text(encoding='utf-8') != text:
                stale.append(f.name)
        else:
            f.write_text(text, encoding='utf-8', newline='\n')
            print(f'{f.relative_to(ROOT)}: {len(out[lang])} strings')
    if stale:
        sys.exit('out of date (run python tools/i18n/build.py): ' + ', '.join(stale))


if __name__ == '__main__':
    main()
