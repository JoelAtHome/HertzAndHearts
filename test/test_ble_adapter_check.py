"""BLE discovery error strings (no radio required)."""

from PySide6.QtBluetooth import QBluetoothDeviceDiscoveryAgent

from hnh import sensor


def test_discovery_error_powered_off_readable():
    msg = sensor._discovery_error_message(QBluetoothDeviceDiscoveryAgent.Error.PoweredOffError)
    assert msg
    assert "Bluetooth" in msg


def test_discovery_error_no_error_silent():
    assert sensor._discovery_error_message(QBluetoothDeviceDiscoveryAgent.Error.NoError) is None


def test_discovery_error_invalid_adapter_readable():
    msg = sensor._discovery_error_message(
        QBluetoothDeviceDiscoveryAgent.Error.InvalidBluetoothAdapterError
    )
    assert msg
    assert "adapter" in msg.lower()
