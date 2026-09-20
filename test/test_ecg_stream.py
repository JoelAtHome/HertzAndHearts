from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from hnh.ecg_stream import (
    EcgSampleStream,
    ecg_stream_sample_count,
    read_ecg_stream_samples,
)


class EcgStreamTests(unittest.TestCase):
    def test_append_read_roundtrip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "session_ecg.f32"
            samples = [0.1, -0.2, 1.25, 0.0]
            with EcgSampleStream.open_write(path) as stream:
                written = stream.append(samples)
                self.assertEqual(written, 4)
                self.assertEqual(stream.sample_count, 4)
            self.assertEqual(ecg_stream_sample_count(path), 4)
            loaded = read_ecg_stream_samples(path)
            self.assertEqual(len(loaded), 4)
            np.testing.assert_allclose(loaded, samples, rtol=1e-6, atol=1e-6)

    def test_append_batches_accumulate(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "session_ecg.f32"
            stream = EcgSampleStream.open_write(path)
            try:
                stream.append([1.0, 2.0])
                stream.append(np.array([3.0, 4.0, 5.0], dtype=float))
            finally:
                stream.close()
            self.assertEqual(read_ecg_stream_samples(path), [1.0, 2.0, 3.0, 4.0, 5.0])


if __name__ == "__main__":
    unittest.main()
