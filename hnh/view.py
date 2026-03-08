from datetime import datetime, date
import hashlib
import os
import json
import math
import random
import shutil
import statistics
import time
from pathlib import Path
import numpy as np
import pyqtgraph as pg
from PySide6.QtCharts import QLineSeries, QChartView, QChart, QValueAxis, QAreaSeries
from PySide6.QtGui import (
    QPen, QIcon, QImage, QLinearGradient, QBrush, QGradient, QColor, QPixmap, QFont,
    QKeySequence, QShortcut, QDesktopServices, QPainter,
)
from PySide6.QtCore import (
    Qt, QThread, Signal, Slot, QObject, QTimer, QMargins, QSize, QPointF, QEvent, QPoint,
    QRect, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QAbstractAnimation,
    QEventLoop, QUrl, QDate,
)
from PySide6.QtBluetooth import QBluetoothAddress, QBluetoothDeviceInfo
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QComboBox, QSlider, QGroupBox, QFormLayout, QCheckBox, QLineEdit, QTextEdit,
    QProgressBar, QGridLayout, QSizePolicy, QStatusBar, QFrame, QCompleter,
    QGraphicsView,
    QMessageBox, QDialog, QScrollArea, QGraphicsOpacityEffect, QInputDialog, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDateEdit,
    QTabWidget, QListWidget, QListWidgetItem, QSplitter,
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
    PLOT_WARMUP_SECONDS,
    MAX_BREATHING_RATE, MIN_BREATHING_RATE, MIN_HRV_TARGET, MAX_HRV_TARGET,
    MIN_PLOT_IBI, MAX_PLOT_IBI,
    ECG_SAMPLE_RATE,
    ECG_QRS_UNCERTAINTY_PCT, ECG_QTc_UNCERTAINTY_PCT,
    RMSSD_NOISY_MS, RMSSD_POOR_MS, SIGNAL_DEGRADE_POPUP_COUNT,
    SIGNAL_POPUP_AUTO_DISMISS_MS,
    PSD_VAGAL_BAND,
)
from hnh.settings import Settings, SettingsDialog, REGISTRY
from hnh.report import (
    format_datetime_for_display,
    generate_session_report,
    generate_session_share_pdf,
    get_date_display_format_for_qt,
)
from hnh.session_artifacts import (
    SessionBundle,
    create_session_bundle,
    default_qtc_payload,
    write_manifest,
)
from hnh.session_artifacts import _slugify as _slugify_profile
from hnh.edf_export import export_session_edf_plus
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

# Popup reasons that auto-dismiss; others (erratic HR, no data, total dropout) require acknowledgment.

_SIGNAL_POPUP_AUTO_DISMISS_REASONS = frozenset({
    "Signal dropout or noise",
    "Poor signal \u2014 electrodes may be dry",
})

_CARD0_DISCLAIMER_PATH = Path(__file__).with_name("disclaimer.md")
_RESEARCH_USE_WARNING = "RESEARCH USE ONLY - NOT FOR CLINICAL DIAGNOSIS OR TREATMENT."
_CARD0_DISCLAIMER_FALLBACK = (
    "# Research Use Disclaimer\n\n"
    "This software is intended only for investigational and research use under\n"
    "qualified clinical supervision. It is not intended for diagnosis or treatment.\n\n"
    "Please review the full disclaimer in `hnh/disclaimer.md`."
)


def _load_card0_disclaimer_text() -> str:
    try:
        text = _CARD0_DISCLAIMER_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return _CARD0_DISCLAIMER_FALLBACK
    return text or _CARD0_DISCLAIMER_FALLBACK


_CARD0_DISCLAIMER_TEXT = _load_card0_disclaimer_text()


def _one_page_share_path(bundle: SessionBundle, report_stage: str) -> Path:
    if report_stage.strip().lower() == "draft":
        return bundle.session_dir / "session_share_draft.pdf"
    return bundle.session_dir / "session_share.pdf"


def _warning_ok(parent, title: str, text: str) -> None:
    """Show warning dialog with Ok as default/focused so Enter dismisses."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Ok)
    msg.setDefaultButton(QMessageBox.Ok)
    msg.exec()


def _info_ok(parent, title: str, text: str) -> None:
    """Show information dialog with Ok as default/focused so Enter dismisses."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Ok)
    msg.setDefaultButton(QMessageBox.Ok)
    msg.exec()


def _save_last_sensor(name, address):
    if not name or "verity" in (name or "").lower():
        return
    try:
        SENSOR_CONFIG.write_text(json.dumps({"name": name, "address": address}))
    except Exception:
        pass

def _load_last_sensor():
    try:
        data = json.loads(SENSOR_CONFIG.read_text())
        if data and "verity" in (data.get("name") or "").lower():
            SENSOR_CONFIG.unlink(missing_ok=True)
            return None
        return data
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
        self._disclaimer.setTextFormat(Qt.MarkdownText)
        card_lay.addWidget(self._disclaimer)
        lay.addWidget(self._card)
        lay.addSpacing(12)

        self._ack_notice = QLabel(
            "By checking the acknowledgment below, you confirm that you have read, "
            "understood, and agree to these terms for this monitoring session."
        )
        self._ack_notice.setWordWrap(True)
        self._ack_notice.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._ack_notice)
        lay.addSpacing(4)

        self._accept_cb = QCheckBox(
            "I acknowledge that I have read and understood the disclaimer."
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
        self._ack_notice.setStyleSheet(
            f"color: #7f8c8d; font-size: {max(12, int(body_px * 0.9))}px; font-style: italic;"
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


def _skip_password_check() -> bool:
    """Return True if password verification should be bypassed (e.g. lockout recovery)."""
    val = os.environ.get("HNH_SKIP_PASSWORD", "").strip().lower()
    return val in ("1", "true", "yes")


class ProfileSelectionDialog(QDialog):
    """Select the active user profile for this app session."""

    def __init__(
        self,
        profiles: list[str],
        last_profile: str | None,
        profile_store: ProfileStore | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._profile_store = profile_store
        self.selected_profile: str | None = None
        self.password_entered: str = ""
        self.setModal(True)
        self.setWindowTitle("Select Session User")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        info = QLabel(
            "Choose who is using this session. This controls profile-specific settings and history."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._combo = QComboBox()
        self._combo.setEditable(False)
        self._combo.setMinimumWidth(195)
        self._combo.setMaximumWidth(195)
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
            unique_profiles = ["Admin"]
        self._combo.addItems(unique_profiles)
        if last_profile:
            idx = self._combo.findText(last_profile, Qt.MatchFixedString)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        form.addRow("User profile:", self._combo)

        self._pw_edit = QLineEdit()
        self._pw_edit.setPlaceholderText("Enter password (optional for profiles without one)")
        self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_edit.setMinimumWidth(195)
        self._pw_edit.setMaximumWidth(195)
        form.addRow("Password:", self._pw_edit)
        root.addLayout(form)

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
            _warning_ok(self, "Invalid Profile", "Profile name cannot be empty.")
            return
        idx = self._combo.findText(name, Qt.MatchFixedString)
        if idx < 0:
            self._combo.addItem(name)
            idx = self._combo.count() - 1
        self._combo.setCurrentIndex(idx)

    def _accept_selected(self):
        name = self._combo.currentText().strip()
        if not name:
            _warning_ok(self, "Profile Required", "Please select a profile.")
            return
        if self._profile_store and not _skip_password_check():
            if not self._profile_store.verify_profile_password(
                name, self._pw_edit.text()
            ):
                _warning_ok(
                    self,
                    "Invalid Password",
                    "The password does not match this profile. Try again or use "
                    '"Continue as Guest".',
                )
                self._pw_edit.clear()
                self._pw_edit.setFocus()
                return
        self.selected_profile = name
        self.password_entered = self._pw_edit.text()
        self.accept()

    def _accept_guest(self):
        self.selected_profile = "Guest"
        self.accept()


class SessionHistoryDialog(QDialog):
    """Read-only session history list for the active profile, with Replay tab."""

    def __init__(self, profile_name: str, sessions: list[dict[str, str | None]], parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(f"Session History — {profile_name}")
        self.resize(980, 620)

        self._profile_name = profile_name
        self._sessions = sessions

        root = QVBoxLayout(self)
        tabs = QTabWidget()

        # ---- Tab 1: History ----
        tab_history = QWidget()
        tab_history_layout = QVBoxLayout(tab_history)
        self._summary = QLabel("")
        self._summary.setStyleSheet("font-size: 12px; color: #2c3e50;")
        tab_history_layout.addWidget(self._summary)

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
        tab_history_layout.addWidget(self._table, stretch=1)

        tabs.addTab(tab_history, "History")

        # ---- Tab 2: Replay ----
        tab_replay = QWidget()
        tab_replay_layout = QVBoxLayout(tab_replay)

        replay_controls = QHBoxLayout()
        replay_controls.addWidget(QLabel("Session:"))
        self._replay_session_combo = QComboBox()
        self._replay_session_combo.setMinimumWidth(280)
        self._replay_session_combo.currentIndexChanged.connect(self._on_replay_session_changed)
        replay_controls.addWidget(self._replay_session_combo)

        self._replay_load_btn = QPushButton("Load")
        self._replay_load_btn.clicked.connect(self._replay_load_session)
        replay_controls.addWidget(self._replay_load_btn)

        replay_controls.addSpacing(16)
        self._replay_play_btn = QPushButton("Play")
        self._replay_play_btn.setEnabled(False)
        self._replay_play_btn.clicked.connect(self._replay_toggle_play)
        replay_controls.addWidget(self._replay_play_btn)

        replay_controls.addWidget(QLabel("Speed:"))
        self._replay_speed_combo = QComboBox()
        for label, mult in [("1×", 1.0), ("2×", 2.0), ("4×", 4.0), ("0.5×", 0.5)]:
            self._replay_speed_combo.addItem(label, mult)
        self._replay_speed_combo.setCurrentIndex(0)
        replay_controls.addWidget(self._replay_speed_combo)

        replay_controls.addStretch()
        tab_replay_layout.addLayout(replay_controls)

        hint = QLabel(
            "Use mouse to pan; mouse wheel on each axis to zoom. "
            "Drag the timeline scrubber or use Play to scroll through time."
        )
        hint.setStyleSheet("font-size: 11px; color: #666; font-style: italic;")
        tab_replay_layout.addWidget(hint)

        self._replay_plot_stack = pg.GraphicsLayoutWidget()
        self._replay_plot_stack.setBackground("w")
        self._replay_hr_plot = self._replay_plot_stack.addPlot(row=0, col=0, title="HR (bpm)")
        self._replay_hr_plot.setLabel("bottom", "Time (s)")
        self._replay_hr_plot.setMouseEnabled(x=True, y=True)
        self._replay_hr_plot.showGrid(x=True, y=True, alpha=0.3)
        self._replay_plot_stack.nextRow()
        self._replay_rmssd_plot = self._replay_plot_stack.addPlot(row=1, col=0, title="RMSSD (ms)")
        self._replay_rmssd_plot.setLabel("bottom", "Time (s)")
        self._replay_rmssd_plot.setMouseEnabled(x=True, y=True)
        self._replay_rmssd_plot.showGrid(x=True, y=True, alpha=0.3)
        self._replay_plot_stack.nextRow()
        self._replay_ecg_plot = self._replay_plot_stack.addPlot(row=2, col=0, title="ECG")
        self._replay_ecg_plot.setLabel("bottom", "Time (s)")
        self._replay_ecg_plot.setMouseEnabled(x=True, y=True)
        self._replay_ecg_plot.showGrid(x=True, y=True, alpha=0.3)
        tab_replay_layout.addWidget(self._replay_plot_stack, stretch=1)

        timeline_layout = QHBoxLayout()
        timeline_layout.addWidget(QLabel("Time:"))
        self._replay_timeline_slider = QSlider(Qt.Horizontal)
        self._replay_timeline_slider.setMinimum(0)
        self._replay_timeline_slider.setMaximum(1000)
        self._replay_timeline_slider.setValue(0)
        self._replay_timeline_slider.valueChanged.connect(self._replay_on_timeline_moved)
        self._replay_timeline_slider.sliderPressed.connect(self._replay_pause)
        timeline_layout.addWidget(self._replay_timeline_slider, stretch=1)
        self._replay_time_label = QLabel("0.0 s")
        self._replay_time_label.setMinimumWidth(80)
        timeline_layout.addWidget(self._replay_time_label)
        tab_replay_layout.addLayout(timeline_layout)

        ann_layout = QHBoxLayout()
        ann_layout.addWidget(QLabel("Jump to:"))
        self._replay_ann_combo = QComboBox()
        self._replay_ann_combo.setMinimumWidth(200)
        self._replay_ann_combo.currentIndexChanged.connect(self._replay_jump_to_annotation)
        ann_layout.addWidget(self._replay_ann_combo)
        ann_layout.addStretch()
        tab_replay_layout.addLayout(ann_layout)

        tabs.addTab(tab_replay, "Replay")

        root.addWidget(tabs, stretch=1)

        actions = QHBoxLayout()
        actions.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        root.addLayout(actions)

        self._replay_data: dict = {}
        self._replay_playing = False
        self._replay_timer = QTimer(self)
        self._replay_timer.timeout.connect(self._replay_tick)
        self._replay_playhead_sec = 0.0
        self._replay_playhead_line_hr: pg.InfiniteLine | None = None
        self._replay_playhead_line_rmssd: pg.InfiniteLine | None = None
        self._replay_playhead_line_ecg: pg.InfiniteLine | None = None

        self.populate(profile_name=profile_name, sessions=sessions)
        self._populate_replay_session_combo()

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

    def _populate_replay_session_combo(self):
        """Fill session combo for Replay tab."""
        self._replay_session_combo.blockSignals(True)
        self._replay_session_combo.clear()
        self._replay_session_combo.addItem("— Select session —", None)
        for s in self._sessions:
            session_dir = s.get("session_dir") or ""
            session_id = str(s.get("session_id") or "--")
            started = self._format_started(s.get("started_at"))
            label = f"{started}  ({session_id})"
            self._replay_session_combo.addItem(label, session_dir)
        self._replay_session_combo.blockSignals(False)

    def _on_replay_session_changed(self, _idx: int):
        """When session selection changes, enable Load if valid."""
        session_dir = self._replay_session_combo.currentData()
        self._replay_load_btn.setEnabled(bool(session_dir))

    def _replay_load_session(self):
        """Load selected session data and display plots."""
        session_dir = self._replay_session_combo.currentData()
        if not session_dir:
            return
        from hnh.replay_loader import load_session_replay_data
        data = load_session_replay_data(Path(session_dir))
        self._replay_data = data
        duration = data.get("duration_seconds") or 0.0

        # Clear plots
        self._replay_hr_plot.clear()
        self._replay_rmssd_plot.clear()
        self._replay_ecg_plot.clear()

        # Remove old playhead lines
        for plot, line in [
            (self._replay_hr_plot, self._replay_playhead_line_hr),
            (self._replay_rmssd_plot, self._replay_playhead_line_rmssd),
            (self._replay_ecg_plot, self._replay_playhead_line_ecg),
        ]:
            if line is not None:
                try:
                    plot.removeItem(line)
                except Exception:
                    pass
        self._replay_playhead_line_hr = None
        self._replay_playhead_line_rmssd = None
        self._replay_playhead_line_ecg = None

        hr_t = data.get("hr_times") or []
        hr_v = data.get("hr_values") or []
        rmssd_t = data.get("rmssd_times") or []
        rmssd_v = data.get("rmssd_values") or []
        ecg_samples = data.get("ecg_samples") or []
        ecg_rate = data.get("ecg_sample_rate_hz") or 130

        if hr_t and hr_v:
            self._replay_hr_plot.plot(hr_t, hr_v, pen=pg.mkPen("r", width=1.5))
        if rmssd_t and rmssd_v:
            self._replay_rmssd_plot.plot(rmssd_t, rmssd_v, pen=pg.mkPen("b", width=1.5))

        if ecg_samples:
            ecg_t = [i / ecg_rate for i in range(len(ecg_samples))]
            self._replay_ecg_plot.plot(ecg_t, ecg_samples, pen=pg.mkPen("k", width=1.0))
        else:
            self._replay_ecg_plot.addItem(pg.TextItem("No ECG data (load from EDF or CSV)", anchor=(0.5, 0.5)))

        # Playhead lines
        self._replay_playhead_line_hr = pg.InfiniteLine(
            pos=0, angle=90, movable=False, pen=pg.mkPen((200, 80, 80, 200), width=1.5)
        )
        self._replay_playhead_line_rmssd = pg.InfiniteLine(
            pos=0, angle=90, movable=False, pen=pg.mkPen((80, 80, 200, 200), width=1.5)
        )
        self._replay_playhead_line_ecg = pg.InfiniteLine(
            pos=0, angle=90, movable=False, pen=pg.mkPen((80, 80, 80, 200), width=1.5)
        )
        self._replay_hr_plot.addItem(self._replay_playhead_line_hr)
        self._replay_rmssd_plot.addItem(self._replay_playhead_line_rmssd)
        self._replay_ecg_plot.addItem(self._replay_playhead_line_ecg)

        # Timeline slider
        max_val = max(1000, int(duration * 10)) if duration > 0 else 1000
        self._replay_timeline_slider.setMaximum(max_val)
        self._replay_timeline_slider.setValue(0)
        self._replay_playhead_sec = 0.0
        self._replay_time_label.setText("0.0 s")

        # Annotations
        self._replay_ann_combo.blockSignals(True)
        self._replay_ann_combo.clear()
        self._replay_ann_combo.addItem("— Select annotation —", -1.0)
        for t, text in data.get("annotations") or []:
            self._replay_ann_combo.addItem(f"{t:.1f}s: {text[:40]}…" if len(text) > 40 else f"{t:.1f}s: {text}", t)
        self._replay_ann_combo.blockSignals(False)

        self._replay_play_btn.setEnabled(duration > 0)
        self._replay_playing = False
        self._replay_play_btn.setText("Play")
        self._replay_timer.stop()

    def _replay_toggle_play(self):
        """Play or pause replay."""
        if not self._replay_data:
            return
        duration = self._replay_data.get("duration_seconds") or 0.0
        if duration <= 0:
            return
        self._replay_playing = not self._replay_playing
        self._replay_play_btn.setText("Pause" if self._replay_playing else "Play")
        if self._replay_playing:
            if self._replay_playhead_sec >= duration:
                self._replay_playhead_sec = 0.0
            self._replay_timer.start(50)
        else:
            self._replay_timer.stop()

    def _replay_tick(self):
        """Advance playhead during replay."""
        if not self._replay_data:
            return
        duration = self._replay_data.get("duration_seconds") or 0.0
        speed = self._replay_speed_combo.currentData() or 1.0
        self._replay_playhead_sec += 0.05 * speed
        if self._replay_playhead_sec >= duration:
            self._replay_playhead_sec = duration
            self._replay_playing = False
            self._replay_play_btn.setText("Play")
            self._replay_timer.stop()
        self._replay_update_playhead()

    def _replay_update_playhead(self):
        """Update playhead position and timeline slider."""
        sec = self._replay_playhead_sec
        self._replay_time_label.setText(f"{sec:.1f} s")
        duration = self._replay_data.get("duration_seconds") or 0.0
        max_slider = self._replay_timeline_slider.maximum()
        if duration > 0 and max_slider > 0:
            val = int(sec / duration * max_slider)
            self._replay_timeline_slider.blockSignals(True)
            self._replay_timeline_slider.setValue(val)
            self._replay_timeline_slider.blockSignals(False)
        if self._replay_playhead_line_hr is not None:
            self._replay_playhead_line_hr.setValue(sec)
        if self._replay_playhead_line_rmssd is not None:
            self._replay_playhead_line_rmssd.setValue(sec)
        if self._replay_playhead_line_ecg is not None:
            self._replay_playhead_line_ecg.setValue(sec)

    def _replay_on_timeline_moved(self, val: int):
        """User dragged timeline scrubber."""
        max_slider = self._replay_timeline_slider.maximum()
        duration = self._replay_data.get("duration_seconds") or 0.0
        if max_slider > 0 and duration > 0:
            self._replay_playhead_sec = val / max_slider * duration
            self._replay_update_playhead()

    def _replay_pause(self):
        """Pause replay when user interacts with timeline."""
        if self._replay_playing:
            self._replay_playing = False
            self._replay_play_btn.setText("Play")
            self._replay_timer.stop()

    def _replay_jump_to_annotation(self, idx: int):
        """Jump playhead to selected annotation time."""
        t = self._replay_ann_combo.currentData()
        if t is not None and t >= 0:
            self._replay_playhead_sec = float(t)
            self._replay_update_playhead()


class TrendsWindow(QMainWindow):
    """Window to compare-plot session trends over day/week/month/year spans."""

    def __init__(self, profile_store, active_profile: str, is_admin: bool = True, parent=None):
        super().__init__(parent)
        self._profile_store = profile_store
        self._active_profile = active_profile
        self._is_admin = is_admin
        self.setWindowTitle("Hertz & Hearts — Session Trends")
        self.resize(960, 560)

        tabs = QTabWidget()

        # ---- Tab 1: Trend Plots (existing) ----
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Profile:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(140)
        for name in profile_store.list_profiles():
            self._profile_combo.addItem(name)
        idx = self._profile_combo.findText(active_profile, Qt.MatchFixedString)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        self._profile_combo.currentTextChanged.connect(self._refresh_plot)
        self._profile_combo.setEnabled(is_admin)
        controls.addWidget(self._profile_combo)

        controls.addSpacing(24)
        hint = QLabel(
            "Use mouse to pan; mouse wheel on each axis to zoom. "
            "Drag the vertical line over a point to show its values.\n"
            "Legend may be moved if desired."
        )
        hint.setStyleSheet("font-size: 11px; color: #666; font-style: italic;")
        hint.setWordWrap(True)
        hint.setMinimumWidth(560)
        controls.addWidget(hint)

        controls.addStretch()
        tab1_layout.addLayout(controls)

        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot_widget = pg.PlotWidget(axisItems={"bottom": date_axis})
        self._plot_widget.setLabel("left", "Value")
        self._plot_widget.setLabel("bottom", "Date & Time")
        self._plot_widget.addLegend(
            offset=(-20, 20),
            brush=(30, 30, 35, 200),
        )
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        tab1_layout.addWidget(self._plot_widget)

        self._hover_label = QLabel(self._plot_widget)
        self._hover_label.setStyleSheet(
            "background: rgba(255,255,255,0.92); padding: 6px 8px; "
            "border: 1px solid #999; font-size: 11px; font-family: monospace;"
        )
        self._hover_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._hover_label.hide()
        self._trend_data: dict = {}
        self._cursor_line: pg.InfiniteLine | None = None

        tabs.addTab(tab1, "Trend Plots")

        # ---- Tab 2: Compare (UI shell, no backend) ----
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)

        compare_controls = QHBoxLayout()
        compare_controls.addWidget(QLabel("Profile:"))
        self._compare_profile_combo = QComboBox()
        self._compare_profile_combo.setMinimumWidth(140)
        for name in profile_store.list_profiles():
            self._compare_profile_combo.addItem(name)
        idx = self._compare_profile_combo.findText(active_profile, Qt.MatchFixedString)
        if idx >= 0:
            self._compare_profile_combo.setCurrentIndex(idx)
        self._compare_profile_combo.setEnabled(is_admin)
        self._compare_profile_combo.currentTextChanged.connect(self._refresh_compare_session_list)
        compare_controls.addWidget(self._compare_profile_combo)

        compare_controls.addSpacing(16)
        compare_controls.addWidget(QLabel("Metrics:"))
        self._metric_hr = QCheckBox("HR")
        self._metric_hr.setChecked(True)
        self._metric_rmssd = QCheckBox("RMSSD")
        self._metric_rmssd.setChecked(True)
        self._metric_sdnn = QCheckBox("SDNN")
        self._metric_sdnn.setChecked(True)
        self._metric_qtc = QCheckBox("QTc")
        self._metric_qtc.setChecked(True)
        self._metric_lfhf = QCheckBox("LF/HF")
        self._metric_lfhf.setChecked(False)
        for cb in (self._metric_hr, self._metric_rmssd, self._metric_sdnn, self._metric_qtc, self._metric_lfhf):
            compare_controls.addWidget(cb)
            cb.stateChanged.connect(self._compare_selection_changed)
        compare_controls.addSpacing(16)
        self._clear_compare_btn = QPushButton("Clear selection")
        self._clear_compare_btn.clicked.connect(self._compare_clear_selection)
        compare_controls.addWidget(self._clear_compare_btn)
        compare_controls.addStretch()
        tab2_layout.addLayout(compare_controls)

        splitter = QSplitter(Qt.Horizontal)

        # Left: session list (loaded from profile_store)
        session_list_container = QWidget()
        session_list_layout = QVBoxLayout(session_list_container)
        session_list_layout.addWidget(QLabel("Sessions (select 2+ to compare)"))
        self._session_list = QListWidget()
        self._session_list.setMinimumWidth(220)
        self._session_list.setMaximumWidth(320)
        self._compare_trends_lookup: dict[str, dict] = {}
        self._session_list.itemChanged.connect(self._compare_selection_changed)
        session_list_layout.addWidget(self._session_list)
        splitter.addWidget(session_list_container)

        # Right: table or placeholder
        self._compare_table_stack = QWidget()
        self._compare_table_stack_layout = QVBoxLayout(self._compare_table_stack)
        self._compare_placeholder = QLabel("Select 2 or more sessions from the list to compare.")
        self._compare_placeholder.setAlignment(Qt.AlignCenter)
        self._compare_placeholder.setStyleSheet("font-size: 13px; color: #666; padding: 40px;")
        self._compare_table = QTableWidget()
        self._compare_table.setAlternatingRowColors(True)
        self._compare_table.hide()
        self._compare_table_stack_layout.addWidget(self._compare_placeholder)
        self._compare_table_stack_layout.addWidget(self._compare_table)
        splitter.addWidget(self._compare_table_stack)

        splitter.setSizes([280, 600])
        tab2_layout.addWidget(splitter)

        hint2 = QLabel("Use Trend Plots tab for time-series view.")
        hint2.setStyleSheet("font-size: 11px; color: #888; font-style: italic;")
        tab2_layout.addWidget(hint2)

        tabs.addTab(tab2, "Compare")

        self.setCentralWidget(tabs)
        self._refresh_plot()
        self._refresh_compare_session_list()

    def _refresh_plot(self):
        profile = self._profile_combo.currentText().strip() or self._active_profile
        rows = self._profile_store.list_session_trends(profile, span="year")
        self._plot_widget.clear()
        self._trend_data = {}
        if not rows:
            return
        x = []
        hr_y, rmssd_y, sdnn_y, qtc_y = [], [], [], []
        for r in rows:
            try:
                dt = datetime.fromisoformat(str(r["ended_at"]))
                x.append(dt.timestamp())
            except (ValueError, TypeError):
                continue
            hr_y.append(r.get("avg_hr") if r.get("avg_hr") is not None else float("nan"))
            rmssd_y.append(r.get("avg_rmssd") if r.get("avg_rmssd") is not None else float("nan"))
            sdnn_y.append(r.get("avg_sdnn") if r.get("avg_sdnn") is not None else float("nan"))
            qtc_y.append(r.get("qtc_ms") if r.get("qtc_ms") is not None else float("nan"))
        if not x:
            return
        self._trend_data = {"x": x, "hr": hr_y, "rmssd": rmssd_y, "sdnn": sdnn_y, "qtc": qtc_y}
        _dotted = Qt.PenStyle.DotLine
        if any(v == v for v in hr_y):
            self._plot_widget.plot(
                x, hr_y,
                pen=pg.mkPen("r", width=1, style=_dotted),
                symbol="o", symbolSize=8, symbolBrush="r", symbolPen="r",
                name="HR (bpm)",
            )
        if any(v == v for v in rmssd_y):
            self._plot_widget.plot(
                x, rmssd_y,
                pen=pg.mkPen("b", width=1, style=_dotted),
                symbol="o", symbolSize=8, symbolBrush="b", symbolPen="b",
                name="RMSSD (ms)",
            )
        if any(v == v for v in sdnn_y):
            self._plot_widget.plot(
                x, sdnn_y,
                pen=pg.mkPen("g", width=1, style=_dotted),
                symbol="o", symbolSize=8, symbolBrush="g", symbolPen="g",
                name="SDNN (ms)",
            )
        if any(v == v for v in qtc_y):
            self._plot_widget.plot(
                x, qtc_y,
                pen=pg.mkPen("m", width=1, style=_dotted),
                symbol="o", symbolSize=8, symbolBrush="m", symbolPen="m",
                name="QTc (ms)",
            )
        x_min, x_max = min(x), max(x)
        x_center = (x_min + x_max) / 2.0
        if self._cursor_line is not None:
            try:
                self._cursor_line.sigPositionChanged.disconnect()
            except Exception:
                pass
            self._plot_widget.removeItem(self._cursor_line)
        self._cursor_line = pg.InfiniteLine(
            pos=x_center,
            angle=90,
            movable=True,
            bounds=[x_min, x_max],
            pen=pg.mkPen((60, 120, 190, 200), width=1.5),
            label="",
        )
        self._plot_widget.addItem(self._cursor_line)
        self._cursor_line.sigPositionChanged.connect(self._on_cursor_line_moved)

    def _nearest_point_index_within_pixels(self, line_x: float, hit_radius_px: float = 30) -> int | None:
        """Return index of nearest data point if cursor is within hit_radius_px (x-axis) in screen space."""
        x_arr = self._trend_data.get("x", [])
        hr = self._trend_data.get("hr", [])
        if not x_arr:
            return None
        vb = self._plot_widget.getViewBox()
        if vb is None:
            return None
        best_i = min(range(len(x_arr)), key=lambda i: abs(x_arr[i] - line_x))
        y_ref = None
        for ys in (hr, self._trend_data.get("rmssd", []), self._trend_data.get("sdnn", []), self._trend_data.get("qtc", [])):
            if best_i < len(ys) and ys[best_i] == ys[best_i]:
                y_ref = ys[best_i]
                break
        if y_ref is None:
            return None
        try:
            sp_point = vb.mapFromView(QPointF(x_arr[best_i], y_ref))
            sp_line = vb.mapFromView(QPointF(line_x, y_ref))
        except Exception:
            return None
        dx_px = abs(sp_point.x() - sp_line.x())
        if dx_px <= hit_radius_px:
            return best_i
        return None

    def _on_cursor_line_moved(self, line):
        if not self._trend_data or line is None:
            self._hover_label.hide()
            return
        try:
            line_x = float(line.value())
        except (TypeError, ValueError):
            self._hover_label.hide()
            return
        idx = self._nearest_point_index_within_pixels(line_x)
        if idx is None:
            self._hover_label.hide()
            return
        x_arr = self._trend_data.get("x", [])
        hr_arr = self._trend_data.get("hr", [])
        rmssd_arr = self._trend_data.get("rmssd", [])
        sdnn_arr = self._trend_data.get("sdnn", [])
        qtc_arr = self._trend_data.get("qtc", [])
        x = x_arr[idx]
        hr = float(hr_arr[idx]) if idx < len(hr_arr) and hr_arr[idx] == hr_arr[idx] else None
        rmssd = float(rmssd_arr[idx]) if idx < len(rmssd_arr) and rmssd_arr[idx] == rmssd_arr[idx] else None
        sdnn = float(sdnn_arr[idx]) if idx < len(sdnn_arr) and sdnn_arr[idx] == sdnn_arr[idx] else None
        qtc = float(qtc_arr[idx]) if idx < len(qtc_arr) and qtc_arr[idx] == qtc_arr[idx] else None
        try:
            dt = datetime.fromtimestamp(x)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError):
            time_str = "—"
        lines = [time_str]
        if hr is not None:
            lines.append(f"HR: {hr:.1f} bpm")
        if rmssd is not None:
            lines.append(f"RMSSD: {rmssd:.1f} ms")
        if sdnn is not None:
            lines.append(f"SDNN: {sdnn:.1f} ms")
        if qtc is not None:
            lines.append(f"QTc: {qtc:.0f} ms")
        self._hover_label.setText("\n".join(lines))
        self._hover_label.adjustSize()
        self._hover_label.move(12, 12)
        self._hover_label.show()

    def _refresh_compare_session_list(self):
        """Load session list from profile_store. Build trends lookup for table data."""
        profile = self._compare_profile_combo.currentText().strip() or self._active_profile
        sessions = self._profile_store.list_sessions(profile, limit=100)
        trends_rows = self._profile_store.list_session_trends(profile, span="year")
        self._compare_trends_lookup = {r["session_id"]: r for r in trends_rows}

        self._session_list.blockSignals(True)
        self._session_list.clear()
        for s in sessions:
            ended_at = s.get("ended_at")
            started_at = s.get("started_at")
            session_id = s.get("session_id", "")
            try:
                end_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00")) if ended_at else None
            except (ValueError, TypeError):
                end_dt = None
            try:
                start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00")) if started_at else None
            except (ValueError, TypeError):
                start_dt = None
            if end_dt:
                date_str = end_dt.strftime("%b %d, %Y  %H:%M")
            else:
                date_str = session_id[:15] if session_id else "—"
            if end_dt and start_dt:
                delta = end_dt - start_dt
                mins = int(delta.total_seconds() / 60)
                dur_str = f"  —  {mins} min"
            else:
                dur_str = "  —  —"
            label = date_str + dur_str
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, session_id)
            self._session_list.addItem(item)
        self._session_list.blockSignals(False)
        self._compare_selection_changed()

    def _compare_clear_selection(self):
        """Uncheck all sessions in the Compare tab list."""
        for i in range(self._session_list.count()):
            item = self._session_list.item(i)
            item.setCheckState(Qt.Unchecked)
        self._compare_placeholder.show()
        self._compare_table.hide()

    def _compare_selection_changed(self):
        """Show table with real session data when 2+ sessions selected; else show placeholder."""
        checked = [
            self._session_list.item(i)
            for i in range(self._session_list.count())
            if self._session_list.item(i).checkState() == Qt.Checked
        ]
        if len(checked) < 2:
            self._compare_placeholder.show()
            self._compare_table.hide()
            return
        session_ids = [item.data(Qt.UserRole) or "" for item in checked]
        session_ids = list(reversed(session_ids))  # oldest first: past → present for table
        lookup = getattr(self, "_compare_trends_lookup", {}) or {}

        # Build column labels: short date/time per session, then delta columns
        col_labels = []
        for sid in session_ids:
            row = lookup.get(sid, {})
            ended = row.get("ended_at")
            try:
                dt = datetime.fromisoformat(str(ended).replace("Z", "+00:00")) if ended else None
                col_labels.append(dt.strftime("%b %d %H:%M") if dt else sid[:12])
            except (ValueError, TypeError):
                col_labels.append(sid[:12] if sid else "—")
        for i in range(len(session_ids) - 1):
            col_labels.append(f"Δ ({i + 1}→{i + 2})")

        # Build rows from real trend data
        rows = []
        for metric_key, label, fmt in [
            ("hr", "HR (bpm)", lambda v: f"{v:.0f}" if v is not None else "—"),
            ("rmssd", "RMSSD (ms)", lambda v: f"{v:.1f}" if v is not None else "—"),
            ("sdnn", "SDNN (ms)", lambda v: f"{v:.1f}" if v is not None else "—"),
            ("qtc", "QTc (ms)", lambda v: f"{v:.0f}" if v is not None else "—"),
        ]:
            key_map = {"hr": "avg_hr", "rmssd": "avg_rmssd", "sdnn": "avg_sdnn", "qtc": "qtc_ms"}
            store_key = key_map.get(metric_key, metric_key)
            if (metric_key == "hr" and not self._metric_hr.isChecked()) or \
               (metric_key == "rmssd" and not self._metric_rmssd.isChecked()) or \
               (metric_key == "sdnn" and not self._metric_sdnn.isChecked()) or \
               (metric_key == "qtc" and not self._metric_qtc.isChecked()):
                continue
            vals = []
            for sid in session_ids:
                r = lookup.get(sid, {})
                v = r.get(store_key) if isinstance(r, dict) else None
                vals.append(fmt(v))
            deltas = []
            for i in range(len(vals) - 1):
                r1, r2 = lookup.get(session_ids[i], {}), lookup.get(session_ids[i + 1], {})
                v1 = r1.get(store_key) if isinstance(r1, dict) else None
                v2 = r2.get(store_key) if isinstance(r2, dict) else None
                if v1 is not None and v2 is not None:
                    d = v2 - v1
                    deltas.append(f"{d:+.1f}" if "ms" in label else f"{d:+.0f}")
                else:
                    deltas.append("—")
            rows.append((label, vals, deltas))

        if self._metric_lfhf.isChecked():
            rows.append(("LF/HF", ["—"] * len(session_ids), ["—"] * (len(session_ids) - 1)))

        if not rows:
            self._compare_placeholder.show()
            self._compare_table.hide()
            return
        self._compare_placeholder.hide()
        self._compare_table.show()
        self._compare_table.setColumnCount(len(col_labels))
        self._compare_table.setRowCount(len(rows))
        self._compare_table.setHorizontalHeaderLabels(col_labels)
        self._compare_table.setVerticalHeaderLabels([m for m, _, _ in rows])
        for r, (_, vals, deltas) in enumerate(rows):
            for c, v in enumerate(vals):
                self._compare_table.setItem(r, c, QTableWidgetItem(str(v)))
            for c, d in enumerate(deltas):
                self._compare_table.setItem(r, len(vals) + c, QTableWidgetItem(str(d)))
        self._compare_table.resizeColumnsToContents()
        self._compare_table.resizeRowsToContents()

    def set_active_profile(self, profile: str):
        self._active_profile = profile
        idx = self._profile_combo.findText(profile, Qt.MatchFixedString)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        idx_compare = self._compare_profile_combo.findText(profile, Qt.MatchFixedString)
        if idx_compare >= 0:
            self._compare_profile_combo.setCurrentIndex(idx_compare)
        self._is_admin = self._profile_store.profile_is_admin(profile)
        self._profile_combo.setEnabled(self._is_admin)
        self._compare_profile_combo.setEnabled(self._is_admin)
        self._refresh_compare_session_list()


class ProfileManagerDialog(QDialog):
    """Manage user profiles (create, rename, archive/delete, restore)."""

    def __init__(
        self,
        store: ProfileStore,
        active_profile: str,
        is_admin: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._store = store
        self._active_profile = active_profile
        self._is_admin = is_admin
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("Profile Manager")
        self.resize(860, 460)

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
        self._show_archived.setVisible(self._is_admin)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Profile", "Status", "Role", "Last Used", "Created"])
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
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.setSortingEnabled(True)
        root.addWidget(self._table, stretch=1)

        details_group = QGroupBox("Profile Details")
        details_form = QFormLayout(details_group)
        demographics_row = QWidget()
        demographics_lay = QHBoxLayout(demographics_row)
        demographics_lay.setContentsMargins(0, 0, 0, 0)
        demographics_lay.setSpacing(8)

        dob_label = QLabel("Date of Birth")
        self._dob_input = QDateEdit()
        self._dob_input.setCalendarPopup(True)
        self._dob_input.setDisplayFormat(get_date_display_format_for_qt())
        self._dob_input.setMaximumWidth(120)
        self._dob_input.setMinimumDate(QDate(1900, 1, 1))
        self._dob_input.setMaximumDate(QDate.currentDate())
        self._dob_input.setSpecialValueText("—")
        self._dob_input.setDate(QDate(1900, 1, 1))
        self._age_label = QLabel("Age: —")
        self._dob_input.dateChanged.connect(self._update_age_from_dob)
        demographics_lay.addWidget(dob_label)
        demographics_lay.addWidget(self._dob_input)
        demographics_lay.addWidget(self._age_label)

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

        self._role_row = QWidget()
        role_lay = QHBoxLayout(self._role_row)
        role_lay.setContentsMargins(0, 0, 0, 0)
        role_lay.addWidget(QLabel("Role"))
        self._role_combo = QComboBox()
        self._role_combo.addItems(["Admin", "User"])
        self._role_combo.setMaximumWidth(100)
        role_lay.addWidget(self._role_combo)
        role_lay.addStretch()
        details_form.addRow(self._role_row)
        self._role_row.setVisible(self._is_admin)

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

        self._password_btn = QPushButton("Set/Reset Password")
        self._password_btn.clicked.connect(self._set_reset_password)
        actions.addWidget(self._password_btn)

        actions.addStretch()

        save_close_btn = QPushButton("Save && Close")
        save_close_btn.clicked.connect(self._save_and_close)
        actions.addWidget(save_close_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        root.addLayout(actions)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._last_selected_profile: str | None = None
        for btn in (self._create_btn, self._rename_btn, self._archive_btn, self._restore_btn, self._delete_btn):
            btn.setVisible(self._is_admin)
        self._refresh()

    def _update_age_from_dob(self):
        qd = self._dob_input.date()
        if qd == QDate(1900, 1, 1):
            self._age_label.setText("Age: —")
            return
        try:
            birth = date(qd.year(), qd.month(), qd.day())
            today = date.today()
            age = today.year - birth.year
            if (today.month, today.day) < (birth.month, birth.day):
                age -= 1
            self._age_label.setText(f"Age: {age}" if 1 <= age <= 130 else "Age: —")
        except (ValueError, TypeError):
            self._age_label.setText("Age: —")

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
        return format_datetime_for_display(raw)

    def _refresh(self):
        previous = self._selected_profile_name() or self._active_profile
        rows = self._store.list_profiles_info(
            include_archived=self._show_archived.isChecked() if self._is_admin else True
        )
        if not self._is_admin:
            rows = [r for r in rows if str(r.get("name") or "").casefold() == self._active_profile.casefold()]
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
            role_str = str(row.get("role") or "user").strip().lower()
            role_display = "Admin" if role_str == "admin" else "User"
            role_item = QTableWidgetItem(role_display)
            last_used_item = QTableWidgetItem(
                self._fmt_time(row.get("last_used_at") if isinstance(row.get("last_used_at"), str) else None)
            )
            created_item = QTableWidgetItem(
                self._fmt_time(row.get("created_at") if isinstance(row.get("created_at"), str) else None)
            )

            self._table.setItem(idx, 0, name_item)
            self._table.setItem(idx, 1, status_item)
            self._table.setItem(idx, 2, role_item)
            self._table.setItem(idx, 3, last_used_item)
            self._table.setItem(idx, 4, created_item)
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
        self._password_btn.setEnabled(has_selection)

    def _on_selection_changed(self):
        new_name = self._selected_profile_name()
        if self._last_selected_profile and self._last_selected_profile != new_name:
            if not self._save_details(self._last_selected_profile):
                self._select_row_by_profile(self._last_selected_profile)
                return
        self._last_selected_profile = new_name
        self._update_action_states()
        self._load_selected_details()

    def _load_selected_details(self):
        name = self._selected_profile_name()
        self._last_selected_profile = name
        if not name:
            self._dob_input.setDate(QDate(1900, 1, 1))
            self._age_label.setText("Age: —")
            self._gender_input.setCurrentIndex(2)
            self._notes_input.clear()
            return
        try:
            details = self._store.get_profile_details(name)
        except ValueError:
            return
        dob_raw = details.get("dob")
        if dob_raw:
            try:
                dt = datetime.strptime(str(dob_raw).strip()[:10], "%Y-%m-%d")
                self._dob_input.setDate(QDate(dt.year, dt.month, dt.day))
            except ValueError:
                self._dob_input.setDate(QDate(1900, 1, 1))
        else:
            self._dob_input.setDate(QDate(1900, 1, 1))
        if dob_raw:
            self._update_age_from_dob()
        else:
            age = details.get("age")
            self._age_label.setText(
                f"Age: {int(age)}" if age is not None and 1 <= int(age) <= 130 else "Age: —"
            )
        gender_raw = str(details.get("gender") or "").strip()
        idx = self._gender_input.findText(gender_raw, Qt.MatchFixedString)
        self._gender_input.setCurrentIndex(idx if idx >= 0 else 2)
        self._notes_input.setPlainText(str(details.get("notes") or ""))
        if self._is_admin:
            role = self._store.get_profile_role(name)
            self._role_combo.setCurrentIndex(0 if role == "admin" else 1)
            is_own = name.casefold() == self._active_profile.casefold()
            self._role_combo.setEnabled(not is_own)

    def _save_details(self, target_name: str | None = None) -> bool:
        name = target_name or self._selected_profile_name()
        if not name:
            return True
        qd = self._dob_input.date()
        dob: str | None = None
        if qd != QDate(1900, 1, 1):
            birth = date(qd.year(), qd.month(), qd.day())
            today = date.today()
            if birth > today:
                _warning_ok(self, "Invalid DOB", "Date of birth cannot be in the future.")
                return False
            age = today.year - birth.year
            if (today.month, today.day) < (birth.month, birth.day):
                age -= 1
            if age < 1 or age > 130:
                _warning_ok(self, "Invalid DOB", "Computed age must be between 1 and 130.")
                return False
            dob = f"{birth.year:04d}-{birth.month:02d}-{birth.day:02d}"
        gender = self._gender_input.currentText().strip()
        notes = self._notes_input.toPlainText().strip()
        try:
            self._store.update_profile_details(
                name,
                dob=dob,
                gender=gender,
                notes=notes or None,
            )
            if self._is_admin:
                new_role = "admin" if self._role_combo.currentIndex() == 0 else "user"
                if name.casefold() == self._active_profile.casefold() and new_role == "user":
                    _warning_ok(
                        self,
                        "Cannot Demote",
                        "You cannot change your own role to User.",
                    )
                    return False
                self._store.set_profile_role(name, new_role)
        except ValueError as exc:
            _warning_ok(self, "Save Failed", str(exc))
            return False
        self._refresh()
        if not target_name or target_name == self._selected_profile_name():
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
            _warning_ok(self, "Invalid Profile", "Profile name cannot be empty.")
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
            _warning_ok(self, "Invalid Profile", "Profile name cannot be empty.")
            return
        try:
            renamed = self._store.rename_profile(current, new_name)
        except ValueError as exc:
            _warning_ok(self, "Rename Failed", str(exc))
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
            _warning_ok(self, "Archive Failed", str(exc))
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
            _warning_ok(self, "Delete Failed", str(exc))
            return
        self._refresh()

    def _set_reset_password(self):
        current = self._selected_profile_name()
        if not current:
            _warning_ok(
                self,
                "No Profile Selected",
                "Please select a profile to set or reset its password.",
            )
            return
        dlg = SetPasswordDialog(
            profile_name=current,
            profile_store=self._store,
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            self._refresh()


class SetPasswordDialog(QDialog):
    """Set or reset password for a profile (used when logged in via Profile Manager)."""

    def __init__(
        self,
        profile_name: str,
        profile_store: ProfileStore,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Set/Reset Password — {profile_name}")
        self._profile_name = profile_name
        self._store = profile_store
        layout = QFormLayout(self)
        layout.addRow(
            QLabel("Current password (leave blank if none):")
        )
        self._current = QLineEdit()
        self._current.setEchoMode(QLineEdit.EchoMode.Password)
        self._current.setPlaceholderText("Leave blank to set initial password")
        layout.addRow(self._current)
        layout.addRow(QLabel("New password:"))
        self._new_pw = QLineEdit()
        self._new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow(self._new_pw)
        layout.addRow(QLabel("Confirm new password (leave both blank to clear):"))
        self._confirm = QLineEdit()
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow(self._confirm)
        btns = QHBoxLayout()
        ok = QPushButton("Set Password")
        ok.clicked.connect(self._apply)
        ok.setDefault(True)
        btns.addWidget(ok)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        layout.addRow(btns)

    def _apply(self):
        if self._store.profile_has_password(self._profile_name):
            if not self._store.verify_profile_password(
                self._profile_name, self._current.text()
            ):
                _warning_ok(
                    self,
                    "Invalid Password",
                    "Current password is incorrect.",
                )
                return
        new_pw = self._new_pw.text()
        if new_pw != self._confirm.text():
            _warning_ok(
                self,
                "Mismatch",
                "New password and confirmation do not match.",
            )
            return
        try:
            self._store.set_profile_password(self._profile_name, new_pw)
        except ValueError as exc:
            _warning_ok(self, "Error", str(exc))
            return
        msg = "Password cleared." if not new_pw else "Password has been updated successfully."
        _info_ok(self, "Password Set", msg)
        self.accept()


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
        self.setViewport(QWidget())
        self.setBackgroundBrush(QBrush(Qt.GlobalColor.white))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
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
    cursor_measurement_captured = Signal(object)
    image_captured = Signal(object)  # QPixmap

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hertz & Hearts \u2014 ECG Monitor")
        self.setMinimumSize(600, 300)
        self.resize(900, 350)

        self._settings = Settings()
        self._display_sec = self._settings.ECG_DISPLAY_SECONDS
        self._default_view_sec = 10.0
        self._view_sec = float(self._default_view_sec)
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
        self._cursor_active = "A"
        self._cursor_suppress_events = False
        self._cursor_a_line = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=True,
            pen=pg.mkPen((30, 30, 180, 220), width=1.5),
            label="A",
            labelOpts={"position": 0.9, "color": (30, 30, 180), "fill": (255, 255, 255, 160)},
        )
        self._cursor_b_line = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=True,
            pen=pg.mkPen((180, 30, 30, 220), width=1.5),
            label="B",
            labelOpts={"position": 0.9, "color": (180, 30, 30), "fill": (255, 255, 255, 160)},
        )
        self._cursor_a_line.setVisible(False)
        self._cursor_b_line.setVisible(False)
        self._plot_widget.addItem(self._cursor_a_line)
        self._plot_widget.addItem(self._cursor_b_line)
        self._cursor_a_line.sigPositionChanged.connect(lambda _line: self._on_cursor_line_changed("A"))
        self._cursor_b_line.sigPositionChanged.connect(lambda _line: self._on_cursor_line_changed("B"))
        self._cursor_a_line.sigPositionChangeFinished.connect(
            lambda _line: self._on_cursor_line_change_finished("A")
        )
        self._cursor_b_line.sigPositionChangeFinished.connect(
            lambda _line: self._on_cursor_line_change_finished("B")
        )
        self._cursor_delta_line = pg.PlotCurveItem(
            pen=pg.mkPen((65, 105, 225, 210), width=1.6)
        )
        self._cursor_delta_line.setVisible(False)
        self._plot_widget.addItem(self._cursor_delta_line)
        self._cursor_arrow_a = pg.ArrowItem(
            angle=0,
            headLen=10,
            tipAngle=30,
            baseAngle=20,
            brush=pg.mkBrush(65, 105, 225, 210),
            pen=pg.mkPen((65, 105, 225, 210), width=1),
        )
        self._cursor_arrow_b = pg.ArrowItem(
            angle=180,
            headLen=10,
            tipAngle=30,
            baseAngle=20,
            brush=pg.mkBrush(65, 105, 225, 210),
            pen=pg.mkPen((65, 105, 225, 210), width=1),
        )
        self._cursor_arrow_a.setVisible(False)
        self._cursor_arrow_b.setVisible(False)
        self._plot_widget.addItem(self._cursor_arrow_a)
        self._plot_widget.addItem(self._cursor_arrow_b)
        self._cursor_delta_text = pg.TextItem(
            html='<span style="color:#4169e1; font-size:10pt;"><b>Δt</b></span>',
            anchor=(0, 0.5),  # left edge at pos, vertically centered (beside arrow)
        )
        self._cursor_delta_text.setVisible(False)
        self._plot_widget.addItem(self._cursor_delta_text)

        self._frozen = False
        self._pre_freeze_view_sec: float | None = None
        self._pre_freeze_follow_main: bool = True
        self._timeline_offset_sec = 0.0
        self._synced_xrange: tuple[float, float] | None = None
        self._follow_main_xrange = True
        self._last_x_range: tuple[float, float] | None = None
        self._last_y_range: tuple[float, float] | None = None
        self._suppress_manual_range_signal = False
        self._pinned = False

        self._zoom_out_button = QPushButton("\u2212")
        self._zoom_out_button.setFixedWidth(28)
        self._zoom_out_button.setToolTip("Zoom Out (show more time)")
        self._zoom_out_button.clicked.connect(self._zoom_out)

        self._zoom_in_button = QPushButton("+")
        self._zoom_in_button.setFixedWidth(28)
        self._zoom_in_button.setToolTip("Zoom In (show less time)")
        self._zoom_in_button.clicked.connect(self._zoom_in)
        self._zoom_reset_button = QPushButton("Reset")
        self._zoom_reset_button.setFixedWidth(56)
        self._zoom_reset_button.setToolTip("Reset manual zoom to current display window.")
        self._zoom_reset_button.clicked.connect(self._reset_zoom)

        self._freeze_button = QPushButton("Freeze")
        self._freeze_button.setFixedWidth(80)
        self._freeze_button.setToolTip("Freeze ECG stream (enables cursor measurement tools).")
        self._freeze_button.clicked.connect(self._toggle_freeze)
        self._pin_button = QPushButton("\U0001F4CC")
        self._pin_button.setCheckable(True)
        self._pin_button.setFixedWidth(30)
        self._pin_button.setFont(QFont("Segoe UI Emoji", 11))
        self._pin_button.setFlat(True)
        self._pin_button.setStyleSheet("font-size: 13px; border: none; padding: 0 2px;")
        self._pin_button.toggled.connect(self._set_pinned)
        self._update_pin_button_visual()
        self._relock_button = QPushButton("Relock")
        self._relock_button.setFixedWidth(64)
        self._relock_button.setToolTip("Relock this chart to the main plot time range.")
        self._relock_button.clicked.connect(self._relock_to_main_xrange)
        self._relock_button.setEnabled(False)

        self._controls_bar = QWidget()
        controls_row = QHBoxLayout(self._controls_bar)
        controls_row.setContentsMargins(6, 2, 6, 2)
        controls_row.setSpacing(6)
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("font-size: 11px;")
        self._cursor_label = QLabel("Cursors:")
        self._cursor_label.setStyleSheet("font-size: 11px; color: #8a8a8a;")
        self._cursor_a_select_button = QPushButton("A")
        self._cursor_a_select_button.setCheckable(True)
        self._cursor_a_select_button.setFixedWidth(28)
        self._cursor_a_select_button.setToolTip(
            "Select cursor A for keyboard nudge.\nShortcut: press A."
        )
        self._cursor_a_select_button.toggled.connect(lambda checked: self._select_active_cursor("A", checked))
        self._cursor_b_select_button = QPushButton("B")
        self._cursor_b_select_button.setCheckable(True)
        self._cursor_b_select_button.setFixedWidth(28)
        self._cursor_b_select_button.setToolTip(
            "Select cursor B for keyboard nudge.\nShortcut: press B."
        )
        self._cursor_b_select_button.toggled.connect(lambda checked: self._select_active_cursor("B", checked))
        self._cursor_interval_type_combo = QComboBox()
        self._cursor_interval_type_combo.addItems(["R-R", "QRS", "QT", "PR", "Other"])
        self._cursor_interval_type_combo.setMinimumWidth(54)
        self._cursor_interval_type_combo.setMaximumWidth(58)
        self._cursor_interval_type_combo.setToolTip("Context for the logged interval (what Δt represents).")
        self._cursor_capture_button = QPushButton("Log Δt")
        self._cursor_capture_button.setFixedWidth(62)
        self._cursor_capture_button.setToolTip("Log cursor interval as session annotation with selected context.")
        self._cursor_capture_button.clicked.connect(self._capture_cursor_measurement)
        self._capture_image_button = QPushButton("Capture Image")
        self._capture_image_button.setFixedWidth(100)
        self._capture_image_button.setToolTip("Save a snapshot of the plot (axes, cursors, Δt) to the session folder.")
        self._capture_image_button.clicked.connect(self._capture_plot_image)
        controls_row.addWidget(zoom_label)
        controls_row.addWidget(self._zoom_out_button)
        controls_row.addWidget(self._zoom_in_button)
        controls_row.addWidget(self._zoom_reset_button)
        controls_row.addStretch(1)
        controls_row.addWidget(self._cursor_label)
        controls_row.addWidget(self._cursor_a_select_button)
        controls_row.addWidget(self._cursor_b_select_button)
        controls_row.addWidget(self._cursor_interval_type_combo)
        controls_row.addWidget(self._cursor_capture_button)
        controls_row.addWidget(self._capture_image_button)
        controls_row.addStretch(1)
        controls_row.addWidget(self._relock_button)
        controls_row.addWidget(self._freeze_button)
        controls_row.addWidget(self._pin_button)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Waiting for ECG data...")
        self._set_active_cursor_visuals()
        self._set_cursor_controls_enabled(False)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._plot_widget, 1)
        central_layout.addWidget(self._controls_bar)
        self.setCentralWidget(central)
        view_box = self._plot_widget.getViewBox()
        if hasattr(view_box, "sigRangeChangedManually"):
            view_box.sigRangeChangedManually.connect(self._on_manual_range_changed)

        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(self._settings.ECG_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._redraw)

    def start(self):
        self._display_sec = self._settings.ECG_DISPLAY_SECONDS
        self._view_sec = min(self._max_view_sec, float(self._default_view_sec))
        self._follow_main_xrange = True
        self._relock_button.setEnabled(False)
        self._refresh_relock_tooltip()
        self._apply_interaction_mode()
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
        self._refresh_relock_tooltip()
        self._got_first_data = False
        self._frozen = False
        self._disable_cursors_for_streaming_view()
        self._freeze_button.setText("Freeze")
        self._apply_interaction_mode()
        self._last_x_range = None
        self._last_y_range = None
        self._curve.setData([], [])
        self._statusbar.showMessage("Waiting for ECG data...")

    def stop(self):
        self._refresh_timer.stop()
        self._frozen = False
        self._disable_cursors_for_streaming_view()
        self._freeze_button.setText("Freeze")
        self._apply_interaction_mode()
        self._statusbar.showMessage("ECG stopped.")

    def _toggle_freeze(self):
        self.set_stream_frozen(not self._frozen)

    def _update_pin_button_visual(self):
        self._pin_button.setChecked(self._pinned)
        if self._pinned:
            self._pin_button.setStyleSheet(
                "font-size: 13px; border: 1px solid #1b6ec2; border-radius: 3px; "
                "padding: 0 2px; background: #e8f2ff;"
            )
        else:
            self._pin_button.setStyleSheet(
                "font-size: 13px; border: 1px solid transparent; border-radius: 3px; "
                "padding: 0 2px; background: transparent;"
            )

    def _set_pinned(self, pinned: bool):
        self._pinned = bool(pinned)
        self._update_pin_button_visual()
        was_visible = self.isVisible()
        was_minimized = self.isMinimized()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self._pinned)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowTitleHint, True)
        if was_visible:
            if was_minimized:
                self.showMinimized()
            else:
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def set_stream_frozen(self, frozen: bool):
        was_frozen = self._frozen
        self._frozen = bool(frozen)
        if self._frozen:
            if not was_frozen:
                self._pre_freeze_view_sec = float(self._view_sec)
                self._pre_freeze_follow_main = bool(self._follow_main_xrange)
            if self._follow_main_xrange:
                self._follow_main_xrange = False
                self._relock_button.setEnabled(True)
            self._freeze_button.setText("Resume")
            self._freeze_button.setToolTip("Resume ECG streaming and hide cursor tools.")
            self._apply_interaction_mode()
            self._auto_zoom_for_frozen_view()
            self._enable_cursors_for_frozen_view()
            self._refresh_relock_tooltip()
            self._statusbar.showMessage("ECG frozen \u2014 drag to pan, scroll wheel or +/\u2212 to zoom.")
        else:
            if was_frozen and self._pre_freeze_view_sec is not None:
                self._view_sec = float(self._pre_freeze_view_sec)
            # Resume should return to the live, relocked timeline behavior while
            # preserving the pre-freeze zoom span.
            self._follow_main_xrange = True
            self._relock_button.setEnabled(False)
            self._freeze_button.setText("Freeze")
            self._freeze_button.setToolTip("Freeze ECG stream (enables cursor measurement tools).")
            self._apply_interaction_mode()
            self._disable_cursors_for_streaming_view()
            if self._synced_xrange is not None:
                x_lo, x_hi = self._synced_xrange
                self._set_follow_main_xrange(float(x_lo), float(x_hi))
            self._refresh_relock_tooltip()
            self._statusbar.showMessage(
                "ECG streaming..." if self._got_first_data else "Waiting for ECG data..."
            )

    def _apply_interaction_mode(self):
        # Manual mode mirrors Poincare-style drag+wheel on X.
        manual_mode = not self._follow_main_xrange
        self._plot_widget.setMouseEnabled(x=manual_mode, y=False)

    def _set_cursor_controls_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self._cursor_label.setEnabled(enabled)
        self._cursor_label.setStyleSheet(
            "font-size: 11px; color: #2e2e2e;" if enabled else "font-size: 11px; color: #8a8a8a;"
        )
        self._cursor_a_select_button.setEnabled(enabled)
        self._cursor_b_select_button.setEnabled(enabled)
        self._cursor_interval_type_combo.setEnabled(enabled)
        self._cursor_capture_button.setEnabled(enabled)
        self._set_active_cursor_visuals()

    def _refresh_relock_tooltip(self):
        if self._frozen:
            self._relock_button.setToolTip(
                "Resume streaming and relock this chart to the main plot time range."
            )
        elif self._follow_main_xrange:
            self._relock_button.setToolTip("Chart is already locked to the main plot time range.")
        else:
            self._relock_button.setToolTip("Relock this chart to the main plot time range.")

    def _estimate_rr_seconds_from_trace(self) -> float | None:
        if len(self._times) < 12 or len(self._values) < 12:
            return None
        t_arr = np.asarray(self._times, dtype=float)
        y_arr = np.asarray(self._values, dtype=float)
        t_max = float(t_arr[-1])
        mask = t_arr >= (t_max - 12.0)
        idxs = np.where(mask)[0]
        if idxs.size < 12:
            return None
        dt = float(np.median(np.diff(t_arr[idxs]))) if idxs.size > 1 else (1.0 / ECG_SAMPLE_RATE)
        dt = max(dt, 1.0 / (3.0 * ECG_SAMPLE_RATE))
        baseline = float(np.median(y_arr[idxs]))
        z = np.abs(y_arr - baseline)
        thresh = float(np.percentile(z[idxs], 75))
        refractory = max(2, int(0.30 / dt))
        peaks: list[int] = []
        start = max(1, int(idxs[0]) + 1)
        end = min(len(z) - 2, int(idxs[-1]) - 1)
        for i in range(start, end + 1):
            if not (z[i] >= z[i - 1] and z[i] >= z[i + 1]):
                continue
            if z[i] < thresh:
                continue
            if peaks and (i - peaks[-1]) <= refractory:
                if z[i] > z[peaks[-1]]:
                    peaks[-1] = i
                continue
            peaks.append(i)
        if len(peaks) < 3:
            return None
        rr = np.diff(t_arr[peaks])
        rr = rr[(rr >= 0.35) & (rr <= 2.0)]
        if rr.size == 0:
            return None
        return float(np.median(rr))

    def _auto_zoom_for_frozen_view(self):
        bounds = self._cursor_time_bounds()
        if bounds is None:
            return
        rr_sec = self._estimate_rr_seconds_from_trace()
        target = 2.0 * rr_sec if rr_sec is not None else 2.4
        self._view_sec = max(0.8, min(self._max_view_sec, float(target)))
        t_hi = bounds[1]
        t_lo = max(bounds[0], t_hi - self._view_sec)
        self._set_xrange_if_needed(t_lo, t_hi)

    def _find_positive_peak_indices(
        self,
        x_lo: float,
        x_hi: float,
    ) -> list[tuple[int, float, float, float, float]]:
        if len(self._times) < 5 or len(self._values) < 5:
            return []
        t_arr = np.asarray(self._times, dtype=float)
        y_arr = np.asarray(self._values, dtype=float)
        mask = (t_arr >= x_lo) & (t_arr <= x_hi)
        idxs = np.where(mask)[0]
        if idxs.size < 5:
            return []
        i0 = max(1, int(idxs[0]) + 1)
        i1 = min(len(y_arr) - 2, int(idxs[-1]) - 1)
        if i1 <= i0:
            return []
        baseline = float(np.median(y_arr[idxs]))
        amp = y_arr - baseline
        min_amp = float(np.percentile(amp[idxs], 40))
        local_noise = float(np.std(y_arr[idxs])) + 1e-6
        out: list[tuple[int, float, float, float, float]] = []
        for i in range(i0, i1 + 1):
            if not (y_arr[i] >= y_arr[i - 1] and y_arr[i] >= y_arr[i + 1]):
                continue
            if amp[i] < min_amp:
                continue
            left_slope = float(y_arr[i] - y_arr[i - 1])
            right_slope = float(y_arr[i] - y_arr[i + 1])
            slope = max(left_slope, right_slope, 0.0)
            half = baseline + 0.5 * float(amp[i])
            width = 1
            j = i - 1
            while j >= i0 and y_arr[j] >= half:
                width += 1
                j -= 1
            j = i + 1
            while j <= i1 and y_arr[j] >= half:
                width += 1
                j += 1
            amp_z = float(amp[i]) / local_noise
            slope_z = slope / local_noise
            # Favor sharp/narrow positive peaks (R-like) over broad domes.
            score = (0.60 * amp_z) + (2.40 * slope_z) - (float(width) / 3.8)
            out.append((i, float(score), float(width), float(slope_z), float(amp_z)))
        return out

    def _suggest_cycle_cursor_positions(
        self,
        x_lo: float,
        x_hi: float,
        rr_sec: float | None,
    ) -> tuple[float, float] | None:
        peaks = self._find_positive_peak_indices(x_lo, x_hi)
        if len(peaks) < 2:
            return None
        t_arr = np.asarray(self._times, dtype=float)
        pairs: list[tuple[float, float, float]] = []
        for i in range(len(peaks) - 1):
            a_i, a_score, a_w, a_slope, _a_amp = peaks[i]
            b_i, b_score, b_w, b_slope, _b_amp = peaks[i + 1]
            dt = float(t_arr[b_i] - t_arr[a_i])
            if dt <= 0.0:
                continue
            if rr_sec is not None and not (0.55 * rr_sec <= dt <= 1.70 * rr_sec):
                continue
            pair_score = float(a_score + b_score)
            # Prefer pairs with similar morphology (corresponding peaks).
            pair_score -= 0.55 * abs(a_w - b_w)
            pair_score -= 0.25 * abs(a_slope - b_slope)
            if rr_sec is not None and rr_sec > 1e-6:
                pair_score -= 0.8 * abs(dt - rr_sec) / rr_sec
            # Prefer more recent pair while keeping morphology score dominant.
            pair_score += 0.04 * float(t_arr[b_i])
            pairs.append((pair_score, float(t_arr[a_i]), float(t_arr[b_i])))
        if not pairs:
            # Fallback: best-scored separated pair (no RR gating).
            min_sep = 0.25
            all_pairs: list[tuple[float, float, float]] = []
            for i in range(len(peaks) - 1):
                for j in range(i + 1, len(peaks)):
                    a_i, a_score, a_w, a_slope, _a_amp = peaks[i]
                    b_i, b_score, b_w, b_slope, _b_amp = peaks[j]
                    dt = float(t_arr[b_i] - t_arr[a_i])
                    if dt < min_sep:
                        continue
                    score = float(a_score + b_score)
                    score -= 0.55 * abs(a_w - b_w)
                    score -= 0.25 * abs(a_slope - b_slope)
                    score += 0.02 * float(t_arr[b_i])
                    all_pairs.append((score, float(t_arr[a_i]), float(t_arr[b_i])))
            if not all_pairs:
                return None
            _score, a_t, b_t = max(all_pairs, key=lambda x: x[0])
            return a_t, b_t
        _score, a_t, b_t = max(pairs, key=lambda x: x[0])
        return a_t, b_t

    def _snap_time_to_nearest_r_peak(self, t: float, x_lo: float, x_hi: float) -> float:
        """Snap time to nearest R-peak in view; return t unchanged if no peaks."""
        peaks = self._find_positive_peak_indices(x_lo, x_hi)
        if not peaks:
            return t
        t_arr = np.asarray(self._times, dtype=float)
        peak_times = np.array([float(t_arr[p[0]]) for p in peaks])
        idx = int(np.argmin(np.abs(peak_times - t)))
        return float(peak_times[idx])

    def _enable_cursors_for_frozen_view(self):
        if len(self._times) < 2:
            self._set_cursor_controls_enabled(False)
            self._cursor_a_line.setVisible(False)
            self._cursor_b_line.setVisible(False)
            return
        self._set_cursor_controls_enabled(True)
        x_rng = self._plot_widget.viewRange()[0]
        x_lo, x_hi = float(x_rng[0]), float(x_rng[1])
        rr_sec = self._estimate_rr_seconds_from_trace()
        suggested = self._suggest_cycle_cursor_positions(x_lo, x_hi, rr_sec=rr_sec)
        if suggested is None:
            span = max(0.2, x_hi - x_lo)
            a_pos = x_lo + 0.33 * span
            b_pos = x_lo + 0.66 * span
            a_pos = self._snap_time_to_nearest_r_peak(a_pos, x_lo, x_hi)
            b_pos = self._snap_time_to_nearest_r_peak(b_pos, x_lo, x_hi)
            if abs(b_pos - a_pos) < 0.05:
                peaks = self._find_positive_peak_indices(x_lo, x_hi)
                if len(peaks) >= 2:
                    t_arr = np.asarray(self._times, dtype=float)
                    a_pos = float(t_arr[peaks[0][0]])
                    b_pos = float(t_arr[peaks[1][0]])
        else:
            a_pos, b_pos = suggested
        self._cursor_suppress_events = True
        self._cursor_a_line.setPos(a_pos)
        self._cursor_b_line.setPos(b_pos)
        self._cursor_suppress_events = False
        self._cursor_a_line.setVisible(True)
        self._cursor_b_line.setVisible(True)
        self._cursor_active = "A"
        self._set_active_cursor_visuals()
        self._update_cursor_readout()

    def _disable_cursors_for_streaming_view(self):
        self._set_cursor_controls_enabled(False)
        self._cursor_a_line.setVisible(False)
        self._cursor_b_line.setVisible(False)
        self._cursor_delta_line.setVisible(False)
        self._cursor_arrow_a.setVisible(False)
        self._cursor_arrow_b.setVisible(False)
        self._cursor_delta_text.setVisible(False)

    def _cursor_time_bounds(self) -> tuple[float, float] | None:
        if len(self._times) < 2:
            return None
        return float(self._times[0]), float(self._times[-1])

    def _on_cursor_line_changed(self, cursor_id: str):
        if self._cursor_suppress_events:
            return
        self._cursor_active = cursor_id
        self._set_active_cursor_visuals()
        self._update_cursor_readout()

    def _on_cursor_line_change_finished(self, cursor_id: str):
        if self._cursor_suppress_events:
            return
        self._cursor_active = cursor_id
        self._set_active_cursor_visuals()
        self._update_cursor_readout()

    def _update_cursor_readout(self):
        if not (self._frozen and self._cursor_a_line.isVisible() and self._cursor_b_line.isVisible()):
            self._cursor_delta_line.setVisible(False)
            self._cursor_arrow_a.setVisible(False)
            self._cursor_arrow_b.setVisible(False)
            self._cursor_delta_text.setVisible(False)
            return
        a_t = float(self._cursor_a_line.value())
        b_t = float(self._cursor_b_line.value())
        dt_ms = abs(b_t - a_t) * 1000.0
        y_rng = self._plot_widget.viewRange()[1]
        y_lo, y_hi = float(y_rng[0]), float(y_rng[1])
        y_span = max(0.1, y_hi - y_lo)
        y_line = y_lo + 0.10 * y_span
        x0 = min(a_t, b_t)
        x1 = max(a_t, b_t)
        self._cursor_delta_line.setData([x0, x1], [y_line, y_line])
        self._cursor_delta_line.setVisible(True)
        self._cursor_arrow_a.setStyle(angle=0)
        self._cursor_arrow_b.setStyle(angle=180)
        self._cursor_arrow_a.setPos(x0, y_line)
        self._cursor_arrow_b.setPos(x1, y_line)
        self._cursor_arrow_a.setVisible(True)
        self._cursor_arrow_b.setVisible(True)
        view_box = self._plot_widget.getViewBox()
        _px_x, px_y = view_box.viewPixelSize()
        x_mid = (x0 + x1) * 0.5
        text_height_px = 18.0
        margin = max(0.02 * y_span, 4.0 * float(px_y))
        # Sample waveform in cursor span to detect overlap at top vs bottom.
        top_crowded = bottom_crowded = False
        min_y_in_range = y_lo
        max_y_in_range = y_hi
        if len(self._times) >= 2 and len(self._values) >= 2:
            t_arr = np.array(self._times)
            v_arr = np.array(self._values)
            in_range = (t_arr >= x0) & (t_arr <= x1)
            if np.any(in_range):
                min_y_in_range = float(np.min(v_arr[in_range]))
                max_y_in_range = float(np.max(v_arr[in_range]))
                top_band = y_hi - text_height_px * float(px_y)
                bottom_band = y_lo + text_height_px * float(px_y)
                top_crowded = max_y_in_range >= top_band
                bottom_crowded = min_y_in_range <= bottom_band
        # Place at very top or very bottom, whichever has no overlap (or more room).
        # Use anchors so text stays INSIDE the view (avoids clipping):
        # - Bottom: anchor (0.5, 1.0) = bottom of text at pos, text extends upward
        # - Top: anchor (0.5, 0) = top of text at pos, text extends downward
        if top_crowded and not bottom_crowded:
            y_text = y_lo + margin
            self._cursor_delta_text.setAnchor((0.5, 1.0))  # bottom at pos, grows up
        elif bottom_crowded and not top_crowded:
            y_text = y_hi - margin
            self._cursor_delta_text.setAnchor((0.5, 0))  # top at pos, grows down
        elif top_crowded and bottom_crowded:
            # Both crowded: pick side with more clearance.
            if (min_y_in_range - y_lo) >= (y_hi - max_y_in_range):
                y_text = y_lo + margin
                self._cursor_delta_text.setAnchor((0.5, 1.0))
            else:
                y_text = y_hi - margin
                self._cursor_delta_text.setAnchor((0.5, 0))
        else:
            y_text = y_lo + margin
            self._cursor_delta_text.setAnchor((0.5, 1.0))
        self._cursor_delta_text.setHtml(
            f'<span style="color:#4169e1; font-size:10pt;"><b>Δt {dt_ms:.1f} ms</b></span>'
        )
        self._cursor_delta_text.setPos(x_mid, y_text)
        self._cursor_delta_text.setVisible(True)

    def _capture_cursor_measurement(self):
        if not (self._frozen and self._cursor_a_line.isVisible() and self._cursor_b_line.isVisible()):
            return
        a_t = float(self._cursor_a_line.value())
        b_t = float(self._cursor_b_line.value())
        dt_ms = abs(b_t - a_t) * 1000.0
        interval_type = self._cursor_interval_type_combo.currentText().strip() or "R-R"
        payload = {
            "a_t_sec": a_t,
            "b_t_sec": b_t,
            "dt_ms": dt_ms,
            "interval_type": interval_type,
        }
        self.cursor_measurement_captured.emit(payload)
        self._statusbar.showMessage(f"Logged ECG cursor interval: Δt={dt_ms:.1f} ms ({interval_type})")

    def _capture_plot_image(self):
        """Grab plot widget (axes, waveform, cursors, Δt) and emit for saving to session folder."""
        pixmap = self._plot_widget.grab()
        if pixmap.isNull():
            self._statusbar.showMessage("Image capture failed.")
            return
        self.image_captured.emit(pixmap)
        # Visual feedback: white flash overlay over plot for ~250ms
        central = self.centralWidget()
        if central is None:
            return
        overlay = QWidget(central)
        overlay.setGeometry(self._plot_widget.geometry())
        overlay.setStyleSheet("background-color: white;")
        overlay.raise_()
        overlay.show()
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(250)
        anim.setStartValue(0.9)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def cleanup():
            overlay.deleteLater()
            anim.deleteLater()

        anim.finished.connect(cleanup)
        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    def set_image_capture_enabled(self, enabled: bool) -> None:
        self._capture_image_button.setEnabled(enabled)

    def _set_active_cursor_visuals(self):
        self._cursor_suppress_events = True
        self._cursor_a_select_button.setChecked(self._cursor_active == "A")
        self._cursor_b_select_button.setChecked(self._cursor_active == "B")
        self._cursor_suppress_events = False
        if not self._cursor_a_select_button.isEnabled():
            disabled_style = "font-weight: normal; color: #8a8a8a;"
            self._cursor_a_select_button.setStyleSheet(disabled_style)
            self._cursor_b_select_button.setStyleSheet(disabled_style)
            return
        active_style = "font-weight: bold; border: 1px solid #1b6ec2; background: #e8f2ff;"
        idle_style = "font-weight: normal;"
        self._cursor_a_select_button.setStyleSheet(active_style if self._cursor_active == "A" else idle_style)
        self._cursor_b_select_button.setStyleSheet(active_style if self._cursor_active == "B" else idle_style)

    def _select_active_cursor(self, cursor_id: str, checked: bool):
        if self._cursor_suppress_events:
            return
        if not checked:
            # Keep one cursor selected at all times.
            self._set_active_cursor_visuals()
            return
        self._cursor_active = cursor_id
        self._set_active_cursor_visuals()

    def _zoom_in(self):
        if self._follow_main_xrange:
            # Base first manual zoom step on the currently visible span, not the
            # default ECG window span, to avoid abrupt jump-in behavior.
            current_range = self._plot_widget.viewRange()[0]
            current_span = float(current_range[1] - current_range[0])
            if current_span > 0:
                self._view_sec = min(self._max_view_sec, max(0.5, current_span))
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
            self._refresh_relock_tooltip()
            self._apply_interaction_mode()
        self._view_sec = max(0.5, self._view_sec / 1.4)
        self._refresh_frozen_view()

    def _zoom_out(self):
        if self._follow_main_xrange:
            current_range = self._plot_widget.viewRange()[0]
            current_span = float(current_range[1] - current_range[0])
            if current_span > 0:
                self._view_sec = min(self._max_view_sec, max(0.5, current_span))
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
            self._refresh_relock_tooltip()
            self._apply_interaction_mode()
        self._view_sec = min(self._max_view_sec, self._view_sec * 1.4)
        self._refresh_frozen_view()

    def _reset_zoom(self):
        self._view_sec = float(self._display_sec)
        if self._follow_main_xrange:
            self._relock_to_main_xrange()
        else:
            self._refresh_frozen_view()

    def _relock_to_main_xrange(self):
        if self._frozen:
            # Relock doubles as Resume for faster workflow.
            self.set_stream_frozen(False)
        self._follow_main_xrange = True
        self._relock_button.setEnabled(False)
        self._refresh_relock_tooltip()
        self._apply_interaction_mode()
        if self._synced_xrange is not None:
            x_lo, x_hi = self._synced_xrange
            self._set_follow_main_xrange(x_lo, x_hi)

    def _set_follow_main_xrange(self, x_lo: float, x_hi: float):
        # Keep ECG right edge aligned to the main plots while using ECG's own zoom span.
        target_hi = float(x_hi)
        min_lo = float(x_lo)
        target_lo = max(min_lo, target_hi - self._view_sec)
        self._set_xrange_if_needed(target_lo, target_hi)

    def _set_xrange_if_needed(self, x_lo: float, x_hi: float):
        target = (float(x_lo), float(x_hi))
        if self._last_x_range is not None:
            prev_lo, prev_hi = self._last_x_range
            if abs(prev_lo - target[0]) < 1e-6 and abs(prev_hi - target[1]) < 1e-6:
                return
        self._suppress_manual_range_signal = True
        self._plot_widget.setXRange(target[0], target[1], padding=0)
        self._suppress_manual_range_signal = False
        self._last_x_range = target
        self._update_cursor_readout()

    def _set_yrange_if_needed(self, y_lo: float, y_hi: float):
        target = (float(y_lo), float(y_hi))
        if self._last_y_range is not None:
            prev_lo, prev_hi = self._last_y_range
            if abs(prev_lo - target[0]) < 1e-6 and abs(prev_hi - target[1]) < 1e-6:
                return
        self._plot_widget.setYRange(target[0], target[1], padding=0)
        self._last_y_range = target
        self._update_cursor_readout()

    def _refresh_frozen_view(self):
        if len(self._times) < 2:
            return
        current_range = self._plot_widget.viewRange()[0]
        center = (current_range[0] + current_range[1]) / 2
        half = self._view_sec / 2
        t_min = float(self._times[0])
        t_max = float(self._times[-1])
        t_lo = max(t_min, center - half)
        t_hi = t_lo + self._view_sec
        if t_hi > t_max:
            t_hi = t_max
            t_lo = max(t_min, t_hi - self._view_sec)
        self._set_xrange_if_needed(t_lo, t_hi)

    def append_samples(self, samples: list):
        self._pending.extend(samples)
        max_pending = ECG_SAMPLE_RATE * 10
        while len(self._pending) > max_pending:
            self._pending.popleft()

    def keyPressEvent(self, event):
        if self._frozen and event.key() in (Qt.Key_A, Qt.Key_B):
            self._cursor_active = "A" if event.key() == Qt.Key_A else "B"
            self._set_active_cursor_visuals()
            event.accept()
            return
        if self._frozen and event.key() in (Qt.Key_Left, Qt.Key_Right):
            bounds = self._cursor_time_bounds()
            if bounds is not None and self._cursor_a_line.isVisible() and self._cursor_b_line.isVisible():
                step = 1.0 / float(ECG_SAMPLE_RATE)
                if event.modifiers() & Qt.ShiftModifier:
                    step *= 5.0
                delta = -step if event.key() == Qt.Key_Left else step
                line = self._cursor_a_line if self._cursor_active == "A" else self._cursor_b_line
                x_new = float(line.value()) + delta
                x_new = max(bounds[0], min(bounds[1], x_new))
                self._cursor_suppress_events = True
                line.setPos(x_new)
                self._cursor_suppress_events = False
                self._update_cursor_readout()
                event.accept()
                return
        super().keyPressEvent(event)

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
        if self._follow_main_xrange:
            self._set_follow_main_xrange(float(x_lo), float(x_hi))

    def _on_manual_range_changed(self, *_args):
        if self._suppress_manual_range_signal or self._follow_main_xrange:
            return
        x_rng = self._plot_widget.viewRange()[0]
        self._view_sec = max(0.5, min(self._max_view_sec, float(x_rng[1] - x_rng[0])))
        self._refresh_relock_tooltip()

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

        y_lo = float(min(self._values))
        y_hi = float(max(self._values))
        margin = max(0.1, (y_hi - y_lo) * 0.15)
        target_lo = y_lo - margin
        target_hi = y_hi + margin
        alpha = 0.15
        self._y_min_smooth += alpha * (target_lo - self._y_min_smooth)
        self._y_max_smooth += alpha * (target_hi - self._y_max_smooth)
        self._set_yrange_if_needed(self._y_min_smooth, self._y_max_smooth)

        t_max = float(self._times[-1])
        if self._follow_main_xrange and self._synced_xrange is not None:
            x_lo, x_hi = self._synced_xrange
            self._set_follow_main_xrange(x_lo, x_hi)
        else:
            x_hi = t_max + 2.0
            x_lo = x_hi - self._view_sec
            self._set_xrange_if_needed(x_lo, x_hi)

        self._curve.setData(self._times, self._values)

    def closeEvent(self, event):
        if self._pinned:
            self._pinned = False
            self._update_pin_button_visual()
        self.stop()
        self.closed.emit()
        super().closeEvent(event)


class QtcWindow(QMainWindow):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hertz & Hearts — QTc Monitor")
        self.setMinimumSize(760, 320)
        self.resize(1120, 380)

        self._plot_widget = pg.PlotWidget(background="w")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self._plot_widget.setLabel("left", "QTc (ms)", color="k")
        self._plot_widget.setLabel("bottom", "Seconds", color="k")
        self._plot_widget.getAxis("left").setTextPen("k")
        self._plot_widget.getAxis("bottom").setTextPen("k")
        self._plot_widget.getAxis("left").setPen(pg.mkPen("k"))
        self._plot_widget.getAxis("bottom").setPen(pg.mkPen("k"))
        self._plot_widget.getAxis("bottom").enableAutoSIPrefix(False)
        self._plot_widget.hideButtons()
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
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("font-size: 11px;")
        self._zoom_out_button = QPushButton("\u2212")
        self._zoom_out_button.setFixedWidth(28)
        self._zoom_out_button.setToolTip("Zoom Out (show more time)")
        self._zoom_out_button.clicked.connect(self._zoom_out)
        self._zoom_in_button = QPushButton("+")
        self._zoom_in_button.setFixedWidth(28)
        self._zoom_in_button.setToolTip("Zoom In (show less time)")
        self._zoom_in_button.clicked.connect(self._zoom_in)
        self._zoom_reset_button = QPushButton("Reset")
        self._zoom_reset_button.setFixedWidth(56)
        self._zoom_reset_button.setToolTip("Reset manual zoom to 60 seconds.")
        self._zoom_reset_button.clicked.connect(self._reset_zoom)
        self._relock_button = QPushButton("Relock")
        self._relock_button.setFixedWidth(64)
        self._relock_button.setToolTip("Relock this chart to the main plot time range.")
        self._relock_button.clicked.connect(self._relock_to_main_xrange)
        self._relock_button.setEnabled(False)
        self._pin_button = QPushButton("\U0001F4CC")
        self._pin_button.setCheckable(True)
        self._pin_button.setFixedWidth(24)
        self._pin_button.setToolTip("Pin/unpin this window on top.")
        self._pin_button.setFlat(True)
        self._pin_button.setStyleSheet("font-size: 14px; border: none; padding: 0 2px;")
        self._pin_button.toggled.connect(self._set_pinned)
        self._info_button = QPushButton("i")
        self._info_button.setFixedWidth(22)
        self._info_button.setToolTip("How to interpret QTc trend and uncertainty.")
        self._info_button.setStyleSheet("font-size: 11px; padding: 2px 4px;")
        self._info_button.clicked.connect(self._show_info)
        self._freeze_button = QPushButton("Freeze")
        self._freeze_button.setFixedWidth(74)
        self._freeze_button.clicked.connect(self._toggle_freeze)
        self._statusbar.addPermanentWidget(zoom_label)
        self._statusbar.addPermanentWidget(self._zoom_out_button)
        self._statusbar.addPermanentWidget(self._zoom_in_button)
        self._statusbar.addPermanentWidget(self._zoom_reset_button)
        self._statusbar.addPermanentWidget(self._relock_button)
        self._statusbar.addPermanentWidget(self._pin_button)
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
        self._follow_main_xrange = True
        self._view_sec = 60.0
        self._max_view_sec = float(self._history_sec)
        self._last_x_range: tuple[float, float] | None = None
        self._suppress_manual_range_signal = False
        self._pinned = False
        self._update_pin_button_visual()
        self._times = deque(maxlen=1200)
        self._medians = deque(maxlen=1200)
        self._p25 = deque(maxlen=1200)
        self._p75 = deque(maxlen=1200)
        self._lowq = deque(maxlen=1200)
        self._formula_label = "Formula: pending"
        self._formula_reason_label = "Rationale: pending"
        view_box = self._plot_widget.getViewBox()
        if hasattr(view_box, "sigRangeChangedManually"):
            view_box.sigRangeChangedManually.connect(self._on_manual_range_changed)

    @staticmethod
    def _format_formula_label(payload: dict) -> str:
        formula_used = payload.get("formula_used")
        formula_default = payload.get("formula_default")
        if isinstance(formula_used, str) and formula_used.strip():
            used = formula_used.strip().lower()
            if used == "mixed":
                return "Formula: adaptive (Bazett/Fridericia)"
            return f"Formula: {used.capitalize()}"
        if isinstance(formula_default, str) and formula_default.strip():
            default = formula_default.strip().lower()
            return f"Formula: {default.capitalize()} (default)"
        return "Formula: unknown"

    @staticmethod
    def _format_formula_reason_label(payload: dict) -> str:
        suggestion = payload.get("method_suggestion")
        if isinstance(suggestion, dict):
            reasoning = suggestion.get("reasoning")
            if isinstance(reasoning, str):
                cleaned = " ".join(reasoning.strip().split())
                if cleaned:
                    # Keep status text concise while preserving the rationale.
                    first_sentence = cleaned.split(". ")[0].rstrip(".")
                    if first_sentence:
                        return f"Rationale: {first_sentence}."
        return "Rationale: insufficient data."

    def _show_info(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("QTc Trend Guide")
        msg.setText(
            "<b>How to read this chart</b><br><br>"
            "• <b>Rolling median QTc</b>: smoothed central QTc estimate.<br>"
            "• <b>Uncertainty band (IQR)</b>: wider band means less confidence.<br>"
            "• <b>Dashed segments</b>: lower signal quality periods.<br>"
            "• <b>Shaded area above 470 ms</b>: elevated reference zone.<br><br>"
            f"<b>Measurement uncertainty</b>: QTc from single-lead ECG may vary by approximately ±{ECG_QTc_UNCERTAINTY_PCT}% from reference."
        )
        msg.setInformativeText("Trend context only; requires clinical review.")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setDefaultButton(QMessageBox.Ok)
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
        self._follow_main_xrange = True
        self._view_sec = 60.0
        self._last_x_range = None
        self._relock_button.setEnabled(False)
        self._apply_interaction_mode()
        self._median_curve.setData([], [])
        self._low_quality_curve.setData([], [])
        self._upper_curve.setData([], [])
        self._lower_curve.setData([], [])
        self._statusbar.showMessage("Waiting for QTc trend points...")

    def start(self):
        self._frozen = False
        self._freeze_button.setText("Freeze QTc")
        self._follow_main_xrange = True
        self._relock_button.setEnabled(False)
        self._apply_interaction_mode()

    def stop(self):
        self._frozen = False
        self._freeze_button.setText("Freeze QTc")
        self._apply_interaction_mode()

    def _toggle_freeze(self):
        self.set_stream_frozen(not self._frozen)

    def _update_pin_button_visual(self):
        self._pin_button.setChecked(self._pinned)
        if self._pinned:
            self._pin_button.setStyleSheet(
                "font-size: 14px; border: 1px solid #1b6ec2; border-radius: 3px; "
                "padding: 0 2px; background: #e8f2ff;"
            )
        else:
            self._pin_button.setStyleSheet(
                "font-size: 14px; border: 1px solid transparent; border-radius: 3px; "
                "padding: 0 2px; background: transparent;"
            )

    def _set_pinned(self, pinned: bool):
        self._pinned = bool(pinned)
        self._update_pin_button_visual()
        was_visible = self.isVisible()
        was_minimized = self.isMinimized()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self._pinned)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowTitleHint, True)
        if was_visible:
            if was_minimized:
                self.showMinimized()
            else:
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def set_stream_frozen(self, frozen: bool):
        self._frozen = bool(frozen)
        if self._frozen and self._follow_main_xrange:
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
        self._freeze_button.setText("Resume" if self._frozen else "Freeze")
        self._apply_interaction_mode()
        if self._frozen:
            self._statusbar.showMessage("QTc view frozen.")
        else:
            self._statusbar.showMessage("QTc streaming.")
            self._redraw()

    def _apply_interaction_mode(self):
        manual_mode = not self._follow_main_xrange
        self._plot_widget.setMouseEnabled(x=manual_mode, y=False)

    def _set_xrange_if_needed(self, x_lo: float, x_hi: float):
        target = (float(x_lo), float(x_hi))
        if self._last_x_range is not None:
            prev_lo, prev_hi = self._last_x_range
            if abs(prev_lo - target[0]) < 1e-6 and abs(prev_hi - target[1]) < 1e-6:
                return
        self._suppress_manual_range_signal = True
        self._plot_widget.setXRange(target[0], target[1], padding=0)
        self._suppress_manual_range_signal = False
        self._last_x_range = target

    def _zoom_in(self):
        if self._follow_main_xrange:
            current_range = self._plot_widget.viewRange()[0]
            current_span = float(current_range[1] - current_range[0])
            if current_span > 0:
                self._view_sec = min(self._max_view_sec, max(2.0, current_span))
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
            self._apply_interaction_mode()
        self._view_sec = max(2.0, self._view_sec / 1.4)
        self._refresh_manual_view()

    def _zoom_out(self):
        if self._follow_main_xrange:
            current_range = self._plot_widget.viewRange()[0]
            current_span = float(current_range[1] - current_range[0])
            if current_span > 0:
                self._view_sec = min(self._max_view_sec, max(2.0, current_span))
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
            self._apply_interaction_mode()
        self._view_sec = min(self._max_view_sec, self._view_sec * 1.4)
        self._refresh_manual_view()

    def _reset_zoom(self):
        self._view_sec = 60.0
        if self._follow_main_xrange:
            self._relock_to_main_xrange()
        else:
            self._refresh_manual_view()

    def _relock_to_main_xrange(self):
        self._follow_main_xrange = True
        self._relock_button.setEnabled(False)
        self._apply_interaction_mode()
        if self._synced_xrange is not None:
            x_lo, x_hi = self._synced_xrange
            self._set_xrange_if_needed(x_lo, x_hi)

    def _refresh_manual_view(self):
        if len(self._times) < 1:
            return
        current_range = self._plot_widget.viewRange()[0]
        center = (current_range[0] + current_range[1]) / 2.0
        half = self._view_sec / 2.0
        t_min = float(self._times[0])
        t_max = float(self._times[-1]) + 2.0
        x_lo = max(t_min, center - half)
        x_hi = x_lo + self._view_sec
        if x_hi > t_max:
            x_hi = t_max
            x_lo = max(t_min, x_hi - self._view_sec)
        self._set_xrange_if_needed(x_lo, x_hi)
        self._threshold_label.setPos(x_hi - 1.0, 471)

    def _on_manual_range_changed(self, *_args):
        if self._suppress_manual_range_signal:
            return
        if self._follow_main_xrange:
            self._follow_main_xrange = False
            self._relock_button.setEnabled(True)
            self._apply_interaction_mode()
        x_rng = self._plot_widget.viewRange()[0]
        self._view_sec = max(2.0, min(self._max_view_sec, float(x_rng[1] - x_rng[0])))

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
        if self._follow_main_xrange and self._times:
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
        if self._follow_main_xrange:
            self._set_xrange_if_needed(float(x_lo), float(x_hi))

    def append_payload(self, payload: dict):
        if not isinstance(payload, dict):
            return
        self._formula_label = self._format_formula_label(payload)
        self._formula_reason_label = self._format_formula_reason_label(payload)
        trend_point = payload.get("trend_point")
        if not isinstance(trend_point, dict):
            quality = payload.get("quality", {}) if isinstance(payload, dict) else {}
            reason = quality.get("reason") if isinstance(quality, dict) else None
            if isinstance(reason, str) and reason.strip():
                self._statusbar.showMessage(
                    f"QTc waiting: {reason}. {self._formula_label}. {self._formula_reason_label}"
                )
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
        if self._follow_main_xrange and self._synced_xrange is not None:
            x_lo, x_hi = self._synced_xrange
            self._set_xrange_if_needed(x_lo, x_hi)
            self._threshold_label.setPos(x_hi - 1.0, 471)
        else:
            auto_hi = x_hi + 2.0
            auto_lo = max(0.0, auto_hi - self._view_sec)
            self._set_xrange_if_needed(auto_lo, auto_hi)
            self._threshold_label.setPos(auto_hi - 1.0, 471)
        self._statusbar.showMessage(
            f"QTc streaming. {self._formula_label}. {self._formula_reason_label} "
            "For trend context only; clinical interpretation requires review."
        )

    def closeEvent(self, event):
        if self._pinned:
            self._pinned = False
            self._update_pin_button_visual()
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
        self._latest_auto_bounds: tuple[float, float] | None = None
        self._axis_hi_soft_cap_ms: float = 2500.0
        self._zoom_out_factor: float = 1.4
        self._zoom_in_factor: float = 1.0 / self._zoom_out_factor

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self._scale_button = QPushButton("Scale AUTO")
        self._scale_button.setToolTip("Toggle between auto-scaling and locked scale.")
        self._scale_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._scale_button.setMinimumWidth(110)
        self._scale_button.clicked.connect(self._toggle_scale_mode)
        header.addWidget(self._scale_button)
        self._zoom_out_button = QPushButton("-")
        self._zoom_out_button.setToolTip("Zoom out locked scale.")
        self._zoom_out_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._zoom_out_button.setFixedWidth(28)
        self._zoom_out_button.clicked.connect(
            lambda: self._adjust_locked_scale(self._zoom_out_factor)
        )
        header.addWidget(self._zoom_out_button)
        self._zoom_in_button = QPushButton("+")
        self._zoom_in_button.setToolTip("Zoom in locked scale.")
        self._zoom_in_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._zoom_in_button.setFixedWidth(28)
        self._zoom_in_button.clicked.connect(
            lambda: self._adjust_locked_scale(self._zoom_in_factor)
        )
        header.addWidget(self._zoom_in_button)
        self._zoom_reset_button = QPushButton("Reset")
        self._zoom_reset_button.setToolTip("Reset locked scale to current data bounds.")
        self._zoom_reset_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._zoom_reset_button.setMinimumWidth(52)
        self._zoom_reset_button.clicked.connect(self._reset_locked_scale)
        header.addWidget(self._zoom_reset_button)
        self._set_locked_zoom_controls_visible(False)
        header.addStretch()
        self._info_button = QPushButton("i")
        self._info_button.setFixedWidth(22)
        self._info_button.setToolTip("What is a Poincare plot?")
        self._info_button.setStyleSheet("font-size: 11px; padding: 2px 4px;")
        self._info_button.clicked.connect(self.info_requested.emit)
        header.addWidget(self._info_button)
        self._pin_button = QPushButton("\U0001F4CC")
        self._pin_button.setCheckable(True)
        self._pin_button.setToolTip("Pin/unpin this window on top.")
        self._pin_button.setStyleSheet("font-size: 14px; border: none; padding: 0 2px;")
        self._pin_button.setFixedWidth(24)
        self._pin_button.setFlat(True)
        self._pin_button.toggled.connect(self._set_pinned)
        header.addWidget(self._pin_button)
        layout.addLayout(header)

        self._plot = pg.PlotWidget(background="w")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("left", "RR(n+1) [ms]", color="k")
        self._plot.setLabel("bottom", "RR(n) [ms]", color="k")
        self._plot.getAxis("left").setTextPen("k")
        self._plot.getAxis("bottom").setTextPen("k")
        self._plot.getAxis("left").setPen(pg.mkPen("k"))
        self._plot.getAxis("bottom").setPen(pg.mkPen("k"))
        self._plot.setMouseEnabled(x=False, y=False)
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
        self._pinned = False
        self._update_pin_button_visual()

    def _update_pin_button_visual(self):
        self._pin_button.setChecked(self._pinned)
        if self._pinned:
            self._pin_button.setStyleSheet(
                "font-size: 14px; border: 1px solid #1b6ec2; border-radius: 3px; "
                "padding: 0 2px; background: #e8f2ff;"
            )
        else:
            self._pin_button.setStyleSheet(
                "font-size: 14px; border: 1px solid transparent; border-radius: 3px; "
                "padding: 0 2px; background: transparent;"
            )

    def _set_pinned(self, pinned: bool):
        self._pinned = bool(pinned)
        self._update_pin_button_visual()
        was_visible = self.isVisible()
        was_minimized = self.isMinimized()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self._pinned)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowTitleHint, True)
        if was_visible:
            if was_minimized:
                self.showMinimized()
            else:
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def _apply_square_bounds(self, lo: float, hi: float):
        lo, hi = self._sanitize_bounds(lo, hi)
        self._plot.setXRange(lo, hi, padding=0)
        self._plot.setYRange(lo, hi, padding=0)
        self._identity.setData([lo, hi], [lo, hi])

    def _sanitize_bounds(self, lo: float, hi: float) -> tuple[float, float]:
        # RR intervals are non-negative, so keep chart bounds non-negative too.
        lo = float(lo)
        hi = float(hi)
        if hi < lo:
            lo, hi = hi, lo
        lo = max(0.0, lo)
        cap_hi = self._current_hi_cap()
        hi = min(hi, cap_hi)
        if lo > (cap_hi - 10.0):
            lo = max(0.0, cap_hi - 10.0)
        hi = max(lo + 10.0, hi)
        return lo, hi

    def _current_hi_cap(self) -> float:
        if self._latest_auto_bounds is None:
            return self._axis_hi_soft_cap_ms
        # Keep zoom from drifting excessively wide while still allowing
        # higher ranges when data itself needs it.
        return max(self._axis_hi_soft_cap_ms, float(self._latest_auto_bounds[1]) + 200.0)

    def _bounds_from_current_view(self) -> tuple[float, float]:
        x_rng, y_rng = self._plot.viewRange()
        return self._sanitize_bounds(
            float(min(x_rng[0], y_rng[0])),
            float(max(x_rng[1], y_rng[1])),
        )

    def _set_locked_zoom_controls_visible(self, visible: bool):
        self._zoom_out_button.setVisible(visible)
        self._zoom_in_button.setVisible(visible)
        self._zoom_reset_button.setVisible(visible)

    def _apply_interaction_mode(self):
        # AUTO keeps scale system-controlled; LOCKED allows user-driven zoom/pan.
        if self._auto_scale:
            self._plot.setMouseEnabled(x=False, y=False)
        else:
            self._plot.setMouseEnabled(x=True, y=True)

    def _adjust_locked_scale(self, factor: float):
        if self._auto_scale:
            return
        if self._locked_bounds is None:
            self._locked_bounds = self._bounds_from_current_view()
        lo, hi = self._locked_bounds
        span = max(10.0, hi - lo) * float(factor)
        span = max(10.0, min(span, 5000.0))
        center = (lo + hi) / 2.0
        new_lo = center - (span / 2.0)
        new_hi = center + (span / 2.0)
        self._locked_bounds = self._sanitize_bounds(new_lo, new_hi)
        self._apply_square_bounds(new_lo, new_hi)

    def _reset_locked_scale(self):
        if self._auto_scale:
            return
        if self._latest_auto_bounds is not None:
            self._locked_bounds = self._sanitize_bounds(*self._latest_auto_bounds)
            self._apply_square_bounds(*self._locked_bounds)
            return
        self._locked_bounds = self._bounds_from_current_view()
        self._apply_square_bounds(*self._locked_bounds)

    def _toggle_scale_mode(self):
        self._auto_scale = not self._auto_scale
        if self._auto_scale:
            self._scale_button.setText("Scale AUTO")
            self._locked_bounds = None
            self._set_locked_zoom_controls_visible(False)
            self._apply_interaction_mode()
            self.statusBar().showMessage("Scale mode: AUTO")
            return
        self._scale_button.setText("Scale MANUAL")
        self._set_locked_zoom_controls_visible(True)
        self._apply_interaction_mode()
        lo, hi = self._bounds_from_current_view()
        if hi - lo < 10.0:
            center = (hi + lo) / 2.0
            lo = center - 5.0
            hi = center + 5.0
        self._locked_bounds = self._sanitize_bounds(lo, hi)
        self._apply_square_bounds(lo, hi)
        self.statusBar().showMessage("Scale mode: MANUAL")

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
        self._latest_auto_bounds = self._sanitize_bounds(lo, hi)
        if self._auto_scale:
            self._apply_square_bounds(lo, hi)
        else:
            if self._locked_bounds is None:
                self._locked_bounds = self._sanitize_bounds(lo, hi)
            else:
                # Preserve manual zoom/pan actions (e.g., mouse wheel) in locked mode.
                current_bounds = self._bounds_from_current_view()
                if current_bounds != self._locked_bounds:
                    self._locked_bounds = current_bounds
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
        mode = "AUTO" if self._auto_scale else "MANUAL"
        self.statusBar().showMessage(f"Showing last {rr.size} beats | Scale: {mode}")

    def closeEvent(self, event):
        if self._pinned:
            self._pinned = False
            self._update_pin_button_visual()
        self.closed.emit()
        super().closeEvent(event)


class PSDWindow(QMainWindow):
    closed = Signal()
    info_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hertz & Hearts — PSD (Vagal Resonance)")
        self.setMinimumSize(560, 420)
        self.resize(800, 500)
        self._vagal_lo, self._vagal_hi = PSD_VAGAL_BAND
        self._default_x_range = (0.0, 0.5)
        self._zoom_factor = 1.4

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self._zoom_out_button = QPushButton("\u2212")
        self._zoom_out_button.setToolTip("Zoom out (show wider frequency range).")
        self._zoom_out_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._zoom_out_button.setFixedWidth(28)
        self._zoom_out_button.clicked.connect(self._zoom_out)
        header.addWidget(self._zoom_out_button)
        self._zoom_in_button = QPushButton("+")
        self._zoom_in_button.setToolTip("Zoom in (narrower frequency range).")
        self._zoom_in_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._zoom_in_button.setFixedWidth(28)
        self._zoom_in_button.clicked.connect(self._zoom_in)
        header.addWidget(self._zoom_in_button)
        self._zoom_reset_button = QPushButton("Reset")
        self._zoom_reset_button.setToolTip("Reset view to default 0–0.5 Hz range.")
        self._zoom_reset_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._zoom_reset_button.setMinimumWidth(52)
        self._zoom_reset_button.clicked.connect(self._reset_zoom)
        header.addWidget(self._zoom_reset_button)
        header.addStretch()
        self._info_button = QPushButton("i")
        self._info_button.setFixedWidth(22)
        self._info_button.setToolTip("What is Vagal Resonance and this PSD plot?")
        self._info_button.setStyleSheet("font-size: 11px; padding: 2px 4px;")
        self._info_button.clicked.connect(self.info_requested.emit)
        header.addWidget(self._info_button)
        self._pin_button = QPushButton("\U0001F4CC")
        self._pin_button.setCheckable(True)
        self._pin_button.setToolTip("Pin/unpin this window on top.")
        self._pin_button.setStyleSheet("font-size: 14px; border: none; padding: 0 2px;")
        self._pin_button.setFixedWidth(24)
        self._pin_button.setFlat(True)
        self._pin_button.toggled.connect(self._set_pinned)
        header.addWidget(self._pin_button)
        layout.addLayout(header)

        self._plot = pg.PlotWidget(background="w")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("left", "Power (ms²/Hz)", color="k")
        self._plot.setLabel("bottom", "Frequency (Hz)", color="k")
        self._plot.getAxis("bottom").enableAutoSIPrefix(False)
        self._plot.getAxis("left").setTextPen("k")
        self._plot.getAxis("bottom").setTextPen("k")
        self._plot.getAxis("left").setPen(pg.mkPen("k"))
        self._plot.getAxis("bottom").setPen(pg.mkPen("k"))
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.hideButtons()
        self._plot.setXRange(*self._default_x_range, padding=0)

        self._vagal_region = pg.LinearRegionItem(
            values=(self._vagal_lo, self._vagal_hi),
            orientation=pg.LinearRegionItem.Vertical,
            movable=False,
            brush=(70, 130, 210, 48),
            pen=pg.mkPen((30, 78, 153, 120), width=1),
        )
        self._plot.addItem(self._vagal_region)
        self._psd_curve = self._plot.plot(
            pen=pg.mkPen((25, 118, 210), width=2),
        )
        layout.addWidget(self._plot, stretch=1)

        metrics_row = QHBoxLayout()
        self._peak_label = QLabel("0.1 Hz peak: --")
        self._peak_label.setStyleSheet(
            "font-size: 11px; color: #2c3e50; "
            "border: 1px solid #bdc3c7; border-radius: 3px; "
            "padding: 2px 8px; background: #f8f9fa;"
        )
        metrics_row.addWidget(self._peak_label)
        metrics_row.addStretch()
        layout.addLayout(metrics_row)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Waiting for R-R data...")
        self._pinned = False
        self._update_pin_button_visual()

    def _update_pin_button_visual(self):
        self._pin_button.setChecked(self._pinned)
        if self._pinned:
            self._pin_button.setStyleSheet(
                "font-size: 14px; border: 1px solid #1b6ec2; border-radius: 3px; "
                "padding: 0 2px;"
            )
        else:
            self._pin_button.setStyleSheet("font-size: 14px; border: none; padding: 0 2px;")

    def _set_pinned(self, checked: bool):
        self._pinned = bool(checked)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self._pinned)
        self.show()
        self._update_pin_button_visual()

    def _zoom_in(self):
        vb = self._plot.getViewBox()
        if vb is None:
            return
        rng = vb.viewRange()
        x_lo, x_hi = rng[0][0], rng[0][1]
        center = (x_lo + x_hi) / 2.0
        span = (x_hi - x_lo) / self._zoom_factor
        span = max(0.01, min(span, self._default_x_range[1] - self._default_x_range[0]))
        nlo = center - span / 2
        nhi = center + span / 2
        nlo = max(self._default_x_range[0], min(nlo, self._default_x_range[1] - span))
        nhi = nlo + span
        vb.setXRange(nlo, nhi, padding=0)

    def _zoom_out(self):
        vb = self._plot.getViewBox()
        if vb is None:
            return
        rng = vb.viewRange()
        x_lo, x_hi = rng[0][0], rng[0][1]
        center = (x_lo + x_hi) / 2.0
        span = (x_hi - x_lo) * self._zoom_factor
        span = min(span, self._default_x_range[1] - self._default_x_range[0])
        nlo = center - span / 2
        nhi = center + span / 2
        nlo = max(self._default_x_range[0], nlo)
        nhi = min(self._default_x_range[1], nhi)
        vb.setXRange(nlo, nhi, padding=0)

    def _reset_zoom(self):
        self._plot.setXRange(*self._default_x_range, padding=0)
        self.statusBar().showMessage("View reset to 0–0.5 Hz.")

    def clear(self):
        self._psd_curve.setData([], [])
        self._peak_label.setText("0.1 Hz peak: --")
        self.statusBar().showMessage("Waiting for R-R data...")

    def update_from_psd(self, freqs: list[float], psd: list[float]):
        if not freqs or not psd or len(freqs) != len(psd):
            self.clear()
            return
        f = np.asarray(freqs)
        p = np.asarray(psd)
        self._psd_curve.setData(f, p)
        vagal_mask = (f >= self._vagal_lo) & (f <= self._vagal_hi)
        if np.any(vagal_mask):
            peak_power = float(np.max(p[vagal_mask]))
            peak_idx = int(np.argmax(p[vagal_mask]))
            peak_freq = float(f[vagal_mask][peak_idx])
            self._peak_label.setText(
                f"0.1 Hz band peak: {peak_power:.4f} @ {peak_freq:.3f} Hz"
            )
        else:
            self._peak_label.setText("0.1 Hz band: no data in range")
        self.statusBar().showMessage(
            "Drag to pan, scroll or +/- to zoom. Shaded band = Vagal Resonance (0.07–0.13 Hz)."
        )

    def closeEvent(self, event):
        if self._pinned:
            self._pinned = False
            self._update_pin_button_visual()
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
        self._cached_frame_inset: QMargins | None = None

        # 1. TRACKERS & STATE
        self.settings = Settings()
        self.model = model
        self.baseline_values = []
        self.baseline_rmssd = None
        self.baseline_hr_values = []
        self.baseline_hr = None
        self.start_time = None 
        self._plot_start_delay_seconds = float(PLOT_WARMUP_SECONDS)
        self.is_phase_active = False
        self._fault_active = False
        self._consecutive_good = 0
        self._hr_ewma = None
        self._hr_ewma_post_warmup = False
        self._signal_popup_shown = False
        self._signal_degrade_count = 0
        self._signal_popup_widget: QMessageBox | None = None
        self._pending_signal_popup_reason: str | None = None
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_floor = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_floor = None
        self._sdnn_axis_ceiling = None
        self._main_plot_warmup_until: float | None = None
        self._main_plots_frozen = False
        self._all_plots_frozen = False
        self._phase_debug_last_second = -1
        self._phase_debug_last_name = ""
        self._debug_heart_anim_groups = []
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._rmssd_smooth_post_warmup = False
        self._main_plot_visible_sec = 60.0
        self._main_plot_guard_sec = 12.0
        self._series_prune_stride = 32
        self._last_data_time = None
        self._suppress_comm_error_popups = False
        self._signal_fault_buffer: list[dict] = []
        self._signal_fault_counts: dict[str, int] = {}
        # Disconnect intervals for manifest/CSV/report (start_ts, end_ts, reason, duration_sec)
        self._disconnect_intervals: list[dict] = []
        self._current_disconnect_start: float | None = None
        self._disconnect_reason: str = ""
        # Gray overlay during disconnect (separate from "no sensor" overlay)
        self._disconnect_overlay_hr: QLabel | None = None
        self._disconnect_overlay_hrv: QLabel | None = None
        # Segment series for explicit timeline gaps (multi-series to avoid bridge lines)
        self._hr_segments: list = []
        self._rmssd_segments: list = []
        self._sdnn_segments: list = []
        self._ibi_diag_last_counts = {"beats_received": 0, "buffer_updates": 0}
        self._session_annotations: list[tuple[str, str]] = []
        self._session_hr_values: list[float] = []
        self._session_hr_times: list[float] = []
        self._session_rmssd_values: list[float] = []
        self._session_rmssd_times: list[float] = []
        self._session_hrv_values: list[float] = []
        self._session_hrv_times: list[float] = []
        self._session_stress_ratio_values: list[float] = []
        self._session_snr_values: list[float] = []
        self._session_qtc_payload: dict = default_qtc_payload()
        self._last_qtc_diag_logged: tuple = ()  # (method, qrs_source) for DEBUG throttle
        self._session_state = "idle"
        self._session_bundle: SessionBundle | None = None
        self._disclaimer_acknowledged_at: str | None = None
        self._disclaimer_ack_mode = "not_recorded"
        self._session_root = Path.home() / "Hertz-and-Hearts"
        self._profile_store = ProfileStore(self._session_root)
        self._session_profile_id = (
            self._profile_store.get_last_active_profile() or "Admin"
        )
        self._profile_store.ensure_profile(self._session_profile_id)

        self.setWindowTitle(f"Hertz & Hearts ({version})")
        self.setWindowIcon(QIcon(":/logo.png"))
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_application_state_changed)

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
        self._ibi_diag_timer = QTimer()
        self._ibi_diag_timer.setInterval(10000)
        self._ibi_diag_timer.timeout.connect(self._emit_ibi_diagnostics)

        self.scanner = SensorScanner()
        self.scanner.sensor_update.connect(self.model.update_sensors)
        self.scanner.status_update.connect(self.show_status)

        self.sensor = SensorClient()
        self.sensor.ibi_update.connect(self.model.update_ibis_buffer)
        self.sensor.verity_limited_support.connect(self._on_verity_limited_support)
        self.sensor.ecg_update.connect(self.model.update_ecg_samples)
        self.sensor.status_update.connect(self.show_status)
        self.sensor.battery_update.connect(self._update_battery_display)

        self.ecg_window = EcgWindow()
        self.qtc_window = QtcWindow()
        self.model.qtc_update.connect(lambda data: self.qtc_window.append_payload(data.value))
        self.sensor.ecg_update.connect(self.ecg_window.append_samples)
        self.ecg_window.cursor_measurement_captured.connect(self._on_ecg_cursor_measurement)
        self.ecg_window.image_captured.connect(self._on_ecg_image_captured)
        self.sensor.ecg_ready.connect(self._on_ecg_ready)
        self.ecg_window.closed.connect(self._on_ecg_window_closed)
        self.qtc_window.closed.connect(self._on_qtc_window_closed)
        self.poincare_window = PoincareWindow()
        self.poincare_window.closed.connect(self._on_poincare_window_closed)
        self.psd_window = PSDWindow()
        self.psd_window.closed.connect(self._on_psd_window_closed)
        self._trends_window: TrendsWindow | None = None
        self.ecg_window.installEventFilter(self)
        self.qtc_window.installEventFilter(self)
        self.poincare_window.installEventFilter(self)
        self.psd_window.installEventFilter(self)
        self.poincare_window.info_requested.connect(self.show_poincare_info)
        self.psd_window.info_requested.connect(self.show_psd_info)
        self.model.ibis_buffer_update.connect(self._update_poincare)
        self.model.psd_update.connect(self._update_psd)

        self.logger = Logger()
        self.logger_thread = QThread()
        self.logger.moveToThread(self.logger_thread)
        self.logger_thread.finished.connect(self.logger.save_recording)
        self.signals.start_recording.connect(self.logger.start_recording)
        self.signals.save_recording.connect(self.logger.save_recording)
        self.signals.annotation.connect(self.logger.write_to_file)
        self.logger.recording_status.connect(self.show_recording_status)
        self.logger.status_update.connect(self.show_status)
        self.model.ibis_buffer_update.connect(self.logger.write_to_file)
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

        self.ibis_widget.plot.legend().setVisible(False)

        self.hr_y_axis_right = QValueAxis()
        self.hr_y_axis_right.setLabelsVisible(False)
        self.hr_y_axis_right.setTitleText(" ")
        self.hr_y_axis_right.setRange(40, 160)
        self.ibis_widget.plot.addAxis(self.hr_y_axis_right, Qt.AlignRight)
        self.hr_trend_series.attachAxis(self.hr_y_axis_right)

        self.hrv_widget = XYSeriesWidget(self.model.hrv_seconds, self.model.hrv_buffer)
        self.hrv_widget.y_axis.setRange(0, 10)
        self.hrv_widget.time_series.setName("RMSSD (ms)")
        self.hrv_widget.plot.legend().setVisible(False)

        self.sdnn_series = QLineSeries()
        self.sdnn_series.setName("HRV(SDNN)")
        sdnn_color = QColor(0, 130, 255)
        pen = QPen(sdnn_color)
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)  # distinguishable on monochrome printouts
        self.sdnn_series.setPen(pen)
        # X-shaped markers for monochrome distinguishability from solid RMSSD line
        sdnn_marker_size = 7
        self.sdnn_series.setMarkerSize(sdnn_marker_size)
        x_marker = QImage(sdnn_marker_size, sdnn_marker_size, QImage.Format.Format_ARGB32)
        x_marker.fill(QColor(0, 0, 0, 0))
        px = QPainter(x_marker)
        px.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        px.setPen(QPen(sdnn_color, 1))
        m = sdnn_marker_size
        px.drawLine(1, 1, m - 2, m - 2)
        px.drawLine(m - 2, 1, 1, m - 2)
        px.end()
        self.sdnn_series.setLightMarker(x_marker)

        self.hrv_y_axis_right = QValueAxis()
        self.hrv_y_axis_right.setTitleText("HRV(SDNN) --x--")
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
        self._disconnect_overlay_hr = self._make_disconnect_overlay(self.ibis_widget)
        self._disconnect_overlay_hrv = self._make_disconnect_overlay(self.hrv_widget)
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
        self._resuming_after_button_disconnect = False

        self.recording_statusbar = StatusBanner()

        # Labels
        self.current_hr_label = QLabel("HR: --")
        self.rmssd_label = QLabel("RMSSD: --")
        self.sdnn_label = QLabel("SDNN: --")
        self.stress_ratio_label = QLabel("LF/HF: --")
        self.qrs_label = QLabel("QRS: -- ms")
        self.health_indicator = QLabel("\u25cf")
        self.health_indicator.setStyleSheet("color: gray; font-size: 18px;")
        self.health_label = QLabel("Signal: Waiting for sensor")

        # Pacer controls
        self.pacer_label = QLabel("Rate: 7")
        self.pacer_rate = QSlider(Qt.Horizontal)
        self.pacer_rate.setRange(3, 15)
        self.pacer_rate.setValue(7)
        self.pacer_rate.setTickPosition(QSlider.TicksBelow)
        self.pacer_rate.setTickInterval(1)
        self.pacer_rate.setSingleStep(1)
        self.pacer_rate.valueChanged.connect(self._update_breathing_rate)
        saved_rate = self._profile_store.get_profile_pref(
            self._session_profile_id, "breathing_rate", "7"
        )
        try:
            rate = int(saved_rate)
            if 3 <= rate <= 15:
                self.pacer_rate.setValue(rate)
                self.model.breathing_rate = float(rate)
                self.pacer_label.setText(f"Rate: {rate}")
        except (ValueError, TypeError):
            pass
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
        self.battery_label = QLabel("\u2014")  # em dash when unknown, value% when connected
        self.battery_label.setStyleSheet(
            "font-size: 10px; color: #666; background: #e0e0e0; "
            "border-radius: 3px; padding: 1px 4px;"
        )
        self.battery_label.setFixedWidth(36)
        self.battery_label.setAlignment(Qt.AlignCenter)
        self.battery_label.setToolTip(
            '<span style="color: black; white-space: nowrap;">Sensor battery level (shown when connected).</span>'
        )
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

        self.ecg_button = QPushButton("ECG (no sensor)")
        self.ecg_button.setEnabled(False)
        self.ecg_button.clicked.connect(self.toggle_ecg_window)
        self.qtc_button = QPushButton("QTc (no sensor)")
        self.qtc_button.setEnabled(False)
        self.qtc_button.clicked.connect(self.toggle_qtc_window)
        self.poincare_button = QPushButton("Poincare (no sensor)")
        self.poincare_button.setEnabled(False)
        self.poincare_button.clicked.connect(self.toggle_poincare_window)
        self.psd_button = QPushButton("PSD (no sensor)")
        self.psd_button.setEnabled(False)
        self.psd_button.clicked.connect(self.toggle_psd_window)

        self.start_recording_button = QPushButton("Start New")
        self.start_recording_button.clicked.connect(self.start_session)
        self.stop_save_button = QPushButton("Stop && Save")
        self.stop_save_button.clicked.connect(self._stop_and_save)
        self.history_button = QPushButton("History")
        self.history_button.clicked.connect(self._open_history)
        self.trends_button = QPushButton("Trends")
        self.trends_button.clicked.connect(self._open_trends)
        self.profile_manager_button = QPushButton("Profiles")
        self.profile_manager_button.clicked.connect(self._open_profile_manager)
        self.logout_button = QPushButton("Switch User")
        self.logout_button.setToolTip("Switch user profile (same popup as startup).")
        self.logout_button.clicked.connect(self._on_logout_clicked)

        self._annotation_enabled_placeholder = "Choose from list or enter new text"
        self._annotation_disabled_placeholder = "Recording only"
        self.annotation = QComboBox()
        self.annotation.setEditable(True)
        self.annotation.setInsertPolicy(QComboBox.NoInsert)
        self.annotation.completer().setFilterMode(Qt.MatchContains)
        self.annotation.completer().setCompletionMode(
            QCompleter.PopupCompletion
        )
        self.annotation.setPlaceholderText(self._annotation_enabled_placeholder)
        if self.annotation.lineEdit() is not None:
            self.annotation.lineEdit().setPlaceholderText(
                self._annotation_enabled_placeholder
            )
        self._refresh_annotation_list()
        self.annotation_button = QPushButton("Annotate")
        self.annotation_button.clicked.connect(self.emit_annotation)
        self.annotation.activated.connect(self.emit_annotation)
        self.annotation.installEventFilter(self)
        if self.annotation.lineEdit() is not None:
            self.annotation.lineEdit().installEventFilter(self)
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
        self.psd_button.setToolTip(
            "Open the PSD (Power Spectral Density) window showing Vagal Resonance at 0.1 Hz."
        )
        self.start_recording_button.setToolTip("Start a new session and begin recording.")
        self.stop_save_button.setToolTip(
            "Stop recording and save session (CSV, report, EDF+) to the path configured in Settings."
        )
        self.history_button.setToolTip("Show recent session history for the active user profile.")
        self.trends_button.setToolTip("Compare-plot session trends over day/week/month/year spans.")
        self.profile_manager_button.setToolTip("Manage user profiles (create, rename, archive, delete).")
        self.annotation.setToolTip("Choose or type a session annotation.")
        self.annotation_button.setToolTip("Add the current annotation to the session log.")
        self.pacer_rate.setToolTip("Breathing pacer rate in breaths per minute.")
        self.pacer_toggle.setToolTip("Show or hide the breathing pacer animation.")
        self.current_hr_label.setToolTip("Current averaged heart rate in beats per minute.")
        self.rmssd_label.setToolTip("Current RMSSD heart rate variability metric.")
        self.sdnn_label.setToolTip("Current SDNN heart rate variability metric.")
        self.stress_ratio_label.setToolTip("Current LF/HF ratio estimate.")
        self.qrs_label.setToolTip(
            f"Current median QRS duration estimate (±{ECG_QRS_UNCERTAINTY_PCT}% measurement uncertainty from single-lead ECG)."
        )
        self.health_label.setToolTip("Current signal quality status.")
        self.recording_statusbar.setToolTip("Session progress and recording state.")

        # 5. LAYOUT ASSEMBLY — monitoring dashboard
        central = QWidget()
        self.vlayout0 = QVBoxLayout(central)
        self.vlayout0.setSpacing(2)

        # Header row: center active profile over plot column, keep controls on right.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        self.profile_header_label = QLabel(f"User: {self._session_profile_id}")
        self.profile_header_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #2c3e50;"
        )
        self.profile_header_label.setAlignment(Qt.AlignCenter)
        self._disclaimer_link = QLabel('<a href="open-disclaimer">Legal Disclaimer</a>')
        self._disclaimer_link.setTextFormat(Qt.RichText)
        self._disclaimer_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._disclaimer_link.setOpenExternalLinks(False)
        self._disclaimer_link.setToolTip("Open the full legal disclaimer file.")
        self._disclaimer_link.linkActivated.connect(self._open_disclaimer_file)
        self._debug_mode_badge = QLabel("DEBUG ON")
        self._debug_mode_badge.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #7e0000; "
            "background: #ffe5e5; border: 1px solid #ffb3b3; "
            "border-radius: 3px; padding: 1px 6px;"
        )
        self._debug_mode_badge.setVisible(False)
        profile_zone = QWidget()
        profile_zone_layout = QHBoxLayout(profile_zone)
        profile_zone_layout.setContentsMargins(0, 0, 0, 0)
        profile_zone_layout.setSpacing(8)
        profile_zone_layout.addStretch()
        profile_zone_layout.addWidget(self.profile_header_label, alignment=Qt.AlignCenter)
        self.logout_button.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        profile_zone_layout.addWidget(self.logout_button, alignment=Qt.AlignVCenter)
        profile_zone_layout.addWidget(self._debug_mode_badge, alignment=Qt.AlignVCenter)
        profile_zone_layout.addStretch()
        controls_zone = QWidget()
        controls_zone_layout = QHBoxLayout(controls_zone)
        controls_zone_layout.setContentsMargins(0, 0, 0, 0)
        controls_zone_layout.setSpacing(8)
        controls_zone_layout.addWidget(self._disclaimer_link, alignment=Qt.AlignVCenter)
        controls_zone_layout.addWidget(self.profile_manager_button)
        controls_zone_layout.addWidget(self._settings_button)
        controls_zone_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_row.addWidget(profile_zone, stretch=1)
        header_row.addWidget(controls_zone)
        self._top_bar = QWidget()
        self._top_bar.setLayout(header_row)
        self.vlayout0.addWidget(self._top_bar)
        for _w in (
            self._top_bar,
            profile_zone,
            controls_zone,
            self.profile_header_label,
            self._disclaimer_link,
            self._debug_mode_badge,
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
        freeze_row.setSpacing(0)
        freeze_row.addStretch()
        freeze_group = QHBoxLayout()
        freeze_group.setSpacing(8)
        self.freeze_two_main_plots_button.setFixedWidth(160)
        freeze_group.addWidget(self.freeze_two_main_plots_button)
        self.freeze_all_button.setFixedWidth(92)
        freeze_group.addWidget(self.freeze_all_button)
        freeze_row.addLayout(freeze_group)
        freeze_row.addSpacing(24)
        reset_group = QHBoxLayout()
        reset_group.setSpacing(8)
        self.reset_axes_button.setFixedWidth(108)
        self.reset_button.setFixedWidth(108)
        reset_group.addWidget(self.reset_axes_button)
        reset_group.addWidget(self.reset_button)
        freeze_row.addLayout(reset_group)
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
        self.psd_button.setMaximumWidth(130)
        self.psd_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.start_recording_button.setMaximumWidth(90)
        self.start_recording_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.stop_save_button.setMaximumWidth(110)
        self.stop_save_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.history_button.setMaximumWidth(80)
        self.history_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.trends_button.setMaximumWidth(100)
        self.trends_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.profile_manager_button.setMinimumWidth(70)
        self.profile_manager_button.setMaximumWidth(80)
        self.profile_manager_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._disclaimer_link.setStyleSheet(
            "font-size: 11px; color: #1b6ec2; text-decoration: underline;"
        )
        self.address_menu.setMaximumWidth(200)
        self.address_menu.setStyleSheet("font-size: 11px;")

        toolbar.addWidget(self.scan_button)
        toolbar.addWidget(self.address_menu)
        toolbar.addWidget(self.connect_button)
        toolbar.addWidget(self.disconnect_button)
        toolbar.addWidget(self.battery_label)

        _sep1 = QFrame()
        _sep1.setFixedSize(1, 18)
        _sep1.setStyleSheet("background: #bdc3c7;")
        toolbar.addWidget(_sep1)

        toolbar.addStretch()
        toolbar.addWidget(self.ecg_button)
        toolbar.addWidget(self.qtc_button)
        toolbar.addWidget(self.poincare_button)
        toolbar.addWidget(self.psd_button)
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
            self.qrs_label,
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

        _sep2 = QFrame()
        _sep2.setFixedSize(1, 18)
        _sep2.setStyleSheet("background: #bdc3c7;")
        toolbar.addWidget(_sep2)

        self.annotation.setMaximumWidth(200)
        self.annotation.setStyleSheet("font-size: 11px;")
        self.annotation.setPlaceholderText(self._annotation_enabled_placeholder)
        self.annotation_button.setMaximumWidth(64)
        self.annotation_button.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 6px; }"
            "QPushButton:disabled { color: #7f8c8d; background-color: #e0e0e0; }"
        )
        toolbar.addWidget(self.start_recording_button)
        toolbar.addWidget(self.stop_save_button)
        toolbar.addWidget(self.history_button)
        toolbar.addWidget(self.trends_button)
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

    def _on_logout_clicked(self):
        selected = self._prompt_for_session_profile()
        if selected is not None and selected.casefold() != self._session_profile_id.casefold():
            self._set_active_profile(selected, announce=True)

    def _prompt_for_session_profile(self, *, use_parent: bool = True) -> str | None:
        profiles = self._profile_store.list_profiles()
        last_profile = self._profile_store.get_last_active_profile()
        dlg = ProfileSelectionDialog(
            profiles=profiles,
            last_profile=last_profile,
            profile_store=self._profile_store,
            parent=self if use_parent else None,
        )
        if dlg.exec() != QDialog.Accepted:
            return None
        if dlg.selected_profile is None:
            return None
        profile_id = self._profile_store.ensure_profile(dlg.selected_profile)
        pw = getattr(dlg, "password_entered", "") or ""
        if pw and profile_id.casefold() != "guest" and not self._profile_store.profile_has_password(profile_id):
            self._profile_store.set_profile_password(profile_id, pw)
        return profile_id

    def _set_active_profile(self, profile_id: str, announce: bool = False):
        self._session_profile_id = self._profile_store.set_last_active_profile(profile_id)
        self.profile_header_label.setText(f"User: {self._session_profile_id}")
        saved_rate = self._profile_store.get_profile_pref(
            self._session_profile_id, "breathing_rate", "7"
        )
        try:
            rate = int(saved_rate)
            if 3 <= rate <= 15:
                self.pacer_rate.setValue(rate)
                self.model.breathing_rate = float(rate)
                self.pacer_label.setText(f"Rate: {rate}")
        except (ValueError, TypeError):
            pass
        debug_pref = self._profile_store.get_profile_pref(
            self._session_profile_id,
            "debug_mode",
            default=("1" if self.settings.DEBUG else "0"),
        )
        self._set_debug_mode(debug_pref == "1", announce=False)
        if announce:
            self.show_status(f"Active user: {self._session_profile_id}")
        if getattr(self, "_trends_window", None) is not None:
            self._trends_window.set_active_profile(self._session_profile_id)

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
        self._disclaimer_acknowledged_at = datetime.now().isoformat()
        self._disclaimer_ack_mode = "interactive_dialog"
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
            msg.setDefaultButton(QMessageBox.Ok)
            flags = msg.windowFlags()
            flags &= ~Qt.WindowMinimizeButtonHint
            flags &= ~Qt.WindowCloseButtonHint
            flags |= Qt.CustomizeWindowHint | Qt.WindowTitleHint
            msg.setWindowFlags(flags)
            msg.exec()
        return True

    def _run_startup_flow(self):
        # Show main window first, then profile selection on top.
        self._show_main_window_fullscreen()
        selected_profile = self._prompt_for_session_profile(use_parent=True)
        if selected_profile is None:
            self.close()
            return
        self._set_active_profile(selected_profile, announce=True)
        if self._should_show_disclaimer_for_profile(selected_profile):
            if not self._show_card0_dialog(selected_profile):
                self.close()
                return
        else:
            self._disclaimer_acknowledged_at = None
            self._disclaimer_ack_mode = "profile_skip_preference"

    def _show_maximized_fit(self):
        """Size window to available screen (avoid showMaximized which can push window off-screen on Windows)."""
        self._measure_and_apply_fit_geometry()

    def _show_main_window_fullscreen(self):
        """Show main window filling available screen (used after startup flow)."""
        screen = self.screen()
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            avail = screen.availableGeometry()
            inset = self._window_frame_inset()
            geom = QRect(
                avail.x() + inset.left(),
                avail.y() + inset.top(),
                avail.width() - inset.left() - inset.right(),
                avail.height() - inset.top() - inset.bottom(),
            )
            self.setGeometry(geom)
        self._maximized_once = True
        self.show()
        QTimer.singleShot(60, self._measure_and_apply_fit_geometry)
        # Do NOT call showMaximized here: on Windows it overwrites our correct
        # geometry and can push the window off-screen. Our setGeometry already
        # fills the available screen.

    def _window_frame_inset(self) -> QMargins:
        """Window frame size; uses cached measurement when available."""
        if self._cached_frame_inset is not None:
            return self._cached_frame_inset
        return QMargins(10, 40, 10, 10)

    def _measure_and_apply_fit_geometry(self):
        """Measure actual window frame and apply geometry that fits the screen."""
        if not self.isVisible():
            return
        fg = self.frameGeometry()
        g = self.geometry()
        left = max(0, g.left() - fg.left())
        top = max(0, g.top() - fg.top())
        right = max(0, fg.right() - g.right())
        bottom = max(0, fg.bottom() - g.bottom())
        self._cached_frame_inset = QMargins(left, top, right, bottom)

        screen = self.screen()
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            avail = screen.availableGeometry()
            geom = QRect(
                avail.x() + left,
                avail.y() + top,
                avail.width() - left - right,
                avail.height() - top - bottom,
            )
            self.setGeometry(geom)

    def _ensure_window_on_screen(self):
        """Clamp window to visible screen area. Safety net for off-screen recovery."""
        if not self.isVisible():
            return
        screen = self.screen()
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        avail = screen.availableGeometry()
        g = self.geometry()
        # Early exit: already fully on screen
        if avail.contains(g):
            return
        # Clamp to available bounds
        new_x = max(avail.left(), min(g.x(), avail.right() - min(g.width(), avail.width())))
        new_y = max(avail.top(), min(g.y(), avail.bottom() - min(g.height(), avail.height())))
        new_w = min(g.width(), avail.width())
        new_h = min(g.height(), avail.height())
        self.setGeometry(QRect(new_x, new_y, new_w, new_h))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._maximized_once:
            self._maximized_once = True
            QTimer.singleShot(0, self._show_maximized_fit)
        # Safety net: ensure window stays on screen (handles monitor changes, etc.)
        QTimer.singleShot(100, self._ensure_window_on_screen)

    def closeEvent(self, event):
        self._suppress_comm_error_popups = True
        if self._session_state == "recording":
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Finalize Session")
            msg.setText("You have an active session. Finalize and save artifacts before closing?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            msg.setDefaultButton(QMessageBox.Yes)
            # Ensure this prompt stays reachable even if an auxiliary popup was pinned.
            msg.setWindowModality(Qt.ApplicationModal)
            msg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            reply = msg.exec()
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Yes:
                self.finalize_session(show_message=False)
            else:
                self._abandon_active_session()
        # Ensure auxiliary plot windows close with the main app window.
        for popup in (self.ecg_window, self.qtc_window, self.poincare_window, self.psd_window):
            try:
                popup.close()
            except Exception:
                pass
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
        connecting = self._connect_attempt_timer.isActive()
        is_recording = self._session_state == "recording"
        annotation_available = is_recording
        self.start_recording_button.setEnabled(connected and not is_recording)
        self.stop_save_button.setEnabled(is_recording)
        self.annotation.setEnabled(annotation_available)
        self.annotation_button.setEnabled(annotation_available)
        annotation_placeholder = (
            self._annotation_enabled_placeholder
            if annotation_available
            else self._annotation_disabled_placeholder
        )
        self.annotation.setPlaceholderText(annotation_placeholder)
        if self.annotation.lineEdit() is not None:
            self.annotation.lineEdit().setPlaceholderText(annotation_placeholder)
        if not annotation_available:
            self.annotation.setCurrentText("")
        self.poincare_button.setEnabled(connected)
        self.psd_button.setEnabled(connected)
        if not connected:
            self.qtc_button.setEnabled(False)
            if not connecting:
                # Connectivity state must override any prior phase banner state.
                self.is_phase_active = False
                self.recording_statusbar.set_disconnected()
                self.ecg_button.setText("ECG (no sensor)")
                self.qtc_button.setText("QTc (no sensor)")
                self.poincare_button.setText("Poincare (no sensor)")
                self.psd_button.setText("PSD (no sensor)")
        elif self.ecg_button.isEnabled():
            self.qtc_button.setEnabled(True)
        self._apply_freeze_button_states()
        self._refresh_popup_control_labels()
        self.ecg_window.set_image_capture_enabled(self._session_bundle is not None)

    def _current_sensor_label(self) -> str:
        text = self.address_menu.currentText().strip()
        if not text:
            return "--"
        return text

    def get_default_session_save_path(self) -> str:
        """Return the default session save path (Sessions/{profile}) for display in Settings."""
        profile_slug = _slugify_profile(getattr(self, "_session_profile_id", "") or "Admin")
        return str(self._session_root / "Sessions" / profile_slug)

    def _session_save_path_from_settings(self) -> Path:
        """Return the configured session save path, or Sessions/{profile} if empty/invalid."""
        raw = (getattr(self.settings, "SESSION_SAVE_PATH", "") or "").strip()
        if not raw:
            profile_slug = _slugify_profile(getattr(self, "_session_profile_id", "") or "Admin")
            return self._session_root / "Sessions" / profile_slug
        candidate = Path(raw)
        if not candidate.exists():
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError:
                profile_slug = _slugify_profile(getattr(self, "_session_profile_id", "") or "Admin")
                return self._session_root / "Sessions" / profile_slug
        return candidate

    def _copy_session_folder_to(self, destination_root: Path) -> Path | None:
        if self._session_bundle is None:
            return None
        source = self._session_bundle.session_dir
        if not source.exists():
            return None
        target = destination_root / source.name
        if target.resolve() == source.resolve():
            return target
        if target.exists():
            for idx in range(1, 1000):
                candidate = destination_root / f"{source.name}_{idx:02d}"
                if not candidate.exists():
                    target = candidate
                    break
        shutil.copytree(source, target)
        return target

    def _copy_selected_artifacts_to(self, destination_root: Path, paths: list[Path]) -> Path | None:
        if self._session_bundle is None:
            return None
        out_dir = destination_root / self._session_bundle.session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        copied_any = False
        for path in paths:
            if not path.exists():
                continue
            shutil.copy2(path, out_dir / path.name)
            copied_any = True
        return out_dir if copied_any else None

    def _build_report_data(self, report_stage: str) -> dict:
        session_start = (
            datetime.fromtimestamp(self.start_time)
            if self.start_time is not None
            else (self._session_bundle.started_at if self._session_bundle else datetime.now())
        )
        session_end = datetime.now()
        last_rmssd = self._session_rmssd_values[-1] if self._session_rmssd_values else None
        last_hr = self._session_hr_values[-1] if self._session_hr_values else None
        ecg_samples = list(getattr(self.model, "_ecg_buffer", []))
        max_samples = int(ECG_SAMPLE_RATE * 8)
        if len(ecg_samples) > max_samples:
            ecg_samples = ecg_samples[-max_samples:]
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
            "hr_time_seconds": list(self._session_hr_times),
            "rmssd_values": list(self._session_rmssd_values),
            "rmssd_time_seconds": list(self._session_rmssd_times),
            "hrv_values": list(self._session_hrv_values),
            "hrv_time_seconds": list(self._session_hrv_times),
            "stress_ratio_values": list(self._session_stress_ratio_values),
            "snr_values": list(self._session_snr_values),
            "ecg_samples": ecg_samples,
            "ecg_sample_rate_hz": ECG_SAMPLE_RATE,
            "ecg_is_simulated": False,
            "notes": "",
            "csv_path": csv_path,
            "report_stage": report_stage,
            "qtc": qtc_payload,
            "disclaimer": self._current_disclaimer_payload(),
            "settling_duration_seconds": getattr(
                self.settings, "SETTLING_DURATION", 15
            ),
        }

    def _export_optional_edf_plus(self, report_data: dict):
        if self._session_bundle is None:
            return
        if not bool(getattr(self.settings, "EXPORT_EDF_PLUS_D", False)):
            return
        ok, result = export_session_edf_plus(str(self._session_bundle.edf_path), report_data)
        if ok:
            self.show_status(f"Saved EDF+ file: {result}")
            return
        self.show_status(f"EDF+ export skipped: {result}")

    def _current_disclaimer_payload(self) -> dict:
        text = _CARD0_DISCLAIMER_TEXT.strip() or _CARD0_DISCLAIMER_FALLBACK
        return {
            "warning": _RESEARCH_USE_WARNING,
            "source_path": str(_CARD0_DISCLAIMER_PATH),
            "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "acknowledgment_mode": self._disclaimer_ack_mode,
            "acknowledged_at": self._disclaimer_acknowledged_at,
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
        disc_intervals = list(self._disconnect_intervals or [])
        total_disc_sec = sum(r.get("duration_sec", 0) for r in disc_intervals)
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
            "disconnect_intervals": disc_intervals,
            "disconnect_total_seconds": total_disc_sec,
            "disclaimer": self._current_disclaimer_payload(),
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
                "share_pdf_final": {
                    "path": str(_one_page_share_path(bundle, "final")),
                    "exists": _one_page_share_path(bundle, "final").exists(),
                },
                "share_pdf_draft": {
                    "path": str(_one_page_share_path(bundle, "draft")),
                    "exists": _one_page_share_path(bundle, "draft").exists(),
                },
                "edf": {
                    "path": str(bundle.edf_path),
                    "exists": bundle.edf_path.exists(),
                    "status": (
                        "saved"
                        if bundle.edf_path.exists()
                        else ("disabled" if not bool(getattr(self.settings, "EXPORT_EDF_PLUS_D", False)) else "pending")
                    ),
                },
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
        self._session_hr_times = []
        self._session_rmssd_values = []
        self._session_rmssd_times = []
        self._session_hrv_values = []
        self._session_hrv_times = []
        self._session_stress_ratio_values = []
        self._session_snr_values = []
        self._session_qtc_payload = default_qtc_payload()
        self._last_qtc_diag_logged = ()
        self._disconnect_intervals = []
        self._profile_store.record_session_started(
            profile_name=self._session_profile_id,
            bundle=self._session_bundle,
        )
        self.signals.start_recording.emit(str(self._session_bundle.csv_path))
        disclaimer = self._current_disclaimer_payload()
        self.signals.annotation.emit(NamedSignal("LegalWarning", disclaimer["warning"]))
        self.signals.annotation.emit(NamedSignal("DisclaimerSHA256", disclaimer["sha256"]))
        self.signals.annotation.emit(
            NamedSignal("DisclaimerAckMode", disclaimer["acknowledgment_mode"])
        )
        if disclaimer["acknowledged_at"]:
            self.signals.annotation.emit(
                NamedSignal("DisclaimerAckAt", disclaimer["acknowledged_at"])
            )
        self._set_session_state("recording")
        self._persist_manifest(state="recording", report_stage="draft")
        if auto:
            self.show_status(f"Session auto-started: {self._session_bundle.session_dir}")
        else:
            self.show_status(f"Session started: {self._session_bundle.session_dir}")

    def stop_session(self):
        """End the measuring session, stop recording, and save data to session folder.
        Does not generate reports or prompt for copy destination. Use Save for that."""
        self._abandon_active_session()
        if self._session_bundle is not None:
            self.show_status(f"Session stopped. Data saved to {self._session_bundle.session_dir}")

    def _abandon_active_session(self):
        if self._session_state != "recording":
            return
        self._record_disconnect_end()  # Close any open interval before abandoning
        self.signals.save_recording.emit()
        if self._session_bundle is not None:
            self._record_session_trend_from_current_state()
            self._profile_store.record_session_finished(
                session_id=self._session_bundle.session_id,
                state="abandoned",
            )
        self._persist_manifest(state="abandoned", report_stage="draft")
        self._set_session_state("finalized")

    def _stop_and_save(self):
        """Stop recording and save session (CSV, report, EDF+) to Settings path."""
        self.finalize_session(show_message=True, build_final_report=True)

    def finalize_session(self, show_message: bool = True, build_final_report: bool = True):
        if self._session_state != "recording":
            if show_message:
                self.show_status("No active session to save.")
            return
        self._record_disconnect_end()  # Close any open disconnect interval for manifest
        destination_root = self._session_save_path_from_settings()
        self.signals.save_recording.emit()
        if build_final_report and self._session_bundle is not None:
            try:
                final_data = self._build_report_data(report_stage="final")
                generate_session_report(str(self._session_bundle.report_final_path), final_data)
                share_path = _one_page_share_path(self._session_bundle, "final")
                generate_session_share_pdf(str(share_path), final_data)
                self._export_optional_edf_plus(final_data)
            except Exception as exc:
                if show_message:
                    self.show_status(f"Final report generation failed: {exc}")
        if self._session_bundle is not None:
            self._record_session_trend_from_current_state()
            self._profile_store.record_session_finished(
                session_id=self._session_bundle.session_id,
                state="finalized",
            )
        self._set_session_state("finalized")
        self._persist_manifest(state="finalized", report_stage="final")
        try:
            copied_dir = self._copy_session_folder_to(destination_root)
            if copied_dir is not None:
                self.show_status(f"Saved session copy to: {copied_dir}")
                if getattr(self.settings, "OPEN_SESSION_FOLDER_ON_SAVE", True):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(copied_dir)))
        except Exception as exc:
            self.show_status(f"Session copy failed: {exc}")
        if show_message and self._session_bundle is not None:
            self.show_status(f"Session finalized: {self._session_bundle.session_dir}")

    def connect_sensor(self):
        if not self.address_menu.currentText():
            return
        parts = self.address_menu.currentText().split(",")
        self._do_connect(parts[0].strip(), parts[1].strip())

    def _do_connect(self, name: str, address: str):
        self._suppress_comm_error_popups = False
        self.model.reset_ibi_diagnostics()
        self._ibi_diag_last_counts = {"beats_received": 0, "buffer_updates": 0}
        sensor = [s for s in self.model.sensors if get_sensor_address(s) == address]

        if not sensor:
            bt_addr = QBluetoothAddress(address)
            device = QBluetoothDeviceInfo(bt_addr, name, 0)
            device.setCoreConfigurations(QBluetoothDeviceInfo.LowEnergyCoreConfiguration)
            sensor = [device]

        # Preserve plot history on reconnect (parity with sensor-induced path)
        preserve_plots = (
            self.hr_trend_series.count() > 0
            or self.hrv_widget.time_series.count() > 0
            or self.sdnn_series.count() > 0
        )
        if preserve_plots:
            self._resuming_after_button_disconnect = True
        else:
            self._resuming_after_button_disconnect = False
            self.start_time = None

        if not preserve_plots:
            self.baseline_values = []
            self.baseline_rmssd = None
            self.baseline_hr_values = []
            self.baseline_hr = None
        self.is_phase_active = False
        self._fault_active = False
        self._consecutive_good = 0
        self._hr_ewma = None
        self._hr_ewma_post_warmup = False
        self._reset_signal_popup()
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_floor = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_floor = None
        self._sdnn_axis_ceiling = None
        self._main_plots_frozen = False
        self._all_plots_frozen = False
        self.ecg_window.set_stream_frozen(False)
        self.qtc_window.set_stream_frozen(False)
        self._apply_freeze_button_states()
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._rmssd_smooth_post_warmup = False
        self._session_annotations = []
        self._session_hr_values = []
        self._session_hr_times = []
        self._session_rmssd_values = []
        self._session_rmssd_times = []
        self._session_hrv_values = []
        self._session_hrv_times = []
        self._session_stress_ratio_values = []
        self._session_snr_values = []
        self._session_qtc_payload = default_qtc_payload()
        self._last_qtc_diag_logged = ()
        self._session_bundle = None
        self.ecg_window.clear()
        self.qtc_window.clear()
        self._set_session_state("idle")
        if not preserve_plots:
            self.hr_trend_series.clear()
            self.sdnn_series.clear()
            self.hrv_widget.time_series.clear()
            # Remove segment series from chart when doing full reset
            for segments, chart in [
                (self._hr_segments, self.ibis_widget.plot),
                (self._rmssd_segments, self.hrv_widget.chart()),
                (self._sdnn_segments, self.hrv_widget.chart()),
            ]:
                while segments:
                    chart.removeSeries(segments.pop(0))
        if not preserve_plots and hasattr(self, 'baseline_series'):
            self.hrv_widget.chart().removeSeries(self.baseline_series)
            del self.baseline_series
        if not preserve_plots and hasattr(self, 'hr_baseline_series'):
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
        self.psd_button.setEnabled(False)
        self.psd_button.setText("PSD (starting...)")
        self.sensor.connect_client(*sensor)
        self._connect_attempt_timer.start()
        self._last_data_time = None
        self._data_watchdog.stop()
        self.show_status("Connecting to Sensor... Please wait.")

    def disconnect_sensor(self):
        self._suppress_comm_error_popups = True
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
        # Complete any open sensor-fault interval
        self._record_disconnect_end()
        self._record_disconnect_start("User disconnect")
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
        if self.psd_window.isVisible():
            self.psd_window.hide()
        self.psd_window.clear()
        # Preserve main plot history (parity with sensor-induced disconnect)
        # self.hrv_widget.time_series, self.hr_trend_series, self.sdnn_series - NOT cleared
        self.model.reset_ibi_diagnostics()
        self._ibi_diag_last_counts = {"beats_received": 0, "buffer_updates": 0}
        if hasattr(self, 'baseline_series'):
            self.hrv_widget.chart().removeSeries(self.baseline_series)
            del self.baseline_series
        if hasattr(self, 'hr_baseline_series'):
            self.ibis_widget.plot.removeSeries(self.hr_baseline_series)
            del self.hr_baseline_series
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
        self.psd_button.setEnabled(False)
        self.psd_button.setText("PSD (no sensor)")
        self._main_plots_frozen = False
        self._all_plots_frozen = False
        self.ecg_window.set_stream_frozen(False)
        self.qtc_window.set_stream_frozen(False)
        self._apply_freeze_button_states()
        self.is_phase_active = False
        self._reset_signal_popup()
        self._flush_signal_fault_log("disconnect")
        self._set_signal_indicator("Disconnected", "gray")
        self.recording_statusbar.set_disconnected()
        self._start_connect_hints()
        self._update_session_actions()

    def toggle_ecg_window(self):
        if not self.ecg_window.isVisible():
            self.ecg_window.show()
            self.ecg_window.showNormal()
            self.ecg_window.raise_()
            self.ecg_window.activateWindow()
            self.ecg_window.start()
            self.ecg_window.set_stream_frozen(self._all_plots_frozen)
        elif self.ecg_window.isMinimized():
            self.ecg_window.showNormal()
            self.ecg_window.raise_()
            self.ecg_window.activateWindow()
        else:
            self.ecg_window.showMinimized()
        self._refresh_popup_control_labels()

    def _on_ecg_ready(self):
        self.ecg_button.setEnabled(True)
        self.qtc_button.setEnabled(True)
        self._refresh_popup_control_labels()

    def _on_ecg_window_closed(self):
        self._refresh_popup_control_labels()

    def toggle_qtc_window(self):
        if not self.qtc_window.isVisible():
            self.qtc_window.show()
            self.qtc_window.showNormal()
            self.qtc_window.raise_()
            self.qtc_window.activateWindow()
            self.qtc_window.start()
            self.qtc_window.set_stream_frozen(self._all_plots_frozen)
        elif self.qtc_window.isMinimized():
            self.qtc_window.showNormal()
            self.qtc_window.raise_()
            self.qtc_window.activateWindow()
        else:
            self.qtc_window.showMinimized()
        self._refresh_popup_control_labels()

    def _on_qtc_window_closed(self):
        self._refresh_popup_control_labels()

    def toggle_poincare_window(self):
        if not self.poincare_window.isVisible():
            self.poincare_window.show()
            self.poincare_window.showNormal()
            self.poincare_window.raise_()
            self.poincare_window.activateWindow()
        elif self.poincare_window.isMinimized():
            self.poincare_window.showNormal()
            self.poincare_window.raise_()
            self.poincare_window.activateWindow()
        else:
            self.poincare_window.showMinimized()
        self._refresh_popup_control_labels()

    def toggle_psd_window(self):
        if not self.psd_window.isVisible():
            self.psd_window.show()
            self.psd_window.showNormal()
            self.psd_window.raise_()
            self.psd_window.activateWindow()
        elif self.psd_window.isMinimized():
            self.psd_window.showNormal()
            self.psd_window.raise_()
            self.psd_window.activateWindow()
        else:
            self.psd_window.showMinimized()
        self._refresh_popup_control_labels()

    def _on_poincare_window_closed(self):
        self._refresh_popup_control_labels()

    def _on_psd_window_closed(self):
        self._refresh_popup_control_labels()

    def _on_verity_limited_support(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Polar Verity Sense — Limited Support")
        msg.setWindowModality(Qt.WindowModal)
        msg.setText(
            "This device does not provide beat-to-beat RR intervals required for "
            "HRV plotting, RMSSD, or spectral analysis.<br><br>"
            "Data will not be displayed. Use a <b>Polar H10</b> chest strap for full functionality."
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setDefaultButton(QMessageBox.Ok)
        msg.exec()

    @staticmethod
    def _popup_button_mode(window: QMainWindow) -> str:
        if not window.isVisible():
            return "open"
        if window.isMinimized():
            return "show"
        return "minimize"

    @staticmethod
    def _popup_button_text(label: str, mode: str) -> str:
        if mode == "show":
            return f"Show {label}"
        if mode == "minimize":
            return f"Minimize {label}"
        return f"Open {label}"

    def _refresh_popup_control_labels(self):
        if self.ecg_button.isEnabled():
            ecg_mode = self._popup_button_mode(self.ecg_window)
            self.ecg_button.setText(self._popup_button_text("ECG", ecg_mode))
        if self.qtc_button.isEnabled():
            qtc_mode = self._popup_button_mode(self.qtc_window)
            self.qtc_button.setText(self._popup_button_text("QTc", qtc_mode))
        if self.poincare_button.isEnabled():
            poincare_mode = self._popup_button_mode(self.poincare_window)
            self.poincare_button.setText(self._popup_button_text("Poincare", poincare_mode))
        if self.psd_button.isEnabled():
            psd_mode = self._popup_button_mode(self.psd_window)
            self.psd_button.setText(self._popup_button_text("PSD", psd_mode))

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
        msg.setDefaultButton(QMessageBox.Ok)
        msg.exec()

    def show_psd_info(self):
        parent = self.psd_window if self.psd_window.isVisible() else self
        msg = QMessageBox(parent)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("PSD & Vagal Resonance Help")
        msg.setWindowModality(Qt.WindowModal)
        msg.setText(
            "<b>What this shows</b><br>"
            "Power Spectral Density (PSD) of heart rate variability from the "
            "interpolated R-R interval stream. FFT-based (Welch method).<br><br>"
            "<b>Vagal Resonance (0.1 Hz)</b><br>"
            "The shaded band highlights 0.07–0.13 Hz (~6 breaths/min). A narrow, "
            "high-amplitude peak here indicates optimal vagal tone and baroreflex "
            "resonance—often associated with pelvic floor relaxation and coherent "
            "breathing.<br><br>"
            "<b>When will changes appear?</b><br>"
            "The plot uses roughly the last minute of heartbeats. Expect 1–2 minutes "
            "of steady breathing at a new rate before the peak shifts or stabilizes. "
            "Contributors: breathing consistency, stillness (reduces motion artifact), "
            "electrode contact, and physiological state (stress, relaxation, caffeine).<br><br>"
            "<b>Interaction</b><br>"
            "Drag to pan, mouse wheel or +/- buttons to zoom. Reset restores 0–0.5 Hz view."
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setDefaultButton(QMessageBox.Ok)
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

    def _update_psd(self, data: NamedSignal):
        if data.name != "psd":
            return
        if not isinstance(data.value, (list, tuple)) or len(data.value) < 2:
            return
        freqs, psd = data.value[0], data.value[1]
        if not freqs or not psd:
            return
        self.psd_window.update_from_psd(list(freqs), list(psd))

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

    @staticmethod
    def _make_disconnect_overlay(parent):
        lbl = QLabel("Signal interrupted\nData preserved", parent)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "background: rgba(128, 128, 128, 140); "
            "color: #fff; font-size: 14px; font-weight: bold; "
            "border-radius: 8px; padding: 16px;"
        )
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lbl.hide()
        return lbl

    def eventFilter(self, obj, event):
        if obj in (self.annotation, self.annotation.lineEdit()) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                QTimer.singleShot(0, self.emit_annotation)
                return False
        if obj in {self.ecg_window, self.qtc_window, self.poincare_window, self.psd_window} and event.type() in {
            QEvent.Type.WindowStateChange,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.Close,
        }:
            QTimer.singleShot(0, self._refresh_popup_control_labels)
        if event.type() == QEvent.Type.Resize:
            overlay = None
            disc_overlay = None
            if obj is self.ibis_widget:
                overlay = self._hr_overlay
                disc_overlay = self._disconnect_overlay_hr
            elif obj is self.hrv_widget:
                overlay = self._hrv_overlay
                disc_overlay = self._disconnect_overlay_hrv
            if overlay is not None:
                overlay.resize(obj.size())
            if disc_overlay is not None:
                disc_overlay.resize(obj.size())
        if (
            obj in {
                getattr(self, "_top_bar", None),
                getattr(self, "profile_header_label", None),
                getattr(self, "_disclaimer_link", None),
                getattr(self, "_debug_mode_badge", None),
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

    def _open_disclaimer_file(self, _link: str = ""):
        if not _CARD0_DISCLAIMER_PATH.exists():
            self.show_status(
                f"Disclaimer file not found: {_CARD0_DISCLAIMER_PATH}",
                print_to_terminal=False,
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(_CARD0_DISCLAIMER_PATH))):
            self.show_status("Unable to open disclaimer file.", print_to_terminal=False)

    def _start_connect_hints(self):
        has_plot_data = (
            (self.hr_trend_series.count() > 0 if hasattr(self, "hr_trend_series") else False)
            or (self.hrv_widget.time_series.count() > 0)
        )
        if has_plot_data:
            self._hr_overlay.hide()
            self._hrv_overlay.hide()
            if self._disconnect_overlay_hr:
                self._disconnect_overlay_hr.show()
                self._disconnect_overlay_hr.resize(self.ibis_widget.size())
            if self._disconnect_overlay_hrv:
                self._disconnect_overlay_hrv.show()
                self._disconnect_overlay_hrv.resize(self.hrv_widget.size())
        else:
            if self._disconnect_overlay_hr:
                self._disconnect_overlay_hr.hide()
            if self._disconnect_overlay_hrv:
                self._disconnect_overlay_hrv.hide()
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
        if self._disconnect_overlay_hr:
            self._disconnect_overlay_hr.hide()
        if self._disconnect_overlay_hrv:
            self._disconnect_overlay_hrv.hide()
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
        dlg = SettingsDialog(
            self.settings,
            parent=self,
            session_save_path_default=self.get_default_session_save_path(),
        )
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

    def _open_trends(self):
        if self._trends_window is None:
            is_admin = self._profile_store.profile_is_admin(self._session_profile_id)
            self._trends_window = TrendsWindow(
                self._profile_store,
                self._session_profile_id,
                is_admin=is_admin,
                parent=self,
            )
        self._trends_window.set_active_profile(self._session_profile_id)
        self._trends_window.show()
        self._trends_window.showNormal()
        self._trends_window.raise_()
        self._trends_window.activateWindow()

    def _record_session_trend_from_current_state(self):
        """Store average session values for trends. Call at end of session (finalize or abandon)."""
        if self._session_bundle is None or self._session_profile_id is None:
            return
        data = self._build_report_data(report_stage="draft")
        hr_vals = [float(v) for v in (data.get("hr_values") or []) if v is not None]
        rmssd_vals = [float(v) for v in (data.get("rmssd_values") or []) if v is not None]
        hrv_vals = [float(v) for v in (data.get("hrv_values") or []) if v is not None]
        qtc_data = data.get("qtc") or {}
        avg_hr = float(statistics.mean(hr_vals)) if hr_vals else data.get("last_hr")
        avg_rmssd = float(statistics.mean(rmssd_vals)) if rmssd_vals else data.get("last_rmssd")
        avg_sdnn = float(statistics.mean(hrv_vals)) if hrv_vals else None
        if avg_hr is not None:
            try:
                avg_hr = float(avg_hr)
            except (TypeError, ValueError):
                avg_hr = None
        if avg_rmssd is not None:
            try:
                avg_rmssd = float(avg_rmssd)
            except (TypeError, ValueError):
                avg_rmssd = None
        qtc_ms = qtc_data.get("session_value_ms") if isinstance(qtc_data, dict) else None
        if qtc_ms is not None:
            try:
                qtc_ms = float(qtc_ms)
            except (TypeError, ValueError):
                qtc_ms = None
        ended = data.get("session_end") or datetime.now()
        if not isinstance(ended, datetime):
            ended = datetime.now()
        self._profile_store.record_session_trend(
            profile_name=self._session_profile_id,
            session_id=self._session_bundle.session_id,
            ended_at=ended,
            avg_hr=avg_hr,
            avg_rmssd=avg_rmssd,
            avg_sdnn=avg_sdnn,
            qtc_ms=qtc_ms,
            baseline_hr=self.baseline_hr,
            baseline_rmssd=self.baseline_rmssd,
        )

    def _open_profile_manager(self):
        if self._session_state == "recording":
            self.show_status("Profile changes are disabled during an active recording.")
            return
        try:
            is_admin = self._profile_store.profile_is_admin(self._session_profile_id)
            dlg = ProfileManagerDialog(
                store=self._profile_store,
                active_profile=self._session_profile_id,
                is_admin=is_admin,
                parent=None,
            )
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
            dlg.exec()
            dlg.deleteLater()
            latest_active = self._profile_store.get_last_active_profile()
            if latest_active and latest_active.casefold() != self._session_profile_id.casefold():
                self._set_active_profile(latest_active, announce=True)
            QTimer.singleShot(150, self._refocus_after_profile_dialog)
        except Exception as exc:
            self.show_status(f"Profile Manager error: {exc}")
            if self.settings.DEBUG:
                import traceback
                traceback.print_exc()

    def _refocus_after_profile_dialog(self):
        self.setEnabled(True)
        self.activateWindow()
        self.raise_()
        self.setFocus()

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

    def emit_annotation(self):
        if self._session_state != "recording":
            self.show_status(self._annotation_disabled_placeholder)
            return
        text = self.annotation.currentText().strip()
        if not text:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self._session_annotations.append((ts, text))
        self.signals.annotation.emit(NamedSignal("Annotation", text))
        self.settings.add_custom_annotation(text)
        self._refresh_annotation_list()
        self.annotation.setCurrentText("")

    @Slot(object)
    def _on_ecg_cursor_measurement(self, payload: object):
        if not isinstance(payload, dict):
            return
        try:
            dt_ms = float(payload.get("dt_ms"))
            a_t = float(payload.get("a_t_sec"))
            b_t = float(payload.get("b_t_sec"))
        except (TypeError, ValueError):
            return
        interval_type = payload.get("interval_type", "").strip() or "R-R"
        text = f"ECG cursor Δt={dt_ms:.1f} ms ({interval_type}) (A={a_t:.3f}s, B={b_t:.3f}s)"
        if self._session_state == "recording":
            ts = datetime.now().strftime("%H:%M:%S")
            self._session_annotations.append((ts, text))
            self.signals.annotation.emit(NamedSignal("Annotation", text))
        self.show_status(text)

    @Slot(object)
    def _on_ecg_image_captured(self, pixmap: object):
        """Save ECG plot snapshot to session folder."""
        if self._session_bundle is None:
            self.show_status("No active session — cannot save ECG image.")
            return
        if pixmap is None or (hasattr(pixmap, "isNull") and pixmap.isNull()):
            self.show_status("ECG image capture failed.")
            return
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self._session_bundle.session_dir / f"ecg_snapshot_{timestamp}.png"
            ok = pixmap.save(str(path))
            if ok:
                self.show_status(f"ECG snapshot saved: {path.name}")
            else:
                self.show_status("Failed to save ECG snapshot.")
        except Exception as exc:
            self.show_status(f"ECG snapshot save failed: {exc}")

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
        self._hr_ewma_post_warmup = False
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_floor = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_floor = None
        self._sdnn_axis_ceiling = None
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._rmssd_smooth_post_warmup = False
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

    @staticmethod
    def _series_points(series: QLineSeries) -> list[QPointF]:
        if hasattr(series, "pointsVector"):
            return list(series.pointsVector())
        return list(series.points())

    def _visible_series_values(self, series: QLineSeries, x_min: float, x_max: float) -> list[float]:
        vals: list[float] = []
        for p in self._series_points(series):
            x = float(p.x())
            if x_min <= x <= x_max:
                vals.append(float(p.y()))
        return vals

    def _prune_series_before(self, series: QLineSeries, min_x: float) -> None:
        count = series.count()
        if count <= self._series_prune_stride:
            return
        if float(series.at(0).x()) >= min_x:
            return
        max_drop = max(0, count - 2)
        drop = 0
        while drop < max_drop and float(series.at(drop).x()) < min_x:
            drop += 1
        if drop > 0:
            series.removePoints(0, drop)

    def _prune_main_chart_series(self, current_x: float) -> None:
        prune_before = current_x - (self._main_plot_visible_sec + self._main_plot_guard_sec)
        if prune_before <= 0:
            return
        self._prune_series_before(self.hr_trend_series, prune_before)
        self._prune_series_before(self.hrv_widget.time_series, prune_before)
        self._prune_series_before(self.sdnn_series, prune_before)
        # Remove segments fully outside visible window
        for segments, chart in [
            (self._hr_segments, self.ibis_widget.plot),
            (self._rmssd_segments, self.hrv_widget.chart()),
            (self._sdnn_segments, self.hrv_widget.chart()),
        ]:
            while segments and segments[0].count() > 0:
                last_x = float(segments[0].at(segments[0].count() - 1).x())
                if last_x >= prune_before:
                    break
                chart.removeSeries(segments.pop(0))

    def reset_y_axes(self):
        x_min = float(self.ibis_widget.x_axis.min())
        x_max = float(self.ibis_widget.x_axis.max())

        # Heart-rate plot: fit to currently visible points with headroom.
        hr_vals = self._visible_series_values(self.hr_trend_series, x_min, x_max)
        if hr_vals:
            hr_lo = max(30.0, min(hr_vals))
            hr_hi = min(220.0, max(hr_vals))
            data_span = hr_hi - hr_lo
            span = max(12.0, data_span)
            pad = max(2.0, span * 0.15)
            hr_lo = max(30.0, hr_lo - pad)
            hr_hi = min(220.0, hr_hi + pad)
        else:
            hr_ref = self.baseline_hr
            if hr_ref is None and self._session_hr_values:
                hr_ref = self._session_hr_values[-1]
            if hr_ref is None:
                hr_ref = 80.0
            half_span = max(20.0, hr_ref * 0.5)
            hr_lo = max(30.0, hr_ref - half_span)
            hr_hi = min(220.0, hr_ref + half_span)
        # Guardrail: never hide baseline HR reference after a manual Y-axis reset.
        if self.baseline_hr is not None:
            hr_lo = min(hr_lo, float(self.baseline_hr) - 2.0)
            hr_hi = max(hr_hi, float(self.baseline_hr) + 2.0)
            hr_lo = max(30.0, hr_lo)
            hr_hi = min(220.0, hr_hi)
        if hr_hi - hr_lo < 12.0:
            center = (hr_hi + hr_lo) / 2.0
            hr_lo = max(30.0, center - 6.0)
            hr_hi = min(220.0, center + 6.0)
        self._hr_axis_floor = int(hr_lo)
        self._hr_axis_ceiling = int(hr_hi)
        self.ibis_widget.y_axis.setRange(self._hr_axis_floor, self._hr_axis_ceiling)
        self.hr_y_axis_right.setRange(self._hr_axis_floor, self._hr_axis_ceiling)

        # RMSSD: baseline-centered range like HR plot.
        hrv_x_min = float(self.hrv_widget.x_axis.min())
        hrv_x_max = float(self.hrv_widget.x_axis.max())
        rmssd_vals = self._visible_series_values(self.hrv_widget.time_series, hrv_x_min, hrv_x_max)
        if rmssd_vals:
            rmssd_lo = max(0.0, min(rmssd_vals))
            rmssd_hi = max(rmssd_vals)
            data_span = rmssd_hi - rmssd_lo
            span = max(6.0, data_span)
            pad = max(1.0, span * 0.15)
            hrv_lo = max(0.0, rmssd_lo - pad)
            hrv_hi = rmssd_hi + pad
        else:
            rmssd_ref = self.baseline_rmssd
            if rmssd_ref is None and self._session_rmssd_values:
                rmssd_ref = self._session_rmssd_values[-1]
            if rmssd_ref is None:
                rmssd_ref = 20.0
            half_span = max(15.0, rmssd_ref * 0.5)
            hrv_lo = max(0.0, rmssd_ref - half_span)
            hrv_hi = rmssd_ref + half_span
        if self.baseline_rmssd is not None:
            hrv_lo = min(hrv_lo, float(self.baseline_rmssd) - 2.0)
            hrv_hi = max(hrv_hi, float(self.baseline_rmssd) + 2.0)
            hrv_lo = max(0.0, hrv_lo)
        if hrv_hi - hrv_lo < 6.0:
            center = (hrv_hi + hrv_lo) / 2.0
            hrv_lo = max(0.0, center - 3.0)
            hrv_hi = center + 3.0
        self._hrv_axis_ceiling = int(-(-hrv_hi // 5)) * 5
        self._hrv_axis_floor = max(0, int(hrv_lo // 5) * 5)
        self.hrv_widget.y_axis.setRange(self._hrv_axis_floor, self._hrv_axis_ceiling)
        self.hrv_widget.chart().update()

        # SDNN: baseline-centered range.
        sdnn_vals = self._visible_series_values(self.sdnn_series, hrv_x_min, hrv_x_max)
        if sdnn_vals:
            sdnn_lo = max(0.0, min(sdnn_vals))
            sdnn_hi = max(sdnn_vals)
            data_span = sdnn_hi - sdnn_lo
            span = max(4.0, data_span)
            pad = max(1.0, span * 0.15)
            sdnn_floor = max(0.0, sdnn_lo - pad)
            sdnn_ceil = sdnn_hi + pad
        else:
            sdnn_ref = self._sdnn_smooth_buf[-1] if self._sdnn_smooth_buf else 30.0
            half_span = max(10.0, sdnn_ref * 0.5)
            sdnn_floor = max(0.0, sdnn_ref - half_span)
            sdnn_ceil = sdnn_ref + half_span
        if sdnn_ceil - sdnn_floor < 4.0:
            center = (sdnn_ceil + sdnn_floor) / 2.0
            sdnn_floor = max(0.0, center - 2.0)
            sdnn_ceil = center + 2.0
        self._sdnn_axis_ceiling = int(-(-sdnn_ceil // 5)) * 5
        self._sdnn_axis_floor = max(0, int(sdnn_floor // 5) * 5)
        self.hrv_y_axis_right.setRange(self._sdnn_axis_floor, self._sdnn_axis_ceiling)
        self.show_status("Y-axes reset to visible data range.")

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

    def _emit_ibi_diagnostics(self):
        if not self.settings.DEBUG:
            return
        if not self._is_sensor_connected():
            return
        snap = self.model.ibi_diagnostics_snapshot()
        beats = snap["beats_received"]
        updates = snap["buffer_updates"]
        delta = snap["delta"]
        beats_inc = beats - int(self._ibi_diag_last_counts.get("beats_received", 0))
        updates_inc = updates - int(self._ibi_diag_last_counts.get("buffer_updates", 0))
        self._ibi_diag_last_counts = {
            "beats_received": beats,
            "buffer_updates": updates,
        }
        if delta != 0:
            print(
                "[IBI-DIAG] WARNING "
                f"total beats={beats} updates={updates} delta={delta} "
                f"last10s beats={beats_inc} updates={updates_inc}"
            )
        else:
            print(
                "[IBI-DIAG] OK "
                f"total beats={beats} updates={updates} delta={delta} "
                f"last10s beats={beats_inc} updates={updates_inc}"
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
        if self.settings.DEBUG:
            if not self._ibi_diag_timer.isActive():
                self._ibi_diag_timer.start()
        else:
            self._ibi_diag_timer.stop()
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
            # During fault, do not append new points — preserves chart with break until recovery.
            if self._fault_active:
                return
            
            raw_y = float(hrv_data.value[1][-1])
            y = max(0, min(raw_y, 250)) 

            if self.start_time is None:
                return

            now = time.time()
            elapsed = now - self.start_time
            x = elapsed - self._plot_start_delay_seconds
            plot_gate_open = self._main_plot_gate_open(now) and x >= 0
            total_calibration_time = self.settings.SETTLING_DURATION + self.settings.BASELINE_DURATION

            # Add smoothed RMSSD to Chart
            if elapsed >= PLOT_WARMUP_SECONDS and not self._rmssd_smooth_post_warmup:
                self._rmssd_smooth_post_warmup = True
                self._rmssd_smooth_buf.clear()
                self._sdnn_smooth_buf.clear()
            ibis = list(self.model.ibis_buffer)
            cur_hr = 60000.0 / ibis[-1] if ibis and ibis[-1] > 0 else 70
            smooth_n = max(5, round(cur_hr / 60 * self.settings.SMOOTH_SECONDS))

            self._rmssd_smooth_buf.append(y)
            while len(self._rmssd_smooth_buf) > smooth_n:
                self._rmssd_smooth_buf.pop(0)
            smoothed_rmssd = sum(self._rmssd_smooth_buf) / len(self._rmssd_smooth_buf)

            # Compute and plot SDNN from IBI buffer
            sdnn = None
            if len(ibis) >= 3:
                sdnn = statistics.stdev(ibis[-min(30, len(ibis)):])
                self._sdnn_smooth_buf.append(sdnn)
                while len(self._sdnn_smooth_buf) > smooth_n:
                    self._sdnn_smooth_buf.pop(0)

            if plot_gate_open:
                self._session_rmssd_values.append(smoothed_rmssd)
                self._session_rmssd_times.append(x)
                if not self._main_plots_frozen:
                    self.hrv_widget.time_series.append(x, smoothed_rmssd)
                if sdnn is not None and len(self._sdnn_smooth_buf) > 0:
                    smoothed_sdnn = sum(self._sdnn_smooth_buf) / len(self._sdnn_smooth_buf)
                    self._session_hrv_values.append(smoothed_sdnn)
                    self._session_hrv_times.append(x)
                    self.sdnn_label.setText(f"SDNN: {sdnn:6.2f} ms")
                    if not self._main_plots_frozen:
                        self.sdnn_series.append(x, smoothed_sdnn)
                if not self._main_plots_frozen and self.hrv_widget.time_series.count() % self._series_prune_stride == 0:
                    self._prune_main_chart_series(x)

            # Expand-only Y-axes
            if self._hrv_axis_ceiling is None:
                self._hrv_axis_ceiling = max(10, int(-(-smoothed_rmssd * 1.5 // 5)) * 5)
            rmssd_padded = int(-(-smoothed_rmssd * 1.3 // 5)) * 5
            if rmssd_padded > self._hrv_axis_ceiling:
                self._hrv_axis_ceiling = rmssd_padded
            if not self._main_plots_frozen:
                hrv_floor = 0 if self._hrv_axis_floor is None else self._hrv_axis_floor
                self.hrv_widget.y_axis.setRange(hrv_floor, self._hrv_axis_ceiling)

            if self._sdnn_axis_ceiling is None:
                self._sdnn_axis_ceiling = 50
            if len(self._sdnn_smooth_buf) > 0:
                sdnn_padded = int(-(-self._sdnn_smooth_buf[-1] * 1.3 // 5)) * 5
                if sdnn_padded > self._sdnn_axis_ceiling:
                    self._sdnn_axis_ceiling = sdnn_padded
            if not self._main_plots_frozen:
                sdnn_floor = 0 if self._sdnn_axis_floor is None else self._sdnn_axis_floor
                self.hrv_y_axis_right.setRange(sdnn_floor, self._sdnn_axis_ceiling)

            # --- CONTINUOUS PHASE ENGINE ---
            
            # PHASE 1: BASELINE COLLECTION (exclude warmup to avoid stabilization artifacts)
            # Only use RMSSD values below noisy threshold; high RMSSD = erratic RR = poor signal.
            if (
                elapsed >= PLOT_WARMUP_SECONDS
                and elapsed < total_calibration_time
            ):
                if y <= RMSSD_NOISY_MS:
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
        # Do not overwrite RMSSD axis when user has reset Y axes (data-driven range)
        if self._hrv_axis_floor is not None:
            return
        self.hrv_widget.y_axis.setRange(0, target.value)

    def _sync_aux_windows_to_main_xrange(self, x_lo: float, x_hi: float):
        self.ecg_window.set_synced_xrange(x_lo, x_hi)
        self.qtc_window.set_synced_xrange(x_lo, x_hi)

    def _apply_freeze_button_states(self):
        connected = self._is_sensor_connected()
        self.freeze_two_main_plots_button.setText(
            "Resume Two Main Plots"
            if self._main_plots_frozen
            else "Freeze Two Main Plots"
        )
        self.freeze_all_button.setText(
            "Resume All" if self._all_plots_frozen else "Freeze All"
        )
        self.freeze_two_main_plots_button.setEnabled(
            connected and not self._all_plots_frozen
        )
        self.freeze_all_button.setEnabled(connected)
        self.reset_axes_button.setEnabled(connected)

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
        self._profile_store.set_profile_pref(
            self._session_profile_id, "breathing_rate", str(int(value))
        )

    def show_recording_status(self, status: int):
        self.recording_statusbar.setRange(0, max(status, 1))

    def _copy_text_to_clipboard(self, text: str) -> bool:
        try:
            clipboard = QApplication.clipboard()
            if clipboard is None:
                return False
            clipboard.setText(text)
            return True
        except Exception:
            return False

    def show_status(self, status: str, print_to_terminal=True):
        report_file_prefix = "Saved report file: "
        if status.startswith(report_file_prefix):
            report_path = status[len(report_file_prefix):].strip()
            if self._copy_text_to_clipboard(report_path):
                status = f"Report path saved to clipboard: {report_path}"

        recording_path = None
        recording_file_prefix = "Saved recording file: "
        recording_saved_prefix = "Saved recording at "
        if status.startswith(recording_file_prefix):
            recording_path = status[len(recording_file_prefix):].strip()
        elif status.startswith(recording_saved_prefix):
            # Backward-compatible parsing for legacy status text.
            recording_path = status[len(recording_saved_prefix):].rstrip(".").strip()

        if recording_path:
            if self._session_bundle is not None and Path(recording_path) == self._session_bundle.session_dir:
                recording_path = str(self._session_bundle.csv_path)
            if self._copy_text_to_clipboard(recording_path):
                status = f"Recording path saved to clipboard: {recording_path}"

        if "Connected" in status and "Disconnecting" not in status:
            self._suppress_comm_error_popups = False
            self._connect_attempt_timer.stop()
            self._stop_connect_hints()
            self.is_phase_active = False
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.scan_button.setEnabled(False)
            if self.address_menu.currentText():
                parts = self.address_menu.currentText().split(",")
                if len(parts) >= 2:
                    name, addr = parts[0].strip(), parts[1].strip()
                    if "verity" not in name.lower():
                        _save_last_sensor(name, addr)
            self._auto_start_recording()
        elif "error" in status.lower() or "Disconnecting" in status:
            # If connect failed or link dropped, unblock reconnect immediately.
            self._connect_attempt_timer.stop()
            self._apply_connect_ready_state()
            self.disconnect_button.setEnabled(False)
            self.scan_button.setEnabled(True)
            self._set_signal_indicator("Disconnected", "gray")
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
        if self._suppress_comm_error_popups:
            return
        if self._signal_popup_shown:
            return
        self._signal_popup_shown = True
        if not self._is_application_active():
            self._pending_signal_popup_reason = reason
            self.statusbar.showMessage(f"Signal quality issue detected: {reason}", 8000)
            QApplication.alert(self, 3000)
            return
        self._fire_signal_popup(reason)

    def _is_application_active(self) -> bool:
        app = QApplication.instance()
        if app is None:
            return True
        return app.applicationState() == Qt.ApplicationState.ApplicationActive

    def _on_application_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            return
        if self._suppress_comm_error_popups:
            self._pending_signal_popup_reason = None
            return
        if self._signal_popup_shown and self._pending_signal_popup_reason:
            reason = self._pending_signal_popup_reason
            self._pending_signal_popup_reason = None
            self._fire_signal_popup(reason)

    def _on_signal_popup_closed(self, _result: int):
        self._signal_popup_widget = None

    def _fire_signal_popup(self, reason: str):
        if self._signal_popup_widget is not None:
            try:
                self._signal_popup_widget.close()
            except Exception:
                pass
            self._signal_popup_widget = None
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
        msg.setDefaultButton(QMessageBox.Ok)
        # Keep warning reachable when plot windows are pinned.
        msg.setWindowModality(Qt.NonModal)
        msg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        msg.finished.connect(self._on_signal_popup_closed)
        self._signal_popup_widget = msg
        msg.open()
        msg.raise_()
        msg.activateWindow()
        if reason in _SIGNAL_POPUP_AUTO_DISMISS_REASONS:
            QTimer.singleShot(SIGNAL_POPUP_AUTO_DISMISS_MS, msg.close)

    def _on_rmssd_degraded(self, rmssd_val: float | None = None):
        self._signal_degrade_count += 1
        if not self._signal_popup_shown and self._signal_degrade_count >= SIGNAL_DEGRADE_POPUP_COUNT:
            self._signal_popup_shown = True
            self._log_signal_fault(
                "RMSSD_POPUP", "Poor signal — electrodes may be dry",
                rmssd_ms=round(rmssd_val, 2) if rmssd_val is not None else None,
                consecutive_breaches=self._signal_degrade_count,
                threshold_noisy=RMSSD_NOISY_MS,
                threshold_poor=RMSSD_POOR_MS,
            )
            self._fire_signal_popup("Poor signal \u2014 electrodes may be dry")

    def _reset_signal_popup(self):
        self._signal_popup_shown = False
        self._signal_degrade_count = 0
        self._pending_signal_popup_reason = None
        if self._signal_popup_widget is not None:
            try:
                self._signal_popup_widget.close()
            except Exception:
                pass
            self._signal_popup_widget = None

    def _handle_stream_reset(self, clear_series: bool = True):
        self.model.clear_buffers()
        self._session_qtc_payload = default_qtc_payload()
        self._last_qtc_diag_logged = ()
        self._arm_main_plot_warmup(clear_series=clear_series)
        self.qtc_window.clear()
        if self.qtc_button.isEnabled() and not self.qtc_window.isVisible():
            self.qtc_button.setText("QTc (warming up...)")
        # Stream resets should clear locked/baseline phase banners immediately.
        self.is_phase_active = False
        if self._is_sensor_connected():
            self.recording_statusbar.set_idle("Waiting for ECG data...")
        else:
            self.recording_statusbar.set_disconnected()

    def _arm_main_plot_warmup(self, clear_series: bool) -> None:
        self._main_plot_warmup_until = time.time() + float(self._plot_start_delay_seconds)
        if clear_series:
            self.hr_trend_series.clear()
            self.sdnn_series.clear()
            self.hrv_widget.time_series.clear()

    def _main_plot_gate_open(self, now: float) -> bool:
        return self._main_plot_warmup_until is None or now >= self._main_plot_warmup_until

    def _check_data_timeout(self):
        if self._last_data_time is None:
            return
        silence = time.time() - self._last_data_time
        if silence >= self.settings.DATA_TIMEOUT_SECONDS and not self._fault_active:
            self._fault_active = True
            self._consecutive_good = 0
            self._record_disconnect_start("No data (timeout)")
            self._update_disconnect_overlay(True)
            self._set_signal_indicator("LOST (No data)", "red")
            self._log_signal_fault(
                "WATCHDOG_LOST", "No data received",
                silence_sec=round(silence, 1),
                threshold_sec=self.settings.DATA_TIMEOUT_SECONDS,
            )
            self._show_signal_degraded_popup("No data received")
            self._handle_stream_reset(clear_series=False)

    def _in_settling(self):
        return (self.start_time is not None
                and (time.time() - self.start_time) < self.settings.SETTLING_DURATION)

    def _set_signal_indicator(self, text: str, color: str):
        self.health_indicator.setStyleSheet("color: %s; font-size: 18px;" % color)
        self.health_label.setText("Signal: %s" % text)

    def _update_disconnect_overlay(self, show: bool):
        """Show or hide gray disconnect overlay when we have plot data."""
        has_data = (
            self.hr_trend_series.count() > 0
            or self.hrv_widget.time_series.count() > 0
        )
        if not has_data or not show:
            if self._disconnect_overlay_hr:
                self._disconnect_overlay_hr.hide()
            if self._disconnect_overlay_hrv:
                self._disconnect_overlay_hrv.hide()
            return
        if self._disconnect_overlay_hr and self.ibis_widget.isVisible():
            self._disconnect_overlay_hr.show()
            self._disconnect_overlay_hr.resize(self.ibis_widget.size())
        if self._disconnect_overlay_hrv and self.hrv_widget.isVisible():
            self._disconnect_overlay_hrv.show()
            self._disconnect_overlay_hrv.resize(self.hrv_widget.size())

    def _start_new_plot_segment(self):
        """Create explicit timeline gap: freeze current series as segment, continue with cleared active series."""
        def freeze_segment(series: QLineSeries, segments: list, chart, x_axis, y_axis):
            if series.count() == 0:
                return
            seg = QLineSeries()
            seg.setPen(series.pen())
            seg.setName(series.name())
            for i in range(series.count()):
                p = series.at(i)
                seg.append(p.x(), p.y())
            chart.addSeries(seg)
            seg.attachAxis(x_axis)
            seg.attachAxis(y_axis)
            segments.append(seg)
            series.clear()

        freeze_segment(
            self.hr_trend_series, self._hr_segments, self.ibis_widget.plot,
            self.ibis_widget.x_axis, self.ibis_widget.y_axis,
        )
        freeze_segment(
            self.hrv_widget.time_series, self._rmssd_segments, self.hrv_widget.chart(),
            self.hrv_widget.x_axis, self.hrv_widget.y_axis,
        )
        freeze_segment(
            self.sdnn_series, self._sdnn_segments, self.hrv_widget.chart(),
            self.hrv_widget.x_axis, self.hrv_y_axis_right,
        )

    def _record_disconnect_start(self, reason: str):
        """Record start of disconnect interval; used for manifest/CSV/report."""
        if self._current_disconnect_start is not None:
            return  # already recording
        self._current_disconnect_start = time.time()
        self._disconnect_reason = reason

    def _record_disconnect_end(self):
        """Complete current disconnect interval, emit annotation, add to manifest data."""
        if self._current_disconnect_start is None:
            return
        end_ts = time.time()
        duration_sec = round(end_ts - self._current_disconnect_start, 1)
        rec = {
            "start_ts": self._current_disconnect_start,
            "end_ts": end_ts,
            "reason": self._disconnect_reason,
            "duration_sec": duration_sec,
        }
        self._disconnect_intervals.append(rec)
        self._current_disconnect_start = None
        # Emit as session annotation for CSV and include in report (only when recording)
        if self._session_state == "recording":
            ts_str = datetime.fromtimestamp(end_ts).strftime("%H:%M:%S")
            text = f"[System] {self._disconnect_reason} ({duration_sec}s)"
            self._session_annotations.append((ts_str, text))
            self.signals.annotation.emit(NamedSignal("Annotation", text))

    @Slot(int)
    def _update_battery_display(self, level: int):
        """Update battery label: numerical percentage with color based on level."""
        if level < 0:
            self.battery_label.setText("\u2014")
            self.battery_label.setStyleSheet(
                "font-size: 10px; color: #666; background: #e0e0e0; "
                "border-radius: 3px; padding: 1px 4px;"
            )
            return
        self.battery_label.setText(f"{level}%")
        if level >= 50:
            self.battery_label.setStyleSheet(
                "font-size: 10px; color: black; font-weight: 700; "
                "background: #a5d6a7; border-radius: 3px; padding: 1px 4px;"
            )
        elif level >= 20:
            self.battery_label.setStyleSheet(
                "font-size: 10px; color: black; font-weight: 700; "
                "background: #ffcc80; border-radius: 3px; padding: 1px 4px;"
            )
        else:
            self.battery_label.setStyleSheet(
                "font-size: 10px; color: black; font-weight: 700; "
                "background: #ef9a9a; border-radius: 3px; padding: 1px 4px;"
            )

    def _log_signal_fault(self, fault_type: str, reason: str, **ctx):
        """Accumulate fault in memory; flushed to disk on disconnect or exit."""
        ts = datetime.now().isoformat(timespec="milliseconds")
        record = {"ts": ts, "fault_type": fault_type, "reason": reason, **ctx}
        self._signal_fault_buffer.append(record)
        self._signal_fault_counts[fault_type] = self._signal_fault_counts.get(fault_type, 0) + 1

    def _get_signal_fault_recommendation(self) -> str:
        """Return recommendation string based on dominant fault pattern."""
        if not self._signal_fault_counts:
            return ""
        sorted_types = sorted(
            self._signal_fault_counts.items(),
            key=lambda x: -x[1],
        )
        top = sorted_types[0][0] if sorted_types else ""
        second = sorted_types[1][0] if len(sorted_types) > 1 else ""
        recs = []
        if top in ("L1_DROPOUT", "WATCHDOG_LOST"):
            recs.append("Increase Data Timeout (Settings > Signal Quality)")
            if top == "L1_DROPOUT":
                recs.append("Increase Dropout IBI Threshold (Advanced)")
        if "L2_NOISE_HIGH" in (top, second) or "L2_NOISE" == top:
            recs.append("Increase Noise Ceiling IBI (Advanced)")
        if "L2_NOISE_LOW" in (top, second):
            recs.append("Ensure electrodes wet and strap snug; consider Noise Floor IBI (Advanced)")
        if top == "L3_ERRATIC":
            recs.append("Increase Deviation Threshold and/or Deviation Window (Signal Quality)")
        if top == "RMSSD_POPUP":
            recs.append("Wet strap and ensure snug fit; movement or dry electrodes")
        if not recs:
            recs.append("Review Settings > Signal Quality and Advanced; ensure strap fit and electrode contact.")
        return "; ".join(dict.fromkeys(recs))

    def _get_signal_fault_action(self) -> str:
        """Return specific actionable guidance (from X to Y) based on fault data and current settings."""
        if not self._signal_fault_buffer or not self._signal_fault_counts:
            return ""
        sorted_types = sorted(
            self._signal_fault_counts.items(),
            key=lambda x: -x[1],
        )
        top = sorted_types[0][0] if sorted_types else ""
        records = [r for r in self._signal_fault_buffer if r.get("fault_type") == top]
        if top == "L3_ERRATIC" and records:
            current = self.settings.DEVIATION_THRESHOLD
            max_dev = max(r.get("deviation_pct", 0) for r in records if "deviation_pct" in r)
            if max_dev >= 0:
                suggested = max(0.20, min(0.35, (max_dev + 8) / 100))
                return f"Raise Deviation Threshold from {current:.2f} to {suggested:.2f} (Settings > Signal Quality)"
        if top == "L1_DROPOUT":
            current = self.settings.DROPOUT_IBI_MS
            suggested = min(10000, current + 1000)
            return f"Raise Dropout IBI Threshold from {current} to {suggested} ms (Settings > Advanced)"
        if top == "WATCHDOG_LOST" and records:
            current = self.settings.DATA_TIMEOUT_SECONDS
            suggested = min(30.0, current + 5.0)
            return f"Raise Data Timeout from {current} to {suggested} s (Settings > Signal Quality)"
        if top == "L2_NOISE_HIGH" and records:
            max_ibi = max(r.get("last_ibi_ms", 0) for r in records if "last_ibi_ms" in r)
            current = self.settings.NOISE_IBI_HIGH_MS
            suggested = min(5000, max(max_ibi + 300, current + 500))
            return f"Raise Noise Ceiling IBI from {current} to {suggested} ms (Settings > Advanced)"
        if top == "L2_NOISE_LOW" and records:
            min_ibi = min(r.get("last_ibi_ms", 500) for r in records if "last_ibi_ms" in r)
            current = self.settings.NOISE_IBI_LOW_MS
            suggested = max(150, min(min_ibi - 50, current - 50))
            return f"Lower Noise Floor IBI from {current} to {suggested} ms (Settings > Advanced); ensure strap is snug"
        if top == "RMSSD_POPUP":
            return "Wet strap and ensure snug fit; check electrode contact"
        return ""

    def _flush_signal_fault_log(self, end_reason: str) -> None:
        """Write in-memory fault log to disk; clear buffer; optionally prompt in DEBUG."""
        if not self._signal_fault_buffer:
            return
        log_path = Path.home() / "Hertz-and-Hearts" / "signal_diag.log"
        try:
            log_dir = log_path.parent
            log_dir.mkdir(parents=True, exist_ok=True)
            profile = getattr(self, "_session_profile_id", "Admin") or "Admin"
            ts = datetime.now().isoformat(timespec="seconds")
            lines = [f"--- {ts} | {profile} | Session ended ({end_reason}) ---\n"]
            for r in self._signal_fault_buffer:
                ctx = {k: v for k, v in r.items() if k not in ("ts", "fault_type", "reason")}
                ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items())
                line = f"{r['ts']} FAULT={r['fault_type']} reason={r['reason']!r} {ctx_str}".strip() + "\n"
                lines.append(line)
            counts = " ".join(f"{k}={v}" for k, v in sorted(self._signal_fault_counts.items()))
            lines.append(f"--- SUMMARY: {counts} ---\n")
            rec = self._get_signal_fault_recommendation()
            if rec:
                lines.append(f"RECOMMEND: {rec}\n")
            action = self._get_signal_fault_action()
            if action:
                lines.append(f"ACTION: {action}\n")
            with log_path.open("a", encoding="utf-8", errors="ignore") as fh:
                fh.writelines(lines)
        except Exception:
            pass
        finally:
            self._signal_fault_buffer.clear()
            self._signal_fault_counts.clear()
        if self.settings.DEBUG:
            reply = QMessageBox.question(
                self,
                "Comm Diagnostics",
                "Comm errors were detected. Review log file?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                try:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))
                except Exception:
                    pass

    def update_ui_labels(self, data: NamedSignal):
        # 1. RAW BEAT DATA (Heart Rate & Instant Faults)
        if data.name == "ibis":
            # First data after button-disconnect reconnect: complete interval, create gap
            if self._resuming_after_button_disconnect:
                self._resuming_after_button_disconnect = False
                self._record_disconnect_end()
                self._start_new_plot_segment()
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
                    self._record_disconnect_start("Signal dropout")
                    self._update_disconnect_overlay(True)
                    self._set_signal_indicator("FAULT: Bad comm", "red")
                    recent = list(data.value[1])[-10:]
                    self._log_signal_fault(
                        "L1_DROPOUT", "Total signal dropout",
                        last_ibi_ms=int(last_ibi_ms),
                        threshold=self.settings.DROPOUT_IBI_MS,
                        recent_ibis=recent,
                    )
                    self._show_signal_degraded_popup("Total signal dropout")
                    self._handle_stream_reset(clear_series=False)
                    return

                # LEVEL 2 FAULT: Hard IBI limits
                if last_ibi_ms > self.settings.NOISE_IBI_HIGH_MS or last_ibi_ms < self.settings.NOISE_IBI_LOW_MS:
                    self._fault_active = True
                    self._consecutive_good = 0
                    self._record_disconnect_start("Signal noise")
                    self._update_disconnect_overlay(True)
                    self._set_signal_indicator("DROP/NOISE", "red")
                    fault_sub = "L2_NOISE_HIGH" if last_ibi_ms > self.settings.NOISE_IBI_HIGH_MS else "L2_NOISE_LOW"
                    recent = list(data.value[1])[-10:]
                    self._log_signal_fault(
                        fault_sub, "Signal dropout or noise",
                        last_ibi_ms=int(last_ibi_ms),
                        low_ms=self.settings.NOISE_IBI_LOW_MS,
                        high_ms=self.settings.NOISE_IBI_HIGH_MS,
                        recent_ibis=recent,
                    )
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
                            self._record_disconnect_start("Erratic signal")
                            self._update_disconnect_overlay(True)
                            self._set_signal_indicator("ERRATIC \u2014 irregular beat", "red")
                            recent = list(data.value[1])[-10:]
                            self._log_signal_fault(
                                "L3_ERRATIC", "Erratic heart rate",
                                last_ibi_ms=int(last_ibi_ms),
                                avg_ibi_ms=int(avg_ibi),
                                deviation_pct=round(deviation * 100, 1),
                                threshold_pct=int(self.settings.DEVIATION_THRESHOLD * 100),
                                recent_ibis=recent,
                            )
                            self._show_signal_degraded_popup("Erratic heart rate")
                            return

                # Normal beat — count towards recovery
                if self._fault_active:
                    self._consecutive_good += 1
                    if self._consecutive_good >= self.settings.RECOVERY_BEATS:
                        self._fault_active = False
                        self._record_disconnect_end()
                        self._start_new_plot_segment()
                        self._update_disconnect_overlay(False)
                        self._reset_signal_popup()
                        self._handle_stream_reset(clear_series=False)
                        self._set_signal_indicator("GOOD", "#00FF00")
        
        # 2. FREQUENCY DATA (Stress Ratio)
        elif data.name == "stress_ratio":
            val = data.value[0]
            self.stress_ratio_label.setText(f"LF/HF: {val:.2f}")
            if self._session_state == "recording":
                self._session_stress_ratio_values.append(float(val))

        # 2b. QTc payload updates from ECG delineation/calculation pipeline.
        elif data.name == "qtc":
            if isinstance(data.value, dict):
                self._session_qtc_payload = data.value
                qrs_val = data.value.get("qrs_ms")
                try:
                    if qrs_val is None:
                        raise TypeError
                    self.qrs_label.setText(f"QRS: {float(qrs_val):.1f} ms")
                except (TypeError, ValueError):
                    self.qrs_label.setText("QRS: -- ms")
                snr_db = data.value.get("snr_db")
                if snr_db is not None and self._session_state == "recording":
                    try:
                        self._session_snr_values.append(float(snr_db))
                    except (TypeError, ValueError):
                        pass
                diag = data.value.get("delineation_diagnostics") or {}
                if diag and self.settings.DEBUG:
                    key = (diag.get("delineation_method"), diag.get("qrs_boundary_source"))
                    if key != self._last_qtc_diag_logged:
                        self._last_qtc_diag_logged = key
                        print(f"ECG delineation: method={key[0]}, qrs_source={key[1]}")
                self._refresh_popup_control_labels()

        # 3. AVERAGED DATA (RMSSD & Stability)
        elif data.name == "hrv":
            if len(data.value[1]) == 0:
                return
            raw_rmssd = float(data.value[1][-1])
            rmssd_val = max(0, min(raw_rmssd, 250))
            self.rmssd_label.setText(f"RMSSD: {rmssd_val:.2f} ms")
            
            if self._fault_active or self._in_settling():
                return

            if rmssd_val > RMSSD_POOR_MS:
                self._set_signal_indicator("POOR (Dry?)", "red")
                self._on_rmssd_degraded(rmssd_val)
            elif rmssd_val > RMSSD_NOISY_MS:
                self._set_signal_indicator("NOISY", "orange")
                self._on_rmssd_degraded(rmssd_val)
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

            # Skip plotting fault-inducing beats (dropout/noise) to avoid bad points on chart.
            if last_ibi_ms > self.settings.DROPOUT_IBI_MS:
                return
            if last_ibi_ms > self.settings.NOISE_IBI_HIGH_MS or last_ibi_ms < self.settings.NOISE_IBI_LOW_MS:
                return

            hr = 60000.0 / last_ibi_ms

            # During fault, do not append new points — preserves chart with break until recovery.
            if self._fault_active:
                return

            if self.start_time is None:
                self.start_time = time.time()
                self._arm_main_plot_warmup(clear_series=True)
                self.ecg_window.sync_timeline_to_main(self._plot_start_delay_seconds)
                self.qtc_window.sync_timeline_to_main(self._plot_start_delay_seconds)
                if self.ecg_button.text() != "ECG (waiting for data...)":
                    self.ecg_button.setText("ECG (waiting for data...)")
                if self.qtc_button.text() not in ("QTc (warming up...)", "QTc (waiting for data...)"):
                    self.qtc_button.setText("QTc (waiting for data...)")
                if self.settings.DEBUG:
                    print("Timer Started")

            now = time.time()
            elapsed = now - self.start_time
            self._update_phase_progress_banner(elapsed, source="ibis")
            plot_elapsed = elapsed - self._plot_start_delay_seconds

            w = self.settings.HR_EWMA_WEIGHT
            if self._hr_ewma is None:
                self._hr_ewma = hr
            elif elapsed >= PLOT_WARMUP_SECONDS and not self._hr_ewma_post_warmup:
                self._hr_ewma_post_warmup = True
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

            if plot_elapsed < 0 or not self._main_plot_gate_open(now):
                return

            self._session_hr_values.append(self._hr_ewma)
            self._session_hr_times.append(plot_elapsed)
            if not self._main_plots_frozen:
                self.hr_trend_series.append(plot_elapsed, self._hr_ewma)
                if self.hr_trend_series.count() % self._series_prune_stride == 0:
                    self._prune_main_chart_series(plot_elapsed)

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
