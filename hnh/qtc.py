from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Literal
import warnings

import numpy as np


QtcFormula = Literal["bazett", "fridericia", "framingham", "hodges"]


@dataclass(frozen=True)
class QtcConfig:
    sampling_rate: int
    summary_window_seconds: int = 30
    min_valid_beats: int = 12
    fridericia_hr_low_threshold: int = 50
    fridericia_hr_high_threshold: int = 100
    fridericia_hysteresis_bpm: int = 5
    max_rr_gap_seconds: float = 2.5
    trend_enabled: bool = False
    default_formula: QtcFormula = "bazett"


def pick_formula(
    hr_bpm: float,
    default_formula: QtcFormula,
    fridericia_hr_low_threshold: int,
    fridericia_hr_high_threshold: int,
) -> QtcFormula:
    if default_formula == "bazett" and (
        hr_bpm < fridericia_hr_low_threshold or hr_bpm > fridericia_hr_high_threshold
    ):
        return "fridericia"
    return default_formula


def compute_qtc_ms(qt_ms: float, rr_ms: float, formula: QtcFormula) -> float | None:
    if qt_ms <= 0 or rr_ms <= 0:
        return None
    rr_sec = rr_ms / 1000.0
    hr_bpm = 60.0 / rr_sec
    if formula == "bazett":
        return qt_ms / np.sqrt(rr_sec)
    if formula == "fridericia":
        return qt_ms / np.cbrt(rr_sec)
    if formula == "framingham":
        return qt_ms + 154.0 * (1.0 - rr_sec)
    if formula == "hodges":
        return qt_ms + 1.75 * (hr_bpm - 60.0)
    return None


def _compute_snr_db(cleaned: np.ndarray, rpeaks: list, sampling_rate: int) -> float | None:
    """
    Compute signal-to-noise ratio (dB) from cleaned ECG and R-peak indices.
    Signal: RMS of QRS windows around each R-peak. Noise: std of baseline between beats.
    """
    if len(rpeaks) < 3:
        return None
    rpeaks_arr = np.asarray(rpeaks, dtype=int)
    # Signal window: ±6 samples (~46ms) around R-peak = QRS-dominated
    half_win = min(6, sampling_rate // 20)
    signal_vals: list[float] = []
    noise_vals: list[float] = []
    n = len(cleaned)
    for i in range(1, len(rpeaks_arr)):
        r = rpeaks_arr[i]
        r_prev = rpeaks_arr[i - 1]
        rr = r - r_prev
        if rr < sampling_rate // 5:  # skip very short intervals
            continue
        # Signal: QRS window around R
        lo = max(0, r - half_win)
        hi = min(n, r + half_win + 1)
        seg = cleaned[lo:hi]
        if seg.size >= 3:
            rms = float(np.sqrt(np.mean(seg.astype(float) ** 2)) + 1e-12)
            signal_vals.append(rms)
        # Noise: middle 40% of RR (baseline between T and next P)
        mid_start = r_prev + int(0.35 * rr)
        mid_end = r_prev + int(0.65 * rr)
        if mid_end - mid_start >= half_win * 2:
            noise_seg = cleaned[mid_start:mid_end]
            noise_vals.extend(noise_seg.astype(float).tolist())
    if not signal_vals or len(noise_vals) < 10:
        return None
    rms_signal = float(np.sqrt(np.mean(np.array(signal_vals) ** 2)))
    std_noise = float(np.std(noise_vals) + 1e-9)
    if std_noise <= 0:
        return None
    ratio = rms_signal / std_noise
    snr_db = 20.0 * np.log10(max(ratio, 1e-6))
    return float(np.clip(snr_db, 0.0, 50.0))  # cap for display stability


def _to_int_or_none(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick_formula_with_hysteresis(
    hr_bpm: float,
    current_formula: QtcFormula,
    default_formula: QtcFormula,
    low_threshold: int,
    high_threshold: int,
    hysteresis_bpm: int,
) -> QtcFormula:
    if default_formula != "bazett":
        return default_formula

    if current_formula == "bazett":
        if hr_bpm < low_threshold or hr_bpm > high_threshold:
            return "fridericia"
        return "bazett"

    # Current formula is Fridericia: only switch back after re-entering
    # a narrower in-band window.
    low_back = low_threshold + hysteresis_bpm
    high_back = high_threshold - hysteresis_bpm
    if low_back <= hr_bpm <= high_back:
        return "bazett"
    return "fridericia"


def suggest_qtc_method(
    candidates: list[dict],
    cfg: QtcConfig,
) -> dict:
    default_suggestion = {
        "suggested_method": cfg.default_formula,
        "reasoning": "Insufficient valid beats for data-driven recommendation.",
    }
    valid = [c for c in candidates if c.get("is_valid")]
    if len(valid) < cfg.min_valid_beats:
        return default_suggestion

    hr_values = np.asarray([float(c["hr_bpm"]) for c in valid], dtype=float)
    if hr_values.size == 0:
        return default_suggestion
    low = float(cfg.fridericia_hr_low_threshold)
    high = float(cfg.fridericia_hr_high_threshold)
    outside_mask = (hr_values < low) | (hr_values > high)
    outside_ratio = float(np.mean(outside_mask))
    hr_span = float(np.max(hr_values) - np.min(hr_values))
    high_ratio = float(np.mean(hr_values > high))
    low_ratio = float(np.mean(hr_values < low))

    if outside_ratio >= 0.35 or hr_span >= 35.0:
        reason = (
            f"HR is frequently outside {int(low)}-{int(high)} bpm "
            f"(outside_ratio={outside_ratio:.2f}, span={hr_span:.1f} bpm). "
            "Fridericia is less rate-biased at extremes."
        )
        return {"suggested_method": "fridericia", "reasoning": reason}

    if outside_ratio >= 0.15:
        dominant = "high" if high_ratio >= low_ratio else "low"
        reason = (
            f"HR occasionally leaves {int(low)}-{int(high)} bpm range "
            f"(outside_ratio={outside_ratio:.2f}, mostly {dominant}-rate excursions). "
            "Use adaptive Bazett/Fridericia switching with hysteresis."
        )
        return {"suggested_method": "adaptive_bazett_fridericia", "reasoning": reason}

    reason = (
        f"HR remains mostly inside {int(low)}-{int(high)} bpm "
        f"(outside_ratio={outside_ratio:.2f}, span={hr_span:.1f} bpm). "
        "Bazett is acceptable for this dataset."
    )
    return {"suggested_method": "bazett", "reasoning": reason}


def extract_qt_candidates(ecg_samples: list[float], cfg: QtcConfig) -> tuple[list[dict], str | None, float | None]:
    if len(ecg_samples) < max(cfg.sampling_rate * 5, 400):
        return [], "insufficient ecg data", None
    try:
        import neurokit2 as nk
    except Exception:
        return [], "neurokit2 unavailable", None

    try:
        ecg = np.asarray(ecg_samples, dtype=float)
        with warnings.catch_warnings():
            # NeuroKit2 can trigger pandas Copy-on-Write chained-assignment
            # warnings internally on newer pandas versions.
            try:
                from pandas.errors import ChainedAssignmentError
            except Exception:
                ChainedAssignmentError = Warning
            warnings.filterwarnings(
                "ignore",
                category=ChainedAssignmentError,
                module=r"neurokit2\..*",
            )
            cleaned = nk.ecg_clean(ecg, sampling_rate=cfg.sampling_rate, method="neurokit")
            _, peaks_info = nk.ecg_peaks(cleaned, sampling_rate=cfg.sampling_rate, correct_artifacts=True)
            rpeaks = peaks_info.get("ECG_R_Peaks", [])
            if len(rpeaks) < 3:
                return [], "insufficient r peaks", None
            snr_db = _compute_snr_db(cleaned, rpeaks, cfg.sampling_rate)
            q_onsets: list = []
            s_offsets: list = []
            t_offsets: list = []
            for method in ("dwt", "cwt", "peak"):
                try:
                    _, waves = nk.ecg_delineate(
                        cleaned,
                        rpeaks,
                        sampling_rate=cfg.sampling_rate,
                        method=method,
                        show=False,
                    )
                except Exception:
                    continue
                q_candidates = waves.get("ECG_Q_Onsets", [])
                if not q_candidates:
                    # "peak" mode may not provide onset boundaries.
                    q_candidates = waves.get("ECG_Q_Peaks", [])
                s_candidates = waves.get("ECG_S_Offsets", [])
                if not s_candidates:
                    # Fallback when offset boundaries are unavailable.
                    s_candidates = waves.get("ECG_S_Peaks", [])
                t_candidates = waves.get("ECG_T_Offsets", [])
                n_local = min(len(rpeaks), len(q_candidates), len(t_candidates))
                if n_local >= 2:
                    q_onsets = q_candidates
                    s_offsets = s_candidates
                    t_offsets = t_candidates
                    break
    except Exception:
        return [], "ecg delineation failed", None

    n = min(len(rpeaks), len(q_onsets), len(t_offsets))
    if n < 2:
        return [], "insufficient delineation", snr_db

    candidates: list[dict] = []
    for idx in range(1, n):
        q_idx = _to_int_or_none(q_onsets[idx])
        s_idx = _to_int_or_none(s_offsets[idx]) if idx < len(s_offsets) else None
        t_idx = _to_int_or_none(t_offsets[idx])
        r_prev = _to_int_or_none(rpeaks[idx - 1])
        r_idx = _to_int_or_none(rpeaks[idx])
        if q_idx is None or t_idx is None or r_prev is None or r_idx is None:
            continue
        if t_idx <= q_idx or r_idx <= r_prev:
            continue
        qt_ms = (t_idx - q_idx) * 1000.0 / cfg.sampling_rate
        rr_ms = (r_idx - r_prev) * 1000.0 / cfg.sampling_rate
        qrs_ms = None
        if s_idx is not None and s_idx > q_idx:
            qrs_ms = (s_idx - q_idx) * 1000.0 / cfg.sampling_rate
        hr_bpm = 60000.0 / rr_ms if rr_ms > 0 else 0.0
        is_valid = (
            200.0 <= qt_ms <= 650.0
            and 300.0 <= rr_ms <= 2200.0
            and rr_ms <= cfg.max_rr_gap_seconds * 1000.0
        )
        candidates.append(
            {
                "t_sec": float(r_idx) / float(cfg.sampling_rate),
                "qt_ms": float(qt_ms),
                "rr_ms": float(rr_ms),
                "qrs_ms": float(qrs_ms) if qrs_ms is not None else None,
                "hr_bpm": float(hr_bpm),
                "is_valid": bool(is_valid),
                "reason": None if is_valid else "signal quality too low",
            }
        )
    if not candidates:
        return [], "no valid qt candidates", snr_db
    return candidates, None, snr_db


def build_qtc_payload(candidates: list[dict], cfg: QtcConfig, snr_db: float | None = None) -> dict:
    payload = {
        "session_value_ms": None,
        "qrs_ms": None,
        "snr_db": snr_db,
        "summary_method": "median_valid_window",
        "summary_window_seconds": int(cfg.summary_window_seconds),
        "status": "unavailable",
        "quality": {
            "is_valid": False,
            "reason": "signal quality too low",
            "minimum_valid_beats": int(cfg.min_valid_beats),
        },
        "trend": {
            "enabled": bool(cfg.trend_enabled),
            "available": False,
            "label": "For trend context only; clinical interpretation requires review.",
        },
        "formula_default": cfg.default_formula,
        "formula_used": None,
        "method_suggestion": {
            "suggested_method": cfg.default_formula,
            "reasoning": "Insufficient data to determine recommendation.",
        },
        "trend_point": None,
    }
    if not candidates:
        return payload

    # Keep QRS available as a separate, robust summary metric even when
    # strict QTc gating marks the window unavailable.
    qrs_window: list[float] = []
    qrs_times: list[float] = []
    for c in candidates:
        qrs_ms = c.get("qrs_ms")
        t_sec = c.get("t_sec")
        if qrs_ms is None or t_sec is None:
            continue
        try:
            qrs_val = float(qrs_ms)
            t_val = float(t_sec)
        except (TypeError, ValueError):
            continue
        # Practical physiologic guardrails for single-lead beat delineation.
        if 50.0 <= qrs_val <= 180.0:
            qrs_window.append(qrs_val)
            qrs_times.append(t_val)
    if qrs_window:
        max_qrs_t = max(qrs_times)
        min_qrs_t = max_qrs_t - float(cfg.summary_window_seconds)
        window_vals = [v for v, t in zip(qrs_window, qrs_times) if t >= min_qrs_t]
        if window_vals:
            payload["qrs_ms"] = float(median(window_vals))
        payload["session_qrs_avg_ms"] = float(mean(qrs_window))

    valid = [c for c in candidates if c.get("is_valid")]
    if not valid:
        # Provisional trend fallback: keep the monitor responsive even when
        # strict validity gates reject all beats.
        provisional: list[float] = []
        provisional_t: list[float] = []
        for c in candidates:
            qtc_val = compute_qtc_ms(float(c["qt_ms"]), float(c["rr_ms"]), cfg.default_formula)
            if qtc_val is None or not (200.0 <= qtc_val <= 650.0):
                continue
            provisional.append(float(qtc_val))
            provisional_t.append(float(c["t_sec"]))
        if provisional:
            payload["trend_point"] = {
                "t_sec": float(max(provisional_t)),
                "median_ms": float(np.percentile(provisional, 50)),
                "p25_ms": float(np.percentile(provisional, 25)),
                "p75_ms": float(np.percentile(provisional, 75)),
                "is_low_quality": True,
            }
        return payload

    max_t = max(float(c["t_sec"]) for c in valid)
    t_min = max_t - float(cfg.summary_window_seconds)
    window = [c for c in valid if float(c["t_sec"]) >= t_min]
    if window:
        win_qtcs = []
        for c in window:
            qtc_val = compute_qtc_ms(float(c["qt_ms"]), float(c["rr_ms"]), cfg.default_formula)
            if qtc_val is not None and 200.0 <= qtc_val <= 650.0:
                win_qtcs.append(float(qtc_val))
        if win_qtcs:
            p25 = float(np.percentile(win_qtcs, 25))
            p50 = float(np.percentile(win_qtcs, 50))
            p75 = float(np.percentile(win_qtcs, 75))
            payload["trend_point"] = {
                "t_sec": float(max(float(c["t_sec"]) for c in window)),
                "median_ms": p50,
                "p25_ms": p25,
                "p75_ms": p75,
                "is_low_quality": len(window) < cfg.min_valid_beats,
            }
    if len(window) < cfg.min_valid_beats:
        payload["method_suggestion"] = suggest_qtc_method(window, cfg)
        return payload

    qtc_values: list[float] = []
    formulas_used: list[str] = []
    current_formula: QtcFormula = cfg.default_formula
    for c in window:
        hr_bpm = float(c["hr_bpm"])
        formula = _pick_formula_with_hysteresis(
            hr_bpm=hr_bpm,
            current_formula=current_formula,
            default_formula=cfg.default_formula,
            low_threshold=cfg.fridericia_hr_low_threshold,
            high_threshold=cfg.fridericia_hr_high_threshold,
            hysteresis_bpm=cfg.fridericia_hysteresis_bpm,
        )
        current_formula = formula
        qtc = compute_qtc_ms(float(c["qt_ms"]), float(c["rr_ms"]), formula=formula)
        if qtc is None or not (200.0 <= qtc <= 650.0):
            continue
        qtc_values.append(float(qtc))
        formulas_used.append(formula)

    if len(qtc_values) < cfg.min_valid_beats:
        payload["method_suggestion"] = suggest_qtc_method(window, cfg)
        return payload

    payload["session_value_ms"] = float(median(qtc_values))
    payload["status"] = "ok"
    payload["quality"] = {
        "is_valid": True,
        "reason": "ok",
        "minimum_valid_beats": int(cfg.min_valid_beats),
    }
    unique_formulas = sorted(set(formulas_used))
    payload["formula_used"] = unique_formulas[0] if len(unique_formulas) == 1 else "mixed"
    payload["method_suggestion"] = suggest_qtc_method(window, cfg)
    payload["trend_point"] = {
        "t_sec": float(max(float(c["t_sec"]) for c in window)),
        "median_ms": float(np.percentile(qtc_values, 50)),
        "p25_ms": float(np.percentile(qtc_values, 25)),
        "p75_ms": float(np.percentile(qtc_values, 75)),
        "is_low_quality": False,
    }
    if cfg.trend_enabled:
        payload["trend"]["available"] = True
        payload["trend"]["values_ms"] = [round(v, 2) for v in qtc_values]
    return payload


def compute_qtc_payload_from_ecg(ecg_samples: list[float], cfg: QtcConfig) -> dict:
    candidates, err, snr_db = extract_qt_candidates(ecg_samples, cfg)
    payload = build_qtc_payload(candidates, cfg, snr_db)
    if err and not payload["quality"]["is_valid"]:
        payload["quality"]["reason"] = err
    return payload
