"""Compressed BLF validation must reject truncated and unfinalized captures."""

import struct
import zlib

import pytest

from vil_logging.storage.blf import FILE_HEADER, OBJECT_HEADER, inspect_blf


def make_blf(records, *, method=2, split=32768):
    records = b"".join(records)
    containers = bytearray()
    for offset in range(0, len(records), split):
        raw = records[offset:offset + split]
        packed = zlib.compress(raw) if method == 2 else raw
        body = struct.pack("<H6xI4x", method, len(raw)) + packed
        container = OBJECT_HEADER.pack(b"LOBJ", 16, 1, 16 + len(body), 10) + body
        containers.extend(container + bytes(len(container) % 4))
    count = records.count(b"LOBJ")
    size = 144 + len(containers)
    header = FILE_HEADER.pack(b"LOGG", 144, *([0] * 8), size, 144 + len(records), count, 0, *([0] * 16))
    return header.ljust(144, b"\0") + containers


def record(kind=1, payload=b"12345678"):
    size = 32 + len(payload)
    return OBJECT_HEADER.pack(b"LOBJ", 32, 1, size, kind) + bytes(16) + payload + bytes(size % 4)


@pytest.mark.parametrize("method,split", [(0, 37), (2, 29), (2, 1048576)])
def test_streams_containers_split_headers_and_unknown_record_types(tmp_path, method, split):
    path = tmp_path / "capture.blf"
    path.write_bytes(make_blf([record(), record(9999), record(payload=bytes(700000))], method=method, split=split))
    result = inspect_blf(path)
    assert result["object_count"] == 3
    assert result["object_types"] == {1: 2, 9999: 1}
    assert result["actual_format"] == "blf"


def test_empty_finalized_blf_is_structurally_valid_without_claiming_traffic(tmp_path):
    path = tmp_path / "empty.blf"
    path.write_bytes(make_blf([]))
    assert inspect_blf(path)["object_count"] == 0


def test_header_count_can_exclude_vector_metadata_records(tmp_path):
    content = bytearray(make_blf([record(), record(115)]))
    struct.pack_into("<I", content, 32, 1)
    path = tmp_path / "metadata.blf"
    path.write_bytes(content)
    result = inspect_blf(path)
    assert result["declared_object_count"] == 1 and result["object_count"] == 2
    assert result["header_count_matches"] is False


@pytest.mark.parametrize("fault", ["truncated", "compressed", "count", "partial_object", "size"])
def test_damaged_or_unfinalized_blf_is_rejected(tmp_path, fault):
    content = bytearray(make_blf([record()]))
    if fault == "truncated":
        del content[-8:]
    elif fault == "compressed":
        content[-8] ^= 0x40
    elif fault == "count":
        struct.pack_into("<I", content, 32, 8)
    elif fault == "partial_object":
        content = bytearray(make_blf([record()[:-2]]))
    elif fault == "size":
        struct.pack_into("<Q", content, 16, 0)
    path = tmp_path / "damaged.blf"
    path.write_bytes(content)
    with pytest.raises((ValueError, zlib.error)):
        inspect_blf(path)
