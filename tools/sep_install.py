# SPDX-License-Identifier: MIT
# このファイルだけ MIT License（リポジトリのほかは GPLv3）。音を分ける部品（PyTorch の NVIDIA・Intel の部品）と組み合わせて動かすため
# （2026-11-03 利用者・THIRD_PARTY_NOTICES.md の 5 節）。このファイルは本体（GPLv3）のコードを読み込まない＝本体のコードを足さないこと。
#
# Copyright (c) 2026 Auto Note Plotter contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
# ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH
# THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""音を分ける部品（パック＝パック専用の Python＋PyTorch＋Demucs＋学習済みの重み htdemucs_ft）を入れる道具（docs/アプリ仕様.md 21 節）。

PyTorch と Demucs はこちらでは配らず、利用者の PC が公式の置き場（download.pytorch.org・PyPI・Hugging Face）から取る。取る物は
この道具の中の一覧（FILES・WEIGHTS＝版・大きさ・指紋 sha256 を固定）だけで、取った後に指紋を確かめてから入れる。
標準ライブラリだけで動く（本体のコードを読み込まない）。pip は別のプロセスで、取ったファイルだけから入れる（--no-index＝pip は
ネットに行かない＝証明書の設定に頼らない）。自分で取る所は ssl.create_default_context()（Windows の証明書の置き場を読む＝
ウイルス対策ソフト等が HTTPS を中継していても、その証明書が Windows に入っていれば通る）。検証は切らない。

パックの置き場 <dir>:
  python/        パック専用の Python（配布物の runtime/ から site-packages を除いて写し、._pth をパック用に）＋ Lib/site-packages/
  hf/            Hugging Face の置き場（HF_HOME）。重みは hf/hub/models--adefossez--HTDemucs-ft/snapshots/<版>/ に置く
  downloads/     取りかけの物（.part）・取った wheel（入れ終わったら消す）
  state.json     段ごとの進み（止めても続きから）
  installed.json 入れ終わった印（variant・版・入れた日・確かめの結果）
  install.log    pip と確かめの記録

使い方（関数）: detect_gpu()・plan(dir, variant)・check(dir[, ng])・set_ng(variant, ng)・install(dir, variant, runtime, progress, cancel)・
  verify(dir)・python_exe(dir)・run_env(dir[, os.environ])。分ける時は python_exe(dir) で tools/separate.py を、環境変数に run_env(dir) を足して動かす。
  check は起動のたびに（40ms ほど・torch を読まない）。別の種類へ入れ替える途中で止めた時は ok のまま resume に途中の種類が出る。
  版の 2 段（2026-11-03 利用者）: 一覧（FILES）＝このアプリの版で動作を確かめた組＝おすすめ。入っている版が違っても、MIN_VERSIONS 以上で
  NG（ng＝使ってはいけない版・配布元の update.json から app/update.py が設定に控えた物）でなければ止めない（stage 'recommended'）。
  最低の版より古い・NG・入っていない・壊れている・Python／重み／パックの作りが違う時だけ止める（'required'・ok=False）。確かめた組
  そのものに NG が入っていれば、部品を入れ直しても直らない（app_update＝アプリの更新が要る・set_ng）。install は違う部品だけ取り直す
  （上げるのも下げるのも同じ道）。
使い方（コマンド）:
  python tools/sep_install.py plan|check|install|verify|gpu --dir <dir> [--variant cu128|cu126|cpu] [--runtime <埋め込み用の Python>]
         [--offline] [--json] [--ng <NG の JSON か、そのファイル>]
  install --json は1行に1つの JSON（progress と同じ形）、最後に {"stage": "done", …} か {"error": "…"}（終わりの値 1）。
  開発用: python tools/sep_install.py lock [--write]（公式の置き場から FILES・WEIGHTS の一覧を作り直す＝版を上げる時。
         入れた後の大きさ SIZES は実際に入れて測り直す）
"""
import argparse
import concurrent.futures
import csv
import ctypes
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------- 版（requirements-sep.txt に合わせて固定・2026-11-03）

PACK_FORMAT = 1
PY_VER = (3, 14)
TORCH = '2.11.0'
DEMUCS = '4.1.0'
MODEL = 'htdemucs_ft'
HF_REPO = 'adefossez/HTDemucs-ft'
HF_REV = 'd74ac89c3a1e874fc78f152555cf4d8533f06cd4'
LOCK_ID = f'torch{TORCH}-demucs{DEMUCS}-{MODEL}-{HF_REV[:7]}-py{PY_VER[0]}{PY_VER[1]}'
UA = 'AutoNotePlotter-sep-install/1'

VARIANTS = {
    'cu128': {'label': 'GPU 版（NVIDIA・CUDA 12.8）', 'index': 'https://download.pytorch.org/whl/cu128',
              'cuda': (12, 8), 'cc': (7, 5)},    # この版の torch は sm_75〜sm_120（GTX 16・RTX 20 以降）だけ（.venv-sep で確かめた）
    'cu126': {'label': 'GPU 版（NVIDIA・CUDA 12.6・古い GPU・古いドライバー向け）', 'index': 'https://download.pytorch.org/whl/cu126',
              'cuda': (12, 6), 'cc': (5, 0)},
    'cpu': {'label': 'CPU 版（GPU を使わない・遅い）', 'index': 'https://download.pytorch.org/whl/cpu'},
}
# PyPI から取る部品（torch・pip のほか）。requirements-sep.txt と同じ版（torchaudio は要らない＝demucs 4.1.0 は分けるだけなら読まない）
LIBS = [
    ('demucs', DEMUCS), ('numpy', '2.5.4'), ('soundfile', '0.14.0'),
    ('filelock', '4.2.7'), ('fsspec', '2026.7.0'), ('Jinja2', '3.1.6'), ('MarkupSafe', '3.0.3'), ('networkx', '3.6.1'),
    ('sympy', '1.14.0'), ('mpmath', '1.3.0'), ('setuptools', '84.2.1'), ('typing_extensions', '4.16.0'),
    ('einops', '0.8.2'), ('julius', '0.2.8'), ('lameenc', '1.9.0'), ('safetensors', '0.8.0'), ('sphn', '0.2.1'),
    ('huggingface_hub', '2.2.0'), ('hf-xet', '1.7.0'), ('httpx2', '2.15.1'), ('httpcore2', '2.15.1'), ('h11', '0.16.0'),
    ('truststore', '0.10.5'), ('anyio', '4.15.1'), ('idna', '3.20'), ('click', '8.5.0'), ('PyYAML', '6.0.3'),
    ('packaging', '26.3'), ('tqdm', '4.70.1'), ('colorama', '0.4.6'), ('cffi', '2.1.1'), ('pycparser', '3.11'),
]
PIP = ('pip', '26.2.1')   # 入れる時だけ使う（wheel のまま動かす・パックには入れない）

# 部品ごとの最低の版（2026-11-03 利用者と決めた「最低の版を持つ 2 段」・docs/アプリ仕様.md 21 節）。下の一覧（FILES＝このアプリの版で
# 動作を確かめた組＝おすすめ）と入っている版が違っても、ここの版以上で NG（使ってはいけない版・check の ng）でなければ止めない
# ＝「おすすめの更新」。ここより古い・NG・入っていない・壊れている時だけ止める（「必須の更新」）。ここに無い部品は、入っていればどの版でもよい。
# 値は文字で書く（LIBS・TORCH を上げても自動では上がらない＝前のアプリの版で入れた部品をそのまま使い続けてよいかを、版を上げる人が
# 部品ごとに決める。前の版で動くと確かめた物だけ据え置く）。確かめた組はここを満たすこと（tests/test_sep_install.py）。
MIN_VERSIONS = {
    'torch': '2.11.0',            # v0.2.0（最初のリリース）で確かめた版（tools/separate.py・Demucs が使う）
    'demucs': '4.1.0',            # tools/separate.py の demucs.api・重みを Hugging Face の置き場から読む
    'numpy': '2.5.4',
    'soundfile': '0.14.0',
    'huggingface_hub': '2.2.0',   # 重みの置き場（HF_HOME の hub/）の形
    'safetensors': '0.8.0',       # 重みの形
    'filelock': '4.2.7',          # これより前は既知の脆弱性（2026-11-03 に上げた・tools/dist/README.md の「脆弱性の確かめ」）
    'setuptools': '84.2.1',       # 同じ
}

# FILES: key（'torch-cu128'・'lib-numpy'・'pip'）→ {'name', 'version', 'file', 'url', 'size', 'sha256'}・WEIGHTS: [{'file', 'url', 'size', 'sha256'}]
# ---- 取る物の一覧（`sep_install.py lock --write` が作る・手で書き換えない） ----
FILES = {
    'lib-demucs': {'name': 'demucs', 'version': '4.1.0', 'file': 'demucs-4.1.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/68/93/6f338f3f5c53522406dc32cd3b8a59abde20ac80d33604aa9dc8c82450e5/demucs-4.1.0-py3-none-any.whl', 'size': 100567, 'sha256': '4916a804702033ce934a6cdfa7e38dde03f7a7a6e85f41d0120eefe9e2966758'},
    'lib-numpy': {'name': 'numpy', 'version': '2.5.4', 'file': 'numpy-2.5.4-cp314-cp314-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/52/9a/e1e512ebc948d5b9dd33b08736760f0ebbed2848fd4eda1f553088a6dcee/numpy-2.5.4-cp314-cp314-win_amd64.whl', 'size': 12703552, 'sha256': '2ca144f15135b6212a5c47b1e2aeca6e412f102f95a2d5d88d8aec77eb255de3'},
    'lib-soundfile': {'name': 'soundfile', 'version': '0.14.0', 'file': 'soundfile-0.14.0-py2.py3-none-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/ed/97/b39c18ac1df45e755ca22b8b00e872929da5d107998a207a5e4ac831bfda/soundfile-0.14.0-py2.py3-none-win_amd64.whl', 'size': 1021480, 'sha256': '299491d3499460fb1b74bb4bd78b57ffc2d243a5fafa7b6ec1b264875c78453e'},
    'lib-filelock': {'name': 'filelock', 'version': '4.2.7', 'file': 'filelock-4.2.7-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/1d/1a/1fcf0d3886bad15b92459a0e529dd86a1ec4d9ef30e789df48044fd3698c/filelock-4.2.7-py3-none-any.whl', 'size': 164345, 'sha256': 'd08972bbca2b8767ee552aff877b091dd111ffb1d22de7de885766ea7d719d5e'},
    'lib-fsspec': {'name': 'fsspec', 'version': '2026.7.0', 'file': 'fsspec-2026.7.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/fd/3c/6a2bf344106328fd04963664a60b9bb6496fc25df8e962fcdc1367285fb9/fsspec-2026.7.0-py3-none-any.whl', 'size': 206583, 'sha256': 'b57ddbafedfaef7018c1ecab32aa200a9d7ca26b77965f64e48b70061249d279'},
    'lib-jinja2': {'name': 'Jinja2', 'version': '3.1.6', 'file': 'jinja2-3.1.6-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/62/a1/3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/jinja2-3.1.6-py3-none-any.whl', 'size': 134899, 'sha256': '85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67'},
    'lib-markupsafe': {'name': 'MarkupSafe', 'version': '3.0.3', 'file': 'markupsafe-3.0.3-cp314-cp314-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/28/52/182836104b33b444e400b14f797212f720cbc9ed6ba34c800639d154e821/markupsafe-3.0.3-cp314-cp314-win_amd64.whl', 'size': 15341, 'sha256': 'bdc919ead48f234740ad807933cdf545180bfbe9342c2bb451556db2ed958581'},
    'lib-networkx': {'name': 'networkx', 'version': '3.6.1', 'file': 'networkx-3.6.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/9e/c9/b2622292ea83fbb4ec318f5b9ab867d0a28ab43c5717bb85b0a5f6b3b0a4/networkx-3.6.1-py3-none-any.whl', 'size': 2068504, 'sha256': 'd47fbf302e7d9cbbb9e2555a0d267983d2aa476bac30e90dfbe5669bd57f3762'},
    'lib-sympy': {'name': 'sympy', 'version': '1.14.0', 'file': 'sympy-1.14.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/a2/09/77d55d46fd61b4a135c444fc97158ef34a095e5681d0a6c10b75bf356191/sympy-1.14.0-py3-none-any.whl', 'size': 6299353, 'sha256': 'e091cc3e99d2141a0ba2847328f5479b05d94a6635cb96148ccb3f34671bd8f5'},
    'lib-mpmath': {'name': 'mpmath', 'version': '1.3.0', 'file': 'mpmath-1.3.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/43/e3/7d92a15f894aa0c9c4b49b8ee9ac9850d6e63b03c9c32c0367a13ae62209/mpmath-1.3.0-py3-none-any.whl', 'size': 536198, 'sha256': 'a0b2b9fe80bbcd81a6647ff13108738cfb482d481d826cc0e02f5b35e5c88d2c'},
    'lib-setuptools': {'name': 'setuptools', 'version': '84.2.1', 'file': 'setuptools-84.2.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/ef/55/6dc6d6bb953bdfc52519a0059592c52b6e3b8ad51cf8256dffceb55b0610/setuptools-84.2.1-py3-none-any.whl', 'size': 876263, 'sha256': 'ca140b45d5325a9478f880e351484f62fef15f336462e449ca0c03c873d589c2'},
    'lib-typing_extensions': {'name': 'typing_extensions', 'version': '4.16.0', 'file': 'typing_extensions-4.16.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/typing_extensions-4.16.0-py3-none-any.whl', 'size': 45571, 'sha256': '481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8'},
    'lib-einops': {'name': 'einops', 'version': '0.8.2', 'file': 'einops-0.8.2-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/2a/09/f8d8f8f31e4483c10a906437b4ce31bdf3d6d417b73fe33f1a8b59e34228/einops-0.8.2-py3-none-any.whl', 'size': 65638, 'sha256': '54058201ac7087911181bfec4af6091bb59380360f069276601256a76af08193'},
    'lib-julius': {'name': 'julius', 'version': '0.2.8', 'file': 'julius-0.2.8-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/86/43/efdb0bcb07c47826fa55857cec0deb743f74cd83b6ba5ec9e413505a72e6/julius-0.2.8-py3-none-any.whl', 'size': 21819, 'sha256': '6891235cbc355e629d839f87489bff8ca46e57a0e7cc35abb909c7a2aa538c25'},
    'lib-lameenc': {'name': 'lameenc', 'version': '1.9.0', 'file': 'lameenc-1.9.0-cp314-cp314-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/18/f7/753ecd677d0aedfd79cf222a752669d989fcfe053414ce0bb7502aa04bfe/lameenc-1.9.0-cp314-cp314-win_amd64.whl', 'size': 122844, 'sha256': '2a7554b14509d25c42fce08081e5fc3226bca3d0b5d9774246cb79757004f362'},
    'lib-safetensors': {'name': 'safetensors', 'version': '0.8.0', 'file': 'safetensors-0.8.0-cp310-abi3-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/1b/6d/3fba214c1e5e0f69991677ec3bc17023f0421776975e1de0c682dca475e2/safetensors-0.8.0-cp310-abi3-win_amd64.whl', 'size': 355540, 'sha256': '096ec1a98435df7beb08853bb5aa9081a84f23d0adc67ed1a0a10550f608373f'},
    'lib-sphn': {'name': 'sphn', 'version': '0.2.1', 'file': 'sphn-0.2.1-cp314-cp314-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/5d/96/92c5a3c879f8bceb7db33f2177726e28729be52c344bfaa0386879ec29c3/sphn-0.2.1-cp314-cp314-win_amd64.whl', 'size': 1606279, 'sha256': '5d5c715216f36f070115b69de220e918cd7da25f01a02e20a3dc0517d4942101'},
    'lib-huggingface_hub': {'name': 'huggingface_hub', 'version': '2.2.0', 'file': 'huggingface_hub-2.2.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/eb/b0/0f7b430fd100b3a3b037fdbb314878200241082e607b3383c63d91a13a72/huggingface_hub-2.2.0-py3-none-any.whl', 'size': 839884, 'sha256': '1667f145dc56dc210d60966069397df9ecfca9607a5d43db88b308c89dae56b3'},
    'lib-hf_xet': {'name': 'hf-xet', 'version': '1.7.0', 'file': 'hf_xet-1.7.0-cp38-abi3-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/4d/59/b35106dfa71b6eef605dc88bd038fe99c7f86fb132a15b60d0bf2f235b2c/hf_xet-1.7.0-cp38-abi3-win_amd64.whl', 'size': 3822644, 'sha256': '2b7bb5727889b0f2436dbaaad8fc4c3e66b8240d992716989e0c086b4278b1bc'},
    'lib-httpx2': {'name': 'httpx2', 'version': '2.15.1', 'file': 'httpx2-2.15.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/7a/bf/56068f774620330c8330e4b4915fae889a5b2d4b52667b3b7c8f66c4a9ad/httpx2-2.15.1-py3-none-any.whl', 'size': 96411, 'sha256': '75841cd83d16b417f7d6da8f2089ce8120806efdbf96af37d46c5129c49015be'},
    'lib-httpcore2': {'name': 'httpcore2', 'version': '2.15.1', 'file': 'httpcore2-2.15.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/0d/9b/e2b556e26fbc67716ab1dfc18832eb6fe196d88363f7094cb1da3d7c0d3e/httpcore2-2.15.1-py3-none-any.whl', 'size': 85055, 'sha256': '730f603058c260a3288378217b464713350c23e3b8fe8bba753701054032d98a'},
    'lib-h11': {'name': 'h11', 'version': '0.16.0', 'file': 'h11-0.16.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl', 'size': 37515, 'sha256': '63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86'},
    'lib-truststore': {'name': 'truststore', 'version': '0.10.5', 'file': 'truststore-0.10.5-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/51/e9/3a7820be2bb0fe53b6bc9c3be26d3d1158004e4c3ab953aa6840b955b1e9/truststore-0.10.5-py3-none-any.whl', 'size': 19017, 'sha256': '9aaaedaefaf06d8b206278cf8b5012bc897f485a874503501e12d776df78951c'},
    'lib-anyio': {'name': 'anyio', 'version': '4.15.1', 'file': 'anyio-4.15.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/12/b8/4bd346e22b28902df4d651910f5242c28d84e4a5c2435ca5c3f797ed7e2e/anyio-4.15.1-py3-none-any.whl', 'size': 132079, 'sha256': '6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101'},
    'lib-idna': {'name': 'idna', 'version': '3.20', 'file': 'idna-3.20-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/58/a2/bb081bab032533a855d44de1d56f8e8426114ff1ba5d1f07a438a0a654f8/idna-3.20-py3-none-any.whl', 'size': 69583, 'sha256': 'ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c'},
    'lib-click': {'name': 'click', 'version': '8.5.0', 'file': 'click-8.5.0-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/58/50/6c0d534c5f134586a8e1ba4e330569e32f057e33372ae556463212fb4cd3/click-8.5.0-py3-none-any.whl', 'size': 125251, 'sha256': '255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360'},
    'lib-pyyaml': {'name': 'PyYAML', 'version': '6.0.3', 'file': 'pyyaml-6.0.3-cp314-cp314-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/23/20/bb6982b26a40bb43951265ba29d4c246ef0ff59c9fdcdf0ed04e0687de4d/pyyaml-6.0.3-cp314-cp314-win_amd64.whl', 'size': 156429, 'sha256': '4a2e8cebe2ff6ab7d1050ecd59c25d4c8bd7e6f400f5f82b96557ac0abafd0ac'},
    'lib-packaging': {'name': 'packaging', 'version': '26.3', 'file': 'packaging-26.3-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/63/34/ba1c580383c9eada3711951fef0795c80b829a078d72188184bcab9dd527/packaging-26.3-py3-none-any.whl', 'size': 129956, 'sha256': 'd7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c'},
    'lib-tqdm': {'name': 'tqdm', 'version': '4.70.1', 'file': 'tqdm-4.70.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/a7/03/921a3d3c75785aca9ebfbfcabfbc3a1be12e2ab5265deb026d55a5a3f83e/tqdm-4.70.1-py3-none-any.whl', 'size': 80199, 'sha256': 'c293e525e6fef9c20e8728fd4612df02a0aa31bb5fe91ecd93e123b1b7bffa73'},
    'lib-colorama': {'name': 'colorama', 'version': '0.4.6', 'file': 'colorama-0.4.6-py2.py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/d1/d6/3965ed04c63042e047cb6a3e6ed1a63a35087b6a609aa3a15ed8ac56c221/colorama-0.4.6-py2.py3-none-any.whl', 'size': 25335, 'sha256': '4f1d9991f5acc0ca119f9d443620b77f9d6b33703e51011c16baf57afb285fc6'},
    'lib-cffi': {'name': 'cffi', 'version': '2.1.1', 'file': 'cffi-2.1.1-cp314-cp314-win_amd64.whl', 'url': 'https://files.pythonhosted.org/packages/a7/06/1c3e01e3ba14c39f6d10bfbac52753b7e22259e38088e5cfe1d704918690/cffi-2.1.1-cp314-cp314-win_amd64.whl', 'size': 187949, 'sha256': '3222ba5d678f80a030e6afbcc33dc1ae5cb45facabb61cee2c7016b8432fde48'},
    'lib-pycparser': {'name': 'pycparser', 'version': '3.11', 'file': 'pycparser-3.11-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/90/11/0e6f11117525ff0eec40ebac3d313376f102df93ca44ad9e893ee85e4f89/pycparser-3.11-py3-none-any.whl', 'size': 51178, 'sha256': '51d5a8ba2be0bbe440b99d2112604c95bbbc3c2748a64260186c541e1729cd80'},
    'pip': {'name': 'pip', 'version': '26.2.1', 'file': 'pip-26.2.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl', 'size': 1816632, 'sha256': '71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e'},
    'torch-cu128': {'name': 'torch', 'version': '2.11.0+cu128', 'file': 'torch-2.11.0+cu128-cp314-cp314-win_amd64.whl', 'url': 'https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp314-cp314-win_amd64.whl', 'size': 2770971557, 'sha256': 'd6c21797ff75271b4fbdd905e2d703be4ecea5ea5bbdde4d1c201e9c71bc411d'},
    'torch-cu126': {'name': 'torch', 'version': '2.11.0+cu126', 'file': 'torch-2.11.0+cu126-cp314-cp314-win_amd64.whl', 'url': 'https://download.pytorch.org/whl/cu126/torch-2.11.0%2Bcu126-cp314-cp314-win_amd64.whl', 'size': 2616869597, 'sha256': '146a8016c5abba673ea8af7d78e45e297b23e1f53c2a6749418a7c94f5d8d9ed'},
    'torch-cpu': {'name': 'torch', 'version': '2.11.0+cpu', 'file': 'torch-2.11.0+cpu-cp314-cp314-win_amd64.whl', 'url': 'https://download.pytorch.org/whl/cpu/torch-2.11.0%2Bcpu-cp314-cp314-win_amd64.whl', 'size': 116375735, 'sha256': '7575af4c9f7f7500ed62b1dafeb069aa0ba35b368a5f09793b3976b3d50f4fe4'},
}
WEIGHTS = [
    {'file': 'htdemucs_ft.yaml', 'url': 'https://huggingface.co/adefossez/HTDemucs-ft/resolve/d74ac89c3a1e874fc78f152555cf4d8533f06cd4/htdemucs_ft.yaml', 'size': 149, 'sha256': '69470b8c1bbd674437b51bc9fb491327a10ab0396b702c93389b9cf750016346'},
    {'file': 'f7e0c4bc.safetensors', 'url': 'https://huggingface.co/adefossez/HTDemucs-ft/resolve/d74ac89c3a1e874fc78f152555cf4d8533f06cd4/f7e0c4bc.safetensors', 'size': 84025440, 'sha256': '2c85ab3c62dd6edd8e0b965e38b16fd1cdde357cc25de6b6bc9ce7c83f60925f'},
    {'file': 'd12395a8.safetensors', 'url': 'https://huggingface.co/adefossez/HTDemucs-ft/resolve/d74ac89c3a1e874fc78f152555cf4d8533f06cd4/d12395a8.safetensors', 'size': 84025440, 'sha256': '5b01a97567ae9a3178a6236fb520251045c03eb8834bc8c24a4eec11d6c8fb56'},
    {'file': '92cfc3b6.safetensors', 'url': 'https://huggingface.co/adefossez/HTDemucs-ft/resolve/d74ac89c3a1e874fc78f152555cf4d8533f06cd4/92cfc3b6.safetensors', 'size': 84025440, 'sha256': 'a241863551f30d01c42bd7b97da40839922ead3acb0f1fcab25682f55b4eeb59'},
    {'file': '04573f0d.safetensors', 'url': 'https://huggingface.co/adefossez/HTDemucs-ft/resolve/d74ac89c3a1e874fc78f152555cf4d8533f06cd4/04573f0d.safetensors', 'size': 84025440, 'sha256': '68854b0d7c2b3274723b5761f6fd9f5aec5f1bcd3f0de7c1669546fdb7871b7c'},
]
# ---- ここまで ----

# 入れた後の大きさ（バイト・2026-11-03 にこの道具で実際に入れて測った値。torch-cu126 だけは cu128 の wheel の大きさの比からの見積もり）
# python＝パックの python/ から site-packages を除いた物・libs＝site-packages から torch・torchgen・functorch を除いた物（.pyc を含む）
SIZES = {
    'python': 26_811_579,
    'libs': 198_785_070,
    'torch-cpu': 479_426_275,
    'torch-cu128': 4_425_313_131,
    'torch-cu126': 4_179_000_000,
}
SIZES_MEASURED = {'python', 'libs', 'torch-cpu', 'torch-cu128'}
MARGIN = 500 * 1000 * 1000      # 空きの余裕
MAX_REL = 125                   # site-packages からの一番長いファイルの場所（torch 2.11 で 119 文字）
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0   # CREATE_NO_WINDOW（窓のアプリから呼んだ時に黒い窓を出さない）

STAGES = [
    ('python', 'Python を準備する'),
    ('download', '部品をダウンロードする（PyTorch・Demucs ほか）'),
    ('hash', 'ダウンロードした部品が壊れていないか確かめる'),
    ('pip', '部品を展開してインストールする'),
    ('weights', '学習済みモデルをダウンロードする（htdemucs_ft）'),
    ('verify', 'インストールした部品を試しに動かす'),
]
LABEL = dict(STAGES) | {'done': 'インストールが終わった'}


class SepInstallError(Exception):
    """利用者に見せるエラー（日本語・何をすればよいかまで）"""


class Cancelled(SepInstallError):
    pass


# ---------------------------------------------------------------- 小物

def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_json(p, obj):
    p = Path(p)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, p)


def _gb(n):
    return f'{n / 1e9:.1f} GB' if n >= 1e9 else f'{n / 1e6:.0f} MB'


def _du(p):
    total = 0
    stack = [str(p)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def _norm(name):
    return re.sub(r'[-_.]+', '_', name).lower()


_VER = re.compile(r'v?(?P<rel>\d+(?:\.\d+)*)(?:[-_.]?(?P<pt>a|alpha|b|beta|c|rc|pre|preview)[-_.]?(?P<pn>\d*))?'
                  r'(?:[-_.]?(?:post|rev|r)[-_.]?(?P<post>\d*))?(?:[-_.]?dev[-_.]?(?P<dev>\d*))?(?:\+(?P<local>[a-z0-9.]+))?')
_PRE = {'a': 0, 'alpha': 0, 'b': 1, 'beta': 1, 'c': 2, 'rc': 2, 'pre': 2, 'preview': 2}


def _vkey(v):
    """版を比べる形（PEP 440 のふつうの形・後ろの +cu128 等は比べない）→ tuple か None（読めない）。2.11 と 2.11.0 は同じ"""
    m = _VER.fullmatch(str(v or '').strip().lower())
    if not m:
        return None
    rel = [int(x) for x in m['rel'].split('.')]
    while len(rel) > 1 and rel[-1] == 0:
        rel.pop()
    if m['pt']:
        pre = (_PRE[m['pt']], int(m['pn'] or 0))
    elif m['dev'] is not None and m['post'] is None:
        pre = (-1, 0)                 # 1.0.dev1 は 1.0a1 より前
    else:
        pre = (9, 0)                  # 正式の版
    post = int(m['post'] or 0) if m['post'] is not None else -1
    dev = int(m['dev'] or 0) if m['dev'] is not None else 1 << 30
    return (tuple(rel), pre, post, dev)


def _local(v):
    """版の後ろの +… （torch の cu128・cpu 等）→ 小文字か ''"""
    s = str(v or '')
    return s.split('+', 1)[1].lower() if '+' in s else ''


def _ver_lt(a, b):
    ka, kb = _vkey(a), _vkey(b)
    return ka is None or (kb is not None and ka < kb)   # 読めない版は古い扱い（止める側に倒す）


def _sha256(p, cb=None):
    h = hashlib.sha256()
    done = 0
    with open(p, 'rb') as f:
        while True:
            b = f.read(4 << 20)
            if not b:
                break
            h.update(b)
            done += len(b)
            if cb:
                cb(done)
    return h.hexdigest()


def _ssl():
    return ssl.create_default_context()   # Windows の証明書の置き場（ROOT・CA）を読む


def _net_error(e, url):
    host = urllib.parse.urlsplit(url).hostname
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return f'取ってくる先にファイルが無い（{host}・404）。置き場が変わった＝アプリを新しくする'
        if e.code == 407:
            return f'プロキシの認証が要る（{host}・407）。Windows のプロキシの設定を確かめる'
        return f'{host} がエラーを返した（{e.code}）。少し待ってから「続きから入れる」'
    reason = getattr(e, 'reason', e)
    if isinstance(reason, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(e):
        return (f'{host} の HTTPS の証明書を確かめられない。ウイルス対策ソフトや会社のプロキシが通信を中継している時は、'
                f'その証明書が Windows の証明書の置き場に入っているかを確かめる（{reason}）')
    return f'ネットにつながらない（{host}: {reason}）。つながってから「続きから入れる」（取った所までは残っている）'


def _open(url, headers=None, method=None, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA, **(headers or {})}, method=method)
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl())


def _clean_env(base=None):
    """子のプロセスに渡す環境（ほかの Python・pip の設定を混ぜない）"""
    env = dict(os.environ if base is None else base)
    for k in list(env):
        ku = k.upper()
        if ku in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONEXECUTABLE', 'VIRTUAL_ENV', '__PYVENV_LAUNCHER__') \
                or ku.startswith('PIP_'):
            del env[k]
    env['PIP_CONFIG_FILE'] = os.devnull       # 利用者の pip.ini に頼らない（--isolated と二重）
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


_JOB = []


def _job():
    """この道具が止められた（プロセスを止めた）時に、子（pip・確かめ）も一緒に止まるジョブ（Windows・作れなければ None）"""
    if os.name != 'nt':
        return None
    if _JOB:
        return _JOB[0]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    h = k.CreateJobObjectW(None, None)
    if not h:
        _JOB.append(None)
        return None

    class Basic(ctypes.Structure):
        _fields_ = [('a', ctypes.c_int64), ('b', ctypes.c_int64), ('LimitFlags', ctypes.c_uint32), ('c', ctypes.c_size_t),
                    ('d', ctypes.c_size_t), ('e', ctypes.c_uint32), ('f', ctypes.c_size_t), ('g', ctypes.c_uint32),
                    ('h', ctypes.c_uint32)]

    class Ext(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6), ('m1', ctypes.c_size_t), ('m2', ctypes.c_size_t),
                    ('m3', ctypes.c_size_t), ('m4', ctypes.c_size_t)]
    info = Ext()
    info.basic.LimitFlags = 0x2000      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = k.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info))   # JobObjectExtendedLimitInformation
    _JOB.append(h if ok else None)
    return _JOB[0]


def _popen(cmd, **kw):
    p = subprocess.Popen(cmd, creationflags=NO_WINDOW, **kw)
    j = _job()
    if j:
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k.AssignProcessToJobObject(j, ctypes.c_void_p(int(p._handle)))
    return p


# ---------------------------------------------------------------- 場所

def python_exe(dir):
    """パックの python.exe（配布物＝python/python.exe・開発の PC の venv＝python/Scripts/python.exe）"""
    d = Path(dir) / 'python'
    for p in (d / 'python.exe', d / 'Scripts' / 'python.exe'):
        if p.exists():
            return p
    return d / 'python.exe'


def _site(dir):
    return Path(dir) / 'python' / 'Lib' / 'site-packages'


def _snapshot(dir):
    return Path(dir) / 'hf' / 'hub' / ('models--' + HF_REPO.replace('/', '--')) / 'snapshots' / HF_REV


def run_env(dir, base=None):
    """tools/separate.py を動かす時に足す環境変数。base（os.environ 等）を渡すと、それにほかの Python の設定を除いて足した全体を返す"""
    d = Path(dir).resolve()
    add = {
        'HF_HOME': str(d / 'hf'),             # 重みはパックの中（利用者のホームの .cache に置かない）
        'HF_HUB_OFFLINE': '1',                # 入れた後はネットに行かない
        'HF_HUB_DISABLE_TELEMETRY': '1',
        'HF_HUB_DISABLE_SYMLINKS_WARNING': '1',
        'TORCH_HOME': str(d / 'torch'),       # Demucs が前の置き場に戻った時も外に書かない
        'PYTHONNOUSERSITE': '1',
        'PYTHONIOENCODING': 'utf-8',
    }
    if base is None:
        return add
    return _clean_env(base) | add


# ---------------------------------------------------------------- GPU

def _nvml():
    """NVML（NVIDIA のドライバーに入っている nvml.dll）で GPU を見る → dict か None"""
    if os.name != 'nt':
        return None
    win = os.environ.get('WINDIR', r'C:\Windows')
    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    lib = None
    for p in (Path(win) / 'System32' / 'nvml.dll', Path(pf) / 'NVIDIA Corporation' / 'NVSMI' / 'nvml.dll'):
        if p.exists():
            try:
                lib = ctypes.WinDLL(str(p))
                break
            except OSError:
                pass
    if lib is None or lib.nvmlInit_v2() != 0:
        return None
    try:
        buf = ctypes.create_string_buffer(96)
        out = {'driver': None, 'cuda': None, 'gpus': []}
        if lib.nvmlSystemGetDriverVersion(buf, 96) == 0:
            out['driver'] = buf.value.decode(errors='replace')
        v = ctypes.c_int()
        if lib.nvmlSystemGetCudaDriverVersion_v2(ctypes.byref(v)) == 0 and v.value:
            out['cuda'] = (v.value // 1000, (v.value % 1000) // 10)
        n = ctypes.c_uint()
        if lib.nvmlDeviceGetCount_v2(ctypes.byref(n)) == 0:
            for i in range(n.value):
                h = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)) != 0:
                    continue
                g = {'name': None, 'cc': None, 'mem': None}
                if lib.nvmlDeviceGetName(h, buf, 96) == 0:
                    g['name'] = buf.value.decode(errors='replace')
                a, b = ctypes.c_int(), ctypes.c_int()
                if lib.nvmlDeviceGetCudaComputeCapability(h, ctypes.byref(a), ctypes.byref(b)) == 0:
                    g['cc'] = (a.value, b.value)
                mem = (ctypes.c_ulonglong * 3)()
                if lib.nvmlDeviceGetMemoryInfo(h, mem) == 0:
                    g['mem'] = int(mem[0])
                out['gpus'].append(g)
        return out
    finally:
        lib.nvmlShutdown()


def _smi():
    """nvidia-smi で GPU を見る → dict か None（NVML が読めない時の代わり）"""
    exe = shutil.which('nvidia-smi')
    if not exe:
        p = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32' / 'nvidia-smi.exe'
        exe = str(p) if p.exists() else None
    if not exe:
        return None
    try:
        q = subprocess.run([exe, '--query-gpu=name,driver_version,compute_cap,memory.total', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW)
        head = subprocess.run([exe], capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if q.returncode != 0:
        return None
    out = {'driver': None, 'cuda': None, 'gpus': []}
    for ln in q.stdout.splitlines():
        f = [x.strip() for x in ln.split(',')]
        if len(f) < 4:
            continue
        g = {'name': f[0], 'cc': None, 'mem': None}
        out['driver'] = f[1]
        m = re.match(r'(\d+)\.(\d+)', f[2])
        if m:
            g['cc'] = (int(m[1]), int(m[2]))
        if f[3].isdigit():
            g['mem'] = int(f[3]) * 1024 * 1024
        out['gpus'].append(g)
    m = re.search(r'CUDA Version:\s*(\d+)\.(\d+)', head.stdout or '')
    if m:
        out['cuda'] = (int(m[1]), int(m[2]))
    return out


def _cuda_from_driver(driver):
    """ドライバーの版から使える CUDA の版の目安（Windows・CUDA の説明の表）"""
    m = re.match(r'(\d+)\.(\d+)', driver or '')
    if not m:
        return None
    v = (int(m[1]), int(m[2]))
    for need, cuda in (((570, 65), (12, 8)), ((560, 76), (12, 6)), ((528, 33), (12, 0))):
        if v >= need:
            return cuda
    return (11, 0)


def _choose(info):
    """GPU の情報 → (おすすめの variant, 理由)"""
    if not info or not info['gpus']:
        return 'cpu', 'NVIDIA の GPU が見つからない → CPU 版（4 分の曲で 5〜10 分ほどかかる）'
    g = max(info['gpus'], key=lambda g: (g['cc'] or (0, 0), g['mem'] or 0))
    cuda = info['cuda'] or _cuda_from_driver(info['driver'])
    cc = g['cc']
    if g['mem'] is not None and g['mem'] < 3 * 1024 ** 3:
        return 'cpu', f'{g["name"]} は GPU のメモリが少ない（{g["mem"] / 1024 ** 3:.1f} GB・3 GB 以上が要る）→ CPU 版'
    if cc is not None and cc < VARIANTS['cu126']['cc']:
        return 'cpu', f'{g["name"]} は古くて PyTorch の GPU 版が対応していない → CPU 版'
    if cuda is None:
        return 'cpu', f'{g["name"]} のドライバーの版が分からない → CPU 版（ドライバーを入れ直すと GPU 版が使える）'
    if cuda >= VARIANTS['cu128']['cuda'] and (cc is None or cc >= VARIANTS['cu128']['cc']):
        return 'cu128', f'{g["name"]} で分ける（4 分の曲で 1 分ほど）'
    if cuda >= VARIANTS['cu126']['cuda'] and not (cc is not None and cc >= (10, 0)):   # cu126 は sm_50〜sm_90 だけ（Blackwell は cu128）
        if cc is not None and cc < VARIANTS['cu128']['cc']:
            return 'cu126', f'{g["name"]} は CUDA 12.8 版が対応していない世代 → CUDA 12.6 版'
        return 'cu126', (f'{g["name"]} のドライバー（{info["driver"]}・CUDA {cuda[0]}.{cuda[1]} まで）は CUDA 12.8 に足りない → '
                         'CUDA 12.6 版（ドライバーを新しくすると 12.8 版も使える）')
    return 'cpu', (f'{g["name"]} のドライバー（{info["driver"]}・CUDA {cuda[0]}.{cuda[1]} まで）が古い → CPU 版'
                   '（NVIDIA のドライバーを新しくすると GPU 版が使える）')


def detect_gpu():
    """→ {'nvidia', 'name', 'driver', 'cuda'（ドライバーが対応する CUDA の版）, 'cc', 'mem', 'variant'（おすすめ）, 'why', 'how'}"""
    info, how = _nvml(), 'nvml'
    if info is None:
        info, how = _smi(), 'nvidia-smi'
    if info is None:
        how = None
    variant, why = _choose(info)
    g = max(info['gpus'], key=lambda g: (g['cc'] or (0, 0), g['mem'] or 0)) if info and info['gpus'] else {}
    cuda = (info or {}).get('cuda')
    return {'nvidia': bool(g), 'name': g.get('name'), 'driver': (info or {}).get('driver'),
            'cuda': f'{cuda[0]}.{cuda[1]}' if cuda else None, 'cc': '.'.join(map(str, g['cc'])) if g.get('cc') else None,
            'mem': g.get('mem'), 'variant': variant, 'why': why, 'how': how}


# ---------------------------------------------------------------- 一覧

def _check_variant(v):
    if v not in VARIANTS:
        raise SepInstallError(f'種類 {v!r} は無い（{"・".join(VARIANTS)} のどれか）')
    if f'torch-{v}' not in FILES:
        raise SepInstallError(f'種類 {v} の PyTorch の一覧がこの道具に無い')


def _lib_files():
    return [FILES[f'lib-{_norm(n)}'] for n, _ in LIBS]


def _wheels(v):
    """取る wheel（torch・小物・pip）"""
    return [FILES[f'torch-{v}'], *_lib_files(), FILES['pip']]


def _find_runtime(runtime=None):
    """パックの Python の元: 引数 → 配布物の runtime/（この道具の隣）→ 埋め込み用の Python で動いていればそれ → None（venv を作る）"""
    if runtime:
        r = Path(runtime)
        if not (r / 'python.exe').exists():
            raise SepInstallError(f'埋め込み用の Python が無い（{r} に python.exe が無い）')
        return r
    r = Path(__file__).resolve().parents[1] / 'runtime'
    if (r / 'python.exe').exists():
        return r
    base = Path(sys.base_prefix)
    if list(base.glob('python*._pth')) and (base / 'python.exe').exists():
        return base
    return None


def _items(v, runtime=None):
    t = FILES[f'torch-{v}']
    libs = _lib_files()
    try:
        rt = _find_runtime(runtime)
    except SepInstallError:
        rt = None
    py_src = f'アプリに入っている Python（{rt}）を写す' if rt else f'今の Python（{sys.base_prefix}）から venv を作る（開発の PC だけ）'
    return [
        {'key': 'python', 'name': f'パック専用の Python {PY_VER[0]}.{PY_VER[1]}',
         'what': 'PyTorch と Demucs を動かす（アプリ本体の Python とは分ける）', 'source': py_src, 'download': 0,
         'install': SIZES['python']},
        {'key': 'torch', 'name': f'PyTorch {TORCH}（{VARIANTS[v]["label"]}）',
         'what': '音を分ける計算の土台' + ('（NVIDIA の GPU で動かす部品を含む）' if v != 'cpu' else ''),
         'source': t['url'], 'download': t['size'], 'install': SIZES[f'torch-{v}']},
        {'key': 'libs', 'name': f'Demucs {DEMUCS} と小物（{len(libs) - 1} 個・numpy・soundfile ほか）',
         'what': '曲を歌・ドラム・ベース・その他の 4 つの音に分ける仕組み（Meta の Demucs）', 'source': 'https://pypi.org/',
         'urls': [f['url'] for f in libs], 'download': sum(f['size'] for f in libs), 'install': SIZES['libs']},
        {'key': 'pip', 'name': f'pip {PIP[1]}', 'what': '部品を入れる道具（入れる時だけ使い、入れ終わったら消す）',
         'source': FILES['pip']['url'], 'download': FILES['pip']['size'], 'install': 0},
        {'key': 'weights', 'name': f'学習済みの重み {MODEL}（{len(WEIGHTS) - 1} つのモデル）',
         'what': '音を分けるのに使う学習済みのデータ（Demucs の作者が公開している物・入れた後はネット無しで使う）',
         'source': f'https://huggingface.co/{HF_REPO}', 'download': sum(w['size'] for w in WEIGHTS),
         'install': sum(w['size'] for w in WEIGHTS)},
    ]


def _head(url, timeout):
    with _open(url, method='HEAD', timeout=timeout) as r:
        n = r.headers.get('Content-Length')
        return int(n) if n and n.isdigit() else None


def _free_bytes(d):
    p = Path(d).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 0


def _long_paths():
    if os.name != 'nt':
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\FileSystem') as k:
            return winreg.QueryValueEx(k, 'LongPathsEnabled')[0] == 1
    except OSError:
        return False


def _path_problem(d):
    n = len(str(_site(Path(d).resolve()))) + 1 + MAX_REL
    if n >= 260 and not _long_paths():
        return (f'入れる場所の名前が長すぎる（PyTorch の一番深いファイルで {n} 文字・Windows の上限 259 文字）。'
                f'もっと短い場所（例: C:\\ANP\\sep）を選ぶ')
    return None


def plan(dir, variant=None, online=True, runtime=None):
    """入れる前の予告（大きさ・場所・何に使うか）。online=True ならネットで大きさを確かめる（短いタイムアウト・だめなら一覧の値）"""
    d = Path(dir).resolve()
    gpu = detect_gpu()
    v = variant or gpu['variant']
    _check_variant(v)
    items = _items(v, runtime)
    warnings = []
    estimated = True
    reached = False
    if online:
        urls = {f['url']: f['size'] for f in _wheels(v)} | {w['url']: w['size'] for w in WEIGHTS}
        try:
            _head(FILES['pip']['url'], timeout=4)     # まず 1 つ（つながらなければ残りを待たない）
            reached = True
        except (OSError, urllib.error.URLError, ValueError):
            pass
        if reached:
            got = {}
            with concurrent.futures.ThreadPoolExecutor(8) as ex:
                futs = {ex.submit(_head, u, 6): u for u in urls}
                for f in concurrent.futures.as_completed(futs):
                    try:
                        got[futs[f]] = f.result()
                    except (OSError, urllib.error.URLError, ValueError):
                        got[futs[f]] = None
            bad = [u for u, n in got.items() if n is not None and n != urls[u]]
            for u in bad:
                warnings.append(f'ダウンロード元のファイルの大きさが予定と違う（{u.rsplit("/", 1)[-1]}）。インストールの途中で止まるので、アプリを新しくしてください')
            estimated = any(n is None for n in got.values())
    install_bytes = sum(i['install'] for i in items)
    download_bytes = sum(i['download'] for i in items)
    # 一番多く使う時: 入れ終わりの大きさ＋wheel（入れ終わるまで残す。重みは取った物をそのまま置く）
    peak = install_bytes + sum(i['download'] for i in items if i['key'] in ('torch', 'libs', 'pip'))
    used = _du(d) if d.exists() else 0
    need = max(0, peak - used) + MARGIN
    free = _free_bytes(d)
    problems = []
    if free < need:
        problems.append(f'空き容量が足りない: {d.anchor or d} に {_gb(need)} 要る（空き {_gb(free)}）。空きを作るか、別のドライブを選んでください')
    pp = _path_problem(d)
    if pp:
        problems.append(pp)
    if not any(SIZES.get(k) for k in SIZES):
        warnings.append('インストール後の大きさの見積もりが無い')
    return {'dir': str(d), 'variant': v, 'variant_label': VARIANTS[v]['label'], 'gpu': gpu, 'items': items,
            'download_bytes': download_bytes, 'install_bytes': install_bytes, 'peak_bytes': peak, 'need_bytes': need,
            'free_bytes': free, 'enough': free >= need, 'estimated': estimated, 'online': reached,
            'install_estimated': f'torch-{v}' not in SIZES_MEASURED, 'problems': problems, 'warnings': warnings,
            'state': check(d)}


# ---------------------------------------------------------------- 入っているかを見る

def _dists(site):
    """site-packages の dist-info → {正規化した名前: (版, dist-info の場所)}"""
    out = {}
    try:
        names = os.listdir(site)
    except OSError:
        return out
    for n in names:
        if n.endswith('.dist-info') and '-' in n:
            name, ver = n[:-len('.dist-info')].rsplit('-', 1)
            out[_norm(name)] = (ver, Path(site) / n)
    return out


def _record_files(dist_info):
    try:
        with open(dist_info / 'RECORD', encoding='utf-8', newline='') as f:
            return [r[0] for r in csv.reader(f) if r]
    except OSError:
        return None


def _pkg_state(site, f, deep=False, dists=None):
    """部品 1 つ: 'ok'・'missing'（入っていない）・'version'（版が違う）・'broken'（途中で止まった・ファイルが足りない）"""
    have = (_dists(site) if dists is None else dists).get(_norm(f['name']))
    if have is None:
        return 'missing'
    if have[0] != f['version']:
        return 'version'
    rec = _record_files(have[1])
    if rec is None:
        return 'broken'
    if deep:
        for r in rec:
            if r.endswith('.pyc') or r.startswith('..'):
                continue
            if not (Path(site) / r).exists():
                return 'broken'
    return 'ok'


KEY_FILES = ['torch/__init__.py', 'torch/lib/c10.dll', 'torch/lib/torch_cpu.dll', 'demucs/api.py', 'numpy/__init__.py',
             '_soundfile_data']


def _resume_info(d, st):
    if not st:
        return None
    v = st.get('variant')
    done = [k for k, _ in STAGES if st.get('stages', {}).get(k, {}).get('done')]
    nxt = next((k for k, _ in STAGES if k not in done), 'verify')
    got = 0
    total = 0
    if v in VARIANTS and f'torch-{v}' in FILES:
        dl = Path(d) / 'downloads'
        for f in _wheels(v):
            total += f['size']
            for p in (dl / f['file'], dl / (f['file'] + '.part')):
                if p.exists():
                    got += p.stat().st_size
                    break
    return {'variant': v, 'stage': nxt, 'label': LABEL.get(nxt, nxt), 'done_stages': done, 'downloaded_bytes': got,
            'download_bytes': total, 'started_at': st.get('started_at'), 'updated_at': st.get('updated_at'),
            'error': st.get('error')}


NAMES = {'torch': 'PyTorch', 'demucs': 'Demucs'}   # 画面に出す名前（ほかは部品の名前のまま）
KEY_OWNER = {'torch': 'torch', 'demucs': 'demucs', 'numpy': 'numpy', '_soundfile_data': 'soundfile'}   # KEY_FILES の一番上 → 部品
WHY = {'diff': '違う版', 'older': '最低の版より古い', 'ng': '使ってはいけない版', 'missing': '入っていない', 'broken': '壊れている',
       'kind': 'GPU 版・CPU 版の種類が違う', 'model': '版が変わった'}
_NG_OP = re.compile(r'(==|!=|<=|>=|<|>)?\s*([0-9A-Za-z.+!_-]{1,64})')


def _ng_rules(ng):
    """NG（使ってはいけない版・app/update.py が配布元の update.json から控えた物）→ {正規化した部品の名前: [版の決まり…]}。
    ng は update.json の ng（{'parts': {名前: [版…]}, …}）か parts そのもの。形の違う物は黙って飛ばす（古い版が新しい形を読んでも止まらない）"""
    if not isinstance(ng, dict):
        return {}
    parts = ng.get('parts') if isinstance(ng.get('parts'), dict) else ({} if 'parts' in ng or 'app' in ng else ng)
    out = {}
    for name, vers in parts.items():
        if not isinstance(name, str) or not isinstance(vers, (list, tuple)):
            continue
        specs = [str(x).strip() for x in vers[:100] if isinstance(x, str) and _NG_OP.fullmatch(str(x).strip())]
        if specs:
            out.setdefault(_norm(name), []).extend(specs)
    return out


def _ng_match(name, version, rules):
    """部品 name の版 version が NG の決まり（'2.11.0'＝その版（+cu128 等はどれも）・'2.11.0+cu126'＝その種類だけ・'<2.11.0' 等）に当たるか"""
    if version is None:
        return False
    for spec in rules.get(_norm(name), ()):
        m = _NG_OP.fullmatch(spec)
        op, want = m[1] or '==', m[2]
        kv, kw = _vkey(version), _vkey(want)
        if kv is None or kw is None:
            continue
        if op in ('==', '!='):
            same = kv == kw and (not _local(want) or _local(want) == _local(version))
            if same == (op == '=='):
                return True
        elif (op == '<' and kv < kw) or (op == '<=' and kv <= kw) or (op == '>' and kv > kw) or (op == '>=' and kv >= kw):
            return True
    return False


def _verified(v=None):
    """確かめた組（この道具の一覧）の [(key, FILES の項目)]。v＝種類（None＝全部の種類の torch）。pip は入れる時だけ使う"""
    torch = [f'torch-{v}'] if v in VARIANTS else [f'torch-{x}' for x in VARIANTS] if v is None else []
    return [(k, FILES[k]) for k in torch + [f'lib-{_norm(n)}' for n, _ in LIBS] + ['pip'] if k in FILES]


def set_ng(variant=None, ng=None):
    """確かめた組（このアプリの版の一覧）の中に入っている NG の版 → [{'key', 'name', 'version'}]。
    空でなければ、部品をインストールし直しても直らない（同じ NG の版をまた入れる）＝アプリの更新が要る"""
    rules = _ng_rules(ng)
    if not rules:
        return []
    return [{'key': k, 'name': f['name'], 'version': f['version']} for k, f in _verified(variant) if _ng_match(f['name'], f['version'], rules)]


def _py_mm(s):
    m = re.match(r'(\d+)\.(\d+)', str(s or ''))
    return (int(m[1]), int(m[2])) if m else None


def _inst_python(inst):
    """入れた時のパックの Python の (major, minor)（installed.json の python か、無ければ lock の頭の後ろ -py314）"""
    mm = _py_mm(inst.get('python'))
    if mm:
        return mm
    m = re.search(r'-py(\d)(\d+)$', str(inst.get('lock') or ''))
    return (int(m[1]), int(m[2])) if m else None


def check(dir, ng=None):
    """起動のたびに呼ぶ（速い・torch を読み込まない）。ng＝使ってはいけない版（_ng_rules の形・app/setup.py が設定の update_ng を渡す）
    → {'ok'（必須の更新が無い）, 'missing'（止める訳・日本語）, 'variant', 'python', 'installed_at', 'resume', 'warnings',
       'stage'（'none'・'recommended'＝おすすめの更新（今のままでも使える）・'required'＝必須（揃うまで新しい曲を取り込めない））,
       'changes'（変わる部品 [{'key', 'name', 'label', 'have'（今の版・無ければ None）, 'want'（確かめた版）, 'min', 'why'（WHY の key）,
                  'required', 'fixable'（確かめた版が NG でない＝インストールで直る）, 'size'（ダウンロード）}]）,
       'update_bytes'（変わる部品だけ取り直す時のダウンロード量）, 'partial'（入っているパックの違う部品だけ取り直せる）,
       'rebuild'（パックの作り・Python の版が変わった＝全部インストールし直す）,
       'ng_set'（確かめた組の中の NG＝set_ng）, 'app_update'（直すにはアプリの更新が要る）, 'ng_why'（NG の訳・日本語）}"""
    d = Path(dir)
    inst = _read_json(d / 'installed.json')
    st = _read_json(d / 'state.json')
    res = {'ok': False, 'missing': [], 'variant': None, 'python': None, 'installed_at': None, 'resume': None, 'warnings': [],
           'stage': 'required', 'changes': [], 'update_bytes': 0, 'partial': False, 'rebuild': False, 'ng_set': [], 'app_update': False,
           'ng_why': (str(ng.get('why') or '')[:300] or None) if isinstance(ng, dict) else None}
    rules = _ng_rules(ng)
    if not d.is_dir():
        res['missing'].append('まだインストールしていない')
        return res
    py = python_exe(d)
    if py.exists():
        res['python'] = str(py)
    v = (inst or {}).get('variant') or (st or {}).get('variant')
    res['variant'] = v
    if inst:
        res['installed_at'] = inst.get('installed_at')
        res['warnings'] = list((inst.get('verify') or {}).get('warnings') or [])
    miss = res['missing']
    if not inst and not st:
        miss.append('まだインストールしていない')
        return res
    rebuild = False
    if not inst:
        miss.append('インストールが途中で止まっている（「続きからインストールする」で、済んだ所から再開する）')
    else:
        # 部品の版の違いは部品ごとに見る（下）。パックの作り・Python の版の違いは今と同じく必須＝全部インストールし直す
        if inst.get('format') != PACK_FORMAT:
            miss.append('アプリが新しくなり、音を分ける部品の作りが変わった（インストールし直してください）')
            rebuild = True
        ipy = _inst_python(inst)
        if ipy != PY_VER:
            have = f'{ipy[0]}.{ipy[1]}' if ipy else '不明'
            miss.append(f'アプリが新しくなり、部品用の Python の版が変わった（{have} → {PY_VER[0]}.{PY_VER[1]}・インストールし直してください）')
            rebuild = True
    if not py.exists():
        miss.append('部品用の Python が無い')
        rebuild = True
    changes = []
    if v not in VARIANTS or f'torch-{v}' not in FILES:
        miss.append(f'種類 {v!r} が分からない（インストールし直してください）')
        rebuild = True
    else:
        site = _site(d)
        res['ng_set'] = set_ng(v, ng)
        bad_keys = {e['key'] for e in res['ng_set']}
        dists = _dists(site)
        for key, f in _verified(v):
            if key == 'pip':
                continue
            cur = dists.get(_norm(f['name']))
            have = cur[0] if cur else None
            s = _pkg_state(site, f, dists=dists)
            lo = MIN_VERSIONS.get(f['name'], MIN_VERSIONS.get(_norm(f['name'])))
            why = None
            if s in ('missing', 'broken'):
                why = s
            elif s == 'version':
                if f['name'] == 'torch' and _local(have) != _local(f['version']):
                    why = 'kind'
                elif _ng_match(f['name'], have, rules):
                    why = 'ng'
                elif lo and _ver_lt(have, lo):
                    why = 'older'
                elif key not in bad_keys:
                    why = 'diff'            # 最低の版以上で NG でない＝今のままでも使える（おすすめの更新）
                # 確かめた版が NG で、入っている版は使える＝入れ替えない（アプリの更新をすすめる＝ng_set）
            elif key in bad_keys:
                why = 'ng'                  # 入っているのが確かめた版そのもので、それが NG
            if why:
                changes.append({'key': key, 'name': f['name'], 'label': NAMES.get(f['name'], f['name']), 'have': have, 'want': f['version'],
                                'min': lo, 'why': why, 'required': why != 'diff', 'fixable': key not in bad_keys and 'pip' not in bad_keys,
                                'size': f['size']})
        keys = KEY_FILES + (['torch/lib/torch_cuda.dll'] if v != 'cpu' else [])
        lost = [k for k in keys if not (site / k).exists()]
        lost_keys = set()      # 大事なファイルが消えた部品（下の「足りない」とは別の文で知らせる）
        if lost:
            miss.append('部品のファイルが消えている（ウイルス対策ソフトが消した等）: ' + '・'.join(lost))
            seen = {c['name'] for c in changes}
            for k in lost:
                owner = KEY_OWNER.get(k.split('/', 1)[0])
                fk = f'torch-{v}' if owner == 'torch' else f'lib-{_norm(owner)}' if owner else None
                if fk in FILES and FILES[fk]['name'] not in seen:
                    f = FILES[fk]
                    seen.add(f['name'])
                    lost_keys.add(fk)
                    cur = dists.get(_norm(f['name']))
                    changes.append({'key': fk, 'name': f['name'], 'label': NAMES.get(f['name'], f['name']), 'have': cur[0] if cur else None,
                                    'want': f['version'], 'min': MIN_VERSIONS.get(f['name']), 'why': 'broken', 'required': True,
                                    'fixable': fk not in bad_keys, 'size': f['size']})

        def names(cs):
            out = []
            for c in cs:
                if c['why'] == 'older':
                    out.append(f'{c["label"]} {c["have"]}（{c["min"]} 以上が要る）')
                elif c['why'] == 'ng':
                    out.append(f'{c["label"]} {c["have"]}')
                else:
                    out.append(f'{c["label"]}（{ {"missing": "無い", "broken": "途中まで", "kind": "GPU 版・CPU 版の種類が違う"}[c["why"]] }）')
            return '・'.join(out[:6]) + (f' ほか {len(out) - 6} 個' if len(out) > 6 else '')
        gone = [c for c in changes if c['why'] in ('missing', 'broken', 'kind') and c['key'] not in lost_keys]
        if gone:
            miss.append('部品が足りない: ' + names(gone))
        old = [c for c in changes if c['why'] == 'older']
        if old:
            miss.append('このアプリには古すぎる版の部品がある: ' + names(old))
        ngs = [c for c in changes if c['why'] == 'ng']
        if ngs:
            miss.append('使ってはいけない版の部品が入っている: ' + names(ngs) + (f'（{res["ng_why"]}）' if res['ng_why'] else ''))
    snap = _snapshot(d)
    wl = [w for w in WEIGHTS if not ((snap / w['file']).exists() and (snap / w['file']).stat().st_size == w['size'])]
    model_changed = bool(inst) and (inst.get('model', MODEL) != MODEL or inst.get('hf_revision', HF_REV) != HF_REV)
    if model_changed:
        miss.append('アプリが新しくなり、学習済みモデルの版が変わった')
    elif wl:
        miss.append(f'学習済みモデルが足りない（{len(wl)} / {len(WEIGHTS)} 個）')
    if wl or model_changed:
        changes.append({'key': 'weights', 'name': MODEL, 'label': f'学習済みモデル（{MODEL}）',
                        'have': str(inst.get('hf_revision'))[:7] if model_changed else None, 'want': HF_REV[:7], 'min': None,
                        'why': 'model' if model_changed else 'missing', 'required': True, 'fixable': True, 'size': sum(w['size'] for w in wl)})
    ref = snap.parent.parent / 'refs' / 'main'
    if not wl and not (ref.exists() and ref.read_text(encoding='ascii', errors='replace').strip() == HF_REV):
        miss.append('学習済みモデルの印（refs/main）が無い')
    res['changes'] = changes
    parts = [c for c in changes if c['key'] != 'weights']
    res['update_bytes'] = sum(c['size'] for c in changes) + (FILES['pip']['size'] if parts else 0)
    res['rebuild'] = rebuild
    res['partial'] = bool(inst) and not rebuild
    res['app_update'] = any(c['required'] and not c['fixable'] for c in changes)
    if res['app_update']:
        miss.append('このアプリの版がインストールする部品が使ってはいけない版（部品をインストールし直しても直らない）＝アプリを更新してください')
    res['ok'] = not miss
    res['stage'] = 'required' if miss else 'recommended' if changes else 'none'
    # 続きから: 入っていない時・入っているパックとは別の種類へ入れ替える途中（今のパックはそのまま使える）・おすすめの更新の途中
    unfinished = bool(st and st.get('variant') and not st.get('finished_at'))
    if unfinished and (not res['ok'] or st.get('variant') != (inst or {}).get('variant') or res['stage'] == 'recommended'):
        res['resume'] = _resume_info(d, st)
    return res


# ---------------------------------------------------------------- 入れる

class _Reporter:
    def __init__(self, progress):
        self.cb = progress
        self.last = (None, 0.0)

    def __call__(self, stage, done=0, total=0, msg='', force=False, **extra):
        if not self.cb:
            return
        now = time.monotonic()
        if not force and stage == self.last[0] and now - self.last[1] < 0.25 and not (total and done >= total):
            return
        self.last = (stage, now)
        steps = [k for k, _ in STAGES]
        self.cb({'stage': stage, 'label': LABEL.get(stage, stage), 'done': done, 'total': total, 'msg': msg,
                 'step': steps.index(stage) + 1 if stage in steps else len(steps), 'steps': len(steps), **extra})


class _Lock:
    """同じ場所に 2 つ同時に入れない（install.lock に PID）"""

    def __init__(self, d):
        self.p = Path(d) / 'install.lock'

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    pid = int(self.p.read_text().strip() or 0)
                except (OSError, ValueError):
                    pid = 0
                if pid and pid != os.getpid() and _alive(pid):
                    raise SepInstallError('同じインストール先に、別のところからインストールしている途中です（終わるのを待つか、そちらを止めてください）')
                self.p.unlink(missing_ok=True)
        raise SepInstallError(f'{self.p} を作れない')

    def __exit__(self, *a):
        self.p.unlink(missing_ok=True)


def _alive(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = ctypes.WinDLL('kernel32')
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x1000, False, pid)    # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


class _State:
    def __init__(self, d, variant):
        self.p = Path(d) / 'state.json'
        st = _read_json(self.p) or {}
        if st.get('variant') != variant or st.get('lock') != LOCK_ID:
            # 別の種類・別の一覧（アプリの版が上がった）でも、パックの作りと Python の版が同じならパック専用の Python は作り直さない
            # （作り直すと site-packages ごと消え、違う部品だけでなく全部を取り直すことになる＝おすすめの更新が数 GB になる）
            py = st.get('stages', {}).get('python') or {}
            same = st.get('format') == PACK_FORMAT and py.get('done') and _py_mm(py.get('version')) == PY_VER
            keep = {'python': py} if same else {}
            st = {'format': PACK_FORMAT, 'lock': LOCK_ID, 'variant': variant, 'started_at': _now(), 'stages': keep}
        st['finished_at'] = None
        self.st = st

    def done(self, k):
        return bool(self.st['stages'].get(k, {}).get('done'))

    def mark(self, k, **info):
        self.st['stages'][k] = {'done': True, 'at': _now(), **info}
        self.save()

    def unmark(self, *ks):
        for k in ks:
            self.st['stages'].pop(k, None)
        self.save()

    def save(self, **kw):
        self.st.update(kw, updated_at=_now())
        _write_json(self.p, self.st)


def _check_cancel(cancel):
    if cancel and cancel():
        raise Cancelled('一時停止した（次に「続きからインストールする」と、済んだ所から再開する）')


def _download(url, part, size, cb, cancel, tries=6):
    """Range で続きから取る（part に足す）。size まで取れたら返る"""
    part.parent.mkdir(parents=True, exist_ok=True)
    err = None
    for i in range(tries):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have == size:
            return
        try:
            hdr = {'Range': f'bytes={have}-'} if have else {}
            with _open(url, headers=hdr, timeout=30) as r:
                if have and r.status != 206:
                    have = 0      # 続きを受け付けない置き場 → 頭から
                elif have:
                    m = re.match(r'bytes (\d+)-', r.headers.get('Content-Range', ''))
                    if not m or int(m[1]) != have:
                        have = 0
                with open(part, 'ab' if have else 'wb') as f:
                    while True:
                        _check_cancel(cancel)
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                        have += len(b)
                        cb(have)
            if have >= size:
                return
            err = OSError('途中で切れた')
        except urllib.error.HTTPError as e:
            if e.code == 416:     # 範囲の外＝もう全部ある（か壊れている）→ 指紋で確かめる
                return
            if e.code in (403, 404, 407, 410):
                raise SepInstallError(_net_error(e, url)) from e
            err = e
        except (urllib.error.URLError, OSError, TimeoutError) as e:   # ConnectionResetError・IncompleteRead 等
            if isinstance(e, Cancelled):
                raise
            err = e
        time.sleep(min(2 ** i, 15))
    raise SepInstallError(_net_error(err, url))


def _fetch_verified(f, dst, dl, rep, cancel, base_done, total, stage='download'):
    """f（url・size・sha256）を dst へ（取りかけは dl（downloads/）の .part・指紋が合ってから dst に置く）"""
    if dst.exists() and dst.stat().st_size == f['size']:
        return
    part = Path(dl) / (f['file'] + '.part')
    for attempt in range(2):
        _download(f['url'], part, f['size'], lambda n: rep(stage, base_done + n, total, f['file']), cancel)
        big = f['size'] > 50e6 and stage == 'download'     # 重み（84MB）は重みの段のまま確かめる
        if big:
            rep('hash', 0, f['size'], f['file'], force=True)
        digest = _sha256(part, (lambda n: rep('hash', n, f['size'], f['file'])) if big else None)
        if digest == f['sha256'] and part.stat().st_size == f['size']:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(part, dst)
            return
        part.unlink(missing_ok=True)       # 壊れた・書き換えられた → 1 回だけ頭から取り直す
    raise SepInstallError(f'ダウンロードしたファイルが壊れている（{f["file"]}）。通信の途中で壊れたか、ダウンロード元のファイルが変わった。'
                          f'もう一度「入れる」を押す（続けて合わなければアプリを新しくする）')


def _copy_runtime(rt, dst):
    """埋め込み用の Python（rt）を dst へ写す。site-packages（アプリ本体の部品）・Scripts・__pycache__ は写さず、._pth をパック用に"""
    rt = Path(rt)

    def ignore(src, names):
        top = Path(src) == rt
        skip = {'__pycache__'} | ({'Scripts'} if top else set()) | ({'site-packages'} if Path(src) == rt / 'Lib' else set())
        return [n for n in names if n in skip or (top and n.endswith('._pth'))]
    shutil.copytree(rt, dst, ignore=ignore)
    zips = sorted(Path(dst).glob('python3*.zip'))
    if not zips:
        shutil.rmtree(dst, ignore_errors=True)
        raise SepInstallError(f'埋め込み用の Python ではない（{rt} に python3XX.zip が無い）')
    ver = zips[0].stem[len('python'):]
    (Path(dst) / 'Lib' / 'site-packages').mkdir(parents=True, exist_ok=True)
    # パック用の ._pth（本体の場所は足さない＝tools/separate.py は numpy・soundfile・torch・demucs だけを読む）
    (Path(dst) / f'python{ver}._pth').write_text('\n'.join([f'python{ver}.zip', '.', r'Lib\site-packages', 'import site', '']),
                                                 encoding='utf-8')
    return ver


def _prepare_python(d, runtime, rep):
    py_dir = d / 'python'
    tmp = d / 'python.tmp'
    rt = _find_runtime(runtime)
    if tmp.exists():
        shutil.rmtree(tmp)
    if py_dir.exists():
        shutil.rmtree(py_dir)
    if rt:
        rep('python', 0, 1, f'{rt} をコピーする', force=True)
        _copy_runtime(rt, tmp)
        os.replace(tmp, py_dir)
    else:
        base = getattr(sys, '_base_executable', None) or sys.executable
        rep('python', 0, 1, f'{base} から venv を作る（開発の PC）', force=True)
        r = subprocess.run([base, '-m', 'venv', '--without-pip', str(tmp)], capture_output=True, text=True,
                           env=_clean_env(), creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise SepInstallError(f'パック専用の Python（venv）を作れない: {r.stderr.strip()[-300:]}')
        os.replace(tmp, py_dir)
    py = python_exe(d)
    r = subprocess.run([str(py), '-I', '-c', 'import sys,struct;print(*sys.version_info[:3],struct.calcsize("P")*8)'],
                       capture_output=True, text=True, env=_clean_env(), creationflags=NO_WINDOW)
    try:
        a, b, c, bits = map(int, r.stdout.split())
    except ValueError:
        raise SepInstallError(f'パック専用の Python が動かない（{py}）: {r.stderr.strip()[-300:]}') from None
    if (a, b) != PY_VER or bits != 64:
        raise SepInstallError(f'パック専用の Python の版が合わない（{a}.{b}・{bits} ビット。{PY_VER[0]}.{PY_VER[1]} の 64 ビットが要る）')
    rep('python', 1, 1, f'Python {a}.{b}.{c}', force=True)
    return f'{a}.{b}.{c}'


def _wheel_tops(whl):
    with zipfile.ZipFile(whl) as z:
        return {n.split('/', 1)[0] for n in z.namelist() if not n.split('/', 1)[0].endswith(('.dist-info', '.data'))}


def _remove_pkg(site, f, whl=None):
    """入れかけ・版違いの部品を消す（RECORD とこれから入れる wheel の一番上の名前）"""
    have = _dists(site).get(_norm(f['name']))
    tops = set()
    if have:
        for r in _record_files(have[1]) or []:
            t = r.split('/', 1)[0]
            if t and not t.startswith('..') and not t.endswith('.dist-info') and t != '__pycache__':
                tops.add(t)
    if whl and Path(whl).exists():
        tops |= _wheel_tops(whl)
    for t in tops:
        p = Path(site) / t
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink(missing_ok=True)
    if have:
        shutil.rmtree(have[1], ignore_errors=True)


PIP_BOOT = "import runpy,sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module('pip', run_name='__main__', alter_sys=True)"


def _run_pip(d, files, rep, cancel, total_bytes, base_bytes, log):
    py = python_exe(d)
    cmd = [str(py), '-I', '-c', PIP_BOOT, str(d / 'downloads' / FILES['pip']['file']), 'install', '--isolated', '--no-index',
           '--no-deps', '--no-cache-dir', '--disable-pip-version-check', '--no-warn-script-location', '--progress-bar', 'off',
           *[str(d / 'downloads' / f['file']) for f in files]]
    site = _site(d)
    with open(log, 'a', encoding='utf-8') as lf:
        lf.write(f'\n[{_now()}] $ {" ".join(cmd)}\n')
        lf.flush()
        p = _popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=_clean_env())
        last = 0.0
        try:
            while p.poll() is None:
                if cancel and cancel():
                    p.kill()
                    p.wait()
                    _check_cancel(cancel)
                time.sleep(0.3)
                if time.monotonic() - last > 1.5:     # 進み＝site-packages の増え方（torch は 1 万ファイル余り＝数え直しは間をあける）
                    last = time.monotonic()
                    rep('pip', min(total_bytes, max(0, _du(site) - base_bytes)), total_bytes,
                        ', '.join(f['name'] for f in files)[:80])
        except BaseException:
            if p.poll() is None:
                p.kill()
                p.wait()
            raise
    if p.returncode != 0:
        tail = Path(log).read_text(encoding='utf-8', errors='replace').strip().splitlines()[-6:]
        raise SepInstallError(f'部品のインストールに失敗した（pip の終わりの値 {p.returncode}）。記録 {log} の最後:\n' + '\n'.join(tail))


VERIFY = r'''
import json, os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
r = {}
t0 = time.time()
import torch
r["torch"] = torch.__version__
r["cuda_build"] = torch.version.cuda
r["cuda"] = bool(torch.cuda.is_available())
if r["cuda"]:
    r["gpu"] = torch.cuda.get_device_name(0)
import demucs, numpy, soundfile
r["demucs"] = getattr(demucs, "__version__", None)
r["import_s"] = round(time.time() - t0, 2)
from demucs.pretrained import get_model
from demucs.apply import apply_model
t1 = time.time()
m = get_model(sys.argv[1])
r["load_s"] = round(time.time() - t1, 2)
r["sources"] = list(m.sources)
dev = "cuda" if r["cuda"] else "cpu"
g = torch.Generator().manual_seed(0)
x = torch.randn(1, 2, 44100 * 2, generator=g) * 0.1
t2 = time.time()
with torch.no_grad():
    y = apply_model(m, x, device=dev, shifts=1, split=True, progress=False)
r["apply_s"] = round(time.time() - t2, 2)
r["shape"] = list(y.shape)
r["finite"] = bool(torch.isfinite(y).all())
print("SEPCHECK " + json.dumps(r))
'''


def verify(dir, log=None):
    """入れた部品で試しに動かす（パックの Python で torch・demucs を読み、ネット無しで重みを読み、2 秒の音を分ける）→ dict"""
    d = Path(dir).resolve()
    py = python_exe(d)
    if not py.exists():
        raise SepInstallError('部品用の Python が無い（インストールし直してください）')
    env = run_env(d, os.environ)
    env['HTTP_PROXY'] = env['HTTPS_PROXY'] = 'http://127.0.0.1:9'   # ネットに行こうとしたら失敗させる＝ネット無しで動くかを見る
    env.pop('NO_PROXY', None)
    env.pop('no_proxy', None)
    t0 = time.time()
    p = _popen([str(py), '-I', '-c', VERIFY, MODEL], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
               errors='replace', env=env)
    try:
        out, err = p.communicate(timeout=900)
    except BaseException:
        p.kill()
        p.wait()
        raise
    r = subprocess.CompletedProcess(p.args, p.returncode, out, err)
    if log:
        with open(log, 'a', encoding='utf-8') as lf:
            lf.write(f'\n[{_now()}] 確かめ（終わりの値 {r.returncode}）\n{r.stdout}\n{r.stderr[-4000:]}\n')
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith('SEPCHECK ')), None)
    if r.returncode != 0 or not line:
        err = (r.stderr.strip().splitlines() or ['（記録なし）'])[-1]
        hint = ''
        if 'DLL' in r.stderr or 'WinError 126' in r.stderr or 'WinError 1114' in r.stderr:
            hint = '（Visual C++ の再頒布可能パッケージ x64 が要るかもしれない）'
        raise SepInstallError(f'インストールした部品で動かせなかった: {err}{hint}')
    res = json.loads(line[len('SEPCHECK '):])
    res['seconds'] = round(time.time() - t0, 1)
    warnings = []
    inst_v = (_read_json(d / 'installed.json') or _read_json(d / 'state.json') or {}).get('variant')
    if inst_v and inst_v != 'cpu' and not res.get('cuda'):
        warnings.append('GPU 版をインストールしたが、グラフィックボードが使えない（ドライバーが古い・対応していない等）。CPU で動く（遅い）。'
                        'NVIDIA のドライバーを新しくするか、CPU 版に入れ替える')
    if not res.get('finite'):
        raise SepInstallError('インストールした部品で分けた結果がおかしい（インストールし直してください）')
    if res.get('torch') != FILES.get(f'torch-{inst_v}', {}).get('version', res.get('torch')):
        warnings.append(f'PyTorch の版が一覧と違う（{res.get("torch")}）')
    res['warnings'] = warnings
    res['ok'] = True
    return res


def install(dir, variant=None, runtime=None, progress=None, cancel=None):
    """段ごとに入れる（止めても次に呼べば済んだ段を飛ばして続きから）→ installed.json の中身。
    progress(dict)＝{'stage', 'label', 'done', 'total', 'msg', 'step', 'steps'}・cancel()＝True で止める（Cancelled）"""
    d = Path(dir).resolve()
    d.mkdir(parents=True, exist_ok=True)
    rep = _Reporter(progress)
    v = variant or detect_gpu()['variant']
    _check_variant(v)
    with _Lock(d):
        inst = _read_json(d / 'installed.json')
        if inst and inst.get('variant') == v and check(d)['stage'] == 'none':   # おすすめの更新（違う版）がある時は入れ替える
            rep('done', 1, 1, 'もうインストールされている', force=True)
            return inst | {'already': True}
        # 入れ終わった印は、中身を書き換える直前に消す（別の種類へ入れ替える途中で止めても、今のパックはそのまま使える）
        drop_mark = lambda: (d / 'installed.json').unlink(missing_ok=True)   # noqa: E731
        st = _State(d, v)
        st.save(error=None)
        p = plan(d, v, online=False, runtime=runtime)
        if p['problems']:
            raise SepInstallError(' / '.join(p['problems']))
        log = d / 'install.log'
        dl = d / 'downloads'
        t_all = time.time()
        times = {}
        try:
            # 1. Python
            t0 = time.time()
            if not (st.done('python') and python_exe(d).exists()):
                st.unmark('python', 'pip', 'verify')
                drop_mark()
                pyver = _prepare_python(d, runtime, rep)
                st.mark('python', version=pyver)
            times['python'] = round(time.time() - t0, 1)
            _check_cancel(cancel)

            # 2. 入っていない・途中まで・版違いの部品だけ取る（直す時も同じ道）
            site = _site(d)
            want = [FILES[f'torch-{v}'], *_lib_files()]
            todo = [f for f in want if _pkg_state(site, f, deep=True) != 'ok']
            keep = {f['file'] for f in todo} | ({FILES['pip']['file']} if todo else set())
            if dl.exists():
                for x in dl.iterdir():      # 別の種類の torch などの取りかけは消す（場所を空ける）
                    base = x.name[:-len('.part')] if x.name.endswith('.part') else x.name
                    if base.endswith('.whl') and base not in keep:
                        x.unlink(missing_ok=True)
            t0 = time.time()
            if todo:
                files = sorted(todo, key=lambda f: -f['size']) + [FILES['pip']]
                total = sum(f['size'] for f in files)
                base = 0
                rep('download', 0, total, files[0]['file'], force=True)
                for f in files:
                    _fetch_verified(f, dl / f['file'], dl, rep, cancel, base, total)
                    base += f['size']
                    rep('download', base, total, f['file'], force=True)
                st.mark('download', files=len(files), bytes=total)
                st.mark('hash')
            else:
                st.mark('download', files=0, bytes=0)
                st.mark('hash')
            times['download'] = round(time.time() - t0, 1)
            _check_cancel(cancel)

            # 3. pip（取ったファイルだけから・ネットに行かない）。入れかけ・版違いは先に消す
            t0 = time.time()
            if todo:
                st.unmark('pip', 'verify')
                drop_mark()
                for f in todo:      # 版違い・入れかけ（pip は dist-info を最後に書く＝止まると torch/ だけが残る）を消してから入れる
                    _remove_pkg(site, f, dl / f['file'])
                small = [f for f in todo if f['name'] != 'torch']
                big = [f for f in todo if f['name'] == 'torch']
                total = (SIZES['libs'] if small else 0) + (SIZES[f'torch-{v}'] if big else 0) or 1
                base0 = _du(site)
                rep('pip', 0, total, '', force=True)
                for group in (small, big):
                    if group:
                        _run_pip(d, group, rep, cancel, total, base0, log)
                still = [f['name'] for f in want if _pkg_state(site, f, deep=True) != 'ok']
                if still:
                    raise SepInstallError(f'部品が全部はインストールできなかった（{"・".join(still)}）。記録 {log}')
                rep('pip', total, total, '', force=True)
            st.mark('pip')
            times['pip'] = round(time.time() - t0, 1)
            _check_cancel(cancel)

            # 4. 重み（Hugging Face の置き場の形で置く＝HF_HUB_OFFLINE=1 で Demucs がそのまま読む）
            t0 = time.time()
            snap = _snapshot(d)
            wtotal = sum(w['size'] for w in WEIGHTS)
            base = 0
            rep('weights', 0, wtotal, '', force=True)
            for w in WEIGHTS:
                _fetch_verified(w, snap / w['file'], dl, rep, cancel, base, wtotal, stage='weights')
                base += w['size']
                rep('weights', base, wtotal, w['file'], force=True)
            ref = snap.parent.parent / 'refs' / 'main'
            ref.parent.mkdir(parents=True, exist_ok=True)
            ref.write_text(HF_REV, encoding='ascii')
            st.mark('weights')
            times['weights'] = round(time.time() - t0, 1)
            _check_cancel(cancel)

            # 5. 確かめ
            t0 = time.time()
            rep('verify', 0, 1, '試しに 2 秒の音を分けている', force=True)
            res = verify(d, log)
            st.mark('verify')
            times['verify'] = round(time.time() - t0, 1)
            rep('verify', 1, 1, f'PyTorch {res.get("torch")}・{"GPU " + res.get("gpu", "") if res.get("cuda") else "CPU"}', force=True)
        except Cancelled:
            st.save(error='止めた')
            raise
        except SepInstallError as e:
            st.save(error=str(e))
            raise
        except Exception as e:     # 思わぬ物も日本語で（記録に詳しく）
            st.save(error=repr(e))
            with open(log, 'a', encoding='utf-8') as lf:
                import traceback
                lf.write(f'\n[{_now()}] 思わぬエラー\n{traceback.format_exc()}\n')
            raise SepInstallError(f'インストールの途中で思わぬエラー（{type(e).__name__}: {e}）。もう一度「続きからインストールする」を押してください。'
                                  f'続けて起きる時は記録 {log} を添えて知らせる') from e
        # 6. 入れ終わった印・取った wheel を消す
        inst = {'format': PACK_FORMAT, 'lock': LOCK_ID, 'variant': v, 'torch': FILES[f'torch-{v}']['version'], 'demucs': DEMUCS,
                'model': MODEL, 'hf_revision': HF_REV, 'python': st.st['stages'].get('python', {}).get('version'),
                'installed_at': _now(), 'seconds': round(time.time() - t_all, 1), 'times': times, 'verify': res}
        _write_json(d / 'installed.json', inst)
        shutil.rmtree(dl, ignore_errors=True)
        inst['size'] = _du(d)
        _write_json(d / 'installed.json', inst)
        st.save(error=None, finished_at=_now())
        rep('done', 1, 1, f'{_gb(inst["size"])}・{inst["seconds"]:.0f} 秒', force=True)
        return inst


# ---------------------------------------------------------------- 開発用: 一覧を作り直す

def _tag_rank(fn):
    """cp314・win_amd64 の CPython で入る wheel の好み（小さいほど良い）・入らなければ None"""
    m = re.match(r'.+?-[^-]+(?:-\d[^-]*)?-([^-]+)-([^-]+)-([^-]+)\.whl$', fn)
    if not m:
        return None
    py, abi, plat = (set(x.split('.')) for x in m.groups())
    tag = f'cp{PY_VER[0]}{PY_VER[1]}'
    if not plat & {'win_amd64', 'any'}:
        return None
    if 'win_amd64' in plat and tag in py and tag in abi:
        return 0
    if 'win_amd64' in plat and 'abi3' in abi and any(p.startswith('cp3') and int(p[3:] or 0) <= PY_VER[1] for p in py):
        return 1
    if 'none' in abi and (py & {tag, 'py3', f'py{PY_VER[0]}{PY_VER[1]}', 'py2.py3'} or 'py3' in py):
        return 2 if 'win_amd64' in plat else 3
    return None


def _lock():
    def get(u):
        with _open(u, timeout=30) as r:
            return r.read()
    files = {}
    for n, ver in LIBS + [PIP]:
        meta = json.loads(get(f'https://pypi.org/pypi/{n}/{ver}/json'))
        cands = [(r, u) for u in meta['urls'] if u['packagetype'] == 'bdist_wheel' and (r := _tag_rank(u['filename'])) is not None]
        if not cands:
            raise SystemExit(f'{n} {ver} に cp{PY_VER[0]}{PY_VER[1]}・win_amd64 で入る wheel が無い')
        u = min(cands, key=lambda c: c[0])[1]
        key = 'pip' if (n, ver) == PIP else f'lib-{_norm(n)}'
        files[key] = {'name': n, 'version': ver, 'file': u['filename'], 'url': u['url'], 'size': u['size'],
                      'sha256': u['digests']['sha256']}
    tag = f'cp{PY_VER[0]}{PY_VER[1]}'
    for v, info in VARIANTS.items():
        html = get(info['index'] + '/torch/').decode()
        fn = f'torch-{TORCH}+{v}-{tag}-{tag}-win_amd64.whl'
        m = re.search(r'href="([^"#]*' + re.escape(urllib.parse.quote(fn)) + r')#sha256=([0-9a-f]{64})"', html)
        if not m:
            raise SystemExit(f'{info["index"]}/torch/ に {fn} が無い')
        url = f'{info["index"]}/{urllib.parse.quote(fn)}'   # 一覧の href は download-r2 の時がある＝決まった置き場の形にそろえる
        files[f'torch-{v}'] = {'name': 'torch', 'version': f'{TORCH}+{v}', 'file': fn, 'url': url, 'size': _head(url, 30),
                               'sha256': m[2]}
    api = json.loads(get(f'https://huggingface.co/api/models/{HF_REPO}/revision/{HF_REV}?blobs=true'))
    bag = get(f'https://huggingface.co/{HF_REPO}/resolve/{HF_REV}/{MODEL}.yaml')
    sigs = re.search(r'models:\s*\[([^\]]*)\]', bag.decode())[1]
    want = [f'{MODEL}.yaml'] + [s.strip(" '\"") + '.safetensors' for s in sigs.split(',')]
    sib = {s['rfilename']: s for s in api['siblings']}
    weights = []
    for fn in want:
        s = sib[fn]
        url = f'https://huggingface.co/{HF_REPO}/resolve/{HF_REV}/{fn}'
        if s.get('lfs'):
            size, sha = s['lfs']['size'], s['lfs']['sha256']
        else:
            size, sha = len(bag), hashlib.sha256(bag).hexdigest()
        weights.append({'file': fn, 'url': url, 'size': size, 'sha256': sha})
    return files, weights


LOCK_BEGIN = '# ---- 取る物の一覧（`sep_install.py lock --write` が作る・手で書き換えない） ----'
LOCK_END = '# ---- ここまで ----'


def _lock_text(files, weights):
    def one(d):
        return '{' + ', '.join(f'{k!r}: {v!r}' for k, v in d.items()) + '}'
    lines = ['FILES = {']
    lines += [f'    {k!r}: {one(v)},' for k, v in files.items()]
    lines += ['}', 'WEIGHTS = [']
    lines += [f'    {one(w)},' for w in weights]
    lines += [']', '']
    return '\n'.join(lines)


# ---------------------------------------------------------------- コマンド

def _print_human(o):
    if 'items' in o:
        g = o['gpu']
        print(f'場所: {o["dir"]}')
        print(f'GPU: {g["name"] or "NVIDIA の GPU なし"}（ドライバー {g["driver"]}・CUDA {g["cuda"]}・{g["how"]}）→ おすすめ {g["variant"]}: {g["why"]}')
        print(f'種類: {o["variant"]}（{o["variant_label"]}）')
        for i in o['items']:
            print(f'  {i["name"]}: 取る {_gb(i["download"])}・入れた後 {_gb(i["install"])} — {i["what"]}（{i["source"]}）')
        print(f'合わせて: 取る {_gb(o["download_bytes"])}・入れた後 {_gb(o["install_bytes"])}・途中で一番多く使う {_gb(o["peak_bytes"])}・'
              f'空き {_gb(o["free_bytes"])}（{"足りる" if o["enough"] else "足りない"}）{"・一覧の値" if o["estimated"] else "・置き場で確かめた"}')
        for p in o['problems']:
            print('  だめ: ' + p)
        for w in o['warnings']:
            print('  注意: ' + w)
        o = o['state']
    stage = {'none': '', 'recommended': '・おすすめの更新あり（今のままでも使える）', 'required': ''}.get(o.get('stage'), '')
    print(('入っている' if o['ok'] else '入っていない') + (f'（{o["variant"]}・{o["installed_at"]}）' if o.get('variant') else '') + stage)
    for m in o.get('missing', []):
        print('  - ' + m)
    for c in o.get('changes', []):
        print(f'  {"必須" if c["required"] else "おすすめ"}: {c["label"]} {c["have"] or "なし"} → {c["want"]}（{WHY.get(c["why"], c["why"])}・'
              f'ダウンロード {_gb(c["size"])}）')
    if o.get('changes'):
        print(f'  違う部品だけ取り直す時のダウンロード: {_gb(o["update_bytes"])}' + ('（全部インストールし直す）' if o.get('rebuild') else ''))
    if o.get('resume'):
        r = o['resume']
        print(f'  続きから: 次は「{r["label"]}」（取った量 {_gb(r["downloaded_bytes"])} / {_gb(r["download_bytes"])}）')


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='音を分ける部品（PyTorch＋Demucs＋重み）を入れる')
    ap.add_argument('cmd', choices=['plan', 'check', 'install', 'verify', 'gpu', 'lock'])
    ap.add_argument('--dir', help='パックの置き場')
    ap.add_argument('--variant', choices=list(VARIANTS), help='種類（既定＝GPU を見てすすめる物）')
    ap.add_argument('--runtime', help='埋め込み用の Python のフォルダ（既定＝この道具の隣の runtime/・無ければ今の Python から venv）')
    ap.add_argument('--offline', action='store_true', help='plan: ネットで大きさを確かめない')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--write', action='store_true', help='lock: この道具の中の一覧を書き直す（開発用）')
    ap.add_argument('--ng', help='check: 使ってはいけない版（update.json の ng の形の JSON か、そのファイル）')
    a = ap.parse_args(argv)
    ng = None
    if a.ng:
        p = Path(a.ng)
        try:
            ng = json.loads(p.read_text(encoding='utf-8') if p.is_file() else a.ng)
        except (OSError, ValueError) as e:
            ap.error(f'--ng を読めない: {e}')

    def out(o):
        print(json.dumps(o, ensure_ascii=False), flush=True)

    if a.cmd == 'lock':
        files, weights = _lock()
        text = _lock_text(files, weights)
        if a.write:
            me = Path(__file__)
            src = me.read_text(encoding='utf-8')
            i, j = src.index(LOCK_BEGIN) + len(LOCK_BEGIN), src.index(LOCK_END)
            me.write_text(src[:i] + '\n' + text + src[j:], encoding='utf-8', newline='\n')
            print(f'{me} の一覧を書き直した（{len(files)} 個・重み {len(weights)} 個）')
        else:
            print(text)
        return 0
    if a.cmd == 'gpu':
        o = detect_gpu()
        out(o) if a.json else print(f'{o["name"] or "NVIDIA の GPU なし"} → {o["variant"]}: {o["why"]}')
        return 0
    if not a.dir:
        ap.error('--dir が要る')
    try:
        if a.cmd == 'plan':
            o = plan(a.dir, a.variant, online=not a.offline, runtime=a.runtime)
            out(o) if a.json else _print_human(o)
            return 0
        if a.cmd == 'check':
            o = check(a.dir, ng)
            out(o) if a.json else _print_human(o)
            return 0 if o['ok'] else 1
        if a.cmd == 'verify':
            o = verify(a.dir, Path(a.dir) / 'install.log')
            out(o) if a.json else print(json.dumps(o, ensure_ascii=False, indent=1))
            return 0
        # install
        if a.json:
            prog = out
        else:
            def prog(p):
                pct = f'{100 * p["done"] / p["total"]:5.1f}%' if p['total'] else ''
                print(f'[{p["step"]}/{p["steps"]}] {p["label"]} {pct} {p["msg"]}', flush=True)
        o = install(a.dir, a.variant, a.runtime, prog)
        out({'stage': 'done', **o}) if a.json else print(f'入れ終わった: {o.get("variant")}・{o.get("installed_at")}')
        return 0
    except KeyboardInterrupt:
        msg = '止めた（次に「続きから入れる」と、済んだ所を飛ばして続ける）'
        out({'error': msg, 'cancelled': True}) if a.json else print(msg, file=sys.stderr)
        return 1
    except SepInstallError as e:
        out({'error': str(e), 'cancelled': isinstance(e, Cancelled)}) if a.json else print('エラー: ' + str(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
