"""Read Windows interface receive counters without opening packet capture handles."""

import ctypes
import os
import time
from collections import deque
from dataclasses import dataclass
from uuid import UUID

from .connections import _nic_key


class _Guid(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]


class _Row(ctypes.Structure):
    # MIB_IF_ROW2, netioapi.h. Native alignment is required (including table padding).
    _fields_ = [("luid", ctypes.c_uint64), ("index", ctypes.c_uint32), ("guid", _Guid),
                ("alias", ctypes.c_wchar * 257), ("description", ctypes.c_wchar * 257),
                ("address_length", ctypes.c_uint32), ("address", ctypes.c_ubyte * 32),
                ("permanent_address", ctypes.c_ubyte * 32)] + [
        (name, ctypes.c_uint32) for name in ("mtu", "type", "tunnel", "media", "physical_media", "access", "direction")
    ] + [("flags", ctypes.c_ubyte)] + [
        (name, ctypes.c_uint32) for name in ("oper_status", "admin_status", "media_state")
    ] + [("network_guid", _Guid), ("connection_type", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in (
            "tx_link", "rx_link", "rx_bytes", "rx_unicast", "rx_other", "rx_discards", "rx_errors", "rx_unknown",
            "rx_unicast_bytes", "rx_multicast_bytes", "rx_broadcast_bytes", "tx_bytes", "tx_unicast", "tx_other",
            "tx_discards", "tx_errors", "tx_unicast_bytes", "tx_multicast_bytes", "tx_broadcast_bytes", "tx_queue")
    ]


class _Table(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint32), ("rows", _Row * 1)]


@dataclass(frozen=True)
class ReceiveCounter:
    packets: int
    identity: int
    status: int


def read_receive_counters():
    """Return GUID-keyed cumulative packet counts; FreeMibTable on every path."""
    if os.name != "nt":
        raise OSError("Windows interface counters are unavailable")
    api = ctypes.WinDLL("iphlpapi")
    api.GetIfTable2.argtypes = [ctypes.POINTER(ctypes.POINTER(_Table))]
    api.GetIfTable2.restype = ctypes.c_uint32
    api.FreeMibTable.argtypes = [ctypes.c_void_p]
    api.FreeMibTable.restype = None
    table = ctypes.POINTER(_Table)()
    error = api.GetIfTable2(ctypes.byref(table))
    if error:
        raise ctypes.WinError(error)
    try:
        count = table.contents.count
        if count > 10_000:
            raise ValueError("Unexpected interface table size")
        rows = ctypes.cast(ctypes.addressof(table.contents) + _Table.rows.offset, ctypes.POINTER(_Row))
        result = {}
        for i in range(count):
            row = rows[i]
            guid = str(UUID(bytes_le=ctypes.string_at(ctypes.byref(row.guid), 16))).upper()
            value = ReceiveCounter(int(row.rx_unicast) + int(row.rx_other), int(row.luid), int(row.oper_status))
            result[guid] = value
            if row.type == 24:  # Windows software loopback maps to Npcap's special capture ID.
                result[_nic_key(r"\Device\NPF_Loopback")] = value
        return time.monotonic(), result
    finally:
        api.FreeMibTable(table)


class ActivityHistory:
    """Bounded receive pps history; gaps/resets are unknown, never a fake zero/spike."""
    def __init__(self, length=24):
        self.length = length
        self.previous = {}
        self.history = {}
        self.missing = {}

    def reset_baseline(self):
        self.previous.clear()

    def update(self, when, counters):
        result = {}
        for key in self.history.keys() | counters.keys():
            value, previous = counters.get(key), self.previous.get(key)
            rate = None
            if value is not None and previous is not None:
                old_time, old = previous
                elapsed = when - old_time
                if (0 < elapsed <= 5 and value.identity == old.identity and value.status == old.status
                        and value.packets >= old.packets):
                    rate = (value.packets - old.packets) / elapsed
            if value is None:
                self.previous.pop(key, None)
                self.missing[key] = self.missing.get(key, 0) + 1
                if self.missing[key] >= self.length:
                    self.history.pop(key, None)
                    self.missing.pop(key, None)
                    continue
            else:
                self.missing.pop(key, None)
                self.previous[key] = when, value
            history = self.history.setdefault(key, deque(maxlen=self.length))
            history.append(rate)
            result[key] = {"pps": rate, "history": list(history)}
        return result
