import json
import socket
import struct
import os
import platform
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from time import perf_counter_ns
from PySide6.QtCore import QObject, Signal, QByteArray, QUuid, QTimer, qVersion
from PySide6.QtBluetooth import (
    QBluetoothDeviceDiscoveryAgent,
    QBluetoothLocalDevice,
    QLowEnergyController,
    QLowEnergyService,
    QLowEnergyCharacteristic,
    QBluetoothUuid,
    QBluetoothDeviceInfo,
    QLowEnergyDescriptor,
)
from PySide6.QtNetwork import (
    QAbstractSocket,
    QHostAddress,
    QNetworkInterface,
    QNetworkProxy,
    QTcpSocket,
)
from math import ceil
from typing import Union
from hnh.utils import get_sensor_address, get_sensor_remote_address
from hnh.config import COMPATIBLE_SENSORS, DEBUG, PHONE_BRIDGE_PORT_DEFAULT
from hnh.perf_probe import get_perf_probe
from hnh.ble_diagnostics import append_ble_diagnostic


def ble_adapter_blocked_message() -> str | None:
    """
    If scanning / BLE cannot work, return a short user-facing reason; else None.

    Uses Qt's local adapter view (same stack as discovery). Some platforms may
    still start discovery when the radio is off; discovery errors are handled
    separately in SensorScanner._handle_scan_error.
    """
    try:
        addresses = QBluetoothLocalDevice.allDevices()
    except Exception:
        return None
    if not addresses:
        return (
            "No Bluetooth adapter was found. Use a PC with Bluetooth (or a USB "
            "adapter), then try Scan again."
        )
    try:
        local = QBluetoothLocalDevice()
    except Exception:
        return None
    if not local.isValid():
        return (
            "Bluetooth adapter is not available. Check Bluetooth in system settings, "
            "then try Scan again."
        )
    try:
        if local.hostMode() == QBluetoothLocalDevice.HostPoweredOff:
            return (
                "Bluetooth is turned off. Turn it on in system settings, then try Scan again."
            )
    except Exception:
        pass
    return None


def _discovery_error_message(error: QBluetoothDeviceDiscoveryAgent.Error) -> str | None:
    if error == QBluetoothDeviceDiscoveryAgent.Error.NoError:
        return None
    if error == QBluetoothDeviceDiscoveryAgent.Error.PoweredOffError:
        return (
            "Bluetooth appears off or unavailable. Turn it on in system settings, "
            "then try Scan again."
        )
    if error == QBluetoothDeviceDiscoveryAgent.Error.InvalidBluetoothAdapterError:
        return "No usable Bluetooth adapter was found. Check hardware and drivers, then retry."
    if error == QBluetoothDeviceDiscoveryAgent.Error.LocationServiceTurnedOffError:
        return (
            "Location services are off. On macOS, enable Location Services for Bluetooth "
            "scanning, then try again."
        )
    if error == QBluetoothDeviceDiscoveryAgent.Error.MissingPermissionsError:
        return (
            "Bluetooth permission is missing. Allow Bluetooth for this app in system "
            "settings, then try Scan again."
        )
    if error == QBluetoothDeviceDiscoveryAgent.Error.UnsupportedDiscoveryMethod:
        return "This Bluetooth adapter does not support BLE scanning."
    if error == QBluetoothDeviceDiscoveryAgent.Error.UnsupportedPlatformError:
        return "Bluetooth scanning is not supported on this platform build."
    if error == QBluetoothDeviceDiscoveryAgent.Error.InputOutputError:
        return "Bluetooth scan failed (I/O error). Toggle Bluetooth off/on and try again."
    return f"Bluetooth scan failed (code {int(error)}). Check Bluetooth, then retry."


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
    scanning_state = Signal(bool)
    diagnostic_logged = Signal(object)

    def __init__(self):
        super().__init__()
        self.scanner = QBluetoothDeviceDiscoveryAgent()
        self.scanner.setLowEnergyDiscoveryTimeout(10000)
        self.scanner.finished.connect(self._handle_scan_result)
        self.scanner.errorOccurred.connect(self._handle_scan_error)

    def scan(self) -> bool:
        if self.scanner.isActive():
            self.status_update.emit("Already searching for sensors.")
            return False
        blocked = ble_adapter_blocked_message()
        if blocked is not None:
            self.scanning_state.emit(False)
            self.status_update.emit(blocked)
            p = append_ble_diagnostic(
                "scanner",
                "scan_blocked",
                message=blocked,
            )
            self.diagnostic_logged.emit(p)
            return False
        self.scanning_state.emit(True)
        self.status_update.emit("Scanning for BLE sensors...")
        self.scanner.start(QBluetoothDeviceDiscoveryAgent.LowEnergyMethod)
        return True

    def _handle_scan_result(self):
        self.scanning_state.emit(False)
        sensors: list[QBluetoothDeviceInfo] = [
            d
            for d in self.scanner.discoveredDevices()
            if (any(cs in d.name() for cs in COMPATIBLE_SENSORS)) and (d.rssi() <= 0)
        ]  # https://www.mokoblue.com/measures-of-bluetooth-rssi/
        if not sensors:
            all_devs = self.scanner.discoveredDevices()
            sample = [d.name() or "(no name)" for d in all_devs[:12]]
            append_ble_diagnostic(
                "scanner",
                "scan_finished_empty",
                message="No compatible sensors matched filters (name + RSSI).",
                discovered_count=len(all_devs),
                sample_names=sample,
                platform=platform.system(),
            )
            self.status_update.emit("Couldn't find sensors.")
            return
        self.sensor_update.emit(sensors)
        self.status_update.emit(f"Found {len(sensors)} sensor(s).")

    def _handle_scan_error(self, error: QBluetoothDeviceDiscoveryAgent.Error) -> None:
        self.scanning_state.emit(False)
        if error == QBluetoothDeviceDiscoveryAgent.Error.NoError:
            return
        msg = _discovery_error_message(error)
        try:
            code = int(error)
        except Exception:
            code = None
        try:
            enum_label = error.name
        except AttributeError:
            enum_label = str(error)
        p = append_ble_diagnostic(
            "scanner",
            "discovery_error",
            message=msg or str(error),
            qt_enum=str(enum_label),
            qt_code=code,
        )
        self.diagnostic_logged.emit(p)
        if msg is not None:
            self.status_update.emit(msg)
        else:
            print(error)


class PhoneBridgeClient(QObject):
    """
    Connect to a phone bridge over Wi-Fi/TCP.

    The bridge sends newline-delimited JSON objects:
      {"type":"status","message":"...","connected":true}
      {"type":"rr","rr_ms":812}
      {"type":"ecg","samples_mv":[0.12,0.18,...]}
    """

    ibi_update = Signal(object)
    ecg_update = Signal(object)
    ecg_ready = Signal()
    status_update = Signal(str)
    battery_update = Signal(int)
    verity_limited_support = Signal()
    diagnostic_logged = Signal(object)

    def __init__(self):
        super().__init__()
        self.client: Union[None, QTcpSocket] = None
        self._buffer = bytearray()
        self._host = ""
        self._port = 0
        self._client_profile_name = "Admin"
        self._ecg_announced = False
        self._rr_frames_seen = 0
        self._ecg_frames_seen = 0

    def set_client_profile_name(self, profile_name: str) -> None:
        name = str(profile_name or "").strip()
        self._client_profile_name = name or "Admin"

    def connect_host(self, host: str, port: int) -> None:
        if self.client is not None:
            self.status_update.emit("Phone Bridge already connected.")
            return
        host = (host or "").strip()
        if not host:
            self.status_update.emit("Phone Bridge host is empty.")
            return
        if port < 1024 or port > 65535:
            self.status_update.emit("Phone Bridge port must be 1024-65535.")
            return
        sock = QTcpSocket(self)
        self.client = sock
        self._buffer.clear()
        self._ecg_announced = False
        self._rr_frames_seen = 0
        self._ecg_frames_seen = 0
        self._host = host
        self._port = int(port)
        sock.connected.connect(self._on_connected)
        sock.disconnected.connect(self._on_disconnected)
        sock.readyRead.connect(self._on_ready_read)
        sock.errorOccurred.connect(self._on_error)
        # Avoid system HTTP/SOCKS proxy routing LAN IPs (can cause spurious timeouts).
        sock.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        host_addr = QHostAddress(host)
        if host_addr.isNull():
            sock.connectToHost(host, self._port)
        else:
            sock.connectToHost(host_addr, self._port)
        self.status_update.emit(f"Connecting to Phone Bridge at {host}:{self._port}...")

    def disconnect_client(self) -> None:
        if self.client is None:
            return
        sock = self.client
        self.client = None
        try:
            sock.readyRead.disconnect(self._on_ready_read)
        except Exception:
            pass
        try:
            sock.disconnected.disconnect(self._on_disconnected)
        except Exception:
            pass
        try:
            sock.connected.disconnect(self._on_connected)
        except Exception:
            pass
        try:
            sock.errorOccurred.disconnect(self._on_error)
        except Exception:
            pass
        if sock.state() != QAbstractSocket.UnconnectedState:
            sock.disconnectFromHost()
            if sock.state() != QAbstractSocket.UnconnectedState:
                sock.abort()
        sock.deleteLater()
        self._buffer.clear()
        self._ecg_announced = False
        self._rr_frames_seen = 0
        self._ecg_frames_seen = 0
        self.status_update.emit("Disconnected from Phone Bridge.")
        self.battery_update.emit(-1)

    def _on_connected(self) -> None:
        self.status_update.emit(f"Connected to Phone Bridge ({self._host}:{self._port}).")
        self.battery_update.emit(-1)
        self._send_client_info()

    def _send_client_info(self) -> None:
        sock = self.client
        if sock is None:
            return
        username = str(getattr(self, "_client_profile_name", "") or "").strip() or "Admin"
        try:
            host = str(platform.node() or "").strip() or socket.gethostname()
        except Exception:
            host = ""
        payload = {
            "type": "client_info",
            "app": "HertzAndHearts",
            "pc_user": username,
            "pc_host": host,
        }
        try:
            sock.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            sock.flush()
        except Exception:
            # Non-fatal: bridge should continue streaming even if metadata send fails.
            pass

    def _on_disconnected(self) -> None:
        had_client = self.client is not None
        if self.client is not None:
            self.client.deleteLater()
            self.client = None
        self._buffer.clear()
        self._ecg_announced = False
        self._rr_frames_seen = 0
        self._ecg_frames_seen = 0
        self.battery_update.emit(-1)
        if had_client:
            self.status_update.emit(
                "Phone Bridge disconnected (remote closed connection)."
            )

    def _on_error(self, _error) -> None:
        if self.client is None:
            return
        msg = self.client.errorString()
        try:
            err_code = int(self.client.error())
            self.status_update.emit(f"Phone Bridge error [{err_code}]: {msg}")
        except Exception:
            self.status_update.emit(f"Phone Bridge error: {msg}")

    def _on_ready_read(self) -> None:
        if self.client is None:
            return
        self._buffer.extend(bytes(self.client.readAll()))
        while True:
            newline_idx = self._buffer.find(b"\n")
            if newline_idx < 0:
                break
            raw = bytes(self._buffer[:newline_idx]).strip()
            del self._buffer[:newline_idx + 1]
            if not raw:
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            self._handle_bridge_message(payload)

    def _handle_bridge_message(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        msg_type = str(payload.get("type", "")).strip().lower()
        if msg_type == "status":
            text = str(payload.get("message", "")).strip()
            if text:
                self.status_update.emit(text)
            battery = payload.get("battery")
            if isinstance(battery, (int, float)):
                level = max(0, min(100, int(battery)))
                self.battery_update.emit(level)
            return
        if msg_type == "rr":
            rr_ms = payload.get("rr_ms", payload.get("ibi_ms"))
            try:
                ibi = int(round(float(rr_ms)))
            except Exception:
                return
            if ibi > 0:
                self._rr_frames_seen += 1
                if DEBUG and (self._rr_frames_seen % 100 == 0):
                    print(f"[PhoneBridge] RR frames received: {self._rr_frames_seen}")
                self.ibi_update.emit(ibi)
            return
        if msg_type == "ecg":
            samples = payload.get("samples_mv", payload.get("samples"))
            if not isinstance(samples, list) or not samples:
                return
            out: list[float] = []
            for sample in samples:
                try:
                    out.append(float(sample))
                except Exception:
                    continue
            if not out:
                return
            self._ecg_frames_seen += 1
            if DEBUG and (
                self._ecg_frames_seen == 1 or (self._ecg_frames_seen % 50 == 0)
            ):
                preview = ", ".join(f"{x:.3f}" for x in out[:3])
                print(
                    f"[PhoneBridge] ECG frame {self._ecg_frames_seen}: "
                    f"n={len(out)} first3=[{preview}]"
                )
            if not self._ecg_announced:
                self._ecg_announced = True
                self.ecg_ready.emit()
                self.status_update.emit("Phone Bridge ECG stream started.")
            self.ecg_update.emit(out)


# UDP: Hertz & Hearts broadcasts on PHONE_BRIDGE_APP_DISCOVERY_PORT; the Android
# Polar H10 bridge app responds (see discover_phone_bridge_hosts).
PHONE_BRIDGE_APP_DISCOVERY_PORT: int = 45124
PHONE_BRIDGE_APP_DISCOVER: bytes = b"HnH_PHONE_BRIDGE_DISCOVER_V1\n"


def _lan_ipv4_broadcast_strings() -> list[str]:
    out: list[str] = ["255.255.255.255"]
    for iface in QNetworkInterface.allInterfaces():
        flags = iface.flags()
        if not (
            flags & QNetworkInterface.InterfaceFlag.IsUp
            and flags & QNetworkInterface.InterfaceFlag.IsRunning
        ):
            continue
        if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        for ae in iface.addressEntries():
            ip = ae.ip()
            if ip.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            b = ae.broadcast()
            if not b.isNull():
                s = b.toString().strip()
                if s and s not in out:
                    out.append(s)
                continue
            # Some Windows adapters report no broadcast in Qt; derive one.
            try:
                ip_s = ip.toString().strip()
                mask_s = ae.netmask().toString().strip()
                ip_i = struct.unpack("!I", socket.inet_aton(ip_s))[0]
                mask_i = struct.unpack("!I", socket.inet_aton(mask_s))[0]
                bcast_i = ip_i | (~mask_i & 0xFFFFFFFF)
                derived = socket.inet_ntoa(struct.pack("!I", bcast_i))
            except (OSError, struct.error, ValueError):
                continue
            if derived and derived not in out:
                out.append(derived)
    seen: set[str] = set()
    dedup: list[str] = []
    for a in out:
        if a not in seen:
            seen.add(a)
            dedup.append(a)
    return dedup


def _lan_ipv4_hosts_for_probe(max_hosts: int = 1024) -> list[str]:
    """
    Return likely LAN host IPs derived from local IPv4 interfaces.
    Used as a fallback when UDP broadcast discovery is blocked.
    """
    iface_entries: list[tuple[int, str, str]] = []
    for iface in QNetworkInterface.allInterfaces():
        flags = iface.flags()
        if not (
            flags & QNetworkInterface.InterfaceFlag.IsUp
            and flags & QNetworkInterface.InterfaceFlag.IsRunning
        ):
            continue
        if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        name = (
            iface.humanReadableName().strip().lower()
            or iface.name().strip().lower()
        )
        is_virtual = any(k in name for k in ("docker", "vmware", "vbox", "hyper-v", "vethernet"))
        for ae in iface.addressEntries():
            ip = ae.ip()
            if ip.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            ip_s = ip.toString().strip()
            mask_s = ae.netmask().toString().strip()
            try:
                net = ipaddress.IPv4Network(f"{ip_s}/{mask_s}", strict=False)
            except ValueError:
                continue
            if net.num_addresses <= 2:
                continue
            own = ipaddress.IPv4Address(ip_s)
            priority = 0
            if not net.is_private:
                priority += 4
            if is_virtual:
                priority += 8
            iface_entries.append((priority, ip_s, mask_s))
    out: list[str] = []
    seen: set[str] = set()
    for _priority, ip_s, mask_s in sorted(iface_entries, key=lambda x: x[0]):
        try:
            net = ipaddress.IPv4Network(f"{ip_s}/{mask_s}", strict=False)
            own = ipaddress.IPv4Address(ip_s)
        except ValueError:
            continue
        candidates = [h for h in net.hosts() if h != own]
        if len(candidates) > 512:
            # Keep probe time bounded on very large subnets.
            candidates = candidates[:512]
        for host in candidates:
            hs = str(host)
            if hs in seen:
                continue
            seen.add(hs)
            out.append(hs)
            if len(out) >= max_hosts:
                return out
    return out


def _tcp_probe_phone_bridge_hosts(
    hosts: list[str],
    port: int,
    timeout_s: float = 0.35,
    max_workers: int = 32,
) -> list[dict[str, object]]:
    found: dict[str, dict[str, object]] = {}

    def _probe(ip: str) -> tuple[str, bool]:
        for _ in range(2):
            try:
                with socket.create_connection((ip, int(port)), timeout=timeout_s):
                    return (ip, True)
            except OSError:
                time.sleep(0.02)
        return (ip, False)

    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=max(4, min(max_workers, len(hosts)))) as ex:
        futures = [ex.submit(_probe, ip) for ip in hosts]
        for fut in as_completed(futures):
            ip, ok = fut.result()
            if not ok:
                continue
            try:
                host = socket.gethostbyaddr(ip)[0]
            except OSError:
                host = ip
            found[ip] = {"ip": ip, "hostname": host, "port": int(port)}
    return sorted(found.values(), key=lambda d: str(d.get("hostname", "")).lower())


def discover_phone_bridge_hosts(timeout_s: float = 2.5) -> list[dict[str, object]]:
    """
    Discover Android PolarH10Bridge instances on the LAN. Returns:
    [{"ip": str, "hostname": str, "port": int}, ...]
    """
    found: dict[str, dict[str, object]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))
        sock.settimeout(0.35)
        targets = _lan_ipv4_broadcast_strings()

        def _send_probe() -> None:
            for addr in targets:
                try:
                    sock.sendto(PHONE_BRIDGE_APP_DISCOVER, (addr, PHONE_BRIDGE_APP_DISCOVERY_PORT))
                except OSError:
                    continue

        _send_probe()
        deadline = time.monotonic() + timeout_s
        next_probe_at = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_probe_at:
                _send_probe()
                next_probe_at = now + 0.8
            try:
                data, raddr = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            ip = raddr[0]
            try:
                line = bytes(data).strip().decode("utf-8", errors="replace")
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("app", "")) != "PolarH10Bridge":
                continue
            if str(payload.get("role", "")) != "phone_bridge":
                continue
            try:
                port = int(payload.get("port", PHONE_BRIDGE_PORT_DEFAULT))
            except (TypeError, ValueError):
                port = int(PHONE_BRIDGE_PORT_DEFAULT)
            if port < 1 or port > 65535:
                port = int(PHONE_BRIDGE_PORT_DEFAULT)
            host = str(payload.get("hostname", "")).strip() or ip
            found[ip] = {"ip": ip, "hostname": host, "port": port}
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if not found:
        port = int(PHONE_BRIDGE_PORT_DEFAULT)
        tcp_hosts = _lan_ipv4_hosts_for_probe(max_hosts=1024)
        for row in _tcp_probe_phone_bridge_hosts(
            tcp_hosts, port=port, timeout_s=0.35, max_workers=32
        ):
            ip = str(row.get("ip", "")).strip()
            if not ip:
                continue
            found[ip] = row
    return sorted(found.values(), key=lambda d: str(d.get("hostname", "")).lower())


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
    diagnostic_logged = Signal(object)

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
        self._last_sensor: Union[None, QBluetoothDeviceInfo] = None
        self._retried_connection_error = False
        self._pending_sensor: Union[None, QBluetoothDeviceInfo] = None
        self._linux_retry_with_public = False
        self._received_first_hr_packet = False
        self._pending_pmd_after_hr = False
        self._no_rr_interval_warning_emitted = False
        raw_enable_pmd = os.environ.get("HNH_ENABLE_PMD", "").strip().lower()
        if raw_enable_pmd:
            self._enable_pmd = raw_enable_pmd in {"1", "true", "yes", "on"}
        else:
            # On Linux/BlueZ, PMD control handshake can destabilize some adapters.
            # Keep core HR/RR streaming stable by default; PMD can be forced on via env.
            self._enable_pmd = platform.system() != "Linux"
        raw_conservative = os.environ.get("HNH_PMD_CONSERVATIVE_CONNECT", "").strip().lower()
        if raw_conservative:
            self._conservative_pmd_connect = raw_conservative in {"1", "true", "yes", "on"}
        else:
            # Linux-only conservative PMD startup: delay PMD until HR packets flow.
            self._conservative_pmd_connect = platform.system() == "Linux"

    def set_enable_pmd(self, enabled: bool) -> None:
        self._enable_pmd = bool(enabled)
        if not self._enable_pmd:
            self._pending_pmd_after_hr = False

    def _start_pmd_discovery_safe(self) -> None:
        if self.pmd_service is None:
            return
        try:
            self.pmd_service.discoverDetails()
        except Exception:
            pass

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
        if not self._windows_ble_preflight(sensor):
            return
        self._last_sensor = sensor
        self._retried_connection_error = False
        self._start_connection(sensor)

    def _windows_ble_preflight(self, sensor: QBluetoothDeviceInfo) -> bool:
        if platform.system() != "Windows":
            return True
        blocked = ble_adapter_blocked_message()
        if blocked is not None:
            self.status_update.emit(blocked)
            p = append_ble_diagnostic(
                "client",
                "windows_preflight_blocked",
                message=blocked,
                sensor=str(get_sensor_address(sensor)),
            )
            self.diagnostic_logged.emit(p)
            return False
        try:
            local = QBluetoothLocalDevice()
        except Exception:
            return True
        try:
            pairing_status = local.pairingStatus(sensor.address())
            if pairing_status == QBluetoothLocalDevice.Unpaired:
                msg = (
                    "Windows requires H10 pairing first. Pair H10 in Windows Bluetooth settings, then retry."
                )
                self.status_update.emit(msg)
                try:
                    ps = int(pairing_status)
                except Exception:
                    ps = None
                p = append_ble_diagnostic(
                    "client",
                    "windows_pairing_required",
                    message=msg,
                    sensor=str(get_sensor_address(sensor)),
                    pairing_status=ps,
                )
                self.diagnostic_logged.emit(p)
                return False
        except Exception:
            # Some Windows BLE stacks do not expose reliable pairing status.
            pass
        return True

    def _start_connection(self, sensor: QBluetoothDeviceInfo):
        self.status_update.emit(
            f"Connecting to sensor at {get_sensor_address(sensor)} (this might take a while)."
        )
        self._pending_sensor = sensor
        self._received_first_hr_packet = False
        self._no_rr_interval_warning_emitted = False
        self._connected_device_name = sensor.name() or ""
        self._verity_warning_emitted = False
        self._linux_retry_with_public = False
        addr_hint = os.environ.get("HNH_BLE_ADDRESS_TYPE", "auto").strip().lower()
        remote_type = QLowEnergyController.RemoteAddressType.RandomAddress
        if addr_hint == "public":
            remote_type = QLowEnergyController.RemoteAddressType.PublicAddress
        elif platform.system() == "Linux" and addr_hint == "auto":
            # Try Random first (common for BLE), then auto-retry Public once on ConnectionError.
            self._linux_retry_with_public = True
        self.client = QLowEnergyController.createCentral(sensor)
        if platform.system() == "Linux":
            self.client.setRemoteAddressType(remote_type)
        self.client.errorOccurred.connect(self._catch_error)
        self.client.connected.connect(self._discover_services)
        self.client.discoveryFinished.connect(self._connect_hr_service)
        self.client.disconnected.connect(self._reset_connection)
        self.client.connectToDevice()
        try:
            qt_v = qVersion()
        except Exception:
            qt_v = ""
        append_ble_diagnostic(
            "client",
            "connect_start",
            message="Low energy connection initiated.",
            sensor=str(get_sensor_address(sensor)),
            sensor_name=sensor.name() or "",
            platform=platform.system(),
            qt_version=qt_v,
            pmd_enabled=bool(self._enable_pmd),
            pmd_conservative=bool(self._conservative_pmd_connect),
        )

    def _retry_last_connection_once(self):
        if self.client is not None:
            return
        if self._last_sensor is None:
            return
        self.status_update.emit("BLE connection failed once; retrying now...")
        self._start_connection(self._last_sensor)

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
            svc_list = [s.toString() for s in self.client.services()][:32]
            msg = f"Couldn't find HR service on {self._sensor_address()}."
            p = append_ble_diagnostic(
                "client",
                "hr_service_missing",
                message=msg,
                discovered_service_uuids=svc_list,
            )
            self.diagnostic_logged.emit(p)
            print(msg)
            return
        self.hr_service = self.client.createServiceObject(hr_service[0])
        if not self.hr_service:
            msg = f"Couldn't establish connection to HR service on {self._sensor_address()}."
            p = append_ble_diagnostic(
                "client",
                "hr_service_object_failed",
                message=msg,
            )
            self.diagnostic_logged.emit(p)
            print(msg)
            return
        self.hr_service.stateChanged.connect(self._start_hr_notification)
        self.hr_service.characteristicChanged.connect(self._data_handler)
        self.hr_service.discoverDetails()

        self._connect_battery_service()
        if not self._enable_pmd:
            return

        pmd_uuid_str = self.PMD_SERVICE_UUID.toString().lower()
        pmd_match = [
            s for s in self.client.services()
            if s.toString().lower() == pmd_uuid_str
        ]
        if not pmd_match:
            svc_list = [s.toString() for s in self.client.services()][:40]
            append_ble_diagnostic(
                "client",
                "pmd_service_missing",
                message="PMD service UUID not in GATT table — ECG unavailable; HR/RR may still work.",
                discovered_service_uuids=svc_list,
                platform=platform.system(),
            )
            self.status_update.emit(
                "ECG (Polar PMD) not found on this link — heart rate / RR still available."
            )
            if DEBUG:
                print("PMD service not found. Available services:")
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
            if self._conservative_pmd_connect:
                # Linux safety path: wait until first HR packet before PMD handshake.
                self._pending_pmd_after_hr = True
            else:
                self.pmd_service.discoverDetails()
        else:
            msg = f"Couldn't establish connection to PMD service on {self._sensor_address()}."
            print(msg)
            p = append_ble_diagnostic(
                "client",
                "pmd_service_object_failed",
                message=msg,
                platform=platform.system(),
            )
            self.diagnostic_logged.emit(p)

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
        if self.client is None:
            return
        try:
            if self.client.state() != QLowEnergyController.ControllerState.ConnectedState:
                return
        except Exception:
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
            msg = f"HR measurement characteristic missing or invalid on {self._sensor_address()}."
            print(msg)
            p = append_ble_diagnostic(
                "client",
                "hr_characteristic_invalid",
                message=msg,
                platform=platform.system(),
            )
            self.diagnostic_logged.emit(p)
            self.status_update.emit(msg)
            return
        self.hr_notification = hr_char.descriptor(
            QBluetoothUuid.DescriptorType.ClientCharacteristicConfiguration
        )
        if not self.hr_notification.isValid():
            msg = f"HR CCCD descriptor invalid on {self._sensor_address()}."
            print(msg)
            p = append_ble_diagnostic(
                "client",
                "hr_cccd_invalid",
                message=msg,
                platform=platform.system(),
            )
            self.diagnostic_logged.emit(p)
            self.status_update.emit(msg)
            return
        self.hr_service.writeDescriptor(self.hr_notification, self.ENABLE_NOTIFICATION)
        append_ble_diagnostic(
            "client",
            "hr_notifications_enabled",
            message="Subscribed to heart rate measurement notifications.",
            address=str(self._sensor_address()),
            platform=platform.system(),
        )
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
                msg = "PMD data CCCD descriptor invalid."
                print(msg)
                p = append_ble_diagnostic(
                    "client",
                    "pmd_data_cccd_invalid",
                    message=msg,
                    platform=platform.system(),
                )
                self.diagnostic_logged.emit(p)
                self.status_update.emit(msg)
        else:
            msg = "PMD data characteristic not found."
            print(msg)
            p = append_ble_diagnostic(
                "client",
                "pmd_data_char_missing",
                message=msg,
                platform=platform.system(),
            )
            self.diagnostic_logged.emit(p)
            self.status_update.emit(msg)

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
        if self._conservative_pmd_connect:
            QTimer.singleShot(350, self.start_ecg_stream)
        else:
            self.start_ecg_stream()

    def start_ecg_stream(self):
        if self.pmd_service is None:
            msg = "Cannot start ECG: PMD service not available."
            print(msg)
            append_ble_diagnostic(
                "client",
                "ecg_start_skipped",
                message=msg,
                reason="no_pmd_service",
                platform=platform.system(),
            )
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
            append_ble_diagnostic(
                "client",
                "ecg_stream_command_sent",
                message="PMD ECG start command written.",
                platform=platform.system(),
            )
            self.status_update.emit("ECG stream requested; waiting for data.")
        else:
            msg = "Cannot start ECG: PMD control characteristic not found."
            print(msg)
            p = append_ble_diagnostic(
                "client",
                "ecg_start_failed",
                message=msg,
                reason="control_char_missing",
                platform=platform.system(),
            )
            self.diagnostic_logged.emit(p)
            self.status_update.emit(msg)

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
        try:
            code = int(error)
        except Exception:
            code = None
        try:
            enum_label = error.name
        except AttributeError:
            enum_label = str(error)
        p = append_ble_diagnostic(
            "client",
            "pmd_service_error",
            message=str(error),
            qt_code=code,
            qt_enum=str(enum_label),
        )
        self.diagnostic_logged.emit(p)
        self.status_update.emit(
            f"ECG (PMD) error: {error}. ECG streaming stopped; heart rate may still work."
        )
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
                append_ble_diagnostic(
                    "client",
                    "first_ecg_pmd_samples",
                    message="First decoded ECG samples from PMD data stream.",
                    sample_count=len(samples),
                    platform=platform.system(),
                )
                self.status_update.emit("ECG data stream active.")
                self.ecg_ready.emit()
            self.ecg_update.emit(samples)

    def _reset_connection(self):
        try:
            addr = self._sensor_address()
        except Exception:
            addr = "unknown"
        print(f"Discarding sensor at {addr}.")
        append_ble_diagnostic(
            "client",
            "link_reset",
            message="BLE link torn down (disconnect, error, or reconnect).",
            address=str(addr),
            platform=platform.system(),
            had_ecg_stream=bool(self._ecg_streaming),
        )
        self._ecg_streaming = False
        self._pmd_ready = False
        self._ecg_start_pending = False
        self._ecg_data_received = False
        self._pmd_descriptors_pending = 0
        self._pending_pmd_after_hr = False
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
        error_text = str(error)
        try:
            code = int(error)
        except Exception:
            code = None
        try:
            enum_label = error.name
        except AttributeError:
            enum_label = str(error)
        addr = None
        try:
            if self._pending_sensor is not None:
                addr = str(get_sensor_address(self._pending_sensor))
        except Exception:
            pass
        p = append_ble_diagnostic(
            "client",
            "low_energy_controller_error",
            message=error_text,
            qt_code=code,
            qt_enum=str(enum_label),
            sensor=addr,
            platform=platform.system(),
        )
        self.diagnostic_logged.emit(p)
        if (
            platform.system() == "Linux"
            and error in (
                QLowEnergyController.Error.ConnectionError,
                QLowEnergyController.Error.UnknownRemoteDeviceError,
            )
            and self._linux_retry_with_public
            and self._pending_sensor is not None
            and not self._received_first_hr_packet
        ):
            self._linux_retry_with_public = False
            self.status_update.emit(
                "Connection retry: switching BLE address mode (Random → Public)."
            )
            sensor = self._pending_sensor
            self._remove_battery_service()
            self._remove_pmd_service()
            self._remove_service()
            self._remove_client()
            self.client = QLowEnergyController.createCentral(sensor)
            self.client.setRemoteAddressType(
                QLowEnergyController.RemoteAddressType.PublicAddress
            )
            self.client.errorOccurred.connect(self._catch_error)
            self.client.connected.connect(self._discover_services)
            self.client.discoveryFinished.connect(self._connect_hr_service)
            self.client.disconnected.connect(self._reset_connection)
            self.client.connectToDevice()
            return
        error_value = None
        try:
            error_value = int(error)
        except Exception:
            error_value = None
        is_windows_connection_error = (
            platform.system() == "Windows" and "ConnectionError" in error_text
        )
        if (
            is_windows_connection_error
            and (not self._retried_connection_error)
            and self._last_sensor is not None
        ):
            self._retried_connection_error = True
            try:
                detail = (
                    f"An error occurred: {error_text}"
                    + (f" ({error_value})" if error_value is not None else "")
                    + ". Retrying once..."
                )
                self.status_update.emit(detail)
            except Exception:
                pass
            try:
                self._reset_connection()
            except Exception:
                pass
            QTimer.singleShot(900, self._retry_last_connection_once)
            return
        try:
            detail = (
                f"An error occurred: {error_text}"
                + (f" ({error_value})" if error_value is not None else "")
            )
            if is_windows_connection_error:
                detail += (
                    ". Disconnecting sensor. "
                    "Windows BLE tip: pair H10 in Windows and close Polar phone app Bluetooth."
                )
            else:
                detail += ". Disconnecting sensor."
            self.status_update.emit(detail)
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
        byte0: int = heart_rate_measurement_bytes[0] if heart_rate_measurement_bytes else 0
        uint8_format: bool = (byte0 & 1) == 0
        energy_expenditure: bool = ((byte0 >> 3) & 1) == 1
        rr_interval: bool = ((byte0 >> 4) & 1) == 1

        if not self._received_first_hr_packet:
            self._received_first_hr_packet = True
            self._pending_sensor = None
            self._linux_retry_with_public = False
            if self._pending_pmd_after_hr and self._enable_pmd:
                self._pending_pmd_after_hr = False
                QTimer.singleShot(700, self._start_pmd_discovery_safe)
            append_ble_diagnostic(
                "client",
                "first_hr_measurement",
                message="First GATT heart-rate notification received.",
                payload_bytes=len(heart_rate_measurement_bytes),
                flags_byte=byte0,
                has_rr_interval=bool(rr_interval),
                address=str(self._sensor_address()),
                platform=platform.system(),
            )
            if not rr_interval and not self._no_rr_interval_warning_emitted:
                self._no_rr_interval_warning_emitted = True
                warn = (
                    "Sensor sent heart rate without RR intervals — check strap fit and "
                    "that no other app holds the sensor exclusively."
                )
                p = append_ble_diagnostic(
                    "client",
                    "hr_no_rr_in_measurement",
                    message=warn,
                    platform=platform.system(),
                )
                self.diagnostic_logged.emit(p)
                self.status_update.emit(warn)

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
