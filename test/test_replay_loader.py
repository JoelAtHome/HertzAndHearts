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
