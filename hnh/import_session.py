"""Import external CSV/EDF files as sessions. Converts to native format for replay, report, trends."""

from __future__ import annotations

import base64
import csv
import math
import shutil
import struct
from datetime import datetime, timedelta
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


def replay_data_from_ibi_ms(
    ibi_ms: list[int] | list[float],
    *,
    bridge_rmssd_ms: float | None = None,
    annotation: str | None = None,
) -> dict[str, Any] | None:
    """Build normalized replay data from phone-bridge IBI list (ms)."""
    cleaned: list[float] = []
    for raw in ibi_ms:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if 200 < value < 3000:
            cleaned.append(value)
    if not cleaned:
        return None

    elapsed_ms = 0.0
    hr_times: list[float] = []
    hr_values: list[float] = []
    for ibi in cleaned:
        hr_times.append(elapsed_ms / 1000.0)
        hr_values.append(60000.0 / ibi)
        elapsed_ms += ibi

    if bridge_rmssd_ms is not None and bridge_rmssd_ms == bridge_rmssd_ms and bridge_rmssd_ms >= 0:
        rmssd_values = [float(bridge_rmssd_ms)]
    else:
        rmssd_values = _compute_rmssd_from_ibis(cleaned)
    rmssd_times = [hr_times[-1]] * len(rmssd_values) if rmssd_values else []

    annotations: list[tuple[float, str]] = []
    if annotation:
        annotations.append((0.0, str(annotation)))

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
        "duration_seconds": max(hr_times) if hr_times else 0.0,
    }


def decode_ritual_ecg_chunks(
    chunks: list[dict[str, Any]] | list[Any],
) -> tuple[list[float], int]:
    """
    Decode PROTOCOL §7 `ritual_chunk` ECG payloads to mV samples.

    Wire encoding: little-endian int16 microvolts (+ optional scale_uv_per_lsb),
    base64 in `data`. Returns (samples_mv, sample_rate_hz).
    """
    samples_uv: list[float] = []
    rate_hz = 130
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        encoding = str(chunk.get("encoding") or "").strip().lower()
        if encoding and encoding not in {"int16_uv_b64", "int16_uv"}:
            continue
        raw_b64 = str(chunk.get("data") or "").strip()
        if not raw_b64:
            continue
        try:
            raw = base64.b64decode(raw_b64, validate=False)
        except Exception:
            continue
        try:
            scale = float(chunk.get("scale_uv_per_lsb", 1.0))
        except (TypeError, ValueError):
            scale = 1.0
        if scale != scale or scale == 0:
            scale = 1.0
        try:
            rate_hz = int(round(float(chunk.get("sample_rate_hz") or rate_hz)))
        except (TypeError, ValueError):
            pass
        n = len(raw) // 2
        for i in range(n):
            (val,) = struct.unpack_from("<h", raw, i * 2)
            samples_uv.append(float(val) * scale)
    rate_hz = max(25, min(1000, int(rate_hz or 130)))
    samples_mv = [v / 1000.0 for v in samples_uv]
    return samples_mv, rate_hz


def import_saved_hrv_package(
    package: dict[str, Any],
    session_root: Path,
    profile_id: str,
    profile_store: ProfileStore,
) -> SessionBundle | None:
    """
    Persist a PROTOCOL §7 saved-HRV package into Session History.

    Prefer IBI series; use official bridge `rmssd_ms` when present. Returns None
    when IBIs are missing/unusable, or the existing bundle is already imported
    (caller should treat that as a quiet no-op success via return of None and
    check profile_store mapping — actually return a sentinel).

    Returns the new SessionBundle, or None if skipped/failed.
    On durable dedupe hit, returns None and leaves mapping unchanged.
    """
    if not isinstance(package, dict):
        return None
    phone_sid = str(package.get("session_id") or "").strip()
    if not phone_sid:
        return None
    if profile_store.get_phone_bridge_imported_session_id(profile_id, phone_sid):
        return None

    ibi_raw = package.get("ibi_ms")
    if not isinstance(ibi_raw, list):
        return None
    bridge_rmssd = package.get("rmssd_ms")
    try:
        bridge_rmssd_f = float(bridge_rmssd) if bridge_rmssd is not None else None
    except (TypeError, ValueError):
        bridge_rmssd_f = None

    reason = str(package.get("transfer_reason") or "").strip() or "saved"
    source = str(package.get("source_device") or "").strip() or "phone_bridge"
    note = f"[Phone Bridge] Saved HRV ({reason})"
    data = replay_data_from_ibi_ms(
        ibi_raw,
        bridge_rmssd_ms=bridge_rmssd_f,
        annotation=note,
    )
    if not data or not data.get("hr_times"):
        return None

    ecg_chunks = package.get("ecg_chunks")
    ecg_samples: list[float] = []
    ecg_rate = 130
    if isinstance(ecg_chunks, list) and ecg_chunks:
        ecg_samples, ecg_rate = decode_ritual_ecg_chunks(ecg_chunks)
        if ecg_samples:
            data["ecg_samples"] = ecg_samples
            data["ecg_sample_rate_hz"] = ecg_rate
            # Prefer ECG length when it extends past IBI-derived duration.
            ecg_dur = len(ecg_samples) / float(ecg_rate)
            if ecg_dur > float(data.get("duration_seconds") or 0):
                data["duration_seconds"] = ecg_dur

    bundle = create_session_bundle(session_root, profile_id)
    write_session_csv(bundle.csv_path, data)

    emitted_at = str(package.get("emitted_at") or "").strip() or None
    duration_s = package.get("duration_s")
    try:
        duration_f = float(duration_s) if duration_s is not None else float(
            data.get("duration_seconds") or 0
        )
    except (TypeError, ValueError):
        duration_f = float(data.get("duration_seconds") or 0)
    if duration_f != duration_f or duration_f < 0:
        duration_f = 0.0

    ended_at = emitted_at or datetime.now().isoformat()
    started_at = bundle.started_at.isoformat()
    start_dt = bundle.started_at
    # Prefer phone emit time for history when parseable.
    if emitted_at:
        try:
            start_dt = datetime.fromisoformat(emitted_at.replace("Z", "+00:00"))
            if start_dt.tzinfo is not None:
                start_dt = start_dt.replace(tzinfo=None)
            started_at = start_dt.isoformat()
            end_dt = start_dt + timedelta(seconds=max(1.0, duration_f or 1.0))
            ended_at = end_dt.isoformat()
        except Exception:
            end_dt = start_dt + timedelta(seconds=max(1.0, duration_f or 1.0))
            ended_at = end_dt.isoformat()
    else:
        end_dt = start_dt + timedelta(seconds=max(1.0, duration_f or 1.0))
        ended_at = end_dt.isoformat()

    edf_ok = False
    if ecg_samples:
        try:
            from hnh.edf_export import export_session_edf_plus

            edf_ok, _reason = export_session_edf_plus(
                str(bundle.edf_path),
                {
                    "session_id": bundle.session_id,
                    "profile_id": profile_id,
                    "session_start": start_dt,
                    "session_end": end_dt,
                    "hr_values": data.get("hr_values") or [],
                    "rmssd_values": data.get("rmssd_values") or [],
                    "ecg_samples": ecg_samples,
                    "ecg_sample_rate_hz": ecg_rate,
                    "ecg_is_simulated": False,
                    "annotations": data.get("annotations") or [],
                },
                sample_rate_hz=1,
            )
            edf_ok = bool(edf_ok and bundle.edf_path.is_file())
        except Exception:
            edf_ok = False

    last_hr = data.get("hr_values", [])[-1] if data.get("hr_values") else None
    last_rmssd = data.get("rmssd_values", [])[-1] if data.get("rmssd_values") else None

    artifacts: dict[str, Any] = {
        "csv": {"path": str(bundle.csv_path.name), "exists": True},
        "phone_bridge_package": {
            "session_id": phone_sid,
            "kind": package.get("kind"),
            "mode": package.get("mode"),
            "ibi_count": len(ibi_raw),
            "has_ecg_chunks": bool(ecg_chunks),
            "ecg_sample_count": len(ecg_samples),
            "ecg_sample_rate_hz": ecg_rate if ecg_samples else None,
        },
    }
    if edf_ok:
        artifacts["edf"] = {"path": str(bundle.edf_path.name), "exists": True}

    payload = {
        "schema_version": 1,
        "updated_at": datetime.now().isoformat(),
        "session_id": bundle.session_id,
        "profile_id": bundle.profile_id,
        "state": "imported",
        "report_stage": "final",
        "sensor": {
            "selected_device": "phone_bridge",
            "source_device": source,
            "phone_bridge_session_id": phone_sid,
            "transfer_reason": reason,
        },
        "timing": {
            "started_at": started_at,
            "first_data_at": started_at,
            "ended_at": ended_at,
            "emitted_at": emitted_at,
            "duration_s": duration_f or package.get("duration_s"),
        },
        "metrics": {
            "baseline_hr": None,
            "baseline_rmssd": None,
            "last_hr": last_hr,
            "last_rmssd": last_rmssd,
            "bridge_rmssd_ms": bridge_rmssd_f,
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
                started_at,
                ended_at,
                "imported",
                str(bundle.session_dir),
                str(bundle.csv_path),
            ),
        )

    try:
        ended_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        if ended_dt.tzinfo is not None:
            ended_dt = ended_dt.replace(tzinfo=None)
    except Exception:
        ended_dt = datetime.now()

    profile_store.record_session_trend(
        profile_name=profile_id,
        session_id=bundle.session_id,
        ended_at=ended_dt,
        avg_hr=last_hr,
        avg_rmssd=last_rmssd,
    )
    profile_store.remember_phone_bridge_import(
        profile_id, phone_sid, bundle.session_id
    )
    return bundle
