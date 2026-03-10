# Build Kiosk ISO (WSL-Friendly)

This guide builds a base Ubuntu live ISO for kiosk use while avoiding the `/mnt/c` live-build failure mode.

## Why This Method

`live-build` is unreliable on Windows-mounted paths (`/mnt/c/...`) due to file/permission semantics.

Use the provided script, which builds in Linux-native storage (`~/hnh-kiosk-build`) and copies the ISO back to your repo `dist` folder.

## Prerequisites

- WSL2 Ubuntu installed and working
- Repo available at `/mnt/c/Users/<you>/Hertz-and-Hearts`

## One-Time Setup

Open Ubuntu (WSL) and run:

```bash
cd /mnt/c/Users/joelb/Hertz-and-Hearts
chmod +x scripts/build_kiosk_iso.sh
```

Optional first-run dependency install:

```bash
bash scripts/build_kiosk_iso.sh --install-deps
```

## Build Command

```bash
cd /mnt/c/Users/joelb/Hertz-and-Hearts
bash scripts/build_kiosk_iso.sh
```

WSL "one-command rebuild" option:

```bash
cd /mnt/c/Users/joelb/Hertz-and-Hearts
bash scripts/wsl_rebuild_kiosk_iso.sh
```

Expected output:

- `dist/hnh-kiosk-base-<version>.iso`

For current beta it should look like:

- `dist/hnh-kiosk-base-1.0.0-beta.iso`

## Included Kiosk Customizations

When present, files under `kiosk/live-build/` are overlaid into the live-build config.
Current overlay includes:

- desktop autostart entry for `hnh-kiosk-launch.sh`
- launcher wrapper at `/usr/local/bin/hnh-kiosk-launch.sh`
- writable path prep (`/var/lib/hnh`, `/var/log/hnh`)

Note: launcher expects Hertz & Hearts to be available in the image (`hnh` command or `python3 -m hnh.app`).

## Optional Overrides

You can override build parameters:

```bash
HNH_DISTRO=noble \
HNH_ARCH=amd64 \
HNH_MIRROR=https://mirrors.edge.kernel.org/ubuntu \
bash scripts/build_kiosk_iso.sh
```

## Troubleshooting

- **`No config/ directory`**: the script handles config automatically; run the script directly.
- **Hash mismatch**: wait 10-20 minutes and retry, or switch mirror via `HNH_MIRROR`.
- **`tar failed` or chroot oddities**: ensure build is running via the script (Linux-native build root).

## Next Step

After base ISO builds, add kiosk customization (autologin/autostart/app launcher/internal write paths) using:

- `docs/KIOSK_USB_PLAN.md`
- `docs/KIOSK_STORAGE_LAYOUT.md`

## CI Fallback (Recommended If Local Mirrors Are Flaky)

If WSL/local builds fail due to repeated apt hash/mirror mismatches, use the GitHub workflow:

- `.github/workflows/kiosk-iso.yml`

How to run:

1. Push current branch to GitHub.
2. Open Actions -> `kiosk-iso`.
3. Click **Run workflow**.
4. Download artifact: `hnh-kiosk-base.iso`.
