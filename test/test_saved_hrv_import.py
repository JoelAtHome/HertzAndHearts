from __future__ import annotations

import base64
import struct
import tempfile
import unittest
from pathlib import Path

from hnh.import_session import (
    decode_ritual_ecg_chunks,
    import_saved_hrv_package,
    replay_data_from_ibi_ms,
)
from hnh.profile_store import ProfileStore


class SavedHrvImportTests(unittest.TestCase):
    def test_replay_data_prefers_bridge_rmssd(self):
        data = replay_data_from_ibi_ms(
            [800, 820, 810],
            bridge_rmssd_ms=42.5,
            annotation="[Phone Bridge] Saved HRV",
        )
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(len(data["hr_times"]), 3)
        self.assertEqual(data["rmssd_values"], [42.5])
        self.assertEqual(data["annotations"][0][1], "[Phone Bridge] Saved HRV")

    def test_decode_ritual_ecg_chunks_to_mv(self):
        # 1000 µV and -500 µV → 1.0 mV and -0.5 mV
        raw = struct.pack("<hh", 1000, -500)
        chunk = {
            "encoding": "int16_uv_b64",
            "sample_rate_hz": 250,
            "scale_uv_per_lsb": 1.0,
            "data": base64.b64encode(raw).decode("ascii"),
        }
        samples, rate = decode_ritual_ecg_chunks([chunk])
        self.assertEqual(rate, 250)
        self.assertEqual(samples, [1.0, -0.5])

    def test_import_writes_history_and_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            package = {
                "session_id": "20260915T120000Z-a1b2",
                "mode": "record",
                "kind": "ritual",
                "transfer_reason": "delayed_push",
                "source_device": "POLAR_H10",
                "emitted_at": "2026-09-15T12:03:00Z",
                "duration_s": 120.0,
                "rmssd_ms": 51.0,
                "ibi_ms": [800, 812, 790, 805],
                "ecg_chunks": [],
            }
            bundle = import_saved_hrv_package(package, root, "Admin", store)
            self.assertIsNotNone(bundle)
            assert bundle is not None
            self.assertTrue(bundle.csv_path.is_file())
            self.assertTrue(bundle.manifest_path.is_file())
            sessions = store.list_sessions(profile_name="Admin", include_hidden=True, limit=10)
            self.assertTrue(any(s.get("session_id") == bundle.session_id for s in sessions))
            self.assertEqual(
                store.get_phone_bridge_imported_session_id("Admin", "20260915T120000Z-a1b2"),
                bundle.session_id,
            )

            again = import_saved_hrv_package(package, root, "Admin", store)
            self.assertIsNone(again)
            sessions2 = store.list_sessions(profile_name="Admin", include_hidden=True, limit=10)
            self.assertEqual(len(sessions2), len(sessions))

    def test_import_with_ecg_writes_edf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            # ~1 second of ECG at 130 Hz
            samples = [int(100 * ((i % 20) - 10)) for i in range(130)]
            raw = struct.pack("<" + "h" * len(samples), *samples)
            package = {
                "session_id": "20260915T130000Z-ecg1",
                "mode": "record",
                "kind": "ritual",
                "transfer_reason": "manual_send",
                "source_device": "FEATHER",
                "emitted_at": "2026-09-15T13:00:00Z",
                "duration_s": 1.0,
                "rmssd_ms": 40.0,
                "ibi_ms": [800, 810],
                "ecg_chunks": [
                    {
                        "seq": 1,
                        "of": 1,
                        "encoding": "int16_uv_b64",
                        "sample_rate_hz": 130,
                        "scale_uv_per_lsb": 1.0,
                        "data": base64.b64encode(raw).decode("ascii"),
                    }
                ],
            }
            bundle = import_saved_hrv_package(package, root, "Admin", store)
            self.assertIsNotNone(bundle)
            assert bundle is not None
            self.assertTrue(bundle.edf_path.is_file())
            from hnh.replay_loader import load_session_replay_data

            replay = load_session_replay_data(bundle.session_dir)
            self.assertTrue(replay.get("ecg_samples"))
            self.assertGreaterEqual(len(replay["ecg_samples"]), 50)


if __name__ == "__main__":
    unittest.main()
