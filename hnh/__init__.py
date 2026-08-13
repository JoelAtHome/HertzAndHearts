# Version resolution shared by the window title, the About dialog and the
# update check, so they can never disagree about which build is running.
from __future__ import annotations

from pathlib import Path
import re
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError

# Sentinel used when neither a source tree nor installed metadata is available.
UNKNOWN_VERSION = "0.0.0-dev"


def _version_from_local_pyproject() -> str | None:
    """Prefer the source-tree version so local launches reflect the repo."""
    root = Path(__file__).resolve().parents[1]
    if getattr(sys, "frozen", False):
        # Frozen builds bundle pyproject.toml next to the extracted package.
        root = Path(getattr(sys, "_MEIPASS", root))
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if not match:
        return None
    return match.group(1).strip() or None


def _version_from_metadata() -> str | None:
    try:
        return _pkg_version("Hertz-and-Hearts").strip() or None
    except PackageNotFoundError:
        return None


__version__ = _version_from_local_pyproject() or _version_from_metadata() or UNKNOWN_VERSION
