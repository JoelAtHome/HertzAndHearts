<img src="docs/logo.png" width="125" height="125" />

# Hertz & Hearts

Desktop HRV biofeedback app for ECG chest straps.  
Current beta: **1.0.0-beta**.

**Research use only. Not for clinical diagnosis or treatment.**

## Start Here

- Install from source:
  - `pip install .`
- Launch:
  - `hnh`
  - or `python -m hnh.app`
- Pair your sensor in OS Bluetooth settings, then in-app:
  - `Scan` -> select sensor -> `Connect`
- Start a session:
  - `Start New` -> record -> `Stop` or `Stop & Save`

For full walkthrough:
- `docs/USER_GUIDE.md`

For troubleshooting:
- `docs/troubleshooting.md`

## Downloads

- Prebuilt artifacts are published in GitHub Releases:
  - https://github.com/JoelAtHome/Hertz-and-Hearts/releases

## Compatible Sensors

- Polar H7, H9, H10
- Decathlon Dual HR (model ZT26D)

## Beta Testing

- Tester announcement: `docs/BETA_ANNOUNCEMENT.md`
- Tester instructions: `docs/BETA_TESTER_INSTRUCTIONS.md`
- Public release checklist: `docs/PUBLIC_RELEASE_CHECKLIST.md`
- BLE platform matrix: `docs/BLE_PLATFORM_VALIDATION_MATRIX.md`

## Packaging and Kiosk

- Cross-platform packaging: `docs/PACKAGING.md`
- Build kiosk ISO (WSL + CI): `docs/BUILD_KIOSK_ISO.md`
- Kiosk architecture notes: `docs/KIOSK_USB_PLAN.md`
- Kiosk storage layout: `docs/KIOSK_STORAGE_LAYOUT.md`

## Screenshots and Example Report Assets

- Suggested screenshot/report capture plan: `docs/SCREENSHOT_AND_REPORT_ASSETS.md`

### Quick Tour (Add Images Here)

Add screenshots using these file names, then they will render in README:

- `docs/assets/app/01_main_dashboard.png`
- `docs/assets/app/02_session_history_replay.png`
- `docs/assets/app/03_trends_compare.png`
- `docs/assets/app/04_qtc_window.png`
- `docs/assets/reports/01_one_page_report.png`

Recommended captions are in `docs/assets/CAPTIONS.md`.

## Upstream Acknowledgment

Hertz & Hearts is built upon OpenHRV by Jan C. Brammer.

- Upstream project: https://github.com/JanCBrammer/OpenHRV
- Continuation/fork remains GPL-3.0 licensed.

## License and Disclaimer

- License: GPL-3.0 (`LICENSE`)
- Full research-use disclaimer: `hnh/disclaimer.md`

## Contributing, Support, and Feedback

- Bug reports:
  - https://github.com/JoelAtHome/Hertz-and-Hearts/issues/new?template=bug_report.yml
- Feature requests:
  - https://github.com/JoelAtHome/Hertz-and-Hearts/issues/new?template=feature_request.yml
- Optional support:
  - GitHub Sponsors: https://github.com/sponsors/JoelAtHome
  - Buy Me a Coffee: https://buymeacoffee.com/JoelAtHome

Please search existing issues before filing a new one.
