#!/usr/bin/env bash
set -euo pipefail

# Build a base Ubuntu kiosk ISO from WSL/Linux-native filesystem.
# Usage:
#   bash scripts/build_kiosk_iso.sh
#   bash scripts/build_kiosk_iso.sh --install-deps
#   HNH_DISTRO=noble HNH_ARCH=amd64 bash scripts/build_kiosk_iso.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HNH_DISTRO="${HNH_DISTRO:-noble}"
HNH_ARCH="${HNH_ARCH:-amd64}"
HNH_MIRROR="${HNH_MIRROR:-https://archive.ubuntu.com/ubuntu}"
BUILD_ROOT="${BUILD_ROOT:-${HOME}/hnh-kiosk-build}"
INSTALL_DEPS="0"

for arg in "$@"; do
  case "${arg}" in
    --install-deps) INSTALL_DEPS="1" ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      exit 2
      ;;
  esac
done

if [[ "${INSTALL_DEPS}" == "1" ]]; then
  echo "[kiosk-iso] Installing build dependencies..."
  sudo apt update
  sudo apt install -y xorriso squashfs-tools live-build wget curl git rsync
fi

if ! command -v lb >/dev/null 2>&1; then
  echo "[kiosk-iso] live-build (lb) not found. Run with --install-deps first." >&2
  exit 1
fi

if ! command -v xorriso >/dev/null 2>&1; then
  echo "[kiosk-iso] xorriso not found. Run with --install-deps first." >&2
  exit 1
fi

PROJECT_VERSION="dev"
if [[ -f "${REPO_ROOT}/pyproject.toml" ]]; then
  PROJECT_VERSION="$(python3 - <<'PY'
import pathlib, re
p = pathlib.Path("pyproject.toml")
text = p.read_text(encoding="utf-8")
m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.M)
print(m.group(1) if m else "dev")
PY
)"
fi
PROJECT_VERSION="${PROJECT_VERSION/b0/-beta}"

mkdir -p "${BUILD_ROOT}"
cd "${BUILD_ROOT}"

echo "[kiosk-iso] Build root: ${BUILD_ROOT}"
echo "[kiosk-iso] Distro: ${HNH_DISTRO}, Arch: ${HNH_ARCH}"
echo "[kiosk-iso] Mirror: ${HNH_MIRROR}"

sudo lb clean --purge || true

lb config \
  --mode ubuntu \
  --distribution "${HNH_DISTRO}" \
  --architectures "${HNH_ARCH}" \
  --binary-images iso-hybrid \
  --archive-areas "main restricted universe multiverse" \
  --mirror-bootstrap "${HNH_MIRROR}" \
  --mirror-binary "${HNH_MIRROR}" \
  --mirror-chroot-security "${HNH_MIRROR}" \
  --debian-installer false \
  --apt-source-archives false \
  --apt-options "--yes -o Acquire::Retries=20 -o Acquire::By-Hash=yes -o Acquire::Languages=none -o Acquire::http::Timeout=90 -o Acquire::https::Timeout=90 -o Acquire::http::No-Cache=true -o Acquire::https::No-Cache=true"

echo "[kiosk-iso] Starting build (this can take a while)..."
sudo lb build

ISO_PATH="${BUILD_ROOT}/live-image-${HNH_ARCH}.hybrid.iso"
if [[ ! -f "${ISO_PATH}" ]]; then
  echo "[kiosk-iso] Build completed but ISO not found at: ${ISO_PATH}" >&2
  exit 1
fi

OUT_DIR="${REPO_ROOT}/dist"
mkdir -p "${OUT_DIR}"
OUT_ISO="${OUT_DIR}/hnh-kiosk-base-${PROJECT_VERSION}.iso"
cp -f "${ISO_PATH}" "${OUT_ISO}"

echo "[kiosk-iso] Done."
echo "[kiosk-iso] Output ISO: ${OUT_ISO}"
