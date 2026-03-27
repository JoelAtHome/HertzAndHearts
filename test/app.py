import math
import time
import uuid
from random import randint
from PySide6.QtCore import QObject, Signal, QTimer
from hnh.utils import get_sensor_address


class MockBluetoothMac:
    def __init__(self, mac):
        self._mac = mac

    def toString(self):
        return self._mac


class MockBluetoothUuid:
    def __init__(self, uuid):
        self._uuid = uuid

    def toString(self):
        return f"{self._uuid}"


class MockSensor:
    def __init__(self):
        self._mac = MockBluetoothMac(
            ":".join([f"{randint(0, 255):02x}" for _ in range(6)])
        )
        self._uuid = MockBluetoothUuid(uuid.uuid4())
        self._name = "MockSensor"

    def name(self):
        return self._name

    def address(self):
        return self._mac

    def deviceUuid(self):
        return self._uuid


class MockSensorScanner(QObject):
    sensor_update = Signal(object)
    status_update = Signal(str)
    scanning_state = Signal(bool)

    def scan(self) -> bool:
        polar_sensors = [MockSensor() for _ in range(3)]
        self.sensor_update.emit(polar_sensors)
        self.status_update.emit(f"Found {len(polar_sensors)} sensor(s).")
        return True


class MockSensorClient(QObject):
    ibi_update = Signal(object)
    ecg_update = Signal(object)
    ecg_ready = Signal()
    status_update = Signal(str)
    battery_update = Signal(int)
    verity_limited_support = Signal()
    diagnostic_logged = Signal(object)

    def __init__(self):
        super().__init__()
        # Polar sensor emits a (package of) IBI(s) about every second.
        # Here we "emit" / simulate IBI(s) in quicker succession in order to push the rendering.
        self.mean_ibi = 900
        self.timer = QTimer()
        self.timer.setInterval(self.mean_ibi)
        self.timer.timeout.connect(self.simulate_ibi)
        self.client = None

    def connect_client(self, sensor):
        self.status_update.emit(
            f"Connecting to sensor at {get_sensor_address(sensor)}."
        )
        self.client = object()
        self.ecg_ready.emit()
        self.timer.start()

    def connect_host(self, host: str, port: int):
        self.status_update.emit(f"Connecting to Phone Bridge at {host}:{int(port)}...")
        self.client = object()
        self.ecg_ready.emit()
        self.timer.start()

    def disconnect_client(self):
        self.status_update.emit("Disconnecting from sensor.")
        self.client = None
        self.timer.stop()

    def simulate_ibi(self):
        # IBIs fluctuate at a rate of `breathing_rate`
        # in a sinusoidal pattern around `mean_ibi`,
        # in a range of `range_ibi`.
        breathing_rate = 6
        range_ibi = 100  # without noise, HRV settles at this value
        ibi = self.mean_ibi + (range_ibi / 2) * math.sin(
            2 * math.pi * breathing_rate / 60 * time.time()
        )
        # add noise spikes
        if randint(1, 30) == 1:
            if randint(1, 2) == 1:
                ibi += 500
            else:
                ibi -= 500
        self.ibi_update.emit(ibi)


def main():
    """Mock sensor classes.

    Mock classes need to replace their mocked counterparts in namespace before
    the latter are imported elsewhere:
    https://stackoverflow.com/questions/3765222/monkey-patch-python-class
    """
    from hnh import sensor  # noqa

    sensor.SensorClient = MockSensorClient
    sensor.SensorScanner = MockSensorScanner

    from hnh.app import main as mock_main  # noqa

    mock_main()


if __name__ == "__main__":
    main()
