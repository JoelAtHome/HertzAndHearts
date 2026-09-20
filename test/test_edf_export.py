from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import unittest

import numpy as np

from hnh.edf_export import export_session_edf_plus
from hnh.ecg_stream import EcgSampleStream


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

    def test_export_preserves_ecg_waveform_without_stretch(self):
        with TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "session.edf"
            stream_path = Path(tmp) / "session_ecg.f32"
            rate = 130
            seconds = 5
            src = np.zeros(rate * seconds, dtype=float)
            for i in range(0, src.size, rate):
                src[i] = 1.0
            with EcgSampleStream.open_write(stream_path) as stream:
                stream.append(src.tolist())

            start = datetime(2026, 3, 1, 10, 0, 0)
            end = start + timedelta(seconds=seconds)
            ok, result = export_session_edf_plus(
                str(out_path),
                {
                    "session_id": "ecg-preserve",
                    "profile_id": "Admin",
                    "session_start": start,
                    "session_end": end,
                    "hr_values": [70.0, 71.0],
                    "rmssd_values": [30.0, 31.0],
                    "ecg_stream_path": str(stream_path),
                    "ecg_sample_rate_hz": rate,
                    "ecg_is_simulated": False,
                },
            )
            self.assertTrue(ok, msg=result)
            import pyedflib

            reader = pyedflib.EdfReader(str(out_path))
            try:
                labels = reader.getSignalLabels()
                self.assertIn("ECG", labels)
                self.assertNotIn("ECG_SIM", labels)
                ecg_idx = labels.index("ECG")
                recovered = np.asarray(reader.readSignal(ecg_idx), dtype=float)
            finally:
                reader._close()

            self.assertEqual(recovered.size, src.size)
            peak_idxs = list(range(0, src.size, rate))
            for idx in peak_idxs:
                self.assertGreater(recovered[idx], 0.85)
                if idx + 1 < recovered.size:
                    self.assertLess(abs(recovered[idx + 1]), 0.15)


if __name__ == "__main__":
    unittest.main()
