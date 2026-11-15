"""遊んだ結果（BeatLeader のリプレイ .bsor）を、作った譜面と突き合わせて見る（読むだけ）。

使い方: .venv/Scripts/python.exe -B tools/replay_check.py <リプレイのフォルダ> <曲名（ファイル名の一部）> [--nlmf 作った.nlmf --stems cache/<曲>]
        --bsor <BeatPlayAnalyzer の bpa/bsor.py>（環境変数 BPA_BSOR でもよい）
出すもの: スコアと精度の目安・見逃し／悪い切り方・切った時刻−ノーツの時刻（ms・マイナス＝早めに切った）の中央値。
--nlmf と --stems を渡すと、歌の打点とドラム・楽器の打点、区間ごとに分けて出す（どこが「ずれて」感じられたかの目安）。
遊ぶ人はノーツを見て切るので、置き場所のずれは小さくしか出ない（1/4 拍ずれても −10ms 程度）。
打点の種類（歌かドラムか）は今の作り方（曲の流れの表＝form.py と同じ打点の選び方・rhythm.choose_hits）で選び直して決めるので、
前の作り方で作った譜面・意思入れで足した打点では分からないノーツが増える（数えない）。区間の名前はマーカーから。
リプレイの読み込みは BeatPlayAnalyzer の bsor.py（numpy だけ）をファイルから読み込んで使う（向こうのフォルダには何も書かない＝-B で動かす）。
"""
import argparse
import glob
import importlib.util
import os
import statistics
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_bsor(path):
    spec = importlib.util.spec_from_file_location('bsor', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['bsor'] = mod   # dataclass はモジュールが登録済みであることを前提にする
    spec.loader.exec_module(mod)
    return mod


def max_score(n):
    """ノーツ n 個（全部 115 点）の最大スコア（倍率 1・2・4・8 の上がり方）"""
    if n <= 0:
        return 0
    m = [1] + [2] * 4 + [4] * 8
    return 115 * (sum(m[:n]) + 8 * max(0, n - len(m)))


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(prog='replay_check')
    p.add_argument('replays')
    p.add_argument('song', help='リプレイのファイル名に入っている曲名（の一部）')
    p.add_argument('--diff', default='ExpertPlus')
    p.add_argument('--nlmf')
    p.add_argument('--stems')
    p.add_argument('--bsor', default=os.environ.get('BPA_BSOR'))
    a = p.parse_args(argv)
    if not a.bsor:
        raise SystemExit('--bsor（または環境変数 BPA_BSOR）に BeatPlayAnalyzer の bpa/bsor.py の場所を入れる')
    bsor = load_bsor(a.bsor)
    files = sorted(glob.glob(os.path.join(a.replays, f'*-{a.song}-{a.diff}-*.bsor')), key=os.path.getmtime)
    if not files:
        raise SystemExit('リプレイが無い')
    r = bsor.read(files[-1])
    ev = [n for n in r.notes if n.event_type != bsor.BOMB]
    good = [n for n in ev if n.event_type == bsor.GOOD]
    lat = [(n.event_time - n.spawn_time) * 1000 for n in good]
    i = r.info
    print(f'{Path(files[-1]).name}')
    print(f'スコア {i.score}（精度の目安 {i.score / max(1, max_score(len(ev))):.1%}）・修飾 {i.modifiers or "なし"}・JD {i.jump_distance:.1f}・'
          f'ノーツ {len(ev)}（切れた {len(good)}・悪い {sum(1 for n in ev if n.event_type == bsor.BAD)}・見逃し {sum(1 for n in ev if n.event_type == bsor.MISS)}）')
    print(f'切った時刻−ノーツの時刻: 中央値 {statistics.median(lat):+.0f} ms')
    if not (a.nlmf and a.stems):
        return
    import json
    from automap import form, music, nlmf, rhythm
    d = nlmf.load(a.nlmf)
    bpm = d['bpm']
    lead = round(-((d.get('graph') or {}).get('song') or {}).get('offset', 0) * 1000)
    markers = d.get('markers') or []
    secs = rhythm.sections_from_markers(markers, 10 ** 6)   # 区間の名前（マーカー）で分けて出す
    ons, _ = rhythm.analyze(a.stems, bpm, lead)
    # 打点の種類: compose と同じ曲の流れの表で打点を選び直す（前の区間の名前で選ぶ道は除いた・docs/除いた物.md）
    end = (json.loads((Path(a.stems) / 'separate.json').read_text(encoding='utf-8'))['seconds'] + lead / 1000) * bpm / 60
    ons_d = json.loads((Path(a.stems) / 'onsets.json').read_text(encoding='utf-8'))['onsets']
    mu = music.analyze(a.stems, ons_d, bpm, lead, int(end))
    blocks = form.build(mu, markers, int(end))
    src = {round(h.beat, 3): h.src for h in rhythm.choose_hits(ons, form.sections(blocks, markers, end), form.plan(blocks))}
    rows = []
    for n in ev:
        b = round(n.spawn_time * bpm / 60 * 4) / 4   # 書き出した曲は無音追加を焼き込む＝拍 b は b×60/BPM 秒
        s = src.get(round(b, 3), '?')
        sec = next((x.name for x in reversed(secs) if x.b0 <= b + 1e-6), '頭')
        rows.append((s, sec, n.event_type, (n.event_time - n.spawn_time) * 1000 if n.event_type == bsor.GOOD else None))

    def summ(sel, label):
        ls = [x[3] for x in sel if x[3] is not None]
        if ls:
            bad = sum(1 for x in sel if x[2] in (bsor.BAD, bsor.MISS))
            print(f'  {label:<24} ノーツ {len(sel):4d}  ずれの中央値 {statistics.median(ls):+5.0f} ms  悪い・見逃し {bad}')
    summ([x for x in rows if x[0] == 'vocal'], '歌の打点')
    summ([x for x in rows if x[0] not in ('vocal', '?')], 'ドラム・楽器の打点')
    for nm in dict.fromkeys(x[1] for x in rows):
        summ([x for x in rows if x[1] == nm and x[0] == 'vocal'], f'{nm}（歌）')
        summ([x for x in rows if x[1] == nm and x[0] not in ('vocal', '?')], f'{nm}（ドラム・楽器）')


if __name__ == '__main__':
    main()
