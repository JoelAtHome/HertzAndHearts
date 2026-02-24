from datetime import datetime
import json
import math
import random
import statistics
import time
from pathlib import Path
import numpy as np
import pyqtgraph as pg
from PySide6.QtCharts import QLineSeries, QChartView, QChart, QValueAxis, QAreaSeries
from PySide6.QtGui import (
    QPen, QIcon, QLinearGradient, QBrush, QGradient, QColor, QPixmap,
    QKeySequence, QShortcut,
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QObject, QTimer, QMargins, QSize, QPointF, QEvent, QPoint,
    QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QAbstractAnimation,
    QEventLoop,
)
from PySide6.QtBluetooth import QBluetoothAddress, QBluetoothDeviceInfo
from PySide6.QtWidgets import (
    QMainWindow, QPushButton, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QComboBox, QSlider, QGroupBox, QFormLayout, QCheckBox, QLineEdit, QTextEdit,
    QProgressBar, QGridLayout, QSizePolicy, QStatusBar, QFrame, QCompleter,
    QMessageBox, QDialog, QScrollArea, QGraphicsOpacityEffect, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    )
from collections import deque
from typing import Iterable
from hnh.utils import get_sensor_address, NamedSignal
from hnh.sensor import SensorScanner, SensorClient
from hnh.logger import Logger
from hnh.pacer import Pacer
from hnh.model import Model
from hnh.config import (
    breathing_rate_to_tick, HRV_HISTORY_DURATION, IBI_HISTORY_DURATION,
    MAX_BREATHING_RATE, MIN_BREATHING_RATE, MIN_HRV_TARGET, MAX_HRV_TARGET,
    MIN_PLOT_IBI, MAX_PLOT_IBI,
    ECG_SAMPLE_RATE,
)
from hnh.settings import Settings, SettingsDialog, REGISTRY
from hnh.report import generate_session_report
from hnh.session_artifacts import (
    SessionBundle,
    create_session_bundle,
    default_qtc_payload,
    write_manifest,
)
from hnh.profile_store import ProfileStore
from hnh import __version__ as version, resources  # noqa
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
pg.setConfigOptions(antialias=True)

BLUE = QColor(135, 206, 250)
WHITE = QColor(255, 255, 255)
GREEN = QColor(0, 255, 0)
YELLOW = QColor(255, 255, 0)
RED = QColor(255, 0, 0)

SENSOR_CONFIG = Path.home() / ".hnh_last_sensor.json"

_CARD0_DISCLAIMER_TEXT = """\
<h3 style="color: #c0392b; margin-bottom: 8px;">
RESEARCH USE DISCLAIMER</h3>
<p>This software ("<b>Hertz &amp; Hearts</b>") is a cardiac monitoring and
biofeedback research tool. It has <b>NOT</b> been cleared, approved, or
certified by the U.S. Food and Drug Administration (FDA), the European
Medicines Agency (EMA), or any other regulatory body as a medical device.</p>

<p>Hertz &amp; Hearts is intended solely for <b>investigational and research use</b>
under the direct supervision of qualified medical professionals. It is
NOT intended to diagnose, treat, cure, or prevent any disease or medical
condition.</p>

<p>The application may display heart rate, HRV, and ECG-derived values for
research and workflow support. These outputs are informational and must not
replace independent clinical judgment.</p>

<h3 style="color: #c0392b; margin-top: 12px; margin-bottom: 8px;">
LIMITATION OF LIABILITY</h3>
<p>The developers and contributors of Hertz &amp; Hearts provide this software
"<b>AS IS</b>" without any warranty, express or implied, including but
not limited to warranties of merchantability, fitness for a particular
purpose, or non-infringement.</p>

<p>In no event shall the developers, contributors, or affiliated
institutions be liable for any direct, indirect, incidental, special,
consequential, or exemplary damages arising from the use of this
software, including but not limited to patient injury, misdiagnosis,
treatment error, or any other clinical outcome.</p>

<h3 style="color: #2c3e50; margin-top: 12px; margin-bottom: 8px;">
CLINICAL RESPONSIBILITY</h3>
<p>The licensed physician or qualified healthcare provider supervising
the monitoring session bears <b>sole and complete responsibility</b>
for:</p>

<ul style="margin-left: 16px;">
<li>All clinical decisions regarding patient selection, monitoring parameters, and session management</li>
<li>Verification that all safety checks and protocols are appropriate for the specific patient</li>
<li>Continuous monitoring of the patient throughout the session</li>
<li>Immediate intervention in the event of adverse patient response</li>
<li>Compliance with all applicable institutional review board (IRB) protocols, local regulations, and institutional policies</li>
</ul>

<p>This software does <b>not</b> replace professional medical judgment.
Autonomous reliance on software-generated alerts, thresholds, or
recommendations without independent clinical verification is expressly
discouraged.</p>

<p style="margin-top: 12px; color: #7f8c8d; font-style: italic;">
By checking the acknowledgment below, you confirm that you have read,
understood, and agree to these terms for this monitoring session.</p>
"""

def _save_last_sensor(name, address):
    try:
        SENSOR_CONFIG.write_text(json.dumps({"name": name, "address": address}))
    except Exception:
        pass

def _load_last_sensor():
    try:
        return json.loads(SENSOR_CONFIG.read_text())
    except Exception:
        return None

class StatusBanner(QFrame):
    """Colored status label with a thin progress strip underneath."""

    _COLORS = {
        "idle":    ("background:#dfe6e9; color:#636e72;", "#b2bec3"),
        "settle":  ("background:#ffeaa7; color:#6c5b00;", "#fdcb6e"),
        "baseline":("background:#74b9ff; color:#003366;", "#0984e3"),
        "locked":  ("background:#00b894; color:#fff;",    "#00b894"),
        "error":   ("background:#fab1a0; color:#7e0000;", "#d63031"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._label = QLabel("Waiting for Sensor\u2026")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "padding: 2px 8px; font-weight: bold; font-size: 12px; "
            "border-radius: 3px; " + self._COLORS["idle"][0]
        )
        lay.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setFixedHeight(4)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setStyleSheet(
            "QProgressBar { background: #dfe6e9; border: none; }"
            "QProgressBar::chunk { background: #b2bec3; }"
        )
        lay.addWidget(self._bar)
        self._state = "idle"

    def _apply(self, state: str, text: str, value: int = 0, maximum: int = 100):
        lbl_css, bar_color = self._COLORS.get(state, self._COLORS["idle"])
        if state != self._state:
            self._state = state
            self._label.setStyleSheet(
                "padding: 2px 8px; font-weight: bold; font-size: 12px; "
                "border-radius: 3px; " + lbl_css
            )
            self._bar.setStyleSheet(
                f"QProgressBar {{ background: #dfe6e9; border: none; }}"
                f"QProgressBar::chunk {{ background: {bar_color}; }}"
            )
        self._label.setText(text)
        self._bar.setRange(0, maximum)
        self._bar.setValue(value)

    def setFormat(self, text: str):
        self._label.setText(text)

    def setRange(self, lo: int, hi: int):
        self._bar.setRange(lo, hi)

    def setValue(self, v: int):
        self._bar.setValue(v)

    def set_idle(self, text: str = "Waiting for Sensor\u2026"):
        self._apply("idle", text)

    def set_settling(self, elapsed: int, total: int):
        remaining = max(0, total - elapsed)
        self._apply("settle", f"Settling\u2026  {remaining}s remaining",
                     elapsed, total)

    def set_baseline(self, elapsed: int, total: int):
        remaining = max(0, total - elapsed)
        self._apply("baseline",
                     f"Establishing Baselines\u2026  {remaining}s remaining",
                     elapsed, total)

    def set_locked(self, rmssd: str, hr: str):
        self._apply("locked",
                     f"\u2705  BASELINES LOCKED  \u2014  RMSSD {rmssd} ms  |  HR {hr} bpm",
                     1, 1)

    def set_disconnected(self):
        self._apply("idle", "Sensor Disconnected")

    def set_error(self, text: str):
        self._apply("error", text)


class Card0Dialog(QDialog):
    """Startup welcome/disclaimer card for Hertz & Hearts."""

    def __init__(self, parent=None, allow_skip_for_profile: bool = False):
        super().__init__(parent)
        self._allow_skip_for_profile = allow_skip_for_profile
        self.setWindowTitle("Hertz & Hearts — Welcome — Research Use Disclaimer")
        self.setMinimumSize(860, 700)
        self.setModal(True)

        self._heart_anim_groups = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: #f4f6f7; border: none; }")

        self._content = QWidget()
        self._content.setStyleSheet("QWidget { background: #f4f6f7; }")
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(40, 14, 40, 8)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignTop)

        logo = ClickableLabel()
        logo_pix = QPixmap(":/logo.png")
        if not logo_pix.isNull():
            logo.setPixmap(
                logo_pix.scaled(
                    88, 88,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            logo.setAlignment(Qt.AlignCenter)
            logo.setStyleSheet("margin-bottom: 4px;")
            lay.addWidget(logo)
            logo.clicked.connect(self._launch_heart_burst)
        self._logo = logo

        self._title = QLabel("Hertz & Hearts")
        self._title.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._title)

        self._tagline = QLabel("Cardiac Monitoring & Biofeedback Research Assistant")
        self._tagline.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._tagline)

        self._ver = QLabel(f"v{version}  ·  Investigational Use Only")
        self._ver.setAlignment(Qt.AlignCenter)
        ver_row = QHBoxLayout()
        ver_row.setAlignment(Qt.AlignCenter)
        ver_row.addWidget(self._ver)
        lay.addLayout(ver_row)

        self._card = QFrame()
        self._card.setStyleSheet(
            "QFrame { background: white; border-radius: 8px; border: 1px solid #e5e8ea; }"
        )
        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(24, 18, 24, 18)

        self._disclaimer = QLabel(_CARD0_DISCLAIMER_TEXT)
        self._disclaimer.setWordWrap(True)
        self._disclaimer.setTextFormat(Qt.RichText)
        card_lay.addWidget(self._disclaimer)
        lay.addWidget(self._card)
        lay.addSpacing(12)

        self._accept_cb = QCheckBox(
            "I have read, understood, and accept the above terms for this monitoring session"
        )
        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setEnabled(False)
        self._continue_btn.setDefault(True)
        self._continue_btn.clicked.connect(self.accept)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._dont_show_cb = QCheckBox("Don't show this disclaimer again for this user")
        self._dont_show_cb.setVisible(allow_skip_for_profile)
        # Keep this in a consistent bottom-left action lane to match the next screen.
        lay.addStretch()
        self._ack_row = QHBoxLayout()
        self._ack_row.setContentsMargins(2, 0, 2, 10)
        self._ack_row.addStretch()
        self._ack_row.addWidget(self._dont_show_cb, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        self._ack_row.addSpacing(20)
        self._ack_row.addWidget(self._accept_cb, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        self._ack_row.addStretch()
        lay.addLayout(self._ack_row)
        self._actions_row = QHBoxLayout()
        self._actions_row.setContentsMargins(2, 0, 2, 10)
        self._actions_row.addStretch()
        self._actions_row.addWidget(self._cancel_btn)
        self._actions_row.addSpacing(10)
        self._actions_row.addWidget(self._continue_btn)
        self._actions_row.addStretch()
        lay.addLayout(self._actions_row)

        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll)

        self._accept_cb.stateChanged.connect(self._on_ack_changed)
        QTimer.singleShot(0, self._fit_content_to_viewport)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_content_to_viewport()

    def _apply_scale(self, body_px: int, viewport_w: int):
        title_px = int(body_px * 2.2)
        tagline_px = max(13, int(body_px * 0.95))
        badge_px = max(10, int(body_px * 0.72))
        checkbox_px = max(12, int(body_px * 0.9))
        indicator_px = max(22, int(body_px * 1.5))
        # On narrower windows, the long acceptance label can dominate.
        # Slightly reduce only that line to keep both checkboxes visually balanced.
        accept_checkbox_px = max(11, checkbox_px - 1) if viewport_w < 1200 else checkbox_px

        self._title.setStyleSheet(
            f"color: #1a5276; font-size: {title_px}px; font-weight: 700;"
        )
        self._tagline.setStyleSheet(
            f"color: #7f8c8d; font-size: {tagline_px}px; margin-bottom: 4px;"
        )
        self._ver.setStyleSheet(
            "color: white; background: #c0392b; padding: 3px 14px; "
            f"border-radius: 4px; margin-bottom: 12px; font-size: {badge_px}px;"
        )
        self._ver.setFixedWidth(self._ver.sizeHint().width() + 28)
        self._disclaimer.setStyleSheet(
            f"color: #333; font-size: {body_px}px; line-height: 1.35;"
        )
        dont_show_css = (
            "QCheckBox { padding: 8px 0; spacing: 3px; color: #2c3e50; "
            f"font-size: {checkbox_px}px; font-weight: 600; }}"
            f"QCheckBox::indicator {{ width: {indicator_px}px; height: {indicator_px}px; }}"
        )
        accept_css = (
            "QCheckBox { padding: 8px 0; spacing: 3px; color: #2c3e50; "
            f"font-size: {accept_checkbox_px}px; font-weight: 600; }}"
            f"QCheckBox::indicator {{ width: {indicator_px}px; height: {indicator_px}px; }}"
        )
        self._accept_cb.setStyleSheet(accept_css)
        self._dont_show_cb.setStyleSheet(dont_show_css)

    def _fit_content_to_viewport(self):
        viewport = self._scroll.viewport()
        viewport_h = viewport.height()
        viewport_w = viewport.width()
        if viewport_h <= 0 or viewport_w <= 0:
            return
        # Ensure wrapping is computed against the real viewport width.
        self._content.setFixedWidth(viewport_w)
        # Favor readability over fitting the entire card without scrolling.
        # Keep a large body font and allow vertical scroll as needed.
        self._apply_scale(16, viewport_w)
        self._content.layout().activate()
        self._content.adjustSize()
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def _on_ack_changed(self, _state: int):
        self._continue_btn.setEnabled(self._accept_cb.isChecked())

    @property
    def dont_show_again_for_profile(self) -> bool:
        return self._allow_skip_for_profile and self._dont_show_cb.isChecked()

    def _launch_heart_burst(self):
        if self._logo is None or self._logo.pixmap() is None:
            return
        center = self._logo.mapTo(self, self._logo.rect().center())
        palette = ["#ff4d6d", "#ff6b6b", "#ff5fa2", "#ff3b30", "#ff8fab"]
        count = 18
        second_wave_delay_ms = 420
        for i in range(count):
            delay_ms = i * 55 + random.randint(0, 40)
            QTimer.singleShot(
                delay_ms,
                lambda c=center, p=palette: self._spawn_heart(c, p),
            )
            QTimer.singleShot(
                second_wave_delay_ms + delay_ms,
                lambda c=center, p=palette: self._spawn_heart(c, p),
            )

    def _spawn_heart(self, center: QPoint, palette: list[str]):
        heart = QLabel("❤", self)
        size = random.randint(18, 34)
        heart.setStyleSheet(
            f"color: {random.choice(palette)}; font-size: {size}px; font-weight: 700;"
        )
        heart.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        heart.adjustSize()
        start = QPoint(center.x() - heart.width() // 2, center.y() - heart.height() // 2)
        heart.move(start)
        heart.show()
        heart.raise_()

        # True 360-degree burst around the logo.
        angle = random.uniform(0.0, 2.0 * math.pi)
        radius = random.randint(260, 620)
        dx = int(math.cos(angle) * radius)
        dy = int(math.sin(angle) * radius)
        end = QPoint(start.x() + dx, start.y() + dy)
        duration = random.randint(1800, 3200)

        pos_anim = QPropertyAnimation(heart, b"pos", self)
        pos_anim.setDuration(duration)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(end)
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity = QGraphicsOpacityEffect(heart)
        heart.setGraphicsEffect(opacity)
        fade_anim = QPropertyAnimation(opacity, b"opacity", self)
        fade_anim.setDuration(duration)
        fade_anim.setStartValue(1.0)
        fade_anim.setEndValue(0.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)

        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)
        group.finished.connect(lambda g=group, h=heart: self._cleanup_heart(g, h))
        self._heart_anim_groups.append(group)
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _cleanup_heart(self, group: QParallelAnimationGroup, heart: QLabel):
        try:
            self._heart_anim_groups.remove(group)
        except ValueError:
            pass
        heart.deleteLater()


class ProfileSelectionDialog(QDialog):
    """Select the active user profile for this app session."""

    def __init__(self, profiles: list[str], last_profile: str | None, parent=None):
        super().__init__(parent)
        self.selected_profile: str | None = None
        self.setModal(True)
        self.setWindowTitle("Select Session User")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        info = QLabel(
            "Choose who is using this session. This controls profile-specific settings and history."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("User profile:"))
        self._combo = QComboBox()
        self._combo.setEditable(False)
        unique_profiles = []
        seen: set[str] = set()
        for profile in profiles:
            p = str(profile).strip()
            if not p:
                continue
            key = p.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique_profiles.append(p)
        if not unique_profiles:
            unique_profiles = ["Default"]
        self._combo.addItems(unique_profiles)
        if last_profile:
            idx = self._combo.findText(last_profile, Qt.MatchFixedString)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        row.addWidget(self._combo, stretch=1)
        root.addLayout(row)

        buttons = QHBoxLayout()
        self._new_btn = QPushButton("New Profile...")
        self._new_btn.clicked.connect(self._create_profile)
        buttons.addWidget(self._new_btn)
        buttons.addStretch()
        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setDefault(True)
        self._continue_btn.clicked.connect(self._accept_selected)
        buttons.addWidget(self._continue_btn)
        buttons.addSpacing(8)
        self._guest_btn = QPushButton("Continue as Guest")
        self._guest_btn.clicked.connect(self._accept_guest)
        buttons.addWidget(self._guest_btn)
        buttons.addSpacing(8)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self._cancel_btn)
        root.addLayout(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_screen()

    def _center_on_screen(self):
        screen = self.screen()
        if screen is None and self.parentWidget() is not None:
            screen = self.parentWidget().screen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def _create_profile(self):
        text, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not ok:
            return
        name = text.strip()
        if not name:
            QMessageBox.warning(self, "Invalid Profile", "Profile name cannot be empty.")
            return
        idx = self._combo.findText(name, Qt.MatchFixedString)
        if idx < 0:
            self._combo.addItem(name)
            idx = self._combo.count() - 1
        self._combo.setCurrentIndex(idx)

    def _accept_selected(self):
        name = self._combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Profile Required", "Please select a profile.")
            return
        self.selected_profile = name
        self.accept()

    def _accept_guest(self):
        self.selected_profile = "Guest"
        self.accept()


class SessionHistoryDialog(QDialog):
    """Read-only session history list for the active profile."""

    def __init__(self, profile_name: str, sessions: list[dict[str, str | None]], parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(f"Session History — {profile_name}")
        self.resize(980, 520)

        root = QVBoxLayout(self)
        self._summary = QLabel("")
        self._summary.setStyleSheet("font-size: 12px; color: #2c3e50;")
        root.addWidget(self._summary)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["Started", "Session ID", "State", "Session Folder", "CSV Path"]
        )
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self._table, stretch=1)

        actions = QHBoxLayout()
        actions.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        root.addLayout(actions)

        self.populate(profile_name=profile_name, sessions=sessions)

    @staticmethod
    def _format_started(value: str | None) -> str:
        if value is None:
            return "--"
        raw = str(value).strip()
        if not raw:
            return "--"
        try:
            dt = datetime.fromisoformat(raw)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw

    def populate(self, profile_name: str, sessions: list[dict[str, str | None]]):
        self.setWindowTitle(f"Session History — {profile_name}")
        self._summary.setText(f"{len(sessions)} session(s) for profile: {profile_name}")
        self._table.setRowCount(len(sessions))
        for row_idx, row in enumerate(sessions):
            started = self._format_started(row.get("started_at"))
            session_id = str(row.get("session_id") or "--")
            state = str(row.get("state") or "--")
            session_dir = str(row.get("session_dir") or "--")
            csv_path = str(row.get("csv_path") or "--")
            values = [started, session_id, state, session_dir, csv_path]
            for col_idx, val in enumerate(values):
                self._table.setItem(row_idx, col_idx, QTableWidgetItem(val))
        self._table.resizeRowsToContents()


class ProfileManagerDialog(QDialog):
    """Manage user profiles (create, rename, archive/delete, restore)."""

    def __init__(self, store: ProfileStore, active_profile: str, parent=None):
        super().__init__(parent)
        self._store = store
        self._active_profile = active_profile
        self.setModal(True)
        self.setWindowTitle("Profile Manager")
        self.resize(780, 460)

        root = QVBoxLayout(self)
        hint = QLabel(
            "Manage profiles used for session history and per-user preferences."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        top = QHBoxLayout()
        self._show_archived = QCheckBox("Show archived profiles")
        self._show_archived.stateChanged.connect(self._refresh)
        top.addWidget(self._show_archived)
        top.addStretch()
        root.addLayout(top)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Profile", "Status", "Last Used", "Created"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionsClickable(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSortingEnabled(True)
        root.addWidget(self._table, stretch=1)

        details_group = QGroupBox("Profile Details")
        details_form = QFormLayout(details_group)
        demographics_row = QWidget()
        demographics_lay = QHBoxLayout(demographics_row)
        demographics_lay.setContentsMargins(0, 0, 0, 0)
        demographics_lay.setSpacing(8)

        age_label = QLabel("Age")
        self._age_input = QLineEdit()
        self._age_input.setPlaceholderText("1-130")
        self._age_input.setMaximumWidth(80)
        self._age_input.setAlignment(Qt.AlignRight)
        demographics_lay.addWidget(age_label)
        demographics_lay.addWidget(self._age_input)

        gender_label = QLabel("Gender")
        self._gender_input = QComboBox()
        self._gender_input.addItems(
            [
                "Male",
                "Female",
                "Prefer not to Say",
            ]
        )
        self._gender_input.setMaximumWidth(170)
        demographics_lay.addSpacing(10)
        demographics_lay.addWidget(gender_label)
        demographics_lay.addWidget(self._gender_input)
        demographics_lay.addStretch()
        details_form.addRow("Demographics", demographics_row)

        self._notes_input = QTextEdit()
        self._notes_input.setPlaceholderText("Optional profile notes")
        self._notes_input.setFixedHeight(84)
        details_form.addRow("Notes", self._notes_input)
        root.addWidget(details_group)

        actions = QHBoxLayout()
        self._create_btn = QPushButton("Create")
        self._create_btn.clicked.connect(self._create_profile)
        actions.addWidget(self._create_btn)

        self._rename_btn = QPushButton("Rename")
        self._rename_btn.clicked.connect(self._rename_profile)
        actions.addWidget(self._rename_btn)

        self._archive_btn = QPushButton("Archive")
        self._archive_btn.clicked.connect(self._archive_profile)
        actions.addWidget(self._archive_btn)

        self._restore_btn = QPushButton("Restore")
        self._restore_btn.clicked.connect(self._restore_profile)
        actions.addWidget(self._restore_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete_profile)
        actions.addWidget(self._delete_btn)
        actions.addStretch()

        save_close_btn = QPushButton("Save && Close")
        save_close_btn.clicked.connect(self._save_and_close)
        actions.addWidget(save_close_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        root.addLayout(actions)

        self._table.itemSelectionChanged.connect(self._update_action_states)
        self._table.itemSelectionChanged.connect(self._load_selected_details)
        self._refresh()

    def _selected_profile_name(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return str(value).strip() if value else None

    @staticmethod
    def _fmt_time(raw: str | None) -> str:
        if not raw:
            return "--"
        try:
            dt = datetime.fromisoformat(raw)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return str(raw)

    def _refresh(self):
        previous = self._selected_profile_name() or self._active_profile
        rows = self._store.list_profiles_info(
            include_archived=self._show_archived.isChecked()
        )
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for idx, row in enumerate(rows):
            name = str(row.get("name") or "")
            archived = bool(row.get("archived"))
            status = "Archived" if archived else "Active"
            if name.casefold() == self._active_profile.casefold():
                status = f"{status} (current)"

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, name)
            status_item = QTableWidgetItem(status)
            last_used_item = QTableWidgetItem(
                self._fmt_time(row.get("last_used_at") if isinstance(row.get("last_used_at"), str) else None)
            )
            created_item = QTableWidgetItem(
                self._fmt_time(row.get("created_at") if isinstance(row.get("created_at"), str) else None)
            )

            self._table.setItem(idx, 0, name_item)
            self._table.setItem(idx, 1, status_item)
            self._table.setItem(idx, 2, last_used_item)
            self._table.setItem(idx, 3, created_item)
        self._table.resizeRowsToContents()
        self._table.setSortingEnabled(True)
        if not self._select_row_by_profile(previous) and self._table.rowCount() > 0:
            self._table.selectRow(0)
        self._update_action_states()
        self._load_selected_details()

    def _select_row_by_profile(self, profile_name: str | None) -> bool:
        if not profile_name:
            return False
        needle = profile_name.casefold()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is None:
                continue
            value = str(item.data(Qt.UserRole) or item.text()).strip()
            if value.casefold() == needle:
                self._table.selectRow(row)
                return True
        return False

    def _update_action_states(self):
        name = self._selected_profile_name()
        has_selection = bool(name)
        is_current = (
            has_selection and name is not None and name.casefold() == self._active_profile.casefold()
        )
        archived = False
        if has_selection and name is not None:
            row = self._table.currentRow()
            archived_item = self._table.item(row, 1)
            archived = archived_item is not None and "Archived" in archived_item.text()
        self._rename_btn.setEnabled(has_selection)
        self._archive_btn.setEnabled(has_selection and not archived and not is_current)
        self._restore_btn.setEnabled(has_selection and archived)
        self._delete_btn.setEnabled(has_selection and not is_current)

    def _load_selected_details(self):
        name = self._selected_profile_name()
        if not name:
            self._age_input.clear()
            self._gender_input.setCurrentIndex(2)
            self._notes_input.clear()
            return
        try:
            details = self._store.get_profile_details(name)
        except ValueError:
            return
        age_raw = details.get("age")
        age_val = int(age_raw) if isinstance(age_raw, int) else 0
        self._age_input.setText(str(age_val) if 1 <= age_val <= 130 else "")
        gender_raw = str(details.get("gender") or "").strip()
        idx = self._gender_input.findText(gender_raw, Qt.MatchFixedString)
        self._gender_input.setCurrentIndex(idx if idx >= 0 else 2)
        self._notes_input.setPlainText(str(details.get("notes") or ""))

    def _save_details(self) -> bool:
        name = self._selected_profile_name()
        if not name:
            return True
        age_text = self._age_input.text().strip()
        age: int | None = None
        if age_text:
            if not age_text.isdigit():
                QMessageBox.warning(self, "Invalid Age", "Age must be a number between 1 and 130.")
                return False
            age = int(age_text)
            if age < 1 or age > 130:
                QMessageBox.warning(self, "Invalid Age", "Age must be a number between 1 and 130.")
                return False
        gender = self._gender_input.currentText().strip()
        notes = self._notes_input.toPlainText().strip()
        try:
            self._store.update_profile_details(
                name,
                age=age,
                gender=gender,
                notes=notes or None,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            return False
        self._refresh()
        self._select_row_by_profile(name)
        return True

    def _save_and_close(self):
        if self._save_details():
            self.accept()

    def _create_profile(self):
        text, ok = QInputDialog.getText(self, "Create Profile", "Profile name:")
        if not ok:
            return
        name = text.strip()
        if not name:
            QMessageBox.warning(self, "Invalid Profile", "Profile name cannot be empty.")
            return
        self._store.ensure_profile(name)
        self._refresh()

    def _rename_profile(self):
        current = self._selected_profile_name()
        if not current:
            return
        text, ok = QInputDialog.getText(
            self, "Rename Profile", "New profile name:", text=current
        )
        if not ok:
            return
        new_name = text.strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Profile", "Profile name cannot be empty.")
            return
        try:
            renamed = self._store.rename_profile(current, new_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Rename Failed", str(exc))
            return
        if current.casefold() == self._active_profile.casefold():
            self._active_profile = renamed
        self._refresh()

    def _archive_profile(self):
        current = self._selected_profile_name()
        if not current:
            return
        try:
            self._store.archive_profile(current)
        except ValueError as exc:
            QMessageBox.warning(self, "Archive Failed", str(exc))
            return
        self._refresh()

    def _restore_profile(self):
        current = self._selected_profile_name()
        if not current:
            return
        self._store.ensure_profile(current)
        self._refresh()

    def _delete_profile(self):
        current = self._selected_profile_name()
        if not current:
            return
        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile '{current}' and its indexed history records?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._store.delete_profile(current)
        except ValueError as exc:
            QMessageBox.warning(self, "Delete Failed", str(exc))
            return
        self._refresh()


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PacerWidget(QChartView):
    def __init__(self, x_values, y_values, color=BLUE):
        super().__init__()
        self.setSizePolicy(QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred))
        self.plot = QChart()
        self.plot.legend().setVisible(False)
        self.plot.setBackgroundRoundness(0)
        self.plot.setMargins(QMargins(0, 0, 0, 0))
        self.outline = QLineSeries()
        for x, y in zip(x_values, y_values):
            self.outline.append(x, y)
        self.disk = QAreaSeries(self.outline)
        self.disk.setColor(color)
        self.disk.setBorderColor(QColor(0, 0, 0, 0))
        self.plot.addSeries(self.disk)
        
        self.x_axis = QValueAxis()
        self.x_axis.setRange(-1, 1)
        self.x_axis.setVisible(False)
        self.plot.addAxis(self.x_axis, Qt.AlignBottom)
        self.disk.attachAxis(self.x_axis)
        
        self.y_axis = QValueAxis()
        self.y_axis.setRange(-1, 1)
        self.y_axis.setVisible(False)
        self.plot.addAxis(self.y_axis, Qt.AlignLeft)
        self.disk.attachAxis(self.y_axis)
        self.setChart(self.plot)

    def update_series(self, x_values, y_values):
        self.outline.replace([QPointF(x, y) for x, y in zip(x_values, y_values)])

    def sizeHint(self):
        height = self.size().height()
        return QSize(height, height)
    
class XYSeriesWidget(QChartView):
    def __init__(self, x_values, y_values, line_color=QColor(0, 0, 0)):
        super().__init__()
        self.plot = QChart()
        self.plot.legend().setVisible(False)
        self.plot.setBackgroundRoundness(0)
        self.plot.setMargins(QMargins(0, 0, 0, 0))

        self.time_series = QLineSeries()
        self.plot.addSeries(self.time_series)
        pen = self.time_series.pen()
        pen.setWidth(2)
        pen.setColor(line_color)
        self.time_series.setPen(pen)

        self.x_axis = QValueAxis()
        self.plot.addAxis(self.x_axis, Qt.AlignBottom)
        self.time_series.attachAxis(self.x_axis)

        self.y_axis = QValueAxis()
        self.y_axis.setRange(0, 100)
        self.plot.addAxis(self.y_axis, Qt.AlignLeft)
        self.time_series.attachAxis(self.y_axis)
        self.setChart(self.plot)

    def update_series(self, x_values, y_values):
        self.time_series.replace([QPointF(x, y) for x, y in zip(x_values, y_values)])


class EcgWindow(QMainWindow):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hertz & Hearts \u2014 ECG Monitor")
        self.setMinimumSize(600, 300)
        self.resize(900, 350)

        self._settings = Settings()
        self._display_sec = self._settings.ECG_DISPLAY_SECONDS
        self._view_sec = float(self._display_sec)
        # Keep a larger rolling history so zoom-out works immediately.
        self._history_sec = max(int(self._display_sec), 30)
        self._max_view_sec = float(self._history_sec)
        buf_size = ECG_SAMPLE_RATE * self._history_sec

        self._times = deque(maxlen=buf_size)
        self._values = deque(maxlen=buf_size)
        self._sample_count = 0

        self._pending = deque()
        self._got_first_data = False
        self._drain_rate = max(1, int(
            ECG_SAMPLE_RATE * (self._settings.ECG_REFRESH_MS / 1000.0)
        ))

        self._y_min_smooth = 0.0
        self._y_max_smooth = 0.0

        self._plot_widget = pg.PlotWidget(background='w')
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self._plot_widget.setLabel('left', 'ECG (mV)', color='k')
        self._plot_widget.setLabel('bottom', 'Seconds', color='k')
        self._plot_widget.getAxis('left').setTextPen('k')
        self._plot_widget.getAxis('bottom').setTextPen('k')
        self._plot_widget.getAxis('left').setPen(pg.mkPen('k'))
        self._plot_widget.getAxis('bottom').setPen(pg.mkPen('k'))
        self._plot_widget.setMouseEnabled(x=False, y=False)
        self._plot_widget.hideButtons()

        self._curve = self._plot_widget.plot(
            pen=pg.mkPen(color='k', width=1.2)
        )

        self._frozen = False
        self._timeline_offset_sec = 0.0
        self._synced_xrange: tuple[float, float] | None = None
        self._follow_main_xrange = True

        self._zoom_out_button = QPushButton("\u2212")
        self._zoom_out_button.setFixedWidth(28)
        self._zoom_out_button.setToolTip("Zoom Out (show more time)")
        self._zoom_out_button.clicked.connect(self._zoom_out)

        self._zoom_in_button = QPushButton("+")
        self._zoom_in_button.setFixedWidth(28)
        self._zoom_in_button.setToolTip("Zoom In (show less time)")
        self._zoom_in_button.clicked.connect(self._zoom_in)

        self._freeze_button = QPushButton("Freeze")
        self._freeze_button.setFixedWidth(80)
        self._freeze_button.clicked.connect(self._toggle_freeze)
        self._relock_button = QPushButton("Relock")
        self._relock_button.setFixedWidth(64)
        self._relock_button.setToolTip("Relock this chart to the main plot time range.")
        self._relock_button.clicked.connect(self._relock_to_main_xrange)
        self._relock_button.setEnabled(False)

        self._statusbar = QStatusBar()
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("font-size: 11px;")
        self._statusbar.addPermanentWidget(zoom_label)
        self._statusbar.addPermanentWidget(self._zoom_out_button)
        self._statusbar.addPermanentWidget(self._zoom_in_button)
        self._statusbar.addPermanentWidget(self._relock_button)
        self._statusbar.addPermanentWidget(self._freeze_button)
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Waiting for ECG data...")

        self.setCentralWidget(self._plot_widget)

        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(self._settings.ECG_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._redraw)

    def start(self):
        self._display_sec = self._settings.ECG_DISPLAY_SECONDS
        self._view_sec = float(self._display_sec)
        self._follow_main_xrange = True
        self._relock_button.setEnabled(False)
        self._history_sec = max(int(self._display_sec), 30)
        self._max_view_sec = float(self._history_sec)
        buf_size = ECG_SAMPLE_RATE * self._history_sec
        self._times = deque(maxlen=buf_size)
        self._values = deque(maxlen=buf_size)
        self._drain_rate = max(1, int(
            ECG_SAMPLE_RATE * (self._settings.ECG_REFRESH_MS / 1000.0)
        ))
        self._y_min_smooth = 0.0
        self._y_max_smooth = 0.0
        if len(self._pending) > buf_size:
            drop = len(self._pending) - buf_size
            for _ in range(drop):
                self._pending.popleft()
        inv_rate = 1.0 / ECG_SAMPLE_RATE
        while self._pending:
            val = self._pending.popleft()
            self._times.append(
                (self._sample_count * inv_rate) + self._timeline_offset_sec
            )
            self._values.append(val)
            self._sample_count += 1
        self._got_first_data = len(self._times) > 0
        self._refresh_timer.setInterval(self._settings.ECG_REFRESH_MS)
        self._refresh_timer.start()
        if self._got_first_data:
            self._statusbar.showMessage("ECG streaming...")
        else:
            self._statusbar.showMessage("Waiting for ECG data from sensor\u2026")

    def clear(self):
        self._refresh_timer.stop()
        self._times.clear()
        self._values.clear()
        self._pending.clear()
        self._sample_count = 0
        self._timeline_offset_sec = 0.0
        self._synced_xrange = None
        self._follow_main_xrange = True
        self._relock_button.setEnabled(False)
        self._got_first_data = False
        self._frozen = False
        self._freeze_button.setText("Freeze")
        self._plot_widget.setMouseEnabled(x=False, y=False)
        self._curve.setData([], [])
        self._statusbar.showMessage("Waiting for ECG data...")

    def stop(self):
        self._refresh_timer.stop()
        self._frozen = False
        self._freeze_button.setText("Freeze")
        self._plot_widget.setMouseEnabled(x=False, y=False)
        self._statusbar.showMessage("ECG stopped.")

    def _toggle_freeze(self):
        self.set_stream_frozen(not self._frozen)

    def set_stream_frozen(self, frozen: bool):
        self._frozen = bool(frozen)
        if self._frozen:
            self._freeze_button.setText("Resume")
            self._plot_widget.setMouseEnabled(x=True, y=False)
            self._statusbar.showMessage("ECG frozen \u2014 drag to pan, scroll wheel or +/\u2212 to zoom.")
        else:
            self._freeze_button.setText("Freeze")
            self._plot_widget.setMouseEnabled(x=False, y=False)
            self._view_sec = float(self._display_sec)
            self._statusbar.showMessage(
                "ECG streaming..." if self._got_first_data else "Waiting for ECG data..."
            )

    def _zoom_in(self):
        if self._follow_main_xrange:
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
        self._view_sec = max(0.5, self._view_sec / 2)
        if self._frozen:
            self._refresh_frozen_view()

    def _zoom_out(self):
        if self._follow_main_xrange:
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
        self._view_sec = min(self._max_view_sec, self._view_sec * 2)
        if self._frozen:
            self._refresh_frozen_view()

    def _relock_to_main_xrange(self):
        self._follow_main_xrange = True
        self._relock_button.setEnabled(False)
        if self._synced_xrange is not None and not self._frozen:
            x_lo, x_hi = self._synced_xrange
            self._plot_widget.setXRange(x_lo, x_hi, padding=0)

    def _refresh_frozen_view(self):
        if len(self._times) < 2:
            return
        t_arr = np.array(self._times)
        current_range = self._plot_widget.viewRange()[0]
        center = (current_range[0] + current_range[1]) / 2
        half = self._view_sec / 2
        t_lo = max(float(t_arr[0]), center - half)
        t_hi = t_lo + self._view_sec
        if t_hi > float(t_arr[-1]):
            t_hi = float(t_arr[-1])
            t_lo = max(float(t_arr[0]), t_hi - self._view_sec)
        self._plot_widget.setXRange(t_lo, t_hi, padding=0)

    def append_samples(self, samples: list):
        self._pending.extend(samples)
        max_pending = ECG_SAMPLE_RATE * 10
        while len(self._pending) > max_pending:
            self._pending.popleft()

    def sync_timeline_to_main(self, main_plot_delay_sec: float):
        inv_rate = 1.0 / ECG_SAMPLE_RATE
        current_raw_t = self._sample_count * inv_rate
        new_offset = -float(main_plot_delay_sec) - current_raw_t
        delta = new_offset - self._timeline_offset_sec
        if delta != 0.0 and self._times:
            self._times = deque(
                (t + delta for t in self._times),
                maxlen=self._times.maxlen,
            )
        self._timeline_offset_sec = new_offset

    def set_synced_xrange(self, x_lo: float, x_hi: float):
        self._synced_xrange = (float(x_lo), float(x_hi))
        if self._follow_main_xrange and self._times:
            target_right = float(x_hi) - 2.0
            latest = float(self._times[-1])
            delta = target_right - latest
            # Keep ECG trace anchored to the same right-edge semantics as main.
            if abs(delta) > 0.75:
                self._times = deque(
                    (t + delta for t in self._times),
                    maxlen=self._times.maxlen,
                )
                self._timeline_offset_sec += delta
        if self._follow_main_xrange and not self._frozen:
            self._plot_widget.setXRange(float(x_lo), float(x_hi), padding=0)

    def _redraw(self):
        if self._frozen:
            return

        n_pending = len(self._pending)
        if n_pending == 0:
            return

        if not self._got_first_data:
            self._got_first_data = True
            self._statusbar.showMessage("ECG streaming...")

        if n_pending > 200:
            drain = min(50, n_pending)
        elif n_pending > 100:
            drain = min(20, n_pending)
        else:
            drain = min(self._drain_rate + 2, n_pending)

        inv_rate = 1.0 / ECG_SAMPLE_RATE
        for _ in range(drain):
            val = self._pending.popleft()
            self._times.append(
                (self._sample_count * inv_rate) + self._timeline_offset_sec
            )
            self._values.append(val)
            self._sample_count += 1

        n = len(self._times)
        if n < 2:
            return

        t_arr = np.array(self._times)
        v_arr = np.array(self._values)

        y_lo = float(v_arr.min())
        y_hi = float(v_arr.max())
        margin = max(0.1, (y_hi - y_lo) * 0.15)
        target_lo = y_lo - margin
        target_hi = y_hi + margin
        alpha = 0.15
        self._y_min_smooth += alpha * (target_lo - self._y_min_smooth)
        self._y_max_smooth += alpha * (target_hi - self._y_max_smooth)
        self._plot_widget.setYRange(self._y_min_smooth, self._y_max_smooth, padding=0)

        t_max = float(t_arr[-1])
        if self._follow_main_xrange and self._synced_xrange is not None:
            x_lo, x_hi = self._synced_xrange
            self._plot_widget.setXRange(x_lo, x_hi, padding=0)
        else:
            x_hi = t_max + 2.0
            x_lo = x_hi - self._view_sec
            self._plot_widget.setXRange(x_lo, x_hi, padding=0)

        self._curve.setData(t_arr, v_arr)

    def closeEvent(self, event):
        self.stop()
        self.closed.emit()
        super().closeEvent(event)


class QtcWindow(QMainWindow):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hertz & Hearts — QTc Monitor")
        self.setMinimumSize(600, 300)
        self.resize(900, 350)

        self._plot_widget = pg.PlotWidget(background="w")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self._plot_widget.setLabel("left", "QTc (ms)", color="k")
        self._plot_widget.setLabel("bottom", "Seconds", color="k")
        self._plot_widget.getAxis("left").setTextPen("k")
        self._plot_widget.getAxis("bottom").setTextPen("k")
        self._plot_widget.getAxis("left").setPen(pg.mkPen("k"))
        self._plot_widget.getAxis("bottom").setPen(pg.mkPen("k"))
        self._plot_widget.getAxis("bottom").enableAutoSIPrefix(False)
        self._plot_widget.setYRange(410, 505, padding=0)
        self._plot_widget.setXRange(0, 60, padding=0)
        self._plot_widget.addLegend(offset=(8, 8))

        # Highlight elevated QTc region.
        self._high_qtc_region = pg.LinearRegionItem(
            values=(470, 510),
            orientation=pg.LinearRegionItem.Horizontal,
            movable=False,
            brush=(220, 80, 80, 32),
            pen=pg.mkPen((220, 80, 80, 40)),
        )
        self._plot_widget.addItem(self._high_qtc_region)
        self._threshold_line = pg.InfiniteLine(
            pos=470,
            angle=0,
            pen=pg.mkPen((180, 90, 90, 170), width=1),
        )
        self._plot_widget.addItem(self._threshold_line)
        self._threshold_label = pg.TextItem(
            text="470 ms threshold",
            color=(120, 80, 80),
            anchor=(1, 0),
        )
        self._plot_widget.addItem(self._threshold_label)

        self._upper_curve = self._plot_widget.plot(
            pen=pg.mkPen((60, 120, 190, 30), width=1),
            name="Uncertainty band (IQR)",
        )
        self._lower_curve = self._plot_widget.plot(pen=pg.mkPen((60, 120, 190, 30), width=1))
        self._band = pg.FillBetweenItem(
            self._upper_curve, self._lower_curve, brush=pg.mkBrush(70, 130, 210, 70)
        )
        self._plot_widget.addItem(self._band)

        self._median_curve = self._plot_widget.plot(
            pen=pg.mkPen((30, 78, 153), width=2.2),
            name="Rolling median QTc",
        )
        self._low_quality_curve = self._plot_widget.plot(
            pen=pg.mkPen((85, 140, 205), width=2, style=Qt.DashLine),
            name="Low-quality interval",
        )

        self._statusbar = QStatusBar()
        self._info_button = QPushButton("Info")
        self._info_button.setFixedWidth(64)
        self._info_button.setToolTip("How to interpret QTc trend and uncertainty.")
        self._info_button.clicked.connect(self._show_info)
        self._freeze_button = QPushButton("Freeze QTc")
        self._freeze_button.setFixedWidth(92)
        self._freeze_button.clicked.connect(self._toggle_freeze)
        self._statusbar.addPermanentWidget(self._info_button)
        self._statusbar.addPermanentWidget(self._freeze_button)
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage(
            "Waiting for QTc trend points... For trend context only; clinical interpretation requires review."
        )

        self.setCentralWidget(self._plot_widget)
        self._frozen = False
        self._timeline_offset_sec = 0.0
        self._synced_xrange: tuple[float, float] | None = None
        self._history_sec = 20 * 60
        self._times = deque(maxlen=1200)
        self._medians = deque(maxlen=1200)
        self._p25 = deque(maxlen=1200)
        self._p75 = deque(maxlen=1200)
        self._lowq = deque(maxlen=1200)

    def _show_info(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("QTc Trend Guide")
        msg.setText(
            "<b>How to read this chart</b><br><br>"
            "• <b>Rolling median QTc</b>: smoothed central QTc estimate.<br>"
            "• <b>Uncertainty band (IQR)</b>: wider band means less confidence.<br>"
            "• <b>Dashed segments</b>: lower signal quality periods.<br>"
            "• <b>Shaded area above 470 ms</b>: elevated reference zone."
        )
        msg.setInformativeText("Trend context only; requires clinical review.")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setMinimumWidth(520)
        flags = msg.windowFlags()
        flags &= ~Qt.WindowMinimizeButtonHint
        flags &= ~Qt.WindowMaximizeButtonHint
        flags |= Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
        msg.setWindowFlags(flags)
        msg.open()

    def clear(self):
        self._times.clear()
        self._medians.clear()
        self._p25.clear()
        self._p75.clear()
        self._lowq.clear()
        self._timeline_offset_sec = 0.0
        self._synced_xrange = None
        self._median_curve.setData([], [])
        self._low_quality_curve.setData([], [])
        self._upper_curve.setData([], [])
        self._lower_curve.setData([], [])
        self._statusbar.showMessage("Waiting for QTc trend points...")

    def start(self):
        self._frozen = False
        self._freeze_button.setText("Freeze QTc")

    def stop(self):
        self._frozen = False
        self._freeze_button.setText("Freeze QTc")

    def _toggle_freeze(self):
        self.set_stream_frozen(not self._frozen)

    def set_stream_frozen(self, frozen: bool):
        self._frozen = bool(frozen)
        self._freeze_button.setText("Resume QTc" if self._frozen else "Freeze QTc")
        if self._frozen:
            self._statusbar.showMessage("QTc view frozen.")
        else:
            self._statusbar.showMessage("QTc streaming.")
            self._redraw()

    def sync_timeline_to_main(self, main_plot_delay_sec: float):
        current_raw_t = float(self._times[-1]) if self._times else 0.0
        new_offset = -float(main_plot_delay_sec) - current_raw_t
        delta = new_offset - self._timeline_offset_sec
        if delta != 0.0 and self._times:
            self._times = deque(
                (t + delta for t in self._times),
                maxlen=self._times.maxlen,
            )
        self._timeline_offset_sec = new_offset

    def set_synced_xrange(self, x_lo: float, x_hi: float):
        self._synced_xrange = (float(x_lo), float(x_hi))
        if self._times:
            target_right = float(x_hi) - 2.0
            latest = float(self._times[-1])
            delta = target_right - latest
            # QTc updates less frequently; tolerate small lag, correct large drift.
            if abs(delta) > 4.0:
                self._times = deque(
                    (t + delta for t in self._times),
                    maxlen=self._times.maxlen,
                )
                self._timeline_offset_sec += delta
        if not self._frozen:
            self._plot_widget.setXRange(float(x_lo), float(x_hi), padding=0)

    def append_payload(self, payload: dict):
        if not isinstance(payload, dict):
            return
        trend_point = payload.get("trend_point")
        if not isinstance(trend_point, dict):
            quality = payload.get("quality", {}) if isinstance(payload, dict) else {}
            reason = quality.get("reason") if isinstance(quality, dict) else None
            if isinstance(reason, str) and reason.strip():
                self._statusbar.showMessage(f"QTc waiting: {reason}.")
            return
        try:
            t_sec = float(trend_point["t_sec"]) + self._timeline_offset_sec
            median_ms = float(trend_point["median_ms"])
            p25_ms = float(trend_point["p25_ms"])
            p75_ms = float(trend_point["p75_ms"])
            is_low_quality = bool(trend_point.get("is_low_quality", False))
        except (KeyError, TypeError, ValueError):
            return

        # Stream resets can rewind t_sec to near zero; clear stale history to
        # prevent overplotted artifacts after reconnect/recovery.
        if self._times and t_sec < (self._times[-1] - 5.0):
            self.clear()

        if self._times and t_sec <= self._times[-1]:
            self._times[-1] = t_sec
            self._medians[-1] = median_ms
            self._p25[-1] = p25_ms
            self._p75[-1] = p75_ms
            self._lowq[-1] = is_low_quality
        else:
            self._times.append(t_sec)
            self._medians.append(median_ms)
            self._p25.append(p25_ms)
            self._p75.append(p75_ms)
            self._lowq.append(is_low_quality)
        if not self._frozen:
            self._redraw()

    def _redraw(self):
        if len(self._times) < 1:
            return

        x = np.asarray(self._times, dtype=float)
        y = np.asarray(self._medians, dtype=float)
        lo = np.asarray(self._p25, dtype=float)
        hi = np.asarray(self._p75, dtype=float)
        lowq = np.asarray(self._lowq, dtype=bool)
        order = np.argsort(x)
        x = x[order]
        y = y[order]
        lo = lo[order]
        hi = hi[order]
        lowq = lowq[order]

        y_good = y.copy()
        y_good[lowq] = np.nan
        y_bad = y.copy()
        y_bad[~lowq] = np.nan

        self._upper_curve.setData(x, hi)
        self._lower_curve.setData(x, lo)
        self._median_curve.setData(x, y_good)
        self._low_quality_curve.setData(x, y_bad)

        x_hi = float(x[-1])
        x_lo = max(0.0, x_hi - 60.0)
        if len(x) == 1:
            x_lo = max(0.0, x_hi - 2.0)
        if self._synced_xrange is not None:
            x_lo, x_hi = self._synced_xrange
            self._plot_widget.setXRange(x_lo, x_hi, padding=0)
            self._threshold_label.setPos(x_hi - 1.0, 471)
        else:
            self._plot_widget.setXRange(x_lo, x_hi + 2.0, padding=0)
            self._threshold_label.setPos(x_hi + 1.0, 471)
        self._statusbar.showMessage(
            "QTc streaming. For trend context only; clinical interpretation requires review."
        )

    def closeEvent(self, event):
        self.stop()
        self.closed.emit()
        super().closeEvent(event)


class PoincareWindow(QMainWindow):
    closed = Signal()
    info_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hertz & Hearts — Poincare Plot")
        self.setMinimumSize(520, 420)
        self.resize(760, 560)
        self._window_beats = 120
        self._auto_scale = True
        self._locked_bounds: tuple[float, float] | None = None

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self._scale_button = QPushButton("Scale: AUTO")
        self._scale_button.setToolTip("Toggle between auto-scaling and locked scale.")
        self._scale_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._scale_button.clicked.connect(self._toggle_scale_mode)
        header.addWidget(self._scale_button)
        header.addStretch()
        self._info_button = QPushButton("i")
        self._info_button.setFixedWidth(22)
        self._info_button.setToolTip("What is a Poincare plot?")
        self._info_button.setStyleSheet("font-size: 11px; padding: 2px 4px;")
        self._info_button.clicked.connect(self.info_requested.emit)
        header.addWidget(self._info_button)
        layout.addLayout(header)

        self._plot = pg.PlotWidget(background="w")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("left", "RR(n+1) [ms]", color="k")
        self._plot.setLabel("bottom", "RR(n) [ms]", color="k")
        self._plot.getAxis("left").setTextPen("k")
        self._plot.getAxis("bottom").setTextPen("k")
        self._plot.getAxis("left").setPen(pg.mkPen("k"))
        self._plot.getAxis("bottom").setPen(pg.mkPen("k"))
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.hideButtons()

        self._identity = self._plot.plot(
            pen=pg.mkPen(color=(150, 150, 150), width=1, style=Qt.DashLine)
        )
        self._scatter = pg.ScatterPlotItem(
            size=7,
            pen=pg.mkPen(color=(25, 118, 210, 180), width=1),
            brush=pg.mkBrush(66, 165, 245, 120),
        )
        self._plot.addItem(self._scatter)
        layout.addWidget(self._plot, stretch=1)

        metrics_row = QHBoxLayout()
        self._sd1_label = QLabel("SD1: -- ms")
        self._sd2_label = QLabel("SD2: -- ms")
        self._ratio_label = QLabel("SD1/SD2: --")
        for label in (self._sd1_label, self._sd2_label, self._ratio_label):
            label.setStyleSheet(
                "font-size: 11px; color: #2c3e50; "
                "border: 1px solid #bdc3c7; border-radius: 3px; "
                "padding: 2px 8px; background: #f8f9fa;"
            )
            metrics_row.addWidget(label)
        metrics_row.addStretch()
        layout.addLayout(metrics_row)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Waiting for beat data...")

    def _apply_square_bounds(self, lo: float, hi: float):
        self._plot.setXRange(lo, hi, padding=0)
        self._plot.setYRange(lo, hi, padding=0)
        self._identity.setData([lo, hi], [lo, hi])

    def _toggle_scale_mode(self):
        self._auto_scale = not self._auto_scale
        if self._auto_scale:
            self._scale_button.setText("Scale: AUTO")
            self._locked_bounds = None
            self.statusBar().showMessage("Scale mode: AUTO")
            return
        self._scale_button.setText("Scale: LOCK")
        x_rng, y_rng = self._plot.viewRange()
        lo = float(min(x_rng[0], y_rng[0]))
        hi = float(max(x_rng[1], y_rng[1]))
        if hi - lo < 10.0:
            center = (hi + lo) / 2.0
            lo = center - 5.0
            hi = center + 5.0
        self._locked_bounds = (lo, hi)
        self._apply_square_bounds(lo, hi)
        self.statusBar().showMessage("Scale mode: LOCK")

    def clear(self):
        self._scatter.setData([], [])
        self._identity.setData([], [])
        self._sd1_label.setText("SD1: -- ms")
        self._sd2_label.setText("SD2: -- ms")
        self._ratio_label.setText("SD1/SD2: --")
        self.statusBar().showMessage("Waiting for beat data...")

    def update_from_ibis(self, rr_ms: list[float]):
        if len(rr_ms) < 3:
            self.clear()
            return
        rr = np.asarray(rr_ms[-self._window_beats:], dtype=float)
        if rr.size < 3:
            self.clear()
            return
        x = rr[:-1]
        y = rr[1:]
        self._scatter.setData(x, y)

        xy_min = float(min(x.min(), y.min()))
        xy_max = float(max(x.max(), y.max()))
        pad = max(20.0, (xy_max - xy_min) * 0.1)
        lo = xy_min - pad
        hi = xy_max + pad
        if self._auto_scale:
            self._apply_square_bounds(lo, hi)
        else:
            if self._locked_bounds is None:
                self._locked_bounds = (lo, hi)
            self._apply_square_bounds(*self._locked_bounds)

        rr_diff = np.diff(rr)
        rr_std = float(np.std(rr, ddof=1)) if rr.size > 2 else 0.0
        diff_std = float(np.std(rr_diff, ddof=1)) if rr_diff.size > 1 else 0.0
        sd1 = float(np.sqrt(max(0.0, 0.5 * (diff_std ** 2))))
        sd2_term = max(0.0, 2.0 * (rr_std ** 2) - 0.5 * (diff_std ** 2))
        sd2 = float(np.sqrt(sd2_term))
        ratio = (sd1 / sd2) if sd2 > 1e-12 else 0.0

        self._sd1_label.setText(f"SD1: {sd1:.2f} ms")
        self._sd2_label.setText(f"SD2: {sd2:.2f} ms")
        self._ratio_label.setText(f"SD1/SD2: {ratio:.3f}")
        mode = "AUTO" if self._auto_scale else "LOCK"
        self.statusBar().showMessage(f"Showing last {rr.size} beats | Scale: {mode}")

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class ViewSignals(QObject):
    annotation = Signal(tuple)
    start_recording = Signal(str)
    save_recording = Signal()
    request_buffer_reset = Signal() 

class View(QMainWindow):
    def __init__(self, model: Model):
        super().__init__()
        self._maximized_once = False
        self.setStyleSheet(
            "QToolTip {"
            "color: #ffffff;"
            "background-color: #111111;"
            "border: 1px solid #aab2bd;"
            "padding: 3px 6px;"
            "}"
        )

        # 1. TRACKERS & STATE
        self.settings = Settings()
        self.model = model
        self.baseline_values = []
        self.baseline_rmssd = None
        self.baseline_hr_values = []
        self.baseline_hr = None
        self.start_time = None 
        self._plot_start_delay_seconds = 1.5
        self.is_phase_active = False
        self._fault_active = False
        self._consecutive_good = 0
        self._hr_ewma = None
        self._signal_popup_shown = False
        self._signal_degrade_count = 0
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_ceiling = None
        self._main_plots_frozen = False
        self._all_plots_frozen = False
        self._phase_debug_last_second = -1
        self._phase_debug_last_name = ""
        self._debug_heart_anim_groups = []
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._last_data_time = None
        self._session_annotations: list[tuple[str, str]] = []
        self._session_hr_values: list[float] = []
        self._session_rmssd_values: list[float] = []
        self._session_qtc_payload: dict = default_qtc_payload()
        self._session_state = "idle"
        self._session_bundle: SessionBundle | None = None
        self._session_root = Path.home() / "Hertz-and-Hearts"
        self._profile_store = ProfileStore(self._session_root)
        self._session_profile_id = (
            self._profile_store.get_last_active_profile() or "Default"
        )
        self._profile_store.ensure_profile(self._session_profile_id)

        self.setWindowTitle(f"Hertz & Hearts ({version})")
        self.setWindowIcon(QIcon(":/logo.png"))

        # 2. DATA CONNECTIONS
        self.model.ibis_buffer_update.connect(self.plot_ibis)
        self.model.ibis_buffer_update.connect(self.update_ui_labels)
        self.model.stress_ratio_update.connect(self.update_ui_labels)
        self.model.hrv_update.connect(self.update_ui_labels)
        self.model.hrv_update.connect(self.direct_chart_update)
        self.model.qtc_update.connect(self.update_ui_labels)

        self.model.addresses_update.connect(self.list_addresses)
        self.model.pacer_rate_update.connect(self.update_pacer_label)
        self.model.hrv_target_update.connect(self.update_hrv_target)

        # 3. COMPONENT INITIALIZATION
        self.signals = ViewSignals()
        self.signals.request_buffer_reset.connect(self._handle_stream_reset)
        self.pacer = Pacer()
        self.pacer_timer = QTimer()
        self.pacer_timer.setInterval(int(1000 / 8))
        self.pacer_timer.timeout.connect(self.plot_pacer_disk)

        self._data_watchdog = QTimer()
        self._data_watchdog.setInterval(5000)
        self._data_watchdog.timeout.connect(self._check_data_timeout)

        self.scanner = SensorScanner()
        self.scanner.sensor_update.connect(self.model.update_sensors)
        self.scanner.status_update.connect(self.show_status)

        self.sensor = SensorClient()
        self.sensor.ibi_update.connect(self.model.update_ibis_buffer)
        self.sensor.ecg_update.connect(self.model.update_ecg_samples)
        self.sensor.status_update.connect(self.show_status)

        self.ecg_window = EcgWindow()
        self.qtc_window = QtcWindow()
        self.model.qtc_update.connect(lambda data: self.qtc_window.append_payload(data.value))
        self.sensor.ecg_update.connect(self.ecg_window.append_samples)
        self.sensor.ecg_ready.connect(self._on_ecg_ready)
        self.ecg_window.closed.connect(self._on_ecg_window_closed)
        self.qtc_window.closed.connect(self._on_qtc_window_closed)
        self.poincare_window = PoincareWindow()
        self.poincare_window.closed.connect(self._on_poincare_window_closed)
        self.poincare_window.info_requested.connect(self.show_poincare_info)
        self.model.ibis_buffer_update.connect(self._update_poincare)

        self.logger = Logger()
        self.logger_thread = QThread()
        self.logger.moveToThread(self.logger_thread)
        self.logger_thread.finished.connect(self.logger.save_recording)
        self.signals.start_recording.connect(self.logger.start_recording)
        self.signals.save_recording.connect(self.logger.save_recording)
        self.signals.annotation.connect(self.logger.write_to_file)
        self.logger.recording_status.connect(self.show_recording_status)
        self.logger.status_update.connect(self.show_status)
        self.model.hrv_update.connect(self.logger.write_to_file)

        # 4. UI WIDGETS
        self.ibis_widget = XYSeriesWidget(self.model.ibis_seconds, self.model.ibis_buffer)
        self.ibis_widget.y_axis.setRange(40, 160)

        self.ibis_widget.plot.removeSeries(self.ibis_widget.time_series)

        self.hr_trend_series = QLineSeries()
        self.hr_trend_series.setName("Averaged Heart Rate (bpm)")
        pen = QPen(QColor(0, 0, 0))
        pen.setStyle(Qt.SolidLine)
        pen.setWidth(2)
        self.hr_trend_series.setPen(pen)
        self.ibis_widget.plot.addSeries(self.hr_trend_series)
        self.hr_trend_series.attachAxis(self.ibis_widget.x_axis)
        self.hr_trend_series.attachAxis(self.ibis_widget.y_axis)

        self.ibis_widget.plot.legend().setVisible(True)
        self.ibis_widget.plot.legend().setAlignment(Qt.AlignTop)

        self.hr_y_axis_right = QValueAxis()
        self.hr_y_axis_right.setLabelsVisible(False)
        self.hr_y_axis_right.setTitleText(" ")
        self.hr_y_axis_right.setRange(40, 160)
        self.ibis_widget.plot.addAxis(self.hr_y_axis_right, Qt.AlignRight)
        self.hr_trend_series.attachAxis(self.hr_y_axis_right)

        self.hrv_widget = XYSeriesWidget(self.model.hrv_seconds, self.model.hrv_buffer)
        self.hrv_widget.y_axis.setRange(0, 10)
        self.hrv_widget.time_series.setName("RMSSD (ms)")
        self.hrv_widget.plot.legend().setVisible(True)
        self.hrv_widget.plot.legend().setAlignment(Qt.AlignTop)

        self.sdnn_series = QLineSeries()
        self.sdnn_series.setName("HRV/SDNN (ms)")
        sdnn_color = QColor(0, 130, 255)
        pen = QPen(sdnn_color)
        pen.setWidth(2)
        self.sdnn_series.setPen(pen)

        self.hrv_y_axis_right = QValueAxis()
        self.hrv_y_axis_right.setTitleText("HRV/SDNN (ms)")
        self.hrv_y_axis_right.setTitleBrush(QBrush(sdnn_color))
        self.hrv_y_axis_right.setLabelsColor(sdnn_color)
        self.hrv_y_axis_right.setRange(0, 50)
        self.hrv_widget.plot.addAxis(self.hrv_y_axis_right, Qt.AlignRight)

        self.hrv_widget.plot.addSeries(self.sdnn_series)
        self.sdnn_series.attachAxis(self.hrv_widget.x_axis)
        self.sdnn_series.attachAxis(self.hrv_y_axis_right)

        self.pacer_widget = PacerWidget(self.pacer.lung_x, self.pacer.lung_y)
        self.pacer_widget.setFixedSize(200, 200)

        self._hr_overlay = self._make_chart_overlay(self.ibis_widget)
        self._hr_overlay.show()
        self._hrv_overlay = self._make_chart_overlay(self.hrv_widget)
        self._hrv_overlay.show()
        self.ibis_widget.installEventFilter(self)
        self.hrv_widget.installEventFilter(self)

        self._connect_pulse_timer = QTimer()
        self._connect_pulse_timer.setInterval(700)
        self._connect_pulse_timer.timeout.connect(self._pulse_connect_button)
        self._connect_attempt_timer = QTimer()
        self._connect_attempt_timer.setSingleShot(True)
        self._connect_attempt_timer.setInterval(15000)
        self._connect_attempt_timer.timeout.connect(self._on_connect_timeout)
        self._connect_pulse_on = False
        self._connect_pulse_active = False
        self._scan_pulse_active = False
        self._preserve_good_on_reset = False

        self.recording_statusbar = StatusBanner()

        # Labels
        self.current_hr_label = QLabel("HR: --")
        self.rmssd_label = QLabel("RMSSD: --")
        self.sdnn_label = QLabel("SDNN: --")
        self.stress_ratio_label = QLabel("LF/HF: --")
        self.health_indicator = QLabel("\u25cf")
        self.health_indicator.setStyleSheet("color: gray; font-size: 18px;")
        self.health_label = QLabel("Signal: Identifying...")

        # Pacer controls
        self.pacer_label = QLabel("Rate: 7")
        self.pacer_rate = QSlider(Qt.Horizontal)
        self.pacer_rate.setRange(3, 15)
        self.pacer_rate.setValue(7)
        self.pacer_rate.setTickPosition(QSlider.TicksBelow)
        self.pacer_rate.setTickInterval(1)
        self.pacer_rate.setSingleStep(1)
        self.pacer_rate.valueChanged.connect(self._update_breathing_rate)
        self.pacer_toggle = QCheckBox("Show Pacer")
        self.pacer_toggle.setChecked(True)
        self.pacer_toggle.stateChanged.connect(self.toggle_pacer)

        self.pacer_group = QGroupBox("Breathing Pacer")
        self.pacer_group.setStyleSheet(
            "QGroupBox { margin-top: 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 6px; padding: 0 2px; }"
        )
        self.pacer_config = QFormLayout(self.pacer_group)
        self.pacer_config.setContentsMargins(6, 2, 6, 4)
        self.pacer_config.setVerticalSpacing(2)
        self.pacer_config.addRow(self.pacer_label, self.pacer_rate)
        self.pacer_config.addRow(self.pacer_toggle)

        # Buttons
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.scanner.scan)
        self.address_menu = QComboBox()
        saved = _load_last_sensor()
        if saved:
            self.address_menu.addItem(f"{saved['name']}, {saved['address']}")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setAutoDefault(True)
        self.connect_button.setDefault(False)
        self.connect_button.clicked.connect(self.connect_sensor)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self.disconnect_sensor)
        
        self.reset_button = QPushButton("Reset Baseline")
        self.reset_button.setEnabled(False)
        self.reset_button.clicked.connect(self.reset_baseline)
        self.reset_axes_button = QPushButton("Reset Y Axes")
        self.reset_axes_button.clicked.connect(self.reset_y_axes)
        self.freeze_two_main_plots_button = QPushButton("Freeze Two Main Plots")
        self.freeze_two_main_plots_button.clicked.connect(self._toggle_two_main_plots_freeze)
        self.freeze_all_button = QPushButton("Freeze All")
        self.freeze_all_button.clicked.connect(self._toggle_freeze_all)

        self.ecg_button = QPushButton("ECG (starting...)")
        self.ecg_button.setEnabled(False)
        self.ecg_button.clicked.connect(self.toggle_ecg_window)
        self.qtc_button = QPushButton("QTc (starting...)")
        self.qtc_button.setEnabled(False)
        self.qtc_button.clicked.connect(self.toggle_qtc_window)
        self.poincare_button = QPushButton("Poincare (starting...)")
        self.poincare_button.setEnabled(False)
        self.poincare_button.clicked.connect(self.toggle_poincare_window)

        self.start_recording_button = QPushButton("Start")
        self.start_recording_button.clicked.connect(self.start_session)
        self.save_recording_button = QPushButton("Save")
        self.save_recording_button.clicked.connect(self.finalize_session)
        self.export_report_button = QPushButton("Report")
        self.export_report_button.clicked.connect(self.export_report)
        self.history_button = QPushButton("History")
        self.history_button.clicked.connect(self._open_history)
        self.profile_manager_button = QPushButton("Profiles")
        self.profile_manager_button.clicked.connect(self._open_profile_manager)

        self.annotation = QComboBox()
        self.annotation.setEditable(True)
        self.annotation.setInsertPolicy(QComboBox.NoInsert)
        self.annotation.completer().setFilterMode(Qt.MatchContains)
        self.annotation.completer().setCompletionMode(
            QCompleter.PopupCompletion
        )
        self.annotation.setPlaceholderText("Choose from list or enter new text")
        if self.annotation.lineEdit() is not None:
            self.annotation.lineEdit().setPlaceholderText(
                "Choose from list or enter new text"
            )
        self._refresh_annotation_list()
        self.annotation_button = QPushButton("Annotate")
        self.annotation_button.clicked.connect(self.emit_annotation)
        self._apply_freeze_button_states()

        # Settings button
        self._settings_button = QPushButton("\u2699")
        self._settings_button.setToolTip(
            "Settings (sampling, thresholds, display, annotations) [Ctrl+,]"
        )
        self._settings_button.setFixedWidth(28)
        self._settings_button.setStyleSheet("font-size: 14px; padding: 2px;")
        self._settings_button.clicked.connect(self._open_settings)
        self._settings_shortcut = QShortcut(QKeySequence("Ctrl+,"), self)
        self._settings_shortcut.activated.connect(self._open_settings)

        # Tooltips for buttons and key data fields.
        self.scan_button.setToolTip("Scan for nearby Bluetooth heart sensors.")
        self.address_menu.setToolTip("Select the sensor to connect.")
        self.connect_button.setToolTip("Connect to the selected sensor.")
        self.disconnect_button.setToolTip("Disconnect from the current sensor.")
        self.reset_button.setToolTip("Reset baseline detection and clear trend buffers.")
        self.reset_axes_button.setToolTip("Restore both chart Y-axes to sensible baseline-centered ranges.")
        self.freeze_two_main_plots_button.setToolTip("Freeze/resume only the two main trend plots.")
        self.freeze_all_button.setToolTip("Freeze/resume the main, ECG, and QTc plots.")
        self.ecg_button.setToolTip("Open/close the live ECG monitor window.")
        self.qtc_button.setToolTip("Open/close the live QTc trend monitor window.")
        self.poincare_button.setToolTip("Open the live Poincare RR scatter window.")
        self.start_recording_button.setToolTip("Start a new session and begin recording.")
        self.save_recording_button.setToolTip("Finalize the active session and save artifacts.")
        self.export_report_button.setToolTip("Export a draft/final DOCX report for this session.")
        self.history_button.setToolTip("Show recent session history for the active user profile.")
        self.profile_manager_button.setToolTip("Manage user profiles (create, rename, archive, delete).")
        self.annotation.setToolTip("Choose or type a session annotation.")
        self.annotation_button.setToolTip("Add the current annotation to the session log.")
        self.pacer_rate.setToolTip("Breathing pacer rate in breaths per minute.")
        self.pacer_toggle.setToolTip("Show or hide the breathing pacer animation.")
        self.current_hr_label.setToolTip("Current averaged heart rate in beats per minute.")
        self.rmssd_label.setToolTip("Current RMSSD heart rate variability metric.")
        self.sdnn_label.setToolTip("Current SDNN heart rate variability metric.")
        self.stress_ratio_label.setToolTip("Current LF/HF ratio estimate.")
        self.health_label.setToolTip("Current signal quality status.")
        self.recording_statusbar.setToolTip("Session progress and recording state.")

        # 5. LAYOUT ASSEMBLY — monitoring dashboard
        central = QWidget()
        self.vlayout0 = QVBoxLayout(central)
        self.vlayout0.setSpacing(4)

        # Header row: centered active profile with settings control at top-right.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        self._header_left_spacer = QWidget()
        # Balance the right-side header controls so the center label stays visually centered.
        self._header_left_spacer.setFixedWidth(116)
        self.profile_header_label = QLabel(f"User: {self._session_profile_id}")
        self.profile_header_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #2c3e50;"
        )
        self.profile_header_label.setAlignment(Qt.AlignCenter)
        self._debug_mode_badge = QLabel("DEBUG ON")
        self._debug_mode_badge.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #7e0000; "
            "background: #ffe5e5; border: 1px solid #ffb3b3; "
            "border-radius: 3px; padding: 1px 6px;"
        )
        self._debug_mode_badge.setVisible(False)
        header_row.addWidget(self._header_left_spacer)
        header_row.addStretch()
        header_row.addWidget(self.profile_header_label, alignment=Qt.AlignCenter)
        header_row.addSpacing(8)
        header_row.addWidget(self._debug_mode_badge, alignment=Qt.AlignVCenter)
        header_row.addStretch()
        header_row.addWidget(self.profile_manager_button)
        header_row.addWidget(self._settings_button)
        self._top_bar = QWidget()
        self._top_bar.setLayout(header_row)
        self.vlayout0.addWidget(self._top_bar)
        for _w in (
            self._top_bar,
            self._header_left_spacer,
            self.profile_header_label,
            self._debug_mode_badge,
            self.profile_manager_button,
            self._settings_button,
        ):
            _w.installEventFilter(self)
        self._refresh_debug_mode_ui()

        # Main content row: equal-height plots on left, pacer stack on right.
        self.content_row = QHBoxLayout()
        self.content_row.setContentsMargins(0, 0, 0, 0)
        self.content_row.setSpacing(2)

        plots_column = QVBoxLayout()
        plots_column.setContentsMargins(0, 0, 0, 0)
        plots_column.setSpacing(2)
        plots_column.addWidget(self.ibis_widget, stretch=1)
        freeze_row = QHBoxLayout()
        freeze_row.addStretch()
        self.freeze_two_main_plots_button.setFixedWidth(160)
        freeze_row.addWidget(self.freeze_two_main_plots_button)
        self.freeze_all_button.setFixedWidth(92)
        freeze_row.addSpacing(8)
        freeze_row.addWidget(self.freeze_all_button)
        self.reset_axes_button.setFixedWidth(100)
        freeze_row.addSpacing(8)
        freeze_row.addWidget(self.reset_axes_button)
        freeze_row.addStretch()
        plots_column.addLayout(freeze_row)
        plots_column.addWidget(self.hrv_widget, stretch=1)
        self.content_row.addLayout(plots_column, stretch=1)

        pacer_column = QVBoxLayout()
        pacer_column.setContentsMargins(0, 0, 0, 0)
        pacer_column.setSpacing(2)
        pacer_column.addWidget(self.pacer_widget, alignment=Qt.AlignHCenter)
        pacer_column.addWidget(self.pacer_group, alignment=Qt.AlignTop)
        pacer_column.addStretch()

        pacer_container = QWidget()
        pacer_container.setFixedWidth(200)
        pacer_container.setLayout(pacer_column)
        self.content_row.addWidget(pacer_container, stretch=0, alignment=Qt.AlignTop)
        self.vlayout0.addLayout(self.content_row, stretch=90)

        # BOTTOM ROW 1: Full-width status banner + reset
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        progress_row.addWidget(self.recording_statusbar, stretch=1)
        self.reset_button.setFixedWidth(90)
        progress_row.addWidget(self.reset_button)
        self.vlayout0.addLayout(progress_row)

        # BOTTOM ROW 2: Compact toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        toolbar.setContentsMargins(0, 0, 0, 0)

        for btn in (self.scan_button, self.connect_button,
                    self.disconnect_button):
            btn.setMaximumWidth(80)
            btn.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.ecg_button.setMaximumWidth(170)
        self.ecg_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.qtc_button.setMaximumWidth(170)
        self.qtc_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.poincare_button.setMaximumWidth(130)
        self.poincare_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.start_recording_button.setMaximumWidth(70)
        self.start_recording_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.save_recording_button.setMaximumWidth(70)
        self.save_recording_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.export_report_button.setMaximumWidth(116)
        self.export_report_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.history_button.setMaximumWidth(80)
        self.history_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.profile_manager_button.setMaximumWidth(80)
        self.profile_manager_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.address_menu.setMaximumWidth(320)
        self.address_menu.setStyleSheet("font-size: 11px;")

        toolbar.addWidget(self.scan_button)
        toolbar.addWidget(self.address_menu)
        toolbar.addWidget(self.connect_button)
        toolbar.addWidget(self.disconnect_button)

        _sep1 = QFrame()
        _sep1.setFixedSize(1, 18)
        _sep1.setStyleSheet("background: #bdc3c7;")
        toolbar.addWidget(_sep1)

        toolbar.addStretch()
        toolbar.addWidget(self.ecg_button)
        toolbar.addWidget(self.qtc_button)
        toolbar.addWidget(self.poincare_button)
        toolbar.addStretch()

        _stat_style = (
            "font-size: 11px; color: #2c3e50; "
            "border: 1px solid #bdc3c7; border-radius: 3px; "
            "padding: 1px 4px 1px 18px; background: #f8f9fa;"
        )
        stat_labels = [
            self.current_hr_label,
            self.rmssd_label,
            self.sdnn_label,
            self.stress_ratio_label,
        ]
        stat_width = 120
        spacer = QWidget()
        spacer.setFixedHeight(88)
        self.pacer_config.addRow(spacer)
        for lbl in stat_labels:
            lbl.setFixedWidth(stat_width)
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            lbl.setStyleSheet(_stat_style)
            self.pacer_config.addRow(lbl)

        toolbar.addSpacing(12)

        _sep2 = QFrame()
        _sep2.setFixedSize(1, 18)
        _sep2.setStyleSheet("background: #bdc3c7;")
        toolbar.addWidget(_sep2)

        self.annotation.setMaximumWidth(200)
        self.annotation.setStyleSheet("font-size: 11px;")
        self.annotation.setPlaceholderText("Choose from list or enter new text")
        self.annotation_button.setMaximumWidth(64)
        self.annotation_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        toolbar.addWidget(self.start_recording_button)
        toolbar.addWidget(self.save_recording_button)
        toolbar.addWidget(self.export_report_button)
        toolbar.addWidget(self.history_button)
        toolbar.addWidget(self.annotation)
        toolbar.addWidget(self.annotation_button)

        self.vlayout0.addLayout(toolbar)

        # Set the monitoring dashboard as the central widget directly
        self.setCentralWidget(central)

        # Initialize
        self.statusbar = self.statusBar()
        self.health_label.setStyleSheet("font-size: 11px;")
        self.statusbar.addPermanentWidget(self.health_indicator)
        self.statusbar.addPermanentWidget(self.health_label)
        self.logger_thread.start()
        self.pacer_timer.start()
        self._apply_connect_ready_state()
        self._start_connect_hints()
        self._update_session_actions()
        self._focus_connect_if_ready()
        QTimer.singleShot(0, self._run_startup_flow)

        # Set Axis Labels
        self.ibis_widget.x_axis.setTitleText("Seconds")
        self.ibis_widget.y_axis.setTitleText("Heart Rate (bpm)")
        self.hrv_widget.x_axis.setTitleText("Seconds")
        self.hrv_widget.y_axis.setTitleText("RMSSD (ms)")

    def _prompt_for_session_profile(self) -> str | None:
        profiles = self._profile_store.list_profiles()
        last_profile = self._profile_store.get_last_active_profile()
        dlg = ProfileSelectionDialog(profiles=profiles, last_profile=last_profile, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return None
        if dlg.selected_profile is None:
            return None
        return self._profile_store.ensure_profile(dlg.selected_profile)

    def _set_active_profile(self, profile_id: str, announce: bool = False):
        self._session_profile_id = self._profile_store.set_last_active_profile(profile_id)
        self.profile_header_label.setText(f"User: {self._session_profile_id}")
        debug_pref = self._profile_store.get_profile_pref(
            self._session_profile_id,
            "debug_mode",
            default=("1" if self.settings.DEBUG else "0"),
        )
        self._set_debug_mode(debug_pref == "1", announce=False)
        if announce:
            self.show_status(f"Active user: {self._session_profile_id}")

    def _should_show_disclaimer_for_profile(self, profile_id: str) -> bool:
        hide_value = self._profile_store.get_profile_pref(
            profile_id, "hide_disclaimer", default="0"
        )
        return hide_value != "1"

    def _show_card0_dialog(self, profile_id: str) -> bool:
        dlg = Card0Dialog(self, allow_skip_for_profile=True)
        dlg.showMaximized()
        if dlg.exec() != QDialog.Accepted:
            return False
        # Persist only the opt-out signal here.
        # Reset to showing the disclaimer is handled explicitly in Settings.
        if dlg.dont_show_again_for_profile:
            self._profile_store.set_profile_pref(
                profile_id,
                "hide_disclaimer",
                "1",
            )
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Preference Saved")
            msg.setText(
                "This disclaimer will be skipped on next launch for this user.\n"
                "You can re-enable it at any time in Settings."
            )
            msg.setStandardButtons(QMessageBox.Ok)
            flags = msg.windowFlags()
            flags &= ~Qt.WindowMinimizeButtonHint
            flags &= ~Qt.WindowCloseButtonHint
            flags |= Qt.CustomizeWindowHint | Qt.WindowTitleHint
            msg.setWindowFlags(flags)
            msg.exec()
        return True

    def _run_startup_flow(self):
        selected_profile = self._prompt_for_session_profile()
        if selected_profile is None:
            self.close()
            return
        self._set_active_profile(selected_profile, announce=True)
        if self._should_show_disclaimer_for_profile(selected_profile):
            if not self._show_card0_dialog(selected_profile):
                self.close()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._maximized_once:
            self._maximized_once = True
            QTimer.singleShot(0, self.showMaximized)

    def closeEvent(self, event):
        if self._session_state == "recording":
            reply = QMessageBox.question(
                self,
                "Finalize Session",
                "You have an active session. Finalize and save artifacts before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Yes:
                self.finalize_session(show_message=False)
            else:
                self._abandon_active_session()
        # Ensure BLE resources are released on app exit to reduce reconnect issues
        # on next launch (especially on Windows stacks that linger briefly).
        if self.sensor.client is not None:
            self.sensor.disconnect_client()
            # Give Qt's BLE stack a brief chance to process disconnect cleanup
            # before the process exits.
            shutdown_wait = QEventLoop(self)
            QTimer.singleShot(350, shutdown_wait.quit)
            shutdown_wait.exec()
        if self.logger_thread.isRunning():
            # Flush any open recording before terminating the logger event loop.
            self.signals.save_recording.emit()
            self.logger_thread.quit()
            self.logger_thread.wait(2000)
        super().closeEvent(event)

    def _is_sensor_connected(self) -> bool:
        return self.sensor.client is not None

    def _set_session_state(self, state: str):
        self._session_state = state
        self._update_session_actions()

    def _update_session_actions(self):
        connected = self._is_sensor_connected()
        is_recording = self._session_state == "recording"
        self.start_recording_button.setEnabled(connected and not is_recording)
        self.save_recording_button.setEnabled(is_recording)
        self.export_report_button.setEnabled(self._session_bundle is not None)
        self.export_report_button.setText("Report (Draft)" if is_recording else "Report")
        self.poincare_button.setEnabled(connected)
        if not connected:
            self.qtc_button.setEnabled(False)
            self.qtc_button.setText("QTc (no sensor)")
        elif self.ecg_button.isEnabled() and not self.qtc_window.isVisible():
            self.qtc_button.setEnabled(True)
            self.qtc_button.setText("QTc Monitor")
        if not connected:
            self.poincare_button.setText("Poincare (no sensor)")
        elif not self.poincare_window.isVisible():
            self.poincare_button.setText("Poincare")

    def _current_sensor_label(self) -> str:
        text = self.address_menu.currentText().strip()
        if not text:
            return "--"
        return text

    def _build_report_data(self, report_stage: str) -> dict:
        session_start = (
            datetime.fromtimestamp(self.start_time)
            if self.start_time is not None
            else (self._session_bundle.started_at if self._session_bundle else datetime.now())
        )
        session_end = datetime.now()
        last_rmssd = self._session_rmssd_values[-1] if self._session_rmssd_values else None
        last_hr = self._session_hr_values[-1] if self._session_hr_values else None
        qtc_payload = self._session_qtc_payload or self.model.latest_qtc_payload or default_qtc_payload()
        csv_path = str(self._session_bundle.csv_path) if self._session_bundle else ""
        return {
            "session_id": self._session_bundle.session_id if self._session_bundle else "--",
            "profile_id": self._session_profile_id,
            "session_type": "General Monitoring",
            "session_start": session_start,
            "session_end": session_end,
            "baseline_hr": self.baseline_hr,
            "baseline_rmssd": self.baseline_rmssd,
            "last_hr": last_hr,
            "last_rmssd": last_rmssd,
            "annotations": list(self._session_annotations),
            "hr_values": list(self._session_hr_values),
            "rmssd_values": list(self._session_rmssd_values),
            "notes": "",
            "csv_path": csv_path,
            "report_stage": report_stage,
            "qtc": qtc_payload,
        }

    def _manifest_payload(self, state: str, report_stage: str | None = None) -> dict:
        now = datetime.now().isoformat()
        last_rmssd = self._session_rmssd_values[-1] if self._session_rmssd_values else None
        last_hr = self._session_hr_values[-1] if self._session_hr_values else None
        qtc_payload = self._session_qtc_payload or self.model.latest_qtc_payload or default_qtc_payload()
        settings_snapshot = {key: getattr(self.settings, key) for key in REGISTRY}
        bundle = self._session_bundle
        if bundle is None:
            return {"updated_at": now, "state": state}
        return {
            "schema_version": 1,
            "updated_at": now,
            "session_id": bundle.session_id,
            "profile_id": bundle.profile_id,
            "state": state,
            "report_stage": report_stage or ("draft" if state == "recording" else "final"),
            "sensor": {"selected_device": self._current_sensor_label()},
            "timing": {
                "started_at": bundle.started_at.isoformat(),
                "first_data_at": (
                    datetime.fromtimestamp(self.start_time).isoformat()
                    if self.start_time is not None
                    else None
                ),
                "ended_at": now if state != "recording" else None,
            },
            "metrics": {
                "baseline_hr": self.baseline_hr,
                "baseline_rmssd": self.baseline_rmssd,
                "last_hr": last_hr,
                "last_rmssd": last_rmssd,
                "qtc": qtc_payload,
                "annotation_count": len(self._session_annotations),
            },
            "artifacts": {
                "csv": {"path": str(bundle.csv_path), "exists": bundle.csv_path.exists()},
                "docx_final": {
                    "path": str(bundle.report_final_path),
                    "exists": bundle.report_final_path.exists(),
                },
                "docx_draft": {
                    "path": str(bundle.report_draft_path),
                    "exists": bundle.report_draft_path.exists(),
                },
                "edf": {"path": str(bundle.edf_path), "status": "planned"},
            },
            "settings_snapshot": settings_snapshot,
        }

    def _persist_manifest(self, state: str, report_stage: str | None = None):
        if self._session_bundle is None:
            return
        payload = self._manifest_payload(state=state, report_stage=report_stage)
        try:
            write_manifest(self._session_bundle.manifest_path, payload)
        except OSError as exc:
            self.show_status(f"Manifest write failed: {exc}")

    def start_session(self, auto: bool = False):
        if self._session_state == "recording":
            return
        if not self._session_profile_id:
            self.show_status("Select a user profile before starting a session.")
            return
        if not self._is_sensor_connected():
            self.show_status("Connect a sensor before starting a session.")
            return
        try:
            self._session_bundle = create_session_bundle(
                root=self._session_root,
                profile_id=self._session_profile_id,
            )
        except Exception as exc:
            self.show_status(f"Unable to create session folder: {exc}")
            return
        self._session_annotations = []
        self._session_hr_values = []
        self._session_rmssd_values = []
        self._session_qtc_payload = default_qtc_payload()
        self._profile_store.record_session_started(
            profile_name=self._session_profile_id,
            bundle=self._session_bundle,
        )
        self.signals.start_recording.emit(str(self._session_bundle.csv_path))
        self._set_session_state("recording")
        self._persist_manifest(state="recording", report_stage="draft")
        if auto:
            self.show_status(f"Session auto-started: {self._session_bundle.session_dir}")
        else:
            self.show_status(f"Session started: {self._session_bundle.session_dir}")

    def _abandon_active_session(self):
        if self._session_state != "recording":
            return
        self.signals.save_recording.emit()
        if self._session_bundle is not None:
            self._profile_store.record_session_finished(
                session_id=self._session_bundle.session_id,
                state="abandoned",
            )
        self._persist_manifest(state="abandoned", report_stage="draft")
        self._set_session_state("finalized")

    def finalize_session(self, show_message: bool = True, build_final_report: bool = True):
        if self._session_state != "recording":
            if show_message:
                self.show_status("No active session to save.")
            return
        self.signals.save_recording.emit()
        if build_final_report and self._session_bundle is not None:
            try:
                final_data = self._build_report_data(report_stage="final")
                generate_session_report(str(self._session_bundle.report_final_path), final_data)
            except Exception as exc:
                if show_message:
                    self.show_status(f"Final report generation failed: {exc}")
        if self._session_bundle is not None:
            self._profile_store.record_session_finished(
                session_id=self._session_bundle.session_id,
                state="finalized",
            )
        self._set_session_state("finalized")
        self._persist_manifest(state="finalized", report_stage="final")
        if show_message and self._session_bundle is not None:
            self.show_status(f"Session finalized: {self._session_bundle.session_dir}")

    def connect_sensor(self):
        if not self.address_menu.currentText():
            return
        parts = self.address_menu.currentText().split(",")
        self._do_connect(parts[0].strip(), parts[1].strip())

    def _do_connect(self, name: str, address: str):
        sensor = [s for s in self.model.sensors if get_sensor_address(s) == address]

        if not sensor:
            bt_addr = QBluetoothAddress(address)
            device = QBluetoothDeviceInfo(bt_addr, name, 0)
            device.setCoreConfigurations(QBluetoothDeviceInfo.LowEnergyCoreConfiguration)
            sensor = [device]

        self.start_time = None
        self.baseline_values = []
        self.baseline_rmssd = None
        self.baseline_hr_values = []
        self.baseline_hr = None
        self.is_phase_active = False
        self._fault_active = False
        self._consecutive_good = 0
        self._hr_ewma = None
        self._reset_signal_popup()
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_ceiling = None
        self._main_plots_frozen = False
        self._all_plots_frozen = False
        self.ecg_window.set_stream_frozen(False)
        self.qtc_window.set_stream_frozen(False)
        self._apply_freeze_button_states()
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._session_annotations = []
        self._session_hr_values = []
        self._session_rmssd_values = []
        self._session_qtc_payload = default_qtc_payload()
        self._session_bundle = None
        self.ecg_window.clear()
        self.qtc_window.clear()
        self._set_session_state("idle")
        self.hr_trend_series.clear()
        self.sdnn_series.clear()

        if hasattr(self, 'baseline_series'):
            self.hrv_widget.chart().removeSeries(self.baseline_series)
            del self.baseline_series
        if hasattr(self, 'hr_baseline_series'):
            self.ibis_widget.plot.removeSeries(self.hr_baseline_series)
            del self.hr_baseline_series

        self._stop_connect_hints()
        self.connect_button.setEnabled(False)
        self.connect_button.setStyleSheet(self._CONNECT_DISABLED_CSS)
        self.disconnect_button.setEnabled(False)
        self.ecg_button.setEnabled(False)
        self.ecg_button.setText("ECG (starting...)")
        self.qtc_button.setEnabled(False)
        self.qtc_button.setText("QTc (starting...)")
        self.poincare_button.setEnabled(False)
        self.poincare_button.setText("Poincare (starting...)")
        self.sensor.connect_client(*sensor)
        self._connect_attempt_timer.start()
        self._last_data_time = None
        self._data_watchdog.stop()
        self.show_status("Connecting to Sensor... Please wait.")

    def disconnect_sensor(self):
        if self._session_state == "recording":
            reply = QMessageBox.question(
                self,
                "Finalize Session",
                "Finalize and save the current session before disconnecting?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Yes:
                self.finalize_session(show_message=False)
            else:
                self._abandon_active_session()
        self._data_watchdog.stop()
        self._connect_attempt_timer.stop()
        if self.ecg_window.isVisible():
            self.ecg_window.stop()
        if self.qtc_window.isVisible():
            self.qtc_window.stop()
            self.qtc_window.hide()
        self.ecg_window.clear()
        self.qtc_window.clear()
        if self.poincare_window.isVisible():
            self.poincare_window.hide()
        self.poincare_window.clear()
        self.sensor.disconnect_client()
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.scan_button.setEnabled(True)
        self.ecg_button.setEnabled(False)
        self.ecg_button.setText("ECG (no sensor)")
        self.qtc_button.setEnabled(False)
        self.qtc_button.setText("QTc (no sensor)")
        self.poincare_button.setEnabled(False)
        self.poincare_button.setText("Poincare (no sensor)")
        self._main_plots_frozen = False
        self._all_plots_frozen = False
        self.ecg_window.set_stream_frozen(False)
        self.qtc_window.set_stream_frozen(False)
        self._apply_freeze_button_states()
        self.is_phase_active = False
        self._reset_signal_popup()
        self.recording_statusbar.set_disconnected()
        self._start_connect_hints()
        self._update_session_actions()

    def toggle_ecg_window(self):
        if self.ecg_window.isVisible():
            self.ecg_window.stop()
            self.ecg_window.hide()
            self.ecg_button.setText("ECG Monitor")
        else:
            self.ecg_window.show()
            self.ecg_window.start()
            self.ecg_window.set_stream_frozen(self._all_plots_frozen)
            self.ecg_button.setText("Close ECG")

    def _on_ecg_ready(self):
        self.ecg_button.setEnabled(True)
        self.ecg_button.setText("ECG Monitor")
        self.qtc_button.setEnabled(True)
        self.qtc_button.setText("QTc Monitor")

    def _on_ecg_window_closed(self):
        self.ecg_button.setText("ECG Monitor")

    def toggle_qtc_window(self):
        if self.qtc_window.isVisible():
            self.qtc_window.stop()
            self.qtc_window.hide()
            self.qtc_button.setText("QTc Monitor")
        else:
            self.qtc_window.show()
            self.qtc_window.start()
            self.qtc_window.set_stream_frozen(self._all_plots_frozen)
            self.qtc_button.setText("Close QTc")

    def _on_qtc_window_closed(self):
        if self._is_sensor_connected():
            self.qtc_button.setText("QTc Monitor")
        else:
            self.qtc_button.setText("QTc (no sensor)")

    def toggle_poincare_window(self):
        if self.poincare_window.isVisible():
            self.poincare_window.hide()
            self.poincare_button.setText("Poincare")
        else:
            self.poincare_window.show()
            self.poincare_button.setText("Close Poincare")

    def _on_poincare_window_closed(self):
        if self._is_sensor_connected():
            self.poincare_button.setText("Poincare")
        else:
            self.poincare_button.setText("Poincare (no sensor)")

    def show_poincare_info(self):
        parent = self.poincare_window if self.poincare_window.isVisible() else self
        msg = QMessageBox(parent)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Poincare Plot Help")
        msg.setWindowModality(Qt.WindowModal)
        msg.setText(
            "<b>What this shows</b><br>"
            "Each dot is one heartbeat interval compared with the next:<br>"
            "RR(n) on x-axis and RR(n+1) on y-axis.<br><br>"
            "<b>How to read it quickly</b><br>"
            "- Tight cluster: usually steadier rhythm and cleaner signal (often good).<br>"
            "- Wider cloud: more variability; can be physiologic, but can also reflect noise/artifact.<br><br>"
            "<b>Metrics</b><br>"
            "- SD1: short-term variability.<br>"
            "- SD2: longer-term variability.<br>"
            "- SD1/SD2: balance of short vs longer-term variability.<br><br>"
            "SD = standard deviation.<br><br>"
            "<b>Important</b><br>"
            "Motion artifact, poor strap contact, or dropouts can distort the plot."
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    def _update_poincare(self, data: NamedSignal):
        if data.name != "ibis":
            return
        if not isinstance(data.value, (list, tuple)) or len(data.value) < 2:
            return
        rr = list(data.value[1])
        if not rr:
            return
        self.poincare_window.update_from_ibis(rr)

    # -- Connect-CTA helpers -------------------------------------------------

    @staticmethod
    def _make_chart_overlay(parent):
        lbl = QLabel(
            "No sensor connected\nPress Connect to begin",
            parent,
        )
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "background: rgba(255, 255, 255, 180); "
            "color: #636e72; font-size: 16px; font-weight: bold; "
            "border-radius: 8px; padding: 20px;"
        )
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        return lbl

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            overlay = None
            if obj is self.ibis_widget:
                overlay = self._hr_overlay
            elif obj is self.hrv_widget:
                overlay = self._hrv_overlay
            if overlay is not None:
                overlay.resize(obj.size())
        if (
            obj in {
                getattr(self, "_top_bar", None),
                getattr(self, "_header_left_spacer", None),
                getattr(self, "profile_header_label", None),
                getattr(self, "_debug_mode_badge", None),
                getattr(self, "profile_manager_button", None),
                getattr(self, "_settings_button", None),
            }
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            mods = event.modifiers()
            if (mods & Qt.ControlModifier) and (mods & Qt.AltModifier):
                click_pos = None
                if isinstance(obj, QWidget) and hasattr(event, "position"):
                    click_pos = obj.mapTo(self, event.position().toPoint())
                self._toggle_debug_mode_hotkey(click_pos)
                return True
        return super().eventFilter(obj, event)

    def _start_connect_hints(self):
        self._hr_overlay.show()
        self._hrv_overlay.show()
        has_sensors = self._has_sensor_choices()
        self._connect_pulse_active = has_sensors
        self._scan_pulse_active = not has_sensors
        self._apply_connect_ready_state()
        if self._scan_pulse_active:
            self.scan_button.setStyleSheet(self._SCAN_NORMAL_CSS)
            self.connect_button.setStyleSheet(self._CONNECT_DISABLED_CSS)
        else:
            self.scan_button.setStyleSheet(self._SCAN_NORMAL_CSS)
            self.connect_button.setStyleSheet(self._CONNECT_NORMAL_CSS)
        if not self._connect_pulse_timer.isActive():
            self._connect_pulse_on = False
            self._connect_pulse_timer.start()

    def _stop_connect_hints(self):
        self._hr_overlay.hide()
        self._hrv_overlay.hide()
        self._connect_pulse_timer.stop()
        self._connect_pulse_on = False
        self._connect_pulse_active = False
        self._scan_pulse_active = False
        self.scan_button.setStyleSheet(self._SCAN_NORMAL_CSS)
        self._apply_connect_ready_state()

    _CONNECT_GLOW_CSS = (
        "QPushButton { "
        "font-size: 11px; padding: 2px 6px; "
        "background: #d4edda; border: 2px solid #28a745; border-radius: 3px; "
        "}"
    )
    _CONNECT_NORMAL_CSS = (
        "QPushButton { "
        "font-size: 11px; padding: 2px 6px; "
        "background: transparent; border: 2px solid transparent; border-radius: 3px; "
        "}"
    )
    _CONNECT_DISABLED_CSS = (
        "QPushButton { "
        "font-size: 11px; padding: 2px 6px; "
        "background: #ecf0f1; color: #7f8c8d; border: 2px solid #bdc3c7; border-radius: 3px; "
        "}"
    )
    _SCAN_GLOW_CSS = (
        "QPushButton { "
        "font-size: 11px; padding: 2px 6px; "
        "background: #d4edda; border: 2px solid #28a745; border-radius: 3px; "
        "}"
    )
    _SCAN_NORMAL_CSS = (
        "QPushButton { "
        "font-size: 11px; padding: 2px 6px; "
        "background: transparent; border: 2px solid transparent; border-radius: 3px; "
        "}"
    )

    def _has_sensor_choices(self) -> bool:
        return self.address_menu.count() > 0 and bool(self.address_menu.currentText().strip())

    def _apply_connect_ready_state(self):
        if self.sensor.client is not None:
            self.connect_button.setToolTip("Already connected to a sensor.")
            self.connect_button.setDefault(False)
            return
        if self._connect_attempt_timer.isActive():
            self.connect_button.setEnabled(False)
            self.connect_button.setStyleSheet(self._CONNECT_DISABLED_CSS)
            self.connect_button.setToolTip("Connecting... please wait for timeout or success.")
            self.connect_button.setDefault(False)
            return
        has_sensors = self._has_sensor_choices()
        self.connect_button.setEnabled(has_sensors)
        if has_sensors:
            self.connect_button.setStyleSheet(self._CONNECT_NORMAL_CSS)
            self.connect_button.setToolTip("Connect to the selected sensor.")
            self.connect_button.setDefault(True)
        else:
            self.connect_button.setStyleSheet(self._CONNECT_DISABLED_CSS)
            self.connect_button.setToolTip("No sensor selected yet. Click Scan first.")
            self.connect_button.setDefault(False)

    def _focus_connect_if_ready(self):
        if not self._has_sensor_choices():
            return
        if self.sensor.client is not None or self._connect_attempt_timer.isActive():
            return
        self.connect_button.setFocus(Qt.OtherFocusReason)
        self.connect_button.setDefault(True)

    def _pulse_connect_button(self):
        self._connect_pulse_on = not self._connect_pulse_on
        if self._connect_pulse_active:
            if self._connect_pulse_on:
                self.connect_button.setStyleSheet(self._CONNECT_GLOW_CSS)
            else:
                self.connect_button.setStyleSheet(self._CONNECT_NORMAL_CSS)
        if self._scan_pulse_active:
            if self._connect_pulse_on:
                self.scan_button.setStyleSheet(self._SCAN_GLOW_CSS)
            else:
                self.scan_button.setStyleSheet(self._SCAN_NORMAL_CSS)

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._set_debug_mode(bool(self.settings.DEBUG), announce=False)
            pending_reset = dlg.get_pending_disclaimer_reset()
            if pending_reset in {"active", "all"}:
                self._apply_disclaimer_prompt_reset(pending_reset)
        self._refresh_annotation_list()

    def _open_history(self):
        sessions = self._profile_store.list_sessions(
            profile_name=self._session_profile_id,
            limit=200,
        )
        dlg = SessionHistoryDialog(
            profile_name=self._session_profile_id,
            sessions=sessions,
            parent=self,
        )
        dlg.exec()

    def _open_profile_manager(self):
        if self._session_state == "recording":
            self.show_status("Profile changes are disabled during an active recording.")
            return
        dlg = ProfileManagerDialog(
            store=self._profile_store,
            active_profile=self._session_profile_id,
            parent=self,
        )
        dlg.exec()
        latest_active = self._profile_store.get_last_active_profile()
        if latest_active and latest_active.casefold() != self._session_profile_id.casefold():
            self._set_active_profile(latest_active, announce=True)

    def _apply_disclaimer_prompt_reset(self, scope: str):
        if scope == "all":
            self._profile_store.clear_profile_pref_for_all("hide_disclaimer")
            self.show_status("Disclaimer prompt reset for all users.")
            return
        self._profile_store.clear_profile_pref(self._session_profile_id, "hide_disclaimer")
        self.show_status(f"Disclaimer prompt reset for user: {self._session_profile_id}")

    def _on_connect_timeout(self):
        if self.sensor.client is not None:
            return
        self.sensor.disconnect_client()
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.scan_button.setEnabled(True)
        self._apply_connect_ready_state()
        self._start_connect_hints()
        self.show_status(
            "Connection timed out. Make sure the strap is awake and in range, then try Connect again."
        )

    def _auto_start_recording(self):
        if self._session_state == "recording":
            return
        self.start_session(auto=True)

    def get_filepath(self):
        self.start_session(auto=False)

    def export_report(self):
        """Create a draft/final DOCX report into the current session folder."""
        if self._session_bundle is None:
            self.show_status("No session bundle available for report export.")
            return
        report_stage = "draft" if self._session_state == "recording" else "final"
        report_path = (
            self._session_bundle.report_draft_path
            if report_stage == "draft"
            else self._session_bundle.report_final_path
        )
        report_data = self._build_report_data(report_stage=report_stage)
        try:
            generate_session_report(str(report_path), report_data)
            self._persist_manifest(state=self._session_state, report_stage=report_stage)
            self.show_status(f"Saved {report_stage} report at {report_path}")
        except Exception as e:
            self.show_status(f"Report export failed: {e}")

    def emit_annotation(self):
        text = self.annotation.currentText().strip()
        if not text:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self._session_annotations.append((ts, text))
        self.signals.annotation.emit(NamedSignal("Annotation", text))
        self.settings.add_custom_annotation(text)
        self._refresh_annotation_list()
        self.annotation.setCurrentText("")

    def _refresh_annotation_list(self):
        self.annotation.clear()
        for item in self.settings.get_all_annotations():
            self.annotation.addItem(item)
        self.annotation.setCurrentIndex(-1)
        self.annotation.setCurrentText("")

    def reset_baseline(self):
        was_good = "GOOD" in self.health_label.text()
        self._preserve_good_on_reset = was_good
        self.reset_button.setEnabled(False)
        self.start_time = None
        self.baseline_rmssd = None
        self.baseline_values = []
        self.baseline_hr = None
        self.baseline_hr_values = []
        self.is_phase_active = False
        self._fault_active = False
        self._consecutive_good = 0
        self._hr_ewma = None
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_ceiling = None
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._last_data_time = time.time()
        self._handle_stream_reset()
        self.hr_trend_series.clear()
        self.sdnn_series.clear()
        if was_good:
            self._set_signal_indicator("GOOD", "#00FF00")
        else:
            self._set_signal_indicator("Identifying...", "gray")
        self.show_status("Baseline Reset. Waiting for data...")
        if hasattr(self, 'baseline_series'):
            self.baseline_series.clear()
        if hasattr(self, 'hr_baseline_series'):
            self.hr_baseline_series.clear()

    def reset_y_axes(self):
        # Heart-rate plot: center around baseline/last value with generous +/-50% span.
        hr_ref = self.baseline_hr
        if hr_ref is None and self._session_hr_values:
            hr_ref = self._session_hr_values[-1]
        if hr_ref is None:
            hr_ref = 80.0
        half_span = max(20.0, hr_ref * 0.5)
        hr_lo = max(30.0, hr_ref - half_span)
        hr_hi = min(220.0, hr_ref + half_span)
        if hr_hi - hr_lo < 40.0:
            hr_hi = min(220.0, hr_lo + 40.0)
        self._hr_axis_floor = int(hr_lo)
        self._hr_axis_ceiling = int(hr_hi)
        self.ibis_widget.y_axis.setRange(self._hr_axis_floor, self._hr_axis_ceiling)
        self.hr_y_axis_right.setRange(self._hr_axis_floor, self._hr_axis_ceiling)

        # RMSSD plot: baseline + 50% (or fallback from current values).
        rmssd_ref = self.baseline_rmssd
        if rmssd_ref is None and self._session_rmssd_values:
            rmssd_ref = self._session_rmssd_values[-1]
        if rmssd_ref is None:
            rmssd_ref = 20.0
        hrv_ceil = max(20.0, rmssd_ref * 1.5)
        self._hrv_axis_ceiling = int(-(-hrv_ceil // 5)) * 5
        self.hrv_widget.y_axis.setRange(0, self._hrv_axis_ceiling)

        sdnn_ref = self._sdnn_smooth_buf[-1] if self._sdnn_smooth_buf else (rmssd_ref * 0.75)
        sdnn_ceil = max(30.0, sdnn_ref * 1.5)
        self._sdnn_axis_ceiling = int(-(-sdnn_ceil // 5)) * 5
        self.hrv_y_axis_right.setRange(0, self._sdnn_axis_ceiling)
        self.show_status("Y-axes reset to baseline-centered ranges.")

    def _update_phase_progress_banner(self, elapsed: float, source: str = "unknown"):
        settling_duration = float(self.settings.SETTLING_DURATION)
        baseline_duration = float(self.settings.BASELINE_DURATION)
        total_calibration_time = settling_duration + baseline_duration
        phase_name = "idle"
        if elapsed < settling_duration:
            phase_name = "settling"
            self.is_phase_active = True
            self.recording_statusbar.set_settling(
                int(max(0.0, elapsed)),
                max(1, int(settling_duration)),
            )
        elif elapsed < total_calibration_time:
            phase_name = "baseline"
            self.is_phase_active = True
            baseline_elapsed = elapsed - settling_duration
            self.recording_statusbar.set_baseline(
                int(max(0.0, baseline_elapsed)),
                max(1, int(baseline_duration)),
            )
        self._emit_phase_debug(elapsed=elapsed, phase=phase_name, source=source)

    def _emit_phase_debug(self, elapsed: float, phase: str, source: str):
        if not self.settings.DEBUG:
            return
        now_sec = int(elapsed)
        if (
            phase == self._phase_debug_last_name
            and now_sec == self._phase_debug_last_second
        ):
            return
        self._phase_debug_last_name = phase
        self._phase_debug_last_second = now_sec
        print(
            "[PHASE] "
            f"source={source} "
            f"phase={phase} "
            f"elapsed={elapsed:.1f}s "
            f"settle={self.settings.SETTLING_DURATION}s "
            f"baseline={self.settings.BASELINE_DURATION}s"
        )

    def _set_debug_mode(self, enabled: bool, *, announce: bool = False):
        self.settings.DEBUG = bool(enabled)
        self.settings.save()
        self._profile_store.set_profile_pref(
            self._session_profile_id,
            "debug_mode",
            "1" if self.settings.DEBUG else "0",
        )
        self._refresh_debug_mode_ui()
        if announce:
            state = "ON" if self.settings.DEBUG else "OFF"
            self.show_status(
                f"Debug Mode {state} (Ctrl+Alt+click top bar).",
                print_to_terminal=False,
            )

    def _refresh_debug_mode_ui(self):
        self._debug_mode_badge.setVisible(bool(self.settings.DEBUG))

    def _toggle_debug_mode_hotkey(self, click_pos: QPoint | None = None):
        self._set_debug_mode(not bool(self.settings.DEBUG), announce=True)
        if click_pos is not None:
            self._launch_debug_heart_burst(click_pos, self.settings.DEBUG)

    def _launch_debug_heart_burst(self, center: QPoint, enabled: bool):
        if enabled:
            # Debug ON: energetic green/mint burst.
            palette = ["#00c853", "#00e676", "#69f0ae", "#00b894", "#55efc4"]
        else:
            # Debug OFF: warm red/pink burst.
            palette = ["#ff4d6d", "#ff6b6b", "#ff5fa2", "#ff3b30", "#ff8fab"]
        count = 8
        for i in range(count):
            delay_ms = i * 22 + random.randint(0, 26)
            QTimer.singleShot(
                delay_ms,
                lambda c=center, p=palette: self._spawn_debug_heart(c, p),
            )

    def _spawn_debug_heart(self, center: QPoint, palette: list[str]):
        heart = QLabel("❤", self)
        size = random.randint(12, 22)
        heart.setStyleSheet(
            f"color: {random.choice(palette)}; font-size: {size}px; font-weight: 700;"
        )
        heart.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        heart.adjustSize()
        start = QPoint(center.x() - heart.width() // 2, center.y() - heart.height() // 2)
        heart.move(start)
        heart.show()
        heart.raise_()

        angle = random.uniform(0.0, 2.0 * math.pi)
        radius = random.randint(60, 150)
        dx = int(math.cos(angle) * radius)
        dy = int(math.sin(angle) * radius)
        end = QPoint(start.x() + dx, start.y() + dy)
        duration = random.randint(650, 1100)

        pos_anim = QPropertyAnimation(heart, b"pos", self)
        pos_anim.setDuration(duration)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(end)
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity = QGraphicsOpacityEffect(heart)
        heart.setGraphicsEffect(opacity)
        fade_anim = QPropertyAnimation(opacity, b"opacity", self)
        fade_anim.setDuration(duration)
        fade_anim.setStartValue(1.0)
        fade_anim.setEndValue(0.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)

        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)
        group.finished.connect(lambda g=group, h=heart: self._cleanup_debug_heart(g, h))
        self._debug_heart_anim_groups.append(group)
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _cleanup_debug_heart(self, group: QParallelAnimationGroup, heart: QLabel):
        try:
            self._debug_heart_anim_groups.remove(group)
        except ValueError:
            pass
        heart.deleteLater()

    def direct_chart_update(self, hrv_data: NamedSignal):
        try:
            if not hrv_data.value or len(hrv_data.value[1]) == 0:
                return
            
            raw_y = float(hrv_data.value[1][-1])
            y = max(0, min(raw_y, 250)) 

            if self.start_time is None:
                return

            now = time.time()
            elapsed = now - self.start_time
            x = elapsed - self._plot_start_delay_seconds
            plot_gate_open = x >= 0
            total_calibration_time = self.settings.SETTLING_DURATION + self.settings.BASELINE_DURATION

            # Add smoothed RMSSD to Chart
            ibis = list(self.model.ibis_buffer)
            cur_hr = 60000.0 / ibis[-1] if ibis and ibis[-1] > 0 else 70
            smooth_n = max(5, round(cur_hr / 60 * self.settings.SMOOTH_SECONDS))

            self._rmssd_smooth_buf.append(y)
            while len(self._rmssd_smooth_buf) > smooth_n:
                self._rmssd_smooth_buf.pop(0)
            smoothed_rmssd = sum(self._rmssd_smooth_buf) / len(self._rmssd_smooth_buf)

            # Compute and plot SDNN from IBI buffer
            sdnn = None
            if len(ibis) >= 10:
                sdnn = statistics.stdev(ibis[-30:])
                self._sdnn_smooth_buf.append(sdnn)
                while len(self._sdnn_smooth_buf) > smooth_n:
                    self._sdnn_smooth_buf.pop(0)

            if plot_gate_open:
                self._session_rmssd_values.append(smoothed_rmssd)
                if not self._main_plots_frozen:
                    self.hrv_widget.time_series.append(x, smoothed_rmssd)
                if sdnn is not None and len(self._sdnn_smooth_buf) > 0:
                    smoothed_sdnn = sum(self._sdnn_smooth_buf) / len(self._sdnn_smooth_buf)
                    self.sdnn_label.setText(f"SDNN: {sdnn:6.2f} ms")
                    if not self._main_plots_frozen:
                        self.sdnn_series.append(x, smoothed_sdnn)

            # Expand-only Y-axes
            if self._hrv_axis_ceiling is None:
                self._hrv_axis_ceiling = max(10, int(-(-smoothed_rmssd * 1.5 // 5)) * 5)
            rmssd_padded = int(-(-smoothed_rmssd * 1.3 // 5)) * 5
            if rmssd_padded > self._hrv_axis_ceiling:
                self._hrv_axis_ceiling = rmssd_padded
            if not self._main_plots_frozen:
                self.hrv_widget.y_axis.setRange(0, self._hrv_axis_ceiling)

            if self._sdnn_axis_ceiling is None:
                self._sdnn_axis_ceiling = 50
            if len(self._sdnn_smooth_buf) > 0:
                sdnn_padded = int(-(-self._sdnn_smooth_buf[-1] * 1.3 // 5)) * 5
                if sdnn_padded > self._sdnn_axis_ceiling:
                    self._sdnn_axis_ceiling = sdnn_padded
            if not self._main_plots_frozen:
                self.hrv_y_axis_right.setRange(0, self._sdnn_axis_ceiling)

            # --- CONTINUOUS PHASE ENGINE ---
            
            # PHASE 1: BASELINE COLLECTION
            if elapsed < total_calibration_time:
                self.baseline_values.append(y)

            # PHASE 2: CALCULATE AVERAGES
            elif self.baseline_rmssd is None and self.baseline_values:
                self.baseline_rmssd = sum(self.baseline_values) / len(self.baseline_values)
                self.reset_button.setEnabled(True)
                hr_text = f"{self.baseline_hr:.0f}" if self.baseline_hr is not None else "--"
                self.statusbar.showMessage(
                    f"Baselines locked \u2014 RMSSD: {self.baseline_rmssd:.1f} ms, HR: {hr_text} bpm"
                )
                if self.settings.DEBUG:
                    print(f"--- BASELINES LOCKED: RMSSD={self.baseline_rmssd:.2f} ms, HR={hr_text} bpm ---")

            # PHASE 3: LOCKED STATE
            if self.baseline_rmssd is not None:
                self.is_phase_active = True
                hr_val = f"{self.baseline_hr:.0f}" if self.baseline_hr is not None else "--"
                self.recording_statusbar.set_locked(
                    f"{self.baseline_rmssd:.1f}", hr_val
                )

                if not hasattr(self, 'baseline_series'):
                    from PySide6.QtCharts import QLineSeries
                    from PySide6.QtGui import QPen
                    from PySide6.QtCore import Qt
                    
                    self.baseline_series = QLineSeries()
                    self.baseline_series.setName("Baseline RMSSD (ms)")
                    pen = QPen(QColor(80, 80, 80))
                    pen.setStyle(Qt.DotLine)
                    pen.setWidth(2)
                    self.baseline_series.setPen(pen)
                    self.hrv_widget.chart().addSeries(self.baseline_series)
                    self.baseline_series.attachAxis(self.hrv_widget.x_axis)
                    self.baseline_series.attachAxis(self.hrv_widget.y_axis)

                if not self._main_plots_frozen:
                    self.baseline_series.clear()
                    self.baseline_series.append(x - 60, self.baseline_rmssd)
                    self.baseline_series.append(x + 2, self.baseline_rmssd)

            # CHART VIEWPORT
            if plot_gate_open and not self._main_plots_frozen:
                self.hrv_widget.x_axis.setRange(x - 60, x + 2)

        except Exception as e:
            print(f"Direct Chart Error: {e}")

    def list_addresses(self, addresses: NamedSignal):
        self.address_menu.clear()
        self.address_menu.addItems(addresses.value)
        self._apply_connect_ready_state()
        self._focus_connect_if_ready()
        if self.sensor.client is None:
            self._start_connect_hints()

    def plot_pacer_disk(self):
        if not self.pacer_toggle.isChecked():
            return
        coordinates = self.pacer.update(self.model.breathing_rate)
        self.pacer_widget.update_series(*coordinates)

    def update_pacer_label(self, rate: NamedSignal):
        self.pacer_label.setText(f"Rate: {rate.value}")

    def update_hrv_target(self, target: NamedSignal):
        self.hrv_widget.y_axis.setRange(0, target.value)

    def _sync_aux_windows_to_main_xrange(self, x_lo: float, x_hi: float):
        self.ecg_window.set_synced_xrange(x_lo, x_hi)
        self.qtc_window.set_synced_xrange(x_lo, x_hi)

    def _apply_freeze_button_states(self):
        self.freeze_two_main_plots_button.setText(
            "Resume Two Main Plots"
            if self._main_plots_frozen
            else "Freeze Two Main Plots"
        )
        self.freeze_all_button.setText(
            "Resume All" if self._all_plots_frozen else "Freeze All"
        )
        self.freeze_two_main_plots_button.setEnabled(not self._all_plots_frozen)

    def _toggle_two_main_plots_freeze(self):
        if self._all_plots_frozen:
            return
        self._main_plots_frozen = not self._main_plots_frozen
        self._apply_freeze_button_states()

    def _toggle_freeze_all(self):
        self._all_plots_frozen = not self._all_plots_frozen
        if self._all_plots_frozen:
            self._main_plots_frozen = True
            self.ecg_window.set_stream_frozen(True)
            self.qtc_window.set_stream_frozen(True)
        else:
            self._main_plots_frozen = False
            self.ecg_window.set_stream_frozen(False)
            self.qtc_window.set_stream_frozen(False)
        self._apply_freeze_button_states()

    def toggle_pacer(self):
        if self.pacer_toggle.isChecked():
            self.pacer_widget.disk.setColor(BLUE)
            self.pacer_widget.disk.setBorderColor(QColor(0, 0, 0, 0))
        else:
            self.pacer_widget.update_series(self.pacer.lung_x, self.pacer.lung_y)
            self.pacer_widget.disk.setColor(QColor(200, 210, 225))
            self.pacer_widget.disk.setBorderColor(QColor(0, 0, 0, 0))

    def _update_breathing_rate(self, value):
        self.model.breathing_rate = float(value)
        self.pacer_label.setText(f"Rate: {value}")

    def show_recording_status(self, status: int):
        self.recording_statusbar.setRange(0, max(status, 1))

    def show_status(self, status: str, print_to_terminal=True):
        if "Connected" in status and "Disconnecting" not in status:
            self._connect_attempt_timer.stop()
            self._stop_connect_hints()
            self.is_phase_active = False
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.scan_button.setEnabled(False)
            if self.address_menu.currentText():
                parts = self.address_menu.currentText().split(",")
                if len(parts) >= 2:
                    _save_last_sensor(parts[0].strip(), parts[1].strip())
            self._auto_start_recording()
        elif "error" in status.lower() or "Disconnecting" in status:
            self._apply_connect_ready_state()
            self.disconnect_button.setEnabled(False)
            self.scan_button.setEnabled(True)
            if self.sensor.client is None:
                self._start_connect_hints()

        if not self.is_phase_active:
            if "error" in status.lower():
                self.recording_statusbar.set_error(status)
            else:
                self.recording_statusbar.set_idle(status)
        
        self.statusbar.showMessage(status)
        self._update_session_actions()
        
        if print_to_terminal and self.settings.DEBUG:
            print(status)

    def _show_signal_degraded_popup(self, reason: str):
        if self._signal_popup_shown:
            return
        self._signal_popup_shown = True
        self._fire_signal_popup(reason)

    def _fire_signal_popup(self, reason: str):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Polar H10 Signal Degraded")
        msg.setText(
            f"<b>Signal quality issue detected: {reason}</b>"
        )
        msg.setInformativeText(
            "Please sit still and breathe normally.\n\n"
            "If the problem persists, re-wet the Polar H10 electrode "
            "pads with water or electrode gel and ensure the strap is "
            "snug against the skin."
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.open()

    def _on_rmssd_degraded(self):
        self._signal_degrade_count += 1
        if not self._signal_popup_shown and self._signal_degrade_count >= 8:
            self._signal_popup_shown = True
            self._fire_signal_popup("Poor signal \u2014 electrodes may be dry")

    def _reset_signal_popup(self):
        self._signal_popup_shown = False
        self._signal_degrade_count = 0

    def _handle_stream_reset(self):
        self.model.clear_buffers()
        self._session_qtc_payload = default_qtc_payload()
        self.qtc_window.clear()
        if self.qtc_button.isEnabled() and not self.qtc_window.isVisible():
            self.qtc_button.setText("QTc (warming up...)")

    def _check_data_timeout(self):
        if self._last_data_time is None:
            return
        silence = time.time() - self._last_data_time
        if silence >= self.settings.DATA_TIMEOUT_SECONDS and not self._fault_active:
            self._fault_active = True
            self._consecutive_good = 0
            self._set_signal_indicator("LOST (No data)", "red")
            self._show_signal_degraded_popup("No data received")
            self._handle_stream_reset()

    def _in_settling(self):
        return (self.start_time is not None
                and (time.time() - self.start_time) < self.settings.SETTLING_DURATION)

    def _set_signal_indicator(self, text: str, color: str):
        self.health_indicator.setStyleSheet("color: %s; font-size: 18px;" % color)
        self.health_label.setText("Signal: %s" % text)

    def update_ui_labels(self, data: NamedSignal):
        # 1. RAW BEAT DATA (Heart Rate & Instant Faults)
        if data.name == "ibis":
            self._last_data_time = time.time()
            if not self._data_watchdog.isActive():
                self._data_watchdog.start()
            if len(data.value[1]) > 0:
                last_ibi_ms = data.value[1][-1]
                
                hr = 60000.0 / last_ibi_ms
                display_hr = self._hr_ewma if self._hr_ewma is not None else hr
                self.current_hr_label.setText(f"HR: {int(display_hr)} bpm")

                if self._in_settling():
                    if self._preserve_good_on_reset:
                        self._set_signal_indicator("GOOD", "#00FF00")
                        return
                    remaining = int(self.settings.SETTLING_DURATION
                                    - (time.time() - self.start_time)) + 1
                    self._set_signal_indicator(f"Settling ({remaining}s)", "#2196F3")
                    return
                elif self._preserve_good_on_reset:
                    self._preserve_good_on_reset = False

                # LEVEL 1 FAULT: Total Dropout
                if last_ibi_ms > self.settings.DROPOUT_IBI_MS:
                    self._fault_active = True
                    self._consecutive_good = 0
                    self._set_signal_indicator("FAULT: Clearing Buffer...", "red")
                    self._show_signal_degraded_popup("Total signal dropout")
                    self.signals.request_buffer_reset.emit()
                    return

                # LEVEL 2 FAULT: Hard IBI limits
                if last_ibi_ms > self.settings.NOISE_IBI_HIGH_MS or last_ibi_ms < self.settings.NOISE_IBI_LOW_MS:
                    self._fault_active = True
                    self._consecutive_good = 0
                    self._set_signal_indicator("DROP/NOISE", "red")
                    self._show_signal_degraded_popup("Signal dropout or noise")
                    return

                # LEVEL 3 FAULT: Adaptive deviation
                if not self._fault_active:
                    recent_ibis = list(data.value[1])[-self.settings.DEVIATION_WINDOW:]
                    if len(recent_ibis) >= self.settings.DEVIATION_MIN_SAMPLES:
                        avg_ibi = sum(recent_ibis) / len(recent_ibis)
                        deviation = abs(last_ibi_ms - avg_ibi) / avg_ibi
                        if deviation > self.settings.DEVIATION_THRESHOLD:
                            self._fault_active = True
                            self._consecutive_good = 0
                            self._set_signal_indicator("ERRATIC \u2014 irregular beat", "red")
                            self._show_signal_degraded_popup("Erratic heart rate")
                            return

                # Normal beat — count towards recovery
                if self._fault_active:
                    self._consecutive_good += 1
                    if self._consecutive_good >= self.settings.RECOVERY_BEATS:
                        self._fault_active = False
                        self._reset_signal_popup()
                        self._handle_stream_reset()
                        self._set_signal_indicator("GOOD", "#00FF00")
        
        # 2. FREQUENCY DATA (Stress Ratio)
        elif data.name == "stress_ratio":
            self.stress_ratio_label.setText(f"LF/HF: {data.value[0]:.2f}")

        # 2b. QTc payload updates from ECG delineation/calculation pipeline.
        elif data.name == "qtc":
            if isinstance(data.value, dict):
                self._session_qtc_payload = data.value
                if (
                    self._is_sensor_connected()
                    and not self.qtc_window.isVisible()
                    and self.qtc_button.isEnabled()
                ):
                    self.qtc_button.setText("QTc Monitor")

        # 3. AVERAGED DATA (RMSSD & Stability)
        elif data.name == "hrv":
            if len(data.value[1]) == 0:
                return
            raw_rmssd = float(data.value[1][-1])
            rmssd_val = max(0, min(raw_rmssd, 250))
            self.rmssd_label.setText(f"RMSSD: {rmssd_val:.2f} ms")
            
            if self._fault_active or self._in_settling():
                return

            if rmssd_val > 200:
                self._set_signal_indicator("POOR (Dry?)", "red")
                self._on_rmssd_degraded()
            elif rmssd_val > 150:
                self._set_signal_indicator("NOISY", "orange")
                self._on_rmssd_degraded()
            else:
                self._set_signal_indicator("GOOD", "#00FF00")
                self._reset_signal_popup()

    def plot_ibis(self, data: NamedSignal):
        try:
            if not isinstance(data.value, (list, tuple)) or len(data.value) < 2:
                return
            if len(data.value[1]) == 0:
                return

            last_ibi_ms = float(data.value[1][-1])
            if last_ibi_ms <= 0:
                return

            hr = 60000.0 / last_ibi_ms

            if self.start_time is None:
                self.start_time = time.time()
                self.ecg_window.sync_timeline_to_main(self._plot_start_delay_seconds)
                self.qtc_window.sync_timeline_to_main(self._plot_start_delay_seconds)
                self.hr_trend_series.clear()
                self.sdnn_series.clear()
                self.hrv_widget.time_series.clear()
                if self.ecg_button.text() != "ECG (waiting for data...)":
                    self.ecg_button.setText("ECG (waiting for data...)")
                if self.qtc_button.isEnabled() and self.qtc_button.text() != "QTc (warming up...)":
                    self.qtc_button.setText("QTc (warming up...)")
                if self.settings.DEBUG:
                    print("Timer Started")

            now = time.time()
            elapsed = now - self.start_time
            self._update_phase_progress_banner(elapsed, source="ibis")
            plot_elapsed = elapsed - self._plot_start_delay_seconds

            w = self.settings.HR_EWMA_WEIGHT
            if self._hr_ewma is None:
                self._hr_ewma = hr
            else:
                self._hr_ewma = w * hr + (1.0 - w) * self._hr_ewma

            if not self.hr_trend_series.count():
                self._hr_ewma = hr

            total_cal = self.settings.SETTLING_DURATION + self.settings.BASELINE_DURATION
            if self.settings.SETTLING_DURATION <= elapsed < total_cal:
                self.baseline_hr_values.append(self._hr_ewma)
            elif self.baseline_hr is None and self.baseline_hr_values:
                self.baseline_hr = sum(self.baseline_hr_values) / len(self.baseline_hr_values)

            if plot_elapsed < 0:
                return

            self._session_hr_values.append(self._hr_ewma)
            if not self._main_plots_frozen:
                self.hr_trend_series.append(plot_elapsed, self._hr_ewma)

            if self.baseline_hr is not None:
                if not hasattr(self, 'hr_baseline_series'):
                    self.hr_baseline_series = QLineSeries()
                    self.hr_baseline_series.setName("Baseline HR (bpm)")
                    pen = QPen(QColor(80, 80, 80))
                    pen.setStyle(Qt.DotLine)
                    pen.setWidth(2)
                    self.hr_baseline_series.setPen(pen)
                    self.ibis_widget.plot.addSeries(self.hr_baseline_series)
                    self.hr_baseline_series.attachAxis(self.ibis_widget.x_axis)
                    self.hr_baseline_series.attachAxis(self.ibis_widget.y_axis)
                if not self._main_plots_frozen:
                    self.hr_baseline_series.clear()
                    self.hr_baseline_series.append(plot_elapsed - 60, self.baseline_hr)
                    self.hr_baseline_series.append(plot_elapsed + 2, self.baseline_hr)

            # Expand-only Y-axis
            min_span = 40
            hr_low = hr - 10
            hr_high = hr + 10

            hr_low = int(hr_low // 10) * 10
            hr_high = int(-(-hr_high // 10)) * 10

            if self._hr_axis_floor is None:
                mid = round(hr / 10) * 10
                self._hr_axis_floor = max(mid - min_span // 2, 30)
                self._hr_axis_ceiling = self._hr_axis_floor + min_span

            if hr_low < self._hr_axis_floor:
                self._hr_axis_floor = max(hr_low, 30)
            if hr_high > self._hr_axis_ceiling:
                self._hr_axis_ceiling = min(hr_high, 220)

            if self._hr_axis_ceiling - self._hr_axis_floor < min_span:
                mid = (self._hr_axis_floor + self._hr_axis_ceiling) / 2
                self._hr_axis_floor = max(int(mid - min_span // 2), 30)
                self._hr_axis_ceiling = self._hr_axis_floor + min_span

            if not self._main_plots_frozen:
                self.ibis_widget.y_axis.setRange(self._hr_axis_floor, self._hr_axis_ceiling)
                self.ibis_widget.x_axis.setRange(plot_elapsed - 60, plot_elapsed + 2)
                self._sync_aux_windows_to_main_xrange(
                    plot_elapsed - 60,
                    plot_elapsed + 2,
                )
            else:
                self._sync_aux_windows_to_main_xrange(
                    float(self.ibis_widget.x_axis.min()),
                    float(self.ibis_widget.x_axis.max()),
                )

        except Exception as e:
            print(f"HR Plot Error: {e}")    
