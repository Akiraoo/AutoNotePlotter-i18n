"""使う時に読むモジュール（アプリの起動を速く・2026-11-09）。

アプリのサーバー（app/server.py・app/versions.py）は、作る処理の部品（automap.__main__ → echo → rhythm → audio → scipy.signal）を頭で
読んでいて、それだけで起動が 0.9 秒（PC を起動した直後は DLL・.pyd の読み込みと検査で 10〜30 秒）かかった。曲を開くのは控え
（app/songcache.py）から・NLM で直したかを見るのは automap/written.py だけで済むので、重い部品は本当に使う所（控えの無い曲を開く・
作り直しの前の比べ…）まで読まない。

    cli = lazy.Module('automap.__main__', light='automap.written')

- 属性を読んだ時に importlib.import_module で本物を読み（2 回目からは sys.modules から）、本物の属性を返す。差し替え（テストの
  monkeypatch.setattr）も本物のモジュールに効く（読むたびに本物から取るので、差し替えた物が見える）。
- light＝軽いモジュール: その中で作った関数・型の名前は、本物を読まずに軽いモジュールから返す。本物が同じ物を軽いモジュールから
  読んでいる時だけ使う（automap.__main__ の _sha・_state_path・_edited_since_written・_save は automap.written の物）。
  本物の側でその名前を差し替えても、ここからは軽いモジュールの物が見える（その名前を差し替えるなら軽いモジュールの方を）。
"""
import importlib


class Module:
    __slots__ = ('_lazy_name', '_lazy_light')

    def __init__(self, name, light=None):
        object.__setattr__(self, '_lazy_name', name)
        object.__setattr__(self, '_lazy_light', light)

    def _real(self):
        return importlib.import_module(self._lazy_name)

    def __getattr__(self, k):
        if k.startswith('__'):
            return getattr(self._real(), k)
        if self._lazy_light:
            v = vars(importlib.import_module(self._lazy_light)).get(k)
            if getattr(v, '__module__', None) == self._lazy_light:   # 軽いモジュールで作った関数・型だけ（読み込んだ部品の名前は本物から）
                return v
        return getattr(self._real(), k)

    def __setattr__(self, k, v):
        setattr(self._real(), k, v)

    def __delattr__(self, k):
        delattr(self._real(), k)

    def __dir__(self):
        return dir(self._real())

    def __repr__(self):
        return f'<使う時に読むモジュール {self._lazy_name!r}>'
