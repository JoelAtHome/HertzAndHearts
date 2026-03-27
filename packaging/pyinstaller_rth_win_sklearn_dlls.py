# PyInstaller runtime hook: runs before the app imports user code.
# PyInstaller often fails to materialize sklearn/.libs even when binaries list it;
# sklearn still probes .../sklearn/.libs/vcomp140.dll. Copy from _internal root.
import os
import shutil
import sys

_SKLEARN_VC_DLLS = (
    "vcomp140.dll",
    "msvcp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "concrt140.dll",
)

if getattr(sys, "frozen", False) and sys.platform == "win32":
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            os.add_dll_directory(meipass)
        except OSError:
            pass
        libs = os.path.join(meipass, "sklearn", ".libs")
        try:
            os.makedirs(libs, exist_ok=True)
            for name in _SKLEARN_VC_DLLS:
                src = os.path.join(meipass, name)
                dst = os.path.join(libs, name)
                if os.path.isfile(src) and not os.path.isfile(dst):
                    shutil.copy2(src, dst)
        except OSError:
            pass
        if os.path.isdir(libs):
            try:
                os.add_dll_directory(libs)
            except OSError:
                pass
