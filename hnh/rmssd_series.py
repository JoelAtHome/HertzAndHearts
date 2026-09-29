"""Rolling RMSSD from beat intervals, matching the live monitor window."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from hnh.config import RMSSD_WINDOW

_MIN_BEATS = 3
_FLAT_TOLERANCE_MS = 0.05


def series_is_flat(values: list[float], *, tolerance_ms: float = _FLAT_TOLERANCE_MS) -> bool:
    """True when every sample is the same number, including an empty series."""
    cleaned: list[float] = []
    for value in values:
        try:
            sample = float(value)
        except (TypeError, ValueError):
            continue
        if sample == sample:
            cleaned.append(sample)
    if not cleaned:
        return True
    return (max(cleaned) - min(cleaned)) <= tolerance_ms


def rolling_rmssd_series(
    ibis_ms: list[float],
    times_sec: list[float] | None = None,
    *,
    window: int = RMSSD_WINDOW,
    min_beats: int = _MIN_BEATS,
) -> tuple[list[float], list[float]]:
    """RMSSD over the last `window` beats, one sample per beat from beat `min_beats`.

    This is the live monitor formula: sqrt(mean(successive IBI differences squared)).
    The window grows until it reaches `window` beats, then slides.
    Returns (times_sec, rmssd_ms). Both lists are empty when there are fewer
    than `min_beats` intervals.
    """
    ibis = [float(v) for v in ibis_ms]
    n = len(ibis)
    if n < min_beats or window < 2:
        return [], []

    if times_sec is None or len(times_sec) != n:
        elapsed = 0.0
        times: list[float] = []
        for ibi in ibis:
            times.append(elapsed)
            elapsed += ibi / 1000.0
    else:
        times = [float(t) for t in times_sec]

    out_times: list[float] = []
    out_values: list[float] = []
    for end in range(min_beats - 1, n):
        start = max(0, end + 1 - window)
        segment = ibis[start : end + 1]
        diffs = [segment[i] - segment[i - 1] for i in range(1, len(segment))]
        if not diffs:
            continue
        out_values.append(math.sqrt(sum(d * d for d in diffs) / len(diffs)))
        out_times.append(times[end])
    return out_times, out_values


def read_ibi_series(csv_path: Path) -> tuple[list[float], list[float], list[float]]:
    """Read beat intervals from a session CSV.

    Returns (times_sec, ibi_ms, stored_rmssd_ms). `stored_rmssd_ms` is the
    `hrv` column as written, which may be a single summary repeated twice.
    """
    times: list[float] = []
    ibis: list[float] = []
    stored: list[float] = []
    if not csv_path.is_file():
        return times, ibis, stored

    current_elapsed_ms = 0.0
    with open(csv_path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "event" not in fields or "value" not in fields:
            return times, ibis, stored
        for row in reader:
            event = str(row.get("event") or "").strip()
            try:
                value = float(str(row.get("value") or "").strip())
            except (TypeError, ValueError):
                value = None
            elapsed_raw = str(row.get("elapsed_sec") or "").strip()
            parsed_elapsed = None
            if elapsed_raw:
                try:
                    parsed_elapsed = float(elapsed_raw)
                except ValueError:
                    parsed_elapsed = None
            if parsed_elapsed is not None:
                current_elapsed_ms = max(current_elapsed_ms, parsed_elapsed)
            if event == "IBI" and value is not None and value > 0:
                if parsed_elapsed is None:
                    current_elapsed_ms += value
                times.append(current_elapsed_ms / 1000.0)
                ibis.append(value)
            elif event == "hrv" and value is not None:
                stored.append(value)
    return times, ibis, stored


def summary_rmssd_average_from_csv(csv_path: Path) -> float | None:
    """Mean of a rolling RMSSD series when the CSV only stored a flat summary.

    Returns None when the file already has a varying RMSSD series, or when
    there are not enough beats to compute one. Callers should leave the
    stored trend alone in that case.
    """
    times, ibis, stored = read_ibi_series(csv_path)
    if not stored or not series_is_flat(stored):
        return None
    _times, values = rolling_rmssd_series(ibis, times)
    if not values:
        return None
    return sum(values) / len(values)


def bridge_rmssd_from_manifest(session_dir: Path) -> float | None:
    manifest_path = session_dir / "session_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    if not isinstance(metrics, dict):
        return None
    try:
        value = float(metrics.get("bridge_rmssd_ms"))
    except (TypeError, ValueError):
        return None
    if value != value or value < 0:
        return None
    return value
