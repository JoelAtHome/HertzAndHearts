from datetime import datetime
from PySide6.QtCore import QObject, Signal
from hnh.utils import NamedSignal


class Logger(QObject):
    recording_status = Signal(int)
    status_update = Signal(str)

    def __init__(self):
        super().__init__()
        self.file = None
        self.current_path: str | None = None

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
        self.file.write("event,value,timestamp\n")  # header
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

    def write_to_file(self, data: NamedSignal):
        if not self.file:
            return
        key, val = data
        try:
            if isinstance(val, list):
                val = val[-1]
            if isinstance(val, tuple):
                val = val[-1][-1]
        except (IndexError, TypeError):
            return
        timestamp = datetime.now().isoformat()
        self.file.write(f"{key},{val},{timestamp}\n")
        self.file.flush()
