from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from hnh.logger import Logger
from hnh.utils import NamedSignal


class LoggerTests(unittest.TestCase):
    def test_logger_writes_elapsed_for_all_events(self):
        with TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "session.csv"
            logger = Logger()

            with patch("hnh.logger.time.perf_counter", side_effect=[100.0, 100.5, 101.0]):
                logger.start_recording(str(out_path))
                logger.write_to_file(NamedSignal("ibis", ([], [800.0])))
                logger.write_to_file(NamedSignal("hrv", ([], [42.0])))
                logger.save_recording()

            with open(out_path, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["event"], "IBI")
            self.assertEqual(rows[1]["event"], "hrv")
            self.assertNotEqual(rows[0]["elapsed_sec"], "")
            self.assertNotEqual(rows[1]["elapsed_sec"], "")
            self.assertGreater(float(rows[1]["elapsed_sec"]), float(rows[0]["elapsed_sec"]))


if __name__ == "__main__":
    unittest.main()
