# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Hertz & Hearts.
# Usage: pyinstaller Hertz-and-Hearts.spec

import platform
import re

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Read version from pyproject.toml (single source of truth).
with open("pyproject.toml", encoding="utf-8") as f:
    _match = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
VERSION = _match.group(1) if _match else "1.0.0b0"

IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

icon_path = "docs/logo.icns" if IS_MAC else "docs/logo.ico"

# Exclude only tkinter (Qt app). Do not strip other stdlib modules without auditing imports.
# Hidden: lazy imports under hnh/ and full reportlab subtree (PDF export).
_hiddenimports = [
    "PySide6.QtCharts",
    "PySide6.QtBluetooth",
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "hnh.resources",
    "numpy",
    "hrvanalysis",
    "matplotlib.figure",
    "matplotlib.backends.backend_agg",
    "scipy.signal",
    "neurokit2",
    "pyedflib",
    "qrcode",
    "qrcode.constants",
    "pandas.errors",
]
_hiddenimports += collect_submodules("reportlab")
# QTc uses lazy `import neurokit2` in hnh/qtc.py — static analysis often misses it.
# NeuroKit2's __init__ imports sklearn and many subpackages; without collect,
# Windows frozen builds often show "neurokit2 unavailable" while PSD (scipy only) works.
_hiddenimports += collect_submodules("neurokit2")
_hiddenimports += collect_submodules("sklearn")

a = Analysis(
    ["hnh/app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("LICENSE", "."),
    ],
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hertz-and-Hearts",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Hertz-and-Hearts",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Hertz-and-Hearts.app",
        icon=icon_path,
        bundle_identifier="com.hertz-and-hearts.app",
        info_plist={
            "NSBluetoothAlwaysUsageDescription": (
                "Hertz & Hearts needs Bluetooth to connect to heart rate sensors."
            ),
            "CFBundleShortVersionString": VERSION,
        },
    )
