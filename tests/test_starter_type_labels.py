import json
from pathlib import Path

READY_ITALIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
READY_INDONESIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "id.json"

# Starter-selection type labels (includes Larvitar/Rock, Beldum/Steel, Gible/Dragon).
STARTER_TYPE_SCRIPT_IDS = {
    "scr_1F97830": "Normal",
    "scr_1F97837": "Fighting",
    "scr_1F97840": "Flying",
    "scr_1F97847": "Poison",
    "scr_1F9784E": "Ground",
    "scr_1F97855": "Rock",
    "scr_1F9785A": "Bug",
    "scr_1F9785E": "Ghost",
    "scr_1F97864": "Steel",
    "scr_1F9786A": "Fire",
    "scr_1F9786F": "Water",
    "scr_1F97875": "Grass",
    "scr_1F9787B": "Electric",
    "scr_1F97884": "Psychic",
    "scr_1F9788C": "Ice",
    "scr_1F97890": "Dragon",
    "scr_1F97897": "Dark",
    "scr_1F9789C": "Fairy",
}

EXPECTED_ITALIAN = {
    "Normal": "Normale",
    "Fighting": "Lotta",
    "Flying": "Volante",
    "Poison": "Veleno",
    "Ground": "Terra",
    "Rock": "Roccia",
    "Bug": "Coleottero",
    "Ghost": "Spettro",
    "Steel": "Acciaio",
    "Fire": "Fuoco",
    "Water": "Acqua",
    "Grass": "Erba",
    "Electric": "Elettro",
    "Psychic": "Psichico",
    "Ice": "Ghiaccio",
    "Dragon": "Drago",
    "Dark": "Buio",
    "Fairy": "Folletto",
}

EXPECTED_INDONESIAN = {
    "Normal": "Normal",
    "Fighting": "Petarung",
    "Flying": "Terbang",
    "Poison": "Racun",
    "Ground": "Tanah",
    "Rock": "Batu",
    "Bug": "Serangga",
    "Ghost": "Hantu",
    "Steel": "Baja",
    "Fire": "Api",
    "Water": "Air",
    "Grass": "Rumput",
    "Electric": "Listrik",
    "Psychic": "Psikis",
    "Ice": "Es",
    "Dragon": "Naga",
    "Dark": "Gelap",
    "Fairy": "Peri",
}


def _entries_by_id(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in data["entries"]}


def test_starter_selection_type_labels_are_translated_italian():
    entries = _entries_by_id(READY_ITALIAN)
    for entry_id, source in STARTER_TYPE_SCRIPT_IDS.items():
        entry = entries[entry_id]
        assert entry["translation_source"] == source
        assert entry["translated"] == EXPECTED_ITALIAN[source]


def test_starter_selection_type_labels_are_translated_indonesian():
    """Regression for #11: Beldum (Steel) and Larvitar (Rock) stayed English."""
    entries = _entries_by_id(READY_INDONESIAN)
    for entry_id, source in STARTER_TYPE_SCRIPT_IDS.items():
        entry = entries[entry_id]
        assert entry["translation_source"] == source
        assert entry["translated"] == EXPECTED_INDONESIAN[source]
        if source in {"Rock", "Steel", "Dragon"}:
            # Dragon was already localized; Rock/Steel must not remain English.
            assert entry["translated"] != source or source == "Dragon"
            if source in {"Rock", "Steel"}:
                assert entry["translated"] != source
