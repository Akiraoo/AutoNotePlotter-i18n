"""歌を拍に寄せる（rhythm.vocal_pull・区間の指示 vsnap・docs/方針.md 6.34）の約束"""
import numpy as np

from automap import intent, rhythm

BPM = 120.0   # 1 拍 0.5 秒・1/4 拍 125ms・DRUM_TOL_MS 30ms＝0.06 拍


def _v(raw, beat=None, s=0.8, weak=False):
    return rhythm.Onset(rhythm.snap_vocals([raw], BPM)[0] if beat is None else beat, raw, 'vocal', s, 60.0, 0.5, weak)


def _d(beat, kind='kick', s=0.8):
    return rhythm.Onset(beat, beat, kind, s)


def test_pull_zero_same_answer():
    """pull 0（とドラムが無い）なら前と同じ答え"""
    rng = np.random.default_rng(1)
    raw = np.sort(rng.uniform(0, 64, 300))
    weak = rng.uniform(0, 1, 300) < 0.3
    a = rhythm.snap_vocals(raw, BPM, coarse=weak)
    assert np.array_equal(a, rhythm.snap_vocals(raw, BPM, coarse=weak, drums=np.arange(0, 64, 0.25), pull=0.0))
    assert np.array_equal(a, rhythm.snap_vocals(raw, BPM, coarse=weak, drums=np.array([]), pull=0.3))


def test_intent_pull_goes_to_drum_neighbor_only():
    """指示の強い寄せ方: 今の目盛りにドラムが無く隣にあれば、近い方の目盛りでもドラムの方へ。1/4 拍を飛び越えては動かさない"""
    drums = np.array([1.25])
    x = np.array([1.06])   # 1.0 に近い（30ms）・1.25 の隣
    assert rhythm.snap_vocals(x, BPM)[0] == 1.0
    assert rhythm.snap_vocals(x, BPM, drums=drums, pull=rhythm.INTENT_PULL / 4, reach=rhythm.INTENT_REACH)[0] == 1.25
    far = np.array([1.5])   # 2 つ先の目盛りのドラムには寄せない
    assert rhythm.snap_vocals(np.array([1.0]), BPM, drums=far + 0, pull=rhythm.INTENT_PULL / 4, reach=rhythm.INTENT_REACH)[0] == 1.0
    # 自動の弱い寄せ方は、真ん中あたりで迷った打点だけ（30ms の所は動かさない）
    assert rhythm.snap_vocals(x, BPM, drums=drums, pull=rhythm.DRUM_PULL / 4)[0] == 1.0
    mid = np.array([1.12])   # 1.0 と 1.25 の真ん中あたり
    assert rhythm.snap_vocals(mid, BPM, drums=drums, pull=rhythm.DRUM_PULL / 4)[0] == 1.25


def test_loose_spans():
    """目盛りにそろった歌はばらつかない・1/8 拍くらい散らばった所だけ拾う"""
    on = [_v(b) for b in np.arange(0, 16, 0.5)]
    assert rhythm.loose_spans(on) == []
    rng = np.random.default_rng(3)
    off = [_v(b + rng.choice([-1, 1]) * rng.uniform(0.07, 0.12)) for b in np.arange(16, 32, 0.5)]
    sp = rhythm.loose_spans(on + off)
    assert sp and all(a >= 12 for a, _ in sp) and any(a <= 16 and b >= 32 for a, b in sp)


def test_vocal_pull_regions_skip_and_merge():
    """指示の区間だけ・寄せない区間は自動でも寄せない・動いた打点が重なったら 1 つに（ノーツは増えない）・前からの重なりはそのまま"""
    drums = [_d(b) for b in (4.25, 8.25)]
    v1, v2 = _v(4.06), _v(4.27)          # v1 は 4.0・v2 は 4.25 → 寄せると 2 つとも 4.25 に重なる
    v3 = _v(8.06)                        # 区間の外（8.0 のまま）
    v4, v5 = _v(12.0), _v(12.02)        # 前から同じ拍（区間の外）
    ons = {'vocal': [v1, v2, v3, v4, v5], 'kick': drums, 'snare': []}
    out, rep = rhythm.vocal_pull(ons, BPM, [(0, 8)], auto=False)
    beats = [o.beat for o in out['vocal']]
    assert beats.count(4.25) == 1 and 4.0 not in beats and 8.0 in beats and beats.count(12.0) == 2
    assert rep == [(0.0, 8.0, 'intent', 1, 2)]
    assert ons['vocal'][0].beat == 4.0   # 元の打点の候補は書き換えない
    # 区間が無い・ドラムが無い・自動で拾う区間が無い → そのまま
    assert rhythm.vocal_pull(ons, BPM, [], auto=False) == (ons, [])
    assert rhythm.vocal_pull({'vocal': [v1], 'kick': [], 'snare': []}, BPM, [(0, 8)])[1] == []
    assert '指示 拍 0〜8 1/2' in rhythm.pull_text(rep) and rhythm.pull_text([]) is None


def test_minus():
    assert rhythm._minus([(0, 16), (20, 24)], [(4, 8), (22, 30)]) == [(0, 4), (8, 16), (20, 22)]
    assert rhythm._minus([(0, 4)], [(0, 4)]) == []


def test_auto_skips_intent_and_off_regions():
    """自動のばらつく区間から、指示の区間（強く寄せる）と「寄せない」の区間を除く"""
    rng = np.random.default_rng(5)
    voc = [_v(b + rng.choice([-1, 1]) * rng.uniform(0.07, 0.12)) for b in np.arange(0, 32, 0.5)]
    ons = {'vocal': voc, 'kick': [_d(b) for b in np.arange(0, 32, 0.25)], 'snare': []}
    _, rep = rhythm.vocal_pull(ons, BPM, [(8, 12)], auto=True, skip=[(16, 20)])
    kinds = {(a, b): k for a, b, k, *_ in rep}
    assert kinds[(8.0, 12.0)] == 'intent'
    assert all(not (a < 20 and 16 < b) for (a, b), k in kinds.items() if k == 'auto')
    assert all(not (a < 12 and 8 < b) for (a, b), k in kinds.items() if k == 'auto')


def test_vsnap_ranges():
    it = {'ranges': [{'b0': 0, 'b1': 8, 'set': {'vsnap': True}}, {'b0': 8, 'b1': 16, 'set': {'vsnap': False}},
                     {'b0': 16, 'b1': 24, 'set': {'vsnap': True, 'rest': True}}, {'b0': 24, 'b1': 32, 'set': {'fill': True}}]}
    assert intent.vsnap_ranges(it) == ([(0.0, 8.0)], [(8.0, 16.0)])
    assert intent.vsnap_ranges(None) == ([], [])
