"""NLM のプロジェクトファイル（.nlmf）の読み書き。

形は NLM の保存形式 version 2（editor-app.js の `_ENC`・`encArr`・`encSec`・`encDiff`）に合わせる。
- 物はタプル: ノーツ = [拍, x, y, c, d, _tr, raw?]（_tr＝レーン、raw＝標準外の項目）。
- 難易度ごとに `sections`（クリップ）と、それを合成したフラットの配列（notes 等・絶対拍＋_tr）を持つ。
  **正はクリップの中身**（NLM は開くたびにクリップからフラットを作り直す）。クリップの中身の拍はクリップの頭からの拍で、
  見えるのは 0 以上・長さ未満だけ（範囲の外はトリムで隠れた分）。
- レーンの内部の番号（track・_tr・laneStates の 'n2' 等）は **0 が一番上**、一番下（表示の Notes 1）が notesLanes-1。
  レーンを一番上に足す時は、既存のノーツ系の番号を全部ずらす（NLM の laneShiftAll と同じ）。
- ミュートは 3D の表示で隠れるだけ（左上の窓・重なりや振りの続きの判定には入る）＝作った譜面の難易度に別の譜面を残さない。
- 作ったクリップの id は「'au' ＋ 中身の指紋 7 文字」（clip_id）。読み込んだ時に計算し直して比べれば、NLM で直されたかがファイルだけで分かる
  （コピーしたファイルを別々に直しても、それぞれ自分で判定できる）。NLM がクリップを作る時（新規・貼り付け・分けた後ろ側・つなげた物）の
  id は 'n…' なので重ならない。NLM はクリップの項目をそのまま保存する（editor-app.js の encSec）。
"""
import hashlib
import json
from datetime import datetime, timezone

NOTE_F = ['beat', 'x', 'y', 'c', 'd']
N_KEYS = ['notes', 'bombs', 'walls', 'arcs', 'chains']   # ノーツ系（lk='n'）の中身。ライトは 'lights'
BEAT_IDX = {'notes': (0,), 'bombs': (0,), 'walls': (0,), 'arcs': (0, 6), 'chains': (0, 5)}   # 拍の項目（アーク・チェーンは頭と尾）
FLAT_N = ['notes', 'bombs', 'walls', 'arcs', 'chains']   # 難易度のフラットのノーツ系の配列
LANE_MAX = 10


def load(path):
    with open(path, 'rb') as f:
        d = json.loads(f.read().decode('utf-8-sig'))
    if d.get('format') not in ('nlmf', 'bslm', 'bsnm') or d.get('version') != 2:
        raise ValueError('NLM の保存形式 version 2 の .nlmf だけを扱う')
    return d


def save(proj, path):
    proj['savedAt'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(proj, f, ensure_ascii=False, separators=(',', ':'))


def diff_key(proj, name=None):
    """難易度のキー（difficulties の小文字のキー）。name が無ければ開いていた難易度。"""
    name = (name or proj.get('current') or '').lower()
    if name in proj['difficulties']:
        return name
    for k in (name + 'standard.dat', name + '.dat'):   # 'expert' は 'expertstandard.dat'（頭が同じ 'expertplus…' を先に拾わない）
        if k in proj['difficulties']:
            return k
    for k in proj['difficulties']:
        if k.startswith(name) and not (name.endswith('expert') and k[len(name):].startswith('plus')):
            return k
    raise KeyError(f'難易度が無い: {name}（ある物: {", ".join(proj["difficulties"])}）')


class TempoMap:
    """拍→秒（NLM の beatToTimeTM と同じ。曲頭＝拍0からの秒。無音追加は含まない）。"""

    def __init__(self, bpm, parts=()):
        self.bpm = float(bpm)
        self.parts = sorted(({'beat': float(p['beat']), 'bpm': float(p['bpm'])} for p in parts or []), key=lambda p: p['beat'])

    def sec(self, b):
        bb, bpm, tt = 0.0, self.bpm, 0.0
        for p in self.parts:
            if p['beat'] >= b:
                break
            tt += (p['beat'] - bb) * 60 / bpm
            bb, bpm = p['beat'], p['bpm']
        return tt + (b - bb) * 60 / bpm


def tempo_of(proj):
    return TempoMap(proj.get('bpm') or 120, proj.get('tempoParts') or [])


def clip_notes(proj, dkey, tracks=None, include_muted=False):
    """クリップの見えている範囲のノーツ（絶対拍）。[{beat,x,y,c,d,tr,clip}] を拍の順に。"""
    st = proj['difficulties'][dkey]
    muted = set((proj.get('laneStates') or {}).get('mute') or [])
    out = []
    for s in st.get('sections') or []:
        if s.get('lk') == 'l' or s.get('kind') == 'null':
            continue
        tr = s.get('track') or 0
        if tracks is not None and tr not in tracks:
            continue
        if not include_muted and f'n{tr}' in muted:
            continue
        b0, L = s.get('beat') or 0, s.get('len') or 4
        for a in (s.get('content') or {}).get('notes') or []:
            if not isinstance(a, list) or a[0] is None:
                continue
            if 0 <= a[0] < L:
                out.append({'beat': a[0] + b0, 'x': a[1], 'y': a[2], 'c': a[3], 'd': a[4], 'tr': tr, 'clip': s.get('id')})
    out.sort(key=lambda n: (n['beat'], n['c'], n['x'], n['y']))
    return out


def items_before(proj, dkey, beat, ids=None):
    """その難易度のノーツ系のクリップの中身のうち、見えている（0 ≤ 拍 < 長さ）・絶対拍が beat より前の物 → {種類: [絶対拍のタプル]}。
    タプルは保存形式のまま（標準外の項目＝raw・矢印の角度なども残る）。拍の項目だけ絶対拍にし、レーン（_tr）は None にする。
    ids を渡すと、その id のクリップだけ"""
    st = proj['difficulties'][dkey]
    out = {k: [] for k in N_KEYS}
    for s in st.get('sections') or []:
        if s.get('lk') == 'l' or s.get('kind') == 'null' or (ids is not None and s.get('id') not in ids):
            continue
        b0, L = s.get('beat') or 0, s.get('len') or 4
        for key, arr in (s.get('content') or {}).items():
            if key not in out:
                continue
            fi = len(_enc_fields(key))
            for a in arr or []:
                if not isinstance(a, list) or a[0] is None or not (0 <= a[0] < L) or a[0] + b0 >= beat - 1e-9:
                    continue
                t = list(a)
                for i in BEAT_IDX[key]:
                    if i < len(t) and t[i] is not None:
                        t[i] = _r(t[i] + b0)
                if len(t) > fi:
                    t[fi] = None
                out[key].append(t)
    for k in out:
        out[k].sort(key=lambda t: t[0])
    return out


def items_between(sec, b0, b1):
    """1つのクリップの中身のうち、見えていて絶対拍が b0 以上 b1 未満の物 → {種類: [絶対拍のタプル]}（保存形式のまま・レーンは None）。
    選んだ区間だけ作り直す時に、区間をまたぐ作ったクリップの外側を同じ中身の新しいクリップにする"""
    out = {}
    base, L = sec.get('beat') or 0, sec.get('len') or 4
    for key, arr in (sec.get('content') or {}).items():
        if key not in N_KEYS:
            continue
        fi = len(_enc_fields(key))
        for a in arr or []:
            if not isinstance(a, list) or a[0] is None or not (0 <= a[0] < L) or not (b0 - 1e-9 <= a[0] + base < b1 - 1e-9):
                continue
            t = list(a)
            for i in BEAT_IDX[key]:
                if i < len(t) and t[i] is not None:
                    t[i] = _r(t[i] + base)
            if len(t) > fi:
                t[fi] = None
            out.setdefault(key, []).append(t)
    return out


APP_LABEL = '自動'   # 作ったクリップの名前の頭
KEEP_WORD = '固定'   # クリップの名前に入れると、作り直しでも残す（NLM で利用者が付ける）
_B36 = '0123456789abcdefghijklmnopqrstuvwxyz'


def _canon(v):
    """指紋のための正規化: 数は小数 4 桁の float・タプルの後ろの None は落とす（NLM が保存で省いても同じになるように）"""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    if isinstance(v, list):
        t = [_canon(x) for x in v]
        while t and t[-1] is None:
            t.pop()
        return t
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in sorted(v.items())}
    return v


def fingerprint(dkey, sec):
    """クリップの指紋（7 文字）: 難易度のキー・始まりの拍・長さ・中身（全部の種類・並び順は問わない）。
    レーンの番号は入れない（NLM で一番上にレーンを足すと全部のクリップの番号がずれ、全部「直した」に見えてしまう）"""
    c = sec.get('content') or {}
    body = {k: sorted(json.dumps(_canon(t), ensure_ascii=False, sort_keys=True) for t in c[k]) for k in sorted(c) if c.get(k)}
    key = json.dumps([dkey, _canon(sec.get('beat') or 0), _canon(sec.get('len') or 0), body], ensure_ascii=False, sort_keys=True)
    h = int(hashlib.sha256(key.encode('utf-8')).hexdigest(), 16)
    s = ''
    for _ in range(7):
        h, r = divmod(h, 36)
        s += _B36[r]
    return s


def clip_id(dkey, sec):
    return 'au' + fingerprint(dkey, sec)


def is_app_clip(sec):
    """作ったクリップの印（id が 'au'＋7 文字・名前の頭が「自動」）。中身が直されていても True"""
    i = str(sec.get('id') or '')
    return i.startswith('au') and len(i) == 9 and str(sec.get('label') or '').startswith(APP_LABEL)


def note_clips(st):
    return [s for s in st.get('sections') or [] if s.get('lk') != 'l' and s.get('kind') != 'null']


def classify(proj, dkey, as_written=False):
    """作り直す前のクリップの分類 → ([(クリップ, 状態)], 新しい形式か, 作ったクリップのレーン or None)。状態:
    app＝作ったまま（作り直す）・fixed＝名前に「固定」・edited＝作ったが中身が変わった（手で直した・動かした・分けた前半）・
    user＝利用者のクリップ（NLM が付けた id・名前を付け直した物も）・legacy＝前の形式（id がでたらめ）で直されたか分からない。
    as_written＝ファイル全体がこちらで書いたまま（手元の指紋が一致）なら、前の形式でも作ったまま"""
    secs = note_clips(proj['difficulties'][dkey])
    new_fmt = any(is_app_clip(s) and s['id'] == clip_id(dkey, s) for s in secs)
    out, lanes = [], {}
    for s in secs:
        if not is_app_clip(s):
            st = 'user'
        else:
            lanes[s.get('track') or 0] = lanes.get(s.get('track') or 0, 0) + 1
            if KEEP_WORD in str(s.get('label') or ''):
                st = 'fixed'
            elif s['id'] == clip_id(dkey, s) or (as_written and not new_fmt):   # 手元の指紋で見るのは前の形式の時だけ
                st = 'app'   # （新しい形式で手元の指紋に頼ると、前の作り直しで残した「手で直した」クリップを次の作り直しで入れ替えてしまう）
            else:
                st = 'edited' if new_fmt else 'legacy'
        out.append((s, st))
    lane = max(lanes, key=lambda k: lanes[k]) if lanes else None
    return out, new_fmt, lane


def coverage_holes(proj, dkey, track, end):
    """そのレーンでクリップの無い時間（0〜end）→ [(拍の始まり, 終わり)]。作ったクリップは曲の頭から終わりまで隙間なく置くので、
    隙間＝NLM で消した所"""
    rs = sorted((s.get('beat') or 0, (s.get('beat') or 0) + (s.get('len') or 0)) for s in note_clips(proj['difficulties'][dkey])
                if (s.get('track') or 0) == track)
    out, at = [], 0.0
    for a, b in rs:
        if a > at + 1e-6:
            out.append((at, min(a, end)))
        at = max(at, b)
        if at >= end:
            break
    if at < end - 1e-6:
        out.append((at, end))
    return [(a, b) for a, b in out if b - a > 1e-6]


def remove_clips(proj, dkey, clips):
    """クリップと、そのクリップから NLM が作ったフラットの物（同じレーン・クリップの範囲）を消す"""
    st = proj['difficulties'][dkey]
    ids = {s.get('id') for s in clips}
    rng = [(s.get('track') or 0, s.get('beat') or 0, (s.get('beat') or 0) + (s.get('len') or 0)) for s in clips]
    st['sections'] = [s for s in st.get('sections') or [] if not (s.get('id') in ids and s.get('lk') != 'l')]
    for key in FLAT_N:
        fi = len(_enc_fields(key))
        if st.get(key):
            st[key] = [a for a in st[key] if not (isinstance(a, list) and len(a) > fi and any(
                (a[fi] or 0) == tr and b0 - 1e-9 <= a[0] < b1 - 1e-9 for tr, b0, b1 in rng))]


def clear_notes(proj, dkey):
    """難易度のノーツ系を全部消す（ノーツのレーンのクリップと、フラットの notes・bombs・walls・arcs・chains）。ライトは残す。

    作り直した譜面と同じ難易度に元の譜面を残さないため。ミュートは NLM の 3D の表示で隠れるだけで、左上の窓・重なりの判定・
    左右の振りの続きの判定には入ってしまう。kind が 'null' のクリップは触らない。戻り値: 消したクリップの数。
    """
    st = proj['difficulties'][dkey]
    secs = st.get('sections') or []
    st['sections'] = [s for s in secs if s.get('lk') == 'l' or s.get('kind') == 'null']
    for key in FLAT_N:
        if key in st:
            st[key] = []
    return len(secs) - len(st['sections'])


def _add_clip(st, dkey, cl, track):
    """クリップ（{'beat','len','label','colHex','notes':[絶対拍], 'extra'}）を作って難易度に足す（フラットにも同じ物）。id は中身の指紋"""
    b0, L = cl['beat'], cl['len']
    rel = [[_r(nt['beat'] - b0), nt['x'], nt['y'], nt['c'], nt['d'], None] for nt in cl['notes'] if b0 - 1e-9 <= nt['beat'] < b0 + L - 1e-9]
    content = {'notes': rel} if rel else {}
    st.setdefault('notes', []).extend([[_r(nt['beat']), nt['x'], nt['y'], nt['c'], nt['d'], track]
                                       for nt in cl['notes'] if b0 - 1e-9 <= nt['beat'] < b0 + L - 1e-9])
    for key, items in (cl.get('extra') or {}).items():
        fi = len(_enc_fields(key))
        for t in items:
            if not (b0 - 1e-9 <= t[0] < b0 + L - 1e-9):
                continue
            r_ = list(t)
            for i in BEAT_IDX[key]:
                if i < len(r_) and r_[i] is not None:
                    r_[i] = _r(r_[i] - b0)
            f_ = list(t) + [None] * max(0, fi + 1 - len(t))
            f_[fi] = track
            if len(r_) > fi:
                r_[fi] = None
            content.setdefault(key, []).append(r_)
            st.setdefault(key, []).append(f_)
    for key in content:
        content[key].sort(key=lambda t: t[0])
    sec = {'id': '', 'beat': _r(b0), 'track': track, 'lk': 'n', 'len': _r(L), 'label': cl.get('label') or APP_LABEL,
           'col': 0, 'colHex': cl.get('colHex'), 'kind': 'sheet', 'content': content}
    sec['id'] = clip_id(dkey, sec)
    st.setdefault('sections', []).append(sec)
    return sec


def put_clips(proj, dkey, clips, track):
    """決まったレーン（作り直す時の作ったクリップのレーン）にクリップを入れる。レーンは足さない・ずらさない"""
    st = proj['difficulties'][dkey]
    for cl in clips:
        _add_clip(st, dkey, cl, track)
    for key in FLAT_N:
        if st.get(key):
            st[key].sort(key=lambda a: a[0])


def _top_lane_used(proj):
    for st in proj['difficulties'].values():
        if any(s.get('lk') != 'l' and (s.get('track') or 0) == 0 for s in st.get('sections') or []):
            return True
        for key in FLAT_N:
            fi = len(_enc_fields(key))
            if any(isinstance(a, list) and len(a) > fi and (a[fi] or 0) == 0 for a in st.get(key) or []):
                return True
    return False


def put_note_lane(proj, clips_by_diff, *, seed=0):   # seed は前の形式（でたらめの id）の名残＝使わない
    """一番上のノーツのレーンにクリップを入れる。一番上のレーンが全難易度で空ならそのまま使い、空でなければ
    一番上にレーンを1本足す（全難易度の既存のノーツ系を1段ずらす）。

    clips_by_diff: {難易度のキー: [{'beat','len','label','colHex','notes':[{beat(絶対),x,y,c,d}], 'extra':{種類: [絶対拍のタプル]}}]}
    extra（任意）は保存形式のタプル（items_before の戻り値）。クリップの範囲に頭がある物をそのまま入れる（人が直した所を残す時）。
    戻り値: 入れたレーンの内部の番号（常に 0）。
    """
    n = int(proj.get('notesLanes') or 1)
    if _top_lane_used(proj):
        if n + 1 > LANE_MAX:
            raise ValueError(f'ノーツのレーンが上限（{LANE_MAX}）')
        for st in proj['difficulties'].values():   # 既存のノーツ系を1段下へ（内部の番号 +1）
            for s in st.get('sections') or []:
                if s.get('lk') != 'l':
                    s['track'] = (s.get('track') or 0) + 1
            for key in FLAT_N:
                for a in st.get(key) or []:
                    fi = len(_enc_fields(key))
                    if isinstance(a, list) and len(a) > fi:
                        a[fi] = (a[fi] or 0) + 1
        ls = proj.setdefault('laneStates', {'mute': [], 'solo': [], 'lock': []})
        for k in ('mute', 'solo', 'lock'):
            ls[k] = [(f'n{int(v[1:]) + 1}' if v[:1] == 'n' else v) for v in ls.get(k) or []]
        if 'editOnly' in ls and ls['editOnly'] is not None:
            ls['editOnly'] += 1
        proj['notesLanes'] = n + 1
    for dkey, clips in clips_by_diff.items():
        put_clips(proj, dkey, clips, 0)
    return 0


def _enc_fields(key):
    return {'notes': NOTE_F, 'bombs': ['beat', 'x', 'y'], 'walls': ['beat', 'x', 'y', 'dur', 'w', 'h'],
            'arcs': ['b', 'c', 'x', 'y', 'd', 'mu', 'tb', 'tx', 'ty', 'tc', 'tmu', 'm'],
            'chains': ['b', 'c', 'x', 'y', 'd', 'tb', 'tx', 'ty', 'sc', 's']}[key]


def _r(v):
    v = round(float(v), 6)
    return int(v) if v == int(v) else v
