# Troubleshooting

## Phone Bridge connection issues

Hertz & Hearts connects to the sensor only through the **Android Phone Bridge** over Wi‑Fi (not a direct PC sensor link).

If Scan/Connect fails, or the live stream drops:

- Confirm the phone and PC are on the **same Wi‑Fi** network (guest/isolation networks often block device-to-device traffic).
- On the phone, open the bridge app and confirm it is running and showing a sensor connection.
- In Hertz & Hearts, click `Disconnect`, then `Scan` (or re-enter the phone IP and port, default `8765`), then `Connect`.
- If Connect times out, fully close and reopen the bridge app on the phone (the phone may still be holding the previous PC session), then try again.
- Optional: in the phone app `Connection settings`, enable `Keep bridge active in background`, and disable battery optimization for the bridge app.
- Strap/electrode contact problems usually show up as noisy or missing data after Connect succeeds — reseat the strap or check electrodes on the phone side, then continue the session.

If you need to reset a Polar strap hardware-side, Polar’s reset guide is here:  
https://support.polar.com/en/support/how_to_reset_my_heart_rate_sensor

For phone setup and message format detail, see `docs/PHONE_BRIDGE_QUICKSTART.md`.

## Launch/version mismatch

If the app shows an unexpected version in the title bar:

- Open a terminal in the repo root.
- Reinstall editable package:
  - `python -m pip install -e .`
- Launch directly:
  - `python -m hnh.app`

If using the desktop shortcut, ensure `Run-HnH.bat` points to this repository.

## Linux notes

Linux is a **best-effort** platform: builds remain available, but Linux-specific issues may not be fixed.

### Linux AppImage

`Hertz-and-Hearts-Linux.AppImage` is the generic Linux binary (x86_64), built on **Ubuntu 22.04**.

```
chmod +x Hertz-and-Hearts-Linux.AppImage
./Hertz-and-Hearts-Linux.AppImage
```

The AppImage needs host glibc **≥ 2.35** (Ubuntu 22.04+, Debian 12, and most current desktops). If it fails with a FUSE message, install `libfuse2` (Ubuntu 22.04 / Debian 12) or `libfuse2t64` (Ubuntu 24.04+). You can also extract and run without FUSE:

```
./Hertz-and-Hearts-Linux.AppImage --appimage-extract
./squashfs-root/AppRun
```

For GUI/runtime dependency requirements, see Qt docs:

- https://doc.qt.io/qt-6/linux-requirements.html
- https://doc.qt.io/qt-6/linux.html

## Packaging and release

If build artifacts are missing on a GitHub release:

- Check Actions runs for `build`.
- Confirm release-upload steps succeeded.
- If needed, manually download workflow artifacts and upload them in the release page.

For full packaging guidance, see `docs/PACKAGING.md`.
