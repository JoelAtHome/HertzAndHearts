# Linux Kiosk Storage Layout (USB Boot, Local Write Paths)

This guide shows a practical setup to avoid heavy write cycles on the boot USB.

## Design Goal

- Boot from USB image (mostly read-only)
- Run app normally
- Persist session/log data to internal PC disk (preferred) or dedicated data disk
- Minimize writes to boot USB

## Recommended Layout

- Boot media: USB (OS + app image)
- Persistent data: internal disk partition mounted at `/var/lib/hnh`
- Logs: `/var/log/hnh` on internal disk
- Temp/runtime scratch: `tmpfs` (RAM) where practical

## Directory Plan

Create these directories:

- `/var/lib/hnh/sessions`
- `/var/lib/hnh/reports`
- `/var/log/hnh`
- `/etc/hnh`

Give kiosk user ownership:

```bash
sudo mkdir -p /var/lib/hnh/sessions /var/lib/hnh/reports /var/log/hnh /etc/hnh
sudo chown -R hnhkiosk:hnhkiosk /var/lib/hnh /var/log/hnh
```

## fstab Example

Assume internal partition UUID is `1234-ABCD`:

```fstab
# Internal data partition for Hertz & Hearts writable data
UUID=1234-ABCD  /var/lib/hnh  ext4  defaults,noatime,commit=30  0  2

# Keep /tmp in RAM to reduce flash writes
tmpfs           /tmp          tmpfs defaults,nosuid,nodev,size=512M,mode=1777 0 0
```

Notes:

- `noatime` reduces metadata writes.
- `commit=30` batches journal commits (trade-off: up to ~30s recent data risk on sudden power loss).

## App Session Save Path

Set app session save destination to:

- `/var/lib/hnh/sessions`

If reports are separated by workflow:

- `/var/lib/hnh/reports`

## Kiosk Launch Script

Create `/usr/local/bin/hnh-kiosk-launch.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="/var/lib/hnh"
LOG_ROOT="/var/log/hnh"

mkdir -p "${DATA_ROOT}/sessions" "${DATA_ROOT}/reports" "${LOG_ROOT}"

# Optional: force app cache/temp into RAM-backed paths.
export XDG_CACHE_HOME="/tmp/hnh-cache"
export TMPDIR="/tmp/hnh-tmp"
mkdir -p "${XDG_CACHE_HOME}" "${TMPDIR}"

# Optional lock to prevent accidental multi-instance in kiosk profile.
LOCK_FILE="/tmp/hnh-kiosk.lock"
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

# Launch app
exec /opt/hnh/Hertz-and-Hearts
```

Make executable:

```bash
sudo chmod +x /usr/local/bin/hnh-kiosk-launch.sh
```

## systemd User Autostart (Kiosk)

Create `~/.config/systemd/user/hnh-kiosk.service` for kiosk user:

```ini
[Unit]
Description=Hertz and Hearts Kiosk
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/local/bin/hnh-kiosk-launch.sh
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
```

Enable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hnh-kiosk.service
```

## If No Internal Disk Is Available

Fallback options:

1. Use second USB dedicated for data (not the boot USB)
2. Use high-endurance industrial flash media
3. Keep write paths separated and rotate/compress logs aggressively

## Operational Safeguards

- Add periodic integrity checks for session artifacts.
- Keep watchdog restart enabled.
- Use UPS or clean shutdown procedure when possible.
- Back up `/var/lib/hnh` regularly.

## Validation Checklist (Storage-Specific)

- Boot USB remains mostly read-only during normal use.
- Session files write only to `/var/lib/hnh/sessions`.
- Reboot preserves all session/report artifacts.
- Removing boot USB write pressure does not affect app behavior.
