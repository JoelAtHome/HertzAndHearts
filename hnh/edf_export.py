from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
from typing import Iterable

import numpy as np


def _resample_series(values: list[float], sample_count: int) -> np.ndarray:
    if sample_count <= 0:
        return np.array([], dtype=float)
    if not values:
        return np.zeros(sample_count, dtype=float)
    if len(values) == 1:
        return np.full(sample_count, float(values[0]), dtype=float)
    src_x = np.linspace(0.0, 1.0, num=len(values), endpoint=True)
    dst_x = np.linspace(0.0, 1.0, num=sample_count, endpoint=True)
    return np.interp(dst_x, src_x, np.asarray(values, dtype=float))


def _safe_float_iter(values: Iterable[object]) -> list[float]:
    out: list[float] = []
    for v in values:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _sanitize_edf_header_text(value: object, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = fallback
    ascii_only = raw.encode("ascii", errors="ignore").decode("ascii")
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in ascii_only)
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _zscore(samples: np.ndarray) -> np.ndarray:
    if samples.size == 0:
        return samples
    mean = float(np.mean(samples))
    std = float(np.std(samples))
    if std < 1e-9:
        return np.zeros_like(samples, dtype=float)
    return (samples - mean) / std


def _simulate_ecg(sample_rate_hz: int, sample_count: int) -> np.ndarray:
    if sample_count <= 0:
        return np.array([], dtype=float)
    out = np.zeros(sample_count, dtype=float)
    for i in range(sample_count):
        t = i / float(sample_rate_hz)
        # Lightweight synthetic ECG-like shape for visualization/testing only.
        base = 0.08 * math.sin(2 * math.pi * 1.05 * t) + 0.01 * math.sin(2 * math.pi * 30.0 * t)
        phase = (t * 1.0) % 1.0
        q = -0.12 * math.exp(-((phase - 0.040) / 0.010) ** 2)
        r = 0.95 * math.exp(-((phase - 0.060) / 0.009) ** 2)
        s = -0.20 * math.exp(-((phase - 0.090) / 0.014) ** 2)
        out[i] = base + q + r + s
    return out


def export_session_edf_plus(
    path: str,
    data: dict,
    *,
    sample_rate_hz: int = 1,
    include_normalized_channels: bool = True,
) -> tuple[bool, str]:
    """
    Export a compact EDF+ session file with derived trend channels.

    Returns:
      (True, output_path) on success
      (False, reason) on skip/failure
    """
    try:
        import pyedflib
    except Exception:
        return False, "pyedflib is not installed"

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    session_start = data.get("session_start")
    session_end = data.get("session_end")
    if not isinstance(session_start, datetime):
        session_start = datetime.now()
    if not isinstance(session_end, datetime):
        session_end = datetime.now()

    duration_seconds = max(1, int((session_end - session_start).total_seconds()))
    sample_count = max(sample_rate_hz, duration_seconds * sample_rate_hz)

    hr_values = _safe_float_iter(data.get("hr_values") or [])
    rmssd_values = _safe_float_iter(data.get("rmssd_values") or [])
    ecg_values = _safe_float_iter(data.get("ecg_samples") or [])
    ecg_rate_hz = int(data.get("ecg_sample_rate_hz") or 130)
    ecg_rate_hz = max(25, min(1000, ecg_rate_hz))
    ecg_is_simulated = bool(data.get("ecg_is_simulated", False))

    hr_samples = _resample_series(hr_values, sample_count)
    rmssd_samples = _resample_series(rmssd_values, sample_count)
    ecg_sample_count = max(ecg_rate_hz, duration_seconds * ecg_rate_hz)
    if ecg_values:
        ecg_samples = _resample_series(ecg_values, ecg_sample_count)
    else:
        ecg_samples = _simulate_ecg(ecg_rate_hz, ecg_sample_count)
        ecg_is_simulated = True

    channel_info = [
        {
            "label": "HR",
            "dimension": "bpm",
            "sample_frequency": sample_rate_hz,
            "physical_min": 20.0,
            "physical_max": 240.0,
            "digital_min": -32768,
            "digital_max": 32767,
            "transducer": "Derived trend",
            "prefilter": "",
        },
        {
            "label": "RMSSD",
            "dimension": "ms",
            "sample_frequency": sample_rate_hz,
            "physical_min": 0.0,
            "physical_max": 1000.0,
            "digital_min": -32768,
            "digital_max": 32767,
            "transducer": "Derived trend",
            "prefilter": "",
        },
    ]
    samples = [hr_samples, rmssd_samples]

    if include_normalized_channels:
        hr_z = np.clip(_zscore(hr_samples), -5.0, 5.0)
        rmssd_z = np.clip(_zscore(rmssd_samples), -5.0, 5.0)
        channel_info.extend(
            [
                {
                    "label": "HR_Z",
                    "dimension": "z",
                    "sample_frequency": sample_rate_hz,
                    "physical_min": -5.0,
                    "physical_max": 5.0,
                    "digital_min": -32768,
                    "digital_max": 32767,
                    "transducer": "Derived zscore",
                    "prefilter": "",
                },
                {
                    "label": "RMSSD_Z",
                    "dimension": "z",
                    "sample_frequency": sample_rate_hz,
                    "physical_min": -5.0,
                    "physical_max": 5.0,
                    "digital_min": -32768,
                    "digital_max": 32767,
                    "transducer": "Derived zscore",
                    "prefilter": "",
                },
            ]
        )
        samples.extend([hr_z, rmssd_z])

    ecg_label = "ECG_SIM" if ecg_is_simulated else "ECG"
    ecg_transducer = "Simulated ECG" if ecg_is_simulated else "ECG stream"
    channel_info.append(
        {
            "label": ecg_label,
            "dimension": "mV",
            "sample_frequency": ecg_rate_hz,
            "physical_min": -2.5,
            "physical_max": 2.5,
            "digital_min": -32768,
            "digital_max": 32767,
            "transducer": ecg_transducer,
            "prefilter": "",
        }
    )
    samples.append(ecg_samples)

    writer = pyedflib.EdfWriter(str(output), len(channel_info), file_type=pyedflib.FILETYPE_EDFPLUS)
    try:
        writer.setSignalHeaders(channel_info)
        writer.setStartdatetime(session_start)
        writer.setPatientCode(_sanitize_edf_header_text(data.get("profile_id"), "Admin"))
        writer.setTechnician("HertzAndHearts")
        writer.setRecordingAdditional(
            _sanitize_edf_header_text(
                f"Session_{data.get('session_id', '--')}_{data.get('session_type', 'GeneralMonitoring')}",
                "Session",
            )
        )
        writer.writeSamples(samples)

        for ann in data.get("annotations", []) or []:
            if not isinstance(ann, (tuple, list)) or len(ann) < 2:
                continue
            ann_text = str(ann[1]).strip()
            if not ann_text:
                continue
            writer.writeAnnotation(0.0, 0.0, ann_text)
    finally:
        writer.close()

    return True, str(output)
