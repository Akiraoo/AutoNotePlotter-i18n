@echo off
chcp 65001 >nul
rem Stop the automap app server started by start.bat (port 8765).
rem The server asks for its per-start key (app/server.py TOKEN). server.py and desktop.py write it to %LOCALAPPDATA%\AutoNotePlotter\session\PORT.key
rem Keep comments ASCII: with chcp 65001, cmd misreads lines after a non-ASCII comment line.
set "KEY="
set "KF=%LOCALAPPDATA%\AutoNotePlotter\session\8765.key"
if exist "%KF%" set /p KEY=<"%KF%"
set "CODE=000"
"%SystemRoot%\System32\curl.exe" -s -o nul -w "%%{http_code}" -m 3 -X POST -H "X-Automap: 1" -H "X-Automap-Key: %KEY%" http://127.0.0.1:8765/api/shutdown > "%TEMP%\anp-stop.txt" 2>nul
if exist "%TEMP%\anp-stop.txt" set /p CODE=<"%TEMP%\anp-stop.txt"
del "%TEMP%\anp-stop.txt" >nul 2>&1
if "%CODE%"=="200" (echo アプリを止めました。) else if "%CODE%"=="403" (echo アプリは動いていますが、止められませんでした。画面の「終わる」で止めてください。) else (echo アプリは動いていません。)
"%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
