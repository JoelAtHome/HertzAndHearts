from __future__ import annotations

import unittest

from hnh.qtc import (
    QtcConfig,
    build_qtc_payload,
    compute_qtc_ms,
    pick_formula,
    suggest_qtc_method,
)


def _candidate(t_sec: float, qt_ms: float, rr_ms: float, valid: bool = True) -> dict:
    hr_bpm = 60000.0 / rr_ms
    return {
        "t_sec": t_sec,
        "qt_ms": qt_ms,
        "rr_ms": rr_ms,
        "hr_bpm": hr_bpm,
        "is_valid": valid,
        "reason": None if valid else "signal quality too low",
    }


class QtcTests(unittest.TestCase):
    def test_pick_formula_switches_to_fridericia_outside_band(self):
        self.assertEqual(pick_formula(85.0, "bazett", 50, 100), "bazett")
        self.assertEqual(pick_formula(105.0, "bazett", 50, 100), "fridericia")
        self.assertEqual(pick_formula(45.0, "bazett", 50, 100), "fridericia")
        self.assertEqual(pick_formula(105.0, "framingham", 50, 100), "framingham")

    def test_compute_qtc_ms_bazett(self):
        # QT=400ms, RR=1000ms -> QTc remains 400ms.
        self.assertAlmostEqual(float(compute_qtc_ms(400.0, 1000.0, "bazett")), 400.0, places=2)

    def test_compute_qtc_ms_fridericia(self):
        # QT=380ms, RR=800ms -> ~409ms with Fridericia.
        val = compute_qtc_ms(380.0, 800.0, "fridericia")
        self.assertIsNotNone(val)
        self.assertAlmostEqual(float(val), 409.34, places=1)

    def test_build_payload_unavailable_when_insufficient_valid_beats(self):
        cfg = QtcConfig(sampling_rate=130, min_valid_beats=4, summary_window_seconds=30)
        candidates = [
            _candidate(1.0, 360.0, 900.0, True),
            _candidate(2.0, 362.0, 910.0, True),
            _candidate(3.0, 359.0, 905.0, False),
        ]
        payload = build_qtc_payload(candidates, cfg)
        self.assertEqual(payload["status"], "unavailable")
        self.assertFalse(payload["quality"]["is_valid"])
        self.assertIsNone(payload["session_value_ms"])

    def test_build_payload_uses_median_window_and_mixed_formula_metadata(self):
        cfg = QtcConfig(
            sampling_rate=130,
            min_valid_beats=3,
            summary_window_seconds=30,
            fridericia_hr_low_threshold=50,
            fridericia_hr_high_threshold=100,
            fridericia_hysteresis_bpm=5,
        )
        candidates = [
            _candidate(10.0, 370.0, 900.0, True),  # Bazett
            _candidate(20.0, 365.0, 850.0, True),  # Bazett
            _candidate(30.0, 360.0, 550.0, True),  # Fridericia (high HR)
            _candidate(31.0, 362.0, 540.0, True),  # Fridericia (high HR)
        ]
        payload = build_qtc_payload(candidates, cfg)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["quality"]["is_valid"])
        self.assertIsNotNone(payload["session_value_ms"])
        self.assertEqual(payload["formula_default"], "bazett")
        self.assertEqual(payload["formula_used"], "mixed")
        self.assertIn("method_suggestion", payload)
        self.assertIn("suggested_method", payload["method_suggestion"])
        self.assertIsNotNone(payload["trend_point"])
        self.assertIn("median_ms", payload["trend_point"])

    def test_hysteresis_keeps_formula_stable_near_high_threshold(self):
        cfg = QtcConfig(
            sampling_rate=130,
            min_valid_beats=4,
            summary_window_seconds=30,
            fridericia_hr_low_threshold=50,
            fridericia_hr_high_threshold=100,
            fridericia_hysteresis_bpm=5,
        )
        # Starts high (Fridericia), then drops but remains above the back-switch
        # threshold (95 bpm), so hysteresis should keep Fridericia active.
        candidates = [
            _candidate(1.0, 360.0, 580.0, True),  # ~103 bpm
            _candidate(2.0, 361.0, 600.0, True),  # 100 bpm
            _candidate(3.0, 362.0, 620.0, True),  # ~97 bpm
            _candidate(4.0, 363.0, 625.0, True),  # ~96 bpm
        ]
        payload = build_qtc_payload(candidates, cfg)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["formula_used"], "fridericia")

    def test_suggest_method_reports_adaptive_for_mixed_hr(self):
        cfg = QtcConfig(sampling_rate=130, min_valid_beats=4)
        candidates = [
            _candidate(1.0, 360.0, 1200.0, True),  # 50 bpm edge
            _candidate(2.0, 360.0, 580.0, True),   # 103 bpm
            _candidate(3.0, 360.0, 900.0, True),   # 67 bpm
            _candidate(4.0, 360.0, 850.0, True),   # 70 bpm
            _candidate(5.0, 360.0, 560.0, True),   # 107 bpm
        ]
        suggestion = suggest_qtc_method(candidates, cfg)
        self.assertIn(suggestion["suggested_method"], {"adaptive_bazett_fridericia", "fridericia"})
        self.assertTrue(len(suggestion["reasoning"]) > 10)

    def test_synthetic_qt_rr_vectors_cover_low_normal_high_hr_ranges(self):
        # Synthetic vectors for quick numeric sanity checks across HR regimes.
        low_hr_bazett = compute_qtc_ms(qt_ms=360.0, rr_ms=1200.0, formula="bazett")
        normal_hr_bazett = compute_qtc_ms(qt_ms=360.0, rr_ms=900.0, formula="bazett")
        high_hr_fridericia = compute_qtc_ms(qt_ms=360.0, rr_ms=550.0, formula="fridericia")
        self.assertIsNotNone(low_hr_bazett)
        self.assertIsNotNone(normal_hr_bazett)
        self.assertIsNotNone(high_hr_fridericia)
        self.assertTrue(320.0 <= float(low_hr_bazett) <= 340.0)
        self.assertTrue(375.0 <= float(normal_hr_bazett) <= 385.0)
        self.assertTrue(430.0 <= float(high_hr_fridericia) <= 450.0)

    def test_noisy_candidates_keep_stable_summary_and_unavailable_fallback(self):
        cfg = QtcConfig(sampling_rate=130, min_valid_beats=4, summary_window_seconds=30)
        mostly_valid = [
            _candidate(1.0, 360.0, 900.0, True),
            _candidate(2.0, 361.0, 905.0, True),
            _candidate(3.0, 359.0, 910.0, True),
            _candidate(4.0, 360.0, 898.0, True),
            _candidate(5.0, 620.0, 250.0, False),  # noisy outlier
            _candidate(6.0, 180.0, 2600.0, False),  # noisy outlier
        ]
        payload_a = build_qtc_payload(mostly_valid, cfg)
        payload_b = build_qtc_payload(mostly_valid, cfg)
        self.assertEqual(payload_a["status"], "ok")
        self.assertIsNotNone(payload_a["session_value_ms"])
        self.assertAlmostEqual(float(payload_a["session_value_ms"]), float(payload_b["session_value_ms"]), places=6)

        too_noisy = [
            _candidate(1.0, 620.0, 250.0, False),
            _candidate(2.0, 180.0, 2600.0, False),
            _candidate(3.0, 190.0, 2800.0, False),
            _candidate(4.0, 640.0, 220.0, False),
        ]
        payload_unavailable = build_qtc_payload(too_noisy, cfg)
        self.assertEqual(payload_unavailable["status"], "unavailable")
        self.assertFalse(payload_unavailable["quality"]["is_valid"])
        self.assertIsNone(payload_unavailable["session_value_ms"])


if __name__ == "__main__":
    unittest.main()
