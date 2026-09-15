from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hnh.import_session import import_saved_hrv_package, replay_data_from_ibi_ms
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


if __name__ == "__main__":
    unittest.main()
