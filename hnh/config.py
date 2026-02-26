from typing import Final
from math import ceil

# ──────────────────────────────────────────────────────────────────────
#  DEVELOPER / DIAGNOSTICS
# ──────────────────────────────────────────────────────────────────────
# Enables verbose diagnostic messages in the background console window
# (the black terminal that opens behind the app).  Useful for
# troubleshooting BLE, signal quality, and data-path issues.
# Leave False for normal operation.
DEBUG: Final[bool] = False

# ──────────────────────────────────────────────────────────────────────
#  HEART RATE LIMITS
# ──────────────────────────────────────────────────────────────────────
MIN_HEART_RATE: Final[int] = 30   # bpm — physiological floor
MAX_HEART_RATE: Final[int] = 220  # bpm — physiological ceiling

# Inter-Beat Interval (IBI) bounds derived from HR limits.
# Any IBI outside this range is replaced by a local median.
MIN_IBI: Final[int] = ceil(60_000 / MAX_HEART_RATE)   # ~273 ms
MAX_IBI: Final[int] = ceil(60_000 / MIN_HEART_RATE)   # 2000 ms

# Y-axis display range for the IBI (heart-rate) chart.
MIN_PLOT_IBI: Final[int] = 300
MAX_PLOT_IBI: Final[int] = 1500

# ──────────────────────────────────────────────────────────────────────
#  IBI / HRV BUFFERS & HISTORY
# ──────────────────────────────────────────────────────────────────────
# How many seconds of history each chart shows.
IBI_HISTORY_DURATION: Final[int] = 60    # seconds (top chart)
HRV_HISTORY_DURATION: Final[int] = 120   # seconds (bottom chart)

# Buffer sizes are calculated to hold enough samples even at the
# fastest possible heart rate.
IBI_BUFFER_SIZE: Final[int] = ceil(IBI_HISTORY_DURATION / (MIN_IBI / 1000))
HRV_BUFFER_SIZE: Final[int] = ceil(HRV_HISTORY_DURATION / (MIN_IBI / 1000))

# Number of recent IBIs used to compute a local median for outlier
# replacement.  Larger = more stable but slower to react.
IBI_MEDIAN_WINDOW: Final[int] = 11  # samples

# ──────────────────────────────────────────────────────────────────────
#  HRV / RMSSD CALCULATION
# ──────────────────────────────────────────────────────────────────────
# Rolling window (in beats) for the RMSSD calculation displayed on the
# chart and label.  Larger = smoother/slower; smaller = more responsive
# but jumpier.  60 beats ≈ 1 minute at resting HR, matching clinical
# short-term HRV convention.
RMSSD_WINDOW: Final[int] = 60  # beats

# EWMA (Exponentially Weighted Moving Average) weight for internal
# trend tracking.  Range [0, 1]: closer to 0 = heavier smoothing.
# This is used internally for outlier validation, not for the displayed
# RMSSD value.
# https://en.wikipedia.org/wiki/Exponential_smoothing
EWMA_WEIGHT_CURRENT_SAMPLE: Final[float] = 0.1

# Ceiling for HRV outlier replacement — any single beat-to-beat diff
# above this is replaced with the current EWMA value.
MIN_HRV_TARGET: Final[int] = 50
MAX_HRV_TARGET: Final[int] = 600

# ──────────────────────────────────────────────────────────────────────
#  FREQUENCY-DOMAIN ANALYSIS (LF/HF Stress Ratio)
# ──────────────────────────────────────────────────────────────────────
# Minimum number of RR intervals needed before computing the
# frequency-domain LF/HF ratio.  Standard clinical = 56 (~1 min);
# use 20 for faster testing during development.
FREQUENCY_WINDOW_SIZE: Final[int] = 20

# ──────────────────────────────────────────────────────────────────────
#  SESSION TIMING (Calibration Phases)
# ──────────────────────────────────────────────────────────────────────
# Settling phase: initial seconds after connection where data is
# collected but signal quality is not yet judged.
SETTLING_DURATION: Final[int] = 15  # seconds

# Baseline phase: follows settling; the RMSSD average captured here
# becomes the patient's baseline reference.
BASELINE_DURATION: Final[int] = 30  # seconds

# Export EDF+ session artifact on finalization.
# Disabled by default to keep baseline recording/export lightweight.
EXPORT_EDF_PLUS_D: Final[bool] = False

# Number of seconds of beats averaged when smoothing the RMSSD chart
# line.  Larger = smoother trace, smaller = more beat-to-beat detail.
SMOOTH_SECONDS: Final[int] = 18

# EWMA weight for the averaged heart-rate line on the top chart.
# Higher = snappier response to HR changes; lower = smoother but laggier.
HR_EWMA_WEIGHT: Final[float] = 0.33

# ──────────────────────────────────────────────────────────────────────
#  BREATHING PACER
# ──────────────────────────────────────────────────────────────────────
MIN_BREATHING_RATE: Final[float] = 4.0  # breaths per minute
MAX_BREATHING_RATE: Final[float] = 7.0  # breaths per minute


def tick_to_breathing_rate(tick: int) -> float:
    return (tick + 8) / 2  # scale tick to [4, 7], step .5


def breathing_rate_to_tick(rate: float) -> int:
    return ceil(rate * 2 - 8)  # scale rate to [0, 6], step 1


# ──────────────────────────────────────────────────────────────────────
#  ECG MONITOR (Floating Window)
# ──────────────────────────────────────────────────────────────────────
# Polar H10 PMD ECG stream sample rate.
ECG_SAMPLE_RATE: Final[int] = 130  # Hz

# How many seconds of ECG waveform are visible at once.
ECG_DISPLAY_SECONDS: Final[int] = 5

# Total samples held in the ECG circular buffer.
ECG_BUFFER_SIZE: Final[int] = ECG_SAMPLE_RATE * ECG_DISPLAY_SECONDS  # 650

# Chart refresh interval.  33 ms ≈ 30 fps — a good balance between
# smooth animation and CPU/GPU load.
ECG_REFRESH_MS: Final[int] = 33

# ──────────────────────────────────────────────────────────────────────
#  ECG TRIGGER (R-peak Detection for Oscilloscope Sweep)
# ──────────────────────────────────────────────────────────────────────
# Initial threshold (mV) for detecting an R-peak to trigger a new sweep.
# Automatically adapts to 50% of tracked peak amplitude during operation.
ECG_TRIGGER_THRESHOLD: Final[float] = 0.3

# ──────────────────────────────────────────────────────────────────────
#  SIGNAL QUALITY DETECTION
# ──────────────────────────────────────────────────────────────────────
# Seconds of silence before declaring "Signal: LOST".
# Shorter = faster detection but may false-trigger during brief dropouts.
DATA_TIMEOUT_SECONDS: Final[float] = 5.0

# Level 1 fault: IBI exceeding this (ms) indicates total signal dropout
# (>3 seconds between beats is not physiologically possible).
DROPOUT_IBI_MS: Final[int] = 3000

# Level 2 fault: hard IBI limits for noise/artifact detection.
# These are tighter than MIN_IBI/MAX_IBI to catch borderline garbage.
NOISE_IBI_LOW_MS: Final[int] = 300    # < 300 ms ≈ HR > 200 bpm
NOISE_IBI_HIGH_MS: Final[int] = 2000  # > 2000 ms ≈ HR < 30 bpm

# Level 3 fault (adaptive): percentage deviation from the rolling
# average that triggers an "ERRATIC" warning.  0.30 = 30%.
DEVIATION_THRESHOLD: Final[float] = 0.30

# Number of recent IBIs used to compute the Level 3 rolling average.
DEVIATION_WINDOW: Final[int] = 30

# Minimum IBIs in the rolling window before Level 3 check activates.
# Prevents false faults during the first few seconds of a session.
DEVIATION_MIN_SAMPLES: Final[int] = 10

# Number of consecutive normal beats required to clear an active fault
# and restore "Signal: GOOD".  Higher = more cautious recovery.
RECOVERY_BEATS: Final[int] = 10

# ──────────────────────────────────────────────────────────────────────
#  QTC ESTIMATION
# ──────────────────────────────────────────────────────────────────────
# Canonical session summary window.
QTC_SUMMARY_WINDOW_SECONDS: Final[int] = 30

# Minimum valid beats needed to publish a QTc summary value.
QTC_MIN_VALID_BEATS: Final[int] = 12

# If default formula is Bazett, switch to Fridericia below this HR.
QTC_FRIDERICIA_HR_LOW_THRESHOLD: Final[int] = 50

# If default formula is Bazett, switch to Fridericia above this HR.
QTC_FRIDERICIA_HR_HIGH_THRESHOLD: Final[int] = 100

# Hysteresis band used to prevent rapid method toggling around thresholds.
QTC_FRIDERICIA_HYSTERESIS_BPM: Final[int] = 5

# Maximum allowed gap between consecutive valid beats for QTc summary.
QTC_MAX_RR_GAP_SECONDS: Final[float] = 2.5

# Dedicated QTc trend is disabled by default for MVP.
QTC_TREND_ENABLED: Final[bool] = False

# ──────────────────────────────────────────────────────────────────────
#  ANNOTATION PRESETS
# ──────────────────────────────────────────────────────────────────────
# Factory-default annotations shown in the monitoring page's annotation
# combo box.  User-added annotations are persisted separately in the
# JSON settings file and merged with this list at runtime.
ANNOTATION_PRESETS: Final[list[str]] = [
    "Caffeine intake",
    "Deep breathing started",
    "Deep breathing stopped",
    "Exercise started",
    "Exercise stopped",
    "Medication taken",
    "Orthostatic - standing",
    "Orthostatic - supine",
    "Polar H10 strap adjusted",
    "Position change",
    "Rest period",
    "Sensor strap went dry",
    "Session paused",
    "Session resumed",
    "Stress event",
]

# ──────────────────────────────────────────────────────────────────────
#  SENSOR COMPATIBILITY
# ──────────────────────────────────────────────────────────────────────
COMPATIBLE_SENSORS: Final[list[str]] = ["Polar", "Decathlon Dual HR"]
