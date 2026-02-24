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
