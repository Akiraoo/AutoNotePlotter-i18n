# 写した元（NLM の曲の解析）

このフォルダの `__init__.py`・`service.py`・`structure.py`・`tempo.py` は、NLM（Non-Linear Mapper Oz-Co2版・https://github.com/Oz-Co-two/nlm-oz-co2 ）の
`song_analysis/` を**手を加えずに**写した物（docs/アプリ仕様.md 5 節）。こちらの都合の変更は外側の包み `automap/analyze_song.py` に置く。

- 写した元の NLM のコミット: `94dcf8eac194381296580ee651f2bb58ee529b07`（`song_analysis/` を最後に変えたコミット `94dcf8eac194381296580ee651f2bb58ee529b07`・2026-11-11T11:20:10+09:00）
- 写した日: 2026-11-11
- ライセンス: GPLv3（NLM 全体が GPLv3。原作者 helba さん・Oz-Co2。NLM の LICENSE・THIRD_PARTY_NOTICES.txt）。
  中身に他所から写したコードの記載は無い（論文の方法の名前だけ: McFee & Ellis (2014) のラプラシアン分割 等）。
- 依存: librosa 1.0.0・numpy・scipy・scikit-learn 1.9.1・soundfile（m4a 等は ffmpeg）。NLM と同じ版にそろえる
  （NLM は版を上げる時に採点＝テンポ 63 曲・構成 39 曲で比べている。版が違うと答えが変わり得る）。
- 写し直し・比べ: `tools/sync_nlm_analysis.py diff|update|check`。

| ファイル | SHA-256（写した時） |
|---|---|
| `__init__.py` | `54399f17847fd8c48288faa8a5521d91b921c2a6af21747cd790747cec4860b1` |
| `service.py` | `32ba2898c490d32c75f7248f2d67cb7268406916a36230bc176a6acc6cca3cac` |
| `structure.py` | `950c6102177bc03fb3413b8b29c948004240a8644690e8bfbcf491c9ef769242` |
| `tempo.py` | `a7a10ece7609de262a021755e218379a7fd1ca4a4b60ec8867eeb7b9aee21985` |
