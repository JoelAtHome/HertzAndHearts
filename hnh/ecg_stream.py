"""Append-only on-disk ECG sample stream (float32 LE) for session recording."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable

import numpy as np

from hnh.config import ECG_SAMPLE_RATE

_ECG_STREAM_NAME = "session_ecg.f32"
_FLUSH_EVERY_SAMPLES = ECG_SAMPLE_RATE  # ~1 s


def ecg_stream_path_for_session(session_dir: Path) -> Path:
    return Path(session_dir) / _ECG_STREAM_NAME


def read_ecg_stream_samples(path: Path | str) -> list[float]:
    """Load all float32 LE samples from a stream file (empty if missing/invalid)."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    try:
        raw = file_path.read_bytes()
    except OSError:
        return []
    if not raw:
        return []
    usable = len(raw) - (len(raw) % 4)
    if usable <= 0:
        return []
    arr = np.frombuffer(raw[:usable], dtype="<f4")
    return [float(x) for x in arr]


def ecg_stream_sample_count(path: Path | str) -> int:
    file_path = Path(path)
    if not file_path.is_file():
        return 0
    try:
        size = file_path.stat().st_size
    except OSError:
        return 0
    return max(0, size // 4)


class EcgSampleStream:
    """Thread-safe append writer for session ECG samples."""

    def __init__(self, path: Path, *, sample_rate_hz: int = ECG_SAMPLE_RATE):
        self.path = Path(path)
        self.sample_rate_hz = int(sample_rate_hz) or ECG_SAMPLE_RATE
        self._lock = threading.Lock()
        self._fh = self.path.open("wb")
        self._count = 0
        self._since_flush = 0
        self._closed = False

    @classmethod
    def open_write(cls, path: Path, *, sample_rate_hz: int = ECG_SAMPLE_RATE) -> EcgSampleStream:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        return cls(path, sample_rate_hz=sample_rate_hz)

    @property
    def sample_count(self) -> int:
        with self._lock:
            return self._count

    def append(self, samples: Iterable[float]) -> int:
        """Append samples; returns number written."""
        if samples is None:
            return 0
        try:
            arr = np.asarray(list(samples) if not hasattr(samples, "__len__") else samples, dtype=np.float64)
        except (TypeError, ValueError):
            return 0
        if arr.size == 0:
            return 0
        # Drop non-finite values rather than writing NaNs into the archive.
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return 0
        payload = np.asarray(arr, dtype="<f4").tobytes(order="C")
        with self._lock:
            if self._closed or self._fh is None:
                return 0
            self._fh.write(payload)
            n = int(arr.size)
            self._count += n
            self._since_flush += n
            if self._since_flush >= _FLUSH_EVERY_SAMPLES:
                self._fh.flush()
                self._since_flush = 0
            return n

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            fh = self._fh
            self._fh = None
        if fh is not None:
            try:
                fh.flush()
            except OSError:
                pass
            try:
                fh.close()
            except OSError:
                pass

    def flush(self) -> None:
        with self._lock:
            if self._closed or self._fh is None:
                return
            try:
                self._fh.flush()
                self._since_flush = 0
            except OSError:
                pass

    def __enter__(self) -> EcgSampleStream:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
