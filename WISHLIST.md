# Project Wishlist

This file is the single source of truth for feature ideas and improvements.
Keep entries short and actionable so they can be moved through the stages.

## Status Values

- `idea`: captured, not triaged
- `triaged`: reviewed and prioritized
- `planned`: ready for implementation
- `done`: shipped and documented

## Item Template

Copy this block when adding a new item:

```md
### <Short title>
- Problem: <What user/project problem does this solve?>
- Proposed approach: <How we could solve it>
- Effort: <S|M|L>
- Impact: <Low|Med|High>
- Status: <idea|triaged|planned|done>
- Notes: <Optional acceptance criteria, links, constraints>
```

## Intake

Raw ideas go here first.

### Fix Profile Editor button not responding
- Problem: The Profile Editor button has stopped working, preventing users from opening/editing profile details.
- Proposed approach: Reproduce the click path, confirm signal/handler wiring and any state guard conditions, then restore expected open/edit behavior with a focused regression test.
- Effort: S
- Impact: High
- Status: done
- Notes: Fixed by keeping Profiles button in header only, using parent=None and exec() for dialog, explicit refocus with setEnabled(True)/setFocus(), and removing _select_row_by_profile override on auto-save.

### Contextual F1 help consistency across UI
- Problem: Contextual help is currently uneven across windows, which makes discoverability and UX consistency weaker.
- Proposed approach: Define and implement a global F1 help standard so each major window and workflow surface provides contextual guidance (matching style, tone, and depth).
- Effort: M
- Impact: High
- Status: idea
- Notes: Start with QTc, ECG, Poincare, main dashboard, Settings, and History. Include keyboard shortcut behavior, help content template, and acceptance checks for consistency. Complexity guardrail: do not turn help into feature sprawl; use it to simplify defaults and improve discoverability.

### ECG info-page quick link (waveform primer)
- Problem: Users reviewing ECG traces need a fast, in-app path to a reference that explains typical P/QRS/T morphology and interval landmarks.
- Proposed approach: Add an explicit link/button in ECG window (and/or F1 help) that opens a curated info page on normal waveform components and common variants.
- Effort: S
- Impact: Med
- Status: idea
- Notes: Keep wording non-diagnostic and include a disclaimer that morphology interpretation requires clinician judgment.

### Linux PMD mode guidance in Help screens
- Problem: Linux users may not know when to keep PMD mode off for stability versus turning it on for experimental ECG/QTc behavior.
- Proposed approach: Add a short "Linux PMD mode" section to Help/F1 screens (main dashboard + ECG/QTc windows) with clear ON/OFF decision rules and the Settings path.
- Effort: S
- Impact: High
- Status: idea
- Notes: Keep language practical: "OFF for stable HR/RR plotting, ON only when ECG/QTc PMD is needed and stable on this adapter."

### Linux startup BLE prep behavior in Help screens
- Problem: Linux users may not realize the app can run a startup Bluetooth reset/prep step before the main window appears, which can feel like a launch delay unless explained.
- Proposed approach: Add a short Help/F1 note that explains the BLE prep popup, expected wait time, and why scan-first flow is recommended.
- Effort: S
- Impact: Med
- Status: idea
- Notes: Include troubleshooting guidance for "scan sees device but connect fails" and clarify that this startup behavior is Linux-specific.

### Dynamic Relock tooltip for QTc trend window
- Problem: The QTc trend `Relock` button tooltip is static, so users may miss that behavior changes by state (locked vs manual vs frozen/resume path).
- Proposed approach: Mirror ECG tooltip behavior in QTc window with dynamic text updates tied to freeze/manual/relock transitions.
- Effort: S
- Impact: Med
- Status: idea
- Notes: Include explicit wording that relock also resumes streaming when frozen, matching actual button behavior.

### ECG capture snapshots in report
- Problem: Cursor capture annotations are text-only, so measured intervals lose visual context in exported reports.
- Proposed approach: Save a small ECG image snippet at each cursor capture and include it in a dedicated report section with timestamp and Δt metadata.
- Effort: M
- Impact: High
- Status: idea
- Notes: Cap included snapshots per report (e.g., 3-5) to control document size and keep layout readable.

Help content template (per screen):
- Title: `<Screen Name> — Quick Guide`
- Purpose (1 line): What this screen is for.
- How to read/use (3-5 bullets): Core controls/visuals and their meaning.
- Guardrails (1-3 bullets): Key caveats or non-diagnostic warnings where relevant.
- Keyboard shortcuts: Include `F1` and any screen-specific shortcuts.
- Next action (1 line): What users typically do after this screen.

### Complexity guardrail check (anti "Swiss army knife" drift)
- Problem: As capabilities expand, the app can drift into an overly complex experience that weakens usability for primary workflows.
- Proposed approach: Add an explicit complexity review checkpoint for each major feature or release.
- Effort: S
- Impact: High
- Status: idea
- Notes: Keep default workflow simple, use progressive disclosure for advanced tools, and avoid increasing visible controls without strong evidence. Use a feature budget per screen and prioritize one primary user outcome per release.

Complexity review checklist:
- [ ] Does this feature improve the default workflow, or should it be advanced/opt-in?
- [ ] Does this increase visible UI controls on the main screen beyond our feature budget?
- [ ] Can this be merged into an existing interaction pattern instead of introducing a new mode/panel?
- [ ] Is there usage evidence to justify promotion to default visibility?
- [ ] Does this release still have one clearly dominant primary user outcome?

### Generate report from past session (post-stop)
- Problem: Users who end sessions with Stop (not Save) get CSV + manifest but no reports. Once the session is no longer active, there is no way to generate the DOCX/PDF report from the stored data.
- Proposed approach: Add a way to generate reports from past sessions—e.g. via Session History (select session → "Generate report") or a small CLI/script that builds report data from CSV + manifest and writes DOCX/PDF into the session folder.
- Effort: M
- Impact: Med
- Status: done
- Notes: Implemented via Session History action (`Generate report`) that rebuilds report data from saved `session.csv` + `session_manifest.json` and writes DOCX/PDF into the selected session folder.

### Example: Save breathing presets
- Proposed approach: Add named preset save/load controls in the main UI.
- Effort: M
- Impact: High
- Status: idea
- Notes: Start with local config storage; no cloud sync required.

### Donation/support CTA surfaces with polite frequency controls
- Problem: Support/donation prompts are currently README-only, so many in-app users (especially kiosk/offline workflows) may never see a support path. Any end-of-session prompt also risks feeling intrusive without opt-out controls.
- Proposed approach: Added lightweight donation CTA surfaces in-app via `More -> Support Development…` and an optional end-of-session prompt with controls for `Hide for 1 week` and `Never show again`, persisted per profile.
- Effort: S
- Impact: Med
- Status: done
- Notes: Completed 2026-03-09. Prompt is non-blocking and only shown after finalize/save (not during active sessions). Includes offline fallback status if support link cannot open.

### Kiosk donation/support UX parity (future)
- Problem: Planned USB Linux kiosk workflows are often offline, so in-app web links may not be reachable during sessions and support messaging can be missed.
- Proposed approach: Add kiosk-specific support surface with offline-friendly short URL + QR code and include the same suppression options (`Hide for 1 week`, `Never show again`) with per-profile persistence parity.
- Effort: S
- Impact: Med
- Status: idea
- Notes: Place in kiosk post-session screen and startup/help surface; never interrupt active session workflow.

### Re-evaluate settings scope after field testing
- Problem: Initial global vs per-profile settings scope is now defined, but real-world workflows may reveal misclassified knobs (too much shared behavior or too much per-user divergence).
- Proposed approach: After additional testing, review each setting and adjust scope (`global` vs `profile`) based on observed multi-user behavior, support feedback, and safety/usability outcomes.
- Effort: S
- Impact: High
- Status: idea
- Notes: Capture concrete examples during testing (who changed what, who was impacted) before changing defaults.

### [F04] Confidence badges on all outputs (deferred, low priority)
- Problem: Metric labels can appear equally trustworthy even when underlying signal quality differs.
- Proposed approach: Add High/Moderate/Low confidence badges for key outputs and reports.
- Effort: M
- Impact: Low
- Status: idea
- Notes: **Deferred; priority: low.** Moved from Prioritized. Depends on SQI and quality-rule definitions; align wording with non-diagnostic guardrails. Design for B&W printing (text-first, color optional).

## Prioritized

Top candidates after triage. Keep this list focused and ordered by value.

### 1) Define session user selection flow
- Problem: The app needs to know who is using the current session before data and settings can be applied correctly.
- Proposed approach: Define when/how the active user is selected at session start.
- Effort: M
- Impact: High
- Status: done
- Notes: Prioritize first because it unblocks per-user settings and history behavior.

### 2) Multiple user profiles with per-user history
- Problem: Sessions and history are not separated by person, which makes tracking progress across users difficult.
- Proposed approach: Add support for multiple user profiles and persist profile-specific session history (SQLite is a candidate).
- Effort: L
- Impact: High
- Status: done
- Notes: Decide where profile management lives in the UI (new card/screen vs settings area).

### 3) Per-user welcome/disclaimer visibility preference
- Problem: Users may not want to see the Welcome/Disclaimer every launch, but this preference should be tracked per user.
- Proposed approach: Add a "don't show again" preference stored per user profile.
- Effort: M
- Impact: Med
- Status: done
- Notes: Depends on session user identity and profile storage.

### 4) Decide QTc presentation format
- Problem: It is unclear how QTc should be presented in a way that is useful and not misleading.
- Proposed approach: Use both in phases: Phase 1 exposes a single end-of-session QTc summary with quality gating; Phase 2 adds an optional QTc trend plot after quality and smoothing validation.
- Effort: S
- Impact: Med
- Status: done
- Notes: Decision locked. `QTc (session)` is the canonical MVP output; if quality checks fail, show `QTc unavailable (signal quality too low)`. Trend view remains optional and hidden by default until validated.

### 5) QTc estimation capability
- Problem: The app currently lacks QTc estimate support for users who want a rough indication.
- Proposed approach: Implement QTc estimation against the locked presentation contract: Phase 1 fills end-of-session `QTc (session)` only; Phase 2 optionally enables trend output when quality gates pass.
- Effort: M
- Impact: Med
- Status: done
- Notes: Implemented. `qtc` payload and report fields populated; quality-gated unavailable fallback; live QTc trend window; DOCX and one-page PDF reports. Optional follow-ups: surface `method_suggestion` in report/UI; add synthetic/replay tests.

Implementation checklist:
- [x] Choose QT correction formula for MVP (default: Bazett) and record formula id in `qtc.summary_method` or adjacent metadata.
- [x] Define QT/QRS beat-quality gates (minimum valid beats, noise/artifact rejection, max gap between valid beats).
- [x] Implement canonical session summary as median of valid-window QTc values over final 30 seconds (`summary_window_seconds=30`).
- [x] Implement unavailable fallback path when quality gates fail (`status=unavailable`, `quality.is_valid=false`, `quality.reason` populated).
- [x] Populate report output `QTc (session)` from `qtc.session_value_ms` with non-diagnostic copy.
- [x] Keep `qtc.trend.enabled=false` by default and add explicit feature toggle path for Phase 2.
- [x] Surface `qtc.method_suggestion` in report/UI (`suggested_method` + plain-language `reasoning`) and include non-diagnostic wording.
- [x] Add synthetic test vectors for known QT/RR pairs and expected QTc ranges across low/normal/high heart rates.
- [x] Add replay tests on recorded noisy sessions to verify stable summary and proper unavailable behavior.

### 6) Add profile demographics metadata (age, gender, notes)
- Problem: Profile records currently do not capture key contextual demographics needed for interpretation and reporting.
- Proposed approach: Extend profile data model and UI to store age, gender, and free-text notes per user profile.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented in profile store schema and Profile Manager details form.

### 7) [F12] One-page clinical summary PDF
- Problem: Current reports are comprehensive but may be too long for fast handoff contexts.
- Proposed approach: Add a concise one-page summary export focused on key pre/post values, quality, and notable events.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented as a companion one-page share PDF with layout/formatting polish and one-page guardrails.

### 8) [F06] Serial session comparison view
- Problem: It is difficult to compare current session outcomes against recent personal history at a glance.
- Proposed approach: Add a second tab ("Compare") under Trends with session checkbox selection, metric selection, and an aligned comparison table with deltas. Default tab remains Trend Plots.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented Compare tab under Trends with session selection, metric selection, and aligned comparison table with deltas. Design: [docs/F06_TRENDS_COMPARE_TAB_DESIGN.md](docs/F06_TRENDS_COMPARE_TAB_DESIGN.md).

### 9) [F13] Session replay mode
- Problem: Post-session review lacks synchronized playback for metric changes and annotations.
- Proposed approach: Add timeline replay for recorded sessions with marker navigation and synchronized chart state.
- Effort: M
- Impact: High
- Status: done
- Notes: Replay tab in Session History with HR/RMSSD/ECG plots (zoom/pan both axes), timeline scrubber, play/pause, variable speed, jump-to-annotation. Data from EDF or CSV.

### 10) [F24] Import connectors (common RR/ECG formats)
- Problem: Historical/external recordings are hard to analyze in-app without native import paths.
- Proposed approach: Add import support for common formats and selected ecosystem exports, then run the same analysis pipeline.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented Phase 1 import in More menu (`Import session...`) with session normalization into native history/replay/report pipeline. Current supported inputs: native CSV (`event,value,timestamp,elapsed_sec`), EDF+, and RR-only text (Kubios/Elite HRV style). Import is disabled during active recording.

### 12) [F08] Tag correlation analytics
- Problem: Tagged events are captured but not leveraged to explain metric changes.
- Proposed approach: Compute and visualize correlations between tags and metric shifts over time.
- Effort: M
- Impact: Med
- Status: done
- Notes: Phase 1+2 implemented: Trends now includes `Tag Insights` tab with annotation-level ΔHR/ΔRMSSD/ΔSDNN/ΔLFHF, confidence tiers, caveats, and controls for range/min events/system annotations, plus per-tag drilldown details. Full DOCX report includes an exploratory `Annotation Associations` section with method text. Remaining follow-up (future phase): deeper statistical confidence intervals/permutation checks.

### 13) [F09] Circadian heatmap (hour/day patterns)
- Problem: Time-of-day patterns in stress/recovery signals are not easily visible.
- Proposed approach: Add heatmap views for metric distributions by hour and day-of-week.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Requires enough historical sessions for stable interpretation.

### 14) [F16] Export bundle profiles
- Problem: Different audiences need different export packages, but current export is one-size-fits-all.
- Proposed approach: Add export presets (`research`, `clinical review`, `raw`) with deterministic contents.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Include manifest-level provenance and file list per bundle.

### 15) [F10] "What changed?" auto-insight card
- Problem: Users must manually infer the most important session-to-session changes.
- Proposed approach: Generate a concise auto-insight card summarizing largest shifts and likely drivers.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Keep language cautious and confidence-aware; avoid diagnostic phrasing.

### 16) [F11] Population/peer percentile norms
- Problem: Session interpretation lacks normative context across demographics.
- Proposed approach: Add optional percentile context by age/sex and quality-filtered cohorts.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Requires validated reference datasets and transparent provenance.

### 17) [F31] SpO2/BP integration panel (manual first, device later)
- Problem: Cardiovascular context is incomplete when SpO2/BP is absent from session workflow.
- Proposed approach: Add manual SpO2/BP entry first, then optional device integrations for auto-capture.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Manual-entry phase is feasible now; device phase depends on vendor protocol/API support.

### 18) [F26] EMR-friendly exports (structured PDF/CSV mappings)
- Problem: Clinical workflow handoff often requires structured artifacts compatible with records systems.
- Proposed approach: Add structured export profiles and field mappings suitable for EMR ingestion workflows.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Full HL7/FHIR/DICOM integration is out of scope for near-term Python desktop delivery.

### 19) [F28] Arrhythmia pre-screen flags (non-diagnostic)
- Problem: High-risk rhythm patterns may be missed without explicit pre-screening cues.
- Proposed approach: Add non-diagnostic rhythm suspicion flags (e.g., AF/PVC tendency) with strict quality gating.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Requires careful validation and conservative UX to avoid diagnostic overreach; limited by single-lead constraints.

### 20) [PERF] Remove duplicate IBI update wiring
- Problem: The app appears to wire `ibi_update -> update_ibis_buffer` in two places, potentially doubling hot-path work and increasing plotting load.
- Proposed approach: Keep a single authoritative connection for `update_ibis_buffer` and verify beat/update counts remain 1:1.
- Effort: S
- Impact: High
- Status: done
- Notes: Duplicate `ibi_update -> update_ibis_buffer` wiring has been removed. Added diagnostics regression checks covering 1:1 beat/update behavior; live-stream/manual smoke validation remains recommended.

### 21) [PERF] Move QTc compute off the UI thread
- Problem: QTc extraction/delineation can block the GUI event loop and cause visible stutter during plotting.
- Proposed approach: Run QTc pipeline in a worker thread/process with latest-only job policy and throttled UI publish.
- Effort: M
- Impact: High
- Status: done
- Notes: Shipped single-worker QTc background compute with latest-only request coalescing and stale-result suppression; formulas/thresholds/payload schema were preserved. Optional follow-up: add queue-depth and compute-time telemetry for ongoing verification.

### 22) [PERF] Bound long-session chart series growth
- Problem: HR/RMSSD/SDNN chart series can grow without pruning, causing long-session slowdown and memory growth.
- Proposed approach: Keep only a rolling time window plus small guard buffer in visual series.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented rolling pruning for main HR/RMSSD/SDNN chart series (visible window + guard) with periodic trim checks to keep long-session UI memory and append cost bounded.

### 23) [PERF] Reduce ECG redraw allocation churn
- Problem: Repeated deque-to-array conversion and range work in the redraw loop adds avoidable CPU pressure.
- Proposed approach: Reuse buffers and minimize per-frame allocations/range resets.
- Effort: M
- Impact: High
- Status: done
- Notes: Reduced redraw churn by avoiding redundant numpy conversions for range math and suppressing no-op X/Y range resets in the ECG refresh path.

### 24) [PERF] Refresh profiling harness for current package
- Problem: Existing profiling helpers still reference older package names and are not ready for current hot-path analysis.
- Proposed approach: Update profiling scripts to current module paths and standardize capture commands.
- Effort: S
- Impact: Med
- Status: done
- Notes: Updated profiling helpers to current `hnh` package paths and added standardized capture/viewer options (`--output`, `--no-view`) for repeatable hot-path analysis.

### 25) [PERF] Optimize BLE ECG packet decode path
- Problem: Python-loop packet unpacking runs continuously and contributes avoidable CPU overhead.
- Proposed approach: Vectorize decode logic (or move hot loop to native/compiled path if needed).
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Keep decoded values bit-for-bit compatible with current output.

### 26) [PERF/UX] Preserve plot history across disconnects with auto system annotations
- Problem: Clearing plots on disconnect removes useful clinical context; users may not have time to manually annotate connectivity faults.
- Proposed approach: Keep existing HR/RMSSD/SDNN traces visible, gray plots during disconnect with overlay copy, resume with a blank timeline gap (no deceptive bridge line), and auto-log system annotations for disconnect/reconnect with reason and duration.
- Effort: M
- Impact: High
- Status: done
- Notes: Full implementation: gray overlay during disconnect; explicit timeline gap via multi-series segments; disconnect intervals in manifest (disconnect_intervals, disconnect_total_seconds); system annotations in CSV/report; button-disconnect preserves plot history and shows gray overlay; parity with sensor-induced path.

Implementation checklist:
- [x] Preserve HR/RMSSD/SDNN traces during sensor-induced signal fault (timeout, dropout).
- [x] Stop appending new points during fault; chart shows break until recovery.
- [x] Resume plotting when good data returns.
- [x] Log faults to signal_diag.log with type, reason, and counts.
- [x] Gray plots during disconnect with overlay copy.
- [x] Resume with explicit blank timeline gap (no deceptive bridge line).
- [x] Persist disconnect intervals/count/total duration in manifest.
- [x] Include auto annotations in CSV/report timelines.
- [x] Button-driven disconnect: preserve history (parity with sensor-induced path).

### 27) [F33] EDF export implementation (native + CSV backfill path)
- Problem: Session manifests include an EDF artifact path but EDF writing is still marked planned and not produced.
- Proposed approach: Implement EDF export at finalize-time from captured session streams, plus a follow-on backfill utility that can generate EDF from existing CSV sessions.
- Effort: M
- Impact: High
- Status: done
- Notes: Native finalize-time EDF+ export is implemented with optional toggle, normalized channels, and tests; CSV backfill remains optional future tooling.

### 28) [PERF/UX] Reconnect gap rendering parity (low priority)
- Problem: After sensor-induced disconnect/reconnect, traces can resume with wonky continuity; button-driven disconnect/reconnect currently clears all plots, creating inconsistent behavior.
- Proposed approach: Normalize reconnect handling so both disconnect paths preserve history with an explicit blank gap (or clearly marked disconnect segment) and avoid deceptive line continuity.
- Effort: M
- Impact: Low
- Status: done
- Notes: Addressed by item #26: both disconnect paths preserve history with explicit gap and gray overlay.

## PlannedNext

Items that are implementation-ready and should be picked up soon.

### A) Session user selection flow (from prioritized item 1)
- Problem: The app must know the active user at session start.
- Proposed approach: Add a startup user-selection step before session data loads.
- Effort: M
- Impact: High
- Status: done
- Notes: Should support quick start and avoid breaking current single-user behavior.

Implementation checklist:
- [x] Define UX path: startup selector vs quick switch entry point.
- [x] Define session lifecycle states (`no_user_selected`, `user_selected`, `guest_mode` if used).
- [x] Add active-user state to app session context.
- [x] Ensure new session start requires a selected user (or explicit guest fallback).
- [x] Define behavior when switching users mid-app (Switch User button; same popup as startup).
- [x] Add acceptance criteria for flow (startup, cancel, user choose, and reconnect baseline checks).

### B) Multiple user profiles and per-user history (from prioritized item 2)
- Problem: Data is not currently segmented by user identity.
- Proposed approach: Add profile entities and persist profile-linked session history (SQLite candidate).
- Effort: L
- Impact: High
- Status: done
- Notes: Build after user-selection flow contract is finalized.

Implementation checklist:
- [x] Choose storage model (SQLite tables vs existing storage path extension).
- [x] Define profile schema (id, display name, created/updated timestamps, optional metadata).
- [x] Define history schema linked to profile id.
- [x] Add profile CRUD operations (create, rename, select, archive/delete policy).
- [x] Migrate existing single-user history to profile-backed indexing safely (legacy fallback profile included).
- [x] Update history queries/views to filter by active profile.
- [x] Add tests for profile isolation and migration edge cases.

### C) [PERF] Remove duplicate IBI update wiring (from prioritized item 23)
- Problem: Duplicate hot-path signal wiring can increase compute load and plotting pressure.
- Proposed approach: Keep one `ibi_update -> update_ibis_buffer` connection and verify no duplicate processing.
- Effort: S
- Impact: High
- Status: done
- Notes: Implemented single authoritative wiring; one follow-up check remains for explicit 1:1 beat/update verification during live streaming.

Implementation checklist:
- [x] Confirm all `ibi_update` wiring locations and choose single owner.
- [x] Remove duplicate connection while preserving `hr_handler` behavior.
- [x] Verify `update_ibis_buffer` triggers once per beat in normal streaming.
- [ ] Smoke-test HR/RMSSD/plot responsiveness and regression-risk paths (connect/reconnect/reset).

## Done

Completed items. Include completion date and optional version reference.

### [F24] Import connectors (common RR/ECG formats)
- Completed: 2026-03-08
- Outcome: Added import flow under More menu (`Import session...`) that creates native session artifacts and indexes imported sessions into history/trends so they can be replayed, reported, and compared like recorded sessions.
- Notes: Supported inputs in this phase: native CSV (`event,value,timestamp,elapsed_sec`), EDF+, and RR-only line-separated text (Kubios/Elite HRV style). Includes sample generator script: `scripts/create_import_samples.py`.

### Session History hide/unhide (soft delete)
- Completed: 2026-03-08
- Outcome: Added reversible session hiding in Session History with `Show hidden` toggle plus `Hide selected` / `Unhide selected` actions; hidden sessions are excluded by default.
- Notes: Backed by `session_history.is_hidden`; includes status messaging and selection-preservation polish for hide/unhide/toggle flows. Extended with `Purge abandoned...` action in History, Trends-side `Show hidden sessions` parity toggle, non-modal History window behavior matching Trends, and startup auto-purge of stale `recording` sessions for primary instance only.

### [F13] Session replay mode
- Completed: 2026-03-07
- Outcome: Replay tab added to Session History with HR, RMSSD, and ECG plots (zoomable and pannable on both axes). Timeline scrubber scrolls time; play/pause with variable speed (0.5×, 1×, 2×, 4×); jump-to-annotation. Data loaded from EDF (if exported) or CSV.
- Notes: `hnh/replay_loader.py`, `hnh/view.py` (SessionHistoryDialog Replay tab).

### [F06] Serial session comparison view
- Completed: 2026-03-07
- Outcome: Compare tab added under Trends with session checkbox selection, metric selection, and aligned comparison table with deltas. Default tab remains Trend Plots. Prioritizes QTc/RMSSD/HR.
- Notes: Design: [docs/F06_TRENDS_COMPARE_TAB_DESIGN.md](docs/F06_TRENDS_COMPARE_TAB_DESIGN.md).

### [F13] Session replay mode
- Completed: 2026-03-07
- Outcome: Replay tab added to Session History window. Select a session, click Load, then use timeline scrubber or Play to scroll through time. HR, RMSSD, and ECG plots are zoomable and pannable on both axes. Variable playback speed (0.5×, 1×, 2×, 4×). Jump-to-annotation dropdown. Data loaded from EDF (if exported) or CSV.
- Notes: `hnh/replay_loader.py`, `hnh/view.py` (SessionHistoryDialog Replay tab).

### CSV export: IBI, HRV, time, and elapsed_sec
- Completed: 2026-03-02
- Outcome: Session recording CSV now logs raw IBI (RR) intervals plus derived HRV (RMSSD), with `elapsed_sec` for Kubios/HRVAS-style downstream analysis. Header: `event,value,timestamp,elapsed_sec`. Event types: IBI (ms), hrv (ms), Annotation, and disclaimer metadata. Enables both simple viewing of derived metrics and full RR-based re-analysis in external tools.
- Notes: `hnh/logger.py`, `hnh/view.py` (ibis_buffer_update → logger); mock CSV in `docs/reporting/generate_mockup_reports.py` updated for format consistency.

### Session trends (Show Trends)
- Completed: 2026-02-27
- Outcome: Store avg session values (HR, RMSSD, SDNN, QTc, baselines) per profile at end of each session with date/time. Show Trends button opens a window with compare-plot of past sessions over the last year. Dotted lines with markers; draggable vertical cursor; pixel-based hit so values show when cursor is near a point (zoom-adaptive). Profile selector (admin only); pan/zoom via mouse. Backfill from manifests for existing sessions.
- Notes: `hnh/profile_store.py` (session_trends table), `hnh/view.py` (TrendsWindow).

### QTc estimation capability
- Completed: 2026-02-27
- Outcome: QTc computation and reporting implemented: multiple formulas (Bazett default, Fridericia, Framingham, Hodges), QT/QRS delineation, quality gating, session median over final window, unavailable fallback. Live QTc trend window and button; QTc (session median) and QRS in DOCX and one-page PDF reports with ±15% uncertainty and non-diagnostic wording. Background worker for compute; `method_suggestion` computed (optional: surface in report/UI). Synthetic/replay test coverage optional follow-up.
- Notes: See `hnh/qtc.py`, `hnh/report.py`, `hnh/view.py` (QtcWindow).

### Session user selection flow
- Completed: 2026-02-24
- Outcome: Startup profile chooser implemented (select/create/guest), active profile shown at top of monitoring card, startup flow gates session context.
- Notes: Mid-session switch added 2026-02-27 via Switch User button next to user name.

### Mid-session user switch
- Completed: 2026-02-27
- Outcome: Switch User button added to right of user name in header; opens same profile selection popup as startup. Available anytime including during recording; same user or Cancel leaves plotting uninterrupted.

### Per-user welcome/disclaimer visibility preference
- Completed: 2026-02-24
- Outcome: Disclaimer display is now profile-specific with "Don't show again" persistence.
- Notes: Settings includes queued reset for disclaimer prompt (active user or all users) applied on Save and Close; confirmation popup and persistence behavior were hardened.

### Multiple user profiles and per-user history
- Completed: 2026-02-24
- Outcome: Profile CRUD (create/rename/archive/restore/delete), one-time legacy migration indexing, profile-scoped history query APIs, and read-only in-app history viewer.
- Notes: Profile Manager blocked during recording; Switch User allowed anytime. Profile details auto-save when switching profiles in Profile Manager. Extended 2026-02-27 with password login, user roles (admin/user), and Role column.

### Profile demographics metadata (age, gender, notes)
- Completed: 2026-02-24
- Outcome: Profile records now persist age, gender, and notes; Profile Manager includes editable fields with save action. DOB replaces age; date format matches reports; auto-save on profile switch.
- Notes: Demographics are currently profile metadata only (not yet surfaced in report documents).

### Decide QTc presentation format
- Completed: 2026-02-24
- Outcome: Presentation format locked to phased rollout: end-of-session QTc summary first, optional dedicated trend plot second.
- Notes: Implementation must enforce quality gating, non-diagnostic copy, and explicit trend-context labeling before enabling trend by default.

### [PERF] Remove duplicate IBI update wiring
- Completed: 2026-02-25
- Outcome: `ibi_update -> update_ibis_buffer` is now wired through a single authoritative connection.
- Notes: Follow-up validation remains: explicitly confirm 1:1 beat/update behavior under live streaming and complete regression smoke checks for connect/reconnect/reset paths.

### Status banner precedence fix (locked vs no-data/no-sensor)
- Completed: 2026-02-25
- Outcome: Recording banner now prioritizes live connectivity/stream state over stale phase state, preventing contradictory combinations like `BASELINES LOCKED` alongside `ECG (waiting for data...)`/`QTc (no sensor)`.
- Notes: Stream reset and disconnected paths now explicitly clear phase-active state and refresh banner text immediately.

### Signal degraded alerts: non-modal and background-safe
- Completed: 2026-02-25
- Outcome: Signal degraded warnings now use a non-modal, no-focus alert path so they stay visible with pinned plot windows without stealing focus from other applications.
- Notes: When the app is not active, alerts are queued and shown on return to the app; indicator/status messaging remains immediate.

### [F12] One-page clinical summary PDF
- Completed: 2026-02-26
- Outcome: Added one-page share PDF export and aligned formatting/content with report conventions (including generated timestamp formatting and visual ordering).
- Notes: Designed as a companion artifact to full DOCX report, with one-page readability constraints.

### [F33] EDF export implementation (native + CSV backfill path)
- Completed: 2026-02-26
- Outcome: Added finalize-time EDF+ export with HR/RMSSD channels, normalized derivation-friendly channels, and ECG waveform support.
- Notes: Optional export toggle and test coverage are in place; CSV backfill path can be added later if still needed.

### Save/Report destination path memory split
- Completed: 2026-02-26
- Outcome: Save and Report actions now prompt for destination folders and remember separate per-profile last-used paths.
- Notes: Includes backward-compatible fallback to legacy shared save-path preference.

### Report and profile UX polish (2026-02-27)
- Completed: 2026-02-27
- Outcome: Report button "Report to Now" during recording; report stage labels "Data collected so far"/"Final" with snapshot disclaimer; QRS session average in reports; QTc/QRS ±15% measurement uncertainty in reports and UI; ECG strip duplicate title removed; trend plot lines thinner; Profile Manager date format matches reports; age label no longer grayed out.
- Notes: ECG_QTc_UNCERTAINTY_PCT and ECG_QRS_UNCERTAINTY_PCT in config; format_datetime_for_display shared for reports and profiles.

### Session closure and report clarity (2026-02-27)
- Completed: 2026-02-27
- Outcome: Explicit Stop button for ending sessions (saves data without report prompt); Post-Session Readings limited to latest values (HR, RMSSD, HRV·SDNN, LF/HF, QTc, QRS); Session Statistics renamed from Intra-Session and holds all deltas (Δ HR/RMSSD from Baseline, Δ HRV·SDNN first→last); Pre-Session Baselines retitled to Pre-Session Baseline Averages; HRV·SDNN labeling (middle dot) to avoid fraction ambiguity; QTc labeled as session median; trend plots truncated to skip initial settling period; LF/HF added to reports (Post-Session latest, Session Statistics Min/Max/Avg, one-page PDF session avg).
- Notes: Stop button enables clean session closure without full finalize; HRV·SDNN replaces HRV (SDNN) and HRV/SDNN; stress_ratio_values recorded during sessions for LF/HF reporting.

### Profile password login and user roles (2026-02-27)
- Completed: 2026-02-27
- Outcome: Optional per-profile password verification at login; user roles (admin vs user) with Profile Manager access control; Admin profile as default (replacing Default) with admin rights; normal users restricted to viewing/editing own profile only; Role column in Profile Manager table; Set/Reset Password in Profile Manager.
- Notes: New profiles default to user role; Admin profile gets admin role; HNH_SKIP_PASSWORD env var for lockout recovery; `docs/password_and_lockout.md` documents recovery and password flows.

## Triage Workflow

1. Add new suggestions to `Intake` using the template.
2. During review, clarify scope and acceptance criteria.
3. Assign `Effort` and `Impact`, then move strong candidates to `Prioritized`.
4. Move build-ready items to `PlannedNext` and set status to `planned`.
5. After release, move to `Done`, set status to `done`, and link version notes in `changelog.md` when relevant.
