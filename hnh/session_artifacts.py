from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# Characters invalid in Windows file/folder names, plus ASCII controls and path separators.
_INVALID_PROFILE_PATH_CHAR = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _slugify(value: str) -> str:
    """
    Normalize a profile name for use as a single filesystem path segment (e.g. under Sessions/).

    Spaces and most punctuation are kept so folder names match the profile name users see.
    Only Windows-invalid / cross-platform unsafe characters are replaced with a hyphen.
    """
    text = str(value).strip()
    if not text:
        return "Admin"
    text = _INVALID_PROFILE_PATH_CHAR.sub("-", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"-{2,}", "-", text).strip("-")
    # Windows: name may not end in space or dot.
    text = text.rstrip(". ")
    if text in (".", "..") or not text:
        return "Admin"
    return text


def _profile_name_issue_explanation(clean: str) -> str:
    """Human-readable rule violations for profile labels vs. _slugify; may be empty."""
    fragments: list[str] = []
    bad = sorted(set(_INVALID_PROFILE_PATH_CHAR.findall(clean)), key=lambda c: (ord(c), c))
    if bad:
        shown = ", ".join(repr(c) for c in bad[:12])
        if len(bad) > 12:
            shown += ", …"
        fragments.append(
            f"It contains character(s) not allowed in folder names ({shown}). "
            "Slashes, colons, quotes, angle brackets, pipes, asterisks, question marks, "
            "and control characters cannot be used."
        )
    collapsed_ws = re.sub(r"\s+", " ", clean)
    if clean != collapsed_ws:
        fragments.append("It uses multiple spaces in a row; use a single space between words.")
    if clean != clean.rstrip(". "):
        fragments.append("It cannot end with a space or a period (Windows folder naming rules).")
    if clean in (".", ".."):
        fragments.append("That name is reserved and cannot be used.")
    return " ".join(fragments)


def validate_profile_display_name(name: str) -> tuple[bool, str, str]:
    """
    Whether the trimmed profile name matches the canonical path segment from _slugify.

    Returns (ok, reason_if_bad, suggested_name). For empty input, suggested_name is "".
    """
    clean = str(name).strip()
    if not clean:
        return False, "Profile name cannot be empty.", ""
    suggested = _slugify(clean)
    if clean in (".", ".."):
        return False, _profile_name_issue_explanation(clean), suggested
    if clean == suggested:
        return True, "", clean
    reason = _profile_name_issue_explanation(clean)
    if not reason:
        reason = (
            "Some aspect of this name does not match the rules used for session folders "
            "(for example repeated hyphens after removing invalid characters)."
        )
    if suggested == "Admin" and clean.casefold() != "admin":
        reason = (
            f"{reason} After cleaning the name, only the default profile name "
            "'Admin' could be used."
        ).strip()
    return False, reason, suggested


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


def create_session_bundle(
    root: Path,
    profile_id: str = "Admin",
    *,
    include_profile_subpath: bool = True,
) -> SessionBundle:
    now = datetime.now()
    safe_profile = _slugify(profile_id)
    date_key = now.strftime("%Y-%m-%d")
    session_id = now.strftime("%Y%m%d-%H%M%S")
    if include_profile_subpath:
        base_dir = root / "Sessions" / safe_profile / now.strftime("%Y") / date_key / session_id
    else:
        base_dir = root / now.strftime("%Y") / date_key / session_id
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
        "session_qrs_avg_ms": None,
        "delineation_diagnostics": {},
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
