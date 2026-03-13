#!/usr/bin/env bash
set -euo pipefail

# Provision a stock Ubuntu install for Hertz & Hearts kiosk use.
# Run as a normal user with sudo rights (not as root).

if [[ "${EUID}" -eq 0 ]]; then
  echo "[hnh-kiosk] Run this script as a normal user, not root." >&2
  exit 1
fi

HNH_REPO_URL="${HNH_REPO_URL:-https://github.com/JoelAtHome/HertzAndHearts.git}"
HNH_REPO_DIR="${HNH_REPO_DIR:-${HOME}/apps/Hertz-and-Hearts}"
HNH_BRANCH="${HNH_BRANCH:-main}"
HNH_VENV_DIR="${HNH_VENV_DIR:-${HNH_REPO_DIR}/.venv}"
HNH_DATA_ROOT="${HNH_DATA_ROOT:-/var/lib/hnh}"
HNH_LOG_ROOT="${HNH_LOG_ROOT:-/var/log/hnh}"
HNH_LAUNCHER_PATH="${HNH_LAUNCHER_PATH:-${HOME}/.local/bin/hnh-kiosk-launch.sh}"
HNH_AUTOSTART_PATH="${HNH_AUTOSTART_PATH:-${HOME}/.config/autostart/hnh.desktop}"
HNH_APP_MENU_ENTRY_PATH="${HNH_APP_MENU_ENTRY_PATH:-${HOME}/.local/share/applications/hertz-and-hearts.desktop}"

echo "[hnh-kiosk] Installing OS packages..."
sudo apt update
sudo apt install -y \
  git \
  python3 \
  python3-venv \
  python3-pip \
  bluetooth \
  bluez \
  libgl1 \
  libxkbcommon-x11-0 \
  libxcb-cursor0

mkdir -p "$(dirname "${HNH_REPO_DIR}")"
if [[ -d "${HNH_REPO_DIR}/.git" ]]; then
  echo "[hnh-kiosk] Updating existing repo at ${HNH_REPO_DIR}..."
  git -C "${HNH_REPO_DIR}" fetch --all --prune
  git -C "${HNH_REPO_DIR}" checkout "${HNH_BRANCH}"
  git -C "${HNH_REPO_DIR}" pull --ff-only origin "${HNH_BRANCH}"
else
  echo "[hnh-kiosk] Cloning repo to ${HNH_REPO_DIR}..."
  git clone --branch "${HNH_BRANCH}" --depth 1 "${HNH_REPO_URL}" "${HNH_REPO_DIR}"
fi

echo "[hnh-kiosk] Creating virtual environment..."
python3 -m venv "${HNH_VENV_DIR}"
"${HNH_VENV_DIR}/bin/python" -m pip install --upgrade pip
"${HNH_VENV_DIR}/bin/pip" install -e "${HNH_REPO_DIR}"

echo "[hnh-kiosk] Preparing writable data/log paths..."
sudo mkdir -p "${HNH_DATA_ROOT}/sessions" "${HNH_DATA_ROOT}/reports" "${HNH_LOG_ROOT}"
sudo chown -R "${USER}:${USER}" "${HNH_DATA_ROOT}" "${HNH_LOG_ROOT}"

mkdir -p "$(dirname "${HNH_LAUNCHER_PATH}")"
cat > "${HNH_LAUNCHER_PATH}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${HNH_DATA_ROOT}"
LOG_ROOT="${HNH_LOG_ROOT}"
VENV_BIN="${HNH_VENV_DIR}/bin"

mkdir -p "\${DATA_ROOT}/sessions" "\${DATA_ROOT}/reports" "\${LOG_ROOT}" || true

export XDG_CACHE_HOME="/tmp/hnh-cache"
export TMPDIR="/tmp/hnh-tmp"
mkdir -p "\${XDG_CACHE_HOME}" "\${TMPDIR}" || true

# Force Qt to use X11 decorations on Linux to keep dialogs bordered/clear.
export QT_QPA_PLATFORM="\${QT_QPA_PLATFORM:-xcb}"
export QT_QPA_PLATFORMTHEME="\${QT_QPA_PLATFORMTHEME:-gtk3}"

LOCK_FILE="/tmp/hnh-kiosk.lock"
exec 9>"\${LOCK_FILE}"
if ! flock -n 9; then
  exit 0
fi

if [[ -x "\${VENV_BIN}/hnh" ]]; then
  exec "\${VENV_BIN}/hnh"
fi

exec "\${VENV_BIN}/python" -m hnh.app
EOF
chmod +x "${HNH_LAUNCHER_PATH}"

mkdir -p "$(dirname "${HNH_AUTOSTART_PATH}")"
cat > "${HNH_AUTOSTART_PATH}" <<EOF
[Desktop Entry]
Type=Application
Name=Hertz and Hearts Kiosk
Comment=Start Hertz and Hearts in kiosk mode
Exec=${HNH_LAUNCHER_PATH}
Terminal=false
X-GNOME-Autostart-enabled=true
NoDisplay=false
EOF

mkdir -p "$(dirname "${HNH_APP_MENU_ENTRY_PATH}")"
cat > "${HNH_APP_MENU_ENTRY_PATH}" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Hertz and Hearts
Comment=Run Hertz and Hearts
Exec=${HNH_LAUNCHER_PATH}
Terminal=false
Categories=Education;Science;MedicalSoftware;
EOF

echo "[hnh-kiosk] Done."
echo "[hnh-kiosk] Launcher: ${HNH_LAUNCHER_PATH}"
echo "[hnh-kiosk] Autostart file: ${HNH_AUTOSTART_PATH}"
echo "[hnh-kiosk] App menu entry: ${HNH_APP_MENU_ENTRY_PATH}"
echo "[hnh-kiosk] Reboot or log out/in to test autostart."
