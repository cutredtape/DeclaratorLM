# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: DeclaratorLM (webview_app.py + Vite dist + nazk_parser)."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Каталог з цим .spec (корінь репозиторію)
try:
    ROOT = Path(SPEC).resolve().parent
except NameError:  # pragma: no cover
    ROOT = Path(os.getcwd()).resolve()


def _py_datas(names: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in names:
        p = ROOT / name
        if p.is_file():
            out.append((str(p), "."))
    return out


def _bundle_package(name: str) -> tuple[list, list, list]:
    """collect_all для пакета (datas, binaries, hiddenimports)."""
    try:
        return collect_all(name)
    except Exception:
        return [], [], []


# UI + НАЗК + скрипти
datas = [
    (str(ROOT / "declarator-lm" / "dist"), os.path.join("declarator-lm", "dist")),
    (str(ROOT / "nazk_parser"), "nazk_parser"),
] + _py_datas(
    [
        "main.py",
        "report.py",
        "openrouter_client.py",
        "dossier_html_summary.py",
        "deep_research_bridge.py",
    ]
)

binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "clr",
    "main",
    "openrouter_client",
    "deep_research_bridge",
    "dossier_html_summary",
    "report",
]

# pywebview + pythonnet + залежності (без цього exe ~15 MB і падає на import webview)
for _pkg in (
    "webview",
    "pythonnet",
    "clr_loader",
    "bottle",
    "proxy_tools",
    "psutil",
    "cffi",
):
    _d, _b, _h = _bundle_package(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

hiddenimports += collect_submodules("webview")

a = Analysis(
    [str(ROOT / "webview_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=list(dict.fromkeys(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Іконка exe / вікна (Windows): assets/app.ico
_app_ico = ROOT / "assets" / "app.ico"
_exe_extra = {}
if _app_ico.is_file():
    _exe_extra["icon"] = str(_app_ico)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DeclaratorLM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **_exe_extra,
)
