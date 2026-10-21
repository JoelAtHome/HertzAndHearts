from __future__ import annotations

import unittest

import numpy as np

from hnh.ecg_display import display_ecg
from hnh.hr_series import clean_ibi_series, display_hr_from_ibis


class DisplayHrTests(unittest.TestCase):
    def test_artifact_interval_does_not_spike_the_line(self):
        intervals = [800.0] * 20 + [250.0, 2500.0] + [800.0] * 10
        times, hr = display_hr_from_ibis(intervals)
        self.assertGreater(len(hr), 5)
        self.assertLess(max(hr), 100.0)
        self.assertGreater(min(hr), 60.0)
        self.assertGreaterEqual(times[0], 3.0)
        self.assertLess(times[0], 4.0)

    def test_relative_outlier_spike_is_replaced(self):
        # ~45 bpm spike while baseline is 75 bpm — passes absolute noise bounds.
        intervals = [800.0] * 20 + [1333.0] + [800.0] * 10
        _times, cleaned, corrections = clean_ibi_series(intervals)
        self.assertGreaterEqual(corrections, 1)
        self.assertEqual(len(cleaned), len(intervals))
        self.assertAlmostEqual(cleaned[20], 800.0, delta=1.0)
        _t, hr = display_hr_from_ibis(intervals)
        self.assertGreater(min(hr), 60.0)
        self.assertLess(max(hr), 90.0)

    def test_mild_contact_dip_under_percent_threshold_is_replaced(self):
        # ~80 → 64 bpm (~25% IBI) slips under DEVIATION_THRESHOLD but exceeds
        # MAX_BEAT_HR_DELTA_BPM — the needle that skewed Low HR on reports.
        intervals = [750.0] * 20 + [937.5] + [750.0] * 10
        _times, cleaned, corrections = clean_ibi_series(intervals)
        self.assertGreaterEqual(corrections, 1)
        self.assertAlmostEqual(cleaned[20], 750.0, delta=1.0)
        hr_values = [60000.0 / ibi for ibi in cleaned]
        self.assertGreater(min(hr_values), 70.0)

    def test_gradual_hr_climb_is_preserved(self):
        # Slow drift (~0.4 bpm/beat) must not be treated as contact spikes.
        intervals = [800.0 - i * 2.0 for i in range(40)]
        _times, cleaned, corrections = clean_ibi_series(intervals)
        self.assertEqual(corrections, 0)
        self.assertEqual(len(cleaned), len(intervals))
        self.assertLess(cleaned[-1], cleaned[0] - 50.0)

    def test_smooth_dampens_a_single_fast_beat(self):
        steady = [800.0] * 30
        bumped = [800.0] * 15 + [650.0] + [800.0] * 14
        _t1, steady_hr = display_hr_from_ibis(steady)
        _t2, bumped_hr = display_hr_from_ibis(bumped)
        raw_spike = 60000.0 / 650.0
        self.assertLess(max(bumped_hr), raw_spike - 5.0)
        self.assertLess(abs(max(bumped_hr) - max(steady_hr)), 15.0)


class DisplayEcgTests(unittest.TestCase):
    def test_slow_drift_is_removed_and_qrs_remains(self):
        rate = 130.0
        n = int(rate * 20)
        t = np.arange(n) / rate
        drift = 0.8 * t
        qrs = np.zeros(n)
        qrs[int(5 * rate)] = 1.2
        shown = np.asarray(display_ecg((drift + qrs).tolist(), rate))
        self.assertLess(float(np.max(shown) - np.min(shown)), 2.0)
        self.assertGreater(float(np.max(shown)), 0.5)
        self.assertLess(abs(float(np.median(shown))), 0.15)


if __name__ == "__main__":
    unittest.main()
