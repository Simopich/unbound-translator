from __future__ import annotations

import zlib

from tests.helpers import load_script_module

bps = load_script_module("scripts/create_bps.py", "create_bps_under_test")


def _decode_number(data, offset):
    value = 0
    shift = 1
    while True:
        byte = data[offset]
        offset += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, offset
        shift <<= 7
        value += shift


def _apply_bps(source, patch):
    assert patch[:4] == b"BPS1"
    offset = 4
    source_size, offset = _decode_number(patch, offset)
    target_size, offset = _decode_number(patch, offset)
    metadata_size, offset = _decode_number(patch, offset)
    assert source_size == len(source)
    offset += metadata_size
    target = bytearray()
    source_relative = 0
    target_relative = 0

    while len(target) < target_size:
        command, offset = _decode_number(patch, offset)
        action = command & 3
        length = (command >> 2) + 1
        if action == 0:
            start = len(target)
            target.extend(source[start: start + length])
        elif action == 1:
            target.extend(patch[offset: offset + length])
            offset += length
        elif action == 2:
            delta, offset = _decode_number(patch, offset)
            source_relative += -(delta >> 1) if delta & 1 else delta >> 1
            target.extend(source[source_relative: source_relative + length])
            source_relative += length
        else:
            delta, offset = _decode_number(patch, offset)
            target_relative += -(delta >> 1) if delta & 1 else delta >> 1
            for _ in range(length):
                target.append(target[target_relative])
                target_relative += 1

    source_crc = int.from_bytes(patch[offset: offset + 4], "little")
    target_crc = int.from_bytes(patch[offset + 4: offset + 8], "little")
    patch_crc = int.from_bytes(patch[offset + 8: offset + 12], "little")
    assert source_crc == zlib.crc32(source)
    assert target_crc == zlib.crc32(target)
    assert patch_crc == zlib.crc32(patch[:-4])
    return bytes(target)


def test_create_bps_round_trips_source_reads_and_target_reads():
    source = b"Pokemon Unbound source ROM text"
    target = b"Pokemon Unbound translated ROM testo"

    patch = bps.create_bps(source, target)

    assert _apply_bps(source, patch) == target
