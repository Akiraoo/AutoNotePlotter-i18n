# BL のリプレイアプリの出典（写した物の記録）

このフォルダは BeatLeader の Web のリプレイの見え方（BeatSaber-Web-Replays・https://github.com/BeatLeader/BeatSaber-Web-Replays ・MIT）の
組み立て済みの物の写し。アプリの「リプレイ」（app/replays.py・static/js/replays.js・docs/アプリ仕様.md 26 節）が、遊んだリプレイと遊んだ時の
譜面の zip をアプリのサーバーから渡して開く（`index.html?link=<.bsor の場所>&mapLink=<譜面の zip の場所>`）。こちらで書いたのはこのファイルだけ。

## 写し方

- `tools/blreplay_fetch.py` が写す（標準ライブラリだけ・npm を使わない）。index.html・`build/`・`vendor/aframe-master.min.js` は BL の公開ページ
  https://replay.beatleader.com/ から（作るには npm が要る＝この PC では使わない）、素材（`assets/`）は GitHub の決めた版のコミットの一覧の物を
  公開ページから、無ければ GitHub の同じ版から。`vendor/` の小さな部品と LICENSE は GitHub の同じ版から。
- Font Awesome Free 6.4.0（ページは CDN から読む）も `fontawesome/` に写した＝開く時にネットへ出るのは BeatLeader の API（プレイヤーの公開
  プロフィール）だけ。
- 写さない物: `assets/test.zip`・`assets/raw/`（元の .blend）・`assets/webfonts/`（Font Awesome 5・使わない）・`vendor/aframe-master.js`（.min を使う）と .map。
- `MANIFEST.json` に写した日・版・ファイルごとの SHA-256。`tools/blreplay_fetch.py --check` で写した物が変わっていないかを確かめる。
  git は行の終わりを変えない（`.gitattributes` の `app/static/blreplay/** -text`）。

## 写した元

- GitHub のコミット `cb3e9b81776d41cfdc25fa410ce4fdd9811662ed`（2026-11-09「Fixed song resume offset on Safari」）・公開ページの本体
  `build/build.1794234981.js`（2026-11-12 に写した）。

## こちらで変えた所（PATCHES・写し直す時に道具が当て直す。当たらなければ止まる）

1. `index.html` の `"/assets/img/firefoxautoplay.jpg"` → `"assets/img/firefoxautoplay.jpg"`（アプリでは /static/blreplay/ の下に置く）
2. `build/build.*.js` の `"/assets/sounds/silence.mp3"` → `"assets/sounds/silence.mp3"`（同じ）
3. `index.html` の Font Awesome の CSS を CDN から写した物（`fontawesome/css/all.css`）に

## 動き方で知っておくこと

- `mapLink` があると、zip-loader は BeatSaver に問い合わせずに zip を読む。遊んだ譜面の hash と zip の中身が違っても止まらない
  （リプレイの記録から組み立てた譜面も開ける）。
- `link` の .bsor はリプレイアプリが XHR で読む（同じアプリのサーバー・使い捨ての鍵の場所 /blr/<鍵>/…）。プレイヤーの名前とアイコンは
  リプレイの頭のプレイヤーの番号で BeatLeader の API から読む（ネットが無ければ出ないだけ）。
- 設定（視点・音量など）はリプレイアプリがブラウザの覚え（このアプリのサーバーの番号ごと）に持つ。

## 写し直す手順

1. `.venv/Scripts/python.exe -I tools/blreplay_fetch.py`（前の物は丸ごと置き換える・このファイルは残す）
2. 写した日・版をこのファイルに書き直す（`MANIFEST.json` の commit・fetched）。
3. 見えない Edge で開けるかを確かめる（docs/アプリ仕様.md 26 節の確かめ）。
