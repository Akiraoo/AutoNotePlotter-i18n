@echo off
rem automap app (Auto Note Plotter) in the browser: start the server, then open http://127.0.0.1:8765/ once it answers.
rem Stop with stop.bat, the Quit button in the page, or by closing this window. The window app is the other .bat file.
rem Keep comments ASCII: with chcp 65001, cmd misreads lines after a non-ASCII comment line.
chcp 65001 >nul
cd /d "%~dp0.."
echo Auto Note Plotter を起動しています…（パソコンを起動し直した直後などは 30 秒ほどかかることがあります。準備ができるとブラウザが開きます）
".venv\Scripts\python.exe" app\server.py %*
if errorlevel 1 pause
