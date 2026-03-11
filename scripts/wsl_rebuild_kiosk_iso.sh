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
sudo apt install -y xorriso squashfs-tools syslinux syslinux-utils isolinux live-build wget curl git rsync || true
if ! command -v isohybrid >/dev/null 2>&1; then
  if command -v isohybrid.pl >/dev/null 2>&1; then
    sudo ln -sf "$(command -v isohybrid.pl)" /usr/bin/isohybrid
  else
    sudo tee /usr/bin/isohybrid >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "[hnh-kiosk] WARN: isohybrid binary unavailable; skipping legacy post-process." >&2
exit 0
EOF
    sudo chmod +x /usr/bin/isohybrid
  fi
fi

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
  --binary-images iso \
  --bootloader grub-efi \
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

ISO_PATH=""
for CANDIDATE in "${BUILD_ROOT}/binary.iso" "${BUILD_ROOT}/live-image-amd64.iso" "${BUILD_ROOT}/live-image-amd64.hybrid.iso"; do
  if [[ -f "${CANDIDATE}" ]]; then
    ISO_PATH="${CANDIDATE}"
    break
  fi
done
if [[ -z "${ISO_PATH}" ]]; then
  echo "[hnh-kiosk] ERROR: no ISO output was produced." >&2
  exit 1
fi

mkdir -p "${DIST_OUT}"
cp -f "${ISO_PATH}" "${DIST_OUT}/hnh-kiosk-base.iso"
if command -v xorriso >/dev/null 2>&1; then
  TMP_USB_ISO="${DIST_OUT}/hnh-kiosk-base.usb.iso"
  if xorriso -indev "${DIST_OUT}/hnh-kiosk-base.iso" -outdev "${TMP_USB_ISO}" -boot_image any replay -boot_image any partition_table=on; then
    mv -f "${TMP_USB_ISO}" "${DIST_OUT}/hnh-kiosk-base.iso"
  else
    echo "[hnh-kiosk] WARN: xorriso replay could not add partition table metadata."
    rm -f "${TMP_USB_ISO}"
  fi
fi
file "${DIST_OUT}/hnh-kiosk-base.iso"
fdisk -l "${DIST_OUT}/hnh-kiosk-base.iso" || true
sha256sum "${DIST_OUT}/hnh-kiosk-base.iso" > "${DIST_OUT}/hnh-kiosk-base.iso.sha256"

echo "[hnh-kiosk] SUCCESS"
echo "[hnh-kiosk] ISO copied to: ${DIST_OUT}/hnh-kiosk-base.iso"
