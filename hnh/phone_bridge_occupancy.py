"""See which program on this PC already holds the phone bridge socket.

The phone keeps one PC TCP session. UDP discover does not name that client, and
a second PC that connects and sends ``client_info`` replaces the current one.
Before Hertz & Hearts opens TCP it looks at established connections on this
computer whose remote address is the phone and whose remote port is the bridge
port. Hertz & Hearts' own process is ignored.

FlareTracker Bridge Companion is that owner when the process image is
``runtime\\node.exe`` under ``%LOCALAPPDATA%\\FlareTracker\\BridgeCompanion\\``,
or the command line contains ``BridgeCompanion\\app\\main.cjs`` or
``phone-bridge-companion``. The name ``node.exe`` alone is not Companion.
A helper listening on localhost port 45126 only means that process is running;
it is not the phone session.

This cannot see a Companion running on another computer.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import struct
from dataclasses import dataclass
from typing import Iterable

COMPANION_BUSY_STATUS = (
    "Phone Bridge is busy with FlareTracker Bridge Companion on this PC. "
    "Disconnect it in FlareTracker, then click Connect here."
)
OTHER_PROGRAM_BUSY_STATUS = (
    "Phone Bridge is busy with another program on this PC. "
    "Disconnect that program, then click Connect here."
)
_BUSY_STATUS_PREFIX = "Phone Bridge is busy with "

_COMPANION_CJS = "bridgecompanion\\app\\main.cjs"
_DEV_HELPER = "phone-bridge-companion"
_ESTABLISHED_STATES = frozenset({"established", "estab", "5"})

# Windows MIB_TCP_STATE. Linux /proc uses different numbers; only the string
# "ESTABLISHED" is handed to the matcher.
_WINDOWS_TCP_STATE_NAMES = {
    1: "CLOSED",
    2: "LISTEN",
    3: "SYN_SENT",
    4: "SYN_RECEIVED",
    5: "ESTABLISHED",
    6: "FIN_WAIT1",
    7: "FIN_WAIT2",
    8: "CLOSE_WAIT",
    9: "CLOSING",
    10: "LAST_ACK",
    11: "TIME_WAIT",
    12: "DELETE_TCB",
}
_LINUX_TCP_ESTABLISHED = 0x01


@dataclass(frozen=True)
class PhoneBridgeTcpRow:
    """One TCP endpoint plus the owning process, real or supplied by a test."""

    remote_host: str
    remote_port: int
    pid: int
    state: str = "ESTABLISHED"
    process_path: str = ""
    command_line: str = ""


def is_phone_bridge_held_locally_status(status: str) -> bool:
    """True for the Connect status shown when some local program holds the phone."""
    return str(status or "").startswith(_BUSY_STATUS_PREFIX)


def other_program_busy_status(program_name: str) -> str:
    name = " ".join(str(program_name or "").split())
    if not name:
        return OTHER_PROGRAM_BUSY_STATUS
    if len(name) > 120:
        name = name[:120].rstrip()
    return (
        f"Phone Bridge is busy with {name} on this PC. "
        "Disconnect that program, then click Connect here."
    )


def is_flaretracker_bridge_companion(
    process_path: str,
    command_line: str = "",
    local_app_data: str = "",
) -> bool:
    """True when this process is FlareTracker Bridge Companion, including a dev helper."""
    folded_cmd = str(command_line or "").replace("/", "\\").casefold()
    if _COMPANION_CJS in folded_cmd:
        return True
    if _DEV_HELPER in str(command_line or "").casefold():
        return True
    return _is_installed_companion_node(process_path, local_app_data)


def phone_bridge_holder_status(
    rows: Iterable[PhoneBridgeTcpRow],
    *,
    phone_host: str,
    phone_port: int,
    own_pid: int | None = None,
    local_app_data: str | None = None,
    host_keys: Iterable[str] | None = None,
) -> str | None:
    """User status when another process on this PC holds ``phone_host:phone_port``.

    ``None`` means no other established session was found. ``rows`` may include
    unrelated connections (tests pass those); only an established remote
    endpoint for this phone counts. A live phone is not required.
    """
    try:
        port = int(phone_port)
    except (TypeError, ValueError):
        return None
    keys = _match_keys(phone_host, host_keys)
    if not keys or port < 1 or port > 65535:
        return None
    app_data = _default_local_app_data() if local_app_data is None else str(local_app_data)
    companion = False
    program_name = ""
    found = False
    for row in rows:
        if not _row_holds_phone(row, keys=keys, phone_port=port, own_pid=own_pid):
            continue
        found = True
        if is_flaretracker_bridge_companion(
            row.process_path,
            row.command_line,
            app_data,
        ):
            companion = True
            break
        if not program_name:
            program_name = _program_name(row.process_path, row.command_line)
    if not found:
        return None
    if companion:
        return COMPANION_BUSY_STATUS
    if program_name:
        return other_program_busy_status(program_name)
    return OTHER_PROGRAM_BUSY_STATUS


def local_phone_bridge_holder_status(host: str, port: int) -> str | None:
    """Live check of this PC. ``None`` when no other local session is visible.

    Failures (permissions, unsupported OS) report nothing so Connect can proceed.
    """
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        return None
    if port_i < 1 or port_i > 65535:
        return None
    try:
        keys = resolve_phone_host_keys(host)
        if not keys:
            return None
        rows = collect_phone_bridge_tcp_rows(keys, port_i)
        return phone_bridge_holder_status(
            rows,
            phone_host=str(host or ""),
            phone_port=port_i,
            own_pid=os.getpid(),
            local_app_data=_default_local_app_data(),
            host_keys=keys,
        )
    except Exception:
        return None


def resolve_phone_host_keys(host: str) -> set[str]:
    """Normalized address keys for a typed host. IP literals skip DNS."""
    keys: set[str] = set()
    literal = _host_key(host)
    if literal:
        keys.add(literal)
    text = _strip_host_decorations(host)
    if not text:
        return keys
    try:
        ipaddress.ip_address(text)
        return keys
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(text, None, type=socket.SOCK_STREAM)
    except OSError:
        return keys
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
        if not sockaddr:
            continue
        key = _host_key(str(sockaddr[0]))
        if key:
            keys.add(key)
    return keys


def collect_phone_bridge_tcp_rows(
    host_keys: Iterable[str],
    phone_port: int,
) -> list[PhoneBridgeTcpRow]:
    """Established connections on this PC to ``host_keys`` at ``phone_port``.

    This process is omitted. Process image and command line are filled in for
    the remaining owners. An owner whose image cannot be read is still returned
    so Connect will not replace an unknown holder.
    """
    keys = {key for key in (_host_key(item) for item in host_keys) if key}
    port = int(phone_port)
    if not keys or port < 1 or port > 65535:
        return []
    own_pid = os.getpid()
    app_data = _default_local_app_data()
    rows: list[PhoneBridgeTcpRow] = []
    seen: set[int] = set()
    for remote_host, remote_port, pid in _iter_established_tcp_endpoints(keys, port):
        if int(remote_port) != port:
            continue
        if _host_key(remote_host) not in keys:
            continue
        pid_i = int(pid)
        if pid_i == own_pid or pid_i in seen:
            continue
        if pid_i > 0:
            seen.add(pid_i)
        path, command_line = ("", "")
        if pid_i > 0:
            path, command_line = _process_path_and_command_line(pid_i, app_data)
        rows.append(
            PhoneBridgeTcpRow(
                remote_host=remote_host,
                remote_port=port,
                pid=pid_i,
                state="ESTABLISHED",
                process_path=path,
                command_line=command_line,
            )
        )
    return rows


def parse_windows_ipv4_owner_pid_table(blob: bytes) -> list[tuple[str, int, int, str]]:
    """Parse a ``MIB_TCPTABLE_OWNER_PID`` blob.

    Each item is ``(remote_ip, remote_port, pid, state_name)``.
    """
    return _parse_windows_owner_table(blob, ipv6=False)


def parse_windows_ipv6_owner_pid_table(blob: bytes) -> list[tuple[str, int, int, str]]:
    """Parse a ``MIB_TCP6TABLE_OWNER_PID`` blob."""
    return _parse_windows_owner_table(blob, ipv6=True)


def parse_proc_net_tcp_line(
    line: str,
    *,
    ipv6: bool = False,
) -> tuple[str, int, str, str] | None:
    """Parse one ``/proc/net/tcp`` or ``tcp6`` line.

    Returns ``(remote_ip, remote_port, inode, state_name)``, or ``None`` for
    the header and short lines. Linux state ``01`` is ``ESTABLISHED``.
    """
    parts = str(line or "").split()
    if len(parts) < 10 or parts[0] == "sl":
        return None
    remote = parts[2]
    if ":" not in remote:
        return None
    addr_hex, port_hex = remote.rsplit(":", 1)
    try:
        port = int(port_hex, 16)
        state = int(parts[3], 16)
    except ValueError:
        return None
    ip = _ip_from_proc_hex(addr_hex, ipv6=ipv6)
    if not ip:
        return None
    state_name = "ESTABLISHED" if state == _LINUX_TCP_ESTABLISHED else f"{state:02X}"
    return ip, port, parts[9], state_name


def _row_holds_phone(
    row: PhoneBridgeTcpRow,
    *,
    keys: set[str],
    phone_port: int,
    own_pid: int | None,
) -> bool:
    if own_pid is not None and int(row.pid) == int(own_pid):
        return False
    if str(row.state or "").strip().casefold() not in _ESTABLISHED_STATES:
        return False
    try:
        remote_port = int(row.remote_port)
    except (TypeError, ValueError):
        return False
    if remote_port != int(phone_port):
        return False
    return _host_key(row.remote_host) in keys


def _match_keys(phone_host: str, host_keys: Iterable[str] | None) -> set[str]:
    if host_keys is None:
        key = _host_key(phone_host)
        return {key} if key else set()
    keys = {key for key in (_host_key(item) for item in host_keys) if key}
    if keys:
        return keys
    key = _host_key(phone_host)
    return {key} if key else set()


def _default_local_app_data() -> str:
    raw = os.environ.get("LOCALAPPDATA", "").strip()
    if raw:
        return raw
    if os.name == "nt":
        return str(os.path.join(os.path.expanduser("~"), "AppData", "Local"))
    return ""


def _is_installed_companion_node(process_path: str, local_app_data: str) -> bool:
    root_text = str(local_app_data or "").strip()
    if not root_text or not str(process_path or "").strip():
        return False
    root = _path_parts(root_text + "\\FlareTracker\\BridgeCompanion")
    parts = _path_parts(process_path)
    if len(parts) < len(root) + 2:
        return False
    if parts[: len(root)] != root:
        return False
    return parts[-2:] == ("runtime", "node.exe")


def _program_name(process_path: str, command_line: str) -> str:
    name = _exe_basename(process_path)
    if name:
        return name
    return _exe_basename(_first_command_token(command_line))


def _exe_basename(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    if not text:
        return ""
    text = text.replace("/", "\\")
    parts = [part for part in text.split("\\") if part and part not in {".", ".."}]
    if not parts:
        return ""
    return parts[-1].strip()


def _first_command_token(command_line: str) -> str:
    text = str(command_line or "").strip()
    if not text:
        return ""
    quote = text[0]
    if quote in {'"', "'"}:
        end = text.find(quote, 1)
        if end > 1:
            return text[1:end]
    return text.split()[0]


def _path_parts(value: str) -> tuple[str, ...]:
    text = str(value or "").strip().strip('"').strip("'")
    text = text.replace("/", "\\")
    parts = [part.casefold() for part in text.split("\\") if part and part != "."]
    return tuple(parts)


def _strip_host_decorations(host: str) -> str:
    text = str(host or "").strip()
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    if "%" in text:
        text = text.split("%", 1)[0]
    return text.strip()


def _host_key(host: str) -> str:
    text = _strip_host_decorations(host)
    if not text:
        return ""
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return text.casefold()
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if isinstance(ip, ipaddress.IPv6Address):
        return ip.compressed.casefold()
    return str(ip)


def _iter_established_tcp_endpoints(
    host_keys: set[str] | None = None,
    phone_port: int | None = None,
) -> list[tuple[str, int, int]]:
    if os.name == "nt":
        # The table already carries the owner pid, so filtering happens in the caller.
        return _windows_established_tcp_endpoints()
    if os.name == "posix" and os.path.isdir("/proc/net"):
        return _linux_established_tcp_endpoints(host_keys, phone_port)
    return []


def _process_path_and_command_line(pid: int, local_app_data: str) -> tuple[str, str]:
    try:
        if os.name == "nt":
            path = _windows_process_image_path(pid)
            command_line = ""
            if not _is_installed_companion_node(path, local_app_data):
                command_line = _windows_process_command_line(pid)
            return path, command_line
        if os.path.isdir(f"/proc/{int(pid)}"):
            return _linux_process_identity(pid)
    except Exception:
        return "", ""
    return "", ""


def _windows_established_tcp_endpoints() -> list[tuple[str, int, int]]:
    import ctypes
    from ctypes import wintypes

    endpoints: list[tuple[str, int, int]] = []
    af_inet = 2
    af_inet6 = 23
    for family, parser in (
        (af_inet, parse_windows_ipv4_owner_pid_table),
        (af_inet6, parse_windows_ipv6_owner_pid_table),
    ):
        blob = _windows_extended_tcp_table(family, ctypes, wintypes)
        for remote_ip, remote_port, pid, state_name in parser(blob):
            if state_name != "ESTABLISHED" or remote_port <= 0 or not remote_ip:
                continue
            endpoints.append((remote_ip, int(remote_port), int(pid)))
    return endpoints


def _windows_extended_tcp_table(address_family: int, ctypes, wintypes) -> bytes:
    error_insufficient_buffer = 122
    tcp_table_owner_pid_connections = 4
    iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    get_table(None, ctypes.byref(size), False, int(address_family), tcp_table_owner_pid_connections, 0)
    if int(size.value) <= 0:
        return b""
    for _ in range(4):
        buf = ctypes.create_string_buffer(int(size.value))
        ret = int(
            get_table(
                ctypes.cast(buf, ctypes.c_void_p),
                ctypes.byref(size),
                False,
                int(address_family),
                tcp_table_owner_pid_connections,
                0,
            )
        )
        if ret == 0:
            return buf.raw[: int(size.value)]
        if ret != error_insufficient_buffer or int(size.value) <= 0:
            return b""
    return b""


def _parse_windows_owner_table(blob: bytes, *, ipv6: bool) -> list[tuple[str, int, int, str]]:
    data = bytes(blob or b"")
    if len(data) < 4:
        return []
    count = struct.unpack_from("<I", data, 0)[0]
    # IPv4 MIB_TCPROW_OWNER_PID is 6 DWORDs. IPv6 MIB_TCP6ROW_OWNER_PID is 56 bytes.
    row_size = 56 if ipv6 else 24
    offset = 4
    rows: list[tuple[str, int, int, str]] = []
    for _ in range(int(count)):
        if offset + row_size > len(data):
            break
        if ipv6:
            remote = data[offset + 24 : offset + 40]
            remote_port, state, pid = struct.unpack_from("<III", data, offset + 44)
            remote_ip = _ipv6_from_bytes(remote)
        else:
            state, _local_addr, _local_port, remote_addr, remote_port, pid = struct.unpack_from(
                "<IIIIII", data, offset
            )
            remote_ip = _ipv4_from_dword(remote_addr)
        offset += row_size
        state_name = _WINDOWS_TCP_STATE_NAMES.get(int(state), str(int(state)))
        rows.append((remote_ip, _port_from_dword(int(remote_port)), int(pid), state_name))
    return rows


def _ipv4_from_dword(value: int) -> str:
    try:
        return socket.inet_ntoa(struct.pack("<I", int(value) & 0xFFFFFFFF))
    except OSError:
        return ""


def _ipv6_from_bytes(raw: bytes) -> str:
    if len(raw) != 16:
        return ""
    try:
        return str(ipaddress.IPv6Address(raw))
    except ValueError:
        return ""


def _port_from_dword(value: int) -> int:
    return int(socket.ntohs(int(value) & 0xFFFF))


def _windows_kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_wchar_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    return kernel32


def _windows_open_process(kernel32, pid: int, access: int):
    handle = kernel32.OpenProcess(int(access), False, int(pid))
    if not handle:
        return None
    return handle


def _windows_process_image_path(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = _windows_kernel32()
    handle = _windows_open_process(kernel32, pid, process_query_limited_information)
    if handle is None:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        if not ok:
            return ""
        return str(buf.value or "")
    finally:
        kernel32.CloseHandle(handle)


def _windows_process_command_line(pid: int) -> str:
    import ctypes

    process_query_limited_information = 0x1000
    process_query_information = 0x0400
    process_vm_read = 0x0010
    kernel32 = _windows_kernel32()
    limited = _windows_open_process(kernel32, pid, process_query_limited_information)
    if limited is not None:
        try:
            text = _windows_command_line_class60(limited, ctypes)
        finally:
            kernel32.CloseHandle(limited)
        if _plausible_command_line(text):
            return text
    full = _windows_open_process(
        kernel32,
        pid,
        process_query_information | process_vm_read,
    )
    if full is None:
        return ""
    try:
        text = _windows_command_line_from_peb(full, kernel32, ctypes)
    finally:
        kernel32.CloseHandle(full)
    return text if _plausible_command_line(text) else ""


def _windows_command_line_class60(handle, ctypes) -> str:
    """``ProcessCommandLineInformation`` (60) on Windows 8.1+. Empty if unavailable."""
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    query = ntdll.NtQueryInformationProcess
    query.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    query.restype = ctypes.c_long
    process_command_line_information = 60
    status_info_length_mismatch = ctypes.c_long(0xC0000004).value
    length = ctypes.c_ulong(32768)
    buf = ctypes.create_string_buffer(int(length.value))
    status = int(
        query(
            handle,
            process_command_line_information,
            buf,
            len(buf),
            ctypes.byref(length),
        )
    )
    if status == status_info_length_mismatch and int(length.value) > len(buf):
        buf = ctypes.create_string_buffer(int(length.value) + 8)
        status = int(
            query(
                handle,
                process_command_line_information,
                buf,
                len(buf),
                ctypes.byref(length),
            )
        )
    if status != 0:
        return ""
    return _decode_unicode_string_buffer(buf)


def _decode_unicode_string_buffer(buf) -> str:
    raw = bytes(buf.raw)
    if len(raw) < 8:
        return ""
    str_len = struct.unpack_from("<H", raw, 0)[0]
    if str_len <= 0:
        return ""
    ptr_off = 8 if struct.calcsize("P") == 8 else 4
    ptr_fmt = "<Q" if ptr_off == 8 else "<I"
    if len(raw) < ptr_off + struct.calcsize(ptr_fmt):
        return ""
    ptr = struct.unpack_from(ptr_fmt, raw, ptr_off)[0]
    base = _ctypes_addressof(buf)
    if ptr and base <= ptr < base + len(raw):
        start = int(ptr - base)
    else:
        start = 16 if ptr_off == 8 else 8
    end = min(len(raw), start + int(str_len))
    if start < 0 or start >= end:
        return ""
    return raw[start:end].decode("utf-16-le", errors="replace").replace("\x00", "").strip()


def _plausible_command_line(text: str) -> bool:
    sample = " ".join(str(text or "").split())
    if len(sample) < 2:
        return False
    printable = sum(1 for ch in sample if ch.isprintable())
    return printable >= max(2, int(len(sample) * 0.85))


def _ctypes_addressof(buf) -> int:
    import ctypes

    return int(ctypes.addressof(buf))


def _windows_command_line_from_peb(handle, kernel32, ctypes) -> str:
    """Read ``PEB -> ProcessParameters -> CommandLine`` for a same-bitness process."""
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    query = ntdll.NtQueryInformationProcess
    query.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    query.restype = ctypes.c_long
    pointer = struct.calcsize("P")
    info = ctypes.create_string_buffer(pointer * 6)
    ret_len = ctypes.c_ulong(0)
    status = int(query(handle, 0, info, len(info), ctypes.byref(ret_len)))
    if status != 0:
        return ""
    peb = struct.unpack_from("<Q" if pointer == 8 else "<I", info.raw, pointer)[0]
    if not peb:
        return ""
    params_offset = 0x20 if pointer == 8 else 0x10
    params_raw = _read_process_memory(kernel32, handle, peb + params_offset, pointer, ctypes)
    if not params_raw:
        return ""
    params = struct.unpack("<Q" if pointer == 8 else "<I", params_raw)[0]
    if not params:
        return ""
    # RTL_USER_PROCESS_PARAMETERS.CommandLine is a UNICODE_STRING.
    cmd_offset = 0x70 if pointer == 8 else 0x40
    us_size = 16 if pointer == 8 else 8
    us_raw = _read_process_memory(kernel32, handle, params + cmd_offset, us_size, ctypes)
    if not us_raw or len(us_raw) < us_size:
        return ""
    str_len = struct.unpack_from("<H", us_raw, 0)[0]
    buf_ptr = struct.unpack_from("<Q" if pointer == 8 else "<I", us_raw, 8 if pointer == 8 else 4)[0]
    if not buf_ptr or str_len <= 0:
        return ""
    str_len = min(int(str_len), 32768)
    text_raw = _read_process_memory(kernel32, handle, buf_ptr, str_len, ctypes)
    if not text_raw:
        return ""
    return text_raw.decode("utf-16-le", errors="replace").replace("\x00", "").strip()


def _read_process_memory(kernel32, handle, address: int, size: int, ctypes) -> bytes | None:
    if int(address) <= 0 or int(size) <= 0:
        return None
    buf = ctypes.create_string_buffer(int(size))
    nread = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(
        handle,
        ctypes.c_void_p(int(address)),
        buf,
        ctypes.c_size_t(int(size)),
        ctypes.byref(nread),
    )
    if not ok:
        return None
    return buf.raw[: int(nread.value)]


def _linux_established_tcp_endpoints(
    host_keys: set[str] | None = None,
    phone_port: int | None = None,
) -> list[tuple[str, int, int]]:
    pending: list[tuple[str, int, str]] = []
    for path, ipv6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except OSError:
            continue
        for line in lines:
            parsed = parse_proc_net_tcp_line(line, ipv6=ipv6)
            if parsed is None:
                continue
            remote_ip, remote_port, inode, state_name = parsed
            if state_name != "ESTABLISHED" or not inode or inode == "0":
                continue
            if phone_port is not None and int(remote_port) != int(phone_port):
                continue
            if host_keys is not None and _host_key(remote_ip) not in host_keys:
                continue
            pending.append((remote_ip, int(remote_port), inode))
    if not pending:
        return []
    pid_by_inode = _linux_pids_for_socket_inodes({inode for _ip, _port, inode in pending})
    endpoints: list[tuple[str, int, int]] = []
    for remote_ip, remote_port, inode in pending:
        pid = pid_by_inode.get(inode, 0)
        endpoints.append((remote_ip, remote_port, int(pid)))
    return endpoints


def _linux_pids_for_socket_inodes(inodes: set[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    if not inodes:
        return found
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    for entry in entries:
        if len(found) == len(inodes):
            break
        if not entry.isdigit():
            continue
        fd_dir = f"/proc/{entry}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            if len(found) == len(inodes):
                break
            try:
                target = os.readlink(f"{fd_dir}/{fd}")
            except OSError:
                continue
            if not target.startswith("socket:[") or not target.endswith("]"):
                continue
            inode = target[8:-1]
            if inode in inodes and inode not in found:
                found[inode] = int(entry)
    return found


def _linux_process_identity(pid: int) -> tuple[str, str]:
    path = ""
    command_line = ""
    try:
        path = os.readlink(f"/proc/{int(pid)}/exe")
    except OSError:
        path = ""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as handle:
            raw = handle.read()
        command_line = " ".join(
            part.decode("utf-8", errors="replace") for part in raw.split(b"\x00") if part
        )
    except OSError:
        command_line = ""
    return path, command_line


def _ip_from_proc_hex(hex_addr: str, *, ipv6: bool) -> str:
    text = str(hex_addr or "").strip()
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        return ""
    if not ipv6:
        if len(raw) != 4:
            return ""
        try:
            return socket.inet_ntoa(raw[::-1])
        except OSError:
            return ""
    if len(raw) != 16:
        return ""
    words = [raw[index : index + 4][::-1] for index in range(0, 16, 4)]
    try:
        return str(ipaddress.IPv6Address(b"".join(words)))
    except ValueError:
        return ""


# Imported names kept for tests that build table bytes without a live socket.
__all__ = [
    "COMPANION_BUSY_STATUS",
    "OTHER_PROGRAM_BUSY_STATUS",
    "PhoneBridgeTcpRow",
    "collect_phone_bridge_tcp_rows",
    "is_flaretracker_bridge_companion",
    "is_phone_bridge_held_locally_status",
    "local_phone_bridge_holder_status",
    "other_program_busy_status",
    "parse_proc_net_tcp_line",
    "parse_windows_ipv4_owner_pid_table",
    "parse_windows_ipv6_owner_pid_table",
    "phone_bridge_holder_status",
    "resolve_phone_host_keys",
]
