# 3D の見え方の出典（写した物の記録）

このフォルダの `preview-v4/`・`js/` は、NLM（Non-Linear Mapper Oz-Co2 版・https://github.com/Oz-Co-two/nlm-oz-co2 ）から写した物。
こちらで書いたのは `preview3d.js`（包み）・`nlmf-map.js`（.nlmf → 譜面）・`test.html`（確かめ用）・このファイルだけ。

## 写した元

- NLM のコミット `70717ed92d494b27fe103d4458397d7025e9ff42`（2026-10-22）から、2026-10-25 に写した。
- `preview-v4/preview-v4.js` — NLM の 3D の見え方（PREVIEW の窓）。**ArcViewer（https://github.com/AllPoland/ArcViewer/ ・GPL-3.0）の
  移植**（NLM の CLAUDE.md）。
- `preview-v4/env/*.json`（13 のステージ）— ArcViewer の実行中のシーンから、NLM の原作者 helba さんの Unity スクリプト
  `NLMEnvExport.cs` で抜き出したメッシュと階層（ArcViewer 由来＝GPL-3.0）。
- `js/three/chamfer-box.js`・`js/notes/chain-bezier.js`・`js/constants.js` — NLM のコード（GPLv3）。preview-v4 が読み込む。
- `js/vendor/three/three.module.js`（three.js r160・MIT License・© 2010-2023 three.js authors）と、preview-v4 が使う addons
  （postprocessing の EffectComposer・MaskPass・Pass・RenderPass・ShaderPass・UnrealBloomPass、shaders の CopyShader・
  LuminosityHighPassShader、objects の Reflector、utils の BufferGeometryUtils）。NLM の `js/vendor/three/` と同じ物。

ライセンス: GPL-3.0（ArcViewer の移植を含むため。NLM も全体を GPLv3 としている）。three.js は MIT。
このアプリも GPLv3 にすることを利用者と決めた（docs/アプリ仕様.md）。

## こちらで変えた所（写し直す時に当て直す）

1. `preview-v4/preview-v4.js` の `loadEnvironment` の1行: ステージの JSON を NLM はページからの相対
   （`fetch('preview-v4/env/'+name+'.json')`）で読む。アプリではページの場所が違うので、`new URL('env/'+name+'.json', import.meta.url)`
   （このファイルからの相対）にした。行の末に `[nlm-automap]` の印。

ほかは手を入れていない。NLM のエディタの状態に頼る所（譜面・時刻・NJS・色・ステージ）は、preview-v4 がもともと
`setData`・`frame` 等で外から受け取る作りなので、`preview3d.js` で包むだけで済んだ。

## 写し直す手順

1. NLM の同じ場所のファイルを、このフォルダの同じ場所へ写す（three.js と addons は NLM が版を上げた時だけ）。
2. 上の「変えた所」を当て直す（`[nlm-automap]` の印の行）。
3. このファイルのコミットと日付を書き換える。
4. `test.html` で NLM の PREVIEW と同じ時刻の絵を見比べる（docs/アプリ仕様.md の 6 節）。

差分を見る: NLM のリポジトリと比べる（例 `git diff --no-index <NLM>/preview-v4/preview-v4.js preview-v4/preview-v4.js` →
`[nlm-automap]` の1行だけが出れば同じ）。

## 足した物（2026-10-25・アプリの利用者の要望）

- `preview-v4/preview-v4.js` に `setCameraView({fov, y, back, lookY, lookZ})` を1つ足した（視点を引く。ゲームと同じ視点だと小さな窓で
  ノーツとレーンが窓いっぱいになり、拡大したように見えて見にくかった）。写し直す時は、この関数をもう一度足す。
