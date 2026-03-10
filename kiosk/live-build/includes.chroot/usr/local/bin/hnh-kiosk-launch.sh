#!/usr/bin/env bash
set -euo pipefail

# Kiosk launcher wrapper for Hertz & Hearts.
# Writes are directed to local machine storage, not boot media when possible.

DATA_ROOT="/var/lib/hnh"
LOG_ROOT="/var/log/hnh"

mkdir -p "${DATA_ROOT}/sessions" "${DATA_ROOT}/reports" "${LOG_ROOT}" || true

# Prefer RAM-backed cache/temp to reduce disk churn.
export XDG_CACHE_HOME="/tmp/hnh-cache"
export TMPDIR="/tmp/hnh-tmp"
mkdir -p "${XDG_CACHE_HOME}" "${TMPDIR}" || true

# Optional guard against accidental multi-instance in kiosk profile.
LOCK_FILE="/tmp/hnh-kiosk.lock"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  exit 0
fi

if command -v hnh >/dev/null 2>&1; then
  exec hnh
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 -m hnh.app
fi

exit 1
