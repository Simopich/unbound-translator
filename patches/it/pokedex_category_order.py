"""Render Italian Pokédex categories as "Pokémon <category>"."""

SUFFIX_ENTRY_ID = "scr_415F8F"
PATCHES = (
    (0x10588C, (b"\x02\xAA",), b"\x0C\x4A"),
    (0x105896, (b"\x02\xA9",), b"\x0A\x49"),
    (0x1058A4, (b"\x06\x4A",), b"\x02\xAA"),
    (
        0x415F8F,
        (
            b"\x00\xCA\xE3\xDF\x1B\xE1\xE3\xE2\xFF",
            b"\xCA\xE3\xDF\x1B\xE1\xE3\xE2\xFF\xFF",
        ),
        b"\xCA\xE3\xDF\x1B\xE1\xE3\xE2\x00\xFF",
    ),
)


def apply(context):
    applied = 0
    for offset, old_forms, replacement in PATCHES:
        current = bytes(context.rom[offset: offset + len(replacement)])
        if current == replacement:
            continue
        if current not in old_forms:
            expected = " | ".join(value.hex(" ") for value in old_forms)
            raise ValueError(
                f"Italian Pokédex category-order mismatch at 0x{offset:X}: "
                f"{current.hex(' ')}; expected {expected}"
            )
        if not context.dry_run:
            context.rom[offset: offset + len(replacement)] = replacement
        applied += 1

    context.handled_entry_ids.add(SUFFIX_ENTRY_ID)
    return {
        "kind": "pokedex_category_order",
        "writes": applied,
        "offsets": [f"0x{offset:X}" for offset, _old, _new in PATCHES],
    }
