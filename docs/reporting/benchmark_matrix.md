# Reporting Benchmark Matrix

This matrix compares the current Hertz and Hearts reporting baseline against patterns used in Oura, WHOOP, Garmin Health Snapshot, and Elite HRV.

## Snapshot of Current Baseline

- Strong raw metric coverage: heart rate min/max/mean, RMSSD, SDNN, ln(RMSSD), pNN50, mean RR, LF/HF power.
- Includes outlier boundaries and signal quality/artifact rate.
- Gaps: minimal interpretation, no personal baseline trend framing, no behavior links, weak share/coach summary format.

## Side-by-Side Matrix

| Area | Hertz and Hearts (Current) | Oura Pattern | WHOOP Pattern | Garmin Snapshot Pattern | Elite HRV Pattern | Gap Severity |
| --- | --- | --- | --- | --- | --- | --- |
| Executive summary | Mostly raw values; no concise "state today" label | Readiness score + contributors | Recovery % with color zones | 2-minute summary card | Data details view | High |
| Baseline context | Population reference ranges only | Personal baseline vs recent deviation | Typical range + daily recovery context | Session min/max/avg framing | Trend context in app/dashboard | High |
| Interpretation | Little "what this means" guidance | Contributor explanations | Plain-language behavior impact | Compact explanations around vitals | Metric education articles | High |
| Data quality confidence | Artifact/noise included | Indirect quality confidence | Sensor reliability expected, little explicit | Device quality assumed | Explicit signal quality grade | Medium |
| Trend views | Not prominent in exported report | Weekly/monthly trends | Longitudinal recovery/strain/sleep | Repeated snapshots over time | Ongoing metric tracking | High |
| Behavior correlations | Not present | Tags influence context | Journal behaviors (sleep, alcohol, stress) | Minimal lifestyle linkage | Notes/context possible | High |
| Shareable report | Multi-page technical export | App reports and exports | Coach/team sharing patterns | Structured export formats | Detailed data view for users | Medium |
| Persona modes | Single report style | Consumer wellness style | Performance coaching style | Snapshot utility style | Biofeedback enthusiast style | Medium |
| Raw export portability | PDF only in current flow | Export options available | Platform analytics focus | CSV/JSON export oriented | Data and interpretation mix | Medium |

## Feature Opportunities Mapped to Gaps

| Proposed Feature | Closes Which Gap | Source Pattern to Borrow |
| --- | --- | --- |
| Recovery status + top drivers card | Missing executive summary | Oura, WHOOP |
| Today vs 7-day and 30-day baseline deltas | Missing personal context | Oura, Garmin |
| Metric interpretation snippets per card | Low interpretability | Oura, Elite HRV |
| Quality confidence badge using artifact and duration | Unclear confidence | Elite HRV |
| Weekly/monthly trend block | Missing trend visibility | Oura, WHOOP |
| Context tags (alcohol, sleep, training load, illness) | Missing behavior linkage | WHOOP |
| One-page share/coach PDF | Weak share utility | Garmin Snapshot |
| CSV/JSON export for advanced users | Limited portability | Garmin |

## Recommended Adoption Priority

1. P1: Summary, baselines, interpretation, confidence, one-page share PDF.
2. P2: Trends + behavior tags + personalized thresholds + action recommendations.
3. P3: Persona modes, anomaly detection, raw export.
