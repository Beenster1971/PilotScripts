# build_windows.ps1
# One-time: ensure you have Python 3.11+ and pip, then:
#   py -3.11 -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   pip install --upgrade pip
#   pip install -r requirements.txt pyinstaller
#
# Build .exe (no console):
pyinstaller --noconsole --onefile --name app.py

Write-Host ""
Write-Host "Build complete. EXE at: dist\SimBriefRTWeb.exe"
Write-Host "If the window doesn't render, install Microsoft Edge WebView2 Runtime:"
Write-Host "https://developer.microsoft.com/microsoft-edge/webview2/#download-section"
