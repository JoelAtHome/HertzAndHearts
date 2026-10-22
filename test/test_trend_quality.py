from __future__ import annotations

import unittest

from hnh.hr_series import clean_ibi_series
from hnh.trend_quality import (
    filter_values_excluding_intervals,
    flat_run_intervals,
    gap_intervals,
    point_unreliable_mask,
    split_runs,
    unreliable_intervals_for_series,
)


class TrendQualityTests(unittest.TestCase):
    def test_window_flat_and_gap_detectors(self):
        times = [float(i) * 0.8 for i in range(20)]
        values = [80.0] * 12 + [90.0] * 8
        flats = flat_run_intervals(values, times, range_limit=2.0)
        self.assertTrue(flats)
        self.assertLessEqual(flats[0][0], 1.0)

        gap_times = [0.0, 0.8, 1.6, 6.0, 6.8]
        gaps = gap_intervals(gap_times, gap_seconds=3.0)
        self.assertEqual(gaps, [(1.6, 6.0)])

    def test_stable_resting_hr_not_marked_flat(self):
        # Clean resting HR wobbles ~1–2 bpm; that must stay solid, not dotted.
        times = [float(i) * 0.5 for i in range(40)]
        values = [118.0 + (0.6 if i % 2 else -0.5) for i in range(40)]
        intervals = unreliable_intervals_for_series(
            values, times, disconnect_elapsed=[], metric="hr"
        )
        mask = point_unreliable_mask(times, intervals)
        self.assertFalse(any(mask))

    def test_held_identical_hr_shelf_still_marked(self):
        times = [float(i) * 0.75 for i in range(24)]
        values = [80.0] * 24
        intervals = unreliable_intervals_for_series(
            values, times, disconnect_elapsed=[], metric="hr"
        )
        mask = point_unreliable_mask(times, intervals)
        self.assertTrue(all(mask))

    def test_rmssd_near_zero_plateau_marked(self):
        times = [float(i) for i in range(15)]
        values = [12.0] * 3 + [0.0] * 9 + [11.0] * 3
        intervals = unreliable_intervals_for_series(
            values, times, disconnect_elapsed=[], metric="rmssd"
        )
        mask = point_unreliable_mask(times, intervals)
        self.assertTrue(any(mask[3:12]))
        kept = filter_values_excluding_intervals(values, times, intervals)
        self.assertGreater(min(kept), 0.5)

    def test_split_runs_breaks_across_time_gaps(self):
        times = [0.0, 0.8, 1.6, 10.0, 10.8]
        values = [80.0, 81.0, 80.5, 82.0, 81.5]
        mask = [False] * 5
        runs = split_runs(values, times, mask, gap_seconds=3.0)
        self.assertEqual(len(runs), 2)
        self.assertEqual(len(runs[0][1]), 3)
        self.assertEqual(len(runs[1][1]), 2)

    def test_plot_gap_threshold_uses_minute_axis_units(self):
        # A ~2.8 minute hole must not be bridged when x is in minutes.
        times_min = [8.95, 8.956, 11.76, 12.43]
        values = [102.7, 102.7, 100.0, 101.9]
        mask = [True, True, True, True]
        runs = split_runs(values, times_min, mask, gap_seconds=3.0 / 60.0)
        self.assertGreaterEqual(len(runs), 2)
        self.assertTrue(all((xs[-1] - xs[0]) < 1.0 for _bad, xs, _ys in runs))

    def test_drop_mode_omits_relative_outliers(self):
        intervals = [750.0] * 20 + [937.5] + [750.0] * 10
        _t, cleaned, corrections = clean_ibi_series(intervals, outlier_mode="drop")
        self.assertGreaterEqual(corrections, 1)
        self.assertEqual(len(cleaned), len(intervals) - 1)
        self.assertTrue(all(abs(v - 750.0) < 1.0 for v in cleaned))


if __name__ == "__main__":
    unittest.main()
