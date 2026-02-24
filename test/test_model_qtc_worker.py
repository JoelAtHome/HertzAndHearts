from __future__ import annotations

import unittest

from hnh.config import ECG_SAMPLE_RATE
from hnh.model import Model
from hnh.utils import NamedSignal


class ModelQtcWorkerTests(unittest.TestCase):
    def _make_model(self) -> Model:
        model = Model()
        self.addCleanup(model._qtc_executor.shutdown, wait=False, cancel_futures=True)
        return model

    def _prime_ecg(self, model: Model, total_samples: int) -> None:
        model._ecg_buffer.clear()
        model._ecg_buffer.extend([0.0] * (ECG_SAMPLE_RATE * 5))
        model._ecg_total_samples = total_samples

    def test_schedule_keeps_only_latest_pending_request(self):
        model = self._make_model()
        model._qtc_active_seq = 1
        model._qtc_latest_request_seq = 1

        self._prime_ecg(model, total_samples=1000)
        model._schedule_qtc_compute()
        first_pending = model._qtc_pending_request
        self.assertIsNotNone(first_pending)

        self._prime_ecg(model, total_samples=2000)
        model._schedule_qtc_compute()
        second_pending = model._qtc_pending_request
        self.assertIsNotNone(second_pending)
        self.assertGreater(second_pending[0], first_pending[0])
        self.assertEqual(second_pending[3], 2000)

    def test_stale_completion_does_not_publish(self):
        model = self._make_model()
        model._qtc_active_seq = 7
        model._qtc_latest_request_seq = 8
        received: list[NamedSignal] = []
        model.qtc_update.connect(received.append)

        payload = {"trend_point": {}, "quality": {"is_valid": True}}
        model._on_qtc_compute_done(seq=7, total_samples=900, payload=payload)
        self.assertEqual(len(received), 0)

    def test_latest_completion_publishes_and_updates_timeline(self):
        model = self._make_model()
        model._qtc_active_seq = 9
        model._qtc_latest_request_seq = 9
        received: list[NamedSignal] = []
        model.qtc_update.connect(received.append)

        payload = {"trend_point": {}, "quality": {"is_valid": False}}
        model._on_qtc_compute_done(seq=9, total_samples=650, payload=payload)

        self.assertEqual(len(received), 1)
        trend = received[0].value["trend_point"]
        self.assertAlmostEqual(trend["t_sec"], 650.0 / float(ECG_SAMPLE_RATE))
        self.assertTrue(trend["is_low_quality"])


if __name__ == "__main__":
    unittest.main()
