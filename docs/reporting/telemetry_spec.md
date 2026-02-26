# Reporting Telemetry Specification (v1)

This spec defines event instrumentation for reporting adoption, comprehension, and retention outcomes.

## 1) Goals

- Measure if users open and understand reports.
- Measure if reports are shared with coaches/clinicians.
- Measure if reports drive repeat measurements.
- Measure interaction with interpretation content.

## 2) Global Event Requirements

All reporting events must include:
- `event_name`
- `event_time_utc`
- `user_id` (or anonymized stable ID)
- `session_id` (measurement session)
- `report_version` (for example `p1_v1`)
- `platform` (`desktop`, `android`, `ios`)

Optional but recommended:
- `baseline_window_count`
- `recovery_state`
- `confidence_state`

## 3) Event Catalog

### `report_opened`
Triggered when report view is first rendered.

Properties:
- `entry_point` (`post_measurement`, `history`, `notification`, `shared_link`)
- `has_baseline` (boolean)
- `quality_grade` (`good`, `okay`, `poor`)

### `report_section_viewed`
Triggered when a section enters viewport for at least 1 second.

Properties:
- `section_id` (`executive_summary`, `baseline_comparison`, `time_domain`, `frequency_domain`, `quality_panel`, `trends`, `recommendation`)
- `view_duration_ms`

### `interpretation_card_opened`
Triggered when user expands or taps interpretation text/help.

Properties:
- `metric_id` (`rmssd`, `sdnn`, `ln_rmssd`, `pnn50`, `mean_rr`, `lf`, `hf`, `lf_hf`, `qtc`)
- `origin_section` (`time_domain`, `frequency_domain`, `summary`)

### `report_shared`
Triggered on successful share/export action.

Properties:
- `share_type` (`pdf_export`, `native_share`, `clipboard`)
- `share_variant` (`coach_share_compact`, `clinical_share_compact`)
- `target_hint` (`coach`, `clinician`, `self`, `unknown`)

### `report_export_completed`
Triggered when PDF generation succeeds.

Properties:
- `export_format` (`pdf`)
- `render_time_ms`
- `page_count`

### `measurement_repeated_within_window`
Derived event from backend job or analytics model.

Properties:
- `days_since_last_measurement`
- `window_bucket` (`1d`, `3d`, `7d`)
- `trigger_context` (`report_opened_recently`, `no_recent_report`)

## 4) KPI Definitions

### Report engagement
- `report_open_rate = unique_users(report_opened) / unique_users(measurement_completed)`
- `section_completion_rate = users_viewing_summary_and_baseline / users_with_report_opened`

### Interpretation usage
- `interpretation_interaction_rate = users(interpretation_card_opened) / users(report_opened)`

### Share behavior
- `share_rate = users(report_shared) / users(report_opened)`
- `pdf_export_success_rate = count(report_export_completed) / count(export_attempted)`

### Retention outcome
- `7d_repeat_rate = users(measurement_repeated_within_window where window_bucket=7d) / users(report_opened)`

## 5) Analysis Cuts

Break down all KPIs by:
- `recovery_state`
- `confidence_state`
- `quality_grade`
- `has_baseline`
- `platform`

This identifies whether low-confidence reports reduce engagement or repeat behavior.

## 6) Instrumentation Notes

- Emit `report_opened` once per session/report pair to avoid inflation.
- Use debounced section tracking to avoid noisy `report_section_viewed` events.
- Ensure offline buffering with retry to prevent data loss.
- Do not log raw ECG samples in telemetry payloads.

## 7) Rollout and Validation

1. Implement client-side events behind `reporting_telemetry_v1` feature flag.
2. Validate payload schemas in staging for one week.
3. Enable for 25% users, then 100% after quality checks.
4. Review KPI dashboard weekly for first four weeks post-release.
