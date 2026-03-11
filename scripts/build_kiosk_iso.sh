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
  sudo apt install -y xorriso squashfs-tools syslinux syslinux-utils isolinux live-build wget curl git rsync
fi

if ! command -v isohybrid >/dev/null 2>&1; then
  if command -v isohybrid.pl >/dev/null 2>&1; then
    sudo ln -sf "$(command -v isohybrid.pl)" /usr/bin/isohybrid
  else
    sudo tee /usr/bin/isohybrid >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "[kiosk-iso] WARN: isohybrid binary unavailable; skipping legacy post-process." >&2
exit 0
EOF
    sudo chmod +x /usr/bin/isohybrid
  fi
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
  --binary-images "iso,hdd" \
  --bootloader grub-efi \
  --archive-areas "main restricted universe multiverse" \
  --mirror-bootstrap "${HNH_MIRROR}" \
  --mirror-binary "${HNH_MIRROR}" \
  --mirror-chroot-security "${HNH_MIRROR}" \
  --debian-installer false \
  --source false \
  --apt-source-archives false \
  --apt-options "--yes -o Acquire::Retries=20 -o Acquire::By-Hash=yes -o Acquire::Languages=none -o Acquire::http::Timeout=90 -o Acquire::https::Timeout=90 -o Acquire::http::No-Cache=true -o Acquire::https::No-Cache=true"
# Some live-build variants still execute lb_source despite --source false.
# Force-disable source image generation in config as a hard override.
printf '%s\n' 'LB_SOURCE="false"' 'LB_SOURCE_IMAGES="none"' >> config/source

echo "[kiosk-iso] Starting build (this can take a while)..."
sudo lb binary

ISO_PATH=""
for CANDIDATE in "${BUILD_ROOT}/binary.iso" "${BUILD_ROOT}/live-image-${HNH_ARCH}.iso" "${BUILD_ROOT}/live-image-${HNH_ARCH}.hybrid.iso"; do
  if [[ -f "${CANDIDATE}" ]]; then
    ISO_PATH="${CANDIDATE}"
    break
  fi
done
IMG_PATH=""
for CANDIDATE in "${BUILD_ROOT}/binary.img" "${BUILD_ROOT}/live-image-${HNH_ARCH}.img"; do
  if [[ -f "${CANDIDATE}" ]]; then
    IMG_PATH="${CANDIDATE}"
    break
  fi
done
if [[ -z "${ISO_PATH}" && -z "${IMG_PATH}" ]]; then
  echo "[kiosk-iso] Build completed but no ISO/IMG output was found." >&2
  exit 1
fi

OUT_DIR="${REPO_ROOT}/dist"
mkdir -p "${OUT_DIR}"
if [[ -n "${ISO_PATH}" ]]; then
  OUT_ISO="${OUT_DIR}/hnh-kiosk-base-${PROJECT_VERSION}.iso"
  cp -f "${ISO_PATH}" "${OUT_ISO}"
  if command -v xorriso >/dev/null 2>&1; then
    TMP_USB_ISO="${OUT_ISO%.iso}.usb.iso"
    if xorriso -indev "${OUT_ISO}" -outdev "${TMP_USB_ISO}" -boot_image any replay -boot_image any partition_table=on; then
      mv -f "${TMP_USB_ISO}" "${OUT_ISO}"
    else
      echo "[kiosk-iso] WARN: xorriso replay could not add partition table metadata."
      rm -f "${TMP_USB_ISO}"
    fi
  fi
  file "${OUT_ISO}"
  fdisk -l "${OUT_ISO}" || true
  sha256sum "${OUT_ISO}" > "${OUT_ISO}.sha256"
fi
if [[ -n "${IMG_PATH}" ]]; then
  OUT_IMG="${OUT_DIR}/hnh-kiosk-base-${PROJECT_VERSION}.img"
  cp -f "${IMG_PATH}" "${OUT_IMG}"
  file "${OUT_IMG}"
  fdisk -l "${OUT_IMG}" || true
  sha256sum "${OUT_IMG}" > "${OUT_IMG}.sha256"
fi

echo "[kiosk-iso] Done."
if [[ -n "${ISO_PATH}" ]]; then
  echo "[kiosk-iso] Output ISO: ${OUT_ISO}"
fi
if [[ -n "${IMG_PATH}" ]]; then
  echo "[kiosk-iso] Output IMG: ${OUT_IMG}"
fi
