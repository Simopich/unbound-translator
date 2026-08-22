import json
from pathlib import Path

import pytest

from lib.gen3_font import text_pixel_width
from lib.pcs_text import hma_quote
from lib.translation_tokens import semantic_token_counts, visible_width
from tests.helpers import load_script_module

READY_ITALIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
READY_INDONESIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "id.json"
READY_GERMAN = Path(__file__).resolve().parents[1] / "ready-translations" / "de.json"
FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "fixed_translation_overrides.json"
)
INJECTOR = load_script_module("005_hybrid_injector.py", "ready_translation_injector")
TRANSLATOR = load_script_module("003_llm_translate.py", "ready_translation_translator")
KNOWN_BINARY_FALSE_POSITIVES = {
    "scr_24019A",
    "scr_245EE0",
    "scr_246AE0",
}


def test_indonesian_is_supported_and_uses_current_ready_schema():
    assert TRANSLATOR.LANGUAGE_NAMES["id"] == "Indonesian"

    italian = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    indonesian = json.loads(READY_INDONESIAN.read_text(encoding="utf-8"))["entries"]
    assert len(indonesian) == len(italian)

    translated_fields = {"translated", "translated_fixed", "translated_controlfixed"}
    for expected, actual in zip(italian, indonesian, strict=True):
        expected_schema = {
            key: value for key, value in expected.items() if key not in translated_fields
        }
        actual_schema = {
            key: value for key, value in actual.items() if key not in translated_fields
        }
        assert actual_schema == expected_schema, actual["id"]

    translated = [entry for entry in indonesian if entry.get("translated")]
    assert len(translated) > 16_000

    charmap = INJECTOR.Charmap(target_lang="id")
    for entry in translated:
        source_tokens = semantic_token_counts(entry["original"])
        translated_tokens = semantic_token_counts(entry["translated"])
        for apostrophe_byte in ("{B3}", "{B4}"):
            source_tokens.pop(apostrophe_byte, None)
            translated_tokens.pop(apostrophe_byte, None)
        assert translated_tokens == source_tokens, entry["id"]

        encoded = INJECTOR.encode_text(
            charmap,
            entry["translated"],
            plain_script=entry.get("category") == "plain_scripts",
        )
        if entry.get("category") == "ability_descriptions":
            assert len(encoded) <= INJECTOR.ABILITY_DESCRIPTION_MAX_BYTES, entry["id"]
        if entry.get("no_relocation") or not INJECTOR.pointer_sources(entry):
            assert len(encoded) <= int(entry["byte_length"]), entry["id"]


def test_ready_italian_preserves_known_binary_pointer_false_positives():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    entries_by_id = {entry["id"]: entry for entry in entries}

    for entry_id in KNOWN_BINARY_FALSE_POSITIVES:
        entry = entries_by_id.get(entry_id)
        if entry is not None:
            assert hma_quote(entry["translated"]) == entry["original"]


def test_pokedex_unknown_fallback_stays_in_place_and_fits():
    italian = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    indonesian = json.loads(READY_INDONESIAN.read_text(encoding="utf-8"))["entries"]
    italian_entry = next(entry for entry in italian if entry["id"] == "scr_1A357CC")
    indonesian_entry = next(
        entry for entry in indonesian if entry["id"] == "scr_1A357CC"
    )

    assert italian_entry["no_relocation"] is True
    assert indonesian_entry["no_relocation"] is True
    assert italian_entry["translated"] == "Sconosciuto"
    assert italian_entry["translated_fixed"] == "Ignoto"
    assert len(INJECTOR.Charmap(target_lang="it").encode("Ignoto")) <= 8


def test_compact_translation_fixture_prefers_display_text_and_preserves_tokens():
    entries = json.loads(FIXTURE.read_text(encoding="utf-8"))["entries"]

    for entry in entries:
        assert INJECTOR.translation_for_injection(entry) == entry["translated_fixed"]
        assert semantic_token_counts(entry["translated_fixed"]) == semantic_token_counts(
            entry["translated"]
        )

    broken = dict(entries[0], translated_fixed="Attacca!")
    with pytest.raises(ValueError, match="changes protected tokens"):
        INJECTOR.translation_for_injection(broken)


def test_ready_italian_compact_overrides_are_lossless_and_fit():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    cmap = INJECTOR.Charmap(target_lang="it")
    checked = 0

    for entry in entries:
        fixed = entry.get("translated_fixed")
        if not fixed:
            continue

        checked += 1
        assert "\ufffd" not in fixed, entry["id"]
        assert semantic_token_counts(fixed) == semantic_token_counts(
            entry.get("translated", "")
        ), entry["id"]

        encoded = INJECTOR.encode_text(
            cmap,
            fixed,
            plain_script=entry.get("category") == "plain_scripts",
        )
        if entry.get("category") == "ability_descriptions":
            assert len(encoded) <= INJECTOR.ABILITY_DESCRIPTION_MAX_BYTES, entry["id"]
        if not INJECTOR.pointer_sources(entry):
            assert len(encoded) <= int(entry["byte_length"]), entry["id"]

    assert checked > 0


def test_ready_italian_ability_descriptions_fit_original_rom_layout_budget():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    cmap = INJECTOR.Charmap(target_lang="it")
    checked = 0

    for entry in entries:
        if entry.get("category") != "ability_descriptions":
            continue
        checked += 1
        text = INJECTOR.translation_for_injection(entry)
        lines = text.splitlines()
        assert len(lines) == 1, entry["id"]
        assert max(map(text_pixel_width, lines), default=0) <= 191, entry["id"]
        assert visible_width(text) <= 34, entry["id"]
        assert len(INJECTOR.encode_text(cmap, text)) <= 35, entry["id"]

    assert checked == 252


def test_misc_menu_text_respects_observed_screen_budgets():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]

    setting_name_entries = [
        entry
        for entry in entries
        if entry.get("category") == "setting_names"
    ]
    assert len(setting_name_entries) == 32
    setting_name_budget = max(
        text_pixel_width(entry["original"][1:-1]) for entry in setting_name_entries
    )
    assert setting_name_budget == 93
    assert max(text_pixel_width(entry["translated"]) for entry in setting_name_entries) <= setting_name_budget

    setting_description_entries = [
        entry
        for entry in entries
        if entry.get("category") == "menu_game_settings"
           and 0x1F4DD6D <= int(entry["address"], 16) <= 0x1F4E214
    ]
    assert len(setting_description_entries) == 36
    setting_descriptions = [entry["translated"] for entry in setting_description_entries]
    assert all("\n" not in text and "\\n" not in text for text in setting_descriptions)
    description_budget = max(
        text_pixel_width(entry["original"][1:-1])
        for entry in setting_description_entries
    )
    assert description_budget == 224
    assert max(map(text_pixel_width, setting_descriptions)) <= description_budget

    move_description_entries = [
        entry for entry in entries if entry.get("category") == "move_descriptions"
    ]
    move_description_lines = [
        line
        for entry in move_description_entries
        for line in entry["translated"].splitlines()
    ]
    assert max(len(entry["translated"].splitlines()) for entry in move_description_entries) <= 6
    assert move_description_lines
    assert max(map(text_pixel_width, move_description_lines)) <= 122

    summary_entries = [
        entry
        for entry in entries
        if entry.get("category") == "menu_pokemon_summary"
           and entry.get("table_index", 99) < 14
    ]
    assert len(summary_entries) == 14
    for entry in summary_entries:
        text = entry["translated"]
        assert text.startswith("Natura \\?00.")
        assert text.count("\\?00") == 1
    assert max(map(text_pixel_width, text.splitlines())) <= 154


def test_ready_german_settings_and_battle_text_respect_rendered_width_budgets():
    entries = json.loads(READY_GERMAN.read_text(encoding="utf-8"))["entries"]

    def rendered_lines(text):
        for token in ("\\pn", "\\p", "\\n", "\\l"):
            text = text.replace(token, "\n")
        return [line for line in text.splitlines() if line.strip()]

    for entry in entries:
        category = entry.get("category")
        effective = INJECTOR.translation_for_injection(entry)
        if category == "setting_names":
            assert text_pixel_width(effective) <= 93, entry["id"]
        elif category == "battle_messages":
            assert max(
                map(text_pixel_width, rendered_lines(effective)), default=0
            ) <= 208, entry["id"]
        elif category == "menu_game_settings":
            address = int(entry["address"], 16)
            if address == 0x1F4DA6C or 0x1F4DBA5 <= address <= 0x1F4DD5F:
                assert text_pixel_width(effective) <= 118, entry["id"]
            elif 0x1F4DD6D <= address <= 0x1F4E214:
                assert text_pixel_width(effective) <= 224, entry["id"]
        elif category == "mission_objectives":
            lines = rendered_lines(effective)
            assert "..." not in effective, entry["id"]
            assert len(lines) <= 2, entry["id"]
            assert max(map(visible_width, lines), default=0) <= 35, entry["id"]
            assert visible_width(" ".join(lines)) <= 65, entry["id"]


def test_ready_german_battle_fragments_keep_runtime_spaces_and_loss_text_german():
    entries = json.loads(READY_GERMAN.read_text(encoding="utf-8"))["entries"]
    by_id = {entry["id"]: entry for entry in entries}

    for entry_id in (
        "tbl_battle_messages_00000_A4C636",
        "tbl_battle_messages_00000_8BD155",
    ):
        assert INJECTOR.translation_for_injection(by_id[entry_id]).endswith(" ")

    for entry_id in (
        "tbl_battle_messages_00007_A4C689",
        "tbl_battle_messages_00009_A4C6FD",
        "tbl_battle_messages_00020_3FB433",
        "tbl_battle_messages_00022_3FB484",
        "scr_1A6197",
        "scr_1A61E5",
    ):
        text = INJECTOR.translation_for_injection(by_id[entry_id])
        assert "is out of" not in text
        assert "usable Pokémon" not in text
        assert "Player lost against" not in text

    for entry_id in (
        "tbl_battle_messages_00020_3FB433",
        "tbl_battle_messages_00022_3FB484",
        "scr_1A6197",
        "scr_1A61E5",
    ):
        assert "hat keine Pokémon mehr!" in INJECTOR.translation_for_injection(
            by_id[entry_id]
        )


def test_ready_german_wireless_status_slots_keep_dynamic_controls_and_fit():
    entries = json.loads(READY_GERMAN.read_text(encoding="utf-8"))["entries"]
    by_address = {entry["address"]: entry for entry in entries}
    expected = {
        "0x41E2B4": r"\?00 Spieler",
        "0x41E2BF": r"\?01 Spieler",
        "0x41E2C9": r"\?02 Spieler",
        "0x41E2D4": r"\?03 Spieler",
        "0x41E2EC": r"\btn01Zurück",
    }
    charmap = INJECTOR.Charmap(target_lang="de")

    for address, translation in expected.items():
        entry = by_address[address]
        effective = INJECTOR.translation_for_injection(entry)
        assert effective == translation
        assert semantic_token_counts(effective) == semantic_token_counts(
            entry["original"]
        )
        if not INJECTOR.pointer_sources(entry):
            assert len(INJECTOR.encode_text(charmap, effective)) <= int(
                entry["byte_length"]
            )


def test_german_battle_command_menus_preserve_choice_order_and_layout():
    entries = json.loads(READY_GERMAN.read_text(encoding="utf-8"))["entries"]
    by_id = {entry["id"]: entry for entry in entries}
    expected = {
        "tbl_menu_battle_00000_3FE725": (
            r"\CC0505\CC040D0E0FKampf\CC1338Beutel\n"
            r"Pokémon\CC1338Flucht"
        ),
        "tbl_menu_battle_00001_3FE747": (
            r"\CC0505\CC040D0E0FBall\CC1338Köder\n"
            r"Stein\CC1338Flucht"
        ),
        "tbl_menu_battle_00002_3FE791": r"\CC0505\CC040D0E0FJa\nNein",
        "tbl_menu_battle_00003_A4C7B7": (
            r"\CC0505\CC040D0E0FKampf\CC1338Cube\nPokémon\CC1338Flucht"
        ),
        "tbl_menu_battle_00004_A4C7DA": (
            r"\CC0505\CC040D0E0FKampf\CC1338\CC040F0E0BCube\n"
            r"\CC040D0E0FPokémon\CC1338Flucht"
        ),
        "tbl_menu_battle_00005_A4C807": (
            r"\CC0505\CC040D0E0FKampf\CC1338Cube\nPokémon\CC1338Zurück"
        ),
        "tbl_menu_battle_00006_A4C82B": (
            r"\CC0505\CC040D0E0FKampf\CC1338\CC040F0E0BCube\n"
            r"\CC040D0E0FPokémon\CC1338Zurück"
        ),
    }

    for entry_id, translation in expected.items():
        entry = by_id[entry_id]
        effective = INJECTOR.translation_for_injection(entry)
        assert effective == translation
        assert "Cube-" not in effective
        assert semantic_token_counts(effective) == semantic_token_counts(
            entry["original"]
        )


def test_verified_official_italian_terms_and_pokedex_layout():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    by_source = {
        (entry.get("category"), entry.get("translation_source")): entry
        for entry in entries
    }

    assert by_source[("move_names", "Clang Scales")]["translated"] == "Clamorsquame"
    assert by_source[("move_names", "Dark Lariat")]["translated"] == "Braccioteso"
    assert by_source[("move_names", "SmellingSalt")]["translated"] == "Maniereforti"
    assert by_source[("item_names", "Leek")]["translated"] == "Gambo"
    assert by_source[("ability_names", "As One")]["translated"] == "Sintonia Equina"
    assert by_source[("pokedex_species", "Tiny Turtle")]["translated"] == "Tartaghina"

    descriptions = [
        entry for entry in entries if entry.get("category") == "pokedex_descriptions"
    ]
    assert descriptions
    for entry in descriptions:
        lines = entry["translated"].splitlines()
        assert len(lines) <= 3, entry["id"]
        assert max(map(visible_width, lines)) <= 43, entry["id"]
        assert visible_width(" ".join(lines)) <= 124, entry["id"]


def test_game_setting_values_and_save_prompt_match_french_layout():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    by_id = {entry["id"]: entry for entry in entries}
    fixture_path = Path(__file__).parent / "fixtures" / "game_settings_layout.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    value_entries = [
        entry
        for entry in entries
        if entry.get("category") == "menu_game_settings"
        and (
            int(entry["address"], 16) == 0x1F4DA6C
            or 0x1F4DBA5 <= int(entry["address"], 16) <= 0x1F4DD5F
        )
    ]
    assert len(value_entries) == 30
    assert max(text_pixel_width(entry["translated"]) for entry in value_entries) <= fixture[
        "value_max_pixels"
    ]
    for entry_id, translated in fixture["values"].items():
        assert by_id[entry_id]["translated"] == translated

    prompt_fixture = fixture["save_prompt"]
    prompt = by_id[prompt_fixture["id"]]
    assert prompt["translated"] == prompt_fixture["translated"]
    assert semantic_token_counts(prompt["translated"]) == semantic_token_counts(
        prompt["original"]
    )
    prompt_lines = prompt["translated"].split("\\n")
    assert len(prompt_lines) == 2
    assert max(map(text_pixel_width, prompt_lines)) <= prompt_fixture["max_line_pixels"]


def test_natures_and_pokedex_controls_keep_safe_complete_ownership():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    by_id = {entry["id"]: entry for entry in entries}
    natures = [entry for entry in entries if entry.get("category") == "nature_names"]
    assert len(natures) == 25
    for index, entry in enumerate(natures):
        assert entry["pointer_sources"] == [
            f"0x{0x463E60 + 4 * index:X}",
            f"0x{0x1FE65F4 + 4 * index:X}",
        ]
        assert "translated_fixed" not in entry

    cmap = INJECTOR.Charmap(target_lang="it")
    compact_ids = {
        "scr_415D2C",
        "scr_415D48",
        "scr_415D50",
        "scr_415D60",
        "scr_415D78",
        "scr_415DB8",
        "scr_415DC4",
        "scr_415DCA",
        "scr_415DD7",
        "scr_415DE0",
        "scr_415E95",
        "scr_415EA4",
        "scr_415ED5",
        "scr_415F51",
        "scr_415F6C",
        "scr_415FB3",
        "scr_415FCF",
        "scr_416002",
        "scr_800FD0",
        "scr_A43AD4",
        "scr_A43B61",
        "tbl_menu_link_controls_00006_418E77",
        "tbl_menu_link_controls_00012_418EB5",
    }
    for entry_id in compact_ids:
        entry = by_id[entry_id]
        fixed = entry["translated_fixed"]
        assert semantic_token_counts(fixed) == semantic_token_counts(entry["translated"])
        assert len(INJECTOR.encode_text(cmap, fixed)) <= int(entry["byte_length"])

    cry = by_id["tbl_menu_pokedex_00000_415FAD"]
    assert cry["translated"] == "\\btn04Verso"
    assert cry["pointer_sources"] == ["0x105FE4", "0x1067B8"]
