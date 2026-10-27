"""Process-match tests for a Phone Bridge socket already held on this PC.

Fake TCP rows stand in for the OS table. A live phone is not required.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import unittest

from hnh.phone_bridge_occupancy import (
    COMPANION_BUSY_STATUS,
    OTHER_PROGRAM_BUSY_STATUS,
    PhoneBridgeTcpRow,
    is_flaretracker_bridge_companion,
    is_phone_bridge_held_locally_status,
    parse_proc_net_tcp_line,
    parse_windows_ipv4_owner_pid_table,
    parse_windows_ipv6_owner_pid_table,
    phone_bridge_holder_status,
)

LOCAL_APP_DATA = r"C:\Users\ada\AppData\Local"
PHONE = "192.168.1.20"
PORT = 8765

COMPANION_MESSAGE = (
    "Phone Bridge is busy with FlareTracker Bridge Companion on this PC. "
    "Disconnect it in FlareTracker, then click Connect here."
)
OTHER_MESSAGE = (
    "Phone Bridge is busy with another program on this PC. "
    "Disconnect that program, then click Connect here."
)


def _companion_runtime(local_app_data: str = LOCAL_APP_DATA) -> str:
    return local_app_data + r"\FlareTracker\BridgeCompanion\runtime\node.exe"


def _row(**kwargs) -> PhoneBridgeTcpRow:
    values = {
        "remote_host": PHONE,
        "remote_port": PORT,
        "pid": 50,
        "state": "ESTABLISHED",
        "process_path": "",
        "command_line": "",
    }
    values.update(kwargs)
    return PhoneBridgeTcpRow(**values)


def _status(rows, **kwargs) -> str | None:
    return phone_bridge_holder_status(
        rows,
        phone_host=kwargs.pop("phone_host", PHONE),
        phone_port=kwargs.pop("phone_port", PORT),
        local_app_data=kwargs.pop("local_app_data", LOCAL_APP_DATA),
        **kwargs,
    )


def _ipv4_dword(ip: str) -> int:
    return struct.unpack("<I", socket.inet_aton(ip))[0]


def _port_dword(port: int) -> int:
    return socket.htons(port)


class PhoneBridgeHolderMessageTests(unittest.TestCase):
    def test_required_status_strings(self):
        self.assertEqual(COMPANION_BUSY_STATUS, COMPANION_MESSAGE)
        self.assertEqual(OTHER_PROGRAM_BUSY_STATUS, OTHER_MESSAGE)
        self.assertTrue(is_phone_bridge_held_locally_status(COMPANION_MESSAGE))
        self.assertTrue(is_phone_bridge_held_locally_status(OTHER_MESSAGE))
        self.assertTrue(
            is_phone_bridge_held_locally_status(
                "Phone Bridge is busy with python.exe on this PC. "
                "Disconnect that program, then click Connect here."
            )
        )
        self.assertFalse(
            is_phone_bridge_held_locally_status(
                "Phone Bridge connection timed out. The phone may still be holding "
                "the last PC session. Force-stop or reopen the phone bridge app, "
                "then click Connect again."
            )
        )
        self.assertFalse(
            is_phone_bridge_held_locally_status("Phone Bridge error [1]: Connection refused")
        )


class PhoneBridgeProcessMatchTests(unittest.TestCase):
    def test_installed_companion_runtime_node(self):
        status = _status([_row(process_path=_companion_runtime())])
        self.assertEqual(status, COMPANION_MESSAGE)

    def test_installed_path_matches_with_mixed_case_and_slashes(self):
        path = "c:/users/ada/appdata/local/FlareTracker/BridgeCompanion/app/runtime/NODE.EXE"
        status = _status([_row(process_path=path)])
        self.assertEqual(status, COMPANION_MESSAGE)

    def test_runtime_node_outside_localappdata_is_not_companion(self):
        path = r"D:\FlareTracker\BridgeCompanion\runtime\node.exe"
        self.assertFalse(is_flaretracker_bridge_companion(path, "", LOCAL_APP_DATA))
        status = _status([_row(process_path=path)])
        self.assertEqual(
            status,
            "Phone Bridge is busy with node.exe on this PC. "
            "Disconnect that program, then click Connect here.",
        )

    def test_node_exe_name_alone_is_not_companion(self):
        path = r"C:\Program Files\nodejs\node.exe"
        command = r'"C:\Program Files\nodejs\node.exe" C:\app\server.js'
        self.assertFalse(is_flaretracker_bridge_companion(path, command, LOCAL_APP_DATA))
        status = _status([_row(process_path=path, command_line=command)])
        self.assertEqual(
            status,
            "Phone Bridge is busy with node.exe on this PC. "
            "Disconnect that program, then click Connect here.",
        )

    def test_command_line_main_cjs_is_companion(self):
        status = _status(
            [
                _row(
                    process_path=r"C:\Program Files\nodejs\node.exe",
                    command_line=r"node D:\src\FlareTracker\BridgeCompanion\app\main.cjs",
                )
            ]
        )
        self.assertEqual(status, COMPANION_MESSAGE)

    def test_command_line_main_cjs_accepts_forward_slashes(self):
        status = _status(
            [
                _row(
                    process_path=r"C:\Program Files\nodejs\node.exe",
                    command_line="node D:/src/FlareTracker/BridgeCompanion/app/main.cjs",
                )
            ]
        )
        self.assertEqual(status, COMPANION_MESSAGE)

    def test_dev_helper_command_line_is_companion(self):
        status = _status(
            [
                _row(
                    process_path=r"C:\Python311\python.exe",
                    command_line="python -m phone-bridge-companion --host 192.168.1.20",
                )
            ]
        )
        self.assertEqual(status, COMPANION_MESSAGE)

    def test_localhost_helper_port_is_not_the_phone_session(self):
        # Port 45126 on localhost only means the helper process is running.
        helper = _row(
            remote_host="127.0.0.1",
            remote_port=45126,
            process_path=_companion_runtime(),
            command_line=r"node C:\Users\ada\AppData\Local\FlareTracker\BridgeCompanion\app\main.cjs",
        )
        self.assertIsNone(_status([helper]))

    def test_helper_port_plus_phone_connection_is_companion(self):
        helper = _row(
            remote_host="127.0.0.1",
            remote_port=45126,
            pid=77,
            process_path=_companion_runtime(),
        )
        phone = _row(pid=77, process_path=_companion_runtime())
        self.assertEqual(_status([helper, phone]), COMPANION_MESSAGE)

    def test_own_process_is_ignored(self):
        self.assertIsNone(
            _status(
                [_row(pid=100, process_path=_companion_runtime())],
                own_pid=100,
            )
        )

    def test_own_process_does_not_hide_another_holder(self):
        rows = [
            _row(pid=100, process_path=_companion_runtime()),
            _row(pid=9, process_path=r"C:\Python311\python.exe"),
        ]
        self.assertEqual(
            _status(rows, own_pid=100),
            "Phone Bridge is busy with python.exe on this PC. "
            "Disconnect that program, then click Connect here.",
        )

    def test_unknown_process_uses_generic_message(self):
        self.assertEqual(_status([_row(pid=9)]), OTHER_MESSAGE)

    def test_command_line_names_program_when_image_path_is_missing(self):
        status = _status(
            [
                _row(
                    command_line=r'"C:\Apps\CustomBridge.exe" --connect',
                )
            ]
        )
        self.assertEqual(
            status,
            "Phone Bridge is busy with CustomBridge.exe on this PC. "
            "Disconnect that program, then click Connect here.",
        )

    def test_companion_wins_over_another_named_program(self):
        rows = [
            _row(pid=3, process_path=r"C:\Windows\System32\curl.exe"),
            _row(pid=4, process_path=_companion_runtime()),
        ]
        self.assertEqual(_status(rows), COMPANION_MESSAGE)

    def test_half_open_and_time_wait_do_not_count(self):
        path = _companion_runtime()
        self.assertIsNone(_status([_row(state="SYN_SENT", process_path=path)]))
        self.assertIsNone(_status([_row(state="TIME_WAIT", process_path=path)]))
        self.assertIsNone(_status([_row(state="LISTEN", process_path=path, remote_port=0)]))

    def test_different_phone_or_port_does_not_count(self):
        row = _row(process_path=_companion_runtime())
        self.assertIsNone(_status([row], phone_host="10.0.0.8"))
        self.assertIsNone(_status([row], phone_port=8766))
        self.assertIsNone(_status([]))

    def test_ipv4_mapped_remote_matches_ipv4_phone(self):
        status = _status(
            [
                _row(
                    remote_host="::ffff:192.168.1.20",
                    process_path=r"C:\Tools\Widget.exe",
                )
            ]
        )
        self.assertEqual(
            status,
            "Phone Bridge is busy with Widget.exe on this PC. "
            "Disconnect that program, then click Connect here.",
        )


class PhoneBridgeTcpTableParseTests(unittest.TestCase):
    def test_windows_ipv4_owner_table_and_process_match(self):
        established = struct.pack(
            "<IIIIII",
            5,
            _ipv4_dword("10.1.2.3"),
            _port_dword(50000),
            _ipv4_dword(PHONE),
            _port_dword(PORT),
            4242,
        )
        listening = struct.pack(
            "<IIIIII",
            2,
            _ipv4_dword("0.0.0.0"),
            _port_dword(45126),
            _ipv4_dword("0.0.0.0"),
            _port_dword(0),
            4242,
        )
        parsed = parse_windows_ipv4_owner_pid_table(struct.pack("<I", 2) + established + listening)
        self.assertEqual(parsed[0], (PHONE, PORT, 4242, "ESTABLISHED"))
        self.assertEqual(parsed[1][1], 0)
        self.assertEqual(parsed[1][3], "LISTEN")

        remote_ip, remote_port, pid, state_name = parsed[0]
        status = _status(
            [
                _row(
                    remote_host=remote_ip,
                    remote_port=remote_port,
                    pid=pid,
                    state=state_name,
                    process_path=_companion_runtime(),
                )
            ]
        )
        self.assertEqual(status, COMPANION_MESSAGE)
        self.assertIsNone(
            _status(
                [
                    _row(
                        remote_host=parsed[1][0],
                        remote_port=parsed[1][1],
                        pid=parsed[1][2],
                        state=parsed[1][3],
                        process_path=_companion_runtime(),
                    )
                ]
            )
        )

    def test_windows_ipv6_owner_table(self):
        remote = ipaddress.IPv6Address("2001:db8::5").packed
        row = b"\x00" * 16
        row += struct.pack("<II", 0, _port_dword(40000))
        row += remote
        row += struct.pack("<II", 0, _port_dword(PORT))
        row += struct.pack("<II", 5, 99)
        self.assertEqual(len(row), 56)
        parsed = parse_windows_ipv6_owner_pid_table(struct.pack("<I", 1) + row)
        self.assertEqual(parsed, [("2001:db8::5", PORT, 99, "ESTABLISHED")])

    def test_short_windows_table_is_empty(self):
        self.assertEqual(parse_windows_ipv4_owner_pid_table(b""), [])
        self.assertEqual(parse_windows_ipv4_owner_pid_table(struct.pack("<I", 1)), [])

    def test_proc_net_tcp_established_line(self):
        line = (
            "   0: 0100007F:C3A2 1401A8C0:223D 01 "
            "00000000:00000000 00:00000000 00000000 1000 0 12345 1 "
            "0000000000000000 100 0 0 10 0"
        )
        parsed = parse_proc_net_tcp_line(line)
        self.assertEqual(parsed, (PHONE, PORT, "12345", "ESTABLISHED"))
        self.assertIsNone(parse_proc_net_tcp_line("sl  local_address rem_address st"))

    def test_proc_net_tcp6_mapped_v4(self):
        line = (
            "   0: 00000000000000000000000000000000:0050 "
            "0000000000000000FFFF00000100007F:223D 01 "
            "00000000:00000000 00:00000000 00000000 1000 0 55 1 "
            "0000000000000000 100 0 0 10 0"
        )
        parsed = parse_proc_net_tcp_line(line, ipv6=True)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        mapped = ipaddress.IPv6Address(parsed[0]).ipv4_mapped
        self.assertEqual(mapped, ipaddress.IPv4Address("127.0.0.1"))
        self.assertEqual(parsed[1], PORT)
        self.assertEqual(parsed[3], "ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
