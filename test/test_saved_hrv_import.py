from __future__ import annotations

import base64
import json
import struct
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hnh.import_session import (
    decode_ritual_ecg_chunks,
    import_saved_hrv_package,
    replay_data_from_ibi_ms,
)
from hnh.profile_store import ProfileStore
from hnh.report import naive_local_from_iso


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

            manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
            expected_start = naive_local_from_iso("2026-09-15T12:03:00Z")
            self.assertIsNotNone(expected_start)
            assert expected_start is not None
            self.assertEqual(manifest["timing"]["started_at"], expected_start.isoformat())
            self.assertEqual(
                manifest["timing"]["ended_at"],
                (expected_start + timedelta(seconds=120)).isoformat(),
            )
            self.assertEqual(manifest["timing"]["emitted_at"], "2026-09-15T12:03:00Z")
            stored = datetime.fromisoformat(manifest["timing"]["started_at"])
            local_tz = datetime.now().astimezone().tzinfo
            as_utc = stored.replace(tzinfo=local_tz).astimezone(timezone.utc)
            self.assertEqual(as_utc, datetime(2026, 9, 15, 12, 3, tzinfo=timezone.utc))
            matched = next(s for s in sessions if s.get("session_id") == bundle.session_id)
            self.assertEqual(matched.get("started_at"), expected_start.isoformat())

    def test_import_keeps_phone_patient_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            package = {
                "session_id": "20260915T140000Z-pat",
                "mode": "record",
                "kind": "ritual",
                "transfer_reason": "manual_send",
                "source_device": "FEATHER",
                "emitted_at": "2026-09-15T14:00:00Z",
                "duration_s": 60.0,
                "rmssd_ms": 33.0,
                "profile_id": "patient-2",
                "profile_display_name": "Joel",
                "ibi_ms": [800, 810, 790],
                "ecg_chunks": [],
            }
            bundle = import_saved_hrv_package(package, root, "Admin", store)
            self.assertIsNotNone(bundle)
            assert bundle is not None
            manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
            stored = manifest["artifacts"]["phone_bridge_package"]
            self.assertEqual(stored["profile_display_name"], "Joel")
            self.assertEqual(stored["profile_id"], "patient-2")
            csv_text = bundle.csv_path.read_text(encoding="utf-8")
            self.assertIn("Joel", csv_text)

    def test_repair_shifts_stored_zulu_wall_clock_to_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            session_dir = root / "sessions" / "old-import"
            session_dir.mkdir(parents=True)
            zulu_start = "2026-09-15T12:03:00"
            zulu_end = "2026-09-15T12:05:00"
            manifest = {
                "timing": {
                    "started_at": zulu_start,
                    "first_data_at": zulu_start,
                    "ended_at": zulu_end,
                    "emitted_at": "2026-09-15T12:03:00Z",
                }
            }
            (session_dir / "session_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with store._db() as conn:
                conn.execute(
                    """
                    INSERT INTO session_history (
                        session_id, profile_name, started_at, ended_at, state, session_dir, csv_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "old-import",
                        "Admin",
                        zulu_start,
                        zulu_end,
                        "imported",
                        str(session_dir),
                        str(session_dir / "session.csv"),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO session_trends (session_id, profile_name, ended_at)
                    VALUES (?, ?, ?)
                    """,
                    ("old-import", "Admin", zulu_end),
                )
            store._set_app_state(store._PHONE_BRIDGE_ZULU_LOCAL_KEY, "")
            fixed = store._repair_phone_bridge_zulu_clocks()
            expected_start = naive_local_from_iso("2026-09-15T12:03:00Z")
            assert expected_start is not None
            expected_end = expected_start + timedelta(seconds=120)
            if expected_start.isoformat() == zulu_start:
                self.assertEqual(fixed, 0)
            else:
                self.assertEqual(fixed, 1)
            sessions = store.list_sessions(profile_name="Admin", include_hidden=True, limit=10)
            row = next(s for s in sessions if s.get("session_id") == "old-import")
            self.assertEqual(row.get("started_at"), expected_start.isoformat())
            self.assertEqual(row.get("ended_at"), expected_end.isoformat())
            repaired = json.loads((session_dir / "session_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(repaired["timing"]["started_at"], expected_start.isoformat())
            self.assertEqual(repaired["timing"]["emitted_at"], "2026-09-15T12:03:00Z")
            with store._db() as conn:
                trend = conn.execute(
                    "SELECT ended_at FROM session_trends WHERE session_id = ?",
                    ("old-import",),
                ).fetchone()
            self.assertEqual(str(trend["ended_at"]), expected_end.isoformat())
            store._set_app_state(store._PHONE_BRIDGE_ZULU_LOCAL_KEY, "")
            self.assertEqual(store._repair_phone_bridge_zulu_clocks(), 0)
            sessions_again = store.list_sessions(profile_name="Admin", include_hidden=True, limit=10)
            row_again = next(s for s in sessions_again if s.get("session_id") == "old-import")
            self.assertEqual(row_again.get("started_at"), expected_start.isoformat())

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
