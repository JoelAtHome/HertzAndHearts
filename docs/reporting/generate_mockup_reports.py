from __future__ import annotations

from datetime import datetime, timedelta
import math
from pathlib import Path

from hnh.edf_export import export_session_edf_plus
from hnh.report import generate_session_report, generate_session_share_pdf


def _build_session_payload(
    *,
    session_id: str,
    profile_id: str,
    start: datetime,
    minutes: int,
    baseline_hr: float,
    baseline_rmssd: float,
    hr_values: list[float],
    rmssd_values: list[float],
    annotations: list[tuple[str, str]],
    csv_path: Path,
    report_stage: str,
    ecg_samples: list[float],
) -> dict:
    end = start + timedelta(minutes=minutes)
    duration_sec = max(1.0, float(minutes * 60))

    def _series_times(count: int) -> list[float]:
        if count <= 0:
            return []
        if count == 1:
            return [0.0]
        step = duration_sec / float(count - 1)
        return [round(i * step, 3) for i in range(count)]

    return {
        "session_id": session_id,
        "profile_id": profile_id,
        "session_type": "General Monitoring",
        "session_start": start,
        "session_end": end,
        "baseline_hr": baseline_hr,
        "baseline_rmssd": baseline_rmssd,
        "last_hr": hr_values[-1] if hr_values else None,
        "last_rmssd": rmssd_values[-1] if rmssd_values else None,
        "annotations": annotations,
        "hr_values": hr_values,
        "hr_time_seconds": _series_times(len(hr_values)),
        "rmssd_values": rmssd_values,
        "rmssd_time_seconds": _series_times(len(rmssd_values)),
        "ecg_samples": ecg_samples,
        "ecg_sample_rate_hz": 130,
        "ecg_is_simulated": True,
        "notes": "Mockup data for report formatting review.",
        "csv_path": str(csv_path),
        "report_stage": report_stage,
        "qtc": {
            "session_value_ms": 422,
            "quality": {"reason": None},
            "trend": {"enabled": False, "label": ""},
        },
        "disclaimer": {
            "warning": "RESEARCH USE ONLY - NOT FOR CLINICAL DIAGNOSIS OR TREATMENT.",
            "source_path": "hnh/disclaimer.md",
            "text": "Mockup-only data. Not clinical guidance.",
            "sha256": "mockup",
            "acknowledgment_mode": "interactive_dialog",
            "acknowledged_at": start.isoformat(timespec="seconds"),
        },
    }


def _write_mock_csv(path: Path, hr_values: list[float], rmssd_values: list[float], start: datetime):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["event,value,timestamp,elapsed_sec"]
    now = start
    elapsed = 0.0
    for hr, rmssd in zip(hr_values, rmssd_values):
        lines.append(f"HR,{hr:.1f},{now.isoformat(timespec='seconds')},{elapsed}")
        lines.append(f"hrv,{rmssd:.2f},{now.isoformat(timespec='seconds')},{elapsed}")
        now += timedelta(seconds=15)
        elapsed += 15
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_mock_ecg(sample_rate_hz: int = 130, seconds: int = 8) -> list[float]:
    total = max(1, sample_rate_hz * seconds)
    values: list[float] = []
    for i in range(total):
        t = i / float(sample_rate_hz)
        # Simple synthetic ECG-like waveform for layout preview only.
        base = 0.12 * math.sin(2 * math.pi * 1.2 * t) + 0.02 * math.sin(2 * math.pi * 35.0 * t)
        phase = (t * 1.1) % 1.0
        r_peak = 0.9 * math.exp(-((phase - 0.06) / 0.012) ** 2)
        q_dip = -0.18 * math.exp(-((phase - 0.04) / 0.01) ** 2)
        s_dip = -0.22 * math.exp(-((phase - 0.09) / 0.014) ** 2)
        values.append(base + q_dip + r_peak + s_dip)
    return values


def main():
    root = Path("Sessions") / "Mockups" / "Jordan-Lee" / "2026-02-26-final-format-pass-v5"
    root.mkdir(parents=True, exist_ok=True)

    profile = "Jordan Lee"
    sessions = [
        {
            "session_id": "20260224-070500",
            "start": datetime(2026, 2, 24, 7, 5, 0),
            "minutes": 8,
            "baseline_hr": 79.0,
            "baseline_rmssd": 20.8,
            "hr_values": [81, 80, 79, 78, 77, 77, 76],
            "rmssd_values": [18.9, 19.4, 20.1, 21.7, 22.4, 23.2, 24.0],
            "annotations": [("07:08:15", "Deep breathing started")],
        },
        {
            "session_id": "20260225-071200",
            "start": datetime(2026, 2, 25, 7, 12, 0),
            "minutes": 10,
            "baseline_hr": 77.5,
            "baseline_rmssd": 23.1,
            "hr_values": [79, 78, 77, 76, 76, 75, 75, 74],
            "rmssd_values": [21.0, 22.2, 23.0, 24.1, 25.6, 26.0, 26.8, 27.4],
            "annotations": [("07:15:30", "Position change"), ("07:18:10", "Rest period")],
        },
        {
            "session_id": "20260226-073000",
            "start": datetime(2026, 2, 26, 7, 30, 0),
            "minutes": 12,
            "baseline_hr": 76.2,
            "baseline_rmssd": 25.0,
            "hr_values": [78, 77, 76, 75, 74, 74, 73, 73, 72],
            "rmssd_values": [22.5, 23.8, 24.7, 25.2, 26.6, 27.9, 29.1, 30.0, 31.2],
            "annotations": [("07:34:20", "Deep breathing started"), ("07:38:45", "Deep breathing stopped")],
        },
    ]

    for idx, session in enumerate(sessions):
        session_dir = root / session["session_id"]
        session_dir.mkdir(parents=True, exist_ok=True)
        csv_path = session_dir / "session.csv"
        _write_mock_csv(csv_path, session["hr_values"], session["rmssd_values"], session["start"])

        stage = "final" if idx < len(sessions) - 1 else "draft"
        payload = _build_session_payload(
            session_id=session["session_id"],
            profile_id=profile,
            start=session["start"],
            minutes=session["minutes"],
            baseline_hr=session["baseline_hr"],
            baseline_rmssd=session["baseline_rmssd"],
            hr_values=session["hr_values"],
            rmssd_values=session["rmssd_values"],
            annotations=session["annotations"],
            csv_path=csv_path,
            report_stage=stage,
            ecg_samples=_make_mock_ecg(),
        )

        docx_name = "session_report_draft.docx" if stage == "draft" else "session_report.docx"
        pdf_name = "session_share_draft.pdf" if stage == "draft" else "session_share.pdf"
        generate_session_report(str(session_dir / docx_name), payload)
        generate_session_share_pdf(str(session_dir / pdf_name), payload)
        export_session_edf_plus(str(session_dir / "session.edf"), payload)

    print(f"Mockup reports generated in: {root.resolve()}")


if __name__ == "__main__":
    main()
