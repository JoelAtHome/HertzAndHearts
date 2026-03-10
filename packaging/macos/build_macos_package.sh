#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -e ".[build]"

python -m PyInstaller Hertz-and-Hearts.spec --clean --noconfirm

mkdir -p dist
ditto -c -k --sequesterRsrc --keepParent dist/Hertz-and-Hearts.app dist/Hertz-and-Hearts-macos.zip

echo "macOS package created: dist/Hertz-and-Hearts-macos.zip"
