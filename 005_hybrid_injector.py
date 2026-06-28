#!/usr/bin/env python3

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from lib.pcs_text import Charmap, fc_arg_count


GBA_POINTER_BASE = 0x08000000
DEFAULT_MIN_ADDRESS = 0x100
DEFAULT_MIN_FREE_RUN = 0x1000
TERMINATOR = 0xFF


def parse_address(value):
    if isinstance(value, int):
        address = value
    elif isinstance(value, str):
        address = int(value, 16) if value.lower().startswith("0x") else int(value)
    else:
        raise ValueError(f"Invalid address: {value!r}")

    if address >= GBA_POINTER_BASE:
        address -= GBA_POINTER_BASE
    return address


def strip_hma_quotes(text):
    if isinstance(text, str) and len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text or ""


def byte_placeholders(values):
    return "".join(f"{{{value:02X}}}" for value in values)


def normalize_text_escapes(text):
    """Convert legacy HMA escape forms to raw byte placeholders."""

    text = re.sub(
        r"\\\\([0-9A-Fa-f]{2})",
        lambda match: byte_placeholders((0xFD, int(match.group(1), 16))),
        text,
    )

    def raw_bytes(match):
        hex_text = re.sub(r"\s+", "", match.group(1))
        if len(hex_text) % 2:
            hex_text = hex_text[:-1]
        values = [int(hex_text[index : index + 2], 16) for index in range(0, len(hex_text), 2)]
        return byte_placeholders(values)

    text = re.sub(r"\\!((?:\s*[0-9A-Fa-f]{2})+)", raw_bytes, text)
    text = re.sub(
        r"\\\?([0-9A-Fa-f]{2})",
        lambda match: byte_placeholders((0xF7, int(match.group(1), 16))),
        text,
    )
    text = re.sub(
        r"\\9([0-9A-Fa-f]{2})",
        lambda match: byte_placeholders((0xF9, int(match.group(1), 16))),
        text,
    )
    text = re.sub(
        r"\\F([0-9A-Fa-f])",
        lambda match: byte_placeholders((int("F" + match.group(1), 16),)),
        text,
    )

    return text


def normalize_plain_script_layout(text):
    """Encode full-screen script layout with raw newlines, never prompt-clear."""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pieces = []
    index = 0

    while index < len(text):
        if text[index] == "\n":
            pieces.append("\\n")
            index += 1
            continue
        if text.startswith("\\pn", index):
            pieces.append("\\n\\n")
            index += 3
            continue
        if text.startswith("\\p", index) and not text.startswith("\\pk", index):
            pieces.append("\\n\\n")
            index += 2
            continue
        if text.startswith("\\l", index):
            pieces.append("\\n")
            index += 2
            continue

        pieces.append(text[index])
        index += 1

    return "".join(pieces)


def encode_text(cmap, text, *, plain_script=False):
    text = strip_hma_quotes(text)
    if plain_script:
        text = normalize_plain_script_layout(text)
    return bytes(cmap.encode(normalize_text_escapes(text)))


def truncate_encoded(encoded, max_size):
    if max_size <= 0:
        return b""
    if len(encoded) <= max_size and encoded.endswith(bytes((TERMINATOR,))):
        return encoded
    if max_size == 1:
        return bytes((TERMINATOR,))

    limit = max_size - 1
    out = bytearray()
    index = 0

    while index < len(encoded):
        byte = encoded[index]
        if byte == TERMINATOR:
            break

        token_len = 1
        if byte == 0xFC and index + 1 < len(encoded):
            token_len = 2 + fc_arg_count(encoded[index + 1])
        elif byte in (0xF7, 0xF8, 0xF9, 0xFD):
            token_len = 2

        if index + token_len > len(encoded) or len(out) + token_len > limit:
            break

        out.extend(encoded[index : index + token_len])
        index += token_len

    out.append(TERMINATOR)
    return bytes(out)


def fit_to_slot(encoded, max_size, pad_byte):
    if len(encoded) > max_size or not encoded.endswith(bytes((TERMINATOR,))):
        encoded = truncate_encoded(encoded, max_size)
    return encoded.ljust(max_size, bytes((pad_byte,)))


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


@dataclass
class FreeBlock:
    start: int
    end: int
    cursor: int

    @property
    def remaining(self):
        return self.end - self.cursor


def align_up(value, alignment):
    if alignment <= 1:
        return value
    return (value + alignment - 1) // alignment * alignment


def find_byte_runs(rom, byte_value, min_len, min_address):
    runs = []
    i = max(0, min_address)
    n = len(rom)

    while i < n:
        if rom[i] != byte_value:
            i += 1
            continue

        start = i
        while i < n and rom[i] == byte_value:
            i += 1

        if i - start >= min_len:
            runs.append((start, i))

    return runs


def merge_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if start >= end:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [(start, end) for start, end in merged]


def subtract_ranges(runs, protected):
    result = []
    protected_index = 0

    for start, end in runs:
        cursor = start
        while protected_index < len(protected) and protected[protected_index][1] <= cursor:
            protected_index += 1

        index = protected_index
        while index < len(protected) and protected[index][0] < end:
            protected_start, protected_end = protected[index]
            if protected_start > cursor:
                result.append((cursor, min(protected_start, end)))
            cursor = max(cursor, protected_end)
            if cursor >= end:
                break
            index += 1

        if cursor < end:
            result.append((cursor, end))

    return result


def protected_entry_ranges(entries, rom_size, min_address):
    ranges = []
    for entry in entries:
        try:
            start = parse_address(entry["address"])
            length = int(entry["byte_length"])
        except Exception:
            continue
        if start >= min_address and length > 0 and start + length <= rom_size:
            ranges.append((start, start + length))
    return merge_ranges(ranges)


def build_free_blocks(rom, entries, min_run, min_address):
    runs = find_byte_runs(rom, 0xFF, min_run, min_address)
    protected = protected_entry_ranges(entries, len(rom), min_address)
    runs = subtract_ranges(runs, protected)
    runs = [(start, end) for start, end in runs if end - start >= min_run]
    runs.sort(key=lambda item: item[1] - item[0], reverse=True)
    return [FreeBlock(start, end, start) for start, end in runs]


def allocate(blocks, size, alignment):
    best_index = None
    best_waste = None
    best_aligned = None

    for index, block in enumerate(blocks):
        aligned = align_up(block.cursor, alignment)
        if aligned + size > block.end:
            continue
        waste = block.end - (aligned + size)
        if best_waste is None or waste < best_waste:
            best_index = index
            best_waste = waste
            best_aligned = aligned

    if best_index is None:
        return None

    block = blocks[best_index]
    block.cursor = best_aligned + size
    return best_aligned


def pointer_sources(entry):
    return entry.get("pointer_sources") or entry.get("pointer_addresses") or []


def current_pointer_matches(rom, pointer_offset, expected_pointer):
    if pointer_offset + 4 > len(rom):
        return False
    current = int.from_bytes(rom[pointer_offset : pointer_offset + 4], "little")
    return current == expected_pointer


def is_duplicate_slot(entry, seen_slots):
    try:
        slot = (parse_address(entry["address"]), int(entry["byte_length"]))
    except Exception:
        return True
    if slot in seen_slots:
        return True
    seen_slots.add(slot)
    return False


def should_relocate_pointer_entry(entry, encoded, policy):
    if entry.get("no_relocation"):
        return False
    if not pointer_sources(entry):
        return False
    if policy == "changed":
        return True
    if policy == "oversized":
        return len(encoded) > int(entry.get("byte_length", 0))
    raise ValueError(f"Unknown relocation policy: {policy}")


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid injector: relocate pointer-based text into internal FF space and patch fixed text in-place."
    )
    parser.add_argument("rom", help="Source GBA ROM")
    parser.add_argument("json", help="Translations JSON")
    parser.add_argument("-o", "--output", default="hybrid-patched.gba", help="Output GBA ROM")
    parser.add_argument("--target-lang", default="it", help="Target language hint for text cleanup")
    parser.add_argument(
        "--min-free-run",
        default=hex(DEFAULT_MIN_FREE_RUN),
        help="Minimum FF run used for relocated text. Default: 0x1000",
    )
    parser.add_argument(
        "--min-address",
        default=hex(DEFAULT_MIN_ADDRESS),
        help="Ignore free space and text entries below this ROM offset. Default: 0x100",
    )
    parser.add_argument(
        "--alignment",
        type=int,
        default=4,
        help="Alignment for relocated text addresses. Default: 4",
    )
    parser.add_argument(
        "--pointer-policy",
        choices=("changed", "oversized"),
        default="oversized",
        help="Relocate all changed pointer text, or only pointer text too large for its original slot. Default: oversized",
    )
    parser.add_argument(
        "--pad-byte",
        default="FF",
        help="Byte used to pad shorter in-place strings, as hex. Default: FF",
    )
    parser.add_argument(
        "--map-output",
        help="Optional JSON report of relocated entries and chosen offsets.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do all allocation, encoding, and pointer checks without writing the ROM.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print skipped/truncated samples while processing.",
    )

    args = parser.parse_args()

    rom_path = Path(args.rom)
    json_path = Path(args.json)
    output_path = Path(args.output)
    min_free_run = parse_address(args.min_free_run)
    min_address = parse_address(args.min_address)
    pad_byte = int(args.pad_byte, 16)

    if not 0 <= pad_byte <= 0xFF:
        raise ValueError("--pad-byte must be between 00 and FF")
    if args.alignment < 1:
        raise ValueError("--alignment must be >= 1")

    rom = bytearray(rom_path.read_bytes())
    data = json.loads(json_path.read_text(encoding="utf-8"))
    entries = list(iter_entries(data))
    cmap = Charmap(target_lang=args.target_lang)
    free_blocks = build_free_blocks(rom, entries, min_free_run, min_address)

    stats = {
        "input_entries": len(entries),
        "free_blocks": len(free_blocks),
        "free_bytes": sum(block.end - block.start for block in free_blocks),
        "relocated": 0,
        "relocated_bytes": 0,
        "pointer_writes": 0,
        "in_place": 0,
        "unchanged": 0,
        "skipped_empty": 0,
        "skipped_unsafe": 0,
        "skipped_duplicate_fixed": 0,
        "skipped_pointer_mismatch": 0,
        "skipped_no_space": 0,
        "skipped_bounds": 0,
        "encode_errors": 0,
        "fixed_truncated": 0,
        "no_relocation_in_place": 0,
        "no_relocation_truncated": 0,
    }

    relocation_map = []
    truncation_samples = []
    mismatch_samples = []
    no_space_samples = []
    seen_fixed_slots = set()

    for entry in entries:
        translated = strip_hma_quotes(entry.get("translated", ""))
        if not translated:
            stats["skipped_empty"] += 1
            continue

        original = strip_hma_quotes(entry.get("original", ""))
        if translated == original:
            stats["unchanged"] += 1
            continue

        try:
            address = parse_address(entry["address"])
            max_size = int(entry["byte_length"])
            encoded = encode_text(
                cmap,
                translated,
                plain_script=entry.get("category") == "plain_scripts",
            )
        except Exception as exc:
            stats["encode_errors"] += 1
            if args.verbose:
                print(f"[ENCODE ERROR] {entry.get('id', '?')}: {exc}")
            continue

        if address < min_address or max_size <= 0:
            stats["skipped_unsafe"] += 1
            continue

        sources = [parse_address(source) for source in pointer_sources(entry)]
        if should_relocate_pointer_entry(entry, encoded, args.pointer_policy):
            expected_pointer = GBA_POINTER_BASE + address
            if not sources or not all(
                current_pointer_matches(rom, source, expected_pointer) for source in sources
            ):
                stats["skipped_pointer_mismatch"] += 1
                if len(mismatch_samples) < 20:
                    mismatch_samples.append(entry.get("id", "?"))
                continue

            relocated_offset = allocate(free_blocks, len(encoded), args.alignment)
            if relocated_offset is None:
                stats["skipped_no_space"] += 1
                if len(no_space_samples) < 20:
                    no_space_samples.append(
                        f"{entry.get('id', '?')}: needs {len(encoded)} bytes"
                    )
                continue

            new_pointer = GBA_POINTER_BASE + relocated_offset
            if not args.dry_run:
                rom[relocated_offset : relocated_offset + len(encoded)] = encoded
                for source in sources:
                    rom[source : source + 4] = new_pointer.to_bytes(4, "little")

            stats["relocated"] += 1
            stats["relocated_bytes"] += len(encoded)
            stats["pointer_writes"] += len(sources)
            relocation_map.append(
                {
                    "id": entry.get("id"),
                    "category": entry.get("category"),
                    "old_offset": f"0x{address:X}",
                    "new_offset": f"0x{relocated_offset:X}",
                    "new_pointer": f"0x{new_pointer:X}",
                    "byte_length": len(encoded),
                    "pointer_sources": [f"0x{source:X}" for source in sources],
                }
            )
            continue

        if sources and args.pointer_policy == "oversized":
            # Pointer text that fits stays in the original slot, but duplicate
            # script fragments are safer to leave alone than to overwrite.
            if is_duplicate_slot(entry, seen_fixed_slots):
                stats["skipped_duplicate_fixed"] += 1
                continue
        elif not sources and is_duplicate_slot(entry, seen_fixed_slots):
            stats["skipped_duplicate_fixed"] += 1
            continue

        if address + max_size > len(rom):
            stats["skipped_bounds"] += 1
            continue

        if len(encoded) > max_size:
            stats["fixed_truncated"] += 1
            if entry.get("no_relocation"):
                stats["no_relocation_truncated"] += 1
            if len(truncation_samples) < 20:
                prefix = "no_relocation " if entry.get("no_relocation") else ""
                truncation_samples.append(
                    f"{prefix}{entry.get('id', '?')}: {len(encoded)} -> {max_size}"
                )

        fitted = fit_to_slot(encoded, max_size, pad_byte)
        if not args.dry_run:
            rom[address : address + max_size] = fitted
        stats["in_place"] += 1
        if entry.get("no_relocation"):
            stats["no_relocation_in_place"] += 1

    used_free_bytes = sum(block.cursor - block.start for block in free_blocks)
    remaining_free_bytes = sum(block.end - block.cursor for block in free_blocks)

    if args.map_output:
        report_path = Path(args.map_output)
        report = {
            "rom": str(rom_path),
            "json": str(json_path),
            "output": str(output_path),
            "stats": stats,
            "used_free_bytes": used_free_bytes,
            "remaining_free_bytes": remaining_free_bytes,
            "relocations": relocation_map,
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run:
        output_path.write_bytes(rom)

    print()
    print("===================================")
    print(f"Input entries          : {stats['input_entries']}")
    print(f"Free blocks            : {stats['free_blocks']}")
    print(f"Free bytes             : {stats['free_bytes']}")
    print(f"Used free bytes        : {used_free_bytes}")
    print(f"Remaining free bytes   : {remaining_free_bytes}")
    print(f"Relocated              : {stats['relocated']}")
    print(f"Relocated bytes        : {stats['relocated_bytes']}")
    print(f"Pointer writes         : {stats['pointer_writes']}")
    print(f"In-place patched       : {stats['in_place']}")
    print(f"Unchanged              : {stats['unchanged']}")
    print(f"Skipped empty          : {stats['skipped_empty']}")
    print(f"Skipped unsafe         : {stats['skipped_unsafe']}")
    print(f"Skipped duplicate fixed: {stats['skipped_duplicate_fixed']}")
    print(f"Pointer mismatches     : {stats['skipped_pointer_mismatch']}")
    print(f"Skipped no space       : {stats['skipped_no_space']}")
    print(f"Skipped out-of-ROM     : {stats['skipped_bounds']}")
    print(f"Encode errors          : {stats['encode_errors']}")
    print(f"Fixed truncated        : {stats['fixed_truncated']}")
    print(f"No-reloc in-place      : {stats['no_relocation_in_place']}")
    print(f"No-reloc truncated     : {stats['no_relocation_truncated']}")
    if truncation_samples:
        print("Fixed truncation sample:")
        for sample in truncation_samples:
            print(f"  {sample}")
    if mismatch_samples:
        print("Pointer mismatch sample:")
        for sample in mismatch_samples:
            print(f"  {sample}")
    if no_space_samples:
        print("No-space sample:")
        for sample in no_space_samples:
            print(f"  {sample}")
    print(f"Output ROM             : {'(dry run)' if args.dry_run else output_path}")
    print("===================================")


if __name__ == "__main__":
    main()
