"""同じ音楽の区間（自動の同じ振り・automap/repeat.py）の組と各回の範囲を、帯「作った譜面」に重ねて出すための受け口（2026-11-11 利用者
「繰り返しの箇所が具体的にどこなのか譜面のラインで見たい。その上で難易度展開でその繰り返しをどう展開しているか確認したい」）。
server.py の connect() が routes(ctx) を呼んでつなぐ。画面は app/static/js/repeats.js。

- GET /api/repeats?file=<結果のファイル>[&diff=<難易度>][&cand=<番号> | &ver=<版>]: 作り直しの報告の
  「- 同じ音楽の区間（自動の同じ振り・…）: 自動1 3 小節: 拍 3（手本）→拍 19（左右反転） ／ …」の行を読んで返す（読むのは
  automap.repeat.parse_groups＝作る側が前の版の組を引き継ぐ時に読む parse_line と同じ行）。
  どの報告か: 基準＝<結果>.report.md（結果のファイルがまだ無い曲は土台の報告）・diff が基準と違う＝派生の報告
  <結果>.<難易度>.report.md（automap/diffs.report_path・今の結果のファイルの物）・別の案・履歴の版＝決めの場所（/api/kime）と同じ
  （app/check.py の chain_of の先頭。版・案は基準の難易度だけ＝cand・ver があれば diff は見ない）。
  答え: {file（読んだ報告のファイルの名前）, diff（その報告の難易度の名前）, derived（派生の報告か）, state, groups}。
  state＝ok（行があった・groups が空なら「見つからなかった」）・none（行が無い＝--no-auto-repeat・行を書く前の版）・no_report（報告が無い）。
  groups の 1 つ＝{name（自動1…）, bars（小節の数）, occ: [{b0, b1（拍）, kind＝model 手本・same 同じ・mirror 左右反転}]}（parse_groups の形のまま）。
- 区間だけ作り直した報告（別の案・この区間だけ作り直す）にも曲の全部の組が書いてある（compose は組を曲の全部で探して全部へ写す）＝
  決めの場所のように前の版の報告をさかのぼらない。
"""
from automap import diffs, lazy
import check   # noqa: E402  （app/ の中・別の案・履歴の版の報告の選び方を決めの場所と同じに）

# automap.repeat は頭で rhythm（numpy・soundfile）を読む＝使う時に読む（アプリの起動を速く・2026-11-09・automap/lazy.py）
RP = lazy.Module('automap.repeat')


def report_of(ctx, q):
    """問い合わせ（file・diff・cand・ver）→ (報告の場所, その報告の難易度の名前, 派生の報告か)"""
    if q.get('cand') or q.get('ver'):
        chain, shown = check.chain_of(ctx, q)
        return chain[0], ctx.file_diff(shown), False
    src = ctx.base_of(ctx.out_file(q['file']))
    base = ctx.file_diff(src)
    d = diffs.name_of(q['diff']) if q.get('diff') else base   # 知らない名前は ValueError（400）
    return diffs.report_path(src, None if d == base else d), d, d != base


def repeat_marks(ctx, q):
    path, d, derived = report_of(ctx, q)
    head = {'file': path.name, 'diff': d, 'derived': derived}
    try:
        md = path.read_text(encoding='utf-8')
    except OSError:
        return dict(head, state='no_report', groups=[])
    groups = RP.parse_groups(md)
    if groups is None:
        return dict(head, state='none', groups=[])
    return dict(head, state='ok', groups=groups)


def routes(ctx):
    """({GET のパス: fn(問い合わせ)}, {POST のパス: fn(本文)})"""
    return {'/api/repeats': lambda q: repeat_marks(ctx, q)}, {}
