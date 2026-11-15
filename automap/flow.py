"""流れと配置（検討の層の ② と ③）: 打点の並びから、手・マス・向きを決める。

打点ごとに「置ける候補」（手・マス・向き）を並べ、減点の合計が一番小さい並びをビームサーチで探す。
減点の考え方は BeatLeader の解析（beatleader-analyzer・MIT）の ParityPredictor / AngleStrain を逆向きに使ったもの:
- 同じ手は振り下ろし側（F）と振り上げ側（B）を交互にする（パリティ）。破るのは十分に間が空いた時だけ（大きな減点）。
- 前の振りの真逆から外れる角度は減点（間が 0.25 秒より空くと BeatLeader と同じ割合で軽くなる）。
- 手首の自然な角度（BeatLeader の中立角: 右手の振り下ろし 247.5°・振り上げ 67.5°、左手は 292.5°・112.5°）からのずれは減点。
- 前の振りの抜けた所から次のノーツの入り口までの移動は減点（間が短いほど重い）。
マス・向きの好み（段・列・斜め・横）は Style の重みで、方針（パラメータ）として人が変えられる。
テーマ（theme.py）がある時は、打点ごとに片手ずつ「型の次の振り」を狙いにし、狙いからのずれ（マス・向き）を減点に足す。
片手ごとに型の何番目まで進んだかを覚え、テーマが変わった（区間が変わった）ら頭に戻す。
"""
import math
import pickle
from dataclasses import dataclass, field, fields
from operator import attrgetter

LEFT, RIGHT = 0, 1          # 色 c: 0＝赤＝左手、1＝青＝右手
F, B = 0, 1                 # 振り下ろし側（forehand）・振り上げ側（backhand）
DIR_ANGLE = {0: 90, 1: 270, 2: 180, 3: 0, 4: 135, 5: 45, 6: 225, 7: 315}
DIR_VEC = {d: (math.cos(math.radians(a)), math.sin(math.radians(a))) for d, a in DIR_ANGLE.items()}
DIR_SPACE = {0: (0, 1), 1: (0, -1), 2: (-1, 0), 3: (1, 0), 4: (-1, 1), 5: (1, 1), 6: (-1, -1), 7: (1, -1)}   # 振り抜ける先のマス（NLM の mapcheck.js と同じ）
MIRROR_D = {0: 0, 1: 1, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}
NEUTRAL = {(RIGHT, F): 247.5, (RIGHT, B): 67.5, (LEFT, F): 292.5, (LEFT, B): 112.5}
VERT, DIAG, SIDE = {0, 1}, {4, 5, 6, 7}, {2, 3}

# 手元の譜面 930曲の Expert+ の平均（docs/方針.md。向きは点を除いて割り直した値。真ん中・同じマスは未集計の仮の値）
LIBRARY_EPLUS = {'row': (0.47, 0.27, 0.26), 'dir': (0.52, 0.41, 0.07), 'center': 0.05, 'still': 0.30, 'alt': 0.69,
                 'col': (0.23, 0.27, 0.27, 0.24)}


def dir_class(d):
    return 0 if d in VERT else 1 if d in DIAG else 2


def parity_of(c, d):
    """その手でその向きに切る振りが、振り下ろし側（F）か振り上げ側（B）か。点（8）は None。"""
    if d in (1, 6, 7):
        return F
    if d in (0, 4, 5):
        return B
    if d == 2:          # 左へ: 右手は体の方へ＝F、左手は外へ＝B
        return F if c == RIGHT else B
    if d == 3:
        return F if c == LEFT else B
    return None


def angle_between(d1, d2):
    a = abs(DIR_ANGLE[d1] - DIR_ANGLE[d2]) % 360
    return 360 - a if a > 180 else a


@dataclass
class Style:
    """方針の数字（減点の重み）。初期値は手元の譜面の統計（docs/方針.md）を見ながら決めた仮の値。"""
    beam: int = 96
    seed: int = 1
    noise: float = 0.12          # 種による揺らぎ（同じ点数の候補から別の案を選ぶため。値は候補ごとに決まる＝_jitter）
    w_a45: float = 0.25          # 前の振りの真逆から 45° ずれる
    w_a90: float = 2.5           # 90° ずれる
    w_neutral: float = 1.5       # 手首の自然な角度からのずれ（(ずれ/180)^2 に掛ける）
    w_travel: float = 0.55       # 抜けた所から次の入り口までの移動（マス）
    travel_k: float = 0.8        # ノーツの中心から振りの抜けた所・入り口までの距離（マス）
    w_repeat: float = 0.12       # 同じ手が同じマスを続ける（2回目から1回ごと）
    w_same_hand: float = 0.10    # 片手の打点が同じ手で続く（割合は targets の alt で合わせる）
    min_gap: float = 0.12        # 同じ手の振りの最短の間（秒）。これより短いと大きく減点
    w_fast: float = 6.0
    reset_gap: float = 1.5       # 振りの交互を破ってよい間（秒）
    w_reset: float = 3.0
    w_first_up: float = 0.5      # 最初の振りが振り上げ
    w_beat: float = 0.15         # 拍の頭で振り上げ／裏で振り下ろし
    w_diag: float = 0.05         # 斜め・横・真ん中の多さは targets で合わせる。ここは体の負担の分だけ
    w_side: float = 0.20
    w_center: float = 0.30       # 真ん中の段の中央2列（視界をふさぐ）
    w_cross_dyn: float = 1.0     # もう片方の手の最近の位置をまたぐ
    w_stack_col: float = 1.0     # 両手同時で同じ列（上下に重なる）
    w_mirror: float = -0.35      # 両手同時が左右の鏡写し（ごほうび）
    w_mixed: float = 0.6         # 両手同時で片方が振り下ろし・片方が振り上げ
    w_accent: float = 1.2        # 山の音で上の段（外側の列はその半分）を選ぶごほうび
    w_top_again: float = 1.0     # 同じ手が続けて振り上げで上の段まで行く
    w_inline: float = 4.0        # もう片方の手が直前（0.2 秒未満・0.35 秒未満は 3 割）に置いたマスに置く（NLM の hitboxInline・2D で後ろに急に現れて見える）
    w_stair: float = 4.0         # もう片方の手が直前に振り抜けたマスに置く（NLM の譜面チェックの hitboxStair）
    w_shrado: float = 4.0        # 斜めの振り下ろしの直後に動いて真上（NLM の譜面チェックで注意）
    w_handclap: float = 8.0      # 両手同時が手拍子の形・振りの通り道に相手のノーツ（NLM の譜面チェックの handclap・hitboxPath でエラー）
    w_theme_cell: float = 1.2    # テーマの狙いのマスからのずれ（マス）
    w_theme_dir: float = 0.6     # テーマの狙いの向きからのずれ（45° ごと）
    w_theme_skip: float = 0.4    # 振りの交互を合わせるために型を1つ飛ばす
    w_fix: float = 4.0           # 決めたノーツ（Event.fix・意思入れの同じ振り）からのずれ（マス・45° ごと。別の手は 3 つ分）
    w_pitch: float = 0.0         # 歌の高さの狙いの段（Event.py）からのずれ（段ごと）。人の譜面は歌が高いと少し高い段（相関 +0.04〜0.08）
    # 片手だけで速く続ける振りは利き手（右手）に（2026-11-03 利用者「難しい高速な大量配置は右手側に・右利き用の譜面が基本」）: 左手が、もう片方の
    # 手がその間に振っていない（同時は振っていないとみる）のに left_fast_s 秒より短い間で続けて振る時の減点（間が短いほど重い・0＝前と同じ答え）。
    # 前は手の割り振りに左右の好みが無く、候補を数える順（左手が先）で同点に近い時は左手になりやすかった（Joy to the love で左 16・右 6）
    w_left_fast: float = 0.0
    left_fast_s: float = 0.3
    # 技術的に難しい振り（向きの曲がり＝前の振りの真逆から外れる・大きな移動）も利き手（右手）に（2026-11-03 利用者「それも右手側に」）:
    # 角度の減点と移動の減点を左手は (1＋w_hand_tech) 倍・右手は (1−w_hand_tech) 倍（全体の難しさは変えずに右へ回す・0＝前と同じ答え）
    w_hand_tech: float = 0.0
    # 左右の受け渡し（Event.want・Event.hoflex・automap/handoff.py）: 使いたい手と違う手の減点・反転の狙いからのずれ（マス・45° ごと）
    w_want: float = 2.5
    w_ho_mirror: float = 3.0     # 1.5 では手から見たマスの目標（重み 12）等に負けて、位相が合う所でも反転にならなかった
    w_ho_lead: float = 0.3       # 反転の受け渡しの先の手が左手（人は反転の 65% が右から）
    w_echo: float = 3.0          # 続けて左右反転（Event.echo）: 1 セット前の打点の左右反転からのずれ（マス・45° ごと）
    w_echo_want: float = 3.5     # 1 セット前と同じ手（反転は手を入れ替える）
    w_echo_phase: float = 2.0    # 振りの向きの位相が逆で反転を置けない
    w_loop: float = 2.0          # 短い往復（Event.loop）: 同じ手の 2 つ前の振りの置き方からのずれ（マス・45° ごと）
    w_erun: float = 5.0          # 続けて左右反転の前のセットを片手に（Event.erun）: セットの最初の打点と違う手（2.5 だと片手にならない所が多かった）
    w_ho_want: float = 3.5       # 反転の受け渡しで使いたい手と違う手（決め打ちの受け渡しの w_want より強く・2.5 では先の手の 2 振り目で手が変わった）
    row_cost: dict = field(default_factory=lambda: {F: (0.0, 0.1, 0.2), B: (0.0, 0.1, 0.3)})
    col_cost: tuple = (2.0, 0.9, 0.12, 0.0)   # 右手の列 0..3（左手は左右反転）
    # 目標の割合（方針）。直近の割合が目標より多い種類を選ぶと減点・少ない種類はごほうび（ずれを戻す形）。
    # 減点だけだと「下段・上下・動かない」が一番安く、単調な譜面になるため（試作0の最初の結果）。
    targets: dict = field(default_factory=lambda: dict(LIBRARY_EPLUS))
    w_target: dict = field(default_factory=lambda: {'row': 4.0, 'dir': 4.0, 'center': 3.0, 'still': 3.0, 'alt': 2.0, 'col': 4.0})

    def static_options(self):
        """(手, 振り) ごとの候補 [(静的な減点, x, y, d)]。"""
        out = {}
        for h in (LEFT, RIGHT):
            for q in (F, B):
                opts = []
                for d in range(8):
                    if parity_of(h, d) != q:
                        continue
                    dev = angle_between_deg(NEUTRAL[(h, q)], DIR_ANGLE[d])
                    base_d = self.w_neutral * (dev / 180) ** 2 + (self.w_diag if d in DIAG else self.w_side if d in SIDE else 0)
                    for x in range(4):
                        cx = self.col_cost[x] if h == RIGHT else self.col_cost[3 - x]
                        for y in range(3):
                            c = base_d + cx + self.row_cost[q][y]
                            if x in (1, 2) and y == 1:
                                c += self.w_center
                            opts.append((c, x, y, d))
                opts.sort()
                out[(h, q)] = opts
        return out


def _pointing(ax, ay, ad, bx, by, deg):
    """a の向きが b の方を deg° 以内で向いているか（NLM の mapcheck.js の isNotePointing と同じ考え）"""
    vx, vy = bx - ax, by - ay
    if vx == 0 and vy == 0:
        return False
    a = math.degrees(math.atan2(vy, vx)) % 360
    return angle_between_deg(a, DIR_ANGLE[ad]) <= deg


def handclap(lx, ly, ld, rx, ry, rd):
    """両手同時の2つが手拍子の形（近くで向かい合う・背を向け合う）か。NLM の譜面チェックの handclap と同じ条件"""
    d = math.hypot(lx - rx, ly - ry)
    pab, pba = (lambda t: _pointing(lx, ly, ld, rx, ry, t)), (lambda t: _pointing(rx, ry, rd, lx, ly, t))
    return ((d <= 1 and pab(45) and pba(45)) or (d <= 1.5 and pab(30) and pba(30)) or (d <= 2 and pab(15) and pba(15))
            or (d <= 1 and not pab(135 - 1e-3) and not pba(135 - 1e-3)) or (d <= 1.5 and not pab(160 - 1e-3) and not pba(160 - 1e-3)))


def hitbox_path(lx, ly, ld, rx, ry, rd):
    """両手同時の片方の振りが入ってくる側（矢印の逆側）の近く（2マス以内）に、もう片方のノーツがあるか。
    NLM の譜面チェックの hitboxPath と同じ条件（向きが相手から 150° より外れている＝相手が振りの入り口の側にいる）"""
    if math.hypot(lx - rx, ly - ry) > 2:
        return False
    return not _pointing(lx, ly, ld, rx, ry, 150) or not _pointing(rx, ry, rd, lx, ly, 150)


def angle_between_deg(a1, a2):
    a = abs(a1 - a2) % 360
    return 360 - a if a > 180 else a


@dataclass
class Event:
    beat: float
    sec: float
    hands: int          # 1＝片手・2＝両手同時
    gid: int = -1       # テーマの番号（-1＝テーマ無し）
    cyc: dict = None    # {手: [(x, y, d)]} その打点で狙う型（左手は左右反転済み）
    accent: bool = False  # 山の音（上の段・外側の大きな振りを好む）
    strong: float = 0.0   # この打点を振り上げで打つ減点（区間の頭・両手同時など、振り下ろしで打ちたい強い打点）
    py: float = None      # 歌の高さから狙う段（0〜2・無ければ None）
    min_gap: float = None  # この打点の同じ手の振りの最短の間（秒・無ければ Style.min_gap。意思入れの振りの速さの上限）
    fix: dict = None      # {手: (x, y, d)} この打点で置きたいノーツ（意思入れの同じ振り＝手本の所と同じ置き方）。強い減点で寄せる（前の振りがそれに合うように選ばれる）
    fix_w: float = None   # fix の重み（無ければ Style.w_fix）。NLM で直して残したノーツは強く（出力に入らず、合わないと本物の譜面の振りが崩れる）
    mods: dict = None     # 意思入れの置き方の指示 {move, width, height, diag, turn, bigmove: 値}（区間の中の打点だけ・intent.PLACE）
    relief: float = 0.0   # 息つぎの打点（automap/relief.py）: テーマに沿う重みの倍率。手から見た列・マスの目標を効かせず、その直近の割合も数えない（0＝今まで通り）
    # 左右の受け渡し（automap/handoff.py）: want＝この片手の打点で使いたい手（違う手は Style.w_want〔want_w があればそれ〕の減点・
    # 同じ手の続きの減点と w_left_fast は掛けない）。hoflex＝(始まりの拍, 段の数): 左右反転の受け渡し。手と始まりは流れの計算が候補ごとに
    # 決める（generate の flex）。どれも None なら今まで通り
    want: int = None
    want_w: float = None
    hoflex: tuple = None
    echo: float = None    # 続けて左右反転（automap/echo.py）: セットの長さ（拍）＝1 セット前の同じ拍の打点の、手を入れ替えた左右反転に寄せる（Style.w_echo）
    loop: float = None    # 短い往復（automap/loops.py）: この拍から始まる往復の区間の中＝同じ手の 2 つ前の振り（区間の中）と同じ置き方に寄せる（Style.w_loop）
    erun: float = None    # 続けて左右反転の前のセットを片手に（automap/echo.py）: セットの始まりの拍。同じ印の最初の打点の手は候補ごとに選び（後ろの
    #                       セットの反転を置ける方が残る）、後の打点はその手（違う手は Style.w_want・同じ手の続きの減点は掛けない）
    ho: int = None        # 受け渡しの番号（報告用）


# 片手の状態: (振り, x, y, d, 秒, 打点の番号, 同じマスの続き, テーマの番号, 型の何番目まで進んだか, 前の振り上げが上の段か)。
# 振りが None＝まだ振っていない
NO_HAND = (None, None, None, None, -99.0, -1, 0, -1, 0, False)


# 目標の割合の追い方: 直近の割合（指数移動平均）を状態に持ち、選んだ種類の「直近の割合 − 目標」を足す
# （多すぎる種類は減点・足りない種類はごほうび）。曲全体でなく直近で見るのは、場所ごとにも偏らせないため。
A_NOTE, A_MOVE, A_ALT = 1 / 24, 1 / 16, 1 / 16
# 両手の広がり（2026-11-03・docs/方針.md 6.21）: 手から見た列 r（右手は r=x・左手は r=3−x。0＝反対の外・1＝反対の内・2＝自分の内・
# 3＝自分の外）の割合（targets の hcol・重み w_target の hcol）と、両手を同時に外へ（左手が列 0・右手が列 3）の割合（wide）。
# wide は置くたびに、もう片方の手の直前の振り（PAIR_S 秒以内）と組にして数える（ランク譜面を数えた物差しと同じ・tools/library_spread.py）。
# 減点は広げた組を選んだ時だけ「直近の割合 − 目標」（少なければごほうび）。重みが 0（既定）なら今までと全く同じ答え。
# 意思入れの「横の広がり +1」（mods の width > 0）の打点は、この2つを効かせない（4 列を使い切る指示）。
A_PAIR = 1 / 24
PAIR_S = 1.0
HCOL0 = (0.0, 0.17, 0.38, 0.45)   # 目標に hcol が無い時の直近の割合の初め（ランク譜面の中央くらい）
WIDE0 = 0.16
# 手から見たマス（2026-11-03・docs/方針.md 6.22）: 番号＝rx×3＋y（rx は右手は x・左手は 3−x）の割合（targets の cell・重み w_target の cell）。
# 作った譜面はどの曲も 31 と 20 の2マスに振りの 62〜78% が集まり（ランク譜面は約 48%）、曲どうしが似た。初めの値はランク譜面（1秒の振り 4.5）
CELL0 = (0.009, 0.007, 0.001, 0.158, 0.009, 0.030, 0.242, 0.016, 0.107, 0.110, 0.240, 0.071)


def _ema0(t):
    hc = tuple(t.get('hcol') or HCOL0)
    k0 = tuple(t.get('cell') or CELL0)
    return (tuple(t['row']), tuple(t['dir']), t['center'], t['still'], t['alt'], tuple(t['col']), (hc, hc), float(t.get('wide', WIDE0)), (k0, k0))


def init_from(notes, tempo):
    """残すノーツ（[{beat, x, y, c, d}]）の最後の振りから、続きを作り始める時の (左手, 右手, 最後の片手の打点の手)。
    人が直した所の後ろだけ作り直す時に、振りの交互・位置・向きを引き継ぐ"""
    hands, last = [NO_HAND, NO_HAND], -1
    byb = {}
    for n in notes:
        byb.setdefault(round(n['beat'], 4), []).append(n)
    for b in sorted(byb):
        ns = byb[b]
        cs = {n['c'] for n in ns if n['c'] in (LEFT, RIGHT)}
        for n in ns:
            if n['c'] not in (LEFT, RIGHT):
                continue
            q = parity_of(n['c'], n['d'])
            if q is None:   # 点ノーツ: 前の振りの逆とみなす
                pq = hands[n['c']][0]
                q = None if pq is None else 1 - pq
            d = n['d'] if n['d'] != 8 else (1 if q == F else 0)
            hands[n['c']] = (q, n['x'], n['y'], d, tempo.sec(n['beat']), -1, 0, -1, 0, q == B and n['y'] == 2)
        last = next(iter(cs)) if len(cs) == 1 else -1
    return hands[LEFT], hands[RIGHT], last


# 意思入れの置き方の指示（区間の中の打点だけ・Event.mods）の減点（負＝ごほうび）。大きさは w_center・col_cost・w_diag と同じくらい
# （指示した区間ではっきり変わるが、振りの交互・手拍子形などの減点には勝たない）。mods の無い打点には何も足さない＝今までと同じ結果
MOD_W = {'width': 1.2, 'height': 1.2, 'diag': 1.0, 'move': 0.5, 'turn': 1.0}


# 種による揺らぎ（Style.noise）は、候補ごとに（種・打点の拍・手・振り・マス・向き）から決まる値にする。
# 前は曲の頭からの1本の乱数の列（random.Random(seed)）を候補を数えた順に取り出していたので、どこかの区間で打点・候補の数が
# 1つ変わると後ろの揺らぎが全部ずれ、指示を1つ変えただけでその区間の後ろの譜面がほぼ全部変わった（docs/アプリ仕様.md 11 節）。
# 値は前の状態（どのビームの候補から来たか）によらない＝メモ（opts_for の memo）で同じ状態の候補を使い回しても同じ。
# 速い整数のハッシュ（splitmix64 の混ぜ方）。Python の hash() は文字列だと起動ごとに変わるので使わない
_M64 = (1 << 64) - 1


def _mix64(z):
    z = (z + 0x9E3779B97F4A7C15) & _M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return z ^ (z >> 31)


def _jitter_key(seed, beat):
    """打点の揺らぎの元（種と打点の拍から）。拍は 1/10000 拍に丸める（同じ拍が計算の道筋で少しずれても同じ値）"""
    return _mix64(_mix64(int(seed) & _M64) ^ (round(beat * 10000) & _M64))


def _jitter(key, h, q, x, y, d):
    """その打点の候補（手・振り・マス・向き）の揺らぎ 0〜1"""
    return (_mix64(key ^ (h | q << 1 | x << 2 | y << 4 | d << 6)) >> 11) * (1.0 / (1 << 53))


# 流れの計算の本体（ビームサーチ）は automap/flow_nb.py（Numba・2026-11-10）。ここの表は flow_nb も使う
_ANG = tuple(tuple(angle_between(a, b) for b in range(8)) for a in range(8))
_RX = ((3, 2, 1, 0), (0, 1, 2, 3))   # 手から見た列（左手は 3−x）
# 確かめ用の数: memo＝直前と同じ入力で覚えた答えを返した数
STATS = {'memo': 0}

# 同じ入力の計算は覚えた答えを返す（2026-11-09・答えは計算した時と同じ）: 作り直しは、打点・方針・始まりが全く同じ generate を続けて
# 呼ぶ所がある（同じ振りの入りを合わせる回で抜く・足すが無かった時など・BURN・ハロで 5〜6 秒）。覚えるのは直前の 1 件だけ。
# 指紋は答えに効く物の全部＝打点の全部の項目（Event の型の項目・後から足した印は generate が読まないので入れない）・方針（Style の型と
# 全部の項目）・始まり（init）を pickle で並べたバイト列（float はビットのまま・int と bool・tuple と list も別＝値が違えば必ず違う。
# 同じ値でも並べ方が違えば違う指紋になるが、それは計算し直すだけ）。返すのは写し（呼ぶ側がノーツを書き換えても覚えた物は変わらない）
_LAST = {}
_EV_KEY = attrgetter(*(f.name for f in fields(Event)))
_ST_KEY = attrgetter(*(f.name for f in fields(Style)))


def _fingerprint(events, st, init):
    try:
        return pickle.dumps((type(st), _ST_KEY(st), init, [_EV_KEY(e) for e in events]), protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:   # pickle にできない物が入っていたら覚えない（毎回計算する）
        return None


def forget():
    """覚えた答えを捨てる（確かめで、同じ入力を続けて計算させる時）"""
    _LAST.clear()


def generate(events, style=None, init=None):
    """打点の並び → (ノーツ [{beat, x, y, c, d}], 減点の合計)。init＝init_from の戻り値（前の振りを引き継いで始める）。
    直前と同じ入力なら計算せずに覚えた答えの写しを返す（_LAST）。"""
    st = style or Style()
    key = _fingerprint(events, st, init)
    if key is not None and _LAST.get('key') == key:
        STATS['memo'] += 1
        notes, cost = _LAST['out']
        return [dict(n) for n in notes], cost
    from . import flow_nb   # 本体（Numba・flow を読み込むので、ここで読む）
    notes, cost = flow_nb.search(events, st, init)
    if key is not None:   # ノーツの値は数（int・float）だけ＝辞書ごとの写しで深い写しと同じ
        _LAST.clear()
        _LAST.update(key=key, out=([dict(n) for n in notes], cost))
    return notes, cost
