"""Beat Saber のプレイリスト（.bplist・PlaylistManager／BeatSaberPlaylistsLib の形）を読み書きする（docs/アプリ仕様.md 22 節・2026-11-03 利用者
「直通の所なんだけど、プレイリストにまとめて入れたい」）。

形: {playlistTitle, playlistAuthor, image（PNG・JPG の base64）, customData?, songs: [{hash, levelid: custom_level_<HASH>, songName,
levelAuthorName, difficulties: [{characteristic, name}], customData?}]}。知らない項目は消さずに残す（BeatLeader 等が作ったプレイリストにも足せる）。
ANP が足した曲には customData.anpFolder（書き出したフォルダ名）を入れ、同じ曲を書き出し直した時（hash が変わる）は前の行を置き換える。
"""
import base64
import json
import os
import re
from pathlib import Path

DEFAULT_TITLE = 'Auto Note Plotter'
DEFAULT_FILE = 'AutoNotePlotter.bplist'
# 難易度の名前（BeatSaver のプレイリストと同じ書き方）
DIFF_NAME = {'Easy': 'easy', 'Normal': 'normal', 'Hard': 'hard', 'Expert': 'expert', 'ExpertPlus': 'expertPlus'}


def load(path):
    with open(path, 'rb') as f:
        d = json.loads(f.read().decode('utf-8-sig'))
    if not isinstance(d, dict):
        raise ValueError(f'プレイリストの形が違います: {Path(path).name}')
    return d


def save(path, d):
    """一時ファイルに書いてから置き換える（書いている途中で止まってもプレイリストを壊さない）"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def list_playlists(folder):
    """フォルダの中のプレイリスト → [{file, title, author, songs, anp（ANP が書いた曲の数）}]（読めない物は飛ばす）"""
    out = []
    d = Path(folder) if folder else None
    if not d or not d.is_dir():
        return out
    for p in sorted(d.glob('*.bplist'), key=lambda q: q.name.lower()):
        try:
            pl = load(p)
        except (OSError, ValueError):
            continue
        songs = pl.get('songs') or []
        out.append({'file': p.name, 'title': pl.get('playlistTitle') or p.stem, 'author': pl.get('playlistAuthor') or '',
                    'songs': len(songs), 'anp': sum(1 for s in songs if isinstance(s, dict) and (s.get('customData') or {}).get('anpFolder'))})
    return out


def safe_file(title):
    """プレイリストの題名 → ファイル名（Windows で使えない字を _ に）"""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(title or '').strip()).strip(' .')
    return (s or 'playlist')[:80] + '.bplist'


def image_b64(path):
    """画像（PNG・JPG）→ base64 の文字（無い・読めない時は None）"""
    try:
        return base64.b64encode(Path(path).read_bytes()).decode('ascii') if path else None
    except OSError:
        return None


def entry(hash_, song_name, level_author, diffs, folder):
    """曲の行。hash＝BeatSaver の版の hash（Info.dat＋難易度の .dat の sha1）・diffs＝[(characteristic, 難易度の名前 'ExpertPlus' 等)]"""
    h = str(hash_).upper()
    return {'hash': h, 'levelid': f'custom_level_{h}', 'songName': song_name or '', 'levelAuthorName': level_author or '',
            'difficulties': [{'characteristic': ch, 'name': DIFF_NAME.get(n, n)} for ch, n in diffs],
            'customData': {'anpFolder': folder}}


def add_song(path, ent, title=None, author=None, image=None):
    """プレイリスト path に曲の行 ent を足す（無ければ作る＝title・author・image）。同じフォルダ（customData.anpFolder）か同じ hash の行は
    置き換える（並びの場所はそのまま）→ {'file', 'title', 'songs', 'replaced'}"""
    p = Path(path)
    if p.exists():
        pl = load(p)
    else:
        pl = {'playlistTitle': title or DEFAULT_TITLE, 'playlistAuthor': author or DEFAULT_TITLE, 'songs': []}
        if image:
            pl['image'] = image
    songs = pl.get('songs')
    if not isinstance(songs, list):
        songs = pl['songs'] = []
    folder = (ent.get('customData') or {}).get('anpFolder')
    same = [i for i, s in enumerate(songs) if isinstance(s, dict) and (
        (folder and (s.get('customData') or {}).get('anpFolder') == folder) or str(s.get('hash', '')).upper() == ent['hash'])]
    if same:
        songs[same[0]] = ent
        for i in reversed(same[1:]):   # 前に同じ曲が何行もあった時は 1 行に
            del songs[i]
    else:
        songs.append(ent)
    save(p, pl)
    return {'file': p.name, 'title': pl.get('playlistTitle') or p.stem, 'songs': len(songs), 'replaced': bool(same)}
