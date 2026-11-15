"""作り直しが書き出すフォルダ名・サブタイトルに印を付けない（2026-11-09）。

前はアプリの作り直しが書き出すフォルダ名に -i を足し（書き出した後に作り直すと、次の書き出しが別のフォルダになり Beat Saber に
同じ曲が 2 つ出た）、取り込みの最初の作り直し（--style）が -5 とサブタイトル「試作5」を入れていた（Beat Saber に「試作5」で出た）。
"""
from automap import __main__ as cli


def _proj(folder='papillon', sub=''):
    return {'graph': {'out': {'folderName': folder}},
            'infoGraph': {'outs': {'o1': {'folderName': folder}},
                          'nodes': {'m': {'t': 'meta', 'data': {'sub': sub}}}},
            'info': {'_songSubName': sub}}


def test_app_rebuild_keeps_the_export_folder():
    p = _proj('papillon')
    cli._clear_old_subtitle(p)
    assert p['graph']['out']['folderName'] == 'papillon'
    assert p['infoGraph']['outs']['o1']['folderName'] == 'papillon'


def test_old_default_subtitles_are_cleared_but_the_users_are_kept():
    for old in ('意思入れ', '試作5', '試作4'):
        p = _proj(sub=old)
        cli._clear_old_subtitle(p)
        assert p['info']['_songSubName'] == ''
        assert p['infoGraph']['nodes']['m']['data']['sub'] == ''
    p = _proj(sub='Short Ver.')
    cli._clear_old_subtitle(p)
    assert p['info']['_songSubName'] == 'Short Ver.'
    assert p['infoGraph']['nodes']['m']['data']['sub'] == 'Short Ver.'
