from __future__ import annotations

import csv
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from hnh.profile_store import ProfileStore

# Window design for event-linked delta computation:
# compare stable pre-event window against post-event window.
_PRE_WINDOW_START_SEC = 45.0
_PRE_WINDOW_END_SEC = 5.0
_POST_WINDOW_START_SEC = 5.0
_POST_WINDOW_END_SEC = 45.0

_HR_EFFECT_FLOOR_BPM = 2.0
_RMSSD_EFFECT_FLOOR_MS = 3.0
_SDNN_EFFECT_FLOOR_MS = 3.0
_LFHF_EFFECT_FLOOR = 0.20


def describe_tag_insights_method(
    *,
    include_system_annotations: bool = False,
    since_days: int | None = None,
    min_usable_events: int = 1,
) -> str:
    scope = "all available sessions"
    if since_days is not None and int(since_days) > 0:
        scope = f"last {int(since_days)} days"
    system_policy = (
        "system annotations included"
        if include_system_annotations
        else "system annotations excluded"
    )
    return (
        "Method: per annotation event, compute median post-pre delta using "
        "pre window t-45s..t-5s and post window t+5s..t+45s; aggregate by annotation "
        "for HR, RMSSD, SDNN, and LF/HF where available. "
        f"Scope: {scope}; minimum usable events: {max(1, int(min_usable_events))}; "
        f"{system_policy}. Confidence tiers use sample size, cross-session consistency, and effect size."
    )


def summarize_tag_correlations(
    profile_store: ProfileStore,
    profile_name: str,
    *,
    session_limit: int = 300,
    include_hidden_sessions: bool = False,
    include_system_annotations: bool = False,
    since_days: int | None = None,
    min_usable_events: int = 1,
) -> list[dict[str, object]]:
    sessions = profile_store.list_sessions(
        profile_name,
        include_hidden=bool(include_hidden_sessions),
        limit=max(1, int(session_limit)),
    )
    aggregates: dict[str, dict[str, object]] = {}
    since_dt = _build_since_threshold(since_days)

    for session in sessions:
        if str(session.get("state") or "").strip().lower() == "recording":
            continue
        if since_dt is not None and not _session_is_within_since(session, since_dt):
            continue
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            continue
        csv_path = _resolve_csv_path(session)
        if csv_path is None or not csv_path.exists():
            continue

        parsed = _parse_session_csv(csv_path)
        hr_points = parsed["hr_points"]
        rmssd_points = parsed["rmssd_points"]
        sdnn_points = parsed["sdnn_points"]
        lfhf_points = parsed["lfhf_points"]
        annotations = parsed["annotations"]
        for t_sec, raw_text in annotations:
            clean_text = _normalize_annotation(raw_text)
            if not clean_text:
                continue
            if (not include_system_annotations) and _is_system_annotation(clean_text):
                continue
            key = clean_text.casefold()
            entry = aggregates.get(key)
            if entry is None:
                entry = {
                    "annotation": clean_text,
                    "events": 0,
                    "sessions_all": set(),
                    "sessions_with_metric": set(),
                    "usable_events": 0,
                    "hr_deltas": [],
                    "rmssd_deltas": [],
                }
                aggregates[key] = entry

            entry["events"] = int(entry["events"]) + 1
            entry["sessions_all"].add(session_id)

            hr_delta = _window_delta(hr_points, t_sec)
            rmssd_delta = _window_delta(rmssd_points, t_sec)
            sdnn_delta = _window_delta(sdnn_points, t_sec)
            lfhf_delta = _window_delta(lfhf_points, t_sec)
            if hr_delta is not None:
                entry["hr_deltas"].append(float(hr_delta))
            if rmssd_delta is not None:
                entry["rmssd_deltas"].append(float(rmssd_delta))
            if sdnn_delta is not None:
                entry.setdefault("sdnn_deltas", []).append(float(sdnn_delta))
            if lfhf_delta is not None:
                entry.setdefault("lfhf_deltas", []).append(float(lfhf_delta))
            if (
                hr_delta is not None
                or rmssd_delta is not None
                or sdnn_delta is not None
                or lfhf_delta is not None
            ):
                entry["usable_events"] = int(entry["usable_events"]) + 1
                entry["sessions_with_metric"].add(session_id)

    rows: list[dict[str, object]] = []
    for item in aggregates.values():
        hr_deltas = [float(v) for v in item["hr_deltas"]]
        rmssd_deltas = [float(v) for v in item["rmssd_deltas"]]
        sdnn_deltas = [float(v) for v in item.get("sdnn_deltas") or []]
        lfhf_deltas = [float(v) for v in item.get("lfhf_deltas") or []]
        usable_events = int(item["usable_events"])
        if usable_events < max(1, int(min_usable_events)):
            continue
        sessions_with_metric = int(len(item["sessions_with_metric"]))
        events = int(item["events"])
        sessions = int(len(item["sessions_all"]))
        hr_median = _safe_median(hr_deltas)
        rmssd_median = _safe_median(rmssd_deltas)
        sdnn_median = _safe_median(sdnn_deltas)
        lfhf_median = _safe_median(lfhf_deltas)
        confidence, rank = _confidence_tier(
            usable_events=usable_events,
            sessions_with_metric=sessions_with_metric,
            hr_deltas=hr_deltas,
            rmssd_deltas=rmssd_deltas,
            sdnn_deltas=sdnn_deltas,
            lfhf_deltas=lfhf_deltas,
        )
        rows.append(
            {
                "annotation": str(item["annotation"]),
                "events": events,
                "sessions": sessions,
                "usable_events": usable_events,
                "delta_hr_bpm": hr_median,
                "delta_rmssd_ms": rmssd_median,
                "delta_sdnn_ms": sdnn_median,
                "delta_lfhf": lfhf_median,
                "confidence": confidence,
                "confidence_rank": rank,
                "consistency_pct": _consistency_percent(
                    hr_deltas=hr_deltas,
                    rmssd_deltas=rmssd_deltas,
                    sdnn_deltas=sdnn_deltas,
                    lfhf_deltas=lfhf_deltas,
                ),
                "caveat": _build_caveat(
                    usable_events=usable_events,
                    hr_deltas=hr_deltas,
                    rmssd_deltas=rmssd_deltas,
                    sdnn_deltas=sdnn_deltas,
                    lfhf_deltas=lfhf_deltas,
                ),
            }
        )

    rows.sort(
        key=lambda r: (
            -int(r["confidence_rank"]),
            -int(r["usable_events"]),
            -int(r["events"]),
            str(r["annotation"]).casefold(),
        )
    )
    return rows


def _build_since_threshold(since_days: int | None) -> datetime | None:
    if since_days is None:
        return None
    try:
        days = int(since_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return datetime.now() - timedelta(days=days)


def _session_is_within_since(session_row: dict[str, object], since_dt: datetime) -> bool:
    for key in ("ended_at", "started_at"):
        raw = str(session_row.get(key) or "").strip()
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is not None:
            when = when.astimezone().replace(tzinfo=None)
        return when >= since_dt
    return False


def _resolve_csv_path(session_row: dict[str, object]) -> Path | None:
    csv_raw = str(session_row.get("csv_path") or "").strip()
    if csv_raw:
        return Path(csv_raw)
    session_dir_raw = str(session_row.get("session_dir") or "").strip()
    if not session_dir_raw:
        return None
    return Path(session_dir_raw) / "session.csv"


def _normalize_annotation(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    return value


def _is_system_annotation(text: str) -> bool:
    lower = text.casefold()
    return lower.startswith("[system]")


def _parse_session_csv(csv_path: Path) -> dict[str, list[tuple[float, float]] | list[tuple[float, str]]]:
    hr_points: list[tuple[float, float]] = []
    rmssd_points: list[tuple[float, float]] = []
    sdnn_points: list[tuple[float, float]] = []
    lfhf_points: list[tuple[float, float]] = []
    annotations: list[tuple[float, str]] = []
    current_elapsed_ms = 0.0

    with open(csv_path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if "event" not in fieldnames or "value" not in fieldnames:
            return {
                "hr_points": [],
                "rmssd_points": [],
                "sdnn_points": [],
                "lfhf_points": [],
                "annotations": [],
            }
        for row in reader:
            event = str(row.get("event") or "").strip()
            value_raw = str(row.get("value") or "").strip()
            elapsed_raw = str(row.get("elapsed_sec") or "").strip()
            elapsed_ms = _parse_float(elapsed_raw)
            if elapsed_ms is not None:
                current_elapsed_ms = elapsed_ms
            t_sec = current_elapsed_ms / 1000.0

            if event == "IBI":
                ibi_ms = _parse_float(value_raw)
                if ibi_ms is None or ibi_ms <= 0:
                    continue
                hr_points.append((t_sec, 60000.0 / ibi_ms))
            elif event == "hrv":
                rmssd = _parse_float(value_raw)
                if rmssd is None:
                    continue
                rmssd_points.append((t_sec, rmssd))
            elif event.casefold() == "sdnn":
                sdnn = _parse_float(value_raw)
                if sdnn is None:
                    continue
                sdnn_points.append((t_sec, sdnn))
            elif event.casefold() in {"stress_ratio", "lf/hf", "lfhf"}:
                lfhf = _parse_float(value_raw)
                if lfhf is None:
                    continue
                lfhf_points.append((t_sec, lfhf))
            elif event == "Annotation":
                annotations.append((t_sec, value_raw or "(annotation)"))

    return {
        "hr_points": hr_points,
        "rmssd_points": rmssd_points,
        "sdnn_points": sdnn_points,
        "lfhf_points": lfhf_points,
        "annotations": annotations,
    }


def _parse_float(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _window_delta(points: list[tuple[float, float]], t_sec: float) -> float | None:
    if not points:
        return None
    pre_vals = [
        value
        for ts, value in points
        if (t_sec - _PRE_WINDOW_START_SEC) <= ts <= (t_sec - _PRE_WINDOW_END_SEC)
    ]
    post_vals = [
        value
        for ts, value in points
        if (t_sec + _POST_WINDOW_START_SEC) <= ts <= (t_sec + _POST_WINDOW_END_SEC)
    ]
    if not pre_vals or not post_vals:
        return None
    return float(statistics.median(post_vals) - statistics.median(pre_vals))


def _safe_median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _direction_consistency(values: list[float], *, epsilon: float = 1e-9) -> float:
    if not values:
        return 0.0
    pos = sum(1 for v in values if v > epsilon)
    neg = sum(1 for v in values if v < -epsilon)
    total = pos + neg
    if total == 0:
        return 0.0
    return float(max(pos, neg) / total)


def _confidence_tier(
    *,
    usable_events: int,
    sessions_with_metric: int,
    hr_deltas: list[float],
    rmssd_deltas: list[float],
    sdnn_deltas: list[float],
    lfhf_deltas: list[float],
) -> tuple[str, int]:
    support_n = max(
        usable_events,
        len(hr_deltas),
        len(rmssd_deltas),
        len(sdnn_deltas),
        len(lfhf_deltas),
    )
    consistency = max(
        _direction_consistency(hr_deltas),
        _direction_consistency(rmssd_deltas),
        _direction_consistency(sdnn_deltas),
        _direction_consistency(lfhf_deltas),
    )
    hr_effect = abs(_safe_median(hr_deltas) or 0.0) >= _HR_EFFECT_FLOOR_BPM
    rmssd_effect = abs(_safe_median(rmssd_deltas) or 0.0) >= _RMSSD_EFFECT_FLOOR_MS
    sdnn_effect = abs(_safe_median(sdnn_deltas) or 0.0) >= _SDNN_EFFECT_FLOOR_MS
    lfhf_effect = abs(_safe_median(lfhf_deltas) or 0.0) >= _LFHF_EFFECT_FLOOR
    effect_ok = hr_effect or rmssd_effect or sdnn_effect or lfhf_effect

    if support_n >= 12 and sessions_with_metric >= 4 and consistency >= 0.70 and effect_ok:
        return ("High", 3)
    if support_n >= 6 and sessions_with_metric >= 2 and consistency >= 0.60:
        return ("Moderate", 2)
    return ("Low", 1)


def _build_caveat(
    *,
    usable_events: int,
    hr_deltas: list[float],
    rmssd_deltas: list[float],
    sdnn_deltas: list[float],
    lfhf_deltas: list[float],
) -> str:
    notes: list[str] = []
    if usable_events < 6:
        notes.append("small sample")

    consistency = max(
        _direction_consistency(hr_deltas),
        _direction_consistency(rmssd_deltas),
        _direction_consistency(sdnn_deltas),
        _direction_consistency(lfhf_deltas),
    )
    if consistency < 0.60 and usable_events >= 2:
        notes.append("mixed direction")

    hr_effect = abs(_safe_median(hr_deltas) or 0.0) >= _HR_EFFECT_FLOOR_BPM
    rmssd_effect = abs(_safe_median(rmssd_deltas) or 0.0) >= _RMSSD_EFFECT_FLOOR_MS
    sdnn_effect = abs(_safe_median(sdnn_deltas) or 0.0) >= _SDNN_EFFECT_FLOOR_MS
    lfhf_effect = abs(_safe_median(lfhf_deltas) or 0.0) >= _LFHF_EFFECT_FLOOR
    if usable_events >= 6 and not (hr_effect or rmssd_effect or sdnn_effect or lfhf_effect):
        notes.append("small effect")

    metric_coverage = sum(
        1 for vals in (hr_deltas, rmssd_deltas, sdnn_deltas, lfhf_deltas) if vals
    )
    if metric_coverage < 2:
        notes.append("limited metric coverage")

    if not notes:
        return "—"
    return "; ".join(dict.fromkeys(notes))


def _consistency_percent(
    *,
    hr_deltas: list[float],
    rmssd_deltas: list[float],
    sdnn_deltas: list[float],
    lfhf_deltas: list[float],
) -> int:
    consistency = max(
        _direction_consistency(hr_deltas),
        _direction_consistency(rmssd_deltas),
        _direction_consistency(sdnn_deltas),
        _direction_consistency(lfhf_deltas),
    )
    return int(round(consistency * 100.0))
