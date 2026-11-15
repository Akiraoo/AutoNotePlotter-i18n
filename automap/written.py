"""結果のファイルを「こちらで書いた」印（out/.state/<ファイル名>.json＝書いた時のファイルの指紋）の読み書き。

前は automap/__main__.py の中にあった（名前もそのまま＝`cli._save` 等で呼ぶ所はそのまま使える・__main__ がここから読む）。
アプリのサーバー（app/server.py・app/versions.py ほか）は曲を開く・NLM で直したかを見るたびにこれだけを使うので、重い部品（scipy 等を読む
__main__）を読まずに済むよう分けた（2026-11-09・起動を速く・app/server.py の `cli`＝automap.lazy.Module）。標準の部品と nlmf だけを読むこと。
"""
import hashlib
import json
from pathlib import Path

from . import nlmf


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _state_path(out):
    return out.parent / '.state' / (out.name + '.json')


def _edited_since_written(out):
    """結果のファイルが、こちらで書いた後に保存し直されたか（記録が無い＝分からないので直された物として扱う）"""
    if not out.exists():
        return False
    try:
        rec = json.loads(_state_path(out).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return True
    return rec.get('sha256') != _sha(out)


def _save(proj, out):
    """保存し、こちらで書いた時の指紋を残す（次に作り直す時、NLM で直されたかを見分ける）"""
    nlmf.save(proj, out)
    sp = _state_path(out)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({'sha256': _sha(out), 'savedAt': proj.get('savedAt')}), encoding='utf-8')
