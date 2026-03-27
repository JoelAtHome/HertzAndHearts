# PyInstaller runtime hook: runs before the app imports user code.
# Helps Windows resolve vcomp140 / vcruntime when sklearn lives under _internal.
import os
import sys

if getattr(sys, "frozen", False) and sys.platform == "win32":
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            os.add_dll_directory(meipass)
        except OSError:
            pass
        libs = os.path.join(meipass, "sklearn", ".libs")
        if os.path.isdir(libs):
            try:
                os.add_dll_directory(libs)
            except OSError:
                pass
