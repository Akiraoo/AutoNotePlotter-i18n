"""型のライブラリの生データを取ってくる（docs/ライブラリ仕様.md 2 節）。取った物は捨てない・同じ物は二度取らない・止めても続きから。

使い方（置き場は --root か app/config.local.json の library_root・手元の譜面は --local か custom_levels）:
  python -I tools/library_build/fetch.py list            BeatLeader のランク譜面の一覧 → bl/<hash>.json（そのままの応答）・bl/_ranked.json（索引）
  python -I tools/library_build/fetch.py local           手元の譜面（CustomLevels）を写さずに登録（場所・並び・版の hash）→ local/index.json
  python -I tools/library_build/fetch.py meta            BeatSaver の譜面の情報（ランクの版と手元の版）→ meta/<key>.json（そのまま）・meta/_hashes.json（hash → key）
  python -I tools/library_build/fetch.py maps [--since 2020] [--skip-local] [--stars 4 10] [--limit N] [--dry]
                                                         BeatSaver の zip を展開してそのまま maps/<key>.<hash の頭 8> (<曲名> - <作者>)/ へ（maps_index.json に記録）
  python -I tools/library_build/fetch.py rate [--jobs 4] BeatLeader の★が無い難易度の★の近似（nlm-rating）→ rating/<hash>.json
                                                         （nlm-rating の版が上がったら測ってある物も測り直す＝BeatLeader の★と同じ計算にそろえる）
  python -I tools/library_build/fetch.py status          取った件数（★の帯・年ごと）と置き場の大きさ
  python -I tools/library_build/fetch.py all [maps の引数]  list → local → meta → maps → rate

取りに行く間は 1 秒あける（--gap）。429・5xx は間を延ばしてやり直し、続けて 5 回失敗したら止める（次に動かすと続きから）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

BANDS = tuple(zip(C.rating_scale.BANDS, C.rating_scale.BANDS[1:]))   # ★の帯（件数の表のため）
KEY_RE = re.compile(r'^[0-9a-f]{1,6}$')


def band(s):
    for lo, hi in BANDS:
        if lo <= s < hi:
            return f'{lo}-{hi}' if hi < 99 else f'{lo}-'
    return '?'


# ---- BeatLeader のランク譜面の一覧 ----

def cmd_list(a, root, http):
    pages, page, groups = 0, 1, defaultdict(list)
    while True:
        d = http.json(f'{C.BL_API}/leaderboards?page={page}&count=100&type=ranked&sortBy=timestamp&order=desc')
        for x in d.get('data') or []:
            groups[x['song']['hash'].lower()].append(x)
        total = d['metadata']['total']
        pages += 1
        print(f'  一覧 {min(page * 100, total)}/{total}', flush=True)
        if page * 100 >= total:
            break
        page += 1
    t = C.now()
    for h, lbs in groups.items():
        C.write_json(root / 'bl' / f'{h}.json', {'hash': h, 'fetched_at': t, 'leaderboards': lbs})
    idx = {h: [[x['difficulty']['modeName'], x['difficulty']['difficultyName'], x['difficulty']['stars'],
                x['difficulty'].get('rankedTime')] for x in lbs] for h, lbs in groups.items()}
    C.write_json(root / 'bl' / '_ranked.json', {'fetched_at': t, 'total': sum(map(len, groups.values())), 'hashes': idx})
    C.log(root, 'list', leaderboards=sum(map(len, groups.values())), hashes=len(groups), pages=pages)
    print(f'ランクの難易度 {sum(map(len, groups.values()))}・曲（版の hash）{len(groups)}')


def ranked_index(root):
    d = C.read_json(root / 'bl' / '_ranked.json')
    if not d:
        raise SystemExit('ランク譜面の一覧が無い（先に list）')
    return d['hashes']


# ---- 手元の譜面の登録 ----

def _sig(folder):
    """フォルダの中身が変わったかの目印（.dat の名前・大きさ・時刻）"""
    out = []
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith('.dat'):
            st = os.stat(os.path.join(folder, f))
            out.append([f, st.st_size, int(st.st_mtime)])
    return out


def cmd_local(a, root, http=None):
    lr = C.local_root(a.local)
    if not lr or not lr.is_dir():
        raise SystemExit('手元の譜面の場所が分からない（--local か app/config.local.json の custom_levels）')
    old = {e['name']: e for e in (C.read_json(root / 'local' / 'index.json') or {}).get('folders', [])}
    out, rehashed = [], 0
    for i, f in enumerate(os.listdir(lr)):   # 並びは os.listdir のまま（library_themes.py と同じ順で数えるため）
        p = lr / f
        if not p.is_dir():
            continue
        try:
            sig = _sig(p)
        except OSError:
            continue
        e = old.get(f)
        if not e or e.get('sig') != sig:
            h, kind = C.bs_hash(p)
            e = {'name': f, 'hash': h, 'kind': kind, 'sig': sig}
            rehashed += 1
        k = f.split(' ')[0].lower()
        e = {**e, 'order': i, 'key': k if KEY_RE.match(k) else None}
        out.append(e)
    C.write_json(root / 'local' / 'index.json', {'root': str(lr), 'registered_at': C.now(), 'folders': out})
    gone = len(set(old) - {e['name'] for e in out})
    C.log(root, 'local', folders=len(out), rehashed=rehashed, gone=gone)
    print(f'手元の譜面 {len(out)} フォルダ（hash を計算し直した {rehashed}・消えた {gone}）')


def local_index(root):
    return C.read_json(root / 'local' / 'index.json') or {'folders': []}


# ---- BeatSaver の譜面の情報 ----

def cmd_meta(a, root, http):
    hashes = C.read_json(root / 'meta' / '_hashes.json') or {}
    want = list(ranked_index(root))
    loc = local_index(root)['folders']
    want += [e['hash'] for e in loc if e.get('hash')]
    todo = list(dict.fromkeys(h for h in want if a.refresh or h not in hashes))
    print(f'BeatSaver の情報: 取る {len(todo)}（取ってある {len(set(want)) - len(todo)}）', flush=True)
    got = miss = 0
    for i in range(0, len(todo), 50):
        hs = todo[i:i + 50]
        try:
            d = http.json(f'{C.BS_API}/maps/hash/{",".join(hs)}')
        except C.NotFound:
            d = {}
        except Exception as e:
            C.log(root, 'meta-fail', hashes=hs, error=str(e))
            if http.fails >= 5:
                break
            continue
        if len(hs) == 1 and d and 'id' in d:
            d = {hs[0]: d}
        for h in hs:
            m = d.get(h)
            if m:
                C.write_json(root / 'meta' / f'{m["id"].lower()}.json', m)
                hashes[h] = {'key': m['id'].lower(), 'via': 'hash'}
                got += 1
            else:
                hashes[h] = {'key': None, 'via': None}
                miss += 1
        C.write_json(root / 'meta' / '_hashes.json', hashes)
        print(f'  {min(i + 50, len(todo))}/{len(todo)}', flush=True)
    # 版で見つからない手元の譜面は、フォルダ名の key で（古い版・BeatSaver に無い物）
    by_key = 0
    for e in loc:
        h, k = e.get('hash'), e.get('key')
        if not h or not k or (hashes.get(h) or {}).get('key') or (hashes.get(h) or {}).get('via') == 'id-miss':
            continue
        try:
            m = http.json(f'{C.BS_API}/maps/id/{k}')
            C.write_json(root / 'meta' / f'{m["id"].lower()}.json', m)
            hashes[h] = {'key': m['id'].lower(), 'via': 'id'}
            by_key += 1
        except C.NotFound:
            hashes[h] = {'key': None, 'via': 'id-miss'}
        except Exception as e:
            C.log(root, 'meta-fail', key=k, error=str(e))
            if http.fails >= 5:
                break
        C.write_json(root / 'meta' / '_hashes.json', hashes)
    C.log(root, 'meta', asked=len(todo), found=got, missing=miss, by_key=by_key)
    print(f'取った {got}・BeatSaver に版が無い {miss}（うちフォルダ名の key で見つけた {by_key}）')


def meta_of(root, hashes, h):
    k = (hashes.get(h) or {}).get('key')
    return C.read_json(root / 'meta' / f'{k}.json') if k else None


# ---- 譜面（zip）を取る ----

def _extract(zp, dst, limit=1 << 30):
    """zip を展開（フォルダの外へ書く名前・大きすぎる物は断る）"""
    dst.mkdir(parents=True)
    base = dst.resolve()
    with zipfile.ZipFile(zp) as z:
        if sum(i.file_size for i in z.infolist()) > limit:
            raise ValueError('展開すると大きすぎる')
        for i in z.infolist():
            name = i.filename.replace('\\', '/')
            if i.is_dir():
                continue
            if name.startswith('/') or ':' in name or any(p in ('..', '') for p in name.split('/')):
                raise ValueError(f'おかしな名前: {name!r}')
            out = (dst / name).resolve()
            if base not in out.parents:
                raise ValueError(f'フォルダの外: {name!r}')
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(out, 'wb') as f:
                shutil.copyfileobj(src, f)


def select(a, root):
    """取る候補: Standard のランクの難易度がある版（--stars の帯に入る物）・アップロード年 --since から・手元に同じ版が無い物（--skip-local）"""
    ranked = ranked_index(root)
    hashes = C.read_json(root / 'meta' / '_hashes.json') or {}
    have = C.read_json(root / 'maps_index.json') or {}
    local = {e['hash'] for e in local_index(root)['folders'] if e.get('hash')}
    out, skipped = [], Counter()
    for h, lbs in ranked.items():
        std = [x for x in lbs if x[0] == 'Standard']
        if a.stars:
            std = [x for x in std if a.stars[0] <= x[2] < a.stars[1]]
        if not std:
            skipped['★の帯の外' if a.stars else 'Standard のランクが無い'] += 1
            continue
        m = meta_of(root, hashes, h)
        if not m:
            skipped['BeatSaver の情報が無い'] += 1
            continue
        if a.since and (m.get('uploaded') or '')[:4] < str(a.since):
            skipped[f'{a.since} 年より前'] += 1
            continue
        if a.skip_local and h in local:
            skipped['手元にある'] += 1
            continue
        if h in have:
            skipped['取ってある'] += 1
            continue
        out.append((m.get('uploaded') or '', h, m))
    out.sort()
    return out, skipped


def cmd_maps(a, root, http):
    todo, skipped = select(a, root)
    if a.limit:
        todo = todo[:a.limit]
    print(f'取る {len(todo)}・取らない {dict(skipped)}', flush=True)
    if a.dry or not todo:
        return
    have = C.read_json(root / 'maps_index.json') or {}
    tmp = root / 'tmp'
    shutil.rmtree(tmp, ignore_errors=True)   # 前に止めた時の書きかけ
    tmp.mkdir(parents=True)
    (root / 'maps').mkdir(exist_ok=True)
    t0, total, n_ok = time.time(), 0, 0
    for i, (_, h, m) in enumerate(todo):
        bl = C.read_json(root / 'bl' / f'{h}.json') or {}
        url = next((x['song'].get('downloadUrl') for x in bl.get('leaderboards', []) if x['song'].get('downloadUrl')), None)
        url = url or next((v['downloadURL'] for v in m.get('versions', []) if v.get('hash') == h), None) or f'https://cdn.beatsaver.com/{h}.zip'
        md = m.get('metadata') or {}
        key = m['id'].lower()
        name = f'{key}.{h[:8]} ({C.safe_name(md.get("songName"))} - {C.safe_name(md.get("levelAuthorName"), 40)})'
        zp, work = tmp / f'{h}.zip', tmp / h
        try:
            size = http.download(url, zp)
            _extract(zp, work)
            got, kind = C.bs_hash(work)
            os.replace(work, root / 'maps' / name)
            zp.unlink()
        except Exception as e:
            shutil.rmtree(work, ignore_errors=True)
            zp.unlink(missing_ok=True)
            C.log(root, 'map-fail', hash=h, key=key, url=url, error=f'{type(e).__name__}: {e}')
            print(f'  [{i + 1}/{len(todo)}] {key} 失敗: {e}', flush=True)
            if http.fails >= 5:
                print('続けて 5 回失敗したので止める（次に動かすと続きから）')
                break
            continue
        ok = None if kind != 'ok' else (got == h)
        have[h] = {'folder': name, 'key': key, 'fetched_at': C.now(), 'bytes': size, 'hash_ok': ok, 'kind': kind}
        C.write_json(root / 'maps_index.json', have)
        C.log(root, 'map', hash=h, key=key, folder=name, bytes=size, hash_ok=ok)
        total += size
        n_ok += 1
        el = time.time() - t0
        print(f'  [{i + 1}/{len(todo)}] {key} {size / 1e6:.1f}MB{"" if ok is not False else "（hash が合わない）"}'
              f'・残り {el / (i + 1) * (len(todo) - i - 1) / 60:.0f} 分', flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'取った {n_ok}・{total / 1e9:.2f}GB・{(time.time() - t0) / 60:.1f} 分')


# ---- ★の近似（nlm-rating） ----

def rating_exe():
    p = os.environ.get('NLM_RATING_EXE') or C.config().get('nlm_rating_exe')
    return p if p and Path(p).exists() else None


def rating_version(exe):
    """nlm-rating の版（`--version`）。BeatLeader の計算が変わると上がる（v0.2.0＝2026-10 の PPv4）"""
    try:
        r = subprocess.run([exe, '--version'], capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return json.loads(r.stdout.decode('utf-8')).get('version')
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return None


def _rate_one(exe, folder, targets):
    files = []
    ip = C.find(folder, 'Info.dat')
    info = C.read_json(ip)
    files.append({'name': 'Info.dat', 'text': Path(ip).read_bytes().decode('utf-8-sig')})
    for s in info['_difficultyBeatmapSets']:
        for bm in s.get('_difficultyBeatmaps', []):
            if (s.get('_beatmapCharacteristicName'), bm.get('_difficulty')) in targets:
                p = C.find(folder, bm.get('_beatmapFilename', ''))
                if p:
                    files.append({'name': os.path.basename(p), 'text': Path(p).read_bytes().decode('utf-8-sig')})
    req = {'protocol': 1, 'files': files, 'targets': [{'characteristic': c, 'difficulty': d} for c, d in sorted(targets)]}
    r = subprocess.run([exe], input=json.dumps(req).encode('utf-8'), capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        return json.loads(r.stdout.decode('utf-8'))
    except ValueError:
        return {'ok': False, 'error': (r.stderr.decode('utf-8', 'replace') or 'no output')[-500:]}


def map_folders(root):
    """取った譜面と手元の譜面の (hash, フォルダ)"""
    out = []
    for h, e in (C.read_json(root / 'maps_index.json') or {}).items():
        out.append((h, root / 'maps' / e['folder']))
    li = local_index(root)
    for e in li['folders']:
        if e.get('hash'):
            out.append((e['hash'], Path(li['root']) / e['name']))
    return out


def cmd_rate(a, root, http=None):
    exe = rating_exe()
    if not exe:
        print('nlm-rating が無いので★の近似は飛ばす（app/config.local.json の nlm_rating_exe か 環境変数 NLM_RATING_EXE）')
        return
    ver = rating_version(exe)
    ranked = (C.read_json(root / 'bl' / '_ranked.json') or {}).get('hashes', {})
    jobs, seen, stale = [], set(), 0
    for h, folder in map_folders(root):
        old = C.read_json(root / 'rating' / f'{h}.json')
        # 測ってある物は飛ばす。ただし nlm-rating の版が違う物は測り直す（BeatLeader の★と同じ物差しにそろえる。版の無い前の失敗も 1 回だけ）
        if h in seen or (old and (old.get('ok') or old.get('per_target')) and old.get('exe_version', old.get('version')) == ver):
            continue
        seen.add(h)
        try:
            info = C.read_json(C.find(folder, 'Info.dat'))
            sets = info['_difficultyBeatmapSets']
        except Exception:
            continue
        have = {(x[0], x[1]) for x in ranked.get(h, [])}
        # Noodle・Mapping Extensions の難易度は型を取らない（4×3 のマスの外のノーツで nlm-rating も失敗する）ので測らない
        targets = {('Standard', bm.get('_difficulty')) for s in sets if s.get('_beatmapCharacteristicName') == 'Standard'
                   for bm in s.get('_difficultyBeatmaps', [])
                   if not any('Noodle' in q or 'Mapping Extensions' in q for q in ((bm.get('_customData') or {}).get('_requirements') or []))} - have
        if targets:
            jobs.append((h, folder, targets))
            stale += bool(old)
    print(f'★の近似を測る {len(jobs)} 曲（nlm-rating {ver}・前の版で測ってあった物 {stale}）', flush=True)
    t0 = time.time()

    def run(job):
        h, folder, targets = job
        try:
            r = _rate_one(exe, folder, targets)
            if not r.get('ok') and len(targets) > 1:   # 1つの難易度のせいで全部が失敗することがある → 難易度ごとに
                parts = [(t, _rate_one(exe, folder, {t})) for t in sorted(targets)]
                r = {'ok': any(p.get('ok') for _, p in parts),
                     'results': [x for _, p in parts for x in p.get('results') or []],
                     'errors': {f'{t[0]}/{t[1]}': p.get('error') for t, p in parts if not p.get('ok')}}
            if not r.get('ok'):
                r['per_target'] = True   # 難易度ごとにも測った＝次からは飛ばす
        except Exception as e:
            r = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
        C.write_json(root / 'rating' / f'{h}.json', {'hash': h, 'rated_at': C.now(), 'exe_version': ver, **r})
        return r.get('ok')

    ok = 0
    with ThreadPoolExecutor(a.jobs) as ex:
        for i, r in enumerate(ex.map(run, jobs)):
            ok += bool(r)
            if (i + 1) % 25 == 0 or i + 1 == len(jobs):
                print(f'  {i + 1}/{len(jobs)}（{(time.time() - t0) / 60:.1f} 分）', flush=True)
    C.log(root, 'rate', maps=len(jobs), ok=ok, version=ver, stale=stale)
    print(f'測った {ok}/{len(jobs)}')


# ---- 件数 ----

def _du(p):
    n = 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            n += os.path.getsize(os.path.join(dp, f))
    return n


def cmd_status(a, root, http=None):
    ranked = ranked_index(root)
    hashes = C.read_json(root / 'meta' / '_hashes.json') or {}
    have = C.read_json(root / 'maps_index.json') or {}
    local = {e['hash'] for e in local_index(root)['folders'] if e.get('hash')}
    tab = defaultdict(Counter)
    songs = defaultdict(lambda: [0, 0])
    for h, lbs in ranked.items():
        m = meta_of(root, hashes, h)
        y = (m or {}).get('uploaded', '????')[:4]
        where = '取った' if h in have else '手元' if h in local else None
        bands = set()
        for mode, diff, st, _ in lbs:
            if mode == 'Standard' and where:
                tab[band(st)][y] += 1
                bands.add(band(st))
        for b in bands:
            songs[b][0 if where == '取った' else 1] += 1
    years = sorted({y for t in tab.values() for y in t})
    print('ランクの Standard の難易度の数（取った物＋手元にある物）')
    print('★の帯 | ' + ' | '.join(years) + ' | 曲（取った・手元）')
    for lo, hi in BANDS:
        b = band(lo)
        print(f'{b} | ' + ' | '.join(str(tab[b][y]) for y in years) + f' | {songs[b][0]}・{songs[b][1]}')
    hok = Counter(e.get('hash_ok') for e in have.values())
    print(f'取った譜面 {len(have)}（hash 一致 {hok[True]}・不一致 {hok[False]}・確かめられない {hok[None]}）・'
          f'手元の譜面 {len(local_index(root)["folders"])}・BeatSaver の情報 {sum(1 for v in hashes.values() if v.get("key"))}')
    if (root / 'maps').exists():
        print(f'置き場の大きさ: maps {_du(root / "maps") / 1e9:.2f}GB・全体 {_du(root) / 1e9:.2f}GB')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['list', 'local', 'meta', 'maps', 'rate', 'status', 'all'])
    ap.add_argument('--root')
    ap.add_argument('--local')
    ap.add_argument('--gap', type=float, default=1.0)
    ap.add_argument('--since', type=int, default=2020)
    ap.add_argument('--skip-local', action='store_true')
    ap.add_argument('--stars', type=float, nargs=2)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--jobs', type=int, default=4)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    root = C.raw_root(a.root)
    root.mkdir(parents=True, exist_ok=True)
    http = C.Http(gap=a.gap)
    steps = ['list', 'local', 'meta', 'maps', 'rate'] if a.cmd == 'all' else [a.cmd]
    t0 = time.time()
    for s in steps:
        print(f'== {s}', flush=True)
        globals()[f'cmd_{s}'](a, root, http)
    print(f'（{(time.time() - t0) / 60:.1f} 分）')


if __name__ == '__main__':
    main()
