"""
Wizard page implementations for the VNS-TA protocol workflow.

Each page is a QWidget designed for ProtocolWizard.add_page().
Pages that gate advancement expose is_complete() and gate_changed.

Reusable styled components (AlertBanner, CardPanel) are defined here
and will be shared across all wizard pages.
"""

import shutil
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QFrame, QScrollArea, QGridLayout, QLineEdit, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QTextEdit, QFileDialog, QSizePolicy, QMessageBox, QDateEdit,
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont, QIntValidator, QColor


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
#  Screen 0 — Welcome & Disclaimer
# ──────────────────────────────────────────────────────────────────────

_DISCLAIMER_TEXT = """\
<h3 style="color: #c0392b; margin-bottom: 8px;">
DISCLAIMER AND TERMS OF USE</h3>
<p>This software ("<b>VNS-TA</b>") is an investigational research tool \
developed independently. It has <b>NOT</b> been cleared, approved, or \
certified by the U.S. Food and Drug Administration (FDA), the European \
Medicines Agency (EMA), or any other regulatory body as a medical device.</p>

<p>VNS-TA is intended solely for <b>investigational and research use</b> \
under the direct supervision of qualified medical professionals. It is \
NOT intended to diagnose, treat, cure, or prevent any disease or medical \
condition.</p>

<h3 style="color: #c0392b; margin-top: 12px; margin-bottom: 8px;">
LIMITATION OF LIABILITY</h3>
<p>The developers and contributors of VNS-TA provide this software \
"<b>AS IS</b>" without any warranty, express or implied, including but \
not limited to warranties of merchantability, fitness for a particular \
purpose, or non-infringement.</p>

<p>In no event shall the developers, contributors, or affiliated \
institutions be liable for any direct, indirect, incidental, special, \
consequential, or exemplary damages arising from the use of this \
software, including but not limited to patient injury, misdiagnosis, \
treatment error, or any other clinical outcome.</p>

<h3 style="color: #2c3e50; margin-top: 12px; margin-bottom: 8px;">
CLINICAL RESPONSIBILITY</h3>
<p>The licensed physician or qualified healthcare provider supervising \
the treatment session bears <b>sole and complete responsibility</b> \
for:</p>

<ul style="margin-left: 16px;">
<li>All clinical decisions regarding patient selection, treatment \
parameters, and session management</li>
<li>Verification that all safety checks and protocols are appropriate \
for the specific patient</li>
<li>Continuous monitoring of the patient throughout the treatment \
session</li>
<li>Immediate intervention in the event of adverse patient response</li>
<li>Compliance with all applicable institutional review board (IRB) \
protocols, local regulations, and institutional policies</li>
</ul>

<p>This software does <b>not</b> replace professional medical judgment. \
Autonomous reliance on software-generated alerts, thresholds, or \
recommendations without independent clinical verification is expressly \
discouraged.</p>

<p style="margin-top: 12px; color: #7f8c8d; font-style: italic;">\
By checking the acknowledgment below, you confirm that you have read, \
understood, and agree to these terms for this session.</p>
"""


class WelcomeDisclaimerPage(QWidget):
    """Application welcome screen with investigational-use disclaimer.

    The user must tick the acknowledgment checkbox before advancing.
    This page is shown at the start of every session.
    """

    gate_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("welcomeScroll")
        scroll.setStyleSheet(
            "#welcomeScroll { background: %s; border: none; }" % _PAGE_BG
        )

        content = QWidget()
        content.setObjectName("welcomeContent")
        content.setStyleSheet(
            "#welcomeContent { background: %s; }" % _PAGE_BG
        )

        lay = QVBoxLayout(content)
        lay.setContentsMargins(60, 36, 60, 24)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        # ── Branding ───────────────────────────────────────────────────
        title = QLabel("VNS-TA")
        title.setFont(QFont("Segoe UI", 36, QFont.Bold))
        title.setStyleSheet("color: %s; background: transparent;" % _BLUE)
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        tagline = QLabel(
            "Vagus Nerve Stimulation \u2014 Treatment Assistant"
        )
        tagline.setFont(QFont("Segoe UI", 13))
        tagline.setStyleSheet(
            "color: %s; background: transparent; margin-bottom: 4px;" % _GRAY
        )
        tagline.setAlignment(Qt.AlignCenter)
        lay.addWidget(tagline)

        from vns_ta import __version__
        ver = QLabel("v%s  \u00B7  Investigational Use Only" % __version__)
        ver.setFont(QFont("Segoe UI", 9))
        ver.setStyleSheet(
            "color: white; background: %s; padding: 3px 14px; "
            "border-radius: 4px; margin-bottom: 16px;" % _RED
        )
        ver.setAlignment(Qt.AlignCenter)
        ver.setFixedWidth(ver.sizeHint().width() + 28)
        hbox = QHBoxLayout()
        hbox.setAlignment(Qt.AlignCenter)
        hbox.addWidget(ver)
        lay.addLayout(hbox)

        # ── Disclaimer card ────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("DisclaimerCard")
        card.setStyleSheet(
            "#DisclaimerCard { background: white; border-radius: 8px; "
            "border: 1px solid #e5e8ea; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 18, 24, 18)

        disclaimer = QLabel(_DISCLAIMER_TEXT)
        disclaimer.setWordWrap(True)
        disclaimer.setTextFormat(Qt.RichText)
        disclaimer.setFont(QFont("Segoe UI", 10))
        disclaimer.setStyleSheet("color: #333; line-height: 1.5;")
        card_lay.addWidget(disclaimer)

        lay.addWidget(card)
        lay.addSpacing(12)

        # ── Acknowledgment checkbox ────────────────────────────────────
        self._accept_cb = QCheckBox(
            "  I have read, understood, and accept the above terms "
            "for this session"
        )
        self._accept_cb.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        self._accept_cb.setStyleSheet(
            "QCheckBox { padding: 10px 0; spacing: 12px; color: %s; }"
            "QCheckBox::indicator { width: 22px; height: 22px; }" % _GRAY_DARK
        )
        self._accept_cb.stateChanged.connect(lambda _: self.gate_changed.emit())
        lay.addWidget(self._accept_cb, alignment=Qt.AlignCenter)

        lay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def is_complete(self) -> bool:
        return self._accept_cb.isChecked()


# ──────────────────────────────────────────────────────────────────────
#  Screen 1 — Pre-Session Checklist
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

        # --- Patient info row ---
        pt_card = CardPanel("Patient Information")
        pt_row = QHBoxLayout()
        pt_row.setSpacing(16)

        lname_lbl = QLabel("Last Name")
        lname_lbl.setFont(QFont("Segoe UI", 9))
        lname_lbl.setStyleSheet("color: %s;" % _GRAY)
        pt_row.addWidget(lname_lbl)
        self._last_name = QLineEdit()
        self._last_name.setPlaceholderText("Last")
        self._last_name.setFont(QFont("Segoe UI", 10))
        self._last_name.setMaximumWidth(180)
        self._last_name.textChanged.connect(lambda _: self.gate_changed.emit())
        pt_row.addWidget(self._last_name)

        fname_lbl = QLabel("First Name")
        fname_lbl.setFont(QFont("Segoe UI", 9))
        fname_lbl.setStyleSheet("color: %s;" % _GRAY)
        pt_row.addWidget(fname_lbl)
        self._first_name = QLineEdit()
        self._first_name.setPlaceholderText("First")
        self._first_name.setFont(QFont("Segoe UI", 10))
        self._first_name.setMaximumWidth(180)
        self._first_name.textChanged.connect(lambda _: self.gate_changed.emit())
        pt_row.addWidget(self._first_name)

        dob_lbl = QLabel("DOB")
        dob_lbl.setFont(QFont("Segoe UI", 9))
        dob_lbl.setStyleSheet("color: %s;" % _GRAY)
        pt_row.addWidget(dob_lbl)
        self._dob = QDateEdit()
        self._dob.setDisplayFormat("MM/dd/yyyy")
        self._dob.setCalendarPopup(True)
        self._dob.setFont(QFont("Segoe UI", 10))
        self._dob.setMaximumWidth(130)
        self._dob.setDate(QDate.currentDate())
        self._dob.dateChanged.connect(lambda _: self.gate_changed.emit())
        pt_row.addWidget(self._dob)

        pt_row.addStretch()
        pt_card.content_layout.addLayout(pt_row)
        lay.addWidget(pt_card)

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

    @property
    def patient_last_name(self) -> str:
        return self._last_name.text().strip()

    @property
    def patient_first_name(self) -> str:
        return self._first_name.text().strip()

    @property
    def patient_dob(self) -> QDate:
        return self._dob.date()

    @property
    def patient_name(self) -> str:
        parts = [self.patient_last_name, self.patient_first_name]
        return ", ".join(p for p in parts if p) or "--"

    def clear_patient_info(self):
        self._last_name.clear()
        self._first_name.clear()
        self._dob.setDate(QDate.currentDate())

    def is_complete(self) -> bool:
        """True when patient info is filled and every checklist item is ticked."""
        has_name = bool(self.patient_last_name and self.patient_first_name)
        return has_name and all(cb.isChecked() for cb in self._checks)


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

    def clear_selection(self):
        self._selected = None
        for card in self._cards.values():
            card.set_selected(False)
        self.gate_changed.emit()


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

    def clear(self):
        self._spo2_input.clear()
        self._spo2_cb.setChecked(False)
        self._ble_cb.setChecked(False)
        self._ble_badge.setVisible(False)
        self.ble_hr_label.setVisible(False)
        self.ble_signal_label.setText("")
        for cb in self._checks:
            cb.setChecked(False)
        self.gate_changed.emit()


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


# ──────────────────────────────────────────────────────────────────────
#  EX4 channel parameter data (per-channel stimulation settings)
# ──────────────────────────────────────────────────────────────────────

EX4_CHANNEL_PARAMS = [
    {
        "ch": 1,
        "target": "taVNS (Left Ear)",
        "frequency": "25 Hz",
        "pulse_width": "250 \u00B5s",
        "duty_cycle": "30 s ON / 30 s OFF",
        "intensity": "Just below perception, typically 1\u20135 mA",
    },
    {
        "ch": 2,
        "target": "MNS (Right Wrist)",
        "frequency": "10 Hz",
        "pulse_width": "200 \u00B5s",
        "duty_cycle": "30 s ON / 30 s OFF",
        "intensity": "Until thumb twitch",
    },
    {
        "ch": 3,
        "target": "TNS (Forehead)",
        "frequency": "100\u2013120 Hz sweep",
        "pulse_width": "100 \u00B5s",
        "duty_cycle": "30 s ON / 30 s OFF",
        "intensity": "Perception threshold",
    },
]

_TABLE_STYLE = (
    "QTableWidget { background: white; border: 1px solid #e5e8ea; "
    "border-radius: 6px; gridline-color: #ecf0f1; "
    "font-size: 10pt; } "
    "QTableWidget::item { padding: 8px 10px; } "
    "QHeaderView::section { background: #f4f6f7; "
    "border: none; border-bottom: 2px solid #dce1e3; "
    "padding: 8px 10px; font-weight: 600; font-size: 10pt; "
    "color: #2c3e50; }"
)


# ──────────────────────────────────────────────────────────────────────
#  Screen 4 — EX4 Configuration (dynamic per modality)
# ──────────────────────────────────────────────────────────────────────

class EX4ConfigPage(QWidget):
    """Channel settings table and verification checklist for the
    Richmar TheraTouch EX4 stimulator.

    The table dynamically shows only the channels active in the
    selected modality.  All 3 verification checkboxes must be ticked
    to advance.
    """

    gate_changed = Signal()

    _HEADERS = [
        "Channel", "Target", "Frequency",
        "Pulse Width", "Duty Cycle", "Intensity",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_channels: list[int] = [1]
        self._checks: list[QCheckBox] = []

        lay = _make_page_scaffold(self)

        title = QLabel("EX4 Configuration")
        title.setFont(QFont("Segoe UI", 20, QFont.DemiBold))
        title.setStyleSheet("color: %s; background: transparent;" % _BLUE)
        lay.addWidget(title)

        sub = QLabel(
            "Configure the Richmar TheraTouch EX4 channels. "
            "Do <b>NOT</b> energize channels yet."
        )
        sub.setStyleSheet(
            "color: %s; font-size: 14px; background: transparent;" % _GRAY
        )
        lay.addWidget(sub)

        # ── Channel settings table ────────────────────────────────────
        self._table_card = CardPanel("Channel Settings")
        self._build_table()
        lay.addWidget(self._table_card)

        # ── Voltage-spike warning ─────────────────────────────────────
        lay.addWidget(AlertBanner(
            "<b>Voltage Spike Prevention:</b> Never remove leads while "
            "the EX4 is active. Always press Stop/Pause first.",
            AlertBanner.WARN,
        ))

        # ── Verification checklist ────────────────────────────────────
        verify_card = CardPanel("Verification")
        self._add(verify_card,
                  "Selected channels configured on the EX4")
        self._add(verify_card,
                  "Duty cycles synchronized across all active channels "
                  "(30 s ON / 30 s OFF)")
        self._add(verify_card,
                  "EX4 is powered on but no channels energized and "
                  "NOT yet delivering current")
        lay.addWidget(verify_card)

        lay.addStretch()

    # ── table builder ─────────────────────────────────────────────────

    def _build_table(self):
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.setStyleSheet(_TABLE_STYLE)

        self._populate_table()
        self._table_card.content_layout.addWidget(self._table)

    def _populate_table(self):
        rows = [p for p in EX4_CHANNEL_PARAMS
                if p["ch"] in self._active_channels]
        self._table.setRowCount(len(rows))

        for r, p in enumerate(rows):
            ch_item = QTableWidgetItem("CH %d" % p["ch"])
            ch_item.setFont(QFont("Segoe UI", 10, QFont.Bold))
            ch_item.setForeground(QColor(_CH_COLORS.get(p["ch"], _GRAY)))
            self._table.setItem(r, 0, ch_item)

            vals = [
                p["target"], p["frequency"], p["pulse_width"],
                p["duty_cycle"], p["intensity"],
            ]
            for c, v in enumerate(vals, start=1):
                item = QTableWidgetItem(v)
                item.setFont(QFont("Segoe UI", 10))
                self._table.setItem(r, c, item)

        self._table.setFixedHeight(
            self._table.horizontalHeader().height()
            + sum(self._table.rowHeight(r) for r in range(self._table.rowCount()))
            + 4
        )

    # ── helpers ───────────────────────────────────────────────────────

    def _add(self, card: CardPanel, text: str):
        cb = card.add_checklist_item(text)
        cb.stateChanged.connect(lambda _: self.gate_changed.emit())
        self._checks.append(cb)

    # ── public API ────────────────────────────────────────────────────

    def set_active_channels(self, channels: list[int]):
        """Rebuild the table when the active modality changes."""
        self._active_channels = list(channels)
        self._populate_table()
        self.gate_changed.emit()

    def is_complete(self) -> bool:
        return all(cb.isChecked() for cb in self._checks)


# ──────────────────────────────────────────────────────────────────────
#  ReadoutGauge — large numeric readout card
# ──────────────────────────────────────────────────────────────────────

class ReadoutGauge(QFrame):
    """Styled readout card showing a single live metric with OK/WARN/DANGER
    color states, matching the mockup's .readout component."""

    OK = "ok"
    WARN = "warn"
    DANGER = "danger"
    NEUTRAL = "neutral"

    _STATE_COLORS = {
        "ok": _GREEN,
        "warn": _YELLOW,
        "danger": _RED,
        "neutral": _GRAY_DARK,
    }

    def __init__(self, label: str, unit: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ReadoutGauge")
        self.setStyleSheet(
            "#ReadoutGauge { background: white; border-radius: 8px; "
            "border: 1px solid #e5e8ea; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignCenter)

        self._label = QLabel(label)
        self._label.setFont(QFont("Segoe UI", 10))
        self._label.setStyleSheet(
            "color: %s; letter-spacing: 0.5px;" % _GRAY
        )
        self._label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._label)

        self._value = QLabel("--")
        self._value.setFont(QFont("Segoe UI", 28, QFont.Bold))
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setStyleSheet("color: %s;" % _GRAY)
        lay.addWidget(self._value)

        self._unit = QLabel(unit)
        self._unit.setFont(QFont("Segoe UI", 10))
        self._unit.setStyleSheet("color: %s;" % _GRAY)
        self._unit.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._unit)

    def set_value(self, text: str, state: str = "neutral"):
        """Update the displayed value and color state."""
        self._value.setText(text)
        color = self._STATE_COLORS.get(state, _GRAY_DARK)
        self._value.setStyleSheet("color: %s;" % color)


# ──────────────────────────────────────────────────────────────────────
#  Screen 5 — Autonomic Readiness Check
# ──────────────────────────────────────────────────────────────────────

class ReadinessPage(QWidget):
    """Live autonomic readouts with GO/NO-GO decision logic.

    Three gauges (HR, RMSSD, SpO2) are fed by the View in real time.
    Two auto-verified checkboxes reflect baselines-locked and
    values-in-range.  One manual checkbox for physician clearance.

    Thresholds are read from the Settings singleton so they can be
    tuned per patient population without code changes.
    """

    gate_changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._checks: list[QCheckBox] = []

        lay = _make_page_scaffold(self)

        title = QLabel("Autonomic Readiness Check")
        title.setFont(QFont("Segoe UI", 20, QFont.DemiBold))
        title.setStyleSheet("color: %s; background: transparent;" % _BLUE)
        lay.addWidget(title)

        sub = QLabel(
            "Confirm the patient\u2019s autonomic baseline meets "
            "the launch criteria."
        )
        sub.setStyleSheet(
            "color: %s; font-size: 14px; background: transparent;" % _GRAY
        )
        lay.addWidget(sub)

        # ── Readout gauges ────────────────────────────────────────────
        gauges = QHBoxLayout()
        gauges.setSpacing(16)

        self._hr_gauge = ReadoutGauge(
            "Resting Heart Rate",
            "BPM (must be < %d)" % settings.READINESS_HR_MAX,
        )
        self._rmssd_gauge = ReadoutGauge(
            "RMSSD (Baseline)",
            "ms (must be > %d)" % settings.READINESS_RMSSD_MIN,
        )
        self._spo2_gauge = ReadoutGauge(
            "SpO\u2082",
            "%% (must be %d\u2013%d)" % (
                settings.READINESS_SPO2_MIN, settings.READINESS_SPO2_MAX
            ),
        )

        gauges.addWidget(self._hr_gauge, stretch=1)
        gauges.addWidget(self._rmssd_gauge, stretch=1)
        gauges.addWidget(self._spo2_gauge, stretch=1)
        lay.addLayout(gauges)

        # ── Progress bar + Reset button ───────────────────────────────
        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(28)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setFormat("Waiting for sensor connection\u2026")
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #d5dbdb; border-radius: 6px; "
            "background: white; text-align: center; font-size: 10pt; "
            "color: %s; } "
            "QProgressBar::chunk { background: %s; border-radius: 5px; }"
            % (_GRAY_DARK, _GREEN)
        )
        progress_row.addWidget(self.progress_bar, stretch=1)

        self.reset_btn = QPushButton("Reset Baseline")
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setEnabled(False)
        self.reset_btn.setStyleSheet(
            "QPushButton { background: %s; color: %s; border: none; "
            "border-radius: 5px; padding: 8px 18px; "
            "font-size: 11pt; font-weight: 600; } "
            "QPushButton:disabled { background: #e8e8e8; color: #bdc3c7; }"
            % (_GRAY_LIGHT, _GRAY_DARK)
        )
        progress_row.addWidget(self.reset_btn)

        lay.addLayout(progress_row)

        # ── Dev mode override panel (hidden by default) ───────────────
        self._dev_panel = QFrame()
        self._dev_panel.setObjectName("DevPanel")
        self._dev_panel.setStyleSheet(
            "#DevPanel { background: #fdf2e9; border: 2px dashed #e67e22; "
            "border-radius: 6px; }"
        )
        self._dev_panel.setVisible(False)

        dp_lay = QHBoxLayout(self._dev_panel)
        dp_lay.setContentsMargins(14, 8, 14, 8)
        dp_lay.setSpacing(12)

        dp_title = QLabel("\U0001F527 DEV OVERRIDES")
        dp_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        dp_title.setStyleSheet("color: #e67e22;")
        dp_lay.addWidget(dp_title)

        dp_lay.addWidget(QLabel("HR:"))
        self._dev_hr = QLineEdit()
        self._dev_hr.setPlaceholderText("BPM")
        self._dev_hr.setFixedWidth(50)
        self._dev_hr.setValidator(QIntValidator(30, 250))
        self._dev_hr.setAlignment(Qt.AlignCenter)
        self._dev_hr.setFont(QFont("Segoe UI", 10))
        self._dev_hr.textChanged.connect(self._on_dev_hr)
        dp_lay.addWidget(self._dev_hr)

        dp_lay.addWidget(QLabel("RMSSD:"))
        self._dev_rmssd = QLineEdit()
        self._dev_rmssd.setPlaceholderText("ms")
        self._dev_rmssd.setFixedWidth(50)
        self._dev_rmssd.setValidator(QIntValidator(0, 300))
        self._dev_rmssd.setAlignment(Qt.AlignCenter)
        self._dev_rmssd.setFont(QFont("Segoe UI", 10))
        self._dev_rmssd.textChanged.connect(self._on_dev_rmssd)
        dp_lay.addWidget(self._dev_rmssd)

        self._dev_lock_btn = QPushButton("Force Baselines Locked")
        self._dev_lock_btn.setCursor(Qt.PointingHandCursor)
        self._dev_lock_btn.setStyleSheet(
            "QPushButton { background: #e67e22; color: white; border: none; "
            "border-radius: 4px; padding: 6px 14px; font-size: 10pt; "
            "font-weight: 600; } "
            "QPushButton:hover { background: #d35400; }"
        )
        self._dev_lock_btn.clicked.connect(
            lambda: self.set_baselines_locked(True)
        )
        dp_lay.addWidget(self._dev_lock_btn)

        dp_lay.addStretch()
        lay.addWidget(self._dev_panel)

        # ── GO / NO-GO alerts ─────────────────────────────────────────
        self._alert_go = AlertBanner(
            "<b>LAUNCH WINDOW: GO.</b> All autonomic readiness "
            "criteria are met.",
            AlertBanner.OK,
        )
        self._alert_go.setVisible(False)
        lay.addWidget(self._alert_go)

        self._alert_nogo = AlertBanner(
            "<b>YELLOW ZONE: NO-GO.</b> One or more readiness "
            "criteria are not met. See values above.",
            AlertBanner.DANGER,
        )
        self._alert_nogo.setVisible(False)
        lay.addWidget(self._alert_nogo)

        self._alert_nogo_rmssd = AlertBanner(
            "<b>YELLOW ZONE: NO-GO.</b> RMSSD < %d ms indicates "
            "high sympathetic dominance. Pharmacological grounding "
            "is recommended rather than taVNS. Consult physician."
            % settings.READINESS_RMSSD_NOGO,
            AlertBanner.DANGER,
        )
        self._alert_nogo_rmssd.setVisible(False)
        lay.addWidget(self._alert_nogo_rmssd)

        # ── Baseline confirmation checklist ───────────────────────────
        confirm_card = CardPanel("Baseline Confirmation")

        # Auto-verified: baselines established
        sep1 = QFrame()
        sep1.setFixedHeight(0)
        confirm_card.content_layout.addWidget(sep1)

        base_row = QHBoxLayout()
        base_row.setSpacing(6)
        self._baselines_cb = QCheckBox()
        self._baselines_cb.setEnabled(False)
        self._baselines_cb.setStyleSheet(
            "QCheckBox { padding: 8px 0; spacing: 10px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self._baselines_badge = QLabel("\u2713 AUTO-VERIFIED:")
        self._baselines_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._baselines_badge.setStyleSheet("color: %s;" % _GREEN)
        self._baselines_badge.setVisible(False)
        self._baselines_text = QLabel(
            "VNS-TA settling period complete and baselines established"
        )
        self._baselines_text.setFont(QFont("Segoe UI", 10))
        self._baselines_text.setStyleSheet("color: %s;" % _GRAY)
        base_row.addWidget(self._baselines_cb)
        base_row.addWidget(self._baselines_badge)
        base_row.addWidget(self._baselines_text)
        base_row.addStretch()
        confirm_card.content_layout.addLayout(base_row)

        # Separator
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: %s;" % _GRAY_LIGHT)
        confirm_card.content_layout.addWidget(sep2)

        # Auto-verified: values in range
        range_row = QHBoxLayout()
        range_row.setSpacing(6)
        self._range_cb = QCheckBox()
        self._range_cb.setEnabled(False)
        self._range_cb.setStyleSheet(
            "QCheckBox { padding: 8px 0; spacing: 10px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self._range_badge = QLabel("\u2713 AUTO-VERIFIED:")
        self._range_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._range_badge.setStyleSheet("color: %s;" % _GREEN)
        self._range_badge.setVisible(False)
        self._range_text = QLabel(
            "All readiness values within acceptable range"
        )
        self._range_text.setFont(QFont("Segoe UI", 10))
        self._range_text.setStyleSheet("color: %s;" % _GRAY)
        range_row.addWidget(self._range_cb)
        range_row.addWidget(self._range_badge)
        range_row.addWidget(self._range_text)
        range_row.addStretch()
        confirm_card.content_layout.addLayout(range_row)

        # Separator
        sep3 = QFrame()
        sep3.setFixedHeight(1)
        sep3.setStyleSheet("background: %s;" % _GRAY_LIGHT)
        confirm_card.content_layout.addWidget(sep3)

        # Manual: physician clearance
        self._physician_cb = confirm_card.add_checklist_item(
            "Supervising physician has given verbal clearance to proceed"
        )
        self._physician_cb.stateChanged.connect(
            lambda _: self.gate_changed.emit()
        )
        self._checks.append(self._physician_cb)

        lay.addWidget(confirm_card)
        lay.addStretch()

        # Internal tracking
        self._baselines_locked = False
        self._hr_val: float | None = None
        self._rmssd_val: float | None = None
        self._spo2_val: int | None = None

    # ── live data feeds (called by View) ──────────────────────────────

    def update_hr(self, hr: float):
        """Push a live heart-rate value."""
        self._hr_val = hr
        limit = self._settings.READINESS_HR_MAX
        state = ReadoutGauge.OK if hr < limit else ReadoutGauge.DANGER
        self._hr_gauge.set_value(str(int(hr)), state)
        self._refresh_readiness()

    def update_rmssd(self, rmssd: float):
        """Push a live RMSSD baseline value."""
        self._rmssd_val = rmssd
        green = self._settings.READINESS_RMSSD_MIN
        nogo = self._settings.READINESS_RMSSD_NOGO
        if rmssd >= green:
            state = ReadoutGauge.OK
        elif rmssd >= nogo:
            state = ReadoutGauge.WARN
        else:
            state = ReadoutGauge.DANGER
        self._rmssd_gauge.set_value("%.0f" % rmssd, state)
        self._refresh_readiness()

    def update_spo2(self, spo2: int | None):
        """Push the SpO2 value (from Sensor page input)."""
        self._spo2_val = spo2
        lo = self._settings.READINESS_SPO2_MIN
        hi = self._settings.READINESS_SPO2_MAX
        if spo2 is None:
            self._spo2_gauge.set_value("--", ReadoutGauge.NEUTRAL)
        elif lo <= spo2 <= hi:
            self._spo2_gauge.set_value(str(spo2), ReadoutGauge.OK)
        else:
            self._spo2_gauge.set_value(str(spo2), ReadoutGauge.DANGER)
        self._refresh_readiness()

    def set_baselines_locked(self, locked: bool):
        """Called when the settling + baseline collection completes."""
        self._baselines_locked = locked
        self._baselines_cb.setChecked(locked)
        self._baselines_badge.setVisible(locked)
        self._baselines_text.setStyleSheet(
            "color: %s;" % (_GRAY_DARK if locked else _GRAY)
        )
        self.reset_btn.setEnabled(locked)
        self._refresh_readiness()

    # ── progress bar feeds (called by View) ───────────────────────────

    def set_progress_settling(self, elapsed: int, total: int):
        """Update progress bar during the settling phase."""
        remaining = max(0, total - elapsed)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(elapsed)
        self.progress_bar.setFormat("Settling\u2026 %ds remaining" % remaining)

    def set_progress_baseline(self, elapsed: int, total: int):
        """Update progress bar during the baseline collection phase."""
        remaining = max(0, total - elapsed)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(elapsed)
        self.progress_bar.setFormat(
            "Establishing baselines\u2026 %ds remaining" % remaining
        )

    def set_progress_locked(self, rmssd_text: str, hr_text: str):
        """Show locked baselines on the progress bar."""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_bar.setFormat(
            "BASELINES LOCKED: RMSSD = %s ms  |  HR = %s bpm"
            % (rmssd_text, hr_text)
        )

    def set_progress_disconnected(self):
        """Reset progress bar to waiting state."""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Waiting for sensor connection\u2026")

    # ── dev mode ──────────────────────────────────────────────────────

    def set_dev_mode(self, enabled: bool):
        self._dev_panel.setVisible(enabled)

    def _on_dev_hr(self, text: str):
        try:
            self.update_hr(float(text))
        except ValueError:
            pass

    def _on_dev_rmssd(self, text: str):
        try:
            self.update_rmssd(float(text))
        except ValueError:
            pass

    # ── internal readiness logic ──────────────────────────────────────

    def _values_in_range(self) -> bool:
        s = self._settings
        hr_ok = self._hr_val is not None and self._hr_val < s.READINESS_HR_MAX
        rmssd_ok = (self._rmssd_val is not None
                    and self._rmssd_val >= s.READINESS_RMSSD_MIN)
        spo2_ok = (self._spo2_val is not None
                   and s.READINESS_SPO2_MIN <= self._spo2_val
                   <= s.READINESS_SPO2_MAX)
        return hr_ok and rmssd_ok and spo2_ok

    def _refresh_readiness(self):
        in_range = self._values_in_range()
        self._range_cb.setChecked(in_range)
        self._range_badge.setVisible(in_range)
        self._range_text.setStyleSheet(
            "color: %s;" % (_GRAY_DARK if in_range else _GRAY)
        )

        all_go = self._baselines_locked and in_range
        self._alert_go.setVisible(all_go)

        rmssd_critical = (self._rmssd_val is not None
                          and self._rmssd_val
                          < self._settings.READINESS_RMSSD_NOGO)
        self._alert_nogo_rmssd.setVisible(rmssd_critical)
        self._alert_nogo.setVisible(
            not all_go
            and not rmssd_critical
            and self._baselines_locked
            and not in_range
        )

        self.gate_changed.emit()

    # ── gate ──────────────────────────────────────────────────────────

    def is_complete(self) -> bool:
        return (
            self._baselines_locked
            and self._values_in_range()
            and all(cb.isChecked() for cb in self._checks)
        )

    def reset_all(self):
        self._baselines_locked = False
        self._hr_val = None
        self._rmssd_val = None
        self._spo2_val = None
        self._hr_gauge.set_value("--")
        self._rmssd_gauge.set_value("--")
        self._spo2_gauge.set_value("--")
        for cb in self._checks:
            cb.setChecked(False)
        self.gate_changed.emit()


# ──────────────────────────────────────────────────────────────────────
#  Screen 6 — Start Sequence
# ──────────────────────────────────────────────────────────────────────

_TIMELINE_STEPS = [
    {
        "ch": 1,
        "time": "0:00",
        "title": "Start CH 1 (taVNS)",
        "body": (
            "Slowly increase intensity to just below perception "
            "(1\u20135 mA). Establishes the <b>Vagal Ground</b>."
        ),
        "check": "CH 1 started and stable for 2 min",
    },
    {
        "ch": 2,
        "time": "2:00",
        "title": "Add CH 2 (MNS)",
        "body": (
            "Increase intensity until slight thumb twitch. "
            "Fist = too high. Establishes the <b>Motor Anchor</b>."
        ),
        "check": "CH 2 added, thumb twitch confirmed, stable 2 min",
    },
    {
        "ch": 3,
        "time": "4:00",
        "title": "Add CH 3 (TNS)",
        "body": (
            "Increase to perception threshold. Watch for blinking, "
            "grimacing, jaw clench. Establishes <b>Cortical Reset</b>."
        ),
        "check": "CH 3 added, no adverse trigeminal reflex",
    },
]

_TL_ITEM_STYLE = (
    "background: white; border-radius: 6px; border: 1px solid #e5e8ea; "
    "padding: 6px 12px; margin-bottom: 4px;"
)
_TL_ACTIVE_STYLE = (
    "background: white; border-radius: 6px; "
    "border-left: 4px solid %s; border-top: 1px solid #e5e8ea; "
    "border-right: 1px solid #e5e8ea; border-bottom: 1px solid #e5e8ea; "
    "padding: 6px 12px; margin-bottom: 4px;" % _BLUE
)


class StartSequencePage(QWidget):
    """Channel ramp-up sequence with timeline, live readouts, and checklist.

    Dynamic: only shows timeline items and checklist entries for the
    channels selected in the Modality page.
    """

    gate_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_channels: list[int] = [1]
        self._baseline_hr: float | None = None
        self._checks: list[QCheckBox] = []
        self._channel_checks: dict[int, QCheckBox] = {}
        self._timeline_items: dict[int, QFrame] = {}

        lay = _make_page_scaffold(self)
        lay.setContentsMargins(24, 12, 24, 12)
        lay.setSpacing(8)

        # Row 0: Title + Vagal Escape alert on one line
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        title = QLabel("Start Sequence")
        title.setFont(QFont("Segoe UI", 16, QFont.DemiBold))
        title.setStyleSheet("color: %s;" % _BLUE)
        top_row.addWidget(title)

        top_row.addWidget(AlertBanner(
            "<b>Vagal Escape Rule:</b> If HR rises >15 BPM after adding "
            "a channel, reduce intensity 50%. If unstable after 60 s, "
            "terminate.",
            AlertBanner.DANGER,
        ), stretch=1)

        lay.addLayout(top_row)

        subtitle = QLabel(
            "Ramp up channels one at a time. Monitor for autonomic "
            "startle responses between each addition."
        )
        subtitle.setFont(QFont("Segoe UI", 9))
        subtitle.setStyleSheet("color: %s;" % _GRAY)
        subtitle.setWordWrap(True)
        lay.addWidget(subtitle)

        # Row 1: Readout gauges — horizontal
        gauge_row = QHBoxLayout()
        gauge_row.setSpacing(12)

        self._hr_gauge = ReadoutGauge("Heart Rate", "BPM")
        gauge_row.addWidget(self._hr_gauge)

        self._delta_gauge = ReadoutGauge("HR \u0394 from Baseline", "BPM (alert if > 15)")
        gauge_row.addWidget(self._delta_gauge)

        self._rmssd_gauge = ReadoutGauge("RMSSD", "ms")
        gauge_row.addWidget(self._rmssd_gauge)

        lay.addLayout(gauge_row)

        # Row 2: Timeline (left) + Checklist (right)
        body = QHBoxLayout()
        body.setSpacing(12)

        # LEFT: Timeline
        tl_col = QVBoxLayout()
        tl_col.setSpacing(0)

        for step in _TIMELINE_STEPS:
            item = QFrame()
            item.setStyleSheet(_TL_ITEM_STYLE)
            il = QVBoxLayout(item)
            il.setContentsMargins(8, 4, 8, 4)
            il.setSpacing(2)

            time_lbl = QLabel(f"{step['time']} \u2014 {step['title']}")
            time_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            time_lbl.setStyleSheet("color: %s;" % _BLUE)
            il.addWidget(time_lbl)

            desc = QLabel(step["body"])
            desc.setWordWrap(True)
            desc.setFont(QFont("Segoe UI", 8))
            desc.setStyleSheet("color: #555;")
            il.addWidget(desc)

            tl_col.addWidget(item)
            self._timeline_items[step["ch"]] = item

        # Final "all channels active" item
        self._final_item = QFrame()
        self._final_item.setStyleSheet(_TL_ACTIVE_STYLE)
        fl = QVBoxLayout(self._final_item)
        fl.setContentsMargins(8, 4, 8, 4)
        fl.setSpacing(2)
        self._final_label = QLabel("All Channels Active")
        self._final_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self._final_label.setStyleSheet("color: %s;" % _BLUE)
        fl.addWidget(self._final_label)
        self._final_desc = QLabel(
            "All selected channels running. Confirm no adverse "
            "responses. Proceed to monitoring."
        )
        self._final_desc.setWordWrap(True)
        self._final_desc.setFont(QFont("Segoe UI", 8))
        self._final_desc.setStyleSheet("color: #555;")
        fl.addWidget(self._final_desc)
        tl_col.addWidget(self._final_item)

        tl_col.addStretch()
        body.addLayout(tl_col, stretch=3)

        # RIGHT: Confirmation checklist
        check_card = CardPanel("Confirmation")
        for step in _TIMELINE_STEPS:
            cb = check_card.add_checklist_item(step["check"])
            cb.stateChanged.connect(lambda _: self.gate_changed.emit())
            self._checks.append(cb)
            self._channel_checks[step["ch"]] = cb

        self._final_cb = check_card.add_checklist_item(
            "All channels running \u2014 vitals normal"
        )
        self._final_cb.stateChanged.connect(lambda _: self.gate_changed.emit())
        self._checks.append(self._final_cb)

        body.addWidget(check_card, stretch=2)

        lay.addLayout(body)
        lay.addStretch()

        self._update_visibility()

    # ── public API ────────────────────────────────────────────────────

    def set_active_channels(self, channels: list[int]):
        self._active_channels = channels
        self._update_visibility()
        self.gate_changed.emit()

    def set_baseline_hr(self, hr: float | None):
        self._baseline_hr = hr

    def update_hr(self, hr: float):
        self._hr_gauge.set_value(f"{int(hr)}", ReadoutGauge.OK)
        if self._baseline_hr is not None:
            delta = hr - self._baseline_hr
            state = ReadoutGauge.DANGER if abs(delta) > 15 else ReadoutGauge.OK
            self._delta_gauge.set_value(f"{delta:+.0f}", state)

    def update_rmssd(self, rmssd: float):
        self._rmssd_gauge.set_value(f"{rmssd:.1f}", ReadoutGauge.OK)

    # ── internal ─────────────────────────────────────────────────────

    def _update_visibility(self):
        for ch, item in self._timeline_items.items():
            item.setVisible(ch in self._active_channels)
        for ch, cb in self._channel_checks.items():
            cb.setVisible(ch in self._active_channels)

        n = len(self._active_channels)
        if n == 1:
            self._final_label.setText("2:00 \u2014 CH 1 Stable")
        elif n == 2:
            self._final_label.setText("4:00 \u2014 Both Channels Active")
        else:
            self._final_label.setText("5:00 \u2014 All Channels Active")

    # ── gate ─────────────────────────────────────────────────────────

    def is_complete(self) -> bool:
        return all(
            cb.isChecked() for cb in self._checks if cb.isVisible()
        )


# ──────────────────────────────────────────────────────────────────────
#  Screen 8 — Session Summary
# ──────────────────────────────────────────────────────────────────────

_SUMMARY_ROW_STYLE = (
    "border-bottom: 1px solid %s; padding: 5px 0; font-size: 10pt;"
    % _GRAY_LIGHT
)


def _summary_row(label: str, value: str, color: str = _GRAY_DARK) -> tuple[QWidget, QLabel]:
    """Label … bold value row matching the mockup .summary-row style."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)

    lbl = QLabel(label)
    lbl.setFont(QFont("Segoe UI", 10))
    lbl.setStyleSheet("color: %s;" % _GRAY_DARK)
    lay.addWidget(lbl)

    lay.addStretch()

    val = QLabel(value)
    val.setFont(QFont("Segoe UI", 10, QFont.Bold))
    val.setStyleSheet("color: %s;" % color)
    val.setObjectName("summaryValue")
    lay.addWidget(val)

    w.setStyleSheet(_SUMMARY_ROW_STYLE)
    return w, val


class SessionSummaryPage(QWidget):
    """Final wizard page — session review, notes, CSV save, Word export."""

    gate_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checks: list[QCheckBox] = []
        self._data: dict = {}
        self._value_labels: dict[str, QLabel] = {}

        lay = _make_page_scaffold(self)
        lay.setContentsMargins(24, 12, 24, 12)
        lay.setSpacing(8)

        # Row 0: Title + status alert + duration — all on one line
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        title = QLabel("Session Complete")
        title.setFont(QFont("Segoe UI", 16, QFont.DemiBold))
        title.setStyleSheet("color: %s;" % _BLUE)
        top_row.addWidget(title)

        self._alert_ok = AlertBanner(
            "<b>Session completed normally.</b> "
            "All abort criteria remained within safe limits.",
            AlertBanner.OK,
        )
        top_row.addWidget(self._alert_ok, stretch=1)

        self._alert_abort = AlertBanner(
            "<b>Session was ABORTED.</b> Review the data below.",
            AlertBanner.DANGER,
        )
        self._alert_abort.setVisible(False)
        top_row.addWidget(self._alert_abort, stretch=1)

        dur_frame = QFrame()
        dur_frame.setStyleSheet(
            "background: white; border: 1px solid #e5e8ea; "
            "border-radius: 6px; padding: 4px 12px;"
        )
        dur_lay = QHBoxLayout(dur_frame)
        dur_lay.setContentsMargins(8, 2, 8, 2)
        dur_lay.setSpacing(6)
        dur_lbl = QLabel("Total Treatment Time")
        dur_lbl.setFont(QFont("Segoe UI", 9))
        dur_lbl.setStyleSheet("color: %s;" % _GRAY)
        dur_lay.addWidget(dur_lbl)
        self._dur_label = QLabel("--")
        self._dur_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._dur_label.setStyleSheet("color: %s;" % _BLUE)
        dur_lay.addWidget(self._dur_label)
        top_row.addWidget(dur_frame)

        lay.addLayout(top_row)

        subtitle = QLabel("Review session data and complete the post-session checklist.")
        subtitle.setFont(QFont("Segoe UI", 9))
        subtitle.setStyleSheet("color: %s;" % _GRAY)
        lay.addWidget(subtitle)

        # Row 1: Summary grid (2x2) — tighter spacing
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        # Pre-session baselines
        pre_card = CardPanel("Pre-Session Baselines")
        for key, label in [
            ("pre_hr", "Heart Rate"),
            ("pre_rmssd", "RMSSD"),
            ("pre_spo2", "SpO\u2082"),
        ]:
            row_w, val_lbl = _summary_row(label, "--")
            pre_card.content_layout.addWidget(row_w)
            self._value_labels[key] = val_lbl
        grid.addWidget(pre_card, 0, 0)

        # Post-session readings
        post_card = CardPanel("Post-Session Readings")
        for key, label in [
            ("post_hr", "Heart Rate"),
            ("post_rmssd", "RMSSD"),
            ("delta_rmssd", "\u0394 RMSSD"),
        ]:
            row_w, val_lbl = _summary_row(label, "--")
            post_card.content_layout.addWidget(row_w)
            self._value_labels[key] = val_lbl
        grid.addWidget(post_card, 0, 1)

        # Treatment parameters
        params_card = CardPanel("Treatment Parameters")
        for key, label in [
            ("modality", "Modality"),
            ("channels", "Active Channels"),
            ("duration", "Duration"),
        ]:
            row_w, val_lbl = _summary_row(label, "--")
            params_card.content_layout.addWidget(row_w)
            self._value_labels[key] = val_lbl
        grid.addWidget(params_card, 1, 0)

        # Session notes — compact text area
        notes_card = CardPanel("Session Notes")
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Enter clinical observations\u2026")
        self._notes_edit.setMaximumHeight(72)
        self._notes_edit.setFont(QFont("Segoe UI", 9))
        self._notes_edit.setStyleSheet(
            "border: 1px solid #d5dbdb; border-radius: 4px; padding: 4px;"
        )
        notes_card.content_layout.addWidget(self._notes_edit)
        grid.addWidget(notes_card, 1, 1)

        lay.addLayout(grid)

        # Row 2: Post-session checklist (two columns) + export buttons side by side
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        checklist_card = CardPanel("Post-Session Checklist")
        checklist_items = [
            "EX4 Stop/Pause pressed before lead removal",
            "All electrodes carefully removed",
            "Skin inspection \u2014 no redness or burns",
            "Polar H10 strap removed and gel wiped",
            "Pulse oximeter removed",
            "Session data reviewed for completeness",
        ]
        chk_grid = QGridLayout()
        chk_grid.setHorizontalSpacing(24)
        chk_grid.setVerticalSpacing(2)
        for idx, text in enumerate(checklist_items):
            cb = QCheckBox(text)
            cb.setFont(QFont("Segoe UI", 9))
            cb.stateChanged.connect(lambda _: self.gate_changed.emit())
            self._checks.append(cb)
            chk_grid.addWidget(cb, idx // 2, idx % 2)
        checklist_card.content_layout.addLayout(chk_grid)
        bottom_row.addWidget(checklist_card, stretch=3)

        # Export buttons column
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        _BTN_STYLE_BLUE = (
            "QPushButton { background: #2980b9; color: white; "
            "border-radius: 6px; padding: 8px 14px; font-size: 9pt; }"
            "QPushButton:hover { background: #1a6ea0; }"
            "QPushButton:disabled { background: #bdc3c7; }"
        )
        _BTN_STYLE_GREEN = (
            "QPushButton { background: #27ae60; color: white; "
            "border-radius: 6px; padding: 8px 14px; font-size: 9pt; }"
            "QPushButton:hover { background: #1e8449; }"
            "QPushButton:disabled { background: #bdc3c7; }"
        )

        self._csv_btn = QPushButton("\U0001F4BE  Save CSV As\u2026")
        self._csv_btn.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self._csv_btn.setStyleSheet(_BTN_STYLE_BLUE)
        self._csv_btn.clicked.connect(self._save_csv)
        btn_col.addWidget(self._csv_btn)

        self._docx_btn = QPushButton("\U0001F4C4  Export Report (.docx)")
        self._docx_btn.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self._docx_btn.setStyleSheet(_BTN_STYLE_GREEN)
        self._docx_btn.clicked.connect(self._export_docx)
        btn_col.addWidget(self._docx_btn)

        btn_col.addStretch()
        bottom_row.addLayout(btn_col, stretch=1)

        lay.addLayout(bottom_row)
        lay.addStretch()

    # ── public API ────────────────────────────────────────────────────

    def set_session_data(self, data: dict):
        """Populate all summary fields from a data dict.

        Expected keys: baseline_hr, baseline_rmssd, spo2,
        last_hr, last_rmssd, modality_name, active_channels,
        session_start, csv_path, annotations, hr_values, rmssd_values,
        outcome.
        """
        self._data = data

        outcome = data.get("outcome", "normal")
        self._alert_ok.setVisible(outcome == "normal")
        self._alert_abort.setVisible(outcome != "normal")

        start = data.get("session_start")
        now = datetime.now()
        if start:
            mins = (now - start).total_seconds() / 60
            self._dur_label.setText(f"{mins:.1f} minutes")
        self._data["session_end"] = now

        def _f(v, unit="", prec=1):
            if v is None:
                return "--"
            if isinstance(v, float):
                return f"{v:.{prec}f} {unit}".strip()
            return f"{v} {unit}".strip()

        self._value_labels["pre_hr"].setText(
            _f(data.get("baseline_hr"), "bpm", 0))
        self._value_labels["pre_rmssd"].setText(
            _f(data.get("baseline_rmssd"), "ms"))
        self._value_labels["pre_spo2"].setText(
            _f(data.get("spo2"), "%", 0))

        self._value_labels["post_hr"].setText(
            _f(data.get("last_hr"), "bpm", 0))
        self._value_labels["post_rmssd"].setText(
            _f(data.get("last_rmssd"), "ms"))

        pre_rmssd = data.get("baseline_rmssd")
        post_rmssd = data.get("last_rmssd")
        if pre_rmssd and post_rmssd and pre_rmssd > 0:
            pct = ((post_rmssd - pre_rmssd) / pre_rmssd) * 100
            color = _GREEN if pct >= 0 else _RED
            self._value_labels["delta_rmssd"].setText(f"{pct:+.1f}%")
            self._value_labels["delta_rmssd"].setStyleSheet(
                "color: %s; font-weight: bold;" % color
            )
        else:
            self._value_labels["delta_rmssd"].setText("--")

        self._value_labels["modality"].setText(
            data.get("modality_name", "--"))
        chs = data.get("active_channels", [])
        self._value_labels["channels"].setText(
            ", ".join(f"CH {c}" for c in chs) if chs else "--")
        self._value_labels["duration"].setText(
            self._dur_label.text())

        has_csv = bool(data.get("csv_path"))
        self._csv_btn.setEnabled(has_csv)
        self._docx_btn.setEnabled(True)

    # ── CSV save ─────────────────────────────────────────────────────

    def _save_csv(self):
        src = self._data.get("csv_path", "")
        if not src:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save Session CSV",
            str(src),
            "CSV Files (*.csv)",
        )
        if dest:
            try:
                shutil.copy2(src, dest)
                QMessageBox.information(
                    self, "CSV Saved",
                    f"Session CSV saved to:\n{dest}")
            except Exception as e:
                QMessageBox.warning(
                    self, "Save Failed", str(e))

    # ── Word export ──────────────────────────────────────────────────

    def _export_docx(self):
        default_name = datetime.now().strftime(
            "VNS-TA_Report_%Y-%m-%d_%H%M.docx")
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Session Report",
            default_name,
            "Word Documents (*.docx)",
        )
        if not dest:
            return

        report_data = dict(self._data)
        report_data["notes"] = self._notes_edit.toPlainText()
        report_data["checklist"] = [
            (cb.text(), cb.isChecked()) for cb in self._checks
        ]

        try:
            from vns_ta.report import generate_session_report
            generate_session_report(dest, report_data)
            QMessageBox.information(
                self, "Report Exported",
                f"Session report saved to:\n{dest}")
        except Exception as e:
            QMessageBox.warning(
                self, "Export Failed", str(e))

    # ── gate ─────────────────────────────────────────────────────────

    def is_complete(self) -> bool:
        return all(cb.isChecked() for cb in self._checks)
