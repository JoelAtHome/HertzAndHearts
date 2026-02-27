# VNS-TA v1.1.0 — Manual Test Specification & Checklist

> **Purpose:** Verify every user-facing function of VNS-TA for correct behavior and accuracy.
> **Equipment needed:** Polar H10 chest strap (preferred — enables ECG tests), or Polar H7/H9, or Decathlon Dual HR. A secondary sensor is helpful for some connection tests.
> **Environment:** Windows 10+ or Ubuntu 24.04. Bluetooth enabled and working.

---

## How to Use This Checklist

- Work through each section in order (later sections depend on earlier ones).
- Mark each item: **PASS**, **FAIL**, or **N/A** (if hardware doesn't support it).
- For **FAIL** items, note the observed behavior.
- "Steady signal" = strap is wet and worn snugly on the chest, user is still.
- "Noisy signal" = strap is dry or loosely placed.

---

## 1. Application Launch & Window

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 1.1 | Launch VNS-TA from terminal (`vns-ta`) or shortcut | Window opens maximized. Title bar reads `VNS-TA <version>`. App icon (logo) is visible in title bar and taskbar. | |
| 1.2 | Verify Control Panel is visible | Left side shows "Control Panel" group box with Scan, address dropdown, Connect, Disconnect, Reset Baseline, and ECG Monitor buttons. | |
| 1.3 | Verify numeric labels initial state | Heart Rate: `-- bpm`, RMSSD: `-- ms`, HRV/SDNN: `-- ms`, Stress Ratio (LF/HF): `--` | |
| 1.4 | Verify charts are present | Two chart areas visible: top (Heart Rate bpm) and bottom (HRV metrics). Both are empty with axis labels. | |
| 1.5 | Verify pacer is visible | Breathing pacer widget (lung-shaped outline) is visible with rate slider and "Show Pacer" checkbox. | |
| 1.6 | Verify recording panel | Start, Save, Annotation dropdown, and Annotate buttons are visible. Start is enabled, Save is disabled. | |
| 1.7 | Verify status bar | Bottom status bar shows signal quality indicator. Initial state: gray dot with "Signal: Identifying..." | |
| 1.8 | Verify progress bar | Progress bar displays "Waiting for Sensor..." | |
| 1.9 | Verify button initial states | Connect is enabled. Disconnect is disabled. Reset Baseline is disabled. ECG Monitor is enabled. | |

---

## 2. Sensor Scanning

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 2.1 | Click **Scan** with sensor powered on and in range | After up to ~10 seconds, the address dropdown populates with the sensor name and address (e.g., `Polar H10, XX:XX:XX:XX:XX:XX`). | |
| 2.2 | Click **Scan** with NO sensor in range | After ~10 seconds, dropdown remains empty or shows no new entries. No crash or hang. | |
| 2.3 | Click **Scan** with Bluetooth disabled on PC | Application handles gracefully — does not crash. An error message or empty result is acceptable. | |
| 2.4 | Click **Scan** with multiple compatible sensors in range | All compatible sensors appear in the dropdown. Verify each shows correct name and address. | |
| 2.5 | Verify incompatible devices are filtered out | Non-Polar / non-Decathlon BLE devices in range do NOT appear in the dropdown. | |
| 2.6 | Click **Scan** multiple times | Dropdown updates on each scan without duplicates accumulating. No crash. | |

---

## 3. Sensor Connection

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 3.1 | Select a sensor from dropdown and click **Connect** | Progress bar changes to "Connecting to Sensor... Please wait." Then transitions to "Settling... 15s" and begins counting down. Connect button becomes disabled. | |
| 3.2 | Verify HR data begins arriving | Within a few seconds of connection, the Heart Rate label updates from `--` to a numeric value (e.g., `72 bpm`). The top chart starts plotting data. | |
| 3.3 | Verify sensor persistence | Close and relaunch VNS-TA. The address dropdown should be pre-populated with the last connected sensor's name and address (from `~/.vns_ta_last_sensor.json`). | |
| 3.4 | Connect using pre-populated (saved) sensor without scanning | Click **Connect** directly using the saved sensor entry. Connection succeeds without needing to scan first. | |
| 3.5 | Attempt to connect with no sensor selected | Connect button should do nothing harmful or should show an appropriate status. No crash. | |
| 3.6 | Attempt to connect when sensor is out of range | Connection fails gracefully. Progress bar or status bar shows an error/disconnect message. No hang or crash. | |
| 3.7 | Click **Connect** while already connected | Should be prevented (button disabled) or handled gracefully. No double-connection. | |

---

## 4. Sensor Disconnection

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 4.1 | Click **Disconnect** while connected | Connection terminates. Progress bar shows "Sensor Disconnected". Connect button re-enables. Disconnect button disables. | |
| 4.2 | Verify charts stop updating | After disconnect, no new data points appear on either chart. Existing data remains visible. | |
| 4.3 | Verify numeric labels after disconnect | Heart Rate, RMSSD, HRV/SDNN, and Stress Ratio stop updating (may show last value or reset to `--`). | |
| 4.4 | Reconnect after disconnect | Click Connect again. Connection succeeds. All buffers and charts are cleared. A fresh settling phase begins. | |
| 4.5 | Sensor powers off / goes out of range mid-session | Within 5 seconds, signal quality shows "Signal: LOST (No data)". Buffers are cleared. | |

---

## 5. Calibration Phase Engine

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 5.1 | **Settling phase (0–15s):** Observe progress bar after connecting | Progress bar shows "Settling... Xs" counting down from 15 to 0. Data is plotted on charts during this time. | |
| 5.2 | **Baseline phase (15–45s):** Observe progress bar after settling completes | Progress bar transitions to "Baseline... Xs" counting down from 30 to 0. RMSSD values are being accumulated. | |
| 5.3 | **Lock event (at 45s):** Observe progress bar when baseline completes | Progress bar changes to "LOCKED: X.Xms" showing the computed baseline RMSSD value. | |
| 5.4 | Verify baseline reference line appears on HRV chart | After lock, a red dotted horizontal line appears on the bottom chart at the baseline RMSSD value. | |
| 5.5 | Verify Reset Baseline button enables after lock | The Reset Baseline button becomes clickable only after the baseline has locked. | |
| 5.6 | Click **Reset Baseline** | All buffers clear. Charts reset. Phase engine restarts from Settling (15s countdown). Reset Baseline button disables again. Baseline reference line disappears. | |
| 5.7 | Verify baseline accuracy | During baseline phase, note the RMSSD values displayed. The locked baseline value should be approximately the mean of the RMSSD values observed during the 30-second baseline window. | |

---

## 6. Heart Rate Chart (Top Chart)

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 6.1 | Verify HR line plots correctly | A solid black line tracks heart rate over time. Values should correspond to the numeric HR label. | |
| 6.2 | Verify EWMA trend line | A blue dotted line tracks a smoothed trend of HR. It should lag behind rapid HR changes and be smoother than the main line. | |
| 6.3 | Verify legend | Legend at top of chart identifies the two lines (HR and EWMA trend). | |
| 6.4 | Verify X-axis shows rolling 60-second window | As time passes, the X-axis scrolls. Only ~60 seconds of data are visible at a time. | |
| 6.5 | Verify Y-axis "expand only" behavior | Raise HR (e.g., brief exercise). Y-axis expands to fit. When HR returns to normal, Y-axis does NOT shrink back. Minimum span is ~40 bpm. | |
| 6.6 | Verify HR calculation accuracy | Heart Rate ≈ `60000 / IBI_in_ms`. If wearing a sensor at rest and seeing IBIs around 800ms, HR should read ~75 bpm. Cross-check with the sensor's own app or a pulse oximeter if available. | |
| 6.7 | Verify smoothing behavior | Line should not be jagged beat-to-beat. It uses a moving average over ~18 seconds of beats at 60bpm. Sudden changes should appear gradually. | |

---

## 7. HRV Chart (Bottom Chart)

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 7.1 | Verify RMSSD line (black, left axis) | A black line plots RMSSD over time on the left Y-axis. Values correspond to the RMSSD numeric label. | |
| 7.2 | Verify SDNN line (blue, right axis) | A blue line plots HRV/SDNN on the right Y-axis. Values correspond to the HRV/SDNN numeric label. | |
| 7.3 | Verify baseline reference line (after lock) | Red dotted horizontal line at the locked baseline RMSSD value. Persists until reset. | |
| 7.4 | Verify X-axis shows rolling 60-second window | Similar to HR chart, scrolls with time. | |
| 7.5 | Verify Y-axes "expand only" behavior | Y-axes grow in steps of 5 to fit data. They do not shrink when values decrease. | |
| 7.6 | Verify RMSSD accuracy | RMSSD should be the root mean square of successive IBI differences over the last ~60 beats. At rest with steady signal, typical values: 20–80ms. Verify it's clamped to [0, 250]. | |
| 7.7 | Verify SDNN accuracy | SDNN = standard deviation of the last 30 IBIs. At rest, typical: 30–100ms. | |
| 7.8 | Verify RMSSD smoothing | Similar to HR, the RMSSD line should be smoothed (moving average). Not instantaneously jumpy. | |

---

## 8. Stress Ratio (LF/HF)

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 8.1 | Verify LF/HF label updates | After sufficient data (≥20 RR intervals, typically after ~20–30 seconds), the Stress Ratio label updates from `--` to a numeric value. | |
| 8.2 | Verify LF/HF updates periodically | The value updates every 5th IBI. Observe it changing over time. | |
| 8.3 | Verify LF/HF range is plausible | At rest: typically 0.5–3.0. Under stress/exertion: may be higher. Value should never be negative. | |
| 8.4 | Verify LF/HF does not update with < 20 intervals | Immediately after connecting (first ~20 beats), the label should remain `--`. | |

---

## 9. Breathing Pacer

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 9.1 | Verify pacer animation | The lung-shaped blue disk expands and contracts rhythmically in a sinusoidal pattern. | |
| 9.2 | Adjust rate slider to minimum (leftmost) | Breathing rate slows to 4.0 breaths/min. Label updates to show the rate. Pacer animation visibly slows. | |
| 9.3 | Adjust rate slider to maximum (rightmost) | Breathing rate increases to 7.0 breaths/min. Label updates. Pacer animation visibly speeds up. | |
| 9.4 | Verify rate label accuracy | The displayed rate matches the expected value for the slider position. Slider range is 1–15 ticks. | |
| 9.5 | Uncheck **Show Pacer** | The animated blue disk disappears and is replaced by a static gray lung outline. | |
| 9.6 | Re-check **Show Pacer** | The animated blue disk resumes at the current rate setting. | |
| 9.7 | Verify pacer is 200x200 pixels (approximate) | The pacer widget should be roughly square and a fixed size. It should not resize with the window. | |
| 9.8 | Verify pacer timing accuracy | With a stopwatch, time 5 full breath cycles at the lowest rate (4.0/min). Expected: ~75 seconds (15s per cycle). Tolerance: ±2 seconds. | |

---

## 10. Signal Quality Detection

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 10.1 | **Good signal:** Wear strap snugly and wet | Status bar: green dot, "Signal: GOOD". | |
| 10.2 | **Noisy signal:** RMSSD > 200ms | Status bar: orange dot, "Signal: NOISY". | |
| 10.3 | **Poor signal:** RMSSD > 240ms (dry strap) | Status bar: red dot, "Signal: POOR (Dry?)". | |
| 10.4 | **Level 1 fault (dropout):** Remove strap briefly (IBI > 3000ms) | Status bar: red dot, "FAULT: Clearing Buffer...". All buffers are cleared. | |
| 10.5 | **Level 2 fault (noise):** Cause extreme artifact (IBI < 300ms or > 2000ms) | Status bar: red dot, "Signal: DROP/NOISE". | |
| 10.6 | **Level 3 fault (erratic):** Cause >30% deviation from rolling average | Status bar: red dot, "Signal: ERRATIC (avg X)". | |
| 10.7 | **Fault recovery:** After a fault, wear strap properly for ≥10 good beats | Signal quality returns to green "Signal: GOOD" after 10 consecutive normal beats. Buffers are reset. | |
| 10.8 | **Signal lost:** Disconnect or turn off sensor, wait 5 seconds | Status bar: red dot, "Signal: LOST (No data)". Buffers are cleared. | |
| 10.9 | Verify signal quality transitions smoothly | Moving between states should not cause flickering or crashes. States should transition in the expected order. | |

---

## 11. ECG Monitor (Polar H10 Only)

> Mark all as **N/A** if not using a Polar H10.

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 11.1 | Click **ECG Monitor** while connected to Polar H10 | A separate window opens titled "VNS-TA -- ECG Monitor" (min 600x300). Status bar shows "Waiting for ECG data..." then transitions to "ECG streaming...". | |
| 11.2 | Verify ECG waveform displays | An oscilloscope-style ECG trace appears, sweeping left to right. QRS complexes (tall spikes) are visible. | |
| 11.3 | Verify R-peak triggering | The trace should re-trigger (start from the left) on each R-peak, creating a stable, non-scrolling display similar to a bedside monitor. | |
| 11.4 | Verify X-axis shows ~5 seconds | The X-axis label reads "Last 5 Seconds". Approximately 5 seconds of ECG are visible. | |
| 11.5 | Verify Y-axis auto-scaling | Y-axis label reads "ECG (mV)". Scale adjusts smoothly to fit the waveform amplitude. | |
| 11.6 | Click **Freeze** button | ECG display freezes. Status bar shows "ECG frozen." Button text changes to "Resume". | |
| 11.7 | Click **Resume** button | ECG display resumes streaming. Status bar shows "ECG streaming." Button text changes to "Freeze". | |
| 11.8 | Close the ECG window (X button or Close ECG button) | ECG window closes. ECG Monitor button on main window re-enables / changes label. ECG streaming stops. No crash. | |
| 11.9 | Click **ECG Monitor** with a non-H10 sensor (Polar H7/H9) | ECG functionality is gracefully unavailable. No crash — button may be inert or show a message. | |
| 11.10 | Verify ECG refresh rate is smooth (~30fps) | The waveform should render smoothly without visible stuttering or frame drops. | |

---

## 12. Session Recording (CSV Logger)

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 12.1 | Click **Start** while connected | A save-file dialog opens. Default filename format: `VNS-TA_YYYY-MM-DD-HH-MM.csv`. | |
| 12.2 | Choose a valid save location and confirm | Recording begins. Start button disables, Save button enables. | |
| 12.3 | Let recording run for ≥30 seconds | File should be growing in size on disk. | |
| 12.4 | Click **Save** | Recording stops. File is saved and closed. Save button disables, Start button re-enables. | |
| 12.5 | Open the CSV file | File contains rows in `event,value,timestamp` format. Verify headers and data rows are present and well-formed. | |
| 12.6 | Verify IBI events are logged | Look for IBI/RR event rows. Values should be in milliseconds (typical: 600–1200ms). Timestamps should be sequential. | |
| 12.7 | Click **Start**, then cancel the file dialog | No recording starts. No crash. Start button remains enabled. | |
| 12.8 | Attempt to save to an invalid path | Application handles gracefully. Error message or dialog — no crash. | |

---

## 13. Annotations

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 13.1 | Type text into the Annotation dropdown | Free-text entry is accepted. Text appears in the combo box. | |
| 13.2 | Click **Annotate** while recording | The annotation text is written to the CSV file as an annotation event row. | |
| 13.3 | Click **Annotate** while NOT recording | No crash. Annotation may be silently discarded or button may be disabled. | |
| 13.4 | Enter empty annotation and click **Annotate** | Should handle gracefully — either ignored or logged as empty. No crash. | |
| 13.5 | Enter a very long annotation string (500+ chars) | Application handles without crash or truncation issues. | |
| 13.6 | Enter special characters in annotation (`"`, `,`, newlines) | CSV file handles escaping correctly. Data is not corrupted. | |

---

## 14. IBI Validation & Outlier Handling

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 14.1 | Verify first 11 beats pass through raw | Immediately after connecting, the first ~11 IBI values should appear on the chart without median filtering. | |
| 14.2 | Verify outlier replacement after 11 beats | After 11+ beats, an out-of-range IBI (e.g., artifact spike) should be replaced by the median of the last 11 values. The chart should not show extreme spikes. | |
| 14.3 | Verify IBI clamping | No plotted IBI should fall below ~273ms (220 bpm) or above 2000ms (30 bpm). | |
| 14.4 | Verify HRV outlier handling | RMSSD values above 600 should be replaced with the EWMA value (capped at 600). Display is clamped to [0, 250]. | |

---

## 15. EWMA Trend

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 15.1 | Verify EWMA line lags behind HR changes | During a deliberate HR change (e.g., stand up quickly), the blue dotted EWMA line should respond more slowly than the black HR line. | |
| 15.2 | Verify EWMA smoothness | The EWMA line should be very smooth with no sharp jumps. Weight is 0.05 for the chart display trend (low responsiveness). | |

---

## 16. Edge Cases & Stress Tests

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 16.1 | Run VNS-TA for 30+ minutes continuously | No memory leaks (RAM usage stays stable). No crashes. Charts continue scrolling. All metrics update. | |
| 16.2 | Resize the application window | Charts and UI elements resize gracefully. Pacer widget stays ~200x200. No overlapping or clipping. | |
| 16.3 | Minimize and restore the window | Application resumes correctly. Data continues to be collected in the background. Charts update on restore. | |
| 16.4 | Disconnect and reconnect rapidly (3–5 times) | Each cycle completes cleanly. No accumulated errors or ghost connections. Settling phase restarts each time. | |
| 16.5 | Scan while connected | Scanning should not disrupt the active connection. Dropdown may update with additional devices. | |
| 16.6 | Start recording before connecting a sensor | Recording should either be prevented or result in an empty/minimal CSV (no data events). No crash. | |
| 16.7 | Connect, lock baseline, disconnect, reconnect | After reconnection, baseline is cleared. Phase engine restarts. Old baseline line disappears. | |
| 16.8 | Close the application while connected | Application closes cleanly. BLE connection is terminated. No orphaned processes. | |
| 16.9 | Close the application while recording | Recording file is saved/closed properly. No data corruption. | |
| 16.10 | Open ECG window, then disconnect sensor | ECG window status shows "ECG stopped." or closes gracefully. No crash. | |

---

## 17. Cross-Check: Numeric Label ↔ Chart Consistency

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 17.1 | Compare HR label to HR chart | The numeric HR label value should correspond to the most recent point on the top chart's HR line (accounting for smoothing). | |
| 17.2 | Compare RMSSD label to RMSSD chart | The numeric RMSSD label should correspond to the most recent point on the bottom chart's black line. | |
| 17.3 | Compare HRV/SDNN label to SDNN chart | The numeric HRV/SDNN label should correspond to the most recent point on the bottom chart's blue line. | |
| 17.4 | Verify locked baseline value matches red line position | The "LOCKED: X.Xms" value in the progress bar should match the Y-value of the red dotted line on the HRV chart. | |

---

## 18. QTc Presentation Format (Phased)

> Run these checks when QTc surfacing is enabled. Until then, mark as **N/A**.

| #   | Test | Expected Result | Status |
|-----|------|-----------------|--------|
| 18.1 | Verify end-of-session QTc summary label | Post-session/report output uses `QTc (session)` label and includes one canonical session value or unavailability message. | |
| 18.2 | Verify quality-gated unavailable state | If QTc quality requirements are not met, output shows `QTc unavailable (signal quality too low)` or equivalent non-numeric unavailable text. | |
| 18.3 | Verify canonical summary method | Session QTc is computed from the agreed canonical method (valid-window median), not an arbitrary instantaneous sample. | |
| 18.4 | Verify trend visibility default | Dedicated QTc trend is hidden by default and only shown when explicitly enabled. | |
| 18.5 | Verify trend safety copy | When QTc trend is shown, UI/report includes `For trend context only; clinical interpretation requires review.` | |
| 18.6 | Verify report/manifest consistency | Session report and `session_manifest.json` agree on QTc availability, value, and trend-enabled state. | |

---

## Results Summary

| Section | Total | Pass | Fail | N/A |
|---------|-------|------|------|-----|
| 1. Launch & Window | 9 | | | |
| 2. Sensor Scanning | 6 | | | |
| 3. Sensor Connection | 7 | | | |
| 4. Sensor Disconnection | 5 | | | |
| 5. Calibration Phases | 7 | | | |
| 6. HR Chart | 7 | | | |
| 7. HRV Chart | 8 | | | |
| 8. Stress Ratio | 4 | | | |
| 9. Breathing Pacer | 8 | | | |
| 10. Signal Quality | 9 | | | |
| 11. ECG Monitor | 10 | | | |
| 12. Session Recording | 8 | | | |
| 13. Annotations | 6 | | | |
| 14. IBI Validation | 4 | | | |
| 15. EWMA Trend | 2 | | | |
| 16. Edge Cases | 10 | | | |
| 17. Label ↔ Chart Consistency | 4 | | | |
| 18. QTc Presentation Format | 6 | | | |
| **TOTAL** | **119** | | | |

**Tested by:** _______________  
**Date:** _______________  
**VNS-TA Version:** _______________  
**Sensor Used:** _______________  
**OS / Platform:** _______________  
