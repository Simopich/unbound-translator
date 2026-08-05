from __future__ import annotations

import json
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
        "mission_objective_wrap_width": 35,
        "mission_objective_max_lines": 2,
        "mission_objective_max_total": 65,
        "mission_description_max_pixels": 172,
        "mission_description_max_lines": 3,
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


def test_paragraph_before_indonesian_k_is_not_pokemon_glyph():
    fixed = controlfix.normalize_actual_layout_breaks("Pertama.\n\nkamu lanjut.")

    assert fixed == "Pertama.\\pnkamu lanjut."
    assert controlfix.Charmap(target_lang="id").encode(fixed) == controlfix.Charmap(
        target_lang="id"
    ).encode("Pertama.\n\nkamu lanjut.")


def test_paragraph_before_italian_n_preserves_first_letter():
    fixed = controlfix.normalize_actual_layout_breaks(
        "ottenere il pacco\n\nnecessario per la missione"
    )

    assert fixed == "ottenere il pacco\\pnnecessario per la missione"
    assert controlfix.Charmap(target_lang="it").encode(fixed) == controlfix.Charmap(
        target_lang="it"
    ).encode("ottenere il pacco\n\nnecessario per la missione")


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


def test_ready_trainer_change_prompt_uses_official_italian_wording():
    fixture_path = Path(__file__).parent / "fixtures" / "trainer_change_prompt.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    ready_path = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
    ready_entries = json.loads(ready_path.read_text(encoding="utf-8"))["entries"]
    ready_entry = next(entry for entry in ready_entries if entry["id"] == fixture["id"])

    assert ready_entry["translated"] == fixture["translated"]
    assert "\\p" in ready_entry["translated"]
    assert controlfix.controls_match(fixture["translated"], fixture["original"])


def test_ready_save_overwrite_prompts_use_official_italian_layout():
    fixture_path = Path(__file__).parent / "fixtures" / "save_overwrite_prompt.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    ready_path = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
    ready_entries = json.loads(ready_path.read_text(encoding="utf-8"))["entries"]
    ready_by_id = {entry["id"]: entry for entry in ready_entries}

    for entry_id in fixture["ids"]:
        assert ready_by_id[entry_id]["translated"] == fixture["translated"]


def test_ready_battle_send_out_messages_fit_fragile_original_slots():
    fixture_path = Path(__file__).parent / "fixtures" / "battle_send_out_messages.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    ready_path = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
    ready_entries = json.loads(ready_path.read_text(encoding="utf-8"))["entries"]
    ready_by_id = {entry["id"]: entry for entry in ready_entries}
    charmap = controlfix.Charmap()

    for fixture in fixtures:
        entry = ready_by_id[fixture["id"]]
        assert entry["translated"] == fixture["translated"]
        assert len(charmap.encode(entry["translated"])) <= entry["byte_length"]
        assert controlfix.controls_match(entry["translated"], entry["original"])


def test_ready_choice_scarf_uses_official_name_and_fits_slots():
    fixture_path = Path(__file__).parent / "fixtures" / "choice_scarf_item.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    ready_path = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
    ready_entries = json.loads(ready_path.read_text(encoding="utf-8"))["entries"]
    ready_by_id = {entry["id"]: entry for entry in ready_entries}
    charmap = controlfix.Charmap()

    for fixture in fixtures:
        entry = ready_by_id[fixture["id"]]
        assert entry["translated"] == fixture["translated"]
        assert len(charmap.encode(entry["translated"])) <= entry["byte_length"]
        assert controlfix.controls_match(entry["translated"], entry["original"])


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


def test_ready_constrained_text_is_meaningfully_condensed_without_added_ellipsis():
    fixture_path = Path(__file__).parent / "fixtures" / "condensed_layout_cases.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    ready_path = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
    entries = json.loads(ready_path.read_text(encoding="utf-8"))["entries"]
    by_id = {entry["id"]: entry for entry in entries}

    for fixture in fixtures:
        assert by_id[fixture["id"]]["translated"] == fixture["translated"]
        assert "..." not in fixture["translated"]
        assert "\u2026" not in fixture["translated"]

    budgets = {
        "pokedex_descriptions": (43, 3, 124),
        "mission_objectives": (35, 2, 65),
    }
    checked = {category: 0 for category in budgets}
    for entry in entries:
        category = entry.get("category")
        if category not in budgets:
            continue

        width, max_lines, max_total = budgets[category]
        translated = entry.get("translated", "")
        lines = translated.splitlines()
        checked[category] += 1

        if "..." not in entry.get("original", ""):
            assert "..." not in translated, entry["id"]
        if "\u2026" not in entry.get("original", ""):
            assert "\u2026" not in translated, entry["id"]
        assert len(lines) <= max_lines, entry["id"]
        assert max(map(controlfix.visible_width, lines), default=0) <= width, entry["id"]
        assert controlfix.visible_width(" ".join(lines)) <= max_total, entry["id"]

    assert checked == {
        "pokedex_descriptions": 993,
        "mission_objectives": 57,
    }


def test_mission_objective_uses_french_observed_shared_budget():
    wrapped, changed, _long_words, skipped = controlfix.wrap_translation(
        "Guardati intorno nel Magazzino Vivill e trova un modo per entrare nel Centro di Comando!",
        {"category": "mission_objectives", "table_index": 37},
        "Look around Vivill Warehouse and find a way into the Command Centre!",
        _args(),
        {"mission_objectives"},
    )

    lines = wrapped.splitlines()
    assert changed
    assert not skipped
    assert len(lines) <= 2
    assert max(map(controlfix.visible_width, lines)) <= 35
    assert controlfix.visible_width(" ".join(lines)) <= 65


def test_mission_log_description_uses_up_to_three_pixel_bounded_lines():
    wrapped, changed, _long_words, skipped = controlfix.wrap_translation(
        "Scopri i segreti dietro le misteriose tavolette di pietra!",
        {"category": "mission_descriptions", "table_index": 1},
        "Uncover the secrets behind the mysterious stone tablets!",
        _args(),
        {"mission_descriptions"},
    )

    lines = wrapped.splitlines()
    assert changed
    assert not skipped
    assert len(lines) <= 3
    assert max(map(controlfix.text_pixel_width, lines)) <= 172
    assert "..." not in wrapped


def test_mission_log_description_never_emits_scroll_or_page_controls():
    wrapped, _changed, _long_words, skipped = controlfix.wrap_translation(
        "Aiuta uno scienziato a conoscere i Pokémon che vivono nella Palude Cootes! Usa il DexNav per aiutarlo a catturarli tutti.",
        {"category": "mission_descriptions", "table_index": 4},
        "Help a scientist learn about the Pokémon living in Cootes Bog!",
        _args(),
        {"mission_descriptions"},
    )

    assert not skipped
    assert len(wrapped.splitlines()) <= 3
    assert "\\l" not in wrapped
    assert "\\p" not in wrapped
    assert max(map(controlfix.text_pixel_width, wrapped.splitlines())) <= 172


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
