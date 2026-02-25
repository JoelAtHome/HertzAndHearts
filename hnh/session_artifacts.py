from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    text = text.strip("-._")
    return text or "Default"


def _next_available_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(1, 1000):
        candidate = Path(f"{path}_{idx:02d}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Unable to allocate a unique session directory.")


@dataclass
class SessionBundle:
    session_id: str
    profile_id: str
    session_dir: Path
    csv_path: Path
    report_final_path: Path
    report_draft_path: Path
    manifest_path: Path
    edf_path: Path
    started_at: datetime


def create_session_bundle(root: Path, profile_id: str = "Default") -> SessionBundle:
    now = datetime.now()
    safe_profile = _slugify(profile_id)
    date_key = now.strftime("%Y-%m-%d")
    session_id = now.strftime("%Y%m%d-%H%M%S")
    base_dir = root / "Sessions" / safe_profile / now.strftime("%Y") / date_key / session_id
    session_dir = _next_available_dir(base_dir)
    session_dir.mkdir(parents=True, exist_ok=False)

    return SessionBundle(
        session_id=session_dir.name,
        profile_id=safe_profile,
        session_dir=session_dir,
        csv_path=session_dir / "session.csv",
        report_final_path=session_dir / "session_report.docx",
        report_draft_path=session_dir / "session_report_draft.docx",
        manifest_path=session_dir / "session_manifest.json",
        edf_path=session_dir / "session.edf",
        started_at=now,
    )


def write_manifest(path: Path, payload: dict):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def default_qtc_payload() -> dict:
    """Canonical QTc metadata scaffold until QTc estimation is implemented."""
    return {
        "session_value_ms": None,
        "qrs_ms": None,
        "summary_method": "median_valid_window",
        "summary_window_seconds": 30,
        "status": "unavailable",
        "quality": {
            "is_valid": False,
            "reason": "signal quality too low",
            "minimum_valid_beats": 12,
        },
        "trend": {
            "enabled": False,
            "available": False,
            "label": "For trend context only; clinical interpretation requires review.",
        },
        "formula_default": "bazett",
        "formula_used": None,
        "method_suggestion": {
            "suggested_method": "bazett",
            "reasoning": "Insufficient data to determine recommendation.",
        },
        "trend_point": None,
    }
