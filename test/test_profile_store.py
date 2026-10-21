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
        ecg_stream_path=session_dir / "session_ecg.f32",
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

    def test_delete_sessions_and_folders(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")

            keep = _bundle(root, "keep1")
            drop = _bundle(root, "drop1")
            store.record_session_started("Admin", keep)
            store.record_session_started("Admin", drop)
            store.record_session_finished("keep1", "finalized")
            store.record_session_finished("drop1", "finalized")
            store.record_session_trend("Admin", "drop1", datetime.now(), avg_hr=71.0)

            result = store.delete_sessions_and_folders(["drop1", "missing-id"])
            self.assertEqual(result["removed_rows"], 1)
            self.assertEqual(result["deleted_dirs"], 1)
            self.assertFalse(drop.session_dir.exists())
            self.assertTrue(keep.session_dir.exists())
            ids = {str(s.get("session_id")) for s in store.list_sessions(include_hidden=True)}
            self.assertIn("keep1", ids)
            self.assertNotIn("drop1", ids)

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

    def test_fill_missing_session_trends_from_manifests(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Sandy")
            b = _bundle(root, "20260205-120000")
            ended = "2026-02-05T12:30:00"
            (b.session_dir / "session_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "session_id": "20260205-120000",
                        "state": "finalized",
                        "metrics": {
                            "last_hr": 72.0,
                            "last_rmssd": 45.5,
                            "baseline_hr": 70.0,
                            "baseline_rmssd": 50.0,
                            "qtc": {"session_value_ms": 420.0},
                        },
                        "artifacts": {"csv": {"path": "session.csv"}},
                    }
                ),
                encoding="utf-8",
            )
            with store._db() as conn:
                conn.execute(
                    """
                    INSERT INTO session_history (
                        session_id, profile_name, started_at, ended_at, state, session_dir, csv_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "20260205-120000",
                        "Sandy",
                        "2026-02-05T12:00:00",
                        ended,
                        "finalized",
                        str(b.session_dir),
                        str(b.csv_path),
                    ),
                )

            self.assertEqual(len(store.list_session_trends("Sandy", span="year")), 0)
            n = store.fill_missing_session_trends_from_manifests()
            self.assertEqual(n, 1)
            rows = store.list_session_trends("Sandy", span="year")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session_id"], "20260205-120000")
            self.assertEqual(rows[0]["avg_hr"], 72.0)
            self.assertEqual(rows[0]["avg_rmssd"], 45.5)
            self.assertEqual(rows[0]["qtc_ms"], 420.0)

            self.assertEqual(store.fill_missing_session_trends_from_manifests(), 0)

    def _write_copied_session(
        self,
        session_dir: Path,
        *,
        session_id: str,
        profile_id: str,
        stale_csv: Path,
    ) -> None:
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.csv").write_text("t,hr\n", encoding="utf-8")
        (session_dir / "session_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "session_id": session_id,
                    "profile_id": profile_id,
                    "state": "finalized",
                    "timing": {
                        "started_at": "2026-04-05T21:06:27",
                        "ended_at": "2026-04-05T21:10:00",
                    },
                    "metrics": {"last_hr": 71.0, "last_rmssd": 28.0},
                    "artifacts": {"csv": {"path": str(stale_csv), "exists": True}},
                }
            ),
            encoding="utf-8",
        )

    def test_save_path_audit_adopts_renamed_profile_and_local_csv(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Sandy Koblich")
            store.ensure_profile("Joel Koblich")
            save_path = root / "Sessions" / "Sandy Koblich"
            stale_csv = Path(r"C:\missing\Sessions\Sandy\2026\2026-04-05\sess\session.csv")
            copied = save_path / "2026" / "2026-04-05" / "20260405-210627"
            kept = save_path / "2026" / "2026-04-06" / "20260406-223113"
            self._write_copied_session(
                copied,
                session_id="20260405-210627",
                profile_id="Sandy",
                stale_csv=stale_csv,
            )
            self._write_copied_session(
                kept,
                session_id="20260406-223113",
                profile_id="Joel Koblich",
                stale_csv=stale_csv,
            )

            audit = store.audit_session_history_integrity(
                scan_roots=[save_path],
                owned_roots=[(save_path, "Sandy Koblich")],
            )
            by_id = {row["session_id"]: row for row in audit["missing_in_db"]}
            adopted = by_id["20260405-210627"]
            self.assertEqual(adopted["profile_name"], "Sandy Koblich")
            self.assertEqual(Path(adopted["csv_path"]), copied / "session.csv")
            self.assertEqual(by_id["20260406-223113"]["profile_name"], "Joel Koblich")

            store.repair_session_history_integrity(audit=audit, fill_missing_session_trends=False)
            sandy = store.list_sessions("Sandy Koblich", include_hidden=True)
            joel = store.list_sessions("Joel Koblich", include_hidden=True)
            self.assertEqual([row["session_id"] for row in sandy], ["20260405-210627"])
            self.assertEqual([row["session_id"] for row in joel], ["20260406-223113"])
            self.assertNotIn("Sandy", store.list_profiles(include_archived=True))

    def test_index_save_path_adds_session_once(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Sandy Koblich")
            save_path = root / "Sessions" / "Sandy Koblich"
            session_dir = save_path / "2026" / "2026-04-16" / "20260416-182402"
            self._write_copied_session(
                session_dir,
                session_id="20260416-182402",
                profile_id="Sandy",
                stale_csv=root / "gone" / "session.csv",
            )
            store.set_profile_pref(
                "Sandy Koblich",
                "setting:SESSION_SAVE_PATH",
                str(save_path),
            )

            added = store.index_profile_save_path_sessions("Sandy Koblich")
            self.assertEqual(added, 1)
            rows = store.list_sessions("Sandy Koblich", include_hidden=True)
            self.assertEqual(rows[0]["session_id"], "20260416-182402")
            self.assertEqual(Path(rows[0]["csv_path"]), session_dir / "session.csv")
            self.assertEqual(store.index_profile_save_path_sessions("Sandy Koblich"), 0)
            trends = store.list_session_trends("Sandy Koblich", span="year")
            self.assertEqual([row["session_id"] for row in trends], ["20260416-182402"])

    def test_merge_profiles_keeps_master_and_moves_sessions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Sandy")
            store.ensure_profile("Sandy Koblich")
            store.set_last_active_profile("Sandy")
            store.set_profile_pref("Sandy", "hide_disclaimer", "1")
            store.set_profile_pref("Sandy", "setting:SESSION_SAVE_PATH", str(root / "Sessions" / "Sandy"))
            store.set_profile_pref("Sandy Koblich", "connection_mode", "phone")
            store.update_profile_details("Sandy", dob="1980-01-15", notes="from sandy")
            store.update_profile_details("Sandy Koblich", gender="F")

            sandy_dir = root / "Sessions" / "Sandy" / "2026" / "2026-04-05" / "20260405-210627"
            sandy_dir.mkdir(parents=True, exist_ok=True)
            (sandy_dir / "session.csv").write_text("t,hr\n", encoding="utf-8")
            b = _bundle(root, "20260405-210627")
            b.session_dir = sandy_dir
            b.csv_path = sandy_dir / "session.csv"
            b.started_at = datetime.fromisoformat("2026-04-05T21:06:27")
            store.record_session_started("Sandy", b)
            store.record_session_finished("20260405-210627", "finalized")
            store.record_session_trend(
                "Sandy",
                "20260405-210627",
                "2026-04-05T21:10:00",
                avg_hr=71.0,
                avg_rmssd=28.0,
            )
            store.remember_phone_bridge_import("Sandy", "phone-1", "20260405-210627")

            master_dir = (
                root / "Sessions" / "Sandy Koblich" / "2026" / "2026-04-05" / "20260405-210627"
            )
            master_dir.parent.mkdir(parents=True, exist_ok=True)
            sandy_dir.rename(master_dir)
            result = store.merge_profiles(
                "Sandy",
                "Sandy Koblich",
                session_updates=[
                    {
                        "session_id": "20260405-210627",
                        "session_dir": str(master_dir),
                        "csv_path": str(master_dir / "session.csv"),
                    }
                ],
            )

            self.assertEqual(result["reassigned_with_path"], 1)
            self.assertNotIn("Sandy", store.list_profiles(include_archived=True))
            self.assertIn("Sandy Koblich", store.list_profiles())
            self.assertEqual(store.get_last_active_profile(), "Sandy Koblich")
            rows = store.list_sessions("Sandy Koblich", include_hidden=True)
            self.assertEqual([row["session_id"] for row in rows], ["20260405-210627"])
            self.assertEqual(Path(rows[0]["session_dir"]), master_dir)
            trends = store.list_session_trends("Sandy Koblich", span="year")
            self.assertEqual([row["session_id"] for row in trends], ["20260405-210627"])
            self.assertEqual(store.get_profile_pref("Sandy Koblich", "hide_disclaimer"), "1")
            self.assertEqual(store.get_profile_pref("Sandy Koblich", "connection_mode"), "phone")
            self.assertEqual(
                store.get_profile_pref("Sandy Koblich", "setting:SESSION_SAVE_PATH", ""),
                "",
            )
            details = store.get_profile_details("Sandy Koblich")
            self.assertEqual(details["dob"], "1980-01-15")
            self.assertEqual(details["gender"], "F")
            self.assertEqual(details["notes"], "from sandy")
            self.assertEqual(
                store.get_phone_bridge_imported_session_id("Sandy Koblich", "phone-1"),
                "20260405-210627",
            )

    def test_merge_profiles_rejects_same_name(self):
        with TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp))
            store.ensure_profile("Sandy Koblich")
            with self.assertRaises(ValueError):
                store.merge_profiles("Sandy Koblich", "Sandy Koblich")

    def test_index_adopts_orphan_edf_folder_without_manifest(self):
        from hnh.import_session import write_session_csv

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Sandy Koblich")
            save_path = root / "Sessions" / "Sandy Koblich"
            session_dir = save_path / "2026" / "2023-02-27" / "20260227-094043"
            session_dir.mkdir(parents=True)
            # Orphan folder: CSV only, no manifest (same discovery path as EDF-only).
            write_session_csv(
                session_dir / "session.csv",
                {
                    "started_at": "2026-02-27T09:40:43",
                    "hr_times": [0.0, 1.0, 2.0],
                    "hr_values": [70.0, 72.0, 71.0],
                    "rmssd_times": [1.0, 2.0],
                    "rmssd_values": [25.0, 27.0],
                    "hrv_times": [],
                    "hrv_values": [],
                    "annotations": [],
                },
            )
            (session_dir / "session_report.docx").write_bytes(b"PK\x03\x04fake")
            store.set_profile_pref(
                "Sandy Koblich",
                "setting:SESSION_SAVE_PATH",
                str(save_path),
            )

            added = store.index_profile_save_path_sessions("Sandy Koblich")
            self.assertGreaterEqual(added, 1)
            self.assertTrue((session_dir / "session_manifest.json").is_file())
            rows = store.list_sessions("Sandy Koblich", include_hidden=True)
            self.assertEqual(rows[0]["session_id"], "20260227-094043")
            self.assertEqual(rows[0]["profile_name"], "Sandy Koblich")
            self.assertEqual(rows[0]["state"], "finalized")
            self.assertEqual(store.index_profile_save_path_sessions("Sandy Koblich"), 0)


if __name__ == "__main__":
    unittest.main()
