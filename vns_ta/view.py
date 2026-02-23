from datetime import datetime
import json
import statistics
import time
from pathlib import Path
from PySide6.QtCharts import QLineSeries, QChartView, QChart, QSplineSeries, QValueAxis, QAreaSeries
from PySide6.QtGui import QPen, QIcon, QLinearGradient, QBrush, QGradient, QColor
from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer, QMargins, QSize, QPointF
from PySide6.QtBluetooth import QBluetoothAddress, QBluetoothDeviceInfo
from PySide6.QtWidgets import (
    QMainWindow, QPushButton, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QComboBox, QSlider, QGroupBox, QFormLayout, QCheckBox, QFileDialog,
    QProgressBar, QGridLayout, QSizePolicy, QStatusBar, QFrame, QCompleter,
    QMessageBox,
    )
from collections import deque
from typing import Iterable
from vns_ta.utils import valid_address, valid_path, get_sensor_address, NamedSignal
from vns_ta.sensor import SensorScanner, SensorClient
from vns_ta.logger import Logger
from vns_ta.pacer import Pacer
from vns_ta.model import Model
from vns_ta.config import (
    breathing_rate_to_tick, HRV_HISTORY_DURATION, IBI_HISTORY_DURATION,
    MAX_BREATHING_RATE, MIN_BREATHING_RATE, MIN_HRV_TARGET, MAX_HRV_TARGET,
    MIN_PLOT_IBI, MAX_PLOT_IBI,
    ECG_SAMPLE_RATE,
)
from vns_ta.settings import Settings, SettingsDialog
from vns_ta.wizard import ProtocolWizard, PlaceholderPage, WIZARD_STEPS, MONITORING_PAGE_INDEX
from vns_ta.wizard_pages import (
    WelcomeDisclaimerPage, PreSessionPage, ModalitySelectionPage,
    SensorPlacementPage, ElectrodePlacementPage, EX4ConfigPage,
    ReadinessPage, StartSequencePage, SessionSummaryPage, MODALITIES,
)
from vns_ta import __version__ as version, resources  # noqa
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

BLUE = QColor(135, 206, 250)
WHITE = QColor(255, 255, 255)
GREEN = QColor(0, 255, 0)
YELLOW = QColor(255, 255, 0)
RED = QColor(255, 0, 0)

SENSOR_CONFIG = Path.home() / ".vns_ta_last_sensor.json"

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

    # Public convenience API (drop-in for old QProgressBar calls)
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
        self.outline.clear()
        for x, y in zip(x_values, y_values):
            self.outline.append(x, y)

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
        """Replaces the points in the series with new data."""
        self.time_series.clear()
        for x, y in zip(x_values, y_values):
            self.time_series.append(x, y)        


class EcgWindow(QMainWindow):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VNS-TA — ECG Monitor")
        self.setMinimumSize(600, 300)
        self.resize(900, 350)

        self._settings = Settings()
        display_sec = self._settings.ECG_DISPLAY_SECONDS
        self._buffer = deque(maxlen=ECG_SAMPLE_RATE * display_sec)
        self._sample_count = 0
        self._y_min_smooth = 0.0
        self._y_max_smooth = 0.0

        self._sweep_buffer = []
        self._reveal_pos = 0.0
        self._sweep_complete = False
        self._prev_sample = None
        self._peak_tracker = 0.0
        self._trigger_threshold = self._settings.ECG_TRIGGER_THRESHOLD
        self._samples_per_frame = ECG_SAMPLE_RATE * (self._settings.ECG_REFRESH_MS / 1000.0)

        chart = QChart()
        chart.legend().setVisible(False)
        chart.setBackgroundRoundness(0)
        chart.setMargins(QMargins(0, 0, 0, 0))
        chart.setAnimationOptions(QChart.NoAnimation)

        self._series = QLineSeries()
        pen = self._series.pen()
        pen.setWidthF(1.2)
        pen.setColor(QColor(0, 0, 0))
        self._series.setPen(pen)
        self._series.setUseOpenGL(True)
        chart.addSeries(self._series)

        self._x_axis = QValueAxis()
        self._x_axis.setTitleText(f"Last {display_sec} Seconds")
        self._x_axis.setRange(0, display_sec)
        self._x_axis.setLabelsVisible(False)
        self._x_axis.setTickCount(6)
        chart.addAxis(self._x_axis, Qt.AlignBottom)
        self._series.attachAxis(self._x_axis)

        self._y_axis = QValueAxis()
        self._y_axis.setTitleText("ECG (mV)")
        self._y_axis.setRange(-1.0, 1.5)
        chart.addAxis(self._y_axis, Qt.AlignLeft)
        self._series.attachAxis(self._y_axis)

        chart_view = QChartView(chart)
        chart_view.setRenderHint(chart_view.renderHints())

        self._frozen = False
        self._freeze_button = QPushButton("Freeze")
        self._freeze_button.setFixedWidth(80)
        self._freeze_button.clicked.connect(self._toggle_freeze)

        self._statusbar = QStatusBar()
        self._statusbar.addPermanentWidget(self._freeze_button)
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Waiting for ECG data...")

        self.setCentralWidget(chart_view)

        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(self._settings.ECG_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._redraw)

    def start(self):
        display_sec = self._settings.ECG_DISPLAY_SECONDS
        self._buffer = deque(maxlen=ECG_SAMPLE_RATE * display_sec)
        self._sweep_buffer = []
        self._reveal_pos = 0.0
        self._sweep_complete = False
        self._prev_sample = None
        self._peak_tracker = 0.0
        self._trigger_threshold = self._settings.ECG_TRIGGER_THRESHOLD
        self._samples_per_frame = ECG_SAMPLE_RATE * (self._settings.ECG_REFRESH_MS / 1000.0)
        self._refresh_timer.setInterval(self._settings.ECG_REFRESH_MS)
        self._x_axis.setRange(0, display_sec)
        self._x_axis.setTitleText(f"Last {display_sec} Seconds")
        self._refresh_timer.start()
        self._statusbar.showMessage("ECG streaming...")

    def stop(self):
        self._refresh_timer.stop()
        self._frozen = False
        self._freeze_button.setText("Freeze")
        self._statusbar.showMessage("ECG stopped.")

    def _toggle_freeze(self):
        self._frozen = not self._frozen
        if self._frozen:
            self._freeze_button.setText("Resume")
            self._statusbar.showMessage("ECG frozen.")
        else:
            self._freeze_button.setText("Freeze")
            self._statusbar.showMessage("ECG streaming...")

    def append_samples(self, samples: list):
        for s in samples:
            self._buffer.append(s)
            self._sample_count += 1

            triggered = False
            if self._prev_sample is not None:
                if self._prev_sample < self._trigger_threshold <= s:
                    if self._sweep_complete or len(self._sweep_buffer) == 0:
                        triggered = True

            if triggered:
                self._sweep_buffer = [s]
                self._sweep_complete = False
                self._reveal_pos = 1.0
            elif not self._sweep_complete:
                self._sweep_buffer.append(s)
                if len(self._sweep_buffer) >= ECG_SAMPLE_RATE * self._settings.ECG_DISPLAY_SECONDS:
                    self._sweep_complete = True

            if s > self._peak_tracker:
                self._peak_tracker = s
            else:
                self._peak_tracker *= 0.998
            self._trigger_threshold = self._peak_tracker * 0.5
            self._prev_sample = s

    def _redraw(self):
        if self._frozen:
            return

        n = len(self._sweep_buffer)
        if n < 2:
            return

        if not self._sweep_complete:
            self._reveal_pos = min(self._reveal_pos + self._samples_per_frame, n)
        show_count = n if self._sweep_complete else int(self._reveal_pos)
        if show_count < 2:
            return

        points = self._sweep_buffer[:show_count]
        inv_rate = 1.0 / ECG_SAMPLE_RATE

        qpoints = []
        y_lo = float('inf')
        y_hi = float('-inf')
        for i, val in enumerate(points):
            t = i * inv_rate
            if val < y_lo:
                y_lo = val
            if val > y_hi:
                y_hi = val
            qpoints.append(QPointF(t, val))

        margin = max(0.1, (y_hi - y_lo) * 0.15)
        target_lo = y_lo - margin
        target_hi = y_hi + margin
        alpha = 0.15
        self._y_min_smooth += alpha * (target_lo - self._y_min_smooth)
        self._y_max_smooth += alpha * (target_hi - self._y_max_smooth)
        self._y_axis.setRange(self._y_min_smooth, self._y_max_smooth)

        self._series.replace(qpoints)

    def closeEvent(self, event):
        self.stop()
        self.closed.emit()
        super().closeEvent(event)


class ViewSignals(QObject):
    annotation = Signal(tuple)
    start_recording = Signal(str)
    request_buffer_reset = Signal() 

class View(QMainWindow):
    def __init__(self, model: Model):
        super().__init__()

        # 1. TRACKERS & STATE
        self.settings = Settings()
        self.model = model
        self.baseline_values = []
        self.baseline_rmssd = None
        self.baseline_hr_values = []
        self.baseline_hr = None
        self.start_time = None 
        self.is_phase_active = False # The "Shield" flag
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

        self.setWindowTitle(f"VNS-TA ({version})")
        self.setWindowIcon(QIcon(":/logo.png"))

        # 2. DATA CONNECTIONS
        self.model.ibis_buffer_update.connect(self.plot_ibis)
        self.model.ibis_buffer_update.connect(self.update_ui_labels)
        self.model.stress_ratio_update.connect(self.update_ui_labels)
        self.model.hrv_update.connect(self.update_ui_labels)
        
        # THE BOSS: Direct connection to the charting/phase logic
        self.model.hrv_update.connect(self.direct_chart_update)

        self.model.addresses_update.connect(self.list_addresses)
        self.model.pacer_rate_update.connect(self.update_pacer_label)
        self.model.hrv_target_update.connect(self.update_hrv_target)

        # 3. COMPONENT INITIALIZATION
        self.signals = ViewSignals()
        #clear buffer after signal lost and recovered
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

        self.logger = Logger()
        self.logger_thread = QThread()
        self.logger.moveToThread(self.logger_thread)
        self.logger_thread.finished.connect(self.logger.save_recording)
        self.signals.start_recording.connect(self.logger.start_recording)
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
        pen = QPen(QColor(30, 100, 220))
        pen.setWidth(2)
        self.sdnn_series.setPen(pen)

        self.hrv_y_axis_right = QValueAxis()
        self.hrv_y_axis_right.setTitleText("HRV/SDNN (ms)")
        self.hrv_y_axis_right.setRange(0, 50)
        self.hrv_widget.plot.addAxis(self.hrv_y_axis_right, Qt.AlignRight)

        self.hrv_widget.plot.addSeries(self.sdnn_series)
        self.sdnn_series.attachAxis(self.hrv_widget.x_axis)
        self.sdnn_series.attachAxis(self.hrv_y_axis_right)

        self.pacer_widget = PacerWidget(self.pacer.lung_x, self.pacer.lung_y)
        self.pacer_widget.setFixedSize(200, 200)
        
        self.recording_statusbar = StatusBanner()

        # Labels
        self.current_hr_label = QLabel("HR: --")
        self.rmssd_label = QLabel("RMSSD: --")
        self.sdnn_label = QLabel("SDNN: --")
        self.stress_ratio_label = QLabel("LF/HF: --")
        self.health_indicator = QLabel("●")
        self.health_indicator.setStyleSheet("color: gray; font-size: 18px;")
        self.health_label = QLabel("Signal: Identifying...")

        # Pacer controls
        self.pacer_label = QLabel("Rate: 7")
        self.pacer_rate = QSlider(Qt.Horizontal)
        self.pacer_rate.setRange(1, 15)
        self.pacer_rate.setValue(7)
        self.pacer_rate.setTickPosition(QSlider.TicksBelow)
        self.pacer_rate.setTickInterval(1)
        self.pacer_rate.setSingleStep(1)
        self.pacer_rate.valueChanged.connect(self._update_breathing_rate)
        self.pacer_toggle = QCheckBox("Show Pacer")
        self.pacer_toggle.setChecked(True)
        self.pacer_toggle.stateChanged.connect(self.toggle_pacer)

        self.pacer_group = QGroupBox("Breathing Pacer")
        self.pacer_config = QFormLayout(self.pacer_group)
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

        self.ecg_button = QPushButton("ECG (starting...)")
        self.ecg_button.setEnabled(False)
        self.ecg_button.clicked.connect(self.toggle_ecg_window)

        self.start_recording_button = QPushButton("Start")
        self.start_recording_button.clicked.connect(self.get_filepath)
        self.save_recording_button = QPushButton("Save")
        self.save_recording_button.clicked.connect(self.logger.save_recording)

        self.annotation = QComboBox()
        self.annotation.setEditable(True)
        self.annotation.setInsertPolicy(QComboBox.NoInsert)
        self.annotation.completer().setFilterMode(Qt.MatchContains)
        self.annotation.completer().setCompletionMode(
            QCompleter.PopupCompletion
        )
        self._refresh_annotation_list()
        self.annotation_button = QPushButton("Annotate")
        self.annotation_button.clicked.connect(self.emit_annotation)

        # 5. LAYOUT ASSEMBLY — monitoring page content
        self.monitoring_page = QWidget()
        self.vlayout0 = QVBoxLayout(self.monitoring_page)
        self.vlayout0.setSpacing(4)

        # TOP: HR Chart + Pacer
        self.hlayout_top = QHBoxLayout()
        self.hlayout_top.addWidget(self.ibis_widget)
        self.hlayout_top.addWidget(self.pacer_widget)
        self.vlayout0.addLayout(self.hlayout_top, stretch=45)

        # MIDDLE: HRV Chart + Pacer Controls (aligned to pacer orb above)
        self.hlayout_mid = QHBoxLayout()
        self.hlayout_mid.addWidget(self.hrv_widget)
        self.pacer_group.setFixedWidth(200)
        self.hlayout_mid.addWidget(self.pacer_group)
        self.vlayout0.addLayout(self.hlayout_mid, stretch=45)

        # BOTTOM ROW 1: Full-width status banner + reset
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        progress_row.addWidget(self.recording_statusbar, stretch=1)
        self.reset_button.setFixedWidth(90)
        progress_row.addWidget(self.reset_button)
        self.vlayout0.addLayout(progress_row)

        # BOTTOM ROW 2: Compact toolbar — constrained for 1366px screens
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        toolbar.setContentsMargins(0, 0, 0, 0)

        for btn in (self.scan_button, self.connect_button,
                    self.disconnect_button):
            btn.setMaximumWidth(80)
            btn.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.ecg_button.setMaximumWidth(110)
        self.ecg_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.address_menu.setMaximumWidth(160)
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
        toolbar.addStretch()

        _stat_style = (
            "font-size: 11px; color: #2c3e50; "
            "border: 1px solid #bdc3c7; border-radius: 3px; "
            "padding: 1px 4px; background: #f8f9fa;"
        )
        _stat_widths = {
            self.current_hr_label: 80,
            self.rmssd_label: 120,
            self.sdnn_label: 110,
            self.stress_ratio_label: 80,
        }
        for lbl, w in _stat_widths.items():
            lbl.setFixedWidth(w)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(_stat_style)
            toolbar.addWidget(lbl)

        toolbar.addSpacing(12)

        _sep2 = QFrame()
        _sep2.setFixedSize(1, 18)
        _sep2.setStyleSheet("background: #bdc3c7;")
        toolbar.addWidget(_sep2)

        self.annotation.setMaximumWidth(200)
        self.annotation.setStyleSheet("font-size: 11px;")
        self.annotation.setPlaceholderText("Annotation\u2026")
        self.annotation_button.setMaximumWidth(64)
        self.annotation_button.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        toolbar.addWidget(self.annotation)
        toolbar.addWidget(self.annotation_button)

        _sep3 = QFrame()
        _sep3.setFixedSize(1, 18)
        _sep3.setStyleSheet("background: #bdc3c7;")
        toolbar.addWidget(_sep3)

        self.health_label.setStyleSheet("font-size: 11px;")
        toolbar.addWidget(self.health_indicator)
        toolbar.addWidget(self.health_label)

        self.vlayout0.addLayout(toolbar)

        # 6. WIZARD ASSEMBLY
        self.wizard = ProtocolWizard()
        self.wizard.header.settings_clicked.connect(self._open_settings)
        self.wizard.dev_mode_changed.connect(self._on_dev_mode_changed)
        self.wizard.page_changed.connect(self._on_wizard_page_changed)
        self.wizard.new_session_requested.connect(self._on_new_session)

        self.welcome_page = WelcomeDisclaimerPage()
        self.welcome_page.gate_changed.connect(self.wizard.refresh_gate)

        self.pre_session_page = PreSessionPage()
        self.pre_session_page.gate_changed.connect(self.wizard.refresh_gate)

        self.modality_page = ModalitySelectionPage()
        self.modality_page.gate_changed.connect(self.wizard.refresh_gate)

        self.sensor_page = SensorPlacementPage()
        self.sensor_page.gate_changed.connect(self.wizard.refresh_gate)
        self.sensor_page.scan_btn.clicked.connect(self.scanner.scan)
        self.sensor_page.connect_btn.clicked.connect(self._connect_from_wizard)
        self.sensor_page.disconnect_btn.clicked.connect(self.disconnect_sensor)
        if saved:
            self.sensor_page.device_menu.addItem(
                f"{saved['name']}, {saved['address']}"
            )

        self.electrode_page = ElectrodePlacementPage()
        self.electrode_page.gate_changed.connect(self.wizard.refresh_gate)

        self.ex4_page = EX4ConfigPage()
        self.ex4_page.gate_changed.connect(self.wizard.refresh_gate)

        self.readiness_page = ReadinessPage(settings=self.settings)
        self.readiness_page.gate_changed.connect(self.wizard.refresh_gate)
        self.readiness_page.reset_btn.clicked.connect(self.reset_baseline)

        self.start_seq_page = StartSequencePage()
        self.start_seq_page.gate_changed.connect(self.wizard.refresh_gate)

        self.summary_page = SessionSummaryPage()
        self.summary_page.gate_changed.connect(self.wizard.refresh_gate)

        self.modality_page.modality_changed.connect(
            lambda key: self.electrode_page.set_active_channels(
                self.modality_page.selected_channels
            )
        )
        self.modality_page.modality_changed.connect(
            lambda key: self.ex4_page.set_active_channels(
                self.modality_page.selected_channels
            )
        )
        self.modality_page.modality_changed.connect(
            lambda key: self.start_seq_page.set_active_channels(
                self.modality_page.selected_channels
            )
        )

        self.sensor_page._spo2_input.textChanged.connect(
            lambda text: self.readiness_page.update_spo2(
                self.sensor_page.spo2_value
            )
        )

        for i, title in enumerate(WIZARD_STEPS):
            if i == 0:
                self.wizard.add_page(
                    self.welcome_page,
                    gate_check=self.welcome_page.is_complete,
                )
            elif i == 1:
                self.wizard.add_page(
                    self.pre_session_page,
                    gate_check=self.pre_session_page.is_complete,
                )
            elif i == 2:
                self.wizard.add_page(
                    self.modality_page,
                    gate_check=self.modality_page.is_complete,
                )
            elif i == 3:
                self.wizard.add_page(
                    self.sensor_page,
                    gate_check=self.sensor_page.is_complete,
                )
            elif i == 4:
                self.wizard.add_page(
                    self.electrode_page,
                    gate_check=self.electrode_page.is_complete,
                )
            elif i == 5:
                self.wizard.add_page(
                    self.ex4_page,
                    gate_check=self.ex4_page.is_complete,
                )
            elif i == 6:
                self.wizard.add_page(
                    self.readiness_page,
                    gate_check=self.readiness_page.is_complete,
                )
            elif i == 7:
                self.wizard.add_page(
                    self.start_seq_page,
                    gate_check=self.start_seq_page.is_complete,
                )
            elif i == MONITORING_PAGE_INDEX:
                self.wizard.add_page(self.monitoring_page)
            elif i == len(WIZARD_STEPS) - 1:
                self.wizard.add_page(
                    self.summary_page,
                    gate_check=self.summary_page.is_complete,
                )
            else:
                self.wizard.add_page(
                    PlaceholderPage(title, f"Step {i + 1} of {len(WIZARD_STEPS)}")
                )
        self.setCentralWidget(self.wizard)

        # Initialize
        self.statusbar = self.statusBar()
        self.logger_thread.start()
        self.pacer_timer.start()

        # Set Axis Labels
        self.ibis_widget.x_axis.setTitleText("Seconds")
        self.ibis_widget.y_axis.setTitleText("Heart Rate (bpm)")
        self.hrv_widget.x_axis.setTitleText("Seconds")
        self.hrv_widget.y_axis.setTitleText("RMSSD (ms)")

    def connect_sensor(self):
        """Connect using the monitoring-page address menu."""
        if not self.address_menu.currentText():
            return
        parts = self.address_menu.currentText().split(",")
        self._do_connect(parts[0].strip(), parts[1].strip())

    def _connect_from_wizard(self):
        """Connect using the wizard sensor-page device menu."""
        if not self.sensor_page.device_menu.currentText():
            return
        parts = self.sensor_page.device_menu.currentText().split(",")
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
        self.hr_trend_series.clear()
        self.sdnn_series.clear()

        if hasattr(self, 'baseline_series'):
            self.hrv_widget.chart().removeSeries(self.baseline_series)
            del self.baseline_series
        if hasattr(self, 'hr_baseline_series'):
            self.ibis_widget.plot.removeSeries(self.hr_baseline_series)
            del self.hr_baseline_series

        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.sensor_page.connect_btn.setEnabled(False)
        self.sensor_page.disconnect_btn.setEnabled(False)
        self.ecg_button.setEnabled(False)
        self.ecg_button.setText("ECG (starting...)")
        self.sensor.connect_client(*sensor)
        self._last_data_time = None
        self._data_watchdog.stop()
        self.show_status("Connecting to Sensor... Please wait.")

    def disconnect_sensor(self):
        """Safely disconnects from the Bluetooth sensor."""
        self._data_watchdog.stop()
        if self.ecg_window.isVisible():
            self.ecg_window.stop()
        self.sensor.disconnect_client()
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.scan_button.setEnabled(True)
        self.sensor_page.connect_btn.setEnabled(True)
        self.sensor_page.disconnect_btn.setEnabled(False)
        self.sensor_page.scan_btn.setEnabled(True)
        self.sensor_page.set_ble_connected(False)
        self.ecg_button.setEnabled(False)
        self.ecg_button.setText("ECG (no sensor)")
        self.is_phase_active = False
        self._reset_signal_popup()
        self.recording_statusbar.set_disconnected()
        self.readiness_page.set_progress_disconnected()

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

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, parent=self)
        dlg.exec()

    def _on_new_session(self):
        """Prompt, then reset the entire wizard for a fresh session."""
        reply = QMessageBox.question(
            self,
            "New Session",
            "Start a new session?\n\n"
            "Make sure you have saved or exported any data you need.\n"
            "Unsaved session data will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Jump to page 0 first, then reset state after event loop settles
        self.wizard.set_page(0)
        QTimer.singleShot(0, self._reset_session_state)

    def _reset_session_state(self):
        """Deferred reset — runs after the page jump is visually complete."""
        if self.sensor.device_connected:
            self.disconnect_sensor()

        # Uncheck all checkboxes across all pages
        for page_idx in range(self.wizard.stack.count()):
            page = self.wizard.stack.widget(page_idx)
            for cb in page.findChildren(QCheckBox):
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)

        self.pre_session_page.clear_patient_info()
        self.modality_page.clear_selection()
        self.sensor_page.clear()
        self.readiness_page.reset_all()
        self.summary_page._notes_edit.clear()

        # Reset monitoring state
        self.baseline_rmssd = None
        self.baseline_hr = None
        self.baseline_values.clear()
        self._rmssd_smooth_buf.clear()
        self._sdnn_smooth_buf.clear()
        self._session_annotations.clear()
        self._session_hr_values.clear()
        self._session_rmssd_values.clear()
        self.start_time = None
        self._hr_ewma = None

        self.recording_statusbar.set_idle()
        self.current_hr_label.setText("HR: --")
        self.rmssd_label.setText("RMSSD: --")
        self.sdnn_label.setText("SDNN: --")
        self.stress_ratio_label.setText("LF/HF: --")

        self.wizard.refresh_gate()

    def _on_wizard_page_changed(self, index: int):
        """Populate the summary page when the user navigates to it."""
        if index == len(WIZARD_STEPS) - 1:
            self._populate_summary()

    def _populate_summary(self):
        modality_key = self.modality_page.selected_modality
        modality_name = "--"
        if modality_key:
            for m in MODALITIES:
                if m["key"] == modality_key:
                    modality_name = m["title"]
                    break

        last_rmssd = None
        if self._rmssd_smooth_buf:
            last_rmssd = sum(self._rmssd_smooth_buf) / len(self._rmssd_smooth_buf)

        csv_path = None
        if self.logger.file is not None:
            csv_path = self.logger.file.name

        session_start_dt = None
        if self.start_time is not None:
            session_start_dt = datetime.fromtimestamp(self.start_time)

        self.summary_page.set_session_data({
            "patient_name": self.pre_session_page.patient_name,
            "patient_dob": self.pre_session_page.patient_dob.toString("MM/dd/yyyy"),
            "baseline_hr": self.baseline_hr,
            "baseline_rmssd": self.baseline_rmssd,
            "spo2": self.sensor_page.spo2_value,
            "last_hr": self._hr_ewma,
            "last_rmssd": last_rmssd,
            "modality_name": modality_name,
            "active_channels": self.modality_page.selected_channels,
            "session_start": session_start_dt,
            "csv_path": csv_path,
            "annotations": list(self._session_annotations),
            "hr_values": list(self._session_hr_values),
            "rmssd_values": list(self._session_rmssd_values),
            "outcome": "normal",
        })

    def _on_dev_mode_changed(self, enabled: bool):
        self.readiness_page.set_dev_mode(enabled)
        suffix = " [DEV]" if enabled else ""
        self.setWindowTitle(f"VNS-TA ({version}){suffix}")

    def _auto_start_recording(self):
        """Auto-start CSV recording on successful BLE connection."""
        if self.logger.file is not None:
            return
        ts = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        auto_path = str(Path.home() / f"VNS-TA_{ts}.csv")
        self.signals.start_recording.emit(auto_path)

    def get_filepath(self):
        """Opens a file dialog to set the recording destination."""
        current_time: str = datetime.now().strftime("%Y-%m-%d-%H-%M")
        default_file_name: str = f"VNS-TA_{current_time}.csv"
        
        # Opens the Windows/System save dialog
        file_path: str = QFileDialog.getSaveFileName(
            None,
            "Create file",
            default_file_name,
            options=QFileDialog.DontUseNativeDialog,
        )[0]
        
        if not file_path:  # User cancelled
            return
            
        if not valid_path(file_path):
            self.show_status("File path is invalid or exists already.")
            return
            
        # Tell the logger to start writing
        self.signals.start_recording.emit(file_path)

    def emit_annotation(self):
        """Send annotation to logger, auto-learn custom entries, clear field."""
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
        """Rebuild the annotation combo from presets + user custom entries."""
        self.annotation.clear()
        for item in self.settings.get_all_annotations():
            self.annotation.addItem(item)
        self.annotation.setCurrentText("")

    def reset_baseline(self):
        self.reset_button.setEnabled(False)
        self.start_time = None
        self.baseline_rmssd = None
        self.baseline_values = []
        self.baseline_hr = None
        self.baseline_hr_values = []
        self.readiness_page.set_baselines_locked(False)
        self.readiness_page.set_progress_disconnected()
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
        self.health_indicator.setStyleSheet("color: gray; font-size: 18px;")
        self.health_label.setText("Signal: Identifying...")
        self.show_status("Baseline Reset. Waiting for data...")
        if hasattr(self, 'baseline_series'):
            self.baseline_series.clear()
        if hasattr(self, 'hr_baseline_series'):
            self.hr_baseline_series.clear()

    def direct_chart_update(self, hrv_data: NamedSignal):
        try:
            # 1. Capture the latest HRV value
            # Since hrv_data now sends (seconds, buffer), we grab the last value
            if not hrv_data.value or len(hrv_data.value[1]) == 0:
                return
            
            raw_y = float(hrv_data.value[1][-1]) # Get the newest RMSSD
            y = max(0, min(raw_y, 250)) 

            # 2. Wait for plot_ibis to start the clock
            if self.start_time is None:
                return

            elapsed = time.time() - self.start_time
            x = elapsed 
            total_calibration_time = self.settings.SETTLING_DURATION + self.settings.BASELINE_DURATION

            # 3. Add smoothed RMSSD to Chart
            ibis = list(self.model.ibis_buffer)
            cur_hr = 60000.0 / ibis[-1] if ibis and ibis[-1] > 0 else 70
            smooth_n = max(5, round(cur_hr / 60 * self.settings.SMOOTH_SECONDS))

            self._rmssd_smooth_buf.append(y)
            while len(self._rmssd_smooth_buf) > smooth_n:
                self._rmssd_smooth_buf.pop(0)
            smoothed_rmssd = sum(self._rmssd_smooth_buf) / len(self._rmssd_smooth_buf)

            # 3b. Compute and plot SDNN from IBI buffer
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
                self.readiness_page.set_progress_settling(
                    int(elapsed), self.settings.SETTLING_DURATION
                )
                return

            if self._rmssd_smooth_buf and not self.hrv_widget.time_series.count():
                self._rmssd_smooth_buf.clear()
                self._sdnn_smooth_buf.clear()
                self._rmssd_smooth_buf.append(y)
                smoothed_rmssd = y

            self.hrv_widget.time_series.append(x, smoothed_rmssd)
            self._session_rmssd_values.append(smoothed_rmssd)
            self.start_seq_page.update_rmssd(smoothed_rmssd)
            if sdnn is not None and len(self._sdnn_smooth_buf) > 0:
                smoothed_sdnn = sum(self._sdnn_smooth_buf) / len(self._sdnn_smooth_buf)
                self.sdnn_series.append(x, smoothed_sdnn)
                self.sdnn_label.setText(f"SDNN: {sdnn:6.2f} ms")

            # 4. Expand-only Y-axes — grow to fit peaks, never shrink
            # Left axis: RMSSD (start tight, grow in steps of 5)
            if self._hrv_axis_ceiling is None:
                self._hrv_axis_ceiling = max(10, int(-(-smoothed_rmssd * 1.5 // 5)) * 5)
            rmssd_padded = int(-(-smoothed_rmssd * 1.3 // 5)) * 5
            if rmssd_padded > self._hrv_axis_ceiling:
                self._hrv_axis_ceiling = rmssd_padded
            self.hrv_widget.y_axis.setRange(0, self._hrv_axis_ceiling)

            # Right axis: HRV/SDNN
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
                self.readiness_page.set_progress_baseline(
                    int(baseline_elapsed), baseline_duration
                )
                self.baseline_values.append(y)

            # PHASE 2: CALCULATE AVERAGES (Only once at end of baseline)
            elif self.baseline_rmssd is None and self.baseline_values:
                self.baseline_rmssd = sum(self.baseline_values) / len(self.baseline_values)
                self.reset_button.setEnabled(True)
                hr_text = f"{self.baseline_hr:.0f}" if self.baseline_hr is not None else "--"
                self.statusbar.showMessage(
                    f"Baselines locked — RMSSD: {self.baseline_rmssd:.1f} ms, HR: {hr_text} bpm"
                )
                self.readiness_page.update_rmssd(self.baseline_rmssd)
                self.readiness_page.set_baselines_locked(True)
                self.start_seq_page.set_baseline_hr(self.baseline_hr)
                if self.settings.DEBUG:
                    print(f"--- BASELINES LOCKED: RMSSD={self.baseline_rmssd:.2f} ms, HR={hr_text} bpm ---")

            # PHASE 3: LOCKED STATE (45s+)
            if self.baseline_rmssd is not None:
                self.is_phase_active = True
                hr_val = f"{self.baseline_hr:.0f}" if self.baseline_hr is not None else "--"
                self.recording_statusbar.set_locked(
                    f"{self.baseline_rmssd:.1f}", hr_val
                )
                self.readiness_page.set_progress_locked(
                    f"{self.baseline_rmssd:.1f}", hr_val
                )

                # Dotted Line Logic
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

            # 5. CHART VIEWPORT
            self.hrv_widget.x_axis.setRange(x - 60, x + 2)

        except Exception as e:
            print(f"Direct Chart Error: {e}")

    def list_addresses(self, addresses: NamedSignal):
        self.address_menu.clear()
        self.address_menu.addItems(addresses.value)
        self.sensor_page.device_menu.clear()
        self.sensor_page.device_menu.addItems(addresses.value)

    def plot_pacer_disk(self):
        if not self.pacer_toggle.isChecked():
            return
        coordinates = self.pacer.update(self.model.breathing_rate)
        self.pacer_widget.update_series(*coordinates)

    def update_pacer_label(self, rate: NamedSignal):
        self.pacer_label.setText(f"Rate: {rate.value}")

    def update_hrv_target(self, target: NamedSignal):
        self.hrv_widget.y_axis.setRange(0, target.value)
        self.hrv_target_label.setText(f"Target: {target.value}")

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
        """Indicate busy state if `status` is 0."""
        self.recording_statusbar.setRange(0, max(status, 1))

    def show_status(self, status: str, print_to_terminal=True):
        if "Connected" in status and "Disconnecting" not in status:
            self.is_phase_active = False
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.scan_button.setEnabled(False)
            self.sensor_page.connect_btn.setEnabled(False)
            self.sensor_page.disconnect_btn.setEnabled(True)
            self.sensor_page.scan_btn.setEnabled(False)
            self.sensor_page.set_ble_connected(True)
            if self.address_menu.currentText():
                parts = self.address_menu.currentText().split(",")
                if len(parts) >= 2:
                    _save_last_sensor(parts[0].strip(), parts[1].strip())
            elif self.sensor_page.device_menu.currentText():
                parts = self.sensor_page.device_menu.currentText().split(",")
                if len(parts) >= 2:
                    _save_last_sensor(parts[0].strip(), parts[1].strip())
            self._auto_start_recording()
        elif "error" in status.lower() or "Disconnecting" in status:
            self.connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(False)
            self.scan_button.setEnabled(True)
            self.sensor_page.connect_btn.setEnabled(True)
            self.sensor_page.disconnect_btn.setEnabled(False)
            self.sensor_page.scan_btn.setEnabled(True)
            self.sensor_page.set_ble_connected(False)

        if not self.is_phase_active:
            if "error" in status.lower():
                self.recording_statusbar.set_error(status)
            else:
                self.recording_statusbar.set_idle(status)
        
        # ALWAYS update the tiny status bar at the very bottom
        self.statusbar.showMessage(status)
        
        if print_to_terminal and self.settings.DEBUG:
            print(status)

    def update_ui_with_mock_data(self):
        self.current_hr_label.setText("HR: 72 bpm")
        self.rmssd_label.setText("RMSSD: 45 ms")
        self.stress_ratio_label.setText("LF/HF: 1.2")

    def _show_signal_degraded_popup(self, reason: str):
        """One-shot popup when H10 signal degrades from IBI faults."""
        if self._signal_popup_shown:
            return
        self._signal_popup_shown = True
        self._fire_signal_popup(reason)

    def _fire_signal_popup(self, reason: str):
        if self.wizard.current_index() >= len(WIZARD_STEPS) - 1:
            return
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Polar H10 Signal Degraded")
        msg.setText(
            f"<b>Signal quality issue detected: {reason}</b>"
        )
        msg.setInformativeText(
            "Please ask the patient to sit still and breathe normally.\n\n"
            "If the problem persists, re-wet the Polar H10 electrode "
            "pads with water or electrode gel and ensure the strap is "
            "snug against the skin."
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.open()

    def _on_rmssd_degraded(self):
        """Track consecutive bad RMSSD readings; popup after sustained degradation."""
        self._signal_degrade_count += 1
        if not self._signal_popup_shown and self._signal_degrade_count >= 8:
            self._signal_popup_shown = True
            self._fire_signal_popup("Poor signal — electrodes may be dry")

    def _reset_signal_popup(self):
        """Allow popup to fire again after signal recovers."""
        self._signal_popup_shown = False
        self._signal_degrade_count = 0

    def _check_data_timeout(self):
        if self._last_data_time is None:
            return
        silence = time.time() - self._last_data_time
        if silence >= self.settings.DATA_TIMEOUT_SECONDS and not self._fault_active:
            self._fault_active = True
            self._consecutive_good = 0
            self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
            self.health_label.setText("Signal: LOST (No data)")
            self._show_signal_degraded_popup("No data received")
            self.model.clear_buffers()

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
                self.sensor_page.update_hr_display(display_hr)
                self.readiness_page.update_hr(display_hr)
                self.start_seq_page.update_hr(display_hr)

                # LEVEL 1 FAULT: Total Dropout
                if last_ibi_ms > self.settings.DROPOUT_IBI_MS:
                    self._fault_active = True
                    self._consecutive_good = 0
                    self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
                    self.health_label.setText("FAULT: Clearing Buffer...")
                    self._show_signal_degraded_popup("Total signal dropout")
                    self.signals.request_buffer_reset.emit()
                    return

                # LEVEL 2 FAULT: Hard IBI limits
                if last_ibi_ms > self.settings.NOISE_IBI_HIGH_MS or last_ibi_ms < self.settings.NOISE_IBI_LOW_MS:
                    self._fault_active = True
                    self._consecutive_good = 0
                    self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
                    self.health_label.setText("Signal: DROP/NOISE")
                    self._show_signal_degraded_popup("Signal dropout or noise")
                    return

                # LEVEL 3 FAULT: Adaptive — 30% deviation from rolling average
                # Skip during recovery: the rolling average is polluted by
                # the bad data that caused the fault in the first place.
                if not self._fault_active:
                    recent_ibis = list(data.value[1])[-self.settings.DEVIATION_WINDOW:]
                    if len(recent_ibis) >= self.settings.DEVIATION_MIN_SAMPLES:
                        avg_ibi = sum(recent_ibis) / len(recent_ibis)
                        deviation = abs(last_ibi_ms - avg_ibi) / avg_ibi
                        if deviation > self.settings.DEVIATION_THRESHOLD:
                            self._fault_active = True
                            self._consecutive_good = 0
                            avg_hr = int(60000.0 / avg_ibi)
                            self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
                            self.health_label.setText(f"Signal: ERRATIC (avg {avg_hr})")
                            self._show_signal_degraded_popup("Erratic heart rate")
                            return

                # Normal beat — count towards recovery
                if self._fault_active:
                    self._consecutive_good += 1
                    if self._consecutive_good >= self.settings.RECOVERY_BEATS:
                        self._fault_active = False
                        self._reset_signal_popup()
                        self.model.clear_buffers()
                        self.health_indicator.setStyleSheet("color: #00FF00; font-size: 18px;")
                        self.health_label.setText("Signal: GOOD")
        
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
            
            if self._fault_active:
                return

            if rmssd_val > 200:
                self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
                self.health_label.setText("Signal: POOR (Dry?)")
                self._on_rmssd_degraded()
            elif rmssd_val > 150:
                self.health_indicator.setStyleSheet("color: orange; font-size: 18px;")
                self.health_label.setText("Signal: NOISY")
                self._on_rmssd_degraded()
            else:
                self.health_indicator.setStyleSheet("color: #00FF00; font-size: 18px;")
                self.health_label.setText("Signal: GOOD")
                self._reset_signal_popup()

    def plot_ibis(self, data: NamedSignal):
        """Plots the top chart as Heart Rate (bpm) vs wall-clock time."""
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
                if self.settings.DEBUG:
                    print("Timer Started")

            elapsed = time.time() - self.start_time

            w = self.settings.HR_EWMA_WEIGHT
            if self._hr_ewma is None:
                self._hr_ewma = hr
            else:
                self._hr_ewma = w * hr + (1.0 - w) * self._hr_ewma

            if elapsed < self.settings.SETTLING_DURATION:
                return

            if not self.hr_trend_series.count():
                self._hr_ewma = hr

            self.hr_trend_series.append(elapsed, self._hr_ewma)
            self._session_hr_values.append(self._hr_ewma)

            total_cal = self.settings.SETTLING_DURATION + self.settings.BASELINE_DURATION
            if elapsed < total_cal:
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

            # Expand-only Y-axis: grows to fit extremes, never shrinks
            min_span = 40
            hr_low = hr - 10
            hr_high = hr + 10

            # Round down to nearest 10, round up to nearest 10
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
