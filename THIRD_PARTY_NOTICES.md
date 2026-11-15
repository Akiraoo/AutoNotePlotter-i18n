# 第三者のコード・部品のライセンス（THIRD_PARTY_NOTICES）

Auto Note Plotter（ANP・開発のリポジトリ名は nlm-automap）のライセンスは **GNU General Public License v3（GPLv3）** です（全文は [LICENSE](LICENSE)）。
ただし音を分ける道具 `tools/separate.py` と、音を分ける部品をインストールする道具 `tools/sep_install.py` だけは **MIT License** です（5 節）。
GPLv3 にしているのは、Non-Linear Mapper（NLM）Oz-Co2 版から写した「曲の解析」と「3D の見え方」が GPLv3 だからです
（3D の見え方は ArcViewer（GPL-3.0）の移植を含みます）。

この文書は次の4つをまとめます。

1. **写した・移植したコード**（このリポジトリに入っている他所のコード）
2. **合わせて書いた所**（他所のコードの決まり・値に合わせて書いた所。コードの写しではないが記録として残す）
3. **配布物に入る部品**（Python の部品。版は `requirements*.txt` と同じ）と、Demucs の学習済みの重み
4. **同梱しない外部のプログラム・サービス**

最後に、GPLv3 と組み合わせて配る時の注意を書きます。調べた日: 2026-11-03。

---

## 1. 写した・移植したコード

### 1.1 NLM の曲の解析（テンポの推定・構成の解析）

| 項目 | 内容 |
|---|---|
| 出どころ | NLM（Non-Linear Mapper Oz-Co2 版）https://github.com/Oz-Co-two/nlm-oz-co2 の `song_analysis/` |
| 写した物 | `automap/song_analysis/__init__.py`・`service.py`・`structure.py`・`tempo.py` |
| 写した元 | NLM のコミット `94dcf8eac194381296580ee651f2bb58ee529b07`（2026-11-11 に写し直した・最初は 2026-10-26 に `70717ed`） |
| ライセンス | GPLv3（GPL-3.0-or-later）。Copyright (C) 2026 helba（NLM の原作者）・Copyright (C) 2026 Oz-Co2（改変と追加） |
| 変えた所 | なし（手を加えない写し。こちらの都合は外側の包み `automap/analyze_song.py` に置く） |
| 記録 | [automap/song_analysis/SOURCE.md](automap/song_analysis/SOURCE.md)（ファイルごとの SHA-256）・写し直しは `tools/sync_nlm_analysis.py` |

中身に他所から写したコードの記載はありません（方法の名前だけ: McFee & Ellis (2014) のラプラシアン分割 等）。

### 1.2 NLM の 3D の見え方（preview-v4・ArcViewer の移植）

| 項目 | 内容 |
|---|---|
| 出どころ | NLM https://github.com/Oz-Co-two/nlm-oz-co2 の `preview-v4/`・`js/` |
| 写した元 | NLM のコミット `70717ed92d494b27fe103d4458397d7025e9ff42`（2026-10-25 に写した） |
| 記録 | [app/static/preview3d/SOURCE.md](app/static/preview3d/SOURCE.md) |

| 写した物 | 元 | ライセンス |
|---|---|---|
| `app/static/preview3d/preview-v4/preview-v4.js` | NLM の 3D の見え方。**ArcViewer**（https://github.com/AllPoland/ArcViewer/ ）の座標系・シェーダーの振る舞い・環境の物の作りを three.js 向けに移植した物 | GPL-3.0（ArcViewer の派生） |
| `app/static/preview3d/preview-v4/env/*.json`（13 のステージ） | ArcViewer の実行中のシーンから、NLM の原作者の Unity スクリプト（NLMEnvExport.cs）で抜き出したメッシュと階層 | GPL-3.0（ArcViewer 由来） |
| `app/static/preview3d/js/constants.js`・`js/three/chamfer-box.js`・`js/notes/chain-bezier.js` | NLM のコード（preview-v4 が読み込む） | GPLv3 |
| `app/static/preview3d/js/vendor/three/three.module.js` と addons（`postprocessing/` の EffectComposer・MaskPass・Pass・RenderPass・ShaderPass・UnrealBloomPass、`shaders/` の CopyShader・LuminosityHighPassShader、`objects/Reflector`、`utils/BufferGeometryUtils`） | **three.js r160**（https://threejs.org/ ）。NLM の `js/vendor/three/` と同じ物 | MIT（Copyright © 2010-2023 three.js authors・本文は付録 A） |

こちらで変えた所（`preview-v4.js` だけ）: ステージの JSON を読む場所を、このファイルからの相対にした1行（行の末に `[nlm-automap]` の印）と、
視点を引く `setCameraView` を1つ足した。こちらで書いたのは `preview3d.js`（包み）・`nlmf-map.js`・`test.html`・`SOURCE.md`。

### 1.3 NLM の tools/cdp.py（見えない Edge を操作する道具・開発用）

| 項目 | 内容 |
|---|---|
| 写した物 | `tools/nlm_cdp.py` |
| 元 | NLM の `tools/cdp.py`（2026-10-20 に写した） |
| ライセンス | GPLv3 |
| 変えた所 | NLM の場所を環境変数 `NLM_ROOT` で渡すようにした（ファイルの頭に記載） |

### 1.4 NLM の書き出し（Beat Saber へ直接書き出す）

| 項目 | 内容 |
|---|---|
| 出どころ | NLM https://github.com/Oz-Co-two/nlm-oz-co2 の `js/runtime/editor-app.js`（exportMap・buildExportInfo・collectExportDiffs・buildDiffJsonFor ほか）と `serve.py`（/__convert/toOgg の ffmpeg の引数） |
| 写した物 | `automap/bs_export.py`（JavaScript から Python へ書き直した写し。元の関数の名前はファイルの頭とコメントに記載） |
| 写した元 | NLM のコミット `8b378d096036a4d77f4f31773f83389ce180f159`（2026-11-03 に写した） |
| ライセンス | GPLv3。Copyright (C) 2026 helba（NLM の原作者）・Copyright (C) 2026 Oz-Co2（改変と追加） |
| 確かめ | NLM で書き出した物と同じになるかを `tools/nlm_export_check.py` で比べる |

### 1.5 BL のリプレイアプリ（BeatLeader の Web のリプレイの見え方）

| 項目 | 内容 |
|---|---|
| 出どころ | BeatSaber-Web-Replays https://github.com/BeatLeader/BeatSaber-Web-Replays （supermedium の beatsaver-viewer から分かれた物）。組み立て済みの物は BL の公開ページ https://replay.beatleader.com/ から |
| 写した物 | `app/static/blreplay/`（index.html・`build/`＝webpack でまとめた本体と見た目・`vendor/`＝A-Frame ほか・`assets/`＝模型・画像・音・字） |
| 写した元 | 素材の一覧は GitHub のコミット `cb3e9b81776d41cfdc25fa410ce4fdd9811662ed`、ファイルは 2026-11-12 の公開ページ（ファイルごとの SHA-256 は `MANIFEST.json`） |
| ライセンス | MIT（Copyright © 2018 Supermedium・本文は `app/static/blreplay/LICENSE.txt` と付録 A） |
| 中に入っている部品 | A-Frame（MIT・`vendor/aframe-master.min.js`＝中に three.js（MIT））・本体にまとめた npm の部品 JSZip（MIT と GPLv3 の選択・こちらは MIT で使う）・drag-drop（MIT）・NoSleep.js（MIT）・字の Teko（SIL OFL 1.1・`assets/fonts/Teko-OFL.txt`） |
| 一緒に写した物 | Font Awesome Free 6.4.0（`app/static/blreplay/fontawesome/`・アイコン CC BY 4.0・字 SIL OFL 1.1・コード MIT・ページは CDN から読んでいた物を写した） |
| 変えた所 | サーバーの頭からの場所 2 つ（`/assets/…`）をページからの場所に・Font Awesome を写した物から読む（`tools/blreplay_fetch.py` の PATCHES） |
| 記録 | [app/static/blreplay/SOURCE.md](app/static/blreplay/SOURCE.md)・写し直しは `tools/blreplay_fetch.py` |

---

## 2. 合わせて書いた所（コードの写しではない）

他所の作りと同じ答えを出すために、決まり・条件・値を合わせて Python で書いた所です。コードを写したり訳したりした物ではありませんが、
出どころとして記録します。

### 2.1 NLM（GPLv3）の保存形式・書き出し・判定に合わせた所

NLM の .nlmf を読み書きし、NLM と同じ結果を出すために、NLM の `js/runtime/editor-app.js` などの決まりに合わせています。
NLM と同じ GPLv3 なので、ライセンスの上の問題はありません。

| こちらのファイル | 合わせた NLM の作り |
|---|---|
| `automap/nlmf.py` | 保存形式 version 2（`_ENC`・`encArr`・`encSec`・`encDiff`・`flatFromSections`）・レーンのずらし（`laneShiftAll`）・拍→秒（`beatToTimeTM`） |
| `automap/rating.py` | 書き出しの形（`buildDiffJsonFor`・`buildExportInfo`・`flatFromSections`・`EMPTY_V3`） |
| `automap/new_project.py` | 新しいプロジェクトの中身（`buildProjectText`・`initScratchDiff`・`createExtra`） |
| `automap/analyze_song.py` | 曲の解析の呼び方と目盛り（`anaAtGrid`・`audioPosAtBeat`）・結果の整え方 |
| `automap/stats.py` | 振りの続きの警告（`swingConflicts`） |
| `automap/diffs.py`・`automap/njs.py` | 書き出す難易度の印・NJS の項目の扱い |

### 2.2 BS Map Check / bsmap（MIT）の譜面チェックの条件

| 項目 | 内容 |
|---|---|
| 出どころ | BS Map Check https://github.com/KivalEvan/BeatSaber-MapCheck ・bsmap https://github.com/KivalEvan/BeatSaber-JSMap （NLM の `js/mapcheck/mapcheck.js` はこの移植） |
| こちらのファイル | `automap/flow.py` の `handclap`・`hitbox_path`・`_pointing`（isNotePointing と同じ考え）・`DIR_SPACE`（振り抜ける先のマス）と、hitboxStair・hitboxInline・shradoAngle を避ける減点 |
| ライセンス | MIT（Copyright (c) 2021 Kival Evan・本文は付録 A） |

### 2.3 BeatLeader の解析（beatleader-analyzer・MIT）の考え方と値

| 項目 | 内容 |
|---|---|
| 出どころ | beatleader-analyzer https://github.com/BeatLeader/beatleader-analyzer の ParityPredictor・AngleStrain |
| こちらのファイル | `automap/flow.py`（振りの交互・角度の減点の考え方を逆向きに使った。手首の中立角 247.5°・67.5°・292.5°・112.5° と、間が 0.25 秒より空くと軽くなる割合） |
| ライセンス | MIT（元の LICENSE.txt の著作権の行は雛形のまま `Copyright (c) [year] [fullname]`＝持ち主の名前が無い。BeatLeader の物として扱う・本文は付録 A） |

### 2.4 BeatLeader のリプレイの形（Open Replay Format・MIT）

| 項目 | 内容 |
|---|---|
| 出どころ | BS-Open-Replay https://github.com/BeatLeader/BS-Open-Replay （形の説明）・ReplayDecoder https://github.com/BeatLeader/ReplayDecoder （壊れた文字列の長さ・ボムの番号の癖・ノーツの番号の分け方・点の種類ごとの満点） |
| こちらのファイル | `automap/bsor.py`（.bsor を読む・コードは写していない） |
| ライセンス | MIT |

---

## 3. 配布物に入る部品

Windows の配布物に入れる Python の部品です。版は `requirements.txt`・`requirements-sep.txt` と同じ（今の開発の環境で確かめた版）。
ライセンスは各部品の配布の情報（`importlib.metadata` の License-Expression・License・分類と、`*.dist-info` のライセンスのファイル）で確かめました。

**配布物を作る時は、各部品の `*.dist-info/licenses/`（無い物は `*.dist-info/LICENSE` 等）と、部品の中のライセンスのファイル
（`numpy-*.dist-info/licenses/` の同梱物の一覧・`soundfile` の `licensing/license_notes.md`・`torch-*.dist-info/NOTICE` 等）を消さずに入れてください。**
ライセンスの本文はそこにあります（この文書には一覧だけを書きます）。

### 3.1 Python の実行環境（配布物に Python を入れる場合）

| 部品 | 版 | ライセンス | 備考 |
|---|---|---|---|
| Python（CPython） | 3.14.7 | PSF-2.0 | https://www.python.org/ ・組み込みの OpenSSL（Apache-2.0）・libffi（MIT）・zlib・expat・bzip2・libmpdec・SQLite（public domain）ほか。Microsoft Visual C++ ランタイムの DLL を含む。ふつうの Python には Tcl/Tk（tkinter・BSD 型）も入る（埋め込み用の Python には入っていない）。ライセンスの本文は Python の `LICENSE.txt`（https://docs.python.org/3.14/license.html ） |

### 3.2 本体（`requirements.txt`）

| 部品 | 版 | ライセンス | 何に使う |
|---|---|---|---|
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 計算全般。`numpy.libs` に OpenBLAS（BSD-3-Clause）・LAPACK（BSD-3-Clause）・GCC runtime library（GPL-3.0-or-later WITH GCC-exception-3.1）・MSVC ランタイムを含む |
| scipy | 1.18.1 | BSD-3-Clause | 信号処理・統計。`scipy.libs` に OpenBLAS（同上）。Qhull 等の同梱物は各フォルダのライセンスのファイル |
| soundfile | 0.14.0 | BSD-3-Clause | 音源の読み書き。**libsndfile 1.2.2（LGPL-2.1-or-later）の DLL** と、それに組み込まれた libogg・libvorbis・FLAC・Opus（BSD 型）・mpg123（LGPL-2.1）・LAME（LGPL）ほかを含む（`licensing/license_notes.md`） |
| cffi | 2.1.1 | MIT-0 | soundfile が使う |
| pycparser | 3.11 | BSD-3-Clause | cffi が使う |
| librosa | 1.0.0 | ISC | 曲の解析・歌の高さ |
| scikit-learn | 1.9.1 | BSD-3-Clause | 曲の解析（構成） |
| threadpoolctl | 3.7.0 | BSD-3-Clause | 曲の解析のスレッドの数 |
| joblib | 1.6.0 | BSD-3-Clause | scikit-learn が使う |
| cloudpickle | 3.1.2 | BSD-3-Clause | joblib が使う |
| narwhals | 2.27.1 | MIT | scikit-learn が使う |
| numba | 0.68.0 | BSD-2-Clause | librosa が使う（同梱物は `LICENSES.third-party`） |
| llvmlite | 0.50.0 | BSD-2-Clause AND Apache-2.0 WITH LLVM-exception | numba が使う（LLVM を含む・`LICENSE.thirdparty`） |
| soxr | 1.1.0 | **LGPL-2.1-or-later** | librosa が使う（libsoxr（LGPL-2.1-or-later）・PFFFT（BSD 型）を含む） |
| lazy-loader | 0.6 | BSD-3-Clause | librosa が使う |
| decorator | 5.3.1 | BSD-2-Clause | librosa が使う |
| msgpack | 1.2.3 | Apache-2.0 | librosa が使う |
| pooch | 1.9.0 | BSD-3-Clause | librosa が使う |
| platformdirs | 4.13.5 | MIT | pooch が使う |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | pooch が使う |
| requests | 2.34.2 | Apache-2.0 | pooch が使う（NOTICE あり） |
| urllib3 | 2.8.0 | MIT | requests が使う |
| idna | 3.20 | BSD-3-Clause | requests が使う |
| charset-normalizer | 3.5.2 | MIT | requests が使う |
| certifi | 2026.10.23 | MPL-2.0 | requests が使う |
| typing_extensions | 4.16.0 | PSF-2.0 | soundfile・librosa が使う |
| pywebview | 6.2.1 | BSD-3-Clause | 窓のアプリ（`app/desktop.py`）。付属の JavaScript に domJSON（MIT）・Native Promise Only（MIT）・Symbol-ES6（MIT）。`webview/lib/` に Microsoft WebView2 SDK の DLL（Microsoft.Web.WebView2.Core・WinForms・WebView2Loader＝Microsoft の BSD-3-Clause 型のライセンス）と WebBrowserInterop の DLL |
| bottle | 0.13.4 | MIT | pywebview が使う |
| proxy_tools | 0.1.0 | MIT | pywebview が使う |
| pythonnet | 3.2.1 | MIT | pywebview が使う（Python.Runtime.dll） |
| clr_loader | 0.3.1 | MIT | pythonnet が使う（ClrLoader.dll） |

### 3.3 音を分ける環境（`requirements-sep.txt`・`.venv-sep`）

| 部品 | 版 | ライセンス | 何に使う |
|---|---|---|---|
| torch（PyTorch・CUDA 12.8 版） | 2.11.0+cu128 | BSD-3-Clause（NOTICE に同梱物の一覧） | Demucs を動かす。**Windows の CUDA 版は `torch/lib/` に NVIDIA の DLL**（CUDA runtime・cuBLAS・cuFFT・cuRAND・cuSOLVER・cuSPARSE・cuDNN・NVRTC・nvJitLink・CUPTI・NVTX＝NVIDIA のソフトウェアのライセンス）と **Intel OpenMP（libiomp5md.dll＝Intel のライセンス）**、libuv（MIT）・zlib を含む |
| torchaudio | 2.11.0+cu128 | BSD-2-Clause | 今の環境に入っている（demucs 4.1.0 の分けるだけなら読み込まない） |
| demucs | 4.1.0 | MIT（Copyright (c) Meta Platforms, Inc. and affiliates.） | 音源分離（https://github.com/adefossez/demucs ・facebookresearch/demucs の続き） |
| einops | 0.8.2 | MIT | demucs が使う |
| julius | 0.2.8 | MIT | demucs が使う |
| lameenc | 1.9.0 | **LGPL-3.0-or-later** | demucs が使う（LAME（LGPL）を含む） |
| safetensors | 0.8.0 | Apache-2.0 | demucs が使う（重みの読み込み） |
| sphn | 0.2.1 | Apache-2.0（ライセンスのファイル） | demucs が使う |
| huggingface_hub | 2.2.0 | Apache-2.0 | demucs が重みを取る |
| hf-xet | 1.7.0 | Apache-2.0 | huggingface_hub が使う |
| httpx2 | 2.15.1 | BSD-3-Clause | huggingface_hub が使う |
| httpcore2 | 2.15.1 | BSD-3-Clause | httpx2 が使う |
| h11 | 0.16.0 | MIT | httpcore2 が使う |
| truststore | 0.10.5 | MIT | httpcore2 が使う |
| anyio | 4.15.1 | MIT | httpx2 が使う |
| idna | 3.20 | BSD-3-Clause | anyio が使う |
| click | 8.5.0 | BSD-3-Clause | huggingface_hub が使う |
| PyYAML | 6.0.3 | MIT | demucs・huggingface_hub が使う |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | 進み具合の表示 |
| colorama | 0.4.6 | BSD-3-Clause | tqdm・click が使う |
| filelock | 3.32.3 | MIT | torch が使う |
| fsspec | 2026.7.0 | BSD-3-Clause | torch が使う |
| Jinja2 | 3.1.6 | BSD-3-Clause | torch が使う |
| MarkupSafe | 3.0.3 | BSD-3-Clause | Jinja2 が使う |
| networkx | 3.6.1 | BSD-3-Clause | torch が使う |
| sympy | 1.14.0 | BSD-3-Clause | torch が使う |
| mpmath | 1.3.0 | BSD-3-Clause | sympy が使う |
| setuptools | 78.1.0 | MIT（同梱の部品は各ライセンス） | torch が使う |
| numpy・soundfile・cffi・pycparser・packaging・typing_extensions | 3.2 と同じ | 3.2 と同じ | |

### 3.4 Demucs の学習済みの重み（htdemucs_ft）

| 項目 | 内容 |
|---|---|
| 物 | htdemucs_ft（4つのモデルの平均。safetensors 4つ・合わせて約 340MB） |
| 取る所 | Hugging Face の `adefossez/HTDemucs-ft`（取れなければ Meta の `dl.fbaipublicfiles.com/demucs/`）。初めて分ける時に Demucs が取り、利用者の PC の Hugging Face の置き場に置く |
| ライセンス | **決まっていない**。Hugging Face のページにライセンスの記載が無い。Demucs の README（adefossez/demucs）は「コードは MIT。重みのライセンスははっきりしない（MusDB に研究目的でしか使えないデータが含まれる・Meta の内部のデータで学習した）・作者は許可を出せない」としている |
| 学習に使ったデータ | MusDB HQ と 800 曲（Meta の内部のデータ） |

→ **重みは配布物に入れず、今と同じく利用者の PC が初回に取る**形をすすめます。重みはこのプログラムの GPLv3 の対象外です。

### 3.5 開発用（`requirements-dev.txt`・配布物には入れない）

| 部品 | 版 | ライセンス |
|---|---|---|
| pytest | 9.1.1 | MIT |
| pytest-xdist | 3.8.0 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| execnet | 2.1.2 | MIT |
| pluggy | 1.7.0 | MIT |
| iniconfig | 2.3.1 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| colorama | 0.4.6 | BSD-3-Clause |

---

## 4. 同梱しない外部のプログラム・サービス

| 物 | ライセンス | 使い方 |
|---|---|---|
| NLM（Non-Linear Mapper Oz-Co2 版）https://github.com/Oz-Co-two/nlm-oz-co2 | GPLv3 | 利用者が別に入れる。作った .nlmf を NLM で開く（設定の `nlm_exe`）。開発用の `tools/nlm_project.py` は NLM のフォルダの `serve.py` と譜面チェック（`js/mapcheck/mapcheck.js`＝BS Map Check の移植・MIT）を NLM の Python で動かす |
| nlm-rating https://github.com/Oz-Co-two/nlm-rating | MIT（中に BeatLeader の RatingAPI・beatleader-analyzer・beatleader-parser（MIT）、ONNX Runtime（MIT）ほか） | 作った譜面の★の近似。無くても動く（設定の `nlm_rating_exe`）。**同梱するなら nlm-rating の LICENSE と THIRD_PARTY_NOTICES.txt も一緒に入れる** |
| ffmpeg | LGPL / GPL（組み立て方による） | m4a など soundfile で読めない音源だけ。PATH にあれば使う |
| Microsoft Edge WebView2 Runtime | Microsoft のライセンス | 窓のアプリの表示。Windows に入っている物を使う |
| BeatPlayAnalyzer の `bsor.py` | （その道具のライセンス） | 開発用の `tools/replay_check.py` が実行の時にファイルから読む（場所は `--bsor`・環境変数 `BPA_BSOR`） |
| BeatLeader の API・BeatSaver の API | 各サービスの規約 | 開発用の `tools/library_build/fetch.py`（型のライブラリの元の譜面と情報を取る）。BL のリプレイアプリ（1.5）は開いた時に BeatLeader の API からプレイヤーの公開プロフィール（名前・アイコン）を読む |
| Hugging Face | 各サービスの規約 | Demucs の重みを取る（3.4） |

型のライブラリ（他人の譜面から作ったデータベース）の配り方は相談中です（docs/アプリ仕様.md 21 節）。この文書の対象外です。

---

## 5. GPLv3 と組み合わせて配る時の注意

- **合うライセンス**: 上の部品の MIT・MIT-0・BSD・ISC・0BSD・Zlib・CC0・PSF-2.0・Apache-2.0・MPL-2.0・LGPL-2.1-or-later・LGPL-3.0-or-later・
  GCC runtime library の例外つき GPL は、どれも GPLv3 のプログラムと一緒に配れます。
- **LGPL の部品**（soundfile の中の libsndfile・mpg123・LAME、soxr の中の libsoxr、lameenc の中の LAME）: 配布物に入れる時は、同じ版のソースの
  入手先を示す（NLM は各リリースに LGPL の部品のソースをまとめた zip を添付している）。利用者が差し替えられるよう、DLL・wheel の形のまま入れる。
- **GPLv3 のソース**: 配布物（exe・zip）を配る時は、同じ版のこのリポジトリのソース（配布物を組み立てる台本も含む）を入手できるようにする。
- **NVIDIA・Intel の DLL（PyTorch の CUDA 版）**: GPLv3 と合わないライセンス（それぞれの会社のライセンス・再配布は各社の条件の範囲）。
  これを読み込むのは音を分ける `tools/separate.py` だけで、本体は別のプロセスとして呼んでいる（コマンドの引数とファイルでやり取り）。
  **決めた（2026-11-03）**: `tools/separate.py` と、音を分ける部品をインストールする道具 `tools/sep_install.py` は **MIT License** にする（ファイルの頭に
  本文。NLM から写した物を含まない・本体の GPLv3 のコードを読み込まない）。PyTorch（CPU 版・GPU 版）と Demucs はこちらでは配らず、
  初めて使う時に利用者の PC が公式の置き場（download.pytorch.org・PyPI）から取る。CPU 版の PyTorch にも Intel OpenMP は入る。
- **Demucs の重み**（3.4）: ライセンスがはっきりしない（研究目的に限るデータを含む）。配布物に入れず、使う時に利用者の PC が取る形にし、使う人向けの
  説明にそのことを書く。

---

## 付録 A. MIT License の本文

第1部・第2部の MIT の物（three.js・BS Map Check / bsmap・beatleader-analyzer・BL のリプレイアプリ）に当てはまる本文です。著作権の表示:

- three.js r160: Copyright © 2010-2023 three.js authors
- BS Map Check / bsmap: Copyright (c) 2021 Kival Evan
- beatleader-analyzer: Copyright (c) [year] [fullname]（元の LICENSE.txt の表記のまま。BeatLeader の物）
- BeatSaber-Web-Replays（BL のリプレイアプリ・1.5）: Copyright © 2018 Supermedium（中の A-Frame・JSZip・drag-drop・NoSleep.js もそれぞれの作者の MIT）

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 付録 B. GPLv3 の部品の著作権の表示

NLM から写した物（1.1・1.2 の NLM のコード・1.3）の元の表示です。

```
Non-Linear Mapper (NLM)
Copyright (C) 2026 helba (original author)
Copyright (C) 2026 Oz-Co2 (modifications and additions)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
```

ArcViewer（1.2 の移植元）: https://github.com/AllPoland/ArcViewer/ ・GNU General Public License v3.0。
GPLv3 の全文はこのリポジトリの [LICENSE](LICENSE) にあります。
