import platform
from pathlib import Path
from collections import namedtuple
from PySide6.QtBluetooth import QBluetoothDeviceInfo


NamedSignal = namedtuple("NamedSignal", "name value")


def get_sensor_address(sensor: QBluetoothDeviceInfo) -> str:
    """Return MAC (Windows, Linux) or UUID (macOS)."""
    system = platform.system()
    sensor_address = ""
    if system in ["Linux", "Windows"]:
        sensor_address = sensor.address().toString()
    elif system == "Darwin":
        sensor_address = sensor.deviceUuid().toString().strip("{}")

    return sensor_address


def get_sensor_remote_address(sensor) -> str:
    """Return MAC (Windows, Linux) or UUID (macOS)."""
    system = platform.system()
    sensor_remote_address = ""
    if system in ["Linux", "Windows"]:
        sensor_remote_address = sensor.remoteAddress().toString()
    elif system == "Darwin":
        sensor_remote_address = sensor.remoteDeviceUuid().toString().strip("{}")

    return sensor_remote_address
