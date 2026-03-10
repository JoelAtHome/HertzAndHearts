from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from hnh.report import generate_session_report, generate_session_share_pdf
from hnh.session_artifacts import default_qtc_payload


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

    return {
        "session_id": str(manifest.get("session_id") or session_dir.name),
        "profile_id": profile_id,
        "session_type": "General Monitoring",
        "session_start": started_at,
        "session_end": ended_at,
        "baseline_hr": baseline_hr,
        "baseline_rmssd": baseline_rmssd,
        "last_hr": last_hr,
        "last_rmssd": last_rmssd,
        "annotations": list(series.get("annotations") or []),
        "hr_values": hr_values,
        "hr_time_seconds": list(series.get("hr_time_seconds") or []),
        "rmssd_values": rmssd_values,
        "rmssd_time_seconds": list(series.get("rmssd_time_seconds") or []),
        "hrv_values": list(series.get("hrv_values") or []),
        "hrv_time_seconds": list(series.get("hrv_time_seconds") or []),
        "stress_ratio_values": list(series.get("stress_ratio_values") or []),
        "snr_values": [],
        "ecg_samples": [],
        "ecg_sample_rate_hz": 130,
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
