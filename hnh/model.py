import numpy as np
import statistics
import math
from collections import deque
from itertools import islice
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtBluetooth import QBluetoothDeviceInfo
from hnh.utils import get_sensor_address, sign, NamedSignal
from hnh.config import (
    tick_to_breathing_rate,
    HRV_BUFFER_SIZE,
    IBI_BUFFER_SIZE,
    MAX_BREATHING_RATE,
    MIN_IBI,
    MAX_IBI,
    MIN_HRV_TARGET,
    MAX_HRV_TARGET,
    ECG_SAMPLE_RATE,
)
from hnh.settings import Settings
from hnh.qtc import QtcConfig, compute_qtc_payload_from_ecg
from hnh.session_artifacts import default_qtc_payload


class Model(QObject):
    ibis_buffer_update = Signal(NamedSignal)
    hrv_update = Signal(NamedSignal)
    addresses_update = Signal(NamedSignal)
    pacer_rate_update = Signal(NamedSignal)
    hrv_target_update = Signal(NamedSignal)
    stress_ratio_update = Signal(NamedSignal)
    qtc_update = Signal(NamedSignal)

    def clear_buffers(self):
        """Wipes the data history to allow rapid recovery from noise."""
        self.ibis_buffer.clear()
        self.hrv_buffer.clear()
        self.rr_intervals.clear()
        self._ecg_buffer.clear()
        self._ecg_samples_since_qtc = 0
        self._ecg_total_samples = 0
        self.latest_qtc_payload = default_qtc_payload()
        self.ewma_hrv = 1.0

    def __init__(self):
        super().__init__()
        self._settings = Settings()
        self.lf_hf_ratio = 0
        self.ibis_buffer: deque[int] = deque(maxlen=IBI_BUFFER_SIZE)
        self.ibis_seconds: deque[float] = deque(
            map(float, range(-IBI_BUFFER_SIZE, 1)), IBI_BUFFER_SIZE
        )
        self.hrv_buffer: deque[float] = deque(maxlen=HRV_BUFFER_SIZE)
        self.hrv_seconds: deque[float] = deque(
            map(float, range(-HRV_BUFFER_SIZE, 1)), HRV_BUFFER_SIZE
        )

        # Exponentially Weighted Moving Average:
        # - https://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average
        # - https://en.wikipedia.org/wiki/Exponential_smoothing
        # - http://nestedsoftware.com/2018/04/04/exponential-moving-average-on-streaming-data-4hhl.24876.html
        self.ewma_hrv: float = 1.0
        self.sensors: list[QBluetoothDeviceInfo] = []
        self.breathing_rate: float = float(MAX_BREATHING_RATE)
        self.hrv_target: int = math.ceil((MIN_HRV_TARGET + MAX_HRV_TARGET) / 2)
        self._last_ibi_phase: int = -1
        self._last_ibi_extreme: int = 0
        self._duration_current_phase: int = 0
        self.rr_intervals = deque(maxlen=IBI_BUFFER_SIZE)
        self.rmssd = 0.0
        self.update_counter = 0
        self._ecg_buffer: deque[float] = deque(maxlen=ECG_SAMPLE_RATE * 120)
        self._ecg_samples_since_qtc = 0
        self._ecg_total_samples = 0
        self.latest_qtc_payload: dict = default_qtc_payload()


    def hr_handler(self, rr_ms):
        try:
            self.current_hr = int(60000 / rr_ms)
            self.rr_intervals.append(rr_ms)
            
            if len(self.rr_intervals) > 1:
                diffs = np.diff(list(self.rr_intervals))
                self.rmssd = np.sqrt(np.mean(np.square(diffs)))
                # print(f"BPM: {self.current_hr} | RMSSD: {self.rmssd:.2f}")
             
        except Exception as e:
            print(f"!!! ERROR: {e}")


    @Slot(int)
    def update_ibis_buffer(self, ibi: int):
        validated_ibi = self.validate_ibi(ibi)
        self.update_ibis_seconds(validated_ibi / 1000)
        self.ibis_buffer.append(validated_ibi)
        self.ibis_buffer_update.emit(
            NamedSignal("ibis", (self.ibis_seconds, self.ibis_buffer))
        )

        if len(self.ibis_buffer) > 1:
            diff = abs(self.ibis_buffer[-1] - self.ibis_buffer[-2])
            self.update_hrv_buffer(diff)

        self.update_counter += 1
        if self.update_counter % 5 == 0:
            self.compute_local_hrv()

    @Slot(object)
    def update_ecg_samples(self, samples):
        if not samples:
            return
        try:
            self._ecg_buffer.extend(float(x) for x in samples)
        except Exception:
            return
        self._ecg_total_samples += len(samples)
        self._ecg_samples_since_qtc += len(samples)
        # Recompute every ~2 seconds of incoming ECG.
        if self._ecg_samples_since_qtc >= ECG_SAMPLE_RATE * 2:
            self._ecg_samples_since_qtc = 0
            self._compute_qtc()

    
    @Slot(int)
    def update_breathing_rate(self, breathing_tick: int):
        self.breathing_rate = tick_to_breathing_rate(breathing_tick)
        self.pacer_rate_update.emit(NamedSignal("PacerRate", self.breathing_rate))

    @Slot(int)
    def update_hrv_target(self, hrv_target: int):
        self.hrv_target = hrv_target
        self.hrv_target_update.emit(NamedSignal("HrvTarget", hrv_target))

    @Slot(object)
    def update_sensors(self, sensors: list[QBluetoothDeviceInfo]):
        self.sensors = sensors
        self.addresses_update.emit(
            NamedSignal(
                "Sensors", [f"{s.name()}, {get_sensor_address(s)}" for s in sensors]
            )
        )

    def validate_ibi(self, ibi: int) -> int:
        # If the buffer is empty or too small, just return the raw IBI 
        # so we can establish the connection!
        if len(self.ibis_buffer) < self._settings.IBI_MEDIAN_WINDOW:
            return ibi
        validated_ibi: int = ibi
        if ibi < MIN_IBI or ibi > MAX_IBI:
            median_ibi: int = math.ceil(
                statistics.median(
                    islice(
                        self.ibis_buffer,
                        len(self.ibis_buffer) - self._settings.IBI_MEDIAN_WINDOW,
                        None,
                    )
                )
            )
            if median_ibi < MIN_IBI:
                validated_ibi = MIN_IBI
            elif median_ibi > MAX_IBI:
                validated_ibi = MAX_IBI
            else:
                validated_ibi = median_ibi
            if self._settings.DEBUG:
                print(f"Correcting outlier IBI {ibi} to {validated_ibi}")

        return validated_ibi

    def validate_hrv(self, hrv: int) -> int:
        validated_hrv: int = hrv
        if hrv > MAX_HRV_TARGET:
            validated_hrv = min(math.ceil(self.ewma_hrv), MAX_HRV_TARGET)
            if self._settings.DEBUG:
                print(f"Correcting outlier HRV {hrv} to {validated_hrv}")

        return validated_hrv

    def compute_local_hrv(self):
        # Wait until we have enough RR samples before spectral analysis.
        if len(self.rr_intervals) < self._settings.FREQUENCY_WINDOW_SIZE:
            return
        try:
            from scipy.signal import welch

            rr_ms = np.asarray(list(self.rr_intervals), dtype=float)
            if rr_ms.size < 4:
                return

            # Convert irregular RR timestamps to seconds.
            rr_sec = rr_ms / 1000.0
            t_beats = np.cumsum(rr_sec)
            t_beats = t_beats - t_beats[0]

            # Interpolate RR tachogram onto an evenly sampled grid for PSD.
            fs = 4.0  # standard resampling rate for HRV spectral estimates
            t_uniform = np.arange(0.0, t_beats[-1], 1.0 / fs)
            if t_uniform.size < 8:
                return
            rr_uniform = np.interp(t_uniform, t_beats, rr_sec)
            rr_uniform = rr_uniform - np.mean(rr_uniform)

            freqs, psd = welch(rr_uniform, fs=fs, nperseg=min(256, rr_uniform.size))
            if freqs.size == 0 or psd.size == 0:
                return

            lf_mask = (freqs >= 0.04) & (freqs < 0.15)
            hf_mask = (freqs >= 0.15) & (freqs < 0.40)
            lf_power = float(np.trapezoid(psd[lf_mask], freqs[lf_mask])) if np.any(lf_mask) else 0.0
            hf_power = float(np.trapezoid(psd[hf_mask], freqs[hf_mask])) if np.any(hf_mask) else 0.0

            stress_val = float(lf_power / hf_power) if hf_power > 1e-12 else 0.0
            if self._settings.DEBUG:
                print(f"--- FREQUENCY MATH UNLOCKED ---")
                print(f"STRESS RATIO: {stress_val:.2f}")
            self.stress_ratio_update.emit(NamedSignal(name="stress_ratio", value=[stress_val]))
        except Exception as e:
            print(f"!!! MATH ERROR: {e}")

    def update_hrv_buffer(self, local_hrv: float):
        self.ewma_hrv = (
            self._settings.EWMA_WEIGHT_CURRENT_SAMPLE * self.validate_hrv(local_hrv)
            + (1 - self._settings.EWMA_WEIGHT_CURRENT_SAMPLE) * self.ewma_hrv
        )

        ibi_list = list(self.ibis_buffer)
        if len(ibi_list) >= 3:
            window = ibi_list[-self._settings.RMSSD_WINDOW:]
            diffs = np.diff(window)
            rmssd = float(np.sqrt(np.mean(np.square(diffs))))
        else:
            rmssd = self.ewma_hrv

        self.hrv_buffer.append(rmssd)
        self.hrv_update.emit(
            NamedSignal("hrv", (self.hrv_seconds, self.hrv_buffer))
        )

    def update_ibis_seconds(self, seconds: float):
        # 1. Clean the data: Ensure we only subtract from numbers
        new_seconds = []
        for val in self.ibis_seconds:
            try:
                # If it's a number, subtract.
                new_seconds.append(float(val) - seconds)
            except (ValueError, TypeError):
                continue
                
        # 2. Rebuild the deque
        self.ibis_seconds = deque(new_seconds, maxlen=IBI_BUFFER_SIZE)
        
        # 3. Add the new '0' point for the latest beat
        self.ibis_seconds.append(0.0)

    def update_hrv_seconds(self, seconds: float):
        """Standard rolling window update for the HRV chart."""
        self.hrv_seconds = deque(
            [i - seconds for i in self.hrv_seconds], HRV_BUFFER_SIZE
        )
        self.hrv_seconds.append(0.0)

    def _compute_qtc(self):
        if len(self._ecg_buffer) < ECG_SAMPLE_RATE * 5:
            return
        cfg = QtcConfig(
            sampling_rate=ECG_SAMPLE_RATE,
            summary_window_seconds=int(self._settings.QTC_SUMMARY_WINDOW_SECONDS),
            min_valid_beats=int(self._settings.QTC_MIN_VALID_BEATS),
            fridericia_hr_low_threshold=int(self._settings.QTC_FRIDERICIA_HR_LOW_THRESHOLD),
            fridericia_hr_high_threshold=int(self._settings.QTC_FRIDERICIA_HR_HIGH_THRESHOLD),
            fridericia_hysteresis_bpm=int(self._settings.QTC_FRIDERICIA_HYSTERESIS_BPM),
            max_rr_gap_seconds=float(self._settings.QTC_MAX_RR_GAP_SECONDS),
            trend_enabled=bool(self._settings.QTC_TREND_ENABLED),
            default_formula="bazett",
        )
        payload = compute_qtc_payload_from_ecg(list(self._ecg_buffer), cfg)
        trend_point = payload.get("trend_point")
        if isinstance(trend_point, dict):
            trend_point["t_sec"] = float(self._ecg_total_samples) / float(ECG_SAMPLE_RATE)
            if not payload.get("quality", {}).get("is_valid", False):
                trend_point["is_low_quality"] = True
        self.latest_qtc_payload = payload
        self.qtc_update.emit(NamedSignal(name="qtc", value=payload))
