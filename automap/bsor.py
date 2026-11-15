"""BeatLeader のリプレイ（.bsor）を読む（2026-11-12・app/replays.py が BL のリプレイアプリで開く前に、曲の一覧・遊んだ時の譜面を
探す・譜面が無い時にノーツを組み立てるために使う）。標準ライブラリだけ（サーバーの頭で読んでも軽い）。

形式は BeatLeader の Open Replay Format（https://github.com/BeatLeader/BS-Open-Replay ・MIT）。公式の読み込み
（https://github.com/BeatLeader/ReplayDecoder ・MIT）と同じ癖に合わせる:
- 文字列の長さがおかしい（負・1000 超）時は 1 バイトずらして読み直す（古い mod の不具合）。
- ノーツの番号が -1、または 100000 未満で下 1 桁が 9 の時はボム（番号に 4 を足す）。
フレーム（頭と両手の位置・向き）は読み飛ばす（見るのは BL のリプレイアプリ）。
"""
import struct
from pathlib import Path

MAGIC = 0x442D3D69
GOOD, BAD, MISS, BOMB = 0, 1, 2, 3
FRAME_SIZE = 4 + 4 + 3 * 7 * 4   # 時刻・fps・頭／左手／右手（位置 3＋回転 4）
_CUT = struct.Struct('<????f3fiff3f3f4f')   # 切った時の情報（GOOD・BAD の時だけ付く・72 バイト）
INFO_KEYS = ('version', 'game_version', 'timestamp', 'player_id', 'player_name', 'platform', 'tracking_system', 'hmd',
             'controller', 'hash', 'song_name', 'mapper', 'difficulty')
# 点の種類（番号の頭・ゲームの値＋2）→ 1 つの満点（公式の NoteParams.ScoreDefinitions の合計）。無い・古い（0・1）は通常
MAX_CUT = {2: 0, 3: 115, 4: 115, 5: 115, 6: 85, 7: 20, 8: 115, 9: 115, 10: 20, 11: 115, 12: 115}
CHAIN_LINKS = (7, 10)   # チェーンの後ろの部分（頭の無いノーツ＝譜面を組み立てる時は使わない）


class BsorError(ValueError):
    pass


class _R:
    def __init__(self, data):
        self.d, self.p = data, 0

    def take(self, n):
        if self.p + n > len(self.d):
            raise BsorError(f'.bsor が途中で終わっている（{self.p} バイト目で {n} バイト足りない）')
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def i32(self):
        return struct.unpack('<i', self.take(4))[0]

    def i64(self):
        return struct.unpack('<q', self.take(8))[0]

    def f32(self):
        return struct.unpack('<f', self.take(4))[0]

    def u8(self):
        return self.take(1)[0]

    def text(self):
        n = self.i32()
        while n > 1000 or n < 0:   # 公式の DecodeString と同じ: 1 バイトずらして読み直す
            self.take(1)
            n = struct.unpack('<i', self.d[self.p - 4:self.p])[0]
        return self.take(n).decode('utf-8', errors='replace')


def _info(r):
    if r.i32() != MAGIC:
        raise BsorError('.bsor ではない（頭の印が違う）')
    if r.u8() != 1:
        raise BsorError('知らない版の .bsor')
    if r.u8() != 0:
        raise BsorError('情報の部分が無い')
    info = {k: r.text() for k in INFO_KEYS}
    info['score'] = r.i32()
    info['mode'], info['environment'], info['modifiers'] = r.text(), r.text(), r.text()
    info['jump_distance'] = r.f32()
    info['left_handed'] = r.u8() != 0
    info['height'], info['start_time'], info['fail_time'], info['speed'] = r.f32(), r.f32(), r.f32(), r.f32()
    return info


def read_info(path, head=16384):
    """リプレイの頭（曲・難易度・hash・点・修飾…）だけを読む（ファイルの頭の数 KB）"""
    with open(path, 'rb') as f:
        data = f.read(head)
        while True:
            try:
                return _info(_R(data))
            except BsorError:
                more = f.read(head)
                if not more:
                    raise
                data += more


def note_params(note_id):
    """ノーツの番号 → (点の種類, 列, 段, 色, 向き)。公式の NoteParams と同じ分け方（100000 以上は列・段の大きい譜面の形）"""
    i = note_id
    if i < 100000:
        st, i = divmod(i, 10000)
        x, i = divmod(i, 1000)
        y, i = divmod(i, 100)
    else:
        st, i = divmod(i, 10000000)
        x, i = divmod(i, 1000000)
        y, i = divmod(i, 100000)
    c, d = divmod(i, 10)
    return st, x, y, c, d


def _note(r):
    nid, t, spawn, kind = r.i32(), r.f32(), r.f32(), r.i32()
    n = {'id': nid, 'time': t, 'spawn': spawn, 'type': kind}
    if kind in (GOOD, BAD):
        v = _CUT.unpack(r.take(_CUT.size))
        n['cut'] = {'speed_ok': v[0], 'direction_ok': v[1], 'saber_type_ok': v[2], 'too_soon': v[3], 'saber_type': v[8],
                    'distance': v[17], 'before': v[19], 'after': v[20]}
    if nid == -1 or (0 < nid < 100000 and nid % 10 == 9):
        n['id'] = nid + 4
        n['type'] = BOMB
    return n


def parse(data):
    """→ {info, frames（数だけ）, end（最後のフレームの時刻＝記録が終わった所・フレームが無ければ None）, notes: [{id, time, spawn, type, cut?}],
    walls, heights, pauses}"""
    r = _R(data)
    out = {'info': _info(r), 'frames': 0, 'end': None, 'notes': [], 'walls': [], 'heights': [], 'pauses': []}
    return _sections(r, out)


def _sections(r, out):
    data = r.d
    while r.p < len(data):
        kind = r.u8()
        if kind == 1:
            n = r.i32()
            fr = r.take(n * FRAME_SIZE)
            out['frames'] = n
            if n > 0:
                out['end'] = struct.unpack_from('<f', fr, (n - 1) * FRAME_SIZE)[0]
        elif kind == 2:
            out['notes'] = [_note(r) for _ in range(r.i32())]
        elif kind == 3:
            out['walls'] = [{'id': r.i32(), 'energy': r.f32(), 'time': r.f32(), 'spawn': r.f32()} for _ in range(r.i32())]
        elif kind == 4:
            out['heights'] = [(r.f32(), r.f32()) for _ in range(r.i32())]
        elif kind == 5:
            out['pauses'] = [(r.i64(), r.f32()) for _ in range(r.i32())]
        else:
            break   # 6（セイバーのずれ）・7（任意のデータ）は使わない
    return out


def read(path):
    """ファイルを読む（フレームは読み飛ばす＝ファイルの 9 割を読まない・全部の履歴の一覧で 800 個を読むため）"""
    with open(path, 'rb') as f:
        head = f.read(65536)
        try:
            r = _R(head)
            info = _info(r)
        except BsorError:   # 頭が 64KB を超える（無いはず）・途中で終わっている → 全部読む
            f.seek(0)
            return parse(f.read())
        out = {'info': info, 'frames': 0, 'end': None, 'notes': [], 'walls': [], 'heights': [], 'pauses': []}
        f.seek(r.p)
        if f.read(1) == b'\x01':
            b = f.read(4)
            if len(b) < 4:
                raise BsorError('.bsor が途中で終わっている（フレームの数）')
            n = struct.unpack('<i', b)[0]
            end = f.seek(0, 2)
            if n < 0 or r.p + 5 + n * FRAME_SIZE > end:
                raise BsorError('.bsor が途中で終わっている（フレーム）')
            out['frames'] = n
            if n > 0:   # 最後のフレームの時刻だけ読む（記録が終わった所＝途中でやめた・失敗したプレイはそこまで）
                f.seek(r.p + 5 + (n - 1) * FRAME_SIZE)
                out['end'] = struct.unpack('<f', f.read(4))[0]
            f.seek(r.p + 5 + n * FRAME_SIZE)
        else:
            f.seek(r.p)
        return _sections(_R(f.read()), out)


def max_score(notes):
    """切るノーツ（ボムを除く）の満点（コンボの倍率 1→2→4→8 を、出てくる順に掛ける）"""
    total, mult, prog = 0, 1, 0
    for n in sorted((n for n in notes if n['type'] != BOMB), key=lambda n: n['spawn']):
        if mult < 8:
            prog += 1
            if prog >= mult * 2:
                mult, prog = mult * 2, 0
        total += MAX_CUT.get(note_params(n['id'])[0], 115) * mult
    return total


def summary(rep):
    """一覧に出す数: {notes, misses（見逃し）, bad（悪い切り方）, bombs, walls, acc（点÷満点・修飾の掛け算も入った目安）, end（記録が終わった秒）}"""
    ns = rep['notes']
    mx = max_score(ns)
    return {'notes': sum(1 for n in ns if n['type'] != BOMB), 'misses': sum(1 for n in ns if n['type'] == MISS),
            'bad': sum(1 for n in ns if n['type'] == BAD), 'bombs': sum(1 for n in ns if n['type'] == BOMB),
            'walls': len(rep['walls']), 'acc': (rep['info']['score'] / mx) if mx else None,
            'end': round(rep['end'], 3) if rep.get('end') is not None else None}
