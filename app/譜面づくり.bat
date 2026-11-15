@echo off
chcp 65001 >nul
rem 譜面づくりのアプリを窓で開く（pywebview の窓・この黒い窓はすぐ閉じる）。ブラウザで使う時は start.bat
rem 黒い窓を出さずに開くショートカットは: .venv\Scripts\python.exe app\desktop.py --shortcut（既定はデスクトップに作る）
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (echo .venv が無い（作り方は CLAUDE.md のテスト・実行）& pause & exit /b 1)
start "" ".venv\Scripts\pythonw.exe" app\desktop.py %*
