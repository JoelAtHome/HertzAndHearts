# Beta Tester Instructions (1.0.0-beta.1)

Thanks for testing Hertz & Hearts.

Please follow this process so results are consistent and actionable.

## 1) Before You Start

- Confirm app version and OS version.
- Pair your sensor with the OS first.
- Use realistic session lengths: include at least one short session (about 2-5 minutes) and one medium session (about 10-20 minutes).

## 2) Run The Checklist

Run all items in:

- `docs/PUBLIC_RELEASE_CHECKLIST.md`
- `docs/BLE_PLATFORM_VALIDATION_MATRIX.md` (for Win11 vs Linux BLE reliability comparisons)

Mark each item as:

- Pass
- Fail
- Not applicable

## 3) Report Findings

Use GitHub Issues and include:

- app version
- OS version
- sensor model
- exact reproduction steps
- expected vs actual
- logs/screenshots when available

Recommended templates:

- `bug_report.yml` for defects
- `beta_checklist_feedback.yml` for checklist pass/fail feedback

## 4) Severity Guidance

Use these severity levels in your report title/body:

- Blocker: prevents normal use or causes data loss
- Major: core flow works but with serious reliability/usability issue
- Minor: workaround exists, low risk

## 5) Suggested Test Matrix

Try at least two of the following:

- Stop-only session (then generate report from Session History)
- Stop & Save session (direct report generation)
- disconnect/reconnect while viewing trends
- replay a saved session and verify timeline behavior
- hide/unhide sessions and verify they remain accessible when shown

## 6) Optional Nice-to-Have Notes

If you have time, include:

- setup friction points
- confusing labels/controls
- suggestions that simplify default workflow

Thanks again. Your feedback directly improves release quality.
