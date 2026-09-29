from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hnh.replay_loader import _load_from_csv


class ReplayLoaderTests(unittest.TestCase):
    def test_elapsed_is_clamped_monotonic_for_replay(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "session.csv"
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["event", "value", "timestamp", "elapsed_sec"])
                w.writerow(["IBI", "1000", "2026-01-01T00:00:00", "1000"])
                w.writerow(["IBI", "1000", "2026-01-01T00:00:01", "900"])
                w.writerow(["hrv", "40.0", "2026-01-01T00:00:01", "950"])
                w.writerow(["IBI", "1000", "2026-01-01T00:00:02", "1500"])

            data = _load_from_csv(csv_path)
            hr_times = data["hr_times"]
            rmssd_times = data["rmssd_times"]

            self.assertEqual(len(hr_times), 3)
            self.assertGreaterEqual(hr_times[1], hr_times[0])
            self.assertGreaterEqual(hr_times[2], hr_times[1])
            self.assertEqual(len(rmssd_times), 1)
            self.assertGreaterEqual(rmssd_times[0], hr_times[1])

    def test_flat_summary_replay_uses_rolling_series(self):
        from hnh.replay_loader import load_session_replay_data

        with TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            csv_path = session_dir / "session.csv"
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["event", "value", "timestamp", "elapsed_sec"])
                elapsed = 0.0
                for ibi in (600, 640, 620, 700, 580, 660):
                    w.writerow(["IBI", f"{ibi:.1f}", "2026-09-28T20:00:00", f"{elapsed:.3f}"])
                    elapsed += ibi
                w.writerow(["hrv", "41.47", "2026-09-28T20:00:00", "0.000"])
                w.writerow(["hrv", "41.47", "2026-09-28T20:00:00", f"{elapsed - 660:.3f}"])
            data = load_session_replay_data(session_dir)
            values = data["rmssd_values"]
            self.assertGreater(len(values), 1)
            self.assertGreater(max(values) - min(values), 1.0)

    def test_ibi_without_elapsed_uses_incremental_fallback(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "session.csv"
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["event", "value", "timestamp", "elapsed_sec"])
                w.writerow(["IBI", "1000", "2026-01-01T00:00:00", ""])
                w.writerow(["IBI", "1000", "2026-01-01T00:00:01", ""])

            data = _load_from_csv(csv_path)
            self.assertEqual(data["hr_times"], [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
