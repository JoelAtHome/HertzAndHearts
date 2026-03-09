import sys
from importlib import metadata
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QLockFile
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
        lock_root = Path.home() / "Hertz-and-Hearts"
        lock_root.mkdir(parents=True, exist_ok=True)
        self._instance_lock = QLockFile(str(lock_root / ".app-startup.lock"))
        self._instance_lock.setStaleLockTime(0)
        self._is_primary_instance = bool(self._instance_lock.tryLock(1))
        self._model = Model()
        self._view = View(self._model)
        self._run_startup_recording_purge_if_primary()
        
        # 1. The "Handshake" connection (Fast & Simple)
        self._view.sensor.ibi_update.connect(self._model.hr_handler)

    def _run_startup_recording_purge_if_primary(self) -> None:
        if not self._is_primary_instance:
            return
        try:
            result = self._view._profile_store.purge_recording_sessions()
        except Exception as exc:
            print(f"[startup] Recording-session purge failed: {exc}", file=sys.stderr)
            return
        removed = int(result.get("removed_rows", 0))
        if removed > 0:
            print(
                "[startup] Purged stale recording sessions: "
                f"rows={removed}, deleted_dirs={int(result.get('deleted_dirs', 0))}, "
                f"missing_dirs={int(result.get('missing_dirs', 0))}.",
                file=sys.stderr,
            )

    def release_instance_lock(self) -> None:
        try:
            if self._is_primary_instance:
                self._instance_lock.unlock()
        except Exception:
            pass

def main():
    _warn_if_pandas_neurokit_combo_is_risky()
    _emit_research_use_startup_warning()
    app = Application(sys.argv)
    app.aboutToQuit.connect(lambda: app._view._flush_signal_fault_log("app exit"))
    app.aboutToQuit.connect(app.release_instance_lock)
    # Main window opens first, then profile selection popup on top (_run_startup_flow).
    sys.exit(app.exec())

if __name__ == "__main__":
    main()