from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, perf_counter_ns

from hnh.data_paths import app_data_root


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _resolve_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class _WindowCounters:
    decode_packets: int = 0
    decode_samples: int = 0
    decode_payload_bytes: int = 0
    decode_wall_ms_total: float = 0.0
    decode_wall_ms_max: float = 0.0
    decode_truncated_bytes: int = 0

    ecg_enqueue_batches: int = 0
    ecg_enqueue_samples: int = 0
    ecg_pending_drop_samples: int = 0
    ecg_pending_max: int = 0

    redraw_ticks: int = 0
    redraw_samples_drained: int = 0
    redraw_wall_ms_total: float = 0.0
    redraw_wall_ms_max: float = 0.0

    def reset(self) -> None:
        self.__dict__.update(_WindowCounters().__dict__)


class PerfProbe:
    def __init__(self, *, enabled: bool, flush_seconds: float, log_path: Path):
        self.enabled = bool(enabled)
        self.flush_seconds = max(1.0, float(flush_seconds))
        self.log_path = log_path
        self._lock = threading.Lock()
        self._window = _WindowCounters()
        self._last_flush = monotonic()
        self._session_started_ns = perf_counter_ns()
        self._ensured_parent = False
        self._pacer_renderer = "unknown"

    def _ensure_parent_dir(self) -> None:
        if self._ensured_parent:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensured_parent = True

    def _maybe_flush_locked(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = monotonic()
        if not force and (now - self._last_flush) < self.flush_seconds:
            return
        self._last_flush = now
        wall_seconds = max(0.0, (perf_counter_ns() - self._session_started_ns) / 1e9)

        decode_avg = (
            self._window.decode_wall_ms_total / self._window.decode_packets
            if self._window.decode_packets
            else 0.0
        )
        redraw_avg = (
            self._window.redraw_wall_ms_total / self._window.redraw_ticks
            if self._window.redraw_ticks
            else 0.0
        )
        payload = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": "perf_probe_window",
            "elapsed_sec": round(wall_seconds, 3),
            "window_sec": round(self.flush_seconds, 2),
            "pacer_renderer": self._pacer_renderer,
            "decode_packets": self._window.decode_packets,
            "decode_samples": self._window.decode_samples,
            "decode_payload_bytes": self._window.decode_payload_bytes,
            "decode_truncated_bytes": self._window.decode_truncated_bytes,
            "decode_ms_avg": round(decode_avg, 4),
            "decode_ms_max": round(self._window.decode_wall_ms_max, 4),
            "ecg_enqueue_batches": self._window.ecg_enqueue_batches,
            "ecg_enqueue_samples": self._window.ecg_enqueue_samples,
            "ecg_pending_drop_samples": self._window.ecg_pending_drop_samples,
            "ecg_pending_max": self._window.ecg_pending_max,
            "redraw_ticks": self._window.redraw_ticks,
            "redraw_samples_drained": self._window.redraw_samples_drained,
            "redraw_ms_avg": round(redraw_avg, 4),
            "redraw_ms_max": round(self._window.redraw_wall_ms_max, 4),
        }
        self._ensure_parent_dir()
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
        self._window.reset()

    def set_pacer_renderer(self, renderer: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._pacer_renderer = str(renderer or "unknown")

    def note_decode(
        self,
        *,
        sample_count: int,
        payload_bytes: int,
        truncated_bytes: int,
        elapsed_ns: int,
    ) -> None:
        if not self.enabled:
            return
        elapsed_ms = max(0.0, float(elapsed_ns) / 1e6)
        with self._lock:
            self._window.decode_packets += 1
            self._window.decode_samples += max(0, int(sample_count))
            self._window.decode_payload_bytes += max(0, int(payload_bytes))
            self._window.decode_truncated_bytes += max(0, int(truncated_bytes))
            self._window.decode_wall_ms_total += elapsed_ms
            self._window.decode_wall_ms_max = max(self._window.decode_wall_ms_max, elapsed_ms)
            self._maybe_flush_locked()

    def note_ecg_enqueue(self, *, added: int, pending_size: int, dropped: int) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._window.ecg_enqueue_batches += 1
            self._window.ecg_enqueue_samples += max(0, int(added))
            self._window.ecg_pending_drop_samples += max(0, int(dropped))
            self._window.ecg_pending_max = max(self._window.ecg_pending_max, int(pending_size))
            self._maybe_flush_locked()

    def note_redraw(self, *, drained: int, elapsed_ns: int) -> None:
        if not self.enabled:
            return
        elapsed_ms = max(0.0, float(elapsed_ns) / 1e6)
        with self._lock:
            self._window.redraw_ticks += 1
            self._window.redraw_samples_drained += max(0, int(drained))
            self._window.redraw_wall_ms_total += elapsed_ms
            self._window.redraw_wall_ms_max = max(self._window.redraw_wall_ms_max, elapsed_ms)
            self._maybe_flush_locked()

    def flush(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._maybe_flush_locked(force=True)


_PROBE_SINGLETON: PerfProbe | None = None


def get_perf_probe() -> PerfProbe:
    global _PROBE_SINGLETON
    if _PROBE_SINGLETON is not None:
        return _PROBE_SINGLETON

    from hnh.settings import Settings

    settings = Settings()
    enabled = bool(settings.PERF_PROBE_ENABLED)
    env_enabled = os.getenv("HNH_PERF_PROBE_ENABLED")
    if env_enabled is not None:
        enabled = _resolve_bool(env_enabled)

    flush_seconds = _as_float(getattr(settings, "PERF_PROBE_FLUSH_SECONDS", 5.0), 5.0)
    env_flush = os.getenv("HNH_PERF_PROBE_FLUSH_SECONDS")
    if env_flush is not None:
        flush_seconds = _as_float(env_flush, flush_seconds)

    env_log_path = os.getenv("HNH_PERF_PROBE_LOG")
    if env_log_path:
        log_path = Path(env_log_path).expanduser()
    else:
        out_dir = app_data_root() / "perf"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = out_dir / f"perf_probe_{stamp}.jsonl"

    _PROBE_SINGLETON = PerfProbe(
        enabled=enabled,
        flush_seconds=flush_seconds,
        log_path=log_path,
    )
    if enabled:
        print(f"[perf_probe] enabled -> {log_path}")
    return _PROBE_SINGLETON
