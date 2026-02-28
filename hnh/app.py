import sys
from importlib import metadata
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from hnh.view import View
from hnh.model import Model


def _parse_major_minor(version_text: str) -> tuple[int, int] | None:
    parts = version_text.split(".")
    if len(parts) < 2:
        return None
    try:
        major = int(parts[0])
        minor_digits = "".join(ch for ch in parts[1] if ch.isdigit())
        if not minor_digits:
            return None
        minor = int(minor_digits)
        return major, minor
    except ValueError:
        return None


def _warn_if_pandas_neurokit_combo_is_risky() -> None:
    """
    Console-only startup warning for a known noisy combination:
    pandas Copy-on-Write + older NeuroKit internals.
    """
    try:
        pandas_version = metadata.version("pandas")
        neurokit_version = metadata.version("neurokit2")
    except metadata.PackageNotFoundError:
        return
    except Exception:
        return

    pandas_mm = _parse_major_minor(pandas_version)
    neurokit_mm = _parse_major_minor(neurokit_version)
    if pandas_mm is None or neurokit_mm is None:
        return

    # Heuristic: pandas 2.2+ is where CoW chained-assignment warnings became
    # more visible in third-party code paths.
    if pandas_mm >= (2, 2):
        print(
            "[startup] Potential pandas/neurokit2 compatibility issue: "
            f"pandas {pandas_version} + neurokit2 {neurokit_version}. "
            "If you see pandas ChainedAssignmentError warnings from neurokit2, "
            "update neurokit2 or pin pandas to an earlier compatible release.",
            file=sys.stderr,
        )


def _emit_research_use_startup_warning() -> None:
    warning = "RESEARCH USE ONLY - NOT FOR CLINICAL DIAGNOSIS OR TREATMENT."
    print(warning, file=sys.stderr)
    try:
        log_dir = Path.home() / "Hertz-and-Hearts"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "startup.log"
        timestamp = datetime.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8", errors="ignore") as fh:
            fh.write(f"{timestamp} {warning}\n")
    except Exception:
        return


class Application(QApplication):
    def __init__(self, sys_argv):
        super(Application, self).__init__(sys_argv)
        self._model = Model()
        self._view = View(self._model)
        
        # 1. The "Handshake" connection (Fast & Simple)
        self._view.sensor.ibi_update.connect(self._model.hr_handler)

def main():
    _warn_if_pandas_neurokit_combo_is_risky()
    _emit_research_use_startup_warning()
    app = Application(sys.argv)
    app.aboutToQuit.connect(lambda: app._view._flush_signal_fault_log("app exit"))
    app._view.show()
    QTimer.singleShot(0, app._view.showMaximized)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()