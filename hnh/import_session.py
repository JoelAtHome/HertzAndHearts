"""Import external CSV/EDF files as sessions. Converts to native format for replay, report, trends."""

from __future__ import annotations

import csv
import math
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from hnh.session_artifacts import SessionBundle, create_session_bundle, write_manifest
from hnh.profile_store import ProfileStore


def _compute_rmssd_from_ibis(ibis_ms: list[float]) -> list[float]:
    """Compute RMSSD from successive IBI pairs. Returns empty if < 2 IBIs."""
    if len(ibis_ms) < 2:
        return []
    diffs = []
    for i in range(1, len(ibis_ms)):
        d = ibis_ms[i] - ibis_ms[i - 1]
        diffs.append(d * d)
    return [math.sqrt(sum(diffs) / len(diffs))] if diffs else []


def parse_external_file(path: Path) -> dict[str, Any] | None:
    """
    Parse CSV or EDF file into normalized replay data.
    Returns dict with hr_times, hr_values, rmssd_times, rmssd_values, annotations,
    ecg_samples, ecg_sample_rate_hz, duration_seconds; or None if unsupported.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".edf":
        return _parse_edf(path)
    if suffix in (".csv", ".txt"):
        return _parse_csv_or_txt(path)
    return None


def _parse_edf(path: Path) -> dict[str, Any] | None:
    """Load HR, RMSSD, ECG from EDF+ file."""
    try:
        import pyedflib
    except ImportError:
        return None
    try:
        reader = pyedflib.EdfReader(str(path))
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
                hr_times, hr_values = times, vals
            elif label == "RMSSD":
                rmssd_times, rmssd_values = times, vals
            elif label in ("ECG", "ECG_SIM"):
                ecg_samples, ecg_rate = vals, int(samp_freq)

        duration = max(hr_times) if hr_times else (max(rmssd_times) if rmssd_times else 0.0)
        if ecg_samples and not duration:
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


def _parse_csv_or_txt(path: Path) -> dict[str, Any] | None:
    """Parse our native CSV or simple RR-only format."""
    with open(path, encoding="utf-8", newline="") as f:
        first_line = f.readline()
    header = first_line.strip().lower()
    if "event" in header and "value" in header:
        return _parse_native_csv(path)
    return _parse_rr_only(path)


def _parse_native_csv(path: Path) -> dict[str, Any] | None:
    """Parse our event,value,timestamp,elapsed_sec CSV."""
    from hnh.replay_loader import _load_from_csv

    return _load_from_csv(path)


def _parse_rr_only(path: Path) -> dict[str, Any] | None:
    """Parse line-separated RR intervals (ms). Kubios/Elite HRV style."""
    ibis_ms: list[float] = []
    with open(path, encoding="utf-8", newline="") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            val = parts[0] if parts else line
            try:
                v = float(val)
                if 200 < v < 3000:
                    ibis_ms.append(v)
            except ValueError:
                continue
    if not ibis_ms:
        return None

    elapsed_ms = 0.0
    hr_times: list[float] = []
    hr_values: list[float] = []
    for ibi in ibis_ms:
        hr_bpm = 60000.0 / ibi
        hr_times.append(elapsed_ms / 1000.0)
        hr_values.append(hr_bpm)
        elapsed_ms += ibi

    rmssd_val = _compute_rmssd_from_ibis(ibis_ms)
    rmssd_times = [hr_times[-1]] * len(rmssd_val) if rmssd_val else []
    rmssd_values = rmssd_val

    duration = max(hr_times) if hr_times else 0.0
    return {
        "hr_times": hr_times,
        "hr_values": hr_values,
        "rmssd_times": rmssd_times,
        "rmssd_values": rmssd_values,
        "hrv_times": [],
        "hrv_values": [],
        "annotations": [],
        "ecg_samples": [],
        "ecg_sample_rate_hz": 130,
        "duration_seconds": duration,
    }


def write_session_csv(csv_path: Path, data: dict[str, Any]) -> None:
    """Write normalized replay data to our session.csv format.
    The elapsed_sec column stores cumulative ms (same convention as logger)."""
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event", "value", "timestamp", "elapsed_sec"])
        base_ts = datetime.now().isoformat()
        hr_times = data.get("hr_times") or []
        hr_values = data.get("hr_values") or []
        rmssd_values = data.get("rmssd_values") or []
        annotations = data.get("annotations") or []

        for i, (t, hr) in enumerate(zip(hr_times, hr_values)):
            elapsed_ms = t * 1000.0
            ibi_ms = 60000.0 / hr
            w.writerow(["IBI", f"{ibi_ms:.1f}", base_ts, f"{elapsed_ms:.3f}"])
            if rmssd_values:
                if i < len(rmssd_values):
                    w.writerow(["hrv", f"{rmssd_values[i]:.2f}", base_ts, f"{elapsed_ms:.3f}"])
                elif i == len(hr_times) - 1 and len(rmssd_values) == 1:
                    w.writerow(["hrv", f"{rmssd_values[0]:.2f}", base_ts, f"{elapsed_ms:.3f}"])

        for t, text in annotations:
            elapsed_ms = t * 1000.0
            w.writerow(["Annotation", str(text), base_ts, f"{elapsed_ms:.3f}"])


def import_file_as_session(
    source_path: Path,
    session_root: Path,
    profile_id: str,
    profile_store: ProfileStore,
) -> SessionBundle | None:
    """
    Import a CSV or EDF file as a session. Creates session folder, writes CSV and manifest,
    registers in profile_store. Returns SessionBundle or None on failure.
    """
    data = parse_external_file(source_path)
    if not data or not data.get("hr_times"):
        return None

    bundle = create_session_bundle(session_root, profile_id)
    write_session_csv(bundle.csv_path, data)

    edf_ok = False
    if source_path.suffix.lower() == ".edf":
        try:
            shutil.copy2(source_path, bundle.edf_path)
            edf_ok = bundle.edf_path.is_file()
        except OSError:
            edf_ok = False

    artifacts: dict[str, Any] = {
        "csv": {"path": str(bundle.csv_path.name), "exists": True},
    }
    if edf_ok:
        artifacts["edf"] = {"path": str(bundle.edf_path.name), "exists": True}

    now = datetime.now()
    payload = {
        "schema_version": 1,
        "updated_at": now.isoformat(),
        "session_id": bundle.session_id,
        "profile_id": bundle.profile_id,
        "state": "imported",
        "report_stage": "final",
        "sensor": {"selected_device": "imported"},
        "timing": {
            "started_at": bundle.started_at.isoformat(),
            "first_data_at": None,
            "ended_at": now.isoformat(),
        },
        "metrics": {
            "baseline_hr": None,
            "baseline_rmssd": None,
            "last_hr": data.get("hr_values", [])[-1] if data.get("hr_values") else None,
            "last_rmssd": data.get("rmssd_values", [])[-1] if data.get("rmssd_values") else None,
            "qtc": {"status": "unavailable"},
            "annotation_count": len(data.get("annotations") or []),
        },
        "disconnect_intervals": [],
        "disconnect_total_seconds": 0,
        "disclaimer": {},
        "artifacts": artifacts,
    }
    write_manifest(bundle.manifest_path, payload)

    profile_store.ensure_profile(profile_id)
    with profile_store._db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO session_history (
                session_id, profile_name, started_at, ended_at, state, session_dir, csv_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bundle.session_id,
                profile_id,
                bundle.started_at.isoformat(),
                now.isoformat(),
                "imported",
                str(bundle.session_dir),
                str(bundle.csv_path),
            ),
        )

    last_hr = data.get("hr_values", [])[-1] if data.get("hr_values") else None
    last_rmssd = data.get("rmssd_values", [])[-1] if data.get("rmssd_values") else None
    profile_store.record_session_trend(
        profile_name=profile_id,
        session_id=bundle.session_id,
        ended_at=now,
        avg_hr=last_hr,
        avg_rmssd=last_rmssd,
    )

    return bundle
