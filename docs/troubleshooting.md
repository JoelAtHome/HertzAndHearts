# Troubleshooting

## Sensor connection issues

If you have trouble connecting (or staying connected) to a supported chest strap:

- Turn Bluetooth off and on again.
- Unpair and re-pair the sensor in OS Bluetooth settings.
- Make sure no other app is already connected to the sensor.
- Reset the sensor if needed: https://support.polar.com/en/support/how_to_reset_my_heart_rate_sensor

## Launch/version mismatch

If the app shows an unexpected version in the title bar:

- Open a terminal in the repo root.
- Reinstall editable package:
  - `python -m pip install -e .`
- Launch directly:
  - `python -m hnh.app`

If using the desktop shortcut, ensure `Run-HnH.bat` points to this repository.

## Linux notes

For GUI/runtime dependency requirements, see Qt docs:

- https://doc.qt.io/qt-6/linux-requirements.html
- https://doc.qt.io/qt-6/linux.html

## Packaging and release

If build artifacts are missing on a GitHub release:

- Check Actions runs for `build`.
- Confirm release-upload steps succeeded.
- If needed, manually download workflow artifacts and upload them in the release page.

For full packaging guidance, see `docs/PACKAGING.md`.
