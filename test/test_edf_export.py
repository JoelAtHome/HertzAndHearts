from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import unittest

from hnh.edf_export import export_session_edf_plus


@unittest.skipUnless(importlib.util.find_spec("pyedflib"), "pyedflib not installed")
class EdfExportTests(unittest.TestCase):
    def test_export_session_edf_plus_writes_file(self):
        with TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "session.edf"
            start = datetime(2026, 2, 26, 9, 0, 0)
            end = start + timedelta(minutes=2)
            data = {
                "session_id": "mock-001",
                "profile_id": "Demo User",
                "session_type": "General Monitoring",
                "session_start": start,
                "session_end": end,
                "hr_values": [76, 75, 74, 73, 72, 73, 74],
                "rmssd_values": [20.2, 22.1, 25.3, 24.9, 27.2, 26.8],
                "annotations": [("09:00:30", "Deep breathing started")],
            }
            ok, result = export_session_edf_plus(str(out_path), data)
            self.assertTrue(ok, msg=result)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)
            import pyedflib

            reader = pyedflib.EdfReader(str(out_path))
            try:
                labels = reader.getSignalLabels()
                self.assertEqual(labels, ["HR", "RMSSD", "HR_Z", "RMSSD_Z", "ECG_SIM"])
                dims = [reader.getPhysicalDimension(i) for i in range(reader.signals_in_file)]
                self.assertEqual(dims, ["bpm", "ms", "z", "z", "mV"])
                freqs = [reader.getSampleFrequency(i) for i in range(reader.signals_in_file)]
                self.assertEqual(freqs, [1.0, 1.0, 1.0, 1.0, 130.0])
            finally:
                reader._close()


if __name__ == "__main__":
    unittest.main()
