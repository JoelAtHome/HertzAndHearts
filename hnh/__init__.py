# Read version from installed package metadata so pyproject.toml
# remains the single source of truth.
from importlib.metadata import version as _pkg_version, PackageNotFoundError
try:
    __version__ = _pkg_version("Hertz-and-Hearts")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
