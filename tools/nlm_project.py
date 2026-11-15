"""NLM を見えない状態で動かして（NLM の開発用の窓口・tools/nlm_cdp.py）、.nlmf を作る・確かめる。

NLM の serve.py を読み込むので、NLM の .venv-build の Python で動かす（NLM のフォルダに何も書かないよう PYTHONDONTWRITEBYTECODE=1）:
  NLM_ROOT=<NLM のリポジトリ> PYTHONDONTWRITEBYTECODE=1 <NLM>/.venv-build/Scripts/python.exe tools/nlm_project.py make <音源> \
      --bpm 129 --lead 240 --sections <区間の表.json> --out <出力.nlmf>
  … tools/nlm_project.py check <.nlmf>

make: 新規のプロジェクトで Expert+ に切り替え、音源を読み込み、BPM・無音追加を入れて「曲を解析」（テンポ→構成）を押し、
  NLM の保存と同じ中身（buildProjectText）を書く。区間の表（{"sections":[{beat,name}]}）があればマーカーにする。
  曲名・アーティストは音源のタグから。音源の実際の場所（graph.song.nativePath）を入れる＝exe 版で開くとダイアログ無しで音源を読む。
  テンポの推定が --bpm/--lead と違えば、推定は適用せず指定の値のまま構成を解析する（違いは表示する）。
--bpm・--lead を渡さなければ NLM のテンポの推定（提案）をそのまま使い、--sections を渡さなければ NLM の構成解析の区間をマーカーにする。
check: .nlmf を NLM で開き、レーン・クリップ・解析の帯（目盛りが解析した時と同じか）・NLM の譜面チェック（BS Map Check の移植）・
  JS のエラーを表示する。振りの続きの警告は置いた時だけの判定なので、ここでは数えない（automap/stats.py の nlm_swing が同じ決まり）。
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nlm_cdp import Editor  # noqa: E402

DIFFS = ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus']


def _send_file(ed, path, var='__automapFile'):
    """ファイルを操作用のパイプで少しずつページへ渡し、window[var] を File にする（NLM のページは自分のサーバー以外へ通信できない＝CSP）"""
    data = Path(path).read_bytes()
    ed.js(f"window.{var}_parts=[];true")
    step = 3 << 20
    for i in range(0, len(data), step):
        b64 = base64.b64encode(data[i:i + step]).decode('ascii')
        ed.js(f"window.{var}_parts.push(Uint8Array.from(atob('{b64}'),c=>c.charCodeAt(0)));true")
    ed.js(f"window.{var}=new File(window.{var}_parts,{json.dumps(Path(path).name)});delete window.{var}_parts;true")
    return f'window.{var}'


def _tags(path):
    try:
        import soundfile as sf
        with sf.SoundFile(str(path)) as f:
            return {'title': f.title or '', 'artist': f.artist or ''}
    except Exception:
        return {'title': '', 'artist': ''}


SET_FIELD_JS = """(id,val)=>{ const el=document.getElementById(id), v=el&&el.querySelector('.bfV'); if(!v) return false;
  v.dispatchEvent(new MouseEvent('click',{bubbles:true})); const inp=v.querySelector('input'); if(!inp) return false;
  inp.value=String(val); inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); if(v.querySelector('input')) inp.blur(); return true; }"""


def markers_from_analysis(an):
    """NLM の構成解析の区間 → マーカー [{beat, name}]。名前は解析の名前（イントロ・Aメロ・サビ…・無ければ番号）。
    同じ名前が続く区間（「サビ S4」「サビ S5」のような前半・後半）は1つにまとめる＝区間の表（コード譜から）と同じ粒度"""
    out = []
    for s in sorted((an.get('structure') or {}).get('sections') or [], key=lambda s: s['start']):
        name = (s.get('name') or s.get('label') or '').strip()
        if out and out[-1]['name'] == name:
            continue
        out.append({'beat': s['start'], 'name': name})
    return out


def make(a):
    src = Path(a.audio).resolve()
    tags = _tags(src)
    with Editor(ready=True) as ed:
        ed.js(f"window._dbg.rt.switchDiffByIndex({DIFFS.index(a.diff)});true")
        fv = _send_file(ed, src)
        ed.js(f"""(async()=>{{ const file={fv};
          await window._dbg.rt.loadSongFromItem({{isMusic:true,name:{json.dumps(src.stem)},songFh:{{getFile:async()=>file}},info:{{_beatsPerMinute:{a.bpm or 120}}}}},0);
          return true; }})()""")
        for _ in range(200):   # 音源のデコードを待つ
            if ed.js("window._dbgApp.nle().music.audio"):
                break
            ed.wait(0.1)
        if a.bpm:
            ed.js(f"({SET_FIELD_JS})('bpmField',{a.bpm})")
        if a.lead is not None:
            ed.js(f"({SET_FIELD_JS})('leadInField',{a.lead})")
        ed.wait(0.3)
        st = ed.js("({bpm:window._dbgApp.state().BPM, lead:window._dbgApp.prev().leadInMs})")
        print(f'目盛り: BPM {st["bpm"]}・無音追加 {st["lead"]} ms')
        ed.js("document.getElementById('anaStartBtn').click();true")
        t0 = time.time()
        while time.time() - t0 < 600:
            ed.wait(0.5)
            an = ed.js("window._dbgApp.analysis()") or {}
            run = an.get('running')
            if run and run.get('stage') == 'decide':
                txt = ed.js("(document.querySelector('#dirtyDlg.anaTempo')||{}).innerText||''")
                if txt:
                    print('テンポの推定（指定と違う）:', ' / '.join(l for l in txt.splitlines() if l.strip())[:400])
                    pick = 'none' if a.bpm else 'a'
                    ed.js(f"(document.querySelector('#dirtyDlg.anaTempo button[data-v=\"{pick}\"]')||{{click(){{}}}}).click();true")
            if not run and an.get('data') and an['data'].get('structure'):
                break
        else:
            raise SystemExit('曲の解析が10分で終わらなかった')
        an = ed.js("window._dbgApp.analysis()")
        print(f'解析: セクション {len(an["data"]["structure"]["sections"])}・細かい区切り {len(an["data"]["structure"]["segments"])}'
              f'・目盛りが変わった {an["stale"]}')
        pj = json.loads(ed.js("window._dbg.rt.buildProjectText()"))
        errs = ed.errors()
    # NLM の保存の中身に、ブラウザでは入らない物を足す
    pj['graph']['song']['nativePath'] = str(src)
    title = a.title or tags['title'] or src.stem
    artist = a.artist if a.artist is not None else tags['artist']
    pj['info'].update({'_songName': title, '_songAuthorName': artist})
    for n in (pj.get('infoGraph') or {}).get('nodes', {}).values():
        if n.get('t') == 'meta':
            n.setdefault('data', {}).update({'name': title, 'artist': artist})
    for ex in pj['graph'].get('extra') or []:
        if ex.get('kind') == 'info':
            ex.setdefault('data', {}).update({'_songName': title, '_songAuthorName': artist})
    if a.sections:
        secs = json.loads(Path(a.sections).read_text(encoding='utf-8'))['sections']
        pj['markers'] = [{'beat': s['beat'], 'name': s['name']} for s in secs]
    else:
        pj['markers'] = markers_from_analysis(pj.get('analysis') or {})
        print('マーカー（NLM の構成解析の区間から）:', ' / '.join(f"{m['beat']:g} {m['name']}" for m in pj['markers']))
    out = Path(a.out)
    if out.exists() and not a.force:
        raise SystemExit(f'もうある: {out}（上書きは --force）')
    out.write_text(json.dumps(pj, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'保存: {out}')
    if errs:
        print('JS のエラー:', *errs, sep='\n  ')


def check(a):
    pj = json.loads(Path(a.nlmf).read_bytes().decode('utf-8-sig'))
    with Editor(ready=True) as ed:
        ed.js(f"(async()=>{{ await window._dbg.rt.applyProject({json.dumps(pj, ensure_ascii=False)}); return true; }})()")
        ed.wait(1.0)
        nle = ed.js("window._dbgApp.nle()")
        an = ed.js("window._dbgApp.analysis()") or {}
        sw = ed.js("window._dbgApp.swing()")
        stt = ed.js("window._dbgApp.state()")
        print(f'難易度 {stt["diff"]}・BPM {stt["BPM"]}・数 {stt["counts"]}')
        print(f'レーン {nle["lanes"]}・クリップ {len(nle["clips"])}・マーカー {len(nle["markers"])}')
        if an.get('data'):
            print(f'解析の帯: 出ている {an.get("shown")}・目盛りが変わった {an.get("stale")}・{an.get("labels")[:20]}')
        print(f'振りの続きの警告（置いた時だけの判定・開いただけでは出ない）: {len(sw["warned"])} 個')
        mc = ed.js("""(async()=>{ const m=await import('/js/mapcheck/mapcheck.js'); const inp=await window._dbgApp.mapCheckInput();
          if(inp.error) return {error:inp.error}; const r=m.runMapCheck(inp);
          return {general:r.general.map(x=>[x.key,x.status]), diffs:r.diffs.map(d=>({d:d.difficulty, error:d.error||null,
            res:d.results.map(x=>({key:x.key, status:x.status, n:(x.objs||[]).length, beats:(x.objs||[]).slice(0,12).map(o=>o.beat)}))}))}; })()""")
        if mc.get('error'):
            print('譜面チェック:', mc['error'])
        else:
            print('譜面チェック（全体）:', mc['general'])
            for d in mc['diffs']:
                print(f'譜面チェック {d["d"]}:', d['error'] or '')
                for r in d['res']:
                    print(f'  [{r["status"]}] {r["key"]} {r["n"]} 個', r['beats'])
        errs = ed.errors()
        print('JS のエラー:', errs or 'なし')


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if not os.environ.get('NLM_ROOT'):
        raise SystemExit('環境変数 NLM_ROOT に NLM のリポジトリの場所を入れる')
    p = argparse.ArgumentParser(prog='nlm_project')
    sub = p.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('make')
    m.add_argument('audio')
    m.add_argument('--out', required=True)
    m.add_argument('--bpm', type=float)
    m.add_argument('--lead', type=float, help='無音追加（ms）')
    m.add_argument('--diff', default='ExpertPlus', choices=DIFFS)
    m.add_argument('--sections', help='区間の表（{"sections":[{beat,name}]}）→ マーカー')
    m.add_argument('--title')
    m.add_argument('--artist')
    m.add_argument('--force', action='store_true')
    m.set_defaults(func=make)
    c = sub.add_parser('check')
    c.add_argument('nlmf')
    c.set_defaults(func=check)
    a = p.parse_args(argv)
    a.func(a)


if __name__ == '__main__':
    main()
