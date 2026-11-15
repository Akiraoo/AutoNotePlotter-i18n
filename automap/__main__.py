"""コマンド（compose だけ。試作0 の regen・打点の確かめ用の rhythm は除いた・docs/除いた物.md）。

python -m automap compose <プロジェクト.nlmf> --stems <分けた音のフォルダ> --form --style [--intent 意思入れの表] [--seed N]
  試作5＋意思入れ（アプリと配布物の作り直し・取り込み・難易度の展開はいつもこれ）。--form と --style は必ず付ける（無い試作1〜4 の道は
  除いた・docs/除いた物.md）。分けた音から測った「曲の流れの表」（form.py・music.py）のまとまり（くり返しの記号）ごとに、盛り上がりの
  段階で密度と両手を決めて打点を選び（rhythm.py）・途切れは空けて戻りを両手に、テーマを曲の個性（テンポ・歌のリズムの細かさと裏拍・歌の
  音の長さと跳び・ドラム・style.py）で傾けて性格ごとに 6 つ選んで小節ごとに回し（form.mix_guides）、流れの計算で置く（flow.py）。
  歌の打点は歌の高さで段を少し選ぶ。出力は --out（無ければ out/<曲名>.intent-s<種>.nlmf・--intent が無ければ style-s<種>）と .report.md。
  マーカーの名前の書き込み（区間は切らない）: ★＝そのまとまりを盛り上げる・静＝抑える・ドラム＝次のマーカーまで歌でなくドラムと楽器に打つ。
  「※」で始まる名前は人のコメント（区間を切らず、報告に一覧を出す）。
  「ここから」＝結果のファイルを土台にした時、その拍より前は結果のファイルのまま残し（人が直したノーツ・ボム・アーク等）、後ろだけ作り直す。
  作り直しは残した所の最後の振り（手・向き・位置）を引き継いで続ける。
  --intent <意思入れの表>: 利用者がアプリで付けた意思入れ（docs/意思入れ.md・intent.py）を効かせる。
  別の案「案 k」（--style と一緒に）: 区間と重なる小節のテーマを、曲のテーマの並びの中でずらして選ぶ（intent.variant_spec）。意思入れの区間の
  指示 set.variant＝k（アプリの「これにする」が付ける）と --variant K（--only の区間・無ければ全部・表の「案」より後に効く）の2つの口。
  珍しい型まで（--style と一緒に）: 区間と重なる小節のテーマを、テーマに使う型のしきい値を「珍しい」まで下げた型の束（少ない曲にしか
  出ない型も・theme.load_themes(…, freq='珍しい')）で選び直す。意思入れの区間の指示 set.rare と --rare（--only の区間・無ければ全部）。
  案 k と一緒なら、広げた束の中で案 k のずらし方。曲全体のテーマの束と種は変えない。
  ★の帯（--style と一緒に）: 区間と重なる小節のテーマを、★の帯だけ変えた型のデータベースの書き出し（library_use.export_band・帯ごとに1回）
  で選び直す。意思入れの区間の指示 set.band（−1 1段やさしく・+1 1段難しく・[下, 上]）と --band（--only の区間・無ければ全部）。
  珍しい型まで・案 k と一緒なら、その帯の束の中で広げる・ずらす。
  同じ振りの形の案 k・珍しい型まで・★の帯（意思入れの形の設定＝intent.form_specs）: その形の型（テーマ）を同じ決まりで選び直す
  （_form_pick。A＝手本の形・B＝アレンジの形は別々。B に設定が無ければ A の型の左右入れ替え＝今まで通り）。小節のテーマには効かせない。
  決め（kime.py）: 型のデータベースの 1回だけの並び（once）の珍しい型を、途切れの前・区間の変わり目の直前などの
  1回だけの場所に1つずつ入れる（決めたノーツとして流れの計算をし直す・決めの前後の外は今の結果に弱く留める）。--no-kime で切る。
  意思入れの区間の指示 set.kime（1＝入れる・−1＝入れない）・珍しい型までの区間（と --only と一緒の --rare）は入れる側。
  型の出どころ（--library）: BeatLeader のランク譜面の型のデータベースの絞り込み（無ければ新しい曲の既定 library_use.DEFAULT）。
  データベースが使えない時は「型のデータベースが使えない（理由）」を出して止まる（前の今の型 cache/themes.json と --themes は除いた）。
  前の譜面に寄せる（--prev-intent <前の作り直しの時の意思入れの表>・結果のファイルを土台にした時だけ）: 今の表と比べて指示が変わった所
  （intent.changed_ranges）と前後 2 拍だけ自由に作り、ほかの打点は前の結果の作ったノーツの置き方に弱く寄せる（重み --anchor-w）
  ＝変えた区間とつなぎ目だけが変わる。アプリは履歴の版の作業ファイルから渡し、全体の設定を変えた時・前の版が分からない時は
  --no-anchor <理由>。意思入れの「そのまま残す」の区間は、前の譜面のノーツを NLM の「固定」と同じに残す（_keep_plan の keep）。
  前の譜面に寄せる時、決めは指示を変えていない所の物を前の版のまま使い（場所と型・kime.carry）、新しく選ぶのは変わった所だけ。
  前の版の決めは、書き換える前の結果のファイルの報告の表（無ければ --prev-intent の隣の <…>.report.md＝アプリの履歴の版の報告）から
  読む（_prev_kimes）。区間だけ作り直した報告には、作り直さなかった所の決めを節「決め（残したノーツの中・前の版のまま）」に書く。

結果のファイルは作業用のファイル: 結果のファイルがあれば、作り直す時はそれを土台にして設定（無音追加・NJS・マーカーの ★ 等）を
引き継ぐ。こちらで書いた後に NLM で保存し直されていたら、上書きの前に out/old/ へ控えを取る（こちらで書いた時のファイルの指紋は out/.state/）。
--fresh は結果のファイルがあっても入力を土台にする（元のファイルを直した時）。
compose が結果のファイルを土台に作り直す時の NLM とのやり取り（クリップの id＝中身の指紋・nlmf.classify）: 作ったまま（id と指紋が一致）の
クリップだけを作り直し、NLM で直した物（中身が変わった・名前に「固定」・利用者のクリップ・別のレーン）は残す。作ったクリップは曲の頭から
終わりまで隙間なく置くので、作ったクリップのレーンの隙間＝NLM で消した所は空のまま。残したノーツは流れの計算に「決めたノーツ」として入れて
前後をつなぐ（出力には入れない）。
"""
import os

if __name__ == '__main__':   # 作り直しのプロセス（python -m automap）: 流れの計算（Numba・automap/flow_nb.py）のコンパイル済みの控えを
    # CPU の種類によらず使う（配布物に入れた控えをどの PC でも読む）。曲の解析（librosa の Numba）はこのプロセスでは動かない
    os.environ.setdefault('NUMBA_CPU_NAME', 'generic')

import argparse
import bisect
import copy
import json
import math
import shutil
import sys
import time
from pathlib import Path

from . import audio, echo, flow, form, groove, handoff, intent, kime, loops, music, nlmf, relief, repeat, rhythm, stats, style, theme, window

ROOT = Path(__file__).resolve().parent.parent
CLIP_COLOR = '#e0a040'
PALETTE = 6   # 性格ごとのテーマの数（試作5・前の --palette の既定。比べの切り替え --palette・--switch・--split・--follow は除いた）


# こちらで書いた印（out/.state/）: 軽い部品に分けた（アプリのサーバーがこの重いモジュールを読まずに使う・automap/written.py）
from .written import _sha, _state_path, _edited_since_written, _save  # noqa: E402,F401


def _open_project(a, out):
    """(プロジェクト, 土台にしたファイル, 知らせ)。結果のファイルがあればそれを土台にする（--fresh の時は入力）。
    結果のファイルが NLM で直されていれば、上書きの前に控えを取る"""
    src, notes = Path(a.input), []
    if out.exists() and not getattr(a, 'fresh', False):
        src = out
        notes.append('結果のファイルを土台にした（設定・マーカーを引き継ぎ）')
    if _edited_since_written(out):
        bk = out.parent / 'old' / f'{out.stem}.{time.strftime("%Y%m%d-%H%M%S")}{out.suffix}'
        bk.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, bk)
        notes.append(f'NLM で直された結果の控え: old/{bk.name}')
    return nlmf.load(src), src, '。'.join(notes) or None


def _out_for(a, name):
    out = Path(a.out) if a.out else ROOT / 'out' / name
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _marker_bounds(proj, end):
    """曲の頭（拍 0）から end までをマーカーで区切る → [(始まり, 終わり, 名前)]。頭のマーカーより前は最初の区間に含める"""
    marks = sorted((m for m in proj.get('markers') or [] if isinstance(m, dict) and isinstance(m.get('beat'), (int, float))),
                   key=lambda m: m['beat'])
    head = [m for m in marks if m['beat'] <= 1e-9]
    inner = [m for m in marks if 1e-9 < m['beat'] < end - 1e-9]
    name0 = head[-1].get('name') if head else (inner[0].get('name') if inner else '')
    if not head and inner:
        inner = inner[1:]
    bounds, at, name = [], 0.0, name0 or ''
    for m in inner:
        if m['beat'] > at + 1e-6:
            bounds.append((at, m['beat'], name))
            at, name = m['beat'], m.get('name') or ''
        else:
            name = m.get('name') or ''
    bounds.append((at, end, name))
    return bounds


def _subtract(ranges, cuts):
    out = []
    for a, b in ranges:
        pieces = [(a, b)]
        for c0, c1 in cuts:
            nxt = []
            for p0, p1 in pieces:
                if c1 <= p0 + 1e-9 or c0 >= p1 - 1e-9:
                    nxt.append((p0, p1))
                    continue
                if c0 > p0 + 1e-9:
                    nxt.append((p0, c0))
                if c1 < p1 - 1e-9:
                    nxt.append((c1, p1))
            pieces = nxt
        out += [(p0, p1) for p0, p1 in pieces if p1 - p0 > 1e-3]
    return out


def _cover_clips(proj, notes, end, exclude=(), extra=None, prefix='自動'):
    """曲の頭（拍 0）から end まで、マーカーの区間ごとに隙間なくクリップを作る（ノーツの無い区間も空のクリップ。隙間＝NLM で消した所と
    見分けるため）。exclude（残したクリップ・消した所）の範囲は除いて分ける。extra は nlmf.items_before の形（範囲の中の物だけ入る）"""
    out = []
    for b, e, name in _marker_bounds(proj, end):
        for p0, p1 in _subtract([(b, e)], exclude):
            cl = {'beat': p0, 'len': p1 - p0, 'label': f'{prefix} {name}'.strip(), 'colHex': CLIP_COLOR,
                  'notes': [n for n in notes if p0 - 1e-9 <= n['beat'] < p1 - 1e-9]}
            if extra:
                cl['extra'] = extra
            out.append(cl)
    return out


KEPT_FIX_W = 20.0   # 残したノーツを決めたノーツとして流れに入れる重み（同じ振りの 4 の 5 倍。合わないと本物の譜面の振りが崩れる）
KEEP_REASON = {'fixed': '固定（名前に「固定」）', 'edited': '手で直した（中身が変わった）', 'user': '利用者のクリップ',
               'legacy': '前の形式で判定できない（--fresh で作り直すか、アプリの画面で捨てる）', 'cut': '「ここから」より前',
               'outside': '選んだ区間の外（そのまま）', 'keep': '「そのまま残す」の区間（前の譜面のまま）'}


def _keep_plan(proj, dkey, as_written, end, cut=None, only=None, keep=()):
    """結果のファイルを土台に作り直す時、何を残し何を作り直すか → dict:
    remove（作り直す＝消すクリップ）・kept [(クリップ, 理由)]・holes（消した所＝空のまま）・lane（作ったクリップのレーン）・
    exclude（新しいクリップを置かない範囲＝同じレーンの残したクリップ＋消した所）・blocked（打点を作らない範囲）・
    kept_notes（残したクリップの見えているノーツ・絶対拍）・carry（「ここから」をまたぐ作り直すクリップの前の部分＝新しいクリップへ移す）・
    split（区間の境目で分けた作ったクリップの残す側＝同じ中身の新しいクリップ）。
    only＝(拍の始まり, 終わり): 区間の外の作ったクリップは残し（理由 outside）、またぐ物は区間の境目で分けて外側をそのまま残す。
    keep＝意思入れの「そのまま残す」の区間 [(拍の始まり, 終わり)]: 区間の外と同じに、その中の作ったクリップの中身を残す（理由 keep・
    NLM の「固定」と同じ強さ。またぐ物は境目で分ける）"""
    cls, new_fmt, lane = nlmf.classify(proj, dkey, as_written)
    holes = nlmf.coverage_holes(proj, dkey, lane, end) if (lane is not None and new_fmt) else []
    remove, kept, span, split, split_ids = [], [], [], [], set()
    o0, o1 = only if only else (None, None)
    keep = intent.merge_spans([(float(a), float(b)) for a, b in keep or () if b - a > 1e-6])
    out_r = [(-1e9, o0), (o1, 1e9)] if only else []
    union = intent.merge_spans(out_r + keep)   # 残す範囲（区間の外・そのまま残す）を重ねてまとめた物
    for s, st in cls:
        b0, b1 = s.get('beat') or 0, (s.get('beat') or 0) + (s.get('len') or 0)
        if st == 'app':
            if cut is not None and b1 <= cut + 1e-9:
                kept.append((s, 'cut'))
                continue
            if any(a - 1e-9 <= b0 and b1 <= b + 1e-9 for a, b in union):
                kept.append((s, 'outside' if any(a < b1 - 1e-9 and b0 < b - 1e-9 for a, b in out_r) else 'keep'))
                continue
            remove.append(s)
            if cut is not None and b0 < cut - 1e-9:
                span.append(s['id'])
            for a, b in union:   # 残す範囲にかかる: その部分は同じ中身・同じ名前の新しいクリップで残す
                p0, p1 = max(a, b0), min(b, b1)
                if p1 - p0 > 1e-6:
                    split_ids.add(s['id'])
                    split.append({'beat': p0, 'len': p1 - p0, 'label': s.get('label') or nlmf.APP_LABEL, 'colHex': s.get('colHex') or CLIP_COLOR,
                                  'notes': [], 'extra': nlmf.items_between(s, p0, p1)})
        else:
            kept.append((s, st))
    has_items = lambda s: any(t and isinstance(t, list) and t[0] is not None and 0 <= t[0] < (s.get('len') or 0)
                              for k in nlmf.N_KEYS for t in (s.get('content') or {}).get(k) or [])
    rng = lambda s: ((s.get('beat') or 0), (s.get('beat') or 0) + (s.get('len') or 0))
    blocked = [rng(s) for s, st in kept if st != 'user' or has_items(s)] + holes
    exclude = [rng(s) for s, _ in kept if (s.get('track') or 0) == lane] + holes
    outside = [(0.0, o0), (o1, max(end, o1))] if only else []
    blocked += outside + keep
    exclude += outside + keep
    ids = {s.get('id') for s, _ in kept}
    kept_by = lambda b: any(a - 1e-9 <= b < c - 1e-9 for a, c in union)
    kept_notes = [n for n in nlmf.clip_notes(proj, dkey, include_muted=True)
                  if n['clip'] in ids or (n['clip'] in split_ids and kept_by(n['beat']))]
    rm = {s.get('id') for s in remove}
    in_keep = lambda b: any(a - 1e-9 <= b < c - 1e-9 for a, c in keep)
    carry = nlmf.items_before(proj, dkey, cut, ids=set(span)) if span else None
    return {'remove': remove, 'kept': kept, 'holes': holes, 'lane': lane, 'exclude': exclude, 'blocked': blocked,
            'kept_notes': kept_notes, 'carry': carry, 'new_fmt': new_fmt, 'split': split, 'only': only, 'keep': keep,
            'keep_notes': sum(1 for n in kept_notes if in_keep(n['beat']) and (n['clip'] in rm or n['clip'] in ids)),
            'prev_notes': [n for n in nlmf.clip_notes(proj, dkey, include_muted=True) if n['clip'] in rm and not kept_by(n['beat'])]}


def _kept_hits(notes, secs, tempo, after=None):
    """残したノーツ → 流れの計算に入れる打点（kept＝出力には入れない・fix＝その置き方に決める）。同じ色が 0.07 秒以内に続く物
    （スライダーの後ろ・重なり）は1つの振り"""
    by, last = {}, {}
    for n in sorted(notes, key=lambda n: (n['beat'], n['c'])):
        if (after is not None and n['beat'] < after - 1e-9) or n['c'] not in (0, 1):
            continue
        t = tempo.sec(n['beat'])
        if n['c'] in last and t - last[n['c']] < 0.07:
            continue
        last[n['c']] = t
        by.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    out = []
    for b, f in sorted(by.items()):
        si = next((i for i, s in enumerate(secs) if s.b0 - 1e-6 <= b < s.b1 - 1e-6), max(0, len(secs) - 1))
        h = rhythm.Hit(b, len(f), si, 0, 'kept', 1.0)
        h.kept, h.fix = True, f
        out.append(h)
    return out


def _song_setup(proj, stems):
    """プロジェクトと分けた音 → (BPM, 無音追加 ms, 曲の終わりの拍, 打点の候補, 寄せの情報)"""
    bpm = float(proj['bpm'])
    if proj.get('tempoParts'):
        sys.exit('テンポパートのある曲はまだ扱えない')
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    lead = round(-off * 1000) if off < 0 else 0
    import json
    secs = json.loads((Path(stems) / 'separate.json').read_text(encoding='utf-8'))['seconds']
    end = (secs + lead / 1000) * bpm / 60
    ons, info = rhythm.analyze(stems, bpm, lead)
    return bpm, lead, end, ons, info


def _put_new_lane(proj, dkey, notes, keep, end):
    """作ったノーツを一番上の新しいレーンへ（その難易度のノーツ系は先に消す・結果のファイルが無い／--fresh の時）。曲の頭から end まで
    隙間なくクリップを置く（_cover_clips）。keep（nlmf.items_before の戻り値・「ここから」より前）はクリップの中に残す。
    前は打点の確かめ用の rhythm コマンドの複数のレーンも置いていた（除いた）"""
    nlmf.clear_notes(proj, dkey)
    nlmf.put_note_lane(proj, {dkey: _cover_clips(proj, sorted(notes, key=lambda n: n['beat']), end, extra=keep or None, prefix='自動')})


AR = {0: '↑', 1: '↓', 2: '←', 3: '→', 4: '↖', 5: '↗', 6: '↙', 7: '↘', 8: '・'}


def _cyc_text(cyc):
    return ' '.join(f'{AR[d]}{x}{y}' for x, y, d in cyc)


def _bar_theme(bgd, bars, beat, variety=None):
    """小節ごとのテーマ（bgd＝form.mix_guides 等）から、その打点のテーマ。意思入れの型の変わり方（variety {'v', 'b0'}）:
    −1＝区間の最初の小節のテーマをずっと使う（覚えやすい）・+1＝小節の後ろ半分（2拍目から）は次の小節（無ければ前の小節）のテーマに替える"""
    bi = max(0, bisect.bisect_right(bars, beat + 1e-6) - 1)
    if variety and variety.get('v', 0) < 0:
        bi = max(0, bisect.bisect_right(bars, variety['b0'] + 1e-6) - 1)
    g = bgd.get(bi)
    if variety and variety.get('v', 0) > 0 and g and beat - bars[bi] >= 2 - 1e-6:
        alt = next((bgd[j] for j in (bi + 1, bi - 1) if j in bgd and bgd[j][0] != g[0]), None)
        if alt:
            g = alt
    return g


def _variant_guides(bgd, blocks, mu, seq, n, only=None):
    """別の案（compose --variant N）: 小節ごとのテーマ（bgd）を、記号ごとのテーマの並び（form.mix_guides）の中で n 個ずらした物に
    替える（only＝(拍の始まり, 終わり) と重なる小節だけ・無ければ全部）。曲の個性で選んだテーマの束はそのまま＝曲らしさを保って、区間の中の
    置き方だけ変える。種（--seed）を変えるだけだと、変わり方が曲・区間によってまちまち（曲C のサビでは案どうしの 7〜9 割のノーツが
    同じ・テーマの選び方の揺らぎが小さい）。ずらすと、どの区間でも案どうし・今の譜面と大きく違う（同じノーツは 1〜5 割）"""
    rot = lambda ts: ts[n % len(ts):] + ts[:n % len(ts)] if ts else ts
    alt = form.mix_guides(blocks, mu, {b: rot(ts) for b, ts in seq.items()})
    bars = mu['bars']
    return {i: (alt[i] if i in alt and i < len(bars) and _bar_in(bars, i, only) else g) for i, g in bgd.items()}


def _bar_in(bars, i, only):
    """小節 i が区間 only＝(拍の始まり, 終わり) と重なるか（None＝曲の全部）"""
    end = bars[i + 1] if i + 1 < len(bars) else bars[i] + 4
    return only is None or (bars[i] < only[1] - 1e-6 and end > only[0] + 1e-6)


def _library(a):
    """型の出どころ（--library＝曲ごとのライブラリの設定＝型のデータベース automap/library_db の絞り込み）→ 生の中身（片手の型・両手の組・
    ★・頻度・難しさ・1回だけの並び once 等）。データベースが使えなければ「型のデータベースが使えない（理由）」を出して止まる"""
    from . import library_use
    try:
        return library_use.export(a.library)
    except library_use.Unavailable as e:
        sys.exit(f'{e}。作り直しを止めた（型は BeatLeader のランク譜面の型のデータベースから作る・「準備と設定」で型のライブラリを確かめる）')


def _library_desc(a, lib):
    """報告の「型の出どころ」の文"""
    from . import library_use
    return library_use.describe(lib)


def _rare(v):
    """テーマを選び直す区間（_variant_ranges の要素）が「珍しい型まで」か（5 つ目の項目。無い＝案だけ＝前と同じ形）"""
    return len(v) > 4 and bool(v[4])


def _band(v):
    """テーマを選び直す区間（_variant_ranges の要素）の★の帯（6 つ目の項目・intent.band_of の値。無い＝None）"""
    return v[5] if len(v) > 5 else None


def _vr(b0, b1, k, why, rare, band):
    """_variant_ranges の要素（★の帯が無ければ前と同じ形＝案だけ 4 つ・珍しい型まで 5 つ）"""
    if band is not None:
        return (b0, b1, k, why, bool(rare), band)
    return (b0, b1, k, why, True) if rare else (b0, b1, k, why)


def _variant_ranges(it, cli_k, only, cli_rare=False, cli_band=None):
    """テーマを選び直す区間（「案 k」・「珍しい型まで」・「★の帯」）→ [(拍の始まり, 終わり（None＝曲の全部）, k（0＝案なし）, 出どころ
    [, True＝珍しい型まで[, ★の帯]])]。意思入れの表（表の順）の後に、compose の --variant K・--rare・--band（--only の区間・無ければ
    曲の全部）＝後の物が勝つ（同じ区間でまた別の案を作れる）"""
    out = [_vr(b0, b1, k, '意思入れ', rare, band) for b0, b1, k, rare, band in intent.theme_ranges(it, band=True)]
    if cli_k or cli_rare or cli_band is not None:
        why = ' '.join(x for x, on in (('--variant', cli_k), ('--rare', cli_rare), ('--band', cli_band is not None)) if on)
        b0, b1 = only if only else (None, None)
        out.append(_vr(b0, b1, cli_k, why, cli_rare, cli_band))
    return out


def _apply_variants(bgd, blocks, mu, vranges, pal_of):
    """区間の「案 k」・「珍しい型まで」・「★の帯」を小節ごとのテーマ（bgd）に効かせる（重なる小節は後の区間が勝つ。案・珍しい型まで・
    ★の帯は小節ごとに別々に）。案 k は intent.variant_spec の (ずらし n, 種 s): 種 s のテーマの並び（pal_of(s)＝style.pick を種 s で・
    (性格ごとの並び, 記号ごとの並び)）の中で n 個ずらしたテーマを、区間と重なる小節だけに使う。珍しい型までの小節は pal_of(s, True)
    （広げた型の束で選んだ並び・案が無ければ種 1 でずらし 0）。★の帯の小節は pal_of(s, 珍しい型まで, 帯)（★の帯を変えた型の束で選んだ並び）。
    曲全体の種・テーマの束は変えない（変えると区間の指示としては同じ物を作り直せない）。
    → (bgd, [(b0, b1, k, n, s, 出どころ, 小節の数, 珍しい型まで, ★の帯)])"""
    rep, eff = [], {}
    bars = mu['bars']
    for v in vranges:
        b0, b1, k, why = v[:4]
        rare, band = _rare(v), _band(v)
        only = None if b0 is None else (b0, b1)
        inb = [i for i in bgd if i < len(bars) and _bar_in(bars, i, only)]
        for i in inb:
            e = eff.setdefault(i, [0, False, None])
            if k:
                e[0] = k
            if rare:
                e[1] = True
            if band is not None:
                e[2] = band
        n, s = intent.variant_spec(k) if k else (0, 1)
        rep.append((b0, b1, k, n, s, why, len(inb), rare, band))
    alt, out = {}, dict(bgd)
    for i, (k, rare, band) in eff.items():
        key = (k, rare, json.dumps(band))
        if key not in alt:
            n, s = intent.variant_spec(k) if k else (0, 1)
            _, seq = pal_of(s, rare, band) if band is not None else pal_of(s, True) if rare else pal_of(s)
            alt[key] = _variant_guides(bgd, blocks, mu, seq, n)
        out[i] = alt[key].get(i, out[i])
    return out, rep


def _form_pick(g, fm, name, chosen, fspec, pal_of, rep):
    """同じ振りの形 (グループ g, 'A'|'B') のテーマ（形の設定 fspec に案 k・珍しい型まで・★の帯がある時）。小節のテーマの「案 k」と同じ決まり:
    intent.variant_spec の (ずらし n, 種 s) で、pal_of(s, 珍しい型まで, ★の帯)（小節のテーマと同じ口）の記号 name のテーマの並び（まとまりの
    頭からの並び）を n 個ずらした頭＝並びの n 番目。指示が無い形は手本の区間の記号の頭のテーマ（chosen・今まで通り）"""
    sp = fspec.get((g, fm))
    base = chosen[name]
    if not sp:
        return base
    n, s = intent.variant_spec(sp['k']) if sp['k'] else (0, 1)
    _, sq = pal_of(s, sp['rare'], sp['band']) if sp['band'] is not None else pal_of(s, True) if sp['rare'] else pal_of(s)
    ts = sq.get(name) or [base]
    th = ts[n % len(ts)]
    rep.append({'g': g, 'form': fm, 'sp': sp, 'th': th, 'base': base, 'n': n, 's': s})
    return th


def _motif_form_theme(m, name, chosen, fspec, pal_of, cache, rep):
    """同じ振りの打点の印 m（intent.apply の hit.motif）→ その形のテーマ（cache＝(グループ, 'A'|'B') → テーマ・rep＝報告の元）。
    A（手本の形）: 形の設定があれば _form_pick で選び直し、無ければ今まで通り（グループで最初の打点の区間の記号の頭のテーマ）。
    B（アレンジの形）: 自分の設定があればそれで選び直し（記号は B の最初の打点の区間）、無ければ A のテーマ（呼ぶ側が左右を入れ替える＝
    今まで通り・A を変えると B も変わる）。name＝今の打点の区間の記号（その形で最初に呼ばれた時だけ使う）"""
    g = m.get('group')
    fm = 'B' if m.get('variant') == 'b' else 'A'
    if (g, 'A') not in cache:   # ふつうは手本（A の1回目）の打点が最初。B が先に来ても A を先に決める（今までと同じ記号で）
        cache[(g, 'A')] = _form_pick(g, 'A', name, chosen, fspec, pal_of, rep)
    if fm == 'B' and (g, 'B') not in cache:
        if (g, 'B') in fspec:
            cache[(g, 'B')] = _form_pick(g, 'B', name, chosen, fspec, pal_of, rep)
        else:
            cache[(g, 'B')] = cache[(g, 'A')]
            if (g, 'A') in fspec:
                rep.append({'g': g, 'form': 'B', 'follow': True})
    return cache[(g, fm)]


def _form_theme_lines(rep, box, it):
    """報告の「- 同じ振りの形のテーマ: …」の行と、形の回ごとに設定が違う時の知らせ（どちらも無ければ空の並び）"""
    from . import library_use
    out, parts = [], []
    for r in rep:
        name = f'{r["g"]} {r["form"]}'
        if r.get('follow'):
            parts.append(f'{name} は A の型の左右入れ替え（今まで通り）')
            continue
        sp = r['sp']
        how = []
        if sp['k']:
            how.append(f'案 {sp["k"]}（ずらし {r.get("n", "-")}・種 {r.get("s", "-")}）')
        if sp['rare']:
            how.append('珍しい型まで')
        if sp['band'] is not None:
            g = _band_info(box, sp['band'], sp['rare'])
            how.append(f'{intent.band_text(sp["band"])}＝{library_use.stars_text(g["stars"])}' if g else
                       f'{intent.band_text(sp["band"])}（効かない: 型のデータベースが使えない）')
        th, base = r['th'], r['base']
        tx = lambda t: f'右 {_cyc_text(t.a)} ／ 左 {_cyc_text(t.b)}（{t.maps}・{t.src}）'
        parts.append(f'{name} は {tx(th)}＝{"・".join(how)} の並びから' + ('（既定と同じ型になった）' if th.key() == base.key() else f'（既定は {tx(base)}）')
                     + ('（アレンジの形なので左右を入れ替えて使う）' if r['form'] == 'B' else ''))
    if parts:
        out.append('- 同じ振りの形のテーマ: ' + '。'.join(parts))
    mixed = intent.form_mixed(it) if it else {}
    if mixed:
        out.append('- 同じ振りの形の設定が回ごとに違う: ' + '・'.join(
            f'{g} {fm} の拍 ' + '・'.join(f'{b0:g}' for b0, _ in lst) + ' に ' + '・'.join(sorted({k for _, ks in lst for k in ks})) + ' が無い'
            for (g, fm), lst in mixed.items()) + '（付いている回の物を形の全部に効かせた・同じ種類なら後の回の物。アレンジの形の量・元にする音は'
            '「アレンジの量」と手本の形で決まる）')
    return out


def _rare_lib(a, lib):
    """「珍しい型まで」の型の束の元（生の中身）: 曲のライブラリの設定が型の頻度を「定番まで」「よくあるまで」に絞っていれば、「珍しいまで」で
    書き出し直す（絞った書き出しには珍しい型が入っていない）。ほかは曲の型の出どころのまま（しきい値だけ theme.load_themes の freq で下げる）"""
    f = (lib.get('library') or {}).get('filters') or {}
    if f.get('freq') in ('定番', 'よくある'):
        from . import library_use
        g = dict(library_use.filters_of(a.library), freq='珍しい')
        try:
            return library_use.export(g)
        except library_use.Unavailable:   # 書き出し直せない時は曲の型の束のまま（しきい値だけ下げる）
            pass
    return lib


def _theme_of(g, cands):
    """小節のテーマ（(番号, {0: 左手の型, 1: 右手の型}, 変え方)）→ そのテーマ（cands の中で同じ変え方で同じ右手の型になる物・無ければ None）"""
    if not g:
        return None
    return next((t for t in cands if theme.transform(t, g[2])[0] == g[1][1]), None)


def _fix_motifs(hits, events, gen, prev=False):
    """同じ振り: 1回目の計算で決まった手本の区間のノーツを、ほかの区間の打点の Event.fix に入れる → {まとまり: 区間の拍の頭の一覧}。
    まとまり（motif['key']）は、そのまま＝グループ・アレンジ＝1回目・3回目…と2回目・4回目…（打点を足した形）の2つ。
    prev（前の譜面に寄せる作り直し・--prev-intent）: 前の譜面に寄せた手本の打点（Event.anchored＝自由に作る所の外）は、1回目の計算ではなく
    前の譜面の置き方（寄せた相手＝Event.fix）を手本にする。1回目の計算は写す側が自由だった前の版の 1回目と違う（写す側も前の譜面に弱く
    寄せる）ので、弱い寄せだけでは手本の置き方が前の版とずれ、写す側ごと変わった（作り物の曲で 4 ノーツ）"""
    at = {}
    for n in gen:
        at.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    model, groups = {}, {}
    for h, ev in zip(hits, events):
        m = getattr(h, 'motif', None)
        if m and m.get('occ') == 0:
            got = dict(ev.fix) if prev and getattr(ev, 'anchored', False) and ev.fix else at.get(round(h.beat, 4), {})
            model.setdefault(m.get('key'), {})[round(h.beat - m['b0'], 4)] = got
    for h, ev in zip(hits, events):
        m = getattr(h, 'motif', None)
        if not m or 'occ' not in m:
            continue
        groups.setdefault(m.get('key'), set()).add(m['b0'])
        got = (model.get(m.get('key')) or {}).get(round(h.beat - m['b0'], 4))   # 手本の区間も1回目の置き方に留める
        if got and m.get('mirror'):   # 左右反転の回（自動の同じ振り・automap/repeat.py）: 手を入れ替え・列を 3−x・向きを左右逆
            got = {1 - c: (3 - x, y, flow.MIRROR_D.get(d, d)) for c, (x, y, d) in got.items()}
        if got:
            ev.fix, ev.fix_w, ev.anchored = got, None, False   # 前の譜面に寄せた打点（重み 0.2）も同じ振りの重みに
    return {g: sorted(b) for g, b in groups.items() if len(b) > 1}


def _motif_breath(hits, events, gen, ons, models=False, allow=None, block=(), soften=None, model_heads=False):
    """同じ振りの区間の入りで、両手の振りの向きのそろい方（両手の最後の振りが同じ向きか）が手本と合わない所は、直前の打点を1つ抜くか
    （1拍以内の片手の打点＝掛け声の前の溜めになる）、空きが1拍以上あれば入りの前に1つ足す（拍の頭か裏の強い音）→ (抜いた拍, 足した拍)。
    手はそれぞれ振り下ろし・振り上げを交互にするので、両手の打点ではそろい方は変わらず（片方ずつ逆の向きの両手になる）、
    片手の打点のたびに入れ替わる＝どの手に割り振っても変えられない（曲C の 4 か所）。抜く・足すと、その後ろのそろい方が全部入れ替わる
    ので、曲の頭から順にたどる。長い間（reset_gap 秒）でも入れ替わったままとみる（そこで振りの順を戻すと NLM の譜面チェックの
    doubleDirectional が出た＝休みの後で同じ向き）。今のそろい方は gen（流れの計算の結果）から読む。
    NLM で直して残したクリップの入り（作ったノーツの後に残したノーツが始まる所）も同じように合わせる（向きは残したノーツそのものから）。
    allow＝(拍の始まり, 終わり): 選んだ区間だけ作り直す時。その外の打点は抜かず、外には足さない（外は今の譜面のまま）。
    block＝打点を作らない範囲（残したクリップ・そのまま残す区間・消した所＝_keep_plan の blocked）には足さない（足しても出力に入らず、
    そこで振りの向きが合わなくなった）。
    soften（派生の時だけ・リスト）: 抜けず足せない時（直前が1拍以内の両手）は、その両手を片手にする（片方の手の振りが1つ減る＝そろい方が
    入れ替わる）。片手にした拍は soften に足す（派生の桃源郷の Expert で、同じ振りの入りの1拍前の両手のせいで片手の向きが手本と逆になり、
    NLM の振りの警告が出た）。
    model_heads（派生の時だけ）: 自動の同じ振りの手本の回の入りも同じように合わせる。手本の置き方は1回目の計算に決めてあるので、その前に
    ある写す側の入りで抜く・足すと、後ろの手本の入りでそろい方が合わなくなった（派生で自動の同じ振りをそろえたら、Rain の Expert+ で手本の
    入りに NLM の振りの警告が 3 つ・2026-11-11）。利用者の同じ振りの手本には効かせない（ハロの Easy で「さあ進め」の回の中の警告が 3 → 6）"""
    ok_b = lambda b: (allow is None or allow[0] - 1e-9 <= b < allow[1] - 1e-9) and not any(r0 - 1e-9 <= b < r1 - 1e-9 for r0, r1 in block)
    at = {}
    for n in gen:
        at.setdefault(round(n['beat'], 4), {})[n['c']] = flow.parity_of(n['c'], n['d'])
    for h in hits:   # 残したノーツは本物の向き（流れの計算が合わせられなかった時も）
        if getattr(h, 'kept', False):
            at[round(h.beat, 4)] = {c: flow.parity_of(c, v[2]) for c, v in h.fix.items()}
    first = {}   # グループ → {手: 手本で最初の振りの向き（F/B）}
    for h in hits:
        m = getattr(h, 'motif', None)
        if m and m.get('occ') == 0:
            f = first.setdefault(m.get('key'), {})
            for c, q in at.get(round(h.beat, 4), {}).items():
                f.setdefault(c, q)
    need = {g: (f[0] == f[1]) for g, f in first.items() if len(f) == 2 and None not in f.values()}
    heads = {}
    for i, h in enumerate(hits):
        m = getattr(h, 'motif', None)
        if m and (m.get('occ') or (model_heads and m.get('auto') and 'occ' in m)) and m.get('key') in need:
            heads.setdefault((m['key'], m['b0']), i)
    if models:   # 両手から入る手本（アレンジの形）は、入りで両手の向きがそろっているように（片手は上・片手は下の両手にしない）
        heads, need = {}, {}
        for i, h in enumerate(hits):
            m = getattr(h, 'motif', None)
            if m and m.get('occ') == 0 and (m['key'], m['b0']) not in heads and not getattr(h, 'kept', False):
                heads[(m['key'], m['b0'])] = i
                if h.hands == 2:
                    need[m['key']] = True
        heads = {k: i for k, i in heads.items() if k[0] in need}
    else:   # 残したクリップの入り: 残したノーツの続きの最初の振り（手ごと）で、両手の向きのそろい方を決める
        for i, h in enumerate(hits):
            if getattr(h, 'kept', False) and i > 0 and not getattr(hits[i - 1], 'kept', False):
                f, j = {}, i
                while j < len(hits) and getattr(hits[j], 'kept', False):
                    for c, v in hits[j].fix.items():
                        f.setdefault(c, flow.parity_of(c, v[2]))
                    j += 1
                if len(f) == 2 and None not in f.values():
                    need[('kept', i)] = f[0] == f[1]
                    heads[(('kept', i), h.beat)] = i
    head_at = {i: g for (g, _), i in heads.items()}
    strength = {}
    for k in ('kick', 'snare', 'vocal', 'other'):
        for o in ons.get(k, []):
            strength[round(o.beat, 4)] = max(strength.get(round(o.beat, 4), 0.0), o.s)
    cut, add, last, flip, prev = set(), [], {}, False, None
    for i, (h, ev) in enumerate(zip(hits, events)):
        if i in head_at and len(last) == 2 and prev is not None:
            rel = (last[0] == last[1]) != flip
            gap = h.beat - hits[prev].beat
            if rel != need[head_at[i]]:
                if gap <= 1.01 and hits[prev].hands == 1 and not getattr(hits[prev], 'motif', None) and hits[prev].src not in ('lead', 'kept') \
                        and ok_b(hits[prev].beat):
                    cut.add(prev)
                    flip = not flip
                elif soften is not None and gap <= 1.01 and hits[prev].hands == 2 and not getattr(hits[prev], 'motif', None) \
                        and not getattr(hits[prev], 'kept', False) and ok_b(hits[prev].beat):
                    hits[prev].hands = events[prev].hands = 1
                    hits[prev].force_dbl = False
                    soften.append(hits[prev].beat)
                    flip = not flip
                elif gap >= 1.5 - 1e-6 and any(ok_b(b) for b in (h.beat - 1.0, h.beat - 0.5) if b - hits[prev].beat >= 0.5 - 1e-6):
                    spb = (ev.sec - events[prev].sec) / gap
                    pos = max((b for b in (h.beat - 1.0, h.beat - 0.5) if b - hits[prev].beat >= 0.5 - 1e-6 and ok_b(b)),
                              key=lambda b: (strength.get(round(b, 4), 0.0), b == h.beat - 1.0))
                    add.append((i, pos, ev.sec - (h.beat - pos) * spb))
                    flip = not flip
        for c, q in at.get(round(h.beat, 4), {}).items():
            if q is not None:
                last[c] = q
        prev = i
    cut_beats = sorted(hits[j].beat for j in cut)
    add_beats = sorted(b for _, b, _ in add)
    ops = [(j, None) for j in cut] + [(i, (b, t)) for i, b, t in add]
    for j, new in sorted(ops, key=lambda o: (o[0], o[1] is None), reverse=True):
        if new is None:
            del hits[j], events[j]
        else:
            b, t = new
            hd = hits[j]
            q = rhythm.Hit(b, 1, hd.sec_i, hd.phr_i, 'lead', strength.get(round(b, 4), 0.3))
            hits.insert(j, q)
            events.insert(j, flow.Event(b, t, 1, events[j].gid, events[j].cyc))
    return cut_beats, add_beats


def _kept_miss(hits, gen):
    """残したノーツのうち、流れの計算がその置き方にできなかった物の数（＝つなぎ目で振りの向きが合っていない）"""
    at = {}
    for n in gen:
        at.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    return sum(1 for h in hits if getattr(h, 'kept', False)
               for c, v in h.fix.items() if at.get(round(h.beat, 4), {}).get(c) != v)


def _motif_match(hits, events, gen, groups):
    """手本どおりに置けたノーツの数 → ({グループ: (区間の拍の頭, 合った数, 狙った数)}, 合わないノーツがあった区間の拍の頭)"""
    at = {}
    for n in gen:
        at.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    out, bad = {}, set()
    for h, ev in zip(hits, events):
        m = getattr(h, 'motif', None)
        if m and ev.fix and m.get('key') in groups:
            b0s, ok, n = out.get(m['key'], (groups[m['key']], 0, 0))
            got = at.get(round(h.beat, 4), {})
            k = sum(got.get(c) == v for c, v in ev.fix.items())
            out[m['key']] = (b0s, ok + k, n + len(ev.fix))
            if k < len(ev.fix) and m.get('occ'):
                bad.add(m['b0'])
    return out, sorted(bad)


def _prev_plan(a, plan, it, mu, end, only, tempo):
    """前の譜面に寄せるか・どこを自由に作るか → {at: {拍: {手: (x, y, d)}}（寄せる相手＝前の結果の作ったノーツ）, free: [(b0, b1)]
    （指示が変わった所）, what: [何が変わったか], why: 寄せない理由}。--prev-intent が無ければ {}（今まで通り・報告にも出さない）。
    寄せない: --no-anchor（画面の「前の譜面に寄せない」・前の版が分からない等）・結果のファイルが無い・全体の設定（自動の休み）を変えた・
    曲の全部の案（--variant・--rare を --only 無しで）"""
    if getattr(a, 'no_anchor', None):
        return {'why': a.no_anchor}
    if not getattr(a, 'prev_intent', None):
        return {}
    if not plan:
        return {'why': '--fresh（入力を土台にした）' if getattr(a, 'fresh', False) else '結果のファイルが無い（前の譜面が無い）'}
    cli = bool(getattr(a, 'variant', 0) or getattr(a, 'rare', False) or _cli_band(a) is not None)
    if cli and not only:
        return {'why': '曲の全部の案（--variant・--rare・--band）'}
    prev = intent.load(a.prev_intent)
    cur = it or {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}}
    free, glob, what = intent.changed_ranges(prev, cur, (mu or {}).get('bars') or (), end)
    if glob:
        return {'why': '全体の設定（自動の休み）を変えた', 'what': what}
    if cli:   # 別の案（--only --variant・--rare・--band）: 選んだ区間は自由に（区間の外はもともと今の譜面のまま）
        free = intent.merge_spans(free + [tuple(only)])
        what.append('別の案の区間')
    at, last = {}, {}
    for n in sorted(plan['prev_notes'], key=lambda n: (n['beat'], n['c'])):   # 同じ色が 0.07 秒以内に続く物は1つの振り（_kept_hits と同じ）
        if n['c'] not in (0, 1):
            continue
        t = tempo.sec(n['beat'])
        if n['c'] in last and t - last[n['c']] < 0.07:
            continue
        last[n['c']] = t
        at.setdefault(round(n['beat'], 4), {})[n['c']] = (n['x'], n['y'], n['d'])
    if not at:
        return {'why': '前の譜面に作り直すノーツが無い', 'what': what}
    return {'at': at, 'free': free, 'what': what, 'n': 0}


SYNC_MAX = 0.03   # 寄せる所の打点を前の譜面にそろえる時の、違う打点の割合の上限（越えたら前の譜面が古い＝そろえない）


def _prev_sync(hits, anc, ons, margin):
    """前の譜面に寄せる前に打点をそろえる → 打点。anc に何をしたかを書く（sync_cut・sync_add・fix）。
    ① 寄せる所（自由に作る所の前後 margin 拍の外）の打点を前の譜面の打点にそろえる: 同じ振りの入りの前で抜いた・足した打点
    （_motif_breath）は 1回目の計算の後に決まるので、そろえないと途中の計算で打点の数が前の譜面と奇数だけ違い、振りの向きの位相を
    曲の頭から入れ替えた（指示を変えずに作り直しても曲の全部が変わった）。違いが多い（SYNC_MAX）時は前の譜面が古いとみてそろえない。
    ② 自由に作る所（前後 margin 拍を含む）の振りの数（片手 1・両手 2）の偶奇を前の譜面に合わせる: 手はそれぞれ振りの向きを交互にする
    ので、振りの数が奇数だけ違うと、どちらかの手の位相が入れ替わったまま戻らない（前に寄せる重みがあると、入れ替える所を自由な所の
    外＝曲の頭の方に選ぶこともあった）。合わない時は、自由な所の終わりの近くの弱い片手の打点を1つ抜く（無ければ1つ足す）。
    前か後ろに寄せる打点が無い所（曲の頭・終わり）は位相が自由なので合わせない。
    ①では片手・両手も前の譜面に合わせる（sync_hands）: 同じ音楽の区間の組から外した小節の写す側は、写しでない素の打点に戻り
    片手・両手が前の譜面（手本の写し）と違う（作り物の曲の拍 42 が片手 → 両手・こだまの拍 154・158 が両手 → 片手）。拍だけそろえると
    振りの数が変わり、その後ろの振りの向きの位相が入れ替わった（2026-11-10）"""
    at = anc['at']
    spans = intent.merge_spans([(x - margin, y + margin) for x, y in anc['free']])
    inside = lambda b: any(x - 1e-6 <= b < y - 1e-6 for x, y in spans)
    fixed = lambda h: getattr(h, 'kept', False) or getattr(h, 'motif', None)
    have = {round(h.beat, 4) for h in hits}
    drop = [h for h in hits if not inside(h.beat) and not fixed(h) and round(h.beat, 4) not in at]
    add_b = sorted(b for b in at if not inside(b) and b not in have)
    n_anch = sum(1 for h in hits if not inside(h.beat) and not getattr(h, 'kept', False))
    hand = [h for h in hits if not inside(h.beat) and not fixed(h) and round(h.beat, 4) in at and len(at[round(h.beat, 4)]) != h.hands]
    if len(drop) + len(add_b) + len(hand) > max(4, SYNC_MAX * n_anch):
        anc['sync_skip'] = len(drop) + len(add_b) + len(hand)
    else:
        for h in hand:
            h.hands = len(at[round(h.beat, 4)])
            if h.hands == 1:
                h.force_dbl = False
        anc['sync_hands'] = sorted(h.beat for h in hand)
        hits = [h for h in hits if h not in drop]
        for b in add_b:
            nx = next((h for h in hits if h.beat > b), hits[-1] if hits else None)
            q = rhythm.Hit(b, len(at[b]), nx.sec_i if nx else 0, nx.phr_i if nx else 0, 'lead', 0.3)
            hits.append(q)
        hits.sort(key=lambda h: h.beat)
        anc['sync_cut'], anc['sync_add'] = sorted(h.beat for h in drop), add_b
    anc['fix'] = []
    _prev_parity(hits, None, anc, ons, margin)
    return hits


def _prev_parity(hits, events, anc, ons, margin):
    """自由に作る所（前後 margin 拍を含む）の振りの数（片手 1・両手 2）の偶奇を前の譜面に合わせる（_prev_sync の②）→ 変えた数。
    events があれば同じ所を一緒に抜く・足す（hits と events は同じ並び）。同じ振りの入りで打点を抜く・足す（_motif_breath）と偶奇が
    変わるので、その後にもう一度呼ぶ。合わせた所は anc['fix'] に足す"""
    at = anc['at']
    spans = intent.merge_spans([(x - margin, y + margin) for x, y in anc['free']])
    fixed = lambda h: getattr(h, 'kept', False) or getattr(h, 'motif', None) or h.src == 'lead'
    strength = {}
    for k in ('kick', 'snare', 'vocal', 'other'):
        for o in ons.get(k, []):
            strength[round(o.beat, 4)] = max(strength.get(round(o.beat, 4), 0.0), o.s)
    n = 0
    for x, y in spans:
        if not any(b < x - 1e-6 for b in at) or not any(b >= y - 1e-6 for b in at):
            continue
        n_new = sum(h.hands for h in hits if x - 1e-6 <= h.beat < y - 1e-6 and not getattr(h, 'kept', False))
        n_old = sum(len(f) for b, f in at.items() if x - 1e-6 <= b < y - 1e-6)
        if (n_new - n_old) % 2 == 0:
            continue
        end = y - margin   # 自由に作る所の終わり（この近くで合わせる＝つなぎ目）
        cut = [h for h in hits if x - 1e-6 <= h.beat < y - 1e-6 and h.hands == 1 and not fixed(h)
               and not getattr(h, 'force_dbl', False) and not getattr(h, 'force_strong', False)]
        n += 1
        if cut:
            h = min(cut, key=lambda h: (not (end - 2 - 1e-6 <= h.beat < y - 1e-6), h.s + strength.get(round(h.beat, 4), 0.0), -h.beat))
            j = hits.index(h)
            del hits[j]
            if events is not None:
                del events[j]
            anc['fix'].append(('抜いた', h.beat))
            continue
        bs = sorted(h.beat for h in hits)
        cand = [b for b, v in strength.items() if x - 1e-6 <= b < y - 1e-6 and abs(b * 2 - round(b * 2)) < 1e-6
                and all(abs(b - q) >= 0.5 - 1e-6 for q in bs)]
        if not cand:
            anc['fix'].append(('合わせられない', x))
            continue
        b = max(cand, key=lambda b: (strength[b], b))
        j = next((i for i, h in enumerate(hits) if h.beat > b), len(hits) - 1)
        nx = hits[j]
        hits.insert(j, rhythm.Hit(b, 1, nx.sec_i, nx.phr_i, 'lead', strength[b]))
        if events is not None:
            e1 = events[j]
            e0 = events[j - 1] if j > 0 else None
            t = e1.sec - (e1.beat - b) * ((e1.sec - e0.sec) / (e1.beat - e0.beat) if e0 and e1.beat > e0.beat else 0.5)
            events.insert(j, flow.Event(b, t, 1, e1.gid, e1.cyc))
        anc['fix'].append(('足した', b))
    return n


def _prev_anchor(hits, events, at, free, weight, margin):
    """前の結果の置き方（at）に弱く寄せる（Event.fix・重み weight・Event.anchored＝寄せた印）→ 寄せた打点の数。自由に作る所（free の
    前後 margin 拍）・ほかの決めたノーツがある打点・残したノーツの打点は寄せない。同じ振りの打点は寄せる（1回目の計算を前の譜面に
    近づける＝手本の置き方も前の譜面から取れる。_fix_motifs が同じ振りの重みで決め直す。寄せないと、同じ振りの決めが入る前の計算で
    手の割り振りが曲の頭から変わった）。
    自由に作る所の前後 margin 拍（つなぎ目のゆとり）にある同じ振りの打点は寄せる（2026-11-10）: そこが手本だと写す側（離れた所）まで
    変わった（作り物の曲で休みの小節の次から始まる組の手本の頭 拍 14〜16 → 写す側 46〜48。利用者「ミラー側へコピーする必要はない」）"""
    spans = [(x - margin, y + margin) for x, y in free]
    n = 0
    for h, ev in zip(hits, events):
        if ev.fix or getattr(h, 'kept', False):
            continue
        if any(x - 1e-6 <= ev.beat < y - 1e-6 for x, y in (free if getattr(h, 'motif', None) else spans)):
            continue
        f = at.get(round(ev.beat, 4))
        if f:
            ev.fix, ev.fix_w, ev.anchored = dict(f), weight, True
            n += 1
    return n


def _prev_groups(a, out, it, mu, end, only):
    """前の譜面に寄せる作り直し（--prev-intent）で、前の版のくり返しの組を引き継ぐための元 → {groups（repeat.parse_line・None＝分からない）,
    chains（echo.parse_table・None＝分からない）, touch（指示が変わった所）} か None（寄せない時）。読むのは前の版の報告（_prev_kimes と同じ所）。
    作業中（2026-11-09・棚上げの 2）: 区間の指示を 1 つ足すと、自動の同じ振り（repeat.find は利用者の区間を避ける）と続けて左右反転
    （echo.unify の続きの選び方）が曲の全部で組み直しになり、変えた所の外も変わった"""
    if only or not getattr(a, 'prev_intent', None) or getattr(a, 'no_anchor', None) or getattr(a, 'fresh', False):
        return None
    if getattr(a, 'variant', 0) or getattr(a, 'rare', False) or _cli_band(a) is not None:
        return None
    cur = it or {'ranges': [], 'line': [], 'auto_rest': {'on': False, 'b': None}}
    free, glob, _ = intent.changed_ranges(intent.load(a.prev_intent), cur, (mu or {}).get('bars') or (), end)
    if glob:
        return None
    md = None
    for p in [out.with_suffix('.report.md')] + ([Path(a.prev_intent).with_name(Path(a.prev_intent).name[:-len('.intent.json')] + '.report.md')]
                                                if Path(a.prev_intent).name.endswith('.intent.json') else []):
        try:
            md = p.read_text(encoding='utf-8')
            break
        except OSError:
            continue
    if md is None:
        return None
    return {'groups': repeat.parse_line(md), 'chains': echo.parse_table(md), 'loops': loops.parse_line(md), 'touch': list(free)}


def _carry_groups_line(pg, rgroups, echo_rep, lp_plan):
    """報告の「前の版のくり返しの組を引き継いだ」の行（前の譜面に寄せて前の版の組が分かった時だけ・作業中）"""
    if not pg:
        return ''
    parts = []
    if pg.get('groups') is not None:
        parts.append(f'同じ音楽の区間 {len(pg["groups"])} 組 → {len(rgroups or [])} 組')
    if pg.get('chains') is not None and echo_rep is not None:
        parts.append(f'続けて左右反転の続き {len(pg["chains"])} → {len(echo_rep.get("chains") or [])}')
    if pg.get('loops') is not None and lp_plan:
        parts.append(f'往復の区間 {len(pg["loops"])} のうち {lp_plan.get("kept", 0)} をそのまま・全部で {len(lp_plan["spans"])}')
    if not parts:
        return ''
    drop, grown = pg.get('dropped') or [], pg.get('grown') or []
    eg = (echo_rep or {}).get('regrown') or []
    return ('- 前の版のくり返しの組を引き継いだ（指示が変わった所にかかる組だけ組み直す）: ' + '・'.join(parts)
            + (f'。組から外した小節 拍 {"・".join(f"{a:g}〜{b:g}" for a, b in intent.merge_spans(drop))}' if drop else '')
            + (f'。指示が無くなった所で組を元の形に戻した小節 拍 {"・".join(f"{a:g}〜{b:g}" for a, b in intent.merge_spans(grown))}' if grown else '')
            + (f'。元の形に戻した続けて左右反転の続き 拍 {"・".join(f"{s:g}〜{s + U * k:g}" for s, U, k in eg)}' if eg else ''))


def _anchored_spans(free, margin):
    """前の譜面に寄せる所（自由に作る所 free の前後 margin 拍の外）→ [(拍, 拍)]。そこは打点を前の譜面にそろえてある（_prev_sync）ので、
    同じ振りの入りの前を抜く・足す（_motif_breath）をしない（試し）。しないと作り直すたびに入りの前の打点を 1 つずつ抜き続け、こだまの写しで
    拍 249〜267 が毎回変わった（抜いた拍 267.25 → 267 …）"""
    out, lo = [], -1e9
    for x, y in intent.merge_spans([(x - margin, y + margin) for x, y in free]):
        if x > lo:
            out.append((lo, x))
        lo = max(lo, y)
    out.append((lo, 1e9))
    return out


def _fresh_like(events):
    """前の譜面に寄せた打点（Event.anchored）の決めを外した打点の写し（同じ並び・ほかの印はそのまま）。短い往復（loops.plan）を、前の譜面に
    寄せない作り（1 回目）と同じ印の状態で選ぶため。そのままだと寄せた打点（決めたノーツとみる）と受け渡しの carry（前の譜面の同じ手の続き＝
    使いたい手）で往復を置ける所が無くなり、新しく作った譜面を指示を変えずに初めて作り直すと往復の所が変わった（作り物の曲で 4 ノーツ）"""
    out = []
    for ev in events:
        g = copy.copy(ev)
        if getattr(ev, 'anchored', False):
            g.fix, g.fix_w, g.anchored = None, None, False
        out.append(g)
    return out


def _anchor_line(anc, a):
    """報告の「前の譜面に寄せた」の行（--prev-intent・--no-anchor が無ければ空）"""
    if not anc:
        return ''
    if anc.get('why'):
        return f'- 前の譜面に寄せなかった（{anc["why"]}）。全部を新しく作った'
    fs = '・'.join(f'{x:g}〜{y:g}' for x, y in anc['free'])
    return (f'- 前の譜面に寄せた（重み {a.anchor_w:g}・寄せた打点 {anc.get("n", 0)}）。自由に作った所: '
            + (f'拍 {fs}（前後 {kime.ANCHOR_MARGIN:g} 拍も）＝' + '・'.join(anc.get('what') or []) if anc['free'] else '無し（指示は前の作り直しと同じ）')
            + (f'。新しい決めの前後 {anc["released"]} 打点は寄せない' if anc.get('released') else '')
            + (f'。寄せる所の打点を前の譜面にそろえた（抜いた 拍 {"・".join(format(b, "g") for b in anc["sync_cut"]) or "なし"}・'
               f'足した 拍 {"・".join(format(b, "g") for b in anc["sync_add"]) or "なし"}'
               + (f'・片手と両手を合わせた 拍 {"・".join(format(b, "g") for b in anc["sync_hands"])}' if anc.get('sync_hands') else '') + '）'
               if anc.get('sync_cut') or anc.get('sync_add') or anc.get('sync_hands') else '')
            + (f'。前の譜面と打点が {anc["sync_skip"]} 違うので打点はそろえない（前の譜面が古い）' if anc.get('sync_skip') else '')
            + ('。振りの数の偶奇を合わせた: ' + '・'.join(f'拍 {b:g} を{w}' if w != '合わせられない' else f'拍 {b:g}〜は合わせられない'
                                                    for w, b in anc['fix']) if anc.get('fix') else ''))


def _keep_line(keeps, plan):
    """報告の「そのまま残す」の行"""
    if not keeps:
        return ''
    fs = '・'.join(f'{x:g}〜{y:g}' for x, y in intent.merge_spans(keeps))
    if not plan:
        return f'- そのまま残す（拍 {fs}）は効かない: 結果のファイルが無い（前の譜面が無い）'
    return f'- そのまま残す: 拍 {fs} は前の譜面のまま（ノーツ {plan.get("keep_notes", 0)}・NLM の「固定」と同じ）'


LEFT_FAST_W = 1.0   # 片手だけで速く続ける振りを左手に置く減点の重み（右利きの譜面を基本に・docs/方針.md 6.25）
HAND_TECH_K = 0.3   # 角度・移動の減点の左右の倍率の差（左手 1＋k・右手 1−k・技術的に難しい振りを右手に・6.25）
# 長い間（flow.Style.reset_gap 秒）の後で振りの順をやり直す（同じ向きを続ける）減点。NLM はやり直しを間の長さによらず振りの警告にする。
# 前は flow の既定の 3 で、先読み（flow_nb._look_tables）がやり直しを見込むようにしたら（2026-11-10）、同じ振りの写しの頭の向きを合わせる
# やり直しが増え、11 曲の NLM の振りの警告が 11 → 24 になった。30 で 13・60 で 11（直す前と同じ・派生の derive.W_RESET も 60）
W_RESET = 60.0


def _swings_per_sec(hits, tempo):
    """打点の並び → 1秒の振りの数（両手同時は 2）。ランク譜面の物差し（stats.spread の sps）と同じ数え方の近似＝両手の広がりの目標の帯を決める"""
    if len(hits) < 2:
        return None
    span = tempo.sec(hits[-1].beat) - tempo.sec(hits[0].beat)
    return sum(h.hands for h in hits) / span if span > 0 else None


def _njs_formula(proj, dkey, tempo, offset=None, settle=False):
    """難易度の式の NJS（★・BPM・難易度・automap/njs.py）→ (値か None, 決め方の説明)。★は nlm-rating で今の中身（今の NJS）を測る
    （無い PC は1秒のノーツの式）。ノーツが 2 つより少なければ (None, 理由)。settle＝式の値が今の NJS と違えば、その速さで測り直す
    （njs.settle・3D で決めた値が入った基準・決めた値から作った派生の式の値を、決めた値の速さの★でずらさない）"""
    from . import diffs, njs, rating
    if offset is None:
        offset = njs.setting()[1]
    name = diffs.name_of(dkey)
    ns = nlmf.clip_notes(proj, dkey, include_muted=True)
    if len(ns) < 2:
        return None, 'ノーツが少ない'
    span = tempo.sec(ns[-1]['beat']) - tempo.sec(ns[0]['beat'])
    nps = len(ns) / span if span > 0 else None
    if settle:
        def at(v):
            r = rating.measure_proj(njs.with_njs(proj, dkey, v), name)
            return r.get('stars') if r.get('ok') else None
        cur = rating.njs_of(proj, dkey, name)[0]
        return njs.settle(name, proj['bpm'], lambda v: at(v) if v != cur else _stars(rating.measure_proj(proj, name)), cur, nps=nps, offset=offset)
    stars = _stars(rating.measure_proj(proj, name))
    return njs.suggest(name, proj['bpm'], stars=stars, nps=nps if stars is None else None, offset=offset)


def _stars(r):
    return r.get('stars') if r.get('ok') else None


def _set_njs(proj, dkey, tempo, base=None, base_formula=None, dv=None):
    """_njs_value（NJS）→ 報告の行に見え始める距離を足す（njs.apply・put がその NJS で狙いの JD になるオフセットも書いた＝njs.fix_jd・
    2026-11-10）。例「- NJS: 16（…から式で）・JD 19.1m・反応 0.57 秒（オフセット −0.623 拍）」"""
    from . import njs
    line = _njs_value(proj, dkey, tempo, base=base, base_formula=base_formula, dv=dv)
    if not line or '決められなかった' in line:
        return line
    t = njs.jd_text(njs.fix_jd(proj, dkey))
    return line + (f'・{t}' if t else '')


def _fix_jd_others(proj, dkey):
    """基準の作り直し: ほかの難易度（アプリが NJS を書いた物）のオフセットも、その NJS で狙いの JD に（njs.fix_all・NLM で決めた
    オフセットは触らない）→ 報告の行（書いた物が無ければ ''）"""
    from . import diffs, njs
    if not njs.setting()[0]:
        return ''
    got = njs.fix_all(proj, skip={dkey})
    if not got:
        return ''
    return '- 見え始める距離（JD）をほかの難易度でも整えた: ' + '・'.join(
        f'{diffs.TEXT[diffs.name_of(k)]} {before:.1f}→{r["jd"]:.1f}m' for k, before, r in got)


def _njs_value(proj, dkey, tempo, base=None, base_formula=None, dv=None):
    """書いた難易度の NJS を★・BPM・難易度から決めて njsCfg に書く（automap/njs.py・docs/アプリ仕様.md 20 節）→ 報告の行。
    ★は nlm-rating で測る（無い PC は1秒のノーツの式）。NLM で利用者が決めた NJS は上書きしない。config の njs_auto: false なら書かない。
    base＝3D で決めた基準の NJS（作業ファイルの njs.base・compose --njs-base・2026-11-09）: 基準（dv が無い）はその値をそのまま（★は測らない・
    njs_auto に依らない）・派生（dv）は基準の NJS＋（派生の式 − 基準の式）（njs.from_base・base_formula＝基準の式の値・無ければ基準の★を測る）。
    派生の元にする基準の NJS は最後に決めた方（njs.base_value）: 基準が NLM で直されていればその値（base が無くても）・無ければ base"""
    from . import njs
    on, off = njs.setting()
    src = '3d'
    if dv is not None:   # 派生: 基準が NLM で直されていれば、その値を元に（3D で決めた値より後＝NLM の値が勝つ）
        base, src = njs.base_value(proj, dv['bkey'], base)
    if base is not None and dv is None:   # 基準: 3D で決めた値そのまま（ON の後で NLM で直された値は触らない）
        if not nlmf.clip_notes(proj, dkey, include_muted=True):
            return ''
        e = (proj.get('njsCfg') or {}).get(dkey)
        if njs.user_value(e) is not None:
            return f'- NJS: {e["njs"]:g}（NLM で直した値のまま＝最後に決めた方・3D で決めた基準の NJS は {base:g}）'
        st, cur = njs.apply(proj, dkey, float(base), force=True)
        return f'- NJS: {cur:g}（3D で決めた基準の NJS・式は使わない）'
    if not on:
        return ''
    v, how = _njs_formula(proj, dkey, tempo, off, settle=base is not None)   # 決めた値からの派生は式の値の速さの★で（展開し直してもずれない）
    if v is None:
        return '' if how == 'ノーツが少ない' else f'- NJS: 決められなかった（{how}）'
    if base is not None:   # 派生: 基準の決めた値から式の上下の間隔を保ってずらす
        fb = base_formula
        if fb is None:
            fb, how_b = _njs_formula(proj, dv['bkey'], tempo, off, settle=True)
            if fb is None:
                return f'- NJS: 決められなかった（基準の式の値: {how_b}）'
        d = njs.from_base(base, v, fb)
        st, cur = njs.apply(proj, dkey, d, force=True)
        if st == 'kept':
            return f'- NJS: {cur:g}（NLM で決めた値のまま・基準の NJS からなら {d:g}）'
        return (f'- NJS: {cur:g}（{njs.BASE_FROM[src]} {float(base):g}＋式の差 {v - float(fb):+g}＝{how}から式で {v:g}・'
                f'基準の式 {float(fb):g}）')
    st, cur = njs.apply(proj, dkey, v)
    if st == 'kept':
        return f'- NJS: {cur:g}（NLM で決めた値のまま・式なら {v:g}＝{how}）'
    return f'- NJS: {cur:g}（{how}から式で' + (f' {v:g}・前に書いた値と 0.5 以内なので前のまま）' if st == 'same' else '）')


OLD_SUBS = ('意思入れ', '試作5', '試作4')   # 前に作り直し・取り込みが既定で入れていたサブタイトル（2026-11-09 利用者「書き出しの曲の情報に意思入れが入っているのを消して」・
# 試作5＝取り込みの最初の作り直しが入れていた＝Beat Saber に「試作5」で出た）


def _clear_old_subtitle(proj):
    """曲のサブタイトルが前の既定（OLD_SUBS）のままなら空にする（利用者が入れたサブタイトル・書き出すフォルダ名は触らない）。
    前は書き出すフォルダ名に -4・-5・-i、サブタイトルに「試作4」等を入れていた（試作4 と v0.1 の譜面を並べて遊ぶため・試作4 の道は除いた）"""
    info = proj.get('info') or {}
    if info.get('_songSubName') in OLD_SUBS:
        info['_songSubName'] = ''
    for v in ((proj.get('infoGraph') or {}).get('nodes') or {}).values():
        if v.get('t') == 'meta' and (v.get('data') or {}).get('sub') in OLD_SUBS:
            v['data']['sub'] = ''


def _fit_amount(a, hits, ons, secs, bars, end, tempo, avoid=()):
    """量の目安（--nps-target・automap/amount.py）: 自動の打点（意思入れの前）の1秒のノーツの数を目安に合わせる →
    (打点, 報告の数（line＝報告の行）か None, 意思入れの区間の量 ±に掛ける関数か None)。目安が無ければ何もしない（答えを変えない）"""
    t = getattr(a, 'nps_target', None)
    if not t:
        return hits, None, None
    from . import amount
    out, info = amount.fit(hits, ons, secs, bars, end, t, tempo, avoid)
    info['line'] = amount.report_line(info, getattr(a, 'nps_from', None))
    return out, info, amount.make_scale(ons, secs, bars, end, tempo, info['ratio'], avoid)


def _derive_check(a):
    """派生の道（--derive-from）の引数を確かめる → (基準の難易度, 派生の難易度, 量の割合)。一緒に使えない物は理由を出して止める"""
    from . import diffs
    try:
        base, target = diffs.name_of(a.derive_from), diffs.name_of(a.diff)
    except ValueError as e:
        sys.exit(str(e))
    if base == target:
        sys.exit(f'--diff（派生の難易度）と --derive-from（基準の難易度）が同じ: {base}')
    for flag, on in (('--prev-intent', a.prev_intent), ('--only', a.only), ('--variant', a.variant), ('--rare', a.rare),
                     ('--band', a.band), ('--fresh', a.fresh), ('--no-anchor', a.no_anchor)):
        if on:
            sys.exit(f'派生（--derive-from）は {flag} と一緒に使えない（派生は基準から作り直すだけ・区間の案や前の譜面への寄せは基準で）')
    r = diffs.ratio(base, target) if a.ratio is None else float(a.ratio)
    if not 0.1 <= r <= 4.0:
        sys.exit(f'--ratio は 0.1〜4.0（基準の1秒のノーツに対する割合）: {r:g}')
    return base, target, r


def _derive_lane(proj, bkey, plan):
    """派生の作ったクリップのレーン: 派生に作ったクリップがあればそのレーン・無ければ基準の作ったクリップのレーン（レーンを増やさない＝
    ほかの難易度の番号をずらさない）・それも無ければ基準のノーツのクリップの一番多いレーン。どれも無ければ None（一番上に足す）"""
    if plan['lane'] is not None:
        return plan['lane']
    _, _, lane = nlmf.classify(proj, bkey)
    if lane is None:
        cnt = {}
        for s in nlmf.note_clips(proj['difficulties'][bkey]):
            cnt[s.get('track') or 0] = cnt.get(s.get('track') or 0, 0) + 1
        lane = max(cnt, key=lambda k: (cnt[k], -k)) if cnt else None
    if lane is not None:
        rng = lambda s: ((s.get('beat') or 0), (s.get('beat') or 0) + (s.get('len') or 0))
        plan['exclude'] = plan['exclude'] + [rng(s) for s, _ in plan['kept'] if (s.get('track') or 0) == lane]
    return lane


def _base_report(a, out):
    """派生: 基準の作り直しの報告の中身（--base-report・無ければ結果のファイルの隣の報告）か None"""
    from . import diffs
    for p in ([Path(a.base_report)] if getattr(a, 'base_report', None) else []) + [diffs.report_path(out)]:
        try:
            return p.read_text(encoding='utf-8')
        except OSError:
            continue
    return None


def _derive_groups(a, out, dv, at, used, bars):
    """派生でそろえる同じ音楽の区間の組（derive.rep_groups → check_groups＝基準でそろっている回だけ）を dv に控える"""
    from . import derive
    if not getattr(a, 'auto_repeat', True):
        dv.update(groups=[], groups_src=None, groups_dropped=[])
        return
    gs, src = derive.rep_groups(_base_report(a, out), used, bars)
    dv['groups'], dv['groups_dropped'] = derive.check_groups(gs, at)
    dv['groups_src'] = src


def _derive_hits(a, proj, bkey, auto, it, secs, ons, mu, tempo, end, plan, dv):
    """派生の打点: 結果のファイルの基準の難易度の今のノーツ（NLM で手で直した所も）を打点にし、下は間引く・上は足す（automap/derive.py）。
    派生の難易度の NLM で直して残したクリップ・消した所（plan の blocked）の打点は先に抜く（残したノーツは後で決めたノーツとして入る）。
    同じ音楽の区間の組（dv['groups']）の回の打点には自動の同じ振りの印（足す・間引くはどの回も同じ所・置き方は手本の回に写す）"""
    from . import derive
    base_notes = nlmf.clip_notes(proj, bkey, include_muted=True)
    if not base_notes:
        sys.exit(f'基準の難易度 {dv["base"]} にノーツが無い')
    at = derive.swings(base_notes, tempo)
    _derive_groups(a, dv['out'], dv, at, dv.get('used_groups'), mu['bars'])
    hits = derive.mark_groups(derive.base_hits(at, auto, secs, ons, it), dv['groups'])
    blk = lambda b: any(r0 - 1e-9 <= b < r1 - 1e-9 for r0, r1 in plan['blocked'])
    hits = [h for h in hits if not blk(h.beat)]
    bars = mu['bars']
    brk = dv['brk'] = [(br['beat'], br['beat'] + br['len']) for br in mu['breaks'] if br['kind'] == 'all' or br['len'] >= 1.0]
    if dv['groups']:   # 写す側の回の打点を手本の回と同じ所に（基準の入りの前に足した打点などで少し違う）
        hits, dv['unify_del'], dv['unify_add'] = derive.unify_groups(hits, dv['groups'], tempo, secs, list(plan['blocked']) + brk)
    r = dv['ratio']
    pre = list(hits)   # 間引く・足す前（同じ音楽の区間の組の片手の数の偶奇を戻す元・thin／thicken は写しを直す）
    if r < 1 - 1e-6:   # 間の難易度・下の難易度があれば入れ子に（間に無い打点から・下にある打点は後に間引く）
        nest = lambda d, memo: _derive_nest(proj, dv, auto, it, secs, ons, bars, end, tempo, at, d, memo)
        up, lo, dv['up'], dv['lo'] = nest(dv['target'], {})
        dv['up_at'] = up
        hits, info = derive.thin(hits, r, bars, end, tempo, ons, dv['base'], dv['target'], (up, lo) if (up or lo) else None)
    elif r > 1 + 1e-6:
        # 足さない範囲: NLM で直した所・利用者の同じ振りの区間・途切れ（自動の同じ振りの組は thicken がどの回も同じ所に足す）
        avoid = list(plan['blocked']) + [(b0, b1) for b0, b1, m in derive.motif_regions(auto, it) if not m.get('auto')] + brk
        hits, info = derive.thicken(hits, r, bars, end, tempo, ons, secs, dv['base'], dv['target'], avoid, dv['groups'])
    else:
        v = derive.amount.measure(hits, tempo)
        info = {'target': v, 'before': v, 'after': v, 'k': 1.0, 'del': 0, 'conv': 0, 'add': 0, 'short': 0, 'dbl': 0, 'far': False,
                'dbl_share': None}
    if dv['groups'] and abs(r - 1) > 1e-6:
        hits, dv['parity_fix'] = derive.keep_parity(hits, pre, dv['groups'], tempo)
        info['after'] = derive.amount.measure(hits, tempo)
    dv.update(at=at, base_notes=base_notes, info=info)
    return hits


def _derive_with(a):
    """--derive-with（同じ展開で一緒に作る派生 '難易度=割合,…'）→ {難易度: 割合}"""
    from . import diffs
    out = {}
    for x in (getattr(a, 'derive_with', None) or '').split(','):
        if x.strip():
            try:
                d, r = x.split('=')
                out[diffs.name_of(d)] = float(r)
            except ValueError:
                sys.exit(f'--derive-with は「難易度=割合」をコンマで: {x}')
    return out


def _derive_nest(proj, dv, auto, it, secs, ons, bars, end, tempo, at, target, memo):
    """派生 target の入れ子の相手 → (上の振りの拍, 下の振りの拍, 上の名前, 下の名前)（derive.nest_pick で選ぶ相手）。上が同じ展開で一緒に作る
    派生（--derive-with・割合 < 1）なら、できた譜面を待たずに、その派生の compose と同じ決まりで間引いた打点で見込む（_derive_predict・
    並べて作れる。流れの計算の中で同じ振りの入りに抜く・足す打点は見込まない）"""
    from . import derive, diffs
    w = {d: r for d, r in dv['with'].items() if r < 1 - 1e-6}
    up, lo = derive.nest_pick(proj, dv['base'], target, w)
    beats = lambda d: set(derive.swings(nlmf.clip_notes(proj, diffs.key(d), include_muted=True), tempo)) if d else None
    if up in w:
        if up not in memo:
            memo[up] = _derive_predict(proj, dv, auto, it, secs, ons, bars, end, tempo, at, up, w[up], memo)
        return memo[up], beats(lo), up, lo
    return beats(up), beats(lo), up, lo


def _derive_predict(proj, dv, auto, it, secs, ons, bars, end, tempo, at, d, r, memo):
    """同じ展開で一緒に作る派生 d（割合 r）の振りの拍の見込み: d を作る compose と同じく、基準の打点から d の残したクリップ・消した所の
    打点を抜き、d の入れ子の相手で間引いた打点の拍＋d の残したノーツの振りの拍"""
    from . import derive, diffs
    k = diffs.key(d)
    pl = _keep_plan(proj, k, dv['as_written'], dv['end_clip']) if k in proj['difficulties'] else None
    gs = dv.get('groups') or []
    hits = derive.mark_groups(derive.base_hits(at, auto, secs, ons, it), gs)   # 同じ組を同じ決まりで（d の compose の _derive_hits と同じ）
    if pl:
        hits = [h for h in hits if not any(r0 - 1e-9 <= h.beat < r1 - 1e-9 for r0, r1 in pl['blocked'])]
    if gs:
        hits, _, _ = derive.unify_groups(hits, gs, tempo, secs, list(pl['blocked'] if pl else []) + dv.get('brk', []))
    up, lo, _, _ = _derive_nest(proj, dv, auto, it, secs, ons, bars, end, tempo, at, d, memo)
    out, _ = derive.thin(hits, r, bars, end, tempo, ons, dv['base'], d, (up, lo) if (up or lo) else None)
    if gs:
        out, _ = derive.keep_parity(out, hits, gs, tempo)
    got = {round(h.beat, 4) for h in out}
    if pl:
        got |= set(derive.swings(pl['kept_notes'], tempo))
    dv.setdefault('predicted', []).append(d)
    return got


def _derive_repeat_line(dv):
    """派生の報告の「同じ音楽の区間」の行: 派生でそろえた組（画面の帯が読む・repeat.report_line と同じ形）。そろえた組が無ければその訳"""
    if dv.get('groups'):
        return repeat.report_line(dv['groups'])
    if dv.get('groups_src') is None:
        return ''
    return ('- 同じ音楽の区間（自動の同じ振り・docs/方針.md 6.31）: 派生でそろえた組は無い（'
            + ('基準の組は回どうしの譜面が違う＝NLM で直した等' if dv.get('groups_dropped') else '基準に組が無い') + '）')


def _derive_group_line(dv, final, tempo):
    """派生の節の「同じ音楽の区間」の行: そろえた組と回・足した数・できた譜面で手本と同じ回（打点・置き方）・外した回"""
    from . import derive
    gs = dv.get('groups') or []
    if dv.get('groups_src') is None or not (gs or dv.get('groups_dropped')):
        return []
    sw = derive.swings(final, tempo)
    ms = [derive.occ_match(sw, g['occ'][0], o, kind) for g in gs for o, kind in zip(g['occ'][1:], g['kinds'][1:])]
    n_occ = sum(len(g['occ']) for g in gs)
    info = dv.get('info') or {}
    add = f'・組の中に足した打点 {info["g_add"]}（どの回も同じ所）' if info.get('g_add') else ''
    line = (f'- 同じ音楽の区間（{dv["groups_src"]}）: {len(gs)} 組 {n_occ} 回を基準の繰り返しのままそろえた（足す・間引くはどの回も同じ所・置き方は'
            f'手本の回に写す）{add}' if gs else f'- 同じ音楽の区間（{dv["groups_src"]}）: そろえた組は無い')
    if ms:
        line += (f'。できた譜面で写す側の回が手本と同じ割合（回ごとの平均）: 打点 {sum(r for r, _ in ms) / len(ms):.0%}・'
                 f'置き方 {sum(p for _, p in ms) / len(ms):.0%}')
    if dv.get('groups_dropped'):
        line += '。基準で手本と違うので外した回: ' + '・'.join(f'{n} 拍 {b:g}（打点 {r:.0%}・置き方 {p:.0%} 同じ）' for n, b, r, p in dv['groups_dropped'])
    return [line]


def _derive_lines(dv, final, tempo, proj, plan, n_anc, a, lib):
    """派生の報告の「派生」の節"""
    from . import derive, diffs
    b, t, info = dv['base'], dv['target'], dv['info']
    mb, md = derive.measures(dv['base_notes'], tempo), derive.measures(final, tempo)
    sp = derive.same_place(dv['at'], final, tempo)
    hr = lambda k: derive.HUMAN[k][t] / derive.HUMAN[k][b]
    pc = lambda v: '-' if v is None else f'{v:.0%}'
    sec = lambda v: '-' if v is None else f'{v:.3f} 秒'
    how = ('間引いた（弱い打点から・小節ごとに同じ倍率 ' + f'{info["k"]:.2f}・消した {info["del"]}・両手を片手に {info["conv"]}）'
           if dv['ratio'] < 1 - 1e-6 else
           f'足した（拾った候補から・小節ごとの倍率 {info["k"]:.2f}・足した {info["add"]}・片手を両手に {info["dbl"]}）'
           if dv['ratio'] > 1 + 1e-6 else '同じ量（打点はそのまま）')
    lines = ['## 派生（基準の譜面から）', '',
             f'- 基準: {diffs.TEXT[b]}（{dv["bkey"]}・作り直していない）→ 派生: {diffs.TEXT[t]}（{dv["dkey"]}'
             + ('・無いか空だったので、この作り直しで置いた＝書き出す印も付けた' if dv['new'] else '') + '）',
             f'- 量の割合 {dv["ratio"]:g}（{"既定＝1段 " + format(diffs.STEP_PCT, "g") + "%" if a.ratio is None else "--ratio"}）: '
             f'打点の1秒のノーツ {info["before"]:.2f} → {info["after"]:.2f}（目安 {info["target"]:.2f}）。{how}',
             f'- 1秒のノーツ（譜面全体・残したクリップも）: 基準 {mb["nps"]:.2f} → 派生 {md["nps"]:.2f}（{md["nps"] / max(1e-9, mb["nps"]):.2f} 倍）',
             f'- 派生の打点のうち基準にもある打点 {sp["common"]:.1%}（打点 {sp["events"]}・基準 {sp["base_events"]}）。'
             f'基準と同じ置き方のノーツ: 拍・手・マス・向き {sp["same"]:.1%}・拍・手・マス {sp["cell"]:.1%}（基準の置き方に寄せた打点 {n_anc}・重み {a.anchor_w:g}）',
             *([f'- 入れ子: 間の難易度 {diffs.TEXT[dv["up"]]} に無い打点から間引いた（派生の打点のうち {diffs.TEXT[dv["up"]]} にもある '
                f'{sum(1 for x in derive.swings(final, tempo) if x in dv["up_at"]) / max(1, sp["events"]):.1%}'
                + ('＝一緒に作る派生なので、その派生と同じ決まりで間引いた打点で見込んだ（できた譜面を待たない）' if dv['up'] in dv.get('predicted', ()) else '')
                + '）'] if dv.get('up') else []),
             *([f'- 入れ子: 下の難易度 {diffs.TEXT[dv["lo"]]} の打点は後に間引いた'] if dv.get('lo') else []),
             f'- 両手（打点あたり）: 基準 {pc(mb["double"])} → 派生 {pc(md["double"])}（人の譜面の比 {hr("double"):.2f} 倍の目安 '
             f'{pc(mb["double"] * hr("double"))}）',
             f'- 打点の間が 1/4 拍: 基準 {pc(mb["quarter"])} → 派生 {pc(md["quarter"])}（人の譜面の比の目安 {pc(mb["quarter"] * hr("quarter"))}）',
             f'- 同じ手の振りの間: 一番短い {sec(mb["gap_min"])} → {sec(md["gap_min"])}・速い方から1割 {sec(mb["gap_q10"])} → {sec(md["gap_q10"])}'
             f'（人の譜面 {derive.HUMAN["fast"][b]:g} → {derive.HUMAN["fast"][t]:g} 秒・流れの計算の最短の間 {dv["min_gap"]:g} 秒）',
             f'- 型の範囲: {_library_desc(a, lib)}',
             '- 決め（珍しい型）は派生では新しく入れない（基準の決めのノーツは、基準の置き方に寄せる仕組みで残りやすい）',
             *_derive_group_line(dv, final, tempo)]
    if info.get('far'):
        lines.append(f'- **目安 {info["target"]:.2f} に対して {info["after"]:.2f}**（'
                     + (_short_text(info) if info['after'] < info['target'] else '間引けない打点（小節の頭・区間の頭・途切れの戻り・両手）が多い') + '）')
    return lines + ['']


def _short_text(info):
    """足りなかった訳の文（derive.thicken の why）"""
    w = info.get('why') or {}
    out = ['拾える打点が足りない']
    if w.get('ceil') and info['target'] > w['ceil']:
        out.append(f'1/4 拍の升を全部埋めても 1秒 {w["ceil"]:.2f}（足すのは 1/4 拍の目盛りまで・打点の間は 1/4 拍より詰めない）')
    if w.get('avoid', 0) >= 0.05:
        out.append(f'足さない範囲（利用者の同じ振りの区間・途切れ・NLM で直した所）が曲の {w["avoid"]:.0%}')
    if w.get('pool'):
        out.append(f'拾った音の立ち上がり（半拍・1/4 拍の目盛り）{w["pool"]} のうち {w["used"]} に打った＝残りは前後が詰まる所'
                   if w['used'] < w['pool'] else f'拾った音の立ち上がり（半拍・1/4 拍の目盛り）{w["pool"]} を全部使った')
    return out[0] + ('：' + '・'.join(out[1:]) if len(out) > 1 else '')


def cmd_compose(a):
    if not (a.form and a.style):   # 試作1〜4 の道（--form・--style 無し）は除いた（docs/除いた物.md）
        sys.exit('compose は --form --style と一緒に使う（試作1〜4 の作り方は除いた・docs/除いた物.md）')
    from . import library_use
    # 型の出どころ: --library が無い・前の形（出どころに手元の譜面）はランク譜面へ読み替える（library_use.migrate_filters・設定の無い曲は
    # 新しい曲の既定）。時期が自動なら、この曲の手本の時期に置き換える（library_use.resolve・曲の名前と種）
    lf = library_use.migrate_filters(library_use.filters_of(a.library) if getattr(a, 'library', None) else None)
    a.library = json.dumps(library_use.resolve(lf, Path(a.stems).name, a.seed), ensure_ascii=False)
    dv = None
    if getattr(a, 'derive_from', None):   # 派生の道（難易度の展開・docs/アプリ仕様.md 17 節・automap/derive.py）
        b_, t_, r_ = _derive_check(a)
        dv = {'base': b_, 'target': t_, 'ratio': r_, 'soft': []}
    if a.anchor_w is None:
        from . import derive
        a.anchor_w = derive.ANCHOR_W if dv else kime.ANCHOR_W
    out = _out_for(a, f'{Path(a.input).stem.split(".")[0]}.{"intent" if a.intent else "style"}-s{a.seed}.nlmf')
    regen = out.exists() and not getattr(a, 'fresh', False)   # 結果のファイルを土台に作り直す（NLM で直した所を残す）
    if getattr(a, 'variant', 0) < 0:
        sys.exit('--variant は案の番号（1 から・0＝無し）')
    only, it = None, None
    if getattr(a, 'only', None):   # 選んだ区間だけ作り直す（外は結果のファイルの今の譜面のまま）
        try:
            only = tuple(sorted(float(x) for x in a.only.split(',')))
        except ValueError:
            sys.exit('--only は「拍の始まり,拍の終わり」')
        if len(only) != 2 or only[1] - only[0] <= 1e-6:
            sys.exit('--only は「拍の始まり,拍の終わり」')
        if not regen:
            sys.exit('選んだ区間だけ作り直すのは、結果のファイルがある時だけ（--fresh とは一緒に使えない）')
    as_written = regen and not _edited_since_written(out)       # こちらで書いたまま（前の形式のファイルの判定に使う）
    proj, src, note = _open_project(a, out)
    if src != Path(a.input):   # 結果のファイルを土台にした時、解析の帯の目盛りが今の無音追加と違えば（取り消し等で古い帯に戻った）入力の帯を使う
        base = nlmf.load(a.input)
        lead_now = round(-(((proj.get('graph') or {}).get('song') or {}).get('offset') or 0) * 1000)
        g_now = ((proj.get('analysis') or {}).get('grid') or {}).get('leadMs')
        g_in = ((base.get('analysis') or {}).get('grid') or {}).get('leadMs')
        if g_now != lead_now and g_in == lead_now and base.get('bpm') == proj.get('bpm'):
            proj['analysis'] = base['analysis']
    if dv:   # 派生: 基準の難易度は読むだけ。派生の難易度が無ければ空の難易度を足す（書き出す印も付ける・diffs.ensure）
        from . import diffs
        dv['bkey'] = diffs.key(dv['base'])
        if dv['bkey'] not in proj['difficulties']:
            sys.exit(f'基準の難易度が無い: {diffs.TEXT[dv["base"]]}（ある物: {", ".join(proj["difficulties"])}）')
        old = proj['difficulties'].get(diffs.key(dv['target']))
        dv['new'] = old is None or not diffs.notes_in(old)   # 無い・空の難易度＝派生を初めて置く（書き出す印も付ける）
        dkey = dv['dkey'] = diffs.ensure(proj, dv['target'], export=dv['new'])
    else:
        dkey = nlmf.diff_key(proj, a.diff)
    tempo = nlmf.tempo_of(proj)
    with audio.kept():   # 打点の候補・曲の中身を初めて作る時（取り込みの最初の譜面）、同じ分けた音を読み直さない
        bpm, lead, end, ons, info = _song_setup(proj, a.stems)
        # 曲の流れの表（まとまり・くり返しの記号・盛り上がりの段階・途切れ）
        ons_d = json.loads((Path(a.stems) / 'onsets.json').read_text(encoding='utf-8'))['onsets']
        mu = music.analyze(a.stems, ons_d, bpm, lead, int(end))
    if a.intent:
        it = intent.load(a.intent)
    vs_on, vs_off = intent.vsnap_ranges(it)
    vpull = None
    if vs_on or getattr(a, 'vocal_pull', True):   # 歌を拍に寄せる（迷った歌の打点をキック・スネアの鳴る目盛りへ・rhythm.vocal_pull・docs/方針.md 6.34）
        ons, vpull = rhythm.vocal_pull(ons, bpm, vs_on, auto=getattr(a, 'vocal_pull', True), skip=vs_off)
    groove_rep, repeat_groups, echo_rep = None, None, None
    blocks = form.build(mu, proj.get('markers') or [], int(end))
    secs = form.sections(blocks, proj.get('markers') or [], end)
    hits = rhythm.choose_hits(ons, secs, plan=form.plan(blocks))
    if getattr(a, 'groove', True):   # リズムの型を使い回す（automap/groove.py・docs/方針.md 6.31）
        hits, groove_rep = groove.regularize(hits, mu, secs, ons)
    hits = form.apply_breaks(hits, mu)
    auto_hits = list(hits)   # 緩急の役はこの打点で決める（量の設定・意思入れ・派生の間引きの前＝どの難易度でも同じ役）
    hits, amt, amt_scale = _fit_amount(a, hits, ons, secs, mu['bars'], end, tempo, [
        (br['beat'], br['beat'] + br['len']) for br in mu['breaks'] if br['kind'] == 'all' or br['len'] >= 1.0])
    irep = None
    if a.intent:   # 意思入れ（区間の指示・全体の量のライン）
        n_auto = len(hits)
        hits, irep = intent.apply(hits, ons, secs, it, mu['bars'], int(end), scale=amt_scale, line=False)
    avoid = [(float(r['b0']), float(r['b1'])) for r in ((it or {}).get('ranges') or [])]   # 利用者の意思入れの区間（自動のくり返しを重ねない）
    pg = _prev_groups(a, out, it, mu, end, only) if regen and not dv else None   # 前の版のくり返しの組（作業中・棚上げの 2）
    rgroups = []
    if getattr(a, 'auto_repeat', True):
        if pg and pg['groups'] is not None:
            rgroups, pg['dropped'] = repeat.carry(pg['groups'], pg['touch'], mu)
            # 指示が無くなった小節は、分かれた組を元の形に戻す（2026-11-10 利用者・まっさらに作った組がその組の続きなら伸ばす）
            rgroups, pg['grown'] = repeat.regrow(rgroups, repeat.find(mu, avoid), pg['touch'], avoid, mu)
        else:
            rgroups = repeat.find(mu, avoid)
    if getattr(a, 'echo', True) and not dv:   # 続けて左右反転のセットのリズムをそろえる（automap/echo.py・自動の同じ振りの前＝手本の区間の続きも写る・
        # 手本の境目と写す側にはかけない）
        hits, echo_rep = echo.unify(hits, mu, ons, avoid, [g['occ'] for g in rgroups], keep=pg['chains'] if pg else None,
                                    touch=pg['touch'] if pg else (), grow=repeat.gone(pg['touch'], avoid) if pg else ())
    if getattr(a, 'auto_repeat', True):   # 同じ音楽の区間は譜面ごとくり返す（automap/repeat.py・利用者の意思入れの区間とは重ねない）
        hits, repeat_groups = repeat.apply(hits, rgroups, secs)
    if a.intent and it['line']:   # 全体の量のライン: 自動のくり返しの後（前は意思入れの中で、くり返しが写し直して戻った）・くり返しの回は同じ位置で
        inner = [[(s + j * U, s + (j + 1) * U) for j in range(k)] for s, U, k in ((echo_rep or {}).get('chains') or [])]
        outer = [list(g['occ']) for g in (repeat_groups or [])] + intent.motif_families(it, hits)
        hits, lrow = intent.apply_line(hits, it, mu['bars'], int(end), ons, secs, inner, outer)
        if lrow:
            irep.append(lrow)
    hits = [h for h in hits if tempo.sec(h.beat) >= 1.6]   # 曲の頭が早すぎない（譜面チェックの hotStart は 1.5 秒）
    cut = rhythm.regen_from(proj.get('markers')) if (src != Path(a.input) or regen) and not dv else None   # 「ここから」: 結果のファイルの前の部分を残す（派生では使わない）
    keep, init = None, None
    if cut is not None:
        keep = nlmf.items_before(proj, dkey, cut)
        kept_notes = [{'beat': t[0], 'x': t[1], 'y': t[2], 'c': t[3], 'd': t[4]} for t in keep['notes']]
        init = flow.init_from(kept_notes, tempo)
        hits = [h for h in hits if h.beat >= cut - 1e-6]
    end_clip = math.ceil(end / 4) * 4
    keeps = intent.keep_ranges(it) if not dv else []   # 意思入れの「そのまま残す」（前の譜面のノーツを NLM の「固定」と同じに残す・基準だけ）
    plan = _keep_plan(proj, dkey, as_written, end_clip, cut, only, keeps) if (regen or dv) else None
    if dv:   # 派生: 打点を基準の譜面から（下は間引く・上は足す）。派生の難易度の NLM で直した所は下の決まりで残る
        dv['lane'] = _derive_lane(proj, dv['bkey'], plan)
        dv.update({'as_written': as_written, 'end_clip': end_clip, 'with': _derive_with(a)})   # 一緒に作る派生の見込みに使う
        dv.update(out=out, used_groups=repeat_groups)   # 同じ音楽の区間の組（基準の報告が読めない時はこの作り直しで選び直した組）
        hits = _derive_hits(a, proj, dv['bkey'], hits, it, secs, ons, mu, tempo, end, plan, dv)
    if plan:   # NLM で直した所（残したクリップ・消した所）には打たない・残したノーツから 1/8 拍未満にも打たない。残したノーツは決めたノーツとして流れへ
        kb = sorted(n['beat'] for n in plan['kept_notes'])
        near = lambda b: any(abs(b - x) < 0.125 - 1e-9 for x in kb[max(0, bisect.bisect_left(kb, b - 0.2)):bisect.bisect_right(kb, b + 0.2)])
        blk = lambda b: any(r0 - 1e-9 <= b < r1 - 1e-9 for r0, r1 in plan['blocked'])
        in_keep = lambda b: any(r0 - 1e-9 <= b < r1 - 1e-9 for r0, r1 in plan['keep'])
        # 選んだ区間の外・そのまま残す区間にある同じ振りの手本: 手本の打点の印を、同じ拍の残したノーツへ移す（ほかの区間の写しが、今の譜面の手本の置き方に合う）
        out_model = {round(h.beat, 4): h.motif for h in hits if ((only and blk(h.beat)) or in_keep(h.beat))
                     and (getattr(h, 'motif', None) or {}).get('occ') == 0}
        hits = [h for h in hits if not blk(h.beat) and not near(h.beat)]
        kh = _kept_hits(plan['kept_notes'], secs, tempo, cut)
        for h in kh:
            if round(h.beat, 4) in out_model:
                h.motif = out_model[round(h.beat, 4)]
        hits = sorted(hits + kh, key=lambda h: h.beat)
    prow, tilt, feats, rl_plan = {}, None, None, None
    vranges, vrep = _variant_ranges(it, getattr(a, 'variant', 0), only, getattr(a, 'rare', False), _cli_band(a)), None   # 「案 k」・「珍しい型まで」・「★の帯」
    lib = _library(a)   # 型の出どころ（生の中身。データベースなら 1回だけの並び once 等も入っている）
    themes = theme.load_themes(lib)
    rare_box = {}   # 珍しい型まで広げた型の束（要る時だけ作る）

    def rare_themes():
        if 'themes' not in rare_box:
            rlib = _rare_lib(a, lib)
            rare_box['themes'] = theme.load_themes(rlib, freq='珍しい')
            rare_box['min'] = theme.thresholds(rlib, '珍しい')
            rare_box['again'] = rlib is not lib
        return rare_box['themes']
    band_box = {'libs': {}, 'got': {}}   # ★の帯を変えた型の束（帯ごとに1回書き出す・同じ帯は使い回す）
    fspec = intent.form_specs(it)   # 同じ振りの形の「案 k」・「珍しい型まで」・「★の帯」（形の型を選び直す）
    sps = _swings_per_sec(hits, tempo)   # 1秒の振りの数（両手の広がりの目標を密度＝★に合わせる・docs/方針.md 6.21）
    # 試作5: 曲の個性で傾けた狙いで、性格ごとに PALETTE 個のテーマ・小節ごとに回す（form.mix_guides）。
    # テーマを選ぶ時の揺らぎの種は曲ごと（曲の名前と種・style.habit_seed）。前はどの曲も種 1 の同じ揺らぎで、同じ型の一覧なら同じ型が
    # 同じだけ得をし、曲どうしが似た（docs/方針.md 6.22）
    tseed = style.habit_seed(Path(a.stems).name, a.seed)
    chosen, second, pal, order, feats, tilt = style.pick(blocks, ons_d, bpm, themes, seed=tseed, k=PALETTE, lib=lib, sps=sps)
    gd = form.guides(secs, blocks, chosen)   # まとまりの頭のテーマ（小節のテーマが無い打点の控え・報告の区間の表）
    bgd = form.mix_guides(blocks, mu, second)   # 小節ごとのテーマ
    by_seed = {(1, False, None): (pal, second)}

    def pal_of(s, rare=False, band=None):
        bt = _band_themes(a, lib, band, rare, band_box) if band is not None else None   # ★の帯（使えなければ None＝帯は効かない）
        key = (s, rare, json.dumps(band) if bt else None)
        if key not in by_seed:   # 種 s（曲の種から数える）で選び直したテーマの並び。曲全体の種・テーマの束は変えない
            ts = bt['themes'] if bt else rare_themes() if rare else themes
            _, sq, pl, *_ = style.pick(blocks, ons_d, bpm, ts, seed=tseed + s - 1, k=PALETTE, lib=bt['lib'] if bt else lib, sps=sps)
            by_seed[key] = (pl, sq)
        return by_seed[key]
    if vranges:   # 案 k・珍しい型まで: 区間と重なる小節のテーマを、案 k の種（珍しい型までは広げた束）のテーマの並びから
        bgd, vrep = _apply_variants(bgd, blocks, mu, vranges, pal_of)
        rare_box['pals'] = [pl for (_, r, _), (pl, _) in by_seed.items() if r]
        band_box['pals'] = {b: [pl for (_, _, b2), (pl, _) in by_seed.items() if b2 == b] for (_, _, b) in by_seed if b}
    if getattr(a, 'relief', False):   # 緩急（試し・automap/relief.py）: 息つぎのまとまりを易しい型のくり返しに
        stars = {i for i, s_ in enumerate(secs) if any(t == '★' for _, t, _ in s_.tags)}
        rl_plan = relief.plan(blocks, auto_hits, it, lib, themes, tilt, sps, tseed, stars)
        bgd = relief.apply_guides(bgd, blocks, rl_plan, mu)
    prow = form.pitch_rows(hits, blocks)
    # 前の譜面に寄せる（docs/アプリ仕様.md 11 節）: 前の作り直しの表（--prev-intent）と比べて指示が変わった所（と前後 ANCHOR_MARGIN 拍）は
    # 自由に作り、ほかの打点は前の結果（結果のファイルの作ったノーツ）の置き方に弱く寄せる（決めたノーツ・重み --anchor-w）。
    # 寄せる所の打点は前の譜面の打点にそろえ、自由に作る所は振りの数の偶奇を前の譜面に合わせる（_prev_sync）
    anc = _prev_plan(a, plan, it, mu, end, only, tempo)
    if rl_plan and anc.get('at'):   # 息つぎのまとまりは前の譜面に寄せず、自由に作る
        anc['free'] = intent.merge_spans(list(anc['free']) + rl_plan['spans'])
        anc['what'] = list(anc.get('what') or []) + ['緩急の息つぎ']
    # 前の版の組から外した小節（写す側）は自由に作らず、ほかの変えていない所と同じに前の譜面に弱く寄せる（2026-11-09 利用者「休みは特徴的な
    # ところや意図的なところに入れたいので、ミラー側へコピーする必要はない」）
    if anc.get('at'):
        hits = _prev_sync(hits, anc, ons, kime.ANCHOR_MARGIN)
    prev_k, prev_src = _prev_kimes(a, out) if (regen and lib.get('once') and not dv) else (None, None)   # 前の版の決め（報告を書き換える前に読む）
    motif_theme = {}   # 同じ振り（意思入れ）: グループの手本の区間のテーマ
    form_theme, form_rep = {}, []   # 同じ振りの形ごとのテーマ（(グループ, 'A'|'B') → テーマ）・報告の行の元
    events, seen = [], set()
    for h in hits:
        if getattr(h, 'kept', False):   # 残したノーツ: その置き方に決めて流れに入れる（出力には入れない）
            ev = flow.Event(h.beat, tempo.sec(h.beat), h.hands)
            ev.fix, ev.fix_w = h.fix, KEPT_FIX_W
            events.append(ev)
            continue
        sec = secs[h.sec_i]
        g = _bar_theme(bgd, mu['bars'], h.beat, getattr(h, 'variety', None))   # 小節ごとのテーマ
        gid, cyc, _ = g or gd[(h.sec_i, h.phr_i)]
        m = getattr(h, 'motif', None)
        if m:   # 同じ振り: 手本の区間のまとまりのテーマを、区間ごとに型の頭からたどる（置き方は下で手本に合わせる）
            if fspec:   # 形の設定に案 k・珍しい型まで・★の帯がある形は、その形の型を選び直す（B は A の型を元にする＝今まで通り）
                th = _motif_form_theme(m, sec.name, chosen, fspec, pal_of, form_theme, form_rep)
            else:
                th = motif_theme.setdefault(m.get('group'), chosen[sec.name])
            ta, tb = theme.transform(th, 'swap' if m.get('variant') == 'b' else 'base')
            gid, cyc = 500000 + m['idx'], ({0: theme.mirror(ta), 1: tb} if m.get('mirror') else {0: theme.mirror(tb), 1: ta})   # 左右反転の回は手を入れ替える
        # 振り下ろしで打ちたい強い打点（振り上げの減点）: 区間の頭・人が「ドラム」と書いた範囲の頭・★の頭・両手同時・小節の頭
        drum_head = any(h.beat >= r0 - 1e-6 and not any(r0 - 1e-6 <= e.beat < h.beat - 1e-6 for e in events) and h.beat < r1
                        for r0, r1 in rhythm.drum_ranges(sec))
        if h.sec_i not in seen or drum_head or getattr(h, 'reentry', False) or getattr(h, 'force_strong', False):   # 途切れの戻り・キックで決めた所も
            strong = 3.0
            seen.add(h.sec_i)
        elif h.accent:
            strong = 1.5
        elif h.hands == 2:
            strong = 0.4
        else:
            strong = 0.2 if abs((h.beat - sec.b0) % 4) < 1e-6 else 0.0
        events.append(flow.Event(h.beat, tempo.sec(h.beat), h.hands, gid, cyc, h.accent, strong, prow.get(round(h.beat, 4)),
                                 getattr(h, 'min_gap', None), mods=getattr(h, 'mods', None)))
    if rl_plan:
        rl_plan['n'] = relief.mark(hits, events, blocks, rl_plan)
    fst = flow.Style(beam=a.beam, seed=a.seed, noise=0.05, col_cost=(1.5, 0.3, 0.05, 0.0), w_same_hand=1.0, min_gap=0.15, w_center=2.0,
                     w_target={k: 0.0 for k in ('row', 'dir', 'center', 'still', 'alt', 'col')}, w_pitch=0.35 if prow else 0.0)
    fst.w_left_fast = LEFT_FAST_W   # 片手だけの速い続きは右手に（flow.Style.w_left_fast・2026-11-03）
    fst.w_reset = W_RESET   # 長い間の後の振りの順のやり直し（NLM の振りの警告になる）は重く（派生の derive.W_RESET と同じ）
    fst.w_hand_tech = HAND_TECH_K   # 向きの曲がり・大きな移動も右手に（flow.Style.w_hand_tech）
    # 試作5: 曲の個性の割合（斜め・外側の列・上の段）へ弱く寄せる。テーマに沿う重みは既定（前の --follow normal）
    fst.targets, fst.w_target = style.targets(tilt, lib=lib, sps=sps, habit=style.habit_seed(Path(a.stems).name, a.seed)), dict(style.W_TARGET)
    fst.w_theme_cell, fst.w_theme_dir = 1.2, 0.6
    fst.w_center = style.W_CENTER
    if anc.get('at'):   # 前の譜面に寄せる（上の _prev_plan）
        anc['n'] = _prev_anchor(hits, events, anc['at'], anc['free'], a.anchor_w, kime.ANCHOR_MARGIN)
    n_anc = 0
    if dv:   # 派生: 基準と同じ拍の打点は基準の置き方（手・マス・向き）に弱く寄せる（前の譜面に寄せるのと同じ仕組み）。下の難易度は同じ手の振りの間を広げる
        from . import derive
        dv['min_gap'] = fst.min_gap = max(fst.min_gap, derive.min_gap(dv['base'], dv['target']))
        for ev in events:
            if ev.min_gap and ev.min_gap < fst.min_gap:
                ev.min_gap = fst.min_gap
        n_anc = _prev_anchor(hits, events, dv['at'], rl_plan['spans'] if rl_plan else [], a.anchor_w, 0.0)
        fst.w_reset = max(fst.w_reset, derive.W_RESET)
    # 左右の受け渡し（automap/handoff.py・docs/方針.md 6.29）: 寄せる打点は前の譜面の同じ手の続きを残し、ほかに新しく計画する
    for h, ev in zip(hits, events):   # 同じ振りの写す側（2 回目から）は受け渡しを計画しない＝手本の受け渡しがそのまま（左右反転の回は反転して）写る
        if (getattr(h, 'motif', None) or {}).get('occ'):
            ev.no_ho = True
    # 続けて左右反転（automap/echo.py・docs/方針.md 6.33）: 打点の段で選んだセット（echo.unify）の 2 つ目からに印（受け渡し・短い往復より先）
    ec_plan = (echo.plan(events, mu, echo_rep['chains'] if echo_rep else None, min_gap=fst.min_gap, anchored_free=bool(anc.get('at')))
               if getattr(a, 'echo', True) else None)
    # 前の譜面に寄せる時、短い往復は寄せていない時と同じ印の状態（寄せた打点の決めを外し、受け渡しは新しく計画した物）で選ぶ（_fresh_like）
    ghost = _fresh_like(events) if anc.get('at') and getattr(a, 'loops', True) else None
    ho_plan = handoff.plan(events, a.seed, mu['bars'], fst.min_gap) if getattr(a, 'handoff', True) else None
    # 短い往復（automap/loops.py・docs/方針.md 6.32）: 往復の区間の打点は同じ手の 2 つ前の振りと同じ置き方に寄せる
    lp_plan = None
    if getattr(a, 'loops', True):
        if ghost is not None:
            if getattr(a, 'handoff', True):
                handoff.plan(ghost, a.seed, mu['bars'], fst.min_gap)
            lp_plan = loops.plan(ghost, mu['bars'], a.seed, keep=pg.get('loops') if pg else None, touch=pg['touch'] if pg else ())
            for ev, g in zip(events, ghost):
                ev.loop = g.loop
        else:
            lp_plan = loops.plan(events, mu['bars'], a.seed)
    # 選んだ区間だけ作り直す時は、流れの計算を区間の前後だけで行う（automap/window.py・下の呼び出しは全部。外は残したノーツのまま）。
    # --only が無い時は今まで通り曲の全部（答えは 1 ビットも変えない）。AUTOMAP_ONLY_FULL=1 なら区間だけの時も全部で（比べ・測り用）
    win = {'pre': [{'beat': t[0], 'x': t[1], 'y': t[2], 'c': t[3], 'd': t[4]} for t in keep['notes']] if keep else [], 'spans': []} \
        if (only and plan and not window.full_wanted()) else None

    def flow_gen():
        if win is None:
            return flow.generate(events, fst, init=init)
        g, c, sp = window.generate(events, hits, fst, only, tempo, init=init, pre=win['pre'])
        win['spans'].append(sp)
        return g, c
    t0 = time.time()
    gen, cost = flow_gen()
    motif_cut, motif_add = [], []
    mb_block = list(plan['blocked']) if plan else []
    if anc.get('at') and not anc.get('sync_skip') and not only:   # 前の譜面に寄せる所（打点を前の譜面にそろえた）では入りの前を抜かない・足さない（試し・下の _anchored_spans）
        mb_block += _anchored_spans(anc['free'], kime.ANCHOR_MARGIN)
    if any(getattr(h, 'motif', None) for h in hits):   # 両手から入る手本の入りを先にそろえて、手本の置き方を決め直す
        motif_cut, motif_add = _motif_breath(hits, events, gen, ons, models=True, allow=only, block=mb_block,
                                             soften=dv['soft'] if dv else None)
        if motif_cut or motif_add:
            if anc.get('at'):   # 抜く・足すで自由な所の振りの数の偶奇が変わる
                _prev_parity(hits, events, anc, ons, kime.ANCHOR_MARGIN)
            gen, cost = flow_gen()
    motif_rep = _fix_motifs(hits, events, gen, prev=bool(anc.get('at')))   # 同じ振り: 手本の区間の置き方を、ほかの区間で狙ってもう一度
    motif_groups = motif_rep
    kept_miss = _kept_miss(hits, gen)
    if motif_rep or kept_miss:   # 残したクリップの入りで振りの向きが合わない時も、入りの前を抜く・足すで合わせる
        res = {}
        for _ in range(3):   # 抜く・足すと流れの計算の選び方も変わるので、合わない所が残れば読み直してもう一度（3回まで）
            cut_now, add_now = _motif_breath(hits, events, gen, ons, allow=only, block=mb_block,
                                             soften=dv['soft'] if dv else None, model_heads=bool(dv))
            for b in cut_now:   # 前の回に足した物を抜いた時・抜いた所に足した時は、差し引きなし
                (motif_add.remove(b) if b in motif_add else motif_cut.append(b))
            for b in add_now:
                (motif_cut.remove(b) if b in motif_cut else motif_add.append(b))
            if not motif_rep and not (cut_now or add_now):
                break
            if anc.get('at') and (cut_now or add_now):
                _prev_parity(hits, events, anc, ons, kime.ANCHOR_MARGIN)
            gen, cost = flow_gen()
            res, bad = _motif_match(hits, events, gen, motif_rep)
            kept_miss = _kept_miss(hits, gen)
            if not (bad or kept_miss) or not (cut_now or add_now):
                break
        motif_rep = res
    kimes, k_carry = [], None
    k_want, k_avoid = intent.kime_ranges(it)   # 意思入れの決め（1＝入れる・−1＝入れない・珍しい型までの区間は入れる側）
    if rl_plan:   # 息つぎのまとまりには決めを入れない
        k_avoid = list(k_avoid) + rl_plan['spans']
    if getattr(a, 'rare', False) and only:   # --rare（別の案「珍しい型まで広げて作る」）の区間も入れる側
        k_want.append(tuple(only))
    if lib.get('once') and not getattr(a, 'no_kime', False) and not dv:   # 珍しい型を「決め」に（型のデータベースの曲だけ・派生では入れない）: 同じ振り・残したノーツの後で、
        # 今の結果の手と振りの向きに合う所・型を選び、決めたノーツとして計算し直す（打点は増やさない・減らさない）
        keep_k, inside = [], None
        if anc.get('at') and prev_k is not None:   # 前の譜面に寄せる時: 指示を変えていない所の決めは前の版のまま・新しく選ぶのは変わった所だけ
            keep_k, k_drop = kime.carry(prev_k, lib, hits, events, gen, anc['at'], anc['free'], allow=only, avoid=k_avoid)
            inside = intent.merge_spans([(x - kime.ANCHOR_MARGIN, y + kime.ANCHOR_MARGIN) for x, y in anc['free']])
            k_carry = {'src': prev_src, 'drop': [(r, why) for r, why in k_drop if why not in ('選んだ区間の外',)]}
        kimes = kime.choose(lib, hits, events, gen, secs, blocks=blocks, mu=mu, targets=fst.targets, seed=a.seed,
                            allow=only, vranges=[v for v in vranges if v[2]], want=k_want, avoid=k_avoid, keep=keep_k, inside=inside)
        if kimes:
            if anc.get('n'):   # 前の譜面に同じ決めが無い所（新しい決め）は、前後のつなぎを前の譜面に寄せない
                new_k = [k for k in kimes if not k.carried and any(
                    not getattr(events[i], 'anchored', False) or (events[i].fix or {}).get(k.hand) != tuple(c) for i, c in zip(k.idx, k.seq))]
                anc['released'] = kime.release(new_k, events)
            kime.apply(kimes, events)
            kime.anchor(kimes, events, gen, hits)   # 決めの所の外は今の結果に弱く留める（決めから遠い所まで変わらないように）
            gen, cost = flow_gen()
            kime.check(kimes, gen)
            kept_miss = _kept_miss(hits, gen)
            if motif_groups:
                motif_rep, _ = _motif_match(hits, events, gen, motif_groups)
    took = time.time() - t0
    kept_b = {round(h.beat, 4) for h in hits if getattr(h, 'kept', False)}
    gen = [n for n in gen if round(n['beat'], 4) not in kept_b]
    hits = [h for h in hits if not getattr(h, 'kept', False)]
    if plan:   # 作ったままのクリップだけ入れ替える（残したクリップ・消した所はそのまま）
        nlmf.remove_clips(proj, dkey, plan['remove'])
        clips = _cover_clips(proj, gen, end_clip, exclude=plan['exclude'], extra=plan['carry']) + plan['split']
        lane = dv['lane'] if dv else plan['lane']   # 派生は基準の作ったクリップと同じレーン（レーンを足すと全部の難易度の番号がずれる）
        if lane is None:   # 作ったクリップが1つも無い（全部消した等）＝一番上に新しいレーン
            nlmf.put_note_lane(proj, {dkey: clips})
        else:
            nlmf.put_clips(proj, dkey, clips, lane)
    else:
        _put_new_lane(proj, dkey, gen, keep, end_clip)
    if not dv:   # 派生は書き出すフォルダ名・サブタイトルに触らない（基準の作り直しが付けた物のまま）
        # 書き出すフォルダ名もサブタイトルも触らない（前の既定の「意思入れ」「試作5」は空に）。前は -i を足していて、書き出した後に
        # 作り直すと次の書き出しが別のフォルダになり Beat Saber に同じ曲が 2 つ出た（2026-11-09）。取り込みの最初の作り直しも同じ（前は -5・「試作5」）
        _clear_old_subtitle(proj)
    njs_line = _set_njs(proj, dkey, tempo, base=getattr(a, 'njs_base', None), base_formula=getattr(a, 'njs_base_formula', None),
                        dv=dv)   # NJS（★・BPM・難易度から・3D で決めた基準の NJS があれば基準はその値・NLM で決めた値は上書きしない）
    if not dv and njs_line:   # 基準: ほかの難易度（アプリが NJS を書いた物）の見え始める距離も整える（前の版で作った派生はオフセット 0 のまま）
        jd_more = _fix_jd_others(proj, dkey)
        if jd_more:
            njs_line += '\n' + jd_more
    if not dv:   # 基準: 書き出す印がまだ誰も決めていなければ付ける（NLM で外した印は触らない・派生は diffs.ensure と展開が付ける）
        from . import diffs
        if diffs.mark_default(proj, dkey):
            print(f'書き出す印: {diffs.TEXT[diffs.name_of(dkey)]} に付けた（まだ決めていなかった）')
    _save(proj, out)
    final = nlmf.clip_notes(proj, dkey, include_muted=True)   # 残したクリップも入れた、この難易度の譜面
    kept_sp = ([(-1e9, cut)] if cut is not None else []) + (list(plan['blocked']) if plan else [])   # 作り直さなかった所（残したノーツ）
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    title = '意思入れ（試作5＋人の指示）' if a.intent else '試作5（曲の個性でテーマ）'
    if dv:
        title = f'派生（{proj["difficulties"][dv["bkey"]].get("name", dv["bkey"])} から）・{title}'
    lines = [f'# {title}: {Path(a.input).name} の {proj["difficulties"][dkey].get("name", dkey)}', '',
             f'- 土台: {src.name}（BPM {proj["bpm"]}・無音追加 {round(-off * 1000)} ms）' + (f'。{note}' if note else ''),
             f'- 打点 {len(hits)}（両手同時 {sum(h.hands == 2 for h in hits)}）・種 {a.seed}・計算 {took:.1f} 秒・減点の合計 {cost:.1f}',
             f'- 目盛りへの寄せ: {info}',
             f'- 型の出どころ: {_library_desc(a, lib)}・型 {len(themes)}',
             *filter(None, [amt and amt['line']]),   # 量の目安（無ければ行も足さない）
             *filter(None, [njs_line]),
             (f'- **選んだ区間（拍 {only[0]:g}〜{only[1]:g}）だけ作り直した**。外は結果のファイルの今の譜面のまま（区間をまたぐクリップは境目で分けた）'
              + (f'。流れの計算は区間の前後（拍 {min(s[0] for s in win["spans"]):g}〜{max(s[1] for s in win["spans"]):g}）だけ'
                 '＝前後の残したノーツを決めたノーツのまま入れてつなぐ（減点の合計はその中の分）' if win and win['spans'] else '')
              if only else ''),
             _variant_line(vranges, vrep),
             *filter(None, [_rare_line(vranges, vrep, len(themes), rare_box)]),   # 無ければ行も足さない（前と同じ報告）
             *filter(None, _band_line(vranges, vrep, band_box)),
             *_form_theme_lines(form_rep, band_box, it),   # 同じ振りの形のテーマ（形に指示が無く、回ごとに違わなければ行も足さない）
             *filter(None, [_anchor_line(anc, a), _keep_line(keeps, plan)]),
             *filter(None, [_carry_groups_line(pg, repeat_groups, echo_rep, lp_plan) if anc.get('at') else '']),   # 前の版の組（作業中）
             *filter(None, [rhythm.pull_text(vpull) and '- ' + rhythm.pull_text(vpull)]),   # 歌を拍に寄せた（寄せる区間が無ければ行も足さない）
             *filter(None, [groove.report_line(groove_rep)]),   # リズムの型（--no-groove なら行も足さない）
             *filter(None, [_derive_repeat_line(dv) if dv else repeat.report_line(repeat_groups)]),   # 同じ音楽の区間（--no-auto-repeat なら行も足さない・派生はそろえた組）
             *filter(None, [echo.report_line(ec_plan, events, gen, echo_rep)]),   # 続けて左右反転（--no-echo なら行も足さない）
             *filter(None, [handoff.report_line(ho_plan, events, gen)]),   # 左右の受け渡し（--no-handoff なら行も足さない）
             *filter(None, [loops.report_line(lp_plan, loops.share(gen) if lp_plan else None)]),   # 短い往復（--no-loops なら行も足さない）
             f'- 出力: {out.name}（' + ('作ったままのクリップだけ入れ替え・NLM で直した所は残した' if plan else
                                                         'この難易度は作った譜面だけ・一番上のレーン') + '）',
             (f'- 「ここから」（拍 {cut:g}）より前は結果のファイルのまま残した（ノーツ {len(keep["notes"])}・'
              f'ほか {sum(len(v) for k, v in keep.items() if k != "notes")}）。後ろだけ作り直した' if cut is not None else ''), '',
             *(_derive_lines(dv, final, tempo, proj, plan, n_anc, a, lib) if dv else []),
             *(_keep_table(plan, tempo, proj) if plan else []),
             '## 区間ごとのテーマ（右手の形・x y。左手は左右反転）', '',
             '| 区間 | 拍 | 盛り上がり | 打点（1拍） | 山の音 | テーマ（曲数） | 変え方 |', '|---|---|---|---|---|---|---|']
    for si, sec in enumerate(secs):
        th = chosen[sec.name]
        hs = [h for h in hits if h.sec_i == si]
        lines.append(f'| {sec.name}{sec.nth + 1} | {sec.b0:g}〜{sec.b1:g} | 段階 {blocks[si].level} | {len(hs)}（{len(hs) / (sec.b1 - sec.b0):.2f}） | '
                     f'{sum(h.accent for h in hs)} | 右 {_cyc_text(th.a)} ／ 左 {_cyc_text(th.b)}（{th.maps}・{th.src}） | {gd[(si, 0)][2]} |')
    if motif_rep:
        lines += ['', '## 同じ振り（意思入れ・自動）', '', '| グループ | 区間（拍の頭） | 手本どおりのノーツ |', '|---|---|---|']
        for g, (b0s, ok, n) in motif_rep.items():
            lines.append(f'| {g} | {"・".join(f"{b:g}" for b in b0s)} | {ok} / {n} |')
    ec_rows = echo.table(ec_plan, events, gen, tempo)
    if ec_rows:   # 続けて左右反転の場所（2026-11-08 利用者「どこがくり返しか分からない・拍で教えて」）
        lines += ['', '## 続けて左右反転の場所（docs/方針.md 6.33）', '', *ec_rows]
    if motif_cut or motif_add or (plan and kept_miss) or (dv and dv['soft']):
        lines += ['', '## 振りの順を合わせた所（同じ振り・残したクリップの入り）', '']
        if dv and dv['soft']:
            lines.append(f'- 入りの直前の両手を片手にした: 拍 {"・".join(f"{b:g}" for b in sorted(dv["soft"]))}')
        if motif_cut:
            lines.append(f'- 直前の打点を抜いた: 拍 {"・".join(f"{b:g}" for b in sorted(motif_cut))}')
        if motif_add:
            lines.append(f'- 入りの前に打点を足した: 拍 {"・".join(f"{b:g}" for b in sorted(motif_add))}')
        if plan and kept_miss:
            lines.append(f'- 残したノーツのうち {kept_miss} 個は、前後の振りの向きと合わせられなかった（つなぎ目で振りが続く）')
    if vrep and any(r[7] for r in vrep):
        lines += ['', '## 珍しい型まで広げた区間', '', *_rare_lines(vrep, bgd, mu['bars'], themes, rare_box)]
    if vrep and any(r[8] is not None for r in vrep):
        lines += ['', '## ★の帯を変えた区間', '', *_band_lines(vrep, bgd, mu['bars'], themes, band_box)]
    if dv:   # 派生: 決めの表は書かない（決めの引き継ぎ・アプリの決めの印は基準の報告を読む）
        pass
    elif lib.get('once'):
        lines += ['', kime.REPORT_HEAD, '', *_kime_lines(kimes, secs, tempo, proj, getattr(a, 'no_kime', False), k_want, k_avoid, k_carry)]
        if prev_k is not None and not getattr(a, 'no_kime', False):   # 残したノーツの中の決め（区間だけ作り直した時は無くても節を書く＝次の作り直しが外の決めを知る）
            rows = _kept_kimes(prev_k, kimes, kept_sp, final)
            if rows or only or cut is not None:
                lines += ['', kime.CARRY_HEAD, '', f'- {len(rows)}（作り直さなかった所＝前の版のまま・{prev_src} から）', '',
                          *(_kime_head() + [_kime_row(r) for r in rows] if rows else [])]
    elif k_want or k_avoid:
        lines += ['', '## 決め（珍しい型）', '', '- 区間の指示「決め」（と珍しい型までの区間の決め）は効かない: 型の書き出しに1回だけの並びが無い']
    if a.intent and dv:
        lines += ['', f'## 意思入れ（{Path(a.intent).name}）', '', '- 基準と同じ表で選んだ自動の打点から、同じ振りの区間の印・置き方の指示・'
                  '速さの上限・型の変わり方を基準の打点に写した（打点の数の指示は基準の譜面に入っている）']
    elif a.intent:
        sec_t = lambda b: tempo.sec(b) + (((proj.get('graph') or {}).get('song') or {}).get('offset') or 0)
        lines += ['', f'## 意思入れ（{Path(a.intent).name}）', '', (f'- 選んだ区間の中の打点 {len(hits)}（自動で選んだ打点・意思入れは曲全体で数えて区間の中だけ使った）' if only else
                   f'- 自動で選んだ打点 {n_auto} → 意思入れの後 {len(hits)}'), '',
                  '| 区間（元の音源の秒） | 拍 | 打点（前→後） | したこと |', '|---|---|---|---|']
        for r, n0, n1, did in irep:
            span = f'{sec_t(r["b0"]):.1f}〜{sec_t(r["b1"]):.1f}' if r['b1'] > r['b0'] else '—'
            cnt = f'{n0} → {n1}' if n0 is not None else ''
            lines.append(f'| {span} | {r["b0"]:g}〜{r["b1"]:g} | {cnt} | {"・".join(did)} |')
    lines += ['', '## 曲の個性（style.py）', '', '- ' + style.describe(feats, tilt),
              f'- テーマ（性格ごとに {PALETTE} 個・小節ごとに回す）: '
              + ' ／ '.join(f'{c} ' + '・'.join(f'{_cyc_text(t.a)}（{t.maps}）' for t in pal[c]) for c in order)]
    if rl_plan:
        lines += relief.report(rl_plan, blocks, gen, bpm, lead, _cyc_text)
    lines += ['', '## 曲の流れの表（まとまり・くり返しの記号・盛り上がりの段階 0〜3）', '', form.table(blocks, bpm, lead)]
    notes_h = [(b, t) for s_ in secs for b, t, _ in s_.tags if t.startswith('※')]
    if notes_h:
        lines += ['', '## 人のコメント（※のマーカー）', ''] + [f'- 拍 {b:g}: {t}' for b, t in sorted(notes_h)]
    if dv:
        from . import diffs
        lines += ['', stats.table([(f'基準 {diffs.TEXT[dv["base"]]}', stats.summarize(dv['base_notes'], tempo)),
                                   (f'派生 {diffs.TEXT[dv["target"]]}', stats.summarize(final, tempo))]), '']
    else:
        lines += ['', stats.table([('この難易度の譜面' if plan else '作った譜面', stats.summarize(final if plan else gen, tempo))]), '']
    rep = '\n'.join(lines)
    if dv:   # 派生の報告は <結果>.<派生の難易度>.report.md（基準の報告は決めの引き継ぎ・アプリの決めの印が読むので上書きしない）
        diffs.report_path(out, dv['target']).write_text(rep, encoding='utf-8')
    else:
        out.with_suffix('.report.md').write_text(rep, encoding='utf-8')
    print(rep)
    print(f'保存: {out}')


def _span(b0, b1):
    return '曲の全部' if b0 is None else f'拍 {b0:g}〜{b1:g} '


def _variant_line(vranges, vrep):
    """報告の「- 別の案: 拍 a〜b は案 k（ずらし n・種 s）」の行（無ければ空）。珍しい型までは _rare_line"""
    rs = [r for r in vrep or [] if r[2]]
    if not rs:
        return ''
    return '- 別の案: ' + '・'.join(f'{_span(r[0], r[1])}は案 {r[2]}（ずらし {r[3]}・種 {r[4]}' + ('・--variant' if '--variant' in r[5] else '')
                                    + ('・珍しい型まで' if len(r) > 7 and r[7] else '') + ('・重なる小節が無い' if not r[6] else '') + '）'
                                    for r in rs)


def _rare_line(vranges, vrep, n_base, box):
    """報告の「- 珍しい型まで: …」の行（無ければ空）"""
    if not any(_rare(v) for v in vranges):
        return ''
    hm, pm = box.get('min', (None, None))
    n_rare = len(box.get('themes') or [])
    rs = [r for r in vrep or [] if r[7]]
    head = ('- 珍しい型まで: ' + '・'.join(f'{_span(r[0], r[1]).strip()}（小節 {r[6]}' + (f'・案 {r[2]}' if r[2] else '')
                                         + ('・--rare' if '--rare' in r[5] else '')
                                         + ('・★の帯の束の中で' if len(r) > 8 and r[8] is not None else '') + '）' for r in rs))
    if 'themes' not in box:   # どれも★の帯と一緒（広げた数は★の帯の行）
        return head + ' のテーマを、★の帯を変えた型の束の中で、テーマに使う型のしきい値を珍しいまで下げて選び直した'
    return (head + f' のテーマを、広げた型の束（型 {n_rare}・曲の束は {n_base}。テーマに使うのは片手の型 {hm} 曲以上・両手の組 {pm} 曲以上'
            + ('・頻度を珍しいまでで書き出し直した' if box.get('again') else '') + '）から選び直した'
            + ('（曲の束と同じ＝曲の設定がもう珍しいまで）' if n_rare == n_base else ''))


def _rare_lines(vrep, bgd, bars, themes, box):
    """報告の「珍しい型まで広げた区間」の節: 区間ごとに、小節のテーマに使った型（右手の形・曲の数）と、曲の束に無い型（広げた分）の数"""
    base = {t.key() for t in themes}
    cands = [t for p in box.get('pals') or [] for ts in p.values() for t in ts]
    out = ['| 区間 | 小節 | 使った型（右手の形・x y／曲の数） | 曲の束に無い型（広げた分） |', '|---|---|---|---|']
    for r in vrep:
        if not r[7]:
            continue
        only = None if r[0] is None else (r[0], r[1])
        used = []
        for i in sorted(bgd):
            if i < len(bars) and _bar_in(bars, i, only):
                t = _theme_of(bgd[i], cands)
                if t is not None and t not in used:
                    used.append(t)
        new = sum(1 for t in used if t.key() not in base)
        out.append(f'| {_span(r[0], r[1]).strip()} | {r[6]} | ' + '・'.join(f'{_cyc_text(t.a)}／{t.maps}' for t in used)
                   + f' | {new} / {len(used)} |')
    return out


def _cli_band(a):
    """compose --band（別の案の「★の帯を変えて作る」）→ intent.band_of の値（無い・使えない＝None）"""
    v = getattr(a, 'band', None)
    return intent.band_of(v) if v not in (None, '') else None


def _band_themes(a, lib, band, rare, box):
    """★の帯を変えた型の束 → {'themes', 'lib', 'stars', 'songs', 'min', 'base', 'db_song'}（帯ごとに1回・box に控える）。データベースが
    使えない時は None（box['err'] に理由・帯は効かない）。曲の設定の★の帯からずらす。
    珍しい型までと一緒なら、その帯の書き出しのしきい値を「珍しい」まで下げる（曲の設定が頻度を絞っていれば「珍しい」で書き出し直す）"""
    from . import library_use
    key = (json.dumps(band), bool(rare))
    if key in box['got']:
        return box['got'][key]
    song = getattr(a, 'library', None)
    sf = library_use.filters_of(song) if song else dict(library_use.DEFAULT)
    freq = '珍しい' if rare and sf.get('freq') in ('定番', 'よくある') else None
    try:
        blib = library_use.export_band(song, band, box['libs'], freq)
    except library_use.Unavailable as e:
        box.setdefault('err', {})[json.dumps(band)] = str(e)
        box['got'][key] = None
        return None
    fr = '珍しい' if rare else None
    got = {'themes': theme.load_themes(blib, freq=fr), 'lib': blib, 'stars': (blib['library'].get('filters') or {}).get('stars'),
           'songs': blib.get('songs'), 'min': theme.thresholds(blib, fr), 'base': sf.get('stars'), 'db_song': bool(song)}
    box['got'][key] = got
    return got


def _band_info(box, band, rare=False):
    """★の帯の控え（_band_themes）から、その帯の物（珍しい型までの有無も同じ物・無ければ同じ帯のどれか）"""
    got = box.get('got') or {}
    if got.get((json.dumps(band), bool(rare))):
        return got[(json.dumps(band), bool(rare))]
    return next((g for (b, _), g in got.items() if g and b == json.dumps(band)), None)


def _band_line(vranges, vrep, box):
    """報告の「- 区間の★の帯: 拍 a〜b は ★x〜y（…）」の行（効かない帯はその知らせ・無ければ空の並び）"""
    from . import library_use
    if not any(_band(v) is not None for v in vranges):
        return []
    parts, errs = [], []
    for r in vrep:
        if r[8] is None:
            continue
        g = _band_info(box, r[8], r[7])
        if g is None:
            errs.append(f'{_span(r[0], r[1]).strip()}（{intent.band_text(r[8])}）')
            continue
        rel = '' if isinstance(r[8], list) else \
            f'{intent.band_text(r[8])}・{"曲の設定" if g["db_song"] else "既定"} {library_use.stars_text(g["base"])} から・'
        parts.append(f'{_span(r[0], r[1]).strip()} は {library_use.stars_text(g["stars"])}（{rel}曲 {g["songs"]}・型 {len(g["themes"])}・'
                     f'小節 {r[6]}' + (f'・案 {r[2]}' if r[2] else '') + ('・珍しい型まで' if r[7] else '')
                     + ('・--band' if '--band' in r[5] else '') + ('・重なる小節が無い' if not r[6] else '') + '）')
    out = ['- 区間の★の帯: ' + '・'.join(parts) + '（テーマをその帯の型から選び直した。量は変えない）'] if parts else []
    if errs:
        err = next(iter((box.get('err') or {}).values()), '')
        out.append(f'- **区間の★の帯（{"・".join(errs)}）は効かない**: {err}')
    return out


def _band_lines(vrep, bgd, bars, themes, box):
    """報告の「★の帯を変えた区間」の節: 区間ごとに、小節のテーマに使った型（右手の形・曲の数・★の中央値＝その帯の書き出しの中で）と、
    曲の束に無い型の数"""
    from . import library_use
    base = {t.key() for t in themes}
    out = ['| 区間 | 帯 | 小節 | 使った型（右手の形・x y／曲の数・★の中央値） | 曲の束に無い型 |', '|---|---|---|---|---|']
    for r in vrep:
        if r[8] is None:
            continue
        g = _band_info(box, r[8], r[7])
        if g is None:
            out.append(f'| {_span(r[0], r[1]).strip()} | {intent.band_text(r[8])} | {r[6]} | 効かない（型のデータベースが使えない） | |')
            continue
        star = {}
        for q in g['lib'].get('pairs') or []:
            star[(tuple(map(tuple, q['a'])), tuple(map(tuple, q['b'])))] = q.get('stars')
        for h in g['lib'].get('hands') or []:
            c = tuple(map(tuple, h['cycle']))
            star.setdefault((c, c), h.get('stars'))
        cands = [t for p in (box.get('pals') or {}).get(json.dumps(r[8])) or [] for ts in p.values() for t in ts]
        only = None if r[0] is None else (r[0], r[1])
        used = []
        for i in sorted(bgd):
            if i < len(bars) and _bar_in(bars, i, only):
                t = _theme_of(bgd[i], cands)
                if t is not None and t not in used:
                    used.append(t)
        new = sum(1 for t in used if t.key() not in base)
        lab = library_use.stars_text(g['stars']) if isinstance(r[8], list) else f'{intent.band_text(r[8])}＝{library_use.stars_text(g["stars"])}'
        out.append(f'| {_span(r[0], r[1]).strip()} | {lab} | {r[6]} | '
                   + '・'.join(f'{_cyc_text(t.a)}／{t.maps}' + (f'・★{star[t.key()]:.1f}' if star.get(t.key()) is not None else '')
                              for t in used) + f' | {new} / {len(used)} |')
    return out


def _kime_head():
    return ['| 拍 | 時刻（元の音源の秒） | 区間 | 場所 | 手 | 型（その手の形・x y） | 曲の数（頻度・難しさ） | 置けた |',
            '|---|---|---|---|---|---|---|---|']


def _kime_row(r):
    """決めの表の1行（r＝kime.parse_row と同じ形の dict。読むのは kime.parse_row・app/check.py）"""
    t = f'{r["t"]:.1f}' if r.get('t') is not None else ''
    pl = f'{r["place"]}（拍 {r["place_beat"]:g}）' if r.get('place_beat') is not None else (r.get('place') or '')
    seq = r.get('seq_text') or _cyc_text(r['seq'])
    return (f'| {r["b0"]:g}〜{r["b1"]:g} | {t} | {r.get("sec") or ""} | {pl} | {"右" if r["hand"] == flow.RIGHT else "左"} | {seq} | '
            f'{r.get("maps")}（{r.get("freq")}・{r.get("hard")}） | {r.get("placed")} / {r.get("total") if r.get("total") is not None else len(r["seq"])} |')


def _kept_kimes(prev, kimes, spans, notes):
    """前の版の決め（kime.prev_kimes）のうち、作り直さなかった所（spans＝「ここから」の前・選んだ区間の外・残したクリップ・そのまま残す）に
    あって譜面 notes にまだある物（今の決めと同じ物は除く）→ 表の行の dict"""
    if not prev:
        return []
    inn = lambda b: any(x - 1e-9 <= b < y - 1e-9 for x, y in spans)
    have = {(k.hand, round(k.beats[0], 3), round(k.beats[-1], 3)) for k in kimes}
    return [r for r in prev if inn(r['b0']) and inn(r['b1']) and (r['hand'], round(r['b0'], 3), round(r['b1'], 3)) not in have
            and kime.present(r, notes)]


def _prev_kimes(a, out):
    """前の版の決め（kime.prev_kimes・None＝分からない）と読んだ報告の名前。今の結果のファイルの報告（書き換える前）、無ければ
    --prev-intent の隣の報告（アプリの履歴の版 <曲>.<版>.intent.json の隣の <曲>.<版>.report.md。別の案は結果のファイルの写しに
    作るので、隣に報告が無い）"""
    paths = [out.with_suffix('.report.md')]
    pi = getattr(a, 'prev_intent', None)
    if pi and Path(pi).name.endswith('.intent.json'):
        paths.append(Path(pi).with_name(Path(pi).name[:-len('.intent.json')] + '.report.md'))
    for p in paths:
        try:
            md = p.read_text(encoding='utf-8')
        except OSError:
            continue
        return kime.prev_kimes(md), p.name
    return None, None


def _carry_line(carry, kimes):
    """報告の「前の版の決めを引き継いだ」の行（前の譜面に寄せて前の版の決めが分かった時だけ）"""
    if not carry:
        return []
    n_c = sum(1 for k in kimes if getattr(k, 'carried', False))
    re_ = sum(1 for _, why in carry['drop'] if why == '指示が変わった所')
    other = [(r, why) for r, why in carry['drop'] if why != '指示が変わった所']
    return [f'- 前の版の決めを引き継いだ {n_c}（指示を変えていない所・{carry["src"]} から）・変わった所で選び直した {re_}・新しく選んだ {len(kimes) - n_c}'
            + ('。引き継がなかった前の決め: ' + '・'.join(f'拍 {r["b0"]:g}〜{r["b1"]:g}（{why}）' for r, why in other) if other else '')]


def _kime_lines(kimes, secs, tempo, proj, off_flag=False, want=(), avoid=(), carry=None):
    """報告の「決め（珍しい型）」の節の中身（kime.py）。want・avoid＝区間の指示の決め（入れる・入れない）。carry＝前の版から引き継いだ
    様子（cmd_compose の k_carry）"""
    if off_flag:
        return ['- 切った（--no-kime）']
    ask = []
    if want:
        got = lambda b0, b1: sum(1 for k in kimes if b0 - 1e-6 <= k.beats[0] and k.beats[-1] <= b1 + 1e-6)
        ask.append('入れる ' + '・'.join(f'拍 {b0:g}〜{b1:g}（' + (f'入った {got(b0, b1)}' if got(b0, b1) else '入る所が無かった') + '）'
                                        for b0, b1 in want))
    if avoid:
        ask.append('入れない ' + '・'.join(f'拍 {b0:g}〜{b1:g}' for b0, b1 in avoid))
    ask = ['- 区間の指示: ' + '／'.join(ask)] if ask else []
    if not kimes:
        return ask + ['- 入れる所が無かった（手と振りの向き・打点の間が合う所と型が無い）'] + _carry_line(carry, kimes)
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    ok = sum(k.placed or 0 for k in kimes)
    tot = sum(len(k.seq) for k in kimes)
    out = ask + [f'- 決め {len(kimes)}・決めたとおりに置けたノーツ {ok} / {tot}（型は 1回だけの並び＝片手の 4 振り・曲の数は絞り込みの中で出た曲）',
                 *_carry_line(carry, kimes), '', *_kime_head()]
    for k in kimes:
        sec = secs[k.sec_i] if 0 <= k.sec_i < len(secs) else None
        it = k.item
        out.append(_kime_row({'b0': k.beats[0], 'b1': k.beats[-1], 't': tempo.sec(k.beats[0]) + off, 'sec': f'{sec.name}{sec.nth + 1}' if sec else '',
                              'place': k.place.kind, 'place_beat': k.place.beat, 'hand': k.hand, 'seq': k.seq, 'maps': it.get('maps'),
                              'freq': it.get('freq'), 'hard': (it.get('hard') or {}).get('class', ''), 'placed': k.placed, 'total': len(k.seq)}))
    return out


def _keep_table(plan, tempo, proj):
    """報告の「NLM で直した所（残したクリップ）」の節"""
    off = ((proj.get('graph') or {}).get('song') or {}).get('offset') or 0
    sec_t = lambda b: tempo.sec(b) + off
    rows = []
    n_out = sum(1 for _, why in plan['kept'] if why == 'outside')
    for s, why in sorted(plan['kept'], key=lambda t: (t[0].get('beat') or 0)):
        if why == 'outside':
            continue
        b0, L = s.get('beat') or 0, s.get('len') or 0
        n = sum(1 for t in (s.get('content') or {}).get('notes') or [] if isinstance(t, list) and t[0] is not None and 0 <= t[0] < L)
        rows.append(f'| {sec_t(b0):.1f}〜{sec_t(b0 + L):.1f} | {b0:g}〜{b0 + L:g} | {s.get("label") or ""} | {s.get("track") or 0} | {KEEP_REASON[why]} | {n} |')
    for h0, h1 in plan['holes']:
        rows.append(f'| {sec_t(h0):.1f}〜{sec_t(h1):.1f} | {h0:g}〜{h1:g} | — | {plan["lane"]} | 消した所（空のまま） | 0 |')
    head = ['## NLM で直した所（残したクリップ）', '']
    if n_out:
        head += [f'- 選んだ区間の外の作ったクリップ {n_out} はそのまま（区間をまたいで分けたクリップ {len(plan.get("split") or [])}）', '']
    if not rows:
        return head + ['- NLM で直して残したクリップは無い', '']
    return head + [f'- 作り直したクリップ {len(plan["remove"])}・残したクリップ {len(plan["kept"]) - n_out}・消した所 {len(plan["holes"])}', '',
                   '| 時刻（元の音源の秒） | 拍 | 名前 | レーン | 理由 | ノーツ |', '|---|---|---|---|---|---|'] + rows + ['']


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m automap')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('compose', help='分けた音とテーマから譜面を作る（試作5＋意思入れ・--form --style を付ける）')
    c.add_argument('input')
    c.add_argument('--stems', required=True, help='分けた音のフォルダ（tools/separate.py の出力）')
    c.add_argument('--diff', default='ExpertPlus')
    c.add_argument('--seed', type=int, default=1)
    c.add_argument('--beam', type=int, default=64)
    c.add_argument('--library', help='型の出どころ＝BeatLeader のランク譜面の型のデータベースの絞り込み（JSON の文字列かファイル・'
                                     'automap/library_use.py）。無ければ新しい曲の既定（library_use.DEFAULT）')
    c.add_argument('--form', action='store_true', help='曲の流れの表（form.py）で決める＝試作4。必ず --style と一緒に（無い道は除いた）')
    c.add_argument('--style', action='store_true', help='テーマを曲の個性で選ぶ＝試作5（style.py）。必ず --form と一緒に')
    c.add_argument('--intent', help='意思入れの表（<曲>.intent.json・intent.py）を効かせる')
    c.add_argument('--only', help='選んだ区間だけ作り直す「拍の始まり,拍の終わり」（外は結果のファイルの今の譜面のまま・結果のファイルがある時だけ）')
    c.add_argument('--vocal-pull', action=argparse.BooleanOptionalAction, default=True,
                   help='歌を拍に寄せる（自動）: 歌の立ち上がりが目盛りからばらつく区間で、迷った歌の打点をキック・スネアの鳴る目盛りへ'
                        '（rhythm.vocal_pull・--no-vocal-pull で切る・区間の指示「歌を拍に寄せる」は切っても効く）')
    c.add_argument('--groove', action=argparse.BooleanOptionalAction, default=True,
                   help='リズムの型（automap/groove.py）: 同じ音楽の小節は同じリズム・似たリズムは 1 つの型へ（--no-groove で切る）')
    c.add_argument('--auto-repeat', action=argparse.BooleanOptionalAction, default=True,
                   help='同じ音楽の区間は譜面ごとくり返す（automap/repeat.py・2 回目・4 回目は左右反転）・--no-auto-repeat で切る')
    c.add_argument('--echo', action=argparse.BooleanOptionalAction, default=True,
                   help='続けて左右反転（automap/echo.py）: 曲の流れでセットを決め、次のセットを手を入れ替えた左右反転に（--no-echo で切る）')
    c.add_argument('--loops', action=argparse.BooleanOptionalAction, default=True,
                   help='短い往復（automap/loops.py）: 曲の一部を同じ手の 2 つ前と同じ置き方の往復に（--no-loops で切る）')
    c.add_argument('--handoff', action=argparse.BooleanOptionalAction, default=True,
                   help='左右の受け渡し（automap/handoff.py）: 片手の打点が同じ間合いで続く所を手が 2 振りずつ交代する形に（一部は左右反転）・--no-handoff で切る')
    c.add_argument('--relief', action='store_true', help='緩急（試し・automap/relief.py）: 曲の中に息つぎ（易しい型のくり返し）のまとまりを作る')
    c.add_argument('--variant', type=int, default=0, help='試作5: 別の案「案 K」。--only の区間（無ければ曲の全部）と重なる小節の'
                                                         'テーマを、案 K の決まり（intent.variant_spec: ずらし 1+(K-1)%%5・種 1+(K-1)//5）で選ぶ。'
                                                         '意思入れの表の「案」より後に効く（0＝無し）')
    c.add_argument('--rare', action='store_true', help='試作5: --only の区間（無ければ曲の全部）と重なる小節のテーマを、テーマに使う型の'
                                                     'しきい値を「珍しい」まで下げた型の束から選ぶ（--variant と一緒なら広げた束の中で案 K。'
                                                     '--only と一緒なら決めもその区間に入れる側）')
    c.add_argument('--band', help='試作5: --only の区間（無ければ曲の全部）と重なる小節のテーマを、★の帯だけ変えた型のデータベースの'
                                   '書き出しから選ぶ（「+1」1段難しく・「-1」1段やさしく・「6,10」帯を直接。'
                                   '--variant・--rare と一緒なら、その帯の束の中で）')
    c.add_argument('--no-kime', action='store_true', help='珍しい型の「決め」を入れない（kime.py）')
    c.add_argument('--fresh', action='store_true', help='結果のファイルが NLM で直されていても、入力を土台にする（控えは取る）')
    c.add_argument('--prev-intent', help='前の作り直しの時の意思入れの表（--intent と同じ形）。今の表と比べて指示が変わった所だけ自由に作り、'
                                         'ほかは前の譜面（結果のファイルの作ったノーツ）に弱く寄せる（アプリが履歴の版から渡す）')
    c.add_argument('--no-anchor', nargs='?', const='--no-anchor', help='前の譜面に寄せない（値＝報告に出す理由）')
    c.add_argument('--anchor-w', type=float, default=None, help='前の譜面に寄せる重み（既定は決めの外を留める重み kime.ANCHOR_W と同じ）・'
                                                                '派生では基準の置き方に寄せる重み（既定 derive.ANCHOR_W）')
    c.add_argument('--derive-from', help='派生（難易度の展開・automap/derive.py）: この基準の難易度（例 ExpertPlus）の今の譜面から、--diff の'
                                         '難易度を作る（下は打点を間引く・上は足す・置き方は基準に寄せて流れの計算をし直す）。基準・ほかの難易度は'
                                         '変えない。派生の難易度が無ければ足す。報告は <結果>.<派生の難易度>.report.md')
    c.add_argument('--ratio', type=float, help='派生の量＝基準の1秒のノーツに対する割合（既定は1段ごとに ±10%%・diffs.ratio）')
    c.add_argument('--derive-with', help='派生: 同じ展開で一緒に作るほかの派生「難易度=割合」をコンマで（アプリが並べて作る時）。'
                                         '入れ子の相手がこの中なら、できた譜面を待たずに同じ決まりで間引いた打点で見込む')
    c.add_argument('--base-report', help='派生: 基準の作り直しの報告（<結果>.report.md）。「同じ音楽の区間」の組を派生でもそろえる'
                                         '（無ければ結果のファイルの隣の報告・それも無ければこの作り直しで選び直した組）')
    c.add_argument('--nps-target', type=float, help='量の目安＝1秒のノーツの数（automap/amount.py）。自動の打点（意思入れの前）を小節ごとに'
                                                     '同じ倍率で足す・減らして合わせる。量のライン・区間の量 ±はこの量に対する割合。無い＝今のまま')
    c.add_argument('--nps-from', help='量の目安の出どころ（報告に出す説明。例「★6〜8 の人の譜面の中央値」）')
    c.add_argument('--njs-base', type=float, help='3D で決めた基準の NJS（作業ファイルの njs.base・automap/njs.py）: 基準はこの値そのまま・'
                                                  '派生（--derive-from）はこの値＋（派生の式の値 − 基準の式の値）。無い＝式のまま')
    c.add_argument('--njs-base-formula', type=float, help='派生と --njs-base: 基準の式の値（アプリの展開が 1 回だけ測って渡す・無ければ基準の★を測る）')
    c.add_argument('--out')
    c.set_defaults(func=cmd_compose)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    a = p.parse_args(argv)
    a.func(a)


if __name__ == '__main__':
    main()
