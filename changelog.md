# Changelog

### Unreleased
+ enhancement: **Stop & Abandon** (right of Stop & Save) ends the session without a final report after a confirmation; the recording stays in history as abandoned.
+ bugfix: Report HR flat detection only flags near-identical held shelves (~0.15 bpm), so clean resting traces are no longer painted dotted gray.
+ bugfix: Short sessions (< RMSSD/SDNN 60s stabilize) fall back to the base settling cut for those trends instead of a single leftover point.
+ bugfix: Report RMSSD flat detection no longer treats slow <1 ms drifts as held shelves; only near-identical or near-zero plateaus are dotted.

### Version 1.0.0-beta.10 (October 21 2026)
+ release: Bumped pre-release version to `1.0.0b10` (public label: `1.0.0-beta.10`).
+ enhancement: **More → Merge Profiles…** (Admin) merges a duplicate profile into a master name, moves sessions/folders, keeps master settings, then deletes the duplicate.
+ bugfix: Session History / Integrity now attribute folders under a profile’s Session Save Path to that profile when the manifest still names a retired profile (e.g. `Sandy` → `Sandy Koblich`), and prefer the local `session.csv` over stale absolute paths.
+ enhancement: Opening History (and Integrity repair) adopts orphan session folders that have EDF/CSV but no manifest, rebuilding CSV/manifest in place for the owning profile.
+ test: Added coverage for save-path attribution, profile merge, and orphan-folder adoption.

### Version 1.0.0-beta.9 (October 20 2026)
+ release: Bumped pre-release version to `1.0.0b9` (public label: `1.0.0-beta.9`).
+ bugfix: Polar H10 saved-HRV imports no longer append the phone's Feather demo profile name (e.g. "Typical patch torso") to the session annotation.
+ enhancement: Live side metrics group HR/baseline mid upper plot, SDNN·LF/HF·QRS beside the freeze row, and RMSSD·Bridge·baseline mid lower plot, with thin dividers only between those groups.
+ enhancement: Session reports (and imports/replay) clean beat intervals with relative median outlier replacement plus a tighter default noise ceiling (`NOISE_IBI_HIGH_MS` 1800 ms), so Polar contact spikes no longer dent the HR/RMSSD/SDNN trends.
+ enhancement: IBI cleaning also caps beat-to-beat HR jumps vs the rolling median (`MAX_BEAT_HR_DELTA_BPM` 15), so milder H10 contact needles (e.g. 80→64 bpm) no longer skew Low HR while gradual trends stay intact.
+ enhancement: Session report trends mark unreliable spans (disconnects, large gaps, held/flat plateaus including RMSSD≈0) as dotted gray while trusted samples stay solid; report rebuild drops outlier beats instead of median-filling; Min/Max/Avg exclude those spans.
+ bugfix: Report trend gaps no longer draw a solid/dotted bridge that looked like a fake flat shelf; unreliable windows use a light band plus broken dotted segments, and plateau detection uses a rolling value-range window.
+ bugfix: Trend gap breaking now treats the x-axis as minutes, so multi-minute dropouts are left empty instead of being stroked across.
+ cleanup: Report trend unreliable segments no longer paint gray background bands; broken/dotted gray line alone marks poor-quality spans.
+ bugfix: Phone-bridge and file imports save under **Session Save Path [Profile]** (same tree as live Stop & Save), not the app Data Folder.
+ bugfix: Imported phone ECG sessions write `session_ecg.f32` and report rebuild falls back to `session.edf`, so History **Generate report** includes the ECG strip.
+ bugfix: Phone imports compute rolling SDNN from beat intervals (and report rebuild fills SDNN when the CSV has none), so the HRV(SDNN) trend is no longer empty.
+ bugfix: When Phone Bridge is linked to Polar H10 (or any non-Feather source), Feather profile and lead-off banners are suppressed.
+ bugfix: Regenerated phone-import reports trim EDF zero-padded ECG tails and pick a strip with real amplitude, so the ECG plot is no longer a flat line; SDNN is filled from IBIs and outlier-filtered like RMSSD.
+ bugfix: Session CSV loaders honor each RMSSD/SDNN row's own elapsed time when metric rows are written after all IBIs (phone imports), so trend plots are no longer collapsed to a single x position.

### Version 1.0.0-beta.8 (October 19 2026)
+ release: Bumped pre-release version to `1.0.0b8` (public label: `1.0.0-beta.8`).
+ enhancement: ECG live view uses classic sweep/clear redraw (fixed X page, draw L→R, then restart) at a 3–5 s default strip.
+ enhancement: ECG monitor has plain **Freeze** (hold current zoom, pan/zoom, no cursors) plus **Freeze 1 Cycle** for measurement zoom+cursors.
+ cleanup: Removed ECG **Relock** (no longer synced to the main plot after sweep mode; Resume/Reset return to live).
+ bugfix: ECG live zoom no longer inherits the ~30 s history buffer or main-plot span; auto-range is disabled on the strip.
+ docs: ECG Quick Guide updated for Freeze / Freeze 1 Cycle / Reset (no Relock).

### Version 1.0.0-beta.7 (October 18 2026)
+ release: Bumped pre-release version to `1.0.0b7` (public label: `1.0.0-beta.7`).
+ bugfix: Phone-bridge imports plot a rolling RMSSD from the saved beat intervals. The phone's single RMSSD stays a labeled summary. Replay, reports, and Trends use that rolling series for sessions already imported, without rewriting their CSV or EDF files.
+ bugfix: Session replay builds heart rate from the saved beat intervals with the live chart's artifact rules and exponential smooth, for both streamed sessions and phone recordings.
+ bugfix: Session replay draws the ECG through a 0.5 Hz high-pass so electrode drift does not shift the baseline. The saved waveform stays raw.
+ enhancement: Saved phone ECG chunks may arrive as int32 microvolts (`int32_uv_b64`) so offsets past ±32.8 mV are kept. Existing int16 packages still load.

### Version 1.0.0-beta.6 (September 26 2026)
+ release: Bumped pre-release version to `1.0.0b6` (public label: `1.0.0-beta.6`).
+ enhancement: **More → Saved Phone Recordings…** lists the phone's stored HRV recordings (time, RMSSD, duration, patient, sent/pending) and imports the one you pick. A recording deleted on the phone is dropped and the list refreshes. Phones that do not advertise `ritual_list` still use **Request saved HRV**. Connect still pulls the newest unacked package.
+ bugfix: Deleting a phone recording from Session History clears its import link, so picking it again from **Saved Phone Recordings** adds a new history row.
+ enhancement: The Select Session User dialog gives the profile name more room.
+ bugfix: Imported phone recordings store the PC's local time instead of the UTC clock that was shown in Session History.
+ enhancement: Session reports show research reference ranges beside the core metrics.
+ bugfix: ECG and QTc use the phone sample rate so Feather and Polar H10 stay on the correct time base.
+ enhancement: CI publishes a Linux AppImage built on Ubuntu 22.04.
+ bugfix: Frozen Linux builds can save the Word session report. python-docx templates are bundled, and the frozen app can open them.
+ bugfix: The Linux main window keeps its title-bar buttons when it opens maximized.

### Version 1.0.0-beta.5 (September 21 2026)
+ release: Bumped pre-release version to `1.0.0b5` (public label: `1.0.0-beta.5`).
+ bugfix: Feather lead-off no longer looks like a dropped phone link. While electrodes are off, Hertz & Hearts keeps the Check electrodes banner and the phone socket instead of declaring “No data” and resetting the stream.
+ bugfix: A quiet phone link is not closed after ~15s with no Feather samples. While the phone socket is still connected, Hertz & Hearts keeps the session (same as VNS-TA during lead-off) instead of treating the pause as “No data” or a dropped link. Phone `ping` lines also refresh that clock.
+ bugfix: Session Overview keeps the last ECG sensor (`Feather ECG-Box` or `Polar H10`) after the phone link drops. The name is frozen on the open session the first time `source_device` arrives, including on live `rr` / `ecg` lines.
+ bugfix: Phone Bridge Scan no longer opens a second TCP connection to the phone you are already linked to (that was closing Hertz & Hearts with “remote closed connection”).
+ bugfix: Phone Bridge link sends a small ping every 10s so an idle Wi-Fi path does not drop the session after about a minute.

### Version 1.0.0-beta.4 (September 19 2026)
+ release: Bumped pre-release version to `1.0.0b4` (public label: `1.0.0-beta.4`).
+ enhancement: Stream session ECG to `session_ecg.f32` during recording and write true-rate EDF+ (pad/truncate only — no stretch-resample of a short buffer).
+ enhancement: Session History **Delete selected…** (confirm → history + folder); **Replay selected** loads/cues Replay; shared Replay **time zoom/pan** with **Fit time**.
+ enhancement: More menu splits **Session History…** / **Session Replay…** (same tabbed window); Legal Disclaimer moved under More → Help.
+ enhancement: Session Integrity Audit lists labeled scan roots (incl. per-profile Session Save Path) and supports **Add folder to scan…**.
+ bugfix: Phone discovery status no longer urges Connect when already linked, and sticky Feather mismatch banners are not overwritten by scan status noise.
+ enhancement: ECG Log Δt saves capped plot snippets (`ecg_cursor_capture_*.png`, newest 5) into the session folder/manifest and embeds them in the Word report **ECG Cursor Captures** section.
+ enhancement: Toolbar end-state `More ▾` + Settings gear (⚙); About moved under Help; Settings removed from More (Ctrl+, unchanged).
+ enhancement: ECG/QTc Relock stays visible while frozen with dynamic tooltips (locked / manual / resume+relock).
+ docs: Help-facing User Guide and Troubleshooting copy no longer mentions Bluetooth/BLE; connection guidance is Phone Bridge / Wi‑Fi only.
+ enhancement: Contextual Help — typed topic registry (`hnh/help_content.py`), F1 on main/ECG/QTc/Poincaré/PSD/Trends/History/Settings, More → Help → User Guide + Quick Start Guide + Troubleshooting, ECG `i` / Waveform Primer, ECG primer markdown; QTc/Poincaré/PSD info dialogs share the same topics.
+ enhancement: Session reports (docx + one-page PDF) include **ECG Sensor** (typically `Feather ECG-Box` or `Polar H10`), taken from phone-bridge `source_device` / session manifest.
+ enhancement: Phone Bridge Feather lead-off — parse `use_leads_off` / `leads_off` on `status` NDJSON and show a sticky **Check electrodes** banner when both are true (clears on reconnect/clear status).
+ enhancement: Startup and Legal Disclaimer show a readable in-app scrollable text view (markdown source rendered; no raw `.md` / external file open).
+ enhancement: More → About links to [J. Kobe Labs](https://jkobelabs.com).
+ enhancement: Removed post-session donation nag and in-app Buy Me a Coffee; More → Support Development keeps optional GitHub Sponsors only.
+ bugfix: Background phone saved-HRV pull no longer shows “Receiving saved HRV…” on the status bar (was misleading at connect / new session start).
+ enhancement: Moved **Show SDNN** beside **Reset Baseline** so the toggle is easier to find.
+ enhancement: When SDNN plotting is off, the lower chart keeps a blank right-axis spacer so it stays the same width as the HR chart.
+ enhancement: Phone Scan probes the last 4 successful bridge IPs first (plus typed host), matching VNS-TA; stores MRU list in `~/.hnh_last_phone_bridge.json`.
+ enhancement: Lower-chart **Show SDNN** checkbox (per-profile) toggles the SDNN trace and right axis without stopping RMSSD or side-panel SDNN values.
+ enhancement: **Restart (no save)** discards the active recording (closes CSV, deletes session folder/history row), resets charts/baselines, and auto-starts a fresh session while still connected.
+ enhancement: Phone Bridge β.59+ Feather profile hint — re-send `client_info` on every active profile change (`pc_user` = subject name); show Feather soft-match `status` lines as a non-blocking banner (Keep/Switch stays on the phone).
+ bugfix: Opening the ECG window now paints the buffered trace immediately and keeps it aligned with the main timeline, instead of showing a blank strip until the next packet.
+ bugfix: Phone Bridge socket errors and refused connects now tear the TCP client down instead of leaving a zombie socket that disabled both Connect and Disconnect.
+ bugfix: Phone Bridge NDJSON drain now isolates handler exceptions and yields the event loop, so a bad ECG frame cannot freeze HR plotting or block reconnect.
+ bugfix: A second HnH launch now warns and exits instead of opening another window that cannot take over the phone's single TCP slot.
+ enhancement: Phone Bridge Connect timeout now tells you to reopen the phone app when the phone is still holding the last PC session.
+ test: Added Phone Bridge reconnect and NDJSON drain coverage (`test/test_phone_bridge_client.py`).

### Version 1.0.0-beta.3 (September 11 2026)
+ release: Bumped pre-release version to `1.0.0b3` (public label: `1.0.0-beta.3`).
+ enhancement: Phone Bridge is the only toolbar connection path. A saved `PC BLE` preference is rewritten so it cannot reconnect on its own. Direct PC BLE code remains in the repo, unused.
+ enhancement: Removed the PC breathing pacer. The patient pacer stays on the phone.
+ enhancement: Side column now shows baseline HR and baseline RMSSD with the live indicators, vertically centered.
+ enhancement: Official phone `rmssd` snapshots appear as **Bridge RMSSD** (cross-check only; live PC RMSSD is unchanged). Unknown bridge message types are still ignored.
+ docs: Documented Windows as the development and test platform; Linux and macOS remain available as best-effort builds.
+ bugfix: Update check now compares GitHub releases against the same version shown in the window title, so the app no longer offers an "upgrade" to the release it is already running.
+ bugfix: Frozen desktop builds now ship their version metadata; previously they reported a dev placeholder version to the update check and the About dialog.
+ test: Added update-check version comparison coverage (`test/test_update_check.py`).

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
