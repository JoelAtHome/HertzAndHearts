from __future__ import annotations

import unittest

from PySide6.QtCore import QByteArray

from hnh.sensor import SensorClient, _decode_pmd_ecg_samples


def _pack_signed_24(value: int) -> bytes:
    if value < 0:
        value += 1 << 24
    return bytes((value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF))


def _legacy_decode(raw_payload: bytes) -> list[float]:
    samples = []
    i = 0
    while i + 2 < len(raw_payload):
        val = raw_payload[i] | (raw_payload[i + 1] << 8) | (raw_payload[i + 2] << 16)
        if val >= 0x800000:
            val -= 0x1000000
        samples.append(val / 1000.0)
        i += 3
    return samples


class SensorDecodeTests(unittest.TestCase):
    def test_decode_matches_legacy_for_boundaries_and_truncated_tail(self):
        values = [0, 1, -1, 123456, -654321, 0x7FFFFF, -0x800000]
        payload = b"".join(_pack_signed_24(v) for v in values) + b"\xAA\xBB"
        self.assertEqual(_decode_pmd_ecg_samples(payload), _legacy_decode(payload))

    def test_decode_returns_empty_for_incomplete_payload(self):
        self.assertEqual(_decode_pmd_ecg_samples(b""), [])
        self.assertEqual(_decode_pmd_ecg_samples(b"\x01"), [])
        self.assertEqual(_decode_pmd_ecg_samples(b"\x01\x02"), [])

    def test_handler_emits_ready_once_and_preserves_sample_values(self):
        client = SensorClient()
        ready_events: list[None] = []
        updates: list[list[float]] = []
        client.ecg_ready.connect(lambda: ready_events.append(None))
        client.ecg_update.connect(lambda samples: updates.append(samples))

        header = bytes([0x00]) + b"\x00" * 9
        frame_a = header + _pack_signed_24(1000) + _pack_signed_24(-1000)
        frame_b = header + _pack_signed_24(500)
        client._pmd_data_handler(None, QByteArray(frame_a))
        client._pmd_data_handler(None, QByteArray(frame_b))

        self.assertEqual(len(ready_events), 1)
        self.assertEqual(updates, [[1.0, -1.0], [0.5]])

    def test_handler_ignores_short_or_non_ecg_frames(self):
        client = SensorClient()
        updates: list[list[float]] = []
        client.ecg_update.connect(lambda samples: updates.append(samples))

        client._pmd_data_handler(None, QByteArray(b"\x00" * 9))
        client._pmd_data_handler(None, QByteArray(bytes([0x01]) + b"\x00" * 12))

        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()
