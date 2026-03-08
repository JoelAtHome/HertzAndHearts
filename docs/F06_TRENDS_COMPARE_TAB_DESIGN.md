# F06: Trends Window — 2-Tab Layout (Compare Tab Design)

Design for integrating the serial session comparison view into the existing Trends window as a second tab. No backend implementation; UI layout and interaction spec only.

---

## Overview

The Trends window gains a **tab bar** with two tabs:

| Tab | Label | Default | Content |
|-----|-------|---------|---------|
| 1 | **Trend Plots** | ✓ Yes | Current time-series plot (HR, RMSSD, SDNN, QTc over sessions) |
| 2 | **Compare** | No | Comparison table with session selection and metric selection |

---

## Tab 1: Trend Plots (unchanged)

- Existing behavior: profile selector, pan/zoom, draggable cursor, hover values.
- No changes to layout or logic.
- Remains the default tab when the window opens.

---

## Tab 2: Compare — Layout

### Top: Controls row

```
[Profile: ▼ Jane Doe    ]  [Metrics: ☑ HR  ☑ RMSSD  ☑ SDNN  ☑ QTc  ☑ LF/HF]  [Clear selection]
```

- **Profile selector** — Same as Tab 1; filters sessions by profile.
- **Metrics checkboxes** — Which metrics to include in the table. Default: HR, RMSSD, SDNN, QTc checked; LF/HF optional.
- **Clear selection** — Deselects all sessions from the comparison set.

### Left: Session list (scrollable)

```
Sessions (select 2+ to compare)
─────────────────────────────
☐ Mar 7, 2025  09:15  —  12 min
☐ Mar 6, 2025  14:30  —  18 min
☐ Mar 5, 2025  10:00  —  15 min
☐ Mar 4, 2025  08:45  —  20 min
☐ Mar 3, 2025  16:20  —  10 min
...
```

- List of sessions for the selected profile (same source as `list_session_trends` / session history).
- Each row: checkbox, date/time, duration.
- Checkbox-add sessions to the comparison set.
- Minimum 2 sessions required to show the table; 1 or 0 shows placeholder: *"Select 2 or more sessions to compare."*
- Optional: "Select last 3" / "Select last 5" quick actions.

### Right: Comparison table

When 2+ sessions are selected:

```
                │ Mar 7 09:15 │ Mar 6 14:30 │ Mar 5 10:00 │ Δ (7→6) │ Δ (6→5)
────────────────┼─────────────┼─────────────┼─────────────┼─────────┼─────────
HR (bpm)        │ 72          │ 68          │ 71          │ -4      │ +3
RMSSD (ms)      │ 48          │ 52          │ 45          │ +4      │ -7
SDNN (ms)       │ 42          │ 45          │ 40          │ +3      │ -5
QTc (ms)        │ 420         │ 418         │ 425         │ -2      │ +7
```

- **Columns**: One per selected session (chronological order, newest first or user-defined).
- **Rows**: One per selected metric (only metrics with checkboxes checked).
- **Delta columns**: Δ between adjacent sessions (Session N → Session N-1).
- **Empty cells**: Use "—" when a metric is unavailable for a session.
- Optional: confidence badges per cell (future F04 integration).

### Placeholder state (0 or 1 session selected)

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Select 2 or more sessions from the list to compare.           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Interaction Summary

| Action | Result |
|--------|--------|
| Open Trends | Tab 1 (Trend Plots) shown by default |
| Switch to Compare tab | Session list loads; table empty until 2+ selected |
| Check session A, then B | Table appears with A and B columns + one Δ column |
| Check session C | Table adds C column + second Δ column |
| Uncheck a session | Table updates; if &lt; 2 selected, show placeholder |
| Uncheck a metric | Row removed from table |
| Clear selection | All session checkboxes unchecked; placeholder shown |
| Change profile | Session list and table refresh for new profile |

---

## Wireframe (Tab 2)

```
+--------------------------------------------------------------------------------------------------+
| Hertz & Hearts — Session Trends                                                                  |
| [Trend Plots] [Compare]                                                                           |
+--------------------------------------------------------------------------------------------------+
| Profile: [Jane Doe ▼]   Metrics: ☑ HR ☑ RMSSD ☑ SDNN ☑ QTc ☐ LF/HF   [Clear selection]             |
+---------------------------+----------------------------------------------------------------------+
| Sessions (select 2+)      |                                                                      |
| ─────────────────────    |   Mar 7 09:15   Mar 6 14:30   Mar 5 10:00   Δ (7→6)   Δ (6→5)        |
| ☑ Mar 7, 2025  09:15 12m |   ───────────   ───────────   ───────────   ───────   ───────        |
| ☑ Mar 6, 2025  14:30 18m |   HR (bpm)      72            68            71         -4      +3    |
| ☑ Mar 5, 2025  10:00 15m |   RMSSD (ms)    48            52            45         +4      -7    |
| ☐ Mar 4, 2025  08:45 20m |   SDNN (ms)     42            45            40         +3      -5    |
| ☐ Mar 3, 2025  16:20 10m |   QTc (ms)      420           418           425        -2      +7    |
| ...                       |                                                                      |
+---------------------------+----------------------------------------------------------------------+
| (Hint: Use Trend Plots tab for time-series view.)                                                |
+--------------------------------------------------------------------------------------------------+
```

---

## Data Selection for Comparison

- **Session list**: Same data source as Tab 1 (`list_session_trends` or equivalent). Show date, time, duration. Order: newest first.
- **Table cells**: Per-session values for each metric (avg_hr, avg_rmssd, avg_sdnn, qtc_ms, lf_hf if available). Backend already stores these in `session_trends` / manifest.
- **Deltas**: Computed in UI: `value[N] - value[N-1]` for adjacent columns. Display with sign (+/−) and unit.

---

## Out of Scope (for this design)

- Backend changes (assume existing `session_trends` / history APIs suffice).
- Confidence badges (F04).
- Export of comparison table to CSV/PDF.
- Session reordering (drag to change column order).

---

## Relation to F06 Wishlist Item

This design fulfills F06 ("Serial session comparison view") by:

- Providing a dedicated comparison view with aligned metrics and deltas.
- Integrating into Trends (no new top-level button).
- Allowing explicit session selection via checkboxes.
- Allowing metric selection via checkboxes.
- Defaulting to Trend Plots to preserve current workflow.
