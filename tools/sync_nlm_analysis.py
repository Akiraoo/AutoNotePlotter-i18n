"""NLM から写した曲の解析（automap/song_analysis/）と、写した元（NLM の song_analysis/）の同じ所を保つ道具（docs/アプリ仕様.md 5 節）。

使い方（NLM の場所は環境変数 NLM_ROOT か --nlm）:
  .venv/Scripts/python.exe tools/sync_nlm_analysis.py diff            … 写した物と NLM の今の物を比べる（版・指紋・違うファイルの差分）
  .venv/Scripts/python.exe tools/sync_nlm_analysis.py update          … NLM の今の物を写し直し、SOURCE.md を書き直す（手を加えずに写す）
  .venv/Scripts/python.exe tools/sync_nlm_analysis.py check [--n 5]   … 写した物が NLM と同じ答えを出すかを、NLM で作った元のプロジェクト
      （解析の結果入り）で比べる。曲は cache/yama_set.json（{name, src}）と out/yama/<name>.nlmf。--pair <.nlmf> <音源> で足せる。
NLM のリポジトリは読むだけ（何も書かない）。
"""
import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DST = ROOT / 'automap' / 'song_analysis'
FILES = ('__init__.py', 'service.py', 'structure.py', 'tempo.py')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def nlm_bytes(p):
    """NLM のファイルの中身を git の中と同じ形（行の終わり LF）で。NLM は core.autocrlf で、作業中のファイルは直した物だけ CRLF に
    なる（2026-11-11 の 94dcf8e）。写し・指紋は git の中の中身にそろえる（写しの側は .gitattributes の -text で変えない）"""
    return Path(p).read_bytes().replace(b'\r\n', b'\n')


def nlm_root(a):
    r = a.nlm or os.environ.get('NLM_ROOT')
    if not r or not (Path(r) / 'song_analysis').is_dir():
        sys.exit('NLM の場所が分からない（--nlm か 環境変数 NLM_ROOT）')
    return Path(r)


def nlm_head(root):
    try:
        out = subprocess.run(['git', '-C', str(root), 'log', '-1', '--format=%H %cI', '--', 'song_analysis'], capture_output=True, text=True, timeout=30)
        head = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=30).stdout.strip()
        dirty = subprocess.run(['git', '-C', str(root), 'status', '--short', '--', 'song_analysis'], capture_output=True, text=True, timeout=30).stdout
        last, when = (out.stdout.strip().split(' ') + ['', ''])[:2]
        return {'head': head, 'last': last, 'when': when, 'dirty': bool(dirty.strip())}
    except Exception as e:   # noqa: BLE001
        return {'head': '', 'last': '', 'when': '', 'dirty': False, 'error': str(e)}


def recorded():
    """SOURCE.md に書いた写した時の指紋 {ファイル: sha256}"""
    p = DST / 'SOURCE.md'
    out = {}
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.startswith('| `') and line.count('|') >= 3:
                cells = [c.strip().strip('`') for c in line.strip('|').split('|')]
                if cells[0] in FILES:
                    out[cells[0]] = cells[1]
    return out


def write_source(info):
    rows = '\n'.join(f'| `{f}` | `{sha(DST / f)}` |' for f in FILES)
    (DST / 'SOURCE.md').write_text(f"""# 写した元（NLM の曲の解析）

このフォルダの `{'`・`'.join(FILES)}` は、NLM（Non-Linear Mapper Oz-Co2版・https://github.com/Oz-Co-two/nlm-oz-co2 ）の
`song_analysis/` を**手を加えずに**写した物（docs/アプリ仕様.md 5 節）。こちらの都合の変更は外側の包み `automap/analyze_song.py` に置く。

- 写した元の NLM のコミット: `{info.get('head', '')}`（`song_analysis/` を最後に変えたコミット `{info.get('last', '')}`・{info.get('when', '')}）
- 写した日: {time.strftime('%Y-%m-%d')}
- ライセンス: GPLv3（NLM 全体が GPLv3。原作者 helba さん・Oz-Co2。NLM の LICENSE・THIRD_PARTY_NOTICES.txt）。
  中身に他所から写したコードの記載は無い（論文の方法の名前だけ: McFee & Ellis (2014) のラプラシアン分割 等）。
- 依存: librosa 1.0.0・numpy・scipy・scikit-learn 1.9.1・soundfile（m4a 等は ffmpeg）。NLM と同じ版にそろえる
  （NLM は版を上げる時に採点＝テンポ 63 曲・構成 39 曲で比べている。版が違うと答えが変わり得る）。
- 写し直し・比べ: `tools/sync_nlm_analysis.py diff|update|check`。

| ファイル | SHA-256（写した時） |
|---|---|
{rows}
""", encoding='utf-8')


def cmd_diff(a):
    root = nlm_root(a)
    info, rec = nlm_head(root), recorded()
    print(f'NLM の今: HEAD {info["head"][:10]}・song_analysis を最後に変えたコミット {info["last"][:10]}（{info["when"]}）'
          + ('・手元に未コミットの変更あり' if info['dirty'] else ''))
    same = True
    for f in FILES:
        src, dst = root / 'song_analysis' / f, DST / f
        s1, s2 = hashlib.sha256(nlm_bytes(src)).hexdigest(), sha(dst) if dst.exists() else ''
        mark = '同じ' if s1 == s2 else '違う'
        if rec.get(f) and rec[f] != s2:
            mark += '（写した物が SOURCE.md の記録と違う＝写した後に手を入れた）'
        print(f'  {f}: {mark}')
        if s1 != s2:
            same = False
            d = difflib.unified_diff(dst.read_text(encoding='utf-8').splitlines() if dst.exists() else [], nlm_bytes(src).decode('utf-8').splitlines(),
                                     f'写した物/{f}', f'NLM/{f}', lineterm='', n=2)
            for i, line in enumerate(d):
                if i >= 200:
                    print('    …（長いので省いた）')
                    break
                print('    ' + line)
    print('→ 写し直す必要なし' if same else '→ 写し直すなら: tools/sync_nlm_analysis.py update（その後 check で答えを確かめる）')


def cmd_update(a):
    root = nlm_root(a)
    DST.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        (DST / f).write_bytes(nlm_bytes(root / 'song_analysis' / f))
    write_source(nlm_head(root))
    print('写し直した:', ', '.join(FILES))


def _same(a, b):
    """数として同じか（.nlmf は JS が書くので 175 と 175.0 が混ざる＝文字で比べると違って見える）"""
    return json.loads(json.dumps(a)) == json.loads(json.dumps(b))


def compare(proj_path, audio, parts=('tempo', 'structure')):
    """NLM が .nlmf に入れた解析の結果と、写した物でもう一度解析した結果を比べる → dict。
    parts＝比べる物（テンポの推定・構成の解析）。構成の解析は .nlmf の BPM・無音追加で解くのでテンポの答えを待たない
    ＝別々に比べられる（テストは 2 つに分けて並べて流す）。比べなかった物の項目は結果に入らない"""
    sys.path.insert(0, str(ROOT))
    from automap import analyze_song as A
    from automap.nlmf import load
    ana = load(proj_path).get('analysis') or {}
    g = ana.get('grid') or {}
    if not ana.get('structure') or not g.get('bpm'):
        return {'skip': '解析の結果が無い'}
    if g.get('tp') or g.get('ms'):
        return {'skip': 'テンポパート・Music の切り貼りあり（扱わない）'}
    t0 = time.time()
    y = A.load(audio)
    hp = A.hpss(y) if len(parts) > 1 else None   # 両方の時は analysis と同じく HPSS を 1 回に（片方だけは写しの中で計算する道）
    out = {}
    if 'tempo' in parts:
        tp = A.clean_tempo(A.tempo(audio, y=y, hp=hp))
        T0 = ana.get('tempo') or {}
        out.update({'tempo': _same(tp, T0), 'bpm': (tp or {}).get('bpm'), 'bpm_nlm': T0.get('bpm'), 'lead': (tp or {}).get('lead_ms'),
                    'lead_nlm': T0.get('lead_ms'), 'sec_tempo': round(time.time() - t0, 1)})
    if 'structure' not in parts:
        return out
    t1 = time.time()
    dur = A.audio_duration(audio)
    st = A.clean_structure(A.structure(audio, g['bpm'], g['leadMs'], y=y, music_beat=g.get('mb') or 0, dur=dur, hp=hp))
    at = A.at_grid(g['bpm'], g['leadMs'], dur, g.get('mb') or 0)
    for s in st['sections']:
        a0, a1 = A.at_sec(at, A.SUB, s['start'], 1), A.at_sec(at, A.SUB, s['end'], -1)
        if a0 is not None:
            s['a0'] = a0
        if a1 is not None:
            s['a1'] = a1
    t2 = time.time()
    S0 = ana['structure']
    out.update({'sections': _same(st['sections'], S0.get('sections')), 'segments': _same(st['segments'], S0.get('segments')),
                'chorus': _same(st['chorus'], S0.get('chorus')), 'n_sec': (len(st['sections']), len(S0.get('sections') or [])),
                'sec_structure': round(t2 - t1, 1)})
    if not out['sections']:   # 何が違うか（境目・名前）
        a_ = [(s['start'], s['end'], s['name'], s['label']) for s in st['sections']]
        b_ = [(s['start'], s['end'], s['name'], s['label']) for s in S0.get('sections') or []]
        out['sections_bounds_same'] = [x[:2] for x in a_] == [x[:2] for x in b_]
        out['sections_names_same'] = [x[2:] for x in a_] == [x[2:] for x in b_]
    return out


def cmd_check(a):
    pairs = [tuple(p) for p in a.pair or []]
    ys = ROOT / 'cache' / 'yama_set.json'
    if ys.exists() and a.n:
        songs = json.loads(ys.read_text(encoding='utf-8'))
        for s in songs:
            pj = ROOT / 'out' / 'yama' / f'{s["name"]}.nlmf'
            if pj.exists() and Path(s['src']).exists():
                pairs.append((str(pj), s['src']))
            if len(pairs) >= a.n + len(a.pair or []):
                break
    if not pairs:
        sys.exit('比べる曲が無い（cache/yama_set.json と out/yama/ か --pair）')
    res = []
    for pj, au in pairs:
        r = compare(pj, au)
        res.append((Path(pj).stem, r))
        if 'skip' in r:
            print(f'{Path(pj).stem}: 飛ばした（{r["skip"]}）')
            continue
        print(f'{Path(pj).stem}: テンポ {"一致" if r["tempo"] else "違う"}（BPM {r["bpm"]}/{r["bpm_nlm"]}・無音追加 {r["lead"]}/{r["lead_nlm"]}）・'
              f'区間 {"一致" if r["sections"] else "違う"} {r["n_sec"][0]}/{r["n_sec"][1]}・細かい区切り {"一致" if r["segments"] else "違う"}・'
              f'サビ {"一致" if r["chorus"] else "違う"}・{r["sec_tempo"]}+{r["sec_structure"]} 秒'
              + ('' if r['sections'] else f'（境目 {"同じ" if r["sections_bounds_same"] else "違う"}・名前 {"同じ" if r["sections_names_same"] else "違う"}）'))
    ok = [r for _, r in res if 'skip' not in r]
    allsame = [r for r in ok if r['tempo'] and r['sections'] and r['segments'] and r['chorus']]
    print(f'→ {len(allsame)}/{len(ok)} 曲で全部一致')
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(description='NLM から写した曲の解析の同じ所を保つ')
    ap.add_argument('--nlm', help='NLM のリポジトリの場所（無ければ環境変数 NLM_ROOT）')
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('diff').set_defaults(func=cmd_diff)
    sp.add_parser('update').set_defaults(func=cmd_update)
    c = sp.add_parser('check')
    c.add_argument('--n', type=int, default=5, help='cache/yama_set.json から比べる曲の数（0 で使わない）')
    c.add_argument('--pair', nargs=2, action='append', metavar=('NLMF', 'AUDIO'), help='比べる .nlmf と音源（くり返せる）')
    c.add_argument('--json', help='結果を書く')
    c.set_defaults(func=cmd_check)
    a = ap.parse_args(argv)
    a.func(a)


if __name__ == '__main__':
    main()
