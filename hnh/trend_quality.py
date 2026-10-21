"""Detect unreliable trend segments and split them for report plotting/stats."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence


# Rolling-window plateau: low value range over several seconds = held/fake.
_FLAT_WINDOW_SECONDS = 5.0
_FLAT_WINDOW_SECONDS_MS = 8.0
_FLAT_MIN_SAMPLES = 6
_FLAT_RANGE_HR_BPM = 1.5
_FLAT_RANGE_MS = 0.6  # true held shelf; normal RMSSD wobble stays above this
_FLAT_NEAR_ZERO_MS = 1.0

# Beat-to-beat silence longer than this is a signal gap (matches dropout scale).
_GAP_SECONDS = 3.0

_BAD_LINE = (0, (1.2, 1.2))  # visible dotted dash pattern
_BAD_COLOR = "#6B7280"


def disconnect_intervals_to_elapsed(
    intervals: Sequence[dict[str, Any]] | None,
    *,
    session_origin_ts: float | None,
) -> list[tuple[float, float]]:
    """Convert wall-clock disconnect records to session-elapsed (start, end) seconds."""
    if not intervals or session_origin_ts is None:
        return []
    out: list[tuple[float, float]] = []
    origin = float(session_origin_ts)
    for raw in intervals:
        if not isinstance(raw, dict):
            continue
        try:
            start_ts = float(raw.get("start_ts"))
            end_ts = float(raw.get("end_ts"))
        except (TypeError, ValueError):
            continue
        if end_ts < start_ts:
            start_ts, end_ts = end_ts, start_ts
        start_elapsed = start_ts - origin
        end_elapsed = end_ts - origin
        if end_elapsed < 0:
            continue
        out.append((max(0.0, start_elapsed), max(0.0, end_elapsed)))
    return out


def session_origin_timestamp(
    session_start: datetime | None,
    *,
    fallback_ts: float | None = None,
) -> float | None:
    if isinstance(session_start, datetime):
        try:
            return float(session_start.timestamp())
        except (OSError, OverflowError, ValueError):
            pass
    if fallback_ts is not None:
        return float(fallback_ts)
    return None


def merge_intervals(
    intervals: Sequence[tuple[float, float]],
    *,
    pad_sec: float = 0.0,
) -> list[tuple[float, float]]:
    """Merge overlapping/adjacent intervals, optionally padded."""
    cleaned: list[tuple[float, float]] = []
    for start, end in intervals:
        try:
            a = float(start) - pad_sec
            b = float(end) + pad_sec
        except (TypeError, ValueError):
            continue
        if b < a:
            a, b = b, a
        cleaned.append((a, b))
    if not cleaned:
        return []
    cleaned.sort()
    merged = [cleaned[0]]
    for start, end in cleaned[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 0.05:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def flat_run_intervals(
    values: Sequence[float],
    times_sec: Sequence[float],
    *,
    range_limit: float,
    window_seconds: float = _FLAT_WINDOW_SECONDS,
    min_samples: int = _FLAT_MIN_SAMPLES,
    near_zero: float | None = None,
) -> list[tuple[float, float]]:
    """Return intervals where a rolling time window has very small value range.

    Pairwise consecutive equality misses shelves that jitter slightly; a
    window range catches held contact plateaus that still look flat on the
    report chart.
    """
    n = len(values)
    if n < min_samples or n != len(times_sec):
        return []
    times = [float(t) for t in times_sec]
    vals = [float(v) for v in values]
    flagged = [False] * n
    left = 0
    for right in range(n):
        while left < right and (times[right] - times[left]) > float(window_seconds):
            left += 1
        width = right - left + 1
        if width < min_samples:
            continue
        window_vals = vals[left : right + 1]
        lo = min(window_vals)
        hi = max(window_vals)
        is_flat = (hi - lo) <= float(range_limit)
        if near_zero is not None and hi <= float(near_zero):
            is_flat = True
        if is_flat:
            for i in range(left, right + 1):
                flagged[i] = True

    intervals: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, bad in enumerate(flagged):
        if bad and run_start is None:
            run_start = i
        elif not bad and run_start is not None:
            intervals.append((times[run_start], times[i - 1]))
            run_start = None
    if run_start is not None:
        intervals.append((times[run_start], times[-1]))
    return intervals


def gap_intervals(
    times_sec: Sequence[float],
    *,
    gap_seconds: float = _GAP_SECONDS,
) -> list[tuple[float, float]]:
    """Return intervals spanning large time jumps between successive samples."""
    if len(times_sec) < 2:
        return []
    out: list[tuple[float, float]] = []
    threshold = float(gap_seconds)
    for i in range(1, len(times_sec)):
        t0 = float(times_sec[i - 1])
        t1 = float(times_sec[i])
        if (t1 - t0) > threshold:
            out.append((t0, t1))
    return out


def unreliable_intervals_for_series(
    values: Sequence[float],
    times_sec: Sequence[float],
    *,
    disconnect_elapsed: Sequence[tuple[float, float]] | None = None,
    metric: str = "hr",
) -> list[tuple[float, float]]:
    """Combine disconnect, flat-run, and gap detectors for one metric series."""
    metric_key = str(metric or "hr").casefold()
    if metric_key in {"rmssd", "hrv", "sdnn"}:
        flats = flat_run_intervals(
            values,
            times_sec,
            range_limit=_FLAT_RANGE_MS,
            window_seconds=_FLAT_WINDOW_SECONDS_MS,
            near_zero=_FLAT_NEAR_ZERO_MS,
        )
    else:
        flats = flat_run_intervals(
            values,
            times_sec,
            range_limit=_FLAT_RANGE_HR_BPM,
            window_seconds=_FLAT_WINDOW_SECONDS,
            near_zero=None,
        )
    gaps = gap_intervals(times_sec)
    combined = list(disconnect_elapsed or []) + flats + gaps
    return merge_intervals(combined)


def point_unreliable_mask(
    times_sec: Sequence[float],
    intervals: Sequence[tuple[float, float]],
) -> list[bool]:
    """True when the sample time falls inside an unreliable interval."""
    if not times_sec:
        return []
    if not intervals:
        return [False] * len(times_sec)
    mask: list[bool] = []
    for t in times_sec:
        sample = float(t)
        bad = False
        for start, end in intervals:
            if start <= sample <= end:
                bad = True
                break
        mask.append(bad)
    return mask


def filter_values_excluding_intervals(
    values: Sequence[float],
    times_sec: Sequence[float],
    intervals: Sequence[tuple[float, float]],
) -> list[float]:
    """Keep values whose times fall outside unreliable intervals."""
    if not values:
        return []
    if len(values) != len(times_sec) or not intervals:
        return [float(v) for v in values]
    mask = point_unreliable_mask(times_sec, intervals)
    return [float(v) for v, bad in zip(values, mask) if not bad]


def split_runs(
    values: Sequence[float],
    times_sec: Sequence[float],
    bad_mask: Sequence[bool],
    *,
    gap_seconds: float = _GAP_SECONDS,
) -> list[tuple[bool, list[float], list[float]]]:
    """Split into contiguous (is_bad, times, values) runs.

    Also breaks a run when successive samples are separated by more than
    ``gap_seconds`` so matplotlib never draws a solid bridge across a hole.
    """
    n = len(values)
    if n == 0 or n != len(times_sec) or n != len(bad_mask):
        return []
    runs: list[tuple[bool, list[float], list[float]]] = []
    cur_bad = bool(bad_mask[0])
    cur_t = [float(times_sec[0])]
    cur_v = [float(values[0])]
    for i in range(1, n):
        flag = bool(bad_mask[i])
        dt = float(times_sec[i]) - float(times_sec[i - 1])
        if flag == cur_bad and dt <= float(gap_seconds):
            cur_t.append(float(times_sec[i]))
            cur_v.append(float(values[i]))
            continue
        runs.append((cur_bad, cur_t, cur_v))
        cur_bad = flag
        cur_t = [float(times_sec[i])]
        cur_v = [float(values[i])]
    runs.append((cur_bad, cur_t, cur_v))
    return runs


def plot_quality_series(
    ax: Any,
    times_minutes: Sequence[float],
    values: Sequence[float],
    bad_mask: Sequence[bool],
    *,
    unreliable_intervals_sec: Sequence[tuple[float, float]] | None = None,
    good_color: str = "black",
    bad_color: str = _BAD_COLOR,
    linewidth: float = 1.0,
) -> None:
    """Plot trusted samples solid and unreliable samples dotted/gray.

    Large time holes are left empty (no interpolating bridge). Unreliable
    samples use a broken gray line only — no background bands.
    """
    del unreliable_intervals_sec  # kept for call-site compatibility; unused
    if not values or len(values) != len(times_minutes) or len(values) != len(bad_mask):
        return
    # times_minutes are in minutes; convert the gap threshold to match.
    runs = split_runs(
        values,
        times_minutes,
        bad_mask,
        gap_seconds=_GAP_SECONDS / 60.0,
    )
    for is_bad, xs, ys in runs:
        if len(xs) == 1:
            ax.plot(
                xs,
                ys,
                linestyle="none",
                marker="o",
                markersize=2.2,
                color=bad_color if is_bad else good_color,
                zorder=3,
            )
            continue
        if is_bad:
            ax.plot(
                xs,
                ys,
                color=bad_color,
                linewidth=max(1.4, linewidth),
                linestyle=_BAD_LINE,
                solid_capstyle="round",
                zorder=2,
            )
        else:
            ax.plot(
                xs,
                ys,
                color=good_color,
                linewidth=linewidth,
                linestyle="-",
                zorder=3,
            )
