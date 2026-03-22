Hertz and Hearts known-good test log template

Purpose
- Record the environment used for each successful (or failed) smoke test.
- Keep one log entry per test run to make regressions easy to track.

How to use
1) Run your source and/or packaged smoke tests.
2) Capture requirements snapshot as described in:
   Windows + Linux instructions for HnH testing.txt
3) Copy the template block below and fill it out.
4) Append a new block for each test run (do not overwrite old runs).

Suggested files in this folder
- known-good-requirements-win11.txt
- known-good-requirements-linux.txt
- README.txt (this log)

-----
Run record template
-----
Date/time:
Tester:

Platform:
- OS:
- OS build/version:
- Machine/device:

Python:
- python --version:
- pip --version:

Run type:
- [ ] Source run
- [ ] Packaged run
- [ ] Both

Smoke test result:
- [ ] PASS
- [ ] FAIL

BLE / H10 notes:

Behavior notes (UI/scan/connect/save):

Artifacts:
- Requirements snapshot file:
- Packaged artifact path (if any):
- Session output path(s):

Issues observed:

Follow-up actions:

-----
