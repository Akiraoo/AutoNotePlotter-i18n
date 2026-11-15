# 配布物の作り方（試作・2026-11-03）

docs/アプリ仕様.md 21 節「そのままダウンロードして使える Windows の配布物」の試作と見積もり。ここの台本は配布物を作るだけで、
本体（app/・automap/・tools/ のほかのファイル）は変えない。

## 作り方（おすすめ: 埋め込み用の Python＋部品＋起動用の小さな exe）

```
py -3.14 -m venv <作業>\venv-build                      # ビルド用（.venv とは別・版は埋め込み用と同じ 3.14）
<作業>\venv-build\Scripts\python.exe tools\dist\build_embed.py --work <作業> --compile --zip
<作業>\venv-build\Scripts\python.exe tools\dist\check_dist.py <作業>\build\AutoNotePlotter --scratch <空の場所> [--window]
```

- `build_embed.py`: python.org の埋め込み用の Python（embeddable zip）を展開 → `._pth` に本体の場所を足す → 部品
  （`requirements-dist.txt`＝.venv の版にそろえた物）を `pip --target` で `runtime\Lib\site-packages` へ → app/・automap/・tools/ を写す
  （`__pycache__`・`config.local.json`・tools/dist は入れない）→ 起動用の exe（`launcher.cs` を Windows に入っている .NET Framework 4 の
  csc.exe で・アイコンは app/desktop.py がコードで描く物）→ .pyc（checked-hash）→ zip。1 分ほど（部品は pip の控えから）。
  版は `automap/version.py` の VERSION（build-info.json・zip の名前・update.json）。`--zip` で `<作業>\build\release\` に GitHub の
  リリースに添付する 2 つ（`AutoNotePlotter-<版>-win-x64.zip`・`update.json`）を作り、アプリの更新と同じ確かめ（照合・展開・版）に通す。
  `--version v〇.〇.〇` は確かめ用（配布物の中の automap/version.py の VERSION の行だけ書き換える＝更新を確かめる 2 つ目の版）。
- `checkset.py`（確かめのセット・docs/アプリ仕様.md 23 節）: `dev`＝配布物のふり（ソースのまま・環境変数 AUTOMAP_AS_DIST で開発の PC に
  しか無い物を見ない）でアプリを起動・`release`＝リリースの前の通しの確かめ（全部のテスト＝曲の解析の答え合わせは控えを使わずに計算 → 作る → check_dist.py → まっさらな設定 → 部品 → デモ曲の取り込み・
  作り直し・★・展開・書き出し → C ドライブ → 更新 → `run/report.md`）。置き場は PC ごと（`--dir` か app/config.local.json の check_dir）。
  リリースの前は `.venv\Scripts\python.exe tools\dist\checkset.py release` が通ることを確かめる。
- `demo_song.py`: 確かめ・チュートリアル用のデモ曲（自分で合成・80 秒・BPM 120）とカバー画像。
- `check_dist.py`: 作った物だけで、部品の読み込み（numba の JIT・pythonnet の .NET も）・DLL の足りない物・曲の解析
  （`-m automap.analyze_song` を合成の音で）・サーバー（空の --out・--cache）・画面・止める・（--window）起動用の exe から窓のアプリの
  確かめ（desktop.py --selftest・LOCALAPPDATA は作業の場所に替える）。

中身:
```
AutoNotePlotter\
  AutoNotePlotter.exe 起動用（runtime\pythonw.exe app\desktop.py を起動してすぐ終わる・PYTHONHOME 等を消す）。--apply-update で更新の差し替え役
  runtime\            埋め込み用の Python 3.14 ＋ Lib\site-packages（numpy・scipy・librosa・scikit-learn・numba・pywebview・pythonnet…）
  app\ automap\ tools\  このリポジトリの写し（.py のまま＋.pyc）
  data\ parts\        配布用の型のライブラリ・★を測る部品（nlm-rating）
  LICENSE  THIRD_PARTY_NOTICES.md  build-info.json（version＝automap/version.py の VERSION・git＝git describe）
  （更新の間だけ）_update\＝ダウンロード・展開の作業場所・_previous_<版>\＝差し替える前の版（1 世代）
```

### PyInstaller（NLM のやり方）にしない理由

- **作り直し・曲の解析・ファイルの窓を `sys.executable -m automap …`／`-c …` の別のプロセスで動かしている**（app/server.py の
  compose_cmd・app/importer.py）。PyInstaller で固めると sys.executable は固めた exe になり、`-m`・`-c` を受ける入口を自分で書くか、
  本体を直す必要がある。埋め込み用の Python なら本物の python.exe なので今のコードのまま動く（確かめた）。
- 音を分けるパック（PyTorch＋Demucs）は固めにくく（数 GB・CUDA の DLL）、どのみち本物の Python で動かす → 本体も同じ作りにそろう。
- numba・librosa（lazy_loader の .pyi）・pythonnet を固める時のはまりどころ（NLM の nlm.spec に hiddenimports・collect_all が並ぶ）が無い。
- 更新は app\・automap\・tools\（数 MB の .py）を入れ替えるだけで済む版が多い（部品の版を上げた時だけ runtime\ ごと）。
- GPLv3 の「元のコードを渡す」が、配布物の中の .py そのもので済む。
- PyInstaller の起動用の exe（bootloader）はウイルス対策ソフトに誤検知されやすい。起動用の exe は 100KB の .NET の物で、python.exe・
  pythonw.exe・python314.dll は PSF の署名付き。
- 悪い所: ファイルの数が多い（展開が遅い）・中身の .py が見える（GPL なので問題ない）。大きさは NLM（PyInstaller・同じ解析の部品）と同じくらい。

### ._pth のはまりどころ（2026-11-03 に3通りを比べた）

- `._pth` を外すと、Windows はレジストリの PythonPath（その PC に入っている**同じ版の Python の Lib・DLLs**）を sys.path に混ぜる
  （この PC では tkinter が「ある」ことになった＝まっさらな PC と違う動き）。
- `._pth` があると隔離の決まり（PYTHONPATH・レジストリ・ユーザーごとの site-packages を見ない・スクリプトの場所も今の場所も sys.path に
  足さない）。→ `..`（automap）・`..\app`（server.py をスクリプトで動かす時の importer 等）・`..\tools`（区間の点検が読む library_themes 等）を書き足す。
- PYTHONIOENCODING は `._pth` があっても効く（作り直しの記録を utf-8 で受け取る今の作りのまま）。
- 埋め込み用の Python に tkinter は無い → ブラウザで使うやり方（server.py）の「選ぶ…」（`importer.tk_pick`）は動かない。窓のアプリは
  pywebview のファイルの窓なので動く。配布物は窓のアプリだけにする。

## 音を分けるパック（PyTorch＋Demucs）

| 物 | 大きさ | 出どころ |
|---|---|---|
| torch 2.11.0 CPU 版（cp314・win_amd64） | wheel 116 MB | PyPI か download.pytorch.org/whl/cpu |
| torch 2.11.0+cu128（GPU・今の .venv-sep） | wheel 2,771 MB（展開 4.2 GB） | download.pytorch.org/whl/cu128 |
| torch 2.11.0+cu126 | wheel 2,617 MB | download.pytorch.org/whl/cu126（古い GPU も） |
| torch 2.11.0+cu130 | wheel 1,922 MB | download.pytorch.org/whl/cu130（CUDA 13＝新しいドライバーが要る・古い GPU を切った） |
| demucs 4.1.0 と小物（huggingface_hub・safetensors・einops・julius・sphn・lameenc・pyyaml・tqdm・sympy・networkx 等） | 30 MB ほど | PyPI |
| htdemucs_ft の重み（4 つ） | 84 MB×4＝336 MB | Hugging Face `adefossez/HTDemucs-ft`（.safetensors）。前の置き場 dl.fbaipublicfiles.com（.th・84 MB×4）にもある |
| htdemucs（速い・1 つ） | 84 MB | Hugging Face `adefossez/HTDemucs` |

- demucs 4.1.0 はモデルの名前をまず Hugging Face から取る（`demucs/hf.py`・`hf_hub_download`・置き場は HF_HOME の hub/）。取れなければ
  前の置き場（AWS・torch.hub の置き場）。torchaudio は要らない（学習用の extra だけ）。
- **ネットなしで動く**: 一度取れば `HF_HUB_OFFLINE=1`（と通らないプロキシ）で読めた（下の「確かめた結果」）。パックの中に重みを入れるなら
  HF_HOME をパックの場所にして HF_HUB_OFFLINE=1 で起動する（demucs・separate.py を変えずに済む）。
- GitHub のリリースの1つのファイルは 2 GiB まで → GPU 版の torch（cu128 2.8 GB）はそのまま置けない。

案（おすすめ）: **パックは「最初に使う時に取ってくる」形**。
1. 本体の配布物と同じ埋め込み用の Python をもう 1 つ（12 MB）＋demucs と小物（30 MB）＝小さな zip を自分のリリースに置く。
2. torch は使う時に PyTorch の公式の置き場（download.pytorch.org）から取る: NVIDIA の GPU があれば（nvidia-smi・WMI で見る）cu128
   （2.8 GB）、無ければ CPU 版（116 MB）。置き場の一覧に `#sha256=` が付いているので確かめてから展開（wheel は zip＝pip なしでも入る。
   pip を入れて `pip install torch --index-url …` でもよい・pip 24.2 以降は Windows の証明書の置き場を使うので Kaspersky 等の中継でも通る）。
3. 重みは使う時に Hugging Face から（336 MB）。取った後は HF_HUB_OFFLINE=1 で動かす。重みの再配布の決まり（Demucs のコードは MIT・
   Hugging Face の置き場にはライセンスの印が無い）は確かめてから、自分のリリースにも置くか決める。
4. 置き場所は本体の外（`%LOCALAPPDATA%\automap-app\sep\` 等）・アプリの画面に「音を分ける部品を入れる（GPU 2.8 GB／CPU 0.1 GB＋モデル
   0.3 GB）」のボタンと進み具合。今の importer は `ROOT\.venv-sep\Scripts\python.exe` 決め打ち（下の一覧）。
- CPU 版は遅い（下の「確かめた結果」）→ CPU の時は htdemucs（1 つ・84 MB）や shifts 1 を既定にする案も。

## 開発の PC が前提になっている所（直さずに一覧・直し方の案）

| 場所 | 今 | 困ること | 直し方の案 |
|---|---|---|---|
| app/server.py `OUT, CACHE = ROOT/'out', ROOT/'cache'`・automap/__main__.py の `--out` の既定 `ROOT/'out'`・tools/listen_page.py | 本体の隣 | Program Files に置くと書けない・更新で本体を入れ替える時に巻き込む | 「作業の場所」を設定に（既定 `ドキュメント\nlm-automap\` 等）。out と cache はその下。曲 1 つで分けた音が 100 MB ほど＝場所を選べるように |
| app/config.local.json（server・library_db・njs・rating・expand が読む。expand は `expand_step_pct` を**書く**） | 本体の中 | Program Files で書けない・更新で消える | `%LOCALAPPDATA%\automap-app\config.json`（desktop.py の data_dir と同じ所）へ。読む所を 1 つの関数にまとめる |
| automap/library_use.py `CACHE_THEMES = ROOT/'cache'/'themes.json'`・__main__ の `--themes` の既定 | 開発の PC で作った物（手元の譜面から・git の管理外） | 配布物に無い＝ライブラリの設定の無い曲・データベースが使えない時の戻り先が無く作り直しが落ちる | 配布用のデータベース（21 節の案）だけにして、戻り先も配布用のデータベースの既定の絞り込みに。themes.json を残すなら配布用に作り直して `data\` に（手元の譜面から作った物は配らない） |
| automap/library_db.py の場所（引数・AUTOMAP_LIBRARY・config の library_db／library_root） | 開発の PC の SSD | 配布物に無い | 配布用のデータベースを本体と一緒に `data\library.sqlite`（読むだけ）に置き、設定が無ければそれ。読むだけの場所では `?mode=ro&immutable=1` で開く（WAL の -shm を作ろうとして失敗しないように） |
| app/importer.py `SEP_PY = ROOT/'.venv-sep'/'Scripts'/'python.exe'` | 開発の .venv-sep | パックの場所が違う・無い | 設定の `sep_python`（無ければパックの決まった場所）。無い時は「音を分ける部品を入れる」へ案内。HF_HOME・HF_HUB_OFFLINE を渡す |
| tools/separate.py の重みの置き場 | 利用者のホームの `.cache\huggingface` | パックを消しても残る・ネットが要る | パックの場所の HF_HOME に |
| NLM の場所（config の nlm_exe・NLM_EXE） | 開発の PC | 無い | 初回の設定で選ぶ（無くても動く・「NLM で開く」だけ薄く） |
| nlm-rating（config の nlm_rating_exe・NLM_RATING_EXE） | 開発の PC | 無い | 無くても動く（★が出ないだけ）。入れるなら nlm-rating のリリースから取る（ライセンスを確かめる）か設定で選ぶ |
| 型のライブラリの手元の譜面（config の custom_levels・library_own） | 開発の PC | 取り込み・作り直しには要らない（作る道具 tools/library_build だけ） | 配布物では使わない |
| app/desktop.py `pythonw()`・`--shortcut` | ROOT\.venv\Scripts\pythonw.exe | 配布物では pythonw＋desktop.py のショートカットになる | 配布物では起動用の exe を指すショートカットに（初回に「デスクトップに置く」） |
| app/importer.py `tk_pick`（tkinter） | .venv には tkinter がある | 埋め込み用の Python に無い | 配布物は窓のアプリだけ（pywebview のファイルの窓）。ブラウザのやり方を残すなら tkinter を足す（10 MB ほど） |
| app/server.py `server_version = 'automap/0.1'`・版の数 | 固定 | 更新の知らせに版が要る | 済み: 版は automap/version.py の VERSION だけ（server_version は窓のアプリが「このアプリが動いているか」を見る印なのでそのまま） |
| tools/theme_spread.py 等の PC の場所・曲名（21 節） | 文書・台本 | 公開の時 | 21 節の掃除で |
| numba の控え（librosa の `cache=True`） | site-packages の __pycache__ | Program Files では書けない | numba が自分でユーザーごとの場所に替える（そのままでよい） |
| WebView2 | Windows 11 は入っている | Windows 10 の一部に無い | 起動で見つからなければ Microsoft の Evergreen の入れ方へ案内 |

### 初回の設定画面に要る物

1. 作業の場所（out・cache を置く所・空きの目安＝1 曲 100 MB ほど）。既定はドキュメントの下。
2. 音を分ける部品: GPU（NVIDIA）か CPU か（見つけた GPU を出す）→「入れる」（大きさと時間の目安・取ってくる進み具合・やめる・あとで）。
   入れずに「分けた音が済んでいる曲だけ」でも開ける。
3. NLM の場所（NonLinearMapper.exe を選ぶ・無くてもよい・NLM のリリースのリンク）。
4. nlm-rating（★）: 無くてもよい。
5. 型のライブラリ: 配布用のデータベースが同梱なら設定なし（場所を変える時だけ）。
6. 更新を確かめるか（既定 ON・NLM と同じ）。
7. デスクトップにショートカットを置くか。

## 署名・更新・リリースの大きさ

- 署名: 起動用の exe に署名が無いと、zip から出した最初の起動で SmartScreen（「Windows によって PC が保護されました」→ 詳細情報 →
  実行）。python.exe・pythonw.exe・python314.dll は PSF の署名付きなので出るのは起動用の exe だけ。費用をかけない道は SignPath Foundation
  （オープンソースに無料で署名）・Azure の署名の仕組み（月額・個人で使えるかは国による）。EV 証明書でも今は SmartScreen の評判は
  すぐには付かない。
- 更新: 作った（2026-11-03・下の「アプリの更新」）。本体だけの小さな zip（数 MB）と全部の zip を分ける案は、まだ（今は毎回全部
  ＝180 MB）。分けるなら update.json の形の版（FORMAT）を上げずに項目を足す形で（古い版は知らない項目を読まない）。
- GitHub のリリース: 1 つのファイルは 2 GiB 未満・リリース全体の大きさと配る量には上限なし（GitHub の説明）。本体の zip（150 MB）・
  CPU のパックは置ける。GPU 版の torch（2.8 GB）は置けない → 公式の置き場から取る（上の案）か、分けて置く。リポジトリ（git）には
  100 MB を超えるファイルを入れられない（リリースの添付は別）。

## 確かめた結果（2026-11-03・このPC）

- 大きさ: 展開して **439 MB**（runtime 26 MB・site-packages 407 MB＝llvmlite 122・scipy 115・scikit-learn 43・numpy 33＋21・numba 28・
  scipy.libs 20・本体の .py＋.pyc 6 MB）・**zip 151 MB**（deflate 9）。NLM の PyInstaller の配布物（同じ解析の部品）は 290 MB。
  .pyc を入れない（--compile なし）と少し小さいが、Program Files に置くと毎回の読み込みが遅くなるので入れる。
- ビルド: 1 分足らず（埋め込み用の Python 3.14.7＝12.7 MB・sha256 d297e5ff…1f15 は python.org の公開の値と照らしてから `PY_SHA256` に入れる）。
- `check_dist.py`（.venv・この PC の Python の場所を PATH から外し、起動用の exe と同じ環境で）: 部品の読み込み（4.4 秒・numba の JIT・
  pythonnet で .NET 4.8）・曲の解析（合成の 40 秒の曲・9 秒・BPM 120）・サーバー（8767・空の --out/--cache・画面・JS・止める）が全部 OK。
- 窓のアプリ: 起動用の exe → pythonw → desktop.py --selftest（LOCALAPPDATA を作業の場所に）で、窓が開いて画面の読み込み・3D（WebGL）・
  ×で閉じてサーバーが止まる まで OK（曲が無いので「曲を開く」「音」は確かめていない）。
- 合成の曲で「分けた音（合成の音を 4 つに写した物）→ 元のプロジェクト（`-m automap.new_project`・18 秒）→ 作り直し（`-m automap compose
  --form --style`）」: 設定なしは `<配布物>\cache\themes.json` が無くて落ちた（一覧の通り）。型のデータベース（読むだけ・AUTOMAP_LIBRARY・
  `--library '{"sources":["ranked"]}'`）を渡すと 5.5 秒で結果のファイルと報告ができた。
- DLL: 埋め込み用の Python は vcruntime140(_1).dll しか持たず、numba・scikit-learn・soxr 等が **MSVCP140.dll・VCOMP140.DLL** を読む
  （この PC は再頒布可能パッケージが入っているので気付かない）→ ビルドで System32 から runtime\ へ写すようにした（NLM の配布物も同梱）。
  tbb12.dll（numba の並列の一つ）は無いが、numba はほかのやり方に替えるので問題ない（NLM も同じ）。
- 音を分けるパック（.venv-sep で・GPU を隠して）: `HF_HUB_OFFLINE=1`＋通らないプロキシでも htdemucs_ft の重みを手元の控えから 1.6 秒で
  読めた＝ネットなしで動く。CPU（12 スレッド）で 20 秒の音に 23 秒（htdemucs_ft・shifts 1）→ 4 分の曲で shifts 1 なら 5 分ほど・
  今の既定の shifts 2 なら 10 分ほど（GPU は 48 秒）。
- まだ: まっさらな Windows（VM・Windows Sandbox）で zip を展開して動かす・WebView2 の無い Windows 10・日本語の場所に展開・
  Program Files に置いた時。

## アプリの更新（2026-11-03・NLM の app_update.py と同じ流れ・詳しくは app/update.py の頭）

利用者「バージョンアップの仕組みも NLM 同等に用意したい」。

1. 起動した時（上の列の版のボタンの窓の「起動した時に新しい版があるか確かめる」＝設定の `update_check`・既定はオン）か、同じ窓の
   「更新を確認」で、GitHub の最新リリースの `update.json` を読む（`app/update.py`・`/api/update/check`）。開発の PC（配布物でない）は確かめない。
2. 新しい版があれば右上の知らせ（あとで・変更点を見る・更新する）→ 窓に変更点（今の版より新しい版の分）。「この版は飛ばす」＝設定の
   `update_skip`（起動した時にはその版まで知らせない）。
3. 「更新する」: zip をダウンロードして update.json の SHA-256・大きさと照合 → `<アプリ>\_update\new\AutoNotePlotter\` へ展開
   （フォルダの外へ出る名前・最上位が違う名前を拒む・中身の版を確かめる）→ 作業ファイルを保存 → 展開した**新しい版の**
   `AutoNotePlotter.exe --apply-update --target <アプリ> --pid <今のアプリ>` を起動 → 今のアプリは終わる（/api/shutdown）。
   作り直し・取り込みなどの作業の途中は差し替えない。
4. 新しい版の exe（launcher.cs）: 小さな窓「更新しています」を出し、古いアプリが終わるのを待って（60 秒まで）、決めた物
   （AutoNotePlotter.exe・runtime・app・automap・tools・data・parts・LICENSE・THIRD_PARTY_NOTICES.md・build-info.json）を
   `_previous_<古い版>\` へ移し（前の退避は消す＝1 世代）、新しい版の物を移して置く（同じドライブの中なのですぐ終わる）→ 起動し直す。
   失敗したら退避した物を戻し、古い版のまま起動し直す（知らせを出す）。記録は `_update\apply.log`。
5. 起動し直したアプリが `_update\` を片付け（記録は `<LOCALAPPDATA>\AutoNotePlotter\update.log` へ写す）、「〇〇に更新しました」。

公開する時（GitHub への push・リリースは利用者が決める）: automap/version.py の VERSION を上げて CHANGES の頭に変更点・docs/リリースノート.md の
頭にその版の節 → master にコミット（作業のフォルダをきれいに＝build-info.json の git が -dirty にならない）→ `checkset.py release`（配布物を作るのも
この中・`<作業>\build\release\` に zip と update.json）→ **公開版**: `tools/dist/make_public.py`（public ブランチに「<版> 公開」の 1 コミットとタグ・
開発の履歴とコミットの文は GitHub に出さない・この PC のユーザーのフォルダ・NAS・メールアドレス・リポジトリの置き場・開発の設定の場所が入って
いれば止まる・`--check` は検査だけ）→ `git push github public:master` と `git push github <版>`（NAS にも `git push origin public <版>`）→
zip と update.json の 2 つを、タグ＝版（例 v1.0.1）の**最新**のリリースに添付する（`gh release create v1.0.1 <zip> <update.json> --latest
--title v1.0.1 --notes-file <本文>`）。update.json を添付し忘れると、古い版は新しい版を知らせられない。最初のリリース（v1.0.0・2026-11-15 に準備）は
GitHub にリポジトリ（`Oz-Co-two/AutoNotePlotter`・公開）を作り、remote `github` を足してから。X の告知の画像と文は版ごとに作業の場所の
`out/announce/<版>/`（git の管理外・作り直し用の HTML と render.ps1 も）。

★版をまたぐ約束（変えると、もう配った版から更新できなくなる）: update.json の場所（`https://github.com/<REPO>/releases/latest/download/update.json`）
と形（format 1: name・format・version・tag・zip{name, sha256, size}・notes[{version, ja[]}]・**urgent・ng**＝下の「リリースした後の部品とアプリの版の扱い」。
format 1 のまま足した項目で、v1.0.0 から読む。無い・形が違う所は黙って捨てる＝これからも項目は「足す」だけにし、今の項目の意味を変えない）・zip の場所（`releases/download/<tag>/<zip>`）・
版の形 `v〇.〇.〇`・zip の名前 `AutoNotePlotter-<版>-win-x64.zip` と中の形（最上位 `AutoNotePlotter/`・build-info.json の version と
automap/version.py の VERSION が同じ）・展開する場所 `_update\new\AutoNotePlotter\`・差し替え役の引数（`--apply-update --target --pid`）・
`app/update.py` の REPO（リポジトリの名前＝`Oz-Co-two/AutoNotePlotter`・2026-11-03 に決めた・配った後は変えない）。

確かめ: `tests/test_update.py`（手元の HTTP サーバー・照合の失敗・外へ出る名前・404・新しくない版・やめる・差し替え役の exe を翻訳して
待つ・置き換える・起動し直す・場所が違えば断る・途中で失敗したら戻す）。画面は `#uptest`（=new・=win・=run・=latest・=dev・=done・=error・=busy・
=manual）→ `#uptestOut`。通しの確かめは、2 つの版を作り（2 つ目は `--version`）、古い版の `runtime\python.exe app\server.py --port 8769
--no-browser` を `AUTOMAP_UPDATE_URL=http://127.0.0.1:<番号>/releases/`（手元の配布元＝GitHub と同じ並び・127.0.0.1 だけ）・
`AUTOMAP_UPDATE_NO_LAUNCH=1`（起動し直さない）・`AUTOMAP_CONFIG`・`LOCALAPPDATA` を写しの場所にして動かす（2026-11-03: ダウンロード・照合・展開 6 秒
（180 MB）・差し替え 1 秒・起動し直した版で「更新しました」と _update の片付けまで通った）。

## リリースした後の部品とアプリの版の扱い（2026-11-03 利用者と決めた・最初のリリース v1.0.0 から）

- **動作を確かめた組＝おすすめ**: アプリの版ごとに `tools/sep_install.py` の一覧（FILES）に固定した音を分ける部品の組。全部の組み合わせは試さない。
- **最低の版を持つ 2 段**（`sep_install.MIN_VERSIONS`）: 入っている部品の版が一覧と違っても、最低の版以上で NG でなければ止めない
  （準備の窓の 2. に「おすすめの状態ではありません」・変わる部品と差分のダウンロード量・「更新する」「あとで」、上の列の「準備と設定」に小さな印）。
  最低の版より古い・NG・入っていない・壊れている時だけ止める（揃うまで新しい曲を取り込めない）。Python の版・学習済みモデルの版・パックの作り
  （PACK_FORMAT）の違いは今までどおり必須。最低の版は文字で書く（LIBS・TORCH を上げても上がらない）＝**版を上げる時、前の版のままでも動くと
  確かめた部品だけ最低の版を据え置く**（据え置けば、前のアプリで入れた人は数 GB を取り直さずに使い続けられ、更新は「おすすめ」になる）。
  更新は違う部品だけ取り直す（上げるのも下げるのも同じ道・パック専用の Python は作り直さない）。
- **急ぎの印と使ってはいけない版（NG）**: `automap/version.py` の `URGENT`・`NG` → update.json の `urgent`・`ng`。どの版のアプリも確かめのたびに読み、
  NG は設定の `update_ng` に控える（ネットにつながらない起動でも効く）。
  - `urgent`: `{版: 理由}`。今の版からその版を越えて更新する人には強い知らせ（起動のたび・「この版は飛ばす」を出さない）。
  - `ng.app`: アプリの版の並び。その版のアプリは起動のたびに強い知らせで更新をすすめる（直した版がまだ無ければ配布元のページへ）。
  - `ng.parts`: `{部品の名前: [版の決まり…]}`（`'2.11.0'`＝その版の全部の種類・`'2.11.0+cu126'`＝その種類だけ・`'<2.11.0'` 等 `==・!=・<・<=・>・>=`）。
    入っていれば止めて更新させる。確かめた組そのもの（そのアプリの版の一覧）に当たる時は部品の入れ直しでは直らないので「アプリの更新が必要です」
    （インストールも断る）＝**直した版のアプリと一緒に出す**。
  - `ng.why`: 利用者に見せる理由（日本語・一言）。
  - `NG`・`URGENT` に足した物は消さない（読まれるのは最新のリリースの update.json だけ＝新しいリリースにも前の NG を書き続ける）。

### リリースした後に問題が分かった時

1. どれが悪いかを決める: アプリの版（`NG['app']`）か、音を分ける部品の版（`NG['parts']`）か。`NG['why']` に一言。急いで上げてほしい直した版が
   あれば `URGENT` に `{直した版: 理由}`。
2. **部品の版だけが悪く、確かめた組には入っていない**（新しい版を入れた人がいる等）・**アプリの版が悪いが直した版がもうある**: リリースを作り直さず、
   最新のリリースの update.json を差し替えるだけでよい:
   ```
   gh release download <最新のタグ> -p update.json -D <作業>
   <作業>\venv-build\Scripts\python.exe tools\dist\build_embed.py --refresh-manifest <作業>\update.json
   gh release upload <最新のタグ> <作業>\update.json --clobber          # GitHub への公開は利用者が決める
   ```
   （`--refresh-manifest` は urgent・ng だけを今の `automap/version.py` の値に書き換える。zip・版・変更点はそのまま・アプリと同じ確かめに通す）
3. **確かめた組そのものが悪い**（今の版の一覧の部品が NG）: 直したアプリの版を出す。`tools/sep_install.py` の LIBS（と requirements-sep.txt）・
   TORCH を直した版にして `lock --write`、必要なら `MIN_VERSIONS` を下げる（下げた版を最低の版に＝確かめた組は最低の版を満たす約束・テストが見る）。
   VERSION を上げて CHANGES・NG・URGENT を書き、ふだんどおり `--zip` で作って最新のリリースに。`build_embed.py` は、出す版が `NG['app']` に入っている・
   出す版の部品の一覧に NG の版がある時は止まる。直した版を出すまでの間は、2. の差し替えで先に NG だけ知らせてよい（その版の人は「アプリの更新が
   必要です」→ 直した版がまだ無ければ配布元のページへ）。
4. 確かめ: `tools/sep_install.py check --dir <パック> --ng <NG の JSON>`（部品の段と変わる部品）・画面は `#sutest=rec|must|appng|planng`・
   `#uptest=urgent|urgent-win|selfng|selfng-win|selfngonly|offline`。

## BeatLeader の★が変わった時（2026-11-07 利用者と決めた）

nlm-rating・型のデータベース・★から決めた数（NJS の式・★の帯の境目）は同じ物差しでそろえて、**アプリの版と一緒に上げる**。どれも配布物の中にあり（`parts\`・`data\`・`automap\`）、
アプリの更新で丸ごと差し替わる＝別の更新の口は作らない。物差しがそろっていないと `build_embed.py`（と `checkset.py`）が同梱の段で止まる（`automap/rating_scale.problems`）。

1. nlm-rating を本家に合わせた版にする（別のリポジトリ・版の上 2 つが本家の PP の版）。
2. `python -I tools/library_build/update_rating.py prepare --exe <新しい nlm-rating.exe>`（一覧の取り直し・★の測り直し・データベースを別の名前で作る・比べの表）。
3. 比べの表を見て★の帯の境目を決める → アプリを閉じて `update_rating.py apply [--bands proposed]`。手順の詳しい決まりは docs/ライブラリ仕様.md 6.11。
4. テスト → コミット → `automap/version.py` の VERSION を上げて CHANGES に一言（例「BeatLeader の PPv4.2 に合わせて★を測り直しました」）→ `checkset.py release` → いつものリリース。

使っている人の作業ファイルの★の帯は読む時に今の境目へ読み替わる（`rating_scale.migrate_work`）。今ある譜面は変わらず、★は測り直され、次の作り直しは前の譜面に寄せたまま新しい型の束で作る。

## 脆弱性の確かめ（リリースのたびに・2026-11-03）

配る前に、入れる物に既知の脆弱性が無いかを確かめる（2026-11-03 に初めて行い、Python 3.14.7 → 3.14.10・音を分けるパックの filelock 3.32.3 → 4.2.7・
setuptools 78.1.0 → 84.2.1 に上げた）。

1. **Python**: https://www.python.org/downloads/windows/ で最新の 3.14.x を見る。新しければ、そのリリースのページの
   「Windows embeddable package (64-bit)」の SHA-256 を `build_embed.py` の `PY_SHA256` に足し、`PY_VERSION` を上げる（ダウンロードして同じか確かめる。
   指紋の無い版では作れない＝試しだけ `--unpinned`）。「expedited security release」と書かれた版は必ず上げる。
2. **部品**: pip-audit（作業用の環境に入れる・`pip install pip-audit`）で 3 つの一覧を照らす。一覧の日本語のコメントは外してから渡す:
   ```
   sed 's/#.*//' requirements.txt | grep -v "^--\|^ *$" > a.txt;  PYTHONUTF8=1 pip-audit -r a.txt --no-deps --disable-pip
   （tools/dist/requirements-dist.txt・requirements-sep.txt も同じ。requirements-sep.txt の torch は「+cu128」を外して torch==<版> で照らす）
   ```
3. 見つかったら、直った版に上げる。音を分けるパックの部品は `tools/sep_install.py` の `LIBS`（と requirements-sep.txt）の版を直して
   `python tools/sep_install.py lock --write` で一覧を作り直し、CPU 版を実際にインストールして試しに分ける（`verify`）まで確かめる。
   torch の版を上げる時は、GPU 版（cu128・cu126）の置き場に同じ版があるか・インストール後の大きさ（`SIZES`）も測り直す。
   前の版を入れたままの人に必ず上げさせたい（脆弱性が重い）時は、前の版を `NG['parts']` に足すか `MIN_VERSIONS` を直した版に上げる
   （どちらも「必須の更新」になる。NG は出した後の update.json の差し替えでも足せる・最低の版はアプリの新しい版でだけ変わる）。
4. 2026-11-03 に残した物: torch 2.11.0 の PYSEC-2025-194（CVE-2025-3000・`torch.jit.script` のメモリの壊れ・この PC の中からの攻撃）。
   音を分ける処理は `torch.jit.script` を使わず、重みは safetensors で読むので影響は小さい＝次に torch を上げる時（2.13 以降）に直す。
