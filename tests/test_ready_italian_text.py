import json
from pathlib import Path


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
