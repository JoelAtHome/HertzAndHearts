"""Heart-rate series for playback, using the same rules as the live chart."""

from __future__ import annotations

import math
import statistics

from hnh.config import (
    DEVIATION_MIN_SAMPLES,
    DEVIATION_THRESHOLD,
    DEVIATION_WINDOW,
    DROPOUT_IBI_MS,
    HR_EWMA_WEIGHT,
    IBI_MEDIAN_WINDOW,
    MAIN_PLOT_START_SECONDS,
    MAIN_PLOT_SYNC_MIN_IBIS,
    MAX_BEAT_HR_DELTA_BPM,
    MAX_IBI,
    MIN_IBI,
    NOISE_IBI_HIGH_MS,
    NOISE_IBI_LOW_MS,
)


def is_relative_ibi_outlier(
    ibi_ms: float,
    prior_ibis_ms: list[float],
    *,
    deviation_threshold: float = DEVIATION_THRESHOLD,
    deviation_window: int = DEVIATION_WINDOW,
    deviation_min_samples: int = DEVIATION_MIN_SAMPLES,
    max_hr_delta_bpm: float = MAX_BEAT_HR_DELTA_BPM,
) -> bool:
    """True when *ibi_ms* is an artifact vs the median of recent prior beats.

    Flags a beat when either:
    - fractional IBI deviation exceeds ``deviation_threshold``, or
    - implied HR differs from the median HR by more than ``max_hr_delta_bpm``.

    The absolute bpm rule catches short contact needles (e.g. 80→64 bpm) that
    stay under the percentage threshold. Gradual trends survive because
    successive beats move only a fraction of a bpm.
    """
    window = max(1, int(deviation_window))
    min_samples = max(1, int(deviation_min_samples))
    sample = [float(v) for v in prior_ibis_ms[-window:] if float(v) > 0.0]
    if len(sample) < min_samples:
        return False
    median_ibi = statistics.median(sample)
    if median_ibi <= 0.0:
        return False
    candidate = float(ibi_ms)
    if candidate <= 0.0:
        return True
    if deviation_threshold > 0.0 and abs(candidate - median_ibi) / median_ibi > float(
        deviation_threshold
    ):
        return True
    if max_hr_delta_bpm > 0.0:
        median_hr = 60000.0 / median_ibi
        candidate_hr = 60000.0 / candidate
        if abs(candidate_hr - median_hr) > float(max_hr_delta_bpm):
            return True
    return False


def clean_ibi_series(
    ibis_ms: list[float],
    times_sec: list[float] | None = None,
    *,
    median_window: int = IBI_MEDIAN_WINDOW,
    min_ibi_ms: int = MIN_IBI,
    max_ibi_ms: int = MAX_IBI,
    dropout_ms: float = DROPOUT_IBI_MS,
    noise_low_ms: float = NOISE_IBI_LOW_MS,
    noise_high_ms: float = NOISE_IBI_HIGH_MS,
    deviation_threshold: float = DEVIATION_THRESHOLD,
    deviation_window: int = DEVIATION_WINDOW,
    deviation_min_samples: int = DEVIATION_MIN_SAMPLES,
    max_hr_delta_bpm: float = MAX_BEAT_HR_DELTA_BPM,
) -> tuple[list[float], list[float], int]:
    """Clean beat intervals with absolute bounds and relative median outliers.

    Absolute out-of-range intervals are median-replaced when the local window
    is full. Relative outliers (percent or absolute bpm vs the rolling median
    of already-accepted beats) are replaced with that median so successive
    HRV diffs stay sane. Intervals that still fail dropout/noise limits are
    dropped.

    Returns ``(times_sec, cleaned_ibi_ms, corrections)`` where *corrections*
    counts replaced or dropped beats.
    """
    ibis = [float(v) for v in ibis_ms]
    n = len(ibis)
    if n == 0:
        return [], [], 0
    if times_sec is None or len(times_sec) != n:
        elapsed = 0.0
        times: list[float] = []
        for ibi in ibis:
            times.append(elapsed)
            elapsed += max(ibi, 0.0) / 1000.0
    else:
        times = [float(t) for t in times_sec]

    window = max(1, int(median_window))
    history: list[float] = []
    out_times: list[float] = []
    out_ibis: list[float] = []
    corrections = 0

    for ibi, t in zip(ibis, times):
        validated = _median_replace(
            ibi,
            history,
            window=window,
            min_ibi_ms=min_ibi_ms,
            max_ibi_ms=max_ibi_ms,
        )
        if validated != ibi:
            corrections += 1
        if is_relative_ibi_outlier(
            validated,
            history,
            deviation_threshold=deviation_threshold,
            deviation_window=deviation_window,
            deviation_min_samples=deviation_min_samples,
            max_hr_delta_bpm=max_hr_delta_bpm,
        ):
            ref = history[-max(1, int(deviation_window)) :]
            validated = float(statistics.median(ref))
            corrections += 1
        if validated > dropout_ms or validated > noise_high_ms or validated < noise_low_ms:
            corrections += 1
            continue
        if validated <= 0.0:
            corrections += 1
            continue
        history.append(validated)
        out_times.append(t)
        out_ibis.append(validated)
    return out_times, out_ibis, corrections


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
    deviation_threshold: float = DEVIATION_THRESHOLD,
    deviation_window: int = DEVIATION_WINDOW,
    deviation_min_samples: int = DEVIATION_MIN_SAMPLES,
    max_hr_delta_bpm: float = MAX_BEAT_HR_DELTA_BPM,
    plot_start_sec: float = MAIN_PLOT_START_SECONDS,
    min_beats: int = MAIN_PLOT_SYNC_MIN_IBIS,
) -> tuple[list[float], list[float]]:
    """Beat times and smoothed heart rate, matching the live HR chart.

    Out-of-range intervals are replaced with the local median once the
    median window is full. Relative outliers are replaced the same way.
    Intervals that still fail the dropout or noise limits are omitted. The
    plotted value is the same exponential smooth as the live chart, and the
    line starts after the same warmup.
    """
    cleaned_times, cleaned_ibis, _corrections = clean_ibi_series(
        ibis_ms,
        times_sec,
        median_window=median_window,
        min_ibi_ms=min_ibi_ms,
        max_ibi_ms=max_ibi_ms,
        dropout_ms=dropout_ms,
        noise_low_ms=noise_low_ms,
        noise_high_ms=noise_high_ms,
        deviation_threshold=deviation_threshold,
        deviation_window=deviation_window,
        deviation_min_samples=deviation_min_samples,
        max_hr_delta_bpm=max_hr_delta_bpm,
    )
    if not cleaned_ibis:
        return [], []

    weight = float(ewma_weight)
    if weight <= 0.0 or weight > 1.0:
        weight = HR_EWMA_WEIGHT

    out_times: list[float] = []
    out_values: list[float] = []
    ewma: float | None = None
    t0 = cleaned_times[0]
    post_warmup = False

    for idx, (ibi, t) in enumerate(zip(cleaned_ibis, cleaned_times)):
        elapsed = t - t0
        hr = 60000.0 / ibi
        if ewma is None:
            ewma = hr
        elif elapsed >= plot_start_sec and not post_warmup:
            post_warmup = True
            ewma = hr
        else:
            ewma = weight * hr + (1.0 - weight) * ewma
        if not out_values:
            ewma = hr
        if elapsed < plot_start_sec or (idx + 1) < min_beats:
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
