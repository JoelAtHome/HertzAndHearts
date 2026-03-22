#!/usr/bin/env python3
"""
Write session.edf into an existing session folder so Replay shows an ECG trace.

Native session.csv does not carry waveform samples; replay only plots ECG when
session.edf exists (from finalized export with EDF+ enabled, or this script).

Usage (from repo root, with venv active):
  python scripts/write_session_edf_for_replay.py "C:/path/to/Sessions/Profile/.../session_id"

Overwrites session.edf if present. Requires pyedflib.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hnh.edf_export import export_session_edf_plus  # noqa: E402
from hnh.replay_loader import _load_from_csv  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Add session.edf for replay ECG (synthetic waveform).")
    p.add_argument("session_dir", type=Path, help="Folder containing session.csv")
    p.add_argument(
        "--force",
        action="store_true",
        help="Write even if session.edf already exists (default: skip if present)",
    )
    args = p.parse_args()
    d = args.session_dir.resolve()
    csv_path = d / "session.csv"
    edf_path = d / "session.edf"
    if not d.is_dir():
        print(f"Not a directory: {d}", file=sys.stderr)
        return 1
    if not csv_path.is_file():
        print(f"Missing session.csv: {csv_path}", file=sys.stderr)
        return 1
    if edf_path.is_file() and not args.force:
        print(f"session.edf already exists (use --force to replace): {edf_path}")
        return 0

    data = _load_from_csv(csv_path)
    duration = float(data.get("duration_seconds") or 0.0)
    if duration <= 0:
        duration = 60.0
    hr_vals = data.get("hr_values") or []
    rm_vals = data.get("rmssd_values") or []
    if not hr_vals:
        hr_vals = [72.0]
    if not rm_vals:
        rm_vals = [25.0]

    end = datetime.now()
    start = end - timedelta(seconds=max(1.0, duration))
    payload = {
        "session_id": d.name,
        "profile_id": "ReplayEDF",
        "session_type": "General Monitoring",
        "session_start": start,
        "session_end": end,
        "hr_values": hr_vals,
        "rmssd_values": rm_vals,
        "annotations": [],
        "ecg_samples": [],
        "ecg_sample_rate_hz": 130,
        "ecg_is_simulated": True,
    }
    ok, msg = export_session_edf_plus(str(edf_path), payload)
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print(f"Wrote {edf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
