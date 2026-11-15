"""受け取った名前・場所の確かめ（2026-11-11・セキュリティのスキャン CLAUDE-SECURITY-20261111-045144 の F3〜F6・F11）。

受け取った名前（?file=・/static/・/audio/・指示の元・★の path）は、ファイルに触る（resolve を含む）前にこれで確かめる。
Windows の pathlib は \\\\host\\share（UNC）・C:\\…（ドライブ名）を足すと前の場所を捨て、resolve がその場所を開きに行く
＝攻撃者のサーバーへ利用者の NTLM の認証を送る。確かめてから場所にすれば、範囲の外の名前はファイルに触らずに断れる。
標準の部品だけ（server.py・workio.py・rating.py が読む）。
"""


def plain(name):
    """1 つのファイル・フォルダの名前だけか（区切り・ドライブ名・UNC・..・. を含まない）"""
    s = str(name if name is not None else '')
    return s not in ('', '.', '..') and not any(c in s for c in '/\\:\0')


def rel_parts(rel):
    """'a/b/c'（/ で区切った場所）→ ['a', 'b', 'c']。どれかが plain でなければ None"""
    parts = str(rel if rel is not None else '').split('/')
    return parts if all(plain(x) for x in parts) else None
