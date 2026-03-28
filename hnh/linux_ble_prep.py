"""
Linux / BlueZ: best-effort steps before starting a PC BLE scan.

Phone Bridge mode skips this path entirely (no local BLE scan). Prep runs in a
worker thread so the UI stays responsive while `bluetoothctl` may block briefly.
"""

from __future__ import annotations

import subprocess
import time

from PySide6.QtCore import QThread


def run_linux_ble_scan_preparation_subprocess() -> None:
    """
    Ask BlueZ to power the default adapter on, then pause briefly for stack settle.

    Safe no-ops if `bluetoothctl` is missing or times out.
    """
    try:
        subprocess.run(
            ["bluetoothctl", "power", "on"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    time.sleep(0.35)


class LinuxBlePrepWorker(QThread):
    """Runs :func:`run_linux_ble_scan_preparation_subprocess` off the GUI thread."""

    def run(self) -> None:
        run_linux_ble_scan_preparation_subprocess()
