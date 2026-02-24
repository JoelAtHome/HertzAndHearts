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
    QInputDialog, QAbstractItemView,
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
    }),
    ("BASELINE_DURATION", {
        "display": "Baseline Duration",
        "tooltip": (
            "Seconds of stable data collected to establish the patient's "
            "resting HRV baseline.  Longer = more accurate baseline."
        ),
        "type": int, "min": 10, "max": 180, "unit": "seconds",
        "section": "Session Timing",
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
    }),
    ("DEVIATION_WINDOW", {
        "display": "Deviation Window",
        "tooltip": (
            "Number of recent heartbeats used to compute the rolling "
            "average for the adaptive signal quality check."
        ),
        "type": int, "min": 5, "max": 120, "unit": "beats",
        "section": "Signal Quality",
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
    }),
    ("QTC_MIN_VALID_BEATS", {
        "display": "QTc Min Valid Beats",
        "tooltip": (
            "Minimum number of valid QT/RR beats required before showing "
            "a session QTc value."
        ),
        "type": int, "min": 3, "max": 60, "unit": "beats",
        "section": "QTc Estimation",
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
        "advanced": True,
    }),
])


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

    def save(self):
        overrides = {}
        for key in REGISTRY:
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
            QMessageBox.warning(self, "Invalid Annotation", result)
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
            QMessageBox.warning(self, "Invalid Annotation", result)
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

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._widgets: dict[str, QCheckBox | QSpinBox | QDoubleSpinBox] = {}
        self._advanced_groups: list[QGroupBox] = []
        self._pending_disclaimer_reset = "none"

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
            for key, meta in items:
                widget = self._create_widget(key, meta)
                label = QLabel(self._build_label(meta))
                label.setToolTip(meta["tooltip"])
                widget.setToolTip(meta["tooltip"])
                form.addRow(label, widget)
                self._widgets[key] = widget
            self._form_layout.addWidget(group)
            if is_advanced:
                group.setVisible(False)
                self._advanced_groups.append(group)

        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

        # Advanced toggle
        self._advanced_toggle = QCheckBox("Show Advanced / Engineering Settings")
        self._advanced_toggle.setChecked(SettingsDialog._show_advanced)
        self._toggle_advanced(SettingsDialog._show_advanced)
        self._advanced_toggle.toggled.connect(self._toggle_advanced)
        root.addWidget(self._advanced_toggle)

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
        if meta["type"] is bool:
            return text
        unit = meta.get("unit", "")
        lo = meta.get("min", "")
        hi = meta.get("max", "")
        return f"{text}  ({lo}\u2013{hi} {unit})".rstrip()

    def _create_widget(self, key, meta):
        current = getattr(self._settings, key)
        if meta["type"] is bool:
            w = QCheckBox()
            w.setChecked(current)
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
            else:
                values[key] = widget.value()
        return values

    def _write_widgets(self):
        for key, widget in self._widgets.items():
            val = getattr(self._settings, key)
            if REGISTRY[key]["type"] is bool:
                widget.setChecked(val)
            else:
                widget.setValue(val)

    # --- button handlers --------------------------------------------------

    def _save_and_close(self):
        for key, val in self._read_widgets().items():
            setattr(self._settings, key, val)
        self._settings.save()
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
        for group in self._advanced_groups:
            group.setVisible(show)

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
