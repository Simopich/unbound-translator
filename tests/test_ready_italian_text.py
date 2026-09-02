import json
from pathlib import Path

from lib.gen3_font import text_pixel_width


ROOT = Path(__file__).resolve().parents[1]


def ready_entries():
    data = json.loads(
        (ROOT / "ready-translations" / "it.json").read_text(encoding="utf-8")
    )
    return {entry["id"]: entry for entry in data["entries"]}


def test_main_difficulty_names_are_consistent():
    entries = ready_entries()
    exact_labels = {
        "tbl_menu_game_settings_00016_75CE9A": "Facile",
        "scr_75CE9F": "Media",
        "tbl_menu_game_settings_00017_75CEA6": "Difficile",
        "scr_A4ED04": "Normale",
        "scr_A4ED0C": "Difficile",
        "scr_A4ED16": "Difficile/Normale",
        "scr_A4ED28": "Esperto",
        "scr_A4ED2F": "Folle",
        "scr_1F10621": "Difficile",
        "scr_1F1062B": "Facile",
        "scr_1F10630": "Normale",
        "scr_1F1063D": "Esperto",
        "scr_1F10644": "Folle",
    }

    for entry_id, expected in exact_labels.items():
        assert entries[entry_id]["translated"] == expected

    mode_text_ids = {
        "scr_1EDFE72",
        "scr_1EE0A84",
        "scr_1F0FD05",
        "scr_1F0FFA4",
        "scr_1F100B9",
        "scr_1F101AC",
        "scr_1F10323",
        "scr_1F10A07",
        "scr_1F2050C",
        "scr_1F20544",
        "scr_1F4E26F",
        "scr_1F4EA74",
        "scr_1F730E7",
        "scr_1F7471C",
    }
    forbidden = (
        "Easy",
        "Vaniglia",
        "Vanilla",
        "Difficult",
        "Expert",
        "Insane",
        "Insano",
        "Pazzo",
    )
    for entry_id in mode_text_ids:
        translated = entries[entry_id]["translated"]
        assert not any(term in translated for term in forbidden), (entry_id, translated)


def test_opening_intro_is_clear_and_keeps_paragraph_boundaries():
    entries = ready_entries()
    expected = {
        "scr_1F0F5A6": (
            "Benvenuto in Pokémon Unbound!\n\n"
            "Prima di iniziare, ricorda che\n"
            "questo fangame non ha scopo di\n"
            "lucro.\n\n"
            "Se hai pagato per ottenerlo,\n"
            "chiedi subito un rimborso!"
        ),
        "scr_1F0F64D": (
            "Nel mondo in cui stai per entrare,\n"
            "sarai l{B4}eroe di una grande\n"
            "avventura.\n\n"
            "Il mondo è vasto: esploralo con\n"
            "calma. Non c{B4}è alcuna fretta."
        ),
        "scr_1F0F6FA": (
            "Parla con le persone ed esamina\n"
            "ciò che trovi in città, lungo le\n"
            "strade e nelle grotte.\n\n"
            "Il mondo e i suoi abitanti sono\n"
            "vivi: cresceranno insieme a te."
        ),
        "scr_1F0F79C": (
            "Ora sei quasi pronto a entrare\n"
            "nella regione di Borrius!\n\n"
            "Ma prima\\."
        ),
    }

    for entry_id, translated in expected.items():
        assert entries[entry_id]["translated"] == translated
        assert "fangame on" not in translated
        assert all(len(line.replace("{B4}", "'")) <= 35 for line in translated.splitlines())


def test_dawn_stone_uses_only_the_structured_item_name_owner():
    entries = ready_entries()

    assert entries["tbl_item_names_00100_877330"]["translated"] == "Pietralbore"
    assert "scr_877326" not in entries


def test_item_names_fit_the_original_screen_width():
    entries = ready_entries()

    for entry in entries.values():
        if entry.get("category") != "item_names":
            continue
        displayed = entry.get("translated_fixed", entry.get("translated", ""))
        assert text_pixel_width(displayed) <= 95, (entry["id"], displayed)


def test_gendered_dialogue_fragments_are_all_translated():
    entries = ready_entries()
    fragments = [
        entry
        for entry in entries.values()
        if entry.get("category") == "gendered_dialogue_fragments"
    ]

    assert len(fragments) == 54
    for entry in fragments:
        assert entry["translated"]
        assert entry["translated"].casefold() != entry["translation_source"].casefold()
        assert entry["pointer_sources"]

    expected = {
        "him": "lui",
        "her": "lei",
        "he": "lui",
        "she": "lei",
        "boy": "ragazzo",
        "girl": "ragazza",
        "son": "figlio",
        "daughter": "figlia",
        "sir": "signore",
        "madam": "signora",
        "dudette": "amica",
    }
    for source, target in expected.items():
        matches = [
            entry for entry in fragments if entry["translation_source"] == source
        ]
        assert matches, source
        assert {entry["translated"] for entry in matches} == {target}


def test_gendered_buffers_do_not_force_masculine_italian_grammar():
    entries = ready_entries()

    assert "Sei il\n[buffer1]" not in entries["scr_7527C2"]["translated"]
    assert "questo\\lgiovane [buffer1]" not in entries["scr_1F30506"]["translated"]
    for entry_id in (
        "scr_1F9FC8C",
        "scr_1F9FEB1",
        "scr_1FA0DB8",
        "scr_1FA1057",
        "scr_1FA1088",
        "scr_1FA115F",
        "scr_1FA1372",
        "scr_1FA13F5",
        "scr_1FA1976",
        "scr_1FA1D24",
        "scr_1FA1E0C",
    ):
        translated = entries[entry_id]["translated"]
        assert "Mio [buffer1]" not in translated
        assert "mio [buffer1]" not in translated
        assert "il mio [buffer1]" not in translated


def test_elite_four_battlefield_condition_texts_are_valid_and_fit():
    from lib.pcs_text import Charmap

    cmap = Charmap()
    entries = ready_entries()

    expected_texts = {
        "scr_A4BE6E": (
            "È apparso un arcobaleno nel cielo\n"
            "sull{B4}intero campo di battaglia!\n\n"
            "Raddoppia la probabilità degli\n"
            "effetti secondari dei tipi Drago!"
        ),
        "scr_A4BC7A": (
            "I Pokémon pesanti hanno un vantaggio\n"
            "qui!\n\n"
            "Più un Pokémon è pesante, più sarà\n"
            "veloce!"
        ),
        "scr_A4BD34": (
            "Un velo oscuro avvolge il campo!\n\n"
            "I tipi Spettro subiscono metà danno\n"
            "quando hanno i PS al massimo!"
        ),
        "scr_A4BE21": "I folletti svolazzano sul campo!",
        "scr_A4BD98": (
            "Ma solo i tipi Spettro usano\n"
            "Salvaguardia sotto il velo oscuro!"
        ),
        "scr_A4BDDC": (
            "Ma solo i tipi Spettro creano un\n"
            "Sostituto sotto il velo oscuro!"
        ),
        "scr_A4BF8F": "L{B4}energia Dynamax ti circonda!",
        "scr_A4BBD2": (
            "Ventoincoda spira alle spalle\n"
            "dei tipi Volante!"
        ),
        "scr_A4BC03": (
            "\\\\13 levita grazie\n"
            "all{B4}elettromagnetismo!"
        ),
        "scr_A4C037": (
            "Mossa bloccata dal potere del\n"
            "Dynamax!"
        ),
    }

    for entry_id, expected in expected_texts.items():
        entry = entries[entry_id]
        translated = entry.get("translated_fixed", entry["translated"])
        assert translated == expected, (entry_id, translated)
        encoded = cmap.encode(translated)
        max_slot = entry["byte_length"]
        assert len(encoded) <= max_slot, (
            entry_id,
            f"{len(encoded)} bytes exceeds slot limit {max_slot}",
        )
        for line in translated.splitlines():
            if line:
                assert text_pixel_width(line) <= 208, (
                    entry_id,
                    f"Line {repr(line)} exceeds battle box width (width: {text_pixel_width(line)}px)",
                )


def test_trainer_classes_pointer_entries_are_valid():
    entries = ready_entries()
    tc_entries = [
        entry
        for entry in entries.values()
        if entry.get("category") == "trainer_classes"
    ]
    assert len(tc_entries) == 107
    expected_pointer_slots = {
        2: ("tbl_trainer_classes_00002_1F2CB7C", "Capo Luce della Rovina", ["0x23E572"]),
        14: ("tbl_trainer_classes_00014_1FAE6F4", "Scagnozzo", ["0x23E60E"]),
        22: ("tbl_trainer_classes_00022_1FA1EE4", "Scagnozzo", ["0x23E676"]),
        26: ("tbl_trainer_classes_00026_1FA1EF5", "Capo Ferrothorn Neri", ["0x23E6AA"]),
        30: ("tbl_trainer_classes_00030_1F949EC", "Asso del Parco", ["0x23E6DE"]),
        31: ("tbl_trainer_classes_00031_1FACB8D", "Membro", ["0x23E6EB"]),
        40: ("tbl_trainer_classes_00040_1EEA039", "Capopalestra di Sinnoh", ["0x23E760"]),
        46: ("tbl_trainer_classes_00046_1F2CB68", "Admin Luce della Rovina", ["0x23E7AE"]),
        47: ("tbl_trainer_classes_00047_1F2CB5A", "Recluta", ["0x23E7BB"]),
    }
    for slot_idx, (entry_id, expected_trans, expected_sources) in expected_pointer_slots.items():
        assert entry_id in entries, f"Missing {entry_id}"
        entry = entries[entry_id]
        assert entry["table_index"] == slot_idx
        assert entry["is_pointer_based"] is True
        assert entry["translated"] == expected_trans
        assert entry["pointer_sources"] == expected_sources


def test_science_society_trainer_names_are_set():
    entries = ready_entries()
    for tid in [341, 342, 466, 469, 470]:
        slot_addr = 0x23EACC + tid * 40
        entry_id = f"tbl_trainer_names_{tid:05d}_{slot_addr:06X}"
        assert entry_id in entries, f"Missing {entry_id}"
        assert entries[entry_id]["translated"] == "Soc.Scient."


def test_gem_boost_message_has_newline():
    entries = ready_entries()
    assert "scr_96CAE2" in entries
    trans = entries["scr_96CAE2"]["translated"]
    assert "\n" in trans
    assert trans == "\\\\16 ha potenziato\nla potenza di \\\\14!"


def test_totem_aura_message_is_translated():
    entries = ready_entries()
    assert "tbl_battle_messages_00000_9665B0" in entries
    entry = entries["tbl_battle_messages_00000_9665B0"]
    assert entry["is_pointer_based"] is True
    assert entry["pointer_sources"] == ["0x9662E1", "0x966319", "0x966377"]
    assert entry["translated"] == "L{B4}aura di \\\\13\nsi è risvegliata!"


def test_stat_quality_modifiers_are_translated():
    entries = ready_entries()
    for entry_id in [
        "tbl_battle_messages_00000_883590",
        "tbl_battle_messages_00001_8835A0",
        "tbl_battle_messages_00000_A4C603",
        "tbl_battle_messages_00001_A4C610",
    ]:
        assert entry_id in entries, f"Missing {entry_id}"
        assert entries[entry_id]["translated"] == " moltissimo"
        assert entries[entry_id]["translated"].startswith(" ")
