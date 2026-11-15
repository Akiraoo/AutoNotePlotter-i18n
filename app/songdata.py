"""曲のデータ（/api/song の中身の元・server.song_data が基準の難易度の譜面とクリップを足し、app/songcache.py が控える）。

分けた音（歌・ドラム・ベース・その他）のパートごとの大きさ・歌の高さ・ドラムと楽器の打点・区間（マーカー）・曲の流れの表のまとまり・
音から測ったくり返しの記号と調のずれ・盛り上がりの手がかり（ドラムの勢いと変わり目・歌の広がり・楽器の多さ・旋律楽器。automap/music.py）・
盛り上がりの繰り返しの候補（automap/hooks.py）を、曲の時刻（元の音源の秒）にそろえて返す（帯・3D・右の欄が使う）。
「比べる」の帯の前の版（試作4 の form-s1・試作5 の style-s1）のノーツもあれば入れる（古い曲の互換）。

前は tools/listen_page.py の中にあり、同じ中身でアプリより前の聞き比べ・意思入れ・3D のページ（out/listen/<曲>.html）も作っていた
（ページの部品 tools/listen/ と一緒に 2026-11-09 に除いた・docs/除いた物.md）。音の場所（src）は server.song_data が /audio/ で入れる。
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automap import diffs, form, hooks, music, nlmf, rhythm  # noqa: E402

STEMS = ('vocals', 'drums', 'bass', 'other')
ENV_FPS = 20


def envelope(path, fps=ENV_FPS):
    """1/fps 秒ごとの音の大きさ（dB・整数）"""
    y, sr = sf.read(str(path), dtype='float32', always_2d=True)
    y = y.mean(axis=1)
    hop = int(round(sr / fps))
    n = len(y) // hop
    p = (y[:n * hop].reshape(n, hop).astype(np.float64) ** 2).mean(axis=1)
    return np.round(10 * np.log10(p + 1e-10)).astype(int).tolist()


# ---- 分けた音と打点の候補だけで決まる重い所（大きさの線・拍ごとの特徴）の控え（このプロセスの中だけ・2026-11-11） ----
# 曲のデータは結果のファイルが変わるたびに作り直すが、重い所（5 秒のうち 4 秒ほど）は分けた音と onsets.json だけで決まる。
# 取り込みは最初の譜面を作っている間に prepare で先に作る（取り込みの後に曲を開く時の待ちを 5 秒 → 1 秒足らずに）。
# 鍵は読むファイルの場所・更新時刻・大きさ＝ファイルが変われば作り直す。
_MEMO, _MEMO_LOCK, MEMO_KEEP = {}, threading.Lock(), 8


def _memo(key, fn):
    with _MEMO_LOCK:
        if key in _MEMO:
            _MEMO[key] = _MEMO.pop(key)   # 使った順（一番後ろが新しい）
            return _MEMO[key]
    v = fn()
    with _MEMO_LOCK:
        _MEMO[key] = v
        while len(_MEMO) > MEMO_KEEP:
            del _MEMO[next(iter(_MEMO))]
    return v


def _stat(p):
    st = os.stat(p)
    return (os.path.abspath(p), st.st_mtime_ns, st.st_size)


def envelope_of(path):
    """envelope（控えから・写しを返す）"""
    return list(_memo(('env', _stat(path), ENV_FPS), lambda: envelope(path)))


def read_onsets(stems):
    """onsets.json の中身と鍵（読む前と後で更新時刻と大きさが同じ時だけ＝書き換えの前後を取り違えない）"""
    p = Path(stems) / 'onsets.json'
    for _ in range(100):
        a = _stat(p)
        d = json.loads(p.read_text(encoding='utf-8'))
        if _stat(p) == a:
            return d, a
        time.sleep(0.05)
    raise RuntimeError(f'{p.name} が書き換わり続けている')


def features_of(stems, ons, ons_key, bpm, lead_ms, n_beats):
    """music.beat_features（控えから・写しを返す）。ons_key＝ons を読んだ onsets.json の鍵（read_onsets）"""
    stems = Path(stems)
    key = ('feat', tuple(_stat(stems / f'{k}.flac') for k in ('bass', 'other', 'drums')), ons_key, bpm, lead_ms, n_beats)
    F = _memo(key, lambda: music.beat_features(stems, ons, bpm, lead_ms, n_beats))
    return {k: v.copy() for k, v in F.items()}


def _grid(proj, stems):
    """(BPM, 無音追加の秒, 拍の数)＝song_data と prepare が同じ物を使う"""
    bpm = float(proj['bpm'])
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    lead = -off if off < 0 else 0.0
    sep = json.loads((Path(stems) / 'separate.json').read_text(encoding='utf-8'))
    return bpm, lead, int((sep['seconds'] + lead) * bpm / 60)


def prepare(proj_path, stems, stop):
    """曲のデータの重い所を先に作って控える（取り込みが最初の譜面の compose と同時に呼ぶ）。onsets.json は compose が書くのを待つ
    （この曲の BPM・無音追加の物が読めるまで）。stop（threading.Event）が立った後は 1 度だけ見て、無ければやめる"""
    stems = Path(stems)
    for k in STEMS:
        envelope_of(stems / f'{k}.flac')
    proj = nlmf.load(proj_path)
    bpm, lead, n_beats = _grid(proj, stems)
    want = {'ver': rhythm.CACHE_VER, 'bpm': bpm, 'lead_ms': round(lead * 1000)}
    while True:
        last = stop.is_set()
        try:
            d, key = read_onsets(stems)
            if d.get('key') == want and 'bass' in d['onsets']:
                break
        except (OSError, ValueError, KeyError):   # まだ無い・書いている途中
            pass
        if last:
            return False
        stop.wait(0.2)
    features_of(stems, d['onsets'], key, bpm, round(lead * 1000), n_beats)
    return True


def song_data(name, proj_path, stems):
    """曲の名前・元にする .nlmf（結果のファイルか土台）・分けた音のフォルダ → 曲のデータ（JSON にできる辞書）"""
    stems = Path(stems)
    proj = nlmf.load(proj_path)
    if proj.get('tempoParts'):
        sys.exit('テンポパートのある曲はまだ扱えない')
    bpm, lead, n_beats = _grid(proj, stems)
    sec = lambda b: round(b * 60 / bpm - lead, 3)   # 拍 → 元の音源の秒
    marks = []
    for m in sorted((m for m in proj.get('markers') or [] if isinstance(m, dict) and isinstance(m.get('beat'), (int, float))),
                    key=lambda m: m['beat']):
        sec_name, tags = rhythm.parse_marker(m.get('name'))
        marks.append({'t': sec(m['beat']), 'beat': m['beat'], 'name': sec_name, 'tags': tags})
    rhythm.analyze(stems, bpm, round(lead * 1000))   # ベースの打点が無ければ足す（後から足した種類）
    ons_d, ons_key = read_onsets(stems)
    ons = ons_d['onsets']
    hits = {k: [[sec(o['raw']), round(o['s'], 2)] for o in ons.get(k, [])] for k in ('kick', 'snare', 'hihat', 'other', 'bass')}
    voc = [[sec(o['raw']), round(o['length'] * 60 / bpm, 3), round(o['midi'], 1), round(o['s'], 2)] for o in ons.get('vocal', [])]

    def notes_of(q):   # Expert+ のノーツ（無ければノーツの一番多い難易度＝基準を別の難易度に置き直した曲。アプリの帯は server.chart が基準から読む）
        ds = q.get('difficulties') or {}
        k = diffs.key('ExpertPlus') if diffs.key('ExpertPlus') in ds else max(ds, key=lambda k: diffs.notes_in(ds[k]), default=None)
        return [[sec(n['beat']), n['x'], n['y'], n['c'], n['d']] for n in nlmf.clip_notes(q, k)] if k else []
    notes = notes_of(proj)
    f4 = proj_path.parent / f'{name}.form-s1.nlmf'   # 試作4（曲の流れの表で作った譜面）があれば「比べる」の帯に並べる
    notes4 = notes_of(nlmf.load(f4)) if f4.exists() else []
    f5 = proj_path.parent / f'{name}.style-s1.nlmf'   # 試作5（曲の個性でテーマ）
    notes5 = notes_of(nlmf.load(f5)) if f5.exists() else []
    sep = json.loads((stems / 'separate.json').read_text(encoding='utf-8'))
    mu = music.analyze(stems, ons, bpm, round(lead * 1000), n_beats)
    F = features_of(stems, ons, ons_key, bpm, round(lead * 1000), n_beats)   # 拍ごとの歌の音名・伴奏の和音（似た所を探す・半音ずらしも比べる）
    bf = {'mel': music._norm_rows(F['mel'], music.FLOOR['mel']), 'acc': music._norm_rows(F['acc'], 1e-3, center=True)}
    blk = form.build(mu, proj.get('markers') or [], n_beats)
    blocks = [[sec(b.b0), sec(b.b1), b.group, b.base, b.level, b.b0, b.b1, b.vocal] for b in blk]
    try:   # 盛り上がりの繰り返しの候補（automap/hooks.py・アプリの右の欄）。探せなくても曲は開く
        hk, hk_err = hooks.detect(F, mu, blk, proj.get('markers') or []), None
    except Exception as e:   # noqa: BLE001
        hk, hk_err = [], f'{type(e).__name__}: {e}'
    return {
        'name': name, 'bpm': bpm, 'lead': lead, 'dur': sep['seconds'], 'fps': ENV_FPS, 'proj': proj_path.name,
        'env': {k: envelope_of(stems / f'{k}.flac') for k in STEMS},
        'marks': marks, 'hits': hits, 'voc': voc, 'notes': notes, 'notes4': notes4, 'notes5': notes5, 'blocks': blocks,
        'hooks': hk, 'hooks_error': hk_err,
        'mus': {'beats': mu['bars'], 'bars': [sec(b) for b in mu['bars']], 'lab': mu['lab'], 'shift': mu['shift'], 'inten': mu['inten'],
                'ssm': {k: [[round(v, 2) for v in row] for row in mu['ssm'][k]] for k in ('mel', 'acc')},
                'bf': {k: [[round(float(v), 2) for v in row] for row in bf[k]] for k in bf},
                'breaks': [[sec(x['beat']), round(x['len'] * 60 / bpm, 3), x['kind']] for x in mu['breaks']]},
    }
