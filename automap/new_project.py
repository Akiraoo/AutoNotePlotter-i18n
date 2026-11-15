"""新しい曲の元のプロジェクト（.nlmf）を、NLM を動かさずに作る（docs/アプリ仕様.md 8 節の6・アプリの曲の取り込み）。

中身は NLM が新しいプロジェクトを作って音源を読み込み、「曲を解析」（テンポ→構成）して保存した時と同じにする
（NLM の editor-app.js の buildProjectText・initScratchDiff・createExtra と、NLM で作った元のプロジェクトで確かめた形）:
- 既定の色・レーン（ノーツ 1・ライト 3）・難易度は NLM の既定の Hard（空）と、作る難易度（既定 Expert+・空）。開いている難易度は作る難易度。
- BPM・無音追加は曲の解析の目盛り（`analysis.grid`）＝推定を NLM の「適用」と同じく丸めた値か、人が決めた値。
  無音追加は `graph.song.offset`＝−無音追加の秒。音源の場所 `graph.song.nativePath`（exe 版の NLM が音源をダイアログ無しで読む）。
- 曲名・アーティストは音源のタグ（無ければファイル名）→ info・infoGraph の meta・曲の流れの画面の info のノード。
- マーカーは曲の解析の区間（tools/nlm_project.markers_from_analysis と同じ決まり）か、区間の表。
- 数は JS の JSON.stringify と同じ書き方（130.0 → 130・−0 → 0）。
カバー画像は前の tools/set_export.py（除いた）と同じ形で入れる（書き出し先の設定は入れない）。

使い方: .venv/Scripts/python.exe -m automap.new_project <音源> --out <元のプロジェクト.nlmf> [--analysis 解析.json]
        [--bpm B] [--lead-ms L] [--title 曲名] [--artist 名前] [--cover 画像] [--sections 区間の表.json] [--force]
  --analysis が無ければここで曲の解析をする（automap/analyze_song.py・15〜30 秒）。
"""
import argparse
import base64
import json
import math
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DIFFS = ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus']
NOTE_RED, NOTE_BLUE = 16721741, 3183359            # NLM の既定の色（ノーツ・ライト）
LIGHT_RED_B, LIGHT_BLUE_B = 16740255, 7331071      # ブーストの色
AUDIO_EXTS = ('.flac', '.wav', '.mp3', '.ogg', '.m4a', '.aac', '.opus', '.aiff', '.aif', '.wma')
IMAGE_EXTS = ('.jpg', '.jpeg', '.png')
COVER_NAMES = ('cover', 'folder', 'front', 'albumart', 'album', 'jacket', 'artwork', 'art')


# ---- 名前・音源の情報・カバー画像の候補 ----

def safe_name(text):
    """曲の名前（ファイル名・分けた音のフォルダ名に使う）。前の tools/new_song.song_name（除いた）と同じく Windows で使えない文字を _ に。
    加えて「.」も _ に（アプリはファイル名の最初の「.」より前を曲の名前とみる）・終わりの点と空白は落とす（Windows が落とす）"""
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(text or '')).strip().rstrip('. ')
    t = t.replace('.', '_').strip()
    if t.upper() in ('CON', 'PRN', 'AUX', 'NUL') or re.fullmatch(r'(?i)(COM|LPT)[1-9]', t):
        t += '_'
    return t or 'song'


# ---- 音源の場所（NLM が開いただけで読める場所） ----
# NLM（exe 版）は音源の場所（graph.song.nativePath）がドライブ名から始まる場所（C:\…・割り当てたネットワークドライブ Z:\… も）なら
# 開いただけで読むが、それ以外（\\NAS\共有\… の UNC 等）は「その PC の NLM のファイルの窓で一度選んだ物」しか読まない（NLM の
# native_paths._path_kind・app._NativeAccess.may_touch＝細工したファイルで Windows の認証を送らせないため）。NAS の音楽フォルダから
# 取り込んだ Joy to the love を NLM で開くと「音源が無い」になった（2026-11-03 利用者・案 A）→ そういう音源は分けた音のフォルダの
# source/ へ同じファイル名で写し、元のプロジェクトはその写しを指す（同じ名前＝NLM で選び直した時も「つなぎ直し」になる）。
SOURCE_DIR = 'source'


def nlm_readable(path):
    """NLM が開いただけで読める音源の場所か（NLM の native_paths._path_kind が 'local'＝ドライブ名から始まる絶対パス）"""
    s = str(path).replace('/', '\\')
    return len(s) >= 3 and s[0].isascii() and s[0].isalpha() and s[1] == ':' and s[2] == '\\'


def local_audio(audio, stems_dir, log=None):
    """音源 → NLM が開いただけで読める場所の音源（そのままか、stems_dir/source/<同じファイル名> への写し）。
    写しがもうあって大きさが同じなら使い回す。書きかけを残さない（.part に書いてから置き換える）"""
    audio = Path(audio)
    if nlm_readable(audio.absolute()):
        return audio
    say = log or (lambda s: None)
    dst = Path(stems_dir) / SOURCE_DIR / audio.name
    if dst.is_file() and dst.stat().st_size == audio.stat().st_size:
        say(f'NLM が開いただけでは読めない場所の音源なので、手元の写しを使う: {dst}')
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + '.part')
    shutil.copy2(audio, part)
    part.replace(dst)
    say(f'NLM が開いただけでは読めない場所（{audio}）の音源なので、手元へ写した: {dst}')
    return dst


def _ffprobe():
    ff = shutil.which('ffprobe')
    if ff:
        return ff
    fm = shutil.which('ffmpeg')
    if fm:
        p = Path(fm).with_name('ffprobe' + Path(fm).suffix)
        if p.exists():
            return str(p)
    return None


def audio_info(path):
    """音源の情報 {title, artist, seconds, sr, channels, format, soundfile}。タグと長さは soundfile（tools/nlm_project._tags と同じ）、
    読めない形式（m4a 等）やタグが無い時は ffprobe があればそれで。soundfile＝分ける時にそのまま読めるか"""
    path = Path(path)
    out = {'title': '', 'artist': '', 'seconds': None, 'sr': None, 'channels': None, 'format': path.suffix.lower().lstrip('.'), 'soundfile': False}
    try:
        import soundfile as sf
        with sf.SoundFile(str(path)) as f:
            out.update(title=(f.title or '').strip(), artist=(f.artist or '').strip(), seconds=round(f.frames / f.samplerate, 3),
                       sr=f.samplerate, channels=f.channels, format=f.format.lower(), soundfile=True)
    except Exception:   # noqa: BLE001
        pass
    if (out['seconds'] is None or not out['title']) and _ffprobe():
        try:
            r = subprocess.run([_ffprobe(), '-v', 'error', '-show_entries', 'format=duration:format_tags=title,artist:stream=sample_rate,channels',
                                '-select_streams', 'a:0', '-of', 'json', str(path)], capture_output=True, timeout=60,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            d = json.loads(r.stdout.decode('utf-8', 'replace') or '{}')
            fmt, st = d.get('format') or {}, (d.get('streams') or [{}])[0]
            tags = {k.lower(): v for k, v in (fmt.get('tags') or {}).items()}
            if out['seconds'] is None and fmt.get('duration'):
                out.update(seconds=round(float(fmt['duration']), 3), sr=int(st.get('sample_rate') or 0) or None, channels=st.get('channels'))
            if not out['title']:
                out['title'] = (tags.get('title') or '').strip()
                out['artist'] = out['artist'] or (tags.get('artist') or '').strip()
        except Exception:   # noqa: BLE001
            pass
    return out


def cover_candidates(path, limit=8):
    """カバー画像の候補: 音源と同じフォルダの Cover.jpg・folder.jpg・front.png 等（よくある名前から）→ ほかの画像"""
    folder = Path(path).parent
    try:
        imgs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    except OSError:
        return []

    def rank(p):
        s = p.stem.lower()
        for i, n in enumerate(COVER_NAMES):
            if s == n or s.startswith(n):
                return (i, s)
        return (len(COVER_NAMES), s)
    return [str(p) for p in sorted(imgs, key=rank)[:limit]]


# ---- マーカー・数の書き方 ----

def markers_from_analysis(an):
    """曲の解析の区間 → マーカー [{beat, name}]（tools/nlm_project.markers_from_analysis と同じ決まり。tests で同じ答えを確かめる）:
    名前は解析の名前（無ければ区間の記号）・同じ名前が続く区間は1つにまとめる"""
    out = []
    for s in sorted((an.get('structure') or {}).get('sections') or [], key=lambda s: s['start']):
        name = (s.get('name') or s.get('label') or '').strip()
        if out and out[-1]['name'] == name:
            continue
        out.append({'beat': s['start'], 'name': name})
    return out


def js_numbers(v):
    """JS の JSON.stringify と同じ数の書き方にそろえる（整数の値の小数 130.0 → 130・−0 → 0）"""
    if isinstance(v, float):
        if math.isfinite(v) and v == int(v) and abs(v) < 2 ** 53:
            return int(v)
        return v
    if isinstance(v, dict):
        return {k: js_numbers(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [js_numbers(x) for x in v]
    return v


def js_now():
    """new Date().toISOString() と同じ形（ミリ秒・Z）"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def _node_id(seq, rnd=random):
    """NLM の追加ノードの id（'x'＋通し番号＋4文字・createExtra）"""
    return 'x' + str(seq) + ''.join(rnd.choice('0123456789abcdefghijklmnopqrstuvwxyz') for _ in range(4))


def _empty_diff(name):
    """空の難易度（NLM の EMPTY_V3・encDiff の形）"""
    base = {'version': '3.2.0', 'bpmEvents': [], 'rotationEvents': [], 'colorNotes': [], 'bombNotes': [], 'obstacles': [], 'sliders': [],
            'burstSliders': [], 'waypoints': [], 'basicBeatmapEvents': [], 'colorBoostBeatmapEvents': [], 'lightColorEventBoxGroups': [],
            'lightRotationEventBoxGroups': [], 'basicEventTypesWithKeywords': {'d': []}, 'useNormalEventsAsCompatibleEvents': True}
    return {'name': name, 'v3': True, 'base': base, 'notes': [], 'bombs': [], 'walls': [], 'arcs': [], 'chains': [], 'lightEvents': [], 'sections': []}


# ---- 元のプロジェクト ----

def build(audio, analysis, title=None, artist=None, diff='ExpertPlus', markers=None, rnd=random):
    """音源の場所と曲の解析（analyze_song.analysis の形）→ NLM が新しいプロジェクトで保存するのと同じ中身（dict）。
    BPM・無音追加は analysis['grid']（構成を解析した時の目盛り）。markers が無ければ解析の区間から"""
    audio = Path(audio)
    if diff not in DIFFS:
        raise ValueError(f'難易度の名前が違う: {diff}（{DIFFS}）')
    g = (analysis or {}).get('grid') or {}
    if not g.get('bpm'):
        raise ValueError('曲の解析の結果に目盛り（grid.bpm）が無い')
    bpm, lead_ms = float(g['bpm']), float(g.get('leadMs') or 0)
    if title is None or artist is None:
        tg = audio_info(audio)
        title = title if title is not None else (tg['title'] or audio.stem)
        artist = artist if artist is not None else tg['artist']
    if markers is None:
        markers = markers_from_analysis(analysis)
    x_info, x_cover = _node_id(1, rnd), _node_id(2, rnd)
    cur = f'{diff}Standard.dat'
    diffs = {'hardstandard.dat': _empty_diff('HardStandard.dat')}   # NLM の新しいプロジェクトの既定＝Hard（initScratchDiff）
    diffs.setdefault(cur.lower(), _empty_diff(cur))
    proj = {
        'format': 'nlmf', 'version': 2, 'savedAt': js_now(), 'bpm': bpm, 'tempoParts': [], 'current': cur, 'musicBeat': 0, 'musicSegs': None,
        'songDeleted': False, 'noteRed': NOTE_RED, 'noteBlue': NOTE_BLUE, 'laserRed': NOTE_RED, 'laserBlue': NOTE_BLUE,
        'markers': [{'beat': m['beat'], 'name': m['name']} for m in markers], 'notesLanes': 1, 'lightLanes': 3,
        'info': {'_songName': title, '_songSubName': '', '_songAuthorName': artist, '_levelAuthorName': '', '_environmentName': '',
                 '_previewStartTime': 12, '_previewDuration': 10, '_beatsPerMinute': bpm},
        'infoGraph': {
            'nodes': {'m1': {'t': 'meta', 'x': 24, 'y': 16, 'data': {'name': title, 'sub': '', 'artist': artist, 'author': ''}},
                      's1': {'t': 'set', 'x': 336, 'y': 16, 'data': {'red': NOTE_RED, 'blue': NOTE_BLUE, 'lred': NOTE_RED, 'lblue': NOTE_BLUE,
                                                                      'lredB': LIGHT_RED_B, 'lblueB': LIGHT_BLUE_B, 'env': '', 'diffs': {}}},
                      'c1': {'t': 'cover', 'x': 24, 'y': 206, 'data': {'name': ''}},
                      'p1': {'t': 'prev', 'x': 336, 'y': 300, 'data': {'start': 12, 'dur': 10}}},
            'nseq': 1, 'outs': {'o1': {'x': 660, 'y': 100, 'folderName': '', 'outDirName': '', 'outDirPath': ''}}, 'activeOut': 'o1', 'oseq': 1,
            'edges': [{'s': 'm1', 'o': 'o1'}, {'s': 's1', 'o': 'o1'}, {'s': 'c1', 'o': 'o1'}, {'s': 'p1', 'o': 'o1'}],
            'cam': {'x': 0, 'y': 0, 's': 1, 'auto': 1}, 'prevMig': 1},
        'njsCfg': {}, 'coverData': {}, 'chainCurveGlobal': {}, 'chromaPalette': [],
        'laneStates': {'mute': [], 'solo': [], 'lock': []},
        'view': {'beat': 0, 'span': 32, 'b0': 0},
        'analysis': analysis,
        'graph': {
            'in': {'nx': 60, 'ny': 230}, 'out': {'nx': 1080, 'ny': 150, 'diffs': {}},
            'edges': [{'fromId': 'in', 'toId': 'song', 'sig': 'audio'}, {'fromId': 'song', 'toId': 'out', 'sig': 'audio'},
                      {'fromId': x_info, 'toId': 'out', 'sig': 'info'}, {'fromId': x_cover, 'toId': 'out', 'sig': 'cover'},
                      {'fromId': 'in', 'toId': 'out', 'sig': 'notes'}, {'fromId': 'in', 'toId': 'out', 'sig': 'lights'}],
            'song': {'nx': 310, 'ny': 360, 'name': audio.name, 'offset': -lead_ms / 1000, 'nativePath': str(audio.resolve())},
            'extra': [{'id': x_info, 'kind': 'info', 'nx': 620, 'ny': 60,
                       'data': {'_songName': title, '_songSubName': '', '_songAuthorName': artist, '_levelAuthorName': ''}, 'name': ''},
                      {'id': x_cover, 'kind': 'cover', 'nx': 620, 'ny': 350, 'data': {}, 'name': ''}],
            'altIns': [], 'altOuts': [], 'altSongs': [], 'activeUids': {'in': None, 'out': None, 'song': None}},
        'difficulties': diffs,
    }
    return js_numbers(proj)


def lead_sec(proj):
    """無音追加（秒）。graph.song.offset＝−無音追加の秒（負の時だけ）"""
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    return -float(off) if off < 0 else 0.0


def set_preview(proj, start=None):
    """試聴の区間（Beat Saber の曲を選ぶ画面で流れる所）: 最初の「サビ」の区間の頭から 10 秒（前の tools/set_export.py の --preview auto と同じ・
    2026-10-26 利用者）。サビが無ければ NLM の既定（12 秒から）のまま。start＝秒を直に。→ 入れた秒。
    試聴の秒は「元の音源の秒」（NLM の試聴ノードと同じ・書き出す時に NLM が無音追加の分を足す）＝拍の時刻から無音追加を引く
    （2026-11-03 まで引いておらず、書き出した試聴が無音追加の分＝0.2〜0.5 秒遅れていた）"""
    if start is None:
        from . import nlmf, rhythm
        s = next((s for s in rhythm.sections_from_markers(proj.get('markers') or [], 10 ** 6) if 'サビ' in s.name), None)
        if s is None:
            return proj['info'].get('_previewStartTime')
        start = round(max(0.0, nlmf.tempo_of(proj).sec(s.b0) - lead_sec(proj)), 2)
    proj['info']['_previewStartTime'], proj['info']['_previewDuration'] = start, 10
    for n in (proj.get('infoGraph') or {}).get('nodes', {}).values():
        if n.get('t') == 'prev':
            n['data'] = {**n.get('data', {}), 'start': start, 'dur': 10}
    return start


def set_cover(proj, out_path, cover, stem=None):
    """カバー画像を入れる（前の tools/set_export.py の apply のカバーの所と同じ形・書き出し先の設定は入れない）: 画像をプロジェクトの隣へ写し
    （<曲の名前>.<拡張子>・同じ名前で中身が違う物があれば上書きしない）、infoGraph の cover ノード・曲の流れの画面の cover ノード・
    coverData（base64 で同梱＝画像が無くても開ける）。→ 写した先のパス"""
    src, out_path = Path(cover), Path(out_path)
    if src.suffix.lower() not in IMAGE_EXTS or not src.is_file():
        raise ValueError(f'カバー画像は jpg・png のファイル: {src}')
    stem = stem or out_path.name.split('.')[0]
    data = src.read_bytes()
    ext = src.suffix.lower()
    dst = out_path.parent / f'{stem}{ext}'
    k = 0
    while dst.exists() and dst.read_bytes() != data:
        k += 1
        dst = out_path.parent / f'{stem}.cover{"" if k == 1 else k}{ext}'
    if not dst.exists():
        shutil.copyfile(src, dst)
    ig = proj.setdefault('infoGraph', {})
    nodes = ig.setdefault('nodes', {})
    cid = next((k_ for k_, v in nodes.items() if v.get('t') == 'cover'), None)
    if cid is None:
        cid = 'c1'
        nodes[cid] = {'t': 'cover', 'x': 24, 'y': 206, 'data': {}}
        oid = ig.get('activeOut') or 'o1'
        ig.setdefault('edges', []).append({'s': cid, 'o': oid})
    nodes[cid]['data'] = {**(nodes[cid].get('data') or {}), 'name': dst.name, 'nativePath': str(dst.resolve())}
    g = proj.setdefault('graph', {})
    extra = g.setdefault('extra', [])
    xc = next((x for x in extra if x.get('kind') == 'cover'), None)
    if xc is None:
        xc = {'id': 'xcover', 'kind': 'cover', 'nx': 620, 'ny': 350, 'data': {}, 'name': ''}
        extra.append(xc)
    xc['name'] = dst.name
    ge = g.setdefault('edges', [])
    if not any(e.get('fromId') == xc['id'] and e.get('toId') == 'out' and e.get('sig') == 'cover' for e in ge):
        ge.append({'fromId': xc['id'], 'toId': 'out', 'sig': 'cover'})
    proj['coverData'] = {cid: 'data:application/octet-stream;base64,' + base64.b64encode(dst.read_bytes()).decode('ascii')}
    return dst


def save(proj, path):
    """NLM の保存と同じ書き方（UTF-8・BOM なし・詰めた JSON・savedAt はミリ秒）。途中で止まっても前のファイルを壊さない"""
    path = Path(path)
    proj['savedAt'] = js_now()
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(js_numbers(proj), ensure_ascii=False, separators=(',', ':')), encoding='utf-8', newline='\n')
    tmp.replace(path)


def make(audio, out, analysis=None, bpm=None, lead_ms=None, title=None, artist=None, cover=None, sections=None, diff='ExpertPlus',
         log=print):
    """元のプロジェクトを作って out へ保存する → プロジェクト（dict）。analysis＝曲の解析の結果（dict か JSON のパス。無ければここで解析）・
    sections＝区間の表 [{beat, name}]（無ければ解析の区間をマーカーに）"""
    audio, out = Path(audio).resolve(), Path(out)
    if analysis is None:
        from . import analyze_song
        log('曲の解析（テンポの推定・構成）…')
        analysis = analyze_song.analysis(str(audio), bpm, lead_ms)
    elif not isinstance(analysis, dict):
        analysis = json.loads(Path(analysis).read_text(encoding='utf-8'))
    markers = [{'beat': s['beat'], 'name': s['name']} for s in sections] if sections else None
    proj = build(audio, analysis, title, artist, diff, markers)
    pv = set_preview(proj)   # NLM の新しいプロジェクトとの違いはここ（試聴を最初のサビに）とカバー画像だけ
    log(f'試聴の区間: {pv} 秒から 10 秒')
    out.parent.mkdir(parents=True, exist_ok=True)
    if cover:
        dst = set_cover(proj, out, cover)
        log(f'カバー画像: {dst.name}')
    save(proj, out)
    t = analysis.get('tempo') or {}
    g = analysis['grid']
    log(f'BPM {js_numbers(g["bpm"])}（推定 {t.get("bpm")}）・無音追加 {js_numbers(g["leadMs"])} ms（推定 {t.get("lead_ms")}）')
    log('マーカー: ' + (' / '.join(f'{m["beat"]:g} {m["name"]}' for m in proj['markers']) or '（無し）'))
    log(f'保存: {out}')
    return proj


# ---- 比べる（NLM で作った元のプロジェクトと） ----

def compare(mine, nlm):
    """2つのプロジェクトの違い [(場所, こちら, NLM)]。数は数として比べる（130 と 130.0 は同じ）。保存の時刻と、追加ノードの id の
    4 文字（でたらめ）は比べない"""
    def norm(p):
        p = json.loads(json.dumps(js_numbers(p)))
        p.pop('savedAt', None)
        ids = {x.get('id'): f'x{i + 1}' for i, x in enumerate(((p.get('graph') or {}).get('extra')) or [])}
        txt = json.dumps(p, ensure_ascii=False)
        for a, b in ids.items():
            if a:
                txt = txt.replace(json.dumps(a), json.dumps(b))
        return json.loads(txt)
    out = []

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in list(a) + [k for k in b if k not in a]:
                walk(a.get(k, '<無い>'), b.get(k, '<無い>'), f'{path}.{k}')
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f'{path}[{i}]')
        elif a != b:
            out.append((path, a, b))
    walk(norm(mine), norm(nlm), '')
    return out


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(prog='new_project', description='新しい曲の元のプロジェクト（.nlmf）を NLM を使わずに作る')
    ap.add_argument('audio')
    ap.add_argument('--out', required=True)
    ap.add_argument('--analysis', help='曲の解析の結果（analyze_song --json の出力）。無ければここで解析する')
    ap.add_argument('--bpm', type=float, help='BPM（無ければ解析の推定）')
    ap.add_argument('--lead-ms', type=float, help='無音追加（ms・無ければ解析の推定）')
    ap.add_argument('--title')
    ap.add_argument('--artist')
    ap.add_argument('--cover', help='カバー画像（jpg・png）')
    ap.add_argument('--sections', help='区間の表（{"sections":[{beat,name}]}）→ マーカー')
    ap.add_argument('--diff', default='ExpertPlus', choices=DIFFS)
    ap.add_argument('--force', action='store_true', help='もうあれば上書きする')
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists() and not a.force:
        sys.exit(f'もうある: {out}（上書きは --force）')
    secs = json.loads(Path(a.sections).read_text(encoding='utf-8'))['sections'] if a.sections else None
    lead = int(round(a.lead_ms)) if a.lead_ms is not None else None
    bpm = round(a.bpm, 2) if a.bpm is not None else None
    try:
        make(a.audio, out, a.analysis, bpm, lead, a.title, a.artist, a.cover, secs, a.diff)
    except Exception as e:   # noqa: BLE001  （解析できない音源など）
        sys.exit(f'元のプロジェクトを作れなかった: {e}')


if __name__ == '__main__':
    main()
