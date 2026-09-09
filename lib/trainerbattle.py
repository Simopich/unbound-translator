"""Pokemon FireRed/CFRU trainerbattle command operand helpers."""

from __future__ import annotations


# Text-pointer offsets relative to script opcode 0x5C. Types 10-12 and 16 are
# CFRU multi/partner forms; other types retain FireRed's operand layouts.
TRAINERBATTLE_TEXT_OPERAND_OFFSETS = {
    0: (6, 10),
    1: (6, 10),
    2: (6, 10),
    3: (6,),
    4: (6, 10, 14),
    5: (6, 10),
    6: (6, 10, 14),
    7: (6, 10, 14),
    8: (6, 10, 14),
    9: (6, 10),
    10: (12, 16),
    11: (10, 14, 18, 22, 26, 30),
    12: (10,),
    13: (6, 10),
    14: (6, 10, 14),
    15: (6,),
    16: (10, 14, 18, 22, 26, 30),
}

_TEXT_OPERAND_OFFSETS = tuple(
    sorted(
        {
            offset
            for offsets in TRAINERBATTLE_TEXT_OPERAND_OFFSETS.values()
            for offset in offsets
        }
    )
)


def is_trainerbattle_text_pointer_source(
    rom: bytes | bytearray,
    source: int,
) -> bool:
    """Return whether ``source`` is an exact text operand of opcode 0x5C."""
    if source < 0 or source + 4 > len(rom):
        return False

    for operand_offset in _TEXT_OPERAND_OFFSETS:
        command = source - operand_offset
        if command < 0 or command + 1 >= len(rom) or rom[command] != 0x5C:
            continue
        battle_type = rom[command + 1]
        if operand_offset in TRAINERBATTLE_TEXT_OPERAND_OFFSETS.get(battle_type, ()):
            return True
    return False
