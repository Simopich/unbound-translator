"""Render complete Italian Mission Log tab titles without the English suffix."""

from lib.pcs_text import decode_pcs

GBA_POINTER_BASE = 0x08000000
SUFFIX_POINTER_OFFSET = 0x1EBE988
SUFFIX_ENTRY_ID = "tbl_mission_log_00000_1F56040"
ACCEPTED_SUFFIXES = {" Missions", "Missions", "Missioni"}


def apply(context):
    pointer = int.from_bytes(
        context.rom[SUFFIX_POINTER_OFFSET: SUFFIX_POINTER_OFFSET + 4], "little"
    )
    target = pointer - GBA_POINTER_BASE
    if not 0 <= target < len(context.rom):
        raise ValueError(
            f"Italian Mission Log suffix pointer is invalid: 0x{pointer:08X}"
        )

    current = decode_pcs(context.rom, target, 32).text
    if current and current not in ACCEPTED_SUFFIXES:
        raise ValueError(
            f"Italian Mission Log suffix mismatch at 0x{target:X}: {current!r}"
        )

    writes = int(bool(current))
    if writes and not context.dry_run:
        context.rom[target] = 0xFF
    context.handled_entry_ids.add(SUFFIX_ENTRY_ID)
    return {
        "kind": "mission_log_tab_titles",
        "writes": writes,
        "pointer_offset": f"0x{SUFFIX_POINTER_OFFSET:X}",
        "target_offset": f"0x{target:X}",
    }
