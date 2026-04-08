# Phone Bridge Changelog

This changelog tracks changes specific to the Android Phone Bridge app (`PolarH10Bridge`).

## Unreleased

## Version 1.0.0-beta.2 (April 08 2026)
- enhancement: Added client identity exchange so the bridge can report the active Hertz & Hearts user profile to the phone app.
- enhancement: Improved Wi-Fi address handling and LAN IP selection flow for more reliable host/connection setup.
- enhancement: Added foreground-service keepalive behavior and safer bridge-port change confirmation while a PC session is connected.
- enhancement: Improved BLE reliability and RSSI display behavior (scan-backed updates, UI throttling, dead-code cleanup).
- maintenance: Updated Android bridge CI/release workflow reliability (gradle wrapper executable handling, release lookup retry before APK attach).
- docs: Added an Android Bridge development workflow note (`Android Dev Workflow.txt`) covering USB debugging and deploy-from-Android-Studio steps.

## Version 1.0.0-beta.1
- release: Published `PolarH10Bridge-debug-v1.0.0-beta.1.apk` to GitHub Releases via the Android bridge release workflow.
- maintenance: Aligned APK asset naming with release tag format (`PolarH10Bridge-debug-<tag>.apk`) for predictable install/update guidance.
