"""
Runtime settings manager with persistent overrides and a GUI dialog.

Defaults come from config.py.  User changes are saved to a small JSON
file in the user's home directory so they survive app restarts.
"""
import json
import math
import os
import platform
import shutil
from collections import OrderedDict
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QLabel,
    QMessageBox, QScrollArea, QWidget, QLineEdit, QListWidget,
    QInputDialog, QAbstractItemView, QFileDialog, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt, Signal

from hnh import config as _defaults
from hnh.data_paths import (
    APP_DATA_ENV_VAR,
    app_data_root,
    default_data_root_tooltip,
    legacy_data_root,
    recommended_data_root,
)

SETTINGS_FILE = Path.home() / ".hnh_settings.json"
TIMELINE_PREF_MAIN_SPAN = "main_timeline_span"
TIMELINE_SPAN_DEFAULT_LABEL = "60 s"
TIMELINE_SPAN_LABELS: tuple[str, ...] = ("15 s", "30 s", "60 s", "120 s", "240 s", "Full")

# ──────────────────────────────────────────────────────────────────────
#  Registry of user-facing settings
# ──────────────────────────────────────────────────────────────────────
# Ordered dict keeps the UI layout deterministic.
# Keys must match config.py attribute names exactly.
# "advanced": True marks settings hidden behind the Advanced toggle.
REGISTRY = OrderedDict([
    # --- Session Timing ---
    ("SETTLING_DURATION", {
        "display": "Settling Duration",
        "tooltip": (
            "Seconds after sensor connection before signal quality is "
            "judged.  Allows the sensor to stabilize on the skin."
        ),
        "type": int, "min": 5, "max": 120, "unit": "seconds",
        "section": "Session Timing",
        "scope": "global",
    }),
    ("BASELINE_DURATION", {
        "display": "Baseline Duration",
        "tooltip": (
            "Seconds of stable data collected to establish the patient's "
            "resting HRV baseline.  Longer = more accurate baseline."
        ),
        "type": int, "min": 10, "max": 180, "unit": "seconds",
        "section": "Session Timing",
        "scope": "global",
    }),
    ("EXPORT_EDF_PLUS_D", {
        "display": "Export EDF+ on Finalize",
        "tooltip": (
            "When enabled, saving/finalizing a session also writes a compact "
            "EDF+ file with HR, RMSSD, and ECG (or synthetic ECG for replay). "
            "Replay plots the waveform from this file; CSV alone does not carry ECG."
        ),
        "type": bool,
        "section": "Session Timing",
        "scope": "profile",
    }),
    ("SESSION_SAVE_PATH", {
        "display": "Session Save Path",
        "tooltip": (
            "Folder where finalized sessions (CSV, report, EDF+) are written. "
            "Leave empty to use the app data folder's Sessions/{profile} location. "
            "Stored when you confirm Save & Close; the next Stop & Save uses this path "
            "(no app restart)."
        ),
        "type": str,
        "section": "Session Timing",
        "scope": "profile",
    }),
    ("OPEN_SESSION_FOLDER_ON_SAVE", {
        "display": "Open Session Folder After Save",
        "tooltip": (
            "When enabled, Stop & Save opens the session folder in your system "
            "file manager so you can quickly access the saved files."
        ),
        "type": bool,
        "section": "Session Timing",
        "scope": "profile",
    }),

    # --- HRV Calculation ---
    ("RMSSD_WINDOW", {
        "display": "RMSSD Window",
        "tooltip": (
            "Number of recent heartbeats used to calculate RMSSD.  "
            "Larger = smoother and slower to change.  "
            "Smaller = more responsive but jumpier.  "
            "60 beats \u2248 1 minute at resting heart rate."
        ),
        "type": int, "min": 10, "max": 300, "unit": "beats",
        "section": "HRV Calculation",
        "scope": "global",
    }),
    ("SMOOTH_SECONDS", {
        "display": "Chart Smoothing",
        "tooltip": (
            "Seconds of data averaged when drawing the RMSSD chart line.  "
            "Larger = smoother trace with less beat-to-beat jitter.  "
            "Smaller = more detail but noisier appearance."
        ),
        "type": int, "min": 3, "max": 60, "unit": "seconds",
        "section": "HRV Calculation",
        "scope": "global",
    }),
    ("FREQUENCY_WINDOW_SIZE", {
        "display": "Stress Ratio Min Beats",
        "tooltip": (
            "Minimum heartbeats needed before the LF/HF stress ratio is "
            "computed.  Clinical standard is 56 (\u2248 1 min).  "
            "Lower values give faster results but less accuracy."
        ),
        "type": int, "min": 10, "max": 120, "unit": "beats",
        "section": "HRV Calculation",
        "scope": "global",
    }),

    # --- Signal Quality ---
    ("DATA_TIMEOUT_SECONDS", {
        "display": "Data Timeout",
        "tooltip": (
            "Seconds of silence before declaring the signal lost.  "
            "Shorter = faster detection but may false-trigger during "
            "brief Bluetooth dropouts."
        ),
        "type": float, "min": 1.0, "max": 30.0, "step": 0.5,
        "unit": "seconds", "section": "Signal Quality",
        "scope": "global",
    }),
    ("DEVIATION_THRESHOLD", {
        "display": "Deviation Threshold",
        "tooltip": (
            "How far a heartbeat can deviate from the rolling average "
            "before triggering an \u2018Erratic\u2019 warning.  "
            "0.30 = 30%.  Lower = more sensitive to irregularities."
        ),
        "type": float, "min": 0.10, "max": 1.00, "step": 0.05,
        "decimals": 2, "unit": "(ratio)", "section": "Signal Quality",
        "scope": "global",
    }),
    ("DEVIATION_WINDOW", {
        "display": "Deviation Window",
        "tooltip": (
            "Number of recent heartbeats used to compute the rolling "
            "average for the adaptive signal quality check."
        ),
        "type": int, "min": 5, "max": 120, "unit": "beats",
        "section": "Signal Quality",
        "scope": "global",
    }),
    ("DEVIATION_MIN_SAMPLES", {
        "display": "Min Samples for Check",
        "tooltip": (
            "Minimum heartbeats collected before the adaptive signal "
            "quality check activates.  Prevents false faults during "
            "the first few seconds of a session."
        ),
        "type": int, "min": 3, "max": 60, "unit": "beats",
        "section": "Signal Quality",
        "scope": "global",
    }),
    ("RECOVERY_BEATS", {
        "display": "Recovery Beats",
        "tooltip": (
            "Consecutive normal heartbeats required to clear an active "
            "fault and restore \u2018Signal: GOOD\u2019.  "
            "Higher = more cautious recovery.  "
            "Lower = faster but risks false clearance."
        ),
        "type": int, "min": 3, "max": 60, "unit": "beats",
        "section": "Signal Quality",
        "scope": "global",
    }),

    # --- ECG Monitor ---
    ("ECG_DISPLAY_SECONDS", {
        "display": "Display Duration",
        "tooltip": (
            "Seconds of ECG waveform visible in the monitor window.  "
            "Takes effect the next time the ECG window is opened."
        ),
        "type": int, "min": 2, "max": 15, "unit": "seconds",
        "section": "ECG Monitor",
        "scope": "profile",
    }),
    ("LINUX_ENABLE_PMD_EXPERIMENTAL", {
        "display": "Linux PMD/ECG Path (Experimental)",
        "tooltip": (
            "Linux only. Enables Polar PMD control/data path used by ECG features. "
            "When disabled, app uses stable HR/RR-only mode. Leave unchecked when "
            "reliable Bluetooth is not available (e.g. disconnects or no data). "
            "If changed while running, disconnect/reconnect sensor to apply."
        ),
        "type": bool,
        "section": "ECG Monitor",
        "scope": "global",
        "advanced": True,
    }),

    # --- QTc Estimation ---
    ("QTC_SUMMARY_WINDOW_SECONDS", {
        "display": "QTc Summary Window",
        "tooltip": (
            "Seconds from the end of the session used to compute the "
            "canonical QTc summary value (median of valid beats)."
        ),
        "type": int, "min": 10, "max": 120, "unit": "seconds",
        "section": "QTc Estimation",
        "scope": "global",
    }),
    ("QTC_MIN_VALID_BEATS", {
        "display": "QTc Min Valid Beats",
        "tooltip": (
            "Minimum number of valid QT/RR beats required before showing "
            "a session QTc value."
        ),
        "type": int, "min": 3, "max": 60, "unit": "beats",
        "section": "QTc Estimation",
        "scope": "global",
    }),

    # --- Developer ---
    ("DEBUG", {
        "display": "Debug Mode",
        "tooltip": (
            "Enables verbose diagnostic messages in the background "
            "console window (the black terminal behind the app).  "
            "Useful for troubleshooting.  Leave off for normal use."
        ),
        "type": bool, "section": "Developer",
        "scope": "profile",
    }),
    ("PERF_PROBE_ENABLED", {
        "display": "Perf Probe Logging",
        "tooltip": (
            "Writes lightweight periodic JSONL metrics for BLE decode and ECG "
            "plot redraw timing. Intended for before/after performance checks."
        ),
        "type": bool, "section": "Developer",
        "scope": "global",
    }),
    ("PERF_PROBE_FLUSH_SECONDS", {
        "display": "Perf Probe Flush Interval",
        "tooltip": (
            "Seconds between aggregated performance metric flushes. "
            "Lower values give finer detail with slightly more disk activity."
        ),
        "type": float, "min": 1.0, "max": 30.0, "step": 0.5,
        "decimals": 1, "unit": "seconds", "section": "Developer",
        "scope": "global",
    }),

    # ─── Advanced / Engineering ───────────────────────────────────────
    ("EWMA_WEIGHT_CURRENT_SAMPLE", {
        "display": "HRV EWMA Weight",
        "tooltip": (
            "Exponentially Weighted Moving Average weight for internal "
            "HRV trend tracking.  Range 0\u20131: closer to 0 = heavier "
            "smoothing.  Used for outlier validation, not the displayed "
            "RMSSD value.  Change with caution."
        ),
        "type": float, "min": 0.01, "max": 1.00, "step": 0.05,
        "decimals": 2, "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("HR_EWMA_WEIGHT", {
        "display": "HR Chart EWMA Weight",
        "tooltip": (
            "EWMA weight for the averaged heart-rate line on the top "
            "chart.  Higher = snappier response to real-time HR changes.  "
            "Lower = smoother but laggier.  0.12 is a good balance."
        ),
        "type": float, "min": 0.01, "max": 0.50, "step": 0.01,
        "decimals": 2, "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("IBI_MEDIAN_WINDOW", {
        "display": "IBI Median Window",
        "tooltip": (
            "Number of recent IBIs used to compute a local median for "
            "outlier replacement.  Larger = more stable correction but "
            "slower to react to genuine HR changes."
        ),
        "type": int, "min": 3, "max": 31, "unit": "samples",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("DROPOUT_IBI_MS", {
        "display": "Dropout IBI Threshold",
        "tooltip": (
            "IBI (ms) above which a Level 1 total-dropout fault is "
            "declared.  3000 ms = 3 seconds between beats, which is "
            "not physiologically possible."
        ),
        "type": int, "min": 2000, "max": 10000, "unit": "ms",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("NOISE_IBI_LOW_MS", {
        "display": "Noise Floor IBI",
        "tooltip": (
            "IBI (ms) below which a Level 2 noise fault is triggered.  "
            "300 ms \u2248 HR > 200 bpm, almost certainly artifact."
        ),
        "type": int, "min": 150, "max": 500, "unit": "ms",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("NOISE_IBI_HIGH_MS", {
        "display": "Noise Ceiling IBI",
        "tooltip": (
            "IBI (ms) above which a Level 2 noise fault is triggered.  "
            "2000 ms \u2248 HR < 30 bpm, almost certainly artifact."
        ),
        "type": int, "min": 1500, "max": 5000, "unit": "ms",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("ECG_REFRESH_MS", {
        "display": "ECG Refresh Interval",
        "tooltip": (
            "Milliseconds between ECG chart redraws.  33 ms \u2248 30 fps.  "
            "Lower = smoother animation but higher CPU/GPU load.  "
            "Takes effect the next time the ECG window is opened."
        ),
        "type": int, "min": 16, "max": 100, "unit": "ms",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("QTC_FRIDERICIA_HR_LOW_THRESHOLD", {
        "display": "QTc Fridericia Low HR Threshold",
        "tooltip": (
            "If QTc default correction is Bazett, switch to Fridericia "
            "below this heart-rate threshold."
        ),
        "type": int, "min": 35, "max": 80, "unit": "bpm",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("QTC_FRIDERICIA_HR_HIGH_THRESHOLD", {
        "display": "QTc Fridericia High HR Threshold",
        "tooltip": (
            "If QTc default correction is Bazett, switch to Fridericia "
            "above this heart-rate threshold."
        ),
        "type": int, "min": 80, "max": 160, "unit": "bpm",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("QTC_FRIDERICIA_HYSTERESIS_BPM", {
        "display": "QTc Fridericia Hysteresis",
        "tooltip": (
            "BPM margin used to avoid rapid formula toggling near "
            "Fridericia low/high thresholds."
        ),
        "type": int, "min": 0, "max": 20, "unit": "bpm",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("QTC_MAX_RR_GAP_SECONDS", {
        "display": "QTc Max RR Gap",
        "tooltip": (
            "Maximum allowed RR gap between consecutive valid beats before "
            "QTc summary quality is downgraded."
        ),
        "type": float, "min": 1.0, "max": 5.0, "step": 0.1,
        "decimals": 1, "unit": "seconds",
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
    ("QTC_TREND_ENABLED", {
        "display": "Enable QTc Trend Output",
        "tooltip": (
            "Allow dedicated QTc trend output. Keep disabled for MVP unless "
            "you have validated trend quality and smoothing."
        ),
        "type": bool,
        "section": "Advanced",
        "scope": "global",
        "advanced": True,
    }),
])


def setting_scope(key: str) -> str:
    meta = REGISTRY.get(key, {})
    scope = str(meta.get("scope", "global")).strip().lower()
    return scope if scope in {"global", "profile"} else "global"


def profile_scoped_keys() -> set[str]:
    return {k for k in REGISTRY if setting_scope(k) == "profile"}


# ──────────────────────────────────────────────────────────────────────
#  Path edit widget (line edit + browse button)
# ──────────────────────────────────────────────────────────────────────
class PathEditWidget(QWidget):
    """Line edit with Browse button for directory selection."""

    textChanged = Signal(str)

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit()
        self._edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._edit.setText(current)
        self._edit.textChanged.connect(self.textChanged.emit)
        layout.addWidget(self._edit)
        browse = QPushButton("Browse…")
        browse.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        browse.clicked.connect(self._browse)
        layout.addWidget(browse)

    def _browse(self):
        start = self._edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select folder", start)
        if chosen:
            self._edit.setText(chosen)

    def value(self) -> str:
        return self._edit.text().strip()

    def setValue(self, val: str) -> None:
        self._edit.setText(val or "")


# ──────────────────────────────────────────────────────────────────────
#  Spin boxes: wheel scrolls the parent until the control is clicked (ClickFocus);
#  after that, wheel adjusts the value like a normal spin box.
# ──────────────────────────────────────────────────────────────────────
class SpinBoxNoWheelUnlessFocused(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.ClickFocus)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class DoubleSpinBoxNoWheelUnlessFocused(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.ClickFocus)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


# ──────────────────────────────────────────────────────────────────────
#  Settings singleton
# ──────────────────────────────────────────────────────────────────────
class Settings:
    """Reads defaults from config.py, overlays user overrides from JSON."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._defaults = {}
            for key in REGISTRY:
                default = getattr(_defaults, key)
                inst._defaults[key] = default
                setattr(inst, key, default)
            inst._custom_annotations: list[str] = []
            inst._load_overrides()
            cls._instance = inst
        return cls._instance

    def _load_overrides(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            for key, val in data.items():
                if key == "_custom_annotations" and isinstance(val, list):
                    self._custom_annotations = [str(v) for v in val]
                elif key in self._defaults:
                    expected_type = type(self._defaults[key])
                    setattr(self, key, expected_type(val))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass

    def save(self, *, exclude_keys: set[str] | None = None):
        excluded = set(exclude_keys or set())
        overrides = {}
        for key in REGISTRY:
            if key in excluded:
                continue
            current = getattr(self, key)
            if current != self._defaults[key]:
                overrides[key] = current
        if self._custom_annotations:
            overrides["_custom_annotations"] = self._custom_annotations
        if overrides:
            SETTINGS_FILE.write_text(json.dumps(overrides, indent=2))
        else:
            try:
                SETTINGS_FILE.unlink()
            except FileNotFoundError:
                pass

    def reset_defaults(self):
        for key, default in self._defaults.items():
            setattr(self, key, default)
        self._custom_annotations = []
        try:
            SETTINGS_FILE.unlink()
        except FileNotFoundError:
            pass

    def get_default(self, key):
        return self._defaults[key]

    # ── annotation helpers ────────────────────────────────────────────

    def get_all_annotations(self) -> list[str]:
        """Return merged, deduplicated, sorted list of all annotations."""
        presets = list(_defaults.ANNOTATION_PRESETS)
        merged = sorted(set(presets + self._custom_annotations),
                        key=str.casefold)
        return merged

    def add_custom_annotation(self, text: str):
        """Add a user-typed annotation to the persistent custom list."""
        text = text.strip()
        if not text:
            return
        if text in _defaults.ANNOTATION_PRESETS:
            return
        if text not in self._custom_annotations:
            self._custom_annotations.append(text)
            self.save()

    def get_custom_annotations(self) -> list[str]:
        return list(self._custom_annotations)

    def set_custom_annotations(self, items: list[str]):
        seen: set[str] = set()
        cleaned: list[str] = []
        presets_lower = {p.casefold() for p in _defaults.ANNOTATION_PRESETS}
        for raw in items:
            text = str(raw).strip()
            if not text:
                continue
            key = text.casefold()
            if key in presets_lower or key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        self._custom_annotations = cleaned
        self.save()

    def clear_custom_annotations(self):
        self._custom_annotations = []
        self.save()


class AnnotationEditorDialog(QDialog):
    """Small dialog to manage custom annotation items."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._custom_items: list[str] = settings.get_custom_annotations()

        self.setWindowTitle("Annotation Manager")
        self.setMinimumSize(560, 420)

        root = QVBoxLayout(self)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search annotations...")
        self._search.textChanged.connect(self._apply_filter)
        root.addWidget(self._search)

        # Built-in list (read-only)
        presets_group = QGroupBox("Built-in Presets (read-only)")
        presets_layout = QVBoxLayout(presets_group)
        self._presets_list = QListWidget()
        self._presets_list.setSelectionMode(QAbstractItemView.NoSelection)
        for item in _defaults.ANNOTATION_PRESETS:
            self._presets_list.addItem(item)
        presets_layout.addWidget(self._presets_list)
        root.addWidget(presets_group)

        # Custom list (editable)
        custom_group = QGroupBox("Custom Annotations")
        custom_layout = QVBoxLayout(custom_group)
        self._custom_list = QListWidget()
        self._custom_list.setSelectionMode(QAbstractItemView.SingleSelection)
        custom_layout.addWidget(self._custom_list)

        actions = QHBoxLayout()
        self._add_btn = QPushButton("Add")
        self._add_btn.clicked.connect(self._add_item)
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.clicked.connect(self._edit_item)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete_item)
        self._up_btn = QPushButton("Move Up")
        self._up_btn.clicked.connect(self._move_up)
        self._down_btn = QPushButton("Move Down")
        self._down_btn.clicked.connect(self._move_down)
        for btn in (self._add_btn, self._edit_btn, self._delete_btn, self._up_btn, self._down_btn):
            actions.addWidget(btn)
        custom_layout.addLayout(actions)
        root.addWidget(custom_group)

        # Bottom buttons
        bottom = QHBoxLayout()
        self._reset_btn = QPushButton("Reset Custom List")
        self._reset_btn.clicked.connect(self._reset_custom)
        bottom.addWidget(self._reset_btn)
        bottom.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("Save")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save_and_close)
        bottom.addWidget(self._close_btn)
        bottom.addWidget(self._save_btn)
        root.addLayout(bottom)

        self._reload_custom()
        self._update_action_state()
        self._custom_list.itemSelectionChanged.connect(self._update_action_state)

    def _reload_custom(self):
        self._custom_list.clear()
        for item in self._custom_items:
            self._custom_list.addItem(item)
        self._apply_filter()

    def _current_index(self) -> int:
        row = self._custom_list.currentRow()
        return row if 0 <= row < len(self._custom_items) else -1

    def _update_action_state(self):
        idx = self._current_index()
        has_sel = idx >= 0
        self._edit_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)
        self._up_btn.setEnabled(has_sel and idx > 0)
        self._down_btn.setEnabled(has_sel and idx < (len(self._custom_items) - 1))

    def _apply_filter(self):
        term = self._search.text().strip().casefold()
        for i in range(self._presets_list.count()):
            item = self._presets_list.item(i)
            item.setHidden(bool(term) and term not in item.text().casefold())
        for i in range(self._custom_list.count()):
            item = self._custom_list.item(i)
            item.setHidden(bool(term) and term not in item.text().casefold())

    def _validate_new_text(self, text: str, skip_index: int = -1) -> tuple[bool, str]:
        value = text.strip()
        if not value:
            return False, "Annotation cannot be empty."
        if len(value) > 80:
            return False, "Annotation is too long (max 80 characters)."
        presets = {p.casefold() for p in _defaults.ANNOTATION_PRESETS}
        if value.casefold() in presets:
            return False, "That entry already exists as a built-in preset."
        for idx, existing in enumerate(self._custom_items):
            if idx == skip_index:
                continue
            if value.casefold() == existing.casefold():
                return False, "That custom annotation already exists."
        return True, value

    def _add_item(self):
        text, ok = QInputDialog.getText(self, "Add Annotation", "New annotation:")
        if not ok:
            return
        valid, result = self._validate_new_text(text)
        if not valid:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Invalid Annotation")
            msg.setText(result)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.setDefaultButton(QMessageBox.Ok)
            msg.exec()
            return
        self._custom_items.append(result)
        self._reload_custom()
        self._custom_list.setCurrentRow(len(self._custom_items) - 1)
        self._update_action_state()

    def _edit_item(self):
        idx = self._current_index()
        if idx < 0:
            return
        current = self._custom_items[idx]
        text, ok = QInputDialog.getText(self, "Edit Annotation", "Annotation:", text=current)
        if not ok:
            return
        valid, result = self._validate_new_text(text, skip_index=idx)
        if not valid:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Invalid Annotation")
            msg.setText(result)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.setDefaultButton(QMessageBox.Ok)
            msg.exec()
            return
        self._custom_items[idx] = result
        self._reload_custom()
        self._custom_list.setCurrentRow(idx)
        self._update_action_state()

    def _delete_item(self):
        idx = self._current_index()
        if idx < 0:
            return
        del self._custom_items[idx]
        self._reload_custom()
        if self._custom_items:
            self._custom_list.setCurrentRow(min(idx, len(self._custom_items) - 1))
        self._update_action_state()

    def _move_up(self):
        idx = self._current_index()
        if idx <= 0:
            return
        self._custom_items[idx - 1], self._custom_items[idx] = (
            self._custom_items[idx],
            self._custom_items[idx - 1],
        )
        self._reload_custom()
        self._custom_list.setCurrentRow(idx - 1)
        self._update_action_state()

    def _move_down(self):
        idx = self._current_index()
        if idx < 0 or idx >= len(self._custom_items) - 1:
            return
        self._custom_items[idx + 1], self._custom_items[idx] = (
            self._custom_items[idx],
            self._custom_items[idx + 1],
        )
        self._reload_custom()
        self._custom_list.setCurrentRow(idx + 1)
        self._update_action_state()

    def _reset_custom(self):
        reply = QMessageBox.question(
            self,
            "Reset Custom List",
            "Remove all custom annotations?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._custom_items = []
        self._reload_custom()
        self._update_action_state()

    def _save_and_close(self):
        self._settings.set_custom_annotations(self._custom_items)
        self.accept()


# ──────────────────────────────────────────────────────────────────────
#  Settings dialog
# ──────────────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    _show_advanced = False
    # Non-default: keep text near-black for contrast; blue is a left accent only.
    _LABEL_STYLE_DEFAULT = "border: none; padding-left: 0; margin-left: 0;"
    _LABEL_STYLE_NON_DEFAULT = (
        "font-weight: 700; color: #0d0d0d; border-left: 4px solid #1565c0; "
        "padding-left: 8px; margin-left: 0;"
    )

    def __init__(
        self,
        settings: Settings,
        parent=None,
        *,
        session_save_path_default: str = "",
        profile_store=None,
        profile_id: str | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._session_save_path_default = session_save_path_default or ""
        self._profile_store = profile_store
        self._profile_id = str(profile_id or "").strip()
        self._widgets: dict[str, QCheckBox | QSpinBox | QDoubleSpinBox | PathEditWidget] = {}
        self._labels: dict[str, QLabel] = {}
        self._base_tooltips: dict[str, str] = {}
        self._baseline_values: dict[str, object] | None = None
        self._advanced_groups: list[QGroupBox] = []
        self._section_groups: list[tuple[QGroupBox, list[str], bool]] = []
        self._pending_disclaimer_reset = "none"
        self._advanced_prev_checked = SettingsDialog._show_advanced
        self._active_data_root = app_data_root()
        self._legacy_data_root = legacy_data_root()
        self._recommended_data_root = recommended_data_root()
        self._timeline_default_label: QLabel | None = None
        self._timeline_default_combo: QComboBox | None = None
        self._phone_bridge_ecg_prompt_reset_label: QLabel | None = None
        self._phone_bridge_ecg_prompt_reset_btn: QPushButton | None = None

        self.setWindowTitle("Hertz & Hearts \u2014 Settings")
        self.setMinimumWidth(500)

        root = QVBoxLayout(self)

        data_group = QGroupBox("Data")
        data_form = QFormLayout(data_group)
        data_form.setLabelAlignment(Qt.AlignRight)
        self._data_root_display = QLineEdit(str(self._active_data_root))
        self._data_root_display.setReadOnly(True)
        self._data_root_display.setCursorPosition(0)
        self._data_root_display.setStyleSheet(
            "QLineEdit { background-color: #f2f2f2; color: #555555; }"
        )
        self._data_root_display.setToolTip(
            "Active app data folder for profiles, session index, and diagnostics."
        )
        self._copy_data_root_btn = QPushButton("Copy Path")
        self._copy_data_root_btn.setToolTip("Copy active data folder path to clipboard.")
        self._copy_data_root_btn.clicked.connect(self._copy_data_root_path)
        data_row_widget = QWidget()
        data_row = QHBoxLayout(data_row_widget)
        data_row.setContentsMargins(0, 0, 0, 0)
        data_row.setSpacing(6)
        data_row.addWidget(self._data_root_display, stretch=1)
        data_row.addWidget(self._copy_data_root_btn)
        data_label = QLabel("Data Folder")
        data_label.setToolTip(default_data_root_tooltip())
        data_form.addRow(data_label, data_row_widget)
        self._migrate_data_root_btn = QPushButton("Move Data to Recommended Location…")
        self._migrate_data_root_btn.clicked.connect(self._migrate_data_root)
        self._migrate_data_root_hint = QLabel("")
        self._migrate_data_root_hint.setWordWrap(True)
        migrate_label = QLabel("Data Migration")
        migrate_row_widget = QWidget()
        migrate_row = QVBoxLayout(migrate_row_widget)
        migrate_row.setContentsMargins(0, 0, 0, 0)
        migrate_row.setSpacing(4)
        migrate_row.addWidget(self._migrate_data_root_btn)
        migrate_row.addWidget(self._migrate_data_root_hint)
        data_form.addRow(migrate_label, migrate_row_widget)
        self._refresh_data_migration_ui()
        root.addWidget(data_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        self._form_layout = QVBoxLayout(scroll_content)

        sections: OrderedDict[str, list] = OrderedDict()
        for key, meta in REGISTRY.items():
            sec = meta["section"]
            sections.setdefault(sec, []).append((key, meta))

        for section_name, items in sections.items():
            is_advanced = items[0][1].get("advanced", False)
            group = QGroupBox(section_name)
            form = QFormLayout(group)
            form.setLabelAlignment(Qt.AlignRight)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            section_keys: list[str] = []
            for key, meta in items:
                widget = self._create_widget(key, meta)
                label = QLabel(self._build_label(meta))
                if key == "SESSION_SAVE_PATH":
                    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                full_tip = self._compose_setting_tooltip(key, meta)
                label.setToolTip(full_tip)
                widget.setToolTip(full_tip)
                form.addRow(label, widget)
                self._widgets[key] = widget
                self._labels[key] = label
                self._base_tooltips[key] = full_tip
                section_keys.append(key)
            if (
                section_name == "ECG Monitor"
                and platform.system() == "Linux"
                and self._profile_store is not None
            ):
                tip = (
                    "Clears the remembered choice from 'Don't ask again' on the Linux "
                    "Phone Bridge ECG/QTc prompt. This is separate from the experimental "
                    "PC Bluetooth PMD setting above. The next Phone Bridge connection can "
                    "show the prompt again."
                )
                pr_label = QLabel("Reset Phone Bridge ECG prompt [Global]")
                pr_label.setToolTip(tip)
                pr_btn = QPushButton("Reset \"Don't ask again\"…")
                pr_btn.setToolTip(tip)
                pr_btn.clicked.connect(self._on_reset_phone_bridge_ecg_prompt)
                pr_row = QWidget()
                pr_lay = QHBoxLayout(pr_row)
                pr_lay.setContentsMargins(0, 0, 0, 0)
                pr_lay.addWidget(pr_btn)
                pr_lay.addStretch()
                form.addRow(pr_label, pr_row)
                self._phone_bridge_ecg_prompt_reset_label = pr_label
                self._phone_bridge_ecg_prompt_reset_btn = pr_btn
                self._refresh_phone_bridge_ecg_prompt_reset_button()
            if section_name == "Session Timing":
                has_profile_context = bool(self._profile_store is not None and self._profile_id)
                timeline_label = QLabel("Default Timeline Width [Profile]")
                timeline_tip = (
                    "Per-user default live timeline span for the two main plots. "
                    f"Default: {TIMELINE_SPAN_DEFAULT_LABEL}."
                )
                timeline_label.setToolTip(timeline_tip)
                timeline_combo = QComboBox()
                timeline_combo.setMinimumWidth(96)
                for option in TIMELINE_SPAN_LABELS:
                    timeline_combo.addItem(option)
                saved_span = TIMELINE_SPAN_DEFAULT_LABEL
                if has_profile_context:
                    raw = self._profile_store.get_profile_pref(
                        self._profile_id,
                        TIMELINE_PREF_MAIN_SPAN,
                        TIMELINE_SPAN_DEFAULT_LABEL,
                    )
                    normalized = str(raw).strip()
                    if normalized in TIMELINE_SPAN_LABELS:
                        saved_span = normalized
                timeline_combo.setCurrentText(saved_span)
                if has_profile_context:
                    timeline_combo.setToolTip(timeline_tip)
                else:
                    timeline_combo.setEnabled(False)
                    timeline_combo.setToolTip(
                        "Available when an active profile context is present."
                    )
                form.addRow(timeline_label, timeline_combo)
                self._timeline_default_label = timeline_label
                self._timeline_default_combo = timeline_combo
            self._form_layout.addWidget(group)
            if is_advanced:
                group.setVisible(False)
                self._advanced_groups.append(group)
            self._section_groups.append((group, section_keys, is_advanced))

        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

        default_legend = QLabel(
            "Values that differ from the factory default use bold text with a blue bar "
            "beside the label. Every setting tooltip includes its factory default. "
            "Hover a label for the full description."
        )
        default_legend.setWordWrap(True)
        default_legend.setStyleSheet("font-size: 11px; color: #666; font-style: italic;")
        root.addWidget(default_legend)

        # Advanced toggle
        self._advanced_toggle = QCheckBox("Show Advanced / Engineering Settings")
        self._advanced_toggle.setChecked(SettingsDialog._show_advanced)
        self._advanced_toggle.toggled.connect(self._toggle_advanced)
        root.addWidget(self._advanced_toggle)

        self._scope_filter_toggle = QCheckBox("Show only this profile settings")
        has_profile_context = bool(self._profile_store is not None and self._profile_id)
        self._scope_filter_toggle.setEnabled(has_profile_context)
        self._scope_filter_toggle.setChecked(False)
        if has_profile_context:
            self._scope_filter_toggle.setToolTip(
                "Hide global settings and show only settings stored per profile."
            )
        else:
            self._scope_filter_toggle.setToolTip(
                "Profile-only filter is available when a profile context is active."
            )
        self._scope_filter_toggle.toggled.connect(self._apply_scope_filter)
        root.addWidget(self._scope_filter_toggle)

        self._toggle_advanced(SettingsDialog._show_advanced)
        self._apply_scope_filter(self._scope_filter_toggle.isChecked())

        self._wire_factory_default_highlights()

        # Buttons
        btn_row = QHBoxLayout()
        restore_btn = QPushButton("Restore Defaults")
        restore_btn.setToolTip("Reset every setting to its factory default.")
        restore_btn.clicked.connect(self._restore_defaults)
        btn_row.addWidget(restore_btn)
        ann_btn = QPushButton("Manage Annotations…")
        ann_btn.setToolTip("Open the custom annotation editor.")
        ann_btn.clicked.connect(self._open_annotation_manager)
        btn_row.addWidget(ann_btn)
        self._reset_disclaimer_btn = QPushButton("Reset Disclaimer Prompt…")
        self._reset_disclaimer_btn.setMinimumWidth(190)
        self._reset_disclaimer_btn.setToolTip(
            "Re-enable startup disclaimer prompts that were hidden via 'Don't show again'."
        )
        self._reset_disclaimer_btn.clicked.connect(self._queue_disclaimer_reset)
        btn_row.addWidget(self._reset_disclaimer_btn)
        self._update_reset_disclaimer_button_ui()
        btn_row.addStretch()

        save_btn = QPushButton("Save && Close")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_and_close)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)

        root.addLayout(btn_row)

    # --- factory-default highlighting ------------------------------------

    @staticmethod
    def _compose_setting_tooltip(key: str, meta: dict) -> str:
        base = str(meta.get("tooltip") or "").strip()
        fd = SettingsDialog._factory_default_tip_line(key)
        if not base:
            return fd
        return f"{base}\n\n{fd}"

    @staticmethod
    def _factory_default_tip_line(key: str) -> str:
        d = getattr(_defaults, key)
        meta = REGISTRY[key]
        t = meta["type"]
        if t is bool:
            return f"Factory default: {'On' if d else 'Off'}"
        if t is int:
            unit = str(meta.get("unit") or "").strip()
            suf = f" {unit}" if unit else ""
            return f"Factory default: {int(d)}{suf}"
        if t is float:
            unit = str(meta.get("unit") or "").strip()
            dec = int(meta.get("decimals", 1))
            suf = f" {unit}" if unit else ""
            return f"Factory default: {float(d):.{dec}f}{suf}"
        if t is str:
            s = str(d).strip()
            if not s:
                if key == "SESSION_SAVE_PATH":
                    return (
                        "Factory default: empty (built-in session folder under your data root)"
                    )
                return "Factory default: empty"
            return f"Factory default: {s}"
        return f"Factory default: {d!r}"

    def _effective_widget_value(self, key: str) -> object:
        widget = self._widgets[key]
        t = REGISTRY[key]["type"]
        if t is bool:
            return widget.isChecked()
        if t is str:
            v = widget.value()
            if key == "SESSION_SAVE_PATH" and self._session_save_path_default and v == self._session_save_path_default:
                return ""
            return v
        return widget.value()

    def _matches_factory_default(self, key: str, val: object) -> bool:
        d = getattr(_defaults, key)
        t = REGISTRY[key]["type"]
        if t is bool:
            return bool(val) is bool(d)
        if t is int:
            return int(val) == int(d)
        if t is str:
            return str(val or "") == str(d or "")
        if t is float:
            return math.isclose(float(val), float(d), rel_tol=0.0, abs_tol=1e-6)
        return val == d

    def _refresh_default_highlight(self, key: str) -> None:
        label = self._labels.get(key)
        if label is None:
            return
        widget = self._widgets.get(key)
        base_tip = self._base_tooltips.get(key, label.toolTip())
        try:
            cur = self._effective_widget_value(key)
            at_default = self._matches_factory_default(key, cur)
        except (TypeError, ValueError):
            at_default = True
        if at_default:
            label.setStyleSheet(SettingsDialog._LABEL_STYLE_DEFAULT)
            label.setToolTip(base_tip)
            if widget is not None:
                widget.setToolTip(base_tip)
        else:
            label.setStyleSheet(SettingsDialog._LABEL_STYLE_NON_DEFAULT)
            nd_tip = (
                base_tip
                + "\n\nCurrent value differs from the app factory default "
                "(config.py / fresh install)."
            )
            label.setToolTip(nd_tip)
            if widget is not None:
                widget.setToolTip(nd_tip)

    def _wire_factory_default_highlights(self) -> None:
        for key, widget in self._widgets.items():
            if isinstance(widget, QCheckBox):
                widget.stateChanged.connect(
                    lambda *_a, k=key: self._refresh_default_highlight(k)
                )
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(
                    lambda *_a, k=key: self._refresh_default_highlight(k)
                )
            elif isinstance(widget, PathEditWidget):
                widget.textChanged.connect(
                    lambda *_a, k=key: self._refresh_default_highlight(k)
                )

    def _refresh_all_default_highlights(self) -> None:
        for k in self._widgets:
            self._refresh_default_highlight(k)

    # --- widget helpers ---------------------------------------------------

    @staticmethod
    def _build_label(meta):
        text = meta["display"]
        scope = str(meta.get("scope", "global")).strip().lower()
        scope_suffix = " [Profile]" if scope == "profile" else " [Global]"
        if meta["type"] is bool or meta["type"] is str:
            return f"{text}{scope_suffix}"
        unit = meta.get("unit", "")
        lo = meta.get("min", "")
        hi = meta.get("max", "")
        return f"{text}{scope_suffix}  ({lo}\u2013{hi} {unit})".rstrip()

    def _create_widget(self, key, meta):
        current = getattr(self._settings, key)
        if meta["type"] is bool:
            w = QCheckBox()
            w.setChecked(current)
        elif meta["type"] is str:
            display_val = str(current) if current else ""
            if key == "SESSION_SAVE_PATH" and not display_val and self._session_save_path_default:
                display_val = self._session_save_path_default
            w = PathEditWidget(display_val)
        elif meta["type"] is float:
            w = DoubleSpinBoxNoWheelUnlessFocused()
            w.setRange(meta["min"], meta["max"])
            w.setDecimals(meta.get("decimals", 1))
            w.setSingleStep(meta.get("step", 0.5))
            w.setValue(current)
        else:
            w = SpinBoxNoWheelUnlessFocused()
            w.setRange(meta["min"], meta["max"])
            w.setSingleStep(meta.get("step", 1))
            w.setValue(current)
        return w

    def _read_widgets(self):
        values = {}
        for key, widget in self._widgets.items():
            if REGISTRY[key]["type"] is bool:
                values[key] = widget.isChecked()
            elif REGISTRY[key]["type"] is str:
                values[key] = widget.value()
            else:
                values[key] = widget.value()
        return values

    def _normalize_for_persist(self, key: str, val: object) -> object:
        if key == "SESSION_SAVE_PATH" and self._session_save_path_default:
            if val == self._session_save_path_default:
                return ""
        return val

    def _normalized_read_widgets(self) -> dict[str, object]:
        return {k: self._normalize_for_persist(k, v) for k, v in self._read_widgets().items()}

    def _persist_equal(self, key: str, a: object, b: object) -> bool:
        t = REGISTRY[key]["type"]
        if t is float:
            try:
                return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-6)
            except (TypeError, ValueError):
                return False
        return a == b

    def _snapshots_equal(self, left: dict[str, object], right: dict[str, object]) -> bool:
        if set(left) != set(right):
            return False
        for k in left:
            if not self._persist_equal(k, left[k], right[k]):
                return False
        return True

    def _format_value_for_change_list(self, key: str, val: object) -> str:
        t = REGISTRY[key]["type"]
        if t is bool:
            return "On" if val else "Off"
        if t is int:
            try:
                return str(int(val))
            except (TypeError, ValueError):
                return str(val)
        if t is float:
            dec = int(REGISTRY[key].get("decimals", 1))
            try:
                return f"{float(val):.{dec}f}"
            except (TypeError, ValueError):
                return str(val)
        if t is str:
            s = str(val).strip() if val is not None else ""
            if not s:
                return "(empty — built-in default)"
            if len(s) > 72:
                return f"{s[:34]}…{s[-34:]}"
            return s
        return repr(val)

    def _summarize_changes(
        self, old: dict[str, object], new: dict[str, object]
    ) -> list[str]:
        lines: list[str] = []
        for key, meta in REGISTRY.items():
            if key not in old or key not in new:
                continue
            o, n = old[key], new[key]
            if self._persist_equal(key, o, n):
                continue
            disp = str(meta.get("display") or key)
            scope = str(meta.get("scope", "global")).strip().lower()
            tag = " [Profile]" if scope == "profile" else " [Global]"
            fo = self._format_value_for_change_list(key, o)
            fn = self._format_value_for_change_list(key, n)
            lines.append(f"{disp}{tag}: {fo} → {fn}")
        return lines

    def _write_widgets(self):
        for key, widget in self._widgets.items():
            val = getattr(self._settings, key)
            if REGISTRY[key]["type"] is bool:
                widget.setChecked(val)
            elif REGISTRY[key]["type"] is str:
                display_val = str(val) if val else ""
                if key == "SESSION_SAVE_PATH" and not display_val and self._session_save_path_default:
                    display_val = self._session_save_path_default
                widget.setValue(display_val)
            else:
                widget.setValue(val)

    def _apply_snapshot_to_widgets(self, snap: dict[str, object]) -> None:
        """Restore controls from a normalized snapshot (e.g. session baseline)."""
        for key, raw in snap.items():
            widget = self._widgets.get(key)
            if widget is None:
                continue
            t = REGISTRY[key]["type"]
            if t is bool:
                widget.setChecked(bool(raw))
            elif t is str:
                display_val = str(raw) if raw else ""
                if key == "SESSION_SAVE_PATH" and not display_val and self._session_save_path_default:
                    display_val = self._session_save_path_default
                widget.setValue(display_val)
            elif t is float:
                widget.setValue(float(raw))
            else:
                widget.setValue(int(raw))

    # --- button handlers --------------------------------------------------

    def _persist_settings_and_accept(self) -> None:
        values = self._read_widgets()
        scoped_profile = profile_scoped_keys()
        for key, val in values.items():
            val = self._normalize_for_persist(key, val)
            setattr(self._settings, key, val)
            if (
                key in scoped_profile
                and self._profile_store is not None
                and self._profile_id
            ):
                self._profile_store.set_profile_pref(
                    self._profile_id,
                    f"setting:{key}",
                    str(val),
                )
        if (
            self._timeline_default_combo is not None
            and self._profile_store is not None
            and self._profile_id
        ):
            selected = str(self._timeline_default_combo.currentText()).strip()
            if selected not in TIMELINE_SPAN_LABELS:
                selected = TIMELINE_SPAN_DEFAULT_LABEL
            self._profile_store.set_profile_pref(
                self._profile_id,
                TIMELINE_PREF_MAIN_SPAN,
                selected,
            )
        self._settings.save(exclude_keys=scoped_profile)
        self.accept()

    def _save_and_close(self) -> None:
        proposed = self._normalized_read_widgets()
        baseline = self._baseline_values
        if baseline is not None and not self._snapshots_equal(baseline, proposed):
            lines = self._summarize_changes(baseline, proposed)
            msg = QMessageBox(self)
            msg.setWindowTitle("Confirm changes?")
            msg.setIcon(QMessageBox.Question)
            msg.setText(
                "You changed one or more settings. Accept these changes and close the dialog?"
            )
            bullet = "\n".join(f"• {ln}" for ln in lines)
            foot = (
                "\n\nCancel returns to Settings without saving. "
                "Restore Previous puts all fields back to when you opened Settings "
                "(not the same as the Restore Defaults button on the main screen). "
                "Accept writes values, closes this dialog, and applies them in the app "
                "(most options take effect immediately; e.g. session save path is used on the "
                "next Stop & Save)."
            )
            if len(lines) <= 16:
                msg.setInformativeText(bullet + foot)
            else:
                msg.setInformativeText(
                    f"{len(lines)} settings will change.{foot}\n\n"
                    "Use “Show Details…” for the full list."
                )
                msg.setDetailedText(bullet)
            restore_btn = msg.addButton(
                "Restore Previous", QMessageBox.ButtonRole.ActionRole
            )
            cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            accept_btn = msg.addButton("Accept", QMessageBox.ButtonRole.AcceptRole)
            msg.setDefaultButton(accept_btn)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == cancel_btn:
                return
            if clicked == restore_btn:
                if self._baseline_values is not None:
                    self._apply_snapshot_to_widgets(self._baseline_values)
                    self._refresh_all_default_highlights()
                return
            if clicked != accept_btn:
                return
        self._persist_settings_and_accept()

    def _restore_defaults(self):
        reply = QMessageBox.question(
            self,
            "Restore Defaults",
            "Reset all settings to their default values?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._settings.reset_defaults()
            self._write_widgets()
            if self._timeline_default_combo is not None:
                self._timeline_default_combo.setCurrentText(TIMELINE_SPAN_DEFAULT_LABEL)
            self._refresh_all_default_highlights()
            self._baseline_values = self._normalized_read_widgets()

    def _toggle_advanced(self, show: bool):
        SettingsDialog._show_advanced = show
        self._refresh_section_visibility()

    def _refresh_phone_bridge_ecg_prompt_reset_button(self) -> None:
        btn = self._phone_bridge_ecg_prompt_reset_btn
        if btn is None or self._profile_store is None:
            return
        has = bool(self._profile_store.get_linux_phone_bridge_ecg_prompt_choice())
        btn.setEnabled(has)

    def _on_reset_phone_bridge_ecg_prompt(self) -> None:
        if self._profile_store is None:
            return
        if not self._profile_store.get_linux_phone_bridge_ecg_prompt_choice():
            return
        self._profile_store.set_linux_phone_bridge_ecg_prompt_choice("")
        self._refresh_phone_bridge_ecg_prompt_reset_button()
        QMessageBox.information(
            self,
            "Phone Bridge ECG prompt",
            "The saved \"don't ask again\" choice was cleared. "
            "The next Linux Phone Bridge connection can show the ECG/QTc prompt again.",
        )

    def _apply_scope_filter(self, profile_only: bool):
        if profile_only:
            self._advanced_prev_checked = bool(self._advanced_toggle.isChecked())
            self._advanced_toggle.blockSignals(True)
            self._advanced_toggle.setChecked(False)
            self._advanced_toggle.blockSignals(False)
            self._advanced_toggle.setEnabled(False)
            self._advanced_toggle.setToolTip(
                "Engineering settings are global. Turn off "
                "'Show only this profile settings' to view them."
            )
        else:
            self._advanced_toggle.setEnabled(True)
            self._advanced_toggle.setToolTip("Show or hide advanced engineering settings.")
            self._advanced_toggle.blockSignals(True)
            self._advanced_toggle.setChecked(bool(self._advanced_prev_checked))
            self._advanced_toggle.blockSignals(False)
            self._toggle_advanced(self._advanced_toggle.isChecked())
        for key, widget in self._widgets.items():
            label = self._labels.get(key)
            visible = (not profile_only) or (setting_scope(key) == "profile")
            widget.setVisible(visible)
            if label is not None:
                label.setVisible(visible)
        g_vis = not profile_only
        if self._phone_bridge_ecg_prompt_reset_label is not None:
            self._phone_bridge_ecg_prompt_reset_label.setVisible(g_vis)
        if self._phone_bridge_ecg_prompt_reset_btn is not None:
            self._phone_bridge_ecg_prompt_reset_btn.parentWidget().setVisible(g_vis)
        self._refresh_section_visibility()

    def _refresh_section_visibility(self):
        show_advanced = bool(self._advanced_toggle.isChecked())
        profile_only = bool(self._scope_filter_toggle.isChecked())
        for group, keys, is_advanced in self._section_groups:
            if is_advanced and not show_advanced:
                group.setVisible(False)
                continue
            if profile_only and not any(setting_scope(k) == "profile" for k in keys):
                group.setVisible(False)
                continue
            group.setVisible(True)

    def _open_annotation_manager(self):
        dlg = AnnotationEditorDialog(self._settings, parent=self)
        dlg.exec()

    def _copy_data_root_path(self):
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        if clipboard is None:
            return
        path_text = self._data_root_display.text().strip()
        if not path_text:
            return
        clipboard.setText(path_text)

    def _refresh_data_migration_ui(self):
        active = self._active_data_root.resolve()
        legacy = self._legacy_data_root.resolve()
        recommended = self._recommended_data_root.resolve()
        env_override = os.environ.get(APP_DATA_ENV_VAR, "").strip()

        # Only offer one-click migration for Windows legacy -> LocalAppData.
        can_offer = (
            os.name == "nt"
            and not env_override
            and active == legacy
            and recommended != legacy
            and legacy.exists()
            and not recommended.exists()
        )

        self._migrate_data_root_btn.setEnabled(can_offer)
        if can_offer:
            self._migrate_data_root_btn.setToolTip(
                f"Copy data from {legacy} to {recommended}. "
                "Restart the app after migration to switch paths."
            )
            self._migrate_data_root_hint.setText(
                "Recommended for dual-boot setups. Copies your data to a Windows-local path "
                "and keeps the current folder as backup until you confirm the switch."
            )
            return

        self._migrate_data_root_btn.setToolTip(
            "Migration unavailable in the current configuration."
        )
        if env_override:
            self._migrate_data_root_hint.setText(
                f"Migration disabled because {APP_DATA_ENV_VAR} is set in this environment."
            )
        elif os.name != "nt":
            self._migrate_data_root_hint.setText(
                "No migration needed on this platform. Linux uses the XDG data path by default."
            )
        elif active == recommended:
            self._migrate_data_root_hint.setText(
                f"You are already using the recommended location: {recommended}"
            )
        elif active == legacy and recommended.exists():
            self._migrate_data_root_hint.setText(
                f"Recommended location already exists: {recommended}. Restart to switch if needed."
            )
        else:
            self._migrate_data_root_hint.setText(
                "Migration is not available for the current data-path state."
            )

    def _migrate_data_root(self):
        self._refresh_data_migration_ui()
        if not self._migrate_data_root_btn.isEnabled():
            return

        source = self._legacy_data_root
        destination = self._recommended_data_root
        reply = QMessageBox.question(
            self,
            "Move Data to Recommended Location",
            (
                "Copy app data to the recommended Windows location now?\n\n"
                f"Source:\n{source}\n\n"
                f"Destination:\n{destination}\n\n"
                "Notes:\n"
                "- Source data is kept as a backup.\n"
                "- Restart the app after migration to use the new location."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination, dirs_exist_ok=False)
        except Exception as exc:
            try:
                if destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
            except Exception:
                pass
            QMessageBox.warning(
                self,
                "Data Migration Failed",
                f"Could not copy data to the recommended location:\n{exc}",
            )
            self._refresh_data_migration_ui()
            return

        self._refresh_data_migration_ui()
        QMessageBox.information(
            self,
            "Data Migration Complete",
            (
                "Data was copied successfully.\n\n"
                f"New location on next launch:\n{destination}\n\n"
                "Please restart Hertz & Hearts now. "
                "After restart, verify Session History and reports, then remove the old folder if desired."
            ),
        )

    def _queue_disclaimer_reset(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Queue Disclaimer Reset")
        msg.setText("Queue a reset for startup disclaimer prompts.")
        msg.setInformativeText(
            "The reset will be applied only when you click Save and Close."
        )
        active_btn = msg.addButton("Active User", QMessageBox.ButtonRole.AcceptRole)
        all_btn = msg.addButton("All Users", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton(QMessageBox.Cancel)
        msg.setDefaultButton(active_btn)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == cancel_btn:
            return
        if clicked == all_btn:
            self._pending_disclaimer_reset = "all"
            self._update_reset_disclaimer_button_ui()
            return
        self._pending_disclaimer_reset = "active"
        self._update_reset_disclaimer_button_ui()

    def _update_reset_disclaimer_button_ui(self):
        if self._pending_disclaimer_reset == "all":
            self._reset_disclaimer_btn.setText("Reset Disclaimer… (All Queued)")
            self._reset_disclaimer_btn.setToolTip(
                "Queued: reset disclaimer prompts for all users on Save and Close."
            )
        elif self._pending_disclaimer_reset == "active":
            self._reset_disclaimer_btn.setText("Reset Disclaimer… (Queued)")
            self._reset_disclaimer_btn.setToolTip(
                "Queued: reset disclaimer prompt for the active user on Save and Close."
            )
        else:
            self._reset_disclaimer_btn.setText("Reset Disclaimer Prompt…")
            self._reset_disclaimer_btn.setToolTip(
                "Re-enable startup disclaimer prompts that were hidden via 'Don't show again'."
            )

    def get_pending_disclaimer_reset(self) -> str:
        return self._pending_disclaimer_reset

    # --- lifecycle --------------------------------------------------------

    def showEvent(self, event):
        self._write_widgets()
        self._refresh_all_default_highlights()
        self._baseline_values = self._normalized_read_widgets()
        super().showEvent(event)
