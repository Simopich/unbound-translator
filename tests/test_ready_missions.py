import json
from pathlib import Path

from lib.gen3_font import text_pixel_width
from lib.pcs_text import Charmap

READY_ITALIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"


def test_route_8_trainer_messages_remain_in_place():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    route_8_ids = {"scr_1F66411", "scr_1F66449"}
    route_8_entries = [entry for entry in entries if entry["id"] in route_8_ids]

    assert {entry["id"] for entry in route_8_entries} == route_8_ids
    charmap = Charmap(target_lang="it")
    assert all(
        len(charmap.encode(entry["translated"])) <= entry["byte_length"]
        for entry in route_8_entries
    )


def test_ready_italian_covers_all_missions_without_overflow():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    names = [entry for entry in entries if entry["category"] == "mission_names"]
    descriptions = [
        entry for entry in entries if entry["category"] == "mission_descriptions"
    ]

    # 84 missions: Hero/Heroine have separate title strings; two side-mission
    # registrations share existing description records.
    assert len(names) == 85
    assert len(descriptions) == 82
    assert all(entry.get("translated") for entry in names + descriptions)

    for entry in descriptions:
        translated = entry["translated"]
        lines = translated.splitlines()
        assert len(lines) <= 3, entry["address"]
        assert max(map(text_pixel_width, lines), default=0) <= 172, entry["address"]
        assert "..." not in translated, entry["address"]
        assert "\\l" not in translated, entry["address"]
        assert "\\p" not in translated, entry["address"]
