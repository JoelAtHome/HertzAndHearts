from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hnh.session_report_rebuild import (
    build_report_data_from_session_dir,
    generate_reports_for_session_dir,
)


class SessionReportRebuildTests(unittest.TestCase):
    def _write_session_files(self, session_dir: Path) -> None:
        csv_path = session_dir / "session.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["event", "value", "timestamp", "elapsed_sec"])
            w.writerow(["IBI", "1000", "2026-01-01T00:00:00", "1000"])
            w.writerow(["IBI", "950", "2026-01-01T00:00:01", "900"])  # backwards elapsed
            w.writerow(["hrv", "42.0", "2026-01-01T00:00:02", "1100"])
            w.writerow(["SDNN", "37.5", "2026-01-01T00:00:03", "1300"])
            w.writerow(["stress_ratio", "1.23", "2026-01-01T00:00:04", "1500"])
            w.writerow(["Annotation", "test marker", "2026-01-01T00:00:05", "1700"])

        manifest = {
            "session_id": "20260101-000000",
            "profile_id": "Admin",
            "timing": {
                "started_at": "2026-01-01T00:00:00",
                "ended_at": "2026-01-01T00:10:00",
            },
            "metrics": {
                "baseline_hr": 68,
                "baseline_rmssd": 35.0,
                "last_hr": 72,
                "last_rmssd": 40.0,
                "qtc": {
                    "session_value_ms": 420.0,
                    "quality": {"is_valid": True, "reason": "ok"},
                    "method_suggestion": {
                        "suggested_method": "adaptive_bazett_fridericia",
                        "reasoning": "Mixed heart-rate range during session.",
                    },
                },
            },
            "disclaimer": {"warning": "RESEARCH USE ONLY"},
            "artifacts": {"csv": {"path": "session.csv", "exists": True}},
            "settings_snapshot": {"SETTLING_DURATION": 15},
        }
        (session_dir / "session_manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

    def test_build_report_data_from_session_dir_parses_saved_artifacts(self):
        with TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session-a"
            session_dir.mkdir(parents=True, exist_ok=True)
            self._write_session_files(session_dir)
            data = build_report_data_from_session_dir(session_dir, profile_name="Admin")
            self.assertEqual(data["profile_id"], "Admin")
            self.assertGreater(len(data["hr_values"]), 0)
            self.assertGreaterEqual(len(data["rmssd_values"]), 1)
            self.assertGreaterEqual(len(data["annotations"]), 1)
            self.assertIn("method_suggestion", data["qtc"])

    def test_generate_reports_for_session_dir_writes_docx_and_pdf(self):
        with TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session-b"
            session_dir.mkdir(parents=True, exist_ok=True)
            self._write_session_files(session_dir)
            docx_path, pdf_path = generate_reports_for_session_dir(session_dir, profile_name="Admin")
            self.assertTrue(docx_path.exists())
            self.assertTrue(pdf_path.exists())


if __name__ == "__main__":
    unittest.main()
