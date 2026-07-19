import json
from pathlib import Path

from lib.gen3_font import text_pixel_width

READY_ITALIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"


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
