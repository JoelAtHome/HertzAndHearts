from datetime import datetime
import time
from PySide6.QtCore import QObject, Signal
from hnh.utils import NamedSignal


class Logger(QObject):
    recording_status = Signal(int)
    status_update = Signal(str)

    def __init__(self):
        super().__init__()
        self.file = None
        self.current_path: str | None = None
        self._recording_started_perf: float | None = None

    def start_recording(self, file_path: str):
        if self.file:
            self.status_update.emit(f"Already writing to a file at {self.file.name}.")
            return  # only write to one file at a time
        try:
            self.file = open(file_path, "a+", encoding="utf-8")
        except OSError as exc:
            self.file = None
            self.current_path = None
            self.status_update.emit(f"Failed to start recording: {exc}")
            return
        self.current_path = file_path
        self._recording_started_perf = time.perf_counter()
        self.file.write("event,value,timestamp,elapsed_sec\n")  # header
        self.file.flush()
        self.recording_status.emit(0)
        self.status_update.emit(f"Started recording to {self.file.name}.")

    def save_recording(self):
        """Called when:
        1. User saves recording.
        2. User closes app while recording
        """
        if not self.file:
            return
        saved_path = self.current_path or self.file.name
        self.file.close()
        self.recording_status.emit(1)
        self.status_update.emit(f"Saved recording file: {saved_path}")
        self.file = None
        self.current_path = None
        self._recording_started_perf = None

    def _elapsed_ms(self) -> float:
        started = self._recording_started_perf
        if started is None:
            return 0.0
        return max(0.0, (time.perf_counter() - started) * 1000.0)

    def write_to_file(self, data: NamedSignal):
        if not self.file:
            return
        key, val = data
        timestamp = datetime.now().isoformat()
        elapsed_ms = self._elapsed_ms()

        if key == "ibis":
            try:
                _, buffer = val
                if not buffer:
                    return
                value = buffer[-1]  # IBI in ms
            except (TypeError, ValueError, IndexError):
                return
            self.file.write(f"IBI,{value},{timestamp},{elapsed_ms:.3f}\n")
        else:
            try:
                if isinstance(val, list):
                    value = val[-1]
                elif isinstance(val, tuple):
                    value = val[-1][-1]
                else:
                    value = val
            except (IndexError, TypeError):
                return
            self.file.write(f"{key},{value},{timestamp},{elapsed_ms:.3f}\n")
        self.file.flush()
