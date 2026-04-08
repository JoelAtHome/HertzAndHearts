# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Hertz & Hearts.
# Usage: pyinstaller Hertz-and-Hearts.spec

import platform
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# PyInstaller accepts POSIX-style destinations; avoids flaky handling of "\\.libs".
_SKLEARN_LIBS_DEST = (Path("sklearn") / ".libs").as_posix()


def _win_sklearn_dot_libs_dlls_explicit() -> list:
    """Every *.dll next to sklearn in site-packages (vcomp140, msvcp140, …)."""
    if platform.system() != "Windows":
        return []
    try:
        import sklearn
    except Exception:
        return []
    root = Path(sklearn.__file__).resolve().parent / ".libs"
    if not root.is_dir():
        return []
    return [(str(p.resolve()), _SKLEARN_LIBS_DEST) for p in sorted(root.glob("*.dll"))]


def _win_dlls_beside_sklearn_openmp() -> list:
    """
    sklearn/.libs/vcomp140.dll loads from that folder; Windows resolves
    vcruntime140*.dll there first. Python ships those runtimes next to python.exe
    / in DLLs/, but PyInstaller usually places them only at _internal root, so
    vcomp still fails on machines without VC++ redist. Copy companions into
    sklearn/.libs alongside vcomp140.dll.
    """
    if platform.system() != "Windows":
        return []
    names = ("vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll")
    search_dirs = [
        Path(sys.executable).resolve().parent,
        Path(sys.base_prefix) / "DLLs",
        Path(sys.base_prefix),
    ]
    dest = _SKLEARN_LIBS_DEST
    out: list[tuple[str, str]] = []
    for name in names:
        for folder in search_dirs:
            candidate = folder / name
            if candidate.is_file():
                out.append((str(candidate), dest))
                break
    return out


def _win_duplicate_binaries_to_internal_root(entries: list) -> list:
    """ctypes fallback uses basename under _MEIPASS if the sklearn\\.libs path fails."""
    if platform.system() != "Windows" or not entries:
        return list(entries)
    return list(entries) + [(src, ".") for src, _ in entries]

block_cipher = None

# Read version from pyproject.toml (single source of truth).
with open("pyproject.toml", encoding="utf-8") as f:
    _match = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
VERSION = _match.group(1) if _match else "1.0.0b2"

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

# hook-sklearn only collects data files. collect_dynamic_libs("sklearn") is empty on
# some runners → _internal/sklearn/.libs never appears; glob site-packages explicitly.
_sklearn_dlls = collect_dynamic_libs("sklearn")
_sklearn_dlls_explicit = _win_sklearn_dot_libs_dlls_explicit()
if IS_WIN:
    _sklearn_merged = list(dict.fromkeys(_sklearn_dlls_explicit + _sklearn_dlls))
    if not _sklearn_merged:
        _sklearn_merged = list(_sklearn_dlls)
else:
    _sklearn_merged = list(_sklearn_dlls)

_win_sklearn_runtime = _win_dlls_beside_sklearn_openmp()
_win_sklearn_binaries = _win_duplicate_binaries_to_internal_root(
    _sklearn_merged + _win_sklearn_runtime
)

# PyInstaller's spec executor may not define __file__ (e.g. on CI).
_spec_src = globals().get("__file__")
_SPEC_DIR = (
    Path(_spec_src).resolve().parent
    if _spec_src
    else Path.cwd().resolve()
)
_runtime_hooks = []
if IS_WIN:
    _runtime_hooks.append(
        str(_SPEC_DIR / "packaging" / "pyinstaller_rth_win_sklearn_dlls.py")
    )

a = Analysis(
    ["hnh/app.py"],
    pathex=[],
    binaries=_win_sklearn_binaries if IS_WIN else _sklearn_dlls,
    datas=[
        ("LICENSE", "."),
    ],
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=_runtime_hooks,
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
    upx_exclude=["vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll"],
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    # UPX can break MSVC / OpenMP DLLs used by sklearn; keep them uncompressed.
    upx_exclude=[
        "vcomp140.dll",
        "msvcp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "concrt140.dll",
    ],
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
