"""Display-only ECG baseline removal for session replay.

The saved waveform is left unchanged. Playback subtracts the slow
electrode drift so a phone recording and a live stream share a flat
isoelectric line.
"""

from __future__ import annotations

import math

import numpy as np


def display_ecg(
    samples: list[float],
    sample_rate_hz: float,
    *,
    cutoff_hz: float = 0.5,
) -> list[float]:
    """Zero-phase one-pole high-pass. QRS stays; wander slower than cutoff goes."""
    if not samples:
        return []
    x = np.asarray(samples, dtype=float)
    rate = float(sample_rate_hz)
    if x.size < 4 or rate <= 0.0 or cutoff_hz <= 0.0 or cutoff_hz >= rate / 2.0:
        return [float(v) for v in x]
    finite = np.isfinite(x)
    if not finite.all():
        if not finite.any():
            return [0.0] * int(x.size)
        fill = float(np.median(x[finite]))
        x = np.where(finite, x, fill)
    dt = 1.0 / rate
    rc = 1.0 / (2.0 * math.pi * float(cutoff_hz))
    alpha = rc / (rc + dt)
    filtered = _highpass(x, alpha)
    filtered = _highpass(filtered[::-1], alpha)[::-1]
    return [float(v) for v in filtered]


def _highpass(samples: np.ndarray, alpha: float) -> np.ndarray:
    out = np.empty_like(samples)
    out[0] = 0.0
    prev_x = float(samples[0])
    prev_y = 0.0
    for i in range(1, samples.size):
        cur = float(samples[i])
        prev_y = alpha * (prev_y + cur - prev_x)
        prev_x = cur
        out[i] = prev_y
    return out
