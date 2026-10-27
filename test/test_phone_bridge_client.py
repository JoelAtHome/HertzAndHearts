from __future__ import annotations

import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtNetwork import QHostAddress, QTcpServer

from hnh.phone_bridge_occupancy import COMPANION_BUSY_STATUS
from hnh.sensor import PhoneBridgeClient


def _ensure_app() -> QCoreApplication:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


class _SignalStub:
    def disconnect(self, _slot):
        return None


class _SocketErrorStub:
    """Enough of a QTcpSocket for PhoneBridgeClient._on_error to tear it down."""

    readyRead = _SignalStub()
    disconnected = _SignalStub()
    connected = _SignalStub()
    errorOccurred = _SignalStub()

    def errorString(self) -> str:
        return "Connection refused"

    def error(self) -> int:
        return 1

    def state(self) -> int:
        return 0

    def abort(self) -> None:
        return None

    def deleteLater(self) -> None:
        return None


def _wait_until(predicate, timeout_ms: int = 3000) -> bool:
    app = _ensure_app()
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if predicate():
            return True
        app.processEvents()
        time.sleep(0.01)
    return bool(predicate())


class PhoneBridgeClientReconnectTests(unittest.TestCase):
    def test_remote_close_clears_client_so_retry_can_connect(self):
        app = _ensure_app()
        client = PhoneBridgeClient()
        statuses: list[str] = []
        client.status_update.connect(statuses.append)

        server = QTcpServer()
        self.addCleanup(server.close)
        self.assertTrue(server.listen(QHostAddress("127.0.0.1"), 0))
        port = int(server.serverPort())

        drop_first = {"done": False}

        def on_new_connection():
            incoming = server.nextPendingConnection()
            if incoming is None:
                return
            if not drop_first["done"]:
                drop_first["done"] = True
                incoming.close()

        server.newConnection.connect(on_new_connection)

        client.connect_host("127.0.0.1", port)
        self.assertTrue(
            _wait_until(lambda: client.client is None, timeout_ms=4000),
            msg=f"socket was not cleared after remote close; statuses={statuses}",
        )
        self.assertFalse(client.is_link_up())
        self.assertTrue(
            any("error" in s.lower() or "disconnected" in s.lower() for s in statuses)
        )

        client.connect_host("127.0.0.1", port)
        self.assertTrue(
            _wait_until(lambda: client.is_link_up(), timeout_ms=4000),
            msg=f"retry did not reconnect; statuses={statuses}",
        )
        client.disconnect_client()
        app.processEvents()

    def test_handler_exception_does_not_strand_following_rr(self):
        _ensure_app()
        client = PhoneBridgeClient()
        ibis: list[int] = []

        def boom(_samples):
            raise RuntimeError("ecg plot failed")

        client.ecg_update.connect(boom)
        client.ibi_update.connect(ibis.append)
        client._buffer.extend(
            b'{"type":"ecg","samples_mv":[0.1,0.2]}\n{"type":"rr","rr_ms":800}\n'
        )
        client._drain_ndjson()
        self.assertEqual(ibis, [800])
        self.assertEqual(client._ecg_frames_seen, 1)

    def test_drain_yields_after_line_budget(self):
        app = _ensure_app()
        client = PhoneBridgeClient()
        ibis: list[int] = []
        client.ibi_update.connect(ibis.append)
        payload = b"".join(
            f'{{"type":"rr","rr_ms":{800 + i}}}\n'.encode("utf-8") for i in range(60)
        )
        client._buffer.extend(payload)
        client._drain_ndjson()
        self.assertEqual(len(ibis), PhoneBridgeClient._MAX_LINES_PER_TURN)
        self.assertIn(b"\n", client._buffer)

        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
        app.processEvents()
        self.assertGreater(len(ibis), PhoneBridgeClient._MAX_LINES_PER_TURN)

    def test_is_link_up_false_without_socket(self):
        _ensure_app()
        client = PhoneBridgeClient()
        self.assertFalse(client.is_link_up())

    def test_ecg_sample_rate_is_announced_before_samples(self):
        _ensure_app()
        client = PhoneBridgeClient()
        events: list[tuple] = []
        client.ecg_sample_rate_update.connect(lambda hz: events.append(("rate", int(hz))))
        client.ecg_update.connect(lambda samples: events.append(("samples", list(samples))))
        client._handle_bridge_message(
            {
                "type": "ecg",
                "source_device": "FEATHER",
                "sample_rate_hz": 250,
                "samples_mv": [0.1, 0.2],
            }
        )
        client._handle_bridge_message(
            {
                "type": "ecg",
                "sample_rate_hz": 250,
                "samples_mv": [0.3],
            }
        )
        self.assertEqual(
            events,
            [("rate", 250), ("samples", [0.1, 0.2]), ("samples", [0.3])],
        )
        self.assertEqual(client.last_ecg_sample_rate_hz(), 250)

    def test_connect_host_does_not_open_tcp_when_local_program_holds_phone(self):
        _ensure_app()
        client = PhoneBridgeClient()
        statuses: list[str] = []
        client.status_update.connect(statuses.append)
        with mock.patch(
            "hnh.sensor.local_phone_bridge_holder_status",
            return_value=COMPANION_BUSY_STATUS,
        ) as check:
            started = client.connect_host("192.0.2.20", 8765)
        check.assert_called_once_with("192.0.2.20", 8765)
        self.assertFalse(started)
        self.assertIsNone(client.client)
        self.assertEqual(statuses, [COMPANION_BUSY_STATUS])

    def test_on_error_prefers_local_holder_over_qt_code(self):
        _ensure_app()
        client = PhoneBridgeClient()
        client._host = "192.0.2.20"
        client._port = 8765
        client.client = _SocketErrorStub()
        statuses: list[str] = []
        client.status_update.connect(statuses.append)
        with mock.patch(
            "hnh.sensor.local_phone_bridge_holder_status",
            return_value=COMPANION_BUSY_STATUS,
        ):
            client._on_error(1)
        self.assertIsNone(client.client)
        self.assertEqual(statuses, [COMPANION_BUSY_STATUS])
        self.assertFalse(any("error [" in status.lower() for status in statuses))

    def test_on_error_keeps_qt_code_when_this_pc_does_not_hold_phone(self):
        _ensure_app()
        client = PhoneBridgeClient()
        client._host = "192.0.2.20"
        client._port = 8765
        client.client = _SocketErrorStub()
        statuses: list[str] = []
        client.status_update.connect(statuses.append)
        with mock.patch(
            "hnh.sensor.local_phone_bridge_holder_status",
            return_value=None,
        ):
            client._on_error(1)
        self.assertEqual(statuses, ["Phone Bridge error [1]: Connection refused"])

    def test_ecg_without_sample_rate_defaults_to_polar(self):
        _ensure_app()
        client = PhoneBridgeClient()
        rates: list[int] = []
        client.ecg_sample_rate_update.connect(rates.append)
        client._handle_bridge_message({"type": "ecg", "samples_mv": [0.1]})
        self.assertEqual(rates, [130])


if __name__ == "__main__":
    unittest.main()
