from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hnh.profile_store import ProfileStore
from hnh.session_artifacts import SessionBundle


def _bundle(root: Path, session_id: str) -> SessionBundle:
    session_dir = root / "Sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return SessionBundle(
        session_id=session_id,
        profile_id="Admin",
        session_dir=session_dir,
        csv_path=session_dir / "session.csv",
        report_final_path=session_dir / "session_report.docx",
        report_draft_path=session_dir / "session_report_draft.docx",
        manifest_path=session_dir / "session_manifest.json",
        edf_path=session_dir / "session.edf",
        started_at=datetime.now(),
    )


class ProfileStoreTests(unittest.TestCase):
    def test_archive_excludes_from_default_list(self):
        with TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp))
            store.ensure_profile("A")
            store.ensure_profile("B")
            store.set_last_active_profile("A")

            store.archive_profile("B")

            self.assertEqual(store.list_profiles(), ["A"])
            self.assertEqual(sorted(store.list_profiles(include_archived=True)), ["A", "B"])

    def test_cannot_archive_active_profile(self):
        with TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp))
            store.ensure_profile("A")
            store.ensure_profile("B")
            store.set_last_active_profile("A")

            with self.assertRaises(ValueError):
                store.archive_profile("A")

    def test_rename_cascades_related_records(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Alice")
            store.ensure_profile("Other")
            store.set_last_active_profile("Alice")
            store.set_profile_pref("Alice", "hide_disclaimer", "1")
            store.record_session_started("Alice", _bundle(root, "s1"))

            renamed = store.rename_profile("Alice", "Alice Renamed")

            self.assertEqual(renamed, "Alice Renamed")
            self.assertEqual(store.get_last_active_profile(), "Alice Renamed")
            self.assertEqual(
                store.get_profile_pref("Alice Renamed", "hide_disclaimer", default="0"), "1"
            )
            self.assertIn("Alice Renamed", store.list_profiles())
            self.assertNotIn("Alice", store.list_profiles(include_archived=True))

    def test_cannot_delete_last_active_remaining_profile(self):
        with TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp))
            store.ensure_profile("Only")
            store.set_last_active_profile("Only")

            with self.assertRaises(ValueError):
                store.delete_profile("Only")

    def test_legacy_migration_imports_manifest_into_history(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "Sessions" / "2025" / "2025-02-24" / "20250224-101010"
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "session_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "session_id": "20250224-101010",
                        "state": "finalized",
                        "timing": {
                            "started_at": "2025-02-24T10:10:10",
                            "ended_at": "2025-02-24T10:30:00",
                        },
                        "artifacts": {"csv": {"path": "session.csv"}},
                    }
                ),
                encoding="utf-8",
            )

            store = ProfileStore(root)

            self.assertIn("Legacy User", store.list_profiles(include_archived=True))
            with store._db() as conn:
                row = conn.execute(
                    "SELECT profile_name, state FROM session_history WHERE session_id = ?",
                    ("20250224-101010",),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(str(row["profile_name"]), "Legacy User")
            self.assertEqual(str(row["state"]), "finalized")

    def test_legacy_migration_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "Sessions" / "Admin" / "2026" / "2026-02-24" / "20260224-111111"
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "session_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "session_id": "20260224-111111",
                        "profile_id": "Admin",
                        "state": "finalized",
                        "timing": {"started_at": "2026-02-24T11:11:11"},
                        "artifacts": {"csv": {"path": str(session_dir / "session.csv")}},
                    }
                ),
                encoding="utf-8",
            )

            store = ProfileStore(root)
            with store._db() as conn:
                first_count = int(
                    conn.execute("SELECT COUNT(*) AS total FROM session_history").fetchone()["total"]
                )
            migrated_again = store.migrate_legacy_sessions()
            with store._db() as conn:
                second_count = int(
                    conn.execute("SELECT COUNT(*) AS total FROM session_history").fetchone()["total"]
                )

            self.assertEqual(first_count, 1)
            self.assertEqual(migrated_again, 0)
            self.assertEqual(second_count, 1)

    def test_list_sessions_filters_and_orders_by_started_at_desc(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Alice")
            store.ensure_profile("Bob")

            b1 = _bundle(root, "s1")
            b1.started_at = datetime.fromisoformat("2026-01-01T10:00:00")
            store.record_session_started("Alice", b1)
            store.record_session_finished("s1", "finalized")

            b2 = _bundle(root, "s2")
            b2.started_at = datetime.fromisoformat("2026-01-02T10:00:00")
            store.record_session_started("Alice", b2)
            store.record_session_finished("s2", "abandoned")

            b3 = _bundle(root, "s3")
            b3.started_at = datetime.fromisoformat("2026-01-03T10:00:00")
            store.record_session_started("Bob", b3)
            store.record_session_finished("s3", "finalized")

            alice_sessions = store.list_sessions("Alice")
            self.assertEqual([s["session_id"] for s in alice_sessions], ["s2", "s1"])

            finalized = store.list_sessions(state="finalized")
            self.assertEqual([s["session_id"] for s in finalized], ["s3", "s1"])

    def test_list_sessions_limit_and_count(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("A")
            for idx in range(5):
                sid = f"s{idx}"
                b = _bundle(root, sid)
                b.started_at = datetime.fromisoformat(f"2026-02-0{idx+1}T08:00:00")
                store.record_session_started("A", b)
                store.record_session_finished(sid, "finalized")

            limited = store.list_sessions("A", limit=2)
            self.assertEqual(len(limited), 2)
            self.assertEqual(store.count_sessions("A"), 5)

    def test_list_profiles_info_reports_archived_flag(self):
        with TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp))
            store.ensure_profile("A")
            store.ensure_profile("B")
            store.set_last_active_profile("A")
            store.archive_profile("B")

            active_only = store.list_profiles_info(include_archived=False)
            all_profiles = store.list_profiles_info(include_archived=True)

            self.assertEqual([p["name"] for p in active_only], ["A"])
            by_name = {str(p["name"]): p for p in all_profiles}
            self.assertIn("B", by_name)
            self.assertEqual(by_name["B"]["archived"], True)

    def test_profile_details_roundtrip(self):
        with TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp))
            store.ensure_profile("Pat")

            store.update_profile_details(
                "Pat",
                dob="1982-03-15",
                gender="Non-binary",
                notes="Follow-up in two weeks",
            )
            details = store.get_profile_details("Pat")
            self.assertEqual(details["dob"], "1982-03-15")
            self.assertIsNotNone(details["age"])
            self.assertGreaterEqual(details["age"], 40)
            self.assertLessEqual(details["age"], 50)
            self.assertEqual(details["gender"], "Non-binary")
            self.assertEqual(details["notes"], "Follow-up in two weeks")

            info = {str(row["name"]): row for row in store.list_profiles_info(include_archived=True)}
            self.assertEqual(info["Pat"]["gender"], "Non-binary")

    def test_purge_abandoned_sessions_deletes_rows_and_dirs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")
            store.ensure_profile("Other")

            b1 = _bundle(root, "a1")
            b2 = _bundle(root, "a2")
            b3 = _bundle(root, "f1")
            store.record_session_started("Admin", b1)
            store.record_session_started("Other", b2)
            store.record_session_started("Admin", b3)
            store.record_session_finished("a1", "abandoned")
            store.record_session_finished("a2", "abandoned")
            store.record_session_finished("f1", "finalized")
            store.record_session_trend("Admin", "a1", datetime.now(), avg_hr=70.0)
            store.record_session_trend("Other", "a2", datetime.now(), avg_hr=72.0)

            res_admin = store.purge_abandoned_sessions("Admin")
            self.assertEqual(res_admin["removed_rows"], 1)
            self.assertFalse(b1.session_dir.exists())
            self.assertTrue(b2.session_dir.exists())
            self.assertTrue(b3.session_dir.exists())

            res_all = store.purge_abandoned_sessions()
            self.assertEqual(res_all["removed_rows"], 1)
            self.assertFalse(b2.session_dir.exists())
            self.assertTrue(b3.session_dir.exists())
            self.assertEqual(len(store.list_sessions(state="abandoned", include_hidden=True)), 0)

    def test_purge_recording_sessions_deletes_rows_and_dirs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")
            store.ensure_profile("Other")

            b1 = _bundle(root, "r1")
            b2 = _bundle(root, "r2")
            b3 = _bundle(root, "f1")
            store.record_session_started("Admin", b1)  # remains recording
            store.record_session_started("Other", b2)  # remains recording
            store.record_session_started("Admin", b3)
            store.record_session_finished("f1", "finalized")
            store.record_session_trend("Admin", "r1", datetime.now(), avg_hr=70.0)
            store.record_session_trend("Other", "r2", datetime.now(), avg_hr=72.0)

            res_admin = store.purge_recording_sessions("Admin")
            self.assertEqual(res_admin["removed_rows"], 1)
            self.assertFalse(b1.session_dir.exists())
            self.assertTrue(b2.session_dir.exists())
            self.assertTrue(b3.session_dir.exists())

            res_all = store.purge_recording_sessions()
            self.assertEqual(res_all["removed_rows"], 1)
            self.assertFalse(b2.session_dir.exists())
            self.assertTrue(b3.session_dir.exists())
            self.assertEqual(len(store.list_sessions(state="recording", include_hidden=True)), 0)


if __name__ == "__main__":
    unittest.main()
