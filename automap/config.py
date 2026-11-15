"""設定（PC ごとの場所・好み）の置き場所と読み書き（docs/アプリ仕様.md 21 節・2026-11-03）。

配布物のふり（環境変数 AUTOMAP_AS_DIST＝同梱物の場所・tools/dist/checkset.py dev）: ソースのまま配布物と同じに動かす
（app/config.local.json・.venv-sep・開発用の型のデータベースを見ない・同梱物はその場所から・更新はしない）。

置き場所: 環境変数 AUTOMAP_CONFIG → app/config.local.json（開発の PC・git の管理外）→ 使う人ごとの場所
<LOCALAPPDATA>/AutoNotePlotter/config.json（配布物＝config.local.json を入れない・アプリの場所（Program Files 等）に書かない・更新で消えない）。
各モジュールの CONFIG は読み込んだ時の path()（テストはそれを差し替える）。

項目（どれも省略できる）:
- work_dir: 作業の場所（out/＝結果のファイル・cache/＝分けた音。無ければリポジトリの out/・cache/＝開発の PC）
- sep_dir・sep_variant: 音を分ける部品（PyTorch＋Demucs）を入れた場所と種類（tools/sep_install.py・無ければ開発の .venv-sep）
- setup_done: 初回の設定画面を終えた
- update_check・update_skip・update_ng（アプリの更新・控えた急ぎと NG・app/update.py）・bs_levels・bs_playlists・mapper_name・bs_playlist_last（Beat Saber への書き出し）
- nlm_exe・nlm_rating_exe・library_db・library_root・custom_levels・library_own・njs_auto・njs_offset・expand_step_pct（それぞれのモジュール）
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / 'app' / 'config.local.json'
APP_NAME = 'AutoNotePlotter'
AS_DIST_ENV = 'AUTOMAP_AS_DIST'   # 配布物のふり（tools/dist/checkset.py dev・docs/アプリ仕様.md 23 節）＝同梱物の場所


def app_dir():
    """使う人ごとの置き場所（設定・窓の覚え・記録）"""
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(base) / APP_NAME


def packaged():
    """本物の配布物（埋め込み用の Python がアプリの隣にある＝tools/dist/build_embed.py の形）か"""
    return (ROOT / 'runtime').is_dir()


def as_dist():
    """配布物のふり（ソースのまま動かし、開発の PC にしか無い物＝app/config.local.json・.venv-sep・開発用の
    型のデータベースを見ない）の同梱物の場所か None。同梱物（data/・parts/・runtime/）はその場所から読む"""
    p = os.environ.get(AS_DIST_ENV)
    return Path(p) if p else None


def distributed():
    """配布物として動くか（本物の配布物か、配布物のふり）。アプリの更新だけは本物の配布物でしか動かない（packaged・app/update.py）"""
    return packaged() or as_dist() is not None


def app_root():
    """配布物の形で見たアプリの場所（同梱物 data/・parts/・runtime/ と、作業の場所が決まる前の out/・cache/）。
    配布物のふりは同梱物の場所（リポジトリの out/・cache/ を見ない）・ほかはリポジトリ＝配布物のフォルダ"""
    return as_dist() or ROOT


def path():
    p = os.environ.get('AUTOMAP_CONFIG')
    if p:
        return Path(p)
    if DEV.exists() and as_dist() is None:
        return DEV
    return app_dir() / 'config.json'


def load(p=None):
    """設定 → dict（無い・読めない時は空）"""
    try:
        cfg = json.loads(Path(p or path()).read_bytes().decode('utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def update(changes, p=None):
    """設定の項目を書く（値が None の項目は消す）。ほかの項目・字下げ・行の終わり（CRLF）はそのまま、一時ファイルに書いてから置き換える
    （書いている途中で止まっても設定を壊さない）。設定が読めない時は書かない（ValueError）→ 書いた後の設定"""
    p = Path(p or path())
    cfg, nl = {}, '\n'
    if p.exists():
        raw = p.read_bytes().decode('utf-8-sig')
        try:
            cfg = json.loads(raw)
        except ValueError as e:
            raise ValueError(f'設定のファイル {p.name} を読めないので書かない（{e}）')
        if not isinstance(cfg, dict):
            raise ValueError(f'設定のファイル {p.name} の形が違うので書かない')
        nl = '\r\n' if '\r\n' in raw else '\n'
    for k, v in changes.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=1).replace('\n', nl) + nl)
    os.replace(tmp, p)
    return cfg


def work_dir(cfg=None):
    """作業の場所（設定の work_dir）か None（＝リポジトリの out/・cache/）"""
    w = (load() if cfg is None else cfg).get('work_dir')
    return Path(w) if w else None


def out_dir(cfg=None):
    w = work_dir(cfg)
    return w / 'out' if w else app_root() / 'out'


def cache_dir(cfg=None):
    w = work_dir(cfg)
    return w / 'cache' if w else app_root() / 'cache'
