@echo off
REM run_dev_windows.bat - run the app in a native window (no build needed)
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -m pip install --user --quiet -r requirements.txt
%PY% simbrief_rtf_webview_app.py
