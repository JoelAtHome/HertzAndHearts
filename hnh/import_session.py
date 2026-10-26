"""Import external CSV/EDF files as sessions. Converts to native format for replay, report, trends."""

from __future__ import annotations

import base64
import csv
import re
import shutil
import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from hnh.session_artifacts import (
    SessionBundle,
    create_session_bundle,
    session_id_clock,
    write_manifest,
)
from hnh.profile_store import ProfileStore
from hnh.report import format_ecg_sensor_display_name, naive_local_from_iso
from hnh.rmssd_series import rolling_rmssd_series, rolling_sdnn_series


def _rmssd_trend_average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def phone_bridge_import_annotation(
    *,
    transfer_reason: str,
    source_device: str | None,
    profile_display_name: str | None,
) -> str:
    """Build the CSV/report annotation for a saved-HRV phone import.

    Feather torso profile display names are useful context. Polar H10 (and other
    non-Feather) packages may still carry a leftover phone demo name such as
    "Typical patch torso" — omit that suffix so the annotation stays meaningful.
    """
    reason = str(transfer_reason or "").strip() or "saved"
    note = f"[Phone Bridge] Saved HRV ({reason})"
    patient = str(profile_display_name or "").strip()
    source = str(source_device or "").strip().upper()
    if patient and source == "FEATHER":
        note = f"{note} · {patient}"
    return note


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

        started_at: datetime | None = None
        try:
            started_at = reader.getStartdatetime()
        except Exception:
            started_at = None

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
            "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
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

    from hnh.hr_series import clean_ibi_series

    elapsed_ms = 0.0
    raw_times: list[float] = []
    for ibi in ibis_ms:
        raw_times.append(elapsed_ms / 1000.0)
        elapsed_ms += ibi

    hr_times, cleaned_ibis, _corrections = clean_ibi_series(ibis_ms, raw_times)
    if not cleaned_ibis:
        return None
    hr_values = [60000.0 / ibi for ibi in cleaned_ibis]

    rmssd_times, rmssd_values = rolling_rmssd_series(cleaned_ibis, hr_times)
    hrv_times, hrv_values = rolling_sdnn_series(cleaned_ibis, hr_times)

    duration = max(hr_times) if hr_times else 0.0
    return {
        "hr_times": hr_times,
        "hr_values": hr_values,
        "rmssd_times": rmssd_times,
        "rmssd_values": rmssd_values,
        "hrv_times": hrv_times,
        "hrv_values": hrv_values,
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
        base_raw = str(data.get("started_at") or "").strip()
        base_ts = base_raw if base_raw else datetime.now().isoformat()
        hr_times = data.get("hr_times") or []
        hr_values = data.get("hr_values") or []
        rmssd_times = list(data.get("rmssd_times") or [])
        rmssd_values = list(data.get("rmssd_values") or [])
        hrv_times = list(data.get("hrv_times") or [])
        hrv_values = list(data.get("hrv_values") or [])
        annotations = data.get("annotations") or []
        if rmssd_values and not rmssd_times:
            rmssd_times = list(hr_times[: len(rmssd_values)])
        if hrv_values and not hrv_times:
            hrv_times = list(hr_times[: len(hrv_values)])

        for t, hr in zip(hr_times, hr_values):
            elapsed_ms = t * 1000.0
            ibi_ms = 60000.0 / hr
            w.writerow(["IBI", f"{ibi_ms:.1f}", base_ts, f"{elapsed_ms:.3f}"])

        for t, rmssd in zip(rmssd_times, rmssd_values):
            w.writerow(["hrv", f"{float(rmssd):.2f}", base_ts, f"{float(t) * 1000.0:.3f}"])

        for t, sdnn in zip(hrv_times, hrv_values):
            w.writerow(["SDNN", f"{float(sdnn):.2f}", base_ts, f"{float(t) * 1000.0:.3f}"])

        for t, text in annotations:
            elapsed_ms = t * 1000.0
            w.writerow(["Annotation", str(text), base_ts, f"{elapsed_ms:.3f}"])


def _write_ecg_stream(path: Path, samples: list[float], sample_rate_hz: int) -> bool:
    """Persist float32 LE ECG samples for report rebuild (same as live sessions)."""
    if not samples:
        return False
    try:
        from hnh.ecg_stream import EcgSampleStream

        stream = EcgSampleStream.open_write(path, sample_rate_hz=sample_rate_hz)
        try:
            stream.append(samples)
        finally:
            stream.close()
        return path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def _recording_window(data: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Wall-clock start and end from a parsed file, or None when it has no clock."""
    started = naive_local_from_iso(str(data.get("started_at") or ""))
    if started is None:
        return None
    try:
        duration = float(data.get("duration_seconds") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration != duration or duration < 0:
        duration = 0.0
    if duration <= 0 and data.get("hr_times"):
        try:
            duration = float(max(data["hr_times"]))
        except (TypeError, ValueError):
            duration = 0.0
    return started, started + timedelta(seconds=max(0.0, duration))


def import_file_as_session(
    source_path: Path,
    session_root: Path,
    profile_id: str,
    profile_store: ProfileStore,
    *,
    include_profile_subpath: bool = False,
) -> SessionBundle | None:
    """
    Import a CSV or EDF file as a session. Creates session folder, writes CSV and manifest,
    registers in profile_store. Returns SessionBundle or None on failure.

    `session_root` should be the profile Session Save Path (same root live Stop & Save uses).
    """
    data = parse_external_file(source_path)
    if not data or not data.get("hr_times"):
        return None

    window = _recording_window(data)
    if window is not None:
        started, ended = window
        data["started_at"] = started.isoformat()
        named_at = ended
    else:
        started = None
        ended = None
        named_at = None

    bundle = create_session_bundle(
        session_root,
        profile_id,
        include_profile_subpath=include_profile_subpath,
        named_at=named_at,
    )
    write_session_csv(bundle.csv_path, data)

    edf_ok = False
    if source_path.suffix.lower() == ".edf":
        try:
            shutil.copy2(source_path, bundle.edf_path)
            edf_ok = bundle.edf_path.is_file()
        except OSError:
            edf_ok = False

    ecg_samples = list(data.get("ecg_samples") or [])
    ecg_rate = int(data.get("ecg_sample_rate_hz") or 130)
    ecg_stream_ok = False
    if ecg_samples:
        ecg_stream_ok = _write_ecg_stream(bundle.ecg_stream_path, ecg_samples, ecg_rate)

    artifacts: dict[str, Any] = {
        "csv": {"path": str(bundle.csv_path.name), "exists": True},
    }
    if edf_ok:
        artifacts["edf"] = {"path": str(bundle.edf_path.name), "exists": True}
    if ecg_stream_ok:
        artifacts["ecg_stream"] = {"path": str(bundle.ecg_stream_path.name), "exists": True}

    now = datetime.now()
    if started is None or ended is None:
        started = bundle.started_at
        ended = started
    payload = {
        "schema_version": 1,
        "updated_at": now.isoformat(),
        "session_id": bundle.session_id,
        "profile_id": bundle.profile_id,
        "state": "imported",
        "report_stage": "final",
        "sensor": {
            "selected_device": "imported",
            "ecg_sample_rate_hz": ecg_rate if ecg_samples else None,
        },
        "timing": {
            "started_at": started.isoformat(),
            "first_data_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "duration_s": max(0.0, (ended - started).total_seconds()),
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
                started.isoformat(),
                ended.isoformat(),
                "imported",
                str(bundle.session_dir),
                str(bundle.csv_path),
            ),
        )

    last_hr = data.get("hr_values", [])[-1] if data.get("hr_values") else None
    rmssd_values = data.get("rmssd_values") or []
    last_rmssd = rmssd_values[-1] if rmssd_values else None
    profile_store.record_session_trend(
        profile_name=profile_id,
        session_id=bundle.session_id,
        ended_at=ended,
        avg_hr=last_hr,
        avg_rmssd=_rmssd_trend_average(rmssd_values),
    )

    return bundle


_SESSION_DIR_NAME_RE = re.compile(r"^(\d{8}-\d{6})(?:_\d{2})?$")


def discover_orphan_session_dirs(root: Path) -> list[Path]:
    """
    Session folders under root that have session.edf and/or session.csv but no manifest.

    These are invisible to the normal integrity scan, which only walks manifests.
    """
    root = Path(root)
    found: list[Path] = []
    seen: set[str] = set()
    try:
        if not root.exists():
            return found
    except OSError:
        return found

    def _add(session_dir: Path) -> None:
        try:
            key = str(session_dir.resolve()).casefold()
        except OSError:
            key = str(session_dir).casefold()
        if key in seen:
            return
        if (session_dir / "session_manifest.json").is_file():
            return
        has_edf = (session_dir / "session.edf").is_file()
        has_csv = (session_dir / "session.csv").is_file()
        if not has_edf and not has_csv:
            return
        seen.add(key)
        found.append(session_dir)

    try:
        for edf_path in root.rglob("session.edf"):
            _add(edf_path.parent)
        for csv_path in root.rglob("session.csv"):
            _add(csv_path.parent)
    except OSError:
        pass
    return found


def _started_at_from_session_id(session_id: str) -> datetime | None:
    return session_id_clock(session_id)


def adopt_existing_session_folder(
    session_dir: Path,
    profile_id: str,
    profile_store: ProfileStore,
) -> dict[str, str | None] | None:
    """
    Rebuild missing session.csv / session_manifest.json in place and index the folder.

    Used when a session folder was copied under a profile's Session Save Path without
    a manifest (EDF/report only). The folder stays where it is; profile_id becomes the
    history owner regardless of any old name embedded in the EDF patient field.
    """
    session_dir = Path(session_dir)
    try:
        if not session_dir.is_dir():
            return None
    except OSError:
        return None

    profile = str(profile_id or "").strip() or "Admin"
    edf_path = session_dir / "session.edf"
    csv_path = session_dir / "session.csv"
    manifest_path = session_dir / "session_manifest.json"
    has_edf = edf_path.is_file()
    has_csv = csv_path.is_file()
    if not has_edf and not has_csv:
        return None

    data: dict[str, Any] | None = None
    if has_edf:
        data = parse_external_file(edf_path)
    if data is None and has_csv:
        data = parse_external_file(csv_path)
    if data is None or not data.get("hr_times"):
        return None

    session_id = session_dir.name.strip() or "imported"
    sid_match = _SESSION_DIR_NAME_RE.match(session_id)
    if sid_match:
        session_id = sid_match.group(1)

    file_started = naive_local_from_iso(str(data.get("started_at") or ""))
    folder_clock = _started_at_from_session_id(session_id)
    duration = float(data.get("duration_seconds") or 0.0)
    if duration <= 0 and data.get("hr_times"):
        try:
            duration = float(max(data["hr_times"]))
        except (TypeError, ValueError):
            duration = 0.0
    duration = max(0.0, duration)
    if file_started is not None:
        # CSV timestamp or EDF header. End-named imports keep the recording
        # start here, so the folder stamp (the end) is not added on again.
        started = file_started
        ended = started + timedelta(seconds=duration)
    elif folder_clock is not None:
        # No clock in the file. Live folders and clockless imports are stamped
        # at creation. Use that instant as the end of the span we can see so a
        # folder named for the recording end cannot be pushed forward by its
        # duration. Clockless imports have no true end, and this keeps the
        # stamp as the later bound.
        ended = folder_clock
        started = folder_clock - timedelta(seconds=duration)
    else:
        started = datetime.now()
        ended = started
    data["started_at"] = started.isoformat()

    if not has_csv:
        write_session_csv(csv_path, data)
        has_csv = csv_path.is_file()
    if not has_csv:
        return None

    ecg_samples = list(data.get("ecg_samples") or [])
    ecg_rate = int(data.get("ecg_sample_rate_hz") or 130)
    ecg_stream_path = session_dir / "session_ecg.f32"
    ecg_stream_ok = False
    if ecg_samples and not ecg_stream_path.is_file():
        ecg_stream_ok = _write_ecg_stream(ecg_stream_path, ecg_samples, ecg_rate)
    elif ecg_stream_path.is_file():
        ecg_stream_ok = True

    has_report = (session_dir / "session_report.docx").is_file()
    state = "finalized" if has_report else "imported"
    now = datetime.now()
    artifacts: dict[str, Any] = {
        "csv": {"path": "session.csv", "exists": True},
    }
    if has_edf:
        artifacts["edf"] = {"path": "session.edf", "exists": True}
    if ecg_stream_ok:
        artifacts["ecg_stream"] = {"path": "session_ecg.f32", "exists": True}
    if has_report:
        artifacts["docx_final"] = {"path": "session_report.docx", "exists": True}
    if (session_dir / "session_share.pdf").is_file():
        artifacts["share_pdf_final"] = {"path": "session_share.pdf", "exists": True}

    payload = {
        "schema_version": 1,
        "updated_at": now.isoformat(),
        "session_id": session_id,
        "profile_id": profile,
        "state": state,
        "report_stage": "final" if has_report else "draft",
        "sensor": {
            "selected_device": "adopted",
            "ecg_sample_rate_hz": ecg_rate if ecg_samples else None,
        },
        "timing": {
            "started_at": started.isoformat(),
            "first_data_at": started.isoformat(),
            "ended_at": ended.isoformat(),
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
        "adoption": {
            "reason": "orphan_folder_without_manifest",
            "adopted_at": now.isoformat(),
        },
    }
    write_manifest(manifest_path, payload)

    profile_store.ensure_profile(profile)
    record = {
        "session_id": session_id,
        "profile_name": profile,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "state": state,
        "session_dir": str(session_dir),
        "csv_path": str(csv_path),
    }
    profile_store._upsert_session_history_rows([record])
    hr_vals = list(data.get("hr_values") or [])
    rmssd_vals = list(data.get("rmssd_values") or [])
    avg_hr = sum(hr_vals) / len(hr_vals) if hr_vals else None
    profile_store.record_session_trend(
        profile_name=profile,
        session_id=session_id,
        ended_at=ended,
        avg_hr=avg_hr,
        avg_rmssd=_rmssd_trend_average(rmssd_vals),
    )
    return record


def replay_data_from_ibi_ms(
    ibi_ms: list[int] | list[float],
    *,
    bridge_rmssd_ms: float | None = None,
    annotation: str | None = None,
) -> dict[str, Any] | None:
    """Build normalized replay data from phone-bridge IBI list (ms)."""
    from hnh.hr_series import clean_ibi_series

    raw_cleaned: list[float] = []
    for raw in ibi_ms:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if 200 < value < 3000:
            raw_cleaned.append(value)
    if not raw_cleaned:
        return None

    elapsed_ms = 0.0
    raw_times: list[float] = []
    for ibi in raw_cleaned:
        raw_times.append(elapsed_ms / 1000.0)
        elapsed_ms += ibi

    hr_times, cleaned, _corrections = clean_ibi_series(raw_cleaned, raw_times)
    if not cleaned:
        return None

    hr_values = [60000.0 / ibi for ibi in cleaned]

    # bridge_rmssd_ms is the phone's session summary. The chart uses the live
    # monitor's rolling window so that one number is not drawn across the session.
    _ = bridge_rmssd_ms
    rmssd_times, rmssd_values = rolling_rmssd_series(cleaned, hr_times)
    hrv_times, hrv_values = rolling_sdnn_series(cleaned, hr_times)

    annotations: list[tuple[float, str]] = []
    if annotation:
        annotations.append((0.0, str(annotation)))

    return {
        "hr_times": hr_times,
        "hr_values": hr_values,
        "rmssd_times": rmssd_times,
        "rmssd_values": rmssd_values,
        "hrv_times": hrv_times,
        "hrv_values": hrv_values,
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

    Wire encoding: little-endian int16 or int32 microvolts (+ optional
    scale_uv_per_lsb), base64 in `data`. int32 is the unclamped recording
    format; int16 remains for packages already on disk. Returns
    (samples_mv, sample_rate_hz).
    """
    samples_uv: list[float] = []
    rate_hz = 130
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        encoding = str(chunk.get("encoding") or "").strip().lower()
        if encoding and encoding not in {
            "int16_uv_b64",
            "int16_uv",
            "int32_uv_b64",
            "int32_uv",
        }:
            continue
        wide = encoding in {"int32_uv_b64", "int32_uv"}
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
        width = 4 if wide else 2
        fmt = "<i" if wide else "<h"
        n = len(raw) // width
        for i in range(n):
            (val,) = struct.unpack_from(fmt, raw, i * width)
            samples_uv.append(float(val) * scale)
    rate_hz = max(25, min(1000, int(rate_hz or 130)))
    samples_mv = [v / 1000.0 for v in samples_uv]
    return samples_mv, rate_hz


def import_saved_hrv_package(
    package: dict[str, Any],
    session_root: Path,
    profile_id: str,
    profile_store: ProfileStore,
    *,
    include_profile_subpath: bool = False,
) -> SessionBundle | None:
    """
    Persist a PROTOCOL §7 saved-HRV package into Session History.

    Prefer IBI series; use official bridge `rmssd_ms` when present. Returns None
    when IBIs are missing/unusable, or the existing bundle is already imported
    (caller should treat that as a quiet no-op success via return of None and
    check profile_store mapping — actually return a sentinel).

    `session_root` should be the profile Session Save Path (same root live
    Stop & Save uses). Returns the new SessionBundle, or None if skipped/failed.
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
    patient = str(package.get("profile_display_name") or "").strip()
    phone_profile_id = str(package.get("profile_id") or "").strip()
    note = phone_bridge_import_annotation(
        transfer_reason=reason,
        source_device=source,
        profile_display_name=patient,
    )
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

    start_dt = datetime.now()
    # Phone emit time is Zulu. History stores naive local clocks, same as live sessions.
    if emitted_at:
        parsed_emit = naive_local_from_iso(emitted_at)
        if parsed_emit is not None:
            start_dt = parsed_emit
    end_dt = start_dt + timedelta(seconds=max(1.0, duration_f or 1.0))
    started_at = start_dt.isoformat()
    ended_at = end_dt.isoformat()
    data["started_at"] = started_at

    bundle = create_session_bundle(
        session_root,
        profile_id,
        include_profile_subpath=include_profile_subpath,
        named_at=end_dt,
    )
    write_session_csv(bundle.csv_path, data)

    edf_ok = False
    ecg_stream_ok = False
    if ecg_samples:
        ecg_stream_ok = _write_ecg_stream(bundle.ecg_stream_path, ecg_samples, ecg_rate)
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
    rmssd_for_trend = data.get("rmssd_values") or []
    last_rmssd = rmssd_for_trend[-1] if rmssd_for_trend else None

    phone_package: dict[str, Any] = {
        "session_id": phone_sid,
        "kind": package.get("kind"),
        "mode": package.get("mode"),
        "ibi_count": len(ibi_raw),
        "has_ecg_chunks": bool(ecg_chunks),
        "ecg_sample_count": len(ecg_samples),
        "ecg_sample_rate_hz": ecg_rate if ecg_samples else None,
    }
    if phone_profile_id:
        phone_package["profile_id"] = phone_profile_id
    if patient:
        phone_package["profile_display_name"] = patient
    artifacts: dict[str, Any] = {
        "csv": {"path": str(bundle.csv_path.name), "exists": True},
        "phone_bridge_package": phone_package,
    }
    if edf_ok:
        artifacts["edf"] = {"path": str(bundle.edf_path.name), "exists": True}
    if ecg_stream_ok:
        artifacts["ecg_stream"] = {"path": str(bundle.ecg_stream_path.name), "exists": True}

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
            "ecg_sensor_name": format_ecg_sensor_display_name(source),
            "ecg_sample_rate_hz": ecg_rate if ecg_samples else None,
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

    profile_store.record_session_trend(
        profile_name=profile_id,
        session_id=bundle.session_id,
        ended_at=end_dt,
        avg_hr=last_hr,
        avg_rmssd=_rmssd_trend_average(rmssd_for_trend),
    )
    profile_store.remember_phone_bridge_import(
        profile_id, phone_sid, bundle.session_id
    )
    return bundle
