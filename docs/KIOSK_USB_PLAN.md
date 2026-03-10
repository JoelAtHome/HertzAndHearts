# Linux USB Kiosk Concept (Feasibility Notes)

## Short Answer

Yes, a Linux-based kiosk build launched from USB is feasible and a good fit for controlled/demo environments.

For a repeatable WSL-based base ISO build path, see `docs/BUILD_KIOSK_ISO.md`.

## Recommended Architecture

- Base OS: Ubuntu LTS (or Debian stable) with minimal desktop session.
- App launch mode: autostart Hertz & Hearts in fullscreen kiosk mode.
- Data path: store sessions on persistent partition or second USB partition.
- Update model: immutable app image + explicit update process (do not auto-update in kiosk sessions).

## Practical USB Strategy

- Use a USB image with:
  - bootable Linux partition
  - persistent data partition (`/data/hnh_sessions`)
- Run app with a wrapper script that:
  - checks Bluetooth availability
  - mounts data partition
  - starts app
  - writes logs to data partition

## Hardware Notes

- Prefer hardware with known BLE stability.
- Disable aggressive power saving for Bluetooth adapter.
- Keep USB storage quality high (industrial/endurance flash preferred).

## UX Notes

- Keep kiosk UI minimal:
  - Start session
  - Stop/Save
  - History/Replay
  - Generate report
- Hide advanced settings behind admin unlock.
- Add a visible "research use only" banner on startup.

## Risk Areas To Validate Early

- BLE reconnect behavior after suspend/wake.
- Filesystem reliability after unclean power removal.
- Startup time consistency and sensor pairing persistence.
- Printer/export behavior in offline mode.

## Pilot Plan

1. Build a proof-of-concept USB image for one hardware profile.
2. Run 20+ repeated session cycles with forced disconnect/reconnect tests.
3. Validate artifact integrity (CSV, manifest, reports) after each run.
4. Add watchdog + auto-restart for app crash recovery.
5. Expand to second hardware profile only after pass criteria are met.
