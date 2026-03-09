"""Load session data for replay from EDF or CSV."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def load_session_replay_data(session_dir: Path) -> dict[str, Any]:
    """
    Load session time-series data for replay.

    Tries EDF first if session.edf exists; otherwise parses CSV.
    Returns dict with: hr_times, hr_values, rmssd_times, rmssd_values,
    hrv_times, hrv_values (SDNN if available), annotations, ecg_samples,
    ecg_sample_rate_hz, duration_seconds.
    """
    session_dir = Path(session_dir)
    edf_path = session_dir / "session.edf"
    csv_path = session_dir / "session.csv"

    if edf_path.exists():
        data = _load_from_edf(edf_path)
        if data:
            return data

    if csv_path.exists():
        return _load_from_csv(csv_path)

    return _empty_replay_data()


def _empty_replay_data() -> dict[str, Any]:
    return {
        "hr_times": [],
        "hr_values": [],
        "rmssd_times": [],
        "rmssd_values": [],
        "hrv_times": [],
        "hrv_values": [],
        "annotations": [],
        "ecg_samples": [],
        "ecg_sample_rate_hz": 130,
        "duration_seconds": 0.0,
    }


def _load_from_edf(edf_path: Path) -> dict[str, Any] | None:
    """Load HR, RMSSD, ECG from EDF+ file."""
    try:
        import pyedflib
    except ImportError:
        return None

    try:
        reader = pyedflib.EdfReader(str(edf_path))
    except Exception:
        return None

    try:
        n_channels = reader.signals_in_file
        labels = [reader.getSignalLabels()[i] for i in range(n_channels)]

        hr_times: list[float] = []
        hr_values: list[float] = []
        rmssd_times: list[float] = []
        rmssd_values: list[float] = []
        ecg_samples: list[float] = []
        ecg_rate = 130

        for i, label in enumerate(labels):
            sig = reader.readSignal(i)
            n = len(sig)
            if n == 0:
                continue
            samp_freq = reader.getSampleFrequency(i)
            times = [j / samp_freq for j in range(n)]
            vals = [float(x) for x in sig]

            if label == "HR":
                hr_times = times
                hr_values = vals
            elif label == "RMSSD":
                rmssd_times = times
                rmssd_values = vals
            elif label in ("ECG", "ECG_SIM"):
                ecg_samples = vals
                ecg_rate = int(samp_freq)

        duration = 0.0
        if hr_times:
            duration = max(hr_times)
        elif rmssd_times:
            duration = max(rmssd_times)
        elif ecg_samples:
            duration = len(ecg_samples) / ecg_rate

        return {
            "hr_times": hr_times,
            "hr_values": hr_values,
            "rmssd_times": rmssd_times,
            "rmssd_values": rmssd_values,
            "hrv_times": [],
            "hrv_values": [],
            "annotations": [],
            "ecg_samples": ecg_samples,
            "ecg_sample_rate_hz": ecg_rate,
            "duration_seconds": duration,
        }
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _load_from_csv(csv_path: Path) -> dict[str, Any]:
    """Parse CSV to build HR and RMSSD time series from IBI and hrv events."""
    hr_times: list[float] = []
    hr_values: list[float] = []
    rmssd_times: list[float] = []
    rmssd_values: list[float] = []
    annotations: list[tuple[float, str]] = []

    current_elapsed = 0.0

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if "event" not in fields or "value" not in fields:
            return _empty_replay_data()

        for row in reader:
            event = (row.get("event") or "").strip()
            value_str = (row.get("value") or "").strip()
            elapsed_str = (row.get("elapsed_sec") or "").strip()
            parsed_elapsed = None
            if elapsed_str:
                try:
                    parsed_elapsed = float(elapsed_str)
                except ValueError:
                    parsed_elapsed = None
            if parsed_elapsed is not None:
                # Old files can have backwards elapsed values; clamp monotonic
                # to avoid replay zig-zag artifacts.
                current_elapsed = max(current_elapsed, parsed_elapsed)

            try:
                value = float(value_str) if value_str else None
            except ValueError:
                value = None

            if event == "IBI" and value is not None and value > 0:
                if parsed_elapsed is None:
                    current_elapsed += value
                hr_bpm = 60000.0 / value
                hr_times.append(current_elapsed / 1000.0)
                hr_values.append(hr_bpm)
            elif event == "hrv" and value is not None:
                rmssd_times.append(current_elapsed / 1000.0)
                rmssd_values.append(value)
            elif event == "Annotation":
                t = current_elapsed / 1000.0 if current_elapsed else 0.0
                annotations.append((t, value_str or "(annotation)"))

    duration = 0.0
    if hr_times:
        duration = max(hr_times)
    elif rmssd_times:
        duration = max(rmssd_times)

    return {
        "hr_times": hr_times,
        "hr_values": hr_values,
        "rmssd_times": rmssd_times,
        "rmssd_values": rmssd_values,
        "hrv_times": [],
        "hrv_values": [],
        "annotations": annotations,
        "ecg_samples": [],
        "ecg_sample_rate_hz": 130,
        "duration_seconds": duration,
    }
