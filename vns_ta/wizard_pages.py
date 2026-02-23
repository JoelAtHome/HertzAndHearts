"""
Wizard page implementations for the VNS-TA protocol workflow.

Each page is a QWidget designed for ProtocolWizard.add_page().
Pages that gate advancement expose is_complete() and gate_changed.

Reusable styled components (AlertBanner, CardPanel) are defined here
and will be shared across all wizard pages.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QFrame, QScrollArea, QGridLayout, QLineEdit, QPushButton, QComboBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIntValidator


# ──────────────────────────────────────────────────────────────────────
#  Palette (matches the HTML mockup CSS variables)
# ──────────────────────────────────────────────────────────────────────

_BLUE = "#1a5276"
_GREEN = "#27ae60"
_YELLOW = "#f39c12"
_RED = "#c0392b"
_GRAY = "#7f8c8d"
_GRAY_DARK = "#2c3e50"
_GRAY_LIGHT = "#ecf0f1"
_PAGE_BG = "#f4f6f7"


# ──────────────────────────────────────────────────────────────────────
#  AlertBanner — styled message bar with icon
# ──────────────────────────────────────────────────────────────────────

class AlertBanner(QFrame):
    """Coloured alert strip matching the mockup's .alert component."""

    WARN = "warn"
    INFO = "info"
    DANGER = "danger"
    OK = "ok"

    _CFG = {
        "warn":   {"bg": "#fef9e7", "border": _YELLOW, "icon": "\u26A0"},
        "info":   {"bg": "#eaf2f8", "border": "#2980b9", "icon": "\u2139"},
        "danger": {"bg": "#fdedec", "border": _RED,     "icon": "\u26A0"},
        "ok":     {"bg": "#eafaf1", "border": _GREEN,   "icon": "\u2713"},
    }

    def __init__(self, text: str, variant: str = "info", parent=None):
        super().__init__(parent)
        c = self._CFG.get(variant, self._CFG["info"])

        self.setObjectName("AlertBanner")
        self.setStyleSheet(
            "#AlertBanner { background: %s; border-left: 4px solid %s; "
            "border-radius: 6px; }" % (c["bg"], c["border"])
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        icon = QLabel(c["icon"])
        icon.setFont(QFont("Segoe UI", 14))
        icon.setFixedWidth(24)
        icon.setAlignment(Qt.AlignTop)
        lay.addWidget(icon)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setFont(QFont("Segoe UI", 10))
        body.setStyleSheet("color: #333;")
        lay.addWidget(body, stretch=1)


# ──────────────────────────────────────────────────────────────────────
#  CardPanel — white card container with checklist support
# ──────────────────────────────────────────────────────────────────────

class CardPanel(QFrame):
    """Styled card matching the mockup's .card component."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._cbs: list[QCheckBox] = []

        self.setObjectName("CardPanel")
        self.setStyleSheet(
            "#CardPanel { background: white; border-radius: 8px; "
            "border: 1px solid #e5e8ea; }"
        )

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 14, 20, 14)
        self._lay.setSpacing(0)
        self._lay.setAlignment(Qt.AlignTop)

        if title:
            lbl = QLabel(title)
            lbl.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
            lbl.setStyleSheet("color: %s; padding-bottom: 8px;" % _GRAY_DARK)
            self._lay.addWidget(lbl)

    def add_checklist_item(self, text: str) -> QCheckBox:
        """Add a labelled checkbox and return it."""
        if self._cbs:
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet("background: %s;" % _GRAY_LIGHT)
            self._lay.addWidget(sep)

        cb = QCheckBox(text)
        cb.setFont(QFont("Segoe UI", 10))
        cb.setStyleSheet(
            "QCheckBox { padding: 8px 0; spacing: 10px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self._lay.addWidget(cb)
        self._cbs.append(cb)
        return cb

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._lay


# ──────────────────────────────────────────────────────────────────────
#  Page scaffold helper
# ──────────────────────────────────────────────────────────────────────

def _make_page_scaffold(parent: QWidget) -> QVBoxLayout:
    """Create the standard page layout: scroll area with gray background.

    Returns the inner content layout where page widgets should be added.
    """
    outer = QVBoxLayout(parent)
    outer.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setObjectName("wizardScroll")
    scroll.setStyleSheet(
        "#wizardScroll { background: %s; border: none; }" % _PAGE_BG
    )

    content = QWidget()
    content.setObjectName("wizardPageContent")
    content.setStyleSheet(
        "#wizardPageContent { background: %s; }" % _PAGE_BG
    )

    lay = QVBoxLayout(content)
    lay.setContentsMargins(32, 24, 32, 24)
    lay.setSpacing(16)

    scroll.setWidget(content)
    outer.addWidget(scroll)
    return lay


# ──────────────────────────────────────────────────────────────────────
#  Screen 0 — Pre-Session Checklist
# ──────────────────────────────────────────────────────────────────────

class PreSessionPage(QWidget):
    """Clinical clearances and patient positioning checks.

    All 8 checkboxes must be ticked before the wizard allows advancement.
    """

    gate_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checks: list[QCheckBox] = []

        lay = _make_page_scaffold(self)

        title = QLabel("Pre-Session Checklist")
        title.setFont(QFont("Segoe UI", 20, QFont.DemiBold))
        title.setStyleSheet("color: %s; background: transparent;" % _BLUE)
        lay.addWidget(title)

        sub = QLabel("Verify clinical clearances before proceeding.")
        sub.setStyleSheet(
            "color: %s; font-size: 14px; background: transparent;" % _GRAY
        )
        lay.addWidget(sub)

        lay.addWidget(AlertBanner(
            "All items must be confirmed before treatment can begin. "
            "If any item cannot be checked, consult the supervising "
            "physician.",
            AlertBanner.WARN,
        ))

        # --- Two-column card row ---
        columns = QGridLayout()
        columns.setSpacing(16)
        columns.setColumnStretch(0, 1)
        columns.setColumnStretch(1, 1)

        c1 = CardPanel("Clinical Clearances")
        self._add(c1, "QTc interval < 470 ms on most recent ECG")
        self._add(
            c1,
            "Clozapine + norclozapine blood levels reviewed "
            "(not near toxic range)",
        )
        self._add(c1, "Patient BFCRS score recorded (Target < 3)")
        self._add(c1, "Time of last Ativan dose recorded")
        self._add(c1, "Time of last Clozapine dose recorded")
        columns.addWidget(c1, 0, 0)

        c2 = CardPanel("Patient Positioning")
        self._add(c2, "Patient seated at 90\u00B0 upright")
        self._add(
            c2, "Suction device available and tested (aspiration safety)"
        )
        self._add(
            c2, "Emergency power-down procedure reviewed with staff"
        )
        columns.addWidget(c2, 0, 1)

        lay.addLayout(columns)
        lay.addStretch()

    def _add(self, card: CardPanel, text: str):
        cb = card.add_checklist_item(text)
        cb.stateChanged.connect(lambda _: self.gate_changed.emit())
        self._checks.append(cb)

    def is_complete(self) -> bool:
        """True when every checklist item is ticked."""
        return all(cb.isChecked() for cb in self._checks)


# ──────────────────────────────────────────────────────────────────────
#  Modality definitions (shared with downstream pages)
# ──────────────────────────────────────────────────────────────────────

MODALITIES = [
    {
        "key": "A",
        "title": "taVNS Only",
        "subtitle": "Priority 1 \u2014 Autonomic Safety Ground",
        "desc": (
            "The foundational safety layer. Best suited for a gentler "
            "approach when the patient\u2019s tolerance for additional "
            "stimulation is uncertain, or when a lighter sensory load "
            "is preferred."
        ),
        "channels": [1],
    },
    {
        "key": "B",
        "title": "taVNS + MNS",
        "subtitle": "Priority 2 \u2014 Bottom-Up Motor Anchor",
        "desc": (
            "Use when the patient is \u201Cfrozen\u201D or posturing. "
            "MNS provides a rhythmic 10 Hz pulse that reconnects the "
            "motor cortex to body awareness."
        ),
        "channels": [1, 2],
    },
    {
        "key": "C",
        "title": "taVNS + TNS",
        "subtitle": "Priority 3 \u2014 Top-Down Cortical Reset",
        "desc": (
            "Use when the patient is stable but \u201Cfoggy\u201D from "
            "medication or illness. TNS uses a high-frequency sweep to "
            "increase cortical signal through the Ativan sedation."
        ),
        "channels": [1, 3],
    },
    {
        "key": "D",
        "title": "Full Stack \u2014 All Three: taVNS + MNS + TNS",
        "subtitle": (
            "(Recommended protocol if tolerated) "
            "\u2014 Complete Neuro-Reset"
        ),
        "desc": (
            "Simultaneously targets all three primary nervous system "
            "pathways. Use when the patient can tolerate the full "
            "sensory load and maximum therapeutic benefit is desired."
        ),
        "channels": [1, 2, 3],
    },
]

_CH_COLORS = {1: "#2980b9", 2: "#27ae60", 3: "#8e44ad"}


def _make_channel_badge(ch: int) -> QLabel:
    """Small coloured pill showing a channel number."""
    lbl = QLabel("CH %d" % ch)
    lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
    lbl.setStyleSheet(
        "background: %s; color: white; padding: 3px 10px; "
        "border-radius: 4px;" % _CH_COLORS.get(ch, _GRAY)
    )
    return lbl


# ──────────────────────────────────────────────────────────────────────
#  ModalityCard — clickable radio-style selection card
# ──────────────────────────────────────────────────────────────────────

class ModalityCard(QFrame):
    """One of the four treatment modality options."""

    clicked = Signal(str)

    def __init__(self, key: str, title: str, subtitle: str,
                 desc: str, channels: list, parent=None):
        super().__init__(parent)
        self._key = key
        self.setObjectName("ModalityCard")
        self.setCursor(Qt.PointingHandCursor)
        self._apply_border(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(6)

        # --- header: radio dot + title / subtitle ---
        header = QHBoxLayout()
        header.setSpacing(10)

        self._radio = QLabel()
        self._radio.setFixedSize(20, 20)
        self._radio.setAlignment(Qt.AlignCenter)
        self._update_radio(False)
        header.addWidget(self._radio, alignment=Qt.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel(title)
        t.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        t.setStyleSheet("color: %s;" % _GRAY_DARK)
        t.setWordWrap(True)
        titles.addWidget(t)
        s = QLabel(subtitle)
        s.setFont(QFont("Segoe UI", 9))
        s.setStyleSheet("color: %s;" % _GRAY)
        s.setWordWrap(True)
        titles.addWidget(s)
        header.addLayout(titles, stretch=1)
        root.addLayout(header)

        # --- description ---
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setFont(QFont("Segoe UI", 9))
        d.setStyleSheet("color: #555;")
        root.addWidget(d)

        # --- channel badges ---
        badges = QHBoxLayout()
        badges.setSpacing(6)
        for ch in channels:
            badges.addWidget(_make_channel_badge(ch))
        badges.addStretch()
        root.addLayout(badges)

    # ── visual state ─────────────────────────────────────────────────

    def set_selected(self, selected: bool):
        self._apply_border(selected)
        self._update_radio(selected)

    def _apply_border(self, selected: bool):
        if selected:
            self.setStyleSheet(
                "#ModalityCard { background: #eaf2f8; border-radius: 8px; "
                "border: 3px solid %s; }" % _BLUE
            )
        else:
            self.setStyleSheet(
                "#ModalityCard { background: white; border-radius: 8px; "
                "border: 3px solid transparent; } "
                "#ModalityCard:hover { border-color: #2980b9; }"
            )

    def _update_radio(self, selected: bool):
        if selected:
            self._radio.setStyleSheet(
                "background: %s; border: 2px solid %s; border-radius: 10px;"
                % (_BLUE, _BLUE)
            )
        else:
            self._radio.setStyleSheet(
                "background: white; border: 2px solid %s; "
                "border-radius: 10px;" % _GRAY
            )

    def mousePressEvent(self, event):
        self.clicked.emit(self._key)
        super().mousePressEvent(event)


# ──────────────────────────────────────────────────────────────────────
#  Screen 1 — Modality Selection
# ──────────────────────────────────────────────────────────────────────

class ModalitySelectionPage(QWidget):
    """Treatment modality picker — four radio-style cards in a 2x2 grid.

    The selected modality key and channel list are available via
    selected_modality and selected_channels for downstream pages.
    """

    gate_changed = Signal()
    modality_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected: str | None = None
        self._cards: dict[str, ModalityCard] = {}

        lay = _make_page_scaffold(self)

        title = QLabel("Treatment Modality Selection")
        title.setFont(QFont("Segoe UI", 20, QFont.DemiBold))
        title.setStyleSheet("color: %s; background: transparent;" % _BLUE)
        lay.addWidget(title)

        sub = QLabel(
            "Select the stimulation configuration based on the "
            "patient\u2019s current clinical presentation."
        )
        sub.setStyleSheet(
            "color: %s; font-size: 14px; background: transparent;" % _GRAY
        )
        lay.addWidget(sub)

        lay.addWidget(AlertBanner(
            "taVNS (Channel 1) is the essential safety base layer and is "
            "<b>always included</b> in every modality. Select the "
            "additional channels based on today\u2019s clinical need.",
            AlertBanner.INFO,
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]

        for pos, m in zip(positions, MODALITIES):
            card = ModalityCard(
                m["key"], m["title"], m["subtitle"],
                m["desc"], m["channels"],
            )
            card.clicked.connect(self._on_select)
            grid.addWidget(card, *pos)
            self._cards[m["key"]] = card

        lay.addLayout(grid)
        lay.addStretch()

    def _on_select(self, key: str):
        self._selected = key
        for k, card in self._cards.items():
            card.set_selected(k == key)
        self.gate_changed.emit()
        self.modality_changed.emit(key)

    @property
    def selected_modality(self) -> str | None:
        return self._selected

    @property
    def selected_channels(self) -> list[int]:
        if self._selected:
            for m in MODALITIES:
                if m["key"] == self._selected:
                    return m["channels"]
        return []

    def is_complete(self) -> bool:
        return self._selected is not None


# ──────────────────────────────────────────────────────────────────────
#  Screen 2 — Sensor Placement and Monitoring
# ──────────────────────────────────────────────────────────────────────

class SensorPlacementPage(QWidget):
    """Pulse-ox, Polar H10 placement checklists and BLE connection controls.

    Public widget references (scan_btn, device_menu, connect_btn,
    disconnect_btn) are wired to the scanner/sensor by the View.
    """

    gate_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checks: list[QCheckBox] = []

        lay = _make_page_scaffold(self)

        title = QLabel("Sensor Placement and Monitoring")
        title.setFont(QFont("Segoe UI", 20, QFont.DemiBold))
        title.setStyleSheet("color: %s; background: transparent;" % _BLUE)
        lay.addWidget(title)

        sub = QLabel(
            "Attach physiological monitoring sensors to the "
            "patient and connect to VNS-TA."
        )
        sub.setStyleSheet(
            "color: %s; font-size: 14px; background: transparent;" % _GRAY
        )
        lay.addWidget(sub)

        # ── Pulse Oximeter ────────────────────────────────────────────
        ox_card = CardPanel("Pulse Oximeter")
        self._add(ox_card, "Place pulse oximeter on patient\u2019s finger")

        # SpO2 input row (auto-verified)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: %s;" % _GRAY_LIGHT)
        ox_card.content_layout.addWidget(sep)

        spo2_row = QHBoxLayout()
        spo2_row.setSpacing(8)

        self._spo2_cb = QCheckBox()
        self._spo2_cb.setEnabled(False)
        self._spo2_cb.setStyleSheet(
            "QCheckBox { padding: 8px 0; spacing: 10px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self._spo2_badge = QLabel("\u2713 AUTO-VERIFIED:")
        self._spo2_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._spo2_badge.setStyleSheet("color: %s;" % _GREEN)
        self._spo2_badge.setVisible(False)
        spo2_lbl = QLabel("SpO\u2082 reading:")
        spo2_lbl.setFont(QFont("Segoe UI", 10))
        self._spo2_input = QLineEdit()
        self._spo2_input.setPlaceholderText("--")
        self._spo2_input.setFixedWidth(44)
        self._spo2_input.setAlignment(Qt.AlignCenter)
        self._spo2_input.setFont(QFont("Segoe UI", 10))
        self._spo2_input.setValidator(QIntValidator(0, 100))
        self._spo2_input.setStyleSheet(
            "QLineEdit { border: 1px solid #ccc; border-radius: 4px; "
            "padding: 4px; }"
        )
        spo2_pct = QLabel("%")
        spo2_pct.setFont(QFont("Segoe UI", 10))
        spo2_range = QLabel("(must be 95\u2013100)")
        spo2_range.setFont(QFont("Segoe UI", 10))
        spo2_range.setStyleSheet("color: %s;" % _GRAY)

        spo2_row.addWidget(self._spo2_cb)
        spo2_row.addWidget(self._spo2_badge)
        spo2_row.addWidget(spo2_lbl)
        spo2_row.addWidget(self._spo2_input)
        spo2_row.addWidget(spo2_pct)
        spo2_row.addWidget(spo2_range)
        spo2_row.addStretch()
        ox_card.content_layout.addLayout(spo2_row)

        self._spo2_input.textChanged.connect(self._on_spo2_changed)

        # ── Polar H10 Heart Rate Sensor ───────────────────────────────
        polar_card = CardPanel("Polar H10 Heart Rate Sensor")
        self._add(
            polar_card,
            "Snap sensor unit onto chest strap if not already in place",
        )
        self._add(
            polar_card,
            "Moisten electrode pads on the Polar H10 strap "
            "with gel (preferred) or water",
        )
        self._add(
            polar_card,
            "Place strap snugly around patient\u2019s chest, "
            "just below the pectoral muscles",
        )

        # Two-column row: Pulse Ox (left) | Polar H10 (right)
        columns = QGridLayout()
        columns.setSpacing(16)
        columns.setColumnStretch(0, 1)
        columns.setColumnStretch(1, 1)
        columns.addWidget(ox_card, 0, 0)
        columns.addWidget(polar_card, 0, 1)
        lay.addLayout(columns)

        # ── Connect to Polar H10 ──────────────────────────────────────
        ble_card = CardPanel("Connect to Polar H10 Heart Monitor")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        self.scan_btn.setStyleSheet(
            "QPushButton { background: %s; color: white; border: none; "
            "border-radius: 5px; padding: 8px 18px; "
            "font-size: 13px; font-weight: 600; }" % _BLUE
        )
        self.device_menu = QComboBox()
        self.device_menu.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.device_menu.setMinimumWidth(180)
        self.device_menu.setMaximumWidth(340)
        self.device_menu.setStyleSheet(
            "QComboBox { padding: 7px 12px; border: 1px solid #ccc; "
            "border-radius: 5px; font-size: 13px; }"
        )
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        self.connect_btn.setStyleSheet(
            "QPushButton { background: %s; color: white; border: none; "
            "border-radius: 5px; padding: 8px 18px; "
            "font-size: 13px; font-weight: 600; } "
            "QPushButton:disabled { background: #bdc3c7; color: #95a5a6; }"
            % _GREEN
        )
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setCursor(Qt.PointingHandCursor)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setStyleSheet(
            "QPushButton { background: %s; color: %s; border: none; "
            "border-radius: 5px; padding: 8px 18px; "
            "font-size: 13px; font-weight: 600; } "
            "QPushButton:disabled { background: #e8e8e8; color: #bdc3c7; }"
            % (_GRAY_LIGHT, _GRAY_DARK)
        )

        btn_row.addWidget(self.scan_btn)
        btn_row.addWidget(self.device_menu)
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.disconnect_btn)
        btn_row.addStretch()
        ble_card.content_layout.addLayout(btn_row)

        # Status indicators
        status_row = QHBoxLayout()
        status_row.setSpacing(16)
        self.ble_status_label = QLabel("\u25CF Not Connected")
        self.ble_status_label.setFont(QFont("Segoe UI", 10))
        self.ble_status_label.setStyleSheet("color: %s;" % _GRAY)
        self.ble_signal_label = QLabel()
        self.ble_signal_label.setFont(QFont("Segoe UI", 10))
        self.ble_signal_label.setVisible(False)
        self.ble_hr_label = QLabel()
        self.ble_hr_label.setFont(QFont("Segoe UI", 10))
        self.ble_hr_label.setVisible(False)
        status_row.addWidget(self.ble_status_label)
        status_row.addWidget(self.ble_signal_label)
        status_row.addWidget(self.ble_hr_label)
        status_row.addStretch()
        ble_card.content_layout.addLayout(status_row)

        # Auto-verified BLE checkbox
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: %s;" % _GRAY_LIGHT)
        ble_card.content_layout.addWidget(sep2)

        ble_auto = QHBoxLayout()
        ble_auto.setSpacing(6)
        self._ble_cb = QCheckBox()
        self._ble_cb.setEnabled(False)
        self._ble_cb.setStyleSheet(
            "QCheckBox { padding: 8px 0; spacing: 10px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self._ble_badge = QLabel("\u2713 AUTO-VERIFIED:")
        self._ble_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._ble_badge.setStyleSheet("color: %s;" % _GREEN)
        self._ble_badge.setVisible(False)
        self._ble_text = QLabel(
            "Sensor is connected and showing live heart rate"
        )
        self._ble_text.setFont(QFont("Segoe UI", 10))
        self._ble_text.setStyleSheet("color: %s;" % _GRAY)
        ble_auto.addWidget(self._ble_cb)
        ble_auto.addWidget(self._ble_badge)
        ble_auto.addWidget(self._ble_text)
        ble_auto.addStretch()
        ble_card.content_layout.addLayout(ble_auto)

        lay.addWidget(ble_card)

        # ── Info alert ────────────────────────────────────────────────
        lay.addWidget(AlertBanner(
            "Settling and baseline calibration will proceed automatically "
            "once the sensor is connected. This runs in the background "
            "as you continue through the next steps.",
            AlertBanner.INFO,
        ))

        lay.addStretch()

    # ── helpers ───────────────────────────────────────────────────────

    def _add(self, card: CardPanel, text: str):
        cb = card.add_checklist_item(text)
        cb.stateChanged.connect(lambda _: self.gate_changed.emit())
        self._checks.append(cb)

    def _on_spo2_changed(self, text: str):
        try:
            valid = 95 <= int(text) <= 100
        except ValueError:
            valid = False
        self._spo2_cb.setChecked(valid)
        self._spo2_badge.setVisible(valid)
        self.gate_changed.emit()

    def set_ble_connected(self, connected: bool):
        """Called by the View when BLE connection state changes."""
        self._ble_cb.setChecked(connected)
        self._ble_badge.setVisible(connected)
        self._ble_text.setStyleSheet(
            "color: %s;" % (_GRAY_DARK if connected else _GRAY)
        )
        if connected:
            self.ble_status_label.setText("\u25CF Connected")
            self.ble_status_label.setStyleSheet("color: %s;" % _GREEN)
        else:
            self.ble_status_label.setText("\u25CF Not Connected")
            self.ble_status_label.setStyleSheet("color: %s;" % _GRAY)
            self.ble_signal_label.setVisible(False)
            self.ble_hr_label.setVisible(False)
        self.gate_changed.emit()

    def update_hr_display(self, hr: float):
        """Update the live HR readout in the BLE status row."""
        self.ble_hr_label.setText("HR: <b>%d</b> BPM" % int(hr))
        self.ble_hr_label.setVisible(True)
        self.ble_signal_label.setText("Signal: <b>GOOD</b>")
        self.ble_signal_label.setStyleSheet("color: %s;" % _GREEN)
        self.ble_signal_label.setVisible(True)

    @property
    def spo2_value(self) -> int | None:
        """Return the entered SpO2 or None if not yet entered."""
        try:
            return int(self._spo2_input.text())
        except ValueError:
            return None

    def is_complete(self) -> bool:
        manual_ok = all(cb.isChecked() for cb in self._checks)
        return manual_ok and self._spo2_cb.isChecked() and self._ble_cb.isChecked()


# ──────────────────────────────────────────────────────────────────────
#  Electrode placement data (per-channel instructions)
# ──────────────────────────────────────────────────────────────────────

ELECTRODE_DATA = [
    {
        "ch": 1,
        "title": "taVNS \u2014 Left Ear + Mastoid",
        "cathode": (
            "Place on the <b>Cymba Conchae</b> (recessed valley above "
            "the ear canal) using an adhesive patch electrode, or clip "
            "to the <b>inner Tragus</b> with conductive electrode gel. "
            "A custom ear mold with gel may also be used."
        ),
        "anode": (
            "Place a 2.5\u20135 cm patch on the <b>Mastoid Process</b> "
            "(bony bump behind the ear). If facial twitching occurs "
            "after the channel is activated, this electrode should be "
            "moved further back."
        ),
    },
    {
        "ch": 2,
        "title": "MNS \u2014 Right Wrist",
        "cathode": (
            "Place on the <b>inner (volar) wrist</b>, 5\u20137 cm from "
            "the wrist crease, between the two prominent tendons."
        ),
        "anode": (
            "Place 3\u20135 cm further up the arm toward the inner "
            "elbow, following the line of the median nerve."
        ),
    },
    {
        "ch": 3,
        "title": "TNS \u2014 Forehead",
        "cathode": (
            "Place <b>2 cm above the midpoint of the eyebrow</b> "
            "(supraorbital nerve exit point)."
        ),
        "anode": (
            "Place higher on the forehead near the <b>hairline</b>, "
            "or laterally toward the temple on the same side."
        ),
    },
]

_LEAD_BLACK = "#2c3e50"
_LEAD_RED = "#e74c3c"


def _make_inline_step(step_num: int, lead_text: str,
                      lead_color: str, desc: str) -> QWidget:
    """Compact inline cathode/anode placement row (Option D style)."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 4, 0, 4)
    row.setSpacing(8)

    badge = QLabel(str(step_num))
    badge.setFixedSize(22, 22)
    badge.setAlignment(Qt.AlignCenter)
    badge.setFont(QFont("Segoe UI", 9, QFont.Bold))
    badge.setStyleSheet(
        "background: %s; color: white; border-radius: 11px;" % _BLUE
    )
    row.addWidget(badge, 0, Qt.AlignTop)

    lead = QLabel(lead_text)
    lead.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
    lead.setStyleSheet(
        "background: %s; color: white; padding: 2px 8px; "
        "border-radius: 3px;" % lead_color
    )
    row.addWidget(lead, 0, Qt.AlignTop)

    body = QLabel(desc)
    body.setWordWrap(True)
    body.setFont(QFont("Segoe UI", 9))
    body.setStyleSheet("color: #555;")
    row.addWidget(body, 1)

    return w


# ──────────────────────────────────────────────────────────────────────
#  Screen 3 — Electrode Placement (dynamic per modality)
# ──────────────────────────────────────────────────────────────────────

class ElectrodePlacementPage(QWidget):
    """Per-channel electrode placement with compact inline steps.

    Cards are arranged in a responsive grid:
      1 channel  → centered
      2 channels → side-by-side
      3 channels → 2 top + 1 centered below

    Uses a 4-column QGridLayout so every card spans 2 columns (= 50%)
    and the third card spans the middle two columns to center it.
    """

    gate_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_channels: list[int] = [1]
        self._channel_cards: dict[int, CardPanel] = {}
        self._channel_cbs: dict[int, QCheckBox] = {}

        lay = _make_page_scaffold(self)

        title = QLabel("Electrode Placement")
        title.setFont(QFont("Segoe UI", 20, QFont.DemiBold))
        title.setStyleSheet("color: %s; background: transparent;" % _BLUE)
        lay.addWidget(title)

        sub = QLabel(
            "Place and verify electrodes for the selected channels "
            "before powering on the EX4."
        )
        sub.setStyleSheet(
            "color: %s; font-size: 14px; background: transparent;" % _GRAY
        )
        lay.addWidget(sub)

        lay.addWidget(AlertBanner(
            "Clean all skin contact surfaces with an alcohol wipe "
            "before applying electrodes. Ensure 100% surface contact "
            "to prevent edge-loading burns.",
            AlertBanner.WARN,
        ))

        for data in ELECTRODE_DATA:
            self._build_channel_card(data)

        self._cards_grid = QGridLayout()
        self._cards_grid.setHorizontalSpacing(16)
        self._cards_grid.setVerticalSpacing(16)
        self._cards_grid.setColumnStretch(0, 1)
        self._cards_grid.setColumnStretch(1, 1)
        self._cards_grid.setColumnStretch(2, 1)
        self._cards_grid.setColumnStretch(3, 1)
        lay.addLayout(self._cards_grid)

        lay.addStretch()
        self._update_layout()

    _CARD_NORMAL = (
        "#CardPanel { background: white; border-radius: 8px; "
        "border: 3px solid transparent; } "
        "#CardPanel:hover { border-color: #2980b9; }"
    )
    _CARD_CHECKED = (
        "#CardPanel { background: #eafaf1; border-radius: 8px; "
        "border: 3px solid %s; }" % _GREEN
    )

    def _build_channel_card(self, data: dict):
        ch = data["ch"]
        card = CardPanel()
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(self._CARD_NORMAL)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_make_channel_badge(ch))
        t = QLabel(data["title"])
        t.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        t.setStyleSheet("color: %s;" % _GRAY_DARK)
        header.addWidget(t)
        header.addStretch()
        card.content_layout.addLayout(header)

        card.content_layout.addWidget(
            _make_inline_step(1, "Cathode (\u2212)", _LEAD_BLACK,
                              data["cathode"])
        )
        card.content_layout.addWidget(
            _make_inline_step(2, "Anode (+)", _LEAD_RED, data["anode"])
        )

        cb = card.add_checklist_item(
            "CH %d electrodes placed and secure" % ch
        )
        cb.stateChanged.connect(lambda _: self.gate_changed.emit())
        cb.stateChanged.connect(
            lambda state, c=card: c.setStyleSheet(
                self._CARD_CHECKED if state else self._CARD_NORMAL
            )
        )
        self._channel_cbs[ch] = cb
        self._channel_cards[ch] = card
        card.mousePressEvent = lambda e, c=cb: c.setChecked(not c.isChecked())

    # ── layout engine ─────────────────────────────────────────────────

    def _update_layout(self):
        """Rearrange cards in the grid based on active channels."""
        for card in self._channel_cards.values():
            self._cards_grid.removeWidget(card)
            card.setVisible(False)

        active = [ch for ch in [1, 2, 3] if ch in self._active_channels]

        if len(active) == 1:
            self._cards_grid.addWidget(
                self._channel_cards[active[0]], 0, 1, 1, 2)
        elif len(active) == 2:
            self._cards_grid.addWidget(
                self._channel_cards[active[0]], 0, 0, 1, 2)
            self._cards_grid.addWidget(
                self._channel_cards[active[1]], 0, 2, 1, 2)
        elif len(active) == 3:
            self._cards_grid.addWidget(
                self._channel_cards[active[0]], 0, 0, 1, 2)
            self._cards_grid.addWidget(
                self._channel_cards[active[1]], 0, 2, 1, 2)
            self._cards_grid.addWidget(
                self._channel_cards[active[2]], 1, 1, 1, 2)

        for ch in active:
            self._channel_cards[ch].setVisible(True)

    # ── public API ────────────────────────────────────────────────────

    def set_active_channels(self, channels: list[int]):
        """Update visible cards when modality changes."""
        self._active_channels = list(channels)
        self._update_layout()
        self.gate_changed.emit()

    def is_complete(self) -> bool:
        return all(
            self._channel_cbs[ch].isChecked()
            for ch in self._active_channels
        )
