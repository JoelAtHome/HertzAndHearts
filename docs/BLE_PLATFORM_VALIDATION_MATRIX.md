# BLE Platform Validation Matrix

Use this document to compare BLE reliability across Windows 11 and Linux candidates for Hertz & Hearts.

Who should run this:

- Beta testers with supported sensors
- Maintainer/operator (you) as the reference baseline

Goal:

- Identify the platform with the best real-world BLE stability and lowest operational friction.

## Test Scope

Platforms to compare:

- Windows 11 (current desktop baseline)
- Linux test environment (candidate A)
- Linux test environment (candidate B, optional)

Hardware:

- BLE adapter(s): onboard + optional known-good USB adapter
- Sensor(s): Polar H10 (required), additional sensors optional

## Standard Scenarios

Run each scenario multiple times per platform/adapter pair.

1. Cold boot -> launch app -> connect -> 10 min record -> stop/save
2. Mid-session sensor disconnect/reconnect
3. Sensor power cycle during active session
4. App restart and reconnect
5. Sleep/wake then reconnect (if applicable)
6. Repeated short sessions (5 back-to-back runs)

## Suggested Run Counts

- Minimum: 10 runs per scenario/platform
- Preferred: 20 runs per scenario/platform for stronger confidence

## Metrics to Capture

- Connect success rate
- Median connect time (seconds)
- Reconnect success rate
- Session completion rate
- Artifact integrity rate (`session.csv`, `session_manifest.json`, reports)
- Crash/hang count

## Pass/Fail Thresholds (Suggested)

- Connect success >= 95%
- Reconnect success >= 90%
- Session completion >= 95%
- Artifact integrity = 100%
- No unrecoverable hangs across test set

## Failure Taxonomy

When a run fails, classify one primary cause:

- Pairing failure
- Connect timeout
- Mid-session BLE dropout unrecovered
- Reconnect failed
- UI freeze/hang
- Artifact missing/corrupt
- Other (describe)

## Run Log Template

| Date | Tester | Platform | Adapter | Sensor | Scenario | Connect Time (s) | Result (Pass/Fail) | Failure Type | Notes |
|---|---|---|---|---|---|---:|---|---|---|
| YYYY-MM-DD | initials | Win11 / Linux A | adapter model | Polar H10 | S1 | 6.2 | Pass | - | - |

## Summary Table Template

| Platform | Adapter | Total Runs | Connect Success % | Reconnect Success % | Completion % | Artifact Integrity % | Crashes/Hangs | Recommendation |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Windows 11 | Intel AX... | 120 | 93.3 | 85.0 | 90.8 | 100 | 2 | Needs tuning |
| Linux A | USB dongle X | 120 | 98.3 | 96.7 | 97.5 | 100 | 0 | Preferred |

## Decision Rule

Select the deployment platform that:

1. Meets thresholds consistently
2. Shows the fewest recoverability issues
3. Is simplest to support in field operations

If no platform meets thresholds, do not promote to production deployment. Fix blockers and rerun.

## Notes for Beta Testers

- Use the same sensor placement and environment when possible.
- Record exact steps for failures (timing matters with BLE).
- Attach screenshots/log snippets when available.
