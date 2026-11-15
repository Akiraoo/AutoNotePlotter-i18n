"""Beat Saber（CustomLevels）へ直接書き出す（NLM の書き出しの計算を写した部品・GPLv3）。

NLM（Non-Linear Mapper Oz-Co2版・https://github.com/Oz-Co-two/nlm-oz-co2 ・GPLv3）の書き出し（editor-app.js の exportMap）と
同じ物を、NLM を動かさずに作る。写した元（読むだけ・関数の名前はコメントに書く）:
- NLM のコミット `8b378d096036a4d77f4f31773f83389ce180f159`（2026-11-03 13:10:33 +0900）
  - js/runtime/editor-app.js: exportMap・collectExportDiffs・buildDiffJsonFor・buildExportInfo・njsOffExport・getSongFileLike・
    readEggMark／writeEggMark・msegs・segEndBeat・musicPieces・eggPieces・eggOutSecOf・getLeadInMs・getSongGainDb・
    applyProject・loadDiff・decArr／decSec・flatFromSections・oldAdoptLoose（v2）・absorbChainCompanionNotes・
    defaultInfoGraph・defInfoData・sanitizeInfoGraph・migratePrevNode・connectedNodeId・applyInfoGraph・sanitizeFolderName・
    connectedCoverFit（補正の要る画像は写していない）
  - js/media/cover-fit.js: coverNeedsFix（補正が要るかの判定だけ）
  - serve.py の _convert_to_ogg（/__convert/toOgg・ffmpeg の引数）・app.py の read_song_file（音源の名前・mtime）
  NLM の版が上がったら tools/nlm_export_check.py で NLM の書き出しと比べ、違えば写し直す。

決まり（NLM と同じ）:
- 「開いてすぐ書き出した」時と同じ: 開いていた難易度（current）はクリップの中身から作り直した物、ほかの難易度は保存された
  フラットの配列（NLM はその難易度を開くまでフラットのまま書き出す）。両方が合わない・クリップの外の物がある等、NLM の答えが
  開き方で変わる物は書かずに BsExportError（「NLM で書き出して」）。
- NLM は書き出す印（設定のノードの diffs）に関係なく「中身のある Standard の難易度」を全部書き出す（印は 1 つ以上選んだかの
  確かめだけ）。ここでは約束どおり印（または diffs の指定）の難易度だけを書く。diffs='all' で NLM と同じ全部。
- Info.dat は JSON.stringify(info, null, 2)・難易度は JSON.stringify(json)（数の書き方も JS と同じ＝js_dumps）。
- song.egg は無音追加・Music の配置（切り貼り）・音量の補正を焼き込む（serve.py と同じ）。soundfile で読める音源は soundfile で
  OGG Vorbis（品質 0.5＝ffmpeg の -q:a 5）に、読めない形式は ffmpeg（PATH・NLM と同じ引数）。.nlm-egg.json の印も NLM と同じ形
  ＝音源・無音追加・配置・音量が前と同じなら変換しない（NLM で書き出した後でも、こちらで書き出した後でも）。

写しと違う所（NLM の書き出しには無い・2026-11-09）:
- **ANP の印**: Info.dat の `_customData._editors`（ChroMapper・MMA2・Beat Sage と同じ慣例＝`_lastEditedBy` とエディタ名をキーに
  `{"version": …}`）に ANP_EDITOR を入れる（put_mark）。型のライブラリ（tools/library_build/build_db.py）が自分で書き出した譜面を
  人の譜面と見分けるため（anp_mark）。Beat Saber・SongCore は `_editors` を使わない（_customData に足すだけ）。BeatSaver の上げも
  ほかのエディタ名のキーで通っている（手元の Beat Sage の譜面はこの形で上がっている・ANP の名前で上げて確かめてはいない）。
  印の分だけ BeatSaver の hash は NLM の書き出しと違う。
  NLM の書き出しと比べる時は印を入れない（build(mark=False)・tools/nlm_export_check.py）。
"""
import base64
import functools
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from . import diffs as D
from . import nlmf
from . import sfread

NLM_COMMIT = '8b378d096036a4d77f4f31773f83389ce180f159'
OUT_DIFFS = ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus']   # editor-app.js の OUT_DIFFS
DIFF_RANK = {'Easy': 1, 'Normal': 3, 'Hard': 5, 'Expert': 7, 'ExpertPlus': 9}   # _DIFF_RANK
DIFF_NJS = {'Easy': 10, 'Normal': 10, 'Hard': 10, 'Expert': 12, 'ExpertPlus': 16}   # _DIFF_NJS
PREV_DEF = {'start': 12, 'dur': 10}
INFO_NODE_TYPES = ('meta', 'set', 'cover', 'prev')
CHAIN_RAW_KEYS = ('cpm', 'la', 's2d', 'fcp', 'csqu', 'td')   # notes/chain-bezier.js（エディタ専用・書き出さない）
ENC = {'notes': ('note', ['beat', 'x', 'y', 'c', 'd']), 'bombs': ('bomb', ['beat', 'x', 'y']),
       'walls': ('wall', ['beat', 'x', 'y', 'dur', 'w', 'h']),
       'arcs': ('arc', ['b', 'c', 'x', 'y', 'd', 'mu', 'tb', 'tx', 'ty', 'tc', 'tmu', 'm']),
       'chains': ('chain', ['b', 'c', 'x', 'y', 'd', 'tb', 'tx', 'ty', 'sc', 's']),
       'lights': (None, ['beat', 'et', 'i', 'f'])}   # _ENC
FLAT_OF = {'notes': 'notes', 'bombs': 'bombs', 'walls': 'walls', 'arcs': 'arcs', 'chains': 'chains', 'lights': 'lightEvents'}
GRP = {'notes': 'n', 'bombs': 'n', 'walls': 'n', 'arcs': 'n', 'chains': 'n', 'lights': 'l'}
LCT = {'notes': ('beat',), 'bombs': ('beat',), 'walls': ('beat',), 'arcs': ('b', 'tb'), 'chains': ('b', 'tb'), 'lights': ('beat',)}
SOUNDFILE_EXTS = ('.flac', '.wav', '.mp3', '.ogg', '.aiff', '.aif')
EGG_QUALITY = 0.5   # ffmpeg の libvorbis -q:a 5（品質 0.5）＝libsndfile の圧縮の強さ 0.5（品質＝1−強さ）
BLOCK = 1 << 16
NLM_HINT = 'この譜面は NLM で書き出してください'
ANP_EDITOR = 'Auto Note Plotter'   # Info.dat の印のエディタ名（_customData._editors のキー・_lastEditedBy）＝変えない（前の書き出しを見分けられなくなる）


class BsExportError(Exception):
    """書き出せない（写していない機能・判断できない物・足りない物）。文は使う人に見せる日本語"""


class BsExportCancelled(BsExportError):
    pass


def _nlm(msg):
    return BsExportError(f'{NLM_HINT}: {msg}')


# ---- JS と同じ値の扱い・JSON の書き方 ----

class _Undef:
    def __repr__(self):
        return 'undefined'


UNDEF = _Undef()   # JS の undefined（JSON.stringify は物の中では項目ごと書かない・配列の中は null）


def _nn(v, d):
    """JS の v ?? d"""
    return d if v is None or v is UNDEF else v


def js_truthy(v):
    if v is None or v is UNDEF or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ''
    return True


def _or(*vs):
    """JS の a || b || c"""
    for v in vs[:-1]:
        if js_truthy(v):
            return v
    return vs[-1]


_NUM_RE = re.compile(r'^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?|Infinity)$')


def js_tonum(v):
    """JS の +v（単項のプラス）"""
    if v is UNDEF:
        return float('nan')
    if v is None or v is False:
        return 0
    if v is True:
        return 1
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == '':
            return 0
        if _NUM_RE.match(s):
            return float(s.replace('Infinity', 'inf'))
        return float('nan')
    return float('nan')


def _isfinite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def numv(v, d):
    """buildExportInfo の numv: Number.isFinite(+v) ? +v : d"""
    x = js_tonum(v)
    return x if _isfinite(x) else d


def js_round(x):
    """JS の Math.round（.5 は大きい方へ）"""
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r


def js_num(x):
    """JS の Number.prototype.toString と同じ数の書き方（JSON.stringify と同じ。NaN・無限は 'null'）"""
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if isinstance(x, int):
        if abs(x) < 2 ** 53:
            return str(x)
        x = float(x)
    if not math.isfinite(x):
        return 'null'
    if x == 0:
        return '0'
    s = repr(abs(x))   # 一番短い桁（JS と同じ桁になる）
    sign = '-' if x < 0 else ''
    m, _, e = s.partition('e')
    exp = int(e) if e else 0
    ip, _, fp = m.partition('.')
    if fp == '0':
        fp = ''
    digits = (ip + fp).lstrip('0')
    lead0 = len(ip + fp) - len((ip + fp).lstrip('0'))
    n = len(ip) + exp - lead0          # 値 = 0.d1d2… × 10^n
    digits = digits.rstrip('0') or '0'
    k = len(digits)
    if k <= n <= 21:
        out = digits + '0' * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + '.' + digits[n:]
    elif -6 < n <= 0:
        out = '0.' + '0' * (-n) + digits
    else:
        e2 = n - 1
        es = ('+' if e2 >= 0 else '-') + str(abs(e2))
        out = digits + 'e' + es if k == 1 else digits[0] + '.' + digits[1:] + 'e' + es
    return sign + out


_LONE = re.compile(r'[\ud800-\udfff]')


def _js_str(s):
    t = json.dumps(s, ensure_ascii=False)
    return _LONE.sub(lambda m: '\\u%04x' % ord(m.group(0)), t)   # 対になっていないサロゲートは JS も \udxxx で書く


def _is_index(k):
    return k.isdigit() and (k == '0' or k[0] != '0') and int(k) < 2 ** 32 - 1


def _keys(d):
    """JS の物の項目の順: 配列の番号の形の名前（'0'・'12'）が先に小さい順・ほかは入れた順"""
    ks = list(d.keys())
    idx = sorted((k for k in ks if isinstance(k, str) and _is_index(k)), key=int)
    return idx + [k for k in ks if not (isinstance(k, str) and _is_index(k))]


def js_dumps(v, indent=None):
    """JSON.stringify(v) / JSON.stringify(v, null, indent) と同じ文字列"""
    def enc(v, lv):
        if v is None or v is UNDEF:
            return 'null'
        if isinstance(v, (bool, int, float)):
            return js_num(v)
        if isinstance(v, str):
            return _js_str(v)
        if isinstance(v, dict):
            items = [(k, v[k]) for k in _keys(v) if v[k] is not UNDEF]
            if not items:
                return '{}'
            if indent is None:
                return '{' + ','.join(_js_str(str(k)) + ':' + enc(x, lv + 1) for k, x in items) + '}'
            pad, pad0 = '\n' + ' ' * (indent * (lv + 1)), '\n' + ' ' * (indent * lv)
            return '{' + ','.join(pad + _js_str(str(k)) + ': ' + enc(x, lv + 1) for k, x in items) + pad0 + '}'
        if isinstance(v, (list, tuple)):
            if not v:
                return '[]'
            if indent is None:
                return '[' + ','.join(enc(x, lv + 1) for x in v) + ']'
            pad, pad0 = '\n' + ' ' * (indent * (lv + 1)), '\n' + ' ' * (indent * lv)
            return '[' + ','.join(pad + enc(x, lv + 1) for x in v) + pad0 + ']'
        raise TypeError(f'JSON にできない値: {type(v)}')
    return enc(v, 0)


def _jstr(v):
    """String(v)（数・真偽・null・undefined）"""
    if v is None:
        return 'null'
    if v is UNDEF:
        return 'undefined'
    if isinstance(v, (bool, int, float)):
        return js_num(v) if not (isinstance(v, float) and not math.isfinite(v)) else ('NaN' if v != v else ('Infinity' if v > 0 else '-Infinity'))
    return str(v)


def _add(a, b):
    """JS の a+b（a が無い＝undefined は NaN＝書くと null）"""
    if a is None or a is UNDEF or b is None or b is UNDEF:
        return float('nan')
    return a + b


def _cmp_by(getter):
    def cmp(p, q):
        a, b = getter(p), getter(q)
        try:
            d = js_tonum(a) - js_tonum(b)
        except TypeError:
            return 0
        return 0 if d != d or d == 0 else (-1 if d < 0 else 1)
    return functools.cmp_to_key(cmp)


def _sort_by(arr, getter):
    """Array.prototype.sort((p,q)=>getter(p)-getter(q))（安定・NaN は同じ扱い）"""
    return sorted(arr, key=_cmp_by(getter))


# ---- 開いた時の中身（applyProject・loadDiff・decArr・flatFromSections） ----

def _dec(key, o, bad):
    """decArr の 1 つ: タプル → {項目…, _tr, raw}（null の項目は持たない）"""
    if isinstance(o, dict):   # v1（物の形）はそのまま
        it = dict(o)
        it.setdefault('raw', None)
        return it
    if not isinstance(o, list):
        bad.append('中身の形が違う物')
        return None
    kind, fields = ENC[key]
    it = {'kind': kind} if kind else {}
    for i, f in enumerate(fields):
        if i < len(o) and o[i] is not None:
            it[f] = o[i]
    n = len(fields)
    if n < len(o) and o[n] is not None:
        it['_tr'] = o[n]
    raw = o[n + 1] if n + 1 < len(o) else None
    if js_truthy(raw) and not isinstance(raw, dict):
        bad.append('標準外の項目の形が違う物')
        raw = None
    it['raw'] = raw if js_truthy(raw) else None
    return it


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def flat_from_sections(secs):
    """flatFromSections: クリップ → フラット（絶対拍・クリップの順・見えている物＝0 ≤ 拍 < 長さ）。ライトだけ拍の順に並べ直す"""
    f = {'notes': [], 'bombs': [], 'walls': [], 'arcs': [], 'chains': [], 'lightEvents': []}
    for s in secs or []:
        if s.get('kind') == 'null':
            continue
        c = s.get('content') or {}
        L = _or(s.get('len'), 4)
        off = _or(s.get('beat'), 0)
        for key in ('notes', 'bombs', 'walls', 'lights'):
            for n in c.get(key) or []:
                b = n.get('beat')
                if _num(b) and b >= 0 and b < L:
                    f[FLAT_OF[key]].append({**n, 'beat': b + off})
        for key in ('arcs', 'chains'):
            for a in c.get(key) or []:
                b = a.get('b')
                if _num(b) and b >= 0 and b < L:
                    f[key].append({**a, 'b': b + off, 'tb': _add(a.get('tb', UNDEF), off)})
    f['lightEvents'] = _sort_by(f['lightEvents'], lambda e: e.get('beat', UNDEF))
    return f


def _has_active(secs):
    return any(s.get('kind') != 'null' for s in secs or [])


def _okey(key, o):
    """_oldKey と同じ考え（同じ物か・絶対拍で比べる）。数は小数 4 桁"""
    fields = ENC[key][1]

    def one(v):
        if _num(v):
            return '%.4f' % v
        return '' if v is None or v is UNDEF else str(v)
    return key + '|' + ','.join(one(o.get(f, UNDEF)) for f in fields)


def _flat_counter(flat):
    c = Counter()
    for key, fk in FLAT_OF.items():
        for o in flat.get(fk) or []:
            c[_okey(key, o)] += 1
    return c


def _loose(secs, flat):
    """oldAdoptLoose（v2）: フラットにあってクリップに無く、どのクリップの範囲にも無い物の数（NLM は開く時に新しいクリップへ入れる）"""
    have = _flat_counter(flat_from_sections(secs))
    n = 0
    for key, fk in FLAT_OF.items():
        by = {}
        for o in flat.get(fk) or []:
            by.setdefault(_okey(key, o), []).append(o)
        for k, arr in by.items():
            nf = max(0, len(arr) - have.get(k, 0))
            for o in arr[len(arr) - nf:] if nf else []:
                b = js_tonum(o.get(LCT[key][0], UNDEF))
                b = b if _isfinite(b) else 0
                if b < 0:
                    continue
                lk = GRP[key]
                inside = any(s.get('kind') != 'null' and ('l' if s.get('lk') == 'l' else 'n') == lk
                             and b >= _or(s.get('beat'), 0) - 1e-6 and b < _or(s.get('beat'), 0) + _or(s.get('len'), 4) - 1e-6
                             for s in secs or [])
                if not inside:
                    n += 1
    return n


def _absorb(notes, chains):
    """absorbChainCompanionNotes: チェーンの頭・尾と重なる隠しノーツ（古い形）を消す → 消した数"""
    if not chains or not notes:
        return 0

    def comp(n):
        if n.get('kind') == 'bomb':
            return False
        for ch in chains:
            if (abs(_or(ch.get('b'), 0) - js_tonum(n.get('beat', UNDEF))) < 1e-4 and ch.get('x') == n.get('x') and ch.get('y') == n.get('y')
                    and ch.get('c') == n.get('c')):
                return True
            if (abs(_or(ch.get('tb'), 0) - js_tonum(n.get('beat', UNDEF))) < 1e-4 and ch.get('tx') == n.get('x') and ch.get('ty') == n.get('y')
                    and ch.get('c') == n.get('c')):
                return True
        return False
    keep = [n for n in notes if not comp(n)]
    k = len(notes) - len(keep)
    notes[:] = keep
    return k


def _dup_key(s):
    """loadDiff の重複クリップの見分け（label・beat・track・len・_diffName・lk）"""
    def j(v):
        return '' if v is None or v is UNDEF else _jstr(v)
    return '|'.join(j(x) for x in (s.get('label'), _or(s.get('beat'), 0), _or(s.get('track'), 0), _or(s.get('len'), 4),
                                   _or(s.get('_diffName'), ''), _or(s.get('lk'), 'n')))


def _current_key(proj):
    """開いた時の難易度（applyProject: プルダウンを info の難易度の一覧か difficulties から作り、current に合う物・無ければ先頭）"""
    ds = proj.get('difficulties') or {}
    sets = ((proj.get('info') or {}).get('_difficultyBeatmapSets')) or []
    std = next((x for x in sets if isinstance(x, dict) and x.get('_beatmapCharacteristicName') == 'Standard'), sets[0] if sets else None)
    opts = [b.get('_beatmapFilename') for b in ((std or {}).get('_difficultyBeatmaps') or []) if isinstance(b, dict)]
    if not opts:
        opts = [(v or {}).get('name') or k for k, v in ds.items()]
    cur = proj.get('current')
    pick = next((o for o in opts if isinstance(o, str) and isinstance(cur, str) and o.lower() == cur.lower()), opts[0] if opts else None)
    return pick.lower() if isinstance(pick, str) else None


def open_diffs(proj):
    """全部の難易度の「開いてすぐ書き出す」時の中身 → ({小文字のキー: {name, v3, base, flat, sections}}, 開いた難易度のキー,
    書けない理由 [(難易度のキー, 文)], 注意)"""
    bad, warn = [], []
    cur = _current_key(proj)
    out = {}
    for k, d in (proj.get('difficulties') or {}).items():
        if not isinstance(d, dict):
            bad.append((k, f'難易度「{k}」の形が違う'))
            continue
        b0 = []
        secs = []
        for s in d.get('sections') or []:
            if not isinstance(s, dict):
                b0.append('クリップの形が違う物')
                continue
            c = s.get('content') or {}
            content = {key: [x for x in (_dec(key, a, b0) for a in (c.get(key) or [])) if x is not None] for key in ENC}
            secs.append({**s, 'content': content})
        flat = {fk: [x for x in (_dec(key, a, b0) for a in (d.get(fk) or [])) if x is not None] for key, fk in FLAT_OF.items()}
        name = d.get('name') or k
        if b0:
            bad.append((k, f'{name}: ' + '・'.join(sorted(set(b0)))))
        if _has_active(secs):
            if _loose(secs, flat):
                bad.append((k, f'{name}: クリップの外にノーツ等がある（NLM で開いて保存し直すと直る）'))
        if k == cur:
            st_secs = secs
            seen, uniq = set(), []
            for s in secs:
                kk = _dup_key(s)
                if kk in seen:
                    continue
                seen.add(kk)
                uniq.append(s)
            if len(uniq) != len(secs):
                warn.append(f'{name}: 重なった同じクリップを 1 つにした（NLM が開く時と同じ）')
                st_secs = uniq
            if _has_active(st_secs):
                f = flat_from_sections(st_secs)
                okc = lambda o: ','.join('%.4f' % js_tonum(o.get(x, 0) or 0) if x in ('b', 'tb') else str(o.get(x)) for x in ('b', 'x', 'y', 'c', 'tb', 'tx', 'ty'))
                hc, ha = {okc(o) for o in f['chains']}, {okc(o) for o in f['arcs']}
                if any(okc(o) not in hc for o in flat['chains']) or any(okc(o) not in ha for o in flat['arcs']):
                    bad.append((k, f'{name}: クリップに入っていないチェーン・アークがある（古い形）'))
            else:
                f = flat
            if _absorb(f['notes'], f['chains']):
                warn.append(f'{name}: チェーンと重なる隠しノーツ（古い形）を除いた（NLM が開く時と同じ）')
        else:
            f = flat
            if _has_active(secs) and _flat_counter(flat) != _flat_counter(flat_from_sections(secs)):
                bad.append((k, f'{name}: 保存されたノーツの一覧とクリップの中身が合わない（NLM でこの難易度を開いて保存し直すと直る）'))
            nb = list(f['notes'])
            if _absorb(nb, f['chains']):
                bad.append((k, f'{name}: チェーンと重なる隠しノーツ（古い形）がある（NLM でこの難易度を開いて保存し直すと直る）'))
        out[k] = {'name': name, 'v3': bool(d.get('v3')), 'base': d.get('base'), 'flat': f, 'sections': secs}
    return out, cur, bad, warn


# ---- テンポ（beatToTimeTM・timeToBeatTM） ----

class Tempo:
    def __init__(self, proj):
        bpm = 120
        info = proj.get('info') if isinstance(proj.get('info'), dict) else {}
        if js_tonum(info.get('_beatsPerMinute', UNDEF)) > 0:
            bpm = js_tonum(info['_beatsPerMinute'])
        if js_tonum(proj.get('bpm', UNDEF)) > 0:
            bpm = js_tonum(proj['bpm'])
        self.bpm = bpm
        tp = proj.get('tempoParts') if isinstance(proj.get('tempoParts'), list) else []
        parts = [{'beat': js_tonum(p.get('beat', UNDEF)), 'bpm': js_tonum(p.get('bpm', UNDEF))} for p in tp
                 if isinstance(p, dict) and _isfinite(js_tonum(p.get('beat', UNDEF))) and js_tonum(p.get('bpm', UNDEF)) > 0]
        self.parts = _sort_by(parts, lambda p: p['beat'])

    def sec(self, b):
        bb, bpm, tt = 0, self.bpm, 0
        for p in self.parts:
            if p['beat'] >= b:
                break
            tt += (p['beat'] - bb) * 60 / bpm
            bb, bpm = p['beat'], p['bpm']
        return tt + (b - bb) * 60 / bpm

    def beat(self, tm):
        bb, bpm, tt = 0, self.bpm, 0
        for p in self.parts:
            seg = (p['beat'] - bb) * 60 / bpm
            if tt + seg > tm:
                break
            tt += seg
            bb, bpm = p['beat'], p['bpm']
        return bb + (tm - tt) * bpm / 60


# ---- 音源・Music の配置（getSongOff・getLeadInMs・msegs・musicPieces・eggPieces・eggOutSecOf） ----

def song_node(proj):
    g = proj.get('graph') if isinstance(proj.get('graph'), dict) else {}
    s = g.get('song')
    return s if isinstance(s, dict) else None


def song_off(sn):
    o = (sn or {}).get('offset')
    return o if _isfinite(o) else 0


def lead_in_ms(sn):
    o = (sn or {}).get('offset')
    return js_round(-o * 1000) if _isfinite(o) and o < 0 else 0


def gain_db(sn):
    g = js_tonum(_or((sn or {}).get('gainDb'), 0)) if sn else 0
    return g if _isfinite(g) else 0


def msegs(proj, dur):
    """Music の区間 [{beat, off, dur}]。分けていなければ全体を 1 つ（音源が無ければ空）"""
    ms = proj.get('musicSegs')
    if ms:
        if not isinstance(ms, list) or not all(isinstance(s, dict) and all(_num(s.get(k)) for k in ('beat', 'off', 'dur')) for s in ms):
            raise _nlm('Music の配置（分けた区間）の形が違う')
        return ms
    if dur is None:
        return []
    mb = js_tonum(proj.get('musicBeat', UNDEF))
    return [{'beat': mb if js_truthy(mb) else 0, 'off': 0, 'dur': max(0, dur - song_off(song_node(proj)))}]


def music_pieces(proj, tempo, dur):
    """eggPieces: [[元の音源の開始秒, 終了秒, 書き出し先の開始秒]]（書き出し先の順）"""
    if dur is None:
        return []
    off0 = song_off(song_node(proj))
    out = []
    for sg in msegs(proj, dur):
        s, d, at = off0 + sg['off'], sg['dur'], tempo.sec(sg['beat'])
        if s < 0:
            at -= s
            d += s
            s = 0
        e = min(dur, s + d)
        if e - s > 0.001:
            out.append([s, e, at])
    return _sort_by(out, lambda p: p[2])


def egg_out_sec(P, src, lead_ms):
    """eggOutSecOf: 元の音源の秒 → 書き出した song.egg の秒"""
    if not P:
        return src + lead_ms / 1000
    for s, e, at in P:
        if src >= s - 1e-6 and src < e:
            return at + (src - s)
    nx = _sort_by([q for q in P if q[0] > src], lambda q: q[0])
    return nx[0][2] if nx else P[0][2]


def egg_plan(proj, tempo, dur):
    """書き出す song.egg の作り方（exportMap）→ {pieces, lead_in_ms, segs, gain_db}"""
    sn = song_node(proj)
    P = music_pieces(proj, tempo, dur)
    whole = len(P) == 1 and P[0][0] < 1e-6 and dur is not None and abs(P[0][1] - dur) < 1e-3
    lead = lead_in_ms(sn) if not P else (js_round(P[0][2] * 1000) if whole else 0)
    segs = [[js_round(v * 1000) / 1000 for v in q] for q in P] if (P and not whole) else None
    return {'pieces': P, 'lead_in_ms': lead, 'segs': segs, 'gain_db': gain_db(sn)}


def audio_path(proj):
    sn = song_node(proj)
    if not sn or proj.get('songDeleted'):
        return None
    p = sn.get('nativePath')
    return p if isinstance(p, str) and p else None


_FRAMES = {}   # (場所, 大きさ, 更新時刻) → (サンプル数, サンプリング周波数)


def audio_frames(path):
    """soundfile で読める音源の本当のサンプル数とサンプリング周波数（読めなければ None）。MP3 は見出しの長さが見積もり
    （Joy to the love で 26031 サンプル長かった）なので最後まで読んで数える（ffmpeg と同じ数になる・4 分で 0.2 秒）。
    終わりのフレームが切れた MP3 は読めた所まで（automap/sfread・ffmpeg より切れた 1 フレーム分短い）"""
    import soundfile as sf
    st = os.stat(path)
    k = (str(path), st.st_size, st.st_mtime_ns)
    if k not in _FRAMES:
        with sf.SoundFile(str(path)) as f:
            n, sr = f.frames, f.samplerate
            mp3 = f.format == 'MPEG' or Path(path).suffix.lower() == '.mp3'
        if mp3:
            n = sfread.frames(path, BLOCK)[0]
        _FRAMES[k] = (n, sr)
    return _FRAMES[k]


def _sf_readable(path):
    try:
        import soundfile as sf
        sf.info(str(path))
        return True
    except Exception:   # noqa: BLE001
        return False


def audio_len(path):
    """音源の長さ（秒）・soundfile で読めるか。読めない形式は ffprobe（あれば）"""
    try:
        n, sr = audio_frames(path)
        if n > 0 and sr > 0:
            return n / sr, True
    except Exception:   # noqa: BLE001
        pass
    from .new_project import audio_info
    s = audio_info(path).get('seconds')
    return (float(s) if s else None), False


# ---- 曲の情報（defaultInfoGraph・sanitizeInfoGraph・migratePrevNode・connectedNodeId・applyInfoGraph） ----

def _def_data(t):
    if t == 'meta':
        return {'name': '', 'sub': '', 'artist': '', 'author': ''}
    if t == 'set':
        return {'red': 0xff274d, 'blue': 0x3092ff, 'lred': 0xff274d, 'lblue': 0x3092ff, 'lredB': 0xff6f9f, 'lblueB': 0x6fdcff, 'env': '', 'diffs': {}}
    if t == 'prev':
        return dict(PREV_DEF)
    return {'name': ''}


def _default_graph():
    return {'nodes': {'m1': {'t': 'meta', 'x': 24, 'y': 16, 'data': _def_data('meta')},
                      's1': {'t': 'set', 'x': 336, 'y': 16, 'data': _def_data('set')},
                      'c1': {'t': 'cover', 'x': 24, 'y': 206, 'data': _def_data('cover')},
                      'p1': {'t': 'prev', 'x': 336, 'y': 300, 'data': _def_data('prev')}}, 'nseq': 1,
            'outs': {'o1': {'x': 660, 'y': 100, 'folderName': '', 'outDirName': '', 'outDirPath': ''}}, 'activeOut': 'o1', 'oseq': 1,
            'edges': [{'s': 'm1', 'o': 'o1'}, {'s': 's1', 'o': 'o1'}, {'s': 'c1', 'o': 'o1'}, {'s': 'p1', 'o': 'o1'}],
            'cam': {'x': 0, 'y': 0, 's': 1, 'auto': 1}, 'prevMig': 1}


def info_graph(proj):
    """開いた時の INFO の図（写し・proj は変えない）"""
    pg = proj.get('infoGraph')
    ig = _default_graph()
    if isinstance(pg, dict):
        ig.update(json.loads(json.dumps(pg)))
    if not isinstance(ig.get('outs'), dict) or not ig['outs'] or not isinstance(ig.get('nodes'), dict):
        raise _nlm('曲の情報（INFO の図）が古い形')
    for nid in list(ig['nodes']):
        n = ig['nodes'][nid]
        if not isinstance(n, dict) or n.get('t') not in INFO_NODE_TYPES:
            del ig['nodes'][nid]
            continue
        n['data'] = {**_def_data(n['t']), **(n.get('data') if isinstance(n.get('data'), dict) else {})}
    ig['oseq'] = _or(ig.get('oseq'), len(ig['outs']))
    ig['nseq'] = _or(ig.get('nseq'), len(ig['nodes']))
    if not isinstance(ig.get('activeOut'), str) or ig['activeOut'] not in ig['outs']:
        ig['activeOut'] = next(iter(ig['outs']))
    eds = [e for e in (ig.get('edges') or []) if isinstance(e, dict) and e.get('s') in ig['nodes'] and e.get('o') in ig['outs']]
    seen, keep = set(), []
    for e in reversed(eds):   # 同じ物と「同じ書き出しに同じ種類が 2 本」は最後に繋いだ物だけ
        k, kt = f"{e['s']}>{e['o']}", f"{e['o']}|{ig['nodes'][e['s']]['t']}"
        if k in seen or kt in seen:
            continue
        seen.update((k, kt))
        keep.append(e)
    ig['edges'] = keep[::-1]
    if not (isinstance(pg, dict) and js_truthy(pg.get('prevMig'))):   # migratePrevNode
        ib = proj.get('info') if isinstance(proj.get('info'), dict) else {}

        def num(v, d):
            return js_tonum(v) if (v is not None and v is not UNDEF and v != '' and _isfinite(js_tonum(v))) else d
        pid = next((i for i, n in ig['nodes'].items() if n['t'] == 'prev'), None)
        if not pid:
            ig['nseq'] += 1
            pid = f"p{ig['nseq']}"
            ig['nodes'][pid] = {'t': 'prev', 'x': 24, 'y': 16, 'data': _def_data('prev')}
            for oid in ig['outs']:
                ig['edges'].append({'s': pid, 'o': oid})
        ig['nodes'][pid]['data'].update(start=num(ib.get('_previewStartTime', UNDEF), PREV_DEF['start']),
                                        dur=num(ib.get('_previewDuration', UNDEF), PREV_DEF['dur']))
    return ig


def connected(ig, t):
    """connectedNodeId: 今の書き出しに繋がったその種類のノード（最後に繋いだ物）"""
    for e in reversed(ig['edges']):
        if e['o'] == ig['activeOut'] and ig['nodes'].get(e['s'], {}).get('t') == t:
            return e['s']
    return None


def info_base(proj, ig):
    """applyInfoGraph の後の infoBase（曲名などは繋がったノードから）＋ 書き出す印・カバー・試聴のノード"""
    ib = dict(proj['info']) if isinstance(proj.get('info'), dict) else {}
    m = ig['nodes'].get(connected(ig, 'meta'))
    d = m['data'] if m else {}
    ib['_songName'] = _or(d.get('name'), '') if m else ''
    ib['_songSubName'] = _or(d.get('sub'), '') if m else ''
    ib['_songAuthorName'] = _or(d.get('artist'), '') if m else ''
    ib['_levelAuthorName'] = _or(d.get('author'), '') if m else ''
    s = ig['nodes'].get(connected(ig, 'set'))
    ib['_environmentName'] = _or(s['data'].get('env'), '') if s else ''
    marks = dict(s['data'].get('diffs') or {}) if s else {}
    p = ig['nodes'].get(connected(ig, 'prev'))
    ib['_previewStartTime'] = js_tonum(p['data'].get('start', UNDEF)) if p else PREV_DEF['start']
    ib['_previewDuration'] = js_tonum(p['data'].get('dur', UNDEF)) if p else PREV_DEF['dur']
    return ib, marks


# ---- カバー画像（exportMap のカバー・cover-fit.js の coverNeedsFix） ----

def image_size(data):
    """PNG・JPEG の寸法（幅, 高さ）。分からなければ None"""
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        return struct.unpack('>II', data[16:24])
    if data[:2] == b'\xff\xd8':
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            mk = data[i + 1]
            if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7 or mk == 0xFF:
                i += 1 if mk == 0xFF else 2
                continue
            ln = struct.unpack('>H', data[i + 2:i + 4])[0]
            if 0xC0 <= mk <= 0xCF and mk not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack('>HH', data[i + 5:i + 9])
                return w, h
            i += 2 + ln
    return None


def cover_needs_fix(w, h, name):
    return w != h or w < 256 or h < 256 or (bool(name) and not re.search(r'\.(png|jpe?g)$', name, re.I))


def cover_source(proj, ig):
    """書き出しに繋がったカバー画像 → {'name','data','path','fit'} か None。exe 版の NLM と同じく、ノードの実パスに画像があれば
    それ・無ければプロジェクトに入っている画像（coverData）"""
    cid = connected(ig, 'cover')
    n = ig['nodes'].get(cid) if cid else None
    if not n:
        return None
    d = n['data']
    path = d.get('nativePath') if isinstance(d.get('nativePath'), str) else None
    if path and os.path.isfile(path):
        try:
            data = Path(path).read_bytes()
            return {'name': os.path.basename(path), 'data': data, 'path': path, 'fit': d.get('fit'), 'id': cid}
        except OSError:
            pass
    u = (proj.get('coverData') or {}).get(cid)
    if isinstance(u, str) and ',' in u:
        try:
            data = base64.b64decode(u.split(',')[1])
        except ValueError:
            data = None
        if data:
            return {'name': _or(d.get('name'), 'cover'), 'data': data, 'path': None, 'fit': d.get('fit'), 'id': cid}
    return None


def cover_out_name(name):
    m = re.search(r'\.([^.]+)$', name or '')
    return 'cover.' + (m.group(1) if m else 'png').lower()


# ---- 難易度の .dat（buildDiffJsonFor） ----

def _rf(r, v3):
    if not js_truthy(r) or not isinstance(r, dict):
        return None
    o = None
    for k, v in r.items():
        if (str(k)[:1] == '_') != v3:
            if o is None:
                o = {}
            o[k] = v
    return o


def _g(o, k):
    return o.get(k, UNDEF)


def diff_json(st, tempo):
    """難易度の中身（open_diffs の 1 つ・切った後のフラット）→ 難易度の .dat の中身"""
    if not isinstance(st.get('base'), dict):
        raise _nlm(f'{st["name"]}: 難易度の土台（base）が無い')
    d = json.loads(json.dumps(st['base']))
    f = st['flat']
    mN, mB, mW, mA, mC, mL = f['notes'], f['bombs'], f['walls'], f['arcs'], f['chains'], f['lightEvents']
    sb = lambda p: _nn(_g(p, 'b'), _g(p, '_time'))
    if st['v3']:
        R3 = lambda o: _rf(o.get('raw'), True)
        heads = [{'a': 0, 'b': _g(c, 'b'), 'x': _g(c, 'x'), 'y': _g(c, 'y'), 'c': _g(c, 'c'),
                  'd': 0 if (_num(c.get('d')) and c.get('d') == 8) else _g(c, 'd')} for c in mC]
        d['colorNotes'] = _sort_by([{**(R3(n) or {'a': 0}), 'b': _g(n, 'beat'), 'x': _g(n, 'x'), 'y': _g(n, 'y'), 'c': _g(n, 'c'),
                                     'd': _g(n, 'd')} for n in mN] + heads, sb)
        d['bombNotes'] = _sort_by([{**(R3(n) or {}), 'b': _g(n, 'beat'), 'x': _g(n, 'x'), 'y': _g(n, 'y')} for n in mB], sb)
        d['obstacles'] = _sort_by([{**(R3(o) or {}), 'b': _g(o, 'beat'), 'x': _g(o, 'x'), 'y': _g(o, 'y'), 'd': _g(o, 'dur'),
                                    'w': _g(o, 'w'), 'h': _g(o, 'h')} for o in mW], sb)
        d['sliders'] = _sort_by([{**(R3(a) or {}), 'b': _g(a, 'b'), 'c': _g(a, 'c'), 'x': _g(a, 'x'), 'y': _g(a, 'y'), 'd': _g(a, 'd'),
                                  'mu': _nn(_g(a, 'mu'), 1), 'tb': _g(a, 'tb'), 'tx': _g(a, 'tx'), 'ty': _g(a, 'ty'),
                                  'tc': _nn(_g(a, 'tc'), _g(a, 'd')), 'tmu': _nn(_g(a, 'tmu'), 1), 'm': _nn(_g(a, 'm'), 0)} for a in mA], sb)

        def strip(r):
            if r is None:
                return None
            return {k: v for k, v in r.items() if k not in CHAIN_RAW_KEYS}
        d['burstSliders'] = _sort_by([{**(strip(R3(c)) or {}), 'b': _g(c, 'b'), 'c': _g(c, 'c'), 'x': _g(c, 'x'), 'y': _g(c, 'y'),
                                       'd': _g(c, 'd'), 'tb': _g(c, 'tb'), 'tx': _g(c, 'tx'), 'ty': _g(c, 'ty'),
                                       'sc': _nn(_g(c, 'sc'), 4), 's': _nn(_g(c, 's'), 1)} for c in mC], sb)

        def omit(r, ks):
            if r:
                for k in ks:
                    r.pop(k, None)
            return r
        et5 = lambda e: _num(e.get('et')) and e.get('et') == 5
        d['basicBeatmapEvents'] = _sort_by([{**(omit(R3(e), ['o']) or {}), 'b': _g(e, 'beat'), 'et': _g(e, 'et'), 'i': _nn(_g(e, 'i'), 0),
                                             'f': _nn(_g(e, 'f'), 1)} for e in mL if not et5(e)], sb)
        bst = [{**(omit(R3(e), ['et', 'i', 'f']) or {}), 'b': _g(e, 'beat'), 'o': js_tonum(_nn(_g(e, 'i'), 0)) > 0} for e in mL if et5(e)]
        old = [e for e in d['colorBoostBeatmapEvents'] if isinstance(e, dict)] if isinstance(d.get('colorBoostBeatmapEvents'), list) else []
        seen = {_jstr(e['b']) + '|' + _jstr(e['o']) for e in bst}
        oldk = lambda e: _jstr(_or(js_tonum(_g(e, 'b')), 0)) + '|' + _jstr(e.get('o') is True or (_num(e.get('o')) and e.get('o') == 1))
        d['colorBoostBeatmapEvents'] = _sort_by([e for e in old if oldk(e) not in seen] + bst, sb)
        d['bpmEvents'] = [{'b': p['beat'], 'm': p['bpm']} for p in tempo.parts]
        d['version'] = _or(d.get('version', UNDEF), '3.2.0')
        d.pop('_version', None)
    else:
        R2 = lambda o: _rf(o.get('raw'), False)
        ns = [{**(R2(n) or {}), '_time': _g(n, 'beat'), '_lineIndex': _g(n, 'x'), '_lineLayer': _g(n, 'y'), '_type': _g(n, 'c'),
               '_cutDirection': _g(n, 'd')} for n in mN]
        bs = [{**(R2(n) or {'_cutDirection': 0}), '_time': _g(n, 'beat'), '_lineIndex': _g(n, 'x'), '_lineLayer': _g(n, 'y'), '_type': 3}
              for n in mB]
        t = lambda p: _g(p, '_time')
        d['_notes'] = _sort_by(ns + bs, t)
        d['_obstacles'] = _sort_by([{**(R2(o) or {}), '_time': _g(o, 'beat'), '_lineIndex': _g(o, 'x'),
                                     '_type': 1 if (_num(o.get('y')) and o.get('y') == 2) else 0, '_duration': _g(o, 'dur'),
                                     '_width': _g(o, 'w')} for o in mW], t)
        d['_events'] = _sort_by([{**(R2(e) or {}), '_time': _g(e, 'beat'), '_type': _g(e, 'et'), '_value': _nn(_g(e, 'i'), 0)} for e in mL], t)
        d['_version'] = _or(d.get('_version', UNDEF), '2.0.0')
        d.pop('version', None)
    return d


def _has_body(f):
    return any(f.get(k) for k in ('notes', 'lightEvents', 'bombs', 'walls', 'arcs', 'chains'))


def cut_flat(f, cut_b):
    """collectExportDiffs: Music の終わり（拍）より後ろを書き出さない"""
    if not cut_b > 0:
        return f
    lim = cut_b + 1e-6
    keep = lambda arr, k: [o for o in arr if js_tonum(_g(o, k)) <= lim]
    return {'notes': keep(f['notes'], 'beat'), 'bombs': keep(f['bombs'], 'beat'), 'walls': keep(f['walls'], 'beat'),
            'arcs': keep(f['arcs'], 'b'), 'chains': keep(f['chains'], 'b'), 'lightEvents': keep(f['lightEvents'], 'beat')}


# ---- 全体の見積もり（書き出す前の計算・ファイルは書かない） ----

def sanitize_folder(v):
    """sanitizeFolderName（英数字と一部の記号だけ）＋前後の空白を落とす"""
    return re.sub(r"[^A-Za-z0-9 \-_.()\[\]&'!+,]", '', str(v or '')).strip()


def _dest(proj, ig):
    g = ((proj.get('graph') or {}).get('out')) or {}
    o = ig['outs'].get(ig['activeOut']) or {}
    p = g.get('outDirPath') or o.get('outDirPath')
    return p if isinstance(p, str) and p else None


class _Ctx:
    """開いた状態（applyProject の後）。書き出しに使う物を全部まとめる"""

    def __init__(self, proj, audio=True):
        self.proj = proj
        self.tempo = Tempo(proj)
        self.diffs, self.cur, self.bad, self.warn = open_diffs(proj)
        self.ig = info_graph(proj)
        self.ib, self.marks = info_base(proj, self.ig)
        self.audio = audio_path(proj) if audio else None   # audio=False＝音源を読み込んでいない NLM と同じ（答え合わせ用）
        self.audio_ok = bool(self.audio and os.path.isfile(self.audio))
        self.dur, self.sf_ok = (audio_len(self.audio) if self.audio_ok else (None, False))
        self.need_ffmpeg = bool(self.audio_ok and not self.sf_ok and not shutil.which('ffmpeg'))   # soundfile で読めず ffmpeg も無い
        if self.audio_ok and self.dur is None and not self.need_ffmpeg:
            self.bad.append((None, f'音源の長さが分からない（{os.path.basename(self.audio)}）'))
        self.egg = egg_plan(proj, self.tempo, self.dur)
        segs = msegs(proj, self.dur)
        cut = 0
        for sg in segs:
            cut = max(cut, self.tempo.beat(self.tempo.sec(sg['beat']) + sg['dur']))
        self.cut_b = cut
        self.cover = cover_source(proj, self.ig)
        g = ((proj.get('graph') or {}).get('out')) or {}
        self.folder = (g.get('folderName') or '').strip() if isinstance(g.get('folderName'), str) else ''
        self.dest = _dest(proj, self.ig)

    def std(self, dn):
        return self.diffs.get(f'{dn}Standard.dat'.lower())

    def nonempty(self):
        return [dn for dn in OUT_DIFFS if self.std(dn) is not None and _has_body(self.std(dn)['flat'])]

    def chosen(self, diffs=None):
        """書き出す難易度（OUT_DIFFS の順・中身の無い物は書かない＝NLM と同じ）。diffs: None＝書き出す印・'all'＝NLM と同じ全部・名前の並び"""
        ne = self.nonempty()
        if diffs == 'all':
            return ne
        if diffs is None:
            want = {D.name_of(k) for k, v in self.marks.items() if js_truthy(v) and _known(k)}
        else:
            want = {D.name_of(x) for x in diffs}
        return [dn for dn in ne if dn in want]

    def problems(self, chosen):
        """書けない理由のうち、書き出す難易度か全体に関わる物"""
        ks = {f'{dn}Standard.dat'.lower() for dn in chosen}
        return [m for k, m in self.bad if k is None or k in ks]

    def njs(self, dn):
        c = (self.proj.get('njsCfg') or {}).get(f'{dn}Standard.dat'.lower()) or {}
        return (c['njs'] if c.get('njs') is not None else DIFF_NJS.get(dn, 16)), (c['offset'] if c.get('offset') is not None else 0)

    def info(self, chosen, cover_name):
        """buildExportInfo"""
        b = self.ib
        return {'_version': '2.1.0',
                '_songName': _or(b.get('_songName'), ''), '_songSubName': _or(b.get('_songSubName'), ''),
                '_songAuthorName': _or(b.get('_songAuthorName'), ''), '_levelAuthorName': _or(b.get('_levelAuthorName'), ''),
                '_beatsPerMinute': self.tempo.bpm, '_songTimeOffset': numv(b.get('_songTimeOffset', UNDEF), 0),
                '_shuffle': numv(b.get('_shuffle', UNDEF), 0),
                '_shufflePeriod': numv(b.get('_shufflePeriod', UNDEF), 0) if numv(b.get('_shuffle', UNDEF), 0) != 0 else 0,
                '_previewStartTime': js_round(egg_out_sec(self.egg['pieces'], numv(b.get('_previewStartTime', UNDEF), PREV_DEF['start']),
                                                          lead_in_ms(song_node(self.proj))) * 1000) / 1000,
                '_previewDuration': numv(b.get('_previewDuration', UNDEF), PREV_DEF['dur']),
                '_songFilename': 'song.egg', '_coverImageFilename': _or(cover_name, b.get('_coverImageFilename', UNDEF), ''),
                '_environmentName': _or(b.get('_environmentName', UNDEF), 'DefaultEnvironment'),
                '_allDirectionsEnvironmentName': _or(b.get('_allDirectionsEnvironmentName', UNDEF), 'GlassDesertEnvironment'),
                '_difficultyBeatmapSets': [{'_beatmapCharacteristicName': 'Standard', '_difficultyBeatmaps': [
                    {'_difficulty': dn, '_difficultyRank': DIFF_RANK[dn], '_beatmapFilename': f'{dn}Standard.dat',
                     '_noteJumpMovementSpeed': self.njs(dn)[0], '_noteJumpStartBeatOffset': self.njs(dn)[1]} for dn in chosen]}]}

    def dat(self, dn):
        st = self.std(dn)
        return diff_json({**st, 'flat': cut_flat(st['flat'], self.cut_b)}, self.tempo)

    def cover_problems(self):
        """写していない補正（data.fit で画像を作り直す）・基準に合わない画像の注意"""
        bad, warn = [], []
        c = self.cover
        if not c:
            return bad, warn
        wh = image_size(c['data'])
        if js_truthy(c.get('fit')):
            if wh is None or cover_needs_fix(wh[0], wh[1], c['name']):
                bad.append('カバー画像の補正（NLM の「カバー画像の補正」）は写していない')
        elif wh is not None and cover_needs_fix(wh[0], wh[1], c['name']):
            warn.append(f'カバー画像が BeatLeader の基準（正方形・256×256 以上・png か jpg）に合わない（{wh[0]}×{wh[1]}）')
        elif wh is None:
            warn.append('カバー画像の寸法が分からない（png・jpg ではない？）')
        return bad, warn


def _known(k):
    try:
        D.name_of(k)
        return True
    except ValueError:
        return False


def _ctx(proj, audio=True):
    try:
        return _Ctx(proj, audio)
    except BsExportError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise _nlm(f'プロジェクトの形が想定と違う（{e}）')


def _lost(ctx, chosen):
    """exportLostNote: 元の譜面にあったが NLM が書き出さない物（ライトボックス・v4 の NJS の変化）"""
    out = []
    for dn in chosen:
        st = ctx.std(dn)
        lb = max([s.get('srcLbx') for s in st['sections'] if isinstance(s.get('srcLbx'), int) and s.get('kind') != 'null'] or [0])
        nj = max([len(s['srcNjs']) for s in st['sections'] if isinstance(s.get('srcNjs'), list) and s.get('kind') != 'null'] or [0])
        p = ([f'ライトボックス {lb} グループ'] if lb else []) + ([f'NJS の変化 {nj} 回'] if nj else [])
        if p:
            out.append(f'{D.TEXT[dn]}: ' + '、'.join(p))
    return ['元の譜面にあった物のうち NLM で扱えない物は書き出さない（' + ' / '.join(out) + '）'] if out else []


def plan(path):
    """.nlmf → 書き出しの見積もり（画面に出す物）。ファイルは書かない"""
    proj = nlmf.load(path)
    return plan_proj(proj)


def plan_proj(proj):
    unsupported, warnings, missing = [], [], []
    try:
        ctx = _ctx(proj)
    except BsExportError as e:
        return {'info': {}, 'folder': '', 'dest': None, 'diffs': [], 'missing': [], 'unsupported': [str(e)], 'warnings': [], 'blocking': []}
    warnings += ctx.warn
    b = ctx.ib
    cov = ctx.cover
    info = {'songName': b.get('_songName') or '', 'songSubName': b.get('_songSubName') or '', 'songAuthorName': b.get('_songAuthorName') or '',
            'levelAuthorName': b.get('_levelAuthorName') or '', 'bpm': ctx.tempo.bpm,
            'previewStart': numv(b.get('_previewStartTime', UNDEF), PREV_DEF['start']),
            'previewDuration': numv(b.get('_previewDuration', UNDEF), PREV_DEF['dur']),
            'environment': _or(b.get('_environmentName', UNDEF), 'DefaultEnvironment'),
            'cover': (cov['path'] if cov and cov['path'] else None), 'cover_embedded': bool(cov and not cov['path'])}
    chosen = ctx.chosen()
    unsupported += ctx.problems(chosen)
    ne = ctx.nonempty()
    rows = []
    for dn in OUT_DIFFS:
        st = ctx.std(dn)
        if st is None:
            continue
        f = cut_flat(st['flat'], ctx.cut_b)
        rows.append({'diff': dn, 'label': D.TEXT[dn], 'notes': len(f['notes']) + len(f['chains']), 'export': dn in chosen,
                     'marked': bool(js_truthy(ctx.marks.get(dn))), 'empty': dn not in ne})
    for k in ('songName', 'songAuthorName', 'levelAuthorName'):
        if not info[k]:
            missing.append(k)
    if not cov:
        missing.append('cover')
    if not ctx.folder:
        missing.append('folder')
    if not ctx.audio_ok:
        missing.append('audio')
    if not chosen:
        missing.append('diffs')
    marked_empty = [D.TEXT[dn] for dn in OUT_DIFFS if js_truthy(ctx.marks.get(dn)) and dn not in ne]
    if marked_empty:
        warnings.append('書き出す印が付いているが中身の無い難易度は書き出さない: ' + '・'.join(marked_empty))
    extra = [D.TEXT[dn] for dn in ne if dn not in chosen]
    if extra:
        warnings.append('書き出す印の無い難易度にもノーツがある（ここでは書き出さない・NLM で書き出すと入る）: ' + '・'.join(extra))
    g_marks = {k: v for k, v in ((((proj.get('graph') or {}).get('out')) or {}).get('diffs') or {}).items() if js_truthy(v)}
    if set(g_marks) != {k for k, v in ctx.marks.items() if js_truthy(v)}:
        warnings.append('書き出す印が 2 か所で違う（NLM は設定のノードの印を使う・こちらも同じ）')
    others = [v.get('name') or k for k, v in (proj.get('difficulties') or {}).items()
              if not any(k == f'{dn}Standard.dat'.lower() for dn in OUT_DIFFS)]
    if others:
        warnings.append('Standard 以外の難易度は書き出さない（NLM と同じ）: ' + '・'.join(map(str, others)))
    for dn in chosen:
        st = ctx.std(dn)
        if not st['v3'] and (st['flat']['arcs'] or st['flat']['chains']):
            warnings.append(f'{D.TEXT[dn]} は v2 の難易度なのでアーク・チェーンは書き出さない（NLM と同じ）')
    bad, warn = ctx.cover_problems()
    unsupported += bad
    warnings += warn
    warnings += _lost(ctx, chosen)
    if ctx.need_ffmpeg:
        missing.append('ffmpeg')
        warnings.append(FFMPEG_MSG.format(ext=Path(ctx.audio).suffix))
    blocking = [k for k in ('folder', 'audio', 'diffs', 'ffmpeg') if k in missing]
    return {'info': info, 'folder': ctx.folder, 'dest': ctx.dest, 'diffs': rows, 'missing': missing, 'unsupported': unsupported,
            'warnings': warnings, 'blocking': blocking, 'audio': ctx.audio}


# ---- 画面で入れた情報を .nlmf へ（NLM の画面で入れたのと同じ所） ----

INFO_KEYS = ('songName', 'songSubName', 'songAuthorName', 'levelAuthorName', 'bpm', 'previewStart', 'previewDuration', 'environment', 'cover')
_META = {'songName': ('name', '_songName'), 'songSubName': ('sub', '_songSubName'), 'songAuthorName': ('artist', '_songAuthorName'),
         'levelAuthorName': ('author', '_levelAuthorName')}


def _node_of(ig, t, x, y):
    """今の書き出しに繋がったその種類のノード（無ければ作って繋ぐ）→ id"""
    nid = None
    for e in reversed(ig.get('edges') or []):
        if e.get('o') == ig['activeOut'] and (ig['nodes'].get(e.get('s')) or {}).get('t') == t:
            nid = e['s']
            break
    if nid is None:
        ig['nseq'] = int(ig.get('nseq') or len(ig['nodes'])) + 1
        nid = t[0] + str(ig['nseq'])
        ig['nodes'][nid] = {'t': t, 'x': x, 'y': y, 'data': _def_data(t)}
        ig.setdefault('edges', []).append({'s': nid, 'o': ig['activeOut']})
    n = ig['nodes'][nid]
    n['data'] = {**_def_data(t), **(n.get('data') or {})}
    return nid


def apply_info(proj, changes):
    """画面で入れた情報（plan の info の key・'folder'・'diffs'＝{難易度: 真偽}）を proj に書く（NLM で開いても同じに見える所）。
    曲名など＝INFO の曲情報のノードと info、環境＝設定のノード（DefaultEnvironment は空）、試聴＝試聴のノード（元の音源の秒）、
    カバー＝カバーのノード（実パス）と coverData、フォルダ名＝graph.out と書き出しのノード（NLM と同じく使えない文字を落とす）。
    → 書いた key の並び"""
    if not changes:
        return []
    proj.setdefault('info', {})
    ig = proj.get('infoGraph')
    if not isinstance(ig, dict) or not isinstance(ig.get('nodes'), dict) or not isinstance(ig.get('outs'), dict) or not ig['outs']:
        raise _nlm('曲の情報（INFO の図）が古い形')
    if ig.get('activeOut') not in ig['outs']:
        ig['activeOut'] = next(iter(ig['outs']))
    done = []
    for k, v in changes.items():
        if k in _META:
            f, ik = _META[k]
            nid = _node_of(ig, 'meta', 24, 16)
            ig['nodes'][nid]['data'][f] = '' if v is None else str(v)
            proj['info'][ik] = '' if v is None else str(v)
            for x in (proj.get('graph') or {}).get('extra') or []:
                if x.get('kind') == 'info' and isinstance(x.get('data'), dict):
                    x['data'][ik] = '' if v is None else str(v)
        elif k == 'bpm':
            if v is not None and float(v) != float(Tempo(proj).bpm):
                raise ValueError('BPM はここでは変えられない（譜面の拍がずれる）')
            continue
        elif k in ('previewStart', 'previewDuration'):
            nid = _node_of(ig, 'prev', 336, 300)
            x = float(v)
            if not math.isfinite(x):
                raise ValueError(f'試聴の秒が数でない: {v}')
            if k == 'previewStart':
                x = max(0, js_round(x * 100) / 100)
                ig['nodes'][nid]['data']['start'] = x
                proj['info']['_previewStartTime'] = x
            else:
                x = max(0.5, js_round(x * 100) / 100)
                ig['nodes'][nid]['data']['dur'] = x
                proj['info']['_previewDuration'] = x
        elif k == 'environment':
            env = '' if (not v or v == 'DefaultEnvironment') else str(v)
            nid = _node_of(ig, 'set', 336, 16)
            ig['nodes'][nid]['data']['env'] = env
            proj['info']['_environmentName'] = env
        elif k == 'cover':
            _set_cover(proj, ig, v)
        elif k == 'folder':
            name = sanitize_folder(v)
            if name in ('.', '..'):
                name = ''
            g = proj.setdefault('graph', {}).setdefault('out', {})
            g['folderName'] = name
            ig['outs'][ig['activeOut']]['folderName'] = name
        elif k == 'diffs':
            for dn, on in (v or {}).items():
                D.set_export(proj, dn, bool(on))
            sid = _node_of(ig, 'set', 336, 16)
            ig['nodes'][sid]['data'].setdefault('diffs', {}).update({D.name_of(dn): 1 if on else 0 for dn, on in (v or {}).items()})
        else:
            raise ValueError(f'知らない項目: {k}')
        done.append(k)
    return done


def _set_cover(proj, ig, path):
    """カバー画像を NLM で選んだのと同じ形で入れる（ノードの名前と実パス・coverData・曲の流れの画面のカバーのノードと繋がり）"""
    cid = _node_of(ig, 'cover', 24, 206)
    if not path:
        ig['nodes'][cid]['data'] = {'name': ''}
        (proj.get('coverData') or {}).pop(cid, None)
        return
    p = Path(path)
    if p.suffix.lower() not in ('.png', '.jpg', '.jpeg') or not p.is_file():
        raise ValueError(f'カバー画像は jpg・png のファイル: {path}')
    data = p.read_bytes()
    d = {k: v for k, v in ig['nodes'][cid]['data'].items() if k != 'fit'}
    d.update(name=p.name, nativePath=str(p.resolve()))
    ig['nodes'][cid]['data'] = d
    proj['coverData'] = {**(proj.get('coverData') or {}), cid: 'data:application/octet-stream;base64,' + base64.b64encode(data).decode('ascii')}
    g = proj.setdefault('graph', {})
    extra = g.setdefault('extra', [])
    xc = next((x for x in extra if x.get('kind') == 'cover'), None)
    if xc is None:
        xc = {'id': 'xcover', 'kind': 'cover', 'nx': 620, 'ny': 350, 'data': {}, 'name': ''}
        extra.append(xc)
    xc['name'] = p.name
    ge = g.setdefault('edges', [])
    if not any(e.get('fromId') == xc['id'] and e.get('toId') == 'out' and e.get('sig') == 'cover' for e in ge):
        ge.append({'fromId': xc['id'], 'toId': 'out', 'sig': 'cover'})


# ---- song.egg（serve.py の _convert_to_ogg と同じ音） ----

def _f32(x):
    import numpy as np
    return np.float32(x)


def delay_samples(ms, sr):
    """ffmpeg の adelay（ミリ秒の指定）と同じ数のサンプル: float の掛け算・割り算をして切り捨て"""
    v = _f32(_f32(ms) * _f32(sr)) / _f32(1000.0)
    return int(v)


def trim_sample(sec, sr):
    """ffmpeg の atrim（'%.6f' 秒）の位置: マイクロ秒 → サンプル（四捨五入・半分は遠い方）"""
    ip, _, fp = ('%.6f' % sec).partition('.')
    us = int(ip) * 1000000 + int(fp)
    q, r = divmod(us * sr, 1000000)
    return q + (1 if 2 * r >= 1000000 else 0)


def egg_mark(path, egg):
    """.nlm-egg.json の印（exportMap の mark。名前・大きさ・更新時刻（ミリ秒・小数）は NLM の read_song_file と同じ）"""
    st = os.stat(path)
    mark = {'name': os.path.basename(path), 'size': st.st_size, 'mtime': os.path.getmtime(path) * 1000,
            'leadInMs': egg['lead_in_ms'], 'segs': egg['segs'], 'gainDb': egg['gain_db']}
    if egg.get('limit'):   # こちらのリミッター（NLM には無い項目・使った時だけ＝使わない時の印は NLM と同じ）
        mark['limit'] = egg['limit']
    return mark


def _num_eq(a, b):
    return _num(a) and _num(b) and a == b


def egg_same(prev, mark):
    """前の印と同じ（exportMap の比べ方）＝変換しなくてよい"""
    if not isinstance(prev, dict):
        return False
    return (prev.get('name') == mark['name'] and _num_eq(prev.get('size'), mark['size']) and _num_eq(prev.get('mtime'), mark['mtime'])
            and _num_eq(_or(prev.get('leadInMs'), 0), mark['leadInMs'])
            and js_dumps(_or(prev.get('segs'), None)) == js_dumps(mark['segs'])
            and _num_eq(_or(prev.get('gainDb'), 0), mark['gainDb'])
            and js_dumps(_or(prev.get('limit'), None)) == js_dumps(mark.get('limit')))


def _gain(g):
    return float('%.2f' % g) if abs(g) >= 0.005 else 0.0


def write_egg_sf(src, dst, egg, cancel=None, log=None, info=None):
    """soundfile で読める音源 → OGG Vorbis（無音追加・切り貼り・音量は ffmpeg と同じ位置と大きさ）。egg['limit']＝[目標 LUFS, 上限 dB] なら
    全体を読んでからリミッターを掛ける（automap/loudness.limit・こちらだけの処理）。info（dict）にリミッターの結果を入れる"""
    import numpy as np
    import soundfile as sf
    say = log or (lambda s: None)
    g = _gain(egg['gain_db'])
    k = np.float32(10 ** (g / 20)) if g else None
    n = audio_frames(src)[0]
    with sf.SoundFile(str(src)) as fi:
        sr, ch = fi.samplerate, fi.channels
        if egg['segs']:
            parts = []
            for a, b, at in egg['segs']:
                s0, s1 = trim_sample(a, sr), min(trim_sample(b, sr), n)
                if s1 > s0:
                    parts.append((s0, s1, delay_samples(round(at * 1000), sr)))   # serve.py は Python の round
            total = max([o + (s1 - s0) for s0, s1, o in parts] or [0])
        else:
            lead = delay_samples(egg['lead_in_ms'], sr) if egg['lead_in_ms'] > 0 else 0
            parts = [(0, n, lead)]
            total = lead + n
        say(f'song.egg を作る（{total / sr:.1f} 秒・{sr} Hz・{ch} ch）…')
        lim = egg.get('limit')
        whole = [] if lim else None
        with sf.SoundFile(str(dst), 'w', samplerate=sr, channels=ch, format='OGG', subtype='VORBIS', compression_level=1 - EGG_QUALITY) as fo:
            pos = 0
            while pos < total:
                if cancel and cancel():
                    raise BsExportCancelled('書き出しをやめた')
                m = min(BLOCK, total - pos)
                buf = np.zeros((m, ch), dtype=np.float32)
                for s0, s1, o in parts:
                    a, b = max(pos, o), min(pos + m, o + (s1 - s0))
                    if b <= a:
                        continue
                    want = s0 + (a - o)
                    if fi.tell() != want:   # 分けていない時は順に読む（MP3 の seek は遅い）
                        fi.seek(want)
                    x = fi.read(b - a, dtype='float32', always_2d=True)
                    buf[a - pos:a - pos + len(x)] += x
                if k is not None:
                    buf *= k
                if whole is not None:
                    whole.append(buf)
                else:
                    fo.write(buf)
                pos += m
            if whole is not None:
                from . import loudness
                say('リミッターで音量をそろえる（10〜20 秒）…')
                y, r = loudness.limit(np.concatenate(whole) if whole else np.zeros((0, ch), np.float32), sr, target=lim[0], ceil=lim[1])
                if info is not None:
                    info.update(r)
                for a in range(0, len(y), BLOCK):
                    if cancel and cancel():
                        raise BsExportCancelled('書き出しをやめた')
                    fo.write(np.ascontiguousarray(y[a:a + BLOCK], dtype=np.float32))
    return total, sr


def ffmpeg_cmd(ffmpeg, src, dst, egg):
    """serve.py の _convert_to_ogg と同じ ffmpeg の引数"""
    g = egg['gain_db']
    vol = 'volume=%.2fdB' % g if abs(g) >= 0.005 else ''
    cmd = [ffmpeg, '-y', '-i', str(src), '-vn']
    segs = egg['segs']
    if segs:
        parts = ['[0:a]atrim=start=%.6f:end=%.6f,asetpts=PTS-STARTPTS,adelay=%d:all=1[p%d]' % (a, b, round(at * 1000), i)
                 for i, (a, b, at) in enumerate(segs)]
        if len(segs) == 1:
            out = '[p0]'
        else:
            parts.append(''.join('[p%d]' % i for i in range(len(segs))) + 'amix=inputs=%d:normalize=0:dropout_transition=0[out]' % len(segs))
            out = '[out]'
        if vol:
            parts.append(out + vol + '[vol]')
            out = '[vol]'
        cmd += ['-filter_complex', ';'.join(parts), '-map', out]
    else:
        af = (['adelay=%d:all=true' % egg['lead_in_ms']] if egg['lead_in_ms'] > 0 else []) + ([vol] if vol else [])
        if af:
            cmd += ['-af', ','.join(af)]
    return cmd + ['-c:a', 'libvorbis', '-q:a', '5', str(dst)]


FFMPEG_MSG = ('この音源（{ext}）を song.egg に変えるには ffmpeg が要る（見つからない。"winget install Gyan.FFmpeg" でインストールして、'
              'アプリを起動し直してからもう一度書き出す）')


def write_egg_ffmpeg(src, dst, egg, cancel=None):
    ff = shutil.which('ffmpeg')
    if not ff:
        raise BsExportError(FFMPEG_MSG.format(ext=Path(src).suffix))
    with tempfile.TemporaryDirectory() as td:
        ext = re.sub(r'[^a-z0-9]', '', Path(src).suffix.lower().lstrip('.')) or 'bin'
        tmp_in = Path(td) / f'in.{ext}'
        shutil.copyfile(src, tmp_in)
        out = Path(td) / 'out.ogg'
        p = subprocess.Popen(ffmpeg_cmd(ff, tmp_in, out, egg), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while True:
                try:
                    _, err = p.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if cancel and cancel():
                        p.kill()
                        p.communicate()
                        raise BsExportCancelled('書き出しをやめた')
        finally:
            if p.poll() is None:
                p.kill()
        if p.returncode != 0 or not out.is_file():
            raise BsExportError('song.egg への変換に失敗した（ffmpeg）: ' + (err or b'').decode('utf-8', 'ignore')[-300:])
        shutil.move(str(out), str(dst))


# ---- ANP の印（NLM の書き出しには無い・写しと違う所） ----

def anp_version():
    """印に書く版（automap/version.py の VERSION から頭の v を落とした物＝ChroMapper 等と同じ「0.2.0」の形）"""
    from . import version
    return str(version.VERSION).lstrip('vV')


def put_mark(info, ver=None):
    """ANP で作った印を Info（v2 の形・buildExportInfo の答え）に入れる: _customData._editors の _lastEditedBy と ANP_EDITOR: {version}。
    前からある _customData・_editors の項目（ほかのエディタの印）は残す。ver: 版の文字（省略は今の版）→ info"""
    cd = info.get('_customData')
    cd = dict(cd) if isinstance(cd, dict) else {}
    ed = cd.get('_editors')
    ed = dict(ed) if isinstance(ed, dict) else {}
    ed['_lastEditedBy'] = ANP_EDITOR
    ed[ANP_EDITOR] = {'version': ver or anp_version()}
    cd['_editors'] = ed
    info['_customData'] = cd
    return info


def anp_mark(info):
    """Info.dat（v2 の _customData._editors・v4 の customData.editors）の ANP の印 → 版の文字（印が無ければ None）。
    ほかのエディタで直した後（_lastEditedBy が別）も ANP_EDITOR の項目が残っていれば印あり（版が分からなければ '?'）"""
    if not isinstance(info, dict):
        return None
    for ck, ek in (('_customData', '_editors'), ('customData', 'editors')):
        cd = info.get(ck)
        ed = cd.get(ek) if isinstance(cd, dict) else None
        if not isinstance(ed, dict):
            continue
        e = ed.get(ANP_EDITOR)
        if isinstance(e, dict):
            return str(e.get('version') or '?')
        if ANP_EDITOR in (ed.get('_lastEditedBy'), ed.get('lastEditedBy')):
            return '?'
    return None


# ---- 書き出す ----

def _atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.part')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def build(proj, diffs=None, audio=True, mark=True):
    """書き出す中身（ファイルは書かない）→ {'files': {名前: バイト}, 'chosen', 'cover', 'ctx', 'info'}。書けない物があれば BsExportError。
    audio=False: 音源を読まない（音源を読み込んでいない NLM と同じ＝Music の配置を音源の長さで切らない・試聴は無音追加を足すだけ）。
    mark: Info.dat の ANP の印（True＝今の版・False＝入れない＝NLM の書き出しとバイトまで同じ（答え合わせ）・版の文字＝その版の印）"""
    ctx = _ctx(proj, audio)
    chosen = ctx.chosen(diffs)
    bad = ctx.problems(chosen) + ctx.cover_problems()[0]
    if bad:
        raise _nlm('・'.join(bad))
    if not chosen:
        raise BsExportError('書き出す難易度が無い（書き出す印の付いた、ノーツのある難易度が要る）')
    cov = ctx.cover
    cover_name = cover_out_name(cov['name']) if cov else ''
    info = ctx.info(chosen, cover_name)
    if mark:   # 写しと違う所（NLM の buildExportInfo には無い）
        put_mark(info, None if mark is True else str(mark))
    files = {}
    files['Info.dat'] = js_dumps(info, 2).encode('utf-8')
    for dn in chosen:
        files[f'{dn}Standard.dat'] = js_dumps(ctx.dat(dn)).encode('utf-8')
    return {'files': files, 'chosen': chosen, 'cover': (cover_name, cov['data']) if cov else None, 'ctx': ctx, 'info': info}


def map_hash(files, info):
    """BeatSaver の版の hash（Info.dat の中身＋難易度の .dat を Info の順に続けた sha1・tools/library_build/common.bs_hash と同じ）"""
    h = hashlib.sha1(files['Info.dat'])
    for s in info['_difficultyBeatmapSets']:
        for bm in s['_difficultyBeatmaps']:
            h.update(files[bm['_beatmapFilename']])
    return h.hexdigest()


def write(path, dest_root, folder=None, changes=None, diffs=None, log=None, cancel=None, force_egg=False, limiter=None):
    """.nlmf を Beat Saber の譜面のフォルダ <dest_root>/<folder>/ に書き出す（NLM の exportMap と同じ物）。
    folder: 無ければ .nlmf のフォルダ名（graph.out.folderName）・changes: 画面で入れた情報（apply_info と同じ key・.nlmf は書き換えない）・
    diffs: 書き出す難易度（None＝書き出す印・'all'＝NLM と同じく中身のある全部・名前の並び）・log(文)・cancel()→真ならやめる・
    force_egg: song.egg を必ず作り直す（NLM の「song.egg を強制再変換」）・limiter: (目標 LUFS, 上限 dB)＝リミッターで音量をそろえる（こちらだけ・
    soundfile で読める音源だけ・印の limit で前と比べる）。
    → {'dir','files','hash','difficulties','song_name','level_author','warnings','egg'（'written'|'kept'）,'limiter'（掛けた時の結果）}"""
    say = log or (lambda s: None)
    stop = cancel or (lambda: False)
    proj = nlmf.load(path)
    if changes:
        apply_info(proj, changes)
    pl = plan_proj(proj)
    name = sanitize_folder(folder if folder is not None else ((proj.get('graph') or {}).get('out') or {}).get('folderName'))
    if not name or name in ('.', '..'):
        raise BsExportError('書き出すフォルダ名が無い（英数字と一部の記号だけ・日本語は Beat Saber が読めないので使えない）')
    root = Path(dest_root)
    if not root.is_dir():
        raise BsExportError(f'書き出し先のフォルダが無い: {root}')
    if not ((proj.get('graph') or {}).get('song') or {}).get('nativePath') or proj.get('songDeleted'):
        raise BsExportError('プロジェクトに音源が無い（song.egg を作れない）')
    p0 = audio_path(proj)
    if not os.path.isfile(p0):
        raise BsExportError(f'音源のファイルが見つからない: {p0}')
    if not _sf_readable(p0) and not shutil.which('ffmpeg'):
        raise BsExportError(FFMPEG_MSG.format(ext=Path(p0).suffix))
    b = build(proj, diffs)
    ctx = b['ctx']
    if stop():
        raise BsExportCancelled('書き出しをやめた')
    dest = root / name
    dest.mkdir(exist_ok=True)
    written = []
    if b['cover']:   # カバー画像 → cover.<拡張子>（補正の無い時はそのままのバイト）
        _atomic(dest / b['cover'][0], b['cover'][1])
        written.append(b['cover'][0])
        say(f'カバー画像: {b["cover"][0]}')
    egg = ctx.egg
    if limiter:
        if ctx.sf_ok:
            egg = dict(egg, limit=[float(limiter[0]), float(limiter[1])])
        else:
            say('この音源の形式ではリミッターを使えない（ffmpeg で変える形式・自動の補正だけ）')
    mark = egg_mark(ctx.audio, egg)
    lim_info = {}
    egg_p = dest / 'song.egg'
    prev = None
    if egg_p.is_file() and not force_egg:
        try:
            prev = json.loads((dest / '.nlm-egg.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            prev = None
    if egg_same(prev, mark):
        egg_state = 'kept'
        say('song.egg は前と同じ（作り直さない）')
    else:
        egg_state = 'written'
        part = dest / 'song.egg.part'
        try:
            data = Path(ctx.audio).read_bytes()[:4]
            if data == b'OggS' and not (egg['lead_in_ms'] > 0 or egg['segs'] or egg['gain_db'] or egg.get('limit')):
                shutil.copyfile(ctx.audio, part)   # 元が OGG で手を加えない時はそのまま写す
            elif ctx.sf_ok:
                write_egg_sf(ctx.audio, part, egg, stop, say, lim_info)
            else:
                say('song.egg を作る（ffmpeg）…')
                write_egg_ffmpeg(ctx.audio, part, ctx.egg, stop)
            os.replace(part, egg_p)
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
        (dest / '.nlm-egg.json').write_text(js_dumps(mark), encoding='utf-8')
    written.append('song.egg')
    if stop():
        raise BsExportCancelled('書き出しをやめた（譜面のファイルは書いていない）')
    for fn, data in b['files'].items():
        _atomic(dest / fn, data)
        written.append(fn)
    say(f'書き出した: {dest}（{" / ".join(written)}）')
    info = b['info']
    return {'dir': str(dest), 'files': written, 'hash': map_hash(b['files'], info),
            'difficulties': [{'characteristic': 'Standard', 'name': dn} for dn in b['chosen']],
            'song_name': info['_songName'], 'level_author': info['_levelAuthorName'], 'warnings': pl['warnings'], 'egg': egg_state,
            'limiter': lim_info or None}
