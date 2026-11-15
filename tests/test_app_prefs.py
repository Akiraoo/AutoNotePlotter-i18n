"""画面の覚え（3D の窓の設定・切る音…）をアプリの設定に持つ（app/server.save_prefs・/api/prefs・2026-11-08）"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app'))
import server  # noqa: E402


def test_save_prefs_merges_into_ui_prefs_and_keeps_other_settings(tmp_path, monkeypatch):
    cfg = tmp_path / 'config.json'
    cfg.write_text(json.dumps({'nlm_exe': 'x.exe', 'ui_prefs': {'automap-cam': '標準'}}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(server, 'CONFIG', cfg)
    server.save_prefs({'automap-sndon': True, 'automap-pvd': 1.6, 'other': 1, 'automap-big': 'x' * 30000})
    got = json.loads(cfg.read_text(encoding='utf-8'))
    assert got['nlm_exe'] == 'x.exe'
    assert got['ui_prefs'] == {'automap-cam': '標準', 'automap-sndon': True, 'automap-pvd': 1.6}   # automap- の物・小さな値だけ
    with pytest.raises(ValueError):
        server.save_prefs(['automap-sndon'])
