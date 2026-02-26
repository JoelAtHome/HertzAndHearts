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
- Status: idea
- Notes: Reported as urgent usability regression; keep scope to button/functionality restore first.

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

### Example: Save breathing presets
- Problem: Users repeat the same target and breathing rate setup each session.
- Proposed approach: Add named preset save/load controls in the main UI.
- Effort: M
- Impact: High
- Status: idea
- Notes: Start with local config storage; no cloud sync required.

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
- Status: planned
- Notes: Populate `qtc` report payload and `metrics.qtc` manifest fields (`session_value_ms`, `summary_method`, `summary_window_seconds`, `status`, `quality`, `trend`) with non-diagnostic messaging and quality-gated unavailable fallback. Data-driven method recommendation is already computed in `qtc.method_suggestion` (`suggested_method`, `reasoning`) and must be surfaced in report/UI so it is not lost.

Implementation checklist:
- [ ] Choose QT correction formula for MVP (default: Bazett) and record formula id in `qtc.summary_method` or adjacent metadata.
- [ ] Define QT/QRS beat-quality gates (minimum valid beats, noise/artifact rejection, max gap between valid beats).
- [ ] Implement canonical session summary as median of valid-window QTc values over final 30 seconds (`summary_window_seconds=30`).
- [ ] Implement unavailable fallback path when quality gates fail (`status=unavailable`, `quality.is_valid=false`, `quality.reason` populated).
- [ ] Populate report output `QTc (session)` from `qtc.session_value_ms` with non-diagnostic copy.
- [ ] Keep `qtc.trend.enabled=false` by default and add explicit feature toggle path for Phase 2.
- [ ] Surface `qtc.method_suggestion` in report/UI (`suggested_method` + plain-language `reasoning`) and include non-diagnostic wording.
- [ ] Add synthetic test vectors for known QT/RR pairs and expected QTc ranges across low/normal/high heart rates.
- [ ] Add replay tests on recorded noisy sessions to verify stable summary and proper unavailable behavior.

### 6) Add profile demographics metadata (age, gender, notes)
- Problem: Profile records currently do not capture key contextual demographics needed for interpretation and reporting.
- Proposed approach: Extend profile data model and UI to store age, gender, and free-text notes per user profile.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented in profile store schema and Profile Manager details form.

### 7) [F20] Finalize-time quality checklist
- Problem: Sessions can be finalized with low-quality or incomplete context, which increases interpretation risk.
- Proposed approach: Add a pre-finalize checklist for data quality, baseline completeness, and report-readiness warnings.
- Effort: S
- Impact: High
- Status: planned
- Notes: Include explicit confirm/override flow and a persisted checklist outcome in `session_manifest.json`.

### 8) [F01] Live Signal Quality Index (SQI) strip
- Problem: Users lack a single quantitative confidence indicator across session timeline and outputs.
- Proposed approach: Compute and display a continuous SQI strip (or score) that reflects confidence in current physiological outputs.
- Effort: M
- Impact: High
- Status: planned
- Notes: Start with HR/RMSSD/QTc confidence blend and expose component reasons (dropout/noise/instability).

### 9) [F04] Confidence badges on all outputs
- Problem: Metric labels can appear equally trustworthy even when underlying signal quality differs.
- Proposed approach: Add High/Moderate/Low confidence badges for key outputs and reports.
- Effort: M
- Impact: High
- Status: triaged
- Notes: Depends on SQI and quality-rule definitions; align wording with non-diagnostic guardrails.

### 10) [F12] One-page clinical summary PDF
- Problem: Current reports are comprehensive but may be too long for fast handoff contexts.
- Proposed approach: Add a concise one-page summary export focused on key pre/post values, quality, and notable events.
- Effort: M
- Impact: High
- Status: done
- Notes: Implemented as a companion one-page share PDF with layout/formatting polish and one-page guardrails.

### 11) [F15] Versioned analysis metadata
- Problem: Reproducibility is harder without explicit algorithm/settings version traces per session.
- Proposed approach: Store analysis version, formula strategy, and settings hash with each session artifact.
- Effort: S
- Impact: High
- Status: planned
- Notes: Add stable keys to manifest and include in report footer/appendix.

### 12) [F06] Serial session comparison view
- Problem: It is difficult to compare current session outcomes against recent personal history at a glance.
- Proposed approach: Add a dedicated serial comparison view for selected sessions with aligned metrics and deltas.
- Effort: M
- Impact: High
- Status: triaged
- Notes: Prioritize QTc/RMSSD/HR plus confidence overlays.

### 13) [F13] Session replay mode
- Problem: Post-session review lacks synchronized playback for metric changes and annotations.
- Proposed approach: Add timeline replay for recorded sessions with marker navigation and synchronized chart state.
- Effort: M
- Impact: High
- Status: triaged
- Notes: Include variable playback speed and jump-to-annotation controls.

### 14) [F24] Import connectors (common RR/ECG formats)
- Problem: Historical/external recordings are hard to analyze in-app without native import paths.
- Proposed approach: Add import support for common formats and selected ecosystem exports, then run the same analysis pipeline.
- Effort: M
- Impact: High
- Status: triaged
- Notes: Start with CSV/EDF plus one high-value vendor export profile.

### 15) [F08] Tag correlation analytics
- Problem: Tagged events are captured but not leveraged to explain metric changes.
- Proposed approach: Compute and visualize correlations between tags and metric shifts over time.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Show association confidence and sample-size caveats to avoid over-interpretation.

### 16) [F09] Circadian heatmap (hour/day patterns)
- Problem: Time-of-day patterns in stress/recovery signals are not easily visible.
- Proposed approach: Add heatmap views for metric distributions by hour and day-of-week.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Requires enough historical sessions for stable interpretation.

### 17) [F16] Export bundle profiles
- Problem: Different audiences need different export packages, but current export is one-size-fits-all.
- Proposed approach: Add export presets (`research`, `clinical review`, `raw`) with deterministic contents.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Include manifest-level provenance and file list per bundle.

### 18) [F10] "What changed?" auto-insight card
- Problem: Users must manually infer the most important session-to-session changes.
- Proposed approach: Generate a concise auto-insight card summarizing largest shifts and likely drivers.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Keep language cautious and confidence-aware; avoid diagnostic phrasing.

### 19) [F11] Population/peer percentile norms
- Problem: Session interpretation lacks normative context across demographics.
- Proposed approach: Add optional percentile context by age/sex and quality-filtered cohorts.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Requires validated reference datasets and transparent provenance.

### 20) [F31] SpO2/BP integration panel (manual first, device later)
- Problem: Cardiovascular context is incomplete when SpO2/BP is absent from session workflow.
- Proposed approach: Add manual SpO2/BP entry first, then optional device integrations for auto-capture.
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Manual-entry phase is feasible now; device phase depends on vendor protocol/API support.

### 21) [F26] EMR-friendly exports (structured PDF/CSV mappings)
- Problem: Clinical workflow handoff often requires structured artifacts compatible with records systems.
- Proposed approach: Add structured export profiles and field mappings suitable for EMR ingestion workflows.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Full HL7/FHIR/DICOM integration is out of scope for near-term Python desktop delivery.

### 22) [F28] Arrhythmia pre-screen flags (non-diagnostic)
- Problem: High-risk rhythm patterns may be missed without explicit pre-screening cues.
- Proposed approach: Add non-diagnostic rhythm suspicion flags (e.g., AF/PVC tendency) with strict quality gating.
- Effort: L
- Impact: Med
- Status: triaged
- Notes: Requires careful validation and conservative UX to avoid diagnostic overreach; limited by single-lead constraints.

### 23) [PERF] Remove duplicate IBI update wiring
- Problem: The app appears to wire `ibi_update -> update_ibis_buffer` in two places, potentially doubling hot-path work and increasing plotting load.
- Proposed approach: Keep a single authoritative connection for `update_ibis_buffer` and verify beat/update counts remain 1:1.
- Effort: S
- Impact: High
- Status: done
- Notes: Duplicate `ibi_update -> update_ibis_buffer` wiring has been removed; follow-up live-stream validation is still pending to explicitly confirm 1:1 beat/update behavior under normal streaming.

### 24) [PERF] Move QTc compute off the UI thread
- Problem: QTc extraction/delineation can block the GUI event loop and cause visible stutter during plotting.
- Proposed approach: Run QTc pipeline in a worker thread/process with latest-only job policy and throttled UI publish.
- Effort: M
- Impact: High
- Status: implemented
- Notes: Shipped single-worker QTc background compute with latest-only request coalescing and stale-result suppression; formulas/thresholds/payload schema were preserved. Optional follow-up: add queue-depth and compute-time telemetry for ongoing verification.

### 25) [PERF] Bound long-session chart series growth
- Problem: HR/RMSSD/SDNN chart series can grow without pruning, causing long-session slowdown and memory growth.
- Proposed approach: Keep only a rolling time window plus small guard buffer in visual series.
- Effort: M
- Impact: High
- Status: implemented
- Notes: Implemented rolling pruning for main HR/RMSSD/SDNN chart series (visible window + guard) with periodic trim checks to keep long-session UI memory and append cost bounded.

### 26) [PERF] Reduce ECG redraw allocation churn
- Problem: Repeated deque-to-array conversion and range work in the redraw loop adds avoidable CPU pressure.
- Proposed approach: Reuse buffers and minimize per-frame allocations/range resets.
- Effort: M
- Impact: High
- Status: implemented
- Notes: Reduced redraw churn by avoiding redundant numpy conversions for range math and suppressing no-op X/Y range resets in the ECG refresh path.

### 27) [PERF] Refresh profiling harness for current package
- Problem: Existing profiling helpers still reference older package names and are not ready for current hot-path analysis.
- Proposed approach: Update profiling scripts to current module paths and standardize capture commands.
- Effort: S
- Impact: Med
- Status: implemented
- Notes: Updated profiling helpers to current `hnh` package paths and added standardized capture/viewer options (`--output`, `--no-view`) for repeatable hot-path analysis.

### 28) [PERF] Optimize BLE ECG packet decode path
- Problem: Python-loop packet unpacking runs continuously and contributes avoidable CPU overhead.
- Proposed approach: Vectorize decode logic (or move hot loop to native/compiled path if needed).
- Effort: M
- Impact: Med
- Status: triaged
- Notes: Keep decoded values bit-for-bit compatible with current output.

### 29) [PERF/UX] Preserve plot history across disconnects with auto system annotations
- Problem: Clearing plots on disconnect removes useful clinical context; users may not have time to manually annotate connectivity faults.
- Proposed approach: Keep existing HR/RMSSD/SDNN traces visible, gray plots during disconnect with overlay copy, resume with a blank timeline gap (no deceptive bridge line), and auto-log system annotations for disconnect/reconnect with reason and duration.
- Effort: M
- Impact: High
- Status: planned
- Notes: Persist disconnect intervals/count/total duration in manifest and include generated annotations in CSV/report timelines.

### 30) [F33] EDF export implementation (native + CSV backfill path)
- Problem: Session manifests include an EDF artifact path but EDF writing is still marked planned and not produced.
- Proposed approach: Implement EDF export at finalize-time from captured session streams, plus a follow-on backfill utility that can generate EDF from existing CSV sessions.
- Effort: M
- Impact: High
- Status: done
- Notes: Native finalize-time EDF+ export is implemented with optional toggle, normalized channels, and tests; CSV backfill remains optional future tooling.

### 31) [PERF/UX] Reconnect gap rendering parity (low priority)
- Problem: After sensor-induced disconnect/reconnect, traces can resume with wonky continuity; button-driven disconnect/reconnect currently clears all plots, creating inconsistent behavior.
- Proposed approach: Normalize reconnect handling so both disconnect paths preserve history with an explicit blank gap (or clearly marked disconnect segment) and avoid deceptive line continuity.
- Effort: M
- Impact: Low
- Status: triaged
- Notes: Low-priority polish follow-up after higher-value plotting/performance tasks.

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
- [x] Define behavior when switching users mid-app (currently startup selection only; switch action deferred).
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
- [ ] Verify `update_ibis_buffer` triggers once per beat in normal streaming.
- [ ] Smoke-test HR/RMSSD/plot responsiveness and regression-risk paths (connect/reconnect/reset).

## Done

Completed items. Include completion date and optional version reference.

### Session user selection flow
- Completed: 2026-02-24
- Outcome: Startup profile chooser implemented (select/create/guest), active profile shown at top of monitoring card, startup flow gates session context.
- Notes: Mid-session quick-switch UI is intentionally deferred; current behavior is select at startup.

### Per-user welcome/disclaimer visibility preference
- Completed: 2026-02-24
- Outcome: Disclaimer display is now profile-specific with "Don't show again" persistence.
- Notes: Settings includes queued reset for disclaimer prompt (active user or all users) applied on Save and Close; confirmation popup and persistence behavior were hardened.

### Multiple user profiles and per-user history
- Completed: 2026-02-24
- Outcome: Profile CRUD (create/rename/archive/restore/delete), one-time legacy migration indexing, profile-scoped history query APIs, and read-only in-app history viewer.
- Notes: Active-profile safeguards are enforced; profile changes are blocked during active recording.

### Profile demographics metadata (age, gender, notes)
- Completed: 2026-02-24
- Outcome: Profile records now persist age, gender, and notes; Profile Manager includes editable fields with save action.
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

## Triage Workflow

1. Add new suggestions to `Intake` using the template.
2. During review, clarify scope and acceptance criteria.
3. Assign `Effort` and `Impact`, then move strong candidates to `Prioritized`.
4. Move build-ready items to `PlannedNext` and set status to `planned`.
5. After release, move to `Done`, set status to `done`, and link version notes in `changelog.md` when relevant.
