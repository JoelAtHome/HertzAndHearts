# Public Release Go/No-Go Checklist

Use this checklist before publishing a public build.

## 1) Core Functionality (Must Pass)

- [ ] Start a session with a real sensor and confirm live HR/RMSSD updates.
- [ ] Stop a session (`Stop`) and confirm `session.csv` + `session_manifest.json` are present.
- [ ] Finalize a session (`Stop & Save`) and confirm `session_report.docx` + `session_share.pdf` are generated.
- [ ] Open `More -> History / Session Replay`, select a past session, and click `Generate report`.
- [ ] Confirm rebuilt report artifacts are written into that session folder without needing an active session.

## 2) Data Integrity and Regression (Must Pass)

- [ ] Confirm IBI diagnostics stay 1:1 (`beats_received == buffer_updates`) during normal streaming.
- [ ] Verify reconnect path preserves chart history and shows an explicit timeline gap.
- [ ] Verify disconnect/reconnect does not crash, freeze, or corrupt session files.
- [ ] Confirm hidden/unhidden sessions still load correctly in History and Trends.

## 3) QTc Safety and Reporting (Must Pass)

- [ ] Validate QTc unavailable behavior on low-quality/noisy data (`status=unavailable`, clear reason).
- [ ] Validate stable QTc summary on repeat runs of the same replay/noisy session.
- [ ] Confirm report includes `QTc method guidance` with non-diagnostic wording.
- [ ] Confirm report still renders when QTc is unavailable.

## 4) Public-Facing Quality (Should Pass)

- [ ] Review in-app wording for non-diagnostic guardrails and disclaimer consistency.
- [ ] Verify no obviously confusing controls were added to primary workflow screens.
- [ ] Confirm `README.md` quickstart/install steps work on a clean machine.
- [ ] Confirm support links and optional donation prompt behavior (including suppression options).

## 5) Packaging and Release Hygiene (Must Pass)

- [ ] Run automated tests: `python -m pytest`.
- [ ] Build/package using your release workflow and launch the packaged app.
- [ ] Verify app version and changelog entries are aligned.
- [ ] Perform one smoke run in packaged app: connect -> record -> stop/save -> history replay/report.
- [ ] Archive release artifacts and checksums in your release notes.

## Go/No-Go Rule

Release only if all **Must Pass** items are complete.  
If any **Must Pass** item fails, mark **No-Go**, fix, and rerun this checklist.
