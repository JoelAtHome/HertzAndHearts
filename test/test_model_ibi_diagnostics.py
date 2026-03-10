from __future__ import annotations

import unittest

from hnh.model import Model


class ModelIbiDiagnosticsTests(unittest.TestCase):
    def test_beat_and_buffer_update_counts_track_one_to_one(self):
        model = Model()
        self.addCleanup(model._qtc_executor.shutdown, wait=False, cancel_futures=True)
        model.reset_ibi_diagnostics()
        rr_values = [900, 880, 910, 895, 905]
        for rr in rr_values:
            model.hr_handler(rr)
            model.update_ibis_buffer(rr)
        snap = model.ibi_diagnostics_snapshot()
        self.assertEqual(snap["beats_received"], len(rr_values))
        self.assertEqual(snap["buffer_updates"], len(rr_values))
        self.assertEqual(snap["delta"], 0)


if __name__ == "__main__":
    unittest.main()
