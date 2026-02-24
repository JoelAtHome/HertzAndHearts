from datetime import datetime
import json
import statistics
import time
from pathlib import Path
import numpy as np
import pyqtgraph as pg
from PySide6.QtCharts import QLineSeries, QChartView, QChart, QValueAxis, QAreaSeries
from PySide6.QtGui import QPen, QIcon, QLinearGradient, QBrush, QGradient, QColor
from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer, QMargins, QSize, QPointF, QEvent
from PySide6.QtBluetooth import QBluetoothAddress, QBluetoothDeviceInfo
from PySide6.QtWidgets import (
    QMainWindow, QPushButton, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QComboBox, QSlider, QGroupBox, QFormLayout, QCheckBox,
    QProgressBar, QGridLayout, QSizePolicy, QStatusBar, QFrame, QCompleter,
    QMessageBox,
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
from hnh.session_artifacts import SessionBundle, create_session_bundle, write_manifest
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

        self._statusbar = QStatusBar()
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("font-size: 11px;")
        self._statusbar.addPermanentWidget(zoom_label)
        self._statusbar.addPermanentWidget(self._zoom_out_button)
        self._statusbar.addPermanentWidget(self._zoom_in_button)
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
        self._history_sec = max(int(self._display_sec), 30)
        self._max_view_sec = float(self._history_sec)
        buf_size = ECG_SAMPLE_RATE * self._history_sec
        self._times = deque(maxlen=buf_size)
        self._values = deque(maxlen=buf_size)
        self._sample_count = 0
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
            self._times.append(self._sample_count * inv_rate)
            self._values.append(val)
            self._sample_count += 1
        self._got_first_data = len(self._times) > 0
        self._refresh_timer.setInterval(self._settings.ECG_REFRESH_MS)
        self._refresh_timer.start()
        if self._got_first_data:
            self._statusbar.showMessage("ECG streaming...")
        else:
            self._statusbar.showMessage("Waiting for ECG data from sensor\u2026")

    def stop(self):
        self._refresh_timer.stop()
        self._frozen = False
        self._freeze_button.setText("Freeze")
        self._plot_widget.setMouseEnabled(x=False, y=False)
        self._statusbar.showMessage("ECG stopped.")

    def _toggle_freeze(self):
        self._frozen = not self._frozen
        if self._frozen:
            self._freeze_button.setText("Resume")
            self._plot_widget.setMouseEnabled(x=True, y=False)
            self._statusbar.showMessage("ECG frozen \u2014 drag to pan, scroll wheel or +/\u2212 to zoom.")
        else:
            self._freeze_button.setText("Freeze")
            self._plot_widget.setMouseEnabled(x=False, y=False)
            self._view_sec = float(self._display_sec)
            self._statusbar.showMessage("ECG streaming...")

    def _zoom_in(self):
        self._view_sec = max(0.5, self._view_sec / 2)
        if self._frozen:
            self._refresh_frozen_view()

    def _zoom_out(self):
        self._view_sec = min(self._max_view_sec, self._view_sec * 2)
        if self._frozen:
            self._refresh_frozen_view()

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
            self._times.append(self._sample_count * inv_rate)
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
        t_min = t_max - self._view_sec
        self._plot_widget.setXRange(max(0, t_min), t_max, padding=0)

        self._curve.setData(t_arr, v_arr)

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
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._last_data_time = None
        self._session_annotations: list[tuple[str, str]] = []
        self._session_hr_values: list[float] = []
        self._session_rmssd_values: list[float] = []
        self._session_state = "idle"
        self._session_bundle: SessionBundle | None = None
        self._session_root = Path.home() / "Hertz-and-Hearts"
        self._session_profile_id = "Default"

        self.setWindowTitle(f"Hertz & Hearts ({version})")
        self.setWindowIcon(QIcon(":/logo.png"))

        # 2. DATA CONNECTIONS
        self.model.ibis_buffer_update.connect(self.plot_ibis)
        self.model.ibis_buffer_update.connect(self.update_ui_labels)
        self.model.stress_ratio_update.connect(self.update_ui_labels)
        self.model.hrv_update.connect(self.update_ui_labels)
        self.model.hrv_update.connect(self.direct_chart_update)

        self.model.addresses_update.connect(self.list_addresses)
        self.model.pacer_rate_update.connect(self.update_pacer_label)
        self.model.hrv_target_update.connect(self.update_hrv_target)

        # 3. COMPONENT INITIALIZATION
        self.signals = ViewSignals()
        self.signals.request_buffer_reset.connect(self.model.clear_buffers)
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
        self.sensor.status_update.connect(self.show_status)

        self.ecg_window = EcgWindow()
        self.sensor.ecg_update.connect(self.ecg_window.append_samples)
        self.sensor.ecg_ready.connect(self._on_ecg_ready)
        self.ecg_window.closed.connect(self._on_ecg_window_closed)
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
        self.connect_button.clicked.connect(self.connect_sensor)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self.disconnect_sensor)
        
        self.reset_button = QPushButton("Reset Baseline")
        self.reset_button.setEnabled(False)
        self.reset_button.clicked.connect(self.reset_baseline)
        self.reset_axes_button = QPushButton("Reset Y Axes")
        self.reset_axes_button.clicked.connect(self.reset_y_axes)

        self.ecg_button = QPushButton("ECG (starting...)")
        self.ecg_button.setEnabled(False)
        self.ecg_button.clicked.connect(self.toggle_ecg_window)
        self.poincare_button = QPushButton("Poincare (starting...)")
        self.poincare_button.setEnabled(False)
        self.poincare_button.clicked.connect(self.toggle_poincare_window)

        self.start_recording_button = QPushButton("Start")
        self.start_recording_button.clicked.connect(self.start_session)
        self.save_recording_button = QPushButton("Save")
        self.save_recording_button.clicked.connect(self.finalize_session)
        self.export_report_button = QPushButton("Report")
        self.export_report_button.clicked.connect(self.export_report)

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

        # Settings button
        self._settings_button = QPushButton("\u2699")
        self._settings_button.setToolTip("Settings")
        self._settings_button.setFixedWidth(28)
        self._settings_button.setStyleSheet("font-size: 14px; padding: 2px;")
        self._settings_button.clicked.connect(self._open_settings)

        # Tooltips for buttons and key data fields.
        self.scan_button.setToolTip("Scan for nearby Bluetooth heart sensors.")
        self.address_menu.setToolTip("Select the sensor to connect.")
        self.connect_button.setToolTip("Connect to the selected sensor.")
        self.disconnect_button.setToolTip("Disconnect from the current sensor.")
        self.reset_button.setToolTip("Reset baseline detection and clear trend buffers.")
        self.reset_axes_button.setToolTip("Restore both chart Y-axes to sensible baseline-centered ranges.")
        self.ecg_button.setToolTip("Open/close the live ECG monitor window.")
        self.poincare_button.setToolTip("Open the live Poincare RR scatter window.")
        self.start_recording_button.setToolTip("Start a new session and begin recording.")
        self.save_recording_button.setToolTip("Finalize the active session and save artifacts.")
        self.export_report_button.setToolTip("Export a draft/final DOCX report for this session.")
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

        # Main content row: equal-height plots on left, pacer stack on right.
        self.content_row = QHBoxLayout()
        self.content_row.setContentsMargins(0, 0, 0, 0)
        self.content_row.setSpacing(2)

        plots_column = QVBoxLayout()
        plots_column.setContentsMargins(0, 0, 0, 0)
        plots_column.setSpacing(2)
        plots_column.addWidget(self.ibis_widget, stretch=1)
        plots_column.addWidget(self.hrv_widget, stretch=1)
        reset_axes_row = QHBoxLayout()
        reset_axes_row.addStretch()
        self.reset_axes_button.setFixedWidth(100)
        reset_axes_row.addWidget(self.reset_axes_button)
        reset_axes_row.addStretch()
        plots_column.addLayout(reset_axes_row)
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

        # Settings row: keep gear in lower-right utility area.
        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.setSpacing(0)
        settings_row.addStretch()
        settings_row.addWidget(self._settings_button)
        self.vlayout0.addLayout(settings_row)

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
        self.poincare_button.setMaximumWidth(130)
        self.poincare_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.start_recording_button.setMaximumWidth(70)
        self.start_recording_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.save_recording_button.setMaximumWidth(70)
        self.save_recording_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.export_report_button.setMaximumWidth(116)
        self.export_report_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
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

        # Set Axis Labels
        self.ibis_widget.x_axis.setTitleText("Seconds")
        self.ibis_widget.y_axis.setTitleText("Heart Rate (bpm)")
        self.hrv_widget.x_axis.setTitleText("Seconds")
        self.hrv_widget.y_axis.setTitleText("RMSSD (ms)")

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
        }

    def _manifest_payload(self, state: str, report_stage: str | None = None) -> dict:
        now = datetime.now().isoformat()
        last_rmssd = self._session_rmssd_values[-1] if self._session_rmssd_values else None
        last_hr = self._session_hr_values[-1] if self._session_hr_values else None
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
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self._session_annotations = []
        self._session_hr_values = []
        self._session_rmssd_values = []
        self._session_bundle = None
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
        if self.poincare_window.isVisible():
            self.poincare_window.hide()
        self.poincare_window.clear()
        self.sensor.disconnect_client()
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.scan_button.setEnabled(True)
        self.ecg_button.setEnabled(False)
        self.ecg_button.setText("ECG (no sensor)")
        self.poincare_button.setEnabled(False)
        self.poincare_button.setText("Poincare (no sensor)")
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
            self.ecg_button.setText("Close ECG")

    def _on_ecg_ready(self):
        self.ecg_button.setEnabled(True)
        self.ecg_button.setText("ECG Monitor")

    def _on_ecg_window_closed(self):
        self.ecg_button.setText("ECG Monitor")

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
            return
        if self._connect_attempt_timer.isActive():
            self.connect_button.setEnabled(False)
            self.connect_button.setStyleSheet(self._CONNECT_DISABLED_CSS)
            self.connect_button.setToolTip("Connecting... please wait for timeout or success.")
            return
        has_sensors = self._has_sensor_choices()
        self.connect_button.setEnabled(has_sensors)
        if has_sensors:
            self.connect_button.setStyleSheet(self._CONNECT_NORMAL_CSS)
            self.connect_button.setToolTip("Connect to the selected sensor.")
        else:
            self.connect_button.setStyleSheet(self._CONNECT_DISABLED_CSS)
            self.connect_button.setToolTip("No sensor selected yet. Click Scan first.")

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
        dlg.exec()
        self._refresh_annotation_list()

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
        self.model.clear_buffers()
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

    def direct_chart_update(self, hrv_data: NamedSignal):
        try:
            if not hrv_data.value or len(hrv_data.value[1]) == 0:
                return
            
            raw_y = float(hrv_data.value[1][-1])
            y = max(0, min(raw_y, 250)) 

            if self.start_time is None:
                return

            elapsed = time.time() - self.start_time
            x = elapsed 
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

            if elapsed < self.settings.SETTLING_DURATION:
                self.is_phase_active = True
                self.recording_statusbar.set_settling(
                    int(elapsed), self.settings.SETTLING_DURATION
                )

            self.hrv_widget.time_series.append(x, smoothed_rmssd)
            self._session_rmssd_values.append(smoothed_rmssd)
            if sdnn is not None and len(self._sdnn_smooth_buf) > 0:
                smoothed_sdnn = sum(self._sdnn_smooth_buf) / len(self._sdnn_smooth_buf)
                self.sdnn_series.append(x, smoothed_sdnn)
                self.sdnn_label.setText(f"SDNN: {sdnn:6.2f} ms")

            # Expand-only Y-axes
            if self._hrv_axis_ceiling is None:
                self._hrv_axis_ceiling = max(10, int(-(-smoothed_rmssd * 1.5 // 5)) * 5)
            rmssd_padded = int(-(-smoothed_rmssd * 1.3 // 5)) * 5
            if rmssd_padded > self._hrv_axis_ceiling:
                self._hrv_axis_ceiling = rmssd_padded
            self.hrv_widget.y_axis.setRange(0, self._hrv_axis_ceiling)

            if self._sdnn_axis_ceiling is None:
                self._sdnn_axis_ceiling = 50
            if len(self._sdnn_smooth_buf) > 0:
                sdnn_padded = int(-(-self._sdnn_smooth_buf[-1] * 1.3 // 5)) * 5
                if sdnn_padded > self._sdnn_axis_ceiling:
                    self._sdnn_axis_ceiling = sdnn_padded
            self.hrv_y_axis_right.setRange(0, self._sdnn_axis_ceiling)

            # --- CONTINUOUS PHASE ENGINE ---
            
            # PHASE 1: BASELINE COLLECTION
            if elapsed < total_calibration_time:
                self.is_phase_active = True
                baseline_elapsed = elapsed - self.settings.SETTLING_DURATION
                baseline_duration = self.settings.BASELINE_DURATION
                self.recording_statusbar.set_baseline(
                    int(baseline_elapsed), baseline_duration
                )
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

                self.baseline_series.clear()
                self.baseline_series.append(x - 60, self.baseline_rmssd)
                self.baseline_series.append(x + 2, self.baseline_rmssd)

            # CHART VIEWPORT
            self.hrv_widget.x_axis.setRange(x - 60, x + 2)

        except Exception as e:
            print(f"Direct Chart Error: {e}")

    def list_addresses(self, addresses: NamedSignal):
        self.address_menu.clear()
        self.address_menu.addItems(addresses.value)
        self._apply_connect_ready_state()
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

    def _check_data_timeout(self):
        if self._last_data_time is None:
            return
        silence = time.time() - self._last_data_time
        if silence >= self.settings.DATA_TIMEOUT_SECONDS and not self._fault_active:
            self._fault_active = True
            self._consecutive_good = 0
            self._set_signal_indicator("LOST (No data)", "red")
            self._show_signal_degraded_popup("No data received")
            self.model.clear_buffers()

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
                        self.model.clear_buffers()
                        self._set_signal_indicator("GOOD", "#00FF00")
        
        # 2. FREQUENCY DATA (Stress Ratio)
        elif data.name == "stress_ratio":
            self.stress_ratio_label.setText(f"LF/HF: {data.value[0]:.2f}")

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
                self.hr_trend_series.clear()
                self.sdnn_series.clear()
                self.hrv_widget.time_series.clear()
                if self.ecg_button.text() != "ECG (waiting for data...)":
                    self.ecg_button.setText("ECG (waiting for data...)")
                if self.settings.DEBUG:
                    print("Timer Started")

            elapsed = time.time() - self.start_time

            w = self.settings.HR_EWMA_WEIGHT
            if self._hr_ewma is None:
                self._hr_ewma = hr
            else:
                self._hr_ewma = w * hr + (1.0 - w) * self._hr_ewma

            if not self.hr_trend_series.count():
                self._hr_ewma = hr

            self.hr_trend_series.append(elapsed, self._hr_ewma)
            self._session_hr_values.append(self._hr_ewma)

            total_cal = self.settings.SETTLING_DURATION + self.settings.BASELINE_DURATION
            if self.settings.SETTLING_DURATION <= elapsed < total_cal:
                self.baseline_hr_values.append(self._hr_ewma)
            elif self.baseline_hr is None and self.baseline_hr_values:
                self.baseline_hr = sum(self.baseline_hr_values) / len(self.baseline_hr_values)

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
                self.hr_baseline_series.clear()
                self.hr_baseline_series.append(elapsed - 60, self.baseline_hr)
                self.hr_baseline_series.append(elapsed + 2, self.baseline_hr)

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

            self.ibis_widget.y_axis.setRange(self._hr_axis_floor, self._hr_axis_ceiling)

            self.ibis_widget.x_axis.setRange(elapsed - 60, elapsed + 2)

        except Exception as e:
            print(f"HR Plot Error: {e}")    
