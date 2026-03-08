#!/usr/bin/env python3
"""
Create sample import files for testing the Import session feature.
Places them in ~/Hertz-and-Hearts/Import Samples/ (alongside your sessions).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def main():
    samples_dir = Path.home() / "Hertz-and-Hearts" / "Import Samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    # 1. Native CSV (Hertz & Hearts format)
    native_csv = samples_dir / "native_sample.csv"
    base_ts = "2025-03-08T14:30:00"
    rows = [
        ("event", "value", "timestamp", "elapsed_sec"),
        ("IBI", "812.0", base_ts, "0"),
        ("hrv", "42.5", base_ts, "0"),
        ("IBI", "765.0", base_ts, "812"),
        ("hrv", "45.2", base_ts, "812"),
        ("IBI", "828.0", base_ts, "1577"),
        ("hrv", "48.1", base_ts, "1577"),
        ("IBI", "791.0", base_ts, "2405"),
        ("Annotation", "Resting baseline", base_ts, "2405"),
        ("IBI", "805.0", base_ts, "3196"),
        ("hrv", "44.8", base_ts, "3196"),
    ]
    native_csv.write_text("\n".join(",".join(r) for r in rows), encoding="utf-8")
    print(f"Created: {native_csv}")

    # 2. RR-only text (Kubios / Elite HRV style)
    rr_txt = samples_dir / "rr_only_sample.txt"
    rr_intervals = [812, 765, 828, 791, 805, 798, 815, 777, 802, 809]
    rr_txt.write_text("\n".join(str(x) for x in rr_intervals), encoding="utf-8")
    print(f"Created: {rr_txt}")

    # 3. EDF+ (HR and RMSSD channels)
    try:
        import pyedflib
        import numpy as np
    except ImportError:
        print("Skipping EDF sample (pyedflib not available)")
        return

    edf_path = samples_dir / "sample.edf"
    duration_sec = 60
    fs_hr = 1
    n_hr = duration_sec * fs_hr
    hr = np.linspace(72, 78, n_hr) + np.random.RandomState(42).randn(n_hr) * 2
    rmssd = np.full(n_hr, 45.0) + np.random.RandomState(43).randn(n_hr) * 3
    rmssd = np.clip(rmssd, 20, 80)

    channel_info = [
        {"label": "HR", "dimension": "bpm", "sample_frequency": fs_hr,
         "physical_min": 30, "physical_max": 200,
         "digital_min": -32768, "digital_max": 32767,
         "transducer": "HR", "prefilter": ""},
        {"label": "RMSSD", "dimension": "ms", "sample_frequency": fs_hr,
         "physical_min": 0, "physical_max": 200,
         "digital_min": -32768, "digital_max": 32767,
         "transducer": "RMSSD", "prefilter": ""},
    ]
    samples = [hr.astype(float), rmssd.astype(float)]

    start = datetime(2025, 3, 8, 14, 30, 0)
    writer = pyedflib.EdfWriter(str(edf_path), 2, file_type=pyedflib.FILETYPE_EDFPLUS)
    try:
        writer.setSignalHeaders(channel_info)
        writer.setStartdatetime(start)
        writer.setPatientCode("Sample")
        writer.setTechnician("HertzAndHearts")
        writer.writeSamples(samples)
    finally:
        writer.close()
    print(f"Created: {edf_path}")

    # README
    readme = samples_dir / "README.txt"
    readme.write_text(
        "Hertz & Hearts — Import Samples\n"
        "================================\n\n"
        "Use More → Import session… and select one of these files to test the import feature.\n\n"
        "• native_sample.csv  — Hertz & Hearts format (event, value, timestamp, elapsed_sec)\n"
        "• rr_only_sample.txt — Line-separated RR intervals in ms (Kubios / Elite HRV style)\n"
        "• sample.edf        — EDF+ with HR and RMSSD channels\n\n"
        "Imported sessions appear in History and can be replayed, reported, and compared.",
        encoding="utf-8",
    )
    print(f"Created: {readme}")

    print(f"\nSamples are in: {samples_dir}")


if __name__ == "__main__":
    main()
