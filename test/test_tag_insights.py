from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hnh.profile_store import ProfileStore
from hnh.session_artifacts import SessionBundle
from hnh.tag_insights import summarize_tag_correlations


def _bundle(root: Path, session_id: str, started_at: datetime) -> SessionBundle:
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
        started_at=started_at,
    )


def _write_session_csv(
    csv_path: Path,
    *,
    annotation_text: str,
    annotation_at_sec: int = 60,
    total_seconds: int = 140,
    pre_hr_bpm: float = 60.0,
    post_hr_bpm: float = 75.0,
    include_phase2_metrics: bool = False,
) -> None:
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["event", "value", "timestamp", "elapsed_sec"])
        ts = datetime.now().isoformat()
        for sec in range(total_seconds + 1):
            hr = pre_hr_bpm if sec < annotation_at_sec else post_hr_bpm
            ibi_ms = 60000.0 / hr
            elapsed_ms = float(sec * 1000)
            writer.writerow(["IBI", f"{ibi_ms:.3f}", ts, f"{elapsed_ms:.3f}"])
            if include_phase2_metrics:
                sdnn = 28.0 if sec < annotation_at_sec else 38.0
                lfhf = 1.05 if sec < annotation_at_sec else 1.55
                writer.writerow(["SDNN", f"{sdnn:.3f}", ts, ""])
                writer.writerow(["stress_ratio", f"{lfhf:.3f}", ts, ""])
            if sec == annotation_at_sec:
                # Intentionally leave elapsed blank (matches live logger behavior).
                writer.writerow(["Annotation", annotation_text, ts, ""])


class TagInsightsTests(unittest.TestCase):
    def test_moderate_confidence_for_consistent_multi_session_shift(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")

            for i in range(6):
                started = datetime.fromisoformat(f"2026-03-{i + 1:02d}T09:00:00")
                bundle = _bundle(root, f"s{i + 1}", started_at=started)
                store.record_session_started("Admin", bundle)
                store.record_session_finished(bundle.session_id, "finalized")
                _write_session_csv(bundle.csv_path, annotation_text="Caffeine intake")

            rows = summarize_tag_correlations(store, "Admin", session_limit=50)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["annotation"], "Caffeine intake")
            self.assertEqual(row["events"], 6)
            self.assertEqual(row["sessions"], 6)
            self.assertEqual(row["confidence"], "Moderate")
            self.assertGreater(float(row["delta_hr_bpm"]), 10.0)

    def test_system_annotations_are_excluded(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")

            bundle = _bundle(root, "s1", started_at=datetime.fromisoformat("2026-03-01T09:00:00"))
            store.record_session_started("Admin", bundle)
            store.record_session_finished(bundle.session_id, "finalized")
            _write_session_csv(bundle.csv_path, annotation_text="[System] signal dropout")

            rows = summarize_tag_correlations(store, "Admin", session_limit=10)
            self.assertEqual(rows, [])

    def test_system_annotations_can_be_included(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")

            bundle = _bundle(root, "s1", started_at=datetime.fromisoformat("2026-03-01T09:00:00"))
            store.record_session_started("Admin", bundle)
            store.record_session_finished(bundle.session_id, "finalized")
            _write_session_csv(bundle.csv_path, annotation_text="[System] signal dropout")

            rows = summarize_tag_correlations(
                store,
                "Admin",
                session_limit=10,
                include_system_annotations=True,
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["annotation"], "[System] signal dropout")

    def test_min_usable_events_filter(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")

            for i in range(6):
                started = datetime.fromisoformat(f"2026-03-{i + 1:02d}T09:00:00")
                bundle = _bundle(root, f"s{i + 1}", started_at=started)
                store.record_session_started("Admin", bundle)
                store.record_session_finished(bundle.session_id, "finalized")
                _write_session_csv(bundle.csv_path, annotation_text="Caffeine intake")

            rows = summarize_tag_correlations(
                store,
                "Admin",
                session_limit=50,
                min_usable_events=7,
            )
            self.assertEqual(rows, [])

    def test_phase2_metrics_sdnn_and_lfhf_are_summarized(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root)
            store.ensure_profile("Admin")
            bundle = _bundle(root, "s1", started_at=datetime.fromisoformat("2026-03-01T09:00:00"))
            store.record_session_started("Admin", bundle)
            store.record_session_finished(bundle.session_id, "finalized")
            _write_session_csv(
                bundle.csv_path,
                annotation_text="Breathing set change",
                include_phase2_metrics=True,
            )
            rows = summarize_tag_correlations(store, "Admin", session_limit=10)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertIsNotNone(row["delta_sdnn_ms"])
            self.assertIsNotNone(row["delta_lfhf"])
            self.assertGreater(float(row["delta_sdnn_ms"]), 0.0)
            self.assertGreater(float(row["delta_lfhf"]), 0.0)


if __name__ == "__main__":
    unittest.main()
