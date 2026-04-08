#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -e ".[build]"

python -m PyInstaller Hertz-and-Hearts.spec --clean --noconfirm

version_label="$(python - <<'PY'
import re, tomllib
v = tomllib.load(open("pyproject.toml", "rb"))["project"]["version"]
m = re.fullmatch(r"(\d+\.\d+\.\d+)b(\d+)", v)
if m:
    n = int(m.group(2))
    print(f"{m.group(1)}-beta" if n == 0 else f"{m.group(1)}-beta.{n}")
else:
    print(v)
PY
)"

mkdir -p dist
out="dist/Hertz-and-Hearts-${version_label}-linux-x64.tar.gz"
tar -C dist -czf "$out" Hertz-and-Hearts

echo "Linux package created: $out"
