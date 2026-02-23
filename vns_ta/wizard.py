"""
Protocol Wizard — multi-step clinical workflow container.

Provides a QStackedWidget-based wizard with a progress header showing
numbered step indicators and a Back/Next navigation footer.  Pages are
added via add_page() and can optionally define gate checks that must
pass before the user can advance.

Step definitions match the HTML mockup at mockup/protocol-wizard.html.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


# ──────────────────────────────────────────────────────────────────────
#  Step definitions
# ──────────────────────────────────────────────────────────────────────

WIZARD_STEPS = [
    "Pre-Session",
    "Modality",
    "Sensors",
    "Electrodes",
    "EX4 Config",
    "Readiness",
    "Start Seq.",
    "Monitoring",
    "Summary",
]

MONITORING_PAGE_INDEX = 7

# ──────────────────────────────────────────────────────────────────────
#  Colors (matching the HTML mockup palette)
# ──────────────────────────────────────────────────────────────────────

_BLUE = "#1a5276"
_GREEN = "#27ae60"
_GRAY = "#7f8c8d"
_GRAY_LIGHT = "#ecf0f1"
_GRAY_DARK = "#2c3e50"
_RED = "#c0392b"


# ──────────────────────────────────────────────────────────────────────
#  StepDot — individual numbered circle in the progress header
# ──────────────────────────────────────────────────────────────────────

class _StepDot(QLabel):
    _TMPL_FUTURE = (
        "background: transparent; color: {gray}; "
        "border: 2px solid {gray}; border-radius: {r}px; "
        "font-size: 10px; font-weight: bold;"
    )
    _TMPL_ACTIVE = (
        "background: {blue}; color: white; "
        "border: 2px solid {blue}; border-radius: {r}px; "
        "font-size: 10px; font-weight: bold;"
    )
    _TMPL_DONE = (
        "background: {green}; color: white; "
        "border: 2px solid {green}; border-radius: {r}px; "
        "font-size: 10px; font-weight: bold;"
    )

    def __init__(self, number: int, size: int = 22, parent=None):
        super().__init__(str(number), parent)
        self._number = number
        self._r = size // 2
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.set_state("future")

    def set_state(self, state: str):
        r = self._r
        if state == "done":
            self.setText("\u2713")
            self.setStyleSheet(self._TMPL_DONE.format(green=_GREEN, r=r))
        elif state == "active":
            self.setText(str(self._number))
            self.setStyleSheet(self._TMPL_ACTIVE.format(blue=_BLUE, r=r))
        else:
            self.setText(str(self._number))
            self.setStyleSheet(self._TMPL_FUTURE.format(gray=_GRAY, r=r))


# ──────────────────────────────────────────────────────────────────────
#  ProgressHeader — horizontal step indicator bar
# ──────────────────────────────────────────────────────────────────────

class ProgressHeader(QWidget):
    """Horizontal step indicator matching the mockup's progress track."""

    def __init__(self, steps: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("ProgressHeader")
        self.setStyleSheet(
            f"#ProgressHeader {{ background: {_GRAY_LIGHT}; "
            "border-bottom: 1px solid #d5dbdb; }"
        )

        self._dots: list[_StepDot] = []
        self._labels: list[QLabel] = []
        self._connectors: list[QFrame] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 6, 20, 6)
        layout.setSpacing(0)

        for i, name in enumerate(steps):
            if i > 0:
                conn = QFrame()
                conn.setFixedSize(16, 2)
                conn.setStyleSheet("background: #bdc3c7;")
                layout.addWidget(conn, alignment=Qt.AlignVCenter)
                self._connectors.append(conn)

            dot = _StepDot(i + 1)
            layout.addWidget(dot, alignment=Qt.AlignVCenter)

            lbl = QLabel(name)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet(
                f"color: {_GRAY}; margin-left: 3px; margin-right: 6px;"
            )
            layout.addWidget(lbl, alignment=Qt.AlignVCenter)

            self._dots.append(dot)
            self._labels.append(lbl)

        layout.addStretch()

    def set_current(self, index: int):
        for i, (dot, lbl) in enumerate(zip(self._dots, self._labels)):
            if i < index:
                dot.set_state("done")
                lbl.setStyleSheet(
                    f"color: {_GREEN}; margin-left: 3px; margin-right: 6px;"
                )
            elif i == index:
                dot.set_state("active")
                lbl.setStyleSheet(
                    f"color: {_BLUE}; font-weight: 600; "
                    "margin-left: 3px; margin-right: 6px;"
                )
            else:
                dot.set_state("future")
                lbl.setStyleSheet(
                    f"color: {_GRAY}; margin-left: 3px; margin-right: 6px;"
                )

        for i, conn in enumerate(self._connectors):
            if i < index:
                conn.setStyleSheet(f"background: {_GREEN};")
            else:
                conn.setStyleSheet("background: #bdc3c7;")


# ──────────────────────────────────────────────────────────────────────
#  NavigationFooter — Back / Next bar at the bottom
# ──────────────────────────────────────────────────────────────────────

class NavigationFooter(QWidget):
    """Back/Next navigation footer at the bottom of the wizard."""

    back_clicked = Signal()
    next_clicked = Signal()

    _BTN_BACK = (
        f"QPushButton {{ background: {_GRAY_LIGHT}; color: {_GRAY_DARK}; "
        "border: none; border-radius: 6px; padding: 8px 24px; "
        "font-size: 13px; font-weight: 600; } "
        "QPushButton:hover:enabled { background: #d5dbdb; } "
        "QPushButton:disabled { background: #d5dbdb; color: #aab7b8; }"
    )
    _BTN_NEXT = (
        f"QPushButton {{ background: {_BLUE}; color: white; "
        "border: none; border-radius: 6px; padding: 8px 24px; "
        "font-size: 13px; font-weight: 600; } "
        "QPushButton:hover:enabled { background: #1a6ea0; } "
        "QPushButton:disabled { background: #bdc3c7; color: #95a5a6; }"
    )
    _BTN_FINISH = (
        f"QPushButton {{ background: {_GREEN}; color: white; "
        "border: none; border-radius: 6px; padding: 8px 24px; "
        "font-size: 13px; font-weight: 600; } "
        "QPushButton:hover:enabled { background: #1e8449; } "
        "QPushButton:disabled { background: #bdc3c7; color: #95a5a6; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavigationFooter")
        self.setStyleSheet(
            "#NavigationFooter { background: white; "
            "border-top: 1px solid #d5dbdb; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 6, 24, 6)

        self.back_button = QPushButton("\u25C0 Back")
        self.back_button.setFixedWidth(120)
        self.back_button.setStyleSheet(self._BTN_BACK)
        self.back_button.clicked.connect(self.back_clicked.emit)
        layout.addWidget(self.back_button)

        layout.addStretch()

        center = QHBoxLayout()
        center.setSpacing(8)

        self.step_label = QLabel("Step 1 of 9")
        self.step_label.setStyleSheet(f"color: {_GRAY}; font-size: 13px;")
        center.addWidget(self.step_label)

        self.gate_warning = QLabel(
            "\u26A0 Complete all required items to continue"
        )
        self.gate_warning.setStyleSheet(
            f"color: {_RED}; font-size: 12px; font-weight: 600;"
        )
        self.gate_warning.setVisible(False)
        center.addWidget(self.gate_warning)

        layout.addLayout(center)
        layout.addStretch()

        self.next_button = QPushButton("Next \u25B6")
        self.next_button.setFixedWidth(160)
        self.next_button.setStyleSheet(self._BTN_NEXT)
        self.next_button.clicked.connect(self.next_clicked.emit)
        layout.addWidget(self.next_button)

    def update_state(self, current: int, total: int, gate_satisfied: bool):
        self.back_button.setEnabled(current > 0)
        self.next_button.setEnabled(gate_satisfied)
        self.step_label.setText(f"Step {current + 1} of {total}")
        self.gate_warning.setVisible(not gate_satisfied)

        if current == total - 1:
            self.next_button.setText("Export && Finish")
            self.next_button.setStyleSheet(self._BTN_FINISH)
        elif current == MONITORING_PAGE_INDEX - 1:
            self.next_button.setText("Begin Monitoring \u25B6")
            self.next_button.setStyleSheet(self._BTN_NEXT)
        else:
            self.next_button.setText("Next \u25B6")
            self.next_button.setStyleSheet(self._BTN_NEXT)


# ──────────────────────────────────────────────────────────────────────
#  PlaceholderPage — temporary stand-in for pages not yet built
# ──────────────────────────────────────────────────────────────────────

class PlaceholderPage(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 22, QFont.DemiBold))
        title_label.setStyleSheet(f"color: {_BLUE};")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(f"color: {_GRAY}; font-size: 14px;")
            sub.setAlignment(Qt.AlignCenter)
            layout.addWidget(sub)

        coming = QLabel("Coming in a future build")
        coming.setStyleSheet(
            "color: #bdc3c7; font-size: 13px; font-style: italic;"
        )
        coming.setAlignment(Qt.AlignCenter)
        layout.addWidget(coming)


# ──────────────────────────────────────────────────────────────────────
#  ProtocolWizard — main container
# ──────────────────────────────────────────────────────────────────────

class ProtocolWizard(QWidget):
    """
    QStackedWidget wrapped with a progress header and Back/Next footer.

    Pages are added via add_page().  Each page may optionally provide a
    gate_check callable; if it returns False the Next button is disabled.
    """

    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        self._gate_checks: dict[int, callable] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = ProgressHeader(WIZARD_STEPS)
        root.addWidget(self.header)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, stretch=1)

        self.footer = NavigationFooter()
        self.footer.back_clicked.connect(self._go_back)
        self.footer.next_clicked.connect(self._go_next)
        root.addWidget(self.footer)

    def add_page(self, page: QWidget, gate_check: callable = None):
        """Add a page widget.  Optional gate_check() → bool gates Next."""
        self.stack.addWidget(page)
        idx = self.stack.count() - 1
        if gate_check is not None:
            self._gate_checks[idx] = gate_check
        self._refresh()

    def current_index(self) -> int:
        return self._current

    def set_page(self, index: int):
        if 0 <= index < self.stack.count():
            self._current = index
            self.stack.setCurrentIndex(index)
            self._refresh()
            self.page_changed.emit(index)

    def refresh_gate(self):
        """Re-evaluate the current page's gate (call after checkbox changes)."""
        self._refresh()

    # ── private ──────────────────────────────────────────────────────

    def _go_back(self):
        if self._current > 0:
            self.set_page(self._current - 1)

    def _go_next(self):
        if not self._gate_ok():
            return
        if self._current < self.stack.count() - 1:
            self.set_page(self._current + 1)

    def _gate_ok(self) -> bool:
        check = self._gate_checks.get(self._current)
        return check() if check else True

    def _refresh(self):
        self.header.set_current(self._current)
        self.footer.update_state(
            self._current, self.stack.count(), self._gate_ok()
        )
