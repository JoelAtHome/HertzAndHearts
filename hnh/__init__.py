# Prefer source-tree pyproject version when available so local
# launches reflect the repository's current version immediately.
from pathlib import Path
import re
from importlib.metadata import version as _pkg_version, PackageNotFoundError


def _version_from_local_pyproject() -> str | None:
    root = Path(__file__).resolve().parents[1]
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


_local_version = _version_from_local_pyproject()
if _local_version:
    __version__ = _local_version
else:
    try:
        __version__ = _pkg_version("Hertz-and-Hearts")
    except PackageNotFoundError:
        __version__ = "0.0.0-dev"
