SimBrief → VFR/IFR Radio Scripts (Windows Standalone WebView App)

Run (dev, no build):
  - Double-click run_dev_windows.bat

Build a single-file EXE:
  - Open PowerShell in this folder
  - py -3.11 -m venv .venv
  - .\.venv\Scripts\Activate.ps1
  - pip install --upgrade pip
  - pip install -r requirements.txt pyinstaller
  - ./build_windows.ps1
  - Output: dist\SimBriefRTWeb.exe

Notes:
  - The window is powered by Microsoft Edge WebView2 (installed on most machines).
    If you see a blank window or an error about WebView2, install the runtime:
    https://developer.microsoft.com/microsoft-edge/webview2/#download-section
  - Internet connection is required to fetch your SimBrief OFP.
  - No external browser windows are opened.
