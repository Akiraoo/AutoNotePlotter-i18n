"""別の案と履歴（docs/アプリ仕様.md 8 節の3・4）: 選んだ区間で別の案を作って見比べて選ぶ・作り直すたびに控えを取って戻す。
server.py の connect() が routes(ctx) を呼んでつなぐ（ctx＝server モジュール。作り直しの前後は ctx.BEFORE_GENERATE・AFTER_GENERATE）。

履歴: <OUT>/.history/<曲>/ に結果のファイルの版を控える（<曲>.<版>.nlmf・その時の作業ファイル <曲>.<版>.automap.json・報告
<曲>.<版>.report.md・一覧 index.json＝時刻・したこと・区間・ノーツの数・報告の要点・こちらで書いたままか・「残す」印）。
- 作り直しの後（AFTER_GENERATE）に作った版を控える。作り直しの前（BEFORE_GENERATE）・戻す前・案を選ぶ前に、今の結果のファイルが
  どの版とも違えば（NLM で直して保存した等）先に控える＝何も失わない。曲ごとに HIST_MAX 版まで（「残す」印と今の版は消さない）。
- 戻す: 選んだ版を結果のファイルに写す（意思入れ＝作業ファイルも戻すかは選べる）。こちらで書いたままの版なら out/.state/ の指紋も
  書き直す（NLM で直した版なら指紋を消す＝次の作り直しで out/old/ に控えを取り、前の形式のファイルでは全部を残す側に倒れる）。
  クリップの id は中身の指紋なので、戻した版の作ったクリップは次の作り直しでも「作ったまま」と見分けられる。
別の案: <OUT>/.cand/<曲>/ に、選んだ区間だけ作り直した案を N_CANDS 個（compose --only … --variant k・並べて動かす）。
- 案 k の作り方（テーマのずらし・種）は automap.intent.variant_spec。compose には --variant k だけを渡す（曲全体の種は変えない）
  ＝作業ファイルの区間の指示「案 k」と同じ口なので、選んだ後に全部を作り直しても区間のテーマは案 k のまま。
- 珍しい型まで広げて作る（rare）: compose に --rare も渡す（区間の小節のテーマを、少ない曲にしか出ない型まで広げた束から選ぶ・
  案 k のずらし方はその束の中で。型のデータベースの曲は決めもその区間に入れる側）。これにすると画面が区間に「珍しい型まで」も足す。
- ★の帯を変えて作る（band＝intent.band_of の値）: compose に --band も渡す（区間の小節のテーマを、★の帯だけ変えた型の束から選ぶ）。
  これにすると画面が区間に「★の帯」も足す。
- compose の --only は --out のファイルがある時だけ動く（それを土台にする）ので、作る前に今の結果のファイルを写して置く。
- 同じ振りの形の別の案（form＝{group, form: 'A'|'B'}・docs/アプリ仕様.md 15 節）: 形の全部の回の同じ振りの指示に「案 v」（と rare・band）を
  付けた表（form_table）を --intent に、今の作業ファイルの表を --prev-intent に（compose_extra が opts.prev_table を渡す）して、全部を
  作り直す（--only 無し）＝指示が変わったのは形の回だけ（同じ振りのグループの全部が自由・ほかは今の譜面に寄せる）。区間だけ（--only）だと
  形のほかの回が作り直されない。決めを引き継ぐように、今の報告を前の表の隣に写す。表の数字は形の全部の回で数える（form_summary）。
- 案の一覧には、区間の中のノーツの数・両手・今と同じ置き方のノーツ・区間の外の違い（0 のはず）など。結果のファイルが変わったら
  （作り直した・戻した・NLM で保存した）古い案は使えないので消す。
- これにする: 履歴に控えてから、案を結果のファイルに写す（報告も）→ 写した版も履歴に。区間の指示「案 k」は画面が作業ファイルに足す
  （作業ファイルの正は画面＝ここで書くと画面の自動保存で消える）。履歴の版の作業ファイルには、画面が送った足した後の物を控える。
前の譜面に寄せる（docs/アプリ仕様.md 11 節）: 作り直しのたびに compose_extra（server の COMPOSE_EXTRA）が、今の結果のファイルを作った
時の版（prev_version）の作業ファイルを compose の --prev-intent に渡す（今の表と比べて指示が変わった所だけ自由に作り、ほかは前の譜面に
弱く寄せる）。寄せない（--no-anchor <理由>）: 画面で「前の譜面に寄せない」を選んだ（作業ファイルの opts.anchor＝False）・前の版が
分からない（履歴が無い・どの版とも合わない）・曲の全体に効く設定（ライブラリ・自動の休み等＝区間の指示と量のライン以外）を変えた。
NLM で直して保存した結果のファイルは、作ったままのクリップ（id＝中身の指紋）が一番多く重なる作り直しの版を前の版とみる（直した
クリップは今まで通り残り、寄せる相手は作ったままのクリップのノーツ）。
区間だけ作り直した版（区間だけ作り直す・区間の別の案・形の別の案）に控える作業ファイルは、効いた意思入れ（_merge_regions＝作り直した
区間の中は今の物・外は前の版の物）。今の物をそのまま控えると、外で変えた指示が次の作り直しで「変えていない」に見えて前の譜面に寄せられ、
効かないまま残った。
未反映の意思入れ（pending・docs/アプリ仕様.md 16 節）: 今の作業ファイルと前の版の作業ファイルを、次の作り直しと同じ決まりで比べる。
難易度（docs/アプリ仕様.md 17 節）: 履歴・別の案・前の譜面に寄せる・未反映の知らせは、曲の基準の難易度（作業ファイルの diff・server.base_diff）
だけを見る。版の一覧に控えた時の基準（diff）を書く（基準を別の難易度に置き直した後も、前の版を正しく読む＝server.file_diff）。
- 戻す・案を選ぶ（_put_base）: 結果のファイルの基準の難易度のノーツ系（ノーツのクリップとフラットの配列）だけを版・案の物に入れ替え、
  ほかの難易度（派生）・基準の難易度のライト・書き出す印・マーカー等は今のファイルのまま。入れ替えた物が版・案のファイルと同じ中身
  （保存の時刻を除く）なら、今まで通り版・案のファイルをそのまま写す（指紋が合う＝一覧の「今の版」）。違えば合わせた物を書き、戻した版は
  新しい版「前の版に戻した」として控える（作った時の作業ファイルも＝前の譜面に寄せる時の前の表に使える）。基準を置き直した後の古い版は、
  版の基準の難易度から今の基準の難易度へ写す（作ったクリップの id＝中身の指紋は難易度のキーを含むので付け直す）。
- 意思入れも戻す: 作業ファイルの diff（基準）・expand（最後に展開した設定）・library・amount は今の物のまま（意思入れとは別の設定）。
- 作業ファイルの diff・expand は前の譜面に寄せるかの「曲の全体に効く設定」に入れない（基準を置き直しても基準のノーツは同じ）。
- 難易度の展開で派生を書いた後の版（app/expand.py が snapshot で控える）は作り直しの版ではない＝前の譜面に寄せる時は、作ったクリップの
  重なりで前の作り直しの版を探す（基準の譜面は同じ）。
"""
import copy
import hashlib
import json
from collections import Counter
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from automap import diffs, lazy, nlmf, rating_scale, stats, written  # noqa: F401
from automap.library_use import amount_of
# 重い部品（意思入れの比べ＝numpy・作る処理＝scipy 等）は使う時に読む（起動を速く・2026-11-09・automap/lazy.py）。
# こちらで書いた印（cli._edited_since_written・_state_path・_sha・_save）は軽い automap/written.py から
intent = lazy.Module('automap.intent')
cli = lazy.Module('automap.__main__', light='automap.written')

HIST_MAX = 30        # 曲ごとに残す版の数（「残す」印の版は数えない・消さない）
N_CANDS = 3          # 1回に作る別の案の数（案 v の作り方は intent.variant_spec）
FAR = 8              # 形の別の案の far_diff: 形の回からこの拍より離れた所の違い（自由に作る所＝回の小節＋前後 2 拍の外）
RELIABLE = ('generate', 'only', 'cand')   # 作り直しに使った作業ファイルを控えた版（前の譜面に寄せる時の前の表に使える・戻した版は reliable の印）
WORK_ONLY = ('ranges', 'line', 'version', 'song', 'saved', 'from', 'history', 'opts', 'diff', 'expand',
             'archived', 'njs')   # 曲の全体に効く設定ではない作業ファイルの項目（archived＝曲を選ぶ窓のアーカイブの印・譜面に関係ない）
# （njs＝3D で決めた基準の NJS・app/njsbase.py＝ノーツは変えない＝変えても前の譜面に寄せる）
KEEP_ON_RESTORE = ('diff', 'expand', 'library', 'amount', 'njs')   # 「意思入れも戻す」でも今の物のままの作業ファイルの項目（njs＝結果のファイルの NJS も戻さない）
SETTING_TEXT = {'library': 'ライブラリ', 'auto_rest': '自動の休み', 'amount': '量の目安'}
KIND_TEXT = {'generate': '作り直した（全部）', 'only': '選んだ区間だけ作り直した', 'cand': '別の案を選んだ',
             'first': '控えを取り始めた時の版', 'nlm': 'NLM で直して保存した版', 'outside': 'アプリの外で作り直した版',
             'manual': '手で控えた版', 'restore': '前の版に戻した'}
VID = re.compile(r'^\d{8}-\d{6}-[0-9a-f]{4}$')

C = None                       # server モジュール（routes で受け取る。OUT 等は呼ばれた時に読む＝--out で変えられる）
_LOCK = threading.RLock()
_PENDING = {}                  # 作り直しの作業の id → 始めた時の作業ファイルの中身（作り直しに使った意思入れ）


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _song(p):
    return p.name.split('.')[0]


def hist_dir(p):
    return Path(C.OUT) / '.history' / _song(p)


def cand_dir(p):
    return Path(C.OUT) / '.cand' / _song(p)


def _ver(p, vid, ext='.nlmf'):
    return hist_dir(p) / f'{_song(p)}.{vid}{ext}'


def _report_path(p):
    return p.with_name(p.name[:-len('.nlmf')] + '.report.md')


def _read(path):
    try:
        return Path(path).read_text(encoding='utf-8')
    except OSError:
        return None


def _write_json(path, d):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)


def _dk(proj, path, d=None):
    """ファイルの基準の難易度（d が無ければ server.file_diff＝曲の作業ファイルの diff・履歴の版は控えた時の基準）のキー"""
    return C.diff_key_in(proj, d or C.file_diff(path), Path(path).name)


def _notes(path, d=None):
    proj = nlmf.load(path)
    return proj, nlmf.clip_notes(proj, _dk(proj, path, d))


def _work_diff(text, default=None):
    """作業ファイルの中身（文字列）の基準の難易度の名前（無い・読めなければ default）"""
    try:
        return diffs.name_of(json.loads(text).get('diff') or diffs.DEFAULT) if text else default
    except (TypeError, ValueError, AttributeError):
        return default


def _report_head(md):
    """報告（<結果>.report.md）の要点の数行"""
    out = []
    for line in (md or '').splitlines():
        s = line.strip()
        if s.startswith(('- 打点', '- **選んだ区間', '- 別の案', '- 「ここから」', '- 作り直したクリップ', '- 前の譜面に寄せ', '- そのまま残す')):
            out.append(re.sub(r'・計算 [\d.]+ 秒|・減点の合計 [\d.]+', '', s[2:].replace('**', '')).split('。')[0])
        m = re.match(r'\| (振りの交互の崩れ|NLM の振りの警告と同じ決まり（回）) \| ([^|]+) \|', s)
        if m:
            out.append(f'{m.group(1).replace("と同じ決まり（回）", "")} {m.group(2).strip()}')
    return out[:7]


# ---- 履歴 ----

def _index(p):
    try:
        return json.loads((hist_dir(p) / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []


def _entry(p, vid):
    if not VID.match(str(vid or '')):
        raise ValueError('版の名前が違う')
    e = next((e for e in _index(p) if e['id'] == vid), None)
    if not e:
        raise FileNotFoundError('その版は無い')
    return e


def _remove_files(p, vid):
    for ext in ('.nlmf', '.automap.json', '.report.md', '.intent.json'):
        _ver(p, vid, ext).unlink(missing_ok=True)


def _is(e, sha):
    """版 e が中身の指紋 sha の版か（also＝アプリ自身が曲の情報だけを書いた後の中身＝同じ版とみなす・adopt）"""
    return bool(sha) and (e['sha'] == sha or sha in (e.get('also') or ()))


def adopt(p, before_sha):
    """アプリ自身が結果のファイルに曲の情報・音量の補正だけを書いた（Beat Saber への書き出し＝app/bsexport.py の _edit）後に呼ぶ: 書く前の
    中身が履歴のどれかの版なら、書いた後の中身もその版とみなす（also に足す）→ その版か None。前は書き出しの後の作り直しのたびに
    「アプリの外で作り直した版（作り直す前）」が増えた（ノーツは同じ・2026-11-15 利用者「直しておいて」）。書く前がどの版とも違えば
    （NLM で直して保存した）何もしない＝次の作り直しの前にふだんどおり控える"""
    if not p.exists() or not before_sha:
        return None
    with _LOCK:
        items = _index(p)
        e = next((e for e in reversed(items) if _is(e, before_sha)), None)
        if not e:
            return None
        now = _sha(p)
        if not _is(e, now):
            e['also'] = ((e.get('also') or []) + [now])[-20:]
            _write_json(hist_dir(p) / 'index.json', items)
        return e


def _prune(p, items, cur_sha):
    """古い版から消す（「残す」印の版・今の版は消さない）"""
    over = sum(1 for e in items if not e.get('keep')) - HIST_MAX
    for e in [e for e in items if not e.get('keep') and not _is(e, cur_sha)][:max(0, over)]:
        items.remove(e)
        _remove_files(p, e['id'])


def snapshot(p, kind, title=None, only=None, work=None, report=None, as_written=None, extra=None, dedupe=True, head=True, diff=None):
    """結果のファイル p の今の中身を履歴に控える → 控えた版（dedupe なら、同じ中身の版が既にあればそれを返す）。
    work・report＝その版の作業ファイル・報告の中身（None なら今のファイルから・'' なら無し）。as_written＝こちらで書いたままか
    （None なら out/.state/ の指紋で見る）。head＝報告の要点を一覧に出すか（NLM で直した版の報告は前の作り直しの物なので出さない）。
    diff＝ファイルの基準の難易度（None なら work の diff・無ければ今の基準の難易度）＝一覧の diff"""
    if not p.exists():
        return None
    with _LOCK:
        sha = _sha(p)
        items = _index(p)
        if dedupe:
            got = next((e for e in reversed(items) if _is(e, sha)), None)
            if got:
                return got
        vid = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4]
        hist_dir(p).mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, _ver(p, vid))
        work = _read(C.work_path(p)) if work is None else work
        if work:
            _ver(p, vid, '.automap.json').write_text(work, encoding='utf-8')
        report = _read(_report_path(p)) if report is None else report
        if report:
            _ver(p, vid, '.report.md').write_text(report, encoding='utf-8')
        if as_written is None:
            as_written = not cli._edited_since_written(p)
        d = diff or _work_diff(work, C.base_diff(p))   # 控えた時の基準の難易度（作り直しに使った作業ファイルの diff）
        proj = nlmf.load(p)
        if not diff and diffs.key(d) not in proj['difficulties']:
            # 作業ファイルの基準がファイルに無い（基準を置き直す直前＝画面が先に作業ファイルの diff を書いた等）: 前の版の基準・無ければ
            # ノーツの一番多い難易度（置き直す時は app/expand.py が diff を渡す）
            prev = next((e.get('diff') for e in reversed(items) if e.get('diff')), None)
            ds = proj['difficulties']
            d = prev if prev and diffs.key(prev) in ds else next((x['diff'] for x in sorted(diffs.listing(proj), key=lambda x: -x['notes'])), d)
        try:
            ns = _notes(p, d)[1]
        except (ValueError, KeyError):   # 基準の難易度が無いファイル（置き直しの途中等）でも控える
            ns = []
        e = {'id': vid, 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'ts': time.time(), 'file': p.name, 'kind': kind, 'diff': d,
             'title': title or KIND_TEXT.get(kind, kind), 'only': [float(x) for x in only] if only else None, 'notes': len(ns),
             'sha': sha, 'head': _report_head(report) if (report and head) else [], 'as_written': bool(as_written),
             'keep': False, 'work': bool(work), 'report': bool(report)}
        e.update(extra or {})
        items.append(e)
        _prune(p, items, sha)
        _write_json(hist_dir(p) / 'index.json', items)
        return e


def guard(p, why, diff=None):
    """今の結果のファイルがどの版とも違えば控える（NLM で直して保存した・アプリの外で作った・控えを取り始める前）→ その版。
    diff＝ファイルの基準の難易度（基準を置き直す前の控え＝作業ファイルの diff がもう新しい基準の時に渡す）"""
    if not p.exists():
        return None
    with _LOCK:
        items, sha = _index(p), _sha(p)
        got = next((e for e in reversed(items) if _is(e, sha)), None)
        if got:
            return got
        edited = cli._edited_since_written(p)
        kind = 'first' if not items else 'nlm' if edited else 'outside'
        title = KIND_TEXT[kind] + (('・NLM で直してあった' if edited else '') if kind == 'first' else '') + f'（{why}）'
        return snapshot(p, kind, title, as_written=not edited, dedupe=False, head=not edited, diff=diff)


def _set_state(p, as_written):
    """out/.state/ の指紋: こちらで書いたままの版なら今の中身の指紋に・そうでなければ消す（分からない＝NLM で直された物として扱われる）"""
    sp = cli._state_path(p)
    if as_written:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({'sha256': _sha(p), 'savedAt': nlmf.load(p).get('savedAt')}), encoding='utf-8')
    else:
        sp.unlink(missing_ok=True)


def list_versions(p):
    items = _index(p)
    cur = _sha(p) if p.exists() else None
    now = next((e['id'] for e in reversed(items) if _is(e, cur)), None)
    # diff＝版の基準の難易度（一覧に書く前の版は控えた作業ファイルの diff・無ければ Expert+＝server.file_diff と同じ決まり）
    out = [dict(e, current=e['id'] == now, diff=e.get('diff') or _work_diff(_read(_ver(p, e['id'], '.automap.json')), diffs.DEFAULT))
           for e in reversed(items)]
    return {'file': p.name, 'song': _song(p), 'versions': out, 'current': now, 'exists': p.exists(),
            'known': now is not None or not p.exists(), 'max': HIST_MAX, 'busy': C.busy(p.name)}


def _shift_tracks(st, k):
    """難易度 st のノーツ系（ノーツのクリップ・フラットの配列）のレーンの番号を k だけずらす（0 未満にはしない）"""
    if not k:
        return
    for s in st.get('sections') or []:
        if s.get('lk') != 'l':
            s['track'] = max(0, (s.get('track') or 0) + k)
    for key in nlmf.FLAT_N:
        fi = len(nlmf._enc_fields(key))
        for a in st.get(key) or []:
            if isinstance(a, list) and len(a) > fi:
                a[fi] = max(0, (a[fi] or 0) + k)


def _align_lanes(proj, n):
    """proj のノーツのレーンを n 本に（NLM はレーンを一番上に足す＝今のレーンの番号を足した数だけずらす。減らす時はしない）→ ずらした数"""
    k = n - int(proj.get('notesLanes') or 1)
    if k <= 0:
        return 0
    for st in proj['difficulties'].values():
        _shift_tracks(st, k)
    ls = proj.setdefault('laneStates', {'mute': [], 'solo': [], 'lock': []})
    for q in ('mute', 'solo', 'lock'):
        ls[q] = [(f'n{int(v[1:]) + k}' if v[:1] == 'n' and v[1:].isdigit() else v) for v in ls.get(q) or []]
    if ls.get('editOnly') is not None:
        ls['editOnly'] += k
    proj['notesLanes'] = n
    return k


def _bare(proj):
    return {k: v for k, v in proj.items() if k != 'savedAt'}


def _put_base(p, src, src_diff, as_written):
    """結果のファイル p の基準の難易度のノーツ系だけを src（履歴の版・別の案）の src_diff の物に入れ替える（ほかの難易度・基準の難易度の
    ライト・書き出す印・マーカー等は今の p のまま）。入れ替えた物が src と同じ中身（保存の時刻を除く）なら src をそのまま写す → True
    （今まで通り）。違えば合わせた物を書く → False。out/.state/ の指紋は as_written（こちらで書いたままの版か）で書き直す・消す"""
    if not p.exists():
        shutil.copyfile(src, p)
        _set_state(p, as_written)
        return True
    cur, ver = nlmf.load(p), nlmf.load(src)
    ks = C.diff_key_in(ver, src_diff, f'戻す版（{src.name}）')
    d = C.base_diff(p)
    kd = C.diff_key_in(cur, d, '今の結果のファイル（基準の難易度）')
    merged = copy.deepcopy(cur)
    _align_lanes(merged, int(ver.get('notesLanes') or 1))
    st = copy.deepcopy(ver['difficulties'][ks])
    _shift_tracks(st, int(merged.get('notesLanes') or 1) - int(ver.get('notesLanes') or 1))
    if ks != kd:   # 基準を置き直した後の古い版: 作ったクリップの id（中身の指紋・難易度のキーを含む）を今の基準の難易度で付け直す
        for s in nlmf.note_clips(st):
            if nlmf.is_app_clip(s) and s['id'] == nlmf.clip_id(ks, s):
                s['id'] = nlmf.clip_id(kd, s)
        st['name'] = diffs.dat(d)
    old = merged['difficulties'][kd]
    lights = lambda x: [s for s in x.get('sections') or [] if s.get('lk') == 'l']
    if lights(old) != lights(st):   # ライトのクリップは今の物（並びが同じなら版の並びのまま）
        st['sections'] = [s for s in st.get('sections') or [] if s.get('lk') != 'l'] + lights(old)
    if (old.get('lightEvents') or []) != (st.get('lightEvents') or []):
        st['lightEvents'] = old.get('lightEvents') or []
    merged['difficulties'][kd] = st
    if _bare(merged) == _bare(ver):
        shutil.copyfile(src, p)
        _set_state(p, as_written)
        return True
    if as_written:
        cli._save(merged, p)   # こちらで書いた印（out/.state/）も
    else:
        nlmf.save(merged, p)
        cli._state_path(p).unlink(missing_ok=True)
    return False


def _restored_work(p, wsrc):
    """「意思入れも戻す」で書く作業ファイル: 版の作業ファイルの、基準の難易度・最後に展開した設定・ライブラリ・量の目安だけ今の物"""
    w = json.loads(wsrc.read_text(encoding='utf-8'))
    now = C.load_work(p)
    for k in KEEP_ON_RESTORE:
        w.pop(k, None)
        if now.get(k) is not None:
            w[k] = now[k]
    return w


def restore(p, vid, work=False):
    """版を結果のファイルに戻す（今の結果のファイルは先に控える）。戻すのは基準の難易度のノーツ系だけ（_put_base）。
    work＝作業ファイル（意思入れ）も戻す（基準の難易度・展開の設定・ライブラリ・量の目安は今のまま）"""
    if C.busy(p.name):
        raise ValueError('この曲は今作り直している（終わってから戻す）')
    with _LOCK:
        e = _entry(p, vid)
        src, wsrc = _ver(p, vid), _ver(p, vid, '.automap.json')
        if not src.exists():
            raise FileNotFoundError('その版のファイルが無い')
        if work and not wsrc.exists():
            raise FileNotFoundError('その版には意思入れの控えが無い（譜面だけ戻す）')
        guard(p, f'{e["at"]} の版に戻す前')
        same = _put_base(p, src, C.file_diff(src), e.get('as_written'))
        rp = _ver(p, vid, '.report.md')
        if rp.exists():
            shutil.copyfile(rp, _report_path(p))
        if work:
            C.save_work(p, _restored_work(p, wsrc))
        ne = None
        if not same:   # ほかの難易度などが版と違う＝合わせた物を新しい版に（作った時の作業ファイルも＝前の譜面に寄せる時の前の表）
            ne = snapshot(p, 'restore', f'{e["at"]} の版に戻した（基準の難易度だけ・ほかは今のまま）', only=e.get('only'),
                          work=_read(wsrc) or '', report=_read(rp) or '', as_written=e.get('as_written'), dedupe=False,
                          head=bool(e.get('head')), diff=C.base_diff(p),
                          extra={'from': vid, 'reliable': bool(e.get('kind') in RELIABLE or e.get('reliable'))})
        drop_cands(p)
        return {'ok': True, 'version': e, 'restored': ne, 'merged': not same, 'work': C.load_work(p) if work else None}



def set_keep(p, vid, keep):
    with _LOCK:
        items = _index(p)
        e = next((e for e in items if e['id'] == _entry(p, vid)['id']), None)
        e['keep'] = bool(keep)
        if not keep:
            _prune(p, items, _sha(p) if p.exists() else None)
        _write_json(hist_dir(p) / 'index.json', items)
        return {'ok': True}


def delete_version(p, vid):
    with _LOCK:
        items = _index(p)
        e = _entry(p, vid)
        if p.exists() and _is(e, _sha(p)):
            raise ValueError('今の版は消せない')
        items = [x for x in items if x['id'] != vid]
        _remove_files(p, vid)
        _write_json(hist_dir(p) / 'index.json', items)
        return {'ok': True}


def before_generate(job, p):
    """作り直しの前: 今の結果のファイルがどの版とも違えば控え、作り直しに使う作業ファイルを覚えておく（失敗しても作り直しは止めない）"""
    try:
        guard(p, '作り直す前')
        prev = None
        if job.get('only'):   # 区間だけ: 外は前の版の意思入れのまま（_merge_regions）
            e, _ = prev_version(p)
            prev = _read(_ver(p, e['id'], '.automap.json')) if e else None
        _PENDING[job['id']] = (_read(C.work_path(p)) or '', prev)
    except Exception as e:   # noqa: BLE001
        job['log'] += f'（履歴の控えに失敗した: {e}）\n'


def after_generate(job, p):
    """作り直しの後: 作った版を控え、古い別の案を消す"""
    work, prev = _PENDING.pop(job['id'], (None, None))
    if job.get('state') != 'done':
        return
    only = job.get('only')
    if only and prev and work:
        work = _merge_regions(prev, work, [sorted(float(x) for x in only)])
    snapshot(p, 'only' if only else 'generate', only=only, work=work, report=job.get('report') or '', dedupe=False)
    drop_cands(p)


# ---- 前の譜面に寄せる ----

def _ver_work(p, vid):
    """版の作業ファイル（★の帯は今の境目へ読み替える＝物差しの更新で境目が動いただけなら「設定を変えた」にせず、前の譜面に寄せる・
    型のライブラリの設定も今の作業ファイルと同じ決まりで読み替える＝library_setting.migrate_work）"""
    from automap import library_setting
    return library_setting.migrate_work(rating_scale.migrate_work(json.loads(_ver(p, vid, '.automap.json').read_text(encoding='utf-8'))))


def _settings(w):
    """作業ファイルの曲の全体に効く設定（区間の指示・量のライン以外）→ {項目: 比べる形}"""
    g = {k: v for k, v in (w or {}).items() if k not in WORK_ONLY and v not in (None, {}, [])}
    ar = g.pop('auto_rest', None) or {}
    if ar.get('on'):
        g['auto_rest'] = {'on': True, 'b': ar.get('b')}
    am = amount_of(g.pop('amount', None))   # 量の目安（自動＝無いのと同じ。変えたら曲の全体が変わる＝寄せない）
    if am:
        g['amount'] = am
    return {k: json.dumps(v, sort_keys=True, ensure_ascii=False) for k, v in g.items()}


def _clip_ids(proj, dk, app_only=False):
    """基準の難易度（キー dk）のクリップの id の組。作ったまま（id＝中身の指紋）のクリップは難易度のキーを抜いた指紋にそろえる
    （基準を別の難易度に置き直した後も、前の版と比べられる）"""
    if app_only:
        cls, new_fmt, _ = nlmf.classify(proj, dk)
        if not new_fmt:
            return set()
        secs = [s for s, st in cls if st == 'app']
    else:
        secs = nlmf.note_clips(proj['difficulties'][dk])
    return {('au' + nlmf.fingerprint('', s)) if s.get('id') == nlmf.clip_id(dk, s) else s.get('id') for s in secs}


def prev_version(p):
    """今の結果のファイルを作った時の作り直しの版（その時の作業ファイルの控えがある版）→ (版, None) か (None, 分からない理由)。
    今の結果のファイルと同じ中身の版が無い（NLM で直して保存した等）時は、作ったままのクリップ（id＝中身の指紋）が一番多く重なる版
    （半分以上）"""
    items = _index(p)
    if not items:
        return None, '前の版が分からない（履歴が無い）'
    ok = lambda e: (e.get('kind') in RELIABLE or e.get('reliable')) and e.get('work') and _ver(p, e['id'], '.automap.json').exists() and _ver(p, e['id']).exists()
    sha = _sha(p)
    e = next((e for e in reversed(items) if _is(e, sha)), None)
    if e and ok(e):
        return e, None
    cands = [e for e in reversed(items) if ok(e)]
    if not cands:
        return None, '前の版が分からない（作り直しの控えが無い）'
    try:
        cur = nlmf.load(p)
        ids = _clip_ids(cur, _dk(cur, p), app_only=True)
    except (ValueError, KeyError):   # 基準の難易度が無い
        ids = set()
    if not ids:
        return None, '前の版が分からない（作ったままのクリップが無い）'
    best = None
    for e in cands:
        try:
            vp = _ver(p, e['id'])
            vj = nlmf.load(vp)
            k = len(ids & _clip_ids(vj, _dk(vj, vp))) / len(ids)
        except (OSError, ValueError, KeyError):
            continue
        if best is None or k > best[0] + 1e-9:
            best = (k, e)
        if k >= 0.999:
            break
    if best and best[0] >= 0.5:
        return best[1], None
    return None, '前の版が分からない（今の結果のファイルがどの版とも違う）'


def _merge_regions(prev_text, cur_text, spans):
    """区間だけ作り直した版に控える作業ファイル（効いた意思入れ）: spans（作り直した区間 [[b0, b1]]）の中に収まる区間の指示は今の物、
    ほかは前の版の物。量のライン・曲の全体の設定も前の版のまま（区間の外は作り直していない）。区間をまたぐ指示も前の版の物＝次の全部の
    作り直しで「変わった所」に入る側に倒す。読めなければ今の物"""
    try:
        pw, cw = json.loads(prev_text), json.loads(cur_text)
    except (TypeError, ValueError):
        return cur_text
    inside = lambda r: any(float(r['b0']) >= a - 1e-6 and float(r['b1']) <= b + 1e-6 for a, b in spans)
    rs = [r for r in pw.get('ranges') or [] if not inside(r)] + [r for r in cw.get('ranges') or [] if inside(r)]
    out = dict(pw, ranges=sorted(rs, key=lambda r: float(r['b0'])), saved=cw.get('saved', pw.get('saved')))
    return json.dumps(out, ensure_ascii=False, indent=1)


_PREV = {}   # 結果のファイル → ((中身と履歴の一覧の印), prev_version の答え)


def _prev_cached(p):
    """prev_version を、結果のファイルと履歴の一覧が変わっていない間は覚えておく（未反映の意思入れは保存のたびに聞かれる）"""
    ix = hist_dir(p) / 'index.json'
    try:
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size, ix.stat().st_mtime_ns if ix.exists() else 0)
    except OSError:
        return prev_version(p)
    got = _PREV.get(str(p))
    if got and got[0] == key:
        return got[1]
    r = prev_version(p)
    _PREV[str(p)] = (key, r)
    return r


def pending(p):
    """未反映の意思入れ（docs/アプリ仕様.md 16 節）: 今の作業ファイルと、今の結果のファイルを作った時の作業ファイル（prev_version）を、
    次の作り直しと同じ決まり（intent.changed_ranges・曲の全体の設定）で比べる → {state, spans, items, settings, version}。
    state: none＝無い・some＝ある・nofile＝結果のファイルがまだ無い・unknown＝前の版が分からない（why）。量のラインは items だけ
    （拍の範囲は小節が要る＝作る側が出す）"""
    if not p.exists():
        return {'state': 'nofile'}
    with _LOCK:
        e, why = _prev_cached(p)
        if not e:
            return {'state': 'unknown', 'why': why}
        pw = _ver_work(p, e['id'])
    w = C.load_work(p)
    pt, ct = C.intent_table(pw), C.intent_table(w)
    spans, _, why = intent.changed_ranges(dict(pt, line=[]), dict(ct, line=[]))
    # 画面の言い方: 区間の指示は足した・変えた（同じ場所で中身が違う）・消したの数、同じ振りは全部の回が変わる。自動の休みは settings に出す
    keys = lambda t: Counter(k for k in map(intent._rkey, intent._form_norm(t['ranges'])) if k)
    pk, ck = keys(pt), keys(ct)
    add, dele = ck - pk, pk - ck
    pos = lambda c: Counter((a, b) for a, b, _ in c.elements())
    chg = sum((pos(add) & pos(dele)).values())
    n = [('足した', sum(add.values()) - chg), ('変えた', chg), ('消した', sum(dele.values()) - chg)]
    items = ['区間の指示（' + '・'.join(f'{k} {v}' for k, v in n if v) + '）'] if add or dele else []
    items += [x.replace('の区間（写した先も）', '（全部の回が変わる）') for x in why if x.startswith('同じ振り')]
    if json.dumps(pt['line'], sort_keys=True) != json.dumps(ct['line'], sort_keys=True):
        items.append('量のライン')
    a, b = _settings(pw), _settings(w)
    sets = [SETTING_TEXT.get(k, k) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    return {'state': 'some' if (items or sets) else 'none', 'spans': [[x, y] for x, y in spans], 'items': items, 'settings': sets,
            'version': {'id': e['id'], 'at': e.get('at'), 'kind': e.get('kind')},
            'line_was': pt['line']}   # 作り直した時の量のライン（点を直線でつなぐ形）＝画面の量のラインの帯が、違う小節を網掛けにする


def compose_extra(p, w):
    """作り直し（server の COMPOSE_EXTRA）: 前の版の作業ファイルを --prev-intent に（意思入れの表の形で版の隣に書く）。
    寄せない時は --no-anchor <理由>（報告に出る）。結果のファイルが無い（初めて作る）時は何も足さない"""
    pt = ((w or {}).get('opts') or {}).get('prev_table')
    if pt:   # 同じ振りの形の別の案: 今の作業ファイルの表を前の表に（形の回だけが「変わった所」＝ほかは今の譜面に寄せる）
        return ['--prev-intent', str(pt)]
    if ((w or {}).get('opts') or {}).get('anchor') is False:
        return ['--no-anchor', '画面で「前の譜面に寄せない」を選んだ']
    if not p.exists():
        return []
    try:
        with _LOCK:
            e, why = prev_version(p)
            if not e:
                return ['--no-anchor', why]
            pw = _ver_work(p, e['id'])
            a, b = _settings(pw), _settings(w)
            diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            if diff:
                return ['--no-anchor', '曲の全体に効く設定（' + '・'.join(SETTING_TEXT.get(k, k) for k in diff) + '）を変えた']
            tf = _ver(p, e['id'], '.intent.json')
            if not tf.exists():
                _write_json(tf, C.intent_table(pw))
            return ['--prev-intent', str(tf)]
    except Exception as ex:   # noqa: BLE001  （寄せられなくても作り直しは止めない）
        return ['--no-anchor', f'前の版を読めなかった（{ex}）']


# ---- 別の案 ----

def _cand(p, n, ext='.nlmf'):
    return cand_dir(p) / f'{_song(p)}.cand{int(n)}{ext}'


def _cand_meta(p):
    try:
        return json.loads((cand_dir(p) / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def drop_cands(p):
    with _LOCK:
        shutil.rmtree(cand_dir(p), ignore_errors=True)


def _making(p):
    return any(j['state'] == 'running' and j.get('kind') == 'cands' and j['file'] == p.name for j in C.JOBS.values())


def _key(n):
    return round(n['beat'], 3), n['c'], n['x'], n['y'], n['d']


def region_summary(path, o0, o1, cur=None):
    """区間の中のノーツの数字（cur＝今の譜面のノーツ: 今と同じ置き方・区間の外の違いも）。振りの交互の崩れ・NLM の振りの警告は区間の前後
    1 小節も入れて数える（つなぎ目）"""
    proj, ns = _notes(path)
    tempo = nlmf.tempo_of(proj)
    ins = lambda n: o0 - 1e-6 <= n['beat'] < o1 - 1e-6
    inside = [n for n in ns if ins(n)]
    by = {}
    for n in inside:
        by.setdefault(round(n['beat'], 3), set()).add(n['c'])
    st = stats.summarize(inside, tempo)
    near = stats.summarize([n for n in ns if o0 - 4 <= n['beat'] < o1 + 4], tempo)
    r = {'notes': len(inside), 'double': sum(1 for v in by.values() if len(v) == 2),
         'diag': round((st.get('dir') or {}).get('diag', 0), 3), 'top': round((st.get('row') or [0, 0, 0])[2], 3),
         'move': round(st.get('move', 0), 2), 'reset': round(near.get('reset', 0), 3), 'warn': near.get('nlm_swing', 0)}
    if cur is not None:
        ci = {_key(n) for n in cur if ins(n)}
        co = {_key(n) for n in cur if not ins(n)}
        r['same'] = len({_key(n) for n in inside} & ci)
        r['outside_diff'] = len({_key(n) for n in ns if not ins(n)} ^ co)
    return r


def form_target(w, form):
    """別の案の形（画面の {group, form: 'A'|'B'}）→ {'group', 'form', 'spans': [[b0, b1]…]（その形の回・始まりの順）, 'others': [[b0, b1]…]
    （同じグループのほかの形の回）}。形の決まりは intent.motif_forms（画面の store.motifForms と同じ）"""
    g = (form or {}).get('group')
    name = str((form or {}).get('form') or 'A').upper()
    forms = intent.motif_forms(w)
    if g not in forms or name not in ('A', 'B') or not forms[g][name]:
        raise ValueError(f'同じ振りの形「{g} {name}」が作業ファイルに無い')
    sp = lambda rs: [[float(r['b0']), float(r['b1'])] for r in rs]
    return {'group': g, 'form': name, 'spans': sp(forms[g][name]), 'others': sp(forms[g]['B' if name == 'A' else 'A'])}


def form_table(w, fm, v, rare=False, band=None):
    """作業ファイル w → compose の --intent の表（server.intent_table の形）で、形 fm の全部の回の同じ振りの指示に「案 v」（rare＝True なら
    「珍しい型まで」・band があれば「★の帯」も）を付けた物。形の区間の中に収まる同じ振りでない区間の同じ項目は外す（そちらが勝つので・
    intent.form_set）。w は変えない"""
    t = C.intent_table(w)
    on = lambda r, sp: abs(float(r['b0']) - sp[0]) < 1e-6 and abs(float(r['b1']) - sp[1]) < 1e-6
    put = {'variant': int(v)}
    if rare:
        put['rare'] = True
    if band is not None:
        put['band'] = band
    for r in t['ranges']:
        st = dict(r.get('set') or {})
        if st.get('rest') or not any(sp[0] - 1e-6 <= float(r['b0']) and float(r['b1']) <= sp[1] + 1e-6 for sp in fm['spans']):
            continue
        m = st.get('motif')
        if m and m.get('group') == fm['group'] and any(on(r, sp) for sp in fm['spans']):
            st.update(put)
        elif not m:
            for k in put:
                st.pop(k, None)
        r['set'] = st
    t['ranges'] = [r for r in t['ranges'] if r['set']]
    return t


def _within(b, spans):
    return any(x - 1e-6 <= b < y - 1e-6 for x, y in spans)


def form_summary(path, fm, cur=None):
    """形の別の案の数字（region_summary と同じ項目を、形の全部の回で数える）。振りの交互の崩れ・NLM の振りの警告は回の前後 1 小節も入れ、
    回ごと（重なる物はまとめて）に数えて合わせる（離れた回どうしの間を続きとみない）。cur があれば same（今と同じ置き方）・outside_diff
    （同じグループの全部の回の外の違い＝回の小節・つなぎ目の違いも入る）・others_diff（同じグループのほかの形の回の中の違い＝A を変えると
    B も変わる）・far_diff（回から FAR 拍より離れた所の違い＝今の譜面に寄せた所。0 に近いはず）"""
    proj, ns = _notes(path)
    tempo = nlmf.tempo_of(proj)
    sp = [tuple(x) for x in fm['spans']]
    ot = [tuple(x) for x in fm.get('others') or []]
    inside = [n for n in ns if _within(n['beat'], sp)]
    by = {}
    for n in inside:
        by.setdefault(round(n['beat'], 3), set()).add(n['c'])
    st = stats.summarize(inside, tempo)
    mv = [stats.summarize([n for n in inside if x - 1e-6 <= n['beat'] < y - 1e-6], tempo) for x, y in sp]
    wm = [(s['move'], s['notes']) for s in mv if 'move' in s]
    near = [stats.summarize([n for n in ns if x - 1e-6 <= n['beat'] < y - 1e-6], tempo)
            for x, y in intent.merge_spans([(x - 4, y + 4) for x, y in sp])]
    wr = [(s['reset'], s['notes']) for s in near if 'reset' in s]
    avg = lambda xs: sum(a * k for a, k in xs) / sum(k for _, k in xs) if xs and sum(k for _, k in xs) else 0
    r = {'notes': len(inside), 'double': sum(1 for v in by.values() if len(v) == 2),
         'diag': round((st.get('dir') or {}).get('diag', 0), 3), 'top': round((st.get('row') or [0, 0, 0])[2], 3),
         'move': round(avg(wm), 2), 'reset': round(avg(wr), 3), 'warn': sum(s.get('nlm_swing', 0) for s in near),
         'spans': len(sp)}
    if cur is not None:
        allg = sp + ot
        ci = {_key(n) for n in cur if _within(n['beat'], sp)}
        r['same'] = len({_key(n) for n in inside} & ci)
        out_now = {_key(n) for n in ns if not _within(n['beat'], allg)}
        r['outside_diff'] = len(out_now ^ {_key(n) for n in cur if not _within(n['beat'], allg)})
        r['others_diff'] = len({_key(n) for n in ns if _within(n['beat'], ot)} ^ {_key(n) for n in cur if _within(n['beat'], ot)})
        # 回から FAR 拍より離れた所の違い（自由に作るのは回の小節の頭と終わり＋前後 2 拍まで＝ここは今の譜面に寄せて 0 に近いはず）
        far = [(x - FAR, y + FAR) for x, y in allg]
        r['far_diff'] = len({_key(n) for n in ns if not _within(n['beat'], far)} ^ {_key(n) for n in cur if not _within(n['beat'], far)})
    return r


def cands_view(p):
    """今ある別の案（結果のファイルが変わっていたら消して stale）"""
    meta = _cand_meta(p)
    if not meta:
        return {'cands': None}
    if not p.exists() or _sha(p) != meta.get('base_sha'):
        if not _making(p):
            drop_cands(p)
        return {'cands': None, 'stale': True}
    return dict(meta, making=_making(p))


def start_cands(p, only, start=1, n=N_CANDS, rare=False, band=None, form=None):
    """選んだ区間で別の案を n 個作る作業を始める（案 v＝start…・compose --variant v。ずらし・種は intent.variant_spec＝表に出す数字）。
    rare＝珍しい型まで広げて作る（compose --rare も渡す）・band＝★の帯を変えて作る（compose --band も渡す・使えない値は無し）。
    form＝{group, form: 'A'|'B'}: 同じ振りの形の別の案（形の全部の回に「案 v」（と rare・band）を付けて全部を作り直し、今の譜面に寄せる・
    only は形の1回目の区間に読み替える）"""
    if not p.exists():
        raise ValueError('別の案は、結果のファイルがある時だけ（先に上の「作り直す」で作る）')
    if C.busy(p.name):
        raise ValueError('この曲は今作り直している')
    w = C.load_work(p) if form else None
    fm = form_target(w, form) if form else None
    o0, o1 = fm['spans'][0] if fm else sorted(float(x) for x in only)
    if o1 - o0 <= 1e-6:
        raise ValueError('区間が空')
    start, n, rare, band = max(1, int(start)), max(1, min(4, int(n))), bool(rare), intent.band_of(band)
    prev_t = cand_dir(p) / f'{_song(p)}.prev.intent.json'
    with _LOCK:
        drop_cands(p)
        cand_dir(p).mkdir(parents=True)
        written = not cli._edited_since_written(p)
        specs = [dict(zip(('variant', 'seed'), intent.variant_spec(start + i)), n=i + 1, v=start + i, rare=rare, band=band, state='waiting') for i in range(n)]
        meta = {'file': p.name, 'only': [o0, o1], 'base_sha': _sha(p), 'start': start, 'made': time.strftime('%Y-%m-%d %H:%M:%S'),
                'cands': specs, 'done': False, 'rare': rare, 'band': band, 'form': fm}
        _write_json(cand_dir(p) / 'index.json', meta)
        if fm:   # 形の別の案: 今の作業ファイルの表（前の表）・案ごとの表。決めを引き継ぐように今の報告を前の表の隣に写す
            _write_json(prev_t, C.intent_table(w))
            if _report_path(p).exists():
                shutil.copy2(_report_path(p), prev_t.with_name(f'{_song(p)}.prev.report.md'))
            for c in specs:
                _write_json(_cand(p, c['n'], '.intent.json'), form_table(w, fm, c['v'], rare, band))

    def run(job):
        subs = []

        def stop_subs():   # やめる（server.cancel_job）: 動いている案ごとの作り直しも全部止める
            for _, sj in subs:
                if sj['state'] == 'running':
                    try:
                        C.cancel_job(sj['id'])
                    except ValueError:
                        pass
        job['_on_cancel'] = [stop_subs]
        for c in specs:   # 案のファイルに今の結果のファイルを写して置く（compose --only はそれを土台にする）
            if job.get('cancel'):
                break
            dst = _cand(p, c['n'])
            shutil.copy2(p, dst)
            if written:   # こちらで書いたままなら、その印も写す（compose が old/ に控えを取らない・前の形式の判定も同じ）
                sp = cli._state_path(dst)
                sp.parent.mkdir(parents=True, exist_ok=True)
                sp.write_text(json.dumps({'sha256': _sha(dst)}), encoding='utf-8')
            if fm:   # 形の別の案: 形の回に「案 v」を付けた表で全部を作り直す（後の --intent が勝つ）・今の表を前の表に（寄せる）
                subs.append((c, C.start_generate(p, out=dst, extra=['--intent', str(_cand(p, c['n'], '.intent.json'))], kind='cand',
                                                 cand=c['n'], opts={'prev_table': str(prev_t)})))
                continue
            extra = ['--variant', c['v']] + (['--rare'] if rare else [])   # 案 v（区間の指示「案 v」と同じ決まり・曲全体の種は変えない）
            if band is not None:   # ★の帯（「-1」が引数の名前に見えないように --band=… の1つで渡す）
                extra.append('--band=' + (','.join(f'{x:g}' for x in band) if isinstance(band, list) else f'{band:+d}'))
            subs.append((c, C.start_generate(p, only=[o0, o1], out=dst, extra=extra, kind='cand', cand=c['n'])))
        if job.get('cancel'):   # 案を並べている間にやめた
            stop_subs()
        while True:
            for c, sj in subs:
                c['state'], c['took'] = sj['state'], sj.get('took')
            job['cands'] = [{'n': c['n'], 'state': c['state'], 'took': c.get('took')} for c in specs]
            if all(sj['state'] != 'running' for _, sj in subs):
                break
            time.sleep(0.5)
        if job.get('cancel'):   # やめた: 作りかけの案は残さない（結果のファイルには触れていない）
            drop_cands(p)
            raise RuntimeError('やめた')
        _, cur = _notes(p)
        meta['current'] = form_summary(p, fm) if fm else region_summary(p, o0, o1)
        for c, sj in subs:
            if sj['state'] == 'done':
                c.update(form_summary(_cand(p, c['n']), fm, cur) if fm else region_summary(_cand(p, c['n']), o0, o1, cur))
                c['head'] = _report_head(sj.get('report'))
            else:
                c['log'] = (sj.get('log') or '')[-1500:]
                job['log'] += f'案{c["n"]} に失敗した\n{c["log"]}\n'
        meta['done'] = True
        with _LOCK:
            if cand_dir(p).exists():
                _write_json(cand_dir(p) / 'index.json', meta)
            shutil.rmtree(cand_dir(p) / 'old', ignore_errors=True)
        if not any(c['state'] == 'done' for c in specs):
            raise RuntimeError('案を1つも作れなかった')

    return C.start_job(p.name, [('別の案を作る', run)], kind='cands', only=[o0, o1], n=n, rare=rare, band=band, form=fm)


def fix_region(p, o0, o1):
    """区間の中の作ったまま（作り直す）クリップの名前に「固定」を足す（全部を作り直しても残す＝NLM とのやり取りの決まり）→ 足した数。
    名前は指紋に入らないので id はそのまま。外すのは NLM でクリップの名前から「固定」を消す"""
    proj = nlmf.load(p)
    dk = _dk(proj, p)
    k = 0
    for s, st in nlmf.classify(proj, dk)[0]:
        b0 = s.get('beat') or 0
        if st == 'app' and b0 >= o0 - 1e-6 and b0 + (s.get('len') or 0) <= o1 + 1e-6:
            s['label'] = f'{s.get("label") or nlmf.APP_LABEL} {nlmf.KEEP_WORD}'
            k += 1
    if k:
        cli._save(proj, p)   # こちらで書いた印（out/.state/）も
    return k


def _work_text(p, w):
    """画面が送った作業ファイルの中身（save_work と同じ形）→ 履歴に控える文字列。形が違えば None（今のファイルを控える）"""
    if not isinstance(w, dict) or not isinstance(w.get('ranges'), list):
        return None
    w = dict(w, version=1, song=_song(p), saved=time.strftime('%Y-%m-%dT%H:%M:%S'))
    return json.dumps(w, ensure_ascii=False, indent=1)


def choose(p, n, fix=False, work=None):
    """案 n を結果のファイルにする（今の結果のファイルは先に控え、選んだ版も履歴に）→ 案の番号 variant・珍しい型まで広げた案か rare
    （画面が区間に指示「案 k」（広げた案なら「珍しい型まで」も）を足す＝次に全部を作り直しても区間のテーマは案のまま）。fix＝区間のクリップを「固定」にする（1つも変えたくない時）。
    work＝画面が「案 k」を足した後の作業ファイルの中身（選んだ版の控えに。画面は返事の後で同じ物を作業ファイルに保存する）。
    答えの form＝同じ振りの形の案なら {group, form, spans, others}（画面は形の全部の回の同じ振りの指示に variant を書き、rare が真なら
    「珍しい型まで」・band があれば「★の帯」も書く＝この案で足した物。偽・None は「今の形の設定のまま」）・区間の案は None"""
    if C.busy(p.name):
        raise ValueError('この曲は今作り直している')
    with _LOCK:
        meta = _cand_meta(p)
        c = next((c for c in (meta or {}).get('cands') or [] if c['n'] == int(n) and c['state'] == 'done'), None)
        if not c or not _cand(p, n).exists():
            raise FileNotFoundError('その案は無い')
        if not p.exists() or _sha(p) != meta['base_sha']:
            drop_cands(p)
            raise ValueError('結果のファイルが変わったので、この案は使えない（もう一度作る）')
        guard(p, '別の案を選ぶ前')
        pe, _ = prev_version(p)   # 選ぶ前の版の意思入れ（案は区間・形の回だけ作り直した＝外は前の版の意思入れのまま）
        prev = _read(_ver(p, pe['id'], '.automap.json')) if pe else None
        src = _cand(p, n)
        _put_base(p, src, C.base_diff(p), True)   # 基準の難易度だけを案の物に（案は今の結果のファイルから作る＝ふつうは案をそのまま写す）
        rep = _read(_cand(p, n, '.report.md'))
        if rep:   # 報告の中の案のファイルの名前を結果のファイルの名前に（案のファイルの控えの知らせは消す）
            rep = re.sub(r'。NLM で直された結果の控え: old/\S+?\.nlmf', '', rep).replace(src.name, p.name)
            _report_path(p).write_text(rep, encoding='utf-8')
        o0, o1 = meta['only']
        fm = meta.get('form')
        k = sum(fix_region(p, x, y) for x, y in (fm['spans'] if fm else [(o0, o1)])) if fix else 0
        v = c.get('v', c['n'])
        rare, band = bool(c.get('rare')), c.get('band')
        cand = {'v': v, 'variant': c['variant'], 'seed': c['seed']}
        if rare:
            cand['rare'] = True
        if band is not None:
            cand['band'] = band
        wt = _work_text(p, work)
        if wt and prev:
            wt = _merge_regions(prev, wt, [list(x) for x in (fm['spans'] + fm['others'])] if fm else [[o0, o1]])
        e = snapshot(p, 'cand', f'別の案 {v}' + (f'（同じ振り「{fm["group"]}」の {fm["form"]} の形）' if fm else '') + ('（珍しい型まで）' if rare else '') + (f'（{intent.band_text(band)}）' if band is not None else '')
                     + ' を選んだ' + ('（区間を固定）' if k else ''),
                     only=meta['only'], report=rep or '', work=wt, as_written=True, dedupe=False,
                     extra={'cand': cand, 'fixed': k, **({'form': fm} if fm else {})})
        drop_cands(p)
        return {'ok': True, 'version': e, 'report': rep or '', 'only': [o0, o1], 'fixed': k, 'variant': v, 'rare': rare, 'band': band,
                'form': fm}


# ---- つなぐ口 ----

def _nlmf_body(path):
    proj = nlmf.load(path)
    proj.pop('coverData', None)
    return proj


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})"""
    global C
    C = ctx
    if before_generate not in ctx.BEFORE_GENERATE:
        ctx.BEFORE_GENERATE.append(before_generate)
    if after_generate not in ctx.AFTER_GENERATE:
        ctx.AFTER_GENERATE.append(after_generate)
    if compose_extra not in ctx.COMPOSE_EXTRA:   # 前の譜面に寄せる（前の版の作業ファイルを compose へ）
        ctx.COMPOSE_EXTRA.append(compose_extra)
    f = lambda d: C.out_file(d['file'])

    def ver_file(q):
        p = f(q)
        path = _ver(p, _entry(p, q['id'])['id'])
        if not path.exists():
            raise FileNotFoundError('その版のファイルが無い')
        return path

    def cand_file(q):
        p = f(q)
        n = int(q['n'])
        if not _cand_meta(p) or not _cand(p, n).exists():
            raise FileNotFoundError('その案は無い')
        return _cand(p, n)

    def snap(b):
        e = guard(f(b), '手で控えた')
        if e is None:
            raise FileNotFoundError('結果のファイルが無い')
        return {'ok': True, 'version': e}

    get = {
        '/api/versions': lambda q: list_versions(f(q)),
        '/api/versions/chart': lambda q: C.chart(ver_file(q)),
        '/api/versions/nlmf': lambda q: _nlmf_body(ver_file(q)),
        '/api/versions/pending': lambda q: pending(f(q)),
        '/api/versions/report': lambda q: {'md': _read(_ver(f(q), _entry(f(q), q['id'])['id'], '.report.md')) or ''},
        '/api/cands': lambda q: cands_view(f(q)),
        '/api/cands/chart': lambda q: C.chart(cand_file(q)),
        '/api/cands/nlmf': lambda q: _nlmf_body(cand_file(q)),
    }
    post = {
        '/api/versions/restore': lambda b: restore(f(b), b['id'], bool(b.get('work'))),
        '/api/versions/keep': lambda b: set_keep(f(b), b['id'], b.get('keep', True)),
        '/api/versions/delete': lambda b: delete_version(f(b), b['id']),
        '/api/versions/snapshot': snap,
        '/api/cands/start': lambda b: {'id': start_cands(f(b), b.get('only'), b.get('start', 1), b.get('n', N_CANDS), bool(b.get('rare')),
                                                         b.get('band'), b.get('form'))['id']},
        '/api/cands/choose': lambda b: choose(f(b), b['n'], bool(b.get('fix')), b.get('work')),
        '/api/cands/discard': lambda b: (drop_cands(f(b)), {'ok': True})[1],
    }
    return get, post
