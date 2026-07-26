import json
from pathlib import Path

from lib.pcs_text import hma_quote


READY_ITALIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
KNOWN_BINARY_FALSE_POSITIVES = {
    "scr_24019A",
    "scr_245EE0",
    "scr_246AE0",
}


def test_ready_italian_preserves_known_binary_pointer_false_positives():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    entries_by_id = {entry["id"]: entry for entry in entries}

    for entry_id in KNOWN_BINARY_FALSE_POSITIVES:
        entry = entries_by_id.get(entry_id)
        if entry is not None:
            assert hma_quote(entry["translated"]) == entry["original"]
