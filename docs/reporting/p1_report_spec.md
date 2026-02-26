# P1 Reporting Specification (v1)

This spec defines the first production-ready reporting iteration for Hertz and Hearts.

## 1) Scope

P1 adds:
- Executive summary with recovery state and key drivers.
- Personal baseline comparison for HRV and heart rate.
- Metric interpretation text for core cards.
- Data quality and confidence panel.
- Inputs needed for one-page shareable PDF generation.

P1 does not add:
- Behavior journaling correlation.
- Advanced anomaly detection.
- Multi-persona report modes.

## 2) Required Inputs

### Session-level inputs
- `session_id`
- `start_time`, `end_time`, `duration_seconds`
- `hr_min_bpm`, `hr_max_bpm`, `hr_avg_bpm`
- `rmssd_ms`, `ln_rmssd`, `sdnn_ms`, `pnn50_percent`
- `rr_mean_ms`
- `lf_power_ms2`, `hf_power_ms2`, `lf_hf_ratio`
- `artifact_percent`
- `beats_count`, `ectopic_count`, `ectopic_percent`

### Baseline inputs
- `baseline_7d_rmssd_ms`, `baseline_30d_rmssd_ms`
- `baseline_7d_rhr_bpm`, `baseline_30d_rhr_bpm`
- `baseline_window_count` (number of sessions contributing)

## 3) Report Information Architecture

1. Executive Summary
2. Baseline Comparison
3. Core Metrics (time-domain and frequency-domain)
4. Data Quality and Confidence
5. Footer (disclaimer + measurement metadata)

## 4) Executive Summary Rules

### Output fields
- `recovery_state`: `low`, `moderate`, `high`
- `confidence_state`: `low`, `medium`, `high`
- `key_drivers`: 2-3 short bullets

### Recovery state heuristic (P1)
- Start from neutral score `0`.
- Add `+1` if `rmssd_ms >= baseline_7d_rmssd_ms`.
- Add `+1` if `hr_avg_bpm <= baseline_7d_rhr_bpm`.
- Add `+1` if `artifact_percent <= 2`.
- Subtract `1` if `lf_hf_ratio > 3.0`.
- Subtract `1` if `duration_seconds < 60`.

Map score:
- `>= 2` -> `high`
- `0 to 1` -> `moderate`
- `< 0` -> `low`

### Key driver generation
- Pick top 2 positive/negative contributors from:
  - RMSSD vs 7d baseline delta.
  - HR average vs 7d baseline delta.
  - Artifact percentage.
  - LF/HF ratio.
- Use plain language templates from section 7.

## 5) Baseline Comparison Section

### Display requirements
- Show current value plus delta vs 7-day and 30-day baseline.
- Use arrow icons:
  - Up arrow if delta > +5%.
  - Down arrow if delta < -5%.
  - Flat arrow otherwise.

### Delta formulas
- `rmssd_delta_7d_percent = ((rmssd_ms - baseline_7d_rmssd_ms) / baseline_7d_rmssd_ms) * 100`
- `rmssd_delta_30d_percent = ((rmssd_ms - baseline_30d_rmssd_ms) / baseline_30d_rmssd_ms) * 100`
- `hr_delta_7d_percent = ((hr_avg_bpm - baseline_7d_rhr_bpm) / baseline_7d_rhr_bpm) * 100`
- `hr_delta_30d_percent = ((hr_avg_bpm - baseline_30d_rhr_bpm) / baseline_30d_rhr_bpm) * 100`

### Insufficient baseline handling
- If `baseline_window_count < 7`, render label: `Building your baseline`.
- Suppress directional recommendation and show confidence cap `medium`.

## 6) Data Quality and Confidence Rules

### Quality grade
- `Good`: `artifact_percent <= 1` and `duration_seconds >= 60`
- `Okay`: `artifact_percent > 1 and <= 3` or `duration_seconds between 45 and 59`
- `Poor`: `artifact_percent > 3` or `duration_seconds < 45`

### Confidence grade
- Start at `high`.
- Downgrade one level if quality is `Okay`.
- Downgrade to `low` if quality is `Poor`.
- Downgrade one level if baseline_window_count < 7.
- Never exceed `medium` when baseline_window_count < 7.

## 7) Interpretation Copy Templates

Use one sentence per metric card.

- RMSSD:
  - Up >= 5% vs 7d: `RMSSD is above your recent baseline, suggesting better short-term recovery.`
  - Down <= -5% vs 7d: `RMSSD is below your recent baseline, which can indicate elevated strain or incomplete recovery.`
  - Otherwise: `RMSSD is near your recent baseline.`

- SDNN:
  - `SDNN reflects overall beat-to-beat variability during this reading.`

- LF/HF ratio:
  - > 3.0: `LF/HF is elevated for this session; consider this a potential stress signal, not a diagnosis.`
  - < 1.0: `LF/HF is low in this session and may reflect stronger parasympathetic influence.`
  - Otherwise: `LF/HF is in a mid-range zone for this session.`

- QTc (if available in source stream):
  - In configured range: `QTc is within configured reference limits for this report.`
  - Out of range: `QTc is outside configured reference limits; review with a clinician if persistent.`

## 8) Action Recommendation Logic (P1-light)

Provide one recommendation string:
- High recovery + high confidence: `Recovery looks favorable. Normal training load is reasonable today.`
- Moderate recovery: `Recovery is mixed. Consider moderate intensity and prioritize sleep tonight.`
- Low recovery or low confidence: `Recovery signal is low-confidence or reduced. Favor easy training and retest under consistent conditions.`

## 9) Acceptance Criteria

- Every report renders all five sections with no blank cards.
- Recovery state appears with exactly 2-3 key drivers.
- Baseline deltas appear for RMSSD and HR when baseline exists.
- Quality and confidence states are always shown.
- Interpretation text appears for RMSSD, SDNN, LF/HF (and QTc when present).
