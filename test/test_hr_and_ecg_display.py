from __future__ import annotations

import unittest

import numpy as np

from hnh.ecg_display import display_ecg
from hnh.hr_series import display_hr_from_ibis


class DisplayHrTests(unittest.TestCase):
    def test_artifact_interval_does_not_spike_the_line(self):
        intervals = [800.0] * 20 + [250.0, 2500.0] + [800.0] * 10
        times, hr = display_hr_from_ibis(intervals)
        self.assertGreater(len(hr), 5)
        self.assertLess(max(hr), 100.0)
        self.assertGreater(min(hr), 60.0)
        self.assertGreaterEqual(times[0], 3.0)
        self.assertLess(times[0], 4.0)

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
