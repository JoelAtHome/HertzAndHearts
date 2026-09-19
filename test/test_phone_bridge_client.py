from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtNetwork import QHostAddress, QTcpServer

from hnh.sensor import PhoneBridgeClient


def _ensure_app() -> QCoreApplication:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


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


if __name__ == "__main__":
    unittest.main()
