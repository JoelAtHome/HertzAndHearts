from datetime import datetime
import json
import statistics
import time
from pathlib import Path
from PySide6.QtCharts import QLineSeries, QChartView, QChart, QSplineSeries, QValueAxis, QAreaSeries
from PySide6.QtGui import QPen, QIcon, QLinearGradient, QBrush, QGradient, QColor
from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer, QMargins, QSize
from PySide6.QtBluetooth import QBluetoothAddress, QBluetoothDeviceInfo
from PySide6.QtWidgets import (
    QMainWindow, QPushButton, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QComboBox, QSlider, QGroupBox, QFormLayout, QCheckBox, QFileDialog,
    QProgressBar, QGridLayout, QSizePolicy
    )
from typing import Iterable
from openhrv.utils import valid_address, valid_path, get_sensor_address, NamedSignal
from openhrv.sensor import SensorScanner, SensorClient
from openhrv.logger import Logger
from openhrv.pacer import Pacer
from openhrv.model import Model
from openhrv.config import (
    breathing_rate_to_tick, HRV_HISTORY_DURATION, IBI_HISTORY_DURATION,
    MAX_BREATHING_RATE, MIN_BREATHING_RATE, MIN_HRV_TARGET, MAX_HRV_TARGET,
    MIN_PLOT_IBI, MAX_PLOT_IBI
)
from openhrv import __version__ as version, resources  # noqa
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

# --- SESSION SETTINGS ---
SETTLING_DURATION = 15   
BASELINE_DURATION = 30
SMOOTH_SECONDS = 18

BLUE = QColor(135, 206, 250)
WHITE = QColor(255, 255, 255)
GREEN = QColor(0, 255, 0)
YELLOW = QColor(255, 255, 0)
RED = QColor(255, 0, 0)

SENSOR_CONFIG = Path.home() / ".openhrv_last_sensor.json"

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


class ViewSignals(QObject):
    annotation = Signal(tuple)
    start_recording = Signal(str)
    request_buffer_reset = Signal() 

class View(QMainWindow):
    def __init__(self, model: Model):
        super().__init__()

        # 1. TRACKERS & STATE
        self.model = model
        self.baseline_values = []
        self.baseline_rmssd = None
        self.start_time = None 
        self.is_phase_active = False # The "Shield" flag
        self._fault_active = False
        self._consecutive_good = 0
        self._hr_ewma = None
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_ceiling = None
        self._hr_smooth_buf = []
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []

        self.setWindowTitle(f"OpenHRV ({version})")
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

        self.scanner = SensorScanner()
        self.scanner.sensor_update.connect(self.model.update_sensors)
        self.scanner.status_update.connect(self.show_status)

        self.sensor = SensorClient()
        self.sensor.ibi_update.connect(self.model.update_ibis_buffer)
        self.sensor.status_update.connect(self.show_status)

        self.logger = Logger()
        self.logger_thread = QThread()
        self.logger.moveToThread(self.logger_thread)
        self.logger_thread.finished.connect(self.logger.save_recording)
        self.signals.start_recording.connect(self.logger.start_recording)
        self.model.hrv_update.connect(self.logger.write_to_file)

        # 4. UI WIDGETS
        self.ibis_widget = XYSeriesWidget(self.model.ibis_seconds, self.model.ibis_buffer)
        self.ibis_widget.y_axis.setRange(40, 160)

        self.ibis_widget.time_series.setName("Actual Heart Rate (bpm)")

        self.hr_trend_series = QLineSeries()
        self.hr_trend_series.setName("Averaged Heart Rate (bpm)")
        pen = QPen(QColor(30, 100, 220))
        pen.setStyle(Qt.DotLine)
        pen.setWidth(2)
        self.hr_trend_series.setPen(pen)
        self.ibis_widget.plot.addSeries(self.hr_trend_series)
        self.hr_trend_series.attachAxis(self.ibis_widget.x_axis)
        self.hr_trend_series.attachAxis(self.ibis_widget.y_axis)

        self.ibis_widget.plot.legend().setVisible(True)
        self.ibis_widget.plot.legend().setAlignment(Qt.AlignTop)

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
        
        self.recording_statusbar = QProgressBar()
        self.recording_statusbar.setMinimumHeight(30)
        self.recording_statusbar.setTextVisible(True)
        self.recording_statusbar.setAlignment(Qt.AlignCenter)
        self.recording_statusbar.setFormat("Waiting for Sensor...")

        # Labels
        self.current_hr_label = QLabel("Heart Rate: --")
        self.rmssd_label = QLabel("RMSSD: --")
        self.sdnn_label = QLabel("HRV/SDNN: --")
        self.stress_ratio_label = QLabel("Stress Ratio (LF/HF): --")
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
        self.disconnect_button.clicked.connect(self.disconnect_sensor)
        
        self.reset_button = QPushButton("Reset Baseline")
        self.reset_button.clicked.connect(self.reset_baseline)

        self.start_recording_button = QPushButton("Start")
        self.start_recording_button.clicked.connect(self.get_filepath)
        self.save_recording_button = QPushButton("Save")
        self.save_recording_button.clicked.connect(self.logger.save_recording)

        self.annotation = QComboBox()
        self.annotation.setEditable(True)
        self.annotation_button = QPushButton("Annotate")
        self.annotation_button.clicked.connect(self.emit_annotation)

        # 5. LAYOUT ASSEMBLY
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.vlayout0 = QVBoxLayout(self.central_widget)

        # TOP: HR Chart + Pacer
        self.hlayout_top = QHBoxLayout()
        self.hlayout_top.addWidget(self.ibis_widget)
        self.hlayout_top.addWidget(self.pacer_widget)
        self.vlayout0.addLayout(self.hlayout_top, stretch=40)

        # MIDDLE: HRV Chart + Pacer Controls (aligned to pacer orb above)
        self.hlayout_mid = QHBoxLayout()
        self.hlayout_mid.addWidget(self.hrv_widget)
        self.pacer_group.setFixedWidth(200)
        self.hlayout_mid.addWidget(self.pacer_group)
        self.vlayout0.addLayout(self.hlayout_mid, stretch=40)

        # BOTTOM: Controls Layout
        self.controls_layout = QHBoxLayout()
        
        # PANEL A: Device & Stats
        self.device_group = QGroupBox("Device & Stats")
        self.device_grid = QGridLayout(self.device_group)
        self.device_grid.addWidget(self.scan_button, 0, 0)
        self.device_grid.addWidget(self.address_menu, 0, 1)
        self.device_grid.addWidget(self.connect_button, 1, 0)
        self.device_grid.addWidget(self.disconnect_button, 1, 1)
        self.device_grid.addWidget(self.reset_button, 2, 0, 1, 2)

        self.device_grid.addWidget(self.rmssd_label, 3, 0)
        self.device_grid.addWidget(self.stress_ratio_label, 3, 1)
        self.device_grid.addWidget(self.current_hr_label, 4, 0)
        self.device_grid.addWidget(self.sdnn_label, 5, 0)

        # PANEL B: Recording & Status
        self.rec_group = QGroupBox("Recording & Status")
        self.rec_grid = QGridLayout(self.rec_group)
        self.rec_grid.addWidget(self.start_recording_button, 0, 0)
        self.rec_grid.addWidget(self.save_recording_button, 0, 1)
        self.rec_grid.addWidget(self.annotation, 1, 0, 1, 2)
        self.rec_grid.addWidget(self.annotation_button, 1, 2)
        self.rec_grid.addWidget(self.recording_statusbar, 2, 0, 1, 3)

        self.controls_layout.addWidget(self.device_group, stretch=45)
        self.controls_layout.addWidget(self.rec_group, stretch=55)
        
        self.vlayout0.addLayout(self.controls_layout, stretch=20)

        # Initialize
        self.statusbar = self.statusBar()
        signal_status_widget = QWidget()
        signal_status_layout = QHBoxLayout(signal_status_widget)
        signal_status_layout.setContentsMargins(8, 0, 8, 0)
        signal_status_layout.addWidget(self.health_indicator)
        signal_status_layout.addWidget(self.health_label)
        self.statusbar.addPermanentWidget(signal_status_widget)
        self.logger_thread.start()
        self.pacer_timer.start()

        # Set Axis Labels
        self.ibis_widget.x_axis.setTitleText("Seconds")
        self.ibis_widget.y_axis.setTitleText("Heart Rate (bpm)")
        self.hrv_widget.x_axis.setTitleText("Seconds")
        self.hrv_widget.y_axis.setTitleText("RMSSD (ms)")

    def show_status(self, status: str):
        """Silently ignore generic status updates if a Phase is active."""
        if not self.is_phase_active:
            self.recording_statusbar.setFormat(status)
        self.statusbar.showMessage(status)

    def connect_sensor(self):
        if not self.address_menu.currentText(): return
        parts = self.address_menu.currentText().split(",")
        name = parts[0].strip()
        address = parts[1].strip()
        sensor = [s for s in self.model.sensors if get_sensor_address(s) == address]
        
        if not sensor:
            bt_addr = QBluetoothAddress(address)
            device = QBluetoothDeviceInfo(bt_addr, name, 0)
            device.setCoreConfigurations(QBluetoothDeviceInfo.LowEnergyCoreConfiguration)
            sensor = [device]

        # RESET EVERYTHING
        self.start_time = None
        self.baseline_values = []
        self.baseline_rmssd = None
        self.is_phase_active = False
        self._fault_active = False
        self._consecutive_good = 0
        self._hr_ewma = None
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_ceiling = None
        self._hr_smooth_buf = []
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self.hr_trend_series.clear()
        self.sdnn_series.clear()
        
        if hasattr(self, 'baseline_series'):
            self.hrv_widget.chart().removeSeries(self.baseline_series)
            del self.baseline_series
            
        self.sensor.connect_client(*sensor)
        self.show_status("Connecting to Sensor... Please wait.")

    def disconnect_sensor(self):
        """Safely disconnects from the Bluetooth sensor."""
        self.sensor.disconnect_client()
        # Ensure the shield is lowered so general status messages can appear again
        self.is_phase_active = False 
        self.recording_statusbar.setFormat("Sensor Disconnected")

    def get_filepath(self):
        """Opens a file dialog to set the recording destination."""
        current_time: str = datetime.now().strftime("%Y-%m-%d-%H-%M")
        default_file_name: str = f"OpenHRV_{current_time}.csv"
        
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
        """Sends the current text in the dropdown to the data logger."""
        self.signals.annotation.emit(
            NamedSignal("Annotation", self.annotation.currentText())
        )    

    def reset_baseline(self):
        self.start_time = None
        self.baseline_rmssd = None
        self.baseline_values = []
        self.is_phase_active = False
        self._hr_ewma = None
        self._hr_axis_floor = None
        self._hr_axis_ceiling = None
        self._hrv_axis_ceiling = None
        self._sdnn_axis_ceiling = None
        self._hr_smooth_buf = []
        self._rmssd_smooth_buf = []
        self._sdnn_smooth_buf = []
        self.ibis_widget.time_series.clear()
        self.hr_trend_series.clear()
        self.sdnn_series.clear()
        self.show_status("Baseline Reset. Waiting for data...")
        if hasattr(self, 'baseline_series'):
            self.baseline_series.clear()

    def direct_chart_update(self, hrv_data: NamedSignal):
        try:
            # 1. Capture the latest HRV value
            # Since hrv_data now sends (seconds, buffer), we grab the last value
            if not hrv_data.value or len(hrv_data.value[1]) == 0:
                return
            
            raw_y = float(hrv_data.value[1][-1]) # Get the newest RMSSD
            y = max(0, min(raw_y, 250)) 

            # 2. Ignition: Start the clock
            if self.start_time is None:
                self.start_time = time.time()
                self.hrv_widget.time_series.clear()
                self.ibis_widget.time_series.clear()
                self.hr_trend_series.clear()
                self.sdnn_series.clear()
                print("DEBUG: Timer Started")

            elapsed = time.time() - self.start_time
            x = elapsed 
            total_calibration_time = SETTLING_DURATION + BASELINE_DURATION 

            # 3. Add smoothed RMSSD to Chart
            ibis = list(self.model.ibis_buffer)
            cur_hr = 60000.0 / ibis[-1] if ibis and ibis[-1] > 0 else 70
            smooth_n = max(5, round(cur_hr / 60 * SMOOTH_SECONDS))

            self._rmssd_smooth_buf.append(y)
            while len(self._rmssd_smooth_buf) > smooth_n:
                self._rmssd_smooth_buf.pop(0)
            smoothed_rmssd = sum(self._rmssd_smooth_buf) / len(self._rmssd_smooth_buf)
            self.hrv_widget.time_series.append(x, smoothed_rmssd)

            # 3b. Compute and plot SDNN from IBI buffer
            if len(ibis) >= 10:
                sdnn = statistics.stdev(ibis[-30:])
                self._sdnn_smooth_buf.append(sdnn)
                while len(self._sdnn_smooth_buf) > smooth_n:
                    self._sdnn_smooth_buf.pop(0)
                smoothed_sdnn = sum(self._sdnn_smooth_buf) / len(self._sdnn_smooth_buf)
                self.sdnn_series.append(x, smoothed_sdnn)
                self.sdnn_label.setText(f"HRV/SDNN: {sdnn:.1f} ms")

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
            
            # PHASE 0 & 1: CALIBRATION (0 to 45 seconds)
            if elapsed < total_calibration_time:
                self.is_phase_active = True
                self.recording_statusbar.setRange(0, total_calibration_time)
                self.recording_statusbar.setValue(int(elapsed))
                
                if elapsed < SETTLING_DURATION:
                    # Settling (0-15s)
                    remaining = int(SETTLING_DURATION - elapsed)
                    self.recording_statusbar.setFormat(f"Settling... {remaining}s")
                else:
                    # Baseline (15-45s)
                    self.baseline_values.append(y)
                    remaining = int(total_calibration_time - elapsed)
                    self.recording_statusbar.setFormat(f"Baseline... {remaining}s")

            # PHASE 2: CALCULATE AVERAGE (Only once at 45s)
            elif self.baseline_rmssd is None and self.baseline_values:
                self.baseline_rmssd = sum(self.baseline_values) / len(self.baseline_values)
                self.statusbar.showMessage(f"Baseline locked at {self.baseline_rmssd:.1f} ms")
                print(f"--- BASELINE LOCKED: {self.baseline_rmssd:.2f} ms ---")

            # PHASE 3: LOCKED STATE (45s+)
            if self.baseline_rmssd is not None:
                self.is_phase_active = True
                self.recording_statusbar.setFormat(f"LOCKED: {self.baseline_rmssd:.1f}ms")
                self.recording_statusbar.setValue(total_calibration_time)

                # Dotted Line Logic
                if not hasattr(self, 'baseline_series'):
                    from PySide6.QtCharts import QLineSeries
                    from PySide6.QtGui import QPen
                    from PySide6.QtCore import Qt
                    
                    self.baseline_series = QLineSeries()
                    self.baseline_series.setName("Baseline RMSSD (ms)")
                    pen = QPen(QColor(220, 40, 40))
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
        self.recording_statusbar.setRange(0, status)

    def show_status(self, status: str, print_to_terminal=True):
        if "Connected" in status:
            self.is_phase_active = False
            if self.address_menu.currentText():
                parts = self.address_menu.currentText().split(",")
                if len(parts) >= 2:
                    _save_last_sensor(parts[0].strip(), parts[1].strip())
            
        if not self.is_phase_active:
            self.recording_statusbar.setFormat(status)
        
        # ALWAYS update the tiny status bar at the very bottom
        self.statusbar.showMessage(status)
        
        # ALWAYS print to the console for debugging
        if print_to_terminal:
            print(status)

    def emit_annotation(self):
        self.signals.annotation.emit(
            NamedSignal("Annotation", self.annotation.currentText())
        )

    def update_ui_with_mock_data(self):
        self.current_hr_label.setText("Heart Rate: 72 bpm")
        self.rmssd_label.setText("RMSSD: 45 ms")
        self.stress_ratio_label.setText("Stress Ratio (LF/HF): 1.2")

    def update_ui_labels(self, data: NamedSignal):
        # 1. RAW BEAT DATA (Heart Rate & Instant Faults)
        if data.name == "ibis":
            if len(data.value[1]) > 0:
                last_ibi_ms = data.value[1][-1]
                
                hr = 60000.0 / last_ibi_ms
                self.current_hr_label.setText(f"Heart Rate: {int(hr)} bpm")

                # LEVEL 1 FAULT: Total Dropout (3s+)
                if last_ibi_ms > 3000: 
                    self._fault_active = True
                    self._consecutive_good = 0
                    self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
                    self.health_label.setText("FAULT: Clearing Buffer...")
                    self.signals.request_buffer_reset.emit()
                    return

                # LEVEL 2 FAULT: Hard limits (HR > 200 or HR < 30)
                if last_ibi_ms > 2000 or last_ibi_ms < 300:
                    self._fault_active = True
                    self._consecutive_good = 0
                    self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
                    self.health_label.setText("Signal: DROP/NOISE")
                    return

                # LEVEL 3 FAULT: Adaptive — 30% deviation from rolling average
                recent_ibis = list(data.value[1])[-30:]
                if len(recent_ibis) >= 10:
                    avg_ibi = sum(recent_ibis) / len(recent_ibis)
                    deviation = abs(last_ibi_ms - avg_ibi) / avg_ibi
                    if deviation > 0.30:
                        self._fault_active = True
                        self._consecutive_good = 0
                        avg_hr = int(60000.0 / avg_ibi)
                        self.health_indicator.setStyleSheet("color: red; font-size: 18px;")
                        self.health_label.setText(f"Signal: ERRATIC (avg {avg_hr})")
                        return

                # Normal beat — count towards recovery
                if self._fault_active:
                    self._consecutive_good += 1
                    if self._consecutive_good >= 10:
                        self._fault_active = False
        
        # 2. FREQUENCY DATA (Stress Ratio)
        elif data.name == "stress_ratio":
            self.stress_ratio_label.setText(f"Stress Ratio (LF/HF): {data.value[0]:.2f}")

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
            elif rmssd_val > 150:
                self.health_indicator.setStyleSheet("color: orange; font-size: 18px;")
                self.health_label.setText("Signal: NOISY")
            else:
                self.health_indicator.setStyleSheet("color: #00FF00; font-size: 18px;")
                self.health_label.setText("Signal: GOOD")

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
                return

            elapsed = time.time() - self.start_time

            smooth_n = max(5, round(hr / 60 * SMOOTH_SECONDS))
            self._hr_smooth_buf.append(hr)
            while len(self._hr_smooth_buf) > smooth_n:
                self._hr_smooth_buf.pop(0)
            smoothed_hr = sum(self._hr_smooth_buf) / len(self._hr_smooth_buf)
            self.ibis_widget.time_series.append(elapsed, smoothed_hr)

            # EWMA trend line (weight 0.05 = smooth rolling average)
            if self._hr_ewma is None:
                self._hr_ewma = hr
            else:
                self._hr_ewma = 0.05 * hr + 0.95 * self._hr_ewma
            self.hr_trend_series.append(elapsed, self._hr_ewma)

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
