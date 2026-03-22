"""
Append-only BLE / Qt Bluetooth diagnostics for support (no console required).

Log file: <app_data_root>/ble-diagnostics.log
(Windows: typically %LOCALAPPDATA%\\Hertz-and-Hearts\\ble-diagnostics.log)
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hnh.data_paths import app_data_root

LOG_FILENAME = "ble-diagnostics.log"
_LOCK = threading.Lock()
_MAX_BYTES = 400_000


def ble_diagnostics_log_path() -> Path:
    return app_data_root() / LOG_FILENAME


def append_ble_diagnostic(
    component: str,
    event: str,
    *,
    message: str = "",
    **fields: Any,
) -> Path:
    """
    Append one JSON line. Returns path to the log file.
    """
    root = app_data_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOG_FILENAME
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        "component": component,
        "event": event,
        "message": message,
    }
    for k, v in fields.items():
        if v is not None:
            record[k] = v
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _LOCK:
        try:
            with path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(line)
        except OSError:
            return path
        _maybe_truncate(path)
    return path


def _maybe_truncate(path: Path) -> None:
    try:
        if path.stat().st_size <= _MAX_BYTES:
            return
    except OSError:
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        keep = lines[-1500:]
        path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    except OSError:
        pass
