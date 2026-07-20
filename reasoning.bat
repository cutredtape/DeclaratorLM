@echo off
setlocal
set "DECLARATOR_REASONING_DEBUG=1"
echo [INFO] Reasoning debug mode ON
python "%~dp0webview_app.py"
endlocal
