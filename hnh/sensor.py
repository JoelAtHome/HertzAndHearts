import struct
import numpy as np
from time import perf_counter_ns
from PySide6.QtCore import QObject, Signal, QByteArray, QUuid, QTimer
from PySide6.QtBluetooth import (
    QBluetoothDeviceDiscoveryAgent,
    QLowEnergyController,
    QLowEnergyService,
    QLowEnergyCharacteristic,
    QBluetoothUuid,
    QBluetoothDeviceInfo,
    QLowEnergyDescriptor,
)
from math import ceil
from typing import Union
from hnh.utils import get_sensor_address, get_sensor_remote_address
from hnh.config import COMPATIBLE_SENSORS, DEBUG
from hnh.perf_probe import get_perf_probe


def _decode_pmd_ecg_samples(raw_payload: bytes) -> list[float]:
    sample_bytes = (len(raw_payload) // 3) * 3
    if sample_bytes == 0:
        return []
    packed = (
        np.frombuffer(raw_payload[:sample_bytes], dtype=np.uint8)
        .reshape(-1, 3)
        .astype(np.int32, copy=False)
    )
    values = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
    values[values >= 0x800000] -= 0x1000000
    return (values.astype(np.float64, copy=False) * 0.001).tolist()


class SensorScanner(QObject):
    sensor_update = Signal(object)
    status_update = Signal(str)

    def __init__(self):
        super().__init__()
        self.scanner = QBluetoothDeviceDiscoveryAgent()
        self.scanner.setLowEnergyDiscoveryTimeout(10000)
        self.scanner.finished.connect(self._handle_scan_result)
        self.scanner.errorOccurred.connect(self._handle_scan_error)

    def scan(self):
        if self.scanner.isActive():
            self.status_update.emit("Already searching for sensors.")
            return
        self.status_update.emit("Scanning for BLE sensors...")
        self.scanner.start(QBluetoothDeviceDiscoveryAgent.LowEnergyMethod)

    def _handle_scan_result(self):
        sensors: list[QBluetoothDeviceInfo] = [
            d
            for d in self.scanner.discoveredDevices()
            if (any(cs in d.name() for cs in COMPATIBLE_SENSORS)) and (d.rssi() <= 0)
        ]  # https://www.mokoblue.com/measures-of-bluetooth-rssi/
        if not sensors:
            self.status_update.emit("Couldn't find sensors.")
            return
        self.sensor_update.emit(sensors)
        self.status_update.emit(f"Found {len(sensors)} sensor(s).")

    def _handle_scan_error(self, error):
        print(error)


class SensorClient(QObject):
    """
    Connect to an ECG sensor that acts as a Bluetooth server / peripheral.
    On Windows, the sensor must already be paired with the machine running
    Hertz & Hearts. Pairing isn't implemented in Qt6.

    In Qt terminology client=central, server=peripheral.
    """

    ibi_update = Signal(object)
    ecg_update = Signal(object)
    ecg_ready = Signal()
    status_update = Signal(str)
    battery_update = Signal(int)  # 0-100 percent, or -1 if unknown/unsupported
    verity_limited_support = Signal()

    PMD_SERVICE_UUID = QBluetoothUuid(QUuid("{FB005C80-02E7-F387-1CAD-8ACD2D8DF0C8}"))
    PMD_CONTROL_UUID = QBluetoothUuid(QUuid("{FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8}"))
    PMD_DATA_UUID = QBluetoothUuid(QUuid("{FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8}"))

    ECG_START_COMMAND = QByteArray(bytes([
        0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00
    ]))
    ECG_STOP_COMMAND = QByteArray(bytes([0x03, 0x00]))

    # Standard BLE Battery Service (0x180F) and Battery Level characteristic (0x2A19)
    BATTERY_SERVICE_UUID = QBluetoothUuid(0x180F)
    BATTERY_LEVEL_UUID = QBluetoothUuid(0x2A19)

    def __init__(self):
        super().__init__()
        self._perf_probe = get_perf_probe()
        self.client: Union[None, QLowEnergyController] = None
        self.hr_service: Union[None, QLowEnergyService] = None
        self.hr_notification: Union[None, QLowEnergyDescriptor] = None
        self.pmd_service: Union[None, QLowEnergyService] = None
        self.pmd_data_notification: Union[None, QLowEnergyDescriptor] = None
        self._ecg_streaming = False
        self._pmd_ready = False
        self._ecg_start_pending = False
        self._ecg_data_received = False
        self._pmd_descriptors_pending = 0
        self.battery_service: Union[None, QLowEnergyService] = None
        self._battery_timer = QTimer(self)
        self._battery_timer.setInterval(90_000)  # 90 seconds
        self._battery_timer.timeout.connect(self._read_battery)
        self.ENABLE_NOTIFICATION: QByteArray = QByteArray.fromHex(b"0100")
        self.DISABLE_NOTIFICATION: QByteArray = QByteArray.fromHex(b"0000")
        self.HR_SERVICE: QBluetoothUuid.ServiceClassUuid = (
            QBluetoothUuid.ServiceClassUuid.HeartRate
        )
        self.HR_CHARACTERISTIC: QBluetoothUuid.CharacteristicType = (
            QBluetoothUuid.CharacteristicType.HeartRateMeasurement
        )
        self._connected_device_name: str = ""
        self._verity_warning_emitted = False

    def _sensor_address(self):
        return get_sensor_remote_address(self.client)

    def connect_client(self, sensor: QBluetoothDeviceInfo):
        if self.client is not None:
            msg = (
                f"Currently connected to sensor at {self._sensor_address()}."
                " Please disconnect before (re-)connecting to (another) sensor."
            )
            self.status_update.emit(msg)
            return
        self.status_update.emit(
            f"Connecting to sensor at {get_sensor_address(sensor)} (this might take a while)."
        )
        self._connected_device_name = sensor.name() or ""
        self._verity_warning_emitted = False
        self.client = QLowEnergyController.createCentral(sensor)
        self.client.errorOccurred.connect(self._catch_error)
        self.client.connected.connect(self._discover_services)
        self.client.discoveryFinished.connect(self._connect_hr_service)
        self.client.disconnected.connect(self._reset_connection)
        self.client.connectToDevice()

    def disconnect_client(self):
        try:
            self.stop_ecg_stream()
        except Exception:
            pass
        try:
            if self.pmd_data_notification is not None and self.pmd_service is not None:
                if self.pmd_data_notification.isValid():
                    self.pmd_service.writeDescriptor(
                        self.pmd_data_notification, self.DISABLE_NOTIFICATION
                    )
        except Exception:
            pass
        try:
            if self.hr_notification is not None and self.hr_service is not None:
                if self.hr_notification.isValid():
                    self.hr_service.writeDescriptor(
                        self.hr_notification, self.DISABLE_NOTIFICATION
                    )
        except Exception:
            pass
        if self.client is not None:
            try:
                self.status_update.emit(
                    f"Disconnecting from sensor at {self._sensor_address()}."
                )
                self.client.disconnectFromDevice()
            except Exception:
                self._reset_connection()

    def _discover_services(self):
        if self.client is not None:
            self.client.discoverServices()

    def _connect_hr_service(self):
        if self.client is None:
            return
        hr_service: list[QBluetoothUuid] = [
            s for s in self.client.services() if s == self.HR_SERVICE
        ]
        if not hr_service:
            print(f"Couldn't find HR service on {self._sensor_address()}.")
            return
        self.hr_service = self.client.createServiceObject(hr_service[0])
        if not self.hr_service:
            print(
                f"Couldn't establish connection to HR service on {self._sensor_address()}."
            )
            return
        self.hr_service.stateChanged.connect(self._start_hr_notification)
        self.hr_service.characteristicChanged.connect(self._data_handler)
        self.hr_service.discoverDetails()

        self._connect_battery_service()

        pmd_uuid_str = self.PMD_SERVICE_UUID.toString().lower()
        pmd_match = [
            s for s in self.client.services()
            if s.toString().lower() == pmd_uuid_str
        ]
        if not pmd_match:
            if DEBUG:
                print(f"PMD service not found. Available services:")
                for s in self.client.services():
                    print(f"  {s.toString()}")
            return
        self.pmd_service = self.client.createServiceObject(pmd_match[0])
        if self.pmd_service:
            self.pmd_service.stateChanged.connect(self._start_pmd_notification)
            self.pmd_service.characteristicChanged.connect(self._pmd_data_handler)
            self.pmd_service.characteristicWritten.connect(self._pmd_write_confirmed)
            self.pmd_service.descriptorWritten.connect(self._pmd_descriptor_written)
            self.pmd_service.errorOccurred.connect(self._pmd_error)
            self.pmd_service.discoverDetails()
        else:
            print(f"Couldn't establish connection to PMD service on {self._sensor_address()}.")

    def _connect_battery_service(self):
        """Connect to BLE Battery Service (0x180F) if available. Polar H10 and many HR sensors support it."""
        if self.client is None:
            return
        battery_match = [
            s for s in self.client.services()
            if s == self.BATTERY_SERVICE_UUID
        ]
        if not battery_match:
            self.battery_update.emit(-1)
            return
        self.battery_service = self.client.createServiceObject(battery_match[0])
        if not self.battery_service:
            self.battery_update.emit(-1)
            return
        self.battery_service.stateChanged.connect(self._on_battery_service_ready)
        self.battery_service.characteristicRead.connect(self._on_battery_level_read)
        self.battery_service.discoverDetails()

    def _on_battery_service_ready(self, state: QLowEnergyService.ServiceState):
        if state != QLowEnergyService.RemoteServiceDiscovered:
            return
        if self.battery_service is None:
            return
        self._read_battery()
        self._battery_timer.start()

    def _read_battery(self):
        if self.battery_service is None:
            return
        char = self.battery_service.characteristic(self.BATTERY_LEVEL_UUID)
        if char.isValid():
            self.battery_service.readCharacteristic(char)

    def _on_battery_level_read(self, char: QLowEnergyCharacteristic, value: QByteArray):
        data = value.data()
        if len(data) >= 1:
            level = min(100, max(0, data[0]))
            self.battery_update.emit(level)
        else:
            self.battery_update.emit(-1)

    def _start_hr_notification(self, state: QLowEnergyService.ServiceState):
        if state != QLowEnergyService.RemoteServiceDiscovered:
            return
        if self.hr_service is None:
            return
        hr_char: QLowEnergyCharacteristic = self.hr_service.characteristic(
            self.HR_CHARACTERISTIC
        )
        if not hr_char.isValid():
            print(f"Couldn't find HR characterictic on {self._sensor_address()}.")
        self.hr_notification = hr_char.descriptor(
            QBluetoothUuid.DescriptorType.ClientCharacteristicConfiguration
        )
        if not self.hr_notification.isValid():
            print("HR characteristic is invalid.")
        self.hr_service.writeDescriptor(self.hr_notification, self.ENABLE_NOTIFICATION)
        self.status_update.emit(f"Connected to {self._sensor_address()}")
        if not self._verity_warning_emitted and "verity" in self._connected_device_name.lower():
            self._verity_warning_emitted = True
            self.verity_limited_support.emit()

    def _start_pmd_notification(self, state: QLowEnergyService.ServiceState):
        if state != QLowEnergyService.RemoteServiceDiscovered:
            return
        if self.pmd_service is None:
            return

        ctrl_uuid_str = self.PMD_CONTROL_UUID.toString().lower()
        pmd_data_uuid_str = self.PMD_DATA_UUID.toString().lower()
        self._pmd_descriptors_pending = 0

        ctrl_char = None
        data_char = None
        for c in self.pmd_service.characteristics():
            uuid_str = c.uuid().toString().lower()
            if uuid_str == ctrl_uuid_str:
                ctrl_char = c
            elif uuid_str == pmd_data_uuid_str:
                data_char = c

        if ctrl_char is not None:
            ctrl_desc = ctrl_char.descriptor(
                QBluetoothUuid.DescriptorType.ClientCharacteristicConfiguration
            )
            if ctrl_desc.isValid():
                self._pmd_descriptors_pending += 1
                self.pmd_service.writeDescriptor(ctrl_desc, self.ENABLE_NOTIFICATION)

        if data_char is not None:
            self.pmd_data_notification = data_char.descriptor(
                QBluetoothUuid.DescriptorType.ClientCharacteristicConfiguration
            )
            if self.pmd_data_notification.isValid():
                self._pmd_descriptors_pending += 1
                self.pmd_service.writeDescriptor(self.pmd_data_notification, self.ENABLE_NOTIFICATION)
            else:
                print("PMD data descriptor is invalid.")
        else:
            print("PMD data characteristic not found!")

        if self._pmd_descriptors_pending == 0:
            self._finalize_pmd_ready()

    def _pmd_descriptor_written(self, descriptor, value):
        self._pmd_descriptors_pending = max(0, self._pmd_descriptors_pending - 1)
        if self._pmd_descriptors_pending == 0:
            self._finalize_pmd_ready()

    def _finalize_pmd_ready(self):
        if self._pmd_ready:
            return
        self._pmd_ready = True
        self.start_ecg_stream()

    def start_ecg_stream(self):
        if self.pmd_service is None:
            print("Cannot start ECG: PMD service not available.")
            return
        if not self._pmd_ready:
            self._ecg_start_pending = True
            return
        ctrl_uuid_str = self.PMD_CONTROL_UUID.toString().lower()
        ctrl_char = self.pmd_service.characteristic(self.PMD_CONTROL_UUID)
        if not ctrl_char.isValid():
            for c in self.pmd_service.characteristics():
                if c.uuid().toString().lower() == ctrl_uuid_str:
                    ctrl_char = c
                    break
        if ctrl_char.isValid():
            self.pmd_service.writeCharacteristic(ctrl_char, self.ECG_START_COMMAND)
            self._ecg_streaming = True
            self.status_update.emit("ECG streaming started.")
        else:
            print("Cannot start ECG: control characteristic not found.")

    def stop_ecg_stream(self):
        if self.pmd_service is None or not self._ecg_streaming:
            return
        ctrl_char = self.pmd_service.characteristic(self.PMD_CONTROL_UUID)
        if not ctrl_char.isValid():
            ctrl_uuid_str = self.PMD_CONTROL_UUID.toString().lower()
            for c in self.pmd_service.characteristics():
                if c.uuid().toString().lower() == ctrl_uuid_str:
                    ctrl_char = c
                    break
        if ctrl_char.isValid():
            self.pmd_service.writeCharacteristic(ctrl_char, self.ECG_STOP_COMMAND)
            self._ecg_streaming = False

    def _pmd_write_confirmed(self, char: QLowEnergyCharacteristic, value: QByteArray):
        if DEBUG:
            print(f"PMD write confirmed: char={char.uuid().toString()}")

    def _pmd_error(self, error):
        print(f"PMD service error: {error}. ECG will be unavailable.")
        self._pmd_ready = False
        self._ecg_streaming = False
        self._ecg_start_pending = False
        self._ecg_data_received = False
        self._remove_pmd_service()

    def _pmd_data_handler(self, char: QLowEnergyCharacteristic, data: QByteArray):
        raw = data.data()
        if len(raw) < 10:
            return
        if raw[0] != 0x00:
            return
        payload = raw[10:]
        start_ns = perf_counter_ns()
        samples = _decode_pmd_ecg_samples(payload)
        elapsed_ns = perf_counter_ns() - start_ns
        sample_bytes = (len(payload) // 3) * 3
        truncated = max(0, len(payload) - sample_bytes)
        self._perf_probe.note_decode(
            sample_count=len(samples),
            payload_bytes=len(payload),
            truncated_bytes=truncated,
            elapsed_ns=elapsed_ns,
        )
        if samples:
            if not self._ecg_data_received:
                self._ecg_data_received = True
                self.ecg_ready.emit()
            self.ecg_update.emit(samples)

    def _reset_connection(self):
        try:
            addr = self._sensor_address()
        except Exception:
            addr = "unknown"
        print(f"Discarding sensor at {addr}.")
        self._ecg_streaming = False
        self._pmd_ready = False
        self._ecg_start_pending = False
        self._ecg_data_received = False
        self._pmd_descriptors_pending = 0
        self._battery_timer.stop()
        self.battery_update.emit(-1)
        self._remove_battery_service()
        self._remove_pmd_service()
        self._remove_service()
        self._remove_client()

    def _remove_battery_service(self):
        if self.battery_service is None:
            return
        try:
            self.battery_service.stateChanged.disconnect()
            self.battery_service.characteristicRead.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.battery_service.deleteLater()
        except Exception as e:
            if DEBUG:
                print(f"Couldn't remove battery service: {e}")
        finally:
            self.battery_service = None

    def _remove_pmd_service(self):
        if self.pmd_service is None:
            return
        try:
            self.pmd_service.stateChanged.disconnect()
            self.pmd_service.characteristicChanged.disconnect()
            self.pmd_service.characteristicWritten.disconnect()
            self.pmd_service.descriptorWritten.disconnect()
            self.pmd_service.errorOccurred.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.pmd_service.deleteLater()
        except Exception as e:
            print(f"Couldn't remove PMD service: {e}")
        finally:
            self.pmd_service = None
            self.pmd_data_notification = None

    def _remove_service(self):
        if self.hr_service is None:
            return
        try:
            self.hr_service.stateChanged.disconnect()
            self.hr_service.characteristicChanged.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.hr_service.deleteLater()
        except Exception as e:
            print(f"Couldn't remove service: {e}")
        finally:
            self.hr_service = None
            self.hr_notification = None

    def _remove_client(self):
        if self.client is None:
            return
        try:
            self.client.errorOccurred.disconnect()
            self.client.connected.disconnect()
            self.client.discoveryFinished.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.client.disconnected.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.client.deleteLater()
        except Exception as e:
            print(f"Couldn't remove client: {e}")
        finally:
            self.client = None

    def _catch_error(self, error):
        try:
            self.status_update.emit(f"An error occurred: {error}. Disconnecting sensor.")
        except Exception:
            pass
        try:
            self._reset_connection()
        except Exception as e:
            print(f"Error during cleanup: {e}")
            self.pmd_service = None
            self.pmd_data_notification = None
            self.hr_service = None
            self.hr_notification = None
            self.client = None

    def _data_handler(self, _, data: QByteArray):  # _ is unused but mandatory argument
        """
        `data` is formatted according to the
        "GATT Characteristic and Object Type 0x2A37 Heart Rate Measurement"
        which is one of the three characteristics included in the
        "GATT Service 0x180D Heart Rate".

        `data` can include the following bytes:
        - flags
            Always present.
            - bit 0: HR format (uint8 vs. uint16)
            - bit 1, 2: sensor contact status
            - bit 3: energy expenditure status
            - bit 4: RR interval status
        - HR
            Encoded by one or two bytes depending on flags/bit0. One byte is
            always present (uint8). Two bytes (uint16) are necessary to
            represent HR > 255.
        - energy expenditure
            Encoded by 2 bytes. Only present if flags/bit3.
        - inter-beat-intervals (IBIs)
            One IBI is encoded by 2 consecutive bytes. Up to 18 bytes depending
            on presence of uint16 HR format and energy expenditure.
        """
        heart_rate_measurement_bytes: bytes = data.data()

        # self.status_update.emit("Sensor Connected and Streaming Data")

        byte0: int = heart_rate_measurement_bytes[0]
        uint8_format: bool = (byte0 & 1) == 0
        energy_expenditure: bool = ((byte0 >> 3) & 1) == 1
        rr_interval: bool = ((byte0 >> 4) & 1) == 1

        if not rr_interval:
            return

        first_rr_byte: int = 2
        if uint8_format:
            # hr = data[1]
            pass
        else:
            # hr = (data[2] << 8) | data[1] # uint16
            first_rr_byte += 1
        if energy_expenditure:
            # ee = (data[first_rr_byte + 1] << 8) | data[first_rr_byte]
            first_rr_byte += 2

        for i in range(first_rr_byte, len(heart_rate_measurement_bytes), 2):
            ibi: int = (
                heart_rate_measurement_bytes[i + 1] << 8
            ) | heart_rate_measurement_bytes[i]
            # Polar H7, H9, and H10 record IBIs in 1/1024 seconds format.
            # Convert 1/1024 sec format to milliseconds.
            # TODO: move conversion to model and only convert if sensor doesn't
            # transmit data in milliseconds.
            ibi = ceil(ibi / 1024 * 1000)
            self.ibi_update.emit(ibi)
