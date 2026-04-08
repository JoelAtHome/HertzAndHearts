# Changelog

### Unreleased
### Version 1.0.0-beta.2 (April 08 2026)
+ docs: Added dedicated Phone Bridge release notes at `Android Bridge App/CHANGELOG.md`.
+ enhancement: Added Session Integrity Audit admin utility (`More -> Session Integrity Audit...`) to scan DB history vs manifests, report missing/mismatched rows, repair index drift, and fill missing trend rows from manifests.
+ enhancement: Added duplicate session-folder resolution workflow to choose which copy to keep and remove other disk locations, then upsert the kept manifest into session history.
+ enhancement: Improved profile naming rules and prompts to enforce filesystem-safe display names with actionable suggestions before create/rename.
+ enhancement: Updated profile manager delete flow to stage profiles as `Pending delete` until `Save & Close`, with cancel-safe rollback behavior.
+ enhancement: Improved session-history and reassign tables with left-click open behavior, folder-path context menus, and hover/cursor affordances.
+ test: Added tests for profile display-name validation and session-folder slug behavior (`test/test_session_artifacts.py`).
+ test: Added coverage for filling missing trend rows from `session_manifest.json` (`test/test_profile_store.py`).
+ docs: Added `Android Bridge App/Android Dev Workflow.txt` for USB-debug deployment workflow notes.

### Version 1.0.0-beta.1
+ release: Bumped pre-release version to `1.0.0b1` (public label: `1.0.0-beta.1`); aligned Polar H10 Bridge and Windows installer metadata.
+ docs: Extended `docs/USER_GUIDE.md` with Tier 1 morning baseline protocol, Session Trends / Compare / Tag Insights, and RMSSD recovery zones.
+ enhancement: Tier 1 trend guidance—morning baseline protocol (checkbox, in-session banner, `session_manifest.json` → `trend_guidance.morning_baseline_protocol`), RMSSD recovery zone strip under Session Trends with configurable baseline window and “Why these zones?” explainer (`hnh/view.py`; prefs `tier1_morning_baseline_protocol`, `tier1_recovery_baseline_sessions`).

### Version 1.0.0-beta
+ release: Set project pre-release version to `1.0.0b0` (public label: `1.0.0-beta`) and added beta launch collateral/templates.
+ enhancement: Added in-app Support Development flow under More menu with two donation methods (GitHub Sponsors and Buy Me a Coffee), including profile-aware post-session prompts and guest-safe behavior.
+ enhancement: Added a richer support dialog with clickable links and QR display support (with graceful fallback when QR generation is unavailable).
+ enhancement: Added settings scope controls (`[Global]` vs `[Profile]`) and profile-only settings filter in Settings UI.
+ enhancement: Added GitHub issue templates for bug reports and feature requests.
+ enhancement: Added funding configuration and README support/reporting links.
+ maintenance: Marked `.app-startup.lock` as ignored runtime lock artifact.
+ maintenance: Removed the kiosk path after the approach failed.

### Version 1.1.1 (December 19 2025)
+ enhancement: Bumped PySide6 to version 6.10.

### Version 1.1.0 (December 15 2024)
+ enhancement: Computing HRV as exponentially weighted moving average (https://en.wikipedia.org/wiki/Exponential_smoothing).
+ enhancement: Accepting Decathlon HR sensor (thanks S73ph4n).

### Version 1.0.1 (November 30 2024)
+ enhancement: Relaxed Python version constraints.
+ enhancement: Bumped PySide6 to version 6.8.
+ enhancement: Bumped Python to version 3.12.
+ bugfix: Improved sensor UUID validation (thanks Mirkan Çalışkan (mirkancal)).

### Version 1.0.0 (April 29 2024)
+ enhancement: Added docs on building macOS with PyInstaller in order to deal with Bluetooth permissions (thanks cyclemaxwell).
+ enhancement: Show version in GUI.
+ enhancement: Removed PyQtGraph and NumPy dependencies.
+ enhancement: Bumped PySide6 to version 6.7.0.
+ enhancement: Bumped Python to version 3.11.

### Version 0.2.0 (April 23, 2022)
+ enhancement: Removed recording of Redis channels (removed Redis dependency).
+ enhancement: Handling Bluetooth connection with QtBluetooth instead of bleak (removed bleak dependency).

### Version 0.1.3 (January 08, 2022)
+ enhancement: Improved Bluetooth connection (thanks Marc Schlaich (schlamar)).
+ bugfix: No more connection attempt with empty address menu.

### Version 0.1.2 (May 18, 2021)
+ enhancement: Local HRV is now averaged over a fixed window of 15 seconds. Removed slider for HRV mean window size.
+ enhancement: Status messages on application state are now displayed in the GUI.
+ enhancement: Added recording- and Redis interface features (undocumented at time of release).
+ enhancement: Rejecting some artifacts in inter-beat-intervals as well as local HRV.
+ bugfix: Made validation of sensor addresses platform-specific (thanks Alexander Weuthen (alexweuthen)).

### Version 0.1.1 (January 13, 2021)
+ enhancement: Visibility of breathing pacer can be toggled.
+ enhancement: Made range of breathing pacer rates more granular (step size .5 instead of 1).

### Version 0.1.0 (January 07, 2021)
+ enhancement: Initial release.
