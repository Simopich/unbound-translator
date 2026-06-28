#!/usr/bin/env python3

"""Extract Pokemon Unbound text without Meowth/HMA dependencies."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import re
from pathlib import Path

from lib.pcs_text import (
    Charmap,
    DecodeResult,
    decode_pcs,
    hma_quote,
    strip_control_tokens,
)


GBA_POINTER_BASE = 0x08000000
DEFAULT_MIN_POINTER_TARGET = 0x100
DEFAULT_MAX_TEXT_LENGTH = 0x800
# Full-screen opening narration text. These are still script pointers, but the
# renderer uses plain line breaks instead of dialogue-box continuation controls.
PLAIN_SCRIPT_TEXT_RANGES = (
    (0x1F11016, 0x1F110D5),
    (0x1F117E3, 0x1F1187C),
    (0x1F11CFD, 0x1F11D10),
)
PLAIN_SCRIPT_TEXT_ADDRESSES = {
    0x1C5A04,
    0x1C5A6B,
    0x8CE9CB,
    0x8CEA72,
    0x1F0F5A6,
    0x1F0F64D,
    0x1F0F6FA,
    0x1F0F79C,
}

# Some engine/common-routine text pointers are not safe to redirect even when
# the text is pointer-based. Keep these strings in their original slots.
NO_RELOCATION_POINTER_SOURCE_RANGES = (
    (0x1A6500, 0x1A6D00),  # common item/PC/field routine messages
    (0x1A8C00, 0x1A9300),  # common field/heal/item routine messages
    (0x9A4800, 0x9A4930),  # receive-item variants
    (0x879000, 0x879064),  # key-item structs, including Braille Converter
    (0x3E0718, 0x3E0724),  # Cube sector labels
    (0x452CF0, 0x452D08),  # Cube pocket labels
    (0xA6D180, 0xA6D1A8),  # Cube V3 menu labels
)


@dataclass(frozen=True)
class FixedTable:
    category: str
    table_name: str
    start: int
    count: int
    slot_size: int
    stride: int | None = None
    pointer_name: bool = False
    substring_name: bool = False


@dataclass(frozen=True)
class SequentialTable:
    category: str
    table_name: str
    start: int
    count: int


@dataclass(frozen=True)
class PointerTable:
    category: str
    table_name: str
    start: int
    count: int


@dataclass(frozen=True)
class ManualTextRange:
    category: str
    table_name: str
    start: int
    end: int


FIXED_TABLES = [
    FixedTable("pokemon_names", "data.pokemon.names", 0x166A98C, 1294, 11),
    FixedTable("type_names", "data.pokemon.type.names", 0xA4EAD4, 24, 7),
    FixedTable("item_names", "data.items.stats", 0x876200, 729, 13, 44, pointer_name=True),
    FixedTable("move_names", "data.pokemon.moves.names", 0xA40A10, 923, 13),
    FixedTable("ability_names", "data.abilities.names", 0xA36398, 293, 17),
    FixedTable(
        "trainer_classes",
        "data.trainers.classes.names",
        0x23E558,
        107,
        13,
        substring_name=True,
    ),
]

SEQUENTIAL_TABLES = [
    SequentialTable("nature_names", "data.pokemon.natures.names", 0x463DBC, 25),
    SequentialTable("habitat_names", "data.pokedex.habitat.names", 0x415DF7, 9),
]

POINTER_TABLES = [
    # Unbound has 293 ability names, but the ability-description pointer table
    # only contains valid text pointers through index 254. The following words
    # point into non-text data and decode as control-heavy garbage.
    PointerTable("ability_descriptions", "data.abilities.descriptions", 0x96DE04, 255),
    PointerTable("move_descriptions", "data.pokemon.moves.descriptions", 0x99F194, 922),
    PointerTable("map_names", "data.maps.names", 0x3F1CAC, 109),
]

DEFAULT_MENU_AUDIT_STRINGS = [
    "SAVING.",
    "DON'T TURN OFF THE POWER",
    "YES",
    "NO",
    "BAG",
    "POKéMON",
    "SAVE",
    "OPTION",
    "PLAYER",
    "TIME",
    "MONEY",
    "BADGES",
    "A Button",
    "B Button",
    "Cube V3",
    "Save Game",
    "Game Settings",
    "L-Button Mode",
    "R-Button Mode",
    "Puzzle Difficulty",
    "General Options",
    "Player",
    "Badges",
    "Time",
    "Old Save",
    "Items",
    "Key Items",
    "Shut Cube",
    "Someone's PC",
    "Item Storage",
    "Mailbox",
    "Deposit Item",
    "Withdraw Item",
    "Fight",
    "Bag",
    "Pokémon",
    "Run",
    "Text Speed",
    "Battle Scene",
    "Battle Style",
    "Sound",
    "Button Mode",
    "Frame",
]

MANUAL_TEXT_TABLES = {
    "menu_common": (
        "data.text.menu.common",
        [
            0x41617A,
            0x416181,
            0x416188,
            0x416190,
            0x4161A0,
            0x4161A4,
            0x4161A9,
            0x4161B2,
            0x4161BC,
            0x4161C1,
            0x4161C8,
            0x4161D4,
            0x4161D9,
            0x4161DE,
            0x4161E3,
            0x4161E9,
            0x4161EF,
            0x4161F4,
            0x4161F9,
            0x41623D,
            0x416244,
            0x416262,
            0x417938,
            0x41793C,
        ],
    ),
    "menu_cube": (
        "data.menus.text.cube",
        [
            0x4162CD,
            0x4162D3,
            0x4162DE,
            0x4162E8,
            0x4162F5,
            0xA4E4D7,
            0xA4E4E4,
            0xA4E4EC,
            0xA4E4F6,
            0xA4E504,
            0xA4E50D,
        ],
    ),
    "menu_game_settings": (
        "data.menus.text.gameSettings",
        [
            0x1F4DB51,
            0x1F4DB5F,
            0x1F4DB6A,
            0x1F4DB7A,
            0x1F4DB88,
            0x1F4DB9D,
            0x1F4DBA5,
            0x1F4DBAB,
            0x1F4DBB0,
            0x1F4DBB9,
            0x1F4DBC4,
            0x1F4DBD0,
            0x1F4DBDC,
            0x1F4DBE7,
            0x1F4DBF2,
            0x1F4DBFE,
            0x1F4DC09,
            0x1F4DC1B,
            0x1F4DC2A,
            0x1F4DC32,
            0x1F4DC3A,
            0x1F4DC44,
            0x1F4DC4F,
            0x1F4DC57,
            0x1F4DC62,
            0x1F4DC74,
            0x1F4DC81,
            0x1F4DC8A,
            0x1F4DC9D,
            0x1F4DCB2,
            0x1F4DCBF,
            0x1F4DCCD,
        ],
    ),
    "menu_save": (
        "data.menus.text.save",
        [
            0x1F11DA3,
            0x1F11DAC,
            0x1F11DB8,
            0x41B60E,
            0x41B69E,
            0x41B6B9,
            0x41B6D5,
            0x41B6DC,
            0x41B6E3,
            0x41B6EC,
        ],
    ),
    "menu_saving_messages": (
        "data.menus.text.savingMessages",
        [
            0x419F54,
            0x41CC42,
            0x41CC64,
            0x41CC7B,
        ],
    ),
    "menu_link_controls": (
        "data.menus.text.linkControls",
        [
            0x1BC4AC,
            0x1BC4CE,
            0x1BC50D,
            0x1BC54C,
            0x418CD9,
            0x418E09,
            0x418E77,
            0x418E8D,
            0x418E95,
            0x418E9E,
            0x418EA7,
            0x418EB0,
            0x418EB5,
            0x418EBC,
        ],
    ),
    "menu_battle": (
        "data.menus.text.battle",
        [
            0x3FE725,
            0x3FE747,
            0xA4C7B7,
            0xA4C7DA,
            0xA4C807,
            0xA4C82B,
        ],
    ),
    "menu_trainer_card": (
        "data.menus.text.trainerCard",
        [
            0x419CDA,
            0x419CE1,
            0x419CE7,
            0x419CEF,
            0x419CFD,
            0x419D0A,
            0x419D1A,
            0x419D2F,
            0x419D3C,
            0x419D4F,
            0x419D57,
            0x419D66,
            0x419D7D,
        ],
    ),
    "menu_multiplayer": (
        "data.menus.text.multiplayer",
        [
            0x4573F4,
            0x457402,
            0x457410,
            0x45741E,
        ],
    ),
    "menu_standalone_labels": (
        "data.menus.text.standaloneLabels",
        [
            0x834ACC,
        ],
    ),
    "menu_options": (
        "data.menus.text.options",
        [
            0x419DCC,
            0x419DD3,
            0x419DDE,
            0x419DEB,
            0x419DF8,
            0x419DFE,
            0x419E0A,
            0x419E17,
            0x419E1C,
            0x419E20,
            0x419E25,
            0x419E28,
            0x419E2C,
            0x419E32,
            0x419E36,
            0x419E3B,
            0x419E46,
            0x419E4B,
            0x419E4F,
            0x419E52,
            0x419C5A,
        ],
    ),
    "menu_pc": (
        "data.menus.text.pc",
        [
            0x418208,
            0x41821B,
            0x418233,
            0x418248,
            0x41825C,
            0x41826C,
            0x41827F,
            0x418295,
            0x4182A7,
            0x4182B8,
            0x4182CE,
            0x4182DF,
            0x4182EC,
            0x4182FF,
            0x418319,
            0x41832C,
            0x418346,
            0x41835A,
            0x418379,
            0x418392,
            0x4183A0,
            0x4183BA,
            0x4183C5,
            0x41825C,
            0x4183DD,
            0x4183F0,
            0x417B9F,
            0x417BAC,
            0x417BB6,
            0x417BBE,
            0x417BCB,
            0x417BD3,
            0x1F21C2A,
            0x1F21C0F,
            0x418433,
            0x418443,
            0x418452,
        ],
    ),
    "menu_pcoptions": ("data.menus.text.pcoptions", [0x4176F1, 0x4176FE, 0x4176E2]),
    "menu_pokemon": (
        "data.menus.text.pokemon",
        [
            0x4171DF,
            0x417396,
            0x4173B0,
            0x4171F1,
            0x417200,
            0x417215,
            0x41722B,
            0x417258,
            0x417270,
            0x417281,
            0x417299,
            0x4173CC,
            0x4173E4,
            0x417301,
            0x417313,
            0x4173CC,
            0xA4E15D,
            0x4173CC,
            0x417337,
            0x41734D,
            0x41735B,
            0x41736B,
            0x417242,
            0x4172AE,
            0x4172C2,
            0x4172D5,
            0x41737F,
        ],
    ),
    "menu_item_storage": ("data.text.menu.itemStorage", [0x417713, 0x417706, 0x4161C1]),
    "menu_pause": (
        "data.text.menu.pause",
        [
            0x41627D,
            0x416285,
            0x415A66,
            0x800FC0,
            0x41628E,
            0x416291,
            0x416296,
            0x41629D,
            0x4162A2,
            0x41628E,
        ],
    ),
    "menu_pokemon_options": (
        "data.text.menu.pokemon.options",
        [
            0x416994,
            0x41698D,
            0x4161C1,
            0x4161D4,
            0x4161B2,
            0x4161DE,
            0x4161D9,
            0x4169B2,
            0x4169B7,
            0x4161C1,
            0x4169BC,
            0x416994,
            0x41698D,
            0x4161C1,
            0x4161E3,
            0x41B6F4,
            0x4169BC,
            0x4169BC,
            0xA4E1F1,
        ],
    ),
    "trade_messages": (
        "data.text.trade.messages",
        [0x41718C, 0x4171CC, 0x4170BC, 0x4170BC, 0x4170FC, 0x4170E0, 0x417130, 0x417164, 0x417164],
    ),
}


MANUAL_TEXT_RANGES = [
    ManualTextRange("menu_game_settings", "data.menus.text.gameSettings.range", 0x1F4DA6C, 0x1F4E26F),
    ManualTextRange("menu_item_storage", "data.text.menu.itemStorage.range", 0x417706, 0x4178C0),
    ManualTextRange("menu_list_labels", "data.menus.text.lists", 0x4178D0, 0x4181E4),
    ManualTextRange("menu_pc", "data.menus.text.pc.range", 0x418468, 0x418740),
    ManualTextRange("menu_cube_system", "data.menus.text.cube.system", 0xA4E047, 0xA4E1C9),
    ManualTextRange("menu_link_controls", "data.menus.text.linkControls.range", 0x41DF4C, 0x41E147),
    ManualTextRange("menu_link_controls", "data.menus.text.linkControls.cancel", 0x41E76B, 0x41E7A3),
    ManualTextRange("menu_saving_messages", "data.menus.text.savingMessages.card", 0x41ED50, 0x41ED9C),
    ManualTextRange("menu_mining", "data.menus.text.mining", 0x1F8225D, 0x1F82358),
    ManualTextRange("credits_text", "data.text.credits", 0x41D3BE, 0x41D45A),
]

POST_POINTER_MANUAL_TEXT_RANGES = [
    ManualTextRange("menu_trainer_card", "data.menus.text.trainerCard.profile", 0x1F81E44, 0x1F81EE5),
    ManualTextRange("item_descriptions", "data.items.descriptions", 0x3D4F00, 0x3DB020),
    ManualTextRange("item_descriptions", "data.items.descriptions.unboundKeyItems", 0xEB1F16, 0xEB20E8),
    ManualTextRange("battle_messages", "data.battle.text.messages", 0x3FB500, 0x3FE780),
    ManualTextRange("battle_messages", "data.battle.text.wildEncounter", 0x8BD140, 0x8BD155),
    ManualTextRange("battle_messages", "data.battle.text.wildEncounter.unbound", 0xA4C515, 0xA4C5DD),
    ManualTextRange("battle_messages", "data.battle.text.safariEncounter", 0x1F68219, 0x1F6826A),
    ManualTextRange("menu_battle", "data.menus.text.battle.partyOptions", 0x41697E, 0x4169D8),
    ManualTextRange("menu_pokemon_summary", "data.menus.text.pokemonSummary", 0x419782, 0x419C51),
    ManualTextRange("mission_log", "data.menus.text.missionLog.notifications", 0x1FB003F, 0x1FB00A8),
    ManualTextRange("mission_descriptions", "data.missions.descriptions.amIBlind", 0x1F1F8AB, 0x1F1F8F0),
]


def find_pointer_sources(rom: bytes, target: int) -> list[int]:
    pointer = (GBA_POINTER_BASE + target).to_bytes(4, "little")
    sources = []
    cursor = 0
    while True:
        source = rom.find(pointer, cursor)
        if source == -1:
            return sources
        sources.append(source)
        cursor = source + 1


def gba_pointer_to_offset(value: int, rom_size: int) -> int | None:
    if GBA_POINTER_BASE <= value < GBA_POINTER_BASE + rom_size:
        return value - GBA_POINTER_BASE
    return None


def format_offset(offset: int) -> str:
    return f"0x{offset:X}"


def pointer_at(rom: bytes, offset: int) -> int | None:
    if offset + 4 > len(rom):
        return None
    return gba_pointer_to_offset(int.from_bytes(rom[offset : offset + 4], "little"), len(rom))


def visible_text(text: str) -> str:
    return strip_control_tokens(text).replace("\n", " ").strip()


def looks_like_table_text(result: DecodeResult, allow_empty: bool = False) -> bool:
    if not result.terminated or result.raw_count:
        return False
    clean = visible_text(result.text)
    if allow_empty and not clean:
        return True
    return bool(clean)


def looks_like_manual_range_text(result: DecodeResult) -> bool:
    if not looks_like_table_text(result):
        return False
    clean = visible_text(result.text)
    ascii_letters = sum(1 for char in clean if char.isascii() and char.isalpha())
    return ascii_letters > 0


def looks_like_pointer_text(result: DecodeResult) -> bool:
    if not result.terminated or result.raw_count:
        return False
    if result.byte_length < 3 or result.byte_length > DEFAULT_MAX_TEXT_LENGTH:
        return False

    clean = visible_text(result.text)
    if len(clean) < 2:
        return False
    if _mostly_padding_or_symbols(clean):
        return False
    letters = sum(1 for char in clean if char.isalpha())
    ascii_letters = sum(1 for char in clean if char.isascii() and char.isalpha())
    digits = sum(1 for char in clean if char.isdigit())
    if letters + digits < 2:
        return False
    if ascii_letters < 1:
        return False
    if len(clean) >= 8 and ascii_letters / max(1, len(clean)) < 0.25:
        return False
    return True


def _mostly_padding_or_symbols(text: str) -> bool:
    meaningful = sum(1 for char in text if char.isalnum())
    return meaningful / max(1, len(text)) < 0.35


def score_name_candidate(result: DecodeResult) -> int:
    if not result.terminated or result.raw_count:
        return -10_000
    clean = visible_text(result.text)
    if not clean:
        return -100
    letters = sum(1 for char in clean if char.isalpha())
    spaces = clean.count(" ")
    controls = result.control_count
    leading_penalty = 12 if clean[0].islower() else 0
    return letters * 4 + spaces + controls - leading_penalty


def decode_slot(rom: bytes, offset: int, size: int) -> DecodeResult:
    return decode_pcs(rom[offset : offset + size], 0, size)


def best_substring_slot(rom: bytes, offset: int, size: int) -> tuple[int, DecodeResult]:
    best_delta = 0
    best_result = decode_slot(rom, offset, size)
    best_score = score_name_candidate(best_result)
    for delta in range(1, size):
        result = decode_slot(rom, offset + delta, size - delta)
        score = score_name_candidate(result)
        if score > best_score:
            best_delta = delta
            best_result = result
            best_score = score
    return offset + best_delta, best_result


def make_entry(
    entry_id: str,
    category: str,
    address: int,
    result: DecodeResult,
    byte_length: int,
    is_pointer_based: bool,
    pointer_sources: list[int] | None = None,
    table_name: str | None = None,
    table_index: int | None = None,
) -> dict:
    entry = {
        "id": entry_id,
        "category": category,
        "address": format_offset(address),
        "pointer_sources": [format_offset(source) for source in pointer_sources or []],
        "original": hma_quote(result.text),
        "byte_length": byte_length,
        "is_pointer_based": is_pointer_based,
    }
    if table_name is not None:
        entry["table_name"] = table_name
    if table_index is not None:
        entry["table_index"] = table_index
    if no_relocation_pointer_sources(pointer_sources or []):
        entry["no_relocation"] = True
    return entry


def no_relocation_pointer_sources(pointer_sources: list[int]) -> bool:
    for source in pointer_sources:
        for start, end in NO_RELOCATION_POINTER_SOURCE_RANGES:
            if start <= source < end:
                return True
    return False


def pointer_text_category(target: int) -> str:
    if target in PLAIN_SCRIPT_TEXT_ADDRESSES:
        return "plain_scripts"
    for start, end in PLAIN_SCRIPT_TEXT_RANGES:
        if start <= target < end:
            return "plain_scripts"
    return "scripts"


def extract_fixed_table(
    rom: bytes,
    table: FixedTable,
    next_table_id: int,
    known_targets: set[int],
    known_pointer_sources: set[int],
) -> tuple[list[dict], int]:
    entries = []
    stride = table.stride or table.slot_size

    for index in range(table.count):
        slot = table.start + index * stride
        target = None
        pointer_sources: list[int] = []
        byte_length = table.slot_size
        is_pointer_based = False

        if table.pointer_name:
            target = pointer_at(rom, slot)
            if target is not None:
                result = decode_pcs(rom, target, DEFAULT_MAX_TEXT_LENGTH)
                if looks_like_table_text(result):
                    pointer_sources = [slot]
                    known_pointer_sources.add(slot)
                    byte_length = result.byte_length
                    is_pointer_based = True
                else:
                    target = None

        if target is None:
            if table.substring_name:
                target, result = best_substring_slot(rom, slot, table.slot_size)
                byte_length = table.slot_size - (target - slot)
            else:
                target = slot
                result = decode_slot(rom, slot, table.slot_size)
                byte_length = table.slot_size

        known_targets.add(target)
        entries.append(
            make_entry(
                f"tbl_{table.category}_{next_table_id:05d}",
                table.category,
                target,
                result,
                byte_length,
                is_pointer_based,
                pointer_sources,
                table.table_name,
                index,
            )
        )
        next_table_id += 1

    return entries, next_table_id


def extract_sequential_table(
    rom: bytes,
    table: SequentialTable,
    next_table_id: int,
    known_targets: set[int],
) -> tuple[list[dict], int]:
    entries = []
    cursor = table.start
    for index in range(table.count):
        result = decode_pcs(rom, cursor, DEFAULT_MAX_TEXT_LENGTH)
        known_targets.add(cursor)
        entries.append(
            make_entry(
                f"tbl_{table.category}_{next_table_id:05d}",
                table.category,
                cursor,
                result,
                result.byte_length,
                False,
                [],
                table.table_name,
                index,
            )
        )
        cursor += max(result.byte_length, 1)
        next_table_id += 1
    return entries, next_table_id


def extract_pointer_table(
    rom: bytes,
    table: PointerTable,
    next_table_id: int,
    known_targets: set[int],
    known_pointer_sources: set[int],
) -> tuple[list[dict], int]:
    entries = []
    for index in range(table.count):
        source = table.start + index * 4
        target = pointer_at(rom, source)
        known_pointer_sources.add(source)
        if target is None:
            result = DecodeResult("", 0, False, raw_count=1)
            target = 0
            byte_length = 0
        else:
            result = decode_pcs(rom, target, DEFAULT_MAX_TEXT_LENGTH)
            byte_length = result.byte_length
            known_targets.add(target)

        entries.append(
            make_entry(
                f"tbl_{table.category}_{next_table_id:05d}",
                table.category,
                target,
                result,
                byte_length,
                True,
                [source] if target else [],
                table.table_name,
                index,
            )
        )
        next_table_id += 1
    return entries, next_table_id


def extract_manual_tables(
    rom: bytes,
    next_table_id: int,
    known_targets: set[int],
    known_pointer_sources: set[int],
    manual_ranges: list[ManualTextRange] | None = None,
    include_tables: bool = True,
) -> tuple[list[dict], int]:
    entries = []
    if manual_ranges is None:
        manual_ranges = MANUAL_TEXT_RANGES

    if include_tables:
        for category, (table_name, addresses) in MANUAL_TEXT_TABLES.items():
            for index, address in enumerate(addresses):
                result = decode_pcs(rom, address, DEFAULT_MAX_TEXT_LENGTH)
                known_targets.add(address)
                pointer_sources = find_pointer_sources(rom, address)
                known_pointer_sources.update(pointer_sources)
                entries.append(
                    make_entry(
                        f"tbl_{category}_{next_table_id:05d}",
                        category,
                        address,
                        result,
                        result.byte_length,
                        bool(pointer_sources),
                        pointer_sources,
                        table_name,
                        index,
                    )
                )
                next_table_id += 1

    for manual_range in manual_ranges:
        cursor = manual_range.start
        index = 0
        while cursor < manual_range.end:
            if cursor in known_targets:
                result = decode_pcs(rom, cursor, DEFAULT_MAX_TEXT_LENGTH)
                cursor += max(result.byte_length, 1)
                continue
            result = decode_pcs(rom, cursor, manual_range.end - cursor)
            if not looks_like_manual_range_text(result):
                cursor += 1
                continue
            known_targets.add(cursor)
            pointer_sources = find_pointer_sources(rom, cursor)
            known_pointer_sources.update(pointer_sources)
            entries.append(
                make_entry(
                    f"tbl_{manual_range.category}_{next_table_id:05d}",
                    manual_range.category,
                    cursor,
                    result,
                    result.byte_length,
                    bool(pointer_sources),
                    pointer_sources,
                    manual_range.table_name,
                    index,
                )
            )
            cursor += max(result.byte_length, 1)
            next_table_id += 1
            index += 1
    return entries, next_table_id


def scan_pointer_texts(
    rom: bytes,
    known_targets: set[int],
    known_pointer_sources: set[int],
    min_target: int,
    max_length: int,
    start_index: int,
    all_pointers: bool = False,
) -> tuple[list[dict], Counter]:
    sources_by_target: dict[int, list[int]] = defaultdict(list)
    stats = Counter()

    for source in range(0, len(rom) - 3):
        if source in known_pointer_sources:
            continue
        if not all_pointers and not is_script_text_pointer_source(rom, source):
            continue
        target = pointer_at(rom, source)
        if target is None:
            continue
        stats["raw_pointers"] += 1
        if target < min_target or target in known_targets:
            continue
        sources_by_target[target].append(source)

    entries = []
    script_index = 0
    for target in sorted(sources_by_target):
        result = decode_pcs(rom, target, max_length)
        if not looks_like_pointer_text(result):
            stats["rejected_targets"] += 1
            continue
        entries.append(
            make_entry(
                f"scr_{start_index + script_index:05d}",
                pointer_text_category(target),
                target,
                result,
                result.byte_length,
                True,
                sources_by_target[target],
            )
        )
        script_index += 1
    stats["accepted_targets"] = len(entries)
    stats["accepted_pointer_sources"] = sum(len(entry["pointer_sources"]) for entry in entries)
    return entries, stats


def is_script_text_pointer_source(rom: bytes, source: int) -> bool:
    if source >= 2 and rom[source - 2] == 0x0F and rom[source - 1] <= 0x03:
        return True
    # Unbound also uses script/menu opcode 0x67 followed directly by a text
    # pointer for some late-game systems, including intro character setup.
    # Restrict this broader pattern to the high script bank to avoid random
    # code/data pointers that happen to be preceded by 0x67.
    return source >= 1 and rom[source - 1] == 0x67 and (source >> 20) == 0x1E


def scan_orphan_texts(
    rom: bytes,
    occupied_starts: set[int],
    min_target: int,
    max_length: int,
    start_index: int,
) -> tuple[list[dict], Counter]:
    entries = []
    stats = Counter()
    cursor = min_target

    while cursor < len(rom):
        if cursor in occupied_starts:
            cursor += 1
            continue
        result = decode_pcs(rom, cursor, max_length)
        if looks_like_pointer_text(result):
            entries.append(
                make_entry(
                    f"orphan_{start_index + len(entries):05d}",
                    "orphan_texts",
                    cursor,
                    result,
                    result.byte_length,
                    False,
                    [],
                )
            )
            cursor += max(result.byte_length, 1)
            continue
        stats["rejected_offsets"] += 1
        cursor += 1

    stats["accepted_orphans"] = len(entries)
    return entries, stats


def entry_ranges(entries: list[dict]) -> tuple[dict[int, dict], list[tuple[int, int, dict]]]:
    by_start = {}
    ranges = []
    for entry in entries:
        try:
            start = int(entry.get("address", ""), 16)
            length = int(entry.get("byte_length") or 0)
        except (TypeError, ValueError):
            continue
        by_start[start] = entry
        if length > 0:
            ranges.append((start, start + length, entry))
    return by_start, ranges


def menu_audit_case_variants(text: str) -> list[str]:
    variants = [text]
    if text.upper() != text:
        variants.append(text.upper())
    titled = text.title().replace("Pokémon", "Pokémon").replace("PokéMon", "Pokémon")
    if titled not in variants:
        variants.append(titled)
    return list(dict.fromkeys(variants))


def load_menu_audit_strings(extra_strings: list[str] | None, strings_file: str | None) -> list[str]:
    strings = list(DEFAULT_MENU_AUDIT_STRINGS)
    if extra_strings:
        strings.extend(extra_strings)
    if strings_file:
        for line in Path(strings_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                strings.append(line)
    return list(dict.fromkeys(strings))


def classify_audit_hit(
    offset: int,
    by_start: dict[int, dict],
    ranges: list[tuple[int, int, dict]],
) -> tuple[str, dict | None]:
    direct = by_start.get(offset)
    if direct is not None:
        return "found_and_extracted", direct
    for start, end, entry in ranges:
        if start <= offset < end:
            return "found_and_extracted", entry
    return "found_but_not_extracted", None


def find_encoded_hits(rom: bytes, encoded: bytes) -> list[int]:
    hits = []
    cursor = 0
    while True:
        offset = rom.find(encoded, cursor)
        if offset == -1:
            return hits
        hits.append(offset)
        cursor = offset + 1


def audit_menu_text(
    rom: bytes,
    rom_path: Path,
    output_path: Path,
    entries: list[dict],
    *,
    extra_strings: list[str] | None = None,
    strings_file: str | None = None,
    no_case_variants: bool = False,
    max_hits_per_string: int = 50,
    preview_bytes: int = 120,
) -> dict:
    by_start, ranges = entry_ranges(entries)
    charmap = Charmap()
    report = {
        "rom": str(rom_path),
        "extracted": str(output_path),
        "strings": [],
        "summary": {},
    }
    totals = Counter()

    for audit_text in load_menu_audit_strings(extra_strings, strings_file):
        variants = [audit_text] if no_case_variants else menu_audit_case_variants(audit_text)
        seen_offsets = set()
        hits = []
        for variant in variants:
            if 0 <= max_hits_per_string <= len(hits):
                break
            encoded = charmap.encode(variant)[:-1]
            if not encoded:
                continue
            for offset in find_encoded_hits(rom, encoded):
                if 0 <= max_hits_per_string <= len(hits):
                    break
                if offset in seen_offsets:
                    continue
                seen_offsets.add(offset)
                status, entry = classify_audit_hit(offset, by_start, ranges)
                hit = {
                    "offset": format_offset(offset),
                    "variant": variant,
                    "status": status,
                    "preview": decode_pcs(rom, offset, preview_bytes).text,
                }
                if entry is not None:
                    hit["entry_id"] = entry.get("id")
                    hit["category"] = entry.get("category")
                    hit["entry_address"] = entry.get("address")
                hits.append(hit)
                totals[status] += 1

        if hits:
            string_status = (
                "found_but_not_extracted"
                if any(hit["status"] == "found_but_not_extracted" for hit in hits)
                else "found_and_extracted"
            )
        else:
            string_status = "not_found_as_pcs_text"
            totals[string_status] += 1

        report["strings"].append(
            {
                "text": audit_text,
                "status": string_status,
                "hits": hits,
            }
        )

    report["summary"] = dict(totals)
    return report


def print_menu_audit_report(report: dict) -> None:
    print("Menu audit:")
    for key, value in report["summary"].items():
        print(f"  {key}: {value}")
    for item in report["strings"]:
        print(f"{item['text']}: {item['status']}")
        if item["status"] == "not_found_as_pcs_text":
            print("  likely graphical/tile text, compressed data, or custom UI encoding")
            continue
        for hit in item["hits"]:
            entry = ""
            if hit["status"] == "found_and_extracted":
                entry = f" -> {hit.get('entry_id')} ({hit.get('category')})"
            preview = hit["preview"].replace("\n", "\\n")
            print(f"  {hit['offset']} [{hit['variant']}]: {hit['status']}{entry}: {preview}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Pokemon Unbound text JSON without Meowth."
    )
    parser.add_argument("rom", nargs="?", default="unbound.gba", help="Source GBA ROM")
    parser.add_argument(
        "-o",
        "--output",
        default="unbound-texts-extracted.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--min-pointer-target",
        default=hex(DEFAULT_MIN_POINTER_TARGET),
        help="Lowest ROM offset accepted for generic pointer text",
    )
    parser.add_argument(
        "--max-text-length",
        type=lambda value: int(value, 0),
        default=DEFAULT_MAX_TEXT_LENGTH,
        help="Maximum bytes to read for one pointer/orphan string",
    )
    parser.add_argument(
        "--include-orphans",
        action="store_true",
        help="Also scan unreferenced terminated text runs. This is noisy but useful for audits.",
    )
    parser.add_argument(
        "--all-pointers",
        action="store_true",
        help="Scan every GBA pointer instead of only script loadpointer sources. This is very noisy.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Use 0 for compact output.",
    )
    parser.add_argument(
        "--audit-menu-text",
        action="store_true",
        help="After extraction, audit common menu/UI strings against the extracted entries.",
    )
    parser.add_argument(
        "--audit-string",
        dest="audit_strings",
        action="append",
        help="Additional menu/UI string to audit. May be passed multiple times.",
    )
    parser.add_argument(
        "--audit-strings-file",
        help="UTF-8 text file with one additional audit string per line.",
    )
    parser.add_argument(
        "--audit-no-case-variants",
        action="store_true",
        help="Audit only exact spellings instead of also checking uppercase/titlecase variants.",
    )
    parser.add_argument(
        "--audit-max-hits-per-string",
        type=int,
        default=50,
        help="Maximum audit hits to print per string. Use -1 for unlimited.",
    )
    parser.add_argument(
        "--audit-preview-bytes",
        type=int,
        default=120,
        help="Maximum bytes to decode for each menu audit hit preview.",
    )
    parser.add_argument(
        "--audit-output",
        help="Optional path for a machine-readable menu audit JSON report.",
    )
    args = parser.parse_args()

    rom_path = Path(args.rom)
    output_path = Path(args.output)
    rom = rom_path.read_bytes()
    min_pointer_target = int(args.min_pointer_target, 0)

    known_targets: set[int] = set()
    known_pointer_sources: set[int] = set()
    entries: list[dict] = []
    next_table_id = 0

    for table in FIXED_TABLES:
        table_entries, next_table_id = extract_fixed_table(
            rom, table, next_table_id, known_targets, known_pointer_sources
        )
        entries.extend(table_entries)

    for table in SEQUENTIAL_TABLES:
        table_entries, next_table_id = extract_sequential_table(
            rom, table, next_table_id, known_targets
        )
        entries.extend(table_entries)

    for table in POINTER_TABLES:
        table_entries, next_table_id = extract_pointer_table(
            rom, table, next_table_id, known_targets, known_pointer_sources
        )
        entries.extend(table_entries)

    table_entries, next_table_id = extract_manual_tables(
        rom, next_table_id, known_targets, known_pointer_sources
    )
    entries.extend(table_entries)

    script_entries, pointer_stats = scan_pointer_texts(
        rom,
        known_targets,
        known_pointer_sources,
        min_pointer_target,
        args.max_text_length,
        next_table_id,
        args.all_pointers,
    )
    entries.extend(script_entries)
    next_table_id += len(script_entries)

    table_entries, next_table_id = extract_manual_tables(
        rom,
        next_table_id,
        known_targets,
        known_pointer_sources,
        POST_POINTER_MANUAL_TEXT_RANGES,
        include_tables=False,
    )
    entries.extend(table_entries)

    orphan_stats = Counter()
    if args.include_orphans:
        occupied_starts = {int(entry["address"], 16) for entry in entries if entry["byte_length"]}
        orphan_entries, orphan_stats = scan_orphan_texts(
            rom,
            occupied_starts,
            min_pointer_target,
            args.max_text_length,
            len(script_entries),
        )
        entries.extend(orphan_entries)

    output = {"entries": entries}
    if args.indent == 0:
        text = json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(output, ensure_ascii=False, indent=args.indent) + "\n"
    output_path.write_text(text, encoding="utf-8")

    counts = Counter(entry["category"] for entry in entries)
    print(f"ROM: {rom_path}")
    print(f"Output: {output_path}")
    print(f"Entries: {len(entries)}")
    for category, count in counts.most_common():
        print(f"{category}: {count}")
    print(f"Pointer candidates: {pointer_stats['raw_pointers']}")
    print(f"Pointer text accepted: {pointer_stats['accepted_targets']}")
    print(f"Pointer text rejected: {pointer_stats['rejected_targets']}")
    if args.include_orphans:
        print(f"Orphan text accepted: {orphan_stats['accepted_orphans']}")
    if args.audit_menu_text:
        audit_report = audit_menu_text(
            rom,
            rom_path,
            output_path,
            entries,
            extra_strings=args.audit_strings,
            strings_file=args.audit_strings_file,
            no_case_variants=args.audit_no_case_variants,
            max_hits_per_string=args.audit_max_hits_per_string,
            preview_bytes=args.audit_preview_bytes,
        )
        print_menu_audit_report(audit_report)
        if args.audit_output:
            Path(args.audit_output).write_text(
                json.dumps(audit_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
