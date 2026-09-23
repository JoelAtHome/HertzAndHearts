from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from hnh.config import ECG_SAMPLE_RATE, FEATHER_ECG_SAMPLE_RATE
from hnh.ecg_stream import read_ecg_stream_samples
from hnh.qtc import QtcConfig, compute_qtc_payload_from_ecg
from hnh.report import (
    format_ecg_sensor_display_name,
    generate_session_report,
    generate_session_share_pdf,
)
from hnh.session_artifacts import default_qtc_payload, write_manifest


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_manifest(session_dir: Path) -> dict[str, Any]:
    manifest_path = session_dir / "session_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_csv_path(session_dir: Path, manifest: dict[str, Any]) -> Path:
    artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else {}
    csv_meta = artifacts.get("csv") if isinstance(artifacts, dict) else {}
    csv_path_raw = csv_meta.get("path") if isinstance(csv_meta, dict) else None
    if isinstance(csv_path_raw, str) and csv_path_raw.strip():
        candidate = Path(csv_path_raw)
        if not candidate.is_absolute():
            candidate = session_dir / candidate
        if candidate.exists():
            return candidate
    return session_dir / "session.csv"


def _load_series_from_csv(csv_path: Path) -> dict[str, Any]:
    hr_values: list[float] = []
    hr_time_seconds: list[float] = []
    rmssd_values: list[float] = []
    rmssd_time_seconds: list[float] = []
    hrv_values: list[float] = []
    hrv_time_seconds: list[float] = []
    stress_ratio_values: list[float] = []
    annotations: list[tuple[str, str]] = []
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    current_elapsed_ms = 0.0

    if not csv_path.exists():
        return {
            "hr_values": hr_values,
            "hr_time_seconds": hr_time_seconds,
            "rmssd_values": rmssd_values,
            "rmssd_time_seconds": rmssd_time_seconds,
            "hrv_values": hrv_values,
            "hrv_time_seconds": hrv_time_seconds,
            "stress_ratio_values": stress_ratio_values,
            "annotations": annotations,
            "first_ts": first_ts,
            "last_ts": last_ts,
        }

    with open(csv_path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if "event" not in (reader.fieldnames or ()) or "value" not in (reader.fieldnames or ()):
            return {
                "hr_values": hr_values,
                "hr_time_seconds": hr_time_seconds,
                "rmssd_values": rmssd_values,
                "rmssd_time_seconds": rmssd_time_seconds,
                "hrv_values": hrv_values,
                "hrv_time_seconds": hrv_time_seconds,
                "stress_ratio_values": stress_ratio_values,
                "annotations": annotations,
                "first_ts": first_ts,
                "last_ts": last_ts,
            }

        for row in reader:
            event = str(row.get("event") or "").strip()
            value_raw = row.get("value")
            elapsed_raw = row.get("elapsed_sec")
            ts = _parse_iso_datetime(row.get("timestamp"))
            if ts is not None:
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)

            parsed_elapsed = _to_float(elapsed_raw)
            if parsed_elapsed is not None:
                current_elapsed_ms = max(current_elapsed_ms, parsed_elapsed)

            value = _to_float(value_raw)
            t_sec = current_elapsed_ms / 1000.0

            if event == "IBI" and value is not None and value > 0:
                if parsed_elapsed is None:
                    current_elapsed_ms += value
                    t_sec = current_elapsed_ms / 1000.0
                hr_values.append(60000.0 / value)
                hr_time_seconds.append(t_sec)
                continue

            if event == "hrv" and value is not None:
                rmssd_values.append(value)
                rmssd_time_seconds.append(t_sec)
                continue

            if event == "SDNN" and value is not None:
                hrv_values.append(value)
                hrv_time_seconds.append(t_sec)
                continue

            if event == "stress_ratio" and value is not None:
                stress_ratio_values.append(value)
                continue

            if event == "Annotation":
                annotations.append((f"{t_sec:.1f}s", str(value_raw or "(annotation)")))

    return {
        "hr_values": hr_values,
        "hr_time_seconds": hr_time_seconds,
        "rmssd_values": rmssd_values,
        "rmssd_time_seconds": rmssd_time_seconds,
        "hrv_values": hrv_values,
        "hrv_time_seconds": hrv_time_seconds,
        "stress_ratio_values": stress_ratio_values,
        "annotations": annotations,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def _settings_number(settings: dict, key: str, default: float, cast: type) -> float:
    if not isinstance(settings, dict) or key not in settings:
        return default
    try:
        return cast(settings[key])
    except (TypeError, ValueError):
        return default


def qtc_config_for_rate(sample_rate_hz: int, settings: dict | None = None) -> QtcConfig:
    """QTc settings used for a rebuilt session, matching the live monitor defaults."""
    snapshot = settings if isinstance(settings, dict) else {}
    return QtcConfig(
        sampling_rate=int(sample_rate_hz),
        summary_window_seconds=int(_settings_number(snapshot, "QTC_SUMMARY_WINDOW_SECONDS", 30, int)),
        min_valid_beats=int(_settings_number(snapshot, "QTC_MIN_VALID_BEATS", 12, int)),
        fridericia_hr_low_threshold=int(_settings_number(snapshot, "QTC_FRIDERICIA_HR_LOW_THRESHOLD", 50, int)),
        fridericia_hr_high_threshold=int(_settings_number(snapshot, "QTC_FRIDERICIA_HR_HIGH_THRESHOLD", 100, int)),
        fridericia_hysteresis_bpm=int(_settings_number(snapshot, "QTC_FRIDERICIA_HYSTERESIS_BPM", 5, int)),
        max_rr_gap_seconds=float(_settings_number(snapshot, "QTC_MAX_RR_GAP_SECONDS", 2.5, float)),
        trend_enabled=bool(snapshot.get("QTC_TREND_ENABLED", False)),
    )


def recompute_qtc_from_samples(
    samples: list[float],
    sample_rate_hz: int,
    settings: dict | None = None,
) -> dict[str, Any] | None:
    """
    Recompute the session QTc payload from stored ECG samples.

    Uses the last 120 seconds, which is the same span the live monitor keeps.
    Returns None when the trace is too short for delineation.
    """
    rate = int(sample_rate_hz)
    if rate < 1 or len(samples) < rate * 5:
        return None
    tail = samples[-rate * 120 :]
    return compute_qtc_payload_from_ecg(tail, qtc_config_for_rate(rate, settings))


def build_report_data_from_session_dir(
    session_dir: Path,
    *,
    profile_name: str | None = None,
    report_stage: str = "final",
) -> dict[str, Any]:
    session_dir = Path(session_dir)
    manifest = _load_manifest(session_dir)
    csv_path = _resolve_csv_path(session_dir, manifest)
    series = _load_series_from_csv(csv_path)

    timing = manifest.get("timing") if isinstance(manifest, dict) else {}
    metrics = manifest.get("metrics") if isinstance(manifest, dict) else {}

    started_at = _parse_iso_datetime(timing.get("started_at")) if isinstance(timing, dict) else None
    ended_at = _parse_iso_datetime(timing.get("ended_at")) if isinstance(timing, dict) else None
    if started_at is None:
        started_at = series.get("first_ts") or datetime.now()
    if ended_at is None:
        ended_at = series.get("last_ts") or datetime.now()

    profile_id = (
        str(manifest.get("profile_id") or "").strip()
        if isinstance(manifest, dict)
        else ""
    ) or (str(profile_name or "").strip() or "Admin")

    qtc_payload = default_qtc_payload()
    if isinstance(metrics, dict) and isinstance(metrics.get("qtc"), dict):
        qtc_payload.update(metrics["qtc"])

    hr_values = list(series.get("hr_values") or [])
    rmssd_values = list(series.get("rmssd_values") or [])

    baseline_hr = metrics.get("baseline_hr") if isinstance(metrics, dict) else None
    baseline_rmssd = metrics.get("baseline_rmssd") if isinstance(metrics, dict) else None
    last_hr = metrics.get("last_hr") if isinstance(metrics, dict) else None
    last_rmssd = metrics.get("last_rmssd") if isinstance(metrics, dict) else None
    if last_hr is None and hr_values:
        last_hr = hr_values[-1]
    if last_rmssd is None and rmssd_values:
        last_rmssd = rmssd_values[-1]

    settings_snapshot = manifest.get("settings_snapshot") if isinstance(manifest, dict) else {}
    settling_duration = 15
    if isinstance(settings_snapshot, dict):
        settle = _to_float(settings_snapshot.get("SETTLING_DURATION"))
        if settle is not None:
            settling_duration = int(settle)

    sensor = manifest.get("sensor") if isinstance(manifest, dict) else {}
    source_device = None
    selected_device = None
    ecg_rate = int(ECG_SAMPLE_RATE)
    if isinstance(sensor, dict):
        source_device = sensor.get("source_device")
        selected_device = sensor.get("selected_device")
        stored_name = str(sensor.get("ecg_sensor_name") or "").strip()
        stored_rate = _to_float(sensor.get("ecg_sample_rate_hz"))
        if stored_rate is not None and stored_rate >= 1:
            ecg_rate = int(round(stored_rate))
        elif str(source_device or "").strip().upper() == "FEATHER":
            # Sessions recorded before sample_rate_hz was stored. Feather is 250 Hz.
            ecg_rate = int(FEATHER_ECG_SAMPLE_RATE)
    else:
        stored_name = ""
    ecg_samples: list[float] = []
    stream_path = session_dir / "session_ecg.f32"
    if stream_path.is_file():
        ecg_samples = read_ecg_stream_samples(stream_path)
    ecg_sensor_name = stored_name or format_ecg_sensor_display_name(
        str(source_device or "").strip() or None,
        selected_device=str(selected_device or "").strip() or None,
    )
    recomputed_qtc = recompute_qtc_from_samples(ecg_samples, ecg_rate, settings_snapshot)
    if recomputed_qtc is not None:
        qtc_payload = recomputed_qtc

    return {
        "session_id": str(manifest.get("session_id") or session_dir.name),
        "profile_id": profile_id,
        "session_type": "General Monitoring",
        "session_start": started_at,
        "session_end": ended_at,
        "ecg_sensor_name": ecg_sensor_name,
        "baseline_hr": baseline_hr,
        "baseline_rmssd": baseline_rmssd,
        "last_hr": last_hr,
        "last_rmssd": last_rmssd,
        "annotations": list(series.get("annotations") or []),
        "ecg_cursor_captures": (
            list(manifest.get("ecg_cursor_captures") or [])
            if isinstance(manifest, dict)
            else []
        ),
        "hr_values": hr_values,
        "hr_time_seconds": list(series.get("hr_time_seconds") or []),
        "rmssd_values": rmssd_values,
        "rmssd_time_seconds": list(series.get("rmssd_time_seconds") or []),
        "hrv_values": list(series.get("hrv_values") or []),
        "hrv_time_seconds": list(series.get("hrv_time_seconds") or []),
        "stress_ratio_values": list(series.get("stress_ratio_values") or []),
        "snr_values": [],
        "ecg_samples": ecg_samples,
        "ecg_sample_rate_hz": ecg_rate,
        "ecg_is_simulated": False,
        "notes": "",
        "csv_path": str(csv_path),
        "report_stage": report_stage,
        "qtc": qtc_payload,
        "annotation_associations": [],
        "annotation_associations_method": "",
        "disclaimer": manifest.get("disclaimer") if isinstance(manifest, dict) else {},
        "settling_duration_seconds": settling_duration,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return float(value)
    try:
        import numpy as np

        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.bool_):
            return bool(value)
    except Exception:
        pass
    return value


def write_corrected_qtc_manifest(session_dir: Path, report_data: dict[str, Any]) -> None:
    """Store the recomputed QTc and the ECG sample rate used to produce it."""
    session_dir = Path(session_dir)
    manifest_path = session_dir / "session_manifest.json"
    manifest = _load_manifest(session_dir)
    if not isinstance(manifest, dict):
        manifest = {}
    sensor = manifest.get("sensor")
    if not isinstance(sensor, dict):
        sensor = {}
        manifest["sensor"] = sensor
    rate = report_data.get("ecg_sample_rate_hz")
    if rate is not None:
        sensor["ecg_sample_rate_hz"] = int(rate)
    metrics = manifest.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
        manifest["metrics"] = metrics
    qtc = report_data.get("qtc")
    if isinstance(qtc, dict):
        metrics["qtc"] = _json_ready(qtc)
    write_manifest(manifest_path, manifest)


def refresh_session_reports(session_dir: Path, *, rewrite_edf: bool = True) -> dict[str, Any]:
    """Rebuild the Word/PDF report from stored ECG and write the corrected QTc back."""
    session_dir = Path(session_dir)
    report_data = build_report_data_from_session_dir(session_dir, report_stage="final")
    write_corrected_qtc_manifest(session_dir, report_data)
    docx_path = session_dir / "session_report.docx"
    pdf_path = session_dir / "session_share.pdf"
    generate_session_report(str(docx_path), report_data)
    generate_session_share_pdf(str(pdf_path), report_data)
    edf_status = "skipped"
    if rewrite_edf and (session_dir / "session.edf").exists():
        from hnh.edf_export import export_session_edf_plus

        ok, result = export_session_edf_plus(str(session_dir / "session.edf"), report_data)
        edf_status = str(result) if ok else f"failed: {result}"
    qtc = report_data.get("qtc") if isinstance(report_data.get("qtc"), dict) else {}
    return {
        "session_id": report_data.get("session_id"),
        "ecg_sample_rate_hz": report_data.get("ecg_sample_rate_hz"),
        "session_value_ms": qtc.get("session_value_ms"),
        "session_qrs_avg_ms": qtc.get("session_qrs_avg_ms"),
        "status": qtc.get("status"),
        "reason": (qtc.get("quality") or {}).get("reason"),
        "formula_used": qtc.get("formula_used"),
        "edf": edf_status,
        "docx": str(docx_path),
    }


def generate_reports_for_session_dir(
    session_dir: Path,
    *,
    profile_name: str | None = None,
) -> tuple[Path, Path]:
    session_dir = Path(session_dir)
    report_data = build_report_data_from_session_dir(
        session_dir,
        profile_name=profile_name,
        report_stage="final",
    )
    docx_path = session_dir / "session_report.docx"
    pdf_path = session_dir / "session_share.pdf"
    generate_session_report(str(docx_path), report_data)
    generate_session_share_pdf(str(pdf_path), report_data)
    return docx_path, pdf_path
