#!/usr/bin/env python3
"""Create a BPS1 patch from a source ROM and its translated target ROM."""

from __future__ import annotations

import argparse
import zlib
from pathlib import Path


def encode_number(value: int) -> bytes:
    if value < 0:
        raise ValueError("BPS numbers cannot be negative")
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            encoded.append(byte | 0x80)
            return bytes(encoded)
        encoded.append(byte)
        value -= 1


def emit_action(output: bytearray, action: int, length: int) -> None:
    if length <= 0:
        return
    output.extend(encode_number(((length - 1) << 2) | action))


def create_bps(source: bytes, target: bytes) -> bytes:
    """Encode a deterministic BPS patch using same-offset source reads."""
    patch = bytearray(b"BPS1")
    patch.extend(encode_number(len(source)))
    patch.extend(encode_number(len(target)))
    patch.extend(encode_number(0))  # No metadata.

    offset = 0
    while offset < len(target):
        same_offset = offset < len(source) and source[offset] == target[offset]
        end = offset + 1
        if same_offset:
            while end < len(target) and end < len(source) and source[end] == target[end]:
                end += 1
            emit_action(patch, 0, end - offset)  # SourceRead.
        else:
            while end < len(target) and (end >= len(source) or source[end] != target[end]):
                end += 1
            emit_action(patch, 1, end - offset)  # TargetRead.
            patch.extend(target[offset:end])
        offset = end

    patch.extend(zlib.crc32(source).to_bytes(4, "little"))
    patch.extend(zlib.crc32(target).to_bytes(4, "little"))
    patch.extend(zlib.crc32(patch).to_bytes(4, "little"))
    return bytes(patch)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a BPS patch from two ROM files.")
    parser.add_argument("source", type=Path, help="Original ROM")
    parser.add_argument("target", type=Path, help="Translated ROM")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output .bps patch")
    args = parser.parse_args()

    patch = create_bps(args.source.read_bytes(), args.target.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patch)
    print(f"Wrote {args.output} ({len(patch):,} bytes)")


if __name__ == "__main__":
    main()
