from __future__ import annotations

import unittest

from hnh.report import (
    _filter_rmssd_outliers,
    _report_metric_settling_seconds,
    _truncate_trend_after_settling,
)


class ReportRmssdFilterTests(unittest.TestCase):
    def test_filter_rmssd_outliers_removes_hard_and_statistical_spikes(self):
        values = [8.0, 9.1, 7.8, 8.4, 9.0, 8.7, 7.9, 8.3, 161.2, 240.0]
        filtered = _filter_rmssd_outliers(values)
        self.assertNotIn(240.0, filtered)
        self.assertNotIn(161.2, filtered)
        self.assertGreaterEqual(len(filtered), 8)

    def test_filter_rmssd_outliers_keeps_short_series(self):
        values = [30.0, 42.5, 55.0]
        filtered = _filter_rmssd_outliers(values)
        self.assertEqual(filtered, values)

    def test_report_metric_settling_seconds_extends_rmssd_hrv(self):
        self.assertEqual(_report_metric_settling_seconds("hr", 15.0), 15.0)
        self.assertEqual(_report_metric_settling_seconds("stress", 15.0), 15.0)
        self.assertEqual(_report_metric_settling_seconds("rmssd", 15.0), 60.0)
        self.assertEqual(_report_metric_settling_seconds("hrv", 15.0), 60.0)

    def test_short_session_falls_back_from_rmssd_stabilize_window(self):
        times = [float(i) for i in range(0, 25)]
        values = [8.0 + (i * 0.01) for i in times]
        # 60s cut would leave nothing usable; fall back to 15s settling.
        out_v, out_t = _truncate_trend_after_settling(
            values, times, 60.0, fallback_sec=15.0
        )
        self.assertGreaterEqual(len(out_v), 2)
        self.assertEqual(out_t[0], 15.0)
        self.assertEqual(out_t[-1], 24.0)


if __name__ == "__main__":
    unittest.main()
