# One-Page Shareable PDF Template (v1)

This template is for coach/clinician sharing and should fit on one A4 or US Letter page.

## 1) Layout Blueprint

Use a 12-column grid with compact spacing.

### Header (full width)
- Product name and logo.
- User identifier (name or anonymized ID).
- Measurement timestamp and duration.
- Report type: `HRV Recovery Snapshot`.

### Row A: Executive Summary (left 8 cols) + Confidence (right 4 cols)
- Recovery state badge (`Low`, `Moderate`, `High`).
- Two to three key driver bullets.
- Confidence panel:
  - Quality grade (`Good`, `Okay`, `Poor`)
  - Artifact %
  - Baseline readiness (`Ready` or `Building baseline`)

### Row B: Baseline Comparison (full width)
- Two metric tiles:
  - RMSSD current + delta vs 7d + delta vs 30d
  - HR average current + delta vs 7d + delta vs 30d
- Include arrow glyphs (up/down/flat) and percentage deltas.

### Row C: Metric Details (time domain left 6 cols, frequency domain right 6 cols)
- Time domain cards: RMSSD, SDNN, ln(RMSSD), pNN50, Mean RR.
- Frequency domain cards: LF, HF, LF/HF, Total power (if available).
- Each metric card has:
  - Value + unit.
  - One-line interpretation from P1 rules.

### Row D: Mini Trend Snapshot + Footer
- Left 8 cols: 7-day mini trend for RMSSD and HR (sparklines).
- Right 4 cols: Action recommendation box.
- Footer:
  - Data source and session ID.
  - Research-use disclaimer.
  - Generated timestamp.

## 2) Wireframe (content hierarchy)

```text
+----------------------------------------------------------------------------------+
| HERTZ AND HEARTS | HRV Recovery Snapshot | User | DateTime | Duration            |
+-----------------------------------------+----------------------------------------+
| Recovery: MODERATE                      | Confidence: GOOD                       |
| - RMSSD near baseline                   | Artifact: 0.4%                         |
| - HR slightly elevated                  | Baseline: READY                        |
| - LF/HF in mid-range                    |                                        |
+----------------------------------------------------------------------------------+
| Baseline Comparison                                                           |
| RMSSD 26.4 ms  (+4% vs 7d) (+1% vs 30d)   HR 85 bpm  (+6% vs 7d) (+3% vs 30d) |
+-------------------------------------------+--------------------------------------+
| Time-Domain Metrics                       | Frequency-Domain Metrics              |
| RMSSD 26.4 ms   [interpretation]          | LF 170 ms2       [interpretation]     |
| SDNN 22.1 ms    [interpretation]          | HF 51 ms2        [interpretation]     |
| ln(RMSSD) 2.51  [interpretation]          | LF/HF 3.31       [interpretation]     |
| pNN50 0%        [interpretation]          | Total Power 221  [interpretation]     |
| Mean RR 705 ms  [interpretation]          |                                      |
+-------------------------------------------+--------------------------------------+
| 7-day trend: RMSSD sparkline + HR sparkline | Recommendation                        |
|                                             | Easy/moderate day; retest tomorrow.   |
+----------------------------------------------------------------------------------+
| Disclaimer | Session ID | Generated at                                           |
+----------------------------------------------------------------------------------+
```

## 3) Data Binding Table

| PDF Field | Source Field | Formatting |
| --- | --- | --- |
| Recovery badge | `recovery_state` | Uppercase label + color token |
| Confidence badge | `confidence_state` | Uppercase label + color token |
| Artifact | `artifact_percent` | One decimal + `%` |
| RMSSD tile | `rmssd_ms`, baseline deltas | One decimal + arrows |
| HR tile | `hr_avg_bpm`, baseline deltas | Integer + arrows |
| Metric cards | session metric fields | Value + unit + 1-line interpretation |
| Trend sparkline | last 7 sessions | No axis labels; min/max markers optional |
| Recommendation | action recommendation logic | One sentence |

## 4) Visual and Copy Rules

- Keep card titles and units consistent across app and PDF.
- Use plain language and avoid diagnosis wording.
- Show `Insufficient baseline` when history is incomplete.
- Avoid more than one line of interpretation per metric in PDF.
- Keep total content within one page without overflow.

## 5) Export Variants

- `ClinicalShareCompact`: includes QTc and out-of-range marker if available.
- `CoachShareCompact`: prioritizes recovery and trend readability.

Both variants must preserve the same section order and confidence panel.
