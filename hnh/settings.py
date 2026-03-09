"""
Runtime settings manager with persistent overrides and a GUI dialog.

Defaults come from config.py.  User changes are saved to a small JSON
file in the user's home directory so they survive app restarts.
"""
import json
from collections import OrderedDict
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QLabel,
    QMessageBox, QScrollArea, QWidget, QLineEdit, QListWidget,
    QInputDialog, QAbstractItemView, QFileDialog,
)
from PySide6.QtCore import Qt

from hnh import config as _defaults

SETTINGS_FILE = Path.home() / ".hnh_settings.json"

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
            "EDF+ file containing derived HR and RMSSD trend channels."
        ),
        "type": bool,
        "section": "Session Timing",
        "scope": "profile",
    }),
    ("SESSION_SAVE_PATH", {
        "display": "Session Save Path",
        "tooltip": (
            "Folder where finalized sessions (CSV, report, EDF+) are copied. "
            "Leave empty to use Hertz-and-Hearts/Sessions/{profile} under your home folder."
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

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit()
        self._edit.setText(current)
        layout.addWidget(self._edit)
        browse = QPushButton("Browse…")
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
        self._advanced_groups: list[QGroupBox] = []
        self._section_groups: list[tuple[QGroupBox, list[str], bool]] = []
        self._pending_disclaimer_reset = "none"
        self._advanced_prev_checked = SettingsDialog._show_advanced

        self.setWindowTitle("Hertz & Hearts \u2014 Settings")
        self.setMinimumWidth(500)

        root = QVBoxLayout(self)

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
            section_keys: list[str] = []
            for key, meta in items:
                widget = self._create_widget(key, meta)
                label = QLabel(self._build_label(meta))
                label.setToolTip(meta["tooltip"])
                widget.setToolTip(meta["tooltip"])
                form.addRow(label, widget)
                self._widgets[key] = widget
                self._labels[key] = label
                section_keys.append(key)
            self._form_layout.addWidget(group)
            if is_advanced:
                group.setVisible(False)
                self._advanced_groups.append(group)
            self._section_groups.append((group, section_keys, is_advanced))

        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

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
            w = QDoubleSpinBox()
            w.setRange(meta["min"], meta["max"])
            w.setDecimals(meta.get("decimals", 1))
            w.setSingleStep(meta.get("step", 0.5))
            w.setValue(current)
        else:
            w = QSpinBox()
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

    # --- button handlers --------------------------------------------------

    def _save_and_close(self):
        values = self._read_widgets()
        scoped_profile = profile_scoped_keys()
        for key, val in values.items():
            if key == "SESSION_SAVE_PATH" and self._session_save_path_default:
                if val == self._session_save_path_default:
                    val = ""  # Store empty = use default
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
        self._settings.save(exclude_keys=scoped_profile)
        self.accept()

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

    def _toggle_advanced(self, show: bool):
        SettingsDialog._show_advanced = show
        self._refresh_section_visibility()

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
        super().showEvent(event)
