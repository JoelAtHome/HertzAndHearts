"""Heart-rate series for playback, using the same rules as the live chart."""

from __future__ import annotations

import math
import statistics

from hnh.config import (
    DROPOUT_IBI_MS,
    HR_EWMA_WEIGHT,
    IBI_MEDIAN_WINDOW,
    MAIN_PLOT_START_SECONDS,
    MAIN_PLOT_SYNC_MIN_IBIS,
    MAX_IBI,
    MIN_IBI,
    NOISE_IBI_HIGH_MS,
    NOISE_IBI_LOW_MS,
)


def display_hr_from_ibis(
    ibis_ms: list[float],
    times_sec: list[float] | None = None,
    *,
    ewma_weight: float = HR_EWMA_WEIGHT,
    median_window: int = IBI_MEDIAN_WINDOW,
    min_ibi_ms: int = MIN_IBI,
    max_ibi_ms: int = MAX_IBI,
    dropout_ms: float = DROPOUT_IBI_MS,
    noise_low_ms: float = NOISE_IBI_LOW_MS,
    noise_high_ms: float = NOISE_IBI_HIGH_MS,
    plot_start_sec: float = MAIN_PLOT_START_SECONDS,
    min_beats: int = MAIN_PLOT_SYNC_MIN_IBIS,
) -> tuple[list[float], list[float]]:
    """Beat times and smoothed heart rate, matching the live HR chart.

    Out-of-range intervals are replaced with the local median once the
    median window is full. Intervals that still fail the dropout or noise
    limits are omitted. The plotted value is the same exponential smooth
    as the live chart, and the line starts after the same warmup.
    """
    ibis = [float(v) for v in ibis_ms]
    n = len(ibis)
    if n == 0:
        return [], []
    if times_sec is None or len(times_sec) != n:
        elapsed = 0.0
        times: list[float] = []
        for ibi in ibis:
            times.append(elapsed)
            elapsed += max(ibi, 0.0) / 1000.0
    else:
        times = [float(t) for t in times_sec]

    weight = float(ewma_weight)
    if weight <= 0.0 or weight > 1.0:
        weight = HR_EWMA_WEIGHT
    window = max(1, int(median_window))

    history: list[float] = []
    out_times: list[float] = []
    out_values: list[float] = []
    ewma: float | None = None
    t0: float | None = None
    post_warmup = False

    for ibi, t in zip(ibis, times):
        validated = _median_replace(
            ibi,
            history,
            window=window,
            min_ibi_ms=min_ibi_ms,
            max_ibi_ms=max_ibi_ms,
        )
        history.append(validated)
        if validated > dropout_ms or validated > noise_high_ms or validated < noise_low_ms:
            continue
        if validated <= 0.0:
            continue
        if t0 is None:
            t0 = t
        elapsed = t - t0
        hr = 60000.0 / validated
        if ewma is None:
            ewma = hr
        elif elapsed >= plot_start_sec and not post_warmup:
            post_warmup = True
            ewma = hr
        else:
            ewma = weight * hr + (1.0 - weight) * ewma
        if not out_values:
            ewma = hr
        if elapsed < plot_start_sec or len(history) < min_beats:
            continue
        out_times.append(t)
        out_values.append(ewma)
    return out_times, out_values


def _median_replace(
    ibi: float,
    history: list[float],
    *,
    window: int,
    min_ibi_ms: int,
    max_ibi_ms: int,
) -> float:
    if len(history) < window:
        return ibi
    if min_ibi_ms <= ibi <= max_ibi_ms:
        return ibi
    sample = history[-window:]
    median_ibi = math.ceil(statistics.median(sample))
    if median_ibi < min_ibi_ms:
        return float(min_ibi_ms)
    if median_ibi > max_ibi_ms:
        return float(max_ibi_ms)
    return float(median_ibi)
