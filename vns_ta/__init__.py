# https://py-pkgs.org/04-package-structure
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("VNS-TA")
except PackageNotFoundError:
    __version__ = "dev"
