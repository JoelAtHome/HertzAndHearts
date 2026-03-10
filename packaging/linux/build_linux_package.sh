#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -e ".[build]"

python -m PyInstaller Hertz-and-Hearts.spec --clean --noconfirm

mkdir -p dist
tar -C dist -czf dist/Hertz-and-Hearts-linux-x64.tar.gz Hertz-and-Hearts

echo "Linux package created: dist/Hertz-and-Hearts-linux-x64.tar.gz"
