#!/usr/bin/env python3

import argparse
import importlib.util
import json
import re
import struct
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path

from lib.pcs_text import Charmap, decode_pcs, fc_arg_count, strip_control_tokens
from lib.translation_tokens import semantic_token_counts
from lib.unbound_free_space import VETTED_FREE_SPACE_RANGES

GBA_POINTER_BASE = 0x08000000
DEFAULT_MIN_ADDRESS = 0x100
DEFAULT_MIN_FREE_RUN = 0x400
DEFAULT_FREE_RUN_MARGIN = 8
DEFAULT_TEXT_ALIGNMENT = 1
# These FF runs contain engine-owned graphics or CFRU/Unbound reserved data.
FREE_SPACE_EXCLUDE_RANGES = (
    # Legacy BPRE text and engine area: contains live engine pointers and function calls
    (0x160000, 0x200000),
    (0x230000, 0x500000),
    # High expansion bank: CFRU engine, hooks, and dynamic data
    (0x1000000, 0x2000000),
)
TERMINATOR = 0xFF
ABILITY_DESCRIPTION_MAX_BYTES = 46
RECLAIMABLE_SCRIPT_TEXT_RANGES = (
    (0x740000, 0x800000),
    (0x8C0000, 0x8D0000),
    (0x1ED0000, 0x1FB0000),
)
RECLAIMED_DESTINATION_CATEGORIES = frozenset({"scripts", "plain_scripts"})


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


def translation_for_injection(entry):
    fixed = entry.get("translated_fixed")
    if isinstance(fixed, str) and fixed:
        fixed = strip_hma_quotes(fixed)
        full = strip_hma_quotes(entry.get("translated", ""))
        if semantic_token_counts(fixed) != semantic_token_counts(full):
            raise ValueError(
                "translated_fixed changes protected tokens for "
                f"{entry.get('id', '?')}"
            )
        return fixed
    return strip_hma_quotes(entry.get("translated", ""))


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


def compact_ability_description(encoded, period_encoded, max_size=ABILITY_DESCRIPTION_MAX_BYTES):
    """Fit Summary ability text to its validated copied-text buffer budget."""
    if len(encoded) <= max_size:
        return encoded

    body = encoded[:-1] if encoded.endswith(bytes((TERMINATOR,))) else encoded
    period = period_encoded[:-1] if period_encoded.endswith(bytes((TERMINATOR,))) else period_encoded
    marker = b"\x00" + period * 3 + b"\x00"
    content_budget = max_size - len(marker) - 1
    boundaries = [index for index, byte in enumerate(body) if byte in (0x00, 0xFE)]
    candidates = []
    for left in boundaries:
        for right_separator in boundaries:
            right = right_separator + 1
            if right <= left:
                continue
            used = left + len(body) - right
            if used > content_budget:
                continue
            balance = abs(left - (len(body) - right))
            candidates.append((-used, balance, left, right))

    if candidates:
        _neg_used, _balance, left, right = min(candidates)
        compacted = body[:left] + marker + body[right:]
        return compacted.rstrip(b"\x00\xFE") + bytes((TERMINATOR,))

    return truncate_encoded(encoded, max_size)


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
    kind: str = "vetted_ff"

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


def intersect_ranges(ranges, allowed_ranges):
    intersections = []
    for start, end in ranges:
        for allowed_start, allowed_end in allowed_ranges:
            clipped_start = max(start, allowed_start)
            clipped_end = min(end, allowed_end)
            if clipped_start < clipped_end:
                intersections.append((clipped_start, clipped_end))
    return merge_ranges(intersections)


def build_free_blocks(rom, entries, min_run, min_address, allowed_ranges=None):
    # An explicit allowlist may contain small spans proven writable by a
    # working reference ROM. Discover their containing FF runs even when the
    # generic minimum-run heuristic would otherwise hide them.
    scan_min_len = 1 if allowed_ranges is not None else min_run
    runs = find_byte_runs(rom, 0xFF, scan_min_len, min_address)
    exclude_ranges = (
        FREE_SPACE_EXCLUDE_RANGES
        if allowed_ranges is None
        else (
            (0x160000, 0x200000),
            (0x230000, 0x500000),
            (0x1000000, 0x1FE0000),
            (0x1FF3000, 0x2000000),
        )
    )
    runs = subtract_ranges(runs, exclude_ranges)
    protected = protected_entry_ranges(entries, len(rom), min_address)
    runs = subtract_ranges(runs, protected)
    runs = [
        (start + DEFAULT_FREE_RUN_MARGIN, end - DEFAULT_FREE_RUN_MARGIN)
        for start, end in runs
        if end - start >= scan_min_len
           and end - start > 2 * DEFAULT_FREE_RUN_MARGIN
    ]
    if allowed_ranges is not None:
        runs = intersect_ranges(runs, allowed_ranges)
    runs.sort()
    return [FreeBlock(start, end, start) for start, end in runs]


def allocate_best_fit(blocks, size, alignment=1):
    best_idx = None
    best_waste = float("inf")
    best_offset = None
    for i, block in enumerate(blocks):
        aligned = align_up(block.cursor, alignment)
        if aligned + size <= block.end:
            waste = (block.end - block.cursor) - size
            if waste < best_waste:
                best_waste = waste
                best_idx = i
                best_offset = aligned
    if best_idx is not None:
        block = blocks[best_idx]
        block.cursor = best_offset + size
        return best_offset, block
    return None, None


def allocate_with_block(blocks, size, alignment):
    for block in blocks:
        aligned = align_up(block.cursor, alignment)
        if aligned + size <= block.end:
            block.cursor = aligned + size
            return aligned, block
    return None, None


def allocate(blocks, size, alignment):
    offset, _block = allocate_with_block(blocks, size, alignment)
    return offset


@dataclass
class RelocationCandidate:
    entry: dict
    address: int
    max_size: int
    encoded: bytes
    sources: tuple[int, ...]
    reclaimable: bool = False


def allocate_near(blocks, size, alignment, origin, max_distance=0x3FFFFE):
    candidates = []
    for index, block in enumerate(blocks):
        aligned = align_up(block.cursor, alignment)
        if aligned + size > block.end:
            continue
        if abs(aligned - origin) > max_distance:
            continue
        candidates.append((block.end - (aligned + size), index, aligned))

    if not candidates:
        return None

    _, index, aligned = min(candidates)
    blocks[index].cursor = aligned + size
    return aligned


def encode_thumb_bl(source, target):
    delta = target - (source + 4)
    if delta % 2 or not -0x400000 <= delta <= 0x3FFFFE:
        raise ValueError(
            f"Thumb BL target 0x{target:X} is out of range from 0x{source:X}"
        )
    upper = 0xF000 | ((delta >> 12) & 0x7FF)
    lower = 0xF800 | ((delta >> 1) & 0x7FF)
    return upper.to_bytes(2, "little") + lower.to_bytes(2, "little")


@dataclass
class RuntimePatchContext:
    rom: bytearray
    cmap: Charmap
    free_blocks: list
    alignment: int
    dry_run: bool
    handled_entry_ids: set[str] = field(default_factory=set)

    def encode_text(self, text):
        return encode_text(self.cmap, text)

    def allocate_near(self, size, origin, *, alignment=4, max_distance=0x3FFFFE):
        return allocate_near(
            self.free_blocks,
            size,
            max(alignment, self.alignment),
            origin,
            max_distance,
        )

    @staticmethod
    def encode_thumb_bl(source, target):
        return encode_thumb_bl(source, target)


def apply_language_patches(patches_root, target_lang, context):
    if not re.fullmatch(r"[a-z0-9-]+", target_lang):
        raise ValueError("--target-lang must contain only lowercase letters, digits, and hyphens")

    language_dir = patches_root / target_lang
    if not language_dir.is_dir():
        return []

    reports = []
    for index, patch_path in enumerate(sorted(language_dir.glob("*.py"))):
        if patch_path.name.startswith("_"):
            continue
        module_name = f"_unbound_runtime_patch_{target_lang.replace('-', '_')}_{index}"
        spec = importlib.util.spec_from_file_location(module_name, patch_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load runtime patch: {patch_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        apply_patch = getattr(module, "apply", None)
        if not callable(apply_patch):
            raise ValueError(f"Runtime patch has no apply(context) function: {patch_path}")

        result = apply_patch(context)
        if result is None:
            continue
        patch_reports = result if isinstance(result, list) else [result]
        for report in patch_reports:
            if not isinstance(report, dict):
                raise ValueError(f"Runtime patch returned an invalid report: {patch_path}")
            reports.append(
                {"file": patch_path.relative_to(patches_root.parent).as_posix(), **report}
            )

    return reports


def pointer_sources(entry):
    return entry.get("pointer_sources") or entry.get("pointer_addresses") or []


def current_pointer_matches(rom, pointer_offset, expected_pointer):
    if pointer_offset + 4 > len(rom):
        return False
    current = int.from_bytes(rom[pointer_offset : pointer_offset + 4], "little")
    return current == expected_pointer


def is_ewram_word(rom, offset):
    if offset < 0 or offset + 4 > len(rom):
        return False
    value = int.from_bytes(rom[offset: offset + 4], "little")
    return 0x02000000 <= value < 0x02040000


def plausible_pointer_source(rom, source):
    """Reject raw pointer-scan matches that would overwrite code or live data."""
    return (
            source % 4 == 0
            or (0x23E558 <= source < 0x23EAC8 and (source - 0x23E558) % 13 == 0)
            or (source >= 1 and rom[source - 1] == 0x9B)
            or (source >= 2 and rom[source - 2] == 0x0F and rom[source - 1] == 0x00)
            or (source >= 2 and rom[source - 2] == 0x85 and rom[source - 1] <= 0x0F)
            or (source >= 1 and rom[source - 1] == 0x67)
            or (source >= 6 and rom[source - 6] == 0x5C)
            or (source >= 10 and rom[source - 10] == 0x5C)
            or (source >= 1 and rom[source - 1] == 0x02 and 0x960000 <= source < 0x970000)
            or is_ewram_word(rom, source - 4)
    )


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
    if entry.get("no_relocation") or entry.get("category") == "pointer_texts":
        return False
    if not pointer_sources(entry):
        return False
    if policy == "changed":
        return True
    if policy == "oversized":
        return len(encoded) > int(entry.get("byte_length", 0))
    raise ValueError(f"Unknown relocation policy: {policy}")


def collect_relocation_candidates(
        rom,
        entries,
        cmap,
        pointer_policy,
        handled_entry_ids,
        min_address,
        allow_lossy_fit=False,
):
    candidates = []
    skipped = {}

    for entry in entries:
        entry_id = entry.get("id")
        if entry_id in handled_entry_ids:
            continue

        translated = translation_for_injection(entry)
        full_translation = strip_hma_quotes(entry.get("translated", ""))
        original = strip_hma_quotes(entry.get("original", ""))
        if not translated or full_translation == original:
            continue

        try:
            address = parse_address(entry["address"])
            max_size = int(entry["byte_length"])
            encoded = encode_text(
                cmap,
                translated,
                plain_script=entry.get("category") == "plain_scripts",
            )
        except Exception:
            continue

        if entry.get("category") == "ability_descriptions":
            compacted = compact_ability_description(
                encoded,
                encode_text(cmap, "."),
            )
            if compacted != encoded and not allow_lossy_fit:
                raise RuntimeError(
                    "Lossy ability-description compaction refused for "
                    f"{entry_id or '?'}: {len(encoded)} -> {len(compacted)} bytes. "
                    "Add a compact translated_fixed value or use --allow-lossy-fit."
                )
            encoded = compacted

        if address < min_address or max_size <= 0:
            continue
        if not should_relocate_pointer_entry(entry, encoded, pointer_policy):
            continue

        sources = tuple(parse_address(source) for source in pointer_sources(entry))
        expected_pointer = GBA_POINTER_BASE + address
        matching_sources = tuple(
            source
            for source in sources
            if current_pointer_matches(rom, source, expected_pointer)
        )
        plausible_sources = tuple(
            source
            for source in matching_sources
            if plausible_pointer_source(rom, source)
        )

        if matching_sources and len(plausible_sources) != len(matching_sources):
            skipped[entry_id] = "implausible"
            continue
        if not sources or len(matching_sources) != len(sources):
            skipped[entry_id] = "mismatch"
            continue

        candidates.append(
            RelocationCandidate(
                entry=entry,
                address=address,
                max_size=max_size,
                encoded=encoded,
                sources=plausible_sources,
            )
        )

    return candidates, skipped


def is_explicit_script_message_source(rom, source):
    """Require an opcode shape that unambiguously consumes a text pointer."""
    if (
        source >= 2
        and rom[source - 2 : source] == b"\x0F\x00"
        and source + 5 < len(rom)
        and rom[source + 4] == 0x09
        and 0x02 <= rom[source + 5] <= 0x06
    ):
        return True
    return (
        source >= 1
        and rom[source - 1] == 0x67
        and (source >> 20) == 0x1E
    )


def discover_raw_rom_pointers(rom, minimum_target, maximum_target):
    """Find every aligned or unaligned absolute ROM pointer in a target range."""
    references = []
    for high_byte in (b"\x08", b"\x09"):
        position = rom.find(high_byte, 3)
        while position >= 0:
            source = position - 3
            target = struct.unpack_from("<I", rom, source)[0] - GBA_POINTER_BASE
            if minimum_target <= target < maximum_target:
                references.append((target, source))
            position = rom.find(high_byte, position + 1)
    references.sort()
    return references


def build_reclaimed_script_text_blocks(
    rom,
    candidates,
    entries,
    allowed_owner_ids=None,
):
    """Return only old script literals with complete, explicit ownership."""
    allowed_owner_ids = (
        set(allowed_owner_ids) if allowed_owner_ids is not None else None
    )
    eligible = []
    for candidate in candidates:
        start = candidate.address
        end = start + candidate.max_size
        if (
            candidate.entry.get("category") == "scripts"
            and (
                allowed_owner_ids is None
                or candidate.entry.get("id") in allowed_owner_ids
            )
            and candidate.sources
            and any(
                allowed_start <= start < end <= allowed_end
                for allowed_start, allowed_end in RECLAIMABLE_SCRIPT_TEXT_RANGES
            )
            and all(
                is_explicit_script_message_source(rom, source)
                for source in candidate.sources
            )
        ):
            eligible.append(candidate)

    ordered = sorted(eligible, key=lambda candidate: candidate.address)
    overlapping = set()
    for index, candidate in enumerate(ordered):
        end = candidate.address + candidate.max_size
        if index and candidate.address < (
            ordered[index - 1].address + ordered[index - 1].max_size
        ):
            overlapping.update((id(candidate), id(ordered[index - 1])))
        if index + 1 < len(ordered) and ordered[index + 1].address < end:
            overlapping.update((id(candidate), id(ordered[index + 1])))

    raw_references = discover_raw_rom_pointers(
        rom,
        RECLAIMABLE_SCRIPT_TEXT_RANGES[0][0],
        RECLAIMABLE_SCRIPT_TEXT_RANGES[-1][1],
    )
    raw_targets = [target for target, _source in raw_references]
    reclaimed = []
    for candidate in ordered:
        if id(candidate) in overlapping:
            continue
        start = candidate.address
        end = start + candidate.max_size
        references = raw_references[
            bisect_left(raw_targets, start) : bisect_left(raw_targets, end)
        ]
        expected = sorted((start, source) for source in candidate.sources)
        if references != expected:
            continue
        candidate.reclaimable = True
        reclaimed.append(candidate)

    reclaim_ranges = merge_ranges(
        (candidate.address, candidate.address + candidate.max_size)
        for candidate in reclaimed
    )
    pointer_operands = merge_ranges(
        (parse_address(source), parse_address(source) + 4)
        for entry in entries
        for source in pointer_sources(entry)
    )
    reclaim_ranges = subtract_ranges(reclaim_ranges, pointer_operands)

    reclaimed_entry_ids = {candidate.entry.get("id") for candidate in reclaimed}
    other_entry_ranges = []
    for entry in entries:
        if entry.get("id") in reclaimed_entry_ids:
            continue
        try:
            start = parse_address(entry["address"])
            length = int(entry["byte_length"])
        except (KeyError, TypeError, ValueError):
            continue
        if length > 0 and start + length <= len(rom):
            other_entry_ranges.append((start, start + length))
    reclaim_ranges = subtract_ranges(
        reclaim_ranges,
        merge_ranges(other_entry_ranges),
    )

    owner_ids = {
        candidate.entry.get("id")
        for candidate in reclaimed
        if any(
            start < candidate.address + candidate.max_size
            and candidate.address < end
            for start, end in reclaim_ranges
        )
    }
    blocks = [
        FreeBlock(start, end, start, "reclaimed_script_text")
        for start, end in reclaim_ranges
    ]
    return blocks, owner_ids


def select_reclaimed_script_text_blocks(blocks, candidates, allowed_owner_ids):
    """Restrict prevalidated reclaimed ranges to relocated owner slots."""
    allowed_owner_ids = set(allowed_owner_ids)
    candidate_by_id = {
        candidate.entry.get("id"): candidate for candidate in candidates
    }
    allowed_ranges = merge_ranges(
        (
            candidate_by_id[entry_id].address,
            candidate_by_id[entry_id].address
            + candidate_by_id[entry_id].max_size,
        )
        for entry_id in allowed_owner_ids
        if entry_id in candidate_by_id
    )
    selected_ranges = []
    for block in blocks:
        for start, end in allowed_ranges:
            overlap_start = max(block.start, start)
            overlap_end = min(block.end, end)
            if overlap_start < overlap_end:
                selected_ranges.append((overlap_start, overlap_end))

    selected_ranges = merge_ranges(selected_ranges)
    selected_owner_ids = {
        entry_id
        for entry_id in allowed_owner_ids
        if entry_id in candidate_by_id
        and any(
            start
            < candidate_by_id[entry_id].address
            + candidate_by_id[entry_id].max_size
            and candidate_by_id[entry_id].address < end
            for start, end in selected_ranges
        )
    }
    return [
        FreeBlock(start, end, start, "reclaimed_script_text")
        for start, end in selected_ranges
    ], selected_owner_ids


def reference_proven_pointer_text_ids(source_rom, reference_rom, candidates):
    """Return heuristic entries independently repointed by a working ROM."""
    if len(reference_rom) != len(source_rom):
        raise ValueError(
            "Reference ROM size mismatch: "
            f"{len(reference_rom)} != {len(source_rom)}"
        )

    proven = set()
    for candidate in candidates:
        if candidate.entry.get("category") != "pointer_texts":
            continue
        expected = GBA_POINTER_BASE + candidate.address
        reference_targets = []
        for source in candidate.sources:
            if source + 4 > len(source_rom):
                reference_targets = []
                break
            original_pointer = struct.unpack_from("<I", source_rom, source)[0]
            reference_pointer = struct.unpack_from("<I", reference_rom, source)[0]
            target = reference_pointer - GBA_POINTER_BASE
            if (
                original_pointer != expected
                or reference_pointer == original_pointer
                or not 0 <= target < len(reference_rom)
            ):
                reference_targets = []
                break
            decoded = decode_pcs(reference_rom, target, 0x800)
            visible = strip_control_tokens(decoded.text).strip()
            if (
                not decoded.terminated
                or decoded.raw_count
                or decoded.byte_length < 3
                or len(visible) < 2
            ):
                reference_targets = []
                break
            reference_targets.append(target)
        if reference_targets and len(set(reference_targets)) == 1:
            proven.add(candidate.entry.get("id"))
    return proven


def table_proven_pointer_text_ids(rom, entries, candidates, minimum_records=8):
    """Prove pointer operands by membership in regular extracted tables."""
    known_sources = set()
    for entry in entries:
        try:
            expected = GBA_POINTER_BASE + parse_address(entry["address"])
        except (KeyError, TypeError, ValueError):
            continue
        for raw_source in pointer_sources(entry):
            try:
                source = parse_address(raw_source)
            except (TypeError, ValueError):
                continue
            if current_pointer_matches(rom, source, expected):
                known_sources.add(source)

    def belongs_to_regular_run(source):
        for stride in range(4, 49, 4):
            start = source
            while start - stride in known_sources:
                start -= stride
            end = source
            while end + stride in known_sources:
                end += stride
            if (end - start) // stride + 1 >= minimum_records:
                return True
        return False

    return {
        candidate.entry.get("id")
        for candidate in candidates
        if candidate.entry.get("category") == "pointer_texts"
        and candidate.sources
        and all(belongs_to_regular_run(source) for source in candidate.sources)
    }


def plan_relocations(
    blocks,
    candidates,
    alignment,
    reclaimed_blocks=None,
    reclaimed_categories=RECLAIMED_DESTINATION_CATEGORIES,
    reclaimed_entry_ids=None,
    reclaimed_owner_ids=None,
):
    """Allocate unique payloads, reserving vetted space for restricted texts."""
    reclaimed_blocks = reclaimed_blocks or []
    reclaimed_entry_ids = set(reclaimed_entry_ids or ())
    reclaimed_owner_ids = set(reclaimed_owner_ids or ()) if reclaimed_owner_ids is not None else None

    def can_use_reclaimed(candidate):
        return (
            candidate.entry.get("category") in reclaimed_categories
            or candidate.entry.get("id") in reclaimed_entry_ids
        )

    def priority(candidate, index):
        cat_reclaim = can_use_reclaimed(candidate)
        is_owner = (
            reclaimed_owner_ids is not None
            and candidate.entry.get("id") in reclaimed_owner_ids
        )
        length = len(candidate.encoded)
        if not cat_reclaim:
            return (0, index)
        elif is_owner:
            return (1, length, index)
        else:
            return (2, length, index)

    ordered_candidates = [
        candidate
        for _index, candidate in sorted(
            enumerate(candidates),
            key=lambda item: priority(item[1], item[0]),
        )
    ]
    plan = {}
    missing = []
    payload_plan = {}
    missing_payloads = set()
    for candidate in ordered_candidates:
        cached = payload_plan.get(candidate.encoded)
        entry_id = candidate.entry.get("id")
        candidate_can_use_reclaimed = can_use_reclaimed(candidate)
        if cached is not None and (
            cached[1] != "reclaimed_script_text"
            or candidate_can_use_reclaimed
        ):
            plan[entry_id] = (*cached, True)
            continue
        missing_key = (candidate.encoded, candidate_can_use_reclaimed)
        if missing_key in missing_payloads:
            missing.append(candidate)
            continue
        offset, block = None, None
        if candidate_can_use_reclaimed:
            offset, block = allocate_best_fit(
                reclaimed_blocks,
                len(candidate.encoded),
                alignment,
            )
        if offset is None:
            offset, block = allocate_with_block(blocks, len(candidate.encoded), alignment)
        if offset is None:
            missing_payloads.add(missing_key)
            missing.append(candidate)
            continue
        payload_plan[candidate.encoded] = (offset, block.kind)
        plan[entry_id] = (offset, block.kind, False)
    return plan, missing


def enforce_relocation_capacity(missing_candidates, fail_on_no_space):
    """Optionally require every relocation candidate to fit."""
    if not missing_candidates or not fail_on_no_space:
        return
    missing_bytes = sum(len(candidate.encoded) for candidate in missing_candidates)
    raise RuntimeError(
        "Transactional relocation preflight failed: "
        f"{len(missing_candidates)} entries / {missing_bytes} bytes do not fit"
    )


def injection_priority(entry):
    """Reserve limited relocation space for structured player-facing text."""
    category = entry.get("category", "")
    if category == "menu_trainer_card":
        return 0
    if category.startswith("menu_") or category in {
        "start_menu_labels",
        "setting_names",
        "mission_log",
        "mission_names",
        "map_names",
        "battle_messages",
        "trade_messages",
    }:
        return 1
    if category in {"scripts", "plain_scripts"}:
        return 3
    if category == "pointer_texts":
        return 4
    if category == "orphan_texts":
        return 5
    return 2


def prioritize_entries(entries):
    return [
        entry
        for _, entry in sorted(
            enumerate(entries), key=lambda item: (injection_priority(item[1]), item[0])
        )
    ]


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
        help="Minimum FF run used for relocated text. Default: 0x400",
    )
    parser.add_argument(
        "--min-address",
        default=hex(DEFAULT_MIN_ADDRESS),
        help="Ignore free space and text entries below this ROM offset. Default: 0x100",
    )
    parser.add_argument(
        "--alignment",
        type=int,
        default=DEFAULT_TEXT_ALIGNMENT,
        help="Alignment for relocated text addresses. Default: 1 (PCS text is byte-addressable)",
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
        "--fail-on-no-space",
        action="store_true",
        help=(
            "Abort when relocation space is exhausted. By default those "
            "translations stay unchanged and are reported as skipped."
        ),
    )
    parser.add_argument(
        "--reclaim-script-slots",
        action="store_true",
        help=(
            "Experimentally reuse fully owned high-bank script literals after "
            "vetted FF space. Reclaimed destinations accept explicit scripts "
            "and pointer_texts enabled by a separate proof option."
        ),
    )
    parser.add_argument(
        "--reclaim-reference-rom",
        help=(
            "Working translated ROM used to prove heuristic pointer_texts "
            "ownership before placing those entries in reclaimed script slots. "
            "Requires --reclaim-script-slots."
        ),
    )
    parser.add_argument(
        "--reclaim-pointer-tables",
        action="store_true",
        help=(
            "Experimentally allow pointer_texts whose every source belongs "
            "to a regular table of at least eight extracted pointer fields. "
            "Requires --reclaim-script-slots."
        ),
    )
    parser.add_argument(
        "--allow-lossy-fit",
        action="store_true",
        help=(
            "Allow legacy fixed-slot truncation and ability-description compaction. "
            "By default the injector aborts instead of silently removing translated text."
        ),
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
    if args.reclaim_reference_rom and not args.reclaim_script_slots:
        raise ValueError(
            "--reclaim-reference-rom requires --reclaim-script-slots"
        )
    if args.reclaim_pointer_tables and not args.reclaim_script_slots:
        raise ValueError(
            "--reclaim-pointer-tables requires --reclaim-script-slots"
        )

    rom = bytearray(rom_path.read_bytes())
    source_rom = bytes(rom)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    entries = prioritize_entries(list(iter_entries(data)))
    cmap = Charmap(target_lang=args.target_lang)
    free_blocks = build_free_blocks(
        rom,
        entries,
        min_free_run,
        min_address,
        VETTED_FREE_SPACE_RANGES,
    )
    patch_context = RuntimePatchContext(
        rom, cmap, free_blocks, args.alignment, args.dry_run
    )
    runtime_patches = apply_language_patches(
        Path(__file__).resolve().parent / "patches",
        args.target_lang.lower(),
        patch_context,
    )

    candidates, relocation_skips = collect_relocation_candidates(
        rom,
        entries,
        cmap,
        args.pointer_policy,
        patch_context.handled_entry_ids,
        min_address,
        args.allow_lossy_fit,
    )
    reclaimed_blocks = []
    reclaimed_owner_ids = set()
    vetted_reclaimed_owner_ids = set()
    reference_proven_ids = set()
    table_proven_ids = set()
    if args.reclaim_script_slots:
        reclamation_base_blocks = [
            FreeBlock(block.start, block.end, block.cursor, block.kind)
            for block in free_blocks
        ]
        vetted_blocks = [
            FreeBlock(block.start, block.end, block.cursor, block.kind)
            for block in reclamation_base_blocks
        ]
        all_reclaimed_blocks, all_reclaimed_owner_ids = (
            build_reclaimed_script_text_blocks(rom, candidates, entries)
        )
        preliminary_plan, _preliminary_missing = plan_relocations(
            vetted_blocks,
            candidates,
            args.alignment,
            reclaimed_owner_ids=all_reclaimed_owner_ids,
        )
        vetted_reclaimed_owner_ids = {
            entry_id
            for entry_id, (_offset, storage, _shared) in preliminary_plan.items()
            if storage == "vetted_ff" and entry_id in all_reclaimed_owner_ids
        }
        if args.reclaim_reference_rom:
            reference_rom = Path(args.reclaim_reference_rom).read_bytes()
            reference_proven_ids = reference_proven_pointer_text_ids(
                source_rom,
                reference_rom,
                candidates,
            )
        if args.reclaim_pointer_tables:
            table_proven_ids = table_proven_pointer_text_ids(
                source_rom,
                entries,
                candidates,
            )
        reclaimed_consumer_ids = reference_proven_ids | table_proven_ids
        active_owner_ids = set(vetted_reclaimed_owner_ids)
        seen_active = {frozenset(active_owner_ids)}
        while True:
            trial_free_blocks = [
                FreeBlock(block.start, block.end, block.cursor, block.kind)
                for block in reclamation_base_blocks
            ]
            trial_reclaimed_blocks, trial_owner_ids = (
                select_reclaimed_script_text_blocks(
                    all_reclaimed_blocks,
                    candidates,
                    active_owner_ids,
                )
            )
            trial_plan, trial_missing = plan_relocations(
                trial_free_blocks,
                candidates,
                args.alignment,
                trial_reclaimed_blocks,
                reclaimed_entry_ids=reclaimed_consumer_ids,
                reclaimed_owner_ids=all_reclaimed_owner_ids,
            )
            next_owner_ids = all_reclaimed_owner_ids.intersection(trial_plan)
            frozen_next = frozenset(next_owner_ids)
            if next_owner_ids == active_owner_ids or frozen_next in seen_active:
                curr_owners = next_owner_ids
                for _ in range(10):
                    final_reclaimed_blocks, final_owner_ids = (
                        select_reclaimed_script_text_blocks(
                            all_reclaimed_blocks,
                            candidates,
                            curr_owners,
                        )
                    )
                    final_free_blocks = [
                        FreeBlock(block.start, block.end, block.cursor, block.kind)
                        for block in reclamation_base_blocks
                    ]
                    final_plan, final_missing = plan_relocations(
                        final_free_blocks,
                        candidates,
                        args.alignment,
                        final_reclaimed_blocks,
                        reclaimed_entry_ids=reclaimed_consumer_ids,
                        reclaimed_owner_ids=all_reclaimed_owner_ids,
                    )
                    successful_owners = final_owner_ids.intersection(final_plan.keys())
                    if successful_owners == final_owner_ids:
                        break
                    curr_owners = successful_owners
                free_blocks = final_free_blocks
                reclaimed_blocks = final_reclaimed_blocks
                reclaimed_owner_ids = final_owner_ids
                relocation_plan = final_plan
                missing_candidates = final_missing
                break
            seen_active.add(frozen_next)
            active_owner_ids = next_owner_ids
    else:
        relocation_plan, missing_candidates = plan_relocations(
            free_blocks,
            candidates,
            args.alignment,
        )
    missing_reclaimed_owners = reclaimed_owner_ids - relocation_plan.keys()
    if missing_reclaimed_owners:
        sample = ", ".join(sorted(missing_reclaimed_owners)[:10])
        raise RuntimeError(
            "Reclaimed-slot ownership closure failed: "
            f"{len(missing_reclaimed_owners)} owners lack relocation plans "
            f"({sample})"
        )
    candidate_by_id = {
        candidate.entry.get("id"): candidate for candidate in candidates
    }
    used_reclaimed_ranges = [
        (block.start, block.cursor)
        for block in reclaimed_blocks
        if block.cursor > block.start
    ]
    used_reclaimed_owner_ids = {
        entry_id
        for entry_id in reclaimed_owner_ids
        if any(
            start < candidate_by_id[entry_id].address
            + candidate_by_id[entry_id].max_size
            and candidate_by_id[entry_id].address < end
            for start, end in used_reclaimed_ranges
        )
    }
    enforce_relocation_capacity(missing_candidates, args.fail_on_no_space)
    missing_candidates_by_id = {
        candidate.entry.get("id"): candidate for candidate in missing_candidates
    }
    candidates_by_id = {
        candidate.entry.get("id"): candidate for candidate in candidates
    }

    stats = {
        "input_entries": len(entries),
        "free_blocks": len(free_blocks) + len(reclaimed_blocks),
        "free_bytes": sum(
            block.end - block.start
            for block in (*free_blocks, *reclaimed_blocks)
        ),
        "vetted_free_blocks": len(free_blocks),
        "vetted_free_bytes": sum(block.end - block.start for block in free_blocks),
        "reclaimed_text_blocks": len(reclaimed_blocks),
        "reclaimed_text_bytes": sum(
            block.end - block.start for block in reclaimed_blocks
        ),
        "reclaimable_text_owners": len(reclaimed_owner_ids),
        "vetted_reclaim_seed_owners": len(vetted_reclaimed_owner_ids),
        "used_reclaimed_text_owners": len(used_reclaimed_owner_ids),
        "reference_proven_pointer_texts": len(reference_proven_ids),
        "table_proven_pointer_texts": len(table_proven_ids),
        "relocated": 0,
        "deduplicated_relocations": 0,
        "relocated_bytes": 0,
        "pointer_writes": 0,
        "in_place": 0,
        "unchanged": 0,
        "skipped_empty": 0,
        "skipped_runtime_patch": 0,
        "skipped_unsafe": 0,
        "skipped_duplicate_fixed": 0,
        "skipped_pointer_mismatch": 0,
        "skipped_implausible_pointer": 0,
        "skipped_no_space": 0,
        "skipped_no_space_bytes": 0,
        "skipped_no_space_by_category": {},
        "skipped_bounds": 0,
        "encode_errors": 0,
        "fixed_overrides_used": 0,
        "fixed_truncated": 0,
        "fixed_truncated_bytes": 0,
        "fixed_truncated_by_category": {},
        "fixed_truncated_bytes_by_category": {},
        "no_relocation_in_place": 0,
        "no_relocation_truncated": 0,
        "no_relocation_truncated_by_category": {},
        "ability_descriptions_compacted": 0,
        "ability_description_bytes_removed": 0,
        "runtime_patches": len(runtime_patches),
    }

    relocation_map = []
    truncation_samples = []
    mismatch_samples = []
    implausible_samples = []
    no_space_samples = []
    missing_fixed_slots = []
    seen_fixed_slots = set()

    for entry in entries:
        if entry.get("id") in patch_context.handled_entry_ids:
            stats["skipped_runtime_patch"] += 1
            continue

        raw_trans = entry.get("translated")
        if raw_trans is None:
            stats["skipped_empty"] += 1
            continue

        translated = translation_for_injection(entry)
        full_translation = strip_hma_quotes(raw_trans)
        original = strip_hma_quotes(entry.get("original", ""))
        if full_translation == original:
            stats["unchanged"] += 1
            continue
        if entry.get("translated_fixed"):
            stats["fixed_overrides_used"] += 1

        try:
            address = parse_address(entry["address"])
            max_size = int(entry["byte_length"])
            encoded = encode_text(
                cmap,
                translated,
                plain_script=entry.get("category") == "plain_scripts",
            )
            if entry.get("category") == "ability_descriptions":
                encoded_size = len(encoded)
                compacted = compact_ability_description(
                    encoded,
                    encode_text(cmap, "."),
                )
                if compacted != encoded:
                    if not args.allow_lossy_fit:
                        raise RuntimeError(
                            "Lossy ability-description compaction refused for "
                            f"{entry.get('id', '?')}: "
                            f"{len(encoded)} -> {len(compacted)} bytes. "
                            "Add a compact translated_fixed value or use "
                            "--allow-lossy-fit."
                        )
                    stats["ability_descriptions_compacted"] += 1
                    stats["ability_description_bytes_removed"] += (
                        encoded_size - len(compacted)
                    )
                    encoded = compacted
        except RuntimeError:
            raise
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
            entry_id = entry.get("id")
            skip_reason = relocation_skips.get(entry_id)
            if skip_reason == "implausible":
                stats["skipped_implausible_pointer"] += 1
                if len(implausible_samples) < 20:
                    implausible_samples.append(entry_id or "?")
                continue
            if skip_reason == "mismatch":
                stats["skipped_pointer_mismatch"] += 1
                if len(mismatch_samples) < 20:
                    mismatch_samples.append(entry_id or "?")
                continue
            candidate = candidates_by_id.get(entry_id)
            if candidate is None:
                raise RuntimeError(
                    f"Missing transactional relocation plan for {entry_id or '?'}"
                )
            if entry_id not in relocation_plan:
                missing_candidate = missing_candidates_by_id.get(entry_id)
                if missing_candidate is None:
                    raise RuntimeError(
                        f"Missing transactional relocation plan for {entry_id or '?'}"
                    )
                category = entry.get("category", "unknown")
                stats["skipped_no_space"] += 1
                stats["skipped_no_space_bytes"] += len(missing_candidate.encoded)
                stats["skipped_no_space_by_category"][category] = (
                    stats["skipped_no_space_by_category"].get(category, 0) + 1
                )
                if len(no_space_samples) < 20:
                    no_space_samples.append(entry_id or "?")
                continue

            relocated_offset, storage_kind, shared_payload = relocation_plan[entry_id]
            sources = list(candidate.sources)
            new_pointer = GBA_POINTER_BASE + relocated_offset
            if not args.dry_run:
                rom[relocated_offset : relocated_offset + len(encoded)] = encoded
                for source in sources:
                    rom[source : source + 4] = new_pointer.to_bytes(4, "little")

            stats["relocated"] += 1
            stats["deduplicated_relocations"] += int(shared_payload)
            stats["relocated_bytes"] += len(encoded)
            stats["pointer_writes"] += len(sources)
            relocation_map.append(
                {
                    "id": entry_id,
                    "category": entry.get("category"),
                    "old_offset": f"0x{address:X}",
                    "new_offset": f"0x{relocated_offset:X}",
                    "new_pointer": f"0x{new_pointer:X}",
                    "byte_length": len(encoded),
                    "pointer_sources": [f"0x{source:X}" for source in sources],
                    "storage": storage_kind,
                    "shared_payload": shared_payload,
                    "old_slot_reclaimed": entry_id in used_reclaimed_owner_ids,
                    "reference_proven": entry_id in reference_proven_ids,
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
            if not args.allow_lossy_fit:
                if args.fail_on_no_space and entry.get("category") != "pointer_texts":
                    raise RuntimeError(
                        "Lossy fixed-slot truncation refused for "
                        f"{entry.get('id', '?')}: {len(encoded)} -> {max_size} bytes. "
                        "Add a compact translated_fixed value or omit "
                        "--fail-on-no-space to leave it unchanged."
                    )
                entry_id = entry.get("id")
                category = entry.get("category", "unknown")
                stats["skipped_no_space"] += 1
                stats["skipped_no_space_bytes"] += len(encoded)
                stats["skipped_no_space_by_category"][category] = (
                    stats["skipped_no_space_by_category"].get(category, 0) + 1
                )
                if len(no_space_samples) < 20:
                    no_space_samples.append(entry_id or "?")
                missing_fixed_slots.append(
                    {
                        "id": entry_id,
                        "category": entry.get("category"),
                        "offset": f"0x{address:X}",
                        "encoded_bytes": len(encoded),
                        "slot_bytes": max_size,
                        "no_relocation": bool(entry.get("no_relocation")),
                    }
                )
                continue
            stats["fixed_truncated"] += 1
            overflow = len(encoded) - max_size
            category = entry.get("category", "unknown")
            stats["fixed_truncated_bytes"] += overflow
            stats["fixed_truncated_by_category"][category] = (
                stats["fixed_truncated_by_category"].get(category, 0) + 1
            )
            stats["fixed_truncated_bytes_by_category"][category] = (
                stats["fixed_truncated_bytes_by_category"].get(category, 0)
                + overflow
            )
            if entry.get("no_relocation"):
                stats["no_relocation_truncated"] += 1
                stats["no_relocation_truncated_by_category"][category] = (
                    stats["no_relocation_truncated_by_category"].get(category, 0)
                    + 1
                )
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

    used_vetted_bytes = sum(block.cursor - block.start for block in free_blocks)
    used_reclaimed_text_bytes = sum(
        block.cursor - block.start for block in reclaimed_blocks
    )
    used_free_bytes = used_vetted_bytes + used_reclaimed_text_bytes
    remaining_free_bytes = sum(
        block.end - block.cursor for block in (*free_blocks, *reclaimed_blocks)
    )

    if args.map_output:
        report_path = Path(args.map_output)
        report = {
            "rom": str(rom_path),
            "json": str(json_path),
            "output": str(output_path),
            "stats": stats,
            "used_free_bytes": used_free_bytes,
            "remaining_free_bytes": remaining_free_bytes,
            "used_vetted_bytes": used_vetted_bytes,
            "used_reclaimed_text_bytes": used_reclaimed_text_bytes,
            "reclaimable_slot_owners": sorted(reclaimed_owner_ids),
            "reclaimed_slot_owners": sorted(used_reclaimed_owner_ids),
            "reference_proven_pointer_text_ids": sorted(reference_proven_ids),
            "table_proven_pointer_text_ids": sorted(table_proven_ids),
            "relocations": relocation_map,
            "missing_relocations": [
                {
                    "id": candidate.entry.get("id"),
                    "category": candidate.entry.get("category"),
                    "old_offset": f"0x{candidate.address:X}",
                    "byte_length": len(candidate.encoded),
                    "pointer_sources": [
                        f"0x{source:X}" for source in candidate.sources
                    ],
                }
                for candidate in missing_candidates
            ],
            "missing_fixed_slots": missing_fixed_slots,
            "runtime_patches": runtime_patches,
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run:
        output_path.write_bytes(rom)

    print()
    print("===================================")
    print(f"Input entries          : {stats['input_entries']}")
    print(f"Free blocks            : {stats['free_blocks']}")
    print(f"Free bytes             : {stats['free_bytes']}")
    print(f"Vetted FF bytes        : {stats['vetted_free_bytes']}")
    print(f"Reclaimed text bytes   : {stats['reclaimed_text_bytes']}")
    print(f"Reclaimable owners     : {stats['reclaimable_text_owners']}")
    print(f"Reclaimed slot owners  : {stats['used_reclaimed_text_owners']}")
    print(f"Reference-proven texts : {stats['reference_proven_pointer_texts']}")
    print(f"Table-proven texts     : {stats['table_proven_pointer_texts']}")
    print(f"Used free bytes        : {used_free_bytes}")
    print(f"Used reclaimed bytes   : {used_reclaimed_text_bytes}")
    print(f"Remaining free bytes   : {remaining_free_bytes}")
    print(f"Relocated              : {stats['relocated']}")
    print(f"Deduplicated relocations: {stats['deduplicated_relocations']}")
    print(f"Relocated bytes        : {stats['relocated_bytes']}")
    print(f"Pointer writes         : {stats['pointer_writes']}")
    print(f"In-place patched       : {stats['in_place']}")
    print(f"Unchanged              : {stats['unchanged']}")
    print(f"Skipped empty          : {stats['skipped_empty']}")
    print(f"Handled by patch       : {stats['skipped_runtime_patch']}")
    print(f"Skipped unsafe         : {stats['skipped_unsafe']}")
    print(f"Skipped duplicate fixed: {stats['skipped_duplicate_fixed']}")
    print(f"Pointer mismatches     : {stats['skipped_pointer_mismatch']}")
    print(f"Implausible pointers   : {stats['skipped_implausible_pointer']}")
    print(f"Skipped no space       : {stats['skipped_no_space']}")
    print(f"No-space bytes         : {stats['skipped_no_space_bytes']}")
    if stats["skipped_no_space_by_category"]:
        print("No-space categories    :")
        for category, count in sorted(
                stats["skipped_no_space_by_category"].items(),
                key=lambda item: (-item[1], item[0]),
        ):
            print(f"  {category}: {count}")
    print(f"Skipped out-of-ROM     : {stats['skipped_bounds']}")
    print(f"Encode errors          : {stats['encode_errors']}")
    print(f"Fixed overrides used   : {stats['fixed_overrides_used']}")
    print(f"Fixed truncated        : {stats['fixed_truncated']}")
    print(f"Fixed bytes removed    : {stats['fixed_truncated_bytes']}")
    if stats["fixed_truncated_by_category"]:
        print("Fixed trunc categories :")
        for category, count in sorted(
                stats["fixed_truncated_by_category"].items(),
                key=lambda item: (-item[1], item[0]),
        ):
            byte_count = stats["fixed_truncated_bytes_by_category"][category]
            print(f"  {category}: {count} ({byte_count} bytes)")
    print(f"No-reloc in-place      : {stats['no_relocation_in_place']}")
    print(f"No-reloc truncated     : {stats['no_relocation_truncated']}")
    print(f"Ability desc compacted : {stats['ability_descriptions_compacted']}")
    print(f"Ability bytes removed  : {stats['ability_description_bytes_removed']}")
    print(f"Runtime patches        : {stats['runtime_patches']}")
    if truncation_samples:
        print("Fixed truncation sample:")
        for sample in truncation_samples:
            print(f"  {sample}")
    if mismatch_samples:
        print("Pointer mismatch sample:")
        for sample in mismatch_samples:
            print(f"  {sample}")
    if implausible_samples:
        print("Implausible pointer sample:")
        for sample in implausible_samples:
            print(f"  {sample}")
    if no_space_samples:
        print("No-space skip sample:")
        for sample in no_space_samples:
            print(f"  {sample}")
    print(f"Output ROM             : {'(dry run)' if args.dry_run else output_path}")
    print("===================================")


if __name__ == "__main__":
    main()
