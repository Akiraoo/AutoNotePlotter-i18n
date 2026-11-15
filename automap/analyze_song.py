"""曲の解析（テンポ・無音追加の推定と構成の解析）を、NLM を動かさずにこちらだけで行う（docs/アプリ仕様.md 5 節）。
中身は NLM の `song_analysis/` の写し（`automap/song_analysis/`・手を加えない・写した元は SOURCE.md・差は tools/sync_nlm_analysis.py）。
ここは NLM の画面と同じ手順・同じ値で写した物を呼ぶ包み:

- テンポ: 音源を読む（service._load と同じ）→ tempo.onset_env → tempo.estimate（NLM が .nlmf の analysis.tempo に入れる形にそろえる＝
  service._run の 'tempo'）。
- HPSS（調波・打楽器成分）: `analysis` は song_analysis.hpss で 1 回だけ分け、テンポ（打楽器成分）と構成（調波成分）へ渡す＝NLM の
  service と同じ使い回し（NLM 94dcf8e・2026-11-11・答えは 1 ビットも同じ・桃源郷で解析が 45 → 17 秒ほど）。
- 構成: 目盛り（拍 0, 1/4, 2/4 … ごとの元の音源の秒＝NLM の editor-app.js の anaAtGrid・audioPosAtBeat・msegs と同じ）→
  structure.measure_at → structure.analyze → structure.result_json（＝service._run の 'structure'）。
  目盛りはテンポが一定で Music を切り貼りしない時（BPM・無音追加・Music の拍の位置だけ）に作れる。テンポパートは扱わない。
- 両方: `analysis(path, bpm, lead_ms)` が NLM の .nlmf の `analysis`（`{v, tempo, structure, names, grid}`）と同じ形を返す。

使い方: .venv/Scripts/python.exe -m automap.analyze_song <音源> [--bpm B --lead-ms L] [--json 出力.json]
  （--bpm・--lead-ms が無ければテンポの推定の値で構成を解析する。NLM の「適用」と同じく BPM は 0.01・無音追加は 1ms に丸める）
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path

from .song_analysis import RESULT_VERSION, hpss
from .song_analysis import service as _svc

SR = _svc.SR
SUB = 4   # structure.SUB と同じ（1拍を何コマに分けて測るか）


class AnalysisError(Exception):
    """解析できない（code は NLM と同じ: too-short・bad-audio・ffmpeg-not-found・few-cells 等）"""
    def __init__(self, code, detail=''):
        super().__init__(f'{code}: {detail}' if detail else code)
        self.code, self.detail = code, detail


def _quiet():
    warnings.filterwarnings('ignore', module=r'(librosa|numpy|scipy|sklearn|numba|soundfile|automap\.song_analysis)')


def load(path):
    """音源を解析の形（SR・モノラル）で読む（service.AnalysisService._load と同じ。m4a 等は ffmpeg で WAV にしてから）"""
    import librosa
    _quiet()
    path = str(path)
    try:
        y, _ = librosa.load(path, sr=SR, mono=True)
    except Exception as e:   # noqa: BLE001
        ext = path.rsplit('.', 1)[-1].lower()
        ffmpeg = shutil.which('ffmpeg')
        if ffmpeg:
            with tempfile.TemporaryDirectory() as td:
                wav = os.path.join(td, 'dec.wav')
                r = subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-i', path, '-vn', '-f', 'wav', '-acodec', 'pcm_f32le', wav],
                                   capture_output=True, timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if r.returncode != 0 or not os.path.isfile(wav):
                    raise AnalysisError('bad-audio', (r.stderr or b'').decode('utf-8', 'ignore')[-300:])
                y, _ = librosa.load(wav, sr=SR, mono=True)
        else:
            y = _tail_load(path)
            if y is None:
                raise AnalysisError('bad-audio' if ext in _svc.SF_EXTS else 'ffmpeg-not-found', str(e)[:300])
    if y.ndim != 1 or len(y) < _svc.MIN_SEC * SR:
        raise AnalysisError('too-short')
    return y


def _tail_load(path):
    """ffmpeg が無い PC で、終わりだけが壊れた音源（最後のフレームが切れた MP3 等・automap/sfread）を librosa.load と同じ手順
    （そのまま読む → to_mono → soxr_hq で SR へ）で読む。読めなければ None（ffmpeg がある時は今まで通り ffmpeg＝NLM と同じ）"""
    import librosa
    from . import sfread
    try:
        x, sr0 = sfread.read(path)
    except Exception:   # noqa: BLE001
        return None
    return librosa.resample(librosa.to_mono(x.T), orig_sr=sr0, target_sr=SR, res_type='soxr_hq')


def tempo(path, y=None, hp=None):
    """テンポ（BPM）と無音追加の推定 → NLM の analysis.tempo と同じ形（bpm・raw_bpm・lead_ms・alt_lead_ms・steps・drift・alt…・version）。
    hp＝y の hpss(y)（先に分けてあれば。無ければここで打楽器成分だけ計算する＝同じ値）"""
    from .song_analysis import tempo as T
    _quiet()
    if y is None:
        y = load(path)
    env, fps, dur, low = T.onset_env(str(path), y=y, yp=None if hp is None else hp[1])
    r = T.estimate(env, fps, low=low)
    if r.get('error'):
        r['error'] = 'few-onsets'   # 強い打点が少なすぎる（BPM・無音追加は目安）
    r['drift'] = [list(x) for x in r.get('drift') or []]
    r['version'] = RESULT_VERSION
    return _svc._plain(r)


def audio_duration(path):
    """音源の長さ（秒）。NLM の画面の songDur（ブラウザが読んだ音の長さ）の代わり"""
    try:
        import soundfile as sf
        return float(sf.info(str(path)).duration)
    except Exception:   # noqa: BLE001
        return len(load(path)) / SR


def at_grid(bpm, lead_ms, dur, music_beat=0.0, sub=SUB):
    """構成の解析に渡す目盛り: 拍 0, 1/sub, 2/sub … ごとの元の音源の秒（音の無い所は None）。NLM の anaAtGrid と同じ:
    Music は1つの区切り（拍 music_beat から・長さ＝曲の長さ＋無音追加＝msegs）・拍→秒はテンポ一定・秒は 1ms に丸める"""
    spb = 60.0 / bpm
    off0 = -lead_ms / 1000.0                         # getSongOff()＝songNode.offset＝−無音追加
    seg_t0, seg_dur = music_beat * spb, max(0.0, dur - off0)
    e = (seg_t0 + seg_dur) / spb                     # segEndBeat
    n = math.floor(e * sub + 1e-6)
    at = []
    for k in range(n + 1):
        rel = (k / sub) * spb - seg_t0
        if 0 <= rel < seg_dur:
            p = off0 + rel
            at.append(round(p * 1000) / 1000 if 0 <= p < dur else None)
        else:
            at.append(None)
    return at


def structure(path, bpm, lead_ms, y=None, music_beat=0.0, dur=None, hp=None):
    """構成の解析 → NLM の analysis.structure と同じ形（sub・sections・segments・chorus・version・bpm・leadMs）。
    hp＝y の hpss(y)（tempo と同じ）"""
    from .song_analysis import structure as ST
    _quiet()
    if y is None:
        y = load(path)
    if dur is None:
        dur = audio_duration(path)
    at = at_grid(bpm, lead_ms, dur, music_beat)
    F = ST.measure_at(str(path), at, bpm, lead_ms, y=y, yh=None if hp is None else hp[0])
    if int((F['at'] == F['at']).sum()) < _svc.MIN_CELLS:
        raise AnalysisError('too-short')
    res = ST.analyze(F, bpm)
    out = ST.result_json(res, RESULT_VERSION)
    out['bpm'], out['leadMs'] = bpm, lead_ms
    return _svc._plain(out)


# ---- NLM の画面が保存の前に結果を整える所（js/analysis/song-analysis.js の cleanTempo・cleanStructure・cleanGrid・atSec）と同じ ----
MAX_ITEMS, NAME_MAX = 4000, 40
_num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def clean_tempo(r):
    if not isinstance(r, dict) or not _num(r.get('bpm')) or r['bpm'] <= 0:
        return None
    o = {'bpm': r['bpm'], 'lead_ms': r['lead_ms'] if _num(r.get('lead_ms')) else 0}
    for k in ('raw_bpm', 'alt_lead_ms', 'offbeat_ratio', 'drift_pct', 'block_mad_ms', 'n_beats', 'family', 'slope', 'resid_mad_ms'):
        if _num(r.get(k)):
            o[k] = r[k]
    o['low_offbeat'] = bool(r.get('low_offbeat'))
    o['slope_sig'] = bool(r.get('slope_sig'))
    o['steps'] = [{'sec': s['sec'], 'ms': s['ms']} for s in (r.get('steps') or []) if isinstance(s, dict) and _num(s.get('sec')) and _num(s.get('ms'))][:50]
    o['drift'] = [[d[0], d[1]] for d in (r.get('drift') or []) if isinstance(d, (list, tuple)) and len(d) >= 2 and _num(d[0]) and _num(d[1])][:400]
    a = r.get('alt')
    o['alt'] = {'bpm': a['bpm'], 'ratio': a['ratio']} if isinstance(a, dict) and _num(a.get('bpm')) and _num(a.get('ratio')) else None
    if r.get('error'):
        o['error'] = True
    return o


def clean_structure(r):
    if not isinstance(r, dict):
        return None
    sstr = lambda x, n: x[:n] if isinstance(x, str) else ''
    secs = []
    for s in [s for s in (r.get('sections') or []) if isinstance(s, dict) and _num(s.get('start')) and _num(s.get('end')) and s['end'] > s['start']][:MAX_ITEMS]:
        o = {'start': s['start'], 'end': s['end'], 'label': sstr(s.get('label'), 12) or '?', 'count': s['count'] if _num(s.get('count')) else 1,
             'chorus': bool(s.get('chorus')), 'name': sstr(s.get('name'), NAME_MAX)}
        for k in ('a0', 'a1'):
            if _num(s.get(k)):
                o[k] = s[k]
        secs.append(o)
    segs = [{'start': s['start'], 'end': s['end'], 'group': sstr(s.get('group'), 8) or '?', 'count': s['count'] if _num(s.get('count')) else 1,
             'best': s['best'] if _num(s.get('best')) else None, 'sim': s['sim'] if _num(s.get('sim')) else None}
            for s in (r.get('segments') or []) if isinstance(s, dict) and _num(s.get('start')) and _num(s.get('end')) and s['end'] > s['start']][:MAX_ITEMS]
    if not secs and not segs:
        return None
    chorus = [x[:8] for x in (r.get('chorus') or []) if isinstance(x, str)][:64]
    return {'sub': r['sub'] if _num(r.get('sub')) else SUB, 'sections': sorted(secs, key=lambda s: s['start']),
            'segments': sorted(segs, key=lambda s: s['start']), 'chorus': chorus}


def at_sec(at, sub, b, d):
    """拍 b の元の音源の秒（無ければ d の向きに近い物）＝NLM の atSec"""
    if not at:
        return None
    k = max(0, min(len(at) - 1, math.floor(b * sub + 0.5)))   # JS の Math.round と同じ（.5 は上へ）
    for rng in (range(k, len(at) if d > 0 else -1, d), range(k, -1 if d > 0 else len(at), -d)):
        for i in rng:
            if _num(at[i]):
                return at[i]
    return None


def analysis(path, bpm=None, lead_ms=None, music_beat=0.0, song_name=None):
    """テンポの推定と構成の解析 → NLM の .nlmf の analysis と同じ形 {v, tempo, structure, names, grid}（NLM の画面が保存する形に整える）。
    bpm・lead_ms が無ければ推定の値を NLM の「適用」と同じく丸めて使う（BPM 0.01・無音追加 1ms）"""
    y = load(path)
    _quiet()
    hp = hpss(y)   # テンポと構成で 1 回だけ（NLM の service と同じ）
    tp = tempo(path, y=y, hp=hp)
    if bpm is None:
        bpm = round(float(tp['bpm']), 2)
    if lead_ms is None:
        lead_ms = int(round(float(tp.get('lead_ms') or 0)))
    dur = audio_duration(path)
    st = clean_structure(structure(path, bpm, lead_ms, y=y, music_beat=music_beat, dur=dur, hp=hp))
    at = at_grid(bpm, lead_ms, dur, music_beat)
    for s in (st or {}).get('sections') or []:   # 解析した時の元の音源の秒（NLM が名前の引き継ぎに使う）
        a0, a1 = at_sec(at, SUB, s['start'], 1), at_sec(at, SUB, s['end'], -1)
        if a0 is not None:
            s['a0'] = a0
        if a1 is not None:
            s['a1'] = a1
    return {'v': RESULT_VERSION, 'tempo': clean_tempo(tp), 'structure': st, 'names': {},
            'grid': {'bpm': bpm, 'leadMs': lead_ms, 'tp': [], 'mb': music_beat, 'ms': None, 'song': (song_name or Path(path).name)[:300]}}


def main(argv=None):
    ap = argparse.ArgumentParser(description='曲の解析（テンポ・無音追加の推定と構成の解析・NLM の写し）')
    ap.add_argument('audio')
    ap.add_argument('--bpm', type=float, help='構成の解析に使う BPM（無ければ推定の値）')
    ap.add_argument('--lead-ms', type=float, help='構成の解析に使う無音追加（ms・無ければ推定の値）')
    ap.add_argument('--music-beat', type=float, default=0.0, help='Music の始まりの拍（NLM の musicBeat・既定 0）')
    ap.add_argument('--json', help='結果（.nlmf の analysis と同じ形）を書くファイル')
    a = ap.parse_args(argv)
    t0 = time.time()
    try:
        res = analysis(a.audio, a.bpm, a.lead_ms, a.music_beat)
    except AnalysisError as e:
        sys.exit(f'解析できない: {e}')
    t = res['tempo']
    print(f'BPM {res["grid"]["bpm"]}（推定 {t.get("bpm")}）・無音追加 {res["grid"]["leadMs"]}ms（推定 {t.get("lead_ms")}）・{time.time() - t0:.1f} 秒')
    for s in res['structure'].get('sections') or []:
        print(f'  拍 {s["start"]:g}〜{s["end"]:g}  {s.get("name") or ""} {s.get("label") or ""}{"（サビ）" if s.get("chorus") else ""}')
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False), encoding='utf-8')
        print(a.json)


if __name__ == '__main__':
    main()
