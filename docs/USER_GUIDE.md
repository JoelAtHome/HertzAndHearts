# User Guide

This is the short practical guide for day-to-day use.

## 1) Connect a Sensor

1. Pair your chest strap in your operating system Bluetooth settings.
2. Open Hertz & Hearts.
3. Click `Scan`.
4. Select your sensor from the dropdown.
5. Click `Connect`.

If connection fails, try `Disconnect` then reconnect.

## 2) Start and Run a Session

1. Select user/profile if prompted.
2. Click `Start New`.
3. Monitor live metrics during the session.
4. Add annotations as needed.

### Morning baseline protocol (optional)

For **more comparable day-to-day trends**, you can enable **Morning baseline** on the main toolbar (next to `Start New` / `Stop & Save`).

- The choice is saved **per user profile**.
- When enabled and you are **actively recording**, a short **protocol banner** appears (e.g. aim for 3–5 minutes, same posture, before caffeine when possible, after waking when practical).
- **Why this protocol?** — use the **Why this protocol?** link in the banner for a plain-language explanation.
- Your finalized session folder’s `session_manifest.json` includes `trend_guidance.morning_baseline_protocol` when this mode was on—useful if you later review or export data.

This is **wellness / research context only**, not medical advice.

## 3) End Session

- `Stop`: end session and keep data artifacts without immediate final report flow.
- `Stop & Save`: finalize session and generate report artifacts.

## 4) Access History and Replay

1. Open `More -> History / Session Replay`.
2. Select a session to review.
3. Use Replay controls to inspect timeline.
4. Use `Generate report` for past sessions as needed.

## 5) Session Trends, Compare, and Tag Insights

1. Open `More -> Trend / Compare / Insight`.
2. **Trend Plots** — long-term view of saved session averages (e.g. HR, RMSSD, SDNN, QTc).
3. **Compare** — pick multiple sessions and see a side-by-side table with deltas.
4. **Tag Insights** — exploratory links between your annotations and metric shifts (association, not causation).

### RMSSD recovery zones (Tier 1)

Under the main trend chart you’ll see a **second plot** that shows **RMSSD only**, with **green / amber / red** horizontal bands.

- Bands are based on **your own recent sessions**, not population norms. The app uses the **latest** session’s average RMSSD and compares it to the **mean and spread** of **earlier** sessions in a **baseline window** (default **14** sessions; you can change 3–60). The setting is saved **per profile** (`tier1_recovery_baseline_sessions` in storage).
- **Why these zones?** — click the button for a short explanation of what the colors mean.
- **Red / amber / green** are simple **personal** cues (e.g. lower RMSSD vs your recent norm). They are **not** a diagnosis and can be affected by posture, sleep, caffeine, stress, breathing, and signal quality.

## 6) Reports

Typical report artifacts per finalized session:

- `session_report.docx`
- `session_share.pdf`

For a stopped session without final report, generate from Session History.

## 7) Data Location (Dual-Boot Safety)

- Open `Settings -> Data` to see your active data folder.
- On Windows, new installs default to `%LOCALAPPDATA%\Hertz-and-Hearts`.
- On Linux, new installs default to `~/.local/share/hertz-and-hearts`.
- If the app detects legacy Windows data under `~/Hertz-and-Hearts`, use
  `Move Data to Recommended Location…` in `Settings -> Data`, then restart.
- Advanced users can override the data root with `HNH_DATA_DIR`.

## 8) Troubleshooting

- See `docs/troubleshooting.md`
- If BLE behavior varies by platform, use `docs/BLE_PLATFORM_VALIDATION_MATRIX.md`

## 9) Important Safety/Scope Notes

- Research and educational workflow support only.
- Not for clinical diagnosis or treatment decisions.
