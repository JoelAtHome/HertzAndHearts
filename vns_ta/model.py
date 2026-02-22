import numpy as np
from hrvanalysis import get_time_domain_features, get_frequency_domain_features
import statistics
import math
from collections import deque
from itertools import islice
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtBluetooth import QBluetoothDeviceInfo
from vns_ta.utils import get_sensor_address, sign, NamedSignal
from vns_ta.config import (
    tick_to_breathing_rate,
    HRV_BUFFER_SIZE,
    IBI_BUFFER_SIZE,
    MAX_BREATHING_RATE,
    MIN_IBI,
    MAX_IBI,
    MIN_HRV_TARGET,
    MAX_HRV_TARGET,
)
from vns_ta.settings import Settings


class Model(QObject):
    ibis_buffer_update = Signal(NamedSignal)
    hrv_update = Signal(NamedSignal)
    addresses_update = Signal(NamedSignal)
    pacer_rate_update = Signal(NamedSignal)
    hrv_target_update = Signal(NamedSignal)
    stress_ratio_update = Signal(NamedSignal)

    def clear_buffers(self):
        """Wipes the data history to allow rapid recovery from noise."""
        self.ibis_buffer.clear()
        self.hrv_buffer.clear()
        self.rr_intervals.clear()
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
    # 1. Wait until we have 56 samples (about 1 minute of data)
        if len(self.rr_intervals) < self._settings.FREQUENCY_WINDOW_SIZE:
            return
        try:
            from hrvanalysis import get_frequency_domain_features
            features = get_frequency_domain_features(list(self.rr_intervals))
            stress_val = features['lf_hf_ratio']
            if self._settings.DEBUG:
                print(f"--- FREQUENCY MATH UNLOCKED ---")
                print(f"STRESS RATIO: {stress_val:.2f}")
            # 6. This tells the UI to update the number on your screen
            self.stress_ratio_update.emit(NamedSignal(name="stress_ratio", value=[stress_val]))
        except Exception as e:
        # This will tell us if anything else goes wrong
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
