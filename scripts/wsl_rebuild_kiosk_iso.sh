#!/usr/bin/env bash
set -euo pipefail

# One-command kiosk ISO rebuild for WSL/Ubuntu.
# Builds in Linux-native filesystem and copies ISO to Windows repo dist folder.
#
# Usage:
#   bash scripts/wsl_rebuild_kiosk_iso.sh

REPO_WIN_PATH="/mnt/c/Users/joelb/Hertz-and-Hearts"
BUILD_ROOT="${HOME}/hnh-kiosk-build"
DIST_OUT="${REPO_WIN_PATH}/dist"

MIRROR_BOOTSTRAP="https://archive.ubuntu.com/ubuntu"
MIRROR_BINARY="https://archive.ubuntu.com/ubuntu"
MIRROR_SECURITY="https://security.ubuntu.com/ubuntu"

echo "[hnh-kiosk] Installing/updating required tools..."
sudo apt update
sudo apt install -y xorriso squashfs-tools live-build wget curl git rsync || true

# Reduce apt index churn/mismatch risk in flaky mirror windows.
printf 'Acquire::Languages "none";\nAcquire::Retries "20";\nAcquire::http::Timeout "90";\nAcquire::https::Timeout "90";\n' \
  | sudo tee /etc/apt/apt.conf.d/99hnh-kiosk-apt >/dev/null

echo "[hnh-kiosk] Preparing build root: ${BUILD_ROOT}"
mkdir -p "${BUILD_ROOT}"
cd "${BUILD_ROOT}"

sudo lb clean --purge || true
rm -rf config auto .build .cache chroot binary

echo "[hnh-kiosk] Configuring live-build..."
lb config \
  --mode ubuntu \
  --distribution noble \
  --architectures amd64 \
  --binary-images iso-hybrid \
  --apt-source-archives false \
  --archive-areas "main restricted universe multiverse" \
  --mirror-bootstrap "${MIRROR_BOOTSTRAP}" \
  --mirror-binary "${MIRROR_BINARY}" \
  --mirror-chroot-security "${MIRROR_SECURITY}" \
  --debian-installer false \
  --apt-options "--yes -o Acquire::Retries=20 -o Acquire::By-Hash=yes -o Acquire::Languages=none -o Acquire::http::Timeout=90 -o Acquire::https::Timeout=90 -o Acquire::http::No-Cache=true -o Acquire::https::No-Cache=true"

# Apply optional kiosk customization overlay from repo.
if [[ -d "${REPO_WIN_PATH}/kiosk/live-build" ]]; then
  rsync -a "${REPO_WIN_PATH}/kiosk/live-build/" config/
  chmod +x config/hooks/normal/*.hook.chroot || true
  chmod +x config/includes.chroot/usr/local/bin/*.sh || true
fi

echo "[hnh-kiosk] Building ISO (this may take a while)..."
sudo lb build

ISO_PATH="${BUILD_ROOT}/live-image-amd64.hybrid.iso"
if [[ ! -f "${ISO_PATH}" ]]; then
  echo "[hnh-kiosk] ERROR: ISO not produced at ${ISO_PATH}" >&2
  exit 1
fi

mkdir -p "${DIST_OUT}"
cp -f "${ISO_PATH}" "${DIST_OUT}/hnh-kiosk-base.iso"

echo "[hnh-kiosk] SUCCESS"
echo "[hnh-kiosk] ISO copied to: ${DIST_OUT}/hnh-kiosk-base.iso"
