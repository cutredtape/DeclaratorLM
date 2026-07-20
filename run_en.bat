@echo off
setlocal
set "DECLARATOR_UI_LANG=en"
python "%~dp0webview_app.py" %*
