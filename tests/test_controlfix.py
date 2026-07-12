from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers import load_script_module

controlfix = load_script_module("004_controlfix_translations.py", "controlfix_under_test")


def _args(**overrides):
    values = {
        "no_wrap": False,
        "wrap_width": 12,
        "description_wrap_width": 12,
        "pokedex_description_wrap_width": 43,
        "pokedex_description_max_lines": 3,
        "pokedex_description_max_total": 124,
        "item_description_wrap_width": 14,
        "item_description_max_lines": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_repair_control_sequences_restores_required_prefix_tokens():
    original = "[black]Hello [player]!"
    translated = "Ciao [player]!"

    fixed, changed = controlfix.repair_control_sequences(translated, original)

    assert changed
    assert fixed == "[black]Ciao [player]!"
    assert controlfix.controls_match(fixed, original)


def test_normalize_and_repair_common_control_damage():
    assert controlfix.normalize_braced_controls("{[black]}Ciao {\\btn01}") == "[black]Ciao \\btn01"
    assert controlfix.repair_split_controls("\\nqoCiao\\pqc") == "\\qoCiao\\qc"
    assert controlfix.fix_apostrophes("l'amico d{B4}oro") == "l{B4}amico d{B4}oro"


def test_remove_excess_dynamic_name_keeps_possessive_position():
    fixed, changed = controlfix.remove_excess_name_tokens(
        "[player]PC di [player]", "[player]’s PC"
    )
    rival_fixed, rival_changed = controlfix.remove_excess_name_tokens(
        "[rival]Casa di [rival]", "[rival]’s house"
    )

    assert changed and rival_changed
    assert fixed == "PC di [player]"
    assert rival_fixed == "Casa di [rival]"


def test_pokedex_category_keeps_only_category_text():
    assert controlfix.normalize_pokedex_category("Pokémon Ratto") == ("Ratto", True)
    assert controlfix.normalize_pokedex_category("Ratto Pokémon") == ("Ratto", True)
    assert controlfix.normalize_pokedex_category("Ratto") == ("Ratto", False)


def test_short_battle_fragments_preserve_assembly_spaces():
    sharp, sharp_changed = controlfix.restore_short_battle_fragment_spacing(
        "di molto", "sharply ", {"category": "battle_messages"}
    )
    little, little_changed = controlfix.restore_short_battle_fragment_spacing(
        "poco!", " little!", {"category": "battle_messages"}
    )

    assert sharp_changed and little_changed
    assert sharp + "aumenta!" == "di molto aumenta!"
    assert little == " poco!"

    modifier, modifier_changed = controlfix.restore_short_battle_fragment_spacing(
        "di molto ",
        "sharply ",
        {"id": "tbl_battle_messages_00224_3FCB41", "category": "battle_messages"},
    )
    assert modifier_changed
    assert "aumenta" + modifier + "!" == "aumenta di molto!"


def test_wrap_translation_uses_dialogue_layout_for_scripts():
    wrapped, changed, long_words, skipped = controlfix.wrap_translation(
        "uno due tre quattro cinque sei",
        {"category": "scripts"},
        "Hello",
        _args(wrap_width=12),
        {"scripts"},
    )

    assert changed
    assert not skipped
    assert long_words == 0
    assert wrapped == "uno due tre\nquattro\\lcinque sei"


def test_wrap_translation_uses_plain_line_breaks_for_plain_scripts_and_descriptions():
    plain_wrapped, changed, _long_words, skipped = controlfix.wrap_translation(
        "uno due tre quattro cinque sei sette",
        {"category": "plain_scripts"},
        "Line one\nLine two",
        _args(wrap_width=12),
        {"plain_scripts"},
    )

    assert changed
    assert not skipped
    assert "\\l" not in plain_wrapped
    assert plain_wrapped.splitlines() == ["uno due tre", "quattro", "", "cinque sei", "sette"]

    item_wrapped, changed, _long_words, skipped = controlfix.wrap_translation(
        "cura ogni problema di stato del pokemon",
        {"category": "item_descriptions"},
        "Item description",
        _args(item_description_wrap_width=14, item_description_max_lines=0),
        {"item_descriptions"},
    )

    assert changed
    assert not skipped
    assert "\\l" not in item_wrapped
    assert item_wrapped == "cura ogni\nproblema di\nstato del\npokemon"


def test_pokedex_description_uses_french_observed_three_line_budget():
    text = (
        "La composizione delle sue cellule è simile a quella delle molecole "
        "d{B4}acqua. Di conseguenza, quando si scioglie nell{B4}acqua, non può essere visto."
    )
    wrapped, changed, _long_words, skipped = controlfix.wrap_translation(
        text,
        {"category": "pokedex_descriptions", "table_index": 133},
        "Source description",
        _args(),
        {"pokedex_descriptions"},
    )

    lines = wrapped.splitlines()
    assert changed
    assert not skipped
    assert len(lines) <= 3
    assert max(map(controlfix.visible_width, lines)) <= 43
    assert controlfix.visible_width(wrapped.replace("\n", " ")) <= 124
    assert "..." in wrapped


def test_menu_and_battle_layout_repairs():
    menu_text, menu_changed = controlfix.restore_compact_menu_line_breaks(
        "Sì No",
        "Yes\nNo",
        {"category": "menu_common"},
    )
    assert menu_changed
    assert menu_text == "Sì\nNo"

    battle_text, battle_changed = controlfix.restore_battle_prompt_layout(
        "Cosa farà \\\\12?",
        "What will \\\\12 do?",
        {"id": "tbl_battle_messages_00412_3FE6D5"},
    )
    assert battle_changed
    assert battle_text == "Cosa farà\n\\\\12?"

    repaired, changed = controlfix.restore_battle_prompt_layout(
        "Cosa deve fare\\n\n\\\\12?",
        "What will\n\\\\12 do?",
        {"id": "tbl_battle_messages_00412_3FE6D5"},
    )
    assert changed
    assert repaired == "Cosa deve fare\n\\\\12?"


def test_mission_and_start_menu_labels_are_trimmed_to_width():
    mission_text, mission_changed = controlfix.trim_mission_name("Missione lunghissima", 8)
    start_text, start_changed = controlfix.compact_start_menu_label(
        "Impostazioni lunghissime",
        {"category": "start_menu_labels"},
        "Settings",
        13,
    )

    assert mission_changed
    assert mission_text == "Missione"
    assert start_changed
    assert start_text == "Impostazioni"
