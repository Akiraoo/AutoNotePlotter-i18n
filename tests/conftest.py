"""テスト全体の下ごしらえ（並べて流す決まり・CLAUDE.md の「テスト・実行」）

- 既定で並べて流す（pytest.ini の -n auto＝pytest-xdist）。1 本で流すのは -n 0（--pdb の時は部品が自分で 1 本にする）。
- 働き手の数（auto・pytest_xdist_auto_num_workers）: 全部の時は物理コアの 4/3（psutil・このPC 12 → 16）。選んだテストの見込み
  （前回の時間の合計）が短い時は減らす: 4 秒未満は並べない・それ以上は見込み÷3 秒の本数（起動の分の方が長い）。テストを 1 つだけ
  指した時（tests/x.py::test_y）も並べない。環境変数 PYTEST_XDIST_AUTO_NUM_WORKERS があればその数（見込みで減らさない）。
  働き手の計算のスレッドは 1 本（pytest_configure）。
- 配り方（pytest_xdist_make_scheduler）: 前回落ちたテスト（.pytest_cache の cache/lastfailed）を一番先に、ほかは前回かかった時間
  （automap/durations・終わるたびに書き足す）の長い順に 1 件ずつ。働き手は「走っている 1 件＋次の 1 件」を持つので、長いテストの
  後ろに控える次の 1 件は短いテストにする（長い物を控えさせると、一番長い曲の解析の後ろに 5 秒のテストが並び全体が延びた）。
  初めて流す時（控えが無い）・知らないテストは並びの順（知らない物は 1 秒と見る）。
- 曲の解析の答え合わせ（tests/test_song_analysis.py）を控えで済ませた時は、かかった時間を控えに書かない（計算した時の長さのまま＝
  計算し直す回も一番先に配る）。控えで済ませたか・計算したかは出力の終わりに 1 行ずつ（pytest_terminal_summary）。
"""
import json
import math
import os
from pathlib import Path

import pytest

# 並べて流す時、働き手のプロセスは起動の文を標準入力から UTF-8 で受け取るが、Windows の子のプロセスは標準入力を cp932 で
# 読むので、フォルダ名の日本語（リポジトリの置き場など）が化けて起動できない（execnet の gateway_bootstrap）。アプリも子の
# プロセスには同じ値を渡している（app/server.py・expand.py・importer.py）。
os.environ['PYTHONIOENCODING'] = 'utf-8'

DUR_KEY = 'automap/durations'
SHORT = 0.5      # これより短いテストは重さ 0（同じ重さは並びの順のまま・長いテストの後ろに控える次の 1 件に使う）
UNKNOWN = 1.0    # 控えに無いテスト（足したばかり）の見込み
_ran = {}        # このセッションでかかった時間（準備・本体・後始末の合計）
_collected = None   # このセッションで集めたテスト（全部を流した時に控えから今は無いテストを落とすため）


def _durations(config):
    cache = getattr(config, 'cache', None)
    return (cache.get(DUR_KEY, {}) if cache else {}) or {}


_memo_lines = []    # 曲の解析の答え合わせ（tests/test_song_analysis.py）の結果の 1 行（控えで済ませたか・計算したか）
_memo_hits = set()  # 控えで済ませたテスト＝かかった時間を控えに書かない（計算した時の長さのまま＝次も一番先に配る）


def pytest_runtest_logreport(report):
    _ran[report.nodeid] = _ran.get(report.nodeid, 0.0) + report.duration
    if report.when == 'call':
        for k, v in getattr(report, 'user_properties', ()) or ():
            if k == 'automap_memo':
                _memo_lines.append(v)
            elif k == 'automap_memo_hit' and v:
                _memo_hits.add(report.nodeid)


def pytest_terminal_summary(terminalreporter):
    """曲の解析の答え合わせを控えで済ませたかを終わりに出す（-q でも出る）"""
    for line in sorted(_memo_lines):
        terminalreporter.write_line(line)


def pytest_collection_finish(session):
    global _collected
    if not hasattr(session.config, 'workerinput'):
        _collected = {it.nodeid for it in session.items}   # 1 本で流した時（並べた時は配り役が覚える）


def pytest_sessionfinish(session):
    """かかった時間を控えに書き足す（取りまとめ役だけ。働き手は自分の分しか知らない）。全部を流した時は、今は無いテスト
    （消した・名前を変えた）を控えから落とす（残すと、選んだテストの見込み・--lf の見込みが狂う）"""
    config = session.config
    cache = getattr(config, 'cache', None)
    if not cache or hasattr(config, 'workerinput') or not _ran:
        return
    d = _durations(config)
    d.update({k: round(v, 3) for k, v in _ran.items() if not (k in _memo_hits and k in d)})
    o = config.option
    whole = (_collected and not (o.keyword or o.markexpr or o.lf or getattr(o, 'deselect', None))
             and {Path(a).resolve() for a in config.args} == {(Path(config.rootpath) / t).resolve() for t in config.getini('testpaths')})
    if whole:
        d = {k: v for k, v in d.items() if k in _collected}
    cache.set(DUR_KEY, d)


THREAD_VARS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')


def pytest_configure(config):
    """並べて流す時、働き手の計算の部品（numpy の BLAS・numba）のスレッドは 1 本に（働き手ごとにコアの数だけ立てて取り合うと、
    一番長い曲の解析が 1 本の時より 1.5 倍遅くなった。1 本で流す時の解析の速さはほぼ同じ）。働き手は起動の時の環境を受け継ぐ"""
    if getattr(config.option, 'numprocesses', None) and not hasattr(config, 'workerinput'):
        for k in THREAD_VARS:
            os.environ.setdefault(k, '1')


AUTO_RATIO = 4 / 3   # 全部の時の働き手＝物理コアの 4/3（決めた時の測りは下）
SMALL_EST = 4.0      # 見込みがこれより短い選び方は並べない（秒）
PER_WORKER = 3.0     # それより長い時は見込み÷これ の本数
# 働き手の数を決めた時の測り（2026-11-09・静かな時・626 本）: 12 本 30.7〜31.8 秒・16 本 27.9〜28.6 秒・20 本 29.7 秒。
# 20 本より多いと、一番長い曲の解析（構成・1 本で 20 秒ほど）が同じコアのもう片方と取り合って 23 秒に延び、働き手を 1 つずつ起こす分
# （1 つ 0.09 秒）とテストを集める取り合いで最初のテストまでが 3.0 → 4.2 秒に延びる。前に「論理コアの 24 は少し遅かった」のも同じ理由。
# 小さい選び方（1 本・4 本・12 本）: test_nlmf 1.3・2.0・2.8 秒／test_intent 4.3・5.2・5.8 秒／test_kime 7.6・4.3・5.5 秒。


def _cache_value(config, key):
    """.pytest_cache の値を直に読む（働き手の数を決める時は config.cache がまだ無い）。-p no:cacheprovider の時は None"""
    try:
        d = Path(os.path.expandvars(config.getini('cache_dir'))).expanduser()
    except ValueError:
        return None
    if not d.is_absolute():
        d = Path(config.rootpath) / d
    try:
        return json.loads((d / 'v' / key).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _selected(config, durs):
    """選んだテストの nodeid（前回の時間の控えにある物）。見込めない選び方（-m・控えに無いファイル・場所の外）は None"""
    if getattr(config.option, 'markexpr', ''):
        return None
    root = Path(config.rootpath).resolve()
    inv = Path(config.invocation_params.dir)
    picked = set()
    for a in config.args:
        path, sep, rest = a.partition('::')
        p = Path(path)
        try:
            rel = (p if p.is_absolute() else inv / p).resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            return None
        if sep:
            want = f'{rel}::{rest}'
            hit = {k for k in durs if k == want or k.startswith(want + '[') or k.startswith(want + '::')}
            picked |= hit or {want}   # 控えに無い 1 件（足したばかり）は知らない物として数える
        else:
            pre = rel + ('::' if rel.endswith('.py') else '/')
            hit = {k for k in durs if rel in ('.', '') or k.startswith(pre)}
            if not hit:
                return None   # 控えに無いファイル・フォルダ＝何件あるか分からない
            picked |= hit
    kw = getattr(config.option, 'keyword', '')
    if kw:
        try:
            from _pytest.mark.expression import Expression
            expr = Expression.compile(kw)
        except Exception:   # noqa: BLE001
            return None

        def keep(nid):
            names = [n.lower() for n in nid.replace('/', '::').split('::')]
            return expr.evaluate(lambda s, **_: any(s.lower() in n for n in names))

        picked = {k for k in picked if keep(k)}
    if getattr(config.option, 'lf', False):
        failed = {k for k in (_cache_value(config, 'cache/lastfailed') or {}) if _alive(root, k)}
        if picked & failed:   # 落ちた物が今は無い（名前を変えた・消した）時は pytest も全部を流す
            picked &= failed
    return picked


def _alive(root, nodeid):
    """そのテストが今もありそうか（ファイルがあり、関数の定義が書いてある。控えには消した・名前を変えたテストも残る）"""
    path, _, rest = nodeid.partition('::')
    name = rest.split('::')[-1].split('[')[0]
    try:
        return f'def {name}(' in (root / path).read_text(encoding='utf-8')
    except OSError:
        return False


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config):
    """-n auto の働き手の数（冒頭の説明）。環境変数 PYTEST_XDIST_AUTO_NUM_WORKERS があれば部品の既定（その数）"""
    if os.environ.get('PYTEST_XDIST_AUTO_NUM_WORKERS'):
        return None
    args = [a for a in config.args if not a.startswith('-')]
    single = len(args) == 1 and '::' in args[0]   # テストを 1 つだけ指した（parametrize の物は控えにある数で見込む）
    try:
        import psutil
        phys = psutil.cpu_count(logical=False) or os.cpu_count() or 1
        logical = psutil.cpu_count() or phys
    except ImportError:
        logical = os.cpu_count() or 1
        phys = max(1, logical // 2)
    cap = max(1, min(logical, round(phys * AUTO_RATIO)))
    durs = _cache_value(config, DUR_KEY) or {}
    sel = _selected(config, durs)
    if sel is None:
        return 0 if single else cap
    est = sum(durs.get(k, UNKNOWN) for k in sel)
    if est < SMALL_EST or len(sel) <= 1:
        return 0
    return max(2, min(cap, len(sel), math.ceil(est / PER_WORKER)))


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_make_scheduler(config, log):
    if config.getoption('dist') != 'load':
        return None   # --dist loadfile 等は部品の物
    from xdist.scheduler import LoadScheduling

    durs = _durations(config)
    failed = set((config.cache.get('cache/lastfailed', {}) if getattr(config, 'cache', None) else {}) or {})

    def weight(nodeid):
        d = durs.get(nodeid)
        return UNKNOWN if d is None else (0.0 if d < SHORT else d)

    class LongFirst(LoadScheduling):
        """前回落ちた物を先に・長い順に 1 件ずつ配る。働き手には「走っている 1 件＋次の 1 件」を持たせ（部品の決まり＝次の 1 件が
        届くまで走り出さない）、走っている（次に走る）物が長ければ次の 1 件は短いテスト（並びの一番後ろ）、短ければ残りの一番長い物"""

        def __init__(self, config, log=None):
            super().__init__(config, log)
            if self.maxschedchunk is None:
                self.maxschedchunk = 1
            self.w = {}
            self.first = set()

        def _send_one(self, node):
            q = self.node2pending[node]
            ahead = q[-1] if q else None   # 送る物はこれの後ろに並ぶ
            tail = self.pending[-1]
            short_behind_long = ahead is not None and self.w.get(ahead, UNKNOWN) > 0 and self.w.get(tail, UNKNOWN) == 0
            i = self.pending.pop(-1 if short_behind_long else 0)
            q.append(i)
            node.send_runtest_some([i])

        def schedule(self):
            assert self.collection_is_completed
            if self.collection is not None:
                return super().schedule()   # 働き手が後から増えた時
            if not self._check_nodes_have_same_collection():
                self.log('**Different tests collected, aborting run**')
                return
            col = self.collection = next(iter(self.node2collection.values()))
            global _collected
            _collected = set(col)
            if not col:
                return
            self.w = {i: weight(col[i]) for i in range(len(col))}
            self.first = {i for i in range(len(col)) if col[i] in failed}
            # 前回落ちた物が先・同じ組の中は長い順・同じ重さは並びの順のまま
            self.pending[:] = sorted(range(len(col)), key=lambda i: (i not in self.first, -self.w[i]))
            for _ in range(2):
                for node in self.nodes:
                    if self.pending:
                        self._send_one(node)
            if not self.pending:
                for node in self.nodes:
                    node.shutdown()

        def check_schedule(self, node, duration=0):
            """1 件終わるたびに 1 件足す（部品の既定は残りの数から何件かまとめて送る＝長い物の後ろに長い物が並ぶ）"""
            if node.shutting_down:
                return
            if self.pending:
                if len(self.node2pending[node]) < 2:
                    self._send_one(node)
            else:
                node.shutdown()

    return LongFirst(config, log)


# ---- 試験用の固定の★の物差し（automap/rating_scale.py） ----
# ★の帯の決まり・NJS の式の決まりを確かめるテストは今の物差しの数に頼らない＝tools/library_build/update_rating.py で物差しを更新しても
# テストを直さなくてよい。使う所は pytestmark = pytest.mark.usefixtures('pinned_scale')
PINNED_NJS = {'stars': {'base': 8.57, 'x': 0.538, 'bpm': 0.0117, 'diff': {'Easy': 0.0, 'Normal': 1.09, 'Hard': 2.03, 'Expert': 2.97, 'ExpertPlus': 3.61}},
              'nps': {'base': 9.56, 'x': 0.685, 'bpm': 0.0069, 'diff': {'Easy': 0.0, 'Normal': 0.94, 'Hard': 1.64, 'Expert': 2.55, 'ExpertPlus': 3.38}}}


@pytest.fixture
def pinned_scale(monkeypatch):
    from automap import library_use as LU, njs, rating_scale as RS
    monkeypatch.setattr(RS, 'MOVED', {})
    monkeypatch.setattr(LU, 'BAND_STEPS', (0, 4, 6, 8, 10, 12, 99))
    monkeypatch.setattr(LU, 'BAND_CHOICES', ([0, 6], [0, 8], [4, 8], [6, 10], [8, 12], [10, 99]))
    monkeypatch.setattr(LU, 'NPS_BANDS', ([0, 4], [4, 6], [6, 8], [8, 10], [10, 12]))
    monkeypatch.setattr(LU, 'NPS_REF', {(0, 4): 3.1, (4, 6): 4.2, (6, 8): 5.7, (8, 10): 7.4, (10, 12): 9.3})
    monkeypatch.setitem(LU.DEFAULT, 'stars', [0, 8])
    monkeypatch.setitem(LU.LEGACY_DEFAULT, 'stars', [0, 8])
    monkeypatch.setattr(njs, 'COEF', PINNED_NJS)
