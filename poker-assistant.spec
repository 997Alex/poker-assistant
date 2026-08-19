# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec per Poker Assistant (Windows e Linux, stessa configurazione).
# Build: pyinstaller poker-assistant.spec --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import os

datas = [
    ("models/poker_best.pt", "models"),
]
hiddenimports = [
    "mss",
    "treys",
    "cv2",
    "numpy",
    "easyocr",   # opzionale, incluso se disponibile
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
]

# Runtime Visual C++ (Windows): c10.dll di torch ne ha bisogno, altrimenti
# "WinError 1114" all'avvio. Se presente nel System32 della macchina di build,
# viene messo accanto all'exe cosi' la DLL viene sempre trovata.
for _dll in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
             "vcruntime140.dll", "vcruntime140_1.dll"):
    _p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", _dll)
    if os.path.exists(_p):
        datas.append((_p, "."))

# ultralytics: pacchetto dati (config yaml dei modelli) + sottomoduli
datas += collect_data_files("ultralytics")
hiddenimports += collect_submodules("ultralytics")

# mss include i suoi dati interni
datas += collect_data_files("mss")

a = Analysis(
    ["app_entry.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pandas", "scipy", "IPython", "jupyter",
        "tkinter", "PyQt6", "PySide2", "PySide6",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PokerAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # app a finestra (nessuna console)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PokerAssistant",
)