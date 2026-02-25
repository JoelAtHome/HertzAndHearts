# IBI 1:1 Wiring Validation Checklist

Use this procedure to validate that incoming `ibi_update` events map 1:1 to
`update_ibis_buffer` processing during live streaming.

---

## Test Metadata

- Tester:
- Date:
- App version/commit:
- Sensor model:
- OS:

---

## Preconditions

- Sensor is paired and available.
- App starts normally.
- Debug mode is ON (`Ctrl+Alt+click top bar` until `DEBUG ON` badge appears).
- Python console is visible so debug logs can be read.

Expected debug telemetry every ~10 seconds when connected:

- `"[IBI-DIAG] OK total beats=<n> updates=<n> delta=0 ..."`
- Any non-zero `delta` prints `"[IBI-DIAG] WARNING ..."`

---

## Procedure A - Baseline Live Stream (2-3 minutes)

- Connect sensor.
- Stream for 2-3 minutes without disconnecting.
- Observe at least 8-12 `IBI-DIAG` lines.
- Confirm `delta=0` for all intervals (or only brief startup transient that returns to 0).

Result notes:

- Max observed absolute delta:
- Any persistent WARNING lines:

---

## Procedure B - Disconnect/Reconnect Regression

- While connected, click `Disconnect`.
- Reconnect to the same sensor.
- Stream for at least 60 seconds.
- Confirm telemetry remains `delta=0` after reconnect stabilization.
- Confirm no visible "double-speed" chart behavior.

Result notes:

- Reconnect result:
- Any anomalies:

---

## Procedure C - Reset Baseline Regression

- While connected and streaming, click `Reset Baseline`.
- Continue streaming for at least 60 seconds.
- Confirm telemetry remains `delta=0` after reset.
- Confirm chart responsiveness appears normal.

Result notes:

- Reset result:
- Any anomalies:

---

## Procedure D - Recording Path Smoke Check

- Start session recording.
- Stream at least 60 seconds.
- Confirm telemetry remains `delta=0`.
- Finalize/save session.
- Confirm session artifacts are created successfully.

Result notes:

- Recording path result:
- Any anomalies:

---

## Pass/Fail Criteria

Pass if all are true:

- No sustained non-zero `delta` during normal streaming.
- No recurrent `IBI-DIAG WARNING` after stabilization.
- No obvious chart-rate duplication after reconnect or reset.
- Recording flow behaves normally.

If failed, capture:

- Timestamp(s):
- Scenario (A/B/C/D):
- Relevant console lines:
- Repro steps:

---

## Completion Statement (for WISHLIST)

Use this note when validation passes:

> Verified 1:1 `ibi_update` to `update_ibis_buffer` behavior under live streaming,
> including connect/reconnect/reset and recording-path smoke checks. No duplicate
> processing regression observed.

