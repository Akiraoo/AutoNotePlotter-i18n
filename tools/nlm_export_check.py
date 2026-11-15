"""答え合わせ: 同じ .nlmf を NLM で書き出したフォルダと、automap/bs_export の書き出しを比べて違いを出す（GPLv3）。
NLM の版が上がった時にも使う（違いが出たら NLM の editor-app.js の exportMap の先を読み直して bs_export を写し直す）。

使い方:
  .venv/Scripts/python.exe tools/nlm_export_check.py <.nlmf> <NLM で書き出したフォルダ> [--work <作業フォルダ>] [--egg] [--marks]
  .venv/Scripts/python.exe tools/nlm_export_check.py --scan <.nlmf のフォルダ> <CustomLevels> [--work …] [--egg]
    --scan: フォルダの .nlmf の書き出すフォルダ名（graph.out.folderName）と同じ名前のフォルダを CustomLevels から探して全部比べる
            （.nlmf の保存の時刻と書き出したファイルの時刻も出す＝書き出した後に .nlmf が直された組は違って当たり前）。
  --egg: song.egg も作って比べる（作業フォルダに書く・1 曲 10〜30 秒）。長さ・頭の無音（元の音源とのずれ）・NLM の song.egg とのずれ。
  --marks: 書き出す難易度を書き出す印で選ぶ（既定は NLM と同じ＝中身のある難易度を全部）。
  --headless: 見えない NLM で .nlmf を開いて書き出させ（Info.dat と難易度の .dat・音源は読まない）、b のフォルダに置いてから比べる。
      NLM の .venv-build の Python で動かす: NLM_ROOT=<NLM> PYTHONDONTWRITEBYTECODE=1 <NLM>/.venv-build/Scripts/python.exe
      tools/nlm_export_check.py <.nlmf> <置き場> --headless（tests/data/bs_export/ の正解はこれで作った）
  どちらのフォルダにも書かない（作業フォルダの中だけ）。.nlmf・NLM の書き出しは読むだけ。

比べる物: Info.dat・難易度の .dat（バイトまで同じか・JSON として同じか・違う所）・BeatSaver の hash・カバー画像・.nlm-egg.json の印。
ANP の印（Info.dat の _customData._editors・bs_export.put_mark＝写しと違う所）: NLM の書き出しには無いので、こちらも入れずに作って比べる。
相手のフォルダの Info.dat に ANP の印がある（ANP で書き出した物＝--scan で拾う）時は、同じ版の印を入れて比べる。
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from automap import bs_export as B  # noqa: E402
from automap import nlmf  # noqa: E402


def _walk(a, b, path, out, lim=40):
    if len(out) >= lim:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b) and set(a) == set(b):
            out.append((path + '（項目の順）', list(a), list(b)))
        for k in list(a) + [k for k in b if k not in a]:
            _walk(a.get(k, '<無い>'), b.get(k, '<無い>'), f'{path}.{k}', out, lim)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path + '（数）', len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, f'{path}[{i}]', out, lim)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        if a != b:
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))


def compare_bytes(name, mine, theirs):
    """1 つのファイル → (同じか, JSON として同じか, 違い)"""
    if mine == theirs:
        return 'バイトまで同じ', []
    try:
        ja, jb = json.loads(mine.decode('utf-8-sig')), json.loads(theirs.decode('utf-8-sig'))
    except ValueError:
        return '違う（JSON でない）', []
    diff = []
    _walk(ja, jb, name, diff)
    return ('JSON として同じ（書き方だけ違う）' if not diff else 'JSON が違う'), diff


def _decode(path, seconds=None):
    import soundfile as sf
    with sf.SoundFile(str(path)) as f:
        n = f.frames if seconds is None else min(f.frames, int(seconds * f.samplerate))
        x = f.read(n, dtype='float32', always_2d=True)
        return x.mean(axis=1), f.samplerate, f.frames, f.channels


def lag(a, b, max_lag):
    """b が a より何サンプル遅れているか（相互相関の山）"""
    import numpy as np
    n = 1
    while n < len(a) + len(b):
        n *= 2
    fa, fb = np.fft.rfft(a, n), np.fft.rfft(b, n)
    cc = np.fft.irfft(np.conj(fa) * fb, n)
    lags = np.r_[0:max_lag + 1, -max_lag:0]
    vals = np.r_[cc[0:max_lag + 1], cc[n - max_lag:n]]
    i = int(np.argmax(vals))
    return int(lags[i]), float(vals[i] / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-12))


def egg_check(proj_path, nlm_dir, work, say):
    """こちらの song.egg を作って、NLM の song.egg・元の音源と比べる"""
    proj = nlmf.load(proj_path)
    ctx = B._ctx(proj)
    if not ctx.audio_ok:
        say(f'  song.egg: 音源が無い（{ctx.audio}）')
        return
    work.mkdir(parents=True, exist_ok=True)
    mine = work / 'song.egg'
    if ctx.sf_ok:
        total, sr = B.write_egg_sf(ctx.audio, mine, ctx.egg)
    else:
        B.write_egg_ffmpeg(ctx.audio, mine, ctx.egg)
    theirs = Path(nlm_dir) / 'song.egg'
    a, sra, na, cha = _decode(mine)
    say(f'  song.egg（こちら）: {na} サンプル（{na / sra:.4f} 秒・{sra} Hz・{cha} ch・{mine.stat().st_size} バイト）・無音追加 {ctx.egg["lead_in_ms"]} ms'
        f'＝{B.delay_samples(ctx.egg["lead_in_ms"], sra) if ctx.egg["lead_in_ms"] else 0} サンプル・切り貼り {ctx.egg["segs"]}・音量 {ctx.egg["gain_db"]} dB')
    if not theirs.is_file():
        say('  song.egg（NLM）: 無い')
        return
    b, srb, nb, chb = _decode(theirs)
    say(f'  song.egg（NLM）: {nb} サンプル（{nb / srb:.4f} 秒・{srb} Hz・{chb} ch・{theirs.stat().st_size} バイト）・長さの差 {na - nb} サンプル')
    if sra == srb:
        k = min(len(a), len(b), sra * 40)
        lg, r = lag(b[:k], a[:k], 4000)
        say(f'  NLM に対するこちらのずれ: {lg} サンプル（相関 {r:.4f}・0 なら同じ位置）')
        src, srs, ns, _ = _decode(ctx.audio, 40)
        if srs == sra and ctx.egg['segs'] is None:
            k2 = min(len(src), len(b))
            lb, rb = lag(src[:k2], b[:k2], 20000)
            la, ra = lag(src[:k2], a[:k2], 20000)
            say(f'  元の音源からの遅れ: NLM {lb} サンプル（相関 {rb:.3f}）・こちら {la} サンプル（相関 {ra:.3f}）')
        import numpy as np
        m = min(len(a), len(b))
        if lg == 0 and m:
            d = a[:m] - b[:m]
            say(f'  音の違い（同じ位置で引いた大きさ）: 最大 {float(np.abs(d).max()):.4f}・平均 {float(np.abs(d).mean()):.5f}'
                f'（vorbis の作り直しの違い＝0.0x 程度なら同じ音）')


def their_mark(nlm_dir):
    """相手のフォルダの Info.dat の ANP の印（版の文字）か None（NLM の書き出し・読めない）"""
    try:
        return B.anp_mark(json.loads((Path(nlm_dir) / 'Info.dat').read_bytes().decode('utf-8-sig')))
    except (OSError, ValueError):
        return None


def check(proj_path, nlm_dir, work=None, egg=False, marks=False, say=print, audio=True):
    """1 組を比べる → 違いの数（0 ならバイトまで全部同じ）"""
    proj = nlmf.load(proj_path)
    nlm_dir = Path(nlm_dir)
    mark = their_mark(nlm_dir)
    if mark:
        say(f'  相手の Info.dat に ANP の印（版 {mark}）＝ANP で書き出した物 → こちらも同じ印を入れて比べる')
    try:
        b = B.build(proj, None if marks else 'all', audio=audio, mark=mark or False)   # NLM の書き出しとは印なしで比べる
    except B.BsExportError as e:
        say(f'  書き出せない（BsExportError）: {e}')
        if egg:   # 譜面は書けなくても音は比べられる
            egg_check(proj_path, nlm_dir, Path(work or '.') / ('egg-' + nlm_dir.name), say)
        return 1
    ctx = b['ctx']
    bad = 0
    say(f'  開いた難易度: {ctx.cur}・書き出す難易度: {", ".join(b["chosen"])}')
    for name, data in b['files'].items():
        p = nlm_dir / name
        if not p.is_file():
            say(f'  {name}: NLM の書き出しに無い')
            bad += 1
            continue
        st, diff = compare_bytes(name, data, p.read_bytes())
        say(f'  {name}: {st}')
        if st != 'バイトまで同じ':
            bad += 1
            for path, x, y in diff[:12]:
                say(f'    {path}: こちら {json.dumps(x, ensure_ascii=False)[:120]} ／ NLM {json.dumps(y, ensure_ascii=False)[:120]}')
    try:
        ninfo = json.loads((nlm_dir / 'Info.dat').read_bytes().decode('utf-8-sig'))
        nnames = [bm['_beatmapFilename'] for s in ninfo['_difficultyBeatmapSets'] for bm in s['_difficultyBeatmaps']]
        extra = [n for n in nnames if n not in b['files']]
        if extra:
            say(f'  NLM だけが書いた難易度: {extra}')
            bad += 1
        h = hashlib.sha1((nlm_dir / 'Info.dat').read_bytes())
        for n in nnames:
            if (nlm_dir / n).is_file():
                h.update((nlm_dir / n).read_bytes())
        mine_h = B.map_hash(b['files'], b['info'])
        say(f'  BeatSaver の hash: {"同じ" if mine_h == h.hexdigest() else "違う"}（こちら {mine_h}・NLM {h.hexdigest()}）')
    except (OSError, ValueError, KeyError) as e:
        say(f'  NLM の Info.dat を読めない: {e}')
        bad += 1
    if b['cover']:
        p = nlm_dir / b['cover'][0]
        same = p.is_file() and p.read_bytes() == b['cover'][1]
        say(f'  カバー画像 {b["cover"][0]}: {"同じ" if same else "違う・無い"}')
        bad += 0 if same else 1
    if ctx.audio_ok:
        mark = B.egg_mark(ctx.audio, ctx.egg)
        try:
            prev = json.loads((nlm_dir / '.nlm-egg.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            prev = None
        say(f'  .nlm-egg.json の印: {"同じ（NLM もこちらも song.egg を作り直さない）" if B.egg_same(prev, mark) else "違う"}'
            + ('' if B.egg_same(prev, mark) else f'（こちら {B.js_dumps(mark)}・NLM {json.dumps(prev, ensure_ascii=False)}）'))
    if egg:
        egg_check(proj_path, nlm_dir, Path(work or '.') / ('egg-' + nlm_dir.name), say)
    return bad


CAPTURE_JS = """(()=>{ window.__cap=[]; HTMLAnchorElement.prototype.click=function(){ window.__cap.push([this.download,this.href]); };
  URL.revokeObjectURL=()=>{}; return true; })()"""


def headless(proj_path, save, say=print):
    """見えない NLM で .nlmf を開いて書き出させる（書き出し先が無い時のダウンロードの形を受け取る＝Info.dat と難易度の .dat。
    音源は読み込まない）→ save に書く。NLM の .venv-build の Python で動かす（環境変数 NLM_ROOT・PYTHONDONTWRITEBYTECODE=1）"""
    sys.path.insert(0, str(ROOT / 'tools'))
    from nlm_cdp import Editor
    pj = json.loads(Path(proj_path).read_bytes().decode('utf-8-sig'))
    save = Path(save)
    save.mkdir(parents=True, exist_ok=True)
    with Editor(ready=True) as ed:
        ed.js(f"(async()=>{{ await window._dbg.rt.applyProject({json.dumps(pj, ensure_ascii=False)}); return true; }})()")
        ed.wait(1.0)
        ed.js(CAPTURE_JS)
        ed.js("(async()=>{ await window._dbg.rt.exportMap(); return true; })()")
        ed.wait(0.5)
        files = ed.js("(async()=>{ const o={}; for(const [n,h] of window.__cap){ o[n]=await (await fetch(h)).text(); } return o; })()") or {}
        errs = ed.errors()
    for n, t in files.items():
        (save / n).write_bytes(t.encode('utf-8'))
    say(f'  NLM の書き出し（見えない NLM・{len(files)} ファイル）: {save}' + (f'・JS のエラー {errs}' if errs else ''))
    return files


def _time(p):
    return datetime.datetime.fromtimestamp(os.stat(p).st_mtime).strftime('%Y-%m-%d %H:%M:%S')


def scan(proj_dir, levels, work=None, egg=False, marks=False, say=print):
    total = 0
    for p in sorted(Path(proj_dir).glob('*.nlmf')):
        try:
            proj = nlmf.load(p)
        except (OSError, ValueError):
            continue
        fn = ((proj.get('graph') or {}).get('out') or {}).get('folderName')
        d = Path(levels) / fn if fn else None
        if not d or not (d / 'Info.dat').is_file():
            continue
        sa = proj.get('savedAt')
        say(f'== {p.name} → {fn}（.nlmf の保存 {sa}・NLM の Info.dat {_time(d / "Info.dat")}）')
        total += check(p, d, work, egg, marks, say) > 0
    say(f'違いのあった組: {total}')
    return total


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(prog='nlm_export_check', description='NLM の書き出しと bs_export の書き出しを比べる')
    ap.add_argument('a', help='.nlmf（--scan の時は .nlmf のフォルダ）')
    ap.add_argument('b', help='NLM で書き出したフォルダ（--scan の時は CustomLevels）')
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--work', help='song.egg を作る作業フォルダ')
    ap.add_argument('--egg', action='store_true')
    ap.add_argument('--marks', action='store_true')
    ap.add_argument('--headless', action='store_true',
                    help='b のフォルダへ見えない NLM で書き出させてから比べる（NLM の .venv-build の Python で・音源は読まない）')
    a = ap.parse_args(argv)
    if a.headless:
        headless(a.a, a.b)
        return 1 if check(a.a, a.b, a.work, False, a.marks, audio=False) else 0
    if a.scan:
        return 1 if scan(a.a, a.b, a.work, a.egg, a.marks) else 0
    return 1 if check(a.a, a.b, a.work, a.egg, a.marks) else 0


if __name__ == '__main__':
    sys.exit(main())
